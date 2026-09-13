"""`ourouler comparer` : combien de watts sépare deux vélos, **mesuré**.

La question du mainteneur, mot pour mot : « mon CLM va plus vite sur le plat
grâce aux prolongateurs, on doit pouvoir voir sur des segments identiques la
différence approximative ». Cette commande y répond sans modèle physique du
tout — ni CdA, ni Crr, ni vent, ni masse. Elle compare des moyennes.

La méthode tient en cinq lignes :

1. prendre les sorties extérieures de chaque vélo (cache + rattachement déjà
   établis par `inventaire`), telles que la calibration les prend déjà ;
2. les découper en tronçons de 200 m avec `calibration.echantillonner`, **sans
   archive météo** : le vent est inconnu, donc on ne comparera que ce qui est
   comparable ;
3. ne garder que les tronçons quasi plats (`|pente| ≤ pente_max`) où le
   capteur de puissance a parlé ;
4. ranger chaque tronçon dans la maille de ~30 m du terrain qui contient son
   milieu — la même clé que `apprentissage.routes`, donc les mêmes routes ;
5. ne retenir que les mailles roulées par **les deux** vélos, puis comparer la
   puissance moyenne par classe de vitesse de 2 km/h.

Ce que cette comparaison **n'est pas** : une mesure de CdA. Deux sorties sur
la même maille n'ont pas le même vent, pas la même fraîcheur, pas le même
sens de passage. En moyenne sur des milliers de tronçons, ces écarts se
compensent en partie ; ils ne s'annulent pas. Le chiffre rendu est une
différence à la louche, ce qui est exactement ce qui a été demandé, et le
nombre de tronçons de chaque côté est affiché pour qu'on sache ce qu'il vaut.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date

from ourouler.activites.cache import Cache
from ourouler.apprentissage.routes import cle_maille
from ourouler.config import Config
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique import calibration as calib

#: Pente maximale, en valeur absolue, d'un tronçon comparable. 1 % sur 200 m,
#: c'est deux mètres de dénivelé : à 30 km/h et 75 kg, une vingtaine de watts.
#: Au-delà, la comparaison mesurerait le terrain plutôt que le vélo.
PENTE_MAX_DEFAUT = 0.01

#: Bornes des classes de vitesse, en km/h. En dessous de 20, le cycliste
#: grimpe ou traîne ; au-delà de 40, il descend ou sprinte : ni l'un ni l'autre
#: ne dit quoi que ce soit de la position sur le vélo.
V_MIN_CLASSE_KMH = 20.0
V_MAX_CLASSE_KMH = 40.0
LARGEUR_CLASSE_KMH = 2.0

#: Classe citée dans la ligne de synthèse : l'allure d'un plat roulant.
V_SYNTHESE_KMH = 30.0


@dataclass(frozen=True)
class Troncon:
    """Un tronçon de 200 m comparable : où, à quelle vitesse, à quelle puissance."""

    cle: tuple[int, int]
    v_kmh: float
    puissance_w: float


@dataclass
class ClasseVitesse:
    """Ce que les deux vélos ont fait dans une tranche de 2 km/h."""

    v_min_kmh: float
    v_max_kmh: float
    puissances: dict[str, float | None] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)

    @property
    def libelle(self) -> str:
        return f"{self.v_min_kmh:.0f}-{self.v_max_kmh:.0f}"

    def difference(self, velo_a: str, velo_b: str) -> float | None:
        """`puissance(velo_b) − puissance(velo_a)`, ou `None` s'il manque un côté."""
        a, b = self.puissances.get(velo_a), self.puissances.get(velo_b)
        if a is None or b is None:
            return None
        return b - a

    @property
    def peuplee(self) -> bool:
        return all(self.puissances.get(nom) is not None for nom in self.puissances)


@dataclass
class Comparaison:
    """Le résultat complet, de quoi écrire le tableau comme le JSON."""

    velos: tuple[str, str]
    pente_max: float
    classes: list[ClasseVitesse] = field(default_factory=list)
    mailles: dict[str, int] = field(default_factory=dict)
    """Nombre de mailles distinctes roulées par chaque vélo, avant recoupement."""
    mailles_communes: int = 0
    troncons: dict[str, int] = field(default_factory=dict)
    """Tronçons retenus **après** recoupement des mailles."""
    sorties: dict[str, int] = field(default_factory=dict)

    def classe_a(self, v_kmh: float) -> ClasseVitesse | None:
        """La classe qui contient cette vitesse, ou `None` si elle est hors bornes."""
        for classe in self.classes:
            if classe.v_min_kmh <= v_kmh < classe.v_max_kmh:
                return classe
        return None


# --- cœur : des tronçons aux classes de vitesse -------------------------------


def troncons_comparables(
    activite,
    *,
    pente_max: float = PENTE_MAX_DEFAUT,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> list[Troncon]:
    """Les tronçons de 200 m d'une sortie qui se prêtent à la comparaison.

    `echantillonner` est appelée **sans archive** : le vent est alors inconnu
    et compté nul partout, ce qui ne coûte rien puisqu'aucun modèle n'est
    évalué ici. Les deux seuls filtres sont ceux demandés : tronçon quasi plat
    et puissance présente. En particulier, `retenu` n'est pas consulté — ses
    critères (accélération, deux premiers kilomètres) servent à ajuster un
    modèle d'équilibre, pas à comparer deux moyennes.
    """
    if not (pente_max >= 0):
        raise ErreurUtilisateur(
            f"comparer : --pente-max {pente_max} — une pente positive ou nulle est attendue"
        )
    retenus = []
    for e in calib.echantillonner(
        activite, [], ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
    ):
        if e.lat is None or e.lon is None:
            continue
        if e.puissance_w <= 0:
            continue
        if abs(e.pente) > pente_max:
            continue
        retenus.append(
            Troncon(
                cle=cle_maille(float(e.lat), float(e.lon)),
                v_kmh=e.v_ms * 3.6,
                puissance_w=e.puissance_w,
            )
        )
    return retenus


def bornes_classes() -> list[tuple[float, float]]:
    """(20, 22), (22, 24)… (38, 40)."""
    bornes = []
    v = V_MIN_CLASSE_KMH
    while v + LARGEUR_CLASSE_KMH <= V_MAX_CLASSE_KMH + 1e-9:
        bornes.append((v, v + LARGEUR_CLASSE_KMH))
        v += LARGEUR_CLASSE_KMH
    return bornes


def comparer(
    par_velo: dict[str, list[Troncon]],
    *,
    velos: tuple[str, str],
    pente_max: float = PENTE_MAX_DEFAUT,
) -> Comparaison:
    """Recoupe les mailles, puis compare la puissance moyenne par classe de vitesse.

    Le recoupement est le cœur de l'affaire : sans lui, on comparerait les
    routes autant que les vélos — le CLM sort les jours de plat roulant, le
    vélo de route les jours de vallons, et la différence de watts mesurerait
    surtout le choix du parcours.
    """
    premier, second = velos
    mailles = {nom: {t.cle for t in troncons} for nom, troncons in par_velo.items()}
    communes = mailles.get(premier, set()) & mailles.get(second, set())

    resultat = Comparaison(
        velos=velos,
        pente_max=pente_max,
        mailles={nom: len(cles) for nom, cles in mailles.items()},
        mailles_communes=len(communes),
    )
    gardes = {
        nom: [t for t in troncons if t.cle in communes] for nom, troncons in par_velo.items()
    }
    resultat.troncons = {nom: len(troncons) for nom, troncons in gardes.items()}

    for v_min, v_max in bornes_classes():
        classe = ClasseVitesse(v_min_kmh=v_min, v_max_kmh=v_max)
        for nom in velos:
            dedans = [t.puissance_w for t in gardes.get(nom, []) if v_min <= t.v_kmh < v_max]
            classe.n[nom] = len(dedans)
            classe.puissances[nom] = statistics.fmean(dedans) if dedans else None
        resultat.classes.append(classe)
    return resultat


# --- couche commande : c'est elle qui touche au cache -------------------------


def executer_comparer(args: argparse.Namespace, config: Config) -> int:
    """Exécute `ourouler comparer`. Code de sortie 0 si la comparaison a eu lieu."""
    noms = list(getattr(args, "velos", None) or [])
    if len(noms) != 2:
        raise ErreurUtilisateur(
            "comparer : --velos attend exactement deux noms de vélo, par exemple "
            "`--velos RCR BMC`"
        )
    if noms[0].casefold() == noms[1].casefold():
        raise ErreurUtilisateur(
            f"comparer : {noms[0]} et {noms[1]} sont le même vélo — il n'y a rien à comparer"
        )
    velos = [config.velo(nom) for nom in noms]
    pente_max = _pente_max(getattr(args, "pente_max", None))
    depuis = _date_option(getattr(args, "depuis", None), config.historique_depuis)

    cache = Cache(config.cache.dossier)
    par_velo: dict[str, list[Troncon]] = {}
    sorties: dict[str, int] = {}
    pannes: list[str] = []
    lues_une_fois: dict[str, object] = {}

    def relire(identifiant: str):
        """Relit une sortie **une seule fois** ; `None` si elle est illisible.

        Le choix des sorties (motif « multisport ») et leur découpe ont tous
        deux besoin du contenu : sans mémoïsation, chaque fichier serait
        analysé deux fois.
        """
        if identifiant not in lues_une_fois:
            try:
                lues_une_fois[identifiant] = cache.relire(identifiant)
            except (KeyError, ErreurUtilisateur, OSError) as e:
                lues_une_fois[identifiant] = None
                pannes.append(f"sortie {identifiant[:12]} illisible ({e})")
        return lues_une_fois[identifiant]

    for velo in velos:
        entrees = calib.sorties_calibrables(
            cache, config, velo, depuis=depuis, relire=relire
        )
        troncons: list[Troncon] = []
        lues = 0
        for entree in entrees:
            activite = relire(entree.identifiant)
            if activite is None:
                continue
            lues += 1
            troncons += troncons_comparables(
                activite,
                pente_max=pente_max,
                ftp_w=config.cycliste.ftp_w,
                vitesse_min_kmh=config.calibration.vitesse_min_kmh,
            )
        par_velo[velo.nom] = troncons
        sorties[velo.nom] = lues

    if not any(par_velo.values()):
        raise ErreurUtilisateur(
            f"comparer : aucun tronçon comparable pour {noms[0]} ou {noms[1]} depuis le "
            f"{depuis} — vérifier le rattachement au vélo (`ourouler inventaire`)"
        )

    resultat = comparer(
        par_velo, velos=(velos[0].nom, velos[1].nom), pente_max=pente_max
    )
    resultat.sorties = sorties
    for panne in pannes[:5]:
        print(f"ourouler : {panne}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(rendre_json(resultat, depuis), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(resultat, depuis))
    return 0


def _pente_max(valeur) -> float:
    if valeur is None:
        return PENTE_MAX_DEFAUT
    try:
        pente = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(
            f"--pente-max {valeur!r} : une pente en tangente est attendue (0,01 = 1 %)"
        ) from e
    if not (0 <= pente <= 1):
        raise ErreurUtilisateur(
            f"--pente-max {valeur!r} : une pente entre 0 et 1 est attendue (0,01 = 1 %)"
        )
    return pente


def _date_option(texte: str | None, defaut: date) -> date:
    if not texte:
        return defaut
    try:
        return date.fromisoformat(str(texte).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis {texte!r} : date AAAA-MM-JJ attendue") from e


# --- rendus -------------------------------------------------------------------


def rendre_texte(resultat: Comparaison, depuis: date) -> str:
    premier, second = resultat.velos
    lignes = [
        f"Comparaison {premier} / {second} — sur les seules routes roulées par les deux",
        f"Depuis le {depuis.isoformat()} : "
        + ", ".join(f"{nom} {resultat.sorties.get(nom, 0)} sortie(s)" for nom in resultat.velos),
        f"Tronçons de {calib.LONGUEUR_ECHANTILLON_M:.0f} m, "
        f"|pente| ≤ {resultat.pente_max * 100:.1f} %, puissance présente, vent inconnu",
        "Mailles de ~30 m : "
        + ", ".join(f"{nom} {resultat.mailles.get(nom, 0)}" for nom in resultat.velos)
        + f" — {resultat.mailles_communes} en commun",
        "Tronçons retenus après recoupement : "
        + ", ".join(f"{nom} {resultat.troncons.get(nom, 0)}" for nom in resultat.velos),
        "",
        f"  {'vitesse':<12}{premier:>9}{second:>9}{second + ' − ' + premier:>14}"
        f"{'n ' + premier:>9}{'n ' + second:>9}",
    ]
    for classe in resultat.classes:
        difference = classe.difference(premier, second)
        lignes.append(
            f"  {classe.libelle + ' km/h':<12}"
            f"{_watts(classe.puissances.get(premier)):>9}"
            f"{_watts(classe.puissances.get(second)):>9}"
            f"{_ecart(difference):>14}"
            f"{classe.n.get(premier, 0):>9}{classe.n.get(second, 0):>9}"
        )
    lignes.append("")
    lignes.append(_synthese(resultat))
    lignes.append(
        "Aucun modèle n'intervient ici : ce sont des moyennes de puissance mesurée. "
        "Le vent, la fraîcheur et le sens de passage diffèrent d'une sortie à l'autre "
        "— ils se compensent en partie, ils ne s'annulent pas."
    )
    return "\n".join(lignes)


def _synthese(resultat: Comparaison) -> str:
    """La ligne qui répond à la question posée, ou dit pourquoi elle ne peut pas."""
    premier, second = resultat.velos
    classe = resultat.classe_a(V_SYNTHESE_KMH)
    if classe is None:
        return f"À {V_SYNTHESE_KMH:g} km/h : hors des classes mesurées."
    difference = classe.difference(premier, second)
    n_premier, n_second = classe.n.get(premier, 0), classe.n.get(second, 0)
    if difference is None:
        return (
            f"À {V_SYNTHESE_KMH:g} km/h sur le plat : rien à dire — "
            f"{n_premier} tronçon(s) {premier}, {n_second} tronçon(s) {second} "
            f"dans la classe {classe.libelle} km/h."
        )
    return (
        f"À {V_SYNTHESE_KMH:g} km/h sur le plat (classe {classe.libelle} km/h) : "
        f"{second} − {premier} = {difference:+.0f} W "
        f"({n_premier + n_second} tronçons : {n_premier} {premier}, {n_second} {second})."
    )


def _watts(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.0f} W"


def _ecart(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:+.0f} W"


def rendre_json(resultat: Comparaison, depuis: date) -> dict:
    premier, second = resultat.velos
    classe = resultat.classe_a(V_SYNTHESE_KMH)
    return {
        "velos": list(resultat.velos),
        "depuis": depuis.isoformat(),
        "pente_max": resultat.pente_max,
        "longueur_troncon_m": calib.LONGUEUR_ECHANTILLON_M,
        "sorties": resultat.sorties,
        "mailles": resultat.mailles,
        "mailles_communes": resultat.mailles_communes,
        "troncons": resultat.troncons,
        "classes": [
            {
                "v_min_kmh": c.v_min_kmh,
                "v_max_kmh": c.v_max_kmh,
                "puissance_w": {
                    nom: (None if v is None else round(v, 1))
                    for nom, v in c.puissances.items()
                },
                "n": dict(c.n),
                "difference_w": (
                    None
                    if c.difference(premier, second) is None
                    else round(c.difference(premier, second), 1)
                ),
            }
            for c in resultat.classes
        ],
        "synthese": {
            "v_kmh": V_SYNTHESE_KMH,
            "classe": None if classe is None else classe.libelle,
            "difference_w": (
                None
                if classe is None or classe.difference(premier, second) is None
                else round(classe.difference(premier, second), 1)
            ),
            "n": {} if classe is None else dict(classe.n),
        },
        "modele_physique": False,
    }


__all__ = [
    "PENTE_MAX_DEFAUT",
    "V_SYNTHESE_KMH",
    "ClasseVitesse",
    "Comparaison",
    "Troncon",
    "bornes_classes",
    "comparer",
    "executer_comparer",
    "rendre_json",
    "rendre_texte",
    "troncons_comparables",
]

"""`ourouler comparer` : combien de km/h — et donc de watts — séparent deux vélos.

La question du mainteneur, mot pour mot : « mon CLM va plus vite sur le plat
grâce aux prolongateurs, on doit pouvoir voir sur des segments identiques la
différence approximative ». Cette commande y répond sans modèle physique du
tout — ni CdA, ni Crr, ni vent, ni masse. Elle compare des moyennes.

La première version comparait la **puissance à vitesse égale**, par classes de
2 km/h, sur toutes les mailles roulées par les deux vélos, arrêts et relances
compris. Elle rendait « BMC +6 W à 30 km/h », en contradiction avec la
calibration (−17 W) et avec ce que le mainteneur vit sur la route : une classe
de vitesse mélange le sprint de fin de ligne droite, la relance après un
carrefour et l'allure de croisière, et le vélo qui sort les jours de vallons y
pèse autant que celui qui sort les jours de plat.

Le schéma retenu (validé par le mainteneur le 13/09) mesure l'inverse — la
**vitesse à puissance égale** — sur des morceaux de route où la vitesse a un
sens, c'est-à-dire là où le cycliste roule vraiment :

1. découper chaque sortie en tronçons de 200 m avec `calibration.echantillonner`,
   **sans archive météo** : le vent est inconnu, donc on ne comparera que ce
   qui est comparable ;
2. ne garder que les tronçons **plats** (`|pente| ≤ pente_max`), **sans arrêt
   ni relance** (motifs `retenu`, `accélération`, `départ` — jamais « arrêt »
   ni « sans puissance ») et dont la puissance tombe dans la **zone** demandée
   (56-75 % de la FTP par défaut, l'endurance : ni la descente, ni l'effort) ;
3. les recoller en **séries consécutives** tant que la route reste **droite**
   (écart de cap d'un tronçon au suivant ≤ `cap_max`) ; une série est gardée si
   elle fait au moins `longueur_min` (500 m par défaut) ;
4. par série : vitesse moyenne (longueur / temps), puissance moyenne pondérée
   par la longueur, longueur ;
5. par vélo : vitesse médiane dans trois bandes de puissance égales à
   l'intérieur de la zone, puis la régression `vitesse = a + b · puissance`
   pondérée par la longueur, lue **au milieu de la zone**.

La différence de vitesse au milieu de la zone est la réponse en km/h ; divisée
par la pente de la régression du premier vélo (en km/h par watt), elle rend la
réponse en watts à vitesse égale — la formule est écrite dans la sortie.

Les mailles communes aux deux vélos ne sont plus un **filtre** : les séries
droites et plates d'un CLM et d'un vélo de route ne se superposent pas assez
pour qu'il en reste quelque chose. Leur nombre est affiché comme une
information : il dit à quel point les deux vélos ont roulé aux mêmes endroits.

Ce que cette comparaison **n'est pas** : une mesure de CdA. Deux séries n'ont
pas le même vent, pas la même fraîcheur, pas le même sens de passage. En
moyenne sur des centaines de séries, ces écarts se compensent en partie ; ils
ne s'annulent pas. Le chiffre rendu est une différence à la louche, ce qui est
exactement ce qui a été demandé, et le nombre de séries de chaque côté est
affiché pour qu'on sache ce qu'il vaut.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date

from ourouler.activites.cache import Cache
from ourouler.apprentissage.routes import cle_maille
from ourouler.boucle.trace import PointTrace, cap_deg, distance_m
from ourouler.config import Config
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique import calibration as calib

#: Pente maximale, en valeur absolue, d'un tronçon comparable. 0,8 % sur 200 m,
#: c'est un mètre et demi de dénivelé : à 30 km/h et 90 kg, une quinzaine de
#: watts. Au-delà, la comparaison mesurerait le terrain plutôt que le vélo.
PENTE_MAX_DEFAUT = 0.008

#: Écart de cap toléré d'un tronçon au suivant, en degrés. Au-delà, la route
#: tourne : le cycliste freine, se redresse, relance — sa vitesse ne dit plus
#: ce que vaut sa position sur le vélo.
CAP_MAX_DEG_DEFAUT = 15.0

#: Longueur minimale d'une série, en mètres. En dessous, la vitesse moyenne
#: dépend surtout de ce que le cycliste faisait juste avant.
LONGUEUR_MIN_M_DEFAUT = 500.0

#: Zone de puissance retenue, en fraction de la FTP : Z2, l'endurance.
ZONE_DEFAUT = (0.56, 0.75)

#: Nombre de bandes de puissance égales découpées dans la zone.
NB_BANDES = 3

#: En dessous, la régression ne veut rien dire et n'est pas rendue.
SERIES_MIN_REGRESSION = 8

#: En dessous, la médiane d'une bande est affichée mais accompagnée de son n,
#: qui suffit à dire qu'elle ne pèse rien.
SERIES_MIN_BANDE = 5


@dataclass(frozen=True)
class Serie:
    """Une portion de route plate, droite et roulée d'un trait.

    `v_kmh` est la vitesse moyenne **de la série** (longueur totale divisée par
    le temps total, pas la moyenne des vitesses des tronçons), `puissance_w` la
    puissance moyenne pondérée par la longueur, `longueur_m` ce qui sert de
    poids partout ensuite.
    """

    v_kmh: float
    puissance_w: float
    longueur_m: float
    mailles: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class Regression:
    """`vitesse = ordonnee + pente · puissance`, pondérée par la longueur."""

    ordonnee_kmh: float
    pente_kmh_par_w: float
    n_series: int
    longueur_m: float

    def vitesse_kmh(self, puissance_w: float) -> float:
        return self.ordonnee_kmh + self.pente_kmh_par_w * puissance_w


@dataclass
class Bande:
    """Une tranche de puissance à l'intérieur de la zone, et ce qu'y font les vélos."""

    p_min_w: float
    p_max_w: float
    vitesses: dict[str, float | None] = field(default_factory=dict)
    n: dict[str, int] = field(default_factory=dict)

    @property
    def libelle(self) -> str:
        return f"{self.p_min_w:.0f}-{self.p_max_w:.0f} W"


@dataclass
class ResultatVelo:
    """Ce qu'un vélo a montré : ses séries, et ce qu'on en tire."""

    nom: str
    n_series: int = 0
    longueur_m: float = 0.0
    puissance_moyenne_w: float | None = None
    vitesse_mediane_kmh: float | None = None
    regression: Regression | None = None
    sorties: int = 0

    @property
    def km(self) -> float:
        return self.longueur_m / 1000.0


@dataclass
class Comparaison:
    """Le résultat complet, de quoi écrire le tableau comme le JSON."""

    velos: tuple[str, str]
    zone_w: tuple[float, float]
    zone_ftp: tuple[float, float]
    pente_max: float
    cap_max_deg: float
    longueur_min_m: float
    par_velo: dict[str, ResultatVelo] = field(default_factory=dict)
    bandes: list[Bande] = field(default_factory=list)
    mailles: dict[str, int] = field(default_factory=dict)
    """Nombre de mailles de ~30 m touchées par les séries de chaque vélo."""
    mailles_communes: int = 0
    """Information seulement : les mailles communes ne filtrent plus rien."""

    @property
    def puissance_milieu_w(self) -> float:
        """Le milieu de la zone : c'est là que les deux régressions sont lues."""
        return (self.zone_w[0] + self.zone_w[1]) / 2.0

    def vitesse_lue(self, nom: str) -> float | None:
        """La vitesse du vélo au milieu de la zone, selon sa régression."""
        resultat = self.par_velo.get(nom)
        if resultat is None or resultat.regression is None:
            return None
        return resultat.regression.vitesse_kmh(self.puissance_milieu_w)

    @property
    def ecart_kmh(self) -> float | None:
        """`vitesse(second) − vitesse(premier)` au milieu de la zone."""
        premier, second = self.velos
        a, b = self.vitesse_lue(premier), self.vitesse_lue(second)
        if a is None or b is None:
            return None
        return b - a

    @property
    def ecart_w(self) -> float | None:
        """L'écart de vitesse converti en watts : `ΔV / pente(premier)`.

        La pente du **premier** vélo est celle qu'on inverse : « combien de
        watts faudrait-il de plus au premier vélo pour rouler à la vitesse du
        second ». Une pente nulle ou négative ne s'inverse pas — ce serait un
        vélo qui n'accélère pas quand on appuie, donc un échantillon qui ne dit
        rien : la conversion est alors refusée.
        """
        premier = self.par_velo.get(self.velos[0])
        ecart = self.ecart_kmh
        if ecart is None or premier is None or premier.regression is None:
            return None
        pente = premier.regression.pente_kmh_par_w
        if pente <= 0:
            return None
        return ecart / pente


# --- cœur : d'une sortie aux séries -------------------------------------------


def _admissible(echantillon, *, zone_w: tuple[float, float], pente_max: float) -> bool:
    """Tronçon plat, roulé d'un trait, dans la zone de puissance, et localisé.

    Les motifs acceptés sont ceux qui ne disent **rien contre** la vitesse du
    tronçon : `retenu`, `accélération` (le contrat de calibration écarte un
    tronçon dont la vitesse change de plus de 1 m/s ; ici c'est la vitesse elle
    -même qu'on mesure, et la série n'est pas coupée pour si peu) et `départ`
    (les deux premiers kilomètres ne dérangent que l'ajustement d'un modèle).
    Sont exclus « arrêt » — un feu rouge au milieu casse la série — et « sans
    puissance », « vitesse », « pente », qui ne sont pas comparables.
    """
    if echantillon.motif not in (calib.MOTIF_RETENU, "accélération", "départ"):
        return False
    if echantillon.lat is None or echantillon.lon is None:
        return False
    if abs(echantillon.pente) > pente_max:
        return False
    if not (zone_w[0] <= echantillon.puissance_w <= zone_w[1]):
        return False
    return echantillon.v_ms > 0 and echantillon.longueur_m > 0


def _cap_entre(precedent, courant) -> float | None:
    """Le cap du milieu d'un tronçon au milieu du suivant, ou `None` s'il est indéfini."""
    a = PointTrace(float(precedent.lat), float(precedent.lon), None, 0.0)
    b = PointTrace(float(courant.lat), float(courant.lon), None, 0.0)
    if distance_m(a, b) <= 0:
        return None
    return cap_deg(a, b)


def _ecart_cap(cap: float, precedent: float) -> float:
    """L'écart angulaire entre deux caps, dans [0, 180]."""
    return abs((cap - precedent + 180.0) % 360.0 - 180.0)


def _serie_de(echantillons: list, longueur_min_m: float) -> Serie | None:
    """Agrège une suite de tronçons contigus en une série, si elle est assez longue."""
    longueur = sum(e.longueur_m for e in echantillons)
    if longueur < longueur_min_m:
        return None
    duree = sum(e.longueur_m / e.v_ms for e in echantillons)
    if duree <= 0:
        return None
    return Serie(
        v_kmh=longueur / duree * 3.6,
        puissance_w=sum(e.puissance_w * e.longueur_m for e in echantillons) / longueur,
        longueur_m=longueur,
        mailles=frozenset(cle_maille(float(e.lat), float(e.lon)) for e in echantillons),
    )


def series_droites(
    activite,
    *,
    zone_w: tuple[float, float],
    pente_max: float = PENTE_MAX_DEFAUT,
    cap_max_deg: float = CAP_MAX_DEG_DEFAUT,
    longueur_min_m: float = LONGUEUR_MIN_M_DEFAUT,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> list[Serie]:
    """Les portions plates, droites et roulées d'un trait d'une sortie.

    `echantillonner` est appelée **sans archive** : le vent est alors inconnu
    et compté nul partout, ce qui ne coûte rien puisqu'aucun modèle n'est
    évalué ici.

    Le cap est celui du milieu d'un tronçon au milieu du suivant ; la série est
    coupée dès que ce cap tourne de plus de `cap_max_deg` d'un tronçon au
    suivant, ou dès qu'un tronçon n'est pas admissible.
    """
    echantillons = calib.echantillonner(
        activite, [], ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
    )
    series: list[Serie] = []
    courante: list = []
    cap_precedent: float | None = None

    def cloturer() -> None:
        nonlocal courante, cap_precedent
        if courante:
            serie = _serie_de(courante, longueur_min_m)
            if serie is not None:
                series.append(serie)
        courante = []
        cap_precedent = None

    for e in echantillons:
        garde = _admissible(e, zone_w=zone_w, pente_max=pente_max)
        cap = None
        if garde and courante:
            cap = _cap_entre(courante[-1], e)
            if cap is not None and cap_precedent is not None:
                garde = _ecart_cap(cap, cap_precedent) <= cap_max_deg
        if not garde:
            cloturer()
            continue
        courante.append(e)
        if cap is not None:
            cap_precedent = cap
    cloturer()
    return series


# --- cœur : des séries à la comparaison ---------------------------------------


def regresser(series: list[Serie]) -> Regression | None:
    """`vitesse = a + b · puissance`, moindres carrés pondérés par la longueur.

    Pondérer par la longueur, c'est dire qu'une série de 3 km pèse six fois une
    série de 500 m — ce qu'elle vaut, puisque sa vitesse moyenne est six fois
    mieux établie. `None` quand il y a trop peu de séries, ou quand toutes ont
    la même puissance : la droite serait alors verticale.
    """
    if len(series) < SERIES_MIN_REGRESSION:
        return None
    poids = [s.longueur_m for s in series]
    total = sum(poids)
    if total <= 0:
        return None
    somme_p = sum(w * s.puissance_w for w, s in zip(poids, series, strict=True))
    somme_v = sum(w * s.v_kmh for w, s in zip(poids, series, strict=True))
    somme_pp = sum(w * s.puissance_w**2 for w, s in zip(poids, series, strict=True))
    somme_pv = sum(w * s.puissance_w * s.v_kmh for w, s in zip(poids, series, strict=True))
    denominateur = total * somme_pp - somme_p**2
    if denominateur <= 0 or not math.isfinite(denominateur):
        return None
    pente = (total * somme_pv - somme_p * somme_v) / denominateur
    ordonnee = (somme_v - pente * somme_p) / total
    if not (math.isfinite(pente) and math.isfinite(ordonnee)):
        return None
    return Regression(
        ordonnee_kmh=ordonnee,
        pente_kmh_par_w=pente,
        n_series=len(series),
        longueur_m=total,
    )


def bornes_bandes(zone_w: tuple[float, float], nombre: int = NB_BANDES) -> list[tuple[float, float]]:
    """`nombre` tranches de puissance égales à l'intérieur de la zone."""
    bas, haut = zone_w
    largeur = (haut - bas) / nombre
    return [(bas + i * largeur, bas + (i + 1) * largeur) for i in range(nombre)]


def comparer(
    par_velo: dict[str, list[Serie]],
    *,
    velos: tuple[str, str],
    zone_w: tuple[float, float],
    zone_ftp: tuple[float, float] = ZONE_DEFAUT,
    pente_max: float = PENTE_MAX_DEFAUT,
    cap_max_deg: float = CAP_MAX_DEG_DEFAUT,
    longueur_min_m: float = LONGUEUR_MIN_M_DEFAUT,
) -> Comparaison:
    """Vitesse médiane par bande de puissance, régression, et l'écart entre les deux vélos."""
    resultat = Comparaison(
        velos=velos,
        zone_w=zone_w,
        zone_ftp=zone_ftp,
        pente_max=pente_max,
        cap_max_deg=cap_max_deg,
        longueur_min_m=longueur_min_m,
    )
    for nom in velos:
        series = par_velo.get(nom, [])
        longueur = sum(s.longueur_m for s in series)
        resultat.par_velo[nom] = ResultatVelo(
            nom=nom,
            n_series=len(series),
            longueur_m=longueur,
            puissance_moyenne_w=(
                sum(s.puissance_w * s.longueur_m for s in series) / longueur if longueur > 0 else None
            ),
            vitesse_mediane_kmh=statistics.median(s.v_kmh for s in series) if series else None,
            regression=regresser(series),
        )
        resultat.mailles[nom] = len({cle for s in series for cle in s.mailles})

    premier, second = velos
    mailles_premier = {cle for s in par_velo.get(premier, []) for cle in s.mailles}
    mailles_second = {cle for s in par_velo.get(second, []) for cle in s.mailles}
    resultat.mailles_communes = len(mailles_premier & mailles_second)

    bornes = bornes_bandes(zone_w)
    for rang, (bas, haut) in enumerate(bornes):
        # La dernière bande est fermée des deux côtés : une série pile sur la
        # borne haute de la zone est admissible, elle doit tomber quelque part.
        derniere = rang == len(bornes) - 1
        bande = Bande(p_min_w=bas, p_max_w=haut)
        for nom in velos:
            dedans = [
                s.v_kmh
                for s in par_velo.get(nom, [])
                if bas <= s.puissance_w and (s.puissance_w < haut or (derniere and s.puissance_w <= haut))
            ]
            bande.n[nom] = len(dedans)
            bande.vitesses[nom] = statistics.median(dedans) if dedans else None
        resultat.bandes.append(bande)
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
    zone_ftp = _zone(getattr(args, "zone", None))
    pente_max = _pente_max(getattr(args, "pente_max", None))
    cap_max = _cap_max(getattr(args, "cap_max", None))
    longueur_min = _longueur_min(getattr(args, "longueur_min", None))
    depuis = _date_option(getattr(args, "depuis", None), config.historique_depuis)
    zone_w = (zone_ftp[0] * config.cycliste.ftp_w, zone_ftp[1] * config.cycliste.ftp_w)

    cache = Cache(config.cache.dossier)
    par_velo: dict[str, list[Serie]] = {}
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
        series: list[Serie] = []
        lues = 0
        for entree in entrees:
            activite = relire(entree.identifiant)
            if activite is None:
                continue
            lues += 1
            series += series_droites(
                activite,
                zone_w=zone_w,
                pente_max=pente_max,
                cap_max_deg=cap_max,
                longueur_min_m=longueur_min,
                ftp_w=config.cycliste.ftp_w,
                vitesse_min_kmh=config.calibration.vitesse_min_kmh,
            )
        par_velo[velo.nom] = series
        sorties[velo.nom] = lues

    if not any(par_velo.values()):
        raise ErreurUtilisateur(
            f"comparer : aucune série plate et droite d'au moins {longueur_min:.0f} m dans la "
            f"zone {zone_w[0]:.0f}-{zone_w[1]:.0f} W pour {noms[0]} ou {noms[1]} depuis le "
            f"{depuis} — vérifier le rattachement au vélo (`ourouler inventaire`)"
        )

    resultat = comparer(
        par_velo,
        velos=(velos[0].nom, velos[1].nom),
        zone_w=zone_w,
        zone_ftp=zone_ftp,
        pente_max=pente_max,
        cap_max_deg=cap_max,
        longueur_min_m=longueur_min,
    )
    for nom, lues in sorties.items():
        resultat.par_velo[nom].sorties = lues
    for panne in pannes[:5]:
        print(f"ourouler : {panne}", file=sys.stderr)
    if getattr(args, "json", False):
        print(json.dumps(rendre_json(resultat, depuis), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(resultat, depuis))
    return 0


def _pente_max(valeur) -> float:
    return _fraction(valeur, PENTE_MAX_DEFAUT, "--pente-max", "0.008 = 0,8 %")


def _attendu(option: str, valeur, exemple: str) -> str:
    return f"{option} {valeur!r} : une valeur entre 0 et 1 est attendue ({exemple})"


def _fraction(valeur, defaut: float, option: str, exemple: str) -> float:
    if valeur is None:
        return defaut
    try:
        fraction = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(_attendu(option, valeur, exemple)) from e
    if not (0 <= fraction <= 1):
        raise ErreurUtilisateur(_attendu(option, valeur, exemple))
    return fraction


def _zone(valeur) -> tuple[float, float]:
    if not valeur:
        return ZONE_DEFAUT
    bornes = list(valeur)
    if len(bornes) != 2:
        raise ErreurUtilisateur(
            "--zone attend deux fractions de la FTP, par exemple `--zone 0.56 0.75`"
        )
    bas = _fraction(bornes[0], ZONE_DEFAUT[0], "--zone", "0.56 = 56 % de la FTP")
    haut = _fraction(bornes[1], ZONE_DEFAUT[1], "--zone", "0.75 = 75 % de la FTP")
    if not (bas < haut):
        raise ErreurUtilisateur(
            f"--zone {bornes[0]} {bornes[1]} : la borne basse doit être sous la borne haute"
        )
    return (bas, haut)


def _cap_max(valeur) -> float:
    if valeur is None:
        return CAP_MAX_DEG_DEFAUT
    try:
        cap = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"--cap-max {valeur!r} : un angle en degrés est attendu") from e
    if not (0 <= cap <= 180):
        raise ErreurUtilisateur(f"--cap-max {valeur!r} : un angle entre 0 et 180 degrés est attendu")
    return cap


def _longueur_min(valeur) -> float:
    if valeur is None:
        return LONGUEUR_MIN_M_DEFAUT
    try:
        longueur = float(valeur)
    except (TypeError, ValueError) as e:
        raise ErreurUtilisateur(f"--longueur-min {valeur!r} : une longueur en mètres est attendue") from e
    if longueur < calib.LONGUEUR_ECHANTILLON_M:
        raise ErreurUtilisateur(
            f"--longueur-min {valeur!r} : au moins la longueur d'un tronçon "
            f"({calib.LONGUEUR_ECHANTILLON_M:.0f} m) est attendue"
        )
    return longueur


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
    bas, haut = resultat.zone_w
    lignes = [
        f"Comparaison {premier} / {second} — vitesse à puissance égale, mesurée",
        f"Depuis le {depuis.isoformat()} : "
        + ", ".join(
            f"{nom} {resultat.par_velo[nom].sorties} sortie(s)" for nom in resultat.velos
        ),
        f"Séries de tronçons de {calib.LONGUEUR_ECHANTILLON_M:.0f} m : "
        f"|pente| ≤ {resultat.pente_max * 100:.1f} %, {_libelle_cap(resultat.cap_max_deg)}, "
        f"≥ {resultat.longueur_min_m:.0f} m, sans arrêt ni relance,",
        f"puissance dans la zone {resultat.zone_ftp[0] * 100:.0f}-{resultat.zone_ftp[1] * 100:.0f} % "
        f"de la FTP, soit {bas:.0f}-{haut:.0f} W. Vent inconnu, aucun modèle physique.",
        "",
        f"  {'vélo':<8}{'séries':>8}{'km':>8}{'P moy':>9}{'V médiane':>12}",
    ]
    for nom in resultat.velos:
        v = resultat.par_velo[nom]
        lignes.append(
            f"  {nom:<8}{v.n_series:>8}{v.km:>8.0f}"
            f"{_watts(v.puissance_moyenne_w):>9}{_kmh(v.vitesse_mediane_kmh):>12}"
        )
    lignes += [
        "",
        "  Vitesse médiane par bande de puissance (bandes égales dans la zone) :",
        f"  {'bande':<12}{premier:>19}{second:>19}",
    ]
    for bande in resultat.bandes:
        lignes.append(
            f"  {bande.libelle:<12}"
            f"{_vitesse_et_n(bande, premier):>19}{_vitesse_et_n(bande, second):>19}"
        )
    milieu = resultat.puissance_milieu_w
    lignes += [
        "",
        f"  Régression vitesse = a + b·puissance (pondérée par la longueur), lue à {milieu:.0f} W "
        "(milieu de la zone) :",
    ]
    for nom in resultat.velos:
        lignes.append(f"  {_ligne_regression(resultat, nom)}")
    lignes += ["", _synthese(resultat)]
    lignes.append(
        "Mailles de ~30 m touchées par ces séries : "
        + ", ".join(f"{nom} {resultat.mailles.get(nom, 0)}" for nom in resultat.velos)
        + f" — {resultat.mailles_communes} en commun (information : les mailles communes ne "
        "filtrent rien ici)."
    )
    lignes.append(
        "Aucun modèle n'intervient : ce sont des moyennes mesurées. Le vent, la fraîcheur et "
        "le sens de passage diffèrent d'une série à l'autre — ils se compensent en partie, ils "
        "ne s'annulent pas."
    )
    return "\n".join(lignes)


def _libelle_cap(cap_max_deg: float) -> str:
    """`--cap-max 180` ne coupe plus rien : le dire plutôt qu'afficher « ≤ 180° »."""
    if cap_max_deg >= 180:
        return "aucun filtre de cap"
    return f"écart de cap ≤ {cap_max_deg:.0f}°"


def _ligne_regression(resultat: Comparaison, nom: str) -> str:
    velo = resultat.par_velo[nom]
    if velo.regression is None:
        return (
            f"{nom} : pas de régression — {velo.n_series} série(s), il en faut au moins "
            f"{SERIES_MIN_REGRESSION}."
        )
    r = velo.regression
    return (
        f"{nom} : {r.vitesse_kmh(resultat.puissance_milieu_w):.1f} km/h "
        f"(pente {r.pente_kmh_par_w * 10:.2f} km/h par 10 W, {r.n_series} séries, "
        f"{r.longueur_m / 1000:.0f} km)"
    )


def _synthese(resultat: Comparaison) -> str:
    """La ligne qui répond à la question posée, ou dit pourquoi elle ne peut pas."""
    premier, second = resultat.velos
    ecart = resultat.ecart_kmh
    if ecart is None:
        return (
            f"Écart non mesurable : il manque une régression "
            f"({premier} {resultat.par_velo[premier].n_series} série(s), "
            f"{second} {resultat.par_velo[second].n_series})."
        )
    milieu = resultat.puissance_milieu_w
    watts = resultat.ecart_w
    debut = (
        f"{second} roule {ecart:+.1f} km/h à puissance égale ({milieu:.0f} W, milieu de la zone)"
    )
    if watts is None:
        return (
            f"{debut}, mais la pente de {premier} ne s'inverse pas : pas de conversion en watts."
        )
    pente = resultat.par_velo[premier].regression.pente_kmh_par_w
    lent, rapide = (premier, second) if watts >= 0 else (second, premier)
    return (
        f"{debut}, soit ≈ {abs(watts):.0f} W à vitesse égale — {lent} doit fournir "
        f"{abs(watts):.0f} W de plus pour tenir l'allure de {rapide} "
        f"(Y = ΔV / pente({premier}) = {ecart:+.2f} / {pente:.4f} km/h par W)."
    )


def _vitesse_et_n(bande: Bande, nom: str) -> str:
    """La médiane de la bande, ou seulement son effectif quand il est dérisoire."""
    vitesse, n = bande.vitesses.get(nom), bande.n.get(nom, 0)
    if vitesse is None or n < SERIES_MIN_BANDE:
        return f"— (n={n})"
    return f"{vitesse:.1f} km/h (n={n})"


def _watts(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.0f} W"


def _kmh(valeur: float | None) -> str:
    return "—" if valeur is None else f"{valeur:.1f} km/h"


def rendre_json(resultat: Comparaison, depuis: date) -> dict:
    premier, second = resultat.velos
    return {
        "velos": list(resultat.velos),
        "depuis": depuis.isoformat(),
        "zone_ftp": list(resultat.zone_ftp),
        "zone_w": [round(v, 1) for v in resultat.zone_w],
        "pente_max": resultat.pente_max,
        "cap_max_deg": resultat.cap_max_deg,
        "longueur_min_m": resultat.longueur_min_m,
        "longueur_troncon_m": calib.LONGUEUR_ECHANTILLON_M,
        "puissance_lue_w": round(resultat.puissance_milieu_w, 1),
        "velo": {
            nom: {
                "sorties": v.sorties,
                "series": v.n_series,
                "km": round(v.km, 1),
                "puissance_moyenne_w": _arrondi(v.puissance_moyenne_w),
                "vitesse_mediane_kmh": _arrondi(v.vitesse_mediane_kmh),
                "regression": (
                    None
                    if v.regression is None
                    else {
                        "ordonnee_kmh": round(v.regression.ordonnee_kmh, 3),
                        "pente_kmh_par_w": round(v.regression.pente_kmh_par_w, 5),
                        "vitesse_lue_kmh": round(
                            v.regression.vitesse_kmh(resultat.puissance_milieu_w), 2
                        ),
                        "series": v.regression.n_series,
                        "km": round(v.regression.longueur_m / 1000, 1),
                    }
                ),
            }
            for nom, v in resultat.par_velo.items()
        },
        "bandes": [
            {
                "p_min_w": round(b.p_min_w, 1),
                "p_max_w": round(b.p_max_w, 1),
                "vitesse_mediane_kmh": {
                    nom: _arrondi(valeur) for nom, valeur in b.vitesses.items()
                },
                "n": dict(b.n),
            }
            for b in resultat.bandes
        ],
        "mailles": resultat.mailles,
        "mailles_communes": resultat.mailles_communes,
        "synthese": {
            "puissance_w": round(resultat.puissance_milieu_w, 1),
            "vitesse_kmh": {
                nom: _arrondi(resultat.vitesse_lue(nom), 2) for nom in (premier, second)
            },
            "ecart_kmh": _arrondi(resultat.ecart_kmh, 2),
            "ecart_w": _arrondi(resultat.ecart_w, 0),
            "formule": f"ecart_w = ecart_kmh / pente({premier}) en km/h par W",
        },
        "modele_physique": False,
    }


def _arrondi(valeur: float | None, decimales: int = 1) -> float | None:
    return None if valeur is None else round(valeur, decimales)


__all__ = [
    "CAP_MAX_DEG_DEFAUT",
    "LONGUEUR_MIN_M_DEFAUT",
    "NB_BANDES",
    "PENTE_MAX_DEFAUT",
    "SERIES_MIN_REGRESSION",
    "ZONE_DEFAUT",
    "Bande",
    "Comparaison",
    "Regression",
    "ResultatVelo",
    "Serie",
    "bornes_bandes",
    "comparer",
    "executer_comparer",
    "regresser",
    "rendre_json",
    "rendre_texte",
    "series_droites",
]

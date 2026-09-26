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
3. les recoller en **séries consécutives**, gardées si elles font au moins
   `longueur_min` (500 m par défaut) ; `--cap-max` peut en plus couper la série
   dès que la route tourne de plus de tant de degrés d'un tronçon au suivant,
   mais ce filtre est **optionnel et désactivé par défaut** : la mesure validée
   par le mainteneur a été faite sans lui ;
4. par série : vitesse moyenne (longueur / temps), puissance moyenne pondérée
   par la longueur, longueur ;
5. par vélo : vitesse médiane dans trois bandes de puissance égales à
   l'intérieur de la zone, puis la régression `vitesse = a + b · puissance`
   pondérée par la longueur, lue **au milieu de la zone**.

**La mesure, c'est l'écart en km/h** au milieu de la zone. Les watts n'en sont
qu'une conversion, dite comme telle : `ΔP ≈ 3 · P · Δv / v` (sur le plat, la
traînée domine et la puissance suit `v³`), et, si le vélo de référence a une
calibration, `P(v_second) − P(v_premier)` avec ses paramètres. La conversion ne
passe **pas** par la pente de la régression : estimée sur des séries bruitées,
elle variait du simple au double selon les filtres, et le chiffre en watts avec
elle. Les formules sont écrites dans la sortie.

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
from ourouler.config import Config
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, cap_deg, distance_m
from ourouler.physique import calibration as calib
from ourouler.physique.modele import Parametres, puissance_requise
from ourouler.services import calibrer

#: Pente maximale, en valeur absolue, d'un tronçon comparable. 0,8 % sur 200 m,
#: c'est un mètre et demi de dénivelé : à 30 km/h et 90 kg, une quinzaine de
#: watts. Au-delà, la comparaison mesurerait le terrain plutôt que le vélo.
PENTE_MAX_DEFAUT = 0.008

#: Écart de cap toléré d'un tronçon au suivant, en degrés, **quand l'option est
#: posée**. Le défaut est `None` : aucun filtre de cap. C'est la mesure validée
#: par le mainteneur, et la seule qui reste cohérente avec la calibration —
#: exiger 15° ne garde que les lignes droites franches, divise par deux la
#: pente de la régression et double le chiffre en watts. `--cap-max 15` reste
#: disponible pour ceux qui veulent ne voir que les segments rectilignes.
CAP_MAX_DEG_SUGGERE = 15.0

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
    cap_max_deg: float | None
    longueur_min_m: float
    par_velo: dict[str, ResultatVelo] = field(default_factory=dict)
    bandes: list[Bande] = field(default_factory=list)
    mailles: dict[str, int] = field(default_factory=dict)
    """Nombre de mailles de ~30 m touchées par les séries de chaque vélo."""
    mailles_communes: int = 0
    """Information seulement : les mailles communes ne filtrent plus rien."""
    parametres_reference: Parametres | None = None
    """Calibration du **premier** vélo, quand elle existe : elle donne une
    seconde conversion de l'écart de vitesse en watts, à côté de la loi en v³.
    Le cœur ne la lit jamais lui-même, la couche commande la lui passe."""

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
    def ecart_w_v3(self) -> float | None:
        """L'écart de vitesse converti en watts par la loi dominante sur le plat.

        Sur du plat sans vent, la traînée l'emporte et la puissance suit `v³` :
        `dP/P = 3·dv/v`, donc `ΔP ≈ 3 · P · Δv / v`, avec `P` la puissance lue
        (le milieu de la zone) et `v` la vitesse du vélo de **référence**, le
        premier nommé.

        C'est un **ordre de grandeur**, pas une mesure : la part roulement
        (`Crr·m·g·v`, linéaire en v) n'y est pas séparée, ce qui surestime un
        peu l'écart en watts. Cette conversion ne passe volontairement plus par
        la pente de la régression : estimée sur des séries bruitées, elle
        variait du simple au double selon les filtres, et le chiffre en watts
        avec elle.
        """
        vitesse = self.vitesse_lue(self.velos[0])
        ecart = self.ecart_kmh
        if ecart is None or vitesse is None or vitesse <= 0:
            return None
        return 3.0 * self.puissance_milieu_w * ecart / vitesse

    @property
    def ecart_w_modele(self) -> float | None:
        """Le même écart, vu par le modèle calibré du vélo de référence.

        `P(v_second) − P(v_premier)` à plat et sans vent, avec le CdA, le Crr et
        la masse issus de la calibration : ce que coûterait, au premier vélo,
        de rouler à l'allure du second. `None` quand le vélo de référence n'a
        pas de calibration — la commande n'invente alors aucun paramètre.
        """
        if self.parametres_reference is None:
            return None
        premier, second = self.velos
        avant, apres = self.vitesse_lue(premier), self.vitesse_lue(second)
        if avant is None or apres is None or avant <= 0 or apres <= 0:
            return None
        return puissance_requise(apres / 3.6, 0.0, 0.0, self.parametres_reference) - puissance_requise(
            avant / 3.6, 0.0, 0.0, self.parametres_reference
        )


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
    cap_max_deg: float | None = None,
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
        if garde and courante and cap_max_deg is not None:
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
    cap_max_deg: float | None = None,
    longueur_min_m: float = LONGUEUR_MIN_M_DEFAUT,
    parametres_reference: Parametres | None = None,
) -> Comparaison:
    """Vitesse médiane par bande de puissance, régression, et l'écart entre les deux vélos."""
    resultat = Comparaison(
        velos=velos,
        zone_w=zone_w,
        zone_ftp=zone_ftp,
        pente_max=pente_max,
        cap_max_deg=cap_max_deg,
        longueur_min_m=longueur_min_m,
        parametres_reference=parametres_reference,
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
    if config.cycliste.ftp_w is None:
        raise ErreurUtilisateur(
            "comparer : FTP non renseignée dans la configuration — cette commande compare "
            "des sorties par zone de puissance relative à la FTP, il en faut une"
        )
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
        entrees = calibrer.sorties_calibrables(
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
        parametres_reference=_calibration_de_reference(config, velos[0].nom),
    )
    for nom, lues in sorties.items():
        resultat.par_velo[nom].sorties = lues
    for panne in pannes[:5]:
        print(f"ourouler : {panne}", file=sys.stderr)
    # Import différé : `rendu.physique` lit les types de ce module (lot 8).
    from ourouler.rendu.physique import rendre_json_comparaison, rendre_texte_comparaison

    if getattr(args, "json", False):
        print(json.dumps(rendre_json_comparaison(resultat, depuis), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte_comparaison(resultat, depuis))
    return 0


def _calibration_de_reference(config: Config, velo: str) -> Parametres | None:
    """Les paramètres calibrés du vélo de référence, ou `None` s'il n'en a pas.

    C'est **ici**, dans la couche commande, que le fichier de calibration est
    lu, et par `physique.commande` qui seul en connaît le nom : le cœur ne
    fabrique aucun chemin. Rien n'est inventé — un vélo sans calibration
    n'a pas de seconde conversion, et la sortie n'en parle pas.
    """
    from ourouler.physique.commande import chemin_calibration
    from ourouler.stockage.calibrations import lire_calibration

    calibree = lire_calibration(chemin_calibration(config), velo)
    return None if calibree is None else calibree.parametres


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


def _cap_max(valeur) -> float | None:
    """`None` quand l'option n'est pas posée : aucun filtre de cap."""
    if valeur is None:
        return None
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


__all__ = [
    "CAP_MAX_DEG_SUGGERE",
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
    "series_droites",
]

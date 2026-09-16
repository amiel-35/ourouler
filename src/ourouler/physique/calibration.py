"""Calibrer CdA et Crr sur les sorties réelles, puis mesurer ce que ça vaut.

La chaîne, en cinq temps :

1. `sorties_calibrables` choisit les sorties exploitables (extérieur, avec
   puissance, ≥ 20 km, nom sans mot de groupe, et — quand elle peut relire les
   fichiers — sans mélange de sports dans le même enregistrement) ;
2. `echantillonner` découpe chaque sortie en tronçons d'environ 200 m et note,
   pour chacun, vitesse (moyenne et aux deux bouts), puissance, pente, vent de
   face et masse volumique de l'air — puis marque ceux qu'on garde et
   **pourquoi** on jette les autres ;
3. `calibrer` ajuste (CdA, Crr) aux moindres carrés sur l'écart de puissance ;
4. `detecter_groupe` repère, avec le modèle obtenu, les sorties
   anormalement rapides — l'aspiration d'un peloton, que ni la pente ni le
   vent n'expliquent ;
5. `valider` rejoue les sorties **les plus récentes**, jamais vues par
   l'ajustement, et rend l'erreur de temps en mouvement.

Le tout deux fois (`calibrer_en_deux_passes`) : la première passe sert à
trouver les sorties en groupe, la seconde à calibrer sans elles.

Ce que le modèle ne sait pas, et qu'il faut lire avec le rapport : il ignore
les arrêts (le temps rendu est un temps **en mouvement**) et il ne connaît du
vent que ce qu'une maille d'archive de plusieurs kilomètres en dit, interpolée
à l'heure — pas la haie qui coupe le vent sur deux cents mètres. Ces écarts
vont dans le même sens : ils font paraître le cycliste plus lent que le modèle.

Troisième réserve, mesurée le 16/09/2026 et expliquée par le mainteneur :
**le CdA d'un vélo n'est pas le CdA d'une position, c'est la moyenne des
positions réellement tenues sur ce vélo.** Sur ses deux vélos, la calibration
trouve le même CdA à 0,7 % près — dans le bruit des incertitudes (±2 % et
±2,5 %) — alors qu'un chrono devrait être nettement plus aérodynamique. Tout
l'écart entre les deux (16 W à 25 km/h, 26 W à 40 km/h) est passé dans le Crr,
plus bas de 21 % sur le chrono.

Ce n'est pas un artefact de régression. Le mainteneur roule une partie de ses
sorties de chrono **hors prolongateur**, en particulier en Z2 ; le chrono porte
de meilleures roues et des pneus plus larges, donc son Crr est réellement plus
bas ; et les gains marginaux (tenue, casque, chaussettes) ne sont pas mis à
toutes les sorties. Le CdA calibré décrit donc un mélange de positions et
d'équipements — ce qui est **exactement ce qu'il faut** pour prédire des
sorties ordinaires, et faux pour prédire un effort tenu au prolongateur de
bout en bout.

Conséquence à connaître : la sensibilité au vent de face est elle aussi une
moyenne. Le gain du chrono ne grandit que de 0,6 W entre l'absence de vent et
20 km/h de vent de face à 30 km/h, là où un vrai gain aérodynamique grandirait
franchement. Pour un effort réellement en position, le modèle sous-estime.

Le vent d'archive est donné à 10 m du sol ; il est **ramené à hauteur de
cycliste** avant d'entrer dans le modèle (`modele.vent_au_cycliste`). Sans
cela, le régresseur aérodynamique est construit sur un vent systématiquement
trop fort, et l'erreur sur un régresseur tire son coefficient vers zéro : le
CdA descendait en butée basse et le Crr absorbait le reste.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import NamedTuple

import numpy as np

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur, rattacher_velo
from ourouler.activites.modele import Activite, Point, est_sport_velo
from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m
from ourouler.config import Config, Velo
from ourouler.connecteurs.openmeteo_archive import HeureArchive
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.modele import (
    RENDEMENT_DEFAUT,
    RHO_DEFAUT,
    Parametres,
    Simulation,
    masse_volumique_air,
    puissance_requise,
    simuler,
    vent_au_cycliste,
    vitesse_regime,
)

#: Longueur visée d'un échantillon, en mètres (contrat de sprint §3).
LONGUEUR_ECHANTILLON_M = 200.0

#: Sous cette vitesse instantanée, le cycliste est à l'arrêt (feu, stop).
#: Un échantillon qui en contient un seul point est jeté : sa vitesse moyenne
#: ne décrit plus un équilibre physique.
SEUIL_ARRET_MS = 1.0

#: Les deux premiers kilomètres sont écartés : mise en route, sortie de ville,
#: capteur de puissance qui n'a pas fini de se caler.
DEBUT_IGNORE_M = 2000.0

#: Bornes de pente des échantillons retenus (contrat §3).
PENTE_MIN = -0.03
PENTE_MAX = 0.08

#: Puissance minimale d'un échantillon retenu, en watts : en dessous, le
#: cycliste roule sur l'élan et le modèle d'équilibre ne s'applique pas.
PUISSANCE_MIN_W = 50.0

#: Multiple de la FTP au-delà duquel un échantillon est jeté (sprint, artefact).
FACTEUR_FTP_MAX = 2.0

#: Variation de vitesse tolérée entre deux échantillons voisins, en m/s.
#:
#: Le seuil valait 0,3 m/s (contrat §3) : il ne gardait que des tronçons
#: « stationnaires », 5 % du total, et ceux-là ne sont pas un échantillon
#: neutre d'une sortie (faux plats descendants, vent arrière). Depuis que la
#: variation d'énergie cinétique du tronçon entre dans la part **connue** de sa
#: puissance (`Echantillon.puissance_cinetique_w`), l'accélération n'est plus
#: une nuisance à fuir mais une grandeur mesurée : le seuil est relâché à
#: 1,0 m/s et ne sert plus qu'à écarter les freinages et relances brutaux, où
#: la vitesse moyenne du tronçon ne décrit plus rien.
DELTA_V_MAX_MS = 1.0

#: Demi-fenêtre, **en mètres**, sur laquelle l'altitude est moyennée avant
#: d'en tirer une pente : assez pour noyer le bruit de l'altimètre
#: barométrique (quelques dizaines de centimètres), assez peu pour que la
#: pente reste celle du tronçon et pas celle de la colline.
#:
#: En mètres et non en nombre de points : un FIT à 1 Hz donne un point tous
#: les 7 m à 28 km/h, un GPX allégé un point tous les 200 m. Une fenêtre
#: comptée en points lissait 80 m dans un cas et 2 200 m dans l'autre, et la
#: pente d'une sortie à 14 % y tombait à 7 %.
#:
#: La pente est calculée **sur le tronçon lui-même**, entre ses deux bouts :
#: une différence centrale sur les tronçons voisins donnait une pente deux
#: fois trop faible aux deux extrémités de la sortie.
DEMI_FENETRE_ALTITUDE_M = 40.0

#: Bornes de l'ajustement (contrat §3).
CDA_MIN, CDA_MAX = 0.18, 0.60
CRR_MIN, CRR_MAX = 0.002, 0.012

#: Masse d'un vélo dont la configuration ne dit rien, en kilogrammes.
MASSE_VELO_DEFAUT_KG = 9.0

#: Nombre minimal d'échantillons pour ajuster deux paramètres.
ECHANTILLONS_MINIMUM = 3

#: Une sortie est dite « en groupe » si le résidu de vitesse dépasse ce seuil
#: sur plus de `PART_DISTANCE_GROUPE` de la distance retenue (contrat §3).
SEUIL_RESIDU_GROUPE = 0.08
PART_DISTANCE_GROUPE = 0.50

#: Distance minimale d'une sortie calibrable, en mètres.
DISTANCE_MINIMALE_M = 20_000.0

#: Vitesse à laquelle on exprime ce que la calibration détermine **vraiment**.
#: CdA et Crr pris séparément peuvent être mal séparés ; leur somme des forces
#: à l'allure d'entraînement, elle, est bien contrainte par les données.
V_REFERENCE_KMH = 27.0

#: Les deux allures auxquelles le rapport chiffre cette résistance totale
#: (décision du 13/09, point 5 de la relecture) : l'allure d'entraînement et
#: l'allure de contre-la-montre. Deux points valent mieux qu'un : c'est leur
#: **écart** qui dit la part aérodynamique, sans qu'on ait à prétendre séparer
#: CdA de Crr.
V_REFERENCES_KMH = (27.0, 35.0)

MOTIF_RETENU = ""

#: Motif d'exclusion d'un fichier qui ne contient pas *que* du vélo : un FIT de
#: triathlon, un enregistrement coupé en plusieurs sessions, un fichier dont le
#: sport déclaré n'est pas cycliste (Q10 du mainteneur).
MOTIF_MULTISPORT = "multisport"

#: Date de repli pour trier une entrée sans horodatage — avant tout le reste,
#: et consciente du fuseau, sinon la comparaison échoue sur un mélange de
#: dates naïves et datées.
_JAMAIS = datetime.min.replace(tzinfo=UTC)


# --- échantillons -------------------------------------------------------------


@dataclass
class Echantillon:
    """Un tronçon d'environ 200 m d'une sortie réelle, et ce qu'on en sait.

    `retenu` dit si la calibration s'en sert, `motif` dit pourquoi pas. Les
    champs après `motif` sont des compléments du contrat de sprint : la
    longueur (pour pondérer par la distance), la masse volumique de l'air
    mesurée du jour, si le vent était connu, l'instant de passage, et les
    **vitesses aux deux bouts** — sans elles, on ne sait pas si le cycliste a
    accéléré pendant les 200 m.

    `v_debut_ms` et `v_fin_ms` valent 0 par défaut : un échantillon construit à
    la main (un test, une fixture) n'a alors aucun terme cinétique, ce qui est
    le comportement d'avant.
    """

    v_ms: float
    puissance_w: float
    pente: float
    vent_face_ms: float
    temp_c: float
    retenu: bool
    motif: str
    longueur_m: float = 0.0
    rho: float = RHO_DEFAUT
    vent_connu: bool = True
    t: datetime | None = None
    dist_m: float = 0.0
    v_debut_ms: float = 0.0
    v_fin_ms: float = 0.0
    lat: float | None = None
    lon: float | None = None
    """Position du **milieu** du tronçon, quand elle est connue. Elle ne sert
    pas à la calibration mais à `physique.comparer`, qui range les tronçons par
    maille du terrain pour comparer deux vélos sur les mêmes routes."""

    @property
    def duree_s(self) -> float:
        """La durée du tronçon, en secondes. 0 si la vitesse moyenne est nulle.

        Elle n'est pas stockée : `v_ms` **est** `longueur_m / duree`, la
        redonder serait offrir deux occasions de se contredire.
        """
        return self.longueur_m / self.v_ms if self.v_ms > 0 and self.longueur_m > 0 else 0.0

    def puissance_cinetique_w(
        self, masse_totale_kg: float, rendement: float = RENDEMENT_DEFAUT
    ) -> float:
        """La puissance qu'a coûtée (ou rendue) le changement de vitesse du tronçon.

        `m · (v_fin² − v_début²) / (2 · Δt)`, au pédalier donc divisée par le
        rendement. Positive quand le cycliste accélère — cette puissance-là
        n'est allée ni dans l'air ni dans les pneus, et l'attribuer au CdA le
        faussait. Négative quand il ralentit : l'élan a payé une part de la
        résistance, et le capteur a vu moins de watts que l'équilibre n'en
        demandait.

        Ce terme est **connu** : il ne dépend ni de CdA ni de Crr, seulement de
        la masse et de deux vitesses mesurées. Il rejoint donc la colonne `c`
        de la régression, du côté des constantes.
        """
        duree = self.duree_s
        if duree <= 0 or rendement <= 0:
            return 0.0
        delta = self.v_fin_ms**2 - self.v_debut_ms**2
        if not math.isfinite(delta):
            return 0.0
        return masse_totale_kg * delta / (2.0 * duree) / rendement


def echantillonner(
    activite: Activite,
    vent: list[HeureArchive],
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> list[Echantillon]:
    """Découpe une sortie en tronçons de `LONGUEUR_ECHANTILLON_M` et les qualifie.

    Tous les tronçons sont rendus, retenus ou non : le rapport de calibration
    doit pouvoir dire combien d'échantillons ont été écartés et pour quelle
    raison, plutôt que d'afficher un nombre sorti de nulle part.

    `vent` est l'archive du jour au point de départ ; vide, les échantillons
    portent un vent nul et `vent_connu = False`.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2:
        return []
    distances = _distances_points(points)
    bruts = _decouper(points, distances)
    if not bruts:
        return []

    altitudes = _altitudes_lissees(points, distances)
    echantillons: list[Echantillon] = []
    for i, j, longueur, duree in bruts:
        pente = (altitudes[j] - altitudes[i]) / longueur
        puissance = _puissance_moyenne(points, i, j)
        t_milieu = points[i].t + (points[j].t - points[i].t) / 2
        heure = _interpoler_archive(vent, t_milieu)
        cap = _cap(points, i, j)
        face = _vent_de_face(heure, cap)
        milieu = points[(i + j) // 2]
        echantillons.append(
            Echantillon(
                v_ms=longueur / duree,
                # 0 W quand la source n'en donne pas : l'échantillon est alors
                # écarté avec le motif « sans puissance », et ce zéro ne sert
                # jamais à rien d'autre. Un NaN, lui, aurait traversé les
                # sommes sans bruit.
                puissance_w=puissance if puissance is not None else 0.0,
                pente=pente,
                vent_face_ms=face if face is not None else 0.0,
                temp_c=heure.temp_c if heure is not None and heure.temp_c is not None else float("nan"),
                retenu=False,
                motif=MOTIF_RETENU,
                longueur_m=longueur,
                rho=masse_volumique_air(
                    heure.temp_c if heure else None, heure.pression_hpa if heure else None
                ),
                vent_connu=face is not None,
                t=t_milieu,
                dist_m=distances[j],
                v_debut_ms=_vitesse_au_point(points, distances, i),
                v_fin_ms=_vitesse_au_point(points, distances, j),
                lat=milieu.lat if milieu is not None else None,
                lon=milieu.lon if milieu is not None else None,
            )
        )
        if puissance is None:
            echantillons[-1].motif = "sans puissance"
        elif _contient_un_arret(points, i, j):
            echantillons[-1].motif = "arrêt"

    _qualifier(echantillons, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
    return echantillons


def _decouper(
    points: Sequence[Point], distances: Sequence[float]
) -> list[tuple[int, int, float, float]]:
    """(début, fin, longueur, durée) de chaque tronçon d'environ 200 m."""
    troncons = []
    debut = 0
    for i in range(1, len(points)):
        longueur = distances[i] - distances[debut]
        if longueur < LONGUEUR_ECHANTILLON_M:
            continue
        duree = (points[i].t - points[debut].t).total_seconds()
        if duree > 0:
            troncons.append((debut, i, longueur, duree))
        debut = i
    return troncons


def _distances_points(points: Sequence[Point]) -> list[float]:
    """Distances cumulées : celles de la source si elles sont croissantes, sinon la géométrie."""
    portees = [p.dist_m for p in points]
    if all(d is not None for d in portees) and all(
        b >= a for a, b in zip(portees[:-1], portees[1:], strict=True)
    ):
        return [float(d) for d in portees]
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
            cumul.append(cumul[-1])
            continue
        cumul.append(cumul[-1] + distance_m(_en_point_trace(a), _en_point_trace(b)))
    return cumul


def _altitudes_lissees(
    points: Sequence[Point], distances: Sequence[float], demi_m: float = DEMI_FENETRE_ALTITUDE_M
) -> list[float]:
    """L'altitude de chaque point, moyennée sur ±`demi_m` mètres le long du parcours.

    Fenêtre glissante sur la distance, pas sur le nombre de points : deux
    curseurs qui n'avancent jamais à reculons, donc un seul passage. Un point
    sans altitude compte pour 0 — un parcours entier sans altitude est
    simplement plat, et `Trace.denivele_m` vaut alors `None` pour le dire.
    """
    alts = [float(p.alt_m) if p.alt_m is not None else 0.0 for p in points]
    cumul = [0.0]
    for a in alts:
        cumul.append(cumul[-1] + a)
    lisse: list[float] = []
    bas = haut = 0
    for i, d in enumerate(distances):
        while distances[bas] < d - demi_m:
            bas += 1
        haut = max(haut, i)
        while haut + 1 < len(distances) and distances[haut + 1] <= d + demi_m:
            haut += 1
        lisse.append((cumul[haut + 1] - cumul[bas]) / (haut + 1 - bas))
    return lisse


def _cap(points: Sequence[Point], i: int, j: int) -> float | None:
    """Cap moyen du tronçon, ou `None` si l'un des deux bouts n'a pas de position."""
    if any(p.lat is None or p.lon is None for p in (points[i], points[j])):
        return None
    debut, fin = _en_point_trace(points[i]), _en_point_trace(points[j])
    return cap_deg(debut, fin) if distance_m(debut, fin) > 0 else None


def _en_point_trace(p: Point) -> PointTrace:
    return PointTrace(lat=float(p.lat), lon=float(p.lon), alt_m=p.alt_m, dist_m=float(p.dist_m or 0.0))


def _puissance_moyenne(points: Sequence[Point], i: int, j: int) -> float | None:
    """Puissance moyenne du tronçon, pondérée par la durée. `None` si aucune valeur."""
    somme = duree = 0.0
    for a, b in zip(points[i:j], points[i + 1 : j + 1], strict=True):
        if a.puissance_w is None:
            continue
        dt = (b.t - a.t).total_seconds()
        if dt <= 0:
            continue
        somme += float(a.puissance_w) * dt
        duree += dt
    return somme / duree if duree > 0 else None


def _vitesse_au_point(points: Sequence[Point], distances: Sequence[float], k: int) -> float:
    """La vitesse instantanée au point `k`, en m/s.

    Celle qu'a enregistrée le compteur si elle existe ; sinon une différence
    finie centrée sur les deux points voisins. Un GPX sans champ de vitesse ne
    doit pas priver la calibration de son terme cinétique — la géométrie la
    donne, à un pas d'échantillonnage près.

    Rend 0 quand rien ne permet de conclure : le terme cinétique est alors le
    même aux deux bouts et s'annule, ce qui est exactement l'ancien
    comportement.
    """
    valeur = points[k].vitesse_ms
    if valeur is not None:
        valeur = float(valeur)
        if math.isfinite(valeur) and valeur >= 0:
            return valeur
    avant = max(0, k - 1)
    apres = min(len(points) - 1, k + 1)
    if apres == avant:
        return 0.0
    duree = (points[apres].t - points[avant].t).total_seconds()
    if duree <= 0:
        return 0.0
    portee = distances[apres] - distances[avant]
    return portee / duree if portee > 0 else 0.0


def _contient_un_arret(points: Sequence[Point], i: int, j: int) -> bool:
    """Vrai si un point du tronçon est sous `SEUIL_ARRET_MS`.

    La vitesse moyenne d'un tronçon coupé par un feu rouge ne décrit aucun
    équilibre : la garder reviendrait à demander au modèle d'expliquer un
    arrêt par de la traînée.
    """
    return any(
        p.vitesse_ms is not None and float(p.vitesse_ms) < SEUIL_ARRET_MS for p in points[i : j + 1]
    )


def _qualifier(
    echantillons: list[Echantillon], *, ftp_w: float, vitesse_min_kmh: float
) -> None:
    """Pose `retenu` et `motif` sur chaque échantillon, filtres du contrat §3."""
    vitesse_min_ms = vitesse_min_kmh / 3.6
    puissance_max = FACTEUR_FTP_MAX * ftp_w
    for indice, e in enumerate(echantillons):
        motif = e.motif  # « arrêt » a pu être posé plus tôt
        if not motif:
            if e.dist_m - e.longueur_m < DEBUT_IGNORE_M:
                motif = "départ"
            elif not (PUISSANCE_MIN_W <= e.puissance_w <= puissance_max):
                motif = "puissance"
            elif e.v_ms < vitesse_min_ms:
                motif = "vitesse"
            elif not (PENTE_MIN <= e.pente <= PENTE_MAX):
                motif = "pente"
            elif _accelere(echantillons, indice):
                motif = "accélération"
        e.motif = motif
        e.retenu = not motif


def _accelere(echantillons: Sequence[Echantillon], indice: int) -> bool:
    """Vrai si la vitesse change de plus de `DELTA_V_MAX_MS` avec un voisin."""
    v = echantillons[indice].v_ms
    for voisin in (indice - 1, indice + 1):
        if 0 <= voisin < len(echantillons):
            if abs(echantillons[voisin].v_ms - v) >= DELTA_V_MAX_MS:
                return True
    return False


# --- vent ---------------------------------------------------------------------


def _interpoler_archive(heures: Sequence[HeureArchive], t: datetime) -> HeureArchive | None:
    """L'archive à l'instant `t`, interpolée entre les deux heures encadrantes.

    Hors de la série (archive vide, sortie à cheval sur deux jours dont on n'a
    qu'un) : `None`. On ne prolonge pas la dernière heure connue — ce serait
    affirmer sans mesure.
    """
    if not heures:
        return None
    ordonnees = sorted(heures, key=lambda h: h.t)
    if t < ordonnees[0].t or t > ordonnees[-1].t:
        return None
    for avant, apres in zip(ordonnees[:-1], ordonnees[1:], strict=True):
        if avant.t <= t <= apres.t:
            duree = (apres.t - avant.t).total_seconds()
            f = (t - avant.t).total_seconds() / duree if duree > 0 else 0.0
            return HeureArchive(
                t=t,
                vent_kmh=_lineaire(avant.vent_kmh, apres.vent_kmh, f),
                vent_depuis_deg=_angulaire(avant.vent_depuis_deg, apres.vent_depuis_deg, f),
                temp_c=_lineaire(avant.temp_c, apres.temp_c, f),
                pression_hpa=_lineaire(avant.pression_hpa, apres.pression_hpa, f),
            )
    return None


def _vent_de_face(heure: HeureArchive | None, cap: float | None) -> float | None:
    """Composante de face du vent **à hauteur de cycliste**, en m/s (de face positive).

    `vent_depuis_deg` est la direction **d'où** vient le vent. Le vent est de
    face quand il vient de là où l'on va : la composante vaut donc
    `v · cos(direction_d_où − cap)`.

    L'archive donne le vent à 10 m du sol ; `vent_au_cycliste` le ramène à la
    hauteur où le cycliste le subit. C'est le **seul** endroit où l'archive est
    convertie : `echantillonner`, `detecter_groupe` et `vent_le_long` passent
    tous par ici.
    """
    if heure is None or cap is None:
        return None
    if heure.vent_kmh is None or heure.vent_depuis_deg is None:
        return None
    a_10m = (heure.vent_kmh / 3.6) * math.cos(math.radians(heure.vent_depuis_deg - cap))
    return vent_au_cycliste(a_10m)


def _lineaire(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return None
    return a + (b - a) * f


def _angulaire(a: float | None, b: float | None, f: float) -> float | None:
    """Interpolation d'un angle par ses composantes : 350° et 10° donnent 0°, pas 180°."""
    if a is None or b is None:
        return None
    ra, rb = math.radians(a), math.radians(b)
    x = math.cos(ra) + (math.cos(rb) - math.cos(ra)) * f
    y = math.sin(ra) + (math.sin(rb) - math.sin(ra)) * f
    if x == 0.0 and y == 0.0:
        return a
    return math.degrees(math.atan2(y, x)) % 360.0


# --- ajustement ---------------------------------------------------------------


@dataclass(frozen=True)
class Incertitudes:
    """Écarts-types des deux paramètres ajustés. `None` quand ils ne se calculent pas.

    Regroupées plutôt que posées à plat sur `Ajustement` : un attribut
    `cda_incertitude` à côté de `cda_m2` donne deux nombres « CdA » sur le
    même objet, et le premier lecteur venu — humain ou test — prend l'un pour
    l'autre.
    """

    cda: float | None = None
    crr: float | None = None


@dataclass
class Ajustement:
    """Le couple (CdA, Crr) qui explique le mieux les échantillons, et ce qu'il vaut."""

    cda_m2: float
    crr: float
    masse_totale_kg: float
    n_echantillons: int
    rmse_w: float
    mae_w: float
    incertitudes: Incertitudes = field(default_factory=Incertitudes)
    rho_moyen: float = RHO_DEFAUT
    bornes_atteintes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()

    def resistance_a(self, v_kmh: float) -> tuple[float, float]:
        """(force en newtons, puissance au pédalier en watts) sur le plat sans vent.

        C'est **la** grandeur que ces données mesurent. CdA et Crr peuvent se
        compenser l'un l'autre — un CdA trop bas avec un Crr trop haut donne la
        même puissance à 27 km/h — mais cette somme-là, non : elle est
        directement ce que le capteur a vu, à l'allure où il l'a vu.
        """
        p = self.parametres()
        v = v_kmh / 3.6
        puissance = puissance_requise(v, 0.0, 0.0, p)
        return (puissance * p.rendement / v, puissance)

    @property
    def resistances(self) -> list[tuple[float, float, float]]:
        """(vitesse km/h, force N, puissance W) à chacune des `V_REFERENCES_KMH`."""
        return [(v, *self.resistance_a(v)) for v in V_REFERENCES_KMH]

    @property
    def force_reference_n(self) -> float:
        """Force totale à vaincre à `V_REFERENCE_KMH` sur le plat sans vent, en newtons.

        C'est la grandeur que l'ajustement contraint le mieux : CdA et Crr
        peuvent se compenser l'un l'autre, leur somme à l'allure courante non.
        À citer chaque fois qu'une borne est atteinte.
        """
        return force_resistante_n(self.parametres())

    def parametres(self, *, rho: float | None = None) -> Parametres:
        """Les `Parametres` correspondants, avec la masse volumique moyenne des échantillons."""
        return Parametres(
            masse_totale_kg=self.masse_totale_kg,
            cda_m2=self.cda_m2,
            crr=self.crr,
            rho=rho if rho is not None else self.rho_moyen,
        )


def force_resistante_n(p: Parametres, v_kmh: float = V_REFERENCE_KMH) -> float:
    """Force totale à vaincre sur le plat sans vent, en newtons, à `v_kmh`."""
    v = v_kmh / 3.6
    return puissance_requise(v, 0.0, 0.0, p) * p.rendement / v


def calibrer(
    echantillons: Sequence[Echantillon],
    *,
    masse_totale_kg: float,
    cda_init: float = 0.32,
    crr_init: float = 0.005,
) -> Ajustement:
    """Moindres carrés sur (CdA, Crr), bornés, à partir des échantillons retenus.

    **Le modèle est linéaire en CdA et en Crr** : à vitesse, pente et vent
    donnés, la puissance vaut `a·CdA + b·Crr + c`, où a, b et c ne dépendent
    d'aucun des deux. Le contrat de sprint prévoyait une grille grossière puis
    un affinage ; la solution exacte existe, on la prend — et les coefficients
    a, b, c sont obtenus en appelant `puissance_requise` avec des paramètres
    unitaires, de sorte que la calibration ne puisse pas diverger de la
    physique du modèle. Écart au contrat assumé et signalé.

    Hors des bornes, le minimum d'une forme quadratique convexe sur un pavé
    est sur le bord : on résout alors les quatre arêtes et on garde la
    meilleure. `cda_init` et `crr_init` ne servent donc qu'à nommer un point
    de départ dans le rapport (ils n'influent pas sur le résultat) et à
    répondre quand le problème est dégénéré.

    **L'incertitude rendue est optimiste** : elle suppose des résidus
    indépendants, alors que deux tronçons de 200 m voisins se ressemblent.
    Elle dit l'ordre de grandeur de ce que les données contraignent, pas
    l'erreur vraie.
    """
    retenus = [e for e in echantillons if e.retenu]
    if len(retenus) < ECHANTILLONS_MINIMUM:
        raise ErreurUtilisateur(
            f"calibration : {len(retenus)} échantillon(s) retenu(s), "
            f"au moins {ECHANTILLONS_MINIMUM} sont nécessaires pour ajuster CdA et Crr"
        )
    if not math.isfinite(masse_totale_kg) or masse_totale_kg <= 0:
        raise ErreurUtilisateur(
            f"calibration : masse totale {masse_totale_kg!r} — une masse positive est attendue"
        )

    a, b, c, y = _matrices(retenus, masse_totale_kg)
    matrice = np.column_stack((a, b))
    reste = y - c
    avertissements: list[str] = []

    solution, rang = _moindres_carres(matrice, reste)
    if rang < 2:
        avertissements.append(
            "les échantillons ne séparent pas CdA de Crr (trop peu de variété de "
            "vitesse ou de pente) : la solution est celle de norme minimale"
        )
        solution = np.array([cda_init, crr_init], dtype=float)
    cda, crr, bornes = _borner(matrice, reste, solution)
    if bornes:
        avertissements.append(
            "une borne est atteinte : CdA et Crr ne sont plus séparés par ces "
            "données, seule leur résistance combinée à l'allure courante est mesurée"
        )

    residus = matrice @ np.array([cda, crr]) - reste
    n = len(retenus)
    rmse = float(np.sqrt(np.mean(residus**2)))
    mae = float(np.mean(np.abs(residus)))
    incertitudes = _incertitudes(matrice, residus, n)
    return Ajustement(
        cda_m2=float(cda),
        crr=float(crr),
        masse_totale_kg=float(masse_totale_kg),
        n_echantillons=n,
        rmse_w=rmse,
        mae_w=mae,
        incertitudes=Incertitudes(*incertitudes),
        rho_moyen=float(np.mean([e.rho for e in retenus])),
        bornes_atteintes=bornes,
        avertissements=tuple(avertissements),
    )


def _matrices(
    retenus: Sequence[Echantillon], masse_totale_kg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Les colonnes (a, b, c) du modèle linéaire et le vecteur des puissances mesurées.

    a, b et c sortent de `puissance_requise` elle-même, avec des paramètres
    unitaires : `a = P(CdA=1, Crr=0) − P(0, 0)`, `b = P(0, Crr=1) − P(0, 0)`,
    `c = P(0, 0)` (la part gravité + rendement). Aucune formule n'est donc
    recopiée ici.

    À `c` s'ajoute la **variation d'énergie cinétique** du tronçon,
    `m · (v_fin² − v_début²) / (2 · Δt)`, elle aussi connue sans CdA ni Crr.
    Sans elle, la calibration ne pouvait garder que des tronçons à vitesse
    constante ; avec elle, un tronçon où le cycliste accélère de 1 m/s dit
    autant qu'un autre, et il y en a des milliers au lieu de quelques
    centaines.
    """
    a = np.empty(len(retenus))
    b = np.empty(len(retenus))
    c = np.empty(len(retenus))
    y = np.empty(len(retenus))
    for i, e in enumerate(retenus):
        base = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=0.0, rho=e.rho)
        seul_cda = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=1.0, crr=0.0, rho=e.rho)
        seul_crr = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=1.0, rho=e.rho)
        # `sans_rien` sert de référence aux deux colonnes : le terme cinétique
        # ne doit surtout pas entrer dans `a` et `b`, qui sont des **écarts**
        # à cette référence. Il ne rejoint `c` qu'ensuite.
        sans_rien = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, base)
        a[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_cda) - sans_rien
        b[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_crr) - sans_rien
        c[i] = sans_rien + e.puissance_cinetique_w(masse_totale_kg, base.rendement)
        y[i] = e.puissance_w
    return a, b, c, y


def _moindres_carres(matrice: np.ndarray, reste: np.ndarray) -> tuple[np.ndarray, int]:
    solution, _, rang, _ = np.linalg.lstsq(matrice, reste, rcond=None)
    return solution, int(rang)


def _borner(
    matrice: np.ndarray, reste: np.ndarray, solution: np.ndarray
) -> tuple[float, float, tuple[str, ...]]:
    """Ramène la solution dans le pavé des bornes, en minimisant vraiment l'écart.

    Écrêter les deux coordonnées séparément ne donne pas le minimum du pavé :
    si CdA sort par le haut, le Crr optimal **à CdA borné** n'est plus celui
    de la solution libre. On résout donc chaque arête à une inconnue et on
    garde la meilleure des candidates.
    """
    cda, crr = float(solution[0]), float(solution[1])
    if CDA_MIN <= cda <= CDA_MAX and CRR_MIN <= crr <= CRR_MAX:
        return (cda, crr, ())

    candidates: list[tuple[float, float]] = []
    for valeur in (CDA_MIN, CDA_MAX):
        candidates.append((valeur, _arete(matrice, reste, fixe=0, valeur=valeur)))
    for valeur in (CRR_MIN, CRR_MAX):
        candidates.append((_arete(matrice, reste, fixe=1, valeur=valeur), valeur))
    candidates += [
        (x, z) for x in (CDA_MIN, CDA_MAX) for z in (CRR_MIN, CRR_MAX)
    ]
    valides = [
        (x, z)
        for x, z in candidates
        if CDA_MIN - 1e-12 <= x <= CDA_MAX + 1e-12 and CRR_MIN - 1e-12 <= z <= CRR_MAX + 1e-12
    ]
    meilleure = min(
        valides, key=lambda xz: float(np.sum((matrice @ np.array(xz) - reste) ** 2))
    )
    cda, crr = meilleure
    bornes = []
    if math.isclose(cda, CDA_MIN) or math.isclose(cda, CDA_MAX):
        bornes.append(f"CdA = {cda:.2f}")
    if math.isclose(crr, CRR_MIN) or math.isclose(crr, CRR_MAX):
        bornes.append(f"Crr = {crr:.4f}")
    return (cda, crr, tuple(bornes))


def _arete(matrice: np.ndarray, reste: np.ndarray, *, fixe: int, valeur: float) -> float:
    """Optimum de l'inconnue restante quand l'autre est fixée à `valeur`, écrêté à ses bornes."""
    libre = 1 - fixe
    colonne = matrice[:, libre]
    cible = reste - matrice[:, fixe] * valeur
    denominateur = float(colonne @ colonne)
    if denominateur <= 0:
        return CRR_MIN if libre == 1 else CDA_MIN
    x = float((colonne @ cible) / denominateur)
    mini, maxi = (CDA_MIN, CDA_MAX) if libre == 0 else (CRR_MIN, CRR_MAX)
    return min(max(x, mini), maxi)


def _incertitudes(
    matrice: np.ndarray, residus: np.ndarray, n: int
) -> tuple[float | None, float | None]:
    """Écarts-types des deux paramètres, `σ²·(AᵀA)⁻¹`. `None` si la matrice est singulière."""
    if n <= 2:
        return (None, None)
    variance = float(residus @ residus) / (n - 2)
    try:
        covariance = np.linalg.inv(matrice.T @ matrice) * variance
    except np.linalg.LinAlgError:
        return (None, None)
    diagonale = np.diag(covariance)
    if np.any(diagonale < 0):
        return (None, None)
    racines = np.sqrt(diagonale)
    return (float(racines[0]), float(racines[1]))


# --- validation ---------------------------------------------------------------


class ErreurSortie(NamedTuple):
    """L'écart entre le temps simulé et le temps en mouvement réel d'une sortie.

    `NamedTuple` et non dataclass, et `jour` en chaîne ISO : le contrat §3
    demande un rapport **texte et JSON**, et `json.dumps` doit pouvoir avaler
    la liste telle quelle sans conversion préalable.
    """

    jour: str  # AAAA-MM-JJ, vide si la source n'a pas d'horodatage
    nom: str
    distance_m: float
    temps_reel_s: float
    temps_simule_s: float

    @property
    def erreur_relative(self) -> float:
        """Positive = le modèle prédit **plus lent** que la réalité."""
        return (self.temps_simule_s - self.temps_reel_s) / self.temps_reel_s


@dataclass
class Validation:
    """Ce que vaut le modèle sur des sorties qu'il n'a pas vues."""

    sorties: list[ErreurSortie] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.sorties)

    @property
    def erreurs(self) -> list[float]:
        return [s.erreur_relative for s in self.sorties]

    @property
    def mae(self) -> float | None:
        """Erreur absolue moyenne, en fraction (0,06 = 6 %)."""
        return statistics.fmean(abs(e) for e in self.erreurs) if self.sorties else None

    @property
    def mediane(self) -> float | None:
        return statistics.median(abs(e) for e in self.erreurs) if self.sorties else None

    @property
    def biais(self) -> float | None:
        """Erreur **signée** moyenne : dit dans quel sens le modèle se trompe."""
        return statistics.fmean(self.erreurs) if self.sorties else None

    @property
    def pire(self) -> ErreurSortie | None:
        return max(self.sorties, key=lambda s: abs(s.erreur_relative), default=None)


def valider(
    sorties_test: Sequence[tuple[Activite, list[HeureArchive]]], p: Parametres
) -> Validation:
    """Rejoue chaque sortie à sa puissance moyenne et son vent réels, et compare les temps.

    La puissance injectée est la **moyenne en mouvement** de la sortie, pas son
    profil détaillé. Ce n'est pas de la paresse, c'est une mesure : rejouer le
    profil mesuré par tranches de 100 m donne un temps catastrophique, parce
    que le modèle ignore l'inertie. Là où le cycliste traverse cent mètres à
    zéro watt sur son élan à 35 km/h, un modèle d'équilibre répond « zéro watt,
    donc à l'arrêt » et y perd des minutes.

    Mesuré sur les 100 sorties RCR réelles du mainteneur, avec les mêmes
    paramètres (CdA 0,32, Crr 0,005, 100 kg) :

    | puissance injectée        | MAE   | médiane | biais  |
    |---------------------------|-------|---------|--------|
    | moyenne en mouvement      | 5,0 % | 4,0 %   | −1,9 % |
    | profil mesuré par 100 m   | 15,7 %| 14,1 %  | +15,0 %|

    C'est aussi l'usage visé : on demande au modèle « combien de temps cette
    boucle, à 200 W ? », pas « rejoue-moi une sortie déjà faite ».

    Le temps de référence est le temps **en mouvement** (`temps_mouvement_s`),
    le seul que la simulation prétende prédire.
    """
    validation = Validation()
    for activite, vent in sorties_test:
        mesure = simuler_sortie(activite, vent, p)
        if mesure is None:
            continue
        simulation, reel = mesure
        validation.sorties.append(
            ErreurSortie(
                jour=activite.debut.date().isoformat() if activite.debut else "",
                nom=str(activite.meta.get("nom") or activite.fichier or ""),
                distance_m=simulation.distance_m,
                temps_reel_s=reel,
                temps_simule_s=simulation.temps_s,
            )
        )
    return validation


def simuler_sortie(
    activite: Activite, vent: Sequence[HeureArchive], p: Parametres
) -> tuple[Simulation, float] | None:
    """(simulation, temps en mouvement réel) d'une sortie, ou `None` si elle est inexploitable."""
    trace = trace_depuis_activite(activite)
    if trace is None:
        return None
    reel = temps_mouvement_s(activite)
    if reel is None or reel <= 0:
        return None
    puissance = puissance_moyenne_en_mouvement(activite)
    if puissance is None or puissance <= 0:
        return None
    simulation = simuler(trace, puissance, p, vent=vent_le_long(activite, vent))
    return (simulation, reel)


def puissance_moyenne_en_mouvement(activite: Activite) -> float | None:
    """Puissance moyenne pondérée par la durée, **hors arrêts**. `None` sans puissance.

    Les zéros d'un feu rouge ne doivent pas entrer dans la moyenne : ils
    abaisseraient la puissance de la sortie sans que le cycliste ait roulé un
    mètre plus lentement.
    """
    points = [p for p in activite.points if p.t is not None]
    somme = duree = 0.0
    for a, b in zip(points[:-1], points[1:], strict=True):
        if a.puissance_w is None:
            continue
        dt = (b.t - a.t).total_seconds()
        if not (0 < dt <= 60):
            continue
        if a.vitesse_ms is not None and float(a.vitesse_ms) < SEUIL_ARRET_MS:
            continue
        somme += float(a.puissance_w) * dt
        duree += dt
    if duree > 0:
        return somme / duree
    return float(activite.puissance_moy_w) if activite.puissance_moy_w else None


def trace_depuis_activite(activite: Activite) -> Trace | None:
    """Le parcours d'une sortie enregistrée, vu comme un `Trace` (sans segments OSM)."""
    points = [
        PointTrace(
            lat=float(p.lat),
            lon=float(p.lon),
            alt_m=float(p.alt_m) if p.alt_m is not None else None,
            dist_m=float(p.dist_m) if p.dist_m is not None else 0.0,
        )
        for p in activite.points
        if p.lat is not None and p.lon is not None
    ]
    if len(points) < 2:
        return None
    return Trace(
        nom=str(activite.meta.get("nom") or "sortie"),
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=activite.denivele_m,
        temps_moteur_s=None,
    )


def temps_mouvement_s(activite: Activite) -> float | None:
    """Le temps passé à rouler, arrêts déduits, en secondes.

    Somme des intervalles dont le point de départ est au-dessus de
    `SEUIL_ARRET_MS`. Les intervalles de plus d'une minute (compteur en pause,
    trou d'enregistrement) sont écartés : ils ne représentent pas du
    mouvement.

    Sans vitesse par point, on se rabat sur `duree_mouvement_s` de la source,
    puis sur la durée écoulée — en sachant que cette dernière **inclut les
    arrêts** et rendra donc le modèle trop rapide.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) >= 2 and any(p.vitesse_ms is not None for p in points):
        total = 0.0
        for a, b in zip(points[:-1], points[1:], strict=True):
            dt = (b.t - a.t).total_seconds()
            if not (0 < dt <= 60):
                continue
            if a.vitesse_ms is not None and float(a.vitesse_ms) >= SEUIL_ARRET_MS:
                total += dt
        if total > 0:
            return total
    if activite.duree_mouvement_s:
        return float(activite.duree_mouvement_s)
    return float(activite.duree_s) if activite.duree_s else None


def vent_le_long(
    activite: Activite, vent: Sequence[HeureArchive]
) -> Callable[[float, float], float] | None:
    """`vent(dist_m, cap_deg)` pour la simulation, daté par l'heure **réelle** de passage.

    Utiliser l'heure réelle plutôt que l'avancement simulé évite d'avoir à
    itérer ; l'erreur commise est du second ordre (le vent d'archive change à
    l'heure, une sortie de trois heures ne se décale que de quelques minutes).
    """
    if not vent:
        return None
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2:
        return None
    distances = _distances_points(points)
    instants = [p.t for p in points]

    def a_l_heure(dist_m: float) -> datetime:
        i = min(range(len(distances)), key=lambda k: abs(distances[k] - dist_m))
        return instants[i]

    def face(dist_m: float, cap: float) -> float:
        heure = _interpoler_archive(vent, a_l_heure(dist_m))
        valeur = _vent_de_face(heure, cap)
        return valeur if valeur is not None else 0.0

    return face


# --- détection des sorties en groupe -----------------------------------------


def detecter_groupe(
    activite: Activite,
    p: Parametres,
    vent: list[HeureArchive],
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> tuple[bool, float]:
    """(en groupe ?, part de la distance anormalement rapide).

    Pour chaque tronçon retenu, on demande au modèle la vitesse que la
    puissance mesurée justifie, compte tenu de la pente et du vent. Rouler
    durablement plus vite que ça, c'est rouler dans une roue : le peloton
    fait gagner 20 à 30 % de traînée, et un tel gain attribué au vélo
    fausserait son CdA pour toutes les autres sorties.

    Le seuil est celui du contrat : résidu > +8 % sur plus de la moitié de la
    distance **retenue** (les tronçons écartés — arrêts, accélérations — ne
    disent rien d'un équilibre).
    """
    echantillons = [
        e
        for e in echantillonner(activite, vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
        if e.retenu
    ]
    distance = sum(e.longueur_m for e in echantillons)
    if distance <= 0:
        return (False, 0.0)
    rapide = 0.0
    for e in echantillons:
        # La part de la puissance qui a servi à accélérer n'a pas servi à
        # tenir une vitesse : la retirer avant de demander au modèle quelle
        # vitesse d'équilibre la puissance justifie, sinon tout tronçon de
        # relance passerait pour un tronçon d'aspiration.
        equilibre = e.puissance_w - e.puissance_cinetique_w(p.masse_totale_kg, p.rendement)
        attendue = vitesse_regime(equilibre, e.pente, e.vent_face_ms, p)
        if attendue > 0 and (e.v_ms - attendue) / attendue > SEUIL_RESIDU_GROUPE:
            rapide += e.longueur_m
    part = rapide / distance
    return (part > PART_DISTANCE_GROUPE, part)


# --- choix des sorties --------------------------------------------------------


def masse_totale_kg(config: Config, velo: Velo) -> float:
    """Cycliste + vélo. Un vélo sans masse déclarée pèse `MASSE_VELO_DEFAUT_KG`.

    Le mainteneur l'a dit : « une masse approximative par vélo suffit, 1 kg
    sur 100 kg fait 1 % en montée et rien sur le plat ».
    """
    return config.cycliste.masse_kg + (
        velo.masse_kg if velo.masse_kg is not None else MASSE_VELO_DEFAUT_KG
    )


def motif_exclusion(entree: EntreeCache, config: Config, velo: Velo) -> str | None:
    """Pourquoi cette sortie n'est pas calibrable, ou `None` si elle l'est.

    Rendre le motif, et pas seulement un booléen, permet à la commande de dire
    « 102 calibrables, 8 trop courtes, 2 en groupe » au lieu d'un nombre nu.
    """
    if not est_sport_velo(entree.sport):
        return "pas du vélo"
    if en_interieur(entree):
        return "home-trainer"
    if rattacher_velo(entree, config) != velo.nom:
        return "autre vélo"
    if entree.puissance_moy_w is None:
        return "sans puissance"
    if (entree.distance_m or 0.0) < DISTANCE_MINIMALE_M:
        return "moins de 20 km"
    nom = str(entree.meta.get("nom") or "").casefold()
    for mot in config.calibration.mots_groupe:
        if mot and mot in nom:
            return f"nom « {mot} »"
    return None


def motif_multisport(activite: Activite | None) -> str | None:
    """`MOTIF_MULTISPORT` si ce fichier ne contient pas *que* du vélo, sinon `None`.

    Trois signes, et un seul suffit :

    - `meta["sessions"]` vaut plus de 1 — le lecteur FIT l'y met quand le
      fichier porte plusieurs trames `session` ;
    - un avertissement de lecture parle de sessions multiples (même cause, vue
      de l'autre côté : un fichier relu par une version qui n'écrivait pas
      encore la clé le dit quand même) ;
    - le sport **du fichier** n'est pas cycliste.

    Ce dernier point ne fait pas doublon avec `motif_exclusion`, qui regarde le
    sport de l'**index** : celui-ci vient d'Intervals, qui annonce « Ride »
    pour le segment vélo d'un triathlon alors que le FIT d'origine, partagé
    entre les trois segments, contient aussi la natation et la course. Relu
    entièrement, un tel fichier donne une « sortie » qui commence à 3 km/h dans
    l'eau : la calibrer reviendrait à demander au modèle d'expliquer une
    brasse par de la traînée aérodynamique.

    Une activité absente (fichier illisible) rend `None` : on ne sait pas,
    donc on ne juge pas — la commande la signalera pour ce qu'elle est.
    """
    if activite is None:
        return None
    sessions = activite.meta.get("sessions")
    if isinstance(sessions, (int, float)) and sessions > 1:
        return MOTIF_MULTISPORT
    for avertissement in activite.avertissements:
        if "session" in str(avertissement).casefold():
            return MOTIF_MULTISPORT
    if not est_sport_velo(activite.sport):
        return MOTIF_MULTISPORT
    return None


def sorties_calibrables_et_motifs(
    cache: Cache,
    config: Config,
    velo: Velo,
    *,
    depuis: date | None = None,
    relire: Callable[[str], Activite | None] | None = None,
) -> tuple[list[EntreeCache], dict[str, int]]:
    """(sorties utilisables, décompte des sorties **de ce vélo** écartées et pourquoi).

    `relire` est le seul moyen d'atteindre le contenu d'un fichier : l'index ne
    dit pas combien de sessions il porte. Il n'est appelé que sur les sorties
    qui ont déjà passé tous les filtres à bon marché, donc jamais sur les
    footings ni sur les sorties de l'autre vélo. Sans lui, la fonction se
    comporte exactement comme avant : le motif « multisport » n'existe pas.

    Les motifs « pas du vélo », « autre vélo » et « home-trainer » ne sont pas
    comptés : ils décrivent le reste du cache, pas ce que ce vélo a perdu.
    """
    depuis = depuis if depuis is not None else config.historique_depuis
    hors_sujet = ("pas du vélo", "autre vélo", "home-trainer")
    retenues: list[EntreeCache] = []
    motifs: dict[str, int] = {}
    for entree in cache.lister(depuis=depuis):
        motif = motif_exclusion(entree, config, velo)
        if motif is None and relire is not None:
            motif = motif_multisport(relire(entree.identifiant))
        if motif is None:
            retenues.append(entree)
        elif motif not in hors_sujet:
            motifs[motif] = motifs.get(motif, 0) + 1
    retenues.sort(key=lambda e: (e.debut or _JAMAIS, e.identifiant))
    return (retenues, motifs)


def sorties_calibrables(
    cache: Cache,
    config: Config,
    velo: Velo,
    *,
    depuis: date | None = None,
    relire: Callable[[str], Activite | None] | None = None,
) -> list[EntreeCache]:
    """Les sorties utilisables pour calibrer ce vélo, de la plus ancienne à la plus récente."""
    return sorties_calibrables_et_motifs(
        cache, config, velo, depuis=depuis, relire=relire
    )[0]


# --- les deux passes ----------------------------------------------------------


@dataclass
class SortieCalibration:
    """Une sortie prête à calibrer : son enregistrement et l'archive météo du jour."""

    activite: Activite
    vent: list[HeureArchive] = field(default_factory=list)
    identifiant: str = ""

    @property
    def jour(self) -> date | None:
        return self.activite.debut.date() if self.activite.debut else None

    @property
    def nom(self) -> str:
        return str(self.activite.meta.get("nom") or self.activite.fichier or self.identifiant)


@dataclass
class RapportCalibration:
    """Tout ce qu'une calibration a trouvé, mesuré et écarté — de quoi la juger."""

    velo: str
    ajustement: Ajustement
    validation: Validation
    passe1: Ajustement
    n_apprentissage: int
    n_validation: int
    groupes: list[tuple[str, float]] = field(default_factory=list)
    """Sorties d'apprentissage écartées au résidu : (nom, part de la distance
    anormalement rapide)."""
    groupes_en_validation: list[tuple[str, float]] = field(default_factory=list)
    """Sorties de **test** que le même critère désigne. Elles restent dans la
    validation — ce sont de vraies sorties — mais il faut savoir qu'elles y
    sont quand on lit l'erreur."""
    echantillons: int = 0
    echantillons_retenus: int = 0
    motifs: dict[str, int] = field(default_factory=dict)
    echantillons_sans_vent: int = 0


def partager(
    sorties: Sequence[SortieCalibration], part_validation: float
) -> tuple[list[SortieCalibration], list[SortieCalibration]]:
    """(apprentissage, validation) : les plus récentes en validation (contrat §3).

    Partager par date et non au hasard est le seul partage honnête ici : un
    tirage aléatoire mettrait dans le test des sorties voisines, faites le même
    mois avec le même matériel, et flatterait le modèle.
    """
    ordonnees = sorted(sorties, key=lambda s: (s.jour or date.min, s.nom))
    if len(ordonnees) < 2:
        return (list(ordonnees), [])
    n_test = max(1, min(len(ordonnees) - 1, round(len(ordonnees) * part_validation)))
    coupe = len(ordonnees) - n_test
    return (ordonnees[:coupe], ordonnees[coupe:])


def calibrer_en_deux_passes(
    sorties: Sequence[SortieCalibration],
    *,
    velo: str,
    masse_totale_kg: float,
    part_validation: float = 0.25,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> RapportCalibration:
    """Calibre, repère les sorties en groupe au résidu, recalibre sans elles, valide.

    Une seule itération, comme décidé le 13/09 : « calibrer d'abord sur les
    sorties sûres, puis utiliser le modèle obtenu pour repérer les autres et
    les écarter ; itérer une fois ».
    """
    if not sorties:
        raise ErreurUtilisateur(f"calibration : aucune sortie exploitable pour le vélo {velo}")
    apprentissage, validation_sorties = partager(sorties, part_validation)

    # Indexé par **position** dans `apprentissage`, et non par une clé
    # reconstruite : `identifiant` vaut `""` par défaut et `nom` retombe sur le
    # nom du fichier, si bien que deux sorties sans identifiant nommées
    # « Sortie du matin » s'écrasaient l'une l'autre — elles disparaissaient
    # alors de `tous` **et** de `restants` sans un mot. La commande passe
    # toujours un identifiant, donc c'était sans effet sur elle ; un appelant
    # de bibliothèque, lui, perdait des échantillons.
    par_sortie = [
        echantillonner(s.activite, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
        for s in apprentissage
    ]
    tous = [e for liste in par_sortie for e in liste]
    motifs: dict[str, int] = {}
    for e in tous:
        if not e.retenu:
            motifs[e.motif] = motifs.get(e.motif, 0) + 1

    passe1 = calibrer(tous, masse_totale_kg=masse_totale_kg)
    p1 = passe1.parametres()

    groupes: list[tuple[str, float]] = []
    gardees: list[int] = []
    for rang, s in enumerate(apprentissage):
        en_groupe, part = detecter_groupe(
            s.activite, p1, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        if en_groupe:
            groupes.append((s.nom, part))
        else:
            gardees.append(rang)

    restants = [e for rang in gardees for e in par_sortie[rang]]
    passe2 = calibrer(restants, masse_totale_kg=masse_totale_kg) if gardees else passe1
    p2 = passe2.parametres()

    validation = valider([(s.activite, s.vent) for s in validation_sorties], p2)
    groupes_test = []
    for s in validation_sorties:
        en_groupe, part = detecter_groupe(
            s.activite, p2, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        if en_groupe:
            groupes_test.append((s.nom, part))

    return RapportCalibration(
        velo=velo,
        ajustement=passe2,
        validation=validation,
        passe1=passe1,
        n_apprentissage=len(gardees),
        n_validation=len(validation_sorties),
        groupes=groupes,
        groupes_en_validation=groupes_test,
        echantillons=len(tous),
        echantillons_retenus=sum(1 for e in tous if e.retenu),
        motifs=dict(sorted(motifs.items(), key=lambda kv: (-kv[1], kv[0]))),
        echantillons_sans_vent=sum(1 for e in tous if e.retenu and not e.vent_connu),
    )

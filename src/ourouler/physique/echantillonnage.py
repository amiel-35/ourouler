"""Les échantillons de la calibration : des tronçons de sortie qualifiés, avec leur vent.

Sorti de `physique/calibration.py`, qui réexporte ces noms. Physique pure
comme lui : des objets en entrée, aucun chemin, réseau ni configuration.
Mêmes calculs, dans le même ordre, qu'avant le déplacement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from ourouler.noyau.activite import Activite, Point
from ourouler.noyau.meteo import HeureArchive
from ourouler.noyau.trace import PointTrace, cap_deg, distance_m
from ourouler.physique.modele import (
    RENDEMENT_DEFAUT,
    RHO_DEFAUT,
    masse_volumique_air,
    vent_au_cycliste,
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

MOTIF_RETENU = ""


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
    pas à la calibration mais à `services.comparer`, qui range les tronçons par
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

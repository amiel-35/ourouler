"""Modèle partagé d'un tracé (parcours), indépendant du moteur qui l'a produit.

Un `Trace` vient de BRouter (avec ses `segments` décrits par les messages du
moteur) ou d'un GPX importé (sans segments). Les outils géométriques de ce
module servent aux coûts (virages, sens de boucle) et à la météo le long du
tracé (cap local).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RAYON_TERRE_M = 6_371_000.0
#: Distance sous laquelle premier et dernier point font une boucle fermée.
FERMETURE_M = 300.0


@dataclass(frozen=True)
class PointTrace:
    lat: float
    lon: float
    alt_m: float | None
    dist_m: float  # distance cumulée depuis le départ


@dataclass
class Segment:
    """Un tronçon homogène tel que le moteur le décrit (tags OSM identiques)."""

    debut_idx: int  # indices dans `Trace.points`, inclusifs
    fin_idx: int
    longueur_m: float
    tags: dict[str, str]


@dataclass
class Trace:
    nom: str
    points: list[PointTrace]
    segments: list[Segment]  # vide pour un GPX importé
    distance_m: float
    denivele_m: float | None
    temps_moteur_s: float | None  # estimation du moteur, informative seulement
    meta: dict = field(default_factory=dict)  # sérialisable JSON

    def bornee(self) -> bool:
        """Vrai si le tracé revient à moins de `FERMETURE_M` de son départ."""
        if len(self.points) < 2:
            return False
        return distance_m(self.points[0], self.points[-1]) < FERMETURE_M


def distance_m(a: PointTrace, b: PointTrace) -> float:
    """Distance haversine entre deux points, en mètres."""
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(h))


def cap_deg(a: PointTrace, b: PointTrace) -> float:
    """Azimut initial de a vers b, en degrés dans [0, 360)."""
    la1, la2 = math.radians(a.lat), math.radians(b.lat)
    dlo = math.radians(b.lon - a.lon)
    x = math.sin(dlo) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return math.degrees(math.atan2(x, y)) % 360


def sens_boucle(trace: Trace) -> str:
    """« horaire », « antihoraire » ou « indetermine » (non bornée ou aire quasi nulle).

    Aire signée (formule du lacet) dans une projection locale équirectangulaire
    centrée sur le premier point : positive = antihoraire (sens trigonométrique
    avec x vers l'est et y vers le nord), négative = horaire.
    """
    if not trace.bornee() or len(trace.points) < 3:
        return "indetermine"
    lat0 = math.radians(trace.points[0].lat)
    xy = [
        (math.radians(p.lon) * math.cos(lat0) * RAYON_TERRE_M, math.radians(p.lat) * RAYON_TERRE_M)
        for p in trace.points
    ]
    aire2 = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1], strict=True):
        aire2 += x1 * y2 - x2 * y1
    # Une boucle de 10 km a une aire de l'ordre du km² ; sous 10 000 m² c'est un aller-retour.
    if abs(aire2) / 2 < 10_000:
        return "indetermine"
    return "antihoraire" if aire2 > 0 else "horaire"

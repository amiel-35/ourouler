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

#: Provenances de `Trace.denivele_m`, rangées dans `meta["denivele_source"]`.
#: Le « filtered ascend » du moteur et le D+ recalculé à la relecture d'un GPX
#: divergent de 10 à 32 % sur les tracés mesurés, dans les deux sens : afficher
#: un chiffre sans dire d'où il vient laisse l'écart inexplicable (un
#: désaccord s'affiche comme un désaccord).
DENIVELE_MOTEUR = "moteur"
DENIVELE_GPX_RELU = "gpx relu"
#: Dénivelé recalculé sur le parcours réellement roulé, demi-tours compris
#: (`seance.placement.trace_parcourue`) : ce n'est ni le D+ du moteur ni celui
#: du tracé d'origine, puisqu'un aller-retour monte deux fois la même côte.
DENIVELE_PARCOURS = "parcours placé"

#: Dénivelé recalculé sur l'altitude du **tracé rerouté** par BRouter, pour une
#: trace dont l'altitude d'origine vient d'un appareil (baromètre) ou d'un
#: fichier importé. Les deux sources accumulent du bruit qu'aucun seuil ne
#: rattrape correctement : mesuré sur une sortie de 86 km,
#: un altimètre barométrique fabrique 20 cm de bruit par point, soit 1 563 m
#: de fausse montée sur une amplitude d'altitude réelle de 41 m. La carte
#: d'altitude que BRouter connaît du terrain n'a pas ce défaut — c'est la
#: même idée que Strava recalculant le D+ sur sa propre carte plutôt que sur
#: celle de l'appareil.
#:
#: **Ce n'est pas le dénivelé du parcours réellement roulé.** La géométrie
#: reroutée s'écarte du tracé réel de 2 m en médiane (mesuré sur trois
#: sorties réelles) : c'est le profil de la route que
#: BRouter a choisie, pas exactement celle roulée.
DENIVELE_REROUTE = "tracé rerouté"

#: Montées inférieures à ce seuil : du bruit d'altimètre, pas du dénivelé.
#: BRouter appelle cela « filtered ascend » ; on fait pareil, plus simplement.
SEUIL_DENIVELE_M = 2.0


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
    #: Coût par kilomètre que le moteur attribue au tronçon (colonne
    #: `CostPerKm` des messages BRouter) : c'est le jugement du routeur
    #: lui-même sur le trafic. `None` quand la source ne le donne pas — un
    #: GPX importé, ou un serveur qui ne renvoie pas la colonne. Le champ a
    #: une valeur par défaut pour que les `Segment(debut, fin, longueur,
    #: tags)` déjà écrits continuent de se construire.
    cout_km: float | None = None
    #: Tags OSM du **nœud où le tronçon se termine** (colonne `NodeTags` des
    #: messages BRouter) : `{"highway": "traffic_signals"}` pour un feu,
    #: `{"highway": "crossing"}` pour un passage piéton. Vide quand le nœud
    #: n'en porte pas, et vide aussi pour une source qui ne les donne pas (un
    #: GPX importé) — un dictionnaire vide veut donc dire « rien de connu »,
    #: jamais « carrefour libre » : c'est `seance.terrain` qui en tire les
    #: conséquences, et qui dit ce qu'il ne sait pas.
    node_tags: dict[str, str] = field(default_factory=dict)


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


def denivele_filtre(points: list[PointTrace]) -> float | None:
    """Le D+ du tracé, ou None si aucun point n'a d'altitude.

    Une montée n'est comptée que si elle dépasse `SEUIL_DENIVELE_M` depuis la
    dernière référence. Ce n'est pas un lissage : le seuil efface le bruit
    **strictement plus petit que lui**, et rien d'autre. Mesuré sur un profil
    de 1 000 points (test `test_ce_que_le_seuil_de_denivele_fait_vraiment`) :

    | profil | D+ brut | après le seuil |
    |---|---|---|
    | plat, bruit ±1 m | 334 m | 0 m |
    | montée régulière de 20 m, bruit ±1 m | 345 m | 19 m |
    | plat, bruit ±2,5 m | 832 m | 550 m |

    Autrement dit : sous un mètre d'oscillation, le seuil rend le chiffre
    exploitable et conserve le vrai dénivelé ; au-delà de 2 m, il ne protège
    plus de grand-chose. Le chiffre reste indicatif — le moteur donne son
    propre « filtered ascend », qu'on préfère quand on l'a, et la provenance
    est écrite dans `meta["denivele_source"]`.
    """
    altitudes = [p.alt_m for p in points if p.alt_m is not None]
    if len(altitudes) < 2:
        return None
    total = 0.0
    reference = altitudes[0]
    for altitude in altitudes[1:]:
        ecart = altitude - reference
        if ecart >= SEUIL_DENIVELE_M:
            total += ecart
            reference = altitude
        elif ecart <= -SEUIL_DENIVELE_M:
            reference = altitude
    return total

"""Greffe les tags OSM d'un tracé rerouté sur la géométrie d'un GPX importé.

Un GPX importé (`boucle.gpx.lire_gpx_trace`) n'a pas de `segments` : BRouter
ne l'a jamais vu, donc aucun tag OSM, aucun `cout_km`, aucun `node_tags` — les
kilomètres de trafic, de revêtement et les feux du tracé restent inconnus
(`couts.evaluer` marque alors `trace.meta["couts_partiels"] = True`).

**On ne remplace pas la géométrie du GPX.** L'utilisateur a donné *son*
tracé ; le rendre modifié par le routeur serait un mensonge, et pour un
organisateur de BRM le tracé est le sujet. On rejoue le GPX dans BRouter
(points de passage espacés, même règle que `apprentissage.routes` — un
tracé rerouté, jetable, qui ne sert qu'à porter des tags), puis pour chaque
point du GPX on cherche le tronçon rerouté le plus proche et on lui
emprunte ses tags, son `cout_km` et les tags de son nœud de fin.

**Le regroupement se fait par tronçon d'origine, pas seulement par tags
identiques.** Deux points consécutifs du GPX rejoignent le même `Segment`
de sortie s'ils se sont rapprochés du **même** tronçon rerouté — une
condition plus stricte que « mêmes tags », qui aurait fusionné deux
tronçons voisins de même nature (deux `tertiary` bout à bout) en perdant
le nœud qui les sépare. C'est ce qui permet d'attribuer un feu ou un stop
au bon endroit : `Segment.node_tags` du tronçon d'origine est reporté sur
le groupe qui en hérite, comme BRouter le fait pour ses propres tronçons
(« le nœud où le tronçon se termine »). Un même tronçon rerouté peut
réapparaître dans plusieurs groupes non consécutifs (un aller-retour sur la
même route, un point isolément mal apparié) : son nœud de fin est alors
reporté sur chacun, ce qui peut compter un feu plusieurs fois — un
compromis assumé, pas caché, plutôt qu'un mécanisme de correspondance plus
complexe pour un cas rare.

**Le seuil de rapprochement.** Au-delà de `SEUIL_RAPPROCHEMENT_M`, un point
n'hérite de rien : lui attribuer les tags d'une route à 275 m serait faux.
Mesuré le 18/09/2026 sur des sorties réelles du mainteneur (méthode : router
un tracé GPS réel via des points de passage tous les 1 500 m, puis mesurer
la distance de chaque point du tracé réel au tronçon rerouté le plus
proche) : médiane 1,6 à 2,4 m, 90ᵉ centile 3,5 à 8,4 m, maximum 23 à 433 m
selon la sortie — le routeur préfère parfois une autre route. **25 m**
(proposition initiale du mainteneur, confirmée par la mesure) couvre
largement la médiane et le 90ᵉ centile de chaque sortie mesurée, tout en
écartant les vraies divergences de tracé : sur quatre sorties rejouées,
0 à 8,2 % des points seulement tombaient au-delà.

Les points qui n'ont rien trouvé dans le seuil ne disparaissent pas : ils
forment des `Segment` aux tags vides, que `boucle.couts.evaluer` range déjà
dans `km_non_classe` — la catégorie « on ne sait pas classer » existe,
on ne la contourne pas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ourouler.boucle.geometrie import _distance_segment_m
from ourouler.boucle.trace import RAYON_TERRE_M, PointTrace, Segment, Trace, distance_m

#: Voir la docstring du module pour la mesure qui le justifie. Point de
#: départ du mainteneur, confirmé sur quatre sorties réelles rejouées.
SEUIL_RAPPROCHEMENT_M = 25.0

#: Taille de maille du quadrillage qui limite la recherche du tronçon
#: rerouté le plus proche. Sans lui, apparier chaque point d'un GPX contre
#: chaque tronçon rerouté est en O(n×m) : mesuré sur un tracé réel de 107 km
#: (2 801 points GPX × 2 735 tronçons reroutés), 12,5 s en recherche naïve —
#: un brevet plus long et enregistré plus finement (un BRM de 300 ou 600 km
#: à 1 Hz compte des dizaines de milliers de points) dépasserait largement
#: la minute. La maille doit couvrir `SEUIL_RAPPROCHEMENT_M` avec une marge :
#: le double, pour absorber l'approximation de la projection locale
#: (`_projeter`) sans repasser en O(n×m).
TAILLE_MAILLE_M = 50.0


@dataclass
class Greffage:
    """Ce que le greffage a produit : les `Segment` à poser sur le GPX, et ce qu'on en sait."""

    segments: list[Segment]
    #: Kilomètres du GPX dont aucun point n'a trouvé de tronçon assez proche.
    km_sans_tag: float
    #: Le seuil réellement appliqué — pour que `trace.meta` le dise (règle
    #: absolue 5 : deux exécutions à des seuils différents ne doivent pas se
    #: comparer en silence).
    seuil_m: float

    @property
    def exploitable(self) -> bool:
        """Faux si aucun point du GPX n'a trouvé de tronçon assez proche.

        Un greffage entièrement vide n'apporte rien : mieux vaut le chemin
        dégradé (`couts_partiels` inchangé) qu'une trace qui prétend avoir
        des tags alors qu'aucun n'a pu être attribué.
        """
        return any(s.tags for s in self.segments)


def greffer(
    trace_gpx: Trace, trace_reroutee: Trace, *, seuil_m: float = SEUIL_RAPPROCHEMENT_M
) -> Greffage:
    """Les `Segment` à poser sur `trace_gpx`, tags empruntés à `trace_reroutee`.

    Voir la docstring du module pour l'algorithme et le choix du seuil. Un
    `trace_reroutee` sans tronçon (BRouter a répondu, mais sans messages
    exploitables) rend un greffage vide et non exploitable : à l'appelant de
    retomber sur le chemin dégradé.
    """
    arcs = _arcs(trace_reroutee)
    if not arcs or len(trace_gpx.points) < 2:
        return Greffage(segments=[], km_sans_tag=trace_gpx.distance_m / 1000.0, seuil_m=seuil_m)

    grille, lat0 = _grille(arcs)
    indices = [_plus_proche(p, arcs, grille, lat0, seuil_m) for p in trace_gpx.points]
    segments = _grouper(trace_gpx.points, indices, trace_reroutee.segments)
    km_sans_tag = sum(s.longueur_m for s in segments if not s.tags) / 1000.0
    return Greffage(segments=segments, km_sans_tag=km_sans_tag, seuil_m=seuil_m)


# --- tronçons reroutés, décomposés en arcs -------------------------------------


def _arcs(trace_reroutee: Trace) -> list[tuple[int, PointTrace, PointTrace]]:
    """(indice du `Segment` d'origine, point de départ, point d'arrivée) par paire consécutive.

    Un `Segment` peut porter plusieurs points bruts (`debut_idx`..`fin_idx`) :
    on le décompose en arcs pour mesurer la distance à la **ligne**, pas
    seulement à ses deux extrémités — même raison que `boucle.geometrie`.
    """
    points = trace_reroutee.points
    arcs: list[tuple[int, PointTrace, PointTrace]] = []
    for idx, segment in enumerate(trace_reroutee.segments):
        debut = max(0, segment.debut_idx)
        fin = min(len(points) - 1, segment.fin_idx)
        for i in range(debut, fin):
            arcs.append((idx, points[i], points[i + 1]))
    return arcs


# --- quadrillage : limiter la recherche du plus proche -------------------------


def _projeter(lat: float, lon: float, lat0_rad: float) -> tuple[float, float]:
    """(x, y) en mètres, projection équirectangulaire locale centrée sur `lat0_rad`.

    Même formule que `boucle.trace.sens_boucle` : exacte au centre, dérive
    doucement avec la distance — sans conséquence ici, la projection ne sert
    qu'à quadriller pour une recherche de voisinage, la distance retenue
    reste celle, sphérique, de `_distance_segment_m`.
    """
    x = math.radians(lon) * math.cos(lat0_rad) * RAYON_TERRE_M
    y = math.radians(lat) * RAYON_TERRE_M
    return x, y


def _cellule(x: float, y: float) -> tuple[int, int]:
    return (math.floor(x / TAILLE_MAILLE_M), math.floor(y / TAILLE_MAILLE_M))


def _grille(
    arcs: list[tuple[int, PointTrace, PointTrace]],
) -> tuple[dict[tuple[int, int], list[int]], float]:
    """Index des arcs par maille, et la latitude de référence de la projection.

    Chaque arc est rangé dans **toutes** les mailles de son rectangle
    englobant, élargi d'une maille de marge : un point à rapprocher tombe
    forcément dans une maille où l'arc a été rangé, quelle que soit sa
    position le long de l'arc (le rectangle englobant d'un segment de droite
    contient tout le segment).
    """
    lat0_rad = math.radians(arcs[0][1].lat)
    grille: dict[tuple[int, int], list[int]] = {}
    for indice, (_, a, b) in enumerate(arcs):
        xa, ya = _projeter(a.lat, a.lon, lat0_rad)
        xb, yb = _projeter(b.lat, b.lon, lat0_rad)
        cx0, cx1 = sorted((math.floor(xa / TAILLE_MAILLE_M), math.floor(xb / TAILLE_MAILLE_M)))
        cy0, cy1 = sorted((math.floor(ya / TAILLE_MAILLE_M), math.floor(yb / TAILLE_MAILLE_M)))
        for cx in range(cx0 - 1, cx1 + 2):
            for cy in range(cy0 - 1, cy1 + 2):
                grille.setdefault((cx, cy), []).append(indice)
    return grille, lat0_rad


def _plus_proche(
    point: PointTrace,
    arcs: list[tuple[int, PointTrace, PointTrace]],
    grille: dict[tuple[int, int], list[int]],
    lat0_rad: float,
    seuil_m: float,
) -> int | None:
    """L'indice (dans `trace_reroutee.segments`) du tronçon le plus proche, `None` au-delà du seuil."""
    x, y = _projeter(point.lat, point.lon, lat0_rad)
    cx, cy = _cellule(x, y)
    candidats: set[int] = set()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            candidats.update(grille.get((cx + dx, cy + dy), ()))
    if not candidats:
        return None
    meilleure_distance = math.inf
    meilleur_idx: int | None = None
    for i in candidats:
        idx_segment, a, b = arcs[i]
        d = _distance_segment_m(point, a, b)
        if d < meilleure_distance:
            meilleure_distance, meilleur_idx = d, idx_segment
    if meilleure_distance > seuil_m:
        return None
    return meilleur_idx


# --- regroupement en segments de sortie -----------------------------------------


def _grouper(
    points: list[PointTrace],
    indices: list[int | None],
    segments_reroutes: list[Segment],
) -> list[Segment]:
    """Les points consécutifs rapprochés du même tronçon rerouté, en un `Segment`.

    La longueur est la somme haversine réelle du groupe, pas celle du
    tronçon d'origine (qui peut être bien plus long ou plus court que ce que
    le GPX en a réellement recoupé).
    """
    resultat: list[Segment] = []
    debut = 0
    for i in range(1, len(indices) + 1):
        if i == len(indices) or indices[i] != indices[debut]:
            resultat.append(_construire(points, debut, i - 1, indices[debut], segments_reroutes))
            debut = i
    return resultat


def _construire(
    points: list[PointTrace],
    debut: int,
    fin: int,
    idx_segment: int | None,
    segments_reroutes: list[Segment],
) -> Segment:
    """Construit le `Segment` de sortie couvrant `[debut, fin]`, longueur haversine incluse.

    La longueur couvre aussi l'arête qui **quitte** `fin` vers le premier
    point du groupe suivant : sans elle, cette arête n'appartenait à aucun
    groupe (ni le précédent, dont l'intervalle s'arrêtait juste avant, ni le
    suivant, qui ne commence qu'après elle), et la somme des longueurs de
    sortie était inférieure à la distance réelle du GPX — silencieusement,
    d'une arête à chaque frontière entre deux tronçons. `min(…, len(points) -
    2)` protège le dernier groupe : le dernier point du tracé n'a pas
    d'arête sortante.
    """
    derniere_arete = min(fin, len(points) - 2)
    longueur = sum(distance_m(points[i], points[i + 1]) for i in range(debut, derniere_arete + 1))
    if idx_segment is None:
        return Segment(debut_idx=debut, fin_idx=fin, longueur_m=longueur, tags={})
    origine = segments_reroutes[idx_segment]
    return Segment(
        debut_idx=debut,
        fin_idx=fin,
        longueur_m=longueur,
        tags=dict(origine.tags),
        cout_km=origine.cout_km,
        node_tags=dict(origine.node_tags),
    )

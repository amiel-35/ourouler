"""Antennes (culs-de-sac) d'un tracé : détection et élagage.

Une **antenne** est une portion du tracé parcourue deux fois, à l'aller puis
au retour : le moteur pousse le cycliste dans une impasse, lui fait faire
demi-tour, et le ramène exactement par où il est venu. C'est le seul défaut
de tracé que le mainteneur veut corriger (contrat du sprint 3, §1) : les
traversées de bourg, elles, sont acceptées.

Ces crochets viennent des points de passage que BRouter place lui-même en
mode boucle : quand l'un d'eux tombe à côté de la route, le moteur va le
chercher et revient. Les paramètres `correct_misplaced_via_points` du moteur
sont censés l'éviter — mesuré sans effet sur le serveur du mainteneur, voir
`connecteurs/brouter.py`. On corrige donc le tracé après coup.

Comment on les reconnaît
------------------------

La trace est d'abord **sous-échantillonnée à ~10 m** : les points BRouter
sont espacés de quelques mètres, et raisonner sur eux coûterait cher sans
rien apporter (la tolérance est de 20 m).

Pour chaque point `k` qui ressemble à un demi-tour (voir
`RATIO_RETOURNEMENT`), on fait grandir le retour point par point. À chaque
pas, `i` est le point de l'aller d'où l'on est parti pour couvrir la
distance déjà refaite au retour — c'est le point de jonction candidat. La
portion `[k, j]` est une antenne si **chacun** de ses points est à moins de
`tolerance_m` d'un point de l'aller `[i, k]` (distance de Hausdorff dirigée
du retour vers l'aller).

Deux garde-fous, et ils ne disent pas la même chose :

- `fenetre_m` borne la longueur **totale** (aller + retour). Un aller-retour
  qui continue de se superposer au-delà de la fenêtre n'est **pas** une
  antenne tronquée à la fenêtre : c'est un aller-retour assumé sur une route
  (une fin de boucle qui repasse par le départ), et la candidate est
  abandonnée entièrement. Rendre ses 600 premiers mètres aurait coupé une
  vraie route.
- `LONGUEUR_MIN_M` écarte les micro-allers-retours. Sans lui, deux points
  sous-échantillonnés consécutifs sont toujours à moins de 20 m l'un de
  l'autre : *tout* point du tracé serait le départ d'une « antenne » de
  20 m.

Ce que l'élagage garde et ce qu'il perd
---------------------------------------

`elaguer` remplace `[debut_idx, fin_idx]` par le seul point de jonction,
recalcule les distances cumulées, réindexe les `segments` (un tronçon
entièrement dans l'antenne disparaît, un tronçon à cheval est tronqué) et
**recalcule** `distance_m` comme somme haversine — d'où
`meta["distance_source"] = "recalculee"` : ce n'est plus le `track-length`
du moteur.

Le dénivelé, lui, **reste celui du moteur** : son « filtered ascend » n'est
pas décomposable par tronçon, on ne sait donc pas ce que l'antenne en
retirait. Il surestime d'autant, et `meta["denivele_approximatif"] = True`
le dit plutôt que de laisser passer un chiffre pour une mesure (règle
absolue 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.boucle.trace import PointTrace, Segment, Trace, distance_m

#: Espacement du sous-échantillonnage. En dessous, on paye la résolution de
#: BRouter (quelques mètres entre points) sans gagner en justesse : la
#: tolérance de rattachement est de 20 m.
PAS_ECHANTILLON_M = 10.0

#: Longueur totale (aller + retour) en dessous de laquelle un aller-retour
#: n'est pas traité comme une antenne. Un rond-point, un décalage de voie ou
#: le bruit d'altimétrie produisent des reparcours de quelques dizaines de
#: mètres ; les crochets de points de passage mal placés, eux, font 200 m à
#: 1 km. Élaguer en dessous de ce seuil ferait plus de dégâts que de bien.
LONGUEUR_MIN_M = 100.0

#: Demi-largeur, en nombre d'échantillons, de la fenêtre qui sert à repérer
#: un demi-tour : on compare la corde entre `k - 3` et `k + 3` à la longueur
#: réellement parcourue entre les deux (~60 m).
DEMI_FENETRE_RETOURNEMENT = 3

#: Rapport corde / longueur parcourue au-dessous duquel `k` est un candidat
#: demi-tour. Une ligne droite donne 1,0 ; un virage à 90° donne 0,71 ; un
#: demi-tour donne presque 0. Le seuil à 0,5 laisse donc passer les
#: demi-tours et les épingles très serrées, jamais un virage ordinaire. Ce
#: n'est qu'un **pré-filtre** : il décide où regarder, pas ce qui est une
#: antenne.
RATIO_RETOURNEMENT = 0.5

#: Décalage maximal, en nombre d'échantillons, entre un point du retour et le
#: point de l'aller auquel on l'apparie. Le retour d'une antenne repasse par
#: la même route : à distance parcourue égale depuis le demi-tour, on doit
#: retomber au même endroit, à ±20 m près. Sans cette contrainte, un point
#: situé **après** la jonction s'appariait au point de jonction lui-même, et
#: l'antenne débordait sur la vraie route des deux côtés.
FENETRE_APPARIEMENT = 2

#: Tolérance de flottant sur les comparaisons de distance parcourue. Un
#: aller-retour parfait était refusé parce que l'aller mesurait
#: 199,999 999 999 m pour un retour de 200,000 000 001 m : la comparaison
#: d'arcs égaux ne peut pas être exacte.
EPSILON_M = 1e-6

#: Valeur de `meta["distance_source"]` après élagage.
DISTANCE_RECALCULEE = "recalculee"


@dataclass(frozen=True)
class Antenne:
    """Un aller-retour repéré dans `trace.points`, bornes incluses."""

    debut_idx: int
    fin_idx: int
    longueur_m: float  # aller + retour


def detecter(trace: Trace, *, fenetre_m: float = 600, tolerance_m: float = 20) -> list[Antenne]:
    """Les antennes du tracé, maximales et sans chevauchement, dans l'ordre du parcours.

    `fenetre_m` borne la longueur totale d'une antenne (aller + retour) ;
    `tolerance_m` est l'écart maximal admis entre le retour et l'aller.

    Une portion qui se superpose à elle-même **au-delà** de `fenetre_m` n'est
    pas rendue du tout : c'est un aller-retour voulu, pas un crochet.
    """
    if not (fenetre_m > 0 and tolerance_m > 0):
        return []
    cumul = _cumul(trace.points)
    echantillons = _sous_echantillonner(trace.points, cumul, PAS_ECHANTILLON_M)
    if len(echantillons) < 3:
        return []
    points = [trace.points[i] for i in echantillons]
    arc = [cumul[i] for i in echantillons]

    trouvees: list[Antenne] = []
    for k in range(len(points)):
        if not _demi_tour_possible(points, arc, k):
            continue
        bornes = _antenne_autour(points, arc, k, fenetre_m=fenetre_m, tolerance_m=tolerance_m)
        if bornes is None:
            continue
        debut, fin, longueur = bornes
        trouvees.append(
            Antenne(
                debut_idx=echantillons[debut],
                fin_idx=echantillons[fin],
                longueur_m=longueur,
            )
        )
    return _maximales(trouvees)


def elaguer(trace: Trace, antennes: list[Antenne]) -> Trace:
    """Un nouveau `Trace` sans les antennes : distances recalculées, segments réindexés.

    Chaque antenne `[debut_idx, fin_idx]` est remplacée par son seul point de
    jonction (`debut_idx`). Le tracé d'entrée n'est jamais modifié.

    `meta["antennes"]` porte le nombre d'antennes retirées et les mètres
    réellement gagnés (différence des distances cumulées, pas la somme des
    `longueur_m` sous-échantillonnées).
    """
    retenues = _maximales(_bornees(trace, antennes))
    retires = _indices_retires(retenues)
    gardes = [i for i in range(len(trace.points)) if i not in retires]
    if not retenues or len(gardes) < 2:
        # Rien à retirer, ou une antenne qui mangerait le tracé entier : on
        # rend le tracé tel quel plutôt qu'un point isolé.
        return _copie(trace, meta_antennes={"nombre": 0, "metres_retires": 0.0})

    projection = _projection(trace.points, retenues, gardes)
    points = _repointer([trace.points[i] for i in gardes])
    segments = _resegmenter(trace.segments, projection, points, retires)

    ancienne = _cumul(trace.points)[-1] if trace.points else 0.0
    nouvelle = points[-1].dist_m if points else 0.0
    resultat = _copie(
        trace,
        meta_antennes={
            "nombre": len(retenues),
            "metres_retires": round(ancienne - nouvelle, 1),
        },
    )
    resultat.points = points
    resultat.segments = segments
    resultat.distance_m = nouvelle
    resultat.meta["distance_source"] = DISTANCE_RECALCULEE
    # Le « filtered ascend » du moteur n'est pas décomposable par tronçon :
    # on ne sait pas ce que l'antenne en retirait. Le chiffre reste, surestimé,
    # et le dit.
    resultat.meta["denivele_approximatif"] = True
    return resultat


# --- détection ----------------------------------------------------------------


def _cumul(points: Sequence[PointTrace]) -> list[float]:
    """Distances cumulées haversine, recalculées.

    `PointTrace.dist_m` porte déjà ce cumul quand le tracé vient de BRouter ou
    d'un GPX, mais un tracé fabriqué à la main peut l'avoir laissé à zéro : la
    détection ne doit pas dépendre d'un champ que personne ne garantit.
    """
    cumul = [0.0]
    for a, b in zip(points, points[1:], strict=False):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul[: len(points)]


def _sous_echantillonner(
    points: Sequence[PointTrace], cumul: Sequence[float], pas_m: float
) -> list[int]:
    """Indices des points retenus, espacés d'au moins `pas_m` le long du tracé.

    Le dernier point est toujours retenu : sans lui, une antenne qui finit sur
    le dernier point du tracé serait rognée de quelques mètres.
    """
    if not points:
        return []
    gardes = [0]
    for i in range(1, len(points)):
        if cumul[i] - cumul[gardes[-1]] >= pas_m:
            gardes.append(i)
    if gardes[-1] != len(points) - 1:
        gardes.append(len(points) - 1)
    return gardes


def _demi_tour_possible(points: Sequence[PointTrace], arc: Sequence[float], k: int) -> bool:
    """Vrai si `k` ressemble à un demi-tour : corde courte pour une longue distance parcourue.

    Pré-filtre bon marché, appliqué à tous les points ; sans lui, la recherche
    complète tournerait des millions de fois sur une boucle de 60 km pour ne
    rien trouver 99 fois sur 100.
    """
    avant = k - DEMI_FENETRE_RETOURNEMENT
    apres = k + DEMI_FENETRE_RETOURNEMENT
    if avant < 0 or apres >= len(points):
        return False
    parcourue = arc[apres] - arc[avant]
    if parcourue <= 0:
        return False
    return distance_m(points[avant], points[apres]) / parcourue < RATIO_RETOURNEMENT


def _antenne_autour(
    points: Sequence[PointTrace],
    arc: Sequence[float],
    k: int,
    *,
    fenetre_m: float,
    tolerance_m: float,
) -> tuple[int, int, float] | None:
    """`(debut, fin, longueur)` de l'antenne dont `k` est le demi-tour, ou `None`.

    Le retour grandit point par point. `debut` est à chaque pas le point de
    l'aller d'où il a fallu partir pour couvrir la distance déjà refaite :
    il ne fait que reculer, donc l'aller `[debut, k]` ne fait que grandir, et
    il suffit de vérifier le **nouveau** point du retour (les précédents
    restent appariés).
    """
    debut = k
    meilleure: tuple[int, int, float] | None = None
    for fin in range(k + 1, len(points)):
        retour_m = arc[fin] - arc[k]
        while debut > 0 and arc[k] - arc[debut] < retour_m - EPSILON_M:
            debut -= 1
        if arc[k] - arc[debut] < retour_m - EPSILON_M:
            break  # l'aller ne remonte pas assez loin : début du tracé atteint
        longueur = arc[fin] - arc[debut]
        if longueur > fenetre_m + EPSILON_M:
            # Toujours superposé au-delà de la fenêtre : aller-retour voulu,
            # pas une antenne. On abandonne la candidate entière.
            return None
        if _ecart_a_l_aller(points, debut, k, points[fin]) > tolerance_m:
            break
        jonction = distance_m(points[debut], points[fin])
        if longueur >= LONGUEUR_MIN_M and jonction <= tolerance_m + EPSILON_M:
            # Les deux bouts se rejoignent : c'est bien une jonction, et pas
            # un point pris au hasard de part et d'autre sur la vraie route.
            meilleure = (debut, fin, longueur)
    return meilleure


def _ecart_a_l_aller(
    points: Sequence[PointTrace], debut: int, k: int, point: PointTrace
) -> float:
    """Distance du `point` au plus proche point de l'aller, autour de `debut`.

    L'appariement est cherché **à distance parcourue égale** depuis le
    demi-tour (c'est ce que veut dire « parcouru en sens inverse »), à
    `FENETRE_APPARIEMENT` échantillons près. Comparer au plus proche point de
    tout l'aller laissait un point situé après la jonction s'apparier à la
    jonction elle-même et faisait déborder l'antenne sur la vraie route.

    On compare aux sommets, pas aux segments : à 10 m d'échantillonnage
    l'écart entre les deux vaut au plus 5 m, très en dessous des 20 m de
    tolérance, et le code reste lisible.
    """
    premier = max(0, debut - FENETRE_APPARIEMENT)
    dernier = min(k, debut + FENETRE_APPARIEMENT)
    return min(distance_m(points[m], point) for m in range(premier, dernier + 1))


def _maximales(antennes: Sequence[Antenne]) -> list[Antenne]:
    """Les antennes les plus longues d'abord, sans chevauchement, remises dans l'ordre.

    Le chevauchement est compté **bornes comprises** : deux antennes qui se
    touchent par une borne partagent un point que la première fait disparaître
    (l'élagage garde le point de jonction du *début*, pas celui de la fin).
    Les garder toutes les deux laisserait la seconde sans point de jonction.
    """
    retenues: list[Antenne] = []
    for antenne in sorted(antennes, key=lambda a: (-a.longueur_m, a.debut_idx)):
        if antenne.fin_idx <= antenne.debut_idx:
            continue
        if any(
            antenne.debut_idx <= autre.fin_idx and autre.debut_idx <= antenne.fin_idx
            for autre in retenues
        ):
            continue
        retenues.append(antenne)
    return sorted(retenues, key=lambda a: a.debut_idx)


# --- élagage ------------------------------------------------------------------


def _bornees(trace: Trace, antennes: Sequence[Antenne]) -> list[Antenne]:
    """Les antennes dont les bornes tiennent dans le tracé. Les autres sont ignorées.

    Un appelant qui passe des indices d'un autre tracé (ou négatifs) doit
    obtenir un tracé intact, pas une exception ni des points retirés au hasard.
    """
    dernier = len(trace.points) - 1
    return [
        a
        for a in antennes
        if 0 <= a.debut_idx < a.fin_idx <= dernier
    ]


def _indices_retires(antennes: Sequence[Antenne]) -> set[int]:
    """Les indices que l'élagage supprime : tout sauf le point de jonction."""
    retires: set[int] = set()
    for antenne in antennes:
        retires.update(range(antenne.debut_idx + 1, antenne.fin_idx + 1))
    return retires


def _projection(
    points: Sequence[PointTrace], antennes: Sequence[Antenne], gardes: Sequence[int]
) -> list[int]:
    """Pour chaque ancien indice, son nouvel indice — celui de la jonction s'il a disparu."""
    nouveau = {ancien: i for i, ancien in enumerate(gardes)}
    projection = [0] * len(points)
    for antenne in antennes:
        for i in range(antenne.debut_idx + 1, antenne.fin_idx + 1):
            projection[i] = nouveau[antenne.debut_idx]
    for ancien, i in nouveau.items():
        projection[ancien] = i
    return projection


def _repointer(points: Sequence[PointTrace]) -> list[PointTrace]:
    """Les mêmes points, avec des distances cumulées recalculées depuis le départ."""
    cumul = _cumul(points)
    return [
        PointTrace(lat=p.lat, lon=p.lon, alt_m=p.alt_m, dist_m=d)
        for p, d in zip(points, cumul, strict=True)
    ]


def _resegmenter(
    segments: Sequence[Segment],
    projection: Sequence[int],
    points: Sequence[PointTrace],
    retires: set[int],
) -> list[Segment]:
    """Les tronçons réindexés : ceux de l'antenne disparaissent, ceux à cheval sont tronqués.

    Un tronçon intact garde la longueur que le moteur lui a donnée ; un
    tronçon tronqué la reprend des distances cumulées recalculées — c'est la
    seule mesure dont on dispose pour un morceau de tronçon.
    """
    dernier = len(projection) - 1
    resegmentes: list[Segment] = []
    for segment in segments:
        ancien_debut = min(max(segment.debut_idx, 0), dernier)
        ancien_fin = min(max(segment.fin_idx, 0), dernier)
        debut, fin = projection[ancien_debut], projection[ancien_fin]
        if fin <= debut:
            # Entièrement dans l'antenne (ou réduit à un point) : il disparaît.
            continue
        intact = not any(i in retires for i in range(ancien_debut, ancien_fin + 1))
        longueur = (
            segment.longueur_m if intact else points[fin].dist_m - points[debut].dist_m
        )
        resegmentes.append(
            Segment(debut_idx=debut, fin_idx=fin, longueur_m=longueur, tags=dict(segment.tags))
        )
    return resegmentes


def _copie(trace: Trace, *, meta_antennes: dict) -> Trace:
    """Un `Trace` jumeau, avec `meta["antennes"]` renseigné. L'original n'est pas touché."""
    return Trace(
        nom=trace.nom,
        points=list(trace.points),
        segments=list(trace.segments),
        distance_m=trace.distance_m,
        denivele_m=trace.denivele_m,
        temps_moteur_s=trace.temps_moteur_s,
        meta={**trace.meta, "antennes": meta_antennes},
    )

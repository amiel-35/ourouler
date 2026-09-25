"""Géométrie d'un tracé exposée en JSON : simplifiée, avec son profil d'altitude.

Contrat du lot F0.1 (`docs/journal/ux/front_contrat.md`) : aucune coordonnée d'un
tracé n'existait dans le JSON de `boucle` ou de `sortie`, seulement dans le
GPX écrit sur disque et dans le HTML Leaflet de `sortie/carte.py`
(`docs/journal/ux/discovery_donnees.md` §2, §3 « Page du jour ») — un front web ne
pouvait dessiner aucune carte. Ce module comble ce trou avec `geometrie_json`.

**Le volume.** Un tracé BRouter compte quelques milliers de points ; un GPX
importé à 1 Hz (`boucle --gpx`, `boucle/gpx.py`) peut en compter des dizaines
de milliers : ni l'un ni l'autre ne tient dans une réponse JSON d'API. La
géométrie est donc réduite par l'algorithme de Douglas-Peucker (`simplifier`),
qui ne retire un point que si le remettre déplacerait la ligne simplifiée de
moins de `tolerance_m` à cet endroit précis — c'est la définition même de
l'algorithme, pas une promesse a posteriori. `TOLERANCE_DEFAUT_M = 5.0` : la
précision d'un relevé GPS ou d'une géométrie OSM est déjà de cet ordre, et
sur une carte affichée dans un navigateur, un pixel représente plusieurs
mètres dès qu'on dézoome légèrement — en deçà, la simplification n'efface que
du bruit invisible. Le cycliste doit reconnaître sa route : 5 m ne la
déplacent pas, et `geometrie_json` mesure l'écart réellement introduit
(`simplification.ecart_max_m`) plutôt que de se fier seulement à la garantie
théorique de l'algorithme — la règle absolue « ne rien affirmer sans mesure »
s'applique aussi ici.

**La forme.** `points` est un tableau de paires `[lat, lon]`, pas d'objets
nommés : c'est exactement ce que Leaflet consomme (`L.polyline(points)`)
sans transformation côté front, et répéter des clés `"lat"`/`"lon"` à chaque
point coûterait plusieurs dizaines d'octets par point pour rien à l'échelle
de milliers de points. `profil` est un tableau parallèle de paires
`[dist_m, alt_m]`, **de même longueur et dans le même ordre** que `points` :
le point `i` de `points` correspond à la ligne `i` de `profil`. Séparé plutôt
que fusionné en objets, pour la même raison de volume, et parce que `points`
sert le tracé sur la carte quand `profil` sert la courbe d'altitude sous la
carte — deux consommateurs, deux tableaux, un `zip` trivial pour un front qui
veut les deux ensemble. `alt_m` peut être `null` (aucune altitude connue pour
ce tracé — un GPX importé sans balise `<ele>`, par exemple) mais `dist_m` ne
l'est jamais.

**Les blocs.** `sortie` place les étapes de la séance à des positions
`debut_m`/`longueur_m`, en mètres depuis le départ sur ce même tracé
(`seance/placement.py`, `Emplacement`) — ce ne sont pas des indices dans
`points`, parce que les indices se déplacent avec la simplification (une
tolérance différente change quels points survivent) alors que la distance
cumulée, elle, ne bouge pas : `PointTrace.dist_m` est une propriété du tracé
d'origine, jamais recalculée ici. La colonne `dist_m` de `profil` est
croissante au sens large d'un point simplifié au suivant (elle l'est déjà
dans le tracé d'origine, et simplifier ne fait que retirer des points, jamais
les réordonner) : un front retrouve la position d'un bloc par recherche
dichotomique sur cette colonne, sans ambiguïté, quelle que soit la tolérance
appliquée.
"""

from __future__ import annotations

import math

from ourouler.noyau.trace import RAYON_TERRE_M, PointTrace, Trace, cap_deg, distance_m

#: Voir la docstring du module. Point de départ, pas une constante figée : un
#: appelant qui a besoin d'un tracé plus léger (ou plus fidèle) passe la
#: sienne à `geometrie_json`.
TOLERANCE_DEFAUT_M = 5.0


def geometrie_json(trace: Trace, *, tolerance_m: float = TOLERANCE_DEFAUT_M) -> dict:
    """La géométrie d'un `Trace`, simplifiée, prête pour le JSON d'API.

    Voir la docstring du module pour la forme de `points`/`profil` et le
    choix de `tolerance_m`. `simplification` documente la réduction : nombre
    de points avant/après et écart maximal **réellement mesuré** entre le
    tracé d'origine et la ligne rendue.
    """
    indices, ecart_max_m = _simplifier_indices(trace.points, tolerance_m)
    retenus = [trace.points[i] for i in indices]
    return {
        "points": [[round(p.lat, 6), round(p.lon, 6)] for p in retenus],
        "profil": [
            [round(p.dist_m, 1), None if p.alt_m is None else round(p.alt_m, 1)]
            for p in retenus
        ],
        "simplification": {
            "tolerance_m": tolerance_m,
            "points_origine": len(trace.points),
            "points_rendus": len(retenus),
            "ecart_max_m": round(ecart_max_m, 2),
        },
    }


def simplifier(points: list[PointTrace], tolerance_m: float = TOLERANCE_DEFAUT_M) -> list[PointTrace]:
    """Sous-ensemble de `points` (Douglas-Peucker) à moins de `tolerance_m` de l'original.

    Garde toujours les deux extrémités. Un tracé de 0 ou 1 point est rendu
    tel quel ; deux points confondus ne se simplifient à rien de plus, ils
    sont déjà l'un et l'autre une extrémité.
    """
    indices, _ = _simplifier_indices(points, tolerance_m)
    return [points[i] for i in indices]


def _simplifier_indices(
    points: list[PointTrace], tolerance_m: float
) -> tuple[list[int], float]:
    """Indices retenus et écart maximal réel des points retirés à la ligne rendue.

    Itératif (pile explicite), pas récursif : un GPX à 1 Hz peut dépasser la
    profondeur de récursion par défaut de Python bien avant d'être un
    problème de temps de calcul.

    L'écart maximal se lit gratuitement pendant le même parcours : quand un
    segment n'est **pas** subdivisé (son pire point est à moins de
    `tolerance_m`), ce pire point est, par construction, le point le plus
    loin de la ligne finale sur toute cette portion — puisqu'elle ne bouge
    plus ensuite. Le maximum sur tous les segments non subdivisés est donc
    l'écart réel du tracé complet, sans second passage sur les points.
    """
    n = len(points)
    if n <= 2:
        return list(range(n)), 0.0
    garder = bytearray(n)
    garder[0] = garder[-1] = 1
    ecart_max_m = 0.0
    pile = [(0, n - 1)]
    while pile:
        i, j = pile.pop()
        if j <= i + 1:
            continue
        a, b = points[i], points[j]
        pire_dist, pire_k = -1.0, -1
        for k in range(i + 1, j):
            d = _distance_segment_m(points[k], a, b)
            if d > pire_dist:
                pire_dist, pire_k = d, k
        if pire_dist > tolerance_m:
            garder[pire_k] = 1
            pile.append((i, pire_k))
            pile.append((pire_k, j))
        else:
            ecart_max_m = max(ecart_max_m, pire_dist)
    return [idx for idx in range(n) if garder[idx]], ecart_max_m


def _distance_segment_m(p: PointTrace, a: PointTrace, b: PointTrace) -> float:
    """Distance du point `p` au segment de grand cercle `[a, b]`, en mètres.

    Distance au travers (« cross-track ») puis le long (« along-track ») —
    formule sphérique classique de navigation, ramenée aux primitives déjà
    présentes dans `boucle.trace` (`distance_m`, `cap_deg`) plutôt que
    projetée sur un plan local : exacte sur la sphère, pas seulement à
    l'échelle d'une boucle. Si la projection perpendiculaire tombe hors du
    segment, la distance au bout le plus proche est rendue à la place — c'est
    la distance à la *ligne* qu'on mesure, pas à sa droite infinie.
    """
    d_ap = distance_m(a, p)
    if d_ap == 0:
        return 0.0
    d_ab = distance_m(a, b)
    if d_ab == 0:
        return d_ap
    brg_ap = math.radians(cap_deg(a, p))
    brg_ab = math.radians(cap_deg(a, b))
    sin_dxt = math.sin(d_ap / RAYON_TERRE_M) * math.sin(brg_ap - brg_ab)
    dxt = math.asin(max(-1.0, min(1.0, sin_dxt))) * RAYON_TERRE_M
    cos_dat = math.cos(d_ap / RAYON_TERRE_M) / math.cos(dxt / RAYON_TERRE_M)
    dat = math.acos(max(-1.0, min(1.0, cos_dat))) * RAYON_TERRE_M
    # `acos` rend toujours une valeur positive : la distance « le long » perd
    # son signe, et sans ce signe un point situé *en arrière* de `a` est mesuré
    # contre la droite infinie au lieu du segment. Mesuré avant correction : un
    # point à 280 m derrière `a`, aligné, était rendu à 0,01 m — Douglas-Peucker
    # le supprimait en certifiant un écart d'un centimètre. Ce qui disparaissait
    # ainsi, ce sont les antennes et les demi-tours, c'est-à-dire exactement la
    # forme que le reste du projet s'attache à modéliser.
    #
    # Le signe se lit sur l'angle entre le cap `a→p` et le cap `a→b` : au-delà
    # de 90°, la projection tombe derrière `a`.
    if math.cos(brg_ap - brg_ab) < 0:
        return d_ap
    if dat <= 0:
        return d_ap
    if dat >= d_ab:
        return distance_m(b, p)
    return abs(dxt)

"""Tests du greffage de tags OSM sur un GPX importé (`boucle.tags_importes`).

Tracés synthétiques uniquement, autour de (0, 0) en mer — même convention que
`tests/test_boucle_geometrie.py` et `tests/test_trace.py`. Aucun appel réseau :
tout part de `Trace` construits à la main.
"""

from __future__ import annotations

import math
import random

import pytest

from ourouler.boucle.couts import evaluer
from ourouler.boucle.geometrie import _distance_segment_m
from ourouler.boucle.tags_importes import (
    SEUIL_RAPPROCHEMENT_M,
    Greffage,
    _plus_proche,
    greffer,
)
from ourouler.noyau.trace import PointTrace, Segment, Trace

#: ~111 m par 0,001° de latitude — sert à fabriquer des décalages en mètres
#: sans dépendre du module testé.
METRES_PAR_DEGRE = 111_320.0


def _point(lat: float, lon: float, dist_m: float = 0.0) -> PointTrace:
    return PointTrace(lat=lat, lon=lon, alt_m=None, dist_m=dist_m)


def _trace(
    points: list[PointTrace], *, segments: list[Segment] | None = None, meta: dict | None = None
) -> Trace:
    return Trace(
        nom="t",
        points=points,
        segments=segments or [],
        distance_m=points[-1].dist_m if points else 0.0,
        denivele_m=None,
        temps_moteur_s=None,
        meta=meta if meta is not None else {},
    )


def _ligne_reroutee(n: int, *, pas_deg: float = 0.0005) -> Trace:
    """Une droite est-ouest de `n` points, un seul tronçon continu du début à la fin."""
    points = [_point(0.0, i * pas_deg, i * pas_deg * METRES_PAR_DEGRE) for i in range(n)]
    segments = [Segment(0, n - 1, points[-1].dist_m, tags={"highway": "tertiary"})]
    return _trace(points, segments=segments)


# --- le rapprochement de base ---------------------------------------------------


def test_un_point_proche_herite_des_tags_du_troncon():
    reroutee = _trace(
        [_point(0.0, 0.0, 0.0), _point(0.0, 0.001, 111.3)],
        segments=[Segment(0, 1, 111.3, tags={"highway": "secondary"}, cout_km=2.5)],
    )
    gpx = _trace([_point(0.00001, 0.0), _point(0.00001, 0.001, 111.3)])

    greffage = greffer(gpx, reroutee)
    assert greffage.exploitable
    assert greffage.km_sans_tag == 0.0
    (segment,) = greffage.segments
    assert segment.tags == {"highway": "secondary"}
    assert segment.cout_km == 2.5
    assert segment.debut_idx == 0
    assert segment.fin_idx == 1


def test_un_point_trop_loin_n_herite_de_rien():
    """Au-delà du seuil, un point ne prend aucun tag — mieux vaut l'ignorance affichée."""
    reroutee = _trace(
        [_point(0.0, 0.0, 0.0), _point(0.0, 0.001, 111.3)],
        segments=[Segment(0, 1, 111.3, tags={"highway": "secondary"})],
    )
    loin_deg = (SEUIL_RAPPROCHEMENT_M + 50.0) / METRES_PAR_DEGRE
    gpx = _trace([_point(loin_deg, 0.0), _point(loin_deg, 0.001, 111.3)])

    greffage = greffer(gpx, reroutee)
    assert not greffage.exploitable
    assert greffage.segments == [] or all(not s.tags for s in greffage.segments)


def test_le_seuil_est_reglable_et_se_retrouve_dans_le_greffage():
    reroutee = _trace(
        [_point(0.0, 0.0, 0.0), _point(0.0, 0.001, 111.3)],
        segments=[Segment(0, 1, 111.3, tags={"highway": "residential"})],
    )
    moyen_deg = 40.0 / METRES_PAR_DEGRE  # entre 25 m (défaut) et un seuil élargi
    gpx = _trace([_point(moyen_deg, 0.0), _point(moyen_deg, 0.001, 111.3)])

    defaut = greffer(gpx, reroutee)
    assert not defaut.exploitable

    elargi = greffer(gpx, reroutee, seuil_m=50.0)
    assert elargi.exploitable
    assert elargi.seuil_m == 50.0


# --- le regroupement ------------------------------------------------------------


def test_les_points_de_memes_tags_se_regroupent_en_un_seul_segment():
    reroutee = _ligne_reroutee(6)  # un seul tronçon "tertiary" continu
    gpx = _trace([_point(0.00001, i * 0.0005, i * 0.0005 * METRES_PAR_DEGRE) for i in range(6)])

    greffage = greffer(gpx, reroutee)
    assert greffage.exploitable
    assert len(greffage.segments) == 1
    segment = greffage.segments[0]
    assert segment.debut_idx == 0
    assert segment.fin_idx == 5
    assert segment.tags == {"highway": "tertiary"}


def test_deux_troncons_voisins_de_meme_highway_restent_deux_segments():
    """Le regroupement suit le tronçon d'origine, pas seulement l'égalité des tags.

    Sans cette distinction, un feu posé à la jonction de deux `tertiary`
    bout à bout disparaîtrait : les deux tronçons fusionneraient en un seul
    groupe et le nœud de fin du premier — celui qui porte le feu — ne serait
    plus le `fin_idx` d'aucun segment de sortie.
    """
    points = [_point(0.0, i * 0.0005, i * 0.0005 * METRES_PAR_DEGRE) for i in range(11)]
    reroutee = _trace(
        points,
        segments=[
            Segment(
                0,
                5,
                5 * 0.0005 * METRES_PAR_DEGRE,
                tags={"highway": "tertiary"},
                node_tags={"highway": "traffic_signals"},
            ),
            Segment(5, 10, 5 * 0.0005 * METRES_PAR_DEGRE, tags={"highway": "tertiary"}),
        ],
    )
    gpx = _trace([_point(0.00001, i * 0.0005, i * 0.0005 * METRES_PAR_DEGRE) for i in range(11)])

    greffage = greffer(gpx, reroutee)
    assert len(greffage.segments) == 2
    premier, second = greffage.segments
    assert premier.fin_idx == 5
    assert premier.node_tags == {"highway": "traffic_signals"}
    assert second.node_tags == {}


def test_la_longueur_du_segment_de_sortie_est_haversine_pas_recopiee():
    """La longueur vient des points du GPX, pas de celle (différente) du tronçon d'origine."""
    reroutee = _trace(
        [_point(0.0, 0.0, 0.0), _point(0.0, 0.01, 1113.0)],
        segments=[Segment(0, 1, 999_999.0, tags={"highway": "tertiary"})],  # longueur absurde à dessein
    )
    gpx = _trace([_point(0.00001, 0.0), _point(0.00001, 0.005, 556.5), _point(0.00001, 0.01, 1113.0)])

    greffage = greffer(gpx, reroutee)
    (segment,) = greffage.segments
    assert segment.longueur_m == pytest.approx(1113.0, rel=0.01)


def test_un_point_isole_sans_tag_devient_un_segment_a_tags_vides():
    reroutee = _ligne_reroutee(6)
    points = [_point(0.00001, i * 0.0005, i * 0.0005 * METRES_PAR_DEGRE) for i in range(6)]
    loin_deg = (SEUIL_RAPPROCHEMENT_M + 100.0) / METRES_PAR_DEGRE
    points[3] = _point(loin_deg, points[3].lon, points[3].dist_m)
    gpx = _trace(points)

    greffage = greffer(gpx, reroutee)
    assert len(greffage.segments) == 3  # [0-2], [3] (sans tag), [4-5]
    assert greffage.segments[1].tags == {}
    assert greffage.segments[1].debut_idx == 3
    assert greffage.segments[1].fin_idx == 3
    assert greffage.km_sans_tag > 0.0


# --- le chemin dégradé -----------------------------------------------------------


def test_un_troncon_rerouté_sans_segments_n_est_pas_exploitable():
    reroutee = _trace([_point(0.0, 0.0), _point(0.0, 0.001, 111.3)], segments=[])
    gpx = _trace([_point(0.0, 0.0), _point(0.0, 0.001, 111.3)])
    greffage = greffer(gpx, reroutee)
    assert not greffage.exploitable
    assert greffage.segments == []


def test_un_gpx_trop_court_n_est_pas_exploitable():
    reroutee = _ligne_reroutee(4)
    gpx = _trace([_point(0.0, 0.0)])  # un seul point : rien à regrouper
    greffage = greffer(gpx, reroutee)
    assert not greffage.exploitable


def test_greffage_non_exploitable_a_un_segment_par_defaut_km_sans_tag_egal_a_la_distance():
    reroutee = _trace([_point(0.0, 0.0), _point(0.0, 0.001, 111.3)], segments=[])
    gpx = _trace([_point(0.0, 0.0, 0.0), _point(0.0, 0.002, 222.6)])
    greffage = greffer(gpx, reroutee)
    assert greffage.km_sans_tag == pytest.approx(0.2226, rel=0.05)


# --- intégration avec les coûts ---------------------------------------------------


def test_une_trace_greffee_sort_couts_evaluer_de_l_etat_partiel():
    reroutee = _trace(
        [_point(0.0, i * 0.001, i * 111.3) for i in range(4)],
        segments=[
            Segment(0, 1, 111.3, tags={"highway": "secondary"}),
            Segment(1, 3, 222.6, tags={"highway": "tertiary"}),
        ],
    )
    gpx_points = [_point(0.00001, i * 0.001, i * 111.3) for i in range(4)]
    gpx = _trace(gpx_points, meta={"couts_partiels": True})

    greffage = greffer(gpx, reroutee)
    assert greffage.exploitable
    # C'est l'appelant (boucle.commande) qui pose les segments et lève le
    # drapeau — `evaluer` ne le fait pas lui-même, il ne fait que le lire.
    gpx.segments = greffage.segments
    gpx.meta["couts_partiels"] = False
    couts = evaluer(gpx)
    assert couts.km_trafic > 0.0
    assert couts.km_calme > 0.0
    assert gpx.meta["couts_partiels"] is False


# --- la recherche du plus proche, comparée à une version naïve ------------------


def test_le_plus_proche_avec_grille_donne_le_meme_resultat_que_le_calcul_naif():
    """La grille est une optimisation de recherche : elle ne doit rien changer au résultat."""
    random.seed(20260918)
    points_reroutee = [_point(0.0, i * 0.0007, i * 0.0007 * METRES_PAR_DEGRE) for i in range(40)]
    segments = [
        Segment(
            i,
            i + 1,
            points_reroutee[i + 1].dist_m - points_reroutee[i].dist_m,
            tags={"highway": f"h{i % 5}"},
        )
        for i in range(39)
    ]
    reroutee = _trace(points_reroutee, segments=segments)

    from ourouler.boucle.tags_importes import _arcs, _grille

    arcs = _arcs(reroutee)
    grille, lat0 = _grille(arcs)

    for _ in range(30):
        lat = random.uniform(-0.0003, 0.0003)
        lon = random.uniform(-0.001, 0.028)
        p = _point(lat, lon)
        via_grille = _plus_proche(p, arcs, grille, lat0, seuil_m=40.0)

        meilleure = math.inf
        meilleur_idx = None
        for idx, a, b in arcs:
            d = _distance_segment_m(p, a, b)
            if d < meilleure:
                meilleure, meilleur_idx = d, idx
        attendu = meilleur_idx if meilleure <= 40.0 else None
        assert via_grille == attendu


def test_greffage_est_un_dataclass_simple():
    """Vérifie juste la forme publique, pour que les appelants (boucle.commande) s'y fient."""
    g = Greffage(segments=[], km_sans_tag=0.0, seuil_m=25.0)
    assert g.exploitable is False

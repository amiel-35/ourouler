"""La densité de marqueurs au kilomètre : feux, stops, passages, ralentisseurs.

Toutes les traces sont **fabriquées** autour de (0.0, 0.0), en pleine mer dans
le golfe de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1
et 3).
"""

from __future__ import annotations

import math

from ourouler.boucle.marqueurs import (
    CLE_RALENTISSEUR,
    NOEUDS_CARREFOUR,
    RALENTISSEURS_SANS_EFFET,
    compter,
    nature_du_noeud,
)
from ourouler.boucle.trace import PointTrace, Segment, Trace

DEGRE_M = math.radians(1.0) * 6_371_000.0
PAS_M = 100.0


def droite(longueur_m: float) -> list[PointTrace]:
    nombre = int(round(longueur_m / PAS_M)) + 1
    return [
        PointTrace(lat=0.0, lon=(i * PAS_M) / DEGRE_M, alt_m=100.0, dist_m=i * PAS_M)
        for i in range(nombre)
    ]


def trace(points, segments, distance_m=None) -> Trace:
    return Trace(
        nom="essai",
        points=points,
        segments=segments,
        distance_m=points[-1].dist_m if distance_m is None else distance_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


def segments_avec(noeuds: dict[int, dict[str, str]], nombre: int) -> list[Segment]:
    """Un tronçon par intervalle ; `noeuds` donne les `node_tags` par indice de fin."""
    return [
        Segment(
            debut_idx=i,
            fin_idx=i + 1,
            longueur_m=PAS_M,
            tags={"highway": "tertiary"},
            node_tags=noeuds.get(i + 1, {}),
        )
        for i in range(nombre)
    ]


# --- la nature d'un nœud ------------------------------------------------------


def test_chaque_nature_de_carrefour_est_reconnue():
    for nature in NOEUDS_CARREFOUR:
        assert nature_du_noeud({"highway": nature}) == nature


def test_un_ralentisseur_est_reconnu_sous_sa_propre_cle():
    assert nature_du_noeud({CLE_RALENTISSEUR: "bump"}) == CLE_RALENTISSEUR


def test_un_ralentisseur_sans_effet_sur_un_cycliste_ne_compte_pas():
    for valeur in RALENTISSEURS_SANS_EFFET:
        assert nature_du_noeud({CLE_RALENTISSEUR: valeur}) is None


def test_un_feu_pose_sur_un_plateau_ne_compte_qu_une_fois():
    """`highway` gagne : se compter deux fois serait pire que de se manquer."""
    assert (
        nature_du_noeud({"highway": "traffic_signals", CLE_RALENTISSEUR: "table"})
        == "traffic_signals"
    )


def test_un_noeud_sans_tag_ne_porte_aucun_marqueur():
    assert nature_du_noeud({}) is None
    assert nature_du_noeud({"highway": "turning_circle"}) is None


# --- le compte et la densité --------------------------------------------------


def test_la_densite_est_le_compte_divise_par_les_kilometres():
    points = droite(10_000.0)  # 10 km, 100 intervalles
    noeuds = {i: {"highway": "crossing"} for i in (10, 20, 30, 40, 50)}
    mesure = compter(trace(points, segments_avec(noeuds, len(points) - 1)))
    assert mesure.nombre == 5
    assert mesure.distance_km == 10.0
    assert mesure.par_km == 0.5


def test_le_compte_par_nature_distingue_les_marqueurs():
    points = droite(5_000.0)
    noeuds = {
        5: {"highway": "traffic_signals"},
        10: {"highway": "traffic_signals"},
        15: {"highway": "stop"},
        20: {CLE_RALENTISSEUR: "hump"},
    }
    mesure = compter(trace(points, segments_avec(noeuds, len(points) - 1)))
    assert mesure.par_nature == {"traffic_signals": 2, "stop": 1, CLE_RALENTISSEUR: 1}
    assert mesure.nombre == 4


def test_un_meme_noeud_vu_par_deux_troncons_ne_compte_qu_une_fois():
    """Deux segments qui finissent au même point décrivent **un** carrefour."""
    points = droite(1_000.0)
    segments = [
        Segment(0, 5, 500.0, {"highway": "tertiary"}, node_tags={"highway": "stop"}),
        Segment(3, 5, 200.0, {"highway": "tertiary"}, node_tags={"highway": "stop"}),
    ]
    assert compter(trace(points, segments)).nombre == 1


def test_sans_segments_la_densite_est_inconnue_et_non_nulle():
    """Règle absolue 5 : un GPX importé ne prouve pas qu'il n'y a pas de feu."""
    mesure = compter(trace(droite(5_000.0), []))
    assert mesure.connue is False
    assert mesure.par_km is None
    assert mesure.nombre == 0


def test_un_trace_sans_marqueur_mais_avec_segments_rend_bien_zero():
    """Là, en revanche, zéro est une mesure : les tags de nœud sont connus."""
    points = droite(5_000.0)
    mesure = compter(trace(points, segments_avec({}, len(points) - 1)))
    assert mesure.connue is True
    assert mesure.nombre == 0
    assert mesure.par_km == 0.0


def test_une_distance_absurde_retombe_sur_la_derniere_distance_cumulee():
    points = droite(4_000.0)
    segments = segments_avec({10: {"highway": "stop"}}, len(points) - 1)
    mesure = compter(trace(points, segments, distance_m=float("nan")))
    assert mesure.distance_km == 4.0
    assert mesure.par_km == 0.25


def test_une_trace_de_longueur_nulle_ne_divise_pas_par_zero():
    point = PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=0.0)
    mesure = compter(trace([point, point], [], distance_m=0.0))
    assert mesure.par_km is None

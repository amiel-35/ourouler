"""Le terrain sous un bloc : notes, motifs, route au-delà, demi-tour.

Toutes les traces sont **fabriquées** autour de (0.0, 0.0), en pleine mer dans
le golfe de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1
et 3).
"""

from __future__ import annotations

import math

import pytest

from ourouler.boucle.trace import PointTrace, Segment, Trace
from ourouler.seance.placement import PENTE_DEMI_TOUR_MAX
from ourouler.seance.terrain import (
    PENALITE_BLOC_TRONQUE,
    POIDS_CARREFOUR,
    POIDS_KM_BATI,
    demi_tour_faisable,
    evaluer_couloir,
    route_au_dela,
)

LAT_FICTIVE = 0.0
LON_FICTIVE = 0.0
#: Un degré de longitude à l'équateur, en mètres (sphère de rayon 6 371 km).
DEGRE_M = math.radians(1.0) * 6_371_000.0
PAS_M = 50.0


def ligne_droite(
    longueur_m: float, altitudes=None, pas_m: float = PAS_M
) -> list[PointTrace]:
    """Une ligne droite plein est depuis (0, 0), un point tous les `pas_m`.

    `altitudes` est une fonction distance → altitude ; sans elle, l'altitude
    est plate à 100 m.
    """
    altitudes = altitudes or (lambda _d: 100.0)
    nombre = int(round(longueur_m / pas_m)) + 1
    points = []
    for i in range(nombre):
        distance = i * pas_m
        points.append(
            PointTrace(
                lat=LAT_FICTIVE,
                lon=LON_FICTIVE + distance / DEGRE_M,
                alt_m=altitudes(distance),
                dist_m=distance,
            )
        )
    return points


def anneau(rayon_deg: float = 0.01, nombre: int = 120) -> list[PointTrace]:
    """Une boucle fermée : le dernier point est exactement le premier."""
    bruts = []
    for i in range(nombre):
        angle = 2 * math.pi * i / nombre
        bruts.append(
            (LAT_FICTIVE + rayon_deg * math.cos(angle), LON_FICTIVE + rayon_deg * math.sin(angle))
        )
    bruts.append(bruts[0])
    points, cumul = [], 0.0
    for i, (lat, lon) in enumerate(bruts):
        if i:
            precedent = points[-1]
            cumul += math.hypot(
                (lat - precedent.lat) * DEGRE_M, (lon - precedent.lon) * DEGRE_M
            )
        points.append(PointTrace(lat=lat, lon=lon, alt_m=100.0, dist_m=cumul))
    return points


def trace_de(points: list[PointTrace], segments: list[Segment] | None = None) -> Trace:
    return Trace(
        nom="fabriquée",
        points=points,
        segments=segments if segments is not None else [],
        distance_m=points[-1].dist_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


def un_segment(points: list[PointTrace], **tags: str) -> list[Segment]:
    """Un unique tronçon couvrant tout le tracé."""
    return [
        Segment(
            debut_idx=0,
            fin_idx=len(points) - 1,
            longueur_m=points[-1].dist_m,
            tags=dict(tags) or {"highway": "tertiary"},
        )
    ]


def decouper(points: list[PointTrace], coupes: list[int], tags: dict[str, str]) -> list[Segment]:
    """Des tronçons consécutifs finissant aux indices `coupes`, tous avec `tags`."""
    segments, debut = [], 0
    for fin in coupes:
        segments.append(
            Segment(
                debut_idx=debut,
                fin_idx=fin,
                longueur_m=points[fin].dist_m - points[debut].dist_m,
                tags=dict(tags),
            )
        )
        debut = fin
    return segments


# --- un couloir parfait -------------------------------------------------------


def test_couloir_plat_et_calme_note_zero():
    points = ligne_droite(3000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="80"))
    note = evaluer_couloir(trace, 500.0, 2000.0)
    assert note.note == pytest.approx(0.0)
    assert note.motifs == []
    assert note.carrefours == 0
    assert note.km_batis == pytest.approx(0.0)
    assert note.descente_m == pytest.approx(0.0)
    assert note.montee_m == pytest.approx(0.0)
    assert note.pente_moyenne == pytest.approx(0.0)


# --- deux feux ----------------------------------------------------------------


def test_deux_feux_dans_le_bloc():
    points = ligne_droite(3000.0)
    segments = decouper(points, [20, 30, 40, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"highway": "traffic_signals"}  # au km 1,0
    segments[1].node_tags = {"highway": "traffic_signals"}  # au km 1,5
    segments[2].node_tags = {"highway": "traffic_signals"}  # au km 2,0, hors du bloc
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 500.0, 1200.0)  # de 500 m à 1 700 m
    assert note.carrefours == 2
    assert note.note == pytest.approx(2 * POIDS_CARREFOUR)
    assert "deux feux" in note.motifs


def test_un_stop_se_dit_au_singulier():
    points = ligne_droite(2000.0)
    segments = decouper(points, [20, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"highway": "stop"}
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 0.0, 1500.0)
    assert note.carrefours == 1
    assert "un stop" in note.motifs


def test_un_noeud_sans_highway_connu_ne_compte_pas():
    points = ligne_droite(2000.0)
    segments = decouper(points, [20, len(points) - 1], {"highway": "tertiary"})
    segments[0].node_tags = {"barrier": "gate"}
    trace = trace_de(points, segments)

    assert evaluer_couloir(trace, 0.0, 1500.0).carrefours == 0


# --- une descente -------------------------------------------------------------


def test_descente_de_un_kilometre():
    # Plat jusqu'au km 1, puis −3 % sur 1 km, puis plat.
    def altitude(d: float) -> float:
        if d <= 1000.0:
            return 100.0
        if d >= 2000.0:
            return 70.0
        return 100.0 - 0.03 * (d - 1000.0)

    points = ligne_droite(3000.0, altitude)
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 3000.0)
    assert note.descente_m == pytest.approx(30.0, abs=1.0)
    # Une pente est une tangente, comme partout ailleurs dans le dépôt.
    assert note.pente_max == pytest.approx(-0.03, abs=0.002)
    assert note.montee_m == pytest.approx(0.0)
    assert any("descente de 1,0 km" in motif for motif in note.motifs)
    assert note.note > 1.5


def test_les_pentes_sont_des_tangentes_pas_des_pourcentages():
    """Convention du dépôt (`physique.modele`, `--pente-max`, `placement`).

    `placement.PENTE_DEMI_TOUR_MAX` compare directement `note.pente_moyenne`
    à 0,015 : une pente rendue en pourcentage y refuserait tout demi-tour dès
    le premier faux-plat.
    """
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.04 * d)  # +4 % d'un bout à l'autre
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.pente_moyenne == pytest.approx(0.04, abs=0.002)
    assert note.pente_max == pytest.approx(0.04, abs=0.002)
    # Le pourcentage ne survit que dans les motifs, qui se lisent.
    assert any("2,0 %" in motif for motif in note.motifs)


def test_la_pente_moyenne_se_divise_par_la_longueur_du_profil_pas_du_couloir():
    """D4 : sur un couloir partiellement dépourvu d'altitude, la pente était divisée par deux.

    `_releve_pentes` ne garde dans son profil que les points qui portent une
    altitude. Diviser le dénivelé par la longueur **du couloir** sous-estimait
    donc la pente d'autant que le couloir était mal renseigné — et c'est cette
    pente-là que `placement.PENTE_DEMI_TOUR_MAX` compare à 0,015 pour
    autoriser un demi-tour. Une côte à 4 % lue à 2 % passait le seuil des 1,5 %
    dès que les trois quarts du couloir manquaient d'altitude.

    Ici : 2 km de couloir, mais seuls les 500 premiers mètres portent une
    altitude, et ils montent de 20 m. La pente mesurée est celle de ces 500 m
    (+4 %), pas celle qu'on obtiendrait en étalant les 20 m sur 2 km (+1 %).
    """
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.04 * d if d <= 500.0 else None)
    trace = trace_de(points, un_segment(points, highway="tertiary"))

    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.pente_moyenne == pytest.approx(0.04, abs=0.002)
    assert note.pente_moyenne > PENTE_DEMI_TOUR_MAX, (
        "une côte à 4 % ne doit pas passer pour un faux-plat propice au demi-tour"
    )


def test_un_faux_plat_descendant_court_ne_compte_pas():
    # 200 m à −3 %, moins que `LONGUEUR_DESCENTE_M`.
    def altitude(d: float) -> float:
        return 100.0 - 0.03 * min(max(d - 500.0, 0.0), 200.0)

    points = ligne_droite(2000.0, altitude)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert evaluer_couloir(trace, 0.0, 2000.0).descente_m == pytest.approx(0.0)


def test_montee_douce_non_penalisee():
    points = ligne_droite(2000.0, lambda d: 100.0 + 0.015 * d)  # +1,5 %
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, 0.0, 2000.0)
    assert note.montee_m == pytest.approx(0.0)
    assert note.note == pytest.approx(0.0, abs=0.01)


# --- zone bâtie ---------------------------------------------------------------


def test_zone_batie_comptee_au_kilometre():
    points = ligne_droite(3000.0)
    milieu = 20  # au km 1,0
    fin = 40  # au km 2,0
    segments = [
        Segment(0, milieu, points[milieu].dist_m, {"highway": "tertiary"}),
        Segment(
            milieu,
            fin,
            points[fin].dist_m - points[milieu].dist_m,
            {"highway": "residential"},
        ),
        Segment(fin, len(points) - 1, points[-1].dist_m - points[fin].dist_m, {"highway": "tertiary"}),
    ]
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 0.0, 3000.0)
    assert note.km_batis == pytest.approx(1.0, abs=0.06)
    assert any("zone bâtie" in motif for motif in note.motifs)
    assert note.note == pytest.approx(POIDS_KM_BATI, abs=0.15)


def test_un_village_qui_s_arrete_avant_le_bloc_ne_lui_est_pas_facture():
    """Décision du 13/09 : aucune évaluation sous une récupération.

    Le village occupe le premier kilomètre — là où tombe la récup — et le
    bloc commence exactement là où il finit. Le point de jonction appartient
    aux deux tronçons : lui demander ses tags faisait payer le village au bloc.
    """
    points = ligne_droite(3000.0)
    jonction = 20  # au km 1,0
    segments = [
        Segment(0, jonction, points[jonction].dist_m, {"highway": "residential"}),
        Segment(
            jonction,
            len(points) - 1,
            points[-1].dist_m - points[jonction].dist_m,
            {"highway": "tertiary"},
        ),
    ]
    trace = trace_de(points, segments)

    note = evaluer_couloir(trace, 1000.0, 2000.0)
    assert note.km_batis == pytest.approx(0.0)
    assert note.note == pytest.approx(0.0)


def test_maxspeed_50_vaut_zone_batie():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="50"))
    assert evaluer_couloir(trace, 0.0, 2000.0).km_batis == pytest.approx(2.0, abs=0.06)


def test_maxspeed_illisible_ne_bat_rien():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary", maxspeed="FR:rural"))
    assert evaluer_couloir(trace, 0.0, 2000.0).km_batis == pytest.approx(0.0)


def test_sans_segments_les_routes_sont_dites_inconnues():
    points = ligne_droite(2000.0)
    note = evaluer_couloir(trace_de(points), 0.0, 1000.0)
    assert note.km_batis == pytest.approx(0.0)
    assert "routes inconnues" in note.motifs


def test_sans_altitude_le_motif_le_dit():
    points = [
        PointTrace(lat=p.lat, lon=p.lon, alt_m=None, dist_m=p.dist_m)
        for p in ligne_droite(2000.0)
    ]
    note = evaluer_couloir(trace_de(points, un_segment(points, highway="tertiary")), 0.0, 1000.0)
    assert note.pente_moyenne == pytest.approx(0.0)
    assert "altitude inconnue" in note.motifs


# --- bloc plus long que le tracé ----------------------------------------------


def test_bloc_plus_long_que_le_trace():
    points = ligne_droite(1000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, 0.0, 5000.0)
    assert note.note >= PENALITE_BLOC_TRONQUE
    assert "bloc plus long que le tracé disponible" in note.motifs


def test_bloc_plus_long_que_la_boucle():
    points = anneau()
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert trace.bornee()
    note = evaluer_couloir(trace, 0.0, 10 * points[-1].dist_m)
    assert "bloc plus long que le tracé disponible" in note.motifs


def test_trace_de_deux_points_ne_leve_pas():
    points = ligne_droite(100.0, pas_m=100.0)
    note = evaluer_couloir(trace_de(points), 0.0, 50.0)
    assert note.note >= 0.0


def test_trace_vide_rend_une_note_sans_lever():
    trace = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )
    note = evaluer_couloir(trace, 0.0, 1000.0)
    assert note.note == pytest.approx(PENALITE_BLOC_TRONQUE)
    assert note.motifs == ["aucun tracé sous le bloc"]


def test_position_negative_est_ramenee_dans_le_trace():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    note = evaluer_couloir(trace, -500.0, 1000.0)
    assert note.note == pytest.approx(0.0)
    assert note.motifs == []


def test_bloc_a_cheval_sur_la_fermeture_dune_boucle():
    points = anneau()
    total = points[-1].dist_m
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    # Un bloc qui commence à 300 m de la fin et qui déborde sur le début.
    note = evaluer_couloir(trace, total - 300.0, 1000.0)
    assert "bloc plus long que le tracé disponible" not in note.motifs
    # Le même bloc, demandé au-delà d'un tour complet, tombe au même endroit.
    memo = evaluer_couloir(trace, total * 2 - 300.0, 1000.0)
    assert memo.note == pytest.approx(note.note)


# --- route au-delà ------------------------------------------------------------


def test_route_au_dela_sur_trace_ouvert():
    points = ligne_droite(2000.0)
    trace = trace_de(points)
    assert route_au_dela(trace, 1000.0, 800.0) is True
    assert route_au_dela(trace, 1500.0, 800.0) is False
    assert route_au_dela(trace, 1500.0, 0.0) is True


def test_route_au_dela_sur_boucle_fermee():
    points = anneau()
    total = points[-1].dist_m
    trace = trace_de(points)
    assert trace.bornee()
    # Où qu'on soit sur la boucle, on peut continuer : la route ne s'arrête pas.
    assert route_au_dela(trace, total - 10.0, 800.0) is True
    # Y compris pour un besoin plus long que le tour lui-même (contrat §2 :
    # « ou si le tracé est une boucle fermée ») : on repasse au même endroit,
    # mais on roule. En pratique le besoin vaut une demi-récup, jamais un tour.
    assert route_au_dela(trace, 0.0, total * 2) is True


def test_route_au_dela_sur_trace_sans_longueur():
    trace = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )
    assert route_au_dela(trace, 0.0, 300.0) is False


# --- demi-tour ----------------------------------------------------------------


def test_demi_tour_refuse_sur_une_secondary():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="secondary"))
    assert demi_tour_faisable(trace, 1000.0) is False


def test_demi_tour_accepte_sur_une_tertiary():
    points = ligne_droite(2000.0)
    trace = trace_de(points, un_segment(points, highway="tertiary"))
    assert demi_tour_faisable(trace, 1000.0) is True


def test_demi_tour_accepte_quand_on_ne_sait_pas():
    points = ligne_droite(2000.0)
    assert demi_tour_faisable(trace_de(points), 1000.0) is True


def test_demi_tour_lit_le_troncon_de_la_position():
    points = ligne_droite(2000.0)
    coupe = 20  # au km 1,0
    segments = [
        Segment(0, coupe, points[coupe].dist_m, {"highway": "secondary"}),
        Segment(
            coupe,
            len(points) - 1,
            points[-1].dist_m - points[coupe].dist_m,
            {"highway": "unclassified"},
        ),
    ]
    trace = trace_de(points, segments)
    assert demi_tour_faisable(trace, 500.0) is False
    assert demi_tour_faisable(trace, 1500.0) is True
    # Dix mètres après la jonction, on est déjà sur l'unclassified : le point
    # de jonction porte les tags des deux tronçons, c'est celui qu'on parcourt
    # qui décide.
    assert demi_tour_faisable(trace, 1010.0) is True

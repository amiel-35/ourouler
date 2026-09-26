"""Tests des antennes (L3.1) : détection et élagage.

Aucune coordonnée réelle, aucun réseau : les tracés sont fabriqués autour du
point fictif (0,0) à partir de déplacements en mètres. À l'équateur et sur
les quelques centaines de mètres utilisées ici, un degré vaut 111 320 m dans
les deux axes — l'approximation est largement en dessous des tolérances
testées.
"""

from __future__ import annotations

import math

import pytest

from ourouler.boucle.antennes import (
    FENETRE_DEFAUT_M,
    LONGUEUR_MIN_M,
    TOLERANCE_DEFAUT_M,
    Antenne,
    detecter,
    elaguer,
)
from ourouler.noyau.trace import PointTrace, Segment, Trace, distance_m

DEGRE_M = 111_320.0


def point(est_m: float, nord_m: float) -> PointTrace:
    """Un point du tracé, repéré en mètres à l'est et au nord de (0, 0)."""
    return PointTrace(lat=nord_m / DEGRE_M, lon=est_m / DEGRE_M, alt_m=None, dist_m=0.0)


def polyligne(sommets: list[tuple[float, float]], pas_m: float = 5.0) -> list[PointTrace]:
    """Les sommets reliés par des points espacés d'environ `pas_m`."""
    points = [point(*sommets[0])]
    for (x1, y1), (x2, y2) in zip(sommets, sommets[1:], strict=False):
        longueur = math.hypot(x2 - x1, y2 - y1)
        n = max(1, round(longueur / pas_m))
        for i in range(1, n + 1):
            points.append(point(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n))
    return points


def tracer(points: list[PointTrace], segments: list[Segment] | None = None) -> Trace:
    """Un `Trace` complet, avec ses distances cumulées et son `distance_m`."""
    cumul = 0.0
    avec_distance = [points[0]]
    for precedent, suivant in zip(points, points[1:], strict=False):
        cumul += distance_m(precedent, suivant)
        avec_distance.append(PointTrace(lat=suivant.lat, lon=suivant.lon, alt_m=suivant.alt_m, dist_m=cumul))
    return Trace(
        nom="fabriquee",
        points=avec_distance,
        segments=segments or [],
        distance_m=cumul,
        denivele_m=120.0,
        temps_moteur_s=None,
        meta={"denivele_source": "moteur"},
    )


def indice_le_plus_proche(trace: Trace, est_m: float, nord_m: float) -> int:
    """L'indice du point du tracé le plus proche d'une position donnée en mètres."""
    cible = point(est_m, nord_m)
    return min(range(len(trace.points)), key=lambda i: distance_m(trace.points[i], cible))


# --- tracés de référence ------------------------------------------------------


def trace_avec_antenne(longueur_antenne_m: float = 150.0) -> Trace:
    """Une route est-ouest de 1 000 m, avec un cul-de-sac vers le nord au 400ᵉ mètre."""
    return tracer(
        polyligne(
            [
                (0.0, 0.0),
                (400.0, 0.0),
                (400.0, longueur_antenne_m),
                (400.0, 0.0),
                (1000.0, 0.0),
            ]
        )
    )


def trace_sans_antenne() -> Trace:
    """Un carré de 400 m de côté, fermé, sans aucun demi-tour."""
    return tracer(polyligne([(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0), (0.0, 0.0)]))


# --- détection : le cas nominal ----------------------------------------------


def test_une_antenne_de_300_m_aller_retour_est_detectee():
    trace = trace_avec_antenne()
    antennes = detecter(trace)

    assert len(antennes) == 1
    antenne = antennes[0]
    assert antenne.longueur_m == pytest.approx(300, abs=25)
    # La jonction est au pied du cul-de-sac, au 400ᵉ mètre, dans les deux sens.
    assert antenne.debut_idx == pytest.approx(indice_le_plus_proche(trace, 400, 0), abs=3)
    assert distance_m(trace.points[antenne.debut_idx], point(400, 0)) < 20
    assert distance_m(trace.points[antenne.fin_idx], point(400, 0)) < 20
    assert antenne.fin_idx > antenne.debut_idx


def test_l_antenne_couvre_bien_le_sommet_du_cul_de_sac():
    trace = trace_avec_antenne()
    antenne = detecter(trace)[0]
    sommet = indice_le_plus_proche(trace, 400, 150)
    assert antenne.debut_idx < sommet < antenne.fin_idx


# --- détection : pas de fausse détection -------------------------------------


def test_un_carre_ferme_n_a_aucune_antenne():
    assert detecter(trace_sans_antenne()) == []


def test_la_fenetre_par_defaut_est_celle_decidee_le_13_09():
    """6 000 m, et non les 600 m du contrat d'origine.

    Deux mesures successives, toutes deux sur des boucles réelles. D'abord
    3 000 m : les culs-de-sac relevés sur les boucles de 60 km font 1,5 à
    2,7 km, une fenêtre de 600 m les laissait tous passer. Puis 6 000 m,
    le 13/09 au soir : le mainteneur a vu sur la carte d'une sortie un
    crochet que 3 000 m laissait encore passer — mesuré sur le GPX, une
    antenne de 3 453 m. Élargir ne coûte rien en fausse détection, puisque
    la détection exige que le retour repasse à moins de 20 m de l'aller :
    une vraie boucle ne repasse pas sur elle-même. Voir `FENETRE_DEFAUT_M`.
    """
    assert FENETRE_DEFAUT_M == 6000.0
    assert TOLERANCE_DEFAUT_M == 20.0
    crochet = trace_avec_antenne(longueur_antenne_m=1200.0)  # 2 400 m aller + retour
    assert len(detecter(crochet)) == 1
    assert detecter(crochet, fenetre_m=600) == []


def test_une_boucle_qui_repasse_par_son_depart_au_dela_de_la_fenetre_n_est_pas_une_antenne():
    """Un aller-retour assumé de 8 km dépasse la fenêtre : il n'est pas rogné.

    Le piège est de rendre l'antenne « tronquée à la fenêtre » : couper ses
    6 000 premiers mètres supprimerait une vraie route. La fenêtre est le
    seul curseur : assez large, la même géométrie redevient une antenne.
    """
    trace = tracer(polyligne([(0.0, 0.0), (4000.0, 0.0), (0.0, 0.0), (0.0, 600.0)], pas_m=20.0))
    assert detecter(trace) == []
    assert len(detecter(trace, fenetre_m=9000)) == 1


def test_un_aller_retour_plus_long_que_la_fenetre_reste_ignore_quelle_qu_elle_soit():
    trace = trace_avec_antenne(longueur_antenne_m=500.0)  # 1 000 m aller + retour
    assert detecter(trace, fenetre_m=600) == []
    # Avec une fenêtre assez large, la même géométrie redevient une antenne.
    assert len(detecter(trace, fenetre_m=1200)) == 1


def test_un_micro_aller_retour_sous_le_seuil_n_est_pas_une_antenne():
    trace = trace_avec_antenne(longueur_antenne_m=LONGUEUR_MIN_M / 4)
    assert detecter(trace) == []


def test_une_ligne_droite_et_un_trace_trop_court_ne_donnent_rien():
    assert detecter(tracer(polyligne([(0.0, 0.0), (1000.0, 0.0)]))) == []
    minuscule = tracer([point(0, 0), point(0, 1)])
    assert detecter(minuscule) == []


def test_des_reglages_absurdes_ne_detectent_rien():
    trace = trace_avec_antenne()
    assert detecter(trace, fenetre_m=0) == []
    assert detecter(trace, tolerance_m=0) == []


# --- détection : bruit, départ, multiplicité ---------------------------------


def trace_antenne_bruitee(amplitude_m: float = 10.0) -> Trace:
    """La même antenne, dont le **retour** s'écarte de l'aller jusqu'à `amplitude_m`."""
    aller = polyligne([(0.0, 0.0), (400.0, 0.0), (400.0, 150.0)])
    retour = polyligne([(400.0, 150.0), (400.0, 0.0), (1000.0, 0.0)])[1:]
    bruites = []
    for i, p in enumerate(retour):
        # Décalage latéral déterministe, en mètres, d'amplitude `amplitude_m`.
        ecart = amplitude_m * math.sin(i * 0.2)
        bruites.append(PointTrace(lat=p.lat, lon=p.lon + ecart / DEGRE_M, alt_m=None, dist_m=0.0))
    return tracer(aller + bruites)


def test_une_antenne_bruitee_de_10_m_est_toujours_detectee():
    antennes = detecter(trace_antenne_bruitee(10.0), tolerance_m=20)
    assert len(antennes) == 1
    assert antennes[0].longueur_m == pytest.approx(300, abs=40)


def test_une_antenne_bruitee_au_dela_de_la_tolerance_n_est_plus_reconnue():
    assert detecter(trace_antenne_bruitee(10.0), tolerance_m=5) == []


def test_une_antenne_au_depart_commence_a_l_indice_zero():
    trace = tracer(polyligne([(0.0, 0.0), (0.0, 150.0), (0.0, 0.0), (600.0, 0.0)]))
    antennes = detecter(trace)
    assert len(antennes) == 1
    assert antennes[0].debut_idx == 0
    assert antennes[0].longueur_m == pytest.approx(300, abs=25)


def test_deux_antennes_sont_detectees_separement():
    trace = tracer(
        polyligne(
            [
                (0.0, 0.0),
                (300.0, 0.0),
                (300.0, 120.0),
                (300.0, 0.0),
                (800.0, 0.0),
                (800.0, -160.0),
                (800.0, 0.0),
                (1200.0, 0.0),
            ]
        )
    )
    antennes = detecter(trace)
    assert len(antennes) == 2
    premiere, seconde = antennes
    assert premiere.fin_idx < seconde.debut_idx
    assert premiere.longueur_m == pytest.approx(240, abs=25)
    assert seconde.longueur_m == pytest.approx(320, abs=25)


def test_les_antennes_rendues_ne_se_chevauchent_jamais():
    trace = trace_avec_antenne()
    antennes = detecter(trace)
    for precedente, suivante in zip(antennes, antennes[1:], strict=False):
        assert precedente.fin_idx < suivante.debut_idx


# --- élagage ------------------------------------------------------------------


def test_elaguer_retire_l_aller_retour_et_raccorde():
    trace = trace_avec_antenne()
    avant = trace.distance_m
    elaguee = elaguer(trace, detecter(trace))

    assert elaguee.distance_m == pytest.approx(1000, abs=25)
    assert avant - elaguee.distance_m == pytest.approx(300, abs=25)
    assert elaguee.meta["antennes"]["nombre"] == 1
    assert elaguee.meta["antennes"]["metres_retires"] == pytest.approx(300, abs=25)
    assert elaguee.meta["distance_source"] == "recalculee"
    # Le D+ du moteur est gardé, et l'approximation est dite.
    assert elaguee.denivele_m == trace.denivele_m
    assert elaguee.meta["denivele_approximatif"] is True
    assert elaguee.meta["denivele_source"] == "moteur"


def test_elaguer_ne_touche_pas_le_trace_d_origine():
    trace = trace_avec_antenne()
    points_avant = len(trace.points)
    distance_avant = trace.distance_m
    elaguer(trace, detecter(trace))
    assert len(trace.points) == points_avant
    assert trace.distance_m == distance_avant
    assert "antennes" not in trace.meta


def test_le_trace_elague_ne_passe_plus_par_le_sommet_du_cul_de_sac():
    trace = trace_avec_antenne()
    elaguee = elaguer(trace, detecter(trace))
    sommet = point(400, 150)
    assert min(distance_m(p, sommet) for p in elaguee.points) > 100


def test_les_distances_cumulees_sont_recalculees_et_croissantes():
    trace = trace_avec_antenne()
    elaguee = elaguer(trace, detecter(trace))
    assert elaguee.points[0].dist_m == 0.0
    assert elaguee.points[-1].dist_m == pytest.approx(elaguee.distance_m)
    for precedent, suivant in zip(elaguee.points, elaguee.points[1:], strict=False):
        assert suivant.dist_m >= precedent.dist_m
        assert suivant.dist_m - precedent.dist_m == pytest.approx(distance_m(precedent, suivant), abs=1e-6)


def test_elaguer_preserve_la_fermeture_de_la_boucle():
    """Une boucle fermée avec une antenne le reste après élagage."""
    trace = tracer(
        polyligne(
            [
                (0.0, 0.0),
                (400.0, 0.0),
                (400.0, 150.0),
                (400.0, 0.0),
                (400.0, 400.0),
                (0.0, 400.0),
                (0.0, 0.0),
            ]
        )
    )
    assert trace.bornee()
    assert len(detecter(trace)) == 1
    elaguee = elaguer(trace, detecter(trace))
    assert elaguee.bornee()


def trace_segmentee() -> Trace:
    """Le tracé à antenne (points tous les 5 m), découpé en tronçons nommés.

    Les cinq tronçons couvrent les quatre cas d'élagage : intact avant
    l'antenne, à cheval sur son entrée, entièrement dedans, à cheval sur sa
    sortie, intact après. Les bornes sont écartées d'une dizaine de mètres
    des extrémités exactes du cul-de-sac : la détection travaille sur un
    sous-échantillonnage à 10 m, elle ne place pas la jonction au décimètre.
    """
    trace = trace_avec_antenne()  # 261 points : pied au 80ᵉ, sommet au 110ᵉ, retour au 140ᵉ
    dernier = len(trace.points) - 1

    def longueur(a: int, b: int) -> float:
        return trace.points[b].dist_m - trace.points[a].dist_m

    bornes = [
        (0, 60, "tertiary"),  # intact, avant l'antenne
        (60, 110, "unclassified"),  # à cheval sur l'entrée
        (110, 130, "service"),  # entièrement dans l'antenne
        (130, 150, "track"),  # à cheval sur la sortie
        (150, dernier, "secondary"),  # intact, après l'antenne
    ]
    trace.segments = [Segment(a, b, longueur(a, b), {"highway": classe}) for a, b, classe in bornes]
    return trace


def test_elaguer_supprime_les_segments_entierement_dans_l_antenne():
    trace = trace_segmentee()
    elaguee = elaguer(trace, detecter(trace))
    classes = [s.tags["highway"] for s in elaguee.segments]
    assert classes == ["tertiary", "unclassified", "track", "secondary"]


def test_les_segments_elagues_se_suivent_et_couvrent_le_trace():
    trace = trace_segmentee()
    elaguee = elaguer(trace, detecter(trace))
    dernier = len(elaguee.points) - 1
    precedent = 0
    for segment in elaguee.segments:
        assert 0 <= segment.debut_idx < segment.fin_idx <= dernier
        assert segment.debut_idx == precedent
        precedent = segment.fin_idx
    assert precedent == dernier


def test_les_segments_a_cheval_sont_tronques_et_les_intacts_gardes_tels_quels():
    trace = trace_segmentee()
    origine = {s.tags["highway"]: s for s in trace.segments}
    elaguee = elaguer(trace, detecter(trace))
    par_classe = {s.tags["highway"]: s for s in elaguee.segments}

    # Le tronçon « unclassified » montait jusqu'au sommet du cul-de-sac : il
    # s'arrête maintenant au pied.
    assert par_classe["unclassified"].longueur_m < origine["unclassified"].longueur_m / 2
    assert par_classe["track"].longueur_m < origine["track"].longueur_m
    # Les tronçons hors de l'antenne gardent la longueur donnée par le moteur.
    for classe in ("tertiary", "secondary"):
        assert par_classe[classe].longueur_m == pytest.approx(origine[classe].longueur_m)
    # La somme des longueurs couvre le tracé élagué, sans double compte.
    somme = sum(s.longueur_m for s in elaguee.segments)
    assert somme == pytest.approx(elaguee.distance_m, abs=5)


def test_l_elagage_garde_le_cout_par_km_du_moteur():
    """Le `CostPerKm` suit le tronçon : sans lui, la colonne « coût profil » disparaît.

    Il ne dépend pas de la longueur du tronçon — c'est un coût *par*
    kilomètre. Le laisser tomber à la réindexation rendait `cout_km_moyen`
    absent sur **toute** candidate générée (donc élaguée), et la colonne du
    lot L3.2 ne s'affichait que sur un GPX importé.
    """
    trace = trace_segmentee()
    for i, segment in enumerate(trace.segments):
        trace.segments[i] = Segment(
            segment.debut_idx, segment.fin_idx, segment.longueur_m, segment.tags, cout_km=1200.0
        )
    elaguee = elaguer(trace, detecter(trace))
    assert elaguee.segments
    assert all(s.cout_km == 1200.0 for s in elaguee.segments)


def test_chaque_segment_elague_couvre_la_distance_entre_ses_bornes():
    trace = trace_segmentee()
    elaguee = elaguer(trace, detecter(trace))
    for segment in elaguee.segments:
        couvert = elaguee.points[segment.fin_idx].dist_m - elaguee.points[segment.debut_idx].dist_m
        assert segment.longueur_m == pytest.approx(couvert, abs=5)


# --- élagage : les entrées qu'on ne maîtrise pas ------------------------------


def test_elaguer_sans_antenne_rend_un_trace_equivalent():
    trace = trace_sans_antenne()
    elaguee = elaguer(trace, [])
    assert len(elaguee.points) == len(trace.points)
    assert elaguee.distance_m == trace.distance_m
    assert elaguee.meta["antennes"] == {"nombre": 0, "metres_retires": 0.0}
    # Sans rien à retirer, la distance reste celle d'origine : pas de mention
    # « recalculee » pour un recalcul qui n'a pas eu lieu.
    assert "distance_source" not in elaguee.meta


def test_elaguer_ignore_les_antennes_hors_bornes_ou_vides():
    trace = trace_sans_antenne()
    hors_bornes = [
        Antenne(-5, 10, 300.0),
        Antenne(0, 10_000, 300.0),
        Antenne(4, 4, 0.0),
        Antenne(9, 3, 300.0),
    ]
    elaguee = elaguer(trace, hors_bornes)
    assert len(elaguee.points) == len(trace.points)
    assert elaguee.meta["antennes"]["nombre"] == 0


def test_elaguer_garde_la_plus_longue_de_deux_antennes_qui_se_chevauchent():
    trace = trace_avec_antenne()
    dernier = len(trace.points) - 1
    elaguee = elaguer(trace, [Antenne(10, 40, 150.0), Antenne(20, dernier, 900.0)])
    assert elaguee.meta["antennes"]["nombre"] == 1
    # C'est la longue qui a été retirée : le tracé s'arrête à l'indice 20.
    assert len(elaguee.points) == 21


def test_elaguer_refuse_de_reduire_le_trace_a_un_point():
    trace = trace_avec_antenne()
    elaguee = elaguer(trace, [Antenne(0, len(trace.points) - 1, 1000.0)])
    assert len(elaguee.points) == len(trace.points)
    assert elaguee.meta["antennes"]["nombre"] == 0


def test_une_antenne_juste_sous_la_fenetre_n_est_pas_perdue_par_son_voisinage():
    """L'écart à l'aller se teste avant la fenêtre.

    Une antenne de 300 m dans une fenêtre de 310 m : le point suivant du
    retour dépasse la fenêtre **et** a déjà quitté l'aller. C'est le second
    fait qui compte — sinon l'antenne serait abandonnée comme un aller-retour
    voulu alors qu'elle tient dans la fenêtre.
    """
    trace = trace_avec_antenne()
    antennes = detecter(trace, fenetre_m=310)
    assert len(antennes) == 1
    assert antennes[0].longueur_m == pytest.approx(300, abs=25)


def test_l_elagage_garde_les_tags_de_noeud():
    """Les feux suivent le tronçon : sans eux, une boucle urbaine se note comme la campagne.

    Même faute que `cout_km`, un champ et trois mois plus tard. `node_tags`
    est arrivé après coup et le constructeur de `_resegmenter` ne l'a jamais
    repris : **toute candidate générée passe par l'élagage**, donc toute
    candidate perdait ses feux, stops et passages piétons avant d'être notée.
    `evaluer_couloir` jugeait des couloirs urbains sans un carrefour.

    Mesuré le 16/09/2026 sur une boucle réelle au nord de Rennes, avant et
    après correction : le couloir du premier bloc notait **2,43 sans un seul
    carrefour**, contre **22,51 avec quatre feux** une fois les tags gardés.
    Le mainteneur l'avait vu à l'œil sur la carte — « le 1er bloc en zone 4 et
    en pleine ville, je suis persuadé qu'il y a des feux, jamais je prends
    ça » — avant qu'aucun des 3 206 tests ne s'en aperçoive.
    """
    trace = trace_segmentee()
    for i, segment in enumerate(trace.segments):
        trace.segments[i] = Segment(
            segment.debut_idx,
            segment.fin_idx,
            segment.longueur_m,
            segment.tags,
            node_tags={"highway": "traffic_signals"},
        )
    elaguee = elaguer(trace, detecter(trace))
    assert elaguee.segments
    gardes = [s for s in elaguee.segments if s.node_tags.get("highway") == "traffic_signals"]
    assert gardes, "aucun tronçon élagué n'a gardé ses tags de nœud : les feux sont perdus"

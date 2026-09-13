"""Tests des coûts d'un tracé (L2.4).

Tracés **fabriqués** autour du point zéro (au large du golfe de Guinée) :
aucune coordonnée réelle, aucun fichier, aucun réseau. Près de l'équateur
un degré de longitude vaut autant qu'un degré de latitude, ce qui rend la
fabrication d'un tracé à cap imposé exacte à mieux que 0,1 %.
"""

from __future__ import annotations

import math

import pytest

from ourouler.boucle.couts import (
    ANGLE_VIRAGE_DEG,
    ESPACEMENT_CAP_M,
    HIGHWAY_CALME,
    HIGHWAY_TRAFIC,
    PENALITE_MAUVAIS_SENS,
    POIDS_KM_NON_REVETU,
    POIDS_KM_TRAFIC,
    POIDS_VIRAGE_GAUCHE,
    POIDS_VIRAGE_GAUCHE_TRAFIC,
    SURFACES_NON_REVETUES,
    evaluer,
    tags_par_point,
    tags_par_troncon,
)
from ourouler.boucle.trace import PointTrace, Segment, Trace, distance_m

#: Mètres par degré de latitude (et de longitude à l'équateur).
METRES_PAR_DEGRE = 111_194.9

PAS_DEFAUT_M = 55.0


def avance(p: PointTrace, cap: float, distance: float) -> PointTrace:
    """Le point atteint depuis `p` en suivant `cap` sur `distance` mètres."""
    r = math.radians(cap)
    return PointTrace(
        lat=p.lat + distance * math.cos(r) / METRES_PAR_DEGRE,
        lon=p.lon + distance * math.sin(r) / METRES_PAR_DEGRE,
        alt_m=None,
        dist_m=p.dist_m + distance,
    )


def trace_de_caps(caps, pas_m: float = PAS_DEFAUT_M, segments=None) -> Trace:
    """Un tracé partant de (0, 0) dont le i-ème tronçon suit `caps[i]` sur `pas_m`."""
    points = [PointTrace(0.0, 0.0, None, 0.0)]
    for cap in caps:
        points.append(avance(points[-1], cap, pas_m))
    return Trace(
        nom="fabrique",
        points=points,
        segments=list(segments or []),
        distance_m=pas_m * len(caps),
        denivele_m=None,
        temps_moteur_s=None,
    )


def carre(horaire: bool, cote_m: float = 300.0) -> Trace:
    """Une boucle carrée fermée, dans le sens demandé."""
    caps = [0.0, 90.0, 180.0, 270.0] if horaire else [0.0, 270.0, 180.0, 90.0]
    points = [PointTrace(0.0, 0.0, None, 0.0)]
    for cap in caps:
        points.append(avance(points[-1], cap, cote_m))
    return Trace(
        nom="carre",
        points=points,
        segments=[],
        distance_m=4 * cote_m,
        denivele_m=None,
        temps_moteur_s=None,
    )


# --- les classes de routes sont bien des constantes nommées ------------------


def test_les_classes_de_routes_sont_disjointes_et_nommees():
    assert not HIGHWAY_TRAFIC & HIGHWAY_CALME
    assert "primary" in HIGHWAY_TRAFIC and "tertiary" in HIGHWAY_CALME
    assert "gravel" in SURFACES_NON_REVETUES


# --- virages -----------------------------------------------------------------


def test_trace_en_l_un_virage_a_droite_puis_un_a_gauche():
    """Nord, puis est (droite), puis nord (gauche)."""
    couts = evaluer(trace_de_caps([0, 0, 90, 90, 0, 0]))
    assert couts.virages_droite == 1
    assert couts.virages_gauche == 1
    assert couts.virages_gauche_trafic == 0


def test_le_changement_de_cap_passe_le_nord_sans_inventer_de_demi_tour():
    """Cap 350° → 10° : +20° à droite, pas −340° à gauche."""
    couts = evaluer(trace_de_caps([350, 350, 10, 10]))
    assert (couts.virages_gauche, couts.virages_droite) == (0, 0)


def test_un_demi_tour_exact_n_est_compte_ni_a_gauche_ni_a_droite():
    """Point 6 de la relecture : un aller-retour était compté comme un tourne-à-gauche.

    Mesuré : `_ecart_cap(0°, 180°)` rend −180, parce que
    `(vers − depuis + 180) % 360 − 180` couvre [−180, 180). Chaque demi-tour
    d'un tracé coûtait donc 0,3 de score (1,3 sur une route à trafic) pour un
    virage qu'il ne fait pas : on repart d'où l'on vient, le signe n'a aucun
    sens géométrique.
    """
    aller_retour = evaluer(trace_de_caps([0, 0, 180, 180]))
    assert (aller_retour.virages_gauche, aller_retour.virages_droite) == (0, 0)
    assert aller_retour.virages_gauche_trafic == 0

    # Et dans l'autre sens de parcours, même réponse : le signe n'entre pas en jeu.
    retour_aller = evaluer(trace_de_caps([180, 180, 0, 0]))
    assert (retour_aller.virages_gauche, retour_aller.virages_droite) == (0, 0)

    # Un virage franc mais qui n'est pas un demi-tour reste compté, lui.
    assert evaluer(trace_de_caps([0, 0, 170, 170])).virages_droite == 1
    assert evaluer(trace_de_caps([0, 0, 190, 190])).virages_gauche == 1


def test_un_demi_tour_ne_coute_rien_au_score():
    """Corollaire : le score d'un aller-retour ne porte pas de pénalité de virage."""
    couts = evaluer(trace_de_caps([0, 0, 180, 180]))
    assert couts.score == pytest.approx(PENALITE_MAUVAIS_SENS), (
        "seul le sens indéterminé doit peser, pas un tourne-à-gauche imaginaire"
    )


def test_un_virage_a_gauche_est_detecte_a_cheval_sur_le_nord():
    """Cap 10° → 300° : −70°, donc à gauche, malgré un écart brut de +290°."""
    couts = evaluer(trace_de_caps([10, 10, 300, 300]))
    assert (couts.virages_gauche, couts.virages_droite) == (1, 0)


def test_une_courbe_longue_n_est_pas_un_virage():
    """45° pris en 9 petits coups sur 500 m : c'est une courbe, pas un virage."""
    couts = evaluer(trace_de_caps([5 * i for i in range(10)], pas_m=55.0))
    assert (couts.virages_gauche, couts.virages_droite) == (0, 0)


def test_le_meme_angle_pris_court_est_un_virage():
    """60° en trois coups : virage si les coups font 20 m, courbe s'ils font 35 m.

    Même géométrie angulaire, seule la longueur sur laquelle l'angle est pris
    change — c'est exactement ce que `LONGUEUR_VIRAGE_M` doit trancher.
    """
    caps = [0, 20, 40, 60, 60]
    assert evaluer(trace_de_caps(caps, pas_m=20.0)).virages_droite == 1
    assert evaluer(trace_de_caps(caps, pas_m=35.0)).virages_droite == 0


def test_les_caps_sont_calcules_sur_des_points_espaces():
    """Des points à 3 m bruités ne créent pas de virage : ils sont sous 15 m."""
    points = [PointTrace(0.0, 0.0, None, 0.0)]
    for i in range(40):
        cap = 90.0 if i % 2 else 270.0  # zigzag pur bruit
        points.append(avance(points[-1], cap, 3.0))
    bruite = Trace(
        nom="bruit", points=points, segments=[], distance_m=120.0,
        denivele_m=None, temps_moteur_s=None,
    )
    ecarts = [distance_m(a, b) for a, b in zip(points[:-1], points[1:], strict=True)]
    assert max(ecarts) < ESPACEMENT_CAP_M, "ce zigzag doit rester sous le seuil d'espacement"
    couts = evaluer(bruite)
    assert (couts.virages_gauche, couts.virages_droite) == (0, 0)


def test_virage_a_gauche_a_trafic_si_le_troncon_sortant_est_a_trafic():
    """Le L ci-dessus, avec la branche de sortie du virage à gauche en primaire."""
    calme = {"highway": "tertiary"}
    passante = {"highway": "primary"}
    sans = trace_de_caps(
        [0, 0, 90, 90, 0, 0],
        segments=[Segment(0, 6, 330.0, calme)],
    )
    avec = trace_de_caps(
        [0, 0, 90, 90, 0, 0],
        segments=[Segment(0, 3, 165.0, calme), Segment(4, 6, 165.0, passante)],
    )
    assert evaluer(sans).virages_gauche_trafic == 0
    resultat = evaluer(avec)
    assert resultat.virages_gauche == 1
    assert resultat.virages_gauche_trafic == 1


# --- sens de la boucle -------------------------------------------------------


def test_boucle_carree_horaire_et_antihoraire():
    horaire = evaluer(carre(horaire=True))
    antihoraire = evaluer(carre(horaire=False))
    assert horaire.sens == "horaire"
    assert antihoraire.sens == "antihoraire"
    # Trois coins avant la fermeture, tous du même côté.
    assert (horaire.virages_droite, horaire.virages_gauche) == (3, 0)
    assert (antihoraire.virages_gauche, antihoraire.virages_droite) == (3, 0)


def test_le_sens_prefere_penalise_l_autre_sens():
    assert evaluer(carre(horaire=True), sens_prefere="horaire").score == 0.0
    penalise = evaluer(carre(horaire=True), sens_prefere="antihoraire")
    assert penalise.score == pytest.approx(PENALITE_MAUVAIS_SENS)


def test_le_sens_indetermine_est_penalise_comme_un_mauvais_sens():
    couts = evaluer(trace_de_caps([0, 0]))
    assert couts.sens == "indetermine"
    assert couts.score == pytest.approx(PENALITE_MAUVAIS_SENS)


# --- kilométrages ------------------------------------------------------------


def test_kilometrages_par_classe_de_route():
    segments = [
        Segment(0, 1, 2000.0, {"highway": "primary", "surface": "asphalt"}),
        Segment(1, 2, 3000.0, {"highway": "tertiary", "surface": "asphalt"}),
        Segment(2, 3, 1000.0, {"highway": "track"}),  # track sans surface = non revêtu
        Segment(3, 4, 500.0, {"highway": "residential", "surface": "gravel"}),
        Segment(4, 5, 700.0, {"surface": "asphalt"}),  # pas de highway : ni trafic ni calme
    ]
    couts = evaluer(trace_de_caps([0, 90, 0, 90, 0], segments=segments))
    assert couts.km_trafic == pytest.approx(2.0)
    assert couts.km_calme == pytest.approx(4.5)  # tertiary + track + residential
    assert couts.km_non_revetu == pytest.approx(1.5)  # track + gravel
    assert couts.km_non_classe == pytest.approx(0.7)  # le tronçon sans highway


def test_les_kilometres_non_classes_ne_s_evaporent_plus():
    """Point 15 de la relecture : `km_trafic + km_calme` peut valoir bien moins que tout.

    Un tracé à moitié sur des chemins sans `highway` connu s'affichait
    « 0,0 km de trafic » exactement comme un tracé parfaitement calme.
    """
    segments = [
        Segment(0, 1, 1000.0, {"highway": "tertiary"}),
        Segment(1, 2, 1000.0, {"highway": "path"}),  # classe inconnue
        Segment(2, 3, 1000.0, {}),  # aucun highway
    ]
    couts = evaluer(trace_de_caps([0, 90, 0], segments=segments))
    assert (couts.km_trafic, couts.km_calme) == (0.0, pytest.approx(1.0))
    assert couts.km_non_classe == pytest.approx(2.0)
    total = couts.km_trafic + couts.km_calme + couts.km_non_classe
    assert total == pytest.approx(3.0), "les trois classes doivent couvrir tous les tronçons"


def test_un_segment_sans_highway_n_est_compte_dans_aucune_classe():
    couts = evaluer(trace_de_caps([0, 90], segments=[Segment(0, 2, 1000.0, {})]))
    assert (couts.km_trafic, couts.km_calme, couts.km_non_revetu) == (0.0, 0.0, 0.0)
    assert couts.km_non_classe == pytest.approx(1.0), "mais il est compté quelque part"


def test_une_classe_de_highway_inconnue_n_est_pas_calme_par_defaut():
    segments = [Segment(0, 2, 1000.0, {"highway": "motorway", "surface": "asphalt"})]
    couts = evaluer(trace_de_caps([0, 90], segments=segments))
    assert (couts.km_trafic, couts.km_calme) == (0.0, 0.0)
    assert couts.km_non_classe == pytest.approx(1.0)


# --- cas dégénérés -----------------------------------------------------------


def test_trace_de_deux_points():
    deux = Trace(
        nom="deux",
        points=[PointTrace(0.0, 0.0, None, 0.0), PointTrace(0.01, 0.0, None, 1112.0)],
        segments=[],
        distance_m=1112.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    couts = evaluer(deux)
    assert (couts.virages_gauche, couts.virages_droite) == (0, 0)
    assert couts.sens == "indetermine"
    assert deux.meta["couts_partiels"] is True


def test_trace_sans_segments_donne_des_couts_partiels():
    sans = carre(horaire=True)
    couts = evaluer(sans)
    assert (couts.km_trafic, couts.km_calme, couts.km_non_revetu) == (0.0, 0.0, 0.0)
    assert sans.meta["couts_partiels"] is True


def test_avec_segments_aucun_marqueur_de_couts_partiels():
    avec = trace_de_caps([0, 90], segments=[Segment(0, 2, 1000.0, {"highway": "tertiary"})])
    evaluer(avec)
    assert "couts_partiels" not in avec.meta


@pytest.mark.parametrize("longueur", [-500.0, float("nan"), float("inf")])
def test_un_troncon_a_la_longueur_absurde_est_ecarte_et_compte(longueur):
    """Le retrancher donnerait un `km_trafic` négatif ou NaN, et un score faux."""
    trace = trace_de_caps(
        [0, 90],
        segments=[
            Segment(0, 1, longueur, {"highway": "primary"}),
            Segment(1, 2, 1000.0, {"highway": "primary"}),
        ],
    )
    couts = evaluer(trace)
    assert couts.km_trafic == pytest.approx(1.0), "seul le tronçon exploitable est compté"
    assert math.isfinite(couts.score) and couts.score >= 0
    assert trace.meta["segments_ignores"] == 1
    assert "couts_partiels" not in trace.meta, "il reste un tronçon mesuré"


def test_tous_les_troncons_ecartes_donnent_des_couts_partiels():
    trace = trace_de_caps([0, 90], segments=[Segment(0, 2, -1.0, {"highway": "primary"})])
    couts = evaluer(trace)
    assert (couts.km_trafic, couts.km_calme, couts.km_non_revetu) == (0.0, 0.0, 0.0)
    assert trace.meta["segments_ignores"] == 1
    assert trace.meta["couts_partiels"] is True


def test_trace_vide():
    vide = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0,
        denivele_m=None, temps_moteur_s=None,
    )
    couts = evaluer(vide)
    assert (couts.virages_gauche, couts.virages_droite) == (0, 0)
    assert couts.sens == "indetermine"


# --- score -------------------------------------------------------------------


def test_le_score_suit_la_formule_du_contrat():
    """Un tracé complet, recomposé à la main depuis les poids nommés."""
    calme = {"highway": "tertiary"}
    passante = {"highway": "primary"}
    trace = trace_de_caps(
        [0, 0, 90, 90, 0, 0],
        segments=[
            Segment(0, 3, 2000.0, calme),
            Segment(4, 6, 3000.0, passante),
        ],
    )
    couts = evaluer(trace, sens_prefere="horaire")
    attendu = (
        couts.km_trafic * POIDS_KM_TRAFIC
        + couts.km_non_revetu * POIDS_KM_NON_REVETU
        + couts.virages_gauche * POIDS_VIRAGE_GAUCHE
        + couts.virages_gauche_trafic * POIDS_VIRAGE_GAUCHE_TRAFIC
        + PENALITE_MAUVAIS_SENS  # tracé non bouclé : sens indéterminé
    )
    assert couts.score == pytest.approx(attendu)
    assert couts.score == pytest.approx(3.0 * 3.0 + 0.3 + 1.0 + 2.0)


def test_le_km_calme_ne_pese_pas_dans_le_score():
    segments = [Segment(0, 2, 10_000.0, {"highway": "residential", "surface": "asphalt"})]
    couts = evaluer(trace_de_caps([0, 90], segments=segments), sens_prefere="horaire")
    assert couts.km_calme == pytest.approx(10.0)
    assert couts.score == pytest.approx(PENALITE_MAUVAIS_SENS)


def test_le_seuil_de_virage_est_bien_celui_annonce():
    """Juste sous 45° : pas de virage ; juste au-dessus : un virage."""
    sous = ANGLE_VIRAGE_DEG - 1.0
    au_dessus = ANGLE_VIRAGE_DEG + 1.0
    assert evaluer(trace_de_caps([0, sous])).virages_droite == 0
    assert evaluer(trace_de_caps([0, au_dessus])).virages_droite == 1
    assert evaluer(trace_de_caps([0, -au_dessus])).virages_gauche == 1


# --- antennes (L3.1) ----------------------------------------------------------


def test_les_metres_d_antennes_viennent_de_la_mesure_d_avant_elagage():
    """Une candidate élaguée n'a plus d'antenne : la colonne lit ce qui a été retiré."""
    trace = trace_de_caps([0, 90])
    trace.meta["antennes"] = {"nombre": 2, "metres_retires": 740.0}
    couts = evaluer(trace)
    assert couts.antennes_m == pytest.approx(740.0)
    # Informatif : le score n'en tient pas compte (ces mètres ne sont plus là).
    assert couts.score == pytest.approx(PENALITE_MAUVAIS_SENS)


def test_un_trace_non_elague_est_mesure_a_la_volee():
    """Un GPX importé n'a pas de `meta["antennes"]` : on ne rend pas 0 sans regarder."""
    aller_retour = trace_de_caps([0] * 10 + [180] * 10, pas_m=20.0)
    assert "antennes" not in aller_retour.meta
    assert evaluer(aller_retour).antennes_m > 300


def test_une_mesure_d_antennes_illisible_est_refaite():
    trace = trace_de_caps([0, 90])
    for valeur in ({"nombre": 1}, {"metres_retires": None}, {"metres_retires": True}, "740"):
        trace.meta["antennes"] = valeur
        assert evaluer(trace).antennes_m == 0.0


def test_un_trace_sans_antenne_rend_zero_metre():
    assert evaluer(trace_de_caps([0, 90, 180, 270])).antennes_m == 0.0

# --- poids injectés (L3.2) ----------------------------------------------------
#
# Le score du sprint 2 était figé : trois kilomètres équivalents par kilomètre
# de « trafic », zéro pour tout le reste. Le sprint 3 le rend paramétrable par
# classe `highway`, les constantes restant le cas par défaut.


def _droite_taggee(tags: list[dict[str, str]], pas_m: float = 1000.0) -> Trace:
    """Une ligne droite d'un tronçon de 1 km par jeu de tags — aucun virage.

    Une droite n'a pas de sens de boucle : son score porte toujours
    `PENALITE_MAUVAIS_SENS`, qu'on retranche pour ne comparer que les routes.
    """
    segments = [Segment(i, i + 1, pas_m, t) for i, t in enumerate(tags)]
    return trace_de_caps([0.0] * len(tags), pas_m=pas_m, segments=segments)


def _score_routes(couts) -> float:
    """Le score sans la pénalité de sens : une droite n'est jamais une boucle."""
    return couts.score - PENALITE_MAUVAIS_SENS


def test_sans_poids_le_score_est_exactement_celui_du_sprint_2():
    trace = _droite_taggee([{"highway": "secondary"}, {"highway": "tertiary"}])
    assert _score_routes(evaluer(trace)) == pytest.approx(POIDS_KM_TRAFIC, rel=0.02)


def test_les_poids_injectes_remplacent_les_constantes():
    trace = _droite_taggee([{"highway": "secondary"}, {"highway": "tertiary"}])
    couts = evaluer(trace, poids={"secondary": 1.0, "tertiary": 0.0})
    assert _score_routes(couts) == pytest.approx(1.0, rel=0.02)


def test_une_classe_penalisee_par_les_poids_appris_pese_sur_le_score():
    trace = _droite_taggee([{"highway": "primary"}])
    leger = evaluer(trace, poids={"primary": 0.5})
    lourd = evaluer(trace, poids={"primary": 4.0})
    assert lourd.score > leger.score
    assert lourd.score - leger.score == pytest.approx(3.5, rel=0.02)


def test_une_classe_absente_des_poids_ne_coute_rien():
    """« Inconnu » n'est jamais un malus, y compris dans le barème."""
    trace = _droite_taggee([{"highway": "living_street"}])
    assert _score_routes(evaluer(trace, poids={"primary": 4.0})) == pytest.approx(0.0, abs=1e-9)


def test_un_bareme_vide_annule_le_cout_des_routes_mais_pas_le_reste():
    trace = _droite_taggee([{"highway": "primary", "surface": "gravel"}])
    couts = evaluer(trace, poids={})
    assert _score_routes(couts) == pytest.approx(POIDS_KM_NON_REVETU, rel=0.02)


def test_les_kilometres_par_classe_sont_rendus():
    trace = _droite_taggee(
        [{"highway": "tertiary"}, {"highway": "tertiary"}, {"highway": "secondary"}]
    )
    couts = evaluer(trace)
    assert couts.km_par_highway["tertiary"] == pytest.approx(2.0)
    assert couts.km_par_highway["secondary"] == pytest.approx(1.0)


def test_un_troncon_sans_highway_se_range_sous_la_classe_vide():
    couts = evaluer(_droite_taggee([{"surface": "asphalt"}]))
    assert couts.km_par_highway[""] == pytest.approx(1.0)
    assert _score_routes(couts) == pytest.approx(0.0, abs=1e-9)


# --- coût du profil BRouter ---------------------------------------------------


def test_le_cout_profil_est_la_moyenne_ponderee_par_la_longueur():
    segments = [
        Segment(0, 1, 1000.0, {"highway": "tertiary"}, cout_km=1000.0),
        Segment(1, 2, 3000.0, {"highway": "tertiary"}, cout_km=2000.0),
    ]
    couts = evaluer(trace_de_caps([0.0, 0.0], pas_m=1000.0, segments=segments))
    assert couts.cout_km_moyen == pytest.approx(1750.0)


def test_les_troncons_sans_cout_ne_tirent_pas_la_moyenne_vers_le_bas():
    segments = [
        Segment(0, 1, 1000.0, {"highway": "tertiary"}, cout_km=None),
        Segment(1, 2, 1000.0, {"highway": "tertiary"}, cout_km=3000.0),
    ]
    couts = evaluer(trace_de_caps([0.0, 0.0], pas_m=1000.0, segments=segments))
    assert couts.cout_km_moyen == pytest.approx(3000.0)


def test_sans_aucun_cout_la_moyenne_est_absente_pas_nulle():
    """Un GPX importé ne dit rien du coût : « — », jamais « 0 »."""
    assert evaluer(trace_de_caps([0.0, 90.0])).cout_km_moyen is None


# --- point et tronçon ---------------------------------------------------------


def test_un_point_de_jonction_appartient_aux_deux_segments_mais_un_troncon_a_un_seul():
    """La distinction que `seance.terrain` paie cher quand on l'oublie.

    Le point 2 ferme le premier segment et ouvre le second : `tags_par_point`
    lui donne les tags du premier. Le tronçon qui part du point 2, lui, est
    tout entier sur le second — et c'est une longueur, pas un point.
    """
    points = [
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=0.0),
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=100.0),
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=200.0),
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=300.0),
    ]
    segments = [
        Segment(0, 2, 200.0, {"highway": "residential"}),
        Segment(2, 3, 100.0, {"highway": "tertiary"}),
    ]

    par_point = tags_par_point(points, segments)
    par_troncon = tags_par_troncon(points, segments)

    assert [t["highway"] for t in par_point] == [
        "residential",
        "residential",
        "residential",
        "tertiary",
    ]
    assert len(par_troncon) == len(points) - 1
    assert [t["highway"] for t in par_troncon] == ["residential", "residential", "tertiary"]


def test_sans_segment_aucun_troncon_n_a_de_tags():
    points = [
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=0.0),
        PointTrace(lat=0.0, lon=0.0, alt_m=None, dist_m=100.0),
    ]
    assert tags_par_troncon(points, []) == [None]
    assert tags_par_troncon([], []) == []

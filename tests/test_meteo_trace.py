"""Tests de la météo le long du tracé (L2.5).

Aucun accès réseau : tout passe par `httpx.MockTransport`. Les tracés sont
fabriqués autour du point zéro et les réponses Open-Meteo sont inventées.
(Le vrai service est hors du domaine d'AROME au point zéro — sans
conséquence ici, où il n'est jamais appelé.)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from ourouler.boucle.horaire import Pause, construire_horaire
from ourouler.boucle.meteo_trace import SEUIL_PLUIE_MM_H, Echantillon, evaluer
from ourouler.meteo.openmeteo import VARIABLES_HORAIRES, ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurHorsDomaine, ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, Trace

DEBUT = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
METRES_PAR_DEGRE = 111_194.9

MODELE = "modele_test"
SECOND = "modele_second"

#: Valeurs horaires par défaut d'une série fabriquée : sec, vent d'est à 20 km/h.
DEFAUTS = {
    "precipitation": 0.0,
    "rain": 0.0,
    "wind_speed_10m": 20.0,
    "wind_direction_10m": 90.0,
    "wind_gusts_10m": 30.0,
    "apparent_temperature": 12.0,
    "temperature_2m": 14.0,
}


# --- tracés fabriqués --------------------------------------------------------


def avance(p: PointTrace, cap: float, distance: float) -> PointTrace:
    r = math.radians(cap)
    return PointTrace(
        lat=p.lat + distance * math.cos(r) / METRES_PAR_DEGRE,
        lon=p.lon + distance * math.sin(r) / METRES_PAR_DEGRE,
        alt_m=None,
        dist_m=p.dist_m + distance,
    )


def trace_droite(longueur_m: float = 20_000.0, cap: float = 90.0, pas_point_m: float = 1000.0):
    """Un tracé rectiligne partant de (0, 0) dans la direction `cap`."""
    points = [PointTrace(0.0, 0.0, None, 0.0)]
    while points[-1].dist_m < longueur_m - 1e-6:
        points.append(avance(points[-1], cap, pas_point_m))
    return Trace(
        nom="droite",
        points=points,
        segments=[],
        distance_m=longueur_m,
        denivele_m=None,
        temps_moteur_s=None,
    )


# --- Open-Meteo bouchonné ----------------------------------------------------


def horaire(n_heures: int, **series) -> dict:
    """Une série horaire fabriquée de `n_heures` heures à partir de 08:00 UTC."""
    bloc = {"time": [f"2026-09-13T{8 + i:02d}:00" for i in range(n_heures)]}
    for nom in VARIABLES_HORAIRES:
        bloc[nom] = list(series.get(nom, [DEFAUTS[nom]] * n_heures))
    return bloc


def client_bouchonne(par_modele, vues: list | None = None) -> ClientOpenMeteo:
    """Un client dont tout le trafic passe par un `MockTransport` : jamais le réseau.

    `par_modele(modele)` rend la série horaire à servir, ou un entier de code
    HTTP pour simuler un échec de ce modèle-là.
    """
    vues = vues if vues is not None else []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        modele = requete.url.params["models"]
        serie = par_modele(modele)
        if isinstance(serie, int):
            return httpx.Response(serie, json={"error": True, "reason": "modele indisponible"})
        lats = requete.url.params["latitude"].split(",")
        lons = requete.url.params["longitude"].split(",")
        blocs = [
            {"latitude": float(la), "longitude": float(lo), "hourly": serie}
            for la, lo in zip(lats, lons, strict=True)
        ]
        return httpx.Response(200, json=blocs)

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def client_simple(serie: dict, vues: list | None = None) -> ClientOpenMeteo:
    return client_bouchonne(lambda _modele: serie, vues)


def heures_de(resultat) -> list[str]:
    return [f"{e.t.astimezone(UTC):%H:%M}" for e in resultat.echantillons]


# --- échantillonnage et appel unique -----------------------------------------


def test_un_seul_appel_http_pour_tous_les_echantillons():
    vues: list[httpx.Request] = []
    client = client_simple(horaire(4), vues)
    resultat = evaluer(
        trace_droite(), client, horaire=construire_horaire(DEBUT, 20.0), modele=MODELE, pas_m=5000.0
    )
    assert len(vues) == 1
    assert [e.dist_m for e in resultat.echantillons] == [0.0, 5000.0, 10_000.0, 15_000.0, 20_000.0]
    assert vues[0].url.params["latitude"].count(",") == 4


def test_heures_de_passage():
    """20 km à 20 km/h : une heure, donc un échantillon tous les quarts d'heure."""
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert heures_de(resultat) == ["08:00", "08:15", "08:30", "08:45", "09:00"]


def test_heures_de_passage_sans_pause_egale_le_calcul_manuel_depart_plus_distance_sur_vitesse():
    """Non-régression : sans pause, `evaluer(horaire=...)` rend exactement le calcul d'avant ce lot."""
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    for e in resultat.echantillons:
        attendu = DEBUT + timedelta(hours=e.dist_m / 1000.0 / 20.0)
        assert e.t == attendu


def test_une_pause_decale_les_echantillons_qui_la_suivent():
    """« À 10 km je m'arrête 30 minutes » : les échantillons après 10 km arrivent 30 min plus tard."""
    pauses = [Pause(dist_m=10_000.0, duree_s=30 * 60.0)]
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0, pauses),
        modele=MODELE,
        pas_m=5000.0,
    )
    heures = {e.dist_m: e.t for e in resultat.echantillons}
    assert heures[0.0] == DEBUT
    assert heures[5000.0] == DEBUT + timedelta(minutes=15), "avant la pause : pas touché"
    assert heures[10_000.0] == DEBUT + timedelta(minutes=30), "au kilomètre de la pause : pas encore prise"
    assert heures[15_000.0] == DEBUT + timedelta(minutes=45 + 30), "après la pause : décalé de 30 min"
    assert heures[20_000.0] == DEBUT + timedelta(hours=1, minutes=30)


def test_le_dernier_point_est_toujours_echantillonne():
    """12 km au pas de 5 km : 0, 5, 10 **et** 12."""
    resultat = evaluer(
        trace_droite(12_000.0),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert [e.dist_m for e in resultat.echantillons] == [0.0, 5000.0, 10_000.0, 12_000.0]


def test_la_fenetre_demandee_va_du_depart_a_l_arrivee_plus_une_heure():
    """Départ à 08:30, arrivée à 09:30 : de 08:00 (heure pleine) à 10:00."""
    vues: list[httpx.Request] = []
    client = client_simple(horaire(4), vues)
    evaluer(
        trace_droite(),
        client,
        horaire=construire_horaire(DEBUT + timedelta(minutes=30), 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert vues[0].url.params["start_hour"] == "2026-09-13T08:00"
    assert vues[0].url.params["end_hour"] == "2026-09-13T10:00"


def test_un_depart_sans_fuseau_est_lu_comme_utc():
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT.replace(tzinfo=None), 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert heures_de(resultat) == ["08:00", "08:15", "08:30", "08:45", "09:00"]


# --- interpolation -----------------------------------------------------------


def test_interpolation_lineaire_entre_les_deux_heures_encadrantes():
    serie = horaire(2, precipitation=[0.0, 2.0], apparent_temperature=[10.0, 14.0])
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    pluies = [e.pluie_mm for e in resultat.echantillons]
    assert pluies == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0])
    assert [e.ressenti_c for e in resultat.echantillons] == pytest.approx([10, 11, 12, 13, 14])
    assert resultat.ressenti_min_c == pytest.approx(10.0)


def test_la_rafale_est_interpolee_lineairement():
    """La rafale est une vitesse, pas une direction : interpolation linéaire,
    comme `vent_kmh` — surtout pas angulaire, ce serait absurde pour une norme.
    """
    serie = horaire(2, wind_gusts_10m=[10.0, 30.0])
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    rafales = [e.rafales_kmh for e in resultat.echantillons]
    assert rafales == pytest.approx([10.0, 15.0, 20.0, 25.0, 30.0])


def test_une_rafale_absente_reste_absente_jamais_zero():
    serie = horaire(4, wind_gusts_10m=[None] * 4)
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert all(e.rafales_kmh is None for e in resultat.echantillons)


def test_l_heure_pile_prend_sa_valeur_meme_si_l_heure_precedente_manque():
    """Une valeur absente à 08 h ne doit pas effacer celle de 09 h."""
    serie = horaire(2, precipitation=[None, 1.0])
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    pluies = [e.pluie_mm for e in resultat.echantillons]
    assert pluies[:4] == [None, None, None, None]
    assert pluies[4] == pytest.approx(1.0)


def test_la_direction_du_vent_est_interpolee_angulairement():
    """350° puis 10° : à mi-chemin c'est le nord (0°), pas le sud (180°).

    Mesuré à travers le vent relatif d'un tracé plein nord : « face » si
    l'interpolation est angulaire, « dos » si elle est linéaire.
    """
    serie = horaire(2, wind_direction_10m=[350.0, 10.0])
    resultat = evaluer(
        trace_droite(cap=0.0),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert [e.vent_relatif for e in resultat.echantillons] == ["face"] * 5


# --- vent relatif au cap local ----------------------------------------------


@pytest.mark.parametrize(
    ("cap", "attendu"),
    [(90.0, "face"), (270.0, "dos"), (0.0, "travers"), (180.0, "travers")],
)
def test_vent_relatif_au_cap_local(cap: float, attendu: str):
    """Vent venant de l'est (90°) : de face si l'on va vers l'est."""
    resultat = evaluer(
        trace_droite(cap=cap),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert {e.vent_relatif for e in resultat.echantillons} == {attendu}
    assert [round(e.cap_deg) for e in resultat.echantillons] == [round(cap)] * 5


def test_parts_de_vent_face_et_dos():
    resultat = evaluer(
        trace_droite(cap=90.0),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert resultat.part_vent_face == pytest.approx(1.0)
    assert resultat.part_vent_dos == pytest.approx(0.0)
    assert resultat.n_vent_connu == len(resultat.echantillons), "ici, tout le vent est connu"


def test_un_vent_de_direction_inconnue_ne_compte_pour_aucune_part():
    serie = horaire(4, wind_direction_10m=[None] * 4)
    resultat = evaluer(
        trace_droite(cap=90.0),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert all(e.vent_relatif is None for e in resultat.echantillons)
    assert (resultat.part_vent_face, resultat.part_vent_dos) == (0.0, 0.0)
    assert resultat.n_vent_connu == 0, "et le dénominateur le dit, au lieu de laisser croire à 0 %"


def test_le_denominateur_des_parts_de_vent_est_expose():
    """Point 18 de la relecture : « 100 % » sur un seul échantillon sur cinq.

    Les parts se calculent sur les seuls échantillons au vent connu — c'est
    le bon choix, un échantillon sans donnée ne doit pas compter pour du
    travers — mais il faut pouvoir lire sur combien d'échantillons repose le
    pourcentage.
    """
    serie = horaire(4, wind_direction_10m=[90.0, None, None, None])
    resultat = evaluer(
        trace_droite(cap=90.0),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    connus = [e for e in resultat.echantillons if e.vent_relatif is not None]
    assert 0 < len(connus) < len(resultat.echantillons), "le test n'a de sens qu'en vent partiel"
    assert resultat.n_vent_connu == len(connus)
    assert resultat.part_vent_face == pytest.approx(1.0), (
        "le pourcentage reste calculé sur les seuls échantillons connus"
    )


# --- pluie cumulée et minutes sous la pluie ---------------------------------


def test_pluie_cumulee_et_minutes_de_pluie():
    """Pluie de 0 à 1 mm/h sur l'heure : 0,5 mm au total, et 52,5 min au-dessus du seuil.

    Les échantillons valent chacun du milieu de l'intervalle précédent au
    milieu du suivant : 7,5 + 15 + 15 + 15 + 7,5 = 60 minutes en tout.
    """
    serie = horaire(2, precipitation=[0.0, 1.0])
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    sous_la_pluie = [e for e in resultat.echantillons if (e.pluie_mm or 0) >= SEUIL_PLUIE_MM_H]
    assert len(sous_la_pluie) == 4
    assert resultat.pluie_cumulee_mm == pytest.approx(0.5)
    assert resultat.minutes_pluie == pytest.approx(52.5)


def test_un_trace_sec_ne_compte_aucune_minute_de_pluie():
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert resultat.pluie_cumulee_mm == 0.0
    assert resultat.minutes_pluie == 0.0


def test_une_pluie_absente_n_est_pas_comptee_comme_zero():
    serie = horaire(4, precipitation=[None] * 4)
    resultat = evaluer(
        trace_droite(),
        client_simple(serie),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert all(e.pluie_mm is None for e in resultat.echantillons)
    assert (resultat.pluie_cumulee_mm, resultat.minutes_pluie) == (0.0, 0.0)
    assert resultat.confiance == "inconnu"


# --- cas limites -------------------------------------------------------------


def test_trace_plus_longue_que_l_horizon_du_modele():
    """Le modèle ne rend que 2 heures : au-delà, tout est absent, pas extrapolé."""
    vues: list[httpx.Request] = []
    client = client_bouchonne(lambda _m: horaire(2, precipitation=[1.0, 1.0]), vues)
    resultat = evaluer(
        trace_droite(60_000.0),
        client,
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert len(vues) == 2  # un appel par modèle, pas un par échantillon
    assert heures_de(resultat)[0] == "08:00"
    assert heures_de(resultat)[-1] == "11:00"
    dans_l_horizon = [e for e in resultat.echantillons if e.t <= DEBUT + timedelta(hours=1)]
    au_dela = [e for e in resultat.echantillons if e.t > DEBUT + timedelta(hours=1)]
    assert au_dela, "ce test doit avoir des échantillons hors horizon"
    assert all(e.pluie_mm is not None for e in dans_l_horizon)
    assert all(_tout_absent(e) for e in au_dela)


def test_tout_le_trace_hors_horizon_donne_une_confiance_inconnue():
    client = client_bouchonne(lambda _m: horaire(2, precipitation=[1.0, 1.0]))
    tardif = DEBUT + timedelta(hours=5)
    resultat = evaluer(
        trace_droite(),
        client,
        horaire=construire_horaire(tardif, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert all(_tout_absent(e) for e in resultat.echantillons)
    assert resultat.confiance == "inconnu"


def _tout_absent(e: Echantillon) -> bool:
    return (e.pluie_mm, e.vent_kmh, e.vent_relatif, e.ressenti_c) == (None, None, None, None)


def test_echantillon_unique():
    """Un tracé réduit à un point : un échantillon, une durée nulle, pas de cap."""
    vues: list[httpx.Request] = []
    client = client_simple(horaire(2, precipitation=[5.0, 5.0]), vues)
    un_point = Trace(
        nom="point",
        points=[PointTrace(0.0, 0.0, None, 0.0)],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    resultat = evaluer(un_point, client, horaire=construire_horaire(DEBUT, 20.0), modele=MODELE)
    assert len(vues) == 1
    assert len(resultat.echantillons) == 1
    unique = resultat.echantillons[0]
    assert (unique.dist_m, unique.cap_deg) == (0.0, 0.0)
    assert unique.pluie_mm == pytest.approx(5.0)
    assert unique.vent_relatif is None, "sans cap local, pas de « à l'aller »"
    assert (resultat.pluie_cumulee_mm, resultat.minutes_pluie) == (0.0, 0.0)


def test_trace_sans_point():
    """Une entrée que l'utilisateur peut corriger : `ErreurUtilisateur`, pas `ValueError`.

    Convention de la CLI : seule une `ErreurUtilisateur` est affichée en une
    ligne avec le code 2 ; toute autre exception est un bug et sort en trace.
    """
    vide = Trace(nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None)
    with pytest.raises(ErreurUtilisateur, match="sans point"):
        evaluer(vide, client_simple(horaire(2)), horaire=construire_horaire(DEBUT, 20.0), modele=MODELE)


@pytest.mark.parametrize(
    ("vitesse", "pas"),
    [
        (0.0, 5000.0),
        (-5.0, 5000.0),
        (float("nan"), 5000.0),
        (20.0, 0.0),
        (20.0, -5000.0),
        (20.0, float("inf")),
    ],
)
def test_vitesse_ou_pas_non_positifs(vitesse: float, pas: float):
    """Le message nomme le paramètre fautif : c'est ce que l'utilisateur doit corriger."""
    with pytest.raises(ErreurUtilisateur, match=r"vitesse_kmh|pas_m"):
        evaluer(
            trace_droite(),
            client_simple(horaire(4)),
            horaire=construire_horaire(DEBUT, vitesse),
            modele=MODELE,
            pas_m=pas,
        )


def test_les_distances_sont_recalculees_si_le_trace_ne_les_porte_pas():
    """Un tracé importé qui laisse `dist_m` à zéro ne doit pas donner un seul échantillon."""
    droit = trace_droite()
    sans_distances = Trace(
        nom="sans",
        points=[PointTrace(p.lat, p.lon, p.alt_m, 0.0) for p in droit.points],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    resultat = evaluer(
        sans_distances,
        client_simple(horaire(4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert len(resultat.echantillons) == 5
    assert resultat.echantillons[-1].dist_m == pytest.approx(20_000.0, rel=1e-3)


# --- second avis -------------------------------------------------------------


def test_sans_second_avis_la_confiance_est_inconnue():
    vues: list[httpx.Request] = []
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4, precipitation=[1.0] * 4), vues),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert len(vues) == 1
    assert resultat.confiance == "inconnu"


def test_second_avis_en_accord():
    def par_modele(modele: str):
        return horaire(4, precipitation=[1.0] * 4 if modele == MODELE else [0.9] * 4)

    vues: list[httpx.Request] = []
    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele, vues),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert [r.url.params["models"] for r in vues] == [MODELE, SECOND]
    assert resultat.confiance == "accord"


def test_second_avis_en_desaccord():
    """Un modèle annonce 2 mm/h, l'autre rien : c'est un désaccord, jamais une moyenne."""

    def par_modele(modele: str):
        return horaire(4, precipitation=[2.0] * 4 if modele == MODELE else [0.0] * 4)

    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert resultat.confiance == "desaccord"
    assert [e.pluie_mm for e in resultat.echantillons] == pytest.approx([2.0] * 5)


def test_un_seul_echantillon_en_desaccord_suffit():
    def par_modele(modele: str):
        if modele == MODELE:
            return horaire(2, precipitation=[0.0, 2.0])
        return horaire(2, precipitation=[0.0, 0.0])

    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert resultat.confiance == "desaccord"


def test_un_second_avis_indisponible_ne_fait_pas_echouer_l_evaluation():
    """Second modèle hors service : confiance « inconnu », le reste est intact."""

    def par_modele(modele: str):
        return horaire(4, precipitation=[1.0] * 4) if modele == MODELE else 500

    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        pas_m=5000.0,
    )
    assert resultat.confiance == "inconnu"
    assert [e.pluie_mm for e in resultat.echantillons] == pytest.approx([1.0] * 5)
    assert resultat.minutes_pluie == pytest.approx(60.0)


# --- repli (Q19) --------------------------------------------------------------
#
# `ourouler sortie --jour <J+2 ou J+3>` perdait toute la météo : le modèle
# principal (AROME, portée 67 h) ne couvre pas une fenêtre à J+3, et rien ne
# basculait sur le second avis déjà configuré. Ces tests couvrent le repli
# ajouté dans `evaluer` : `modele_repli`, `MeteoTrace.modele_utilise/.repli`.


def horaire_vide(n_heures: int) -> dict:
    """Un bloc « hors de portée » : toutes les variables à `None` (Q19)."""
    return horaire(n_heures, **{nom: [None] * n_heures for nom in VARIABLES_HORAIRES})


def test_sans_defaut_le_modele_demande_est_nomme():
    """Même sans repli, `modele_utilise` est renseigné : la ligne d'affichage en dépend."""
    resultat = evaluer(
        trace_droite(),
        client_simple(horaire(4, precipitation=[1.0] * 4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=5000.0,
    )
    assert resultat.modele_utilise == MODELE
    assert resultat.repli is False


def test_le_repli_prend_le_relais_quand_le_principal_est_hors_de_portee():
    """Le cas de Q19 : le principal ne couvre pas la fenêtre, le repli si."""

    def par_modele(modele: str):
        return horaire_vide(4) if modele == MODELE else horaire(4, precipitation=[3.0] * 4)

    vues: list[httpx.Request] = []
    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele, vues),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        modele_repli=SECOND,
        pas_m=5000.0,
    )
    assert [r.url.params["models"] for r in vues] == [MODELE, SECOND]
    assert resultat.modele_utilise == SECOND
    assert resultat.repli is True
    assert [e.pluie_mm for e in resultat.echantillons] == pytest.approx([3.0] * 5)


def test_sans_modele_de_repli_l_echec_remonte_tel_quel():
    """Le comportement d'avant Q19 est inchangé quand personne ne fournit de repli."""
    with pytest.raises(ErreurHorsDomaine):
        evaluer(
            trace_droite(),
            client_simple(horaire_vide(4)),
            horaire=construire_horaire(DEBUT, 20.0),
            modele=MODELE,
            pas_m=5000.0,
        )


def test_le_repli_egal_au_principal_n_est_pas_retente():
    """Un `modele_repli` égal au principal ne changerait rien : on ne boucle pas dessus."""
    with pytest.raises(ErreurHorsDomaine):
        evaluer(
            trace_droite(),
            client_simple(horaire_vide(4)),
            horaire=construire_horaire(DEBUT, 20.0),
            modele=MODELE,
            modele_repli=MODELE,
            pas_m=5000.0,
        )


def test_le_repli_n_interroge_pas_deux_fois_le_meme_modele_pour_le_second_avis():
    """`second_avis` == le modèle de repli : pas de troisième appel qui comparerait un modèle à lui-même."""

    def par_modele(modele: str):
        return horaire_vide(4) if modele == MODELE else horaire(4, precipitation=[1.0] * 4)

    vues: list[httpx.Request] = []
    resultat = evaluer(
        trace_droite(),
        client_bouchonne(par_modele, vues),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        second_avis=SECOND,
        modele_repli=SECOND,
        pas_m=5000.0,
    )
    assert [r.url.params["models"] for r in vues] == [MODELE, SECOND], (
        "un troisième appel demanderait le second avis en plus du repli, pour rien"
    )
    assert resultat.confiance == "inconnu", "comparer un modèle à lui-même n'est pas un second avis"


# --- repli partiel : la moitié du tracé peut déborder l'horizon du principal --
#
# Un 600 km avec une nuit de sommeil déborde parfois l'horizon horaire du
# modèle principal en cours de route, sans que le **départ** en soit hors
# domaine : Open-Meteo rend alors une série valide qui s'arrête, pas un bloc
# entièrement nul (ce dernier cas est le repli *total*, ci-dessus). Avant ce
# lot, les échantillons au-delà restaient silencieusement absents, même avec
# un `modele_repli` configuré — ces tests couvrent le rattrapage.


def horaire_partiel(n_valides: int, n_total: int, valeur: float = 1.0) -> dict:
    """Une série valide sur les `n_valides` premières heures, puis **tout** absent au-delà.

    « Tout », pas seulement la pluie : c'est ce qui distingue une fenêtre qui
    dépasse la portée horaire du modèle (aucune variable ne répond plus,
    au-delà d'un moment) d'une simple valeur ponctuellement manquante.
    """
    return horaire(
        n_total,
        **{
            nom: [valeur if nom in ("precipitation", "rain") else DEFAUTS[nom]] * n_valides
            + [None] * (n_total - n_valides)
            for nom in VARIABLES_HORAIRES
        },
    )


def test_repli_partiel_bascule_seulement_les_echantillons_non_couverts():
    """Le principal répond pour le début du tracé, le repli prend le relais pour la fin."""

    def par_modele(modele: str):
        if modele == MODELE:
            # Valide à 08:00 et 09:00, puis une série qui s'arrête (10:00,
            # 11:00 à `None`, **toutes** les variables) — la signature
            # mesurée d'une fenêtre trop longue, pas d'un point hors domaine
            # (voir docstring du module).
            return horaire_partiel(2, 4, valeur=1.0)
        return horaire(4, precipitation=[9.0] * 4)

    vues: list[httpx.Request] = []
    resultat = evaluer(
        trace_droite(40_000.0),
        client_bouchonne(par_modele, vues),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        modele_repli=SECOND,
        pas_m=10_000.0,
    )
    assert [r.url.params["models"] for r in vues] == [MODELE, SECOND], (
        "le repli n'est tenté qu'une fois, mémoïsé, pas un appel par échantillon absent"
    )
    assert [e.modele for e in resultat.echantillons] == [MODELE, MODELE, MODELE, SECOND, SECOND]
    assert [e.pluie_mm for e in resultat.echantillons] == pytest.approx([1.0, 1.0, 1.0, 9.0, 9.0])
    assert resultat.bascule_dist_m == pytest.approx(30_000.0)
    assert resultat.repli is True
    assert resultat.modele_utilise == MODELE, "le principal reste nommé : il a répondu pour l'essentiel"


def test_sans_repli_partiel_configure_les_echantillons_non_couverts_restent_absents():
    """Sans `modele_repli`, le comportement d'avant ce lot est inchangé : rien n'est inventé."""
    resultat = evaluer(
        trace_droite(40_000.0),
        client_simple(horaire_partiel(2, 4)),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        pas_m=10_000.0,
    )
    assert [e.modele for e in resultat.echantillons] == [MODELE, MODELE, MODELE, None, None]
    assert resultat.bascule_dist_m is None
    assert resultat.repli is False


def test_un_repli_partiel_indisponible_laisse_les_echantillons_absents_sans_echouer():
    """Le repli tombe en panne : les échantillons qu'il aurait couverts restent absents."""

    def par_modele(modele: str):
        if modele == MODELE:
            return horaire_partiel(2, 4)
        return 503

    resultat = evaluer(
        trace_droite(40_000.0),
        client_bouchonne(par_modele),
        horaire=construire_horaire(DEBUT, 20.0),
        modele=MODELE,
        modele_repli=SECOND,
        pas_m=10_000.0,
    )
    assert [e.modele for e in resultat.echantillons] == [MODELE, MODELE, MODELE, None, None]
    assert resultat.bascule_dist_m is None
    assert resultat.repli is False

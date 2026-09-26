"""Tests du client Open-Meteo (L1.5).

Aucun accès réseau : `httpx.MockTransport` intercepte tout. Les réponses
sont **fabriquées** (coordonnées au point zéro, valeurs inventées).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from ourouler.meteo.openmeteo import VARIABLES_HORAIRES, ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurHorsDomaine

DEBUT = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
POINTS_3 = [(0.0, 0.0), (0.1, 0.0), (0.0, 0.1)]


def bloc(lat: float, lon: float, n: int = 3, **remplacements: Any) -> dict[str, Any]:
    """Un bloc de réponse fabriqué, n heures à partir de 08:00 UTC."""
    horaire: dict[str, Any] = {"time": [f"2026-09-13T{8 + i:02d}:00" for i in range(n)]}
    valeurs = {
        "precipitation": [0.0, 0.5, 1.2],
        "rain": [0.0, 0.5, 1.2],
        "wind_speed_10m": [14.0, 16.0, 18.0],
        "wind_direction_10m": [45.0, 50.0, 200.0],
        "wind_gusts_10m": [25.0, 28.0, 33.0],
        "apparent_temperature": [12.0, 12.5, 11.0],
        "temperature_2m": [14.0, 14.5, 13.0],
    }
    for nom in VARIABLES_HORAIRES:
        horaire[nom] = valeurs[nom][:n]
    horaire.update(remplacements)
    return {"latitude": lat, "longitude": lon, "timezone": "GMT", "hourly": horaire}


def client_avec(gestionnaire) -> ClientOpenMeteo:
    """Un client dont tout le trafic passe par un `MockTransport` : jamais le réseau."""
    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def client_repondant(charge: Any, code: int = 200) -> tuple[ClientOpenMeteo, list[httpx.Request]]:
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(code, json=charge)

    return client_avec(gestionnaire), vues


# --- un seul appel, bons paramètres -----------------------------------------


def test_un_seul_appel_http_pour_tous_les_points():
    charge = [bloc(lat, lon) for lat, lon in POINTS_3]
    client, vues = client_repondant(charge)
    previsions = client.previsions(POINTS_3, modele="modele_test", debut=DEBUT, horizon_h=3)
    assert len(vues) == 1
    assert len(previsions) == 3


def test_parametres_envoyes():
    client, vues = client_repondant([bloc(lat, lon) for lat, lon in POINTS_3])
    client.previsions(POINTS_3, modele="modele_test", debut=DEBUT, horizon_h=3)
    p = vues[0].url.params
    assert p["latitude"] == "0.0000,0.1000,0.0000"
    assert p["longitude"] == "0.0000,0.0000,0.1000"
    assert p["hourly"] == ",".join(VARIABLES_HORAIRES)
    assert p["models"] == "modele_test"
    assert p["timezone"] == "UTC"
    # ISO sans secondes, fenêtre inclusive de horizon_h heures.
    assert p["start_hour"] == "2026-09-13T08:00"
    assert p["end_hour"] == "2026-09-13T10:00"
    assert vues[0].url.path == "/v1/forecast"


def test_debut_naif_lu_comme_utc():
    client, vues = client_repondant(bloc(0.0, 0.0, n=1))
    client.previsions([(0.0, 0.0)], modele="m", debut=datetime(2026, 9, 13, 8, 0), horizon_h=1)
    assert vues[0].url.params["start_hour"] == "2026-09-13T08:00"


def test_debut_dans_un_autre_fuseau_converti_en_utc():
    """10:00 en UTC+2 (heure d'été européenne) = 08:00 UTC."""
    heure_ete = timezone(timedelta(hours=2))
    client, vues = client_repondant(bloc(0.0, 0.0, n=1))
    client.previsions(
        [(0.0, 0.0)], modele="m", debut=datetime(2026, 9, 13, 10, 0, tzinfo=heure_ete), horizon_h=1
    )
    assert vues[0].url.params["start_hour"] == "2026-09-13T08:00"


def test_valeurs_decodees():
    client, _ = client_repondant([bloc(0.0, 0.0)])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert point.lat == 0.0 and point.lon == 0.0
    assert [h.t for h in point.heures] == [
        datetime(2026, 9, 13, 8, tzinfo=UTC),
        datetime(2026, 9, 13, 9, tzinfo=UTC),
        datetime(2026, 9, 13, 10, tzinfo=UTC),
    ]
    assert [h.pluie_mm for h in point.heures] == [0.0, 0.5, 1.2]
    assert point.heures[0].vent_kmh == 14.0
    assert point.heures[0].rafales_kmh == 25.0
    assert point.heures[0].vent_depuis_deg == 45.0
    assert point.heures[0].ressenti_c == 12.0
    assert point.heures[0].temp_c == 14.0


# --- un seul point : l'API renvoie un objet, pas une liste ------------------


def test_reponse_objet_pour_un_seul_point():
    client, _ = client_repondant(bloc(1.0, 2.0, n=2))
    previsions = client.previsions([(1.0, 2.0)], modele="m", debut=DEBUT, horizon_h=2)
    assert len(previsions) == 1
    assert previsions[0].lat == 1.0 and previsions[0].lon == 2.0
    assert len(previsions[0].heures) == 2


def test_reponse_liste_a_un_element_pour_un_seul_point():
    client, _ = client_repondant([bloc(1.0, 2.0, n=2)])
    previsions = client.previsions([(1.0, 2.0)], modele="m", debut=DEBUT, horizon_h=2)
    assert len(previsions) == 1 and len(previsions[0].heures) == 2


# --- valeurs nulles ---------------------------------------------------------


def test_valeurs_nulles_tolerees():
    """Un `null` de `precipitation` reste `None` : pas de repli valeur par valeur.

    Le repli sur `rain` se décidait heure par heure et recopiait le 0.0 de
    `rain` à la place d'un `null` de `precipitation` : la table affichait
    « il ne pleut pas » là où le modèle ne disait rien.
    """
    b = bloc(0.0, 0.0, precipitation=[None, 0.4, None], apparent_temperature=[None, None, None])
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert [h.pluie_mm for h in point.heures] == [None, 0.4, None]
    assert all(h.ressenti_c is None for h in point.heures)


def test_repli_sur_rain_si_precipitation_absente_de_la_reponse():
    """Le repli ne joue que si le modèle ne sert pas du tout `precipitation`."""
    b = bloc(0.0, 0.0)
    del b["hourly"]["precipitation"]
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert [h.pluie_mm for h in point.heures] == [0.0, 0.5, 1.2]


def test_repli_sur_rain_si_la_serie_precipitation_est_nulle():
    """`"precipitation": null` = série non fournie, donc repli sur `rain`."""
    b = bloc(0.0, 0.0, precipitation=None)
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert [h.pluie_mm for h in point.heures] == [0.0, 0.5, 1.2]


def test_pluie_none_si_precipitation_et_rain_nulles():
    b = bloc(0.0, 0.0, precipitation=[None, None, None], rain=[None, None, None])
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert all(h.pluie_mm is None for h in point.heures)


def test_variable_entierement_absente_donne_des_none():
    b = bloc(0.0, 0.0)
    del b["hourly"]["wind_gusts_10m"]
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert all(h.rafales_kmh is None for h in point.heures)


# --- erreurs ----------------------------------------------------------------


@pytest.mark.parametrize("code", [400, 401, 429, 500, 503])
def test_erreur_http_donne_erreur_connecteur(code: int):
    client, _ = client_repondant({"error": True, "reason": "Minutely API request limit"}, code=code)
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions(POINTS_3, modele="m", debut=DEBUT, horizon_h=3)
    message = str(e.value)
    assert str(code) in message
    assert "api.open-meteo.com/v1/forecast" in message
    # L'URL est citée sans paramètres : ni coordonnées, ni fenêtre.
    assert "latitude" not in message and "start_hour" not in message


def test_erreur_http_cite_le_motif_de_l_api_et_le_modele():
    client, _ = client_repondant({"error": True, "reason": "Cannot initialize WeatherModel"}, code=400)
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="modele_inexistant", debut=DEBUT, horizon_h=3)
    assert "Cannot initialize WeatherModel" in str(e.value)
    assert "modele_inexistant" in str(e.value)


def test_erreur_reseau_donne_erreur_connecteur():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable", request=requete)

    with pytest.raises(ErreurConnecteur) as e:
        client_avec(gestionnaire).previsions(POINTS_3, modele="m", debut=DEBUT, horizon_h=3)
    assert "injoignable" in str(e.value) or "ConnectError" in str(e.value)


def test_reponse_non_json():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>pas du json</html>")

    with pytest.raises(ErreurConnecteur) as e:
        client_avec(gestionnaire).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "non-JSON" in str(e.value)


def test_erreur_json_sans_code_http():
    """Open-Meteo répond parfois 200 avec un objet d'erreur."""
    client, _ = client_repondant({"error": True, "reason": "paramètre inconnu"})
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "paramètre inconnu" in str(e.value)


def test_nombre_de_blocs_different_du_nombre_de_points():
    client, _ = client_repondant([bloc(0.0, 0.0), bloc(0.1, 0.0)])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions(POINTS_3, modele="m", debut=DEBUT, horizon_h=3)
    assert "2 bloc" in str(e.value) and "3 point" in str(e.value)


def test_hourly_absent():
    client, _ = client_repondant([{"latitude": 0.0, "longitude": 0.0}])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "hourly" in str(e.value)


def test_hourly_time_absent():
    client, _ = client_repondant([{"latitude": 0.0, "longitude": 0.0, "hourly": {}}])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "hourly.time" in str(e.value)


def test_tableaux_de_longueurs_differentes():
    client, _ = client_repondant([bloc(0.0, 0.0, wind_speed_10m=[14.0, 16.0])])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert "wind_speed_10m" in str(e.value) and "2 valeurs" in str(e.value)


def test_variable_qui_n_est_pas_un_tableau():
    client, _ = client_repondant([bloc(0.0, 0.0, precipitation=0.5)])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert "tableau" in str(e.value)


def test_valeur_de_type_inattendu():
    client, _ = client_repondant([bloc(0.0, 0.0, precipitation=[0.0, "beaucoup", 1.0])])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert "nombre" in str(e.value)


def test_horodatage_illisible():
    client, _ = client_repondant([bloc(0.0, 0.0, time=["pas une date", "x", "y"])])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert "horodatage" in str(e.value)


def test_json_de_type_inattendu():
    client, _ = client_repondant("une chaîne")
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "JSON inattendu" in str(e.value)


def test_bloc_de_type_inattendu():
    client, _ = client_repondant([42])
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "bloc de prévision inattendu" in str(e.value)


def test_aucun_point():
    client, vues = client_repondant([])
    with pytest.raises(ErreurConnecteur):
        client.previsions([], modele="m", debut=DEBUT, horizon_h=1)
    assert vues == []  # pas d'appel inutile


def test_horizon_nul():
    client, vues = client_repondant([])
    with pytest.raises(ErreurConnecteur):
        client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=0)
    assert vues == []


def test_coordonnees_de_retour_defaut_sur_la_demande():
    """Si l'API ne renvoie pas de latitude exploitable, on garde celle demandée."""
    b = bloc(0.0, 0.0, n=1)
    b["latitude"] = None
    b["longitude"] = "?"
    client, _ = client_repondant([b])
    (point,) = client.previsions([(1.5, -2.5)], modele="m", debut=DEBUT, horizon_h=1)
    assert (point.lat, point.lon) == (1.5, -2.5)


def test_base_url_personnalisee():
    client, vues = client_repondant(bloc(0.0, 0.0, n=1))
    client.base_url = "https://exemple.invalide"
    client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert str(vues[0].url).startswith("https://exemple.invalide/v1/forecast")


# --- point hors du domaine du modèle ----------------------------------------
#
# Tests qui auraient attrapé D1. Mesuré sur le vrai service : pour un point
# hors couverture d'AROME, Open-Meteo répond **HTTP 200** avec un corps
# contenant des littéraux `nan` en minuscules — donc invalide en JSON, que
# `reponse.json()` refuse. L'utilisateur recevait « réponse non-JSON
# (Expecting value: line 1 column 14) », qui ne dit rien de la cause.

#: Corps HTTP 200 tel que le vrai service le renvoie hors du domaine du modèle.
CORPS_HORS_DOMAINE = (
    '{"latitude":nan,"longitude":nan,"generationtime_ms":0.07,"utc_offset_seconds":0,'
    '"timezone":"GMT","timezone_abbreviation":"GMT","elevation":nan,'
    '"hourly_units":{"time":"iso8601","precipitation":"mm"},'
    '"hourly":{"time":["2026-09-13T08:00"],"precipitation":[null]}}'
)


def client_texte(corps: str, code: int = 200) -> ClientOpenMeteo:
    """Un client qui répond un corps **brut** : indispensable pour du JSON invalide."""
    return client_avec(lambda _: httpx.Response(code, text=corps))


def test_corps_avec_des_litteraux_nan_donne_hors_du_domaine():
    client = client_texte(CORPS_HORS_DOMAINE)
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(0.0, 0.0)], modele="meteofrance_arome_france_hd", debut=DEBUT, horizon_h=1)
    message = str(e.value)
    assert "hors du domaine" in message
    assert "meteofrance_arome_france_hd" in message, "le message doit nommer le modèle fautif"
    assert "global" in message, "il doit dire quoi faire"
    # Q19 : `ourouler sortie` n'a pas d'option `--modele` — un message de la
    # couche connecteur ne doit pas conseiller une option de ligne de
    # commande qu'il ne connaît pas (c'est à l'appelant de savoir la sienne).
    assert "--modele" not in message
    assert "Expecting value" not in message, "l'erreur de parsing ne renseigne personne"


def test_le_message_hors_domaine_ne_publie_pas_les_coordonnees():
    """Les messages Open-Meteo ne citent jamais le point de départ (confidentialité).

    Le point de contrôle est une vraie coordonnée française — c'est tout
    l'intérêt — donc il est écrit en dix-millièmes de degré entiers et
    reconstitué à l'exécution : en clair, il ferait de ce fichier de test
    exactement ce qu'il dénonce (règle absolue 1).
    """
    lat, lon = 481173 / 10000, -16778 / 10000
    client = client_texte(CORPS_HORS_DOMAINE)
    with pytest.raises(ErreurConnecteur) as e:
        client.previsions([(lat, lon)], modele="m", debut=DEBUT, horizon_h=1)
    for morceau in (f"{lat:.1f}", f"{abs(lon):.2f}", f"{lon:.1f}"):
        assert morceau not in str(e.value)


@pytest.mark.parametrize(
    "corps",
    [
        '{"latitude":nan}',
        '{"elevation":-nan,"hourly":{}}',
        '{"latitude":[nan,nan]}',
        '{"latitude":inf}',
    ],
)
def test_toutes_les_formes_de_litteral_non_json_sont_reconnues(corps: str):
    with pytest.raises(ErreurConnecteur, match="hors du domaine"):
        client_texte(corps).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)


@pytest.mark.parametrize(
    "corps",
    [
        "<html>503 Service Unavailable</html>",
        "",
        '{"timezone":"Europe/Paris","ville":"Nanterre"',  # « nan » dans une chaîne
    ],
)
def test_un_corps_illisible_sans_nan_garde_le_message_generique(corps: str):
    """On ne veut pas diagnostiquer « hors du domaine » à tort sur n'importe quel corps cassé."""
    with pytest.raises(ErreurConnecteur) as e:
        client_texte(corps).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert "non-JSON" in str(e.value)
    assert "hors du domaine" not in str(e.value)


def test_un_point_entierement_nul_donne_hors_du_domaine():
    """Autre signature du même défaut : 200, JSON valide, mais pas une valeur pour ce point."""
    vide = {nom: [None, None, None] for nom in VARIABLES_HORAIRES}
    b = bloc(0.0, 0.0, **vide)
    client, _ = client_repondant([b])
    with pytest.raises(ErreurConnecteur, match="hors du domaine"):
        client.previsions([(0.0, 0.0)], modele="arome", debut=DEBUT, horizon_h=3)


def test_hors_domaine_est_un_type_distinct_pour_permettre_un_repli():
    """Q19 : `ErreurHorsDomaine` doit être catchable à part d'une panne quelconque.

    C'est ce qui permet à un appelant (`boucle.meteo_trace.evaluer`) de
    retenter avec un modèle de repli seulement dans ce cas précis, sans
    masquer une vraie panne réseau sur laquelle retenter ne changerait rien.
    """
    vide = {nom: [None, None, None] for nom in VARIABLES_HORAIRES}
    client, _ = client_repondant([bloc(0.0, 0.0, **vide)])
    with pytest.raises(ErreurHorsDomaine):
        client.previsions([(0.0, 0.0)], modele="arome", debut=DEBUT, horizon_h=3)


def test_un_point_nul_parmi_plusieurs_est_signale():
    nul = bloc(0.1, 0.0, **{nom: [None] * 3 for nom in VARIABLES_HORAIRES})
    charge = [bloc(0.0, 0.0), nul, bloc(0.0, 0.1)]
    client, _ = client_repondant(charge)
    with pytest.raises(ErreurConnecteur, match="hors du domaine"):
        client.previsions(POINTS_3, modele="arome", debut=DEBUT, horizon_h=3)


def test_une_seule_valeur_presente_suffit_a_ne_pas_crier_au_hors_domaine():
    vide = {nom: [None, None, None] for nom in VARIABLES_HORAIRES}
    vide["temperature_2m"] = [None, 12.0, None]
    b = bloc(0.0, 0.0, **vide)
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="arome", debut=DEBUT, horizon_h=3)
    assert point.heures[1].temp_c == 12.0


# --- NaN numérique ----------------------------------------------------------
#
# Tests qui auraient attrapé D9 : `NaN` majuscule (et `Infinity`) sont acceptés
# par le module `json` de Python, qui les rend en flottants. Un NaN de pluie se
# propageait dans les cumuls et rendait `meilleure_direction` arbitraire, sans
# un message — alors que `lecture.py` les écarte explicitement.


def client_json_brut(corps: str) -> ClientOpenMeteo:
    """Un corps JSON écrit à la main : le seul moyen d'y mettre un littéral `NaN`."""
    return client_avec(
        lambda _: httpx.Response(200, text=corps, headers={"content-type": "application/json"})
    )


# `-NaN` n'est pas accepté par le module `json` : il tombe dans la détection
# « hors du domaine » du point 5, testée plus haut.
@pytest.mark.parametrize("litteral", ["NaN", "Infinity", "-Infinity"])
def test_nan_et_infinis_traites_comme_des_valeurs_absentes(litteral: str):
    corps = (
        '{"latitude":0.0,"longitude":0.0,"hourly":{'
        '"time":["2026-09-13T08:00","2026-09-13T09:00"],'
        f'"precipitation":[{litteral},0.5],'
        f'"rain":[{litteral},0.5],'
        f'"wind_speed_10m":[{litteral},16.0],'
        '"wind_direction_10m":[45.0,50.0],"wind_gusts_10m":[25.0,28.0],'
        '"apparent_temperature":[12.0,12.5],"temperature_2m":[14.0,14.5]}}'
    )
    (point,) = client_json_brut(corps).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=2)
    assert point.heures[0].pluie_mm is None, "un NaN de pluie doit valoir « absente »"
    assert point.heures[0].vent_kmh is None
    assert point.heures[1].pluie_mm == 0.5, "la valeur saine de l'heure suivante est gardée"


def test_un_nan_de_pluie_ne_contamine_pas_les_cumuls():
    """La conséquence concrète : un NaN rendait tout cumul, donc tout conseil, arbitraire."""
    corps = (
        '{"latitude":0.0,"longitude":0.0,"hourly":{'
        '"time":["2026-09-13T08:00","2026-09-13T09:00"],'
        '"precipitation":[NaN,1.5],"rain":[NaN,1.5],'
        '"wind_speed_10m":[14.0,16.0],"wind_direction_10m":[45.0,50.0],'
        '"wind_gusts_10m":[25.0,28.0],"apparent_temperature":[12.0,12.5],'
        '"temperature_2m":[14.0,14.5]}}'
    )
    (point,) = client_json_brut(corps).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=2)
    connues = [h.pluie_mm for h in point.heures if h.pluie_mm is not None]
    cumul = sum(connues)
    assert cumul == 1.5
    assert cumul == cumul, "un NaN dans le cumul rendrait toute comparaison fausse"


def test_un_nan_de_precipitation_ne_se_replie_pas_sur_rain():
    """Un NaN se comporte comme un `null` : il reste `None`, il n'emprunte pas `rain`.

    La série `precipitation` est bien servie par le modèle ; le repli ne joue
    donc pas, et la valeur de cette heure-là reste inconnue.
    """
    corps = (
        '{"latitude":0.0,"longitude":0.0,"hourly":{'
        '"time":["2026-09-13T08:00"],'
        '"precipitation":[NaN],"rain":[0.8],'
        '"wind_speed_10m":[14.0],"wind_direction_10m":[45.0],'
        '"wind_gusts_10m":[25.0],"apparent_temperature":[12.0],'
        '"temperature_2m":[14.0]}}'
    )
    (point,) = client_json_brut(corps).previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=1)
    assert point.heures[0].pluie_mm is None


def test_un_point_entierement_nan_est_un_point_hors_domaine():
    """Cohérence avec le point 5 : tout à NaN, c'est tout à None, donc hors du domaine."""
    corps = (
        '{"latitude":0.0,"longitude":0.0,"hourly":{'
        '"time":["2026-09-13T08:00"],'
        '"precipitation":[NaN],"rain":[NaN],"wind_speed_10m":[NaN],'
        '"wind_direction_10m":[NaN],"wind_gusts_10m":[NaN],'
        '"apparent_temperature":[NaN],"temperature_2m":[NaN]}}'
    )
    with pytest.raises(ErreurConnecteur, match="hors du domaine"):
        client_json_brut(corps).previsions([(0.0, 0.0)], modele="arome", debut=DEBUT, horizon_h=1)


def test_les_valeurs_finies_restent_intactes():
    """Le filtre ne doit pas manger les valeurs légitimes, zéro et négatives comprises."""
    b = bloc(0.0, 0.0, apparent_temperature=[-5.0, 0.0, 37.5])
    client, _ = client_repondant([b])
    (point,) = client.previsions([(0.0, 0.0)], modele="m", debut=DEBUT, horizon_h=3)
    assert [h.ressenti_c for h in point.heures] == [-5.0, 0.0, 37.5]

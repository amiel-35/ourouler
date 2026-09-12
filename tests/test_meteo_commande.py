"""Tests de la sous-commande `meteo` (L1.5).

Configuration de test au point (0.0, 0.0), client injecté : aucun accès
réseau, aucune coordonnée réelle, aucune clé.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from ourouler.config import Config, depuis_dict
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.commande import HORIZON_MAX_H, executer, heure_depart
from ourouler.meteo.openmeteo import ClientOpenMeteo

CONFIG_BRUTE = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
    "meteo": {
        "directions": 8,
        "distances_km": [15, 25],
        "modele": "modele_principal_test",
        "second_avis": "modele_second_test",
        "horizon_h": 3,
    },
}


def config_de_test() -> Config:
    return depuis_dict(CONFIG_BRUTE)


def args(**champs) -> argparse.Namespace:
    defauts = {
        "depart": None,
        "horizon": None,
        "distance": None,
        "modele": None,
        "second_avis": None,
        "json": False,
    }
    return argparse.Namespace(**{**defauts, **champs})


def bloc(lat: float, lon: float, n: int, pluie: float) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-13T{8 + i:02d}:00" for i in range(n)],
            "precipitation": [pluie] * n,
            "rain": [pluie] * n,
            "wind_speed_10m": [14.0] * n,
            "wind_direction_10m": [0.0] * n,
            "wind_gusts_10m": [25.0] * n,
            "apparent_temperature": [12.0] * n,
            "temperature_2m": [14.0] * n,
        },
    }


def client_mock(pluie_principale: float = 0.0, pluie_second: float = 0.0, echec_second: bool = False):
    """Client Open-Meteo bouchonné : répond par modèle, sans jamais sortir du process."""
    appels: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        modele = requete.url.params["models"]
        if echec_second and modele == "modele_second_test":
            return httpx.Response(429, json={"error": True, "reason": "limite atteinte"})
        pluie = pluie_second if modele == "modele_second_test" else pluie_principale
        lats = requete.url.params["latitude"].split(",")
        lons = requete.url.params["longitude"].split(",")
        debut = datetime.fromisoformat(requete.url.params["start_hour"])
        fin = datetime.fromisoformat(requete.url.params["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        return httpx.Response(
            200,
            json=[bloc(float(a), float(o), n, pluie) for a, o in zip(lats, lons, strict=True)],
        )

    client = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    return client, appels


# --- heure de départ --------------------------------------------------------


def test_heure_depart_par_defaut_arrondie_a_l_heure():
    maintenant = datetime(2026, 9, 13, 8, 47, 23, tzinfo=UTC)
    assert heure_depart(None, maintenant) == datetime(2026, 9, 13, 8, 0, tzinfo=UTC)


def test_heure_depart_hh_mm_aujourd_hui_en_local():
    heure_ete = timezone(timedelta(hours=2))
    maintenant = datetime(2026, 9, 13, 6, 30, tzinfo=heure_ete)
    t = heure_depart("14:30", maintenant)
    assert t == datetime(2026, 9, 13, 14, 0, tzinfo=heure_ete)
    assert t.astimezone(UTC).hour == 12  # le client interrogera 12:00 UTC


def test_heure_depart_iso_complet():
    maintenant = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
    assert heure_depart("2026-09-15T07:00", maintenant) == datetime(2026, 9, 15, 7, 0, tzinfo=UTC)


def test_heure_depart_minutes_tronquees():
    maintenant = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
    assert heure_depart("2026-09-15T07:45", maintenant).minute == 0


@pytest.mark.parametrize("mauvais", ["", "   ", "25:00", "demain", "2026-13-45T07:00", "7h"])
def test_heure_depart_invalide(mauvais: str):
    maintenant = datetime(2026, 9, 13, 6, 0, tzinfo=UTC)
    if not mauvais.strip():
        # Chaîne vide = pas d'option : on retombe sur l'heure courante.
        assert heure_depart(mauvais, maintenant) == maintenant
        return
    with pytest.raises(ErreurUtilisateur) as e:
        heure_depart(mauvais, maintenant)
    assert "--depart" in str(e.value)


# --- exécution --------------------------------------------------------------


def test_executer_affiche_la_table(capsys):
    client, appels = client_mock()
    assert executer(args(), config_de_test(), client=client) == 0
    sortie = capsys.readouterr()
    assert sortie.err == ""
    assert "Point zéro" in sortie.out
    assert "Direction conseillée" in sortie.out
    for direction in ("N", "NE", "E", "SE", "S", "SO", "O", "NO"):
        assert any(ligne.startswith(direction) for ligne in sortie.out.splitlines())
    assert "── 15 km" in sortie.out and "── 25 km" in sortie.out
    # Deux appels seulement : modèle principal + second avis.
    assert len(appels) == 2
    assert {a.url.params["models"] for a in appels} == {
        "modele_principal_test",
        "modele_second_test",
    }


def test_executer_un_seul_appel_par_modele_pour_tous_les_points():
    client, appels = client_mock()
    executer(args(), config_de_test(), client=client)
    for appel in appels:
        # 1 (« ici ») + 8 directions × 2 distances = 17 coordonnées dans un seul appel.
        assert len(appel.url.params["latitude"].split(",")) == 17


def test_executer_respecte_horizon_et_modeles_des_options():
    client, appels = client_mock()
    executer(
        args(horizon=2, modele="autre_principal", second_avis="autre_second"),
        config_de_test(),
        client=client,
    )
    assert {a.url.params["models"] for a in appels} == {"autre_principal", "autre_second"}
    for appel in appels:
        debut = datetime.fromisoformat(appel.url.params["start_hour"])
        fin = datetime.fromisoformat(appel.url.params["end_hour"])
        assert fin - debut == timedelta(hours=1)  # 2 heures inclusives


def test_executer_depart_explicite(capsys):
    client, appels = client_mock()
    executer(args(depart="2026-09-13T08:00"), config_de_test(), client=client)
    # 08:00 local converti en UTC : on ne vérifie que la date, le fuseau dépend de la machine.
    assert appels[0].url.params["start_hour"].startswith("2026-09-1")
    assert "13 septembre 2026" in capsys.readouterr().out


def test_executer_filtre_une_distance(capsys):
    client, _ = client_mock()
    executer(args(distance=25.0), config_de_test(), client=client)
    sortie = capsys.readouterr().out
    assert "── 25 km" in sortie and "── 15 km" not in sortie


def test_executer_json(capsys):
    client, _ = client_mock(pluie_principale=1.0, pluie_second=0.0)
    assert executer(args(json=True), config_de_test(), client=client) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["modele"] == "modele_principal_test"
    assert d["second_avis"] == "modele_second_test"
    assert len(d["cellules"]) == 17 * 3
    assert all(c["confiance"] == "desaccord" for c in d["cellules"])


def test_executer_second_avis_en_echec_avertit_mais_ne_plante_pas(capsys):
    client, _ = client_mock(echec_second=True)
    assert executer(args(), config_de_test(), client=client) == 0
    sortie = capsys.readouterr()
    assert "second avis" in sortie.err and "429" in sortie.err
    assert "Direction conseillée" in sortie.out


def test_executer_second_avis_en_echec_donne_confiance_inconnue(capsys):
    client, _ = client_mock(echec_second=True)
    executer(args(json=True), config_de_test(), client=client)
    sortie = capsys.readouterr()
    d = json.loads(sortie.out)
    assert all(c["confiance"] == "inconnu" for c in d["cellules"])
    assert "inconnu" in sortie.err


def test_executer_echec_du_modele_principal_remonte():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": True, "reason": "en panne"})

    client = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur) as e:
        executer(args(), config_de_test(), client=client)
    assert "500" in str(e.value)


def test_executer_second_avis_identique_au_principal_un_seul_appel(capsys):
    """Inutile de demander deux fois le même modèle : un seul appel, confiance « inconnu »."""
    client, appels = client_mock()
    executer(
        args(modele="meme_modele", second_avis="meme_modele", json=True),
        config_de_test(),
        client=client,
    )
    assert len(appels) == 1
    d = json.loads(capsys.readouterr().out)
    assert all(c["confiance"] == "inconnu" for c in d["cellules"])


@pytest.mark.parametrize("horizon", [0, -1, HORIZON_MAX_H + 1])
def test_executer_horizon_hors_bornes(horizon: int):
    client, appels = client_mock()
    with pytest.raises(ErreurUtilisateur) as e:
        executer(args(horizon=horizon), config_de_test(), client=client)
    assert "horizon" in str(e.value)
    assert appels == []  # rien n'est demandé à l'API


def test_executer_directions_invalides_dans_la_config():
    config = depuis_dict({**CONFIG_BRUTE, "meteo": {**CONFIG_BRUTE["meteo"], "directions": 5}})
    client, appels = client_mock()
    with pytest.raises(ErreurUtilisateur) as e:
        executer(args(), config, client=client)
    assert "directions" in str(e.value)
    assert appels == []

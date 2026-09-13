"""Tests de l'inventaire et du rattachement au vélo (L1.3)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import (
    HOME_TRAINER,
    INCONNU,
    inventaire,
    rattacher_velo,
    rendre_json,
    rendre_texte,
)
from ourouler.cli import main
from ourouler.config import Config, depuis_dict

# Point fictif en mer : jamais de coordonnée réelle, même dans une config de test.
CONFIG_BRUTE = {
    "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
    "velos": [
        {"nom": "Route", "usage": "route", "intervals_gear": "velo-test-route"},
        {
            "nom": "CLM",
            "usage": "clm",
            "intervals_gear": "velo-test-clm",
            "periodes": [{"debut": "2024-06-01", "fin": "2024-06-30"}],
        },
    ],
}


@pytest.fixture
def config() -> Config:
    return depuis_dict(CONFIG_BRUTE)


def entree(**champs) -> EntreeCache:
    """Entrée de cache minimale, surchargée par mot-clé."""
    defauts = dict(
        identifiant="a" * 64,
        source="intervals",
        id_externe="1",
        debut=datetime(2024, 3, 30, 9, 0, tzinfo=UTC),
        duree_s=3600.0,
        distance_m=30000.0,
        puissance_moy_w=200.0,
        sport="Ride",
        appareil="Appareil de test",
        equipement=None,
        chemin=Path("/inexistant"),
        meta={},
    )
    return EntreeCache(**{**defauts, **champs})


# --- les quatre règles de rattachement, dans l'ordre --------------------------


def test_regle_1_equipement_de_la_source(config: Config):
    assert rattacher_velo(entree(equipement="velo-test-clm"), config) == "CLM"


def test_regle_1_insensible_a_la_casse_et_aux_espaces(config: Config):
    assert rattacher_velo(entree(equipement="  VELO-Test-CLM "), config) == "CLM"


def test_regle_1_prime_sur_la_periode(config: Config):
    """Un équipement connu gagne même si la date tombe dans la période d'un autre vélo."""
    dans_la_periode_clm = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    assert (
        rattacher_velo(entree(equipement="velo-test-route", debut=dans_la_periode_clm), config)
        == "Route"
    )


def test_regle_1_prime_sur_l_interieur(config: Config):
    assert (
        rattacher_velo(entree(equipement="velo-test-clm", sport="VirtualRide"), config) == "CLM"
    )


def test_regle_2_periode_du_velo(config: Config):
    assert rattacher_velo(entree(debut=datetime(2024, 6, 15, 9, 0, tzinfo=UTC)), config) == "CLM"
    # Hors période : on retombe sur la règle 4.
    assert rattacher_velo(entree(debut=datetime(2024, 7, 1, 9, 0, tzinfo=UTC)), config) == "Route"


def test_regle_2_prime_sur_l_interieur(config: Config):
    dans_la_periode = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    assert rattacher_velo(entree(debut=dans_la_periode, sport="VirtualRide"), config) == "CLM"


@pytest.mark.parametrize(
    "champs",
    [
        {"sport": "VirtualRide"},
        {"sport": "virtual_ride"},
        {"sport": "cycling/indoor_cycling"},
        {"appareil": "Zwift 1.70"},
        {"appareil": "rouvy"},
        {"meta": {"interieur": True}},
    ],
    ids=["virtualride", "virtual_ride", "indoor_cycling", "zwift", "rouvy", "meta"],
)
def test_regle_3_sport_interieur(config: Config, champs: dict):
    assert rattacher_velo(entree(**champs), config) == HOME_TRAINER


def test_regle_4_premier_velo_de_route(config: Config):
    assert rattacher_velo(entree(), config) == "Route"


def test_regle_4_sans_velo_de_route():
    """Aucun vélo d'usage route : on prend le premier déclaré, pas une exception."""
    config = depuis_dict({**CONFIG_BRUTE, "velos": [{"nom": "CLM", "usage": "clm"}]})
    assert rattacher_velo(entree(), config) == "CLM"


def test_rattachement_sans_date(config: Config):
    """Une entrée sans début ne peut pas passer par les périodes, mais ne casse pas."""
    assert rattacher_velo(entree(debut=None), config) == "Route"


def test_velo_inconnu_est_un_nom_reserve():
    assert INCONNU == "inconnu" and HOME_TRAINER == "home-trainer"


# --- inventaire sur un vrai cache ---------------------------------------------


@pytest.fixture
def cache_rempli(tmp_path: Path, activites: Path) -> Cache:
    c = Cache(tmp_path / "cache")
    c.indexer_dossier(activites)
    return c


def test_inventaire_par_velo(cache_rempli: Cache, config: Config):
    inv = inventaire(cache_rempli, config, date(2023, 12, 1))
    assert inv.total == 8
    par_nom = {s.velo: s for s in inv.par_velo}
    assert set(par_nom) == {"Route", HOME_TRAINER}
    route = par_nom["Route"]
    assert route.nombre == 7
    assert route.km > 30
    assert route.heures > 0.5
    assert route.premiere == date(2024, 3, 30)
    assert route.derniere == date(2024, 4, 2)
    assert 0 < route.part_puissance < 1  # sans_puissance.gpx est dans le lot
    assert par_nom[HOME_TRAINER].nombre == 1
    assert par_nom[HOME_TRAINER].part_puissance == 1.0


def test_inventaire_par_mois_exclut_l_interieur(cache_rempli: Cache, config: Config):
    inv = inventaire(cache_rempli, config, date(2023, 12, 1))
    par_mois = {m.mois: m for m in inv.par_mois}
    assert sorted(par_mois) == ["2024-03", "2024-04"]
    # 7 activités en mars, dont une sur home-trainer : 6 sorties extérieures.
    assert par_mois["2024-03"].sorties == 6
    assert par_mois["2024-03"].sorties_avec_puissance == 5
    assert par_mois["2024-04"].sorties == 1
    assert par_mois["2024-03"].km > 0


def test_inventaire_signale_les_anomalies(cache_rempli: Cache, config: Config):
    inv = inventaire(cache_rempli, config, date(2023, 12, 1))
    motifs = {a.motif.split(" (")[0].split(" ")[0] for a in inv.anomalies}
    assert "durée" in motifs
    assert any("sans puissance" == a.motif for a in inv.anomalies)
    assert all(a.identifiant for a in inv.anomalies)


def test_anomalie_distance_nulle(tmp_path: Path, config: Config, monkeypatch):
    cache = Cache(tmp_path / "cache")

    def lister(depuis=None, jusqua=None):
        return [entree(distance_m=0.0, duree_s=1800.0)]

    monkeypatch.setattr(cache, "lister", lister)
    inv = inventaire(cache, config, date(2023, 12, 1))
    assert [a.motif for a in inv.anomalies] == ["distance nulle"]


def test_inventaire_respecte_depuis(cache_rempli: Cache, config: Config):
    inv = inventaire(cache_rempli, config, date(2024, 4, 1))
    assert inv.total == 1
    assert [m.mois for m in inv.par_mois] == ["2024-04"]


def test_inventaire_vide(tmp_path: Path, config: Config):
    inv = inventaire(Cache(tmp_path / "cache"), config, date(2023, 12, 1))
    assert inv.total == 0 and inv.par_velo == [] and inv.anomalies == []
    assert "Cache vide" in rendre_texte(inv)


# --- rendus -------------------------------------------------------------------


def test_rendre_texte(cache_rempli: Cache, config: Config):
    texte = rendre_texte(inventaire(cache_rempli, config, date(2023, 12, 1)))
    assert "Inventaire des sorties depuis le 2023-12-01" in texte
    assert "Par vélo" in texte and "Par mois" in texte and "Anomalies" in texte
    assert "Route" in texte and HOME_TRAINER in texte
    assert "2024-03" in texte


def test_rendre_json_est_serialisable(cache_rempli: Cache, config: Config):
    d = rendre_json(inventaire(cache_rempli, config, date(2023, 12, 1)))
    retour = json.loads(json.dumps(d, ensure_ascii=False))  # doit passer sans `default=`
    assert retour["depuis"] == "2023-12-01"
    assert retour["total"] == 8
    assert {v["velo"] for v in retour["par_velo"]} == {"Route", HOME_TRAINER}
    assert retour["par_mois"][0]["mois"] == "2024-03"
    assert isinstance(retour["anomalies"], list)


# --- bout en bout par la CLI --------------------------------------------------

CONFIG_TOML = """
historique_depuis = "2023-12-01"
[depart]
nom = "Point fictif"
latitude = 0.0
longitude = 0.0
[cycliste]
masse_kg = 80
ftp_w = 250
[[velos]]
nom = "Route"
usage = "route"
[cache]
dossier = "{cache}"
"""


@pytest.fixture
def config_toml(tmp_path: Path) -> Path:
    chemin = tmp_path / "config_test.toml"
    chemin.write_text(CONFIG_TOML.format(cache=tmp_path / "cache"), encoding="utf-8")
    return chemin


def test_cli_inventaire_importer(config_toml: Path, activites: Path, capsys):
    code = main(["--config", str(config_toml), "inventaire", "--importer", str(activites)])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "8 activité(s) ajoutée(s)" in sortie
    assert "Inventaire des sorties" in sortie
    assert "ignoré — vide.fit" in sortie


def test_cli_inventaire_json(config_toml: Path, activites: Path, capsys):
    main(["--config", str(config_toml), "--json", "inventaire", "--importer", str(activites)])
    d = json.loads(capsys.readouterr().out)
    assert d["total"] == 8
    assert d["journal"] and "ajoutée" in d["journal"][0]


def test_cli_inventaire_depuis(config_toml: Path, activites: Path, capsys):
    main(["--config", str(config_toml), "inventaire", "--importer", str(activites)])
    capsys.readouterr()
    main(["--config", str(config_toml), "--json", "inventaire", "--depuis", "2024-04-01"])
    d = json.loads(capsys.readouterr().out)
    assert d["depuis"] == "2024-04-01" and d["total"] == 1


def test_cli_inventaire_depuis_invalide(config_toml: Path, capsys):
    assert main(["--config", str(config_toml), "inventaire", "--depuis", "hier"]) == 2
    assert "--depuis" in capsys.readouterr().err


def test_cli_synchroniser_sans_cle_refuse_proprement(config_toml: Path, capsys):
    """Sans clé, la commande doit refuser en une ligne — et surtout pas tenter le réseau."""
    assert main(["--config", str(config_toml), "inventaire", "--synchroniser"]) == 2
    erreur = capsys.readouterr().err
    assert "athlete_id" in erreur and "api_key" in erreur

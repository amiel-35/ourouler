"""Tests de l'inventaire et du rattachement au vélo (L1.3, révisé par L2.7).

Les noms de capteurs et les identifiants d'équipement sont **inventés** : ce
sont des chaînes de test, jamais les valeurs du compte du mainteneur.
"""

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
        {
            "nom": "Route",
            "usage": "route",
            "intervals_gear": "velo-test-route",
            "intervals_gear_id": "b-test-route",
            "capteur_puissance": "CAPTEUR 0001",
        },
        {
            "nom": "CLM",
            "usage": "clm",
            "intervals_gear": "velo-test-clm",
            "intervals_gear_id": "b-test-clm",
            "capteur_puissance": "CAPTEUR 0002",
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


# --- les cinq règles de rattachement, dans l'ordre ----------------------------
#
# L'ordre : (1) intérieur ; (2) capteur de puissance ; (3) gear_id ou
# équipement ; (4) période ; (5) premier vélo d'usage route. L'intérieur
# prime même sur l'équipement.


def test_regle_1_interieur():
    """« (1) intérieur (VirtualRide, meta["trainer"] vrai, appareil Zwift/Rouvy,
    meta["interieur"]) → "home-trainer" »."""
    config = depuis_dict(CONFIG_BRUTE)
    for champs in (
        {"sport": "VirtualRide"},
        {"sport": "virtual_ride"},
        {"sport": "cycling/indoor_cycling"},
        {"appareil": "Zwift 1.70"},
        {"appareil": "rouvy"},
        {"meta": {"interieur": True}},
        {"meta": {"trainer": True}},
    ):
        assert rattacher_velo(entree(**champs), config) == HOME_TRAINER, champs


def test_regle_2_capteur_de_puissance(config: Config):
    """« (2) meta["power_meter"] égal […] à velo.capteur_puissance non vide »."""
    assert rattacher_velo(entree(meta={"power_meter": "CAPTEUR 0002"}), config) == "CLM"
    assert rattacher_velo(entree(meta={"power_meter": "CAPTEUR 0001"}), config) == "Route"


@pytest.mark.parametrize("capteur", ["capteur 0002", "  CAPTEUR   0002 ", "Capteur0002"])
def test_regle_2_insensible_a_la_casse_et_aux_espaces(config: Config, capteur: str):
    assert rattacher_velo(entree(meta={"power_meter": capteur}), config) == "CLM"


@pytest.mark.parametrize("capteur", [None, "", "   ", "CAPTEUR 9999"])
def test_regle_2_capteur_vide_ou_inconnu_ne_capture_pas(config: Config, capteur):
    """Un capteur absent ou étranger ne doit pas attraper une sortie au hasard."""
    assert rattacher_velo(entree(meta={"power_meter": capteur}), config) == "Route"


def test_regle_2_un_capteur_vide_en_configuration_ne_capture_rien():
    """Un vélo sans `capteur_puissance` ne doit pas rafler les sorties sans capteur."""
    config = depuis_dict(
        {
            **CONFIG_BRUTE,
            "velos": [
                {"nom": "Sans capteur", "usage": "clm"},
                {"nom": "Route", "usage": "route"},
            ],
        }
    )
    assert rattacher_velo(entree(meta={"power_meter": ""}), config) == "Route"


def test_regle_3_gear_id(config: Config):
    """« (3) meta["gear_id"] égal à velo.intervals_gear_id non vide »."""
    assert rattacher_velo(entree(meta={"gear_id": "b-test-clm"}), config) == "CLM"
    assert rattacher_velo(entree(meta={"gear_id": "b-inconnu"}), config) == "Route"


def test_regle_3_equipement_de_la_source(config: Config):
    """« … ou equipement égal (casse) à velo.intervals_gear non vide »."""
    assert rattacher_velo(entree(equipement="velo-test-clm"), config) == "CLM"


def test_regle_3_equipement_insensible_a_la_casse_et_aux_espaces(config: Config):
    assert rattacher_velo(entree(equipement="  VELO-Test-CLM "), config) == "CLM"


def test_regle_4_periode_du_velo(config: Config):
    assert rattacher_velo(entree(debut=datetime(2024, 6, 15, 9, 0, tzinfo=UTC)), config) == "CLM"
    # Hors période : on retombe sur la règle 5.
    assert rattacher_velo(entree(debut=datetime(2024, 7, 1, 9, 0, tzinfo=UTC)), config) == "Route"


def test_regle_5_premier_velo_de_route(config: Config):
    assert rattacher_velo(entree(), config) == "Route"


def test_regle_5_sans_velo_de_route():
    """Aucun vélo d'usage route : on prend le premier déclaré, pas une exception."""
    config = depuis_dict({**CONFIG_BRUTE, "velos": [{"nom": "CLM", "usage": "clm"}]})
    assert rattacher_velo(entree(), config) == "CLM"


# --- l'ordre lui-même : un cas par paire de règles concurrentes ---------------
#
# Les paires « n avant 5 » n'ont pas de test à elles : le vélo par défaut de
# `CONFIG_BRUTE` est « Route », donc chaque `test_regle_n_*` qui attend « CLM »
# (ou le home-trainer) prouve déjà que la règle n passe devant la règle 5.


def test_1_avant_2_l_interieur_prime_sur_le_capteur(config: Config):
    """Le home-trainer se fait avec le capteur du vélo de route : c'est quand même
    de l'intérieur, sinon ces kilomètres virtuels s'ajoutent au vélo."""
    ht = entree(sport="VirtualRide", meta={"power_meter": "CAPTEUR 0001"})
    assert rattacher_velo(ht, config) == HOME_TRAINER


def test_1_avant_3_l_interieur_prime_sur_l_equipement(config: Config):
    ht = entree(sport="VirtualRide", equipement="velo-test-clm", meta={"gear_id": "b-test-clm"})
    assert rattacher_velo(ht, config) == HOME_TRAINER


def test_1_avant_4_l_interieur_prime_sur_la_periode(config: Config):
    dans_la_periode = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    assert rattacher_velo(entree(debut=dans_la_periode, sport="VirtualRide"), config) == HOME_TRAINER


def test_2_avant_3_le_capteur_prime_sur_l_equipement(config: Config):
    """Équipement et capteur se contredisent : le capteur gagne. C'est lui qui est
    physiquement monté sur le vélo ; `gear` est ce que l'athlète a bien voulu saisir."""
    contradictoire = entree(
        meta={"power_meter": "CAPTEUR 0002", "gear_id": "b-test-route"},
        equipement="velo-test-route",
    )
    assert rattacher_velo(contradictoire, config) == "CLM"


def test_2_avant_4_le_capteur_prime_sur_la_periode(config: Config):
    dans_la_periode_clm = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    sortie = entree(debut=dans_la_periode_clm, meta={"power_meter": "CAPTEUR 0001"})
    assert rattacher_velo(sortie, config) == "Route"


def test_3_avant_4_l_equipement_prime_sur_la_periode(config: Config):
    """Un équipement connu gagne même si la date tombe dans la période d'un autre vélo."""
    dans_la_periode_clm = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    assert (
        rattacher_velo(entree(equipement="velo-test-route", debut=dans_la_periode_clm), config)
        == "Route"
    )
    assert (
        rattacher_velo(entree(meta={"gear_id": "b-test-route"}, debut=dans_la_periode_clm), config)
        == "Route"
    )


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


# --- colonne « capteur » et filtrage des sports (L2.7) ------------------------


def _cache_bouchonne(tmp_path: Path, entrees, monkeypatch) -> Cache:
    cache = Cache(tmp_path / "cache")
    monkeypatch.setattr(cache, "lister", lambda depuis=None, jusqua=None: list(entrees))
    return cache


def test_capteurs_vus_par_velo(tmp_path: Path, config: Config, monkeypatch):
    """Le tableau par vélo doit montrer sur quoi repose le rattachement."""
    cache = _cache_bouchonne(
        tmp_path,
        [
            entree(identifiant="1" * 64, meta={"power_meter": "CAPTEUR 0001"}),
            entree(identifiant="2" * 64, meta={"power_meter": "CAPTEUR 0001"}),
            entree(identifiant="3" * 64, meta={"power_meter": "CAPTEUR 0002"}),
        ],
        monkeypatch,
    )
    inv = inventaire(cache, config, date(2023, 12, 1))
    par_nom = {s.velo: s for s in inv.par_velo}
    assert par_nom["Route"].capteurs == ["CAPTEUR 0001"]  # deux sorties, une valeur distincte
    assert par_nom["CLM"].capteurs == ["CAPTEUR 0002"]
    texte = rendre_texte(inv)
    assert "capteur" in texte and "CAPTEUR 0001" in texte and "CAPTEUR 0002" in texte
    assert rendre_json(inv)["par_velo"][0]["capteurs"]


def test_capteur_absent_ne_casse_pas_le_tableau(cache_rempli: Cache, config: Config):
    inv = inventaire(cache_rempli, config, date(2023, 12, 1))
    assert all(s.capteurs == [] for s in inv.par_velo)
    assert "capteur" in rendre_texte(inv)


def test_inventaire_ecarte_les_autres_sports(tmp_path: Path, config: Config, monkeypatch):
    """936 activités dont 359 footings : un inventaire de sorties vélo n'en veut pas."""
    cache = _cache_bouchonne(
        tmp_path,
        [
            entree(identifiant="1" * 64, sport="Ride"),
            entree(identifiant="2" * 64, sport="Run"),
            entree(identifiant="3" * 64, sport="Swim"),
            entree(identifiant="4" * 64, sport="WeightTraining"),
            entree(identifiant="5" * 64, sport="VirtualRide"),
        ],
        monkeypatch,
    )
    inv = inventaire(cache, config, date(2023, 12, 1))
    assert inv.total == 2
    assert inv.autres_sports == 3
    assert sum(s.nombre for s in inv.par_velo) == 2
    assert "3 activité(s) d'autres sports ignorée(s)" in rendre_texte(inv)
    assert rendre_json(inv)["autres_sports"] == 3


def test_l_inventaire_dit_lesquels_il_ecarte(tmp_path: Path, config: Config, monkeypatch):
    """Point 16 de la relecture : le nombre seul ne suffit pas.

    Avec « Triathlon » parmi les libellés écartés, le mainteneur ne pouvait
    pas savoir que des sorties vélo réelles venaient de sortir de
    l'inventaire. Les libellés sont donc cités, du plus fréquent au moins.
    """
    entrees = [entree(identifiant=f"{i:064d}", sport="Run") for i in range(10)]
    entrees += [entree(identifiant=f"{100 + i:064d}", sport="Swim") for i in range(4)]
    entrees += [entree(identifiant=f"{200 + i:064d}", sport="Triathlon") for i in range(2)]
    entrees.append(entree(identifiant="f" * 64, sport="Ride"))
    cache = _cache_bouchonne(tmp_path, entrees, monkeypatch)

    inv = inventaire(cache, config, date(2023, 12, 1))
    assert inv.autres_sports == 16
    assert inv.autres_sports_par_libelle == {"Run": 10, "Swim": 4, "Triathlon": 2}
    texte = rendre_texte(inv)
    assert "16 activité(s) d'autres sports ignorée(s) (Run 10, Swim 4, Triathlon 2)." in texte, texte
    assert rendre_json(inv)["autres_sports_par_libelle"] == {"Run": 10, "Swim": 4, "Triathlon": 2}


def test_la_liste_des_libelles_ecartes_ne_deroule_pas_tout(
    tmp_path: Path, config: Config, monkeypatch
):
    """Au-delà de quelques libellés, la ligne dit « … » plutôt que de tout dérouler."""
    autres = ["Run", "Swim", "WeightTraining", "Hike", "AlpineSki", "Rowing"]
    entrees = [entree(identifiant=f"{i:064d}", sport=sport) for i, sport in enumerate(autres)]
    entrees.append(entree(identifiant="f" * 64, sport="Ride"))
    cache = _cache_bouchonne(tmp_path, entrees, monkeypatch)

    inv = inventaire(cache, config, date(2023, 12, 1))
    ligne = next(x for x in rendre_texte(inv).splitlines() if "autres sports" in x)
    assert ligne.endswith("…)."), ligne
    assert len(inv.autres_sports_par_libelle) == len(autres), "le JSON, lui, garde tout"


@pytest.mark.parametrize(
    "sport", ["cycling", "cycling/indoor_cycling", "Biking", None, "", "GravelRide"]
)
def test_les_sports_de_fichier_restent_du_velo(
    tmp_path: Path, config: Config, monkeypatch, sport
):
    """Un FIT dit « cycling », un TCX « Biking » : un filtre calé sur le seul
    vocabulaire d'Intervals jetterait tout ce qui vient de `--importer`."""
    cache = _cache_bouchonne(tmp_path, [entree(sport=sport)], monkeypatch)
    inv = inventaire(cache, config, date(2023, 12, 1))
    assert (inv.total, inv.autres_sports) == (1, 0)


def test_cli_sans_rafraichir_existe_et_n_appelle_pas_le_reseau(config_toml: Path, capsys):
    """L'option est reconnue ; sans clé, la commande refuse toujours avant tout appel."""
    assert main(["--config", str(config_toml), "inventaire", "--synchroniser", "--sans-rafraichir"]) == 2
    assert "api_key" in capsys.readouterr().err

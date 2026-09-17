"""Tests de l'API (lot F1).

**Aucun réseau** (règle absolue 3) : les clients BRouter, Open-Meteo et
Intervals sont ceux, bouchonnés par `httpx.MockTransport`, des tests de
`ourouler sortie` — c'est précisément ce que l'injection de clients dans
`api.routes.Clients` sert à rendre possible.

**Aucune donnée personnelle** (règle absolue 1) : le départ est le point
fictif (0, 0), la clé Intervals est celle, inventée, de
`tests/test_seance_intervals.py`, et la FTP est celle des fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

#: **Sans l'extra `api`, ce module se saute au lieu de casser la collecte.**
#: `uv sync && uv run pytest` sur un dépôt fraîchement cloné n'installe pas
#: FastAPI (extra `api`) : sans cette ligne, l'import ci-dessous levait une
#: erreur de collecte, et le contributeur voyait la suite échouer au lieu de
#: voir des tests ignorés. `uv sync --all-extras` les rend.
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

import httpx
from fastapi.testclient import TestClient
from test_seance_intervals import ATHLETE, CLE, W
from test_sortie_commande import (
    JOUR,
    client_intervals,
    ecrire_calibration,
    moteur_brouter,
    moteur_meteo,
    reponse_anneau,
)

from ourouler.api.adaptateur import Budgets
from ourouler.api.application import creer_application
from ourouler.api.depots import DepotFichiers, DepotProfils, SocleTOML, nom_sur
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.api.routes import Clients
from ourouler.config import depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.geocodage import ClientBAN, ClientNominatim
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurConfig

#: La configuration servie par le serveur de test. Point fictif en pleine mer,
#: clé inventée, serveur BRouter qui n'existe pas (tous les appels sont
#: bouchonnés).
CONFIG_TOML = f"""
historique_depuis = "2023-12-01"

[depart]
nom = "Point zéro"
latitude = 0.0
longitude = 0.0

[cycliste]
masse_kg = 76.5
ftp_w = {W.FTP_TEST}

[[velos]]
nom = "Route"
usage = "route"
masse_kg = 8.5
cda_m2 = 0.32

[[velos]]
nom = "CLM"
usage = "clm"
masse_kg = 9.5
cda_m2 = 0.26

[meteo]
directions = 8
distances_km = [15]
modele = "modele_principal_test"
second_avis = ""
horizon_h = 6

[brouter]
url = "https://brouter.exemple.test"
profil = "fastbike"
timeout_s = 5.0

[boucle]
vitesse_moyenne_kmh = 27.0
sens = "horaire"
candidates = 2

[intervals]
athlete_id = "{ATHLETE}"
api_key = "{CLE}"

[cache]
dossier = "{{cache}}"
"""

AUTRE = Proprietaire("autre-cycliste")


def ecrire_config(tmp_path: Path) -> Path:
    chemin = tmp_path / "config.toml"
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    chemin.write_text(CONFIG_TOML.replace("{cache}", str(cache)), encoding="utf-8")
    return chemin


def serveur(tmp_path: Path, **clients) -> TestClient:
    """Une application prête, clients bouchonnés, dossier de données isolé."""
    ecrire_calibration(tmp_path / "cache")
    application = creer_application(
        chemin_config=ecrire_config(tmp_path),
        dossier_donnees=tmp_path / "cache" / "api",
        clients=Clients(**clients),
        budgets=Budgets(),
    )
    # Le gestionnaire d'exception de l'application doit répondre, pas être
    # court-circuité par le client de test : c'est le comportement réel qu'on
    # vérifie, y compris pour le 500.
    return TestClient(application, raise_server_exceptions=False)


def moteur_muet(code: int = 502, charge: dict | None = None) -> ClientBrouter:
    """Un BRouter qui refuse — la panne la plus banale du service."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(code, json=charge or {"erreur": "indisponible"})

    params = depuis_dict(
        {
            "depart": {"nom": "x", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 70, "ftp_w": 200},
            "brouter": {"url": "https://brouter.exemple.test", "timeout_s": 5.0},
        }
    ).brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def intervals_refuse(code: int = 401) -> ClientIntervals:
    """Une clé révoquée : Intervals répond 401, et ce n'est pas une panne."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(code, json={"error": "unauthorized"})

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


def geocodeur(candidats: list[dict]) -> ClientBAN:
    """La BAN bouchonnée, qui rend plusieurs candidats — le cas normal."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "properties": {"label": c["label"], "score": c["score"]},
                        "geometry": {"type": "Point", "coordinates": [c["lon"], c["lat"]]},
                    }
                    for c in candidats
                ]
            },
        )

    return ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def nominatim_vide() -> ClientNominatim:
    """Nominatim qui répond, sans rien trouver — le repli d'une BAN muette."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(200, json=[])

    return ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def nominatim_muet() -> ClientNominatim:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"Nominatim ne devait pas être appelé : {requete.url}")

    return ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


# --- système et profil --------------------------------------------------------


def test_le_systeme_dit_ce_qui_est_renseigne_sans_dire_avec_quoi(tmp_path: Path):
    reponse = serveur(tmp_path).get("/api/v1/systeme")
    assert reponse.status_code == 200
    charge = reponse.json()
    assert charge["capacites"] == {
        "intervals": True,
        "brouter": True,
        "velos": ["Route", "CLM"],
    }
    assert CLE not in reponse.text


def test_les_budgets_disent_d_ou_vient_leur_chiffre(tmp_path: Path):
    """Décision 6 : la durée annoncée est mesurée, ou marquée comme ne l'étant pas."""
    budgets = serveur(tmp_path).get("/api/v1/systeme/budgets").json()["budgets"]
    par_operation = {b["operation"]: b for b in budgets}
    assert par_operation["sortie"]["source"] == "defaut"
    assert par_operation["sortie"]["attendu_ms"] > 0
    assert par_operation["sortie"]["median_ms"] is None


def test_le_profil_masque_la_cle_et_ne_publie_pas_les_chemins_du_serveur(tmp_path: Path):
    reponse = serveur(tmp_path).get("/api/v1/profil")
    assert reponse.status_code == 200
    profil = reponse.json()["donnees"]
    assert profil["intervals"]["api_key"] == "***"
    assert CLE not in reponse.text
    # Ni le dossier de cache, ni l'URL du serveur BRouter : ce sont des
    # données d'exploitation, pas de cycliste.
    assert "cache" not in profil
    assert "brouter" not in profil
    assert "brouter.exemple.test" not in reponse.text
    assert profil["services"]["brouter"] == {"renseigne": True, "profil": "fastbike"}


def test_le_profil_porte_les_trois_valeurs_de_l_ecran_de_ftp(tmp_path: Path):
    profil = serveur(tmp_path).get("/api/v1/profil").json()["donnees"]
    vitesse = profil["seance"]["vitesse_compteur"]
    assert vitesse["velo"] == "Route"
    assert vitesse["vitesse_a_plat_kmh"] > vitesse["moyenne_compteur_kmh"]
    assert vitesse["facteur_mesure"] is False  # aucun facteur réglé dans la config de test


def test_modifier_le_profil_change_la_ftp_et_deplace_les_zones(tmp_path: Path):
    client = serveur(tmp_path)
    avant = client.get("/api/v1/profil/zones").json()["donnees"]
    reponse = client.patch("/api/v1/profil", json={"cycliste": {"ftp_w": W.FTP_TEST + 20}})
    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["cycliste"]["ftp_w"] == W.FTP_TEST + 20
    apres = client.get("/api/v1/profil/zones").json()["donnees"]
    # Décision 7 : la position n'a pas bougé, tout l'escalier s'est déplacé.
    assert apres["position_zone"] == avant["position_zone"]
    assert apres["zones"][1]["puissance_w"] > avant["zones"][1]["puissance_w"]


def test_une_modification_survit_a_un_redemarrage(tmp_path: Path):
    serveur(tmp_path).patch("/api/v1/profil", json={"cycliste": {"masse_kg": 71.0}})
    # Un deuxième serveur, même dossier : le profil est dans le dépôt, pas en mémoire.
    profil = serveur(tmp_path).get("/api/v1/profil").json()["donnees"]
    assert profil["cycliste"]["masse_kg"] == 71.0


def test_le_toml_du_mainteneur_n_est_jamais_reecrit(tmp_path: Path):
    chemin = ecrire_config(tmp_path)
    avant = chemin.read_text(encoding="utf-8")
    serveur(tmp_path).patch("/api/v1/profil", json={"cycliste": {"ftp_w": 300}})
    assert chemin.read_text(encoding="utf-8") == avant


@pytest.mark.parametrize(
    ("corps", "motif"),
    [
        ({"cache": {"dossier": "/tmp/ailleurs"}}, "cache"),
        ({"brouter": {"url": "https://ailleurs.test"}}, "brouter"),
        ({"cycliste": {"cda_m2": 0.3}}, "cycliste.cda_m2"),
    ],
)
def test_ce_qui_n_est_pas_modifiable_est_refuse_et_nomme(tmp_path: Path, corps: dict, motif: str):
    """Refuser plutôt qu'ignorer : un champ tu, c'est un front qui croit avoir enregistré."""
    reponse = serveur(tmp_path).patch("/api/v1/profil", json=corps)
    assert reponse.status_code == 400
    assert reponse.json()["erreur"]["code"] == "requete_invalide"
    assert motif in reponse.json()["erreur"]["message"]


def test_un_profil_invalide_ne_remplace_pas_le_precedent(tmp_path: Path):
    client = serveur(tmp_path)
    client.patch("/api/v1/profil", json={"cycliste": {"ftp_w": 260}})
    reponse = client.patch("/api/v1/profil", json={"cycliste": {"ftp_w": -10}})
    assert reponse.status_code == 422
    assert reponse.json()["erreur"]["code"] == "profil_invalide"
    assert client.get("/api/v1/profil").json()["donnees"]["cycliste"]["ftp_w"] == 260


def test_la_cle_intervals_s_enregistre_et_ne_ressort_jamais(tmp_path: Path):
    client = serveur(tmp_path)
    reponse = client.patch("/api/v1/profil", json={"intervals": {"api_key": "cle-inventee-1234"}})
    assert reponse.status_code == 200
    assert "cle-inventee-1234" not in reponse.text
    assert reponse.json()["donnees"]["intervals"]["api_key"] == "***"
    assert "cle-inventee-1234" not in client.get("/api/v1/profil").text


# --- l'échelle des zones ------------------------------------------------------


def test_l_echelle_des_zones_donne_les_bornes_et_la_cible(tmp_path: Path):
    donnees = serveur(tmp_path).get("/api/v1/profil/zones").json()["donnees"]
    assert len(donnees["zones"]) == 7
    # Les zones ouvertes (la première et la dernière) n'ont pas de cible :
    # une position n'y veut rien dire.
    assert donnees["zones"][0]["puissance_w"] is None
    assert donnees["zones"][-1]["puissance_w"] is None
    assert donnees["zones"][1]["puissance_w"] == pytest.approx(0.60 * W.FTP_TEST, abs=0.5)


def test_l_apercu_relie_les_trois_valeurs_sans_rien_stocker(tmp_path: Path):
    client = serveur(tmp_path)
    depart = client.get("/api/v1/profil/zones").json()["donnees"]
    vitesse = depart["valeurs_liees"]["vitesse_a_plat_kmh"]

    apercu = client.post("/api/v1/profil/zones/apercu", json={"vitesse_a_plat_kmh": vitesse + 2})
    assert apercu.status_code == 200
    donnees = apercu.json()["donnees"]
    assert donnees["position_zone"] > depart["position_zone"]
    assert donnees["valeurs_liees"]["puissance_endurance_w"] > (
        depart["valeurs_liees"]["puissance_endurance_w"]
    )
    # Rien n'est stocké tant que le front n'a pas envoyé la position.
    assert client.get("/api/v1/profil/zones").json()["donnees"]["position_zone"] == (
        depart["position_zone"]
    )


def test_l_apercu_dit_qu_une_moyenne_compteur_saisie_a_plat_sort_de_la_bande(tmp_path: Path):
    """Décision 8 : la faute se montre, elle ne se corrige pas en silence."""
    client = serveur(tmp_path)
    depart = client.get("/api/v1/profil/zones").json()["donnees"]["valeurs_liees"]
    apercu = client.post(
        "/api/v1/profil/zones/apercu",
        json={"vitesse_a_plat_kmh": depart["moyenne_compteur_kmh"]},
    ).json()["donnees"]
    assert apercu["position_zone"] < 0  # sous la Z2, non écrêté
    assert apercu["hors_bande"] is True


def test_l_apercu_refuse_deux_valeurs_a_la_fois(tmp_path: Path):
    reponse = serveur(tmp_path).post(
        "/api/v1/profil/zones/apercu", json={"puissance_w": 150, "vitesse_a_plat_kmh": 28}
    )
    assert reponse.status_code == 400
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_la_position_apercue_est_celle_qu_on_enregistre(tmp_path: Path):
    """Le geste complet de l'écran : aperçu, puis validation — et c'est la
    **position** qui part, jamais les watts (décision 7)."""
    client = serveur(tmp_path)
    apercu = client.post("/api/v1/profil/zones/apercu", json={"puissance_w": 0.70 * W.FTP_TEST})
    position = apercu.json()["donnees"]["position_zone"]
    client.patch("/api/v1/profil", json={"seance": {"position_zone": position}})
    profil = client.get("/api/v1/profil").json()["donnees"]
    assert profil["seance"]["position_zone"] == pytest.approx(position)
    assert profil["seance"]["puissance_endurance_pct"] == pytest.approx(0.70, abs=1e-4)


# --- géocodage ----------------------------------------------------------------


def test_le_geocodage_rend_toute_la_liste_et_ne_tranche_pas(tmp_path: Path):
    """F0.7, à l'inverse de la ligne de commande : l'API ne choisit pas, elle fait choisir."""
    client = serveur(
        tmp_path,
        ban=geocodeur(
            [
                {"label": "Rue inventée, Villefictive", "score": 0.91, "lat": 0.1, "lon": 0.1},
                {"label": "Rue inventée, Autreville", "score": 0.72, "lat": 0.2, "lon": 0.2},
            ]
        ),
        nominatim=nominatim_muet(),
    )
    charge = client.get("/api/v1/geocodage", params={"adresse": "rue inventée"}).json()
    candidats = charge["donnees"]["candidats"]
    assert len(candidats) == 2
    assert [c["score"] for c in candidats] == [0.91, 0.72]
    assert charge["budget"]["operation"] == "geocodage"


def test_une_adresse_introuvable_rend_une_phrase_et_non_une_liste_vide(tmp_path: Path):
    """Les services ont répondu : ce n'est pas une panne, mais l'écran d'échec
    « adresse introuvable » a besoin d'une phrase à afficher."""
    # La BAN ne rend rien, et le connecteur bascule alors sur Nominatim, qui
    # ne rend rien non plus : c'est le vrai chemin d'une adresse introuvable.
    client = serveur(tmp_path, ban=geocodeur([]), nominatim=nominatim_vide())
    charge = client.get("/api/v1/geocodage", params={"adresse": "zzz"}).json()
    assert charge["donnees"]["candidats"] == []
    assert any("aucune adresse trouvée" in a for a in charge["avertissements"])


def test_un_parametre_hors_bornes_est_nomme_en_francais(tmp_path: Path):
    """Les motifs de Pydantic sont en anglais : ils restent dans `details`, et
    la phrase affichable nomme le champ, en français."""
    reponse = serveur(tmp_path).get("/api/v1/geocodage", params={"adresse": ""})
    assert reponse.status_code == 422
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "requete_invalide"
    assert "requête mal formée" in erreur["message"]
    assert "adresse" in erreur["message"]
    assert "String should have" not in erreur["message"]
    assert erreur["details"]["champs"][0]["motif"], "le motif brut reste, pour le débogage"


# --- météo --------------------------------------------------------------------


def test_la_meteo_rend_la_grille_par_direction(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    charge = client.get("/api/v1/meteo", params={"heure_depart": "09:00"}).json()
    directions = {c["direction"] for c in charge["donnees"]["cellules"]}
    assert len(directions - {"ici"}) == 8
    assert charge["donnees"]["meilleure_direction"]["nom"]
    assert charge["duree_ms"] >= 0
    assert charge["budget"]["source"] in ("mesure", "defaut")


def test_la_meteo_accepte_un_autre_point_pour_cette_requete(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    charge = client.get(
        "/api/v1/meteo", params={"latitude": 0.5, "longitude": 0.5, "nom": "Ailleurs"}
    ).json()
    assert charge["donnees"]["depart"] == {"nom": "Ailleurs", "latitude": 0.5, "longitude": 0.5}


def test_la_meteo_refuse_une_latitude_sans_longitude(tmp_path: Path):
    reponse = serveur(tmp_path, meteo=moteur_meteo()).get("/api/v1/meteo", params={"latitude": 0.5})
    assert reponse.status_code == 400
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_une_panne_meteo_sort_avec_le_service_nomme(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo(en_panne=True))
    reponse = client.get("/api/v1/meteo")
    assert reponse.status_code == 502
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "meteo_indisponible"
    assert erreur["service"] == "openmeteo"
    assert erreur["message"].startswith("Open-Meteo")


# --- séances ------------------------------------------------------------------


def test_la_semaine_rend_un_jour_par_ligne(tmp_path: Path):
    client = serveur(tmp_path, intervals=client_intervals())
    charge = client.get(
        "/api/v1/seances", params={"depuis": "2026-09-07", "jusqua": "2026-09-09"}
    ).json()
    assert len(charge["donnees"]["jours"]) == 3


def test_un_jour_sans_seance_n_est_pas_une_erreur(tmp_path: Path):
    """La ligne de commande sort en 0 ; l'API sort en 200 avec `seance: null`."""
    client = serveur(tmp_path, intervals=client_intervals([]))
    reponse = client.get(f"/api/v1/seances/{JOUR.isoformat()}")
    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["seance"] is None


def test_une_cle_revoquee_ne_passe_pas_pour_une_panne(tmp_path: Path):
    client = serveur(tmp_path, intervals=intervals_refuse())
    reponse = client.get(f"/api/v1/seances/{JOUR.isoformat()}")
    assert reponse.status_code == 502
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "intervals_refuse"
    assert erreur["service"] == "intervals"
    assert CLE not in reponse.text


ZWO = """<workout_file>
  <name>Séance inventée</name>
  <workout>
    <Warmup Duration="600" PowerLow="0.45" PowerHigh="0.60"/>
    <SteadyState Duration="1200" Power="0.75"/>
    <Cooldown Duration="600" PowerLow="0.60" PowerHigh="0.45"/>
  </workout>
</workout_file>
"""


def test_un_zwo_depose_rend_la_seance_et_un_identifiant(tmp_path: Path):
    client = serveur(tmp_path)
    reponse = client.post(
        "/api/v1/seances/fichier",
        files={"fichier": ("seance.zwo", ZWO, "application/xml")},
        params={"jour": JOUR.isoformat()},
    )
    assert reponse.status_code == 200, reponse.text
    charge = reponse.json()
    assert charge["donnees"]["nom"] == "Séance inventée"
    assert charge["donnees"]["etapes"], "les étapes lues dans le fichier"
    assert charge["fichier"]["id"]
    assert "/api/v1/fichiers/" in charge["fichier"]["url"]


def test_le_fit_de_seance_se_refuse_en_le_disant(tmp_path: Path):
    """Décision 5 : « son absence se dit à l'écran plutôt que de se découvrir au dépôt »."""
    reponse = serveur(tmp_path).post(
        "/api/v1/seances/fichier",
        files={"fichier": ("seance.fit", b"\x00\x01", "application/octet-stream")},
    )
    assert reponse.status_code == 422
    assert reponse.json()["erreur"]["code"] == "format_non_lu"
    assert ".ZWO" in reponse.json()["erreur"]["message"]


# --- génération ---------------------------------------------------------------


def test_une_generation_rend_les_propositions_leur_geometrie_et_leur_gpx(tmp_path: Path):
    client = serveur(
        tmp_path,
        brouter=moteur_brouter(),
        meteo=moteur_meteo(),
        intervals=client_intervals(),
    )
    reponse = client.post("/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2})
    assert reponse.status_code == 200, reponse.text
    charge = reponse.json()
    donnees = charge["donnees"]
    assert donnees["propositions"], "au moins une proposition contrastée"
    assert donnees["candidates"][0]["trace"]["points"], "la géométrie est dans le JSON (F0.1)"
    assert donnees["candidates"][0]["placement"]["emplacements"]
    # Un fichier est un identifiant, jamais un chemin de disque.
    assert set(donnees["gpx"]) == {"id", "nom", "url"}
    assert str(tmp_path) not in reponse.text
    assert charge["duree_ms"] > 0
    assert charge["budget"]["operation"] == "sortie"

    gpx = client.get(donnees["gpx"]["url"])
    assert gpx.status_code == 200
    assert gpx.text.lstrip().startswith("<?xml")


def test_la_duree_mesuree_nourrit_le_budget_annonce(tmp_path: Path):
    """Décision 6 : « X doit être mesuré, pas inventé » — et il l'est dès la
    première génération réussie."""
    client = serveur(
        tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(), intervals=client_intervals()
    )
    client.post("/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2})
    budget = next(
        b for b in client.get("/api/v1/systeme/budgets").json()["budgets"] if b["operation"] == "sortie"
    )
    assert budget["source"] == "mesure"
    assert budget["n"] == 1
    assert budget["median_ms"] is not None


def test_une_boucle_libre_rend_sa_geometrie(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "N"})
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["candidates"][0]["trace"]["points"]
    assert donnees["gpx"]["url"].startswith("/api/v1/fichiers/")


def test_la_generation_part_du_point_que_le_front_a_choisi(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    reponse = client.post(
        "/api/v1/boucles",
        json={
            "distance_km": 30.0,
            "direction": "N",
            "depart": {"latitude": 0.3, "longitude": 0.4, "nom": "Ailleurs"},
        },
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["donnees"]["depart"]["nom"] == "Ailleurs"


def moteur_non_borne() -> ClientBrouter:
    """Un moteur qui répond, mais avec un tracé qui ne revient pas au départ.

    Ce n'est pas une panne — c'est le cas « aucune boucle trouvée », qui a son
    écran dans les maquettes et ne doit pas être présenté comme un service en
    rade.
    """
    points = [(0.0 + 0.001 * i, 0.0, 40.0) for i in range(120)]

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(200, json=reponse_anneau(points))

    params = depuis_dict(
        {
            "depart": {"nom": "x", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 70, "ftp_w": 200},
            "brouter": {"url": "https://brouter.exemple.test", "timeout_s": 5.0},
        }
    ).brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def test_aucune_boucle_trouvee_n_est_pas_une_panne_de_service(tmp_path: Path):
    """BRouter a répondu ; simplement, rien de ce qu'il rend n'est une boucle."""
    client = serveur(tmp_path, brouter=moteur_non_borne(), meteo=moteur_meteo())
    reponse = client.post("/api/v1/boucles", json={"distance_km": 60.0, "direction": "N"})
    assert reponse.status_code == 422
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "aucune_boucle"
    assert erreur["service"] is None


def test_une_seance_qui_ne_tient_sur_aucune_boucle_a_le_meme_code(tmp_path: Path):
    """L'autre chemin vers le même écran : les boucles existent, la séance n'y entre pas."""
    client = serveur(
        tmp_path,
        brouter=moteur_brouter({float(a): {"rayon_deg": 0.002} for a in range(0, 360, 5)}),
        meteo=moteur_meteo(),
        intervals=client_intervals(),
    )
    reponse = client.post(
        "/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2, "distance_km": 5.0}
    )
    assert reponse.status_code == 422, reponse.text
    assert reponse.json()["erreur"]["code"] == "aucune_boucle"


def test_brouter_injoignable_a_son_code_et_son_service(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_muet(), meteo=moteur_meteo())
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "N"})
    assert reponse.status_code == 502
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "brouter_indisponible"
    assert erreur["service"] == "brouter"


def test_une_meteo_tombee_ne_fait_pas_tomber_la_boucle(tmp_path: Path):
    """« La météo est le seul maillon qu'on accepte de perdre » — et l'API le dit
    dans `avertissements`, là où la ligne de commande l'écrit sur stderr."""
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(en_panne=True))
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "N"})
    assert reponse.status_code == 200, reponse.text
    charge = reponse.json()
    assert charge["donnees"]["candidates"][0]["meteo"] is None
    assert any("météo indisponible" in a for a in charge["avertissements"])
    assert not any(a.startswith("ourouler : ") for a in charge["avertissements"])


def test_une_direction_illisible_est_une_faute_de_requete(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "nord-est"})
    assert reponse.status_code == 400
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_un_corps_mal_forme_sort_dans_la_forme_d_erreur_du_projet(tmp_path: Path):
    reponse = serveur(tmp_path).post("/api/v1/boucles", json={"distance_km": -3, "direction": "N"})
    assert reponse.status_code == 422
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "requete_invalide"
    assert erreur["details"]["champs"][0]["champ"].endswith("distance_km")


# --- les routes de lecture qui restent, une par sous-commande ------------------


def test_l_inventaire_repond_sur_un_cache_vide(tmp_path: Path):
    """Aucune sortie indexée n'est une réponse, pas une panne — et
    `--synchroniser` n'est pas exposé : il écrit dans le cache du serveur."""
    charge = serveur(tmp_path).get("/api/v1/inventaire").json()
    assert charge["donnees"]["total"] == 0
    assert charge["donnees"]["par_velo"] == []


def test_les_statistiques_de_routes_se_lisent(tmp_path: Path):
    reponse = serveur(tmp_path, brouter=moteur_brouter()).get("/api/v1/routes/stats")
    assert reponse.status_code == 200, reponse.text
    assert isinstance(reponse.json()["donnees"], dict)


def test_les_poids_sans_rien_d_appris_le_disent_en_francais(tmp_path: Path):
    """Un serveur neuf n'a rien appris : ce n'est pas une panne, c'est une
    consigne — et elle sort dans la forme d'erreur du projet."""
    reponse = serveur(tmp_path, brouter=moteur_brouter()).get("/api/v1/routes/poids")
    assert reponse.status_code == 400
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "requete_invalide"
    assert "aucune route apprise" in erreur["message"]


def test_apprendre_n_est_pas_exposee(tmp_path: Path):
    """Elle rejoue des mois de sorties dans BRouter : c'est une commande
    d'administration, pas un bouton."""
    reponse = serveur(tmp_path).get("/api/v1/routes/apprendre")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_une_simulation_part_d_un_gpx_du_depot(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    boucle = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "N"})
    identifiant = boucle.json()["donnees"]["gpx"]["id"]
    reponse = client.post(
        "/api/v1/simulations", json={"gpx": identifiant, "puissance_w": 150.0}
    )
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["temps_mouvement_s"] > 0
    assert donnees["vitesse_moy_kmh"] > 0


def test_une_simulation_sur_le_gpx_d_un_autre_est_introuvable(tmp_path: Path):
    a_lui = DepotFichiers(tmp_path / "cache" / "api").deposer(AUTRE, "a-lui.gpx", b"<gpx/>")
    reponse = serveur(tmp_path).post(
        "/api/v1/simulations", json={"gpx": a_lui.identifiant, "puissance_w": 150.0}
    )
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"


# --- fichiers et isolation ----------------------------------------------------


@pytest.mark.parametrize(
    ("propose", "attendu"),
    [
        ('../../etc/"passwd".gpx', "_passwd_.gpx"),
        ("seance\r\nX-Injecte: oui.zwo", "seance__X-Injecte_ oui.zwo"),
        ("/tmp/secret.gpx", "secret.gpx"),
        ("...gpx", "gpx"),
    ],
)
def test_un_nom_de_fichier_ne_peut_pas_couper_un_entete(propose: str, attendu: str):
    """Le nom d'affichage ressort dans `Content-Disposition` : il vient du front,
    donc de n'importe où, et un guillemet ou un retour chariot y casserait
    l'en-tête."""
    assert nom_sur(propose) == attendu


def test_un_nom_assaini_est_celui_que_le_telechargement_porte(tmp_path: Path):
    client = serveur(tmp_path)
    reponse = client.post(
        "/api/v1/seances/fichier",
        files={"fichier": ('../se"ance.zwo', ZWO, "application/xml")},
        params={"jour": JOUR.isoformat()},
    )
    assert reponse.status_code == 200, reponse.text
    identifiant = reponse.json()["fichier"]["id"]
    entete = client.get(f"/api/v1/fichiers/{identifiant}").headers["content-disposition"]
    assert '"' not in entete.replace('filename="', "").rstrip('"')
    assert "\n" not in entete


def test_le_fichier_d_un_autre_proprietaire_est_introuvable(tmp_path: Path):
    """Doctrine §10.2 : l'isolation est vérifiée côté serveur, à chaque requête."""
    depot = DepotFichiers(tmp_path / "cache" / "api")
    a_lui = depot.deposer(AUTRE, "secret.gpx", b"<gpx/>")
    reponse = serveur(tmp_path).get(f"/api/v1/fichiers/{a_lui.identifiant}")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"


@pytest.mark.parametrize("identifiant", ["0" * 31, "nimportequoi", "profil", "0" * 33])
def test_un_identifiant_de_fichier_mal_forme_est_refuse_avant_tout_chemin(
    tmp_path: Path, identifiant: str
):
    reponse = serveur(tmp_path).get(f"/api/v1/fichiers/{identifiant}")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"


@pytest.mark.parametrize("chemin", ["../../../etc/passwd", "..%2F..%2Fconfig.toml", "../profil.json"])
def test_une_traversee_de_chemin_ne_sert_jamais_de_fichier(tmp_path: Path, chemin: str):
    """Ni 200, ni contenu : soit la route n'existe pas, soit l'identifiant est refusé."""
    reponse = serveur(tmp_path).get(f"/api/v1/fichiers/{chemin}")
    assert reponse.status_code in (404, 405)
    assert "root:" not in reponse.text
    assert "api_key" not in reponse.text


def _socle_partage(tmp_path: Path) -> SocleTOML:
    """Un socle déclaré **impersonnel** : un TOML qui n'est le profil de personne.

    C'est ce qui permet à deux propriétaires de le partager. Le service, lui,
    déclare le TOML du mainteneur comme étant le sien (`proprietaire=
    PROPRIETAIRE_LOCAL`), et le dépôt refuse alors de le servir à un autre —
    voir le test de la fuite ci-dessous.
    """
    return SocleTOML(ecrire_config(tmp_path), proprietaire=None)


def test_les_profils_de_deux_proprietaires_ne_se_melangent_pas(tmp_path: Path):
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    depot.enregistrer(AUTRE, {"cycliste": {"ftp_w": 999}})
    assert depot.config(AUTRE).cycliste.ftp_w == 999
    assert depot.config(PROPRIETAIRE_LOCAL).cycliste.ftp_w == W.FTP_TEST


def test_le_socle_personnel_du_mainteneur_ne_se_sert_pas_a_un_autre(tmp_path: Path):
    """La fuite trouvée en relecture de F1, fermée le 17/09/2026.

    Le test précédent vérifiait que le champ **surchargé** diffère d'un
    propriétaire à l'autre, et en concluait que les profils ne se mélangent
    pas. Il manquait la moitié de la question : tout ce qu'un propriétaire ne
    surcharge **pas**, il l'héritait du socle — donc `[intervals] api_key`,
    `athlete_id` et `[depart]`, c'est-à-dire la clé et le domicile du
    mainteneur. Le socle du service est désormais déclaré comme étant le sien,
    et le dépôt refuse de le servir à quelqu'un d'autre plutôt que de décider
    tout seul quelles sections sont communes — cet arbitrage est au mainteneur
    (`docs/questions_mainteneur.md`).
    """
    depot = DepotProfils(
        SocleTOML(ecrire_config(tmp_path), proprietaire=PROPRIETAIRE_LOCAL),
        tmp_path / "cache" / "api",
    )
    assert depot.config(PROPRIETAIRE_LOCAL).intervals.renseigne, "le mainteneur n'est plus servi"
    with pytest.raises(ErreurConfig) as refus:
        depot.config(AUTRE)
    assert "ne se partage pas" in str(refus.value)
    with pytest.raises(ErreurConfig):
        depot.enregistrer(AUTRE, {"cycliste": {"ftp_w": 999}})


def test_chaque_profil_est_ecrit_pour_son_seul_proprietaire(tmp_path: Path):
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    depot.enregistrer(AUTRE, {"cycliste": {"ftp_w": 999}})
    ecrit = json.loads((tmp_path / "cache" / "api" / AUTRE.identifiant / "profil.json").read_text())
    assert ecrit == {"cycliste": {"ftp_w": 999}}
    assert not (tmp_path / "cache" / "api" / PROPRIETAIRE_LOCAL.identifiant / "profil.json").exists()


def test_le_profil_qui_porte_une_cle_n_est_lisible_que_de_son_proprietaire(tmp_path: Path):
    """Pas de chiffrement au repos avant F3 ; les droits du fichier, eux, se posent."""
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    depot.enregistrer(PROPRIETAIRE_LOCAL, {"intervals": {"api_key": "cle-inventee-9876"}})
    chemin = tmp_path / "cache" / "api" / PROPRIETAIRE_LOCAL.identifiant / "profil.json"
    assert chemin.stat().st_mode & 0o077 == 0

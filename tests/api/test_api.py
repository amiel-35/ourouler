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

import httpx
import pytest
from fastapi.testclient import TestClient
from test_seance_intervals import ATHLETE, CLE, W
from test_sortie_commande import (
    JOUR,
    client_intervals,
    ecrire_calibration,
    moteur_brouter,
    moteur_meteo,
    pluie_au_nord,
    reponse_anneau,
)

from ourouler.api.adaptateur import Budgets
from ourouler.api.application import creer_application
from ourouler.api.depots import (
    CHAMPS_MODIFIABLES,
    CHAMPS_RACINE_MODIFIABLES,
    LISTES_MODIFIABLES,
    DepotFichiers,
    DepotProfils,
    SocleTOML,
    nom_sur,
)
from ourouler.api.erreurs import CODES_PANNE
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.api.routes.commun import Clients
from ourouler.config import depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.geocodage import ClientBAN, ClientNominatim
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.noyau.erreurs import ErreurConfig, ErreurUtilisateur

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


def test_le_profil_expose_prenom_et_nom_vides_pour_une_config_anterieure(tmp_path: Path):
    """`CONFIG_TOML` ne porte ni prénom ni nom (elle date d'avant le lot) : le
    profil continue de se servir, avec des chaînes vides — pas une panne, pas
    un champ manquant."""
    profil = serveur(tmp_path).get("/api/v1/profil").json()["donnees"]
    assert profil["cycliste"]["prenom"] == ""
    assert profil["cycliste"]["nom"] == ""


def test_modifier_le_profil_enregistre_prenom_et_nom(tmp_path: Path):
    client = serveur(tmp_path)
    reponse = client.patch("/api/v1/profil", json={"cycliste": {"prenom": "Camille", "nom": "Ruiz"}})
    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["cycliste"]["prenom"] == "Camille"
    assert reponse.json()["donnees"]["cycliste"]["nom"] == "Ruiz"
    # Une modification indépendante (ex. la FTP) ne perd pas l'identité déjà
    # enregistrée, et ne l'exige pas non plus : l'obligation est côté
    # assistant, pas une contrainte de chaque écriture.
    client.patch("/api/v1/profil", json={"cycliste": {"ftp_w": W.FTP_TEST + 5}})
    profil = client.get("/api/v1/profil").json()["donnees"]
    assert profil["cycliste"]["prenom"] == "Camille"
    assert profil["cycliste"]["ftp_w"] == W.FTP_TEST + 5


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


def test_un_poids_hors_bornes_rend_un_message_lisible_a_l_ecran(tmp_path: Path):
    """Constaté en vrai le 25/09/2026 : l'assistant affichait « [cycliste]
    masse_kg = 7075.0 hors de [20, 300] » tel quel. L'API rend maintenant une
    phrase française, et `details.champ` pour l'afficher près du champ."""
    reponse = serveur(tmp_path).patch("/api/v1/profil", json={"cycliste": {"masse_kg": 7075.0}})
    assert reponse.status_code == 422
    erreur = reponse.json()["erreur"]
    assert erreur["message"] == "Votre poids doit être entre 20 et 300 kg."
    assert erreur["details"] == {"champ": "masse_kg"}


def test_la_cle_intervals_s_enregistre_et_ne_ressort_jamais(tmp_path: Path):
    """Correctif de prod du 25/09/2026 : une clé seule (sans `athlete_id`,
    comme l'envoient l'assistant et Réglages) déclenche sa résolution auprès
    d'Intervals.icu (`GET /athlete/0`) — bouchonnée ici, jamais de réseau."""

    def resoudre(requete: httpx.Request) -> httpx.Response:
        del requete
        return httpx.Response(200, json={"id": ATHLETE})

    client = serveur(tmp_path, intervals=httpx.Client(transport=httpx.MockTransport(resoudre)))
    reponse = client.patch("/api/v1/profil", json={"intervals": {"api_key": "cle-inventee-1234"}})
    assert reponse.status_code == 200, reponse.text
    assert "cle-inventee-1234" not in reponse.text
    assert reponse.json()["donnees"]["intervals"]["api_key"] == "***"
    assert reponse.json()["donnees"]["intervals"]["athlete_id"] == ATHLETE
    assert reponse.json()["donnees"]["services"]["intervals"]["renseigne"] is True
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
    # La phrase reste — un écran d'échec en a besoin — mais c'est le **code**
    # qui dit de quoi il s'agit (relecture F2 · B3).
    assert any(a["code"] == "adresse_introuvable" for a in charge["avertissements"])
    assert any("aucune adresse trouvée" in a["message"] for a in charge["avertissements"])


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
    # Q40 (g) : aucun GPX n'est écrit à la génération — le champ du cœur reste
    # nul — et **chaque** proposition porte l'adresse de sa propre trace.
    assert donnees["gpx"] is None, "aucun GPX écrit à la génération"
    assert donnees["generation"], "la génération est nommée, pour demander ses GPX ensuite"
    assert str(tmp_path) not in reponse.text
    assert charge["duree_ms"] > 0
    assert charge["budget"]["operation"] == "sortie"

    # Une carte, elle, reste un fichier : un identifiant, jamais un chemin.
    assert set(donnees["carte"]) == {"id", "nom", "url"}

    for proposition in donnees["propositions"]:
        gpx = client.get(proposition["gpx"]["url"])
        assert gpx.status_code == 200, proposition["gpx"]["url"]
        assert gpx.text.lstrip().startswith("<?xml")
        assert proposition["gpx"]["nom"].endswith(f"_n{proposition['numero']}.gpx")


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


def test_une_boucle_libre_sans_direction_balaie_l_horizon(tmp_path: Path):
    """Q47 : `direction` est désormais facultative, comme côté `POST /sorties`.

    Le bouton « Chercher » du front n'a plus de raison d'être grisé en
    Endurance Z2 faute de direction choisie — c'est ce que cette route doit
    permettre.
    """
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "candidates": 3})
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["demande"]["direction"] is None
    assert donnees["demande"]["azimut_deg"] is None
    azimuts = sorted(c["azimut_deg"] for c in donnees["candidates"])
    assert len(azimuts) == 3
    assert azimuts == pytest.approx([0.0, 120.0, 240.0])


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
    # **Le code, pas la phrase.** Le front dessine son bandeau « Pas de météo »
    # là-dessus : tant que l'avertissement n'était qu'une chaîne, il le
    # décidait à l'expression régulière, et une reformulation l'effaçait en
    # silence (relecture F2 · B3).
    assert any(a["code"] == "meteo_indisponible" for a in charge["avertissements"])
    assert any("météo indisponible" in a["message"] for a in charge["avertissements"])
    assert not any(a["message"].startswith("ourouler : ") for a in charge["avertissements"])


def test_un_avertissement_porte_toujours_un_code_et_un_message(tmp_path: Path):
    """La forme de `avertissements` est un contrat, comme celle de `erreur`.

    Un front qui reçoit une liste hétérogène — des chaînes ici, des objets
    là — retombe sur le reniflage de type, puis sur le reniflage de phrase.
    Toute route de calcul rend donc la même forme, y compris quand il n'y a
    rien à dire (liste vide).
    """
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(en_panne=True))
    reponse = client.post("/api/v1/boucles", json={"distance_km": 30.0, "direction": "N"})
    avertissements = reponse.json()["avertissements"]
    assert avertissements, "la météo est tombée : il devrait y avoir un avertissement"
    for a in avertissements:
        assert set(a) == {"code", "message"}, a
        assert isinstance(a["code"], str) and a["code"]
        assert isinstance(a["message"], str) and a["message"]


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


# --- un parcours déjà en main, à analyser (L9.8) -------------------------------


def _gpx_parcours(longueur_m: float = 30_000.0, nom: str = "Imposé du club") -> bytes:
    from ourouler.boucle.gpx import ecrire_gpx
    from ourouler.noyau.trace import PointTrace, Trace

    metre_en_degre = 1.0 / 111_194.93
    points = [
        PointTrace(lat=0.0, lon=d * metre_en_degre, alt_m=100.0, dist_m=float(d))
        for d in range(0, int(longueur_m) + 1, 500)
    ]
    trace = Trace(nom, points, [], longueur_m, 0.0, None)
    return ecrire_gpx(trace, nom).encode("utf-8")


def test_deposer_puis_analyser_un_parcours(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    depot = client.post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("brm200.gpx", _gpx_parcours(), "application/gpx+xml")},
    )
    assert depot.status_code == 200, depot.text
    charge = depot.json()
    assert charge["apercu"]["distance_km"] == pytest.approx(30.0, rel=0.01)
    identifiant = charge["fichier"]["id"]

    reponse = client.post(
        "/api/v1/parcours/analyser",
        json={"gpx": identifiant, "heure_depart": "2026-09-08T08:00"},
    )
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    # La fourchette porte à porte (L9.1), jamais un seul chiffre.
    assert donnees["temps_ecoule_bas_s"] <= donnees["temps_ecoule_s"] <= donnees["temps_ecoule_haut_s"]
    assert donnees["heure_arrivee_bas"] <= donnees["heure_arrivee"] <= donnees["heure_arrivee_haut"]
    # La puissance par défaut est celle de l'endurance du profil : ni nulle,
    # ni celle, arbitraire, d'un autre test.
    assert donnees["puissance_w"] > 0
    # La météo par tronçon, dans la forme d'une candidate de boucle (F0.1).
    assert donnees["meteo"] is not None
    assert isinstance(donnees["meteo"]["fleches_vent"], list)
    assert len(donnees["trace"]["points"]) > 0


def test_analyser_refuse_un_fichier_qui_n_est_pas_un_gpx(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    reponse = client.post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("seance.zwo", b"<workout_file/>", "application/xml")},
    )
    assert reponse.status_code == 422
    assert reponse.json()["erreur"]["code"] == "format_non_lu"


def test_analyser_refuse_un_parcours_trop_long_des_le_depot(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    reponse = client.post(
        "/api/v1/parcours/fichier",
        files={
            "fichier": (
                "flèche.gpx",
                _gpx_parcours(longueur_m=1_100_000.0),
                "application/gpx+xml",
            )
        },
    )
    assert reponse.status_code == 422
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_analyser_sans_heure_depart_est_une_faute_de_requete(tmp_path: Path):
    client = serveur(tmp_path, meteo=moteur_meteo())
    depot = client.post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("boucle.gpx", _gpx_parcours(), "application/gpx+xml")},
    )
    identifiant = depot.json()["fichier"]["id"]
    reponse = client.post("/api/v1/parcours/analyser", json={"gpx": identifiant})
    assert reponse.status_code == 422
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


def test_analyser_sur_le_gpx_d_un_autre_est_introuvable(tmp_path: Path):
    a_lui = DepotFichiers(tmp_path / "cache" / "api").deposer(AUTRE, "a-lui.gpx", b"<gpx/>")
    reponse = serveur(tmp_path).post(
        "/api/v1/parcours/analyser",
        json={"gpx": a_lui.identifiant, "heure_depart": "2026-09-08T08:00"},
    )
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"


@pytest.mark.parametrize(
    ("cas", "points"),
    [
        ("un seul point", '<trkpt lat="45" lon="5"/>'),
        ("latitude hors du globe", '<trkpt lat="91" lon="5"/><trkpt lat="91.01" lon="5"/>'),
        ("longitude infinie", '<trkpt lat="45" lon="5"/><trkpt lat="45" lon="inf"/>'),
        ("latitude nan", '<trkpt lat="nan" lon="5"/><trkpt lat="45" lon="5"/>'),
    ],
)
def test_un_gpx_impossible_est_refuse_lisiblement_au_depot(tmp_path: Path, cas: str, points: str):
    """Relecture de L9.8 : « inf » rendait un 500 au dépôt, « nan » un 500 à
    l'analyse, un seul point passait le dépôt pour échouer à l'analyse."""
    del cas
    gpx = f"<gpx><trk><trkseg>{points}</trkseg></trk></gpx>".encode()
    client = serveur(tmp_path, meteo=moteur_meteo())
    reponse = client.post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("imposé.gpx", gpx, "application/gpx+xml")},
    )
    assert reponse.status_code == 422, reponse.text
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "fichier_illisible"
    # Le nom du fichier du cycliste, jamais le chemin du serveur.
    assert "imposé.gpx" in erreur["message"]
    assert str(tmp_path) not in erreur["message"]


def test_un_depot_de_parcours_en_flux_sans_longueur_est_coupe_a_la_borne(tmp_path: Path):
    """Relecture de L9.8 : la route manquait à `BORNES_CORPS` — un envoi sans
    `Content-Length` s'écrivait en entier avant d'être compté."""
    from ourouler.api.routes.commun import TAILLE_MAX_PARCOURS

    frontiere = "xyz"
    entete = (
        f"--{frontiere}\r\nContent-Disposition: form-data; name=\"fichier\"; "
        'filename="gros.gpx"\r\nContent-Type: application/gpx+xml\r\n\r\n'
    ).encode()

    def morceaux():
        yield entete
        for _ in range(TAILLE_MAX_PARCOURS // 1_000_000 + 2):
            yield b"<" * 1_000_000

    reponse = serveur(tmp_path).post(
        "/api/v1/parcours/fichier",
        content=morceaux(),
        headers={"content-type": f"multipart/form-data; boundary={frontiere}"},
    )
    assert reponse.status_code == 413, reponse.text
    assert reponse.json()["erreur"]["code"] == "fichier_trop_gros"


def test_un_parcours_en_deux_segments_disjoints_le_dit_des_le_depot(tmp_path: Path):
    """Deux segments d'une même trace, 5 km d'écart : enchaînés, et le trou est dit."""
    km = 1.0 / 111.19493

    def seg(debut_km: int, fin_km: int) -> str:
        points = [f'<trkpt lat="0" lon="{d * km:.7f}"/>' for d in range(debut_km, fin_km + 1)]
        return "<trkseg>" + "".join(points) + "</trkseg>"

    gpx = f"<gpx><trk><name>BRM</name>{seg(0, 10)}{seg(15, 30)}</trk></gpx>".encode()
    reponse = serveur(tmp_path).post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("brm.gpx", gpx, "application/gpx+xml")},
    )
    assert reponse.status_code == 200, reponse.text
    apercu = reponse.json()["apercu"]
    assert apercu["distance_km"] == pytest.approx(30.0, rel=0.01)
    assert apercu["avertissements"] == [
        "2 morceaux enchaînés, dans l'ordre du fichier",
        "un trou de 5 km entre la trace 1 (segment 1) et la trace 1 (segment 2), compté "
        "en ligne droite dans la distance et la durée",
    ]


def test_un_parcours_d_une_seule_trace_n_avertit_de_rien(tmp_path: Path):
    reponse = serveur(tmp_path).post(
        "/api/v1/parcours/fichier",
        files={"fichier": ("club.gpx", _gpx_parcours(), "application/gpx+xml")},
    )
    assert reponse.json()["apercu"]["avertissements"] == []


#: Le quota de `POST /parcours/analyser` (mode hébergé) est testé à part,
#: dans `test_api_quotas.py` — c'est là que vivent les autres tests de
#: `quotas_meteo`, et le serveur de ce module tourne en mode personnel, où
#: `_verifier_quota` ne fait rien (voir sa docstring).


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
    """Depuis Q35 (tiers 3, tranché le 17/09/2026), écrire son profil veut dire l'écrire **en entier** :
    `depart`/`cycliste` ne s'héritent plus du socle partagé, y compris pour
    le propriétaire qui n'a rien écrit du tout — voir le test suivant.
    """
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    depot.enregistrer(
        AUTRE,
        {
            "depart": {"nom": "Chez l'autre", "latitude": 3.0, "longitude": 4.0},
            "cycliste": {"masse_kg": 60.0, "ftp_w": 999},
        },
    )
    assert depot.config(AUTRE).cycliste.ftp_w == 999
    assert depot.config(AUTRE).cycliste.masse_kg == 60.0
    assert depot.config(AUTRE).depart.nom == "Chez l'autre"


def test_un_proprietaire_qui_n_a_rien_ecrit_n_herite_pas_du_socle_partage(tmp_path: Path):
    """**Le trou précis, fermé le 21/09/2026** — voir aussi `test_api_isolation_proprietaire.py`.

    Le socle partagé du test ci-dessus (`ecrire_config`) porte pourtant un
    départ, un cycliste (masse, FTP `W.FTP_TEST`) et des vélos bien formés :
    c'est le TOML d'un profil personnel ordinaire, réutilisé tel quel pour
    prouver que même un contenu personnel complet ne fuit plus vers un
    propriétaire qui n'a rien surchargé — ni le point de départ, ni la masse,
    ni la FTP du mainteneur.

    **Ce que ça rend au lieu de lever, depuis le 22/09/2026**
    (`DepotProfils.config_ou_comblee` — voir `SocleTOML.config_ou_comblee`,
    `docs/journal/questions/questions_mainteneur.md` Q66) : un profil incomplet lève encore
    *tant que rien ne peut se construire du tout*, mais un compte hébergé
    tout juste activé doit rester lisible avant sa première écriture — c'est
    ce qu'`Assistant.tsx`/`App.tsx` supposent au démarrage. `AUTRE` reçoit
    donc le comblement neutre (`COMBLEMENT_EMBARQUEMENT`), le même pour tout
    le monde — jamais le départ ni le cycliste du mainteneur.
    """
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    config = depot.config(AUTRE)
    assert (config.depart.latitude, config.depart.longitude) == (0.0, 0.0)
    assert config.cycliste.masse_kg == 70.0
    assert config.cycliste.ftp_w is None, "AUTRE hérite la FTP du mainteneur au lieu de rien avoir"


def test_le_socle_partage_ignore_les_variables_ouroler_depart_pour_les_deux_proprietaires(
    tmp_path: Path,
):
    """**Le trou précis du 21/09/2026**, fermé ici — voir aussi la sonde rejouée sur l'ancien code.

    Ce qu'aucun test n'éprouvait avant cette date, malgré 4830 tests verts
    (relecture du sprint 8) : un `SocleTOML` construit avec `variables=` **et**
    plusieurs propriétaires en même temps. Ça reproduit le paquetage réel
    (`deploiement/api/README.md`) : le TOML du serveur porte un départ (« Point
    zéro », `ecrire_config`), et les trois variables `OUROULER_DEPART_*` sont
    posées — comme le fait le déploiement Coolify en service aujourd'hui
    (`OUROULER_DEPART_NOM=Rennes`, un point générique ; celui du test est
    inventé et synthétique, règle absolue 1).

    Deux propriétaires distincts d'un même socle hébergé : `AUTRE` écrit son
    propre départ, `tiers` n'écrit rien du tout. Aucun des deux ne doit
    jamais recevoir un `Depart` qu'il n'a pas lui-même écrit — ni celui du
    TOML serveur, ni celui de la variable d'environnement, ni celui de
    l'autre propriétaire.
    """
    tiers = Proprietaire("tierce-personne")
    variables_serveur = {
        # Nom générique et coordonnée synthétique (règle absolue 1, à plus de
        # 50 km de toute ville française) : le point d'un déploiement réel,
        # sans en être un.
        "OUROULER_DEPART_NOM": "Commune générique",
        "OUROULER_DEPART_LATITUDE": "0.0009",
        "OUROULER_DEPART_LONGITUDE": "0.0004",
    }
    socle = SocleTOML(ecrire_config(tmp_path), variables=variables_serveur, proprietaire=None)
    depot = DepotProfils(socle, tmp_path / "cache" / "api")

    depot.enregistrer(
        AUTRE,
        {
            "depart": {"nom": "Chez AUTRE", "latitude": 10.0, "longitude": 11.0},
            "cycliste": {"masse_kg": 60.0},
        },
    )

    # AUTRE reçoit exactement SON départ — ni celui du TOML serveur
    # (« Point zéro »), ni celui de la variable d'environnement
    # (« Commune générique »).
    depart_autre = depot.config(AUTRE).depart
    assert depart_autre.nom == "Chez AUTRE"
    assert depart_autre.latitude == 10.0
    assert depart_autre.longitude == 11.0

    # `tiers` n'a rien écrit : ni le TOML, ni la variable, ni le départ
    # d'AUTRE ne lui parviennent — seulement le comblement neutre, le même
    # pour n'importe quel compte tout juste activé (`config_ou_comblee`,
    # Q66). C'est cette neutralité qui distingue le comblement de la fuite
    # fermée par ce lot : (0, 0) n'est le domicile de personne, « Rennes »
    # ou « Chez AUTRE » l'auraient été.
    depart_tiers = depot.config(tiers).depart
    assert (depart_tiers.latitude, depart_tiers.longitude) == (0.0, 0.0)
    assert depart_tiers.nom not in {"Point zéro", "Commune générique", "Chez AUTRE"}


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
    (`docs/journal/questions/questions_mainteneur.md`).
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
    profil = {
        "depart": {"nom": "Chez l'autre", "latitude": 3.0, "longitude": 4.0},
        "cycliste": {"masse_kg": 60.0, "ftp_w": 999},
    }
    depot.enregistrer(AUTRE, profil)
    ecrit = json.loads((tmp_path / "cache" / "api" / AUTRE.identifiant / "profil.json").read_text())
    assert ecrit == profil
    assert not (tmp_path / "cache" / "api" / PROPRIETAIRE_LOCAL.identifiant / "profil.json").exists()


def test_le_profil_qui_porte_une_cle_n_est_lisible_que_de_son_proprietaire(tmp_path: Path):
    """Pas de chiffrement au repos avant F3 ; les droits du fichier, eux, se posent."""
    depot = DepotProfils(_socle_partage(tmp_path), tmp_path / "cache" / "api")
    depot.enregistrer(
        PROPRIETAIRE_LOCAL,
        {
            "depart": {"nom": "Chez le mainteneur", "latitude": 5.0, "longitude": 6.0},
            "cycliste": {"masse_kg": 70.0},
            "intervals": {"api_key": "cle-inventee-9876"},
        },
    )
    chemin = tmp_path / "cache" / "api" / PROPRIETAIRE_LOCAL.identifiant / "profil.json"
    assert chemin.stat().st_mode & 0o077 == 0


def test_le_socle_se_decoupe_en_trois_tiers_section_par_section_q35(tmp_path: Path):
    """Q35 (17/09/2026, « trois tiers, et jamais de profil incomplet »), section par section.

    Avant ce lot, `CHAMPS_MODIFIABLES` ne couvrait ni `boucle`, ni
    `evitements`, ni `historique_depuis` — trois des sections « perso » ou
    « perso à défaut serveur » de Q35 — et rien ne vérifiait que `calibration`
    (tiers serveur, malgré son nom) reste bien hors de portée d'un cycliste.
    Ce test remplace l'absence de couverture, pas un ancien test tout-ou-rien
    (celui-là existe déjà : `test_les_profils_de_deux_proprietaires_ne_se_melangent_pas`
    et `test_le_socle_personnel_du_mainteneur_ne_se_sert_pas_a_un_autre`, qui
    protègent un invariant différent — l'appartenance d'un *socle TOML entier*
    — inchangé par ce lot).

    Le socle est déclaré **impersonnel** (`_socle_partage`, comme les tests
    voisins) : ça isole la mécanique de fusion section par section de la
    question, distincte, de qui a le droit de lire le socle de qui.
    """
    chemin = tmp_path / "config.toml"
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        f"""
historique_depuis = "2022-06-01"

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

[meteo]
directions = 8
distances_km = [15]
modele = "modele_principal_test"

[brouter]
url = "https://brouter.exemple.test"

[boucle]
sens = "horaire"
candidates = 9
tolerance_distance = 0.2

[calibration]
mots_groupe = ["club"]
vitesse_min_kmh = 10.0

[cache]
dossier = "{cache}"
""",
        encoding="utf-8",
    )
    depot = DepotProfils(SocleTOML(chemin, proprietaire=None), tmp_path / "cache" / "api")

    depot.enregistrer(
        AUTRE,
        {
            "boucle": {"sens": "antihoraire"},
            "historique_depuis": "2024-01-01",
            "depart": {"nom": "Chez l'autre", "latitude": 1.0, "longitude": 1.0},
            "evitements": [
                {"nom": "carrefour test", "latitude": 1.0, "longitude": 1.0, "rayon_m": 150}
            ],
        },
    )
    autre = depot.config(AUTRE)
    local = depot.config(PROPRIETAIRE_LOCAL)

    # Tiers 2 (« perso, défaut serveur »), champ par champ : le sens choisi
    # par AUTRE ne déteint pas sur les deux champs de service de la même
    # section, qui restent ceux du socle pour tout le monde — y compris pour
    # AUTRE, qui ne les a pas surchargés.
    assert autre.boucle.sens == "antihoraire"
    assert autre.boucle.candidates == 9
    assert autre.boucle.tolerance_distance == 0.2
    assert local.boucle.sens == "horaire"
    assert local.boucle.candidates == 9

    # Tiers 1 (« serveur, jamais servi ») : `calibration` trompe par son nom
    # (Q35) — c'est un réglage de méthode, pas un résultat personnel — et
    # reste refusé en écriture, même si le champ existe côté cœur.
    with pytest.raises(ErreurUtilisateur, match="calibration"):
        depot.enregistrer(AUTRE, {"calibration": {"vitesse_min_kmh": 3.0}})
    assert autre.calibration.vitesse_min_kmh == 10.0

    # Un champ de service d'une section à défaut commun reste refusé même si
    # un autre champ de la même section, lui, est modifiable.
    with pytest.raises(ErreurUtilisateur, match=r"boucle\.candidates"):
        depot.enregistrer(AUTRE, {"boucle": {"candidates": 20}})

    # Tiers 3 (« perso pur »), jamais hérité : ce qu'AUTRE a écrit lui
    # appartient, sans rien devoir au socle ni au mainteneur. `local` (qui
    # n'a rien écrit) ne reçoit ni « 2022-06-01 » (le TOML du serveur) ni
    # « Point zéro » (son départ) : `historique_depuis` retombe sur le
    # défaut du cœur, et `depart` sur le comblement neutre de l'embarquement
    # (`COMBLEMENT_EMBARQUEMENT`, Q66 — trou mesuré et fermé le 22/09/2026 :
    # `historique_depuis` est un champ scalaire à la racine, pas une
    # section, et `SocleTOML.config` ne le taisait pas encore).
    assert autre.historique_depuis.isoformat() == "2024-01-01"
    assert local.historique_depuis.isoformat() == "2023-12-01"
    assert autre.depart.nom == "Chez l'autre"
    assert (local.depart.latitude, local.depart.longitude) == (0.0, 0.0)
    assert local.depart.nom != "Point zéro"
    assert [e.nom for e in autre.evitements] == ["carrefour test"]
    assert local.evitements == ()

    # `tenue` appartient au cycliste dans le **modèle de données** (Q35),
    # mais son interface d'édition attend explicitement la V2 (« même ça
    # attend la V2 ») : en V1, elle reste refusée en écriture, comme une
    # section serveur ordinaire — décision prise en écrivant ce lot, à
    # corriger d'un trait si elle ne convient pas.
    with pytest.raises(ErreurUtilisateur, match="tenue"):
        depot.enregistrer(AUTRE, {"tenue": {"vent_veste_kmh": 25.0}})


# --- ce que la réconciliation des tests de contrat a ajouté (17/09/2026) -----


def test_un_transport_injecte_est_habille_du_connecteur_du_proprietaire(tmp_path: Path):
    """La convention d'injection : on donne un transport, la route habille.

    C'était le point qui bloquait douze tests de contrat écrits en aveugle.
    Le connecteur Intervals a besoin d'une clé, et cette clé est dans le
    **profil** — que la fabrique ne connaît pas encore et que la route
    connaît. Un `httpx.Client` suffit donc, pour les cinq services.
    """
    application = creer_application(
        chemin_config=ecrire_config(tmp_path),
        dossier_donnees=tmp_path / "cache" / "api",
        client_intervals=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
        ),
    )
    reponse = TestClient(application, raise_server_exceptions=False).get("/api/v1/seances")
    assert reponse.status_code == 200, reponse.text


def test_un_connecteur_deja_construit_reste_accepte_tel_quel(tmp_path: Path):
    """L'autre moitié de la même règle : ce qui n'est pas un transport est un connecteur."""
    client = serveur(tmp_path, intervals=intervals_refuse())
    assert client.get("/api/v1/seances").json()["erreur"]["code"] == "intervals_refuse"


def test_le_schema_publie_le_catalogue_des_codes_de_panne(tmp_path: Path):
    """Un front ne peut pas dessiner un état qu'il ne sait pas reconnaître.

    Les deux cas qui manquaient sont ceux de E14 · dégradé et E15 · échec ;
    on vérifie la table entière pour que le prochain ajout ne s'oublie pas.
    """
    schema = json.dumps(serveur(tmp_path).get("/openapi.json").json(), ensure_ascii=False)
    for code in CODES_PANNE:
        assert code in schema, f"le code {code!r} n'est nommé nulle part dans le schéma publié"


def test_une_panne_de_service_rappelle_la_date_du_dernier_succes(tmp_path: Path):
    """E15 : « La date compte plus que le message. »

    Deux temps, parce qu'un seul ne prouverait rien : la clé marche, puis elle
    est révoquée, et c'est la date du premier appel qui doit revenir. Les deux
    serveurs partagent le dossier de données — c'est là que la mémoire vit.
    """
    assert serveur(tmp_path, intervals=client_intervals()).get("/api/v1/seances").status_code == 200
    erreur = serveur(tmp_path, intervals=intervals_refuse()).get("/api/v1/seances").json()["erreur"]
    assert erreur["code"] == "intervals_refuse"
    assert erreur["details"]["dernier_succes"], "aucune date retenue du premier appel réussi"


def test_un_compte_neuf_n_invente_pas_une_date_de_dernier_succes(tmp_path: Path):
    """`null` et non une date : un compte neuf n'a rien manqué, et l'écran doit le voir."""
    erreur = serveur(tmp_path, intervals=intervals_refuse()).get("/api/v1/seances").json()["erreur"]
    assert erreur["details"]["dernier_succes"] is None


@pytest.mark.parametrize("valeur", ["", "   ", "\x00\x01\x02"], ids=["vide", "espaces", "octets"])
def test_une_chaine_vide_de_sens_est_refusee_au_bord(tmp_path: Path, valeur: str):
    """`min_length=1` laissait passer deux des trois — et `jour=""` devenait « aujourd'hui »."""
    client = serveur(tmp_path)
    assert client.get("/api/v1/geocodage", params={"adresse": valeur}).status_code == 422
    refus = client.post("/api/v1/sorties", json={"jour": valeur})
    assert refus.status_code == 422, refus.text
    assert refus.json()["erreur"]["code"] == "requete_invalide"


def test_un_depot_trop_gros_est_refuse_sur_sa_taille_annoncee(tmp_path: Path):
    reponse = serveur(tmp_path).post(
        "/api/v1/seances/fichier",
        files={"fichier": ("gros.zwo", b"0" * 2_000_000, "text/xml")},
    )
    assert reponse.status_code == 413
    assert "annoncés" in reponse.json()["erreur"]["message"]


def test_le_chemin_du_serveur_ne_sort_jamais_dans_un_refus_de_depot(tmp_path: Path):
    """Le cœur cite le chemin qu'on lui donne ; c'est à l'API de le remplacer.

    Ce que le cycliste reconnaît, c'est le nom de **son** fichier — pas
    `/var/folders/…/fichiers/137a….zwo`, qui en prime décrit l'arborescence du
    serveur (doctrine §10.2).
    """
    reponse = serveur(tmp_path).post(
        "/api/v1/seances/fichier", files={"fichier": ("vide.zwo", b"", "application/xml")}
    )
    assert reponse.status_code == 422
    message = reponse.json()["erreur"]["message"]
    assert message.startswith("vide.zwo"), message
    assert str(tmp_path) not in message


def test_la_route_d_ecriture_du_profil_publie_ce_qu_elle_accepte(tmp_path: Path):
    """Décision 7 : la position se stocke, la puissance d'endurance se déduit.

    Le corps de `PATCH /profil` est lu à la main et validé par la liste
    blanche : sans schéma publié, F2 devait lire `depots.py` pour l'apprendre.
    """
    schema = serveur(tmp_path).get("/openapi.json").json()
    corps = schema["paths"]["/api/v1/profil"]["patch"]["requestBody"]
    proprietes = corps["content"]["application/json"]["schema"]["properties"]
    assert set(proprietes) == (
        set(CHAMPS_MODIFIABLES) | set(LISTES_MODIFIABLES) | set(CHAMPS_RACINE_MODIFIABLES)
    )
    assert set(proprietes["seance"]["properties"]) == {"position_zone"}
    assert set(proprietes["boucle"]["properties"]) == {"sens"}


def test_le_facteur_compteur_dit_en_un_mot_s_il_est_mesure_ou_suppose(tmp_path: Path):
    liees = serveur(tmp_path).get("/api/v1/profil/zones").json()["donnees"]["valeurs_liees"]
    assert liees["facteur_provenance"] in {"mesure", "suppose"}
    assert liees["facteur_provenance"] == ("mesure" if liees["facteur_mesure"] else "suppose")


# --- Q40 (g) : le GPX d'une proposition, fabriqué à l'appel --------------------

#: Deux azimuts au relief marqué : sans quoi les anneaux bouchonnés se
#: ressemblent tous et `contraste.choisir` ne garde qu'une proposition — un
#: test sur « trois traces différentes » ne prouverait alors rien.
RELIEFS_CONTRASTES = {0.0: {"amplitude_m": 90.0}, 180.0: {"amplitude_m": 40.0}}


def test_chaque_proposition_rend_une_trace_differente(tmp_path: Path):
    """Le défaut que la génération paresseuse corrige.

    Tant qu'un seul GPX était exposé, choisir « la plus sèche » puis l'envoyer
    au compteur envoyait la trace de « la plus calme ». Deux propositions
    contrastées doivent donc rendre deux fichiers différents.
    """
    client = serveur(
        tmp_path,
        brouter=moteur_brouter(RELIEFS_CONTRASTES),
        meteo=moteur_meteo(pluie=pluie_au_nord),
        intervals=client_intervals(),
    )
    donnees = client.post(
        "/api/v1/sorties",
        json={"jour": JOUR.isoformat(), "candidates": 4, "heure_depart": "09:00"},
    ).json()["donnees"]
    traces = [client.get(p["gpx"]["url"]).text for p in donnees["propositions"]]
    assert len(traces) >= 2, "sans deux propositions, ce test ne prouve rien"
    assert len(set(traces)) == len(traces), "deux propositions rendent la même trace"


def test_aucun_gpx_n_est_ecrit_sur_le_disque(tmp_path: Path):
    """Q40 (g) : ni à la génération (deux jetées), ni au choix (la réponse *est* le fichier)."""
    client = serveur(
        tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(), intervals=client_intervals()
    )
    donnees = client.post(
        "/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2}
    ).json()["donnees"]
    for proposition in donnees["propositions"]:
        assert client.get(proposition["gpx"]["url"]).status_code == 200
    assert not list((tmp_path / "cache" / "api").rglob("*.gpx"))
    assert not list((tmp_path / "cache" / "sorties").glob("*.gpx"))


def test_le_gpx_est_servi_avec_son_nom_de_telechargement(tmp_path: Path):
    client = serveur(
        tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(), intervals=client_intervals()
    )
    donnees = client.post(
        "/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2}
    ).json()["donnees"]
    proposition = donnees["propositions"][-1]
    reponse = client.get(proposition["gpx"]["url"])
    assert reponse.headers["content-type"].startswith("application/gpx+xml")
    assert proposition["gpx"]["nom"] in reponse.headers["content-disposition"]


def test_une_generation_oubliee_est_un_404_nomme(tmp_path: Path):
    """Le prix assumé de ne rien écrire : l'écran redemande une recherche.

    Un 500 laisserait une page blanche ; `generation_introuvable` dit au front
    quoi proposer.
    """
    client = serveur(tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo())
    reponse = client.get("/api/v1/sorties/" + "0" * 32 + "/propositions/1/gpx")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "generation_introuvable"
    assert reponse.json()["erreur"]["code"] in CODES_PANNE


def test_une_proposition_inconnue_de_la_generation_est_refusee(tmp_path: Path):
    client = serveur(
        tmp_path, brouter=moteur_brouter(), meteo=moteur_meteo(), intervals=client_intervals()
    )
    donnees = client.post(
        "/api/v1/sorties", json={"jour": JOUR.isoformat(), "candidates": 2}
    ).json()["donnees"]
    reponse = client.get(f"/api/v1/sorties/{donnees['generation']}/propositions/99/gpx")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "generation_introuvable"


# --- Q40 (a) : une date lointaine arrive avec sa météo déclarée absente --------


def _jour_lointain() -> str:
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    from ourouler.config import HORIZON_JOURS_DEFAUT

    return (_date.today() + _timedelta(days=HORIZON_JOURS_DEFAUT + 30)).isoformat()


def test_une_date_lointaine_est_servie_sans_502(tmp_path: Path):
    """Q40 (a) : « le service est en panne » n'est pas la même chose que « trop loin ».

    Aucun client météo n'est injecté, et aucun n'est appelé : s'il l'était, la
    commande sortirait sur le réseau, ce que la règle absolue 3 interdit.
    """
    client = serveur(tmp_path, brouter=moteur_brouter(), intervals=client_intervals())
    lointain = _jour_lointain()
    reponse = client.post("/api/v1/sorties", json={"jour": lointain, "candidates": 2})
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["candidates"], "le parcours est servi"
    assert donnees["meteo_absente"]["jour"] == lointain
    assert donnees["tenue"] is None
    assert "pas de météo" in donnees["meteo_absente"]["message"]


def test_une_boucle_libre_lointaine_est_servie_sans_502(tmp_path: Path):
    client = serveur(tmp_path, brouter=moteur_brouter())
    reponse = client.post(
        "/api/v1/boucles",
        json={
            "distance_km": 30.0,
            "direction": "N",
            "heure_depart": f"{_jour_lointain()}T09:00",
        },
    )
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["candidates"]
    assert "pas de météo" in donnees["meteo_absente"]["message"]


# --- le dépôt des générations, vu de près --------------------------------------


class _GpxFactice:
    """Ce que le cœur remet au dépôt : un numéro, un nom, un texte."""

    def __init__(self, numero: int) -> None:
        self.numero = numero
        self.nom_fichier = f"sortie_20260908_n{numero}.gpx"
        self.texte = f"<gpx n={numero}/>"


def test_une_generation_n_est_pas_lisible_par_un_autre_proprietaire():
    """L'identifiant est opaque, mais l'opacité n'est pas l'isolation.

    La clé porte le propriétaire : demander la génération de A en étant B est
    introuvable, sans que la réponse dise qu'elle existe ailleurs.
    """
    from ourouler.api.depots import DepotGenerations

    depot = DepotGenerations()
    identifiant = depot.retenir(PROPRIETAIRE_LOCAL, [_GpxFactice(1)])
    assert depot.gpx(PROPRIETAIRE_LOCAL, identifiant, 1)[0].endswith("_n1.gpx")
    with pytest.raises(ErreurUtilisateur):
        depot.gpx(AUTRE, identifiant, 1)


def test_les_generations_les_plus_vieilles_sont_oubliees_d_abord():
    """Borné exprès : la mémoire d'un serveur n'est pas un dossier de fichiers."""
    from ourouler.api.depots import DepotGenerations

    depot = DepotGenerations(taille=2)
    vieille = depot.retenir(PROPRIETAIRE_LOCAL, [_GpxFactice(1)])
    for _ in range(2):
        depot.retenir(PROPRIETAIRE_LOCAL, [_GpxFactice(1)])
    with pytest.raises(ErreurUtilisateur, match="relancer la recherche"):
        depot.gpx(PROPRIETAIRE_LOCAL, vieille, 1)


def test_un_identifiant_mal_forme_ne_construit_aucune_cle():
    from ourouler.api.depots import DepotGenerations

    with pytest.raises(ErreurUtilisateur):
        DepotGenerations().gpx(PROPRIETAIRE_LOCAL, "../../etc/passwd", 1)


# --- l'application au socle vide, et ce qu'elle a le droit de dire -----------
#
# **Il y a deux fabriques, et rien à l'écran ne disait laquelle prendre.**
# `creer_application()` est la fabrique de bibliothèque : elle ne lit rien,
# c'est le point d'injection de la règle absolue 3, et elle ne doit pas
# changer. `ourouler.api.application:application` est la fabrique de service.
# Le mainteneur a lancé la première en croyant lancer la seconde, et a eu une
# application qui démarrait en annonçant « configuration invalide » sur tout —
# avec, pour explication, « section [depart] manquante », c'est-à-dire le
# reproche fait à un fichier qu'il n'avait jamais eu l'intention d'écrire.


def test_la_fabrique_de_bibliotheque_se_construit_toujours_sans_rien():
    """L'invariant à ne pas casser : sans argument, sans disque, sans réseau."""
    client = TestClient(creer_application(), raise_server_exceptions=False)
    assert client.get("/openapi.json").status_code == 200


def test_une_application_sans_profil_dit_qu_elle_n_en_a_pas_et_comment_en_avoir_un():
    client = TestClient(creer_application(), raise_server_exceptions=False)
    reponse = client.get("/api/v1/systeme")
    assert reponse.status_code == 503, "rien n'est cassé : le service n'est pas prêt"
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "profil_absent"
    assert "sans profil" in erreur["message"]
    assert "PATCH /api/v1/profil" in erreur["message"], "le geste, pas seulement le constat"
    assert "ourouler api" in erreur["message"], "l'autre fabrique est nommée"
    assert "[depart]" not in erreur["message"], (
        "parler d'une section de TOML décrit un fichier que l'appelant n'a jamais écrit"
    )


def test_intervals_jamais_relie_n_est_pas_une_demande_invalide():
    """« Cette demande n'est pas valide » pour une source qu'on n'a pas branchée.

    Le premier compte invité (19/09/2026) est arrivé sur l'écran d'aujourd'hui
    et a lu ça, suivi de « compléter [intervals] athlete_id et api_key dans la
    configuration » — le vocabulaire d'un fichier TOML que personne d'autre
    que le mainteneur ne verra jamais. Ce n'est ni une faute de l'appelant, ni
    une panne : c'est une source de données que ce cycliste n'a pas encore
    reliée, et elle a désormais son code à elle.

    Le texte reste celui du cœur, où il est juste pour la ligne de commande ;
    c'est le **type** de l'exception qui permet à l'API de le classer, et au
    front de le remplacer par une phrase et un bouton vers les réglages.
    """
    from ourouler.api.erreurs import classer
    from ourouler.noyau.erreurs import ErreurIntervalsAbsent, ErreurUtilisateur

    panne = classer(ErreurIntervalsAbsent("séance : Intervals.icu n'est pas renseigné"))
    assert panne.code == "intervals_absent"
    assert panne.statut == 409, "ni 4xx de forme, ni 5xx : l'état du compte n'est pas prêt"

    # La contre-épreuve : une `ErreurUtilisateur` ordinaire reste, elle, une
    # demande invalide. Sans ça, « ne pas dire requete_invalide » s'obtiendrait
    # en ne le disant plus jamais.
    ordinaire = classer(ErreurUtilisateur("jour : format attendu AAAA-MM-JJ"))
    assert ordinaire.code == "requete_invalide"


def test_les_routes_de_donnees_repondent_toutes_la_meme_chose_sans_profil():
    """Une seule phrase, partout : une liste d'exceptions se remplirait toute seule."""
    client = TestClient(creer_application(), raise_server_exceptions=False)
    for route in ("/api/v1/systeme", "/api/v1/profil", "/api/v1/profil/zones", "/api/v1/meteo"):
        assert route and client.get(route).json()["erreur"]["code"] == "profil_absent", route


def test_un_profil_ecrit_par_patch_rend_l_application_au_socle_vide_utilisable(tmp_path: Path):
    """Le socle vide reste **modifiable** : c'est par là qu'on lui donne un profil."""
    client = TestClient(
        creer_application(dossier_donnees=tmp_path / "donnees"),
        raise_server_exceptions=False,
    )
    reponse = client.patch(
        "/api/v1/profil",
        json={
            "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 80, "ftp_w": 250},
        },
    )
    assert reponse.status_code == 200, reponse.text
    assert client.get("/api/v1/profil").status_code == 200


def test_un_profil_commence_mais_incomplet_nomme_ce_qui_manque():
    """L'autre moitié : là, l'erreur de validation *est* l'information utile."""
    from ourouler.api.depots import SocleVide
    from ourouler.api.erreurs import ErreurProfilAbsent

    with pytest.raises(ErreurProfilAbsent) as faute:
        SocleVide().config({"cycliste": {"masse_kg": 80, "ftp_w": 250}})
    assert "incomplet" in str(faute.value)
    assert "PATCH /api/v1/profil" in str(faute.value)


def test_le_pneu_d_un_velo_s_enregistre_et_se_relit(tmp_path: Path):
    """L9.1 : la fiche vélo porte une catégorie de pneu, validée comme la
    configuration TOML — une inconnue est refusée et nommée, jamais tue."""
    client = serveur(tmp_path)
    velos = [{"nom": "Route", "usage": "route", "masse_kg": 9.0, "pneu": "course_quatre_saisons"}]
    reponse = client.patch("/api/v1/profil", json={"velos": velos})
    assert reponse.status_code == 200
    relu = client.get("/api/v1/profil").json()["donnees"]["velos"][0]
    assert relu["pneu"] == "course_quatre_saisons"

    refus = client.patch(
        "/api/v1/profil", json={"velos": [{"nom": "Route", "pneu": "pneu inventé"}]}
    )
    assert refus.status_code >= 400
    assert "pneu" in refus.text

"""L'accueil : `assistant_recommande`, la lecture du profil Intervals, la FTP par vitesse+terrain.

Trois pièces neuves du 19/09/2026 (`docs/journal/ux/parcours_accueil.md`) :

- `GET /profil` porte `donnees.assistant_recommande`, le signal qui doit
  faire atterrir un compte neuf dans l'assistant plutôt que sur l'écran du
  jour, qui réclame Intervals et échoue (défaut constaté en vrai) ;
- `GET /profil/intervals` lit le profil de l'athlète pour confirmation
  ([[Q64]]) ;
- `POST /profil/ftp/apercu` calcule une FTP à partir d'une vitesse au
  compteur et d'un terrain déclarés (T4), sans rien stocker.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from outils_api import (
    CLE_INTERVALS_SENTINELLE,
    DEPART_SYNTHETIQUE,
    client_api,
    client_bouchon,
    config_d_essai,
)

#: Un TOML d'essai minimal, écrit sur `tmp_path` — jamais de coordonnée réelle
#: (règle absolue 1). Sert les tests qui écrivent (`PATCH /profil`) : `config=`
#: donne un socle **en lecture seule** (`SocleFixe`), voir
#: `_service_pour_deux` dans `test_api_isolation_proprietaire.py` pour le même
#: constat. `chemin_config=` reste modifiable.
_TOML_ESSAI = (
    f'[depart]\nnom = "{DEPART_SYNTHETIQUE["nom"]}"\n'
    f"latitude = {DEPART_SYNTHETIQUE['latitude']}\n"
    f"longitude = {DEPART_SYNTHETIQUE['longitude']}\n"
    "\n[cycliste]\nmasse_kg = 70.0\n"
    '\n[[velos]]\nnom = "Essai"\nusage = "route"\nmasse_kg = 9.0\n'
)


def _client_modifiable(tmp_path: Path):
    chemin = tmp_path / "config.toml"
    chemin.write_text(_TOML_ESSAI, encoding="utf-8")
    return client_api(chemin_config=chemin, dossier_donnees=tmp_path / "donnees")


# --- assistant_recommande -----------------------------------------------------


def test_assistant_recommande_vrai_sur_un_profil_jamais_touche(tmp_path: Path):
    """Aucune surcharge écrite pour ce propriétaire : le compte est neuf."""
    client = _client_modifiable(tmp_path)
    reponse = client.get("/api/v1/profil")
    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["assistant_recommande"] is True


def test_assistant_recommande_faux_apres_le_premier_patch(tmp_path: Path):
    """Le premier `PATCH /profil` fait tomber le drapeau — pas un état à part,
    juste la conséquence de ce qui est maintenant écrit sur le disque."""
    client = _client_modifiable(tmp_path)
    ecrit = client.requete("PATCH", "/api/v1/profil", json={"cycliste": {"masse_kg": 71.0}})
    assert ecrit.status_code == 200, ecrit.text[:300]
    assert ecrit.json()["donnees"]["assistant_recommande"] is False
    relu = client.get("/api/v1/profil")
    assert relu.json()["donnees"]["assistant_recommande"] is False


# --- GET /profil/intervals -----------------------------------------------------


def test_profil_intervals_refuse_sans_cle_posee():
    """Ni panne ni faute : un compte qui n'a pas encore posé sa clé Intervals."""
    client = client_api(config=config_d_essai(intervals={"athlete_id": "", "api_key": ""}))
    reponse = client.get("/api/v1/profil/intervals")
    assert reponse.status_code == 409
    assert reponse.json()["erreur"]["code"] == "intervals_absent"


def test_profil_intervals_rend_ftp_et_poids_pour_confirmation():
    """Rien n'est stocké : c'est un aperçu, comme `/profil/zones/apercu`."""
    bouchon = client_bouchon(
        200,
        {
            "id": "i000000",
            "weight": 68.4,
            "sportSettings": [{"types": ["Ride"], "ftp": 231}],
        },
    )
    client = client_api(config=config_d_essai(), client_intervals=bouchon)
    reponse = client.get("/api/v1/profil/intervals")
    assert reponse.status_code == 200
    assert reponse.json()["donnees"] == {"ftp_w": 231.0, "masse_kg": 68.4}
    # Rien écrit : le profil n'a toujours reçu aucune surcharge.
    assert client.get("/api/v1/profil").json()["donnees"]["assistant_recommande"] is True


def test_profil_intervals_401_ne_laisse_pas_fuir_la_cle():
    """Clé révoquée (E15 · échec) : la sentinelle de la clé n'apparaît jamais."""
    bouchon = client_bouchon(401, {"error": "unauthorized"})
    client = client_api(config=config_d_essai(), client_intervals=bouchon)
    reponse = client.get("/api/v1/profil/intervals")
    assert reponse.status_code >= 400
    assert CLE_INTERVALS_SENTINELLE not in reponse.text


# --- PATCH /profil {intervals: {api_key}} : résolution de l'athlete_id ---------
#
# Correctif de prod du 25/09/2026 : un invité hébergé ne peut brancher
# Intervals que par sa clé (l'assistant et Réglages ne demandent jamais son
# athlete_id) — sans résolution côté serveur, `ParametresIntervals.renseigne`
# restait faux et toutes les routes Intervals répondaient 409 `intervals_absent`.


def test_patch_profil_cle_seule_resout_l_athlete_id_et_l_ecrit(tmp_path: Path):
    chemin = tmp_path / "config.toml"
    chemin.write_text(_TOML_ESSAI, encoding="utf-8")
    bouchon = client_bouchon(200, {"id": "i555555", "weight": 70.0})
    client = client_api(
        chemin_config=chemin,
        dossier_donnees=tmp_path / "donnees",
        client_intervals=bouchon,
    )
    patch = client.requete(
        "PATCH",
        "/api/v1/profil",
        json={"intervals": {"api_key": CLE_INTERVALS_SENTINELLE}},
    )
    assert patch.status_code == 200, patch.text[:300]
    assert patch.json()["donnees"]["services"]["intervals"]["renseigne"] is True
    assert patch.json()["donnees"]["services"]["intervals"]["athlete_id"] == "i555555"
    # La clé posée n'apparaît jamais dans la réponse.
    assert CLE_INTERVALS_SENTINELLE not in patch.text
    # Rechargé depuis le disque, le profil porte bien le vrai identifiant :
    # `GET /profil/intervals` ne répond plus 409 `intervals_absent`.
    lu = client.get("/api/v1/profil")
    assert lu.json()["donnees"]["services"]["intervals"]["athlete_id"] == "i555555"


def test_patch_profil_athlete_id_deja_pose_n_est_pas_ecrase(tmp_path: Path):
    """`athlete_id` déjà présent (non vide) dans le corps : pas d'appel réseau."""
    chemin = tmp_path / "config.toml"
    chemin.write_text(_TOML_ESSAI, encoding="utf-8")

    def refuse(requete):  # ne doit jamais être appelé
        raise AssertionError(f"appel réseau inattendu : {requete.url}")

    import httpx

    bouchon = httpx.Client(transport=httpx.MockTransport(refuse))
    client = client_api(
        chemin_config=chemin,
        dossier_donnees=tmp_path / "donnees",
        client_intervals=bouchon,
    )
    patch = client.requete(
        "PATCH",
        "/api/v1/profil",
        json={"intervals": {"athlete_id": "i000001", "api_key": CLE_INTERVALS_SENTINELLE}},
    )
    assert patch.status_code == 200, patch.text[:300]
    assert patch.json()["donnees"]["services"]["intervals"]["athlete_id"] == "i000001"


def test_patch_profil_cle_refusee_n_ecrit_rien(tmp_path: Path):
    """Clé rejetée par Intervals (401) : `intervals_refuse`, rien n'est écrit."""
    chemin = tmp_path / "config.toml"
    chemin.write_text(_TOML_ESSAI, encoding="utf-8")
    bouchon = client_bouchon(401, {"error": "unauthorized"})
    client = client_api(
        chemin_config=chemin,
        dossier_donnees=tmp_path / "donnees",
        client_intervals=bouchon,
    )
    patch = client.requete(
        "PATCH",
        "/api/v1/profil",
        json={"intervals": {"api_key": CLE_INTERVALS_SENTINELLE}},
    )
    assert patch.status_code >= 400
    assert patch.json()["erreur"]["code"] == "intervals_refuse"
    assert CLE_INTERVALS_SENTINELLE not in patch.text
    # Rien écrit : le profil reste celui d'un compte jamais touché.
    lu = client.get("/api/v1/profil")
    assert lu.json()["donnees"]["assistant_recommande"] is True
    assert lu.json()["donnees"]["services"]["intervals"]["renseigne"] is False


def test_patch_profil_intervals_injoignable_n_ecrit_rien(tmp_path: Path):
    chemin = tmp_path / "config.toml"
    chemin.write_text(_TOML_ESSAI, encoding="utf-8")

    import httpx

    def injoignable(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("injoignable", request=requete)

    bouchon = httpx.Client(transport=httpx.MockTransport(injoignable))
    client = client_api(
        chemin_config=chemin,
        dossier_donnees=tmp_path / "donnees",
        client_intervals=bouchon,
    )
    patch = client.requete(
        "PATCH",
        "/api/v1/profil",
        json={"intervals": {"api_key": CLE_INTERVALS_SENTINELLE}},
    )
    assert patch.status_code >= 400
    assert patch.json()["erreur"]["code"] in ("intervals_indisponible", "service_externe_indisponible")
    lu = client.get("/api/v1/profil")
    assert lu.json()["donnees"]["services"]["intervals"]["renseigne"] is False


# --- POST /profil/ftp/apercu ----------------------------------------------------


def test_apercu_ftp_depuis_terrain_ne_stocke_rien():
    client = client_api(config=config_d_essai())
    reponse = client.post(
        "/api/v1/profil/ftp/apercu",
        json={"vitesse_kmh": 24.0, "denivele_m_par_km": 10.0},
    )
    assert reponse.status_code == 200
    donnees = reponse.json()["donnees"]
    assert donnees["ftp_w"] is not None and donnees["ftp_w"] > 0
    assert donnees["valeurs_liees"] is not None
    # Rien écrit : le profil n'a reçu aucune surcharge par cet appel.
    assert client.get("/api/v1/profil").json()["donnees"]["assistant_recommande"] is True


def test_apercu_ftp_terrain_plus_raide_demande_plus_de_puissance():
    """Le levier du §6 de `docs/journal/ux/parcours_accueil.md` : à vitesse compteur
    égale, un terrain plus raide implique une FTP plus haute."""
    client = client_api(config=config_d_essai())
    plat = client.post(
        "/api/v1/profil/ftp/apercu", json={"vitesse_kmh": 24.0, "denivele_m_par_km": 3.0}
    ).json()["donnees"]["ftp_w"]
    montagne = client.post(
        "/api/v1/profil/ftp/apercu", json={"vitesse_kmh": 24.0, "denivele_m_par_km": 30.0}
    ).json()["donnees"]["ftp_w"]
    assert montagne > plat


def test_apercu_ftp_sans_velo_est_un_refus_nomme():
    """`depuis_dict` pose toujours un vélo « Route » par défaut (F0.6) : le cas
    « aucun vélo » ne s'obtient qu'en le retirant après coup."""
    config = dataclasses.replace(config_d_essai(), velos=())
    client = client_api(config=config)
    reponse = client.post(
        "/api/v1/profil/ftp/apercu",
        json={"vitesse_kmh": 24.0, "denivele_m_par_km": 10.0},
    )
    assert reponse.status_code == 400
    assert "vélo" in reponse.json()["erreur"]["message"]


def test_apercu_ftp_vitesse_incoherente_avec_le_terrain_est_un_refus_nomme():
    """Une moyenne compteur bien trop haute pour le terrain choisi — aucune
    puissance plausible ne l'explique, ce n'est pas au modèle de deviner."""
    client = client_api(config=config_d_essai())
    reponse = client.post(
        "/api/v1/profil/ftp/apercu",
        json={"vitesse_kmh": 95.0, "denivele_m_par_km": 30.0},
    )
    assert reponse.status_code == 400
    assert reponse.json()["erreur"]["code"] == "requete_invalide"


# --- GET /profil/ftp/generique (T5, le fond du tunnel) --------------------------


def test_ftp_generique_ne_stocke_rien_et_ne_peut_pas_echouer():
    client = client_api(config=config_d_essai())
    reponse = client.get("/api/v1/profil/ftp/generique")
    assert reponse.status_code == 200
    donnees = reponse.json()["donnees"]
    assert donnees["ftp_w"] is not None and donnees["ftp_w"] > 0
    assert client.get("/api/v1/profil").json()["donnees"]["assistant_recommande"] is True


def test_ftp_generique_marche_meme_sans_le_moindre_velo():
    """« Jamais rien » — le filet de littérature ne demande qu'un poids."""
    config = dataclasses.replace(config_d_essai(), velos=())
    client = client_api(config=config)
    reponse = client.get("/api/v1/profil/ftp/generique")
    assert reponse.status_code == 200
    assert reponse.json()["donnees"]["ftp_w"] is not None

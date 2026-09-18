"""Le paquetage du front et de l'API sur un seul service (lot L7.E).

Deux promesses, prouvées ici et nulle part ailleurs :

- **la sonde de santé répond sans session**, y compris sur un déploiement
  hébergé qui n'a jamais ouvert la moindre session — sinon un orchestrateur
  (Coolify, `docker compose --wait`, un `HEALTHCHECK`) croirait le service
  mort dès qu'aucune méthode d'authentification n'est branchée, ce qui est
  précisément l'état par défaut du lot L7.A ;
- **le front construit se sert depuis la même origine que l'API**, sans
  masquer aucune route de `/api/v1` — `front/README.md` : « le code, lui,
  n'appelle que des chemins relatifs sous /api/v1, si bien qu'en production
  l'API et le front se servent depuis la même origine. » C'est la promesse
  que ce test vérifie tenue côté serveur.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from outils_api import client_api

from ourouler.api.session import SessionHebergee

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")


def test_la_sonde_de_sante_repond_sans_session():
    """Un service hébergé, sans authentification branchée, reste sondable.

    `SessionHebergee` n'ouvre jamais de session (lot L7.A) : c'est
    exactement l'état d'un déploiement fraîchement posé, avant même que la
    méthode de connexion soit choisie. Un `/api/v1/systeme` y répondrait 401
    (voir `test_api_isolation_proprietaire.py`) — la sonde, elle, doit
    répondre 200 quand même, sinon l'orchestrateur redémarre en boucle un
    service qui n'a rien de cassé.
    """
    client = client_api(session=SessionHebergee())
    reponse = client.get("/sante")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["etat"] == "ok"
    assert corps["version"]


def test_la_sonde_de_sante_est_hors_du_contrat_publie():
    """`/sante` n'est pas une promesse faite à un cycliste : elle n'entre pas dans le schéma.

    `test_api_isolation_proprietaire.py::test_la_liste_des_routes_hors_donnees_ne_ment_pas`
    interdit toute dispense sous `/api/v1` — cette sonde vit donc hors du
    préfixe, et hors du schéma OpenAPI que `front/` lit pour savoir quoi
    appeler : elle n'a rien à y faire, elle n'est pas un service du produit.
    """
    client = client_api(session=SessionHebergee())
    schema = client.get("/openapi.json").json()
    assert "/sante" not in schema.get("paths", {})


def _construire_front(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><title>où rouler</title><body>front construit</body>",
        encoding="utf-8",
    )
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("// front construit", encoding="utf-8")
    return dist


def test_le_front_construit_est_servi_a_la_racine(tmp_path: Path):
    """`dossier_front` donné : `/` rend `index.html`, comme un serveur statique ordinaire."""
    dist = _construire_front(tmp_path)
    client = client_api(dossier_front=dist)
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert "front construit" in reponse.text


def test_le_front_construit_sert_aussi_ses_fichiers(tmp_path: Path):
    dist = _construire_front(tmp_path)
    client = client_api(dossier_front=dist)
    reponse = client.get("/assets/app.js")
    assert reponse.status_code == 200
    assert "front construit" in reponse.text


def test_le_montage_du_front_ne_masque_aucune_route_de_l_api(tmp_path: Path):
    """Le point du lot : `/api/v1/...` et `/sante` restent prioritaires sur `/`.

    Un montage `StaticFiles("/")` enregistré avant les routes de l'API les
    intercepterait toutes — la garde est dans l'ordre d'enregistrement
    (`application.py`), et c'est ce que ce test éprouve, pas seulement
    l'ordre du code source.
    """
    dist = _construire_front(tmp_path)
    client = client_api(dossier_front=dist, session=SessionHebergee())

    sans_session = client.get("/api/v1/systeme")
    assert sans_session.status_code == 401
    assert sans_session.json()["erreur"]["code"] == "session_absente"

    sonde = client.get("/sante")
    assert sonde.status_code == 200

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/v1/systeme" in schema.json()["paths"]


def test_sans_dossier_front_la_racine_ne_sert_rien():
    """L'absence de `dossier_front` (le défaut, `ourouler api` compris) ne monte rien.

    Une route non servie rend la forme d'erreur du projet (`route_inconnue`),
    jamais un 404 nu de FastAPI ni une trace.
    """
    client = client_api()
    reponse = client.get("/")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "route_inconnue"

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

from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.api.session import SessionHebergee
from ourouler.erreurs import ErreurConfig

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


def test_un_chemin_du_front_inconnu_de_staticfiles_rend_index_html(tmp_path: Path):
    """La panne constatée en vrai le 19/09/2026 (lot L7.2-D) : `/entrer` sur un 404.

    `/entrer` (l'écran d'activation d'une invitation) et `/connexion` ne
    correspondent à aucun fichier du front construit : avant ce lot,
    `StaticFiles` les faisait tomber sur le même 404 JSON qu'une route
    d'API inconnue, et le lien d'invitation n'ouvrait jamais l'écran attendu
    — la page blanche que la doctrine interdit. Le front n'a pas de routeur
    (`front/src/App.tsx` décide sur `window.location.pathname`, une fois
    chargé) : il lui faut `index.html`, pas un refus.
    """
    dist = _construire_front(tmp_path)
    client = client_api(dossier_front=dist)

    reponse = client.get("/entrer")
    assert reponse.status_code == 200
    assert "text/html" in reponse.headers.get("content-type", "")
    assert "front construit" in reponse.text

    reponse = client.get("/connexion")
    assert reponse.status_code == 200
    assert "front construit" in reponse.text


def test_un_chemin_d_api_inconnu_ne_bascule_jamais_sur_index_html(tmp_path: Path):
    """Le repli ne doit **jamais** avaler une route d'API — l'autre sens du test ci-dessus.

    Sans cette garde, `/api/v1/inconnu` répondrait 200 en HTML au lieu du 404
    JSON `route_inconnue` que le front sait reconnaître (`api/client.ts`,
    `reponse_illisible`) — la panne la plus déroutante qui soit, un serveur
    qui a l'air de répondre normalement à une route qui n'existe pas.
    """
    dist = _construire_front(tmp_path)
    client = client_api(dossier_front=dist)
    reponse = client.get("/api/v1/inconnu")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "route_inconnue"
    assert "front construit" not in reponse.text


def test_api_sans_barre_finale_ne_bascule_pas_non_plus(tmp_path: Path):
    """`/api` tout court passait la garde, parce que `"/api".startswith("/api/")` est faux.

    Une base d'URL mal construite ou une sonde générique interrogeait donc la
    racine du préfixe et recevait `index.html` en 200, là où elle attendait une
    erreur. Trouvé en relecture le 19/09/2026 ; le préfixe gardé est désormais
    `"/api"`, qui couvre les deux.
    """
    client = client_api(dossier_front=_construire_front(tmp_path))
    reponse = client.get("/api")
    assert reponse.status_code == 404, reponse.text
    assert "front construit" not in reponse.text


def test_un_fichier_absent_ne_recoit_pas_index_html(tmp_path: Path):
    """Un actif manquant doit valoir 404, pas `index.html` déguisé en JavaScript.

    Le cas n'est pas théorique : `vite` change l'empreinte des fichiers à
    chaque construction, et un onglet resté ouvert sur l'ancien `index.html`
    redemande un `assets/index-<ancienne empreinte>.js` qui n'existe plus.
    Avec le repli trop large, il recevait du HTML servi en 200 — une erreur de
    syntaxe muette dans la console plutôt qu'un 404 que le navigateur nomme.
    """
    client = client_api(dossier_front=_construire_front(tmp_path))
    reponse = client.get("/assets/index-ancienne-empreinte.js")
    assert reponse.status_code == 404, reponse.text
    assert "front construit" not in reponse.text


def test_une_page_du_front_sans_extension_recoit_toujours_index_html(tmp_path: Path):
    """La contre-épreuve du test ci-dessus : resserrer ne doit pas tout fermer."""
    client = client_api(dossier_front=_construire_front(tmp_path))
    for chemin in ("/entrer", "/connexion", "/reglages"):
        reponse = client.get(chemin)
        assert reponse.status_code == 200, f"{chemin} : {reponse.status_code}"
        assert "front construit" in reponse.text, chemin


def test_sans_dossier_front_la_racine_ne_sert_rien():
    """L'absence de `dossier_front` (le défaut, `ourouler api` compris) ne monte rien.

    Une route non servie rend la forme d'erreur du projet (`route_inconnue`),
    jamais un 404 nu de FastAPI ni une trace.
    """
    client = client_api()
    reponse = client.get("/")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "route_inconnue"

# --- à qui appartient le TOML du serveur (lot L7.2, corrigé le 19/09/2026) ----


def _toml_de_serveur(tmp_path: Path, extra: str = "") -> Path:
    fichier = tmp_path / "serveur.toml"
    fichier.write_text(
        '[depart]\nnom="Rennes"\nlatitude=48.1113\nlongitude=-1.68\n'
        "[cycliste]\nmasse_kg=75\nftp_w=250\n" + extra,
        encoding="utf-8",
    )
    return fichier


def test_en_heberge_le_socle_n_appartient_a_personne(tmp_path: Path, monkeypatch):
    """Un compte tout juste activé doit voir quelque chose.

    Avant le 19/09/2026, `application()` marquait le TOML du serveur comme le
    profil de « local » quel que soit le mode. Le premier cycliste invité
    entrait — session ouverte, cookie posé — et recevait sur tous les écrans
    « le socle de ce serveur est le profil de "local" et ne se partage pas ».
    Constaté en vrai, sur la première activation.
    """
    monkeypatch.setenv("OUROULER_MODE", "heberge")
    monkeypatch.setenv("OUROULER_CONFIG", str(_toml_de_serveur(tmp_path)))
    monkeypatch.setenv("OUROULER_DATABASE_URL", "postgres://personne@127.0.0.1:1/absente")
    from ourouler.api.application import application

    depot = application().state.ourouler.profils
    depot.verifier_proprietaire(Proprietaire("aba9e195930e70f7f4c9be54a5337075"))


def test_en_personnel_le_socle_reste_celui_du_mainteneur(tmp_path: Path, monkeypatch):
    """La contre-épreuve : sur sa propre machine, le fichier reste le sien.

    Sans elle, « le socle n'appartient à personne » pourrait être obtenu en le
    retirant partout, ce qui rouvrirait la fuite que le lot L7.A a fermée.
    """
    monkeypatch.setenv("OUROULER_MODE", "personnel")
    monkeypatch.setenv("OUROULER_CONFIG", str(_toml_de_serveur(tmp_path)))
    from ourouler.api.application import application

    depot = application().state.ourouler.profils
    depot.verifier_proprietaire(PROPRIETAIRE_LOCAL)
    with pytest.raises(ErreurConfig, match="ne se partage pas"):
        depot.verifier_proprietaire(Proprietaire("quelqu-un-d-autre"))


def test_en_heberge_une_cle_intervals_dans_le_socle_refuse_le_demarrage(tmp_path: Path, monkeypatch):
    """Une base commune est servie à **tout le monde** : une clé qui y traîne est distribuée.

    Refus au démarrage et non à la requête — un déploiement mal configuré doit
    échouer là où quelqu'un regarde.
    """
    monkeypatch.setenv("OUROULER_MODE", "heberge")
    monkeypatch.setenv(
        "OUROULER_CONFIG",
        str(_toml_de_serveur(tmp_path, '[intervals]\napi_key="cle-factice-de-test"\n')),
    )
    monkeypatch.setenv("OUROULER_DATABASE_URL", "postgres://personne@127.0.0.1:1/absente")
    from ourouler.api.application import application

    with pytest.raises(ErreurConfig, match="clé Intervals"):
        application()

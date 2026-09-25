"""`POST /reinitialiser`, `GET /moi`, `POST /moi/mot-de-passe` — contre le service réel (lot L9.6).

Même patron que `test_routes_session.py` et `test_vie_privee_comptes.py` : un client ASGI
local (pas de partage avec `tests/api/`, qui coupe le réseau pour son dossier), une vraie
base PostgreSQL jetable. Ce fichier prouve par HTTP ce que
`test_reinitialiser_retirer.py` prouve déjà au dépôt : que le fil qui va du navigateur au
dépôt se comporte pareil, pas seulement le dépôt isolé — la même distinction que
[[Q58]] a rendue nécessaire pour les autres routes de comptes.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from ourouler.api.application import creer_application  # noqa: E402
from ourouler.api.base_de_donnees import ouvrir  # noqa: E402
from ourouler.api.comptes import DepotComptes  # noqa: E402
from ourouler.api.depots import SocleVide  # noqa: E402
from ourouler.api.session import NOM_COOKIE, SessionParCookie  # noqa: E402

PREFIXE = "/api/v1"
MOT_DE_PASSE = "grenat-poulie-silex-marmotte"
NOUVEAU_MOT_DE_PASSE = "corbeau-lentille-etain-marmotte"


def _app(url_base: str, tmp_path):
    return creer_application(
        socle=SocleVide(), dossier_donnees=tmp_path / "donnees", session=SessionParCookie(url_base)
    )


def requete(app, methode: str, chemin: str, *, cookies=None, **kwargs) -> httpx.Response:
    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://api.test", cookies=cookies
        ) as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


def _compte_actif(url_base: str, adresse: str) -> None:
    with ouvrir(url_base) as cx:
        depot = DepotComptes(cx)
        emise = depot.inviter(adresse)
        depot.activer(emise.jeton, MOT_DE_PASSE)


def _entrer(app, adresse: str) -> dict[str, str]:
    reponse = requete(
        app, "POST", f"{PREFIXE}/connexion", json={"email": adresse, "secret": MOT_DE_PASSE}
    )
    assert reponse.status_code == 200, reponse.text
    jeton = reponse.cookies.get(NOM_COOKIE)
    assert jeton
    return {NOM_COOKIE: jeton}


# --- POST /reinitialiser --------------------------------------------------------


def test_reinitialiser_pose_le_nouveau_mot_de_passe_et_ferme_les_autres_sessions(
    url_base, tmp_path
):
    _compte_actif(url_base, "reinit-route@exemple.invalid")
    app = _app(url_base, tmp_path)

    # Une session déjà ouverte, avant l'émission du lien.
    cookies_avant = _entrer(app, "reinit-route@exemple.invalid")

    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).reinitialiser("reinit-route@exemple.invalid")

    reponse = requete(
        app,
        "POST",
        f"{PREFIXE}/reinitialiser",
        json={"jeton": emise.jeton, "secret": NOUVEAU_MOT_DE_PASSE},
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.cookies.get(NOM_COOKIE), "aucun cookie de session posé après réinitialisation"

    # L'ancienne session ne vaut plus rien...
    profil_avec_ancien_cookie = requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies_avant)
    assert profil_avec_ancien_cookie.status_code == 401

    # ... et l'ancien mot de passe non plus.
    connexion_ancien = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "reinit-route@exemple.invalid", "secret": MOT_DE_PASSE},
    )
    assert connexion_ancien.status_code == 401

    # Le nouveau, lui, ouvre une session.
    connexion_neuve = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "reinit-route@exemple.invalid", "secret": NOUVEAU_MOT_DE_PASSE},
    )
    assert connexion_neuve.status_code == 200


def test_deux_reinitialiser_avec_le_meme_jeton_le_second_est_refuse(url_base, tmp_path):
    _compte_actif(url_base, "rejoue-reinit@exemple.invalid")
    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).reinitialiser("rejoue-reinit@exemple.invalid")

    app = _app(url_base, tmp_path)
    corps = {"jeton": emise.jeton, "secret": NOUVEAU_MOT_DE_PASSE}
    premiere = requete(app, "POST", f"{PREFIXE}/reinitialiser", json=corps)
    seconde = requete(app, "POST", f"{PREFIXE}/reinitialiser", json=corps)

    assert premiere.status_code == 200, premiere.text
    assert seconde.status_code >= 400, seconde.text
    assert emise.jeton not in seconde.text


def test_reinitialiser_avec_un_jeton_invente_est_refuse_proprement(url_base, tmp_path):
    reponse = requete(
        _app(url_base, tmp_path),
        "POST",
        f"{PREFIXE}/reinitialiser",
        json={"jeton": "jeton-completement-invente", "secret": NOUVEAU_MOT_DE_PASSE},
    )
    assert 400 <= reponse.status_code < 500
    assert reponse.json()["erreur"]["code"] == "invitation_invalide"
    assert "jeton-completement-invente" not in reponse.text


# --- GET /moi ---------------------------------------------------------------


def test_get_moi_rend_l_adresse_du_compte_de_la_session(url_base, tmp_path):
    _compte_actif(url_base, "get-moi@exemple.invalid")
    app = _app(url_base, tmp_path)
    cookies = _entrer(app, "get-moi@exemple.invalid")

    reponse = requete(app, "GET", f"{PREFIXE}/moi", cookies=cookies)
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["donnees"]["email"] == "get-moi@exemple.invalid"


def test_get_moi_isole_bien_deux_comptes(url_base, tmp_path):
    """Un cas simple d'isolation par propriétaire, en plus du balayage générique."""
    _compte_actif(url_base, "compte-a@exemple.invalid")
    _compte_actif(url_base, "compte-b@exemple.invalid")
    app = _app(url_base, tmp_path)

    cookies_a = _entrer(app, "compte-a@exemple.invalid")
    cookies_b = _entrer(app, "compte-b@exemple.invalid")

    reponse_a = requete(app, "GET", f"{PREFIXE}/moi", cookies=cookies_a)
    reponse_b = requete(app, "GET", f"{PREFIXE}/moi", cookies=cookies_b)

    assert reponse_a.json()["donnees"]["email"] == "compte-a@exemple.invalid"
    assert reponse_b.json()["donnees"]["email"] == "compte-b@exemple.invalid"


def test_get_moi_sans_session_repond_401(url_base, tmp_path):
    reponse = requete(_app(url_base, tmp_path), "GET", f"{PREFIXE}/moi")
    assert reponse.status_code == 401
    assert reponse.json()["erreur"]["code"] == "session_absente"


# --- POST /moi/mot-de-passe --------------------------------------------------


def test_changer_mon_mot_de_passe_avec_le_bon_ancien(url_base, tmp_path):
    _compte_actif(url_base, "change-mdp@exemple.invalid")
    app = _app(url_base, tmp_path)
    cookies = _entrer(app, "change-mdp@exemple.invalid")

    reponse = requete(
        app,
        "POST",
        f"{PREFIXE}/moi/mot-de-passe",
        cookies=cookies,
        json={"mot_de_passe_actuel": MOT_DE_PASSE, "nouveau_mot_de_passe": NOUVEAU_MOT_DE_PASSE},
    )
    assert reponse.status_code == 200, reponse.text

    # La session en cours reste ouverte : pas de déconnexion sur ce chemin-là.
    profil = requete(app, "GET", f"{PREFIXE}/profil", cookies=cookies)
    assert profil.status_code != 401

    connexion_neuve = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "change-mdp@exemple.invalid", "secret": NOUVEAU_MOT_DE_PASSE},
    )
    assert connexion_neuve.status_code == 200


def test_changer_mon_mot_de_passe_refuse_si_l_ancien_est_faux(url_base, tmp_path):
    _compte_actif(url_base, "mauvais-ancien-route@exemple.invalid")
    app = _app(url_base, tmp_path)
    cookies = _entrer(app, "mauvais-ancien-route@exemple.invalid")

    reponse = requete(
        app,
        "POST",
        f"{PREFIXE}/moi/mot-de-passe",
        cookies=cookies,
        json={"mot_de_passe_actuel": "un-mot-de-passe-invente", "nouveau_mot_de_passe": NOUVEAU_MOT_DE_PASSE},
    )
    assert reponse.status_code == 401
    assert reponse.json()["erreur"]["code"] == "mot_de_passe_actuel_refuse"

    # L'ancien mot de passe reste valable — rien n'a bougé.
    connexion_ancien = requete(
        app,
        "POST",
        f"{PREFIXE}/connexion",
        json={"email": "mauvais-ancien-route@exemple.invalid", "secret": MOT_DE_PASSE},
    )
    assert connexion_ancien.status_code == 200


def test_changer_mon_mot_de_passe_sans_session_repond_401(url_base, tmp_path):
    reponse = requete(
        _app(url_base, tmp_path),
        "POST",
        f"{PREFIXE}/moi/mot-de-passe",
        json={"mot_de_passe_actuel": "peu-importe", "nouveau_mot_de_passe": "peu-importe-non-plus"},
    )
    assert reponse.status_code == 401
    assert reponse.json()["erreur"]["code"] == "session_absente"

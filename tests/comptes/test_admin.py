"""L'administration (`ourouler admin`) : auth dédiée, CSRF, modération, suppression.

Sprint 12. Même patron que `tests/comptes/test_cli_retirer.py` : un client ASGI
local contre une vraie base PostgreSQL jetable, et — pour la suppression d'un
compte — le même dossier de données qu'une vraie application aurait servi,
pour prouver l'effet réel (le fichier disparaît), pas seulement la forme.

Adresses de test toutes en `.invalid` (RFC 2606, règle absolue 1).
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
import pytest

from ourouler.api.admin import (
    NOM_COOKIE_ADMIN,
    ParametresApplicationAdmin,
    creer_application_admin,
)
from ourouler.api.application import NOM_DOSSIER_DONNEES, creer_application
from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.demandes import DepotDemandes
from ourouler.api.depots import DepotFichiers, SocleTOML
from ourouler.api.exploitation import ParametresAdmin
from ourouler.api.session import NOM_COOKIE, SessionParCookie

MOT_DE_PASSE = "pigeon-vaisselle-quartz-ficelle"
IDENTIFIANT_ADMIN = "amiel-essai"
SECRET_ADMIN = "un-secret-d-essai-suffisamment-long"


def _toml_partage(tmp_path: Path) -> Path:
    chemin = tmp_path / "service_partage.toml"
    chemin.write_text(
        "[depart]\n"
        'nom = "Départ d\'essai"\n'
        "latitude = 0.0009\nlongitude = 0.0004\n"
        "\n[cycliste]\nmasse_kg = 70.0\nftp_w = 200\n"
        f'\n[cache]\ndossier = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return chemin


def _requete(app, methode: str, chemin: str, *, cookies=None, **kwargs) -> httpx.Response:
    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://admin.test", cookies=cookies, follow_redirects=False
        ) as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


@pytest.fixture
def app_admin(url_base: str):
    return creer_application_admin(
        ParametresApplicationAdmin(
            url_comptes=url_base,
            identifiant=ParametresAdmin(identifiant=IDENTIFIANT_ADMIN, secret=SECRET_ADMIN),
            url_publique="https://exemple.invalid",
        )
    )


def _connecter(app_admin) -> dict[str, str]:
    reponse = _requete(
        app_admin,
        "POST",
        "/admin/connexion",
        data={"identifiant": IDENTIFIANT_ADMIN, "secret": SECRET_ADMIN},
    )
    assert reponse.status_code == 303, reponse.text
    jeton = reponse.cookies.get(NOM_COOKIE_ADMIN)
    assert jeton
    return {NOM_COOKIE_ADMIN: jeton}


def _csrf_de(page_html: str) -> str:
    trouve = re.search(r'name="csrf" value="([^"]+)"', page_html)
    assert trouve, "aucun jeton CSRF trouvé dans la page"
    return trouve.group(1)


# --- authentification ---------------------------------------------------------


def test_le_tableau_de_bord_refuse_sans_session(app_admin):
    reponse = _requete(app_admin, "GET", "/admin/")
    assert reponse.status_code == 403


def test_connexion_avec_de_mauvais_identifiants_est_refusee(app_admin):
    reponse = _requete(
        app_admin, "POST", "/admin/connexion", data={"identifiant": IDENTIFIANT_ADMIN, "secret": "faux"}
    )
    assert reponse.status_code == 401
    assert NOM_COOKIE_ADMIN not in reponse.cookies


def test_connexion_avec_les_bons_identifiants_ouvre_le_tableau_de_bord(app_admin):
    cookies = _connecter(app_admin)
    reponse = _requete(app_admin, "GET", "/admin/", cookies=cookies)
    assert reponse.status_code == 200
    assert "no-store" in reponse.headers.get("cache-control", "")


def test_deconnexion_ferme_la_session(app_admin):
    cookies = _connecter(app_admin)
    _requete(app_admin, "POST", "/admin/deconnexion", cookies=cookies)
    reponse = _requete(app_admin, "GET", "/admin/", cookies=cookies)
    assert reponse.status_code == 403


# --- CSRF ----------------------------------------------------------------------


def test_une_action_sans_jeton_csrf_est_refusee(app_admin, url_base: str):
    with ouvrir(url_base) as cx:
        demande = DepotDemandes(cx).deposer("sans-csrf@exemple.invalid", None)
    cookies = _connecter(app_admin)
    reponse = _requete(app_admin, "POST", f"/admin/demandes/{demande.id}/refuser", cookies=cookies, data={})
    assert reponse.status_code in (403, 422)  # 422 si Pydantic refuse le champ manquant, 403 sinon
    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() != []  # rien n'a été refusé


def test_une_action_avec_un_faux_jeton_csrf_est_refusee(app_admin, url_base: str):
    with ouvrir(url_base) as cx:
        demande = DepotDemandes(cx).deposer("faux-csrf@exemple.invalid", None)
    cookies = _connecter(app_admin)
    reponse = _requete(
        app_admin, "POST", f"/admin/demandes/{demande.id}/refuser", cookies=cookies, data={"csrf": "invente"}
    )
    assert reponse.status_code == 403
    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() != []


# --- modération des demandes ---------------------------------------------------


def test_accepter_une_demande_depuis_le_tableau_de_bord(app_admin, url_base: str):
    with ouvrir(url_base) as cx:
        demande = DepotDemandes(cx).deposer("accepte-admin@exemple.invalid", "un mot")
    cookies = _connecter(app_admin)
    page = _requete(app_admin, "GET", "/admin/", cookies=cookies)
    csrf = _csrf_de(page.text)

    reponse = _requete(
        app_admin, "POST", f"/admin/demandes/{demande.id}/accepter", cookies=cookies, data={"csrf": csrf}
    )
    assert reponse.status_code == 303

    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() == []
        compte = DepotComptes(cx).compte_par_email("accepte-admin@exemple.invalid")
    assert compte is not None
    assert compte.actif is False  # l'invitation est émise, pas encore consommée


def test_refuser_une_demande_ne_cree_aucun_compte(app_admin, url_base: str):
    with ouvrir(url_base) as cx:
        demande = DepotDemandes(cx).deposer("refuse-admin@exemple.invalid", None)
    cookies = _connecter(app_admin)
    csrf = _csrf_de(_requete(app_admin, "GET", "/admin/", cookies=cookies).text)

    reponse = _requete(
        app_admin, "POST", f"/admin/demandes/{demande.id}/refuser", cookies=cookies, data={"csrf": csrf}
    )
    assert reponse.status_code == 303

    with ouvrir(url_base) as cx:
        assert DepotDemandes(cx).en_attente() == []
        assert DepotComptes(cx).compte_par_email("refuse-admin@exemple.invalid") is None


def test_le_tableau_de_bord_masque_l_adresse_des_invitations_en_cours(app_admin, url_base: str):
    with ouvrir(url_base) as cx:
        DepotComptes(cx).inviter("visible-en-clair@exemple.invalid")
    cookies = _connecter(app_admin)
    page = _requete(app_admin, "GET", "/admin/", cookies=cookies)
    assert "visible-en-clair@exemple.invalid" not in page.text


# --- suppression d'un compte, avec double confirmation --------------------------


def test_supprimer_un_compte_efface_bien_les_donnees_par_le_chemin_partage(
    tmp_path: Path, url_base: str, monkeypatch: pytest.MonkeyPatch
):
    """Même preuve que `test_cli_retirer.test_retirer_efface_bien_les_donnees_par_le_chemin_partage` :
    un fichier déposé par une vraie requête HTTP doit disparaître, et la suppression exige deux clics."""
    chemin_toml = _toml_partage(tmp_path)
    dossier_cache = tmp_path / "cache"
    dossier_donnees = dossier_cache / NOM_DOSSIER_DONNEES
    marque = "sentinelle-admin-9k2"
    courriel = "supprime-moi-admin@exemple.invalid"

    socle = SocleTOML(chemin_toml, proprietaire=None)
    app = creer_application(socle=socle, dossier_donnees=dossier_donnees, session=SessionParCookie(url_base))

    with ouvrir(url_base) as cx:
        emise = DepotComptes(cx).inviter(courriel)
    entree = _requete(app, "POST", "/api/v1/entrer", json={"jeton": emise.jeton, "secret": MOT_DE_PASSE})
    assert entree.status_code == 200, entree.text
    proprietaire_id = entree.json()["donnees"]["proprietaire"]
    jeton_session = entree.cookies.get(NOM_COOKIE)

    fichier_zwo = (
        "<?xml version='1.0'?>\n<workout_file>\n"
        f"<name>{marque}</name>\n<description>essai</description>\n"
        '<workout><SteadyState Duration="600" Power="0.7"/></workout>\n'
        "</workout_file>\n"
    ).encode()
    depot_fichier = _requete(
        app,
        "POST",
        "/api/v1/seances/fichier",
        cookies={NOM_COOKIE: jeton_session},
        files={"fichier": (f"seance-{marque}.zwo", fichier_zwo, "application/xml")},
    )
    assert depot_fichier.status_code == 200, depot_fichier.text[:300]

    from ourouler.api.proprietaire import Proprietaire

    qui = Proprietaire(proprietaire_id)
    assert DepotFichiers(dossier_donnees).lister(qui), "le semis du fichier n'a pas pris"

    # --- l'administration, avec le même OUROULER_CONFIG que le serveur ---

    monkeypatch.setenv("OUROULER_CONFIG", str(chemin_toml))
    app_admin_local = creer_application_admin(
        ParametresApplicationAdmin(
            url_comptes=url_base,
            identifiant=ParametresAdmin(identifiant=IDENTIFIANT_ADMIN, secret=SECRET_ADMIN),
            url_publique="https://exemple.invalid",
        )
    )
    cookies = _connecter(app_admin_local)

    with ouvrir(url_base) as cx:
        identifiant_compte = DepotComptes(cx).compte_par_email(courriel).identifiant

    page = _requete(app_admin_local, "GET", "/admin/", cookies=cookies)
    assert courriel in page.text  # un compte actif n'est pas masqué, à la différence des invitations
    csrf = _csrf_de(page.text)

    # --- premier clic : la confirmation, rien n'est effacé encore ---

    premier_clic = _requete(
        app_admin_local,
        "POST",
        f"/admin/comptes/{identifiant_compte}/supprimer",
        cookies=cookies,
        data={"csrf": csrf},
    )
    assert premier_clic.status_code == 200
    assert "confirm" in premier_clic.text.lower()
    with ouvrir(url_base) as cx:
        assert DepotComptes(cx).compte_par_email(courriel) is not None
    assert DepotFichiers(dossier_donnees).lister(qui), "le fichier ne doit pas disparaître au premier clic"

    # --- second clic : confirmation posée, l'effacement a vraiment lieu ---

    second_clic = _requete(
        app_admin_local,
        "POST",
        f"/admin/comptes/{identifiant_compte}/supprimer",
        cookies=cookies,
        data={"csrf": csrf, "confirmation": "oui"},
    )
    assert second_clic.status_code == 303

    with ouvrir(url_base) as cx:
        assert DepotComptes(cx).compte_par_email(courriel) is None
    assert DepotFichiers(dossier_donnees).lister(qui) == [], "le fichier aurait dû disparaître"


# --- écoute locale uniquement ---------------------------------------------------


def test_la_sous_commande_admin_n_offre_aucune_option_d_hote():
    """`ourouler api` accepte `--hote` ; `ourouler admin` ne le doit jamais — rien ne doit
    pouvoir la faire écouter ailleurs que sur 127.0.0.1 (QP6)."""
    import argparse

    from ourouler.cli.admin import ajouter_admin

    parseur = argparse.ArgumentParser()
    sous = parseur.add_subparsers()
    ajouter_admin(sous)
    aide = sous.choices["admin"].format_help()
    assert "--hote" not in aide

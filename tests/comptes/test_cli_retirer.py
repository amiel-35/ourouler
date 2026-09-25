"""`ourouler retirer` : le câblage complet de `cli.py`, jusqu'au chemin RGPD partagé (lot L9.6).

Deux niveaux de preuve, comme le brief du lot le demande :

1. `test_retirer_refuse_une_adresse_sans_compte` et `test_retirer_annule_sans_confirmation`
   exercent `cli.main()` de bout en bout contre une vraie base PostgreSQL jetable, sans
   toucher au système de fichiers.
2. `test_retirer_efface_bien_les_donnees_par_le_chemin_partage` va plus loin : un compte
   est activé et dépose un fichier **par une vraie requête HTTP** (comme le ferait un
   navigateur), puis `ourouler retirer` est appelé en reconstruisant exactement les
   dépôts que le serveur hébergé utilise (`OUROULER_CONFIG`, `[cache]`) — et le test
   vérifie que le fichier a disparu du disque. C'est la preuve, demandée par le contrat,
   qu'`executer_retirer` passe bien par `vie_privee.effacer_donnees` et pas par une
   réimplémentation : un simple compteur à zéro ne le prouverait pas, un fichier qui
   disparaît vraiment le prouve.

Adresses de test en `.invalid` uniquement (RFC 2606, règle absolue 1).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.exploitation import VARIABLE_CONFIG, VARIABLE_DATABASE_URL
from ourouler.cli import main

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from ourouler.api.application import NOM_DOSSIER_DONNEES, creer_application  # noqa: E402
from ourouler.api.depots import DepotFichiers, SocleTOML  # noqa: E402
from ourouler.api.session import NOM_COOKIE, SessionParCookie  # noqa: E402

CONFIG_CYCLISTE = (
    '[depart]\nnom="Test"\nlatitude=48.0\nlongitude=2.0\n'
    '[cycliste]\nmasse_kg=75\nftp_w=250\nprenom="Cycliste"\nnom="Essai"\n'
)
MOT_DE_PASSE = "pigeon-vaisselle-quartz-ficelle"

#: L'adresse synthétique de ce fichier, et la sentinelle du fichier déposé.
COURRIEL = "retire-moi@exemple.invalid"
MARQUE = "sentinelle-retirer-9k2"


def _toml_partage(tmp_path: Path) -> Path:
    """Le TOML partagé du serveur hébergé — même forme que `tests/comptes/test_vie_privee_comptes.py`."""
    chemin = tmp_path / "service_partage.toml"
    chemin.write_text(
        "[depart]\n"
        "nom = \"Départ d'essai\"\n"
        "latitude = 0.0009\nlongitude = 0.0004\n"
        "\n[cycliste]\nmasse_kg = 70.0\nftp_w = 200\n"
        f"\n[cache]\ndossier = \"{tmp_path / 'cache'}\"\n",
        encoding="utf-8",
    )
    return chemin


@pytest.fixture
def config_toml(tmp_path: Path) -> Path:
    fichier = tmp_path / "config_cycliste.toml"
    fichier.write_text(CONFIG_CYCLISTE, encoding="utf-8")
    return fichier


@pytest.fixture(autouse=True)
def environnement_base(monkeypatch: pytest.MonkeyPatch, url_base: str) -> None:
    monkeypatch.setenv(VARIABLE_DATABASE_URL, url_base)


def test_retirer_refuse_une_adresse_sans_compte(
    config_toml: Path, capsys, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(VARIABLE_CONFIG, str(_toml_partage(tmp_path)))
    code = main(["--config", str(config_toml), "retirer", "personne@exemple.invalid", "--oui"])
    assert code == 2
    erreur = capsys.readouterr().err
    assert "n'a pas de compte" in erreur
    assert "Traceback" not in erreur


def test_retirer_annule_sans_confirmation(
    config_toml: Path, capsys, tmp_path: Path, url_base: str, monkeypatch: pytest.MonkeyPatch
):
    """Sans `--oui`, `retirer` demande confirmation — une réponse négative n'efface rien."""
    monkeypatch.setenv(VARIABLE_CONFIG, str(_toml_partage(tmp_path)))
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("hesitant@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    # `main()` n'expose pas `demander_confirmation` (c'est `executer_retirer`, appelé plus
    # bas dans la pile, qui l'accepte) : ce test-ci passe donc par le vrai `input()`,
    # remplacé pour ne jamais bloquer sur une entrée standard pendant la suite.
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "non")

    code = main(["--config", str(config_toml), "retirer", "hesitant@exemple.invalid"])
    assert code == 1
    erreur = capsys.readouterr().err
    assert "annulé" in erreur

    with ouvrir(url_base) as connexion:
        restant = connexion.execute(
            "SELECT count(*) FROM comptes WHERE lower(email) = %s", ("hesitant@exemple.invalid",)
        ).fetchone()[0]
    assert restant == 1, "le compte ne doit pas avoir été touché"


def _requete_http(app, methode: str, chemin: str, *, cookies=None, **kwargs) -> httpx.Response:
    async def _aller() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://api.test", cookies=cookies
        ) as client:
            return await client.request(methode, chemin, **kwargs)

    return asyncio.run(_aller())


def test_retirer_efface_bien_les_donnees_par_le_chemin_partage(
    tmp_path: Path, url_base: str, monkeypatch: pytest.MonkeyPatch, capsys
):
    """`ourouler retirer` doit suivre `vie_privee.effacer_donnees`, pas le réimplémenter.

    Preuve symétrique à `tests/comptes/test_vie_privee_comptes.py` côté `DELETE /moi` :
    un fichier déposé par une vraie requête HTTP doit avoir disparu du disque une fois
    `retirer` passé — pas seulement un compteur à zéro qu'une commande bâclée pourrait
    rendre sans avoir rien effacé.
    """
    chemin_toml = _toml_partage(tmp_path)
    dossier_cache = tmp_path / "cache"
    dossier_donnees = dossier_cache / NOM_DOSSIER_DONNEES

    # --- une vraie requête HTTP : invitation, activation, dépôt d'un fichier ---

    socle = SocleTOML(chemin_toml, proprietaire=None)
    app = creer_application(
        socle=socle, dossier_donnees=dossier_donnees, session=SessionParCookie(url_base)
    )

    with ouvrir(url_base) as connexion:
        emise = DepotComptes(connexion).inviter(COURRIEL)

    entree = _requete_http(
        app, "POST", "/api/v1/entrer", json={"jeton": emise.jeton, "secret": MOT_DE_PASSE}
    )
    assert entree.status_code == 200, entree.text
    proprietaire_id = entree.json()["donnees"]["proprietaire"]
    jeton_session = entree.cookies.get(NOM_COOKIE)
    assert jeton_session

    fichier_zwo = (
        "<?xml version='1.0'?>\n<workout_file>\n"
        f"<name>{MARQUE}</name>\n<description>essai</description>\n"
        '<workout><SteadyState Duration="600" Power="0.7"/></workout>\n'
        "</workout_file>\n"
    ).encode()
    depot_fichier = _requete_http(
        app,
        "POST",
        "/api/v1/seances/fichier",
        cookies={NOM_COOKIE: jeton_session},
        files={"fichier": (f"seance-{MARQUE}.zwo", fichier_zwo, "application/xml")},
    )
    assert depot_fichier.status_code == 200, depot_fichier.text[:300]

    fichiers = DepotFichiers(dossier_donnees)
    from ourouler.api.proprietaire import Proprietaire

    qui = Proprietaire(proprietaire_id)
    assert fichiers.lister(qui), "le semis du fichier n'a pas pris : le test ne prouverait rien"

    # --- ourouler retirer, avec les mêmes dépôts que le serveur hébergé ---

    monkeypatch.setenv(VARIABLE_DATABASE_URL, url_base)
    monkeypatch.setenv(VARIABLE_CONFIG, str(chemin_toml))
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "oui")

    config_toml_cli = tmp_path / "config_cycliste.toml"
    config_toml_cli.write_text(CONFIG_CYCLISTE, encoding="utf-8")

    code = main(["--config", str(config_toml_cli), "retirer", COURRIEL])
    assert code == 0, capsys.readouterr().err

    # --- le fichier a bien disparu, et le compte avec lui ---

    fichiers_relus = DepotFichiers(dossier_donnees)
    assert fichiers_relus.lister(qui) == [], "le fichier déposé aurait dû disparaître"

    with ouvrir(url_base) as connexion:
        restant = connexion.execute(
            "SELECT count(*) FROM comptes WHERE lower(email) = %s", (COURRIEL,)
        ).fetchone()[0]
    assert restant == 0

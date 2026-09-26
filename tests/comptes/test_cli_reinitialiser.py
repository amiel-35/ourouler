"""`ourouler reinitialiser` : le câblage complet de `cli.py` (lot L9.6).

Même patron que `test_cli_inviter.py` — `cli.main()` de bout en bout, contre une vraie
base PostgreSQL jetable (fixture `url_base`). Sans Docker, ces tests sautent proprement.

**Aucun courriel n'est envoyé ici** (même règle qu'`inviter`) : tous les appels passent
`--sans-courriel`, l'envoi réel étant couvert ailleurs (`tests/api/test_courriel.py`).

Adresses de test en `.invalid` uniquement (RFC 2606, règle absolue 1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ourouler.api.base_de_donnees import ouvrir
from ourouler.api.comptes import DepotComptes
from ourouler.api.exploitation import VARIABLE_DATABASE_URL
from ourouler.cli import VARIABLE_URL_PUBLIQUE, main

CONFIG = (
    '[depart]\nnom="Test"\nlatitude=48.0\nlongitude=2.0\n'
    '[cycliste]\nmasse_kg=75\nftp_w=250\nprenom="Cycliste"\nnom="Essai"\n'
)

MOT_DE_PASSE = "pigeon-vaisselle-quartz-ficelle"
URL_PUBLIQUE = "https://ourouler.exemple.invalid"


@pytest.fixture
def config_toml(tmp_path: Path) -> Path:
    fichier = tmp_path / "config.toml"
    fichier.write_text(CONFIG, encoding="utf-8")
    return fichier


@pytest.fixture(autouse=True)
def environnement_hebergement(monkeypatch: pytest.MonkeyPatch, url_base: str) -> None:
    monkeypatch.setenv(VARIABLE_DATABASE_URL, url_base)
    monkeypatch.setenv(VARIABLE_URL_PUBLIQUE, URL_PUBLIQUE)


def test_reinitialiser_refuse_une_adresse_sans_compte_actif(config_toml: Path, capsys):
    code = main(
        [
            "--config",
            str(config_toml),
            "reinitialiser",
            "jamais-invite@exemple.invalid",
            "--sans-courriel",
        ]
    )
    assert code == 2
    erreur = capsys.readouterr().err
    assert "n'a pas de compte" in erreur
    assert "Traceback" not in erreur


def test_reinitialiser_affiche_le_lien_pour_un_compte_actif(config_toml: Path, capsys, url_base: str):
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("actif@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    code = main(["--config", str(config_toml), "reinitialiser", "actif@exemple.invalid", "--sans-courriel"])
    assert code == 0
    sortie = capsys.readouterr().out
    assert f"{URL_PUBLIQUE}/reinitialiser?jeton=" in sortie
    assert "valable jusqu'au" in sortie


def test_reinitialiser_json_porte_le_lien_reinitialiser(config_toml: Path, capsys, url_base: str):
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("json@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    code = main(
        [
            "--config",
            str(config_toml),
            "reinitialiser",
            "json@exemple.invalid",
            "--sans-courriel",
            "--json",
        ]
    )
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["lien"].startswith(f"{URL_PUBLIQUE}/reinitialiser?jeton=")


def test_reinitialiser_deux_fois_de_suite_reprend_le_meme_lien(config_toml: Path, capsys, url_base: str):
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("relance@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    main(["--config", str(config_toml), "reinitialiser", "relance@exemple.invalid", "--sans-courriel"])
    premiere = capsys.readouterr().out
    main(["--config", str(config_toml), "reinitialiser", "relance@exemple.invalid", "--sans-courriel"])
    seconde = capsys.readouterr().out

    premier_lien = next(ligne for ligne in premiere.splitlines() if "reinitialiser?jeton=" in ligne)
    second_lien = next(ligne for ligne in seconde.splitlines() if "reinitialiser?jeton=" in ligne)
    assert premier_lien == second_lien
    assert "déjà en cours" in seconde


def test_reinitialiser_marche_avec_un_toml_hebergement_sans_depart_ni_cycliste(
    capsys, tmp_path: Path, url_base: str
):
    """Même constat qu'`inviter` (25/09/2026) : un TOML hébergé sans [depart] ni
    [cycliste] (Q66a) doit suffire — `reinitialiser` ne s'en sert pas non plus."""
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("hebergement@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    config_toml_hebergement = tmp_path / "hebergement.toml"
    config_toml_hebergement.write_text("[meteo]\ndirections=8\n", encoding="utf-8")

    code = main(
        [
            "--config",
            str(config_toml_hebergement),
            "reinitialiser",
            "hebergement@exemple.invalid",
            "--sans-courriel",
        ]
    )
    sortie = capsys.readouterr()
    assert code == 0, sortie.err
    assert f"{URL_PUBLIQUE}/reinitialiser?jeton=" in sortie.out

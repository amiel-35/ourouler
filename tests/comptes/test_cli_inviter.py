"""`ourouler inviter` / `ourouler invitations` : le câblage complet de `cli.py`.

Contrairement à `tests/api/test_invitation_commande.py` (un double de `DepotComptes`,
aucune base), ce fichier exerce `cli.main()` de bout en bout, avec une vraie base
PostgreSQL jetable (fixture `url_base` de ce dossier). Sans Docker, ces tests sautent
proprement — voir `conftest.py`.

**Aucun courriel n'est envoyé ici** (règle absolue 4 du lot) : tous les appels passent
`--sans-courriel`, ce qui évite à `_commande_inviter` de charger `service.toml` — donc de
réclamer un vrai relais SMTP. L'envoi réel, contre un double, est déjà couvert par
`tests/api/test_courriel.py` et `tests/api/test_invitation_commande.py`.

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
    '[cycliste]\nmasse_kg=75\nftp_w=250\nprenom="Amiel"\nnom="Test"\n'
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
    """Pose les deux variables que `_commande_inviter`/`_commande_invitations` réclament.

    `url_base` (conftest.py) déclenche le saut propre sans Docker : les tests de ce
    fichier héritent donc de ce comportement sans avoir à le redire.
    """
    monkeypatch.setenv(VARIABLE_DATABASE_URL, url_base)
    monkeypatch.setenv(VARIABLE_URL_PUBLIQUE, URL_PUBLIQUE)


def test_inviter_affiche_le_lien_et_l_echeance_meme_sans_courriel(config_toml: Path, capsys):
    code = main(
        ["--config", str(config_toml), "inviter", "cycliste@exemple.invalid", "--sans-courriel"]
    )
    assert code == 0
    sortie = capsys.readouterr().out
    assert f"{URL_PUBLIQUE}/entrer?jeton=" in sortie
    assert "valable jusqu'au" in sortie
    assert "courriel non envoyé" in sortie


def test_inviter_deux_fois_de_suite_reprend_le_meme_jeton(config_toml: Path, capsys):
    main(["--config", str(config_toml), "inviter", "relance@exemple.invalid", "--sans-courriel"])
    premiere_sortie = capsys.readouterr().out
    main(["--config", str(config_toml), "inviter", "relance@exemple.invalid", "--sans-courriel"])
    seconde_sortie = capsys.readouterr().out

    premier_lien = next(ligne for ligne in premiere_sortie.splitlines() if "entrer?jeton=" in ligne)
    second_lien = next(ligne for ligne in seconde_sortie.splitlines() if "entrer?jeton=" in ligne)
    assert premier_lien == second_lien, "le jeton doit être le même à l'émission et à la reprise"
    assert "déjà en cours" in seconde_sortie


def test_inviter_un_compte_deja_actif_echoue_avec_code_2_et_sans_trace(
    config_toml: Path, capsys, url_base: str
):
    with ouvrir(url_base) as connexion:
        depot = DepotComptes(connexion)
        emise = depot.inviter("active@exemple.invalid")
        depot.activer(emise.jeton, MOT_DE_PASSE)

    code = main(
        ["--config", str(config_toml), "inviter", "active@exemple.invalid", "--sans-courriel"]
    )
    assert code == 2
    erreur = capsys.readouterr().err
    assert "a déjà un compte" in erreur
    assert "Traceback" not in erreur


def test_inviter_json_porte_le_lien_et_l_etat(config_toml: Path, capsys):
    code = main(
        [
            "--config",
            str(config_toml),
            "inviter",
            "json@exemple.invalid",
            "--sans-courriel",
            "--json",
        ]
    )
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["lien"].startswith(f"{URL_PUBLIQUE}/entrer?jeton=")
    assert sortie["deja_en_cours"] is False
    assert sortie["courriel_envoye"] is False


def test_invitations_liste_ce_qui_vient_d_etre_invite(config_toml: Path, capsys):
    main(["--config", str(config_toml), "inviter", "listee@exemple.invalid", "--sans-courriel"])
    capsys.readouterr()  # on ne garde pas la sortie d'`inviter`

    code = main(["--config", str(config_toml), "invitations"])
    assert code == 0
    sortie = capsys.readouterr().out
    assert "listee@exemple.invalid" in sortie
    assert "entrer?jeton=" in sortie
    assert "valable jusqu'au" in sortie


def test_invitations_json(config_toml: Path, capsys):
    main(["--config", str(config_toml), "inviter", "json2@exemple.invalid", "--sans-courriel"])
    capsys.readouterr()

    code = main(["--config", str(config_toml), "invitations", "--json"])
    assert code == 0
    sortie = json.loads(capsys.readouterr().out)
    adresses = [i["adresse"] for i in sortie]
    assert "json2@exemple.invalid" in adresses
    entree = next(i for i in sortie if i["adresse"] == "json2@exemple.invalid")
    assert entree["lien"].startswith(f"{URL_PUBLIQUE}/entrer?jeton=")


def test_invitations_sans_rien_en_cours_le_dit_sans_planter(config_toml: Path, capsys):
    code = main(["--config", str(config_toml), "invitations"])
    assert code == 0
    assert "aucune invitation" in capsys.readouterr().out


def test_le_jeton_n_apparait_dans_aucun_journal(config_toml: Path, capsys, caplog):
    with caplog.at_level("DEBUG"):
        main(
            [
                "--config",
                str(config_toml),
                "inviter",
                "journal@exemple.invalid",
                "--sans-courriel",
            ]
        )
    sortie = capsys.readouterr().out
    lien = next(ligne for ligne in sortie.splitlines() if "entrer?jeton=" in ligne)
    jeton = lien.rsplit("jeton=", 1)[1]
    assert jeton, "le test ne prouve rien s'il n'a pas trouvé de jeton dans la sortie"
    assert all(jeton not in enregistrement.getMessage() for enregistrement in caplog.records)

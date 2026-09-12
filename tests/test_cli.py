"""Tests de la CLI (L1.1)."""

import json
from pathlib import Path

import pytest

from ourouler.cli import construire_parseur, main

CONFIG = '[depart]\nnom="Test"\nlatitude=0.0\nlongitude=0.0\n[cycliste]\nmasse_kg=80\nftp_w=250\n'


def test_sans_commande_affiche_aide(capsys):
    assert main([]) == 0
    assert "meteo" in capsys.readouterr().out


def test_config_affiche(tmp_path: Path, capsys):
    f = tmp_path / "c.toml"
    f.write_text(CONFIG, encoding="utf-8")
    assert main(["--config", str(f), "config"]) == 0
    out = capsys.readouterr().out
    assert "Test" in out and "non renseigné" in out


def test_config_absente_code_2(tmp_path: Path, capsys):
    assert main(["--config", str(tmp_path / "x.toml"), "config"]) == 2
    assert "introuvable" in capsys.readouterr().err


# --- --json avant ou après la sous-commande ---------------------------------
#
# Tests qui auraient attrapé A3 : `--json` n'était déclaré qu'en option
# globale, et `ourouler meteo --json` — la forme écrite au contrat de sprint
# §4 — répondait « unrecognized arguments: --json ».


@pytest.mark.parametrize(
    "commande",
    ["config", "inventaire", "meteo", "boucle"],
    ids=lambda c: c,
)
@pytest.mark.parametrize("place", ["avant", "apres"], ids=lambda p: f"--json {p}")
def test_json_accepte_avant_et_apres_la_sous_commande(commande: str, place: str):
    """Le parseur doit accepter les deux formes, avec le même `dest`."""
    parseur = construire_parseur()
    argv = ["--json", commande] if place == "avant" else [commande, "--json"]
    args = parseur.parse_args(argv)
    assert args.json is True, f"{' '.join(argv)} : --json non pris en compte"
    assert args.commande == commande


@pytest.mark.parametrize("commande", ["config", "inventaire", "meteo", "boucle"])
def test_sans_json_la_sortie_reste_en_texte(commande: str):
    """Le sous-parseur ne doit pas non plus forcer `--json` à vrai."""
    assert construire_parseur().parse_args([commande]).json is False


def test_json_apres_la_sous_commande_avec_d_autres_options():
    args = construire_parseur().parse_args(["meteo", "--horizon", "3", "--json"])
    assert args.json is True and args.horizon == 3


def test_json_global_n_est_pas_ecrase_par_le_defaut_du_sous_parseur():
    """Le piège d'argparse : sans `default=SUPPRESS`, le sous-parseur remet False."""
    args = construire_parseur().parse_args(["--json", "meteo", "--horizon", "3"])
    assert args.json is True


def test_json_rend_bien_du_json_sur_la_sous_commande_config(tmp_path: Path, capsys):
    """De bout en bout : la forme `config --json` doit produire du JSON analysable."""
    f = tmp_path / "c.toml"
    f.write_text(CONFIG, encoding="utf-8")
    assert main(["--config", str(f), "config", "--json"]) == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["depart"]["nom"] == "Test"
    assert charge["intervals"]["api_key"] == "", "aucune clé renseignée ici"


def test_une_option_vraiment_inconnue_reste_refusee(capsys):
    """On n'a pas ouvert la porte à n'importe quelle option après la sous-commande."""
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["meteo", "--jsonn"])
    assert "unrecognized arguments" in capsys.readouterr().err


# --- état des connecteurs dans `ourouler config` (L2.1) ----------------------

MOT_DE_PASSE_CLI = "secret-de-test-cli"
CONFIG_BROUTER = (
    CONFIG
    + '[brouter]\nurl="https://brouter.exemple.test"\nutilisateur="u"\n'
    + f'mot_de_passe="{MOT_DE_PASSE_CLI}"\nprofil="gravel"\n'
)


def _config(tmp_path: Path, contenu: str) -> Path:
    f = tmp_path / "c.toml"
    f.write_text(contenu, encoding="utf-8")
    return f


def test_config_affiche_brouter_renseigne_avec_son_url(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config"]) == 0
    out = capsys.readouterr().out
    assert "BRouter  : renseigné" in out
    assert "https://brouter.exemple.test" in out, "l'URL n'est pas un secret"
    assert "gravel" in out


def test_config_affiche_brouter_non_renseigne(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG)), "config"]) == 0
    assert "BRouter  : non renseigné" in capsys.readouterr().out


def test_le_mot_de_passe_brouter_n_est_jamais_affiche(tmp_path: Path, capsys):
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config"]) == 0
    assert MOT_DE_PASSE_CLI not in capsys.readouterr().out


def test_le_mot_de_passe_brouter_est_masque_en_json(tmp_path: Path, capsys):
    """`dataclasses.asdict` ignore le `repr` masquant : il faut masquer ici aussi."""
    assert main(["--config", str(_config(tmp_path, CONFIG_BROUTER)), "config", "--json"]) == 0
    sortie = capsys.readouterr().out
    assert MOT_DE_PASSE_CLI not in sortie
    assert json.loads(sortie)["brouter"]["mot_de_passe"] == "***"
    assert json.loads(sortie)["brouter"]["url"] == "https://brouter.exemple.test"

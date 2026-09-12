"""Tests de la CLI (L1.1)."""

from pathlib import Path

from ourouler.cli import main

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

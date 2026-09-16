"""Tests du point d'entrée unique `seance.fichier.lire_fichier_seance` (F1, C1).

Vérifie seulement le **dispatch par extension** — `.ZWO` et `.MRC` ont chacun
leurs propres tests (`test_seance_zwo.py`, `test_seance_mrc.py`). Toutes les
séances sont fabriquées pour ce test, aucune ne vient d'un compte réel.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ourouler.erreurs import ErreurLecture
from ourouler.seance.fichier import EXTENSIONS, lire_fichier_seance

JOUR = date(2026, 9, 16)
FTP = 200.0  # inventée

ZWO = (
    "<?xml version='1.0'?>\n<workout_file>\n<name>4x8 fabriquée</name>\n"
    '<workout><SteadyState Duration="480" Power="0.9"/></workout>\n'
    "</workout_file>\n"
)

MRC = (
    "[COURSE HEADER]\nMINUTES PERCENT\n[END COURSE HEADER]\n"
    "[COURSE DATA]\n0.0\t50\n8.0\t50\n8.0\t90\n16.0\t90\n[END COURSE DATA]\n"
)


def _ecrire(tmp_path: Path, nom: str, contenu: str) -> Path:
    chemin = tmp_path / nom
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_zwo_est_delegue_a_lire_zwo(tmp_path: Path):
    chemin = _ecrire(tmp_path, "seance.zwo", ZWO)
    seance = lire_fichier_seance(chemin, ftp_w=FTP, jour=JOUR)
    assert seance.meta["source"] == "zwo"
    assert seance.nom == "4x8 fabriquée"
    assert seance.jour == JOUR


def test_mrc_est_delegue_a_lire_mrc(tmp_path: Path):
    chemin = _ecrire(tmp_path, "seance.mrc", MRC)
    seance = lire_fichier_seance(chemin, ftp_w=FTP, jour=JOUR)
    assert seance.meta["source"] == "mrc"
    assert seance.jour == JOUR


def test_extension_insensible_a_la_casse(tmp_path: Path):
    chemin = _ecrire(tmp_path, "seance.ZWO", ZWO)
    seance = lire_fichier_seance(chemin, ftp_w=FTP, jour=JOUR)
    assert seance.meta["source"] == "zwo"


def test_seuil_recuperation_est_transmis_au_mrc(tmp_path: Path):
    """Un seuil très bas fait passer toute la séance en blocs — preuve qu'il a
    bien été transmis à `lire_mrc` et non ignoré."""
    chemin = _ecrire(tmp_path, "seance.mrc", MRC)
    seance = lire_fichier_seance(chemin, ftp_w=FTP, seuil_recuperation_pct=0.01, jour=JOUR)
    assert all(e.type == "bloc" for e in seance.etapes)


def test_extension_inconnue_est_refusee(tmp_path: Path):
    chemin = _ecrire(tmp_path, "seance.fit", "peu importe")
    with pytest.raises(ErreurLecture, match="inconnue"):
        lire_fichier_seance(chemin, ftp_w=FTP, jour=JOUR)


def test_fichier_absent_leve_erreur_lecture(tmp_path: Path):
    with pytest.raises(ErreurLecture):
        lire_fichier_seance(tmp_path / "absent.zwo", ftp_w=FTP, jour=JOUR)


def test_extensions_couvre_zwo_et_mrc():
    assert set(EXTENSIONS) == {"zwo", "mrc"}

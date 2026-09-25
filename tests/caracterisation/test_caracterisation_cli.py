"""Filet 0b : les sorties de référence de la ligne de commande.

Chaque scénario lance `ourouler.cli.main([...])` — **la surface publique**, pas
une fonction `executer` que les lots de restructuration vont déplacer — avec
`--json`, un fichier de configuration synthétique écrit dans `tmp_path`, le
réseau rejoué et l'horloge figée (`outils_caracterisation`). Ce qui est figé :
le code de sortie, la sortie standard JSON, la sortie d'erreur, les fichiers
écrits et le journal des appels aux services.

Une différence avec la référence est **un changement de comportement** : elle
se relit, puis se régénère par
`uv run pytest tests/caracterisation --regenerer-golden`.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from outils_caracterisation import (
    DOSSIER,
    JOUR,
    arrondir,
    comparer_a_la_reference,
    ecrire_config,
    garde_reseau,  # noqa: F401 — fixture autouse : la garde réseau de ce module
    normaliser,
    preparer,
)

from ourouler.cli import main

pytestmark = pytest.mark.usefixtures("fuseau_de_paris")

REGENERER = "`uv run pytest tests/caracterisation --regenerer-golden`"

class Scene:
    """Un dossier de travail, une configuration, le réseau rejoué et l'horloge figée."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        self.racine = tmp_path
        self.travail = tmp_path / "travail"
        self.travail.mkdir()
        self.cache = tmp_path / "cache"
        self.config = ecrire_config(tmp_path / "config.toml", self.cache)
        monkeypatch.chdir(self.travail)
        self.rejeu = preparer(monkeypatch)
        self.capsys = capsys

    def lancer(self, *argv: str) -> dict[str, Any]:
        """Lance la commande, rend ce qui est figé — code, sorties, fichiers, réseau."""
        self.capsys.readouterr()
        self.rejeu.journal.clear()
        avant = self._fichiers()
        code = main(["--config", str(self.config), *argv])
        sortie, erreur = self.capsys.readouterr()
        try:
            stdout: Any = json.loads(sortie) if sortie.strip() else None
        except ValueError:
            stdout = sortie
        resultat = {
            "argv": list(argv),
            "code": code,
            "stdout": stdout,
            "stderr": erreur,
            "fichiers_ecrits": {
                nom: empreinte for nom, empreinte in self._fichiers().items() if nom not in avant
            },
            "reseau": sorted(self.rejeu.journal),
        }
        return normaliser(resultat, self.remplacements())

    def remplacements(self) -> dict[str, str]:
        racine = str(self.racine)
        return {racine: "<TMP>", os.path.realpath(racine): "<TMP>"}

    def _fichiers(self) -> dict[str, str]:
        """Les GPX et les cartes HTML écrits, où qu'ils soient (dossier de
        travail ou `cache/sorties/`), par chemin relatif.

        Un GPX est figé par son empreinte (la géométrie retenue est un
        comportement) ; une carte HTML seulement par sa présence — elle
        embarque des bibliothèques et une mise en page qui ne sont pas le
        sujet de ce filet.
        """
        trouves = {}
        for chemin in sorted(self.racine.rglob("*")):
            suffixe = chemin.suffix.lower()
            if not chemin.is_file() or suffixe not in (".gpx", ".html"):
                continue
            nom = chemin.relative_to(self.racine).as_posix()
            if suffixe == ".gpx":
                trouves[nom] = "sha256:" + hashlib.sha256(chemin.read_bytes()).hexdigest()[:16]
            else:
                trouves[nom] = "présent"
        return trouves


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Scene:
    return Scene(tmp_path, monkeypatch, capsys)


def verifier(nom: str, obtenu: Any, regenerer_golden: bool) -> None:
    comparer_a_la_reference(obtenu, DOSSIER / f"cli_{nom}.json", regenerer_golden, REGENERER)


# --- historique synthétique : deux vélos, huit sorties chacun ------------------


def ecrire_historique(dossier: Path) -> Path:
    """Huit sorties plates de RCR en janvier, huit de BMC en février, en TCX.

    Fabriquées par le modèle physique lui-même (`test_physique_calibration.
    sortie_synthetique`), plein est depuis (0, 0) : la calibration a une
    réponse connue, la comparaison deux CdA distincts à départager.
    """
    from test_physique_calibration import VRAI, sortie_synthetique
    from test_physique_commande import _en_tcx

    from ourouler.physique.modele import Parametres

    clm = Parametres(masse_totale_kg=VRAI.masse_totale_kg, cda_m2=0.26, crr=VRAI.crr)
    dossier.mkdir(parents=True, exist_ok=True)
    for mois, parametres in ((1, VRAI), (2, clm)):
        for jour in range(1, 9):
            quand = date(2026, mois, jour)
            activite = sortie_synthetique(parametres, duree_s=2600)
            (dossier / f"sortie_{quand.isoformat()}.tcx").write_bytes(_en_tcx(activite, quand))
    return dossier


# --- les scénarios ---------------------------------------------------------------


def test_meteo(scene: Scene, regenerer_golden: bool):
    obtenu = scene.lancer("meteo", "--json", "--heure-depart", f"{JOUR}T09:00")
    verifier("meteo", obtenu, regenerer_golden)


def test_boucle(scene: Scene, regenerer_golden: bool):
    obtenu = scene.lancer(
        "boucle", "--json", "--distance", "30", "--heure-depart", f"{JOUR}T09:00"
    )
    verifier("boucle", obtenu, regenerer_golden)


def test_sortie(scene: Scene, regenerer_golden: bool):
    obtenu = scene.lancer("sortie", "--json", "--jour", JOUR, "--heure-depart", "09:00")
    verifier("sortie", obtenu, regenerer_golden)


def test_seance(scene: Scene, regenerer_golden: bool):
    obtenu = {
        "jour_avec_seance": scene.lancer("seance", "--json", "--jour", JOUR),
        "jour_sans_seance": scene.lancer("seance", "--json", "--jour", "2026-09-09"),
    }
    verifier("seance", obtenu, regenerer_golden)


def test_inventaire(scene: Scene, regenerer_golden: bool):
    historique = ecrire_historique(scene.racine / "historique")
    obtenu = {
        "import": scene.lancer("inventaire", "--json", "--importer", str(historique)),
        "relecture": scene.lancer("inventaire", "--json"),
    }
    verifier("inventaire", obtenu, regenerer_golden)


#: Chiffres significatifs gardés pour `calibrer` : l'ajustement passe par
#: numpy (moindres carrés), dont le dernier chiffre dépend de la bibliothèque
#: d'algèbre linéaire de la machine. Six chiffres gardent visible toute dérive
#: qui compte (un CdA qui bouge de 0,0001 m² sur 0,31 en change le quatrième).
CHIFFRES_CALIBRER = 6


def test_calibrer(scene: Scene, regenerer_golden: bool):
    historique = ecrire_historique(scene.racine / "historique")
    scene.lancer("inventaire", "--importer", str(historique))
    obtenu = scene.lancer("calibrer", "--json", "--velo", "RCR")
    verifier("calibrer", arrondir(obtenu, CHIFFRES_CALIBRER), regenerer_golden)


def test_comparer(scene: Scene, regenerer_golden: bool):
    historique = ecrire_historique(scene.racine / "historique")
    scene.lancer("inventaire", "--importer", str(historique))
    obtenu = scene.lancer("comparer", "--json", "--velos", "RCR", "BMC", "--zone", "0.85", "0.99")
    verifier("comparer", obtenu, regenerer_golden)


def test_refus(scene: Scene, regenerer_golden: bool):
    """Les refus : code 2, message en français sur la sortie d'erreur, aucun appel."""
    obtenu = {
        "boucle_distance_negative": scene.lancer("boucle", "--json", "--distance", "-5"),
        "sortie_jour_impossible": scene.lancer("sortie", "--json", "--jour", "2026-02-31"),
        "seance_jour_illisible": scene.lancer("seance", "--json", "--jour", "demain"),
        "comparer_meme_velo": scene.lancer("comparer", "--json", "--velos", "RCR", "rcr"),
        "calibrer_velo_inconnu": scene.lancer("calibrer", "--json", "--velo", "Tandem"),
    }
    verifier("refus", obtenu, regenerer_golden)


def test_la_garde_reseau_est_active():
    """La garde est une fixture importée, pas un `conftest.py` : vérifier qu'elle mord."""
    import socket

    from outils_caracterisation import ReseauInterdit

    with pytest.raises(ReseauInterdit):
        socket.create_connection(("exemple.invalid", 80))


def test_l_horloge_est_bien_figee(scene: Scene):
    """Sans ce contrôle, une référence pourrait dépendre du jour où on la lance."""
    from ourouler.seance import commande as seance_commande
    from ourouler.sortie import commande as sortie_commande

    assert sortie_commande.date.today() == date(2026, 9, 8)
    assert seance_commande.date.today() == date(2026, 9, 8)
    assert isinstance(date(2020, 1, 1), sortie_commande.date), "isinstance doit tenir"
    assert datetime.now(UTC).year >= 2026  # la vraie horloge, hors du paquet, n'est pas touchée

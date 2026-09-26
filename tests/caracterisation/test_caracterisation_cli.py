"""Filet 0b : les sorties de référence de la ligne de commande.

Chaque scénario lance `ourouler.cli.main([...])` — **la surface publique**, pas
une fonction `executer` que les lots de restructuration vont déplacer — deux
fois : avec `--json`, puis sans (le texte que lit le cycliste), avec un
fichier de configuration synthétique écrit dans `tmp_path`, le réseau rejoué
et l'horloge figée (`outils_caracterisation`). Ce qui est figé : le code de
sortie, la sortie standard (JSON relu, ou texte ligne à ligne), la sortie
d'erreur, les fichiers écrits (empreintes) et le journal des appels aux
services.

Une différence avec la référence est **un changement de comportement** : elle
se relit, puis se régénère par
`uv run pytest tests/caracterisation --regenerer-golden`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from donnees_synthetiques import ecrire_historique
from outils_caracterisation import (
    DOSSIER,
    JOUR,
    arrondir,
    comparer_a_la_reference,
    ecrire_config,
    garde_reseau,  # noqa: F401 — fixture autouse : la garde réseau de ce module
    horloges_reelles_restantes,
    normaliser,
    preparer,
)

from ourouler.cli import main

_VRAIE_DATE = date

pytestmark = pytest.mark.usefixtures("fuseau_de_paris")

REGENERER = "`uv run pytest tests/caracterisation --regenerer-golden`"

#: La ligne de la carte HTML qui porte l'heure de génération, **retirée**
#: avant l'empreinte : `<p class="horodatage">Page générée le 08/09/2026 à
#: 09:00.</p>` (`rendu/carte_jour.py`, `_page_jour` et `construire_page_sans_seance`).
#: L'horloge est figée, la ligne serait stable ; on la retire quand même pour
#: qu'un lot qui déplace la lecture de l'horloge de la carte (et la fige
#: autrement) ne casse pas l'empreinte de toute la page. C'est la **seule**
#: ligne retirée ; les chemins temporaires et identifiants aléatoires de la
#: page sont remplacés comme ailleurs (`normaliser`).
LIGNE_HORODATAGE = re.compile(r'^\s*<p class="horodatage">Page générée le [^<]*</p>\s*$')


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
        stdout: Any
        if "--json" in argv:
            try:
                stdout = json.loads(sortie) if sortie.strip() else None
            except ValueError:
                stdout = sortie
        else:
            # Ligne à ligne : un diff de référence se lit alors comme le texte.
            stdout = sortie.splitlines()
        resultat = {
            "argv": list(argv),
            "code": code,
            "stdout": stdout,
            "stderr": erreur,
            "fichiers_ecrits": {
                nom: empreinte for nom, empreinte in self._fichiers().items() if avant.get(nom) != empreinte
            },
            "reseau": sorted(self.rejeu.journal),
        }
        return normaliser(resultat, self.remplacements())

    def les_deux(self, commande: str, *options: str) -> dict[str, Any]:
        """La commande en `--json`, puis en texte, dans cet ordre."""
        return {
            "json": self.lancer(commande, "--json", *options),
            "texte": self.lancer(commande, *options),
        }

    def remplacements(self) -> dict[str, str]:
        racine = str(self.racine)
        return {racine: "<TMP>", os.path.realpath(racine): "<TMP>"}

    def _fichiers(self) -> dict[str, str]:
        """Les GPX et les cartes HTML présents, où qu'ils soient (dossier de
        travail ou `cache/sorties/`), par chemin relatif, avec leur empreinte.

        Un GPX est figé par l'empreinte de ses octets ; une carte HTML par
        l'empreinte de son texte normalisé, ligne `LIGNE_HORODATAGE` retirée.
        """
        trouves = {}
        for chemin in sorted(self.racine.rglob("*")):
            suffixe = chemin.suffix.lower()
            if not chemin.is_file() or suffixe not in (".gpx", ".html"):
                continue
            nom = chemin.relative_to(self.racine).as_posix()
            if suffixe == ".gpx":
                octets = chemin.read_bytes()
            else:
                octets = self.page_normalisee(chemin).encode()
            trouves[nom] = "sha256:" + hashlib.sha256(octets).hexdigest()[:16]
        return trouves

    def page_normalisee(self, chemin: Path) -> str:
        lignes = [
            ligne
            for ligne in chemin.read_text(encoding="utf-8").splitlines()
            if not LIGNE_HORODATAGE.match(ligne)
        ]
        return normaliser("\n".join(lignes), self.remplacements())


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Scene:
    return Scene(tmp_path, monkeypatch, capsys)


def verifier(nom: str, obtenu: Any, regenerer_golden: bool) -> None:
    comparer_a_la_reference(obtenu, DOSSIER / f"cli_{nom}.json", regenerer_golden, REGENERER)


# --- les scénarios ---------------------------------------------------------------


def test_meteo(scene: Scene, regenerer_golden: bool):
    obtenu = scene.les_deux("meteo", "--heure-depart", f"{JOUR}T09:00")
    verifier("meteo", obtenu, regenerer_golden)


def test_meteo_a_l_heure_courante(scene: Scene, regenerer_golden: bool):
    """Sans `--heure-depart` : la fenêtre de prévision vient de l'horloge figée.

    C'est cette référence qui rend le gel d'horloge **porteur** : une commande
    qui lirait la vraie horloge demanderait une autre fenêtre à Open-Meteo.
    """
    verifier("meteo_heure_courante", scene.les_deux("meteo"), regenerer_golden)


def test_boucle(scene: Scene, regenerer_golden: bool):
    obtenu = scene.les_deux("boucle", "--distance", "30", "--heure-depart", f"{JOUR}T09:00")
    verifier("boucle", obtenu, regenerer_golden)


def test_sortie(scene: Scene, regenerer_golden: bool):
    obtenu = scene.les_deux("sortie", "--jour", JOUR, "--heure-depart", "09:00")
    verifier("sortie", obtenu, regenerer_golden)


def test_seance(scene: Scene, regenerer_golden: bool):
    obtenu = {
        "jour_avec_seance": scene.les_deux("seance", "--jour", JOUR),
        "jour_sans_seance": scene.les_deux("seance", "--jour", "2026-09-09"),
    }
    verifier("seance", obtenu, regenerer_golden)


def test_seance_du_jour(scene: Scene, regenerer_golden: bool):
    """Sans `--jour` : « aujourd'hui » vient de l'horloge figée (le jour de la séance)."""
    verifier("seance_du_jour", scene.les_deux("seance"), regenerer_golden)


def test_inventaire(scene: Scene, regenerer_golden: bool):
    historique = ecrire_historique(scene.racine / "historique")
    obtenu = {
        "import": scene.lancer("inventaire", "--json", "--importer", str(historique)),
        "relecture": scene.les_deux("inventaire"),
    }
    verifier("inventaire", obtenu, regenerer_golden)


#: Chiffres significatifs gardés pour `calibrer` : l'ajustement passe par
#: numpy (moindres carrés), dont le dernier chiffre dépend de la bibliothèque
#: d'algèbre linéaire de la machine. Six chiffres gardent visible toute dérive
#: qui compte (un CdA qui bouge de 0,0001 m² sur 0,31 en change le quatrième).
#: Vaut aussi pour la `sortie` qui suit : elle roule avec ces paramètres.
CHIFFRES_CALIBRER = 6


def test_calibrer(scene: Scene, regenerer_golden: bool):
    """`calibrer`, le `calibration.json` qu'il écrit, puis une `sortie` qui le relit.

    Le fichier est un contrat entre deux commandes (et, en hébergé, entre une
    tâche de fond et les requêtes suivantes) : figer seulement la sortie de
    `calibrer` laisserait passer un lot qui n'écrit plus rien, ou dont la
    `sortie` ne relit plus rien.
    """
    historique = ecrire_historique(scene.racine / "historique")
    scene.lancer("inventaire", "--importer", str(historique))
    calibrer_json = scene.lancer("calibrer", "--json", "--velo", "RCR")
    fichier = scene.cache / "calibration.json"
    ecrit = json.loads(fichier.read_text(encoding="utf-8")) if fichier.is_file() else None
    obtenu = {
        "calibrer": {"json": calibrer_json, "texte": scene.lancer("calibrer", "--velo", "RCR")},
        "calibration_json": normaliser(ecrit, scene.remplacements()),
        "sortie_velo_calibre": scene.les_deux(
            "sortie", "--jour", JOUR, "--heure-depart", "09:00", "--velo", "RCR"
        ),
    }
    verifier("calibrer", arrondir(obtenu, CHIFFRES_CALIBRER), regenerer_golden)


def test_comparer(scene: Scene, regenerer_golden: bool):
    historique = ecrire_historique(scene.racine / "historique")
    scene.lancer("inventaire", "--importer", str(historique))
    obtenu = scene.les_deux("comparer", "--velos", "RCR", "BMC", "--zone", "0.85", "0.99")
    verifier("comparer", obtenu, regenerer_golden)


def test_refus(scene: Scene, regenerer_golden: bool):
    """Les refus : code 2, message en français sur la sortie d'erreur, aucun appel."""
    obtenu = {
        "boucle_distance_negative": scene.les_deux("boucle", "--distance", "-5"),
        "sortie_jour_impossible": scene.les_deux("sortie", "--jour", "2026-02-31"),
        "seance_jour_illisible": scene.les_deux("seance", "--jour", "demain"),
        "comparer_meme_velo": scene.les_deux("comparer", "--velos", "RCR", "rcr"),
        "calibrer_velo_inconnu": scene.les_deux("calibrer", "--velo", "Tandem"),
    }
    verifier("refus", obtenu, regenerer_golden)


# --- les contrôles du filet lui-même ------------------------------------------------


def test_la_garde_reseau_est_active():
    """La garde est une fixture importée, pas un `conftest.py` : vérifier qu'elle mord."""
    import socket

    from outils_caracterisation import ReseauInterdit

    with pytest.raises(ReseauInterdit):
        socket.create_connection(("exemple.invalid", 80))


#: Nombre minimal de modules `ourouler.*` dont le gel d'horloge remplace au
#: moins un attribut (36 modules, 48 attributs au 25/09/2026). En dessous,
#: c'est que le balayage a cessé de trouver les modules — un lot qui renomme
#: le paquet, un import paresseux qui échoue — et le filet ne figerait plus
#: rien sans le dire. Un lot qui regroupe légitimement du code sous ce seuil
#: l'abaisse dans sa PR, en le disant.
MODULES_FIGES_MINIMUM = 30


def test_l_horloge_est_bien_figee(scene: Scene):
    """Sans ce contrôle, une référence pourrait dépendre du jour où on la lance.

    Par balayage de `sys.modules`, pas par une liste de modules : aucun
    module `ourouler.*` ne garde une vraie horloge (sous quelque nom que ce
    soit), et assez de modules ont été touchés pour que le balayage ait vu
    le paquet.
    """
    touchee = scene.rejeu.horloge_touchee
    modules = {entree.split(":")[0] for entree in touchee}
    assert len(modules) >= MODULES_FIGES_MINIMUM, sorted(modules)
    assert horloges_reelles_restantes() == []
    assert datetime.now(UTC).year >= 2026  # la vraie horloge, hors du paquet, n'est pas touchée


def test_le_gel_couvre_import_datetime_et_les_alias(monkeypatch: pytest.MonkeyPatch):
    """`import datetime`, `import datetime as _dt`, `from datetime import date as _d`.

    Sur un paquet d'essai (`essai_horloge`), pas sur un faux module
    `ourouler` : le balayage est le même, le paquet balayé est un paramètre.
    """
    import datetime as vrai_module
    import sys
    import types

    from outils_caracterisation import figer_horloge

    faux = types.ModuleType("essai_horloge.module")
    faux.datetime = vrai_module
    faux._dt = vrai_module
    faux._d = vrai_module.date
    faux.Horodatage = vrai_module.datetime
    faux.sans_rapport = vrai_module.timedelta
    monkeypatch.setitem(sys.modules, "essai_horloge.module", faux)

    touchee = figer_horloge(monkeypatch, paquet="essai_horloge")

    attendus = {f"essai_horloge.module:{a}" for a in ("datetime", "_dt", "_d", "Horodatage")}
    assert set(touchee) == attendus
    assert horloges_reelles_restantes("essai_horloge") == []
    jour = date(2026, 9, 8)
    assert faux.datetime.date.today() == jour
    assert faux._dt.datetime.now(UTC).date() == jour
    assert faux._d.today() == jour
    assert faux.Horodatage.now().date() == jour
    assert faux._dt.timedelta is vrai_module.timedelta, "le reste du module est le vrai"
    assert isinstance(date(2020, 1, 1), faux._d), "isinstance doit tenir"
    assert vrai_module.date is _VRAIE_DATE, "le vrai module n'est pas modifié"


#: Ce que le filet a le droit d'importer de `ourouler` : la ligne de commande,
#: la fabrique de l'application et les objets qu'elle prend en paramètre.
#: Tout le reste (commandes, modèle physique, connecteurs) est déplacé par les
#: lots 3 à 10 : un import direct casserait le filet pour une mauvaise raison.
IMPORTS_AUTORISES = frozenset(
    {
        "ourouler",  # le paquet, pour que le gel d'horloge en balaie les modules
        "ourouler.cli",
        "ourouler.api.application",
        "ourouler.api.depots",  # SocleTOML, le socle commun du mode hébergé
        "ourouler.api.adaptateur",  # Budgets, paramètre de creer_application
        "ourouler.api.proprietaire",  # Proprietaire, rendu par une session
        "ourouler.api.quotas",  # Quotas, paramètre de creer_application
        "ourouler.api.session",  # SessionHebergee, MODE_HEBERGE
        "ourouler.api.taches_fond",  # l'attente des tâches de fond (conftest API)
    }
)

#: Les modules de test qu'il peut importer : les siens (`outils_caracterisation`,
#: `donnees_synthetiques`) et le client ASGI (`outils_api`) — jamais un `test_*`.
MODULES_DE_TEST_AUTORISES = frozenset({"outils_caracterisation", "donnees_synthetiques", "outils_api"})


def test_le_filet_ne_depend_que_de_surfaces_stables():
    fichiers = [
        DOSSIER / "outils_caracterisation.py",
        DOSSIER / "donnees_synthetiques.py",
        DOSSIER / "test_caracterisation_cli.py",
        DOSSIER.parent / "api" / "test_caracterisation_api.py",
    ]
    locaux = {f.stem for f in DOSSIER.glob("*.py")} | {"outils_api"}
    fautifs = []
    for fichier in fichiers:
        for noeud in ast.walk(ast.parse(fichier.read_text(encoding="utf-8"))):
            if isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms = [noeud.module]
            elif isinstance(noeud, ast.Import):
                noms = [alias.name for alias in noeud.names]
            else:
                continue
            for nom in noms:
                if nom.startswith("ourouler") and nom not in IMPORTS_AUTORISES:
                    fautifs.append(f"{fichier.name}: {nom}")
                racine = nom.split(".")[0]
                if racine.startswith(("test_", "tests", "workouts", "conftest")):
                    fautifs.append(f"{fichier.name}: {nom}")
                elif racine in locaux and racine not in MODULES_DE_TEST_AUTORISES:
                    fautifs.append(f"{fichier.name}: {nom}")
    assert fautifs == [], fautifs

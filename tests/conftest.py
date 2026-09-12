"""Fixtures partagées.

Les fichiers d'activité de test sont versionnés dans
`tests/fixtures/activites/`, mais régénérés automatiquement s'ils manquent :
le script `tests/fixtures/generer_activites.py` est la source de vérité.
Aucun test ne touche le réseau.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

DOSSIER_FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOSSIER_ACTIVITES = DOSSIER_FIXTURES / "activites"


def _generateur():
    """Charge `tests/fixtures/generer_activites.py` (hors paquet, chargé par chemin)."""
    if "generer_activites" in sys.modules:
        return sys.modules["generer_activites"]
    chemin = DOSSIER_FIXTURES / "generer_activites.py"
    spec = importlib.util.spec_from_file_location("generer_activites", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generer_activites"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def generateur():
    return _generateur()


@pytest.fixture(scope="session")
def activites(generateur) -> Path:
    """Dossier des fichiers d'activité synthétiques, généré au besoin."""
    module = generateur
    attendus = [*module.VALIDES, "vide.fit", "tronque.fit", "non_monotone.gpx"]
    if not all((DOSSIER_ACTIVITES / nom).exists() for nom in attendus):
        module.generer(DOSSIER_ACTIVITES)
    return DOSSIER_ACTIVITES

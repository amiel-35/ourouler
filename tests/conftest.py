"""Fixtures partagées.

Les fichiers d'activité de test sont versionnés dans
`tests/fixtures/activites/`, mais régénérés automatiquement s'ils manquent :
le script `tests/fixtures/generer_activites.py` est la source de vérité.
Aucun test ne touche le réseau.
"""

from __future__ import annotations

import importlib.util
import itertools
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


# --- le cache de la machine, jamais -------------------------------------------
#
# Sans `[cache]` dans la configuration, le cœur retombe sur `CACHE_DEFAUT`,
# le vrai `~/.cache/ourouler` du mainteneur. Une centaine de tests y lisaient
# `calibration.json` ou `routes_connues.sqlite`, et l'API y écrivait même des
# fichiers temporaires : leurs résultats dépendaient de la dernière
# calibration lancée sur la machine (relevé en relecture de L9.1, 25/09/2026,
# quand la fourchette du porte à porte s'est mise à lire ce fichier). Chaque
# test reçoit donc un cache vide à lui ; celui qui a besoin d'un contenu
# l'écrit dans son propre `tmp_path`, comme avant.


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "cache_machine: garde le vrai `CACHE_DEFAUT` (test qui vérifie la constante, "
        "sans rien lire ni écrire dedans)",
    )


@pytest.fixture(scope="session")
def _caches_de_test(tmp_path_factory):
    """Un seul dossier pour la session : `mktemp` à chaque test rescanne ses
    voisins, et doublait la durée de la suite."""
    return tmp_path_factory.mktemp("caches_defaut"), itertools.count()


@pytest.fixture(autouse=True)
def _cache_isole(request, monkeypatch, _caches_de_test):
    if request.node.get_closest_marker("cache_machine"):
        return
    import ourouler.api.depots as depots
    import ourouler.config as module_config

    racine, numeros = _caches_de_test
    dossier = racine / str(next(numeros))
    dossier.mkdir()
    monkeypatch.setattr(module_config, "CACHE_DEFAUT", dossier)
    monkeypatch.setattr(depots, "CACHE_DEFAUT", dossier)
    # Le défaut du champ de la dataclass est figé à sa définition : on le
    # remplace là où `ParametresCache()` le lit.
    monkeypatch.setattr(module_config.ParametresCache.__init__, "__defaults__", (dossier,))

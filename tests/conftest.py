"""Fixtures partagées.

Les fichiers d'activité de test sont versionnés dans
`tests/fixtures/activites/`, mais régénérés automatiquement s'ils manquent :
le script `tests/fixtures/generer_activites.py` est la source de vérité.
Aucun test ne touche le réseau — voir `reseau_interdit` ci-dessous.
"""

from __future__ import annotations

import importlib.util
import itertools
import socket
import sys
import time
from pathlib import Path
from typing import Any

import pytest

DOSSIER_FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOSSIER_ACTIVITES = DOSSIER_FIXTURES / "activites"


# --- pas de réseau dans les tests, pour toute la suite ------------------------
#
# `tests/api/conftest.py` et `tests/adversarial/conftest.py` coupent déjà tout
# le réseau, sans exception, pour leurs dossiers respectifs — de même que la
# fixture `garde_reseau` importée par les modules de `tests/caracterisation/`.
# Ils sont volontairement conservés : ils font strictement plus que la garde
# ci-dessous (aucune sortie locale non plus, pas même `127.0.0.1`), ce dont
# leurs tests ASGI/rejoués n'ont jamais besoin. Cette garde-ci couvre le
# **reste** de la suite, qui n'avait jusqu'ici aucun filet : un `monkeypatch`
# déplacé par une restructuration pouvait laisser un test partir sur Internet
# sans que rien ne le signale.
#
# Elle bloque toute connexion qui n'est pas locale, mais laisse passer la
# boucle locale : `tests/comptes/` a besoin d'une vraie connexion TCP vers le
# PostgreSQL jetable que Docker publie sur `127.0.0.1` (voir
# `tests/comptes/conftest.py`). psycopg parle au serveur via la libpq (code C,
# hors du module `socket` de Python) : cette garde ne le voit de toute façon
# pas passer, local ou non.
#
# Comme pour les gardes existantes, `ReseauInterdit` dérive de `BaseException`
# pour qu'un `except Exception` du code testé ne puisse pas l'avaler en
# silence.


class ReseauInterdit(BaseException):
    """Un test a tenté de sortir sur le réseau. Règle absolue 3 de CLAUDE.md."""


#: Hôtes considérés locaux : boucle locale (v4/v6), nom conventionnel, et
#: `""`/`None` (adresse « toutes interfaces », utilisée en écoute plutôt qu'en
#: connexion, mais jamais une sortie vers Internet).
_HOTES_LOCAUX = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", "", None})


def _hote_est_local(hote: object) -> bool:
    if isinstance(hote, bytes):
        hote = hote.decode("utf-8", errors="replace")
    return hote in _HOTES_LOCAUX


def _cible(adresse: object) -> tuple[object, object] | None:
    """`(hôte, port)` d'une adresse `AF_INET`/`AF_INET6`, ou `None` pour un
    chemin de socket Unix (`str`/`bytes` au lieu d'un tuple) — toujours local."""
    if isinstance(adresse, tuple) and len(adresse) >= 2:
        return adresse[0], adresse[1]
    return None


def _message(hote: object, port: object) -> str:
    return (
        f"test qui sort sur Internet : {hote}:{port} — la règle est pas de réseau "
        "dans les tests ; injecter un client ou une réponse enregistrée"
    )


@pytest.fixture(autouse=True)
def reseau_interdit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coupe toute sortie réseau non locale, pour l'ensemble de la suite."""

    connect_original = socket.socket.connect
    connect_ex_original = socket.socket.connect_ex
    create_connection_original = socket.create_connection
    getaddrinfo_original = socket.getaddrinfo

    def connect(self: socket.socket, adresse: Any, *args: Any, **kwargs: Any):
        cible = _cible(adresse)
        if cible is not None and not _hote_est_local(cible[0]):
            raise ReseauInterdit(_message(*cible))
        return connect_original(self, adresse, *args, **kwargs)

    def connect_ex(self: socket.socket, adresse: Any, *args: Any, **kwargs: Any):
        cible = _cible(adresse)
        if cible is not None and not _hote_est_local(cible[0]):
            raise ReseauInterdit(_message(*cible))
        return connect_ex_original(self, adresse, *args, **kwargs)

    def create_connection(adresse: Any, *args: Any, **kwargs: Any):
        cible = _cible(adresse)
        if cible is not None and not _hote_est_local(cible[0]):
            raise ReseauInterdit(_message(*cible))
        return create_connection_original(adresse, *args, **kwargs)

    def getaddrinfo(hote: Any, port: Any, *args: Any, **kwargs: Any):
        if not _hote_est_local(hote):
            raise ReseauInterdit(_message(hote, port))
        return getaddrinfo_original(hote, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def classe_reseau_interdit() -> type[BaseException]:
    """`ReseauInterdit`, exposée en fixture plutôt qu'en `from conftest import` :

    quatre `conftest.py` coexistent sous `tests/` (racine, `api/`,
    `adversarial/`, `comptes/`), tous nommés `conftest` une fois importés —
    `from conftest import ...` depuis un module à la racine de `tests/`
    résout au hasard de l'ordre de collecte (déjà noté dans
    `tests/caracterisation/outils_caracterisation.py`). Une fixture, elle,
    passe par le mécanisme de pytest, jamais par `sys.modules["conftest"]`.
    """
    return ReseauInterdit


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
    config.addinivalue_line(
        "markers",
        "ecart_attendu: test qui provoque exprès un écart du double chemin de l'API (lot 11)",
    )


# --- fichiers de référence (golden) -------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--regenerer-golden",
        action="store_true",
        default=False,
        help="réécrit les fichiers de référence au lieu de les comparer",
    )


@pytest.fixture
def regenerer_golden(request) -> bool:
    return request.config.getoption("--regenerer-golden")


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
    monkeypatch.setattr(module_config.ParametresCache.__init__, "__defaults__", (dossier, None))


@pytest.fixture
def fuseau_de_paris(monkeypatch):
    """Le fuseau du système posé à Europe/Paris le temps d'un test, puis rendu.

    `--depart 09:00` se lit en **heure locale de la machine** (`heure_depart`,
    contrat de la CLI). Les bouchons Open-Meteo de `test_boucle_commande.py`,
    `test_sortie_commande.py` et `fabriques_propositions.py` rendent une série figée qui
    commence à 06:00 **UTC**, sans lire `start_hour` : ils ont été calibrés sur
    le Mac du mainteneur, où 09:00 local vaut 07:00 UTC. Sous TZ=UTC (CI,
    conteneur), le même 09:00 tombe à la fin de la série et la pluie, le vent
    et la tenue disparaissent. Le fuseau que ces tests supposent est donc dit
    ici, au lieu d'être emprunté à la machine qui les lance.

    `monkeypatch` rend `TZ` à la fin, mais la libc garde le fuseau chargé
    tant qu'on ne rappelle pas `tzset()` : sans le second appel, tous les
    tests suivants hériteraient de Paris.
    """
    if not hasattr(time, "tzset"):  # pragma: no cover - Windows
        pytest.skip("time.tzset() indisponible sur cette plateforme")
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()

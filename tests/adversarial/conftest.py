"""Socle des tests adversariaux.

Deux garanties données à tous les tests de ce dossier :

1. **Aucun réseau.** Une fixture *autouse* remplace `socket.socket`,
   `socket.create_connection` et `socket.getaddrinfo` par une fonction qui
   lève `ReseauInterdit`. `httpx.MockTransport` n'ouvre aucune socket : les
   tests de connecteur passent, une vraie requête tombe. `ReseauInterdit`
   dérive volontairement de `BaseException` pour qu'un `except Exception`
   dans le code testé ne puisse pas l'avaler en silence.
2. **Des fichiers d'activité hostiles**, générés une fois par session par
   `fixtures/generer_hostiles.py` dans un dossier temporaire (rien de
   binaire n'est versionné, voir le docstring du générateur).

Les modules testés s'importent normalement : un module absent ou renommé
fait échouer la collecte au lieu de sauter des tests en silence
(`tests/sauts_autorises.py` dit quels sauts sont admis).
"""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path
from types import ModuleType

import pytest
from outils import ReseauInterdit

DOSSIER = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def reseau_interdit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coupe le réseau pour tous les tests du dossier."""

    def refuser(*_args, **_kwargs):
        raise ReseauInterdit(
            "réseau interdit dans les tests : injecter un httpx.Client("
            "transport=httpx.MockTransport(...)) au lieu d'appeler le service"
        )

    monkeypatch.setattr(socket, "socket", refuser)
    monkeypatch.setattr(socket, "create_connection", refuser)
    monkeypatch.setattr(socket, "getaddrinfo", refuser)


def _charger_generateur() -> ModuleType:
    chemin = DOSSIER / "fixtures" / "generer_hostiles.py"
    spec = importlib.util.spec_from_file_location("generer_hostiles", chemin)
    assert spec and spec.loader, f"générateur de fixtures introuvable : {chemin}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def generateur() -> ModuleType:
    """Le module `generer_hostiles` (contenus en mémoire, catalogue, encodeurs)."""
    return _charger_generateur()


@pytest.fixture(scope="session")
def hostiles(generateur: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """{nom de fichier: chemin} — le catalogue matérialisé une fois par session."""
    return generateur.ecrire_tous(tmp_path_factory.mktemp("hostiles"))


@pytest.fixture
def ecrire_config(tmp_path: Path):
    """Écrit un config.toml de test et renvoie son chemin.

    Le dossier de cache pointe **toujours** dans `tmp_path` : aucun test ne
    doit écrire dans le vrai `~/.cache/ourouler` du mainteneur.
    """

    def _ecrire(corps: str = "", *, dossier_cache: Path | None = None) -> Path:
        cache = dossier_cache if dossier_cache is not None else tmp_path / "cache"
        chemin = tmp_path / "config.toml"
        chemin.write_text(
            '[depart]\nnom = "Point fictif"\nlatitude = 0.0\nlongitude = 0.0\n'
            "[cycliste]\nmasse_kg = 80.0\nftp_w = 250.0\n"
            f'[cache]\ndossier = "{cache.as_posix()}"\n' + corps,
            encoding="utf-8",
        )
        return chemin

    return _ecrire

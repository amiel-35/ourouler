"""Une seule source de version : `pyproject.toml`.

Avant ce test, `ourouler.__version__` était figé à `"0.0.1"` dans
`src/ourouler/__init__.py`, repris tel quel par l'API (titre OpenAPI et
`/sante`) — une chaîne périmée dès la première publication. Ce test vérifie
que `__version__`, le `package.json` du front et la réponse `/sante` disent
tous la même chose que `pyproject.toml`, la seule source qui compte.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _version_pyproject() -> str:
    donnees = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    return donnees["project"]["version"]


def test_version_du_paquet_suit_pyproject():
    import ourouler

    assert ourouler.__version__ == _version_pyproject()


def test_version_du_front_suit_pyproject():
    paquet = json.loads((RACINE / "front" / "package.json").read_text(encoding="utf-8"))
    assert paquet["version"] == _version_pyproject()


def test_sante_rend_la_vraie_version():
    import pytest

    pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

    from fastapi.testclient import TestClient

    from ourouler.api.application import creer_application

    client = TestClient(creer_application(), raise_server_exceptions=False)
    reponse = client.get("/sante")
    assert reponse.status_code == 200
    assert reponse.json() == {"etat": "ok", "version": _version_pyproject()}

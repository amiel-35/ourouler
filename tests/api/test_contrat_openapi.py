"""Filet 0c : le contrat OpenAPI figé en référence.

Écrit sous `tests/api/` et non sous `tests/caracterisation/` : la garde
réseau (`reseau_interdit`, autouse) est posée dans `tests/api/conftest.py`
et ne s'applique qu'aux tests collectés sous ce dossier — c'est le seul
moyen d'en bénéficier ici. Le fichier de référence, lui, reste à l'endroit
demandé : `tests/caracterisation/openapi.json`.

L'application est construite exactement comme le reste de `tests/api/` :
via `client_api()` (aucun réseau, cf. `outils_api.ClientApi`), puis
`schema_openapi()` qui appelle `app.openapi()` sans passer par HTTP quand
c'est possible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from outils_api import client_api, schema_openapi

#: Sans l'extra `api`, ce module se saute au lieu de casser la collecte
#: (même garde que `test_api_socle.py`).
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

REFERENCE = Path(__file__).resolve().parents[1] / "caracterisation" / "openapi.json"


def _serialise(schema: dict) -> str:
    return json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_le_contrat_openapi_correspond_a_la_reference(regenerer_golden: bool):
    """Le contrat publié par l'API ne doit pas bouger sans qu'on le remarque.

    Un changement ici est un changement de comportement pour le front : il se
    relit comme tel, jamais en régénérant la référence par réflexe.
    """
    schema = schema_openapi(client_api())
    obtenu = _serialise(schema)

    if regenerer_golden:
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE.write_text(obtenu, encoding="utf-8")
        pytest.skip("référence régénérée")

    attendu = REFERENCE.read_text(encoding="utf-8")
    assert obtenu == attendu, (
        "le contrat d'API a changé : relire le diff comme un changement de comportement, "
        "puis `uv run pytest --regenerer-golden tests/api/test_contrat_openapi.py`"
    )

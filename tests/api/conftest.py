"""Socle des tests de contrat de l'API (lot F1).

Ces tests sont écrits **en aveugle de l'implémentation** : ils ne connaissent
ni le nom du module, ni les chemins de routes, ni les noms de paramètres. Tout
se découvre à l'exécution, par le schéma OpenAPI que l'application publie.
C'est volontaire : un test qui code en dur `/api/sortie` ne teste que le goût
de celui qui l'a écrit, alors qu'un test qui exige « il existe une route qui
porte `sortie`, et elle déclare un paramètre de durée » teste le contrat.

Trois garanties données à tous les tests de ce dossier :

1. **Aucun réseau** (règle absolue 3 de CLAUDE.md). Une fixture *autouse*
   remplace `socket.socket.connect`, `socket.create_connection` et
   `socket.getaddrinfo` par une fonction qui lève `ReseauInterdit`, laquelle
   dérive de `BaseException` pour qu'un `except Exception` du code testé ne
   puisse pas l'avaler. On ne coupe volontairement **pas** `socket.socket`
   lui-même : `asyncio` fabrique son tube interne avec `socket.socketpair()`,
   qui passe par cette classe, et le client ASGI en a besoin. Couper `connect`
   suffit à interdire toute sortie réelle.
2. **Aucune donnée personnelle** (règle absolue 1). Le départ synthétique est
   en mer et les secrets sont des sentinelles inventées — voir `outils_api.py`.
3. **Aucune erreur de collecte.** L'API n'existe pas encore : rien d'elle n'est
   importé au niveau du module. Tout passe par `client_api()`, appelé *dans le
   corps* du test, qui lève `ApiAbsente` — une sous-classe d'`AssertionError`,
   donc un échec et non une erreur. Les tests portent `xfail(strict=True)` :
   ils crieront le jour où ils se mettront à passer.

Les outils vivent dans `outils_api.py` plutôt qu'ici : trois `conftest.py`
coexistent sous `tests/`, et `import conftest` serait ambigu.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Any

import pytest

DOSSIER = Path(__file__).resolve().parent

# Rend `outils_api.py` importable depuis les modules de test de ce dossier.
if str(DOSSIER) not in sys.path:
    sys.path.insert(0, str(DOSSIER))


class ReseauInterdit(BaseException):
    """Un test a tenté d'ouvrir une connexion. Règle absolue 3 de CLAUDE.md."""


@pytest.fixture(autouse=True)
def reseau_interdit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coupe toute sortie réseau pour les tests de ce dossier."""

    def refuser(*_args: Any, **_kwargs: Any):
        raise ReseauInterdit(
            "réseau interdit dans les tests de l'API : l'application doit accepter des "
            "clients HTTP injectables (httpx.Client(transport=httpx.MockTransport(...)))"
        )

    monkeypatch.setattr(socket.socket, "connect", refuser)
    monkeypatch.setattr(socket.socket, "connect_ex", refuser)
    monkeypatch.setattr(socket, "create_connection", refuser)
    monkeypatch.setattr(socket, "getaddrinfo", refuser)

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

import logging
import socket
from typing import Any

import pytest


class ReseauInterdit(BaseException):
    """Un test a tenté d'ouvrir une connexion. Règle absolue 3 de CLAUDE.md."""


@pytest.fixture(autouse=True)
def taches_lourdes_rendues():
    """Chaque test part d'un serveur sans tâche lourde en cours (import, calibration).

    Une tâche lancée par le test précédent peut encore être en train de rendre
    le verrou serveur (`api/taches_fond.VERROU`, quelques millisecondes après
    son « fini ») : depuis que `api/garde_avant_corps.py` refuse un import
    **avant** d'en lire le corps, cette fenêtre suffisait à recevoir un
    `import_deja_en_cours` pour de mauvaises raisons. Importé ici et non en
    tête de module : garantie 3 ci-dessus, rien de l'API à la collecte.
    """
    import time

    try:
        from ourouler.api import taches_fond
    except Exception:  # noqa: BLE001 — extra « api » absent : rien à attendre
        yield
        return
    debut = time.monotonic()
    while not taches_fond.VERROU.acquire(blocking=False):
        assert time.monotonic() - debut < 30, "une tâche lourde ne rend pas le verrou serveur"
        time.sleep(0.01)
    taches_fond.VERROU.release()
    yield


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


@pytest.fixture(autouse=True)
def chemin_api_de_l_environnement(monkeypatch: pytest.MonkeyPatch, request):
    """`OUROULER_API_CHEMIN=nouveau uv run pytest tests/api` rejoue tout ce dossier sur ce chemin.

    `creer_application` ne lit pas l'environnement ; une application
    construite sans `chemin_api` prend `double_chemin.CHEMIN_DEFAUT`. Poser la
    variable change ce défaut le temps du test, par la même lecture que le
    service (`exploitation.chemin_api`). Sans la variable, rien ne change.

    En `double`, un test qui laisse une ligne d'écart échoue, sauf s'il porte
    le marqueur `ecart_attendu` (la mutation de contrôle).
    """
    import os

    if not os.environ.get("OUROULER_API_CHEMIN"):
        yield
        return
    try:
        from ourouler.api import double_chemin, exploitation
    except Exception:  # noqa: BLE001 — extra « api » absent
        yield
        return
    chemin = exploitation.chemin_api()
    monkeypatch.setattr(double_chemin, "CHEMIN_DEFAUT", chemin)
    lignes: list[str] = []

    class Recueil(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lignes.append(record.getMessage())

    recueil = Recueil(level=logging.WARNING)
    double_chemin.journal.addHandler(recueil)
    try:
        yield
    finally:
        double_chemin.journal.removeHandler(recueil)
    if chemin == double_chemin.CHEMIN_DOUBLE and not request.node.get_closest_marker("ecart_attendu"):
        assert not lignes, f"écarts entre l'ancien et le nouveau chemin : {lignes}"

"""`api/limite_corps.LimiteTailleCorps` — ASGI brut, sans FastAPI (L9.2 suite).

Éprouvé ici directement contre la classe, avec une fausse application et de
faux messages ASGI : c'est le seul moyen de rejouer un corps envoyé en
plusieurs morceaux sans `Content-Length` (`Transfer-Encoding: chunked`),
qu'`httpx.AsyncClient` ne fabrique pas lui-même pour un `files=` en mémoire.
Le comportement contre le **service réel** (FastAPI, les deux routes
bornées) est éprouvé par `tests/api/test_api_entrees_hostiles.py` et
`tests/test_api.py`.
"""

from __future__ import annotations

import asyncio

import pytest

from ourouler.api.limite_corps import LimiteTailleCorps

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")


class _AppEspion:
    """Une application factice qui note ce qu'elle a reçu, et rend 200."""

    def __init__(self) -> None:
        self.corps_recu = b""
        self.appelee = False

    async def __call__(self, scope, receive, send) -> None:
        self.appelee = True
        while True:
            message = await receive()
            self.corps_recu += message.get("body") or b""
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def _scope(chemin: str, content_length: int | None = None) -> dict:
    entetes = []
    if content_length is not None:
        entetes.append((b"content-length", str(content_length).encode()))
    return {"type": "http", "path": chemin, "headers": entetes, "method": "POST"}


def _recepteur(messages: list[dict]):
    """Un `receive()` qui rend les messages donnés, un par appel."""
    it = iter(messages)

    async def receive() -> dict:
        return next(it)

    return receive


def _executer(middleware: LimiteTailleCorps, scope: dict, messages: list[dict]) -> list[dict]:
    envoyes: list[dict] = []

    async def send(message: dict) -> None:
        envoyes.append(message)

    asyncio.run(middleware(scope, _recepteur(messages), send))
    return envoyes


def _corps_json(envoyes: list[dict]) -> dict:
    import json

    corps = b"".join(m["body"] for m in envoyes if m["type"] == "http.response.body")
    return json.loads(corps)


def test_un_corps_sous_la_borne_traverse_sans_etre_touche():
    app = _AppEspion()
    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 100})
    messages = [{"type": "http.request", "body": b"petit", "more_body": False}]
    envoyes = _executer(middleware, _scope("/api/v1/activites/import"), messages)
    assert app.appelee
    assert app.corps_recu == b"petit"
    assert envoyes[0]["status"] == 200


def test_un_chemin_hors_des_bornes_traverse_sans_etre_compte():
    app = _AppEspion()
    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 10})
    messages = [{"type": "http.request", "body": b"0" * 999, "more_body": False}]
    envoyes = _executer(middleware, _scope("/api/v1/autre-route"), messages)
    assert app.appelee
    assert envoyes[0]["status"] == 200


def test_content_length_menteur_refuse_avant_de_lire():
    """`Content-Length` annoncé au-delà de la borne : l'app n'est jamais appelée."""
    app = _AppEspion()
    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 100})
    envoyes = _executer(
        middleware, _scope("/api/v1/activites/import", content_length=1000), messages=[]
    )
    assert not app.appelee, "l'application ne doit jamais voir un corps refusé sur l'en-tête"
    assert envoyes[0]["status"] == 413
    assert "annoncés" in _corps_json(envoyes)["erreur"]["message"]


def test_un_flux_sans_content_length_est_coupe_en_cours_de_route():
    """Le cas que `Content-Length` seul ne voit pas : pas d'en-tête, plusieurs
    morceaux (`Transfer-Encoding: chunked`), et le total dépasse la borne
    avant le dernier morceau. L'app ne doit voir aucun de ces octets."""
    app = _AppEspion()
    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 10})
    messages = [
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"67890", "more_body": True},
        {"type": "http.request", "body": b"trop", "more_body": False},
    ]
    envoyes = _executer(middleware, _scope("/api/v1/activites/import"), messages)
    assert not app.appelee, "l'application ne doit jamais recevoir un corps qui dépasse"
    assert envoyes[0]["status"] == 413
    corps = _corps_json(envoyes)
    assert corps["erreur"]["code"] == "fichier_trop_gros"
    assert "reçus" in corps["erreur"]["message"]


def test_un_flux_en_plusieurs_morceaux_sous_la_borne_est_rejoue_integralement():
    """Le corps est bien reconstitué à l'identique côté application, morceau par
    morceau — pas seulement laissé passer d'un bloc."""
    app = _AppEspion()
    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 100})
    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ]
    _executer(middleware, _scope("/api/v1/activites/import"), messages)
    assert app.corps_recu == b"abcdef"


def test_une_requete_websocket_traverse_sans_etre_touchee():
    appelee = False

    async def app(scope, receive, send) -> None:
        nonlocal appelee
        appelee = True

    middleware = LimiteTailleCorps(app, {"/api/v1/activites/import": 10})
    scope = {"type": "websocket", "path": "/api/v1/activites/import"}

    async def receive() -> dict:  # pragma: no cover — jamais appelé ici
        raise AssertionError

    async def send(message: dict) -> None:  # pragma: no cover — jamais appelé ici
        raise AssertionError

    asyncio.run(middleware(scope, receive, send))
    assert appelee

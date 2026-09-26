"""Filet du lot 13 : quel point d'entrée résout chaque chemin littéral.

Le routeur essaie les routes **dans l'ordre d'enregistrement** et s'arrête à
la première qui correspond entièrement (méthode et chemin) ; une route qui ne
correspond que par le chemin ne sert que si aucune autre ne correspond
entièrement, et rend alors 405. Répartir les routes entre les modules de `api/routes/` change
l'ordre dans lequel les routes s'enregistrent si l'on n'y prend garde :
`GET /seances/fichier`, par exemple, est servi par `seance_du_jour`
(`/seances/{jour}`), et `POST /seances/fichier` par `deposer_seance`
uniquement parce que la première ne connaît pas `POST`.

Ce test fige, dans `tests/caracterisation/resolution_routes.json` :

- **l'ordre d'enregistrement** : méthodes, chemin et nom de chaque route ;
- **la résolution** : pour chaque chemin littéral tiré d'une route (les
  paramètres remplacés par une valeur d'exemple) et chacune des méthodes
  servies par l'application, le point d'entrée qui répond — module et nom de
  fonction —, ou `405`, ou `404`.

La résolution passe par le routeur de l'application lui-même, pas par une
copie de son algorithme, sur une session qui n'en ouvre aucune : ce qui est
figé est le choix de la route, pas ce qu'elle répond.

**Le module d'une route de `ourouler.api.routes.*` s'écrit
`ourouler.api.routes`** : le découpage de ce paquet en modules par domaine
(lot 13) n'est pas un changement de résolution. Qu'une route vienne bien de
la fonction nommée est vérifié à part, sans référence
(`test_chaque_point_d_entree_est_la_fonction_de_son_module`).

Régénérer, après relecture du diff seulement :
`uv run pytest tests/api/test_resolution_routes.py --regenerer-golden`.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from pathlib import Path
from typing import Any

from outils_api import charger_application
from outils_caracterisation import comparer_a_la_reference
from starlette.exceptions import HTTPException

from ourouler.api.session import SessionHebergee

REFERENCE = Path(__file__).resolve().parents[1] / "caracterisation" / "resolution_routes.json"
REGENERER = "`uv run pytest tests/api/test_resolution_routes.py --regenerer-golden`"

#: Le paquet des routes de l'API : ses modules se ramènent à ce nom.
PAQUET_ROUTES = "ourouler.api.routes"

PARAMETRE = re.compile(r"\{(?P<nom>[a-z_]+)(?::(?P<type>[a-z]+))?\}")


def _application() -> Any:
    """L'application, sur une session qui n'en ouvre **aucune**.

    Toute route de données y répond 401 avant d'avoir rien fait, et les
    routes d'avant session refusent un corps vide : sonder la résolution ne
    touche ainsi à aucune donnée.
    """
    return charger_application(session=SessionHebergee())


def _routes(app: Any) -> list[Any]:
    """Les routes dans l'ordre où le routeur les essaie, routeurs inclus dépliés.

    Depuis FastAPI 0.14x, `include_router` garde le routeur inclus comme un
    nœud au lieu d'en recopier les routes ; `iter_route_contexts` les déplie
    avec leur chemin effectif. Un FastAPI plus ancien recopie, et
    `app.router.routes` suffit.
    """
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # pragma: no cover — FastAPI qui recopie les routes incluses
        return list(app.router.routes)
    return list(iter_route_contexts(app.router.routes))


def _module(point: Any) -> str:
    module = point.__module__
    if module == PAQUET_ROUTES or module.startswith(PAQUET_ROUTES + "."):
        return PAQUET_ROUTES
    return module


def _litteral(chemin: str) -> str:
    """Le chemin, chaque paramètre remplacé par une valeur que son convertisseur accepte."""

    def exemple(m: re.Match) -> str:
        if m.group("type") == "int":
            return "1"
        if m.group("nom") == "jour":
            return "2026-09-26"
        return f"exemple-{m.group('nom')}"

    return PARAMETRE.sub(exemple, chemin)


def _resoudre(app: Any, methode: str, chemin: str) -> str:
    """Le point d'entrée que le routeur choisit pour cette requête, ou 405, ou 404.

    C'est le routeur qui pose `scope["endpoint"]` sur la route retenue. Sans
    session, la route s'arrête à sa première dépendance.
    """
    portee: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": methode,
        "scheme": "http",
        "path": chemin,
        "raw_path": chemin.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"essai")],
        "client": ("essai", 1),
        "server": ("essai", 80),
        "app": app,
    }
    statuts: list[int] = []

    async def recevoir() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def envoyer(message: dict) -> None:
        if message["type"] == "http.response.start":
            statuts.append(message["status"])

    async def aller() -> None:
        try:
            await app.router(portee, recevoir, envoyer)
        except HTTPException as refus:
            statuts.append(refus.status_code)
        except Exception:  # noqa: BLE001 — le refus de la route elle-même, pas du routeur
            statuts.append(0)

    asyncio.run(aller())
    if statuts and statuts[0] == 405:
        return "405"
    point = portee.get("endpoint")
    if point is None:
        return "404"
    return f"{_module(point)}:{point.__name__}"


def table_de_resolution(app: Any) -> dict[str, Any]:
    routes = [r for r in _routes(app) if r.methods]
    ordre = [
        {"methodes": sorted(r.methods - {"HEAD"}), "chemin": r.path, "nom": r.name} for r in routes
    ]
    methodes = sorted({m for r in routes for m in r.methods} - {"HEAD"})
    chemins = sorted({_litteral(r.path) for r in routes})
    resolution = {
        f"{methode} {chemin}": _resoudre(app, methode, chemin)
        for chemin in chemins
        for methode in methodes
    }
    return {"ordre": ordre, "resolution": resolution}


def test_la_resolution_des_chemins_correspond_a_la_reference(regenerer_golden: bool):
    """Chaque chemin littéral est servi par le même point d'entrée qu'à la référence."""
    table = table_de_resolution(_application())
    comparer_a_la_reference(table, REFERENCE, regenerer_golden, REGENERER)


def test_chaque_point_d_entree_est_la_fonction_de_son_module():
    """Le nom retenu par la table désigne bien la fonction qui sert la route."""
    for route in _routes(_application()):
        if not route.methods or "<locals>" in route.endpoint.__qualname__:
            continue  # la sonde de santé et les routes du cadre (openapi, docs)
        module = importlib.import_module(route.endpoint.__module__)
        assert getattr(module, route.endpoint.__name__) is route.endpoint, (
            f"{route.path} : {route.endpoint.__module__}.{route.endpoint.__name__} "
            "n'est pas la fonction qui sert la route"
        )


def test_la_table_voit_bien_les_collisions():
    """Contre-épreuve : un chemin littéral qui tombe sur une route à paramètre est vu."""
    table = table_de_resolution(_application())["resolution"]
    assert table["GET /api/v1/seances/fichier"] == f"{PAQUET_ROUTES}:seance_du_jour"
    assert table["POST /api/v1/seances/fichier"] == f"{PAQUET_ROUTES}:deposer_seance"
    assert table["PATCH /api/v1/seances/fichier"] == "405"
    assert table["GET /api/v1/activites/import"] == f"{PAQUET_ROUTES}:etat_import"

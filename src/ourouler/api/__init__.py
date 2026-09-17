"""L'API HTTP d'`ourouler` (lot F1).

**Une couche d'exploitation, comme `cli.py`** : elle a le droit de lire la
configuration et l'environnement, le cœur non (règle absolue 2 de
`CLAUDE.md`). Dans ce paquet, un seul module y touche — `exploitation.py` —
et un invariant le vérifie (`tests/test_invariants.py`).

Ce qu'elle expose est **ce que la ligne de commande sait déjà rendre en
JSON** (`doctrine_architecture.md` §10.2 : « L'API expose ce que la CLI sait
déjà rendre en JSON ; le front la consomme »). Elle ne recalcule rien
elle-même : elle appelle les mêmes fonctions `executer(...)` que `cli.py`,
avec les mêmes clients injectables, et rend leur JSON tel quel — voir
`adaptateur.py` pour le pourquoi de ce choix et son prix.

Le contrat détaillé (routes, formes, codes d'erreur) est dans
`docs/ux/api_contrat.md`.

Le paquet ne s'importe pas au chargement d'`ourouler` : FastAPI est un extra
(`uv sync --extra api`), et la ligne de commande doit tourner sans.
"""

from __future__ import annotations

__all__ = ["creer_application"]


def creer_application(*args, **kwargs):
    """Raccourci vers `ourouler.api.application.creer_application`.

    Import paresseux : nommer FastAPI ici le rendrait obligatoire pour qui
    n'utilise que la ligne de commande.
    """
    from ourouler.api.application import creer_application as fabrique

    return fabrique(*args, **kwargs)

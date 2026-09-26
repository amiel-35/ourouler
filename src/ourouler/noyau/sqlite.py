"""Lecture de la structure d'une base SQLite, pour les migrations des index locaux.

Partagé par le cache d'activités, la base des routes connues et le cache de
l'archive météo, qui vivent dans des couches différentes.
"""

from __future__ import annotations

import sqlite3


def table_existe(cx: sqlite3.Connection, nom: str) -> bool:
    """Vrai si la table `nom` existe dans la base."""
    return (
        cx.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (nom,)
        ).fetchone()
        is not None
    )


def colonne_existe(cx: sqlite3.Connection, table: str, colonne: str) -> bool:
    """`PRAGMA table_info` plutôt que le texte du `CREATE TABLE` : on lit la structure."""
    return any(ligne[1] == colonne for ligne in cx.execute(f"PRAGMA table_info({table})"))

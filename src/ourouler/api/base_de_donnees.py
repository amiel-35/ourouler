"""La base de l'hébergé : ouvrir une connexion, appliquer les migrations.

Doctrine §10.2 : « Base de données hébergée : PostgreSQL, dès le premier jour
de l'hébergé, jamais SQLite. […] Migrations SQL numérotées, SQL nu, pas
d'ORM. » Ce module est l'application littérale de cette phrase, et rien de
plus : il ne connaît aucune table du produit.

**Il ne lit pas l'environnement.** L'URL de connexion arrive en argument ;
c'est `api/exploitation.py` — et lui seul, puisque le cœur ne lit ni
configuration ni environnement — qui sait d'où
elle vient (`OUROULER_DATABASE_URL`). Un module qui ouvrirait la base « en se
débrouillant » serait exactement le bug que l'invariant de
`tests/test_invariants.py` cherche.

## Pourquoi des fichiers `.sql` numérotés et pas un cadre de migration

Le projet n'a ni équipe, ni branche longue, ni base de recette : un dossier de
fichiers `0001_…sql`, une table qui dit lesquels sont passés, et une fonction
qui applique ce qui manque. Alembic saurait faire davantage — descendre,
engendrer un diff depuis un modèle — mais il n'y a pas de modèle à comparer
(pas d'ORM) et personne pour descendre. Le coût d'une dépendance de plus n'est
pas payé par un besoin.

## Ce que l'idempotence veut dire ici

`appliquer_migrations` se relance sans rien casser : elle lit ce que la table
`migrations` contient déjà et n'applique que le reste. Chaque fichier passe
dans **sa propre transaction**, avec son enregistrement dans `migrations` :
une migration à moitié appliquée n'existe pas, et la reprise repart du bon
numéro. C'est ce qui permet de la lancer à chaque démarrage du service sans y
penser.

## Le mode de connexion attendu : autocommit

Les connexions rendues par `ouvrir` sont en **autocommit**, et chaque dépôt
enveloppe son opération dans `with connexion.transaction():`. C'est le choix
recommandé de psycopg 3, et il a ici une conséquence qu'on veut : la portée
d'une transaction est **écrite** là où elle sert, au lieu d'être le hasard de
l'endroit où quelqu'un appelle `commit()`. Un appelant qui a besoin d'une
transaction plus large (un test qui tient une écriture ouverte pour en
provoquer une seconde) ouvre la sienne autour : psycopg imbrique alors par
point de reprise, et c'est le bloc extérieur qui valide.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import psycopg

#: Le dossier des migrations, à côté de ce module. Les fichiers y sont
#: nommés `NNNN_sujet.sql` et appliqués dans l'ordre de leur numéro.
DOSSIER_MIGRATIONS = Path(__file__).resolve().parent / "migrations"

#: La table qui retient ce qui a déjà été appliqué. Elle est créée par cette
#: fonction-ci et non par une migration : c'est elle qui rend les migrations
#: idempotentes, elle ne peut donc pas en dépendre.
_TABLE_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS migrations (
    numero      INTEGER PRIMARY KEY,
    nom         TEXT NOT NULL,
    applique_le TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class ErreurMigration(RuntimeError):
    """Le dossier de migrations est incohérent. C'est un bug du dépôt, pas de l'utilisateur."""


def ouvrir(url: str) -> psycopg.Connection:
    """Une connexion à la base que l'URL désigne, en autocommit.

    L'URL **arrive** ; ce module ne la cherche nulle part. Voir la note de
    module sur l'autocommit : ce n'est pas « sans transaction », c'est « les
    transactions se déclarent ».
    """
    return psycopg.connect(url, autocommit=True)


def migrations_disponibles(dossier: Path | None = None) -> list[tuple[int, str, Path]]:
    """`[(numero, nom, chemin)]`, triées par numéro.

    Le numéro est le préfixe du nom de fichier. Deux fichiers qui porteraient
    le même numéro sont une erreur du dépôt, pas un cas à départager au
    hasard de l'ordre alphabétique.
    """
    dossier = DOSSIER_MIGRATIONS if dossier is None else dossier
    trouvees: list[tuple[int, str, Path]] = []
    for chemin in sorted(dossier.glob("*.sql")):
        prefixe = chemin.name.split("_", 1)[0]
        if not prefixe.isdigit():
            raise ErreurMigration(
                f"{chemin.name} : une migration se nomme « NNNN_sujet.sql », "
                "le numéro d'abord"
            )
        trouvees.append((int(prefixe), chemin.name, chemin))
    numeros = [numero for numero, _, _ in trouvees]
    if len(set(numeros)) != len(numeros):
        raise ErreurMigration(f"deux migrations portent le même numéro dans {dossier}")
    return sorted(trouvees)


def appliquer_migrations(
    connexion: psycopg.Connection, dossier: Path | None = None
) -> list[str]:
    """Applique ce qui manque et rend les noms des migrations appliquées cette fois.

    Relancer ne fait rien et ne casse rien : la liste rendue est alors vide.
    C'est la seule promesse que l'appelant a besoin de connaître, et un test
    la vérifie en rejouant deux fois sur la même base.
    """
    with connexion.transaction():
        connexion.execute(_TABLE_MIGRATIONS)
    deja = _migrer_deja_appliquees(connexion)
    appliquees: list[str] = []
    for numero, nom, chemin in migrations_disponibles(dossier):
        if numero in deja:
            continue
        sql = chemin.read_text(encoding="utf-8")
        # Une migration et son enregistrement dans la même transaction : une
        # migration à moitié appliquée n'existerait qu'au prix de cette ligne.
        with connexion.transaction():
            connexion.execute(sql)
            _migrer_noter(connexion, numero, nom)
        appliquees.append(nom)
    return appliquees


def _migrer_deja_appliquees(connexion: psycopg.Connection) -> set[int]:
    """Les numéros déjà passés. Préfixe `_migrer` : voir `PREFIXE_EXEMPT` des invariants."""
    lignes: Iterable[tuple[int]] = connexion.execute(
        "SELECT numero FROM migrations"
    ).fetchall()
    return {numero for (numero,) in lignes}


def _migrer_noter(connexion: psycopg.Connection, numero: int, nom: str) -> None:
    """Note qu'une migration est passée. Préfixe `_migrer` : voir les invariants."""
    connexion.execute(
        "INSERT INTO migrations (numero, nom) VALUES (%s, %s)", (numero, nom)
    )


__all__ = [
    "DOSSIER_MIGRATIONS",
    "ErreurMigration",
    "appliquer_migrations",
    "migrations_disponibles",
    "ouvrir",
]

"""Les consignes aux agents (`AGENTS.md`, `CLAUDE.md`) ne citent que ce qui existe.

Un chemin cité entre backticks doit exister dans le dépôt ; une commande
`uv run <outil>` doit désigner un outil installé dans l'environnement, et
`npm run <script>` un script de `front/package.json`. Aucun réseau : on lit
des fichiers et le dossier `bin/` de l'interpréteur courant.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOCUMENTS = ("AGENTS.md", "CLAUDE.md")

#: Fichiers cités mais écrits en parallèle sur d'autres branches. À VIDER dès
#: qu'ils sont mergés dans `main` : ils seront alors vérifiés comme les autres.
A_VENIR = set()

#: Un chemin court est cherché à la racine, puis dans le paquet
#: (`cli.py`, `activites/` se lisent comme des modules de `src/ourouler/`).
BASES = (RACINE, RACINE / "src" / "ourouler")

EXTENSIONS = r"(md|py|toml|json|ya?ml|ts|tsx|mdc|lock|txt|cfg)"
RE_FICHIER = re.compile(rf"^[\w.-]*\w\.{EXTENSIONS}$")
RE_DOSSIER_CACHE = re.compile(r"^\.(gitignore|github|claude|cursor)\b")
RE_BACKTICKS = re.compile(r"`([^`\n]+)`")


def _ressemble_a_un_chemin(jeton: str) -> bool:
    if any(c in jeton for c in " <>*~:$") or jeton.startswith("-"):
        return False
    return "/" in jeton or bool(RE_FICHIER.match(jeton)) or bool(RE_DOSSIER_CACHE.match(jeton))


def chemins_cites(texte: str) -> set[str]:
    return {j for j in RE_BACKTICKS.findall(texte) if _ressemble_a_un_chemin(j)}


def _texte(nom: str) -> str:
    return (RACINE / nom).read_text(encoding="utf-8")


@pytest.mark.parametrize("document", DOCUMENTS)
def test_les_chemins_cites_existent(document: str):
    cites = chemins_cites(_texte(document))
    assert cites, f"{document} ne cite aucun chemin : l'extraction est cassée"
    absents = sorted(c for c in cites - A_VENIR if not any((base / c).exists() for base in BASES))
    assert not absents, f"{document} cite des chemins absents du dépôt : {absents}"


@pytest.mark.parametrize("document", DOCUMENTS)
def test_les_outils_uv_run_sont_installes(document: str):
    binaires = Path(sys.executable).parent
    outils = set(re.findall(r"\buv run ([\w-]+)", _texte(document)))
    manquants = sorted(o for o in outils if not (binaires / o).exists())
    assert not manquants, f"{document} cite `uv run` sur des outils absents : {manquants}"


@pytest.mark.parametrize("document", DOCUMENTS)
def test_les_scripts_npm_run_existent(document: str):
    scripts = json.loads(_texte("front/package.json"))["scripts"]
    cites = set(re.findall(r"\bnpm run ([\w:-]+)", _texte(document)))
    inconnus = sorted(cites - scripts.keys())
    assert not inconnus, f"{document} cite des scripts npm absents : {inconnus}"


def test_agents_md_cite_bien_des_commandes():
    """Sinon les deux tests de commandes seraient verts sans rien vérifier."""
    texte = _texte("AGENTS.md")
    assert re.search(r"\buv run ", texte)
    assert re.search(r"\bnpm run ", texte)


def test_claude_md_importe_agents_md():
    assert _texte("CLAUDE.md").splitlines()[0] == "@AGENTS.md"


def test_l_extraction_ecarte_ce_qui_n_est_pas_un_chemin():
    texte = "`uv sync --frozen` `.fit` `--regenerer-golden` `velo` `src/ourouler/` `AGENTS.md`"
    assert chemins_cites(texte) == {"src/ourouler/", "AGENTS.md"}

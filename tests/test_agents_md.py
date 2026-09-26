"""Les documents qui décrivent le dépôt ne citent que ce qui existe.

Un chemin cité entre backticks doit exister dans le dépôt ; une commande
`uv run <outil>` doit désigner un outil installé dans l'environnement, et
`npm run <script>` un script de `front/package.json`. Aucun réseau : on lit
des fichiers et le dossier `bin/` de l'interpréteur courant.

N8 (constat 13 de la revue) étend la vérification des chemins, jusqu'ici
limitée à `AGENTS.md`/`CLAUDE.md`, à `README.md`, `ARCHITECTURE.md`,
`CONTRIBUTING.md` et `docs/*.md` (pas `docs/journal/`, le matériau brut).
Même logique qu'avant (extraction par backticks, existence dans le dépôt) ;
la seule différence est que ces documents plus larges citent aussi des
identifiants externes (image Docker, dépôt GitHub), des chemins relatifs à
leur propre dossier (`docs/LISEZMOI.md` → `../AGENTS.md`), et des chemins en
table qui ne portent qu'un nom de fichier (`ARCHITECTURE.md`, colonne
« Fichiers principaux ») — d'où `_existe` (recherche aussi par nom seul,
n'importe où sous le dépôt) et `IGNORES` (ce qui ressemble à un chemin sans
en être un, documenté cas par cas, jamais par un joker).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOCUMENTS = ("AGENTS.md", "CLAUDE.md")

#: N8, constat 13 : les mêmes chemins, vérifiés aussi dans les documents
#: publics qui décrivent le dépôt. `docs/*.md` est un glob non récursif :
#: `docs/journal/` (le matériau brut, pas relu) en est exclu de fait.
DOCUMENTS_PUBLICS = ("README.md", "ARCHITECTURE.md", "CONTRIBUTING.md")
DOCS_RACINE = tuple(sorted(f"docs/{p.name}" for p in (RACINE / "docs").glob("*.md")))
DOCUMENTS_ETENDUS = DOCUMENTS + DOCUMENTS_PUBLICS + DOCS_RACINE

#: Fichiers cités mais écrits en parallèle sur d'autres branches. À VIDER dès
#: qu'ils sont mergés dans `main` : ils seront alors vérifiés comme les autres.
A_VENIR: set[str] = set()

#: Jetons qui ressemblent à un chemin sans en être un, par document. Jamais
#: un joker : chaque entrée est un jeton exact, avec sa raison ici.
#:
#: - `config.toml` / `service.toml` (`docs/inviter.md`, `docs/services_externes.md`) :
#:   les fichiers réels du service hébergé, jamais commités (`.gitignore`) —
#:   cités par leur nom, pas par un chemin du dépôt.
#: - `docs/guide_ligne_de_commande.md` : `sorties/` est le dossier de sortie
#:   par défaut de la ligne de commande, écrit au lancement, jamais commité.
#: - `docs/ouverture_plan.md` : un plan antérieur à la phase de nettoyage
#:   (rangement en `docs/decisions/`, jamais fait — voir `docs/journal/questions/`)
#:   et des raccourcis vers des modules déjà déplacés ou renommés depuis, sous
#:   un ancien chemin ou sans leur extension, assumés comme tels dans la prose ;
#:   et `.claude/` (agents et `settings.json` de Claude Code), retiré du dépôt
#:   et gardé en local, que le plan cite pour dire ce retrait.
IGNORES: dict[str, frozenset[str]] = {
    "docs/guide_ligne_de_commande.md": frozenset({"sorties/"}),
    "docs/inviter.md": frozenset({"config.toml", "service.toml"}),
    "docs/services_externes.md": frozenset({"service.toml"}),
    "docs/ouverture_plan.md": frozenset(
        {
            ".claude/",
            ".claude/agents/",
            "settings.json",
            "docs/decisions/",
            "docs/decisions/Qnn",
            "docs/journal/questions/…#Qnn",
            "front/.vite/deps/",
            "physique/commande",
            "services/calibrer",
            "services/comptes",
            "stockage/calibrations",
            "tests/validation/",
            "api/client.ts",
            "api/routes.py",
            "boucle/trace.py",
            "cli.py",
            "CLAUDE.local.md",
        }
    ),
}

#: Un chemin court est cherché à la racine, puis dans le paquet Python et le
#: front (`cli/`, `activites/` comme modules de `src/ourouler/` ;
#: `api/client.ts` comme module de `front/src/`).
BASES = (RACINE, RACINE / "src" / "ourouler", RACINE / "front" / "src")

#: Dossiers jamais parcourus par la recherche « par nom seul » : générés,
#: jamais la source qu'un document devrait citer.
DOSSIERS_EXCLUS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    "dist",
    "build",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
}

EXTENSIONS = r"(md|py|toml|json|ya?ml|ts|tsx|mdc|lock|txt|cfg)"
RE_FICHIER = re.compile(rf"^[\w.-]*\w\.{EXTENSIONS}$")
RE_DOSSIER_CACHE = re.compile(r"^\.(gitignore|github|claude|cursor)\b")
RE_BACKTICKS = re.compile(r"`([^`\n]+)`")

#: Un premier segment qui ressemble à un domaine (`ghcr.io/…`, `garmin.com/…`)
#: signale un identifiant externe, jamais un chemin de ce dépôt.
RE_DOMAINE = re.compile(r"^[\w.-]+\.[A-Za-z]{2,}$")


def _ressemble_a_un_chemin(jeton: str) -> bool:
    if any(c in jeton for c in " <>*~:$=") or jeton.startswith("-") or jeton.startswith("/"):
        return False
    if "/" not in jeton:
        return bool(RE_FICHIER.match(jeton)) or bool(RE_DOSSIER_CACHE.match(jeton))
    if RE_DOMAINE.match(jeton.split("/", 1)[0]):
        return False
    if jeton.endswith("/"):
        return True
    dernier = jeton.rsplit("/", 1)[-1]
    if "." in dernier and not RE_FICHIER.match(dernier):
        # un symbole pointé (`module.fonction`), pas un nom de fichier
        return False
    return True


def chemins_cites(texte: str) -> set[str]:
    return {j for j in RE_BACKTICKS.findall(texte) if _ressemble_a_un_chemin(j)}


def _texte(nom: str) -> str:
    return (RACINE / nom).read_text(encoding="utf-8")


def _existe_par_nom(nom: str, *, dossier: bool = False) -> bool:
    """Cherche `nom` n'importe où sous le dépôt, hors dossiers générés.

    Nécessaire pour les chemins en table d'`ARCHITECTURE.md`, qui ne portent
    qu'un nom de fichier relatif à la colonne « Paquet » de leur ligne — bien
    plus coûteux à résoudre précisément qu'à vérifier que le nom existe
    quelque part de légitime.
    """
    for chemin in RACINE.rglob(nom):
        if any(partie in DOSSIERS_EXCLUS for partie in chemin.parts):
            continue
        if dossier and not chemin.is_dir():
            continue
        return True
    return False


def _existe(document: str, jeton: str) -> bool:
    if "/" not in jeton:
        return any((base / jeton).exists() for base in BASES) or _existe_par_nom(jeton)
    candidat = jeton.rstrip("/")
    bases = (*BASES, (RACINE / document).parent)
    if any((base / candidat).exists() for base in bases):
        return True
    if jeton.endswith("/"):
        return _existe_par_nom(candidat.rsplit("/", 1)[-1], dossier=True)
    return False


@pytest.mark.parametrize("document", DOCUMENTS_ETENDUS)
def test_les_chemins_cites_existent(document: str):
    cites = chemins_cites(_texte(document))
    assert cites, f"{document} ne cite aucun chemin : l'extraction est cassée"
    ignores = IGNORES.get(document, frozenset())
    absents = sorted(c for c in cites - A_VENIR - ignores if not _existe(document, c))
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

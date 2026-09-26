"""Réécrit les imports et les cibles de monkeypatch vers les modules déplacés.

Lots 3 et 4 du plan de restructuration (`docs/ouverture_plan.md` §6) : des
modules passent au noyau, et leur ancien chemin ne garde qu'un réexport
temporaire. Un `monkeypatch.setattr` qui vise un module de réexport ne
remplace rien dans le vrai module : le test passerait sans rien tester. Ce
script fait donc suivre **tous** les chemins, pas seulement les imports.

    uv run python scripts/reecrire_imports.py --mesurer   # compte, ne touche à rien
    uv run python scripts/reecrire_imports.py             # réécrit src/ et tests/

Ce qu'il réécrit, dans chaque fichier `.py` de `src/` et `tests/` :

- le nom pointé d'un ancien module, partout où il apparaît : `from … import`,
  `import …`, attribut `ourouler.boucle.trace.X`, chaîne
  `"ourouler.boucle.trace.X"` (cible de `monkeypatch.setattr`, de `patch`,
  d'`importorskip`) ;
- `from ourouler.boucle import trace` et ses variantes, où l'ancien module est
  un nom importé depuis son paquet : la ligne se scinde, le nom garde son
  alias (`from ourouler.noyau import activite as modele`).

Il laisse les modules de réexport eux-mêmes, le noyau et
`tests/test_architecture.py` (sa table nomme les anciens chemins exprès).
Le lot 4 y a ajouté le modèle de séance et les zones, le lot 6 la carte HTML
(`sortie/carte.py` → `rendu/carte.py`).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

#: Ancien module → nouveau module.
DEPLACEMENTS: dict[str, str] = {
    "ourouler.boucle.trace": "ourouler.noyau.trace",
    "ourouler.activites.modele": "ourouler.noyau.activite",
    "ourouler.erreurs": "ourouler.noyau.erreurs",
    "ourouler.proprietaire": "ourouler.noyau.proprietaire",
    # lot 4
    "ourouler.seance.modele": "ourouler.noyau.seance",
    "ourouler.seance.zones": "ourouler.noyau.zones",
    # lot 6 : la carte HTML passe au rendu
    "ourouler.sortie.carte": "ourouler.rendu.carte",
}

#: Fichiers qui nomment les anciens chemins exprès.
EPARGNES = {
    "src/ourouler/boucle/trace.py",
    "src/ourouler/activites/modele.py",
    "src/ourouler/erreurs.py",
    "src/ourouler/proprietaire.py",
    "src/ourouler/seance/modele.py",
    "src/ourouler/seance/zones.py",
    "src/ourouler/sortie/carte.py",
    "tests/test_architecture.py",
}


def _motif(ancien: str) -> re.Pattern[str]:
    # Ni précédé d'un identifiant ou d'un point (`ourouler.api.erreurs` n'est
    # pas `ourouler.erreurs`), ni suivi d'un identifiant (`erreurs_x`).
    return re.compile(r"(?<![\w.])" + re.escape(ancien) + r"(?!\w)")


MOTIFS = {ancien: _motif(ancien) for ancien in DEPLACEMENTS}

#: `from paquet import a, b as c` sur une ligne, sans parenthèse.
FROM_IMPORT = re.compile(
    r"^(?P<retrait>\s*)from (?P<paquet>[\w.]+) import (?P<noms>[^()#\n]+?)(?P<fin>\s*(#.*)?)$"
)


def _scinder_from(ligne: str) -> tuple[str, int]:
    """`from ourouler.boucle import trace, gpx` → deux lignes. Rend (texte, nb de noms déplacés)."""
    m = FROM_IMPORT.match(ligne)
    if not m:
        return ligne, 0
    paquet = m["paquet"]
    restants, deplaces = [], []
    for morceau in (n.strip() for n in m["noms"].split(",")):
        nom, _, alias = morceau.partition(" as ")
        cible = DEPLACEMENTS.get(f"{paquet}.{nom.strip()}")
        if cible is None:
            restants.append(morceau)
            continue
        nouveau_paquet, _, nouveau_nom = cible.rpartition(".")
        alias = alias.strip() or nom.strip()
        importe = nouveau_nom if alias == nouveau_nom else f"{nouveau_nom} as {alias}"
        deplaces.append((nouveau_paquet, importe))
    if not deplaces:
        return ligne, 0
    lignes = [f"{m['retrait']}from {p} import {n}{m['fin']}" for p, n in deplaces]
    if restants:
        lignes.insert(0, f"{m['retrait']}from {paquet} import {', '.join(restants)}{m['fin']}")
    return "\n".join(lignes), len(deplaces)


def _paquets_de_modules_deplaces() -> set[str]:
    return {ancien.rpartition(".")[0] for ancien in DEPLACEMENTS}


def reecrire(source: str) -> tuple[str, int]:
    """Le texte réécrit et le nombre de remplacements faits."""
    compte = 0
    paquets = _paquets_de_modules_deplaces()
    lignes = []
    for ligne in source.split("\n"):
        if any(re.match(rf"\s*from {re.escape(p)} import ", ligne) for p in paquets):
            if "(" in ligne and ")" not in ligne:
                # Import parenthésé sur plusieurs lignes depuis un paquet qui
                # perd un module : on ne devine pas, on s'arrête.
                raise SystemExit(f"import sur plusieurs lignes, à vérifier et scinder à la main : {ligne!r}")
            ligne, n = _scinder_from(ligne)
            compte += n
        for ancien, motif in MOTIFS.items():
            ligne, n = motif.subn(DEPLACEMENTS[ancien], ligne)
            compte += n
        lignes.append(ligne)
    return "\n".join(lignes), compte


def fichiers() -> list[Path]:
    resultat = []
    for dossier in ("src", "tests"):
        for chemin in sorted((RACINE / dossier).rglob("*.py")):
            relatif = chemin.relative_to(RACINE).as_posix()
            if relatif not in EPARGNES and not relatif.startswith("src/ourouler/noyau/"):
                resultat.append(chemin)
    return resultat


# --- mesure --------------------------------------------------------------------


def _module_de(expr: ast.expr, alias: dict[str, str]) -> str | None:
    """Le module que désigne `expr` (`trace`, `ourouler.boucle.trace`), s'il est connu."""
    if isinstance(expr, ast.Name):
        return alias.get(expr.id)
    if isinstance(expr, ast.Attribute):
        base = _module_de(expr.value, alias)
        return f"{base}.{expr.attr}" if base else None
    return None


def _alias_de_modules(arbre: ast.AST) -> dict[str, str]:
    """Nom local → module, pour les imports de modules du fichier (tous niveaux confondus)."""
    alias: dict[str, str] = {}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for a in noeud.names:
                if a.asname:
                    alias[a.asname] = a.name
                else:
                    racine = a.name.split(".")[0]
                    alias[racine] = racine
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            for a in noeud.names:
                alias[a.asname or a.name] = f"{noeud.module}.{a.name}"
        elif isinstance(noeud, ast.FunctionDef):
            # Fixture `def trace(): return pytest.importorskip("ourouler.boucle.trace")` :
            # un test qui la reçoit en paramètre tient le module sous ce nom.
            for retour in (n for n in ast.walk(noeud) if isinstance(n, ast.Return)):
                appel = retour.value
                if (
                    isinstance(appel, ast.Call)
                    and isinstance(appel.func, ast.Attribute)
                    and appel.func.attr in ("importorskip", "import_module")
                    and appel.args
                    and isinstance(appel.args[0], ast.Constant)
                    and isinstance(appel.args[0].value, str)
                ):
                    alias[noeud.name] = appel.args[0].value
    return alias


def _vise_un_ancien(nom: str | None) -> str | None:
    if not nom:
        return None
    for ancien in DEPLACEMENTS:
        if nom == ancien or nom.startswith(ancien + "."):
            return ancien
    return None


def setattr_vers_anciens(chemin: Path) -> list[str]:
    """Chaque `setattr`/`delattr`/`patch` du fichier qui vise un ancien module."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    alias = _alias_de_modules(arbre)
    trouves = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call) or not noeud.args:
            continue
        fonction = noeud.func.attr if isinstance(noeud.func, ast.Attribute) else getattr(noeud.func, "id", "")
        if fonction not in ("setattr", "delattr", "patch", "object", "setitem"):
            continue
        premier = noeud.args[0]
        if isinstance(premier, ast.Constant) and isinstance(premier.value, str):
            vise = _vise_un_ancien(premier.value)
        else:
            vise = _vise_un_ancien(_module_de(premier, alias))
        if vise:
            trouves.append(f"{chemin.relative_to(RACINE)}:{noeud.lineno} → {vise}")
    return trouves


def references_restantes(chemin: Path) -> int:
    texte = chemin.read_text(encoding="utf-8")
    return sum(len(m.findall(texte)) for m in MOTIFS.values())


def imports_vers_anciens(chemin: Path) -> int:
    """Les instructions d'import qui nomment un ancien module (directement ou comme nom importé)."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    compte = 0
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            compte += any(_vise_un_ancien(a.name) for a in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            compte += bool(
                _vise_un_ancien(noeud.module)
                or any(_vise_un_ancien(f"{noeud.module}.{a.name}") for a in noeud.names)
            )
    return compte


def mesurer() -> int:
    setattrs, imports, refs = [], {"src": 0, "tests": 0}, 0
    for chemin in fichiers():
        setattrs += setattr_vers_anciens(chemin)
        imports[chemin.relative_to(RACINE).parts[0]] += imports_vers_anciens(chemin)
        refs += references_restantes(chemin)
    print(f"setattr/patch visant un ancien module : {len(setattrs)}")
    for ligne in setattrs:
        print("  " + ligne)
    print(f"imports vers un ancien module : src {imports['src']}, tests {imports['tests']}")
    print(f"mentions restantes d'un ancien chemin (texte) : {refs}")
    return len(setattrs)


def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--mesurer", action="store_true", help="compter sans rien écrire")
    args = parseur.parse_args()
    if args.mesurer:
        return 1 if mesurer() else 0
    total, touches = 0, 0
    for chemin in fichiers():
        source = chemin.read_text(encoding="utf-8")
        nouveau, n = reecrire(source)
        if n:
            chemin.write_text(nouveau, encoding="utf-8")
            total += n
            touches += 1
    print(f"{total} remplacements dans {touches} fichiers")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Vérifie pyright contre une ligne de base figée, sans faire régresser.

Lot N9-T (adoption de pyright) : les erreurs déjà présentes le jour de
l'adoption sont tolérées, mais gelées dans `pyright_ligne_de_base.json`
(à la racine du dépôt). Ce script :

- lance ``pyright --outputjson`` sur le périmètre défini par
  ``[tool.pyright]`` (``pyproject.toml``, aujourd'hui ``src/`` seulement) ;
- compare chaque erreur à la ligne de base par (fichier, règle, message),
  **sans numéro de ligne** — un simple déplacement de ligne (renommage plus
  haut dans le fichier, ajout d'une ligne au-dessus) ne doit pas casser la
  comparaison ;
- échoue (code de sortie 1) si une erreur **nouvelle** apparaît, absente de
  la ligne de base ;
- signale, sans faire échouer, les erreurs de la ligne de base qui ont
  disparu — c'est un progrès, mais qui invite à régénérer le fichier pour
  que la ligne de base baisse réellement (elle ne baisse jamais toute
  seule : un compte qui reste inchangé ne prouve rien).

Usage, depuis la racine du dépôt :

    uv run python scripts/pyright_ligne_de_base.py           # vérifie
    uv run python scripts/pyright_ligne_de_base.py --regenerer  # réécrit la ligne de base

``--regenerer`` ne se justifie que lorsqu'une erreur a disparu (jamais pour
en faire entrer une nouvelle : dans ce cas, corriger le code plutôt que la
ligne de base). N'appelle aucun réseau ; ne lit que ce que pyright rend.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FICHIER_LIGNE_DE_BASE = RACINE / "pyright_ligne_de_base.json"


def executer_pyright() -> dict:
    """Lance pyright en JSON et rend le rapport, que la commande réussisse ou non.

    Le code de sortie de pyright n'est pas le signal utilisé ici (il vaut 1
    dès qu'il existe une erreur, y compris une erreur de la ligne de base) :
    seul le contenu JSON compte.
    """
    resultat = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson"],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=False,
    )
    if not resultat.stdout.strip():
        print(resultat.stderr, file=sys.stderr)
        raise SystemExit("pyright n'a rendu aucune sortie JSON (voir stderr ci-dessus).")
    return json.loads(resultat.stdout)


def cle_erreur(diagnostic: dict) -> tuple[str, str, str]:
    """Identité d'une erreur pour la comparaison : (fichier, règle, message).

    Volontairement sans numéro de ligne, pour ne pas casser la comparaison
    au moindre déplacement de ligne dans un fichier par ailleurs inchangé.
    """
    fichier = diagnostic.get("file", "")
    try:
        fichier = str(Path(fichier).resolve().relative_to(RACINE))
    except ValueError:
        pass
    regle = diagnostic.get("rule", "(sans regle)")
    message = diagnostic.get("message", "")
    return (fichier, regle, message)


def erreurs_du_rapport(rapport: dict) -> list[dict]:
    return [d for d in rapport.get("generalDiagnostics", []) if d.get("severity") == "error"]


def charger_ligne_de_base() -> list[dict]:
    if not FICHIER_LIGNE_DE_BASE.exists():
        return []
    return json.loads(FICHIER_LIGNE_DE_BASE.read_text(encoding="utf-8"))


def ecrire_ligne_de_base(erreurs: list[dict]) -> None:
    entrees = [{"fichier": f, "regle": r, "message": m} for f, r, m in sorted(cle_erreur(e) for e in erreurs)]
    FICHIER_LIGNE_DE_BASE.write_text(
        json.dumps(entrees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def cles_de_la_ligne_de_base(entrees: list[dict]) -> Counter[tuple[str, str, str]]:
    return Counter((e["fichier"], e["regle"], e["message"]) for e in entrees)


def verifier() -> int:
    rapport = executer_pyright()
    erreurs_actuelles = erreurs_du_rapport(rapport)
    # Compté, pas seulement présent : une deuxième erreur identique dans le même
    # fichier est une erreur nouvelle.
    cles_actuelles = Counter(cle_erreur(e) for e in erreurs_actuelles)
    ligne_de_base = charger_ligne_de_base()
    cles_figees = cles_de_la_ligne_de_base(ligne_de_base)

    nouvelles = sorted((cles_actuelles - cles_figees).elements())
    disparues = sorted((cles_figees - cles_actuelles).elements())

    if disparues:
        print(f"{len(disparues)} erreur(s) de la ligne de base ont disparu (progrès) :")
        for fichier, regle, message in disparues:
            print(f"  - {fichier} [{regle}] {message}")
        print(
            "  Régénérer la ligne de base pour la faire baisser : "
            "uv run python scripts/pyright_ligne_de_base.py --regenerer"
        )

    if nouvelles:
        print(f"{len(nouvelles)} nouvelle(s) erreur(s) pyright, absente(s) de la ligne de base :")
        for fichier, regle, message in nouvelles:
            print(f"  - {fichier} [{regle}] {message}")
        print(f"\n{len(erreurs_actuelles)} erreur(s) au total (ligne de base : {len(ligne_de_base)}).")
        return 1

    print(
        f"Aucune nouvelle erreur pyright. {len(erreurs_actuelles)} erreur(s) au total "
        f"(ligne de base : {len(ligne_de_base)})."
    )
    return 0


def regenerer() -> int:
    rapport = executer_pyright()
    erreurs = erreurs_du_rapport(rapport)
    ecrire_ligne_de_base(erreurs)
    print(f"Ligne de base réécrite : {len(erreurs)} erreur(s) dans {FICHIER_LIGNE_DE_BASE.name}.")
    return 0


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--regenerer",
        action="store_true",
        help="Réécrit la ligne de base à partir de l'état actuel (seulement pour une baisse).",
    )
    args = analyseur.parse_args()
    return regenerer() if args.regenerer else verifier()


if __name__ == "__main__":
    raise SystemExit(main())

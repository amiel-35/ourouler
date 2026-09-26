"""Vérifie les exceptions de `[tool.ruff.lint.per-file-ignores]`.

Les seuils de complexité et de taille (`C901`, `PLR0912`, `PLR0915`,
`PLR0917`) sont des règles ruff vérifiées. Ce qui les dépasse est listé en
exceptions dans `pyproject.toml`, chacune précédée d'un commentaire de l'une
de ces deux formes :

- « exception datée : n fonction(s), à retirer avant AAAA-MM-JJ » :
  une dette à rembourser avant l'échéance ;
- « exception permanente : <raison> » : assumée, pour une raison écrite
  (un script de mesure hors produit, par exemple).

Ce test :
- relit `pyproject.toml` (aucun réseau) ;
- relance ruff, en un seul sous-processus, sur l'ensemble des fichiers
  exceptés, avec les mêmes seuils que la configuration du dépôt ;
- échoue si une exception ne sert plus (le fichier est redevenu conforme
  pour ce code : il faut retirer l'exception) ;
- échoue si la date d'échéance d'une exception datée est dépassée.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PYPROJECT = RACINE / "pyproject.toml"

CODES_BORNES = ["C901", "PLR0912", "PLR0915", "PLR0917"]

# Un commentaire d'exception, immédiatement suivi de la ligne
# `"chemin" = ["CODE", ...]`.
MOTIF_EXCEPTION = re.compile(
    r"# exception datée : \d+ fonction\(s\), à retirer avant (?P<date>\d{4}-\d{2}-\d{2})\n"
    r'"(?P<chemin>[^"]+)" = \[(?P<codes>[^\]]*)\]'
)

# Un commentaire d'exception permanente : une raison non vide, puis la ligne.
MOTIF_PERMANENTE = re.compile(
    r"# exception permanente : (?P<raison>\S[^\n]*)\n"
    r'"(?P<chemin>[^"]+)" = \[(?P<codes>[^\]]*)\]'
)


def charger_config() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def charger_exceptions_commentees() -> dict[str, str]:
    """Associe chaque chemin excepté à la date de son commentaire."""
    texte = PYPROJECT.read_text(encoding="utf-8")
    dates_par_chemin: dict[str, str] = {}
    for m in MOTIF_EXCEPTION.finditer(texte):
        dates_par_chemin[m.group("chemin")] = m.group("date")
    return dates_par_chemin


def charger_exceptions_permanentes() -> dict[str, str]:
    """Associe chaque chemin excepté pour de bon à la raison écrite."""
    texte = PYPROJECT.read_text(encoding="utf-8")
    return {m.group("chemin"): m.group("raison") for m in MOTIF_PERMANENTE.finditer(texte)}


def test_chaque_exception_a_un_commentaire_date_ou_une_raison() -> None:
    config = charger_config()
    per_file_ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    datees = charger_exceptions_commentees()
    permanentes = charger_exceptions_permanentes()

    assert not set(datees) & set(permanentes), "une exception est à la fois datée et permanente"
    assert set(per_file_ignores) == set(datees) | set(permanentes), (
        "Chaque entrée de [tool.ruff.lint.per-file-ignores] doit être précédée d'un "
        "commentaire « exception datée : n fonction(s), à retirer avant AAAA-MM-JJ » "
        "ou « exception permanente : <raison> »."
    )


def test_aucune_echeance_depassee() -> None:
    dates_par_chemin = charger_exceptions_commentees()
    aujourdhui = date.today()

    depassees = {}
    for chemin, texte_date in dates_par_chemin.items():
        echeance = date.fromisoformat(texte_date)
        if echeance < aujourdhui:
            depassees[chemin] = texte_date

    assert not depassees, (
        "Échéance(s) d'exception dépassée(s) : découper la fonction, ou repousser "
        f"la date en le justifiant : {depassees}"
    )


def test_exceptions_encore_necessaires() -> None:
    """Chaque code excepté doit encore être en infraction dans son fichier.

    Une exception qui ne sert plus (le fichier est devenu conforme pour ce
    code) doit être retirée de `per-file-ignores`.
    """
    config = charger_config()
    lint = config["tool"]["ruff"]["lint"]
    per_file_ignores: dict[str, list[str]] = lint["per-file-ignores"]
    mccabe = lint.get("mccabe", {})
    pylint = lint.get("pylint", {})

    max_complexity = mccabe["max-complexity"]
    max_branches = pylint["max-branches"]
    max_statements = pylint["max-statements"]
    max_positional_args = pylint["max-positional-args"]

    fichiers = sorted(per_file_ignores)
    assert fichiers, "Aucune exception à vérifier : le test n'a plus lieu d'être ?"

    for chemin in fichiers:
        assert (RACINE / chemin).is_file(), f"Fichier excepté introuvable : {chemin}"

    # Un seul sous-processus pour tous les fichiers exceptés : rapide (<10s)
    # même avec de nombreuses entrées.
    resultat = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            *fichiers,
            "--select",
            ",".join(CODES_BORNES),
            "--isolated",
            "--output-format",
            "json",
            "--config",
            f"lint.mccabe.max-complexity={max_complexity}",
            "--config",
            f"lint.pylint.max-branches={max_branches}",
            "--config",
            f"lint.pylint.max-statements={max_statements}",
            "--config",
            f"lint.pylint.max-positional-args={max_positional_args}",
        ],
        cwd=RACINE,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert resultat.returncode in (0, 1), (
        f"ruff a échoué à s'exécuter : {resultat.stderr}"
    )

    import json

    violations = json.loads(resultat.stdout)
    codes_par_fichier: dict[str, set[str]] = {chemin: set() for chemin in fichiers}
    for v in violations:
        chemin_relatif = str(Path(v["filename"]).resolve().relative_to(RACINE))
        codes_par_fichier.setdefault(chemin_relatif, set()).add(v["code"])

    inutiles = []
    for chemin, codes_ignores in per_file_ignores.items():
        codes_encore_en_infraction = codes_par_fichier.get(chemin, set())
        for code in codes_ignores:
            if code not in codes_encore_en_infraction:
                inutiles.append((chemin, code))

    assert not inutiles, (
        "Exception(s) qui ne servent plus (le fichier est devenu conforme, "
        f"à retirer de per-file-ignores) : {inutiles}"
    )


def test_per_file_ignores_ne_depasse_pas_les_codes_bornes() -> None:
    """Les exceptions ne portent que sur les règles de taille/complexité."""
    config = charger_config()
    per_file_ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]

    for chemin, codes in per_file_ignores.items():
        inconnus = set(codes) - set(CODES_BORNES)
        assert not inconnus, f"{chemin} : code(s) hors des règles de taille et de complexité : {inconnus}"

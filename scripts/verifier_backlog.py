#!/usr/bin/env python3
"""Vérifie mécaniquement docs/backlog/sprints.toml.

Outillage de dépôt (pas du cœur ourouler) : lu en local et en CI. Vérifie des
règles statiques toujours (structure, cohérence des statuts, existence des
fiches/chantiers référencés) et, si --base est fourni, des règles contre une
version antérieure du fichier (via git) pour empêcher un remaniement furtif
d'un sprint déjà figé/en cours et tout retour en arrière de statut.

Usage :
    uv run python scripts/verifier_backlog.py
    uv run python scripts/verifier_backlog.py --etat
    uv run python scripts/verifier_backlog.py --json
    uv run python scripts/verifier_backlog.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

# Chantiers connus : nom -> chemin relatif (depuis la racine du dépôt) du
# fichier qui doit exister pour que le chantier soit considéré valide.
CHANTIERS: dict[str, str] = {
    "ouverture": "docs/ouverture_plan.md",
}

STATUTS_SPRINT_VALIDES = {"esquisse", "fige", "en_cours", "clos"}
STATUTS_ELEMENT_VALIDES = {"prevu", "en_cours", "livre", "abandonne"}
CLES_SPRINT_VALIDES = {"numero", "statut", "titre", "derogations", "element"}
CLES_ELEMENT_VALIDES = {"chantier", "fiche", "statut", "pr", "raison"}

# Ordre attendu DANS LE FICHIER (règle C) : clos* puis au plus un en_cours
# puis fige* puis esquisse* — une suite non décroissante selon ces rangs.
ORDRE_SEQUENCE_FICHIER = {"clos": 0, "en_cours": 1, "fige": 2, "esquisse": 3}

# Ordre de PROGRESSION DANS LE TEMPS d'un même sprint (règle G) : un sprint
# n'évolue que esquisse -> fige -> en_cours -> clos, jamais en arrière.
ORDRE_PROGRESSION = {"esquisse": 0, "fige": 1, "en_cours": 2, "clos": 3}


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------


def charger_toml(chemin: Path) -> dict[str, Any]:
    with chemin.open("rb") as f:
        return tomllib.load(f)


def charger_toml_depuis_git(racine: Path, base: str) -> tuple[dict[str, Any] | None, str | None]:
    """Retourne (structure, message_erreur). Un des deux est None."""
    resultat = subprocess.run(
        ["git", "show", f"{base}:docs/backlog/sprints.toml"],
        cwd=racine,
        capture_output=True,
        text=True,
    )
    if resultat.returncode != 0:
        return None, (
            f"Impossible de lire docs/backlog/sprints.toml dans {base} "
            f"(règles F et G sautées) : {resultat.stderr.strip()}"
        )
    try:
        return tomllib.loads(resultat.stdout), None
    except tomllib.TOMLDecodeError as exc:
        return None, (
            f"docs/backlog/sprints.toml dans {base} n'est pas un TOML valide "
            f"(règles F et G sautées) : {exc}"
        )


# ---------------------------------------------------------------------------
# Règles statiques (A à E)
# ---------------------------------------------------------------------------


def _contexte(numero_sprint: int | None, element_desc: str | None) -> str:
    if numero_sprint is None:
        return "[fichier]"
    if element_desc is None:
        return f"[sprint {numero_sprint}]"
    return f"[sprint {numero_sprint}, élément {element_desc}]"


def _identifiant_element(element: dict[str, Any]) -> str:
    if "fiche" in element:
        return f"fiche={element['fiche']!r}"
    if "chantier" in element:
        return f"chantier={element['chantier']!r}"
    return "sans identifiant"


def _valider_derogations(valeur: Any, ctx: str, violations: list[str]) -> None:
    if not isinstance(valeur, list) or not all(isinstance(v, str) for v in valeur):
        violations.append(f"{ctx} derogations doit être une liste de chaînes")
        return
    for entree in valeur:
        partie_date = entree.split(" : ", 1)
        if len(partie_date) != 2:
            violations.append(
                f"{ctx} dérogation mal formée (attendu 'JJ/MM/AAAA : raison') : {entree!r}"
            )
            continue
        date_str, raison = partie_date
        morceaux = date_str.split("/")
        date_ok = len(morceaux) == 3 and all(m.isdigit() for m in morceaux)
        if not date_ok:
            violations.append(f"{ctx} date de dérogation invalide : {entree!r}")
        if len(raison) > 120:
            violations.append(f"{ctx} raison de dérogation > 120 caractères : {entree!r}")


def _valider_cles_et_types_sprint(sprint: dict[str, Any], ctx: str) -> list[str]:
    violations: list[str] = []
    cles_inconnues = set(sprint.keys()) - CLES_SPRINT_VALIDES
    if cles_inconnues:
        violations.append(f"{ctx} clé(s) inconnue(s) : {sorted(cles_inconnues)}")

    if not isinstance(sprint.get("numero"), int):
        violations.append(f"{ctx} 'numero' doit être un entier")

    statut = sprint.get("statut")
    if not isinstance(statut, str) or statut not in STATUTS_SPRINT_VALIDES:
        violations.append(f"{ctx} 'statut' invalide : {statut!r}")

    titre = sprint.get("titre")
    if not isinstance(titre, str):
        violations.append(f"{ctx} 'titre' doit être une chaîne")
    else:
        if "\n" in titre:
            violations.append(f"{ctx} 'titre' contient un saut de ligne")
        if len(titre) > 80:
            violations.append(f"{ctx} 'titre' dépasse 80 caractères")

    if "derogations" in sprint:
        _valider_derogations(sprint["derogations"], ctx, violations)

    return violations


def _violations_coherence_statut_sprint(
    statut: Any, statuts_elements: list[Any], ctx: str
) -> list[str]:
    violations: list[str] = []
    if statut == "clos":
        for s in statuts_elements:
            if s not in {"livre", "abandonne"}:
                violations.append(
                    f"{ctx} sprint clos mais contient un élément de statut {s!r} "
                    "(seuls livre/abandonne sont autorisés)"
                )
    if statut in {"fige", "esquisse"}:
        for s in statuts_elements:
            if s not in {"prevu", "abandonne"}:
                violations.append(
                    f"{ctx} sprint {statut} mais contient un élément de statut {s!r} "
                    "(seuls prevu/abandonne sont autorisés)"
                )
    return violations


def _valider_sprint_statique(
    sprint: dict[str, Any], racine: Path, identifiants_vus: set[str]
) -> list[str]:
    numero = sprint.get("numero")
    ctx = _contexte(numero if isinstance(numero, int) else None, None)

    violations = _valider_cles_et_types_sprint(sprint, ctx)

    elements = sprint.get("element", [])
    if not isinstance(elements, list):
        violations.append(f"{ctx} 'element' doit être une liste")
        elements = []

    for element in elements:
        violations.extend(
            _valider_element_statique(element, numero, racine, identifiants_vus)
        )

    statut = sprint.get("statut")
    statuts_elements = [
        e.get("statut") for e in elements if isinstance(e, dict) and isinstance(e.get("statut"), str)
    ]
    violations.extend(_violations_coherence_statut_sprint(statut, statuts_elements, ctx))

    return violations


def _valider_cles_et_types_element(element: dict[str, Any], ctx: str) -> list[str]:
    violations: list[str] = []
    cles_inconnues = set(element.keys()) - CLES_ELEMENT_VALIDES
    if cles_inconnues:
        violations.append(f"{ctx} clé(s) inconnue(s) : {sorted(cles_inconnues)}")

    a_fiche = "fiche" in element
    a_chantier = "chantier" in element
    if a_fiche and a_chantier:
        violations.append(f"{ctx} a à la fois 'fiche' et 'chantier' (une seule autorisée)")
    elif not a_fiche and not a_chantier:
        violations.append(f"{ctx} n'a ni 'fiche' ni 'chantier'")

    statut = element.get("statut")
    if not isinstance(statut, str) or statut not in STATUTS_ELEMENT_VALIDES:
        violations.append(f"{ctx} 'statut' invalide : {statut!r}")

    return violations


def _valider_pr_et_raison(element: dict[str, Any], ctx: str) -> list[str]:
    violations: list[str] = []
    statut = element.get("statut")

    if "pr" in element and not isinstance(element["pr"], int):
        violations.append(f"{ctx} 'pr' doit être un entier")
    if statut == "livre" and "pr" not in element:
        violations.append(f"{ctx} statut livre exige la clé 'pr'")
    if "pr" in element and statut != "livre":
        violations.append(f"{ctx} 'pr' présent mais statut != livre")

    if "raison" in element:
        raison = element["raison"]
        if not isinstance(raison, str):
            violations.append(f"{ctx} 'raison' doit être une chaîne")
        elif len(raison) > 120:
            violations.append(f"{ctx} 'raison' dépasse 120 caractères")
    if statut == "abandonne" and "raison" not in element:
        violations.append(f"{ctx} statut abandonne exige la clé 'raison'")
    if "raison" in element and statut != "abandonne":
        violations.append(f"{ctx} 'raison' présente mais statut != abandonne")

    return violations


def _valider_reference_fiche(
    fiche: Any, racine: Path, identifiants_vus: set[str], ctx: str
) -> list[str]:
    violations: list[str] = []
    if not isinstance(fiche, str):
        return [f"{ctx} 'fiche' doit être une chaîne"]

    if fiche in identifiants_vus:
        violations.append(f"{ctx} fiche référencée plusieurs fois dans le fichier")
    identifiants_vus.add(fiche)

    chemin_fiche = racine / "docs" / "backlog" / f"{fiche}.md"
    if not chemin_fiche.exists():
        violations.append(f"{ctx} fichier introuvable : {chemin_fiche}")
        return violations

    lignes = chemin_fiche.read_text(encoding="utf-8").splitlines()
    if not any(ligne.strip() in {"Type : feature", "Type : bug"} for ligne in lignes):
        violations.append(
            f"{ctx} {chemin_fiche} n'a pas de ligne 'Type : feature' ou 'Type : bug'"
        )
    return violations


def _valider_reference_chantier(
    chantier: Any, racine: Path, identifiants_vus: set[str], ctx: str
) -> list[str]:
    violations: list[str] = []
    if not isinstance(chantier, str):
        return [f"{ctx} 'chantier' doit être une chaîne"]

    if chantier in identifiants_vus:
        violations.append(f"{ctx} chantier référencé plusieurs fois dans le fichier")
    identifiants_vus.add(chantier)

    if chantier not in CHANTIERS:
        violations.append(f"{ctx} chantier inconnu (absent de CHANTIERS) : {chantier!r}")
        return violations

    chemin_chantier = racine / CHANTIERS[chantier]
    if not chemin_chantier.exists():
        violations.append(f"{ctx} fichier de chantier introuvable : {chemin_chantier}")
    return violations


def _valider_element_statique(
    element: Any, numero_sprint: Any, racine: Path, identifiants_vus: set[str]
) -> list[str]:
    if not isinstance(element, dict):
        ctx = _contexte(numero_sprint if isinstance(numero_sprint, int) else None, "?")
        return [f"{ctx} élément qui n'est pas une table"]

    ident = _identifiant_element(element)
    ctx = _contexte(numero_sprint if isinstance(numero_sprint, int) else None, ident)

    violations = _valider_cles_et_types_element(element, ctx)
    violations.extend(_valider_pr_et_raison(element, ctx))

    # Règle D : existence et unicité (l'élément en_cours vs sprint parent est
    # vérifié à part dans violations_statiques, qui a la vue d'ensemble).
    if "fiche" in element:
        violations.extend(_valider_reference_fiche(element["fiche"], racine, identifiants_vus, ctx))
    elif "chantier" in element:
        violations.extend(
            _valider_reference_chantier(element["chantier"], racine, identifiants_vus, ctx)
        )

    return violations


def _violations_element_vs_sprint_parent(sprints: list[dict[str, Any]]) -> list[str]:
    """Règle E (suite) : en_cours/livre de l'élément vs statut du sprint parent."""
    violations: list[str] = []
    for sprint in sprints:
        if not isinstance(sprint, dict):
            continue
        statut_sprint = sprint.get("statut")
        numero = sprint.get("numero")
        for element in sprint.get("element", []) or []:
            if not isinstance(element, dict):
                continue
            statut_element = element.get("statut")
            ctx = _contexte(
                numero if isinstance(numero, int) else None, _identifiant_element(element)
            )
            if statut_element == "en_cours" and statut_sprint != "en_cours":
                violations.append(
                    f"{ctx} élément en_cours mais le sprint parent n'est pas en_cours "
                    f"(statut sprint : {statut_sprint!r})"
                )
            if statut_element == "livre" and statut_sprint not in {"en_cours", "clos"}:
                violations.append(
                    f"{ctx} élément livré mais le sprint parent n'est ni en_cours ni clos "
                    f"(statut sprint : {statut_sprint!r})"
                )
    return violations


def _violations_numerotation(sprints: list[dict[str, Any]]) -> list[str]:
    """Règle B : numéros uniques et strictement croissants dans l'ordre du fichier."""
    violations: list[str] = []
    numeros_valides = [s.get("numero") for s in sprints if isinstance(s.get("numero"), int)]

    vus: set[int] = set()
    for n in numeros_valides:
        if n in vus:
            violations.append(f"[fichier] numéro de sprint dupliqué : {n}")
        vus.add(n)

    for precedent, suivant in zip(numeros_valides, numeros_valides[1:], strict=False):
        if not (suivant > precedent):
            violations.append(
                f"[fichier] numéros de sprint non strictement croissants : {precedent} -> {suivant}"
            )
    return violations


def _violations_monotonie_statuts(sprints: list[dict[str, Any]]) -> list[str]:
    """Règle C : suite clos* puis au plus un en_cours puis fige* puis esquisse*."""
    violations: list[str] = []
    statuts_ordre = [s.get("statut") for s in sprints]
    statuts_connus = [s for s in statuts_ordre if s in ORDRE_SEQUENCE_FICHIER]
    if len(statuts_connus) != len(statuts_ordre):
        return violations  # statut invalide déjà signalé ailleurs (règle A)

    rangs = [ORDRE_SEQUENCE_FICHIER[s] for s in statuts_connus]
    for precedent, suivant in zip(rangs, rangs[1:], strict=False):
        if suivant < precedent:
            violations.append(
                "[fichier] statuts de sprint non monotones (attendu clos* puis "
                f"au plus un en_cours puis fige* puis esquisse*) : {statuts_ordre}"
            )
            break

    nb_en_cours = statuts_connus.count("en_cours")
    if nb_en_cours > 1:
        violations.append(f"[fichier] plus d'un sprint en_cours ({nb_en_cours}) : {statuts_ordre}")
    nb_fige = statuts_connus.count("fige")
    if nb_fige > 2:
        violations.append(f"[fichier] plus de 2 sprints figés ({nb_fige})")
    nb_esquisse = statuts_connus.count("esquisse")
    if nb_esquisse > 2:
        violations.append(f"[fichier] plus de 2 sprints esquissés ({nb_esquisse})")
    return violations


def violations_statiques(donnees: dict[str, Any], racine: Path) -> list[str]:
    violations: list[str] = []
    sprints = donnees.get("sprint", [])
    if not isinstance(sprints, list):
        return ["[fichier] la clé 'sprint' doit être une liste"]

    identifiants_vus: set[str] = set()
    for sprint in sprints:
        if not isinstance(sprint, dict):
            violations.append("[fichier] un sprint n'est pas une table")
            continue
        violations.extend(_valider_sprint_statique(sprint, racine, identifiants_vus))

    sprints_tables = [s for s in sprints if isinstance(s, dict)]
    violations.extend(_violations_element_vs_sprint_parent(sprints_tables))
    violations.extend(_violations_numerotation(sprints_tables))
    violations.extend(_violations_monotonie_statuts(sprints_tables))

    return violations


# ---------------------------------------------------------------------------
# Règles contre une base git (F et G) — fonctions pures, testables sans git.
# ---------------------------------------------------------------------------


def _index_sprints(donnees: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        s["numero"]: s
        for s in donnees.get("sprint", [])
        if isinstance(s, dict) and isinstance(s.get("numero"), int)
    }


def _identifiants_elements(sprint: dict[str, Any]) -> set[str]:
    ids = set()
    for element in sprint.get("element", []) or []:
        if not isinstance(element, dict):
            continue
        if "fiche" in element:
            ids.add(f"fiche:{element['fiche']}")
        elif "chantier" in element:
            ids.add(f"chantier:{element['chantier']}")
    return ids


def _a_derogation_nouvelle(sprint_courant: dict[str, Any], sprint_base: dict[str, Any]) -> bool:
    derog_courantes = sprint_courant.get("derogations") or []
    derog_base = set(sprint_base.get("derogations") or [])
    return any(d not in derog_base for d in derog_courantes)


def violations_contre_base(base: dict[str, Any], courant: dict[str, Any]) -> list[str]:
    """Règles F et G, comparaison pure entre deux structures déjà parsées."""
    violations: list[str] = []
    sprints_base = _index_sprints(base)
    sprints_courant = _index_sprints(courant)

    for numero, sprint_base in sprints_base.items():
        ctx = f"[sprint {numero}]"

        # Règle G : un sprint de la base doit rester présent.
        if numero not in sprints_courant:
            violations.append(f"{ctx} a disparu du fichier (présent dans la base)")
            continue

        sprint_courant = sprints_courant[numero]
        statut_base = sprint_base.get("statut")
        statut_courant = sprint_courant.get("statut")

        # Règle G : pas de retour en arrière de statut de sprint.
        if statut_base in ORDRE_PROGRESSION and statut_courant in ORDRE_PROGRESSION:
            if ORDRE_PROGRESSION[statut_courant] < ORDRE_PROGRESSION[statut_base]:
                violations.append(
                    f"{ctx} statut revenu en arrière : {statut_base!r} -> {statut_courant!r}"
                )

        # Règle F : un sprint fige/en_cours dans la base garde le même ensemble
        # d'éléments, sauf dérogation nouvelle.
        if statut_base in {"fige", "en_cours"}:
            ids_base = _identifiants_elements(sprint_base)
            ids_courant = _identifiants_elements(sprint_courant)
            if ids_base != ids_courant and not _a_derogation_nouvelle(sprint_courant, sprint_base):
                violations.append(
                    f"{ctx} était {statut_base!r} et ses éléments ont changé sans dérogation "
                    f"nouvelle : base={sorted(ids_base)} courant={sorted(ids_courant)}"
                )

        # Règle G : un élément livré/abandonné dans la base ne change plus de statut.
        elements_base = {
            _cle_element(e): e.get("statut")
            for e in sprint_base.get("element", []) or []
            if isinstance(e, dict)
        }
        elements_courant = {
            _cle_element(e): e.get("statut")
            for e in sprint_courant.get("element", []) or []
            if isinstance(e, dict)
        }
        for cle, statut_elem_base in elements_base.items():
            if statut_elem_base not in {"livre", "abandonne"}:
                continue
            statut_elem_courant = elements_courant.get(cle)
            if statut_elem_courant is not None and statut_elem_courant != statut_elem_base:
                violations.append(
                    f"{ctx} élément {cle} était {statut_elem_base!r} dans la base, "
                    f"ne peut plus changer (trouvé {statut_elem_courant!r})"
                )

    return violations


def _cle_element(element: dict[str, Any]) -> str:
    if "fiche" in element:
        return f"fiche:{element['fiche']}"
    if "chantier" in element:
        return f"chantier:{element['chantier']}"
    return "?"


# ---------------------------------------------------------------------------
# Vue --etat / --json
# ---------------------------------------------------------------------------


def _titre_fiche(chemin: Path) -> str:
    if not chemin.exists():
        return "(fiche introuvable)"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("# "):
            return ligne[2:].strip()
    return "(sans titre)"


def _type_fiche(chemin: Path) -> str | None:
    if not chemin.exists():
        return None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne in {"Type : feature", "Type : bug"}:
            return ligne.split(":", 1)[1].strip()
    return None


def construire_etat(donnees: dict[str, Any], racine: Path) -> dict[str, Any]:
    sprints_actifs = []
    fiches_planifiees: set[str] = set()

    for sprint in donnees.get("sprint", []) or []:
        if not isinstance(sprint, dict):
            continue
        elements_sortie = []
        for element in sprint.get("element", []) or []:
            if not isinstance(element, dict):
                continue
            if "fiche" in element:
                fiches_planifiees.add(element["fiche"])
                chemin_fiche = racine / "docs" / "backlog" / f"{element['fiche']}.md"
                titre = _titre_fiche(chemin_fiche)
            else:
                titre = element.get("chantier", "?")
            elements_sortie.append(
                {
                    "identifiant": element.get("fiche") or element.get("chantier"),
                    "type": "fiche" if "fiche" in element else "chantier",
                    "statut": element.get("statut"),
                    "titre": titre,
                }
            )
        if sprint.get("statut") != "clos":
            sprints_actifs.append(
                {
                    "numero": sprint.get("numero"),
                    "statut": sprint.get("statut"),
                    "titre": sprint.get("titre"),
                    "elements": elements_sortie,
                }
            )

    dossier_backlog = racine / "docs" / "backlog"
    non_planifie = []
    if dossier_backlog.exists():
        for fichier in sorted(dossier_backlog.glob("*.md")):
            nom = fichier.stem
            if nom in fiches_planifiees:
                continue
            non_planifie.append({"fiche": nom, "type": _type_fiche(fichier)})

    return {"sprints": sprints_actifs, "non_planifie": non_planifie}


def imprimer_etat(etat: dict[str, Any]) -> None:
    for sprint in etat["sprints"]:
        print(f"Sprint {sprint['numero']} — {sprint['statut']} — {sprint['titre']}")
        for element in sprint["elements"]:
            print(f"  - [{element['statut']}] {element['titre']} ({element['identifiant']})")
    print()
    print("Non planifié :")
    if not etat["non_planifie"]:
        print("  (aucun)")
    for entree in etat["non_planifie"]:
        print(f"  - {entree['fiche']} (Type : {entree['type']})")


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Vérifie docs/backlog/sprints.toml")
    parser.add_argument("--racine", type=Path, default=None, help="Racine du dépôt (surcharge)")
    parser.add_argument("--base", default=None, help="Référence git à comparer (ex. origin/main)")
    parser.add_argument("--etat", action="store_true", help="Affiche l'état lisible")
    parser.add_argument("--json", action="store_true", help="Affiche l'état en JSON")
    args = parser.parse_args()

    racine = args.racine or Path(__file__).resolve().parent.parent
    chemin_toml = racine / "docs" / "backlog" / "sprints.toml"
    donnees = charger_toml(chemin_toml)

    violations = violations_statiques(donnees, racine)

    if args.base:
        base_donnees, message_erreur = charger_toml_depuis_git(racine, args.base)
        if message_erreur:
            print(message_erreur)
        else:
            assert base_donnees is not None
            violations.extend(violations_contre_base(base_donnees, donnees))

    if args.etat or args.json:
        etat = construire_etat(donnees, racine)
        if args.json:
            print(json.dumps({"etat": etat, "violations": violations}, ensure_ascii=False, indent=2))
        else:
            imprimer_etat(etat)
            if violations:
                print()
                print("Violations :")
                for v in violations:
                    print(f"  - {v}")
        return 1 if violations else 0

    if not violations:
        print("backlog conforme")
        return 0

    for v in violations:
        print(v)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

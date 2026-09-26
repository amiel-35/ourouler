#!/usr/bin/env python3
"""Vérifie mécaniquement docs/backlog/sprints.toml.

Outillage de dépôt (pas du cœur ourouler) : lu en local et en CI. Vérifie des
règles statiques toujours (structure, cohérence des statuts, existence des
fiches/chantiers référencés) et, si --base est fourni, des règles contre une
version antérieure du fichier (via git) pour empêcher un remaniement furtif
d'un sprint déjà figé/en cours et tout retour en arrière de statut.

Avec --base, toute impossibilité de comparer (racine hors dépôt git, référence
introuvable, TOML de la base illisible) est une violation. Seul cas toléré :
la référence existe mais le fichier n'y existe pas encore (création), ce qui
est dit explicitement.

Usage :
    uv run python scripts/verifier_backlog.py
    uv run python scripts/verifier_backlog.py --etat
    uv run python scripts/verifier_backlog.py --json
    uv run python scripts/verifier_backlog.py --base origin/main
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

CHEMIN_RELATIF_TOML = "docs/backlog/sprints.toml"

# Chantiers connus : nom -> chemin relatif (depuis la racine du dépôt) du
# fichier qui doit exister pour que le chantier soit considéré valide.
CHANTIERS: dict[str, str] = {
    "ouverture": "docs/ouverture_plan.md",
}

STATUTS_SPRINT_VALIDES = {"esquisse", "fige", "en_cours", "clos"}
STATUTS_ELEMENT_VALIDES = {"prevu", "en_cours", "livre", "abandonne"}
CLES_RACINE_VALIDES = {"sprint"}
CLES_SPRINT_VALIDES = {"numero", "statut", "titre", "derogations", "element"}
CLES_ELEMENT_VALIDES = {"chantier", "fiche", "statut", "pr", "raison"}

# Nom de fiche : minuscules, chiffres, tirets simples entre des mots.
MOTIF_FICHE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Dérogation : « JJ/MM/AAAA : raison ».
MOTIF_DEROGATION = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) : (.*)$", re.DOTALL)
LONGUEUR_MIN_RAISON_DEROGATION = 10
LONGUEUR_MAX_RAISON = 120
LONGUEUR_MAX_TITRE = 80
# La ligne « Type : ... » d'une fiche doit se trouver dans ses premières lignes.
LIGNES_EN_TETE_FICHE = 10
LIGNES_TYPE_FICHE = {"Type : feature", "Type : bug"}

# Ordre attendu DANS LE FICHIER (règle C) : clos* puis au plus un en_cours
# puis fige* puis esquisse* — une suite non décroissante selon ces rangs.
ORDRE_SEQUENCE_FICHIER = {"clos": 0, "en_cours": 1, "fige": 2, "esquisse": 3}

# Ordre de PROGRESSION DANS LE TEMPS d'un même sprint (règle G) : un sprint
# n'évolue que esquisse -> fige -> en_cours -> clos, d'une étape au plus par
# diff, jamais en arrière.
ORDRE_PROGRESSION = {"esquisse": 0, "fige": 1, "en_cours": 2, "clos": 3}

MESSAGE_CREATION = "création : {chemin} absent de {base}, règles F et G sans objet"


# ---------------------------------------------------------------------------
# Petits outils de type
# ---------------------------------------------------------------------------


def _est_entier(valeur: Any) -> bool:
    """Entier strict : un booléen Python est un int, on le refuse."""
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def _est_texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _elements(sprint: dict[str, Any]) -> list[dict[str, Any]]:
    """Les éléments d'un sprint qui sont bien des tables (les autres sont
    signalés par la règle A)."""
    elements = sprint.get("element", [])
    if not isinstance(elements, list):
        return []
    return [e for e in elements if isinstance(e, dict)]


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------


def charger_toml(chemin: Path) -> dict[str, Any]:
    with chemin.open("rb") as f:
        return tomllib.load(f)


def _git(racine: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=racine, capture_output=True, text=True
    )


def charger_toml_depuis_git(
    racine: Path, base: str
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    """Lit sprints.toml dans la référence git `base`.

    Retourne (structure, violations, message_creation) :
    - structure lue, [], None : comparaison possible ;
    - None, [violation], None : impossible de comparer, c'est une violation ;
    - None, [], message : la référence existe mais le fichier n'y existe pas
      encore (création), F et G sont sans objet.
    """
    if not racine.is_dir():
        return None, [f"[base] racine introuvable : {racine}"], None

    toplevel = _git(racine, "rev-parse", "--show-toplevel")
    if toplevel.returncode != 0:
        return None, [f"[base] {racine} n'est pas un dépôt git : impossible de comparer à {base}"], None
    if Path(toplevel.stdout.strip()).resolve() != racine.resolve():
        return None, [
            f"[base] {racine} n'est pas la racine du dépôt git "
            f"({toplevel.stdout.strip()}) : impossible de comparer à {base}"
        ], None

    ref = _git(racine, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if ref.returncode != 0:
        return None, [f"[base] référence git introuvable : {base!r}"], None

    existe = _git(racine, "cat-file", "-e", f"{base}:{CHEMIN_RELATIF_TOML}")
    if existe.returncode != 0:
        return None, [], MESSAGE_CREATION.format(chemin=CHEMIN_RELATIF_TOML, base=base)

    contenu = _git(racine, "show", f"{base}:{CHEMIN_RELATIF_TOML}")
    if contenu.returncode != 0:
        return None, [
            f"[base] lecture de {CHEMIN_RELATIF_TOML} dans {base} impossible : "
            f"{contenu.stderr.strip()}"
        ], None
    try:
        return tomllib.loads(contenu.stdout), [], None
    except tomllib.TOMLDecodeError as exc:
        return None, [
            f"[base] {CHEMIN_RELATIF_TOML} dans {base} n'est pas un TOML valide : {exc}"
        ], None


# ---------------------------------------------------------------------------
# Règles statiques (A à E)
# ---------------------------------------------------------------------------


def _contexte(numero_sprint: Any, element_desc: str | None) -> str:
    if not _est_entier(numero_sprint):
        return "[fichier]" if element_desc is None else f"[sprint ?, élément {element_desc}]"
    if element_desc is None:
        return f"[sprint {numero_sprint}]"
    return f"[sprint {numero_sprint}, élément {element_desc}]"


def _identifiant_element(element: dict[str, Any]) -> str:
    if "fiche" in element:
        return f"fiche={element['fiche']!r}"
    if "chantier" in element:
        return f"chantier={element['chantier']!r}"
    return "sans identifiant"


def _ctx_element(sprint: dict[str, Any], element: dict[str, Any]) -> str:
    return _contexte(sprint.get("numero"), _identifiant_element(element))


# --- Règle A : dérogations --------------------------------------------------


def valider_entree_derogation(entree: str) -> str | None:
    """Retourne None si l'entrée est bien « JJ/MM/AAAA : raison », sinon le
    motif du refus. La date doit exister au calendrier."""
    correspondance = MOTIF_DEROGATION.match(entree)
    if correspondance is None:
        return "mal formée (attendu 'JJ/MM/AAAA : raison')"
    jour, mois, annee, raison = correspondance.groups()
    try:
        datetime.date(int(annee), int(mois), int(jour))
    except ValueError:
        return "date inexistante au calendrier"
    raison = raison.strip()
    if len(raison) < LONGUEUR_MIN_RAISON_DEROGATION:
        return f"raison de moins de {LONGUEUR_MIN_RAISON_DEROGATION} caractères"
    if len(raison) > LONGUEUR_MAX_RAISON:
        return f"raison de plus de {LONGUEUR_MAX_RAISON} caractères"
    if "\n" in raison:
        return "raison sur plusieurs lignes"
    return None


def _valider_derogations(valeur: Any, ctx: str) -> list[str]:
    if not isinstance(valeur, list) or not all(isinstance(v, str) for v in valeur):
        return [f"{ctx} derogations doit être une liste de chaînes"]
    violations: list[str] = []
    for entree in valeur:
        motif = valider_entree_derogation(entree)
        if motif is not None:
            violations.append(f"{ctx} dérogation invalide, {motif} : {entree!r}")
    vues: set[str] = set()
    for entree in valeur:
        if entree in vues:
            violations.append(f"{ctx} dérogation en double : {entree!r}")
        vues.add(entree)
    return violations


# --- Règle A : clés et types --------------------------------------------------


def _valider_cles_et_types_sprint(sprint: dict[str, Any], ctx: str) -> list[str]:
    violations: list[str] = []
    cles_inconnues = set(sprint.keys()) - CLES_SPRINT_VALIDES
    if cles_inconnues:
        violations.append(f"{ctx} clé(s) inconnue(s) : {sorted(cles_inconnues)}")

    if not _est_entier(sprint.get("numero")):
        violations.append(f"{ctx} 'numero' doit être un entier (booléen refusé)")

    statut = sprint.get("statut")
    if not isinstance(statut, str) or statut not in STATUTS_SPRINT_VALIDES:
        violations.append(f"{ctx} 'statut' invalide : {statut!r}")

    titre = sprint.get("titre")
    if not isinstance(titre, str):
        violations.append(f"{ctx} 'titre' doit être une chaîne")
    else:
        if not titre.strip():
            violations.append(f"{ctx} 'titre' vide")
        if "\n" in titre or "\r" in titre:
            violations.append(f"{ctx} 'titre' contient un saut de ligne")
        if len(titre) > LONGUEUR_MAX_TITRE:
            violations.append(f"{ctx} 'titre' dépasse {LONGUEUR_MAX_TITRE} caractères")

    if "derogations" in sprint:
        violations.extend(_valider_derogations(sprint["derogations"], ctx))

    if "element" in sprint and not isinstance(sprint["element"], list):
        violations.append(f"{ctx} 'element' doit être une liste")

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

    if "pr" in element and not _est_entier(element["pr"]):
        violations.append(f"{ctx} 'pr' doit être un entier (booléen refusé)")

    if "raison" in element:
        raison = element["raison"]
        if not isinstance(raison, str):
            violations.append(f"{ctx} 'raison' doit être une chaîne")
        elif not raison.strip():
            violations.append(f"{ctx} 'raison' vide")
        elif len(raison) > LONGUEUR_MAX_RAISON:
            violations.append(f"{ctx} 'raison' dépasse {LONGUEUR_MAX_RAISON} caractères")

    return violations


# --- Règle D : références (fiches, chantiers) et unicité --------------------


def ligne_type_fiche(texte: str) -> str | None:
    """Cherche « Type : feature » ou « Type : bug » dans les premières lignes
    de la fiche, hors bloc de code Markdown. Retourne 'feature', 'bug' ou None."""
    dans_bloc_code = False
    for ligne in texte.splitlines()[:LIGNES_EN_TETE_FICHE]:
        nette = ligne.strip()
        if nette.startswith("```") or nette.startswith("~~~"):
            dans_bloc_code = not dans_bloc_code
            continue
        if dans_bloc_code:
            continue
        if nette in LIGNES_TYPE_FICHE:
            return nette.split(":", 1)[1].strip()
    return None


def _noms_fichiers_backlog(racine: Path) -> set[str]:
    """Noms exacts (casse comprise) des fichiers de docs/backlog/ : on ne se
    fie pas à Path.exists(), qui ignore la casse sur certains systèmes."""
    dossier = racine / "docs" / "backlog"
    if not dossier.is_dir():
        return set()
    return {entree.name for entree in dossier.iterdir() if entree.is_file()}


def _valider_reference_fiche(
    fiche: Any, racine: Path, noms_fichiers: set[str], ctx: str
) -> list[str]:
    if not isinstance(fiche, str):
        return [f"{ctx} 'fiche' doit être une chaîne"]
    if not MOTIF_FICHE.match(fiche):
        return [f"{ctx} nom de fiche invalide (attendu {MOTIF_FICHE.pattern}) : {fiche!r}"]

    nom_fichier = f"{fiche}.md"
    chemin_fiche = racine / "docs" / "backlog" / nom_fichier
    if nom_fichier not in noms_fichiers:
        return [f"{ctx} fichier introuvable (nom exact, casse comprise) : {chemin_fiche}"]

    if ligne_type_fiche(chemin_fiche.read_text(encoding="utf-8")) is None:
        return [
            f"{ctx} {chemin_fiche} n'a pas de ligne 'Type : feature' ou 'Type : bug' "
            f"dans ses {LIGNES_EN_TETE_FICHE} premières lignes, hors bloc de code"
        ]
    return []


def _valider_reference_chantier(chantier: Any, racine: Path, ctx: str) -> list[str]:
    if not isinstance(chantier, str):
        return [f"{ctx} 'chantier' doit être une chaîne"]
    if chantier not in CHANTIERS:
        return [f"{ctx} chantier inconnu (absent de CHANTIERS) : {chantier!r}"]
    chemin_chantier = racine / CHANTIERS[chantier]
    if not chemin_chantier.is_file():
        return [f"{ctx} fichier de chantier introuvable : {chemin_chantier}"]
    return []


def _violations_unicite(sprints: list[dict[str, Any]]) -> list[str]:
    """Une fiche n'apparaît qu'une fois, un chantier aussi : deux espaces de
    noms séparés (une fiche et un chantier de même nom ne se confondent pas)."""
    violations: list[str] = []
    for espace, libelle in (("fiche", "fiche référencée"), ("chantier", "chantier référencé")):
        vus: set[str] = set()
        for sprint in sprints:
            for element in _elements(sprint):
                valeur = element.get(espace)
                if not isinstance(valeur, str):
                    continue
                if valeur in vus:
                    violations.append(
                        f"{_ctx_element(sprint, element)} {libelle} plusieurs fois dans le fichier"
                    )
                vus.add(valeur)
    return violations


def _valider_element_statique(
    element: Any, sprint: dict[str, Any], racine: Path, noms_fichiers: set[str]
) -> list[str]:
    if not isinstance(element, dict):
        return [f"{_contexte(sprint.get('numero'), '?')} élément qui n'est pas une table"]

    ctx = _ctx_element(sprint, element)
    violations = _valider_cles_et_types_element(element, ctx)
    if "fiche" in element:
        violations.extend(_valider_reference_fiche(element["fiche"], racine, noms_fichiers, ctx))
    elif "chantier" in element:
        violations.extend(_valider_reference_chantier(element["chantier"], racine, ctx))
    return violations


# --- Règle E : cohérence statut d'élément / statut de sprint ----------------
# Une fonction par sous-règle ; chacune prend un sprint et rend ses violations.


def regle_e_en_cours_exige_sprint_en_cours(sprint: dict[str, Any]) -> list[str]:
    """Un élément en_cours n'existe que dans le sprint en_cours."""
    statut_sprint = sprint.get("statut")
    if statut_sprint == "en_cours":
        return []
    return [
        f"{_ctx_element(sprint, e)} élément en_cours mais le sprint parent n'est pas en_cours "
        f"(statut sprint : {statut_sprint!r})"
        for e in _elements(sprint)
        if e.get("statut") == "en_cours"
    ]


def regle_e_livre_exige_pr_et_sprint_actif(sprint: dict[str, Any]) -> list[str]:
    """Un élément livré porte sa PR et son sprint est en_cours ou clos."""
    violations: list[str] = []
    statut_sprint = sprint.get("statut")
    for e in _elements(sprint):
        if e.get("statut") != "livre":
            continue
        if "pr" not in e:
            violations.append(f"{_ctx_element(sprint, e)} statut livre exige la clé 'pr'")
        if statut_sprint not in {"en_cours", "clos"}:
            violations.append(
                f"{_ctx_element(sprint, e)} élément livré mais le sprint parent n'est ni "
                f"en_cours ni clos (statut sprint : {statut_sprint!r})"
            )
    return violations


def regle_e_pr_reservee_au_livre(sprint: dict[str, Any]) -> list[str]:
    """La clé 'pr' n'a de sens que sur un élément livré."""
    return [
        f"{_ctx_element(sprint, e)} 'pr' présent mais statut != livre"
        for e in _elements(sprint)
        if "pr" in e and e.get("statut") != "livre"
    ]


def regle_e_abandonne_exige_raison(sprint: dict[str, Any]) -> list[str]:
    """Un élément abandonné dit pourquoi."""
    return [
        f"{_ctx_element(sprint, e)} statut abandonne exige la clé 'raison'"
        for e in _elements(sprint)
        if e.get("statut") == "abandonne" and "raison" not in e
    ]


def regle_e_raison_reservee_a_abandonne(sprint: dict[str, Any]) -> list[str]:
    """La clé 'raison' n'a de sens que sur un élément abandonné."""
    return [
        f"{_ctx_element(sprint, e)} 'raison' présente mais statut != abandonne"
        for e in _elements(sprint)
        if "raison" in e and e.get("statut") != "abandonne"
    ]


def regle_e_sprint_clos_termine(sprint: dict[str, Any]) -> list[str]:
    """Un sprint clos ne contient que du livré ou de l'abandonné."""
    if sprint.get("statut") != "clos":
        return []
    return [
        f"{_contexte(sprint.get('numero'), None)} sprint clos mais contient un élément de "
        f"statut {e.get('statut')!r} (seuls livre/abandonne sont autorisés)"
        for e in _elements(sprint)
        if e.get("statut") not in {"livre", "abandonne"}
    ]


def regle_e_sprint_non_commence(sprint: dict[str, Any]) -> list[str]:
    """Un sprint fige ou esquisse ne contient que du prévu ou de l'abandonné."""
    statut = sprint.get("statut")
    if statut not in {"fige", "esquisse"}:
        return []
    return [
        f"{_contexte(sprint.get('numero'), None)} sprint {statut} mais contient un élément de "
        f"statut {e.get('statut')!r} (seuls prevu/abandonne sont autorisés)"
        for e in _elements(sprint)
        if e.get("statut") not in {"prevu", "abandonne"}
    ]


REGLES_E = (
    regle_e_en_cours_exige_sprint_en_cours,
    regle_e_livre_exige_pr_et_sprint_actif,
    regle_e_pr_reservee_au_livre,
    regle_e_abandonne_exige_raison,
    regle_e_raison_reservee_a_abandonne,
    regle_e_sprint_clos_termine,
    regle_e_sprint_non_commence,
)


# --- Règles B et C : numérotation et ordre des statuts ----------------------


def _violations_numerotation(sprints: list[dict[str, Any]]) -> list[str]:
    """Règle B : numéros uniques et strictement croissants dans l'ordre du fichier."""
    violations: list[str] = []
    numeros_valides = [s.get("numero") for s in sprints if _est_entier(s.get("numero"))]

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
    """Règle C : suite clos* puis au plus un en_cours puis fige* (≤ 2) puis
    esquisse* (≤ 2)."""
    violations: list[str] = []
    statuts_ordre = [s.get("statut") for s in sprints]
    if any(s not in ORDRE_SEQUENCE_FICHIER for s in statuts_ordre):
        return violations  # statut invalide déjà signalé par la règle A

    rangs = [ORDRE_SEQUENCE_FICHIER[s] for s in statuts_ordre]
    for precedent, suivant in zip(rangs, rangs[1:], strict=False):
        if suivant < precedent:
            violations.append(
                "[fichier] statuts de sprint non monotones (attendu clos* puis "
                f"au plus un en_cours puis fige* puis esquisse*) : {statuts_ordre}"
            )
            break

    nb_en_cours = statuts_ordre.count("en_cours")
    if nb_en_cours > 1:
        violations.append(f"[fichier] plus d'un sprint en_cours ({nb_en_cours}) : {statuts_ordre}")
    nb_fige = statuts_ordre.count("fige")
    if nb_fige > 2:
        violations.append(f"[fichier] plus de 2 sprints figés ({nb_fige})")
    nb_esquisse = statuts_ordre.count("esquisse")
    if nb_esquisse > 2:
        violations.append(f"[fichier] plus de 2 sprints esquissés ({nb_esquisse})")
    return violations


def violations_statiques(donnees: dict[str, Any], racine: Path) -> list[str]:
    violations: list[str] = []

    cles_racine_inconnues = set(donnees.keys()) - CLES_RACINE_VALIDES
    if cles_racine_inconnues:
        violations.append(
            f"[fichier] clé(s) inconnue(s) à la racine (seule 'sprint' est permise) : "
            f"{sorted(cles_racine_inconnues)}"
        )

    sprints = donnees.get("sprint", [])
    if not isinstance(sprints, list):
        return violations + ["[fichier] la clé 'sprint' doit être une liste de tables [[sprint]]"]
    if not sprints:
        violations.append("[fichier] aucun [[sprint]] : au moins un sprint est exigé")

    noms_fichiers = _noms_fichiers_backlog(racine)
    sprints_tables: list[dict[str, Any]] = []
    for sprint in sprints:
        if not isinstance(sprint, dict):
            violations.append("[fichier] un sprint n'est pas une table")
            continue
        sprints_tables.append(sprint)
        violations.extend(_valider_cles_et_types_sprint(sprint, _contexte(sprint.get("numero"), None)))
        elements = sprint.get("element", [])
        for element in elements if isinstance(elements, list) else []:
            violations.extend(_valider_element_statique(element, sprint, racine, noms_fichiers))
        for regle in REGLES_E:
            violations.extend(regle(sprint))

    violations.extend(_violations_unicite(sprints_tables))
    violations.extend(_violations_numerotation(sprints_tables))
    violations.extend(_violations_monotonie_statuts(sprints_tables))
    return violations


# ---------------------------------------------------------------------------
# Règles contre une base git (F et G) — fonctions pures, testables sans git.
# ---------------------------------------------------------------------------


def _index_sprints(donnees: dict[str, Any]) -> dict[int, dict[str, Any]]:
    sprints = donnees.get("sprint", [])
    if not isinstance(sprints, list):
        return {}
    return {
        s["numero"]: s for s in sprints if isinstance(s, dict) and _est_entier(s.get("numero"))
    }


def _cle_element(element: dict[str, Any]) -> str:
    if "fiche" in element:
        return f"fiche:{element['fiche']}"
    if "chantier" in element:
        return f"chantier:{element['chantier']}"
    return "?"


def _index_elements(sprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {_cle_element(e): e for e in _elements(sprint)}


def _derogations(sprint: dict[str, Any]) -> list[Any]:
    valeur = sprint.get("derogations", [])
    return valeur if isinstance(valeur, list) else []


def _regle_g_transition_sprint(
    ctx: str, statut_base: Any, statut_courant: Any
) -> list[str]:
    """Pas de recul, au plus une étape, clos seulement depuis en_cours."""
    if statut_base not in ORDRE_PROGRESSION or statut_courant not in ORDRE_PROGRESSION:
        return []  # statut invalide : règle A
    ecart = ORDRE_PROGRESSION[statut_courant] - ORDRE_PROGRESSION[statut_base]
    if ecart < 0:
        return [f"{ctx} statut revenu en arrière : {statut_base!r} -> {statut_courant!r}"]
    violations: list[str] = []
    if ecart > 1:
        violations.append(
            f"{ctx} statut avancé de plus d'une étape en un diff : "
            f"{statut_base!r} -> {statut_courant!r}"
        )
    if statut_courant == "clos" and statut_base not in {"en_cours", "clos"}:
        violations.append(
            f"{ctx} clos alors qu'il n'était pas en_cours dans la base ({statut_base!r})"
        )
    return violations


def _regle_g_elements_termines_geles(
    ctx: str, sprint_base: dict[str, Any], sprint_courant: dict[str, Any]
) -> list[str]:
    """Un élément livré/abandonné dans la base reste dans le même sprint, avec
    exactement les mêmes champs."""
    violations: list[str] = []
    elements_courant = _index_elements(sprint_courant)
    for cle, element_base in _index_elements(sprint_base).items():
        if element_base.get("statut") not in {"livre", "abandonne"}:
            continue
        element_courant = elements_courant.get(cle)
        if element_courant is None:
            violations.append(
                f"{ctx} élément {cle} était {element_base.get('statut')!r} dans la base "
                "et a quitté ce sprint (il ne peut plus changer)"
            )
        elif element_courant != element_base:
            violations.append(
                f"{ctx} élément {cle} était {element_base.get('statut')!r} dans la base, "
                f"ne peut plus changer : base={element_base} courant={element_courant}"
            )
    return violations


def _regle_g_sprint_clos_gele(
    ctx: str, sprint_base: dict[str, Any], sprint_courant: dict[str, Any]
) -> list[str]:
    """Un sprint clos dans la base est identique en tout dans la version courante."""
    if sprint_base.get("statut") != "clos":
        return []
    identiques = (
        sprint_base.get("statut") == sprint_courant.get("statut")
        and sprint_base.get("titre") == sprint_courant.get("titre")
        and _derogations(sprint_base) == _derogations(sprint_courant)
        and _index_elements(sprint_base) == _index_elements(sprint_courant)
        and len(_elements(sprint_base)) == len(_elements(sprint_courant))
    )
    if identiques:
        return []
    return [f"{ctx} était clos dans la base et a été modifié (un sprint clos ne change plus)"]


def _regle_f_derogations_append_only(
    ctx: str, sprint_base: dict[str, Any], sprint_courant: dict[str, Any]
) -> list[str]:
    derog_base = _derogations(sprint_base)
    derog_courant = _derogations(sprint_courant)
    if derog_courant[: len(derog_base)] != derog_base:
        return [
            f"{ctx} dérogations modifiées : la liste de la base doit rester un préfixe exact "
            f"(ajouts en fin seulement) : base={derog_base} courant={derog_courant}"
        ]
    return []


def _regle_f_composition_figee(
    ctx: str, sprint_base: dict[str, Any], sprint_courant: dict[str, Any]
) -> list[str]:
    """Un sprint fige/en_cours dans la base garde ses éléments et son titre,
    sauf exactement une dérogation nouvelle dans ce diff ; une dérogation
    nouvelle sans changement est orpheline."""
    statut_base = sprint_base.get("statut")
    if statut_base not in {"fige", "en_cours"}:
        return []

    ids_base = set(_index_elements(sprint_base))
    ids_courant = set(_index_elements(sprint_courant))
    changements = []
    if ids_base != ids_courant:
        changements.append(f"éléments base={sorted(ids_base)} courant={sorted(ids_courant)}")
    if sprint_base.get("titre") != sprint_courant.get("titre"):
        changements.append(
            f"titre {sprint_base.get('titre')!r} -> {sprint_courant.get('titre')!r}"
        )

    derog_base = _derogations(sprint_base)
    derog_courant = _derogations(sprint_courant)
    if derog_courant[: len(derog_base)] != derog_base:
        return []  # déjà signalé par _regle_f_derogations_append_only
    nb_nouvelles = len(derog_courant) - len(derog_base)

    if changements and nb_nouvelles == 0:
        return [
            f"{ctx} était {statut_base!r} et a changé sans dérogation nouvelle : "
            + " ; ".join(changements)
        ]
    if changements and nb_nouvelles > 1:
        return [
            f"{ctx} était {statut_base!r} : {nb_nouvelles} dérogations nouvelles dans ce diff, "
            "exactement une est attendue pour couvrir le changement"
        ]
    if not changements and nb_nouvelles > 0:
        return [
            f"{ctx} dérogation nouvelle sans changement d'éléments ni de titre "
            f"({nb_nouvelles} ajoutée(s)) : une dérogation couvre un changement"
        ]
    return []


def _regle_g_nouveau_sprint_esquisse(ctx: str, sprint_courant: dict[str, Any]) -> list[str]:
    """Un sprint dont le numéro est absent de la base (fichier déjà existant,
    mais ce sprint précis y est nouveau) ne peut apparaître qu'en 'esquisse'.
    Toute autre valeur de statut pour un sprint tout neuf est une violation."""
    statut = sprint_courant.get("statut")
    if statut == "esquisse":
        return []
    return [
        f"{ctx} sprint nouveau (absent de la base) doit être 'esquisse', trouvé {statut!r}"
    ]


def violations_contre_base(base: dict[str, Any], courant: dict[str, Any]) -> list[str]:
    """Règles F et G, comparaison pure entre deux structures déjà parsées."""
    violations: list[str] = []
    sprints_base = _index_sprints(base)
    sprints_courant = _index_sprints(courant)

    for numero, sprint_base in sprints_base.items():
        ctx = f"[sprint {numero}]"
        sprint_courant = sprints_courant.get(numero)
        if sprint_courant is None:
            violations.append(f"{ctx} a disparu du fichier (présent dans la base)")
            continue

        violations.extend(
            _regle_g_transition_sprint(ctx, sprint_base.get("statut"), sprint_courant.get("statut"))
        )
        violations.extend(_regle_g_sprint_clos_gele(ctx, sprint_base, sprint_courant))
        violations.extend(_regle_g_elements_termines_geles(ctx, sprint_base, sprint_courant))
        violations.extend(_regle_f_derogations_append_only(ctx, sprint_base, sprint_courant))
        violations.extend(_regle_f_composition_figee(ctx, sprint_base, sprint_courant))

    for numero, sprint_courant in sprints_courant.items():
        if numero not in sprints_base:
            violations.extend(
                _regle_g_nouveau_sprint_esquisse(f"[sprint {numero}]", sprint_courant)
            )

    return violations


# ---------------------------------------------------------------------------
# Vue --etat / --json
# ---------------------------------------------------------------------------


def _titre_fiche(chemin: Path) -> str:
    if not chemin.is_file():
        return "(fiche introuvable)"
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("# "):
            return ligne[2:].strip()
    return "(sans titre)"


def construire_etat(donnees: dict[str, Any], racine: Path) -> dict[str, Any]:
    sprints_actifs = []
    fiches_planifiees: set[str] = set()

    sprints = donnees.get("sprint", [])
    for sprint in sprints if isinstance(sprints, list) else []:
        if not isinstance(sprint, dict):
            continue
        elements_sortie = []
        for element in _elements(sprint):
            if isinstance(element.get("fiche"), str):
                fiches_planifiees.add(element["fiche"])
                titre = _titre_fiche(racine / "docs" / "backlog" / f"{element['fiche']}.md")
            else:
                titre = str(element.get("chantier", "?"))
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
    if dossier_backlog.is_dir():
        for fichier in sorted(dossier_backlog.glob("*.md")):
            if fichier.stem in fiches_planifiees:
                continue
            type_fiche = ligne_type_fiche(fichier.read_text(encoding="utf-8"))
            non_planifie.append({"fiche": fichier.stem, "type": type_fiche})

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vérifie docs/backlog/sprints.toml")
    parser.add_argument("--racine", type=Path, default=None, help="Racine du dépôt (surcharge)")
    parser.add_argument("--base", default=None, help="Référence git à comparer (ex. origin/main)")
    parser.add_argument("--etat", action="store_true", help="Affiche l'état lisible")
    parser.add_argument("--json", action="store_true", help="Affiche l'état en JSON")
    args = parser.parse_args(argv)

    racine = args.racine or Path(__file__).resolve().parent.parent
    chemin_toml = racine / CHEMIN_RELATIF_TOML
    try:
        donnees = charger_toml(chemin_toml)
    except FileNotFoundError:
        print(f"[fichier] {chemin_toml} introuvable")
        return 1
    except tomllib.TOMLDecodeError as exc:
        print(f"[fichier] {chemin_toml} n'est pas un TOML valide : {exc}")
        return 1

    violations = violations_statiques(donnees, racine)

    informations: list[str] = []
    if args.base:
        base_donnees, violations_base, message_creation = charger_toml_depuis_git(
            racine, args.base
        )
        violations.extend(violations_base)
        if message_creation:
            informations.append(message_creation)
        if base_donnees is not None:
            violations.extend(violations_contre_base(base_donnees, donnees))

    _imprimer_resultat(args, donnees, racine, informations, violations)
    return 1 if violations else 0


def _imprimer_resultat(
    args: argparse.Namespace,
    donnees: dict[str, Any],
    racine: Path,
    informations: list[str],
    violations: list[str],
) -> None:
    if args.json:
        etat = construire_etat(donnees, racine)
        sortie = {"etat": etat, "informations": informations, "violations": violations}
        print(json.dumps(sortie, ensure_ascii=False, indent=2))
        return

    for information in informations:
        print(information)

    if args.etat:
        imprimer_etat(construire_etat(donnees, racine))
        if violations:
            print()
            print("Violations :")
            for v in violations:
                print(f"  - {v}")
        return

    if not violations:
        print("backlog conforme")
    for v in violations:
        print(v)


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests de scripts/verifier_backlog.py (outillage de dépôt, pas le cœur)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

RACINE_DEPOT = Path(__file__).resolve().parent.parent

# scripts/ n'est pas un package installé : on charge le module par chemin.
_spec = importlib.util.spec_from_file_location(
    "verifier_backlog", RACINE_DEPOT / "scripts" / "verifier_backlog.py"
)
verifier_backlog = importlib.util.module_from_spec(_spec)
sys.modules["verifier_backlog"] = verifier_backlog
_spec.loader.exec_module(verifier_backlog)

violations_statiques = verifier_backlog.violations_statiques
violations_contre_base = verifier_backlog.violations_contre_base
charger_toml = verifier_backlog.charger_toml
main = verifier_backlog.main


# ---------------------------------------------------------------------------
# Le vrai fichier du dépôt doit être conforme.
# ---------------------------------------------------------------------------


def test_vrai_sprints_toml_conforme():
    chemin = RACINE_DEPOT / "docs" / "backlog" / "sprints.toml"
    donnees = charger_toml(chemin)
    violations = violations_statiques(donnees, RACINE_DEPOT)
    assert violations == []


# ---------------------------------------------------------------------------
# Fixtures synthétiques : un dossier docs/backlog/ minimal sous tmp_path.
# ---------------------------------------------------------------------------


def _preparer_depot(tmp_path: Path, fiches: dict[str, str] | None = None) -> Path:
    """Crée <tmp_path>/docs/backlog/ avec des fiches synthétiques minimales."""
    dossier = tmp_path / "docs" / "backlog"
    dossier.mkdir(parents=True)
    fiches = fiches or {}
    for nom, type_fiche in fiches.items():
        (dossier / f"{nom}.md").write_text(
            f"# Fiche synthétique {nom}\n\nType : {type_fiche}\n", encoding="utf-8"
        )
    return tmp_path


def _ecrire_toml(racine: Path, contenu: str) -> dict:
    chemin = racine / "docs" / "backlog" / "sprints.toml"
    chemin.write_text(contenu, encoding="utf-8")
    return charger_toml(chemin)


def _viole(violations: list[str], sous_chaine: str) -> bool:
    return any(sous_chaine in v for v in violations)


# --- Règle A : clés inconnues, types, longueurs ----------------------------


def test_regle_a_cle_inconnue_sprint(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"
        clef_inconnue = "boum"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "clé(s) inconnue(s)")


def test_regle_a_titre_trop_long(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    titre_long = "x" * 81
    donnees = _ecrire_toml(
        racine,
        f"""
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "{titre_long}"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "'titre' dépasse 80 caractères")


def test_regle_a_statut_sprint_invalide(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "pas_un_statut"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "'statut' invalide")


def test_regle_a_raison_trop_longue(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    raison_longue = "x" * 121
    donnees = _ecrire_toml(
        racine,
        f"""
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "abandonne"
        raison = "{raison_longue}"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "'raison' dépasse 120 caractères")


# --- Règle B : numéros uniques et strictement croissants -------------------


def test_regle_b_numeros_non_croissants(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 2
        statut = "fige"
        titre = "Deux"

        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"

        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Un"

        [[sprint.element]]
        fiche = "fiche-b"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "non strictement croissants")


def test_regle_b_numero_duplique(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Un"

        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"

        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Un bis"

        [[sprint.element]]
        fiche = "fiche-b"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "numéro de sprint dupliqué")


# --- Règle C : monotonie des statuts de sprint ------------------------------


def test_regle_c_statuts_non_monotones(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "esquisse"
        titre = "Un"

        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"

        [[sprint]]
        numero = 2
        statut = "en_cours"
        titre = "Deux"

        [[sprint.element]]
        fiche = "fiche-b"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "non monotones")


def test_regle_c_trop_de_sprints_figes(tmp_path):
    fiches = {f"fiche-{i}": "feature" for i in range(3)}
    racine = _preparer_depot(tmp_path, fiches)
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Un"

        [[sprint.element]]
        fiche = "fiche-0"
        statut = "prevu"

        [[sprint]]
        numero = 2
        statut = "fige"
        titre = "Deux"

        [[sprint.element]]
        fiche = "fiche-1"
        statut = "prevu"

        [[sprint]]
        numero = 3
        statut = "fige"
        titre = "Trois"

        [[sprint.element]]
        fiche = "fiche-2"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "plus de 2 sprints figés")


# --- Règle D : fiche/chantier, existence, unicité ---------------------------


def test_regle_d_fiche_et_chantier_ensemble(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        chantier = "ouverture"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "a à la fois 'fiche' et 'chantier'")


def test_regle_d_ni_fiche_ni_chantier(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "n'a ni 'fiche' ni 'chantier'")


def test_regle_d_fiche_introuvable(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "fiche-absente"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "fichier introuvable")


def test_regle_d_fiche_sans_type(tmp_path):
    racine = _preparer_depot(tmp_path)
    dossier = racine / "docs" / "backlog"
    (dossier / "fiche-sans-type.md").write_text("# Une fiche\n\nPas de ligne Type.\n", encoding="utf-8")
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "fiche-sans-type"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "n'a pas de ligne 'Type : feature' ou 'Type : bug'")


def test_regle_d_chantier_inconnu(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        chantier = "chantier-qui-n-existe-pas"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "chantier inconnu")


def test_regle_d_element_duplique(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Un"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "en_cours"

        [[sprint]]
        numero = 2
        statut = "fige"
        titre = "Deux"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "référencée plusieurs fois")


# --- Règle E : cohérence statut élément / statut sprint ---------------------


def test_regle_e_element_en_cours_dans_sprint_fige(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "en_cours"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "élément en_cours mais le sprint parent n'est pas en_cours")


def test_regle_e_livre_sans_pr(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "livre"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "statut livre exige la clé 'pr'")


def test_regle_e_abandonne_sans_raison(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "abandonne"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "statut abandonne exige la clé 'raison'")


def test_regle_e_sprint_clos_avec_element_prevu(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "clos"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "sprint clos mais contient un élément de statut 'prevu'")


def test_regle_e_sprint_fige_avec_element_livre(tmp_path):
    racine = _preparer_depot(tmp_path, {"une-fiche": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Titre"

        [[sprint.element]]
        fiche = "une-fiche"
        statut = "livre"
        pr = 42
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "sprint fige mais contient un élément de statut 'livre'")


# ---------------------------------------------------------------------------
# Règles F et G : fonctions pures sur des dicts, sans git.
# ---------------------------------------------------------------------------


def test_regle_f_sprint_fige_remanie_sans_derogation():
    base = {
        "sprint": [
            {
                "numero": 1,
                "statut": "fige",
                "titre": "Titre",
                "element": [{"fiche": "a", "statut": "prevu"}, {"fiche": "b", "statut": "prevu"}],
            }
        ]
    }
    courant = {
        "sprint": [
            {
                "numero": 1,
                "statut": "fige",
                "titre": "Titre",
                "element": [{"fiche": "a", "statut": "prevu"}, {"fiche": "c", "statut": "prevu"}],
            }
        ]
    }
    violations = violations_contre_base(base, courant)
    assert _viole(violations, "sans dérogation nouvelle")


def test_regle_f_sprint_fige_remanie_avec_derogation_ok():
    base = {
        "sprint": [
            {
                "numero": 1,
                "statut": "fige",
                "titre": "Titre",
                "element": [{"fiche": "a", "statut": "prevu"}, {"fiche": "b", "statut": "prevu"}],
            }
        ]
    }
    courant = {
        "sprint": [
            {
                "numero": 1,
                "statut": "fige",
                "titre": "Titre",
                "derogations": ["26/09/2026 : raison courte"],
                "element": [{"fiche": "a", "statut": "prevu"}, {"fiche": "c", "statut": "prevu"}],
            }
        ]
    }
    violations = violations_contre_base(base, courant)
    assert violations == []


def test_regle_g_sprint_supprime():
    base = {"sprint": [{"numero": 1, "statut": "fige", "titre": "Titre", "element": []}]}
    courant = {"sprint": []}
    violations = violations_contre_base(base, courant)
    assert _viole(violations, "a disparu du fichier")


def test_regle_g_statut_sprint_retour_en_arriere():
    base = {"sprint": [{"numero": 1, "statut": "en_cours", "titre": "Titre", "element": []}]}
    courant = {"sprint": [{"numero": 1, "statut": "fige", "titre": "Titre", "element": []}]}
    violations = violations_contre_base(base, courant)
    assert _viole(violations, "statut revenu en arrière")


def test_regle_g_element_livre_qui_change_de_statut():
    base = {
        "sprint": [
            {
                "numero": 1,
                "statut": "en_cours",
                "titre": "Titre",
                "element": [{"fiche": "a", "statut": "livre", "pr": 1}],
            }
        ]
    }
    courant = {
        "sprint": [
            {
                "numero": 1,
                "statut": "clos",
                "titre": "Titre",
                "element": [{"fiche": "a", "statut": "abandonne", "raison": "changement d'avis"}],
            }
        ]
    }
    violations = violations_contre_base(base, courant)
    assert _viole(violations, "ne peut plus changer")


# ---------------------------------------------------------------------------
# Outils pour les tests qui suivent (relecture du commit abea2619).
# ---------------------------------------------------------------------------


def _sprint(numero: int, statut: str, elements: list[dict], **autres) -> dict:
    return {"numero": numero, "statut": statut, "titre": "Titre", "element": elements, **autres}


def _fichier(sprints: list[dict]) -> dict:
    return {"sprint": sprints}


DEROGATION_OK = "26/09/2026 : remplacement décidé en revue"


# --- M1 à M13 : une mutation du vérificateur, un test qui la voit ---------


def test_m1_plus_d_un_sprint_en_cours(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Un"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"

        [[sprint]]
        numero = 2
        statut = "en_cours"
        titre = "Deux"
        [[sprint.element]]
        fiche = "fiche-b"
        statut = "prevu"
        """,
    )
    assert _viole(violations_statiques(donnees, racine), "plus d'un sprint en_cours")


def test_m2_plus_de_deux_sprints_esquisses(tmp_path):
    racine = _preparer_depot(tmp_path)
    blocs = "".join(
        f'\n[[sprint]]\nnumero = {n}\nstatut = "esquisse"\ntitre = "S{n}"\n' for n in (1, 2, 3)
    )
    donnees = _ecrire_toml(racine, blocs)
    assert _viole(violations_statiques(donnees, racine), "plus de 2 sprints esquissés")


def test_m3_titre_avec_saut_de_ligne(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine, '[[sprint]]\nnumero = 1\nstatut = "esquisse"\ntitre = "Ligne\\nautre"\n'
    )
    assert _viole(violations_statiques(donnees, racine), "'titre' contient un caractère non imprimable")


def test_m4_raison_hors_abandonne(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Titre"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"
        raison = "une raison inutile ici"
        """,
    )
    assert _viole(violations_statiques(donnees, racine), "'raison' présente mais statut != abandonne")


def test_m5_pr_hors_livre(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "en_cours"
        pr = 12
        """,
    )
    assert _viole(violations_statiques(donnees, racine), "'pr' présent mais statut != livre")


def test_m6_pr_non_entier(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "livre"
        pr = "12"
        """,
    )
    assert _viole(violations_statiques(donnees, racine), "'pr' doit être un entier")


def test_m7_derogations_strictes(tmp_path):
    racine = _preparer_depot(tmp_path)
    entrees = [
        "31/02/2026 : date absente du calendrier",
        "32/13/2026 : jour et mois hors bornes",
        "26/09/2026 : court",
        "26-09-2026 : séparateurs de date incorrects",
        "29/02/2024 : année bissextile, date valide",
        "29/02/2024 : année bissextile, date valide",
    ]
    liste = ", ".join(f'"{e}"' for e in entrees)
    donnees = _ecrire_toml(
        racine,
        f'[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "T"\nderogations = [{liste}]\n',
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "date inexistante au calendrier : '31/02/2026")
    assert _viole(violations, "date inexistante au calendrier : '32/13/2026")
    assert _viole(violations, "raison de moins de 10 caractères")
    assert _viole(violations, "mal formée")
    assert _viole(violations, "dérogation en double")
    # la date bissextile valide n'est pas refusée pour sa date
    assert not _viole(violations, "date inexistante au calendrier : '29/02/2024")


def test_m7_dates_de_derogation_valides_et_invalides():
    valider = verifier_backlog.valider_entree_derogation
    assert valider("30/04/2026 : trente avril existe bien") is None
    assert valider("31/04/2026 : trente et un avril n'existe pas") is not None
    assert valider("29/02/2025 : pas bissextile en 2025") is not None
    assert valider("29/02/2024 : bissextile en 2024 donc OK") is None
    assert valider("01/01/2026 :           ") is not None


def test_m8_deux_derogations_nouvelles_pour_un_changement():
    base = _fichier([_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}])])
    courant = _fichier(
        [
            _sprint(
                1,
                "fige",
                [{"fiche": "b", "statut": "prevu"}],
                derogations=[DEROGATION_OK, "27/09/2026 : seconde dérogation du même diff"],
            )
        ]
    )
    assert _viole(violations_contre_base(base, courant), "exactement une est attendue")


def test_m8_derogation_nouvelle_sans_changement():
    base = _fichier([_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}])])
    courant = _fichier(
        [_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}], derogations=[DEROGATION_OK])]
    )
    assert _viole(violations_contre_base(base, courant), "dérogation nouvelle sans changement")


def test_m8_derogation_retiree_puis_reintroduite_n_est_pas_nouvelle():
    """Scénario c10 : la base a une dérogation, le diff la retire ; puis un
    diff la réintroduit pour couvrir un remaniement : refusé (append-only)."""
    base = _fichier(
        [_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}], derogations=[DEROGATION_OK])]
    )
    sans = _fichier([_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}])])
    assert _viole(violations_contre_base(base, sans), "dérogations modifiées")


def test_m9_regle_f_sur_sprint_en_cours():
    base = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": "prevu"}])])
    courant = _fichier([_sprint(1, "en_cours", [{"fiche": "b", "statut": "prevu"}])])
    assert _viole(violations_contre_base(base, courant), "sans dérogation nouvelle")


def test_m9_regle_f_titre_change_sans_derogation():
    base = _fichier([_sprint(1, "fige", [])])
    sprint = _sprint(1, "fige", [])
    sprint["titre"] = "Autre titre"
    assert _viole(violations_contre_base(base, _fichier([sprint])), "sans dérogation nouvelle")


def test_m10_fichier_de_chantier_absent(tmp_path):
    racine = _preparer_depot(tmp_path)  # pas de docs/ouverture_plan.md
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"
        [[sprint.element]]
        chantier = "ouverture"
        statut = "en_cours"
        """,
    )
    assert _viole(violations_statiques(donnees, racine), "fichier de chantier introuvable")


def test_m11_cle_inconnue_sur_un_element(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "fige"
        titre = "Titre"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "prevu"
        priorite = 1
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "élément fiche='fiche-a'] clé(s) inconnue(s) : ['priorite']")


def test_m13_element_livre_qui_change_de_champ():
    """La mutation du dossier mut/ neutralisait le gel des éléments terminés."""
    base = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": "livre", "pr": 80}])])
    courant = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": "livre", "pr": 1}])])
    assert _viole(violations_contre_base(base, courant), "ne peut plus changer")


def test_m14_nouveau_sprint_doit_etre_esquisse():
    """Un numéro de sprint absent de la base (mais le fichier existait déjà) ne
    peut apparaître qu'en 'esquisse' ; toute autre valeur est une violation."""
    base = _fichier([_sprint(1, "fige", [])])

    courant_en_cours = _fichier([_sprint(1, "fige", []), _sprint(2, "en_cours", [])])
    assert _viole(
        violations_contre_base(base, courant_en_cours),
        "sprint nouveau (absent de la base) doit être 'esquisse'",
    )

    # Cas positif : le même sprint nouveau, mais en esquisse, ne déclenche pas
    # cette règle (les autres règles F/G ne s'appliquent pas à un numéro
    # absent de la base, seule cette nouvelle règle les concerne).
    courant_esquisse = _fichier([_sprint(1, "fige", []), _sprint(2, "esquisse", [])])
    assert not _viole(
        violations_contre_base(base, courant_esquisse),
        "sprint nouveau (absent de la base) doit être 'esquisse'",
    )


def test_m14_mutation_neutraliser_la_regle_du_nouveau_sprint(monkeypatch):
    """Test de mutation (au sens de ce fichier, cf. M1-M13) : si on neutralise
    la vérification du sprint nouveau (en la faisant toujours passer), la
    violation du scénario ci-dessus n'est plus détectée — la présence de
    cette règle dans violations_contre_base est bien ce qui la détecte."""
    base = _fichier([_sprint(1, "fige", [])])
    courant = _fichier([_sprint(1, "fige", []), _sprint(2, "en_cours", [])])

    # Sans mutation : la règle réelle du dépôt détecte la violation.
    assert _viole(
        violations_contre_base(base, courant),
        "sprint nouveau (absent de la base) doit être 'esquisse'",
    )

    # Mutation : on neutralise la fonction de la règle (comme un mutant qui
    # supprimerait le corps de la vérification) et on vérifie que la
    # violation disparaît bien — preuve que le test ci-dessus tuerait ce
    # mutant s'il apparaissait dans le code.
    monkeypatch.setattr(
        verifier_backlog, "_regle_g_nouveau_sprint_esquisse", lambda ctx, sprint_courant: []
    )
    assert not _viole(
        violations_contre_base(base, courant),
        "sprint nouveau (absent de la base) doit être 'esquisse'",
    )


# --- B1 et M12 : la comparaison à la base n'est jamais sautée en silence ----


GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@exemple.invalid",
       "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]

TOML_BASE = """
[[sprint]]
numero = 1
statut = "fige"
titre = "Titre"

[[sprint.element]]
fiche = "fiche-a"
statut = "prevu"

[[sprint.element]]
fiche = "fiche-b"
statut = "prevu"
"""


def _git(racine: Path, *arguments: str) -> None:
    subprocess.run([*GIT, *arguments], cwd=racine, check=True, capture_output=True)


def _depot_git(tmp_path: Path, contenu_base: str | None = TOML_BASE) -> Path:
    """Dépôt git réel : premier commit = la base (avec ou sans sprints.toml)."""
    racine = _preparer_depot(
        tmp_path, {"fiche-a": "feature", "fiche-b": "feature", "fiche-c": "bug"}
    )
    _git(racine, "init", "-q")
    if contenu_base is not None:
        (racine / "docs" / "backlog" / "sprints.toml").write_text(contenu_base, encoding="utf-8")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "base")
    return racine


def _commit_toml(racine: Path, contenu: str) -> None:
    (racine / "docs" / "backlog" / "sprints.toml").write_text(contenu, encoding="utf-8")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "courant")


def test_main_git_conforme(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_BASE.replace('statut = "fige"', 'statut = "en_cours"'))
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 0
    assert "backlog conforme" in capsys.readouterr().out


def test_main_git_sprint_fige_remanie_sans_derogation(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_BASE.replace('fiche = "fiche-b"', 'fiche = "fiche-c"'))
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 1
    assert "sans dérogation nouvelle" in capsys.readouterr().out


def test_main_git_sprint_fige_remanie_avec_derogation(tmp_path):
    racine = _depot_git(tmp_path)
    courant = TOML_BASE.replace('fiche = "fiche-b"', 'fiche = "fiche-c"').replace(
        'titre = "Titre"', f'titre = "Titre"\nderogations = ["{DEROGATION_OK}"]'
    )
    _commit_toml(racine, courant)
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 0


def test_b1_ref_base_inexistante(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    assert main(["--racine", str(racine), "--base", "ref-qui-n-existe-pas"]) == 1
    assert "référence git introuvable" in capsys.readouterr().out


def test_b1_racine_hors_depot_git(tmp_path, capsys):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    (racine / "docs" / "backlog" / "sprints.toml").write_text(TOML_BASE, encoding="utf-8")
    assert main(["--racine", str(racine), "--base", "HEAD"]) == 1
    assert "dépôt git" in capsys.readouterr().out


def test_b1_racine_sous_dossier_d_un_depot_git(tmp_path, capsys):
    """Un sous-dossier d'un dépôt ferait lire le mauvais chemin dans la base :
    refusé plutôt que pris pour une création."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "LISEZMOI").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    racine = _preparer_depot(tmp_path / "sous", {"fiche-a": "feature", "fiche-b": "feature"})
    (racine / "docs" / "backlog" / "sprints.toml").write_text(TOML_BASE, encoding="utf-8")
    assert main(["--racine", str(racine), "--base", "HEAD"]) == 1
    assert "n'est pas la racine du dépôt git" in capsys.readouterr().out


def test_b1_toml_de_la_base_invalide(tmp_path, capsys):
    racine = _depot_git(tmp_path, contenu_base="[[sprint]\nnumero = ")
    _commit_toml(racine, TOML_BASE)
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 1
    assert "n'est pas un TOML valide" in capsys.readouterr().out


def test_b1_m12_creation_du_fichier_est_dite(tmp_path, capsys):
    racine = _depot_git(tmp_path, contenu_base=None)
    _commit_toml(racine, TOML_BASE)
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 0
    sortie = capsys.readouterr().out
    assert "création" in sortie and "F et G sans objet" in sortie


def test_b1_fichier_sans_aucun_sprint(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(racine, "# vide\n")
    assert _viole(violations_statiques(donnees, racine), "au moins un sprint est exigé")


# --- B2 : un élément terminé reste dans son sprint, champs identiques -------


def test_b2_element_livre_deplace_dans_un_autre_sprint():
    base = _fichier(
        [
            _sprint(1, "en_cours", [{"fiche": "a", "statut": "livre", "pr": 5}]),
            _sprint(2, "fige", []),
        ]
    )
    courant = _fichier(
        [
            _sprint(1, "en_cours", []),
            _sprint(2, "fige", [{"fiche": "a", "statut": "livre", "pr": 5}]),
        ]
    )
    assert _viole(violations_contre_base(base, courant), "a quitté ce sprint")


def test_b2_raison_d_abandon_modifiee():
    base = _fichier(
        [_sprint(1, "en_cours", [{"fiche": "a", "statut": "abandonne", "raison": "hors sujet"}])]
    )
    courant = _fichier(
        [_sprint(1, "en_cours", [{"fiche": "a", "statut": "abandonne", "raison": "autre motif"}])]
    )
    assert _viole(violations_contre_base(base, courant), "ne peut plus changer")


# --- B3 : dérogations en ajout seulement --------------------------------------


def test_b3_derogations_reordonnees():
    d1 = "01/09/2026 : première dérogation du sprint"
    d2 = "02/09/2026 : deuxième dérogation du sprint"
    base = _fichier([_sprint(1, "fige", [], derogations=[d1, d2])])
    courant = _fichier([_sprint(1, "fige", [], derogations=[d2, d1])])
    assert _viole(violations_contre_base(base, courant), "dérogations modifiées")


def test_b3_derogation_ajoutee_en_fin_acceptee():
    d1 = "01/09/2026 : première dérogation du sprint"
    base = _fichier([_sprint(1, "fige", [{"fiche": "a", "statut": "prevu"}], derogations=[d1])])
    courant = _fichier(
        [_sprint(1, "fige", [{"fiche": "b", "statut": "prevu"}], derogations=[d1, DEROGATION_OK])]
    )
    assert violations_contre_base(base, courant) == []


# --- B4 : nom de fiche, casse exacte, ligne Type hors bloc de code ----------


def _toml_une_fiche(nom: str) -> str:
    return (
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "T"\n'
        f'[[sprint.element]]\nfiche = "{nom}"\nstatut = "prevu"\n'
    )


def test_b4_nom_de_fiche_hors_motif(tmp_path):
    racine = _preparer_depot(tmp_path)
    for nom in ("Majuscule", "double--tiret", "sous_tiret", "-debut", "fin-", "../evasion"):
        donnees = _ecrire_toml(racine, _toml_une_fiche(nom))
        assert _viole(violations_statiques(donnees, racine), "nom de fiche invalide"), nom


def test_b4_casse_du_fichier_differente(tmp_path):
    racine = _preparer_depot(tmp_path)
    (racine / "docs" / "backlog" / "Fiche-a.md").write_text("# F\n\nType : feature\n")
    donnees = _ecrire_toml(racine, _toml_une_fiche("fiche-a"))
    assert _viole(violations_statiques(donnees, racine), "fichier introuvable")


def test_b4_type_dans_un_bloc_de_code_ne_compte_pas(tmp_path):
    racine = _preparer_depot(tmp_path)
    (racine / "docs" / "backlog" / "fiche-a.md").write_text(
        "# F\n\n```\nType : feature\n```\n\nTexte.\n", encoding="utf-8"
    )
    donnees = _ecrire_toml(racine, _toml_une_fiche("fiche-a"))
    assert _viole(violations_statiques(donnees, racine), "n'a pas de ligne 'Type : feature'")


def test_b4_type_au_dela_des_dix_premieres_lignes(tmp_path):
    racine = _preparer_depot(tmp_path)
    (racine / "docs" / "backlog" / "fiche-a.md").write_text(
        "# F\n" + "\n" * 10 + "Type : feature\n", encoding="utf-8"
    )
    donnees = _ecrire_toml(racine, _toml_une_fiche("fiche-a"))
    assert _viole(violations_statiques(donnees, racine), "n'a pas de ligne 'Type : feature'")


# --- C3 : seule la clé 'sprint' à la racine -----------------------------------


def test_c3_cle_orpheline_a_la_racine(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine, 'sprints_typo = 1\n[[sprint]]\nnumero = 1\nstatut = "esquisse"\ntitre = "T"\n'
    )
    assert _viole(violations_statiques(donnees, racine), "inconnue(s) à la racine")


def test_c3_table_orpheline_a_la_racine(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine, '[[sprint]]\nnumero = 1\nstatut = "esquisse"\ntitre = "T"\n\n[element]\nx = 1\n'
    )
    assert _viole(violations_statiques(donnees, racine), "inconnue(s) à la racine")


# --- C4 : booléens refusés comme entiers, textes non vides -------------------


def test_c4_booleens_refuses_comme_entiers(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = true
        statut = "en_cours"
        titre = "Titre"
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "livre"
        pr = true
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "'numero' doit être un entier")
    assert _viole(violations, "'pr' doit être un entier")


def test_c4_titre_et_raison_vides(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "   "
        [[sprint.element]]
        fiche = "fiche-a"
        statut = "abandonne"
        raison = "  "
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "'titre' vide")
    assert _viole(violations, "'raison' vide")


# --- C5 : transitions d'une étape, sprint clos gelé ---------------------------


def test_c5_saut_d_etape_esquisse_vers_en_cours():
    base = _fichier([_sprint(1, "esquisse", [])])
    courant = _fichier([_sprint(1, "en_cours", [])])
    assert _viole(violations_contre_base(base, courant), "plus d'une étape")


def test_c5_clos_directement_depuis_fige():
    base = _fichier([_sprint(1, "fige", [])])
    courant = _fichier([_sprint(1, "clos", [])])
    violations = violations_contre_base(base, courant)
    assert _viole(violations, "clos alors qu'il n'était pas en_cours")


def test_c5_une_etape_a_la_fois_acceptee():
    base = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": "en_cours"}]),
                     _sprint(2, "fige", []), _sprint(3, "esquisse", [])])
    courant = _fichier([_sprint(1, "clos", [{"fiche": "a", "statut": "livre", "pr": 3}]),
                        _sprint(2, "en_cours", []), _sprint(3, "fige", [])])
    assert violations_contre_base(base, courant) == []


def test_c5_sprint_clos_modifie():
    elements = [{"fiche": "a", "statut": "livre", "pr": 3}]
    base = _fichier([_sprint(1, "clos", elements)])
    sprint = _sprint(1, "clos", elements)
    sprint["titre"] = "Titre retouché"
    assert _viole(violations_contre_base(base, _fichier([sprint])), "était clos dans la base")
    avec_derog = _fichier([_sprint(1, "clos", elements, derogations=[DEROGATION_OK])])
    assert _viole(violations_contre_base(base, avec_derog), "était clos dans la base")


# --- M-e : fiches et chantiers dans deux espaces de noms ---------------------


def test_me_fiche_et_chantier_de_meme_nom_ne_se_confondent_pas(tmp_path):
    racine = _preparer_depot(tmp_path, {"ouverture": "feature"})
    (racine / "docs" / "ouverture_plan.md").write_text("# Plan\n", encoding="utf-8")
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Titre"
        [[sprint.element]]
        chantier = "ouverture"
        statut = "en_cours"
        [[sprint.element]]
        fiche = "ouverture"
        statut = "prevu"
        """,
    )
    assert violations_statiques(donnees, racine) == []


# --- M-a : chaque sous-règle E, isolément -------------------------------------


def test_regles_e_une_par_une():
    ve = verifier_backlog
    assert ve.regle_e_en_cours_exige_sprint_en_cours(
        _sprint(1, "fige", [{"fiche": "a", "statut": "en_cours"}])
    )
    assert not ve.regle_e_en_cours_exige_sprint_en_cours(
        _sprint(1, "en_cours", [{"fiche": "a", "statut": "en_cours"}])
    )
    assert ve.regle_e_livre_exige_pr_et_sprint_actif(
        _sprint(1, "en_cours", [{"fiche": "a", "statut": "livre"}])
    )
    assert ve.regle_e_livre_exige_pr_et_sprint_actif(
        _sprint(1, "fige", [{"fiche": "a", "statut": "livre", "pr": 1}])
    )
    assert not ve.regle_e_livre_exige_pr_et_sprint_actif(
        _sprint(1, "clos", [{"fiche": "a", "statut": "livre", "pr": 1}])
    )
    assert ve.regle_e_pr_reservee_au_livre(
        _sprint(1, "en_cours", [{"fiche": "a", "statut": "prevu", "pr": 1}])
    )
    assert ve.regle_e_abandonne_exige_raison(
        _sprint(1, "fige", [{"fiche": "a", "statut": "abandonne"}])
    )
    assert ve.regle_e_raison_reservee_a_abandonne(
        _sprint(1, "fige", [{"fiche": "a", "statut": "prevu", "raison": "x"}])
    )
    assert ve.regle_e_sprint_clos_termine(_sprint(1, "clos", [{"fiche": "a", "statut": "prevu"}]))
    assert ve.regle_e_sprint_non_commence(
        _sprint(1, "esquisse", [{"fiche": "a", "statut": "en_cours"}])
    )
    assert not ve.regle_e_sprint_non_commence(
        _sprint(1, "esquisse", [{"fiche": "a", "statut": "abandonne", "raison": "x"}])
    )


# ---------------------------------------------------------------------------
# Deuxième contre-relecture : m1, m2, m3, m5 (N8, N15, N26) et --commits.
# ---------------------------------------------------------------------------


# --- m1 : dérogations interdites sur esquisse, jamais sans changement -------


def test_m1_derogations_interdites_sur_sprint_esquisse(tmp_path):
    """Règle statique : vraie sans aucune base git."""
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        f'[[sprint]]\nnumero = 1\nstatut = "esquisse"\ntitre = "T"\n'
        f'derogations = ["{DEROGATION_OK}"]\n',
    )
    assert _viole(violations_statiques(donnees, racine), "'derogations' interdite sur un sprint esquisse")
    # la même clé sur un sprint figé n'est pas interdite par cette règle
    donnees = _ecrire_toml(
        racine,
        f'[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "T"\nderogations = ["{DEROGATION_OK}"]\n',
    )
    assert not _viole(violations_statiques(donnees, racine), "interdite sur un sprint esquisse")


def test_m1_derogation_sans_changement_refusee_quel_que_soit_le_statut():
    elements = [{"fiche": "a", "statut": "prevu"}]
    # esquisse -> fige, une dérogation ajoutée sans rien changer
    base = _fichier([_sprint(1, "esquisse", elements)])
    courant = _fichier([_sprint(1, "fige", elements, derogations=[DEROGATION_OK])])
    assert _viole(violations_contre_base(base, courant), "dérogation nouvelle sans changement")
    # en_cours -> clos, idem
    livres = [{"fiche": "a", "statut": "livre", "pr": 1}]
    base = _fichier([_sprint(1, "en_cours", livres)])
    courant = _fichier([_sprint(1, "clos", livres, derogations=[DEROGATION_OK])])
    assert _viole(violations_contre_base(base, courant), "dérogation nouvelle sans changement")


def test_m1_derogation_qui_couvre_un_changement_admise_depuis_esquisse():
    base = _fichier([_sprint(1, "esquisse", [{"fiche": "a", "statut": "prevu"}])])
    courant = _fichier(
        [_sprint(1, "fige", [{"fiche": "b", "statut": "prevu"}], derogations=[DEROGATION_OK])]
    )
    assert violations_contre_base(base, courant) == []


# --- m2 : un élément ne recule jamais de statut -----------------------------


def test_m2_transitions_d_element_interdites():
    interdites = [
        ("livre", "prevu"), ("en_cours", "prevu"), ("abandonne", "prevu"),
        ("abandonne", "en_cours"), ("livre", "abandonne"), ("livre", "en_cours"),
    ]
    for avant, apres in interdites:
        base = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": avant}])])
        courant = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": apres}])])
        violations = verifier_backlog.regle_g_transition_elements(base, courant)
        assert _viole(violations, f"transition d'élément interdite : {avant!r} -> {apres!r}"), (
            avant, apres
        )


def test_m2_transitions_d_element_admises():
    admises = [
        ("prevu", "prevu"), ("prevu", "en_cours"), ("en_cours", "livre"),
        ("prevu", "abandonne"), ("en_cours", "abandonne"), ("prevu", "livre"),
    ]
    for avant, apres in admises:
        base = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": avant}])])
        courant = _fichier([_sprint(1, "en_cours", [{"fiche": "a", "statut": apres}])])
        assert verifier_backlog.regle_g_transition_elements(base, courant) == [], (avant, apres)


def test_m2_recul_par_deplacement_dans_un_autre_sprint():
    """Déplacer un élément en_cours dans un autre sprint en prevu est un recul."""
    base = _fichier(
        [_sprint(1, "en_cours", [{"fiche": "a", "statut": "en_cours"}]), _sprint(2, "fige", [])]
    )
    courant = _fichier(
        [_sprint(1, "en_cours", []), _sprint(2, "fige", [{"fiche": "a", "statut": "prevu"}])]
    )
    assert _viole(violations_contre_base(base, courant), "'en_cours' -> 'prevu'")


# --- m3 : dates bornées, caractères imprimables -----------------------------


def test_m3_bornes_des_dates_de_derogation():
    valider = verifier_backlog.valider_entree_derogation
    assert valider("01/01/2024 : première date admise") is None
    assert valider("31/12/2100 : dernière date admise") is None
    assert "hors bornes" in valider("31/12/2023 : la veille de la borne")
    assert "hors bornes" in valider("01/01/2101 : le lendemain de la borne")
    assert "hors bornes" in valider("01/01/0001 : an un du calendrier")


def test_m3_date_en_chiffres_non_ascii_refusee():
    # « ٢٦ » : chiffres arabo-indiens, que int() accepterait
    assert "mal formée" in verifier_backlog.valider_entree_derogation(
        "٢٦/09/2026 : chiffres non ASCII"
    )


def test_m3_raison_de_derogation_non_imprimable_refusee_avant_strip():
    valider = verifier_backlog.valider_entree_derogation
    for piege in ("\t", "\r", "\x0b", "\x00", " ", "\x1b"):
        for entree in (
            f"26/09/2026 : raison assez longue{piege}",  # en bordure : strip() l'effacerait
            f"26/09/2026 : raison{piege}assez longue",
        ):
            assert "non imprimable" in (valider(entree) or ""), repr(entree)
    assert valider("26/09/2026 : raison avec des espaces normaux") is None


def test_m3_titre_et_raison_non_imprimables(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    for piege in ("\\t", "\\r", "\\u000b", "\\u2028"):
        donnees = _ecrire_toml(
            racine,
            f'[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre{piege}"\n'
            f'[[sprint.element]]\nfiche = "fiche-a"\nstatut = "abandonne"\n'
            f'raison = "{piege}une raison"\n',
        )
        violations = violations_statiques(donnees, racine)
        assert _viole(violations, "'titre' contient un caractère non imprimable"), piege
        assert _viole(violations, "'raison' contient un caractère non imprimable"), piege


# --- m5 : N15 (raison multi-lignes), N26 (unicité des chantiers), N8 --------


def test_n15_raison_d_element_avec_saut_de_ligne_refusee(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "T"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "abandonne"\n'
        'raison = """première ligne\nseconde ligne"""\n',
    )
    assert _viole(violations_statiques(donnees, racine), "'raison' contient un caractère non imprimable")


def test_n15_raison_de_derogation_avec_saut_de_ligne_refusee(tmp_path):
    entree = "26/09/2026 : première ligne\nseconde ligne"
    assert "non imprimable" in verifier_backlog.valider_entree_derogation(entree)
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "T"\n'
        'derogations = ["26/09/2026 : première ligne\\nseconde ligne"]\n',
    )
    assert _viole(violations_statiques(donnees, racine), "non imprimable")


def test_n26_chantier_reference_dans_deux_sprints(tmp_path):
    racine = _preparer_depot(tmp_path)
    (racine / "docs" / "ouverture_plan.md").write_text("# Plan\n", encoding="utf-8")
    donnees = _ecrire_toml(
        racine,
        """
        [[sprint]]
        numero = 1
        statut = "en_cours"
        titre = "Un"
        [[sprint.element]]
        chantier = "ouverture"
        statut = "en_cours"

        [[sprint]]
        numero = 2
        statut = "fige"
        titre = "Deux"
        [[sprint.element]]
        chantier = "ouverture"
        statut = "prevu"
        """,
    )
    violations = violations_statiques(donnees, racine)
    assert _viole(violations, "chantier référencé plusieurs fois")
    assert not _viole(violations, "fiche référencée plusieurs fois")


def test_n8_clos_depuis_fige_une_seule_violation():
    """« clos seulement depuis en_cours » découle de « une étape au plus » :
    une seule violation, qui dit les deux."""
    base = _fichier([_sprint(1, "fige", [])])
    courant = _fichier([_sprint(1, "clos", [])])
    violations = verifier_backlog._regle_g_transition_sprint("[sprint 1]", "fige", "clos")
    assert len(violations) == 1
    assert "plus d'une étape" in violations[0] and "clos alors qu'il n'était pas en_cours" in violations[0]
    assert violations_contre_base(base, courant) == violations


# --- --commits : un diff = un commit ------------------------------------------


def _sha(racine: Path, rev: str = "HEAD") -> str:
    return subprocess.run(
        [*GIT, "rev-parse", rev], cwd=racine, check=True, capture_output=True, text=True
    ).stdout.strip()


TOML_EN_COURS = TOML_BASE.replace('statut = "fige"', 'statut = "en_cours"')
TOML_CLOS = (
    TOML_BASE.replace('statut = "fige"', 'statut = "clos"')
    .replace('fiche = "fiche-a"\nstatut = "prevu"', 'fiche = "fiche-a"\nstatut = "livre"\npr = 1')
    .replace(
        'fiche = "fiche-b"\nstatut = "prevu"',
        'fiche = "fiche-b"\nstatut = "abandonne"\nraison = "reporté au sprint suivant"',
    )
)


def test_cas17_deux_commits_legitimes_passent(tmp_path, capsys):
    """fige -> en_cours puis en_cours -> clos : une étape par commit."""
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_EN_COURS)
    _commit_toml(racine, TOML_CLOS)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 0
    assert "2 commit(s)" in capsys.readouterr().out
    # --base, en bloc, voit fige -> clos et refuse : c'est bien la différence
    assert main(["--racine", str(racine), "--base", "HEAD~2"]) == 1


def test_cas17_meme_transformation_en_un_commit_refusee(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_CLOS)
    assert main(["--racine", str(racine), "--commits", "HEAD~1"]) == 1
    sortie = capsys.readouterr().out
    assert f"[{_sha(racine)[:7]}] [sprint 1] statut avancé de plus d'une étape" in sortie


def test_commits_seul_le_commit_fautif_est_cite(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_EN_COURS)
    legitime = _sha(racine)
    _commit_toml(racine, TOML_BASE)  # recul en_cours -> fige
    fautif = _sha(racine)
    _commit_toml(racine, TOML_EN_COURS)
    assert main(["--racine", str(racine), "--commits", "HEAD~3"]) == 1
    sortie = capsys.readouterr().out
    assert f"[{fautif[:7]}] [sprint 1] statut revenu en arrière" in sortie
    assert f"[{legitime[:7]}]" not in sortie
    # --base ne voit que fige -> en_cours, légitime en bloc
    assert main(["--racine", str(racine), "--base", "HEAD~3"]) == 0


def _branche(racine: Path, nom: str, depuis: str) -> None:
    _git(racine, "checkout", "-q", "-b", nom, depuis)


def _fusion_resolue_a_la_main(racine: Path, autre: str, contenu: str) -> None:
    """Commit de fusion à deux parents dont sprints.toml vaut `contenu`."""
    _git(racine, "merge", "-q", "--no-ff", "--no-commit", "-s", "ours", autre)
    (racine / "docs" / "backlog" / "sprints.toml").write_text(contenu, encoding="utf-8")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "fusion")


TOML_REMANIE_AVEC_DEROGATION = TOML_BASE.replace('fiche = "fiche-b"', 'fiche = "fiche-c"').replace(
    'titre = "Titre"', f'titre = "Titre"\nderogations = ["{DEROGATION_OK}"]'
)


def _deux_branches(racine: Path) -> None:
    """principale : fige -> en_cours ; cote (depuis la base) : remaniement
    couvert par une dérogation. Revient sur principale."""
    _git(racine, "branch", "-q", "-M", "principale")
    _commit_toml(racine, TOML_EN_COURS)
    _branche(racine, "cote", "HEAD~1")
    _commit_toml(racine, TOML_REMANIE_AVEC_DEROGATION)
    _git(racine, "checkout", "-q", "principale")


def test_commits_fusion_identique_a_un_parent_ignoree(tmp_path, capsys):
    """La fusion garde la version de « cote » (second parent) : comparée au
    premier parent elle serait un recul en_cours -> fige, mais elle ne
    retouche pas le fichier par rapport à chacun de ses parents : ignorée."""
    racine = _depot_git(tmp_path)
    _deux_branches(racine)
    _fusion_resolue_a_la_main(racine, "cote", TOML_REMANIE_AVEC_DEROGATION)
    fusion = _sha(racine)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 0
    assert f"[{fusion[:7]}]" not in capsys.readouterr().out


def test_commits_fusion_qui_retouche_le_fichier_est_controlee(tmp_path, capsys):
    """Résolution à la main qui diffère des deux parents : comparée au premier
    parent (en_cours), où fiche-b devient fiche-c sans dérogation."""
    racine = _depot_git(tmp_path)
    _deux_branches(racine)
    _fusion_resolue_a_la_main(
        racine, "cote", TOML_EN_COURS.replace('fiche = "fiche-b"', 'fiche = "fiche-c"')
    )
    fusion = _sha(racine)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 1
    assert f"[{fusion[:7]}] [sprint 1] était 'en_cours' et a changé sans dérogation" in (
        capsys.readouterr().out
    )


def test_commits_fusion_qui_retouche_le_fichier_legitimement_passe(tmp_path):
    racine = _depot_git(tmp_path)
    _deux_branches(racine)
    _fusion_resolue_a_la_main(
        racine,
        "cote",
        TOML_REMANIE_AVEC_DEROGATION.replace('statut = "fige"', 'statut = "en_cours"'),
    )
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 0


def test_commits_une_fusion_ne_masque_pas_un_commit_fautif_de_l_autre_cote(tmp_path, capsys):
    """Sans --full-history, git suivrait seulement le parent identique à la
    fusion et sauterait le commit fautif du premier parent."""
    racine = _depot_git(tmp_path)
    _git(racine, "branch", "-q", "-M", "principale")
    _commit_toml(racine, TOML_CLOS)  # fige -> clos : saut interdit
    fautif = _sha(racine)
    _branche(racine, "cote", "HEAD~1")
    _commit_toml(racine, TOML_EN_COURS)
    _git(racine, "checkout", "-q", "principale")
    _fusion_resolue_a_la_main(racine, "cote", TOML_EN_COURS)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 1
    assert f"[{fautif[:7]}] [sprint 1] statut avancé de plus d'une étape" in capsys.readouterr().out


def test_commits_ref_introuvable(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    assert main(["--racine", str(racine), "--commits", "ref-qui-n-existe-pas"]) == 1
    assert "[commits] référence git introuvable" in capsys.readouterr().out


def test_commits_hors_depot_git(tmp_path, capsys):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature", "fiche-b": "feature"})
    (racine / "docs" / "backlog" / "sprints.toml").write_text(TOML_BASE, encoding="utf-8")
    assert main(["--racine", str(racine), "--commits", "HEAD"]) == 1
    assert "n'est pas un dépôt git" in capsys.readouterr().out


def test_commits_toml_invalide_dans_un_commit_intermediaire(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, "[[sprint]\nnumero = ")
    fautif = _sha(racine)
    _commit_toml(racine, TOML_EN_COURS)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 1
    assert f"[{fautif[:7]}] docs/backlog/sprints.toml n'est pas un TOML valide" in (
        capsys.readouterr().out
    )


def test_commits_creation_toleree_et_dite(tmp_path, capsys):
    racine = _depot_git(tmp_path, contenu_base=None)
    _commit_toml(racine, TOML_BASE)
    createur = _sha(racine)
    _commit_toml(racine, TOML_EN_COURS)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 0
    assert f"[{createur[:7]}] création" in capsys.readouterr().out


def test_commits_creation_au_commit_racine(tmp_path, capsys):
    """Base sans ancêtre commun : le commit racine, qui crée le fichier, est
    dans la plage ; sans parent, c'est une création."""
    racine = _depot_git(tmp_path)  # le commit racine crée le fichier
    racine_sha = _sha(racine)
    _commit_toml(racine, TOML_EN_COURS)
    # commit sans parent, sans lien avec l'historique de HEAD
    orphelin = subprocess.run(
        [*GIT, "commit-tree", "HEAD^{tree}", "-m", "sans lien"],
        cwd=racine, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert main(["--racine", str(racine), "--commits", orphelin]) == 0
    sortie = capsys.readouterr().out
    assert "2 commit(s)" in sortie
    assert f"[{racine_sha[:7]}] création" in sortie


def test_commits_base_qui_n_est_pas_un_commit(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    arbre = subprocess.run(
        [*GIT, "rev-parse", "HEAD^{tree}"], cwd=racine, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert main(["--racine", str(racine), "--commits", arbre]) == 1
    assert "référence git introuvable" in capsys.readouterr().out


def test_commits_suppression_puis_recreation_refusees(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    _git(racine, "rm", "-q", "docs/backlog/sprints.toml")
    _git(racine, "commit", "-q", "-m", "suppression")
    suppression = _sha(racine)
    _commit_toml(racine, TOML_EN_COURS)
    recreation = _sha(racine)
    assert main(["--racine", str(racine), "--commits", "HEAD~2"]) == 1
    sortie = capsys.readouterr().out
    assert f"[{suppression[:7]}] docs/backlog/sprints.toml supprimé" in sortie
    assert f"[{recreation[:7]}] docs/backlog/sprints.toml recréé" in sortie


def test_commits_et_base_sont_exclusifs(tmp_path):
    racine = _depot_git(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--racine", str(racine), "--base", "HEAD", "--commits", "HEAD"])
    assert exc.value.code == 2


def test_commits_version_courante_passe_toujours_les_regles_statiques(tmp_path, capsys):
    racine = _depot_git(tmp_path)
    (racine / "docs" / "backlog" / "sprints.toml").write_text(
        TOML_BASE.replace('titre = "Titre"', 'titre = "Titre"\nclef_inconnue = 1'),
        encoding="utf-8",
    )
    assert main(["--racine", str(racine), "--commits", "HEAD"]) == 1
    assert "clé(s) inconnue(s)" in capsys.readouterr().out


def _git_show_en_echec(monkeypatch):
    """Le fichier existe dans l'objet git mais `git show` échoue (dépôt
    abîmé, objet manquant) : jamais un saut silencieux."""
    vrai_git = verifier_backlog._git

    def faux_git(racine, *arguments):
        if arguments[:1] == ("show",):
            return subprocess.CompletedProcess(["git", *arguments], 128, "", "objet manquant")
        return vrai_git(racine, *arguments)

    monkeypatch.setattr(verifier_backlog, "_git", faux_git)


def test_base_git_show_en_echec_est_une_violation(tmp_path, capsys, monkeypatch):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_EN_COURS)
    _git_show_en_echec(monkeypatch)
    assert main(["--racine", str(racine), "--base", "HEAD~1"]) == 1
    assert "illisible : objet manquant" in capsys.readouterr().out


def test_commits_git_show_en_echec_est_une_violation(tmp_path, capsys, monkeypatch):
    racine = _depot_git(tmp_path)
    _commit_toml(racine, TOML_EN_COURS)
    commit = _sha(racine)
    _git_show_en_echec(monkeypatch)
    assert main(["--racine", str(racine), "--commits", "HEAD~1"]) == 1
    assert f"[{commit[:7]}] docs/backlog/sprints.toml illisible : objet manquant" in (
        capsys.readouterr().out
    )


def test_commits_premier_parent_illisible_est_une_violation(tmp_path, capsys):
    """Le premier parent est hors de la plage (c'est la base) et son TOML est
    invalide : le commit qui le répare ne peut pas être comparé."""
    racine = _depot_git(tmp_path, contenu_base="[[sprint]\nnumero = ")
    _commit_toml(racine, TOML_BASE)
    assert main(["--racine", str(racine), "--commits", "HEAD~1"]) == 1
    assert "au premier parent" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Correction 1 : espace insécable (U+00A0) et espace fine insécable (U+202F)
# tolérées dans titre/raison, le reste d'isprintable() inchangé.
# ---------------------------------------------------------------------------


def test_espace_insecable_et_fine_toleree_dans_titre_et_raisons(tmp_path):
    nbsp = " "
    nnbsp = " "
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        f'[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre{nbsp}: essai"\n'
        f'[[sprint.element]]\nfiche = "fiche-a"\nstatut = "abandonne"\n'
        f'raison = "raison{nnbsp}: pas de souci ici"\n',
    )
    violations = violations_statiques(donnees, racine)
    assert not _viole(violations, "'titre' contient un caractère non imprimable")
    assert not _viole(violations, "'raison' contient un caractère non imprimable")

    entree_ok = f"26/09/2026 : raison avec une espace fine{nnbsp}: correcte"
    assert verifier_backlog.valider_entree_derogation(entree_ok) is None
    entree_ok_nbsp = f"26/09/2026 : raison avec une espace insécable{nbsp}: correcte"
    assert verifier_backlog.valider_entree_derogation(entree_ok_nbsp) is None


def test_autres_caracteres_non_imprimables_toujours_refuses_non_regression(tmp_path):
    """Non-régression : \\r et \\x0b (parmi d'autres) restent refusés, seules
    U+00A0 et U+202F sont tolérées en plus."""
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    # Échappements TOML (\r, \u000b) : le caractère brut correspondant n'est
    # pas légal tel quel dans une chaîne TOML sur une ligne.
    for piege_toml in ("\\r", "\\u000b"):
        donnees = _ecrire_toml(
            racine,
            f'[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre{piege_toml}suite"\n'
            f'[[sprint.element]]\nfiche = "fiche-a"\nstatut = "abandonne"\n'
            f'raison = "raison{piege_toml}suite ici"\n',
        )
        violations = violations_statiques(donnees, racine)
        assert _viole(violations, "'titre' contient un caractère non imprimable"), piege_toml
        assert _viole(violations, "'raison' contient un caractère non imprimable"), piege_toml

    entree = "26/09/2026 : raison avec un\rretour chariot ici"
    assert "non imprimable" in verifier_backlog.valider_entree_derogation(entree)


# ---------------------------------------------------------------------------
# Correction 2 : un champ d'un type inattendu (liste, table…) ne plante
# jamais le script — une violation propre, jamais une exception.
# ---------------------------------------------------------------------------


def test_robustesse_type_statut_sprint(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = []\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "prevu"\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'statut' invalide")


def test_robustesse_type_statut_element(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "clos"\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = []\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'statut' invalide")


def test_robustesse_type_numero(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = []\nstatut = "fige"\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "prevu"\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'numero' doit être un entier")


def test_robustesse_type_titre(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = { x = 1 }\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "prevu"\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'titre' doit être une chaîne")


def test_robustesse_type_fiche(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = []\nstatut = "prevu"\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'fiche' doit être une chaîne")


def test_robustesse_type_chantier(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre"\n'
        '[[sprint.element]]\nchantier = { x = 1 }\nstatut = "prevu"\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'chantier' doit être une chaîne")


def test_robustesse_type_pr(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "en_cours"\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "livre"\npr = []\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'pr' doit être un entier")


def test_robustesse_type_raison(tmp_path):
    racine = _preparer_depot(tmp_path, {"fiche-a": "feature"})
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre"\n'
        '[[sprint.element]]\nfiche = "fiche-a"\nstatut = "abandonne"\nraison = []\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "'raison' doit être une chaîne")


def test_robustesse_type_derogations(tmp_path):
    racine = _preparer_depot(tmp_path)
    donnees = _ecrire_toml(
        racine,
        '[[sprint]]\nnumero = 1\nstatut = "fige"\ntitre = "Titre"\nderogations = { x = 1 }\n',
    )
    violations = violations_statiques(donnees, racine)  # ne doit pas lever
    assert violations != []
    assert _viole(violations, "derogations doit être une liste de chaînes")

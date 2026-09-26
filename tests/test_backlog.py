"""Tests de scripts/verifier_backlog.py (outillage de dépôt, pas le cœur)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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

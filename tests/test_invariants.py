"""Invariants de doctrine, vérifiés sur le code source lui-même.

Règle absolue 2 de CLAUDE.md : sous `src/ourouler/`, seuls `cli.py` et
`config.py` ont le droit de toucher un fichier de configuration, une
variable d'environnement ou un chemin utilisateur. Plutôt que de faire
confiance à la relecture, on le mesure.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parents[1] / "src" / "ourouler"
TESTS = Path(__file__).resolve().parent

#: Modules autorisés à lire l'environnement d'exécution.
AUTORISES = {"cli.py", "config.py"}

#: Ce qu'un module du cœur ne doit jamais faire.
INTERDITS = ("tomllib", "os.environ", "getenv", "Path.home()", ".expanduser(", "load_dotenv")


def modules_du_coeur() -> list[Path]:
    return sorted(p for p in SOURCES.rglob("*.py") if p.name not in AUTORISES)


def test_il_y_a_bien_des_modules_a_verifier():
    noms = {p.name for p in modules_du_coeur()}
    assert {"lecture.py", "cache.py", "inventaire.py", "intervals.py"} <= noms


@pytest.mark.parametrize("module", modules_du_coeur(), ids=lambda p: p.name)
def test_le_coeur_ne_lit_pas_son_environnement(module: Path):
    source = module.read_text(encoding="utf-8")
    for interdit in INTERDITS:
        assert interdit not in source, (
            f"{module.relative_to(SOURCES)} touche « {interdit} » : "
            "seuls cli.py et config.py en ont le droit"
        )


@pytest.mark.parametrize("module", modules_du_coeur(), ids=lambda p: p.name)
def test_le_coeur_n_importe_pas_tomllib(module: Path):
    arbre = ast.parse(module.read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            importes.add(noeud.module.split(".")[0])
    assert "tomllib" not in importes
    assert "os" not in importes


def test_aucun_client_http_reel_n_est_cree_a_l_import():
    """Un connecteur ne doit ouvrir un client qu'à la demande, jamais au chargement."""
    intervals = (SOURCES / "connecteurs" / "intervals.py").read_text(encoding="utf-8")
    arbre = ast.parse(intervals)
    for noeud in arbre.body:  # niveau module uniquement
        assert not isinstance(noeud, ast.Assign) or "httpx.Client" not in ast.unparse(noeud.value)


@pytest.mark.parametrize(
    "fichier", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name
)
def test_aucun_test_ne_cree_un_client_http_sans_transport_bouchonne(fichier: Path):
    """`httpx.Client(...)` n'est permis dans les tests qu'avec un MockTransport."""
    source = fichier.read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if not isinstance(noeud, ast.Call):
            continue
        appel = ast.unparse(noeud.func)
        if appel in ("httpx.Client", "httpx.AsyncClient"):
            assert "MockTransport" in ast.unparse(noeud), (
                f"{fichier.name} : client httpx sans MockTransport — un test ne "
                "doit jamais pouvoir sortir sur le réseau"
            )


def test_les_fixtures_ne_contiennent_aucune_coordonnee_reelle():
    """Les traces synthétiques tournent autour de (0, 0) : moins de 0,5° d'écart."""
    generateur = (TESTS / "fixtures" / "generer_activites.py").read_text(encoding="utf-8")
    assert "LAT_FICTIVE = 0.0" in generateur
    assert "LON_FICTIVE = 0.0" in generateur
    config = (TESTS / "fixtures" / "config_test.toml").read_text(encoding="utf-8")
    assert "latitude = 0.0" in config and "longitude = 0.0" in config
    assert 'api_key = ""' in config

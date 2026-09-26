"""Le filet de la règle absolue 1, mesuré sur `.gitignore` lui-même.

Règle absolue 1 de CLAUDE.md : aucune donnée personnelle dans le dépôt, « les
fixtures sont synthétiques ou anonymisées, **réintégrées nommément** dans
`.gitignore` ». Le dépôt a longtemps porté `!tests/fixtures/**`, une
réintégration en bloc : les patrons `*.fit`, `*.gpx`, `*.tcx` étaient annulés
d'un coup sous `tests/fixtures/`, et un vrai fichier d'activité déposé dans
`tests/fixtures/activites/` se serait retrouvé commité sans la moindre
résistance — ni ligne rouge dans `git status`, ni rien.

Trois choses sont mesurées ici :

1. aucune réintégration n'est générique — la prochaine ligne `!…/**` échoue ;
2. la liste nommée est exactement la sortie de `generer_activites.py`, ni plus
   (un nom qui n'est plus produit sort) ni moins (une fixture ajoutée au
   générateur et oubliée ici serait ignorée à la prochaine régénération) ;
3. git, interrogé pour de vrai, ignore bien un fichier d'activité qui ne
   figure pas dans cette liste, et n'ignore aucune fixture versionnée.

Le point 3 passe par `git check-ignore` : les subtilités de `.gitignore`
(ordre des règles, `core.ignorecase`, réintégration impossible sous un dossier
exclu) ne se réimplémentent pas honnêtement en Python, et c'est le verdict de
git qui compte. Aucun réseau, aucune écriture dans le dépôt.

Ce verdict est demandé **sous les deux valeurs de `core.ignorecase`** : macOS
(insensible à la casse, `true`) et Linux (CI, serveur, `false`). Interrogé
seulement avec la configuration de la machine, le filet était vert sur le Mac
du mainteneur alors que `*.gpx` laissait passer `Ma_sortie_du_dimanche.GPX`
sous Linux (run CI 36149735808).

**Ce que ce filet ne peut pas attraper**, et qu'il ne faut pas croire qu'il
attrape : un vrai fichier déposé sous le nom exact d'une fixture. `boucle.fit`
est réintégré, donc un `boucle.fit` réel le serait aussi — et sur un système de
fichiers insensible à la casse (macOS, `core.ignorecase`), ses variantes de
casse avec lui. C'est le prix de la réintégration nommée, et le rattrapage est
ailleurs : `test_invariants.py` compare chaque fixture versionnée octet pour
octet à ce que le générateur produit, et y lit les coordonnées. Un vrai fichier
sous un nom de fixture passe le filet de `.gitignore` et meurt là.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
GITIGNORE = RACINE / ".gitignore"

#: Ce qui fait d'une réintégration une réintégration « en bloc ».
JOKERS = ("*", "?", "[")


def lignes_utiles() -> list[str]:
    """Les lignes de `.gitignore` qui portent une règle (ni vides, ni commentaires)."""
    return [
        ligne.strip()
        for ligne in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if ligne.strip() and not ligne.lstrip().startswith("#")
    ]


def reintegrations() -> list[str]:
    """Les motifs réintégrés, sans le `!` de tête."""
    return [ligne[1:] for ligne in lignes_utiles() if ligne.startswith("!")]


def extensions_ignorees() -> set[str]:
    """Les extensions qu'une règle `*.xxx` de `.gitignore` attrape, en minuscules.

    Lues dans le fichier plutôt qu'écrites ici : si `*.kml` est ajouté demain
    aux données de l'utilisateur, une fixture `.kml` devra elle aussi être
    réintégrée nommément, sans qu'on ait à y penser.

    Une extension écrite en classes de caractères (`*.[gG][pP][xX]`, la forme
    insensible à la casse) compte pour son nom en minuscules (`gpx`).
    """
    extensions = set()
    for ligne in lignes_utiles():
        trouve = re.fullmatch(r"\*\.((?:\w|\[\w\w\])+)", ligne)
        if trouve:
            extensions.add(re.sub(r"\[(\w)\w\]", r"\1", trouve.group(1)).lower())
    return extensions


def noms_a_reintegrer(noms: list[str]) -> set[str]:
    """Parmi des noms de fixtures, ceux qu'une règle `*.xxx` ignorerait.

    Comparaison en minuscules des deux côtés : `COURTE.GPX` est attrapé par
    `*.[gG][pP][xX]` quelle que soit la casse du système de fichiers, il doit
    donc être nommé. Ce qui ne rend pas la liste de réintégrations insensible
    à la casse pour autant : voir la limite dite en tête de module.
    """
    return {nom for nom in noms if nom.rsplit(".", 1)[-1].lower() in extensions_ignorees()}


# --- git, interrogé pour de vrai ---------------------------------------------


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(RACINE), *arguments], capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def git_disponible() -> None:
    """Sans dépôt git (archive, tarball), les tests qui interrogent git n'ont pas de sens."""
    if shutil.which("git") is None:
        pytest.skip("git absent de la machine")
    if _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        pytest.skip("pas dans un dépôt git")


#: Les deux valeurs de `core.ignorecase` : macOS (`true`), Linux (`false`).
CASSES = (True, False)


def _option_casse(ignorecase: bool) -> tuple[str, str]:
    return ("-c", f"core.ignorecase={'true' if ignorecase else 'false'}")


def est_ignore(chemin_relatif: str, *, ignorecase: bool) -> bool:
    """Le verdict de git sur un chemin, qu'il existe ou non sur le disque.

    `ignorecase` impose `core.ignorecase` au lieu de prendre celui de la
    machine : le filet doit tenir sous Linux même quand on le mesure sur macOS.
    """
    options = _option_casse(ignorecase)
    return _git(*options, "check-ignore", "--no-index", "-q", chemin_relatif).returncode == 0


@pytest.mark.parametrize("ignorecase", CASSES, ids=lambda v: f"ignorecase={v}")
def test_la_sonde_mesure_bien_quelque_chose(ignorecase: bool, git_disponible: None):
    """Sans ce contrôle, un `est_ignore` cassé rendrait tous les tests suivants verts."""
    assert est_ignore(".venv/lib/python3.12/site-packages/x.py", ignorecase=ignorecase), (
        "`.venv/` doit être ignoré"
    )
    assert not est_ignore("pyproject.toml", ignorecase=ignorecase), "`pyproject.toml` ne doit pas être ignoré"


def test_la_sonde_distingue_les_deux_casses(git_disponible: None):
    """Sans ce contrôle, `-c core.ignorecase` pourrait être sans effet et le
    paramétrage sur les deux casses ne mesurerait qu'une seule configuration.

    `COURTE.GPX` est réintégré nommément : sa variante en minuscules l'est
    aussi quand la casse est ignorée (macOS), et ne l'est pas sous Linux.
    """
    variante = "tests/fixtures/activites/courte.gpx"
    assert not est_ignore(variante, ignorecase=True)
    assert est_ignore(variante, ignorecase=False)


# --- 1. aucune réintégration en bloc -----------------------------------------


@pytest.mark.parametrize("motif", reintegrations(), ids=lambda m: m)
def test_aucune_reintegration_n_est_generique(motif: str):
    """La règle absolue 1 dit « nommément » : un joker dans un `!` la contourne."""
    for joker in JOKERS:
        assert joker not in motif, (
            f"`!{motif}` réintègre en bloc : la règle absolue 1 exige une réintégration "
            "nommée, fichier par fichier. Citer chaque fichier, ou laisser le patron faire "
            "son travail."
        )
    assert not motif.endswith("/"), (
        f"`!{motif}` réintègre un dossier entier, donc tout ce qu'on y déposera plus tard"
    )


def test_il_y_a_bien_des_reintegrations_a_verifier():
    """Vert parce qu'il n'y a plus aucun `!` serait un invariant creux."""
    assert len(reintegrations()) >= 10


# --- 2. la liste nommée suit le générateur -----------------------------------


def test_les_fixtures_d_activite_sont_reintegrees_nommement(generateur, tmp_path: Path):
    """La liste de `.gitignore` est exactement ce que le générateur produit.

    Le générateur est la source de vérité (cf. `test_invariants.py`) : lui seul
    dit quels fichiers ont le droit d'être versionnés là. Écrire la liste à la
    main des deux côtés, c'est la voir dériver au premier ajout de fixture.
    """
    produits = noms_a_reintegrer(sorted(generateur.generer(tmp_path)))
    prefixe = "tests/fixtures/activites/"
    nommes = {motif[len(prefixe) :] for motif in reintegrations() if motif.startswith(prefixe)}

    manquants = produits - nommes
    assert not manquants, (
        f"{sorted(manquants)} : fixtures produites par generer_activites.py mais absentes "
        f"de .gitignore — elles seront ignorées à la prochaine régénération. Ajouter "
        f"`!{prefixe}<nom>` pour chacune."
    )
    en_trop = nommes - produits
    assert not en_trop, (
        f"{sorted(en_trop)} : réintégrées dans .gitignore alors que generer_activites.py ne "
        "les produit plus. Une réintégration qui survit à sa fixture est une porte laissée "
        "ouverte : y déposer un vrai fichier de ce nom suffirait à le commiter."
    )
    assert produits, "aucune fixture à réintégrer : le test ne mesurerait rien"


def test_les_noms_non_ignores_ne_sont_pas_reintegres(generateur, tmp_path: Path):
    """`inconnu.dat` n'est attrapé par aucun patron : le réintégrer serait du bruit."""
    produits = sorted(generateur.generer(tmp_path))
    libres = set(produits) - noms_a_reintegrer(produits)
    assert "inconnu.dat" in libres, "le générateur ne produit plus de fixture sans extension ignorée"
    nommes = {motif.rsplit("/", 1)[-1] for motif in reintegrations()}
    assert not (libres & nommes), f"{sorted(libres & nommes)} : réintégration inutile"


# --- 3. le verdict de git ----------------------------------------------------

#: Des noms qu'un vrai fichier d'activité pourrait porter. Aucun n'est écrit sur
#: le disque : `check-ignore --no-index` juge un chemin hypothétique.
DEPOTS_INTERDITS = (
    "tests/fixtures/activites/sortie_2026_09_17.fit",
    "tests/fixtures/activites/Ma_sortie_du_dimanche.GPX",
    "tests/fixtures/activites/EXPORT_GARMIN.FIT",
    "tests/fixtures/activites/Sortie.Tcx",
    "tests/fixtures/activites/sortie.gPx",
    "tests/fixtures/activites/entrainement.gpx",
    "tests/fixtures/activites/entrainement.tcx",
    "tests/fixtures/activites/sous_dossier/vraie_trace.fit",
    "tests/fixtures/traces/vraie_trace.gpx",
    "tests/fixtures/carte_de_la_boucle.html",
    "tests/adversarial/fixtures/nominal.fit",
    "tests/adversarial/fixtures/activite_sans_extension",
)


@pytest.mark.parametrize("ignorecase", CASSES, ids=lambda v: f"ignorecase={v}")
@pytest.mark.parametrize("chemin", DEPOTS_INTERDITS, ids=lambda c: c)
def test_un_vrai_fichier_d_activite_reste_ignore(chemin: str, ignorecase: bool, git_disponible: None):
    """Le cas que `!tests/fixtures/**` laissait passer, posé à git tel quel.

    Sous les deux casses : `*.gpx` seul laissait passer `….GPX` sous Linux.
    """
    assert est_ignore(chemin, ignorecase=ignorecase), (
        f"{chemin} serait commité sans résistance (core.ignorecase={ignorecase}). "
        "C'est exactement ce que la règle absolue 1 interdit : seules les fixtures "
        "nommées sont réintégrées."
    )


@pytest.mark.parametrize("ignorecase", CASSES, ids=lambda v: f"ignorecase={v}")
def test_aucun_fichier_versionne_n_est_ignore(ignorecase: bool, git_disponible: None):
    """Le filet doit se resserrer sur les vraies données, pas sur le dépôt.

    Un fichier à la fois suivi et ignoré est un piège : il reste dans l'index,
    mais toute suppression puis régénération le fait disparaître en silence.
    """
    suivis = _git("ls-files").stdout.splitlines()
    assert suivis, "aucun fichier suivi : le test ne mesurerait rien"
    ignores = subprocess.run(
        ["git", "-C", str(RACINE), *_option_casse(ignorecase), "check-ignore", "--stdin", "--no-index"],
        input="\n".join(suivis),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert not ignores, (
        f"{ignores} : fichiers versionnés que .gitignore ignore. Les réintégrer nommément, "
        "ou les sortir du dépôt."
    )

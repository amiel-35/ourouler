"""Tests du cache local (L1.3)."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from ourouler.activites.cache import NOM_BRUT, NOM_INDEX, Cache
from ourouler.erreurs import ErreurLecture, ErreurUtilisateur


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache")


def octets(activites: Path, nom: str) -> bytes:
    return (activites / nom).read_bytes()


# --- création -----------------------------------------------------------------


def test_creation_du_dossier_et_de_l_index(tmp_path: Path):
    c = Cache(tmp_path / "profond" / "cache")
    assert (c.dossier / NOM_BRUT).is_dir()
    assert (c.dossier / NOM_INDEX).is_file()
    assert c.lister() == []


def test_ouvrir_deux_fois_le_meme_cache_ne_perd_rien(tmp_path: Path, activites: Path):
    dossier = tmp_path / "cache"
    identifiant = Cache(dossier).ajouter(
        octets(activites, "boucle.fit"),
        source="fichier",
        id_externe="boucle.fit",
        extension="fit",
        meta={},
    )
    encore = Cache(dossier)
    assert [e.identifiant for e in encore.lister()] == [identifiant]


def test_dossier_non_inscriptible(tmp_path: Path):
    interdit = tmp_path / "interdit"
    interdit.mkdir()
    interdit.chmod(0o500)
    try:
        with pytest.raises(ErreurUtilisateur) as e:
            Cache(interdit / "cache")
        assert "cache" in str(e.value)
    finally:
        interdit.chmod(0o700)


def test_index_corrompu_donne_une_erreur_utilisateur(tmp_path: Path):
    dossier = tmp_path / "cache"
    Cache(dossier)
    (dossier / NOM_INDEX).write_bytes(b"ceci n'est pas une base SQLite" * 100)
    with pytest.raises(ErreurUtilisateur) as e:
        Cache(dossier)
    assert "corrompu" in str(e.value) or "inutilisable" in str(e.value)


# --- ajout et idempotence -----------------------------------------------------


def test_ajouter_archive_le_brut_et_indexe(cache: Cache, activites: Path):
    identifiant = cache.ajouter(
        octets(activites, "boucle.fit"),
        source="intervals",
        id_externe="42",
        extension="fit",
        meta={"nom": "Sortie inventée", "equipement": "Route"},
    )
    assert len(identifiant) == 64  # sha256 hexadécimal
    brut = cache.chemin(identifiant)
    assert brut.is_file() and brut.name == f"{identifiant}.fit"
    assert brut.read_bytes() == octets(activites, "boucle.fit")

    (entree,) = cache.lister()
    assert entree.identifiant == identifiant
    assert entree.source == "intervals" and entree.id_externe == "42"
    assert entree.jour == date(2024, 3, 30)
    assert entree.duree_s == pytest.approx(678, abs=1)
    assert entree.distance_m and entree.distance_m > 4000
    assert entree.puissance_moy_w == pytest.approx(206.6, abs=0.5)
    assert entree.equipement == "Route"
    assert entree.meta["nom"] == "Sortie inventée"


def test_ajouter_deux_fois_le_meme_contenu_est_idempotent(cache: Cache, activites: Path):
    contenu = octets(activites, "boucle.gpx")
    premier = cache.ajouter(contenu, source="fichier", id_externe="a.gpx", extension="gpx", meta={})
    second = cache.ajouter(contenu, source="fichier", id_externe="b.gpx", extension="gpx", meta={})
    assert premier == second
    assert len(cache.lister()) == 1
    assert len(list((cache.dossier / NOM_BRUT).iterdir())) == 1


def test_extension_toleree_avec_point_et_majuscules(cache: Cache, activites: Path):
    identifiant = cache.ajouter(
        octets(activites, "COURTE.GPX"),
        source="fichier",
        id_externe="COURTE.GPX",
        extension=".GPX",
        meta={},
    )
    assert cache.chemin(identifiant).suffix == ".gpx"


def test_ajouter_un_contenu_illisible_n_ecrit_rien(cache: Cache):
    with pytest.raises(ErreurLecture):
        cache.ajouter(b"", source="fichier", id_externe="vide.fit", extension="fit", meta={})
    assert cache.lister() == []
    assert list((cache.dossier / NOM_BRUT).iterdir()) == []


def test_metadonnees_de_la_source_priment_sur_le_fichier(cache: Cache, activites: Path):
    """Intervals sait que c'est un VirtualRide là où le FIT dit « cycling »."""
    identifiant = cache.ajouter(
        octets(activites, "boucle.fit"),
        source="intervals",
        id_externe="7",
        extension="fit",
        meta={"sport": "VirtualRide", "appareil": "Zwift", "equipement": "Home-trainer"},
    )
    (entree,) = cache.lister()
    assert entree.identifiant == identifiant
    assert entree.sport == "VirtualRide"
    assert entree.appareil == "Zwift"
    # Les mesures, elles, viennent bien du fichier.
    assert entree.puissance_moy_w == pytest.approx(206.6, abs=0.5)


# --- interrogation ------------------------------------------------------------


def test_contient_par_source_et_id_externe(cache: Cache, activites: Path):
    cache.ajouter(
        octets(activites, "boucle.fit"), source="intervals", id_externe="99", extension="fit", meta={}
    )
    assert cache.contient(source="intervals", id_externe="99")
    assert cache.contient(source="intervals", id_externe=99)  # accepte un entier
    assert not cache.contient(source="intervals", id_externe="100")
    assert not cache.contient(source="fichier", id_externe="99")


def test_lister_filtre_par_dates(cache: Cache, activites: Path):
    cache.indexer_dossier(activites)
    tout = cache.lister()
    assert len(tout) == 8
    assert [e.jour for e in tout] == sorted(e.jour for e in tout)  # trié par date

    mars = cache.lister(depuis=date(2024, 3, 1), jusqua=date(2024, 3, 31))
    avril = cache.lister(depuis=date(2024, 4, 1))
    assert len(mars) == 7 and len(avril) == 1
    assert all(e.jour.month == 3 for e in mars)
    assert avril[0].id_externe == "COURTE.GPX"
    assert cache.lister(depuis=date(2025, 1, 1)) == []
    # Les bornes sont incluses.
    assert len(cache.lister(depuis=date(2024, 3, 30), jusqua=date(2024, 3, 30))) == 7


def test_chemin_inconnu_leve_key_error(cache: Cache):
    with pytest.raises(KeyError):
        cache.chemin("0" * 64)


def test_relire_rend_tous_les_points(cache: Cache, activites: Path):
    identifiant = cache.ajouter(
        octets(activites, "boucle.tcx"), source="fichier", id_externe="x.tcx", extension="tcx", meta={}
    )
    activite = cache.relire(identifiant)
    assert len(activite.points) == 340
    assert activite.source == "tcx"


# --- import d'un dossier ------------------------------------------------------


def test_indexer_dossier_ignore_les_fichiers_abimes(cache: Cache, activites: Path):
    ajoutes = cache.indexer_dossier(activites)
    assert ajoutes == 8
    assert len(cache.echecs) == 6  # 3 vides + 3 tronqués
    assert all("<octets>" not in e for e in cache.echecs), "le message doit nommer le fichier"
    assert any(e.startswith("vide.fit") for e in cache.echecs)
    assert all(e.source == "fichier" for e in cache.lister())


def test_indexer_dossier_deux_fois_n_ajoute_rien(cache: Cache, activites: Path):
    assert cache.indexer_dossier(activites) == 8
    assert cache.indexer_dossier(activites) == 0
    assert len(cache.lister()) == 8


def test_indexer_dossier_absent(cache: Cache, tmp_path: Path):
    with pytest.raises(ErreurUtilisateur) as e:
        cache.indexer_dossier(tmp_path / "nulle_part")
    assert "introuvable" in str(e.value)


def test_indexer_dossier_descend_dans_les_sous_dossiers(cache: Cache, activites: Path, tmp_path: Path):
    racine = tmp_path / "import"
    (racine / "2024" / "mars").mkdir(parents=True)
    (racine / "2024" / "mars" / "une.fit").write_bytes(octets(activites, "boucle.fit"))
    assert cache.indexer_dossier(racine) == 1


def test_l_index_est_bien_du_sqlite_standard(cache: Cache, activites: Path):
    """L'index doit rester lisible par n'importe quel outil SQLite."""
    cache.ajouter(
        octets(activites, "boucle.fit"), source="fichier", id_externe="a.fit", extension="fit", meta={}
    )
    cx = sqlite3.connect(cache.index)
    try:
        assert cx.execute("SELECT count(*) FROM activites").fetchone()[0] == 1
        assert cx.execute("PRAGMA user_version").fetchone()[0] >= 1
    finally:
        cx.close()

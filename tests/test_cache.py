"""Tests du cache local (L1.3)."""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ourouler.activites.cache import NOM_BRUT, NOM_INDEX, VERSION_SCHEMA, Cache
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
    assert entree.duree_s == pytest.approx(708, abs=1)
    assert entree.distance_m and entree.distance_m > 4000
    assert entree.puissance_moy_w == pytest.approx(206.9, abs=0.5)
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


def test_lister_bornes_datetime_et_chaine_iso(cache: Cache, activites: Path):
    """Une borne peut être une `date`, un `datetime` ou une chaîne ISO."""
    cache.indexer_dossier(activites)
    attendu = cache.lister(depuis=date(2024, 4, 1))
    assert cache.lister(depuis=datetime(2024, 4, 1, 13, 45, tzinfo=UTC)) == attendu
    assert cache.lister(depuis="2024-04-01") == attendu
    assert cache.lister(depuis="2024-04-01T13:45:00+00:00") == attendu
    assert cache.lister(depuis=" 2024-04-01 ") == attendu


@pytest.mark.parametrize("borne", [15, 3.5, True, object(), date, ["2024-04-01"]])
def test_lister_borne_de_type_refuse_nomme_le_parametre(cache: Cache, borne):
    with pytest.raises(ErreurUtilisateur, match="depuis"):
        cache.lister(depuis=borne)
    with pytest.raises(ErreurUtilisateur, match="jusqua"):
        cache.lister(jusqua=borne)


def test_lister_borne_chaine_non_iso_refusee(cache: Cache):
    with pytest.raises(ErreurUtilisateur, match="depuis"):
        cache.lister(depuis="hier")
    with pytest.raises(ErreurUtilisateur, match="jusqua"):
        cache.lister(jusqua="01/04/2024")


def test_lister_bornes_inversees_rend_une_liste_vide(cache: Cache, activites: Path):
    """Un intervalle vide n'est pas une erreur : il est simplement vide."""
    cache.indexer_dossier(activites)
    assert cache.lister(depuis=date(2024, 12, 31), jusqua=date(2024, 1, 1)) == []


def test_chemin_inconnu_leve_key_error(cache: Cache):
    with pytest.raises(KeyError):
        cache.chemin("0" * 64)


def test_relire_rend_tous_les_points(cache: Cache, activites: Path):
    identifiant = cache.ajouter(
        octets(activites, "boucle.tcx"), source="fichier", id_externe="x.tcx", extension="tcx", meta={}
    )
    activite = cache.relire(identifiant)
    assert len(activite.points) == 60
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


def test_indexer_dossier_compte_un_fichier_illisible_sans_trace(
    cache: Cache, activites: Path, tmp_path: Path
):
    """Test qui aurait attrapé C1 : `read_bytes()` était hors du `try`.

    Un fichier sans droit de lecture levait une `PermissionError` nue — pas
    une `ErreurUtilisateur` — qui sortait en trace avec le code 1, contre le
    docstring de `indexer_dossier`.
    """
    if os.geteuid() == 0:  # pragma: no cover - root lit tout, le test n'a pas de sens
        pytest.skip("root peut lire un fichier en mode 000")
    dossier = tmp_path / "a_importer"
    dossier.mkdir()
    shutil.copy(activites / "boucle.gpx", dossier / "lisible.gpx")
    interdit = dossier / "interdit.gpx"
    shutil.copy(activites / "boucle.gpx", interdit)
    interdit.chmod(0o000)
    try:
        assert not os.access(interdit, os.R_OK), "le fichier doit vraiment être illisible"
        ajoutes = cache.indexer_dossier(dossier)
    finally:
        interdit.chmod(0o600)  # sinon tmp_path n'est pas nettoyable
    assert ajoutes == 1, "le fichier lisible est importé malgré le voisin illisible"
    assert len(cache.echecs) == 1
    assert cache.echecs[0].startswith("interdit.gpx : "), cache.echecs
    assert "<octets>" not in cache.echecs[0]


def test_indexer_dossier_compte_un_fichier_disparu_sans_trace(
    cache: Cache, activites: Path, tmp_path: Path
):
    """Même famille : un lien symbolique cassé est une `OSError`, pas une trace."""
    dossier = tmp_path / "liens"
    dossier.mkdir()
    shutil.copy(activites / "boucle.gpx", dossier / "lisible.gpx")
    (dossier / "casse.gpx").symlink_to(tmp_path / "nulle_part.gpx")
    ajoutes = cache.indexer_dossier(dossier)
    assert ajoutes == 1
    # `is_file()` est faux sur un lien cassé : il est ignoré avant la lecture.
    assert len(cache.echecs) == 0


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


# --- version du schéma de l'index --------------------------------------------
#
# Dette notée en relecture (C3) : `PRAGMA user_version` était écrit sans jamais
# être relu. Au schéma 2, un index v1 aurait été relu comme s'il était à jour.


def test_l_index_porte_la_version_du_schema(cache: Cache):
    with sqlite3.connect(cache.index) as cx:
        assert cx.execute("PRAGMA user_version").fetchone()[0] == VERSION_SCHEMA


def test_reouvrir_un_index_a_la_bonne_version_marche(cache: Cache, activites: Path):
    cache.ajouter(
        octets(activites, "boucle.gpx"), source="fichier", id_externe="x.gpx", extension="gpx", meta={}
    )
    rouvert = Cache(cache.dossier)
    assert len(rouvert.lister()) == 1


def test_un_index_d_un_autre_schema_est_refuse_avec_la_marche_a_suivre(cache: Cache):
    """Un index venu d'une version future : on refuse en disant quoi faire."""
    with sqlite3.connect(cache.index) as cx:
        cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA + 1}")
    with pytest.raises(ErreurUtilisateur) as e:
        Cache(cache.dossier)
    message = str(e.value)
    assert str(VERSION_SCHEMA + 1) in message and str(VERSION_SCHEMA) in message
    assert "index.sqlite" in message, "le message doit dire quel fichier supprimer"
    assert "bruts sont conservés" in message


def test_un_index_anterieur_au_versionnement_est_tolere(cache: Cache):
    """`user_version = 0` : index d'avant le versionnement, le schéma se repose."""
    with sqlite3.connect(cache.index) as cx:
        cx.execute("PRAGMA user_version = 0")
    rouvert = Cache(cache.dossier)
    assert rouvert.lister() == []
    with sqlite3.connect(rouvert.index) as cx:
        assert cx.execute("PRAGMA user_version").fetchone()[0] == VERSION_SCHEMA


# --- mise à jour des métadonnées sur place (L2.7) ------------------------------


def test_mettre_a_jour_meta_reecrit_sans_toucher_au_fichier(cache: Cache, activites: Path):
    """Enrichir une entrée déjà rapatriée ne doit pas dépendre d'un retéléchargement."""
    identifiant = cache.ajouter(
        octets(activites, "boucle.fit"),
        source="intervals",
        id_externe="42",
        extension="fit",
        meta={"nom": "Sortie inventée"},
    )
    horodatage = cache.chemin(identifiant).stat().st_mtime_ns

    assert cache.mettre_a_jour_meta(
        source="intervals",
        id_externe="42",
        meta={"nom": "Sortie inventée", "power_meter": "CAPTEUR 0001"},
        equipement="Route inventee",
    )
    (entree,) = cache.lister()
    assert entree.identifiant == identifiant
    assert entree.meta["power_meter"] == "CAPTEUR 0001"
    assert entree.equipement == "Route inventee"
    assert cache.chemin(identifiant).stat().st_mtime_ns == horodatage


def test_mettre_a_jour_meta_sur_une_entree_absente_renvoie_faux(cache: Cache):
    assert not cache.mettre_a_jour_meta(source="intervals", id_externe="inconnu", meta={})


def test_mettre_a_jour_meta_sans_equipement_n_efface_pas_l_ancien(cache: Cache, activites: Path):
    """Une réponse plus pauvre ne doit pas effacer ce qu'on savait déjà."""
    cache.ajouter(
        octets(activites, "boucle.fit"),
        source="intervals",
        id_externe="42",
        extension="fit",
        meta={"equipement": "Route inventee"},
    )
    cache.mettre_a_jour_meta(source="intervals", id_externe="42", meta={"gear_id": "b000"})
    (entree,) = cache.lister()
    assert entree.equipement == "Route inventee"
    assert entree.meta["gear_id"] == "b000"


def test_mettre_a_jour_meta_ne_touche_que_la_bonne_source(cache: Cache, activites: Path):
    cache.ajouter(
        octets(activites, "boucle.fit"), source="fichier", id_externe="42", extension="fit", meta={}
    )
    assert not cache.mettre_a_jour_meta(source="intervals", id_externe="42", meta={"x": 1})
    assert cache.lister()[0].meta == {}

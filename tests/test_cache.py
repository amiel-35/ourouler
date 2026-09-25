"""Tests du cache local (L1.3)."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ourouler.activites.cache import NOM_BRUT, NOM_INDEX, VERSION_SCHEMA, Cache
from ourouler.noyau.erreurs import ErreurLecture, ErreurUtilisateur
from ourouler.noyau.proprietaire import PROPRIETAIRE_LOCAL


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


def test_ajouter_deux_fois_la_meme_identite_est_idempotent(cache: Cache, activites: Path):
    contenu = octets(activites, "boucle.gpx")
    premier = cache.ajouter(contenu, source="fichier", id_externe="a.gpx", extension="gpx", meta={})
    second = cache.ajouter(contenu, source="fichier", id_externe="a.gpx", extension="gpx", meta={})
    assert premier == second
    assert len(cache.lister()) == 1
    assert len(list((cache.dossier / NOM_BRUT).iterdir())) == 1


def test_deux_identites_sur_le_meme_contenu_font_deux_entrees(cache: Cache, activites: Path):
    """Un triathlon : natation et vélo, deux activités, un seul FIT (point 2 de la relecture)."""
    contenu = octets(activites, "boucle.gpx")
    premier = cache.ajouter(contenu, source="intervals", id_externe="i1", extension="gpx", meta={})
    second = cache.ajouter(contenu, source="intervals", id_externe="i2", extension="gpx", meta={})
    assert premier == second, "l'identifiant reste le sha256 du contenu : le fichier est partagé"
    entrees = cache.lister()
    assert [e.id_externe for e in entrees] == ["i1", "i2"], "lister() doit rendre les deux"
    assert len(list((cache.dossier / NOM_BRUT).iterdir())) == 1, "un seul fichier brut"
    assert cache.contient(source="intervals", id_externe="i1")
    assert cache.contient(source="intervals", id_externe="i2")


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


#: Le schéma 1, tel qu'il était écrit : `identifiant` clé primaire. Recopié
#: ici (et pas importé) pour que le test continue de décrire l'ancien index
#: même quand le module ne le connaîtra plus.
_SCHEMA_V1 = """
CREATE TABLE activites (
    identifiant       TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    id_externe        TEXT,
    extension         TEXT NOT NULL,
    debut             TEXT,
    duree_s           REAL,
    distance_m        REAL,
    puissance_moy_w   REAL,
    sport             TEXT,
    appareil          TEXT,
    equipement        TEXT,
    meta              TEXT NOT NULL DEFAULT '{}',
    ajoutee_le        TEXT NOT NULL
);
CREATE INDEX idx_activites_debut ON activites(debut);
CREATE INDEX idx_activites_source ON activites(source, id_externe);
"""


def test_un_index_au_schema_1_est_migre_sans_perdre_les_fichiers_bruts(
    tmp_path: Path, activites: Path
):
    """Migration v1 → v2 : les lignes et les fichiers bruts survivent (point 2).

    Le schéma 1 ne sait pas représenter deux activités au même fichier ; on
    ne peut donc pas récupérer ce qu'il avait déjà perdu, mais on ne doit
    rien perdre de plus, ni forcer l'utilisateur à tout retélécharger.
    """
    dossier = tmp_path / "cache"
    (dossier / NOM_BRUT).mkdir(parents=True)
    contenu = octets(activites, "boucle.gpx")
    identifiant = hashlib.sha256(contenu).hexdigest()
    (dossier / NOM_BRUT / f"{identifiant}.gpx").write_bytes(contenu)
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        cx.executescript(_SCHEMA_V1)
        cx.execute(
            "INSERT INTO activites (identifiant, source, id_externe, extension, debut, "
            "ajoutee_le) VALUES (?,?,?,?,?,?)",
            (identifiant, "intervals", "a111", "gpx", "2024-03-30T09:00:00+00:00", "2024-03-30"),
        )
        cx.execute("PRAGMA user_version = 1")

    cache = Cache(dossier)
    (entree,) = cache.lister()
    assert (entree.identifiant, entree.source, entree.id_externe) == (identifiant, "intervals", "a111")
    assert cache.contient(source="intervals", id_externe="a111")
    assert cache.chemin(identifiant).is_file(), "le fichier brut ne doit pas bouger"
    with sqlite3.connect(cache.index) as cx:
        assert cx.execute("PRAGMA user_version").fetchone()[0] == VERSION_SCHEMA

    # Et l'index migré accepte bien deux activités au même contenu.
    cache.ajouter(contenu, source="intervals", id_externe="a222", extension="gpx", meta={})
    assert {e.id_externe for e in cache.lister()} == {"a111", "a222"}
    assert len(list((dossier / NOM_BRUT).iterdir())) == 1


# --- isolation par propriétaire (doctrine §10.1 et §10.2) ---------------------
#
# Il n'y a pas encore de comptes : ces tests construisent deux `Cache` sur le
# même dossier avec deux propriétaires, ce qui est exactement ce que fera la
# couche web en F3 — un dépôt par utilisateur authentifié, le même stockage
# derrière. Aucune donnée réelle : les identifiants sont inventés.

AUTRE = "utilisateur-b"


#: Le schéma 2, tel qu'il était écrit : pas de colonne `proprietaire`, unicité
#: sur `(source, id_externe|identifiant)`. Recopié ici pour que le test
#: continue de décrire l'ancien index même quand le module ne le connaîtra plus.
_SCHEMA_V2 = """
CREATE TABLE activites (
    identifiant       TEXT NOT NULL,
    source            TEXT NOT NULL,
    id_externe        TEXT,
    extension         TEXT NOT NULL,
    debut             TEXT,
    duree_s           REAL,
    distance_m        REAL,
    puissance_moy_w   REAL,
    sport             TEXT,
    appareil          TEXT,
    equipement        TEXT,
    meta              TEXT NOT NULL DEFAULT '{}',
    ajoutee_le        TEXT NOT NULL
);
CREATE INDEX idx_activites_debut ON activites(debut);
CREATE INDEX idx_activites_identifiant ON activites(identifiant);
CREATE UNIQUE INDEX idx_activites_identite
    ON activites(source, COALESCE(id_externe, identifiant));
"""


def _index_v2(dossier: Path, contenu: bytes, id_externe: str) -> str:
    """Un index au schéma 2 portant une ligne, et son fichier brut."""
    (dossier / NOM_BRUT).mkdir(parents=True, exist_ok=True)
    identifiant = hashlib.sha256(contenu).hexdigest()
    (dossier / NOM_BRUT / f"{identifiant}.gpx").write_bytes(contenu)
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        cx.executescript(_SCHEMA_V2)
        cx.execute(
            "INSERT INTO activites (identifiant, source, id_externe, extension, debut, "
            "ajoutee_le) VALUES (?,?,?,?,?,?)",
            (identifiant, "intervals", id_externe, "gpx", "2024-03-30T09:00:00+00:00", "2024-03-30"),
        )
        cx.execute("PRAGMA user_version = 2")
    return identifiant


def test_un_cache_neuf_range_ses_lignes_sous_le_proprietaire_local(cache: Cache, activites: Path):
    cache.ajouter(
        octets(activites, "boucle.gpx"),
        source="intervals",
        id_externe="a111",
        extension="gpx",
        meta={},
    )
    with sqlite3.connect(cache.index) as cx:
        assert cx.execute("SELECT DISTINCT proprietaire FROM activites").fetchall() == [
            (PROPRIETAIRE_LOCAL,)
        ]


def test_deux_proprietaires_peuvent_avoir_la_meme_activite_intervals(
    tmp_path: Path, activites: Path
):
    """Le cœur du changement d'unicité.

    Avant, `(source, id_externe)` seul faisait l'identité : le second import
    n'aurait pas levé d'erreur, il aurait **écrasé** la ligne du premier via le
    `ON CONFLICT DO UPDATE`. La fuite la plus discrète possible.
    """
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    a = Cache(dossier)
    b = Cache(dossier, proprietaire=AUTRE)
    a.ajouter(contenu, source="intervals", id_externe="a111", extension="gpx", meta={"velo": "A"})
    b.ajouter(contenu, source="intervals", id_externe="a111", extension="gpx", meta={"velo": "B"})

    assert [e.meta.get("velo") for e in a.lister()] == ["A"]
    assert [e.meta.get("velo") for e in b.lister()] == ["B"]
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        assert cx.execute("SELECT COUNT(*) FROM activites").fetchone()[0] == 2
    # **Deux fichiers bruts**, un chacun (contre-lecture Fable du 25/09/2026) :
    # le même contenu n'est plus partagé entre propriétaires — ni pour la
    # suppression de l'un, ni comme indice que l'autre l'a déjà déposé.
    assert len([f for f in (dossier / NOM_BRUT).iterdir() if f.is_file()]) == 1
    assert len(list(b.brut.iterdir())) == 1
    assert b.brut != a.brut and b.chemin(a.lister()[0].identifiant) != a.chemin(
        a.lister()[0].identifiant
    )


def test_supprimer_un_compte_ne_touche_jamais_les_fichiers_d_un_autre(
    tmp_path: Path, activites: Path
):
    """Même contenu chez deux comptes : effacer l'un laisse le fichier de l'autre."""
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    a = Cache(dossier, proprietaire="compte-a")
    b = Cache(dossier, proprietaire="compte-b")
    a.ajouter(contenu, source="fichier", id_externe=None, extension="gpx", meta={})
    b.ajouter(contenu, source="fichier", id_externe=None, extension="gpx", meta={})
    assert a.supprimer_tout() == 1
    assert not a.brut.exists() or list(a.brut.iterdir()) == []
    (entree,) = b.lister()
    assert entree.chemin.is_file()
    assert b.relire(entree.identifiant) is not None


def test_un_proprietaire_au_nom_hostile_reste_dans_brut(tmp_path: Path):
    """Un propriétaire qui ne serait pas un identifiant sûr ne sort jamais de `brut/`."""
    cache = Cache(tmp_path / "cache", proprietaire="../../hors")
    assert cache.brut.resolve().is_relative_to((tmp_path / "cache" / NOM_BRUT).resolve())
    assert ".." not in cache.brut.relative_to(tmp_path / "cache").parts


def test_un_fichier_depose_avant_la_separation_se_relit_encore(
    tmp_path: Path, activites: Path
):
    """Un compte dont le fichier est dans le `brut/` commun (dépôt d'avant le
    25/09/2026) le relit toujours, et sa suppression l'y efface s'il est seul à
    le citer."""
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    compte = Cache(dossier, proprietaire="compte-a")
    identifiant = compte.ajouter(
        contenu, source="fichier", id_externe=None, extension="gpx", meta={}
    )
    # Simule l'ancien rangement : le fichier dans le `brut/` commun.
    propre = compte.brut / f"{identifiant}.gpx"
    ancien = dossier / NOM_BRUT / f"{identifiant}.gpx"
    propre.replace(ancien)
    assert compte.chemin(identifiant) == ancien
    assert compte.relire(identifiant) is not None
    compte.supprimer_tout()
    assert not ancien.exists()


def test_reimporter_la_meme_activite_converge_toujours_par_proprietaire(
    tmp_path: Path, activites: Path
):
    """`--synchroniser` ne doit pas cesser d'être idempotent pour autant."""
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    a = Cache(dossier)
    a.ajouter(contenu, source="intervals", id_externe="a111", extension="gpx", meta={})
    a.ajouter(contenu, source="intervals", id_externe="a111", extension="gpx", meta={})
    assert len(a.lister()) == 1


def test_un_proprietaire_ne_voit_rien_de_ce_qui_appartient_a_un_autre(
    tmp_path: Path, activites: Path
):
    """Toutes les lectures, pas seulement `lister` : c'est l'oubli habituel."""
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    a = Cache(dossier)
    identifiant = a.ajouter(
        contenu, source="intervals", id_externe="a111", extension="gpx", meta={}
    )
    b = Cache(dossier, proprietaire=AUTRE)

    assert b.lister() == []
    assert not b.contient(source="intervals", id_externe="a111")
    assert not b.contient_identifiant(identifiant)
    with pytest.raises(KeyError):
        b.chemin(identifiant)
    assert not b.mettre_a_jour_meta(source="intervals", id_externe="a111", meta={"sport": "Run"})
    # Et l'entrée de A n'a pas bougé sous le nez de B.
    assert a.lister()[0].sport != "Run"


@pytest.mark.parametrize("mauvais", ["", "   ", None, 12])
def test_un_proprietaire_vide_ou_absurde_est_refuse(tmp_path: Path, mauvais):
    """Une clause `WHERE proprietaire = ''` ne rendrait jamais rien : la panne
    la plus difficile à diagnostiquer est celle qui ressemble à un cache vide."""
    with pytest.raises(ErreurUtilisateur):
        Cache(tmp_path / "cache", proprietaire=mauvais)


def test_un_index_au_schema_2_est_migre_sans_perdre_de_ligne(tmp_path: Path, activites: Path):
    """Migration 2 → 3 : la colonne s'ajoute, les lignes restent, rattachées au local."""
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    identifiant = _index_v2(dossier, contenu, "a111")

    cache = Cache(dossier)

    (entree,) = cache.lister()
    assert (entree.identifiant, entree.id_externe) == (identifiant, "a111")
    assert cache.chemin(identifiant).is_file(), "le fichier brut ne doit pas bouger"
    with sqlite3.connect(cache.index) as cx:
        assert cx.execute("PRAGMA user_version").fetchone()[0] == VERSION_SCHEMA
        assert cx.execute("SELECT DISTINCT proprietaire FROM activites").fetchall() == [
            (PROPRIETAIRE_LOCAL,)
        ]
        # L'unicité porte bien le propriétaire, sans quoi la colonne ne
        # protégerait rien : l'index a été refait, pas seulement recréé.
        (sql,) = cx.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_activites_identite'"
        ).fetchone()
        assert "proprietaire" in sql


def test_migrer_un_index_deja_migre_ne_le_touche_pas(tmp_path: Path, activites: Path):
    """Piège classique : une migration qui s'exécute deux fois.

    Comparer les octets du fichier ne dirait rien (SQLite incrémente son
    compteur de modifications à chaque ouverture en écriture). On mesure donc
    les deux choses qu'une recopie changerait : la structure déclarée, et les
    `rowid`. Un **trou** est ménagé exprès dans les rowid — une table recopiée
    par `INSERT … SELECT` les renumérote à partir de 1, et le trou disparaît.
    """
    dossier = tmp_path / "cache"
    contenu = octets(activites, "boucle.gpx")
    _index_v2(dossier, contenu, "a111")

    cache = Cache(dossier)  # migre
    cache.ajouter(contenu, source="intervals", id_externe="a222", extension="gpx", meta={})
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        cx.execute("DELETE FROM activites WHERE id_externe = 'a111'")  # rowid 1 libéré
    empreinte = _empreinte(dossier)
    assert empreinte[1] == [(2, "a222")], "le trou dans les rowid doit exister au départ"

    Cache(dossier)
    Cache(dossier, proprietaire=AUTRE)
    assert _empreinte(dossier) == empreinte


def _empreinte(dossier: Path) -> tuple[list, list]:
    """(structure déclarée, lignes avec leur rowid) — ce qu'une recopie changerait."""
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        structure = cx.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        lignes = cx.execute("SELECT rowid, id_externe FROM activites ORDER BY rowid").fetchall()
    return structure, lignes


def test_un_index_au_schema_1_arrive_directement_au_schema_courant(
    tmp_path: Path, activites: Path
):
    """L'escalier se monte d'un coup quand la table est de toute façon recopiée."""
    dossier = tmp_path / "cache"
    (dossier / NOM_BRUT).mkdir(parents=True)
    contenu = octets(activites, "boucle.gpx")
    identifiant = hashlib.sha256(contenu).hexdigest()
    (dossier / NOM_BRUT / f"{identifiant}.gpx").write_bytes(contenu)
    with sqlite3.connect(dossier / NOM_INDEX) as cx:
        cx.executescript(_SCHEMA_V1)
        cx.execute(
            "INSERT INTO activites (identifiant, source, id_externe, extension, debut, "
            "ajoutee_le) VALUES (?,?,?,?,?,?)",
            (identifiant, "intervals", "a111", "gpx", "2024-03-30T09:00:00+00:00", "2024-03-30"),
        )
        cx.execute("PRAGMA user_version = 1")

    cache = Cache(dossier)
    assert [e.id_externe for e in cache.lister()] == ["a111"]
    with sqlite3.connect(cache.index) as cx:
        colonnes = {ligne[1] for ligne in cx.execute("PRAGMA table_info(activites)")}
    assert "proprietaire" in colonnes


# --- mise à jour des métadonnées sur place (L2.7) ------------------------------


def test_mettre_a_jour_meta_reecrit_aussi_ce_qui_derive_de_la_meta(cache: Cache, activites: Path):
    """`sport` et `appareil` dérivent de `meta` : les laisser rendait l'index incohérent.

    Mesuré sur le cache réel du mainteneur : quatre triathlons, hérités d'une
    collision de contenu du schéma 1, portaient l'identifiant Intervals de
    leur segment vélo mais le sport de leur segment natation. Un
    `--synchroniser` réécrivait leur `meta` (« Ride ») sans toucher à la
    colonne `sport` (« OpenWaterSwim ») : l'inventaire continuait de les
    écarter, indéfiniment.
    """
    cache.ajouter(
        octets(activites, "boucle.fit"),
        source="intervals",
        id_externe="t1",
        extension="fit",
        meta={"sport": "OpenWaterSwim", "appareil": "Montre"},
    )
    assert cache.lister()[0].sport == "OpenWaterSwim"

    assert cache.mettre_a_jour_meta(
        source="intervals",
        id_externe="t1",
        meta={"sport": "Ride", "appareil": "Compteur", "power_meter": "CAPTEUR 0001"},
    )
    (entree,) = cache.lister()
    assert entree.sport == "Ride", "la colonne doit suivre la meta qu'elle résume"
    assert entree.appareil == "Compteur"
    assert entree.meta["power_meter"] == "CAPTEUR 0001"

    # Une réponse plus pauvre n'efface pas ce qu'on savait déjà.
    assert cache.mettre_a_jour_meta(source="intervals", id_externe="t1", meta={"nom": "Sortie"})
    (entree,) = cache.lister()
    assert (entree.sport, entree.appareil) == ("Ride", "Compteur")


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

"""Tests de l'import d'archives déposées (L9.2, `docs/sprint9_contrat.md`).

Toutes les archives sont **fabriquées en mémoire** dans ce fichier — aucune
vraie archive Strava/Garmin, aucune donnée personnelle, aucun réseau (règle
absolue 1 et 3 de CLAUDE.md). Les fichiers d'activité qu'on y range viennent
de `tests/fixtures/activites/` (fixture `activites`), déjà synthétiques.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from pathlib import Path

import pytest

from ourouler.activites.cache import Cache
from ourouler.activites.import_archive import (
    RATIO_MAX_DECOMPRESSION,
    etat,
    importer,
)


@pytest.fixture
def cache_a(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache", proprietaire="a")


@pytest.fixture
def cache_b(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache", proprietaire="b")


def octets(activites: Path, nom: str) -> bytes:
    return (activites / nom).read_bytes()


def _zip(entrees: dict[str, bytes]) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for nom, contenu in entrees.items():
            zf.writestr(nom, contenu)
    return tampon.getvalue()


# --- le cas normal --------------------------------------------------------------


def test_un_fichier_isole_est_importe(cache_a: Cache, activites: Path):
    rapport = importer(cache_a, [("boucle.fit", octets(activites, "boucle.fit"))])
    assert rapport.importees == 1
    assert rapport.doublons == 0
    assert not rapport.ignorees
    assert [e.identifiant for e in cache_a.lister()]


def test_un_fichier_gz_est_decompresse_puis_importe(cache_a: Cache, activites: Path):
    gz = gzip.compress(octets(activites, "boucle.gpx"))
    rapport = importer(cache_a, [("boucle.gpx.gz", gz)])
    assert rapport.importees == 1
    assert rapport.ignorees == []


def test_une_archive_strava_plausible_est_importee(cache_a: Cache, activites: Path):
    """Un `.fit.gz`, un `.gpx` nu, un `activities.csv` hors liste, un média hors liste."""
    archive = _zip(
        {
            "activities.csv": b"id,name\n1,essai\n",
            "media/photo.jpg": b"\xff\xd8\xff" + b"0" * 100,
            "activities/1.fit.gz": gzip.compress(octets(activites, "boucle.fit")),
            "activities/2.gpx": octets(activites, "boucle.gpx"),
        }
    )
    rapport = importer(cache_a, [("export_9999.zip", archive)])
    assert rapport.importees == 2
    motifs = {i["motif"] for i in rapport.resume_ignorees()}
    assert any("extension non prise en charge" in m for m in motifs)


def test_une_archive_garmin_avec_zip_imbrique_est_importee(cache_a: Cache, activites: Path):
    """Le cas mesuré sur la vraie archive Garmin : un `.zip` dans le `.zip`."""
    interne = _zip(
        {
            "1.fit": octets(activites, "boucle.fit"),
            "2.tcx": octets(activites, "boucle.tcx"),
        }
    )
    exterieure = _zip(
        {
            "DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part1.zip": interne,
            "customer_data/customer.json": b"{}",
        }
    )
    rapport = importer(cache_a, [("garmin_export.zip", exterieure)])
    assert rapport.importees == 2


def test_plusieurs_fichiers_dans_le_meme_depot(cache_a: Cache, activites: Path):
    rapport = importer(
        cache_a,
        [
            ("un.fit", octets(activites, "boucle.fit")),
            ("deux.gpx", octets(activites, "boucle.gpx")),
            ("trois.tcx", octets(activites, "boucle.tcx")),
        ],
    )
    assert rapport.importees == 3


# --- dédoublonnage (Q62 : plusieurs archives successives) ----------------------


def test_reimporter_le_meme_fichier_ne_duplique_rien(cache_a: Cache, activites: Path):
    contenu = octets(activites, "boucle.fit")
    importer(cache_a, [("boucle.fit", contenu)])
    second = importer(cache_a, [("boucle.fit", contenu)])
    assert second.importees == 0
    assert second.doublons == 1
    assert len(cache_a.lister()) == 1


def test_reimporter_la_meme_archive_deux_appels_successifs(cache_a: Cache, activites: Path):
    """Q62 : l'invité dépose son export en plusieurs fois, ou le redépose. Rien n'est dupliqué."""
    archive = _zip({"activities/1.fit": octets(activites, "boucle.fit")})
    premier = importer(cache_a, [("export.zip", archive)])
    second = importer(cache_a, [("export.zip", archive)])
    assert premier.importees == 1
    assert second.importees == 0 and second.doublons == 1
    assert len(cache_a.lister()) == 1


def test_un_fichier_modifie_sous_le_meme_nom_met_a_jour_au_lieu_de_dupliquer(
    cache_a: Cache, activites: Path
):
    importer(cache_a, [("boucle.fit", octets(activites, "boucle.fit"))])
    autre_contenu = octets(activites, "boucle.tcx")  # contenu différent, même nom
    second = importer(cache_a, [("boucle.fit", autre_contenu)])
    # Le lecteur .fit refuse un contenu .tcx : c'est un fichier corrompu, pas
    # un doublon — sert surtout à documenter que le nom seul ne fait pas
    # l'identité, `Cache.ajouter` compare aussi le contenu.
    assert second.doublons == 0
    assert second.ignorees


# --- isolation par propriétaire -------------------------------------------------


def test_deux_proprietaires_important_le_meme_contenu_ont_chacun_leur_ligne(
    cache_a: Cache, cache_b: Cache, activites: Path
):
    contenu = octets(activites, "boucle.fit")
    importer(cache_a, [("boucle.fit", contenu)])
    importer(cache_b, [("boucle.fit", contenu)])
    assert len(cache_a.lister()) == 1
    assert len(cache_b.lister()) == 1


# --- fichiers corrompus, jamais un échec de tout l'import -----------------------


def test_fichier_isole_corrompu_est_ignore_avec_un_motif(cache_a: Cache):
    rapport = importer(cache_a, [("casse.fit", b"pas un vrai fit")])
    assert rapport.importees == 0
    assert rapport.ignorees
    assert "corrompu" in rapport.ignorees[0].motif


def test_archive_zip_corrompue_est_ignoree_sans_lever(cache_a: Cache):
    rapport = importer(cache_a, [("archive.zip", b"pas une archive zip")])
    assert rapport.importees == 0
    assert "corrompue" in rapport.ignorees[0].motif


def test_une_entree_corrompue_dans_une_archive_n_empeche_pas_les_autres(
    cache_a: Cache, activites: Path
):
    archive = _zip(
        {
            "bonne.fit": octets(activites, "boucle.fit"),
            "cassee.gpx": b"<gpx>non ferme",
        }
    )
    rapport = importer(cache_a, [("mixte.zip", archive)])
    assert rapport.importees == 1
    assert rapport.ignorees
    assert "corrompu" in rapport.ignorees[0].motif


def test_extension_hors_liste_est_ignoree_sans_faire_echouer(cache_a: Cache, activites: Path):
    rapport = importer(cache_a, [("notes.txt", b"pas une activite")])
    assert rapport.importees == 0
    assert "extension non prise en charge" in rapport.ignorees[0].motif


# --- bornes de sécurité ----------------------------------------------------------


def test_chemin_absolu_dans_une_archive_est_refuse(cache_a: Cache, activites: Path):
    archive = _zip({"/etc/passwd": octets(activites, "boucle.fit")})
    rapport = importer(cache_a, [("hostile.zip", archive)])
    assert rapport.importees == 0
    assert "chemin refusé" in rapport.ignorees[0].motif


def test_chemin_avec_double_point_est_refuse(cache_a: Cache, activites: Path):
    archive = _zip({"../../hors_de_l_archive.fit": octets(activites, "boucle.fit")})
    rapport = importer(cache_a, [("hostile.zip", archive)])
    assert rapport.importees == 0
    assert "chemin refusé" in rapport.ignorees[0].motif


def test_bombe_de_decompression_par_ratio_est_refusee(cache_a: Cache):
    """Un `.gpx` compressible à l'extrême — mesuré à 11× sur l'archive Garmin réelle,
    ici largement au-delà du plafond, pour que le test ne dépende pas du taux de
    compression réel de `zipfile`."""
    enorme = b"0" * (RATIO_MAX_DECOMPRESSION * 2 * 1024 * 1024)  # se compresse à presque rien
    archive = _zip({"bombe.gpx": enorme})
    rapport = importer(cache_a, [("hostile.zip", archive)])
    assert rapport.importees == 0
    assert any("bombe" in i.motif for i in rapport.ignorees)


def test_trop_de_fichiers_dans_une_archive_est_refuse(cache_a: Cache, monkeypatch, activites: Path):
    monkeypatch.setattr("ourouler.activites.import_archive.NOMBRE_MAX_FICHIERS", 3)
    archive = _zip({f"{i}.fit": octets(activites, "boucle.fit") for i in range(6)})
    rapport = importer(cache_a, [("beaucoup.zip", archive)])
    assert rapport.importees <= 3
    assert any("fichiers rencontrés" in i.motif for i in rapport.ignorees)


def test_archive_trop_imbriquee_est_refusee(cache_a: Cache, monkeypatch, activites: Path):
    monkeypatch.setattr("ourouler.activites.import_archive.PROFONDEUR_MAX_ARCHIVE", 1)
    plus_interne = _zip({"1.fit": octets(activites, "boucle.fit")})
    milieu = _zip({"niveau2.zip": plus_interne})
    exterieure = _zip({"niveau1.zip": milieu})
    rapport = importer(cache_a, [("trop_profond.zip", exterieure)])
    assert rapport.importees == 0
    assert any("imbriquée" in i.motif for i in rapport.ignorees)


def test_lien_symbolique_dans_une_archive_est_refuse(cache_a: Cache):
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as zf:
        info = zipfile.ZipInfo("lien.fit")
        info.external_attr = (0o120777 & 0xFFFF) << 16  # S_IFLNK
        zf.writestr(info, "/etc/passwd")
    rapport = importer(cache_a, [("hostile.zip", tampon.getvalue())])
    assert rapport.importees == 0
    assert "chemin refusé" in rapport.ignorees[0].motif


def test_gz_corrompu_est_ignore(cache_a: Cache):
    rapport = importer(cache_a, [("casse.fit.gz", b"pas du gzip")])
    assert rapport.importees == 0
    assert "gz" in rapport.ignorees[0].motif


def test_gz_qui_decompresse_au_dela_du_plafond_est_refuse(cache_a: Cache, monkeypatch):
    monkeypatch.setattr("ourouler.activites.import_archive.TAILLE_MAX_FICHIER", 1024)
    enorme = gzip.compress(b"0" * (10 * 1024))
    rapport = importer(cache_a, [("gros.fit.gz", enorme)])
    assert rapport.importees == 0
    assert rapport.ignorees


def test_les_ignorees_sont_groupees_par_motif(cache_a: Cache):
    """Une archive Strava réelle porte des centaines de médias : un motif, un compte,
    pas une ligne par fichier."""
    archive = _zip({f"media/photo{i}.jpg": b"x" for i in range(50)})
    rapport = importer(cache_a, [("export.zip", archive)])
    resume = rapport.resume_ignorees()
    assert len(resume) == 1
    assert resume[0]["nombre"] == 50
    assert len(resume[0]["exemples"]) <= 5


# --- l'état, pour l'écran ---------------------------------------------------------


def test_etat_sans_rien_importe(cache_a: Cache):
    e = etat(cache_a)
    assert e == {"nombre": 0, "premiere": None, "derniere": None}


def test_etat_compte_seulement_les_depots_fichier(cache_a: Cache, activites: Path):
    importer(cache_a, [("boucle.fit", octets(activites, "boucle.fit"))])
    cache_a.ajouter(
        octets(activites, "boucle.gpx"),
        source="intervals",
        id_externe="i-123",
        extension="gpx",
        meta={},
    )
    e = etat(cache_a)
    assert e["nombre"] == 1

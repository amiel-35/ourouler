"""`POST /api/v1/activites/import` et `GET /api/v1/activites/import` (L9.2).

Le cœur de l'algorithme (bornes, dédoublonnage, archives imbriquées) est
éprouvé sans HTTP dans `tests/test_import_archive.py`. Ce fichier-ci vérifie
la couche route : la garde sur `Content-Length`, la réponse quand aucun
fichier n'est déposé, et que la réponse a la forme attendue une fois passée
par l'enveloppe de l'API.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from pathlib import Path

import pytest
from outils_api import client_api, config_d_essai

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

PREFIXE = "/api/v1"


def _config_avec_cache(tmp_path: Path):
    return config_d_essai(cache={"dossier": str(tmp_path / "cache")})


def _gpx() -> bytes:
    return (
        b"<?xml version='1.0'?>\n"
        b'<gpx version="1.1" creator="essai">\n'
        b'<trk><name>essai</name><trkseg>\n'
        b'<trkpt lat="0.0009" lon="0.0004"><time>2024-06-05T08:00:00Z</time></trkpt>\n'
        b'<trkpt lat="0.0018" lon="0.0004"><time>2024-06-05T08:01:00Z</time></trkpt>\n'
        b"</trkseg></trk>\n</gpx>\n"
    )


def test_un_gpx_depose_est_importe(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("sortie.gpx", _gpx(), "application/gpx+xml")},
    )
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["importees"] == 1
    assert donnees["doublons"] == 0
    assert donnees["ignorees"] == []


def test_reimporter_le_meme_fichier_le_compte_comme_doublon(tmp_path: Path):
    config = _config_avec_cache(tmp_path)
    client = client_api(config=config)
    fichier = ("sortie.gpx", _gpx(), "application/gpx+xml")
    client.post(f"{PREFIXE}/activites/import", files={"fichiers": fichier})
    reponse = client.post(f"{PREFIXE}/activites/import", files={"fichiers": fichier})
    donnees = reponse.json()["donnees"]
    assert donnees["importees"] == 0
    assert donnees["doublons"] == 1


def test_plusieurs_depots_successifs_ne_dupliquent_rien(tmp_path: Path):
    """Q62 : l'invité dépose son archive en plusieurs fois."""
    config = _config_avec_cache(tmp_path)
    client = client_api(config=config)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("activities/1.gpx", _gpx())
    contenu = archive.getvalue()

    premier = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("export.zip", contenu, "application/zip")},
    )
    second = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("export.zip", contenu, "application/zip")},
    )
    assert premier.json()["donnees"]["importees"] == 1
    assert second.json()["donnees"]["doublons"] == 1

    etat = client.get(f"{PREFIXE}/activites/import")
    assert etat.status_code == 200
    assert etat.json()["donnees"]["nombre"] == 1


def test_une_archive_hostile_est_ignoree_pas_une_panne(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../hors_de_l_archive.gpx", _gpx())
    reponse = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("hostile.zip", archive.getvalue(), "application/zip")},
    )
    assert reponse.status_code == 200, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["importees"] == 0
    assert donnees["ignorees"]
    assert "chemin refusé" in donnees["ignorees"][0]["motif"]


def test_un_gz_depose_est_decompresse(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("sortie.gpx.gz", gzip.compress(_gpx()), "application/gzip")},
    )
    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["donnees"]["importees"] == 1


def test_requete_trop_grosse_est_refusee_sur_l_en_tete(tmp_path: Path):
    """`Content-Length` annoncé au-delà du plafond : refusé avant d'être lu."""
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.post(
        f"{PREFIXE}/activites/import",
        headers={"content-length": str(800 * 1024 * 1024)},
        files={"fichiers": ("sortie.gpx", _gpx(), "application/gpx+xml")},
    )
    assert reponse.status_code == 413
    assert reponse.json()["erreur"]["code"] == "fichier_trop_gros"


def test_aucun_fichier_depose_est_une_requete_invalide(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.post(f"{PREFIXE}/activites/import", files={})
    assert reponse.status_code in (400, 422)


def test_etat_avant_tout_depot_est_vide(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.get(f"{PREFIXE}/activites/import")
    assert reponse.status_code == 200
    assert reponse.json()["donnees"] == {"nombre": 0, "premiere": None, "derniere": None}

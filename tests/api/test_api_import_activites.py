"""`POST/GET /api/v1/activites/import` et `GET .../import/{id}` (L9.2).

Le cœur de l'algorithme (bornes, dédoublonnage, archives imbriquées) est
éprouvé sans HTTP dans `tests/test_import_archive.py`. Ce fichier-ci vérifie
la couche route et la tâche de fond : le 202 immédiat, l'avancement via
`GET .../import/{id}`, le refus lisible d'un second import pendant qu'un
premier tourne, et la garde sur `Content-Length`.
"""

from __future__ import annotations

import gzip
import io
import time
import zipfile
from pathlib import Path

from outils_api import client_api, config_d_essai

from ourouler.api import taches_fond

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


def _attendre(client, id_job: str, delai_max_s: float = 5.0) -> dict:
    debut = time.monotonic()
    while True:
        reponse = client.get(f"{PREFIXE}/activites/import/{id_job}")
        assert reponse.status_code == 200, reponse.text
        donnees = reponse.json()["donnees"]
        if donnees["statut"] != "en_cours":
            return donnees
        if time.monotonic() - debut > delai_max_s:
            raise AssertionError(f"import {id_job} toujours en_cours après {delai_max_s} s")
        time.sleep(0.02)


def _deposer_et_attendre(client, fichier: tuple) -> dict:
    reponse = client.post(f"{PREFIXE}/activites/import", files={"fichiers": fichier})
    assert reponse.status_code == 202, reponse.text
    return _attendre(client, reponse.json()["donnees"]["id"])


def test_le_depot_rend_202_et_un_identifiant_tout_de_suite(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.post(
        f"{PREFIXE}/activites/import",
        files={"fichiers": ("sortie.gpx", _gpx(), "application/gpx+xml")},
    )
    assert reponse.status_code == 202, reponse.text
    donnees = reponse.json()["donnees"]
    assert donnees["statut"] in ("en_cours", "fini")  # peut déjà être fini, très rapide
    assert donnees["id"]
    assert donnees["rapport"] is None or donnees["statut"] == "fini"


def test_un_gpx_depose_est_importe(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    fini = _deposer_et_attendre(client, ("sortie.gpx", _gpx(), "application/gpx+xml"))
    assert fini["statut"] == "fini"
    assert fini["rapport"] == {"importees": 1, "doublons": 0, "ignorees": []}
    assert fini["traites"] == fini["total"] == 1


def test_reimporter_le_meme_fichier_le_compte_comme_doublon(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    fichier = ("sortie.gpx", _gpx(), "application/gpx+xml")
    _deposer_et_attendre(client, fichier)
    fini = _deposer_et_attendre(client, fichier)
    assert fini["rapport"]["importees"] == 0
    assert fini["rapport"]["doublons"] == 1


def test_plusieurs_depots_successifs_ne_dupliquent_rien(tmp_path: Path):
    """Q62 : l'invité dépose son archive en plusieurs fois."""
    client = client_api(config=_config_avec_cache(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("activities/1.gpx", _gpx())
    contenu = archive.getvalue()

    premier = _deposer_et_attendre(client, ("export.zip", contenu, "application/zip"))
    second = _deposer_et_attendre(client, ("export.zip", contenu, "application/zip"))
    assert premier["rapport"]["importees"] == 1
    assert second["rapport"]["doublons"] == 1

    etat = client.get(f"{PREFIXE}/activites/import")
    assert etat.status_code == 200
    assert etat.json()["donnees"]["nombre"] == 1


def test_une_archive_hostile_est_ignoree_pas_une_panne(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../../hors_de_l_archive.gpx", _gpx())
    fini = _deposer_et_attendre(client, ("hostile.zip", archive.getvalue(), "application/zip"))
    assert fini["statut"] == "fini"
    assert fini["rapport"]["importees"] == 0
    assert fini["rapport"]["ignorees"]
    assert "chemin refusé" in fini["rapport"]["ignorees"][0]["motif"]


def test_un_gz_depose_est_decompresse(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    fini = _deposer_et_attendre(
        client, ("sortie.gpx.gz", gzip.compress(_gpx()), "application/gzip")
    )
    assert fini["rapport"]["importees"] == 1


def test_un_import_qui_leve_est_marque_echoue_pas_perdu(tmp_path: Path, monkeypatch):
    """Une panne inattendue du cœur (pas une entrée hostile — le cache lui-même)
    ne doit pas laisser le job muet : `statut` passe à `echoue`, avec un message."""

    def _casse(*args, **kwargs):
        raise RuntimeError("panne fabriquée pour le test")

    monkeypatch.setattr("ourouler.api.imports_fond.importer", _casse)
    client = client_api(config=_config_avec_cache(tmp_path))
    fini = _deposer_et_attendre(client, ("sortie.gpx", _gpx(), "application/gpx+xml"))
    assert fini["statut"] == "echoue"
    assert fini["code_erreur"] == "erreur_interne"
    assert "panne fabriquée" not in fini["erreur"], "le texte interne ne sort pas"


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


def test_job_inconnu_rend_fichier_introuvable(tmp_path: Path):
    client = client_api(config=_config_avec_cache(tmp_path))
    reponse = client.get(f"{PREFIXE}/activites/import/inconnu")
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"


def test_un_second_import_pendant_le_premier_est_refuse_lisiblement(tmp_path: Path):
    """Un seul import à la fois, pour le serveur entier — le verrou est tenu ici
    directement, sans dépendre du minutage réel d'un import (trop rapide sur un
    petit fichier pour être observé de façon fiable autrement)."""
    client = client_api(config=_config_avec_cache(tmp_path))
    assert taches_fond.VERROU.acquire(blocking=False), "verrou déjà tenu avant le test"
    try:
        reponse = client.post(
            f"{PREFIXE}/activites/import",
            files={"fichiers": ("sortie.gpx", _gpx(), "application/gpx+xml")},
        )
        assert reponse.status_code == 409, reponse.text
        assert reponse.json()["erreur"]["code"] == "import_deja_en_cours"
    finally:
        taches_fond.VERROU.release()

    # Le verrou relâché, un import suivant fonctionne normalement.
    fini = _deposer_et_attendre(client, ("sortie.gpx", _gpx(), "application/gpx+xml"))
    assert fini["statut"] == "fini"

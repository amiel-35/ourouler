"""`api/imports_fond.py` — le registre de tâches, sans HTTP (L9.2 suite).

Le comportement contre le service réel (202, `GET .../import/{id}`, le
refus d'un second import) est éprouvé par `tests/api/test_api_import_activites.py`
et `tests/api/test_api_isolation_proprietaire.py`. Ce fichier-ci isole le
registre lui-même : un seul verrou pour tout le module, donc les tests qui
le tiennent le relâchent toujours dans un `finally`, pour ne jamais laisser
un test raté bloquer les suivants.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ourouler.activites.cache import Cache
from ourouler.api import imports_fond, taches_fond


def _fichier(tmp_path: Path, nom: str, contenu: bytes) -> Path:
    chemin = tmp_path / nom
    chemin.write_bytes(contenu)
    return chemin


def _gpx() -> bytes:
    return (
        b"<?xml version='1.0'?>\n"
        b'<gpx version="1.1" creator="essai">\n'
        b"<trk><name>essai</name><trkseg>\n"
        b'<trkpt lat="0.0009" lon="0.0004"><time>2024-06-05T08:00:00Z</time></trkpt>\n'
        b'<trkpt lat="0.0018" lon="0.0004"><time>2024-06-05T08:01:00Z</time></trkpt>\n'
        b"</trkseg></trk>\n</gpx>\n"
    )


def _attendre(job: imports_fond.Job, delai_max_s: float = 5.0) -> None:
    debut = time.monotonic()
    while job.statut == taches_fond.STATUT_EN_COURS:
        if time.monotonic() - debut > delai_max_s:
            raise AssertionError("job toujours en_cours")
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _verrou_libre():
    """Contre-épreuve avant chaque test : un test précédent qui aurait mal
    relâché le verrou rendrait tous les suivants faussement rouges."""
    assert taches_fond.VERROU.acquire(blocking=False), "le verrou n'était pas libre au départ"
    taches_fond.VERROU.release()
    yield


def test_lancer_puis_trouver_par_le_bon_proprietaire(tmp_path: Path):
    cache = Cache(tmp_path / "cache", proprietaire="a")
    depots = [("sortie.gpx", _fichier(tmp_path, "sortie.gpx", _gpx()))]
    job = imports_fond.lancer(cache, "a", depots)
    _attendre(job)
    assert job.statut == taches_fond.STATUT_FINI
    assert job.rapport is not None and job.rapport.importees == 1

    retrouve = imports_fond.trouver("a", job.id)
    assert retrouve is job


def test_trouver_ne_rend_rien_a_un_autre_proprietaire(tmp_path: Path):
    cache = Cache(tmp_path / "cache", proprietaire="a")
    depots = [("sortie.gpx", _fichier(tmp_path, "sortie.gpx", _gpx()))]
    job = imports_fond.lancer(cache, "a", depots)
    _attendre(job)
    assert imports_fond.trouver("b", job.id) is None


def test_trouver_un_identifiant_inconnu_rend_none():
    assert imports_fond.trouver("a", "jamais-lance") is None


def test_un_second_lancement_pendant_le_premier_leve():
    assert taches_fond.VERROU.acquire(blocking=False)
    try:
        with pytest.raises(imports_fond.ErreurImportEnCours):
            imports_fond.lancer(Cache.__new__(Cache), "a", [])
    finally:
        taches_fond.VERROU.release()


def test_le_verrou_est_relache_meme_si_l_import_leve(tmp_path: Path, monkeypatch):
    def _casse(*args, **kwargs):
        raise RuntimeError("panne fabriquée")

    monkeypatch.setattr("ourouler.api.imports_fond.importer", _casse)
    cache = Cache(tmp_path / "cache", proprietaire="a")
    depots = [("sortie.gpx", _fichier(tmp_path, "sortie.gpx", _gpx()))]
    job = imports_fond.lancer(cache, "a", depots)
    _attendre(job)
    assert job.statut == taches_fond.STATUT_ECHOUE
    # Contre-lecture Fable du 25/09 : le texte interne de l'exception ne sort
    # plus ; un code et une phrase générique, la trace au journal.
    assert job.code_erreur == "erreur_interne"
    assert "panne fabriquée" not in job.erreur
    # Le verrou a bien été relâché : un import suivant peut partir aussitôt.
    assert taches_fond.VERROU.acquire(blocking=False)
    taches_fond.VERROU.release()


def test_les_fichiers_temporaires_sont_effaces_apres_l_import(tmp_path: Path):
    chemin = _fichier(tmp_path, "sortie.gpx", _gpx())
    cache = Cache(tmp_path / "cache", proprietaire="a")
    job = imports_fond.lancer(cache, "a", [("sortie.gpx", chemin)])
    _attendre(job)
    assert not chemin.exists()


def test_le_progres_avance_pendant_l_import(tmp_path: Path):
    cache = Cache(tmp_path / "cache", proprietaire="a")
    depots = [("sortie.gpx", _fichier(tmp_path, "sortie.gpx", _gpx()))]
    job = imports_fond.lancer(cache, "a", depots)
    _attendre(job)
    assert job.traites == job.total == 1


def test_json_rend_une_forme_stable(tmp_path: Path):
    cache = Cache(tmp_path / "cache", proprietaire="a")
    depots = [("sortie.gpx", _fichier(tmp_path, "sortie.gpx", _gpx()))]
    job = imports_fond.lancer(cache, "a", depots)
    _attendre(job)
    charge = job.json()
    assert set(charge) == {"id", "statut", "traites", "total", "rapport", "erreur", "code_erreur"}
    assert charge["erreur"] is None
    assert charge["code_erreur"] is None
    assert charge["rapport"] == {
        "importees": 1,
        "doublons": 0,
        "ignorees": [],
        "fichiers_conserves": True,
        "derivees": 0,
        "rafraichies": 0,
        "sans_vent": 0,
        "restaurees": 0,
    }


# --- contre-lecture Fable du 25/09/2026 ---------------------------------------


def test_un_fil_qui_ne_demarre_pas_rend_le_verrou(monkeypatch):
    """`Thread.start()` qui lève (plus de fils, plus de mémoire) ne doit pas
    laisser le verrou pris pour toujours."""
    import threading

    from ourouler.api import taches_fond

    def refuser(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", refuser)
    with pytest.raises(RuntimeError):
        taches_fond.lancer("a", taches_fond.NATURE_IMPORT, lambda job: None)
    monkeypatch.undo()
    assert taches_fond.VERROU.acquire(blocking=False), "le verrou est resté pris"
    taches_fond.VERROU.release()


def test_l_erreur_interne_part_au_journal_pas_dans_la_reponse(tmp_path: Path, monkeypatch, caplog):
    def _casse(*args, **kwargs):
        raise RuntimeError("/srv/secret/chemin interne")

    monkeypatch.setattr("ourouler.api.imports_fond.importer", _casse)
    cache = Cache(tmp_path / "cache", proprietaire="a")
    with caplog.at_level("ERROR", logger="ourouler.api.taches_fond"):
        job = imports_fond.lancer(cache, "a", [])
        _attendre(job)
    assert "/srv/secret" not in job.erreur
    assert job.code_erreur == "erreur_interne"
    assert any("/srv/secret" in (r.exc_text or "") for r in caplog.records)


def test_balayer_les_copies_orphelines_et_elles_seules(tmp_path: Path):
    import os

    vieille = tmp_path / f"{imports_fond.PREFIXE_TEMPORAIRE}vieille.bin"
    recente = tmp_path / f"{imports_fond.PREFIXE_TEMPORAIRE}recente.bin"
    etrangere = tmp_path / "autre-chose.bin"
    for chemin in (vieille, recente, etrangere):
        chemin.write_bytes(b"x")
    maintenant = 10_000_000.0
    os.utime(vieille, (maintenant - 7200, maintenant - 7200))
    os.utime(recente, (maintenant - 60, maintenant - 60))
    os.utime(etrangere, (maintenant - 7200, maintenant - 7200))
    assert imports_fond.balayer_temporaires_orphelins(tmp_path, maintenant=maintenant) == 1
    assert not vieille.exists()
    assert recente.exists() and etrangere.exists()

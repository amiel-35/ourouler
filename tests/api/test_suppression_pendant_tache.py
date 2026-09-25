"""`DELETE /moi` pendant un import ou une calibration (contre-lecture Fable du 25/09/2026).

La preuve Fable : un compte supprimé à mi-import retrouvait, une fois
l'import fini, cinq lignes et cinq fichiers bruts — l'import continuait
d'écrire pour un compte qui n'existait plus. Ici, l'import est ralenti (un
temps d'arrêt par fichier, rien d'autre ne change) pour que la suppression
tombe au milieu, puis on vérifie qu'il ne reste **rien**, même après que
l'import aurait dû finir.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from fastapi.testclient import TestClient  # noqa: E402
from outils_api import config_d_essai  # noqa: E402

from ourouler.activites import import_archive  # noqa: E402
from ourouler.activites.cache import Cache  # noqa: E402
from ourouler.api import taches_fond  # noqa: E402
from ourouler.api.application import creer_application  # noqa: E402
from ourouler.api.proprietaire import Proprietaire  # noqa: E402
from ourouler.api.session import MODE_HEBERGE  # noqa: E402

A = "essai-suppr-a"
B = "essai-suppr-b"
N_FICHIERS = 30


@dataclass(frozen=True)
class SessionParEnTete:
    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        valeur = getattr(requete, "headers", {}).get("x-compte-essai")
        return Proprietaire(valeur) if valeur else None


def _gpx(rang: int) -> bytes:
    heure = 6 + rang // 60
    minute = rang % 60
    return (
        "<?xml version='1.0'?>\n<gpx version=\"1.1\" creator=\"essai\"><trk><trkseg>"
        f'<trkpt lat="0.0009" lon="0.0004"><time>2024-06-05T{heure:02d}:{minute:02d}:00Z</time></trkpt>'
        f'<trkpt lat="0.0018" lon="0.0004"><time>2024-06-05T{heure:02d}:{minute:02d}:30Z</time></trkpt>'
        "</trkseg></trk></gpx>\n"
    ).encode()


@pytest.fixture
def import_lent(monkeypatch):
    """Chaque fichier traité attend 50 ms : 30 fichiers, 1,5 s d'import."""
    avancer = import_archive._Etat.avancer

    def lent(self):
        time.sleep(0.05)
        avancer(self)

    monkeypatch.setattr(import_archive._Etat, "avancer", lent)


def _client(tmp_path: Path) -> TestClient:
    application = creer_application(
        config=config_d_essai(cache={"dossier": str(tmp_path / "cache")}),
        dossier_donnees=tmp_path / "donnees",
        session=SessionParEnTete(),
    )
    return TestClient(application, raise_server_exceptions=False)


def test_supprimer_le_compte_a_mi_import_ne_laisse_rien_revenir(tmp_path: Path, import_lent):
    client = _client(tmp_path)
    h = {"x-compte-essai": A}
    fichiers = [("fichiers", (f"s{i}.gpx", _gpx(i), "application/gpx+xml")) for i in range(N_FICHIERS)]
    lance = client.post("/api/v1/activites/import", headers=h, files=fichiers)
    assert lance.status_code == 202, lance.text
    id_job = lance.json()["donnees"]["id"]

    # Au milieu de l'import : quelques fichiers déjà écrits, pas tous.
    debut = time.monotonic()
    while client.get(f"/api/v1/activites/import/{id_job}", headers=h).json()["donnees"][
        "traites"
    ] < 5:
        assert time.monotonic() - debut < 5
        time.sleep(0.01)
    cache = Cache(tmp_path / "cache", proprietaire=A)
    assert 0 < len(cache.lister()) < N_FICHIERS, "la suppression doit tomber à mi-import"

    suppression = client.delete("/api/v1/moi", headers=h)
    assert suppression.status_code == 200, suppression.text

    # L'import a été arrêté, et **rien** ne revient — même une seconde plus
    # tard, bien après que l'import non annulé aurait fini.
    job = taches_fond.trouver(A, id_job)
    assert job is not None and job.statut == taches_fond.STATUT_ECHOUE
    assert "annulée" in (job.erreur or "")
    time.sleep(1.0)
    assert Cache(tmp_path / "cache", proprietaire=A).lister() == []
    assert list((tmp_path / "cache" / "brut").rglob("*.gpx")) == []


def test_un_compte_en_cours_d_effacement_ne_relance_rien(tmp_path: Path):
    """Pendant l'effacement, une tâche lancée pour ce compte est refusée."""
    with taches_fond.suspendre(A), pytest.raises(taches_fond.ErreurTacheEnCours):
        taches_fond.lancer(A, taches_fond.NATURE_IMPORT, lambda job: None)
    # Un autre compte, lui, n'est pas concerné.
    with taches_fond.suspendre(A):
        job = taches_fond.lancer(B, taches_fond.NATURE_IMPORT, lambda job: None)
    assert job._termine.wait(5)


def test_une_tache_qui_ne_s_arrete_pas_empeche_l_effacement(tmp_path: Path, monkeypatch):
    """Si la tâche ne rend pas la main à temps, rien n'est effacé et le refus le dit."""
    relache = __import__("threading").Event()
    job = taches_fond.lancer(A, taches_fond.NATURE_IMPORT, lambda job: relache.wait(5))
    try:
        monkeypatch.setattr(
            taches_fond,
            "annuler_et_attendre",
            lambda proprietaire, delai_s=120.0: False,
        )
        client = _client(tmp_path)
        reponse = client.delete("/api/v1/moi", headers={"x-compte-essai": A})
        assert reponse.status_code == 409, reponse.text
        assert reponse.json()["erreur"]["code"] == "tache_lourde_en_cours"
    finally:
        relache.set()
        assert job._termine.wait(5)

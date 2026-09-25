"""`api/garde_avant_corps.py` et le quota d'imports (contre-lecture Fable du 25/09/2026).

Un import refusé (pas de session, serveur occupé, quota épuisé) doit l'être
**avant** que le serveur ait lu un octet du corps — jusqu'à 750 Mo. La preuve
se fait en ASGI brut : un `receive()` qui compte ses appels, et l'application
réelle (`creer_application`) derrière.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from fastapi.testclient import TestClient  # noqa: E402
from outils_api import config_d_essai  # noqa: E402

from ourouler.api import taches_fond  # noqa: E402
from ourouler.api.application import creer_application  # noqa: E402
from ourouler.api.proprietaire import Proprietaire  # noqa: E402
from ourouler.api.quotas import Quotas  # noqa: E402
from ourouler.api.session import MODE_HEBERGE  # noqa: E402

CHEMIN = "/api/v1/activites/import"


@dataclass(frozen=True)
class SessionParEnTete:
    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        valeur = getattr(requete, "headers", {}).get("x-compte-essai")
        return Proprietaire(valeur) if valeur else None


def _application(tmp_path: Path, **options):
    return creer_application(
        config=config_d_essai(cache={"dossier": str(tmp_path / "cache")}),
        dossier_donnees=tmp_path / "donnees",
        session=SessionParEnTete(),
        **options,
    )


def _appeler_sans_lire(application, entetes: list[tuple[bytes, bytes]]) -> tuple[int, dict, int]:
    """(statut, corps JSON, nombre de `receive()` appelés) pour un POST d'import."""
    lus = 0

    async def receive() -> dict:
        # Un vrai début de multipart, puis un fichier qui ne finit jamais :
        # sans lui, le parseur refuserait dès le premier morceau (400) et le
        # test ne mesurerait pas la borne.
        nonlocal lus
        lus += 1
        if lus == 1:
            entete = (
                b"--x\r\nContent-Disposition: form-data; name=\"fichiers\"; "
                b"filename=\"a.gpx\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            )
            return {"type": "http.request", "body": entete, "more_body": True}
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    envoyes: list[dict] = []

    async def send(message: dict) -> None:
        envoyes.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": CHEMIN,
        "raw_path": CHEMIN.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x"), *entetes],
        "client": ("127.0.0.1", 1),
        "server": ("api.test", 80),
    }
    asyncio.run(application(scope, receive, send))
    statut = next(m["status"] for m in envoyes if m["type"] == "http.response.start")
    corps = b"".join(m.get("body", b"") for m in envoyes if m["type"] == "http.response.body")
    return statut, json.loads(corps), lus


def test_sans_session_refus_avant_de_lire_le_corps(tmp_path: Path):
    statut, corps, lus = _appeler_sans_lire(_application(tmp_path), [])
    assert statut == 401
    assert corps["erreur"]["code"] == "session_absente"
    assert lus == 0, "le corps a été lu avant de refuser une requête sans session"


def test_serveur_occupe_refus_avant_de_lire_le_corps(tmp_path: Path):
    application = _application(tmp_path)
    assert taches_fond.VERROU.acquire(blocking=False)
    try:
        statut, corps, lus = _appeler_sans_lire(application, [(b"x-compte-essai", b"essai-a")])
    finally:
        taches_fond.VERROU.release()
    assert statut == 409
    assert corps["erreur"]["code"] == "import_deja_en_cours"
    assert lus == 0, "le corps a été lu avant de refuser pendant une tâche lourde"


def test_quota_epuise_refus_avant_de_lire_le_corps(tmp_path: Path):
    application = _application(tmp_path, quotas_import=Quotas(plafond=0, libelle="imports"))
    statut, corps, lus = _appeler_sans_lire(application, [(b"x-compte-essai", b"essai-a")])
    assert statut == 429
    assert corps["erreur"]["code"] == "quota_atteint"
    assert lus == 0


def _gpx(minute: int) -> bytes:
    return (
        "<?xml version='1.0'?>\n<gpx version=\"1.1\" creator=\"essai\"><trk><trkseg>"
        f'<trkpt lat="0.0009" lon="0.0004"><time>2024-06-05T08:{minute:02d}:00Z</time></trkpt>'
        f'<trkpt lat="0.0018" lon="0.0004"><time>2024-06-05T08:{minute + 1:02d}:00Z</time></trkpt>'
        "</trkseg></trk></gpx>\n"
    ).encode()


def _importer(client: TestClient, minute: int, compte: str = "essai-a"):
    reponse = client.post(
        f"{CHEMIN}",
        headers={"x-compte-essai": compte},
        files={"fichiers": (f"s{minute}.gpx", _gpx(minute), "application/gpx+xml")},
    )
    if reponse.status_code != 202:
        return reponse, None
    id_job = reponse.json()["donnees"]["id"]
    debut = time.monotonic()
    while True:
        etat = client.get(f"{CHEMIN}/{id_job}", headers={"x-compte-essai": compte}).json()
        if etat["donnees"]["statut"] != "en_cours":
            return reponse, etat["donnees"]
        assert time.monotonic() - debut < 5
        time.sleep(0.01)


def test_le_quota_d_imports_se_consomme_par_compte(tmp_path: Path):
    client = TestClient(_application(tmp_path, quotas_import=Quotas(plafond=2, libelle="imports")))
    assert _importer(client, 1)[1]["statut"] == "fini"
    assert _importer(client, 3)[1]["statut"] == "fini"
    refus, _ = _importer(client, 5)
    assert refus.status_code == 429
    assert refus.json()["erreur"]["code"] == "quota_atteint"
    # Un autre compte n'en pâtit pas.
    assert _importer(client, 5, compte="essai-b")[1]["statut"] == "fini"


def test_un_import_qui_echoue_rend_son_credit(tmp_path: Path, monkeypatch):
    def _casse(*args, **kwargs):
        raise RuntimeError("panne fabriquée")

    monkeypatch.setattr("ourouler.api.imports_fond.importer", _casse)
    quotas = Quotas(plafond=1, libelle="imports")
    client = TestClient(_application(tmp_path, quotas_import=quotas))
    assert _importer(client, 1)[1]["statut"] == "echoue"
    assert quotas.restant(Proprietaire("essai-a")) == 1


def test_l_application_reelle_coupe_un_flux_sans_fin_a_la_borne(tmp_path: Path, monkeypatch):
    """De bout en bout, FastAPI compris : un corps sans `Content-Length` qui ne
    finit jamais est coupé à la borne, et la réponse est le 413 lisible — pas le
    400 « error parsing the body » que FastAPI fabrique sur une lecture coupée."""
    from ourouler.api import application as module_application

    monkeypatch.setattr(module_application, "BORNES_CORPS", {CHEMIN: 10_000})
    statut, corps, lus = _appeler_sans_lire(
        _application(tmp_path), [(b"x-compte-essai", b"essai-a")]
    )
    assert statut == 413
    assert corps["erreur"]["code"] == "fichier_trop_gros"
    assert lus <= 12, f"{lus} morceaux de 1 Ko lus pour une borne de 10 Ko"

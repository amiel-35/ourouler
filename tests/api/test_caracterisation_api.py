"""Filet 0b : les sorties de référence des routes principales de l'API.

Écrit sous `tests/api/` pour la même raison que `test_contrat_openapi.py` : la
garde réseau `reseau_interdit` (autouse) et l'attente des tâches lourdes ne
valent que pour ce dossier. Les références, elles, vivent à côté
d'`openapi.json`, dans `tests/caracterisation/api_*.json`.

Les routes retenues sont celles qu'appelle le front (`front/src/api/client.ts`)
sur le parcours d'un cycliste : système, profil et zones, profil Intervals,
géocodage, météo, vent au départ, semaine et séance du jour, sortie (et son
GPX), boucle, inventaire, calibrations. Chacune avec ses échecs : 401 sans
session, 409 Intervals absent, 422 requête invalide, 429 quota atteint, 404.

L'application est construite par `creer_application` **sans aucun client
injecté** : chaque service est fabriqué par le code comme en production, et
c'est `httpx.Client` lui-même qui est rejoué (`outils_caracterisation`). Une
restructuration qui change la façon d'injecter les clients ne casse donc pas
ces références ; une qui change ce que l'API répond, si.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

#: Sans l'extra `api`, ce module se saute au lieu de casser la collecte.
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "caracterisation"))

from outils_api import ClientApi  # noqa: E402
from outils_caracterisation import (  # noqa: E402
    DOSSIER,
    JOUR,
    comparer_a_la_reference,
    ecrire_config,
    normaliser,
    preparer,
)

from ourouler.api.adaptateur import Budgets  # noqa: E402
from ourouler.api.application import creer_application  # noqa: E402
from ourouler.api.proprietaire import Proprietaire  # noqa: E402
from ourouler.api.quotas import Quotas  # noqa: E402
from ourouler.api.session import MODE_HEBERGE, SessionHebergee  # noqa: E402

pytestmark = pytest.mark.usefixtures("fuseau_de_paris")

REGENERER = "`uv run pytest tests/api/test_caracterisation_api.py --regenerer-golden`"

#: Clés dont la valeur mesure le temps d'exécution (`time.perf_counter`), pas
#: un comportement : leur **présence** est figée, leur valeur non. `duree_ms`
#: partout ; `attendu_ms` et `median_ms` seulement dans un budget dont la
#: `source` est `mesure` — un budget par défaut (`source: defaut`) est une
#: constante du code, et reste figé à sa valeur.
CLES_CHRONOMETREES = frozenset({"duree_ms"})
CLES_CHRONOMETREES_SI_MESURE = frozenset({"attendu_ms", "median_ms"})


@dataclass(frozen=True)
class SessionUnCompte:
    """Un compte hébergé fixe : le mode où les quotas s'appliquent (L9.3)."""

    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        return Proprietaire("compte-essai-caracterisation")


class Serveur:
    def __init__(self, tmp_path: Path, rejeu, **options: Any) -> None:
        self.racine = tmp_path
        self.rejeu = rejeu
        avec_intervals = options.pop("avec_intervals", True)
        cache = tmp_path / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        chemin = ecrire_config(tmp_path / "config.toml", cache, avec_intervals=avec_intervals)
        self.client = ClientApi(
            creer_application(
                chemin_config=chemin,
                dossier_donnees=tmp_path / "donnees",
                budgets=Budgets(),
                **options,
            )
        )

    def appel(self, methode: str, url: str, **kwargs: Any) -> dict[str, Any]:
        """Statut, type de contenu, corps (JSON, ou empreinte) et journal réseau."""
        self.rejeu.journal.clear()
        reponse = self.client.requete(methode, url, **kwargs)
        type_media = reponse.headers.get("content-type", "").split(";")[0]
        if "json" in type_media:
            corps: Any = reponse.json()
        else:
            corps = {
                "octets": len(reponse.content),
                "sha256": hashlib.sha256(reponse.content).hexdigest()[:16],
            }
        resultat = {
            "requete": f"{methode} {url}",
            "statut": reponse.status_code,
            "type": type_media,
            "corps": _chronos(corps),
            "reseau": sorted(self.rejeu.journal),
        }
        racine = str(self.racine)
        return normaliser(resultat, {racine: "<TMP>", os.path.realpath(racine): "<TMP>"})


def _chronos(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        chronos = set(CLES_CHRONOMETREES)
        if valeur.get("source") == "mesure":
            chronos |= CLES_CHRONOMETREES_SI_MESURE
        return {
            cle: ("<CHRONO>" if cle in chronos else _chronos(sous))
            for cle, sous in valeur.items()
        }
    if isinstance(valeur, list):
        return [_chronos(sous) for sous in valeur]
    return valeur


@pytest.fixture
def rejeu(monkeypatch: pytest.MonkeyPatch):
    return preparer(monkeypatch)


@pytest.fixture
def serveur(tmp_path: Path, rejeu):
    def fabriquer(nom: str = "principal", **options: Any) -> Serveur:
        dossier = tmp_path / nom
        dossier.mkdir()
        return Serveur(dossier, rejeu, **options)

    return fabriquer


def verifier(nom: str, obtenu: Any, regenerer_golden: bool) -> None:
    comparer_a_la_reference(obtenu, DOSSIER / f"api_{nom}.json", regenerer_golden, REGENERER)


# --- les routes ------------------------------------------------------------------


def test_systeme(serveur, regenerer_golden: bool):
    verifier("systeme", serveur().appel("GET", "/api/v1/systeme"), regenerer_golden)


def test_profil(serveur, regenerer_golden: bool):
    obtenu = {
        "profil": serveur().appel("GET", "/api/v1/profil"),
        "sans_session_401": serveur("heberge", session=SessionHebergee()).appel(
            "GET", "/api/v1/profil"
        ),
    }
    verifier("profil", obtenu, regenerer_golden)


def test_zones(serveur, regenerer_golden: bool):
    s = serveur()
    obtenu = {
        "zones": s.appel("GET", "/api/v1/profil/zones"),
        "apercu": s.appel("POST", "/api/v1/profil/zones/apercu", json={"puissance_w": 180}),
        "apercu_invalide_422": s.appel(
            "POST", "/api/v1/profil/zones/apercu", json={"puissance_w": "beaucoup"}
        ),
    }
    verifier("zones", obtenu, regenerer_golden)


def test_profil_intervals(serveur, regenerer_golden: bool):
    obtenu = {
        "avec_cle": serveur().appel("GET", "/api/v1/profil/intervals"),
        "sans_cle_409": serveur("sans_cle", avec_intervals=False).appel(
            "GET", "/api/v1/profil/intervals"
        ),
    }
    verifier("profil_intervals", obtenu, regenerer_golden)


def test_geocodage(serveur, regenerer_golden: bool):
    s = serveur()
    obtenu = {
        "adresse": s.appel("GET", "/api/v1/geocodage", params={"adresse": "7 rue du If"}),
        "adresse_vide_422": s.appel("GET", "/api/v1/geocodage", params={"adresse": "   "}),
    }
    verifier("geocodage", obtenu, regenerer_golden)


def test_meteo(serveur, regenerer_golden: bool):
    obtenu = {
        "meteo": serveur().appel(
            "GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"}
        ),
        "horizon_invalide_422": serveur("invalide").appel(
            "GET", "/api/v1/meteo", params={"horizon": 0}
        ),
        "quota_atteint_429": serveur(
            "quota", session=SessionUnCompte(), quotas_meteo=Quotas(plafond=0)
        ).appel("GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"}),
    }
    verifier("meteo", obtenu, regenerer_golden)


def test_vent_depart(serveur, regenerer_golden: bool):
    obtenu = serveur().appel(
        "GET", "/api/v1/vent-depart", params={"jour": JOUR, "heure_depart": "09:00"}
    )
    verifier("vent_depart", obtenu, regenerer_golden)


def test_seances(serveur, regenerer_golden: bool):
    s = serveur()
    obtenu = {
        "semaine": s.appel(
            "GET", "/api/v1/seances", params={"depuis": "2026-09-07", "jusqua": "2026-09-13"}
        ),
        "jour_avec_seance": s.appel("GET", f"/api/v1/seances/{JOUR}"),
        "jour_sans_seance": s.appel("GET", "/api/v1/seances/2026-09-09"),
        "jour_illisible_422": s.appel("GET", "/api/v1/seances/pas-une-date"),
        "sans_cle_409": serveur("sans_cle", avec_intervals=False).appel(
            "GET", f"/api/v1/seances/{JOUR}"
        ),
    }
    verifier("seances", obtenu, regenerer_golden)


def test_sorties(serveur, regenerer_golden: bool):
    s = serveur()
    sortie = s.appel(
        "POST", "/api/v1/sorties", json={"jour": JOUR, "heure_depart": "09:00", "candidates": 2}
    )
    generation = s.client.post(
        "/api/v1/sorties", json={"jour": JOUR, "heure_depart": "09:00", "candidates": 2}
    ).json()
    identifiant = _generation(generation)
    obtenu = {
        "sortie": sortie,
        "gpx_proposition_1": s.appel(
            "GET", f"/api/v1/sorties/{identifiant}/propositions/1/gpx"
        ),
        "gpx_proposition_inconnue_404": s.appel(
            "GET", f"/api/v1/sorties/{identifiant}/propositions/99/gpx"
        ),
        "demande_invalide_422": s.appel("POST", "/api/v1/sorties", json={"candidates": 0}),
        "sans_session_401": serveur("heberge", session=SessionHebergee()).appel(
            "POST", "/api/v1/sorties", json={"jour": JOUR}
        ),
        "quota_atteint_429": serveur(
            "quota", session=SessionUnCompte(), quotas=Quotas(plafond=0)
        ).appel("POST", "/api/v1/sorties", json={"jour": JOUR}),
    }
    verifier("sorties", obtenu, regenerer_golden)


def _generation(corps: dict) -> str:
    """L'identifiant de génération que la route de GPX attend, lu dans la réponse."""
    trouve = _chercher(corps, "generation")
    assert trouve, f"pas d'identifiant de génération dans la réponse : {sorted(corps)}"
    return str(trouve)


def _chercher(valeur: Any, cle: str) -> Any:
    if isinstance(valeur, dict):
        if cle in valeur and isinstance(valeur[cle], str | int):
            return valeur[cle]
        for sous in valeur.values():
            trouve = _chercher(sous, cle)
            if trouve is not None:
                return trouve
    if isinstance(valeur, list):
        for sous in valeur:
            trouve = _chercher(sous, cle)
            if trouve is not None:
                return trouve
    return None


def test_boucles(serveur, regenerer_golden: bool):
    s = serveur()
    obtenu = {
        "boucle": s.appel(
            "POST",
            "/api/v1/boucles",
            json={"distance_km": 30, "direction": "N", "heure_depart": f"{JOUR}T09:00"},
        ),
        "distance_manquante_422": s.appel("POST", "/api/v1/boucles", json={"direction": "N"}),
    }
    verifier("boucles", obtenu, regenerer_golden)


def test_inventaire(serveur, regenerer_golden: bool):
    verifier("inventaire", serveur().appel("GET", "/api/v1/inventaire"), regenerer_golden)


def test_calibrations(serveur, regenerer_golden: bool):
    verifier("calibrations", serveur().appel("GET", "/api/v1/calibrations"), regenerer_golden)

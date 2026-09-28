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

**Chaque test tourne sur les trois chemins de l'API**
(`api/double_chemin.py`) — `ancien` (l'adaptateur de la ligne de commande),
`nouveau` (service et rendu), `double` (les deux, l'ancien répond) — contre
les **mêmes** références. En `double`, deux choses de plus : aucune ligne
d'écart ne doit être journalisée, et chaque appel réseau est fait deux fois,
dans le même ordre (l'ancien chemin, puis le nouveau) ; le journal comparé à
la référence est alors la première moitié, après vérification que la
seconde la répète à l'identique. Les références ne se régénèrent que sur
l'ancien chemin.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from donnees_synthetiques import ATHLETE, CLE, ROUTE, tcx_synthetique
from outils_api import ClientApi, attendre_tache_rendue
from outils_caracterisation import (
    DOSSIER,
    JOUR,
    MODELE_SECOND,
    comparer_a_la_reference,
    ecrire_config,
    normaliser,
    preparer,
)

from ourouler.api.adaptateur import Budgets
from ourouler.api.application import creer_application
from ourouler.api.depots import SocleTOML
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.quotas import Quotas
from ourouler.api.session import MODE_HEBERGE, SessionHebergee

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
    def __init__(self, tmp_path: Path, rejeu, chemin_api: str, **options: Any) -> None:
        self.racine = tmp_path
        self.rejeu = rejeu
        self.chemin_api = chemin_api
        avec_intervals = options.pop("avec_intervals", True)
        cache = tmp_path / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        chemin = ecrire_config(tmp_path / "config.toml", cache, avec_intervals=avec_intervals)
        if options.pop("socle_partage", False):
            # Comme `application()` en mode hébergé : le TOML du serveur n'est
            # le profil de personne, chaque compte pose le sien (`PATCH /profil`).
            options["socle"] = SocleTOML(chemin, proprietaire=None)
        else:
            options["chemin_config"] = chemin
        self.client = ClientApi(
            creer_application(
                dossier_donnees=tmp_path / "donnees",
                budgets=Budgets(),
                chemin_api=chemin_api,
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
        self.dernier_corps = corps
        resultat = {
            "requete": f"{methode} {url}",
            "statut": reponse.status_code,
            "type": type_media,
            "corps": _chronos(corps),
            "reseau": sorted(self._journal_d_un_passage()),
        }
        racine = str(self.racine)
        return normaliser(resultat, {racine: "<TMP>", os.path.realpath(racine): "<TMP>"})

    def _journal_d_un_passage(self) -> list[str]:
        """Le journal réseau d'**un** chemin : en `double`, la moitié répétée.

        Le mode `double` fait tourner l'ancien chemin puis le nouveau, qui
        refont les mêmes appels dans le même ordre. Une route qui ne passe
        pas par le double chemin (profil, calibrations…) n'appelle qu'une
        fois : son journal n'est pas une répétition, il est rendu tel quel.
        """
        journal = list(self.rejeu.journal)
        moitie = len(journal) // 2
        if (
            self.chemin_api == CHEMIN_DOUBLE
            and journal
            and len(journal) % 2 == 0
            and journal[:moitie] == journal[moitie:]
        ):
            return journal[:moitie]
        return journal


def _chronos(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        chronos = set(CLES_CHRONOMETREES)
        if valeur.get("source") == "mesure":
            chronos |= CLES_CHRONOMETREES_SI_MESURE
        return {cle: ("<CHRONO>" if cle in chronos else _chronos(sous)) for cle, sous in valeur.items()}
    if isinstance(valeur, list):
        return [_chronos(sous) for sous in valeur]
    return valeur


@pytest.fixture
def rejeu(monkeypatch: pytest.MonkeyPatch):
    return preparer(monkeypatch)


#: Les trois chemins de l'API (`api/double_chemin.py`), écrits en
#: clair : le filet ne dépend que de surfaces stables
#: (`test_le_filet_ne_depend_que_de_surfaces_stables`), et ces trois mots
#: sont celles d'`OUROULER_API_CHEMIN`.
CHEMIN_ANCIEN, CHEMIN_NOUVEAU, CHEMIN_DOUBLE = "ancien", "nouveau", "double"
CHEMINS = (CHEMIN_ANCIEN, CHEMIN_NOUVEAU, CHEMIN_DOUBLE)

#: Le chemin de l'API de chaque test, lu par `verifier`.
_CHEMIN_COURANT: list[str] = [CHEMIN_ANCIEN]


@pytest.fixture(params=CHEMINS)
def chemin_api(request, caplog: pytest.LogCaptureFixture):
    """Les trois chemins ; en `double`, **aucun écart** ne doit avoir été journalisé."""
    _CHEMIN_COURANT[0] = request.param
    with caplog.at_level("WARNING", logger="ourouler.api.double_chemin"):
        yield request.param
    ecarts = [r.getMessage() for r in caplog.records if r.name == "ourouler.api.double_chemin"]
    assert not ecarts, f"écarts entre l'ancien et le nouveau chemin : {ecarts}"


@pytest.fixture
def serveur(tmp_path: Path, rejeu, chemin_api: str):
    def fabriquer(nom: str = "principal", **options: Any) -> Serveur:
        dossier = tmp_path / nom
        dossier.mkdir()
        return Serveur(dossier, rejeu, chemin_api, **options)

    return fabriquer


def verifier(nom: str, obtenu: Any, regenerer_golden: bool) -> None:
    """Compare à la référence ; ne la réécrit que depuis l'ancien chemin."""
    if regenerer_golden and _CHEMIN_COURANT[0] != CHEMIN_ANCIEN:
        pytest.skip("les références se régénèrent sur l'ancien chemin seulement")
    comparer_a_la_reference(obtenu, DOSSIER / f"api_{nom}.json", regenerer_golden, REGENERER)


# --- les routes ------------------------------------------------------------------


def test_systeme(serveur, regenerer_golden: bool):
    verifier("systeme", serveur().appel("GET", "/api/v1/systeme"), regenerer_golden)


def test_profil(serveur, regenerer_golden: bool):
    obtenu = {
        "profil": serveur().appel("GET", "/api/v1/profil"),
        "sans_session_401": serveur("heberge", session=SessionHebergee()).appel("GET", "/api/v1/profil"),
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
        "sans_cle_409": serveur("sans_cle", avec_intervals=False).appel("GET", "/api/v1/profil/intervals"),
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
        "meteo": serveur().appel("GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"}),
        "horizon_invalide_422": serveur("invalide").appel("GET", "/api/v1/meteo", params={"horizon": 0}),
        "quota_atteint_429": serveur(
            "quota", session=SessionUnCompte(), quotas_meteo=Quotas(plafond=0)
        ).appel("GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"}),
    }
    verifier("meteo", obtenu, regenerer_golden)


def test_vent_depart(serveur, regenerer_golden: bool):
    obtenu = serveur().appel("GET", "/api/v1/vent-depart", params={"jour": JOUR, "heure_depart": "09:00"})
    verifier("vent_depart", obtenu, regenerer_golden)


def test_seances(serveur, regenerer_golden: bool):
    s = serveur()
    obtenu = {
        "semaine": s.appel("GET", "/api/v1/seances", params={"depuis": "2026-09-07", "jusqua": "2026-09-13"}),
        "jour_avec_seance": s.appel("GET", f"/api/v1/seances/{JOUR}"),
        "jour_sans_seance": s.appel("GET", "/api/v1/seances/2026-09-09"),
        "jour_illisible_422": s.appel("GET", "/api/v1/seances/pas-une-date"),
        "sans_cle_409": serveur("sans_cle", avec_intervals=False).appel("GET", f"/api/v1/seances/{JOUR}"),
    }
    verifier("seances", obtenu, regenerer_golden)


def test_sorties(serveur, regenerer_golden: bool):
    s = serveur()
    sortie = s.appel("POST", "/api/v1/sorties", json={"jour": JOUR, "heure_depart": "09:00", "candidates": 2})
    generation = s.client.post(
        "/api/v1/sorties", json={"jour": JOUR, "heure_depart": "09:00", "candidates": 2}
    ).json()
    identifiant = _generation(generation)
    obtenu = {
        "sortie": sortie,
        "gpx_proposition_1": s.appel("GET", f"/api/v1/sorties/{identifiant}/propositions/1/gpx"),
        "gpx_proposition_inconnue_404": s.appel("GET", f"/api/v1/sorties/{identifiant}/propositions/99/gpx"),
        "demande_invalide_422": s.appel("POST", "/api/v1/sorties", json={"candidates": 0}),
        "sans_session_401": serveur("heberge", session=SessionHebergee()).appel(
            "POST", "/api/v1/sorties", json={"jour": JOUR}
        ),
        "quota_atteint_429": serveur("quota", session=SessionUnCompte(), quotas=Quotas(plafond=0)).appel(
            "POST", "/api/v1/sorties", json={"jour": JOUR}
        ),
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


# --- un compte hébergé, en succès ------------------------------------------------
#
# `SessionUnCompte` tient lieu de compte : un propriétaire ≠ `local`, en mode
# hébergé (quotas actifs), **sans** Postgres. Ce qui est figé ici : ce qu'un
# compte obtient une fois authentifié (cloisonnement du cache, de la
# calibration, des imports). Ce qui ne l'est pas : l'authentification réelle
# (comptes, invitations, sessions en base) — voir le LISEZMOI.


#: Le profil que le compte pose sur le socle commun : les sections « perso
#: pur » (Q35) que `SocleTOML(proprietaire=None)` retire du TOML du serveur.
#: Mêmes valeurs synthétiques que `CONFIG_TOML` : départ (0, 0) en mer.
PROFIL_DU_COMPTE = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 91.0, "ftp_w": 200},
    "velos": [
        {
            "nom": "RCR",
            "usage": "route",
            "periodes": [{"debut": "2026-01-01", "fin": "2026-01-31"}],
        }
    ],
    "intervals": {"athlete_id": ATHLETE, "api_key": CLE},
}


def serveur_de_compte(serveur) -> tuple[Serveur, dict[str, Any]]:
    """Un serveur hébergé à socle commun, et le compte qui y pose son profil."""
    s = serveur("compte", session=SessionUnCompte(), socle_partage=True)
    return s, s.appel("PATCH", "/api/v1/profil", json=PROFIL_DU_COMPTE)


def test_heberge_sortie_et_calibrations(serveur, regenerer_golden: bool):
    s, profil = serveur_de_compte(serveur)
    obtenu = {
        "profil_pose": profil,
        "sortie": s.appel(
            "POST",
            "/api/v1/sorties",
            json={"jour": JOUR, "heure_depart": "09:00", "candidates": 2},
        ),
        "calibrations": s.appel("GET", "/api/v1/calibrations"),
    }
    verifier("heberge", obtenu, regenerer_golden)


#: Au-delà, un import qui ne finit pas fait échouer le test au lieu de le bloquer.
DELAI_IMPORT_S = 30.0


def test_heberge_import_d_activites(serveur, regenerer_golden: bool):
    """`POST /activites/import` (202), puis `GET /activites/import/{id}` jusqu'à la fin.

    Seul l'état final est figé : combien d'interrogations il a fallu dépend
    de la machine, pas du comportement.
    """
    s, _ = serveur_de_compte(serveur)
    tcx = tcx_synthetique(ROUTE, date(2026, 1, 5))
    depot = s.appel(
        "POST",
        "/api/v1/activites/import",
        files={"fichiers": ("sortie_2026-01-05.tcx", tcx, "application/vnd.garmin.tcx+xml")},
    )
    id_job = s.dernier_corps["donnees"]["id"]  # avant normalisation : l'UUID réel
    debut = time.monotonic()
    while True:
        etat = s.appel("GET", f"/api/v1/activites/import/{id_job}")
        if etat["corps"]["donnees"]["statut"] != "en_cours":
            attendre_tache_rendue(id_job)
            break
        assert time.monotonic() - debut < DELAI_IMPORT_S, "import toujours en cours"
        time.sleep(0.02)
    # L'état du dépôt (en cours ou déjà fini) dépend de la vitesse de la machine.
    depot["corps"]["donnees"]["statut"] = "<en_cours|fini>"
    for cle in ("traites", "total", "rapport"):
        if cle in depot["corps"]["donnees"]:
            depot["corps"]["donnees"][cle] = "<selon l'avancement>"
    obtenu = {
        "depot": depot,
        "fin": etat,
        "inventaire_apres": s.appel("GET", "/api/v1/inventaire"),
        "calibrations_apres": s.appel("GET", "/api/v1/calibrations"),
    }
    verifier("heberge_import", obtenu, regenerer_golden)


# --- un avertissement du cœur -----------------------------------------------------


def test_avertissement_second_avis_en_panne(serveur, rejeu, regenerer_golden: bool):
    """Le second modèle météo répond 500 : la météo sort, avec un avertissement **codé**.

    Le chemin est celui que le nouveau chemin de l'API réécrit (sortie d'erreur
    du cœur → `avertissements` de l'enveloppe) : sans ce scénario, toutes les
    références portent `avertissements: []`, et un adaptateur qui les perdrait
    passerait.
    """
    rejeu.en_panne("api.open-meteo.com", models=MODELE_SECOND)
    obtenu = serveur().appel("GET", "/api/v1/meteo", params={"heure_depart": f"{JOUR}T09:00"})
    avertissements = obtenu["corps"]["avertissements"]
    assert avertissements and all(a.get("code") for a in avertissements), avertissements
    verifier("avertissement", obtenu, regenerer_golden)

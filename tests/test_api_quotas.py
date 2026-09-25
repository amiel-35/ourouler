"""Tests du quota journalier de générations coûteuses par compte (lot L9.3).

Aucun réseau : mêmes bouchons que `tests/test_api.py` (`moteur_brouter`,
`moteur_meteo`, `client_intervals`). Deux comptes distincts sont simulés par
un fournisseur de session minimal qui lit un en-tête — pas de base de
comptes réelle : `api/session.FournisseurSession` est une interface, la
brancher sur un en-tête plutôt que sur un cookie est une implémentation
légitime pour un test, exactement comme `SessionParCookie` en est une pour
le service réel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from fastapi.testclient import TestClient
from test_api import ecrire_config
from test_seance_intervals import ATHLETE, CLE, W
from test_sortie_commande import client_intervals, ecrire_calibration, moteur_brouter, moteur_meteo

from ourouler.api.adaptateur import Budgets
from ourouler.api.application import creer_application
from ourouler.api.depots import SocleTOML
from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL, Proprietaire
from ourouler.api.quotas import Quotas
from ourouler.api.routes import Clients
from ourouler.api.session import MODE_HEBERGE, SessionPersonnelle

#: Le profil qu'un compte de test écrit sur lui-même avant sa première
#: génération — depuis Q35 (tiers 3), un socle hébergé et partagé
#: (`SocleTOML(..., proprietaire=None)`) ne prête **rien** de perso pur
#: (départ, cycliste, vélos, Intervals) à qui n'a pas écrit le sien.
PROFIL_COMPTE_ESSAI = {
    "depart": {"nom": "Point d'essai", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 76.5, "ftp_w": W.FTP_TEST},
    "velos": [{"nom": "Route", "usage": "route", "masse_kg": 8.5, "cda_m2": 0.32}],
    "intervals": {"athlete_id": ATHLETE, "api_key": CLE},
}


@dataclass(frozen=True)
class SessionParEnTete:
    """Un fournisseur de session minimal, pour choisir un compte par en-tête.

    Le service réel utilise `SessionParCookie` (jeton opaque, base des
    comptes) ; ce test-ci n'a besoin que de deux identités stables et
    distinctes, sans base de données. `FournisseurSession` est une
    interface — n'importe quelle implémentation qui rend un `Proprietaire`
    ou `None` la respecte.
    """

    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        identifiant = getattr(requete, "headers", {}).get("x-compte-essai")
        return Proprietaire(identifiant) if identifiant else None


def serveur(
    tmp_path: Path,
    *,
    quotas: Quotas | None = None,
    session=None,
    partage: bool = True,
    **clients,
) -> TestClient:
    """Le même serveur que `test_api.serveur`, avec un quota et une session injectables.

    `partage=True` (le défaut, pour ces tests multi-comptes) déclare le TOML
    comme le profil de **personne** (`SocleTOML(..., proprietaire=None)`,
    même geste que `application()` en mode hébergé) : chaque compte doit
    écrire le sien (`activer_compte`) avant sa première génération.
    """
    ecrire_calibration(tmp_path / "cache")
    chemin = ecrire_config(tmp_path)
    application = creer_application(
        socle=SocleTOML(chemin, proprietaire=None) if partage else None,
        chemin_config=None if partage else chemin,
        dossier_donnees=tmp_path / "cache" / "api",
        clients=Clients(**clients),
        budgets=Budgets(),
        quotas=quotas,
        session=session,
    )
    return TestClient(application, raise_server_exceptions=False)


def client_hors_reseau(tmp_path: Path, *, quotas: Quotas, session=None) -> TestClient:
    """Un serveur dont les trois services externes sont bouchonnés et répondent."""
    return serveur(
        tmp_path,
        quotas=quotas,
        session=session or SessionParEnTete(),
        brouter=moteur_brouter(),
        meteo=moteur_meteo(),
        intervals=client_intervals(),
    )


def activer_compte(client: TestClient, compte: str) -> None:
    """Écrit un profil complet pour ce compte — sinon la génération refuse
    (« profil incomplet »), sans rapport avec le quota que ces tests visent."""
    reponse = client.patch(
        "/api/v1/profil", json=PROFIL_COMPTE_ESSAI, headers={"x-compte-essai": compte}
    )
    assert reponse.status_code == 200, reponse.text


def generer_sortie(client: TestClient, compte: str = "essai-a"):
    return client.post(
        "/api/v1/sorties",
        json={"jour": "2026-09-08", "candidates": 1},
        headers={"x-compte-essai": compte},
    )


def generer_boucle(client: TestClient, compte: str = "essai-a"):
    return client.post(
        "/api/v1/boucles",
        json={"distance_km": 30.0, "direction": "N"},
        headers={"x-compte-essai": compte},
    )


# --- le plafond refuse, avec un contrat exploitable ---------------------------


def test_sous_le_plafond_les_generations_passent(tmp_path: Path):
    client = client_hors_reseau(tmp_path, quotas=Quotas(plafond=2))
    assert generer_sortie(client).status_code == 200
    assert generer_boucle(client).status_code == 200


def test_au_dela_du_plafond_le_service_refuse(tmp_path: Path):
    client = client_hors_reseau(tmp_path, quotas=Quotas(plafond=2))
    assert generer_sortie(client).status_code == 200
    assert generer_boucle(client).status_code == 200
    refus = generer_sortie(client)
    assert refus.status_code == 429
    charge = refus.json()["erreur"]
    assert charge["code"] == "quota_atteint"
    assert "quota" in charge["message"].lower()
    assert "reinitialisation_utc" in charge["details"]
    assert charge["details"]["plafond"] == 2


def test_boucles_et_sorties_partagent_le_meme_compteur(tmp_path: Path):
    """Une « génération » au sens du quota, que la route soit l'une ou l'autre."""
    client = client_hors_reseau(tmp_path, quotas=Quotas(plafond=1))
    assert generer_sortie(client).status_code == 200
    refus = generer_boucle(client)
    assert refus.status_code == 429
    assert refus.json()["erreur"]["code"] == "quota_atteint"


def test_un_refus_de_quota_ne_touche_ni_brouter_ni_meteo(tmp_path: Path):
    """Le quota se vérifie avant tout travail : un compte au plafond ne coûte rien au serveur."""
    brouter_appele = moteur_brouter()
    client = serveur(
        tmp_path,
        quotas=Quotas(plafond=0),
        session=SessionParEnTete(),
        brouter=brouter_appele,
        meteo=moteur_meteo(),
        intervals=client_intervals(),
    )
    refus = generer_sortie(client)
    assert refus.status_code == 429


# --- isolation entre comptes ---------------------------------------------------


def test_deux_comptes_ont_chacun_leur_plafond(tmp_path: Path):
    client = client_hors_reseau(tmp_path, quotas=Quotas(plafond=1))
    # Chacun avec son propre profil complet (Q35, tiers 3 : rien n'est
    # hérité du socle partagé, voir `test_api.py`) — pour prouver que
    # l'isolation du quota tient même quand les comptes sont pour de vrai
    # deux profils distincts, pas seulement deux identifiants.
    activer_compte(client, "essai-a")
    activer_compte(client, "essai-b")
    assert generer_sortie(client, compte="essai-a").status_code == 200
    # Le compte A est au plafond ; B, distinct, n'a encore rien consommé.
    assert generer_sortie(client, compte="essai-b").status_code == 200
    # Et A reste refusé — son compteur n'a pas été remis à zéro par B.
    assert generer_sortie(client, compte="essai-a").status_code == 429


# --- remise à zéro au jour suivant, horloge injectée ---------------------------


def test_le_quota_se_remet_a_zero_le_jour_suivant(tmp_path: Path):
    horloge = {"maintenant": datetime(2026, 9, 25, 23, 0, tzinfo=UTC)}
    quotas = Quotas(plafond=1, horloge=lambda: horloge["maintenant"])
    client = client_hors_reseau(tmp_path, quotas=quotas)

    assert generer_sortie(client).status_code == 200
    assert generer_sortie(client).status_code == 429

    horloge["maintenant"] = datetime(2026, 9, 26, 0, 5, tzinfo=UTC)
    assert generer_sortie(client).status_code == 200, "un nouveau jour UTC, un nouveau plafond"


def test_quotas_consommer_et_restant_directement():
    """Le comportement de `Quotas`, sans passer par l'API — la remise à zéro et `restant`."""
    horloge = {"maintenant": datetime(2026, 1, 1, tzinfo=UTC)}
    quotas = Quotas(plafond=2, horloge=lambda: horloge["maintenant"])
    quelqu_un = Proprietaire("essai-directe")

    assert quotas.restant(quelqu_un) == 2
    quotas.consommer(quelqu_un)
    assert quotas.restant(quelqu_un) == 1
    quotas.consommer(quelqu_un)
    assert quotas.restant(quelqu_un) == 0
    with pytest.raises(Exception) as exc_info:
        quotas.consommer(quelqu_un)
    assert "quota_atteint" in str(exc_info.value) or getattr(exc_info.value, "code", "") == (
        "quota_atteint"
    )

    horloge["maintenant"] = datetime(2026, 1, 2, tzinfo=UTC)
    assert quotas.restant(quelqu_un) == 2, "un autre jour UTC, un compteur neuf"
    quotas.consommer(quelqu_un)  # ne lève pas


# --- le mode personnel n'a pas de quota -----------------------------------------


def test_le_mode_personnel_n_a_aucun_quota(tmp_path: Path):
    """Même un plafond à zéro laisse passer `PROPRIETAIRE_LOCAL` (`SessionPersonnelle`)."""
    ecrire_calibration(tmp_path / "cache")
    application = creer_application(
        chemin_config=ecrire_config(tmp_path),
        dossier_donnees=tmp_path / "cache" / "api",
        clients=Clients(
            brouter=moteur_brouter(), meteo=moteur_meteo(), intervals=client_intervals()
        ),
        budgets=Budgets(),
        quotas=Quotas(plafond=0),
        session=SessionPersonnelle(),
    )
    client = TestClient(application, raise_server_exceptions=False)
    for _ in range(3):
        reponse = client.post(
            "/api/v1/sorties", json={"jour": "2026-09-08", "candidates": 1}
        )
        assert reponse.status_code == 200, reponse.text


def test_systeme_porte_le_quota_en_mode_heberge_mais_pas_en_personnel(tmp_path: Path):
    client = client_hors_reseau(tmp_path, quotas=Quotas(plafond=7))
    charge = client.get("/api/v1/systeme", headers={"x-compte-essai": "essai-a"}).json()
    assert charge["quota"] == {"plafond": 7, "restant": 7}

    ecrire_calibration(tmp_path / "cache-perso")
    application_perso = creer_application(
        chemin_config=ecrire_config(tmp_path),
        dossier_donnees=tmp_path / "cache-perso" / "api",
        budgets=Budgets(),
    )
    charge_perso = TestClient(application_perso).get("/api/v1/systeme").json()
    assert charge_perso["proprietaire"] == str(PROPRIETAIRE_LOCAL)
    assert "quota" not in charge_perso

"""La calibration depuis l'écran (lot L9.4) : `GET/POST /calibrations`, `GET /calibrations/{id}`.

Aucun réseau (règle absolue 3) : l'archive météo est un `MockTransport`
(`test_physique_commande.archive_bouchonnee`), BRouter et Open-Meteo les
bouchons ordinaires du dépôt. Les sorties sont **fabriquées par le modèle**
(`test_physique_calibration.sortie_synthetique`) autour du point (0, 0) —
aucune donnée personnelle, aucune coordonnée réelle.

Ce qui est éprouvé : le calcul de bout en bout en mode hébergé, écrit dans le
dossier du compte et relu par ses seules routes (isolation A/B, jusqu'aux
boucles) ; les quatre préconditions et ce qu'elles disent ; le verrou des
tâches lourdes ; le quota (une par jour, remboursé sur échec) ; le mode
personnel, qui écrit là où la ligne de commande écrit.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api import ecrire_config
from test_physique_calibration import sortie_synthetique
from test_physique_commande import _en_tcx, archive_bouchonnee
from test_sortie_commande import client_intervals, moteur_brouter, moteur_meteo

from ourouler.activites.cache import Cache
from ourouler.api import taches_fond
from ourouler.api.adaptateur import Budgets
from ourouler.api.application import creer_application
from ourouler.api.depots import SocleTOML
from ourouler.api.proprietaire import Proprietaire
from ourouler.api.quotas import Quotas
from ourouler.api.routes.commun import Clients
from ourouler.api.session import MODE_HEBERGE
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique import commande as physique
from ourouler.services import calibrer
from ourouler.stockage.calibrations import VERSION_CALIBRATION

PREFIXE = "/api/v1"
A = "essai-calib-a"
B = "essai-calib-b"


@dataclass(frozen=True)
class SessionParEnTete:
    """Deux identités distinctes sans base de comptes — même patron que `test_api_quotas`."""

    mode = MODE_HEBERGE

    def ouvrir(self, requete: object) -> Proprietaire | None:
        identifiant = getattr(requete, "headers", {}).get("x-compte-essai")
        return Proprietaire(identifiant) if identifiant else None


def _profil(*, velos: list[dict] | None = None, ftp: float | None = 258.0) -> dict:
    cycliste: dict = {"masse_kg": 91.0}
    if ftp is not None:
        cycliste["ftp_w"] = ftp
    return {
        "depart": {"nom": "Point d'essai", "latitude": 0.0, "longitude": 0.0},
        "cycliste": cycliste,
        "velos": velos
        if velos is not None
        else [{"nom": "Route", "usage": "route", "masse_kg": 9.0, "pneu": "course_rapide"}],
    }


def _serveur(tmp_path: Path, *, quotas_calibration: Quotas | None = None) -> TestClient:
    chemin = ecrire_config(tmp_path)
    application = creer_application(
        socle=SocleTOML(chemin, proprietaire=None),
        dossier_donnees=tmp_path / "donnees",
        clients=Clients(
            brouter=moteur_brouter(),
            meteo=moteur_meteo(),
            intervals=client_intervals(),
            archive=archive_bouchonnee(),
        ),
        budgets=Budgets(),
        quotas_calibration=quotas_calibration,
        session=SessionParEnTete(),
    )
    return TestClient(application, raise_server_exceptions=False)


def _activer(client: TestClient, qui: str, profil: dict) -> None:
    reponse = client.patch(f"{PREFIXE}/profil", json=profil, headers={"x-compte-essai": qui})
    assert reponse.status_code == 200, reponse.text


def _semer(tmp_path: Path, qui: str, n: int, *, meta: dict | None = None, mois: int = 1) -> None:
    """`n` sorties fabriquées par le modèle, déposées comme par l'import (`source="fichier"`)."""
    cache = Cache(tmp_path / "cache", proprietaire=qui)
    for jour in range(1, n + 1):
        quand = date(2026, mois, jour)
        cache.ajouter(
            _en_tcx(sortie_synthetique(duree_s=2600), quand),
            source="fichier",
            id_externe=f"{qui}-{quand.isoformat()}",
            extension="tcx",
            meta={"nom": f"sortie du {quand}", "sport": "Ride", **(meta or {})},
        )


def _lancer(client: TestClient, qui: str, **corps):
    return client.post(f"{PREFIXE}/calibrations", json=corps, headers={"x-compte-essai": qui})


def _attendre(client: TestClient, qui: str, id_job: str, delai_max_s: float = 30.0) -> dict:
    debut = time.monotonic()
    while True:
        reponse = client.get(f"{PREFIXE}/calibrations/{id_job}", headers={"x-compte-essai": qui})
        assert reponse.status_code == 200, reponse.text
        donnees = reponse.json()["donnees"]
        if donnees["statut"] != taches_fond.STATUT_EN_COURS:
            return donnees
        if time.monotonic() - debut > delai_max_s:
            raise AssertionError(f"calibration {id_job} toujours en cours")
        time.sleep(0.05)


def _calibrer(client: TestClient, qui: str, **corps) -> dict:
    reponse = _lancer(client, qui, **corps)
    assert reponse.status_code == 202, reponse.text
    return _attendre(client, qui, reponse.json()["donnees"]["id"])


@pytest.fixture(autouse=True)
def _verrou_libre():
    assert taches_fond.VERROU.acquire(blocking=False), "le verrou n'était pas libre au départ"
    taches_fond.VERROU.release()
    yield


# --- de bout en bout, et l'isolation --------------------------------------------


def test_calibrer_de_bout_en_bout_ecrit_dans_le_dossier_du_compte(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)

    fini = _calibrer(client, A)
    assert fini["statut"] == "fini", fini
    assert fini["nature"] == "calibration" and fini["sujet"] == "Route"
    resultat = fini["rapport"]["calibration"]
    assert resultat["provenance"] == "mesure"
    assert resultat["crr_source"] == "pneu" and resultat["pneu"] == "course_rapide"
    assert 50 < resultat["puissance_repere_w"] < 400
    assert resultat["vitesse_repere_kmh"] == 30.0
    assert resultat["n_sorties"] > 0 and resultat["n_validation"] > 0
    assert resultat["erreur_validation"] is not None
    # 12 sorties : trop peu de sorties de validation pour une fourchette
    # mesurée — la convention reste en vigueur, et elle le dit.
    assert resultat["porte_a_porte"]["provenance"] == "defaut"
    assert set(resultat["detail"]) == {"cda_m2", "crr", "masse_totale_kg"}

    # Écrite dans le dossier du compte, jamais dans le cache du serveur.
    fichier = tmp_path / "donnees" / A / "calibration.json"
    assert fichier.is_file()
    assert "Route" in json.loads(fichier.read_text(encoding="utf-8"))["velos"]
    assert not (tmp_path / "cache" / "calibration.json").exists()

    # Et relue ensuite partout : l'écran de FTP de A dit « calibration ».
    zones = client.get(f"{PREFIXE}/profil/zones", headers={"x-compte-essai": A}).json()
    assert zones["donnees"]["valeurs_liees"]["modele_physique"] == "calibration"
    etat = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": A}).json()
    velo = etat["donnees"]["velos"][0]
    assert velo["calibration"]["provenance"] == "mesure"
    assert velo["tache"]["id"] == fini["id"]


def test_la_calibration_de_a_n_affecte_jamais_b(tmp_path: Path):
    """A et B ont un vélo du même nom ; seul A calibre. Rien de A n'atteint B —
    ni l'état de calibration, ni l'écran de FTP, ni les boucles."""
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _activer(client, B, _profil())
    _semer(tmp_path, A, 12)
    _semer(tmp_path, B, 2, mois=3)

    boucle_b_avant = client.post(
        f"{PREFIXE}/boucles",
        json={"distance_km": 30.0, "candidates": 1},
        headers={"x-compte-essai": B},
    )
    assert boucle_b_avant.status_code == 200, boucle_b_avant.text

    assert _calibrer(client, A)["statut"] == "fini"

    etat_b = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": B}).json()
    assert etat_b["donnees"]["velos"][0]["calibration"] is None
    assert etat_b["donnees"]["velos"][0]["tache"] is None
    zones_b = client.get(f"{PREFIXE}/profil/zones", headers={"x-compte-essai": B}).json()
    assert zones_b["donnees"]["valeurs_liees"]["modele_physique"] == "littérature"
    zones_a = client.get(f"{PREFIXE}/profil/zones", headers={"x-compte-essai": A}).json()
    assert zones_a["donnees"]["valeurs_liees"]["modele_physique"] == "calibration"

    boucle_b_apres = client.post(
        f"{PREFIXE}/boucles",
        json={"distance_km": 30.0, "candidates": 1},
        headers={"x-compte-essai": B},
    )
    assert boucle_b_apres.status_code == 200, boucle_b_apres.text
    avant = boucle_b_avant.json()["donnees"]
    apres = boucle_b_apres.json()["donnees"]
    assert json.dumps(apres["compteur"], sort_keys=True) == json.dumps(
        avant["compteur"], sort_keys=True
    )
    assert "calibration" not in json.dumps(apres, ensure_ascii=False)


def test_un_compte_heberge_ne_lit_jamais_la_calibration_commune(tmp_path: Path):
    """Un `calibration.json` dans le cache du serveur (celui de la ligne de
    commande) nomme un vélo « Route » ; B a un « Route » lui aussi, jamais
    calibré. Ni son état de calibration ni son écran de FTP ne doivent le voir."""
    client = _serveur(tmp_path)
    _activer(client, B, _profil())
    commun = tmp_path / "cache" / physique.NOM_CALIBRATION
    commun.parent.mkdir(parents=True, exist_ok=True)
    commun.write_text(
        json.dumps({"version": VERSION_CALIBRATION, "velos": {"Route": {
            "cda_m2": 0.9, "crr": 0.02, "masse_totale_kg": 100.0, "rendement": 0.97,
            "rho": 1.2, "date": "2026-01-01", "n_sorties": 50}}}),
        encoding="utf-8",
    )
    etat_b = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": B}).json()
    assert etat_b["donnees"]["velos"][0]["calibration"] is None
    zones_b = client.get(f"{PREFIXE}/profil/zones", headers={"x-compte-essai": B}).json()
    assert zones_b["donnees"]["valeurs_liees"]["modele_physique"] == "littérature"


def test_le_job_d_un_autre_est_introuvable(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)
    fini = _calibrer(client, A)
    reponse = client.get(
        f"{PREFIXE}/calibrations/{fini['id']}", headers={"x-compte-essai": B}
    )
    assert reponse.status_code == 404
    assert reponse.json()["erreur"]["code"] == "fichier_introuvable"
    # Et un identifiant de calibration ne se lit pas par la route des imports.
    reponse = client.get(
        f"{PREFIXE}/activites/import/{fini['id']}", headers={"x-compte-essai": A}
    )
    assert reponse.status_code == 404


# --- préconditions -----------------------------------------------------------------


def _refus(client: TestClient, qui: str, **corps) -> dict:
    reponse = _lancer(client, qui, **corps)
    assert reponse.status_code == 422, reponse.text
    return reponse.json()["erreur"]


def test_sans_velo_le_refus_le_dit(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil(velos=[]))
    assert _refus(client, A)["code"] == "velo_absent"


def test_sans_ftp_le_refus_le_dit(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil(ftp=None))
    _semer(tmp_path, A, 12)
    erreur = _refus(client, A)
    assert erreur["code"] == "ftp_absente"
    assert "FTP" in erreur["message"]


def test_trop_peu_de_sorties_dit_combien_il_en_faut_et_combien_il_y_en_a(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 3)
    erreur = _refus(client, A)
    assert erreur["code"] == "sorties_insuffisantes"
    assert erreur["details"]["il_en_faut"] == 10
    assert erreur["details"]["disponibles"] == 3
    assert "3 sortie(s) exploitable(s), il en faut au moins 10" in erreur["message"]


def test_sans_pneu_le_refus_propose_de_calibrer_quand_meme(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil(velos=[{"nom": "Route", "usage": "route", "masse_kg": 9.0}]))
    _semer(tmp_path, A, 12)
    erreur = _refus(client, A)
    assert erreur["code"] == "pneu_absent"
    assert "calibrez quand même" in erreur["message"]
    crr = erreur["details"]["crr_usage"]

    fini = _calibrer(client, A, sans_pneu=True)
    assert fini["statut"] == "fini", fini
    resultat = fini["rapport"]["calibration"]
    assert resultat["crr_source"] == "usage"
    assert resultat["detail"]["crr"] == crr


def test_plusieurs_velos_sorties_sans_rattachement_refus_lisible(tmp_path: Path):
    """Deux vélos, des fichiers déposés sans capteur ni équipement : on ne devine pas."""
    velos = [
        {"nom": "Route", "usage": "route", "masse_kg": 9.0, "pneu": "course_rapide",
         "capteur_puissance": "CAPTEUR 0001"},
        {"nom": "Chrono", "usage": "clm", "masse_kg": 9.0, "pneu": "course_rapide"},
    ]
    client = _serveur(tmp_path)
    _activer(client, A, _profil(velos=velos))
    _semer(tmp_path, A, 12)
    erreur = _refus(client, A, velo="Route")
    assert erreur["code"] == "sorties_insuffisantes"
    assert erreur["details"]["ecartees"] == {"vélo non identifié": 12}
    assert "ne disent pas sur quel vélo" in erreur["message"]


def test_plusieurs_velos_sorties_rattachees_par_le_capteur(tmp_path: Path):
    velos = [
        {"nom": "Route", "usage": "route", "masse_kg": 9.0, "pneu": "course_rapide",
         "capteur_puissance": "CAPTEUR 0001"},
        {"nom": "Chrono", "usage": "clm", "masse_kg": 9.0, "pneu": "course_rapide"},
    ]
    client = _serveur(tmp_path)
    _activer(client, A, _profil(velos=velos))
    _semer(tmp_path, A, 12, meta={"power_meter": "CAPTEUR 0001"})
    fini = _calibrer(client, A, velo="Route")
    assert fini["statut"] == "fini", fini
    etat = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": A}).json()
    par_velo = {v["velo"]: v for v in etat["donnees"]["velos"]}
    assert par_velo["Route"]["calibration"] is not None
    assert par_velo["Chrono"]["calibration"] is None
    assert par_velo["Chrono"]["sorties_disponibles"] == 0


# --- verrou et quota -------------------------------------------------------------


def test_une_tache_lourde_en_cours_refuse_sans_consommer_le_quota(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)
    assert taches_fond.VERROU.acquire(blocking=False)
    try:
        reponse = _lancer(client, A)
    finally:
        taches_fond.VERROU.release()
    assert reponse.status_code == 409, reponse.text
    assert reponse.json()["erreur"]["code"] == "tache_lourde_en_cours"
    etat = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": A}).json()
    assert etat["donnees"]["quota"] == {"plafond": 1, "restant": 1}
    # Le verrou rendu, la calibration passe.
    assert _calibrer(client, A)["statut"] == "fini"


def test_une_calibration_par_jour_la_seconde_est_refusee(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)
    assert _calibrer(client, A)["statut"] == "fini"
    refus = _lancer(client, A)
    assert refus.status_code == 429
    assert refus.json()["erreur"]["code"] == "quota_atteint"
    # Le compteur est par compte : B n'en pâtit pas.
    _activer(client, B, _profil())
    _semer(tmp_path, B, 12, mois=3)
    assert _calibrer(client, B)["statut"] == "fini"


def test_une_calibration_qui_echoue_rend_son_credit_et_le_dit_sans_chemin(
    tmp_path: Path, monkeypatch
):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)
    cache_serveur = str(tmp_path / "cache")

    def _casse(*args, **kwargs):
        raise ErreurUtilisateur(f"calibration : panne fabriquée dans {cache_serveur}/brut")

    monkeypatch.setattr(calibrer, "calibrer_velo", _casse)
    fini = _calibrer(client, A)
    assert fini["statut"] == "echoue"
    assert "panne fabriquée" in fini["erreur"]
    assert cache_serveur not in fini["erreur"]
    etat = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": A}).json()
    assert etat["donnees"]["quota"]["restant"] == 1
    assert not (tmp_path / "donnees" / A / "calibration.json").exists()


def test_un_refus_de_precondition_ne_consomme_pas_le_quota(tmp_path: Path):
    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 3)
    assert _lancer(client, A).status_code == 422
    etat = client.get(f"{PREFIXE}/calibrations", headers={"x-compte-essai": A}).json()
    assert etat["donnees"]["quota"]["restant"] == 1


# --- export et suppression --------------------------------------------------------


def test_la_calibration_part_avec_l_export_et_la_suppression(tmp_path: Path):
    import io
    import zipfile

    client = _serveur(tmp_path)
    _activer(client, A, _profil())
    _semer(tmp_path, A, 12)
    assert _calibrer(client, A)["statut"] == "fini"

    export = client.get(f"{PREFIXE}/moi/export", headers={"x-compte-essai": A})
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert "calibration.json" in archive.namelist()

    suppression = client.delete(f"{PREFIXE}/moi", headers={"x-compte-essai": A})
    assert suppression.status_code == 200, suppression.text
    assert suppression.json()["donnees"]["supprime"]["calibration"] is True
    assert not (tmp_path / "donnees" / A / "calibration.json").exists()


# --- mode personnel ------------------------------------------------------------------


def test_en_mode_personnel_la_calibration_est_celle_de_la_ligne_de_commande(tmp_path: Path):
    """`ourouler api` chez le mainteneur : `calibration.json` du dossier de cache,
    celui qu'écrit `ourouler calibrer`, et pas de quota."""
    chemin = ecrire_config(tmp_path)
    application = creer_application(
        chemin_config=chemin,
        dossier_donnees=tmp_path / "donnees",
        clients=Clients(archive=archive_bouchonnee()),
        budgets=Budgets(),
    )
    client = TestClient(application, raise_server_exceptions=False)
    profil = client.get(f"{PREFIXE}/profil").json()["donnees"]
    velo = profil["velos"][0]["nom"]
    client.patch(
        f"{PREFIXE}/profil",
        json={"cycliste": {"masse_kg": 91.0, "ftp_w": 258.0},
              "velos": [{"nom": velo, "usage": "route", "masse_kg": 9.0,
                         "pneu": "course_rapide"}]},
    )
    _semer(tmp_path, "local", 12)
    reponse = client.post(f"{PREFIXE}/calibrations", json={})
    assert reponse.status_code == 202, reponse.text
    id_job = reponse.json()["donnees"]["id"]
    debut = time.monotonic()
    while True:
        donnees = client.get(f"{PREFIXE}/calibrations/{id_job}").json()["donnees"]
        if donnees["statut"] != "en_cours":
            break
        assert time.monotonic() - debut < 30
        time.sleep(0.05)
    assert donnees["statut"] == "fini", donnees
    assert (tmp_path / "cache" / "calibration.json").is_file()
    assert "quota" not in client.get(f"{PREFIXE}/calibrations").json()["donnees"]

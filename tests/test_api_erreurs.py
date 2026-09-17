"""La forme des pannes, et le verrou qui rend l'adaptateur sûr (lot F1).

`tests/test_api.py` vérifie les pannes de bout en bout, à travers de vraies
requêtes ; ici, on vérifie la traduction elle-même, cas par cas, avec les
messages **exacts** que les connecteurs du projet écrivent. Les deux
ensemble : le classement est juste, et il est branché.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

#: **Sans l'extra `api`, ce module se saute au lieu de casser la collecte.**
#: `uv sync && uv run pytest` sur un dépôt fraîchement cloné n'installe pas
#: FastAPI (extra `api`) : sans cette ligne, l'import ci-dessous levait une
#: erreur de collecte, et le contributeur voyait la suite échouer au lieu de
#: voir des tests ignorés. `uv sync --all-extras` les rend.
pytest.importorskip("fastapi", reason="extra « api » absent — uv sync --all-extras")

from test_api import moteur_meteo, serveur
from test_seance_intervals import CLE

from ourouler.api import adaptateur
from ourouler.api.erreurs import ErreurApi, assainir, classer
from ourouler.erreurs import (
    ErreurConnecteur,
    ErreurHorsDomaine,
    ErreurLecture,
    ErreurUtilisateur,
)


@pytest.mark.parametrize(
    ("exception", "code", "service"),
    [
        (
            ErreurConnecteur("BRouter : HTTP 502 sur https://exemple.test"),
            "brouter_indisponible",
            "brouter",
        ),
        (
            ErreurConnecteur("Open-Meteo : HTTP 503 sur https://exemple.test"),
            "meteo_indisponible",
            "openmeteo",
        ),
        (
            ErreurConnecteur(
                "Intervals.icu événements : HTTP 401 — clé d'API refusée, vérifier "
                "[intervals] api_key et athlete_id"
            ),
            "intervals_refuse",
            "intervals",
        ),
        (
            ErreurConnecteur("Intervals.icu événements : HTTP 500 — panne côté Intervals.icu"),
            "intervals_indisponible",
            "intervals",
        ),
        (ErreurHorsDomaine("Open-Meteo : hors domaine"), "meteo_hors_domaine", "openmeteo"),
        (ErreurConnecteur("BAN : adresse vide"), "geocodage_indisponible", "ban"),
        (
            ErreurConnecteur("boucle : aucune boucle bornée trouvée autour de N pour 60 km"),
            "aucune_boucle",
            None,
        ),
        (
            ErreurConnecteur("sortie : aucune boucle bornée trouvée (N) pour 60 km"),
            "aucune_boucle",
            None,
        ),
        (
            ErreurUtilisateur("sortie : la séance « 4x8 » ne tient sur aucune des 2 boucle(s)"),
            "aucune_boucle",
            None,
        ),
        (ErreurLecture("seance.zwo : XML illisible"), "fichier_illisible", None),
        (ErreurUtilisateur("--direction 'nord-est' : azimut illisible"), "requete_invalide", None),
        (ValueError("un bug"), "erreur_interne", None),
    ],
)
def test_chaque_panne_previsible_a_son_code(exception: Exception, code: str, service: str | None):
    erreur = classer(exception)
    assert (erreur.code, erreur.service) == (code, service)
    assert erreur.message, "une panne sans message n'est pas affichable"
    assert erreur.charge()["erreur"]["code"] == code


def test_les_statuts_separent_la_faute_du_client_de_celle_du_service():
    assert classer(ErreurUtilisateur("--distance -5 : …")).statut == 400
    assert classer(ErreurUtilisateur("sortie : la séance …")).statut == 422
    assert classer(ErreurConnecteur("BRouter : HTTP 502")).statut == 502
    assert classer(ValueError("bug")).statut == 500


def test_un_bug_ne_laisse_filer_ni_trace_ni_detail():
    erreur = classer(RuntimeError("index hors bornes dans un tableau interne"))
    assert erreur.statut == 500
    assert "index hors bornes" not in erreur.message


def test_une_cle_ne_sort_jamais_dans_un_message_d_erreur():
    """Ceinture et bretelles : le cœur promet de n'en mettre aucune, on vérifie."""
    erreur = classer(ErreurConnecteur(f"Intervals.icu : requête avec {CLE} refusée"), secrets=[CLE])
    assert CLE not in erreur.message
    assert "***" in erreur.message


def test_un_secret_trop_court_ne_massacre_pas_le_message():
    """Masquer une chaîne vide ou de deux lettres détruirait le message utile."""
    assert assainir("BRouter : HTTP 502", ["", "ab"]) == "BRouter : HTTP 502"


def test_une_erreur_deja_traduite_n_est_pas_reclassee():
    deja = ErreurApi(code="calcul_en_cours", message="occupé", statut=409)
    assert classer(deja) is deja


def test_un_serveur_deja_occupe_le_dit_au_lieu_de_faire_attendre(tmp_path: Path, monkeypatch):
    """Le front a un écran pour ça ; une requête qui pend n'en a pas."""
    monkeypatch.setattr(adaptateur, "DELAI_ATTENTE_S", 0.05)
    client = serveur(tmp_path, meteo=moteur_meteo())
    with adaptateur._VERROU:  # un calcul est en cours, tenu par un autre fil
        reponse = client.get("/api/v1/meteo")
    assert reponse.status_code == 409
    erreur = reponse.json()["erreur"]
    assert erreur["code"] == "calcul_en_cours"
    assert "secondes" in erreur["message"]
    # Et le verrou est bien rendu : la requête suivante passe.
    assert client.get("/api/v1/meteo").status_code == 200


def test_une_panne_pendant_le_calcul_rend_le_verrou(tmp_path: Path):
    """Un verrou qui fuit sur exception gèlerait le serveur jusqu'au redémarrage."""
    client = serveur(tmp_path, meteo=moteur_meteo(en_panne=True))
    assert client.get("/api/v1/meteo").status_code == 502
    assert not adaptateur._VERROU.locked()


def test_deux_requetes_simultanees_ne_melangent_pas_leurs_reponses(tmp_path: Path):
    """La sortie standard est un objet de processus, pas de fil d'exécution :
    sans le verrou de l'adaptateur, les deux JSON se seraient mêlés. C'est le
    prix, assumé, de passer par le chemin exact de la ligne de commande."""
    client = serveur(tmp_path, meteo=moteur_meteo())
    reponses: list[dict] = []

    def appeler() -> None:
        reponses.append(client.get("/api/v1/meteo").json())

    fils = [threading.Thread(target=appeler) for _ in range(4)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert len(reponses) == 4
    for charge in reponses:
        assert charge["donnees"]["depart"]["nom"] == "Point zéro"
        assert len({c["direction"] for c in charge["donnees"]["cellules"]} - {"ici"}) == 8

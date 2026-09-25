"""Tests du connecteur de géocodage (F0.2).

Aucun accès réseau : `httpx.MockTransport` intercepte tout. Les réponses
sont **fabriquées**, avec des adresses inventées (`tests/fixtures/geocodage/`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ourouler.connecteurs.geocodage import (
    USER_AGENT_NOMINATIM,
    Candidat,
    ClientBAN,
    ClientNominatim,
    ambiguite,
    chercher_adresse,
)
from ourouler.noyau.erreurs import ErreurConnecteur

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "geocodage"


def _charge(nom: str) -> Any:
    return json.loads((FIXTURES / nom).read_text(encoding="utf-8"))


def client_ban_repondant(charge: Any, code: int = 200) -> tuple[ClientBAN, list[httpx.Request]]:
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(code, json=charge)

    return ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire))), vues


def client_nominatim_repondant(charge: Any, code: int = 200) -> tuple[ClientNominatim, list[httpx.Request]]:
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(code, json=charge)

    return (
        ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire))),
        vues,
    )


# --- ClientBAN ---------------------------------------------------------------


def test_ban_rend_plusieurs_candidats_avec_leur_score():
    """Le point de conception du lot : une adresse ambiguë rend une liste, pas un choix."""
    client, vues = client_ban_repondant(_charge("ban_ambigu.json"))
    candidats = client.chercher("7 rue du if")
    assert len(candidats) == 2
    assert candidats[0] == Candidat(
        label="7 Rue du If 44999 Vallombreuse",
        latitude=0.123456,
        longitude=0.234567,
        score=0.83,
        source="ban",
        commune="Vallombreuse",
        code_postal="44999",
    )
    assert candidats[1].label == "7 Rue du If 62999 Hautbocage"
    assert vues[0].url.params["q"] == "7 rue du if"


def test_ban_adresse_introuvable_rend_une_liste_vide_pas_une_erreur():
    client, _ = client_ban_repondant(_charge("ban_vide.json"))
    assert client.chercher("adresse totalement introuvable") == []


def test_ban_limite_transmise_au_service():
    client, vues = client_ban_repondant(_charge("ban_vide.json"))
    client.chercher("x", limite=3)
    assert vues[0].url.params["limit"] == "3"


def test_ban_adresse_vide_refusee_sans_appel_reseau():
    client, vues = client_ban_repondant(_charge("ban_vide.json"))
    with pytest.raises(ErreurConnecteur):
        client.chercher("   ")
    assert vues == []


def test_ban_panne_http_leve_erreur_connecteur():
    client, _ = client_ban_repondant({"features": []}, code=503)
    with pytest.raises(ErreurConnecteur, match="503"):
        client.chercher("une adresse")


def test_ban_reponse_illisible_leve_erreur_connecteur():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pas du json")

    client = ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur):
        client.chercher("une adresse")


def test_ban_candidat_sans_label_leve_erreur_connecteur():
    charge = {"features": [{"geometry": {"coordinates": [0.0, 0.0]}, "properties": {}}]}
    client, _ = client_ban_repondant(charge)
    with pytest.raises(ErreurConnecteur):
        client.chercher("une adresse")


# --- ClientNominatim -----------------------------------------------------------


def test_nominatim_rend_un_candidat():
    client, vues = client_nominatim_repondant(_charge("nominatim_un_candidat.json"))
    candidats = client.chercher("14 elm hollow road")
    assert candidats == [
        Candidat(
            label="14, Elm Hollow Road, Rivermill, Testshire, ZZ9 9ZZ, Royaume-Uni",
            latitude=51.234567,
            longitude=-0.123456,
            score=0.42,
            source="nominatim",
            commune="Rivermill",
            code_postal="ZZ9 9ZZ",
        )
    ]
    assert vues[0].url.params["q"] == "14 elm hollow road"
    assert vues[0].url.params["format"] == "jsonv2"


def test_nominatim_envoie_toujours_un_user_agent_identifiant():
    """Politique d'usage Nominatim : le User-Agent par défaut d'une lib HTTP ne suffit pas."""
    client, vues = client_nominatim_repondant([])
    client.chercher("une adresse")
    assert vues[0].headers["user-agent"] == USER_AGENT_NOMINATIM


def test_nominatim_adresse_introuvable_rend_une_liste_vide():
    client, _ = client_nominatim_repondant([])
    assert client.chercher("adresse totalement introuvable") == []


def test_nominatim_panne_http_leve_erreur_connecteur():
    client, _ = client_nominatim_repondant([], code=500)
    with pytest.raises(ErreurConnecteur, match="500"):
        client.chercher("une adresse")


# --- chercher_adresse (orchestration BAN -> repli Nominatim) -------------------


def test_chercher_adresse_ne_consulte_pas_nominatim_si_la_ban_trouve():
    ban, _ = client_ban_repondant(_charge("ban_ambigu.json"))
    appels_nominatim: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels_nominatim.append(requete)
        return httpx.Response(200, json=[])

    nominatim = ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    candidats = chercher_adresse("7 rue du if", ban=ban, nominatim=nominatim)
    assert len(candidats) == 2
    assert appels_nominatim == []


def test_chercher_adresse_replie_sur_nominatim_si_la_ban_ne_trouve_rien():
    ban, _ = client_ban_repondant(_charge("ban_vide.json"))
    nominatim, vues_nominatim = client_nominatim_repondant(_charge("nominatim_un_candidat.json"))
    candidats = chercher_adresse("14 elm hollow road", ban=ban, nominatim=nominatim)
    assert len(candidats) == 1
    assert candidats[0].source == "nominatim"
    assert len(vues_nominatim) == 1


def test_chercher_adresse_rend_liste_vide_si_aucune_des_deux_sources_ne_trouve():
    ban, _ = client_ban_repondant(_charge("ban_vide.json"))
    nominatim, _ = client_nominatim_repondant([])
    assert chercher_adresse("adresse totalement introuvable", ban=ban, nominatim=nominatim) == []


def test_chercher_adresse_ne_masque_pas_une_panne_de_la_ban_par_un_repli():
    """Une panne n'est pas une adresse introuvable (règle absolue 5) : Nominatim n'est pas appelé."""
    ban, _ = client_ban_repondant({}, code=503)
    appels_nominatim: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels_nominatim.append(requete)
        return httpx.Response(200, json=[])

    nominatim = ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur, match="503"):
        chercher_adresse("une adresse", ban=ban, nominatim=nominatim)
    assert appels_nominatim == []


def test_chercher_adresse_ne_masque_pas_une_panne_du_repli():
    ban, _ = client_ban_repondant(_charge("ban_vide.json"))
    nominatim, _ = client_nominatim_repondant([], code=500)
    with pytest.raises(ErreurConnecteur, match="500"):
        chercher_adresse("une adresse", ban=ban, nominatim=nominatim)


# --- ambiguite() : la règle sans seuil (Q34) ------------------------------------
#
# Mesuré le 17/09/2026 sur la vraie BAN, quinze requêtes, lieux publics
# uniquement : neuf adresses complètes rendent toutes **une** commune, six
# adresses sans commune en rendent **cinq** à chaque fois. Les écarts de score,
# eux, se recouvrent : 0,0020 quand la réponse est juste, 0,0016 à 0,0024 quand
# elle est arbitraire. Ces tests fixent la règle qui en découle.


def candidat(label: str, commune: str | None, code_postal: str | None = None, score: float = 0.9):
    return Candidat(
        label=label, latitude=0.1, longitude=0.2, score=score, source="ban",
        commune=commune, code_postal=code_postal,
    )


def test_ambiguite_liste_vide_n_est_pas_une_ambiguite():
    """Une absence de réponse a déjà son message (« adresse introuvable »)."""
    assert ambiguite([]) is None


def test_ambiguite_un_seul_candidat_avec_sa_commune_est_franc():
    assert ambiguite([candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999")]) is None


def test_ambiguite_plusieurs_candidats_dans_la_meme_commune_est_franc():
    """Le cas normal d'une adresse complète : le numéro, puis la rue. Pas une ambiguïté."""
    assert (
        ambiguite(
            [
                candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999", 0.98),
                candidat("Rue du If 44999 Vallombreuse", "Vallombreuse", "44999", 0.71),
            ]
        )
        is None
    )


def test_ambiguite_deux_communes_differentes_est_refusee():
    trouble = ambiguite(
        [
            candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999", 0.9774),
            candidat("7 Rue du If 62999 Hautbocage", "Hautbocage", "62999", 0.9773),
        ]
    )
    assert trouble is not None
    assert trouble.motif == "communes_differentes"
    assert trouble.communes == ("Vallombreuse", "Hautbocage")
    assert "2 communes possibles" in trouble.phrase


def test_ambiguite_ne_regarde_jamais_l_ecart_de_score():
    """Le point de la décision Q34 : aucun seuil.

    Deux candidats séparés de 0,27 — un écart franc — restent refusés s'ils sont
    dans deux communes ; deux candidats séparés de 0,0001 passent s'ils sont
    dans la même. C'est exactement l'inverse de ce qu'un seuil ferait.
    """
    ecart_franc = ambiguite(
        [
            candidat("A", "Vallombreuse", "44999", 0.98),
            candidat("B", "Hautbocage", "62999", 0.71),
        ]
    )
    assert ecart_franc is not None, "un écart de score franc ne rachète pas deux communes"

    ecart_infime = ambiguite(
        [
            candidat("A", "Vallombreuse", "44999", 0.9774),
            candidat("B", "Vallombreuse", "44999", 0.9773),
        ]
    )
    assert ecart_infime is None, "un écart infime dans une seule commune n'est pas une ambiguïté"


def test_ambiguite_commune_absente_est_refusee():
    trouble = ambiguite([candidat("Lieu-dit du If", None)])
    assert trouble is not None
    assert trouble.motif == "commune_absente"
    assert "ne rattache pas" in trouble.phrase


def test_ambiguite_une_seule_commune_manquante_suffit_a_refuser():
    """Un candidat sans commune parmi d'autres empêche de vérifier qu'ils sont tous au même endroit."""
    trouble = ambiguite(
        [
            candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999"),
            candidat("Lieu-dit du If", None),
        ]
    )
    assert trouble is not None
    assert trouble.motif == "commune_absente"


def test_ambiguite_ignore_la_casse_et_les_espaces_du_nom_de_commune():
    """« SAINT-… » et « Saint-… » sont la même commune : un refus là serait du bruit."""
    assert (
        ambiguite(
            [
                candidat("A", "Vallombreuse", "44999"),
                candidat("B", "VALLOMBREUSE", "44999"),
                candidat("C", "Vallombreuse ", "44999"),
            ]
        )
        is None
    )


def test_ambiguite_separe_deux_communes_homonymes_par_leur_code_postal():
    """Deux communes françaises portent le même nom : le code postal les distingue."""
    trouble = ambiguite(
        [
            candidat("A", "Vallombreuse", "44999"),
            candidat("B", "Vallombreuse", "62999"),
        ]
    )
    assert trouble is not None
    assert trouble.motif == "communes_differentes"


def test_nominatim_demande_le_detail_d_adresse_sinon_la_commune_n_existe_pas():
    """Sans `addressdetails=1`, `ambiguite()` refuserait **tout** repli Nominatim."""
    client, vues = client_nominatim_repondant([])
    client.chercher("une adresse")
    assert vues[0].url.params["addressdetails"] == "1"


def test_nominatim_sans_niveau_de_commune_rend_un_candidat_sans_commune():
    """En pleine campagne ou hors de France, aucun niveau ne donne la commune — et on le dit."""
    client, _ = client_nominatim_repondant(
        [
            {
                "lat": "51.0",
                "lon": "-0.1",
                "display_name": "Un point au milieu de nulle part",
                "importance": 0.1,
                "address": {"country": "Testland", "country_code": "zz"},
            }
        ]
    )
    candidats = client.chercher("nulle part")
    assert candidats[0].commune is None
    assert ambiguite(candidats) is not None

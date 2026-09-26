"""Tests de la sous-commande `ourouler geocoder` (F0.2).

Clients injectés : aucun accès réseau, aucune adresse réelle.
"""

from __future__ import annotations

import argparse
import json

import httpx
import pytest

from ourouler.cli import construire_parseur
from ourouler.commandes.geocoder import executer_depuis_namespace as executer
from ourouler.config import Config, depuis_dict
from ourouler.connecteurs.geocodage import Candidat, ClientBAN, ClientNominatim
from ourouler.geocodage.commande import rendre_json, rendre_texte

CONFIG_BRUTE = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
}


def config_de_test() -> Config:
    return depuis_dict(CONFIG_BRUTE)


def args(**champs) -> argparse.Namespace:
    defauts = {"adresse": "une adresse", "max": None, "json": False}
    return argparse.Namespace(**{**defauts, **champs})


def client_ban_avec(candidats: list[Candidat]) -> ClientBAN:
    """Un `ClientBAN` dont la réponse est fabriquée directement à partir de `Candidat`."""
    charge = {
        "features": [
            {
                "geometry": {"coordinates": [c.longitude, c.latitude]},
                "properties": {
                    "label": c.label,
                    "score": c.score,
                    "city": c.commune,
                    "postcode": c.code_postal,
                },
            }
            for c in candidats
        ]
    }

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=charge)

    return ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def client_nominatim_vide() -> ClientNominatim:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    return ClientNominatim(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


# --- CLI : le parseur accepte la commande -------------------------------------


def test_ourouler_geocoder_est_dans_l_aide():
    parseur = construire_parseur()
    sous = next(a for a in parseur._actions if a.dest == "commande")
    assert "geocoder" in sous.choices


def test_ourouler_geocoder_parse_adresse_et_max():
    parseur = construire_parseur()
    lus = parseur.parse_args(["geocoder", "7 rue du if", "--max", "3", "--json"])
    assert lus.adresse == "7 rue du if"
    assert lus.max == 3
    assert lus.json is True


# --- executer() ----------------------------------------------------------------


def test_executer_texte_liste_les_candidats(capsys):
    ban = client_ban_avec(
        [
            Candidat("7 Rue du If 44999 Vallombreuse", 0.1, 0.2, 0.83, "ban"),
            Candidat("7 Rue du If 62999 Hautbocage", 0.9, 0.3, 0.61, "ban"),
        ]
    )
    code = executer(args(adresse="7 rue du if"), config_de_test(), ban=ban)
    assert code == 0
    sortie = capsys.readouterr().out
    assert "2 candidat(s)" in sortie
    assert "Vallombreuse" in sortie
    assert "Hautbocage" in sortie
    assert "0.83" in sortie


def test_executer_texte_adresse_introuvable_message_clair(capsys):
    ban = client_ban_avec([])
    nominatim = client_nominatim_vide()
    code = executer(args(adresse="lieu qui n'existe pas"), config_de_test(), ban=ban, nominatim=nominatim)
    assert code == 0
    sortie = capsys.readouterr().out
    assert "aucune adresse trouvée" in sortie
    assert "lieu qui n'existe pas" in sortie


def test_executer_json(capsys):
    ban = client_ban_avec(
        [Candidat("7 Rue du If 44999 Vallombreuse", 0.1, 0.2, 0.83, "ban", "Vallombreuse", "44999")]
    )
    code = executer(args(adresse="7 rue du if", json=True), config_de_test(), ban=ban)
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge == {
        "adresse": "7 rue du if",
        "candidats": [
            {
                "label": "7 Rue du If 44999 Vallombreuse",
                "latitude": 0.1,
                "longitude": 0.2,
                "score": 0.83,
                "source": "ban",
                "commune": "Vallombreuse",
                "code_postal": "44999",
            }
        ],
        "ambigu": False,
        "motif_ambiguite": None,
    }


def test_executer_max_transmis_au_connecteur():
    vues: list[str] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete.url.params["limit"])
        return httpx.Response(200, json={"features": []})

    ban = ClientBAN(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    nominatim = client_nominatim_vide()
    executer(args(adresse="x", max=2), config_de_test(), ban=ban, nominatim=nominatim)
    assert vues == ["2"]


# --- rendu pur -------------------------------------------------------------------


def test_rendre_texte_liste_vide():
    assert rendre_texte("adresse fantôme", []) == "aucune adresse trouvée pour « adresse fantôme »"


def test_rendre_json_liste_vide():
    assert rendre_json("adresse fantôme", []) == {
        "adresse": "adresse fantôme",
        "candidats": [],
        "ambigu": False,
        "motif_ambiguite": None,
    }


@pytest.mark.parametrize("json_actif", [True, False])
def test_executer_ne_leve_jamais_pour_une_liste_vide(json_actif, capsys):
    """Une adresse introuvable n'est pas une erreur technique (contrat du lot)."""
    ban = client_ban_avec([])
    nominatim = client_nominatim_vide()
    code = executer(args(adresse="x", json=json_actif), config_de_test(), ban=ban, nominatim=nominatim)
    assert code == 0

"""Tests du connecteur BRouter (L2.1).

Aucun accès réseau : `httpx.MockTransport` intercepte tout. La réponse de
référence est **fabriquée** (`tests/fixtures/brouter/boucle_fabriquee.json`,
30 points et 6 messages autour du point fictif (0.0, 0.0)) ; elle respecte
le format relevé sur le serveur réel — coordonnées de messages en
microdegrés entiers passés en chaînes, retombant exactement sur un point de
la géométrie.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from ourouler.config import ParametresBrouter
from ourouler.connecteurs.brouter import MODE_BOUCLE, ClientBrouter
from ourouler.erreurs import ErreurConnecteur

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "brouter"
MOT_DE_PASSE = "secret-de-test-a-ne-jamais-imprimer"
PARAMS = ParametresBrouter(
    url="https://brouter.exemple.test",
    utilisateur="utilisateur-test",
    mot_de_passe=MOT_DE_PASSE,
    profil="fastbike",
    timeout_s=5.0,
)


def _generateur():
    """Charge `tests/fixtures/generer_brouter.py` par chemin (hors paquet)."""
    if "generer_brouter" in sys.modules:
        return sys.modules["generer_brouter"]
    chemin = FIXTURES.parent / "generer_brouter.py"
    spec = importlib.util.spec_from_file_location("generer_brouter", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generer_brouter"] = module
    spec.loader.exec_module(module)
    return module


def reponse_fabriquee() -> dict:
    """La réponse de référence, régénérée si la fixture versionnée manque."""
    chemin = FIXTURES / "boucle_fabriquee.json"
    if not chemin.is_file():
        _generateur().generer(FIXTURES)
    return json.loads(chemin.read_text(encoding="utf-8"))


def client_repondant(charge: Any, code: int = 200) -> tuple[ClientBrouter, list[httpx.Request]]:
    """Un client dont tout le trafic passe par un `MockTransport` : jamais le réseau."""
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        if isinstance(charge, (bytes, str)):
            return httpx.Response(code, content=charge)
        return httpx.Response(code, json=charge)

    return (
        ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))),
        vues,
    )


def client_fabrique() -> tuple[ClientBrouter, list[httpx.Request]]:
    return client_repondant(reponse_fabriquee())


# --- paramètres envoyés -------------------------------------------------------


def test_itineraire_convertit_lat_lon_en_lon_lat():
    client, vues = client_fabrique()
    client.itineraire([(0.01, 0.02), (0.03, 0.04)])
    p = vues[0].url.params
    assert p["lonlats"] == "0.020000,0.010000|0.040000,0.030000"
    assert p["profile"] == "fastbike"
    assert p["format"] == "geojson"
    assert p["alternativeidx"] == "0"
    assert vues[0].url.path == "/brouter"


def test_boucle_envoie_le_mode_moteur_entier_et_ses_parametres():
    client, vues = client_fabrique()
    client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=8000, nb_points=5)
    p = vues[0].url.params
    assert p["engineMode"] == str(MODE_BOUCLE) == "4"
    assert p["lonlats"] == "0.000000,0.000000"
    assert p["roundTripStartDirection"] == "45"
    assert p["roundTripDistance"] == "8000"
    assert p["roundTripPoints"] == "5"
    assert "roundTripDirectionAdd" not in p


def test_boucle_normalise_l_azimut_et_transmet_l_ecart():
    client, vues = client_fabrique()
    client.boucle((0.0, 0.0), azimut_deg=395.0, rayon_m=8000, ecart_deg=30)
    p = vues[0].url.params
    assert p["roundTripStartDirection"] == "35"
    assert p["roundTripDirectionAdd"] == "30"


def test_le_profil_de_l_appel_prime_sur_celui_de_la_configuration():
    client, vues = client_fabrique()
    client.itineraire([(0.0, 0.0), (0.01, 0.0)], profil="gravel")
    assert vues[0].url.params["profile"] == "gravel"


def test_la_boucle_demande_le_recalage_des_points_de_passage():
    """Contrat §1 : les paramètres de `correct_misplaced_via_points` partent avec la demande.

    Mesuré sur le serveur du mainteneur : acceptés et **sans effet** (voir
    `CORRECTION_POINTS_DE_PASSAGE`). Le test vérifie qu'on les envoie, pas
    qu'ils servent — c'est `boucle/antennes.py` qui corrige les crochets.
    """
    client, vues = client_fabrique()
    client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=8000)
    p = vues[0].url.params
    assert p["profile:correct_misplaced_via_points"] == "1"
    assert p["profile:correct_misplaced_via_points_distance"] == "40"


def test_un_itineraire_simple_ne_demande_pas_le_recalage():
    """Un A→B n'a que les points de passage donnés par l'appelant : rien à recaler."""
    client, vues = client_fabrique()
    client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert "profile:correct_misplaced_via_points" not in vues[0].url.params


def test_l_authentification_basique_est_envoyee():
    client, vues = client_fabrique()
    client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert vues[0].headers["authorization"].startswith("Basic ")


# --- lecture du GeoJSON -------------------------------------------------------


def test_trace_lue_depuis_la_reponse_fabriquee():
    client, _ = client_fabrique()
    trace = client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=1500)
    assert len(trace.points) == 30
    assert trace.distance_m == pytest.approx(7543, abs=1)
    assert trace.denivele_m == pytest.approx(40, abs=1)
    assert trace.temps_moteur_s == pytest.approx(1078, abs=1)
    assert trace.meta["moteur"] == "brouter"
    assert trace.meta["profil"] == "fastbike"
    assert trace.meta["azimut_deg"] == 45
    assert trace.meta["rayon_m"] == 1500.0
    assert trace.bornee(), "la fixture est une boucle fermée"


def test_les_points_portent_altitude_et_distance_cumulee_croissante():
    client, _ = client_fabrique()
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert trace.points[0].dist_m == 0.0
    assert all(a.dist_m <= b.dist_m for a, b in zip(trace.points, trace.points[1:], strict=False))
    assert all(p.alt_m is not None for p in trace.points)
    # La distance cumulée haversine recoupe le `track-length` du moteur.
    assert trace.points[-1].dist_m == pytest.approx(trace.distance_m, rel=0.01)


def test_les_segments_suivent_les_messages_et_couvrent_toute_la_trace():
    client, _ = client_fabrique()
    trace = client.boucle((0.0, 0.0), azimut_deg=0, rayon_m=1500)
    assert len(trace.segments) == 6
    assert [s.debut_idx for s in trace.segments] == [0, 5, 10, 15, 20, 25]
    assert [s.fin_idx for s in trace.segments] == [5, 10, 15, 20, 25, 29]
    assert sum(s.longueur_m for s in trace.segments) == pytest.approx(trace.distance_m, abs=1)


def test_le_dernier_message_d_une_boucle_ne_revient_pas_au_point_zero():
    """Le tronçon final cite le point de départ, qui est aussi l'arrivée.

    Une recherche par valeur seule le rattacherait à l'indice 0 et
    inverserait le dernier tronçon : le rattachement doit avancer.
    """
    client, _ = client_fabrique()
    trace = client.boucle((0.0, 0.0), azimut_deg=0, rayon_m=1500)
    dernier = trace.segments[-1]
    assert dernier.fin_idx == len(trace.points) - 1
    assert dernier.fin_idx > dernier.debut_idx


def test_les_tags_de_chemin_sont_decoupes():
    client, _ = client_fabrique()
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert trace.segments[0].tags == {"highway": "residential", "surface": "asphalt"}
    assert trace.segments[3].tags["surface"] == "gravel"
    assert trace.segments[5].tags == {"highway": "primary", "surface": "asphalt", "lanes": "2"}


def test_coordonnees_de_messages_en_degres_acceptees_aussi():
    """Le serveur mesuré renvoie des microdegrés ; des degrés doivent marcher pareil."""
    charge = reponse_fabriquee()
    messages = charge["features"][0]["properties"]["messages"]
    for ligne in messages[1:]:
        ligne[0] = f"{float(ligne[0]) / 1e6:.6f}"
        ligne[1] = f"{float(ligne[1]) / 1e6:.6f}"
    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert [s.fin_idx for s in trace.segments] == [5, 10, 15, 20, 25, 29]


def test_une_coordonnee_de_message_pres_du_meridien_0_reste_des_microdegres():
    """« 570 » microdegrés vaut 0,00057°, pas 570 degrés (point 3 de la relecture).

    La bande d'ambiguïté |coordonnée| ≤ 0,001° fait ±111 m de part et d'autre
    de l'équateur **et** du méridien de Greenwich — et toutes les fixtures du
    dépôt y vivent. Deviner l'unité valeur par valeur y voyait des degrés :
    le tronçon partait s'accrocher au point le plus proche d'une latitude
    impossible, c'est-à-dire n'importe lequel, sans le moindre message.
    """
    generateur = _generateur()
    points = generateur.trajectoire()
    dans_la_bande = [
        i
        for i, (lat, lon, _) in enumerate(points)
        if i > 1 and (0 < abs(lat) <= 0.001 or 0 < abs(lon) <= 0.001)
    ]
    assert dans_la_bande, "la fixture doit frôler un axe pour que le test ait un sens"
    cible = dans_la_bande[0]

    charge = generateur.reponse_boucle(points)
    messages = charge["features"][0]["properties"]["messages"]
    lat, lon, _ = points[cible]
    messages[1][0] = str(round(lon * 1e6))
    messages[1][1] = str(round(lat * 1e6))
    assert min(abs(float(messages[1][0])), abs(float(messages[1][1]))) <= 1000.0

    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert trace.segments[0].fin_idx == cible, (
        f"tronçon rattaché au point {trace.segments[0].fin_idx} au lieu de {cible} : "
        "une coordonnée sous 0,001° a été lue comme des degrés"
    )


def test_des_messages_sans_point_ou_s_accrocher_sont_comptes():
    """Point 14 de la relecture : ces lignes disparaissaient sans être comptées.

    Si le serveur envoie plus de messages que la géométrie ne porte de
    points, la boucle de rattachement s'arrête. `meta["messages_ignores"]`
    annonçait alors 0 alors que des tronçons avaient été perdus — exactement
    le contraire de l'intention affichée.
    """
    charge = reponse_fabriquee()
    proprietes = charge["features"][0]["properties"]
    entete, lignes = proprietes["messages"][0], proprietes["messages"][1:]
    # La géométrie est réduite à trois points : il n'y a plus de quoi accrocher
    # les six tronçons que les messages décrivent.
    geometrie = charge["features"][0]["geometry"]["coordinates"]
    charge["features"][0]["geometry"]["coordinates"] = geometrie[:3]
    proprietes["messages"] = [entete, *lignes]

    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    perdus = len(lignes) - len(trace.segments)
    assert perdus > 0, "le test n'a de sens que si des lignes sont bien perdues"
    assert trace.meta["messages_ignores"] == perdus, (
        f"{perdus} ligne(s) perdue(s), {trace.meta['messages_ignores']} comptée(s)"
    )
    assert trace.meta["messages_ignores_motifs"], "le motif doit être dit, pas seulement le compte"


def test_messages_sans_en_tete_lus_avec_l_ordre_de_colonnes_connu():
    charge = reponse_fabriquee()
    proprietes = charge["features"][0]["properties"]
    proprietes["messages"] = proprietes["messages"][1:]  # on retire l'en-tête
    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert len(trace.segments) == 6
    assert trace.segments[0].tags["highway"] == "residential"


def test_messages_absents_donnent_une_trace_sans_segment():
    charge = reponse_fabriquee()
    del charge["features"][0]["properties"]["messages"]
    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert trace.segments == []
    assert len(trace.points) == 30
    assert trace.distance_m > 0


def test_une_ligne_de_message_illisible_est_comptee_pas_avalee():
    charge = reponse_fabriquee()
    charge["features"][0]["properties"]["messages"][2] = ["pas", "un", "nombre"]
    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert len(trace.segments) == 5
    assert trace.meta["messages_ignores"] == 1
    assert trace.meta["messages_ignores_motifs"]


def test_distance_manquante_repliee_sur_la_distance_cumulee():
    charge = reponse_fabriquee()
    del charge["features"][0]["properties"]["track-length"]
    client, _ = client_repondant(charge)
    trace = client.itineraire([(0.0, 0.0), (0.01, 0.0)])
    assert trace.distance_m == pytest.approx(trace.points[-1].dist_m)


# --- erreurs ------------------------------------------------------------------


def test_url_vide_refusee_a_la_construction():
    with pytest.raises(ErreurConnecteur, match="url"):
        ClientBrouter(ParametresBrouter())


def test_moins_de_deux_points_refuse():
    client, vues = client_fabrique()
    with pytest.raises(ErreurConnecteur, match="deux points"):
        client.itineraire([(0.0, 0.0)])
    assert vues == [], "rien ne part sur le réseau avant la validation"


def test_rayon_nul_refuse():
    client, _ = client_fabrique()
    with pytest.raises(ErreurConnecteur, match="rayon"):
        client.boucle((0.0, 0.0), azimut_deg=0, rayon_m=0)


def test_500_sans_corps_evoque_le_profil():
    """Mesuré sur le serveur réel : un profil absent donne un 500 sans corps."""
    client, _ = client_repondant(b"", code=500)
    with pytest.raises(ErreurConnecteur, match="profil inconnu"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)], profil="fastbike-lowtraffic")


def test_401_oriente_vers_les_identifiants():
    client, _ = client_repondant(b"", code=401)
    with pytest.raises(ErreurConnecteur, match="identifiants refus"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


def test_corps_vide_en_200():
    client, _ = client_repondant(b"", code=200)
    with pytest.raises(ErreurConnecteur, match="vide"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


def test_json_illisible():
    client, _ = client_repondant(b"<html>oups</html>")
    with pytest.raises(ErreurConnecteur, match="non-JSON"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


@pytest.mark.parametrize(
    "charge",
    [{}, {"type": "FeatureCollection", "features": []}, {"features": "pas une liste"}, []],
    ids=["sans features", "features vide", "features non liste", "racine liste"],
)
def test_reponse_sans_itineraire(charge):
    client, _ = client_repondant(charge)
    with pytest.raises(ErreurConnecteur):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


def test_geometrie_a_un_seul_point():
    charge = reponse_fabriquee()
    charge["features"][0]["geometry"]["coordinates"] = [[0.0, 0.0, 30.0]]
    client, _ = client_repondant(charge)
    with pytest.raises(ErreurConnecteur, match="au moins 2"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


def test_coordonnee_non_numerique():
    charge = reponse_fabriquee()
    charge["features"][0]["geometry"]["coordinates"][3] = ["nord", "ouest", 12]
    client, _ = client_repondant(charge)
    with pytest.raises(ErreurConnecteur, match="non numérique"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


def test_serveur_injoignable():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("délai dépassé")

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur, match="injoignable"):
        client.itineraire([(0.0, 0.0), (0.01, 0.0)])


# --- le mot de passe ne sort jamais -------------------------------------------


def gestionnaires_fautifs():
    """Toutes les façons connues d'échouer, pour vérifier chacune des erreurs."""
    return [
        (b"", 500),
        (b"", 401),
        (b"", 404),
        (b"<html>", 200),
        ({}, 200),
        (b"", 200),
    ]


@pytest.mark.parametrize("charge,code", gestionnaires_fautifs())
def test_le_mot_de_passe_n_apparait_dans_aucune_erreur(charge, code):
    client, _ = client_repondant(charge, code=code)
    with pytest.raises(ErreurConnecteur) as capture:
        client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=8000)
    message = str(capture.value)
    assert MOT_DE_PASSE not in message
    assert "utilisateur-test" not in message
    assert "brouter.exemple.test" in message, "l'URL, elle, peut s'afficher"


def test_le_mot_de_passe_n_apparait_ni_dans_le_repr_ni_dans_les_attributs():
    client, _ = client_fabrique()
    assert MOT_DE_PASSE not in repr(client)
    assert MOT_DE_PASSE not in repr(vars(client))
    assert not any(MOT_DE_PASSE == valeur for valeur in vars(client).values())


def test_le_mot_de_passe_n_apparait_pas_dans_le_repr_des_parametres():
    assert MOT_DE_PASSE not in repr(PARAMS)
    assert "***" in repr(PARAMS)


# --- la fixture versionnée est bien celle que produit le générateur -----------


def test_la_fixture_brouter_est_reproductible(tmp_path: Path):
    ecrits = _generateur().generer(tmp_path)
    assert ecrits
    for nom, chemin in ecrits.items():
        versionnee = FIXTURES / nom
        assert versionnee.is_file(), f"{nom} n'est pas versionnée"
        assert chemin.read_bytes() == versionnee.read_bytes(), (
            f"{nom} : la fixture versionnée diffère du générateur "
            "— relancer `uv run python tests/fixtures/generer_brouter.py`"
        )


def test_la_fixture_ne_porte_que_des_coordonnees_fictives():
    """Tout tient dans un rayon de 2 km autour du point zéro, en pleine mer."""
    charge = reponse_fabriquee()
    for lon, lat, _alt in charge["features"][0]["geometry"]["coordinates"]:
        assert abs(lat) < 0.02 and abs(lon) < 0.02


def test_la_reponse_fabriquee_n_est_pas_modifiee_par_les_tests():
    """Chaque test part d'une copie : la fixture sur disque n'est jamais altérée."""
    avant = reponse_fabriquee()
    charge = reponse_fabriquee()
    charge["features"][0]["properties"]["messages"] = []
    assert reponse_fabriquee() == avant

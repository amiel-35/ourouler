"""Tests des candidates de boucle (L2.3).

Aucun accès réseau : le moteur est un `MockTransport` qui rend la réponse
BRouter fabriquée, avec la longueur qu'on lui dicte — c'est ce qui permet de
mesurer l'ajustement de rayon sans dépendre du terrain.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from test_brouter import PARAMS, reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.boucle.candidates import (
    AJUSTEMENTS_MAX,
    PAS_AZIMUT_DEG,
    RAPPORT_RAYON_DEFAUT,
    azimuts,
    generer,
)
from ourouler.config import Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur

DEPART = Depart(nom="Point fictif", latitude=0.0, longitude=0.0)


def moteur(
    longueur_m,
    *,
    bornee: bool = True,
    echec_sur: float | None = None,
    code_echec: int = 500,
) -> tuple[ClientBrouter, list[dict[str, Any]]]:
    """Un moteur bouchonné. `longueur_m` : un nombre, ou une fonction du rayon demandé."""
    appels: list[dict[str, Any]] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        rayon = float(p["roundTripDistance"])
        azimut = float(p["roundTripStartDirection"])
        appels.append({"azimut": azimut, "rayon": rayon, "profil": p["profile"]})
        if echec_sur is not None and azimut == echec_sur:
            return httpx.Response(code_echec, content=b"")
        charge = reponse_fabriquee()
        entite = charge["features"][0]
        longueur = longueur_m(rayon) if callable(longueur_m) else longueur_m
        entite["properties"]["track-length"] = str(round(longueur))
        if not bornee:
            # Une demi-boucle : les extrémités sont à plus de 300 m l'une de l'autre.
            entite["geometry"]["coordinates"] = entite["geometry"]["coordinates"][:15]
        return httpx.Response(200, json=charge)

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    return client, appels


# --- la série d'azimuts -------------------------------------------------------


def test_les_azimuts_s_ecartent_de_part_et_d_autre():
    assert azimuts(45, 5) == [45, 45 + 20, 45 - 20, 45 + 40, 45 - 40]
    assert PAS_AZIMUT_DEG == 20.0


def test_les_azimuts_restent_dans_le_tour():
    assert azimuts(10, 5) == [10, 30, 350, 50, 330]
    assert azimuts(350, 3) == [350, 10, 330]


def test_un_seul_azimut_demande():
    assert azimuts(45, 1) == [45]


# --- le cas nominal -----------------------------------------------------------


def test_le_premier_rayon_vaut_la_cible_divisee_par_le_rapport_de_depart():
    client, appels = moteur(lambda rayon: rayon * RAPPORT_RAYON_DEFAUT)
    generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert appels[0]["rayon"] == pytest.approx(60_000 / RAPPORT_RAYON_DEFAUT)


def test_un_moteur_pile_dans_la_tolerance_ne_demande_qu_un_appel_par_azimut():
    client, appels = moteur(lambda rayon: rayon * RAPPORT_RAYON_DEFAUT)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.10)
    assert len(appels) == 5
    assert len(trouvees) == 5
    assert [round(c.azimut_deg) for c in trouvees] == [45, 65, 25, 85, 5]
    assert all(c.ecart_relatif == pytest.approx(0.0) for c in trouvees)
    assert all(c.trace.distance_m == pytest.approx(60_000) for c in trouvees)


def test_le_rayon_est_ajuste_par_proportion():
    """Rapport réel de 4 : la première boucle fait 80 % de la cible, la seconde tombe juste."""
    client, appels = moteur(lambda rayon: rayon * 4.0)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.05)
    assert len(appels) == 2
    assert appels[0]["rayon"] == pytest.approx(12_000)
    assert appels[1]["rayon"] == pytest.approx(15_000)
    assert trouvees[0].rayon_m == pytest.approx(15_000)
    assert trouvees[0].ecart_relatif == pytest.approx(0.0)


def test_l_ajustement_s_arrete_apres_deux_corrections():
    """Un moteur qui ignore le rayon ne doit pas faire tourner la boucle indéfiniment."""
    client, appels = moteur(20_000)  # toujours 20 km, quel que soit le rayon
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.05)
    assert len(appels) == 1 + AJUSTEMENTS_MAX == 3
    assert len(trouvees) == 1, "une candidate hors tolérance vaut mieux que rien"
    assert trouvees[0].ecart_relatif == pytest.approx(-2 / 3)


def test_une_candidate_dans_la_tolerance_suffit():
    client, appels = moteur(lambda rayon: rayon * 4.8)  # écart de −4 %, sous la tolérance
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)
    assert len(appels) == 2
    assert all(abs(c.ecart_relatif) <= 0.10 for c in trouvees)


def test_le_profil_est_transmis_au_moteur():
    client, appels = moteur(lambda rayon: rayon * 5.0)
    generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10, profil="gravel")
    assert appels[0]["profil"] == "gravel"


def test_les_candidates_sont_triees_par_ecart_absolu():
    """Le meilleur azimut n'est pas forcément celui qu'on visait.

    Le moteur ignore ici le rayon demandé — chaque direction bute sur une
    longueur qui lui est propre, comme un terrain qui ne se laisse pas
    étirer. L'ajustement par proportion ne peut donc pas les rattraper, et
    c'est le tri qui doit remonter la meilleure.
    """
    longueurs = {45.0: 40_000, 65.0: 66_000, 25.0: 58_000}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        azimut = float(requete.url.params["roundTripStartDirection"])
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = str(longueurs[azimut])
        return httpx.Response(200, json=charge)

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    trouvees = generer(
        client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.01, appels_max=99
    )
    ecarts = [abs(c.ecart_relatif) for c in trouvees]
    assert ecarts == sorted(ecarts)
    assert round(trouvees[0].azimut_deg) == 25


# --- garde-fous ---------------------------------------------------------------


def test_le_plafond_d_appels_est_respecte():
    client, appels = moteur(20_000)  # jamais dans la tolérance : 3 appels par azimut
    trouvees = generer(
        client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.05, appels_max=7
    )
    assert len(appels) == 7
    assert len(trouvees) == 3, "les azimuts déjà tentés donnent quand même leur meilleure boucle"


def test_un_plafond_d_un_seul_appel():
    client, appels = moteur(20_000)
    trouvees = generer(
        client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.05, appels_max=1
    )
    assert len(appels) == 1
    assert len(trouvees) == 1


def test_les_boucles_non_bornees_sont_ecartees():
    client, appels = moteur(lambda rayon: rayon * 5.0, bornee=False)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)
    assert appels, "le moteur a bien été interrogé"
    assert trouvees == [], "un tracé qui ne revient pas au départ n'est pas une boucle"


def test_une_distance_nulle_n_entraine_pas_de_correction_infinie():
    client, appels = moteur(0)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)
    assert len(appels) == 2, "un appel par azimut : rien à corriger proportionnellement"
    assert all(c.ecart_relatif == pytest.approx(-1.0) for c in trouvees)


def test_distance_demandee_nulle_refusee():
    client, appels = moteur(20_000)
    with pytest.raises(ErreurConnecteur, match="distance"):
        generer(client, DEPART, distance_km=0, azimut_deg=45, nb=3, tolerance=0.10)
    assert appels == [], "rien ne part avant la validation"


def test_un_azimut_en_echec_ne_perd_pas_les_autres():
    client, appels = moteur(lambda rayon: rayon * 5.0, echec_sur=65.0)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)
    assert [round(c.azimut_deg) for c in trouvees] == [45, 25]
    assert len(appels) == 3


def test_un_moteur_entierement_en_panne_releve_l_erreur():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"")

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur, match="HTTP 500"):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)


def test_le_mot_de_passe_n_apparait_pas_dans_l_erreur_relevee():
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"")

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    with pytest.raises(ErreurConnecteur) as capture:
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)
    assert PARAMS.mot_de_passe not in str(capture.value)


def test_la_meilleure_tentative_d_un_azimut_est_gardee():
    """Si la correction dégrade le résultat, on garde la boucle la plus proche."""
    longueurs = iter([66_000, 40_000, 40_000])

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = str(next(longueurs))
        return httpx.Response(200, json=charge)

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.01)
    assert trouvees[0].trace.distance_m == 66_000
    assert trouvees[0].ecart_relatif == pytest.approx(0.1)

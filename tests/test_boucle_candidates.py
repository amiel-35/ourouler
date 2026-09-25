"""Tests des candidates de boucle (L2.3).

Aucun accès réseau : le moteur est un `MockTransport` qui rend la réponse
BRouter fabriquée, avec la longueur qu'on lui dicte — c'est ce qui permet de
mesurer l'ajustement de rayon sans dépendre du terrain.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
import pytest
from test_brouter import PARAMS, reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.boucle.candidates import (
    AJUSTEMENTS_MAX,
    PAS_AZIMUT_DEG,
    RAPPORT_RAYON_DEFAUT,
    RAYON_MAX_M,
    RAYON_MIN_M,
    appels_pour,
    azimuts,
    generer,
)
from ourouler.config import Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurDistanceInatteignable, ErreurUtilisateur

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


def test_l_ajustement_s_arrete_apres_trois_corrections():
    """Un moteur qui ignore le rayon ne doit pas faire tourner la boucle indéfiniment.

    Trois corrections depuis le 13/09/2026 : l'élagage des antennes fait
    osciller la distance mesurée, deux s'arrêtaient au milieu de l'oscillation.
    Voir `AJUSTEMENTS_MAX`. Le moteur ne converge jamais (50 km quel que soit
    le rayon, écart de −17 %) : la tolérance de 5 % ne peut pas l'absorber
    même élargie au maximum autorisé, donc la boucle refuse — c'est
    `AJUSTEMENTS_MAX` qui a bien arrêté l'affinage, mesuré via le nombre
    d'appels, pas via une candidate qui n'est plus servie.
    """
    # 50 km quel que soit le rayon : la correction reste bornée (facteur 1,2,
    # rayon sous `RAYON_MAX_M`), c'est donc bien `AJUSTEMENTS_MAX` qui arrête.
    client, appels = moteur(50_000)
    with pytest.raises(ErreurDistanceInatteignable) as exc:
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.05)
    assert AJUSTEMENTS_MAX == 3
    assert len(appels) == 1 + AJUSTEMENTS_MAX == 4
    assert exc.value.ecart_relatif == pytest.approx(-1 / 6)


def test_cinq_demandees_cinq_rendues_meme_si_le_moteur_ne_converge_pas():
    """Le plafond d'appels suit la demande, il ne la rabote pas.

    Régression du 13/09/2026 : `AJUSTEMENTS_MAX` passé à 3 contre un plafond
    fixe de 12 appels rendait **trois** candidates à qui en demandait cinq,
    dès que le moteur cessait de converger — c'est-à-dire le cas que le
    troisième ajustement devait justement absorber. Rien ne le disait à
    l'utilisateur.
    """
    # 50 km quel que soit le rayon : chaque azimut épuise ses ajustements, avec
    # un écart de −17 % qu'une tolérance de 5 % ne peut pas absorber même
    # élargie au maximum : les cinq azimuts sont bien tentés (appels_pour(5)
    # appels), mais aucune candidate ne tient, donc la boucle refuse — le
    # « cinq rendues » se vérifie maintenant sur le mouchard d'appels.
    client, appels = moteur(50_000)
    with pytest.raises(ErreurDistanceInatteignable):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.05)
    assert len(appels) == appels_pour(5) == 5 * (1 + AJUSTEMENTS_MAX)
    assert len({round(a["azimut"]) for a in appels}) == 5, "cinq directions distinctes tentées"


def test_une_candidate_au_dessus_de_la_cible_dans_la_tolerance_suffit():
    """Déjà au-dessus de la cible et dans la tolérance : pas d'essai de plus."""
    client, appels = moteur(lambda rayon: rayon * 5.2)  # +4 %, dans la tolérance
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)
    assert len(appels) == 2  # un appel par azimut
    assert all(abs(c.ecart_relatif) <= 0.10 for c in trouvees)


def test_sous_la_cible_dans_la_tolerance_tente_une_correction_vers_plus_long():
    """Mots du mainteneur (18/09/2026) : il préfère dépasser la cible que rester en dessous.

    À rayon initial, le moteur rend −4 % (dans la tolérance, sous la cible) :
    ce n'est pas servi tout de suite. La correction proportionnelle vise
    naturellement plus long (`cible_m / distance_m > 1` sous la cible) et
    tombe ici pile sur la cible — c'est elle qui est retenue.
    """
    client, appels = moteur(lambda rayon: rayon * 4.8)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels) == 2  # le premier essai, puis l'essai « plus long »
    assert trouvees[0].ecart_relatif == pytest.approx(0.0, abs=1e-9)


def test_l_essai_plus_long_qui_sort_de_la_tolerance_retombe_sur_le_premier():
    """Si viser plus long sort de la bande, on ne le sert pas : la première candidate reprend la main."""
    reponses = iter([4.8, 6.0])  # −4 % puis une sur-correction à +25 %, hors tolérance

    def longueur(rayon: float) -> float:
        return rayon * next(reponses)

    client, appels = moteur(longueur)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels) == 2  # un seul essai de plus, jamais une relance
    assert trouvees[0].ecart_relatif == pytest.approx(-0.04, abs=1e-9)


def test_l_essai_plus_long_mais_plus_court_ne_remplace_pas_le_premier():
    """**La règle du lot, et le seul test qui la prouve** (ajouté le 18/09/2026).

    Relecture : retirer la clause « et réellement plus long » de `generer`
    laissait les trente-quatre autres tests verts. Ce cas-ci est le seul qui
    la tienne, et il n'est pas théorique — le docstring d'`AJUSTEMENTS_MAX`
    note que la distance rendue **oscille** d'une itération à l'autre
    (53,6 km puis 65,4 km pour 60 km demandés).

    Premier essai à −4 %, second à −8 % : tous deux dans la bande, mais le
    second est plus court. Servir le second serait exactement le sous-tir que
    ce lot existe pour tuer.
    """
    reponses = iter([4.8, 4.416])  # −4 %, puis −8 % : dans la bande, mais plus court
    client, appels = moteur(lambda rayon: rayon * next(reponses))
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels) == 2
    assert trouvees[0].ecart_relatif == pytest.approx(-0.04, abs=1e-9)


def test_un_echec_du_moteur_au_second_essai_ne_perd_pas_la_premiere_candidate():
    """Le bug que la relecture cherchait en premier : il n'y est pas, et maintenant c'est tenu.

    Une candidate acceptable est déjà en main quand l'essai « plus long »
    échoue. Elle doit être servie, et l'échec ne doit pas remonter : il ne
    remonte que si **rien** n'a été trouvé.
    """
    etat = {"premier": True}

    def gestionnaire(requete):
        p = requete.url.params
        appels_vus.append(float(p["roundTripDistance"]))
        if not etat["premier"]:
            return httpx.Response(500, content=b"")
        etat["premier"] = False
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = str(round(12_000.0 * 4.8))
        return httpx.Response(200, json=charge)

    appels_vus: list[float] = []
    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels_vus) == 2
    assert len(trouvees) == 1
    assert trouvees[0].ecart_relatif == pytest.approx(-0.04, abs=1e-9)


def test_l_essai_plus_long_qui_depasse_davantage_ne_gagne_pas():
    """**L'arbitrage du mainteneur du 18/09/2026**, sur ses propres chiffres.

    125 km demandés, tolérance 10 % : un premier essai à 120 km (−4 %) et un
    second à 137 km (+9,9 %) tiennent tous deux dans la bande. La première
    écriture du lot servait 137 — on s'éloignait de douze kilomètres de la
    demande en ayant cinq en main. Le mainteneur a tranché : la plus proche
    de la cible.
    """
    reponses = iter([4.8, 5.2608])  # −4 %, puis +9,6 % : dans la bande, mais plus loin
    client, appels = moteur(lambda rayon: rayon * next(reponses))
    trouvees = generer(client, DEPART, distance_km=125, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels) == 2
    assert trouvees[0].ecart_relatif == pytest.approx(-0.04, abs=1e-9)


def test_a_ecart_egal_la_plus_longue_l_emporte():
    """C'est là, et seulement là, que la préférence du mainteneur s'exprime :
    entre −4 % et +4 %, on part sur le +4 %. Ça ne coûte rien, et c'est ce
    qu'il a demandé — « c'est pas dur de faire 10 bornes de plus »."""
    reponses = iter([4.8, 4.992])  # −4 %, puis exactement +4 %
    client, appels = moteur(lambda rayon: rayon * next(reponses))
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    assert len(appels) == 2
    assert trouvees[0].ecart_relatif == pytest.approx(0.04, abs=1e-4)


def test_l_essai_plus_long_ne_se_declenche_pas_sans_budget_disponible():
    """Le biais ne dépense jamais plus que ce qu'`appels_max` autorise déjà."""
    client, appels = moteur(lambda rayon: rayon * 4.8)  # −4 %, dans la tolérance, sous la cible
    trouvees = generer(
        client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10, appels_max=1
    )
    assert len(appels) == 1  # le plafond d'appels prime sur l'essai « plus long »
    assert trouvees[0].ecart_relatif == pytest.approx(-0.04, abs=1e-9)


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
    # 20 km quel que soit le rayon pour une cible de 60 : écart de −67 %,
    # bien au-delà de ce qu'une tolérance de 5 % peut absorber même élargie.
    # Le sujet du test est le plafond d'appels lui-même, qui se lit sur le
    # mouchard d'appels, pas sur des candidates qui ne sont plus servies.
    client, appels = moteur(20_000)  # jamais dans la tolérance : 3 appels par azimut
    with pytest.raises(ErreurDistanceInatteignable):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.05, appels_max=7)
    assert len(appels) == 7


def test_un_plafond_d_un_seul_appel():
    client, appels = moteur(20_000)
    with pytest.raises(ErreurDistanceInatteignable):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=5, tolerance=0.05, appels_max=1)
    assert len(appels) == 1


def test_les_boucles_non_bornees_sont_ecartees():
    client, appels = moteur(lambda rayon: rayon * 5.0, bornee=False)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)
    assert appels, "le moteur a bien été interrogé"
    assert trouvees == [], "un tracé qui ne revient pas au départ n'est pas une boucle"


def test_une_distance_nulle_n_entraine_pas_de_correction_infinie():
    # Servir 0 m pour 60 km demandés (écart de −100 %) sans un mot était
    # exactement le défaut corrigé par `ErreurDistanceInatteignable` : ici,
    # le refus est désormais l'issue attendue, pas une boucle de 0 m.
    client, appels = moteur(0)
    with pytest.raises(ErreurDistanceInatteignable) as exc:
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)
    assert len(appels) == 2, "un appel par azimut : rien à corriger proportionnellement"
    assert exc.value.ecart_relatif == pytest.approx(-1.0)


@pytest.mark.parametrize("distance_km", [0, -10.0, float("nan"), float("inf")])
def test_distance_demandee_absurde_refusee(distance_km):
    """Une distance de cible inexploitable est une erreur d'usage, pas une panne du moteur.

    `ErreurConnecteur` est réservée à « échec d'un appel à un service
    externe » (`ourouler.noyau.erreurs`) : ici rien n'est encore parti. Le refus est
    une `ErreurUtilisateur` qui nomme le paramètre, levée avant tout appel.
    """
    client, appels = moteur(20_000)
    with pytest.raises(ErreurUtilisateur, match="distance_km"):
        generer(client, DEPART, distance_km=distance_km, azimut_deg=45, nb=3, tolerance=0.10)
    assert appels == [], "rien ne part avant la validation"


@pytest.mark.parametrize("nb", [0, -3])
def test_nombre_de_candidates_absurde_refuse(nb):
    client, appels = moteur(20_000)
    with pytest.raises(ErreurUtilisateur, match="nb"):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=nb, tolerance=0.10)
    assert appels == [], "aucune candidate demandée, aucun appel"


def test_un_moteur_qui_rend_toujours_100_m_ne_fait_pas_exploser_le_rayon():
    """Point 4 de la relecture : l'ajustement n'était borné ni en facteur ni en valeur.

    Mesuré avant correction, avec une cible de 60 km : les rayons demandés au
    serveur du mainteneur étaient 12 000 m, puis 7 200 000 m, puis
    4 320 000 000 m — `roundTripDistance` à 4,3 millions de kilomètres.
    `appels_max` bornait le nombre d'appels, pas leur coût.
    """
    # Une boucle de 100 m pour une cible de 60 km (écart de −99,8 %) n'entre
    # plus dans la tolérance même élargie au maximum : les trois azimuts sont
    # abandonnés faute de correction exploitable, et la demande refuse. Les
    # bornes de rayon restent le vrai sujet du test, vérifiées sur le
    # mouchard d'appels.
    client, appels = moteur(100.0)
    with pytest.raises(ErreurDistanceInatteignable) as exc:
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=3, tolerance=0.10)

    rayons = [a["rayon"] for a in appels]
    assert rayons, "le premier essai de chaque azimut doit bien partir"
    assert max(rayons) <= RAYON_MAX_M, f"rayon demandé hors plage : {max(rayons)} m"
    assert min(rayons) >= RAYON_MIN_M, f"rayon demandé hors plage : {min(rayons)} m"
    assert len(appels) == 3, (
        f"un essai par azimut attendu (la borne abandonne l'azimut), {len(appels)} faits : {rayons}"
    )
    # L'azimut est abandonné, mais sa meilleure tentative est bien celle
    # jugée par le refus : une boucle de 100 m est une mauvaise réponse, pas
    # une absence de réponse.
    assert exc.value.distance_obtenue_km == pytest.approx(0.1)


def test_un_moteur_qui_rend_une_boucle_bien_trop_longue_ne_reduit_pas_le_rayon_a_rien():
    """Symétrique du précédent : le rayon ne descend pas sous la borne basse.

    6 000 km pour une cible de 60 (écart de +9 900 %) est hors de portée même
    d'une tolérance élargie au maximum : la demande refuse, mais les bornes
    de rayon restent vérifiables sur le mouchard d'appels.
    """
    client, appels = moteur(6_000_000.0)  # 6 000 km pour une cible de 60
    with pytest.raises(ErreurDistanceInatteignable):
        generer(client, DEPART, distance_km=60, azimut_deg=45, nb=2, tolerance=0.10)
    rayons = [a["rayon"] for a in appels]
    assert min(rayons) >= RAYON_MIN_M, f"rayon demandé hors plage : {min(rayons)} m"
    assert len(appels) == 2, f"un essai par azimut attendu, {len(appels)} faits : {rayons}"


def test_le_rayon_initial_reste_dans_la_plage_exploitable():
    """Une cible démesurée ne doit pas sortir de la plage dès le premier appel.

    Avec un rapport réel de 5, une cible de 5 000 km clampe le rayon initial
    à `RAYON_MAX_M`, ce qui rend une boucle bien plus courte que la cible
    (écart de −80 %) : la demande refuse, mais le rayon demandé au moteur
    reste le vrai sujet du test.
    """
    client, appels = moteur(lambda rayon: rayon * 5.0)
    with pytest.raises(ErreurDistanceInatteignable):
        generer(client, DEPART, distance_km=5000, azimut_deg=0, nb=1, tolerance=0.10)
    assert appels[0]["rayon"] == pytest.approx(RAYON_MAX_M)


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
    longueurs = iter([66_000, 40_000, 40_000, 40_000])

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = str(next(longueurs))
        return httpx.Response(200, json=charge)

    client = ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    # Tolérance à 0,05 (au lieu de 0,01) : l'écart de +10 % de la meilleure
    # tentative ne nécessite plus qu'un seul palier d'élargissement, dans le
    # plafond autorisé — la tolérance plus serrée aurait refusé la demande
    # entière, ce qui n'est pas le sujet ici (garder la meilleure tentative).
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.05)
    assert trouvees[0].trace.distance_m == 66_000
    assert trouvees[0].ecart_relatif == pytest.approx(0.1)


# --- élagage des antennes (L3.1) ----------------------------------------------


def anneau_avec_antenne(
    rayon_deg: float = 0.01, pas_m: float = 10.0, antenne_m: float = 150.0
) -> list[list[float]]:
    """Un anneau fermé autour de (0, 0), avec un cul-de-sac radial vers l'extérieur.

    Coordonnées `[lon, lat, alt]` comme les rend BRouter. Le cul-de-sac part
    du point à l'est de l'anneau, sort de `antenne_m` et revient par le même
    chemin : un aller-retour de `2 × antenne_m`.
    """
    degre_m = 111_320.0
    circonference = 2 * math.pi * rayon_deg * degre_m
    nb = max(8, round(circonference / pas_m))
    anneau = [
        [rayon_deg * math.sin(2 * math.pi * i / nb), rayon_deg * math.cos(2 * math.pi * i / nb), 30.0]
        for i in range(nb + 1)
    ]
    # Le point à l'est (quart du tour) porte l'antenne.
    pied = nb // 4
    pas_deg = pas_m / degre_m
    nb_pas = round(antenne_m / pas_m)
    dehors = [[rayon_deg + pas_deg * i, 0.0, 30.0] for i in range(1, nb_pas + 1)]
    return anneau[: pied + 1] + dehors + dehors[-2::-1] + anneau[pied:]


def moteur_avec_antenne(points: list[list[float]]) -> ClientBrouter:
    """Un moteur bouchonné qui rend toujours la géométrie donnée, sans tronçons."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        entite = charge["features"][0]
        entite["geometry"]["coordinates"] = points
        entite["properties"]["messages"] = []
        entite["properties"].pop("track-length", None)  # distance = cumul haversine
        return httpx.Response(200, json=charge)

    return ClientBrouter(PARAMS, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def test_les_candidates_sont_elaguees_de_leurs_antennes():
    client = moteur_avec_antenne(anneau_avec_antenne())
    trouvees = generer(client, DEPART, distance_km=7.0, azimut_deg=45, nb=1, tolerance=0.5)

    trace = trouvees[0].trace
    assert trace.meta["antennes"]["nombre"] == 1
    assert trace.meta["antennes"]["metres_retires"] == pytest.approx(300, abs=30)
    assert trace.meta["distance_source"] == "recalculee"
    # Le cul-de-sac partait à 0,01 + 150 m vers l'est : plus aucun point là-bas.
    assert max(p.lon for p in trace.points) < 0.0102


def test_l_ecart_relatif_est_mesure_apres_elagage():
    """L'ajustement de rayon travaille sur la distance réellement proposée."""
    points = anneau_avec_antenne()
    client = moteur_avec_antenne(points)
    trouvees = generer(client, DEPART, distance_km=7.0, azimut_deg=45, nb=1, tolerance=0.5)

    trace = trouvees[0].trace
    attendu = (trace.distance_m - 7000.0) / 7000.0
    assert trouvees[0].ecart_relatif == pytest.approx(attendu)
    # L'anneau seul fait environ 7 000 m ; avec l'antenne il en ferait 7 300.
    assert trace.distance_m == pytest.approx(6993, abs=60)


def test_une_candidate_sans_antenne_garde_la_distance_du_moteur():
    """Sans rien à retirer, `track-length` n'est pas remplacé par un recalcul."""
    client, _ = moteur(59_000)
    trouvees = generer(client, DEPART, distance_km=60, azimut_deg=45, nb=1, tolerance=0.10)
    trace = trouvees[0].trace
    assert trace.distance_m == 59_000
    assert trace.meta["antennes"] == {"nombre": 0, "metres_retires": 0.0}
    assert "distance_source" not in trace.meta

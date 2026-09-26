"""Le vent au départ, servi **avant** la recherche — Q44.

L'écran de demande posait une direction sans jamais dire d'où vient le vent,
alors que la maquette E16 le prévoyait (« Vent de sud-ouest à 22 km/h demain
matin »). Cette route comble ce trou, et elle porte en même temps ce que
chaque préférence d'orientation imposerait comme azimut.

Ce que ces tests protègent avant tout : **« de travers » rend deux azimuts,
opposés**. Un champ scalaire, ou un front qui n'en lirait qu'un, entasserait
la moitié de la promesse sous le tapis.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from outils_api import (
    client_api,
    client_bouchon,
    client_meteo_ordinaire,
    config_d_essai,
    corps_json,
)

#: Le vent des fixtures du dépôt vient de 45° (nord-est) à 14 km/h — au-dessus
#: du seuil de 8 km/h, donc la question se pose.
VENT_DEPUIS_DEG = 45.0


def demander_le_vent(client, **params):
    return client.get("/api/v1/vent-depart", params=params)


def donnees_du_vent(**options):
    client = client_api(
        config=config_d_essai(),
        client_meteo=options.pop("client_meteo", None) or client_meteo_ordinaire(**options),
    )
    reponse = demander_le_vent(client, jour=date.today().isoformat())
    assert reponse.status_code == 200, reponse.text
    return corps_json(reponse)["donnees"]


def test_le_vent_au_depart_est_servi_avec_sa_direction_nommee():
    """« Vent de sud-ouest » est une valeur affichée : elle vient de l'API.

    Le front n'a pas le droit de traduire 225° en « SO » lui-même — ce serait
    un calcul côté écran, et la règle du contrat de front l'interdit.
    """
    donnees = donnees_du_vent()
    assert donnees["posee"] is True, donnees["motif"]
    assert donnees["vent_kmh"] > 0
    assert donnees["vent_depuis_deg"] == pytest.approx(VENT_DEPUIS_DEG)
    assert donnees["vent_depuis_nom"] == "NE"


def test_le_travers_rend_deux_azimuts_opposes():
    """Le cœur de Q44, vu depuis l'API."""
    donnees = donnees_du_vent()
    travers = donnees["azimuts_par_choix"]["travers"]
    assert len(travers) == 2, travers
    a, b = (c["azimut_deg"] for c in travers)
    assert abs(a - b) % 360.0 == pytest.approx(180.0)
    # Et chacun porte son nom, pour la même raison que le vent lui-même.
    assert all(c["nom"] for c in travers)


def test_les_deux_dos_au_vent_n_en_rendent_qu_un_chacun():
    donnees = donnees_du_vent()
    par_choix = donnees["azimuts_par_choix"]
    assert len(par_choix["retour-dos"]) == 1
    assert len(par_choix["depart-dos"]) == 1
    (retour,) = par_choix["retour-dos"]
    (depart,) = par_choix["depart-dos"]
    assert abs(retour["azimut_deg"] - depart["azimut_deg"]) % 360.0 == pytest.approx(180.0)


def test_peu_importe_ne_contraint_rien():
    """« Peu importe » est une réponse valable, et c'est le défaut."""
    assert donnees_du_vent()["azimuts_par_choix"]["peu-importe"] == []


def test_chaque_azimut_servi_est_un_azimut():
    """Un front qui dessine une flèche a besoin d'un angle du tour de l'horizon."""
    par_choix = donnees_du_vent()["azimuts_par_choix"]
    for choix, azimuts in par_choix.items():
        for c in azimuts:
            assert 0.0 <= c["azimut_deg"] < 360.0, (choix, c)


def test_un_vent_trop_faible_ne_propose_aucune_orientation_et_dit_pourquoi():
    """Sous 8 km/h l'orientation ne change rien de perceptible (règle absolue 5).

    Le front en a besoin pour **griser** le mode « selon le vent » au lieu de
    proposer trois préférences qui ne feraient rien.
    """
    donnees = donnees_du_vent(vent_kmh=1.0)
    assert donnees["posee"] is False
    assert donnees["motif"], "refusé sans dire pourquoi"
    assert all(azimuts == [] for azimuts in donnees["azimuts_par_choix"].values())


def test_au_dela_de_l_horizon_la_question_ne_se_pose_pas():
    """Trois jours inclus, quatre non : on ne promet pas ce qu'on ne prévoit pas."""
    client = client_api(config=config_d_essai(), client_meteo=client_meteo_ordinaire())
    lointain = date.today() + timedelta(days=donnees_du_vent()["horizon_jours"] + 3)
    donnees = corps_json(
        demander_le_vent(client, jour=lointain.isoformat())
    )["donnees"]
    assert donnees["posee"] is False
    assert donnees["motif"]


def test_une_panne_meteo_ne_rend_pas_une_erreur_mais_une_ignorance():
    """L'écran de demande doit rester utilisable sans Open-Meteo.

    C'est la même règle que E14 pour le parcours : on perd les affirmations,
    pas l'écran. Un 503 ici empêcherait de demander une sortie du tout.
    """
    client = client_api(
        config=config_d_essai(),
        client_meteo=client_bouchon(503, texte="service unavailable"),
    )
    reponse = demander_le_vent(client, jour=date.today().isoformat())
    assert reponse.status_code == 200, reponse.text
    donnees = corps_json(reponse)["donnees"]
    assert donnees["posee"] is False
    assert donnees["motif"]


def test_latitude_sans_longitude_est_refusee():
    """Même règle que `/meteo` : les deux ensemble, ou aucune."""
    client = client_api(config=config_d_essai(), client_meteo=client_meteo_ordinaire())
    reponse = demander_le_vent(client, jour=date.today().isoformat(), latitude=48.0)
    assert reponse.status_code == 400, reponse.text

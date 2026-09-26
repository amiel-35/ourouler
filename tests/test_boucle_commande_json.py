"""`ourouler boucle --json` : le document publié, et `--pause` à l'écran.

Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from outils_boucle_commande import (
    args,
    config_de_test,
    moteur_brouter,
    moteur_meteo,
)

from ourouler.commandes.boucle import executer_depuis_namespace as executer

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- la sortie JSON ------------------------------------------------------------


def test_json_valide_avec_toutes_les_mesures(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(pluie=0.3))
    charge = json.loads(capsys.readouterr().out)
    assert charge["gpx"].endswith(".gpx")
    assert Path(charge["gpx"]).is_file()
    assert charge["demande"]["direction"] == "NE"
    assert charge["demande"]["azimut_deg"] == pytest.approx(45.0)
    candidate = charge["candidates"][0]
    assert candidate["retenue"] is True
    assert set(candidate["couts"]) == {
        "km_trafic",
        "km_calme",
        "km_non_classe",
        "km_non_revetu",
        "antennes_m",
        "virages_gauche",
        "virages_gauche_trafic",
        "virages_droite",
        "sens",
        "score",
    }
    assert candidate["meteo"]["pluie_cumulee_mm"] > 0
    assert candidate["meteo"]["echantillons"], "les échantillons de L2.5 doivent être publiés"
    # Lot L5.3 : les flèches de vent (mêmes que la carte HTML) sont dans le
    # JSON de la boucle libre. Le vent bouchonné (14 km/h) dépasse le seuil.
    fleches = candidate["meteo"]["fleches_vent"]
    assert fleches, "un vent bouchonné à 14 km/h doit produire des flèches"
    for fleche in fleches:
        assert set(fleche) == {"pt", "depuis_deg", "vent_kmh", "rafale_kmh", "relatif"}


# --- --pause : l'écran, le JSON --------------------------------------------------


def test_sans_pause_l_entete_ne_dit_rien_des_pauses(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    assert "Pauses" not in capsys.readouterr().out


def test_l_entete_annonce_le_total_des_pauses_et_l_arrivee(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(
        args(pause=["10:0h45", "40:4h30"]),
        config_de_test(),
        moteur_brouter(),
        moteur_meteo(),
    )
    sortie = capsys.readouterr().out
    ligne = next(ligne for ligne in sortie.splitlines() if ligne.startswith("Pauses"))
    assert "2 déclarée(s)" in ligne
    assert "5:15 au total" in ligne, ligne  # 45 min + 4h30 = 5h15
    assert "Arrivée estimée" in ligne
    assert "par-dessus le temps écoulé porte à porte" in ligne


def test_le_json_porte_les_pauses_declarees_et_l_heure_d_arrivee(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    executer(
        args(json=True, pause=["10:0h45"]),
        config_de_test(),
        moteur_brouter(),
        moteur_meteo(),
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["pauses"] == [{"km": 10.0, "duree_s": 2700}]
    candidate = charge["candidates"][0]
    assert "heure_arrivee" in candidate
    depart = datetime.fromisoformat(charge["depart"]["heure"])
    arrivee = datetime.fromisoformat(candidate["heure_arrivee"])
    assert arrivee > depart + timedelta(minutes=45), (
        "l'arrivée doit au moins porter la pause déclarée, en plus du temps de route"
    )


def test_une_pause_avance_l_heure_d_arrivee_de_sa_duree(tmp_path: Path, monkeypatch, capsys):
    """Comparaison directe : seule la pause doit expliquer l'écart entre les deux arrivées."""
    monkeypatch.chdir(tmp_path)
    executer(args(json=True, candidates=1), config_de_test(), moteur_brouter(), moteur_meteo())
    sans_pause = json.loads(capsys.readouterr().out)

    executer(
        args(json=True, candidates=1, pause=["10:0h45"]),
        config_de_test(),
        moteur_brouter(),
        moteur_meteo(),
    )
    avec_pause = json.loads(capsys.readouterr().out)

    t_sans = datetime.fromisoformat(sans_pause["candidates"][0]["heure_arrivee"])
    t_avec = datetime.fromisoformat(avec_pause["candidates"][0]["heure_arrivee"])
    assert (t_avec - t_sans) == timedelta(minutes=45)

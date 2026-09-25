"""`ourouler analyser` : la météo et la durée porte à porte d'un parcours déjà en main.

Rien ne sort sur le réseau : la météo est un `MockTransport` (repris de
`test_physique_commande.client_meteo_bouchonne`). Aucune coordonnée réelle :
tout part du point (0, 0), comme les autres tests de ce module.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pytest
from test_physique_commande import client_meteo_bouchonne, config_de_test, gpx_plat

from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.commande import (
    DISTANCE_MAX_ANALYSE_M,
    chemin_calibration,
    ecrire_calibration,
    executer_analyser,
)


def args_analyser(**champs) -> argparse.Namespace:
    defauts = {
        "gpx": None,
        "puissance": None,
        "vitesse_a_plat": None,
        "velo": None,
        "depart": None,
        "json": True,
    }
    return argparse.Namespace(**{**defauts, **champs})


def test_analyser_refuse_sans_heure_depart(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    with pytest.raises(ErreurUtilisateur, match="heure-depart"):
        executer_analyser(args_analyser(gpx=str(gpx)), config)


def test_analyser_refuse_sans_gpx(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="--gpx"):
        executer_analyser(args_analyser(depart="2026-05-16T05:00"), config)


def test_analyser_refuse_un_gpx_absent(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="introuvable"):
        executer_analyser(
            args_analyser(gpx=str(tmp_path / "nulle_part.gpx"), depart="2026-05-16T05:00"),
            config,
        )


def test_analyser_refuse_sans_ftp_ni_puissance(tmp_path: Path):
    """Sans FTP dans le profil, rien ne construit une puissance d'endurance par défaut —
    même repli que `boucle._modele_du_velo` (« pas de calcul sur une valeur inventée »)."""
    config = config_de_test(tmp_path / "cache", cycliste={"masse_kg": 91})
    assert config.cycliste.ftp_w is None
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    with pytest.raises(ErreurUtilisateur, match="--puissance"):
        executer_analyser(args_analyser(gpx=str(gpx), depart="2026-05-16T05:00"), config)


def test_analyser_avec_puissance_par_defaut_de_la_ftp(tmp_path: Path, capsys):
    """Sans --puissance, la puissance d'endurance du profil (position_zone × FTP)."""
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    code = executer_analyser(
        args_analyser(gpx=str(gpx), depart="2026-05-16T05:00"),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    attendue = config.seance.puissance_endurance_pct * config.cycliste.ftp_w
    assert charge["puissance_w"] == pytest.approx(attendue, rel=1e-6)


def test_analyser_rend_une_fourchette_porte_a_porte_et_une_arrivee(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {
            "cda_m2": 0.31,
            "crr": 0.0045,
            "masse_totale_kg": 100.0,
            "date": "2026-09-13",
            "porte_a_porte": {"bas": 1.02, "mediane": 1.08, "haut": 1.15, "n": 12},
        },
    )
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    code = executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart="2026-05-16T05:00"),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    assert code == 0
    charge = json.loads(capsys.readouterr().out)

    # Le temps sans arrêt (L9.1) — jamais un seul chiffre au porte à porte.
    assert charge["temps_estime_s"] > 0
    assert (
        charge["temps_ecoule_bas_s"]
        <= charge["temps_ecoule_s"]
        <= charge["temps_ecoule_haut_s"]
    )
    assert charge["temps_ecoule_source"] == "mesure"
    assert charge["temps_ecoule_bas_s"] == pytest.approx(charge["temps_estime_s"] * 1.02, rel=1e-3)
    assert charge["temps_ecoule_haut_s"] == pytest.approx(charge["temps_estime_s"] * 1.15, rel=1e-3)

    # Trois heures d'arrivée, dans l'ordre, dérivées du même départ.
    assert (
        charge["heure_arrivee_bas"] <= charge["heure_arrivee"] <= charge["heure_arrivee_haut"]
    )

    # La météo par tronçon, dans la même forme qu'une candidate de boucle
    # (F0.1) : flèches de vent et échantillons, pour réutiliser Carte/
    # LegendeVent/ProfilAltitude côté front sans code neuf.
    assert charge["meteo"] is not None
    assert charge["meteo"]["n_echantillons"] > 0
    assert isinstance(charge["meteo"]["fleches_vent"], list)
    assert charge["meteo_absente"] is None

    # La géométrie du tracé, pour la carte et le profil d'altitude.
    assert len(charge["trace"]["points"]) > 0
    assert len(charge["trace"]["profil"]) == len(charge["trace"]["points"])


def test_analyser_sans_calibration_retombe_sur_la_convention(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart="2026-05-16T05:00"),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["temps_ecoule_source"] == "defaut"
    assert charge["parametres"]["provenance"] == "littérature"


def test_analyser_au_dela_de_l_horizon_rend_la_duree_sans_meteo(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache", meteo={"horizon_jours": 7})
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    loin = date.today().isoformat()[:4] + "-12-24T05:00"  # largement au-delà de 7 jours
    code = executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart=loin),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["meteo"] is None
    assert charge["meteo_absente"] is not None
    # La durée, elle, reste rendue — sans météo, pas sans réponse.
    assert charge["temps_estime_s"] > 0
    assert charge["heure_arrivee"] is not None


def test_analyser_refuse_un_parcours_trop_long(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=DISTANCE_MAX_ANALYSE_M + 10_000.0)
    with pytest.raises(ErreurUtilisateur, match="km"):
        executer_analyser(
            args_analyser(gpx=str(gpx), puissance=200.0, depart="2026-05-16T05:00"), config
        )

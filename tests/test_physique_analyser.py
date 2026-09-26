"""`ourouler analyser` : la météo et la durée porte à porte d'un parcours déjà en main.

Rien ne sort sur le réseau : la météo est un `MockTransport` (repris de
`test_physique_commande.client_meteo_bouchonne`). Aucune coordonnée réelle :
tout part du point (0, 0), comme les autres tests de ce module.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from test_physique_commande import client_meteo_bouchonne, config_de_test, gpx_plat

from ourouler.commandes.physique import analyser_depuis_namespace as executer_analyser
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.services.physique import (
    DISTANCE_MAX_ANALYSE_M,
    chemin_calibration,
    ecrire_calibration,
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
    assert charge["temps_ecoule_bas_s"] <= charge["temps_ecoule_s"] <= charge["temps_ecoule_haut_s"]
    assert charge["temps_ecoule_source"] == "mesure"
    assert charge["temps_ecoule_bas_s"] == pytest.approx(charge["temps_estime_s"] * 1.02, rel=1e-3)
    assert charge["temps_ecoule_haut_s"] == pytest.approx(charge["temps_estime_s"] * 1.15, rel=1e-3)

    # Trois heures d'arrivée, dans l'ordre, dérivées du même départ.
    assert charge["heure_arrivee_bas"] <= charge["heure_arrivee"] <= charge["heure_arrivee_haut"]

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
        executer_analyser(args_analyser(gpx=str(gpx), puissance=200.0, depart="2026-05-16T05:00"), config)


# --- relecture de L9.8 : heures porte à porte, horizon, plusieurs traces ------


def _calibration_porte_a_porte(config, facteur: float) -> None:
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {
            "cda_m2": 0.31,
            "crr": 0.0045,
            "masse_totale_kg": 100.0,
            "date": "2026-09-13",
            "porte_a_porte": {"bas": facteur, "mediane": facteur, "haut": facteur, "n": 12},
        },
    )


def _analyse_longue(tmp_path: Path, capsys, facteur: float, depart: str, **sections) -> dict:
    config = config_de_test(tmp_path / f"cache-{facteur}", **sections)
    _calibration_porte_a_porte(config, facteur)
    gpx = gpx_plat(tmp_path / "long.gpx", longueur_m=300_000.0)
    executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart=depart),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    return json.loads(capsys.readouterr().out)


def _demain(heure: str) -> str:
    return f"{(date.today() + timedelta(days=1)).isoformat()}T{heure}"


def test_sur_300_km_la_meteo_est_datee_au_porte_a_porte(tmp_path: Path, capsys):
    """Les heures de passage suivent le porte à porte (temps en mouvement × médiane
    de la fourchette), pas le temps en mouvement seul : sur 300 km, l'écart se
    compte en heures."""
    sans_arret = _analyse_longue(tmp_path, capsys, 1.0, _demain("06:00"))
    avec_arrets = _analyse_longue(tmp_path, capsys, 1.5, _demain("06:00"))

    def ecarts_s(charge: dict) -> list[float]:
        depart = datetime.fromisoformat(charge["depart"])
        return [
            (datetime.fromisoformat(e["t"]) - depart).total_seconds() for e in charge["meteo"]["echantillons"]
        ]

    a, b = ecarts_s(sans_arret), ecarts_s(avec_arrets)
    assert a == sorted(a) and b == sorted(b)  # croissantes
    assert b[-1] == pytest.approx(1.5 * a[-1], rel=1e-6)
    assert b[-1] - a[-1] > 3 * 3600  # plus de trois heures d'écart à l'arrivée
    # La datation est à vent nul (second ordre, voir `_vitesse_a_vent_nul`) :
    # le dernier échantillon tombe au porte à porte médian **sans vent**, soit
    # le temps en mouvement à vent nul × 1,5 — ici avant l'arrivée annoncée,
    # le bouchon soufflant 10 km/h de face.
    assert b[-1] == pytest.approx(1.5 * 300.0 / avec_arrets["vitesse_a_vent_nul_kmh"] * 3600, rel=1e-3)
    assert avec_arrets["porte_a_porte"]["mediane"] == 1.5


def test_rien_au_dela_de_l_horizon_n_est_une_prevision(tmp_path: Path, capsys):
    """Départ le dernier jour couvert, 20 h, 300 km : la fin tombe le lendemain,
    au-delà de l'horizon. Même si Open-Meteo rendait ces heures (le bouchon rend
    tout ce qu'on lui demande), elles sont vides et marquées."""
    charge = _analyse_longue(tmp_path, capsys, 1.0, _demain("20:00"), meteo={"horizon_jours": 1})
    meteo = charge["meteo"]
    limite = datetime.combine(
        date.today() + timedelta(days=2), time(0), tzinfo=datetime.fromisoformat(charge["depart"]).tzinfo
    )
    avant = [e for e in meteo["echantillons"] if datetime.fromisoformat(e["t"]) <= limite]
    apres = [e for e in meteo["echantillons"] if datetime.fromisoformat(e["t"]) > limite]
    assert avant and apres
    for e in apres:
        assert e["au_dela_prevision"] is True
        assert e["modele"] is None
        assert e["pluie_mm"] is None and e["vent_kmh"] is None and e["ressenti_c"] is None
    assert all(not e["au_dela_prevision"] and e["modele"] for e in avant)
    assert meteo["au_dela_prevision_dist_m"] == apres[0]["dist_m"]
    assert meteo["n_vent_connu"] == len(avant)


def test_le_texte_dit_l_au_dela_de_la_prevision(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache", meteo={"horizon_jours": 1})
    gpx = gpx_plat(tmp_path / "long.gpx", longueur_m=300_000.0)
    executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart=_demain("20:00"), json=False),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    texte = capsys.readouterr().out
    assert "au-delà de la prévision" in texte
    assert "porte à porte, arrêts compris" in texte


def test_plusieurs_traces_sont_enchainees_et_le_trou_est_dit(tmp_path: Path, capsys):
    """Un brevet en trois traces, dont la troisième commence 12 km plus loin."""
    km = 1.0 / 111.19493  # un kilomètre en degrés, à l'équateur

    def trk(nom: str, debut_km: float, fin_km: float) -> str:
        pts = "".join(
            f'<trkpt lat="0" lon="{d * km:.7f}"><ele>100</ele></trkpt>'
            for d in (debut_km + i * 0.5 for i in range(int((fin_km - debut_km) / 0.5) + 1))
        )
        return f"<trk><name>{nom}</name><trkseg>{pts}</trkseg></trk>"

    gpx = tmp_path / "brevet.gpx"
    gpx.write_text(
        f"<gpx>{trk('Étape 1', 0, 20)}{trk('Étape 2', 20, 40)}{trk('Étape 3', 52, 70)}</gpx>",
        encoding="utf-8",
    )
    config = config_de_test(tmp_path / "cache")
    executer_analyser(
        args_analyser(gpx=str(gpx), puissance=200.0, depart=_demain("06:00")),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    sortie = capsys.readouterr()
    charge = json.loads(sortie.out)
    # Les trois traces, trou compris en ligne droite : 70 km, pas 20.
    assert charge["distance_km"] == pytest.approx(70.0, rel=0.01)
    assert charge["nom"] == "Étape 1"
    assert charge["avertissements_trace"] == [
        "3 traces enchaînées, dans l'ordre du fichier",
        "un trou de 12 km entre la trace 2 et la trace 3, compté en ligne droite dans "
        "la distance et la durée",
    ]
    assert "un trou de 12 km" in sortie.err

"""Les sous-commandes `ourouler calibrer` et `ourouler simuler`, et la colonne « temps ».

Rien ne sort sur le réseau : l'archive météo est un `MockTransport`, le cache
est construit dans `tmp_path` à partir de sorties fabriquées par le modèle.
Aucune coordonnée réelle : tout part du point (0, 0).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from test_physique_calibration import VRAI, sortie_synthetique

from ourouler.activites.cache import Cache
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.cli import main
from ourouler.commandes.physique import calibrer_depuis_namespace as executer_calibrer
from ourouler.commandes.physique import simuler_depuis_namespace as executer_simuler
from ourouler.config import Config, Velo, depuis_dict
from ourouler.connecteurs.openmeteo_archive import ClientArchive
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.physique import litterature
from ourouler.physique.modele import Parametres
from ourouler.physique.parametres_velo import (
    ALERTE_PNEU_CHANGE,
    CDA_DEFAUT,
    Calibration,
    crr_du_velo,
    fourchette_defaut,
)
from ourouler.services.physique import (
    alerte_calibration,
    chemin_calibration,
    ecrire_calibration,
    fourchette_du_velo,
    lire_calibration,
    parametres_du_velo,
    velo_demande,
)
from ourouler.stockage.calibrations import VERSION_CALIBRATION

METRE_EN_DEGRE = 1.0 / 111_194.93


def config_de_test(dossier: Path, **sections) -> Config:
    brute = {
        "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
        "cycliste": {"masse_kg": 91, "ftp_w": 258},
        "velos": [
            {"nom": "RCR", "usage": "route", "capteur_puissance": "CAPTEUR 0001"},
            {"nom": "BMC", "usage": "clm", "capteur_puissance": "CAPTEUR 0002"},
        ],
        "cache": {"dossier": str(dossier)},
        "boucle": {"vitesse_moyenne_kmh": 27.0},
    }
    return depuis_dict({**brute, **sections})


def args(**champs) -> argparse.Namespace:
    defauts = {"velo": None, "depuis": None, "max": None, "json": False}
    return argparse.Namespace(**{**defauts, **champs})


# --- calibration.json ---------------------------------------------------------


def test_ecrire_puis_relire(tmp_path: Path):
    chemin = tmp_path / "calibration.json"
    ecrire_calibration(
        chemin,
        "RCR",
        {
            "cda_m2": 0.31,
            "crr": 0.0045,
            "masse_totale_kg": 100.0,
            "date": "2026-09-13",
            "n_sorties": 74,
            "mae": 0.048,
        },
    )
    lue = lire_calibration(chemin, "RCR")
    assert isinstance(lue, Calibration)
    assert lue.parametres.cda_m2 == 0.31
    assert lue.parametres.crr == 0.0045
    assert lue.n_sorties == 74
    assert "0,048" not in lue.resume and "4.8 %" in lue.resume


def test_calibrer_un_velo_n_efface_pas_l_autre(tmp_path: Path):
    chemin = tmp_path / "calibration.json"
    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0})
    ecrire_calibration(chemin, "BMC", {"cda_m2": 0.26, "crr": 0.0040, "masse_totale_kg": 99.0})
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    assert set(charge["velos"]) == {"RCR", "BMC"}
    assert lire_calibration(chemin, "RCR").parametres.cda_m2 == 0.31
    assert lire_calibration(chemin, "BMC").parametres.cda_m2 == 0.26


@pytest.mark.parametrize(
    "contenu",
    [
        "",
        "pas du json",
        '{"version": 999, "velos": {"RCR": {"cda_m2": 0.3, "crr": 0.005, "masse_totale_kg": 100}}}',
        '{"version": 1, "velos": []}',
        '{"version": 1, "velos": {"RCR": {"cda_m2": "beaucoup"}}}',
        '{"version": 1, "velos": {"RCR": {"cda_m2": 0.3}}}',
    ],
)
def test_un_fichier_de_calibration_abime_ne_leve_rien(tmp_path: Path, contenu: str):
    chemin = tmp_path / "calibration.json"
    chemin.write_text(contenu, encoding="utf-8")
    assert lire_calibration(chemin, "RCR") is None


def test_calibration_absente(tmp_path: Path):
    assert lire_calibration(tmp_path / "jamais_ecrit.json", "RCR") is None


def test_la_version_est_ecrite(tmp_path: Path):
    chemin = tmp_path / "calibration.json"
    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0})
    assert json.loads(chemin.read_text())["version"] == VERSION_CALIBRATION


# --- choix du vélo et des paramètres ------------------------------------------


def test_velo_demande(tmp_path: Path):
    config = config_de_test(tmp_path)
    assert velo_demande(config, None).nom == "RCR"  # premier vélo d'usage route
    assert velo_demande(config, "bmc").nom == "BMC"  # insensible à la casse


def test_parametres_du_velo_par_provenance(tmp_path: Path):
    config = config_de_test(tmp_path)
    chemin = chemin_calibration(config)
    velo = config.velo("RCR")

    # Rien de mesuré, rien de configuré : la table de littérature de l'usage,
    # et non plus les constantes muettes du module (18/09/2026).
    parametres, provenance = parametres_du_velo(config, velo, chemin)
    assert provenance == "littérature"
    assert parametres.cda_m2 == litterature.ROUTE_AMATEUR_HAUT.cda_m2
    assert parametres.masse_totale_kg == 91.0 + 9.0  # vélo sans masse déclarée

    # Le dernier recours reste, pour un usage qu'aucune catégorie ne couvre.
    hors_table = Velo(nom="Le gravel", usage="gravel")
    parametres, provenance = parametres_du_velo(config, hors_table, chemin)
    assert provenance == "défaut"
    assert parametres.cda_m2 == CDA_DEFAUT

    configure = config_de_test(
        tmp_path,
        velos=[{"nom": "RCR", "usage": "route", "cda_m2": 0.29, "crr": 0.004, "masse_kg": 8.0}],
    )
    parametres, provenance = parametres_du_velo(
        configure, configure.velo("RCR"), chemin_calibration(configure)
    )
    assert provenance == "configuration"
    assert (parametres.cda_m2, parametres.crr, parametres.masse_totale_kg) == (0.29, 0.004, 99.0)

    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.33, "crr": 0.0052, "masse_totale_kg": 100.0})
    parametres, provenance = parametres_du_velo(config, velo, chemin)
    assert provenance == "calibration"
    assert parametres.cda_m2 == 0.33


# --- ourouler calibrer, de bout en bout ---------------------------------------


def archive_bouchonnee(vent_kmh: float = 0.0, depuis_deg: float = 0.0) -> ClientArchive:
    """L'archive Open-Meteo, bouchonnée : 24 heures constantes, quel que soit le jour."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        jour = requete.url.params["start_date"]
        return httpx.Response(
            200,
            json={
                "latitude": 0.0,
                "longitude": 0.0,
                "hourly": {
                    "time": [f"{jour}T{h:02d}:00" for h in range(24)],
                    "wind_speed_10m": [vent_kmh] * 24,
                    "wind_direction_10m": [depuis_deg] * 24,
                    "temperature_2m": [15.0] * 24,
                    "surface_pressure": [1013.25] * 24,
                },
            },
        )

    return ClientArchive(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def cache_de_sorties(dossier: Path, jours: list[date], **fabrique) -> Cache:
    """Un cache alimenté de sorties fabriquées par le modèle, une par jour donné."""
    cache = Cache(dossier)
    for jour in jours:
        activite = sortie_synthetique(**fabrique)
        cache.ajouter(
            _en_tcx(activite, jour),
            source="intervals",
            id_externe=f"i{jour.isoformat()}",
            extension="tcx",
            meta={"nom": f"sortie du {jour}", "power_meter": "CAPTEUR 0001", "sport": "Ride"},
        )
    return cache


def _en_tcx(activite, jour: date) -> bytes:
    """La sortie fabriquée, écrite en TCX : c'est le format que le lecteur du
    projet relit avec vitesse, puissance, altitude et position."""
    debut = datetime(jour.year, jour.month, jour.day, 9, 0, tzinfo=UTC)
    decalage = debut - activite.debut
    points = []
    for p in activite.points[::5]:  # 1 point sur 5 : ~5 s, assez pour 200 m
        points.append(
            "<Trackpoint>"
            f"<Time>{(p.t + decalage).isoformat().replace('+00:00', 'Z')}</Time>"
            f"<Position><LatitudeDegrees>{p.lat:.7f}</LatitudeDegrees>"
            f"<LongitudeDegrees>{p.lon:.7f}</LongitudeDegrees></Position>"
            f"<AltitudeMeters>{p.alt_m:.2f}</AltitudeMeters>"
            f"<DistanceMeters>{p.dist_m:.2f}</DistanceMeters>"
            '<Extensions><TPX xmlns="http://www.garmin.com/xmlschemas/ActivityExtension/v2">'
            f"<Speed>{p.vitesse_ms:.3f}</Speed><Watts>{p.puissance_w:.0f}</Watts>"
            "</TPX></Extensions>"
            "</Trackpoint>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="Biking"><Id>{debut.isoformat()}</Id>'
        f'<Lap StartTime="{debut.isoformat()}"><Track>{"".join(points)}</Track></Lap>'
        "</Activity></Activities></TrainingCenterDatabase>"
    ).encode()


def test_calibrer_de_bout_en_bout(tmp_path: Path, capsys):
    """Huit sorties fabriquées avec un CdA connu : la commande le retrouve et l'écrit."""
    jours = [date(2026, 1, j) for j in range(1, 9)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(tmp_path / "cache")

    code = executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())
    assert code == 0
    texte = capsys.readouterr().out
    assert "Calibration RCR" in texte
    assert "CdA" in texte and "Crr" in texte
    assert "temps en mouvement" in texte

    lue = lire_calibration(chemin_calibration(config), "RCR")
    assert lue is not None
    assert lue.parametres.cda_m2 == pytest.approx(VRAI.cda_m2, rel=0.10)
    assert lue.parametres.masse_totale_kg == 100.0
    assert lue.mae is not None and lue.mae < 0.05


def test_calibrer_en_json(tmp_path: Path, capsys):
    jours = [date(2026, 1, j) for j in range(1, 7)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    executer_calibrer(args(velo="RCR", json=True), config, client_archive=archive_bouchonnee())
    charge = json.loads(capsys.readouterr().out)
    assert charge["velo"] == "RCR"
    assert charge["ajustement"]["cda_m2"] == pytest.approx(VRAI.cda_m2, rel=0.10)
    assert charge["validation"]["n"] >= 1
    assert charge["archives"]["appels"] >= 1
    assert charge["apprentissage"]["echantillons"] > 0


def test_calibrer_sans_sortie(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="aucune sortie calibrable"):
        executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())


def test_calibrer_refuse_sans_ftp(tmp_path: Path):
    """Point 5 (T5) : `calibrer_en_deux_passes` garde `ftp_w: float = 250.0` non
    optionnel — ce n'est pas son rôle de deviner. Le refus se fait en amont,
    avant même de lire le cache, avec un message qui nomme la FTP plutôt que
    de laisser filer un `TypeError` sur `zone_w` ou l'appel de calibration."""
    config = config_de_test(tmp_path / "cache", cycliste={"masse_kg": 91})
    assert config.cycliste.ftp_w is None
    with pytest.raises(ErreurUtilisateur, match="FTP"):
        executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())


def test_calibrer_survit_a_une_archive_en_panne(tmp_path: Path, capsys):
    """L'archive muette ne doit pas empêcher de calibrer : on le dit, on continue."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": True, "reason": "maintenance"})

    en_panne = ClientArchive(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))
    cache_de_sorties(tmp_path / "cache", [date(2026, 1, j) for j in range(1, 7)], duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    assert executer_calibrer(args(velo="RCR"), config, client_archive=en_panne) == 0
    capture = capsys.readouterr()
    assert "archive météo" in capture.err
    assert "sans vent archivé" in capture.out


def test_calibrer_un_velo_inconnu(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="aucun vélo"):
        executer_calibrer(args(velo="Gravel"), config, client_archive=archive_bouchonnee())


def test_depuis_invalide(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="AAAA-MM-JJ"):
        executer_calibrer(args(velo="RCR", depuis="hier"), config, client_archive=archive_bouchonnee())


# --- ourouler simuler ---------------------------------------------------------


def gpx_plat(chemin: Path, longueur_m: float = 20_000.0) -> Path:
    points = [
        PointTrace(lat=0.0, lon=d * METRE_EN_DEGRE, alt_m=100.0, dist_m=float(d))
        for d in range(0, int(longueur_m) + 1, 100)
    ]
    trace = Trace("boucle d'essai", points, [], longueur_m, 0.0, None)
    chemin.write_text(ecrire_gpx(trace, trace.nom), encoding="utf-8")
    return chemin


def args_simuler(**champs) -> argparse.Namespace:
    defauts = {
        "gpx": None,
        "puissance": 200.0,
        "vitesse_a_plat": None,
        "velo": None,
        "depart": None,
        "json": False,
    }
    return argparse.Namespace(**{**defauts, **champs})


def test_simuler_sans_calibration_le_dit(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    assert executer_simuler(args_simuler(gpx=str(gpx)), config) == 0
    texte = capsys.readouterr().out
    assert "(littérature)" in texte
    assert "n'ont pas été mesurés" in texte
    # Ce que vaut la catégorie servie, mesuré — pas seulement son nom.
    assert "route amateur, haut de fourchette" in texte
    assert "Dérive mesurée" in texte
    assert "Temps en mouvement" in texte


def test_simuler_avec_la_calibration(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0, "date": "2026-09-13"},
    )
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    executer_simuler(args_simuler(gpx=str(gpx), json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["parametres"]["provenance"] == "calibration"
    assert charge["parametres"]["cda_m2"] == 0.31
    assert charge["arrets_modelises"] is False
    # 20 km plats à 200 W avec ces paramètres : entre 30 et 40 km/h.
    assert 30.0 < charge["vitesse_moy_kmh"] < 40.0
    assert charge["temps_mouvement_s"] == pytest.approx(20_000 / (charge["vitesse_moy_kmh"] / 3.6), rel=0.01)


def test_simuler_refuse_une_puissance_absurde(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    for puissance in (0.0, -100.0, 5000.0):
        with pytest.raises(ErreurUtilisateur, match="puissance"):
            executer_simuler(args_simuler(gpx=str(gpx), puissance=puissance), config)


def test_simuler_refuse_un_gpx_absent(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="introuvable"):
        executer_simuler(args_simuler(gpx=str(tmp_path / "nulle_part.gpx")), config)


def test_simuler_sans_gpx(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="--gpx"):
        executer_simuler(args_simuler(), config)


# --- --pause sur `simuler` -----------------------------------------------------


def client_meteo_bouchonne(pluie: float = 0.0) -> ClientOpenMeteo:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        lats = p["latitude"].split(",")
        lons = p["longitude"].split(",")
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        blocs = [
            {
                "latitude": float(a),
                "longitude": float(o),
                "hourly": {
                    "time": [(debut + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)],
                    "precipitation": [pluie] * n,
                    "rain": [pluie] * n,
                    "wind_speed_10m": [10.0] * n,
                    "wind_direction_10m": [90.0] * n,
                    "wind_gusts_10m": [15.0] * n,
                    "apparent_temperature": [12.0] * n,
                    "temperature_2m": [14.0] * n,
                },
            }
            for a, o in zip(lats, lons, strict=True)
        ]
        return httpx.Response(200, json=blocs)

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def test_simuler_avec_pause_est_repetable_et_lue(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    code = executer_simuler(
        args_simuler(
            gpx=str(gpx),
            depart="2026-05-16T05:00",
            pause=["5:0h30", "15:0h15"],
            json=True,
        ),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["pauses"] == [
        {"km": 5.0, "duree_s": 1800},
        {"km": 15.0, "duree_s": 900},
    ]
    assert charge["heure_arrivee"] is not None


def test_simuler_l_arrivee_porte_le_total_des_pauses(tmp_path: Path, capsys):
    """Comparaison directe : la seule différence entre les deux arrivées est la pause."""
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)

    executer_simuler(
        args_simuler(gpx=str(gpx), depart="2026-05-16T05:00", json=True),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    sans_pause = json.loads(capsys.readouterr().out)

    executer_simuler(
        args_simuler(gpx=str(gpx), depart="2026-05-16T05:00", pause=["5:0h30"], json=True),
        config,
        client_meteo=client_meteo_bouchonne(),
    )
    avec_pause = json.loads(capsys.readouterr().out)

    t_sans = datetime.fromisoformat(sans_pause["heure_arrivee"])
    t_avec = datetime.fromisoformat(avec_pause["heure_arrivee"])
    assert (t_avec - t_sans) == timedelta(minutes=30)
    # Le temps en mouvement, lui, ne bouge pas : une pause n'est pas un modèle
    # de fatigue, la vitesse reste constante.
    assert avec_pause["temps_mouvement_s"] == sans_pause["temps_mouvement_s"]


def test_simuler_sans_heure_depart_une_pause_ne_change_rien_et_le_dit(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    code = executer_simuler(args_simuler(gpx=str(gpx), pause=["5:0h30"]), config)
    assert code == 0
    capture = capsys.readouterr()
    assert "n'a aucun effet" in capture.err


@pytest.mark.parametrize(
    ("pause", "motif"),
    [
        ("-5:0h30", "kilomètre"),
        ("5:0h0", "durée"),
        ("500:0h30", "au-delà"),
    ],
)
def test_simuler_refuse_une_pause_invalide(tmp_path: Path, pause: str, motif: str):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    with pytest.raises(ErreurUtilisateur, match=motif):
        executer_simuler(args_simuler(gpx=str(gpx), pause=[pause]), config)


def test_simuler_refuse_deux_pauses_au_meme_kilometre(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx", longueur_m=20_000.0)
    with pytest.raises(ErreurUtilisateur, match="même kilomètre"):
        executer_simuler(args_simuler(gpx=str(gpx), pause=["5:0h30", "5:0h15"]), config)


def test_les_sous_commandes_sont_dans_la_cli(tmp_path: Path, capsys):
    """`ourouler calibrer --help` et `ourouler simuler --help` existent et sortent en 0."""
    for commande in ("calibrer", "simuler"):
        with pytest.raises(SystemExit) as sortie:
            main([commande, "--help"])
        assert sortie.value.code == 0
        assert commande in capsys.readouterr().out


def test_la_calibration_lue_sert_bien_de_parametres(tmp_path: Path, capsys):
    """Deux CdA différents doivent donner deux temps différents, pas le même."""
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    temps = []
    for cda in (0.25, 0.45):
        ecrire_calibration(
            chemin_calibration(config),
            "RCR",
            {"cda_m2": cda, "crr": 0.0045, "masse_totale_kg": 100.0},
        )
        executer_simuler(args_simuler(gpx=str(gpx), json=True), config)
        temps.append(json.loads(capsys.readouterr().out)["temps_mouvement_s"])
    assert temps[0] < temps[1]


def test_parametres_est_bien_un_parametres(tmp_path: Path):
    chemin = tmp_path / "calibration.json"
    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0})
    assert isinstance(lire_calibration(chemin, "RCR").parametres, Parametres)


# --- vent de prévision ramené à hauteur de cycliste (point 1 de la relecture) --


def _meteo_a_vent_constant(vent_kmh: float, depuis_deg: float):
    """Un `MeteoTrace` minimal : un seul échantillon, au vent connu."""
    from ourouler.boucle.meteo_trace import Echantillon as EchantillonMeteo
    from ourouler.boucle.meteo_trace import MeteoTrace

    return MeteoTrace(
        echantillons=[
            EchantillonMeteo(
                dist_m=0.0,
                t=datetime(2026, 3, 15, 9, 0, tzinfo=UTC),
                lat=0.0,
                lon=0.0,
                cap_deg=90.0,
                pluie_mm=0.0,
                vent_kmh=vent_kmh,
                vent_relatif="face",
                ressenti_c=12.0,
                vent_depuis_deg=depuis_deg,
            )
        ],
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=1.0,
        part_vent_dos=0.0,
        ressenti_min_c=12.0,
        confiance="bonne",
        n_vent_connu=1,
    )


def test_vent_prevu_est_ramene_a_hauteur_de_cycliste():
    """18 km/h de face prévus à 10 m valent 0,6 × 5 m/s pour le cycliste.

    Pendant exact de ce que la calibration fait sur l'archive : le modèle est
    calibré avec un vent converti, il doit être utilisé avec un vent converti.
    """
    from ourouler.physique.modele import vent_au_cycliste
    from ourouler.services.physique import vent_depuis_meteo

    face = vent_depuis_meteo(_meteo_a_vent_constant(18.0, 90.0))
    assert face is not None
    assert face(0.0, 90.0) == pytest.approx(vent_au_cycliste(5.0), abs=1e-9)
    assert face(0.0, 90.0) == pytest.approx(3.0, abs=1e-9)
    # De dos : le signe survit à la conversion.
    de_dos = vent_depuis_meteo(_meteo_a_vent_constant(18.0, 270.0))
    assert de_dos(0.0, 90.0) == pytest.approx(-3.0, abs=1e-9)


def test_vent_prevu_absent_reste_absent():
    """Un tracé sans vent connu ne fabrique pas un vent nul converti."""
    from ourouler.services.physique import vent_depuis_meteo

    meteo = _meteo_a_vent_constant(18.0, 90.0)
    meteo.echantillons[0].vent_kmh = None
    assert vent_depuis_meteo(meteo) is None


# --- fichiers multisport écartés (point 4 de la relecture, Q10) ---------------


def test_calibrer_ecarte_un_fichier_multisport(tmp_path: Path, capsys):
    """Intervals annonce « Ride », le fichier dit « Running » : c'est le fichier qui tranche.

    C'est la forme que prend un triathlon dans le cache : trois segments
    Intervals qui citent le même enregistrement, dont seul l'un est du vélo.
    """
    cache = cache_de_sorties(tmp_path / "cache", [date(2026, 1, j) for j in range(1, 7)], duree_s=2600)
    octets = _en_tcx(sortie_synthetique(duree_s=2600), date(2026, 2, 1)).replace(
        b'Sport="Biking"', b'Sport="Running"'
    )
    cache.ajouter(
        octets,
        source="intervals",
        id_externe="segment-velo-du-triathlon",
        extension="tcx",
        meta={
            "nom": "segment vélo du triathlon",
            "power_meter": "CAPTEUR 0001",
            "sport": "Ride",
        },
    )
    config = config_de_test(tmp_path / "cache")

    executer_calibrer(args(velo="RCR", json=True), config, client_archive=archive_bouchonnee())
    charge = json.loads(capsys.readouterr().out)
    assert charge["sorties_ecartees"].get("multisport") == 1
    assert charge["sorties_calibrables"] == 6
    assert all("triathlon" not in s["nom"] for s in charge["validation"]["sorties"])


# --- le rapport chiffre la résistance totale (point 5 de la relecture) --------


def test_le_rapport_donne_la_resistance_a_27_et_35(tmp_path: Path, capsys):
    """Ce que les données mesurent passe devant ; CdA et Crr sont relégués au détail."""
    cache_de_sorties(tmp_path / "cache", [date(2026, 1, j) for j in range(1, 9)], duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())
    texte = capsys.readouterr().out

    assert "résistance totale sur le plat sans vent" in texte
    assert "à 27 km/h" in texte and "à 35 km/h" in texte
    assert "N  —" in texte and "W au pédalier" in texte
    # CdA et Crr restent lisibles, mais en ligne secondaire et avec la mise en garde.
    detail = next(ligne for ligne in texte.splitlines() if "CdA" in ligne)
    assert "mal séparé" in detail and "Crr" in detail
    # La résistance vient avant le détail.
    lignes = texte.splitlines()
    assert lignes.index("  résistance totale sur le plat sans vent, vélo + cycliste :") < (
        lignes.index(detail)
    )


def test_la_resistance_est_dans_le_json(tmp_path: Path, capsys):
    cache_de_sorties(tmp_path / "cache", [date(2026, 1, j) for j in range(1, 7)], duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    executer_calibrer(args(velo="RCR", json=True), config, client_archive=archive_bouchonnee())
    charge = json.loads(capsys.readouterr().out)
    resistance = charge["ajustement"]["resistance"]
    assert [r["v_kmh"] for r in resistance] == [27.0, 35.0]
    # Plus vite, c'est plus dur : force et puissance croissent toutes deux.
    assert resistance[1]["force_n"] > resistance[0]["force_n"]
    assert resistance[1]["puissance_w"] > resistance[0]["puissance_w"]
    # Et le fichier de calibration en garde trace.
    ecrit = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))
    assert set(ecrit["velos"]["RCR"]["resistance"]) == {"27", "35"}


def test_la_resistance_ne_depend_que_du_couple_cda_crr(tmp_path: Path):
    """Deux couples (CdA, Crr) qui se compensent donnent la même résistance à 27 km/h.

    C'est toute la raison d'être de cette grandeur : elle est stable là où CdA
    et Crr, pris séparément, ne le sont pas.
    """
    from ourouler.physique.calibration import Ajustement

    def a_27(cda: float, crr: float) -> float:
        return Ajustement(
            cda_m2=cda, crr=crr, masse_totale_kg=100.0, n_echantillons=9, rmse_w=0.0, mae_w=0.0
        ).resistance_a(27.0)[0]

    reference = a_27(0.30, 0.005)
    # Moins de traînée, plus de roulement : à 27 km/h, la somme ne bouge pas.
    v = 27.0 / 3.6
    delta_cda = 0.02
    compensation = 0.5 * 1.226 * delta_cda * v**2 / (100.0 * 9.80665)
    assert a_27(0.30 - delta_cda, 0.005 + compensation) == pytest.approx(reference, rel=1e-6)


# --- L9.1 : pneu, Crr fixé, fourchette du porte à porte -----------------------


def test_le_pneu_donne_le_crr_d_un_velo_jamais_calibre(tmp_path: Path):
    """Sans calibration : le CdA du jeu de l'usage, le Crr du pneu déclaré."""
    config = config_de_test(tmp_path, velos=[{"nom": "RCR", "usage": "route", "pneu": "course_rapide"}])
    parametres, provenance = parametres_du_velo(config, config.velo("RCR"), chemin_calibration(config))
    assert provenance == "littérature"
    assert parametres.cda_m2 == litterature.ROUTE_AMATEUR_HAUT.cda_m2
    assert parametres.crr == litterature.PNEUS["course_rapide"].crr


def test_un_crr_ecrit_a_la_main_passe_avant_le_pneu(tmp_path: Path):
    velo = Velo(nom="RCR", usage="route", crr=0.0042, pneu="vtt")
    assert crr_du_velo(velo) == (0.0042, "configuration")
    assert crr_du_velo(Velo(nom="RCR", pneu="vtt")) == (0.012, "pneu")
    assert crr_du_velo(Velo(nom="RCR")) is None


def test_calibrer_avec_un_pneu_fixe_le_crr_et_le_dit(tmp_path: Path, capsys):
    """Le Crr du pneu est gardé tel quel, seul le CdA est cherché, et
    calibration.json dit d'où vient le Crr (`crr_source`)."""
    jours = [date(2026, 1, j) for j in range(1, 9)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(
        tmp_path / "cache",
        velos=[
            {
                "nom": "RCR",
                "usage": "route",
                "capteur_puissance": "CAPTEUR 0001",
                "pneu": "course_rapide",
            }
        ],
    )
    executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())
    texte = capsys.readouterr().out
    assert "fixé (pneu course rapide" in texte
    assert "mal séparé" not in texte
    brut = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))["velos"]["RCR"]
    assert brut["crr"] == litterature.PNEUS["course_rapide"].crr
    assert brut["crr_source"] == "pneu"
    assert brut["pneu"] == "course_rapide"


def test_calibrer_crr_libre_garde_l_ancien_ajustement(tmp_path: Path, capsys):
    jours = [date(2026, 1, j) for j in range(1, 9)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(
        tmp_path / "cache",
        velos=[{"nom": "RCR", "usage": "route", "capteur_puissance": "CAPTEUR 0001", "pneu": "vtt"}],
    )
    executer_calibrer(args(velo="RCR", crr_libre=True), config, client_archive=archive_bouchonnee())
    assert "mal séparé" in capsys.readouterr().out
    brut = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))["velos"]["RCR"]
    assert brut["crr_source"] == "ajuste"
    assert brut["pneu"] is None
    assert brut["crr"] != litterature.PNEUS["vtt"].crr


def test_calibrer_ecrit_la_fourchette_du_porte_a_porte(tmp_path: Path, capsys):
    """Trente-deux sorties, donc huit en validation : la fourchette est mesurée
    sur ces huit-là seulement, écrite, et relue par `fourchette_du_velo` avec
    la provenance « mesure »."""
    jours = [date(2026, 1, 1) + timedelta(days=j) for j in range(32)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    executer_calibrer(args(velo="RCR", json=True), config, client_archive=archive_bouchonnee())
    charge = json.loads(capsys.readouterr().out)
    assert charge["porte_a_porte"]["n"] == 8
    assert charge["porte_a_porte"]["n_total"] == 8  # la validation, pas les 32
    assert charge["porte_a_porte"]["sorties"] == "validation"
    assert charge["porte_a_porte"]["base"] == "temps_ecoule"
    brut = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))["velos"]["RCR"]
    pp = brut["porte_a_porte"]
    assert pp["centiles"] == [25, 50, 75]
    assert pp["seuil_groupe"] == 0.5
    assert pp["bas"] <= pp["mediane"] <= pp["haut"]
    # Des sorties fabriquées par le modèle, sans arrêt : ratio ≈ 1.
    assert pp["mediane"] == pytest.approx(1.0, abs=0.05)
    fourchette = fourchette_du_velo(config.velo("RCR"), chemin_calibration(config))
    assert fourchette.provenance == "mesure"
    assert fourchette.n == 8
    assert fourchette.mediane == pp["mediane"]


def test_trop_peu_de_sorties_laisse_la_convention(tmp_path: Path, capsys):
    jours = [date(2026, 1, j) for j in range(1, 5)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(tmp_path / "cache")
    executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())
    assert "la fourchette par défaut (convention) reste en vigueur" in capsys.readouterr().out
    brut = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))["velos"]["RCR"]
    assert brut["porte_a_porte"] is None
    fourchette = fourchette_du_velo(config.velo("RCR"), chemin_calibration(config))
    assert fourchette == fourchette_defaut()
    assert fourchette.provenance == "defaut"


@pytest.mark.parametrize(
    "porte_a_porte",
    [
        {"bas": 1.1, "mediane": 1.0, "haut": 1.2},  # désordonnée
        {"bas": "x", "mediane": 1.0, "haut": 1.2},
        {"mediane": 1.0, "haut": 1.2},
        [1.0, 1.05, 1.1],
    ],
)
def test_une_fourchette_abimee_retombe_sur_la_convention(tmp_path: Path, porte_a_porte):
    config = config_de_test(tmp_path)
    chemin = chemin_calibration(config)
    ecrire_calibration(
        chemin,
        "RCR",
        {"cda_m2": 0.33, "crr": 0.006, "masse_totale_kg": 100.0, "porte_a_porte": porte_a_porte},
    )
    lue = lire_calibration(chemin, "RCR")
    assert lue is not None and lue.porte_a_porte is None
    assert fourchette_du_velo(config.velo("RCR"), chemin).provenance == "defaut"


# --- décisions du mainteneur du 25/09 : Crr écrit figé, pneu changé dit -------


def test_un_crr_ecrit_a_la_main_est_fige_par_calibrer(tmp_path: Path, capsys):
    jours = [date(2026, 1, j) for j in range(1, 9)]
    cache_de_sorties(tmp_path / "cache", jours, duree_s=2600)
    config = config_de_test(
        tmp_path / "cache",
        velos=[{"nom": "RCR", "usage": "route", "capteur_puissance": "CAPTEUR 0001", "crr": 0.0045}],
    )
    executer_calibrer(args(velo="RCR"), config, client_archive=archive_bouchonnee())
    brut = json.loads(chemin_calibration(config).read_text(encoding="utf-8"))["velos"]["RCR"]
    assert brut["crr"] == 0.0045
    assert brut["crr_source"] == "configuration"
    assert "fixé (configuration)" in capsys.readouterr().out


def _calibre_avec(tmp_path: Path, **velo) -> tuple:
    config = config_de_test(tmp_path, velos=[{"nom": "RCR", "usage": "route", **velo}])
    return config, chemin_calibration(config)


def test_pas_d_alerte_quand_le_pneu_n_a_pas_change(tmp_path: Path):
    config, chemin = _calibre_avec(tmp_path, pneu="course_rapide")
    ecrire_calibration(
        chemin,
        "RCR",
        {
            "cda_m2": 0.33,
            "crr": 0.005,
            "masse_totale_kg": 100.0,
            "crr_source": "pneu",
            "pneu": "course_rapide",
        },
    )
    assert alerte_calibration(config.velo("RCR"), chemin) is None


@pytest.mark.parametrize(
    ("velo", "calibration"),
    [
        # Pneu changé.
        ({"pneu": "vtt"}, {"crr_source": "pneu", "pneu": "course_rapide", "crr": 0.005}),
        # Pneu déclaré après une calibration libre.
        ({"pneu": "vtt"}, {"crr_source": "ajuste", "crr": 0.0106}),
        # Pneu retiré.
        ({}, {"crr_source": "pneu", "pneu": "course_rapide", "crr": 0.005}),
        # Crr écrit à la main, modifié depuis.
        ({"crr": 0.004}, {"crr_source": "configuration", "crr": 0.005}),
    ],
)
def test_la_calibration_qui_ne_suit_plus_le_pneu_le_dit_et_reste_utilisee(
    tmp_path: Path, velo: dict, calibration: dict
):
    config, chemin = _calibre_avec(tmp_path, **velo)
    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.33, "masse_totale_kg": 100.0, **calibration})
    assert alerte_calibration(config.velo("RCR"), chemin) == ALERTE_PNEU_CHANGE
    _parametres, provenance = parametres_du_velo(config, config.velo("RCR"), chemin)
    assert provenance == "calibration"  # gardée, pas jetée


def test_une_calibration_ancienne_sans_pneu_ne_dit_rien(tmp_path: Path):
    config, chemin = _calibre_avec(tmp_path)
    ecrire_calibration(chemin, "RCR", {"cda_m2": 0.22, "crr": 0.0106, "masse_totale_kg": 100.0})
    assert alerte_calibration(config.velo("RCR"), chemin) is None


def test_simuler_dit_que_le_pneu_a_change(tmp_path: Path, capsys):
    config, chemin = _calibre_avec(tmp_path, pneu="vtt")
    ecrire_calibration(
        chemin,
        "RCR",
        {
            "cda_m2": 0.33,
            "crr": 0.005,
            "masse_totale_kg": 100.0,
            "crr_source": "pneu",
            "pneu": "course_rapide",
        },
    )
    executer_simuler(args_simuler(gpx=str(gpx_plat(tmp_path / "plat.gpx"))), config)
    assert ALERTE_PNEU_CHANGE in capsys.readouterr().out

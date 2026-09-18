"""Tests de la sous-commande `ourouler boucle` (L2.6).

Configuration de test au point fictif (0.0, 0.0), `[brouter] url` inventée,
les deux clients bouchonnés par un `httpx.MockTransport` : aucun accès
réseau, aucune coordonnée réelle, aucun identifiant.

Les réponses BRouter viennent du générateur de fixtures
(`tests/fixtures/generer_brouter.py`, via `test_brouter.reponse_fabriquee`) ;
les réponses Open-Meteo sont fabriquées ici, au format relevé au sprint 1.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_brouter import reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.boucle.commande import (
    MARQUE_RETENUE,
    TITRE_ANTENNES_DETECTEES,
    TITRE_ANTENNES_RETIREES,
    Demande,
    Evaluation,
    _info_compteur,
    direction_en_azimut,
    executer,
    lire_options,
    rendre_json,
    rendre_texte,
)
from ourouler.boucle.couts import Couts
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.boucle.trace import PointTrace, Trace
from ourouler.cli import construire_parseur, main
from ourouler.config import Config, depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.physique.modele import PART_ARRET_REFERENCE, temps_ecoule

CONFIG_BRUTE = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
    "meteo": {
        "directions": 8,
        "distances_km": [15],
        "modele": "modele_principal_test",
        "second_avis": "modele_second_test",
        "horizon_h": 6,
    },
    "brouter": {
        "url": "https://brouter.exemple.test",
        "utilisateur": "utilisateur-test",
        "mot_de_passe": "mot-de-passe-de-test",
        "profil": "fastbike",
        "timeout_s": 5.0,
    },
    "boucle": {"vitesse_moyenne_kmh": 27.0, "sens": "horaire", "candidates": 3},
}

CONFIG_TOML = """
[depart]
nom = "Point zéro"
latitude = 0.0
longitude = 0.0
[cycliste]
masse_kg = 80
ftp_w = 250
"""


def config_de_test(**sections: Any) -> Config:
    brute = {**CONFIG_BRUTE, **sections}
    return depuis_dict(brute)


def args(**champs) -> argparse.Namespace:
    defauts = {
        "distance": 60.0,
        "direction": "NE",
        "depart": "2026-09-13T09:00",
        "candidates": None,
        "profil": None,
        "sortie": None,
        "ecraser": False,
        "gpx": None,
        "json": False,
        "velo": None,
        "puissance": None,
    }
    return argparse.Namespace(**{**defauts, **champs})


# --- moteurs bouchonnés -------------------------------------------------------


def moteur_brouter(longueur_par_azimut: dict[float, float] | None = None) -> ClientBrouter:
    """BRouter bouchonné : une boucle fabriquée dont la longueur dépend de l'azimut."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        azimut = float(requete.url.params["roundTripStartDirection"])
        charge = reponse_fabriquee()
        entite = charge["features"][0]
        longueur = (longueur_par_azimut or {}).get(azimut, 60_000.0)
        entite["properties"]["track-length"] = str(round(longueur))
        return httpx.Response(200, json=charge)

    params = config_de_test().brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def bloc_meteo(lat: float, lon: float, n: int, pluie: float) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-13T{6 + i:02d}:00" for i in range(n)],
            "precipitation": [pluie] * n,
            "rain": [pluie] * n,
            "wind_speed_10m": [14.0] * n,
            "wind_direction_10m": [45.0] * n,
            "wind_gusts_10m": [25.0] * n,
            "apparent_temperature": [11.5] * n,
            "temperature_2m": [14.0] * n,
        },
    }


def moteur_meteo(pluie: float = 0.0, en_panne: bool = False) -> ClientOpenMeteo:
    """Open-Meteo bouchonné. `en_panne` : le service répond 503 à tout."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if en_panne:
            return httpx.Response(503, json={"error": True, "reason": "maintenance"})
        p = requete.url.params
        lats = p["latitude"].split(",")
        lons = p["longitude"].split(",")
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        return httpx.Response(
            200,
            json=[bloc_meteo(float(a), float(o), n, pluie) for a, o in zip(lats, lons, strict=True)],
        )

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def lignes_du_tableau(sortie: str) -> list[str]:
    """Les lignes de candidates du tableau texte : après l'en-tête, jusqu'au premier non-chiffre.

    L'en-tête de la commande contient lui aussi « 60 km » et la ligne
    « → retenue : … » commence comme une ligne marquée : on repère donc le
    tableau par sa ligne de titres, puis on ne garde que les lignes dont le
    premier jeton est un numéro.
    """
    lignes = sortie.splitlines()
    debut = next(i for i, ligne in enumerate(lignes) if "n°" in ligne and "distance" in ligne)
    gardees = []
    for ligne in lignes[debut + 1 :]:
        jetons = ligne.replace(MARQUE_RETENUE, " ").split()
        if not jetons or not jetons[0].isdigit():
            break
        gardees.append(ligne)
    return gardees


# --- la direction -------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [("N", 0.0), ("NE", 45.0), ("E", 90.0), ("NO", 315.0), ("ne", 45.0), ("NNE", 22.5)],
)
def test_une_direction_nommee_devient_un_azimut(texte: str, attendu: float):
    libelle, azimut = direction_en_azimut(texte)
    assert azimut == pytest.approx(attendu)
    assert libelle == texte.upper()


@pytest.mark.parametrize(("texte", "attendu"), [("45", 45.0), ("45°", 45.0), ("0", 0.0), ("370", 10.0)])
def test_un_azimut_en_degres_est_accepte(texte: str, attendu: float):
    assert direction_en_azimut(texte)[1] == pytest.approx(attendu)


def test_la_notation_anglaise_du_ouest_est_toleree():
    assert direction_en_azimut("NW")[1] == pytest.approx(315.0)


@pytest.mark.parametrize("mauvais", ["", "   ", "nord-est", "XY", "nan", "inf"])
def test_une_direction_illisible_est_refusee(mauvais: str):
    with pytest.raises(ErreurUtilisateur, match="direction"):
        direction_en_azimut(mauvais)


# --- erreurs utilisateur, avant tout appel réseau -----------------------------


def test_sans_distance_ni_gpx_erreur_utilisateur():
    with pytest.raises(ErreurUtilisateur, match="--distance"):
        lire_options(args(distance=None), config_de_test())


def test_sans_direction_ni_gpx_la_demande_balaie_tout_l_horizon():
    """Q47 : ce n'était pas un choix de conception, `boucle` n'avait jamais appris à balayer.

    `sortie` (avec séance) balaie déjà les huit directions quand rien n'est
    demandé ; `boucle` (sortie libre) refusait — « --direction … est
    obligatoire » — alors que rien ne le justifiait. Sans direction, la
    demande doit maintenant se construire comme `sortie` le fait : un
    libellé vide, aucun azimut fixé, à charge pour la génération de
    balayer.
    """
    demande = lire_options(args(direction=None), config_de_test())
    assert demande.direction == ""
    assert demande.azimut_deg is None


def test_sans_direction_l_execution_bout_en_bout_balaie_les_azimuts(tmp_path, monkeypatch, capsys):
    """Q47, vérifié en bout en bout : le refus disparaît, et les candidates
    sont réparties sur l'horizon plutôt qu'entassées sur un seul azimut —
    exactement le défaut que `boucle.candidates.azimuts` (±20°, ±40°…)
    aurait produit avec un seul appel.
    """
    monkeypatch.chdir(tmp_path)
    config = config_de_test(boucle={"vitesse_moyenne_kmh": 27.0, "sens": "horaire", "candidates": 3})
    code = executer(args(direction=None, json=True), config, moteur_brouter(), moteur_meteo())
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    azimuts = sorted(c["azimut_deg"] for c in charge["candidates"])
    assert len(azimuts) == 3
    # `pas = 360 / 3 = 120°` : les trois candidates doivent se répartir aux
    # trois azimuts, pas s'entasser sur un seul.
    assert azimuts == pytest.approx([0.0, 120.0, 240.0])
    assert charge["demande"]["direction"] is None
    assert charge["demande"]["azimut_deg"] is None


@pytest.mark.parametrize("distance", [0.0, -10.0])
def test_une_distance_nulle_ou_negative_est_refusee(distance: float):
    with pytest.raises(ErreurUtilisateur, match="--distance"):
        lire_options(args(distance=distance), config_de_test())


def test_brouter_non_renseigne_est_refuse_avant_tout_appel():
    config = depuis_dict({k: v for k, v in CONFIG_BRUTE.items() if k != "brouter"})
    with pytest.raises(ErreurUtilisateur, match="brouter"):
        lire_options(args(), config)


def test_un_gpx_introuvable_est_refuse(tmp_path: Path):
    with pytest.raises(ErreurUtilisateur, match="introuvable"):
        lire_options(args(gpx=str(tmp_path / "absent.gpx")), config_de_test())


def test_un_gpx_illisible_est_refuse(tmp_path: Path):
    fichier = tmp_path / "casse.gpx"
    fichier.write_text("ceci n'est pas du GPX", encoding="utf-8")
    with pytest.raises(ErreurUtilisateur, match="GPX"):
        executer(args(gpx=str(fichier)), config_de_test(), moteur_brouter(), moteur_meteo())


def test_les_erreurs_sortent_en_code_2_par_la_cli(tmp_path: Path, capsys):
    """Bout en bout : aucun client injecté, donc l'erreur doit tomber avant le réseau."""
    fichier = tmp_path / "c.toml"
    fichier.write_text(CONFIG_TOML, encoding="utf-8")
    assert main(["--config", str(fichier), "boucle", "--direction", "NE"]) == 2
    assert "--distance" in capsys.readouterr().err


def test_brouter_non_renseigne_sort_en_code_2_par_la_cli(tmp_path: Path, capsys):
    fichier = tmp_path / "c.toml"
    fichier.write_text(CONFIG_TOML, encoding="utf-8")
    code = main(["--config", str(fichier), "boucle", "--distance", "60", "--direction", "NE"])
    assert code == 2
    assert "brouter" in capsys.readouterr().err


# --- le tableau ---------------------------------------------------------------


def test_le_tableau_montre_les_candidates_demandees(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = executer(args(candidates=3), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 3, sortie


def test_cinq_candidates_demandees_cinq_rendues_moteur_qui_ne_converge_pas(
    tmp_path: Path, monkeypatch, capsys
):
    """La commande donne au générateur un plafond d'appels à la hauteur de la demande.

    Sans cela, cinq directions demandées en rendaient trois dès que le moteur
    n'atteignait pas la distance voulue — et l'utilisateur ne voyait que le
    tableau, pas la raison.
    """
    monkeypatch.chdir(tmp_path)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        # 50 km quel que soit le rayon demandé : chaque azimut épuise ses
        # ajustements sans jamais entrer dans la tolérance.
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = "50000"
        return httpx.Response(200, json=charge)

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    code = executer(args(candidates=5), config_de_test(), brouter, moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 5, sortie


def test_les_colonnes_du_contrat_sont_toutes_la(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo(pluie=0.5))
    sortie = capsys.readouterr().out
    for titre in (
        "n°", "distance", "D+", "temps", "trafic", "non revêtu",
        TITRE_ANTENNES_RETIREES, "virages G", "sens",
    ):
        assert titre in sortie
    for titre in ("pluie", "vent face", "ressenti min"):
        assert titre in sortie


def test_le_tableau_est_trie_par_score_plus_pluie(tmp_path: Path, monkeypatch, capsys):
    """La meilleure candidate est en tête, et le n° 1 porte la marque."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    lignes = lignes_du_tableau(sortie)
    assert lignes[0].startswith(MARQUE_RETENUE), sortie
    assert lignes[0].split()[1] == "1"
    assert not any(ligne.startswith(MARQUE_RETENUE) for ligne in lignes[1:])
    assert f"{MARQUE_RETENUE} retenue : n° 1" in sortie


def test_le_tri_suit_bien_le_total_annonce(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(pluie=0.4))
    charge = json.loads(capsys.readouterr().out)
    totaux = [c["total_tri"] for c in charge["candidates"]]
    assert totaux == sorted(totaux)
    for candidate in charge["candidates"]:
        attendu = candidate["couts"]["score"] + candidate["meteo"]["pluie_cumulee_mm"] * 2
        assert candidate["total_tri"] == pytest.approx(attendu, abs=1e-3)


def test_le_temps_estime_suit_la_vitesse_de_la_configuration(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    candidate = charge["candidates"][0]
    attendu = candidate["distance_km"] / 27.0 * 3600
    assert candidate["temps_estime_s"] == pytest.approx(attendu, abs=1)


# --- le GPX écrit --------------------------------------------------------------


def test_la_meilleure_est_ecrite_dans_le_dossier_courant(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    ecrits = list(tmp_path.glob("*.gpx"))
    assert len(ecrits) == 1
    assert ecrits[0].name == "boucle_NE_60km_20260913-0900.gpx"
    assert "<trkpt" in ecrits[0].read_text(encoding="utf-8")
    assert ecrits[0].name in capsys.readouterr().out


def test_sortie_choisie_par_l_utilisateur(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"
    executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    assert voulu.is_file()
    assert list(tmp_path.glob("*.gpx")) == [voulu]


def test_la_colonne_vent_face_dit_sur_combien_d_echantillons(tmp_path: Path, monkeypatch, capsys):
    """Point 18 : « vent face 100 % » ne distinguait pas 12 sur 12 d'un seul sur 12.

    Le bouchon météo n'a que quelques heures de série : les échantillons de
    fin de boucle tombent hors de l'horizon et n'ont pas de vent. C'est
    exactement la situation qui rendait le pourcentage trompeur.
    """
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    trouve = re.search(r"(\d+) % \((\d+)/(\d+)\)", ligne)
    assert trouve, ligne
    connus, total = int(trouve.group(2)), int(trouve.group(3))
    assert connus < total, (
        f"ce bouchon doit produire un dénominateur partiel, reçu {connus}/{total}"
    )


def test_le_denominateur_du_vent_est_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    meteo = json.loads(capsys.readouterr().out)["candidates"][0]["meteo"]
    assert meteo["n_echantillons"] == len(meteo["echantillons"])
    assert 0 < meteo["n_vent_connu"] < meteo["n_echantillons"], meteo["n_vent_connu"]
    # Le pourcentage porte bien sur les seuls échantillons au vent connu.
    connus = [e for e in meteo["echantillons"] if e["vent_relatif"] is not None]
    assert len(connus) == meteo["n_vent_connu"]
    face = [e for e in connus if e["vent_relatif"] == "face"]
    assert meteo["part_vent_face"] == pytest.approx(len(face) / len(connus), abs=1e-3)


def test_les_kilometres_non_classes_sont_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    """Point 15 : `km_trafic + km_calme` peut valoir bien moins que la distance."""
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    couts = charge["candidates"][0]["couts"]
    assert "km_non_classe" in couts
    assert couts["km_non_classe"] >= 0.0


def test_un_trace_surtout_non_classe_le_dit_dans_le_tableau(tmp_path: Path, monkeypatch, capsys):
    """Sans cette ligne, « 0,0 km de trafic » se lit comme « tracé calme »."""
    monkeypatch.chdir(tmp_path)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        proprietes = charge["features"][0]["properties"]
        entete, lignes = proprietes["messages"][0], proprietes["messages"][1:]
        for ligne in lignes:  # colonne WayTags : une classe qu'on ne connaît pas
            ligne[9] = "highway=path surface=asphalt"
        proprietes["messages"] = [entete, *lignes]
        proprietes["track-length"] = "60000"
        return httpx.Response(200, json=charge)

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    executer(args(candidates=1), config_de_test(), brouter, moteur_meteo())
    sortie = capsys.readouterr().out
    assert "non classées" in sortie, sortie


# --- écriture du GPX : refus d'avance et erreurs utilisateur (point 8) --------


def test_un_dossier_de_sortie_inexistant_est_refuse_avant_tout_appel(tmp_path: Path, monkeypatch):
    """Point 8 : le refus doit tomber dans `lire_options`, pas après 22 appels externes."""
    monkeypatch.chdir(tmp_path)
    manquant = tmp_path / "jamais" / "cree" / "x.gpx"
    with pytest.raises(ErreurUtilisateur, match="n'existe pas"):
        lire_options(args(sortie=str(manquant)), config_de_test())


def test_un_dossier_de_sortie_non_inscriptible_est_refuse_avant_tout_appel(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    interdit = tmp_path / "interdit"
    interdit.mkdir()
    interdit.chmod(0o500)
    try:
        with pytest.raises(ErreurUtilisateur, match="écriture impossible"):
            lire_options(args(sortie=str(interdit / "x.gpx")), config_de_test())
    finally:
        interdit.chmod(0o700)


def test_aucun_appel_reseau_quand_la_sortie_est_impossible(tmp_path: Path, monkeypatch):
    """Le refus d'avance doit épargner jusqu'à 12 appels BRouter et 10 Open-Meteo."""
    monkeypatch.chdir(tmp_path)

    def interdit(requete: httpx.Request) -> httpx.Response:
        raise AssertionError(f"aucun appel ne doit partir : {requete.url}")

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(interdit))
    )
    meteo = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(interdit)))
    with pytest.raises(ErreurUtilisateur):
        executer(
            args(sortie=str(tmp_path / "absent" / "x.gpx")), config_de_test(), brouter, meteo
        )


def test_une_ecriture_qui_echoue_sort_en_erreur_utilisateur(tmp_path: Path, monkeypatch):
    """Point 8 : `write_text` hors de tout `try` sortait en `OSError` nue, donc en trace.

    Le dossier est inscriptible au moment de la vérification et ne l'est plus
    à l'écriture : c'est le seul chemin qui reste après le refus d'avance,
    et il doit donner un message, pas une trace.
    """
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"

    def refuser(*a, **kw):
        raise OSError("disque plein")

    monkeypatch.setattr(Path, "write_text", refuser)
    with pytest.raises(ErreurUtilisateur, match="écriture impossible"):
        executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())


def test_un_fichier_de_sortie_existant_n_est_pas_ecrase_sans_ecraser(
    tmp_path: Path, monkeypatch, capsys
):
    """Point 19, tranché par le superviseur : `--sortie` ne remplace pas en silence."""
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"
    executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    ancien = voulu.read_text(encoding="utf-8")

    with pytest.raises(ErreurUtilisateur) as capture:
        executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    assert "ma_boucle.gpx" in str(capture.value), "le message doit nommer le fichier"
    assert "--ecraser" in str(capture.value), "et dire quoi faire"
    assert voulu.read_text(encoding="utf-8") == ancien, "le fichier ne doit pas bouger"

    code = executer(
        args(sortie=str(voulu), ecraser=True), config_de_test(), moteur_brouter(), moteur_meteo()
    )
    assert code == 0 and voulu.is_file()


def test_le_nom_par_defaut_horodate_est_ecrase_sans_question(tmp_path: Path, monkeypatch, capsys):
    """Il porte l'heure à la minute : la collision est improbable, et sans enjeu."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    (ecrit,) = list(tmp_path.glob("*.gpx"))
    ecrit.write_text("contenu précédent", encoding="utf-8")

    assert executer(args(), config_de_test(), moteur_brouter(), moteur_meteo()) == 0
    assert "<trkpt" in ecrit.read_text(encoding="utf-8")


# --- le mode --gpx -------------------------------------------------------------


def gpx_de_test(tmp_path: Path) -> Path:
    """Un GPX écrit depuis une boucle fabriquée, relu ensuite par `--gpx`."""
    trace = moteur_brouter().boucle((0.0, 0.0), azimut_deg=45.0, rayon_m=12_000.0)
    chemin = tmp_path / "importee.gpx"
    chemin.write_text(ecrire_gpx(trace, trace.nom), encoding="utf-8")
    return chemin


def test_gpx_importe_evalue_seul_sans_rien_ecrire(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    code = executer(args(gpx=str(chemin)), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Tracé importé" in sortie
    assert list(tmp_path.glob("*.gpx")) == [chemin], "aucun nouveau GPX ne doit être écrit"
    assert len(lignes_du_tableau(sortie)) == 1


def test_gpx_importe_affiche_des_couts_partiels(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    executer(args(gpx=str(chemin), json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["gpx"] is None
    assert len(charge["candidates"]) == 1
    assert charge["candidates"][0]["couts_partiels"] is True
    assert charge["candidates"][0]["meteo"] is not None


def test_la_colonne_d_plus_dit_d_ou_vient_le_chiffre(tmp_path: Path, monkeypatch, capsys):
    """Point 5 de la relecture : « D+ 362 m » ne disait pas moteur ou GPX relu.

    Les deux divergent de 10 à 32 % sur les tracés mesurés, dans les deux
    sens. Sans la provenance, `--gpx` sur le fichier qu'on vient d'écrire
    affiche un autre chiffre que celui inscrit dedans, sans explication.
    """
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    assert "m (moteur)" in ligne, ligne

    chemin = gpx_de_test(tmp_path)
    executer(args(gpx=str(chemin)), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    assert "m (gpx relu)" in ligne, ligne


def test_la_provenance_du_denivele_est_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["candidates"][0]["denivele_source"] == "moteur"

    chemin = gpx_de_test(tmp_path)
    executer(
        args(gpx=str(chemin), json=True), config_de_test(), moteur_brouter(), moteur_meteo()
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["candidates"][0]["denivele_source"] == "gpx relu"


def test_gpx_importe_n_appelle_pas_brouter(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)

    def interdit(requete: httpx.Request) -> httpx.Response:
        raise AssertionError("BRouter ne doit pas être appelé avec --gpx")

    client = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(interdit))
    )
    assert executer(args(gpx=str(chemin)), config_de_test(), client, moteur_meteo()) == 0


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


# --- la météo en panne ne fait pas perdre la boucle ----------------------------


def test_meteo_en_panne_le_tableau_reste_affiche(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = executer(args(), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    capture = capsys.readouterr()
    assert code == 0
    titres = next(ligne for ligne in capture.out.splitlines() if "n°" in ligne and "distance" in ligne)
    for colonne in ("pluie", "vent face", "ressenti min"):
        assert colonne not in titres, "sans météo, les colonnes météo disparaissent"
    assert "météo indisponible" in capture.err
    assert list(tmp_path.glob("*.gpx")), "la boucle reste écrite malgré la panne météo"


def test_meteo_en_panne_le_json_dit_null(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    charge = json.loads(capsys.readouterr().out)
    assert all(c["meteo"] is None for c in charge["candidates"])
    assert all(c["total_tri"] == pytest.approx(c["couts"]["score"]) for c in charge["candidates"])


# --- le repli de modèle (Q19), sur `boucle` aussi -----------------------------
#
# Le piège de Q19 avait été refermé sur `ourouler sortie` et laissé ouvert sur
# `ourouler boucle` : une boucle demandée à J+3 perdait *toute* sa météo —
# pluie, vent, ressenti — alors que le second avis configuré couvre la
# fenêtre. Les deux commandes appellent le même `meteo_trace.evaluer` ; ces
# tests vérifient qu'elles lui passent le même repli.


def moteur_meteo_hors_de_portee(pluie_du_repli: float = 2.0) -> tuple[ClientOpenMeteo, list[str]]:
    """Open-Meteo bouchonné : le modèle principal rend un bloc nul, le repli répond.

    Un bloc entièrement à `null` est exactement ce qu'Open-Meteo rend pour une
    fenêtre au-delà de la portée d'un modèle régional (diagnostic de Q19). La
    liste rendue nomme, dans l'ordre, les modèles réellement interrogés.
    """
    demandes: list[str] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        modele = p["models"]
        demandes.append(modele)
        lats = p["latitude"].split(",")
        lons = p["longitude"].split(",")
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        if modele == CONFIG_BRUTE["meteo"]["modele"]:
            blocs = [bloc_meteo_nul(float(a), float(o), n) for a, o in zip(lats, lons, strict=True)]
        else:
            blocs = [
                bloc_meteo(float(a), float(o), n, pluie_du_repli)
                for a, o in zip(lats, lons, strict=True)
            ]
        return httpx.Response(200, json=blocs)

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire))), demandes


def bloc_meteo_nul(lat: float, lon: float, n: int) -> dict:
    """Le bloc « hors de portée » : les heures sont là, les valeurs sont `null`."""
    variables = (
        "precipitation",
        "rain",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
        "apparent_temperature",
        "temperature_2m",
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-13T{6 + i:02d}:00" for i in range(n)],
            **{nom: [None] * n for nom in variables},
        },
    }


def test_le_repli_garde_la_meteo_quand_le_modele_principal_ne_couvre_pas(
    tmp_path: Path, monkeypatch, capsys
):
    """Le défaut Q19 lui-même : sans repli, les trois colonnes météo disparaissaient."""
    monkeypatch.chdir(tmp_path)
    meteo, demandes = moteur_meteo_hors_de_portee()
    code = executer(args(), config_de_test(), moteur_brouter(), meteo)
    capture = capsys.readouterr()
    assert code == 0
    assert demandes[:2] == [
        CONFIG_BRUTE["meteo"]["modele"],
        CONFIG_BRUTE["meteo"]["second_avis"],
    ], "le principal est demandé d'abord, puis le repli — jamais l'inverse"
    titres = next(
        ligne for ligne in capture.out.splitlines() if "n°" in ligne and "distance" in ligne
    )
    for colonne in ("pluie", "vent face", "ressenti min"):
        assert colonne in titres, "le repli rend la météo, donc les colonnes"
    assert "météo indisponible" not in capture.err


def test_le_repli_est_nomme_dans_l_entete(tmp_path: Path, monkeypatch, capsys):
    """Un repli silencieux afficherait la pluie d'un modèle sous le nom d'un autre."""
    monkeypatch.chdir(tmp_path)
    meteo, _ = moteur_meteo_hors_de_portee()
    executer(args(), config_de_test(), moteur_brouter(), meteo)
    sortie = capsys.readouterr().out
    assert CONFIG_BRUTE["meteo"]["modele"] in sortie
    assert "bascule sur modele_second_test" in sortie


def test_sans_repli_l_entete_nomme_le_modele_qui_a_repondu(tmp_path: Path, monkeypatch, capsys):
    """Le cas ordinaire ne change pas de forme : le modèle principal est nommé."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert "Météo modele_principal_test, second avis modele_second_test" in sortie
    assert "bascule" not in sortie


def test_le_json_dit_quel_modele_a_repondu_et_si_c_est_un_repli(
    tmp_path: Path, monkeypatch, capsys
):
    """Même forme que `sortie` : un écran lit le repli de la même façon sur les deux routes."""
    monkeypatch.chdir(tmp_path)
    meteo, _ = moteur_meteo_hors_de_portee()
    executer(args(json=True), config_de_test(), moteur_brouter(), meteo)
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_meteo"] == {"utilise": "modele_second_test", "repli": True}
    assert charge["modele"] == "modele_principal_test", "la configuration reste dite telle quelle"


def test_sans_meteo_du_tout_le_modele_utilise_vaut_null(tmp_path: Path, monkeypatch, capsys):
    """Aucune candidate n'a de météo : on ne nomme aucun modèle plutôt qu'un modèle muet."""
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    assert json.loads(capsys.readouterr().out)["modele_meteo"] is None


# --- l'enregistrement dans la CLI ---------------------------------------------


def test_la_sous_commande_est_enregistree_et_accepte_json_apres():
    parseur = construire_parseur()
    args_ = parseur.parse_args(["boucle", "--distance", "60", "--direction", "NE", "--json"])
    assert args_.commande == "boucle"
    assert args_.json is True
    assert args_.distance == 60.0 and args_.direction == "NE"


def test_json_global_avant_la_sous_commande_boucle():
    assert construire_parseur().parse_args(["--json", "boucle"]).json is True


# --- colonne des antennes (L3.1) ----------------------------------------------


def moteur_brouter_avec_antenne() -> ClientBrouter:
    """BRouter bouchonné dont chaque boucle porte un cul-de-sac de 150 m aller-retour."""
    from test_boucle_candidates import anneau_avec_antenne

    points = anneau_avec_antenne()

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        entite = charge["features"][0]
        entite["geometry"]["coordinates"] = points
        entite["properties"]["messages"] = []
        entite["properties"].pop("track-length", None)
        return httpx.Response(200, json=charge)

    params = config_de_test().brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def test_la_colonne_antennes_compte_les_metres_retires(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    lignes = capsys.readouterr().out.splitlines()
    entete = next(ligne for ligne in lignes if TITRE_ANTENNES_RETIREES in ligne)
    assert TITRE_ANTENNES_DETECTEES not in entete
    assert 270 <= _cellule(lignes, entete, TITRE_ANTENNES_RETIREES) <= 330


def test_le_json_porte_les_antennes_retirees(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1, json=True),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["couts"]["antennes_m"] == pytest.approx(300, abs=30)
    assert candidate["antennes"]["nombre"] == 1
    assert candidate["distance_source"] == "recalculee"
    assert candidate["meta"]["denivele_approximatif"] is True


def test_sans_antenne_la_colonne_affiche_zero(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["couts"]["antennes_m"] == 0.0
    assert candidate["antennes"] == {"nombre": 0, "metres_retires": 0.0}
    assert candidate["distance_source"] is None


def _cellule(lignes: list[str], entete: str, titre: str) -> float:
    """La valeur en mètres de la colonne `titre`, sur la ligne suivant l'en-tête.

    Les colonnes sont justifiées à droite : la cellule finit là où finit son
    titre.
    """
    fin = entete.index(titre) + len(titre)
    return float(lignes[lignes.index(entete) + 1][:fin].rsplit(None, 2)[-2])


def test_un_gpx_importe_dit_antennes_detectees_et_non_retirees(
    tmp_path: Path, monkeypatch, capsys
):
    """Un GPX n'est pas élagué : ses antennes sont encore là, le titre le dit."""
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    gpx = next(tmp_path.glob("*.gpx"))
    capsys.readouterr()

    executer(args(gpx=str(gpx), distance=None), config_de_test(), None, moteur_meteo())
    lignes = capsys.readouterr().out.splitlines()
    entete = next(ligne for ligne in lignes if TITRE_ANTENNES_DETECTEES in ligne)
    assert TITRE_ANTENNES_RETIREES not in entete
    # Le GPX écrit vient d'une candidate déjà élaguée : il n'a plus d'antenne.
    assert _cellule(lignes, entete, TITRE_ANTENNES_DETECTEES) == 0.0


def test_le_json_nomme_la_provenance_des_metres_d_antennes(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1, json=True),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    assert json.loads(capsys.readouterr().out)["candidates"][0]["antennes_source"] == "retirees"

    gpx = next(tmp_path.glob("*.gpx"))
    executer(
        args(gpx=str(gpx), distance=None, json=True), config_de_test(), None, moteur_meteo()
    )
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["antennes_source"] == "detectees"
    assert candidate["antennes"] is None

# --- routes connues et poids appris (L3.2) ------------------------------------
#
# `boucle` lit deux fichiers appris dans le dossier de cache — `poids_routes.json`
# et `routes_connues.sqlite` — et passe leur contenu au cœur en objets. La
# colonne « connu % » est **informative** : elle ne doit jamais peser sur le tri.


def config_avec_cache(tmp_path: Path) -> Config:
    return config_de_test(cache={"dossier": str(tmp_path / "cache")})


def base_de_routes(tmp_path: Path, trace) -> None:
    """Apprend un tracé dans la base du cache de test."""
    from datetime import date

    from ourouler.apprentissage.commande import NOM_BASE
    from ourouler.apprentissage.routes import BaseRoutes

    BaseRoutes(tmp_path / "cache" / NOM_BASE).ajouter_trace(
        trace, jour=date(2024, 3, 4), id_sortie="sortie-de-test"
    )


def ecrire_poids_de_test(tmp_path: Path, poids: dict) -> None:
    from ourouler.apprentissage.commande import NOM_POIDS
    from ourouler.apprentissage.routes import ecrire_poids

    ecrire_poids(tmp_path / "cache" / NOM_POIDS, poids)


def test_sans_fichiers_appris_les_colonnes_apprises_disparaissent(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" not in titres, "sans base de routes, la colonne connu % disparaît"
    assert "valeurs par défaut" in sortie


def test_la_colonne_cout_profil_apparait_des_que_le_moteur_le_donne(
    tmp_path: Path, monkeypatch, capsys
):
    """La fixture BRouter porte `CostPerKm` : la colonne doit être là."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "coût profil" in titres
    assert "1200" in sortie


def test_la_colonne_connu_apparait_avec_une_base(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    client = moteur_brouter()
    trace = client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=12_000)
    base_de_routes(tmp_path, trace)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" in titres
    assert "100 %" in sortie, "le tracé appris est reconnu à 100 %"
    assert "informatif, jamais dans le score" in sortie


def test_la_part_connue_n_entre_pas_dans_le_tri(tmp_path: Path, monkeypatch, capsys):
    """Le score doit être identique avec et sans base de routes."""
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sans = json.loads(capsys.readouterr().out)

    client = moteur_brouter()
    base_de_routes(tmp_path, client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=12_000))
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    avec = json.loads(capsys.readouterr().out)

    assert [c["total_tri"] for c in avec["candidates"]] == [
        c["total_tri"] for c in sans["candidates"]
    ]
    assert avec["candidates"][0]["part_connue"] == pytest.approx(1.0, abs=0.01)
    assert sans["candidates"][0]["part_connue"] is None


def test_les_poids_appris_changent_le_score(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    defaut = json.loads(capsys.readouterr().out)
    assert defaut["poids_routes"] is None

    ecrire_poids_de_test(tmp_path, {"primary": 0.0, "secondary": 0.0, "trunk": 0.0})
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    appris = json.loads(capsys.readouterr().out)

    assert appris["poids_routes"] == {"primary": 0.0, "secondary": 0.0, "trunk": 0.0}
    assert appris["candidates"][0]["couts"]["score"] < defaut["candidates"][0]["couts"]["score"]


def test_l_entete_dit_d_ou_viennent_les_poids(tmp_path: Path, monkeypatch, capsys):
    """Et cite les classes **présentes dans le tableau**, pas les plus pénalisées.

    Citer les plus pénalisées donnait une ligne vraie mais inutile
    (« primary_link 4,0 ») : ces classes ne font pas cinquante mètres du tracé.
    """
    monkeypatch.chdir(tmp_path)
    ecrire_poids_de_test(tmp_path, {"secondary": 1.5, "trunk_link": 4.0})
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert "appris sur vos sorties" in sortie
    assert "secondary 1,5" in sortie, "la fixture porte de la secondary : elle doit être citée"
    assert "trunk_link" not in sortie, "une classe absente du tracé n'a rien à faire là"


def test_un_fichier_de_poids_abime_ne_fait_pas_perdre_la_boucle(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "poids_routes.json").write_text("{tronqué", encoding="utf-8")
    assert executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo()) == 0
    assert "valeurs par défaut" in capsys.readouterr().out


def test_une_base_de_routes_abimee_ne_fait_pas_perdre_la_boucle(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "routes_connues.sqlite").write_bytes(b"pas une base" * 50)
    assert executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo()) == 0
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" not in titres


def test_boucle_ne_cree_pas_de_base_de_routes(tmp_path: Path, monkeypatch, capsys):
    """Afficher une colonne informative ne justifie pas d'écrire dans le cache."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    assert not (tmp_path / "cache" / "routes_connues.sqlite").exists()

# --- colonne « temps estimé » (L3.3) ------------------------------------------
#
# Le contrat du sprint 3 §3 : la colonne « temps estimé » vient du modèle
# calibré si `calibration.json` existe, avec la mention `(modèle)` ; sinon la
# vitesse moyenne de la configuration, avec la mention `(27 km/h)`.


def config_avec_velo_calibrable(dossier: Path, **sections: Any) -> Config:
    return config_de_test(
        cache={"dossier": str(dossier)},
        velos=[{"nom": "RCR", "usage": "route"}],
        **sections,
    )


def test_sans_calibration_la_colonne_dit_la_vitesse_moyenne(
    tmp_path: Path, monkeypatch, capsys
):
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    executer(args(velo=None, puissance=None), config, moteur_brouter(), moteur_meteo())
    texte = capsys.readouterr().out
    assert "temps (27 km/h)" in texte
    assert "aucun vélo calibré" in texte


def test_avec_calibration_la_colonne_dit_le_modele(tmp_path: Path, monkeypatch, capsys):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0, "date": "2026-09-13"},
    )
    executer(args(velo=None, puissance=None), config, moteur_brouter(), moteur_meteo())
    texte = capsys.readouterr().out
    assert "temps (modèle)" in texte
    assert "modèle calibré du RCR" in texte
    assert "arrêts non modélisés" in texte


def test_le_temps_du_modele_depend_de_la_puissance(tmp_path: Path, monkeypatch, capsys):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    temps = []
    for puissance in (150.0, 250.0):
        executer(
            args(velo="RCR", puissance=puissance, json=True),
            config,
            moteur_brouter(),
            moteur_meteo(),
        )
        charge = json.loads(capsys.readouterr().out)
        assert charge["modele_physique"]["puissance_w"] == puissance
        assert all(c["temps_source"] == "modele" for c in charge["candidates"])
        temps.append(charge["candidates"][0]["temps_estime_s"])
    assert temps[0] > temps[1]


def test_sans_calibration_le_json_dit_d_ou_vient_le_temps(
    tmp_path: Path, monkeypatch, capsys
):
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_physique"] is None
    assert all(c["temps_source"] == "vitesse_moyenne" for c in charge["candidates"])


# --- heure de passage météo à la vitesse du modèle (point 5 de la relecture) --


def test_sans_calibration_les_heures_de_passage_restent_a_la_vitesse_de_config(
    tmp_path: Path, monkeypatch, capsys
):
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert all(
        c["vitesse_meteo_kmh"] == pytest.approx(config.boucle.vitesse_moyenne_kmh)
        for c in charge["candidates"]
    )


def test_avec_calibration_les_heures_de_passage_suivent_le_modele(
    tmp_path: Path, monkeypatch, capsys
):
    """La vitesse qui date la prévision vient du modèle, pas des 27 km/h de la config.

    Deux puissances très différentes doivent donner deux vitesses de passage
    différentes : c'est la preuve que la vitesse vient bien de la simulation.
    """
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    vitesses = []
    for puissance in (120.0, 300.0):
        executer(
            args(velo="RCR", puissance=puissance, json=True),
            config,
            moteur_brouter(),
            moteur_meteo(),
        )
        charge = json.loads(capsys.readouterr().out)
        relevees = [c["vitesse_meteo_kmh"] for c in charge["candidates"]]
        assert all(v is not None and v > 0 for v in relevees)
        vitesses.append(relevees[0])
    assert vitesses[0] < vitesses[1]
    assert vitesses[0] != pytest.approx(config.boucle.vitesse_moyenne_kmh)


def test_l_entete_dit_que_la_vitesse_de_passage_vient_du_modele(
    tmp_path: Path, monkeypatch, capsys
):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    executer(args(velo="RCR", puissance=300.0), config, moteur_brouter(), moteur_meteo())
    entete = capsys.readouterr().out.splitlines()[1]
    assert "heures de passage météo" in entete
    assert "(modèle)" in entete
    assert "27 km/h" not in entete


# --- temps écoulé porte à porte, et le bloc « compteur » (18/09/2026) --------
#
# Le défaut corrigé : la carte affichait le temps *en mouvement* du modèle
# comme si c'était la durée de la sortie. Ici, `compteur` et `temps_ecoule_s`
# de chaque candidate, câblés dans `rendre_json`/`rendre_texte` via
# `_info_compteur` (délégué à `ecran_ftp.info_compteur`) et
# `physique.modele.temps_ecoule` (dont la formule est testée à part dans
# `tests/test_physique_modele.py`).


def config_avec_facteur_mesure(dossier: Path, facteur: float = 0.85) -> Config:
    """Un vélo dont le facteur compteur est **mesuré**, pas dérivé — pour que
    `moyenne_compteur_kmh` soit un nombre connu d'avance, calculable à la
    main dans les tests ci-dessous."""
    return config_de_test(
        cache={"dossier": str(dossier)},
        velos=[
            {
                "nom": "RCR",
                "usage": "route",
                "masse_kg": 9.0,
                "cda_m2": 0.30,
                "crr": 0.005,
                "facteur_compteur": facteur,
            }
        ],
    )


def _trace_de_test(distance_m: float = 100_000.0) -> Trace:
    points = [
        PointTrace(lat=0.0, lon=0.0, alt_m=0.0, dist_m=0.0),
        PointTrace(lat=0.5, lon=0.0, alt_m=0.0, dist_m=distance_m),
    ]
    return Trace(
        nom="boucle-test",
        points=points,
        segments=[],
        distance_m=distance_m,
        denivele_m=None,
        temps_moteur_s=None,
    )


def _couts_de_test() -> Couts:
    return Couts(
        km_trafic=0.0,
        km_calme=0.0,
        km_non_classe=0.0,
        km_non_revetu=0.0,
        antennes_m=0.0,
        virages_gauche=0,
        virages_gauche_trafic=0,
        virages_droite=0,
        sens="horaire",
        score=0.0,
    )


def _evaluation_de_test(temps_s: float | None, distance_m: float = 100_000.0) -> Evaluation:
    return Evaluation(
        numero=1,
        trace=_trace_de_test(distance_m),
        couts=_couts_de_test(),
        meteo=None,
        ecart_relatif=None,
        azimut_deg=None,
        rayon_m=None,
        total=0.0,
        temps_s=temps_s,
    )


def _demande_de_test(distance_km: float = 100.0) -> Demande:
    return Demande(
        gpx=None,
        distance_km=distance_km,
        direction="NE",
        azimut_deg=45.0,
        nb_candidates=1,
        profil="fastbike",
        depart=datetime(2026, 9, 18, 9, 0),
        sortie=None,
    )


def test_info_compteur_boucle_rend_none_sans_le_moindre_velo(tmp_path: Path):
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    assert _info_compteur(config, None) is None


def test_compteur_et_temps_ecoule_sont_nuls_sans_velo(tmp_path: Path):
    """Le test explicite du DoD : `compteur` et `temps_ecoule_s` de chaque
    candidate valent `null` sur une configuration sans vélo."""
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    assert charge["compteur"] is None
    candidate = charge["candidates"][0]
    assert candidate["temps_ecoule_s"] is None
    assert candidate["temps_ecoule_source"] is None
    # `temps_estime_s`/`temps_source`, eux, restent renseignés : la panne du
    # compteur n'efface pas le temps de mouvement.
    assert candidate["temps_estime_s"] == 5_000
    assert candidate["temps_source"] == "modele"


def test_compteur_json_porte_les_quatre_champs_du_contrat(tmp_path: Path):
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    compteur = charge["compteur"]
    assert compteur["velo"] == "RCR"
    assert compteur["facteur_compteur"] == pytest.approx(0.85)
    assert compteur["facteur_provenance"] == "mesure"
    assert compteur["part_arret_plancher"] == PART_ARRET_REFERENCE
    assert compteur["moyenne_compteur_kmh"] > 0


def test_temps_ecoule_json_suit_la_formule_partagee(tmp_path: Path):
    """Pas une deuxième formule : ce que `rendre_json` publie doit être
    exactement `physique.modele.temps_ecoule` appliqué à la distance de la
    candidate, son `temps_estime_s`, et la moyenne compteur du bloc `compteur`."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    candidate = charge["candidates"][0]
    attendu_s, attendue_source = temps_ecoule(
        50.0, 5_000.0, compteur_info["moyenne_compteur_kmh"]
    )
    assert candidate["temps_ecoule_s"] == round(attendu_s)
    assert candidate["temps_ecoule_source"] == attendue_source
    # Jamais sous le temps de mouvement (le point du plancher) :
    assert candidate["temps_ecoule_s"] >= candidate["temps_estime_s"]


def test_texte_boucle_affiche_mouvement_et_ecoule(tmp_path: Path):
    """CLI et front disent la même chose : une seule cellule, « m:ss / m:ss »,
    et une légende sous le tableau plutôt qu'une colonne de plus."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    texte = rendre_texte(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    ecoule_s, _ = temps_ecoule(50.0, 5_000.0, compteur_info["moyenne_compteur_kmh"])
    minutes_mouvement = round(5_000.0 / 60)
    minutes_ecoule = round(ecoule_s / 60)
    attendu = (
        f"{minutes_mouvement // 60}:{minutes_mouvement % 60:02d}"
        f" / {minutes_ecoule // 60}:{minutes_ecoule % 60:02d}"
    )
    assert attendu in texte
    assert "mouvement / écoulé porte à porte" in texte
    assert "RCR" in texte


def test_texte_boucle_sans_compteur_n_affiche_pas_la_legende(tmp_path: Path):
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    texte = rendre_texte(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=None
    )
    assert "écoulé porte à porte" not in texte
    assert " / " not in texte.splitlines()[3]  # la ligne de la candidate n° 1

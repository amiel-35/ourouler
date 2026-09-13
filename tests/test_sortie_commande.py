"""Tests de `ourouler sortie` et de sa carte (lot L4.4).

Aucun réseau : les trois clients — BRouter, Open-Meteo, Intervals — passent
par un `httpx.MockTransport`. Aucune donnée personnelle : la configuration
part du point fictif (0.0, 0.0), les boucles sont des anneaux fabriqués
autour de ce point, et la séance vient des `workout_doc` inventés de
`tests/fixtures/workouts.py`.

Les anneaux sont paramétrés par azimut : c'est ainsi qu'on fabrique des
candidates dont on connaît d'avance le classement — une boucle plate se note
mieux qu'une boucle qui descend, et c'est la note de placement qui doit
trier, la pluie ne départageant qu'à égalité.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_seance_intervals import ATHLETE, CLE, W

from ourouler.boucle.couts import Couts
from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.boucle.trace import PointTrace, Trace
from ourouler.boucle.trace import distance_m as distance_points
from ourouler.cli import construire_parseur, main
from ourouler.config import Config, depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.physique.commande import VERSION_CALIBRATION
from ourouler.physique.modele import Parametres
from ourouler.seance.modele import Etape, Seance
from ourouler.seance.placement import Emplacement, Placement
from ourouler.seance.terrain import NoteBloc
from ourouler.sortie import carte
from ourouler.sortie.carte import COULEURS_BLOCS
from ourouler.sortie.commande import (
    ARRONDI_DISTANCE_KM,
    Proposition,
    _Contexte,
    _ecrire_gpx,
    executer,
    lire_options,
    rendre_texte,
)

JOUR = date(2026, 9, 8)
FTP = W.FTP_TEST  # 200 W, inventée

#: Paramètres physiques inventés, proches d'un vélo de route.
PARAMETRES = Parametres(masse_totale_kg=85.0, cda_m2=0.32, crr=0.005)

#: Rayon d'un anneau, en degrés : environ 34 km de tour à l'équateur, de quoi
#: porter la séance fabriquée (≈ 34 km) de bout en bout.
RAYON_DEG = 0.0485

#: Nombre de points d'un anneau : un point tous les ~85 m, comme un vrai tracé.
POINTS_ANNEAU = 400

DEGRE_EN_M = 111_200.0


CONFIG_BRUTE: dict[str, Any] = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 76.5, "ftp_w": FTP},
    "velos": [{"nom": "Route", "usage": "route"}],
    "meteo": {
        "directions": 8,
        "distances_km": [15],
        "modele": "modele_principal_test",
        "second_avis": "",
        "horizon_h": 6,
    },
    "brouter": {
        "url": "https://brouter.exemple.test",
        "profil": "fastbike",
        "timeout_s": 5.0,
    },
    "boucle": {"vitesse_moyenne_kmh": 27.0, "sens": "horaire", "candidates": 2},
    "intervals": {"athlete_id": ATHLETE, "api_key": CLE},
}


def config_de_test(dossier: Path, **sections: Any) -> Config:
    brute = {**CONFIG_BRUTE, "cache": {"dossier": str(dossier)}, **sections}
    return depuis_dict(brute)


def args(**champs) -> argparse.Namespace:
    defauts = {
        "jour": JOUR.isoformat(),
        "distance": None,
        "direction": None,
        "candidates": 2,
        "velo": None,
        "depart": "09:00",
        "sortie": None,
        "carte": None,
        "profil": None,
        "ecraser": False,
        "json": False,
    }
    return argparse.Namespace(**{**defauts, **champs})


def ecrire_calibration(dossier: Path, velo: str = "Route") -> None:
    """Une calibration inventée, pour que le placement parte d'un modèle connu."""
    chemin = dossier / "calibration.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "version": VERSION_CALIBRATION,
                "velos": {
                    velo: {
                        "masse_totale_kg": PARAMETRES.masse_totale_kg,
                        "cda_m2": PARAMETRES.cda_m2,
                        "crr": PARAMETRES.crr,
                        "date": "2026-09-01",
                        "n_sorties": 12,
                        "mae": 0.03,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


# --- BRouter bouchonné : des anneaux fabriqués --------------------------------


def anneau(
    azimut_deg: float, *, rayon_deg: float = RAYON_DEG, amplitude_m: float = 1.0, n: int = POINTS_ANNEAU
) -> list[tuple[float, float, float]]:
    """Un anneau fermé qui **part du point (0, 0)** et s'éloigne vers `azimut_deg`.

    L'altitude suit deux sinusoïdes par tour : `amplitude_m` faible donne un
    anneau plat, `amplitude_m` fort des descentes qui pénalisent les blocs.
    """
    a = math.radians(azimut_deg)
    centre = (rayon_deg * math.cos(a), rayon_deg * math.sin(a))
    phi0 = math.atan2(-math.sin(a), -math.cos(a))
    points = []
    for i in range(n):
        phi = phi0 + 2 * math.pi * i / n
        lat = round(centre[0] + rayon_deg * math.cos(phi), 6)
        lon = round(centre[1] + rayon_deg * math.sin(phi), 6)
        alt = round(40.0 + amplitude_m * math.sin(2 * (phi - phi0)), 2)
        points.append((lat, lon, alt))
    points.append(points[0])
    return points


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6_371_000.0 * math.asin(math.sqrt(h))


ENTETE_MESSAGES = [
    "Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost",
    "TurnCost", "NodeCost", "InitialCost", "WayTags", "NodeTags", "Time", "Energy",
]  # fmt: skip


def reponse_anneau(points: list[tuple[float, float, float]], *, troncons: int = 20) -> dict:
    """Le GeoJSON d'un anneau, au format du serveur réel, tronçons couvrant tout le tracé.

    Les tags sont ceux d'une petite route de campagne — ni trafic, ni village :
    ce qui distingue les candidates dans ces tests, c'est le relief, pas la
    classe de route.
    """
    pas = max(1, (len(points) - 1) // troncons)
    fins = list(range(pas, len(points), pas))
    if fins[-1] != len(points) - 1:
        fins.append(len(points) - 1)
    messages = [list(ENTETE_MESSAGES)]
    debut = 0
    total = 0.0
    for fin in fins:
        longueur = sum(
            distance_m(points[i][:2], points[i + 1][:2]) for i in range(debut, fin)
        )
        total += longueur
        lat, lon, alt = points[fin]
        messages.append(
            [
                str(round(lon * 1e6)), str(round(lat * 1e6)), str(round(alt)),
                str(round(longueur)), "1200", "0", "0", "0", "0",
                "highway=tertiary surface=asphalt", "", "60", "9000",
            ]  # fmt: skip
        )
        debut = fin
    denivele = sum(max(0.0, b[2] - a[2]) for a, b in zip(points[:-1], points[1:], strict=True))
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "creator": "BRouter-test",
                    "name": "anneau_fabrique",
                    "track-length": str(round(total)),
                    "filtered ascend": str(round(denivele)),
                    "total-time": str(round(total / 7.5)),
                    "cost": str(round(total * 2)),
                    "messages": messages,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat, alt] for lat, lon, alt in points],
                },
            }
        ],
    }


def moteur_brouter(reglages: dict[float, dict] | None = None) -> ClientBrouter:
    """BRouter bouchonné : un anneau par azimut, réglable en relief et en rayon."""
    reglages = reglages or {}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        azimut = float(requete.url.params["roundTripStartDirection"])
        reglage = reglages.get(azimut, {})
        return httpx.Response(
            200,
            json=reponse_anneau(
                anneau(
                    azimut,
                    rayon_deg=reglage.get("rayon_deg", RAYON_DEG),
                    amplitude_m=reglage.get("amplitude_m", 1.0),
                )
            ),
        )

    params = depuis_dict(CONFIG_BRUTE).brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


# --- Open-Meteo bouchonné -----------------------------------------------------


def bloc_meteo(lat: float, lon: float, n: int, pluie: float) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-08T{6 + i:02d}:00" for i in range(n)],
            "precipitation": [pluie] * n,
            "rain": [pluie] * n,
            "wind_speed_10m": [14.0] * n,
            "wind_direction_10m": [45.0] * n,
            "wind_gusts_10m": [25.0] * n,
            "apparent_temperature": [11.5] * n,
            "temperature_2m": [14.0] * n,
        },
    }


def moteur_meteo(pluie=None, en_panne: bool = False) -> ClientOpenMeteo:
    """Open-Meteo bouchonné. `pluie` : une fonction (lat, lon) → mm/h."""
    pluie = pluie if pluie is not None else (lambda lat, lon: 0.0)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if en_panne:
            return httpx.Response(503, json={"error": True, "reason": "maintenance"})
        p = requete.url.params
        lats = [float(x) for x in p["latitude"].split(",")]
        lons = [float(x) for x in p["longitude"].split(",")]
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        return httpx.Response(
            200,
            json=[
                bloc_meteo(a, o, n, pluie(a, o)) for a, o in zip(lats, lons, strict=True)
            ],
        )

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def pluie_au_nord(lat: float, lon: float) -> float:
    return 2.0 if lat > 0 else 0.0


# --- Intervals bouchonné ------------------------------------------------------


def client_intervals(evenements: list[dict] | None = None) -> ClientIntervals:
    charge = (
        evenements
        if evenements is not None
        else [W.evenement(W.groupes_watts(), nom="4x8 fabriquée")]
    )

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=charge)

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


def clients_interdits():
    """Trois clients qui font échouer le test dès qu'on les appelle."""

    def refus(requete: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"appel réseau inattendu : {requete.url}")

    return (
        ClientBrouter(
            depuis_dict(CONFIG_BRUTE).brouter,
            http=httpx.Client(transport=httpx.MockTransport(refus)),
        ),
        ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(refus))),
        ClientIntervals(ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(refus))),
    )


def lancer(tmp_path: Path, monkeypatch, *, meteo=None, brouter=None, intervals=None, **champs):
    """Exécute la commande dans `tmp_path`, clients bouchonnés, et rend le code."""
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    return executer(
        args(**champs),
        config_de_test(tmp_path / "cache"),
        brouter if brouter is not None else moteur_brouter(),
        meteo if meteo is not None else moteur_meteo(),
        intervals if intervals is not None else client_intervals(),
    )


def lignes_du_tableau(sortie: str) -> list[str]:
    """Les lignes de candidates du tableau texte, repérées par la ligne de titres."""
    lignes = sortie.splitlines()
    debut = next(i for i, ligne in enumerate(lignes) if "n°" in ligne and "note placement" in ligne)
    gardees = []
    for ligne in lignes[debut + 1 :]:
        jetons = ligne.replace("→", " ").split()
        if not jetons or not jetons[0].isdigit():
            break
        gardees.append(ligne)
    return gardees


# --- erreurs utilisateur, avant tout appel réseau -----------------------------


@pytest.mark.parametrize(
    ("champs", "motif"),
    [
        ({"distance": -5.0}, "--distance"),
        ({"distance": 0.0}, "--distance"),
        ({"direction": "nord-est"}, "direction"),
        ({"candidates": 0}, "--candidates"),
        ({"jour": "2026-02-31"}, "--jour"),
        ({"velo": "Tandem"}, "Tandem"),
    ],
)
def test_une_option_fautive_est_refusee_avant_tout_appel(
    tmp_path: Path, monkeypatch, champs: dict, motif: str
):
    monkeypatch.chdir(tmp_path)
    brouter, meteo, intervals = clients_interdits()
    with pytest.raises(ErreurUtilisateur, match=re.escape(motif)):
        executer(args(**champs), config_de_test(tmp_path / "cache"), brouter, meteo, intervals)


def test_brouter_non_renseigne_est_refuse_avant_tout_appel(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = depuis_dict(
        {k: v for k, v in CONFIG_BRUTE.items() if k != "brouter"}
        | {"cache": {"dossier": str(tmp_path / "cache")}}
    )
    with pytest.raises(ErreurUtilisateur, match="brouter"):
        lire_options(args(), config)


def test_un_dossier_de_sortie_inexistant_est_refuse(tmp_path: Path):
    with pytest.raises(ErreurUtilisateur, match="n'existe pas"):
        lire_options(
            args(sortie=str(tmp_path / "absent" / "s.gpx")), config_de_test(tmp_path / "cache")
        )


def test_un_fichier_existant_n_est_pas_ecrase_sans_ecraser(tmp_path: Path):
    cible = tmp_path / "deja.gpx"
    cible.write_text("<gpx/>", encoding="utf-8")
    with pytest.raises(ErreurUtilisateur, match="existe déjà"):
        lire_options(args(sortie=str(cible)), config_de_test(tmp_path / "cache"))
    # Avec --ecraser, la même demande passe.
    assert lire_options(
        args(sortie=str(cible), ecraser=True), config_de_test(tmp_path / "cache")
    ).sortie == cible


def test_les_erreurs_sortent_en_code_2_par_la_cli(tmp_path: Path, capsys):
    fichier = tmp_path / "c.toml"
    fichier.write_text(
        "[depart]\nnom = 'Point zéro'\nlatitude = 0.0\nlongitude = 0.0\n"
        "[cycliste]\nmasse_kg = 80\nftp_w = 250\n",
        encoding="utf-8",
    )
    code = main(["--config", str(fichier), "sortie", "--jour", "2026-09-08"])
    assert code == 2
    assert "brouter" in capsys.readouterr().err


def test_la_sous_commande_est_declaree_dans_la_cli():
    parseur = construire_parseur()
    lus = parseur.parse_args(["sortie", "--jour", "2026-09-08", "--carte", "c.html", "--json"])
    assert lus.commande == "sortie"
    assert lus.carte == "c.html"
    assert lus.json is True


# --- aucune séance ------------------------------------------------------------


def test_sans_seance_ce_jour_la_message_clair_et_code_0(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, intervals=client_intervals([]))
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Aucune séance" in sortie
    assert not list(tmp_path.glob("*.gpx"))
    assert not list(tmp_path.glob("*.html"))


def test_sans_seance_le_json_le_dit(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, intervals=client_intervals([]), json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["seance"] is None
    assert charge["candidates"] == []


# --- le tableau ---------------------------------------------------------------


def test_le_tableau_montre_les_candidates_retenues(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, candidates=3)
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 3, sortie


def test_le_tri_prend_la_note_de_placement_avant_la_pluie(tmp_path: Path, monkeypatch, capsys):
    """La boucle plate est **au nord**, donc sous la pluie ; elle gagne quand même.

    C'est tout l'ordre du contrat §4 : la pluie se contourne en partant plus
    tard, un bloc de seuil en descente ne se contourne pas.
    """
    reglages = {0.0: {"amplitude_m": 1.0}, 180.0: {"amplitude_m": 90.0}}
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(reglages),
        meteo=moteur_meteo(pluie_au_nord),
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    premiere, seconde = charge["candidates"]
    assert premiere["azimut_deg"] == 0.0, charge
    assert premiere["placement"]["note_totale"] < seconde["placement"]["note_totale"]
    assert premiere["meteo"]["pluie_cumulee_mm"] > seconde["meteo"]["pluie_cumulee_mm"]


def test_a_note_egale_la_pluie_departage(tmp_path: Path, monkeypatch, capsys):
    """Deux anneaux de même relief, l'un au nord sous la pluie, l'autre au sud au sec."""
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(),
        meteo=moteur_meteo(pluie_au_nord),
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    premiere, seconde = charge["candidates"]
    assert premiere["placement"]["note_totale"] == pytest.approx(
        seconde["placement"]["note_totale"], abs=1e-9
    )
    assert premiere["azimut_deg"] == 180.0
    assert premiere["meteo"]["pluie_cumulee_mm"] < seconde["meteo"]["pluie_cumulee_mm"]


def test_une_candidate_de_note_catastrophique_reste_affichee_en_derniere_position(tmp_path: Path):
    """Règle produit (e) : « on note, on ne filtre pas ».

    Rien ne protégeait explicitement cette règle. Le seul garde-fou était le
    dépaquetage `premiere, seconde = charge["candidates"]` d'un test de tri :
    un filtre qui laisserait toujours passer deux candidates l'aurait franchi
    sans bruit. Le test d'écartement voisin, lui, écarte une boucle **trop
    courte** — une impossibilité physique, pas une mauvaise note.

    Ici la troisième candidate est roulable de bout en bout ; elle est
    simplement épouvantable. Elle doit rester dans le JSON, rester dans le
    tableau, et finir dernière.
    """
    # Fabriqué à la main plutôt que par la commande : la note est alors une
    # donnée du test, pas le sous-produit d'un relief qu'il faudrait régler.
    bonnes = [_proposition_avec_demi_tour(), _proposition_avec_demi_tour()]
    catastrophique = _proposition_avec_demi_tour()
    for numero, proposition in enumerate(bonnes, start=1):
        proposition.numero = numero
        proposition.placement.note_totale = float(numero) * 0.1
    catastrophique.numero = 3
    catastrophique.placement.note_totale = 250.0
    propositions = [*bonnes, catastrophique]
    assert propositions == sorted(propositions, key=lambda p: p.tri), (
        "la fixture doit être déjà triée, sinon le test ne mesure que le tri"
    )

    texte = rendre_texte(propositions, _contexte_minimal(tmp_path, _seance_fabriquee()))

    lignes = lignes_du_tableau(texte)
    assert len(lignes) == 3, texte
    assert lignes[-1].split()[0] == "3", lignes[-1]
    assert "250,00" in lignes[-1], (
        f"la candidate épouvantable est affichée sans sa note : {lignes[-1]}"
    )


@pytest.mark.parametrize("en_json", [False, True], ids=["texte", "json"])
def test_une_candidate_epouvantable_n_est_jamais_filtree(
    tmp_path: Path, monkeypatch, capsys, en_json
):
    """Suite du précédent : le rendu, texte comme JSON, la montre toujours."""
    reglages = {0.0: {"amplitude_m": 1.0}, 120.0: {"amplitude_m": 1.0}, 240.0: {"amplitude_m": 120.0}}
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(reglages),
        candidates=3,
        json=en_json,
    )
    sortie = capsys.readouterr().out
    assert code == 0
    if en_json:
        charge = json.loads(sortie)
        assert "écartée" not in sortie
        assert len(charge["candidates"]) == 3, (
            "une candidate roulable a disparu du JSON : on note, on ne filtre pas"
        )
        notes = [c["placement"]["note_totale"] for c in charge["candidates"]]
        assert notes == sorted(notes), notes
        pire = charge["candidates"][-1]
        assert pire["azimut_deg"] == 240.0, charge["candidates"]
        assert pire["placement"]["note_totale"] > 5 * notes[0], notes
        assert pire["retenue"] is False
    else:
        lignes = lignes_du_tableau(sortie)
        assert len(lignes) == 3, sortie
        assert "candidate(s) écartée(s)" not in sortie


def test_les_candidates_ou_la_seance_ne_tient_pas_sont_ecartees(
    tmp_path: Path, monkeypatch, capsys
):
    """Un anneau trop court porte la séance nulle part : il est écarté, et on dit pourquoi."""
    reglages = {180.0: {"rayon_deg": RAYON_DEG / 6}}
    code = lancer(
        tmp_path, monkeypatch, brouter=moteur_brouter(reglages), candidates=2
    )
    sortie = capsys.readouterr().out
    assert code == 0
    assert "1 candidate(s) écartée(s)" in sortie
    assert "ne tient pas sur ce tracé" in sortie
    assert len(lignes_du_tableau(sortie)) == 1


def test_toutes_les_candidates_refusees_donne_un_message_clair(tmp_path: Path, monkeypatch):
    """Aucune proposition possible : code 2, comme `boucle` sans boucle bornée."""
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="ne tient sur aucune"):
        executer(
            args(distance=5.0),
            config_de_test(tmp_path / "cache"),
            moteur_brouter({a: {"rayon_deg": RAYON_DEG / 8} for a in (0.0, 180.0)}),
            moteur_meteo(),
            client_intervals(),
        )


def test_la_distance_par_defaut_vient_de_la_seance_arrondie(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    distance = charge["demande"]["distance_km"]
    assert distance % ARRONDI_DISTANCE_KM == 0
    assert "arrondis au multiple de 5" in charge["demande"]["distance_source"]
    # La séance fabriquée fait un peu plus de 30 km : l'arrondi doit rester proche.
    assert 30.0 <= distance <= 45.0


def test_une_distance_demandee_l_emporte(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, distance=34.0, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["demande"]["distance_km"] == 34.0
    assert charge["demande"]["distance_source"] == "demandée"


# --- la séance placée, la tenue ------------------------------------------------


def test_la_seance_placee_est_detaillee_sous_le_tableau(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Séance placée sur la candidate n° 1" in sortie
    # Quatre blocs dans `groupes_watts()`, chacun avec son kilomètre de départ.
    blocs = [ligne for ligne in sortie.splitlines() if ligne.strip().startswith("bloc ")]
    assert len(blocs) == 4, sortie
    assert all(re.search(r"km \d+,\d+ → \d+,\d+", ligne) for ligne in blocs), blocs
    assert all("note" in ligne for ligne in blocs)


def test_la_tenue_est_conseillee_quand_la_meteo_repond(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Tenue conseillée" in sortie
    assert "au départ :" in sortie


def test_sans_meteo_le_tableau_reste_et_la_tenue_disparait(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, meteo=moteur_meteo(en_panne=True))
    lu = capsys.readouterr()
    assert code == 0
    assert "météo indisponible" in lu.err
    assert "aucun conseil de tenue" in lu.out
    assert "pluie" not in lignes_du_tableau(lu.out)[0]
    assert len(lignes_du_tableau(lu.out)) == 2


# --- les fichiers écrits -------------------------------------------------------


def test_le_gpx_et_la_carte_sont_ecrits_dans_le_dossier_courant(
    tmp_path: Path, monkeypatch, capsys
):
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    gpx = tmp_path / f"sortie_{JOUR:%Y%m%d}.gpx"
    carte = tmp_path / f"sortie_{JOUR:%Y%m%d}.html"
    assert gpx.is_file() and carte.is_file()
    assert gpx.name in sortie and carte.name in sortie
    assert gpx.read_text(encoding="utf-8").startswith("<?xml")


def test_le_gpx_ecrit_est_le_parcours_place(tmp_path: Path, monkeypatch, capsys):
    """Défaut mesuré le 22/04 : le fichier envoyé au compteur ignorait le placement.

    Ici la séance tient sur l'anneau sans demi-tour, donc parcours et boucle se
    confondent — ce que le fichier doit dire, c'est la distance **placée** et
    combien de demi-tours il contient.
    """
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    place = charge["candidates"][0]["placement"]
    texte = (tmp_path / f"sortie_{JOUR:%Y%m%d}.gpx").read_text(encoding="utf-8")
    relu = lire_gpx_trace(texte.encode("utf-8"))
    assert relu.distance_m == pytest.approx(place["distance_totale_m"], rel=0.01)
    assert "sans demi-tour" in texte, texte[:400]


def _trace_anneau() -> Trace:
    """L'anneau des tests, monté en `Trace` avec ses distances cumulées."""
    points: list[PointTrace] = []
    for lat, lon, alt in anneau(0.0):
        point = PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=0.0)
        cumul = 0.0 if not points else points[-1].dist_m + distance_points(points[-1], point)
        points.append(PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=cumul))
    return Trace(
        nom="anneau",
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


def _proposition_avec_demi_tour(denivele_moteur_m: float = 460.0):
    """Une candidate dont le parcours placé vaut le double de la boucle.

    C'est le cas réel du 22/04 réduit à ce qu'il faut pour l'afficher : une
    boucle, un placement qui fait demi-tour, et un D+ moteur qui ne peut pas
    être celui du parcours.
    """
    trace = _trace_anneau()
    trace.denivele_m = denivele_moteur_m
    place = Placement(
        decalage_z2_s=0.0,
        emplacements=[
            Emplacement(
                etape_idx=1, debut_m=6000.0, longueur_m=3000.0, demi_tour=True, note=NoteBloc(0.0)
            )
        ],
        note_totale=1.0,
        duree_totale_s=9840.0,  # 2 h 44, comme le cas relevé
        distance_totale_m=2 * trace.distance_m,
        jalons_m=[0.0, trace.distance_m, 0.0],
    )
    return Proposition(
        numero=1,
        trace=trace,
        placement=place,
        couts=Couts(
            km_trafic=0.0,
            km_calme=trace.distance_m / 1000,
            km_non_classe=0.0,
            km_non_revetu=0.0,
            antennes_m=0.0,
            virages_gauche=0,
            virages_gauche_trafic=0,
            virages_droite=0,
            sens="horaire",
            score=0.0,
        ),
        meteo=None,
        azimut_deg=0.0,
        ecart_relatif=0.0,
        part_connue=None,
        vitesse_kmh=25.0,
    )


def _seance_fabriquee() -> Seance:
    """Une Z2 d'ouverture et un bloc : de quoi que `_seance_placee` ait un indice 1."""
    etapes = [
        Etape("echauffement", 1200.0, 140.0, 160.0, "Z2", elastique=True),
        Etape("bloc", 1200.0, 200.0, 220.0, "bloc"),
    ]
    return Seance(
        nom="4x8 fabriquée", jour=JOUR, etapes=etapes, duree_s=2400.0, meta={}
    )


def _contexte_minimal(tmp_path: Path, seance: Seance) -> Any:
    config = config_de_test(tmp_path / "cache")
    return _Contexte(
        seance=seance,
        demande=lire_options(args(), config),
        config=config,
        distance_km=34.0,
        distance_source="déduite de la séance",
        provenance_modele="calibration du vélo Route",
        ecartees=[],
        tenue=None,
        gpx=None,
        carte=None,
    )


def test_sortie_dit_qu_une_autre_seance_du_jour_a_ete_ignoree(tmp_path: Path):
    """S1 : `ourouler seance` le disait, `ourouler sortie` non.

    C'est pourtant `sortie` qui construit une boucle entière pour la séance
    choisie en silence — la plus longue. La clé restait dans `meta`, donc
    visible en `--json` seul.
    """
    seance = _seance_fabriquee()
    seance.meta["seances_ignorees"] = ["Vélo B", "Vélo C"]
    texte = rendre_texte(
        [_proposition_avec_demi_tour()], _contexte_minimal(tmp_path, seance)
    )
    assert "ignorée(s) au profit de la plus longue" in texte
    assert "Vélo B, Vélo C" in texte


def test_l_heure_de_depart_accepte_aussi_heure():
    """C5 : `--depart` (heure) et le `--depuis` (lieu) prévu diffèrent d'une lettre.

    `--heure` est accepté partout comme synonyme, sans rien retirer : le nom
    sans ambiguïté existe avant que `--depuis` soit écrit (Q15).
    """
    parseur = construire_parseur()
    for commande in ("meteo", "boucle", "simuler", "sortie"):
        arguments = {
            "meteo": [],
            "boucle": ["--distance", "40", "--direction", "N"],
            "simuler": ["--gpx", "x.gpx", "--puissance", "200"],
            "sortie": [],
        }[commande]
        lus = parseur.parse_args([commande, *arguments, "--heure", "09:30"])
        assert lus.depart == "09:30", f"{commande} : --heure n'alimente pas `depart`"
        lus = parseur.parse_args([commande, *arguments, "--depart", "10:15"])
        assert lus.depart == "10:15", f"{commande} : --depart a été perdu"


def test_le_tableau_distingue_la_boucle_du_parcours_reellement_roule(tmp_path: Path):
    """C1 : la même ligne affichait 38,5 km et 2 h 44, soit 14 km/h.

    La distance venait de la boucle, la durée du placement. Les deux sont
    justes et ne parlent pas du même parcours : le tableau porte maintenant
    les deux distances, et « temps » va avec « parcours ».
    """
    proposition = _proposition_avec_demi_tour()
    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    entete = next(ligne for ligne in texte.splitlines() if "note placement" in ligne)
    assert "boucle" in entete and "parcours" in entete, entete
    assert "distance" not in entete, "« distance » ne dit pas de quel parcours il s'agit"

    boucle_km = proposition.trace.distance_m / 1000
    ligne = next(ligne for ligne in texte.splitlines() if ligne.startswith("→"))
    assert f"{boucle_km:.1f}".replace(".", ",") in ligne
    assert f"{2 * boucle_km:.1f}".replace(".", ",") in ligne, (
        f"le parcours réellement roulé n'est pas dans la ligne : {ligne}"
    )
    assert "Boucle" in texte and "parcours réellement roulé" in texte


def test_les_deux_denivelés_sont_montrés_cote_a_cote(tmp_path: Path):
    """C2 : 460 m annoncés par le moteur, 308 m recalculés — et rien ne le disait.

    Règle absolue 5 : deux mesures qui divergent s'affichent comme un
    désaccord. La provenance était bien écrite dans chaque artefact, mais il
    fallait ouvrir le GPX pour voir l'écart.
    """
    proposition = _proposition_avec_demi_tour(denivele_moteur_m=460.0)
    recalcule = proposition.denivele_parcours_m
    assert recalcule is not None
    assert abs(recalcule - 460.0) > 10.0, (
        "la fixture doit faire diverger les deux mesures, sinon le test ne prouve rien"
    )
    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    ligne = next((ligne for ligne in texte.splitlines() if ligne.startswith("D+ :")), None)
    assert ligne is not None, f"aucune ligne ne compare les deux D+ :\n{texte}"
    assert "460 m" in ligne and f"{recalcule:.0f} m" in ligne, ligne
    assert "moteur" in ligne and "parcours placé" in ligne


def test_le_gpx_d_un_parcours_avec_demi_tour_contient_l_aller_retour(
    tmp_path: Path, monkeypatch
):
    """Un placement qui fait demi-tour au km 12 et rentre au km 6 : 18 km de fichier.

    Le placement est fabriqué ici, parce que l'anneau des autres tests porte la
    séance de bout en bout sans jamais avoir à se retourner. Ce qui est vérifié
    est ce que le mainteneur a mesuré le 22/04 : le fichier doit contenir
    l'aller-retour, et son `<desc>` le dire.
    """
    monkeypatch.chdir(tmp_path)
    trace = _trace_anneau()
    place = Placement(
        decalage_z2_s=0.0,
        emplacements=[
            Emplacement(etape_idx=1, debut_m=6000.0, longueur_m=3000.0, demi_tour=True, note=NoteBloc(0.0))
        ],
        note_totale=1.0,
        duree_totale_s=3600.0,
        distance_totale_m=18_000.0,
        jalons_m=[0.0, 12_000.0, 6_000.0],
    )
    seance = Seance(nom="séance fabriquée", jour=JOUR, etapes=[], duree_s=0.0, meta={})
    demande = lire_options(args(), config_de_test(tmp_path / "cache"))

    chemin = _ecrire_gpx(trace, place, seance, demande)

    texte = chemin.read_text(encoding="utf-8")
    relu = lire_gpx_trace(texte.encode("utf-8"))
    assert relu.distance_m == pytest.approx(18_000.0, rel=0.01), (
        f"{relu.distance_m:.0f} m écrits pour 18 000 m roulés : le demi-tour manque au fichier"
    )
    assert "1 demi-tour" in texte and "18,0 km" in texte, texte[:400]
    # Le GPX repasse bien deux fois par le même endroit : le point du km 9 de la
    # boucle est écrit à l'aller et au retour.
    passages = [p for p in relu.points if distance_points(p, _point_a_9_km(trace)) < 50.0]
    assert len(passages) >= 2, f"{len(passages)} passage(s) au km 9 : l'aller-retour n'y est pas"


def _point_a_9_km(trace: Trace) -> PointTrace:
    """Le point de la boucle au km 9, entre le demi-tour et le retour."""
    return min(trace.points, key=lambda p: abs(p.dist_m - 9_000.0))


def test_les_chemins_demandes_sont_respectes(tmp_path: Path, monkeypatch, capsys):
    code = lancer(
        tmp_path,
        monkeypatch,
        sortie=str(tmp_path / "ma_sortie.gpx"),
        carte=str(tmp_path / "ma_carte.html"),
    )
    capsys.readouterr()
    assert code == 0
    assert (tmp_path / "ma_sortie.gpx").is_file()
    assert (tmp_path / "ma_carte.html").is_file()


# --- la carte ------------------------------------------------------------------


class _Compteur(HTMLParser):
    """Un parseur tolérant qui vérifie que la page est du HTML bien formé."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pile: list[str] = []
        self.balises: dict[str, int] = {}
        self.titre = ""
        self._dans_titre = False
        self.desequilibres: list[str] = []

    AUTONOMES = {"meta", "link", "br", "img", "hr", "input"}

    def handle_starttag(self, tag, attrs):
        self.balises[tag] = self.balises.get(tag, 0) + 1
        if tag not in self.AUTONOMES:
            self.pile.append(tag)
        if tag == "title":
            self._dans_titre = True

    def handle_endtag(self, tag):
        if tag in self.AUTONOMES:
            return
        if not self.pile or self.pile[-1] != tag:
            self.desequilibres.append(tag)
            if tag in self.pile:
                while self.pile and self.pile.pop() != tag:
                    pass
            return
        self.pile.pop()
        if tag == "title":
            self._dans_titre = False

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data


def carte_produite(tmp_path: Path, monkeypatch, **champs) -> str:
    lancer(tmp_path, monkeypatch, **champs)
    return (tmp_path / f"sortie_{JOUR:%Y%m%d}.html").read_text(encoding="utf-8")


def test_la_carte_se_parse_en_html_et_porte_le_nom_de_la_seance(
    tmp_path: Path, monkeypatch, capsys
):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    compteur = _Compteur()
    compteur.feed(page)
    assert compteur.desequilibres == []
    assert compteur.pile == []
    assert "4x8 fabriquée" in compteur.titre
    assert compteur.balises.get("svg") == 1
    assert compteur.balises.get("script") == 2  # Leaflet, puis le script de la page


def test_la_carte_porte_les_quatre_blocs_avec_leur_note(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    assert len(donnees["blocs"]) == 4
    for numero, bloc in enumerate(donnees["blocs"], start=1):
        assert bloc["couleur"] == COULEURS_BLOCS[numero - 1]
        assert bloc["etiquette"].startswith(f"{numero} ·")
        assert "Bloc" in bloc["infobulle"]
        assert len(bloc["pts"]) >= 2
    # Les liaisons (échauffement, récups, calme) sont là et ne portent pas de note.
    assert donnees["liaisons"]


def test_la_carte_ne_contient_que_la_geometrie_du_trace(tmp_path: Path, monkeypatch, capsys):
    """Aucune coordonnée ne vient du générateur : tout sort du tracé passé en paramètre."""
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    points = {tuple(p) for p in donnees["trace"]}
    assert tuple(donnees["depart"]) in points
    for bloc in donnees["blocs"]:
        # Les extrémités d'un bloc sont interpolées ; le reste vient du tracé.
        assert sum(1 for p in bloc["pts"] if tuple(p) in points) >= len(bloc["pts"]) - 2
    lat_max = max(abs(lat) for lat, _ in points)
    assert lat_max < 0.2  # le point fictif (0, 0), rien d'autre


def test_la_carte_utilise_le_cdn_autorise_et_osm(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    assert "https://cdnjs.cloudflare.com/ajax/libs/leaflet/" in page
    assert "tile.openstreetmap.org" in page
    externes = set(re.findall(r"https?://[a-z0-9.\-]+", page))
    # `www.openstreetmap.org` n'est pas une ressource chargée : c'est le lien
    # d'attribution que l'ODbL impose (C4), et il ne part que si l'on clique.
    assert externes <= {
        "https://cdnjs.cloudflare.com",
        "https://tile.openstreetmap.org",
        "https://www.openstreetmap.org",
    }, externes


def test_l_attribution_openstreetmap_est_un_lien_vers_la_licence(tmp_path: Path, monkeypatch, capsys):
    """C4 : l'ODbL demande une attribution qui **pointe** vers la page de licence."""
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    attribution = donnees["tuiles"]["attribution"]
    assert "OpenStreetMap" in attribution
    assert 'href="https://www.openstreetmap.org/copyright"' in attribution, (
        f"attribution sans lien vers la licence : {attribution!r}"
    )


def test_la_charge_json_de_la_carte_ne_peut_pas_fermer_le_script(
    tmp_path: Path, monkeypatch, capsys
):
    """C3 : `<` est neutralisé à la sérialisation, pas seulement en amont.

    Rien aujourd'hui ne fait entrer `</script>` dans la charge — tout le texte
    libre passe par `html.escape`. La garantie tenait donc à ce chemin-là et
    non à la sérialisation : le jour où un champ arrive sans échappement, la
    page devient injectable. On mesure la sérialisation elle-même.
    """
    charge = carte._charge_json({"motif": "</script><img src=x onerror=alert(1)>"})
    assert "<" not in charge and ">" not in charge, charge
    assert json.loads(charge)["motif"] == "</script><img src=x onerror=alert(1)>"

    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    script = re.search(r"^const D = (\{.*\});$", page, re.M).group(1)
    assert "<" not in script and ">" not in script


def test_la_carte_dessine_le_profil_d_altitude(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    profil = re.search(r"<svg .*?</svg>", page, re.S).group(0)
    assert profil.count("<polyline") >= 5  # le tracé, plus un par bloc
    for couleur in COULEURS_BLOCS[:4]:
        assert couleur in profil


# --- JSON ----------------------------------------------------------------------


def test_le_json_est_valide_et_complet(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["jour"] == JOUR.isoformat()
    assert charge["seance"]["n_blocs"] == 4
    assert charge["gpx"].endswith(".gpx")
    assert charge["carte"].endswith(".html")
    assert charge["tenue"]["base"]
    candidate = charge["candidates"][0]
    assert candidate["retenue"] is True
    assert len(candidate["placement"]["emplacements"]) == 4
    for emplacement in candidate["placement"]["emplacements"]:
        assert emplacement["longueur_m"] > 0
        assert isinstance(emplacement["motifs"], list)

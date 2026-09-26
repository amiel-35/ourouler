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
import dataclasses
import json
import math
import re
import types
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_seance_intervals import ATHLETE, CLE, W

from ourouler.boucle.couts import Couts
from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.cli import construire_parseur, main
from ourouler.config import (
    HORIZON_JOURS_DEFAUT,
    Config,
    Depart,
    ParametresSeance,
    depuis_dict,
)
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.seance import Etape, Seance
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.noyau.trace import distance_m as distance_points
from ourouler.physique.commande import VERSION_CALIBRATION
from ourouler.physique.litterature import FOURCHETTE_PORTE_A_PORTE_DEFAUT
from ourouler.physique.modele import Parametres
from ourouler.rendu import carte
from ourouler.rendu.boucle import ligne_temps_ecoule
from ourouler.rendu.carte import COULEURS_BLOCS
from ourouler.rendu.sortie import _ecart_seance, _ligne_modele_meteo, rendre_json, rendre_texte
from ourouler.seance.ecran_ftp import info_compteur
from ourouler.seance.placement import Emplacement, Placement
from ourouler.seance.terrain import NoteBloc
from ourouler.sortie.commande import (
    ARRONDI_DISTANCE_KM,
    Proposition,
    _comparer,
    _Contexte,
    _distance,
    _ecrire_gpx,
    _notes_egales,
    _seance,
    executer,
    lire_options,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


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


def config_avec_facteur_mesure(dossier: Path, facteur: float = 0.85) -> Config:
    """Comme `config_de_test`, avec un facteur compteur **mesuré** plutôt que
    dérivé : `moyenne_compteur_kmh` devient un nombre connu d'avance, pour
    des tests de `temps_ecoule_s` calculables à la main."""
    return config_de_test(
        dossier,
        velos=[
            {
                "nom": "Route",
                "usage": "route",
                "cda_m2": 0.32,
                "crr": 0.005,
                "facteur_compteur": facteur,
            }
        ],
    )


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
        "carte_sans_seance": False,
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


def _gestionnaire_brouter(reglages: dict[float, dict] | None = None):
    """Un anneau par azimut, réglable en relief et en rayon."""
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

    return gestionnaire


def client_brouter(reglages: dict[float, dict] | None = None) -> httpx.Client:
    """Le **client HTTP** bouchonné de `moteur_brouter`, sans le connecteur autour.

    Extrait le 17/09/2026 : les tests de contrat de l'API injectent un
    `httpx.Client` et laissent l'API l'habiller du connecteur, avec l'URL et
    les identifiants du profil (`api/routes/commun.FABRIQUES_CONNECTEUR`). Ils ont
    donc besoin de ce bouchon-ci, pas d'un `ClientBrouter` déjà pointé
    ailleurs — et refabriquer chez eux une géométrie de boucle crédible en
    ferait une deuxième à tenir à jour.

    `httpx.MockTransport` est écrit **ici**, à la construction du client, et
    non caché derrière une fonction : l'invariant qui interdit un client HTTP
    sans transport bouchonné lit le code, pas son intention.
    """
    return httpx.Client(transport=httpx.MockTransport(_gestionnaire_brouter(reglages)))


def moteur_brouter(reglages: dict[float, dict] | None = None) -> ClientBrouter:
    """BRouter bouchonné : un anneau par azimut, réglable en relief et en rayon."""
    params = depuis_dict(CONFIG_BRUTE).brouter
    return ClientBrouter(params, http=client_brouter(reglages))


# --- Open-Meteo bouchonné -----------------------------------------------------


def bloc_meteo(lat: float, lon: float, n: int, pluie: float, vent_kmh: float = 14.0) -> dict:
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-08T{6 + i:02d}:00" for i in range(n)],
            "precipitation": [pluie] * n,
            "rain": [pluie] * n,
            "wind_speed_10m": [vent_kmh] * n,
            "wind_direction_10m": [45.0] * n,
            "wind_gusts_10m": [25.0] * n,
            "apparent_temperature": [11.5] * n,
            "temperature_2m": [14.0] * n,
        },
    }


def _gestionnaire_meteo(pluie=None, en_panne: bool = False, vent_kmh: float = 14.0):
    """Le bouchon Open-Meteo, sans le transport ni le connecteur autour."""
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
                bloc_meteo(a, o, n, pluie(a, o), vent_kmh=vent_kmh)
                for a, o in zip(lats, lons, strict=True)
            ],
        )

    return gestionnaire


def client_meteo(pluie=None, en_panne: bool = False, vent_kmh: float = 14.0) -> httpx.Client:
    """Le **client HTTP** bouchonné de `moteur_meteo`. Même raison que `client_brouter`."""
    return httpx.Client(
        transport=httpx.MockTransport(_gestionnaire_meteo(pluie, en_panne, vent_kmh))
    )


def moteur_meteo(pluie=None, en_panne: bool = False, vent_kmh: float = 14.0) -> ClientOpenMeteo:
    """Open-Meteo bouchonné. `pluie` : une fonction (lat, lon) → mm/h.

    `vent_kmh` : vitesse constante du vent bouchonné (14 km/h @ 45° par
    défaut, comme avant L5.1 — les tests existants qui ne le précisent pas
    ne changent donc pas de fixture). `0.0` fabrique une météo sans vent,
    utile pour comparer un placement au vent à son équivalent sans vent
    (`test_le_vent_change_ou_tombent_les_blocs`).
    """
    return ClientOpenMeteo(http=client_meteo(pluie, en_panne, vent_kmh))


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


def lancer(
    tmp_path: Path, monkeypatch, *, meteo=None, brouter=None, intervals=None, lieu_depart=None, **champs
):
    """Exécute la commande dans `tmp_path`, clients bouchonnés, et rend le code."""
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    return executer(
        args(**champs),
        config_de_test(tmp_path / "cache"),
        brouter if brouter is not None else moteur_brouter(),
        meteo if meteo is not None else moteur_meteo(),
        intervals if intervals is not None else client_intervals(),
        lieu_depart=lieu_depart,
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


def test_carte_sans_seance_absente_par_defaut_et_activable():
    parseur = construire_parseur()
    assert parseur.parse_args(["sortie", "--jour", "2026-09-08"]).carte_sans_seance is False
    lus = parseur.parse_args(["sortie", "--jour", "2026-09-08", "--carte-sans-seance"])
    assert lus.carte_sans_seance is True


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
    assert charge["carte"] is None, "--carte-sans-seance absent : rien n'est écrit"


def test_sans_seance_et_carte_sans_seance_ecrit_une_page(tmp_path: Path, monkeypatch, capsys):
    """Contrat de l'hébergé minimal, périmètre point 4 : le service planifié
    doit produire une page, jamais rien ni une erreur, un jour sans séance."""
    code = lancer(
        tmp_path, monkeypatch, intervals=client_intervals([]), carte_sans_seance=True
    )
    sortie = capsys.readouterr().out
    assert code == 0
    pages = list((tmp_path / "cache" / "sorties").glob("*.html"))
    assert len(pages) == 1
    contenu = pages[0].read_text(encoding="utf-8")
    assert "Rien de prévu" in contenu
    assert JOUR.isoformat() in contenu
    assert not list((tmp_path / "cache" / "sorties").glob("*.gpx")), "rien à rouler, pas de GPX"
    assert str(pages[0]) in sortie


def test_sans_seance_et_carte_sans_seance_le_json_donne_le_chemin(tmp_path: Path, monkeypatch, capsys):
    code = lancer(
        tmp_path,
        monkeypatch,
        intervals=client_intervals([]),
        carte_sans_seance=True,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["seance"] is None
    assert charge["carte"] is not None
    assert Path(charge["carte"]).is_file()


def test_sans_seance_et_carte_sans_seance_respecte_loption_carte(tmp_path: Path, monkeypatch):
    code = lancer(
        tmp_path,
        monkeypatch,
        intervals=client_intervals([]),
        carte_sans_seance=True,
        carte=str(tmp_path / "ma_page.html"),
    )
    assert code == 0
    assert (tmp_path / "ma_page.html").is_file()


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


def test_a_note_equivalente_la_pluie_departage(tmp_path: Path, monkeypatch, capsys):
    """Deux anneaux de même relief, l'un au nord sous la pluie, l'autre au sud au sec.

    **Ce test exigeait des notes bit-identiques (`abs=1e-9`) jusqu'au lot
    L5.1.** Ce n'était pas son propos — c'était sa *précondition* : sans elle,
    « c'est la pluie qui départage » pourrait passer pour la mauvaise raison,
    parce que l'anneau sud aurait simplement une meilleure note.

    Depuis que le vent entre dans la note, deux anneaux de même relief mais
    d'orientation opposée **ne peuvent plus** avoir la même note : l'un est
    parcouru vent de face là où l'autre l'a dans le dos. C'est une
    impossibilité de construction, pas un réglage à trouver — aucune valeur de
    `tolerance_egalite` n'y changerait rien, puisqu'elle n'agit que sur le tri
    et jamais sur la valeur stockée.

    La précondition est donc réécrite dans la forme qu'elle aurait dû avoir
    dès le début : les deux notes doivent être **équivalentes au sens de la
    tolérance**. Si un jour elles s'écartent au-delà, ce test redeviendra
    rouge — et il aura raison, parce que le scénario aura cessé d'être une
    égalité et que l'assertion sur la pluie ne prouverait plus rien.
    """
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
    note_premiere = premiere["placement"]["note_totale"]
    note_seconde = seconde["placement"]["note_totale"]
    tolerance = ParametresSeance().tolerance_egalite
    assert _notes_egales(note_premiere, note_seconde, tolerance), (
        f"le scénario n'est plus une égalité : {note_premiere} contre {note_seconde}. "
        "L'assertion sur la pluie ne prouverait plus rien."
    )
    assert premiere["azimut_deg"] == 180.0
    assert premiere["meteo"]["pluie_cumulee_mm"] < seconde["meteo"]["pluie_cumulee_mm"]


def test_le_vent_change_ou_tombent_les_blocs(tmp_path: Path, monkeypatch, capsys):
    """Le cœur du lot L5.1 : `ourouler sortie` place maintenant avec le vent.

    Une candidate unique (azimut 0°, `candidates=1`), placée deux fois avec
    la même géométrie et la même séance — sans vent, puis avec un vent fort
    et uniforme (45 km/h @ 45°). Si le vent n'était pas branché, les deux
    placements seraient identiques au bit près (c'est exactement ce que
    `placer(..., vent=None)` garantit, et ce que les 2 936 tests du sprint 4
    vérifiaient déjà). Ici ils doivent différer : c'est la preuve que
    `ourouler sortie` construit bien un `ChampVent` et replace la séance
    avec (contrat §1.6, deuxième passe).
    """
    dossier_sans = tmp_path / "sans_vent"
    dossier_sans.mkdir()
    code = lancer(
        dossier_sans, monkeypatch, meteo=moteur_meteo(vent_kmh=0.0), candidates=1, json=True
    )
    assert code == 0
    sans_vent = json.loads(capsys.readouterr().out)["candidates"][0]["placement"]

    dossier_avec = tmp_path / "avec_vent"
    dossier_avec.mkdir()
    code = lancer(
        dossier_avec, monkeypatch, meteo=moteur_meteo(vent_kmh=45.0), candidates=1, json=True
    )
    assert code == 0
    avec_vent = json.loads(capsys.readouterr().out)["candidates"][0]["placement"]

    assert avec_vent["note_totale"] != pytest.approx(sans_vent["note_totale"]), (
        "un vent fort et uniforme doit changer la note de placement"
    )
    # Depuis le lot L5.2, `emplacements[0]` est l'échauffement (toujours au
    # km 0) : c'est le premier **bloc** — le premier emplacement noté — qui
    # doit bouger avec le vent.
    premier_bloc_sans = next(e for e in sans_vent["emplacements"] if e["note"] is not None)
    premier_bloc_avec = next(e for e in avec_vent["emplacements"] if e["note"] is not None)
    assert premier_bloc_avec["debut_m"] != pytest.approx(
        premier_bloc_sans["debut_m"]
    ), "…et donc l'endroit où tombe le premier bloc"


def _proposition_note_pluie(note: float, pluie_mm: float) -> Proposition:
    """Une `Proposition` minimale, seules la note de placement et la pluie comptent."""
    proposition = _proposition_avec_demi_tour()
    proposition.placement.note_totale = note
    proposition.meteo = types.SimpleNamespace(pluie_cumulee_mm=pluie_mm)
    return proposition


def test_notes_egales_ecart_relatif():
    """`_notes_egales` : deux notes comptent comme égales sous la tolérance (écart relatif)."""
    assert _notes_egales(1.0, 1.0, 0.0)
    assert _notes_egales(0.0, 0.0, 0.0), "deux notes nulles sont égales même à tolérance nulle"
    assert _notes_egales(0.0049, 0.0056, 0.15), "l'écart mesuré au sprint 4 (~12,5 %) est sous 15 %"
    assert not _notes_egales(0.0049, 0.0056, 0.05), "…mais pas sous 5 %"
    assert not _notes_egales(1.0, 2.0, 0.15), "un écart de 50 % n'est jamais une égalité"


def test_comparer_departage_par_la_pluie_dans_la_tolerance():
    """`_comparer` : à tolérance non nulle, la pluie décide entre deux notes proches (contrat sprint 4).

    Les deux notes (0,0049 et 0,0056) sont celles mesurées le 15/09/2026 sur
    les deux anneaux de même relief de `test_a_note_egale_la_pluie_departage`
    — 12,5 % d'écart relatif une fois le vent dans le placement. Sans
    tolérance, la meilleure note gagne même mouillée ; avec la tolérance par
    défaut, l'écart compte comme une égalité et c'est la boucle sèche qui
    l'emporte, comme au sprint 4.
    """
    mouillee_mieux_notee = _proposition_note_pluie(note=0.0049, pluie_mm=3.0)
    seche_un_peu_moins_bien_notee = _proposition_note_pluie(note=0.0056, pluie_mm=0.0)

    comparer_strict = _comparer(0.0)
    assert comparer_strict(mouillee_mieux_notee, seche_un_peu_moins_bien_notee) < 0, (
        "sans tolérance, la note seule décide même mouillée"
    )

    comparer_tolerant = _comparer(0.15)
    assert comparer_tolerant(mouillee_mieux_notee, seche_un_peu_moins_bien_notee) > 0, (
        "à tolérance 15 %, l'écart de note (12,5 %) compte comme une égalité : la pluie décide"
    )
    assert comparer_tolerant(seche_un_peu_moins_bien_notee, mouillee_mieux_notee) < 0


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
    """Un anneau trop court est écarté, et on dit pourquoi — jamais en silence.

    **Le motif a changé le 17/09/2026 (Q41 d), pas l'exigence.** Un anneau six
    fois trop petit ne va plus jusqu'au placement : il est refusé avant, parce
    qu'il est trop loin de la distance demandée (−83 % pour une tolérance de
    10 %, élargissement plafonné à 10 %). Les deux refus disent maintenant la
    même chose au même endroit, et c'est tout l'objet de ce test : **une
    direction écartée se dit**. Demander deux directions et n'en voir qu'une
    sans explication serait le défaut même que ce lot corrige.
    """
    reglages = {180.0: {"rayon_deg": RAYON_DEG / 6}}
    code = lancer(
        tmp_path, monkeypatch, brouter=moteur_brouter(reglages), candidates=2
    )
    sortie = capsys.readouterr().out
    assert code == 0
    assert "1 candidate(s) écartée(s)" in sortie
    assert "de la distance demandée" in sortie, "le motif du refus doit être lisible"
    assert "il aurait fallu élargir de" in sortie, "et dire de combien"
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


def test_le_gpx_et_la_carte_sont_ecrits_hors_du_dossier_courant(
    tmp_path: Path, monkeypatch, capsys
):
    """Q23 : par défaut, les fichiers produits ne vont plus dans le dossier courant.

    Avant ce correctif, ce test s'appelait
    `..._sont_ecrits_dans_le_dossier_courant` et vérifiait exactement ce
    défaut : sans `--sortie` ni `--carte`, les fichiers atterrissaient dans
    le répertoire courant, donc le dépôt quand la commande y est lancée
    depuis là. Ils vivent maintenant sous le dossier de cache configuré
    (`config.cache.dossier / "sorties"`), et le dossier courant ne doit plus
    en porter aucun.
    """
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    gpx = tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.gpx"
    carte = tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.html"
    assert gpx.is_file() and carte.is_file()
    assert not list(tmp_path.glob("*.gpx")) and not list(tmp_path.glob("*.html")), (
        "le dossier courant ne doit porter aucun fichier produit par défaut (Q23)"
    )
    assert str(gpx) in sortie and str(carte) in sortie, "le chemin complet doit être dit en clair"
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
    texte = (tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.gpx").read_text(
        encoding="utf-8"
    )
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
    return _contexte_avec(seance, config)


def _contexte_avec(seance: Seance, config: Config) -> Any:
    """Comme `_contexte_minimal`, mais avec une configuration donnée — pour
    tester le bloc `compteur` à facteur mesuré, ou sans vélo du tout."""
    demande = lire_options(args(), config)
    return _Contexte(
        seance=seance,
        demande=demande,
        config=config,
        distance_km=34.0,
        distance_source="déduite de la séance",
        provenance_modele="calibration du vélo Route",
        ecartees=[],
        tenue=None,
        gpx=None,
        carte=None,
        # Comme `executer` : le bloc « compteur » est lu par la commande, le
        # rendu le reçoit (lot 6).
        compteur_info=info_compteur(config, demande.velo),
    )


# --- temps écoulé porte à porte, et le bloc « compteur » (18/09/2026) --------
#
# Même défaut, même correction que `boucle` : la colonne « temps » montrait le
# temps *en mouvement* du placement (`placement.duree_totale_s`) comme s'il
# s'agissait du temps écoulé de la sortie. Ici, `compteur` et
# `candidate.temps_ecoule_s`, câblés dans `rendre_json`/`rendre_texte` via
# `ecran_ftp.info_compteur` et `physique.modele.temps_ecoule` — la même
# formule que `boucle`, testée à part dans `tests/test_physique_modele.py`.


def test_compteur_et_temps_ecoule_sont_nuls_sans_velo(tmp_path: Path):
    """Le test explicite du DoD : `compteur` et `temps_ecoule_s` de chaque
    candidate valent `null` sur une configuration sans vélo — même si, en
    pratique, `sortie` a toujours besoin d'un vélo pour placer une séance
    (`_parametres` lève sinon) : ce cas ne s'obtient qu'en le retirant après
    coup, comme pour `boucle`."""
    seance = _seance_fabriquee()
    config = dataclasses.replace(config_de_test(tmp_path / "cache"), velos=())
    charge = rendre_json([_proposition_avec_demi_tour()], _contexte_avec(seance, config))
    assert charge["compteur"] is None
    candidate = charge["candidates"][0]
    assert candidate["temps_ecoule_s"] is None
    assert candidate["temps_ecoule_source"] is None
    # Le temps de mouvement du placement, lui, reste renseigné.
    assert candidate["placement"]["duree_totale_s"] == round(
        _proposition_avec_demi_tour().placement.duree_totale_s
    )


def test_compteur_json_porte_les_quatre_champs_du_contrat(tmp_path: Path):
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    charge = rendre_json([_proposition_avec_demi_tour()], _contexte_avec(seance, config))
    compteur = charge["compteur"]
    assert compteur["velo"] == "Route"
    assert compteur["facteur_compteur"] == pytest.approx(0.85)
    assert compteur["facteur_provenance"] == "mesure"
    assert compteur["moyenne_compteur_kmh"] > 0
    assert compteur["porte_a_porte"]["provenance"] == "defaut"


def test_temps_ecoule_json_suit_la_formule_partagee(tmp_path: Path):
    """Pas une deuxième formule : `candidate.temps_ecoule_s` et ses bornes
    sont exactement `physique.modele.temps_ecoule` appliqué à
    `placement.duree_totale_s` (le parcours réellement roulé, demi-tours
    compris — pas la boucle) et à la fourchette du bloc `compteur`."""
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    proposition = _proposition_avec_demi_tour()
    charge = rendre_json([proposition], _contexte_avec(seance, config))
    candidate = charge["candidates"][0]
    mouvement = proposition.placement.duree_totale_s
    bas, mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT
    assert candidate["temps_ecoule_s"] == round(mouvement * mediane)
    assert candidate["temps_ecoule_bas_s"] == round(mouvement * bas)
    assert candidate["temps_ecoule_haut_s"] == round(mouvement * haut)
    assert candidate["temps_ecoule_source"] == "defaut"
    assert candidate["temps_ecoule_s"] >= candidate["placement"]["duree_totale_s"]


def test_texte_sortie_affiche_mouvement_et_ecoule(tmp_path: Path):
    """CLI et front disent la même chose, **dans le même ordre** : le porte à
    porte d'abord, en fourchette, le temps sans arrêt ensuite, dans une
    cellule combinée, et la légende partagée avec `boucle` sous le tableau."""
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    contexte = _contexte_avec(seance, config)
    proposition = _proposition_avec_demi_tour()
    texte = rendre_texte([proposition], contexte)

    from ourouler.seance.ecran_ftp import info_compteur

    compteur = info_compteur(config, contexte.demande.velo)
    mouvement = proposition.placement.duree_totale_s
    bas, _mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT

    def hm(secondes: float) -> str:
        minutes = round(secondes / 60)
        return f"{minutes // 60}:{minutes % 60:02d}"

    assert f"{hm(mouvement * bas)}-{hm(mouvement * haut)} / {hm(mouvement)}" in texte
    assert ligne_temps_ecoule(compteur) in texte


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


#: Les quatre commandes qui portent une heure de départ, et le minimum à leur
#: passer pour que le parseur accepte la ligne.
COMMANDES_A_HEURE_DEPART = {
    "meteo": [],
    "boucle": ["--distance", "40", "--direction", "N"],
    "simuler": ["--gpx", "x.gpx", "--puissance", "200"],
    "sortie": [],
}


#: Les trois commandes qui partent d'un **lieu**, donc qui portent
#: `--adresse-depart` (lot F0.7). `simuler` n'en est pas : elle part du GPX
#: qu'on lui donne, pas d'un point.
COMMANDES_A_ADRESSE_DEPART = ("meteo", "boucle", "sortie")


def test_l_heure_de_depart_s_appelle_heure_depart_partout():
    """Q15, tranchée par le mainteneur le 13/09.

    L'heure de départ s'appelle `--heure-depart` ; le lieu de départ
    s'appelle `--adresse-depart` (livré par F0.7). `--depart`, qui disait
    « heure » alors que `--adresse-depart` dit « lieu », et `--heure`, ajouté
    en attendant la décision, restent acceptés pour ne rien casser.
    """
    parseur = construire_parseur()
    for commande, arguments in COMMANDES_A_HEURE_DEPART.items():
        lus = parseur.parse_args([commande, *arguments, "--heure-depart", "08:00"])
        assert lus.depart == "08:00", f"{commande} : --heure-depart n'alimente pas `depart`"
        lus = parseur.parse_args([commande, *arguments, "--heure", "09:30"])
        assert lus.depart == "09:30", f"{commande} : --heure n'alimente pas `depart`"
        lus = parseur.parse_args([commande, *arguments, "--depart", "10:15"])
        assert lus.depart == "10:15", f"{commande} : --depart a été perdu"


def test_les_anciens_noms_de_l_heure_de_depart_ne_sont_plus_documentes():
    """Acceptés, oui ; enseignés, non (Q15).

    L'aide ne doit plus proposer `--depart` ni `--heure` : les laisser dans
    l'aide reviendrait à ne rien avoir tranché.
    """
    parseur = construire_parseur()
    sous = next(
        action
        for action in parseur._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for commande in COMMANDES_A_HEURE_DEPART:
        aide = sous.choices[commande].format_help()
        assert "--heure-depart" in aide, f"{commande} : le nom canonique manque dans l'aide"
        # Les deux noms canoniques sont retirés avant de chercher les anciens :
        # « --adresse-depart » est cité dans l'aide de `--heure-depart` et
        # réciproquement, précisément pour qu'on ne les confonde pas.
        sans_noms_canoniques = aide.replace("--heure-depart", "").replace("--adresse-depart", "")
        for ancien in ("--depart", "--heure"):
            assert ancien not in sans_noms_canoniques, (
                f"{commande} : l'aide documente encore {ancien}"
            )


def test_le_lieu_de_depart_s_appelle_adresse_depart_et_rien_d_autre():
    """Ce que gardait le test du nom réservé, maintenant que le nom est livré (F0.7).

    Le test écrit au sprint 4 vérifiait que `--adresse-depart` **n'existait
    pas**, pour que le nom ne soit pas pris par autre chose avant qu'on le
    livre. Ce qu'il protégeait vraiment, c'est le nom lui-même — pas son
    absence : c'est ce qui est vérifié ici.

    Aucun des noms écartés (`--depuis`, provisoire du plan du sprint 4,
    `--lieu-depart`, `--depart-adresse`) ne doit apparaître à la place, et
    l'option n'existe que là où partir d'ailleurs a un sens : `simuler` part
    du GPX qu'on lui donne, pas d'un point.
    """
    parseur = construire_parseur()
    sous = next(
        action
        for action in parseur._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for commande in COMMANDES_A_HEURE_DEPART:
        aide = sous.choices[commande].format_help()
        attendu = commande in COMMANDES_A_ADRESSE_DEPART
        assert ("--adresse-depart" in aide) is attendu, (
            f"{commande} : --adresse-depart devrait "
            f"{'figurer' if attendu else 'être absent'} de l'aide"
        )
        for ecarte in ("--depuis", "--lieu-depart", "--depart-adresse"):
            assert ecarte not in aide, (
                f"{commande} : {ecarte} a été livré à la place du nom retenu"
            )


def test_l_adresse_de_depart_et_l_heure_de_depart_ne_se_confondent_pas():
    """Les deux options sur la même ligne, chacune dans son `dest` (Q15).

    C'est la confusion pour laquelle le lieu ne s'appelle pas `--depart` : un
    `dest` partagé ferait qu'une heure deviendrait un lieu, ou l'inverse, sans
    que rien ne le dise.
    """
    parseur = construire_parseur()
    for commande in COMMANDES_A_ADRESSE_DEPART:
        arguments = COMMANDES_A_HEURE_DEPART[commande]
        lus = parseur.parse_args(
            [commande, *arguments, "--heure-depart", "08:00", "--adresse-depart", "Place du Test"]
        )
        assert lus.depart == "08:00", f"{commande} : l'heure a été écrasée par le lieu"
        assert lus.adresse_depart == "Place du Test", f"{commande} : le lieu n'est pas arrivé"

        # L'ordre inverse, et l'ancien nom de l'heure, ne changent rien.
        lus = parseur.parse_args(
            [commande, *arguments, "--adresse-depart", "Place du Test", "--depart", "10:15"]
        )
        assert lus.depart == "10:15"
        assert lus.adresse_depart == "Place du Test"

        # Sans l'option, aucun lieu n'est demandé : la configuration décide.
        lus = parseur.parse_args([commande, *arguments])
        assert lus.adresse_depart is None


#: Un départ « ailleurs », toujours fictif : à quelques centièmes de degré du
#: point zéro de la configuration de test, donc mesurable sans nommer un lieu
#: réel (règle absolue 1).
AILLEURS = Depart(nom="Place inventée 44999 Vallombreuse", latitude=0.123456, longitude=0.234567)


def test_sortie_part_du_lieu_recu_et_pas_de_celui_de_la_configuration(tmp_path: Path, monkeypatch):
    """F0.7 : le cœur reçoit un `Depart`, il ne le lit pas.

    Les deux services qui partent d'un point sont surveillés : la question
    d'orientation au vent (premier appel Open-Meteo, sur le départ) et la
    génération des candidates (BRouter). Un seul des deux resté sur la
    configuration donnerait une sortie fausse — le vent de chez soi, ou la
    boucle de chez soi.
    """
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")

    departs_brouter: list[tuple[float, float]] = []
    points_meteo: list[tuple[float, float]] = []

    def espion_brouter(requete: httpx.Request) -> httpx.Response:
        lon, lat = requete.url.params["lonlats"].split(",")
        departs_brouter.append((float(lat), float(lon)))
        azimut = float(requete.url.params["roundTripStartDirection"])
        return httpx.Response(200, json=reponse_anneau(anneau(azimut)))

    def espion_meteo(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        lats = [float(x) for x in p["latitude"].split(",")]
        lons = [float(x) for x in p["longitude"].split(",")]
        points_meteo.extend(zip(lats, lons, strict=True))
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        return httpx.Response(
            200, json=[bloc_meteo(a, o, n, 0.0) for a, o in zip(lats, lons, strict=True)]
        )

    brouter = ClientBrouter(
        depuis_dict(CONFIG_BRUTE).brouter,
        http=httpx.Client(transport=httpx.MockTransport(espion_brouter)),
    )
    meteo = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(espion_meteo)))

    code = executer(
        args(json=True),
        config_de_test(tmp_path / "cache"),
        brouter,
        meteo,
        client_intervals(),
        lieu_depart=AILLEURS,
    )
    assert code == 0

    assert departs_brouter, "aucune candidate demandée au moteur"
    for lat, lon in departs_brouter:
        assert (lat, lon) == pytest.approx((AILLEURS.latitude, AILLEURS.longitude), abs=1e-6)

    # Le tout premier appel météo est la question du vent, posée sur le départ.
    # `abs=1e-3` : le client arrondit les coordonnées qu'il envoie.
    assert points_meteo[0] == pytest.approx(
        (AILLEURS.latitude, AILLEURS.longitude), abs=1e-3
    ), "la question du vent est restée sur le départ configuré"


def test_le_json_de_sortie_dit_de_quel_lieu_la_boucle_part(tmp_path: Path, monkeypatch, capsys):
    """Sans cette clé, deux réponses identiques décriraient deux parcours différents.

    C'est ce dont l'API aura besoin pour que le front sache d'où part ce
    qu'il affiche : l'heure de départ était publiée, le lieu non.
    """
    lancer(tmp_path, monkeypatch, json=True, lieu_depart=AILLEURS)
    charge = json.loads(capsys.readouterr().out)
    lieu = charge["demande"]["lieu_depart"]
    assert lieu["nom"] == AILLEURS.nom
    assert lieu["latitude"] == pytest.approx(AILLEURS.latitude)
    assert lieu["longitude"] == pytest.approx(AILLEURS.longitude)

    lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["lieu_depart"]["nom"] == "Point zéro", (
        "sans lieu fourni, le JSON doit nommer le départ de la configuration"
    )


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


def test_un_retour_au_calme_qui_s_allonge_s_affiche_sans_avertissement(tmp_path: Path):
    """Q14 : « c'est du kilomètre facile » ne s'affiche pas avec un ⚠.

    Les deux listes du placement ne se rendent pas de la même façon : les
    avertissements portent un ⚠, les informations non. Un retour au calme qui
    s'allonge dans sa fenêtre est une information, et l'afficher comme une
    alerte était précisément le ton que le mainteneur a corrigé.
    """
    proposition = _proposition_avec_demi_tour()
    proposition.placement.informations = [
        "retour au calme : 38 min au lieu des 20 prescrites, 8 km de plus à allure facile"
    ]
    proposition.placement.avertissements = ["étape 1 (libre) : aucune puissance cible"]

    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    info = next(ligne for ligne in texte.splitlines() if "retour au calme : 38 min" in ligne)
    assert "⚠" not in info, info
    assert "8 km de plus à allure facile" in info
    alerte = next(ligne for ligne in texte.splitlines() if "aucune puissance cible" in ligne)
    assert "⚠" in alerte, "les vrais défauts gardent leur ⚠"


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
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(), config)

    chemin = _ecrire_gpx(trace, place, seance, demande, config)

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
    # Q23 : le fichier par défaut vit sous le dossier de cache, plus le
    # dossier courant — voir `chemin_carte_par_defaut`.
    return (tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.html").read_text(
        encoding="utf-8"
    )


def test_la_carte_se_parse_en_html_et_porte_le_nom_de_la_seance(
    tmp_path: Path, monkeypatch, capsys
):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    compteur = _Compteur()
    compteur.feed(page)
    assert compteur.desequilibres == []
    assert compteur.pile == []
    assert "4x8 fabriquée" in compteur.titre
    # Lot L5.4 : la page du jour porte un profil d'altitude **par proposition**
    # contrastée, chacun un vrai `<svg>` statique — un seul visible à la fois
    # (`hidden` posé par `_page_jour`, pas absent du HTML), c'est ce qui permet
    # de changer de proposition sans redemander de calcul au serveur.
    assert compteur.balises.get("svg") == len(donnees["propositions"])
    assert compteur.balises.get("script") == 2  # Leaflet, puis le script de la page


def test_la_carte_porte_les_quatre_blocs_avec_leur_note(tmp_path: Path, monkeypatch, capsys):
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    # Lot L5.4 : la page porte une liste `propositions`, chacune avec ses
    # propres blocs — la première est celle que le tri a retenue.
    premiere = donnees["propositions"][0]
    assert len(premiere["blocs"]) == 4
    for numero, bloc in enumerate(premiere["blocs"], start=1):
        assert bloc["couleur"] == COULEURS_BLOCS[numero - 1]
        assert bloc["etiquette"].startswith(f"{numero} ·")
        assert "Bloc" in bloc["infobulle"]
        assert len(bloc["pts"]) >= 2
    # Les liaisons (échauffement, récups, calme) sont là et ne portent pas de note.
    assert premiere["liaisons"]


def test_la_carte_ne_contient_que_la_geometrie_du_trace(tmp_path: Path, monkeypatch, capsys):
    """Aucune coordonnée ne vient du générateur : tout sort du tracé passé en paramètre."""
    page = carte_produite(tmp_path, monkeypatch)
    capsys.readouterr()
    donnees = json.loads(re.search(r"^const D = (\{.*\});$", page, re.M).group(1))
    premiere = donnees["propositions"][0]
    points = {tuple(p) for p in premiere["trace"]}
    assert tuple(premiere["depart"]) in points
    for bloc in premiere["blocs"]:
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
    # Depuis le lot L5.2 (Q13), `emplacements` porte toutes les étapes, pas
    # seulement les blocs : échauffement, 4 blocs, 4 récupérations, retour au
    # calme — 10 étapes pour 4 blocs.
    assert len(candidate["placement"]["emplacements"]) == 10
    for emplacement in candidate["placement"]["emplacements"]:
        assert emplacement["longueur_m"] > 0
        if emplacement["note"] is None:
            assert emplacement["motifs"] is None, (
                "une étape sans note ne doit pas porter de motifs inventés"
            )
        else:
            assert isinstance(emplacement["motifs"], list)
    # Lot L5.3 : `km_non_classe` manquait côté sortie alors qu'il existait déjà
    # côté boucle libre — sans lui, un tracé partiellement classé s'annonce
    # aussi calme qu'un tracé entièrement classé.
    assert "km_non_classe" in candidate["couts"]
    # Les flèches de vent (mêmes que la carte HTML) sont aussi dans ce JSON ;
    # le vent bouchonné par défaut (14 km/h) dépasse le seuil sensible.
    fleches = candidate["meteo"]["fleches_vent"]
    assert fleches, "un vent bouchonné à 14 km/h doit produire des flèches"
    for fleche in fleches:
        assert set(fleche) == {"pt", "depuis_deg", "vent_kmh", "rafale_kmh", "relatif"}
    # Le tracé entier, pour le colorer (lot d'affordance, 20/09/2026) : une
    # position par échantillon, sans le filtre de sensibilité de `fleches_vent`
    # — donc au moins autant de positions que de flèches.
    positions = candidate["meteo"]["vent_par_position"]
    assert len(positions) >= len(fleches)
    for position in positions:
        assert set(position) == {"dist_m", "relatif"}


def test_une_etape_libre_compte_dans_le_dimensionnement(tmp_path: Path):
    """Une étape sans puissance prescrite n'est pas une étape de longueur nulle.

    Faute trouvée le 16/09/2026 sur la séance de référence « 4x8 SV1 outdoor »
    du 22/04 : 22 étapes, dont trois « libres » — échauffement 20 min,
    récupération 12 min, retour au calme 40 min. `_distance` ne sommait que
    les longueurs chiffrées, donc **63 min sur 135 seulement comptaient** :
    le moteur demandait une boucle de 35 km pour une sortie de 67, puis
    rattrapait en roulant la boucle presque deux fois avec des demi-tours
    dont personne n'avait besoin.

    Le test compare deux séances de même durée : l'une entièrement chiffrée,
    l'autre dont la moitié est libre. Les distances demandées doivent rester
    du même ordre — sans le repli à l'allure d'endurance, la seconde tombe à
    la moitié de la première.
    """
    config = config_de_test(tmp_path)
    parametres = PARAMETRES
    chiffree = Seance(
        nom="chiffrée",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, 150.0, 150.0, "Z2"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    moitie_libre = Seance(
        nom="moitié libre",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, None, None, "libre"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    demande = types.SimpleNamespace(distance_km=None)
    km_chiffree, _ = _distance(demande, chiffree, parametres, config)
    km_libre, _ = _distance(demande, moitie_libre, parametres, config)
    assert km_libre > km_chiffree * 0.7, (
        f"une séance à moitié libre est dimensionnée à {km_libre} km contre "
        f"{km_chiffree} km pour la même durée entièrement chiffrée : les étapes "
        "libres comptent encore pour zéro"
    )


def test_une_etape_libre_sans_ftp_retombe_sur_la_vitesse_moyenne(tmp_path: Path):
    """Point 4 (T5) : `pct * ftp_w` avec `ftp_w=None` levait `TypeError`.

    Sans FTP renseignée, les minutes des étapes libres ne peuvent plus être
    converties en distance par le modèle physique — repli silencieux sur
    `config.boucle.vitesse_moyenne_kmh`, la même vitesse assumée que le repli
    « aucune étape chiffrée du tout » déjà présent dans `_distance`.
    """
    config = config_de_test(tmp_path, cycliste={"masse_kg": 76.5})
    assert config.cycliste.ftp_w is None
    parametres = PARAMETRES
    moitie_libre = Seance(
        nom="moitié libre",
        jour=JOUR,
        duree_s=3600.0,
        etapes=[
            Etape("echauffement", 1800.0, None, None, "libre"),
            Etape("bloc", 1800.0, 150.0, 150.0, "Z2"),
        ],
    )
    demande = types.SimpleNamespace(distance_km=None)
    km, source = _distance(demande, moitie_libre, parametres, config)
    assert km > 0
    assert "faute de FTP renseignée" in source


# --- les propositions contrastées (lot L5.3) ----------------------------------


def test_le_json_publie_les_propositions_avec_leur_phrase(tmp_path: Path, monkeypatch, capsys):
    """Les clés que le contrat du lot fixe : `distinction`, `axe_distinctif`,
    `densite_marqueurs_km`, `question_vent`."""
    code = lancer(tmp_path, monkeypatch, candidates=3, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    propositions = charge["propositions"]
    assert propositions, charge
    assert propositions[0]["retenue"] is True
    assert propositions[0]["numero"] == 1
    for proposition in propositions:
        for cle in (
            "distinction",
            "axe_distinctif",
            "densite_marqueurs_km",
            "part_trafic",
            "orientation_vent",
            "recouvrement_max_avec",
        ):
            assert cle in proposition, proposition
    assert charge["question_vent"] is not None
    assert "motif_deux_propositions" in charge


def test_chaque_proposition_porte_une_phrase_et_un_axe_distinct(
    tmp_path: Path, monkeypatch, capsys
):
    """Le garde-fou du lot : pas de phrase, pas de proposition — et deux
    propositions ne peuvent pas se réclamer du même axe."""
    lancer(tmp_path, monkeypatch, candidates=3, json=True)
    propositions = json.loads(capsys.readouterr().out)["propositions"]
    if len(propositions) == 1:
        return  # une seule : rien à distinguer, c'est un cas légitime
    axes = [p["axe_distinctif"] for p in propositions]
    assert all(p["distinction"] for p in propositions), propositions
    assert all(axe for axe in axes), propositions
    vents = [p["orientation_vent"] for p in propositions if p["axe_distinctif"] == "vent"]
    assert len(set(vents)) == len(vents), "deux propositions du même vent"
    non_vent = [a for a in axes if a != "vent"]
    assert len(set(non_vent)) == len(non_vent), axes


def test_moins_de_trois_propositions_dit_pourquoi(tmp_path: Path, monkeypatch, capsys):
    """Avec une seule candidate, il n'y a rien à contraster — et c'est écrit."""
    lancer(tmp_path, monkeypatch, candidates=1, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert len(charge["propositions"]) == 1
    assert charge["motif_deux_propositions"]


def test_les_propositions_sont_un_sous_ensemble_des_candidates(
    tmp_path: Path, monkeypatch, capsys
):
    """`candidates` reste la liste complète et inchangée : un script du sprint 4
    qui la lisait continue de marcher."""
    lancer(tmp_path, monkeypatch, candidates=3, json=True)
    charge = json.loads(capsys.readouterr().out)
    numeros_candidates = {c["numero"] for c in charge["candidates"]}
    numeros_propositions = {p["numero"] for p in charge["propositions"]}
    assert numeros_propositions <= numeros_candidates
    assert len(charge["candidates"]) >= len(charge["propositions"])


def test_sous_le_seuil_de_vent_la_question_n_est_pas_posee(tmp_path: Path, monkeypatch, capsys):
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(vent_kmh=1.0), candidates=2, json=True)
    question = json.loads(capsys.readouterr().out)["question_vent"]
    assert question["posee"] is False
    assert question["motif"]
    assert question["azimuts_recherche_deg"] == []


def test_au_dessus_du_seuil_la_question_est_posee_et_le_texte_la_montre(
    tmp_path: Path, monkeypatch, capsys
):
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(vent_kmh=30.0), candidates=2)
    sortie = capsys.readouterr().out
    assert "Vent au départ" in sortie
    assert "--vent retour-dos" in sortie


def test_une_reponse_au_vent_dirige_la_recherche(tmp_path: Path, monkeypatch, capsys):
    """Le vent bouchonné vient de 45° : pour rentrer avec, on part vers 45°."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        candidates=2,
        vent="retour-dos",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["question_vent"]["reponse"] == "retour-dos"
    assert charge["question_vent"]["azimuts_recherche_deg"] == [pytest.approx(45.0)]


def test_demander_une_direction_et_une_orientation_au_vent_est_refuse(
    tmp_path: Path, monkeypatch
):
    """Q44 : les deux fixent le même azimut, et rien ne disait lequel gagnait.

    `--direction` l'emportait en silence — le cycliste qui avait demandé de
    rentrer avec le vent dans le dos partait au nord sans jamais l'apprendre.
    On ne choisit plus un gagnant, on refuse la contradiction.
    """
    with pytest.raises(ErreurUtilisateur) as erreur:
        lancer(
            tmp_path,
            monkeypatch,
            meteo=moteur_meteo(vent_kmh=30.0),
            direction="N",
            candidates=2,
            vent="retour-dos",
            json=True,
        )
    message = str(erreur.value)
    assert "--direction" in message and "--vent" in message


def test_une_direction_seule_reste_acceptee(tmp_path: Path, monkeypatch, capsys):
    """Le refus ne vise que la contradiction : « au nord » tout court marche."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        direction="N",
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["azimut_deg"] == 0.0


def test_peu_importe_avec_une_direction_n_est_pas_une_contradiction(
    tmp_path: Path, monkeypatch, capsys
):
    """« Peu importe » est l'absence de demande, pas une demande concurrente."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        direction="N",
        candidates=2,
        vent="peu-importe",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["azimut_deg"] == 0.0


def test_une_reponse_au_vent_inconnue_est_refusee_avant_tout_appel(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brouter, meteo, intervals = clients_interdits()
    with pytest.raises(ErreurUtilisateur, match="--vent"):
        executer(
            args(vent="plein-nord"),
            config_de_test(tmp_path / "cache"),
            brouter,
            meteo,
            intervals,
        )


# --- Q21 a : l'alerte d'amputation suit le placement, pas un seuil en minutes --


def test_moins_d_une_minute_n_est_jamais_dit():
    """Sous 60 s, l'écart n'est même pas affiché — arrondi du placement, pas une info."""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=30.0)) == ""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=-30.0)) == ""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=None)) == ""


def test_un_depassement_positif_reste_neutre():
    assert _ecart_seance(types.SimpleNamespace(depassement_s=18 * 60.0)) == " (+18 min)"


def test_un_ecart_negatif_sans_verdict_d_amputation_n_alerte_pas():
    """Le défaut mesuré (Q21 a) : 1 min sur 2 h prescrites (0,8 %) déclenchait ⚠

    à tort, alors que le seuil du mainteneur (`elasticite_calme_min`, −5 %)
    ne le justifiait pas. `seance_amputee` porte le verdict du placement, qui
    honore déjà ce seuil (`seance.placement`) — ce test fige seulement que
    l'affichage le respecte, sans lui-même recalculer un pourcentage.
    """
    profil = types.SimpleNamespace(depassement_s=-60.0, seance_amputee=False)
    texte = _ecart_seance(profil)
    assert "⚠" not in texte
    assert "amput" not in texte
    assert texte == " (-1 min)"


def test_un_ecart_negatif_amputant_la_seance_alerte():
    profil = types.SimpleNamespace(depassement_s=-12 * 60.0, seance_amputee=True)
    assert _ecart_seance(profil) == " (⚠ séance amputée de 12 min)"


# --- Q19 : le modèle météo utilisé est nommé dans l'en-tête --------------------


def _config_avec_modele(modele: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(meteo=types.SimpleNamespace(modele=modele))


def _proposition_avec_meteo(meteo) -> types.SimpleNamespace:
    return types.SimpleNamespace(meteo=meteo)


def test_sans_meteo_aucune_ligne_de_modele():
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(None)], _config_avec_modele("AROME"))
    assert lignes == []


def test_sans_repli_la_ligne_nomme_juste_le_modele():
    meteo = types.SimpleNamespace(modele_utilise="AROME", repli=False)
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(meteo)], _config_avec_modele("AROME"))
    assert lignes == ["Météo : modèle AROME."]


def test_le_repli_est_dit_et_nomme_les_deux_modeles():
    """Critère d'acceptation du contrat : « en nommant le modèle utilisé »."""
    meteo = types.SimpleNamespace(modele_utilise="ICON", repli=True)
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(meteo)], _config_avec_modele("AROME"))
    assert len(lignes) == 1
    assert "AROME" in lignes[0] and "ICON" in lignes[0]
    assert "ne couvre pas" in lignes[0]


# --- --fichier-seance (F1, C1 de docs/journal/ux/relecture_f0.md) ---------------------

ZWO_SORTIE_FABRIQUE = (
    "<?xml version='1.0'?>\n<workout_file>\n<name>Séance fichier fabriquée</name>\n"
    '<workout><SteadyState Duration="1200" Power="1.0"/></workout>\n'
    "</workout_file>\n"
)


def _ecrire_zwo_sortie(tmp_path: Path) -> Path:
    chemin = tmp_path / "seance.zwo"
    chemin.write_text(ZWO_SORTIE_FABRIQUE, encoding="utf-8")
    return chemin


def refus_intervals() -> ClientIntervals:
    """Un client Intervals qui fait échouer le test dès qu'on le sollicite."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise AssertionError("Intervals.icu appelé alors qu'un fichier de séance était donné")

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


def test_lire_options_porte_le_fichier_de_la_demande(tmp_path: Path):
    chemin = _ecrire_zwo_sortie(tmp_path)
    demande = lire_options(args(fichier_seance=str(chemin)), config_de_test(tmp_path / "cache"))
    assert demande.fichier == chemin


def test_sans_option_le_fichier_de_la_demande_est_absent(tmp_path: Path):
    demande = lire_options(args(), config_de_test(tmp_path / "cache"))
    assert demande.fichier is None


def test_seance_avec_fichier_ne_touche_jamais_intervals(tmp_path: Path):
    chemin = _ecrire_zwo_sortie(tmp_path)
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(fichier_seance=str(chemin)), config)
    seance = _seance(demande, config, refus_intervals())
    assert seance is not None
    assert seance.meta["source"] == "zwo"
    assert seance.jour == demande.jour


def test_seance_avec_fichier_marche_meme_sans_client_donne(tmp_path: Path):
    """`client=None` construit normalement un `ClientIntervals` depuis la config —
    avec un fichier, cette branche n'est jamais atteinte."""
    chemin = _ecrire_zwo_sortie(tmp_path)
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(fichier_seance=str(chemin)), config)
    seance = _seance(demande, config, None)
    assert seance is not None


def test_seance_sans_fichier_utilise_toujours_intervals(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(), config)
    seance = _seance(demande, config, client_intervals())
    assert seance is not None
    assert seance.nom == "4x8 fabriquée"


def test_fichier_seance_bout_en_bout_remplace_intervals(tmp_path: Path, monkeypatch):
    """Preuve de bout en bout via `executer` : la recherche de parcours tourne
    sur une séance de fichier sans jamais appeler Intervals.icu."""
    chemin = _ecrire_zwo_sortie(tmp_path)
    # `distance=34.0` : la séance du .ZWO vaut environ 15 km, alors que l'anneau
    # bouchonné en fait 33,9 quel que soit le rayon. Depuis Q41 (d), un tel
    # écart (+126 %) est refusé au lieu d'être servi en silence — la boucle ne
    # serait donc jamais construite, et le sujet du test (la séance vient d'un
    # fichier, Intervals n'est jamais appelé) ne serait plus atteignable. La
    # distance n'a jamais été son sujet ; on la fixe pour ne pas la subir.
    code = lancer(
        tmp_path,
        monkeypatch,
        fichier_seance=str(chemin),
        intervals=refus_intervals(),
        distance=34.0,
    )
    assert code == 0


# --- Q40 (g) : aucun GPX à la génération, un GPX au choix ----------------------

#: Deux azimuts au relief marqué : de quoi que `contraste.choisir` ait
#: réellement trois propositions à distinguer. Avec des anneaux identiques il
#: n'en reste qu'une, et un test sur « trois traces différentes » ne prouve
#: plus rien.
RELIEFS_CONTRASTES = {0.0: {"amplitude_m": 90.0}, 180.0: {"amplitude_m": 40.0}}


def test_recueil_gpx_n_ecrit_aucun_fichier_et_rend_les_trois_traces(
    tmp_path: Path, monkeypatch, capsys
):
    """Q40 (g) : « aucun GPX à la génération, et on le fait à la demande. »

    Les trois propositions sont contrastées exprès ; n'écrire que celle du
    classement, c'était envoyer la mauvaise trace au compteur à qui
    choisissait « la plus sèche ». Écrire les trois, c'était en jeter deux.
    """
    recueillis: list = []
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    code = executer(
        args(json=True, candidates=4),
        config_de_test(tmp_path / "cache"),
        moteur_brouter(RELIEFS_CONTRASTES),
        moteur_meteo(pluie=pluie_au_nord),
        client_intervals(),
        recueil_gpx=recueillis.extend,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert not list((tmp_path / "cache" / "sorties").glob("*.gpx")), (
        "aucun GPX ne doit être écrit quand l'appelant les recueille"
    )
    assert charge["gpx"] is None, "le JSON ne doit pas annoncer un fichier qui n'existe pas"
    assert len(recueillis) >= 2, (
        "le bouchon ne contraste plus rien : sans deux propositions, ce test ne prouve rien"
    )
    numeros = [g.numero for g in recueillis]
    assert numeros == [p["numero"] for p in charge["propositions"]]
    assert len({g.texte for g in recueillis}) == len(recueillis), (
        "deux propositions contrastées ne peuvent pas rendre le même GPX"
    )
    for gpx in recueillis:
        assert gpx.nom_fichier.endswith(f"_n{gpx.numero}.gpx")
        assert lire_gpx_trace(gpx.texte.encode("utf-8")).points


def test_sans_recueil_la_ligne_de_commande_ecrit_toujours_son_gpx(
    tmp_path: Path, monkeypatch, capsys
):
    """La ligne de commande ne change pas : `--sortie` (ou le nom daté) est écrit."""
    demande = tmp_path / "choisi.gpx"
    code = lancer(tmp_path, monkeypatch, json=True, sortie=str(demande))
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert demande.is_file() and demande.read_text(encoding="utf-8").startswith("<?xml")
    assert charge["gpx"] == str(demande)


def test_la_carte_embarque_les_memes_gpx_que_le_recueil(tmp_path: Path, monkeypatch, capsys):
    """Un seul calcul pour deux usages : la page du jour et l'appelant lisent la même trace."""
    recueillis: list = []
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    executer(
        args(json=True, candidates=4),
        config_de_test(tmp_path / "cache"),
        moteur_brouter(RELIEFS_CONTRASTES),
        moteur_meteo(pluie=pluie_au_nord),
        client_intervals(),
        recueil_gpx=recueillis.extend,
    )
    capsys.readouterr()
    page = (tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.html").read_text(
        encoding="utf-8"
    )
    for gpx in recueillis:
        assert gpx.nom_fichier in page


# --- Q40 (a) : une date lointaine est servie, sans météo -----------------------


def test_une_date_lointaine_est_servie_sans_appeler_open_meteo(
    tmp_path: Path, monkeypatch, capsys
):
    """Q40 (a) : « si on demande trop loin, ben pas de météo » — et direct.

    Le client météo interdit fait échouer le test au premier appel : demander
    ~150 prévisions pour récolter des blocs vides serait payer le service pour
    apprendre ce que la date disait déjà.
    """
    _, meteo_interdite, _ = clients_interdits()
    lointain = date.today() + timedelta(days=HORIZON_JOURS_DEFAUT + 30)
    code = lancer(
        tmp_path,
        monkeypatch,
        meteo=meteo_interdite,
        jour=lointain.isoformat(),
        json=True,
    )
    lu = capsys.readouterr()
    charge = json.loads(lu.out)
    assert code == 0, "le parcours est servi, la date n'est pas refusée"
    assert charge["candidates"], "la boucle reste là : c'est la météo qui disparaît"
    absente = charge["meteo_absente"]
    assert absente["jour"] == lointain.isoformat()
    assert absente["dernier_jour_couvert"] == (
        date.today() + timedelta(days=HORIZON_JOURS_DEFAUT)
    ).isoformat()
    assert "pas de météo" in absente["message"]
    assert "s'arrêtent" in absente["message"], "le message dit jusqu'où vont les prévisions"
    assert "pas de météo" in lu.err


def test_une_date_lointaine_ne_promet_ni_pluie_ni_vent_ni_tenue(
    tmp_path: Path, monkeypatch, capsys
):
    """E14 · dégradé : ce qui disparaît sont les affirmations qu'on ne soutient plus."""
    _, meteo_interdite, _ = clients_interdits()
    lointain = date.today() + timedelta(days=HORIZON_JOURS_DEFAUT + 30)
    lancer(
        tmp_path, monkeypatch, meteo=meteo_interdite, jour=lointain.isoformat(), json=True
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["tenue"] is None
    assert charge["modele_meteo"] is None
    assert all(c["meteo"] is None for c in charge["candidates"])
    assert charge["question_vent"]["posee"] is False


def test_une_meteo_en_panne_dans_l_horizon_ne_promet_pas_une_fin_de_previsions(
    tmp_path: Path, monkeypatch, capsys
):
    """Le même écran, l'autre cause — et la phrase ne dit toujours pas pourquoi."""
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(en_panne=True), json=True)
    charge = json.loads(capsys.readouterr().out)
    absente = charge["meteo_absente"]
    assert absente["jour"] == JOUR.isoformat()
    assert "s'arrêtent" not in absente["message"], (
        "les prévisions couvrent ce jour-là : elles n'ont rien rendu, ce n'est pas la même chose"
    )


def test_la_meteo_repond_dans_l_horizon(tmp_path: Path, monkeypatch, capsys):
    """Contre-épreuve : tant qu'on est dans l'horizon, rien ne change."""
    lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert charge["meteo_absente"] is None
    assert charge["candidates"][0]["meteo"] is not None


# --- Q44 : le travers ouvre deux azimuts, et les candidates s'y répartissent ---
#
# Le point que le mainteneur demande explicitement de vérifier plutôt que de
# supposer : « les candidates doivent alors se répartir entre les deux azimuts,
# pas s'entasser sur le premier ».
#
# Le piège est réel et il est dans `boucle.candidates.azimuts` : un appel
# `generer(azimut, nb)` explore `azimut`, puis ±20°, ±40°… — il **élargit un
# secteur, il n'en ouvre jamais un second**. Un seul appel pour deux azimuts
# opposés aurait donc rendu toutes les candidates du même côté, et le JSON
# aurait quand même annoncé deux directions.


def azimuts_demandes_a_brouter() -> tuple[httpx.Client, list[float]]:
    """Un BRouter bouchonné qui note chaque `roundTripStartDirection` reçu."""
    vus: list[float] = []
    gestionnaire = _gestionnaire_brouter()

    def espion(requete: httpx.Request) -> httpx.Response:
        vus.append(float(requete.url.params["roundTripStartDirection"]))
        return gestionnaire(requete)

    params = depuis_dict(CONFIG_BRUTE).brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(espion))), vus


def cote(azimut: float, reference: float) -> int:
    """0 ou 1 : de quel côté de la paire d'opposés tombe `azimut`.

    L'écart angulaire est ramené dans [0, 180] avant comparaison — sans quoi
    350° et 10° passeraient pour éloignés de 340°.
    """
    ecart = abs((azimut - reference + 180.0) % 360.0 - 180.0)
    return 0 if ecart <= 90.0 else 1


def test_le_travers_repartit_les_candidates_entre_les_deux_azimuts(
    tmp_path: Path, monkeypatch, capsys
):
    """Quatre candidates de travers : deux d'un côté, deux de l'autre."""
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=4,
        vent="travers",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    azimuts = charge["question_vent"]["azimuts_recherche_deg"]
    assert len(azimuts) == 2, azimuts

    # Ce que BRouter a réellement été prié d'explorer, et non ce que le JSON
    # annonce : c'est la différence entre la promesse et le fait.
    cotes = [cote(a, azimuts[0]) for a in vus]
    assert cotes.count(0) > 0 and cotes.count(1) > 0, vus
    assert abs(cotes.count(0) - cotes.count(1)) <= 1, vus

    # Et les candidates rendues, pas seulement les appels émis.
    retenus = [cote(c["azimut_deg"], azimuts[0]) for c in charge["candidates"]]
    assert retenus.count(0) > 0 and retenus.count(1) > 0, charge["candidates"]


def test_le_travers_ne_demande_jamais_un_seul_cote(tmp_path: Path, monkeypatch, capsys):
    """Le défaut qu'on corrige, pris à l'envers : trois candidates suffisent.

    Trois se répartissent 2/1 — le reste va au premier azimut, assumé — mais
    **jamais 3/0** : une part nulle voudrait dire que le second azimut n'a pas
    été exploré du tout.
    """
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=3,
        vent="travers",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    premier = charge["question_vent"]["azimuts_recherche_deg"][0]
    cotes = [cote(a, premier) for a in vus]
    assert cotes.count(1) > 0, f"tout est parti du même côté : {vus}"


def test_rentrer_avec_le_vent_n_explore_qu_un_secteur(tmp_path: Path, monkeypatch, capsys):
    """Le pendant : « rentrer avec » contraint, et on le voit dans les appels.

    C'est ce qui rend la mesure de Q44 lisible — la préférence qui contraint
    le plus est celle qui produit les propositions les plus ressemblantes.
    """
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=4,
        vent="retour-dos",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    (azimut,) = charge["question_vent"]["azimuts_recherche_deg"]
    assert all(cote(a, azimut) == 0 for a in vus), vus


def test_le_texte_nomme_les_deux_azimuts_du_travers(tmp_path: Path, monkeypatch, capsys):
    """Annoncer « vers 315° » une recherche menée à 315° **et** 135° serait faux."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        candidates=4,
        vent="travers",
    )
    sortie = capsys.readouterr().out
    assert "directions imposées" in sortie
    # Vent bouchonné de 45° : le travers ouvre 135° et 315°.
    assert "135°" in sortie and "315°" in sortie


def test_sortie_avertit_aussi_quand_le_modele_vient_de_la_litterature(tmp_path: Path):
    """L'avertissement ne tenait qu'au mot « défaut » (corrigé le 18/09/2026).

    Depuis que les vélos non calibrés reçoivent les valeurs de
    `physique.litterature`, la provenance ne commence plus par « défaut » : le
    ⚠ disparaissait exactement dans le cas où il sert — des blocs placés sur
    des vitesses jamais mesurées sur ce cycliste (règle absolue 5).
    """
    seance = _seance_fabriquee()
    contexte = dataclasses.replace(
        _contexte_minimal(tmp_path, seance), provenance_modele="littérature (Route)"
    )
    texte = rendre_texte([_proposition_avec_demi_tour()], contexte)
    assert "aucun vélo calibré" in texte
    assert "viennent de la littérature" in texte

    calibre = dataclasses.replace(
        _contexte_minimal(tmp_path, seance), provenance_modele="calibration (Route)"
    )
    assert "aucun vélo calibré" not in rendre_texte([_proposition_avec_demi_tour()], calibre)

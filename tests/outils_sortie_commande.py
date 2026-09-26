"""Bouchons et fabriques partagés par les tests de `ourouler sortie`.

Aucun réseau : les trois clients — BRouter, Open-Meteo, Intervals — passent
par un `httpx.MockTransport`. Aucune donnée personnelle : la configuration
part du point fictif (0.0, 0.0), les boucles sont des anneaux fabriqués
autour de ce point, et la séance vient des `workout_doc` inventés de
`tests/fixtures/workouts.py`.

Les anneaux sont paramétrés par azimut : c'est ainsi qu'on fabrique des
candidates dont on connaît d'avance le classement — une boucle plate se note
mieux qu'une boucle qui descend, et c'est la note de placement qui doit
trier, la pluie ne départageant qu'à égalité.

Les tests de l'API et les tests adversariaux empruntent ces mêmes bouchons :
un seul harnais à tenir à jour.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
from test_seance_intervals import ATHLETE, CLE, W

from ourouler.boucle.couts import Couts
from ourouler.commandes.sortie import executer_depuis_namespace as executer
from ourouler.commandes.sortie import lire_options
from ourouler.config import (
    Config,
    Depart,
    depuis_dict,
)
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.seance import Etape, Seance
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.noyau.trace import distance_m as distance_points
from ourouler.physique.modele import Parametres
from ourouler.seance.ecran_ftp import info_compteur
from ourouler.seance.placement import Emplacement, Placement
from ourouler.seance.terrain import NoteBloc
from ourouler.sortie.commande import (
    Proposition,
    _Contexte,
)
from ourouler.stockage.calibrations import VERSION_CALIBRATION

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


#: Un départ « ailleurs », toujours fictif : à quelques centièmes de degré du
#: point zéro de la configuration de test, donc mesurable sans nommer un lieu
#: réel (règle absolue 1).
AILLEURS = Depart(nom="Place inventée 44999 Vallombreuse", latitude=0.123456, longitude=0.234567)


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


# --- Q40 (g) : aucun GPX à la génération, un GPX au choix ----------------------

#: Deux azimuts au relief marqué : de quoi que `contraste.choisir` ait
#: réellement trois propositions à distinguer. Avec des anneaux identiques il
#: n'en reste qu'une, et un test sur « trois traces différentes » ne prouve
#: plus rien.
RELIEFS_CONTRASTES = {0.0: {"amplitude_m": 90.0}, 180.0: {"amplitude_m": 40.0}}


def cote(azimut: float, reference: float) -> int:
    """0 ou 1 : de quel côté de la paire d'opposés tombe `azimut`.

    L'écart angulaire est ramené dans [0, 180] avant comparaison — sans quoi
    350° et 10° passeraient pour éloignés de 340°.
    """
    ecart = abs((azimut - reference + 180.0) % 360.0 - 180.0)
    return 0 if ecart <= 90.0 else 1

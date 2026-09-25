"""Les données synthétiques du filet 0b, **copiées ici** plutôt qu'importées.

Le filet ne doit dépendre que de surfaces que les lots de restructuration ne
déplacent pas : `ourouler.cli.main`, l'application FastAPI et `httpx`. Il
importait jusqu'ici des modules de test (`test_sortie_commande`,
`test_seance_intervals`, `test_physique_calibration`, `test_physique_commande`)
et `ourouler.physique.modele.Parametres` : un lot qui déplace l'un d'eux
cassait le filet pour une mauvaise raison — ou pire, un lot qui corrige un
bug du modèle physique changeait les **entrées** du filet sans qu'on le voie.

Ce module ne dépend donc **de rien sous `src/`** (vérifié par
`test_le_filet_ne_depend_que_de_surfaces_stables`). Chaque fabrique est la
copie, calcul pour calcul, de celle d'où elle vient ; les sorties produites
sont identiques à l'octet (les références n'ont pas bougé en la copiant).

- séance Intervals : `rejeu_intervals_evenement.json`, sérialisation de
  `workouts.evenement(workouts.groupes_watts(), nom="4x8 fabriquée")` ;
- anneau BRouter : `anneau` et `reponse_anneau` de `tests/test_sortie_commande.py` ;
- sorties TCX : `sortie_synthetique` de `tests/test_physique_calibration.py`
  (le modèle `puissance_requise`/`vitesse_regime` de `physique/modele.py`,
  réduit au plat sans vent) et `_en_tcx` de `tests/test_physique_commande.py`.

Aucune donnée personnelle : départ (0, 0) en mer, identifiants inventés.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DOSSIER = Path(__file__).resolve().parent

# --- Intervals.icu ------------------------------------------------------------

#: Identifiant d'athlète et clé entièrement inventés.
ATHLETE = "i000000"
CLE = "cle-de-test-inventee"


def evenement_seance() -> dict:
    """La séance « 4x8 fabriquée » du 8 septembre 2026, telle qu'Intervals la rend."""
    texte = (DOSSIER / "rejeu_intervals_evenement.json").read_text(encoding="utf-8")
    return json.loads(texte)


# --- BRouter : un anneau qui part de (0, 0) -----------------------------------

#: Rayon d'un anneau, en degrés : environ 34 km de tour à l'équateur.
RAYON_DEG = 0.0485

#: Nombre de points d'un anneau : un point tous les ~85 m.
POINTS_ANNEAU = 400


def anneau(
    azimut_deg: float, *, rayon_deg: float = RAYON_DEG, amplitude_m: float = 1.0, n: int = POINTS_ANNEAU
) -> list[tuple[float, float, float]]:
    """Un anneau fermé qui part du point (0, 0) et s'éloigne vers `azimut_deg`."""
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


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
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
    """Le GeoJSON d'un anneau, au format du serveur BRouter réel."""
    pas = max(1, (len(points) - 1) // troncons)
    fins = list(range(pas, len(points), pas))
    if fins[-1] != len(points) - 1:
        fins.append(len(points) - 1)
    messages = [list(ENTETE_MESSAGES)]
    debut = 0
    total = 0.0
    for fin in fins:
        longueur = sum(_distance_m(points[i][:2], points[i + 1][:2]) for i in range(debut, fin))
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


# --- sorties TCX fabriquées par le modèle physique ------------------------------

#: Constantes de `physique/modele.py` au moment de la copie. Elles sont celles
#: des **entrées** du filet : si le modèle change, les entrées ne bougent pas,
#: et c'est la sortie de `calibrer` qui doit dire ce qui a changé.
_G = 9.80665
_RHO = 1.226
_RENDEMENT = 0.976
_V_MAX_MS = 30.0
_TOLERANCE_MS = 1e-10
_MAX_ITERATIONS = 200
_METRE_EN_DEGRE = 1.0 / 111_194.93


@dataclass(frozen=True)
class Reglage:
    """Masse, CdA et Crr d'un couple cycliste + vélo fabriqué."""

    masse_totale_kg: float
    cda_m2: float
    crr: float


#: Le vélo de route (RCR) et le vélo de contre-la-montre (BMC) fabriqués.
ROUTE = Reglage(masse_totale_kg=100.0, cda_m2=0.31, crr=0.0045)
CLM = Reglage(masse_totale_kg=100.0, cda_m2=0.26, crr=0.0045)


def _puissance_requise(v_ms: float, r: Reglage) -> float:
    """`physique.modele.puissance_requise` sur le plat, sans vent — même ordre d'opérations."""
    theta = math.atan(0.0)
    v_air = v_ms + 0.0
    resistance = r.crr * r.masse_totale_kg * _G * math.cos(theta) + r.masse_totale_kg * _G * math.sin(
        theta
    )
    trainee = 0.5 * _RHO * r.cda_m2 * v_air * abs(v_air)
    return (resistance * v_ms + trainee * v_ms) / _RENDEMENT


def _vitesse_regime(puissance_w: float, r: Reglage) -> float:
    """`physique.modele.vitesse_regime` : bissection sur [0, 30 m/s]."""
    haut = _V_MAX_MS
    if _puissance_requise(haut, r) - puissance_w <= 0:
        return haut
    bas = 0.0
    for _ in range(_MAX_ITERATIONS):
        if haut - bas <= _TOLERANCE_MS:
            break
        milieu = (bas + haut) / 2
        if _puissance_requise(milieu, r) - puissance_w > 0:
            haut = milieu
        else:
            bas = milieu
    return (bas + haut) / 2


def _puissance_ondulante(seconde: int) -> float:
    return 200.0 + 15.0 * math.sin(seconde / 400.0)


def tcx_synthetique(r: Reglage, jour: date, *, duree_s: int = 2600) -> bytes:
    """Une sortie plein est depuis (0, 0), départ à 09:00 UTC, un point sur cinq."""
    debut = datetime(jour.year, jour.month, jour.day, 9, 0, tzinfo=UTC)
    points = []
    distance = 0.0
    altitude = 100.0
    for seconde in range(duree_s):
        puissance = _puissance_ondulante(seconde)
        v = _vitesse_regime(puissance, r) * 1.0
        if seconde % 5 == 0:
            t = debut + timedelta(seconds=seconde)
            points.append(
                "<Trackpoint>"
                f"<Time>{t.isoformat().replace('+00:00', 'Z')}</Time>"
                f"<Position><LatitudeDegrees>{0.0:.7f}</LatitudeDegrees>"
                f"<LongitudeDegrees>{distance * _METRE_EN_DEGRE:.7f}</LongitudeDegrees></Position>"
                f"<AltitudeMeters>{altitude:.2f}</AltitudeMeters>"
                f"<DistanceMeters>{distance:.2f}</DistanceMeters>"
                "<Extensions><TPX xmlns=\"http://www.garmin.com/xmlschemas/ActivityExtension/v2\">"
                f"<Speed>{v:.3f}</Speed><Watts>{puissance:.0f}</Watts>"
                "</TPX></Extensions>"
                "</Trackpoint>"
            )
        distance += v
        altitude += v * 0.0
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        f'<Activities><Activity Sport="Biking"><Id>{debut.isoformat()}</Id>'
        f'<Lap StartTime="{debut.isoformat()}"><Track>{"".join(points)}</Track></Lap>'
        "</Activity></Activities></TrainingCenterDatabase>"
    ).encode()


def ecrire_historique(dossier: Path) -> Path:
    """Huit sorties plates de RCR en janvier, huit de BMC en février, en TCX."""
    dossier.mkdir(parents=True, exist_ok=True)
    for mois, reglage in ((1, ROUTE), (2, CLM)):
        for jour in range(1, 9):
            quand = date(2026, mois, jour)
            (dossier / f"sortie_{quand.isoformat()}.tcx").write_bytes(tcx_synthetique(reglage, quand))
    return dossier

"""Couronne de points autour du départ : une direction × une distance = un point.

Calcul de destination sur la sphère (rayon moyen 6 371 km). C'est largement
suffisant à 15-40 km : l'écart avec un calcul ellipsoïdal est de l'ordre de
0,1 %, très en dessous de la maille du modèle météo (1,3 km pour AROME HD).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.noyau.erreurs import ErreurConfig
from ourouler.noyau.profil import DIRECTIONS_ACCEPTEES, Depart

#: Rayon moyen de la Terre, en kilomètres.
RAYON_TERRE_KM = 6371.0

#: Nom du point de départ lui-même dans la couronne (distance 0).
NOM_ICI = "ici"

#: Les 8 directions cardinales et intercardinales, en français (O = ouest).
NOMS_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")

#: Les 16 directions, en français, si `directions = 16` est demandé.
NOMS_DIRECTIONS_16 = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSO",
    "SO",
    "OSO",
    "O",
    "ONO",
    "NO",
    "NNO",
)

#: Nombres de directions acceptés. Défini dans `config` — c'est lui qui doit
#: refuser la valeur au chargement ; importé ici pour le message d'erreur.


@dataclass(frozen=True)
class PointCouronne:
    """Un point interrogé : son nom de direction, son azimut, sa distance et ses coordonnées."""

    nom: str
    azimut_deg: float
    distance_km: float
    lat: float
    lon: float


def noms_directions(directions: int) -> tuple[str, ...]:
    """Les noms des directions pour 8 ou 16 secteurs. Lève `ErreurConfig` sinon."""
    if directions == 8:
        return NOMS_DIRECTIONS
    if directions == 16:
        return NOMS_DIRECTIONS_16
    raise ErreurConfig(f"[meteo] directions = {directions}, attendu un de {DIRECTIONS_ACCEPTEES}")


def destination(lat: float, lon: float, azimut_deg: float, distance_km: float) -> tuple[float, float]:
    """Point atteint depuis (lat, lon) en suivant `azimut_deg` sur `distance_km`.

    Formule de destination sur la grande sphère :
        φ₂ = asin(sin φ₁ cos δ + cos φ₁ sin δ cos θ)
        λ₂ = λ₁ + atan2(sin θ sin δ cos φ₁, cos δ − sin φ₁ sin φ₂)
    avec δ = d / R.
    """
    if distance_km == 0:
        return (lat, lon)
    delta = distance_km / RAYON_TERRE_KM
    theta = math.radians(azimut_deg)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    # Ramène la longitude dans [-180, 180].
    lon2 = (math.degrees(lambda2) + 540.0) % 360.0 - 180.0
    return (math.degrees(phi2), lon2)


def couronne(depart: Depart, directions: int, distances_km: Sequence[float]) -> list[PointCouronne]:
    """Les points à interroger : le départ lui-même, puis chaque distance × chaque direction.

    L'ordre est stable et regroupé par distance croissante, ce qui donne
    directement les tables du rapport (une par distance).
    """
    noms = noms_directions(directions)
    pas = 360.0 / len(noms)
    points = [
        PointCouronne(
            nom=NOM_ICI,
            azimut_deg=0.0,
            distance_km=0.0,
            lat=depart.latitude,
            lon=depart.longitude,
        )
    ]
    for distance in sorted({float(d) for d in distances_km}):
        if distance <= 0:
            continue
        for i, nom in enumerate(noms):
            azimut = i * pas
            lat, lon = destination(depart.latitude, depart.longitude, azimut, distance)
            points.append(PointCouronne(nom=nom, azimut_deg=azimut, distance_km=distance, lat=lat, lon=lon))
    return points


def azimut_de(nom: str, directions: int = 8) -> float:
    """L'azimut d'un nom de direction (`"NE"` → 45,0). Lève `ErreurConfig` si inconnu."""
    noms = noms_directions(directions)
    if nom not in noms:
        raise ErreurConfig(f"direction inconnue : {nom!r} (attendu un de {noms})")
    return noms.index(nom) * (360.0 / len(noms))


def nom_de_azimut(azimut_deg: float, directions: int = 8) -> str:
    """Le nom de direction le plus proche d'un azimut (225° → `"SO"`).

    La réciproque d'`azimut_de`, au secteur près : un azimut quelconque tombe
    rarement pile sur une des huit branches, on prend la plus proche. 246°
    reste « SO », 250° devient « O ».

    Elle existe pour que le **front n'ait pas à la refaire** : « vent de
    sud-ouest » est une valeur affichée, et une valeur affichée ne se calcule
    pas côté écran. Un azimut non fini n'a pas de nom — on rend `""` plutôt
    qu'une direction inventée (on n'affirme rien sans mesure).
    """
    if not math.isfinite(azimut_deg):
        return ""
    noms = noms_directions(directions)
    secteur = 360.0 / len(noms)
    return noms[round((azimut_deg % 360.0) / secteur) % len(noms)]


def ecart_angulaire(a_deg: float, b_deg: float) -> float:
    """Écart absolu entre deux azimuts, dans [0, 180]."""
    ecart = abs(a_deg - b_deg) % 360.0
    return 360.0 - ecart if ecart > 180.0 else ecart


def distance_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance orthodromique entre deux points, en km (formule de haversine).

    Avec `azimut_initial_deg`, l'inverse de `destination` : ce qui permet de
    vérifier la couronne de l'extérieur.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * RAYON_TERRE_KM * math.asin(math.sqrt(a))


def azimut_initial_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Azimut initial du trajet (lat1, lon1) → (lat2, lon2), en degrés dans [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x)) % 360.0

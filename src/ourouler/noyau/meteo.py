"""Types de prévision météo : ce que le client Open-Meteo rend et ce que le domaine lit.

Rangés au noyau pour que le domaine et le cache des prévisions les
connaissent sans importer le client HTTP (`meteo.openmeteo`), qui les utilise.

`HeureArchive` : une heure de l'archive Open-Meteo — le vent qu'il
faisait. Le calcul de calibration (`physique.calibration`) la lit sans
importer le connecteur d'archive (`connecteurs.openmeteo_archive`), qui
l'utilise aussi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PrevisionHeure:
    """Une heure de prévision en un point. Toute valeur peut manquer (`null` côté API)."""

    t: datetime
    pluie_mm: float | None
    vent_kmh: float | None
    rafales_kmh: float | None
    vent_depuis_deg: float | None
    ressenti_c: float | None
    temp_c: float | None


@dataclass(frozen=True)
class PrevisionPoint:
    """La prévision horaire d'un point, dans l'ordre où il a été demandé."""

    lat: float
    lon: float
    heures: list[PrevisionHeure]


@dataclass(frozen=True)
class HeureArchive:
    """Une heure d'archive en un point. Toute valeur peut manquer (`null` côté API)."""

    t: datetime  # UTC
    vent_kmh: float | None
    vent_depuis_deg: float | None
    temp_c: float | None
    pression_hpa: float | None


def interpoler_lineaire(a: float | None, b: float | None, f: float) -> float | None:
    """`a + (b - a) × f`, ou `None` si l'une des deux valeurs manque."""
    if a is None or b is None:
        return None
    return a + (b - a) * f


def interpoler_angle(a: float | None, b: float | None, f: float) -> float | None:
    """Interpolation d'un angle par ses composantes : 350° et 10° donnent 0°, pas 180°.

    Une seule version pour la calibration, la météo le long du tracé et le
    champ de vent de la séance : deux copies auraient tôt fait de diverger, et
    c'est exactement la faute qu'elle évite.
    """
    if a is None or b is None:
        return None
    ra, rb = math.radians(a), math.radians(b)
    x = math.cos(ra) + (math.cos(rb) - math.cos(ra)) * f
    y = math.sin(ra) + (math.sin(rb) - math.sin(ra)) * f
    if x == 0.0 and y == 0.0:  # deux directions opposées à mi-chemin : indécidable
        return a
    return math.degrees(math.atan2(y, x)) % 360.0

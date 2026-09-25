"""Types de prévision météo : ce que le client Open-Meteo rend et ce que le domaine lit.

Rangés au noyau (lot 4) pour que le domaine et le cache des prévisions les
connaissent sans importer le client HTTP (`meteo.openmeteo`), qui les
réexporte.
"""

from __future__ import annotations

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

#!/usr/bin/env python3
"""Génère les réponses BRouter de test dans `tests/fixtures/brouter/`.

Réponses **fabriquées**, jamais enregistrées : la trajectoire est un petit
cercle autour du point fictif (0.0, 0.0), en pleine mer dans le golfe de
Guinée. Le format, lui, est celui relevé sur le serveur réel :

- `features[0].geometry.coordinates` = `[lon, lat, alt]` en degrés ;
- `properties` : `track-length`, `total-time`, `filtered ascend`, `cost`…
  **en chaînes** ;
- `properties.messages` : une ligne d'en-tête de 13 colonnes puis une ligne
  par tronçon, coordonnées en **microdegrés entiers passés en chaînes**,
  retombant exactement sur un point de la géométrie, `Distance` en mètres
  dont la somme vaut `track-length`.

Usage : `uv run python tests/fixtures/generer_brouter.py`
Le script est idempotent : il réécrit les mêmes octets à chaque exécution.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

LAT_FICTIVE = 0.0
LON_FICTIVE = 0.0
RAYON_TERRE_M = 6_371_000.0

DOSSIER_DEFAUT = Path(__file__).resolve().parent / "brouter"

#: 30 points, 6 messages : ce que demande le contrat de sprint pour la fixture.
NB_POINTS = 30
FINS_DE_TRONCON = (5, 10, 15, 20, 25, 29)

ENTETE = [
    "Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost",
    "TurnCost", "NodeCost", "InitialCost", "WayTags", "NodeTags", "Time", "Energy",
]  # fmt: skip

#: Un jeu de tags volontairement varié : trafic, calme, non revêtu, sans surface.
TAGS = (
    "highway=residential surface=asphalt",
    "highway=tertiary surface=asphalt",
    "highway=secondary surface=asphalt",
    "highway=track surface=gravel",
    "highway=cycleway surface=paved",
    "highway=primary surface=asphalt lanes=2",
)


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine entre deux (lat, lon), en mètres."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * RAYON_TERRE_M * math.asin(math.sqrt(h))


def trajectoire(n: int = NB_POINTS) -> list[tuple[float, float, float]]:
    """Un anneau fermé légèrement irrégulier : (lat, lon, alt), dernier point = premier."""
    points: list[tuple[float, float, float]] = []
    for i in range(n - 1):
        angle = 2 * math.pi * i / (n - 1)
        rayon = 0.010 + 0.002 * math.sin(3 * angle)
        lat = round(LAT_FICTIVE + rayon * math.cos(angle), 6)
        lon = round(LON_FICTIVE + rayon * math.sin(angle), 6)
        alt = round(30.0 + 10.0 * math.sin(2 * angle), 2)
        points.append((lat, lon, alt))
    points.append(points[0])  # la boucle se referme sur son point de départ
    return points


def denivele_positif(points: list[tuple[float, float, float]]) -> float:
    return sum(max(0.0, b[2] - a[2]) for a, b in zip(points, points[1:], strict=False))


def reponse_boucle(points: list[tuple[float, float, float]] | None = None) -> dict:
    """La réponse GeoJSON complète, au format du serveur réel."""
    points = points or trajectoire()
    messages: list[list[str]] = [list(ENTETE)]
    debut = 0
    longueurs: list[int] = []
    for numero, fin in enumerate(FINS_DE_TRONCON):
        longueur = round(
            sum(
                distance_m(points[i][:2], points[i + 1][:2])
                for i in range(debut, min(fin, len(points) - 1))
            )
        )
        longueurs.append(longueur)
        lat, lon, alt = points[fin]
        messages.append(
            [
                str(round(lon * 1e6)),
                str(round(lat * 1e6)),
                str(round(alt)),
                str(longueur),
                "1200",
                "0",
                "0" if numero % 2 else "20",
                "0",
                "0",
                TAGS[numero],
                "",
                str(120 * (numero + 1)),
                str(9000 * (numero + 1)),
            ]
        )
        debut = fin
    longueur_totale = sum(longueurs)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "creator": "BRouter-1.7.8",
                    "name": "brouter_fastbike_0",
                    "track-length": str(longueur_totale),
                    "filtered ascend": str(round(denivele_positif(points))),
                    "plain-ascend": "0",
                    "total-time": str(round(longueur_totale / 7.0)),
                    "total-energy": "540000",
                    "cost": str(longueur_totale * 2),
                    "messages": messages,
                    "times": [round(i * 12.0, 1) for i in range(len(points))],
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat, alt] for lat, lon, alt in points],
                },
            }
        ],
    }


def generer(dossier: Path | None = None) -> dict[str, Path]:
    dossier = dossier or DOSSIER_DEFAUT
    dossier.mkdir(parents=True, exist_ok=True)
    fichiers = {"boucle_fabriquee.json": reponse_boucle()}
    ecrits: dict[str, Path] = {}
    for nom, charge in fichiers.items():
        chemin = dossier / nom
        chemin.write_text(json.dumps(charge, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        ecrits[nom] = chemin
    return ecrits


if __name__ == "__main__":  # pragma: no cover
    for nom, chemin in generer().items():
        print(f"{nom:24} {chemin.stat().st_size:>8} octets")

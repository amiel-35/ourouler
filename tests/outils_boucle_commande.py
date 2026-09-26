"""Bouchons et fabriques partagés par les tests de `ourouler boucle`.

Configuration de test au point fictif (0.0, 0.0), `[brouter] url` inventée,
les deux clients bouchonnés par un `httpx.MockTransport` : aucun accès
réseau, aucune coordonnée réelle, aucun identifiant.

Les réponses BRouter viennent du générateur de fixtures
(`tests/fixtures/generer_brouter.py`, via `test_brouter.reponse_fabriquee`) ;
les réponses Open-Meteo sont fabriquées ici, au format que le service rend.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from test_brouter import reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.boucle.commande import (
    Evaluation,
)
from ourouler.boucle.couts import Couts
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.config import Config, depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.rendu.boucle import (
    MARQUE_RETENUE,
)

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
    """BRouter bouchonné : une boucle fabriquée dont la longueur dépend de l'azimut.

    Répond aussi à un appel `itineraire` (sans `roundTripStartDirection`) : le
    greffage de tags sur un GPX importé (`boucle.tags_importes`) en fait un,
    et ce même client sert souvent à générer *et* à réévaluer un GPX dans le
    même test.
    """

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        azimut_brut = requete.url.params.get("roundTripStartDirection")
        charge = reponse_fabriquee()
        if azimut_brut is not None:
            entite = charge["features"][0]
            longueur = (longueur_par_azimut or {}).get(float(azimut_brut), 60_000.0)
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


# --- le mode --gpx -------------------------------------------------------------


def gpx_de_test(tmp_path: Path) -> Path:
    """Un GPX écrit depuis une boucle fabriquée, relu ensuite par `--gpx`."""
    trace = moteur_brouter().boucle((0.0, 0.0), azimut_deg=45.0, rayon_m=12_000.0)
    chemin = tmp_path / "importee.gpx"
    chemin.write_text(ecrire_gpx(trace, trace.nom), encoding="utf-8")
    return chemin


def _cellule(lignes: list[str], entete: str, titre: str) -> float:
    """La valeur en mètres de la colonne `titre`, sur la ligne suivant l'en-tête.

    Les colonnes sont justifiées à droite : la cellule finit là où finit son
    titre.
    """
    fin = entete.index(titre) + len(titre)
    return float(lignes[lignes.index(entete) + 1][:fin].rsplit(None, 2)[-2])

# --- colonne « temps estimé » ---------------------------------------------------
#
# La colonne « temps estimé » vient du modèle calibré si `calibration.json`
# existe, avec la mention `(modèle)` ; sinon la vitesse moyenne de la
# configuration, avec la mention `(27 km/h)`.


def config_avec_velo_calibrable(dossier: Path, **sections: Any) -> Config:
    return config_de_test(
        cache={"dossier": str(dossier)},
        velos=[{"nom": "RCR", "usage": "route"}],
        **sections,
    )


# --- temps écoulé porte à porte, et le bloc « compteur » -----------------------
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

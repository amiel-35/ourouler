"""Client Open-Meteo : un seul appel HTTP pour tous les points de la couronne.

Open-Meteo est gratuit et sans clé (usage non commercial). L'API accepte
plusieurs coordonnées dans un même appel (`latitude=a,b,c&longitude=…`) et
renvoie alors une **liste** de blocs, un par point ; pour un seul point elle
renvoie un **objet**. Les deux formes sont gérées.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ourouler.erreurs import ErreurConnecteur

BASE_URL_DEFAUT = "https://api.open-meteo.com"
CHEMIN_PREVISION = "/v1/forecast"

#: Variables horaires demandées, dans l'ordre du contrat de sprint.
VARIABLES_HORAIRES = (
    "precipitation",
    "rain",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "apparent_temperature",
    "temperature_2m",
)

#: Format ISO sans secondes, attendu par `start_hour` / `end_hour`.
FORMAT_HEURE = "%Y-%m-%dT%H:%M"

DELAI_S = 30.0

#: Modèle global proposé quand le point sort du domaine d'un modèle régional.
MODELE_GLOBAL_SUGGERE = "icon_seamless"

#: Un littéral `nan` / `NaN` / `inf` là où un nombre est attendu (`"latitude":nan`).
#: Mesuré sur le vrai service : hors du domaine d'AROME, Open-Meteo répond
#: HTTP 200 avec un corps que `json.loads` refuse. La classe de caractères en
#: tête évite de confondre avec un `nan` dans une chaîne (« Nanterre »).
LITTERAL_NON_JSON = re.compile(r"[:,\[]\s*-?(?:nan|inf(?:inity)?)\b", re.IGNORECASE)


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


class ClientOpenMeteo:
    """Client Open-Meteo. `http` est injectable : les tests ne touchent jamais le réseau."""

    def __init__(self, http: httpx.Client | None = None, base_url: str = BASE_URL_DEFAUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http if http is not None else httpx.Client(timeout=DELAI_S)

    @property
    def url_prevision(self) -> str:
        """L'URL sans paramètres — la seule qu'on cite dans un message d'erreur."""
        return f"{self.base_url}{CHEMIN_PREVISION}"

    def previsions(
        self,
        points: Sequence[tuple[float, float]],
        *,
        modele: str,
        debut: datetime,
        horizon_h: int,
    ) -> list[PrevisionPoint]:
        """Prévisions horaires pour tous les points, en **un seul** appel HTTP.

        `debut` doit être conscient du fuseau (sinon il est lu comme UTC) ;
        la fenêtre couvre `horizon_h` heures à partir de `debut` inclus.
        """
        if not points:
            raise ErreurConnecteur(f"Open-Meteo : aucun point à interroger ({self.url_prevision})")
        if horizon_h < 1:
            raise ErreurConnecteur(f"Open-Meteo : horizon de {horizon_h} h, au moins 1 h attendue")

        debut_utc = debut.astimezone(UTC) if debut.tzinfo else debut.replace(tzinfo=UTC)
        fin_utc = debut_utc + timedelta(hours=horizon_h - 1)
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
            "hourly": ",".join(VARIABLES_HORAIRES),
            "models": modele,
            "timezone": "UTC",
            "start_hour": debut_utc.strftime(FORMAT_HEURE),
            "end_hour": fin_utc.strftime(FORMAT_HEURE),
        }

        try:
            reponse = self.http.get(self.url_prevision, params=params)
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"Open-Meteo injoignable sur {self.url_prevision} ({type(e).__name__})"
            ) from e

        if reponse.status_code >= 400:
            raise ErreurConnecteur(
                f"Open-Meteo : HTTP {reponse.status_code} sur {self.url_prevision}"
                f"{_motif_api(reponse)} (modèle demandé : {modele})"
            )

        try:
            charge = reponse.json()
        except ValueError as e:
            if LITTERAL_NON_JSON.search(reponse.text):
                raise _hors_domaine(modele) from e
            raise ErreurConnecteur(f"Open-Meteo : réponse non-JSON sur {self.url_prevision} ({e})") from e

        blocs = _blocs(charge, self.url_prevision)
        if len(blocs) != len(points):
            raise ErreurConnecteur(
                f"Open-Meteo : {len(blocs)} bloc(s) reçu(s) pour {len(points)} point(s) demandé(s) "
                f"sur {self.url_prevision}"
            )
        return [
            self._point(bloc, demande, modele) for bloc, demande in zip(blocs, points, strict=True)
        ]

    def _point(self, bloc: Any, demande: tuple[float, float], modele: str) -> PrevisionPoint:
        if not isinstance(bloc, dict):
            raise ErreurConnecteur(
                f"Open-Meteo : bloc de prévision inattendu ({type(bloc).__name__}) sur {self.url_prevision}"
            )
        horaire = bloc.get("hourly")
        if not isinstance(horaire, dict):
            raise ErreurConnecteur(
                f"Open-Meteo : champ « hourly » absent ou inattendu sur {self.url_prevision}"
            )
        temps = horaire.get("time")
        if not isinstance(temps, list):
            raise ErreurConnecteur(
                f"Open-Meteo : champ « hourly.time » absent ou inattendu sur {self.url_prevision}"
            )

        colonnes = {nom: self._colonne(horaire, nom, len(temps)) for nom in VARIABLES_HORAIRES}
        # Repli `precipitation` → `rain` : il se décide **une fois pour la
        # série**, et seulement si le modèle ne fournit pas du tout
        # `precipitation`. Le faire valeur par valeur inventait une pluie :
        # `precipitation` à `null` à une heure donnée veut dire « le modèle ne
        # sait pas », et `rain` à 0.0 à la même heure porte sur une autre
        # variable (pluie liquide seule) ; recopier ce 0.0 affirmait « il ne
        # pleut pas » là où la réponse ne dit rien. Un `null` reste `None`.
        pluie = colonnes["precipitation" if horaire.get("precipitation") is not None else "rain"]
        heures = []
        for i, brut_t in enumerate(temps):
            heures.append(
                PrevisionHeure(
                    t=self._instant(brut_t),
                    pluie_mm=pluie[i],
                    vent_kmh=colonnes["wind_speed_10m"][i],
                    rafales_kmh=colonnes["wind_gusts_10m"][i],
                    vent_depuis_deg=colonnes["wind_direction_10m"][i],
                    ressenti_c=colonnes["apparent_temperature"][i],
                    temp_c=colonnes["temperature_2m"][i],
                )
            )
        if heures and all(_heure_vide(h) for h in heures):
            # Un point sans une seule valeur sur tout l'horizon : le modèle ne
            # couvre pas ce point. Le dire, plutôt que de propager des trous
            # qui rendraient `meilleure_direction` arbitraire.
            raise _hors_domaine(modele)
        return PrevisionPoint(
            lat=_flottant(bloc.get("latitude"), demande[0]),
            lon=_flottant(bloc.get("longitude"), demande[1]),
            heures=heures,
        )

    def _colonne(self, horaire: dict[str, Any], nom: str, attendu: int) -> list[float | None]:
        """Une variable horaire, ramenée à une liste de `float | None` de longueur `attendu`."""
        valeurs = horaire.get(nom)
        if valeurs is None:
            # Variable absente (modèle qui ne la fournit pas) : tout à None, pas une erreur.
            return [None] * attendu
        if not isinstance(valeurs, list):
            raise ErreurConnecteur(
                f"Open-Meteo : « hourly.{nom} » devrait être un tableau, reçu "
                f"{type(valeurs).__name__} sur {self.url_prevision}"
            )
        if len(valeurs) != attendu:
            raise ErreurConnecteur(
                f"Open-Meteo : « hourly.{nom} » a {len(valeurs)} valeurs pour {attendu} horodatages "
                f"sur {self.url_prevision}"
            )
        return [self._valeur(v, nom) for v in valeurs]

    def _valeur(self, v: Any, nom: str) -> float | None:
        """Une valeur horaire en `float`, ou None si elle est absente ou non finie."""
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise ErreurConnecteur(
                f"Open-Meteo : « hourly.{nom} » contient {v!r}, un nombre était attendu "
                f"sur {self.url_prevision}"
            )
        try:
            x = float(v)
        except ValueError as e:
            raise ErreurConnecteur(
                f"Open-Meteo : « hourly.{nom} » contient {v!r}, un nombre était attendu "
                f"sur {self.url_prevision}"
            ) from e
        # `NaN` majuscule (et `Infinity`) sont acceptés par le module `json` de
        # Python, qui les rend en flottants. Un NaN de pluie se propagerait
        # dans les cumuls et rendrait `meilleure_direction` arbitraire, sans
        # un message. `lecture.py:429` les écarte déjà, l'asymétrie était
        # accidentelle : ici aussi, une valeur non finie vaut « absente ».
        return x if math.isfinite(x) else None

    def _instant(self, brut: Any) -> datetime:
        """Un horodatage Open-Meteo (`2026-09-13T08:00`, en UTC car `timezone=UTC`)."""
        try:
            t = datetime.fromisoformat(str(brut))
        except (TypeError, ValueError) as e:
            raise ErreurConnecteur(
                f"Open-Meteo : horodatage illisible {brut!r} sur {self.url_prevision}"
            ) from e
        return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _heure_vide(h: PrevisionHeure) -> bool:
    """Aucune valeur du tout à cette heure-là (tout `null` côté API)."""
    return all(
        v is None
        for v in (h.pluie_mm, h.vent_kmh, h.rafales_kmh, h.vent_depuis_deg, h.ressenti_c, h.temp_c)
    )


def _hors_domaine(modele: str) -> ErreurConnecteur:
    """Le point demandé sort de la grille du modèle.

    Deux signatures, toutes deux mesurées sur le vrai service : un corps
    HTTP 200 contenant des littéraux `nan` (donc invalide en JSON), ou un
    bloc entièrement à `null`. Le message ne cite pas les coordonnées : les
    messages Open-Meteo ne doivent jamais publier le point de départ.
    """
    return ErreurConnecteur(
        f"Open-Meteo : point hors du domaine du modèle {modele}, essayer un modèle "
        f"global (par exemple --modele {MODELE_GLOBAL_SUGGERE})"
    )


def _blocs(charge: Any, url: str) -> list[Any]:
    """Normalise la réponse : une liste de blocs, que l'API en ait renvoyé un ou plusieurs."""
    if isinstance(charge, list):
        return charge
    if isinstance(charge, dict):
        if charge.get("error"):
            motif = charge.get("reason") or "sans motif"
            raise ErreurConnecteur(f"Open-Meteo a refusé la requête sur {url} : {motif}")
        return [charge]
    raise ErreurConnecteur(f"Open-Meteo : JSON inattendu ({type(charge).__name__}) sur {url}")


def _motif_api(reponse: httpx.Response) -> str:
    """Le motif renvoyé par l'API, s'il est lisible. Ne contient jamais les paramètres envoyés."""
    try:
        charge = reponse.json()
    except ValueError:
        return ""
    if isinstance(charge, dict) and charge.get("reason"):
        return f" — {charge['reason']}"
    return ""


def _flottant(x: Any, defaut: float) -> float:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return defaut

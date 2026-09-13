"""Archives météo Open-Meteo : le vent qu'il faisait, le jour de la sortie.

Sans le vent réel, calibrer un CdA revient à attribuer au cycliste ce qui
appartenait à la brise : trois mètres par seconde de face sur une sortie
plate, c'est 20 % de puissance aérodynamique en plus. C'est le seul point sur
lequel le mainteneur a demandé de ne pas transiger (« l'effort va dans ce qui
compte : CdA par vélo, vent réel, exclusion des sorties en groupe »).

L'archive du passé **ne change pas** : chaque réponse est mémoïsée dans un
SQLite dont le chemin est passé au constructeur (le cœur ne connaît aucun
chemin, règle absolue 2). Une deuxième calibration ne rappelle donc rien.

Un appel par (jour, point arrondi à `ARRONDI_DEG`). Arrondir n'est pas une
approximation gratuite : la grille de l'archive est bien plus grossière que
0,05° (le service ramène lui-même le point demandé au nœud le plus proche),
et cela transforme 137 sorties parties de la même rue en 137 clés identiques
au point près.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur

BASE_URL_DEFAUT = "https://archive-api.open-meteo.com"
CHEMIN_ARCHIVE = "/v1/archive"


#: Pas d'arrondi du point interrogé, en degrés (0,05° ≈ 5,5 km en latitude).
ARRONDI_DEG = 0.05

#: Variables horaires demandées (contrat de sprint §3).
VARIABLES_HORAIRES = (
    "wind_speed_10m",
    "wind_direction_10m",
    "temperature_2m",
    "surface_pressure",
)

DELAI_S = 60.0

VERSION_SCHEMA = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive (
    lat        REAL NOT NULL,
    lon        REAL NOT NULL,
    jour       TEXT NOT NULL,
    heures     TEXT NOT NULL,
    obtenue_le TEXT NOT NULL,
    PRIMARY KEY (lat, lon, jour)
);
"""


@dataclass(frozen=True)
class HeureArchive:
    """Une heure d'archive en un point. Toute valeur peut manquer (`null` côté API)."""

    t: datetime  # UTC
    vent_kmh: float | None
    vent_depuis_deg: float | None
    temp_c: float | None
    pression_hpa: float | None


def arrondir(valeur: float, pas: float = ARRONDI_DEG) -> float:
    """Ramène une coordonnée au multiple de `pas` le plus proche.

    L'arrondi passe par les centièmes : `round(x / 0.05) * 0.05` rendait
    `0.15000000000000002`, donc une clé de cache différente d'une exécution à
    l'autre selon le chemin de calcul.
    """
    return round(round(valeur / pas) * pas, 6)


class ClientArchive:
    """Client de l'archive Open-Meteo, mémoïsé sur disque.

    `http` est injectable (les tests ne touchent jamais le réseau) et
    `chemin_cache` est passé par l'appelant. Sans fichier de cache, le client
    mémorise quand même ce qu'il a demandé, mais seulement le temps du
    processus : c'est le fichier qui fait durer l'économie d'une exécution à
    la suivante.
    """

    def __init__(
        self,
        http: httpx.Client | None = None,
        base_url: str = BASE_URL_DEFAUT,
        chemin_cache: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http if http is not None else httpx.Client(timeout=DELAI_S)
        self.chemin_cache = Path(chemin_cache) if chemin_cache is not None else None
        self._memoire: dict[tuple[float, float, str], list[HeureArchive]] = {}
        """Mémoïsation en mémoire, doublant celle sur disque. Sans elle, une
        calibration sans fichier de cache redemandait le même jour au même
        point autant de fois qu'on le lui demandait ; et c'est elle qui tient
        quand le fichier de cache s'avère inutilisable."""
        self.appels = 0
        """Nombre d'appels HTTP réellement passés — ce qui n'a pas été trouvé
        en cache. Sert au rapport de calibration."""
        self.lectures_cache = 0
        if self.chemin_cache is not None:
            self._preparer_cache()

    @property
    def url_archive(self) -> str:
        """L'URL sans paramètres — la seule qu'on cite dans un message d'erreur."""
        return f"{self.base_url}{CHEMIN_ARCHIVE}"

    def horaires(
        self, lat: float, lon: float, jour: date, *, aujourd_hui: date | None = None
    ) -> list[HeureArchive]:
        """Les 24 heures de ce jour-là au point donné (arrondi à `ARRONDI_DEG`).

        Un jour **futur** est refusé : l'archive ne l'a pas, et demander
        quand même consommerait un appel pour rien. Une réponse vide ou
        entièrement à `null` (point hors de la grille) est rendue telle
        quelle — c'est à l'appelant de décider qu'il roulera sans vent
        plutôt que de ne pas rouler.
        """
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ErreurUtilisateur(f"archive : point ({lat}, {lon}) illisible")
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ErreurUtilisateur(
                f"archive : point ({lat}, {lon}) hors du globe — latitude dans [-90, 90], "
                "longitude dans [-180, 180]"
            )
        aujourd_hui = aujourd_hui if aujourd_hui is not None else datetime.now(UTC).date()
        if jour > aujourd_hui:
            raise ErreurUtilisateur(
                f"archive : le {jour.isoformat()} est dans le futur — "
                "l'archive météo ne connaît que le passé"
            )
        lat_a, lon_a = arrondir(lat), arrondir(lon)
        cle = (lat_a, lon_a, jour.isoformat())
        if cle in self._memoire:
            self.lectures_cache += 1
            return self._memoire[cle]
        en_cache = self._lire_cache(lat_a, lon_a, jour)
        if en_cache is not None:
            self.lectures_cache += 1
            self._memoire[cle] = en_cache
            return en_cache
        heures = self._demander(lat_a, lon_a, jour)
        self._memoire[cle] = heures
        self._ecrire_cache(lat_a, lon_a, jour, heures)
        return heures

    # --- réseau ---------------------------------------------------------------

    def _demander(self, lat: float, lon: float, jour: date) -> list[HeureArchive]:
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "start_date": jour.isoformat(),
            "end_date": jour.isoformat(),
            "hourly": ",".join(VARIABLES_HORAIRES),
            "timezone": "UTC",
        }
        self.appels += 1
        try:
            reponse = self.http.get(self.url_archive, params=params)
        except httpx.HTTPError as e:
            raise ErreurConnecteur(
                f"archive Open-Meteo injoignable sur {self.url_archive} ({type(e).__name__})"
            ) from e
        if reponse.status_code >= 400:
            raise ErreurConnecteur(
                f"archive Open-Meteo : HTTP {reponse.status_code} sur {self.url_archive}"
                f"{_motif(reponse)} (jour {jour.isoformat()})"
            )
        try:
            charge = reponse.json()
        except ValueError as e:
            raise ErreurConnecteur(
                f"archive Open-Meteo : réponse non-JSON sur {self.url_archive} ({e})"
            ) from e
        return _heures(charge, self.url_archive)

    # --- mémoïsation ----------------------------------------------------------

    def _preparer_cache(self) -> None:
        """Ouvre (ou crée) le fichier de mémoïsation. En cas d'échec, on s'en passe.

        Le fichier appartient à l'utilisateur : il peut être un reliquat d'une
        autre version, un fichier texte, un lien cassé. Refuser de calibrer
        pour autant serait absurde — la mémoïsation est une commodité, pas
        une source de vérité. On le dit sur la sortie d'erreur et on continue
        avec la seule mémoire du processus.
        """
        try:
            self.chemin_cache.parent.mkdir(parents=True, exist_ok=True)
            with self._connexion() as cx:
                cx.executescript(_SCHEMA)
                cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
        except (OSError, sqlite3.Error, ErreurUtilisateur) as e:
            print(
                f"ourouler : cache d'archive {self.chemin_cache} inutilisable ({e}) — "
                "les archives seront redemandées à chaque exécution",
                file=sys.stderr,
            )
            self.chemin_cache = None

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        """Connexion le temps d'une opération, toujours refermée.

        Même forme que `activites.cache` : une connexion SQLite laissée
        ouverte garde un verrou sur le fichier, et une calibration en ouvre
        une par sortie.
        """
        try:
            cx = sqlite3.connect(self.chemin_cache)
        except sqlite3.Error as e:
            raise ErreurUtilisateur(
                f"archive : cache {self.chemin_cache} inutilisable ({e})"
            ) from e
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    def _lire_cache(self, lat: float, lon: float, jour: date) -> list[HeureArchive] | None:
        if self.chemin_cache is None:
            return None
        try:
            with self._connexion() as cx:
                ligne = cx.execute(
                    "SELECT heures FROM archive WHERE lat = ? AND lon = ? AND jour = ?",
                    (lat, lon, jour.isoformat()),
                ).fetchone()
        except sqlite3.Error:
            # Cache abîmé : on rappelle le service plutôt que d'échouer. Le
            # cache est une commodité, pas une source de vérité.
            return None
        if ligne is None:
            return None
        try:
            brut = json.loads(ligne[0])
        except json.JSONDecodeError:
            return None
        if not isinstance(brut, list):
            return None
        return [_heure_depuis_json(h) for h in brut if isinstance(h, dict)]

    def _ecrire_cache(self, lat: float, lon: float, jour: date, heures: list[HeureArchive]) -> None:
        if self.chemin_cache is None:
            return
        charge = json.dumps([_heure_en_json(h) for h in heures], ensure_ascii=False)
        try:
            with self._connexion() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO archive (lat, lon, jour, heures, obtenue_le) "
                    "VALUES (?,?,?,?,?)",
                    (
                        lat,
                        lon,
                        jour.isoformat(),
                        charge,
                        datetime.now(UTC).isoformat(timespec="seconds"),
                    ),
                )
        except sqlite3.Error:
            return  # même raison : le cache ne doit jamais faire échouer un appel réussi


# --- lecture de la charge JSON ------------------------------------------------


def _heures(charge: Any, url: str) -> list[HeureArchive]:
    if isinstance(charge, dict) and charge.get("error"):
        motif = charge.get("reason") or "sans motif"
        raise ErreurConnecteur(f"archive Open-Meteo a refusé la requête sur {url} : {motif}")
    if not isinstance(charge, dict):
        raise ErreurConnecteur(
            f"archive Open-Meteo : JSON inattendu ({type(charge).__name__}) sur {url}"
        )
    horaire = charge.get("hourly")
    if horaire is None:
        return []
    if not isinstance(horaire, dict):
        raise ErreurConnecteur(f"archive Open-Meteo : champ « hourly » inattendu sur {url}")
    temps = horaire.get("time")
    if not isinstance(temps, list):
        return []
    colonnes = {nom: _colonne(horaire, nom, len(temps), url) for nom in VARIABLES_HORAIRES}
    heures = []
    for i, brut_t in enumerate(temps):
        instant = _instant(brut_t)
        if instant is None:
            continue
        heures.append(
            HeureArchive(
                t=instant,
                vent_kmh=colonnes["wind_speed_10m"][i],
                vent_depuis_deg=colonnes["wind_direction_10m"][i],
                temp_c=colonnes["temperature_2m"][i],
                pression_hpa=colonnes["surface_pressure"][i],
            )
        )
    return heures


def _colonne(horaire: dict[str, Any], nom: str, attendu: int, url: str) -> list[float | None]:
    """Une variable horaire ramenée à `attendu` valeurs. Variable absente = tout à None."""
    valeurs = horaire.get(nom)
    if valeurs is None:
        return [None] * attendu
    if not isinstance(valeurs, list):
        raise ErreurConnecteur(
            f"archive Open-Meteo : « hourly.{nom} » devrait être un tableau, reçu "
            f"{type(valeurs).__name__} sur {url}"
        )
    # Une colonne plus courte que `time` (réponse tronquée) est complétée par
    # des absences : mieux vaut une heure sans vent qu'une exception qui prive
    # la calibration de toute la sortie.
    valeurs = [_valeur(v) for v in valeurs[:attendu]]
    return valeurs + [None] * (attendu - len(valeurs))


def _valeur(v: Any) -> float | None:
    """Un nombre, ou None si la valeur est absente, illisible ou non finie."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _instant(brut: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(brut))
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _motif(reponse: httpx.Response) -> str:
    try:
        charge = reponse.json()
    except ValueError:
        return ""
    if isinstance(charge, dict) and charge.get("reason"):
        return f" — {charge['reason']}"
    return ""


def _heure_en_json(h: HeureArchive) -> dict:
    return {
        "t": h.t.isoformat(),
        "vent_kmh": h.vent_kmh,
        "vent_depuis_deg": h.vent_depuis_deg,
        "temp_c": h.temp_c,
        "pression_hpa": h.pression_hpa,
    }


def _heure_depuis_json(d: dict) -> HeureArchive:
    return HeureArchive(
        t=_instant(d.get("t")) or datetime(1970, 1, 1, tzinfo=UTC),
        vent_kmh=_valeur(d.get("vent_kmh")),
        vent_depuis_deg=_valeur(d.get("vent_depuis_deg")),
        temp_c=_valeur(d.get("temp_c")),
        pression_hpa=_valeur(d.get("pression_hpa")),
    )

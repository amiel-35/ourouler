"""Fabriques d'entrées hostiles pour le tracé, BRouter, le GPX et la météo le long.

Complète `outils.py` (le socle commun) avec ce dont ces tests ont besoin :

* de la **géométrie** synthétique : lignes droites, coudes, cercles — toujours
  au large du golfe de Guinée, jamais une coordonnée française (règle absolue 1
  de CLAUDE.md, vérifiée par `test_adv_invariants`) ;
* des **réponses BRouter fabriquées** : le serveur réel n'est pas joignable
  depuis les tests (règle absolue 3), et une question reste ouverte côté
  serveur — les coordonnées des `messages` sont-elles en microdegrés ou en
  degrés ? Les deux formes se fabriquent ici ;
* des **réponses Open-Meteo fabriquées**, construites à partir de la requête
  reçue (un bloc par point demandé, les heures de la fenêtre demandée) ;
* un **garde-fou de temps** (`limite_temps`) : un pas d'échantillonnage nul ou
  négatif ne doit pas figer la suite de tests.

Aucune valeur réelle n'entre ici : ni URL du serveur du mainteneur, ni mot de
passe, ni identifiant d'équipement.
"""

from __future__ import annotations

import json
import math
import signal
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ourouler.noyau.trace import PointTrace, Segment, Trace, distance_m

# --- valeurs bidon ----------------------------------------------------------

#: Faux identifiants de serveur BRouter. Ce ne sont pas ceux du mainteneur :
#: aucune URL ni aucun secret réel n'entre dans le dépôt (règle absolue 1).
URL_BROUTER = "https://brouter.exemple.invalide"
UTILISATEUR_BIDON = "utilisateur-de-test"
MOT_DE_PASSE_BIDON = "mot-de-passe-de-test-qui-ne-doit-jamais-fuiter-0123456789"

#: Point de référence des géométries : en pleine mer, au sud du golfe de Guinée.
LAT0 = 0.0011
LON0 = 0.0017

#: Mètres par degré de latitude, approximation plate suffisante à l'équateur.
METRES_PAR_DEGRE = 111_320.0


# --- garde-fou de temps -----------------------------------------------------


class TropLong(BaseException):
    """Un appel n'a pas rendu la main dans le temps imparti.

    Dérive de `BaseException` comme `ReseauInterdit` : un `except Exception`
    dans le code testé ne doit pas pouvoir transformer une boucle infinie en
    résultat plausible.
    """


@contextmanager
def limite_temps(secondes: float, quoi: str) -> Iterator[None]:
    """Interrompt le bloc au bout de `secondes` (SIGALRM, fil principal)."""

    def _sonner(_signum: int, _frame: Any) -> None:
        raise TropLong(f"{quoi} : rien rendu après {secondes} s — boucle infinie ?")

    ancien = signal.signal(signal.SIGALRM, _sonner)
    signal.setitimer(signal.ITIMER_REAL, secondes)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, ancien)


# --- géométrie --------------------------------------------------------------


def deplacer(lat: float, lon: float, cap_deg: float, distance: float) -> tuple[float, float]:
    """Point atteint en partant de (lat, lon) au cap donné sur `distance` mètres."""
    cap = math.radians(cap_deg)
    dlat = distance * math.cos(cap) / METRES_PAR_DEGRE
    dlon = distance * math.sin(cap) / (METRES_PAR_DEGRE * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def ligne(
    n: int,
    *,
    pas_m: float = 100.0,
    cap_deg: float = 0.0,
    depart: tuple[float, float] = (LAT0, LON0),
    alt: float | None = 10.0,
) -> list[tuple[float, float, float | None]]:
    """`n` points alignés, espacés de `pas_m`, au cap donné."""
    lat, lon = depart
    points = [(lat, lon, alt)]
    for _ in range(n - 1):
        lat, lon = deplacer(lat, lon, cap_deg, pas_m)
        points.append((lat, lon, alt))
    return points


def coude(
    *,
    cap_avant: float,
    cap_apres: float,
    pas_m: float = 100.0,
    n: int = 5,
    depart: tuple[float, float] = (LAT0, LON0),
) -> list[tuple[float, float, float | None]]:
    """Deux branches droites se rejoignant sur un virage unique et net."""
    avant = ligne(n, pas_m=pas_m, cap_deg=cap_avant, depart=depart)
    lat, lon, _ = avant[-1]
    apres = ligne(n, pas_m=pas_m, cap_deg=cap_apres, depart=(lat, lon))
    return avant + apres[1:]


def cercle(
    n: int = 24,
    *,
    rayon_m: float = 1500.0,
    sens: str = "horaire",
    centre: tuple[float, float] = (LAT0, LON0),
    alt: float | None = 10.0,
) -> list[tuple[float, float, float | None]]:
    """Boucle fermée de `n` côtés, parcourue dans le sens demandé.

    x vers l'est, y vers le nord : partir du nord en allant vers l'est décrit
    un cercle horaire (aire signée négative, convention de `trace.sens_boucle`).
    """
    lat0, lon0 = centre
    signe = 1.0 if sens == "horaire" else -1.0
    points = []
    for i in range(n + 1):  # le dernier point referme la boucle
        angle = signe * 2.0 * math.pi * i / n
        lat = lat0 + rayon_m * math.cos(angle) / METRES_PAR_DEGRE
        lon = lon0 + rayon_m * math.sin(angle) / (METRES_PAR_DEGRE * math.cos(math.radians(lat0)))
        points.append((lat, lon, alt))
    return points


# --- traces -----------------------------------------------------------------


def points_trace(coords: Sequence[tuple[float, float, float | None]]) -> list[PointTrace]:
    """Des `PointTrace` avec la distance cumulée calculée par le module testé."""
    points: list[PointTrace] = []
    cumul = 0.0
    for lat, lon, alt in coords:
        point = PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=cumul)
        if points:
            cumul += distance_m(points[-1], point)
            point = PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=cumul)
        points.append(point)
    return points


def trace_fictive(
    coords: Sequence[tuple[float, float, float | None]],
    *,
    tags: Sequence[dict[str, str]] | None = None,
    nom: str = "trace de test",
    denivele_m: float | None = 0.0,
    temps_moteur_s: float | None = None,
    meta: dict | None = None,
) -> Trace:
    """Une `Trace` cohérente. `tags` (un par tronçon) engendre les `Segment`."""
    points = points_trace(coords)
    segments: list[Segment] = []
    if tags is not None:
        assert len(tags) == max(len(points) - 1, 0), "un jeu de tags par tronçon attendu"
        for i, jeu in enumerate(tags):
            segments.append(
                Segment(
                    debut_idx=i,
                    fin_idx=i + 1,
                    longueur_m=points[i + 1].dist_m - points[i].dist_m,
                    tags=dict(jeu),
                )
            )
    return Trace(
        nom=nom,
        points=points,
        segments=segments,
        distance_m=points[-1].dist_m if points else 0.0,
        denivele_m=denivele_m,
        temps_moteur_s=temps_moteur_s,
        meta=meta if meta is not None else {},
    )


def verifier_trace(trace: Any, *, quoi: str, distance_max_km: float = 1000.0) -> None:
    """Invariants d'un `Trace`, quelle que soit sa provenance.

    Le garde-fou principal est l'**aberration** : BRouter ne dit pas toujours
    si ses coordonnées sont en microdegrés, et une lecture qui se trompe
    d'unité fabrique une trace de plusieurs milliers de kilomètres — ou des
    points hors du globe — sans rien signaler.
    """
    assert isinstance(trace.points, list), f"{quoi} : points doit être une liste"
    assert isinstance(trace.segments, list), f"{quoi} : segments doit être une liste"
    assert isinstance(trace.nom, str), f"{quoi} : nom doit être une chaîne"
    for nom_champ in ("distance_m", "denivele_m", "temps_moteur_s"):
        valeur = getattr(trace, nom_champ)
        if valeur is not None:
            assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
                f"{quoi} : {nom_champ} doit être un nombre ou None, reçu {valeur!r}"
            )
            assert math.isfinite(valeur), f"{quoi} : {nom_champ} non fini ({valeur!r})"
    assert trace.distance_m is None or trace.distance_m >= 0, f"{quoi} : distance négative"
    assert isinstance(trace.meta, dict), f"{quoi} : meta doit être un dict"
    json.dumps(trace.meta, ensure_ascii=False)  # meta doit rester sérialisable

    precedent: PointTrace | None = None
    cumul = 0.0
    for i, p in enumerate(trace.points):
        assert -90.0 <= p.lat <= 90.0, f"{quoi} : points[{i}].lat = {p.lat} hors du globe"
        assert -180.0 <= p.lon <= 180.0, f"{quoi} : points[{i}].lon = {p.lon} hors du globe"
        assert math.isfinite(p.dist_m), f"{quoi} : points[{i}].dist_m non fini"
        if precedent is not None:
            saut = distance_m(precedent, p)
            assert saut < 50_000.0, (
                f"{quoi} : {saut / 1000:.0f} km entre les points {i - 1} et {i} — "
                "unité de coordonnées mal lue ?"
            )
            cumul += saut
            assert p.dist_m >= precedent.dist_m - 1.0, (
                f"{quoi} : points[{i}].dist_m recule ({precedent.dist_m} → {p.dist_m})"
            )
        precedent = p
    assert cumul <= distance_max_km * 1000.0, (
        f"{quoi} : trace de {cumul / 1000:.0f} km là où on en attendait moins de "
        f"{distance_max_km:.0f} — coordonnées lues dans la mauvaise unité ?"
    )
    if trace.points and trace.distance_m:
        assert trace.distance_m <= distance_max_km * 1000.0, (
            f"{quoi} : distance_m = {trace.distance_m / 1000:.0f} km, aberrant"
        )

    for i, s in enumerate(trace.segments):
        assert 0 <= s.debut_idx < len(trace.points), f"{quoi} : segments[{i}].debut_idx hors bornes"
        assert 0 <= s.fin_idx < len(trace.points), f"{quoi} : segments[{i}].fin_idx hors bornes"
        assert s.debut_idx <= s.fin_idx, f"{quoi} : segments[{i}] à l'envers"
        assert s.longueur_m >= 0, f"{quoi} : segments[{i}].longueur_m négative"
        assert isinstance(s.tags, dict), f"{quoi} : segments[{i}].tags doit être un dict"
        for cle, valeur in s.tags.items():
            assert isinstance(cle, str) and isinstance(valeur, str), (
                f"{quoi} : segments[{i}].tags contient {cle!r}: {valeur!r}, des chaînes OSM étaient attendues"
            )


# --- réponses BRouter fabriquées --------------------------------------------

ENTETE_MESSAGES = [
    "Longitude",
    "Latitude",
    "Elevation",
    "Distance",
    "CostPerKm",
    "ElevCost",
    "TurnCost",
    "NodeCost",
    "InitialCost",
    "WayTags",
    "NodeTags",
    "Time",
    "Energy",
]


def _way_tags(tags: dict[str, str]) -> str:
    return " ".join(f"{cle}={valeur}" for cle, valeur in tags.items())


def geojson_brouter(
    coords: Sequence[tuple[float, float, float | None]],
    *,
    tags: Sequence[dict[str, str]] | None = None,
    microdegres: bool = True,
    entete: bool = True,
    messages: bool = True,
    pas_messages: int = 1,
    track_length: float | None = None,
    total_time: float | None = 1800.0,
    ascend: float | None = 120.0,
    nom: str = "brouter_test_0",
) -> dict:
    """Une réponse GeoJSON BRouter fabriquée, au format que le serveur rend.

    `coords` est en (lat, lon, alt) côté Python ; la géométrie sort bien en
    `[lon, lat, alt]`. Les `messages` décrivent chacun le tronçon **se
    terminant** au point cité, en microdegrés entiers ou en degrés selon
    `microdegres` : le contrat laisse la question ouverte, le lecteur doit
    gérer l'une ou l'autre forme sans fabriquer une trace aberrante.
    """
    points = points_trace(coords)
    longueur = track_length if track_length is not None else (points[-1].dist_m if points else 0.0)
    # Un message par point, ou un point sur `pas_messages` : BRouter ne décrit
    # que les **fins** de tronçon, la géométrie est bien plus dense que les
    # messages dès que la route est sinueuse.
    fins = list(range(pas_messages, len(coords), pas_messages))
    if fins and fins[-1] != len(coords) - 1:
        fins.append(len(coords) - 1)
    if tags is not None:
        jeux = list(tags)
    else:
        jeux = [{"highway": "tertiary", "surface": "asphalt"}] * len(fins)
    assert len(jeux) == len(fins), f"{len(jeux)} jeux de tags pour {len(fins)} tronçons"
    lignes: list[list[str]] = [list(ENTETE_MESSAGES)] if entete else []
    debut = 0
    for jeu, fin in zip(jeux, fins, strict=True):
        lat, lon, alt = coords[fin]
        if microdegres:
            x, y = str(round(lon * 1_000_000)), str(round(lat * 1_000_000))
        else:
            x, y = f"{lon:.7f}", f"{lat:.7f}"
        troncon = points[fin].dist_m - points[debut].dist_m
        debut = fin
        lignes.append(
            [
                x,
                y,
                str(int(alt or 0)),
                str(round(troncon)),
                "80",
                "0",
                "0",
                "0",
                "0",
                _way_tags(jeu),
                "",
                "60",
                "10",
            ]
        )
    proprietes: dict[str, Any] = {
        "creator": "BRouter-fabrique-de-test",
        "name": nom,
        "track-length": f"{longueur:.0f}",
        "filtered ascend": None if ascend is None else f"{ascend:.0f}",
        "total-time": None if total_time is None else f"{total_time:.0f}",
    }
    proprietes = {k: v for k, v in proprietes.items() if v is not None}
    if messages:
        proprietes["messages"] = lignes
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": proprietes,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [lon, lat] if alt is None else [lon, lat, alt] for lat, lon, alt in coords
                    ],
                },
            }
        ],
    }


class EspionHttp:
    """Transport bouchon qui retient les requêtes et délègue la réponse."""

    def __init__(self, reponse):
        self.requetes: list[httpx.Request] = []
        self._reponse = reponse

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        return self._reponse(requete) if callable(self._reponse) else self._reponse

    @property
    def chemins(self) -> list[str]:
        return [r.url.path for r in self.requetes]

    def params(self, i: int = 0) -> dict[str, str]:
        return dict(self.requetes[i].url.params)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


# --- réponses Open-Meteo fabriquées -----------------------------------------


def _heures_demandees(params: dict[str, str]) -> list[datetime]:
    debut = datetime.fromisoformat(params["start_hour"]).replace(tzinfo=UTC)
    fin = datetime.fromisoformat(params["end_hour"]).replace(tzinfo=UTC)
    heures = []
    courante = debut
    while courante <= fin and len(heures) < 400:
        heures.append(courante)
        courante += timedelta(hours=1)
    return heures or [debut]


def repondre_openmeteo(
    requete: httpx.Request,
    *,
    pluie: Any = 0.0,
    vent_kmh: Any = 12.0,
    vent_depuis_deg: Any = 0.0,
    ressenti_c: Any = 14.0,
    temp_c: Any = 15.0,
    heures_max: int | None = None,
) -> httpx.Response:
    """Une réponse Open-Meteo fabriquée, calée sur la requête reçue.

    Chaque valeur peut être un scalaire, `None` (le modèle ne sait pas) ou une
    fonction `(indice_point, indice_heure) -> valeur`.
    """
    params = dict(requete.url.params)
    points = params.get("latitude", "").split(",")
    heures = _heures_demandees(params)
    if heures_max is not None:
        heures = heures[:heures_max]

    def colonne(valeur: Any, ip: int) -> list[Any]:
        if callable(valeur):
            return [valeur(ip, ih) for ih in range(len(heures))]
        return [valeur] * len(heures)

    blocs = []
    for ip, _ in enumerate(points):
        blocs.append(
            {
                "latitude": float(params["latitude"].split(",")[ip]),
                "longitude": float(params["longitude"].split(",")[ip]),
                "hourly": {
                    "time": [h.strftime("%Y-%m-%dT%H:%M") for h in heures],
                    "precipitation": colonne(pluie, ip),
                    "rain": colonne(pluie, ip),
                    "wind_speed_10m": colonne(vent_kmh, ip),
                    "wind_direction_10m": colonne(vent_depuis_deg, ip),
                    "wind_gusts_10m": colonne(vent_kmh, ip),
                    "apparent_temperature": colonne(ressenti_c, ip),
                    "temperature_2m": colonne(temp_c, ip),
                },
            }
        )
    return httpx.Response(200, json=blocs if len(blocs) != 1 else blocs[0])

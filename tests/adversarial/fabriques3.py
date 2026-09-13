"""Fabriques d'entrées hostiles pour le sprint 3 (antennes, routes, physique, archive).

Complète `fabriques.py` (sprint 2) avec ce dont les lots L3.1 à L3.3 ont besoin :

* des **géométries à antenne** : une boucle fermée dans laquelle on greffe un
  aller-retour exact, bruité, ou trop long pour la fenêtre — c'est le seul
  défaut de tracé que le mainteneur veut voir corrigé (contrat §1) ;
* des **activités synthétiques** dont on connaît la vitesse point par point :
  sans elles, `detecter_groupe` ne se teste que par ses bornes, jamais par son
  verdict (contrat §3) ;
* des **réponses d'archive météo fabriquées**, avec heures manquantes, valeurs
  `null` ou colonnes plus courtes que `time` — le cas que le contrat §4 cite
  nommément ;
* un **constructeur tolérant de `Parametres`** : le contrat fixe les champs du
  modèle physique mais pas leur ordre ni leurs valeurs par défaut.

Comme au sprint 2 : aucune coordonnée française, aucune URL réelle, aucun
identifiant du mainteneur (règle absolue 1 de CLAUDE.md).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import fabriques
import httpx
import outils

from ourouler.activites.modele import Activite, Point

#: Faux serveur d'archive météo. Le vrai (`archive-api.open-meteo.com`) n'est
#: jamais joignable depuis les tests (règle absolue 3).
URL_ARCHIVE = "https://archive.exemple.invalide"

#: Jour de référence des tests d'archive : passé, postérieur à 1940, fixe.
JOUR_ARCHIVE = datetime(2024, 5, 14, tzinfo=UTC).date()

VARIABLES_ARCHIVE = (
    "wind_speed_10m",
    "wind_direction_10m",
    "temperature_2m",
    "surface_pressure",
    "pressure_msl",
)


# --- géométries à antenne ---------------------------------------------------


def greffer_antenne(
    coords: list[tuple[float, float, float | None]],
    *,
    position: int,
    aller_m: float = 200.0,
    n_aller: int = 4,
    cap_deg: float = 45.0,
    bruit_m: float = 0.0,
) -> tuple[list[tuple[float, float, float | None]], int, int]:
    """Insère un aller-retour au point `position` de `coords`.

    Renvoie `(coords, debut, fin)` où `debut` et `fin` sont les indices, dans
    la nouvelle liste, du point de greffe et de son retour : entre les deux se
    trouve exactement l'aller-retour, et rien d'autre.

    `bruit_m` décale latéralement chaque point du retour : c'est l'antenne
    « quasi exacte » du contrat §4, celle qu'un moteur de tracé rend vraiment
    (le retour emprunte le même axe, pas les mêmes nœuds).
    """
    assert 0 <= position < len(coords), f"position {position} hors de la trace"
    assert n_aller >= 1, "au moins un point d'aller"
    lat, lon, alt = coords[position]
    pas = aller_m / n_aller

    aller: list[tuple[float, float, float | None]] = []
    courant = (lat, lon)
    for _ in range(n_aller):
        courant = fabriques.deplacer(courant[0], courant[1], cap_deg, pas)
        aller.append((courant[0], courant[1], alt))

    retour: list[tuple[float, float, float | None]] = []
    for plat, plon, palt in reversed(aller[:-1]):
        if bruit_m:
            plat, plon = fabriques.deplacer(plat, plon, cap_deg + 90.0, bruit_m)
        retour.append((plat, plon, palt))
    retour.append(coords[position])

    nouvelles = coords[: position + 1] + aller + retour + coords[position + 1 :]
    return nouvelles, position, position + len(aller) + len(retour)


def boucle_avec_antenne(
    *,
    aller_m: float = 200.0,
    n_aller: int = 4,
    bruit_m: float = 0.0,
    position: int = 6,
    n_cercle: int = 24,
    rayon_m: float = 1500.0,
    tags: dict[str, str] | None = None,
) -> tuple[Any, int, int]:
    """Une boucle fermée portant une antenne unique. Renvoie `(trace, debut, fin)`."""
    coords = fabriques.cercle(n=n_cercle, rayon_m=rayon_m)
    coords, debut, fin = greffer_antenne(
        coords, position=position, aller_m=aller_m, n_aller=n_aller, bruit_m=bruit_m
    )
    jeu = tags if tags is not None else {"highway": "tertiary", "surface": "asphalt"}
    trace = fabriques.trace_fictive(coords, tags=[dict(jeu)] * (len(coords) - 1))
    return trace, debut, fin


def longueur_entre(trace: Any, debut: int, fin: int) -> float:
    """Longueur réelle du tronçon `[debut, fin]`, calculée comme le module testé."""
    return trace.points[fin].dist_m - trace.points[debut].dist_m


def copie_lisible(trace: Any) -> list[tuple[float, float, float | None, float]]:
    """Instantané comparable d'une trace : `elaguer` ne doit pas toucher l'entrée."""
    return [(p.lat, p.lon, p.alt_m, p.dist_m) for p in trace.points]


# --- activités synthétiques -------------------------------------------------

DEBUT_ACTIVITE = datetime(2024, 5, 14, 8, 0, tzinfo=UTC)


def activite_fictive(
    *,
    vitesses_ms: Sequence[float] | float = 8.0,
    n_points: int = 200,
    pas_m: float = 200.0,
    pente: float = 0.0,
    puissance_w: Sequence[float] | float | None = 200.0,
    cap_deg: float = 90.0,
    alt0: float = 40.0,
    temp_c: float | None = 15.0,
    depart: tuple[float, float] = (fabriques.LAT0, fabriques.LON0),
    debut: datetime = DEBUT_ACTIVITE,
    sport: str | None = "Ride",
    nom: str | None = None,
    avec_gps: bool = True,
) -> Activite:
    """Une `Activite` dont on connaît la vitesse et la puissance point par point.

    Les points sont espacés de `pas_m` mètres le long d'une droite : la pente
    est donc exactement `pente` partout, et le temps entre deux points vaut
    `pas_m / v`. C'est ce qui permet de comparer un temps simulé à un temps
    « réel » sans rien supposer de l'échantillonnage.
    """
    n = int(n_points)
    assert n >= 1, "au moins un point"

    def _serie(valeur: Any, defaut: float | None) -> list[float | None]:
        if valeur is None:
            return [defaut] * n
        if callable(valeur):
            return [float(valeur(i)) for i in range(n)]
        if isinstance(valeur, (int, float)):
            return [float(valeur)] * n
        suite = list(valeur)
        assert len(suite) == n, f"{len(suite)} valeurs pour {n} points"
        return [None if v is None else float(v) for v in suite]

    vitesses = _serie(vitesses_ms, 8.0)
    puissances = _serie(puissance_w, None)

    lat, lon = depart
    t = debut
    alt = alt0
    points: list[Point] = []
    distance = 0.0
    for i in range(n):
        points.append(
            Point(
                t=t,
                lat=lat if avec_gps else None,
                lon=lon if avec_gps else None,
                alt_m=alt if avec_gps else None,
                dist_m=distance,
                vitesse_ms=vitesses[i],
                puissance_w=puissances[i],
                cadence_rpm=85.0,
                fc_bpm=140.0,
                temp_c=temp_c,
            )
        )
        if i == n - 1:
            break
        v = vitesses[i + 1] or vitesses[i] or 1.0
        t = t + timedelta(seconds=pas_m / max(v, 0.1))
        lat, lon = fabriques.deplacer(lat, lon, cap_deg, pas_m)
        alt += pente * pas_m
        distance += pas_m

    duree = (points[-1].t - points[0].t).total_seconds()
    connues = [p for p in puissances if p is not None]
    meta: dict[str, Any] = {"sport": sport}
    if nom is not None:
        meta["nom"] = nom
        meta["name"] = nom
    return Activite(
        source="gpx",
        fichier=None,
        debut=points[0].t,
        duree_s=duree,
        duree_mouvement_s=duree,
        distance_m=distance,
        denivele_m=max(0.0, pente) * distance,
        puissance_moy_w=(sum(connues) / len(connues)) if connues else None,
        puissance_np_w=None,
        sport=sport,
        appareil="appareil de test",
        points=points,
        meta=meta,
    )


# --- réponses d'archive météo fabriquées ------------------------------------


def _jour_demande(params: dict[str, str]):
    for cle in ("start_date", "end_date", "date"):
        if params.get(cle):
            return datetime.fromisoformat(params[cle][:10]).date()
    for cle in ("start_hour", "end_hour"):
        if params.get(cle):
            return datetime.fromisoformat(params[cle][:10]).date()
    return JOUR_ARCHIVE


def repondre_archive(
    requete: httpx.Request,
    *,
    vent_kmh: Any = 18.0,
    vent_depuis_deg: Any = 230.0,
    temp_c: Any = 16.0,
    pression_hpa: Any = 1013.0,
    heures: int = 24,
    colonnes_courtes: int | None = None,
    sans: Sequence[str] = (),
    hourly: Any = ...,
) -> httpx.Response:
    """Une réponse d'archive fabriquée, calée sur le jour demandé.

    `colonnes_courtes` tronque **toutes** les colonnes sauf `time` : c'est
    l'« heures manquantes » du contrat §4, celle qui fabrique un `IndexError`
    chez un lecteur qui zippe à l'aveugle. `sans` retire des variables
    entières, `hourly` remplace le bloc (pour `{}`, `None`, une liste…).
    """
    params = dict(requete.url.params)
    jour = _jour_demande(params)
    base = datetime(jour.year, jour.month, jour.day, tzinfo=UTC)
    instants = [base + timedelta(hours=i) for i in range(heures)]

    def colonne(valeur: Any) -> list[Any]:
        suite = [valeur(i) for i in range(heures)] if callable(valeur) else [valeur] * heures
        if colonnes_courtes is not None:
            return suite[:colonnes_courtes]
        return suite

    bloc: dict[str, Any] = {"time": [h.strftime("%Y-%m-%dT%H:%M") for h in instants]}
    valeurs = {
        "wind_speed_10m": vent_kmh,
        "wind_direction_10m": vent_depuis_deg,
        "temperature_2m": temp_c,
        "surface_pressure": pression_hpa,
        "pressure_msl": pression_hpa,
    }
    for nom, valeur in valeurs.items():
        if nom not in sans:
            bloc[nom] = colonne(valeur)

    charge: dict[str, Any] = {
        "latitude": float(params.get("latitude", "0") or 0),
        "longitude": float(params.get("longitude", "0") or 0),
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "hourly_units": {"wind_speed_10m": "km/h", "temperature_2m": "°C"},
        "hourly": bloc if hourly is ... else hourly,
    }
    return httpx.Response(200, json=charge)


# --- dataclasses du contrat dont l'ordre n'est pas fixé ---------------------

CHAMPS_PARAMETRES = {"masse_totale_kg", "cda_m2", "crr"}


def parametres(module: Any, **surcharges: Any) -> Any:
    """Un `Parametres` du contrat §3, construit sans supposer l'ordre des champs."""
    outils.exiger_champs(module.Parametres, CHAMPS_PARAMETRES)
    valeurs: dict[str, Any] = {"masse_totale_kg": 85.0, "cda_m2": 0.32, "crr": 0.005}
    valeurs.update(surcharges)
    return outils.fabriquer(module.Parametres, valeurs)


def valeurs_numeriques(objet: Any) -> dict[str, float]:
    """Tous les attributs numériques publics d'un objet, à plat (hors booléens)."""
    trouvees: dict[str, float] = {}
    for nom in dir(objet):
        if nom.startswith("_"):
            continue
        try:
            valeur = getattr(objet, nom)
        except Exception:  # noqa: BLE001 — une propriété qui lève est signalée ailleurs
            continue
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            trouvees[nom] = float(valeur)
    return trouvees


def tout_fini(objet: Any, quoi: str) -> None:
    """Aucun NaN ni infini dans les nombres publics d'un résultat."""
    for nom, valeur in valeurs_numeriques(objet).items():
        assert not math.isnan(valeur), f"{quoi} : {nom} vaut NaN (moyenne sur zéro élément ?)"
        assert math.isfinite(valeur), f"{quoi} : {nom} est infini ({valeur})"

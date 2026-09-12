"""Lecteur unique : un FIT, un GPX ou un TCX entre, une `Activite` sort.

Un fichier sans GPS ou sans puissance est valide : les champs concernés
valent None. Un fichier vide, tronqué, d'extension inconnue, mal formé ou
sans le moindre enregistrement lève `ErreurLecture`.

Ce module ne lit jamais la configuration, l'environnement ni un chemin
utilisateur : il reçoit un chemin ou des octets.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import fitdecode
import gpxpy
import gpxpy.gpx

from ourouler.activites.modele import (
    Activite,
    Point,
    denivele_positif,
    puissance_moyenne,
    puissance_normalisee,
)
from ourouler.erreurs import ErreurLecture

#: Extensions reconnues, en minuscules et sans le point.
EXTENSIONS = ("fit", "gpx", "tcx")

#: Conversion des semicercles FIT en degrés.
_DEGRES_PAR_SEMICERCLE = 180.0 / 2**31

Entree = Path | str | bytes | bytearray


def lire(chemin: Path | str) -> Activite:
    """Lit un fichier d'activité, lecteur choisi par extension (insensible à la casse)."""
    chemin = Path(chemin)
    extension = chemin.suffix.lower().lstrip(".")
    lecteur = LECTEURS.get(extension)
    if lecteur is None:
        raise ErreurLecture(
            f"{chemin} : extension « {chemin.suffix or '(aucune)'} » inconnue "
            f"(attendu {', '.join('.' + e for e in EXTENSIONS)})"
        )
    return lecteur(chemin)


def lecteur_pour(extension: str) -> Callable[[Entree], Activite]:
    """Lecteur correspondant à une extension (avec ou sans point, toute casse)."""
    extension = extension.lower().lstrip(".")
    lecteur = LECTEURS.get(extension)
    if lecteur is None:
        raise ErreurLecture(
            f"extension « {extension} » inconnue (attendu {', '.join(EXTENSIONS)})"
        )
    return lecteur


# --- FIT ----------------------------------------------------------------------


def lire_fit(source: Entree) -> Activite:
    contenu, fichier = _octets(source)
    points: list[Point] = []
    avertissements: list[str] = []
    sport: str | None = None
    appareil: str | None = None
    duree_mouvement_s: float | None = None
    distance_m: float | None = None
    meta: dict = {}

    try:
        with fitdecode.FitReader(io.BytesIO(contenu)) as fit:
            for trame in fit:
                if trame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                if trame.name == "record":
                    point = _point_fit(trame)
                    if point is not None:
                        points.append(point)
                elif trame.name == "session":
                    sport = sport or _sport_fit(trame)
                    duree_mouvement_s = _flottant(_champ(trame, "total_timer_time"))
                    distance_m = _flottant(_champ(trame, "total_distance"))
                elif trame.name == "sport":
                    sport = sport or _sport_fit(trame)
                elif trame.name == "file_id":
                    appareil = _appareil_fit(trame)
                elif trame.name == "device_info" and appareil is None:
                    appareil = _texte(_champ(trame, "product_name"))
    except fitdecode.FitError as e:
        raise ErreurLecture(f"{fichier or '<octets>'} : FIT illisible ({e})") from e

    if not points:
        raise ErreurLecture(f"{fichier or '<octets>'} : FIT sans enregistrement exploitable")
    if distance_m is None:
        distance_m = _derniere_distance(points)
    return _assembler(
        "fit",
        fichier,
        points,
        avertissements=avertissements,
        sport=sport,
        appareil=appareil,
        duree_mouvement_s=duree_mouvement_s,
        distance_m=distance_m,
        meta=meta,
    )


def _point_fit(trame) -> Point | None:
    t = _instant(_champ(trame, "timestamp"))
    if t is None:
        return None
    lat = _champ(trame, "position_lat")
    lon = _champ(trame, "position_long")
    return Point(
        t=t,
        lat=lat * _DEGRES_PAR_SEMICERCLE if isinstance(lat, int | float) else None,
        lon=lon * _DEGRES_PAR_SEMICERCLE if isinstance(lon, int | float) else None,
        alt_m=_flottant(_champ(trame, "enhanced_altitude", "altitude")),
        dist_m=_flottant(_champ(trame, "distance")),
        vitesse_ms=_flottant(_champ(trame, "enhanced_speed", "speed")),
        puissance_w=_flottant(_champ(trame, "power")),
        cadence_rpm=_flottant(_champ(trame, "cadence")),
        fc_bpm=_flottant(_champ(trame, "heart_rate")),
        temp_c=_flottant(_champ(trame, "temperature")),
    )


def _champ(trame, *noms: str):
    for nom in noms:
        if trame.has_field(nom):
            valeur = trame.get_value(nom, fallback=None)
            if valeur is not None:
                return valeur
    return None


def _sport_fit(trame) -> str | None:
    """« cycling », ou « cycling/indoor_cycling » quand le sous-sport est significatif.

    Le sous-sport est la seule chose qui, dans un FIT, distingue une sortie
    d'un home-trainer : on le garde, tel que la source le nomme.
    """
    sport = _texte(_champ(trame, "sport"))
    sous_sport = _texte(_champ(trame, "sub_sport"))
    if sous_sport and sous_sport not in ("generic", "all", "255"):
        return f"{sport or '?'}/{sous_sport}"
    return sport


def _appareil_fit(trame) -> str | None:
    morceaux = [
        _texte(_champ(trame, "manufacturer")),
        _texte(_champ(trame, "garmin_product", "product_name", "product")),
    ]
    presents = [m for m in morceaux if m and m not in ("0", "None")]
    return " ".join(presents) or None


# --- GPX ----------------------------------------------------------------------

#: Noms de balises d'extension GPX reconnus, en minuscules, sans espace de noms.
_EXTENSIONS_GPX = {
    "hr": "fc_bpm",
    "heartrate": "fc_bpm",
    "cad": "cadence_rpm",
    "cadence": "cadence_rpm",
    "atemp": "temp_c",
    "temp": "temp_c",
    "temperature": "temp_c",
    "power": "puissance_w",
    "powerinwatts": "puissance_w",
    "watts": "puissance_w",
    "speed": "vitesse_ms",
}


def lire_gpx(source: Entree) -> Activite:
    contenu, fichier = _octets(source)
    try:
        gpx = gpxpy.parse(contenu.decode("utf-8", errors="replace"))
    except Exception as e:  # gpxpy lève GPXException, mais aussi des erreurs XML brutes
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX illisible ({e})") from e

    avertissements: list[str] = []
    points: list[Point] = []
    cumul = 0.0
    precedent = None
    sans_horodatage = 0
    for trace in gpx.tracks:
        for segment in trace.segments:
            for brut in segment.points:
                t = _instant(brut.time)
                if t is None:
                    sans_horodatage += 1
                    continue
                if precedent is not None:
                    cumul += brut.distance_2d(precedent) or 0.0
                precedent = brut
                point = Point(
                    t=t,
                    lat=_flottant(brut.latitude),
                    lon=_flottant(brut.longitude),
                    alt_m=_flottant(brut.elevation),
                    dist_m=round(cumul, 2),
                )
                _appliquer_extensions_gpx(point, brut.extensions)
                points.append(point)
    if not points:
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX sans point horodaté")
    if sans_horodatage:
        avertissements.append(f"{sans_horodatage} point(s) GPX sans horodatage, ignorés")

    trace = gpx.tracks[0] if gpx.tracks else None
    return _assembler(
        "gpx",
        fichier,
        points,
        avertissements=avertissements,
        sport=getattr(trace, "type", None) or None,
        appareil=gpx.creator or None,
        duree_mouvement_s=None,  # le GPX ne distingue pas temps écoulé et temps de mouvement
        distance_m=_derniere_distance(points),
        meta={"nom": getattr(trace, "name", None)} if trace else {},
    )


def _appliquer_extensions_gpx(point: Point, extensions) -> None:
    for element in _descendants(extensions or []):
        nom = _sans_espace_de_noms(element.tag).lower()
        champ = _EXTENSIONS_GPX.get(nom)
        if champ is None or getattr(point, champ) is not None:
            continue
        valeur = _flottant((element.text or "").strip())
        if valeur is not None:
            setattr(point, champ, valeur)


def _descendants(elements) -> Iterator:
    for element in elements:
        yield element
        yield from _descendants(list(element))


# --- TCX ----------------------------------------------------------------------

_NS_TCX = "{http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2}"


def lire_tcx(source: Entree) -> Activite:
    contenu, fichier = _octets(source)
    if not contenu.strip():
        raise ErreurLecture(f"{fichier or '<octets>'} : fichier vide")
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as e:
        raise ErreurLecture(f"{fichier or '<octets>'} : TCX illisible ({e})") from e

    activite = _premier(racine, f"{_NS_TCX}Activities/{_NS_TCX}Activity")
    if activite is None:
        activite = racine
    points: list[Point] = []
    distance_m: float | None = None
    for trackpoint in activite.iter(f"{_NS_TCX}Trackpoint"):
        point = _point_tcx(trackpoint)
        if point is not None:
            points.append(point)
            if point.dist_m is not None:
                distance_m = point.dist_m
    if not points:
        raise ErreurLecture(f"{fichier or '<octets>'} : TCX sans point horodaté")

    sport = activite.get("Sport") or None
    appareil = _texte_balise(activite, f"{_NS_TCX}Creator/{_NS_TCX}Name")
    meta = {"identifiant_source": _texte_balise(activite, f"{_NS_TCX}Id")}
    return _assembler(
        "tcx",
        fichier,
        points,
        avertissements=[],
        sport=sport,
        appareil=appareil,
        duree_mouvement_s=None,  # TotalTimeSeconds est un temps écoulé de tour, pas du mouvement
        distance_m=distance_m if distance_m is not None else _derniere_distance(points),
        meta=meta,
    )


def _point_tcx(trackpoint: ET.Element) -> Point | None:
    t = _instant(_texte_balise(trackpoint, f"{_NS_TCX}Time"))
    if t is None:
        return None
    point = Point(
        t=t,
        lat=_flottant(_texte_balise(trackpoint, f"{_NS_TCX}Position/{_NS_TCX}LatitudeDegrees")),
        lon=_flottant(_texte_balise(trackpoint, f"{_NS_TCX}Position/{_NS_TCX}LongitudeDegrees")),
        alt_m=_flottant(_texte_balise(trackpoint, f"{_NS_TCX}AltitudeMeters")),
        dist_m=_flottant(_texte_balise(trackpoint, f"{_NS_TCX}DistanceMeters")),
        cadence_rpm=_flottant(_texte_balise(trackpoint, f"{_NS_TCX}Cadence")),
        fc_bpm=_flottant(
            _texte_balise(trackpoint, f"{_NS_TCX}HeartRateBpm/{_NS_TCX}Value")
        ),
    )
    # Les extensions Garmin (TPX) portent la puissance et la vitesse.
    for element in trackpoint.iter():
        nom = _sans_espace_de_noms(element.tag)
        if nom == "Watts" and point.puissance_w is None:
            point.puissance_w = _flottant((element.text or "").strip())
        elif nom == "Speed" and point.vitesse_ms is None:
            point.vitesse_ms = _flottant((element.text or "").strip())
    return point


def _premier(element: ET.Element, chemin: str) -> ET.Element | None:
    return element.find(chemin)


def _texte_balise(element: ET.Element, chemin: str) -> str | None:
    trouve = element.find(chemin)
    if trouve is None or trouve.text is None:
        return None
    return trouve.text.strip() or None


# --- assemblage commun --------------------------------------------------------

LECTEURS: dict[str, Callable[[Entree], Activite]] = {
    "fit": lire_fit,
    "gpx": lire_gpx,
    "tcx": lire_tcx,
}


def _assembler(
    source: str,
    fichier: str | None,
    points: list[Point],
    *,
    avertissements: list[str],
    sport: str | None,
    appareil: str | None,
    duree_mouvement_s: float | None,
    distance_m: float | None,
    meta: dict,
) -> Activite:
    non_monotones = sum(1 for a, b in zip(points, points[1:], strict=False) if b.t < a.t)
    if non_monotones:
        avertissements.append(
            f"{non_monotones} horodatage(s) non monotone(s) : points réordonnés par date"
        )
        points = sorted(points, key=lambda p: p.t)
    meta = {k: v for k, v in meta.items() if v is not None}
    if avertissements:
        meta["avertissements"] = avertissements
    return Activite(
        source=source,
        fichier=fichier,
        debut=points[0].t,
        duree_s=(points[-1].t - points[0].t).total_seconds(),
        duree_mouvement_s=duree_mouvement_s,
        distance_m=distance_m,
        denivele_m=denivele_positif(points),
        puissance_moy_w=puissance_moyenne(points),
        puissance_np_w=puissance_normalisee(points),
        sport=sport,
        appareil=appareil,
        points=points,
        meta=meta,
    )


def _octets(source: Entree) -> tuple[bytes, str | None]:
    """Renvoie (contenu, chemin informatif). Lève `ErreurLecture` si vide ou illisible."""
    if isinstance(source, bytes | bytearray):
        contenu, fichier = bytes(source), None
    else:
        chemin = Path(source)
        try:
            contenu = chemin.read_bytes()
        except OSError as e:
            raise ErreurLecture(f"{chemin} : lecture impossible ({e})") from e
        fichier = str(chemin)
    if not contenu:
        raise ErreurLecture(f"{fichier or '<octets>'} : fichier vide")
    return contenu, fichier


def _derniere_distance(points: list[Point]) -> float | None:
    for point in reversed(points):
        if point.dist_m is not None:
            return point.dist_m
    return None


def _instant(valeur) -> datetime | None:
    """Normalise un horodatage en datetime UTC conscient du fuseau."""
    if valeur is None:
        return None
    if isinstance(valeur, str):
        texte = valeur.strip()
        if not texte:
            return None
        try:
            valeur = datetime.fromisoformat(texte.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(valeur, datetime):
        return None
    if valeur.tzinfo is None:
        return valeur.replace(tzinfo=UTC)  # source naïve : on suppose UTC
    return valeur.astimezone(UTC)


def _flottant(valeur) -> float | None:
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        x = float(valeur)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # écarte les NaN


def _texte(valeur) -> str | None:
    if valeur is None:
        return None
    texte = str(valeur).strip()
    return texte or None


def _sans_espace_de_noms(balise: str) -> str:
    return balise.rsplit("}", 1)[-1]

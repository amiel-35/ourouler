"""GPX : écrire un `Trace`, relire un GPX en `Trace`.

C'est le format d'échange décidé par le mainteneur (Q5) : le GPX suffit, on
ne pousse rien chez Garmin avant le sprint 5.

À ne pas confondre avec `activites.lecture.lire_gpx`, qui lit une **sortie
enregistrée** (points horodatés, puissance, cadence) pour l'inventaire.
Ici on lit un **parcours** : ni horodatage ni capteur, juste une suite de
points. Un GPX de parcours sans horodatage est refusé par l'autre lecteur,
et c'est précisément le cas courant.
"""

from __future__ import annotations

from pathlib import Path

import gpxpy
import gpxpy.gpx

from ourouler.boucle.trace import (
    DENIVELE_GPX_RELU,
    PointTrace,
    Trace,
    distance_m,
)
from ourouler.erreurs import ErreurLecture

Entree = Path | str | bytes | bytearray

CREATEUR = "ourouler"

#: Montées inférieures à ce seuil : du bruit d'altimètre, pas du dénivelé.
#: BRouter appelle cela « filtered ascend » ; on fait pareil, plus simplement.
SEUIL_DENIVELE_M = 2.0


# --- écriture -----------------------------------------------------------------


def ecrire_gpx(trace: Trace, nom: str) -> str:
    """Le tracé en GPX 1.1 : une `<trk>` nommée, avec altitudes si elles existent."""
    gpx = gpxpy.gpx.GPX()
    gpx.creator = CREATEUR
    piste = gpxpy.gpx.GPXTrack(name=nom, description=description(trace))
    segment = gpxpy.gpx.GPXTrackSegment()
    segment.points = [
        gpxpy.gpx.GPXTrackPoint(latitude=p.lat, longitude=p.lon, elevation=p.alt_m)
        for p in trace.points
    ]
    piste.segments.append(segment)
    gpx.tracks.append(piste)
    return gpx.to_xml(version="1.1")


def description(trace: Trace) -> str:
    """« 60,3 km · D+ 412 m (moteur) · 2 h 14 estimées » — ce qu'on sait du tracé.

    Le D+ porte sa provenance : sans elle, relire avec `--gpx` le fichier
    qu'on vient d'écrire affichait un dénivelé différent de celui inscrit
    dans le `<desc>`, sans qu'on puisse comprendre pourquoi (point 5 de la
    relecture du sprint 2).
    """
    morceaux = [f"{trace.distance_m / 1000:.1f} km".replace(".", ",")]
    if trace.denivele_m is not None:
        morceaux.append(f"D+ {trace.denivele_m:.0f} m{_provenance(trace)}")
    if trace.temps_moteur_s is not None:
        morceaux.append(f"{_duree(trace.temps_moteur_s)} estimées")
    return " · ".join(morceaux)


def _provenance(trace: Trace) -> str:
    """« (moteur) », « (gpx relu) », ou rien si la provenance n'a pas été notée."""
    source = trace.meta.get("denivele_source")
    return f" ({source})" if source else ""


def _duree(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


# --- import -------------------------------------------------------------------


def lire_gpx_trace(chemin_ou_bytes: Entree) -> Trace:
    """Lit un GPX de parcours : première `<trk>`, à défaut première `<rte>`.

    Les horodatages ne sont pas nécessaires (un parcours n'en a pas) ;
    `segments` reste vide, faute de tags OSM — d'où les coûts partiels du lot
    L2.4. Fichier vide, XML cassé ou GPX sans point : `ErreurLecture`.
    """
    contenu, fichier = _octets(chemin_ou_bytes)
    try:
        gpx = gpxpy.parse(contenu.decode("utf-8", errors="replace"))
    except Exception as e:  # gpxpy lève GPXException, mais aussi des erreurs XML brutes
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX illisible ({e})") from e

    nom, bruts = _premiere_suite(gpx)
    if not bruts:
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX sans point de tracé")

    points: list[PointTrace] = []
    cumul = 0.0
    for brut in bruts:
        if brut.latitude is None or brut.longitude is None:
            continue
        point = PointTrace(
            lat=float(brut.latitude),
            lon=float(brut.longitude),
            alt_m=float(brut.elevation) if brut.elevation is not None else None,
            dist_m=cumul,
        )
        if points:
            cumul += distance_m(points[-1], point)
            point = PointTrace(lat=point.lat, lon=point.lon, alt_m=point.alt_m, dist_m=cumul)
        points.append(point)
    if not points:
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX sans point de tracé")

    denivele = _denivele(points)
    return Trace(
        nom=nom or (Path(fichier).stem if fichier else "Trace importée"),
        points=points,
        segments=[],  # un GPX ne porte pas les tags OSM du moteur
        distance_m=cumul,
        denivele_m=denivele,
        temps_moteur_s=None,  # aucun moteur n'a estimé ce tracé
        meta={
            "source": "gpx",
            "fichier": fichier or "",
            "couts_partiels": True,
            # Recalculé sur les altitudes du fichier, pas repris d'un moteur :
            # les deux chiffres diffèrent, la colonne doit dire lequel.
            "denivele_source": DENIVELE_GPX_RELU if denivele is not None else None,
        },
    )


def _premiere_suite(gpx) -> tuple[str, list]:
    """(nom, points) de la première piste non vide, à défaut de la première route."""
    for piste in gpx.tracks:
        points = [p for segment in piste.segments for p in segment.points]
        if points:
            return (piste.name or ""), points
    for route in gpx.routes:
        if route.points:
            return (route.name or ""), list(route.points)
    return "", []


def _denivele(points: list[PointTrace]) -> float | None:
    """Le D+ du tracé, ou None si aucun point n'a d'altitude.

    Les montées sous `SEUIL_DENIVELE_M` sont ignorées : sans filtre, le bruit
    d'un altimètre barométrique double le dénivelé d'un parcours plat. Le
    chiffre reste indicatif — le moteur, lui, donne son propre « filtered
    ascend », qu'on préfère quand on l'a.
    """
    altitudes = [p.alt_m for p in points if p.alt_m is not None]
    if len(altitudes) < 2:
        return None
    total = 0.0
    reference = altitudes[0]
    for altitude in altitudes[1:]:
        ecart = altitude - reference
        if ecart >= SEUIL_DENIVELE_M:
            total += ecart
            reference = altitude
        elif ecart <= -SEUIL_DENIVELE_M:
            reference = altitude
    return total


def _octets(source: Entree) -> tuple[bytes, str | None]:
    """(contenu, chemin informatif). `ErreurLecture` si le fichier est absent ou vide."""
    if isinstance(source, bytes | bytearray):
        contenu, fichier = bytes(source), None
    else:
        chemin = Path(source)
        try:
            contenu = chemin.read_bytes()
        except OSError as e:
            raise ErreurLecture(f"{chemin} : lecture impossible ({e})") from e
        fichier = str(chemin)
    if not contenu.strip():
        raise ErreurLecture(f"{fichier or '<octets>'} : fichier vide")
    return contenu, fichier

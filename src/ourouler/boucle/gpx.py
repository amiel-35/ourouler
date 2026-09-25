"""GPX : écrire un `Trace`, relire un GPX en `Trace`.

C'est le format d'échange décidé par le mainteneur (Q5) : le GPX suffit, on
ne pousse rien chez Garmin avant le sprint 5.

À ne pas confondre avec `activites.lecture.lire_gpx`, qui lit une **sortie
enregistrée** (points horodatés, puissance, cadence) pour l'inventaire.
Ici on lit un **parcours** : ni horodatage ni capteur, juste une suite de
points. Un GPX de parcours sans horodatage est refusé par l'autre lecteur,
et c'est précisément le cas courant.

Le calcul du D+ (`denivele_filtre`, `SEUIL_DENIVELE_M`) a rejoint
`boucle.trace` : il ne dépend pas du format, et `seance.placement` en a besoin
pour le parcours réellement roulé.
"""

from __future__ import annotations

import math
from pathlib import Path

import gpxpy
import gpxpy.gpx

from ourouler.noyau.erreurs import ErreurLecture
from ourouler.noyau.trace import (
    DENIVELE_GPX_RELU,
    PointTrace,
    Trace,
    denivele_filtre,
    distance_m,
)

Entree = Path | str | bytes | bytearray

CREATEUR = "ourouler"


# --- écriture -----------------------------------------------------------------


def ecrire_gpx(trace: Trace, nom: str, *, desc: str | None = None) -> str:
    """Le tracé en GPX 1.1 : une `<trk>` nommée, avec altitudes si elles existent.

    `desc` remplace la description par défaut quand l'appelant en sait plus que
    le tracé lui-même — `ourouler sortie` y met le nombre de demi-tours du
    parcours placé, que la géométrie seule ne dit pas.
    """
    gpx = gpxpy.gpx.GPX()
    gpx.creator = CREATEUR
    piste = gpxpy.gpx.GPXTrack(name=nom, description=desc if desc is not None else description(trace))
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
    L2.4. Fichier vide, XML cassé, GPX sans point ou coordonnée impossible :
    `ErreurLecture`.

    Pour un parcours **déposé** à analyser, qui peut arriver en plusieurs
    traces, voir `lire_gpx_parcours`.
    """
    contenu, fichier = _octets(chemin_ou_bytes)
    gpx = _analyser_xml(contenu, fichier)
    nom, bruts = _premiere_suite(gpx)
    return _trace_depuis(bruts, nom, fichier)


#: Au-delà de cet écart entre la fin d'un morceau et le début du suivant,
#: `lire_gpx_parcours` le dit : ce n'est plus un point GPS qui saute, c'est un
#: trou dans le tracé, que le calcul franchit en ligne droite.
ECART_MAX_ENTRE_MORCEAUX_M = 200.0


def lire_gpx_parcours(chemin_ou_bytes: Entree) -> tuple[Trace, list[str]]:
    """Lit **tout** un GPX de parcours (L9.8) : (tracé, avertissements).

    Un brevet ou une Flèche arrive souvent en plusieurs `<trk>` (une par
    étape) ou en plusieurs `<trkseg>`. `lire_gpx_trace` n'en lit que le
    premier — ce qui, pour un parcours qu'on va rouler en entier, tronque en
    silence. Ici, toutes les traces et tous leurs segments sont enchaînés dans
    l'ordre du fichier ; à défaut de trace, toutes les routes (`<rte>`).

    Les avertissements disent ce qui a été fait, en phrases lisibles :
    « 3 traces enchaînées », et chaque trou de plus de
    `ECART_MAX_ENTRE_MORCEAUX_M` entre deux morceaux, **compté en ligne
    droite** dans la distance — le calcul ne sait pas par où on passe, il ne
    le cache pas.
    """
    contenu, fichier = _octets(chemin_ou_bytes)
    gpx = _analyser_xml(contenu, fichier)

    # (libellé, nom, points) de chaque morceau non vide, dans l'ordre du fichier.
    morceaux: list[tuple[str, str, list]] = []
    for i, piste in enumerate(gpx.tracks, start=1):
        segments = [seg for seg in piste.segments if seg.points]
        for j, segment in enumerate(segments, start=1):
            libelle = f"la trace {i}" if len(segments) == 1 else f"la trace {i} (segment {j})"
            morceaux.append((libelle, piste.name or "", list(segment.points)))
    genre = "traces"
    if not morceaux:
        genre = "routes"
        for i, route in enumerate(gpx.routes, start=1):
            if route.points:
                morceaux.append((f"la route {i}", route.name or "", list(route.points)))

    bruts = [p for _, _, points in morceaux for p in points]
    nom = next((n for _, n, _ in morceaux if n), "")
    trace = _trace_depuis(bruts, nom, fichier)

    avertissements: list[str] = []
    if len(morceaux) > 1:
        # « 3 traces enchaînées » quand chaque trace n'a qu'un segment ;
        # sinon on dit « morceaux », chaque trou nommant ensuite trace et segment.
        un_segment_par_piste = all("segment" not in libelle for libelle, _, _ in morceaux)
        mot = genre if un_segment_par_piste else "morceaux"
        accord = "enchaînés" if mot == "morceaux" else "enchaînées"
        avertissements.append(f"{len(morceaux)} {mot} {accord}, dans l'ordre du fichier")
    for (libelle_a, _, points_a), (libelle_b, _, points_b) in zip(
        morceaux[:-1], morceaux[1:], strict=True
    ):
        fin_a, debut_b = _coordonnees(points_a[-1], fichier), _coordonnees(points_b[0], fichier)
        if fin_a is None or debut_b is None:
            continue
        ecart = distance_m(
            PointTrace(lat=fin_a[0], lon=fin_a[1], alt_m=None, dist_m=0.0),
            PointTrace(lat=debut_b[0], lon=debut_b[1], alt_m=None, dist_m=0.0),
        )
        if ecart > ECART_MAX_ENTRE_MORCEAUX_M:
            avertissements.append(
                f"un trou de {_distance_lisible(ecart)} entre {libelle_a} et {libelle_b}, "
                "compté en ligne droite dans la distance et la durée"
            )
    return trace, avertissements


def _distance_lisible(metres: float) -> str:
    if metres >= 1000:
        return f"{metres / 1000:.1f} km".replace(".", ",").replace(",0 km", " km")
    return f"{metres:.0f} m"


def _analyser_xml(contenu: bytes, fichier: str | None):
    try:
        return gpxpy.parse(contenu.decode("utf-8", errors="replace"))
    except Exception as e:  # gpxpy lève GPXException, mais aussi des erreurs XML brutes
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX illisible ({e})") from e


def _coordonnees(brut, fichier: str | None) -> tuple[float, float] | None:
    """(lat, lon) d'un point GPX, `None` s'il n'en a pas ; `ErreurLecture` si impossible.

    Une coordonnée impossible (« nan », « inf », une latitude de 91°) n'est
    pas un parcours : refusée ici, lisiblement, plutôt que de remonter en
    `ValueError` du calcul de distance — une erreur interne (500) côté API
    (relecture de L9.8, 25/09/2026).
    """
    if brut.latitude is None or brut.longitude is None:
        return None
    lat, lon = float(brut.latitude), float(brut.longitude)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ErreurLecture(
            f"{fichier or '<octets>'} : coordonnée impossible dans le GPX "
            f"(latitude {brut.latitude}, longitude {brut.longitude})"
        )
    return lat, lon


def _trace_depuis(bruts: list, nom: str, fichier: str | None) -> Trace:
    """Le `Trace` de points GPX bruts, distances cumulées et D+ recalculés."""
    if not bruts:
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX sans point de tracé")

    points: list[PointTrace] = []
    cumul = 0.0
    for brut in bruts:
        coordonnees = _coordonnees(brut, fichier)
        if coordonnees is None:
            continue
        altitude = float(brut.elevation) if brut.elevation is not None else None
        if altitude is not None and not math.isfinite(altitude):
            altitude = None  # « nan » en altitude : une altitude absente, pas un calcul faux
        point = PointTrace(lat=coordonnees[0], lon=coordonnees[1], alt_m=altitude, dist_m=cumul)
        if points:
            cumul += distance_m(points[-1], point)
            point = PointTrace(lat=point.lat, lon=point.lon, alt_m=point.alt_m, dist_m=cumul)
        points.append(point)
    if not points:
        raise ErreurLecture(f"{fichier or '<octets>'} : GPX sans point de tracé")

    denivele = denivele_filtre(points)
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

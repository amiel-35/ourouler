"""Pluie et vent **le long du tracé, à l'heure de passage**.

La différence avec `ourouler.meteo` : là on demandait « où va-t-il pleuvoir
autour de moi ? » sur une couronne de points, ici on suit un parcours déjà
tracé et on interroge chaque tronçon à l'heure où le cycliste y sera. Une
averse qui traverse la région à 10 h ne concerne que les kilomètres 25 à 35.

Un **seul** appel Open-Meteo pour tous les échantillons (le service accepte
plusieurs coordonnées par requête) ; un second appel seulement si un second
avis est demandé. Les valeurs horaires sont interpolées linéairement entre
les deux heures encadrantes — angulairement pour la direction du vent, sans
quoi 350° et 10° donneraient 180°, c'est-à-dire le sud au lieu du nord.

La règle du vent relatif (secteur de ±45°) n'est pas réécrite ici : c'est
`ourouler.meteo.rapport.vent_relatif`, appliquée au **cap local du tracé**
au lieu de l'azimut d'une direction de couronne.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.openmeteo import ClientOpenMeteo, PrevisionHeure
from ourouler.meteo.rapport import (
    CONFIANCE_ACCORD,
    CONFIANCE_DESACCORD,
    CONFIANCE_INCONNUE,
    VENT_DOS,
    VENT_FACE,
    confiance,
    vent_relatif,
)

#: Au-delà, on compte l'échantillon comme « sous la pluie » (seuil du contrat).
SEUIL_PLUIE_MM_H = 0.2

#: Marge demandée après l'heure d'arrivée : la dernière heure encadrante doit
#: exister, sinon le dernier échantillon ne serait pas interpolable.
MARGE_APRES_ARRIVEE_H = 1

#: Pas d'échantillonnage par défaut, en mètres.
PAS_DEFAUT_M = 5000.0


@dataclass
class Echantillon:
    """Un point du tracé, à l'heure où le cycliste y passe."""

    dist_m: float
    t: datetime
    lat: float
    lon: float
    cap_deg: float
    pluie_mm: float | None
    vent_kmh: float | None
    vent_relatif: str | None
    ressenti_c: float | None


@dataclass
class MeteoTrace:
    """Ce que le tracé promet comme météo, échantillon par échantillon et en résumé."""

    echantillons: list[Echantillon]
    pluie_cumulee_mm: float
    minutes_pluie: float
    part_vent_face: float  # fraction dans [0, 1] des échantillons au vent connu
    part_vent_dos: float
    ressenti_min_c: float | None
    confiance: str


def evaluer(
    trace: Trace,
    client: ClientOpenMeteo,
    *,
    depart: datetime,
    vitesse_kmh: float,
    modele: str,
    second_avis: str | None = None,
    pas_m: float = PAS_DEFAUT_M,
) -> MeteoTrace:
    """La météo le long de `trace`, échantillonnée tous les `pas_m`.

    `depart` sans fuseau est lu comme UTC, comme dans le client Open-Meteo.
    `vitesse_kmh` sert à dater chaque échantillon : heure de passage =
    `depart + distance / vitesse`. Elle vient de la configuration, jamais
    d'une lecture faite ici (règle absolue 2).
    """
    # Ces trois refus tombent **avant** le premier appel à Open-Meteo : une
    # entrée absurde ne consomme pas de quota et ne fait pas attendre.
    if not trace.points:
        raise ErreurUtilisateur("tracé sans point : il n'y a rien à évaluer le long du parcours")
    if not _strictement_positif(vitesse_kmh):
        raise ErreurUtilisateur(
            f"vitesse_kmh = {vitesse_kmh} : une vitesse strictement positive est attendue "
            "(l'heure de passage vaut départ + distance / vitesse)"
        )
    if not _strictement_positif(pas_m):
        raise ErreurUtilisateur(
            f"pas_m = {pas_m} : un pas d'échantillonnage strictement positif est attendu"
        )

    depart_tz = depart if depart.tzinfo else depart.replace(tzinfo=UTC)
    distances = _distances_cumulees(trace.points)
    indices = _indices_echantillons(distances, pas_m)

    bases = [
        (
            distances[i],
            depart_tz + timedelta(hours=distances[i] / 1000.0 / vitesse_kmh),
            trace.points[i],
            _cap_local(trace.points, i),
        )
        for i in indices
    ]
    coordonnees = [(p.lat, p.lon) for _, _, p, _ in bases]

    debut_heure, horizon_h = _fenetre(depart_tz, bases[-1][1])
    previsions = client.previsions(
        coordonnees, modele=modele, debut=debut_heure, horizon_h=horizon_h
    )

    echantillons = []
    for (dist, t, point, cap), prevision in zip(bases, previsions, strict=True):
        valeurs = _interpoler(prevision.heures, t)
        echantillons.append(
            Echantillon(
                dist_m=dist,
                t=t,
                lat=point.lat,
                lon=point.lon,
                cap_deg=cap if cap is not None else 0.0,
                pluie_mm=valeurs.pluie_mm,
                vent_kmh=valeurs.vent_kmh,
                # Sans cap local (tracé réduit à un point), il n'y a pas de
                # « à l'aller » : la valeur est absente plutôt que fausse —
                # même raison que pour le point « ici » d'une couronne.
                vent_relatif=(
                    vent_relatif(cap, valeurs.vent_depuis_deg) if cap is not None else None
                ),
                ressenti_c=valeurs.ressenti_c,
            )
        )

    pluies_second_avis = _second_avis(
        client, coordonnees, [t for _, t, _, _ in bases], debut_heure, horizon_h, second_avis
    )
    return _resumer(echantillons, pluies_second_avis)


# --- échantillonnage ---------------------------------------------------------


def _strictement_positif(valeur: float) -> bool:
    """Vrai pour un nombre fini et > 0. NaN et l'infini sont des refus, pas des vitesses."""
    return math.isfinite(valeur) and valeur > 0


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    `PointTrace.dist_m` est la source normale. Un tracé importé qui aurait
    laissé ce champ à zéro donnerait un seul échantillon au kilomètre zéro,
    en silence : on le rattrape plutôt que de rendre une météo de départ
    pour tout le parcours.
    """
    if len(points) >= 2 and points[-1].dist_m > 0:
        return [p.dist_m for p in points]
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _indices_echantillons(distances: Sequence[float], pas_m: float) -> list[int]:
    """Indices des points à échantillonner : tous les `pas_m`, et le dernier point."""
    total = distances[-1]
    cibles = []
    cible = 0.0
    while cible < total:
        cibles.append(cible)
        cible += pas_m
    cibles.append(total)

    indices: list[int] = []
    j = 0
    for cible in cibles:
        while j + 1 < len(distances) and distances[j] < cible:
            j += 1
        if not indices or indices[-1] != j:
            indices.append(j)
    return indices


def _cap_local(points: Sequence[PointTrace], i: int) -> float | None:
    """Le cap du tracé au point `i` : vers le suivant, ou depuis le précédent au bout.

    `None` si aucun autre point distinct n'existe (tracé réduit à un point).
    """
    for j in range(i + 1, len(points)):
        if distance_m(points[i], points[j]) > 0:
            return cap_deg(points[i], points[j])
    for j in range(i - 1, -1, -1):
        if distance_m(points[j], points[i]) > 0:
            return cap_deg(points[j], points[i])
    return None


def _fenetre(depart: datetime, arrivee: datetime) -> tuple[datetime, int]:
    """(première heure demandée, nombre d'heures) couvrant départ → arrivée + 1 h.

    Le début est ramené à l'heure pleine précédente : sans cela, un départ à
    8 h 30 n'aurait pas d'heure encadrante inférieure et le premier
    échantillon serait vide.
    """
    debut = depart.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    fin = arrivee.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=MARGE_APRES_ARRIVEE_H
    )
    heures = int((fin - debut).total_seconds() // 3600) + 1
    return (debut, max(1, heures))


# --- interpolation entre les deux heures encadrantes -------------------------


@dataclass(frozen=True)
class _Valeurs:
    """Ce qu'on retient d'une heure interpolée. Tout peut manquer."""

    pluie_mm: float | None = None
    vent_kmh: float | None = None
    vent_depuis_deg: float | None = None
    ressenti_c: float | None = None


def _interpoler(heures: Sequence[PrevisionHeure], t: datetime) -> _Valeurs:
    """Les valeurs à l'instant `t`, interpolées entre les deux heures encadrantes.

    Hors de la série (tracé plus long que l'horizon du modèle, départ avant
    la première heure fournie) : tout est absent. On ne prolonge pas la
    dernière heure connue — ce serait affirmer sans mesure.
    """
    encadrantes = _encadrantes(heures, t)
    if encadrantes is None:
        return _Valeurs()
    avant, apres = encadrantes
    duree = (apres.t - avant.t).total_seconds()
    f = (t - avant.t).total_seconds() / duree if duree > 0 else 0.0
    return _Valeurs(
        pluie_mm=_lineaire(avant.pluie_mm, apres.pluie_mm, f),
        vent_kmh=_lineaire(avant.vent_kmh, apres.vent_kmh, f),
        vent_depuis_deg=_angulaire(avant.vent_depuis_deg, apres.vent_depuis_deg, f),
        ressenti_c=_lineaire(avant.ressenti_c, apres.ressenti_c, f),
    )


def _encadrantes(
    heures: Sequence[PrevisionHeure], t: datetime
) -> tuple[PrevisionHeure, PrevisionHeure] | None:
    """Les deux heures qui encadrent `t`, ou `None` si `t` est hors de la série.

    Une heure pile est rendue seule, des deux côtés : sinon un échantillon
    tombant exactement sur 09 h serait interpolé depuis le couple (08 h, 09 h)
    et une valeur absente à 08 h effacerait la valeur connue de 09 h.
    """
    if not heures or t < heures[0].t or t > heures[-1].t:
        return None
    for heure in heures:
        if heure.t == t:
            return (heure, heure)
    for avant, apres in zip(heures[:-1], heures[1:], strict=True):
        if avant.t < t < apres.t:
            return (avant, apres)
    return None  # série non triée : on préfère ne rien affirmer


def _lineaire(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return None
    return a + (b - a) * f


def _angulaire(a: float | None, b: float | None, f: float) -> float | None:
    """Interpolation d'un angle par ses composantes : 350° et 10° donnent 0°, pas 180°."""
    if a is None or b is None:
        return None
    ra, rb = math.radians(a), math.radians(b)
    x = math.cos(ra) + (math.cos(rb) - math.cos(ra)) * f
    y = math.sin(ra) + (math.sin(rb) - math.sin(ra)) * f
    if x == 0.0 and y == 0.0:  # deux directions opposées à mi-chemin : indécidable
        return a
    return math.degrees(math.atan2(y, x)) % 360.0


# --- second avis -------------------------------------------------------------


def _second_avis(
    client: ClientOpenMeteo,
    coordonnees: Sequence[tuple[float, float]],
    instants: Sequence[datetime],
    debut_heure: datetime,
    horizon_h: int,
    modele: str | None,
) -> list[float | None] | None:
    """La pluie d'un second modèle aux mêmes points et aux mêmes instants.

    `None` si aucun second avis n'est demandé **ou** si le second modèle ne
    répond pas (hors domaine, service en panne) : un second avis manquant
    n'est pas une raison de faire échouer l'évaluation, il rend seulement la
    confiance « inconnu ». Les deux modèles ne sont jamais moyennés.
    """
    if not modele:
        return None
    try:
        previsions = client.previsions(
            coordonnees, modele=modele, debut=debut_heure, horizon_h=horizon_h
        )
    except ErreurConnecteur:
        return None
    return [
        _interpoler(prevision.heures, t).pluie_mm
        for prevision, t in zip(previsions, instants, strict=True)
    ]


# --- résumé ------------------------------------------------------------------


def _resumer(
    echantillons: Sequence[Echantillon], pluies_second_avis: Sequence[float | None] | None
) -> MeteoTrace:
    """Les agrégats : cumul de pluie, minutes sous la pluie, parts de vent, confiance."""
    durees_h = _durees_h(echantillons)

    pluie_cumulee = sum(
        e.pluie_mm * d for e, d in zip(echantillons, durees_h, strict=True) if e.pluie_mm is not None
    )
    minutes_pluie = sum(
        d * 60.0
        for e, d in zip(echantillons, durees_h, strict=True)
        if e.pluie_mm is not None and e.pluie_mm >= SEUIL_PLUIE_MM_H
    )

    # Parts de vent sur le **nombre** d'échantillons au vent connu : la
    # vitesse étant constante, ils sont régulièrement espacés en temps comme
    # en distance, et un échantillon sans vent ne doit pas compter pour du
    # travers.
    connus = [e.vent_relatif for e in echantillons if e.vent_relatif is not None]
    part_face = connus.count(VENT_FACE) / len(connus) if connus else 0.0
    part_dos = connus.count(VENT_DOS) / len(connus) if connus else 0.0

    ressentis = [e.ressenti_c for e in echantillons if e.ressenti_c is not None]

    return MeteoTrace(
        echantillons=list(echantillons),
        pluie_cumulee_mm=pluie_cumulee,
        minutes_pluie=minutes_pluie,
        part_vent_face=part_face,
        part_vent_dos=part_dos,
        ressenti_min_c=min(ressentis) if ressentis else None,
        confiance=_confiance_globale(echantillons, pluies_second_avis),
    )


def _durees_h(echantillons: Sequence[Echantillon]) -> list[float]:
    """La durée que chaque échantillon représente, en heures (règle du point milieu).

    Un échantillon vaut du milieu de l'intervalle qui le précède au milieu de
    celui qui le suit ; la somme fait exactement la durée du parcours. Un
    échantillon unique représente une durée nulle : on ne sait pas combien de
    temps dure un tracé réduit à un point.
    """
    n = len(echantillons)
    if n < 2:
        return [0.0] * n
    instants = [e.t for e in echantillons]
    bornes = [instants[0]]
    for avant, apres in zip(instants[:-1], instants[1:], strict=True):
        bornes.append(avant + (apres - avant) / 2)
    bornes.append(instants[-1])
    return [
        (fin - debut).total_seconds() / 3600.0
        for debut, fin in zip(bornes[:-1], bornes[1:], strict=True)
    ]


def _confiance_globale(
    echantillons: Sequence[Echantillon], pluies_second_avis: Sequence[float | None] | None
) -> str:
    """« desaccord » dès qu'un échantillon divise les deux modèles, « inconnu » si rien n'est comparable."""
    if pluies_second_avis is None:
        return CONFIANCE_INCONNUE
    niveaux = [
        confiance(e.pluie_mm, seconde)
        for e, seconde in zip(echantillons, pluies_second_avis, strict=True)
    ]
    if CONFIANCE_DESACCORD in niveaux:
        return CONFIANCE_DESACCORD
    if CONFIANCE_ACCORD in niveaux:
        return CONFIANCE_ACCORD
    return CONFIANCE_INCONNUE

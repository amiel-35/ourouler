"""Calibrer CdA et Crr sur les sorties réelles, puis mesurer ce que ça vaut.

La chaîne, en cinq temps :

1. `sorties_calibrables` choisit les sorties exploitables (extérieur, avec
   puissance, ≥ 20 km, nom sans mot de groupe) ;
2. `echantillonner` découpe chaque sortie en tronçons d'environ 200 m et note,
   pour chacun, vitesse, puissance, pente, vent de face et masse volumique de
   l'air — puis marque ceux qu'on garde et **pourquoi** on jette les autres ;
3. `calibrer` ajuste (CdA, Crr) aux moindres carrés sur l'écart de puissance ;
4. `detecter_groupe` repère, avec le modèle obtenu, les sorties
   anormalement rapides — l'aspiration d'un peloton, que ni la pente ni le
   vent n'expliquent ;
5. `valider` rejoue les sorties **les plus récentes**, jamais vues par
   l'ajustement, et rend l'erreur de temps en mouvement.

Le tout deux fois (`calibrer_en_deux_passes`) : la première passe sert à
trouver les sorties en groupe, la seconde à calibrer sans elles.

Ce que le modèle ne sait pas, et qu'il faut lire avec le rapport : il ignore
les arrêts (le temps rendu est un temps **en mouvement**), il ignore l'inertie
(une sortie hachée coûte plus cher que ce qu'il dit), et il prend le vent à
10 m du sol tel que l'archive le donne, alors que le cycliste roule à 1,5 m,
dans un couloir d'arbres et de haies. Ces trois écarts vont tous dans le même
sens : ils font paraître le cycliste plus lent que le modèle.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import numpy as np

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur, rattacher_velo
from ourouler.activites.modele import Activite, Point, est_sport_velo, moyenne_glissante
from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m
from ourouler.config import Config, Velo
from ourouler.connecteurs.openmeteo_archive import HeureArchive
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.modele import (
    RHO_DEFAUT,
    Parametres,
    Simulation,
    masse_volumique_air,
    puissance_requise,
    simuler,
    vitesse_regime,
)

#: Longueur visée d'un échantillon, en mètres (contrat de sprint §3).
LONGUEUR_ECHANTILLON_M = 200.0

#: Sous cette vitesse instantanée, le cycliste est à l'arrêt (feu, stop).
#: Un échantillon qui en contient un seul point est jeté : sa vitesse moyenne
#: ne décrit plus un équilibre physique.
SEUIL_ARRET_MS = 1.0

#: Les deux premiers kilomètres sont écartés : mise en route, sortie de ville,
#: capteur de puissance qui n'a pas fini de se caler.
DEBUT_IGNORE_M = 2000.0

#: Bornes de pente des échantillons retenus (contrat §3).
PENTE_MIN = -0.03
PENTE_MAX = 0.08

#: Puissance minimale d'un échantillon retenu, en watts : en dessous, le
#: cycliste roule sur l'élan et le modèle d'équilibre ne s'applique pas.
PUISSANCE_MIN_W = 50.0

#: Multiple de la FTP au-delà duquel un échantillon est jeté (sprint, artefact).
FACTEUR_FTP_MAX = 2.0

#: Variation de vitesse tolérée entre deux échantillons voisins, en m/s.
#: Au-delà, le cycliste accélère ou freine : l'énergie cinétique change, et le
#: modèle, qui ne connaît que l'équilibre, attribuerait cet écart au CdA.
DELTA_V_MAX_MS = 0.3

#: Pas de la moyenne glissante qui lisse l'altitude des échantillons. Trois
#: échantillons de 200 m font une fenêtre de 600 m, comparable aux 700 m de
#: `physique.modele.FENETRE_ALTITUDE`.
FENETRE_ALTITUDE = 3

#: Bornes de l'ajustement (contrat §3).
CDA_MIN, CDA_MAX = 0.18, 0.60
CRR_MIN, CRR_MAX = 0.002, 0.012

#: Masse d'un vélo dont la configuration ne dit rien, en kilogrammes.
MASSE_VELO_DEFAUT_KG = 9.0

#: Nombre minimal d'échantillons pour ajuster deux paramètres.
ECHANTILLONS_MINIMUM = 3

#: Une sortie est dite « en groupe » si le résidu de vitesse dépasse ce seuil
#: sur plus de `PART_DISTANCE_GROUPE` de la distance retenue (contrat §3).
SEUIL_RESIDU_GROUPE = 0.08
PART_DISTANCE_GROUPE = 0.50

#: Distance minimale d'une sortie calibrable, en mètres.
DISTANCE_MINIMALE_M = 20_000.0

#: Vitesse à laquelle on exprime ce que la calibration détermine **vraiment**.
#: CdA et Crr pris séparément peuvent être mal séparés ; leur somme des forces
#: à l'allure d'entraînement, elle, est bien contrainte par les données.
V_REFERENCE_KMH = 27.0

MOTIF_RETENU = ""

#: Date de repli pour trier une entrée sans horodatage — avant tout le reste,
#: et consciente du fuseau, sinon la comparaison échoue sur un mélange de
#: dates naïves et datées.
_JAMAIS = datetime.min.replace(tzinfo=UTC)


# --- échantillons -------------------------------------------------------------


@dataclass
class Echantillon:
    """Un tronçon d'environ 200 m d'une sortie réelle, et ce qu'on en sait.

    `retenu` dit si la calibration s'en sert, `motif` dit pourquoi pas. Les
    champs après `motif` sont des compléments du contrat de sprint : la
    longueur (pour pondérer par la distance), la masse volumique de l'air
    mesurée du jour, si le vent était connu, et l'instant de passage.
    """

    v_ms: float
    puissance_w: float
    pente: float
    vent_face_ms: float
    temp_c: float
    retenu: bool
    motif: str
    longueur_m: float = 0.0
    rho: float = RHO_DEFAUT
    vent_connu: bool = True
    t: datetime | None = None
    dist_m: float = 0.0


def echantillonner(
    activite: Activite,
    vent: list[HeureArchive],
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> list[Echantillon]:
    """Découpe une sortie en tronçons de `LONGUEUR_ECHANTILLON_M` et les qualifie.

    Tous les tronçons sont rendus, retenus ou non : le rapport de calibration
    doit pouvoir dire combien d'échantillons ont été écartés et pour quelle
    raison, plutôt que d'afficher un nombre sorti de nulle part.

    `vent` est l'archive du jour au point de départ ; vide, les échantillons
    portent un vent nul et `vent_connu = False`.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2:
        return []
    distances = _distances_points(points)
    bruts = _decouper(points, distances)
    if not bruts:
        return []

    altitudes = moyenne_glissante(
        [_altitude_moyenne(points, i, j) for i, j, *_ in bruts], FENETRE_ALTITUDE
    )
    echantillons: list[Echantillon] = []
    for indice, (i, j, longueur, duree) in enumerate(bruts):
        pente = _pente(altitudes, indice, longueur)
        t_milieu = points[i].t + (points[j].t - points[i].t) / 2
        heure = _interpoler_archive(vent, t_milieu)
        cap = _cap(points, i, j)
        face = _vent_de_face(heure, cap)
        echantillons.append(
            Echantillon(
                v_ms=longueur / duree,
                puissance_w=_puissance_moyenne(points, i, j),
                pente=pente,
                vent_face_ms=face if face is not None else 0.0,
                temp_c=heure.temp_c if heure is not None and heure.temp_c is not None else float("nan"),
                retenu=False,
                motif=MOTIF_RETENU,
                longueur_m=longueur,
                rho=masse_volumique_air(
                    heure.temp_c if heure else None, heure.pression_hpa if heure else None
                ),
                vent_connu=face is not None,
                t=t_milieu,
                dist_m=distances[j],
            )
        )
        if _contient_un_arret(points, i, j):
            echantillons[-1].motif = "arrêt"

    _qualifier(echantillons, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
    return echantillons


def _decouper(
    points: Sequence[Point], distances: Sequence[float]
) -> list[tuple[int, int, float, float]]:
    """(début, fin, longueur, durée) de chaque tronçon d'environ 200 m."""
    tronçons = []
    debut = 0
    for i in range(1, len(points)):
        longueur = distances[i] - distances[debut]
        if longueur < LONGUEUR_ECHANTILLON_M:
            continue
        duree = (points[i].t - points[debut].t).total_seconds()
        if duree > 0:
            tronçons.append((debut, i, longueur, duree))
        debut = i
    return tronçons


def _distances_points(points: Sequence[Point]) -> list[float]:
    """Distances cumulées : celles de la source si elles sont croissantes, sinon la géométrie."""
    portees = [p.dist_m for p in points]
    if all(d is not None for d in portees) and all(
        b >= a for a, b in zip(portees[:-1], portees[1:], strict=True)
    ):
        return [float(d) for d in portees]
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
            cumul.append(cumul[-1])
            continue
        cumul.append(cumul[-1] + distance_m(_en_point_trace(a), _en_point_trace(b)))
    return cumul


def _cap(points: Sequence[Point], i: int, j: int) -> float | None:
    """Cap moyen du tronçon, ou `None` si l'un des deux bouts n'a pas de position."""
    if any(p.lat is None or p.lon is None for p in (points[i], points[j])):
        return None
    debut, fin = _en_point_trace(points[i]), _en_point_trace(points[j])
    return cap_deg(debut, fin) if distance_m(debut, fin) > 0 else None


def _en_point_trace(p: Point) -> PointTrace:
    return PointTrace(lat=float(p.lat), lon=float(p.lon), alt_m=p.alt_m, dist_m=float(p.dist_m or 0.0))


def _altitude_moyenne(points: Sequence[Point], i: int, j: int) -> float:
    """Altitude moyenne du tronçon. 0 si la sortie n'a pas d'altitude (terrain plat faute de mieux)."""
    valeurs = [float(p.alt_m) for p in points[i : j + 1] if p.alt_m is not None]
    return sum(valeurs) / len(valeurs) if valeurs else 0.0


def _pente(altitudes: Sequence[float], indice: int, longueur: float) -> float:
    """Pente du tronçon : différence des altitudes lissées voisines, sur deux demi-longueurs.

    L'altitude lissée d'un tronçon vaut en son milieu : la dénivelée entre le
    tronçon précédent et le suivant couvre donc deux longueurs de tronçon.
    Aux deux bouts, on se rabat sur le voisin qui existe.
    """
    avant = altitudes[indice - 1] if indice > 0 else altitudes[indice]
    apres = altitudes[indice + 1] if indice + 1 < len(altitudes) else altitudes[indice]
    portee = longueur * (2 if 0 < indice < len(altitudes) - 1 else 1)
    return (apres - avant) / portee if portee > 0 else 0.0


def _puissance_moyenne(points: Sequence[Point], i: int, j: int) -> float:
    """Puissance moyenne du tronçon, pondérée par la durée. NaN si aucune valeur."""
    somme = duree = 0.0
    for a, b in zip(points[i:j], points[i + 1 : j + 1], strict=True):
        if a.puissance_w is None:
            continue
        dt = (b.t - a.t).total_seconds()
        if dt <= 0:
            continue
        somme += float(a.puissance_w) * dt
        duree += dt
    return somme / duree if duree > 0 else float("nan")


def _contient_un_arret(points: Sequence[Point], i: int, j: int) -> bool:
    """Vrai si un point du tronçon est sous `SEUIL_ARRET_MS`.

    La vitesse moyenne d'un tronçon coupé par un feu rouge ne décrit aucun
    équilibre : la garder reviendrait à demander au modèle d'expliquer un
    arrêt par de la traînée.
    """
    return any(
        p.vitesse_ms is not None and float(p.vitesse_ms) < SEUIL_ARRET_MS for p in points[i : j + 1]
    )


def _qualifier(
    echantillons: list[Echantillon], *, ftp_w: float, vitesse_min_kmh: float
) -> None:
    """Pose `retenu` et `motif` sur chaque échantillon, filtres du contrat §3."""
    vitesse_min_ms = vitesse_min_kmh / 3.6
    puissance_max = FACTEUR_FTP_MAX * ftp_w
    for indice, e in enumerate(echantillons):
        motif = e.motif  # « arrêt » a pu être posé plus tôt
        if not motif:
            if e.dist_m - e.longueur_m < DEBUT_IGNORE_M:
                motif = "départ"
            elif not math.isfinite(e.puissance_w):
                motif = "sans puissance"
            elif not (PUISSANCE_MIN_W <= e.puissance_w <= puissance_max):
                motif = "puissance"
            elif e.v_ms < vitesse_min_ms:
                motif = "vitesse"
            elif not (PENTE_MIN <= e.pente <= PENTE_MAX):
                motif = "pente"
            elif _accelere(echantillons, indice):
                motif = "accélération"
        e.motif = motif
        e.retenu = not motif


def _accelere(echantillons: Sequence[Echantillon], indice: int) -> bool:
    """Vrai si la vitesse change de plus de `DELTA_V_MAX_MS` avec un voisin."""
    v = echantillons[indice].v_ms
    for voisin in (indice - 1, indice + 1):
        if 0 <= voisin < len(echantillons):
            if abs(echantillons[voisin].v_ms - v) >= DELTA_V_MAX_MS:
                return True
    return False


# --- vent ---------------------------------------------------------------------


def _interpoler_archive(heures: Sequence[HeureArchive], t: datetime) -> HeureArchive | None:
    """L'archive à l'instant `t`, interpolée entre les deux heures encadrantes.

    Hors de la série (archive vide, sortie à cheval sur deux jours dont on n'a
    qu'un) : `None`. On ne prolonge pas la dernière heure connue — ce serait
    affirmer sans mesure.
    """
    if not heures:
        return None
    ordonnees = sorted(heures, key=lambda h: h.t)
    if t < ordonnees[0].t or t > ordonnees[-1].t:
        return None
    for avant, apres in zip(ordonnees[:-1], ordonnees[1:], strict=True):
        if avant.t <= t <= apres.t:
            duree = (apres.t - avant.t).total_seconds()
            f = (t - avant.t).total_seconds() / duree if duree > 0 else 0.0
            return HeureArchive(
                t=t,
                vent_kmh=_lineaire(avant.vent_kmh, apres.vent_kmh, f),
                vent_depuis_deg=_angulaire(avant.vent_depuis_deg, apres.vent_depuis_deg, f),
                temp_c=_lineaire(avant.temp_c, apres.temp_c, f),
                pression_hpa=_lineaire(avant.pression_hpa, apres.pression_hpa, f),
            )
    return None


def _vent_de_face(heure: HeureArchive | None, cap: float | None) -> float | None:
    """Composante de face du vent, en m/s (positive de face, négative de dos).

    `vent_depuis_deg` est la direction **d'où** vient le vent. Le vent est de
    face quand il vient de là où l'on va : la composante vaut donc
    `v · cos(direction_d_où − cap)`.
    """
    if heure is None or cap is None:
        return None
    if heure.vent_kmh is None or heure.vent_depuis_deg is None:
        return None
    return (heure.vent_kmh / 3.6) * math.cos(math.radians(heure.vent_depuis_deg - cap))


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
    if x == 0.0 and y == 0.0:
        return a
    return math.degrees(math.atan2(y, x)) % 360.0


# --- ajustement ---------------------------------------------------------------


@dataclass
class Ajustement:
    """Le couple (CdA, Crr) qui explique le mieux les échantillons, et ce qu'il vaut."""

    cda_m2: float
    crr: float
    masse_totale_kg: float
    n_echantillons: int
    rmse_w: float
    mae_w: float
    cda_incertitude: float | None = None
    crr_incertitude: float | None = None
    rho_moyen: float = RHO_DEFAUT
    bornes_atteintes: tuple[str, ...] = ()
    avertissements: tuple[str, ...] = ()

    @property
    def force_reference_n(self) -> float:
        """Force totale à vaincre à `V_REFERENCE_KMH` sur le plat sans vent, en newtons.

        C'est la grandeur que l'ajustement contraint le mieux : CdA et Crr
        peuvent se compenser l'un l'autre, leur somme à l'allure courante non.
        À citer chaque fois qu'une borne est atteinte.
        """
        return force_resistante_n(self.parametres())

    def parametres(self, *, rho: float | None = None) -> Parametres:
        """Les `Parametres` correspondants, avec la masse volumique moyenne des échantillons."""
        return Parametres(
            masse_totale_kg=self.masse_totale_kg,
            cda_m2=self.cda_m2,
            crr=self.crr,
            rho=rho if rho is not None else self.rho_moyen,
        )


def force_resistante_n(p: Parametres, v_kmh: float = V_REFERENCE_KMH) -> float:
    """Force totale à vaincre sur le plat sans vent, en newtons, à `v_kmh`."""
    v = v_kmh / 3.6
    return puissance_requise(v, 0.0, 0.0, p) * p.rendement / v


def calibrer(
    echantillons: Sequence[Echantillon],
    *,
    masse_totale_kg: float,
    cda_init: float = 0.32,
    crr_init: float = 0.005,
) -> Ajustement:
    """Moindres carrés sur (CdA, Crr), bornés, à partir des échantillons retenus.

    **Le modèle est linéaire en CdA et en Crr** : à vitesse, pente et vent
    donnés, la puissance vaut `a·CdA + b·Crr + c`, où a, b et c ne dépendent
    d'aucun des deux. Le contrat de sprint prévoyait une grille grossière puis
    un affinage ; la solution exacte existe, on la prend — et les coefficients
    a, b, c sont obtenus en appelant `puissance_requise` avec des paramètres
    unitaires, de sorte que la calibration ne puisse pas diverger de la
    physique du modèle. Écart au contrat assumé et signalé.

    Hors des bornes, le minimum d'une forme quadratique convexe sur un pavé
    est sur le bord : on résout alors les quatre arêtes et on garde la
    meilleure. `cda_init` et `crr_init` ne servent donc qu'à nommer un point
    de départ dans le rapport (ils n'influent pas sur le résultat) et à
    répondre quand le problème est dégénéré.

    **L'incertitude rendue est optimiste** : elle suppose des résidus
    indépendants, alors que deux tronçons de 200 m voisins se ressemblent.
    Elle dit l'ordre de grandeur de ce que les données contraignent, pas
    l'erreur vraie.
    """
    retenus = [e for e in echantillons if e.retenu]
    if len(retenus) < ECHANTILLONS_MINIMUM:
        raise ErreurUtilisateur(
            f"calibration : {len(retenus)} échantillon(s) retenu(s), "
            f"au moins {ECHANTILLONS_MINIMUM} sont nécessaires pour ajuster CdA et Crr"
        )
    if not math.isfinite(masse_totale_kg) or masse_totale_kg <= 0:
        raise ErreurUtilisateur(
            f"calibration : masse totale {masse_totale_kg!r} — une masse positive est attendue"
        )

    a, b, c, y = _matrices(retenus, masse_totale_kg)
    matrice = np.column_stack((a, b))
    reste = y - c
    avertissements: list[str] = []

    solution, rang = _moindres_carres(matrice, reste)
    if rang < 2:
        avertissements.append(
            "les échantillons ne séparent pas CdA de Crr (trop peu de variété de "
            "vitesse ou de pente) : la solution est celle de norme minimale"
        )
        solution = np.array([cda_init, crr_init], dtype=float)
    cda, crr, bornes = _borner(matrice, reste, solution)
    if bornes:
        avertissements.append(
            "une borne est atteinte : CdA et Crr ne sont plus séparés par ces "
            "données, seule leur résistance combinée à l'allure courante est mesurée"
        )

    residus = matrice @ np.array([cda, crr]) - reste
    n = len(retenus)
    rmse = float(np.sqrt(np.mean(residus**2)))
    mae = float(np.mean(np.abs(residus)))
    incertitudes = _incertitudes(matrice, residus, n)
    return Ajustement(
        cda_m2=float(cda),
        crr=float(crr),
        masse_totale_kg=float(masse_totale_kg),
        n_echantillons=n,
        rmse_w=rmse,
        mae_w=mae,
        cda_incertitude=incertitudes[0],
        crr_incertitude=incertitudes[1],
        rho_moyen=float(np.mean([e.rho for e in retenus])),
        bornes_atteintes=bornes,
        avertissements=tuple(avertissements),
    )


def _matrices(
    retenus: Sequence[Echantillon], masse_totale_kg: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Les colonnes (a, b, c) du modèle linéaire et le vecteur des puissances mesurées.

    a, b et c sortent de `puissance_requise` elle-même, avec des paramètres
    unitaires : `a = P(CdA=1, Crr=0) − P(0, 0)`, `b = P(0, Crr=1) − P(0, 0)`,
    `c = P(0, 0)` (la part gravité + rendement). Aucune formule n'est donc
    recopiée ici.
    """
    a = np.empty(len(retenus))
    b = np.empty(len(retenus))
    c = np.empty(len(retenus))
    y = np.empty(len(retenus))
    for i, e in enumerate(retenus):
        base = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=0.0, rho=e.rho)
        seul_cda = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=1.0, crr=0.0, rho=e.rho)
        seul_crr = Parametres(masse_totale_kg=masse_totale_kg, cda_m2=0.0, crr=1.0, rho=e.rho)
        c[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, base)
        a[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_cda) - c[i]
        b[i] = puissance_requise(e.v_ms, e.pente, e.vent_face_ms, seul_crr) - c[i]
        y[i] = e.puissance_w
    return a, b, c, y


def _moindres_carres(matrice: np.ndarray, reste: np.ndarray) -> tuple[np.ndarray, int]:
    solution, _, rang, _ = np.linalg.lstsq(matrice, reste, rcond=None)
    return solution, int(rang)


def _borner(
    matrice: np.ndarray, reste: np.ndarray, solution: np.ndarray
) -> tuple[float, float, tuple[str, ...]]:
    """Ramène la solution dans le pavé des bornes, en minimisant vraiment l'écart.

    Écrêter les deux coordonnées séparément ne donne pas le minimum du pavé :
    si CdA sort par le haut, le Crr optimal **à CdA borné** n'est plus celui
    de la solution libre. On résout donc chaque arête à une inconnue et on
    garde la meilleure des candidates.
    """
    cda, crr = float(solution[0]), float(solution[1])
    if CDA_MIN <= cda <= CDA_MAX and CRR_MIN <= crr <= CRR_MAX:
        return (cda, crr, ())

    candidates: list[tuple[float, float]] = []
    for valeur in (CDA_MIN, CDA_MAX):
        candidates.append((valeur, _arete(matrice, reste, fixe=0, valeur=valeur)))
    for valeur in (CRR_MIN, CRR_MAX):
        candidates.append((_arete(matrice, reste, fixe=1, valeur=valeur), valeur))
    candidates += [
        (x, z) for x in (CDA_MIN, CDA_MAX) for z in (CRR_MIN, CRR_MAX)
    ]
    valides = [
        (x, z)
        for x, z in candidates
        if CDA_MIN - 1e-12 <= x <= CDA_MAX + 1e-12 and CRR_MIN - 1e-12 <= z <= CRR_MAX + 1e-12
    ]
    meilleure = min(
        valides, key=lambda xz: float(np.sum((matrice @ np.array(xz) - reste) ** 2))
    )
    cda, crr = meilleure
    bornes = []
    if math.isclose(cda, CDA_MIN) or math.isclose(cda, CDA_MAX):
        bornes.append(f"CdA = {cda:.2f}")
    if math.isclose(crr, CRR_MIN) or math.isclose(crr, CRR_MAX):
        bornes.append(f"Crr = {crr:.4f}")
    return (cda, crr, tuple(bornes))


def _arete(matrice: np.ndarray, reste: np.ndarray, *, fixe: int, valeur: float) -> float:
    """Optimum de l'inconnue restante quand l'autre est fixée à `valeur`, écrêté à ses bornes."""
    libre = 1 - fixe
    colonne = matrice[:, libre]
    cible = reste - matrice[:, fixe] * valeur
    denominateur = float(colonne @ colonne)
    if denominateur <= 0:
        return CRR_MIN if libre == 1 else CDA_MIN
    x = float((colonne @ cible) / denominateur)
    mini, maxi = (CDA_MIN, CDA_MAX) if libre == 0 else (CRR_MIN, CRR_MAX)
    return min(max(x, mini), maxi)


def _incertitudes(
    matrice: np.ndarray, residus: np.ndarray, n: int
) -> tuple[float | None, float | None]:
    """Écarts-types des deux paramètres, `σ²·(AᵀA)⁻¹`. `None` si la matrice est singulière."""
    if n <= 2:
        return (None, None)
    variance = float(residus @ residus) / (n - 2)
    try:
        covariance = np.linalg.inv(matrice.T @ matrice) * variance
    except np.linalg.LinAlgError:
        return (None, None)
    diagonale = np.diag(covariance)
    if np.any(diagonale < 0):
        return (None, None)
    racines = np.sqrt(diagonale)
    return (float(racines[0]), float(racines[1]))


# --- validation ---------------------------------------------------------------


@dataclass
class ErreurSortie:
    """L'écart entre le temps simulé et le temps en mouvement réel d'une sortie."""

    jour: date | None
    nom: str
    distance_m: float
    temps_reel_s: float
    temps_simule_s: float

    @property
    def erreur_relative(self) -> float:
        """Positive = le modèle prédit **plus lent** que la réalité."""
        return (self.temps_simule_s - self.temps_reel_s) / self.temps_reel_s


@dataclass
class Validation:
    """Ce que vaut le modèle sur des sorties qu'il n'a pas vues."""

    sorties: list[ErreurSortie] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.sorties)

    @property
    def erreurs(self) -> list[float]:
        return [s.erreur_relative for s in self.sorties]

    @property
    def mae(self) -> float | None:
        """Erreur absolue moyenne, en fraction (0,06 = 6 %)."""
        return statistics.fmean(abs(e) for e in self.erreurs) if self.sorties else None

    @property
    def mediane(self) -> float | None:
        return statistics.median(abs(e) for e in self.erreurs) if self.sorties else None

    @property
    def biais(self) -> float | None:
        """Erreur **signée** moyenne : dit dans quel sens le modèle se trompe."""
        return statistics.fmean(self.erreurs) if self.sorties else None

    @property
    def pire(self) -> ErreurSortie | None:
        return max(self.sorties, key=lambda s: abs(s.erreur_relative), default=None)


def valider(
    sorties_test: Sequence[tuple[Activite, list[HeureArchive]]], p: Parametres
) -> Validation:
    """Rejoue chaque sortie à sa puissance moyenne et son vent réels, et compare les temps.

    La puissance injectée est la **moyenne en mouvement** de la sortie, pas son
    profil détaillé. Ce n'est pas de la paresse, c'est une mesure : rejouer le
    profil mesuré par tranches de 100 m donne un temps catastrophique, parce
    que le modèle ignore l'inertie. Là où le cycliste traverse cent mètres à
    zéro watt sur son élan à 35 km/h, un modèle d'équilibre répond « zéro watt,
    donc à l'arrêt » et y perd des minutes.

    Mesuré sur les 100 sorties RCR réelles du mainteneur, avec les mêmes
    paramètres (CdA 0,32, Crr 0,005, 100 kg) :

    | puissance injectée        | MAE   | médiane | biais  |
    |---------------------------|-------|---------|--------|
    | moyenne en mouvement      | 5,0 % | 4,0 %   | −1,9 % |
    | profil mesuré par 100 m   | 15,7 %| 14,1 %  | +15,0 %|

    C'est aussi l'usage visé : on demande au modèle « combien de temps cette
    boucle, à 200 W ? », pas « rejoue-moi une sortie déjà faite ».

    Le temps de référence est le temps **en mouvement** (`temps_mouvement_s`),
    le seul que la simulation prétende prédire.
    """
    validation = Validation()
    for activite, vent in sorties_test:
        mesure = simuler_sortie(activite, vent, p)
        if mesure is None:
            continue
        simulation, reel = mesure
        validation.sorties.append(
            ErreurSortie(
                jour=activite.debut.date() if activite.debut else None,
                nom=str(activite.meta.get("nom") or activite.fichier or ""),
                distance_m=simulation.distance_m,
                temps_reel_s=reel,
                temps_simule_s=simulation.temps_s,
            )
        )
    return validation


def simuler_sortie(
    activite: Activite, vent: Sequence[HeureArchive], p: Parametres
) -> tuple[Simulation, float] | None:
    """(simulation, temps en mouvement réel) d'une sortie, ou `None` si elle est inexploitable."""
    trace = trace_depuis_activite(activite)
    if trace is None:
        return None
    reel = temps_mouvement_s(activite)
    if reel is None or reel <= 0:
        return None
    puissance = puissance_moyenne_en_mouvement(activite)
    if puissance is None or puissance <= 0:
        return None
    simulation = simuler(trace, puissance, p, vent=vent_le_long(activite, vent))
    return (simulation, reel)


def puissance_moyenne_en_mouvement(activite: Activite) -> float | None:
    """Puissance moyenne pondérée par la durée, **hors arrêts**. `None` sans puissance.

    Les zéros d'un feu rouge ne doivent pas entrer dans la moyenne : ils
    abaisseraient la puissance de la sortie sans que le cycliste ait roulé un
    mètre plus lentement.
    """
    points = [p for p in activite.points if p.t is not None]
    somme = duree = 0.0
    for a, b in zip(points[:-1], points[1:], strict=True):
        if a.puissance_w is None:
            continue
        dt = (b.t - a.t).total_seconds()
        if not (0 < dt <= 60):
            continue
        if a.vitesse_ms is not None and float(a.vitesse_ms) < SEUIL_ARRET_MS:
            continue
        somme += float(a.puissance_w) * dt
        duree += dt
    if duree > 0:
        return somme / duree
    return float(activite.puissance_moy_w) if activite.puissance_moy_w else None


def trace_depuis_activite(activite: Activite) -> Trace | None:
    """Le parcours d'une sortie enregistrée, vu comme un `Trace` (sans segments OSM)."""
    points = [
        PointTrace(
            lat=float(p.lat),
            lon=float(p.lon),
            alt_m=float(p.alt_m) if p.alt_m is not None else None,
            dist_m=float(p.dist_m) if p.dist_m is not None else 0.0,
        )
        for p in activite.points
        if p.lat is not None and p.lon is not None
    ]
    if len(points) < 2:
        return None
    return Trace(
        nom=str(activite.meta.get("nom") or "sortie"),
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=activite.denivele_m,
        temps_moteur_s=None,
    )


def temps_mouvement_s(activite: Activite) -> float | None:
    """Le temps passé à rouler, arrêts déduits, en secondes.

    Somme des intervalles dont le point de départ est au-dessus de
    `SEUIL_ARRET_MS`. Les intervalles de plus d'une minute (compteur en pause,
    trou d'enregistrement) sont écartés : ils ne représentent pas du
    mouvement.

    Sans vitesse par point, on se rabat sur `duree_mouvement_s` de la source,
    puis sur la durée écoulée — en sachant que cette dernière **inclut les
    arrêts** et rendra donc le modèle trop rapide.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) >= 2 and any(p.vitesse_ms is not None for p in points):
        total = 0.0
        for a, b in zip(points[:-1], points[1:], strict=True):
            dt = (b.t - a.t).total_seconds()
            if not (0 < dt <= 60):
                continue
            if a.vitesse_ms is not None and float(a.vitesse_ms) >= SEUIL_ARRET_MS:
                total += dt
        if total > 0:
            return total
    if activite.duree_mouvement_s:
        return float(activite.duree_mouvement_s)
    return float(activite.duree_s) if activite.duree_s else None


def vent_le_long(
    activite: Activite, vent: Sequence[HeureArchive]
) -> Callable[[float, float], float] | None:
    """`vent(dist_m, cap_deg)` pour la simulation, daté par l'heure **réelle** de passage.

    Utiliser l'heure réelle plutôt que l'avancement simulé évite d'avoir à
    itérer ; l'erreur commise est du second ordre (le vent d'archive change à
    l'heure, une sortie de trois heures ne se décale que de quelques minutes).
    """
    if not vent:
        return None
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2:
        return None
    distances = _distances_points(points)
    instants = [p.t for p in points]

    def a_l_heure(dist_m: float) -> datetime:
        i = min(range(len(distances)), key=lambda k: abs(distances[k] - dist_m))
        return instants[i]

    def face(dist_m: float, cap: float) -> float:
        heure = _interpoler_archive(vent, a_l_heure(dist_m))
        valeur = _vent_de_face(heure, cap)
        return valeur if valeur is not None else 0.0

    return face


# --- détection des sorties en groupe -----------------------------------------


def detecter_groupe(
    activite: Activite,
    p: Parametres,
    vent: list[HeureArchive],
    *,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> tuple[bool, float]:
    """(en groupe ?, part de la distance anormalement rapide).

    Pour chaque tronçon retenu, on demande au modèle la vitesse que la
    puissance mesurée justifie, compte tenu de la pente et du vent. Rouler
    durablement plus vite que ça, c'est rouler dans une roue : le peloton
    fait gagner 20 à 30 % de traînée, et un tel gain attribué au vélo
    fausserait son CdA pour toutes les autres sorties.

    Le seuil est celui du contrat : résidu > +8 % sur plus de la moitié de la
    distance **retenue** (les tronçons écartés — arrêts, accélérations — ne
    disent rien d'un équilibre).
    """
    echantillons = [
        e
        for e in echantillonner(activite, vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh)
        if e.retenu
    ]
    distance = sum(e.longueur_m for e in echantillons)
    if distance <= 0:
        return (False, 0.0)
    rapide = 0.0
    for e in echantillons:
        attendue = vitesse_regime(e.puissance_w, e.pente, e.vent_face_ms, p)
        if attendue > 0 and (e.v_ms - attendue) / attendue > SEUIL_RESIDU_GROUPE:
            rapide += e.longueur_m
    part = rapide / distance
    return (part > PART_DISTANCE_GROUPE, part)


# --- choix des sorties --------------------------------------------------------


def masse_totale_kg(config: Config, velo: Velo) -> float:
    """Cycliste + vélo. Un vélo sans masse déclarée pèse `MASSE_VELO_DEFAUT_KG`.

    Le mainteneur l'a dit : « une masse approximative par vélo suffit, 1 kg
    sur 100 kg fait 1 % en montée et rien sur le plat ».
    """
    return config.cycliste.masse_kg + (
        velo.masse_kg if velo.masse_kg is not None else MASSE_VELO_DEFAUT_KG
    )


def motif_exclusion(entree: EntreeCache, config: Config, velo: Velo) -> str | None:
    """Pourquoi cette sortie n'est pas calibrable, ou `None` si elle l'est.

    Rendre le motif, et pas seulement un booléen, permet à la commande de dire
    « 102 calibrables, 8 trop courtes, 2 en groupe » au lieu d'un nombre nu.
    """
    if not est_sport_velo(entree.sport):
        return "pas du vélo"
    if en_interieur(entree):
        return "home-trainer"
    if rattacher_velo(entree, config) != velo.nom:
        return "autre vélo"
    if entree.puissance_moy_w is None:
        return "sans puissance"
    if (entree.distance_m or 0.0) < DISTANCE_MINIMALE_M:
        return "moins de 20 km"
    nom = str(entree.meta.get("nom") or "").casefold()
    for mot in config.calibration.mots_groupe:
        if mot and mot in nom:
            return f"nom « {mot} »"
    return None


def sorties_calibrables(
    cache: Cache, config: Config, velo: Velo, *, depuis: date | None = None
) -> list[EntreeCache]:
    """Les sorties utilisables pour calibrer ce vélo, de la plus ancienne à la plus récente."""
    depuis = depuis if depuis is not None else config.historique_depuis
    retenues = [
        e for e in cache.lister(depuis=depuis) if motif_exclusion(e, config, velo) is None
    ]
    return sorted(retenues, key=lambda e: (e.debut or _JAMAIS, e.identifiant))


# --- les deux passes ----------------------------------------------------------


@dataclass
class SortieCalibration:
    """Une sortie prête à calibrer : son enregistrement et l'archive météo du jour."""

    activite: Activite
    vent: list[HeureArchive] = field(default_factory=list)
    identifiant: str = ""

    @property
    def jour(self) -> date | None:
        return self.activite.debut.date() if self.activite.debut else None

    @property
    def nom(self) -> str:
        return str(self.activite.meta.get("nom") or self.activite.fichier or self.identifiant)


@dataclass
class RapportCalibration:
    """Tout ce qu'une calibration a trouvé, mesuré et écarté — de quoi la juger."""

    velo: str
    ajustement: Ajustement
    validation: Validation
    passe1: Ajustement
    n_apprentissage: int
    n_validation: int
    groupes: list[tuple[str, float]] = field(default_factory=list)
    """Sorties d'apprentissage écartées au résidu : (nom, part de la distance
    anormalement rapide)."""
    groupes_en_validation: list[tuple[str, float]] = field(default_factory=list)
    """Sorties de **test** que le même critère désigne. Elles restent dans la
    validation — ce sont de vraies sorties — mais il faut savoir qu'elles y
    sont quand on lit l'erreur."""
    echantillons: int = 0
    echantillons_retenus: int = 0
    motifs: dict[str, int] = field(default_factory=dict)
    echantillons_sans_vent: int = 0


def partager(
    sorties: Sequence[SortieCalibration], part_validation: float
) -> tuple[list[SortieCalibration], list[SortieCalibration]]:
    """(apprentissage, validation) : les plus récentes en validation (contrat §3).

    Partager par date et non au hasard est le seul partage honnête ici : un
    tirage aléatoire mettrait dans le test des sorties voisines, faites le même
    mois avec le même matériel, et flatterait le modèle.
    """
    ordonnees = sorted(sorties, key=lambda s: (s.jour or date.min, s.nom))
    if len(ordonnees) < 2:
        return (list(ordonnees), [])
    n_test = max(1, min(len(ordonnees) - 1, round(len(ordonnees) * part_validation)))
    coupe = len(ordonnees) - n_test
    return (ordonnees[:coupe], ordonnees[coupe:])


def calibrer_en_deux_passes(
    sorties: Sequence[SortieCalibration],
    *,
    velo: str,
    masse_totale_kg: float,
    part_validation: float = 0.25,
    ftp_w: float = 250.0,
    vitesse_min_kmh: float = 8.0,
) -> RapportCalibration:
    """Calibre, repère les sorties en groupe au résidu, recalibre sans elles, valide.

    Une seule itération, comme décidé le 13/09 : « calibrer d'abord sur les
    sorties sûres, puis utiliser le modèle obtenu pour repérer les autres et
    les écarter ; itérer une fois ».
    """
    if not sorties:
        raise ErreurUtilisateur(f"calibration : aucune sortie exploitable pour le vélo {velo}")
    apprentissage, validation_sorties = partager(sorties, part_validation)

    par_sortie = {
        s.identifiant or s.nom: echantillonner(
            s.activite, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        for s in apprentissage
    }
    tous = [e for liste in par_sortie.values() for e in liste]
    motifs: dict[str, int] = {}
    for e in tous:
        if not e.retenu:
            motifs[e.motif] = motifs.get(e.motif, 0) + 1

    passe1 = calibrer(tous, masse_totale_kg=masse_totale_kg)
    p1 = passe1.parametres()

    groupes: list[tuple[str, float]] = []
    gardees: list[SortieCalibration] = []
    for s in apprentissage:
        en_groupe, part = detecter_groupe(
            s.activite, p1, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        if en_groupe:
            groupes.append((s.nom, part))
        else:
            gardees.append(s)

    restants = [e for s in gardees for e in par_sortie[s.identifiant or s.nom]]
    passe2 = calibrer(restants, masse_totale_kg=masse_totale_kg) if gardees else passe1
    p2 = passe2.parametres()

    validation = valider([(s.activite, s.vent) for s in validation_sorties], p2)
    groupes_test = []
    for s in validation_sorties:
        en_groupe, part = detecter_groupe(
            s.activite, p2, s.vent, ftp_w=ftp_w, vitesse_min_kmh=vitesse_min_kmh
        )
        if en_groupe:
            groupes_test.append((s.nom, part))

    return RapportCalibration(
        velo=velo,
        ajustement=passe2,
        validation=validation,
        passe1=passe1,
        n_apprentissage=len(gardees),
        n_validation=len(validation_sorties),
        groupes=groupes,
        groupes_en_validation=groupes_test,
        echantillons=len(tous),
        echantillons_retenus=sum(1 for e in tous if e.retenu),
        motifs=dict(sorted(motifs.items(), key=lambda kv: (-kv[1], kv[0]))),
        echantillons_sans_vent=sum(1 for e in tous if e.retenu and not e.vent_connu),
    )

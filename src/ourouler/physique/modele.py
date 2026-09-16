"""Modèle physique : quelle puissance pour quelle vitesse, et l'inverse.

Le bilan est celui de Martin & al. (1998), réduit à ce qui compte hors
montagne et **sans folie** (décision du mainteneur, 13/09) : roulement,
gravité, aérodynamique, rendement de transmission. Ni inertie, ni frottement
des roulements de roue, ni résistance du vent de travers.

    P = (1/η) · [ (Crr·m·g·cos θ + m·g·sin θ)·v + ½·ρ·CdA·v_air·|v_air|·v ]

avec θ = atan(pente) et `v_air = v + v_vent_face` (vent de face compté
positif). Le contrat de sprint §3 écrit ce dernier terme `(v + v_vent_face)²` ;
c'est la même chose tant que l'air vient de face, mais un vent arrière plus
rapide que le cycliste (`v_air < 0`) rendait alors une traînée **positive**,
c'est-à-dire un vent de dos qui freine. `v_air·|v_air|` garde le signe : la
poussée est une puissance négative. Écart au contrat assumé et signalé.

Le vent que ce bilan attend est celui **à hauteur de cycliste**, pas celui
des bulletins : `vent_au_cycliste` fait la conversion, une fois pour toutes,
pour l'archive comme pour la prévision.

Deux grandeurs sortent de ce module :

- `puissance_requise(v)` — directe, exacte ;
- `vitesse_regime(P)` — son inverse, par bissection sur [0, 30] m/s.

Et une simulation de parcours, `simuler`, qui donne un **temps en mouvement** :
les arrêts (feux, stops, ravitaillement, photo) ne sont pas modélisés. Sur
route ouverte, c'est la principale raison pour laquelle un temps simulé est
plus court qu'un temps réel.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ourouler.activites.modele import moyenne_glissante
from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m
from ourouler.erreurs import ErreurUtilisateur

#: Accélération de la pesanteur (valeur normale, CGPM 1901).
G = 9.80665

#: Constante spécifique de l'air sec, en J/(kg·K).
R_AIR = 287.058

#: Masse volumique de l'air par défaut : 15 °C à 1013,25 hPa, au niveau de la mer.
RHO_DEFAUT = 1.226

#: Rendement de transmission par défaut (chaîne propre, valeur de Martin & al.).
RENDEMENT_DEFAUT = 0.976

#: Borne haute de la bissection, en m/s (108 km/h : au-delà, ce n'est plus du vélo).
V_MAX_BISSECTION_MS = 30.0

#: Vitesse plafond en descente, en km/h : le cycliste freine, le modèle ne le sait pas.
V_MAX_DESCENTE_KMH = 60.0

#: Pas de la simulation, en mètres.
PAS_M = 100.0

#: Nombre de pas de la moyenne glissante qui lisse l'altitude (7 pas = 700 m).
#: L'altimètre barométrique d'un compteur bruite de quelques dizaines de
#: centimètres ; sur 100 m, cela vaut des pentes fantômes de plusieurs pour
#: cent. On lisse avant de dériver.
FENETRE_ALTITUDE = 7

#: Sous cette vitesse, le modèle n'a plus de sens (le cycliste met pied à
#: terre). Les pas concernés sont comptés dans `Simulation.pas_bloques` et
#: leur temps est calculé à cette vitesse plancher : c'est un plancher
#: affiché, pas une mesure.
V_MIN_MS = 0.5

#: Facteur qui ramène un vent **météo** (mesuré ou prévu à 10 m du sol) au vent
#: que le cycliste subit réellement, à hauteur de buste.
#:
#: Le profil de vent en couche limite est logarithmique :
#: `v(z) = v* / k · ln(z / z₀)`, donc `v(z₁)/v(z₂) = ln(z₁/z₀) / ln(z₂/z₀)`.
#: Avec `z = 1,5 m` (buste d'un cycliste sur la route), `z₀ = 0,1 m`
#: (longueur de rugosité d'un bocage : haies, arbres, cultures hautes) et la
#: hauteur de référence de 10 m des modèles météo :
#:
#:     ln(1,5 / 0,1) / ln(10 / 0,1) = ln(15) / ln(100) ≈ 0,588
#:
#: soit **0,6** en chiffre rond. Ce n'est pas un réglage libre : c'est la
#: conversion d'une grandeur météo en la grandeur physique dont le modèle a
#: besoin. Elle s'applique des deux côtés — archive (calibration) et
#: prévision (simulation) — sans quoi le modèle serait calibré sur un vent et
#: utilisé sur un autre.
FACTEUR_VENT_HAUTEUR = 0.6

#: Tolérance de la bissection, en m/s. 10⁻¹⁰ m/s rend `puissance_requise(
#: vitesse_regime(P))` égale à P à bien mieux que 0,1 W sur toute la plage utile.
TOLERANCE_MS = 1e-10

#: Garde-fou d'itérations de la bissection. 30/2⁵⁰ ≈ 3·10⁻¹⁴ : la tolérance
#: est atteinte bien avant, cette borne n'existe que pour ne jamais boucler.
MAX_ITERATIONS = 200


@dataclass(frozen=True)
class Parametres:
    """Ce qu'il faut savoir du couple cycliste + vélo pour prédire une vitesse.

    `masse_totale_kg` est la masse **en mouvement** : cycliste habillé, vélo,
    bidons. `cda_m2` (m²) et `crr` (sans dimension) sortent de la calibration.
    """

    masse_totale_kg: float
    cda_m2: float
    crr: float
    rendement: float = RENDEMENT_DEFAUT
    rho: float = RHO_DEFAUT


@dataclass
class Simulation:
    """Le résultat de `simuler` : un temps **en mouvement**, pas un temps de sortie.

    `par_segment` donne, pour chaque pas : (distance cumulée en fin de pas,
    pente, vitesse en km/h, temps du pas en secondes).
    """

    temps_s: float
    distance_m: float
    vitesse_moy_kmh: float
    par_segment: list[tuple[float, float, float, float]] = field(default_factory=list)
    pas_plafonnes: int = 0
    """Pas où la vitesse a été ramenée à `V_MAX_DESCENTE_KMH` : le modèle
    descendait plus vite que ce qu'un humain accepte."""
    pas_bloques: int = 0
    """Pas où la vitesse calculée était sous `V_MIN_MS` (puissance nulle ou
    quasi nulle) : le temps de ces pas est un plancher, pas une mesure."""


def vent_au_cycliste(vent_10m: float) -> float:
    """Le vent vu par le cycliste, à partir d'un vent météo donné à 10 m.

    Une seule multiplication, et **une seule constante** :
    `FACTEUR_VENT_HAUTEUR`. La calibration passe par cette fonction ;
    `seance.vent.ChampVent` applique la même constante lui-même, parce qu'il
    expose un `facteur_hauteur` injectable que ses tests font varier. Les deux
    ne peuvent donc pas diverger numériquement, mais ce ne sont pas les mêmes
    lignes — la version antérieure de cette docstring disait « un seul
    endroit », et c'est devenu faux avec le lot L5.1.

    Le signe est conservé : un vent de dos (compté négatif en composante de
    face) reste un vent de dos. Une valeur non finie est rendue telle quelle —
    c'est à l'appelant de décider qu'un vent inconnu vaut zéro, pas à cette
    conversion de le masquer.
    """
    return vent_10m * FACTEUR_VENT_HAUTEUR


def masse_volumique_air(temp_c: float | None, pression_hpa: float | None) -> float:
    """ρ = p / (R·T), en kg/m³. Rend `RHO_DEFAUT` si l'une des deux manque.

    Entre 0 °C et 30 °C, ρ varie de 1,29 à 1,16 : 10 % sur la traînée, soit
    plusieurs minutes sur une sortie de trois heures. Cela vaut l'appel à
    l'archive.
    """
    if temp_c is None or pression_hpa is None:
        return RHO_DEFAUT
    if not (math.isfinite(temp_c) and math.isfinite(pression_hpa)):
        return RHO_DEFAUT
    kelvin = temp_c + 273.15
    if kelvin <= 0 or pression_hpa <= 0:
        return RHO_DEFAUT
    return (pression_hpa * 100.0) / (R_AIR * kelvin)


def puissance_requise(v_ms: float, pente: float, vent_face_ms: float, p: Parametres) -> float:
    """Puissance mécanique au pédalier, en watts, pour tenir `v_ms`.

    `pente` est une tangente (0,05 = 5 %), `vent_face_ms` le vent de face
    compté positif (un vent de dos est négatif). Le résultat peut être
    négatif : en descente, il faudrait freiner.

    Une entrée non finie est **refusée**. Rendre `nan` serait pire que lever :
    le NaN traverse les additions sans bruit, ressort en « temps estimé » vide
    ou en tri arbitraire, et personne ne sait d'où il vient.
    """
    _finis(v_ms=v_ms, pente=pente, vent_face_ms=vent_face_ms)
    theta = math.atan(pente)
    v_air = v_ms + vent_face_ms
    resistance = (
        p.crr * p.masse_totale_kg * G * math.cos(theta) + p.masse_totale_kg * G * math.sin(theta)
    )
    trainee = 0.5 * p.rho * p.cda_m2 * v_air * abs(v_air)
    return (resistance * v_ms + trainee * v_ms) / p.rendement


def _finis(**valeurs: float) -> None:
    """Refuse toute entrée non finie, en nommant le paramètre fautif."""
    fautifs = {nom: v for nom, v in valeurs.items() if not math.isfinite(v)}
    if fautifs:
        detail = ", ".join(f"{nom}={v!r}" for nom, v in fautifs.items())
        raise ErreurUtilisateur(f"modèle physique : {detail} — des nombres finis sont attendus")


def vitesse_regime(puissance_w: float, pente: float, vent_face_ms: float, p: Parametres) -> float:
    """Vitesse d'équilibre, en m/s, pour une puissance tenue — l'inverse de `puissance_requise`.

    Bissection sur [0, `V_MAX_BISSECTION_MS`]. Sur le plat et en montée,
    `puissance_requise` est strictement croissante en v et la racine est
    unique. En descente elle décroît d'abord (la gravité fournit), passe par
    un minimum négatif, puis croît : pour une puissance demandée ≥ 0, il n'y
    a là encore qu'une seule racine, celle qui suit le minimum — c'est la
    vitesse d'équilibre, et la bissection y va d'elle-même puisque
    `f(0) = −P ≤ 0`.

    Puissance nulle sur le plat → 0 m/s, sans division par zéro. Puissance
    nulle en descente → la vitesse limite de la descente. Puissance négative
    → 0 m/s : le modèle ne sait pas freiner.
    """
    # Puissance **nulle** n'est pas un cas à part : sur le plat la bissection
    # rend 0 m/s, en descente elle rend la vitesse limite. Seules une
    # puissance négative (le modèle ne sait pas freiner) et une valeur non
    # finie sont refusées d'entrée.
    if not math.isfinite(puissance_w) or puissance_w < 0:
        return 0.0
    _finis(pente=pente, vent_face_ms=vent_face_ms)

    def ecart(v: float) -> float:
        return puissance_requise(v, pente, vent_face_ms, p) - puissance_w

    haut = V_MAX_BISSECTION_MS
    if ecart(haut) <= 0:
        # Plus de puissance que ce que 108 km/h demande : on ne va pas au-delà.
        return haut
    bas = 0.0
    if ecart(bas) > 0:
        # Ne peut arriver qu'avec une puissance négative, déjà écartée.
        return 0.0
    for _ in range(MAX_ITERATIONS):
        if haut - bas <= TOLERANCE_MS:
            break
        milieu = (bas + haut) / 2
        if ecart(milieu) > 0:
            haut = milieu
        else:
            bas = milieu
    return (bas + haut) / 2


# --- simulation d'un parcours -------------------------------------------------


def simuler(
    trace: Trace,
    puissance_w: float | Callable[[float], float],
    p: Parametres,
    vent: Callable[[float, float], float] | None = None,
) -> Simulation:
    """Le temps **en mouvement** sur `trace`, par pas de `PAS_M` mètres.

    `puissance_w` est une constante ou une fonction de la distance cumulée
    (en mètres) — c'est ainsi qu'on rejoue le profil de puissance d'une
    sortie réelle. `vent(dist_m, cap_deg)` rend le vent de face en m/s au
    point courant ; sans lui, air calme.

    **Ce temps ignore les arrêts** : feux, stops, ravitaillements, photos,
    crevaisons. Sur route ouverte il est donc systématiquement plus court
    qu'un temps de sortie mesuré montre en montre, et l'écart n'est pas une
    erreur du modèle.

    Le profil d'altitude est rééchantillonné au pas de 100 m puis lissé
    (`FENETRE_ALTITUDE` pas) avant d'être dérivé en pente ; sans ce lissage,
    le bruit de l'altimètre fabriquerait des rampes qui n'existent pas.
    """
    points = trace.points
    if len(points) < 2:
        raise ErreurUtilisateur("simuler : tracé de moins de deux points, il n'y a rien à parcourir")
    distances = _distances_cumulees(points)
    total = distances[-1]
    if not (math.isfinite(total) and total > 0):
        raise ErreurUtilisateur("simuler : tracé de longueur nulle")

    bornes = _bornes_pas(total)
    altitudes = moyenne_glissante(
        [_altitude(points, distances, d) for d in bornes], FENETRE_ALTITUDE
    )
    puissance = puissance_w if callable(puissance_w) else (lambda _d, _p=float(puissance_w): _p)

    v_max_descente = V_MAX_DESCENTE_KMH / 3.6
    temps_total = 0.0
    par_segment: list[tuple[float, float, float, float]] = []
    plafonnes = bloques = 0
    for i in range(len(bornes) - 1):
        longueur = bornes[i + 1] - bornes[i]
        if longueur <= 0:
            continue
        pente = (altitudes[i + 1] - altitudes[i]) / longueur
        milieu = (bornes[i] + bornes[i + 1]) / 2
        cap = _cap_a(points, distances, milieu)
        vent_face = vent(milieu, cap) if vent is not None else 0.0
        if vent_face is None or not math.isfinite(vent_face):
            vent_face = 0.0
        v = vitesse_regime(float(puissance(milieu)), pente, vent_face, p)
        if pente < 0 and v > v_max_descente:
            v = v_max_descente
            plafonnes += 1
        if v < V_MIN_MS:
            v = V_MIN_MS
            bloques += 1
        t = longueur / v
        temps_total += t
        par_segment.append((bornes[i + 1], pente, v * 3.6, t))

    return Simulation(
        temps_s=temps_total,
        distance_m=total,
        vitesse_moy_kmh=(total / 1000.0) / (temps_total / 3600.0) if temps_total > 0 else 0.0,
        par_segment=par_segment,
        pas_plafonnes=plafonnes,
        pas_bloques=bloques,
    )


def _bornes_pas(total: float) -> list[float]:
    """Les bornes des pas de 100 m, le dernier pas absorbant le reste.

    Un reste minuscule (3 cm sur un tracé de 10 000,03 m) ferait un pas
    dégénéré : il est fondu dans le pas précédent plutôt que de produire une
    pente calculée sur trois centimètres d'altitude lissée.
    """
    bornes = [0.0]
    while bornes[-1] + PAS_M < total:
        bornes.append(bornes[-1] + PAS_M)
    if total - bornes[-1] < PAS_M / 10 and len(bornes) > 1:
        bornes[-1] = total
    else:
        bornes.append(total)
    return bornes


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    Même précaution que dans `boucle.meteo_trace` : un tracé importé dont les
    `dist_m` sont restées à zéro donnerait une simulation de longueur nulle.
    """
    if points[-1].dist_m > 0:
        valeurs = [float(p.dist_m) for p in points]
        if all(b >= a for a, b in zip(valeurs[:-1], valeurs[1:], strict=True)):
            return valeurs
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _index_avant(distances: Sequence[float], d: float) -> int:
    """Indice du dernier point dont la distance cumulée est ≤ `d` (recherche dichotomique)."""
    bas, haut = 0, len(distances) - 1
    while bas < haut:
        milieu = (bas + haut + 1) // 2
        if distances[milieu] <= d:
            bas = milieu
        else:
            haut = milieu - 1
    return bas


def _altitude(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Altitude interpolée à la distance `d`. 0 si le tracé n'a aucune altitude.

    Un tracé sans altitude donne une pente nulle partout — c'est le terrain
    plat, faute de mieux, et c'est dit dans `Trace.denivele_m` qui vaut alors
    `None`.
    """
    i = _index_avant(distances, d)
    avant = points[i]
    apres = points[min(i + 1, len(points) - 1)]
    if avant.alt_m is None and apres.alt_m is None:
        return 0.0
    if avant.alt_m is None:
        return float(apres.alt_m)
    if apres.alt_m is None:
        return float(avant.alt_m)
    portee = distances[min(i + 1, len(distances) - 1)] - distances[i]
    f = (d - distances[i]) / portee if portee > 0 else 0.0
    return float(avant.alt_m) + (float(apres.alt_m) - float(avant.alt_m)) * f


def _cap_a(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Le cap du tracé à la distance `d`, en degrés. 0 si les deux points coïncident."""
    i = _index_avant(distances, d)
    j = min(i + 1, len(points) - 1)
    if j == i:
        i = max(0, j - 1)
    if distance_m(points[i], points[j]) <= 0:
        return 0.0
    return cap_deg(points[i], points[j])

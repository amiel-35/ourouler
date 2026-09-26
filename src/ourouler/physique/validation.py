"""La validation de la calibration : resimuler des sorties jamais vues, mesurer leur erreur.

Sorti de physique/calibration.py. Physique pure
comme lui ; mêmes calculs, dans le même ordre, avant et après le déplacement.
"""

from __future__ import annotations

import bisect
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple

from ourouler.noyau.activite import Activite
from ourouler.noyau.meteo import HeureArchive
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.physique.echantillonnage import (
    SEUIL_ARRET_MS,
    _distances_points,
    _interpoler_archive,
    _vent_de_face,
)
from ourouler.physique.modele import (
    Parametres,
    Simulation,
    simuler,
)

# --- validation ---------------------------------------------------------------


class ErreurSortie(NamedTuple):
    """L'écart entre le temps simulé et le temps en mouvement réel d'une sortie.

    `NamedTuple` et non dataclass, et `jour` en chaîne ISO : le contrat §3
    demande un rapport **texte et JSON**, et `json.dumps` doit pouvoir avaler
    la liste telle quelle sans conversion préalable.
    """

    jour: str  # AAAA-MM-JJ, vide si la source n'a pas d'horodatage
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
                jour=activite.debut.date().isoformat() if activite.debut else "",
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
        # Le point le plus proche en distance, le premier en cas d'égalité —
        # par dichotomie (les distances cumulées ne décroissent jamais) : un
        # parcours linéaire coûtait N par pas de simulation, et la calibration
        # à CdA seul (L9.1) rejoue chaque sortie une dizaine de fois.
        i = bisect.bisect_left(distances, dist_m)
        if i >= len(distances) or (
            i > 0 and dist_m - distances[i - 1] <= distances[i] - dist_m
        ):
            i -= 1
        return instants[bisect.bisect_left(distances, distances[i])]

    def face(dist_m: float, cap: float) -> float:
        heure = _interpoler_archive(vent, a_l_heure(dist_m))
        valeur = _vent_de_face(heure, cap)
        return valeur if valeur is not None else 0.0

    return face

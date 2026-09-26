"""Le tracé vu comme une suite de pas, tel que le placement le parcourt.

Sorti de `seance/placement.py` : distances cumulées,
altitude, caps et vent arrondi de chaque pas (`_Terrain`). Rien ici ne
décide d'un placement ; les mêmes calculs, dans le même ordre, qu'avant le
déplacement.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence

from ourouler.noyau.activite import moyenne_glissante
from ourouler.noyau.trace import (
    PointTrace,
    Trace,
    cap_deg,
    distance_m,
)
from ourouler.physique.modele import (
    FENETRE_ALTITUDE,
    PAS_M,
    V_MAX_DESCENTE_KMH,
    V_MIN_MS,
    Parametres,
    vitesse_regime,
)
from ourouler.seance.vent import ChampVent

#: Pas d'arrondi de la composante de vent, en m/s, pour la mémoïsation des
#: vitesses. 0,25 m/s vaut 0,9 km/h — bien en deçà de ce que la prévision sait
#: dire, donc l'arrondi ne coûte aucune justesse.
#:
#: Il ne gagne pas grand-chose non plus, et c'est mesuré : le supprimer coûte
#: **2 %** sur un placement, pas une explosion du cache. La raison est
#: que `_Terrain.vent_face` mémoïse déjà par `(pas, sens)` : il n'existe que
#: deux valeurs de vent possibles par pas, quoi qu'il arrive. On garde
#: l'arrondi parce qu'il est gratuit et qu'il borne la clé, pas parce qu'il
#: sauve le cache.
PAS_VENT_MS = 0.25


def _point_a(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> PointTrace:
    """Le point du tracé à la distance `d`, interpolé entre les deux qui l'encadrent."""
    i = min(max(bisect.bisect_right(distances, d) - 1, 0), len(points) - 2)
    avant, apres = points[i], points[i + 1]
    portee = distances[i + 1] - distances[i]
    f = min(max((d - distances[i]) / portee if portee > 0 else 0.0, 0.0), 1.0)
    if avant.alt_m is None or apres.alt_m is None:
        altitude = avant.alt_m if apres.alt_m is None else apres.alt_m
    else:
        altitude = avant.alt_m + (apres.alt_m - avant.alt_m) * f
    return PointTrace(
        lat=avant.lat + (apres.lat - avant.lat) * f,
        lon=avant.lon + (apres.lon - avant.lon) * f,
        alt_m=altitude,
        dist_m=d,
    )


# --- le tracé vu comme une suite de pas -------------------------------------


class _Terrain:
    """Le tracé découpé en pas de `PAS_M` mètres, avec la pente et le cap de chaque pas.

    Même découpage et même lissage d'altitude que `physique.modele.simuler` :
    l'altimètre bruite de quelques dizaines de centimètres, ce qui fabrique
    des pentes fantômes de plusieurs pour cent sur 100 m. Les vitesses sont
    mémorisées par (puissance, pente arrondie, vent de face arrondi) : le
    balayage des décalages repasse mille fois sur les mêmes pas, et la
    bissection du modèle n'a aucune raison d'être refaite.

    Le **cap** de chaque pas est de la géométrie pure, calculée une fois à la
    construction au même titre que les pentes. Il ne sert qu'au vent — mais
    sans lui, un champ de vent ne saurait pas dire si le cycliste va vers lui
    ou s'en éloigne.

    Sans champ de vent (`vent=None`), la composante de face vaut zéro partout
    et les vitesses sont **exactement** celles d'avant : c'est la garantie de
    non-régression.
    """

    def __init__(self, trace: Trace, p: Parametres, vent: ChampVent | None = None) -> None:
        self.p = p
        self.vent = vent
        distances = _distances_cumulees(trace.points)
        self.total = distances[-1]
        self.bornes = _bornes_pas(self.total)
        altitudes = moyenne_glissante(
            [_altitude(trace.points, distances, d) for d in self.bornes], FENETRE_ALTITUDE
        )
        # `_bornes_pas` ne fabrique jamais de pas nul sur un tracé de longueur
        # non nulle ; un tracé de deux points confondus, lui, en donne un. La
        # pente y est indéfinie, pas infinie : on la dit plate plutôt que de
        # laisser lever un `ZeroDivisionError` nu. `placer` refuse déjà ce
        # tracé en amont, mais `_Terrain` ne doit pas être un piège pour le
        # prochain appelant.
        self.pentes = []
        for i in range(len(self.bornes) - 1):
            longueur = self.bornes[i + 1] - self.bornes[i]
            denivele = altitudes[i + 1] - altitudes[i]
            self.pentes.append(denivele / longueur if longueur > 0 else 0.0)
        self.caps = _caps_pas(trace.points, distances, self.bornes)
        self.bornee = trace.bornee()
        self._vitesses: dict[tuple[float, float, float], float] = {}
        self._vents: dict[tuple[int, int], float] = {}

    def vitesse(self, puissance_w: float, pente: float, vent_face_ms: float = 0.0) -> float:
        """La vitesse de régime, en m/s, avec les mêmes garde-fous que la simulation.

        `vent_face_ms` est compté positif de face, comme dans `physique.modele`.
        Il est arrondi à `PAS_VENT_MS` avant d'entrer dans la clé de cache —
        et c'est la valeur arrondie qui va au modèle, pour que deux appels à
        la même clé rendent le même nombre.
        """
        cle = (round(puissance_w, 1), round(pente, 5), _arrondir_vent(vent_face_ms))
        connue = self._vitesses.get(cle)
        if connue is not None:
            return connue
        v = vitesse_regime(cle[0], cle[1], cle[2], self.p)
        if cle[1] < 0:
            v = min(v, V_MAX_DESCENTE_KMH / 3.6)  # le cycliste freine, le modèle ne le sait pas
        v = max(v, V_MIN_MS)  # plancher affiché, pas une mesure
        self._vitesses[cle] = v
        return v

    def vent_face(self, i: int, sens: int) -> float:
        """La composante de face, en m/s, au milieu du pas `i` parcouru dans `sens`.

        Le milieu du pas plutôt qu'une de ses bornes : le vent y vaut la
        moyenne du pas, et une borne partagée par deux pas voisins donnerait
        au vent une discontinuité que la pente n'a pas.

        Mémoïsée par (pas, sens) : il n'y a que deux valeurs possibles par
        pas, et le balayage des décalages les redemande des milliers de fois.
        """
        if self.vent is None:
            return 0.0
        cle = (i, 1 if sens > 0 else -1)
        connue = self._vents.get(cle)
        if connue is None:
            milieu = (self.bornes[i] + self.bornes[i + 1]) / 2.0
            connue = self.vent.vent_face_ms(milieu, self.caps[i], sens)
            self._vents[cle] = connue
        return connue

    def vent_face_a(self, position_m: float, sens: int) -> float:
        """La composante de face à une position, prise sur le pas qui la contient."""
        if self.vent is None:
            return 0.0
        return self.vent_face(self._pas_contenant(position_m), sens)

    def pente_a(self, position_m: float) -> float:
        """La pente du pas qui contient `position_m` (celle du pas le plus proche aux bouts)."""
        return self.pentes[self._pas_contenant(position_m)]

    def _pas_contenant(self, position_m: float) -> int:
        """L'indice du pas qui contient `position_m`, celui du bout au-delà des bornes."""
        i = bisect.bisect_right(self.bornes, position_m) - 1
        return min(max(i, 0), len(self.pentes) - 1)

    def dans_le_trace(self, position_m: float) -> float:
        """Ramène une position entre le départ et l'arrivée, sans faire le tour.

        À distinguer de `borner`, qui fait le tour d'une boucle fermée. Ici on
        veut la position telle qu'on la reparcourra sur le tracé : un demi-tour
        amorcé à moins d'une demi-récup de la fin d'une boucle se fait donc au
        bout du tracé, quelques centaines de mètres plus tôt que dans le calcul
        des durées. C'est la seule approximation du parcours rendu par
        `trace_parcourue`, et elle ne joue qu'à cet endroit-là.
        """
        return min(max(position_m, 0.0), self.total)

    def borner(self, position_m: float) -> float:
        """Ramène une position dans le tracé : par le tour de boucle si elle est fermée."""
        if self.bornee and self.total > 0:
            return position_m % self.total
        return min(max(position_m, 0.0), self.total)

    def avancer(self, position_m: float, sens: int, duree_s: float, puissance_w: float) -> float | None:
        """Position atteinte après `duree_s`, ou `None` si l'on sort du tracé.

        On ne fait pas le tour de la boucle : une séance qui ne tient pas en
        un passage ne tient pas, et le dire vaut mieux que rendre un parcours
        qui repasse deux fois au même endroit.
        """
        if duree_s <= 0:
            return position_m
        restant, pos = duree_s, position_m
        for _ in range(len(self.bornes) + 1):
            i = self._pas(pos, sens)
            if i is None:
                return None
            borne = self.bornes[i + 1] if sens > 0 else self.bornes[i]
            v = self.vitesse(puissance_w, self.pentes[i] * sens, self.vent_face(i, sens))
            t = abs(borne - pos) / v
            if t >= restant:
                return pos + sens * v * restant
            restant -= t
            pos = borne
        return None

    def duree_pour(self, position_m: float, sens: int, distance: float, puissance_w: float) -> float | None:
        """Le temps qu'il faut pour couvrir `distance` depuis `position_m`, ou `None`."""
        if distance <= 0:
            return 0.0
        restant, pos, duree = distance, position_m, 0.0
        for _ in range(len(self.bornes) + 1):
            i = self._pas(pos, sens)
            if i is None:
                return None
            borne = self.bornes[i + 1] if sens > 0 else self.bornes[i]
            v = self.vitesse(puissance_w, self.pentes[i] * sens, self.vent_face(i, sens))
            longueur = abs(borne - pos)
            if longueur >= restant:
                return duree + restant / v
            duree += longueur / v
            restant -= longueur
            pos = borne
        return None

    def _pas(self, position_m: float, sens: int) -> int | None:
        """Indice du pas dans lequel on entre depuis `position_m`, `None` hors du tracé."""
        if sens > 0:
            i = bisect.bisect_right(self.bornes, position_m) - 1
        else:
            i = bisect.bisect_left(self.bornes, position_m) - 1
        return i if 0 <= i < len(self.pentes) else None


def _arrondir_vent(vent_face_ms: float) -> float:
    """Le vent de face arrondi au multiple de `PAS_VENT_MS` le plus proche.

    Rend `0.0` — et non `-0.0` — pour un vent nul : les deux sont égaux pour
    Python mais font la même clé de cache, autant n'en écrire qu'une.
    """
    return round(vent_face_ms / PAS_VENT_MS) * PAS_VENT_MS or 0.0


def _caps_pas(
    points: Sequence[PointTrace], distances: Sequence[float], bornes: Sequence[float]
) -> list[float]:
    """Le cap de chaque pas, en degrés (0 = nord, sens horaire).

    Même géométrie que `boucle.trace.cap_deg`, entre les deux bouts du pas.
    Un pas dont les deux bouts tombent sur le même point — un tracé qui
    revient sur lui-même, deux points GPS identiques — reprend le cap du pas
    précédent plutôt que de rendre un zéro qui se lirait « plein nord ».
    """
    caps: list[float] = []
    for i in range(len(bornes) - 1):
        a = _point_a(points, distances, bornes[i])
        b = _point_a(points, distances, bornes[i + 1])
        if distance_m(a, b) > 0:
            caps.append(cap_deg(a, b))
        else:
            # Deux points confondus : le cap n'existe pas. On prolonge le
            # précédent ; au tout premier pas il n'y en a pas, et le repli
            # vaut alors 0.0, c'est-à-dire plein nord — une valeur fausse
            # qu'on assume parce qu'un tracé qui commence par deux points
            # confondus est refusé par `placer` bien avant d'arriver ici.
            caps.append(caps[-1] if caps else 0.0)
    return caps


def _bornes_pas(total: float) -> list[float]:
    """Les bornes des pas de `PAS_M`, le dernier absorbant le reste, jamais de pas nul."""
    bornes = [0.0]
    while bornes[-1] + PAS_M < total:
        bornes.append(bornes[-1] + PAS_M)
    bornes.append(total)
    return bornes


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    Même précaution que dans `boucle.meteo_trace` et `physique.modele` : un
    tracé importé dont les `dist_m` sont restées à zéro donnerait une séance
    posée sur une longueur nulle.
    """
    if len(points) >= 2 and points[-1].dist_m > 0:
        valeurs = [float(p.dist_m) for p in points]
        if all(b >= a for a, b in zip(valeurs[:-1], valeurs[1:], strict=True)):
            return valeurs
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _altitude(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Altitude interpolée à la distance `d` ; 0 si le tracé n'a pas d'altitude (terrain plat)."""
    i = min(max(bisect.bisect_right(distances, d) - 1, 0), len(points) - 1)
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

"""Le vent le long du tracé, interrogeable à n'importe quelle position.

`boucle.meteo_trace` produit des `Echantillon` espacés de quelques
kilomètres, chacun daté de l'heure de passage. Le placement, lui, avance par
pas de 100 m et a besoin du vent **à la position où il se trouve**, pas au
plus proche échantillon : d'où ce champ, qui interpole entre les deux
échantillons encadrants.

Ce que ce module apporte au placement, mesuré sur les paramètres calibrés du
mainteneur (terrain plat, 20 min à 210 W) : 11,1 km sans vent, 13,3 km avec
20 km/h dans le dos, 9,2 km avec 20 km/h de face. Placer un bloc sans tenir
compte du vent, c'est se tromper de 4 km sur un bloc qui en fait 11.

Deux précautions qui portent tout le module :

* **Vent inconnu n'est pas vent nul.** Un échantillon hors de l'horizon de
  prévision ne dit rien du vent ; `vent_face_ms` rend alors `0.0` — il faut
  bien avancer — mais `complet` passe à `False` et l'appelant peut dire
  « vent non pris en compte » plutôt que de laisser croire à un calcul.
* **Le vent de travers ne ralentit pas ici.** `physique.modele` ne connaît
  qu'une composante longitudinale ; un vent perpendiculaire au cap rend donc
  exactement zéro. C'est une approximation assumée, pas un oubli.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

from ourouler.boucle.meteo_trace import Echantillon, interpoler_angle
from ourouler.physique.modele import FACTEUR_VENT_HAUTEUR


class ChampVent:
    """Le vent le long du tracé, interrogeable à n'importe quelle position."""

    def __init__(
        self,
        echantillons: Sequence[Echantillon],
        facteur_hauteur: float = FACTEUR_VENT_HAUTEUR,
    ) -> None:
        """`facteur_hauteur` ramène le vent météo (10 m) à hauteur de cycliste.

        Sa valeur par défaut est celle de `physique.modele`, la même que celle
        dont la calibration se sert sur l'archive : le modèle serait calibré
        sur un vent et utilisé sur un autre si les deux divergeaient. Le
        paramètre n'existe que pour qu'un test puisse neutraliser la
        conversion, pas pour être réglé.
        """
        ordonnes = sorted(echantillons, key=lambda e: e.dist_m)
        self.facteur_hauteur = facteur_hauteur
        self.positions = [e.dist_m for e in ordonnes]
        self.vitesses_ms = [
            e.vent_kmh / 3.6 if e.vent_kmh is not None else None for e in ordonnes
        ]
        self.directions_deg = [e.vent_depuis_deg for e in ordonnes]
        self.complet = bool(ordonnes) and all(
            v is not None and d is not None
            for v, d in zip(self.vitesses_ms, self.directions_deg, strict=True)
        )

    def vent_face_ms(self, position_m: float, cap_deg: float, sens: int) -> float:
        """Composante de face en m/s : positive de face, négative dans le dos.

        `v_face = V · cos(vent_depuis_deg − cap_effectif)`, où `cap_effectif`
        est `cap_deg` à l'aller et `cap_deg + 180` au retour d'un demi-tour.
        `vent_depuis_deg` étant la direction **d'où vient** le vent, un vent
        qui vient exactement de là où l'on va rend `+V` : c'est bien un vent
        de face. Vent de dos : `−V`. Vent perpendiculaire : `0` — voir la
        note du module sur le travers.

        Rend `0.0` quand le vent n'est pas connu à cette position ; `complet`
        dit alors que le champ ne couvre pas tout le tracé.
        """
        vitesse, direction = self._a(position_m)
        if vitesse is None or direction is None:
            return 0.0
        cap_effectif = cap_deg if sens > 0 else cap_deg + 180.0
        a_10m = vitesse * math.cos(math.radians(direction - cap_effectif))
        return a_10m * self.facteur_hauteur

    def _a(self, position_m: float) -> tuple[float | None, float | None]:
        """(vitesse en m/s à 10 m, direction d'où vient le vent) à cette position.

        Au-delà du dernier échantillon ou avant le premier, on prend celui du
        bout : ce sont les mêmes points du tracé, et un placement qui dépasse
        de quelques mètres la dernière borne ne doit pas perdre le vent.
        L'interpolation de la direction est **angulaire** (350° et 10° font
        0°, pas 180°), et c'est celle de `meteo_trace`, pas une seconde
        version qui pourrait en diverger.
        """
        if not self.positions:
            return (None, None)
        if not math.isfinite(position_m):
            return (None, None)
        if position_m <= self.positions[0]:
            return (self.vitesses_ms[0], self.directions_deg[0])
        if position_m >= self.positions[-1]:
            return (self.vitesses_ms[-1], self.directions_deg[-1])

        j = bisect.bisect_right(self.positions, position_m)
        i = j - 1
        portee = self.positions[j] - self.positions[i]
        f = (position_m - self.positions[i]) / portee if portee > 0 else 0.0
        va, vb = self.vitesses_ms[i], self.vitesses_ms[j]
        da, db = self.directions_deg[i], self.directions_deg[j]
        if va is None or vb is None or da is None or db is None:
            return (None, None)
        return (va + (vb - va) * f, interpoler_angle(da, db, f))

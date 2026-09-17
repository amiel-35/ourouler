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

Quatre précautions portent tout le module :

* **Vent inconnu n'est pas vent nul.** `complet` est une propriété du champ
  entier, pas d'un point : il dit « tous les échantillons portaient un vent »
  et permet à l'appelant d'écrire « vent non pris en compte » plutôt que de
  laisser croire à un calcul qui n'a pas eu lieu.
* **Un trou n'efface pas le reste.** Un échantillon manquant sur vingt-cinq
  ne fait pas perdre le vent des vingt-quatre autres : l'interpolation se
  fait entre les échantillons **connus** qui encadrent la position. Seul un
  champ sans aucun vent connu rend zéro partout.
* **Hors des bornes, on prolonge le bout.** L'échantillonnage est tous les
  5 km : le tracé dépasse le dernier échantillon par construction, et rendre
  zéro y creuserait un trou de vent artificiel à la fin de chaque boucle.
* **Le vent de travers ne ralentit pas ici.** `physique.modele` ne connaît
  qu'une composante longitudinale ; un vent perpendiculaire au cap rend donc
  exactement zéro. C'est une approximation assumée, pas un oubli.

Invariant dur : `vent_face_ms` ne rend **jamais** un NaN ni un infini. Un tel
nombre traverserait `physique.modele._finis`, qui lève `ErreurUtilisateur` —
au milieu du balayage des décalages, c'est-à-dire là où personne ne saurait
d'où l'erreur vient. Une valeur non finie reçue d'Open-Meteo est donc traitée
comme un vent **inconnu**, exactement comme une valeur absente.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

from ourouler.boucle.meteo_trace import (
    SEUIL_VENT_SENSIBLE_KMH,
    Echantillon,
    interpoler_angle,
)
from ourouler.physique.modele import FACTEUR_VENT_HAUTEUR

#: Réexporté de `boucle.meteo_trace`, où la constante vit depuis le
#: 17/09/2026 avec sa justification (échelle de Beaufort) et la règle qui
#: s'en sert, `fleches_vent`. Elle était ici ; `boucle` en a eu besoin pour
#: sérialiser les flèches de vent du JSON, et `boucle` ne peut pas importer
#: `seance` — c'est `seance` qui importe `boucle`, partout. La déplacer d'un
#: cran plus bas garde **une seule constante pour tous ses usages**, qui est
#: exactement ce que le lot L5.3 voulait ; la dupliquer pour préserver
#: l'emplacement aurait trahi la règle en respectant la ligne.
__all__ = ["SEUIL_VENT_SENSIBLE_KMH", "ChampVent", "seuil_vent_sensible_ms"]


def seuil_vent_sensible_ms() -> float:
    """`SEUIL_VENT_SENSIBLE_KMH` en m/s **à hauteur de cycliste**.

    C'est dans cette unité que se comparent les composantes de face rendues
    par `ChampVent.vent_face_ms` : les comparer au chiffre météo brut serait
    comparer deux grandeurs différentes.
    """
    return SEUIL_VENT_SENSIBLE_KMH / 3.6 * FACTEUR_VENT_HAUTEUR


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

        Rien n'est refusé à la construction : un échantillon sans vent, ou
        porteur d'un nombre non fini, est **écarté** et `complet` passe à
        `False`. Une prévision abîmée ne doit pas tuer la planification de la
        sortie, elle doit seulement se dire.
        """
        self.facteur_hauteur = facteur_hauteur if math.isfinite(facteur_hauteur) else 0.0
        connus = sorted(
            (e for e in echantillons if _utilisable(e)), key=lambda e: float(e.dist_m)
        )
        self.positions = [float(e.dist_m) for e in connus]
        self.vitesses_ms = [float(e.vent_kmh) / 3.6 for e in connus]
        self.directions_deg = [float(e.vent_depuis_deg) for e in connus]
        self.complet = bool(echantillons) and len(connus) == len(echantillons)

    def vent_face_ms(self, position_m: float, cap_deg: float, sens: int) -> float:
        """Composante de face en m/s : positive de face, négative dans le dos.

        `v_face = V · cos(vent_depuis_deg − cap_effectif)`, où `cap_effectif`
        est `cap_deg` à l'aller et `cap_deg + 180` au retour d'un demi-tour.
        `vent_depuis_deg` étant la direction **d'où vient** le vent, un vent
        qui vient exactement de là où l'on va rend `+V` : c'est bien un vent
        de face. Vent de dos : `−V`. Vent perpendiculaire : `0` — voir la
        note du module sur le travers.

        Rend `0.0` quand aucun vent n'est connu nulle part sur le tracé, et
        quand le cap ou la position n'est pas un nombre fini. Jamais de NaN.
        """
        vitesse, direction = self._a(position_m)
        if vitesse is None or direction is None or not math.isfinite(cap_deg):
            return 0.0
        cap_effectif = cap_deg if sens > 0 else cap_deg + 180.0
        a_10m = vitesse * math.cos(math.radians(direction - cap_effectif))
        face = a_10m * self.facteur_hauteur
        return face if math.isfinite(face) else 0.0

    def _a(self, position_m: float) -> tuple[float | None, float | None]:
        """(vitesse en m/s à 10 m, direction d'où vient le vent) à cette position.

        Ne voit que les échantillons dont le vent est connu : un trou dans la
        série est traversé plutôt que de faire un trou dans le vent. Au-delà
        du dernier de ces échantillons ou avant le premier, on prolonge celui
        du bout — c'est le même vent, quelques centaines de mètres plus loin.

        L'interpolation de la direction est **angulaire** (350° et 10° font
        0°, pas 180°), et c'est celle de `meteo_trace`, pas une seconde
        version qui pourrait en diverger.
        """
        if not self.positions or not math.isfinite(position_m):
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
        return (
            va + (vb - va) * f,
            interpoler_angle(self.directions_deg[i], self.directions_deg[j], f),
        )


def _utilisable(e: Echantillon) -> bool:
    """Vrai si l'échantillon porte un vent exploitable : présent **et** fini.

    Une position non finie est écartée aussi : elle empêcherait de trier la
    série et rendrait toute recherche par dichotomie absurde.
    """
    return all(
        valeur is not None and math.isfinite(valeur)
        for valeur in (e.dist_m, e.vent_kmh, e.vent_depuis_deg)
    )

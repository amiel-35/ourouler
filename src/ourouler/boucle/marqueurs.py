"""Ce qui fait « la ville » sous les roues : feux, stops, passages piétons,
cédez-le-passage, ralentisseurs — comptés au kilomètre.

Ce qu'un cycliste appelle la ville : croisements, voitures, dos d'âne ou
chicanes, feux. Ce module compte
exactement ces marqueurs-là sur un tracé entier et en tire une **densité au
kilomètre**.

**Pourquoi ce module existe.** `seance.terrain` sait déjà les compter, mais
seulement **sous un bloc** — et bien des plans ne contiennent aucune séance
à blocs en extérieur. Sur une endurance, la sortie ordinaire, la note de
terrain vaut zéro et rien ne dit
qu'une boucle traverse six bourgs quand l'autre n'en traverse aucun. Il
fallait donc une mesure qui porte sur le **tracé entier**, indépendante du
placement.

**Ce qu'il remplace fonctionnellement.** `seance.terrain.MAXSPEED_BATI_KMH`
devait repérer l'agglomération par la vitesse limite ; mesuré, notre profil
BRouter ne renvoie **jamais** `maxspeed`, et la zone bâtie se
réduit donc à trois valeurs de `highway`. Un bourg traversé sur une
départementale n'est pas vu. Les marqueurs de nœud, eux, sont renvoyés — et
ils sont ce qu'un cycliste perçoit réellement.

**Vocabulaire partagé, pas dupliqué.** `NOEUDS_CARREFOUR`,
`CLE_RALENTISSEUR` et `RALENTISSEURS_SANS_EFFET` sont ici, et
`seance.terrain` les importe. Deux
définitions de « ce qui fait lever le pied » finiraient par diverger, et la
note sous un bloc ne dirait plus la même chose que la densité du tracé.

**Zéro ne veut jamais dire « aucun feu ».** Un GPX importé n'a pas de
`segments` : il ne porte aucun tag de nœud, ce qui n'est pas la même chose
que n'avoir aucun feu. `Marqueurs.connue` est faux dans ce cas et `par_km`
rend `None` — on n'affirme rien sans mesure, une ignorance se dit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ourouler.noyau.trace import Trace

#: `highway` d'un **nœud** qui impose un arrêt ou un ralentissement. Ils
#: arrivent par `Segment.node_tags`, alimenté par la colonne `NodeTags` des
#: messages BRouter.
NOEUDS_CARREFOUR = frozenset({"traffic_signals", "stop", "give_way", "mini_roundabout", "crossing"})

#: Ceux qui **arrêtent** vraiment, par opposition à ceux qui font lever le
#: pied. Mesuré sur une boucle réelle de 55 km : 457 marqueurs,
#: dont **296 passages piétons (65 %)** et seulement **28 feux (6 %)**. Le
#: composite est donc dominé par ce qui coûte le moins — un passage piéton
#: sur une route de campagne se traverse sans lever le pied.
#:
#: C'est la vraie raison de cette distinction : qui lit « 1,7 feux par km » et
#: roule 100 km s'attend à croiser 170 feux. Une unité qui invite à multiplier, sur un
#: composite qui mélange l'arrêt et le rien.
NOEUDS_ARRET = frozenset({"traffic_signals", "stop"})

#: Un **ralentisseur** : dos d'âne, coussin, chicane, plateau. Il arrive par la
#: clé `traffic_calming` des `NodeTags`, pas par `highway` — un compte fondé
#: sur `highway` ne le verrait pas, alors que BRouter en pose 30 sur une seule
#: boucle réelle (mesuré).
CLE_RALENTISSEUR = "traffic_calming"

#: Valeurs de `traffic_calming` qui ne ralentissent pas un cycliste : une
#: écluse ou un rétrécissement se franchit sans lever du selle quand on est
#: seul. On les écarte plutôt que de gonfler le compte pour rien.
RALENTISSEURS_SANS_EFFET = frozenset({"choker", "island", "dip"})

#: Les noms lisibles de chaque nature, au singulier et au pluriel.
LIBELLES = {
    "traffic_signals": ("feu", "feux"),
    "stop": ("stop", "stops"),
    "give_way": ("cédez-le-passage", "cédez-le-passage"),
    "mini_roundabout": ("mini-giratoire", "mini-giratoires"),
    "crossing": ("passage piéton", "passages piétons"),
    CLE_RALENTISSEUR: ("ralentisseur", "ralentisseurs"),
}


def nature_du_noeud(node_tags: dict[str, str]) -> str | None:
    """La nature du marqueur porté par ce nœud, ou `None` s'il n'en porte pas.

    Un feu posé sur un plateau surélevé reste **un** marqueur : `highway`
    gagne sur `traffic_calming`, parce que se compter deux fois serait pire
    que de se manquer.
    """
    nature = node_tags.get("highway", "")
    if nature in NOEUDS_CARREFOUR:
        return nature
    calme = node_tags.get(CLE_RALENTISSEUR, "")
    if calme and calme not in RALENTISSEURS_SANS_EFFET:
        return CLE_RALENTISSEUR
    return None


@dataclass(frozen=True)
class Marqueurs:
    """Le compte des marqueurs d'un tracé, et ce qu'on sait de ce compte."""

    nombre: int
    distance_km: float
    #: Vrai si le tracé porte des `segments`, donc si l'absence de marqueur
    #: veut dire quelque chose. Faux pour un GPX importé.
    connue: bool
    par_nature: dict[str, int] = field(default_factory=dict)

    @property
    def arrets(self) -> int | None:
        """Feux et stops seulement : ce qui pose le pied, pas ce qui ralentit.

        `None` quand le tracé ne porte pas de tronçons — l'absence n'est alors
        pas une mesure (on n'affirme rien sans mesure).
        """
        if not self.connue:
            return None
        return sum(self.par_nature.get(n, 0) for n in NOEUDS_ARRET)

    @property
    def arrets_par_km(self) -> float | None:
        """Les arrêts au kilomètre — comparable entre boucles de longueurs différentes.

        C'est cette grandeur qui sert d'axe de contraste ; l'affichage, lui,
        montre des **nombres absolus**, qu'on ne peut pas multiplier de travers.
        """
        n = self.arrets
        if n is None or self.distance_km <= 0:
            return None
        return n / self.distance_km

    @property
    def par_km(self) -> float | None:
        """Marqueurs au kilomètre, ou `None` quand on ne sait pas."""
        if not self.connue or self.distance_km <= 0:
            return None
        return self.nombre / self.distance_km


def compter(trace: Trace) -> Marqueurs:
    """Les marqueurs du tracé **entier** et leur densité au kilomètre.

    Un marqueur est attaché au nœud de **fin** d'un tronçon (`NodeTags`) :
    chaque nœud n'est donc compté qu'une fois, même si plusieurs tronçons s'y
    terminaient. La distance est celle du tracé, pas celle du parcours placé —
    un demi-tour repasse devant les mêmes feux, mais il repasse aussi sur les
    mêmes kilomètres, et le rapport ne bouge pas.
    """
    distance_km = _distance_km(trace)
    if not trace.segments:
        return Marqueurs(nombre=0, distance_km=distance_km, connue=False)
    natures: dict[int, str] = {}
    for segment in trace.segments:
        nature = nature_du_noeud(segment.node_tags)
        if nature is not None:
            natures[segment.fin_idx] = nature
    par_nature: dict[str, int] = {}
    for nature in natures.values():
        par_nature[nature] = par_nature.get(nature, 0) + 1
    return Marqueurs(
        nombre=len(natures),
        distance_km=distance_km,
        connue=True,
        par_nature=par_nature,
    )


def _distance_km(trace: Trace) -> float:
    """La longueur du tracé en km, 0 si elle n'est pas un nombre exploitable."""
    distance = trace.distance_m
    if distance is None or not math.isfinite(distance) or distance <= 0:
        if not trace.points:
            return 0.0
        distance = trace.points[-1].dist_m
    if distance is None or not math.isfinite(distance) or distance <= 0:
        return 0.0
    return distance / 1000.0

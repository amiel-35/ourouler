"""Ce que le placement rend : `Emplacement`, `Placement`, et la trace réellement parcourue.

Sorti de `seance/placement.py` : le résultat d'un
placement et sa relecture sur le tracé (`trace_parcourue`), sans rien du
déroulé qui l'a produit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ourouler.noyau.trace import (
    DENIVELE_PARCOURS,
    PointTrace,
    Trace,
    denivele_filtre,
    distance_m,
)
from ourouler.seance.pas_trace import _distances_cumulees, _point_a
from ourouler.seance.terrain import NoteBloc


@dataclass
class Emplacement:
    """Où tombe une étape de la séance, et ce que vaut le terrain à cet endroit.

    **Une étape de la séance = un `Emplacement`** (décision Q13),
    pas seulement les blocs : l'échauffement, les récupérations et le retour
    au calme ont eux aussi une position, même sans note — aucun terrain n'est
    évalué sous une récupération. `note` vaut donc `None` pour tout ce qui n'est pas un bloc ;
    ce n'est pas une valeur neutre inventée, c'est l'absence de mesure. Un
    appelant qui ne veut que les blocs (l'ancien comportement) utilise
    `Placement.blocs()`, qui filtre sur `note is not None` — c'est exactement
    équivalent à filtrer sur le type de l'étape, sans avoir besoin de le
    répéter ici : `Placement` ne connaît pas la `Seance`, `note` suffit.

    Deux positions, et elles divergent après un demi-tour :

    * `debut_m`/`longueur_m` repèrent une position **sur le tracé d'origine**
      (celle que `_couloir` calcule depuis les deux bouts du pas) — c'est ce
      dont la carte a besoin pour savoir quels points dessiner. Après un
      demi-tour, `debut_m` peut **reculer** : le bloc suivant reprend le
      couloir du bloc précédent, à l'envers.
    * `debut_parcouru_m` est le **compteur kilométrique** : la distance
      parcourue depuis le départ, cumulée, qui ne recule **jamais** — c'est
      lui que l'affichage texte et les infobulles de la carte utilisent,
      parce que c'est ce que « km » veut dire pour quelqu'un qui roule.
      Deux étapes qui reprennent le même couloir (un demi-tour) tombent au
      même `debut_m`, mais jamais au même `debut_parcouru_m` : sur une
      séance qui fait des demi-tours, la suite des `debut_parcouru_m` est
      **strictement croissante** d'une étape à la suivante (testé).

    **Le demi-tour d'une récupération ne se coupe pas en deux `Emplacement`.**
    Elle reste **une** étape de la séance, donc **un** `Emplacement` : celui
    qui va du point où le bloc précédent s'est arrêté jusqu'au point de
    demi-tour, puis en revient. Son `debut_m` est le début de ce couloir
    (`_couloir` sur le point de départ et le point de demi-tour, non écrêté —
    voir plus bas) ; sa `longueur_m` vaut **deux fois** la demi-distance
    estimée (`2 × besoin_m`, aller et retour), pas l'écart entre les deux
    points du tracé (qui vaudrait `besoin_m`) et surtout pas zéro (le départ
    et l'arrivée de cette étape sont le même point). C'est cette même
    estimation `2 × besoin_m` qui est ajoutée à `_Etat.distance_m` ; l'invariant
    « la somme des longueurs vaut `distance_totale_m` » tient donc par
    construction.

    **`jalons_m` n'est pas cette même autorité.** Au bout d'une boucle
    fermée, le point de demi-tour qu'il mémorise est écrêté par
    `_Terrain.dans_le_trace` (approximation connue et documentée, voir sa
    docstring) : `jalons_m` peut alors totaliser un peu
    moins que `distance_totale_m`. `debut_m`/`longueur_m` ne portent pas cet
    écrêtage — ils viennent du point de demi-tour **non écrêté**, cohérent
    avec ce qui est réellement ajouté à `_Etat.distance_m`.
    """

    etape_idx: int
    debut_m: float
    longueur_m: float
    demi_tour: bool  # le bloc réutilise le segment précédent en sens inverse
    note: NoteBloc | None = None
    #: Le compteur kilométrique — voir la docstring de la classe. 0.0 par
    #: défaut pour les appelants qui construisent un `Emplacement` à la main
    #: sans s'en soucier (tests).
    debut_parcouru_m: float = 0.0


@dataclass
class Placement:
    """Une séance posée sur un tracé : le décalage retenu et ce qu'il donne."""

    decalage_z2_s: float  # allongement (ou raccourcissement) de la Z2 d'ouverture
    #: **Toutes** les étapes de la séance, dans l'ordre où on les roule
    #: — voir `Emplacement`. `blocs()` n'en garde que les blocs.
    emplacements: list[Emplacement]
    note_totale: float  # `note_terrain` + `penalite_seance`, et c'est elle qui trie
    duree_totale_s: float
    distance_totale_m: float
    #: Ce qui cloche : un ⚠ à l'affichage. Une séance amputée, une puissance
    #: devinée, un retour au calme hors de sa fenêtre.
    avertissements: list[str] = field(default_factory=list)
    #: Ce qui se dit sans être un défaut : un ⚠ y serait un contresens. Le
    #: retour au calme qui s'allonge dans sa fenêtre est une information, pas
    #: une alerte — c'est la façon normale de refermer la boucle.
    informations: list[str] = field(default_factory=list)
    #: Le terrain seul : moyenne des notes de couloir pondérée par la durée des
    #: blocs. C'est ce que `note_totale` valait avant qu'on lui ajoute la
    #: pénalité, et ce qu'il faut regarder pour comparer deux couloirs.
    note_terrain: float = 0.0
    #: Ce que coûtent les extrémités élastiques : une séance amputée, et le
    #: dépassement du retour au calme au prorata (voir `_penalite_seance`).
    #: Zéro quand la séance est tenue exactement telle qu'elle est prescrite.
    #: L'identité `note_totale = note_terrain + penalite_seance` tient toujours.
    penalite_seance: float = 0.0
    #: Les positions le long du tracé, du départ à l'arrivée, à **chaque
    #: changement de sens** : `[0, 23100, 0]` se lit « on est allé jusqu'au
    #: km 23,1, on a fait demi-tour, on est rentré ». Entre deux jalons on
    #: roule dans un seul sens, ce qui suffit à reconstruire le parcours
    #: réellement roulé — voir `trace_parcourue`.
    jalons_m: list[float] = field(default_factory=list)

    def blocs(self) -> list[Emplacement]:
        """Les seuls emplacements notés : les blocs, dans l'ordre où on les roule.

        La note de terrain, `blocs_bien_places`, `demi_tours` ne comptent
        qu'eux, jamais une récupération.
        """
        return [e for e in self.emplacements if e.note is not None]


#: Sous cette distance, deux points consécutifs du parcours sont le même point :
#: le point interpolé d'un jalon tombe sur un point du tracé, et on n'écrit pas
#: deux fois la même coordonnée dans le GPX.
DOUBLON_PARCOURS_M = 0.01


def trace_parcourue(placement: Placement, trace: Trace) -> Trace:
    """Le parcours réellement roulé, demi-tours compris, comme un `Trace`.

    Le tracé d'origine décrit la boucle que le moteur a proposée ; le placement,
    lui, en roule parfois un morceau deux fois et en laisse un autre de côté. Le
    fichier envoyé au compteur doit contenir ce qu'on va rouler : avec quatre
    demi-tours, un placement réel comptait 72,7 km sur une boucle de 38,5, et
    le GPX de la boucle n'en portait aucun — ce n'était pas la séance.

    `placement.jalons_m` suffit à reconstruire le parcours : entre deux jalons
    on roule dans un seul sens, donc on découpe le tracé à ces positions et on
    recolle les morceaux, à l'endroit ou à l'envers. Distances cumulées,
    distance totale et D+ sont recalculés sur le résultat — un aller-retour
    monte deux fois la même côte, et le `<desc>` du GPX doit le dire.

    Un placement sans jalons (construit à la main, ou d'une version antérieure)
    rend le tracé tel quel : on ne sait pas ce qui a été roulé, on n'invente pas.
    """
    if len(trace.points) < 2:
        return trace
    distances = _distances_cumulees(trace.points)
    total = distances[-1]
    if total <= 0 or len(placement.jalons_m) < 2:
        return trace
    jalons = [min(max(float(j), 0.0), total) for j in placement.jalons_m]

    points: list[PointTrace] = []
    for depart, arrivee in zip(jalons[:-1], jalons[1:], strict=True):
        for point in _points_entre(trace.points, distances, depart, arrivee):
            _empiler(points, point)
    if len(points) < 2:
        return trace

    denivele = denivele_filtre(points)
    return Trace(
        nom=f"{trace.nom} — parcours placé",
        points=points,
        segments=[],  # les indices de segments du tracé d'origine ne désignent plus rien
        distance_m=points[-1].dist_m,
        denivele_m=denivele,
        temps_moteur_s=None,  # aucun moteur n'a estimé ce parcours-là
        meta={
            "source": "parcours placé",
            "trace_origine": trace.nom,
            "denivele_source": DENIVELE_PARCOURS if denivele is not None else None,
            "demi_tours": sum(1 for e in placement.emplacements if e.demi_tour),
        },
    )


def _points_entre(
    points: Sequence[PointTrace], distances: Sequence[float], depart: float, arrivee: float
) -> list[PointTrace]:
    """Les points du tracé de `depart` à `arrivee`, bornes interpolées comprises.

    À l'envers quand `arrivee` est avant `depart` : c'est exactement ce que fait
    le cycliste après un demi-tour, il repasse sur ses propres points.
    """
    bas, haut = min(depart, arrivee), max(depart, arrivee)
    entre = [p for p, d in zip(points, distances, strict=True) if bas < d < haut]
    if arrivee < depart:
        entre.reverse()
    return [
        _point_a(points, distances, depart),
        *entre,
        _point_a(points, distances, arrivee),
    ]


def _empiler(points: list[PointTrace], point: PointTrace) -> None:
    """Ajoute le point au parcours avec sa distance cumulée, sans écrire de doublon."""
    if not points:
        points.append(replace(point, dist_m=0.0))
        return
    pas = distance_m(points[-1], point)
    if pas < DOUBLON_PARCOURS_M:
        return
    points.append(replace(point, dist_m=points[-1].dist_m + pas))

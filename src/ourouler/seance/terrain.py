"""Le terrain sous un bloc d'intervalle : une note, jamais un filtre.

Un bloc de seuil ne se tient pas n'importe où. Ce qui le gâche, du plus grave
au moins grave (cadrage du sprint 4, corrigé par le mainteneur le 13/09) :

1. **une descente longue** — on ne peut pas tenir la puissance en roue libre ;
2. **un village ou un carrefour dans le bloc** — il faut lever le pied ;
3. **une pente irrégulière** — la puissance tient, la vitesse fait le yoyo.

Une montée régulière, elle, n'est pas un défaut : la puissance se tient très
bien, seule la vitesse baisse. Elle n'est donc pénalisée qu'au-delà de
`PENTE_MONTEE_TOLEREE`, et faiblement.

**Ce module ne dit jamais non.** Il rend une note en kilomètres équivalents
(0 = parfait, plus haut = moins bon, même unité que `boucle.couts`) et des
motifs lisibles — « deux feux », « descente de 1,2 km ». Le placement garde
la boucle la moins mauvaise et affiche ce qui cloche ; il ne renvoie pas le
cycliste chez lui parce qu'aucun couloir n'est parfait.

**Aucune évaluation sous une récupération** (décision du mainteneur, 13/09).
Pendant une récup, village, carrefour et revêtement sont sans importance :
`evaluer_couloir` n'a rien à y faire. La seule question qu'on pose à une
récup est mécanique — reste-t-il de la route au-delà du segment, et le
demi-tour est-il faisable : `route_au_dela` et `demi_tour_faisable`.

Ce que ce module ne sait pas et qu'il dit : sans altitude (un GPX sans `ele`),
les pentes valent 0 et le motif « altitude inconnue » le signale ; sans
`segments` (un tracé relu d'une activité), les kilomètres bâtis valent 0 et
le motif « routes inconnues » le signale. Zéro ne veut jamais dire « parfait »
en silence (règle absolue 5).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from ourouler.boucle.couts import HIGHWAY_TRAFIC, tags_par_troncon, virages_detectes
from ourouler.boucle.trace import PointTrace, Trace

# --- ce qui fait un carrefour -------------------------------------------------

#: `highway` d'un **nœud** qui impose un arrêt ou un ralentissement. Ils
#: arrivent par `Segment.node_tags`, alimenté par la colonne `NodeTags` des
#: messages BRouter.
NOEUDS_CARREFOUR = frozenset(
    {"traffic_signals", "stop", "give_way", "mini_roundabout", "crossing"}
)

#: Changement de direction à partir duquel on compte un carrefour, même sans
#: nœud tagué : à 60° on a tourné, donc on a ralenti. La détection elle-même
#: est celle de `boucle.couts` (sous-échantillonnage des caps, fenêtre de 60 m,
#: demi-tour exclu) : on ne la refait pas ici.
ANGLE_CARREFOUR_DEG = 60.0

# --- ce qui fait une zone bâtie ----------------------------------------------

#: `highway` d'une route de village ou de lotissement.
HIGHWAY_BATI = frozenset({"residential", "living_street", "service"})

#: Vitesse limite (km/h) au-dessous ou égale à laquelle on se sait en
#: agglomération, quand le tag existe. Une `tertiary` à 50 traverse un bourg.
MAXSPEED_BATI_KMH = 50.0

# --- ce qui fait une pente ---------------------------------------------------
#
# **Une pente est une tangente**, jamais un pourcentage : 0,05 vaut 5 %. C'est
# la convention de tout le dépôt — `physique.modele.puissance_requise`,
# `physique.calibration.PENTE_MIN/PENTE_MAX`, `--pente-max` de la ligne de
# commande, `seance.placement.PENTE_DEMI_TOUR_MAX`. Le pourcentage n'apparaît
# qu'au moment d'écrire un motif lisible, dans `_pourcent`.

#: Pas de mesure de la pente. Deux points GPS consécutifs sont trop proches
#: pour qu'une différence d'altitude au mètre près veuille dire quelque chose :
#: on agrège jusqu'à cette longueur avant de calculer une pente.
PAS_PENTE_M = 100.0

#: Pente au-dessous de laquelle on descend pour de bon (−1,5 %).
PENTE_DESCENTE = -0.015

#: Longueur minimale d'une descente pour qu'elle compte. Un faux plat
#: descendant de 150 m ne casse pas un bloc de 8 minutes.
LONGUEUR_DESCENTE_M = 300.0

#: Pente tolérée en montée sans aucune pénalité (+2 %).
PENTE_MONTEE_TOLEREE = 0.02

# --- poids de la note, en kilomètres équivalents ------------------------------
#
# Calibrés sur la validation rétrospective (`tests/validation/
# terrain_retrospectif.py`) : les emplacements où le mainteneur a réellement
# fait ses blocs doivent recevoir une note nettement meilleure que des
# emplacements tirés au hasard sur la même sortie.

#: Un **nœud tagué** traversé pendant un bloc — un feu, un stop, un
#: cédez-le-passage : on lève le pied, parfois on pose le pied.
#:
#: Non validé par la validation rétrospective : une sortie enregistrée est une
#: trace GPS sans nœuds OSM, le script ne voit donc aucun feu. Ce poids reste
#: celui du raisonnement produit, pas d'une mesure — et le dire fait partie du
#: lot (règle absolue 5).
POIDS_CARREFOUR = 1.0

#: Un **virage marqué** sans nœud tagué : la route tourne, c'est tout. Dix fois
#: moins cher qu'un feu, et pour cause — mesuré le 13/09 sur les deux sorties
#: de référence, les blocs réels du mainteneur en contiennent 0,86 par km
#: contre 0,90 par km pour des emplacements tirés au hasard : il ne les évite
#: pas. À 1,0 ce poste noyait, à lui seul, tout le reste de la note.
POIDS_VIRAGE_MARQUE = 0.10

#: Un kilomètre de bloc en zone bâtie. Mesuré le 13/09 : les blocs réels en
#: contiennent **zéro**, contre 0,06 km par km au hasard. C'est le poste le
#: plus discriminant qui soit, il mérite de peser.
POIDS_KM_BATI = 3.0

#: Un mètre de dénivelé perdu dans une descente qualifiante. Le défaut le plus
#: grave, et le second poste le plus discriminant (mesuré le 13/09 : 0,36 m par
#: km dans les blocs réels contre 2,52 au hasard, soit 14 %). Une descente de
#: 1 km à −3 % (30 m) coûte trois fois un feu.
POIDS_M_DESCENTE = 0.10

#: Un mètre de dénivelé gagné dans une portion plus raide que
#: `PENTE_MONTEE_TOLEREE`. Presque rien, et c'est mesuré : les blocs réels
#: du mainteneur montent **plus** que le hasard (4,85 m par km contre 3,64,
#: soit 133 %). Il ne fuit pas les montées, il les cherche — la puissance s'y
#: tient mieux qu'ailleurs. Le poids ne sert plus qu'à départager deux couloirs
#: par ailleurs identiques.
POIDS_M_MONTEE = 0.002

#: Une unité d'écart-type de la pente sur le bloc — la pente étant une
#: tangente, un point de pourcentage d'écart-type coûte donc 0,30. Faible,
#: comme le veut le contrat, et la mesure du 13/09 le confirme : 1,47 % dans
#: les blocs réels contre 1,72 % au hasard (86 %), une discrimination réelle
#: mais ténue.
POIDS_IRREGULARITE = 30.0

#: Ce que coûte un bloc qui **ne tient pas** sur le tracé disponible.
#:
#: **Une impossibilité, pas un défaut de terrain** — la distinction est le sens
#: même de cette constante. Les autres poids tarifent ce qui gâche un bloc ;
#: celui-ci dit qu'il n'y a pas de bloc du tout. La note doit le dire fort sans
#: pour autant lever d'exception, parce que ce module ne filtre jamais : le
#: placement verra une note très haute et le motif « bloc plus long que le
#: tracé disponible », et choisira autre chose de lui-même.
PENALITE_BLOC_TRONQUE = 10.0

#: Écart-type de pente à partir duquel l'irrégularité mérite un motif (1 %).
#: En dessous, la ligne « pente irrégulière » ferait du bruit pour rien.
SEUIL_MOTIF_IRREGULARITE = 0.01

#: Distance sous laquelle un virage marqué et un nœud tagué sont le **même**
#: carrefour. Un feu se trouve presque toujours à un endroit où la route
#: tourne : sans ce dédoublonnage, le carrefour le plus banal comptait double.
DEDOUBLONNAGE_M = 40.0

#: Tolérance de flottant sur les distances cumulées, en mètres.
EPSILON_M = 1e-6


@dataclass
class NoteBloc:
    """Ce que vaut un emplacement pour un bloc. `note` : 0 = parfait, plus haut = moins bon."""

    note: float  # en kilomètres équivalents, comme `boucle.couts.Couts.score`
    motifs: list[str] = field(default_factory=list)
    #: Pente moyenne du bloc, du premier au dernier point, **en tangente** :
    #: 0,03 pour 3 % (convention du dépôt, voir plus haut).
    pente_moyenne: float = 0.0
    #: Pente la plus raide rencontrée, en tangente et **signée** : −0,06 pour
    #: une descente à 6 %. C'est la valeur absolue qui est maximale, le signe
    #: dit de quel côté.
    pente_max: float = 0.0
    #: Nœuds tagués (feux, stops…) et virages marqués, dédoublonnés.
    carrefours: int = 0
    #: Kilomètres du bloc en zone bâtie.
    km_batis: float = 0.0
    #: Mètres de dénivelé perdus dans les descentes qualifiantes (positif).
    descente_m: float = 0.0
    #: Mètres de dénivelé gagnés dans les portions plus raides que
    #: `PENTE_MONTEE_TOLEREE` (positif). Pas le D+ du bloc : la part
    #: tolérée n'y est pas.
    montee_m: float = 0.0


# --- l'évaluation -------------------------------------------------------------


def evaluer_couloir(trace: Trace, debut_m: float, longueur_m: float) -> NoteBloc:
    """Note le couloir de `longueur_m` qui commence à `debut_m` sur le tracé.

    Sur une boucle fermée, le couloir continue au-delà du dernier point en
    repartant du premier ; sur un tracé ouvert, il s'arrête et la note porte
    `PENALITE_BLOC_TRONQUE` avec le motif qui va avec. Un `debut_m` hors du
    tracé est ramené dans le tracé (modulo sur une boucle, borné sinon)
    plutôt que refusé : ce module ne lève pas d'exception sur une demande
    bancale, il la note.
    """
    couloir = _couloir(trace, debut_m, longueur_m)
    if not couloir.points:
        return NoteBloc(
            note=PENALITE_BLOC_TRONQUE,
            motifs=["aucun tracé sous le bloc"],
        )

    tagues, virages, motifs_carrefours = _carrefours(trace, couloir)
    km_batis, routes_connues = _zone_batie(trace, couloir)
    releve = _releve_pentes(couloir)

    note = (
        tagues * POIDS_CARREFOUR
        + virages * POIDS_VIRAGE_MARQUE
        + km_batis * POIDS_KM_BATI
        + releve.descente_m * POIDS_M_DESCENTE
        + releve.montee_m * POIDS_M_MONTEE
        + releve.irregularite * POIDS_IRREGULARITE
        + (PENALITE_BLOC_TRONQUE if couloir.tronque else 0.0)
    )

    motifs = _motifs(
        couloir=couloir,
        motifs_carrefours=motifs_carrefours,
        km_batis=km_batis,
        routes_connues=routes_connues,
        releve=releve,
    )
    return NoteBloc(
        note=note,
        motifs=motifs,
        pente_moyenne=releve.pente_moyenne,
        pente_max=releve.pente_max,
        carrefours=tagues + virages,
        km_batis=km_batis,
        descente_m=releve.descente_m,
        montee_m=releve.montee_m,
    )


def route_au_dela(trace: Trace, position_m: float, besoin_m: float) -> bool:
    """Reste-t-il `besoin_m` de route après `position_m` ?

    C'est la **seule** question posée à une récupération (cadrage du 13/09 :
    « en récup, village, croisement etc. c'est pas grave ; il faut de la route
    au-delà du segment »). La moitié d'une récup sert à dépasser le segment
    avant de faire demi-tour : 4 min à 25 km/h ≈ 800 m, 1'30 ≈ 300 m.

    Sur une boucle fermée, **la réponse est toujours oui** : la route ne
    s'arrête pas, on repart sur le tour suivant (contrat §2, « ou si le tracé
    est une boucle fermée (on continue sur la boucle) »). Un besoin plus long
    que le tour lui-même ne change rien à la question posée — on repasse au
    même endroit, mais on roule. Sur un tracé ouvert, il faut que la longueur
    restante suffise.

    Un tracé sans longueur rend faux : il n'y a pas de route du tout.
    """
    if besoin_m <= 0:
        return True
    total = _longueur(trace)
    if total <= 0:
        return False
    if trace.bornee():
        return True
    position = min(max(position_m, 0.0), total)
    return total - position >= besoin_m


def demi_tour_faisable(trace: Trace, position_m: float) -> bool:
    """Peut-on faire demi-tour ici ?

    Faux sur une route à trafic (`boucle.couts.HIGHWAY_TRAFIC`) : une
    départementale passante, on ne s'y retourne pas. Vrai partout ailleurs,
    **y compris quand on ne sait pas** : une classe de route inconnue n'est
    jamais un malus (contrat du sprint 3 §2).
    """
    tags = _tags_a(trace, position_m)
    if tags is None:
        return True
    return tags.get("highway", "") not in HIGHWAY_TRAFIC


# --- découpe du couloir -------------------------------------------------------


@dataclass
class _Couloir:
    """La portion de tracé sous un bloc, découpée au mètre près.

    `points` porte la géométrie (les deux extrémités sont interpolées si elles
    tombent entre deux points du tracé) ; `parts` décrit chaque intervalle
    retenu : indice du point d'origine qui le porte, indice du nœud qui le
    termine (`None` si l'intervalle est coupé avant), longueur retenue.
    """

    points: list[PointTrace]
    parts: list[_Part]
    longueur_m: float
    tronque: bool


@dataclass(frozen=True)
class _Part:
    idx_debut: int  # indice, dans `trace.points`, du point qui porte l'intervalle
    idx_noeud: int | None  # nœud de fin, s'il est dans le couloir
    longueur_m: float
    fin_m: float  # distance cumulée **dans le couloir** à la fin de ce pas


def _couloir(trace: Trace, debut_m: float, longueur_m: float) -> _Couloir:
    """Découpe la portion de `longueur_m` qui commence à `debut_m`."""
    vide = _Couloir(points=[], parts=[], longueur_m=0.0, tronque=True)
    if len(trace.points) < 2 or not math.isfinite(longueur_m) or longueur_m <= 0:
        return vide
    total = _longueur(trace)
    if total <= 0:
        return vide

    boucle = trace.bornee()
    debut = _position(debut_m, total, boucle)
    # Sur une boucle on tourne, mais pas deux fois : un bloc plus long que la
    # boucle entière ne « tient » pas davantage parce qu'on repasse au même
    # endroit — il est tronqué, et la note le dira.
    voulu = min(longueur_m, total) if boucle else longueur_m
    fin = debut + voulu

    points: list[PointTrace] = []
    parts: list[_Part] = []
    couvert = 0.0
    derniere: tuple[int, int, float, float] | None = None
    for idx_a, idx_b, d0, d1 in _intervalles(trace, total, boucle):
        if d1 <= debut + EPSILON_M:
            continue
        if d0 >= fin - EPSILON_M:
            break
        a0, a1 = max(d0, debut), min(d1, fin)
        points.append(_interpoler(trace.points[idx_a], trace.points[idx_b], (a0 - d0) / (d1 - d0)))
        couvert += a1 - a0
        parts.append(
            _Part(
                idx_debut=idx_a,
                idx_noeud=idx_b if a1 >= d1 - EPSILON_M else None,
                longueur_m=a1 - a0,
                fin_m=couvert,
            )
        )
        derniere = (idx_a, idx_b, d0, d1)

    if derniere is None:
        return vide
    idx_a, idx_b, d0, d1 = derniere
    points.append(
        _interpoler(trace.points[idx_a], trace.points[idx_b], (min(d1, fin) - d0) / (d1 - d0))
    )
    return _Couloir(
        points=points,
        parts=parts,
        longueur_m=couvert,
        tronque=couvert < longueur_m - EPSILON_M,
    )


def _intervalles(trace: Trace, total: float, boucle: bool):
    """`(idx_a, idx_b, d0, d1)` de chaque intervalle, un second tour si `boucle`.

    Le second tour est le premier décalé de la longueur du tracé. La jointure
    saute du dernier point au premier, distants de moins de `FERMETURE_M` :
    c'est la définition d'une boucle fermée, et l'écart reste sous 300 m.
    """
    for tour in (0.0, total) if boucle else (0.0,):
        for i in range(len(trace.points) - 1):
            d0 = trace.points[i].dist_m + tour
            d1 = trace.points[i + 1].dist_m + tour
            if d1 > d0:
                yield (i, i + 1, d0, d1)


def _position(position_m: float, total: float, boucle: bool) -> float:
    """Ramène une position dans le tracé : modulo sur une boucle, bornée sinon."""
    if not math.isfinite(position_m):
        return 0.0
    if boucle:
        return position_m % total
    return min(max(position_m, 0.0), total)


def _interpoler(a: PointTrace, b: PointTrace, fraction: float) -> PointTrace:
    """Le point à `fraction` du chemin de `a` vers `b` (altitude comprise)."""
    f = min(max(fraction, 0.0), 1.0)
    alt = None
    if a.alt_m is not None and b.alt_m is not None:
        alt = a.alt_m + (b.alt_m - a.alt_m) * f
    elif f <= 0.5:
        alt = a.alt_m
    else:
        alt = b.alt_m
    return PointTrace(
        lat=a.lat + (b.lat - a.lat) * f,
        lon=a.lon + (b.lon - a.lon) * f,
        alt_m=alt,
        dist_m=a.dist_m + (b.dist_m - a.dist_m) * f,
    )


def _longueur(trace: Trace) -> float:
    """La longueur du tracé telle que les points la portent, en mètres.

    C'est `points[-1].dist_m` et non `trace.distance_m` : les positions
    demandées à ce module se comparent aux distances cumulées des points, et
    le moteur annonce parfois une distance légèrement différente.
    """
    if len(trace.points) < 2:
        return 0.0
    longueur = trace.points[-1].dist_m
    return longueur if math.isfinite(longueur) and longueur > 0 else 0.0


# --- carrefours ---------------------------------------------------------------


def _carrefours(trace: Trace, couloir: _Couloir) -> tuple[int, int, dict[str, int]]:
    """(nœuds tagués, virages marqués, compte par nature) sous le couloir.

    Les deux se comptent à part parce qu'ils ne coûtent pas la même chose : un
    feu arrête, un virage fait ralentir. `NoteBloc.carrefours` en donne la
    somme, la note les tarife séparément.

    Un feu **est** un virage quand la route tourne : le compter deux fois
    doublerait la pénalité du carrefour le plus banal. Un virage marqué
    tombant à moins de `DEDOUBLONNAGE_M` d'un nœud tagué est donc ignoré.
    Le compte par nature ne sert qu'aux motifs.
    """
    tagues = _noeuds_tagues(trace, couloir)
    natures: dict[str, int] = {}
    for _, nature in tagues:
        natures[nature] = natures.get(nature, 0) + 1

    positions = [position for position, _ in tagues]
    geometriques = 0
    for virage in virages_detectes(couloir.points, angle_deg=ANGLE_CARREFOUR_DEG):
        ou = _position_dans_couloir(couloir, virage.sommet_idx)
        if any(abs(ou - position) <= DEDOUBLONNAGE_M for position in positions):
            continue  # déjà compté par son nœud
        geometriques += 1
    if geometriques:
        natures["virage"] = geometriques
    return (len(tagues), geometriques, natures)


def _position_dans_couloir(couloir: _Couloir, idx_point: int) -> float:
    """La distance cumulée, depuis le début du couloir, du `idx_point`-ième point."""
    if idx_point <= 0:
        return 0.0
    if idx_point - 1 < len(couloir.parts):
        return couloir.parts[idx_point - 1].fin_m
    return couloir.longueur_m


def _noeuds_tagues(trace: Trace, couloir: _Couloir) -> list[tuple[float, str]]:
    """Les nœuds tagués traversés, chacun à sa position dans le couloir.

    `Segment.node_tags` décrit le nœud **de fin** du tronçon : c'est donc
    `fin_idx` qui porte le tag. Un tracé sans segments n'en a aucun — et ne
    prétend pas qu'il n'y a pas de feu, voir le motif « routes inconnues ».
    """
    natures = {
        segment.fin_idx: segment.node_tags.get("highway", "")
        for segment in trace.segments
        if segment.node_tags.get("highway", "") in NOEUDS_CARREFOUR
    }
    if not natures:
        return []
    return [
        (part.fin_m, natures[part.idx_noeud])
        for part in couloir.parts
        if part.idx_noeud is not None and part.idx_noeud in natures
    ]


# --- zone bâtie ---------------------------------------------------------------


def _zone_batie(trace: Trace, couloir: _Couloir) -> tuple[float, bool]:
    """(kilomètres bâtis, tags disponibles ?).

    Ce sont les tags du **tronçon** parcouru, pas ceux de son point de départ :
    le point de départ d'un tronçon est aussi le point d'arrivée du précédent,
    et c'est par là que le village traversé pendant la récupération se
    retrouvait facturé au bloc qui suit (décision du 13/09 : aucune évaluation
    sous une récup).

    Sans `segments` — un tracé relu d'une activité enregistrée — on ne sait
    rien des routes : 0 km bâti, et le second membre est faux pour que le
    motif « routes inconnues » le dise.
    """
    if not trace.segments:
        return (0.0, False)
    tags = tags_par_troncon(trace.points, trace.segments)
    metres = 0.0
    connu = False
    for part in couloir.parts:
        if not (0 <= part.idx_debut < len(tags)):
            continue
        du_point = tags[part.idx_debut]
        if du_point is None:
            continue
        connu = True
        if _bati(du_point):
            metres += part.longueur_m
    return (metres / 1000.0, connu)


def _bati(tags: dict[str, str]) -> bool:
    """Vrai pour une route de village, ou pour une route limitée à 50 ou moins."""
    if tags.get("highway", "") in HIGHWAY_BATI:
        return True
    limite = _maxspeed_kmh(tags.get("maxspeed"))
    return limite is not None and limite <= MAXSPEED_BATI_KMH


def _maxspeed_kmh(brut: str | None) -> float | None:
    """La limite en km/h, ou `None` si le tag est absent ou non numérique.

    OSM écrit « 50 », parfois « 30 mph », souvent « FR:urban » ou « walk » :
    seul le cas numérique est exploité, le reste est une ignorance, pas un 0.
    """
    if not brut:
        return None
    morceaux = str(brut).split()
    try:
        valeur = float(morceaux[0])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(valeur) or valeur <= 0:
        return None
    if len(morceaux) > 1 and morceaux[1].lower() == "mph":
        return valeur * 1.609344
    return valeur


# --- pentes -------------------------------------------------------------------


@dataclass(frozen=True)
class _Releve:
    pente_moyenne: float  # tangente
    pente_max: float  # tangente, signée
    descente_m: float
    montee_m: float
    irregularite: float  # écart-type des pentes, en tangente lui aussi
    descentes: list[float]  # longueur de chaque descente qualifiante, en mètres
    altitude_connue: bool


def _releve_pentes(couloir: _Couloir) -> _Releve:
    """Pentes, descentes et montées du couloir, mesurées par pas de ~100 m."""
    vide = _Releve(
        pente_moyenne=0.0,
        pente_max=0.0,
        descente_m=0.0,
        montee_m=0.0,
        irregularite=0.0,
        descentes=[],
        altitude_connue=False,
    )
    profil = [(p.dist_m, p.alt_m) for p in couloir.points if p.alt_m is not None]
    if len(profil) < 2 or couloir.longueur_m <= 0:
        return vide
    pas = _pas_de_pente(profil)
    if not pas:
        return vide

    pentes = [pente for _, _, pente in pas]
    descentes = _descentes(pas)
    return _Releve(
        pente_moyenne=_pente_moyenne(profil, couloir.longueur_m),
        pente_max=max(pentes, key=abs),
        descente_m=sum(chute for _, chute in descentes),
        montee_m=sum(denivele for _, denivele, pente in pas if pente > PENTE_MONTEE_TOLEREE),
        irregularite=statistics.pstdev(pentes) if len(pentes) > 1 else 0.0,
        descentes=[longueur for longueur, _ in descentes],
        altitude_connue=True,
    )


def _pente_moyenne(profil: list[tuple[float, float]], longueur_m: float) -> float:
    """Le dénivelé du profil divisé par la longueur **sur laquelle il est mesuré**.

    `profil` ne retient que les points qui portent une altitude : sur un couloir
    dont la moitié est sans altitude, diviser par la longueur du couloir donnait
    une pente moyenne deux fois trop faible. C'est cette pente-là qui décide du
    demi-tour (`placement.PENTE_DEMI_TOUR_MAX`), donc la sous-estimer autorisait
    un demi-tour dans une côte — précisément la condition que le mainteneur a
    posée.

    On divise donc par l'étendue du profil, et par la longueur du couloir
    seulement si cette étendue est nulle (tous les points d'altitude à la même
    distance), auquel cas il n'y a de toute façon rien à mesurer.
    """
    etendue = profil[-1][0] - profil[0][0]
    denivele = profil[-1][1] - profil[0][1]
    if etendue > 0:
        return denivele / etendue
    return denivele / longueur_m if longueur_m > 0 else 0.0


def _pas_de_pente(profil: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """Le couloir en pas d'au moins `PAS_PENTE_M` : (longueur, dénivelé, pente en tangente).

    Le dernier pas peut être plus court que `PAS_PENTE_M` : on ne jette pas la
    fin du bloc, mais on ne la rallonge pas non plus. Un couloir plus court
    qu'un pas rend un pas unique.
    """
    pas: list[tuple[float, float, float]] = []
    d0, a0 = profil[0]
    for d1, a1 in profil[1:]:
        if d1 - d0 < PAS_PENTE_M:
            continue
        longueur = d1 - d0
        pas.append((longueur, a1 - a0, (a1 - a0) / longueur))
        d0, a0 = d1, a1
    reste = profil[-1][0] - d0
    if reste > 0:
        pas.append((reste, profil[-1][1] - a0, (profil[-1][1] - a0) / reste))
    return pas


def _descentes(pas: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """Les descentes qualifiantes : (longueur en m, dénivelé perdu en m, positif).

    Une descente est une suite de pas consécutifs sous `PENTE_DESCENTE`,
    d'une longueur totale supérieure à `LONGUEUR_DESCENTE_M`. Le pas neutre
    ajouté en fin de liste sert à fermer la dernière suite.
    """
    trouvees: list[tuple[float, float]] = []
    longueur = chute = 0.0
    for pas_longueur, denivele, pente in [*pas, (0.0, 0.0, 0.0)]:
        if pas_longueur > 0 and pente < PENTE_DESCENTE:
            longueur += pas_longueur
            chute += -denivele
            continue
        if longueur > LONGUEUR_DESCENTE_M:
            trouvees.append((longueur, chute))
        longueur = chute = 0.0
    return trouvees


# --- motifs -------------------------------------------------------------------


def _motifs(
    *,
    couloir: _Couloir,
    motifs_carrefours: dict[str, int],
    km_batis: float,
    routes_connues: bool,
    releve: _Releve,
) -> list[str]:
    """Les motifs lisibles, du plus coûteux au moins coûteux."""
    pesees: list[tuple[float, str]] = []
    if couloir.tronque:
        pesees.append((PENALITE_BLOC_TRONQUE, "bloc plus long que le tracé disponible"))
    if releve.descentes:
        pesees.append((releve.descente_m * POIDS_M_DESCENTE, _motif_descentes(releve)))
    for nature, nombre in motifs_carrefours.items():
        poids = POIDS_VIRAGE_MARQUE if nature == "virage" else POIDS_CARREFOUR
        pesees.append((nombre * poids, _motif_carrefour(nature, nombre)))
    if km_batis > 0:
        pesees.append((km_batis * POIDS_KM_BATI, f"{_nombre(km_batis)} km en zone bâtie"))
    if releve.montee_m > 0:
        pesees.append(
            (
                releve.montee_m * POIDS_M_MONTEE,
                f"montée de {releve.montee_m:.0f} m au-delà de "
                f"{_pourcent(PENTE_MONTEE_TOLEREE)}",
            )
        )
    if releve.irregularite >= SEUIL_MOTIF_IRREGULARITE:
        pesees.append(
            (
                releve.irregularite * POIDS_IRREGULARITE,
                f"pente irrégulière (± {_pourcent(releve.irregularite)})",
            )
        )
    motifs = [motif for _, motif in sorted(pesees, key=lambda p: -p[0])]
    # Les ignorances viennent en dernier : elles ne coûtent rien, mais elles
    # doivent être lues avec la note.
    if not releve.altitude_connue:
        motifs.append("altitude inconnue")
    if not routes_connues:
        motifs.append("routes inconnues")
    return motifs


def _motif_descentes(releve: _Releve) -> str:
    if len(releve.descentes) == 1:
        return f"descente de {_nombre(releve.descentes[0] / 1000.0)} km"
    return (
        f"{_en_lettres(len(releve.descentes), feminin=True)} descentes, "
        f"{releve.descente_m:.0f} m de dénivelé"
    )


#: Comment nommer chaque nature de carrefour au singulier et au pluriel, avec
#: son genre — « deux feux », « une priorité à droite ».
LIBELLES_CARREFOUR: dict[str, tuple[str, str, bool]] = {
    "traffic_signals": ("feu", "feux", False),
    "stop": ("stop", "stops", False),
    "give_way": ("cédez-le-passage", "cédez-le-passage", False),
    "mini_roundabout": ("rond-point", "ronds-points", False),
    "crossing": ("passage piéton", "passages piétons", False),
    "virage": ("virage marqué", "virages marqués", False),
}


def _motif_carrefour(nature: str, nombre: int) -> str:
    singulier, pluriel, feminin = LIBELLES_CARREFOUR.get(nature, ("carrefour", "carrefours", False))
    mot = singulier if nombre == 1 else pluriel
    return f"{_en_lettres(nombre, feminin=feminin)} {mot}"


#: Les petits nombres s'écrivent en toutes lettres dans les motifs : « deux
#: feux » se lit mieux que « 2 feux ». Au-delà, le chiffre reprend la main.
_LETTRES = ("zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf")


def _en_lettres(nombre: int, *, feminin: bool = False) -> str:
    if nombre == 1:
        return "une" if feminin else "un"
    if 0 <= nombre < len(_LETTRES):
        return _LETTRES[nombre]
    return str(nombre)


def _nombre(valeur: float) -> str:
    """Un nombre à une décimale, virgule française."""
    return f"{valeur:.1f}".replace(".", ",")


def _pourcent(pente: float) -> str:
    """Une pente (tangente) écrite en pourcentage : 0,015 → « 1,5 % ».

    Le seul endroit du module où une pente devient un pourcentage : un motif
    se lit, il ne se calcule pas.
    """
    return f"{_nombre(100.0 * pente)} %"


# --- tags à une position ------------------------------------------------------


def _tags_a(trace: Trace, position_m: float) -> dict[str, str] | None:
    """Les tags du tronçon qui porte cette position, `None` si on ne sait pas.

    Le tronçon parcouru, pas le point qui l'ouvre : à dix mètres après une
    jonction, on est sur la nouvelle route, pas sur celle qu'on vient de
    quitter.
    """
    if not trace.segments or len(trace.points) < 2:
        return None
    total = _longueur(trace)
    if total <= 0:
        return None
    position = _position(position_m, total, trace.bornee())
    idx = _point_a(trace, position)
    tags = tags_par_troncon(trace.points, trace.segments)
    return tags[idx] if 0 <= idx < len(tags) else None


def _point_a(trace: Trace, position_m: float) -> int:
    """L'indice du point du tracé qui précède cette distance cumulée."""
    for i in range(len(trace.points) - 1):
        if trace.points[i + 1].dist_m > position_m:
            return i
    return len(trace.points) - 2

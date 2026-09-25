"""Coûts d'un tracé : trafic, revêtement, virages à gauche, sens de la boucle.

Ce que le cycliste veut éviter, dans l'ordre : les routes passantes, les
portions non revêtues sur un vélo de route, et les virages à gauche — qui
coupent la circulation et coûtent un arrêt, surtout sur une route à trafic.
Le sens de la boucle compte aussi : à droite en France, une boucle prise
dans le bon sens présente moins de tourne-à-gauche.

Le score agrège tout ça en **kilomètres équivalents** : plus bas = mieux.
Tous les poids sont des constantes nommées ci-dessous, jamais des nombres
enfouis dans une formule. Depuis le sprint 3, le poids d'une classe de route
peut aussi être **appris** sur les sorties réelles du cycliste et injecté par
la ligne de commande (`evaluer(..., poids=...)`) : les constantes restent le
cas par défaut, celui d'un cycliste dont on ne sait rien.

Sans `segments` (un GPX importé n'en a pas), les kilomètres par type de
route ne sont pas calculables : ils valent 0 et `trace.meta["couts_partiels"]`
passe à `True` pour que l'affichage ne fasse pas passer une ignorance pour
une mesure (règle absolue 5). Un tronçon dont la longueur est absurde
(négative, NaN, infinie) est écarté du calcul plutôt que soustrait des
kilomètres réels, et compté dans `trace.meta["segments_ignores"]` — pour la
même raison : une ignorance se dit, elle ne se déguise pas en mesure.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from ourouler.boucle.antennes import detecter
from ourouler.noyau.trace import PointTrace, Segment, Trace, cap_deg, distance_m, sens_boucle

# --- classes de routes et de revêtements ------------------------------------

#: `highway` des routes que l'on compte « à trafic » : passantes et rapides.
HIGHWAY_TRAFIC = frozenset(
    {"primary", "primary_link", "secondary", "secondary_link", "trunk"}
)

#: `highway` des routes que l'on compte « calmes ».
HIGHWAY_CALME = frozenset(
    {
        "tertiary",
        "unclassified",
        "residential",
        "cycleway",
        "track",
        "service",
        "living_street",
    }
)

#: `surface` que l'on compte non revêtues pour un vélo de route.
SURFACES_NON_REVETUES = frozenset(
    {"gravel", "unpaved", "dirt", "ground", "grass", "compacted", "fine_gravel", "sand"}
)

#: `highway` comptés non revêtus quand aucune `surface` n'est renseignée : un
#: chemin d'exploitation sans tag de surface n'est pratiquement jamais bitumé.
HIGHWAY_NON_REVETU_SANS_SURFACE = frozenset({"track"})

# --- poids du score (en kilomètres équivalents) ------------------------------

#: Un kilomètre de route à trafic « coûte » autant que 3 km de route calme.
POIDS_KM_TRAFIC = 3.0

#: Poids par classe `highway`, en kilomètres équivalents par kilomètre roulé.
#: C'est la forme générale du score : les constantes ci-dessus en sont le cas
#: par défaut. `apprentissage.routes.poids_appris` produit un dictionnaire de
#: même forme, appris sur les sorties du cycliste, que la ligne de commande
#: injecte dans `evaluer`.
POIDS_HIGHWAY_DEFAUT: dict[str, float] = {h: POIDS_KM_TRAFIC for h in sorted(HIGHWAY_TRAFIC)}

#: Ce que coûte une classe absente du dictionnaire de poids. Zéro, jamais
#: autre chose : une classe qu'on ne sait pas juger ne se pénalise pas
#: (« inconnu » n'est jamais un malus, contrat du sprint 3 §2).
POIDS_HIGHWAY_INCONNU = 0.0
#: Un kilomètre non revêtu en coûte 4.
POIDS_KM_NON_REVETU = 4.0
#: Un tourne-à-gauche ordinaire.
POIDS_VIRAGE_GAUCHE = 0.3
#: Un tourne-à-gauche dont le tronçon entrant ou sortant est à trafic, en plus.
POIDS_VIRAGE_GAUCHE_TRAFIC = 1.0
#: Boucle prise dans l'autre sens que celui demandé.
PENALITE_MAUVAIS_SENS = 2.0

# --- détection des virages ---------------------------------------------------

#: Espacement minimal entre deux points servant à calculer un cap. En dessous,
#: le bruit GPS (quelques mètres) domine l'angle et invente des virages.
ESPACEMENT_CAP_M = 15.0
#: Changement de cap à partir duquel on parle de virage (négatif = à gauche).
ANGLE_VIRAGE_DEG = 45.0
#: Longueur au-delà de laquelle un changement de cap n'est plus un virage mais
#: une courbe : les 45° doivent être pris en moins de 60 m.
LONGUEUR_VIRAGE_M = 60.0

#: Tolérance de flottant autour du demi-tour exact. Un changement de cap de
#: 180° n'est ni à gauche ni à droite : on repart d'où l'on vient, le signe
#: n'a pas de sens géométrique. Compter un aller-retour comme un
#: tourne-à-gauche le pénalisait pour un virage qu'il ne fait pas.
EPSILON_DEMI_TOUR_DEG = 1e-6

SENS_INDETERMINE = "indetermine"


@dataclass
class Couts:
    """Ce qu'un tracé coûte au cycliste. `score` : plus bas = mieux."""

    km_trafic: float
    km_calme: float
    #: Kilomètres de tronçons dont le `highway` est absent ou d'une classe
    #: qu'on ne connaît pas (`path`, `footway`, `steps`, une valeur OSM
    #: nouvelle). Ni trafic ni calme : sans ce chiffre, un tracé à moitié sur
    #: des chemins non classés s'affichait « 0,0 km de trafic » comme un tracé
    #: parfaitement calme.
    km_non_classe: float
    km_non_revetu: float
    #: Mètres d'antennes (aller-retour dans un cul-de-sac) **avant** élagage,
    #: pour information : le tracé proposé n'en a plus. Ils viennent de
    #: `trace.meta["antennes"]` quand la génération les a déjà mesurés, d'une
    #: détection à la volée sinon (un GPX importé, lui, n'est pas élagué).
    #: Le score ne les compte pas : ce qui a été retiré n'a plus de coût.
    antennes_m: float
    virages_gauche: int
    virages_gauche_trafic: int  # sous-ensemble de `virages_gauche`
    virages_droite: int
    sens: str  # "horaire" | "antihoraire" | "indetermine"
    score: float
    #: Kilomètres par classe `highway`, telle que le moteur l'a écrite. C'est
    #: la matière du score dès que les poids sont appris : `km_trafic` et
    #: `km_calme` n'en sont qu'un résumé en deux cases.
    km_par_highway: dict[str, float] = field(default_factory=dict)
    #: Moyenne du `CostPerKm` du moteur, pondérée par la longueur des
    #: tronçons — le jugement du routeur lui-même sur le trafic du tracé.
    #: `None` quand aucun tronçon ne le donne (GPX importé) : jamais 0, qui
    #: voudrait dire « tracé idéal ».
    cout_km_moyen: float | None = None


def evaluer(
    trace: Trace, *, sens_prefere: str = "horaire", poids: dict[str, float] | None = None
) -> Couts:
    """Les coûts du tracé, et le score qui les agrège en kilomètres équivalents.

    `sens_prefere` vaut « horaire » ou « antihoraire ». Un tracé dont le sens
    est indéterminé (aller-retour, tracé non bouclé) est pénalisé comme un
    mauvais sens : on ne sait pas, donc on ne promet rien.

    `poids` associe un coût en kilomètres équivalents à chaque classe
    `highway`. Absent, c'est `POIDS_HIGHWAY_DEFAUT` — les constantes
    historiques, donc exactement le score du sprint 2. Fourni, il vient de
    `apprentissage.routes.poids_appris` et c'est **la ligne de commande** qui
    l'injecte : ce module ne lit aucun fichier. Une classe absente du
    dictionnaire ne coûte rien (`POIDS_HIGHWAY_INCONNU`) : on ne pénalise pas
    ce qu'on ne sait pas juger.

    Un tronçon à la longueur absurde est écarté et compté dans
    `trace.meta["segments_ignores"]` : mieux vaut un kilométrage incomplet et
    signalé qu'un kilométrage négatif ou NaN.
    """
    bareme = POIDS_HIGHWAY_DEFAUT if poids is None else poids
    segments = _segments_utilisables(trace)
    km_trafic, km_calme, km_non_classe, km_non_revetu = _kilometrages(trace, segments)
    km_par_highway = _km_par_highway(segments)
    gauche, gauche_trafic, droite = _virages(trace, segments)
    sens = sens_boucle(trace)

    km_ponderes = sum(
        km * bareme.get(highway, POIDS_HIGHWAY_INCONNU) for highway, km in km_par_highway.items()
    )
    score = (
        km_ponderes
        + km_non_revetu * POIDS_KM_NON_REVETU
        + gauche * POIDS_VIRAGE_GAUCHE
        + gauche_trafic * POIDS_VIRAGE_GAUCHE_TRAFIC
        + (0.0 if sens == sens_prefere else PENALITE_MAUVAIS_SENS)
    )
    return Couts(
        km_trafic=km_trafic,
        km_calme=km_calme,
        km_non_classe=km_non_classe,
        km_non_revetu=km_non_revetu,
        antennes_m=_antennes_m(trace),
        virages_gauche=gauche,
        virages_gauche_trafic=gauche_trafic,
        virages_droite=droite,
        sens=sens,
        score=score,
        km_par_highway=km_par_highway,
        cout_km_moyen=_cout_km_moyen(segments),
    )


# --- antennes -----------------------------------------------------------------


def _antennes_m(trace: Trace) -> float:
    """Les mètres d'antennes du tracé, avant élagage s'il a eu lieu.

    Une candidate générée par `boucle.candidates` est déjà élaguée : la mesure
    est dans `meta["antennes"]`, et la redétecter rendrait 0. Un GPX importé,
    lui, n'est pas élagué — on le mesure alors à la volée, sinon la colonne
    afficherait « 0 m d'antennes » pour un tracé qui en est plein (règle
    absolue 5 : une ignorance ne se déguise pas en mesure).
    """
    mesure = trace.meta.get("antennes")
    if isinstance(mesure, dict):
        retires = mesure.get("metres_retires")
        if isinstance(retires, (int, float)) and not isinstance(retires, bool):
            return float(retires)
    return sum(a.longueur_m for a in detecter(trace))


# --- kilomètres par classe de route ------------------------------------------


def _km_par_highway(segments: Sequence[Segment]) -> dict[str, float]:
    """Kilomètres par classe `highway`, la classe absente sous la clé vide."""
    par_classe: dict[str, float] = {}
    for segment in segments:
        highway = segment.tags.get("highway", "")
        par_classe[highway] = par_classe.get(highway, 0.0) + segment.longueur_m / 1000.0
    return par_classe


def _cout_km_moyen(segments: Sequence[Segment]) -> float | None:
    """Moyenne du `CostPerKm` du moteur pondérée par la longueur, `None` sans donnée."""
    pondere = 0.0
    longueur = 0.0
    for segment in segments:
        if segment.cout_km is None or not math.isfinite(segment.cout_km):
            continue
        pondere += segment.cout_km * segment.longueur_m
        longueur += segment.longueur_m
    return pondere / longueur if longueur > 0 else None


def _segments_utilisables(trace: Trace) -> list[Segment]:
    """Les tronçons exploitables ; les autres sont comptés dans `meta`.

    BRouter n'a aucune raison d'annoncer une longueur négative ou NaN, mais un
    GPX bricolé ou un jour de panne le peuvent. Retrancher un tel tronçon des
    kilomètres ferait un `km_trafic` négatif et un `score` faux, sans que rien
    ne le dise : on l'écarte, et on écrit combien on en a écarté.
    """
    gardes = [s for s in trace.segments if _longueur_exploitable(s.longueur_m)]
    ignores = len(trace.segments) - len(gardes)
    if ignores:
        trace.meta["segments_ignores"] = ignores
    return gardes


def _longueur_exploitable(longueur_m: object) -> bool:
    """Vrai pour une longueur de tronçon utilisable : un nombre fini et positif ou nul."""
    if not isinstance(longueur_m, (int, float)) or isinstance(longueur_m, bool):
        return False
    return math.isfinite(longueur_m) and longueur_m >= 0


def _kilometrages(
    trace: Trace, segments: Sequence[Segment]
) -> tuple[float, float, float, float]:
    """(trafic, calme, non classé, non revêtu) en km. Tout à 0 sans segments."""
    if not segments:
        # Un GPX importé ne dit rien des routes empruntées : on le marque
        # plutôt que de laisser croire à 0 km de trafic. Un tracé dont tous
        # les tronçons ont été écartés est dans le même cas.
        trace.meta["couts_partiels"] = True
        return (0.0, 0.0, 0.0, 0.0)

    trafic = calme = non_classe = non_revetu = 0.0
    for segment in segments:
        km = segment.longueur_m / 1000.0
        highway = segment.tags.get("highway", "")
        if highway in HIGHWAY_TRAFIC:
            trafic += km
        elif highway in HIGHWAY_CALME:
            calme += km
        else:
            # Un segment sans `highway` (ou d'une classe inconnue) n'est ni
            # trafic ni calme : il n'est pas « calme » par défaut, mais il ne
            # s'évapore plus non plus du kilométrage.
            non_classe += km
        if _non_revetu(segment.tags):
            non_revetu += km
    return (trafic, calme, non_classe, non_revetu)


def _non_revetu(tags: dict[str, str]) -> bool:
    """Vrai si la `surface` est non revêtue, ou si c'est un `track` sans surface."""
    surface = tags.get("surface")
    if surface is not None:
        return surface in SURFACES_NON_REVETUES
    return tags.get("highway", "") in HIGHWAY_NON_REVETU_SANS_SURFACE


# --- virages -----------------------------------------------------------------


@dataclass(frozen=True)
class Virage:
    """Un changement de direction marqué, détecté sur la seule géométrie.

    Les indices sont ceux de la liste de points passée à `virages_detectes`.
    `entrant` et `sortant` bornent les tronçons qui entrent dans le virage et
    qui en sortent, au sens d'une tranche `points[debut:fin]`.
    """

    amplitude_deg: float  # signée, négative à gauche
    sommet_idx: int  # premier point du virage
    entrant: tuple[int, int]
    sortant: tuple[int, int]


def virages_detectes(
    points: Sequence[PointTrace], *, angle_deg: float = ANGLE_VIRAGE_DEG
) -> list[Virage]:
    """Les virages d'au moins `angle_deg`, demi-tours exclus.

    Les caps sont calculés entre des points espacés d'au moins
    `ESPACEMENT_CAP_M` : sans ce sous-échantillonnage, deux points GPS
    consécutifs à 2 m l'un de l'autre donnent un cap dominé par le bruit et
    une boucle bien lisse se retrouve pleine de « virages ».

    Un demi-tour exact (±180°) n'est pas un virage : voir
    `EPSILON_DEMI_TOUR_DEG`. Il est quand même consommé, sinon il serait
    réexaminé au décalage suivant.

    `angle_deg` est le seul réglage : les coûts d'un tracé comptent les
    tourne-à-gauche à partir de 45° (`ANGLE_VIRAGE_DEG`), `seance.terrain`
    compte les carrefours traversés sous un bloc à partir de 60°. La
    mécanique, elle, est la même des deux côtés.
    """
    indices = _indices_espaces(points, ESPACEMENT_CAP_M)
    if len(indices) < 3:
        return []
    noeuds = [points[i] for i in indices]
    caps = [cap_deg(a, b) for a, b in zip(noeuds[:-1], noeuds[1:], strict=True)]

    trouves: list[Virage] = []
    i = 0
    while i + 1 < len(caps):
        j, cumul = _accumuler(caps, noeuds, i, angle_deg)
        if cumul is None:
            i += 1
            continue
        if abs(cumul) < 180.0 - EPSILON_DEMI_TOUR_DEG:
            trouves.append(
                Virage(
                    amplitude_deg=cumul,
                    sommet_idx=indices[i + 1],
                    entrant=(indices[i], indices[i + 1]),
                    sortant=(indices[j + 1], indices[j + 2]),
                )
            )
        # Le virage consomme les caps i..j+1 : on repart du tronçon sortant,
        # sinon un virage à 90° serait recompté à chaque décalage.
        i = j + 1
    return trouves


def _virages(trace: Trace, segments: Sequence[Segment]) -> tuple[int, int, int]:
    """(gauche, gauche à trafic, droite), à partir de `ANGLE_VIRAGE_DEG`."""
    a_trafic = _points_a_trafic(trace.points, segments)
    gauche = gauche_trafic = droite = 0
    for virage in virages_detectes(trace.points):
        if virage.amplitude_deg <= -ANGLE_VIRAGE_DEG:
            gauche += 1
            entrant = _troncon_a_trafic(a_trafic, *virage.entrant)
            sortant = _troncon_a_trafic(a_trafic, *virage.sortant)
            if entrant or sortant:
                gauche_trafic += 1
        else:
            droite += 1
    return (gauche, gauche_trafic, droite)


def _accumuler(
    caps: Sequence[float], noeuds: Sequence[PointTrace], i: int, angle_deg: float
) -> tuple[int, float | None]:
    """Cumule les changements de cap depuis `caps[i]` tant qu'on reste sous 60 m.

    Renvoie `(j, cumul)` où `caps[j + 1]` est le tronçon sortant du virage,
    ou `(i, None)` si `angle_deg` n'est pas atteint dans la fenêtre. Le premier
    changement est toujours examiné : un virage sec à 90° entre deux tronçons
    ne doit pas dépendre de leur longueur.
    """
    cumul = 0.0
    longueur = 0.0
    j = i
    while j + 1 < len(caps):
        cumul += _ecart_cap(caps[j], caps[j + 1])
        if abs(cumul) >= angle_deg:
            return (j, cumul)
        longueur += distance_m(noeuds[j + 1], noeuds[j + 2])
        if longueur > LONGUEUR_VIRAGE_M:
            return (i, None)
        j += 1
    return (i, None)


def _ecart_cap(depuis: float, vers: float) -> float:
    """Changement de cap signé, ramené dans [−180, 180) : négatif = à gauche.

    Le modulo est ce qui fait que passer du cap 350° au cap 10° est un petit
    virage **à droite** (+20°) et non un demi-tour à gauche (−340°). Le cas
    se présente à chaque passage par le nord, donc sur toute boucle.

    L'intervalle est fermé à gauche : un demi-tour exact rend −180, jamais
    +180. C'est sans conséquence, parce que `_virages` ne compte un demi-tour
    d'aucun côté — le signe n'y a pas de sens géométrique.
    """
    return (vers - depuis + 180.0) % 360.0 - 180.0


def _indices_espaces(points: Sequence[PointTrace], espacement_m: float) -> list[int]:
    """Indices des points retenus, chacun à au moins `espacement_m` du précédent retenu."""
    if not points:
        return []
    gardes = [0]
    for i in range(1, len(points)):
        if distance_m(points[gardes[-1]], points[i]) >= espacement_m:
            gardes.append(i)
    return gardes


def _points_a_trafic(
    points: Sequence[PointTrace], segments: Sequence[Segment]
) -> list[bool]:
    """Pour chaque point du tracé : le segment qui le porte est-il à trafic ?"""
    tags = tags_par_point(points, segments)
    return [t is not None and t.get("highway", "") in HIGHWAY_TRAFIC for t in tags]


def tags_par_point(
    points: Sequence[PointTrace], segments: Sequence[Segment]
) -> list[dict[str, str] | None]:
    """Les tags du segment couvrant chaque point, `None` si aucun ne le couvre.

    Un point de jonction appartient aux **deux** segments qui s'y touchent ;
    c'est le premier qui l'emporte. Cette correspondance répond donc à « suis-je
    passé par une route à trafic ? » et non à « sur quelle route suis-je entre
    ce point et le suivant ? » : pour cette question-là, qui est celle d'une
    longueur parcourue, c'est `tags_par_troncon` qu'il faut.
    """
    tags: list[dict[str, str] | None] = [None] * len(points)
    for segment in segments:
        debut = max(0, segment.debut_idx)
        fin = min(len(points) - 1, segment.fin_idx)
        for i in range(debut, fin + 1):
            if tags[i] is None:  # en cas de recouvrement, le premier segment gagne
                tags[i] = segment.tags
    return tags


def tags_par_troncon(
    points: Sequence[PointTrace], segments: Sequence[Segment]
) -> list[dict[str, str] | None]:
    """Les tags du segment couvrant chaque **intervalle** `[i, i + 1]`.

    Un tronçon, lui, n'appartient qu'à un seul segment : la liste rendue a un
    élément de moins que `points`, et l'élément `i` décrit ce qu'on a sous les
    roues entre le point `i` et le point `i + 1`.

    Public depuis le sprint 4 : `seance.terrain` mesure des kilomètres bâtis
    sous un bloc, donc des longueurs, et il n'y a pas deux façons de
    construire cette correspondance. La différence avec `tags_par_point` n'est
    pas cosmétique : attribuer à l'intervalle qui *commence* au point `i` les
    tags du segment qui *finit* en `i` faisait payer à un bloc le village
    traversé juste avant lui, pendant la récupération.
    """
    tags: list[dict[str, str] | None] = [None] * max(len(points) - 1, 0)
    for segment in segments:
        debut = max(0, segment.debut_idx)
        fin = min(len(tags), segment.fin_idx)
        for i in range(debut, fin):
            if tags[i] is None:  # en cas de recouvrement, le premier segment gagne
                tags[i] = segment.tags
    return tags


def _troncon_a_trafic(a_trafic: Sequence[bool], debut: int, fin: int) -> bool:
    """Vrai si au moins un point du tronçon `[debut, fin[` est sur une route à trafic."""
    return any(a_trafic[debut:fin])

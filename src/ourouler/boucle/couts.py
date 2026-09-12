"""Coûts d'un tracé : trafic, revêtement, virages à gauche, sens de la boucle.

Ce que le cycliste veut éviter, dans l'ordre : les routes passantes, les
portions non revêtues sur un vélo de route, et les virages à gauche — qui
coupent la circulation et coûtent un arrêt, surtout sur une route à trafic.
Le sens de la boucle compte aussi : à droite en France, une boucle prise
dans le bon sens présente moins de tourne-à-gauche.

Le score agrège tout ça en **kilomètres équivalents** : plus bas = mieux.
Tous les poids sont des constantes nommées ci-dessous, jamais des nombres
enfouis dans une formule.

Sans `segments` (un GPX importé n'en a pas), les kilomètres par type de
route ne sont pas calculables : ils valent 0 et `trace.meta["couts_partiels"]`
passe à `True` pour que l'affichage ne fasse pas passer une ignorance pour
une mesure (règle absolue 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m, sens_boucle

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

SENS_INDETERMINE = "indetermine"


@dataclass
class Couts:
    """Ce qu'un tracé coûte au cycliste. `score` : plus bas = mieux."""

    km_trafic: float
    km_calme: float
    km_non_revetu: float
    virages_gauche: int
    virages_gauche_trafic: int  # sous-ensemble de `virages_gauche`
    virages_droite: int
    sens: str  # "horaire" | "antihoraire" | "indetermine"
    score: float


def evaluer(trace: Trace, *, sens_prefere: str = "horaire") -> Couts:
    """Les coûts du tracé, et le score qui les agrège en kilomètres équivalents.

    `sens_prefere` vaut « horaire » ou « antihoraire ». Un tracé dont le sens
    est indéterminé (aller-retour, tracé non bouclé) est pénalisé comme un
    mauvais sens : on ne sait pas, donc on ne promet rien.
    """
    km_trafic, km_calme, km_non_revetu = _kilometrages(trace)
    gauche, gauche_trafic, droite = _virages(trace)
    sens = sens_boucle(trace)

    score = (
        km_trafic * POIDS_KM_TRAFIC
        + km_non_revetu * POIDS_KM_NON_REVETU
        + gauche * POIDS_VIRAGE_GAUCHE
        + gauche_trafic * POIDS_VIRAGE_GAUCHE_TRAFIC
        + (0.0 if sens == sens_prefere else PENALITE_MAUVAIS_SENS)
    )
    return Couts(
        km_trafic=km_trafic,
        km_calme=km_calme,
        km_non_revetu=km_non_revetu,
        virages_gauche=gauche,
        virages_gauche_trafic=gauche_trafic,
        virages_droite=droite,
        sens=sens,
        score=score,
    )


# --- kilomètres par classe de route ------------------------------------------


def _kilometrages(trace: Trace) -> tuple[float, float, float]:
    """(trafic, calme, non revêtu) en km. Tout à 0 si le tracé n'a pas de segments."""
    if not trace.segments:
        # Un GPX importé ne dit rien des routes empruntées : on le marque
        # plutôt que de laisser croire à 0 km de trafic.
        trace.meta["couts_partiels"] = True
        return (0.0, 0.0, 0.0)

    trafic = calme = non_revetu = 0.0
    for segment in trace.segments:
        km = segment.longueur_m / 1000.0
        highway = segment.tags.get("highway", "")
        if highway in HIGHWAY_TRAFIC:
            trafic += km
        elif highway in HIGHWAY_CALME:
            calme += km
        # Un segment sans `highway` (ou d'une classe inconnue) n'est compté ni
        # d'un côté ni de l'autre : il n'est pas « calme » par défaut.
        if _non_revetu(segment.tags):
            non_revetu += km
    return (trafic, calme, non_revetu)


def _non_revetu(tags: dict[str, str]) -> bool:
    """Vrai si la `surface` est non revêtue, ou si c'est un `track` sans surface."""
    surface = tags.get("surface")
    if surface is not None:
        return surface in SURFACES_NON_REVETUES
    return tags.get("highway", "") in HIGHWAY_NON_REVETU_SANS_SURFACE


# --- virages -----------------------------------------------------------------


def _virages(trace: Trace) -> tuple[int, int, int]:
    """(gauche, gauche à trafic, droite).

    Les caps sont calculés entre des points espacés d'au moins
    `ESPACEMENT_CAP_M` : sans ce sous-échantillonnage, deux points GPS
    consécutifs à 2 m l'un de l'autre donnent un cap dominé par le bruit et
    une boucle bien lisse se retrouve pleine de « virages ».
    """
    indices = _indices_espaces(trace.points, ESPACEMENT_CAP_M)
    if len(indices) < 3:
        return (0, 0, 0)

    noeuds = [trace.points[i] for i in indices]
    caps = [cap_deg(a, b) for a, b in zip(noeuds[:-1], noeuds[1:], strict=True)]
    a_trafic = _points_a_trafic(trace)

    gauche = gauche_trafic = droite = 0
    i = 0
    while i + 1 < len(caps):
        j, cumul = _accumuler(caps, noeuds, i)
        if cumul is None:
            i += 1
            continue
        if cumul <= -ANGLE_VIRAGE_DEG:
            gauche += 1
            entrant = _troncon_a_trafic(a_trafic, indices[i], indices[i + 1])
            sortant = _troncon_a_trafic(a_trafic, indices[j + 1], indices[j + 2])
            if entrant or sortant:
                gauche_trafic += 1
        else:
            droite += 1
        # Le virage consomme les caps i..j+1 : on repart du tronçon sortant,
        # sinon un virage à 90° serait recompté à chaque décalage.
        i = j + 1
    return (gauche, gauche_trafic, droite)


def _accumuler(
    caps: Sequence[float], noeuds: Sequence[PointTrace], i: int
) -> tuple[int, float | None]:
    """Cumule les changements de cap depuis `caps[i]` tant qu'on reste sous 60 m.

    Renvoie `(j, cumul)` où `caps[j + 1]` est le tronçon sortant du virage,
    ou `(i, None)` si les 45° ne sont pas atteints dans la fenêtre. Le premier
    changement est toujours examiné : un virage sec à 90° entre deux tronçons
    ne doit pas dépendre de leur longueur.
    """
    cumul = 0.0
    longueur = 0.0
    j = i
    while j + 1 < len(caps):
        cumul += _ecart_cap(caps[j], caps[j + 1])
        if abs(cumul) >= ANGLE_VIRAGE_DEG:
            return (j, cumul)
        longueur += distance_m(noeuds[j + 1], noeuds[j + 2])
        if longueur > LONGUEUR_VIRAGE_M:
            return (i, None)
        j += 1
    return (i, None)


def _ecart_cap(depuis: float, vers: float) -> float:
    """Changement de cap signé, ramené dans (−180, 180] : négatif = à gauche.

    Le modulo est ce qui fait que passer du cap 350° au cap 10° est un petit
    virage **à droite** (+20°) et non un demi-tour à gauche (−340°). Le cas
    se présente à chaque passage par le nord, donc sur toute boucle.
    Un demi-tour exact (180°) est compté à droite, faute de mieux : le signe
    n'y a pas de sens géométrique.
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


def _points_a_trafic(trace: Trace) -> list[bool]:
    """Pour chaque point du tracé : le segment qui le porte est-il à trafic ?"""
    tags = _tags_par_point(trace)
    return [t is not None and t.get("highway", "") in HIGHWAY_TRAFIC for t in tags]


def _tags_par_point(trace: Trace) -> list[dict[str, str] | None]:
    """Les tags du segment couvrant chaque point, `None` si aucun ne le couvre."""
    tags: list[dict[str, str] | None] = [None] * len(trace.points)
    for segment in trace.segments:
        debut = max(0, segment.debut_idx)
        fin = min(len(trace.points) - 1, segment.fin_idx)
        for i in range(debut, fin + 1):
            if tags[i] is None:  # en cas de recouvrement, le premier segment gagne
                tags[i] = segment.tags
    return tags


def _troncon_a_trafic(a_trafic: Sequence[bool], debut: int, fin: int) -> bool:
    """Vrai si au moins un point du tronçon `[debut, fin[` est sur une route à trafic."""
    return any(a_trafic[debut:fin])

"""Comment s'habiller pour la sortie, d'après la météo le long du tracé.

Règle (décision Q3, `docs/journal/questions/questions_mainteneur.md`) : **la
base se décide sur le départ**, parce que c'est là qu'on a froid. Le reste du
parcours ne change pas ce qu'on met, il
dit ce qu'on emporte et ce qu'on prévoit d'enlever — le ressenti qui monte
d'une catégorie fait ranger les manchettes, la pluie annoncée fait emporter
la veste, le ressenti qui redescend en fin de sortie fait garder de quoi se
recouvrir.

Le vent compte deux fois : il est déjà dans le ressenti (`apparent_temperature`
d'Open-Meteo) et il déclenche **seul** la veste au-delà de `vent_veste_kmh`,
parce qu'un vent fort sans pluie ni froid reste désagréable de face.

Convention des seuils, la même partout : **une valeur exactement sur une
borne appartient à la catégorie supérieure**. 3,0 °C ressentis, c'est
« froid » et non « très froid » ; 0,2 mm/h, c'est « humide » et non « sec ».

Les tenues par catégorie sont un tableau, `TENUES_DEFAUT`, remplaçable
catégorie par catégorie depuis la configuration : les habitudes
vestimentaires ne sont pas les mêmes d'un cycliste à l'autre, et ce n'est
pas au code d'en décider.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from ourouler.boucle.meteo_trace import Echantillon, MeteoTrace
from ourouler.noyau.profil import ParametresTenue

#: Catégories de température ressentie, de la plus froide à la plus chaude.
#: Il y en a une de plus que de bornes : `ParametresTenue.bornes_c`.
CATEGORIES_TEMP = ("très froid", "froid", "frais", "modéré", "chaud", "canicule")

#: Catégories d'humidité, de la plus sèche à la plus humide.
CATEGORIES_PLUIE = ("sec", "humide", "averses", "pluie")

#: Ce qu'on répond quand la donnée manque. Jamais une catégorie par défaut :
#: une ignorance se dit, elle ne se déguise pas en mesure.
INCONNU = "inconnu"

#: Le jeu de tenues par défaut, celui d'un cycliste dont on ne sait rien.
#: L'ordre de chaque liste va du tronc vers les extrémités. Les vêtements
#: qu'on peut enlever et ranger en roulant (manchettes, jambières, gilet)
#: sont volontairement distincts de ceux qu'on ne peut pas : c'est ce qui
#: permet de dire « prévoir d'enlever X » sans dire de bêtise.
TENUES_DEFAUT: dict[str, tuple[str, ...]] = {
    "très froid": (
        "maillot thermique manches longues",
        "collant long",
        "veste coupe-vent",
        "gants d'hiver",
        "sous-casque",
        "couvre-chaussures",
    ),
    "froid": (
        "maillot manches longues",
        "collant long",
        "gilet coupe-vent",
        "gants longs",
        "couvre-chaussures",
    ),
    "frais": (
        "maillot manches courtes",
        "manchettes",
        "jambières",
        "gilet coupe-vent",
        "gants longs",
    ),
    "modéré": (
        "maillot manches courtes",
        "cuissard",
        "manchettes",
    ),
    "chaud": (
        "maillot manches courtes",
        "cuissard",
    ),
    "canicule": (
        "maillot léger",
        "cuissard",
        "casquette sous le casque",
        "bidon supplémentaire",
    ),
}

#: Ce qu'on emporte quand la pluie ou le vent l'imposent.
#:
#: Deux vestes, pas une : l'imperméable arrête l'eau, la coupe-vent arrête le
#: vent. Et une **veste** coupe-vent, pas le gilet coupe-vent de la tenue de
#: base : à 30 km/h de vent ce sont les bras qui prennent : le vent déclenche seul la
#: veste au-delà de `vent_veste_kmh`. Un cycliste qui porte déjà une veste
#: coupe-vent — la tenue « très froid » — n'en emporte pas une seconde,
#: `_ajouter` s'en charge.
VESTE_PLUIE = "veste imperméable"
VESTE_VENT = "veste coupe-vent"


@dataclass
class Tenue:
    """Ce qu'on met, ce qu'on emporte, ce qu'on prévoit d'enlever — et pourquoi."""

    categorie_temp: str
    categorie_humidite: str
    base: list[str]
    a_emporter: list[str]
    a_enlever: list[str]
    motifs: list[str] = field(default_factory=list)


def conseiller(meteo: MeteoTrace, p: ParametresTenue) -> Tenue:
    """La tenue conseillée pour la météo `meteo`, selon les seuils `p`.

    La base sort du **premier** échantillon du tracé ; le reste du parcours
    alimente « à emporter », « à enlever » et les motifs.
    """
    echantillons = meteo.echantillons
    if not echantillons:
        return Tenue(
            categorie_temp=INCONNU,
            categorie_humidite=INCONNU,
            base=[],
            a_emporter=[],
            a_enlever=[],
            motifs=["aucun échantillon le long du tracé : rien à conseiller"],
        )

    tenues = _tenues(p)
    motifs: list[str] = []
    base: list[str] = []
    a_emporter: list[str] = []
    a_enlever: list[str] = []

    depart = echantillons[0]
    rang_base = _rang(depart.ressenti_c, p.bornes_c)
    categorie_temp = _nom(rang_base, p.bornes_c, CATEGORIES_TEMP)
    if rang_base is None:
        motifs.append("ressenti inconnu au départ : aucune tenue de base conseillée")
    else:
        base = list(tenues.get(categorie_temp, ()))
        motifs.append(
            f"au départ : {depart.ressenti_c:.0f} °C ressentis, catégorie « {categorie_temp} »"
        )
        if not base:
            motifs.append(f"aucune tenue n'est définie pour la catégorie « {categorie_temp} »")

    categorie_humidite = _humidite(echantillons, p, base, a_emporter, motifs)
    _vent(echantillons, p, base, a_emporter, motifs)
    if rang_base is not None:
        _variation(
            echantillons,
            p,
            rang_base,
            tenues,
            base,
            a_emporter=a_emporter,
            a_enlever=a_enlever,
            motifs=motifs,
        )

    return Tenue(
        categorie_temp=categorie_temp,
        categorie_humidite=categorie_humidite,
        base=base,
        a_emporter=list(dict.fromkeys(a_emporter)),
        a_enlever=list(dict.fromkeys(a_enlever)),
        motifs=motifs,
    )


# --- les trois lectures du parcours ------------------------------------------


def _humidite(
    echantillons: Sequence[Echantillon],
    p: ParametresTenue,
    base: Sequence[str],
    a_emporter: list[str],
    motifs: list[str],
) -> str:
    """La catégorie d'humidité (le pire échantillon du parcours) et la veste qui va avec.

    La catégorie porte sur **tout** le parcours, et non sur le départ : une
    averse au kilomètre 40 mouille autant qu'une averse au départ, et c'est
    elle qui fait emporter la veste.
    """
    pires = [(e.pluie_mm, e.dist_m) for e in echantillons if e.pluie_mm is not None]
    if not pires:
        motifs.append("pluie inconnue le long du tracé")
        return INCONNU
    pluie_max, dist = max(pires)
    rang = _rang(pluie_max, p.bornes_pluie_mmh)
    categorie = _nom(rang, p.bornes_pluie_mmh, CATEGORIES_PLUIE)
    if rang is not None and rang >= 1:
        _ajouter(a_emporter, VESTE_PLUIE, base)
        motifs.append(
            f"pluie jusqu'à {pluie_max:.1f} mm/h au km {dist / 1000:.0f} "
            f"(« {categorie} ») : emporter la veste"
        )
    return categorie


def _vent(
    echantillons: Sequence[Echantillon],
    p: ParametresTenue,
    base: Sequence[str],
    a_emporter: list[str],
    motifs: list[str],
) -> None:
    """Le vent déclenche seul la veste au-delà du seuil, pluie ou pas."""
    vents = [(e.vent_kmh, e.dist_m) for e in echantillons if e.vent_kmh is not None]
    if not vents:
        return
    vent_max, dist = max(vents)
    if vent_max >= p.vent_veste_kmh:
        _ajouter(a_emporter, VESTE_VENT, base)
        motifs.append(
            f"vent jusqu'à {vent_max:.0f} km/h au km {dist / 1000:.0f} "
            f"(seuil {p.vent_veste_kmh:.0f}) : {_conseil(a_emporter, VESTE_VENT)}"
        )


def _variation(
    echantillons: Sequence[Echantillon],
    p: ParametresTenue,
    rang_base: int,
    tenues: dict[str, tuple[str, ...]],
    base: Sequence[str],
    *,
    a_emporter: list[str],
    a_enlever: list[str],
    motifs: list[str],
) -> None:
    """Ce que la suite du parcours change : couches à ranger, couches à garder."""
    suite = [(_rang(e.ressenti_c, p.bornes_c), e) for e in echantillons[1:]]
    connus = [(r, e) for r, e in suite if r is not None]
    if not connus:
        return

    rang_haut, chaud = max(connus, key=lambda c: c[0])
    if rang_haut > rang_base:
        categorie = _nom(rang_haut, p.bornes_c, CATEGORIES_TEMP)
        amovibles = [v for v in base if v not in tenues.get(categorie, ())]
        a_enlever.extend(amovibles)
        motifs.append(
            f"le ressenti monte à {chaud.ressenti_c:.0f} °C au km {chaud.dist_m / 1000:.0f} "
            f"(« {categorie} ») : prévoir d'enlever {_liste(amovibles)}"
        )

    rang_bas, froid = min(connus, key=lambda c: c[0])
    if rang_bas < rang_base:
        categorie = _nom(rang_bas, p.bornes_c, CATEGORIES_TEMP)
        manquants = [v for v in tenues.get(categorie, ()) if v not in base]
        for vetement in manquants:
            _ajouter(a_emporter, vetement, base)
        motifs.append(
            f"le ressenti redescend à {froid.ressenti_c:.0f} °C au km "
            f"{froid.dist_m / 1000:.0f} (« {categorie} ») : emporter {_liste(manquants)}"
        )
    elif a_enlever and connus[-1][0] <= rang_base:
        motifs.append(
            f"le ressenti redescend en fin de parcours : garder {_liste(list(a_enlever))}"
        )


# --- outils ------------------------------------------------------------------


def _tenues(p: ParametresTenue) -> dict[str, tuple[str, ...]]:
    """Le tableau des tenues : le jeu par défaut, catégorie par catégorie, écrasé par la configuration.

    La source est `ParametresTenue.tenue_de`, l'accesseur prévu pour ça :
    `ParametresTenue.tenues` est un **tuple de couples** `(catégorie,
    vêtements)` — une dataclass gelée ne peut pas porter un dict —
    et c'est cette forme-là, et elle seule, que produit la chaîne
    TOML → `depuis_dict` → `Config`. Une configuration qui ne décrit qu'une
    catégorie garde le défaut pour les autres, comme le promettent les onze
    lignes de `config.example.toml`.

    Ce module a lu pendant un temps `p.tenues` en attendant un `dict` : le
    champ existait, la validation TOML aussi, et la tenue rendue restait celle
    du code. On passe donc par `tenue_de`, qui est le contrat public, plutôt
    que par la représentation interne du champ.
    """
    tableau = dict(TENUES_DEFAUT)
    for categorie, _ in getattr(p, "tenues", ()):
        pieces = p.tenue_de(categorie)
        if pieces is not None:
            tableau[str(categorie)] = tuple(str(v) for v in pieces)
    return tableau


def _rang(valeur: float | None, bornes: Sequence[float]) -> int | None:
    """L'indice de catégorie d'une valeur, `None` si la valeur manque.

    `bisect_right` met la valeur exactement égale à une borne dans la
    catégorie supérieure : c'est la convention annoncée en tête de module.
    """
    if valeur is None or not math.isfinite(valeur):
        return None
    return bisect.bisect_right(list(bornes), valeur)


def _nom(rang: int | None, bornes: Sequence[float], noms: Sequence[str]) -> str:
    """Le nom de la catégorie de rang `rang`.

    Une configuration libre de donner autant de bornes qu'elle veut peut en
    donner un nombre pour lequel on n'a pas de nom : on numérote plutôt que
    d'appeler « canicule » ce qui n'en est pas une.
    """
    if rang is None:
        return INCONNU
    if len(noms) != len(bornes) + 1:
        return f"palier {rang + 1} sur {len(bornes) + 1}"
    return noms[rang]


def _ajouter(liste: list[str], vetement: str, base: Sequence[str]) -> None:
    """Ajoute un vêtement à emporter, sauf s'il est déjà sur le dos ou déjà prévu."""
    if vetement in liste:
        return
    if any(vetement in porte for porte in base):
        return
    liste.append(vetement)


def _conseil(a_emporter: Sequence[str], vetement: str) -> str:
    """« emporter la veste coupe-vent », ou le fait qu'elle soit déjà sur le dos.

    Un motif qui dit « emporter X » alors que « à emporter » est vide se lit
    comme un oubli. Quand `_ajouter` a jugé que le vêtement était déjà porté,
    le motif le dit plutôt que de le taire.
    """
    if vetement in a_emporter:
        return f"emporter la {vetement}"
    return f"la {vetement} est déjà dans la tenue de base"


def _liste(vetements: Sequence[str]) -> str:
    """« les manchettes et le gilet », pour un motif lisible."""
    if not vetements:
        return "rien"
    if len(vetements) == 1:
        return vetements[0]
    return ", ".join(vetements[:-1]) + " et " + vetements[-1]

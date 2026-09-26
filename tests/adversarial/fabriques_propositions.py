"""Fabriques du lot L5.3 — trois propositions contrastées (contrat sprint 5 §3.3).

Écrit **en aveugle** de l'implémentation, puis **réconcilié le 16/09/2026**
après sa fusion. Les vérificateurs n'ont pas changé de fond ; ce sont les
adaptateurs qui ont appris à lire ce que le lot publie réellement.

## Pourquoi ce fichier est aussi gros

Le contrat §3.3 ne nommait **aucune interface** : ni module, ni fonction, ni
champ. Il décrivait un comportement (« trois représentants éloignés », « une
phrase par proposition », « deux gardes sur la question du vent », « une
densité de marqueurs au kilomètre ») sans dire par quelle porte on y entre.
Deux conséquences, et elles structurent tout le dossier.

1. **Les vérificateurs sont écrits contre une vue générique**
   (`VueProposition`, `VueChoix`), pas contre l'implémentation. Les
   adaptateurs (`vue_depuis_json`, `decouvrir_callable`) vont chercher la
   vraie porte au moment du test et disent ce qu'ils ont cherché quand ils
   échouent. Rien n'est deviné en silence.
2. **Une implémentation de référence** (`choisir_reference`,
   `densite_reference`, `question_vent_reference`) sert de cobaye : elle est
   mutée vingt-sept fois dans `test_adv_propositions_autocontrole.py`, et chaque
   mutation doit être attrapée par un vérificateur nommé. C'est la discipline
   du lot L5.2, où deux tests s'étaient révélés aveugles à la mutation qu'ils
   annonçaient. Elle ne remplace pas les tests sur le vrai code : elle prouve
   que les vérificateurs ne sont pas creux.

## Un adaptateur muet doit se dénoncer

La leçon de la réconciliation, et elle vaut au-delà de ce lot. Mon
`vue_depuis_json` était écrit pour la forme imbriquée de `candidates[]` ; le
lot publie ses propositions à plat. L'adaptateur ne lisait donc **aucun** axe,
rendait des vues toutes neutres — donc identiques — et le vérificateur de
clones criait « trois propositions identiques » sur des propositions qui
différaient très bien. `exiger_axes_lus` refuse désormais de conclure quand
rien n'a été lu : mieux vaut échouer en disant « je ne sais pas lire » que
rendre un verdict faux avec assurance.

## Ce que la référence n'est pas

Ce n'est **pas** une proposition d'implémentation, et surtout pas une norme :
le contrat ne fixe ni la distance entre deux propositions, ni le seuil à
partir duquel elles sont « éloignées ». La référence choisit la distance de
Tchebychev et un seuil explicite parce qu'il faut bien un cobaye qui tourne ;
**aucun test sur le vrai code n'exige ces choix-là**.

## Aucune coordonnée réelle

Toute géométrie part de `fabriques.LAT0/LON0` (en pleine mer au large du golfe
de Guinée), comme le reste du dossier. Règle absolue 1 de CLAUDE.md.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import fabriques
import fabriques_seance

from ourouler.noyau.trace import Trace

# --- les axes perceptibles ----------------------------------------------------

#: Les axes que le contrat §3.3.1 déclare perceptibles — « la durée réelle, la
#: présence de demi-tours, la traversée de ville, l'orientation au vent, la
#: pluie, la part de routes qu'il connaît déjà. Pas la note. »
#:
#: `sens` dit ce qui est *meilleur* et sert aux phrases, pas au contraste :
#: deux propositions sont contrastées par leur **écart**, dans un sens comme
#: dans l'autre. `part_connue` n'a volontairement pas de sens : « vous
#: connaissez déjà ces routes » et « des routes nouvelles » sont deux
#: affirmations également recevables.
AXES: dict[str, str] = {
    "pluie_mm": "min",
    "demi_tours": "min",
    "depassement_s": "min",
    "densite_marqueurs_km": "min",
    "vent_dos_retour": "max",
    "vent_dos_depart": "max",
    "vent_travers": "max",
    "note_terrain": "min",
    # Pas dans le tableau du contrat §3.3.2, mais le lot l'implémente
    # (`contraste.AXE_TRAFIC`) et §3.1.3 a) documente le manque qu'il comble.
    # Perceptible sans discussion : rouler sur une départementale se sent.
    "part_trafic": "min",
}

#: **`part_connue` n'est pas ici, et c'est le point le plus important du
#: fichier.** Le tableau §3.3.2 l'a listée, puis rayée le 16/09/2026 :
#: « Retiré : contredit le contrat du sprint 3 ». La règle vient de la
#: docstring de `BaseRoutes.part_connue` — « **Informatif seulement.** Le
#: contrat l'interdit dans tout score : les traces ne couvrent qu'une partie du
#: territoire, et pénaliser l'inconnu condamnerait d'avance toute direction
#: jamais explorée » — et la doctrine en donne la raison de fond : les routes
#: déjà roulées sont un **instrument de mesure**, jamais un critère. Le jour où
#: elles entrent dans le score, l'outil renvoie au cycliste ses propres
#: habitudes en prétendant les avoir trouvées, et toute validation
#: rétrospective devient circulaire.
#:
#: J'avais écrit l'inverse — un test exigeant qu'elle devienne un axe — sur la
#: foi d'une version du contrat antérieure au retrait, alors que ma propre
#: non-régression citait la docstring qui l'interdit. Deux positions
#: contradictoires dans la même branche. Le test est retiré et remplacé par son
#: miroir, `test_la_part_de_routes_connues_ne_doit_jamais_entrer_dans_la_selection`.
AXE_INTERDIT = "part_connue"

#: La note de placement, que le contrat §3.3.1 exclut explicitement du
#: contraste (« Pas la note »). Elle reste ici pour le **tri primaire**, qui
#: continue d'exister : le contraste choisit parmi des candidates classées.
AXE_NOTE = "note_totale"


@dataclass(frozen=True)
class VueProposition:
    """Une candidate réduite à ce que le cycliste voit ou sent.

    `cle` identifie la candidate (un entier suffit) ; `axes` porte une valeur
    finie par axe de `AXES` ; `phrase` est ce que le lot doit écrire, et vaut
    `None` tant qu'on ne l'a pas demandé.
    """

    cle: Any
    axes: dict[str, float]
    note_totale: float = 0.0
    phrase: str | None = None
    #: L'orientation au vent **nommée** par le lot ("retour-dos", "depart-dos",
    #: "travers", "face"), ou `None`. Une phrase de vent est une affirmation
    #: descriptive sur cette valeur, pas un superlatif sur un axe numérique.
    orientation: str | None = None
    #: Les axes réellement lus dans le JSON. Vide = l'adaptateur n'a rien
    #: compris, et aucun verdict ne doit être rendu (`exiger_axes_lus`).
    axes_lus: frozenset = frozenset()
    #: Le plus fort recouvrement de routes avec une autre proposition, publié
    #: par le lot sous `recouvrement_max_avec`. Le contrat §3.3.2 en fait un
    #: axe de plein droit, et le seul qui mesure la différence **entre** les
    #: boucles plutôt que leurs attributs.
    recouvrement_max: float | None = None
    #: Lue pour être surveillée, jamais pour contraster — voir `AXE_INTERDIT`.
    part_connue: float | None = None

    def axe(self, nom: str) -> float:
        valeur = self.axes.get(nom)
        assert valeur is not None, f"candidate {self.cle!r} : axe « {nom} » absent"
        return float(valeur)


@dataclass
class VueChoix:
    """Ce que le lot rend : les retenues, et ce qu'il dit du contraste."""

    retenues: list[VueProposition]
    #: Vrai si le lot **affirme** que les retenues sont contrastées. Le contrat
    #: autorise à en rendre deux « et le dire » : une implémentation qui rend
    #: trois clones en les annonçant contrastées **sans rien dire** est le
    #: défaut central du lot.
    contraste_affirme: bool = True
    #: Vrai si le lot dit que les retenues **se valent** — la phrase de Q45.
    #: Depuis Q43, publier trois clones sur les axes est permis quand les
    #: tracés, eux, vont ailleurs ; ce qui ne l'est pas, c'est de laisser
    #: croire qu'une différence mesurée les sépare.
    equivalence_dite: bool = False
    #: Ce que le lot dit quand il n'a pas pu en contraster trois.
    motif: str = ""
    pool: list[VueProposition] = field(default_factory=list)


# --- fabrication d'un vivier --------------------------------------------------

#: Valeurs neutres : une candidate « moyenne » sur tous les axes.
NEUTRE: dict[str, float] = {
    "pluie_mm": 2.0,
    "demi_tours": 1,
    "depassement_s": 900.0,
    "densite_marqueurs_km": 4.0,
    "vent_dos_retour": 0.5,
    "vent_dos_depart": 0.5,
    "vent_travers": 0.5,
    "part_trafic": 0.3,
    "note_terrain": 1.0,
}


def vue(cle: Any, *, note: float = 1.0, phrase: str | None = None, **axes: float) -> VueProposition:
    """Une `VueProposition` neutre, sauf sur les axes qu'on lui impose."""
    inconnus = set(axes) - set(AXES)
    assert not inconnus, f"axes inconnus : {sorted(inconnus)}"
    valeurs = dict(NEUTRE)
    valeurs.update({k: float(v) for k, v in axes.items()})
    return VueProposition(cle=cle, axes=valeurs, note_totale=float(note), phrase=phrase)


def vivier_clones(n: int = 5, *, notes_distinctes: bool = True) -> list[VueProposition]:
    """`n` candidates **identiques sur tous les axes perceptibles**.

    Le cas que le lot existe pour refuser : sur le papier les notes diffèrent
    (1,93 / 2,30 / 4,72 du contrat §3.3.1), sur une carte c'est la même sortie.
    Avec `notes_distinctes=False`, même les notes sont égales — le classement
    dégénéré, où une normalisation naïve divise par une étendue nulle.
    """
    return [
        vue(i, note=(1.93 + 0.37 * i) if notes_distinctes else 1.93) for i in range(n)
    ]


def vivier_deux_familles(par_famille: int = 3) -> list[VueProposition]:
    """Deux grappes de clones et rien entre les deux : au plus **deux** représentants.

    Trois retenues obligeraient à reprendre deux membres de la même grappe,
    c'est-à-dire deux propositions indiscernables sur la carte. Le contrat :
    « il vaut mieux n'en proposer que deux et le dire ».
    """
    vivier: list[VueProposition] = []
    for k in range(par_famille):
        vivier.append(vue(("a", k), note=1.0 + 0.01 * k, pluie_mm=0.0, densite_marqueurs_km=1.0))
        vivier.append(vue(("b", k), note=1.5 + 0.01 * k, pluie_mm=9.0, densite_marqueurs_km=9.0))
    return vivier


def vivier_contrastable() -> list[VueProposition]:
    """Le piège du tri unique : les trois **mieux notées** sont des clones.

    Cinq candidates. Les trois premières du classement (notes 1,00 / 1,01 /
    1,02) sont identiques sur tous les axes perceptibles ; les deux dernières
    (notes 3,00 et 3,10) sont aux antipodes l'une de l'autre et de la grappe.
    Un lot qui prend « les trois premières d'un tri » rend trois cartes
    jumelles ; un lot qui choisit des représentants éloignés va chercher les
    deux extrêmes.
    """
    grappe = [
        vue(("tete", k), note=1.0 + 0.01 * k, pluie_mm=3.0, demi_tours=2,
            depassement_s=1800.0, densite_marqueurs_km=8.0,
            vent_dos_retour=0.2)
        for k in range(3)
    ]
    seche = vue(
        "seche", note=3.0, pluie_mm=0.0, demi_tours=0, depassement_s=120.0,
        densite_marqueurs_km=0.5, vent_dos_retour=0.9,
    )
    ventee = vue(
        "ventee", note=3.1, pluie_mm=9.0, demi_tours=0, depassement_s=2400.0,
        densite_marqueurs_km=0.6, vent_dos_retour=0.95,
    )
    return [*grappe, seche, ventee]


def vivier_un_axe(axe: str, valeurs: Sequence[float]) -> list[VueProposition]:
    """`len(valeurs)` candidates qui ne diffèrent **que** sur `axe`.

    Sert aux phrases : quand une seule chose distingue une candidate, la phrase
    qui la décrit ne peut parler que de celle-là. Une phrase qui parle d'autre
    chose est fausse, et une affirmation fausse est le défaut que le contrat
    nomme (« une phrase est une affirmation : elle doit être vraie »).
    """
    assert axe in AXES, f"axe inconnu : {axe}"
    return [vue(i, note=1.0, **{axe: float(v)}) for i, v in enumerate(valeurs)]


def vivier_sans_bloc(n: int = 5) -> list[VueProposition]:
    """Le cas courant du mainteneur (contrat §3.1.3 b) : aucune séance à bloc.

    `note_terrain` vaut zéro pour toutes ; les notes ne diffèrent que par la
    pénalité de dépassement du retour au calme (0,00 / 0,05 / 0,08 / 0,15 /
    0,29, les vraies valeurs mesurées le 12/09). Le terrain ne départage rien,
    mais le trafic, la ville et les routes connues, eux, diffèrent franchement.
    """
    notes = (0.00, 0.05, 0.08, 0.15, 0.29)[:n]
    densites = (9.0, 7.0, 5.0, 2.5, 0.8)[:n]
    connues = (0.30, 0.45, 0.55, 0.70, 0.98)[:n]
    del connues  # la part de routes connues n'est pas un axe (voir `AXE_INTERDIT`)
    return [
        vue(i, note=notes[i], densite_marqueurs_km=densites[i],
            depassement_s=notes[i] * 3600.0)
        for i in range(min(n, 5))
    ]


# --- distance et contraste (le cobaye, pas la norme) --------------------------

#: Seuil de contraste **de la référence**. Aucun test du vrai code ne l'exige :
#: le contrat ne chiffre pas « éloignées ». Voir le docstring du module.
SEUIL_CONTRASTE = 0.25


def etendues(pool: Sequence[VueProposition]) -> dict[str, float]:
    """L'étendue de chaque axe sur le vivier. Zéro quand l'axe est dégénéré."""
    sortie: dict[str, float] = {}
    for nom in AXES:
        valeurs = [p.axe(nom) for p in pool]
        sortie[nom] = (max(valeurs) - min(valeurs)) if valeurs else 0.0
    return sortie


def distance(a: VueProposition, b: VueProposition, portees: dict[str, float]) -> float:
    """Tchebychev sur les axes normalisés : l'écart du plus discriminant.

    **Un axe d'étendue nulle contribue zéro**, il ne divise pas par zéro. C'est
    exactement le piège de la séance sans bloc, où tous les scores de terrain
    sont égaux : une normalisation min-max écrite sans garde y lève une
    `ZeroDivisionError` au moment précis où le mainteneur s'en sert le plus.
    """
    ecarts = []
    for nom, portee in portees.items():
        if portee <= 0 or not math.isfinite(portee):
            continue
        ecarts.append(abs(a.axe(nom) - b.axe(nom)) / portee)
    return max(ecarts) if ecarts else 0.0


def tri_primaire(pool: Sequence[VueProposition]) -> list[VueProposition]:
    """Le classement existant : note de placement, puis pluie. Voir `_comparer`."""
    return sorted(pool, key=lambda p: (p.note_totale, p.axe("pluie_mm")))


def choisir_reference(
    pool: Sequence[VueProposition], *, nb: int = 3, seuil: float = SEUIL_CONTRASTE
) -> VueChoix:
    """Le cobaye : amorce sur le tri, puis points les plus éloignés.

    1. on part de la mieux classée (le tri existant reste le point d'entrée) ;
    2. on ajoute à chaque tour celle dont la distance **minimale** aux déjà
       retenues est la plus grande — « trois représentants éloignés les uns des
       autres », pas les trois premières d'un tri ;
    3. on s'arrête dès que la meilleure candidate restante n'apporte plus
       `seuil` d'écart : mieux vaut deux propositions et le dire.
    """
    if not pool:
        return VueChoix(retenues=[], contraste_affirme=False, motif="aucune candidate", pool=[])
    portees = etendues(pool)
    classees = tri_primaire(pool)
    retenues = [classees[0]]
    restantes = [p for p in classees[1:]]
    tronque = False
    while len(retenues) < nb and restantes:
        meilleure, ecart = None, -1.0
        for candidate in restantes:
            d = min(distance(candidate, r, portees) for r in retenues)
            if d > ecart:
                meilleure, ecart = candidate, d
        if meilleure is None or ecart < seuil:
            tronque = True
            break
        retenues.append(meilleure)
        restantes = [p for p in restantes if p.cle != meilleure.cle]

    # Le contrat §3.3.3 fait de la phrase le juge de dernier ressort : « si
    # aucune phrase n'est écrivable, c'est que les trois ne sont pas
    # contrastées — et il vaut mieux n'en proposer que deux et le dire ». On
    # retire donc la dernière retenue tant qu'une phrase reste vide, plutôt
    # que de livrer une proposition qui ne sait pas dire ce qui la distingue.
    # (Trouvé en écrivant l'autocontrôle, sur le vivier « séance sans bloc » :
    # la troisième retenue n'était la meilleure sur aucun axe.)
    ecrites = ecrire_phrases_reference(retenues, portees)
    while len(ecrites) > 1 and any(not (p.phrase or "").strip() for p in ecrites):
        retenues = retenues[:-1]
        tronque = True
        ecrites = ecrire_phrases_reference(retenues, portees)

    return VueChoix(
        retenues=ecrites,
        contraste_affirme=not tronque and len(ecrites) > 1,
        motif=(
            "aucune autre candidate ne se distingue assez de celles-ci"
            if tronque
            else ""
        ),
        pool=list(pool),
    )


#: Comment nommer chaque axe en langage de cycliste. Les tournures viennent du
#: contrat §3.3.3, qui les donne en exemple. Jamais de note, jamais de chiffre
#: à deux décimales.
TOURNURES: dict[tuple[str, str], str] = {
    ("pluie_mm", "min"): "la plus sèche",
    ("pluie_mm", "max"): "la plus arrosée",
    ("demi_tours", "min"): "aucun demi-tour",
    ("demi_tours", "max"): "avec des demi-tours",
    ("depassement_s", "min"): "la plus courte",
    ("depassement_s", "max"): "la plus longue",
    ("densite_marqueurs_km", "min"): "elle évite les villages",
    ("densite_marqueurs_km", "max"): "elle traverse les bourgs",
    ("vent_dos_retour", "max"): "vous rentrez avec le vent dans le dos",
    ("vent_dos_retour", "min"): "vous rentrez face au vent",
    ("vent_dos_depart", "max"): "vent dans le dos au départ",
    ("vent_dos_depart", "min"): "vent de face au départ",
    ("vent_travers", "max"): "vent de travers",
    ("vent_travers", "min"): "jamais de vent de travers",
}


def ecrire_phrases_reference(
    retenues: Sequence[VueProposition], portees: dict[str, float]
) -> list[VueProposition]:
    """Une phrase par retenue : l'axe où elle est **strictement** la meilleure du trio.

    On choisit l'axe où son avance normalisée sur la meilleure des autres est la
    plus grande, et on refuse d'écrire deux fois le même axe. Sans avance
    stricte nulle part, la phrase serait une affirmation invérifiable : on rend
    alors une chaîne vide, que le vérificateur attrapera.
    """
    sortie: list[VueProposition] = []
    pris: set[tuple[str, str]] = set()
    for p in retenues:
        autres = [q for q in retenues if q.cle != p.cle]
        meilleur: tuple[float, tuple[str, str]] | None = None
        for nom, portee in portees.items():
            if portee <= 0 or not math.isfinite(portee) or not autres:
                continue
            for sens in ("min", "max"):
                if (nom, sens) in pris:
                    continue
                # Les deux sens restent dicibles ; `sens` n'est qu'une tournure.
                mien = p.axe(nom)
                leur = (
                    min(q.axe(nom) for q in autres)
                    if sens == "min"
                    else max(q.axe(nom) for q in autres)
                )
                avance = (leur - mien) / portee if sens == "min" else (mien - leur) / portee
                if avance > 0 and (meilleur is None or avance > meilleur[0]):
                    meilleur = (avance, (nom, sens))
        if meilleur is None:
            sortie.append(replace(p, phrase=""))
            continue
        pris.add(meilleur[1])
        sortie.append(replace(p, phrase=TOURNURES[meilleur[1]]))
    return sortie


# --- les phrases : reconnaître une affirmation et la vérifier -----------------


@dataclass(frozen=True)
class Affirmation:
    """Une tournure reconnaissable, et ce sur quoi elle engage le lot.

    Deux natures d'affirmation, et les confondre affaiblit la vérification :

    * **superlative** (`sens` vaut "min", "max" ou "zero") — « la plus sèche »
      affirme être la meilleure des retenues sur la pluie ;
    * **descriptive** (`orientation` renseignée) — « vous rentrez avec le vent
      dans le dos » n'affirme rien sur les autres, elle décrit *cette*
      proposition, et se vérifie contre l'orientation que le lot publie.

    La seconde est plus forte quand elle est disponible : elle attrape une
    phrase collée à la mauvaise proposition même quand les trois ont la même
    valeur numérique.
    """

    nom: str
    motifs: tuple[str, ...]
    axe: str
    sens: str  # "min", "max" ou "zero"
    orientation: str | None = None


#: Le lexique est délibérément celui du contrat §3.3.3, qui donne les phrases en
#: exemple : « vous rentrez avec le vent dans le dos », « aucun demi-tour »,
#: « la plus sèche », « 20 minutes de moins », « elle évite les villages ».
#: L'ordre compte : la tournure la plus spécifique est reconnue d'abord.
AFFIRMATIONS: tuple[Affirmation, ...] = (
    Affirmation("vent_dos_depart", ("vent dans le dos au départ", "vent dans le dos au depart",
                                    "vous partez avec le vent"), "vent_dos_depart", "max",
                orientation="depart-dos"),
    Affirmation("vent_dos_retour", ("rentrez avec le vent dans le dos", "vent dans le dos au retour",
                                    "vent dans le dos à la fin", "vent dans le dos a la fin",
                                    "vent dans le dos pour rentrer"), "vent_dos_retour", "max",
                orientation="retour-dos"),
    Affirmation("vent_travers", ("vent de travers", "vent latéral", "vent lateral"),
                "vent_travers", "max", orientation="travers"),
    # « du vent de face au départ comme au retour » : une phrase qui distingue
    # par la négative, et que le lot écrit réellement. Ne pas la reconnaître
    # ferait passer pour muette une proposition qui dit très bien ce qu'elle est.
    Affirmation("vent_face", ("vent de face au départ comme au retour",
                              "vent de face au depart comme au retour",
                              "du vent de face"), "vent_dos_retour", "min",
                orientation="face"),
    Affirmation("demi_tour", ("aucun demi-tour", "sans demi-tour", "pas de demi-tour"),
                "demi_tours", "zero"),
    # « un seul demi-tour » / « 2 demi-tours seulement » : le lot les écrit, et
    # ce sont des superlatifs, pas des « zéro ».
    Affirmation("demi_tour_moins", ("un seul demi-tour", "demi-tours seulement",
                                    "demi-tour seulement"), "demi_tours", "min"),
    Affirmation("pluie", ("la plus sèche", "la plus seche", "au sec", "sans pluie", "moins de pluie"),
                "pluie_mm", "min"),
    Affirmation("duree", ("minutes de moins", "la plus courte", "plus courte", "moins longue",
                          "la plus proche de la séance", "tient la durée", "tient la duree"),
                "depassement_s", "min"),
    Affirmation("ville", ("évite les villages", "evite les villages", "évite les bourgs",
                          "evite les bourgs", "évite la ville", "evite la ville",
                          "sans traverser", "moins de feux", "la plus calme"),
                "densite_marqueurs_km", "min"),
    Affirmation("trafic", ("évite les grands axes", "evite les grands axes",
                           "évite les départementales", "evite les departementales"),
                "part_trafic", "min"),
    Affirmation("terrain", ("les blocs tombent le mieux", "le mieux pour les blocs"),
                "note_terrain", "min"),
)

#: Ce qui trahit le langage de note plutôt que le langage de cycliste. Le
#: contrat : « en langage de cycliste et **jamais en langage de note** ».
#: `\d+[,.]\d\d` attrape « note 1,93 » sans attraper « 4,2 km » ni « 20 minutes ».
MOTS_DE_NOTE = ("note", "score", "classement", "pénalité", "penalite", "rang ", "points de")
MOTIF_NOTE_CHIFFREE = re.compile(r"\d+[,.]\d{2}(?!\d)")


def _sans_accents_bas(texte: str) -> str:
    import unicodedata

    plat = "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )
    return plat.casefold()


def affirmations_de(phrase: str) -> list[Affirmation]:
    """Les affirmations du lexique que cette phrase engage."""
    plat = _sans_accents_bas(phrase)
    trouvees: list[Affirmation] = []
    for a in AFFIRMATIONS:
        if any(_sans_accents_bas(m) in plat for m in a.motifs):
            trouvees.append(a)
    # « retour au calme » n'est pas « la plus calme » : on retire le faux positif.
    if "retour au calme" in plat:
        trouvees = [a for a in trouvees if a.nom != "ville" or "la plus calme" not in plat]
    return trouvees


def phrase_est_en_langage_de_note(phrase: str) -> bool:
    plat = _sans_accents_bas(phrase)
    if MOTIF_NOTE_CHIFFREE.search(phrase):
        return True
    return any(_sans_accents_bas(mot) in plat for mot in MOTS_DE_NOTE)


# --- vérificateurs ------------------------------------------------------------

#: Marge des comparaisons de flottants qui **doivent différer franchement**.
#: Leçon du lot L5.1, où un test verdissait sur 1,8·10⁻¹² m de bruit : on ne
#: compare jamais sans marge deux grandeurs censées être nettement distinctes.
MARGE = 1e-9


def verifier_retenues_bien_formees(choix: VueChoix, *, nb_max: int = 3) -> None:
    """Le minimum : des retenues distinctes, tirées du vivier, en nombre borné."""
    cles = [p.cle for p in choix.retenues]
    assert len(cles) <= nb_max, (
        f"{len(cles)} propositions rendues pour {nb_max} demandées : {cles}"
    )
    assert len(set(map(repr, cles))) == len(cles), (
        f"la même candidate est proposée deux fois : {cles}. Deux cartes identiques "
        "ne sont pas deux propositions."
    )
    if choix.pool:
        connues = {repr(p.cle) for p in choix.pool}
        etrangeres = [c for c in cles if repr(c) not in connues]
        assert not etrangeres, (
            f"propositions hors du vivier : {etrangeres}. Le lot choisit parmi les "
            "candidates, il n'en invente pas."
        )


def verifier_pas_de_trio_de_clones(choix: VueChoix, *, seuil_recouvrement: float | None = None) -> None:
    """Deux propositions indiscernables ne sont pas deux propositions — sauf à le dire.

    Formulation **sans seuil** sur les axes — le contrat ne chiffre pas
    « éloignées », donc on n'exige rien de chiffré : deux retenues dont *tous*
    les axes perceptibles sont égaux au bit près sont, sur les axes, la même
    sortie vue deux fois.

    **Ce que Q43 a changé, le 17/09/2026.** Ce n'est plus disqualifiant en
    soi : le mainteneur a tranché que « le parcours lui-même est distinctif en
    soi », et deux boucles aux axes identiques peuvent parfaitement aller à
    deux endroits opposés. Le lot a donc désormais **deux sorties honnêtes**,
    et une seule faute :

    - il n'affirme pas le contraste, et dit pourquoi — la voie d'avant, qui
      reste ouverte ;
    - ou il prouve que les tracés vont ailleurs (recouvrement sous le seuil)
      **et** dit que les propositions se valent (la phrase de Q45) ;
    - la faute : les publier comme contrastées en laissant croire qu'une
      différence mesurée les sépare, alors qu'aucune ne les sépare.

    Le recouvrement est exigé **lu**, pas supposé : une implémentation qui ne
    le publie pas ne peut pas s'en prévaloir.
    """
    jumelles = []
    for i, a in enumerate(choix.retenues):
        for b in choix.retenues[i + 1 :]:
            if all(
                abs(a.axe(nom) - b.axe(nom)) <= MARGE * max(1.0, abs(a.axe(nom)))
                for nom in AXES
            ):
                jumelles.append((a.cle, b.cle))
    if not jumelles:
        return
    if not choix.contraste_affirme:
        assert choix.motif.strip(), (
            f"le lot rend des propositions jumelles ({jumelles}) sans affirmer le contraste, "
            "mais sans rien dire non plus. Le contrat demande de **le dire**."
        )
        return
    seuil = seuil_recouvrement if seuil_recouvrement is not None else seuil_recouvrement_du_lot()
    inconnus = [p.cle for p in choix.retenues if p.recouvrement_max is None]
    assert seuil is not None and not inconnus, (
        f"propositions identiques sur tous les axes perceptibles : {jumelles}, annoncées "
        f"contrastées, et le recouvrement de routes n'est pas lisible ({inconnus=}, "
        f"{seuil=}). Depuis Q43 c'est le tracé qui les distingue : sans ce chiffre, rien "
        "ne prouve qu'elles vont ailleurs."
    )
    trop = [(p.cle, p.recouvrement_max) for p in choix.retenues if p.recouvrement_max > seuil]
    assert not trop, (
        f"propositions identiques sur tous les axes perceptibles : {jumelles}, et leurs "
        f"tracés se recouvrent au-delà du seuil {seuil} : {trop}. Rien ne les distingue, "
        "ni les chiffres ni la carte."
    )
    assert choix.equivalence_dite, (
        f"propositions identiques sur tous les axes perceptibles : {jumelles}, publiées "
        "comme contrastées sans dire qu'elles se valent. Q45, mots du mainteneur : « s'il "
        "n'y a pas de pluie et peu de vent et que tout est plat, à un moment rien ne "
        "change » — et le produit doit le dire, pas chercher une différence qui n'existe "
        f"pas. Ce que le lot a écrit : {choix.motif.strip()!r}"
    )


def verifier_plus_etale_que_le_tri(choix: VueChoix) -> None:
    """Les retenues doivent être plus éloignées que les trois premières du tri.

    À n'appeler que sur un vivier construit pour que ce soit possible — sinon
    l'exigence n'aurait pas de sens. La marge est franche (le vivier
    `vivier_contrastable` met des clones exacts en tête, distance 0), pas
    épsilonesque : c'est une différence de conception, pas du bruit.
    """
    pool = choix.pool
    assert len(pool) >= 3, "vivier trop petit pour que la question se pose"
    portees = etendues(pool)
    tete = tri_primaire(pool)[: len(choix.retenues)]
    ecart_tete = _ecart_minimal(tete, portees)
    ecart_retenu = _ecart_minimal(choix.retenues, portees)
    assert ecart_retenu > ecart_tete + 1e-6, (
        f"les retenues {[p.cle for p in choix.retenues]} sont espacées de {ecart_retenu:.4f}, "
        f"les {len(tete)} premières du tri {[p.cle for p in tete]} de {ecart_tete:.4f} : le lot "
        "rend le sommet d'un classement unique, pas des représentants éloignés "
        "(contrat §3.3.3)."
    )


def _ecart_minimal(groupe: Sequence[VueProposition], portees: dict[str, float]) -> float:
    if len(groupe) < 2:
        return 0.0
    return min(
        distance(a, b, portees)
        for i, a in enumerate(groupe)
        for b in groupe[i + 1 :]
    )


def verifier_phrases(choix: VueChoix) -> None:
    """Les phrases : jamais absentes du champ, jamais partagées, jamais en langage de note.

    **Une phrase vide n'est plus un défaut, depuis Q43** (17/09/2026). La
    rédaction d'avant l'interdisait — « si aucune phrase n'est écrivable, il
    faut en rendre moins » — et c'était la règle retirée, vue depuis les
    phrases : elle obligeait à jeter un tracé franchement différent quand on
    ne savait pas le résumer. Une proposition sans phrase est désormais une
    proposition dont le tracé parle seul, et la carte le montre.

    Ce qui reste, et qui est ce qui comptait vraiment :

    - le **champ** existe (`None` = le lot ne publie rien, et personne ne peut
      lire ce qui distingue quoi) ;
    - deux propositions ne partagent jamais une même phrase non vide — une
      phrase qui dit ce qui distingue une proposition **des autres** ne peut
      pas être portée par deux ;
    - aucune n'est du langage de note ;
    - **et si aucune n'a de phrase, le lot le dit** (Q45) : trois cartes sans
      un mot laissent le cycliste chercher une différence que le produit sait
      inexistante.
    """
    if len(choix.retenues) < 2:
        return
    for p in choix.retenues:
        assert p.phrase is not None, f"candidate {p.cle!r} : aucune phrase (contrat §3.3.3)"
        assert not phrase_est_en_langage_de_note(p.phrase), (
            f"candidate {p.cle!r} : « {p.phrase} » est du langage de note. Le contrat demande "
            "du langage de cycliste : « la plus sèche », « aucun demi-tour », « 20 minutes de "
            "moins » — jamais « note 1,93 »."
        )
    dites = [_sans_accents_bas(p.phrase or "").strip() for p in choix.retenues]
    dites = [d for d in dites if d]
    assert len(set(dites)) == len(dites), (
        f"deux propositions reçoivent la même phrase : {dites}. Une phrase qui dit ce qui "
        "distingue une proposition **des deux autres** ne peut pas être partagée."
    )
    assert dites or choix.equivalence_dite, (
        f"{len(choix.retenues)} propositions et pas une phrase, sans dire pourquoi. Q45 : "
        "« ces trois boucles se valent, choisissez où vous voulez aller » est une information "
        f"honnête, et le silence n'en est pas une. Ce que le lot a écrit : {choix.motif.strip()!r}"
    )


def verifier_phrases_vraies(choix: VueChoix) -> None:
    """Une phrase est une affirmation : elle doit être **vraie**.

    Pour chaque affirmation du lexique reconnue dans une phrase, la proposition
    doit réellement être la meilleure du trio sur l'axe correspondant (ou
    porter zéro demi-tour, pour l'affirmation « aucun demi-tour »). Une phrase
    dont aucune tournure n'est reconnue n'est pas sanctionnée ici — le lexique
    n'est pas la loi ; c'est `verifier_phrase_parle_du_bon_axe` qui s'en charge,
    sur des viviers construits pour n'avoir qu'un seul axe discriminant.
    """
    for p in choix.retenues:
        autres = [q for q in choix.retenues if q.cle != p.cle]
        if not autres:
            continue
        for a in affirmations_de(p.phrase or ""):
            # Affirmation **descriptive** : elle se vérifie contre l'orientation
            # que le lot publie, et c'est le contrôle le plus dur — il attrape
            # une phrase de vent collée à la mauvaise proposition même quand les
            # trois portent la même valeur numérique.
            if a.orientation is not None and p.orientation is not None:
                assert p.orientation == a.orientation, (
                    f"proposition {p.cle!r} : « {p.phrase} » annonce un vent "
                    f"« {a.orientation} », mais le lot publie « {p.orientation} ». "
                    "Une phrase est une affirmation : elle doit être vraie."
                )
                continue
            mien = p.axe(a.axe)
            if a.sens == "zero":
                assert abs(mien) <= MARGE, (
                    f"candidate {p.cle!r} : « {p.phrase} » alors que {a.axe} vaut {mien}. "
                    "Une phrase fausse est pire qu'une phrase absente."
                )
                continue
            leur = (
                min(q.axe(a.axe) for q in autres)
                if a.sens == "min"
                else max(q.axe(a.axe) for q in autres)
            )
            mieux = mien <= leur + MARGE if a.sens == "min" else mien >= leur - MARGE
            assert mieux, (
                f"candidate {p.cle!r} : « {p.phrase} » affirme être la meilleure sur {a.axe} "
                f"({a.sens}), mais elle vaut {mien} quand une autre retenue vaut {leur}. "
                "Contrat §3.3.3 : la phrase dit ce qui la **distingue**."
            )


def verifier_phrase_parle_du_bon_axe(choix: VueChoix, axe: str, extreme: str) -> None:
    """Sur un vivier à un seul axe discriminant, la phrase doit parler de cet axe.

    `extreme` vaut « min » ou « max » : la proposition qui porte l'extrême de
    `axe` parmi les retenues est celle dont la phrase doit nommer cet axe. C'est
    l'exigence la plus directe du contrat — « une phrase par proposition disant
    ce qui la distingue » — et la seule qui attrape une phrase générique.
    """
    if len(choix.retenues) < 2:
        return
    valeurs = [(p.axe(axe), p) for p in choix.retenues]
    cible = (min if extreme == "min" else max)(valeurs, key=lambda t: t[0])[1]
    noms = {a.axe for a in affirmations_de(cible.phrase or "")}
    assert axe in noms, (
        f"candidate {cible.cle!r} porte l'extrême de « {axe} » ({cible.axe(axe)}) parmi les "
        f"retenues, et c'est la **seule** chose qui la distingue sur ce vivier, mais sa "
        f"phrase « {cible.phrase} » n'en parle pas (axes reconnus : {sorted(noms) or 'aucun'}). "
        "Soit la phrase ne dit pas ce qui distingue, soit sa tournure est absente du lexique "
        "de `fabriques_propositions.AFFIRMATIONS` — dans ce second cas, c'est le lexique qu'il faut "
        "étendre, et cela se décide avec le mainteneur, pas en silence."
    )


# --- les marges de contraste du contrat §3.3.3 bis ----------------------------

#: Les marges **dans l'unité de chaque axe**, telles que le contrat §3.3.3 bis
#: les fixe le 16/09/2026 : « durée ≥ 10 min ; demi-tours : un compte
#: différent ; pluie ≥ 0,5 mm ; vent : une catégorie relative dominante
#: différente ; ville : un écart de densité chiffré par la mesure du lot ;
#: terrain : au moins 1,0 km équivalent, soit le prix d'un feu ».
#:
#: Ce sont **les chiffres du contrat**, pas les miens : c'est tout l'intérêt.
#: J'avais signalé que « éloignées » n'était pas chiffré et que c'était le plus
#: large trou de ma couverture — une implémentation rendant trois propositions
#: séparées de 1 % serait passée. Le contrat a tranché ; ces marges sont
#: désormais **exigées**, et non plus seulement souhaitées.
#:
#: La densité de marqueurs est le seul axe que le contrat renvoie à « la mesure
#: du lot ». On lit donc le pas du lot lui-même quand il est lisible, plutôt
#: que d'inventer un chiffre que le contrat refuse d'inventer.
MARGES_CONTRASTE: dict[str, float] = {
    "depassement_s": 600.0,
    "pluie_mm": 0.5,
    "note_terrain": 1.0,
    "densite_marqueurs_km": 0.5,
}

#: Les axes dont la marge n'est pas un nombre mais une **différence de
#: catégorie** : un compte de demi-tours différent, une orientation au vent
#: différente.
AXES_CATEGORIELS = ("demi_tours", "orientation")


def marges_du_lot() -> dict[str, float]:
    """Les marges de `MARGES_CONTRASTE`, remplacées par celles du lot si lisibles.

    Le contrat renvoie explicitement la marge de densité à « la mesure du
    lot » : la lire chez lui n'est pas se rendre, c'est appliquer le contrat.
    Les autres ne sont lues que pour signaler un écart, jamais pour s'y plier —
    si le lot s'écartait d'un chiffre que le contrat fixe, c'est le lot qui a
    tort, et `verifier_pas_de_marge_relachee` le dira.
    """
    marges = dict(MARGES_CONTRASTE)
    try:
        from ourouler.sortie import contraste
    except ImportError:
        return marges
    pas = getattr(contraste, "PAS_MARQUEURS_KM", None)
    if isinstance(pas, (int, float)) and math.isfinite(float(pas)) and pas > 0:
        marges["densite_marqueurs_km"] = float(pas)
    return marges


def verifier_pas_de_marge_relachee(module: Any | None = None) -> None:
    """Les pas du lot ne doivent pas être plus laxistes que ceux du contrat.

    Un pas plus **large** que celui du contrat est une exigence renforcée et
    reste acceptable ; un pas plus **étroit** laisse passer des propositions
    que le contrat déclare indiscernables.

    `module` existe pour que l'autocontrôle puisse lui présenter un cobaye aux
    pas relâchés : sans ce paramètre, ce vérificateur n'était couvert par
    aucune mutation, et le neutraliser ne faisait échouer aucun test — un
    vérificateur creux, exactement ce que ce dossier traque ailleurs.
    """
    contraste = module
    if contraste is None:
        try:
            from ourouler.sortie import contraste
        except ImportError:  # pragma: no cover - le lot est fusionné
            return
    attendus = {
        "PAS_DUREE_S": 600.0,
        "PAS_PLUIE_MM": 0.5,
        "PAS_TERRAIN_KM_EQ": 1.0,
    }
    for nom, plancher in attendus.items():
        valeur = getattr(contraste, nom, None)
        if valeur is None:
            continue
        assert float(valeur) >= plancher, (
            f"{nom} = {valeur} alors que le contrat §3.3.3 bis fixe {plancher} dans l'unité "
            "de l'axe. Un pas plus étroit laisse passer des propositions que le contrat "
            "déclare indiscernables — « être meilleur de 1 % n'est pas une différence pour "
            "un cycliste »."
        )


def _axes_gagnes(sujet: VueProposition, autres: Sequence[VueProposition],
                 marges: dict[str, float]) -> set[str]:
    """Les axes où `sujet` est meilleur que **tous** les autres, de la marge exigée."""
    gagnes: set[str] = set()
    for nom, marge in marges.items():
        sens = AXES.get(nom, "min")
        mien = sujet.axe(nom)
        if sens == "min":
            if all(mien <= q.axe(nom) - marge for q in autres):
                gagnes.add(nom)
        elif all(mien >= q.axe(nom) + marge for q in autres):
            gagnes.add(nom)
    # Demi-tours : « un compte différent », et en moins.
    mien = sujet.axe("demi_tours")
    if all(mien < q.axe("demi_tours") for q in autres):
        gagnes.add("demi_tours")
    # Vent : « une catégorie relative dominante différente ».
    if sujet.orientation is not None and all(
        q.orientation != sujet.orientation for q in autres
    ):
        gagnes.add("orientation")
    return gagnes


def verifier_verrou_de_recouvrement(
    choix: VueChoix, *, seuil_recouvrement: float | None = None
) -> None:
    """Le seul verrou qui reste depuis Q43 : les tracés vont-ils ailleurs ?

    Le contrat §3.3.3 bis en exigeait trois choses. Les deux premières — chaque
    proposition meilleure sur un axe, et sur un axe différent des autres — sont
    tombées le 17/09/2026 : *« le parcours lui-même est distinctif en soi »*.
    Elles visaient les descriptions et finissaient par jeter des tracés
    franchement différents faute de savoir les résumer en une phrase.

    Reste la troisième, et elle porte désormais tout : **le recouvrement de
    routes entre deux retenues reste sous le seuil du lot.** Contrat §3.3.2 :
    « deux boucles peuvent avoir des notes très éloignées et emprunter les
    mêmes routes ; elles se ressembleront sur la carte quoi qu'en disent les
    chiffres. »

    Ce que le retrait ne dispense pas de vérifier est ailleurs, et y a gagné en
    exigence : `verifier_phrases_meritees` (une phrase ne s'écrit que si elle
    est méritée d'une marge du contrat) et `verifier_pas_de_trio_de_clones`
    (des propositions qui se valent doivent le dire).
    """
    exiger_axes_lus(choix.retenues)
    if len(choix.retenues) < 2:
        return
    seuil = seuil_recouvrement if seuil_recouvrement is not None else seuil_recouvrement_du_lot()
    if seuil is None:
        return
    trop = [
        (p.cle, p.recouvrement_max)
        for p in choix.retenues
        if p.recouvrement_max is not None and p.recouvrement_max > seuil
    ]
    assert not trop, (
        f"recouvrement de routes au-dessus du seuil {seuil} : {trop}. Contrat §3.3.2 : « deux "
        "boucles peuvent avoir des notes très éloignées et emprunter les mêmes routes ; elles "
        "se ressembleront sur la carte quoi qu'en disent les chiffres. » Depuis Q43 c'est le "
        "seul verrou : s'il ne mord pas, plus rien ne garantit que les propositions diffèrent."
    )


def verifier_phrases_meritees(choix: VueChoix) -> None:
    """Une phrase qui nomme un axe doit être gagnée **d'une marge du contrat**.

    C'est ce que les marges du §3.3.3 bis gardent après Q43. Elles ne décident
    plus qui entre dans le trio — le recouvrement s'en charge — mais elles
    décident toujours **ce qu'on a le droit d'écrire**. « La plus sèche » avec
    0,05 mm d'avance est une phrase vraie au sens strict et fausse au sens qui
    compte : « être meilleur de 1 % n'est pas une différence pour un cycliste ».

    Plus strict que `verifier_phrases_vraies`, qui vérifie le **sens** de
    l'avantage à une marge de flottant près ; celui-ci en vérifie la
    **grandeur**, dans l'unité de l'axe.

    Une phrase dont aucune tournure n'est reconnue n'engage rien ici, et une
    proposition **sans phrase** n'est plus un défaut : depuis Q43, son tracé la
    distingue sans qu'on ait à la résumer.
    """
    marges = marges_du_lot()
    for p in choix.retenues:
        autres = [q for q in choix.retenues if q.cle != p.cle]
        if not autres:
            continue
        gagnes = _axes_gagnes(p, autres, marges)
        for a in affirmations_de(p.phrase or ""):
            if a.orientation is not None:
                assert "orientation" in gagnes, (
                    f"proposition {p.cle!r} : « {p.phrase} » présente son vent comme ce qui la "
                    f"distingue, mais elle n'est pas la seule de son orientation "
                    f"({[q.orientation for q in autres]}). Deux propositions « vent dans le dos "
                    "au retour » ne se distinguent pas par le vent."
                )
                continue
            if a.sens == "zero":
                continue  # « aucun demi-tour » est un fait absolu, pas un comparatif
            assert a.axe in gagnes, (
                f"proposition {p.cle!r} : « {p.phrase} » se présente comme la meilleure sur "
                f"{a.axe}, mais pas de la marge que le contrat exige ({marges.get(a.axe)} dans "
                f"l'unité de l'axe). Valeurs : moi {p.axe(a.axe)}, les autres "
                f"{[q.axe(a.axe) for q in autres]}. Axes réellement gagnés : {sorted(gagnes)}."
            )


def seuil_recouvrement_du_lot() -> float | None:
    """Le seuil de recouvrement **mesuré par le lot**, ou `None` s'il est illisible.

    Le contrat §3.3.2 dit que ce seuil « se **mesure** sur la distribution des
    recouvrements deux à deux de candidates réellement générées, il ne s'invente
    pas ». Je n'ai pas cette distribution ; je lis donc celui du lot plutôt que
    d'en inventer un, et c'est la seule attitude honnête ici.
    """
    try:
        from ourouler.sortie import contraste
    except ImportError:
        return None
    valeur = getattr(contraste, "SEUIL_RECOUVREMENT", None)
    if isinstance(valeur, (int, float)) and math.isfinite(float(valeur)):
        return float(valeur)
    return None


def verifier_part_connue_hors_selection(choix: VueChoix) -> None:
    """La part de routes connues ne doit **jamais** départager deux propositions.

    Doctrine, reprise au contrat §3.3.2 le 16/09/2026 : les routes déjà roulées
    sont un instrument de mesure, pas un critère. Le contrôle possible depuis
    l'extérieur : aucune phrase ne doit s'appuyer dessus, et l'axe ne doit
    exister dans aucune structure d'axes du lot.
    """
    for p in choix.retenues:
        plat = _sans_accents_bas(p.phrase or "")
        for tournure in ("que vous connaissez", "routes connues", "deja roule",
                         "routes nouvelles", "que vous ne connaissez pas"):
            assert _sans_accents_bas(tournure) not in plat, (
                f"proposition {p.cle!r} : « {p.phrase} » distingue par les routes déjà "
                "roulées. Doctrine et contrat §3.3.2 : « la part connue reste affichée, "
                "peut servir à décrire une proposition retenue pour une autre raison, et "
                "n'entre ni dans une note ni dans la sélection »."
            )


# --- densité de marqueurs -----------------------------------------------------

#: Les marqueurs que le contrat §3.3.2 nomme : « feux, passages piétons,
#: ralentisseurs » — c'est-à-dire ce que `terrain._noeuds_tagues` sait déjà
#: reconnaître. On réutilise ses constantes plutôt que d'en réécrire une
#: seconde liste qui divergerait.
def marqueurs_du_projet() -> tuple[frozenset[str], str, frozenset[str]]:
    """Le vocabulaire des marqueurs, **où qu'il vive**.

    Il était dans `seance.terrain` sur `sprint-5` ; le lot L5.3 l'a déplacé
    dans `boucle.marqueurs`, que `seance.terrain` importe désormais, pour que
    la note sous un bloc et la densité du tracé ne puissent pas diverger. Le
    déplacement est un bon geste : ce sont les **valeurs** que la
    non-régression fige, pas leur adresse. On cherche donc les deux, dans
    l'ordre où elles vivent aujourd'hui.
    """
    for module in ("ourouler.boucle.marqueurs", "ourouler.seance.terrain"):
        try:
            mod = __import__(module, fromlist=["NOEUDS_CARREFOUR"])
            return (
                mod.NOEUDS_CARREFOUR,
                mod.CLE_RALENTISSEUR,
                mod.RALENTISSEURS_SANS_EFFET,
            )
        except (ImportError, AttributeError):
            continue
    raise AssertionError(
        "vocabulaire des marqueurs introuvable : ni `ourouler.boucle.marqueurs` ni "
        "`ourouler.seance.terrain` n'expose NOEUDS_CARREFOUR / CLE_RALENTISSEUR / "
        "RALENTISSEURS_SANS_EFFET"
    )


def compter_marqueurs(trace: Trace) -> int:
    """Le nombre de **nœuds** tagués du tracé entier.

    On compte par nœud de fin (`Segment.fin_idx`) et non par tronçon : deux
    tronçons qui se terminent au même nœud ne font qu'un feu. C'est la règle
    que `seance.terrain._noeuds_tagues` appliquait déjà, et la compter de
    travers ferait sortir un facteur deux aux carrefours.
    """
    carrefour, cle_calme, sans_effet = marqueurs_du_projet()
    natures: dict[int, str] = {}
    for segment in trace.segments:
        tags = segment.node_tags
        if tags.get("highway", "") in carrefour:
            natures[segment.fin_idx] = tags["highway"]
            continue
        calme = tags.get(cle_calme, "")
        if calme and calme not in sans_effet:
            natures[segment.fin_idx] = cle_calme
    return len(natures)


@dataclass(frozen=True)
class Densite:
    """Une densité au kilomètre, ou l'aveu qu'on ne sait pas.

    `connue=False` est la forme que prend « on ne sait pas » : le contrat du
    sprint 3 interdit qu'une classe inconnue devienne un malus, et ici le
    risque est symétrique et pire — une portion **sans tag** rendrait zéro,
    c'est-à-dire « la campagne », alors que c'est « on ne sait pas ».
    """

    par_km: float
    connue: bool
    motif: str = ""


def trace_pour_densite(
    longueur_m: float,
    n_marqueurs: int,
    *,
    sans_segments: bool = False,
    node_tags: dict[int, dict[str, str]] | None = None,
    distance_annoncee: float | None = None,
    cap_deg: float = 90.0,
) -> Trace:
    """Une droite de `longueur_m` portant `n_marqueurs` feux régulièrement espacés.

    `cap_deg` oriente la droite : deux tracés de caps différents ne se
    recouvrent pas, ce qu'exige tout test qui passe par `contraste.choisir` —
    deux droites de même cap partant du même point sont la **même route**, et
    le lot a raison de refuser de les proposer toutes les deux.

    `distance_annoncee` force `trace.distance_m` indépendamment de la
    géométrie : c'est ainsi qu'on fabrique le tracé de longueur nulle ou de
    longueur illisible sans fabriquer une géométrie absurde.
    """
    pas_m = 100.0
    n = max(int(longueur_m // pas_m), 1)
    coords = fabriques_seance.droite(n, pas_m=pas_m, cap_deg=cap_deg, pentes=0.0, alt0=50.0)
    if node_tags is None:
        ecart = max(1, n // max(n_marqueurs, 1))
        node_tags = {i * ecart: {"highway": "traffic_signals"} for i in range(n_marqueurs)}
    trace = fabriques_seance.trace_taguee(
        coords, tags={"highway": "tertiary"}, node_tags=node_tags, sans_segments=sans_segments
    )
    if distance_annoncee is not None:
        trace.distance_m = distance_annoncee
    return trace


def densite_reference(trace: Trace) -> Densite:
    """Le cobaye : marqueurs du tracé entier divisés par ses kilomètres."""
    if not trace.segments:
        return Densite(0.0, connue=False, motif="routes inconnues")
    longueur_m = trace.distance_m
    if longueur_m is None or not math.isfinite(longueur_m) or longueur_m <= 0:
        longueur_m = trace.points[-1].dist_m if len(trace.points) >= 2 else 0.0
    if not math.isfinite(longueur_m) or longueur_m <= 0:
        return Densite(0.0, connue=False, motif="tracé de longueur nulle")
    return Densite(compter_marqueurs(trace) / (longueur_m / 1000.0), True)


def verifier_densite(
    fn: Callable[..., Any], *, lire: Callable[[Any], Densite] | None = None
) -> None:
    """La batterie de la densité : le contrat §3.3.2 et l'invariant du sprint 3.

    `fn(trace)` rend n'importe quoi que `lire` sait convertir en `Densite`.

    **La mesure porte sur le tracé entier**, pas sur un couloir : c'est le
    choix du lot, et il est justifié — sur une endurance il n'y a aucun bloc
    sous lequel découper un couloir, et c'est le cas courant du mainteneur.
    La batterie a été réécrite pour cette signature ; les exigences, elles,
    n'ont pas bougé.
    """
    lire = lire or (lambda v: v)

    # 10 marqueurs sur ~5 km : 2,0 /km. Ni 10 (le compte brut, « au kilomètre »
    # oublié), ni 0,002 (divisé par les mètres).
    #
    # L'attendu se calcule sur la longueur **que le tracé annonce**, pas sur les
    # 5 000 m nominaux : la géométrie sphérique des fabriques rend 4 994 m, et
    # comparer à 2,0 pile testerait la fabrique au lieu de tester la division.
    # C'est la leçon de L5.1, prise par l'autre bout — une marge est nécessaire,
    # mais une marge qui masque l'écart à mesurer ne vaut rien : ici l'attendu
    # est exact et c'est la référence qui est ajustée.
    court = trace_pour_densite(5000.0, 10)
    attendu = 10.0 / (court.distance_m / 1000.0)
    d = lire(fn(court))
    assert d.connue, "un tracé dont les tronçons sont tagués porte une densité connue"
    assert d.par_km == pytest_approx(attendu, rel=1e-9), (
        f"10 marqueurs sur {court.distance_m:.0f} m font {attendu:.4f} /km, pas {d.par_km!r}. "
        "Un compte brut rendrait 10 ; une division par les mètres rendrait 0,002."
    )

    # La même densité doit sortir d'un tracé deux fois plus long portant deux
    # fois plus de marqueurs : c'est ce qui distingue une densité d'un compte.
    long_ = trace_pour_densite(10_000.0, 20)
    d2 = lire(fn(long_))
    assert d2.par_km == pytest_approx(20.0 / (long_.distance_m / 1000.0), rel=1e-9), (
        f"20 marqueurs sur {long_.distance_m:.0f} m : {d2.par_km!r}"
    )
    assert abs(d2.par_km - d.par_km) < 0.02, (
        f"deux fois plus de marqueurs sur deux fois plus de kilomètres donnent la même "
        f"densité : {d.par_km!r} contre {d2.par_km!r}. Une densité ne dépend pas de la "
        "longueur du tracé ; un compte, si — et l'écart serait alors de 10, pas de 0,02."
    )

    # Longueur nulle, négative, illisible : ni division par zéro, ni NaN.
    for annoncee in (0.0, -500.0, float("nan"), float("inf")):
        lue = lire(fn(trace_pour_densite(5000.0, 10, distance_annoncee=annoncee)))
        assert math.isfinite(lue.par_km), (
            f"distance annoncée {annoncee!r} : densité {lue.par_km!r} — division par zéro, "
            "ou un non-fini qui traversera tout le contraste"
        )

    # Un tracé réellement vide : deux points confondus, aucun kilomètre.
    vide_geometrique = trace_pour_densite(100.0, 0, distance_annoncee=0.0)
    lue = lire(fn(vide_geometrique))
    assert math.isfinite(lue.par_km), f"tracé de longueur nulle : densité {lue.par_km!r}"

    # Tracé sans **aucun** segment : « on ne sait pas », jamais « la campagne ».
    d_nu = lire(fn(trace_pour_densite(5000.0, 0, sans_segments=True)))
    assert not d_nu.connue, (
        "un tracé sans segments rend une densité de zéro **connue** : c'est « la campagne "
        "prouvée » là où il n'y a que « on ne sait pas ». Le contrat du sprint 3 interdit "
        "qu'une classe inconnue devienne un malus ; ici l'erreur est symétrique et pire, "
        "elle en ferait un bonus — l'outil proposerait par préférence les tracés qu'il ne "
        "sait pas lire."
    )

    # Segments présents mais aucun marqueur : là, zéro est une **mesure**.
    d_vide = lire(fn(trace_pour_densite(5000.0, 0)))
    assert d_vide.connue and d_vide.par_km == pytest_approx(0.0), (
        f"des tronçons tagués sans marqueur, c'est une densité nulle **connue** : {d_vide!r}"
    )

    # Deux nœuds tagués côte à côte, et un nœud qui porte les deux tags.
    empiles = lire(
        fn(
            trace_pour_densite(
                5000.0,
                0,
                node_tags={
                    30: {"highway": "traffic_signals"},
                    31: {"highway": "stop"},
                    32: {"highway": "traffic_signals", CLE_CALME: "bump"},
                },
            )
        )
    )
    assert math.isfinite(empiles.par_km) and empiles.par_km >= 0, (
        f"nœuds empilés : densité {empiles.par_km!r}"
    )
    reference_empiles = trace_pour_densite(5000.0, 0)
    assert empiles.par_km == pytest_approx(
        3.0 / (reference_empiles.distance_m / 1000.0), rel=1e-9
    ), (
        f"trois nœuds marqués sur 5 km font 0,6 /km, pas {empiles.par_km!r}. Le nœud qui porte "
        "un feu **et** un ralentisseur ne compte qu'une fois : « se compter deux fois serait "
        "pire que de se manquer »."
    )


#: La clé des ralentisseurs, lue une fois pour les fabriques ci-dessus.
CLE_CALME = "traffic_calming"


def pytest_approx(valeur: float, *, rel: float = 1e-9, abs_: float = 1e-9):  # noqa: D417
    """`pytest.approx` sans importer pytest dans un module de fabriques."""

    class _Approx:
        def __eq__(self, autre: object) -> bool:
            if not isinstance(autre, (int, float)):
                return False
            return abs(float(autre) - valeur) <= max(abs_, rel * abs(valeur))

        def __repr__(self) -> str:  # pragma: no cover - lisibilité d'échec
            return f"≈{valeur!r}"

    return _Approx()


# --- la question du vent ------------------------------------------------------

#: L'horizon au-delà duquel le contrat §3.3.4 interdit la question. « on ne la
#: pose pas au-delà de 3 jours » — donc 3 jours pile est encore dedans.
HORIZON_JOURS = 3


def question_vent_reference(
    *,
    vent_kmh: float | None,
    direction_deg: float | None,
    jours_a_l_avance: float,
    seuil_kmh: float,
) -> bool:
    """Le cobaye des deux gardes du contrat §3.3.4."""
    if vent_kmh is None or not math.isfinite(vent_kmh):
        return False
    if direction_deg is None or not math.isfinite(direction_deg):
        return False
    if not math.isfinite(jours_a_l_avance) or jours_a_l_avance > HORIZON_JOURS:
        return False
    return vent_kmh >= seuil_kmh


def balayer_seuil(poser: Callable[[float], bool], vents: Sequence[float]) -> list[bool]:
    return [bool(poser(v)) for v in vents]


def transitions(reponses: Sequence[bool]) -> int:
    """Le nombre de changements dans une suite de booléens."""
    return sum(1 for a, b in zip(reponses, reponses[1:], strict=False) if a != b)


#: Balayage de vent des tests de garde, en km/h. Il encadre les deux seules
#: valeurs que le contrat §3.3.4 chiffre : 2,5 (« sous le seuil ») et 14 (le
#: vent médian, celui pour lequel la question existe).
VENTS_BALAYES = (0.0, 0.5, 1.0, 2.0, 2.5, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 20.0, 30.0, 45.0)


def verifier_gardes_vent(poser: Callable[..., bool]) -> None:
    """Les deux gardes du contrat §3.3.4, **sans supposer la valeur du seuil**.

    `poser(vent_kmh=…, direction_deg=…, jours_a_l_avance=…)` rend un booléen.

    Le contrat ne chiffre pas le seuil de vent : il dit seulement que 2,5 km/h
    est dessous. On n'exige donc rien d'autre que ce qu'il dit, plus deux
    propriétés qui ne dépendent d'aucune valeur — la monotonie et le zéro.
    """
    appel = lambda **kw: bool(  # noqa: E731 - lisibilité locale
        poser(**{"vent_kmh": 14.0, "direction_deg": 250.0, "jours_a_l_avance": 1.0, **kw})
    )

    # --- garde 1 : le seuil de vent
    assert not appel(vent_kmh=0.0), (
        "vent nul : l'orientation au vent ne change rien, la question « n'apprend qu'à "
        "cliquer sans lire » (contrat §3.3.4)"
    )
    assert not appel(vent_kmh=2.5), (
        "2,5 km/h : le contrat §3.3.4 place explicitement cette valeur **sous** le seuil "
        "(« Vent médian 14 km/h mais descend à 2,5 : sous le seuil »)"
    )
    reponses = balayer_seuil(lambda v: appel(vent_kmh=v), VENTS_BALAYES)
    balayage = list(zip(VENTS_BALAYES, reponses, strict=True))
    assert transitions(reponses) <= 1, (
        f"la question n'est pas monotone en vitesse de vent : {balayage}. "
        "Un seuil se franchit une fois ; deux bascules trahissent un intervalle ou une "
        "comparaison de travers."
    )
    assert reponses[-1], (
        "45 km/h et toujours pas de question : le seuil ne peut pas être au-dessus de tout "
        f"({balayage})"
    )

    # --- garde 2 : l'horizon de 3 jours
    #
    # Le vent des tests d'horizon est celui dont le balayage vient de prouver
    # qu'il **déclenche** la question, et non une valeur choisie d'avance : le
    # contrat ne chiffre pas le seuil, donc rien ne garantit que 14 km/h soit
    # au-dessus. Sans cette précaution, un seuil haut ferait échouer la garde
    # d'horizon pour une raison qui n'est pas la sienne.
    vent_declencheur = VENTS_BALAYES[-1]
    appel = lambda **kw: bool(  # noqa: E731 - lisibilité locale
        poser(
            **{
                "vent_kmh": vent_declencheur,
                "direction_deg": 250.0,
                "jours_a_l_avance": 1.0,
                **kw,
            }
        )
    )
    # L'horizon se balaye en **jours entiers** : l'entrée du lot est une date
    # de séance et une date du jour, et une demi-journée d'avance n'existe pas
    # dans ce domaine. Mon premier balayage passait 3,01 jours et criait à tort
    # — une valeur qui ne peut pas se produire ne prouve rien.
    assert appel(jours_a_l_avance=0), "aujourd'hui : dans l'horizon"
    assert appel(jours_a_l_avance=HORIZON_JOURS), (
        f"{HORIZON_JOURS} jours pile : le contrat dit « on ne propose une orientation au vent "
        "que **jusqu'à** 3 jours » et chiffre ce jour-là (88 % de bon secteur). La borne est "
        "donc incluse — si l'implémentation l'a lue exclusive, c'est une lecture du contrat à "
        "trancher avec le mainteneur, pas à deviner."
    )
    for au_dela in (HORIZON_JOURS + 1, 5, 10, 60):
        assert not appel(jours_a_l_avance=au_dela), (
            f"{au_dela} jours : au-delà de 3 jours « l'outil dit qu'il ne sait pas » "
            "(contrat §3.3.4 et §3.1.2 — AROME s'arrête à 67 h)"
        )

    # --- météo absente, vent connu sans direction
    assert not appel(vent_kmh=None), "météo absente : on ne promet pas une orientation au vent"
    assert not appel(direction_deg=None), (
        "vent connu mais direction inconnue : on ne peut pas dire « vous rentrerez avec le vent "
        "dans le dos » sans savoir d'où il vient"
    )
    for absurde in (float("nan"), float("inf")):
        assert not appel(vent_kmh=absurde), (
            f"vent {absurde!r} : une valeur non finie n'est pas un vent"
        )
    # La direction non finie a son vérificateur à elle (`verifier_direction_non_finie`) :
    # c'est un défaut réel du lot au 16/09/2026, et le garder ici ferait
    # échouer toute la batterie pour un seul point, en masquant les autres.


def verifier_direction_non_finie(poser: Callable[..., bool]) -> None:
    """Une direction de vent non finie ne doit pas faire poser la question.

    `interroger` vérifie `math.isfinite` sur la **vitesse** mais seulement
    `is None` sur la **direction**. Un NaN ou un infini passe donc la garde, la
    question est posée, et `QuestionVent.azimuts_pour(...)` rend
    `(nan + décalage) % 360`, c'est-à-dire `nan` — un azimut qui part ensuite
    dans `boucle.candidates.generer` puis dans l'URL BRouter.

    Le vent vient d'Open-Meteo, qui peut rendre `null` comme une valeur
    aberrante : c'est exactement la famille d'entrées hostiles que la règle
    absolue 5 demande de traiter, et le module `seance.vent` la traite déjà
    (« Invariant dur : `vent_face_ms` ne rend **jamais** un NaN »).
    """
    for absurde in (float("nan"), float("inf"), float("-inf")):
        pose = poser(vent_kmh=14.0, direction_deg=absurde, jours_a_l_avance=1)
        assert not pose, (
            f"direction du vent = {absurde!r} et la question est posée quand même. La vitesse "
            "est filtrée par `math.isfinite`, la direction seulement par `is None` : l'azimut "
            "de recherche vaut alors NaN et descend tel quel jusqu'à l'appel BRouter. "
            "Une direction qu'on ne sait pas lire, c'est « je ne sais pas », comme une "
            "direction absente."
        )


# --- géométries pour les tests sur le vrai code -------------------------------


def boucle_avec_marqueurs(n_marqueurs: int, *, rayon_m: float = 4000.0, n: int = 240) -> Trace:
    """Une boucle plate, `n_marqueurs` feux répartis régulièrement dessus."""
    pas = max(1, n // max(n_marqueurs, 1))
    noeuds = {i * pas: {"highway": "traffic_signals"} for i in range(n_marqueurs)}
    return fabriques_seance.boucle_plate(
        rayon_m=rayon_m, n=n, tags={"highway": "tertiary"}, node_tags=noeuds,
        nom=f"boucle à {n_marqueurs} marqueurs",
    )


def depart_fictif() -> tuple[float, float]:
    """Le point de départ des fabriques : rien de réel, rien de personnel."""
    return (fabriques.LAT0, fabriques.LON0)


# --- le harnais de bout en bout ----------------------------------------------
#
# Le contrat §3.3 ne nomme aucune interface interne. La seule surface stable du
# lot est donc celle que le mainteneur voit : ce que `ourouler sortie --json`
# écrit. On la pilote avec le harnais déjà écrit pour le sprint 4
# (`tests/test_sortie_commande.py`) : trois clients bouchonnés par
# `httpx.MockTransport`, aucune socket, aucune donnée réelle, un départ à
# (0, 0). Tester par là plutôt que par un nom de fonction deviné, c'est tester
# ce qui est promis plutôt que ce qu'on imagine.


def harnais() -> Any:
    """Le module `tests/test_sortie_commande.py`, ses bouchons et sa configuration."""
    import sys
    from pathlib import Path

    dossier_tests = str(Path(__file__).resolve().parent.parent)
    if dossier_tests not in sys.path:
        sys.path.insert(0, dossier_tests)
    import test_sortie_commande

    return test_sortie_commande


def moteur_brouter_clone(*, amplitude_m: float = 1.0) -> Any:
    """BRouter qui rend **le même anneau** quelle que soit la direction demandée.

    Toutes les candidates portent alors exactement le même tracé : même pluie,
    même relief, même orientation au vent, mêmes demi-tours, même durée. C'est
    le vivier où aucune paire n'est contrastable, et où le contrat impose de ne
    pas prétendre le contraire.
    """
    import httpx

    h = harnais()
    from ourouler.config import depuis_dict
    from ourouler.connecteurs.brouter import ClientBrouter

    corps = h.reponse_anneau(h.anneau(0.0, amplitude_m=amplitude_m))

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=corps)

    return ClientBrouter(
        depuis_dict(h.CONFIG_BRUTE).brouter,
        http=httpx.Client(transport=httpx.MockTransport(gestionnaire)),
    )


def lancer_json(tmp_path: Any, monkeypatch: Any, capsys: Any, **kw: Any) -> dict:
    """Exécute `ourouler sortie --json` sous bouchons et rend le document."""
    import json as _json

    h = harnais()
    code = h.lancer(tmp_path, monkeypatch, json=True, **kw)
    assert code == 0, f"`ourouler sortie` a rendu {code}"
    sortie = capsys.readouterr().out
    try:
        return _json.loads(sortie)
    except ValueError as e:  # pragma: no cover - diagnostic
        raise AssertionError(f"sortie --json illisible : {e}\n{sortie[:2000]}") from e


#: Les clés sous lesquelles une phrase peut raisonnablement être publiée. Le
#: contrat ne la nomme pas ; on cherche donc large, et la sentinelle dit
#: exactement ce qu'elle a cherché quand elle ne trouve rien.
CLES_PHRASE = ("phrase", "distingue", "distinction", "resume", "résumé", "accroche", "pourquoi")


def _profond(noeud: Any, cible: str) -> list[Any]:
    """Toutes les valeurs des clés dont le nom contient `cible`, en profondeur."""
    trouvees: list[Any] = []

    def descendre(x: Any) -> None:
        if isinstance(x, dict):
            for cle, valeur in x.items():
                if isinstance(cle, str) and cible in _sans_accents_bas(cle):
                    trouvees.append(valeur)
                descendre(valeur)
        elif isinstance(x, (list, tuple)):
            for e in x:
                descendre(e)

    descendre(noeud)
    return trouvees


def valeurs_par_cle_exacte(noeud: Any, cles: Sequence[str]) -> list[tuple[str, Any]]:
    """Toutes les `(clé, valeur)` dont la clé est **exactement** l'une de `cles`.

    Une recherche par sous-chaîne ne convient pas ici : « lon » est contenu
    dans `longueur_m`, et le test des coordonnées criait sur des mètres.
    """
    voulues = set(cles)
    trouvees: list[tuple[str, Any]] = []

    def descendre(x: Any) -> None:
        if isinstance(x, dict):
            for cle, valeur in x.items():
                if cle in voulues:
                    trouvees.append((cle, valeur))
                descendre(valeur)
        elif isinstance(x, (list, tuple)):
            for e in x:
                descendre(e)

    descendre(noeud)
    return trouvees


def phrase_de(candidate: dict) -> str | None:
    """La phrase d'une candidate, sous la clé où le lot a choisi de la publier."""
    for cle in CLES_PHRASE:
        valeurs = [v for v in _profond(candidate, _sans_accents_bas(cle)) if isinstance(v, str)]
        if valeurs:
            return valeurs[0]
    return None


def propositions_du_json(doc: dict) -> list[dict]:
    """Les propositions faites au cycliste, telles que le document les publie.

    Deux règles, dans cet ordre :

    1. un bloc nommé `propositions` **est** la liste des propositions, qu'il
       porte des phrases ou non ;
    2. à défaut, les entrées de `candidates` qui portent une phrase — la forme
       qu'aurait prise le lot s'il avait enrichi le bloc existant.

    La règle 1 a été ajoutée à la réconciliation, et l'erreur qu'elle corrige
    vaut d'être écrite. Ma première version ne retenait que les entrées
    **portant une phrase**. Or le lot, tout à fait correctement, laisse la
    phrase vide quand il ne retient qu'**une** proposition : une phrase dit ce
    qui distingue « des deux autres », et sans deux autres il n'y a rien à
    dire. Mon filtre jetait donc cette proposition, rendait une liste vide, et
    cinq tests — dont les deux qui portent le cœur du lot — se mettaient en
    `skip` en annonçant « le lot n'est pas livré ». Le cas que j'avais le plus
    travaillé était précisément celui que je ne regardais plus.
    """
    for valeur in _profond(doc, "proposition"):
        if isinstance(valeur, list) and all(isinstance(e, dict) for e in valeur):
            return valeur
    for valeur in _profond(doc, "candidates"):
        if isinstance(valeur, list) and all(isinstance(e, dict) for e in valeur):
            avec_phrase = [c for c in valeur if (phrase_de(c) or "").strip()]
            if avec_phrase:
                return avec_phrase
    return []


def vue_depuis_json(candidate: dict, doc: dict, *, cle: Any = None) -> VueProposition:
    """Une `VueProposition` bâtie sur ce que le JSON publie.

    Deux formes coexistent depuis le lot, et il faut savoir lire les deux :

    * `candidates[]`, imbriquée, héritée du sprint 4 :
      `placement.duree_totale_s`, `meteo.pluie_cumulee_mm`, `part_connue`… ;
    * `propositions[]`, **plate**, écrite par le lot : `duree_s`, `pluie_mm`,
      `demi_tours`, `densite_marqueurs_km`, `part_trafic`, `orientation_vent`,
      `note_terrain`. C'est là que vivent les phrases.

    **Un axe non lu prend sa valeur neutre, et `axes_lus` dit lesquels l'ont
    été.** C'est le point qui m'a coûté un faux positif à la réconciliation :
    l'adaptateur, écrit pour la forme imbriquée, ne lisait **aucun** axe d'une
    proposition plate, rendait donc trois vues rigoureusement neutres, et le
    vérificateur de clones criait « trois propositions identiques » sur des
    propositions qui différaient très bien. Un adaptateur muet doit se
    dénoncer, pas produire un verdict.
    """
    placement = candidate.get("placement") or {}
    meteo = candidate.get("meteo") or {}
    seance = doc.get("seance") or {}
    axes = dict(NEUTRE)
    lus: set[str] = set()

    def poser(nom: str, valeur: Any) -> None:
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            if math.isfinite(float(valeur)):
                axes[nom] = float(valeur)
                lus.add(nom)

    # pluie : plate ou imbriquée
    poser("pluie_mm", candidate.get("pluie_mm", meteo.get("pluie_cumulee_mm")))
    poser("demi_tours", candidate.get("demi_tours", placement.get("demi_tours")))
    # Densité : la clé publiée par le lot d'abord, puis une recherche en
    # profondeur — L5.4 réécrit `sortie/commande.py` en ce moment, et une
    # densité qui déménagerait sous `placement` ne doit pas rendre l'axe muet.
    poser("densite_marqueurs_km", candidate.get("densite_marqueurs_km"))
    if "densite_marqueurs_km" not in lus:
        for nom in ("densite", "marqueur"):
            valeurs = [
                v
                for v in _profond(candidate, nom)
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]
            if valeurs:
                poser("densite_marqueurs_km", valeurs[0])
                break
    poser("part_trafic", candidate.get("part_trafic"))
    poser("note_terrain", candidate.get("note_terrain", placement.get("note_terrain")))
    # `part_connue` est lue pour être **surveillée**, jamais pour contraster :
    # voir `AXE_INTERDIT`. Elle est rangée à part, hors du dictionnaire d'axes.

    # Durée : le lot publie `duree_s` à plat, le sprint 4 `placement.duree_totale_s`.
    # On garde l'**écart à la séance** quand on la connaît — même ordre que la
    # durée brute tant que les propositions dépassent toutes, et plus lisible
    # dans un message d'échec.
    duree = candidate.get("duree_s", placement.get("duree_totale_s"))
    if isinstance(duree, (int, float)) and "duree_s" in seance:
        poser("depassement_s", float(duree) - float(seance["duree_s"]))
    else:
        poser("depassement_s", duree)

    orientation = candidate.get("orientation_vent") or candidate.get("orientation")
    if isinstance(orientation, str) and orientation:
        lus.add("orientation")
        # Les trois axes de vent sont dérivés de l'orientation nommée : c'est
        # elle que le lot publie, et elle est plus sûre qu'une part de face
        # moyenne dont le signe se perd.
        axes["vent_dos_retour"] = 1.0 if orientation == "retour-dos" else 0.0
        axes["vent_dos_depart"] = 1.0 if orientation == "depart-dos" else 0.0
        axes["vent_travers"] = 1.0 if orientation == "travers" else 0.0
        lus |= {"vent_dos_retour", "vent_dos_depart", "vent_travers"}
    elif "part_vent_face" in meteo:
        poser("vent_travers", 1.0 - float(meteo["part_vent_face"]))

    recouvrements = candidate.get("recouvrement_max_avec") or {}
    valeurs_r = [
        float(v)
        for v in (recouvrements.values() if isinstance(recouvrements, dict) else [])
        if isinstance(v, (int, float)) and math.isfinite(float(v))
    ]
    part_connue = candidate.get("part_connue")

    return VueProposition(
        cle=cle if cle is not None else candidate.get("numero", candidate.get("nom")),
        axes=axes,
        note_totale=float(placement.get("note_totale", candidate.get("note_terrain", 0.0)) or 0.0),
        phrase=phrase_de(candidate),
        orientation=orientation if isinstance(orientation, str) else None,
        axes_lus=frozenset(lus),
        recouvrement_max=max(valeurs_r) if valeurs_r else None,
        part_connue=float(part_connue) if isinstance(part_connue, (int, float)) else None,
    )


def exiger_axes_lus(vues: Sequence[VueProposition]) -> None:
    """Refuse de conclure quand l'adaptateur n'a lu aucun axe.

    Sans cette garde, un changement de forme du JSON transforme tous les
    vérificateurs en générateurs de faux positifs : ils comparent des vues
    neutres, donc identiques, et concluent « trois clones ». Mieux vaut
    échouer en disant « je ne sais pas lire » que rendre un verdict faux.
    """
    muettes = [v.cle for v in vues if not v.axes_lus]
    assert not muettes, (
        f"aucun axe lu pour les propositions {muettes} : l'adaptateur JSON ne reconnaît plus "
        "la forme publiée. Les vérificateurs compareraient des valeurs neutres, donc "
        "identiques, et crieraient « trois clones » à tort. Corriger `vue_depuis_json` avant "
        "de conclure quoi que ce soit."
    )


def choix_depuis_json(doc: dict) -> VueChoix:
    """Le `VueChoix` correspondant à ce que la commande a proposé.

    `contraste_affirme` est vrai dès que le lot publie plusieurs propositions
    **sans rien dire** d'une impossibilité : publier trois cartes côte à côte,
    c'est affirmer qu'elles valent la peine d'être comparées. Le motif se
    cherche partout dans le document, sous n'importe quel nom — on ne devine
    pas la clé, on cherche le mot.

    `equivalence_dite` cherche de la même façon l'aveu de Q45 : le lot annonce
    que ses propositions **se valent**, et qu'aucune ne se détache. C'est le
    contraire d'un aveu d'échec, mais ça se lit au même endroit.
    """
    proposees = propositions_du_json(doc)
    vues = [vue_depuis_json(c, doc, cle=i) for i, c in enumerate(proposees)]
    motifs: list[str] = []
    for jeton in ("motif", "contraste", "avertissement", "note_de_lecture", "message"):
        motifs += [v for v in _profond(doc, jeton) if isinstance(v, str) and v.strip()]
    texte = " ".join(motifs)
    plat = _sans_accents_bas(texte)
    aveu = any(
        m in plat
        for m in ("se ressemblent", "pas contrast", "peu contrast", "non contrast", "indiscernab")
    )
    equivalence = any(m in plat for m in ("se valent", "se valaient", "ne se detache"))
    return VueChoix(
        retenues=vues,
        contraste_affirme=not aveu and len(vues) > 1,
        equivalence_dite=equivalence,
        motif=texte,
        pool=vues,
    )


# --- découverte des points d'entrée non nommés par le contrat -----------------


def modules_ourouler() -> list[Any]:
    """Tous les modules importables du paquet, pour y chercher un point d'entrée."""
    import importlib
    import pkgutil

    import ourouler

    trouves = []
    for info in pkgutil.walk_packages(ourouler.__path__, prefix="ourouler."):
        try:
            trouves.append(importlib.import_module(info.name))
        except Exception:  # noqa: BLE001 - un module qui ne s'importe pas n'est pas le nôtre
            continue
    return trouves


def decouvrir_callable(
    motifs: Sequence[Sequence[str]], *, quoi: str, fonctions_seules: bool = True
) -> Any | None:
    """Le premier appelable public dont **le nom ou celui de son module** correspond.

    `motifs` est une liste de conjonctions : `[("densite",), ("marqueur", "km")]`
    accepte `densite_marqueurs` comme `marqueurs_par_km`.

    Deux corrections apportées à la réconciliation, et elles disent la même
    chose : ma recherche était trop étroite d'un côté, trop large de l'autre.

    * **Le module compte autant que la fonction.** Le lot a écrit
      `boucle.marqueurs.compter` : un nom de fonction parfaitement clair *dans
      son module*, que chercher « densite » ou « marqueur » dans le seul nom de
      fonction ne trouvait pas. On concatène donc les deux.
    * **Une dataclasse n'est pas un point d'entrée.** La recherche rendait
      `QuestionVent`, la structure de résultat, au lieu de `interroger`, la
      fonction qui décide — et l'inspection de signature partait sur les champs
      de la structure. `fonctions_seules` écarte les classes.
    """
    import dataclasses
    import inspect

    for module in modules_ourouler():
        court = module.__name__.rsplit(".", 1)[-1]
        for nom in sorted(vars(module)):
            if nom.startswith("_"):
                continue
            objet = getattr(module, nom)
            if not callable(objet) or getattr(objet, "__module__", "") != module.__name__:
                continue
            if fonctions_seules and (
                inspect.isclass(objet) or dataclasses.is_dataclass(objet)
            ):
                continue
            plat = _sans_accents_bas(f"{court} {nom}")
            if any(all(mot in plat for mot in motif) for motif in motifs):
                return objet
    return None


MOTIFS_DENSITE = (
    ("marqueur", "compter"),
    ("densite", "marqueur"),
    ("densite", "km"),
    ("marqueur", "km"),
    ("densite",),
)
MOTIFS_QUESTION_VENT = (
    ("vent", "interroger"),
    ("vent", "demande"),
    ("question", "vent"),
    ("orientation", "vent", "demand"),
    ("demander", "vent"),
    ("poser", "vent"),
)

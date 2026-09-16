"""Fabriques du lot L5.3 — trois propositions contrastées (contrat sprint 5 §3.3).

Écrit **en aveugle** de l'implémentation : ces fabriques ne connaissent du lot
que ce que le contrat promet, et du code que ce qui existait sur `sprint-5`
avant lui (`sortie/commande.py`, `boucle/candidates.py`, `seance/terrain.py`,
`apprentissage/routes.py`).

## Pourquoi ce fichier est aussi gros

Le contrat §3.3 ne nomme **aucune interface** : ni module, ni fonction, ni
champ. Il décrit un comportement (« trois représentants éloignés », « une
phrase par proposition », « deux gardes sur la question du vent », « une
densité de marqueurs au kilomètre ») sans dire par quelle porte on y entre.
Deux conséquences, et elles structurent tout le dossier.

1. **Les vérificateurs sont écrits contre une vue générique**
   (`VueProposition`, `VueChoix`), pas contre l'implémentation. Un adaptateur
   (`decouvrir_*`) va chercher la vraie porte au moment du test et échoue avec
   un message qui dit ce qu'il a cherché. Rien n'est deviné en silence.
2. **Une implémentation de référence** (`choisir_reference`,
   `densite_reference`, `question_vent_reference`) sert de cobaye : elle est
   mutée dix-huit fois dans `test_adv_l53_autocontrole.py`, et chaque mutation
   doit être attrapée par un vérificateur nommé. C'est la discipline du lot
   L5.2, où deux tests s'étaient révélés aveugles à la mutation qu'ils
   annonçaient. Elle ne remplace pas les tests sur le vrai code : elle prouve
   que les vérificateurs ont des dents avant que le vrai code arrive.

## Ce que la référence n'est pas

Ce n'est **pas** une proposition d'implémentation, et surtout pas une norme :
le contrat ne fixe ni la distance entre deux propositions, ni le seuil à
partir duquel elles sont « éloignées », ni le seuil de vent. La référence
choisit la distance de Tchebychev et un seuil explicite parce qu'il faut bien
un cobaye qui tourne ; **aucun test sur le vrai code n'exige ces choix-là**.
Les tests du vrai code sont écrits pour être vrais quel que soit le seuil —
voir `test_adv_trois_propositions.py`, section « sans seuil ».

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
import fabriques4

from ourouler.boucle.trace import Trace

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
    "part_connue": "",
    "vent_dos_retour": "max",
    "vent_dos_depart": "max",
    "vent_travers": "max",
}

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
    #: trois clones en les annonçant contrastées est le défaut central du lot.
    contraste_affirme: bool = True
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
    "part_connue": 0.5,
    "vent_dos_retour": 0.5,
    "vent_dos_depart": 0.5,
    "vent_travers": 0.5,
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
            depassement_s=1800.0, densite_marqueurs_km=8.0, part_connue=0.9,
            vent_dos_retour=0.2)
        for k in range(3)
    ]
    seche = vue(
        "seche", note=3.0, pluie_mm=0.0, demi_tours=0, depassement_s=120.0,
        densite_marqueurs_km=0.5, part_connue=0.1, vent_dos_retour=0.9,
    )
    ventee = vue(
        "ventee", note=3.1, pluie_mm=9.0, demi_tours=0, depassement_s=2400.0,
        densite_marqueurs_km=0.6, part_connue=0.2, vent_dos_retour=0.95,
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
    return [
        vue(i, note=notes[i], densite_marqueurs_km=densites[i], part_connue=connues[i],
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
    ("part_connue", "max"): "des routes que vous connaissez",
    ("part_connue", "min"): "des routes nouvelles pour vous",
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
                if AXES[nom] and AXES[nom] != sens and nom != "part_connue":
                    pass  # les deux sens restent dicibles ; `sens` n'est qu'une tournure
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
    """Une tournure reconnaissable, et l'axe sur lequel elle engage le lot."""

    nom: str
    motifs: tuple[str, ...]
    axe: str
    sens: str  # "min", "max" ou "zero"


#: Le lexique est délibérément celui du contrat §3.3.3, qui donne les phrases en
#: exemple : « vous rentrez avec le vent dans le dos », « aucun demi-tour »,
#: « la plus sèche », « 20 minutes de moins », « elle évite les villages ».
#: L'ordre compte : la tournure la plus spécifique est reconnue d'abord.
AFFIRMATIONS: tuple[Affirmation, ...] = (
    Affirmation("vent_dos_depart", ("vent dans le dos au départ", "vent dans le dos au depart",
                                    "vous partez avec le vent"), "vent_dos_depart", "max"),
    Affirmation("vent_dos_retour", ("rentrez avec le vent dans le dos", "vent dans le dos au retour",
                                    "vent dans le dos à la fin", "vent dans le dos a la fin",
                                    "vent dans le dos pour rentrer"), "vent_dos_retour", "max"),
    Affirmation("vent_travers", ("vent de travers", "vent latéral", "vent lateral"),
                "vent_travers", "max"),
    Affirmation("demi_tour", ("aucun demi-tour", "sans demi-tour", "pas de demi-tour"),
                "demi_tours", "zero"),
    Affirmation("pluie", ("la plus sèche", "la plus seche", "au sec", "sans pluie", "moins de pluie"),
                "pluie_mm", "min"),
    Affirmation("duree", ("minutes de moins", "la plus courte", "plus courte", "moins longue",
                          "la plus proche de la séance", "tient la durée", "tient la duree"),
                "depassement_s", "min"),
    Affirmation("ville", ("évite les villages", "evite les villages", "évite les bourgs",
                          "evite les bourgs", "évite la ville", "evite la ville",
                          "sans traverser", "moins de feux", "la plus calme"),
                "densite_marqueurs_km", "min"),
    Affirmation("connues", ("que vous connaissez", "routes connues", "déjà roulé", "deja roule"),
                "part_connue", "max"),
    Affirmation("nouvelles", ("routes nouvelles", "nouvelles pour vous", "que vous ne connaissez pas",
                              "inédit", "inedit"), "part_connue", "min"),
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


def verifier_pas_de_trio_de_clones(choix: VueChoix) -> None:
    """Le cœur du lot : trois propositions indiscernables ne sont pas trois propositions.

    Formulation **sans seuil** — le contrat ne chiffre pas « éloignées », donc
    on n'exige rien de chiffré : deux retenues dont *tous* les axes perceptibles
    sont égaux au bit près sont, par toute lecture du contrat, la même sortie
    vue deux fois. Si le lot en rend deux pareilles, il n'a pas le droit
    d'affirmer qu'elles sont contrastées.
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
    assert not choix.contraste_affirme, (
        f"propositions identiques sur tous les axes perceptibles : {jumelles}, et le lot "
        "les annonce contrastées. Contrat §3.3.1 : « deux propositions ne sont contrastées "
        "que si elles diffèrent sur quelque chose que le cycliste voit ou sent ». "
        "Contrat §3.3.3 : « il vaut mieux n'en proposer que deux et le dire »."
    )
    assert choix.motif.strip(), (
        f"le lot rend des propositions jumelles ({jumelles}) sans affirmer le contraste, "
        "mais sans rien dire non plus. Le contrat demande de **le dire**."
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
    """Une phrase par proposition : non vide, unique, en langage de cycliste."""
    if len(choix.retenues) < 2:
        return
    for p in choix.retenues:
        assert p.phrase is not None, f"candidate {p.cle!r} : aucune phrase (contrat §3.3.3)"
        assert p.phrase.strip(), (
            f"candidate {p.cle!r} : phrase vide. Le contrat : « chaque proposition porte une "
            "phrase qui dit ce qui la distingue des deux autres » — et si aucune phrase n'est "
            "écrivable, il faut en rendre moins, pas en rendre une vide."
        )
        assert not phrase_est_en_langage_de_note(p.phrase), (
            f"candidate {p.cle!r} : « {p.phrase} » est du langage de note. Le contrat demande "
            "du langage de cycliste : « la plus sèche », « aucun demi-tour », « 20 minutes de "
            "moins » — jamais « note 1,93 »."
        )
    phrases = [_sans_accents_bas(p.phrase or "").strip() for p in choix.retenues]
    assert len(set(phrases)) == len(phrases), (
        f"deux propositions reçoivent la même phrase : {phrases}. Une phrase qui dit ce qui "
        "distingue une proposition **des deux autres** ne peut pas être partagée."
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
        "de `fabriques_l53.AFFIRMATIONS` — dans ce second cas, c'est le lexique qu'il faut "
        "étendre, et cela se décide avec le mainteneur, pas en silence."
    )


# --- densité de marqueurs -----------------------------------------------------

#: Les marqueurs que le contrat §3.3.2 nomme : « feux, passages piétons,
#: ralentisseurs » — c'est-à-dire ce que `terrain._noeuds_tagues` sait déjà
#: reconnaître. On réutilise ses constantes plutôt que d'en réécrire une
#: seconde liste qui divergerait.
def marqueurs_du_projet() -> tuple[frozenset[str], str, frozenset[str]]:
    from ourouler.seance.terrain import (
        CLE_RALENTISSEUR,
        NOEUDS_CARREFOUR,
        RALENTISSEURS_SANS_EFFET,
    )

    return (NOEUDS_CARREFOUR, CLE_RALENTISSEUR, RALENTISSEURS_SANS_EFFET)


def compter_marqueurs(trace: Trace, debut_m: float, longueur_m: float) -> int:
    """Le nombre de nœuds tagués dont la position tombe dans la portion."""
    carrefour, cle_calme, sans_effet = marqueurs_du_projet()
    fin_m = debut_m + longueur_m
    total = 0
    for segment in trace.segments:
        if segment.fin_idx >= len(trace.points):
            continue
        position = trace.points[segment.fin_idx].dist_m
        if not (debut_m <= position <= fin_m):
            continue
        if segment.node_tags.get("highway", "") in carrefour:
            total += 1
            continue
        calme = segment.node_tags.get(cle_calme, "")
        if calme and calme not in sans_effet:
            total += 1
    return total


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


def densite_reference(trace: Trace, debut_m: float = 0.0, longueur_m: float | None = None) -> Densite:
    """Le cobaye : nombre de marqueurs divisé par les kilomètres de la portion."""
    if longueur_m is None:
        longueur_m = trace.points[-1].dist_m if len(trace.points) >= 2 else 0.0
    if not trace.segments:
        return Densite(0.0, connue=False, motif="routes inconnues")
    if not math.isfinite(longueur_m) or longueur_m <= 0:
        return Densite(0.0, connue=False, motif="portion de longueur nulle")
    if not math.isfinite(debut_m):
        return Densite(0.0, connue=False, motif="position illisible")
    return Densite(compter_marqueurs(trace, debut_m, longueur_m) / (longueur_m / 1000.0), True)


def verifier_densite(
    fn: Callable[..., Any], *, lire: Callable[[Any], Densite] | None = None
) -> None:
    """La batterie de la densité : le contrat §3.3.2 et l'invariant du sprint 3.

    `fn(trace, debut_m, longueur_m)` rend n'importe quoi que `lire` sait
    convertir en `Densite`. Six exigences, chacune dans son assertion.
    """
    lire = lire or (lambda v: v)

    #: 10 marqueurs sur 5 km : la densité vaut 2 /km, pas 10, pas 0,002.
    coords = fabriques4.droite(200, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0)
    noeuds = {i: {"highway": "traffic_signals"} for i in range(20, 70, 5)}
    trace = fabriques4.trace_taguee(coords, tags={"highway": "tertiary"}, node_tags=noeuds)
    d = lire(fn(trace, 2000.0, 5000.0))
    assert d.connue, "une portion dont les tronçons sont tagués est une portion connue"
    assert d.par_km == pytest_approx(2.0), (
        f"10 marqueurs sur 5 km font 2,0 /km, pas {d.par_km!r}. Un compte brut rendrait 10 ; "
        "une division par les mètres rendrait 0,002."
    )

    #: Longueur nulle : pas de division par zéro, pas de NaN, pas d'infini.
    d = lire(fn(trace, 2000.0, 0.0))
    assert math.isfinite(d.par_km), f"longueur nulle : densité {d.par_km!r} (division par zéro ?)"
    assert not d.connue, "une portion de longueur nulle ne porte aucune densité connue"

    #: Longueur négative, et plus courte qu'un pas de 100 m.
    for longueur in (-500.0, 1e-9, float("nan")):
        d = lire(fn(trace, 2000.0, longueur))
        assert math.isfinite(d.par_km), f"longueur {longueur!r} : densité {d.par_km!r}"

    #: Tracé sans **aucun** segment : « on ne sait pas », jamais « la campagne ».
    nu = fabriques4.trace_taguee(coords, tags={"highway": "tertiary"}, sans_segments=True)
    d_nu = lire(fn(nu, 2000.0, 5000.0))
    assert not d_nu.connue, (
        "un tracé sans segments rend une densité de zéro **connue** : c'est « la campagne "
        "prouvée » là où il n'y a que « on ne sait pas ». Le contrat du sprint 3 interdit "
        "qu'une classe inconnue devienne un malus ; ici l'erreur est symétrique et pire, "
        "elle en fait un bonus."
    )

    #: Segments présents mais aucun marqueur : là, zéro est une **mesure**.
    vide = fabriques4.trace_taguee(coords, tags={"highway": "tertiary"}, node_tags={})
    d_vide = lire(fn(vide, 2000.0, 5000.0))
    assert d_vide.connue and d_vide.par_km == pytest_approx(0.0), (
        f"des tronçons tagués sans marqueur, c'est une densité nulle **connue** : {d_vide!r}"
    )

    #: Tous les nœuds au même endroit : rien ne doit exploser.
    empiles = fabriques4.trace_taguee(
        coords,
        tags={"highway": "tertiary"},
        node_tags={30: {"highway": "traffic_signals"}, 31: {"highway": "stop"}},
    )
    d_emp = lire(fn(empiles, 2900.0, 400.0))
    assert math.isfinite(d_emp.par_km) and d_emp.par_km >= 0, (
        f"nœuds empilés sur un court couloir : densité {d_emp.par_km!r}"
    )


def pytest_approx(valeur: float, *, rel: float = 1e-9, abs_: float = 1e-9):
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
    assert appel(jours_a_l_avance=0.0), "aujourd'hui : dans l'horizon"
    assert appel(jours_a_l_avance=float(HORIZON_JOURS)), (
        f"{HORIZON_JOURS} jours pile : le contrat dit « on ne propose une orientation au vent "
        "que **jusqu'à** 3 jours » et chiffre ce jour-là (88 % de bon secteur). La borne est "
        "donc incluse — si l'implémentation l'a lue exclusive, c'est une lecture du contrat à "
        "trancher avec le mainteneur, pas à deviner."
    )
    for au_dela in (HORIZON_JOURS + 0.01, 4.0, 5.0, 10.0):
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
        assert not appel(vent_kmh=absurde), f"vent {absurde!r} : une valeur non finie n'est pas un vent"
        assert not appel(direction_deg=absurde), f"direction {absurde!r} : idem"
    assert not appel(jours_a_l_avance=float("nan")), "horizon illisible : pas de question"


# --- géométries pour les tests sur le vrai code -------------------------------


def boucle_avec_marqueurs(n_marqueurs: int, *, rayon_m: float = 4000.0, n: int = 240) -> Trace:
    """Une boucle plate, `n_marqueurs` feux répartis régulièrement dessus."""
    pas = max(1, n // max(n_marqueurs, 1))
    noeuds = {i * pas: {"highway": "traffic_signals"} for i in range(n_marqueurs)}
    return fabriques4.boucle_plate(
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
    """Les candidates **proposées au cycliste**, c'est-à-dire celles qui portent une phrase.

    Sur `sprint-5`, `candidates` liste toutes les boucles évaluées et aucune ne
    porte de phrase : la fonction rend alors une liste vide, et la sentinelle
    échoue. Après le lot, elle rend les propositions contrastées, où qu'elles
    soient publiées.
    """
    listes: list[list] = []
    for cle in ("propositions", "candidates"):
        for valeur in _profond(doc, cle):
            if isinstance(valeur, list) and all(isinstance(e, dict) for e in valeur):
                listes.append(valeur)
    for liste in listes:
        avec_phrase = [c for c in liste if (phrase_de(c) or "").strip()]
        if avec_phrase:
            return avec_phrase
    return []


def vue_depuis_json(candidate: dict, doc: dict, *, cle: Any = None) -> VueProposition:
    """Une `VueProposition` bâtie sur ce que le JSON publie déjà.

    Les axes absents du JSON prennent leur valeur neutre : un axe que le lot ne
    publie pas ne peut ni contraster ni mentir, et c'est un test à part qui
    exige sa publication (`test_la_densite_de_marqueurs_est_publiee`).
    """
    placement = candidate.get("placement") or {}
    meteo = candidate.get("meteo") or {}
    seance = doc.get("seance") or {}
    axes = dict(NEUTRE)
    if "pluie_cumulee_mm" in meteo:
        axes["pluie_mm"] = float(meteo["pluie_cumulee_mm"])
    if "demi_tours" in placement:
        axes["demi_tours"] = float(placement["demi_tours"])
    if "duree_totale_s" in placement and "duree_s" in seance:
        axes["depassement_s"] = abs(float(placement["duree_totale_s"]) - float(seance["duree_s"]))
    if candidate.get("part_connue") is not None:
        axes["part_connue"] = float(candidate["part_connue"])
    if "part_vent_face" in meteo:
        # Faute de mieux tant que le lot ne publie pas la part de vent par
        # quart : la part de face globale, prise à l'envers, approche
        # « le vent est-il porteur ». Sert au contraste, jamais à juger une
        # phrase d'orientation — d'où l'absence de `vent_dos_retour` ici.
        axes["vent_travers"] = 1.0 - float(meteo["part_vent_face"])
    for nom in ("densite_marqueurs_km", "densite", "marqueurs_km", "marqueurs_par_km"):
        valeurs = [v for v in _profond(candidate, nom) if isinstance(v, (int, float))]
        if valeurs:
            axes["densite_marqueurs_km"] = float(valeurs[0])
            break
    return VueProposition(
        cle=cle if cle is not None else candidate.get("numero", candidate.get("nom")),
        axes=axes,
        note_totale=float((placement or {}).get("note_totale", 0.0)),
        phrase=phrase_de(candidate),
    )


def choix_depuis_json(doc: dict) -> VueChoix:
    """Le `VueChoix` correspondant à ce que la commande a proposé.

    `contraste_affirme` est vrai dès que le lot publie plusieurs propositions
    **sans rien dire** d'une impossibilité : publier trois cartes côte à côte,
    c'est affirmer qu'elles valent la peine d'être comparées. Le motif se
    cherche partout dans le document, sous n'importe quel nom — on ne devine
    pas la clé, on cherche le mot.
    """
    proposees = propositions_du_json(doc)
    vues = [vue_depuis_json(c, doc, cle=i) for i, c in enumerate(proposees)]
    motifs: list[str] = []
    for jeton in ("motif", "contraste", "avertissement", "note_de_lecture", "message"):
        motifs += [v for v in _profond(doc, jeton) if isinstance(v, str) and v.strip()]
    texte = " ".join(motifs)
    aveu = any(
        m in _sans_accents_bas(texte)
        for m in ("se ressemblent", "pas contrast", "peu contrast", "non contrast", "indiscernab")
    )
    return VueChoix(
        retenues=vues, contraste_affirme=not aveu and len(vues) > 1, motif=texte, pool=vues
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


def decouvrir_callable(motifs: Sequence[Sequence[str]], *, quoi: str) -> Any | None:
    """Le premier appelable public dont le nom contient tous les mots d'un motif.

    `motifs` est une liste de conjonctions : `[("densite",), ("marqueur", "km")]`
    accepte `densite_marqueurs` comme `marqueurs_par_km`. Rend `None` quand rien
    ne correspond — c'est à l'appelant de décider s'il saute ou s'il échoue.
    """
    for module in modules_ourouler():
        for nom in sorted(vars(module)):
            if nom.startswith("_"):
                continue
            objet = getattr(module, nom)
            if not callable(objet) or getattr(objet, "__module__", "") != module.__name__:
                continue
            plat = _sans_accents_bas(nom)
            if any(all(mot in plat for mot in motif) for motif in motifs):
                return objet
    return None


MOTIFS_DENSITE = (("densite", "marqueur"), ("densite", "km"), ("marqueur", "km"), ("densite",))
MOTIFS_QUESTION_VENT = (
    ("question", "vent"),
    ("orientation", "vent", "demand"),
    ("demander", "vent"),
    ("poser", "vent"),
    ("vent", "pertinent"),
)

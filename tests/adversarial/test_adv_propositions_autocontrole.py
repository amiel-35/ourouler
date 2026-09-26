"""Autocontrôle du lot L5.3 : les vérificateurs ont-ils des dents ?

**Ce fichier ne teste pas le lot.** Il teste `fabriques_propositions`, c'est-à-dire les
vérificateurs avec lesquels `test_adv_trois_propositions.py` jugera le lot. Il tournait
vert avant que le lot existe, et il doit le rester après : il ne dépend
d'aucune interface du lot, seulement de mes propres vérificateurs.

## Pourquoi il existe

Sur le lot L5.2, deux tests adversariaux annonçaient attraper une mutation
qu'ils n'attrapaient pas ; on ne l'a su qu'en écrivant une implémentation de
référence et en la mutant quatorze fois. La leçon est reprise ici et durcie :
`fabriques_propositions` porte un cobaye complet (`choisir_reference`,
`densite_reference`, `question_vent_reference`), et ce fichier le mute
**vingt-sept fois**. Chaque mutation est nommée, rattachée au vérificateur qui
doit la voir, et le test échoue si le vérificateur la laisse passer.

Un test qui passe du premier coup sur du code non trivial est suspect. Celui-ci
est conçu pour que la question ne se pose pas : la moitié de ses assertions
exigent qu'un appel **échoue**.

## Ce que l'autocontrôle ne prouve pas

Qu'un vérificateur attrape une mutation de la référence ne prouve pas qu'il
attrapera *toute* faute de l'implémentation réelle : la référence n'est pas
l'implémentation, et le contrat ne fixe pas d'interface (voir le docstring de
`fabriques_propositions`). Il prouve seulement que le vérificateur n'est pas creux —
ce qui est exactement ce qui avait manqué au lot précédent.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import fabriques_propositions as f53
import fabriques_seance
import pytest

from ourouler.noyau.trace import Trace

# Ce que le vérificateur a le droit de lever quand il attrape quelque chose :
# une assertion, ou l'exception que la mutation elle-même provoque.
ATTRAPE = (AssertionError, ZeroDivisionError, ValueError, TypeError)


def _attrape(verificateur: Callable[[], Any], *, quoi: str) -> None:
    """`verificateur` doit refuser. S'il accepte, c'est lui qui est en cause."""
    try:
        verificateur()
    except ATTRAPE:
        return
    pytest.fail(
        f"mutation « {quoi} » non attrapée : le vérificateur l'a acceptée. C'est le "
        "vérificateur qu'il faut corriger, pas la mutation."
    )


# =============================================================================
# 0. La référence elle-même passe tous les vérificateurs
# =============================================================================


@pytest.mark.parametrize(
    "vivier",
    [
        pytest.param(f53.vivier_contrastable(), id="contrastable"),
        pytest.param(f53.vivier_clones(5), id="clones"),
        pytest.param(f53.vivier_clones(5, notes_distinctes=False), id="clones-notes-egales"),
        pytest.param(f53.vivier_deux_familles(), id="deux-familles"),
        pytest.param(f53.vivier_sans_bloc(), id="sans-bloc"),
        pytest.param([], id="vide"),
        pytest.param(f53.vivier_clones(1), id="une-seule"),
    ],
)
def test_la_reference_passe_les_verificateurs(vivier):
    """Un contrôle positif : sans lui, un vérificateur toujours-vrai passerait aussi.

    Les viviers dégénérés sont dedans : le vivier vide, la candidate unique, et
    surtout `clones-notes-egales`, où **tous** les scores sont égaux — le cas
    de la séance sans bloc, celui où une normalisation min-max écrite sans
    garde divise par zéro.
    """
    choix = f53.choisir_reference(vivier)
    f53.verifier_retenues_bien_formees(choix)
    f53.verifier_pas_de_trio_de_clones(choix)
    f53.verifier_phrases(choix)
    f53.verifier_phrases_vraies(choix)


def test_la_reference_va_chercher_les_extremes():
    """Contrôle positif du vérificateur d'étalement, sur le vivier fait pour ça."""
    choix = f53.choisir_reference(f53.vivier_contrastable())
    assert len(choix.retenues) == 3, f"trois attendues, {len(choix.retenues)} rendues"
    f53.verifier_plus_etale_que_le_tri(choix)


def test_la_reference_n_en_rend_que_deux_sur_deux_familles():
    """Le chemin « on n'en propose que deux et on le dit » n'est pas théorique."""
    choix = f53.choisir_reference(f53.vivier_deux_familles())
    assert len(choix.retenues) == 2, (
        f"deux grappes de clones : au plus deux représentants, {len(choix.retenues)} rendus"
    )
    assert choix.motif.strip(), "et il faut le dire"


def test_la_reference_sur_des_clones_ne_pretend_pas_au_contraste():
    choix = f53.choisir_reference(f53.vivier_clones(5))
    assert len(choix.retenues) == 1, (
        f"cinq candidates indiscernables : une seule proposition honnête, "
        f"{len(choix.retenues)} rendues"
    )


def test_la_reference_de_densite_passe_sa_batterie():
    f53.verifier_densite(f53.densite_reference)


@pytest.mark.parametrize("seuil", [2.6, 5.0, 8.0, 13.9, 40.0])
def test_la_reference_de_question_vent_passe_ses_gardes(seuil):
    """Le vérificateur ne doit dépendre d'aucune valeur de seuil particulière.

    Les seuils balayés sont tous **au-dessus de 2,5 km/h**, seule valeur que le
    contrat §3.3.4 place explicitement sous le seuil, et tous au plus égaux à
    45 km/h, borne haute du balayage. Un seuil de 1 km/h fait légitimement
    échouer le vérificateur : il contredirait le contrat.
    """
    f53.verifier_gardes_vent(
        lambda **kw: f53.question_vent_reference(seuil_kmh=seuil, **kw)
    )


# =============================================================================
# 1. Mutations du choix des représentants (10)
# =============================================================================


def _phrases(retenues, pool):
    return f53.ecrire_phrases_reference(retenues, f53.etendues(pool))


def m01_trois_premieres(pool) -> f53.VueChoix:
    """La faute que le lot existe pour éviter : le sommet d'un tri unique."""
    tete = f53.tri_primaire(pool)[:3]
    return f53.VueChoix(retenues=_phrases(tete, pool), contraste_affirme=True, pool=list(pool))


def m02_toujours_trois(pool) -> f53.VueChoix:
    """Trois quoi qu'il arrive, contraste affirmé sans l'avoir vérifié."""
    trois = list(pool)[:3]
    return f53.VueChoix(
        retenues=[replace(p, phrase=f"proposition {i + 1}") for i, p in enumerate(trois)],
        contraste_affirme=True,
        pool=list(pool),
    )


def m03_normalisation_sans_garde(pool) -> f53.VueChoix:
    """Min-max sans garde : `ZeroDivisionError` quand un axe est dégénéré."""
    portees = f53.etendues(pool)
    a, b = pool[0], pool[1]
    # Reproduit la faute exacte : on divise par l'étendue sans la tester.
    max(abs(a.axe(n) - b.axe(n)) / portees[n] for n in f53.AXES)
    return f53.choisir_reference(pool)


def m04_distance_sur_la_note(pool) -> f53.VueChoix:
    """Contraste mesuré sur la note — ce que le contrat §3.3.1 exclut (« Pas la note »)."""
    classees = f53.tri_primaire(pool)
    retenues = [classees[0]]
    restantes = list(classees[1:])
    while len(retenues) < 3 and restantes:
        meilleure = max(
            restantes, key=lambda c: min(abs(c.note_totale - r.note_totale) for r in retenues)
        )
        retenues.append(meilleure)
        restantes = [p for p in restantes if p.cle != meilleure.cle]
    return f53.VueChoix(retenues=_phrases(retenues, pool), contraste_affirme=True, pool=list(pool))


def m05_doublon(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(f53.vivier_contrastable())
    p = choix.retenues[0]
    return replace(choix, retenues=[p, replace(p, phrase="la plus sèche"), choix.retenues[1]])


def m06_hors_vivier(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(pool)
    intruse = f53.vue("venue-d-ailleurs", phrase="aucun demi-tour", demi_tours=0)
    return replace(choix, retenues=[*choix.retenues, intruse])


def m07_quatre_propositions(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(pool)
    supplement = [p for p in pool if all(p.cle != r.cle for r in choix.retenues)]
    return replace(choix, retenues=[*choix.retenues, *supplement[:1]])


def m08_silence_sur_la_troncature(pool) -> f53.VueChoix:
    """Deux propositions jumelles, aucun contraste affirmé — mais rien de dit non plus."""
    jumelles = list(pool)[:2]
    return f53.VueChoix(
        retenues=[replace(p, phrase=f"option {i}") for i, p in enumerate(jumelles)],
        contraste_affirme=False,
        motif="",
        pool=list(pool),
    )


def m09_deux_clones_annonces_contrastes(pool) -> f53.VueChoix:
    jumelles = list(pool)[:2]
    return f53.VueChoix(
        retenues=[
            replace(jumelles[0], phrase="la plus sèche"),
            replace(jumelles[1], phrase="aucun demi-tour"),
        ],
        contraste_affirme=True,
        pool=list(pool),
    )


def m10_vivier_ignore(pool) -> f53.VueChoix:
    """Le lot fabrique ses propositions au lieu de choisir parmi les candidates."""
    inventees = [f53.vue(f"inventée {i}", phrase=p) for i, p in enumerate(
        ("la plus sèche", "aucun demi-tour", "elle évite les villages")
    )]
    return f53.VueChoix(retenues=inventees, contraste_affirme=True, pool=list(pool))


MUTATIONS_CHOIX: tuple[tuple[str, Callable, Any, Callable], ...] = (
    ("m01 : les trois premières du tri", m01_trois_premieres,
     f53.vivier_contrastable(), f53.verifier_plus_etale_que_le_tri),
    ("m01bis : les trois premières du tri (ce sont des clones)", m01_trois_premieres,
     f53.vivier_contrastable(), f53.verifier_pas_de_trio_de_clones),
    ("m02 : trois quoi qu'il arrive", m02_toujours_trois,
     f53.vivier_clones(5), f53.verifier_pas_de_trio_de_clones),
    ("m03 : min-max sans garde d'étendue nulle", m03_normalisation_sans_garde,
     f53.vivier_clones(5, notes_distinctes=False), f53.verifier_pas_de_trio_de_clones),
    ("m04 : contraste mesuré sur la note", m04_distance_sur_la_note,
     f53.vivier_clones(5), f53.verifier_pas_de_trio_de_clones),
    ("m05 : la même candidate deux fois", m05_doublon,
     f53.vivier_contrastable(), f53.verifier_retenues_bien_formees),
    ("m06 : une proposition hors du vivier", m06_hors_vivier,
     f53.vivier_contrastable(), f53.verifier_retenues_bien_formees),
    ("m07 : quatre propositions", m07_quatre_propositions,
     f53.vivier_contrastable(), f53.verifier_retenues_bien_formees),
    ("m08 : troncature silencieuse", m08_silence_sur_la_troncature,
     f53.vivier_clones(5), f53.verifier_pas_de_trio_de_clones),
    ("m09 : deux clones annoncés contrastés", m09_deux_clones_annonces_contrastes,
     f53.vivier_clones(5), f53.verifier_pas_de_trio_de_clones),
    ("m10 : propositions inventées hors vivier", m10_vivier_ignore,
     f53.vivier_contrastable(), f53.verifier_retenues_bien_formees),
)


@pytest.mark.parametrize(
    ("quoi", "mutant", "vivier", "verificateur"),
    MUTATIONS_CHOIX,
    ids=[m[0].split(" :")[0] for m in MUTATIONS_CHOIX],
)
def test_mutation_du_choix_attrapee(quoi, mutant, vivier, verificateur):
    _attrape(lambda: verificateur(mutant(vivier)), quoi=quoi)


# =============================================================================
# 2. Mutations des phrases (6)
# =============================================================================


def m11_toutes_muettes_sans_le_dire(pool) -> f53.VueChoix:
    """Q45 : plusieurs propositions, pas une phrase, et pas un mot d'explication.

    Remplace « une phrase vide », qui gardait la règle retirée le 17/09/2026 :
    depuis Q43, une proposition sans phrase est une proposition dont le tracé
    parle seul, et c'est légitime. Ce qui ne l'est pas, c'est de les servir
    toutes muettes en laissant le cycliste chercher la différence.
    """
    choix = f53.choisir_reference(pool)
    return replace(
        choix,
        retenues=[replace(p, phrase="") for p in choix.retenues],
        equivalence_dite=False,
    )


def m12_phrases_identiques(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(pool)
    return replace(choix, retenues=[replace(p, phrase="la plus sèche") for p in choix.retenues])


def m13_phrase_en_langage_de_note(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(pool)
    return replace(
        choix,
        retenues=[
            replace(p, phrase=f"note {1.93 + 0.37 * i:.2f}".replace(".", ","))
            for i, p in enumerate(choix.retenues)
        ],
    )


def m14_phrase_sur_le_mauvais_axe(pool) -> f53.VueChoix:
    """« la plus sèche » collée à la plus arrosée : l'affirmation est fausse."""
    choix = f53.choisir_reference(pool)
    arrosee = max(choix.retenues, key=lambda p: p.axe("pluie_mm"))
    return replace(
        choix,
        retenues=[
            replace(p, phrase="la plus sèche") if p.cle == arrosee.cle else p
            for p in choix.retenues
        ],
    )


def m15_aucun_demi_tour_faux(pool) -> f53.VueChoix:
    choix = f53.choisir_reference(pool)
    avec = max(choix.retenues, key=lambda p: p.axe("demi_tours"))
    if avec.axe("demi_tours") <= 0:
        avec = replace(avec, axes={**avec.axes, "demi_tours": 2.0})
    return replace(
        choix,
        retenues=[
            replace(avec, phrase="aucun demi-tour") if p.cle == avec.cle else p
            for p in choix.retenues
        ],
    )


def m16_phrases_generiques(pool) -> f53.VueChoix:
    """Distinctes, non vides, sans langage de note — et pourtant elles ne disent rien."""
    choix = f53.choisir_reference(pool)
    return replace(
        choix,
        retenues=[
            replace(p, phrase=f"une belle sortie, option {i + 1}")
            for i, p in enumerate(choix.retenues)
        ],
    )


MUTATIONS_PHRASES: tuple[tuple[str, Callable, Any, Callable], ...] = (
    ("m11 : toutes muettes, sans dire qu'elles se valent", m11_toutes_muettes_sans_le_dire,
     f53.vivier_contrastable(), f53.verifier_phrases),
    ("m12 : la même phrase pour toutes", m12_phrases_identiques,
     f53.vivier_contrastable(), f53.verifier_phrases),
    ("m13 : « note 1,93 » au lieu du langage de cycliste", m13_phrase_en_langage_de_note,
     f53.vivier_contrastable(), f53.verifier_phrases),
    ("m14 : « la plus sèche » sur la plus arrosée", m14_phrase_sur_le_mauvais_axe,
     f53.vivier_contrastable(), f53.verifier_phrases_vraies),
    ("m15 : « aucun demi-tour » avec deux demi-tours", m15_aucun_demi_tour_faux,
     f53.vivier_contrastable(), f53.verifier_phrases_vraies),
)


@pytest.mark.parametrize(
    ("quoi", "mutant", "vivier", "verificateur"),
    MUTATIONS_PHRASES,
    ids=[m[0].split(" :")[0] for m in MUTATIONS_PHRASES],
)
def test_mutation_des_phrases_attrapee(quoi, mutant, vivier, verificateur):
    _attrape(lambda: verificateur(mutant(vivier)), quoi=quoi)


def test_mutation_phrase_generique_attrapee():
    """m16 : la seule mutation que seul `verifier_phrase_parle_du_bon_axe` voit.

    Écrite à part parce qu'elle a besoin d'un vivier à **un seul axe
    discriminant** : c'est la seule situation où l'on peut affirmer qu'une
    phrase qui ne parle pas de cet axe ne dit pas ce qui distingue.
    """
    vivier = f53.vivier_un_axe("pluie_mm", (0.0, 4.0, 9.0))
    mutant = m16_phrases_generiques(vivier)
    # Contrôle préalable : les vérificateurs plus généraux, eux, l'acceptent.
    f53.verifier_phrases(mutant)
    f53.verifier_phrases_vraies(mutant)
    _attrape(
        lambda: f53.verifier_phrase_parle_du_bon_axe(mutant, "pluie_mm", "min"),
        quoi="m16 : des phrases distinctes qui ne disent rien",
    )


@pytest.mark.parametrize("axe,extreme", [
    ("pluie_mm", "min"),
    ("demi_tours", "min"),
    ("depassement_s", "min"),
    ("densite_marqueurs_km", "min"),
    ("vent_dos_retour", "max"),
])
def test_la_reference_nomme_le_bon_axe(axe, extreme):
    """Contrôle positif de `verifier_phrase_parle_du_bon_axe`, axe par axe.

    Sans lui, un lexique qui ne reconnaîtrait rien ferait échouer le
    vérificateur sur *toute* implémentation, la bonne comprise.
    """
    valeurs = (0.0, 4.0, 9.0) if extreme == "min" else (0.9, 0.5, 0.1)
    vivier = f53.vivier_un_axe(axe, valeurs)
    choix = f53.choisir_reference(vivier)
    assert len(choix.retenues) >= 2, f"vivier à un axe : au moins deux représentants ({axe})"
    f53.verifier_phrase_parle_du_bon_axe(choix, axe, extreme)


# =============================================================================
# 3. Mutations de la densité de marqueurs (4)
# =============================================================================


def _km(trace: Trace) -> float:
    longueur = trace.distance_m
    if longueur is None or not math.isfinite(longueur) or longueur <= 0:
        longueur = trace.points[-1].dist_m if len(trace.points) >= 2 else 0.0
    return longueur / 1000.0


def m17_compte_brut(trace: Trace) -> f53.Densite:
    """Le nombre de marqueurs, pas leur densité : « au kilomètre » oublié."""
    if not trace.segments:
        return f53.Densite(0.0, connue=False)
    return f53.Densite(float(f53.compter_marqueurs(trace)), True)


def m18_par_metre(trace: Trace) -> f53.Densite:
    """Division par les mètres au lieu des kilomètres : facteur 1 000."""
    if not trace.segments or _km(trace) <= 0:
        return f53.Densite(0.0, connue=False)
    return f53.Densite(f53.compter_marqueurs(trace) / (_km(trace) * 1000.0), True)


def m19_inconnu_vaut_la_campagne(trace: Trace) -> f53.Densite:
    """Un tracé sans segments rend « zéro marqueur au km », **connu**."""
    km = _km(trace)
    if not math.isfinite(km) or km <= 0:
        return f53.Densite(0.0, connue=False)
    return f53.Densite(f53.compter_marqueurs(trace) / km, True)


def m20_division_sans_garde(trace: Trace) -> f53.Densite:
    """Aucune garde sur la longueur : division par zéro sur un tracé sans kilomètre."""
    if not trace.segments:
        return f53.Densite(0.0, connue=False)
    longueur = trace.distance_m
    return f53.Densite(f53.compter_marqueurs(trace) / (longueur / 1000.0), True)


def m27_noeud_compte_deux_fois(trace: Trace) -> f53.Densite:
    """Compté par tronçon et par tag, pas par nœud : un feu sur un plateau vaut deux.

    Mutation ajoutée à la réconciliation, après la fusion du lot : `boucle.marqueurs.nature_du_noeud`
    fait explicitement ce choix (« se compter deux fois serait pire que de se
    manquer »), et rien ne le surveillait.
    """
    if not trace.segments:
        return f53.Densite(0.0, connue=False)
    km = _km(trace)
    if km <= 0:
        return f53.Densite(0.0, connue=False)
    carrefour, cle_calme, sans_effet = f53.marqueurs_du_projet()
    total = 0
    for segment in trace.segments:
        if segment.node_tags.get("highway", "") in carrefour:
            total += 1
        calme = segment.node_tags.get(cle_calme, "")
        if calme and calme not in sans_effet:
            total += 1
    return f53.Densite(total / km, True)


MUTATIONS_DENSITE = (
    ("m17 : un compte brut, pas une densité", m17_compte_brut),
    ("m18 : divisé par les mètres", m18_par_metre),
    ("m19 : l'inconnu devient la campagne", m19_inconnu_vaut_la_campagne),
    ("m20 : division par une longueur nulle", m20_division_sans_garde),
    ("m27 : un nœud compté deux fois", m27_noeud_compte_deux_fois),
)


@pytest.mark.parametrize(
    ("quoi", "mutant"), MUTATIONS_DENSITE, ids=[m[0].split(" :")[0] for m in MUTATIONS_DENSITE]
)
def test_mutation_de_la_densite_attrapee(quoi, mutant):
    _attrape(lambda: f53.verifier_densite(mutant), quoi=quoi)


def test_le_compteur_de_marqueurs_voit_feux_et_ralentisseurs():
    """Contrôle positif du compteur : sinon toute la batterie compterait zéro partout.

    Le ralentisseur n'est pas un `highway` — il vit sous `traffic_calming`, et
    c'est précisément ce que la première rédaction de `terrain.py` ne voyait
    pas (commentaire de `CLE_RALENTISSEUR`). Les valeurs sans effet
    (`choker`, `island`, `dip`) ne comptent pas.
    """
    coords = fabriques_seance.droite(60, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0)
    trace = fabriques_seance.trace_taguee(
        coords,
        tags={"highway": "tertiary"},
        node_tags={
            5: {"highway": "traffic_signals"},
            10: {"highway": "crossing"},
            15: {"traffic_calming": "bump"},
            20: {"traffic_calming": "island"},  # sans effet : ne compte pas
            25: {"highway": "residential"},  # pas un nœud de carrefour
        },
    )
    assert f53.compter_marqueurs(trace) == 3, (
        "deux nœuds `highway` de carrefour et un ralentisseur effectif : trois marqueurs. "
        "Un compteur qui ignorerait `traffic_calming` en verrait deux ; un compteur qui "
        "ignorerait `RALENTISSEURS_SANS_EFFET` en verrait quatre."
    )


# =============================================================================
# 4. Mutations de la question du vent (5)
# =============================================================================


def m21_sans_seuil(**kw) -> bool:
    kw.pop("seuil_kmh", None)
    vent = kw.get("vent_kmh")
    if vent is None or not math.isfinite(vent):
        return False
    return f53.question_vent_reference(seuil_kmh=0.0, **kw)


def m22_sans_horizon(**kw) -> bool:
    kw.pop("seuil_kmh", None)
    kw["jours_a_l_avance"] = 0.0
    return f53.question_vent_reference(seuil_kmh=8.0, **kw)


def m23_horizon_strict(**kw) -> bool:
    """`< 3` au lieu de `<= 3` : trois jours pile devient muet."""
    kw.pop("seuil_kmh", None)
    if kw.get("jours_a_l_avance") is not None and not (
        kw["jours_a_l_avance"] < f53.HORIZON_JOURS
    ):
        return False
    return f53.question_vent_reference(seuil_kmh=8.0, **kw)


def m24_direction_ignoree(**kw) -> bool:
    kw.pop("seuil_kmh", None)
    kw["direction_deg"] = 250.0
    return f53.question_vent_reference(seuil_kmh=8.0, **kw)


def m25_seuil_en_intervalle(**kw) -> bool:
    """Un `if 3 <= vent <= 25` au lieu d'un seuil : deux bascules au lieu d'une."""
    kw.pop("seuil_kmh", None)
    vent = kw.get("vent_kmh")
    if vent is None or not math.isfinite(vent) or not (3.0 <= vent <= 25.0):
        return False
    return f53.question_vent_reference(seuil_kmh=0.0, **kw)


MUTATIONS_VENT = (
    ("m21 : aucun seuil de vent", m21_sans_seuil),
    ("m22 : aucun horizon", m22_sans_horizon),
    ("m23 : horizon strict, muet à 3 jours pile", m23_horizon_strict),
    ("m24 : direction inconnue ignorée", m24_direction_ignoree),
    ("m25 : un intervalle au lieu d'un seuil", m25_seuil_en_intervalle),
)


@pytest.mark.parametrize(
    ("quoi", "mutant"), MUTATIONS_VENT, ids=[m[0].split(" :")[0] for m in MUTATIONS_VENT]
)
def test_mutation_de_la_question_vent_attrapee(quoi, mutant):
    _attrape(lambda: f53.verifier_gardes_vent(mutant), quoi=quoi)


def m26_direction_non_finie_ignoree(**kw) -> bool:
    """`is None` sur la direction, sans `math.isfinite` : le défaut réel du lot."""
    kw.pop("seuil_kmh", None)
    direction = kw.get("direction_deg")
    if direction is not None and not math.isfinite(direction):
        kw["direction_deg"] = 250.0  # la garde ne le voit pas
    return f53.question_vent_reference(seuil_kmh=8.0, **kw)


def test_mutation_direction_non_finie_attrapee():
    """m26 : le vérificateur dédié doit voir passer un NaN de direction.

    C'est la mutation qui reproduit le défaut constaté sur `sprint-5` le
    16/09/2026. Elle est ici pour que le vérificateur qui l'attrape soit
    lui-même prouvé non creux — sans quoi le test rouge du lot ne vaudrait
    rien.
    """
    _attrape(
        lambda: f53.verifier_direction_non_finie(m26_direction_non_finie_ignoree),
        quoi="m26 : direction non finie acceptée",
    )


def test_la_reference_refuse_une_direction_non_finie():
    """Contrôle positif du même vérificateur."""
    f53.verifier_direction_non_finie(
        lambda **kw: f53.question_vent_reference(seuil_kmh=8.0, **kw)
    )


# =============================================================================
# 4 bis. Ce qui reste des marges après Q43 (5 mutations)
# =============================================================================
#
# Écrit le 16/09/2026, quand le contrat a chiffré « éloignées » : c'était le
# trou que j'avais signalé — « une implémentation rendant trois propositions
# séparées de 1 % serait passée ».
#
# **Refondu le 17/09/2026, après Q43.** Les marges ne décident plus qui entre
# dans le trio : le mainteneur a tranché que « le parcours lui-même est
# distinctif en soi », et le recouvrement de routes est devenu le seul verrou.
# Trois des cinq mutations d'alors gardaient très exactement cette règle
# retirée (m28 séparées de 1 %, m29 deux fois le même axe, m30 une proposition
# pour faire nombre) ; les garder aurait fait crier mon oracle sur un
# comportement que le produit doit maintenant avoir.
#
# Elles sont réécrites sur ce qui reste vrai, et qui n'est pas moins exigeant :
#
# - les marges gardent le **droit d'écrire une phrase** (m28, m29, m32) ;
# - le recouvrement porte seul le verrou, donc il doit mordre (m31) ;
# - et des propositions qui se valent doivent **le dire** (m30, Q45).

AXES_LUS_TOUS = frozenset(f53.AXES) | {"orientation"}


def _vue_mesuree(cle, *, orientation=None, recouvrement=None, phrase=None, **axes):
    """Une `VueProposition` dont tous les axes comptent pour lus."""
    base = f53.vue(cle, **axes)
    return replace(
        base,
        orientation=orientation,
        axes_lus=AXES_LUS_TOUS,
        recouvrement_max=recouvrement,
        phrase=phrase if phrase is not None else (base.phrase or ""),
    )


def _choix(vues, *, equivalence_dite=False) -> f53.VueChoix:
    return f53.VueChoix(
        retenues=list(vues),
        contraste_affirme=True,
        equivalence_dite=equivalence_dite,
        pool=list(vues),
    )


def test_trois_propositions_franchement_distinctes_passent_les_verrous():
    """Contrôle positif : sans lui, un vérificateur toujours-faux passerait aussi.

    Trois propositions séparées bien au-delà des marges du contrat, chacune
    avec la phrase qu'elle mérite : la plus sèche, la plus courte, celle sans
    demi-tour. Leurs tracés ne se recouvrent pas.
    """
    choix = _choix([
        _vue_mesuree("seche", pluie_mm=0.0, depassement_s=3000.0, demi_tours=2,
                     recouvrement=0.05, phrase="la plus sèche"),
        _vue_mesuree("courte", pluie_mm=6.0, depassement_s=0.0, demi_tours=2,
                     recouvrement=0.05, phrase="20 minutes de moins"),
        _vue_mesuree("directe", pluie_mm=6.0, depassement_s=3000.0, demi_tours=0,
                     recouvrement=0.05, phrase="aucun demi-tour"),
    ])
    f53.verifier_verrou_de_recouvrement(choix, seuil_recouvrement=0.25)
    f53.verifier_phrases_meritees(choix)
    f53.verifier_phrases(choix)
    f53.verifier_pas_de_trio_de_clones(choix, seuil_recouvrement=0.25)


def m28_phrase_gagnee_a_un_pourcent(_pool=None) -> f53.VueChoix:
    """« La plus sèche » pour 0,05 mm d'avance : exactement ce que le contrat refuse.

    La mutation d'avant ne portait aucune phrase et testait l'appartenance au
    trio ; celle-ci teste le droit d'écrire, qui est ce que les marges gardent.
    """
    return _choix([
        _vue_mesuree("a", pluie_mm=5.00, depassement_s=3000.0, recouvrement=0.05,
                     phrase="la plus sèche"),
        _vue_mesuree("b", pluie_mm=5.05, depassement_s=3030.0, recouvrement=0.05, phrase=""),
        _vue_mesuree("c", pluie_mm=5.10, depassement_s=3060.0, recouvrement=0.05, phrase=""),
    ])


def m29_deux_fois_la_phrase_de_la_pluie(_pool=None) -> f53.VueChoix:
    """Deux propositions se disent la plus sèche : au moins une des deux ment."""
    return _choix([
        _vue_mesuree("arrosee", pluie_mm=9.0, depassement_s=3000.0, demi_tours=1,
                     recouvrement=0.05, phrase=""),
        _vue_mesuree("seche1", pluie_mm=0.0, depassement_s=3000.0, demi_tours=1,
                     recouvrement=0.05, phrase="la plus sèche"),
        _vue_mesuree("seche2", pluie_mm=0.1, depassement_s=3000.0, demi_tours=1,
                     recouvrement=0.05, phrase="la plus sèche, elle aussi"),
    ])


def m30_des_clones_annonces_contrastes(_pool=None) -> f53.VueChoix:
    """Q45 : trois boucles égales sur tous les axes, servies comme si elles différaient.

    C'est le défaut que Q43 rend possible et que Q45 interdit : les tracés vont
    bien ailleurs (recouvrement 5 %), donc les publier est légitime — mais les
    publier **sans dire qu'elles se valent** laisse chercher une différence que
    le produit sait inexistante.
    """
    return _choix([
        _vue_mesuree("a", pluie_mm=3.0, depassement_s=1500.0, demi_tours=1, recouvrement=0.05),
        _vue_mesuree("b", pluie_mm=3.0, depassement_s=1500.0, demi_tours=1, recouvrement=0.05),
        _vue_mesuree("c", pluie_mm=3.0, depassement_s=1500.0, demi_tours=1, recouvrement=0.05),
    ])


def m31_recouvrement_au_dessus_du_seuil(_pool=None) -> f53.VueChoix:
    """Trois propositions bien distinctes sur le papier, mais les mêmes routes.

    Inchangée depuis le 16/09/2026, et c'est la seule des cinq dans ce cas :
    depuis Q43 elle garde le **seul** verrou du lot.
    """
    return _choix([
        _vue_mesuree("a", pluie_mm=0.0, depassement_s=3000.0, demi_tours=2, recouvrement=0.90),
        _vue_mesuree("b", pluie_mm=6.0, depassement_s=0.0, demi_tours=2, recouvrement=0.90),
        _vue_mesuree("c", pluie_mm=6.0, depassement_s=3000.0, demi_tours=0, recouvrement=0.85),
    ])


def m32_vent_de_la_meme_categorie(_pool=None) -> f53.VueChoix:
    """Deux propositions annoncées « vent » avec la **même** orientation.

    Deux fois « retour-dos » ne distingue rien, même si les phrases sont
    jolies : celle qui l'écrit affirme que le vent la sépare de l'autre, et
    c'est faux.
    """
    return _choix([
        _vue_mesuree("a", orientation="retour-dos", pluie_mm=3.0, depassement_s=1500.0,
                     recouvrement=0.05, phrase="vous rentrez avec le vent dans le dos"),
        _vue_mesuree("b", orientation="retour-dos", pluie_mm=3.0, depassement_s=1500.0,
                     recouvrement=0.05, phrase=""),
    ])


#: Le seuil de recouvrement se passe explicitement : ces vues sont fabriquées,
#: elles ne viennent pas d'une lecture du lot.
def _clones(choix):
    return f53.verifier_pas_de_trio_de_clones(choix, seuil_recouvrement=0.25)


def _recouvrement(choix):
    return f53.verifier_verrou_de_recouvrement(choix, seuil_recouvrement=0.25)


MUTATIONS_MARGES = (
    ("m28 : « la plus sèche » pour 0,05 mm d'avance", m28_phrase_gagnee_a_un_pourcent,
     f53.verifier_phrases_meritees),
    ("m29 : deux propositions se disent la plus sèche", m29_deux_fois_la_phrase_de_la_pluie,
     f53.verifier_phrases_meritees),
    ("m30 : des clones annoncés contrastés sans dire qu'ils se valent",
     m30_des_clones_annonces_contrastes, _clones),
    ("m31 : recouvrement de routes au-dessus du seuil", m31_recouvrement_au_dessus_du_seuil,
     _recouvrement),
    ("m32 : une phrase de vent sur deux propositions de même orientation",
     m32_vent_de_la_meme_categorie, f53.verifier_phrases_meritees),
)


@pytest.mark.parametrize(
    ("quoi", "mutant", "verificateur"),
    MUTATIONS_MARGES,
    ids=[m[0].split(" :")[0] for m in MUTATIONS_MARGES],
)
def test_mutation_des_marges_attrapee(quoi, mutant, verificateur):
    _attrape(lambda: verificateur(mutant()), quoi=quoi)


def test_des_clones_qui_disent_se_valoir_passent():
    """Contrôle négatif de m30 : le dire suffit, et c'est tout ce que Q45 demande."""
    f53.verifier_pas_de_trio_de_clones(
        replace(m30_des_clones_annonces_contrastes(), equivalence_dite=True),
        seuil_recouvrement=0.25,
    )


def test_des_clones_qui_partagent_leurs_routes_ne_passent_pas_meme_en_le_disant():
    """Le dire ne rachète pas tout : sans tracé distinct, rien ne les sépare.

    C'est la garde qui empêche Q45 de devenir un passe-droit — « elles se
    valent » resterait vrai, mais servir trois fois la même boucle n'est pas ce
    que le mainteneur a accepté.
    """
    clones = [
        replace(p, recouvrement_max=0.90) for p in m30_des_clones_annonces_contrastes().retenues
    ]
    _attrape(
        lambda: f53.verifier_pas_de_trio_de_clones(
            _choix(clones, equivalence_dite=True), seuil_recouvrement=0.25
        ),
        quoi="m30 bis : des clones sur les mêmes routes, annoncés équivalents",
    )


@pytest.mark.parametrize(
    ("nom", "valeur"),
    [("PAS_DUREE_S", 300.0), ("PAS_PLUIE_MM", 0.1), ("PAS_TERRAIN_KM_EQ", 0.2)],
)
def test_mutation_pas_relache_attrapee(nom, valeur):
    """m34 : un pas du lot plus étroit que celui du contrat §3.3.3 bis.

    « Être meilleur de 1 % n'est pas une différence pour un cycliste » : un pas
    de 5 min sur la durée, ou de 0,1 mm sur la pluie, rouvre exactement le trou
    que le contrat vient de fermer.
    """
    from types import SimpleNamespace

    cobaye = SimpleNamespace(PAS_DUREE_S=600.0, PAS_PLUIE_MM=0.5, PAS_TERRAIN_KM_EQ=1.0)
    setattr(cobaye, nom, valeur)
    _attrape(
        lambda: f53.verifier_pas_de_marge_relachee(cobaye),
        quoi=f"m34 : {nom} relâché à {valeur}",
    )


def test_des_pas_conformes_ou_plus_stricts_passent():
    """Contrôle négatif : un pas **plus large** est une exigence renforcée."""
    from types import SimpleNamespace

    f53.verifier_pas_de_marge_relachee(
        SimpleNamespace(PAS_DUREE_S=600.0, PAS_PLUIE_MM=0.5, PAS_TERRAIN_KM_EQ=1.0)
    )
    f53.verifier_pas_de_marge_relachee(
        SimpleNamespace(PAS_DUREE_S=900.0, PAS_PLUIE_MM=1.0, PAS_TERRAIN_KM_EQ=2.0)
    )


def test_les_marges_du_contrat_sont_celles_du_contrat():
    """Les chiffres de `MARGES_CONTRASTE` sont ceux que le §3.3.3 bis écrit.

    Figés ici pour qu'une relecture distraite ne puisse pas les assouplir sans
    que quelque chose crie : « durée ≥ 10 min ; pluie ≥ 0,5 mm ; terrain : au
    moins 1,0 km équivalent ».
    """
    assert f53.MARGES_CONTRASTE["depassement_s"] == 600.0, "durée ≥ 10 min"
    assert f53.MARGES_CONTRASTE["pluie_mm"] == 0.5, "pluie ≥ 0,5 mm"
    assert f53.MARGES_CONTRASTE["note_terrain"] == 1.0, "terrain ≥ 1,0 km équivalent"


# =============================================================================
# 4 ter. Les routes connues, gardées dans le bon sens (1 mutation)
# =============================================================================


def m33_phrase_sur_les_routes_connues(_pool=None) -> f53.VueChoix:
    """Une phrase qui distingue par les routes déjà roulées — ce que la doctrine refuse."""
    return _choix([
        replace(_vue_mesuree("a"), phrase="des routes que vous connaissez déjà"),
        replace(_vue_mesuree("b"), phrase="la plus sèche"),
    ])


def test_mutation_phrase_sur_les_routes_connues_attrapee():
    _attrape(
        lambda: f53.verifier_part_connue_hors_selection(m33_phrase_sur_les_routes_connues()),
        quoi="m33 : une phrase qui distingue par les routes connues",
    )


def test_une_phrase_ordinaire_passe_la_garde_des_routes_connues():
    """Contrôle négatif : la garde ne doit pas crier sur une phrase quelconque."""
    f53.verifier_part_connue_hors_selection(
        _choix([
            replace(_vue_mesuree("a"), phrase="la plus sèche"),
            replace(_vue_mesuree("b"), phrase="aucun demi-tour"),
        ])
    )


def test_part_connue_n_est_pas_un_axe_de_mes_fabriques():
    """Mes propres axes ne doivent pas porter ce que la doctrine interdit.

    Si `part_connue` restait dans `AXES`, mon détecteur de clones deviendrait
    **trop indulgent** : deux propositions identiques sur tout ce que le
    cycliste voit, ne différant que par la part de routes déjà roulées,
    passeraient pour contrastées.
    """
    assert f53.AXE_INTERDIT not in f53.AXES, (
        f"`{f53.AXE_INTERDIT}` est dans AXES : il n'est pas un axe de contraste "
        "(contrat §3.3.2, ligne rayée le 16/09/2026)"
    )
    assert f53.AXE_INTERDIT not in f53.NEUTRE
    assert not any(a.axe == f53.AXE_INTERDIT for a in f53.AFFIRMATIONS), (
        "aucune affirmation ne doit engager la part de routes connues"
    )


# =============================================================================
# 5. Le lexique des phrases lui-même
# =============================================================================


@pytest.mark.parametrize(
    ("phrase", "attendu"),
    [
        ("note 1,93", True),
        ("note de placement 2,30", True),
        ("score 4,72", True),
        ("pénalité de 0,29", True),
        ("la plus sèche", False),
        ("aucun demi-tour", False),
        ("20 minutes de moins", False),
        ("elle évite les villages", False),
        ("vous rentrez avec le vent dans le dos", False),
        ("4,2 km de routes à trafic", False),  # une décimale : une mesure, pas une note
        ("55,2 km pour 2 h", False),
    ],
)
def test_le_detecteur_de_langage_de_note(phrase, attendu):
    """Le détecteur doit séparer « note 1,93 » de « 4,2 km ». Sinon il crie à tort."""
    assert f53.phrase_est_en_langage_de_note(phrase) is attendu, (
        f"« {phrase} » : langage de note attendu {attendu}"
    )


@pytest.mark.parametrize(
    ("phrase", "axes_attendus"),
    [
        ("la plus sèche", {"pluie_mm"}),
        ("aucun demi-tour", {"demi_tours"}),
        ("vous rentrez avec le vent dans le dos", {"vent_dos_retour"}),
        ("vent dans le dos au départ", {"vent_dos_depart"}),
        ("vent de travers", {"vent_travers"}),
        ("elle évite les villages", {"densite_marqueurs_km"}),
        ("20 minutes de moins, la plus courte", {"depassement_s"}),
        # Les routes déjà roulées ne sont **pas** un axe : la tournure ne doit
        # donc rien engager. Voir `fabriques_propositions.AXE_INTERDIT`.
        ("des routes que vous connaissez", set()),
        ("une belle sortie", set()),
        ("retour au calme confortable", set()),
    ],
)
def test_le_lexique_reconnait_les_tournures_du_contrat(phrase, axes_attendus):
    """Les tournures reconnues sont celles que le contrat §3.3.3 donne en exemple.

    « retour au calme » ne doit pas être lu comme « la plus calme » : c'est le
    faux positif le plus probable, le retour au calme étant une étape de toutes
    les séances du mainteneur.
    """
    assert {a.axe for a in f53.affirmations_de(phrase)} == axes_attendus, (
        f"« {phrase} » : axes {sorted({a.axe for a in f53.affirmations_de(phrase)})}"
    )


# =============================================================================
# 6. Les adaptateurs JSON — sans quoi dix-sept tests seraient morts-nés
# =============================================================================
#
# `test_adv_trois_propositions.py` juge le lot à travers ce que
# `ourouler sortie --json` publie. Tant que le lot n'est pas là, ces tests sont
# en `skip` : rien ne prouverait qu'ils s'exécuteront vraiment le jour venu,
# ni que l'adaptateur sait lire un document où les phrases existent. On le
# prouve ici, sur des documents fabriqués à la forme du vrai.


def _candidate_json(numero: int, *, phrase: str, pluie: float, demi_tours: int,
                    duree_s: float, part_connue: float, note: float = 1.0) -> dict:
    """Une candidate à la forme exacte de `commande._candidate_json`, plus la phrase."""
    return {
        "numero": numero,
        "retenue": numero == 1,
        "nom": f"anneau {numero}",
        "distance_km": 55.2,
        "denivele_m": 340,
        "azimut_deg": 90.0 * numero,
        "ecart_relatif": 0.01,
        "part_connue": part_connue,
        "vitesse_kmh": 27.4,
        "phrase": phrase,
        "placement": {
            "note_totale": note,
            "note_terrain": 0.0,
            "penalite_seance": note,
            "duree_totale_s": duree_s,
            "distance_totale_m": 55_200.0,
            "demi_tours": demi_tours,
            "blocs_bien_places": 0,
            "avertissements": [],
            "informations": [],
            "emplacements": [],
        },
        "couts": {"km_trafic": 24.1, "km_calme": 31.1, "score": 1.0, "sens": "horaire"},
        "meteo": {
            "pluie_cumulee_mm": pluie,
            "minutes_pluie": 0.0,
            "part_vent_face": 0.33,
            "confiance": "bonne",
            "n_echantillons": 12,
        },
    }


def _doc_json(candidates: list[dict], **extra) -> dict:
    return {
        "jour": "2026-09-16",
        "seance": {"nom": "EF 2 h", "duree_s": 7200, "n_etapes": 1, "n_blocs": 0, "meta": {}},
        "demande": {"distance_km": 55.2, "candidates": 5},
        "candidates": candidates,
        **extra,
    }


def test_l_adaptateur_json_lit_trois_propositions_contrastees():
    """Le chemin nominal : trois propositions distinctes, chacune avec sa phrase."""
    doc = _doc_json([
        _candidate_json(1, phrase="la plus sèche", pluie=0.0, demi_tours=2,
                        duree_s=7800.0, part_connue=0.4),
        _candidate_json(2, phrase="aucun demi-tour", pluie=6.0, demi_tours=0,
                        duree_s=9000.0, part_connue=0.5, note=1.4),
        _candidate_json(3, phrase="20 minutes de moins, la plus courte", pluie=4.0,
                        demi_tours=1, duree_s=7210.0, part_connue=0.9, note=1.8),
    ])
    proposees = f53.propositions_du_json(doc)
    assert len(proposees) == 3, f"{len(proposees)} propositions lues, 3 publiées"
    choix = f53.choix_depuis_json(doc)
    assert [p.phrase for p in choix.retenues] == [
        "la plus sèche", "aucun demi-tour", "20 minutes de moins, la plus courte"
    ]
    f53.verifier_retenues_bien_formees(choix)
    f53.verifier_pas_de_trio_de_clones(choix)
    f53.verifier_phrases(choix)
    f53.verifier_phrases_vraies(choix)


def test_l_adaptateur_json_attrape_trois_clones_publies():
    """La preuve que le test central n'est pas mort-né.

    Trois propositions rigoureusement identiques sur tous les axes que le JSON
    porte, chacune avec une phrase distincte et bien tournée : c'est exactement
    la livraison ratée que le lot existe pour éviter. La chaîne complète —
    lecture du JSON puis vérification — doit la refuser.
    """
    jumelle = dict(phrase="", pluie=1.0, demi_tours=1, duree_s=7800.0, part_connue=0.5)
    doc = _doc_json([
        _candidate_json(1, **{**jumelle, "phrase": "la plus sèche"}),
        _candidate_json(2, **{**jumelle, "phrase": "aucun demi-tour"}),
        _candidate_json(3, **{**jumelle, "phrase": "elle évite les villages"}),
    ])
    choix = f53.choix_depuis_json(doc)
    assert len(choix.retenues) == 3, "les trois clones sont bien lus"
    _attrape(
        lambda: f53.verifier_pas_de_trio_de_clones(choix),
        quoi="trois clones publiés en JSON avec de belles phrases",
    )


def test_l_adaptateur_json_accepte_l_aveu_de_ressemblance():
    """Le contrat autorise « il vaut mieux n'en proposer que deux et le dire ».

    Un lot qui publie deux propositions jumelles **en le disant** ne doit pas
    être sanctionné : c'est le chemin de sortie prévu. Sans ce test, le
    vérificateur pourrait être bloquant là où le contrat est permissif — le
    genre de faux positif qui fait supprimer un test plutôt que corriger le code.
    """
    jumelle = dict(pluie=1.0, demi_tours=1, duree_s=7800.0, part_connue=0.5)
    doc = _doc_json(
        [
            _candidate_json(1, phrase="au nord", **jumelle),
            _candidate_json(2, phrase="au sud", **jumelle),
        ],
        contraste="deux boucles seulement : les autres se ressemblent trop pour être proposées",
    )
    choix = f53.choix_depuis_json(doc)
    assert not choix.contraste_affirme, (
        f"l'aveu n'a pas été reconnu dans {choix.motif!r}"
    )
    f53.verifier_pas_de_trio_de_clones(choix)


def test_l_adaptateur_json_attrape_une_phrase_fausse():
    """« la plus sèche » sur la plus arrosée, à travers le JSON."""
    doc = _doc_json([
        _candidate_json(1, phrase="la plus sèche", pluie=9.0, demi_tours=2,
                        duree_s=7800.0, part_connue=0.4),
        _candidate_json(2, phrase="aucun demi-tour", pluie=0.0, demi_tours=0,
                        duree_s=9000.0, part_connue=0.5),
    ])
    choix = f53.choix_depuis_json(doc)
    _attrape(
        lambda: f53.verifier_phrases_vraies(choix), quoi="phrase fausse publiée en JSON"
    )


def test_l_adaptateur_json_ne_lit_aucune_phrase_avant_le_lot():
    """Sur un document à la forme de `sprint-5`, aucune phrase : le skip est mérité.

    Contrôle négatif indispensable : si l'adaptateur inventait une phrase à
    partir d'une clé quelconque (« nom », « motif »…), les dix-sept tests en
    skip s'exécuteraient sur du vide et passeraient pour de mauvaises raisons.
    """
    doc = _doc_json([
        {k: v for k, v in _candidate_json(
            1, phrase="", pluie=0.0, demi_tours=0, duree_s=7200.0, part_connue=0.5
        ).items() if k != "phrase"},
    ])
    assert f53.propositions_du_json(doc) == [], (
        "une candidate sans phrase ne doit pas être lue comme une proposition"
    )
    assert f53.choix_depuis_json(doc).retenues == []


def test_l_adaptateur_json_trouve_la_densite_ou_qu_elle_soit():
    """La densité publiée sous n'importe quelle clé évoquant « densité » ou « marqueur »."""
    base = _candidate_json(1, phrase="elle évite les villages", pluie=0.0, demi_tours=0,
                           duree_s=7200.0, part_connue=0.5)
    for cle, ou in (
        ("densite_marqueurs_km", "racine"),
        ("marqueurs_par_km", "racine"),
        ("densite", "placement"),
    ):
        candidate = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
        if ou == "racine":
            candidate[cle] = 7.5
        else:
            candidate["placement"][cle] = 7.5
        vue = f53.vue_depuis_json(candidate, _doc_json([candidate]))
        assert vue.axe("densite_marqueurs_km") == 7.5, (
            f"densité publiée sous « {cle} » ({ou}) non lue : {vue.axes}"
        )


def test_aucune_coordonnee_reelle_dans_les_geometries():
    """Règle absolue 1 : les fabriques partent du large du golfe de Guinée."""
    for trace in (f53.boucle_avec_marqueurs(8), f53.boucle_avec_marqueurs(0)):
        for p in trace.points:
            assert abs(p.lat) < 1.0 and abs(p.lon) < 1.0, (
                f"point ({p.lat}, {p.lon}) hors de la zone fictive : aucune fixture ne "
                "porte de coordonnée réelle (CLAUDE.md règle 1)"
            )

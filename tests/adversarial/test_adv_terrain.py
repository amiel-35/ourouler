"""L4.2 — le terrain sous un bloc, mis à l'épreuve.

Cible : contrat du sprint 4 §2 et §5. C'est un point critique : `evaluer_couloir`
ne lève jamais rien, elle rend un nombre. Un poids inversé ou un seuil raté
donne une note plausible sur un terrain infaisable, et personne ne le voit
avant d'être dehors, au milieu d'un bourg, à 320 W.

Ce qui est traqué :

* les **bornes du couloir** : bloc plus long que le tracé, position négative,
  tracé de deux points, bloc à cheval sur la fermeture d'une boucle ;
* les **seuils** du contrat pris à contre-pied : une descente de 200 m n'est
  pas une descente (moins de 300 m), une pente de −1 % non plus (au-dessus de
  −1,5 %), une montée à +1,5 % ne coûte rien (tolérée jusqu'à +2 %) ;
* la **hiérarchie** annoncée par le cadrage : « une descente longue coûte plus
  qu'un carrefour ». Elle n'est vraie que si les poids sont dans le bon ordre ;
* le **hors-champ** : trois feux au kilomètre 15 ne doivent rien changer à la
  note d'un bloc qui court du kilomètre 5 au kilomètre 9. Un évaluateur qui
  note le tracé entier au lieu du couloir passe tous les tests de forme et
  aucun de ceux-ci ;
* les **valeurs non numériques** venues d'OSM : `maxspeed = "30 mph"`,
  `maxspeed = "signals"`, altitude absente.
"""

from __future__ import annotations

from typing import Any

import fabriques4
import pytest
from fabriques4 import droite, trace_taguee
from outils import robuste

from ourouler.boucle.couts import HIGHWAY_TRAFIC
from ourouler.noyau.erreurs import ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L4.2 absent (ourouler.seance.terrain)"
MOTIF_NODE_TAGS = "Segment.node_tags absent : prérequis du lot L4.2 (contrat §2)"

ERREURS = (ErreurUtilisateur, ValueError)

#: Tracé de référence : 20 km rectilignes, plats, sur une route secondaire.
N_TRONCONS = 200
PAS_M = 100.0
#: Couloir évalué : du km 5 au km 9 — les tronçons 50 à 89.
DEBUT_M = 5000.0
LONGUEUR_M = 4000.0

#: Une route passante, prise dans la liste que `couts` fait déjà autorité.
HIGHWAY_PASSANTE = sorted(HIGHWAY_TRAFIC)[0]


def _terrain() -> Any:
    return fabriques4.module("terrain", motif=MOTIF_ABSENT)


def _exiger_node_tags() -> None:
    if not fabriques4.segments_disponibles_avec_node_tags():
        pytest.skip(MOTIF_NODE_TAGS)


def _trace(
    *,
    pentes: Any = 0.0,
    tags: Any = None,
    node_tags: dict[int, dict[str, str]] | None = None,
    alt0: float | None = 50.0,
    n: int = N_TRONCONS,
) -> Any:
    return trace_taguee(
        droite(n, pas_m=PAS_M, pentes=pentes, alt0=alt0),
        tags=tags,
        node_tags=node_tags,
        nom="ligne droite de test",
    )


def _note(trace: Any, debut: float = DEBUT_M, longueur: float = LONGUEUR_M) -> Any:
    note = _terrain().evaluer_couloir(trace, debut, longueur)
    fabriques4.verifier_note(note, quoi=f"evaluer_couloir({debut}, {longueur})")
    return note


def _pentes(paires: dict[range, float], *, n: int = N_TRONCONS) -> list[float]:
    pentes = [0.0] * n
    for intervalle, valeur in paires.items():
        for i in intervalle:
            pentes[i] = valeur
    return pentes


# --- forme et bornes ---------------------------------------------------------


def test_un_couloir_propre_ne_reproche_rien():
    note = _note(_trace())
    assert note.carrefours == 0 and note.km_batis == pytest.approx(0.0)
    assert note.descente_m == pytest.approx(0.0) and note.montee_m == pytest.approx(0.0)
    assert note.pente_moyenne == pytest.approx(0.0, abs=1e-6)
    assert note.note == pytest.approx(0.0, abs=1e-9), (
        f"note {note.note} sur 4 km plats, rectilignes et sans feu — motifs : {note.motifs}"
    )


@pytest.mark.parametrize(
    ("debut", "longueur"),
    [
        (0.0, 50_000.0),
        (-1000.0, 4000.0),
        (25_000.0, 1000.0),
        (5000.0, 0.0),
    ],
    ids=["plus_long_que_le_trace", "debut_negatif", "hors_trace", "longueur_nulle"],
)
def test_un_couloir_hors_bornes_ne_rend_ni_nan_ni_trace(debut, longueur):
    mod = _terrain()
    trace = _trace()
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(trace, debut, longueur),
        quoi=f"evaluer_couloir(debut={debut}, longueur={longueur})",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        fabriques4.verifier_note(note, quoi="NoteBloc hors bornes")


@pytest.mark.parametrize("n", [1], ids=["un_seul_troncon"])
def test_un_trace_minuscule_ne_casse_pas(n):
    mod = _terrain()
    trace = _trace(n=n)
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(trace, 0.0, 1000.0),
        quoi=f"evaluer_couloir sur un tracé de {n + 1} points",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        fabriques4.verifier_note(note, quoi="NoteBloc sur tracé minuscule")


def test_un_trace_sans_segments_reste_evaluable():
    """Un GPX importé n'a aucun segment : restent la géométrie et l'altitude."""
    mod = _terrain()
    trace = trace_taguee(droite(N_TRONCONS, pentes=0.0), sans_segments=True)
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(trace, DEBUT_M, LONGUEUR_M),
        quoi="evaluer_couloir sans segments",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        fabriques4.verifier_note(note, quoi="NoteBloc sans segments")
        assert note.km_batis == pytest.approx(0.0), "sans tags, aucun kilomètre ne peut être dit bâti"


def test_un_trace_sans_altitude_ne_fabrique_pas_de_pente():
    mod = _terrain()
    trace = _trace(alt0=None)
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(trace, DEBUT_M, LONGUEUR_M),
        quoi="evaluer_couloir sans altitude",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        fabriques4.verifier_note(note, quoi="NoteBloc sans altitude")
        assert note.descente_m == pytest.approx(0.0) and note.montee_m == pytest.approx(0.0), (
            "sans altitude, le dénivelé est inconnu, pas nul-puis-inventé"
        )


def test_evaluer_ne_modifie_pas_le_trace():
    trace = _trace()
    avant = fabriques4.instantane_trace(trace)
    _note(trace)
    assert fabriques4.instantane_trace(trace) == avant, "evaluer_couloir a modifié le tracé reçu"


# --- carrefours ---------------------------------------------------------------


def test_trois_feux_dans_le_bloc_se_comptent_et_se_paient():
    _exiger_node_tags()
    propre = _trace()
    avec_feux = _trace(node_tags={i: {"highway": "traffic_signals"} for i in (60, 65, 70)})
    note = _note(avec_feux)
    assert note.carrefours >= 3, f"trois feux dans le couloir, {note.carrefours} comptés"
    assert note.note > _note(propre).note, "trois feux dans un bloc de seuil doivent coûter"
    assert note.motifs, "un carrefour compté sans motif lisible est invisible pour le mainteneur"


def test_des_feux_hors_du_bloc_ne_changent_rien():
    """Le couloir court du km 5 au km 9 ; les feux sont au km 15."""
    _exiger_node_tags()
    propre = _trace()
    ailleurs = _trace(node_tags={i: {"highway": "traffic_signals"} for i in (150, 155, 160)})
    assert _note(ailleurs).carrefours == 0, "des feux hors du couloir ont été comptés"
    assert _note(ailleurs).note == pytest.approx(_note(propre).note), (
        "la note d'un bloc dépend du couloir, pas du reste du tracé"
    )


@pytest.mark.parametrize(
    ("tags_noeud", "attendu"),
    [
        ({"highway": "traffic_signals"}, True),
        ({"highway": "mini_roundabout"}, True),
        ({"highway": "bus_stop"}, False),
    ],
    ids=["feu", "mini_rond_point", "arret_de_bus"],
)
def test_seuls_les_noeuds_de_la_liste_font_un_carrefour(tags_noeud, attendu):
    _exiger_node_tags()
    note = _note(_trace(node_tags={65: dict(tags_noeud)}))
    assert (note.carrefours >= 1) is attendu, (
        f"node_tags={tags_noeud} : {note.carrefours} carrefour(s), attendu {'au moins 1' if attendu else 0}"
    )


@pytest.mark.parametrize(("angle", "attendu"), [(90.0, True), (20.0, False)], ids=["angle_droit", "leger"])
def test_un_virage_serre_compte_comme_un_carrefour(angle, attendu):
    """Contrat §2 : « virage de plus de 60° détecté géométriquement »."""
    coords = fabriques4.virage(65, 135, angle_deg=angle, pas_m=PAS_M)
    note = _note(trace_taguee(coords))
    assert (note.carrefours >= 1) is attendu, (
        f"virage de {angle}° au km 6,5 : {note.carrefours} carrefour(s) comptés"
    )


# --- zones bâties -------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags_troncon", "batie"),
    [
        ({"highway": "residential"}, True),
        ({"highway": "living_street"}, True),
        ({"highway": "tertiary", "maxspeed": "50"}, True),
        ({"highway": "tertiary", "maxspeed": "70"}, False),
    ],
    ids=["residentiel", "zone_de_rencontre", "limite_50", "limite_70"],
)
def test_la_zone_batie_suit_la_regle_du_contrat(tags_troncon, batie):
    tags = [{"highway": "secondary"} for _ in range(N_TRONCONS)]
    for i in range(60, 70):  # 1 km dans le couloir
        tags[i] = dict(tags_troncon)
    note = _note(_trace(tags=tags))
    if batie:
        assert note.km_batis == pytest.approx(1.0, abs=0.15), (
            f"1 km de {tags_troncon} dans le couloir, km_batis = {note.km_batis}"
        )
        assert note.note > 0.0, "une traversée de bourg dans un bloc doit se payer"
    else:
        assert note.km_batis == pytest.approx(0.0), f"{tags_troncon} n'est pas une zone bâtie"


@pytest.mark.parametrize("maxspeed", ["30 mph", "50;30"])
def test_un_maxspeed_non_numerique_ne_leve_pas(maxspeed):
    """OSM écrit ce qu'il veut dans `maxspeed` : un `int()` nu tomberait."""
    mod = _terrain()
    tags = [{"highway": "tertiary"} for _ in range(N_TRONCONS)]
    for i in range(60, 70):
        tags[i] = {"highway": "tertiary", "maxspeed": maxspeed}
    trace = _trace(tags=tags)
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(trace, DEBUT_M, LONGUEUR_M),
        quoi=f"maxspeed={maxspeed!r}",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        fabriques4.verifier_note(note, quoi=f"NoteBloc maxspeed={maxspeed!r}")


# --- pentes -------------------------------------------------------------------


def test_une_descente_longue_se_compte_et_coute_cher():
    """1 km à −3 % dans le bloc : 30 m de descente, le défaut le plus grave."""
    descendante = _trace(pentes=_pentes({range(60, 70): -0.03}))
    note = _note(descendante)
    assert note.descente_m == pytest.approx(30.0, abs=2.0), (
        f"1 km à −3 % fait 30 m de descente, compté {note.descente_m}"
    )
    assert note.note > _note(_trace()).note, "une descente dans un bloc de seuil doit coûter"


@pytest.mark.parametrize(
    ("pente", "troncons", "raison"),
    [
        (-0.03, 2, "moins de 300 m"),
        (-0.01, 10, "au-dessus de −1,5 %"),
    ],
    ids=["descente_courte", "pente_douce"],
)
def test_une_descente_sous_les_seuils_n_est_pas_une_descente(pente, troncons, raison):
    trace = _trace(pentes=_pentes({range(60, 60 + troncons): pente}))
    note = _note(trace)
    assert note.descente_m == pytest.approx(0.0), (
        f"descente comptée ({note.descente_m} m) alors qu'elle est {raison} — contrat §2"
    )


def test_une_montee_douce_ne_coute_rien():
    """Contrat §2 : « tolérée et non pénalisée jusqu'à +2 % »."""
    plat = _note(_trace())
    douce = _note(_trace(pentes=0.015))
    assert douce.note == pytest.approx(plat.note, abs=1e-6), (
        f"une montée régulière à +1,5 % est notée {douce.note} contre {plat.note} sur le plat "
        f"— motifs : {douce.motifs}"
    )


def test_une_montee_raide_coute_moins_qu_une_descente_equivalente():
    montante = _note(_trace(pentes=_pentes({range(55, 85): 0.04})))
    descendante = _note(_trace(pentes=_pentes({range(55, 85): -0.04})))
    plat = _note(_trace())
    assert montante.note > plat.note, "au-delà de +2 %, la montée se paie (poids modéré)"
    assert descendante.note > montante.note, (
        f"descente notée {descendante.note}, montée {montante.note} : sur un bloc de seuil, "
        "c'est la descente qu'on ne peut pas tenir"
    )


def test_une_longue_descente_coute_plus_qu_un_carrefour():
    """Hiérarchie annoncée au cadrage : « une descente longue coûte plus qu'un carrefour »."""
    _exiger_node_tags()
    descendante = _note(_trace(pentes=_pentes({range(55, 85): -0.03})))
    un_feu = _note(_trace(node_tags={65: {"highway": "traffic_signals"}}))
    assert descendante.note > un_feu.note, (
        f"3 km à −3 % notés {descendante.note}, un feu noté {un_feu.note} : poids inversés"
    )


def test_un_profil_irregulier_coute_plus_qu_un_profil_regulier():
    """Écart-type de la pente, poids faible mais non nul (contrat §2)."""
    # ±1,2 % : sous le seuil de montée tolérée (+2 %) et au-dessus de celui de
    # descente (−1,5 %). Ne reste que l'écart-type pour différencier les deux.
    alternee = [0.012 if i % 2 else -0.012 for i in range(N_TRONCONS)]
    irregulier = _note(_trace(pentes=alternee))
    regulier = _note(_trace())
    assert irregulier.pente_moyenne == pytest.approx(0.0, abs=1e-3), "profil en dents de scie, moyenne nulle"
    assert irregulier.descente_m == pytest.approx(0.0) and irregulier.montee_m == pytest.approx(0.0), (
        "aucune portion ne dépasse les seuils : seul l'écart-type de la pente peut jouer"
    )
    assert irregulier.note > regulier.note, (
        f"profil en dents de scie noté {irregulier.note}, plat noté {regulier.note} : "
        "l'irrégularité n'est pas prise en compte"
    )


# --- boucle fermée -------------------------------------------------------------


def test_un_bloc_a_cheval_sur_la_fermeture_continue_sur_la_boucle():
    """Contrat §2 (`route_au_dela`) : sur une boucle fermée, « on continue sur la boucle »."""
    _exiger_node_tags()
    mod = _terrain()
    boucle = fabriques4.boucle_plate(node_tags={2: {"highway": "traffic_signals"}})
    debut = boucle.distance_m - 500.0
    note, erreur = robuste(
        lambda: mod.evaluer_couloir(boucle, debut, 1500.0),
        quoi="evaluer_couloir à cheval sur la fermeture",
        erreurs_acceptees=ERREURS,
    )
    if erreur is not None:
        return
    fabriques4.verifier_note(note, quoi="NoteBloc à cheval")
    assert note.carrefours >= 1, (
        "le feu placé juste après la fermeture n'a pas été vu : le couloir a été tronqué "
        "au lieu de continuer sur la boucle"
    )


# --- route au-delà -------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "besoin", "attendu"),
    [(10_000.0, 5000.0, True), (10_000.0, 15_000.0, False), (19_900.0, 1000.0, False)],
    ids=["assez_de_route", "trace_trop_court", "presque_la_fin"],
)
def test_route_au_dela_sur_un_trace_ouvert(position, besoin, attendu):
    mod = _terrain()
    assert mod.route_au_dela(_trace(), position, besoin) is attendu


def test_route_au_dela_est_toujours_vrai_sur_une_boucle_fermee():
    """« ou si le tracé est une boucle fermée (on continue sur la boucle) »."""
    mod = _terrain()
    boucle = fabriques4.boucle_plate()
    assert mod.route_au_dela(boucle, boucle.distance_m - 10.0, 100_000.0) is True


@pytest.mark.parametrize(
    ("position", "besoin"),
    [(-500.0, 1000.0), (10_000.0, -100.0)],
    ids=["position_negative", "besoin_negatif"],
)
def test_route_au_dela_sur_des_entrees_absurdes(position, besoin):
    mod = _terrain()
    trace = _trace()
    valeur, erreur = robuste(
        lambda: mod.route_au_dela(trace, position, besoin),
        quoi=f"route_au_dela({position}, {besoin})",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        assert isinstance(valeur, bool), f"route_au_dela doit rendre un booléen, reçu {valeur!r}"


# --- demi-tour faisable ---------------------------------------------------------


@pytest.mark.parametrize(
    ("highway", "attendu"),
    [("residential", True), ("tertiary", True), (HIGHWAY_PASSANTE, False)],
    ids=["petite_route", "departementale_calme", "route_passante"],
)
def test_demi_tour_faisable_suit_la_liste_des_routes_passantes(highway, attendu):
    mod = _terrain()
    trace = _trace(tags={"highway": highway})
    assert mod.demi_tour_faisable(trace, 10_000.0) is attendu, (
        f"demi-tour sur {highway} : le contrat §2 refuse les routes de HIGHWAY_TRAFIC et accepte le reste"
    )


@pytest.mark.parametrize("position", [50_000.0], ids=["hors_trace"])
def test_demi_tour_faisable_sur_une_position_absurde(position):
    mod = _terrain()
    trace = _trace()
    valeur, erreur = robuste(
        lambda: mod.demi_tour_faisable(trace, position),
        quoi=f"demi_tour_faisable({position})",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        assert isinstance(valeur, bool), f"demi_tour_faisable doit rendre un booléen, reçu {valeur!r}"


def test_demi_tour_faisable_sans_segments():
    """Sans tag, on ne peut pas affirmer que la route est passante."""
    mod = _terrain()
    trace = trace_taguee(droite(N_TRONCONS), sans_segments=True)
    valeur, erreur = robuste(
        lambda: mod.demi_tour_faisable(trace, 10_000.0),
        quoi="demi_tour_faisable sans segments",
        erreurs_acceptees=ERREURS,
    )
    if erreur is None:
        assert isinstance(valeur, bool)

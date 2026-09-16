"""Non-régression du lot L5.3 : ce qui existait avant lui ne doit pas bouger.

Toutes les valeurs de ce fichier ont été **relevées sur `sprint-5` le
16/09/2026, avant le lot L5.3** (commit `b2b0a3c`, « Contrat du lot L5.3 »), et
sont comparées à l'**égalité exacte**. C'est la méthode qui a payé deux fois
sur ce sprint : une valeur recopiée d'une exécution postérieure au lot ne
prouve rien — elle grave la régression au lieu de l'attraper.

Ce que le lot L5.3 a le droit de faire, d'après son §3.3.5 : « on note, on
contraste, on explique — on ne replace pas ». Donc :

* `Placement.note_totale`, `note_terrain`, `penalite_seance` et l'identité
  `note_totale = note_terrain + penalite_seance` : inchangés ;
* `terrain.evaluer_couloir` : inchangé, y compris ses deux réponses à
  « on ne sait pas » (tracé sans segments : `routes inconnues` ; tracé tagué
  sans marqueur : note nulle **mesurée**) ;
* `BaseRoutes.part_connue` : inchangé, y compris sa promesse d'être
  « informatif seulement » ;
* `_comparer` et `_notes_egales` : inchangés, bornes comprises.

Le lot ajoute un axe de contraste ; il ne renote rien. Un changement de l'une
de ces valeurs se discute avec le mainteneur, il ne se constate pas après coup.
"""

from __future__ import annotations

import inspect
import math
from datetime import date
from pathlib import Path

import fabriques4
import fabriques_l52
import fabriques_l53 as f53
import pytest

from ourouler.apprentissage.routes import BaseRoutes
from ourouler.seance.placement import placer
from ourouler.seance.terrain import evaluer_couloir
from ourouler.sortie.commande import POIDS_PLUIE_TRI, Proposition, _comparer, _notes_egales

# =============================================================================
# 1. `_notes_egales` — la table, au booléen près
# =============================================================================

#: `(a, b, tolerance, attendu)`. Relevé sur sprint-5 le 16/09/2026.
#:
#: Trois lignes méritent d'être lues avant d'être touchées :
#: * `(1.0, 1.05, 0.0476)` vaut **False** et `(…, 0.05)` vaut True : l'écart
#:   relatif est rapporté à la **plus grande** des deux notes (0,05/1,05 =
#:   0,047619…), pas à la plus petite ni à leur moyenne. Trois lignes encadrent
#:   ce point de bascule à 10⁻⁴ près.
#: * `(0.0, 1e-300, 0.1)` vaut **False** : deux notes microscopiques mais
#:   différentes ne sont pas égales, parce que l'écart est rapporté à
#:   l'échelle, qui est elle aussi microscopique. Une implémentation qui
#:   comparerait `abs(a-b) <= tolerance` en absolu rendrait True.
#: * `(-1.0, 1.0, 10.0)` vaut **True** : rien n'interdit une tolérance > 1.
TABLE_NOTES_EGALES = (
    (0.0, 0.0, 0.0, True),
    (0.0, 0.0, 0.1, True),
    (0.0, 1e-300, 0.1, False),
    (1.0, 1.0, 0.0, True),
    (1.0, 1.05, 0.05, True),
    (1.0, 1.05, 0.0476, False),
    (1.0, 1.05, 0.0475, False),
    (-1.0, -1.0, 0.0, True),
    (-1.0, 1.0, 10.0, True),
    (2.0, 0.0, 1.0, True),
    (2.0, 0.0, 0.999, False),
    (1.93, 2.30, 0.16, False),
    (1.93, 2.30, 0.161, True),
    (0.0, 0.05, 0.0, False),
    (0.0, 0.05, 1.0, True),
)


@pytest.mark.parametrize(("a", "b", "tolerance", "attendu"), TABLE_NOTES_EGALES)
def test_notes_egales_ne_bouge_pas(a, b, tolerance, attendu):
    assert _notes_egales(a, b, tolerance) is attendu, (
        f"_notes_egales({a}, {b}, {tolerance}) : {attendu} relevé sur sprint-5 avant L5.3. "
        "Le lot §3.3.5 ne touche pas au tri."
    )


def test_notes_egales_est_symetrique():
    """Invariant, pas valeur figée : l'ordre des arguments ne change rien.

    `echelle = max(abs(a), abs(b))` est symétrique ; une réécriture en
    `abs(a - b) / abs(a)` ne le serait plus, et le tri dépendrait alors de
    l'ordre dans lequel `functools.cmp_to_key` présente les candidates.
    """
    for a, b, tolerance, _ in TABLE_NOTES_EGALES:
        assert _notes_egales(a, b, tolerance) is _notes_egales(b, a, tolerance), (
            f"_notes_egales n'est pas symétrique sur ({a}, {b}, {tolerance})"
        )


# =============================================================================
# 2. `_comparer` — les signes, à l'entier près
# =============================================================================

#: `(note_a, pluie_a, note_b, pluie_b)`.
CAS_COMPARER = (
    (1.0, 0.0, 2.0, 0.0),
    (2.0, 0.0, 1.0, 0.0),
    (1.0, 5.0, 1.0, 1.0),
    (1.0, 1.0, 1.0, 1.0),
    (1.0, 5.0, 1.02, 1.0),
    (1.0, 0.0, 1.02, 3.0),
    (0.0, 1.0, 0.0, 2.0),
    (0.0, 2.0, 0.0, 1.0),
)

#: Relevé sur sprint-5 avant L5.3. La cinquième colonne est la seule qui change
#: entre les deux tolérances, et c'est tout l'objet de `tolerance_egalite` :
#: à 0 le vent (dans la note) tranche toujours, à 0,05 la pluie départage deux
#: notes que rien ne distingue vraiment.
SIGNES_ATTENDUS = {
    0.0: (-1, 1, 1, 0, -1, -1, -1, 1),
    0.05: (-1, 1, 1, 0, 1, -1, -1, 1),
}


class _PropositionMinimale:
    """Le strict nécessaire pour `_comparer` : une note et une pluie."""

    def __init__(self, note: float, pluie: float):
        self.placement = type("_P", (), {"note_totale": note})()
        self._pluie = pluie

    @property
    def pluie_mm(self) -> float:
        return self._pluie


@pytest.mark.parametrize("tolerance", sorted(SIGNES_ATTENDUS))
def test_comparer_ne_bouge_pas(tolerance):
    comparer = _comparer(tolerance)
    obtenus = tuple(
        comparer(_PropositionMinimale(na, pa), _PropositionMinimale(nb, pb))
        for na, pa, nb, pb in CAS_COMPARER
    )
    assert obtenus == SIGNES_ATTENDUS[tolerance], (
        f"tolérance {tolerance} : {obtenus} au lieu de {SIGNES_ATTENDUS[tolerance]} relevé sur "
        "sprint-5 avant L5.3."
    )


def test_comparer_est_antisymetrique():
    """`comparer(a, b) == -comparer(b, a)`, sinon le tri n'est pas déterministe."""
    for tolerance in SIGNES_ATTENDUS:
        comparer = _comparer(tolerance)
        for na, pa, nb, pb in CAS_COMPARER:
            a, b = _PropositionMinimale(na, pa), _PropositionMinimale(nb, pb)
            assert comparer(a, b) == -comparer(b, a), (
                f"comparer non antisymétrique sur ({na}, {pa}) / ({nb}, {pb}), "
                f"tolérance {tolerance}"
            )


def test_poids_pluie_tri_ne_bouge_pas():
    assert POIDS_PLUIE_TRI == 2.0, "POIDS_PLUIE_TRI valait 2,0 sur sprint-5 avant L5.3"


def test_comparer_garde_sa_signature():
    """`_comparer(tolerance)` rend un comparateur à deux arguments.

    Une signature qui gagnerait un axe de contraste obligatoire ferait basculer
    en erreur, pas en skip, les tests ci-dessus : on préfère le dire ici.
    """
    parametres = list(inspect.signature(_comparer).parameters)
    assert parametres == ["tolerance"], (
        f"_comparer prend maintenant {parametres} : le lot §3.3.5 ne touche pas au tri "
        "(« on note, on contraste, on explique — on ne replace pas »)."
    )


# =============================================================================
# 3. `Proposition.tri` et l'identité de la note
# =============================================================================


def test_proposition_garde_ses_champs_d_axe():
    """Les axes que le contrat §3.3.2 dit « mesure existante » doivent exister.

    Si le lot renomme `pluie_mm`, `demi_tours` ou `part_connue`, la moitié du
    tableau de la §3.3.2 ne désigne plus rien. Le lot a le droit d'**ajouter**
    des champs, pas de retirer ceux sur lesquels il s'appuie.
    """
    for nom in ("pluie_mm", "demi_tours", "blocs_bien_places", "distance_parcours_m", "tri"):
        assert hasattr(Proposition, nom), (
            f"Proposition.{nom} a disparu : le contrat §3.3.2 le cite comme « mesure "
            "existante » sur laquelle le contraste s'appuie"
        )
    champs = {f for f in Proposition.__dataclass_fields__}
    for nom in ("placement", "trace", "meteo", "part_connue", "azimut_deg", "vitesse_kmh"):
        assert nom in champs, f"Proposition.{nom} a disparu (champ du sprint 4)"


#: Relevés sur sprint-5 avant L5.3, sur `fabriques_l52.boucle_carree(15 km de
#: côté, pas 250 m)` et `fabriques_l52.seance_2x20()`. Un carré de 60 km, deux
#: blocs de 20 min, un demi-tour : ni dégénéré ni particulier.
GOLDEN_2X20 = {
    "note_totale": 1.0634017128524713,
    "note_terrain": 0.6,
    "penalite_seance": 0.46340171285247134,
    "duree_totale_s": 11480.410277114828,
    "distance_totale_m": 96785.03858216893,
    "decalage_z2_s": 660.0,
    "n_emplacements": 5,
    "n_blocs": 2,
    "jalons_m": [0.0, 48392.51929108446, 0.0],
}

#: Le cas courant du mainteneur (contrat §3.1.3 b) : aucune étape n'est un bloc.
#: `note_terrain` vaut **exactement zéro**, et toute la note est la pénalité
#: d'extrémité. C'est le classement dégénéré que L5.3 doit traverser sans
#: diviser par zéro.
GOLDEN_SANS_BLOC = {
    "note_totale": 0.3656537273469966,
    "note_terrain": 0.0,
    "penalite_seance": 0.3656537273469966,
    "duree_totale_s": 7233.92236408198,
    "distance_totale_m": 60000.0,
    "n_blocs": 0,
}


def _placement_2x20():
    return placer(
        fabriques_l52.seance_2x20(),
        fabriques_l52.boucle_carree(cote_m=15_000.0, pas_m=250.0),
        fabriques_l52.parametres(),
    )


def _placement_sans_bloc():
    return placer(
        fabriques_l52.seance_sans_bloc(),
        fabriques_l52.boucle_carree(cote_m=15_000.0, pas_m=250.0),
        fabriques_l52.parametres(),
    )


@pytest.mark.parametrize("cle", sorted(GOLDEN_2X20))
def test_placement_2x20_ne_bouge_pas(cle):
    p = _placement_2x20()
    assert p is not None, "la séance 2×20 tenait sur cette boucle sur sprint-5"
    obtenu = {
        "note_totale": p.note_totale,
        "note_terrain": p.note_terrain,
        "penalite_seance": p.penalite_seance,
        "duree_totale_s": p.duree_totale_s,
        "distance_totale_m": p.distance_totale_m,
        "decalage_z2_s": p.decalage_z2_s,
        "n_emplacements": len(p.emplacements),
        "n_blocs": len(p.blocs()),
        "jalons_m": list(p.jalons_m),
    }[cle]
    assert obtenu == GOLDEN_2X20[cle], (
        f"{cle} : {obtenu!r} au lieu de {GOLDEN_2X20[cle]!r} relevé sur sprint-5 avant L5.3. "
        "Comparaison à l'égalité exacte, volontairement : le lot ne replace rien (§3.3.5)."
    )


@pytest.mark.parametrize("cle", sorted(GOLDEN_SANS_BLOC))
def test_placement_sans_bloc_ne_bouge_pas(cle):
    p = _placement_sans_bloc()
    assert p is not None, "la séance sans bloc tenait sur cette boucle sur sprint-5"
    obtenu = {
        "note_totale": p.note_totale,
        "note_terrain": p.note_terrain,
        "penalite_seance": p.penalite_seance,
        "duree_totale_s": p.duree_totale_s,
        "distance_totale_m": p.distance_totale_m,
        "n_blocs": len(p.blocs()),
    }[cle]
    assert obtenu == GOLDEN_SANS_BLOC[cle], (
        f"{cle} : {obtenu!r} au lieu de {GOLDEN_SANS_BLOC[cle]!r} relevé sur sprint-5 avant L5.3"
    )


@pytest.mark.parametrize("fabriquer", [_placement_2x20, _placement_sans_bloc])
def test_identite_note_totale(fabriquer):
    """`note_totale = note_terrain + penalite_seance`, à l'arrondi flottant près.

    L'identité est documentée sur `Placement.penalite_seance`. Le lot L5.3 note
    les candidates sur sept axes : s'il range l'un d'eux dans `note_totale`,
    l'identité casse et l'affichage `_seance_placee` (« = terrain … + extrémités
    … ») se met à mentir. La marge est `1e-12` en relatif — largement au-dessus
    du bruit d'une addition de deux flottants, très en dessous de n'importe
    quel axe ajouté.
    """
    p = fabriquer()
    assert p is not None
    somme = p.note_terrain + p.penalite_seance
    assert p.note_totale == pytest.approx(somme, rel=1e-12, abs=1e-12), (
        f"note_totale = {p.note_totale!r} mais terrain + extrémités = {somme!r} "
        f"(terrain {p.note_terrain!r}, extrémités {p.penalite_seance!r}). "
        "L'identité est documentée sur `Placement.penalite_seance` et sert à l'affichage."
    )


def test_la_seance_sans_bloc_ne_note_aucun_terrain():
    """Le cas courant : `note_terrain` vaut **exactement** zéro, pas « presque ».

    C'est le point de départ de tout le §3.3.2 (« vaut zéro sur une séance sans
    bloc, donc jamais seul »). Si ce zéro devenait un epsilon, la démonstration
    du contrat s'effondrerait sans bruit.
    """
    p = _placement_sans_bloc()
    assert p is not None
    assert p.note_terrain == 0.0, f"note_terrain = {p.note_terrain!r}, attendu 0.0 exactement"
    assert p.blocs() == [], "une séance sans bloc n'a aucun emplacement noté"


# =============================================================================
# 4. `terrain.evaluer_couloir` — et ses deux façons de dire « je ne sais pas »
# =============================================================================


def _trace_200_troncons(node_tags=None, *, sans_segments=False):
    coords = fabriques4.droite(200, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0)
    return fabriques4.trace_taguee(
        coords,
        tags={"highway": "tertiary"},
        node_tags=node_tags,
        sans_segments=sans_segments,
    )


def _trace_taguee_dense():
    noeuds = {i: {"highway": "traffic_signals"} for i in range(10, 200, 20)}
    noeuds.update({i: {"traffic_calming": "bump"} for i in range(15, 200, 20)})
    return _trace_200_troncons(noeuds)


def test_evaluer_couloir_ne_bouge_pas():
    """Relevé sur sprint-5 avant L5.3 : deux feux, deux ralentisseurs, note 4,0."""
    note = evaluer_couloir(_trace_taguee_dense(), 2000.0, 5000.0, puissance_w=210.0, ftp_w=200.0)
    assert note.note == 4.0, f"note {note.note!r}, attendu 4.0"
    assert note.carrefours == 4, f"carrefours {note.carrefours!r}, attendu 4"
    assert note.km_batis == 0.0, f"km_batis {note.km_batis!r}, attendu 0.0"
    assert list(note.motifs) == ["deux feux", "deux ralentisseurs"], (
        f"motifs {list(note.motifs)!r}"
    )


def test_une_portion_sans_marqueur_note_zero_et_ne_dit_rien():
    """Des tronçons tagués sans nœud de carrefour : zéro **mesuré**, aucun motif."""
    note = evaluer_couloir(
        _trace_200_troncons({}), 2000.0, 5000.0, puissance_w=210.0, ftp_w=200.0
    )
    assert note.note == 0.0, f"note {note.note!r}, attendu 0.0"
    assert note.carrefours == 0
    assert list(note.motifs) == [], f"motifs {list(note.motifs)!r}, attendu aucun"


def test_une_portion_sans_segments_avoue_ne_pas_savoir():
    """L'invariant du sprint 3 : une classe inconnue n'est jamais un malus…

    …et, symétriquement, elle ne devient jamais un bonus non plus. Un tracé sans
    segments rend **note nulle et le motif « routes inconnues »** : la note ne
    punit pas l'ignorance, et le motif interdit de lire ce zéro comme « la
    campagne prouvée ». C'est exactement la distinction que la densité de
    marqueurs de L5.3 doit reprendre — voir
    `test_adv_trois_propositions.py::test_densite_sur_un_trace_sans_segments`.
    """
    note = evaluer_couloir(
        _trace_200_troncons(sans_segments=True), 2000.0, 5000.0, puissance_w=210.0, ftp_w=200.0
    )
    assert note.note == 0.0, (
        f"note {note.note!r} : l'ignorance ne se paie pas (contrat du sprint 3)"
    )
    assert note.carrefours == 0
    assert "routes inconnues" in note.motifs, (
        f"motifs {list(note.motifs)!r} : sans ce motif, la note nulle se lirait « aucun feu », "
        "alors qu'elle dit « je n'ai aucun tag »"
    )


def test_les_marqueurs_reconnus_ne_bougent_pas():
    """Le vocabulaire des marqueurs, figé : L5.3 s'appuie dessus (§3.3.2)."""
    carrefour, cle_calme, sans_effet = f53.marqueurs_du_projet()
    assert carrefour == frozenset(
        {"traffic_signals", "stop", "give_way", "mini_roundabout", "crossing"}
    ), f"NOEUDS_CARREFOUR = {sorted(carrefour)}"
    assert cle_calme == "traffic_calming", f"CLE_RALENTISSEUR = {cle_calme!r}"
    assert sans_effet == frozenset({"choker", "island", "dip"}), (
        f"RALENTISSEURS_SANS_EFFET = {sorted(sans_effet)}"
    )


# =============================================================================
# 5. `BaseRoutes.part_connue` — informatif, et il le reste
# =============================================================================


def _base_et_traces(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    longue = fabriques4.trace_taguee(
        fabriques4.droite(200, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0),
        tags={"highway": "tertiary"},
    )
    moitie = fabriques4.trace_taguee(
        fabriques4.droite(100, pas_m=100.0, cap_deg=90.0, pentes=0.0, alt0=50.0),
        tags={"highway": "tertiary"},
    )
    return base, longue, moitie


def test_part_connue_ne_bouge_pas(tmp_path: Path):
    """Relevé sur sprint-5 avant L5.3. 0,5 à 10⁻¹⁵ près, pas « à peu près ».

    La marge est serrée **exprès** : la valeur exacte relevée était
    0,5000000000000002, c'est-à-dire un cumul de flottants sur 20 km. Une marge
    large laisserait passer un changement de découpage en mailles, qui est
    précisément ce qu'un lot qui touche à `part_connue` ferait bouger.
    """
    base, longue, moitie = _base_et_traces(tmp_path)
    assert base.part_connue(longue) == 0.0, "base vide : on ne connaît rien"
    base.ajouter_trace(moitie, jour=date(2026, 1, 15), id_sortie="essai-1")
    assert base.part_connue(longue) == pytest.approx(0.5, abs=1e-12), (
        f"moitié apprise : {base.part_connue(longue)!r}, attendu 0,5"
    )
    assert base.part_connue(moitie) == 1.0, "tout appris : exactement 1,0"


def test_part_connue_reste_bornee(tmp_path: Path):
    """Invariant : une part est dans [0, 1], et jamais un NaN.

    Le lot L5.3 fait entrer `part_connue` dans le contraste (§3.3.2 :
    « aujourd'hui absent du classement »). Une valeur hors bornes normaliserait
    de travers tous les autres axes.
    """
    base, longue, moitie = _base_et_traces(tmp_path)
    base.ajouter_trace(moitie, jour=date(2026, 1, 15), id_sortie="essai-1")
    for trace in (longue, moitie):
        valeur = base.part_connue(trace)
        assert math.isfinite(valeur), f"part_connue = {valeur!r}"
        assert 0.0 <= valeur <= 1.0, f"part_connue = {valeur!r} hors de [0, 1]"


def test_part_connue_d_un_trace_vide_rend_zero(tmp_path: Path):
    """« pas une division par zéro, et pas 1,0 » — le docstring du sprint 3."""
    from ourouler.boucle.trace import Trace

    base, _, _ = _base_et_traces(tmp_path)
    vide = Trace(
        nom="vide",
        points=[],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
        meta={},
    )
    assert base.part_connue(vide) == 0.0, (
        "un tracé vide rend 0,0 : « on ne connaît rien de ce qu'on n'a pas mesuré »"
    )

"""Tests de `seance.placement` (sprint 4, lot L4.3).

`seance/modele.py` (lot L4.1) et `seance/terrain.py` (lot L4.2) sont écrits en
parallèle par d'autres agents. Le **code de production les importe pour de
vrai** ; ce fichier de test, lui, installe des doubles minimaux — mêmes
champs, mêmes signatures que le contrat du sprint 4 §1 et §2 — tant que les
vrais modules ne sont pas fusionnés, et s'efface dès qu'ils arrivent. Les
fonctions de terrain sont de toute façon remplacées par `monkeypatch` dans
chaque test : on veut un terrain dont on connaît la réponse, pas le vrai.

Aucune coordonnée réelle : le tracé est une ligne droite au large du golfe de
Guinée, comme les autres tracés synthétiques du dépôt. Aucun réseau.
"""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass, field, replace
from datetime import date

import pytest

import ourouler.seance
from ourouler.boucle.trace import PointTrace, Trace
from ourouler.physique.modele import Parametres, vitesse_regime

TYPES = ("echauffement", "bloc", "recuperation", "calme")


# --- doubles des deux lots parallèles ----------------------------------------


@dataclass(frozen=True)
class _Etape:
    type: str
    duree_s: float
    puissance_min_w: float | None
    puissance_max_w: float | None
    libelle: str = ""
    elastique: bool = False

    @property
    def puissance_cible_w(self) -> float | None:
        if self.puissance_min_w is None or self.puissance_max_w is None:
            return self.puissance_min_w if self.puissance_max_w is None else self.puissance_max_w
        return (self.puissance_min_w + self.puissance_max_w) / 2


@dataclass
class _Seance:
    nom: str
    jour: date
    etapes: list[_Etape]
    duree_s: float
    meta: dict = field(default_factory=dict)

    def blocs(self) -> list[tuple[int, _Etape]]:
        return [(i, e) for i, e in enumerate(self.etapes) if e.type == "bloc"]


@dataclass
class _NoteBloc:
    note: float
    motifs: list[str] = field(default_factory=list)
    pente_moyenne: float = 0.0
    pente_max: float = 0.0
    carrefours: int = 0
    km_batis: float = 0.0
    descente_m: float = 0.0
    montee_m: float = 0.0


def _double(nom: str) -> types.ModuleType:
    module = types.ModuleType(f"ourouler.seance.{nom}")
    sys.modules[module.__name__] = module
    setattr(ourouler.seance, nom, module)
    return module


def _installer_les_doubles() -> list[str]:
    """Installe un double pour chaque module du sprint 4 qui n'existe pas encore."""
    absents = []
    try:
        importlib.import_module("ourouler.seance.modele")
    except ModuleNotFoundError:
        modele = _double("modele")
        modele.TYPES, modele.Etape, modele.Seance = TYPES, _Etape, _Seance
        absents.append("seance.modele")
    try:
        importlib.import_module("ourouler.seance.terrain")
    except ModuleNotFoundError:
        terrain = _double("terrain")
        terrain.NoteBloc = _NoteBloc
        terrain.evaluer_couloir = lambda trace, debut_m, longueur_m: _NoteBloc(0.0)
        terrain.route_au_dela = lambda trace, position_m, besoin_m: True
        terrain.demi_tour_faisable = lambda trace, position_m: True
        absents.append("seance.terrain")
    return absents


DOUBLES = _installer_les_doubles()

from ourouler.seance import placement  # noqa: E402
from ourouler.seance.modele import Etape, Seance  # noqa: E402
from ourouler.seance.terrain import NoteBloc  # noqa: E402

# --- fixtures synthétiques ----------------------------------------------------

#: Un cycliste plausible, aucune donnée personnelle : 80 kg tout compris.
P = Parametres(masse_totale_kg=80.0, cda_m2=0.35, crr=0.006)

PUISSANCE_Z2 = 180.0
PUISSANCE_BLOC = 210.0
PUISSANCE_RECUP = 140.0
PUISSANCE_CALME = 150.0

#: Degrés de longitude par mètre à l'équateur (le tracé est une ligne droite).
DEG_PAR_M = 1.0 / 111_194.9


def _trace(longueur_m: float = 78_000.0, *, pente: float = 0.0, pas_m: float = 500.0) -> Trace:
    """Une ligne droite vers l'est, d'altitude constante (ou de pente constante)."""
    n = int(longueur_m // pas_m)
    points = [
        PointTrace(lat=0.0, lon=i * pas_m * DEG_PAR_M, alt_m=100.0 + pente * i * pas_m, dist_m=i * pas_m)
        for i in range(n + 1)
    ]
    return Trace(
        nom="essai",
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=None,
        temps_moteur_s=None,
    )


def _etape(type_: str, minutes: float, puissance: float | None, *, elastique: bool = False) -> Etape:
    return Etape(
        type=type_,
        duree_s=minutes * 60.0,
        puissance_min_w=None if puissance is None else puissance - 10,
        puissance_max_w=None if puissance is None else puissance + 10,
        libelle=f"{type_} {minutes:g} min",
        elastique=elastique,
    )


def _seance() -> Seance:
    """1 h d'échauffement, 2 × [20 min de bloc, 4 min de récup], 30 min de calme."""
    etapes = [
        _etape("echauffement", 60, PUISSANCE_Z2, elastique=True),
        _etape("bloc", 20, PUISSANCE_BLOC),
        _etape("recuperation", 4, PUISSANCE_RECUP),
        _etape("bloc", 20, PUISSANCE_BLOC),
        _etape("recuperation", 4, PUISSANCE_RECUP),
        _etape("calme", 30, PUISSANCE_CALME, elastique=True),
    ]
    return Seance(
        nom="2x20' de test",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )


def _vitesse(puissance: float) -> float:
    """La vitesse du modèle sur le plat : le tracé d'essai n'a aucune pente."""
    return vitesse_regime(puissance, 0.0, 0.0, P)


def _positions(decalage_s: float) -> list[float]:
    """Les positions attendues [début bloc 1, fin bloc 1, début bloc 2, fin bloc 2]."""
    debut1 = _vitesse(PUISSANCE_Z2) * (3600.0 + decalage_s)
    fin1 = debut1 + _vitesse(PUISSANCE_BLOC) * 1200.0
    debut2 = fin1 + _vitesse(PUISSANCE_RECUP) * 240.0
    return [debut1, fin1, debut2, debut2 + _vitesse(PUISSANCE_BLOC) * 1200.0]


def _couloirs(monkeypatch, bon: tuple[float, float], *, mauvais: float = 10.0, pente: float = 0.0):
    """Terrain factice : note 0 dans la fenêtre `bon`, `mauvais` partout ailleurs.

    Rend la liste des couloirs évalués, pour vérifier ce qui a été noté — et
    surtout ce qui ne l'a pas été.
    """
    appels: list[tuple[float, float]] = []

    def evaluer_couloir(trace, debut_m: float, longueur_m: float) -> NoteBloc:
        appels.append((debut_m, longueur_m))
        dedans = bon[0] <= debut_m and debut_m + longueur_m <= bon[1]
        return NoteBloc(
            note=0.0 if dedans else mauvais,
            motifs=[] if dedans else ["hors du bon couloir"],
            pente_moyenne=pente,
            pente_max=pente,
            carrefours=0,
            km_batis=0.0,
            descente_m=0.0,
            montee_m=0.0,
        )

    monkeypatch.setattr(placement, "evaluer_couloir", evaluer_couloir)
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: True)
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: True)
    return appels


# --- le décalage de la Z2 d'ouverture -----------------------------------------


def test_le_decalage_va_chercher_le_seul_bon_couloir(monkeypatch):
    # Le bon couloir est exactement là où la séance tombe avec +20 % d'échauffement.
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert resultat.note_totale == 0.0
    assert [e.demi_tour for e in resultat.emplacements] == [False, False]
    assert resultat.emplacements[0].debut_m == pytest.approx(attendues[0], abs=1.0)
    assert resultat.emplacements[1].debut_m == pytest.approx(attendues[2], abs=1.0)
    assert [e.etape_idx for e in resultat.emplacements] == [1, 3]


def test_sans_le_bon_decalage_la_note_est_mauvaise(monkeypatch):
    """Le même terrain, mais sans élasticité : on tombe à côté et on le dit."""
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(_seance(), _trace(), P, elasticite=(0.0, 0.0))

    assert resultat is not None
    assert resultat.decalage_z2_s == 0.0
    # Le premier bloc tombe avant le bon couloir : la note est bien moins bonne.
    # 10 sous l'un des deux blocs, 0 sous l'autre, et les deux durent 20 min :
    # la moyenne pondérée par la durée vaut 5 (décision du 13/09, Q12).
    assert resultat.note_terrain == 5.0
    assert "hors du bon couloir" in resultat.emplacements[0].note.motifs
    assert resultat.emplacements[1].note.motifs == []


def test_pas_plus_grand_que_la_marge_essaie_quand_meme_les_bornes(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(_seance(), _trace(), P, pas_s=10_000.0)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert resultat.note_totale == 0.0


def test_pas_s_absurde_ne_boucle_pas(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    for pas in (0.0, -60.0, float("nan"), float("inf"), 1e-3):
        resultat = placement.placer(_seance(), _trace(), P, pas_s=pas)
        assert resultat is not None


# --- le demi-tour --------------------------------------------------------------


def test_demi_tour_choisi_quand_il_n_y_a_qu_un_bon_segment(monkeypatch):
    # Le bon couloir ne fait la longueur que d'un seul bloc.
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))

    resultat = placement.placer(_seance(), _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert [e.demi_tour for e in resultat.emplacements] == [False, True]
    # Le second bloc reprend exactement le segment du premier, en sens inverse.
    premier, second = resultat.emplacements
    assert second.debut_m == pytest.approx(premier.debut_m, abs=1.0)
    assert second.longueur_m == pytest.approx(premier.longueur_m, abs=1.0)
    # La pénalité de demi-tour ne porte que sur le second des deux blocs de
    # 20 min : pondérée par la durée, elle compte pour la moitié.
    assert resultat.note_terrain == pytest.approx(0.5)
    assert any("demi-tour" in m for m in second.note.motifs)


def test_demi_tour_refuse_sans_route_au_dela(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: False)

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.emplacements] == [False, False]
    # Un seul des deux blocs de 20 min tombe hors du bon couloir : 10 et 0,
    # moyenne pondérée par la durée = 5.
    assert resultat.note_terrain == 5.0


# --- la note est pondérée par la durée des blocs -------------------------------

#: Une activation de 40 s, comme les quatre du « 4x8 SV1 outdoor » du 22/04.
ACTIVATION_S = 40.0
BLOC_LONG_S = 1200.0
MAUVAIS = 10.0


def _seance_courte_et_longue() -> Seance:
    """1 h de Z2, une activation de 40 s, une récup, un bloc de 20 min, la fin."""
    etapes = [
        _etape("echauffement", 60, PUISSANCE_Z2, elastique=True),
        _etape("bloc", ACTIVATION_S / 60.0, PUISSANCE_BLOC),
        _etape("recuperation", 4, PUISSANCE_RECUP),
        _etape("bloc", BLOC_LONG_S / 60.0, PUISSANCE_BLOC),
        _etape("recuperation", 4, PUISSANCE_RECUP),
        _etape("calme", 30, PUISSANCE_CALME, elastique=True),
    ]
    return Seance(
        nom="activation + bloc long",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )


def _positions_courte_et_longue() -> tuple[tuple[float, float], tuple[float, float]]:
    """(activation, bloc long), chacun (début, fin), sans décalage d'ouverture."""
    debut_court = _vitesse(PUISSANCE_Z2) * 3600.0
    fin_court = debut_court + _vitesse(PUISSANCE_BLOC) * ACTIVATION_S
    debut_long = fin_court + _vitesse(PUISSANCE_RECUP) * 240.0
    return (debut_court, fin_court), (debut_long, debut_long + _vitesse(PUISSANCE_BLOC) * BLOC_LONG_S)


def _zone_sale(monkeypatch, zone: tuple[float, float]):
    """Terrain noté `MAUVAIS` dès qu'un couloir touche `zone`, 0 partout ailleurs.

    Le demi-tour est fermé (`route_au_dela` faux) : on compare ici deux
    placements droits, pas deux figures.
    """

    def evaluer_couloir(trace, debut_m: float, longueur_m: float) -> NoteBloc:
        touche = debut_m < zone[1] and debut_m + longueur_m > zone[0]
        return NoteBloc(
            note=MAUVAIS if touche else 0.0,
            motifs=["zone salie"] if touche else [],
            pente_moyenne=0.0,
            pente_max=0.0,
            carrefours=0,
            km_batis=0.0,
            descente_m=0.0,
            montee_m=0.0,
        )

    monkeypatch.setattr(placement, "evaluer_couloir", evaluer_couloir)
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: False)
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: False)


def test_un_mauvais_couloir_sous_un_bloc_long_pese_bien_plus_que_sous_une_activation(monkeypatch):
    """Décision du superviseur du 13/09 (Q12) : la note est pondérée par la durée.

    Même séance, même terrain, même mauvais couloir de note 10 : une fois sous
    l'activation de 40 s, une fois sous le bloc de 20 min. Le second doit être
    nettement plus pénalisé — exactement dans le rapport des durées, 1200/40.
    """
    court, long = _positions_courte_et_longue()

    _zone_sale(monkeypatch, court)
    sous_activation = placement.placer(
        _seance_courte_et_longue(), _trace(), P, elasticite=(0.0, 0.0)
    )
    monkeypatch.undo()

    _zone_sale(monkeypatch, long)
    sous_bloc_long = placement.placer(
        _seance_courte_et_longue(), _trace(), P, elasticite=(0.0, 0.0)
    )

    assert sous_activation is not None and sous_bloc_long is not None
    assert [e.demi_tour for e in sous_activation.emplacements] == [False, False]
    assert [e.demi_tour for e in sous_bloc_long.emplacements] == [False, False]
    # Un seul bloc est sali dans chaque cas, et c'est le bon.
    assert [e.note.note for e in sous_activation.emplacements] == [MAUVAIS, 0.0]
    assert [e.note.note for e in sous_bloc_long.emplacements] == [0.0, MAUVAIS]

    total_s = ACTIVATION_S + BLOC_LONG_S
    assert sous_activation.note_terrain == pytest.approx(MAUVAIS * ACTIVATION_S / total_s)
    assert sous_bloc_long.note_terrain == pytest.approx(MAUVAIS * BLOC_LONG_S / total_s)
    assert sous_bloc_long.note_terrain == pytest.approx(
        sous_activation.note_terrain * BLOC_LONG_S / ACTIVATION_S
    )
    # Une somme brute aurait donné la même note aux deux : c'est le bug corrigé.
    assert sous_bloc_long.note_terrain > 20 * sous_activation.note_terrain


def test_demi_tour_refuse_sur_une_route_a_trafic(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: False)

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.emplacements] == [False, False]


def test_demi_tour_refuse_en_cote(monkeypatch):
    """« Un tronçon marche dans les deux sens sur du plat, mais en côte » non."""
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50), pente=0.04)

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.emplacements] == [False, False]


def test_la_penalite_de_demi_tour_peut_le_rendre_moins_interessant(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50), mauvais=0.5)

    resultat = placement.placer(_seance(), _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    # Un couloir moyen tout droit (0,5) coûte moins qu'un bon couloir repris à
    # l'envers (0 + 1,0) : on reste tout droit.
    assert [e.demi_tour for e in resultat.emplacements] == [False, False]


# --- ce que la récupération ne subit pas ---------------------------------------


def test_aucune_recuperation_n_est_evaluee(monkeypatch):
    appels = _couloirs(monkeypatch, (0.0, 1e9))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    longueur_bloc = _vitesse(PUISSANCE_BLOC) * 1200.0
    assert appels, "aucun couloir évalué"
    for _debut, longueur in appels:
        assert longueur == pytest.approx(longueur_bloc, abs=1.0)


# --- la Z2 de fin absorbe -------------------------------------------------------


def test_la_z2_de_fin_absorbe_le_reste(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    trace = _trace()

    resultat = placement.placer(_seance(), trace, P)

    assert resultat is not None
    # Le retour au calme ramène jusqu'au bout du tracé, quelle que soit sa durée.
    assert resultat.distance_totale_m == pytest.approx(trace.points[-1].dist_m, abs=1.0)
    prescrit = sum(e.duree_s for e in _seance().etapes[:-1]) + resultat.decalage_z2_s
    calme = resultat.duree_totale_s - prescrit
    assert calme > 0
    # La dernière récupération est roulée elle aussi avant le retour au calme.
    fin_seance = _positions(resultat.decalage_z2_s)[3] + _vitesse(PUISSANCE_RECUP) * 240.0
    reste_m = trace.points[-1].dist_m - fin_seance
    assert calme == pytest.approx(reste_m / _vitesse(PUISSANCE_CALME), rel=1e-3)


def _trace_de_longueur(longueur_m: float) -> Trace:
    """Le tracé droit, mais d'une longueur **exacte** : le dernier point tombe pile.

    `_trace` arrondit au pas de 500 m ; ici on veut que le dernier bloc puisse
    finir exactement au bout du tracé, parce que c'est ce qui met le retour au
    calme à zéro.
    """
    trace = _trace(longueur_m)
    if trace.points[-1].dist_m < longueur_m:
        trace.points.append(
            PointTrace(lat=0.0, lon=longueur_m * DEG_PAR_M, alt_m=100.0, dist_m=longueur_m)
        )
        trace.distance_m = longueur_m
    return trace


def _seance_calme(calme_s: float) -> Seance:
    """La même séance, avec un retour au calme d'une durée choisie."""
    etapes = list(_seance().etapes)
    etapes[-1] = replace(etapes[-1], duree_s=calme_s)
    return Seance(
        nom="2x20' de test",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )


def _fin_de_seance(decalage_s: float) -> float:
    """La position atteinte quand la dernière récupération est finie."""
    return _positions(decalage_s)[3] + _vitesse(PUISSANCE_RECUP) * 240.0


def test_une_seance_tronquee_perd_contre_un_placement_complet(monkeypatch):
    """Le défaut mesuré le 08/02 : le placement gagnant ne tenait pas la séance.

    Le tracé finit exactement là où la séance se termine au décalage +12 min :
    à ce décalage, les deux blocs tombent dans le seul bon couloir (note 0),
    mais il ne reste que cinq mètres pour le retour au calme, qui tombe à 0 min
    au lieu des 13 prescrites — la séance n'est pas tenue. Au décalage nul, le
    premier bloc tombe avant le bon couloir (note 2 ; le second, lui, y retombe)
    et le retour au calme dure exactement ce qui est prescrit. C'est ce second
    placement qui doit gagner : un terrain moins bon vaut mieux qu'une séance
    amputée du cinquième de sa durée.
    """
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50), mauvais=2.0)
    longueur = _fin_de_seance(720.0) + 5.0
    # Le retour au calme prescrit : exactement de quoi rentrer depuis le
    # décalage nul, donc un écart de 0 % à cet endroit-là.
    calme_s = _vitesse(PUISSANCE_Z2) * 720.0 / _vitesse(PUISSANCE_CALME)

    resultat = placement.placer(_seance_calme(calme_s), _trace_de_longueur(longueur), P)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(0.0), (
        "le placement retenu doit être celui qui tient la séance, pas celui qui la tronque"
    )
    assert resultat.note_terrain == pytest.approx(1.0), (
        "le premier bloc tombe hors du bon couloir (note 2), le second dedans (note 0) : "
        "moyenne pondérée par des durées égales, 1,0"
    )
    assert resultat.penalite_seance == pytest.approx(0.0), "cette séance-là est tenue en entier"
    assert resultat.note_totale == pytest.approx(1.0)
    assert not any("retour au calme" in a for a in resultat.avertissements)


def test_un_retour_au_calme_a_zero_se_paie_et_se_dit(monkeypatch):
    """Le même tracé, mais le décalage tronqué imposé : ce qu'il coûte.

    L'élasticité réduite au seul +20 % force le placement que la correction
    écarte. Il note toujours 0 sur le terrain — et c'est bien le piège — mais
    porte une pénalité de séance non tenue hors de proportion, et l'avertissement
    du lot précédent est toujours là : on note, on ne refuse pas.
    """
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50), mauvais=2.0)
    longueur = _fin_de_seance(720.0) + 5.0
    calme_s = _vitesse(PUISSANCE_Z2) * 720.0 / _vitesse(PUISSANCE_CALME)

    resultat = placement.placer(
        _seance_calme(calme_s), _trace_de_longueur(longueur), P, elasticite=(0.20, 0.20)
    )

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert resultat.note_terrain == pytest.approx(0.0), "le terrain sous les blocs est parfait"
    # Écart de −100 % pour une fenêtre réduite à +20 % : 1,20 hors de la fenêtre.
    assert resultat.penalite_seance == pytest.approx(
        placement.PENALITE_SEANCE_NON_TENUE * 1.20, rel=0.01
    ), "la pénalité se compte hors de la fenêtre, au prorata"
    assert resultat.note_totale == pytest.approx(
        resultat.note_terrain + resultat.penalite_seance
    )
    assert any("retour au calme" in a and "-100%" in a for a in resultat.avertissements), (
        f"l'avertissement du lot précédent doit rester : {resultat.avertissements}"
    )


def test_un_retour_au_calme_hors_fenetre_se_dit(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    # Tracé bien trop long pour la séance : le retour au calme s'étire.
    resultat = placement.placer(_seance(), _trace(120_000.0), P)

    assert resultat is not None
    assert any("retour au calme" in a for a in resultat.avertissements)


# --- refus ----------------------------------------------------------------------


def test_seance_trop_longue_pour_le_trace(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    trace = _trace(20_000.0)

    assert placement.placer(_seance(), trace, P) is None
    motif = trace.meta[placement.CLE_MOTIF]
    assert "ne tient pas" in motif
    assert "20.0 km" in motif
    assert "décalages essayés" in motif


def test_seance_vide_et_trace_degenere(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    vide = Seance(nom="vide", jour=date(2026, 9, 13), etapes=[], duree_s=0.0, meta={})
    trace = _trace()
    assert placement.placer(vide, trace, P) is None
    assert "sans étape" in trace.meta[placement.CLE_MOTIF]

    point = Trace(
        nom="point",
        points=[PointTrace(0.0, 0.0, None, 0.0)],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    assert placement.placer(_seance(), point, P) is None
    assert "deux points" in point.meta[placement.CLE_MOTIF]


def test_le_motif_disparait_quand_le_placement_reussit(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    trace = _trace()
    trace.meta[placement.CLE_MOTIF] = "vieux motif"

    assert placement.placer(_seance(), trace, P) is not None
    assert placement.CLE_MOTIF not in trace.meta


# --- cas dégradés ----------------------------------------------------------------


def test_etape_sans_puissance_cible_se_dit(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    etapes = list(_seance().etapes)
    etapes[2] = _etape("recuperation", 4, None)
    seance = Seance(
        nom="sans puissance",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert any("aucune puissance cible" in a for a in resultat.avertissements)


def test_seance_sans_z2_elastiques(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    etapes = [
        _etape("echauffement", 60, PUISSANCE_Z2),
        _etape("bloc", 20, PUISSANCE_BLOC),
    ]
    seance = Seance(
        nom="sans élastique",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert resultat.decalage_z2_s == 0.0
    assert any("aucune Z2 d'ouverture élastique" in a for a in resultat.avertissements)
    assert any("aucun retour au calme élastique" in a for a in resultat.avertissements)


def test_un_trace_en_pente_change_les_positions(monkeypatch):
    """La pente entre bien dans le modèle : à 1 %, on avance moins loin."""
    appels_plat = _couloirs(monkeypatch, (0.0, 1e9))
    plat = placement.placer(_seance(), _trace(), P, elasticite=(0.0, 0.0))
    assert plat is not None
    assert appels_plat

    appels_cote = _couloirs(monkeypatch, (0.0, 1e9))
    cote = placement.placer(_seance(), _trace(pente=0.01), P, elasticite=(0.0, 0.0))
    assert cote is not None
    assert appels_cote
    assert cote.emplacements[0].debut_m < plat.emplacements[0].debut_m
    assert cote.emplacements[0].longueur_m < plat.emplacements[0].longueur_m

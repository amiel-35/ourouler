"""Tests de `seance.placement` : la séance posée sur le tracé.

Les fonctions de terrain sont remplacées par `monkeypatch` dans chaque test :
on veut un terrain dont on connaît la réponse, pas le vrai. Les **modules**,
eux, sont importés normalement.

Ce fichier a porté, le temps que les lots L4.1 et L4.2 s'écrivent en
parallèle, un mécanisme de doubles qui installait de faux
`ourouler.noyau.seance` et `ourouler.seance.terrain` dans `sys.modules` quand
les vrais ne s'importaient pas. Il est retiré : son `except ModuleNotFoundError`
n'attrapait pas seulement « le module n'existe pas encore » mais aussi « le
module existe et un de ses imports a disparu », et il aurait alors installé
silencieusement un `evaluer_couloir` qui rend toujours 0 et une
`demi_tour_faisable` qui dit toujours oui — vingt-quatre tests au vert contre
une production cassée.

Aucune coordonnée réelle : le tracé est une ligne droite au large du golfe de
Guinée, comme les autres tracés synthétiques du dépôt. Aucun réseau.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from ourouler.noyau.seance import Etape, Seance
from ourouler.noyau.trace import PointTrace, Trace, distance_m
from ourouler.physique.modele import Parametres, vitesse_regime
from ourouler.seance import pas_trace, placement, placement_note, placement_resultat
from ourouler.seance.terrain import PENALITE_BLOC_TRONQUE, POIDS_KM_BATI, NoteBloc

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

    Rend la liste des couloirs évalués — début, longueur et **puissance
    donnée** — pour vérifier ce qui a été noté, à quelle intensité, et surtout
    ce qui ne l'a pas été.
    """
    appels: list[tuple[float, float, float | None, float | None]] = []

    def evaluer_couloir(
        trace,
        debut_m: float,
        longueur_m: float,
        *,
        puissance_w: float | None = None,
        ftp_w: float | None = None,
    ) -> NoteBloc:
        appels.append((debut_m, longueur_m, puissance_w, ftp_w))
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


def _seance_recups_inegales() -> Seance:
    """Deux blocs séparés par des récupérations **de durées différentes**, sans Z2 de fin.

    Sans retour au calme élastique, `duree_totale_s` est entièrement prescrite :
    c'est la somme des durées des étapes plus le décalage de la Z2 d'ouverture,
    et rien d'autre. Toute seconde en plus ou en moins est une récupération qui
    a bougé.

    Les deux récupérations sont inégales (4 min et 7 min) : un étirement
    *uniforme* n'est pas le seul défaut possible, et un test qui ne compare que
    deux placements entre eux ne verrait pas une récup étirée « quand ça
    arrange ».
    """
    etapes = [
        _etape("echauffement", 40, PUISSANCE_Z2, elastique=True),
        _etape("bloc", 8, PUISSANCE_BLOC),
        _etape("recuperation", 4, PUISSANCE_RECUP),
        _etape("bloc", 8, PUISSANCE_BLOC),
        _etape("recuperation", 7, PUISSANCE_RECUP),
        _etape("bloc", 8, PUISSANCE_BLOC),
    ]
    return Seance(
        nom="3x8 à récups inégales",
        jour=date(2026, 9, 13),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )


def _terrain_vallonne(monkeypatch, *, demi_tour: bool = False):
    """Un terrain dont la note varie vite le long du tracé, sans trou ni plateau.

    C'est la condition pour que le test morde : sur un terrain uniforme, étirer
    une récupération ne rapporte rien et un placement tricheur n'aurait aucune
    raison de le faire. Ici la note oscille tous les ~700 m, donc décaler le
    bloc suivant de quelques centaines de mètres change sa note — la tentation
    est permanente.
    """
    import math as _math

    def evaluer_couloir(
        trace,
        debut_m: float,
        longueur_m: float,
        *,
        puissance_w: float | None = None,
        ftp_w: float | None = None,
    ) -> NoteBloc:
        milieu = debut_m + longueur_m / 2.0
        return NoteBloc(
            note=5.0 * _math.sin(milieu / 700.0) ** 2,
            motifs=[],
            pente_moyenne=0.0,
            pente_max=0.0,
            carrefours=0,
            km_batis=0.0,
            descente_m=0.0,
            montee_m=0.0,
        )

    monkeypatch.setattr(placement, "evaluer_couloir", evaluer_couloir)
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: demi_tour)
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: demi_tour)


@pytest.mark.parametrize("demi_tour", [False, True], ids=["tout_droit", "demi_tours_permis"])
def test_aucune_duree_de_recuperation_ne_bouge_quel_que_soit_le_decalage(monkeypatch, demi_tour):
    """Règle (b) du mainteneur : « aucune récupération ne bouge, jamais ».

    L'invariant n'avait aucun test dédié : il n'était vérifié qu'indirectement,
    et un placement qui essaierait chaque récupération à sa durée prescrite
    **et** à ×1,2 en gardant la mieux notée passait toute la suite au vert.

    Ici la séance n'a pas de retour au calme élastique : `duree_totale_s` est
    donc entièrement prescrite — la somme des durées plus le décalage de la Z2
    d'ouverture, à la seconde près. Le terrain est volontairement vallonné pour
    qu'une variante étirée soit tentante à chaque bloc.
    """
    _terrain_vallonne(monkeypatch, demi_tour=demi_tour)
    seance = _seance_recups_inegales()
    prescrite = sum(e.duree_s for e in seance.etapes)

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert resultat.duree_totale_s == pytest.approx(
        prescrite + resultat.decalage_z2_s, abs=1.0
    ), (
        f"{resultat.duree_totale_s:.0f} s roulées pour {prescrite + resultat.decalage_z2_s:.0f} s "
        f"prescrites (décalage compris) : une durée non élastique a bougé de "
        f"{resultat.duree_totale_s - prescrite - resultat.decalage_z2_s:+.0f} s"
    )
    # Les durées de la prescription elle-même n'ont pas été réécrites en place.
    assert [e.duree_s for e in seance.etapes] == [
        e.duree_s for e in _seance_recups_inegales().etapes
    ]


def test_l_ecart_entre_deux_blocs_vaut_exactement_la_recuperation_prescrite(monkeypatch):
    """La même règle, mesurée en mètres plutôt qu'en secondes.

    Sur un tracé plat, la vitesse de récupération est constante : l'écart le
    long du tracé entre la fin d'un bloc et le début du suivant vaut donc
    exactement `vitesse(récup) × durée prescrite`. Deux récupérations inégales,
    donc deux écarts différents : un étirement d'une seule des deux se voit.
    """
    _terrain_vallonne(monkeypatch, demi_tour=False)
    seance = _seance_recups_inegales()

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert len(resultat.blocs()) == 3
    recups = [e for e in seance.etapes if e.type == "recuperation"]
    for numero, (recup, avant, apres) in enumerate(
        zip(recups, resultat.blocs()[:-1], resultat.blocs()[1:], strict=True), start=1
    ):
        attendu = _vitesse(PUISSANCE_RECUP) * recup.duree_s
        mesure = apres.debut_m - (avant.debut_m + avant.longueur_m)
        assert mesure == pytest.approx(attendu, abs=5.0), (
            f"récupération {numero} : {mesure:.0f} m roulés pour {attendu:.0f} m prescrits "
            f"({recup.duree_s / 60:.0f} min à {_vitesse(PUISSANCE_RECUP) * 3.6:.1f} km/h)"
        )


# --- l'asymétrie des deux pénalités de séance (point produit 2 de la relecture) ---

#: Les deux formes de séance de référence, réduites à ce qui pèse dans la
#: comparaison : la durée de chaque bloc et celle du retour au calme prescrit.
#: Aucune donnée personnelle — un 2×20' et un 4×8' sont des structures
#: d'entraînement courantes, les durées ci-dessous sont celles de la forme, pas
#: d'un fichier du mainteneur.
FORMES_DE_REFERENCE = (
    ("2x20 + 4x3", (1200.0, 1200.0, 180.0, 180.0, 180.0, 180.0), 1200.0),
    ("4x40s + 5 + 4x8", (40.0, 40.0, 40.0, 40.0, 300.0, 480.0, 480.0, 480.0, 480.0), 2400.0),
)

#: Le retard qu'on compare : rentrer vingt minutes après l'heure prescrite.
RETARD_S = 20 * 60.0

#: Les deux fenêtres d'élasticité par défaut, désormais distinctes (Q14) : la
#: Z2 d'ouverture est un levier de placement et reste étroite, le retour au
#: calme absorbe et s'ouvre largement vers le haut.
ELASTICITE = (-0.05, 0.20)
ELASTICITE_CALME = (-0.05, 1.5)


def _note_du_village(durees: tuple[float, ...], *, km_batis: float = 1.0) -> float:
    """Ce que coûte 1 km de village traversé pendant le **plus long** bloc.

    C'est-à-dire ce que la note de terrain pondérée par la durée retient d'un
    défaut franc sous le bloc qui compte le plus dans la séance.
    """
    etapes = [_etape("bloc", duree / 60.0, PUISSANCE_BLOC) for duree in durees]
    pire = max(range(len(durees)), key=lambda i: durees[i])
    emplacements = [
        placement.Emplacement(
            etape_idx=i,
            debut_m=0.0,
            longueur_m=1000.0,
            demi_tour=False,
            note=NoteBloc(
                note=(POIDS_KM_BATI * km_batis) if i == pire else 0.0,
                motifs=[],
                pente_moyenne=0.0,
                pente_max=0.0,
                carrefours=0,
                km_batis=km_batis if i == pire else 0.0,
                descente_m=0.0,
                montee_m=0.0,
            ),
        )
        for i in range(len(durees))
    ]
    return placement._note_ponderee(emplacements, etapes)


def _calme(ecart: float, depassement_s: float = 0.0) -> placement._EcartElastique:
    """Un retour au calme tel qu'il a été placé, dans la forme attendue par la pénalité."""
    return placement._EcartElastique(ecart=ecart, depassement_s=depassement_s, absorbe=True)


def _cout_du_retard(retard_s: float, calme_s: float) -> float:
    """Ce que coûte un retour au calme qui dure `retard_s` de plus que prescrit."""
    return placement._penalite_seance(
        [_calme(ecart=retard_s / calme_s, depassement_s=retard_s)], ELASTICITE, ELASTICITE_CALME
    )


@pytest.mark.parametrize(
    ("nom", "durees", "calme_s"), FORMES_DE_REFERENCE, ids=[f[0] for f in FORMES_DE_REFERENCE]
)
def test_un_village_sous_un_bloc_coute_plus_cher_qu_un_retour_de_vingt_minutes(
    nom, durees, calme_s
):
    """Q14 : rentrer plus tard doit rester bien moins cher qu'un défaut de terrain franc.

    Le mainteneur, 13/09 : « le retour au calme en fait peut dépasser de plus,
    c'est souvent ce que je fais car c'est incontrôlable de faire parfait, et
    c'est du kilomètre facile. » L'arbitrage est donc posé dans ce sens-là : le
    défaut de terrain, qu'on subit pendant un bloc, doit coûter plus que le
    retard, qui n'est que du kilomètre facile en plus.

    La comparaison est faite sur les **durées réelles** des deux séances de
    référence, et sur les mêmes fonctions que la production (`_penalite_seance`
    et `_note_ponderee`), pas sur une arithmétique refaite ici.
    """
    retard = _cout_du_retard(RETARD_S, calme_s)
    village = _note_du_village(durees)
    assert retard < village / 2, (
        f"{nom} : rentrer 20 min en retard coûte {retard:.2f} km équivalent, traverser "
        f"1 km de village pendant le bloc le plus long en coûte {village:.2f} — "
        "le retard doit rester très loin derrière, pas le disputer"
    )


@pytest.mark.parametrize(
    ("nom", "durees", "calme_s"), FORMES_DE_REFERENCE, ids=[f[0] for f in FORMES_DE_REFERENCE]
)
def test_le_depassement_du_retour_au_calme_se_paie_des_la_premiere_minute(nom, durees, calme_s):
    """Q14, l'autre moitié : « faut réduire le dépassement au max. »

    Aucun seuil, donc : le coût court dès la première minute en trop, et il
    est proportionnel. C'est ce qui fait qu'à terrain égal la boucle la plus
    juste gagne — avec une marche, les deux étaient à égalité parfaite en deçà
    de la fenêtre et le tri retombait sur l'ordre des candidates.
    """
    dix, vingt, quarante = (_cout_du_retard(n * 60.0, calme_s) for n in (10, 20, 40))
    assert dix > 0.0, "un dépassement de 10 minutes doit déjà coûter quelque chose"
    assert dix == pytest.approx(0.10) and vingt == pytest.approx(0.20)
    assert quarante == pytest.approx(0.40), "le coût est proportionnel, sans palier"
    # Et il ne dépend pas de la durée prescrite : 20 min de trop, c'est 20 min
    # de trop, que le retour au calme prescrit dure 20 ou 40 minutes.
    assert vingt == pytest.approx(_cout_du_retard(20 * 60.0, 2 * calme_s))
    # Même le dépassement le plus large reste sous un défaut de terrain franc.
    assert quarante < _note_du_village(durees)


@pytest.mark.parametrize(
    ("nom", "durees", "calme_s"), FORMES_DE_REFERENCE, ids=[f[0] for f in FORMES_DE_REFERENCE]
)
def test_une_seance_tronquee_coute_plus_cher_qu_un_bloc_mutile(nom, durees, calme_s):
    """L'autre bord : amputer la séance doit rester le défaut le plus cher.

    C'est tout l'objet de `PENALITE_SEANCE_NON_TENUE`, que Q14 laisse intact,
    et la borne basse est nommée : `terrain.PENALITE_BLOC_TRONQUE`, ce que
    coûte un bloc qui ne tient pas du tout sur le tracé. Un retour au calme
    supprimé doit coûter plus que ça, sans quoi tronquer la séance redevient
    une option.
    """
    supprime = placement._penalite_seance(  # retour au calme à 0 min
        [_calme(ecart=-1.0)], ELASTICITE, ELASTICITE_CALME
    )
    assert supprime > PENALITE_BLOC_TRONQUE, (
        f"{nom} : supprimer le retour au calme coûte {supprime:.1f}, un bloc qui ne tient "
        f"pas sur le tracé en coûte {PENALITE_BLOC_TRONQUE:.1f} — tronquer la séance redevient "
        "moins cher que de renoncer à un bloc"
    )
    # Et il reste plus cher que le pire terrain franc mesurable sous les blocs.
    assert supprime > 4 * _note_du_village(durees, km_batis=1.0)


def test_les_deux_penalites_de_seance_restent_dans_le_bon_ordre():
    """Raccourcir la séance coûte plus cher que l'allonger, et de très loin.

    Allonger fait rentrer plus tard — « c'est du kilomètre facile » ; raccourcir
    supprime de la séance. Un coût de dépassement qui rattraperait celui du
    raccourcissement rendrait les deux défauts équivalents, ce qu'ils ne sont
    pas. Les deux ne se mesurent même pas dans la même unité : le premier en
    kilomètres équivalents par heure de trop, le second en part de séance
    manquante.
    """
    heure_de_trop = placement_note.PENALITE_CALME_ALLONGE_KM_PAR_H
    calme_supprime = placement._penalite_seance([_calme(ecart=-1.0)], ELASTICITE, ELASTICITE_CALME)
    assert heure_de_trop < calme_supprime / 10
    # Et une heure entière de trop reste sous le poids brut d'un défaut de
    # terrain franc sous un bloc : un kilomètre de village, avant pondération.
    assert heure_de_trop < POIDS_KM_BATI


def test_la_fenetre_du_retour_au_calme_ne_facture_pas_le_depassement():
    """La fenêtre haute dit, elle ne facture pas — sinon le seuil revient.

    Deux fenêtres très différentes, le même dépassement : le même coût. Ce qui
    change au-delà de la fenêtre, c'est le ton du message (voir `_fermer`), pas
    l'addition.
    """
    etroite = placement._penalite_seance(
        [_calme(ecart=1.0, depassement_s=1200.0)], ELASTICITE, (-0.05, 0.20)
    )
    large = placement._penalite_seance(
        [_calme(ecart=1.0, depassement_s=1200.0)], ELASTICITE, (-0.05, 1.5)
    )
    assert etroite == pytest.approx(large) == pytest.approx(0.20)


# --- le décalage de la Z2 d'ouverture -----------------------------------------


def test_le_decalage_va_chercher_le_seul_bon_couloir(monkeypatch):
    # Le bon couloir est exactement là où la séance tombe avec +20 % d'échauffement.
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert resultat.note_terrain == 0.0
    # Le retour au calme dépasse de deux minutes sur ce tracé : depuis Q14 cela
    # se paie sans seuil, donc la note n'est plus exactement nulle — mais deux
    # minutes valent deux centièmes de kilomètre équivalent.
    assert resultat.penalite_seance < 0.05
    assert resultat.note_totale == pytest.approx(resultat.penalite_seance)
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]
    assert resultat.blocs()[0].debut_m == pytest.approx(attendues[0], abs=1.0)
    assert resultat.blocs()[1].debut_m == pytest.approx(attendues[2], abs=1.0)
    assert [e.etape_idx for e in resultat.blocs()] == [1, 3]


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
    assert "hors du bon couloir" in resultat.blocs()[0].note.motifs
    assert resultat.blocs()[1].note.motifs == []


def test_pas_plus_grand_que_la_marge_essaie_quand_meme_les_bornes(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(_seance(), _trace(), P, pas_s=10_000.0)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert resultat.note_terrain == 0.0
    assert resultat.penalite_seance < 0.05  # deux minutes de retour au calme en trop


def test_pas_s_absurde_ne_boucle_pas(monkeypatch):
    _couloirs(monkeypatch, (0.0, 1e9))
    for pas in (0.0, -60.0, float("nan"), float("inf"), 1e-3):
        resultat = placement.placer(_seance(), _trace(), P, pas_s=pas)
        assert resultat is not None


# --- l'invariant de continuité (Q13) ------------------------------------------
#
# Les emplacements se suivent sans trou ni recouvrement, du
# départ à l'arrivée, et la somme de leurs longueurs vaut `distance_totale_m`
# — au sens du parcours réellement roulé, demi-tours compris. C'est ce qui
# prouve qu'on montre toute la séance et pas des morceaux. Rejoué sur une
# séance tout droit et une séance à demi-tour.


def _verifier_continuite(resultat: placement.Placement, seance: Seance) -> None:
    """Toutes les étapes, dans l'ordre, sans trou ni recouvrement en distance roulée.

    Vérifie `debut_parcouru_m` lui-même, pas seulement la somme des
    longueurs : un `debut_parcouru_m` resté à 0.0 par défaut (un champ
    oublié à un site de construction) laisserait passer la somme — la
    longueur totale ne dépend pas de l'endroit où chaque étape *dit* qu'elle
    commence, seulement de combien elle dit avoir roulé.
    """
    assert [e.etape_idx for e in resultat.emplacements] == list(range(len(seance.etapes))), (
        "chaque étape de la séance doit apparaître une fois, dans l'ordre : "
        f"{[e.etape_idx for e in resultat.emplacements]}"
    )
    parcouru = 0.0
    for emplacement in resultat.emplacements:
        assert math.isfinite(emplacement.longueur_m) and emplacement.longueur_m >= 0.0, (
            f"étape {emplacement.etape_idx} : longueur {emplacement.longueur_m!r} invalide"
        )
        assert emplacement.debut_parcouru_m == pytest.approx(parcouru, abs=1e-6), (
            f"étape {emplacement.etape_idx} : debut_parcouru_m = "
            f"{emplacement.debut_parcouru_m:.3f} m, attendu {parcouru:.3f} m — le compteur "
            "ne suit pas la somme des longueurs déjà roulées"
        )
        parcouru += emplacement.longueur_m
    assert parcouru == pytest.approx(resultat.distance_totale_m, abs=1e-6), (
        f"la somme des longueurs affichées ({parcouru:.3f} m) ne vaut pas la distance "
        f"réellement roulée ({resultat.distance_totale_m:.3f} m) : la séance affichée "
        "n'est pas la séance roulée"
    )


def test_invariant_continuite_sans_demi_tour(monkeypatch):
    """Placement tout droit : cinq étapes, aucun trou, la somme fait le compte."""
    seance = _seance()
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert not any(e.demi_tour for e in resultat.emplacements), (
        "cette fixture ne doit pas provoquer de demi-tour, sinon elle double ce que "
        "l'autre test vérifie"
    )
    _verifier_continuite(resultat, seance)


def test_invariant_continuite_avec_demi_tour(monkeypatch):
    """La récupération coupée en deux par un demi-tour reste une seule étape.

    Elle roule deux fois la demi-distance (aller, puis retour) : sa longueur
    compte donc pour `2 × besoin_m`, pas pour l'écart entre les deux points du
    tracé (qui sous-compterait de moitié) ni pour zéro (départ et arrivée sont
    le même point). L'invariant ne tiendrait pas sinon.
    """
    seance = _seance()
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))

    resultat = placement.placer(seance, _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.blocs()] == [False, True], (
        "cette fixture a besoin du demi-tour pour avoir quelque chose à vérifier"
    )
    _verifier_continuite(resultat, seance)

    # Et le détail qui prouve que ce n'est pas un accident de la somme globale :
    # la récupération du demi-tour (étape 2) roule bien deux fois sa moitié.
    recup = next(e for e in resultat.emplacements if e.etape_idx == 2)
    bloc1 = next(e for e in resultat.emplacements if e.etape_idx == 1)
    tournant = resultat.jalons_m[1]
    aller = tournant - (bloc1.debut_m + bloc1.longueur_m)
    assert aller > 100.0, "la fixture doit laisser une demi-récup franche, sinon c'est du bruit"
    assert recup.longueur_m == pytest.approx(2.0 * aller, abs=1.0), (
        f"la récupération du demi-tour roule {recup.longueur_m:.0f} m, attendu "
        f"{2 * aller:.0f} m (aller + retour)"
    )


def test_invariant_continuite_avec_recuperations_inegales(monkeypatch):
    """Trois blocs, deux récupérations de durées différentes : toujours pas de trou."""
    seance = _seance_recups_inegales()
    _terrain_vallonne(monkeypatch, demi_tour=False)

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    _verifier_continuite(resultat, seance)


def test_le_compteur_de_debut_est_strictement_croissant_avec_demi_tour(monkeypatch):
    """Le test qui protège l'affichage : le compteur ne recule ni ne stagne.

    `debut_m` — une position sur le tracé — recule après un demi-tour : les
    blocs 2, 3 et 4 d'une même paire récup-bloc reprise en boucle peuvent
    tomber au même kilomètre de tracé, ou plus bas. Affiché tel quel à un
    cycliste, « km 11,4 » qui revient deux fois de suite est indiscernable
    d'un moteur cassé — c'est le défaut que le mainteneur a signalé sur la
    carte du 01/09. `debut_parcouru_m`, lui, ne doit jamais reculer ni
    stagner : c'est le compteur du vélo, pas la géométrie du tracé.
    """
    seance = _seance()
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))

    resultat = placement.placer(seance, _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.blocs()] == [False, True], (
        "cette fixture a besoin du demi-tour pour avoir quelque chose à vérifier"
    )
    debuts_tracee = [e.debut_m for e in resultat.emplacements]
    assert len(set(round(d, 3) for d in debuts_tracee)) < len(debuts_tracee), (
        "cette fixture doit faire reculer debut_m quelque part (deux étapes au même "
        "kilomètre de tracé), sinon elle ne distingue pas debut_m de debut_parcouru_m"
    )

    compteurs = [e.debut_parcouru_m for e in resultat.emplacements]
    for avant, apres in zip(compteurs[:-1], compteurs[1:], strict=True):
        assert apres > avant, (
            f"le compteur recule ou stagne : {avant:.1f} m puis {apres:.1f} m — "
            f"suite complète : {[round(c, 1) for c in compteurs]}"
        )


# --- le demi-tour --------------------------------------------------------------


def test_demi_tour_choisi_quand_il_n_y_a_qu_un_bon_segment(monkeypatch):
    # Le bon couloir ne fait la longueur que d'un seul bloc.
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))

    resultat = placement.placer(_seance(), _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    assert resultat.decalage_z2_s == pytest.approx(720.0)
    assert [e.demi_tour for e in resultat.blocs()] == [False, True]
    # Le second bloc reprend exactement le segment du premier, en sens inverse.
    premier, second = resultat.blocs()
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
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]
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

    def evaluer_couloir(
        trace,
        debut_m: float,
        longueur_m: float,
        *,
        puissance_w: float | None = None,
        ftp_w: float | None = None,
    ) -> NoteBloc:
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
    assert [e.demi_tour for e in sous_activation.blocs()] == [False, False]
    assert [e.demi_tour for e in sous_bloc_long.blocs()] == [False, False]
    # Un seul bloc est sali dans chaque cas, et c'est le bon.
    assert [e.note.note for e in sous_activation.blocs()] == [MAUVAIS, 0.0]
    assert [e.note.note for e in sous_bloc_long.blocs()] == [0.0, MAUVAIS]

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
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]


def test_demi_tour_refuse_en_cote(monkeypatch):
    """« Un tronçon marche dans les deux sens sur du plat, mais en côte » non."""
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50), pente=0.04)

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]


def test_la_penalite_de_demi_tour_peut_le_rendre_moins_interessant(monkeypatch):
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50), mauvais=0.5)

    resultat = placement.placer(_seance(), _trace(), P, penalite_demi_tour=1.0)

    assert resultat is not None
    # Un couloir moyen tout droit (0,5) coûte moins qu'un bon couloir repris à
    # l'envers (0 + 1,0) : on reste tout droit.
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]


# --- ce que la récupération ne subit pas ---------------------------------------


def test_aucune_recuperation_n_est_evaluee(monkeypatch):
    """La règle produit du sprint : une récup n'est jamais notée, à aucun titre.

    Deux façons de la trahir, et les deux sont gardées ici : évaluer un couloir
    de la longueur d'une récupération, et — depuis que le prix d'une descente
    dépend de l'intensité (13/09) — évaluer un couloir **à la puissance d'une
    récupération**. La seconde ferait entrer l'intensité d'une récup dans une
    note de terrain, ce qui est le même défaut sous un autre nom.
    """
    appels = _couloirs(monkeypatch, (0.0, 1e9))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    longueur_bloc = _vitesse(PUISSANCE_BLOC) * 1200.0
    assert appels, "aucun couloir évalué"
    for _debut, longueur, puissance, _ftp in appels:
        assert longueur == pytest.approx(longueur_bloc, abs=1.0)
        assert puissance == pytest.approx(PUISSANCE_BLOC), (
            "un couloir a été noté à une autre puissance que celle du bloc"
        )
    assert all(p != pytest.approx(PUISSANCE_RECUP) for _, _, p, _ in appels)


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
    assert resultat.penalite_seance == pytest.approx(0.0, abs=0.01), (
        "cette séance-là est tenue en entier : il ne reste que l'arrondi du placement"
    )
    assert resultat.note_totale == pytest.approx(1.0, abs=0.01)
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
    # Écart de −100 % pour une fenêtre de retour au calme qui descend à −5 % :
    # 0,95 hors de la fenêtre. L'élasticité de l'ouverture, réduite ici à
    # +20 % pour forcer le placement, n'entre pas dans ce calcul : depuis Q14
    # les deux fenêtres sont distinctes.
    assert resultat.penalite_seance == pytest.approx(
        placement_note.PENALITE_SEANCE_NON_TENUE * 0.95, rel=0.01
    ), "la pénalité se compte hors de la fenêtre du retour au calme, au prorata"
    assert resultat.note_totale == pytest.approx(
        resultat.note_terrain + resultat.penalite_seance
    )
    assert any(
        "retour au calme raccourci" in a and "-100%" in a for a in resultat.avertissements
    ), f"l'avertissement du lot précédent doit rester, et garder son ⚠ : {resultat.avertissements}"
    assert not resultat.informations, (
        "une séance amputée n'est pas une information neutre (Q14)"
    )


def test_un_retour_au_calme_tres_au_dela_de_sa_fenetre_reste_un_avertissement(monkeypatch):
    """Au-delà de la fenêtre haute, ce n'est plus la boucle qui tombe mal.

    Q14 laisse un ⚠ dans exactement deux cas : la séance amputée, et le
    dépassement qui sort de la fenêtre — à ce point-là, c'est la boucle qui ne
    va pas avec la séance, et c'est un choix de boucle à refaire.
    """
    _couloirs(monkeypatch, (0.0, 1e9))
    # Tracé bien trop long pour la séance : le retour au calme s'étire.
    resultat = placement.placer(_seance(), _trace(120_000.0), P)

    assert resultat is not None
    dits = [a for a in resultat.avertissements if "retour au calme" in a]
    assert len(dits) == 1, resultat.avertissements
    assert "au-delà de la fenêtre" in dits[0]
    assert "km de plus à allure facile" in dits[0], dits[0]
    assert not any("retour au calme" in i for i in resultat.informations), (
        "hors fenêtre, c'est un avertissement et rien d'autre"
    )


def test_un_retour_au_calme_qui_s_allonge_dans_sa_fenetre_est_une_information(monkeypatch):
    """Q14, le ton : « c'est du kilomètre facile » ne se dit pas avec un ⚠.

    Le mainteneur, 13/09 : « le retour au calme en fait peut dépasser de plus,
    c'est souvent ce que je fais car c'est incontrôlable de faire parfait ».
    Un retour au calme qui s'allonge dans sa fenêtre n'est donc pas un défaut :
    c'est une information, rangée à part pour que l'affichage ne lui colle pas
    un ⚠ — et elle se dit en kilomètres, pas en pourcentage de dépassement.
    """
    _couloirs(monkeypatch, (0.0, 1e9))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert not any("retour au calme" in a for a in resultat.avertissements), (
        f"rentrer un peu plus tard n'est pas une alerte : {resultat.avertissements}"
    )
    dits = [i for i in resultat.informations if "retour au calme" in i]
    assert len(dits) == 1, resultat.informations
    assert "⚠" not in dits[0]
    assert "au lieu des 30 prescrites" in dits[0], dits[0]
    assert "de plus à allure facile" in dits[0], dits[0]


def test_a_terrain_egal_le_placement_qui_deborde_le_moins_gagne(monkeypatch):
    """Q14 : « faut réduire le dépassement au max. » — et sans seuil, sinon rien ne départage.

    Terrain uniformément parfait : la note de terrain ne dit rien, tous les
    décalages sont à égalité. Avant Q14, la marche de l'ancienne pénalité les
    laissait exactement à égalité tant qu'on restait dans la fenêtre, et le
    départage retombait sur « le décalage qui touche le moins à la séance »,
    c'est-à-dire zéro — en laissant le retour au calme déborder le plus.
    Maintenant le dépassement se paie dès la première minute : le levier de
    placement sert à le réduire, et le placement retenu est celui qui rentre le
    plus près de l'heure prescrite.
    """
    _couloirs(monkeypatch, (0.0, 1e9))

    retenu = placement.placer(_seance(), _trace(), P)
    fige = placement.placer(_seance(), _trace(), P, elasticite=(0.0, 0.0))

    assert retenu is not None and fige is not None
    assert retenu.note_terrain == fige.note_terrain == 0.0, "le terrain ne départage rien ici"
    assert retenu.decalage_z2_s == pytest.approx(720.0), (
        "la Z2 d'ouverture est allongée au maximum pour raccourcir le retour au calme"
    )
    assert 0.0 < retenu.penalite_seance < fige.penalite_seance, (
        "le placement retenu dépasse moins, et ce moindre dépassement est ce qui l'a fait gagner"
    )
    assert retenu.duree_totale_s < fige.duree_totale_s, (
        "moins de dépassement, c'est aussi rentrer plus tôt : la même distance est "
        "roulée à l'allure de la Z2 plutôt qu'à celle du retour au calme"
    )


# --- le parcours réellement roulé -----------------------------------------------


def _boucle_carree(cote_m: float = 20_000.0, pas_m: float = 500.0) -> Trace:
    """Un carré fermé de `4 × cote_m`, plat, au large du golfe de Guinée.

    Une vraie boucle, pas une ligne droite : le parcours rendu doit recoller
    des morceaux qui tournent, pas seulement des longitudes croissantes.
    """
    n = int(cote_m // pas_m)
    cotes = ((1, 0), (0, 1), (-1, 0), (0, -1))  # est, nord, ouest, sud
    x = y = 0.0
    points = [PointTrace(lat=0.0, lon=0.0, alt_m=100.0, dist_m=0.0)]
    for dx, dy in cotes:
        for _ in range(n):
            x, y = x + dx * pas_m, y + dy * pas_m
            points.append(
                PointTrace(
                    lat=y * DEG_PAR_M,
                    lon=x * DEG_PAR_M,
                    alt_m=100.0,
                    dist_m=points[-1].dist_m + pas_m,
                )
            )
    return Trace(
        nom="carré d'essai",
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


def _point_du_parcours(parcours: Trace, distance_m_: float) -> PointTrace:
    """Le point du parcours à `distance_m_` du départ, interpolé."""
    return pas_trace._point_a(parcours.points, [p.dist_m for p in parcours.points], distance_m_)


def test_le_parcours_place_contient_le_demi_tour(monkeypatch):
    """Défaut mesuré le 22/04 : le GPX écrit ne contenait aucun aller-retour.

    Une boucle fabriquée, un seul bon couloir de la longueur d'un bloc : le
    placement fait demi-tour, et le parcours rendu doit faire la distance
    **placée**, pas celle de la boucle, en repassant exactement sur ses pas.
    """
    attendues = _positions(720.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[1] + 50))
    trace = _boucle_carree()

    resultat = placement.placer(_seance(), trace, P, penalite_demi_tour=1.0)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.blocs()] == [False, True], (
        "ce test a besoin du demi-tour pour avoir quelque chose à vérifier"
    )
    assert len(resultat.jalons_m) == 3, f"un demi-tour, donc trois jalons : {resultat.jalons_m}"

    parcours = placement_resultat.trace_parcourue(resultat, trace)

    assert parcours.distance_m == pytest.approx(resultat.distance_totale_m, rel=0.01), (
        f"parcours de {parcours.distance_m:.0f} m pour une séance placée sur "
        f"{resultat.distance_totale_m:.0f} m : ce n'est pas ce qui sera roulé"
    )
    assert parcours.distance_m != pytest.approx(trace.distance_m, rel=0.01), (
        "le parcours ne peut pas faire la longueur de la boucle : on a fait demi-tour"
    )
    # On revient sur ses pas : de part et d'autre du demi-tour, mêmes points.
    demi_tour_m = resultat.jalons_m[1]
    for ecart in (50.0, 500.0, 2_000.0, 5_000.0):
        avant = _point_du_parcours(parcours, demi_tour_m - ecart)
        apres = _point_du_parcours(parcours, demi_tour_m + ecart)
        assert distance_m(avant, apres) < 1.0, (
            f"à {ecart:.0f} m du demi-tour, le retour passe à {distance_m(avant, apres):.1f} m "
            "de l'aller : le parcours ne revient pas sur ses pas"
        )
    # Et le premier point du parcours est bien le départ de la boucle.
    assert distance_m(parcours.points[0], trace.points[0]) < 1.0


def test_un_parcours_sans_demi_tour_redonne_le_trace(monkeypatch):
    """Sans demi-tour, le parcours est la boucle elle-même, du départ à l'arrivée."""
    _couloirs(monkeypatch, (0.0, 1e9))
    trace = _boucle_carree()

    resultat = placement.placer(_seance(), trace, P)

    assert resultat is not None
    assert [e.demi_tour for e in resultat.blocs()] == [False, False]
    parcours = placement_resultat.trace_parcourue(resultat, trace)
    assert parcours.distance_m == pytest.approx(trace.distance_m, rel=0.001)
    assert parcours.distance_m == pytest.approx(resultat.distance_totale_m, rel=0.01)


def test_un_placement_sans_jalons_rend_le_trace_tel_quel(monkeypatch):
    """Un `Placement` construit à la main ne dit pas ce qui a été roulé : on n'invente pas."""
    trace = _boucle_carree()
    nu = placement.Placement(
        decalage_z2_s=0.0,
        emplacements=[],
        note_totale=0.0,
        duree_totale_s=0.0,
        distance_totale_m=0.0,
    )
    assert placement_resultat.trace_parcourue(nu, trace) is trace


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
    assert cote.blocs()[0].debut_m < plat.blocs()[0].debut_m
    assert cote.blocs()[0].longueur_m < plat.blocs()[0].longueur_m


# --- l'intensité du bloc atteint l'évaluation du terrain -----------------------


def test_la_ftp_de_la_seance_atteint_l_evaluation_du_terrain(monkeypatch):
    """Décision du 13/09 : le prix d'une descente dépend de la zone du bloc.

    Le placement doit donc donner à `evaluer_couloir` la puissance du bloc
    **et** la FTP de la séance — celle qui a produit les watts des étapes,
    rangée dans `meta["ftp_w"]` par `seance.intervals`. Sans elle, le facteur
    de zone resterait neutre sans que personne ne s'en aperçoive.
    """
    appels = _couloirs(monkeypatch, (0.0, 1e9))
    seance = _seance()
    seance.meta["ftp_w"] = 258.0

    resultat = placement.placer(seance, _trace(), P)

    assert resultat is not None
    assert appels
    assert all(ftp == pytest.approx(258.0) for _, _, _, ftp in appels)


def test_une_seance_sans_ftp_n_en_invente_pas(monkeypatch):
    appels = _couloirs(monkeypatch, (0.0, 1e9))

    resultat = placement.placer(_seance(), _trace(), P)

    assert resultat is not None
    assert appels
    assert all(ftp is None for _, _, _, ftp in appels)


@pytest.mark.parametrize(
    ("meta", "attendu"),
    [
        ({}, None),
        ({"ftp_w": None}, None),
        ({"ftp_w": 0.0}, None),
        ({"ftp_w": -258.0}, None),
        ({"ftp_w": float("nan")}, None),
        ({"ftp_w": True}, None),
        ({"ftp_w": "illisible"}, None),
        ({"ftp_w": 258}, 258.0),
        ({"ftp_w": 258.0}, 258.0),
    ],
)
def test_ftp_de_ne_rend_qu_une_ftp_exploitable(meta, attendu):
    seance = _seance()
    seance.meta = dict(meta)
    assert placement.ftp_de(seance) == attendu


# --- le vent dans le placement (lot L5.1) --------------------------------------
#
# Le tracé d'essai est une ligne droite plein **est** : cap 90°. Un vent
# « d'est » (`vent_depuis_deg = 90`) est donc plein face, un vent « d'ouest »
# (270°) plein dos. Les deux sont la même mesure vue des deux côtés.

CAP_TRACE_DEG = 90.0


def _champ_vent(vent_kmh: float, vent_depuis_deg: float, *, longueur_m: float = 80_000.0):
    """Un champ de vent uniforme sur tout le tracé d'essai."""
    from ourouler.boucle.meteo_trace import Echantillon
    from ourouler.seance.vent import ChampVent

    echantillons = [
        Echantillon(
            dist_m=d,
            t=datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
            lat=0.0,
            lon=d * DEG_PAR_M,
            cap_deg=CAP_TRACE_DEG,
            pluie_mm=0.0,
            vent_kmh=vent_kmh,
            vent_relatif=None,
            ressenti_c=14.0,
            vent_depuis_deg=vent_depuis_deg,
        )
        for d in (0.0, longueur_m / 2.0, longueur_m)
    ]
    return ChampVent(echantillons)


def test_le_defaut_de_vent_vaut_bien_none(monkeypatch):
    """Ne pas passer `vent` et passer `vent=None` donnent le même placement.

    **Ce test ne prouve pas la non-régression**, et son nom précédent le
    laissait croire : il compare `placer` à lui-même, donc les deux branches
    bougeraient ensemble si le lot L5.1 avait déplacé quoi que ce soit. Ce
    qu'il garde vraiment, c'est que le paramètre par défaut est bien `None` et
    qu'aucun chemin caché ne fabrique un champ de vent implicite.

    La vraie non-régression est ailleurs, et elle est dure : un `GOLDEN` de
    positions figées avant le lot, comparé à l'égalité exacte, dans
    `tests/adversarial/test_adv_vent_placement.py` (relevé sur `b311d88` puis
    rejoué à l'identique en relecture).
    """
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    trace = _trace()
    sans_parametre = placement.placer(_seance(), trace, P)
    avec_none = placement.placer(_seance(), _trace(), P, vent=None)
    assert sans_parametre is not None and avec_none is not None
    assert [e.debut_m for e in avec_none.blocs()] == [
        e.debut_m for e in sans_parametre.blocs()
    ]
    assert avec_none.distance_totale_m == sans_parametre.distance_totale_m
    assert avec_none.duree_totale_s == sans_parametre.duree_totale_s
    assert avec_none.note_totale == sans_parametre.note_totale


def test_un_champ_de_vent_nul_vaut_labsence_de_vent(monkeypatch):
    """0 km/h de vent et « vent non pris en compte » donnent le même placement."""
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    sans = placement.placer(_seance(), _trace(), P, vent=None)
    nul = placement.placer(_seance(), _trace(), P, vent=_champ_vent(0.0, 90.0))
    assert sans is not None and nul is not None
    assert [e.debut_m for e in nul.blocs()] == [e.debut_m for e in sans.blocs()]
    assert nul.distance_totale_m == pytest.approx(sans.distance_totale_m)


def test_le_vent_de_face_raccourcit_le_couloir_dun_bloc(monkeypatch):
    """Un bloc de 20 min couvre moins de route face au vent, davantage dans le dos.

    C'est la mesure qui motive tout le lot. Elle ne se lit pas sur la distance
    totale — le retour au calme absorbe et le tracé d'essai s'arrête de toute
    façon à son dernier point — mais sur la **longueur du couloir** que le
    bloc occupe : c'est elle que le placement va chercher sur le terrain.
    """
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    sans = placement.placer(_seance(), _trace(), P, vent=None)
    face = placement.placer(_seance(), _trace(), P, vent=_champ_vent(20.0, CAP_TRACE_DEG))
    dos = placement.placer(_seance(), _trace(), P, vent=_champ_vent(20.0, CAP_TRACE_DEG + 180.0))
    assert sans is not None and face is not None and dos is not None
    longueurs = [p.blocs()[0].longueur_m for p in (face, sans, dos)]
    assert longueurs[0] < longueurs[1] < longueurs[2]
    # 20 km/h de vent valent plus de deux kilomètres d'écart sur un bloc de 20 min.
    assert longueurs[2] - longueurs[0] > 2_000.0


def test_le_vent_deplace_le_debut_des_blocs(monkeypatch):
    """Un vent de face pendant l'échauffement pose le premier bloc plus tôt sur le tracé."""
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    sans = placement.placer(_seance(), _trace(), P, vent=None)
    face = placement.placer(_seance(), _trace(), P, vent=_champ_vent(20.0, CAP_TRACE_DEG))
    assert sans is not None and face is not None
    assert face.blocs()[0].debut_m < sans.blocs()[0].debut_m - 500.0


def test_un_vent_de_travers_ne_change_rien(monkeypatch):
    """Approximation assumée : `vitesse_regime` ne connaît qu'une composante longitudinale."""
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    sans = placement.placer(_seance(), _trace(), P, vent=None)
    travers = placement.placer(_seance(), _trace(), P, vent=_champ_vent(40.0, CAP_TRACE_DEG + 90.0))
    assert sans is not None and travers is not None
    assert travers.distance_totale_m == pytest.approx(sans.distance_totale_m, abs=1.0)


def test_un_vent_inconnu_ne_vaut_pas_un_vent_nul(monkeypatch):
    """Le champ le dit par `complet`, et l'appelant peut écrire « vent non pris en compte »."""
    from ourouler.boucle.meteo_trace import Echantillon
    from ourouler.seance.vent import ChampVent

    inconnus = [
        Echantillon(
            dist_m=d,
            t=datetime(2026, 9, 15, 8, 0, tzinfo=UTC),
            lat=0.0,
            lon=d * DEG_PAR_M,
            cap_deg=CAP_TRACE_DEG,
            pluie_mm=None,
            vent_kmh=None,
            vent_relatif=None,
            ressenti_c=None,
            vent_depuis_deg=None,
        )
        for d in (0.0, 80_000.0)
    ]
    champ = ChampVent(inconnus)
    assert champ.complet is False

    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    sans = placement.placer(_seance(), _trace(), P, vent=None)
    inconnu = placement.placer(_seance(), _trace(), P, vent=champ)
    assert sans is not None and inconnu is not None
    assert inconnu.distance_totale_m == pytest.approx(sans.distance_totale_m)


# --- la mémoïsation du vent ----------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [(0.0, 0.0), (-0.0, 0.0), (0.1, 0.0), (0.13, 0.25), (0.37, 0.25), (-1.6, -1.5), (3.0, 3.0)],
)
def test_le_vent_sarrondit_au_quart_de_metre_par_seconde(brut: float, attendu: float):
    """Sans arrondi, aucune clé de cache ne serait jamais réutilisée."""
    assert pas_trace._arrondir_vent(brut) == pytest.approx(attendu)
    assert str(pas_trace._arrondir_vent(brut))[0] != "-" or attendu < 0


def test_la_cle_de_memoisation_porte_le_vent():
    """Deux vents différents sur le même pas ne doivent pas rendre la même vitesse."""
    terrain = placement._Terrain(_trace(longueur_m=2_000.0), P)
    lente = terrain.vitesse(PUISSANCE_BLOC, 0.0, 3.0)
    rapide = terrain.vitesse(PUISSANCE_BLOC, 0.0, -3.0)
    neutre = terrain.vitesse(PUISSANCE_BLOC, 0.0)
    assert lente < neutre < rapide
    assert len(terrain._vitesses) == 3


def test_le_cache_de_vitesse_sert_encore_avec_du_vent(monkeypatch):
    """Le placement avec vent ne doit pas faire exploser le nombre de clés.

    Un tracé de 80 km fait 800 pas ; avec 2 sens et 4 puissances, une clé par
    (pas, sens, puissance) ferait 6 400 entrées. L'arrondi du vent et le
    terrain plat les ramènent à une poignée.
    """
    attendues = _positions(0.0)
    _couloirs(monkeypatch, (attendues[0] - 50, attendues[3] + 50))
    trace = _trace()
    terrain = placement._Terrain(trace, P, _champ_vent(20.0, CAP_TRACE_DEG))
    for _ in range(50):
        terrain.avancer(0.0, 1, 600.0, PUISSANCE_BLOC)
    assert len(terrain._vitesses) <= 8


# --- le cap de chaque pas ------------------------------------------------------


def test_le_cap_de_chaque_pas_suit_le_trace():
    """Le tracé d'essai va plein est : tous les caps valent 90°."""
    terrain = placement._Terrain(_trace(longueur_m=3_000.0), P)
    assert len(terrain.caps) == len(terrain.pentes)
    assert all(cap == pytest.approx(90.0, abs=0.5) for cap in terrain.caps)


# --- le signe du vent doit survivre au branchement, pas seulement au calcul ------
#
# `_Terrain.vitesse(210, 0, ±5)` reçoit un vent déjà signé : elle ne voit rien
# de ce qui s'est passé en amont. Un `sens` oublié en chemin, ou recollé à
# l'envers entre `ChampVent` et `vitesse_regime`, passerait tous les tests
# unitaires du champ de vent sans qu'aucun ne bronche. Ces deux-là vérifient
# donc la chaîne entière, depuis `placer`.


def test_le_terrain_transmet_bien_le_sens_au_champ_de_vent():
    """Le même pas, parcouru dans les deux sens, doit rendre des vents opposés."""
    terrain = placement._Terrain(_trace(longueur_m=5_000.0), P, _champ_vent(36.0, CAP_TRACE_DEG))
    aller = terrain.vent_face(10, 1)
    retour = terrain.vent_face(10, -1)
    assert aller > 0  # cap est, vent d'est : de face
    assert retour == pytest.approx(-aller)


def test_un_demi_tour_change_le_vent_de_face_en_vent_de_dos(monkeypatch):
    """Le bloc repris en sens inverse doit être plus long que celui de l'aller.

    Figure du demi-tour : bloc à l'aller, demi-récup, demi-tour, demi-récup,
    même bloc en sens inverse. Avec un vent de face à l'aller, le retour se
    fait vent dans le dos : à durée identique, le second bloc couvre plus de
    route. Si le `sens` n'était pas transmis — ou transmis à l'envers — les
    deux couloirs feraient la même longueur, ou l'inverse.
    """
    vent = _champ_vent(25.0, CAP_TRACE_DEG)

    # Premier passage, tout droit, pour savoir où le bloc 1 tombe réellement
    # avec ce vent-là : la borne du bon couloir se déduit de la mesure plutôt
    # que d'une position devinée qui ne vaudrait que pour un vent nul.
    _couloirs(monkeypatch, (0.0, 1e9))
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: False)
    droit = placement.placer(_seance(), _trace(), P, vent=vent)
    assert droit is not None
    borne = droit.blocs()[0].debut_m + droit.blocs()[0].longueur_m + 200.0

    # Second passage : au-delà de `borne`, tout est mauvais. Le bloc 2 ne peut
    # être bien noté qu'en revenant sur ses pas — la figure du demi-tour.
    _couloirs(monkeypatch, (0.0, borne))
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: True)
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: True)
    resultat = placement.placer(
        _seance(), _trace(), P, vent=vent, penalite_demi_tour=0.0, pas_s=120.0
    )
    assert resultat is not None
    demi_tours = [e for e in resultat.blocs() if e.demi_tour]
    assert demi_tours, "le terrain devait rendre le demi-tour indispensable"
    aller = resultat.blocs()[0]
    for retour in demi_tours:
        assert retour.longueur_m > aller.longueur_m


def test_le_vent_de_dos_mene_plus_loin_que_le_vent_de_face_a_travers_placer():
    """De bout en bout, sans terrain factice : la géométrie seule doit suffire.

    Aucun `monkeypatch` ici — le vrai `evaluer_couloir` tourne. Ce qu'on
    mesure n'est pas la note mais la distance atteinte au bout de la séance,
    et elle ne peut venir que du modèle physique nourri par le bon signe.
    """
    face = placement.placer(_seance(), _trace(), P, vent=_champ_vent(25.0, CAP_TRACE_DEG))
    dos = placement.placer(_seance(), _trace(), P, vent=_champ_vent(25.0, CAP_TRACE_DEG + 180.0))
    assert face is not None and dos is not None
    fin_face = face.blocs()[-1].debut_m + face.blocs()[-1].longueur_m
    fin_dos = dos.blocs()[-1].debut_m + dos.blocs()[-1].longueur_m
    assert fin_dos > fin_face + 5_000.0


# --- le garde-fou du tracé de longueur nulle -------------------------------------


def test_un_trace_de_deux_points_confondus_est_refuse_sans_planter():
    """Le motif était déjà écrit, mais la construction du terrain levait avant lui.

    `_Terrain` divise par la longueur de chaque pas pour en tirer la pente :
    sur un tracé de 0 m, c'était une `ZeroDivisionError` nue au lieu du refus
    lisible que `placer` avait prévu deux lignes plus bas.
    """
    point = PointTrace(lat=0.0, lon=0.0, alt_m=100.0, dist_m=0.0)
    trace = Trace(
        nom="deux fois le même point",
        points=[point, point],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    assert placement.placer(_seance(), trace, P) is None
    assert "longueur nulle" in str(trace.meta[placement.CLE_MOTIF])

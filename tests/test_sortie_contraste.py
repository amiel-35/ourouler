"""Trois propositions contrastées : les axes, les marges, le recouvrement, les phrases.

Toutes les traces sont **fabriquées** autour de (0.0, 0.0), en pleine mer dans
le golfe de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1
et 3).

Ce que ces tests doivent attraper, et qui est le point dur du lot : une
proposition qui entre dans le trio **sans avoir de phrase**, et deux
propositions qui se ressemblent sur la carte malgré des notes très
différentes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pytest

from ourouler.boucle.meteo_trace import Echantillon, MeteoTrace
from ourouler.boucle.trace import PointTrace, Segment, Trace
from ourouler.sortie import contraste
from ourouler.sortie.contraste import (
    AXE_DEMI_TOURS,
    AXE_DUREE,
    AXE_TERRAIN,
    AXE_TRAFIC,
    AXE_VENT,
    AXE_VILLE,
    PAS_DUREE_S,
    PAS_MARQUEURS_KM,
    PAS_PLUIE_MM,
    PAS_TERRAIN_KM_EQ,
    PAS_TRAFIC_PART,
    SEUIL_RECOUVREMENT,
    Profil,
    choisir,
    orientation_au_vent,
)
from ourouler.sortie.orientation import (
    ORIENTATION_DEPART_DOS,
    ORIENTATION_FACE,
    ORIENTATION_RETOUR_DOS,
    ORIENTATION_TRAVERS,
)

DEGRE_M = math.radians(1.0) * 6_371_000.0
PAS_M = 100.0


# --- fabriques ----------------------------------------------------------------


def droite(longueur_m: float, *, lat: float = 0.0, depart_m: float = 0.0) -> Trace:
    """Une ligne droite plein est, décalée en latitude pour ne rien partager."""
    nombre = int(round(longueur_m / PAS_M)) + 1
    points = [
        PointTrace(
            lat=lat,
            lon=(depart_m + i * PAS_M) / DEGRE_M,
            alt_m=100.0,
            dist_m=i * PAS_M,
        )
        for i in range(nombre)
    ]
    segments = [
        Segment(i, i + 1, PAS_M, {"highway": "tertiary"}, node_tags={})
        for i in range(nombre - 1)
    ]
    return Trace(
        nom="essai",
        points=points,
        segments=segments,
        distance_m=points[-1].dist_m,
        denivele_m=0.0,
        temps_moteur_s=None,
    )


@dataclass
class FauxPlacement:
    duree_totale_s: float
    note_terrain: float


@dataclass
class FausseProposition:
    """Le strict minimum de l'interface de `sortie.commande.Proposition`."""

    numero: int
    trace: Trace
    placement: FauxPlacement
    demi_tours: int
    meteo: MeteoTrace | None = None
    part_connue: float | None = None


#: Durée prescrite de la séance de référence de ces tests, en secondes.
#: L'axe de la durée compare l'écart **à cette valeur**, pas les durées nues :
#: sans quoi la candidate qui ampute la séance gagne l'axe.
DUREE_SEANCE_S = 7200.0


def profil(**kw) -> Profil:
    """Un profil de référence. `duree_s` fixe le dépassement, sauf s'il est donné.

    Écrire `profil(duree_s=DUREE_SEANCE_S + 600)` veut donc dire « une sortie
    qui rentre 10 min plus tard que prévu », et non « une sortie de 2 h 10 »
    dans l'absolu — c'est bien l'écart qui porte l'axe.
    """
    base = {
        "duree_s": DUREE_SEANCE_S,
        "demi_tours": 0,
        "note_terrain": 0.0,
        "pluie_mm": 0.0,
        "densite_marqueurs_km": 2.0,
        "part_trafic": 0.40,
        "orientation": None,
    }
    champs = {**base, **kw}
    champs.setdefault("depassement_s", champs["duree_s"] - DUREE_SEANCE_S)
    # Par défaut, une sortie plus courte que la prescription d'au moins une
    # minute est traitée comme amputée : c'est ce que le placement dirait, et
    # ces tests n'ont pas de placement. `seance_amputee=` reste passable
    # explicitement pour le cas de l'arrondi.
    champs.setdefault("seance_amputee", champs["depassement_s"] < -60.0)
    return Profil(**champs)


def selection_de(profils: list[Profil], *, traces: list[Trace] | None = None):
    """Appelle `choisir` sur des profils imposés, avec des tracés disjoints par défaut.

    Les tracés sont décalés en latitude d'un degré (≈ 111 km) : leur
    recouvrement est nul par construction, ce qui isole la condition sur les
    axes de la condition sur les routes communes.
    """
    traces = traces or [droite(50_000.0, lat=float(i)) for i in range(len(profils))]
    propositions = [
        FausseProposition(
            numero=i + 1,
            trace=t,
            placement=FauxPlacement(p.duree_s, p.note_terrain),
            demi_tours=p.demi_tours,
        )
        for i, (p, t) in enumerate(zip(profils, traces, strict=True))
    ]
    par_id = dict(zip((id(p) for p in propositions), profils, strict=True))
    vrai = contraste.profil
    contraste.profil = lambda proposition, meteo=None, **_: par_id[id(proposition)]
    try:
        return choisir(propositions), propositions
    finally:
        contraste.profil = vrai


# --- la marge est dans l'unité de l'axe, jamais un pourcentage de note ---------


def test_un_ecart_de_duree_sous_le_pas_ne_distingue_pas():
    selection, _ = selection_de(
        [
            profil(duree_s=7200.0),
            profil(duree_s=7200.0 + PAS_DUREE_S - 1),
        ]
    )
    assert len(selection.retenues) == 1
    assert "une marge perceptible" in (selection.motif_deux_propositions or "")


def test_un_ecart_de_duree_au_pas_distingue_si_l_autre_gagne_un_axe():
    selection, _ = selection_de(
        [
            profil(duree_s=7200.0, part_trafic=0.50),
            profil(duree_s=7200.0 + PAS_DUREE_S, part_trafic=0.50 - PAS_TRAFIC_PART),
        ]
    )
    assert [r.axe_distinctif for r in selection.retenues] == [AXE_DUREE, AXE_TRAFIC]
    assert selection.retenues[0].distinction == "10 minutes de moins"
    assert selection.retenues[1].distinction == "elle évite les grands axes"


@pytest.mark.parametrize(
    ("champ", "pas", "axe"),
    [
        ("densite_marqueurs_km", PAS_MARQUEURS_KM, AXE_VILLE),
        ("part_trafic", PAS_TRAFIC_PART, AXE_TRAFIC),
        ("pluie_mm", PAS_PLUIE_MM, "pluie"),
        ("note_terrain", PAS_TERRAIN_KM_EQ, AXE_TERRAIN),
    ],
)
def test_chaque_axe_numerique_a_sa_marge(champ, pas, axe):
    """Juste sous le pas, rien ; au pas, l'axe est gagné."""
    haut = {"densite_marqueurs_km": 3.0, "part_trafic": 0.5, "pluie_mm": 2.0, "note_terrain": 4.0}[
        champ
    ]
    trop_peu, _ = selection_de(
        [profil(**{champ: haut - pas + pas / 100}), profil(**{champ: haut}, duree_s=7200.0)]
    )
    assert len(trop_peu.retenues) == 1
    assez, _ = selection_de(
        [
            profil(**{champ: haut - pas}, duree_s=7200.0 + PAS_DUREE_S),
            profil(**{champ: haut}, duree_s=7200.0),
        ]
    )
    assert {r.axe_distinctif for r in assez.retenues} == {axe, AXE_DUREE}


# --- condition a) : chacune la meilleure sur un axe, et un axe différent ------


def test_une_candidate_sans_aucun_axe_gagne_n_entre_pas_dans_le_trio():
    """Elle est dominée partout : elle n'a rien à dire, donc elle n'existe pas."""
    selection, _ = selection_de(
        [
            profil(duree_s=6000.0, part_trafic=0.20),
            profil(duree_s=9000.0, part_trafic=0.60),  # pire partout
            profil(duree_s=7800.0, densite_marqueurs_km=0.5),
        ]
    )
    numeros = [r.proposition.numero for r in selection.retenues]
    assert 2 not in numeros


def test_deux_candidates_ne_peuvent_pas_gagner_le_meme_axe():
    """Le meilleur d'un axe est unique : deux propositions ne s'y partagent pas."""
    selection, _ = selection_de(
        [profil(duree_s=7200.0), profil(duree_s=7200.0 + 3 * PAS_DUREE_S)]
    )
    assert len(selection.retenues) == 1


def test_la_premiere_du_tri_est_toujours_proposee():
    selection, propositions = selection_de([profil(), profil(duree_s=1.0)])
    assert selection.retenues[0].proposition is propositions[0]


# --- condition c) : le recouvrement de routes ---------------------------------


def test_deux_boucles_qui_partagent_trop_de_route_ne_sont_pas_contrastees():
    """Le critère du mainteneur : mêmes routes = mêmes propositions, quelles que
    soient les notes."""
    commune = droite(50_000.0, lat=0.0)
    selection, _ = selection_de(
        [
            profil(duree_s=7200.0),
            profil(duree_s=7200.0 + 3 * PAS_DUREE_S, part_trafic=0.1),
        ],
        traces=[commune, commune],
    )
    assert len(selection.retenues) == 1
    assert f"{SEUIL_RECOUVREMENT:.0%}" in (selection.motif_deux_propositions or "")


def test_le_recouvrement_des_retenues_est_publie():
    selection, _ = selection_de(
        [
            profil(duree_s=7200.0, part_trafic=0.50),
            profil(duree_s=7200.0 + PAS_DUREE_S, part_trafic=0.50 - PAS_TRAFIC_PART),
        ]
    )
    assert selection.recouvrements[(0, 1)] == pytest.approx(0.0, abs=1e-9)


# --- le vent : un axe par orientation -----------------------------------------


def test_trois_orientations_differentes_font_trois_propositions():
    """L'exemple que le contrat donne lui-même en §3.1 doit être expressible."""
    selection, _ = selection_de(
        [
            profil(orientation=ORIENTATION_RETOUR_DOS),
            profil(orientation=ORIENTATION_DEPART_DOS),
            profil(orientation=ORIENTATION_TRAVERS),
        ]
    )
    assert [r.distinction for r in selection.retenues] == [
        "vous rentrez avec le vent dans le dos",
        "vent dans le dos au départ, vous rentrez dans le dur",
        "vent de travers, ni répit ni mur",
    ]
    assert all(contraste.axe_de_base(r.axe_distinctif) == AXE_VENT for r in selection.retenues)


def test_deux_candidates_de_meme_orientation_ne_gagnent_pas_le_vent():
    selection, _ = selection_de(
        [profil(orientation=ORIENTATION_TRAVERS), profil(orientation=ORIENTATION_TRAVERS)]
    )
    assert len(selection.retenues) == 1


def test_un_vent_inconnu_ne_distingue_rien_et_ne_penalise_rien():
    """L'ignorance ne fait gagner personne — et ne fait perdre personne non plus."""
    selection, _ = selection_de(
        [
            profil(orientation=None, duree_s=7200.0),
            profil(orientation=ORIENTATION_TRAVERS, duree_s=7200.0 + PAS_DUREE_S),
        ]
    )
    # La seconde gagne le vent (elle est seule de son orientation), la première
    # la durée : deux propositions, et l'inconnue n'a rien coûté à personne.
    assert len(selection.retenues) == 2
    assert selection.retenues[0].axe_distinctif == AXE_DUREE


# --- les demi-tours -----------------------------------------------------------


def test_aucun_demi_tour_se_dit_quand_les_autres_en_ont():
    selection, _ = selection_de(
        [
            profil(demi_tours=2, duree_s=7200.0),
            profil(demi_tours=0, duree_s=7200.0 + PAS_DUREE_S),
        ]
    )
    phrases = {r.axe_distinctif: r.distinction for r in selection.retenues}
    assert phrases[AXE_DEMI_TOURS] == "aucun demi-tour"


# --- une mesure inconnue ne fait jamais gagner --------------------------------


def test_une_densite_inconnue_ne_gagne_pas_l_axe_de_la_ville():
    """`None` veut dire « on ne sait pas » : ce n'est ni un zéro ni un avantage."""
    sujet = profil(densite_marqueurs_km=None)
    autre = profil(densite_marqueurs_km=5.0)
    assert AXE_VILLE not in contraste._axes_gagnes(sujet, [autre])
    assert AXE_VILLE not in contraste._axes_gagnes(autre, [sujet])


# --- l'orientation au vent ----------------------------------------------------


def meteo_trace(lot: list[Echantillon]) -> MeteoTrace:
    """Un `MeteoTrace` dont seuls les échantillons comptent ici."""
    return MeteoTrace(
        echantillons=lot,
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=None,
        confiance=None,
    )


def echantillons(vent_kmh: float, directions: list[float]) -> MeteoTrace:
    """Un échantillon tous les 5 km, cap plein est, direction de vent imposée."""
    lot = [
        Echantillon(
            dist_m=i * 5_000.0,
            t=None,
            lat=0.0,
            lon=0.0,
            cap_deg=90.0,
            pluie_mm=0.0,
            vent_kmh=vent_kmh,
            vent_relatif=None,
            ressenti_c=None,
            vent_depuis_deg=d,
        )
        for i, d in enumerate(directions)
    ]
    return meteo_trace(lot)


def test_vent_de_dos_a_la_fin_se_nomme_retour_dos():
    # Cap plein est (90°) : vent venant de l'ouest (270°) est dans le dos.
    meteo = echantillons(20.0, [90.0, 90.0, 180.0, 270.0, 270.0])
    assert orientation_au_vent(meteo) == ORIENTATION_RETOUR_DOS


def test_vent_de_dos_au_depart_se_nomme_depart_dos():
    meteo = echantillons(20.0, [270.0, 270.0, 180.0, 90.0, 90.0])
    assert orientation_au_vent(meteo) == ORIENTATION_DEPART_DOS


def test_vent_perpendiculaire_partout_se_nomme_travers():
    meteo = echantillons(20.0, [180.0] * 5)
    assert orientation_au_vent(meteo) == ORIENTATION_TRAVERS


def test_vent_de_face_aux_deux_bouts_se_nomme_face():
    meteo = echantillons(20.0, [90.0, 90.0, 180.0, 90.0, 90.0])
    assert orientation_au_vent(meteo) == ORIENTATION_FACE


def test_un_vent_trop_faible_n_a_pas_d_orientation():
    """« Pas de vent » n'est pas « vent de travers » : les deux rendent zéro de
    composante de face, mais un seul se sent."""
    meteo = echantillons(3.0, [180.0] * 5)
    assert orientation_au_vent(meteo) is None


def test_sans_meteo_l_orientation_est_inconnue():
    assert orientation_au_vent(None) is None
    assert orientation_au_vent(meteo_trace([])) is None


# --- cas dégénérés ------------------------------------------------------------


def test_aucune_candidate_rend_une_selection_vide_avec_son_motif():
    selection = choisir([])
    assert selection.retenues == []
    assert selection.motif_deux_propositions


def test_une_seule_candidate_est_rendue_sans_phrase():
    selection, _ = selection_de([profil()])
    assert len(selection.retenues) == 1
    assert selection.retenues[0].distinction == ""
    assert "1 candidate(s)" in (selection.motif_deux_propositions or "")


# --- l'axe de la durée porte l'écart à la séance, pas la durée nue ------------
#
# Le défaut que ces tests gardent fermé, relevé par les tests adversariaux du
# 17/09/2026 : l'axe comparait les durées brutes, donc la candidate qui
# amputait le plus la séance gagnait — et recevait la phrase « 71 minutes de
# moins », présentée comme un avantage. Une phrase est une affirmation ;
# celle-là était fausse de la pire façon, parce qu'elle était flatteuse.


def test_une_seance_amputee_ne_gagne_jamais_l_axe_de_la_duree():
    """Le cas exact du testeur : 2 905 s pour une séance de 7 200."""
    amputee = profil(duree_s=2905.0)
    entiere = profil(duree_s=7151.0, seance_amputee=False)
    assert AXE_DUREE not in contraste._axes_gagnes(amputee, [entiere])
    assert AXE_DUREE in contraste._axes_gagnes(entiere, [amputee])


def test_la_phrase_d_une_seance_amputee_ne_vante_jamais_sa_brieveté():
    selection, _ = selection_de(
        [profil(duree_s=7151.0, seance_amputee=False), profil(duree_s=2905.0)]
    )
    phrases = [r.distinction for r in selection.retenues]
    assert "71 minutes de moins" not in phrases, phrases
    assert not any("minutes de moins" in p for p in phrases if p), phrases


def test_amputer_de_vingt_minutes_vaut_depasser_de_vingt_minutes():
    """L'axe est un écart en valeur absolue : les deux ratent la cible d'autant.

    Mais seule celle qui tient la séance peut gagner l'axe — l'amputation est
    déjà payée par `PENALITE_SEANCE_NON_TENUE`.
    """
    court = profil(duree_s=DUREE_SEANCE_S - 1200.0)
    long_ = profil(duree_s=DUREE_SEANCE_S + 1200.0)
    assert court.ecart_duree_s == long_.ecart_duree_s == 1200.0
    assert court.seance_tenue is False
    assert long_.seance_tenue is True


def test_depasser_moins_gagne_l_axe():
    """Deux sorties qui tiennent la séance : la plus proche de la cible gagne."""
    juste = profil(duree_s=DUREE_SEANCE_S + 60.0)
    longue = profil(duree_s=DUREE_SEANCE_S + 60.0 + PAS_DUREE_S)
    assert AXE_DUREE in contraste._axes_gagnes(juste, [longue])
    assert AXE_DUREE not in contraste._axes_gagnes(longue, [juste])


def test_la_phrase_dit_la_plus_proche_quand_l_autre_est_plus_courte_mais_amputee():
    """Le gagnant n'est pas le plus court du groupe : « X minutes de moins »
    serait faux, et on ne le dit pas."""
    selection, _ = selection_de(
        [
            profil(duree_s=DUREE_SEANCE_S + 60.0, part_trafic=0.50),
            profil(duree_s=DUREE_SEANCE_S - 3000.0, part_trafic=0.50 - PAS_TRAFIC_PART),
        ]
    )
    par_axe = {r.axe_distinctif: r.distinction for r in selection.retenues}
    assert par_axe.get(AXE_DUREE) == "la plus proche de la durée prévue"


def test_un_arrondi_de_moins_d_une_minute_n_est_pas_une_amputation():
    """Le placement seul décide : 49 s de moins que la prescription, avec un
    retour au calme entier, reste une séance tenue."""
    juste = profil(duree_s=DUREE_SEANCE_S - 49.0, seance_amputee=False)
    # Deux pas d'écart : l'axe se mesure entre |−49 s| et |+20 min|, soit
    # 1 151 s — au-dessus du pas. À un seul pas, les deux se vaudraient, et
    # c'est normal : 49 s de moins et 10 min de plus, ça n'est pas 10 min
    # d'écart pour le cycliste.
    longue = profil(duree_s=DUREE_SEANCE_S + 2 * PAS_DUREE_S)
    assert juste.seance_tenue is True
    assert AXE_DUREE in contraste._axes_gagnes(juste, [longue])


def test_sans_duree_de_seance_l_axe_de_la_duree_est_inconnu_et_non_faux():
    """Mieux vaut un axe qui ne distingue rien qu'un axe qui ment."""
    sujet = Profil(duree_s=3600.0, demi_tours=0, note_terrain=0.0)
    autre = Profil(duree_s=9000.0, demi_tours=0, note_terrain=0.0)
    assert sujet.ecart_duree_s is None
    assert AXE_DUREE not in contraste._axes_gagnes(sujet, [autre])
    assert AXE_DUREE not in contraste._axes_gagnes(autre, [sujet])

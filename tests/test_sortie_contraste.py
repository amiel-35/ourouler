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


def profil(**kw) -> Profil:
    base = {
        "duree_s": 7200.0,
        "demi_tours": 0,
        "note_terrain": 0.0,
        "pluie_mm": 0.0,
        "densite_marqueurs_km": 2.0,
        "part_trafic": 0.40,
        "orientation": None,
    }
    return Profil(**{**base, **kw})


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
    contraste.profil = lambda proposition, meteo=None: par_id[id(proposition)]
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

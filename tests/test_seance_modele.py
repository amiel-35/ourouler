"""Tests de `seance.modele` (lot L4.1).

Aucune donnée réelle : toutes les séances sont fabriquées ici.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.seance.modele import (
    TYPES,
    ZONES_PUISSANCE_DEFAUT,
    Etape,
    Seance,
)


def etape(type_="bloc", duree=480.0, bas=250.0, haut=270.0, **kw) -> Etape:
    return Etape(type=type_, duree_s=duree, puissance_min_w=bas, puissance_max_w=haut, **kw)


# --- Etape --------------------------------------------------------------------


def test_les_quatre_types_du_contrat():
    assert TYPES == ("echauffement", "bloc", "recuperation", "calme")


def test_puissance_cible_est_le_milieu_de_la_fourchette():
    assert etape(bas=200.0, haut=260.0).puissance_cible_w == 230.0


def test_puissance_cible_avec_une_seule_borne_connue():
    assert etape(bas=200.0, haut=None).puissance_cible_w == 200.0
    assert etape(bas=None, haut=260.0).puissance_cible_w == 260.0


def test_puissance_cible_absente_quand_aucune_borne():
    assert etape(bas=None, haut=None).puissance_cible_w is None


def test_les_bornes_sont_remises_dans_l_ordre():
    """Une rampe descendante arrive avec start > end : la fourchette reste lisible."""
    e = etape(bas=240.0, haut=140.0)
    assert (e.puissance_min_w, e.puissance_max_w) == (140.0, 240.0)
    assert e.puissance_cible_w == 190.0


def test_un_type_inconnu_est_refuse():
    with pytest.raises(ErreurUtilisateur, match="type d'étape"):
        etape(type_="sprint")


def test_une_duree_negative_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="durée négative"):
        etape(duree=-1.0)


def test_une_duree_non_finie_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="fini"):
        etape(duree=float("inf"))


def test_une_puissance_negative_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="négative"):
        etape(bas=-10.0, haut=None)


def test_une_puissance_non_finie_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="fini"):
        etape(bas=float("nan"), haut=None)


def test_duree_nulle_acceptee_par_le_modele():
    """Le filtrage des durées nulles est le rôle du lecteur, pas du modèle."""
    assert etape(duree=0.0).duree_s == 0.0


@pytest.mark.parametrize("type_", ["bloc", "recuperation"])
def test_seules_les_z2_des_extremites_sont_elastiques(type_):
    with pytest.raises(ErreurUtilisateur, match="jamais élastique"):
        etape(type_=type_, elastique=True)


@pytest.mark.parametrize("type_", ["echauffement", "calme"])
def test_echauffement_et_calme_peuvent_etre_elastiques(type_):
    assert etape(type_=type_, elastique=True).elastique is True


def test_contraignante_n_est_vrai_que_pour_un_bloc():
    assert etape(type_="bloc").contraignante is True
    for autre in ("echauffement", "recuperation", "calme"):
        assert etape(type_=autre).contraignante is False


def test_une_etape_est_immuable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        etape().duree_s = 10.0


# --- Seance -------------------------------------------------------------------


def seance_4x8() -> Seance:
    etapes = [etape("echauffement", 600.0, 140.0, 190.0, elastique=True)]
    for _ in range(4):
        etapes.append(etape("bloc", 480.0, 230.0, 270.0))
        etapes.append(etape("recuperation", 240.0, 100.0, 140.0))
    etapes.append(etape("calme", 300.0, 100.0, 140.0, elastique=True))
    return Seance(
        nom="4x8 fabriquée",
        jour=date(2026, 9, 8),
        etapes=etapes,
        duree_s=sum(e.duree_s for e in etapes),
        meta={},
    )


def test_blocs_rend_indices_et_etapes():
    s = seance_4x8()
    indices = [i for i, _ in s.blocs()]
    assert indices == [1, 3, 5, 7]
    assert all(e.type == "bloc" for _, e in s.blocs())


def test_duree_blocs():
    assert seance_4x8().duree_blocs_s == 4 * 480.0


def test_recuperation_apres_un_bloc():
    s = seance_4x8()
    recup = s.recuperation_apres(1)
    assert recup is not None and recup.duree_s == 240.0


def test_pas_de_recuperation_apres_le_dernier_bloc():
    """Le 4e bloc est suivi d'une récup, mais le calme qui suit n'en est pas une."""
    s = seance_4x8()
    assert s.recuperation_apres(8) is None  # l'étape 8 est une récup, suivie du calme


def test_recuperation_apres_indice_hors_bornes():
    s = seance_4x8()
    assert s.recuperation_apres(len(s.etapes) - 1) is None
    assert s.recuperation_apres(-5) is None


def test_une_seance_sans_bloc_a_une_liste_de_blocs_vide():
    s = Seance(
        nom="EF",
        jour=date(2026, 8, 29),
        etapes=[etape("echauffement", 7200.0, 140.0, 190.0, elastique=True)],
        duree_s=7200.0,
        meta={},
    )
    assert s.blocs() == []
    assert s.duree_blocs_s == 0.0


# --- zones --------------------------------------------------------------------


def test_les_zones_par_defaut_sont_sept_et_croissantes():
    assert len(ZONES_PUISSANCE_DEFAUT) == 7
    bas = [z[0] for z in ZONES_PUISSANCE_DEFAUT]
    assert bas == sorted(bas)
    assert all(b <= h for b, h in ZONES_PUISSANCE_DEFAUT)


def test_la_zone_4_est_celle_observee_chez_intervals():
    assert ZONES_PUISSANCE_DEFAUT[3] == (0.91, 1.05)

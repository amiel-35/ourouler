"""La position dans la zone (décision 7) et les zones ouvertes (le piège).

Aucune donnée personnelle : les FTP de ces tests sont des nombres ronds
choisis pour que les watts se lisent de tête, pas celles de quelqu'un.
"""

from __future__ import annotations

import pytest

from ourouler.erreurs import ErreurUtilisateur
from ourouler.seance.modele import PUISSANCE_ENDURANCE_PCT_DEFAUT, ZONES_PUISSANCE_DEFAUT
from ourouler.seance.zones import (
    POSITION_ENDURANCE_DEFAUT,
    ZONE_ENDURANCE,
    bornes_zone,
    echelle,
    position_dans_zone,
    position_endurance,
    puissance_endurance_pct,
    puissance_pct_ftp,
    zone_ouverte,
)

#: Table à trois zones, dont une seule est fermée : le cas limite accepté par
#: la configuration. Elle sert à vérifier que « la dernière zone » est
#: **positionnelle** et non « la Z7 ».
TABLE_COURTE = ((0.0, 0.50), (0.51, 0.80), (0.81, 2.0))


# --- ce que la décision 7 promet ---------------------------------------------


def test_la_position_par_defaut_rend_exactement_la_puissance_mesuree():
    """Le défaut ne change aucun comportement : 0,60 de FTP, au bit près.

    C'est la règle absolue 5 appliquée à ce lot. 0,60 est une **mesure**
    (Q11), pas une valeur ronde : la dérivation doit la rendre telle quelle,
    sinon le lot a déplacé la puissance d'endurance de tout le monde en
    silence.
    """
    assert puissance_endurance_pct(POSITION_ENDURANCE_DEFAUT) == PUISSANCE_ENDURANCE_PCT_DEFAUT
    assert puissance_endurance_pct(POSITION_ENDURANCE_DEFAUT) == 0.60


def test_la_position_par_defaut_est_celle_de_la_mesure_dans_la_bande():
    # (0,60 − 0,56) / (0,75 − 0,56) = 0,2105…
    assert POSITION_ENDURANCE_DEFAUT == pytest.approx(0.2105263, abs=1e-6)


@pytest.mark.parametrize("pct", [0.40, 0.50, 0.60, 0.65, 0.70, 0.80])
def test_valeur_puis_position_puis_valeur_revient_au_point_de_depart(pct):
    """L'aller-retour est exact : c'est ce qui rend la migration sûre."""
    assert puissance_endurance_pct(position_endurance(pct)) == pct


def test_la_position_se_propage_aux_autres_zones_fermees():
    """« Qui se met au milieu de sa Z2 prend le milieu de sa Z3 et de sa Z4. »"""
    assert puissance_pct_ftp(0.5, 2) == pytest.approx((0.56 + 0.75) / 2)
    assert puissance_pct_ftp(0.5, 3) == pytest.approx((0.76 + 0.90) / 2)
    assert puissance_pct_ftp(0.5, 4) == pytest.approx((0.91 + 1.05) / 2)


def test_les_bornes_de_la_bande_sont_0_et_1():
    assert puissance_pct_ftp(0.0, 2) == pytest.approx(0.56)
    assert puissance_pct_ftp(1.0, 2) == pytest.approx(0.75)


def test_une_ftp_qui_progresse_deplace_tout_l_escalier_sans_reglage():
    """Le point de la décision 7, vérifié : seul le multiplicateur change."""
    avant = echelle(0.5, 250.0)
    apres = echelle(0.5, 262.0)
    for a, b in zip(avant, apres, strict=True):
        if a.puissance_w is None:
            assert b.puissance_w is None
        else:
            assert b.puissance_w == pytest.approx(a.puissance_w * 262.0 / 250.0)


# --- les zones ouvertes -------------------------------------------------------


def test_la_premiere_et_la_derniere_zone_sont_ouvertes():
    assert zone_ouverte(1)
    assert zone_ouverte(len(ZONES_PUISSANCE_DEFAUT))
    assert not any(zone_ouverte(n) for n in range(2, len(ZONES_PUISSANCE_DEFAUT)))


def test_une_position_dans_une_zone_ouverte_ne_rend_pas_de_chiffre():
    """Le milieu de la Z1 vaudrait 27,5 % de FTP — du pédalage à vide.

    Mieux vaut un trou assumé qu'un chiffre que personne ne peut tenir.
    """
    assert puissance_pct_ftp(0.5, 1) is None
    assert puissance_pct_ftp(0.5, len(ZONES_PUISSANCE_DEFAUT)) is None
    assert position_dans_zone(0.30, 1) is None
    assert position_dans_zone(1.80, len(ZONES_PUISSANCE_DEFAUT)) is None


def test_ouverte_veut_dire_premiere_ou_derniere_pas_z1_et_z7():
    """Le critère est positionnel : une table courte a sa propre dernière zone."""
    assert zone_ouverte(3, TABLE_COURTE)
    assert not zone_ouverte(2, TABLE_COURTE)
    assert puissance_pct_ftp(0.5, 3, TABLE_COURTE) is None
    assert puissance_pct_ftp(0.5, 2, TABLE_COURTE) == pytest.approx((0.51 + 0.80) / 2)


def test_l_escalier_laisse_les_zones_ouvertes_vides_mais_montre_leurs_bornes():
    paliers = echelle(0.5, 300.0)
    assert [p.numero for p in paliers] == list(range(1, 8))
    assert paliers[0].ouverte and paliers[0].puissance_w is None
    assert paliers[-1].ouverte and paliers[-1].puissance_w is None
    # Les bornes, elles, restent affichables : c'est la cible qui manque.
    assert paliers[0].haut_w == pytest.approx(0.55 * 300.0)
    assert paliers[3].puissance_w == pytest.approx((0.91 + 1.05) / 2 * 300.0)


# --- la faute que la décision 8 veut rendre visible ---------------------------


def test_une_puissance_sous_la_z2_rend_une_position_negative_non_ecretee():
    """0,508 × FTP → −27 % de la bande. C'est le chiffre du contrat.

    Écrêter à 0 aurait masqué la faute (quelqu'un qui saisit sa moyenne
    compteur au lieu de sa vitesse à plat) au lieu de permettre à l'écran de
    la dire.
    """
    assert position_dans_zone(0.508, ZONE_ENDURANCE) == pytest.approx(-0.2737, abs=1e-4)


def test_une_puissance_au_dessus_de_la_z2_rend_une_position_au_dessus_de_1():
    assert position_dans_zone(0.80, ZONE_ENDURANCE) > 1.0


# --- refus nets ---------------------------------------------------------------


@pytest.mark.parametrize("numero", [0, -1, 8, 99])
def test_un_numero_de_zone_hors_table_est_refuse(numero):
    with pytest.raises(ErreurUtilisateur, match="zones"):
        bornes_zone(numero)


@pytest.mark.parametrize("numero", ["2", 2.0, True, None])
def test_un_numero_de_zone_qui_n_est_pas_un_entier_est_refuse(numero):
    with pytest.raises(ErreurUtilisateur, match="entier"):
        bornes_zone(numero)


@pytest.mark.parametrize("position", [float("nan"), float("inf"), "milieu", None])
def test_une_position_non_finie_est_refusee(position):
    with pytest.raises(ErreurUtilisateur, match="position"):
        puissance_pct_ftp(position, 2)


@pytest.mark.parametrize("ftp", [0.0, -10.0])
def test_une_ftp_non_positive_est_refusee_par_l_escalier(ftp):
    with pytest.raises(ErreurUtilisateur, match="FTP"):
        echelle(0.5, ftp)


def test_une_table_sans_z2_fermee_refuse_de_deduire_une_endurance():
    with pytest.raises(ErreurUtilisateur, match="endurance"):
        puissance_endurance_pct(0.5, ((0.0, 0.55), (0.56, 2.0)))


# --- le piège déjà tombé une fois --------------------------------------------


def test_la_zone_d_endurance_est_une_zone_de_puissance():
    """Une zone de FC n'est pas la zone de puissance de même numéro.

    `ZONE_ENDURANCE` indexe la table des zones de **puissance** ; c'est
    justement parce que la correspondance de numéros est fausse dans le bas
    qu'une consigne en zone de FC basse vise cette puissance-là plutôt que le
    milieu de la Z1 ou de la Z2 de FC. L'erreur a déjà été commise sur ce
    projet ; ce test la fige.
    """
    assert ZONE_ENDURANCE == 2
    assert bornes_zone(ZONE_ENDURANCE) == (0.56, 0.75)
    assert 0.55 < puissance_endurance_pct(POSITION_ENDURANCE_DEFAUT) < 0.76

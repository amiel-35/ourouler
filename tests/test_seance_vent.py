"""Le champ de vent : convention d'angle, interpolation, vent inconnu.

La convention d'angle est le seul vrai piège du module. `vent_depuis_deg` est
la direction **d'où vient** le vent ; un vent « de nord » vient du nord et
souffle vers le sud. Se tromper de signe ici donnerait un placement qui pose
les blocs exactement là où il ne faut pas, sans qu'aucun test de non-régression
ne bronche. Les trois cas canoniques sont donc testés avant tout le reste.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ourouler.boucle.meteo_trace import Echantillon
from ourouler.physique.modele import FACTEUR_VENT_HAUTEUR
from ourouler.seance.vent import ChampVent

T0 = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)


def echantillon(
    dist_m: float,
    vent_kmh: float | None = 18.0,
    vent_depuis_deg: float | None = 0.0,
) -> Echantillon:
    """Un échantillon réduit à ce dont le champ de vent se sert."""
    return Echantillon(
        dist_m=dist_m,
        t=T0,
        # Au large du golfe de Guinée, comme tous les tracés synthétiques du
        # dépôt : aucune coordonnée réelle, pas même approchée (règle absolue 1).
        lat=0.0,
        lon=0.0,
        cap_deg=0.0,
        pluie_mm=0.0,
        vent_kmh=vent_kmh,
        vent_relatif=None,
        ressenti_c=12.0,
        vent_depuis_deg=vent_depuis_deg,
    )


def champ(*echantillons: Echantillon, facteur: float = 1.0) -> ChampVent:
    """Un champ dont la conversion de hauteur est neutralisée, pour tester la géométrie."""
    return ChampVent(echantillons, facteur_hauteur=facteur)


# --- les trois cas canoniques de la convention d'angle ------------------------


def test_vent_venant_de_la_ou_lon_va_est_plein_face():
    """Cap au nord, vent « de nord » : on va dans le vent, composante = +V."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0))
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(10.0)


def test_vent_venant_de_derriere_est_plein_dos():
    """Cap au nord, vent « de sud » : il pousse, composante = −V."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=180.0))
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(-10.0)


@pytest.mark.parametrize("depuis", [90.0, 270.0])
def test_vent_perpendiculaire_ne_compte_pour_rien(depuis: float):
    """Le modèle physique ne connaît qu'une composante longitudinale (approximation assumée)."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=depuis))
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("cap", [0.0, 45.0, 137.0, 270.0, 359.0])
def test_la_convention_tient_quel_que_soit_le_cap(cap: float):
    """Ce n'est pas le nord qui est de face, c'est la direction suivie."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=cap))
    assert c.vent_face_ms(0.0, cap_deg=cap, sens=1) == pytest.approx(10.0)


def test_le_demi_tour_retourne_la_composante():
    """Au retour, le vent de face devient vent de dos — c'est tout l'intérêt du sens."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0))
    aller = c.vent_face_ms(0.0, cap_deg=0.0, sens=1)
    retour = c.vent_face_ms(0.0, cap_deg=0.0, sens=-1)
    assert aller == pytest.approx(10.0)
    assert retour == pytest.approx(-10.0)


def test_un_vent_de_biais_vaut_le_cosinus():
    """45° de biais : 36 km/h en rendent 10 · cos(45°) ≈ 7,07 m/s."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=45.0))
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(7.0710678, abs=1e-6)


# --- le facteur de hauteur ----------------------------------------------------


def test_le_facteur_de_hauteur_est_celui_du_modele_physique():
    """Le vent météo est donné à 10 m ; le cycliste est à 1,5 m dans du bocage.

    Ce n'est pas un réglage libre : si ce facteur n'était pas celui de la
    calibration, le modèle serait calibré sur un vent et utilisé sur un autre.
    """
    c = ChampVent([echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0)])
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(10.0 * FACTEUR_VENT_HAUTEUR)


# --- interpolation le long du tracé -------------------------------------------


def test_la_vitesse_est_interpolee_lineairement():
    c = champ(
        echantillon(0.0, vent_kmh=0.0, vent_depuis_deg=0.0),
        echantillon(10_000.0, vent_kmh=36.0, vent_depuis_deg=0.0),
    )
    assert c.vent_face_ms(5_000.0, cap_deg=0.0, sens=1) == pytest.approx(5.0)


def test_la_direction_est_interpolee_angulairement():
    """350° et 10° font 0°, pas 180° : la faute classique, et celle qui coûte le plus.

    À mi-chemin entre ces deux directions, le vent vient du nord. Cap au nord
    donc plein face : la composante vaut +V. L'interpolation linéaire aurait
    rendu 180°, c'est-à-dire un vent de dos — le contraire exact.
    """
    c = champ(
        echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=350.0),
        echantillon(10_000.0, vent_kmh=36.0, vent_depuis_deg=10.0),
    )
    assert c.vent_face_ms(5_000.0, cap_deg=0.0, sens=1) == pytest.approx(10.0, abs=1e-9)


def test_hors_des_bornes_on_prend_lechantillon_du_bout():
    """Un placement qui dépasse de quelques mètres la dernière borne garde son vent."""
    c = champ(
        echantillon(1_000.0, vent_kmh=36.0, vent_depuis_deg=0.0),
        echantillon(9_000.0, vent_kmh=72.0, vent_depuis_deg=0.0),
    )
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(10.0)
    assert c.vent_face_ms(50_000.0, cap_deg=0.0, sens=1) == pytest.approx(20.0)


def test_des_echantillons_desordonnes_sont_remis_en_ordre():
    c = champ(
        echantillon(10_000.0, vent_kmh=36.0, vent_depuis_deg=0.0),
        echantillon(0.0, vent_kmh=0.0, vent_depuis_deg=0.0),
    )
    assert c.vent_face_ms(5_000.0, cap_deg=0.0, sens=1) == pytest.approx(5.0)


def test_un_seul_echantillon_vaut_pour_tout_le_trace():
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0))
    assert c.vent_face_ms(80_000.0, cap_deg=0.0, sens=1) == pytest.approx(10.0)


def test_deux_echantillons_a_la_meme_position_ne_divisent_pas_par_zero():
    c = champ(
        echantillon(5_000.0, vent_kmh=36.0, vent_depuis_deg=0.0),
        echantillon(5_000.0, vent_kmh=72.0, vent_depuis_deg=0.0),
    )
    assert c.vent_face_ms(5_000.0, cap_deg=0.0, sens=1) == pytest.approx(10.0)


def test_une_position_non_finie_ne_fait_pas_de_nan():
    """Un NaN traverserait les additions sans bruit et ressortirait en temps vide."""
    c = champ(echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0))
    assert c.vent_face_ms(float("nan"), cap_deg=0.0, sens=1) == 0.0
    assert c.vent_face_ms(float("inf"), cap_deg=0.0, sens=1) == 0.0


# --- vent inconnu : ce n'est pas un vent nul ----------------------------------


def test_un_champ_entierement_connu_est_complet():
    c = champ(echantillon(0.0), echantillon(5_000.0))
    assert c.complet is True


def test_un_echantillon_sans_vent_rend_le_champ_incomplet():
    """Hors de l'horizon de prévision, le vent n'est pas nul : il est inconnu."""
    c = champ(echantillon(0.0), echantillon(5_000.0, vent_kmh=None, vent_depuis_deg=None))
    assert c.complet is False


def test_une_direction_manquante_suffit_a_rendre_le_champ_incomplet():
    c = champ(echantillon(0.0), echantillon(5_000.0, vent_depuis_deg=None))
    assert c.complet is False


def test_un_champ_vide_nest_pas_complet_et_ne_leve_pas():
    c = champ()
    assert c.complet is False
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == 0.0


def test_une_position_dans_un_intervalle_inconnu_rend_zero():
    """On ne prolonge pas le dernier vent connu : ce serait affirmer sans mesure."""
    c = champ(
        echantillon(0.0, vent_kmh=36.0, vent_depuis_deg=0.0),
        echantillon(10_000.0, vent_kmh=None, vent_depuis_deg=None),
    )
    assert c.vent_face_ms(0.0, cap_deg=0.0, sens=1) == pytest.approx(10.0)
    assert c.vent_face_ms(5_000.0, cap_deg=0.0, sens=1) == 0.0

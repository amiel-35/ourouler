"""Tests de la couronne (L1.5) : distances et azimuts retrouvés par la formule inverse.

Aucune coordonnée réelle : les départs de test sont au point (0.0, 0.0), en
pleine mer, ou à des latitudes manifestement choisies pour le calcul.
"""

from __future__ import annotations

import math

import pytest

from ourouler.config import Depart
from ourouler.meteo.couronne import (
    NOM_ICI,
    NOMS_DIRECTIONS,
    NOMS_DIRECTIONS_16,
    azimut_de,
    azimut_initial_deg,
    couronne,
    destination,
    distance_haversine_km,
    ecart_angulaire,
    noms_directions,
)
from ourouler.noyau.erreurs import ErreurConfig

DEPART = Depart(nom="Point zéro", latitude=0.0, longitude=0.0)
DEPART_NORD = Depart(nom="Haute latitude", latitude=60.0, longitude=0.0)  # mer du Nord

TOLERANCE_RELATIVE = 0.005  # 0,5 %, exigence du contrat


def test_huit_noms_en_francais():
    assert NOMS_DIRECTIONS == ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
    assert noms_directions(8) == NOMS_DIRECTIONS


def test_seize_noms_en_francais():
    noms = noms_directions(16)
    assert noms == NOMS_DIRECTIONS_16
    assert len(noms) == 16
    # Français : O pour ouest, jamais W ; pas de « W » dans les composés non plus.
    assert "OSO" in noms and "ONO" in noms and "ENE" in noms
    assert not any("W" in n for n in noms)


def test_nombre_de_directions_invalide():
    with pytest.raises(ErreurConfig) as e:
        noms_directions(12)
    assert "directions" in str(e.value)


def test_azimuts_des_huit_directions():
    attendus = {"N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0}
    attendus |= {"S": 180.0, "SO": 225.0, "O": 270.0, "NO": 315.0}
    for nom, azimut in attendus.items():
        assert azimut_de(nom) == pytest.approx(azimut)


def test_azimut_de_inconnu():
    with pytest.raises(ErreurConfig):
        azimut_de("W")


def test_point_ici_inclus_en_premier():
    points = couronne(DEPART, 8, [15.0])
    assert points[0].nom == NOM_ICI
    assert points[0].distance_km == 0.0
    assert (points[0].lat, points[0].lon) == (DEPART.latitude, DEPART.longitude)


def test_nombre_de_points():
    assert len(couronne(DEPART, 8, [15.0, 25.0, 40.0])) == 1 + 8 * 3
    assert len(couronne(DEPART, 16, [20.0])) == 1 + 16


def test_groupe_par_distance_croissante():
    points = couronne(DEPART, 8, [40.0, 15.0])
    distances = [p.distance_km for p in points]
    assert distances == [0.0] + [15.0] * 8 + [40.0] * 8


def test_distance_nulle_ou_negative_ignoree():
    points = couronne(DEPART, 8, [0.0, -5.0, 15.0])
    assert {p.distance_km for p in points} == {0.0, 15.0}


@pytest.mark.parametrize("depart", [DEPART, DEPART_NORD])
@pytest.mark.parametrize("distance", [1.0, 15.0, 40.0, 200.0])
def test_formule_inverse_retrouve_distance_et_azimut(depart: Depart, distance: float):
    """Chaque point, relu par haversine + azimut initial, redonne ce qu'on a demandé."""
    for p in couronne(depart, 16, [distance]):
        if p.nom == NOM_ICI:
            continue
        mesuree = distance_haversine_km(depart.latitude, depart.longitude, p.lat, p.lon)
        assert mesuree == pytest.approx(distance, rel=TOLERANCE_RELATIVE)
        azimut = azimut_initial_deg(depart.latitude, depart.longitude, p.lat, p.lon)
        assert ecart_angulaire(azimut, p.azimut_deg) < 360.0 * TOLERANCE_RELATIVE


def test_nord_augmente_la_latitude_et_est_augmente_la_longitude():
    par_nom = {p.nom: p for p in couronne(DEPART, 8, [100.0])}
    assert par_nom["N"].lat > 0 and par_nom["N"].lon == pytest.approx(0.0, abs=1e-9)
    assert par_nom["S"].lat < 0
    assert par_nom["E"].lon > 0 and par_nom["E"].lat == pytest.approx(0.0, abs=1e-9)
    assert par_nom["O"].lon < 0


def test_destination_distance_nulle_ne_bouge_pas():
    assert destination(12.0, 34.0, 90.0, 0.0) == (12.0, 34.0)


def test_destination_reste_dans_les_bornes_de_longitude():
    """Départ juste à l'ouest de l'antiméridien, cap à l'est : la longitude se replie."""
    _, lon = destination(0.0, 179.9, 90.0, 100.0)
    assert -180.0 <= lon <= 180.0
    assert lon < 0  # on a franchi l'antiméridien


def test_un_degre_de_latitude_fait_environ_111_km():
    lat, _ = destination(0.0, 0.0, 0.0, math.pi * 6371.0 / 180.0)
    assert lat == pytest.approx(1.0, rel=1e-6)


@pytest.mark.parametrize(
    ("a", "b", "attendu"),
    [(0.0, 0.0, 0.0), (0.0, 10.0, 10.0), (350.0, 10.0, 20.0), (0.0, 180.0, 180.0), (0.0, 270.0, 90.0)],
)
def test_ecart_angulaire(a: float, b: float, attendu: float):
    assert ecart_angulaire(a, b) == pytest.approx(attendu)

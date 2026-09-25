"""Tests de `boucle.horaire` : l'heure de passage à un point du tracé, avec pauses.

Aucun réseau, aucune coordonnée réelle : ce module ne construit qu'une
fonction pure (`Horaire`) et lit des chaînes de ligne de commande.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ourouler.boucle.horaire import (
    Pause,
    analyser_duree,
    analyser_pause,
    construire_horaire,
    valider_pauses,
)
from ourouler.noyau.erreurs import ErreurUtilisateur

DEPART = datetime(2026, 5, 16, 5, 0, tzinfo=UTC)


# --- construire_horaire : non-régression, sans pause --------------------------


def test_sans_pause_horaire_vaut_exactement_depart_plus_distance_sur_vitesse():
    """Le calcul d'avant ce lot, à la lettre : c'est le test de non-régression."""
    horaire = construire_horaire(DEPART, 20.0)
    for km in (0.0, 5.0, 37.5, 123.4):
        dist_m = km * 1000.0
        attendu = DEPART + timedelta(hours=dist_m / 1000.0 / 20.0)
        assert horaire(dist_m) == attendu


def test_horaire_zero_vaut_toujours_le_depart():
    """`horaire(0.0)` sert de départ à `meteo_trace.evaluer` : jamais décalé par une pause."""
    pauses = [Pause(dist_m=0.0, duree_s=3600.0), Pause(dist_m=10_000.0, duree_s=600.0)]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    assert horaire(0.0) == DEPART


def test_un_depart_sans_fuseau_est_lu_comme_utc():
    horaire = construire_horaire(DEPART.replace(tzinfo=None), 20.0)
    assert horaire(0.0) == DEPART


@pytest.mark.parametrize("vitesse", [0.0, -5.0, float("nan"), float("inf")])
def test_une_vitesse_non_strictement_positive_est_refusee(vitesse: float):
    with pytest.raises(ErreurUtilisateur, match="vitesse_kmh"):
        construire_horaire(DEPART, vitesse)


# --- construire_horaire : avec pauses ------------------------------------------


def test_une_pause_avant_un_echantillon_le_decale():
    """« À 10 km je m'arrête 45 minutes » : tout ce qui suit arrive 45 min plus tard."""
    pauses = [Pause(dist_m=10_000.0, duree_s=45 * 60.0)]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    sans_pause = DEPART + timedelta(hours=20_000.0 / 1000.0 / 20.0)
    assert horaire(20_000.0) == sans_pause + timedelta(minutes=45)


def test_une_pause_apres_un_echantillon_ne_le_touche_pas():
    pauses = [Pause(dist_m=15_000.0, duree_s=45 * 60.0)]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    sans_pause = DEPART + timedelta(hours=10_000.0 / 1000.0 / 20.0)
    assert horaire(10_000.0) == sans_pause, "la pause est plus loin, elle ne doit rien décaler"


def test_une_pause_exactement_au_kilometre_de_l_echantillon_ne_le_touche_pas():
    """Au kilomètre de la pause, le cycliste vient d'y arriver : il ne l'a pas encore prise."""
    pauses = [Pause(dist_m=10_000.0, duree_s=45 * 60.0)]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    sans_pause = DEPART + timedelta(hours=10_000.0 / 1000.0 / 20.0)
    assert horaire(10_000.0) == sans_pause


def test_plusieurs_pauses_se_cumulent():
    pauses = [
        Pause(dist_m=10_000.0, duree_s=30 * 60.0),
        Pause(dist_m=20_000.0, duree_s=15 * 60.0),
    ]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    sans_pause = DEPART + timedelta(hours=30_000.0 / 1000.0 / 20.0)
    assert horaire(30_000.0) == sans_pause + timedelta(minutes=45)


def test_les_pauses_desordonnees_sont_prises_dans_le_bon_ordre():
    """L'ordre de déclaration ne doit pas compter, seul le kilomètre compte."""
    pauses = [
        Pause(dist_m=20_000.0, duree_s=15 * 60.0),
        Pause(dist_m=10_000.0, duree_s=30 * 60.0),
    ]
    horaire = construire_horaire(DEPART, 20.0, pauses)
    sans_pause = DEPART + timedelta(hours=30_000.0 / 1000.0 / 20.0)
    assert horaire(30_000.0) == sans_pause + timedelta(minutes=45)


# --- analyser_duree ------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "secondes"),
    [
        ("4h30", 4 * 3600 + 30 * 60),
        ("0h45", 45 * 60),
        ("4h", 4 * 3600),
        ("45min", 45 * 60),
        ("1:30", 3600 + 30 * 60),
        ("0:05", 5 * 60),
    ],
)
def test_les_formes_de_duree_acceptees(texte: str, secondes: float):
    assert analyser_duree(texte) == pytest.approx(secondes)


@pytest.mark.parametrize("texte", ["", "abc", "4h75", "4heures", "-1h", "1:99", "1h:30"])
def test_les_formes_de_duree_refusees(texte: str):
    with pytest.raises(ErreurUtilisateur, match="durée"):
        analyser_duree(texte)


# --- analyser_pause -------------------------------------------------------------


def test_une_pause_valide_est_lue():
    pause = analyser_pause("180:0h45")
    assert pause == Pause(dist_m=180_000.0, duree_s=45 * 60.0)


def test_une_pause_avec_une_duree_a_deux_points_reste_lisible():
    """« 180:1:30 » : seul le premier « : » sépare le kilomètre de la durée."""
    pause = analyser_pause("180:1:30")
    assert pause == Pause(dist_m=180_000.0, duree_s=3600.0 + 30 * 60.0)


def test_une_pause_sans_deux_points_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="KM:DUREE"):
        analyser_pause("18045min")


@pytest.mark.parametrize("texte", ["-5:0h45", "abc:0h45", "nan:0h45"])
def test_un_kilometre_negatif_ou_illisible_est_refuse(texte: str):
    with pytest.raises(ErreurUtilisateur, match="kilomètre"):
        analyser_pause(texte)


@pytest.mark.parametrize("texte", ["180:0h0", "180:0min", "180:0:00"])
def test_une_duree_nulle_est_refusee(texte: str):
    with pytest.raises(ErreurUtilisateur, match="durée"):
        analyser_pause(texte)


# --- valider_pauses --------------------------------------------------------------


def test_deux_pauses_au_meme_kilometre_sont_refusees():
    pauses = [Pause(180_000.0, 600.0), Pause(180_000.0, 300.0)]
    with pytest.raises(ErreurUtilisateur, match="même kilomètre"):
        valider_pauses(pauses)


def test_une_pause_au_dela_du_parcours_est_refusee():
    pauses = [Pause(200_000.0, 600.0)]
    with pytest.raises(ErreurUtilisateur, match="au-delà"):
        valider_pauses(pauses, distance_m=180_000.0)


def test_une_pause_dans_le_parcours_est_acceptee():
    valider_pauses([Pause(180_000.0, 600.0)], distance_m=200_000.0)


def test_sans_longueur_connue_le_refus_au_dela_est_reporte():
    """`distance_m=None` : la longueur n'est pas encore connue à ce point de la commande."""
    valider_pauses([Pause(999_000_000.0, 600.0)], distance_m=None)

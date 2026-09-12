"""Tests du lecteur unique FIT / GPX / TCX (L1.2)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ourouler.activites.lecture import lire, lire_fit, lire_gpx, lire_tcx
from ourouler.activites.modele import Point, denivele_positif, puissance_normalisee
from ourouler.erreurs import ErreurLecture, ErreurUtilisateur

TROIS_FORMATS = ["boucle.fit", "boucle.gpx", "boucle.tcx"]


# --- cas nominaux -------------------------------------------------------------


@pytest.mark.parametrize("nom", TROIS_FORMATS)
def test_lire_les_trois_formats(activites: Path, nom: str):
    a = lire(activites / nom)
    assert a.source == nom.rsplit(".", 1)[1]
    assert a.fichier and a.fichier.endswith(nom)
    assert a.debut == datetime(2024, 3, 30, 9, 0, tzinfo=UTC)
    assert a.debut.tzinfo is not None
    assert a.duree_s == pytest.approx(678, abs=1)
    assert len(a.points) == 340
    assert a.distance_m and 4000 < a.distance_m < 8000
    assert a.puissance_moy_w == pytest.approx(206.6, abs=0.5)
    assert a.denivele_m == pytest.approx(58.3, abs=1.0)
    assert a.sport
    assert a.appareil
    assert not a.avertissements


def test_les_trois_formats_donnent_les_memes_grandeurs_derivees(activites: Path):
    """La même trace, encodée trois fois : les grandeurs dérivées coïncident.

    Le dénivelé tolère 0,5 m d'écart : le FIT stocke l'altitude au cinquième
    de mètre (échelle 5), le GPX et le TCX au décimètre.
    """
    lues = [lire(activites / nom) for nom in TROIS_FORMATS]
    for champ, tolerance in (
        ("puissance_moy_w", 1e-9),
        ("puissance_np_w", 1e-9),
        ("duree_s", 1e-9),
        ("denivele_m", 0.5),
    ):
        valeurs = [getattr(a, champ) for a in lues]
        assert valeurs[0] == pytest.approx(valeurs[1], abs=tolerance), champ
        assert valeurs[0] == pytest.approx(valeurs[2], abs=tolerance), champ


@pytest.mark.parametrize("nom", TROIS_FORMATS)
def test_tous_les_horodatages_sont_en_utc(activites: Path, nom: str):
    a = lire(activites / nom)
    assert all(p.t.tzinfo is not None and p.t.utcoffset() == timedelta(0) for p in a.points)


def test_les_points_portent_les_capteurs(activites: Path):
    a = lire(activites / "boucle.fit")
    p = a.points[10]
    assert p.lat == pytest.approx(0.0, abs=0.02) and p.lon == pytest.approx(0.0, abs=0.02)
    assert p.alt_m is not None and p.dist_m is not None
    assert p.puissance_w and p.cadence_rpm and p.fc_bpm
    assert p.temp_c == 14
    assert p.vitesse_ms == pytest.approx(7.8, abs=0.01)


def test_fit_donne_le_temps_de_mouvement_les_autres_non(activites: Path):
    assert lire(activites / "boucle.fit").duree_mouvement_s == pytest.approx(648, abs=1)
    assert lire(activites / "boucle.gpx").duree_mouvement_s is None
    assert lire(activites / "boucle.tcx").duree_mouvement_s is None


def test_extension_en_majuscules(activites: Path):
    a = lire(activites / "COURTE.GPX")
    assert a.source == "gpx"
    assert len(a.points) == 120


def test_lecteurs_acceptent_des_octets(activites: Path):
    for nom, lecteur in (
        ("boucle.fit", lire_fit),
        ("boucle.gpx", lire_gpx),
        ("boucle.tcx", lire_tcx),
    ):
        a = lecteur((activites / nom).read_bytes())
        assert a.fichier is None
        assert len(a.points) == 340


# --- sources incomplètes, mais valides ----------------------------------------


def test_sans_gps_reste_valide(activites: Path):
    a = lire(activites / "home_trainer.fit")
    assert all(p.lat is None and p.lon is None for p in a.points)
    assert a.puissance_moy_w is not None
    assert a.denivele_m is None  # pas d'altitude du tout


def test_sans_puissance_reste_valide(activites: Path):
    a = lire(activites / "sans_puissance.gpx")
    assert a.puissance_moy_w is None
    assert a.puissance_np_w is None
    assert a.points and all(p.lat is not None for p in a.points)


def test_sans_altitude_denivele_none(activites: Path):
    a = lire(activites / "sans_altitude.gpx")
    assert a.denivele_m is None
    assert all(p.alt_m is None for p in a.points)


def test_horodatages_non_monotones_tolere_et_signale(activites: Path):
    a = lire(activites / "non_monotone.gpx")
    assert a.avertissements, "l'anomalie doit être signalée dans meta['avertissements']"
    assert "monotone" in a.avertissements[0]
    horodatages = [p.t for p in a.points]
    assert horodatages == sorted(horodatages)
    assert a.duree_s > 0


# --- cas d'erreur -------------------------------------------------------------


@pytest.mark.parametrize("nom", ["vide.fit", "vide.gpx", "vide.tcx"])
def test_fichier_vide(activites: Path, nom: str):
    with pytest.raises(ErreurLecture) as e:
        lire(activites / nom)
    assert nom in str(e.value)
    assert "vide" in str(e.value)


@pytest.mark.parametrize("nom", ["tronque.fit", "tronque.gpx", "tronque.tcx"])
def test_fichier_tronque(activites: Path, nom: str):
    with pytest.raises(ErreurLecture) as e:
        lire(activites / nom)
    assert nom in str(e.value)


def test_extension_inconnue(activites: Path):
    with pytest.raises(ErreurLecture) as e:
        lire(activites / "inconnu.dat")
    assert ".dat" in str(e.value)


def test_fichier_absent(tmp_path: Path):
    with pytest.raises(ErreurLecture) as e:
        lire(tmp_path / "nulle_part.fit")
    assert "nulle_part.fit" in str(e.value)


def test_fit_sans_enregistrement(generateur):
    """Un FIT bien formé mais ne contenant qu'un file_id n'est pas exploitable."""
    corps = generateur.message_definition(0, 0, generateur.CHAMPS_FILE_ID)
    corps += generateur.message_donnees(0, generateur.CHAMPS_FILE_ID, [4, 255, 0, 0])
    with pytest.raises(ErreurLecture) as e:
        lire_fit(generateur.fichier_fit(corps))
    assert "sans enregistrement" in str(e.value)


def test_gpx_xml_invalide():
    with pytest.raises(ErreurLecture):
        lire_gpx(b"<gpx><trk><trkseg>")


def test_tcx_sans_trackpoint():
    tcx = (
        b'<?xml version="1.0"?>'
        b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/'
        b'TrainingCenterDatabase/v2"><Activities/></TrainingCenterDatabase>'
    )
    with pytest.raises(ErreurLecture) as e:
        lire_tcx(tcx)
    assert "sans point" in str(e.value)


def test_erreur_lecture_est_une_erreur_utilisateur():
    assert issubclass(ErreurLecture, ErreurUtilisateur)


# --- grandeurs dérivées, testées isolément ------------------------------------


def _points(puissances=None, altitudes=None, pas_s=1):
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    taille = len(puissances or altitudes or [])
    return [
        Point(
            t=t0 + timedelta(seconds=i * pas_s),
            puissance_w=None if puissances is None else puissances[i],
            alt_m=None if altitudes is None else altitudes[i],
        )
        for i in range(taille)
    ]


def test_np_egale_la_puissance_constante():
    """Puissance constante : la NP vaut exactement cette puissance."""
    assert puissance_normalisee(_points(puissances=[200.0] * 300)) == pytest.approx(200.0)


def test_np_superieure_a_la_moyenne_si_variable():
    """L'élévation à la puissance 4 pénalise la variabilité : NP > moyenne."""
    alternee = [100.0, 300.0] * 150
    np = puissance_normalisee(_points(puissances=alternee))
    assert np is not None
    assert 195 < np < 205  # lissé sur 30 s, l'alternance rapide se moyenne


def test_np_penalise_les_variations_longues():
    """Des blocs de 2 min à 100 W puis 300 W : la NP dépasse nettement la moyenne."""
    blocs = ([100.0] * 120 + [300.0] * 120) * 3
    np = puissance_normalisee(_points(puissances=blocs))
    assert np is not None and np > 230


def test_np_none_sans_puissance():
    assert puissance_normalisee(_points(puissances=[None] * 100)) is None
    assert puissance_normalisee([]) is None


def test_denivele_lisse_le_bruit():
    """Un plateau bruité : le lissage doit diviser le faux dénivelé par plus de deux.

    Le lissage sur 5 points n'annule pas le bruit, il l'atténue : on mesure
    l'atténuation plutôt que d'affirmer un zéro qu'on n'obtient pas.
    """
    alea = random.Random(1234)  # graine fixe : test déterministe
    bruit = [100.0 + alea.uniform(-1.5, 1.5) for _ in range(500)]
    brut = sum(max(0.0, b - a) for a, b in zip(bruit, bruit[1:], strict=False))
    lisse = denivele_positif(_points(altitudes=bruit))
    assert lisse is not None
    assert lisse < brut / 2, f"lissage insuffisant : {lisse:.1f} m contre {brut:.1f} m brut"


def test_denivele_compte_la_montee_seule():
    montee = list(range(0, 100)) + list(range(100, 0, -1))
    d = denivele_positif(_points(altitudes=[float(x) for x in montee]))
    assert d == pytest.approx(100, abs=6)  # ~100 m de montée, la descente ne compte pas


def test_denivele_none_sans_altitude():
    assert denivele_positif(_points(altitudes=[None] * 50)) is None

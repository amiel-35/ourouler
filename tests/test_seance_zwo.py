"""Tests du lecteur `.ZWO` (`seance.zwo`, lot F0.5).

Toutes les séances sont **fabriquées** pour ce test, aucune ne vient d'un
compte réel. Aucun réseau, aucun fichier de configuration.
"""

from __future__ import annotations

from datetime import date

import pytest

from ourouler.noyau.erreurs import ErreurLecture
from ourouler.seance.zwo import lire_zwo

JOUR = date(2026, 9, 16)
FTP = 200.0  # inventée


def zwo(workout_xml: str, *, entete: str = "") -> bytes:
    """Assemble un `.ZWO` minimal autour du contenu de `<workout>`."""
    return (
        "<?xml version='1.0'?>\n"
        "<workout_file>\n"
        "<name>Séance test inventée</name>\n"
        "<description>Fabriquée pour les tests, aucune donnée réelle</description>\n"
        f"{entete}"
        f"<workout>{workout_xml}</workout>\n"
        "</workout_file>\n"
    ).encode()


def test_warmup_steady_cooldown_convertis_et_elastiques():
    doc = zwo(
        '<Warmup Duration="300" PowerLow="0.4" PowerHigh="0.75"/>'
        '<SteadyState Duration="600" Power="0.9"/>'
        '<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.3"/>'
    )
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)

    assert [e.type for e in seance.etapes] == ["echauffement", "bloc", "calme"]
    echauffement, bloc, calme = seance.etapes

    assert echauffement.puissance_min_w == pytest.approx(80.0)
    assert echauffement.puissance_max_w == pytest.approx(150.0)
    assert echauffement.elastique is True

    assert bloc.puissance_min_w == bloc.puissance_max_w == pytest.approx(180.0)
    assert bloc.elastique is False

    # Cooldown descend de 60 % à 30 % : les bornes sont remises dans l'ordre
    # par `Etape`, mais le libellé garde le sens de lecture d'origine.
    assert calme.puissance_min_w == pytest.approx(60.0)
    assert calme.puissance_max_w == pytest.approx(120.0)
    assert calme.elastique is True
    assert "60-30" in calme.libelle_court or "60-30" in calme.libelle

    assert seance.jour == JOUR
    assert seance.meta["conversion"].startswith("pourcentages de FTP convertis")
    assert seance.duree_s == 300 + 600 + 300


def test_intervalles_se_deplient():
    doc = zwo('<IntervalsT Repeat="3" OnDuration="30" OffDuration="15" OnPower="1.2" OffPower="0.5"/>')
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)

    assert [e.type for e in seance.etapes] == [
        "bloc",
        "recuperation",
        "bloc",
        "recuperation",
        "bloc",
        "recuperation",
    ]
    assert [e.duree_s for e in seance.etapes] == [30, 15, 30, 15, 30, 15]
    on, off = seance.etapes[0], seance.etapes[1]
    assert on.puissance_min_w == on.puissance_max_w == pytest.approx(240.0)
    assert off.puissance_min_w == off.puissance_max_w == pytest.approx(100.0)
    assert "1/3" in on.libelle
    assert "3/3" in seance.etapes[-1].libelle


def test_ramp_reste_un_bloc_meme_en_tete():
    """Une `Ramp` n'est ni un `Warmup` ni un `Cooldown` : elle garde son type
    de bloc même si elle ouvre la séance, tant qu'elle porte une puissance."""
    doc = zwo('<Ramp Duration="300" PowerLow="0.5" PowerHigh="0.95"/>')
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)

    (etape,) = seance.etapes
    assert etape.type == "bloc"
    assert etape.puissance_min_w == pytest.approx(100.0)
    assert etape.puissance_max_w == pytest.approx(190.0)
    assert etape.elastique is False


def test_freeride_type_par_position():
    doc = zwo(
        '<FreeRide Duration="60"/>'
        '<SteadyState Duration="300" Power="0.9"/>'
        '<FreeRide Duration="60"/>'
    )
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)

    assert [e.type for e in seance.etapes] == ["echauffement", "bloc", "calme"]
    premiere, milieu, derniere = seance.etapes
    assert premiere.puissance_min_w is None
    assert derniere.puissance_min_w is None
    assert premiere.elastique is True
    assert derniere.elastique is True
    assert milieu.puissance_min_w == pytest.approx(180.0)


def test_freeride_au_milieu_devient_recuperation():
    doc = zwo(
        '<SteadyState Duration="300" Power="0.9"/>'
        '<FreeRide Duration="60"/>'
        '<SteadyState Duration="300" Power="0.9"/>'
    )
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)
    assert [e.type for e in seance.etapes] == ["bloc", "recuperation", "bloc"]


def test_puissance_negative_est_ignoree_mais_ne_reclasse_pas():
    # Une consigne présente mais négative est illisible (comme dans
    # `seance/intervals.py`) : la puissance est effacée, mais la balise a
    # bien voulu dire quelque chose, donc le type de bloc par défaut reste —
    # ce n'est pas la même chose qu'une balise sans aucune consigne
    # (`FreeRide`), qui elle serait retypée par sa position.
    doc = zwo('<SteadyState Duration="60" Power="-0.5"/>')
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)
    (etape,) = seance.etapes
    assert etape.puissance_min_w is None
    assert etape.puissance_max_w is None
    assert etape.type == "bloc"


def test_sans_ftp_aucune_puissance_calculee():
    doc = zwo(
        '<Warmup Duration="300" PowerLow="0.4" PowerHigh="0.75"/>'
        '<SteadyState Duration="600" Power="0.9"/>'
        '<Cooldown Duration="300" PowerLow="0.6" PowerHigh="0.3"/>'
    )
    seance = lire_zwo(doc, ftp_w=None, jour=JOUR)

    assert all(e.puissance_min_w is None and e.puissance_max_w is None for e in seance.etapes)
    assert seance.meta["conversion"].startswith("FTP inconnue")
    assert seance.meta["etapes_sans_ftp"] == 3
    # Sans FTP, les marqueurs Warmup/Cooldown restent ce qu'ils sont : le
    # typage par balise ne dépend pas de la conversion en watts.
    assert [e.type for e in seance.etapes] == ["echauffement", "bloc", "calme"]


def test_textevent_ignore_sans_erreur():
    doc = zwo(
        '<textevent timeoffset="10" message="Allez !"/>'
        '<SteadyState Duration="60" Power="0.7"/>'
    )
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)
    assert len(seance.etapes) == 1


def test_bloc_inconnu_leve_une_erreur_en_clair():
    doc = zwo('<CoinDeTable Duration="60"/>')
    with pytest.raises(ErreurLecture, match="CoinDeTable"):
        lire_zwo(doc, ftp_w=FTP, jour=JOUR)


def test_fichier_vide():
    with pytest.raises(ErreurLecture, match="vide"):
        lire_zwo(b"", ftp_w=FTP, jour=JOUR)


def test_pas_du_tout_xml():
    with pytest.raises(ErreurLecture, match="illisible"):
        lire_zwo(b"ceci n'est pas du XML du tout {}", ftp_w=FTP, jour=JOUR)


def test_xml_tronque_au_milieu_d_une_balise():
    contenu = b"<workout_file><workout><SteadyState Duration=\"600\" Power=\"0.6\""
    with pytest.raises(ErreurLecture, match="illisible"):
        lire_zwo(contenu, ftp_w=FTP, jour=JOUR)


def test_sans_balise_workout():
    doc = b"<?xml version='1.0'?><workout_file><name>Vide</name></workout_file>"
    with pytest.raises(ErreurLecture, match="<workout>"):
        lire_zwo(doc, ftp_w=FTP, jour=JOUR)


def test_jour_par_defaut_est_aujourdhui():
    doc = zwo('<SteadyState Duration="60" Power="0.7"/>')
    seance = lire_zwo(doc, ftp_w=FTP)
    assert seance.jour == date.today()


def test_repetitions_negatives_ignorees_et_comptees():
    doc = zwo('<IntervalsT Repeat="-1" OnDuration="30" OffDuration="15" OnPower="1" OffPower="0.5"/>')
    seance = lire_zwo(doc, ftp_w=FTP, jour=JOUR)
    assert seance.etapes == []
    assert seance.meta["groupes_ignores"] == 1

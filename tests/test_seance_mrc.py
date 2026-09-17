"""Tests du lecteur `.MRC` (`seance.mrc`, lot F0.5).

Toutes les séances sont **fabriquées** pour ce test. Aucun réseau, aucun
fichier de configuration.
"""

from __future__ import annotations

from datetime import date

import pytest

from ourouler.erreurs import ErreurLecture
from ourouler.seance.mrc import lire_mrc

JOUR = date(2026, 9, 16)
FTP = 200.0  # inventée


def mrc(unite: str, lignes: str, *, description: str = "Séance test inventée") -> bytes:
    return (
        "[COURSE HEADER]\n"
        f"DESCRIPTION = {description}\n"
        f"MINUTES {unite}\n"
        "[END COURSE HEADER]\n"
        "[COURSE DATA]\n"
        f"{lignes}\n"
        "[END COURSE DATA]\n"
    ).encode()


def test_pourcentages_convertis_et_types_par_seuil():
    # 50 % = 100 W (sous le seuil 75 % = 150 W) puis 90 % = 180 W (au-dessus),
    # avec deux sauts verticaux (durée nulle) qui doivent être ignorés.
    doc = mrc(
        "PERCENT",
        "0.0\t50\n10.0\t50\n10.0\t90\n20.0\t90\n20.0\t50\n25.0\t50",
    )
    seance = lire_mrc(doc, ftp_w=FTP, jour=JOUR)

    assert [e.type for e in seance.etapes] == ["echauffement", "bloc", "calme"]
    echauffement, bloc, calme = seance.etapes
    assert echauffement.puissance_min_w == echauffement.puissance_max_w == pytest.approx(100.0)
    assert echauffement.duree_s == pytest.approx(600.0)
    assert echauffement.elastique is True
    assert bloc.puissance_min_w == bloc.puissance_max_w == pytest.approx(180.0)
    assert bloc.duree_s == pytest.approx(600.0)
    assert calme.puissance_min_w == calme.puissance_max_w == pytest.approx(100.0)
    assert calme.duree_s == pytest.approx(300.0)
    assert calme.elastique is True
    assert seance.meta["unite"] == "percent"
    assert seance.meta["conversion"].startswith("pourcentages de FTP convertis")
    assert seance.nom == "Séance test inventée"


def test_watts_directs_sans_ftp():
    doc = mrc("WATTS", "0.0\t120\n5.0\t120\n5.0\t250\n10.0\t250")
    seance = lire_mrc(doc, jour=JOUR)  # pas de FTP fournie, inutile en watts

    assert seance.meta["unite"] == "watts"
    assert "conversion" not in seance.meta  # rien à déclarer : c'était déjà des watts
    puissances = [e.puissance_cible_w for e in seance.etapes]
    assert puissances == [pytest.approx(120.0), pytest.approx(250.0)]


def test_rampe_garde_l_ordre_d_origine_dans_le_libelle():
    doc = mrc("WATTS", "0.0\t100\n5.0\t200")
    seance = lire_mrc(doc, jour=JOUR)
    (etape,) = seance.etapes
    assert etape.puissance_min_w == pytest.approx(100.0)
    assert etape.puissance_max_w == pytest.approx(200.0)
    assert "100-200" in etape.libelle

    doc_descendant = mrc("WATTS", "0.0\t200\n5.0\t100")
    (etape_descendante,) = lire_mrc(doc_descendant, jour=JOUR).etapes
    # Les bornes de `Etape` sont toujours remises dans l'ordre...
    assert etape_descendante.puissance_min_w == pytest.approx(100.0)
    assert etape_descendante.puissance_max_w == pytest.approx(200.0)
    # ...mais le libellé garde le sens de lecture d'origine, qui descend.
    assert "200-100" in etape_descendante.libelle


def test_sans_ftp_les_pourcentages_restent_non_convertis():
    doc = mrc("PERCENT", "0.0\t50\n10.0\t50\n10.0\t90\n20.0\t90")
    seance = lire_mrc(doc, ftp_w=None, jour=JOUR)

    assert all(e.puissance_min_w is None for e in seance.etapes)
    assert seance.meta["conversion"].startswith("FTP inconnue")
    assert seance.meta["etapes_sans_ftp"] == len(seance.etapes)
    # Sans FTP et sans watts calculables, aucun seuil n'est calculable non
    # plus : tout reste « bloc », on ne devine pas les types.
    assert all(e.type == "bloc" for e in seance.etapes)


def test_puissance_negative_est_ignoree():
    doc = mrc("WATTS", "0.0\t-50\n5.0\t-50")
    seance = lire_mrc(doc, jour=JOUR)
    (etape,) = seance.etapes
    assert etape.puissance_min_w is None
    assert etape.puissance_max_w is None


def test_entete_manquant():
    contenu = b"[COURSE DATA]\n0.0\t50\n10.0\t90\n[END COURSE DATA]\n"
    with pytest.raises(ErreurLecture, match="MINUTES"):
        lire_mrc(contenu, ftp_w=FTP, jour=JOUR)


def test_fichier_vide():
    with pytest.raises(ErreurLecture, match="vide"):
        lire_mrc(b"", ftp_w=FTP, jour=JOUR)


def test_moins_de_deux_points():
    doc = mrc("WATTS", "0.0\t100")
    with pytest.raises(ErreurLecture, match="deux points"):
        lire_mrc(doc, ftp_w=FTP, jour=JOUR)


def test_uniquement_des_sauts_verticaux():
    # Deux points à la même minute : durée nulle, aucune étape n'en sort.
    doc = mrc("WATTS", "10.0\t100\n10.0\t200")
    with pytest.raises(ErreurLecture, match="durée nulle"):
        lire_mrc(doc, ftp_w=FTP, jour=JOUR)


def test_fichier_tronque_sans_section_donnees():
    contenu = (
        b"[COURSE HEADER]\nDESCRIPTION = Coupee\nMINUTES PERCENT\n[END COURSE HEADER]\n"
    )
    with pytest.raises(ErreurLecture, match="deux points"):
        lire_mrc(contenu, ftp_w=FTP, jour=JOUR)


def test_jour_par_defaut_est_aujourdhui():
    doc = mrc("WATTS", "0.0\t100\n5.0\t150")
    seance = lire_mrc(doc, ftp_w=FTP)
    assert seance.jour == date.today()


def test_nom_explicite_prime_sur_la_description():
    doc = mrc("WATTS", "0.0\t100\n5.0\t150", description="Description du fichier")
    seance = lire_mrc(doc, ftp_w=FTP, jour=JOUR, nom="Nom donné par l'appelant")
    assert seance.nom == "Nom donné par l'appelant"

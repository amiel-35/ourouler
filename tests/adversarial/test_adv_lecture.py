"""L1.2 — lecteur unique FIT / GPX / TCX, mis à l'épreuve.

Cible : contrat §1. Les fichiers viennent de `fixtures/generer_hostiles.py`
(tous synthétiques, autour de (0.0, 0.0)). Trois tests garde-fous en tête de
module vérifient que les fixtures elles-mêmes sont ce qu'elles prétendent :
si l'encodeur du générateur se casse, c'est là que ça tombe, pas dans les
tests du lecteur.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import outils
import pytest

from ourouler.erreurs import ErreurLecture, ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L1.2 absent (ourouler.activites.lecture)"

# Instants UTC attendus dans les fichiers du changement d'heure (cf. générateur).
UTC_HEURE_ETE = [
    datetime(2026, 10, 25, 0, 59, tzinfo=UTC),
    datetime(2026, 10, 25, 1, 1, tzinfo=UTC),
    datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
    datetime(2026, 10, 25, 2, 0, tzinfo=UTC),
]
UTC_PRINTEMPS = [
    datetime(2026, 3, 29, 0, 59, tzinfo=UTC),
    datetime(2026, 3, 29, 1, 1, tzinfo=UTC),
    datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
    datetime(2026, 3, 29, 2, 0, tzinfo=UTC),
]


def _lecture():
    return pytest.importorskip("ourouler.activites.lecture", reason=MOTIF_ABSENT)


# --- garde-fous sur les fixtures --------------------------------------------


def test_le_catalogue_est_documente(generateur, hostiles):
    assert set(generateur.contenus()) == set(generateur.CATALOGUE), (
        "chaque fichier hostile doit être documenté dans CATALOGUE"
    )
    assert set(hostiles) == set(generateur.CATALOGUE)
    for nom, chemin in hostiles.items():
        assert chemin.exists(), nom


def test_le_fit_nominal_est_bien_un_fit(hostiles):
    fitdecode = pytest.importorskip("fitdecode")
    noms = []
    with fitdecode.FitReader(io.BytesIO(hostiles["nominal.fit"].read_bytes())) as fr:
        for trame in fr:
            if isinstance(trame, fitdecode.FitDataMessage):
                noms.append(trame.name)
    assert noms.count("record") == 60, "le FIT généré doit porter 60 records"
    assert "session" in noms and "file_id" in noms


def test_les_gpx_et_tcx_nominaux_sont_valides(hostiles):
    gpxpy = pytest.importorskip("gpxpy")
    gpx = gpxpy.parse(hostiles["nominal.gpx"].read_text(encoding="utf-8"))
    points = [p for t in gpx.tracks for s in t.segments for p in s.points]
    assert len(points) == 30
    racine = ET.fromstring(hostiles["nominal.tcx"].read_bytes())
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    assert len(racine.findall(".//t:Trackpoint", ns)) == 30


# --- choix du lecteur par extension -----------------------------------------


@pytest.mark.parametrize(
    "nom, source",
    [
        ("nominal.fit", "fit"),
        ("nominal_maj.FIT", "fit"),
        ("nominal.gpx", "gpx"),
        ("nominal_maj.GPX", "gpx"),
        ("nominal_mixte.Gpx", "gpx"),
        ("nominal.tcx", "tcx"),
        ("nominal_maj.TCX", "tcx"),
    ],
)
def test_extension_insensible_a_la_casse(hostiles, nom, source):
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite, source_attendue=source)


@pytest.mark.parametrize(
    "nom", ["activite.inconnu", "activite_sans_extension", "activite.fit.gz", "activite.gpx.bak"]
)
def test_extension_inconnue_refusee(hostiles, nom):
    lecture = _lecture()
    with pytest.raises(ErreurLecture) as capture:
        lecture.lire(hostiles[nom])
    assert nom in str(capture.value), "le message doit nommer le fichier fautif (contrat §1)"


def test_le_choix_se_fait_sur_l_extension_pas_sur_le_contenu(hostiles, tmp_path):
    """Un GPX déguisé en .tcx doit être refusé, pas reniflé."""
    lecture = _lecture()
    piege = tmp_path / "piege.tcx"
    piege.write_bytes(hostiles["nominal.gpx"].read_bytes())
    with pytest.raises(ErreurLecture):
        lecture.lire(piege)


def test_chemin_exotique_accepte(hostiles, tmp_path):
    lecture = _lecture()
    cible = tmp_path / "activité (1) — copie.GPX"
    cible.write_bytes(hostiles["nominal.gpx"].read_bytes())
    outils.verifier_activite(lecture.lire(cible), source_attendue="gpx")


def test_fichier_absent_ou_dossier(tmp_path):
    lecture = _lecture()
    with pytest.raises(ErreurUtilisateur):
        lecture.lire(tmp_path / "jamais_vu.gpx")
    dossier = tmp_path / "un_dossier.gpx"
    dossier.mkdir()
    with pytest.raises(ErreurUtilisateur):
        lecture.lire(dossier)


# --- entrées illisibles : ErreurLecture exigée -------------------------------


@pytest.mark.parametrize(
    "nom",
    [
        "vide.fit",
        "vide.gpx",
        "vide.tcx",
        "espaces_seuls.gpx",
        "tronque.fit",
        "entete_menteur.fit",
        "corps_aleatoire.fit",
        "xml_invalide.gpx",
        "xml_invalide.tcx",
        "gpx_sans_gps.gpx",
    ],
)
def test_fichier_illisible_leve_erreur_lecture(hostiles, nom):
    lecture = _lecture()
    with pytest.raises(ErreurLecture) as capture:
        lecture.lire(hostiles[nom])
    message = str(capture.value)
    assert nom in message, f"le message doit nommer le fichier ({message!r})"
    assert message.strip() and message.strip() != nom, "le message doit aussi donner la cause"


@pytest.mark.parametrize(
    "nom", ["entete_seul.fit", "gpx_sans_point.gpx", "pas_du_gpx.gpx", "tcx_sans_trackpoint.tcx"]
)
def test_fichier_sans_enregistrement_leve_erreur_lecture(hostiles, nom):
    """Contrat §1 : « FIT sans enregistrement » → ErreurLecture.

    Étendu ici aux GPX/TCX sans point : `Activite.debut` et `duree_s` ne sont
    pas optionnels, un fichier sans aucun point ne peut pas les remplir.
    """
    lecture = _lecture()
    with pytest.raises(ErreurLecture):
        lecture.lire(hostiles[nom])


@pytest.mark.parametrize("nom", ["crc_faux.fit", "tcx_sans_espaces_de_noms.tcx", "fit_sans_session.fit"])
def test_fichier_douteux_degrade_sans_bug(hostiles, nom):
    """Cas que le contrat ne tranche pas : refus propre ou lecture cohérente."""
    lecture = _lecture()
    activite, _ = outils.robuste(
        lambda: lecture.lire(hostiles[nom]), quoi=f"lire({nom})", erreurs_acceptees=(ErreurUtilisateur,)
    )
    if activite is not None:
        outils.verifier_activite(activite)


@pytest.mark.parametrize("nom", ["gpx_sans_temps.gpx", "gpx_temps_naif.gpx", "gpx_temps_absurde.gpx"])
def test_horodatages_absents_ou_illisibles(hostiles, nom):
    """Sans horodatage exploitable, `debut` est indéterminable : refus ou UTC assumé."""
    lecture = _lecture()
    activite, _ = outils.robuste(
        lambda: lecture.lire(hostiles[nom]), quoi=f"lire({nom})", erreurs_acceptees=(ErreurUtilisateur,)
    )
    if activite is not None:
        outils.verifier_activite(activite)


# --- absences légitimes : GPS, puissance -------------------------------------


@pytest.mark.parametrize("nom, source", [("fit_sans_gps.fit", "fit"), ("tcx_sans_gps.tcx", "tcx")])
def test_sans_gps_reste_valide(hostiles, nom, source):
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite, source_attendue=source)
    assert all(p.lat is None and p.lon is None for p in activite.points), (
        "aucun point ne doit inventer de position"
    )


@pytest.mark.parametrize(
    "nom, source",
    [
        ("fit_sans_puissance.fit", "fit"),
        ("gpx_sans_puissance.gpx", "gpx"),
        ("tcx_sans_puissance.tcx", "tcx"),
    ],
)
def test_sans_puissance_reste_valide_et_ne_vaut_pas_zero(hostiles, nom, source):
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite, source_attendue=source)
    assert all(p.puissance_w is None for p in activite.points), "puissance absente ≠ puissance nulle"
    assert activite.puissance_moy_w is None, "puissance_moy_w doit être None, pas 0.0"
    assert activite.puissance_np_w is None, "puissance_np_w doit être None, pas 0.0"


@pytest.mark.parametrize(
    "nom, source", [("nominal.fit", "fit"), ("nominal.gpx", "gpx"), ("nominal.tcx", "tcx")]
)
def test_fichier_complet_renseigne_les_champs(hostiles, nom, source):
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite, source_attendue=source)
    assert activite.debut == datetime(2026, 4, 12, 9, 0, tzinfo=UTC)
    attendu = 3540.0 if source == "fit" else 1740.0
    assert activite.duree_s == pytest.approx(attendu), "durée = dernier point − premier"
    assert activite.puissance_moy_w is not None and activite.puissance_moy_w > 0
    assert activite.puissance_np_w is not None and activite.puissance_np_w > 0
    assert all(p.lat is not None for p in activite.points)
    if activite.fichier is not None:
        assert Path(activite.fichier).name == nom, "`fichier` doit rappeler le chemin d'origine"


def test_le_denivele_est_lisse_et_non_cumule_a_l_aveugle(hostiles):
    """Le profil d'altitude monte et descend de 40 m tous les 5 points.

    Cumulé brut, cela fait 480 m sur le FIT nominal (12 cycles) : un dénivelé
    supérieur signerait un double comptage, un dénivelé négatif un signe
    inversé. Le contrat demande un calcul « lissé », donc au plus le brut.
    """
    lecture = _lecture()
    activite = lecture.lire(hostiles["nominal.fit"])
    if activite.denivele_m is None:
        pytest.skip("dénivelé non calculé par cette implémentation")
    assert 0.0 <= activite.denivele_m <= 480.0 + 1e-6, f"dénivelé suspect : {activite.denivele_m}"


# --- horodatages non monotones ----------------------------------------------


@pytest.mark.parametrize(
    "nom", ["fit_non_monotone.fit", "gpx_non_monotone.gpx", "tcx_non_monotone.tcx"]
)
def test_non_monotone_tolere_et_signale(hostiles, nom):
    """Contrat §1 : toléré, et signalé dans meta["avertissements"]."""
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite)
    avertissements = activite.meta.get("avertissements")
    assert avertissements, 'meta["avertissements"] doit signaler les horodatages non monotones'
    assert isinstance(avertissements, list), 'meta["avertissements"] : liste attendue (JSON)'
    assert all(isinstance(a, str) for a in avertissements), "chaque avertissement doit être lisible"


@pytest.mark.parametrize("nom", ["nominal.fit", "nominal.gpx", "nominal.tcx"])
def test_pas_d_avertissement_gratuit(hostiles, nom):
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    assert not activite.meta.get("avertissements"), (
        "un fichier propre ne doit pas produire d'avertissement"
    )


# --- changement d'heure ------------------------------------------------------


@pytest.mark.parametrize(
    "nom, source, attendus",
    [
        ("gpx_heure_ete.gpx", "gpx", UTC_HEURE_ETE),
        ("tcx_heure_ete.tcx", "tcx", UTC_HEURE_ETE),
        ("gpx_heure_ete_printemps.gpx", "gpx", UTC_PRINTEMPS),
    ],
)
def test_changement_d_heure_les_instants_restent_monotones_en_utc(hostiles, nom, source, attendus):
    """Fenêtre du changement d'heure, offsets mélangés (+02:00 puis +01:00).

    En heure locale de Paris ces points reculent (02:59 puis 02:01) ; en UTC
    ils avancent. Un lecteur qui passe par une heure locale naïve produit
    soit un avertissement fantôme, soit une durée négative.
    """
    lecture = _lecture()
    activite = lecture.lire(hostiles[nom])
    outils.verifier_activite(activite, source_attendue=source)
    assert [p.t for p in activite.points] == attendus
    assert activite.debut == attendus[0]
    assert activite.duree_s == pytest.approx(3660.0), "00:59 UTC → 02:00 UTC = 3660 s"
    assert not activite.meta.get("avertissements"), (
        "ces horodatages sont monotones en UTC : aucun avertissement attendu"
    )


# --- entrée en bytes ---------------------------------------------------------


@pytest.mark.parametrize(
    "fonction, nom",
    [("lire_fit", "nominal.fit"), ("lire_gpx", "nominal.gpx"), ("lire_tcx", "nominal.tcx")],
)
def test_lecteurs_acceptent_des_bytes(hostiles, fonction, nom):
    lecture = _lecture()
    lire_x = getattr(lecture, fonction)
    depuis_chemin = lire_x(hostiles[nom])
    depuis_octets = lire_x(hostiles[nom].read_bytes())
    outils.verifier_activite(depuis_octets)
    assert depuis_octets.debut == depuis_chemin.debut
    assert depuis_octets.duree_s == depuis_chemin.duree_s
    assert len(depuis_octets.points) == len(depuis_chemin.points)
    assert depuis_octets.fichier is None, "sans chemin d'origine, `fichier` vaut None"


@pytest.mark.parametrize("fonction", ["lire_fit", "lire_gpx", "lire_tcx"])
def test_lecteurs_refusent_des_bytes_vides(fonction):
    lecture = _lecture()
    with pytest.raises(ErreurLecture):
        getattr(lecture, fonction)(b"")


def test_un_seul_point_ne_casse_ni_la_duree_ni_la_puissance_normalisee(hostiles):
    """Une activité d'un point : durée nulle, aucune division par zéro, aucun NaN."""
    lecture = _lecture()
    activite = lecture.lire(hostiles["fit_un_point.fit"])
    outils.verifier_activite(activite, source_attendue="fit")
    assert len(activite.points) == 1
    assert activite.duree_s == 0.0

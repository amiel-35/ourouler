"""Tests du lecteur unique FIT / GPX / TCX (L1.2)."""

from __future__ import annotations

import math
import random
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ourouler.activites.lecture import _sans_preambule_xml, lire, lire_fit, lire_gpx, lire_tcx
from ourouler.noyau.activite import Point, denivele_positif, puissance_normalisee
from ourouler.noyau.erreurs import ErreurLecture, ErreurUtilisateur

TROIS_FORMATS = ["boucle.fit", "boucle.gpx", "boucle.tcx"]


# --- cas nominaux -------------------------------------------------------------


@pytest.mark.parametrize("nom", TROIS_FORMATS)
def test_lire_les_trois_formats(activites: Path, nom: str):
    a = lire(activites / nom)
    assert a.source == nom.rsplit(".", 1)[1]
    assert a.fichier and a.fichier.endswith(nom)
    assert a.debut == datetime(2024, 3, 30, 9, 0, tzinfo=UTC)
    assert a.debut.tzinfo is not None
    assert a.duree_s == pytest.approx(708, abs=1)
    assert len(a.points) == 60
    assert a.distance_m and 4000 < a.distance_m < 8000
    assert a.puissance_moy_w == pytest.approx(206.9, abs=0.5)
    assert a.denivele_m == pytest.approx(50.0, abs=1.0)
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
    assert lire(activites / "boucle.fit").duree_mouvement_s == pytest.approx(678, abs=1)
    assert lire(activites / "boucle.gpx").duree_mouvement_s is None
    assert lire(activites / "boucle.tcx").duree_mouvement_s is None


def test_extension_en_majuscules(activites: Path):
    a = lire(activites / "COURTE.GPX")
    assert a.source == "gpx"
    assert len(a.points) == 40


def test_lecteurs_acceptent_des_octets(activites: Path):
    for nom, lecteur in (
        ("boucle.fit", lire_fit),
        ("boucle.gpx", lire_gpx),
        ("boucle.tcx", lire_tcx),
    ):
        a = lecteur((activites / nom).read_bytes())
        assert a.fichier is None
        assert len(a.points) == 60


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


# --- L6.3 : préambule avant la déclaration XML ---------------------------------
#
# **Non vérifié sur les fichiers réels** : les neuf TCX Samsung Health
# 2020-2021 qui ont motivé ce lot sont introuvables sur cette machine (Q46 —
# import à venir). Ce qui suit teste une **cause plausible, reproduite sur
# fixture synthétique**, pas un constat sur les fichiers eux-mêmes : le
# critère « les neuf TCX refusés se lisent » reste ouvert.
#
# Un BOM UTF-8 **isolé**, immédiatement suivi de `<?xml ...?>`, se parse déjà
# sans erreur avec `ET.fromstring` sur cet environnement : ce cas-là ne
# distingue pas « corrigé » de « pas corrigé » et ne prouve donc rien. Les cas
# qui portent réellement l'erreur du ticket (« XML or text declaration not at
# start of entity ») sont un BOM suivi d'un saut de ligne, ou un simple espace
# avant la déclaration — c'est ce que couvrent les tests ci-dessous, en boîte
# blanche sur `_sans_preambule_xml` puis bout en bout, avec dans chaque cas un
# `pytest.raises` qui prouve que les octets bruts échouaient avant correctif
# (sans quoi le test resterait vert le jour où un parseur plus tolérant ne
# mesurerait plus rien — même idiome que `test_invariants.py`).
#
# Piste pour le jour où les fichiers réels seront disponibles : expat rend le
# même message pour **tout** `<?xml ...?>` qui n'est pas au tout premier
# octet, pas seulement pour un BOM ou un blanc — par exemple deux fichiers
# XML concaténés, ou du texte non blanc en tête. `_sans_preambule_xml` ne
# couvre que la branche BOM + blancs ; si les neuf fichiers réels persistent
# à échouer une fois relus, regarder d'abord ce qui précède leur premier `<`.


def test_sans_preambule_xml_retire_bom_et_blancs():
    """`_sans_preambule_xml` retire un préambule de BOM(s) et de blancs.

    C'est la fonction qui corrige L6.3. Un BOM nu (sans rien d'autre) est
    déjà accepté tel quel par `ET.fromstring` — ce n'est *pas* le bug. Le
    bug, c'est un BOM suivi d'un blanc, ou un blanc seul : ça, `ET.fromstring`
    le refuse avec « XML or text declaration not at start of entity ».
    """
    contenu = b'<?xml version="1.0" encoding="UTF-8"?><a/>'
    assert _sans_preambule_xml(b"\xef\xbb\xbf\n" + contenu) == contenu, "BOM + saut de ligne"
    assert _sans_preambule_xml(b" " + contenu) == contenu, "espace en tête"
    assert _sans_preambule_xml(b"\xef\xbb\xbf\xef\xbb\xbf \t" + contenu) == contenu, "combinaison"
    assert _sans_preambule_xml(contenu) == contenu, "rien à retirer : inchangé"
    # Sans `<` derrière, on ne retire rien : un fichier de blancs reste tel
    # quel, donc toujours détecté comme vide ou illisible en aval — pas
    # « corrigé » en un fichier valide qui ne contiendrait aucun XML.
    assert _sans_preambule_xml(b"   \n") == b"   \n"
    assert _sans_preambule_xml(b"\xef\xbb\xbf") == b"\xef\xbb\xbf"
    assert _sans_preambule_xml(b"") == b""


def test_bom_saut_de_ligne_tcx_est_tolere(generateur, tmp_path: Path):
    """Bout en bout : un TCX avec BOM + saut de ligne avant `<?xml` se lit.

    Octets jetables dans `tmp_path`, pas dans le dossier partagé
    `tests/fixtures/activites/` : une trace à un seul point y serait comptée
    comme une vraie sortie par l'inventaire, alors que c'est le genre de cas
    dégénéré catalogué « hostile » ailleurs (`fit_un_point.fit`).
    """
    xml = generateur.encoder_tcx(generateur.trajectoire(n=1)).encode("utf-8")
    octets = b"\xef\xbb\xbf\n" + xml
    with pytest.raises(ET.ParseError):
        ET.fromstring(octets)  # sans le correctif, ces octets étaient refusés

    chemin = tmp_path / "bom_saut_de_ligne.tcx"
    chemin.write_bytes(octets)
    a = lire(chemin)
    assert a.source == "tcx"
    assert a.points
    assert a.debut is not None


def test_espace_en_tete_gpx_est_tolere(generateur, tmp_path: Path):
    """Bout en bout : un GPX avec un espace avant `<?xml` se lit (même mécanisme)."""
    xml = generateur.encoder_gpx(generateur.trajectoire(n=1)).encode("utf-8")
    octets = b" " + xml
    with pytest.raises(ET.ParseError):
        ET.fromstring(octets)  # sans le correctif, ces octets étaient refusés

    chemin = tmp_path / "espace_en_tete.gpx"
    chemin.write_bytes(octets)
    a = lire(chemin)
    assert a.source == "gpx"
    assert a.points
    assert a.debut is not None


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


# --- NP et échantillonnage irrégulier ---------------------------------------
#
# Tests qui auraient attrapé B1 : la moyenne extérieure des puissances⁴ était
# faite par échantillon et non pondérée par la durée. Un même effort physique
# donnait 315,1 W ou 196,4 W au lieu de 275 W selon la façon de l'enregistrer.

#: Profil physique unique : 900 s à 320 W, 900 s à 150 W, ondulation de ±30 W.
#: Les variations sont lentes devant le pas le plus grossier testé (10 s), donc
#: un échantillonnage grossier décrit bien le même effort — sans quoi la
#: comparaison n'aurait aucun sens.
def profil_physique(t: float) -> float:
    if t < 900:
        return 320.0 + 30.0 * math.sin(t / 23.0)
    return 150.0 + 20.0 * math.sin(t / 23.0)


def points_du_profil(pas: Callable[[int, float], float], duree_s: float = 1800.0) -> list[Point]:
    """Échantillonne `profil_physique` avec un pas quelconque, éventuellement variable."""
    t0 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    points: list[Point] = []
    t, i = 0.0, 0
    while t <= duree_s:
        points.append(Point(t=t0 + timedelta(seconds=t), puissance_w=profil_physique(t)))
        t += pas(i, t)
        i += 1
    return points


#: Le même profil à 0,1 s : la valeur de référence, 275,1 W.
def np_de_reference() -> float:
    valeur = puissance_normalisee(points_du_profil(lambda i, t: 0.1))
    assert valeur is not None
    return valeur


def test_np_de_reference_du_profil():
    assert np_de_reference() == pytest.approx(275.1, abs=0.1)


@pytest.mark.parametrize(
    "nom, pas",
    [
        ("1 s constant", lambda i, t: 1.0),
        ("2 s constant", lambda i, t: 2.0),
        ("5 s constant", lambda i, t: 5.0),
        ("10 s constant", lambda i, t: 10.0),
        # Les deux cas qui faussaient la NP : une moitié enregistrée dix fois
        # plus densément que l'autre, dans un sens puis dans l'autre.
        ("1 s puis 10 s", lambda i, t: 1.0 if t < 900 else 10.0),
        ("10 s puis 1 s", lambda i, t: 10.0 if t < 900 else 1.0),
        # Pas irrégulier de 1 à 9 s, sans motif aligné sur le profil.
        ("pas irrégulier", lambda i, t: 1.0 + (i * 7) % 9),
    ],
)
def test_np_ne_depend_pas_de_l_echantillonnage(nom: str, pas: Callable[[int, float], float]):
    """Même profil physique, sept échantillonnages : la NP doit tenir à 1 %."""
    reference = np_de_reference()
    mesure = puissance_normalisee(points_du_profil(pas))
    assert mesure is not None
    ecart = abs(mesure - reference) / reference
    assert ecart < 0.01, f"{nom} : {mesure:.1f} W contre {reference:.1f} W ({ecart:.1%})"


def test_np_les_deux_echantillonnages_du_relecteur_donnent_la_meme_np():
    """Le cas exact mesuré en relecture : 1 s constant contre 1 s puis 10 s."""
    regulier = puissance_normalisee(points_du_profil(lambda i, t: 1.0))
    dense_puis_creux = puissance_normalisee(points_du_profil(lambda i, t: 1.0 if t < 900 else 10.0))
    assert regulier is not None and dense_puis_creux is not None
    assert dense_puis_creux == pytest.approx(regulier, rel=0.01)


def test_np_constante_meme_a_pas_irregulier():
    """Une puissance constante reste sa propre NP, quel que soit le pas."""
    t0 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    instants = [0, 1, 2, 3, 10, 11, 30, 31, 32, 90, 200, 201, 400]
    points = [Point(t=t0 + timedelta(seconds=s), puissance_w=180.0) for s in instants]
    assert puissance_normalisee(points) == pytest.approx(180.0)


def test_np_tous_les_points_au_meme_instant_se_reduit_a_la_moyenne():
    """Cas dégénéré : sans durée, pondérer n'a pas de sens, pas de division par zéro."""
    t0 = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    points = [Point(t=t0, puissance_w=w) for w in (100.0, 200.0, 300.0)]
    assert puissance_normalisee(points) == pytest.approx(200.0)


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


# --- FIT à plusieurs sessions -----------------------------------------------
#
# Tests qui auraient attrapé B2 : `duree_mouvement_s` et `distance_m` étaient
# réaffectés à chaque trame `session`, alors que `sport` était protégé par
# `sport or ...`. Un fichier multisport, ou une sortie coupée en deux,
# rapportait donc la distance du **dernier tronçon seulement**, en silence.


def test_fit_deux_sessions_somme_les_distances(generateur):
    """Une sortie coupée en deux : la distance est celle des deux tronçons."""
    trace = generateur.trajectoire(n=200)
    premier, second = trace[:100], trace[100:]
    octets = generateur.encoder_fit_multisession([premier, second])

    distance_1 = premier[-1].dist_m - premier[0].dist_m
    distance_2 = second[-1].dist_m - second[0].dist_m
    assert distance_2 < distance_1 * 3, "les deux tronçons doivent être distinguables"

    activite = lire_fit(octets)
    assert activite.distance_m == pytest.approx(distance_1 + distance_2, rel=1e-3)
    assert activite.distance_m != pytest.approx(distance_2, rel=1e-3), (
        "c'était le bug : seule la dernière session comptait"
    )


def test_fit_deux_sessions_somme_les_durees_de_mouvement(generateur):
    trace = generateur.trajectoire(n=200)
    premier, second = trace[:100], trace[100:]
    une_seule = lire_fit(generateur.encoder_fit_multisession([second]))
    deux = lire_fit(generateur.encoder_fit_multisession([premier, second]))
    assert une_seule.duree_mouvement_s is not None
    assert deux.duree_mouvement_s is not None
    assert deux.duree_mouvement_s > une_seule.duree_mouvement_s


def test_fit_deux_sessions_avertit_dans_meta(generateur):
    """Le lecteur ne doit pas cumuler en silence : l'inventaire doit pouvoir le dire."""
    trace = generateur.trajectoire(n=200)
    activite = lire_fit(generateur.encoder_fit_multisession([trace[:100], trace[100:]]))
    assert activite.meta.get("sessions") == 2
    avertissements = " ".join(activite.avertissements)
    assert "session" in avertissements, activite.avertissements
    assert "2" in avertissements


def test_fit_trois_sessions(generateur):
    trace = generateur.trajectoire(n=210)
    troncons = [trace[:70], trace[70:140], trace[140:]]
    attendu = sum(t[-1].dist_m - t[0].dist_m for t in troncons)
    activite = lire_fit(generateur.encoder_fit_multisession(troncons))
    assert activite.distance_m == pytest.approx(attendu, rel=1e-3)
    assert activite.meta.get("sessions") == 3


def test_fit_une_seule_session_n_avertit_pas(generateur):
    """Le cas courant ne doit pas hériter d'un avertissement ni d'un champ en trop."""
    activite = lire_fit(generateur.encoder_fit(generateur.trajectoire(n=120)))
    assert "sessions" not in activite.meta
    assert all("session" not in a for a in activite.avertissements), activite.avertissements


def test_fit_deux_sessions_garde_tous_les_points(generateur):
    trace = generateur.trajectoire(n=200)
    activite = lire_fit(generateur.encoder_fit_multisession([trace[:100], trace[100:]]))
    assert len(activite.points) == 200

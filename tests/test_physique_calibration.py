"""La calibration : échantillonnage, ajustement, validation, détection de groupe.

Toutes les données sont **fabriquées par le modèle lui-même** : on lui donne
un CdA et un Crr, on en déduit des vitesses, on bruite, et on vérifie qu'il
les retrouve. Aucune coordonnée réelle (tout part du point (0, 0)), aucune
donnée du mainteneur, aucun réseau.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.config import depuis_dict
from ourouler.noyau.activite import Activite, Point
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.meteo import HeureArchive
from ourouler.physique.calibration import (
    CDA_MAX,
    MASSE_VELO_DEFAUT_KG,
    Echantillon,
    Parametres,
    SortieCalibration,
    calibrer,
    calibrer_en_deux_passes,
    detecter_groupe,
    echantillonner,
    motif_multisport,
    partager,
    valider,
)
from ourouler.physique.echantillonnage import DELTA_V_MAX_MS, LONGUEUR_ECHANTILLON_M
from ourouler.physique.modele import (
    FACTEUR_VENT_HAUTEUR,
    RHO_DEFAUT,
    puissance_requise,
    vent_au_cycliste,
    vitesse_regime,
)
from ourouler.physique.validation import puissance_moyenne_en_mouvement, temps_mouvement_s
from ourouler.services.calibrer import (
    masse_totale_kg,
    motif_exclusion,
    sorties_calibrables,
    sorties_calibrables_et_motifs,
)

MASSE = 100.0
CDA_VRAI = 0.31
CRR_VRAI = 0.0045
VRAI = Parametres(masse_totale_kg=MASSE, cda_m2=CDA_VRAI, crr=CRR_VRAI)

DEPART = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
METRE_EN_DEGRE = 1.0 / 111_194.93


# --- fabriques ----------------------------------------------------------------


def archive(vent_kmh: float = 0.0, depuis_deg: float = 0.0, temp_c: float = 15.0):
    """24 heures d'archive constante, comme si le vent ne tournait pas."""
    return [
        HeureArchive(
            t=DEPART.replace(hour=h, minute=0),
            vent_kmh=vent_kmh,
            vent_depuis_deg=depuis_deg,
            temp_c=temp_c,
            pression_hpa=1013.25,
        )
        for h in range(24)
    ]


def vent_archive_kmh(face_ms: float) -> float:
    """Le vent **d'archive** (10 m) qui donne `face_ms` à hauteur de cycliste.

    Les sorties fabriquées le sont avec un vent subi ; l'archive, elle, est
    donnée à 10 m du sol. Sans cette conversion, les tests fabriqueraient une
    sortie avec un vent et la reliraient avec un autre.
    """
    return abs(face_ms) * 3.6 / FACTEUR_VENT_HAUTEUR


def puissance_ondulante(seconde: int) -> float:
    """Puissance qui ondule lentement : l'accélération entre deux échantillons
    voisins reste sous le seuil de rejet de 0,3 m/s."""
    return 200.0 + 15.0 * math.sin(seconde / 400.0)


def sortie_synthetique(
    p: Parametres = VRAI,
    *,
    duree_s: int = 2600,
    pente: float = 0.0,
    vent_face_ms: float = 0.0,
    facteur_vitesse: float = 1.0,
    rho: float = RHO_DEFAUT,
    nom: str = "sortie fabriquée",
    puissances: Callable[[int], float] = puissance_ondulante,
) -> Activite:
    """Une sortie plein est dont chaque seconde est **la solution du modèle**.

    `facteur_vitesse` permet de fabriquer une sortie qui va plus vite que ce
    que sa puissance justifie — c'est ainsi qu'on imite un peloton.
    """
    modele = Parametres(
        masse_totale_kg=p.masse_totale_kg,
        cda_m2=p.cda_m2,
        crr=p.crr,
        rendement=p.rendement,
        rho=rho,
    )
    points = []
    distance = 0.0
    altitude = 100.0
    for seconde in range(duree_s):
        puissance = puissances(seconde)
        v = vitesse_regime(puissance, pente, vent_face_ms, modele) * facteur_vitesse
        points.append(
            Point(
                t=DEPART + timedelta(seconds=seconde),
                lat=0.0,
                lon=distance * METRE_EN_DEGRE,
                alt_m=altitude,
                dist_m=distance,
                vitesse_ms=v,
                puissance_w=puissance,
            )
        )
        distance += v
        altitude += v * pente
    return Activite(
        source="fit",
        fichier=None,
        debut=DEPART,
        duree_s=float(duree_s - 1),
        duree_mouvement_s=float(duree_s - 1),
        distance_m=distance,
        denivele_m=max(0.0, duree_s * pente),
        puissance_moy_w=200.0,
        puissance_np_w=200.0,
        sport="cycling",
        appareil=None,
        points=points,
        meta={"nom": nom},
    )


def echantillons_synthetiques(
    n: int = 400, *, bruit_w: float = 10.0, p: Parametres = VRAI, graine: int = 1
) -> list[Echantillon]:
    """`n` échantillons dont la puissance est celle du modèle, plus un bruit gaussien."""
    alea = random.Random(graine)
    echantillons = []
    for _ in range(n):
        v = alea.uniform(5.0, 14.0)
        pente = alea.uniform(-0.03, 0.08)
        vent = alea.uniform(-5.0, 5.0)
        puissance = puissance_requise(v, pente, vent, p) + alea.gauss(0.0, bruit_w)
        echantillons.append(
            Echantillon(
                v_ms=v,
                puissance_w=puissance,
                pente=pente,
                vent_face_ms=vent,
                temp_c=15.0,
                retenu=True,
                motif="",
                longueur_m=200.0,
                rho=p.rho,
            )
        )
    return echantillons


def echantillons_avec_acceleration(
    n: int = 400,
    *,
    p: Parametres = VRAI,
    graine: int = 7,
    bruit_w: float = 0.0,
    dv_min: float = -0.9,
    dv_max: float = 0.9,
) -> list[Echantillon]:
    """Des tronçons où le cycliste **accélère**, d'une quantité connue.

    La puissance de chacun est la somme exacte de deux termes : celle qu'exige
    l'équilibre à la vitesse moyenne, et celle qu'a coûtée la variation
    d'énergie cinétique entre les deux bouts. C'est le cas que le point 2 de la
    relecture veut savoir traiter : il ne s'agit plus de jeter ces tronçons
    mais de leur retrancher ce qu'on sait d'eux.
    """
    alea = random.Random(graine)
    echantillons = []
    for _ in range(n):
        v = alea.uniform(6.0, 13.0)
        pente = alea.uniform(-0.03, 0.05)
        vent = alea.uniform(-4.0, 4.0)
        longueur = LONGUEUR_ECHANTILLON_M
        duree = longueur / v
        dv = alea.uniform(dv_min, dv_max)
        v_debut, v_fin = v - dv / 2, v + dv / 2
        cinetique = p.masse_totale_kg * (v_fin**2 - v_debut**2) / (2 * duree) / p.rendement
        echantillons.append(
            Echantillon(
                v_ms=v,
                puissance_w=puissance_requise(v, pente, vent, p)
                + cinetique
                + alea.gauss(0.0, bruit_w),
                pente=pente,
                vent_face_ms=vent,
                temp_c=15.0,
                retenu=True,
                motif="",
                longueur_m=longueur,
                rho=p.rho,
                v_debut_ms=v_debut,
                v_fin_ms=v_fin,
            )
        )
    return echantillons


# --- échantillonnage ----------------------------------------------------------


def test_echantillonner_retrouve_vitesse_pente_et_vent():
    """Sur une sortie fabriquée à 2 % avec 18 km/h de face, les trois sont retrouvés."""
    vent_ms = 5.0
    activite = sortie_synthetique(pente=0.02, vent_face_ms=vent_ms)
    # Le tracé va plein est (cap 90°) : un vent qui vient de l'est est de face.
    echantillons = echantillonner(
        activite, archive(vent_kmh=vent_archive_kmh(vent_ms), depuis_deg=90.0)
    )
    retenus = [e for e in echantillons if e.retenu]
    assert len(retenus) > 40
    milieu = retenus[len(retenus) // 2]
    assert milieu.pente == pytest.approx(0.02, abs=0.002)
    assert milieu.vent_face_ms == pytest.approx(vent_ms, abs=0.01)
    assert milieu.longueur_m == pytest.approx(200.0, abs=15.0)
    attendue = vitesse_regime(milieu.puissance_w, 0.02, vent_ms, VRAI)
    assert milieu.v_ms == pytest.approx(attendue, rel=0.02)


def test_vent_de_dos_est_negatif():
    activite = sortie_synthetique(duree_s=800)
    # Vent venant de l'ouest (270°) alors qu'on va vers l'est : de dos.
    echantillons = echantillonner(activite, archive(vent_kmh=18.0, depuis_deg=270.0))
    assert echantillons[-1].vent_face_ms == pytest.approx(-5.0 * FACTEUR_VENT_HAUTEUR, abs=0.01)


def test_le_vent_d_archive_est_ramene_a_hauteur_de_cycliste():
    """18 km/h de face à 10 m ne sont plus que 0,6 × 5 m/s pour le cycliste.

    C'est le point 1 de la relecture Fable : l'archive et la prévision donnent
    le vent à 10 m, le modèle en attend un à 1,5 m. Sans cette conversion, le
    régresseur aérodynamique est bâti sur un vent trop fort.
    """
    activite = sortie_synthetique(duree_s=800)
    echantillons = echantillonner(activite, archive(vent_kmh=18.0, depuis_deg=90.0))
    subi = echantillons[-1].vent_face_ms
    assert subi == pytest.approx(vent_au_cycliste(5.0), abs=0.01)
    assert subi == pytest.approx(5.0 * 0.6, abs=0.01)
    # Et l'aller-retour est exact : le vent d'archive qu'on fabrique pour
    # obtenir 5 m/s subis redonne bien 5 m/s.
    a_5_ms = echantillonner(activite, archive(vent_kmh=vent_archive_kmh(5.0), depuis_deg=90.0))
    assert a_5_ms[-1].vent_face_ms == pytest.approx(5.0, abs=0.01)


def test_vent_de_travers_est_nul():
    activite = sortie_synthetique(duree_s=800)
    echantillons = echantillonner(activite, archive(vent_kmh=18.0, depuis_deg=0.0))
    assert echantillons[-1].vent_face_ms == pytest.approx(0.0, abs=0.01)


def test_archive_vide_donne_un_vent_inconnu_et_nul():
    echantillons = echantillonner(sortie_synthetique(duree_s=800), [])
    assert echantillons
    assert all(e.vent_face_ms == 0.0 and not e.vent_connu for e in echantillons)


def test_archive_qui_ne_couvre_pas_l_heure():
    """L'archive d'un autre jour ne doit pas être extrapolée."""
    veille = [
        HeureArchive(
            t=DEPART.replace(day=14, hour=h), vent_kmh=20.0, vent_depuis_deg=90.0,
            temp_c=10.0, pression_hpa=1000.0,
        )
        for h in range(24)
    ]
    echantillons = echantillonner(sortie_synthetique(duree_s=800), veille)
    assert all(not e.vent_connu for e in echantillons)


def test_les_deux_premiers_kilometres_sont_ecartes():
    echantillons = echantillonner(sortie_synthetique(), archive())
    debuts = [e for e in echantillons if e.dist_m - e.longueur_m < 2000.0]
    assert debuts and all(e.motif == "départ" for e in debuts)


def test_un_arret_jette_l_echantillon():
    activite = sortie_synthetique()
    for p in activite.points[1200:1260]:
        p.vitesse_ms = 0.0
    echantillons = echantillonner(activite, archive())
    assert any(e.motif == "arrêt" for e in echantillons)


def test_pente_hors_bornes_jetee():
    """Une descente à −8 % sort des bornes [−3 %, +8 %] et n'est pas calibrable.

    C'est la descente qu'on prend en exemple, pas la montée : à 200 W pour
    100 kg, toute pente au-dessus de 8 % met le cycliste sous 8 km/h, donc
    sous le filtre de vitesse — la borne haute de pente ne mord presque jamais.
    """
    echantillons = echantillonner(sortie_synthetique(pente=-0.08, duree_s=600), archive())
    assert echantillons
    assert not [e for e in echantillons if e.retenu]
    assert any(e.motif == "pente" for e in echantillons)


def test_puissance_hors_bornes_jetee():
    activite = sortie_synthetique(duree_s=1500)
    for p in activite.points[1000:1400]:
        p.puissance_w = 20.0
    echantillons = echantillonner(activite, archive())
    assert any(e.motif == "puissance" for e in echantillons)


def test_acceleration_forte_jetee():
    """Une marche de puissance fait sauter la vitesse : les tronçons voisins sont jetés."""
    activite = sortie_synthetique(
        duree_s=2000, puissances=lambda s: 120.0 if s < 1000 else 400.0
    )
    echantillons = echantillonner(activite, archive())
    assert any(e.motif == "accélération" for e in echantillons)
    # Seuil relâché à 1,0 m/s (point 2 de la relecture) : depuis que la
    # variation d'énergie cinétique est comptée, seuls les sauts brutaux
    # restent à écarter.
    assert DELTA_V_MAX_MS == 1.0


def test_la_pente_ne_depend_pas_de_la_densite_des_points():
    """Un point tous les 200 m ou un point par seconde : la même pente.

    Le lissage d'altitude se compte en **mètres**, pas en nombre de points.
    Compté en points, il s'étalait sur 2 200 m pour une trace allégée et la
    pente d'une sortie à 14 % y tombait à 7 % — assez pour passer sous la
    borne de +8 % et polluer la calibration.
    """
    dense = sortie_synthetique(pente=0.14, duree_s=1200)
    clairseme = Activite(**{**dense.__dict__, "points": dense.points[::40]})
    assert len(clairseme.points) < 40
    for activite, quoi in ((dense, "1 Hz"), (clairseme, "allégée")):
        echantillons = echantillonner(activite, archive())
        assert echantillons, quoi
        assert all(e.pente > 0.12 for e in echantillons), quoi
        assert not [e for e in echantillons if e.retenu], quoi


def test_une_sortie_sans_puissance_ne_donne_pas_de_nan():
    """Sans capteur : motif « sans puissance » et un zéro inoffensif, jamais un NaN."""
    activite = sortie_synthetique(duree_s=1200)
    for p in activite.points:
        p.puissance_w = None
    echantillons = echantillonner(activite, archive())
    assert echantillons
    assert all(math.isfinite(e.puissance_w) for e in echantillons)
    assert all(not e.retenu and e.motif == "sans puissance" for e in echantillons)


def test_tout_echantillon_ecarte_porte_un_motif():
    activite = sortie_synthetique(pente=-0.08, duree_s=900)
    for e in echantillonner(activite, archive()):
        assert e.retenu != bool(e.motif.strip())


def test_sortie_trop_courte_ne_donne_aucun_echantillon():
    courte = sortie_synthetique(duree_s=5)
    assert echantillonner(courte, archive()) == []
    vide = Activite(
        source="fit", fichier=None, debut=DEPART, duree_s=0.0, duree_mouvement_s=None,
        distance_m=0.0, denivele_m=None, puissance_moy_w=None, puissance_np_w=None,
        sport="cycling", appareil=None, points=[],
    )
    assert echantillonner(vide, archive()) == []


# --- ajustement ---------------------------------------------------------------


def test_calibrer_retrouve_cda_et_crr_a_cinq_pour_cent():
    """Le cœur du lot : des échantillons fabriqués par le modèle, bruités, sont inversés."""
    ajustement = calibrer(echantillons_synthetiques(), masse_totale_kg=MASSE)
    assert ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=0.05)
    assert ajustement.crr == pytest.approx(CRR_VRAI, rel=0.05)
    assert ajustement.n_echantillons == 400
    assert ajustement.bornes_atteintes == ()
    assert ajustement.rmse_w == pytest.approx(10.0, rel=0.3)


def test_calibrer_sans_bruit_est_exact():
    ajustement = calibrer(echantillons_synthetiques(bruit_w=0.0), masse_totale_kg=MASSE)
    assert ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=1e-6)
    assert ajustement.crr == pytest.approx(CRR_VRAI, rel=1e-6)
    assert ajustement.rmse_w == pytest.approx(0.0, abs=1e-6)


def test_l_incertitude_diminue_quand_les_echantillons_augmentent():
    peu = calibrer(echantillons_synthetiques(40, graine=2), masse_totale_kg=MASSE)
    beaucoup = calibrer(echantillons_synthetiques(1000, graine=2), masse_totale_kg=MASSE)
    assert peu.incertitudes.cda is not None and beaucoup.incertitudes.cda is not None
    assert beaucoup.incertitudes.cda < peu.incertitudes.cda


def test_calibrer_n_utilise_que_les_echantillons_retenus():
    echantillons = echantillons_synthetiques(bruit_w=0.0)
    for e in echantillons[:200]:
        e.puissance_w = 999.0  # aberrants…
        e.retenu = False  # …mais écartés
        e.motif = "puissance"
    ajustement = calibrer(echantillons, masse_totale_kg=MASSE)
    assert ajustement.n_echantillons == 200
    assert ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=1e-6)


def test_les_bornes_sont_respectees():
    """Un CdA vrai de 1,0 m² (impossible à vélo) est ramené à la borne, et c'est dit."""
    hors = Parametres(masse_totale_kg=MASSE, cda_m2=1.0, crr=CRR_VRAI)
    ajustement = calibrer(
        echantillons_synthetiques(p=hors, bruit_w=0.0), masse_totale_kg=MASSE
    )
    assert ajustement.cda_m2 == pytest.approx(CDA_MAX)
    assert ajustement.bornes_atteintes
    assert "CdA" in ajustement.bornes_atteintes[0]


def test_la_borne_ne_se_contente_pas_d_ecreter():
    """À CdA bloqué en butée, le Crr rendu doit être le meilleur *à cette butée*.

    Écrêter les deux coordonnées de la solution libre donnerait un couple qui
    n'est pas le minimum du pavé : on vérifie qu'aucun autre Crr ne fait mieux.
    """
    hors = Parametres(masse_totale_kg=MASSE, cda_m2=1.0, crr=CRR_VRAI)
    echantillons = echantillons_synthetiques(p=hors, bruit_w=0.0)
    ajustement = calibrer(echantillons, masse_totale_kg=MASSE)
    trouve = ajustement.parametres()

    def ecart(crr: float) -> float:
        essai = Parametres(masse_totale_kg=MASSE, cda_m2=trouve.cda_m2, crr=crr)
        return sum(
            (puissance_requise(e.v_ms, e.pente, e.vent_face_ms, essai) - e.puissance_w) ** 2
            for e in echantillons
        )

    # Les essais restent **dans** les bornes : hors bornes, un Crr plus grand
    # ferait évidemment mieux — c'est justement ce que la borne interdit.
    essais = [c for c in (0.002, 0.004, 0.006, 0.008, 0.010, 0.012) if c != ajustement.crr]
    assert ecart(ajustement.crr) <= min(ecart(c) for c in essais)
    assert ajustement.crr == pytest.approx(0.012)  # butée haute du Crr


def test_trop_peu_d_echantillons():
    for n in (0, 1, 2):
        with pytest.raises(ErreurUtilisateur, match="échantillon"):
            calibrer(echantillons_synthetiques(n), masse_totale_kg=MASSE)


def test_echantillons_tous_identiques_ne_font_pas_exploser():
    """CdA et Crr ne sont plus séparables : on le dit, on ne rend pas n'importe quoi."""
    unique = Echantillon(
        v_ms=8.0, puissance_w=180.0, pente=0.0, vent_face_ms=0.0, temp_c=15.0,
        retenu=True, motif="", longueur_m=200.0,
    )
    ajustement = calibrer([unique] * 20, masse_totale_kg=MASSE)
    assert ajustement.avertissements
    assert 0.18 <= ajustement.cda_m2 <= 0.60
    assert 0.002 <= ajustement.crr <= 0.012


def test_masse_absurde_refusee():
    with pytest.raises(ErreurUtilisateur, match="masse"):
        calibrer(echantillons_synthetiques(50), masse_totale_kg=0.0)


# --- temps en mouvement et profil de puissance --------------------------------


def test_temps_mouvement_deduit_les_arrets():
    activite = sortie_synthetique(duree_s=1000)
    for p in activite.points[400:500]:
        p.vitesse_ms = 0.0
    assert temps_mouvement_s(activite) == pytest.approx(899.0, abs=2.0)


def test_temps_mouvement_sans_vitesse_retombe_sur_la_source():
    activite = sortie_synthetique(duree_s=600)
    for p in activite.points:
        p.vitesse_ms = None
    assert temps_mouvement_s(activite) == pytest.approx(599.0)


def test_puissance_moyenne_en_mouvement_ignore_les_arrets():
    activite = sortie_synthetique(duree_s=1200)
    for p in activite.points[400:600]:
        p.vitesse_ms = 0.0
        p.puissance_w = 0.0
    moyenne = puissance_moyenne_en_mouvement(activite)
    assert moyenne is not None and moyenne > 150.0


# --- validation ---------------------------------------------------------------


def test_valider_sur_une_sortie_fabriquee_par_le_modele():
    """Boucle fermée : le modèle rejoue ce qu'il a lui-même produit, à 1 % près."""
    activite = sortie_synthetique(duree_s=2600)
    validation = valider([(activite, archive())], VRAI)
    assert validation.n == 1
    assert abs(validation.sorties[0].erreur_relative) < 0.01
    assert validation.mae is not None and validation.mae < 0.01


def test_valider_voit_un_cda_trop_grand():
    activite = sortie_synthetique(duree_s=2600)
    trop = Parametres(masse_totale_kg=MASSE, cda_m2=CDA_VRAI * 1.5, crr=CRR_VRAI)
    validation = valider([(activite, archive())], trop)
    # Plus de traînée que la réalité : le modèle prédit plus lent.
    assert validation.biais is not None and validation.biais > 0.05


def test_valider_tient_compte_du_vent():
    """Une sortie faite avec 5 m/s de face n'est explicable qu'avec ce vent."""
    activite = sortie_synthetique(duree_s=2600, vent_face_ms=5.0)
    avec = valider([(activite, archive(vent_kmh=vent_archive_kmh(5.0), depuis_deg=90.0))], VRAI)
    sans = valider([(activite, archive(vent_kmh=0.0))], VRAI)
    assert abs(avec.sorties[0].erreur_relative) < 0.02
    assert sans.sorties[0].erreur_relative < -0.10  # sans vent, le modèle se croit rapide


def test_valider_ignore_une_sortie_inexploitable():
    sans_position = sortie_synthetique(duree_s=600)
    for p in sans_position.points:
        p.lat = p.lon = None
    assert valider([(sans_position, archive())], VRAI).n == 0


def test_validation_vide():
    validation = valider([], VRAI)
    assert validation.n == 0 and validation.mae is None and validation.pire is None


def test_la_validation_est_serialisable_en_json():
    """Le rapport existe en texte et en JSON : les lignes par sortie doivent passer.

    D'où `ErreurSortie` en `NamedTuple` avec un jour en chaîne ISO : une
    dataclass portant une `date` faisait échouer `json.dumps` sur le rapport.
    """
    validation = valider([(sortie_synthetique(duree_s=1500), archive())], VRAI)
    assert validation.n == 1
    for nom in (n for n in dir(validation) if not n.startswith("_")):
        valeur = getattr(validation, nom)
        if isinstance(valeur, (list, dict)):
            json.dumps(valeur)  # ne doit pas lever
    assert validation.sorties[0].jour == "2026-03-15"


# --- détection de groupe ------------------------------------------------------


def test_detecter_groupe_faux_sur_une_sortie_conforme():
    conforme = sortie_synthetique(duree_s=2600)
    en_groupe, part = detecter_groupe(conforme, VRAI, archive())
    assert not en_groupe
    assert part < 0.1


def test_detecter_groupe_vrai_sur_une_sortie_vingt_pour_cent_trop_rapide():
    peloton = sortie_synthetique(duree_s=2600, facteur_vitesse=1.20)
    en_groupe, part = detecter_groupe(peloton, VRAI, archive())
    assert en_groupe
    assert part > 0.9


def test_detecter_groupe_sur_une_sortie_sans_echantillon():
    assert detecter_groupe(sortie_synthetique(duree_s=5), VRAI, archive()) == (False, 0.0)


def test_un_vent_de_dos_ignore_ferait_croire_a_un_groupe():
    """Sans le vent, une sortie poussée par 6 m/s passe pour un peloton.

    C'est la justification chiffrée de l'appel aux archives : le même
    enregistrement bascule d'un côté ou de l'autre du critère selon qu'on
    connaît le vent ou non.
    """
    poussee = sortie_synthetique(duree_s=2600, vent_face_ms=-6.0)
    sans_vent, part_sans = detecter_groupe(poussee, VRAI, [])
    avec_vent, part_avec = detecter_groupe(
        poussee, VRAI, archive(vent_kmh=vent_archive_kmh(6.0), depuis_deg=270.0)
    )
    assert sans_vent and part_sans > 0.9
    assert not avec_vent and part_avec < 0.1


# --- partage et deux passes ---------------------------------------------------


def _sortie(jour: date, **kwargs) -> SortieCalibration:
    activite = sortie_synthetique(**kwargs)
    activite.debut = datetime(jour.year, jour.month, jour.day, 9, 0, tzinfo=UTC)
    decalage = activite.debut - DEPART
    for p in activite.points:
        p.t = p.t + decalage
    return SortieCalibration(activite=activite, vent=[], identifiant=jour.isoformat())


def test_partager_reserve_les_plus_recentes():
    sorties = [_sortie(date(2026, 1, jour), duree_s=100) for jour in range(1, 9)]
    apprentissage, validation = partager(sorties, 0.25)
    assert len(apprentissage) == 6 and len(validation) == 2
    assert validation[0].jour == date(2026, 1, 7)
    assert all(a.jour < validation[0].jour for a in apprentissage)


def test_partager_garde_toujours_au_moins_une_sortie_de_chaque_cote():
    deux = [_sortie(date(2026, 1, j), duree_s=100) for j in (1, 2)]
    apprentissage, validation = partager(deux, 0.25)
    assert len(apprentissage) == 1 and len(validation) == 1
    seule = [_sortie(date(2026, 1, 1), duree_s=100)]
    assert partager(seule, 0.25) == (seule, [])


def test_deux_passes_ecartent_la_sortie_en_groupe():
    """Cinq sorties conformes, une en peloton : la seconde passe l'exclut et s'en trouve mieux."""
    sorties = [_sortie(date(2026, 1, jour), duree_s=2600) for jour in (1, 2, 4, 5, 6, 7)]
    # Datée au milieu du lot : elle tombe donc dans l'apprentissage, pas dans
    # le test — c'est là que la première passe doit la repérer.
    sorties.append(_sortie(date(2026, 1, 3), duree_s=2600, facteur_vitesse=1.20))
    rapport = calibrer_en_deux_passes(
        sorties, velo="Essai", masse_totale_kg=MASSE, part_validation=0.25
    )
    assert [nom for nom, _ in rapport.groupes]
    assert rapport.ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=0.08)
    # La première passe, polluée par le peloton, sous-estime la traînée.
    assert rapport.passe1.cda_m2 < rapport.ajustement.cda_m2
    assert rapport.validation.n >= 1
    assert rapport.echantillons > rapport.echantillons_retenus
    assert "départ" in rapport.motifs


def test_deux_sorties_sans_identifiant_ne_s_ecrasent_pas():
    """Les échantillons sont rangés par position, pas sous une clé reconstruite.

    `identifiant` vaut `""` par défaut et `nom` retombe sur le nom du fichier :
    deux sorties sans identifiant et de même nom (« Sortie du matin »)
    disparaissaient l'une dans l'autre, donc de l'ajustement comme de la
    seconde passe, sans un mot. La commande passe toujours un identifiant ;
    un appelant de bibliothèque, lui, perdait des échantillons.
    """
    jours = [date(2026, 1, j) for j in (1, 2, 4, 5, 6, 7)]
    avec = [_sortie(j, duree_s=2600) for j in jours]
    sans = [_sortie(j, duree_s=2600) for j in jours]
    assert len({s.nom for s in sans}) == 1, "même nom pour toutes : c'est le cas qui collisionnait"
    for s in sans:
        s.identifiant = ""

    reference = calibrer_en_deux_passes(avec, velo="Essai", masse_totale_kg=MASSE)
    anonymes = calibrer_en_deux_passes(sans, velo="Essai", masse_totale_kg=MASSE)
    assert anonymes.echantillons == reference.echantillons
    assert anonymes.echantillons_retenus == reference.echantillons_retenus
    assert anonymes.ajustement.cda_m2 == pytest.approx(reference.ajustement.cda_m2)


def test_deux_passes_sans_sortie():
    with pytest.raises(ErreurUtilisateur, match="aucune sortie"):
        calibrer_en_deux_passes([], velo="Essai", masse_totale_kg=MASSE)


# --- choix des sorties calibrables --------------------------------------------

CONFIG_BRUTE = {
    "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
    "velos": [
        {"nom": "Route", "usage": "route", "capteur_puissance": "CAPTEUR 0001"},
        {"nom": "CLM", "usage": "clm", "capteur_puissance": "CAPTEUR 0002"},
    ],
    "calibration": {"mots_groupe": ["club", "peloton"]},
}


def entree(**champs) -> EntreeCache:
    defauts = dict(
        identifiant="a" * 64,
        source="intervals",
        id_externe="1",
        debut=datetime(2024, 3, 30, 9, 0, tzinfo=UTC),
        duree_s=3600.0,
        distance_m=30000.0,
        puissance_moy_w=200.0,
        sport="Ride",
        appareil="Appareil de test",
        equipement=None,
        chemin=Path("/inexistant"),
        meta={"power_meter": "CAPTEUR 0001", "nom": "sortie du matin"},
    )
    return EntreeCache(**{**defauts, **champs})


def test_motif_exclusion():
    config = depuis_dict(CONFIG_BRUTE)
    route = config.velo("Route")
    assert motif_exclusion(entree(), config, route) is None
    assert motif_exclusion(entree(sport="Run"), config, route) == "pas du vélo"
    assert motif_exclusion(entree(sport="VirtualRide"), config, route) == "home-trainer"
    assert motif_exclusion(entree(), config, config.velo("CLM")) == "autre vélo"
    assert motif_exclusion(entree(puissance_moy_w=None), config, route) == "sans puissance"
    assert motif_exclusion(entree(distance_m=15_000.0), config, route) == "moins de 20 km"
    groupe = entree(meta={"power_meter": "CAPTEUR 0001", "nom": "Sortie CLUB du dimanche"})
    assert motif_exclusion(groupe, config, route) == "nom « club »"


def test_sorties_calibrables_trie_et_filtre(tmp_path: Path, generateur):
    """Sur un vrai cache alimenté par les fixtures synthétiques du dépôt."""
    fixtures = generateur.generer(tmp_path / "fixtures")
    cache = Cache(tmp_path / "cache")
    cache.ajouter(
        fixtures["boucle.fit"].read_bytes(),
        source="intervals",
        id_externe="calibrable",
        extension="fit",
        meta={"nom": "sortie neutre", "power_meter": "CAPTEUR 0001", "sport": "Ride"},
    )
    cache.ajouter(
        fixtures["boucle.fit"].read_bytes(),
        source="intervals",
        id_externe="peloton",
        extension="fit",
        meta={"nom": "Sortie club", "power_meter": "CAPTEUR 0001", "sport": "Ride"},
    )
    config = depuis_dict(CONFIG_BRUTE)
    toutes = cache.lister()
    assert len(toutes) == 2, "les deux entrées doivent être indexées, sinon le test ne mesure rien"
    motifs = {
        e.meta.get("nom"): motif_exclusion(e, config, config.velo("Route")) for e in toutes
    }
    # La fixture du dépôt fait 5,5 km : les deux sorties sont trop courtes, et
    # c'est ce motif-là qui tombe en premier (l'ordre des filtres est vérifié
    # sur des entrées fabriquées dans `test_motif_exclusion`).
    assert set(motifs.values()) == {"moins de 20 km"}
    assert sorties_calibrables(cache, config, config.velo("Route"), depuis=date(2000, 1, 1)) == []
    # Le seuil est bien la seule chose qui les écarte : abaissé, elles reviennent.
    import ourouler.physique.calibration as calib

    ancien = calib.DISTANCE_MINIMALE_M
    calib.DISTANCE_MINIMALE_M = 1000.0
    try:
        retenues = sorties_calibrables(
            cache, config, config.velo("Route"), depuis=date(2000, 1, 1)
        )
    finally:
        calib.DISTANCE_MINIMALE_M = ancien
    assert [e.meta.get("nom") for e in retenues] == ["sortie neutre"]


def test_masse_totale_kg():
    config = depuis_dict(CONFIG_BRUTE)
    assert masse_totale_kg(config, config.velo("Route")) == 80.0 + MASSE_VELO_DEFAUT_KG
    lourd = depuis_dict(
        {**CONFIG_BRUTE, "velos": [{"nom": "Route", "usage": "route", "masse_kg": 8.2}]}
    )
    assert masse_totale_kg(lourd, lourd.velo("Route")) == pytest.approx(88.2)


# --- terme d'énergie cinétique (point 2 de la relecture) ----------------------


def test_calibrer_retrouve_cda_et_crr_sur_des_troncons_qui_accelerent():
    """Accélération connue retranchée : les deux paramètres sont retrouvés exactement."""
    ajustement = calibrer(echantillons_avec_acceleration(), masse_totale_kg=MASSE)
    assert ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=0.01)
    assert ajustement.crr == pytest.approx(CRR_VRAI, rel=0.02)
    assert ajustement.rmse_w < 0.5  # il ne reste rien à expliquer


def test_sans_les_vitesses_aux_bornes_l_acceleration_fausse_l_ajustement():
    """Les mêmes tronçons, vitesses aux bouts effacées : CdA et Crr dérapent.

    C'est la mesure de ce que le terme apporte. Le cycliste accélère ici
    systématiquement (`dv_min > 0`) ; sans le terme cinétique, ces watts-là
    n'ont nulle part où aller et se rangent dans la traînée et le roulement.
    """
    avec = echantillons_avec_acceleration(dv_min=0.2, dv_max=0.9)
    sans = [
        Echantillon(**{**e.__dict__, "v_debut_ms": 0.0, "v_fin_ms": 0.0}) for e in avec
    ]
    juste = calibrer(avec, masse_totale_kg=MASSE)
    faux = calibrer(sans, masse_totale_kg=MASSE)
    assert juste.cda_m2 == pytest.approx(CDA_VRAI, rel=0.01)
    assert juste.crr == pytest.approx(CRR_VRAI, rel=0.02)
    assert abs(faux.cda_m2 - CDA_VRAI) > 0.02 or abs(faux.crr - CRR_VRAI) > 0.001
    assert faux.rmse_w > 10 * max(juste.rmse_w, 0.01)


def test_puissance_cinetique_signe_et_ordre_de_grandeur():
    """Accélérer coûte, ralentir rend, et l'ordre de grandeur est celui attendu.

    Passer de 8 à 9 m/s sur 200 m à 8,5 m/s de moyenne (≈ 23,5 s) coûte
    100 × (81 − 64) / (2 × 23,5) ≈ 36 W au pédalier, soit 37 W avec le
    rendement — l'ordre de grandeur d'une relance, pas d'un détail.
    """
    monte = Echantillon(
        v_ms=8.5,
        puissance_w=0.0,
        pente=0.0,
        vent_face_ms=0.0,
        temp_c=15.0,
        retenu=True,
        motif="",
        longueur_m=200.0,
        v_debut_ms=8.0,
        v_fin_ms=9.0,
    )
    descend = Echantillon(**{**monte.__dict__, "v_debut_ms": 9.0, "v_fin_ms": 8.0})
    assert monte.duree_s == pytest.approx(200.0 / 8.5)
    assert monte.puissance_cinetique_w(100.0) == pytest.approx(37.0, abs=1.0)
    assert descend.puissance_cinetique_w(100.0) == pytest.approx(
        -monte.puissance_cinetique_w(100.0)
    )


def test_puissance_cinetique_nulle_sans_vitesses_aux_bornes():
    """Un échantillon fabriqué à la main n'a aucun terme cinétique."""
    e = Echantillon(
        v_ms=8.0,
        puissance_w=200.0,
        pente=0.0,
        vent_face_ms=0.0,
        temp_c=15.0,
        retenu=True,
        motif="",
        longueur_m=200.0,
    )
    assert e.puissance_cinetique_w(100.0) == 0.0


def test_echantillonner_note_les_vitesses_aux_deux_bouts():
    """Sur une sortie fabriquée, les vitesses aux bornes encadrent la moyenne."""
    activite = sortie_synthetique(duree_s=1200)
    retenus = [e for e in echantillonner(activite, archive()) if e.retenu]
    assert retenus
    for e in retenus:
        assert e.v_debut_ms > 0 and e.v_fin_ms > 0
        assert min(e.v_debut_ms, e.v_fin_ms) - 0.5 <= e.v_ms <= max(e.v_debut_ms, e.v_fin_ms) + 0.5


def test_vitesses_aux_bornes_sans_champ_de_vitesse():
    """Un enregistrement sans vitesse (GPX nu) les retrouve par la géométrie."""
    activite = sortie_synthetique(duree_s=1200)
    for point in activite.points:
        point.vitesse_ms = None
    retenus = [e for e in echantillonner(activite, archive()) if e.retenu]
    assert retenus
    assert all(e.v_debut_ms > 0 and e.v_fin_ms > 0 for e in retenus)


# --- fichiers multisport (point 4 de la relecture, Q10) -----------------------


def test_motif_multisport_sur_plusieurs_sessions():
    """Le lecteur FIT pose `meta["sessions"]` : un fichier à trois sessions est écarté."""
    activite = sortie_synthetique(duree_s=600)
    activite.meta["sessions"] = 3
    assert motif_multisport(activite) == "multisport"


def test_motif_multisport_sur_l_avertissement_de_lecture():
    """Même fichier vu de l'autre côté : l'avertissement suffit."""
    activite = sortie_synthetique(duree_s=600)
    activite.meta["avertissements"] = [
        "3 sessions dans le fichier : distance et durée de mouvement sont la somme des sessions"
    ]
    assert motif_multisport(activite) == "multisport"


@pytest.mark.parametrize("sport", ["swimming", "running", "Run", "transition"])
def test_motif_multisport_sur_le_sport_du_fichier(sport: str):
    """Le sport du **fichier** prime : Intervals annonce « Ride » pour un segment de triathlon."""
    activite = sortie_synthetique(duree_s=600)
    activite.sport = sport
    assert motif_multisport(activite) == "multisport"


@pytest.mark.parametrize("sport", ["cycling", "Ride", "biking", "cycling/road", None, ""])
def test_une_sortie_velo_ordinaire_n_est_pas_multisport(sport):
    activite = sortie_synthetique(duree_s=600)
    activite.sport = sport
    assert motif_multisport(activite) is None
    activite.meta["sessions"] = 1
    assert motif_multisport(activite) is None


def test_un_fichier_illisible_n_est_pas_declare_multisport():
    """On ne sait pas : on ne juge pas. La commande le signalera pour ce qu'il est."""
    assert motif_multisport(None) is None


def _cache_a_deux_sorties(tmp_path: Path, generateur) -> tuple[Cache, dict]:
    """Un cache avec deux sorties vélo rattachées au même vélo."""
    fixtures = generateur.generer(tmp_path / "fixtures")
    cache = Cache(tmp_path / "cache")
    # Deux fichiers de **contenus différents** : le cache range les bruts par
    # empreinte, deux copies du même octet-pour-octet n'auraient qu'un
    # identifiant, et le test ne distinguerait plus les deux sorties.
    for id_externe, fixture in (("normale", "boucle.fit"), ("triathlon", "boucle.tcx")):
        cache.ajouter(
            fixtures[fixture].read_bytes(),
            source="intervals",
            id_externe=id_externe,
            extension=fixture.rsplit(".", 1)[1],
            meta={
                "nom": f"sortie {id_externe}",
                "power_meter": "CAPTEUR 0001",
                "sport": "Ride",
                "puissance_moy_w": 200.0,
            },
        )
    return (cache, fixtures)


def test_sorties_calibrables_ecarte_le_multisport(tmp_path: Path, generateur, monkeypatch):
    """La sortie dont le fichier porte trois sessions est écartée, avec son motif."""
    import ourouler.physique.calibration as calib

    monkeypatch.setattr(calib, "DISTANCE_MINIMALE_M", 1000.0)
    cache, _ = _cache_a_deux_sorties(tmp_path, generateur)
    config = depuis_dict(CONFIG_BRUTE)
    velo = config.velo("Route")
    identifiants = {
        e.meta.get("nom"): e.identifiant
        for e in cache.lister(depuis=date(2000, 1, 1))
    }

    def relire(identifiant: str):
        activite = cache.relire(identifiant)
        if identifiant == identifiants["sortie triathlon"]:
            activite.meta["sessions"] = 3
        return activite

    sans_relecture = sorties_calibrables(cache, config, velo, depuis=date(2000, 1, 1))
    assert len(sans_relecture) == 2  # l'index seul ne voit rien

    retenues, motifs = sorties_calibrables_et_motifs(
        cache, config, velo, depuis=date(2000, 1, 1), relire=relire
    )
    assert [e.meta.get("nom") for e in retenues] == ["sortie normale"]
    assert motifs == {"multisport": 1}


def test_sorties_calibrables_ne_relit_pas_les_sorties_deja_ecartees(
    tmp_path: Path, generateur, monkeypatch
):
    """Le lecteur ne doit pas être appelé sur les footings ni sur l'autre vélo.

    Relire un FIT coûte cher ; le cache du mainteneur en contient neuf cents,
    dont la plupart ne sont pas des sorties de ce vélo.
    """
    import ourouler.physique.calibration as calib

    monkeypatch.setattr(calib, "DISTANCE_MINIMALE_M", 1000.0)
    cache, fixtures = _cache_a_deux_sorties(tmp_path, generateur)
    cache.ajouter(
        fixtures["boucle.gpx"].read_bytes(),
        source="intervals",
        id_externe="footing",
        extension="gpx",
        meta={
            "nom": "footing",
            "power_meter": "CAPTEUR 0001",
            "sport": "Run",
            "puissance_moy_w": 200.0,
        },
    )
    config = depuis_dict(CONFIG_BRUTE)
    appels: list[str] = []

    def relire(identifiant: str):
        appels.append(identifiant)
        return cache.relire(identifiant)

    retenues, _ = sorties_calibrables_et_motifs(
        cache, config, config.velo("Route"), depuis=date(2000, 1, 1), relire=relire
    )
    assert len(retenues) == 2
    assert len(appels) == 2  # le footing n'a jamais été ouvert


def test_sans_relecture_le_comportement_est_celui_d_avant(tmp_path: Path, generateur, monkeypatch):
    import ourouler.physique.calibration as calib

    monkeypatch.setattr(calib, "DISTANCE_MINIMALE_M", 1000.0)
    cache, _ = _cache_a_deux_sorties(tmp_path, generateur)
    config = depuis_dict(CONFIG_BRUTE)
    retenues, motifs = sorties_calibrables_et_motifs(
        cache, config, config.velo("Route"), depuis=date(2000, 1, 1)
    )
    assert len(retenues) == 2
    assert "multisport" not in motifs


# --- L9.1 : Crr fixé, CdA cherché, fourchette du porte à porte ----------------


def test_calibrer_a_crr_fixe_retrouve_le_cda_exactement():
    """Le Crr donné (pneu), seul le CdA est cherché : sans bruit, il est exact."""
    ajustement = calibrer(
        echantillons_synthetiques(bruit_w=0.0), masse_totale_kg=MASSE, crr_fixe=CRR_VRAI
    )
    assert ajustement.crr_fixe
    assert ajustement.crr == CRR_VRAI  # reçu, jamais retouché
    assert ajustement.cda_m2 == pytest.approx(CDA_VRAI, rel=1e-6)
    assert ajustement.incertitudes.crr is None
    assert ajustement.incertitudes.cda is not None


def test_calibrer_a_crr_fixe_trop_haut_fait_baisser_le_cda():
    """La compensation que la calibration libre ne savait pas séparer : un Crr
    fixé trop haut ne se voit qu'à un CdA plus bas."""
    trop_haut = calibrer(
        echantillons_synthetiques(bruit_w=0.0), masse_totale_kg=MASSE, crr_fixe=CRR_VRAI * 1.5
    )
    assert trop_haut.cda_m2 < CDA_VRAI


def test_calibrer_a_crr_fixe_absurde_est_refuse():
    with pytest.raises(ErreurUtilisateur, match="Crr fixé"):
        calibrer(echantillons_synthetiques(), masse_totale_kg=MASSE, crr_fixe=0.5)


def test_calibrer_a_crr_fixe_qui_pousse_le_cda_en_butee_le_dit():
    fin = Parametres(masse_totale_kg=MASSE, cda_m2=0.20, crr=0.002)
    ajustement = calibrer(
        echantillons_synthetiques(bruit_w=0.0, p=fin), masse_totale_kg=MASSE, crr_fixe=0.012
    )
    assert ajustement.cda_m2 == 0.18
    assert ajustement.bornes_atteintes
    assert any("pneu" in a for a in ajustement.avertissements)


def _sorties_variees() -> list[SortieCalibration]:
    """Six sorties fabriquées par le modèle : à plat, en côte, et vent de face."""
    reglages = [
        {"pente": 0.0},
        {"pente": 0.02},
        {"pente": 0.0, "vent_face_ms": 3.0},
        {"pente": 0.01},
        {"pente": 0.0},
        {"pente": 0.03},
    ]
    sorties = []
    for jour, reglage in enumerate(reglages, start=1):
        sortie = _sortie(date(2026, 2, jour), duree_s=1500, **reglage)
        if reglage.get("vent_face_ms"):
            sortie.vent = [
                HeureArchive(
                    t=h.t.replace(month=2, day=jour),
                    vent_kmh=h.vent_kmh,
                    vent_depuis_deg=h.vent_depuis_deg,
                    temp_c=h.temp_c,
                    pression_hpa=h.pression_hpa,
                )
                for h in archive(vent_kmh=vent_archive_kmh(3.0), depuis_deg=90.0)
            ]
        sorties.append(sortie)
    return sorties


def test_chercher_cda_sur_sorties_retrouve_le_cda_du_modele():
    """Méthode retenue le 25/09 : minimiser l'erreur de **temps** des sorties."""
    from ourouler.physique.calibration import PRECISION_CDA_M2, chercher_cda_sur_sorties

    cda = chercher_cda_sur_sorties(_sorties_variees(), masse_totale_kg=MASSE, crr=CRR_VRAI)
    assert cda == pytest.approx(CDA_VRAI, abs=2 * PRECISION_CDA_M2)


def test_chercher_cda_sans_sortie_est_refuse():
    from ourouler.physique.calibration import chercher_cda_sur_sorties

    with pytest.raises(ErreurUtilisateur, match="aucune sortie"):
        chercher_cda_sur_sorties([], masse_totale_kg=MASSE, crr=CRR_VRAI)


def test_deux_passes_a_crr_fixe_ne_cherchent_que_le_cda():
    sorties = [*_sorties_variees(), _sortie(date(2026, 2, 9), duree_s=1500)]
    rapport = calibrer_en_deux_passes(
        sorties, velo="Essai", masse_totale_kg=MASSE, crr_fixe=CRR_VRAI
    )
    assert rapport.ajustement.crr == CRR_VRAI
    assert rapport.ajustement.crr_fixe
    assert rapport.passe1.crr == CRR_VRAI
    assert rapport.ajustement.cda_m2 == pytest.approx(CDA_VRAI, abs=0.005)
    # À la précision de la simulation près (pas de 100 m, altitude lissée).
    assert rapport.validation.mae is not None and rapport.validation.mae < 0.02


def _avec_arrets(sortie: SortieCalibration, facteur: float) -> SortieCalibration:
    """La même sortie, dont le porte à porte réel dure `facteur` fois son temps en mouvement.

    Les points ne changent pas : seul l'écoulé (premier → dernier point, feux
    compris) s'allonge, comme un compteur qui tourne pendant les arrêts.
    """
    sortie.activite.duree_s = sortie.activite.duree_s * facteur
    return sortie


def test_mesurer_porte_a_porte_rend_les_centiles_du_ratio_ecoule_sur_simule():
    from ourouler.physique.calibration import mesurer_porte_a_porte

    facteurs = [1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12, 1.14]
    sorties = [
        _avec_arrets(_sortie(date(2026, 3, i + 1), duree_s=1200), f)
        for i, f in enumerate(facteurs)
    ]
    mesure = mesurer_porte_a_porte(sorties, VRAI)
    assert mesure.n == 8
    bas, mediane, haut = mesure.centiles
    # Le modèle rejoue ses propres sorties : simulé ≈ mouvement, donc le ratio
    # vaut le facteur d'arrêts, à la précision de la simulation près.
    assert bas == pytest.approx(1.035, abs=0.01)
    assert mediane == pytest.approx(1.07, abs=0.01)
    assert haut == pytest.approx(1.105, abs=0.01)
    assert mesure.centiles_mouvement[1] == pytest.approx(1.0, abs=0.01)


def test_mesurer_porte_a_porte_ecarte_les_sorties_en_groupe():
    """Le filtre à 50 % de signal de groupe se fait dans le pipeline, une fois."""
    from ourouler.physique.calibration import mesurer_porte_a_porte

    sorties = [
        _avec_arrets(_sortie(date(2026, 3, i + 1), duree_s=1200), 1.05) for i in range(8)
    ]
    peloton = _avec_arrets(_sortie(date(2026, 3, 20), duree_s=1200, facteur_vitesse=1.2), 0.8)
    mesure = mesurer_porte_a_porte([*sorties, peloton], VRAI)
    assert len(mesure.sorties) == 9
    assert mesure.n == 8
    assert all(s.part_groupe < 0.5 for s in mesure.retenues)
    assert mesure.centiles[0] == pytest.approx(1.05, abs=0.01)


def test_trop_peu_de_sorties_solo_ne_donne_pas_de_fourchette():
    from ourouler.physique.calibration import SORTIES_MIN_FOURCHETTE, mesurer_porte_a_porte

    sorties = [
        _sortie(date(2026, 3, i + 1), duree_s=1200) for i in range(SORTIES_MIN_FOURCHETTE - 1)
    ]
    mesure = mesurer_porte_a_porte(sorties, VRAI)
    assert mesure.n == SORTIES_MIN_FOURCHETTE - 1
    assert mesure.centiles is None
    assert mesure.centiles_mouvement is None


def test_le_vent_le_long_prend_le_point_le_plus_proche_comme_avant():
    """La dichotomie de `vent_le_long` rend le même instant que l'ancien
    parcours linéaire (premier point le plus proche), y compris aux égalités
    et aux distances répétées d'un arrêt."""
    from ourouler.physique import echantillonnage
    from ourouler.physique.validation import vent_le_long

    activite = sortie_synthetique(duree_s=300)
    # Un arrêt : trois points à la même distance.
    for p in activite.points[100:103]:
        p.dist_m = activite.points[100].dist_m
    points = [p for p in activite.points if p.t is not None]
    distances = echantillonnage._distances_points(points)
    # Un vent qui change d'heure en heure, pour que l'instant choisi se voie.
    heures = [
        HeureArchive(
            t=DEPART.replace(hour=h), vent_kmh=float(h), vent_depuis_deg=90.0, temp_c=15.0,
            pression_hpa=1013.25,
        )
        for h in range(24)
    ]
    face = vent_le_long(activite, heures)
    milieu = (distances[10] + distances[11]) / 2
    for d in [0.0, distances[100], distances[100] + 0.001, milieu, distances[-1], 1e9]:
        attendu = min(range(len(distances)), key=lambda k: abs(distances[k] - d))
        instant = points[attendu].t
        assert face(d, 90.0) == pytest.approx(
            echantillonnage._vent_de_face(echantillonnage._interpoler_archive(heures, instant), 90.0)
        )


# --- contre-lecture du 25/09 : roue partielle hors de l'apprentissage ---------


def test_la_roue_partielle_n_entre_pas_dans_la_recherche_du_cda(monkeypatch):
    """Neuf sorties solo, dix à 40 % de signal de groupe — sous les 50 % qui
    écartent une sortie, au-dessus des 30 % de `part_groupe_max` — roulées
    20 % plus vite que la puissance ne le justifie. Elles restent dans les
    moindres carrés de la seconde passe, mais pas dans la recherche du CdA
    sur le temps : le CdA vrai est retrouvé. (Majoritaires exprès : l'erreur
    absolue moyenne est robuste à une minorité d'aberrantes, et c'est bien
    une majorité de sorties en roue partielle qu'on a mesurée chez le
    mainteneur — 36 % de signal de groupe en moyenne.)"""
    from ourouler.physique import calibration as calib

    solo = [_sortie(date(2026, 4, j), duree_s=1500) for j in range(1, 10)]
    roue = [_sortie(date(2026, 4, j), duree_s=1500, facteur_vitesse=1.2) for j in range(10, 20)]
    for s in roue:
        s.activite.meta["nom"] = "roue partielle"
    validation = [_sortie(date(2026, 5, j), duree_s=1500) for j in range(1, 7)]

    def part_imposee(activite, *_a, **_k):
        return (False, 0.40 if activite.meta.get("nom") == "roue partielle" else 0.05)

    monkeypatch.setattr(calib, "detecter_groupe", part_imposee)
    rapport = calibrer_en_deux_passes(
        [*solo, *roue, *validation], velo="Essai", masse_totale_kg=MASSE, crr_fixe=CRR_VRAI
    )
    assert rapport.part_groupe_max == 0.30
    assert rapport.n_validation == 6
    assert rapport.n_solo == 9
    assert rapport.repli_solo == ""
    assert rapport.ajustement.cda_m2 == pytest.approx(CDA_VRAI, abs=0.005)

    # Au seuil de 50 %, la roue partielle entre, et le CdA descend.
    au_seuil_large = calibrer_en_deux_passes(
        [*solo, *roue, *validation],
        velo="Essai",
        masse_totale_kg=MASSE,
        crr_fixe=CRR_VRAI,
        part_groupe_max=0.5,
    )
    assert au_seuil_large.n_solo == 19
    assert au_seuil_large.ajustement.cda_m2 < rapport.ajustement.cda_m2 - 0.01


def test_trop_peu_de_sorties_solo_replie_et_le_dit():
    from ourouler.physique.calibration import SORTIES_MIN_SOLO

    sorties = [_sortie(date(2026, 4, j), duree_s=1500) for j in range(1, 8)]
    rapport = calibrer_en_deux_passes(
        sorties, velo="Essai", masse_totale_kg=MASSE, crr_fixe=CRR_VRAI
    )
    assert rapport.n_solo < SORTIES_MIN_SOLO
    assert "il en faut" in rapport.repli_solo


def test_la_fourchette_n_est_mesuree_que_sur_la_validation():
    sorties = [_sortie(date(2026, 4, j), duree_s=1200) for j in range(1, 13)]
    rapport = calibrer_en_deux_passes(
        sorties, velo="Essai", masse_totale_kg=MASSE, crr_fixe=CRR_VRAI
    )
    assert len(rapport.porte_a_porte.sorties) == rapport.n_validation == 3
    jours_validation = {s.jour for s in rapport.porte_a_porte.sorties}
    assert jours_validation == {"2026-04-10", "2026-04-11", "2026-04-12"}

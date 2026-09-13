"""La calibration : échantillonnage, ajustement, validation, détection de groupe.

Toutes les données sont **fabriquées par le modèle lui-même** : on lui donne
un CdA et un Crr, on en déduit des vitesses, on bruite, et on vérifie qu'il
les retrouve. Aucune coordonnée réelle (tout part du point (0, 0)), aucune
donnée du mainteneur, aucun réseau.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.modele import Activite, Point
from ourouler.config import depuis_dict
from ourouler.connecteurs.openmeteo_archive import HeureArchive
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.calibration import (
    CDA_MAX,
    DELTA_V_MAX_MS,
    MASSE_VELO_DEFAUT_KG,
    Echantillon,
    Parametres,
    SortieCalibration,
    calibrer,
    calibrer_en_deux_passes,
    detecter_groupe,
    echantillonner,
    masse_totale_kg,
    motif_exclusion,
    partager,
    puissance_moyenne_en_mouvement,
    sorties_calibrables,
    temps_mouvement_s,
    valider,
)
from ourouler.physique.modele import RHO_DEFAUT, puissance_requise, vitesse_regime

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


# --- échantillonnage ----------------------------------------------------------


def test_echantillonner_retrouve_vitesse_pente_et_vent():
    """Sur une sortie fabriquée à 2 % avec 18 km/h de face, les trois sont retrouvés."""
    vent_ms = 5.0
    activite = sortie_synthetique(pente=0.02, vent_face_ms=vent_ms)
    # Le tracé va plein est (cap 90°) : un vent qui vient de l'est est de face.
    echantillons = echantillonner(activite, archive(vent_kmh=vent_ms * 3.6, depuis_deg=90.0))
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
    assert echantillons[-1].vent_face_ms == pytest.approx(-5.0, abs=0.01)


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
    # Le seuil est bien celui du contrat.
    assert DELTA_V_MAX_MS == 0.3


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
    assert peu.cda_incertitude is not None and beaucoup.cda_incertitude is not None
    assert beaucoup.cda_incertitude < peu.cda_incertitude


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
    avec = valider([(activite, archive(vent_kmh=18.0, depuis_deg=90.0))], VRAI)
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
    avec_vent, part_avec = detecter_groupe(poussee, VRAI, archive(vent_kmh=21.6, depuis_deg=270.0))
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

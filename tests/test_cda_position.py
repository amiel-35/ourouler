"""Tests du script de mesure `scripts/validation/cda_position_retrospectif.py`.

Le script lui-même lit le cache réel du mainteneur et ne peut donc pas être
collecté par pytest. Ce qu'on teste ici, ce sont ses **deux mécanismes
vérifiables sans aucune donnée réelle** :

1. **l'ajustement à trois paramètres** — un Crr commun et un CdA par groupe —
   sur des échantillons fabriqués à partir d'une réponse connue d'avance. Si
   l'ajustement ne retrouve pas les paramètres qui ont servi à construire les
   puissances, il ne mesure rien ;
2. **l'isolement d'une session cycliste** dans un FIT multisport fabriqué. Le
   lecteur du projet somme les sessions d'un tel fichier ; prendre cette somme
   pour une sortie à vélo reviendrait à demander au modèle d'expliquer une
   brasse par de la traînée aérodynamique.

S'y ajoutent l'agrégation en segments, le comportement aux bornes, et le
garde-fou qui empêche un footing enregistré le même jour d'entrer dans la
mesure.

Aucun réseau, aucune donnée personnelle : les échantillons sont synthétiques et
les coordonnées du générateur de fixtures sont au large du golfe de Guinée.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ourouler.activites.cache import EntreeCache
from ourouler.activites.lecture import lire_fit
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique.calibration import CDA_MIN, Echantillon
from ourouler.physique.modele import Parametres, puissance_requise

RACINE = Path(__file__).resolve().parents[1]

#: Les paramètres qui fabriquent les échantillons de référence. Le groupe A est
#: nettement plus aérodynamique que le groupe B, les deux partagent leur Crr :
#: c'est exactement la situation que le script prétend savoir démêler.
CDA_A_VRAI = 0.22
CDA_B_VRAI = 0.30
CRR_VRAI = 0.0045
MASSE_KG = 95.0


def _mesure():
    """Le script de validation, chargé par chemin (il vit hors de `tests/`)."""
    if "cda_position_retrospectif" in sys.modules:
        return sys.modules["cda_position_retrospectif"]
    chemin = RACINE / "scripts" / "validation" / "cda_position_retrospectif.py"
    spec = importlib.util.spec_from_file_location("cda_position_retrospectif", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cda_position_retrospectif"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mesure():
    return _mesure()


# --- ajustement à trois paramètres --------------------------------------------


def _echantillon(
    v_kmh: float,
    pente: float,
    cda: float,
    *,
    vent_face_ms: float = 0.0,
    crr: float = CRR_VRAI,
    longueur_m: float = 200.0,
    bruit_w: float = 0.0,
) -> Echantillon:
    """Un tronçon dont la puissance est **exactement** celle que le modèle demande.

    La puissance sort de `puissance_requise`, la même fonction que l'ajustement
    utilise pour construire ses colonnes. Un ajustement qui ne retrouve pas
    (cda, crr) sur de tels échantillons est faux sans discussion possible : il
    n'y a ni bruit, ni approximation, ni désaccord de modèle à invoquer.
    """
    v = v_kmh / 3.6
    p = Parametres(masse_totale_kg=MASSE_KG, cda_m2=cda, crr=crr, rho=1.225)
    return Echantillon(
        v_ms=v,
        puissance_w=puissance_requise(v, pente, vent_face_ms, p) + bruit_w,
        pente=pente,
        vent_face_ms=vent_face_ms,
        temp_c=15.0,
        retenu=True,
        motif="",
        longueur_m=longueur_m,
        rho=1.225,
        t=datetime(2024, 1, 1, 12, tzinfo=UTC),
        dist_m=10_000.0,
        # Vitesses de bout égales à la vitesse moyenne : aucun terme cinétique,
        # donc l'équilibre du modèle est exactement ce que décrit le tronçon.
        v_debut_ms=v,
        v_fin_ms=v,
    )


def _population(cda: float, **extra) -> list[Echantillon]:
    """Une douzaine de tronçons variés : trois vitesses, deux pentes, deux vents."""
    return [
        _echantillon(v, pente, cda, vent_face_ms=vent, **extra)
        for v in (24.0, 30.0, 38.0)
        for pente in (0.0, 0.02)
        for vent in (-2.0, 3.0)
    ]


def test_ajustement_retrouve_les_parametres_qui_ont_fabrique_les_donnees(mesure):
    """Sur des données sans bruit, les trois inconnues sortent à la virgule près."""
    resultat = mesure.ajuster(
        _population(CDA_A_VRAI), _population(CDA_B_VRAI), masse_totale_kg=MASSE_KG
    )
    assert resultat.cda_a == pytest.approx(CDA_A_VRAI, abs=1e-6)
    assert resultat.cda_b == pytest.approx(CDA_B_VRAI, abs=1e-6)
    assert resultat.crr == pytest.approx(CRR_VRAI, abs=1e-7)
    assert resultat.delta_cda == pytest.approx(CDA_A_VRAI - CDA_B_VRAI, abs=1e-6)
    assert resultat.rmse_w == pytest.approx(0.0, abs=1e-6)
    assert not resultat.bornes_atteintes
    assert not resultat.avertissements


def test_le_crr_est_bien_commun_aux_deux_groupes(mesure):
    """Deux groupes construits avec des Crr différents ne peuvent pas être ajustés juste.

    C'est le contrat du script énoncé à l'envers : il **impose** un Crr unique.
    Si les données en portent deux, l'ajustement ne peut pas les satisfaire
    toutes les deux, et l'erreur résiduelle doit le dire. Un résidu nul ici
    signifierait que le Crr commun n'est pas commun du tout.
    """
    a = _population(CDA_A_VRAI, crr=0.0040)
    b = _population(CDA_A_VRAI, crr=0.0080)
    resultat = mesure.ajuster(a, b, masse_totale_kg=MASSE_KG)
    assert resultat.rmse_w > 1.0
    assert 0.0040 < resultat.crr < 0.0080


def test_les_watts_rendus_sont_ceux_du_modele(mesure):
    """La traduction du ΔCdA en watts est celle de `puissance_requise`, pas une formule à part."""
    resultat = mesure.ajuster(
        _population(CDA_A_VRAI), _population(CDA_B_VRAI), masse_totale_kg=MASSE_KG
    )
    for v_kmh in (27.0, 35.0):
        v = v_kmh / 3.6
        commun = {"masse_totale_kg": MASSE_KG, "crr": resultat.crr, "rho": resultat.rho_moyen}
        attendu = puissance_requise(
            v, 0.0, 0.0, Parametres(cda_m2=CDA_A_VRAI, **commun)
        ) - puissance_requise(v, 0.0, 0.0, Parametres(cda_m2=CDA_B_VRAI, **commun))
        assert resultat.watts(v_kmh) == pytest.approx(attendu, abs=1e-6)
    # Le groupe A est le plus aérodynamique : l'écart doit être une économie.
    assert resultat.watts(35.0) < resultat.watts(27.0) < 0


def test_une_borne_atteinte_est_signalee_et_la_solution_libre_rapportee(mesure):
    """Un CdA sous `CDA_MIN` bute, le dit, et la solution non bornée reste lisible.

    C'est la règle du lot : un paramètre en butée est un aveu, pas une valeur.
    Le script doit donc rendre les deux — la valeur bornée qu'il utilise, et la
    valeur libre qui montre à quel point les données la refusent.
    """
    resultat = mesure.ajuster(
        _population(0.10), _population(CDA_B_VRAI), masse_totale_kg=MASSE_KG
    )
    assert resultat.cda_a == pytest.approx(CDA_MIN)
    assert any("borne basse" in b for b in resultat.bornes_atteintes)
    assert any("borne" in a for a in resultat.avertissements)
    assert resultat.libre is not None
    assert resultat.libre[0] == pytest.approx(0.10, abs=1e-6)


def test_la_solution_bornee_est_le_vrai_minimum_du_pave(mesure):
    """Quand une borne mord, le Crr rendu bat celui qu'on obtiendrait en écrêtant.

    Écrêter la solution libre coordonnée par coordonnée n'est pas le minimum du
    pavé : l'autre paramètre doit être réoptimisé **à borne tenue**. Le test le
    vérifie en comparant la somme des carrés, seul juge en la matière.
    """
    a, b = _population(0.10), _population(CDA_B_VRAI)
    resultat = mesure.ajuster(a, b, masse_totale_kg=MASSE_KG)
    libre = resultat.libre
    assert libre is not None
    ecrete = (
        min(max(libre[0], CDA_MIN), 0.60),
        min(max(libre[1], CDA_MIN), 0.60),
        libre[2],
    )
    obtenu = (resultat.cda_a, resultat.cda_b, resultat.crr)
    assert _somme_carres(mesure, a, b, obtenu) <= _somme_carres(mesure, a, b, ecrete) + 1e-9


def _somme_carres(mesure, a, b, parametres) -> float:
    """Écart quadratique entre puissances mesurées et modélisées, pour un triplet donné."""
    cda_a, cda_b, crr = parametres
    total = 0.0
    for groupe, cda in ((a, cda_a), (b, cda_b)):
        for e in groupe:
            p = Parametres(masse_totale_kg=MASSE_KG, cda_m2=cda, crr=crr, rho=e.rho)
            total += (puissance_requise(e.v_ms, e.pente, e.vent_face_ms, p) - e.puissance_w) ** 2
    _ = mesure
    return total


def test_trop_peu_de_troncons_est_une_erreur_pas_un_chiffre(mesure):
    """Trois inconnues demandent au moins trois tronçons par groupe."""
    with pytest.raises(ErreurUtilisateur, match="au moins"):
        mesure.ajuster(_population(CDA_A_VRAI)[:2], _population(CDA_B_VRAI), masse_totale_kg=MASSE_KG)


def test_le_bootstrap_tire_des_blocs_sans_figer_un_groupe(mesure):
    """Un bloc plus long que le tiers du groupe est rabattu, sinon le groupe ne varie plus.

    Avec cinq segments et des blocs de cinq, il n'existe qu'une seule fenêtre :
    le groupe redevient une constante et l'intervalle paraît étroit sans l'être.
    """
    import random

    echantillons = _population(CDA_A_VRAI)[:6]
    tirages = {
        tuple(id(e) for e in mesure._tirer_blocs(echantillons, 99, random.Random(graine)))
        for graine in range(30)
    }
    assert len(tirages) > 1


# --- agrégation en segments ---------------------------------------------------


def test_agreger_fusionne_les_troncons_consecutifs_en_segments(mesure):
    """Dix tronçons de 200 m réguliers donnent deux segments d'un kilomètre."""
    bruts = [_echantillon(30.0, 0.0, CDA_A_VRAI) for _ in range(10)]
    reglages = mesure.Reglages(segment_min_m=1000.0, segment_max_m=2000.0)
    segments = mesure.agreger(bruts, [True] * 10, reglages)
    assert len(segments) == 2
    assert all(s.longueur_m == pytest.approx(1000.0) for s in segments)
    assert all(s.v_ms == pytest.approx(30.0 / 3.6) for s in segments)
    assert all(s.retenu for s in segments)


def test_un_troncon_ecarte_coupe_le_segment(mesure):
    """Un trou au milieu — un arrêt, un carrefour — ne se recolle pas.

    Sans cette coupure, le script fabriquerait un « kilomètre d'effort tenu »
    qui contient un feu rouge, et demanderait au modèle de l'expliquer par de
    l'aérodynamique.
    """
    bruts = [_echantillon(30.0, 0.0, CDA_A_VRAI) for _ in range(9)]
    reglages = mesure.Reglages(segment_min_m=1000.0)
    # Sans trou, les cinq premiers tronçons font le kilomètre demandé.
    assert len(mesure.agreger(bruts, [True] * 9, reglages)) == 1
    # Avec un trou au milieu, il ne reste que deux suites de quatre tronçons :
    # 800 m chacune, trop court, et surtout de part et d'autre d'un arrêt.
    masque = [True] * 9
    masque[4] = False
    assert mesure.agreger(bruts, masque, reglages) == []


def test_un_segment_dont_la_vitesse_flotte_est_ecarte(mesure):
    """La dispersion de vitesse est ce qui distingue un effort tenu d'un yo-yo."""
    vitesses = [24.0, 36.0, 24.0, 36.0, 24.0]
    bruts = [_echantillon(v, 0.0, CDA_A_VRAI) for v in vitesses]
    reglages = mesure.Reglages(segment_min_m=1000.0)
    assert mesure.agreger(bruts, [True] * 5, reglages) == []
    # Les paquets, eux, ont bien été formés : c'est la stabilité qui les rejette.
    assert len(mesure.paquets(bruts, [True] * 5, reglages)) == 1


def test_un_segment_dont_la_pente_s_inverse_est_ecarte(mesure):
    """Un kilomètre qui monte puis descend a une pente moyenne nulle et ne décrit rien."""
    pentes = [0.04, 0.04, 0.0, -0.04, -0.04]
    bruts = [_echantillon(30.0, p, CDA_A_VRAI) for p in pentes]
    assert mesure.agreger(bruts, [True] * 5, mesure.Reglages(segment_min_m=1000.0)) == []


def test_la_pente_du_segment_est_ponderee_par_la_distance(mesure):
    """Un dénivelé rapporté à une longueur se moyenne par la distance, pas par le temps.

    Pondérée par le temps, la portion lente — celle qui monte — pèserait plus
    que sa part de dénivelé, et la pente du segment serait surestimée.
    """
    bruts = [
        _echantillon(20.0, 0.04, CDA_A_VRAI, longueur_m=500.0),
        _echantillon(40.0, 0.00, CDA_A_VRAI, longueur_m=500.0),
    ]
    segment = mesure._fusionner(bruts)
    assert segment.pente == pytest.approx(0.02)
    assert segment.longueur_m == pytest.approx(1000.0)
    # La puissance, elle, est un flux : elle se pondère par la durée, donc le
    # tronçon lent (deux fois plus long en temps) y pèse deux fois plus.
    attendu = (bruts[0].puissance_w * 2 + bruts[1].puissance_w) / 3
    assert segment.puissance_w == pytest.approx(attendu, rel=1e-9)


def test_les_bouts_du_segment_sont_ceux_de_ses_extremites(mesure):
    """Le terme cinétique doit porter sur tout le segment, pas sur chaque bout de 200 m."""
    bruts = [_echantillon(v, 0.0, CDA_A_VRAI) for v in (28.0, 29.0, 30.0, 31.0, 32.0)]
    segment = mesure._fusionner(bruts)
    assert segment.v_debut_ms == pytest.approx(28.0 / 3.6)
    assert segment.v_fin_ms == pytest.approx(32.0 / 3.6)


def test_sans_agregation_les_troncons_passent_tels_quels(mesure):
    """`segment_min_m = None` rend les tronçons d'origine : la comparaison de granularité."""
    bruts = [_echantillon(30.0, 0.0, CDA_A_VRAI) for _ in range(10)]
    masque = [True] * 10
    masque[3] = False
    gardes = mesure.agreger(bruts, masque, mesure.Reglages(segment_min_m=None))
    assert len(gardes) == 9


def test_un_segment_agrege_se_reajuste_sur_les_memes_parametres(mesure):
    """Agréger ne doit rien casser : les paramètres sortent encore justes.

    C'est le vrai contrat de l'agrégation — elle change la granularité, pas la
    physique. Si le ΔCdA changeait en passant de 200 m à 1 km sur des données
    parfaites, l'agrégation introduirait un biais à elle seule.
    """
    reglages = mesure.Reglages(segment_min_m=1000.0, cv_vitesse_max=1.0, cv_puissance_max=10.0)
    groupes = []
    for cda in (CDA_A_VRAI, CDA_B_VRAI):
        bruts = [
            _echantillon(v, pente, cda)
            for v in (24.0, 30.0, 38.0)
            for pente in (0.0, 0.02)
            for _ in range(5)
        ]
        groupes.append(mesure.agreger(bruts, [True] * len(bruts), reglages))
    resultat = mesure.ajuster(groupes[0], groupes[1], masse_totale_kg=MASSE_KG)
    assert resultat.cda_a == pytest.approx(CDA_A_VRAI, abs=1e-4)
    assert resultat.cda_b == pytest.approx(CDA_B_VRAI, abs=1e-4)
    assert resultat.crr == pytest.approx(CRR_VRAI, abs=1e-5)


# --- isolement d'une session dans un FIT multisport ---------------------------

#: (sport, sous-sport) FIT des trois segments d'un triathlon fabriqué.
NAGE = (5, 18)  # swimming / open_water
VELO = (2, 7)  # cycling / road
COURSE = (1, 0)  # running / generic


@pytest.fixture
def triathlon(generateur, tmp_path) -> Path:
    """Un FIT multisport fabriqué : nage lente, vélo rapide, course intermédiaire.

    Les trois sessions s'enchaînent sans trou, comme dans un vrai fichier de
    triathlon, et leurs distances se cumulent d'un bout à l'autre du fichier —
    c'est précisément ce qui fait que la partie vélo « commence » à plusieurs
    centaines de mètres et que la remise à zéro est nécessaire.
    """
    debut = datetime(2024, 6, 1, 7, 0, tzinfo=UTC)
    troncons = []
    distance = 0.0
    instant = debut
    for vitesse, n in ((1.2, 10), (9.0, 30), (3.0, 20)):
        troncon = []
        for _ in range(n):
            distance += vitesse * 10
            instant += timedelta(seconds=10)
            troncon.append(
                generateur.Echantillon(
                    t=instant,
                    lat=0.10,
                    lon=0.10,
                    alt_m=12.0,
                    dist_m=round(distance, 2),
                    vitesse_ms=vitesse,
                    puissance_w=180,
                    cadence_rpm=85,
                    fc_bpm=140,
                    temp_c=18,
                )
            )
        troncons.append(troncon)
    chemin = tmp_path / "triathlon.fit"
    chemin.write_bytes(
        generateur.encoder_fit_multisession(troncons, sports=[NAGE, VELO, COURSE])
    )
    return chemin


def test_les_sessions_du_fit_sont_relues_dans_l_ordre(mesure, triathlon):
    sessions = mesure.sessions_fit(triathlon)
    assert [s.rang for s in sessions] == [1, 2, 3]
    assert [s.sport for s in sessions] == ["swimming", "cycling", "running"]
    assert [s.intitule for s in sessions] == [
        "swimming/open_water",
        "cycling/road",
        "running/generic",
    ]
    assert all(s.debut < s.fin for s in sessions)


def test_choisir_la_session_par_son_sport(mesure, triathlon):
    session = mesure.choisir_session(mesure.sessions_fit(triathlon), sport="cycling")
    assert session.rang == 2


def test_choisir_la_session_par_son_rang(mesure, triathlon):
    assert mesure.choisir_session(mesure.sessions_fit(triathlon), rang=3).sport == "running"


def test_un_sport_absent_ou_ambigu_ne_se_devine_pas(mesure, triathlon):
    sessions = mesure.sessions_fit(triathlon)
    with pytest.raises(ErreurUtilisateur, match="aucune session"):
        mesure.choisir_session(sessions, sport="rowing")
    with pytest.raises(ErreurUtilisateur, match="préciser"):
        mesure.choisir_session(sessions, rang=None, sport=None)
    doublees = [*sessions, sessions[1]]
    with pytest.raises(ErreurUtilisateur, match="préciser --session-rang"):
        mesure.choisir_session(doublees, sport="cycling")


def test_isoler_la_session_velo_ne_garde_que_ses_points(mesure, triathlon):
    """Le cœur du lot : la partie vélo, et rien qu'elle.

    Le lecteur du projet somme les trois sessions ; l'activité qu'il rend
    commence donc dans l'eau. Après isolement, tous les points doivent être
    dans la fenêtre de la session cycliste, et sa vitesse être celle du vélo.
    """
    activite = lire_fit(triathlon)
    assert activite.meta["sessions"] == 3
    session = mesure.choisir_session(mesure.sessions_fit(triathlon), sport="cycling")
    isolee = mesure.isoler_session(activite, session)

    assert len(isolee.points) < len(activite.points)
    assert all(session.debut <= p.t <= session.fin for p in isolee.points)
    assert all(p.vitesse_ms == pytest.approx(9.0) for p in isolee.points)
    assert isolee.sport == "cycling/road"
    assert isolee.meta["session_isolee"] == 2


def test_isoler_remet_les_distances_a_zero(mesure, triathlon):
    """Sans remise à zéro, `echantillonner` n'écarterait pas le départ de la partie vélo.

    Les 2 000 premiers mètres sont écartés parce que le cycliste s'y met en
    route. Dans un fichier multisport, la distance court depuis le premier coup
    de bras : la partie vélo « commencerait » déjà à 120 m dans cet exemple, et
    le filtre de départ ne mordrait presque plus.
    """
    activite = lire_fit(triathlon)
    session = mesure.choisir_session(mesure.sessions_fit(triathlon), sport="cycling")
    avant = [p.dist_m for p in activite.points if session.debut <= p.t <= session.fin]
    assert avant[0] > 100.0

    isolee = mesure.isoler_session(activite, session)
    assert isolee.points[0].dist_m == pytest.approx(0.0)
    assert isolee.points[-1].dist_m == pytest.approx(avant[-1] - avant[0])
    assert isolee.distance_m == pytest.approx(isolee.points[-1].dist_m)


def test_isoler_une_session_vide_est_une_erreur(mesure, triathlon):
    """Une fenêtre sans points ne rend pas une activité vide : elle le dit."""
    session = mesure.choisir_session(mesure.sessions_fit(triathlon), sport="cycling")
    ailleurs = mesure.SessionFit(
        rang=9,
        sport="cycling",
        sous_sport=None,
        debut=session.fin + timedelta(days=1),
        fin=session.fin + timedelta(days=2),
    )
    with pytest.raises(ErreurUtilisateur, match="point"):
        mesure.isoler_session(lire_fit(triathlon), ailleurs)


def test_les_grandeurs_heritees_du_fichier_entier_sont_effacees(mesure, triathlon):
    """Mieux vaut `None` qu'une valeur qui décrit le triathlon complet."""
    isolee = mesure.isoler_session(
        lire_fit(triathlon), mesure.choisir_session(mesure.sessions_fit(triathlon), sport="cycling")
    )
    assert isolee.duree_mouvement_s is None
    assert isolee.puissance_np_w is None
    assert isolee.denivele_m is None
    assert isolee.puissance_moy_w == pytest.approx(180.0)


# --- choix des sorties --------------------------------------------------------


def _entree(jour: str, nom: str, sport: str, puissance: float | None) -> EntreeCache:
    return EntreeCache(
        identifiant="x" * 8,
        source="fichier",
        id_externe=None,
        debut=datetime.fromisoformat(f"{jour}T09:00:00+00:00"),
        duree_s=3600.0,
        distance_m=40_000.0,
        puissance_moy_w=puissance,
        sport=sport,
        appareil=None,
        equipement=None,
        chemin=Path("/inexistant"),
        meta={"nom": nom},
    )


def test_un_critere_se_lit_avec_ou_sans_bout_de_nom(mesure):
    nu = mesure.Critere.depuis_texte("2001-04-11")
    assert nu.jour.isoformat() == "2001-04-11" and nu.motif == ""
    avec = mesure.Critere.depuis_texte("2001-04-11:une course")
    assert avec.motif == "une course"
    with pytest.raises(ErreurUtilisateur, match="AAAA-MM-JJ"):
        mesure.Critere.depuis_texte("pas-une-date")


def test_un_critere_ne_ramasse_pas_le_footing_du_meme_jour(mesure):
    """Le garde-fou qui compte le plus : un jour porte souvent deux ou trois fichiers.

    Une course à pied enregistrée avec puissance affiche plusieurs centaines de
    watts pour dix kilomètres ; entrée dans l'ajustement, le modèle l'explique
    en gonflant la traînée, et personne ne voit rien.
    """
    critere = mesure.Critere.depuis_texte("2001-06-20")
    assert critere.correspond(_entree("2001-06-20", "sortie", "Ride", 160.0))
    assert not critere.correspond(_entree("2001-06-20", "enchainement", "Run", 385.0))
    assert not critere.correspond(_entree("2001-06-20", "nat.", "Swim", None))
    assert not critere.correspond(_entree("2001-06-20", "sortie", "Ride", None))
    assert not critere.correspond(_entree("2001-06-21", "sortie", "Ride", 160.0))


def test_un_critere_filtre_l_interieur(mesure):
    """Un home-trainer n'a ni vent, ni pente, ni position : il n'a rien à faire là."""
    critere = mesure.Critere.depuis_texte("2001-06-20")
    interieur = _entree("2001-06-20", "home", "VirtualRide", 160.0)
    assert not critere.correspond(interieur)


# --- plage de vitesse commune -------------------------------------------------


def test_la_plage_commune_restreint_les_deux_groupes(mesure):
    a = [_echantillon(v, 0.0, CDA_A_VRAI) for v in (30.0, 33.0, 36.0, 39.0)]
    b = [_echantillon(v, 0.0, CDA_B_VRAI) for v in (18.0, 24.0, 30.0, 33.0)]
    garde_a, garde_b, plage = mesure.restreindre_plage_commune(a, b, 0.0)
    assert plage is not None
    bas, haut = plage
    assert bas == pytest.approx(30.0 / 3.6) and haut == pytest.approx(33.0 / 3.6)
    assert [round(e.v_ms * 3.6) for e in garde_a] == [30, 33]
    assert [round(e.v_ms * 3.6) for e in garde_b] == [30, 33]


def test_sans_recouvrement_la_plage_commune_ne_ment_pas(mesure):
    """Deux populations disjointes rendent `None`, et les groupes reviennent intacts."""
    a = [_echantillon(v, 0.0, CDA_A_VRAI) for v in (36.0, 38.0, 40.0)]
    b = [_echantillon(v, 0.0, CDA_B_VRAI) for v in (16.0, 18.0, 20.0)]
    garde_a, garde_b, plage = mesure.restreindre_plage_commune(a, b, 0.0)
    assert plage is None
    assert len(garde_a) == 3 and len(garde_b) == 3


def test_la_distribution_de_vitesse_est_rendue_en_kmh(mesure):
    echantillons = [_echantillon(v, 0.0, CDA_A_VRAI) for v in (20.0, 25.0, 30.0, 35.0, 40.0)]
    mini, _, mediane, _, maxi = mesure.distribution_kmh(echantillons)
    assert mini == pytest.approx(20.0)
    assert mediane == pytest.approx(30.0)
    assert maxi == pytest.approx(40.0)


def test_le_script_n_ecrit_aucun_fichier_de_calibration():
    """Garde-fou du lot : `ourouler calibrer` écrase `calibration.json`, ce script non.

    La consigne était explicite après un accident. Un test qui lit le source
    est grossier, mais c'est exactement ce qu'on veut vérifier : qu'aucune
    écriture n'a été ajoutée par inadvertance au fil des retouches.
    """
    source = (RACINE / "scripts" / "validation" / "cda_position_retrospectif.py").read_text()
    for interdit in ("ecrire_calibration", "write_text", "open(", ".write("):
        assert interdit not in source, f"le script de mesure ne doit rien écrire ({interdit})"


def test_les_bornes_du_script_sont_celles_de_la_calibration(mesure):
    """Un ΔCdA obtenu avec des bornes plus larges ne serait pas comparable au CdA calibré."""
    from ourouler.physique import calibration as calib

    assert mesure.BORNES == (
        (calib.CDA_MIN, calib.CDA_MAX),
        (calib.CDA_MIN, calib.CDA_MAX),
        (calib.CRR_MIN, calib.CRR_MAX),
    )


def test_le_coefficient_de_variation_refuse_une_moyenne_nulle(mesure):
    """Une moyenne nulle ou négative rend l'infini, donc le segment est rejeté, pas divisé par zéro."""
    assert math.isinf(mesure._coefficient_variation([0.0, 0.0]))
    assert mesure._coefficient_variation([10.0, 10.0]) == pytest.approx(0.0)

"""Le modèle physique : cohérence puissance ↔ vitesse, monotonie, bornes, simulation.

Aucune coordonnée réelle : les tracés fabriqués partent du point (0, 0), au
milieu de l'Atlantique, à plus de 5 000 km de toute ville de la région du
mainteneur.
"""

from __future__ import annotations

import math

import pytest

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.physique.modele import (
    FACTEUR_VENT_HAUTEUR,
    FENETRE_ALTITUDE,
    PAS_M,
    RHO_DEFAUT,
    V_MAX_BISSECTION_MS,
    V_MAX_DESCENTE_KMH,
    FourchettePorteAPorte,
    Parametres,
    facteur_compteur_defaut,
    masse_volumique_air,
    moyenne_compteur_kmh,
    puissance_a_plat_w,
    puissance_requise,
    simuler,
    temps_ecoule,
    vent_au_cycliste,
    vitesse_a_plat_kmh,
    vitesse_a_plat_ms,
    vitesse_regime,
)

P = Parametres(masse_totale_kg=100.0, cda_m2=0.32, crr=0.005)

#: Un degré de longitude à l'équateur, en mètres (haversine, rayon du projet).
METRE_EN_DEGRE = 1.0 / 111_194.93


def trace_plate(longueur_m: float, *, pente: float = 0.0, pas_m: float = 100.0) -> Trace:
    """Un tracé plein est vers l'est, de pente constante, au point (0, 0)."""
    points = []
    n = int(round(longueur_m / pas_m))
    for i in range(n + 1):
        d = i * pas_m
        points.append(
            PointTrace(lat=0.0, lon=d * METRE_EN_DEGRE, alt_m=100.0 + d * pente, dist_m=d)
        )
    return Trace(
        nom="essai",
        points=points,
        segments=[],
        distance_m=longueur_m,
        denivele_m=max(0.0, longueur_m * pente),
        temps_moteur_s=None,
    )


# --- cohérence des deux sens --------------------------------------------------

PENTES = (-0.20, -0.08, -0.03, 0.0, 0.02, 0.05, 0.10, 0.20)
VENTS = (-10.0, -5.0, -2.0, 0.0, 2.0, 5.0, 10.0)
PUISSANCES = (25.0, 75.0, 150.0, 250.0, 400.0, 600.0)


@pytest.mark.parametrize("pente", PENTES)
@pytest.mark.parametrize("vent", VENTS)
@pytest.mark.parametrize("puissance", PUISSANCES)
def test_puissance_requise_inverse_vitesse_regime(pente: float, vent: float, puissance: float):
    """`puissance_requise(vitesse_regime(P)) = P` à 0,1 W près (contrat §4)."""
    v = vitesse_regime(puissance, pente, vent, P)
    if v >= V_MAX_BISSECTION_MS:
        pytest.skip("puissance au-delà de la borne de bissection")
    assert puissance_requise(v, pente, vent, P) == pytest.approx(puissance, abs=0.1)


@pytest.mark.parametrize("pente", PENTES)
@pytest.mark.parametrize("vent", VENTS)
def test_vitesse_regime_croit_avec_la_puissance(pente: float, vent: float):
    """Strictement croissante, sauf une fois la borne de bissection atteinte.

    À −20 % avec 10 m/s de vent arrière, la vitesse d'équilibre dépasse déjà
    108 km/h à 0 W : la fonction rend sa borne, et deux puissances de plus en
    plus fortes y rendent la même valeur. C'est le plafond qui parle, pas une
    non-monotonie.
    """
    vitesses = [vitesse_regime(p, pente, vent, P) for p in (0.0, 50.0, 100.0, 200.0, 400.0)]
    for a, b in zip(vitesses[:-1], vitesses[1:], strict=True):
        assert b > a or a == b == V_MAX_BISSECTION_MS


def test_puissance_requise_croit_avec_la_vitesse_sur_le_plat():
    valeurs = [puissance_requise(v, 0.0, 0.0, P) for v in (1.0, 3.0, 6.0, 9.0, 12.0, 15.0)]
    assert all(a < b for a, b in zip(valeurs[:-1], valeurs[1:], strict=True))


# --- cas limites --------------------------------------------------------------


def test_pente_nulle_et_puissance_nulle_donnent_une_vitesse_nulle():
    """Sans division par zéro : c'est la racine v = 0, pas une exception."""
    assert vitesse_regime(0.0, 0.0, 0.0, P) == pytest.approx(0.0, abs=1e-6)


def test_puissance_negative_ou_non_finie_donne_zero():
    assert vitesse_regime(-50.0, 0.0, 0.0, P) == 0.0
    assert vitesse_regime(float("nan"), 0.0, 0.0, P) == 0.0
    assert vitesse_regime(float("inf"), 0.0, 0.0, P) == 0.0


def test_descente_a_puissance_nulle_donne_la_vitesse_limite():
    """À −8 % et 0 W, l'équilibre est une vraie vitesse, pas zéro."""
    v = vitesse_regime(0.0, -0.08, 0.0, P)
    assert v > 10.0
    assert puissance_requise(v, -0.08, 0.0, P) == pytest.approx(0.0, abs=0.1)


def test_descente_tres_forte_reste_sous_la_borne():
    v = vitesse_regime(0.0, -0.20, 0.0, P)
    assert 0 < v <= V_MAX_BISSECTION_MS


def test_puissance_demesuree_est_bornee():
    """20 000 W dépassent 108 km/h : la fonction rend sa borne plutôt que d'extrapoler."""
    assert vitesse_regime(20_000.0, 0.0, 0.0, P) == V_MAX_BISSECTION_MS


def test_vent_de_dos_fort_pousse_sans_freiner():
    """Un vent arrière plus rapide que le cycliste ne doit pas devenir une traînée.

    C'est l'écart assumé au contrat §3 : `v_air·|v_air|` au lieu de
    `(v + v_vent)²`. Avec le carré, un vent de dos de 15 m/s rendait une
    traînée positive et une vitesse **plus faible** qu'à vent nul.
    """
    sans_vent = vitesse_regime(200.0, 0.0, 0.0, P)
    dos_fort = vitesse_regime(200.0, 0.0, -15.0, P)
    assert dos_fort > sans_vent
    assert puissance_requise(5.0, 0.0, -15.0, P) < 0.0


def test_pente_ou_vent_non_finis_sont_refuses():
    """Refuser, plutôt que rendre un NaN qui traverse tout sans bruit.

    Un NaN de pente ressortirait en « temps estimé » vide ou en tri
    arbitraire de candidates, sans que rien ne dise d'où il vient.
    """
    for pente, vent in ((float("nan"), 0.0), (0.0, float("inf")), (float("inf"), 0.0)):
        with pytest.raises(ErreurUtilisateur):
            vitesse_regime(200.0, pente, vent, P)
        with pytest.raises(ErreurUtilisateur):
            puissance_requise(6.0, pente, vent, P)
    with pytest.raises(ErreurUtilisateur):
        puissance_requise(float("nan"), 0.0, 0.0, P)


# --- masse volumique ----------------------------------------------------------


def test_masse_volumique_air():
    assert masse_volumique_air(15.0, 1013.25) == pytest.approx(1.2250, abs=0.001)
    assert masse_volumique_air(30.0, 1013.25) == pytest.approx(1.1644, abs=0.001)
    assert masse_volumique_air(None, 1013.25) == RHO_DEFAUT
    assert masse_volumique_air(15.0, None) == RHO_DEFAUT
    assert masse_volumique_air(float("nan"), 1013.25) == RHO_DEFAUT
    assert masse_volumique_air(-300.0, 1013.25) == RHO_DEFAUT


# --- simulation ---------------------------------------------------------------

#: Valeur calculée à la main pour `P` (100 kg, CdA 0,32, Crr 0,005, η 0,976,
#: ρ 1,226) à 200 W sur le plat sans vent. La cubique
#: `0,196160·v³ + 4,903325·v − 195,2 = 0` a pour unique racine réelle
#: v = 9,151183 m/s, soit **32,944 km/h** et **1 092,75 s** (18 min 13 s) pour
#: 10 km. Vérifiée indépendamment par `numpy.roots`.
V_PLAT_200W_MS = 9.151183
T_10KM_200W_S = 1092.755


def test_simulation_plat_10km_a_200w():
    sim = simuler(trace_plate(10_000.0), 200.0, P)
    assert sim.distance_m == pytest.approx(10_000.0, abs=1.0)
    assert sim.temps_s == pytest.approx(T_10KM_200W_S, rel=1e-4)
    assert sim.vitesse_moy_kmh == pytest.approx(V_PLAT_200W_MS * 3.6, rel=1e-4)
    assert len(sim.par_segment) == 100
    assert sim.pas_plafonnes == 0 and sim.pas_bloques == 0


def test_simulation_puissance_variable():
    """Une puissance fonction de la distance : la seconde moitié plus forte va plus vite."""
    sim = simuler(trace_plate(10_000.0), lambda d: 150.0 if d < 5000 else 300.0, P)
    premiers = [t for dist, _, _, t in sim.par_segment if dist <= 5000]
    derniers = [t for dist, _, _, t in sim.par_segment if dist > 5000]
    assert sum(derniers) < sum(premiers)


def test_simulation_plafonne_la_descente():
    """À −8 % et 200 W, le modèle dépasse 60 km/h : la vitesse est ramenée au plafond.

    Les trois premiers et les trois derniers pas y échappent : la moyenne
    glissante de l'altitude rétrécit sa fenêtre aux bords, la pente y est donc
    adoucie. C'est le comportement de `moyenne_glissante`, partagé avec le
    calcul de dénivelé du projet.
    """
    sim = simuler(trace_plate(5_000.0, pente=-0.08), 200.0, P)
    demi = FENETRE_ALTITUDE // 2
    milieu = sim.par_segment[demi:-demi]
    assert all(v == pytest.approx(V_MAX_DESCENTE_KMH) for _, _, v, _ in milieu)
    assert sim.pas_plafonnes == len(milieu)
    assert max(v for _, _, v, _ in sim.par_segment) == pytest.approx(V_MAX_DESCENTE_KMH)


def test_simulation_a_puissance_nulle_plancher():
    """Zéro watt sur le plat : le temps est un plancher, et la simulation le dit."""
    sim = simuler(trace_plate(1_000.0), 0.0, P)
    assert sim.pas_bloques == len(sim.par_segment)
    assert math.isfinite(sim.temps_s)


def test_simulation_du_vent():
    """Le vent de face allonge, le vent de dos raccourcit, à puissance égale."""
    trace = trace_plate(10_000.0)
    calme = simuler(trace, 200.0, P).temps_s
    face = simuler(trace, 200.0, P, vent=lambda d, cap: 5.0).temps_s
    dos = simuler(trace, 200.0, P, vent=lambda d, cap: -5.0).temps_s
    assert dos < calme < face


def test_le_vent_recoit_le_cap_local():
    """Le tracé va plein est : le cap passé au vent doit valoir 90°."""
    caps = []
    simuler(trace_plate(1_000.0), 200.0, P, vent=lambda d, cap: caps.append(cap) or 0.0)
    assert caps
    assert all(c == pytest.approx(90.0, abs=0.5) for c in caps)


def test_simulation_d_un_trace_de_deux_points():
    trace = trace_plate(250.0, pas_m=250.0)
    assert len(trace.points) == 2
    sim = simuler(trace, 200.0, P)
    assert sim.distance_m == pytest.approx(250.0, abs=1.0)
    assert sum(t for *_, t in sim.par_segment) == pytest.approx(sim.temps_s)


def test_simulation_refuse_un_trace_degenere():
    un_point = Trace("x", [PointTrace(0.0, 0.0, None, 0.0)], [], 0.0, None, None)
    with pytest.raises(ErreurUtilisateur):
        simuler(un_point, 200.0, P)
    deux_fois_le_meme = Trace(
        "x", [PointTrace(0.0, 0.0, None, 0.0), PointTrace(0.0, 0.0, None, 0.0)], [], 0.0, None, None
    )
    with pytest.raises(ErreurUtilisateur):
        simuler(deux_fois_le_meme, 200.0, P)


def test_simulation_sans_altitude_est_plate():
    points = [
        PointTrace(lat=0.0, lon=d * METRE_EN_DEGRE, alt_m=None, dist_m=float(d))
        for d in range(0, 2001, 100)
    ]
    trace = Trace("sans alt", points, [], 2000.0, None, None)
    sim = simuler(trace, 200.0, P)
    assert all(pente == pytest.approx(0.0) for _, pente, _, _ in sim.par_segment)


def test_le_dernier_pas_absorbe_le_reste():
    """10 000,03 m ne doivent pas produire un pas de trois centimètres."""
    trace = trace_plate(10_000.0)
    points = list(trace.points)
    points.append(PointTrace(lat=0.0, lon=10_000.03 * METRE_EN_DEGRE, alt_m=100.0, dist_m=10_000.03))
    trace = Trace("x", points, [], 10_000.03, None, None)
    sim = simuler(trace, 200.0, P)
    assert all(dist_fin > 0 for dist_fin, _, _, _ in sim.par_segment)
    longueurs = [
        b - a
        for a, b in zip(
            [0.0] + [d for d, _, _, _ in sim.par_segment[:-1]],
            [d for d, _, _, _ in sim.par_segment],
            strict=True,
        )
    ]
    assert min(longueurs) >= PAS_M / 10


# --- vent météo ramené à hauteur de cycliste ---------------------------------


def test_facteur_vent_hauteur_suit_le_profil_logarithmique():
    """0,6 n'est pas un réglage : c'est ln(1,5/0,1) / ln(10/0,1) arrondi.

    z = 1,5 m (buste), z₀ = 0,1 m (bocage), référence météo 10 m.
    """
    theorique = math.log(1.5 / 0.1) / math.log(10.0 / 0.1)
    assert theorique == pytest.approx(0.588, abs=0.001)
    assert FACTEUR_VENT_HAUTEUR == pytest.approx(theorique, abs=0.02)


def test_vent_au_cycliste_conserve_le_signe_et_le_zero():
    assert vent_au_cycliste(10.0) == pytest.approx(6.0)
    assert vent_au_cycliste(-10.0) == pytest.approx(-6.0)
    assert vent_au_cycliste(0.0) == 0.0


# --- à plat, sans vent, lancé (décision 7 : l'édition bidirectionnelle) --------


@pytest.mark.parametrize("puissance", [50.0, 100.0, 155.0, 250.0, 400.0])
def test_a_plat_l_aller_retour_puissance_vitesse_est_exact(puissance):
    """Éditer les watts puis la vitesse doit ramener aux mêmes watts.

    C'est le mécanisme de l'écran de FTP : les deux champs se répondent, et
    l'utilisateur ne doit pas voir sa saisie dériver de quelques watts à
    chaque aller-retour.
    """
    kmh = vitesse_a_plat_kmh(puissance, P)
    assert puissance_a_plat_w(kmh, P) == pytest.approx(puissance, abs=1e-6)


@pytest.mark.parametrize("kmh", [10.0, 20.0, 28.6, 35.0, 45.0])
def test_a_plat_l_aller_retour_vitesse_puissance_est_exact(kmh):
    watts = puissance_a_plat_w(kmh, P)
    assert vitesse_a_plat_kmh(watts, P) == pytest.approx(kmh, abs=1e-6)


def test_a_plat_est_exactement_le_cas_pente_nulle_vent_nul():
    """Les raccourcis ne sont pas un second modèle : ce sont les mêmes lignes."""
    assert vitesse_a_plat_ms(200.0, P) == vitesse_regime(200.0, 0.0, 0.0, P)
    assert vitesse_a_plat_kmh(200.0, P) == pytest.approx(vitesse_regime(200.0, 0.0, 0.0, P) * 3.6)
    assert puissance_a_plat_w(30.0, P) == puissance_requise(30.0 / 3.6, 0.0, 0.0, P)


def test_a_plat_la_vitesse_croit_avec_la_puissance():
    vitesses = [vitesse_a_plat_kmh(p, P) for p in (50.0, 100.0, 200.0, 300.0)]
    assert vitesses == sorted(vitesses)
    assert all(b > a for a, b in zip(vitesses, vitesses[1:], strict=False))


def test_a_plat_puissance_nulle_donne_une_vitesse_nulle():
    assert vitesse_a_plat_kmh(0.0, P) == pytest.approx(0.0, abs=1e-6)
    assert puissance_a_plat_w(0.0, P) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("mauvaise", [-1.0, -30.0])
def test_a_plat_une_vitesse_negative_est_refusee(mauvaise):
    """Reculer n'est pas un régime : mieux vaut lever que rendre une puissance
    négative que l'écran afficherait comme une cible."""
    with pytest.raises(ErreurUtilisateur, match="négative"):
        puissance_a_plat_w(mauvaise, P)


@pytest.mark.parametrize("mauvaise", [float("nan"), float("inf")])
def test_a_plat_une_vitesse_non_finie_est_refusee(mauvaise):
    with pytest.raises(ErreurUtilisateur, match="vitesse_kmh"):
        puissance_a_plat_w(mauvaise, P)


# --- la moyenne du compteur (décision 8 : la troisième valeur) ----------------

#: Deux cyclistes que seule la masse sépare. Chiffres synthétiques : ce ne sont
#: ni la masse ni le vélo de qui que ce soit.
LEGER = Parametres(masse_totale_kg=70.0, cda_m2=0.30, crr=0.004)
LOURD = Parametres(masse_totale_kg=95.0, cda_m2=0.30, crr=0.004)

#: Puissance d'essai, en watts. Un régime d'endurance plausible, rien de plus.
PUISSANCE_ESSAI = 170.0


def test_le_facteur_par_defaut_est_une_fraction_plausible():
    """Entre la moitié et la totalité de la vitesse à plat : au-delà, le défaut
    ne servirait plus à rien ; en deçà, ce ne serait plus du vélo."""
    facteur = facteur_compteur_defaut(PUISSANCE_ESSAI, LEGER)
    assert 0.5 < facteur < 1.0


def test_sans_relief_ni_arret_le_facteur_vaut_un():
    """Le plat sans arrêt, c'est exactement la vitesse à plat : le seul cas où
    la troisième valeur n'apprend rien."""
    facteur = facteur_compteur_defaut(
        PUISSANCE_ESSAI, LEGER, denivele_m_par_km=0.0, part_arret=0.0
    )
    assert facteur == pytest.approx(1.0, abs=1e-9)


def test_les_arrets_sont_un_facteur_multiplicatif_exact():
    """La part d'arrêt s'applique telle quelle sur le reste : c'est ce qui
    permet de la lire comme une convention séparée du modèle physique."""
    sans = facteur_compteur_defaut(PUISSANCE_ESSAI, LEGER, part_arret=0.0)
    avec = facteur_compteur_defaut(PUISSANCE_ESSAI, LEGER, part_arret=0.20)
    assert avec == pytest.approx(sans * 0.80, rel=1e-12)


def test_le_relief_coute_toujours_quelque_chose():
    """La convexité de puissance → vitesse : la côte coûte plus que la descente
    ne rend, donc plus de dénivelé fait toujours tomber le facteur."""
    precedent = 1.1
    for denivele in (0.0, 5.0, 10.0, 20.0):
        facteur = facteur_compteur_defaut(
            PUISSANCE_ESSAI, LEGER, denivele_m_par_km=denivele, part_arret=0.0
        )
        assert facteur < precedent
        precedent = facteur


def test_le_facteur_depend_de_la_masse_et_c_est_tout_l_interet():
    """Le point du lot : un facteur écrit en dur serait faux pour tout le monde
    sauf son auteur. Vingt-cinq kilos de plus coûtent plusieurs points de
    facteur sur le vallonné — et aucun sur le plat, où la masse ne joue que par
    le roulement, qui ne dépend pas de la pente."""
    assert facteur_compteur_defaut(PUISSANCE_ESSAI, LOURD) < facteur_compteur_defaut(
        PUISSANCE_ESSAI, LEGER
    )
    a_plat = facteur_compteur_defaut(PUISSANCE_ESSAI, LOURD, denivele_m_par_km=0.0)
    assert a_plat == pytest.approx(
        facteur_compteur_defaut(PUISSANCE_ESSAI, LEGER, denivele_m_par_km=0.0), rel=1e-12
    )


@pytest.mark.parametrize(
    ("kwargs", "motif"),
    [
        ({"denivele_m_par_km": -1.0}, "négatif"),
        ({"part_arret": 1.0}, "part d'arrêt"),
        ({"part_arret": -0.1}, "part d'arrêt"),
        ({"denivele_m_par_km": float("nan")}, "denivele_m_par_km"),
    ],
)
def test_le_defaut_refuse_une_reference_absurde(kwargs, motif):
    with pytest.raises(ErreurUtilisateur, match=motif):
        facteur_compteur_defaut(PUISSANCE_ESSAI, LEGER, **kwargs)


@pytest.mark.parametrize("mauvaise", [0.0, -10.0])
def test_le_defaut_refuse_une_puissance_nulle_ou_negative(mauvaise):
    """Sans puissance il n'y a pas de vitesse à plat, donc pas de rapport."""
    with pytest.raises(ErreurUtilisateur, match="puissance"):
        facteur_compteur_defaut(mauvaise, LEGER)


def test_la_moyenne_compteur_applique_le_facteur_mesure():
    """Un facteur donné — celui que le cycliste a mesuré — prime sur le défaut."""
    attendue = vitesse_a_plat_kmh(PUISSANCE_ESSAI, LEGER) * 0.85
    assert moyenne_compteur_kmh(PUISSANCE_ESSAI, LEGER, 0.85) == pytest.approx(attendue)


def test_la_moyenne_compteur_retombe_sur_le_defaut():
    """Vélo neuf, aucun historique : le défaut dérivé prend le relais plutôt que
    de laisser l'écran sans troisième valeur."""
    attendue = vitesse_a_plat_kmh(PUISSANCE_ESSAI, LEGER) * facteur_compteur_defaut(
        PUISSANCE_ESSAI, LEGER
    )
    assert moyenne_compteur_kmh(PUISSANCE_ESSAI, LEGER) == pytest.approx(attendue)


def test_la_moyenne_compteur_est_sous_la_vitesse_a_plat():
    """C'est toute la raison d'afficher la troisième valeur : elle doit être
    visiblement plus basse que le champ « à plat » qu'on vient de remplir."""
    assert moyenne_compteur_kmh(PUISSANCE_ESSAI, LEGER) < vitesse_a_plat_kmh(
        PUISSANCE_ESSAI, LEGER
    )


@pytest.mark.parametrize("mauvais", [0.0, -0.5, float("nan")])
def test_la_moyenne_compteur_refuse_un_facteur_absurde(mauvais):
    with pytest.raises(ErreurUtilisateur):
        moyenne_compteur_kmh(PUISSANCE_ESSAI, LEGER, mauvais)


# --- temps_ecoule (L9.1 : une fourchette, plus une moyenne à plat) -----------


def test_temps_ecoule_multiplie_le_temps_simule_par_la_fourchette():
    """La formule à la main : 4 h 20 de mouvement × [1,015 ; 1,039 ; 1,072]
    — l'exemple de la note du 23/09, « entre 4 h 23 et 4 h 38 »."""
    f = FourchettePorteAPorte(bas=1.015, mediane=1.039, haut=1.072, provenance="mesure", n=83)
    pp = temps_ecoule(4 * 3600 + 20 * 60, f)
    assert pp.bas_s == pytest.approx(15600 * 1.015)  # 4 h 23 min 54 s
    assert pp.mediane_s == pytest.approx(15600 * 1.039)
    assert pp.haut_s == pytest.approx(15600 * 1.072)  # 4 h 38 min 43 s
    assert pp.provenance == "mesure"


def test_temps_ecoule_ignore_la_distance_et_suit_le_relief_du_trace():
    """Le défaut que L9.1 corrige : le porte à porte ne dépend plus que du
    temps simulé de CE tracé-ci. Deux boucles de même distance, l'une deux
    fois plus lente (vallonnée), ont deux porte à porte dans le même
    rapport — l'ancienne formule leur donnait le même, à plat."""
    f = FourchettePorteAPorte(bas=1.02, mediane=1.05, haut=1.09)
    plat, montagne = temps_ecoule(3600.0, f), temps_ecoule(7200.0, f)
    assert montagne.mediane_s == pytest.approx(2 * plat.mediane_s)


def test_temps_ecoule_rend_la_provenance_de_la_fourchette():
    pp = temps_ecoule(3600.0, FourchettePorteAPorte(bas=1.02, mediane=1.05, haut=1.09))
    assert pp.provenance == "defaut"
    assert pp.bas_s <= pp.mediane_s <= pp.haut_s


@pytest.mark.parametrize("mauvais", [-1.0, float("nan"), float("inf")])
def test_temps_ecoule_refuse_un_temps_absurde(mauvais):
    with pytest.raises(ErreurUtilisateur):
        temps_ecoule(mauvais, FourchettePorteAPorte(bas=1.02, mediane=1.05, haut=1.09))


@pytest.mark.parametrize(
    ("bas", "mediane", "haut", "provenance"),
    [
        (1.10, 1.05, 1.09, "mesure"),  # bas au-dessus de la médiane
        (1.02, 1.10, 1.09, "mesure"),  # médiane au-dessus du haut
        (0.0, 1.05, 1.09, "mesure"),  # un ratio nul n'a pas de sens
        (float("nan"), 1.05, 1.09, "mesure"),
        (1.02, 1.05, 1.09, "devine"),  # provenance inconnue
    ],
)
def test_la_fourchette_refuse_l_incoherent(bas, mediane, haut, provenance):
    with pytest.raises(ErreurUtilisateur):
        FourchettePorteAPorte(bas=bas, mediane=mediane, haut=haut, provenance=provenance)

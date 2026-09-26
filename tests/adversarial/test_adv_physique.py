"""Modèle physique et simulation, mis à l'épreuve.

C'est le point critique des estimations de temps : une erreur de signe ou une
borne oubliée ici se voit sur toutes les colonnes « temps estimé » sans jamais
lever d'exception.

Ce qui est traqué :

* la **division par zéro** : `vitesse_regime(0 W, pente 0)` vaut 0 m/s, et
  `puissance_requise` à vitesse nulle vaut 0 W — pas `nan`, pas `inf` ;
* la **réciprocité** : le contrat exige
  `puissance_requise(vitesse_regime(P)) = P` à 0,1 W. C'est la seule
  vérification qui attrape une constante fausse des deux côtés ;
* le **vent de dos plus rapide que le cycliste** : `v + v_vent` devient
  négatif et la traînée change de signe. Un modèle qui élève `(v + v_vent)`
  au carré sans garder le signe fait accélérer le cycliste dans le vent de
  face ; un modèle qui prend la valeur absolue lui fait payer un vent qui le
  pousse. Dans les deux cas, la vitesse doit rester bornée et croissante avec
  la puissance ;
* les **entrées qui n'existent pas** : pente `NaN`, masse nulle ou négative,
  Crr et CdA nuls, descente à −20 % ;
* la **puissance qui lève** : `simuler` accepte un `Callable`. Si le callable
  lève et que `simuler` avale l'exception, le mainteneur reçoit un temps
  plausible calculé sur rien.
"""

from __future__ import annotations

import math
from typing import Any

import fabriques
import fabriques_physique
import pytest
from outils import robuste

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import Trace
from ourouler.physique import modele as module_modele

#: Bornes du modèle, réécrites ici plutôt que lues dans le module testé.
V_MAX_MS = 30.0
V_MAX_DESCENTE_KMH = 60.0
#: Marge d'arrondi sur le plafond : 60,000000000000014 km/h reste 60 km/h.
PLAFOND_KMH = V_MAX_DESCENTE_KMH * (1 + 1e-9)
TOLERANCE_RECIPROQUE_W = 0.1

ERREURS = (ErreurUtilisateur, ValueError)

#: Une exception d'appelant, reconnaissable et dérivée d'`Exception` : un
#: `except Exception:` dans `simuler` doit se voir, pas passer inaperçu.
class BoumAppelant(Exception):
    """Levée par un callable de test. Ne doit jamais être avalée."""


def _p(module, **surcharges):
    return fabriques_physique.parametres(module, **surcharges)


def _trace_pente(pente: float, *, n: int = 51, pas_m: float = 100.0, alt0: float = 200.0) -> Trace:
    """Une droite de pente constante — la pente lissée doit y valoir exactement `pente`."""
    coords = fabriques.ligne(n, pas_m=pas_m)
    avec_alt = [(lat, lon, alt0 + pente * pas_m * i) for i, (lat, lon, _) in enumerate(coords)]
    return fabriques.trace_fictive(avec_alt, denivele_m=max(0.0, pente) * pas_m * (n - 1))


def _nombre(valeur: Any, quoi: str) -> float:
    assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
        f"{quoi} : nombre attendu, reçu {type(valeur).__name__} ({valeur!r})"
    )
    assert not math.isnan(valeur), f"{quoi} : NaN"
    assert math.isfinite(valeur), f"{quoi} : infini"
    return float(valeur)


def _vitesse(valeur: Any, quoi: str) -> float:
    v = _nombre(valeur, quoi)
    assert 0.0 <= v <= V_MAX_MS, f"{quoi} = {v} m/s, hors de la borne 0-30 m/s du contrat"
    return v


# --- puissance_requise --------------------------------------------------------


def test_puissance_requise_a_vitesse_nulle():
    """Pente 0 et vitesse 0 : aucune division par zéro."""
    module = module_modele
    p = _p(module)
    assert _nombre(
        module.puissance_requise(0.0, 0.0, 0.0, p), "puissance_requise(0 m/s, plat, sans vent)"
    ) == pytest.approx(0.0, abs=1e-6), "immobile sur le plat sans vent, la puissance requise est nulle"


def test_puissance_requise_croit_avec_la_vitesse_sur_le_plat():
    module = module_modele
    p = _p(module)
    valeurs = [
        _nombre(module.puissance_requise(v, 0.0, 0.0, p), f"puissance_requise({v} m/s)")
        for v in (1.0, 3.0, 5.0, 8.0, 12.0, 16.0, 20.0)
    ]
    assert all(b > a for a, b in zip(valeurs, valeurs[1:], strict=False)), (
        f"la puissance ne croît pas avec la vitesse sur le plat : {valeurs}"
    )


def test_puissance_requise_croit_avec_la_pente():
    module = module_modele
    p = _p(module)
    valeurs = [
        _nombre(module.puissance_requise(6.0, pente, 0.0, p), f"puissance_requise(pente={pente})")
        for pente in (-0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    ]
    assert all(b > a for a, b in zip(valeurs, valeurs[1:], strict=False)), (
        f"la puissance ne croît pas avec la pente à vitesse constante : {valeurs}"
    )


def test_puissance_requise_croit_avec_le_vent_de_face():
    module = module_modele
    p = _p(module)
    valeurs = [
        _nombre(module.puissance_requise(8.0, 0.0, vent, p), f"puissance_requise(vent={vent})")
        for vent in (-8.0, -4.0, 0.0, 4.0, 8.0)
    ]
    assert all(b > a for a, b in zip(valeurs, valeurs[1:], strict=False)), (
        f"la puissance ne croît pas avec le vent de face : {valeurs} — "
        "le signe du vent relatif est perdu (valeur absolue ou carré nu ?)"
    )


def test_un_vent_de_dos_plus_rapide_que_le_cycliste_allege_la_traine():
    """Angle obligatoire : `v + v_vent` négatif, la traînée change de signe.

    À 2 m/s avec 15 m/s de vent dans le dos, l'air pousse : la puissance
    requise est inférieure à celle du même effort sans vent, et elle peut
    même être négative. Ce qui est interdit, c'est qu'elle soit **supérieure**
    — ce que donne un `(v + v_vent) ** 2` sans signe.
    """
    module = module_modele
    p = _p(module)
    sans_vent = _nombre(module.puissance_requise(2.0, 0.0, 0.0, p), "puissance_requise(sans vent)")
    vent_de_dos = _nombre(
        module.puissance_requise(2.0, 0.0, -15.0, p), "puissance_requise(vent de dos 15 m/s)"
    )
    assert vent_de_dos < sans_vent, (
        f"{vent_de_dos:.1f} W avec 15 m/s de vent dans le dos contre {sans_vent:.1f} W sans "
        "vent : la traînée ne change pas de signe quand le vent dépasse la vitesse"
    )


@pytest.mark.parametrize("pente", [-0.20, -0.08, 0.0, 0.08, 0.20])
def test_puissance_requise_reste_finie_sur_les_pentes_extremes(pente):
    """Jusqu'à −20 % de pente, la puissance requise reste finie."""
    module = module_modele
    p = _p(module)
    for v in (0.0, 5.0, 15.0, V_MAX_MS):
        _nombre(module.puissance_requise(v, pente, 0.0, p), f"puissance_requise({v}, {pente})")


def test_puissance_requise_avec_une_pente_nan():
    """Angle obligatoire : pente NaN. Refus ou valeur finie, jamais un NaN qui se propage."""
    module = module_modele
    p = _p(module)
    resultat, _ = robuste(
        lambda: module.puissance_requise(6.0, float("nan"), 0.0, p),
        quoi="puissance_requise(pente=NaN)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _nombre(resultat, "puissance_requise(pente=NaN)")


# --- vitesse_regime -----------------------------------------------------------


def test_vitesse_regime_a_puissance_nulle():
    """Pente 0 et puissance 0 → vitesse 0, sans division par zéro."""
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(10.0, "vitesse_regime(0 W)"):
        v = _vitesse(module.vitesse_regime(0.0, 0.0, 0.0, p), "vitesse_regime(0 W, plat, sans vent)")
    assert v == pytest.approx(0.0, abs=1e-3), f"0 W sur le plat sans vent donne {v} m/s"


@pytest.mark.parametrize(("pente", "vent"), [(0.0, 0.0), (0.05, 0.0), (-0.05, 0.0), (0.0, 6.0), (0.0, -6.0)])
def test_vitesse_regime_croit_avec_la_puissance(pente, vent):
    """`vitesse_regime` est monotone en puissance."""
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(20.0, f"vitesse_regime(pente={pente}, vent={vent})"):
        vitesses = [
            _vitesse(
                module.vitesse_regime(puissance, pente, vent, p),
                f"vitesse_regime({puissance} W, pente={pente}, vent={vent})",
            )
            for puissance in (0.0, 25.0, 50.0, 100.0, 150.0, 200.0, 300.0, 400.0, 600.0)
        ]
    reculs = [
        (a, b) for a, b in zip(vitesses, vitesses[1:], strict=False) if b < a - 1e-6
    ]
    assert not reculs, (
        f"la vitesse recule quand la puissance monte (pente={pente}, vent={vent}) : {vitesses}"
    )


def test_vitesse_regime_reste_bornee_avec_un_vent_de_dos_plus_rapide_que_le_cycliste():
    """Angle obligatoire : vent de dos supérieur à la vitesse — borné **et** monotone."""
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(20.0, "vitesse_regime(vent de dos 15 m/s)"):
        vitesses = [
            _vitesse(
                module.vitesse_regime(puissance, 0.0, -15.0, p),
                f"vitesse_regime({puissance} W, vent de dos 15 m/s)",
            )
            for puissance in (0.0, 10.0, 50.0, 100.0, 200.0, 400.0)
        ]
    reculs = [(a, b) for a, b in zip(vitesses, vitesses[1:], strict=False) if b < a - 1e-6]
    assert not reculs, f"vent de dos de 15 m/s : la vitesse n'est plus monotone {vitesses}"
    assert vitesses[-1] <= V_MAX_MS, f"{vitesses[-1]} m/s à 400 W, borne du contrat : {V_MAX_MS}"


@pytest.mark.parametrize("pente", [-0.20, -0.10, 0.0, 0.08, 0.15])
@pytest.mark.parametrize("vent", [-5.0, 0.0, 7.0])
@pytest.mark.parametrize("puissance", [60.0, 150.0, 250.0, 400.0])
def test_puissance_requise_est_bien_l_inverse_de_vitesse_regime(pente, vent, puissance):
    """`puissance_requise(vitesse_regime(P)) = P` à 0,1 W près.

    L'égalité ne peut évidemment pas tenir quand la vitesse sature à la borne
    du contrat (une descente à −20 % à 400 W) : on ne la vérifie qu'à
    l'intérieur de l'intervalle.
    """
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(10.0, "vitesse_regime"):
        v = _vitesse(module.vitesse_regime(puissance, pente, vent, p), "vitesse_regime")
    if v <= 1e-6 or v >= V_MAX_MS - 1e-6:
        pytest.skip(f"vitesse saturée ({v} m/s) : la réciprocité ne s'applique pas")
    retour = _nombre(module.puissance_requise(v, pente, vent, p), "puissance_requise(vitesse_regime)")
    assert retour == pytest.approx(puissance, abs=TOLERANCE_RECIPROQUE_W), (
        f"vitesse_regime({puissance} W) = {v:.4f} m/s, qui redemande {retour:.4f} W — "
        f"écart de {abs(retour - puissance):.3f} W pour une tolérance de {TOLERANCE_RECIPROQUE_W} W"
    )


@pytest.mark.parametrize("puissance", [-100.0, float("nan"), float("inf")])
def test_vitesse_regime_avec_une_puissance_absurde(puissance):
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(10.0, f"vitesse_regime({puissance})"):
        resultat, _ = robuste(
            lambda: module.vitesse_regime(puissance, 0.0, 0.0, p),
            quoi=f"vitesse_regime({puissance} W)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _vitesse(resultat, f"vitesse_regime({puissance} W)")


def test_vitesse_regime_avec_une_pente_nan():
    """Angle obligatoire : pente NaN. Une bissection sur un NaN ne converge jamais."""
    module = module_modele
    p = _p(module)
    with fabriques.limite_temps(10.0, "vitesse_regime(pente=NaN)"):
        resultat, _ = robuste(
            lambda: module.vitesse_regime(200.0, float("nan"), 0.0, p),
            quoi="vitesse_regime(pente=NaN)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _vitesse(resultat, "vitesse_regime(pente=NaN)")


@pytest.mark.parametrize("masse", [0.0, -5.0])
def test_le_modele_avec_une_masse_nulle_ou_negative(masse):
    """Angle obligatoire : masse ≤ 0. Une masse nulle annule gravité et roulement."""
    module = module_modele
    p, _ = robuste(
        lambda: _p(module, masse_totale_kg=masse),
        quoi=f"Parametres(masse_totale_kg={masse})",
        erreurs_acceptees=ERREURS,
    )
    if p is None:
        return  # refusée à la construction : c'est une réponse
    with fabriques.limite_temps(10.0, f"vitesse_regime(masse={masse})"):
        resultat, _ = robuste(
            lambda: module.vitesse_regime(200.0, 0.03, 0.0, p),
            quoi=f"vitesse_regime(masse={masse})",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _vitesse(resultat, f"vitesse_regime(masse={masse})")


@pytest.mark.parametrize(("cda", "crr"), [(0.0, 0.005), (0.32, 0.0), (0.0, 0.0)])
def test_le_modele_avec_un_cda_ou_un_crr_nul(cda, crr):
    """Sans traînée ni roulement, la vitesse d'équilibre est infinie : la borne doit tenir."""
    module = module_modele
    p, _ = robuste(
        lambda: _p(module, cda_m2=cda, crr=crr),
        quoi=f"Parametres(cda={cda}, crr={crr})",
        erreurs_acceptees=ERREURS,
    )
    if p is None:
        return
    with fabriques.limite_temps(10.0, f"vitesse_regime(cda={cda}, crr={crr})"):
        resultat, _ = robuste(
            lambda: module.vitesse_regime(300.0, 0.0, 0.0, p),
            quoi=f"vitesse_regime(cda={cda}, crr={crr})",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _vitesse(resultat, f"vitesse_regime(cda={cda}, crr={crr})")


# --- simuler ------------------------------------------------------------------


def _verifier_simulation(simulation: Any, trace: Trace, quoi: str) -> None:
    temps = _nombre(simulation.temps_s, f"{quoi}.temps_s")
    distance = _nombre(simulation.distance_m, f"{quoi}.distance_m")
    moyenne = _nombre(simulation.vitesse_moy_kmh, f"{quoi}.vitesse_moy_kmh")
    assert temps > 0, f"{quoi}.temps_s = {temps} : une sortie dure un temps strictement positif"
    assert distance >= 0, f"{quoi}.distance_m = {distance}"
    if trace.distance_m:
        assert distance == pytest.approx(trace.distance_m, rel=0.05), (
            f"{quoi}.distance_m = {distance:.0f} pour un tracé de {trace.distance_m:.0f} m"
        )
    assert 0 < moyenne <= PLAFOND_KMH, (
        f"{quoi}.vitesse_moy_kmh = {moyenne}, plafond du contrat : {V_MAX_DESCENTE_KMH}"
    )
    assert moyenne == pytest.approx(distance / temps * 3.6, rel=0.05), (
        f"{quoi} : {moyenne:.2f} km/h pour {distance:.0f} m en {temps:.0f} s "
        f"({distance / temps * 3.6:.2f} km/h)"
    )
    assert isinstance(simulation.par_segment, list), f"{quoi}.par_segment : liste attendue"
    cumul_t = 0.0
    for i, segment in enumerate(simulation.par_segment):
        assert len(segment) == 4, (
            f"{quoi}.par_segment[{i}] : le contrat décrit (dist_m, pente, v_kmh, t_s), "
            f"reçu {segment!r}"
        )
        dist, pente, v_kmh, t_s = segment
        _nombre(dist, f"{quoi}.par_segment[{i}].dist_m")
        _nombre(pente, f"{quoi}.par_segment[{i}].pente")
        assert abs(pente) <= 1.0, f"{quoi}.par_segment[{i}] : pente = {pente} (une pente, pas un %)"
        assert 0 <= _nombre(v_kmh, f"{quoi}.par_segment[{i}].v_kmh") <= PLAFOND_KMH, (
            f"{quoi}.par_segment[{i}] : {v_kmh} km/h, plafond du contrat {V_MAX_DESCENTE_KMH}"
        )
        assert _nombre(t_s, f"{quoi}.par_segment[{i}].t_s") >= 0
        cumul_t += t_s
    if simulation.par_segment:
        assert cumul_t == pytest.approx(temps, rel=0.05), (
            f"{quoi} : les temps par segment font {cumul_t:.0f} s pour un total de {temps:.0f} s"
        )


def test_simuler_un_plat_a_puissance_constante():
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=101, pas_m=100.0)  # 10 km
    with fabriques.limite_temps(20.0, "simuler(plat)"):
        simulation = module.simuler(trace, 200.0, p)
    _verifier_simulation(simulation, trace, "simuler(plat, 200 W)")
    attendue = module.vitesse_regime(200.0, 0.0, 0.0, p) * 3.6
    assert simulation.vitesse_moy_kmh == pytest.approx(attendue, rel=0.10), (
        f"{simulation.vitesse_moy_kmh:.1f} km/h sur 10 km de plat à 200 W, là où la vitesse "
        f"d'équilibre vaut {attendue:.1f} km/h"
    )


def test_simuler_une_descente_plafonne_la_vitesse():
    """La vitesse est plafonnée en descente (`v_max_kmh = 60`)."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(-0.10, n=101, pas_m=100.0, alt0=1200.0)
    with fabriques.limite_temps(20.0, "simuler(descente)"):
        simulation = module.simuler(trace, 250.0, p)
    _verifier_simulation(simulation, trace, "simuler(descente à 10 %, 250 W)")
    assert simulation.vitesse_moy_kmh <= PLAFOND_KMH, (
        f"{simulation.vitesse_moy_kmh:.1f} km/h en descente : le plafond de "
        f"{V_MAX_DESCENTE_KMH} km/h n'est pas appliqué"
    )


def test_simuler_une_montee_est_plus_lent_qu_un_plat():
    module = module_modele
    p = _p(module)
    plat = _trace_pente(0.0, n=101, pas_m=100.0)
    montee = _trace_pente(0.06, n=101, pas_m=100.0)
    with fabriques.limite_temps(30.0, "simuler(plat vs montée)"):
        t_plat = module.simuler(plat, 200.0, p).temps_s
        t_montee = module.simuler(montee, 200.0, p).temps_s
    assert t_montee > t_plat * 1.5, (
        f"10 km à 6 % en {t_montee:.0f} s contre {t_plat:.0f} s sur le plat, à 200 W : "
        "la pente n'est pas prise en compte"
    )


def test_simuler_un_trace_de_deux_points():
    """Un tracé de 2 points, plus court que le pas de 100 m, se simule."""
    module = module_modele
    p = _p(module)
    trace = fabriques.trace_fictive(fabriques.ligne(2, pas_m=40.0))
    with fabriques.limite_temps(10.0, "simuler(2 points)"):
        resultat, _ = robuste(
            lambda: module.simuler(trace, 200.0, p),
            quoi="simuler(tracé de 2 points)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _verifier_simulation(resultat, trace, "simuler(2 points)")


@pytest.mark.parametrize("nb", [0, 1])
def test_simuler_un_trace_sans_longueur(nb):
    module = module_modele
    p = _p(module)
    trace = (
        fabriques.trace_fictive(fabriques.ligne(1, pas_m=100.0))
        if nb
        else Trace("vide", [], [], 0.0, None, None, {})
    )
    with fabriques.limite_temps(10.0, f"simuler({nb} point)"):
        resultat, _ = robuste(
            lambda: module.simuler(trace, 200.0, p),
            quoi=f"simuler(tracé de {nb} point)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        assert _nombre(resultat.temps_s, "temps_s") >= 0
        assert _nombre(resultat.distance_m, "distance_m") >= 0


def test_simuler_un_trace_sans_altitude():
    """Un GPX sans `<ele>` : pente inconnue, pas pente `None` propagée jusqu'à la division."""
    module = module_modele
    p = _p(module)
    coords = [(lat, lon, None) for lat, lon, _ in fabriques.ligne(101, pas_m=100.0)]
    trace = fabriques.trace_fictive(coords, denivele_m=None)
    with fabriques.limite_temps(20.0, "simuler(sans altitude)"):
        resultat, _ = robuste(
            lambda: module.simuler(trace, 200.0, p),
            quoi="simuler(tracé sans altitude)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _verifier_simulation(resultat, trace, "simuler(sans altitude)")


def test_simuler_a_puissance_nulle():
    """0 W sur le plat : la vitesse d'équilibre est nulle, donc le temps est infini."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=51, pas_m=100.0)
    with fabriques.limite_temps(20.0, "simuler(0 W)"):
        resultat, _ = robuste(
            lambda: module.simuler(trace, 0.0, p), quoi="simuler(0 W)", erreurs_acceptees=ERREURS
        )
    if resultat is not None:
        temps = _nombre(resultat.temps_s, "simuler(0 W).temps_s")
        assert temps > 0, f"temps_s = {temps} à 0 W"


def test_simuler_avec_une_puissance_callable():
    """Le contrat accepte `Callable[[float], float]` : la puissance varie le long du tracé."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=101, pas_m=100.0)
    vus: list[float] = []

    def puissance(x):
        vus.append(float(x))
        return 200.0

    with fabriques.limite_temps(20.0, "simuler(puissance callable)"):
        simulation = module.simuler(trace, puissance, p)
    _verifier_simulation(simulation, trace, "simuler(puissance callable)")
    assert vus, "le callable de puissance n'a jamais été appelé"
    assert max(vus) > min(vus), (
        f"le callable est toujours appelé avec la même valeur ({vus[0]}) : "
        "l'argument n'est pas l'abscisse le long du tracé"
    )


def test_une_puissance_callable_qui_leve_ne_doit_pas_etre_avalee():
    """Angle obligatoire : si le callable lève, `simuler` ne doit pas rendre un temps."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=51, pas_m=100.0)

    def puissance(_x):
        raise BoumAppelant("la séance du jour est illisible")

    with fabriques.limite_temps(20.0, "simuler(puissance qui lève)"):
        with pytest.raises(BaseException) as capture:  # noqa: B017 — on vérifie l'identité ensuite
            module.simuler(trace, puissance, p)
    chaine = []
    erreur: BaseException | None = capture.value
    while erreur is not None and len(chaine) < 10:
        chaine.append(erreur)
        erreur = erreur.__cause__ or erreur.__context__
    assert any(isinstance(e, BoumAppelant) for e in chaine), (
        f"simuler a remplacé l'exception du callable par {capture.value!r} sans la chaîner : "
        "l'origine de la panne est perdue"
    )


@pytest.mark.parametrize("valeur", [float("nan"), float("-inf"), -50.0])
def test_une_puissance_callable_qui_rend_une_valeur_absurde(valeur):
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=51, pas_m=100.0)
    with fabriques.limite_temps(20.0, f"simuler(puissance -> {valeur})"):
        resultat, _ = robuste(
            lambda: module.simuler(trace, lambda _x: valeur, p),
            quoi=f"simuler(puissance -> {valeur})",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _verifier_simulation(resultat, trace, f"simuler(puissance -> {valeur})")


def test_simuler_avec_un_vent_le_long_du_trace():
    """`vent(dist_m, cap_deg) -> vent de face m/s` : un vent de face doit ralentir."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=101, pas_m=100.0)
    vus: list[tuple[float, float]] = []

    def vent(dist_m, cap_deg):
        vus.append((float(dist_m), float(cap_deg)))
        return 6.0

    with fabriques.limite_temps(30.0, "simuler(vent de face)"):
        sans = module.simuler(trace, 200.0, p)
        avec = module.simuler(trace, 200.0, p, vent)
    _verifier_simulation(avec, trace, "simuler(vent de face 6 m/s)")
    assert vus, "la fonction de vent n'a jamais été appelée"
    assert all(0.0 <= cap < 360.0 for _, cap in vus), (
        f"caps hors de [0, 360) transmis à la fonction de vent : "
        f"{sorted({round(c) for _, c in vus})[:10]}"
    )
    assert avec.temps_s > sans.temps_s, (
        f"6 m/s de vent de face ne changent rien au temps ({avec.temps_s:.0f} s contre "
        f"{sans.temps_s:.0f} s)"
    )


def test_un_vent_callable_qui_leve_ne_doit_pas_etre_avale():
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.0, n=51, pas_m=100.0)

    def vent(_d, _c):
        raise BoumAppelant("prévision indisponible")

    with fabriques.limite_temps(20.0, "simuler(vent qui lève)"):
        with pytest.raises(BaseException) as capture:  # noqa: B017 — identité vérifiée ensuite
            module.simuler(trace, 200.0, p, vent)
    chaine = []
    erreur: BaseException | None = capture.value
    while erreur is not None and len(chaine) < 10:
        chaine.append(erreur)
        erreur = erreur.__cause__ or erreur.__context__
    assert any(isinstance(e, BoumAppelant) for e in chaine), (
        f"simuler a avalé l'exception de la fonction de vent et rendu {capture.value!r}"
    )


def test_simuler_ne_modifie_pas_le_trace():
    """La simulation lit le tracé ; la même boucle est ensuite exportée en GPX."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.02, n=101, pas_m=100.0)
    avant = fabriques_physique.copie_lisible(trace)
    with fabriques.limite_temps(20.0, "simuler"):
        module.simuler(trace, 200.0, p)
    assert fabriques_physique.copie_lisible(trace) == avant, "simuler a modifié les points du tracé"


def test_simuler_donne_un_temps_en_mouvement_reproductible():
    """Deux appels identiques donnent le même temps : pas d'état caché entre simulations."""
    module = module_modele
    p = _p(module)
    trace = _trace_pente(0.01, n=101, pas_m=100.0)
    with fabriques.limite_temps(30.0, "simuler(x2)"):
        premier = module.simuler(trace, 200.0, p).temps_s
        second = module.simuler(trace, 200.0, p).temps_s
    assert premier == pytest.approx(second, rel=1e-9), (
        f"deux simulations identiques donnent {premier} s puis {second} s"
    )

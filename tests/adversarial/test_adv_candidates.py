"""L2.3 — génération des candidates de boucle, mise à l'épreuve.

Cible : contrat du sprint 2 §3 et §8. Le moteur est remplacé par un
`MoteurFactice` qui note chaque appel et rend la distance qu'on lui dicte :
c'est le seul moyen de vérifier en aveugle la **stratégie** (azimuts, rayon
initial, ajustement par proportion, plafond d'appels) sans dépendre d'un
serveur BRouter.

Ce que ces tests traquent :

* une stratégie qui ne converge pas et **boucle** (plafond `appels_max`) ;
* une division par zéro sur `ecart_relatif` quand la distance cible est nulle ;
* des candidates non bornées gardées alors que le contrat les écarte ;
* un tri qui ne met pas la meilleure candidate en tête.
"""

from __future__ import annotations

import math
from typing import Any

import fabriques
import pytest
from outils import robuste

from ourouler.boucle.trace import Trace
from ourouler.config import Depart
from ourouler.erreurs import ErreurConnecteur, ErreurDistanceInatteignable, ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L2.3 absent (ourouler.boucle.candidates)"

DEPART = Depart(nom="Point fictif", latitude=fabriques.LAT0, longitude=fabriques.LON0)

#: Le contrat fixe le rayon initial à `distance_km * 1000 / 5` et mesure un
#: ratio d'environ 5 entre rayon demandé et boucle obtenue.
RATIO_MESURE = 5.0


def _module():
    return pytest.importorskip("ourouler.boucle.candidates", reason=MOTIF_ABSENT)


def _trace_de_distance(distance_m: float, *, fermee: bool = True) -> Trace:
    """Une boucle fabriquée dont le périmètre vaut à peu près `distance_m`."""
    if distance_m <= 0:
        trace = fabriques.trace_fictive(fabriques.ligne(2, pas_m=1.0))
        trace.distance_m = 0.0
        return trace
    rayon = distance_m / (2.0 * math.pi)
    coords = fabriques.cercle(36, rayon_m=rayon)
    if not fermee:
        coords = coords[:-1]  # la boucle reste ouverte de tout un côté
    trace = fabriques.trace_fictive(coords, nom=f"boucle {distance_m / 1000:.1f} km")
    trace.distance_m = float(distance_m)
    return trace


class MoteurFactice:
    """Client BRouter bouchon : `boucle()` rend la distance dictée par `loi`."""

    def __init__(
        self,
        loi=None,
        *,
        par_azimut: dict[float, float] | None = None,
        fermee: bool = True,
        lever_a_partir_de: int | None = None,
    ):
        self.appels: list[dict[str, Any]] = []
        self._loi = loi
        self._par_azimut = par_azimut
        self._fermee = fermee
        self._lever = lever_a_partir_de
        self.params = None

    def boucle(self, depart, *, azimut_deg: float, rayon_m: float, **reste: Any) -> Trace:
        self.appels.append({"depart": depart, "azimut_deg": azimut_deg, "rayon_m": rayon_m, **reste})
        if self._lever is not None and len(self.appels) >= self._lever:
            raise ErreurConnecteur("BRouter : le serveur a lâché (fabriqué pour le test)")
        if self._par_azimut is not None:
            distance = self._par_azimut[round(azimut_deg % 360.0, 6)]
        elif callable(self._loi):
            distance = self._loi(rayon_m)
        else:
            distance = float(self._loi)
        return _trace_de_distance(distance, fermee=self._fermee)

    def itineraire(self, points, **reste: Any) -> Trace:  # pragma: no cover - non utilisé ici
        raise AssertionError("generer() ne doit interroger que le mode boucle")

    @property
    def azimuts(self) -> list[float]:
        return [a["azimut_deg"] for a in self.appels]

    @property
    def rayons(self) -> list[float]:
        return [a["rayon_m"] for a in self.appels]


def _generer(module, moteur, **surcharges):
    arguments: dict[str, Any] = {
        "distance_km": 60.0,
        "azimut_deg": 90.0,
        "nb": 5,
        "tolerance": 0.10,
        "appels_max": 12,
    }
    arguments.update(surcharges)
    with fabriques.limite_temps(10.0, "candidates.generer"):
        return module.generer(moteur, DEPART, **arguments)


def _verifier_candidates(candidates, *, cible_km: float, quoi: str) -> None:
    assert isinstance(candidates, list), f"{quoi} : une liste est attendue"
    ecarts = []
    for i, c in enumerate(candidates):
        fabriques.verifier_trace(c.trace, quoi=f"{quoi} candidates[{i}].trace")
        assert math.isfinite(c.ecart_relatif), f"{quoi} : candidates[{i}].ecart_relatif non fini"
        assert math.isfinite(c.rayon_m) and c.rayon_m > 0, (
            f"{quoi} : candidates[{i}].rayon_m = {c.rayon_m!r}"
        )
        assert math.isfinite(c.azimut_deg), f"{quoi} : candidates[{i}].azimut_deg non fini"
        attendu = (c.trace.distance_m - cible_km * 1000.0) / (cible_km * 1000.0)
        assert c.ecart_relatif == pytest.approx(attendu, abs=1e-6), (
            f"{quoi} : candidates[{i}].ecart_relatif = {c.ecart_relatif}, "
            f"attendu (distance − cible)/cible = {attendu}"
        )
        assert c.trace.bornee(), f"{quoi} : candidates[{i}] n'est pas une boucle fermée"
        ecarts.append(abs(c.ecart_relatif))
    assert ecarts == sorted(ecarts), f"{quoi} : candidates non triées par |ecart_relatif| : {ecarts}"


# --- stratégie nominale ------------------------------------------------------


def test_le_rayon_initial_suit_la_regle_du_contrat():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    candidates = _generer(module, moteur, distance_km=60.0)

    assert moteur.rayons, "aucun appel au moteur"
    assert moteur.rayons[0] == pytest.approx(60.0 * 1000.0 / 5.0, rel=0.01), (
        f"rayon initial {moteur.rayons[0]} : le contrat fixe distance_km × 1000 / 5"
    )
    _verifier_candidates(candidates, cible_km=60.0, quoi="ratio parfait")
    assert len(moteur.appels) == 5, (
        f"un moteur qui tombe juste du premier coup ne justifie aucun ajustement "
        f"({len(moteur.appels)} appels pour 5 azimuts)"
    )


def test_l_ajustement_par_proportion_rattrape_une_boucle_trop_courte():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * 4.0)  # 20 % trop court au premier essai
    candidates = _generer(module, moteur, distance_km=60.0, nb=1, tolerance=0.05)

    _verifier_candidates(candidates, cible_km=60.0, quoi="ajustement")
    assert candidates, "avec un moteur linéaire, l'ajustement doit trouver la cible"
    assert abs(candidates[0].ecart_relatif) <= 0.05, (
        f"écart final {candidates[0].ecart_relatif:.3f} : l'ajustement par proportion "
        "(rayon × cible/obtenu) devait rentrer dans la tolérance"
    )
    assert len(moteur.appels) <= 3, (
        f"{len(moteur.appels)} appels pour un azimut : le contrat en autorise deux d'ajustement"
    )


def test_les_azimuts_explorent_de_part_et_d_autre():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    _generer(module, moteur, azimut_deg=90.0, nb=5)

    azimuts = moteur.azimuts
    assert azimuts[0] == pytest.approx(90.0), (
        f"le premier azimut exploré est celui demandé, reçu {azimuts[0]}"
    )
    attendus = {90.0, 70.0, 110.0, 50.0, 130.0}
    obtenus = {round(a % 360.0, 6) for a in azimuts}
    assert obtenus <= attendus, (
        f"azimuts explorés {sorted(obtenus)} : le contrat demande ±20°, ±40°… autour de 90°"
    )
    assert len(obtenus) == 5, f"5 azimuts distincts attendus, reçu {sorted(obtenus)}"


def test_les_azimuts_restent_dans_le_tour_du_compas():
    """`roundTripStartDirection` est un cap : 370° ou −30° n'ont rien à faire dans l'URL."""
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    _generer(module, moteur, azimut_deg=350.0, nb=5)
    hors = [a for a in moteur.azimuts if not 0.0 <= a < 360.0]
    assert not hors, f"azimuts hors de [0, 360) envoyés au moteur : {hors}"


def test_un_seul_candidat_demande_n_explore_qu_un_azimut():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    candidates = _generer(module, moteur, nb=1)
    assert {round(a, 6) for a in moteur.azimuts} == {90.0}
    assert len(candidates) <= 1


# --- moteur récalcitrant -----------------------------------------------------


def test_un_moteur_qui_rend_toujours_la_meme_boucle_ne_tourne_pas_en_rond():
    """Contrat §8 : « moteur qui renvoie toujours la même boucle ».

    Rendre 30 km pour une cible de 60 (écart de −50 %) en silence, quand la
    tolérance vaut 10 %, est exactement le défaut corrigé le 17/09/2026:
    aucun azimut ne peut tenir dans la tolérance même élargie au maximum
    (40 % de manque contre 10 % de plafond), donc la demande refuse plutôt
    que de servir une candidate hors sujet. Le plafond d'appels reste le
    vrai sujet ici, vérifié sur le moteur bouchon.
    """
    module = _module()
    moteur = MoteurFactice(30_000.0)  # 30 km quoi qu'on demande, cible 60 km
    with pytest.raises(ErreurDistanceInatteignable):
        _generer(module, moteur, distance_km=60.0, nb=5, tolerance=0.10, appels_max=12)

    assert len(moteur.appels) <= 12, f"plafond d'appels dépassé : {len(moteur.appels)}"


#: Ajustements de rayon consentis à un azimut, essai initial exclu. Le contrat
#: du sprint 2 §3 écrivait « au plus 2 fois » ; le superviseur l'a porté à 3 le
#: 13/09/2026, après la vérification réelle : l'élagage des antennes (L3.1)
#: retire des centaines de mètres à la boucle du moteur, la distance mesurée
#: oscille (53,6 puis 65,4 km pour 60 demandés) et deux corrections
#: s'arrêtaient au milieu de l'oscillation. Ce qui est testé ici n'a pas
#: changé : un azimut ne mange pas le plafond global d'appels.
AJUSTEMENTS_CONSENTIS = 3


def test_un_azimut_ne_coute_jamais_plus_de_trois_ajustements():
    """Contrat §3, révisé par le superviseur le 13/09 : voir `AJUSTEMENTS_CONSENTIS`.

    Le moteur ne converge jamais vers 60 km (30 km quoi qu'on demande), donc
    la tolérance de 1 % ne peut être tenue même élargie au maximum : la
    demande refuse. Le sujet du test — le nombre d'ajustements consentis à
    un seul azimut — se lit sur le moteur bouchon, refus ou pas.
    """
    module = _module()
    moteur = MoteurFactice(30_000.0)  # ne converge jamais vers 60 km
    with pytest.raises(ErreurDistanceInatteignable):
        _generer(module, moteur, nb=1, tolerance=0.01, appels_max=12)
    assert len(moteur.appels) <= 1 + AJUSTEMENTS_CONSENTIS, (
        f"{len(moteur.appels)} appels pour un seul azimut : un essai initial et "
        f"{AJUSTEMENTS_CONSENTIS} ajustements au maximum, même quand le plafond global "
        "le permettrait"
    )


def test_les_candidates_sont_triees_par_ecart_absolu():
    """Une boucle 2 % trop longue vaut mieux qu'une boucle 20 % trop courte."""
    module = _module()
    cible = 60_000.0
    facteurs = {90.0: 1.30, 110.0: 0.95, 70.0: 1.02, 130.0: 0.80, 50.0: 1.15}
    moteur = MoteurFactice(par_azimut={a: cible * f for a, f in facteurs.items()})
    # Tolérance à 0,30 (au lieu de 0,01) : le plus grand écart fabriqué ici
    # est de 30 %, tout juste dans la tolérance — aucun azimut n'a besoin
    # d'élargissement, ce qui laisse les cinq candidates en jeu pour vérifier
    # le tri, qui est le vrai sujet du test.
    candidates = _generer(
        module, moteur, distance_km=60.0, azimut_deg=90.0, nb=5, tolerance=0.30, appels_max=30
    )
    _verifier_candidates(candidates, cible_km=60.0, quoi="tri")
    assert len(candidates) == 5, f"cinq azimuts, cinq candidates attendues, reçu {len(candidates)}"
    assert candidates[0].azimut_deg == pytest.approx(70.0), (
        "la meilleure candidate est celle dont l'écart est le plus petit **en valeur absolue** "
        f"(2 % trop longue), reçu l'azimut {candidates[0].azimut_deg}"
    )
    assert candidates[-1].azimut_deg == pytest.approx(90.0), "la pire est celle à +30 %"


def test_le_plafond_d_appels_est_respecte_a_la_lettre():
    # 30 km rendus quoi qu'on demande pour une cible de 60 (écart de −50 %) :
    # aucun plafond ne suffit à faire tenir la tolérance par défaut (10 %,
    # même élargie), la demande refuse systématiquement. Le plafond d'appels
    # lui-même — le vrai sujet — se vérifie sur le moteur bouchon, refus ou
    # pas.
    module = _module()
    for plafond in (1, 2, 3, 7):
        moteur = MoteurFactice(30_000.0)
        with pytest.raises(ErreurDistanceInatteignable):
            _generer(module, moteur, appels_max=plafond, nb=5)
        assert len(moteur.appels) <= plafond, (
            f"appels_max={plafond} : {len(moteur.appels)} appels effectués"
        )


def test_un_plafond_nul_n_appelle_pas_le_moteur():
    module = _module()
    moteur = MoteurFactice(30_000.0)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur, appels_max=0),
        quoi="generer(appels_max=0)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    assert not moteur.appels, "appels_max=0 interdit tout appel"
    if erreur is None:
        assert candidates == [], "sans appel, il n'y a pas de candidate"


def test_les_boucles_non_bornees_sont_ecartees():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE, fermee=False)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur),
        quoi="generer(boucles ouvertes)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert candidates == [], (
            "le contrat ne garde que les boucles bornées : une trace ouverte n'est pas une boucle"
        )


def test_une_panne_du_moteur_ne_remonte_pas_en_trace():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE, lever_a_partir_de=3)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur),
        quoi="generer(moteur en panne)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier_candidates(candidates, cible_km=60.0, quoi="moteur en panne")
        assert candidates, "deux azimuts avaient répondu avant la panne"


# --- entrées hostiles --------------------------------------------------------


def test_une_distance_nulle_ne_divise_pas_par_zero():
    """`ecart_relatif = (distance − cible)/cible` : cible nulle = ZeroDivisionError."""
    module = _module()
    moteur = MoteurFactice(30_000.0)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur, distance_km=0.0),
        quoi="generer(distance_km=0)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        for c in candidates:
            assert math.isfinite(c.ecart_relatif), "ecart_relatif infini ou NaN"


@pytest.mark.parametrize("distance_km", [-10.0, float("nan"), float("inf")])
def test_une_distance_absurde_est_refusee_ou_ignoree(distance_km):
    module = _module()
    moteur = MoteurFactice(30_000.0)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur, distance_km=distance_km),
        quoi=f"generer(distance_km={distance_km})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        for c in candidates:
            assert math.isfinite(c.ecart_relatif), f"distance_km={distance_km} : écart non fini"
            assert c.rayon_m > 0, f"distance_km={distance_km} : rayon {c.rayon_m}"


@pytest.mark.parametrize("nb", [0, -3])
def test_un_nombre_de_candidates_absurde_ne_casse_rien(nb):
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur, nb=nb),
        quoi=f"generer(nb={nb})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert candidates == [], f"nb={nb} ne peut pas produire de candidate"
        assert not moteur.appels, f"nb={nb} ne justifie aucun appel au moteur"


@pytest.mark.parametrize("tolerance", [0.0, -0.5, 10.0])
def test_une_tolerance_absurde_ne_fait_pas_boucler(tolerance):
    module = _module()
    moteur = MoteurFactice(30_000.0)
    candidates, erreur = robuste(
        lambda: _generer(module, moteur, tolerance=tolerance, appels_max=12),
        quoi=f"generer(tolerance={tolerance})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    assert len(moteur.appels) <= 12, "le plafond d'appels protège de toute tolérance absurde"
    if erreur is None:
        _verifier_candidates(candidates, cible_km=60.0, quoi=f"tolerance={tolerance}")


def test_le_profil_demande_est_transmis_au_moteur():
    module = _module()
    moteur = MoteurFactice(lambda rayon: rayon * RATIO_MESURE)
    _generer(module, moteur, nb=1, profil="gravel")
    assert moteur.appels, "aucun appel"
    assert moteur.appels[0].get("profil") == "gravel", (
        f"le profil doit descendre jusqu'au moteur, appel : {moteur.appels[0]}"
    )

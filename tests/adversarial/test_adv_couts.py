"""L2.4 — coûts d'un tracé, mis à l'épreuve.

Cible : contrat du sprint 2 §4 et §8. Rien à brancher ici : `evaluer` est une
fonction pure sur un `Trace`, donc les tests sont directs et exigeants.

Ce qui est traqué :

* le **bruit GPS** : sans le garde-fou des 15 m, une ligne droite relevée au
  mètre compte des dizaines de virages imaginaires ;
* le **méridien 0** : l'écart de cap doit se calculer modulo 360, sinon un
  tracé qui passe de 359° à 1° compte un demi-tour ;
* les **segments hostiles** (indices hors bornes, tags sans `highway`,
  longueurs négatives) : une erreur utilisateur ou un résultat cohérent,
  jamais un `IndexError` ;
* la **formule de score**, que le contrat fixe au poids près.
"""

from __future__ import annotations

import math
from typing import Any

import fabriques
import outils
import pytest
from outils import robuste

from ourouler.boucle.trace import Segment
from ourouler.erreurs import ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L2.4 absent (ourouler.boucle.couts)"

CHAMPS = {
    "km_trafic",
    "km_calme",
    "km_non_revetu",
    "virages_gauche",
    "virages_gauche_trafic",
    "virages_droite",
    "sens",
    "score",
}
SENS_ATTENDUS = {"horaire", "antihoraire", "indetermine"}

#: Poids du contrat §4, en km équivalents.
POIDS_TRAFIC = 3.0
POIDS_NON_REVETU = 4.0
POIDS_VIRAGE_GAUCHE = 0.3
POIDS_VIRAGE_GAUCHE_TRAFIC = 1.0
POIDS_MAUVAIS_SENS = 2.0


def _module():
    return pytest.importorskip("ourouler.boucle.couts", reason=MOTIF_ABSENT)


def _verifier_couts(couts: Any, quoi: str) -> None:
    outils.exiger_champs(type(couts), CHAMPS)
    for nom in ("km_trafic", "km_calme", "km_non_revetu", "score"):
        valeur = getattr(couts, nom)
        assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
            f"{quoi} : {nom} doit être un nombre, reçu {valeur!r}"
        )
        assert math.isfinite(valeur), f"{quoi} : {nom} non fini ({valeur!r})"
        assert valeur >= 0, f"{quoi} : {nom} négatif ({valeur})"
    for nom in ("virages_gauche", "virages_gauche_trafic", "virages_droite"):
        valeur = getattr(couts, nom)
        assert isinstance(valeur, int) and not isinstance(valeur, bool), (
            f"{quoi} : {nom} doit être un entier, reçu {valeur!r}"
        )
        assert valeur >= 0, f"{quoi} : {nom} négatif ({valeur})"
    assert couts.sens in SENS_ATTENDUS, f"{quoi} : sens = {couts.sens!r}"
    assert couts.virages_gauche_trafic <= couts.virages_gauche, (
        f"{quoi} : {couts.virages_gauche_trafic} virages à gauche à trafic pour "
        f"{couts.virages_gauche} virages à gauche"
    )


def _evaluer(module, trace, **kwargs):
    couts = module.evaluer(trace, **kwargs)
    _verifier_couts(couts, f"evaluer({kwargs})")
    return couts


def _droite(tags: list[dict[str, str]], *, pas_m: float = 1000.0):
    """Une ligne droite d'un tronçon par jeu de tags — aucun virage possible."""
    coords = fabriques.ligne(len(tags) + 1, pas_m=pas_m, cap_deg=0.0)
    return fabriques.trace_fictive(coords, tags=tags)


# --- classification des tronçons ---------------------------------------------


@pytest.mark.parametrize(
    "highway", ["primary", "primary_link", "secondary", "secondary_link", "trunk"]
)
def test_les_routes_a_trafic_sont_comptees_comme_telles(highway):
    module = _module()
    couts = _evaluer(module, _droite([{"highway": highway}]))
    assert couts.km_trafic == pytest.approx(1.0, rel=0.02), (
        f"highway={highway} : 1 km de trafic attendu, reçu {couts.km_trafic}"
    )
    assert couts.km_calme == pytest.approx(0.0, abs=0.01), f"highway={highway} compté comme calme"


@pytest.mark.parametrize(
    "highway",
    ["tertiary", "unclassified", "residential", "cycleway", "track", "service", "living_street"],
)
def test_les_routes_calmes_ne_comptent_pas_dans_le_trafic(highway):
    module = _module()
    couts = _evaluer(module, _droite([{"highway": highway}]))
    assert couts.km_calme == pytest.approx(1.0, rel=0.02), (
        f"highway={highway} : 1 km calme attendu, reçu {couts.km_calme}"
    )
    assert couts.km_trafic == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize(
    "surface", ["gravel", "unpaved", "dirt", "ground", "grass", "compacted", "fine_gravel", "sand"]
)
def test_les_surfaces_non_revetues_sont_comptees(surface):
    module = _module()
    couts = _evaluer(module, _droite([{"highway": "tertiary", "surface": surface}]))
    assert couts.km_non_revetu == pytest.approx(1.0, rel=0.02), (
        f"surface={surface} : 1 km non revêtu attendu, reçu {couts.km_non_revetu}"
    )


def test_un_chemin_sans_surface_est_repute_non_revetu():
    """Contrat §4 : « ou track sans surface »."""
    module = _module()
    couts = _evaluer(module, _droite([{"highway": "track"}]))
    assert couts.km_non_revetu == pytest.approx(1.0, rel=0.02), (
        f"un track sans tag `surface` compte pour du non revêtu, reçu {couts.km_non_revetu}"
    )


def test_un_track_asphalte_n_est_pas_non_revetu():
    module = _module()
    couts = _evaluer(module, _droite([{"highway": "track", "surface": "asphalt"}]))
    assert couts.km_non_revetu == pytest.approx(0.0, abs=0.01), (
        "un `track` explicitement asphalté n'est pas un chemin de terre"
    )


def test_un_troncon_sans_highway_ne_compte_ni_en_trafic_ni_en_calme():
    module = _module()
    couts = _evaluer(module, _droite([{"surface": "asphalt"}, {}]))
    assert couts.km_trafic == pytest.approx(0.0, abs=0.01)
    assert couts.km_calme == pytest.approx(0.0, abs=0.01), (
        "sans `highway`, on ne sait pas si le tronçon est calme : ne pas l'inventer"
    )


def test_un_highway_inconnu_n_est_pas_range_d_office():
    module = _module()
    couts = _evaluer(module, _droite([{"highway": "motorway"}, {"highway": "footway"}]))
    assert couts.km_trafic + couts.km_calme <= 2.05, "chaque tronçon ne compte qu'une fois"


# --- score --------------------------------------------------------------------


def _trace_melangee():
    return _droite(
        [
            {"highway": "primary"},
            {"highway": "residential"},
            {"highway": "track", "surface": "gravel"},
            {"highway": "tertiary"},
        ]
    )


def _trace_avec_virage():
    coords = fabriques.coude(cap_avant=90.0, cap_apres=0.0, pas_m=25.0, n=8)
    return fabriques.trace_fictive(coords, tags=[{"highway": "secondary"}] * (len(coords) - 1))


def _trace_bouclee():
    coords = fabriques.cercle(24, rayon_m=1200.0, sens="horaire")
    return fabriques.trace_fictive(coords, tags=[{"highway": "tertiary"}] * (len(coords) - 1))


@pytest.mark.parametrize("fabrique", [_trace_melangee, _trace_avec_virage, _trace_bouclee])
@pytest.mark.parametrize("sens_prefere", ["horaire", "antihoraire"])
def test_le_score_suit_la_formule_du_contrat(fabrique, sens_prefere):
    module = _module()
    couts = _evaluer(module, fabrique(), sens_prefere=sens_prefere)
    attendu = (
        couts.km_trafic * POIDS_TRAFIC
        + couts.km_non_revetu * POIDS_NON_REVETU
        + couts.virages_gauche * POIDS_VIRAGE_GAUCHE
        + couts.virages_gauche_trafic * POIDS_VIRAGE_GAUCHE_TRAFIC
        + (0.0 if couts.sens == sens_prefere else POIDS_MAUVAIS_SENS)
    )
    assert couts.score == pytest.approx(attendu, rel=1e-6), (
        f"score = {couts.score}, formule du contrat = {attendu} "
        f"(trafic {couts.km_trafic:.2f} km, non revêtu {couts.km_non_revetu:.2f} km, "
        f"virages G {couts.virages_gauche} dont {couts.virages_gauche_trafic} à trafic, "
        f"sens {couts.sens} / préféré {sens_prefere})"
    )


def test_le_mauvais_sens_coute_exactement_deux_kilometres():
    module = _module()
    trace = fabriques.trace_fictive(
        fabriques.cercle(24, rayon_m=1200.0, sens="horaire"),
        tags=[{"highway": "tertiary"}] * 24,
    )
    bon = _evaluer(module, trace, sens_prefere="horaire")
    mauvais = _evaluer(module, trace, sens_prefere="antihoraire")
    assert bon.sens == "horaire", f"le cercle fabriqué est horaire, `evaluer` dit {bon.sens!r}"
    assert mauvais.score - bon.score == pytest.approx(POIDS_MAUVAIS_SENS, rel=1e-6), (
        f"la pénalité de sens doit valoir {POIDS_MAUVAIS_SENS} km équivalents, "
        f"mesurée à {mauvais.score - bon.score}"
    )


def test_le_sens_antihoraire_est_reconnu():
    module = _module()
    trace = fabriques.trace_fictive(fabriques.cercle(24, rayon_m=1200.0, sens="antihoraire"))
    assert _evaluer(module, trace).sens == "antihoraire"


def test_une_trace_ouverte_a_un_sens_indetermine():
    module = _module()
    assert _evaluer(module, _droite([{"highway": "tertiary"}] * 3)).sens == "indetermine"


# --- virages ------------------------------------------------------------------


def test_le_bruit_gps_ne_fabrique_pas_de_virages():
    """Contrat §4 : cap calculé sur des points espacés d'au moins 15 m."""
    module = _module()
    coords = []
    lat, lon = fabriques.LAT0, fabriques.LON0
    for i in range(120):
        lat_i, _ = fabriques.deplacer(lat, lon, 0.0, 2.0 * i)
        decalage = 1.5 if i % 2 else -1.5
        _, lon_i = fabriques.deplacer(lat_i, lon, 90.0, decalage)
        coords.append((lat_i, lon_i, 10.0))
    trace = fabriques.trace_fictive(coords)
    couts = _evaluer(module, trace)
    assert couts.virages_gauche + couts.virages_droite <= 2, (
        f"{couts.virages_gauche} virages à gauche et {couts.virages_droite} à droite sur une "
        "ligne droite bruitée au mètre : le cap se calcule sur des points espacés d'au moins 15 m"
    )


def test_un_virage_a_gauche_net_est_compte_a_gauche():
    module = _module()
    trace = fabriques.trace_fictive(
        fabriques.coude(cap_avant=90.0, cap_apres=0.0, pas_m=25.0, n=8)
    )
    couts = _evaluer(module, trace)
    assert couts.virages_gauche >= 1, "un virage de 90° vers le nord depuis l'est est à gauche"
    assert couts.virages_droite == 0, f"{couts.virages_droite} virage(s) à droite inventé(s)"


def test_un_virage_a_droite_net_est_compte_a_droite():
    module = _module()
    trace = fabriques.trace_fictive(
        fabriques.coude(cap_avant=0.0, cap_apres=90.0, pas_m=25.0, n=8)
    )
    couts = _evaluer(module, trace)
    assert couts.virages_droite >= 1, "tourner à l'est en venant du nord est un virage à droite"
    assert couts.virages_gauche == 0, f"{couts.virages_gauche} virage(s) à gauche inventé(s)"


def test_le_passage_du_meridien_zero_n_invente_pas_de_virage():
    """Contrat §8 : « cap au passage du méridien 0 ».

    Une ligne quasi plein nord qui traverse la longitude 0 : le cap oscille de
    part et d'autre de 0° (donc entre 359,x° et 0,x°). Un écart de cap calculé
    sans modulo 360 y voit un virage à gauche de −359° à chaque point.
    """
    module = _module()
    coords = []
    lat, lon = fabriques.LAT0, -0.00005
    for i in range(60):
        coords.append((lat, lon, 10.0))
        # 20 m vers le nord : assez pour que le cap soit calculable (≥ 15 m) et
        # que trois points tiennent dans la fenêtre de 60 m d'un virage.
        lat, _ = fabriques.deplacer(lat, lon, 0.0, 20.0)
        _, lon = fabriques.deplacer(lat, lon, 90.0, 0.25 + (0.3 if i % 2 else -0.3))
    trace = fabriques.trace_fictive(coords)
    assert coords[0][1] < 0 < coords[-1][1], "la ligne de test doit bien traverser le méridien 0"
    couts = _evaluer(module, trace)
    assert couts.virages_gauche == 0 and couts.virages_droite == 0, (
        f"{couts.virages_gauche} à gauche, {couts.virages_droite} à droite sur une ligne "
        "quasi droite plein nord qui traverse le méridien 0 : l'écart de cap se calcule "
        "modulo 360, et le bruit sous 15 m ne compte pas"
    )


def test_un_demi_tour_ne_compte_pas_des_deux_cotes():
    module = _module()
    trace = fabriques.trace_fictive(
        fabriques.coude(cap_avant=0.0, cap_apres=185.0, pas_m=25.0, n=8)
    )
    couts = _evaluer(module, trace)
    assert couts.virages_droite == 0, "un demi-tour à −175° ne se compte pas aussi à droite"
    assert couts.virages_gauche <= 2, (
        f"{couts.virages_gauche} virages à gauche pour un seul demi-tour"
    )


def test_un_virage_a_gauche_sur_une_route_a_trafic_est_signale():
    module = _module()
    coords = fabriques.coude(cap_avant=90.0, cap_apres=0.0, pas_m=25.0, n=8)
    tags = [{"highway": "secondary"}] * (len(coords) - 1)
    couts = _evaluer(module, fabriques.trace_fictive(coords, tags=tags))
    if couts.virages_gauche:
        assert couts.virages_gauche_trafic >= 1, (
            "le virage se fait entre deux tronçons `secondary` : il doit compter en virage "
            "à gauche à trafic"
        )


# --- traces dégénérées --------------------------------------------------------


def test_une_trace_sans_segments_donne_des_couts_partiels():
    """Contrat §4 : un GPX importé n'a pas de tronçon décrit."""
    module = _module()
    trace = fabriques.trace_fictive(fabriques.ligne(20, pas_m=200.0))
    assert trace.segments == []
    couts = _evaluer(module, trace)
    assert couts.km_trafic == 0 and couts.km_calme == 0 and couts.km_non_revetu == 0, (
        "sans segments, aucun kilomètre ne peut être classé"
    )
    assert trace.meta.get("couts_partiels") is True, (
        f"`meta['couts_partiels']` doit valoir True, meta = {trace.meta!r}"
    )


@pytest.mark.parametrize("nb_points", [0, 1, 2])
def test_une_trace_minuscule_ne_casse_rien(nb_points):
    module = _module()
    trace = fabriques.trace_fictive(fabriques.ligne(nb_points) if nb_points else [])
    couts, erreur = robuste(
        lambda: module.evaluer(trace),
        quoi=f"evaluer(trace de {nb_points} point(s))",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier_couts(couts, f"trace de {nb_points} point(s)")
        assert couts.virages_gauche == 0 and couts.virages_droite == 0, (
            "moins de trois points ne font pas un virage"
        )
        assert couts.sens == "indetermine"


def test_des_points_confondus_ne_donnent_pas_de_nan():
    module = _module()
    coords = [(fabriques.LAT0, fabriques.LON0, 10.0)] * 8
    couts, erreur = robuste(
        lambda: module.evaluer(fabriques.trace_fictive(coords)),
        quoi="evaluer(points confondus)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier_couts(couts, "points confondus")


@pytest.mark.parametrize(
    "attributs, quoi",
    [
        ({"debut_idx": 0, "fin_idx": 99, "longueur_m": 100.0}, "fin hors bornes"),
        ({"debut_idx": 3, "fin_idx": 1, "longueur_m": 100.0}, "segment à l'envers"),
        ({"debut_idx": -2, "fin_idx": 1, "longueur_m": 100.0}, "indice négatif"),
        ({"debut_idx": 0, "fin_idx": 1, "longueur_m": -500.0}, "longueur négative"),
        ({"debut_idx": 0, "fin_idx": 1, "longueur_m": float("nan")}, "longueur NaN"),
    ],
)
def test_un_segment_incoherent_ne_provoque_pas_d_index_error(attributs, quoi):
    module = _module()
    trace = fabriques.trace_fictive(fabriques.ligne(5, pas_m=200.0))
    trace.segments = [Segment(tags={"highway": "primary"}, **attributs)]
    couts, erreur = robuste(
        lambda: module.evaluer(trace),
        quoi=f"evaluer({quoi})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier_couts(couts, quoi)


def test_des_tags_qui_ne_sont_pas_des_chaines_ne_cassent_rien():
    module = _module()
    trace = fabriques.trace_fictive(fabriques.ligne(4, pas_m=200.0))
    trace.segments = [
        Segment(debut_idx=0, fin_idx=1, longueur_m=200.0, tags={"highway": None}),
        Segment(debut_idx=1, fin_idx=2, longueur_m=200.0, tags={"surface": 3}),
    ]
    couts, erreur = robuste(
        lambda: module.evaluer(trace),
        quoi="evaluer(tags non textuels)",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        _verifier_couts(couts, "tags non textuels")


def test_evaluer_ne_detruit_pas_la_trace():
    module = _module()
    trace = _droite([{"highway": "primary"}, {"highway": "tertiary"}])
    avant = (len(trace.points), len(trace.segments), trace.distance_m)
    _evaluer(module, trace)
    assert (len(trace.points), len(trace.segments), trace.distance_m) == avant, (
        "`evaluer` lit la trace, elle ne la réécrit pas (sauf `meta['couts_partiels']`)"
    )

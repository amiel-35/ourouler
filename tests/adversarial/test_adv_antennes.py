"""L3.1 — antennes (cul-de-sac), mises à l'épreuve.

Cible : contrat du sprint 3 §1 et §4. `detecter` et `elaguer` sont deux
fonctions pures sur un `Trace` : rien à brancher, donc rien à excuser.

Ce qui est traqué :

* la **fausse détection** : une boucle propre ne contient aucune antenne. Un
  détecteur qui compare des points « proches » sans exiger que le retour soit
  un retour trouve des antennes partout sur un cercle — et `elaguer`
  découperait alors la boucle du mainteneur ;
* la **borne de la fenêtre** : le contrat écrit « sur une longueur totale ≤
  `fenetre_m` ». Une antenne mesurée exactement à la fenêtre est donc dedans,
  et une antenne de 2 km ne doit pas être élaguée sous prétexte qu'elle
  revient sur ses pas (c'est un aller-retour choisi, pas un défaut) ;
* l'**élagage sans antenne** : `elaguer(trace, [])` doit rendre une trace
  équivalente, pas une trace vidée, tronquée ou dont les distances repartent
  de travers ;
* la **réindexation** : le contrat exige « distances recalculées, segments
  réindexés ». Un segment qui garde les indices d'avant pointe, après coupe,
  sur des points qui n'existent plus — `IndexError` chez `couts.evaluer` ;
* l'**immutabilité de l'entrée** : `elaguer` rend un *nouveau* `Trace`. Un
  élagage en place casserait la comparaison avant/après que le contrat §1
  demande précisément de faire sur la boucle NE de 60 km.
"""

from __future__ import annotations

import math
from typing import Any

import fabriques
import fabriques3
import pytest
from outils import robuste

from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import Segment, Trace
from ourouler.noyau.trace import distance_m as distance_entre

MOTIF_ABSENT = "module attendu par le contrat L3.1 absent (ourouler.boucle.antennes)"

CHAMPS_ANTENNE = {"debut_idx", "fin_idx", "longueur_m"}

#: Défauts du contrat §1, réécrits ici : un test qui lit les défauts du module
#: testé ne teste plus rien.
FENETRE_DEFAUT_M = 600.0
TOLERANCE_DEFAUT_M = 20.0

ERREURS = (ErreurUtilisateur, ValueError)


def _module():
    return pytest.importorskip("ourouler.boucle.antennes", reason=MOTIF_ABSENT)


# --- vérificateurs ----------------------------------------------------------


def _verifier_antennes(antennes: Any, trace: Trace, quoi: str) -> list[Any]:
    assert isinstance(antennes, list), f"{quoi} : liste attendue, reçu {type(antennes).__name__}"
    for i, a in enumerate(antennes):
        manquants = CHAMPS_ANTENNE - {n for n in dir(a) if not n.startswith("_")}
        assert not manquants, f"{quoi}[{i}] : champs du contrat absents {sorted(manquants)}"
        for nom in ("debut_idx", "fin_idx"):
            valeur = getattr(a, nom)
            assert isinstance(valeur, int) and not isinstance(valeur, bool), (
                f"{quoi}[{i}].{nom} : entier attendu, reçu {valeur!r}"
            )
            assert 0 <= valeur < len(trace.points), (
                f"{quoi}[{i}].{nom} = {valeur} hors des {len(trace.points)} points de la trace"
            )
        assert a.debut_idx < a.fin_idx, f"{quoi}[{i}] : antenne vide ou à l'envers ({a})"
        assert isinstance(a.longueur_m, (int, float)) and not isinstance(a.longueur_m, bool), (
            f"{quoi}[{i}].longueur_m : nombre attendu, reçu {a.longueur_m!r}"
        )
        assert math.isfinite(a.longueur_m) and a.longueur_m >= 0, (
            f"{quoi}[{i}].longueur_m = {a.longueur_m}"
        )
    rangees = sorted(antennes, key=lambda a: a.debut_idx)
    for precedente, suivante in zip(rangees, rangees[1:], strict=False):
        assert precedente.fin_idx <= suivante.debut_idx, (
            f"{quoi} : antennes qui se chevauchent ({precedente} et {suivante}) — "
            "`elaguer` ne saurait pas quoi retirer"
        )
    return list(antennes)


def _verifier_elaguee(avant: Trace, apres: Any, quoi: str) -> None:
    assert isinstance(apres, Trace), f"{quoi} : Trace attendu, reçu {type(apres).__name__}"
    assert apres is not avant, f"{quoi} : le contrat demande un *nouveau* Trace"
    fabriques.verifier_trace(apres, quoi=quoi, distance_max_km=100.0)
    assert len(apres.points) >= 2, f"{quoi} : {len(apres.points)} point(s) après élagage"
    assert apres.points[0].dist_m == pytest.approx(0.0, abs=1e-6), (
        f"{quoi} : la distance cumulée ne repart pas de 0 ({apres.points[0].dist_m}) — "
        "le contrat demande des distances recalculées"
    )
    cumul = 0.0
    for precedent, point in zip(apres.points, apres.points[1:], strict=False):
        cumul += distance_entre(precedent, point)
        assert point.dist_m == pytest.approx(cumul, abs=1.0), (
            f"{quoi} : dist_m = {point.dist_m:.1f} là où la géométrie donne {cumul:.1f}"
        )
    if apres.distance_m is not None:
        assert apres.distance_m == pytest.approx(apres.points[-1].dist_m, abs=1.0), (
            f"{quoi} : distance_m = {apres.distance_m:.1f} pour un dernier point à "
            f"{apres.points[-1].dist_m:.1f}"
        )
    for i, s in enumerate(apres.segments):
        assert 0 <= s.debut_idx <= s.fin_idx < len(apres.points), (
            f"{quoi} : segments[{i}] = ({s.debut_idx}, {s.fin_idx}) pour "
            f"{len(apres.points)} points — segments non réindexés"
        )


# --- aucune fausse détection -------------------------------------------------


def test_une_boucle_propre_ne_contient_aucune_antenne():
    """Contrat §4 : « boucle sans antenne (aucune fausse détection) »."""
    module = _module()
    coords = fabriques.cercle(n=48, rayon_m=2000.0)
    trace = fabriques.trace_fictive(coords)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(cercle)")
    assert antennes == [], (
        f"{len(antennes)} antenne(s) trouvée(s) sur un cercle de 2 km de rayon : "
        "le détecteur confond « points proches » et « géométrie reparcourue »"
    )


def test_une_ligne_droite_ne_contient_aucune_antenne():
    """Un aller simple n'est pas un aller-retour : rien à élaguer."""
    module = _module()
    trace = fabriques.trace_fictive(fabriques.ligne(40, pas_m=100.0))
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(ligne)")
    assert antennes == [], f"antenne inventée sur une ligne droite : {antennes}"


# --- détection ---------------------------------------------------------------


def test_un_aller_retour_exact_est_detecte():
    """Contrat §4 : « aller-retour exact »."""
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(antenne exacte)")
    assert antennes, "aller-retour de 400 m greffé sur une boucle : aucune antenne détectée"
    assert len(antennes) == 1, f"une seule antenne greffée, {len(antennes)} détectées : {antennes}"
    a = antennes[0]
    assert a.debut_idx <= debut + 1 and a.fin_idx >= fin - 1, (
        f"antenne située en ({a.debut_idx}, {a.fin_idx}), greffée en ({debut}, {fin})"
    )
    attendue = fabriques3.longueur_entre(trace, debut, fin)
    assert a.longueur_m == pytest.approx(attendue, rel=0.25), (
        f"longueur_m = {a.longueur_m:.0f} m pour un aller-retour de {attendue:.0f} m "
        "(le contrat compte l'aller **et** le retour)"
    )


def test_un_aller_retour_bruite_de_dix_metres_reste_detecte():
    """Contrat §4 : « quasi-exact (bruit 10 m) », sous la tolérance de 20 m."""
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4, bruit_m=10.0)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(bruit 10 m)")
    assert antennes, (
        "un retour décalé de 10 m (tolérance 20 m) n'est plus reconnu : le détecteur "
        "exige les mêmes nœuds, pas la même géométrie"
    )


def test_un_retour_au_dela_de_la_tolerance_n_est_pas_une_antenne():
    """Le pendant du test précédent : au-delà de la tolérance, deux routes distinctes."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4, bruit_m=120.0)
    antennes = _verifier_antennes(
        module.detecter(trace, tolerance_m=TOLERANCE_DEFAUT_M), trace, "detecter(bruit 120 m)"
    )
    assert antennes == [], (
        f"retour à 120 m de l'aller pris pour une antenne avec une tolérance de "
        f"{TOLERANCE_DEFAUT_M:.0f} m : {antennes}"
    )


def test_une_antenne_au_depart_est_detectee():
    """Contrat §4 : « antenne au départ » — le cas où les indices commencent à 0."""
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4, position=0)
    assert debut == 0, "le montage doit greffer l'antenne sur le tout premier point"
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(antenne au départ)")
    assert antennes, "antenne greffée au point 0 : non détectée (borne de boucle oubliée ?)"
    premiere = min(a.debut_idx for a in antennes)
    assert premiere == 0, f"antenne au départ signalée à partir du point {premiere}"
    assert max(a.fin_idx for a in antennes) >= fin - 1, (
        f"antenne au départ tronquée : elle devrait courir jusqu'au point {fin}"
    )


def test_une_antenne_plus_longue_que_la_fenetre_est_laissee_en_place():
    """Contrat §1 : l'antenne se définit « sur une longueur totale ≤ fenetre_m »."""
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=1200.0, n_aller=12)
    longueur = fabriques3.longueur_entre(trace, debut, fin)
    assert longueur > FENETRE_DEFAUT_M, "le montage doit dépasser la fenêtre par défaut"
    antennes = _verifier_antennes(
        module.detecter(trace, fenetre_m=FENETRE_DEFAUT_M), trace, "detecter(antenne de 2,4 km)"
    )
    trop_longues = [a for a in antennes if a.longueur_m > FENETRE_DEFAUT_M * 1.01]
    assert not trop_longues, (
        f"antenne(s) de plus de {FENETRE_DEFAUT_M:.0f} m rendues : {trop_longues} — "
        "un aller-retour de 2,4 km est un choix du cycliste, pas un défaut de tracé"
    )


def test_une_antenne_exactement_a_la_fenetre_est_dedans():
    """Contrat §1 : « ≤ fenetre_m ». La borne est inclusive, sinon elle n'est pas dite.

    La longueur est mesurée avec les distances cumulées de la trace elle-même :
    c'est exactement ce que le module additionnera.
    """
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=250.0, n_aller=5)
    longueur = fabriques3.longueur_entre(trace, debut, fin)
    en_dessous = _verifier_antennes(
        module.detecter(trace, fenetre_m=longueur / 2), trace, "detecter(fenêtre = moitié)"
    )
    assert en_dessous == [], (
        f"antenne de {longueur:.0f} m rendue avec une fenêtre de {longueur / 2:.0f} m : "
        f"{en_dessous}"
    )
    a_la_borne = _verifier_antennes(
        module.detecter(trace, fenetre_m=longueur), trace, "detecter(fenêtre = longueur)"
    )
    assert a_la_borne, (
        f"antenne de {longueur:.3f} m écartée par une fenêtre de {longueur:.3f} m : "
        "le contrat écrit « ≤ fenetre_m », la comparaison est donc large"
    )


def test_deux_antennes_distinctes_sont_rendues_separement():
    """Deux culs-de-sac sur la même boucle : deux entrées, pas une fusion."""
    module = _module()
    coords = fabriques.cercle(n=32, rayon_m=2000.0)
    coords, _, _ = fabriques3.greffer_antenne(coords, position=20, aller_m=180.0, n_aller=3)
    coords, _, _ = fabriques3.greffer_antenne(coords, position=5, aller_m=180.0, n_aller=3)
    trace = fabriques.trace_fictive(coords)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(deux antennes)")
    assert len(antennes) == 2, f"deux antennes greffées, {len(antennes)} rendues : {antennes}"


# --- entrées dégénérées ------------------------------------------------------


@pytest.mark.parametrize("nb", [0, 1, 2])
def test_detecter_sur_une_trace_minuscule(nb):
    """Le contrat ne dit rien d'une trace de 0 à 2 points : aucun `IndexError` n'est permis."""
    module = _module()
    coords = fabriques.ligne(nb, pas_m=100.0) if nb else []
    trace = fabriques.trace_fictive(coords) if nb else Trace("vide", [], [], 0.0, None, None, {})
    resultat, _ = robuste(
        lambda: module.detecter(trace), quoi=f"detecter(trace de {nb} point(s))", erreurs_acceptees=ERREURS
    )
    if resultat is not None:
        _verifier_antennes(resultat, trace, f"detecter({nb} points)")


@pytest.mark.parametrize(("fenetre", "tolerance"), [(0.0, 20.0), (-100.0, 20.0), (600.0, 0.0), (600.0, -5.0)])
def test_detecter_avec_des_reglages_absurdes(fenetre, tolerance):
    """Fenêtre ou tolérance nulle ou négative : erreur utilisateur ou résultat cohérent."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne()
    with fabriques.limite_temps(10.0, f"detecter(fenetre_m={fenetre}, tolerance_m={tolerance})"):
        resultat, _ = robuste(
            lambda: module.detecter(trace, fenetre_m=fenetre, tolerance_m=tolerance),
            quoi=f"detecter(fenetre_m={fenetre}, tolerance_m={tolerance})",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _verifier_antennes(resultat, trace, "detecter(réglages absurdes)")


def test_detecter_sur_une_trace_a_points_confondus():
    """Un moteur qui répète deux fois le même point ne doit pas engendrer une antenne de 0 m."""
    module = _module()
    coords = fabriques.ligne(20, pas_m=100.0)
    coords = coords[:10] + [coords[10]] * 4 + coords[10:]
    trace = fabriques.trace_fictive(coords)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(points confondus)")
    vides = [a for a in antennes if a.longueur_m < 1.0]
    assert not vides, f"antennes de longueur nulle rendues sur des points confondus : {vides}"


# --- élagage -----------------------------------------------------------------


def test_elaguer_sans_antenne_rend_une_trace_equivalente():
    """Angle obligatoire : `elaguer(trace, [])` ne doit rien changer d'observable."""
    module = _module()
    coords = fabriques.cercle(n=32, rayon_m=1800.0)
    trace = fabriques.trace_fictive(coords, tags=[{"highway": "tertiary"}] * (len(coords) - 1))
    avant = fabriques3.copie_lisible(trace)
    apres = module.elaguer(trace, [])
    _verifier_elaguee(trace, apres, "elaguer(trace, [])")
    assert len(apres.points) == len(trace.points), (
        f"{len(trace.points)} points avant, {len(apres.points)} après un élagage sans antenne"
    )
    assert fabriques3.copie_lisible(apres) == avant, (
        "elaguer(trace, []) modifie la géométrie ou les distances cumulées"
    )
    assert len(apres.segments) == len(trace.segments), (
        f"{len(trace.segments)} segments avant, {len(apres.segments)} après"
    )
    assert apres.distance_m == pytest.approx(trace.distance_m, abs=1.0)
    assert apres.bornee() == trace.bornee(), "une boucle fermée le reste après un élagage vide"


def test_elaguer_retire_l_antenne_et_preserve_la_fermeture():
    """Contrat §4 : « élagage qui préserve la fermeture et les segments »."""
    module = _module()
    trace, debut, fin = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4)
    assert trace.bornee(), "le montage doit partir d'une boucle fermée"
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter")
    assert antennes, "rien à élaguer : le détecteur a déjà échoué"
    apres = module.elaguer(trace, antennes)
    _verifier_elaguee(trace, apres, "elaguer(boucle avec antenne)")
    assert apres.bornee(), "la boucle n'est plus fermée après élagage"
    retiree = fabriques3.longueur_entre(trace, debut, fin)
    assert apres.points[-1].dist_m == pytest.approx(
        trace.points[-1].dist_m - retiree, rel=0.05
    ), (
        f"{trace.points[-1].dist_m - apres.points[-1].dist_m:.0f} m retirés pour une antenne "
        f"de {retiree:.0f} m"
    )
    assert len(apres.points) < len(trace.points), "aucun point retiré alors qu'une antenne l'était"


def test_elaguer_ne_touche_pas_la_trace_d_origine():
    """Le contrat demande un « nouveau Trace » : la comparaison avant/après en dépend."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4)
    avant = fabriques3.copie_lisible(trace)
    segments_avant = [(s.debut_idx, s.fin_idx, s.longueur_m) for s in trace.segments]
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter")
    module.elaguer(trace, antennes)
    assert fabriques3.copie_lisible(trace) == avant, "elaguer a modifié les points de l'entrée"
    assert [(s.debut_idx, s.fin_idx, s.longueur_m) for s in trace.segments] == segments_avant, (
        "elaguer a modifié les segments de l'entrée"
    )


def test_elaguer_puis_detecter_ne_trouve_plus_rien():
    """L'élagage converge : une trace élaguée n'a plus d'antenne à élaguer."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne(aller_m=200.0, n_aller=4)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter")
    apres = module.elaguer(trace, antennes)
    restantes = _verifier_antennes(module.detecter(apres), apres, "detecter(après élagage)")
    assert restantes == [], f"antennes encore présentes après élagage : {restantes}"


def test_elaguer_conserve_les_tags_des_troncons_gardes():
    """Les segments survivants gardent leurs tags : `couts.evaluer` tourne derrière."""
    module = _module()
    coords = fabriques.cercle(n=24, rayon_m=1500.0)
    coords, debut, fin = fabriques3.greffer_antenne(coords, position=6, aller_m=200.0, n_aller=4)
    tags = [
        {"highway": "track"} if debut <= i < fin else {"highway": "tertiary"}
        for i in range(len(coords) - 1)
    ]
    trace = fabriques.trace_fictive(coords, tags=tags)
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter")
    assert antennes, "rien détecté : le reste du test n'aurait pas de sens"
    apres = module.elaguer(trace, antennes)
    _verifier_elaguee(trace, apres, "elaguer(tags distincts)")
    restants = [s.tags.get("highway") for s in apres.segments]
    assert "tertiary" in restants, f"les tronçons gardés ont perdu leurs tags : {restants}"
    assert restants.count("track") == 0, (
        f"les tags de l'antenne survivent à son élagage : {restants}"
    )


@pytest.mark.parametrize(
    "fabrique",
    [
        pytest.param(lambda n: (0, n + 50), id="fin hors bornes"),
        pytest.param(lambda n: (-3, 5), id="début négatif"),
        pytest.param(lambda n: (10, 4), id="à l'envers"),
        pytest.param(lambda n: (7, 7), id="vide"),
    ],
)
def test_elaguer_avec_des_antennes_fabriquees_hors_bornes(fabrique):
    """Une antenne venue d'ailleurs (JSON relu, appelant bricolé) ne doit pas faire d'`IndexError`."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne()
    debut, fin = fabrique(len(trace.points))
    antenne = module.Antenne(debut_idx=debut, fin_idx=fin, longueur_m=400.0)
    resultat, _ = robuste(
        lambda: module.elaguer(trace, [antenne]),
        quoi=f"elaguer(Antenne({debut}, {fin}))",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_elaguee(trace, resultat, f"elaguer(Antenne({debut}, {fin}))")


def test_elaguer_toute_la_trace_ne_rend_pas_une_trace_incoherente():
    """Cas limite : l'antenne couvre tout. Refus ou trace cohérente, jamais un `Trace` cassé."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne()
    antenne = module.Antenne(debut_idx=0, fin_idx=len(trace.points) - 1, longueur_m=trace.distance_m)
    resultat, _ = robuste(
        lambda: module.elaguer(trace, [antenne]),
        quoi="elaguer(antenne = toute la trace)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        assert isinstance(resultat, Trace), "Trace attendu"
        fabriques.verifier_trace(resultat, quoi="elaguer(tout)", distance_max_km=100.0)


def test_elaguer_une_trace_sans_segment():
    """Un GPX importé n'a pas de segment : la réindexation ne doit pas le supposer."""
    module = _module()
    coords = fabriques.cercle(n=24, rayon_m=1500.0)
    coords, _, _ = fabriques3.greffer_antenne(coords, position=6, aller_m=200.0, n_aller=4)
    trace = fabriques.trace_fictive(coords)  # aucun segment
    assert trace.segments == []
    antennes = _verifier_antennes(module.detecter(trace), trace, "detecter(sans segment)")
    apres = module.elaguer(trace, antennes)
    _verifier_elaguee(trace, apres, "elaguer(sans segment)")
    assert apres.segments == [], f"segments inventés à partir de rien : {apres.segments}"


def test_elaguer_avec_des_segments_qui_debordent():
    """Segments incohérents en entrée : erreur utilisateur ou sortie cohérente."""
    module = _module()
    trace, _, _ = fabriques3.boucle_avec_antenne()
    trace.segments.append(Segment(debut_idx=0, fin_idx=len(trace.points) + 5, longueur_m=10.0, tags={}))
    antennes, _ = robuste(
        lambda: module.detecter(trace), quoi="detecter(segments qui débordent)", erreurs_acceptees=ERREURS
    )
    resultat, _ = robuste(
        lambda: module.elaguer(trace, antennes or []),
        quoi="elaguer(segments qui débordent)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        for i, s in enumerate(resultat.segments):
            assert 0 <= s.debut_idx <= s.fin_idx < len(resultat.points), (
                f"elaguer recopie un segment hors bornes : segments[{i}] = "
                f"({s.debut_idx}, {s.fin_idx}) pour {len(resultat.points)} points"
            )

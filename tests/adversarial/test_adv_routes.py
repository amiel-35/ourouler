"""L3.2 — routes connues (apprentissage), mises à l'épreuve.

Cible : contrat du sprint 3 §2 et §4.

Ce qui est traqué :

* l'**idempotence par `id_sortie`** : `apprendre` est fait pour être relancé
  (« ~160 sorties × 1 appel ≈ 2 min ; idempotent »). Une seconde passe qui
  double les `passages` fausse toutes les parts, donc tous les poids appris ;
* la **maille** : la clé est `(round(lat*3000), round(lon*3000))`. `round`
  arrondit au pair en Python ; si l'écriture et la lecture n'arrondissent pas
  de la même façon, une sortie apprise se relit comme inconnue et `part_connue`
  s'effondre sans rien signaler ;
* les **divisions de `poids_appris`** : le contrat écrit
  `min(4, max(0, log2(part_expo / part_sorties)))`. Une classe jamais roulée
  donne `log2(x/0)`, une classe absente des deux donne `log2(0/0)`, et un jeu
  de parts qui ne somme pas à 1 (classes filtrées en amont) doit rester borné ;
* la **base corrompue** : un `routes_connues.sqlite` tronqué appartient à
  l'utilisateur, pas au programme — message, pas trace.

Le contrat ne décrit pas la forme de `Statistiques` (« km par highway, par
maxspeed, par surface ; part semaine ») : ces tests la découvrent par
introspection plutôt que de l'inventer.
"""

from __future__ import annotations

import dataclasses
import json
import math
from datetime import date
from typing import Any

import fabriques
import pytest
from outils import robuste, sans_accents

from ourouler.boucle.trace import Trace
from ourouler.erreurs import ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L3.2 absent (ourouler.apprentissage.routes)"

#: Maille du contrat §2 : ~30 m à l'équateur.
FACTEUR_MAILLE = 3000

#: Lundi et dimanche de la même semaine : « part semaine » = lundi-vendredi.
LUNDI = date(2024, 5, 13)
DIMANCHE = date(2024, 5, 19)

ERREURS = (ErreurUtilisateur,)


def _module():
    return pytest.importorskip("ourouler.apprentissage.routes", reason=MOTIF_ABSENT)


def _base(module, tmp_path, nom: str = "routes_connues.sqlite"):
    return module.BaseRoutes(tmp_path / nom)


def _trace(n: int = 30, *, highway: str = "tertiary", depart=None, pas_m: float = 100.0):
    coords = fabriques.ligne(n, pas_m=pas_m, depart=depart or (fabriques.LAT0, fabriques.LON0))
    tags = [{"highway": highway, "surface": "asphalt"}] * (n - 1)
    return fabriques.trace_fictive(coords, tags=tags)


# --- vérificateurs tolérants -------------------------------------------------


def _nombres(objet: Any) -> dict[str, float]:
    """Les nombres publics d'un objet, y compris ceux rangés dans ses dicts."""
    trouves: dict[str, float] = {}
    for nom in dir(objet):
        if nom.startswith("_"):
            continue
        valeur = getattr(objet, nom, None)
        if callable(valeur):
            continue
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            trouves[nom] = float(valeur)
        elif isinstance(valeur, dict):
            for cle, sous in valeur.items():
                if isinstance(sous, (int, float)) and not isinstance(sous, bool):
                    trouves[f"{nom}[{cle!r}]"] = float(sous)
    return trouves


def _dicts_numeriques(objet: Any) -> dict[str, dict[str, float]]:
    """Les attributs qui sont des dictionnaires « classe -> nombre »."""
    trouves: dict[str, dict[str, float]] = {}
    for nom in dir(objet):
        if nom.startswith("_"):
            continue
        valeur = getattr(objet, nom, None)
        if isinstance(valeur, dict) and valeur:
            if all(
                isinstance(c, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                for c, v in valeur.items()
            ):
                trouves[nom] = {c: float(v) for c, v in valeur.items()}
    return trouves


def _verifier_statistiques(stats: Any, quoi: str) -> None:
    for nom, valeur in _nombres(stats).items():
        assert not math.isnan(valeur), f"{quoi} : {nom} vaut NaN (division par zéro sortie ?)"
        assert math.isfinite(valeur), f"{quoi} : {nom} est infini ({valeur})"
        assert valeur >= 0, f"{quoi} : {nom} négatif ({valeur})"
        if "part" in sans_accents(nom).casefold():
            assert valeur <= 1.000001, f"{quoi} : {nom} = {valeur}, une part vaut au plus 1"
    for table in _dicts_numeriques(stats).values():
        json.dumps(table)  # les statistiques finissent dans un rapport JSON


def _valeur_pour(stats: Any, classe: str) -> dict[str, float]:
    """Toutes les entrées `classe` des tables de `stats`, par nom de table."""
    return {
        nom: table[classe] for nom, table in _dicts_numeriques(stats).items() if classe in table
    }


# --- la base -----------------------------------------------------------------


def test_la_base_se_cree_et_se_rouvre(tmp_path):
    module = _module()
    chemin = tmp_path / "routes_connues.sqlite"
    base = _base(module, tmp_path)
    assert chemin.is_file(), f"BaseRoutes n'a pas créé {chemin}"
    base.ajouter_trace(_trace(), jour=LUNDI, id_sortie="s1")
    autre = module.BaseRoutes(chemin)
    assert "s1" in autre.sorties_apprises(), (
        "ce qui est appris ne survit pas à la réouverture de la base"
    )


def test_la_base_cree_les_dossiers_parents_manquants(tmp_path):
    """Le cache du mainteneur peut être un dossier tout neuf : pas de `FileNotFoundError`."""
    module = _module()
    chemin = tmp_path / "cache" / "routes_connues.sqlite"
    resultat, _ = robuste(
        lambda: module.BaseRoutes(chemin), quoi="BaseRoutes(dossier absent)", erreurs_acceptees=ERREURS
    )
    if resultat is not None:
        assert chemin.is_file(), "BaseRoutes accepte un chemin dont le dossier n'existe pas sans rien créer"


def test_une_base_corrompue_donne_une_erreur_utilisateur(tmp_path):
    """Contrat §4 : « base corrompue ». Un fichier qui n'est pas du SQLite appartient à l'utilisateur."""
    module = _module()
    chemin = tmp_path / "routes_connues.sqlite"
    chemin.write_bytes(b"ceci n'est pas une base sqlite\x00\x01\x02" * 40)
    base, erreur = robuste(
        lambda: module.BaseRoutes(chemin), quoi="BaseRoutes(fichier corrompu)", erreurs_acceptees=ERREURS
    )
    if base is None:
        assert "sqlite" in str(erreur).casefold() or str(chemin) in str(erreur), (
            f"le message ne dit pas quel fichier reprendre : « {erreur} »"
        )
        return
    robuste(
        lambda: base.ajouter_trace(_trace(), jour=LUNDI, id_sortie="s1"),
        quoi="ajouter_trace(base corrompue)",
        erreurs_acceptees=ERREURS,
    )


def test_ajouter_deux_fois_la_meme_sortie_ne_compte_qu_une_fois(tmp_path):
    """Contrat §2 : « idempotent par id_sortie »."""
    module = _module()
    base = _base(module, tmp_path)
    trace = _trace()
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    apres_une = _nombres(base.statistiques())
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    apres_deux = _nombres(base.statistiques())
    assert base.sorties_apprises() == {"s1"}, (
        f"sorties_apprises() = {base.sorties_apprises()} après deux ajouts du même id_sortie"
    )
    assert apres_deux == apres_une, (
        "rejouer la même sortie change les statistiques : "
        f"{ {c: (apres_une[c], apres_deux[c]) for c in apres_une if apres_une[c] != apres_deux.get(c)} }"
    )


def test_deux_sorties_sur_la_meme_route_cumulent_les_passages(tmp_path):
    """Le pendant du test précédent : l'idempotence ne doit pas devenir de la déduplication."""
    module = _module()
    base = _base(module, tmp_path)
    trace = _trace()
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    une = _nombres(base.statistiques())
    base.ajouter_trace(trace, jour=DIMANCHE, id_sortie="s2")
    deux = _nombres(base.statistiques())
    assert base.sorties_apprises() == {"s1", "s2"}
    assert deux != une, (
        "deux sorties distinctes sur la même route laissent les statistiques inchangées — "
        "les passages ne sont pas comptés"
    )


def test_ajouter_une_trace_sans_segment(tmp_path):
    """Un GPX relu n'a pas de segment : pas de tags OSM, donc rien à apprendre, mais pas de trace."""
    module = _module()
    base = _base(module, tmp_path)
    coords = fabriques.ligne(20, pas_m=100.0)
    resultat, _ = robuste(
        lambda: base.ajouter_trace(fabriques.trace_fictive(coords), jour=LUNDI, id_sortie="s1"),
        quoi="ajouter_trace(trace sans segment)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        assert isinstance(resultat, int) and resultat >= 0, (
            f"ajouter_trace doit rendre un compte de tronçons, reçu {resultat!r}"
        )
    _verifier_statistiques(base.statistiques(), "statistiques(après trace sans segment)")


@pytest.mark.parametrize("nb", [0, 1, 2])
def test_ajouter_une_trace_minuscule(tmp_path, nb):
    module = _module()
    base = _base(module, tmp_path)
    trace = _trace(nb) if nb >= 2 else Trace("minuscule", [], [], 0.0, None, None, {})
    robuste(
        lambda: base.ajouter_trace(trace, jour=LUNDI, id_sortie=f"s{nb}"),
        quoi=f"ajouter_trace(trace de {nb} point(s))",
        erreurs_acceptees=ERREURS,
    )


def test_statistiques_sur_une_base_vide(tmp_path):
    """Aucune sortie apprise : des zéros, pas un NaN ni un `ZeroDivisionError`."""
    module = _module()
    base = _base(module, tmp_path)
    stats, _ = robuste(
        lambda: base.statistiques(), quoi="statistiques(base vide)", erreurs_acceptees=ERREURS
    )
    assert stats is not None, "statistiques() doit répondre sur une base vide"
    _verifier_statistiques(stats, "statistiques(base vide)")
    assert base.sorties_apprises() == set()


def test_les_kilometres_sont_bien_des_kilometres(tmp_path):
    """Contrat §2 : « km par highway ». Une table en mètres fausse toutes les parts affichées."""
    module = _module()
    base = _base(module, tmp_path)
    trace = _trace(51, highway="tertiary", pas_m=200.0)  # 10 km
    attendu_km = trace.distance_m / 1000.0
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    stats = base.statistiques()
    _verifier_statistiques(stats, "statistiques(10 km tertiary)")
    entrees = _valeur_pour(stats, "tertiary")
    assert entrees, (
        "aucune table de statistiques ne cite « tertiary » après 10 km de tertiary : "
        f"tables trouvées = {sorted(_dicts_numeriques(stats))}"
    )
    assert any(v == pytest.approx(attendu_km, rel=0.15) for v in entrees.values()), (
        f"tertiary vaut {entrees} pour un tracé de {attendu_km:.1f} km — "
        f"une valeur proche de {trace.distance_m:.0f} trahirait des mètres au lieu de km"
    )


# --- part_connue --------------------------------------------------------------


def _verifier_part(part: Any, quoi: str) -> float:
    assert isinstance(part, (int, float)) and not isinstance(part, bool), (
        f"{quoi} : nombre attendu, reçu {part!r}"
    )
    assert not math.isnan(part), f"{quoi} : NaN — part calculée sur une distance nulle ?"
    assert 0.0 <= part <= 1.0, f"{quoi} = {part}, une part se lit entre 0 et 1"
    return float(part)


def test_part_connue_d_un_trace_vide(tmp_path):
    """Contrat §4 : « part_connue sur tracé vide ». Le dénominateur vaut zéro."""
    module = _module()
    base = _base(module, tmp_path)
    vide = Trace("vide", [], [], 0.0, None, None, {})
    part, _ = robuste(
        lambda: base.part_connue(vide), quoi="part_connue(tracé vide)", erreurs_acceptees=ERREURS
    )
    if part is not None:
        _verifier_part(part, "part_connue(tracé vide)")


def test_part_connue_sur_une_base_vide_vaut_zero(tmp_path):
    module = _module()
    base = _base(module, tmp_path)
    part = _verifier_part(base.part_connue(_trace()), "part_connue(base vide)")
    assert part == pytest.approx(0.0, abs=1e-9), (
        f"part_connue = {part} alors que rien n'a jamais été appris"
    )


def test_part_connue_d_une_route_apprise_vaut_un(tmp_path):
    """Ce qui vient d'être appris doit se relire : c'est le test de la clé de maille."""
    module = _module()
    base = _base(module, tmp_path)
    trace = _trace(40, pas_m=100.0)
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    part = _verifier_part(base.part_connue(trace), "part_connue(route apprise)")
    assert part == pytest.approx(1.0, abs=0.05), (
        f"part_connue = {part:.2f} sur la trace qui vient d'être apprise — "
        "la maille écrite et la maille relue ne coïncident pas"
    )


def test_part_connue_d_une_route_jamais_vue_vaut_zero(tmp_path):
    module = _module()
    base = _base(module, tmp_path)
    base.ajouter_trace(_trace(40, pas_m=100.0), jour=LUNDI, id_sortie="s1")
    ailleurs = _trace(40, pas_m=100.0, depart=(fabriques.LAT0 + 0.5, fabriques.LON0 + 0.5))
    part = _verifier_part(base.part_connue(ailleurs), "part_connue(route inconnue)")
    assert part == pytest.approx(0.0, abs=0.05), (
        f"part_connue = {part:.2f} à 55 km de tout ce qui a été appris"
    )


def test_une_maille_pile_sur_la_borne_se_relit(tmp_path):
    """Angle obligatoire : `lat * 3000` tombe exactement sur un demi.

    `round` arrondit au pair : `round(10.5) == 10` et `round(11.5) == 12`. Une
    écriture et une lecture qui ne passent pas par la même fonction rangent le
    même point dans deux mailles voisines.
    """
    module = _module()
    base = _base(module, tmp_path)
    # Deux latitudes dont le produit par 3000 vaut exactement k + 0,5, de part
    # et d'autre de la parité : le cas où « arrondi au pair » se voit.
    for k, id_sortie in ((10, "pair"), (11, "impair")):
        lat = (k + 0.5) / FACTEUR_MAILLE
        lon = (k + 0.5) / FACTEUR_MAILLE
        assert abs(lat * FACTEUR_MAILLE - (k + 0.5)) < 1e-9, "la borne doit tomber sur un demi"
        trace = _trace(10, pas_m=40.0, depart=(lat, lon))
        base.ajouter_trace(trace, jour=LUNDI, id_sortie=id_sortie)
        part = _verifier_part(base.part_connue(trace), f"part_connue(borne {id_sortie})")
        assert part == pytest.approx(1.0, abs=0.15), (
            f"part_connue = {part:.2f} sur une trace dont le premier point tombe pile sur la "
            f"borne de maille ({k} + 0,5) et qui vient d'être apprise"
        )


def test_deux_points_du_meme_arrondi_tombent_dans_la_meme_maille(tmp_path):
    """La clé du contrat est `round(lat*3000)`, pas une troncature.

    `k + 0,6` et `k + 1,4` s'arrondissent tous deux à `k + 1` : ils sont dans la
    même maille. `int()` ou `math.floor()` les sépareraient en `k` et `k + 1`,
    et une route apprise se relirait comme inconnue une fois sur deux — sans
    que rien ne le signale, puisque l'écriture et la lecture seraient d'accord
    entre elles.
    """
    module = _module()
    base = _base(module, tmp_path)
    k = 10
    ici = (k + 0.6) / FACTEUR_MAILLE
    voisin = (k + 1.4) / FACTEUR_MAILLE
    assert round(ici * FACTEUR_MAILLE) == round(voisin * FACTEUR_MAILLE), "le montage est faux"
    assert int(ici * FACTEUR_MAILLE) != int(voisin * FACTEUR_MAILLE), "le montage est faux"
    base.ajouter_trace(_trace(2, pas_m=2.0, depart=(ici, ici)), jour=LUNDI, id_sortie="s1")
    part = _verifier_part(
        base.part_connue(_trace(2, pas_m=2.0, depart=(voisin, voisin))), "part_connue(même maille)"
    )
    assert part == pytest.approx(1.0, abs=0.15), (
        f"part_connue = {part:.2f} pour un point distant de 27 cm d'une route apprise, "
        "dans la même maille au sens de round(lat*3000)"
    )


def test_part_connue_est_bornee_sur_une_route_mi_connue(tmp_path):
    """Moitié apprise, moitié neuve : une part intermédiaire, jamais 0 ni plus de 1."""
    module = _module()
    base = _base(module, tmp_path)
    connue = _trace(41, pas_m=100.0)  # 4 km
    base.ajouter_trace(connue, jour=LUNDI, id_sortie="s1")
    prolongee = _trace(81, pas_m=100.0)  # les 4 mêmes km, puis 4 km neufs
    part = _verifier_part(base.part_connue(prolongee), "part_connue(mi-connue)")
    assert 0.2 < part < 0.8, (
        f"part_connue = {part:.2f} pour un tracé connu sur la moitié de ses kilomètres"
    )


# --- poids_appris -------------------------------------------------------------


def _stats(module, tmp_path, classes: dict[str, int], *, nom: str, jour: date = LUNDI):
    """Une `Statistiques` obtenue de la base : sa forme exacte reste celle du lot."""
    base = _base(module, tmp_path, nom=nom)
    decalage = 0.0
    for i, (highway, n) in enumerate(classes.items()):
        depart = (fabriques.LAT0 + decalage, fabriques.LON0)
        base.ajouter_trace(
            _trace(n + 1, highway=highway, pas_m=200.0, depart=depart),
            jour=jour,
            id_sortie=f"{nom}-{i}",
        )
        decalage += 0.5
    return base.statistiques()


def _verifier_poids(poids: Any, quoi: str) -> dict[str, float]:
    assert isinstance(poids, dict), f"{quoi} : dict attendu, reçu {type(poids).__name__}"
    for classe, valeur in poids.items():
        assert isinstance(classe, str), f"{quoi} : clé {classe!r} non textuelle"
        assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
            f"{quoi}[{classe!r}] : nombre attendu, reçu {valeur!r}"
        )
        assert not math.isnan(valeur), f"{quoi}[{classe!r}] vaut NaN (log2(0/0) ?)"
        assert math.isfinite(valeur), f"{quoi}[{classe!r}] est infini (log2(x/0) ?)"
        assert 0.0 <= valeur <= 4.0, (
            f"{quoi}[{classe!r}] = {valeur} : le contrat borne les poids par min(4, max(0, …))"
        )
    json.dumps(poids)  # les poids sont écrits dans poids_routes.json
    assert poids.get("tertiary", 0.0) == 0.0, (
        f"{quoi} : tertiary = {poids.get('tertiary')} — le contrat le force à 0"
    )
    return {c: float(v) for c, v in poids.items()}


def _appeler_poids(module, stats, exposition=None):
    if exposition is None:
        return module.poids_appris(stats)
    return module.poids_appris(stats, exposition)


def test_poids_appris_sans_exposition(tmp_path):
    """Contrat §2 : « Sans exposition (tests), `poids_appris` sur `stats` seule … »."""
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 40, "secondary": 10}, nom="sorties.sqlite")
    poids, _ = robuste(
        lambda: _appeler_poids(module, stats),
        quoi="poids_appris(stats)",
        erreurs_acceptees=(ErreurUtilisateur, TypeError),
    )
    if poids is None:
        pytest.skip("poids_appris exige une exposition : le contrat §2 dit l'inverse (à trancher)")
    _verifier_poids(poids, "poids_appris(stats seule)")
    assert poids, "poids_appris sans exposition rend un dict vide : aucun poids par défaut"


def test_poids_appris_avec_une_exposition_identique_ne_penalise_rien(tmp_path):
    """`log2(part / part) = 0` : rouler exactement ce qu'on rencontre ne coûte rien."""
    module = _module()
    classes = {"tertiary": 40, "secondary": 20, "unclassified": 20}
    stats = _stats(module, tmp_path, classes, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, classes, nom="expo.sqlite")
    poids = _verifier_poids(_appeler_poids(module, stats, expo), "poids_appris(identiques)")
    non_nuls = {c: v for c, v in poids.items() if v > 0.05}
    assert not non_nuls, (
        f"poids non nuls alors que sorties et exposition ont les mêmes parts : {non_nuls}"
    )


def test_poids_appris_penalise_une_classe_evitee(tmp_path):
    """Une classe quatre fois plus offerte que roulée vaut `log2(4) = 2`."""
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 90, "secondary": 10}, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, {"tertiary": 60, "secondary": 40}, nom="expo.sqlite")
    poids = _verifier_poids(_appeler_poids(module, stats, expo), "poids_appris(classe évitée)")
    assert "secondary" in poids, f"secondary absent des poids : {poids}"
    assert poids["secondary"] > 0.5, (
        f"secondary = {poids['secondary']:.2f} alors qu'il est 4 fois plus offert que roulé — "
        "l'évitement appris n'est pas capté"
    )


def test_poids_appris_ne_recompense_pas_une_classe_sur_roulee(tmp_path):
    """`max(0, …)` : une classe plus roulée qu'offerte a un poids nul, jamais négatif."""
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 20, "secondary": 80}, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, {"tertiary": 80, "secondary": 20}, nom="expo.sqlite")
    poids = _verifier_poids(_appeler_poids(module, stats, expo), "poids_appris(sur-roulée)")
    assert poids.get("secondary", 0.0) == pytest.approx(0.0, abs=1e-6), (
        f"secondary = {poids.get('secondary')} alors qu'il est plus roulé qu'offert"
    )


def test_poids_appris_avec_une_classe_jamais_roulee(tmp_path):
    """Contrat §4 : « part 0, log2 de 0/0, plafond 4 » — la division interdite."""
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 100}, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, {"tertiary": 50, "track": 50}, nom="expo.sqlite")
    poids = _verifier_poids(_appeler_poids(module, stats, expo), "poids_appris(classe jamais roulée)")
    assert poids.get("track", 4.0) == pytest.approx(4.0, abs=1e-6), (
        f"track = {poids.get('track')} : une classe offerte et jamais roulée doit saturer "
        "le plafond de 4, pas valoir l'infini ni disparaître"
    )


def test_poids_appris_quand_toutes_les_parts_des_sorties_sont_nulles(tmp_path):
    """Contrat §4 : « log2 de 0/0 ». Chaque classe a 0 km roulé **et** 0 km au total."""
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 50, "secondary": 50}, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, {"tertiary": 50, "secondary": 50}, nom="expo.sqlite")
    poids, _ = robuste(
        lambda: _appeler_poids(module, _mettre_a_echelle(stats, 0.0), expo),
        quoi="poids_appris(sorties à 0 km)",
        erreurs_acceptees=ERREURS,
    )
    if poids is not None:
        _verifier_poids(poids, "poids_appris(0/0)")


def test_poids_appris_avec_des_statistiques_vides(tmp_path):
    """Deux bases vides : `0/0` partout. Erreur utilisateur ou dict borné, jamais un NaN."""
    module = _module()
    vide = _base(module, tmp_path, nom="vide.sqlite").statistiques()
    autre = _base(module, tmp_path, nom="vide2.sqlite").statistiques()
    poids, _ = robuste(
        lambda: _appeler_poids(module, vide, autre),
        quoi="poids_appris(statistiques vides)",
        erreurs_acceptees=ERREURS,
    )
    if poids is not None:
        _verifier_poids(poids, "poids_appris(vides)")


def _mettre_a_echelle(stats: Any, facteur: float):
    """Multiplie toutes les tables numériques : les parts ne somment plus à 1."""
    if not dataclasses.is_dataclass(stats):
        pytest.skip("Statistiques n'est pas une dataclasse : mise à l'échelle impossible en aveugle")
    remplacements = {}
    for champ in dataclasses.fields(stats):
        valeur = getattr(stats, champ.name)
        if isinstance(valeur, dict) and valeur and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in valeur.values()
        ):
            remplacements[champ.name] = {c: v * facteur for c, v in valeur.items()}
    if not remplacements:
        pytest.skip("aucune table numérique dans Statistiques : rien à déséquilibrer")
    return dataclasses.replace(stats, **remplacements)


@pytest.mark.parametrize("facteur", [0.4, 2.5])
def test_poids_appris_avec_des_parts_qui_ne_somment_pas_a_un(tmp_path, facteur):
    """Angle obligatoire : les classes filtrées en amont font des parts qui ne somment pas à 1.

    Le contrat raisonne en *parts* ; si `poids_appris` compare des kilomètres
    bruts sans normaliser, changer l'échelle d'un des deux jeux change tous les
    poids — et une base plus fournie pénaliserait tout.
    """
    module = _module()
    stats = _stats(module, tmp_path, {"tertiary": 60, "secondary": 40}, nom="sorties.sqlite")
    expo = _stats(module, tmp_path, {"tertiary": 30, "secondary": 70}, nom="expo.sqlite")
    reference = _verifier_poids(_appeler_poids(module, stats, expo), "poids_appris(référence)")
    mis_a_echelle = _mettre_a_echelle(stats, facteur)
    obtenus = _verifier_poids(
        _appeler_poids(module, mis_a_echelle, expo), f"poids_appris(stats × {facteur})"
    )
    assert set(obtenus) == set(reference), (
        f"les classes changent quand les parts ne somment plus à 1 : {sorted(obtenus)} "
        f"contre {sorted(reference)}"
    )
    ecarts = {
        c: (reference[c], obtenus[c]) for c in reference if abs(reference[c] - obtenus[c]) > 0.05
    }
    assert not ecarts, (
        f"multiplier les kilomètres des sorties par {facteur} change les poids {ecarts} : "
        "le contrat compare des parts, pas des kilomètres"
    )


# --- socle du sprint 3 déjà livré : [[evitements]] -----------------------------
#
# Contrat §2 : « Évitements : `Config.evitements` → paramètre
# `nogos=lon,lat,rayon|…` passé par `ClientBrouter.boucle/itineraire` ». La
# configuration, elle, est déjà livrée : cette section ne saute pas.


def _charger(sections: dict):
    from ourouler import config as module_config

    return module_config.depuis_dict(
        {
            "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 76.0, "ftp_w": 250.0},
            **sections,
        }
    )


def test_un_evitement_complet_est_relu():
    config = _charger(
        {"evitements": [{"nom": "Rond-point", "latitude": 0.001, "longitude": 0.002, "rayon_m": 150}]}
    )
    assert len(config.evitements) == 1
    evitement = config.evitements[0]
    assert evitement.nom == "Rond-point"
    assert evitement.rayon_m == pytest.approx(150.0)


def test_un_evitement_sans_nom_en_recoit_un():
    """Un évitement sans nom doit rester affichable : la CLI en liste plusieurs."""
    config = _charger({"evitements": [{"latitude": 0.001, "longitude": 0.002}]})
    assert config.evitements[0].nom.strip(), "évitement sans nom lisible"
    assert config.evitements[0].rayon_m > 0, "rayon par défaut nul : l'évitement n'évite rien"


@pytest.mark.parametrize(
    "evitement",
    [
        pytest.param({"latitude": 91.0, "longitude": 0.0}, id="latitude hors du globe"),
        pytest.param({"latitude": 0.0, "longitude": 181.0}, id="longitude hors du globe"),
        pytest.param({"longitude": 0.0}, id="latitude absente"),
        pytest.param({"latitude": 0.0}, id="longitude absente"),
        pytest.param({"latitude": 0.0, "longitude": 0.0, "rayon_m": 0}, id="rayon nul"),
        pytest.param({"latitude": 0.0, "longitude": 0.0, "rayon_m": -50}, id="rayon négatif"),
        pytest.param({"latitude": True, "longitude": 0.0}, id="latitude booléenne"),
        pytest.param("Rennes", id="chaîne au lieu d'une table"),
    ],
)
def test_un_evitement_invalide_nomme_la_section(evitement):
    """Contrat sprint 1 §0 : `ErreurConfig` nomme le champ, jamais une trace et un code 1."""
    from ourouler.erreurs import ErreurConfig

    with pytest.raises(ErreurConfig) as capture:
        _charger({"evitements": [evitement]})
    assert "evitements" in str(capture.value), (
        f"le message ne dit pas quelle section reprendre : « {capture.value} »"
    )


def test_un_evitement_ne_fuite_pas_dans_le_repr_de_la_configuration():
    """Une zone évitée est une adresse : elle ne sort pas dans un `repr` de trace pytest.

    Le contrat ne tranche pas ; ce test **documente** le comportement actuel
    plutôt que de le contraindre — il échouera le jour où quelqu'un décidera de
    masquer les évitements comme le mot de passe BRouter, et c'est le moment où
    le mainteneur devra trancher (règle absolue 1).
    """
    config = _charger({"evitements": [{"nom": "Chez X", "latitude": 0.001, "longitude": 0.002}]})
    assert "Chez X" in repr(config), (
        "les évitements sont désormais masqués dans le repr de Config : mettre à jour "
        "docs/questions_mainteneur.md, c'est une décision produit"
    )

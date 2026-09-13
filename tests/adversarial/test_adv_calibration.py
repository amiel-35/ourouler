"""L3.3 — calibration (`physique/calibration.py`), mise à l'épreuve.

Cible : contrat du sprint 3 §3 et §4. C'est **le** livrable du sprint : le CdA
et le Crr sortis d'ici servent ensuite à toutes les estimations de temps.

Ce qui est traqué :

* la **régression dégénérée** : 0, 1 ou 2 échantillons, ou trente échantillons
  identiques, donnent un système sans solution unique. Un moindres carrés qui
  ne le voit pas rend un CdA de 3 m² ou un `nan`, et le mainteneur lit un
  chiffre faux sans avertissement ;
* les **bornes** : `CdA ∈ [0,18 ; 0,6]`, `Crr ∈ [0,002 ; 0,012]`. Une borne
  atteinte n'est pas un résultat, c'est un échec de l'ajustement — elle doit
  se **dire**, sinon la valeur bornée se lit comme une mesure ;
* le **retour aux paramètres vrais** : des échantillons fabriqués avec un CdA
  connu doivent rendre ce CdA. C'est la seule vérification qui distingue une
  vraie régression d'une fonction qui recopie ses valeurs initiales ;
* la **validation sans sortie de test** : `part_validation = 0,25` sur trois
  sorties peut ne rien réserver du tout. MAE sur zéro sortie, c'est `0/0` ;
* `detecter_groupe` : le contrat le dit « vrai si résidu de vitesse > +8 % sur
  > 50 % de la distance ». Une sortie construite pour coller exactement au
  modèle doit donner faux, une sortie 20 % plus rapide doit donner vrai.
"""

from __future__ import annotations

import inspect
import json
import math
from datetime import date, timedelta
from typing import Any

import fabriques
import fabriques3
import outils
import pytest
from outils import robuste, sans_accents

from ourouler import config as module_config
from ourouler.activites.cache import Cache
from ourouler.erreurs import ErreurUtilisateur

MOTIF_ABSENT = "module attendu par le contrat L3.3 absent (ourouler.physique.calibration)"
MOTIF_MODELE = "ourouler.physique.modele absent : la calibration ne se vérifie pas seule"
MOTIF_ARCHIVE = "ourouler.connecteurs.openmeteo_archive absent : pas de HeureArchive à fournir"

#: Bornes du contrat §3, réécrites ici plutôt que lues dans le module testé.
CDA_MIN, CDA_MAX = 0.18, 0.6
CRR_MIN, CRR_MAX = 0.002, 0.012
MASSE_TOTALE_KG = 85.0

CHAMPS_ECHANTILLON = {"v_ms", "puissance_w", "pente", "vent_face_ms", "temp_c", "retenu", "motif"}

#: Mots par lesquels un lot peut dire qu'une borne a été atteinte.
JETONS_BORNE = ("borne", "satur", "avert", "plafond", "limite", "contraint", "butee")

ERREURS = (ErreurUtilisateur, ValueError)


def _module():
    return pytest.importorskip("ourouler.physique.calibration", reason=MOTIF_ABSENT)


def _modele():
    return pytest.importorskip("ourouler.physique.modele", reason=MOTIF_MODELE)


def _archive():
    return pytest.importorskip("ourouler.connecteurs.openmeteo_archive", reason=MOTIF_ARCHIVE)


# --- lecture tolérante des résultats ------------------------------------------


def _valeurs(objet: Any, jeton: str) -> dict[str, Any]:
    """Les attributs publics dont le nom contient `jeton` (sans accents, sans casse)."""
    cible = sans_accents(jeton).casefold()
    trouves = {}
    for nom in dir(objet):
        if nom.startswith("_"):
            continue
        if cible not in sans_accents(nom).casefold():
            continue
        valeur = getattr(objet, nom, None)
        if not callable(valeur):
            trouves[nom] = valeur
    return trouves


def _nombre_nomme(objet: Any, jeton: str, quoi: str) -> float:
    candidats = {
        nom: valeur
        for nom, valeur in _valeurs(objet, jeton).items()
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool)
    }
    assert candidats, (
        f"{quoi} : aucun attribut numérique évoquant « {jeton} » "
        f"(attributs : {[n for n in dir(objet) if not n.startswith('_')]})"
    )
    assert len(candidats) == 1, f"{quoi} : « {jeton} » ambigu, candidats {sorted(candidats)}"
    return float(next(iter(candidats.values())))


def _verifier_ajustement(ajustement: Any, quoi: str) -> tuple[float, float]:
    fabriques3.tout_fini(ajustement, quoi)
    cda = _nombre_nomme(ajustement, "cda", quoi)
    crr = _nombre_nomme(ajustement, "crr", quoi)
    assert CDA_MIN <= cda <= CDA_MAX, (
        f"{quoi} : CdA = {cda}, hors des bornes [{CDA_MIN} ; {CDA_MAX}] du contrat"
    )
    assert CRR_MIN <= crr <= CRR_MAX, (
        f"{quoi} : Crr = {crr}, hors des bornes [{CRR_MIN} ; {CRR_MAX}] du contrat"
    )
    return cda, crr


def _dit_une_borne(ajustement: Any) -> bool:
    """Vrai si l'objet signale, d'une façon ou d'une autre, qu'une borne est atteinte."""
    for nom in dir(ajustement):
        if nom.startswith("_"):
            continue
        valeur = getattr(ajustement, nom, None)
        if callable(valeur):
            continue
        reduit = sans_accents(nom).casefold()
        if any(jeton in reduit for jeton in JETONS_BORNE):
            if isinstance(valeur, bool):
                if valeur:
                    return True
            elif valeur:
                return True
        if isinstance(valeur, str) and any(j in sans_accents(valeur).casefold() for j in JETONS_BORNE):
            return True
        if isinstance(valeur, (list, tuple)):
            textes = " ".join(str(v) for v in valeur)
            if any(j in sans_accents(textes).casefold() for j in JETONS_BORNE):
                return True
    return False


# --- fabrication d'échantillons ------------------------------------------------


def _echantillon(module, **valeurs):
    complet = {
        "v_ms": 8.0,
        "puissance_w": 180.0,
        "pente": 0.0,
        "vent_face_ms": 0.0,
        "temp_c": 15.0,
        "retenu": True,
        "motif": "",
    }
    complet.update(valeurs)
    return outils.fabriquer(module.Echantillon, complet)


def _echantillons_coherents(module, modele, p, *, n_max: int = 60):
    """Des échantillons fabriqués **avec** le modèle : `calibrer` doit y retrouver `p`."""
    echantillons = []
    for v in (5.0, 6.5, 8.0, 9.5, 11.0):
        for pente in (-0.02, 0.0, 0.02, 0.05):
            for vent in (-3.0, 0.0, 4.0):
                puissance = modele.puissance_requise(v, pente, vent, p)
                echantillons.append(
                    _echantillon(
                        module, v_ms=v, puissance_w=puissance, pente=pente, vent_face_ms=vent
                    )
                )
    return echantillons[:n_max]


def _vent_constant(module_archive, *, vent_kmh: float = 0.0, depuis_deg: float = 0.0, heures: int = 24):
    outils.exiger_champs(
        module_archive.HeureArchive, {"t", "vent_kmh", "vent_depuis_deg", "temp_c", "pression_hpa"}
    )
    base = fabriques3.DEBUT_ACTIVITE.replace(hour=0, minute=0)
    return [
        outils.fabriquer(
            module_archive.HeureArchive,
            {
                "t": base + timedelta(hours=i),
                "vent_kmh": vent_kmh,
                "vent_depuis_deg": depuis_deg,
                "temp_c": 15.0,
                "pression_hpa": 1013.0,
            },
        )
        for i in range(heures)
    ]


# --- calibrer ------------------------------------------------------------------


@pytest.mark.parametrize("nb", [0, 1, 2])
def test_calibrer_avec_trop_peu_d_echantillons(nb):
    """Contrat §4 : « calibration avec 0/1/2 échantillons » — le système est sous-déterminé."""
    module = _module()
    echantillons = [_echantillon(module, v_ms=6.0 + i) for i in range(nb)]
    resultat, _ = robuste(
        lambda: module.calibrer(echantillons, masse_totale_kg=MASSE_TOTALE_KG),
        quoi=f"calibrer({nb} échantillon(s))",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_ajustement(resultat, f"calibrer({nb} échantillons)")


def test_calibrer_avec_des_echantillons_tous_identiques():
    """Contrat §4 : « échantillons tous identiques ». Deux inconnues, une seule équation."""
    module = _module()
    echantillons = [_echantillon(module) for _ in range(40)]
    resultat, _ = robuste(
        lambda: module.calibrer(echantillons, masse_totale_kg=MASSE_TOTALE_KG),
        quoi="calibrer(échantillons identiques)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_ajustement(resultat, "calibrer(échantillons identiques)")


def test_calibrer_retrouve_les_parametres_qui_ont_servi_a_fabriquer_les_echantillons():
    """La seule vérification qui distingue un ajustement d'une recopie des valeurs initiales."""
    module = _module()
    modele = _modele()
    vrais = fabriques3.parametres(modele, cda_m2=0.28, crr=0.0042)
    echantillons = _echantillons_coherents(module, modele, vrais)
    with fabriques.limite_temps(60.0, "calibrer(échantillons cohérents)"):
        ajustement = module.calibrer(
            echantillons, masse_totale_kg=MASSE_TOTALE_KG, cda_init=0.40, crr_init=0.008
        )
    cda, crr = _verifier_ajustement(ajustement, "calibrer(échantillons cohérents)")
    assert cda == pytest.approx(0.28, rel=0.20), (
        f"CdA ajusté = {cda:.4f} pour des échantillons fabriqués à 0,28 m² "
        f"(valeur initiale 0,40 : l'ajustement n'a pas bougé ?)"
    )
    assert crr == pytest.approx(0.0042, rel=0.35), (
        f"Crr ajusté = {crr:.5f} pour des échantillons fabriqués à 0,0042"
    )


def test_calibrer_ignore_les_echantillons_non_retenus():
    """`Echantillon.retenu` existe pour être lu : un échantillon écarté ne doit rien peser."""
    module = _module()
    modele = _modele()
    vrais = fabriques3.parametres(modele, cda_m2=0.28, crr=0.0042)
    bons = _echantillons_coherents(module, modele, vrais)
    pollues = bons + [
        _echantillon(
            module,
            v_ms=3.0,
            puissance_w=1200.0,
            pente=0.0,
            retenu=False,
            motif="puissance hors bornes",
        )
        for _ in range(len(bons))
    ]
    with fabriques.limite_temps(90.0, "calibrer(avec échantillons écartés)"):
        propre = _verifier_ajustement(
            module.calibrer(bons, masse_totale_kg=MASSE_TOTALE_KG), "calibrer(propre)"
        )
        pollue = _verifier_ajustement(
            module.calibrer(pollues, masse_totale_kg=MASSE_TOTALE_KG), "calibrer(pollué)"
        )
    assert pollue[0] == pytest.approx(propre[0], rel=0.02), (
        f"CdA = {pollue[0]:.4f} avec des échantillons marqués `retenu=False`, contre "
        f"{propre[0]:.4f} sans eux : les échantillons écartés pèsent quand même"
    )


def test_une_borne_atteinte_se_dit():
    """Contrat §4 : « bornes atteintes ». Une valeur bornée n'est pas une mesure.

    Les échantillons demandent ici un CdA largement supérieur au plafond : le
    résultat doit rester dans les bornes **et** signaler qu'il y est collé.
    """
    module = _module()
    modele = _modele()
    enorme = fabriques3.parametres(modele, cda_m2=0.95, crr=0.02)
    echantillons = _echantillons_coherents(module, modele, enorme)
    with fabriques.limite_temps(60.0, "calibrer(borne atteinte)"):
        ajustement = module.calibrer(echantillons, masse_totale_kg=MASSE_TOTALE_KG)
    cda, crr = _verifier_ajustement(ajustement, "calibrer(borne atteinte)")
    assert cda == pytest.approx(CDA_MAX, abs=0.02), (
        f"CdA = {cda:.4f} pour des échantillons qui en réclament 0,95 : la borne haute "
        f"({CDA_MAX}) devrait être atteinte"
    )
    assert _dit_une_borne(ajustement), (
        f"CdA collé à la borne {CDA_MAX} sans que l'Ajustement le dise : aucun champ ni "
        f"avertissement n'évoque {JETONS_BORNE} parmi "
        f"{[n for n in dir(ajustement) if not n.startswith('_')]}"
    )


@pytest.mark.parametrize("masse", [0.0, -20.0])
def test_calibrer_avec_une_masse_absurde(masse):
    module = _module()
    echantillons = [_echantillon(module, v_ms=5.0 + i * 0.5) for i in range(20)]
    resultat, _ = robuste(
        lambda: module.calibrer(echantillons, masse_totale_kg=masse),
        quoi=f"calibrer(masse_totale_kg={masse})",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_ajustement(resultat, f"calibrer(masse={masse})")


def test_calibrer_avec_des_echantillons_pollues_de_nan():
    """Un point de FIT sans capteur donne un `nan` : il ne doit pas contaminer la somme."""
    module = _module()
    modele = _modele()
    vrais = fabriques3.parametres(modele)
    echantillons = _echantillons_coherents(module, modele, vrais)
    echantillons.append(_echantillon(module, v_ms=float("nan"), puissance_w=float("nan")))
    with fabriques.limite_temps(60.0, "calibrer(NaN)"):
        resultat, _ = robuste(
            lambda: module.calibrer(echantillons, masse_totale_kg=MASSE_TOTALE_KG),
            quoi="calibrer(échantillon NaN)",
            erreurs_acceptees=ERREURS,
        )
    if resultat is not None:
        _verifier_ajustement(resultat, "calibrer(échantillon NaN)")


# --- echantillonner -------------------------------------------------------------


def _verifier_echantillons(echantillons: Any, quoi: str) -> list[Any]:
    assert isinstance(echantillons, list), f"{quoi} : liste attendue, reçu {type(echantillons).__name__}"
    for i, e in enumerate(echantillons):
        manquants = CHAMPS_ECHANTILLON - {n for n in dir(e) if not n.startswith("_")}
        assert not manquants, f"{quoi}[{i}] : champs du contrat absents {sorted(manquants)}"
        assert isinstance(e.retenu, bool), f"{quoi}[{i}].retenu : booléen attendu, reçu {e.retenu!r}"
        assert isinstance(e.motif, str), f"{quoi}[{i}].motif : chaîne attendue, reçu {e.motif!r}"
        if not e.retenu:
            assert e.motif.strip(), (
                f"{quoi}[{i}] : échantillon écarté sans motif — le rapport ne pourra pas dire "
                "pourquoi il ne reste que 12 points sur 400"
            )
        for nom in ("v_ms", "puissance_w", "pente", "vent_face_ms"):
            valeur = getattr(e, nom)
            if valeur is None:
                continue
            assert isinstance(valeur, (int, float)) and not isinstance(valeur, bool), (
                f"{quoi}[{i}].{nom} : nombre attendu, reçu {valeur!r}"
            )
            assert not math.isnan(valeur), f"{quoi}[{i}].{nom} : NaN"
            assert math.isfinite(valeur), f"{quoi}[{i}].{nom} : infini"
        if e.retenu:
            assert e.v_ms > 0, f"{quoi}[{i}] : échantillon retenu à {e.v_ms} m/s"
            assert e.puissance_w > 0, f"{quoi}[{i}] : échantillon retenu à {e.puissance_w} W"
    return list(echantillons)


def test_echantillonner_ecarte_les_deux_premiers_kilometres():
    """Contrat §3 : « pas dans les 2 premiers km » (échauffement, GPS qui se cale)."""
    module = _module()
    archive = _archive()
    activite = fabriques3.activite_fictive(n_points=120, pas_m=200.0, vitesses_ms=8.0)
    echantillons = _verifier_echantillons(
        module.echantillonner(activite, _vent_constant(archive)), "echantillonner(plat)"
    )
    assert echantillons, "aucun échantillon sur une sortie de 24 km parfaitement régulière"
    retenus = [e for e in echantillons if e.retenu]
    assert retenus, (
        f"{len(echantillons)} échantillons, aucun retenu sur une sortie régulière : "
        f"motifs = {sorted({e.motif for e in echantillons})}"
    )
    assert len(retenus) < len(echantillons), (
        "tous les échantillons sont retenus, y compris ceux des 2 premiers kilomètres"
    )


def test_echantillonner_ecarte_les_pentes_hors_bornes():
    """Contrat §3 : « pente entre −3 % et +8 % » — au-delà, la mesure ne dit plus rien du CdA."""
    module = _module()
    archive = _archive()
    activite = fabriques3.activite_fictive(n_points=120, pas_m=200.0, vitesses_ms=5.0, pente=0.14)
    echantillons = _verifier_echantillons(
        module.echantillonner(activite, _vent_constant(archive)), "echantillonner(14 %)"
    )
    retenus = [e for e in echantillons if e.retenu]
    assert not retenus, (
        f"{len(retenus)} échantillon(s) retenus sur une sortie à 14 % de pente constante"
    )


def test_echantillonner_sur_une_sortie_sans_puissance():
    """Sans capteur, il n'y a rien à calibrer : une liste vide ou des motifs, pas une trace."""
    module = _module()
    archive = _archive()
    activite = fabriques3.activite_fictive(n_points=120, pas_m=200.0, puissance_w=None)
    echantillons = _verifier_echantillons(
        module.echantillonner(activite, _vent_constant(archive)), "echantillonner(sans puissance)"
    )
    retenus = [e for e in echantillons if e.retenu]
    assert not retenus, f"{len(retenus)} échantillon(s) retenus sans un seul watt mesuré"


def test_echantillonner_sans_archive_de_vent():
    """Contrat §4 : « archive météo vide ». Le vent inconnu n'est pas un vent nul mesuré."""
    module = _module()
    activite = fabriques3.activite_fictive(n_points=120, pas_m=200.0)
    resultat, _ = robuste(
        lambda: module.echantillonner(activite, []),
        quoi="echantillonner(vent=[])",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_echantillons(resultat, "echantillonner(vent=[])")


def test_echantillonner_sur_une_sortie_sans_gps():
    """Sans coordonnées, pas de cap, donc pas de vent de face : ni pente ni `TypeError`."""
    module = _module()
    archive = _archive()
    activite = fabriques3.activite_fictive(n_points=60, pas_m=200.0, avec_gps=False)
    resultat, _ = robuste(
        lambda: module.echantillonner(activite, _vent_constant(archive)),
        quoi="echantillonner(sans GPS)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_echantillons(resultat, "echantillonner(sans GPS)")


@pytest.mark.parametrize("nb", [1, 2])
def test_echantillonner_sur_une_sortie_minuscule(nb):
    module = _module()
    archive = _archive()
    activite = fabriques3.activite_fictive(n_points=nb, pas_m=200.0)
    resultat, _ = robuste(
        lambda: module.echantillonner(activite, _vent_constant(archive)),
        quoi=f"echantillonner(sortie de {nb} point(s))",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_echantillons(resultat, f"echantillonner({nb} points)")


# --- detecter_groupe -------------------------------------------------------------


def _verifier_verdict(verdict: Any, quoi: str) -> tuple[bool, float]:
    assert isinstance(verdict, tuple) and len(verdict) == 2, (
        f"{quoi} : le contrat annonce `tuple[bool, float]`, reçu {verdict!r}"
    )
    groupe, residu = verdict
    assert isinstance(groupe, bool), f"{quoi} : premier membre {groupe!r}, booléen attendu"
    assert isinstance(residu, (int, float)) and not isinstance(residu, bool), (
        f"{quoi} : second membre {residu!r}, nombre attendu"
    )
    assert not math.isnan(residu), f"{quoi} : résidu NaN"
    assert math.isfinite(residu), f"{quoi} : résidu infini"
    return groupe, float(residu)


def _sortie_conforme(modele, p, *, facteur: float = 1.0, n_points: int = 200):
    """Une sortie où la vitesse est exactement celle que le modèle prédit (× `facteur`)."""
    puissance = 200.0
    v = modele.vitesse_regime(puissance, 0.0, 0.0, p)
    assert v > 1.0, "le montage suppose une vitesse d'équilibre exploitable"
    return fabriques3.activite_fictive(
        n_points=n_points, pas_m=200.0, vitesses_ms=v * facteur, puissance_w=puissance
    )


def test_detecter_groupe_sur_une_sortie_parfaitement_conforme():
    """Contrat §4 : « sortie parfaitement conforme (faux) »."""
    module = _module()
    modele = _modele()
    archive = _archive()
    p = fabriques3.parametres(modele)
    activite = _sortie_conforme(modele, p)
    with fabriques.limite_temps(60.0, "detecter_groupe(conforme)"):
        groupe, residu = _verifier_verdict(
            module.detecter_groupe(activite, p, _vent_constant(archive)), "detecter_groupe(conforme)"
        )
    assert not groupe, (
        f"sortie roulée exactement à la vitesse que le modèle prédit, classée « groupe » "
        f"(résidu {residu:.3f}) : la calibration écarterait les sorties solo"
    )


def test_detecter_groupe_sur_une_sortie_vingt_pour_cent_trop_rapide():
    """Contrat §4 : « sortie 20 % trop rapide (vrai) » — le seuil du contrat est +8 %."""
    module = _module()
    modele = _modele()
    archive = _archive()
    p = fabriques3.parametres(modele)
    activite = _sortie_conforme(modele, p, facteur=1.20)
    with fabriques.limite_temps(60.0, "detecter_groupe(20 % trop rapide)"):
        groupe, residu = _verifier_verdict(
            module.detecter_groupe(activite, p, _vent_constant(archive)),
            "detecter_groupe(20 % trop rapide)",
        )
    assert groupe, (
        f"sortie roulée 20 % plus vite que le modèle sur 100 % de la distance, non classée "
        f"« groupe » (résidu {residu:.3f}) : le seuil de +8 % sur > 50 % de la distance"
    )


def test_detecter_groupe_sur_une_sortie_vide():
    module = _module()
    modele = _modele()
    archive = _archive()
    p = fabriques3.parametres(modele)
    activite = fabriques3.activite_fictive(n_points=1)
    resultat, _ = robuste(
        lambda: module.detecter_groupe(activite, p, _vent_constant(archive)),
        quoi="detecter_groupe(sortie d'un point)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_verdict(resultat, "detecter_groupe(sortie d'un point)")


# --- valider ---------------------------------------------------------------------


def _verifier_validation(validation: Any, quoi: str) -> None:
    fabriques3.tout_fini(validation, quoi)
    for nom, valeur in fabriques3.valeurs_numeriques(validation).items():
        reduit = sans_accents(nom).casefold()
        if "mae" in reduit or "median" in reduit or "erreur" in reduit:
            assert valeur >= 0, f"{quoi} : {nom} = {valeur}, une erreur en valeur absolue est positive"
    for nom in dir(validation):
        if nom.startswith("_"):
            continue
        valeur = getattr(validation, nom, None)
        if isinstance(valeur, (dict, list)):
            try:
                json.dumps(valeur)
            except TypeError as e:
                raise AssertionError(
                    f"{quoi}.{nom} n'est pas sérialisable JSON : le contrat §3 demande un "
                    f"« rapport texte + JSON » ({e})"
                ) from e


def test_valider_sans_aucune_sortie_de_test():
    """Angle obligatoire : zéro sortie de test. MAE sur zéro sortie, c'est `0/0`."""
    module = _module()
    modele = _modele()
    p = fabriques3.parametres(modele)
    resultat, _ = robuste(
        lambda: module.valider([], p), quoi="valider([])", erreurs_acceptees=ERREURS
    )
    if resultat is not None:
        _verifier_validation(resultat, "valider([])")


def test_valider_sur_une_seule_sortie():
    """Une sortie : la médiane et la MAE existent, et valent la même chose."""
    module = _module()
    modele = _modele()
    archive = _archive()
    p = fabriques3.parametres(modele)
    sortie = (_sortie_conforme(modele, p), _vent_constant(archive))
    with fabriques.limite_temps(60.0, "valider(une sortie)"):
        resultat, _ = robuste(
            lambda: module.valider([sortie], p), quoi="valider(une sortie)", erreurs_acceptees=ERREURS
        )
    if resultat is None:
        return
    _verifier_validation(resultat, "valider(une sortie)")
    erreurs = {
        nom: valeur
        for nom, valeur in fabriques3.valeurs_numeriques(resultat).items()
        if "mae" in sans_accents(nom).casefold()
    }
    assert erreurs, f"aucune MAE dans la validation : {[n for n in dir(resultat) if not n.startswith('_')]}"
    for nom, valeur in erreurs.items():
        assert valeur < 0.5, (
            f"{nom} = {valeur} sur une sortie roulée exactement à la vitesse du modèle — "
            "une erreur de plus de 50 % (ou de 0,5 si la valeur est une fraction) signale "
            "une unité ou un temps de référence incohérents"
        )


def test_valider_sur_une_sortie_immobile():
    """Une sortie de durée nulle : division par le temps réel."""
    module = _module()
    modele = _modele()
    archive = _archive()
    p = fabriques3.parametres(modele)
    activite = fabriques3.activite_fictive(n_points=2, pas_m=0.0, vitesses_ms=0.1)
    resultat, _ = robuste(
        lambda: module.valider([(activite, _vent_constant(archive))], p),
        quoi="valider(sortie immobile)",
        erreurs_acceptees=ERREURS,
    )
    if resultat is not None:
        _verifier_validation(resultat, "valider(sortie immobile)")


# --- sorties_calibrables ----------------------------------------------------------


def _config(tmp_path, mots_groupe=("club", "groupe", "peloton")):
    return module_config.depuis_dict(
        {
            "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 76.0, "ftp_w": 250.0},
            "cache": {"dossier": str(tmp_path / "cache")},
            "velos": [{"nom": "Essai", "masse_kg": 8.5}],
            "calibration": {"mots_groupe": list(mots_groupe)},
        }
    )


def _cache(tmp_path):
    return Cache(tmp_path / "cache")


def test_sorties_calibrables_sur_un_cache_vide(tmp_path):
    module = _module()
    config = _config(tmp_path)
    resultat, _ = robuste(
        lambda: module.sorties_calibrables(_cache(tmp_path), config, config.velos[0]),
        quoi="sorties_calibrables(cache vide)",
        erreurs_acceptees=ERREURS,
    )
    assert resultat == [], f"cache vide, {resultat!r} rendu"


def test_sorties_calibrables_ecarte_le_home_trainer_et_les_sorties_de_groupe(tmp_path, generateur):
    """Contrat §3 : « extérieur, puissance présente, ≥ 20 km, hors mots_groupe »."""
    module = _module()
    config = _config(tmp_path)
    cache = _cache(tmp_path)
    # Des longueurs toutes différentes : le cache range un fichier brut par
    # contenu, deux entrées au contenu identique partageraient leur identifiant.
    for nom, contenu, meta in (
        (
            "solo",
            generateur.gpx(nb_points=250),  # ~27 km
            {"sport": "Ride", "nom": "Sortie tranquille", "name": "Sortie tranquille"},
        ),
        (
            "club",
            generateur.gpx(nb_points=252),
            {"sport": "Ride", "nom": "Sortie club du samedi", "name": "Sortie club du samedi"},
        ),
        (
            "courte",
            generateur.gpx(nb_points=30),  # ~3 km
            {"sport": "Ride", "nom": "Aller au pain", "name": "Aller au pain"},
        ),
        (
            "interieur",
            generateur.gpx(nb_points=254),
            {
                "sport": "VirtualRide",
                "nom": "Home-trainer",
                "name": "Home-trainer",
                "appareil": "home-trainer",
            },
        ),
        (
            "sans_watt",
            generateur.gpx(nb_points=256, puissance=False),
            {"sport": "Ride", "nom": "Balade", "name": "Balade"},
        ),
    ):
        cache.ajouter(contenu, source="intervals", id_externe=nom, extension="gpx", meta=meta)
    retenues, _ = robuste(
        lambda: module.sorties_calibrables(cache, config, config.velos[0]),
        quoi="sorties_calibrables",
        erreurs_acceptees=ERREURS,
    )
    assert retenues is not None, "sorties_calibrables doit répondre sur un cache peuplé"
    noms = {e.id_externe for e in retenues}
    for nom in ("club", "courte", "interieur", "sans_watt"):
        assert nom not in noms, (
            f"la sortie « {nom} » est retenue pour la calibration alors que le contrat "
            "l'écarte (mot de groupe, moins de 20 km, intérieur, ou sans capteur)"
        )
    assert "solo" in noms, (
        "la sortie « solo » (27 km, extérieure, avec puissance) n'est pas retenue "
        f"(métadonnées fournies : sport, nom, name ; retenues = {sorted(noms)})"
    )


def test_sorties_calibrables_respecte_les_mots_de_groupe_configures(tmp_path, generateur):
    """`mots_groupe` est un paramètre de configuration, pas une constante du code."""
    module = _module()
    config = _config(tmp_path, mots_groupe=("cyclosportive",))
    cache = _cache(tmp_path)
    cache.ajouter(
        generateur.gpx(nb_points=250),
        source="intervals",
        id_externe="marquee",
        extension="gpx",
        meta={"sport": "Ride", "nom": "Grande cyclosportive", "name": "Grande cyclosportive"},
    )
    cache.ajouter(
        generateur.gpx(nb_points=252),
        source="intervals",
        id_externe="ordinaire",
        extension="gpx",
        meta={"sport": "Ride", "nom": "Sortie du mardi", "name": "Sortie du mardi"},
    )
    retenues, _ = robuste(
        lambda: module.sorties_calibrables(cache, config, config.velos[0]),
        quoi="sorties_calibrables(mots_groupe configurés)",
        erreurs_acceptees=ERREURS,
    )
    assert retenues is not None
    noms = {e.id_externe for e in retenues}
    assert "marquee" not in noms, (
        "une sortie dont le nom contient le mot de groupe configuré « cyclosportive » est "
        "retenue : les mots sont codés en dur au lieu d'être lus dans la configuration"
    )
    assert "ordinaire" in noms, (
        f"la sortie témoin, de même longueur et sans mot de groupe, est écartée elle aussi "
        f"(retenues = {sorted(noms)})"
    )


def test_sorties_calibrables_respecte_la_date_de_depart(tmp_path, generateur):
    """`depuis` : un historique tronqué ne doit pas ramener des sorties antérieures."""
    module = _module()
    if "depuis" not in inspect.signature(module.sorties_calibrables).parameters:
        pytest.skip("sorties_calibrables ne prend pas de date de départ (contrat §3 muet)")
    config = _config(tmp_path)
    cache = _cache(tmp_path)
    cache.ajouter(
        generateur.gpx(nb_points=250),
        source="intervals",
        id_externe="ancienne",
        extension="gpx",
        meta={"sport": "Ride", "nom": "Sortie", "name": "Sortie"},
    )
    retenues, _ = robuste(
        lambda: module.sorties_calibrables(cache, config, config.velos[0], depuis=date(2030, 1, 1)),
        quoi="sorties_calibrables(depuis 2030)",
        erreurs_acceptees=ERREURS,
    )
    assert retenues == [], f"{retenues!r} rendues pour un « depuis » postérieur à toute sortie"

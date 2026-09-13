"""`ourouler comparer` : deux vélos, les mêmes routes, la différence de watts.

Toutes les sorties sont fabriquées : vitesse et puissance constantes, choisies
ici, sur un tracé qui part du point (0, 0) au milieu de l'Atlantique. Aucune
coordonnée réelle, aucun réseau, aucune donnée du mainteneur.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from test_physique_commande import _en_tcx, config_de_test

from ourouler.activites.cache import Cache
from ourouler.activites.modele import Activite, Point
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.comparer import (
    PENTE_MAX_DEFAUT,
    V_SYNTHESE_KMH,
    Troncon,
    bornes_classes,
    comparer,
    executer_comparer,
    troncons_comparables,
)

METRE_EN_DEGRE = 1.0 / 111_194.93
DEPART = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)


def args(**champs) -> argparse.Namespace:
    defauts = {"velos": ["RCR", "BMC"], "pente_max": None, "depuis": None, "json": False}
    return argparse.Namespace(**{**defauts, **champs})


def sortie_a_allure(
    v_kmh: float,
    puissance_w: float,
    *,
    duree_s: int = 3000,
    lat: float = 0.0,
    pente: float = 0.0,
    nom: str = "sortie fabriquée",
) -> Activite:
    """Une sortie plein est à vitesse et puissance **imposées**, pas déduites.

    C'est l'inverse de `sortie_synthetique` : ici on ne veut pas que le modèle
    décide de la vitesse, on veut savoir exactement quelle moyenne de puissance
    la comparaison doit retrouver.
    """
    v = v_kmh / 3.6
    points = [
        Point(
            t=DEPART + timedelta(seconds=s),
            lat=lat,
            lon=s * v * METRE_EN_DEGRE,
            alt_m=100.0 + s * v * pente,
            dist_m=s * v,
            vitesse_ms=v,
            puissance_w=puissance_w,
        )
        for s in range(duree_s)
    ]
    return Activite(
        source="tcx",
        fichier=None,
        debut=DEPART,
        duree_s=float(duree_s - 1),
        duree_mouvement_s=float(duree_s - 1),
        distance_m=points[-1].dist_m,
        denivele_m=max(0.0, (duree_s - 1) * v * pente),
        puissance_moy_w=puissance_w,
        puissance_np_w=puissance_w,
        sport="cycling",
        appareil=None,
        points=points,
        meta={"nom": nom},
    )


# --- classes de vitesse -------------------------------------------------------


def test_les_classes_vont_de_20_a_40_par_2():
    bornes = bornes_classes()
    assert bornes[0] == (20.0, 22.0)
    assert bornes[-1] == (38.0, 40.0)
    assert len(bornes) == 10


# --- recoupement des mailles --------------------------------------------------


def test_seules_les_mailles_roulees_par_les_deux_comptent():
    """La maille que seul le RCR a roulée ne pèse pas dans sa moyenne."""
    commune = (100, 200)
    a_lui_seul = (999, 999)
    resultat = comparer(
        {
            "RCR": [
                Troncon(cle=commune, v_kmh=31.0, puissance_w=200.0),
                Troncon(cle=a_lui_seul, v_kmh=31.0, puissance_w=400.0),
            ],
            "BMC": [Troncon(cle=commune, v_kmh=31.0, puissance_w=175.0)],
        },
        velos=("RCR", "BMC"),
    )
    assert resultat.mailles == {"RCR": 2, "BMC": 1}
    assert resultat.mailles_communes == 1
    assert resultat.troncons == {"RCR": 1, "BMC": 1}
    classe = resultat.classe_a(31.0)
    assert classe.libelle == "30-32"
    assert classe.puissances["RCR"] == pytest.approx(200.0)
    assert classe.puissances["BMC"] == pytest.approx(175.0)
    assert classe.difference("RCR", "BMC") == pytest.approx(-25.0)
    assert classe.n == {"RCR": 1, "BMC": 1}


def test_aucune_maille_commune_ne_rend_aucune_difference():
    resultat = comparer(
        {
            "RCR": [Troncon(cle=(1, 1), v_kmh=31.0, puissance_w=200.0)],
            "BMC": [Troncon(cle=(2, 2), v_kmh=31.0, puissance_w=175.0)],
        },
        velos=("RCR", "BMC"),
    )
    assert resultat.mailles_communes == 0
    assert all(c.difference("RCR", "BMC") is None for c in resultat.classes)


def test_chaque_classe_de_vitesse_est_separee():
    """Un tronçon à 23 km/h et un à 31 km/h ne se mélangent pas."""
    resultat = comparer(
        {
            "RCR": [
                Troncon(cle=(1, 1), v_kmh=23.0, puissance_w=140.0),
                Troncon(cle=(1, 1), v_kmh=31.0, puissance_w=220.0),
            ],
            "BMC": [
                Troncon(cle=(1, 1), v_kmh=23.0, puissance_w=130.0),
                Troncon(cle=(1, 1), v_kmh=31.0, puissance_w=190.0),
            ],
        },
        velos=("RCR", "BMC"),
    )
    assert resultat.classe_a(23.0).difference("RCR", "BMC") == pytest.approx(-10.0)
    assert resultat.classe_a(31.0).difference("RCR", "BMC") == pytest.approx(-30.0)


def test_hors_bornes_de_vitesse_rien_n_est_compte():
    resultat = comparer(
        {
            "RCR": [Troncon(cle=(1, 1), v_kmh=12.0, puissance_w=100.0)],
            "BMC": [Troncon(cle=(1, 1), v_kmh=45.0, puissance_w=300.0)],
        },
        velos=("RCR", "BMC"),
    )
    assert sum(sum(c.n.values()) for c in resultat.classes) == 0


# --- découpe d'une sortie -----------------------------------------------------


def test_troncons_comparables_garde_le_plat_et_la_puissance():
    troncons = troncons_comparables(sortie_a_allure(31.0, 200.0, duree_s=1200))
    assert len(troncons) > 20
    assert all(t.puissance_w == pytest.approx(200.0) for t in troncons)
    assert all(t.v_kmh == pytest.approx(31.0, abs=0.5) for t in troncons)
    # Toutes les mailles sont distinctes le long d'une ligne droite, mais la
    # clé est bien celle de `apprentissage.routes`.
    from ourouler.apprentissage.routes import cle_maille

    assert troncons[0].cle == cle_maille(0.0, troncons[0].cle[1] / 3000)


def test_une_pente_trop_forte_ecarte_le_troncon():
    """À 3 %, plus rien ne passe le filtre du plat."""
    raide = sortie_a_allure(31.0, 200.0, duree_s=1200, pente=0.03)
    assert troncons_comparables(raide, pente_max=PENTE_MAX_DEFAUT) == []
    # Le même tracé, avec un plafond de pente relevé, redevient comparable.
    assert troncons_comparables(raide, pente_max=0.05)


def test_sans_puissance_aucun_troncon():
    muette = sortie_a_allure(31.0, 200.0, duree_s=1200)
    for point in muette.points:
        point.puissance_w = None
    assert troncons_comparables(muette) == []


def test_pente_max_negative_refusee():
    with pytest.raises(ErreurUtilisateur, match="pente-max"):
        troncons_comparables(sortie_a_allure(31.0, 200.0, duree_s=600), pente_max=-0.1)


# --- la commande de bout en bout ----------------------------------------------


def cache_de_deux_velos(dossier: Path) -> Cache:
    """Deux vélos sur la **même** route, à la même allure, à 25 W d'écart.

    Le RCR sort en plus sur une route que le BMC n'a jamais prise, et à une
    puissance très différente : si le recoupement des mailles ne marchait pas,
    la moyenne du RCR en serait bouleversée.
    """
    cache = Cache(dossier)
    plans = [
        ("CAPTEUR 0001", 200.0, 0.0, [date(2026, 1, j) for j in range(1, 5)], "RCR"),
        ("CAPTEUR 0002", 175.0, 0.0, [date(2026, 2, j) for j in range(1, 5)], "BMC"),
        # Ailleurs, RCR seul, à 400 W : ces mailles doivent disparaître.
        ("CAPTEUR 0001", 400.0, 0.5, [date(2026, 3, j) for j in range(1, 5)], "RCR ailleurs"),
    ]
    for capteur, puissance, lat, jours, etiquette in plans:
        for jour in jours:
            activite = sortie_a_allure(31.0, puissance, lat=lat, nom=f"{etiquette} {jour}")
            cache.ajouter(
                _en_tcx(activite, jour),
                source="intervals",
                id_externe=f"{etiquette}-{jour.isoformat()}",
                extension="tcx",
                meta={
                    "nom": f"{etiquette} du {jour}",
                    "power_meter": capteur,
                    "sport": "Ride",
                },
            )
    return cache


def test_comparer_de_bout_en_bout(tmp_path: Path, capsys):
    """Les 25 W d'écart fabriqués sont retrouvés à 30 km/h, sur les seules mailles communes."""
    cache_de_deux_velos(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", historique_depuis=date(2023, 12, 1))

    assert executer_comparer(args(), config) == 0
    texte = capsys.readouterr().out
    assert "Comparaison RCR / BMC" in texte
    assert "30-32 km/h" in texte
    assert f"À {V_SYNTHESE_KMH:g} km/h sur le plat" in texte
    assert "BMC − RCR = -25 W" in texte


def test_comparer_en_json(tmp_path: Path, capsys):
    cache_de_deux_velos(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache", historique_depuis=date(2023, 12, 1))

    assert executer_comparer(args(json=True), config) == 0
    charge = json.loads(capsys.readouterr().out)
    assert charge["velos"] == ["RCR", "BMC"]
    assert charge["modele_physique"] is False
    assert charge["mailles_communes"] > 0
    assert charge["synthese"]["classe"] == "30-32"
    assert charge["synthese"]["difference_w"] == pytest.approx(-25.0, abs=0.5)
    assert charge["synthese"]["n"]["RCR"] > 0 and charge["synthese"]["n"]["BMC"] > 0
    # Les sorties « ailleurs » à 400 W ont bien été recoupées hors du tableau.
    trente = next(c for c in charge["classes"] if c["v_min_kmh"] == 30.0)
    assert trente["puissance_w"]["RCR"] == pytest.approx(200.0, abs=0.5)
    assert trente["puissance_w"]["BMC"] == pytest.approx(175.0, abs=0.5)


def test_comparer_refuse_deux_fois_le_meme_velo(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="même vélo"):
        executer_comparer(args(velos=["RCR", "rcr"]), config)


def test_comparer_sans_sortie(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="aucun tronçon comparable"):
        executer_comparer(args(), config)


def test_comparer_refuse_une_pente_max_absurde(tmp_path: Path):
    Cache(tmp_path / "cache")
    config = config_de_test(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="pente-max"):
        executer_comparer(args(pente_max=-1.0), config)

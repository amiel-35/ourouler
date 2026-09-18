"""Tests de `seance.ecran_ftp.info_compteur` — le bloc « compteur » partagé par
`boucle` et `sortie` (18/09/2026).

Configuration au point fictif (0.0, 0.0), aucune coordonnée réelle.
"""

from __future__ import annotations

import dataclasses

import pytest

from ourouler.config import depuis_dict
from ourouler.physique.modele import PART_ARRET_REFERENCE
from ourouler.seance.ecran_ftp import info_compteur, valeurs_liees

CONFIG_SANS_VELO = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
}

CONFIG_VELO_MESURE = {
    **CONFIG_SANS_VELO,
    "velos": [
        {
            "nom": "RCR",
            "usage": "route",
            "masse_kg": 9.0,
            "cda_m2": 0.30,
            "crr": 0.005,
            "facteur_compteur": 0.85,
        }
    ],
}


def test_info_compteur_rend_none_sans_le_moindre_velo():
    """`depuis_dict` pose toujours un vélo « Route » par défaut (F0.6) : le cas
    « aucun vélo » ne s'obtient qu'en le retirant après coup, comme
    `cli._info_vitesse_compteur` le teste déjà pour son propre sous-ensemble."""
    config = depuis_dict(CONFIG_SANS_VELO)
    assert info_compteur(dataclasses.replace(config, velos=())) is None


def test_info_compteur_reprend_exactement_valeurs_liees():
    """Pas une deuxième implémentation : les champs viennent tels quels de
    `valeurs_liees`, plus `part_arret_plancher` — et `puissance_w` dit à
    quelle puissance `moyenne_compteur_kmh` a été calculée (règle absolue 5)."""
    config = depuis_dict(CONFIG_VELO_MESURE)
    liees = valeurs_liees(config)
    info = info_compteur(config)
    assert info == {
        "velo": liees["velo"],
        "puissance_w": liees["puissance_endurance_w"],
        "moyenne_compteur_kmh": liees["moyenne_compteur_kmh"],
        "facteur_compteur": liees["facteur_compteur"],
        "facteur_provenance": liees["facteur_provenance"],
        "part_arret_plancher": PART_ARRET_REFERENCE,
    }


def test_info_compteur_sans_puissance_demandee_reprend_la_position_de_la_config():
    """Non-régression : sans `puissance_w`/`vitesse_a_plat_kmh`, `info_compteur`
    continue d'utiliser la position de la configuration, comme avant le
    correctif du 18/09/2026 (le défaut où le porte à porte ne suivait pas
    `--puissance`)."""
    config = depuis_dict(CONFIG_VELO_MESURE)
    assert info_compteur(config) == info_compteur(config, puissance_w=None, vitesse_a_plat_kmh=None)


def test_info_compteur_suit_la_puissance_demandee():
    """Le cœur du correctif : deux puissances demandées rendent deux moyennes
    compteur différentes, chacune datée par le champ `puissance_w`."""
    config = depuis_dict(CONFIG_VELO_MESURE)
    info_150 = info_compteur(config, puissance_w=150.0)
    info_300 = info_compteur(config, puissance_w=300.0)
    assert info_150["puissance_w"] == pytest.approx(150.0, abs=0.1)
    assert info_300["puissance_w"] == pytest.approx(300.0, abs=0.1)
    assert info_300["moyenne_compteur_kmh"] > info_150["moyenne_compteur_kmh"]
    # Le facteur mesuré ne bouge pas avec la puissance demandée :
    assert info_150["facteur_compteur"] == info_300["facteur_compteur"] == 0.85


def test_info_compteur_dit_le_facteur_mesure():
    config = depuis_dict(CONFIG_VELO_MESURE)
    info = info_compteur(config)
    assert info["velo"] == "RCR"
    assert info["facteur_compteur"] == 0.85
    assert info["facteur_provenance"] == "mesure"
    assert info["part_arret_plancher"] == PART_ARRET_REFERENCE


def test_info_compteur_dit_le_facteur_suppose_sans_reglage():
    config = depuis_dict(
        {
            **CONFIG_SANS_VELO,
            "velos": [
                {"nom": "RCR", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.30, "crr": 0.005}
            ],
        }
    )
    info = info_compteur(config)
    assert info["facteur_provenance"] == "suppose"

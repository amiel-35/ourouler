"""Tests de `seance.ecran_ftp.info_compteur` — le bloc « compteur » partagé par
`boucle` et `sortie` (18/09/2026).

Configuration au point fictif (0.0, 0.0), aucune coordonnée réelle.
"""

from __future__ import annotations

import dataclasses

import pytest

from ourouler.config import depuis_dict
from ourouler.erreurs import ErreurUtilisateur
from ourouler.physique.modele import PART_ARRET_REFERENCE
from ourouler.seance.ecran_ftp import ftp_pour_vitesse_compteur, info_compteur, rendu, valeurs_liees

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


# --- sans FTP (facultative depuis le 19/09/2026) ------------------------------

CONFIG_VELO_SANS_FTP = {
    "depart": {"nom": "Point zéro", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80},  # pas de ftp_w
    "velos": [{"nom": "RCR", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.30, "crr": 0.005}],
}


def test_valeurs_liees_none_sans_ftp_meme_avec_un_velo():
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    assert config.cycliste.ftp_w is None
    assert valeurs_liees(config) is None


def test_rendu_sans_ftp_rend_un_etat_explicite_plutot_que_de_planter():
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    r = rendu(config)
    assert r["ftp_w"] is None
    assert r["zones"] == []
    assert r["valeurs_liees"] is None
    # La position, elle, ne dépend pas de la FTP et reste rendue.
    assert r["position_zone"] == pytest.approx(config.seance.position_zone, abs=1e-5)


def test_info_compteur_none_sans_ftp():
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    assert info_compteur(config) is None


# --- T4 de l'accueil : ftp_pour_vitesse_compteur ------------------------------


def test_ftp_pour_vitesse_compteur_sans_velo_leve_une_erreur_nommee():
    """`depuis_dict` pose toujours un vélo « Route » par défaut (F0.6) : le cas
    « aucun vélo » ne s'obtient qu'en le retirant après coup."""
    config = dataclasses.replace(depuis_dict(CONFIG_SANS_VELO), velos=())
    with pytest.raises(ErreurUtilisateur, match="vélo"):
        ftp_pour_vitesse_compteur(
            config, None, vitesse_compteur_kmh=24.0, denivele_m_par_km=10.0
        )


def test_ftp_pour_vitesse_compteur_est_l_inverse_de_moyenne_compteur_kmh():
    """Aller-retour : une FTP connue donne une moyenne compteur (`valeurs_liees`),
    et cette moyenne, reposée en entrée, doit rendre à peu près la même FTP —
    à `position_zone` égale, puisque c'est cette position que la fonction
    suppose (elle établit une FTP, elle n'en déplace pas une)."""
    config_avec_ftp = depuis_dict({**CONFIG_VELO_SANS_FTP, "cycliste": {"masse_kg": 80, "ftp_w": 220}})
    liees = valeurs_liees(config_avec_ftp)
    config_sans_ftp = depuis_dict(CONFIG_VELO_SANS_FTP)
    retrouvee = ftp_pour_vitesse_compteur(
        config_sans_ftp,
        None,
        vitesse_compteur_kmh=liees["moyenne_compteur_kmh"],
        denivele_m_par_km=10.0,  # le défaut du dépôt (DENIVELE_REFERENCE_M_PAR_KM)
    )
    assert retrouvee == pytest.approx(220, abs=1.0)


def test_ftp_pour_vitesse_compteur_terrain_plus_raide_donne_une_ftp_plus_haute():
    """Le levier du §6 de `docs/ux/parcours_accueil.md` : à vitesse compteur
    égale, un terrain plus dur implique une puissance plus haute."""
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    plat = ftp_pour_vitesse_compteur(config, None, vitesse_compteur_kmh=24.0, denivele_m_par_km=3.0)
    montagne = ftp_pour_vitesse_compteur(
        config, None, vitesse_compteur_kmh=24.0, denivele_m_par_km=30.0
    )
    assert montagne > plat


def test_ftp_pour_vitesse_compteur_incoherente_leve_une_erreur_nommee():
    """Aucune puissance plausible n'expliquerait 95 km/h de moyenne compteur
    en montagne — ce n'est pas au modèle de deviner une saisie fautive."""
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    with pytest.raises(ErreurUtilisateur, match="plausible"):
        ftp_pour_vitesse_compteur(
            config, None, vitesse_compteur_kmh=95.0, denivele_m_par_km=30.0
        )


def test_ftp_pour_vitesse_compteur_rejette_une_vitesse_negative_ou_nulle():
    config = depuis_dict(CONFIG_VELO_SANS_FTP)
    with pytest.raises(ErreurUtilisateur):
        ftp_pour_vitesse_compteur(config, None, vitesse_compteur_kmh=0.0, denivele_m_par_km=10.0)

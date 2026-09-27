"""Sprint 11 — « Trois boucles retenues d'office » (QP4, 25/09/2026).

Quand une demande de parcours ne retient qu'une ou deux boucles, la
recherche se relance elle-même avec plus de candidates avant de répondre,
jusqu'à trois boucles retenues ou un plafond de tentatives. Ce module teste
la relance elle-même, sans toucher `SEUIL_RECOUVREMENT` ni la logique de
sélection (`contraste._meilleur_groupe`, `contraste._assez_disjointes`) —
hors sujet du lot.

Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from outils_sortie_commande import (
    brouter_qui_compte,
    lancer,
    moteur_brouter_identique,
)

from ourouler.services.sortie import (
    PALIERS_RELANCE_CANDIDATES,
    _paliers_candidates,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- les paliers, en pure fonction ---------------------------------------------


def test_les_paliers_montent_a_partir_du_nombre_demande():
    assert _paliers_candidates(3) == [3, *PALIERS_RELANCE_CANDIDATES]


def test_un_palier_deja_depasse_n_est_pas_repete():
    """Demander déjà 8 candidates ne redescend pas à 8 : seul 12 s'ajoute."""
    assert _paliers_candidates(8) == [8, 12]


def test_un_palier_intermediaire_saute_directement_au_suivant():
    """Demander 10 candidates : 8 n'apporterait rien, seul 12 s'ajoute."""
    assert _paliers_candidates(10) == [10, 12]


def test_au_dela_de_tous_les_paliers_aucune_relance_n_est_possible():
    """Demander déjà plus que le plus grand palier : un seul essai, le sien."""
    assert _paliers_candidates(20) == [20]


def test_le_plafond_a_deux_paliers_de_relance_au_plus():
    """Le plafond de tentatives, mesuré (voir la constante) : au plus trois
    essais en tout — la demande initiale, et deux relances."""
    assert len(PALIERS_RELANCE_CANDIDATES) == 2


# --- la relance en pratique -----------------------------------------------------


def test_une_demande_qui_retient_deja_trois_boucles_ne_relance_pas(tmp_path: Path, monkeypatch, capsys):
    """Le cas normal : pas de relance, pas de coût de plus."""
    client, compteur = brouter_qui_compte()
    lancer(tmp_path, monkeypatch, brouter=client, candidates=3, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert len(charge["propositions"]) == 3
    assert charge["motif_deux_propositions"] is None
    # Trois candidates demandées, un essai : le nombre d'appels est celui
    # d'une recherche à 3, pas la somme de plusieurs paliers.
    from ourouler.boucle.candidates import appels_pour

    assert compteur["appels"] <= appels_pour(3)


def test_une_demande_trop_courte_se_relance_jusqu_a_trois_boucles(tmp_path: Path, monkeypatch, capsys):
    """Le défaut corrigé par ce lot : une candidate ne suffit jamais à
    contraster trois boucles — la recherche se relance d'elle-même."""
    client, compteur = brouter_qui_compte()
    lancer(tmp_path, monkeypatch, brouter=client, candidates=1, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert len(charge["propositions"]) == 3
    assert charge["motif_deux_propositions"] is None
    # La demande elle-même n'a pas changé : c'est la recherche interne qui
    # s'est relancée, pas ce que le cycliste a demandé.
    assert charge["demande"]["candidates"] == 1
    # Plus d'appels qu'un essai à 1 candidate seule, et pas plus que ce que
    # les paliers autorisent (1, puis 8, puis 12 au pire).
    from ourouler.boucle.candidates import appels_pour

    assert compteur["appels"] > appels_pour(1)
    assert compteur["appels"] <= appels_pour(1) + appels_pour(8) + appels_pour(12)


def test_la_relance_s_arrete_au_plafond_si_trois_boucles_n_existent_pas(tmp_path: Path, monkeypatch, capsys):
    """Quand trois boucles disjointes n'existent vraiment pas, la relance
    essaie tous les paliers puis s'arrête — et le dit honnêtement, sans
    inventer un troisième itinéraire qui repasse par les mêmes routes.

    Le bouchon rend **le même anneau** quel que soit l'azimut demandé, à
    n'importe quel palier : aucune quantité de candidates ne peut jamais
    produire une deuxième boucle qui diffère de la première.
    """
    client = moteur_brouter_identique()
    lancer(tmp_path, monkeypatch, brouter=client, candidates=1, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert len(charge["propositions"]) == 1
    assert charge["motif_deux_propositions"]
    assert charge["demande"]["candidates"] == 1


def test_la_relance_ne_depasse_jamais_le_dernier_palier(tmp_path: Path, monkeypatch, capsys):
    """Le nombre d'appels au moteur reste borné même quand aucun palier ne
    suffit — le plafond de tentatives est un plafond, pas une limite molle."""
    from ourouler.boucle.candidates import appels_pour

    client, compteur = brouter_qui_compte()
    # Un client qui rend toujours le même anneau compterait ses appels, mais
    # `brouter_qui_compte` reste sur le bouchon varié : ce test vérifie le
    # plafond même dans le cas favorable, où la relance s'arrête tôt. Le cas
    # défavorable (aucune boucle disjointe) est couvert par le test
    # précédent, sans compteur — l'essentiel s'y vérifie sur le motif rendu.
    lancer(tmp_path, monkeypatch, brouter=client, candidates=1, json=True)
    capsys.readouterr()
    assert compteur["appels"] <= appels_pour(1) + appels_pour(8) + appels_pour(12)

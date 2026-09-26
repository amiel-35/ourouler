"""Lot F2.4 — le sort de **toutes** les candidates, et par quelle paire.

Le défaut que ces tests gardent est celui que le mainteneur a trouvé en
regardant des cartes : le jugement du produit lui était invisible. Il voyait
ce qui était retenu, jamais ce qui avait été jeté ni pourquoi — et c'est au
**contraste** que ses candidates disparaissaient.

Deux choses doivent tenir, et la seconde compte autant que la première :

1. **Une écartée dit pourquoi dans les termes qui décident** — un pourcentage
   de routes communes et le numéro de la boucle contre laquelle elle a perdu.
   Un motif littéraire ne se vérifie pas sur une carte.
2. **« Écartée » et « pas de place » ne se confondent pas.** Une candidate qui
   allait bien ailleurs mais qui arrive quatrième n'est pas un défaut du
   produit ; les mettre dans le même sac ferait voir un problème là où il n'y
   en a pas.

Toutes les traces sont **fabriquées** autour de (0.0, 0.0), en pleine mer dans
le golfe de Guinée : aucune coordonnée réelle, aucun réseau (règles absolues 1
et 3).
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_sortie_commande import _contexte_minimal, _seance_fabriquee, lancer
from test_sortie_contraste import droite, profil, selection_de

from ourouler.rendu.sortie_json import rendre_json
from ourouler.sortie import contraste
from ourouler.sortie.commande import (
    ETAPE_DISTANCE,
    ETAPE_PLACEMENT,
    Ecartee,
)
from ourouler.sortie.contraste import (
    SORT_PLACE_PRISE,
    SORT_RETENUE,
    SORT_TROP_PROCHE,
)


def sorts(selection) -> list[str]:
    return [v.sort for v in selection.verdicts]


# --- chaque candidate a un verdict, retenue comprise ---------------------------


def test_toutes_les_candidates_portent_un_verdict():
    """Trois candidates entrées, trois verdicts sortis — pas seulement les retenues.

    C'est la demande même du mainteneur : « qu'il m'affiche tout avec le choix
    qu'il aurait fait — écarté ou bien accepté ».
    """
    selection, propositions = selection_de([profil(), profil(), profil()])
    assert len(selection.verdicts) == len(propositions)
    assert [v.numero for v in selection.verdicts] == [1, 2, 3]
    assert sorts(selection) == [SORT_RETENUE] * 3


def test_une_candidate_ecartee_dit_le_pourcentage_et_contre_laquelle():
    """« 50 % des mêmes routes que la n° 1 » — pas « elles se ressemblent ».

    Les deux tracés partagent la moitié de leur longueur : la n° 2 est écartée
    par cette paire-là, et le motif porte les deux termes qui ont décidé.
    """
    commune = droite(50_000.0, lat=0.0)
    chevauchante = droite(50_000.0, lat=0.0, depart_m=25_000.0)
    selection, _ = selection_de(
        [profil(), profil()], traces=[commune, chevauchante]
    )
    assert sorts(selection) == [SORT_RETENUE, SORT_TROP_PROCHE]
    perdante = selection.verdicts[1]
    assert perdante.contre_numero == 1
    assert perdante.recouvrement_max == pytest.approx(0.5, abs=0.02)
    # Sans espace avant le signe, comme `contraste._motif` l'écrit déjà.
    assert "50%" in perdante.motif
    assert "n° 1" in perdante.motif


def test_une_quatrieme_candidate_n_est_pas_dite_ecartee_quand_la_place_manque():
    """Quatre tracés disjoints, trois places : la quatrième n'est pas un défaut.

    La confondre avec une écartée ferait chercher un souci de recouvrement là
    où il n'y en a aucun — et c'est justement ce que cette vue doit éviter de
    faire croire.
    """
    selection, _ = selection_de([profil(), profil(), profil(), profil()])
    assert sorts(selection) == [SORT_RETENUE] * 3 + [SORT_PLACE_PRISE]
    quatrieme = selection.verdicts[3]
    assert "places étaient prises" in quatrieme.motif
    assert "écartée" not in quatrieme.motif


# --- la matrice : c'est elle qui montre qu'une paire suffit --------------------


def test_toutes_les_paires_sont_mesurees_pas_seulement_celles_des_retenues():
    """Quatre candidates, six paires — y compris celles d'aucun groupe servi.

    Sans la matrice complète, un lecteur verrait des verdicts sans pouvoir
    refaire le raisonnement : c'est la case au-dessus du seuil qui explique
    pourquoi telle ligne de candidates est interdite.
    """
    selection, _ = selection_de([profil(), profil(), profil(), profil()])
    assert sorted(selection.recouvrements_candidates) == [
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 2),
        (1, 3),
        (2, 3),
    ]


def test_une_seule_mauvaise_paire_disqualifie_un_trio_et_le_compte_le_dit():
    """Le point de conception que cette vue doit rendre visible.

    Quatre candidates dont trois paires seulement posent problème : la n° 1
    chevauche les n° 2, 3 et 4. Chacun des trois trios possibles contient donc
    au moins une paire au-dessus du seuil, et deux d'entre eux n'en
    contiennent qu'**une** — c'est ce que `refuses_par_une_paire` mesure, et
    c'est ce que la phrase dit.
    """
    tete = droite(50_000.0, lat=0.0)
    selection, _ = selection_de(
        [profil(), profil(), profil(), profil()],
        traces=[
            tete,
            droite(50_000.0, lat=0.0, depart_m=25_000.0),
            droite(50_000.0, lat=5.0),
            droite(50_000.0, lat=9.0),
        ],
    )
    essais = selection.essais
    assert essais is not None
    # Les trois trios contenant la tête : {1,2,3}, {1,2,4}, {1,3,4}.
    assert essais.essayes == 3
    # Seul {1,3,4} tient : la n° 2 chevauche la n° 1.
    assert essais.valides == 1
    # Les deux refusés le sont chacun sur la seule paire (1, 2).
    assert essais.refuses_par_une_paire == 2
    assert "une seule paire" in (selection.phrase_arbitrage or "")
    # Et le groupe servi est bien celui-là : trois propositions, pas deux.
    assert sorts(selection) == [SORT_RETENUE, SORT_TROP_PROCHE, SORT_RETENUE, SORT_RETENUE]


def test_la_phrase_n_invente_pas_une_paire_coupable_quand_il_n_y_en_a_pas():
    """Rien ne tombe : la phrase compte les groupes et s'arrête là.

    Règle absolue 5 — on ne dit « une seule paire a suffi » que lorsque le
    compte le montre.
    """
    selection, _ = selection_de([profil(), profil(), profil()])
    assert (selection.essais and selection.essais.refuses_par_une_paire) == 0
    assert "une seule paire" not in (selection.phrase_arbitrage or "")


def test_le_seuil_publie_est_celui_de_l_appel_pas_la_constante():
    """Un affichage qui relirait la constante mentirait dès qu'on passe autre chose."""
    selection, _ = selection_de([profil(), profil()])
    assert selection.seuil_recouvrement == contraste.SEUIL_RECOUVREMENT


def test_aucun_verdict_ne_sort_sans_sa_phrase():
    """Le pourcentage est écrit par le cœur, jamais laissé à recalculer en aval."""
    selection, _ = selection_de([profil(), profil(), profil(), profil()])
    assert all(v.motif.strip() for v in selection.verdicts)


def test_une_seule_candidate_le_dit_au_lieu_de_comparer_du_vide():
    selection, _ = selection_de([profil()])
    assert sorts(selection) == [SORT_RETENUE]
    assert selection.verdicts[0].recouvrement_max is None
    assert selection.verdicts[0].contre_numero is None
    assert "rien à comparer" in selection.verdicts[0].motif
    # Pas assez de candidates pour former un trio : on ne compte pas des
    # groupes qui n'existent pas.
    assert selection.essais is None
    assert selection.phrase_arbitrage is None


# --- ce que le JSON publie ----------------------------------------------------


def test_le_json_publie_le_sort_de_chaque_candidate(tmp_path, monkeypatch, capsys):
    """Bout en bout, clients bouchonnés : trois candidates, trois verdicts.

    C'est le contrat que le front consomme. Sans ces clés, l'écran ne pourrait
    afficher le sort d'une candidate qu'en le recalculant — ce qu'il n'a pas le
    droit de faire (doctrine §10.2).
    """
    code = lancer(tmp_path, monkeypatch, candidates=3, json=True)
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    arbitrage = charge["arbitrage"]
    assert arbitrage is not None
    assert [c["numero"] for c in arbitrage["candidates"]] == [1, 2, 3]
    assert all(c["motif"] for c in arbitrage["candidates"])
    assert all(
        c["sort"] in {SORT_RETENUE, SORT_TROP_PROCHE, SORT_PLACE_PRISE}
        for c in arbitrage["candidates"]
    )
    # Toutes les paires, pas seulement celles des retenues.
    assert {(p["a"], p["b"]) for p in arbitrage["paires"]} == {(1, 2), (1, 3), (2, 3)}
    assert arbitrage["seuil_recouvrement"] == contraste.SEUIL_RECOUVREMENT
    assert arbitrage["essais"]["taille"] == 3
    assert arbitrage["phrase"]


def test_une_ecartee_du_placement_porte_son_trace_celle_de_la_distance_non(tmp_path):
    """Un azimut et une distance ne se dessinent pas — la géométrie, si.

    Et on n'en invente pas : un refus sur la **distance** n'a jamais construit
    de boucle, donc son `trace` reste `null` plutôt que d'exister vide.
    """
    contexte = replace(
        _contexte_minimal(tmp_path, _seance_fabriquee()),
        ecartees=[
            Ecartee(
                azimut_deg=0.0,
                distance_km=50.0,
                motif="la séance n'y tient pas (motif inventé)",
                etape=ETAPE_PLACEMENT,
                trace=droite(50_000.0, lat=0.0),
            ),
            Ecartee(
                azimut_deg=180.0,
                distance_km=8.2,
                motif="\u221283 % de la distance demandée (motif inventé)",
                etape=ETAPE_DISTANCE,
            ),
        ],
    )
    ecartees = rendre_json([], contexte)["ecartees"]
    assert [e["etape"] for e in ecartees] == [ETAPE_PLACEMENT, ETAPE_DISTANCE]
    assert len(ecartees[0]["trace"]["points"]) > 1
    assert ecartees[1]["trace"] is None

"""`ourouler sortie` : les propositions contrastées et leur répartition.

Trois propositions au plus, chacune avec une phrase qui la distingue ; par
vent de travers, deux azimuts ouverts et des candidates réparties entre eux.
Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import httpx
import pytest
from outils_sortie_commande import (
    CONFIG_BRUTE,
    _contexte_minimal,
    _gestionnaire_brouter,
    _proposition_avec_demi_tour,
    _seance_fabriquee,
    args,
    clients_interdits,
    config_de_test,
    cote,
    lancer,
    moteur_meteo,
)

from ourouler.commandes.sortie import executer_depuis_namespace as executer
from ourouler.config import (
    depuis_dict,
)
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.rendu.sortie import rendre_texte

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- les propositions contrastées ----------------------------------------------


def test_le_json_publie_les_propositions_avec_leur_phrase(tmp_path: Path, monkeypatch, capsys):
    """Les clés que le contrat du lot fixe : `distinction`, `axe_distinctif`,
    `densite_marqueurs_km`, `question_vent`."""
    code = lancer(tmp_path, monkeypatch, candidates=3, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    propositions = charge["propositions"]
    assert propositions, charge
    assert propositions[0]["retenue"] is True
    assert propositions[0]["numero"] == 1
    for proposition in propositions:
        for cle in (
            "distinction",
            "axe_distinctif",
            "densite_marqueurs_km",
            "part_trafic",
            "orientation_vent",
            "recouvrement_max_avec",
        ):
            assert cle in proposition, proposition
    assert charge["question_vent"] is not None
    assert "motif_deux_propositions" in charge


def test_chaque_proposition_porte_une_phrase_et_un_axe_distinct(tmp_path: Path, monkeypatch, capsys):
    """Le garde-fou du lot : pas de phrase, pas de proposition — et deux
    propositions ne peuvent pas se réclamer du même axe."""
    lancer(tmp_path, monkeypatch, candidates=3, json=True)
    propositions = json.loads(capsys.readouterr().out)["propositions"]
    if len(propositions) == 1:
        return  # une seule : rien à distinguer, c'est un cas légitime
    axes = [p["axe_distinctif"] for p in propositions]
    assert all(p["distinction"] for p in propositions), propositions
    assert all(axe for axe in axes), propositions
    vents = [p["orientation_vent"] for p in propositions if p["axe_distinctif"] == "vent"]
    assert len(set(vents)) == len(vents), "deux propositions du même vent"
    non_vent = [a for a in axes if a != "vent"]
    assert len(set(non_vent)) == len(non_vent), axes


def test_moins_de_trois_propositions_dit_pourquoi(tmp_path: Path, monkeypatch, capsys):
    """Avec une seule candidate, il n'y a rien à contraster — et c'est écrit."""
    lancer(tmp_path, monkeypatch, candidates=1, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert len(charge["propositions"]) == 1
    assert charge["motif_deux_propositions"]


def test_les_propositions_sont_un_sous_ensemble_des_candidates(tmp_path: Path, monkeypatch, capsys):
    """`candidates` reste la liste complète et inchangée : un script qui la
    lisait avant les propositions continue de marcher."""
    lancer(tmp_path, monkeypatch, candidates=3, json=True)
    charge = json.loads(capsys.readouterr().out)
    numeros_candidates = {c["numero"] for c in charge["candidates"]}
    numeros_propositions = {p["numero"] for p in charge["propositions"]}
    assert numeros_propositions <= numeros_candidates
    assert len(charge["candidates"]) >= len(charge["propositions"])


def test_sous_le_seuil_de_vent_la_question_n_est_pas_posee(tmp_path: Path, monkeypatch, capsys):
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(vent_kmh=1.0), candidates=2, json=True)
    question = json.loads(capsys.readouterr().out)["question_vent"]
    assert question["posee"] is False
    assert question["motif"]
    assert question["azimuts_recherche_deg"] == []


def test_au_dessus_du_seuil_la_question_est_posee_et_le_texte_la_montre(tmp_path: Path, monkeypatch, capsys):
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(vent_kmh=30.0), candidates=2)
    sortie = capsys.readouterr().out
    assert "Vent au départ" in sortie
    assert "--vent retour-dos" in sortie


def test_une_reponse_au_vent_dirige_la_recherche(tmp_path: Path, monkeypatch, capsys):
    """Le vent bouchonné vient de 45° : pour rentrer avec, on part vers 45°."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        candidates=2,
        vent="retour-dos",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["question_vent"]["reponse"] == "retour-dos"
    assert charge["question_vent"]["azimuts_recherche_deg"] == [pytest.approx(45.0)]


def test_demander_une_direction_et_une_orientation_au_vent_est_refuse(tmp_path: Path, monkeypatch):
    """Q44 : les deux fixent le même azimut, et rien ne disait lequel gagnait.

    `--direction` l'emportait en silence — le cycliste qui avait demandé de
    rentrer avec le vent dans le dos partait au nord sans jamais l'apprendre.
    On ne choisit plus un gagnant, on refuse la contradiction.
    """
    with pytest.raises(ErreurUtilisateur) as erreur:
        lancer(
            tmp_path,
            monkeypatch,
            meteo=moteur_meteo(vent_kmh=30.0),
            direction="N",
            candidates=2,
            vent="retour-dos",
            json=True,
        )
    message = str(erreur.value)
    assert "--direction" in message and "--vent" in message


def test_une_direction_seule_reste_acceptee(tmp_path: Path, monkeypatch, capsys):
    """Le refus ne vise que la contradiction : « au nord » tout court marche."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        direction="N",
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["azimut_deg"] == 0.0


def test_peu_importe_avec_une_direction_n_est_pas_une_contradiction(tmp_path: Path, monkeypatch, capsys):
    """« Peu importe » est l'absence de demande, pas une demande concurrente."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        direction="N",
        candidates=2,
        vent="peu-importe",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["azimut_deg"] == 0.0


def test_une_reponse_au_vent_inconnue_est_refusee_avant_tout_appel(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brouter, meteo, intervals = clients_interdits()
    with pytest.raises(ErreurUtilisateur, match="--vent"):
        executer(
            args(vent="plein-nord"),
            config_de_test(tmp_path / "cache"),
            brouter,
            meteo,
            intervals,
        )


# --- Q44 : le travers ouvre deux azimuts, et les candidates s'y répartissent ---
#
# Le point que le mainteneur demande explicitement de vérifier plutôt que de
# supposer : « les candidates doivent alors se répartir entre les deux azimuts,
# pas s'entasser sur le premier ».
#
# Le piège est réel et il est dans `boucle.candidates.azimuts` : un appel
# `generer(azimut, nb)` explore `azimut`, puis ±20°, ±40°… — il **élargit un
# secteur, il n'en ouvre jamais un second**. Un seul appel pour deux azimuts
# opposés aurait donc rendu toutes les candidates du même côté, et le JSON
# aurait quand même annoncé deux directions.


def azimuts_demandes_a_brouter() -> tuple[httpx.Client, list[float]]:
    """Un BRouter bouchonné qui note chaque `roundTripStartDirection` reçu."""
    vus: list[float] = []
    gestionnaire = _gestionnaire_brouter()

    def espion(requete: httpx.Request) -> httpx.Response:
        vus.append(float(requete.url.params["roundTripStartDirection"]))
        return gestionnaire(requete)

    params = depuis_dict(CONFIG_BRUTE).brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(espion))), vus


def test_le_travers_repartit_les_candidates_entre_les_deux_azimuts(tmp_path: Path, monkeypatch, capsys):
    """Quatre candidates de travers : deux d'un côté, deux de l'autre."""
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=4,
        vent="travers",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    azimuts = charge["question_vent"]["azimuts_recherche_deg"]
    assert len(azimuts) == 2, azimuts

    # Ce que BRouter a réellement été prié d'explorer, et non ce que le JSON
    # annonce : c'est la différence entre la promesse et le fait.
    cotes = [cote(a, azimuts[0]) for a in vus]
    assert cotes.count(0) > 0 and cotes.count(1) > 0, vus
    assert abs(cotes.count(0) - cotes.count(1)) <= 1, vus

    # Et les candidates rendues, pas seulement les appels émis.
    retenus = [cote(c["azimut_deg"], azimuts[0]) for c in charge["candidates"]]
    assert retenus.count(0) > 0 and retenus.count(1) > 0, charge["candidates"]


def test_le_travers_ne_demande_jamais_un_seul_cote(tmp_path: Path, monkeypatch, capsys):
    """Le défaut qu'on corrige, pris à l'envers : trois candidates suffisent.

    Trois se répartissent 2/1 — le reste va au premier azimut, assumé — mais
    **jamais 3/0** : une part nulle voudrait dire que le second azimut n'a pas
    été exploré du tout.
    """
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=3,
        vent="travers",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    premier = charge["question_vent"]["azimuts_recherche_deg"][0]
    cotes = [cote(a, premier) for a in vus]
    assert cotes.count(1) > 0, f"tout est parti du même côté : {vus}"


def test_rentrer_avec_le_vent_n_explore_qu_un_secteur(tmp_path: Path, monkeypatch, capsys):
    """Le pendant : « rentrer avec » contraint, et on le voit dans les appels.

    C'est ce qui rend la mesure de Q44 lisible — la préférence qui contraint
    le plus est celle qui produit les propositions les plus ressemblantes.
    """
    brouter, vus = azimuts_demandes_a_brouter()
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        brouter=brouter,
        candidates=4,
        vent="retour-dos",
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    (azimut,) = charge["question_vent"]["azimuts_recherche_deg"]
    assert all(cote(a, azimut) == 0 for a in vus), vus


def test_le_texte_nomme_les_deux_azimuts_du_travers(tmp_path: Path, monkeypatch, capsys):
    """Annoncer « vers 315° » une recherche menée à 315° **et** 135° serait faux."""
    lancer(
        tmp_path,
        monkeypatch,
        meteo=moteur_meteo(vent_kmh=30.0),
        candidates=4,
        vent="travers",
    )
    sortie = capsys.readouterr().out
    assert "directions imposées" in sortie
    # Vent bouchonné de 45° : le travers ouvre 135° et 315°.
    assert "135°" in sortie and "315°" in sortie


def test_sortie_avertit_aussi_quand_le_modele_vient_de_la_litterature(tmp_path: Path):
    """L'avertissement ne tenait qu'au mot « défaut » (corrigé le 18/09/2026).

    Depuis que les vélos non calibrés reçoivent les valeurs de
    `physique.litterature`, la provenance ne commence plus par « défaut » : le
    ⚠ disparaissait exactement dans le cas où il sert — des blocs placés sur
    des vitesses jamais mesurées sur ce cycliste (règle absolue 5).
    """
    seance = _seance_fabriquee()
    contexte = dataclasses.replace(
        _contexte_minimal(tmp_path, seance), provenance_modele="littérature (Route)"
    )
    texte = rendre_texte([_proposition_avec_demi_tour()], contexte)
    assert "aucun vélo calibré" in texte
    assert "viennent de la littérature" in texte

    calibre = dataclasses.replace(
        _contexte_minimal(tmp_path, seance), provenance_modele="calibration (Route)"
    )
    assert "aucun vélo calibré" not in rendre_texte([_proposition_avec_demi_tour()], calibre)

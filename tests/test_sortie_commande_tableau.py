"""`ourouler sortie` : le tableau imprimé.

Le classement des candidates, la séance placée et la tenue, l'alerte
d'amputation qui suit le placement, le modèle météo nommé dans l'en-tête.
Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
import re
import types
from pathlib import Path

import pytest
from outils_sortie_commande import (
    RAYON_DEG,
    _contexte_minimal,
    _proposition_avec_demi_tour,
    _seance_fabriquee,
    args,
    client_intervals,
    config_de_test,
    ecrire_calibration,
    lancer,
    lignes_du_tableau,
    moteur_brouter,
    moteur_meteo,
    pluie_au_nord,
)

from ourouler.commandes.sortie import executer_depuis_namespace as executer
from ourouler.config import (
    ParametresSeance,
)
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.rendu.sortie import _ecart_seance, _ligne_modele_meteo, rendre_texte
from ourouler.services.sortie import (
    ARRONDI_DISTANCE_KM,
    Proposition,
    _comparer,
    _notes_egales,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- le tableau ---------------------------------------------------------------


def test_le_tableau_montre_les_candidates_retenues(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, candidates=3)
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 3, sortie


def test_le_tri_prend_la_note_de_placement_avant_la_pluie(tmp_path: Path, monkeypatch, capsys):
    """La boucle plate est **au nord**, donc sous la pluie ; elle gagne quand même.

    C'est tout l'ordre de tri : la pluie se contourne en partant plus
    tard, un bloc de seuil en descente ne se contourne pas.
    """
    reglages = {0.0: {"amplitude_m": 1.0}, 180.0: {"amplitude_m": 90.0}}
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(reglages),
        meteo=moteur_meteo(pluie_au_nord),
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    # Depuis la relance d'office (sprint 11) : demander deux candidates ne
    # retient jamais trois boucles à contraster, donc la recherche se
    # relance avec plus de candidates, et le tableau en montre plus que deux.
    # 0° et 180° y restent : c'est sur ces deux-là, et elles seules, que ce
    # test porte, quel que soit le nombre total de candidates cherchées.
    par_azimut = {c["azimut_deg"]: c for c in charge["candidates"]}
    premiere, seconde = par_azimut[0.0], par_azimut[180.0]
    assert premiere["placement"]["note_totale"] < seconde["placement"]["note_totale"]
    assert premiere["meteo"]["pluie_cumulee_mm"] > seconde["meteo"]["pluie_cumulee_mm"]


def test_a_note_equivalente_la_pluie_departage(tmp_path: Path, monkeypatch, capsys):
    """Deux anneaux de même relief, l'un au nord sous la pluie, l'autre au sud au sec.

    **Ce test exigeait des notes bit-identiques (`abs=1e-9`) jusqu'au lot
    L5.1.** Ce n'était pas son propos — c'était sa *précondition* : sans elle,
    « c'est la pluie qui départage » pourrait passer pour la mauvaise raison,
    parce que l'anneau sud aurait simplement une meilleure note.

    Depuis que le vent entre dans la note, deux anneaux de même relief mais
    d'orientation opposée **ne peuvent plus** avoir la même note : l'un est
    parcouru vent de face là où l'autre l'a dans le dos. C'est une
    impossibilité de construction, pas un réglage à trouver — aucune valeur de
    `tolerance_egalite` n'y changerait rien, puisqu'elle n'agit que sur le tri
    et jamais sur la valeur stockée.

    La précondition est donc réécrite dans la forme qu'elle aurait dû avoir
    dès le début : les deux notes doivent être **équivalentes au sens de la
    tolérance**. Si un jour elles s'écartent au-delà, ce test redeviendra
    rouge — et il aura raison, parce que le scénario aura cessé d'être une
    égalité et que l'assertion sur la pluie ne prouverait plus rien.
    """
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(),
        meteo=moteur_meteo(pluie_au_nord),
        candidates=2,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    # Même remarque que dans le test précédent : la relance d'office
    # (sprint 11) ajoute d'autres candidates au tableau, mais 0° et 180°
    # restent celles sur lesquelles ce test porte.
    par_azimut = {c["azimut_deg"]: c for c in charge["candidates"]}
    premiere, seconde = par_azimut[180.0], par_azimut[0.0]
    note_premiere = premiere["placement"]["note_totale"]
    note_seconde = seconde["placement"]["note_totale"]
    tolerance = ParametresSeance().tolerance_egalite
    assert _notes_egales(note_premiere, note_seconde, tolerance), (
        f"le scénario n'est plus une égalité : {note_premiere} contre {note_seconde}. "
        "L'assertion sur la pluie ne prouverait plus rien."
    )
    assert premiere["azimut_deg"] == 180.0
    assert premiere["meteo"]["pluie_cumulee_mm"] < seconde["meteo"]["pluie_cumulee_mm"]


def test_le_vent_change_ou_tombent_les_blocs(tmp_path: Path, monkeypatch, capsys):
    """`ourouler sortie` place la séance avec le vent.

    Une candidate unique (azimut 0°, `candidates=1`), placée deux fois avec
    la même géométrie et la même séance — sans vent, puis avec un vent fort
    et uniforme (45 km/h @ 45°). Si le vent n'était pas branché, les deux
    placements seraient identiques au bit près (c'est exactement ce que
    `placer(..., vent=None)` garantit). Ici ils doivent différer : c'est la
    preuve que `ourouler sortie` construit bien un `ChampVent` et replace la
    séance avec, en deuxième passe.
    """
    dossier_sans = tmp_path / "sans_vent"
    dossier_sans.mkdir()
    code = lancer(dossier_sans, monkeypatch, meteo=moteur_meteo(vent_kmh=0.0), candidates=1, json=True)
    assert code == 0
    sans_vent = json.loads(capsys.readouterr().out)["candidates"][0]["placement"]

    dossier_avec = tmp_path / "avec_vent"
    dossier_avec.mkdir()
    code = lancer(dossier_avec, monkeypatch, meteo=moteur_meteo(vent_kmh=45.0), candidates=1, json=True)
    assert code == 0
    avec_vent = json.loads(capsys.readouterr().out)["candidates"][0]["placement"]

    assert avec_vent["note_totale"] != pytest.approx(sans_vent["note_totale"]), (
        "un vent fort et uniforme doit changer la note de placement"
    )
    # Depuis le lot L5.2, `emplacements[0]` est l'échauffement (toujours au
    # km 0) : c'est le premier **bloc** — le premier emplacement noté — qui
    # doit bouger avec le vent.
    premier_bloc_sans = next(e for e in sans_vent["emplacements"] if e["note"] is not None)
    premier_bloc_avec = next(e for e in avec_vent["emplacements"] if e["note"] is not None)
    assert premier_bloc_avec["debut_m"] != pytest.approx(premier_bloc_sans["debut_m"]), (
        "…et donc l'endroit où tombe le premier bloc"
    )


def _proposition_note_pluie(note: float, pluie_mm: float) -> Proposition:
    """Une `Proposition` minimale, seules la note de placement et la pluie comptent."""
    proposition = _proposition_avec_demi_tour()
    proposition.placement.note_totale = note
    proposition.meteo = types.SimpleNamespace(pluie_cumulee_mm=pluie_mm)
    return proposition


def test_notes_egales_ecart_relatif():
    """`_notes_egales` : deux notes comptent comme égales sous la tolérance (écart relatif)."""
    assert _notes_egales(1.0, 1.0, 0.0)
    assert _notes_egales(0.0, 0.0, 0.0), "deux notes nulles sont égales même à tolérance nulle"
    assert _notes_egales(0.0049, 0.0056, 0.15), "l'écart mesuré au sprint 4 (~12,5 %) est sous 15 %"
    assert not _notes_egales(0.0049, 0.0056, 0.05), "…mais pas sous 5 %"
    assert not _notes_egales(1.0, 2.0, 0.15), "un écart de 50 % n'est jamais une égalité"


def test_comparer_departage_par_la_pluie_dans_la_tolerance():
    """`_comparer` : à tolérance non nulle, la pluie décide entre deux notes proches.

    Les deux notes (0,0049 et 0,0056) sont celles mesurées le 15/09/2026 sur
    les deux anneaux de même relief de `test_a_note_egale_la_pluie_departage`
    — 12,5 % d'écart relatif une fois le vent dans le placement. Sans
    tolérance, la meilleure note gagne même mouillée ; avec la tolérance par
    défaut, l'écart compte comme une égalité et c'est la boucle sèche qui
    l'emporte.
    """
    mouillee_mieux_notee = _proposition_note_pluie(note=0.0049, pluie_mm=3.0)
    seche_un_peu_moins_bien_notee = _proposition_note_pluie(note=0.0056, pluie_mm=0.0)

    comparer_strict = _comparer(0.0)
    assert comparer_strict(mouillee_mieux_notee, seche_un_peu_moins_bien_notee) < 0, (
        "sans tolérance, la note seule décide même mouillée"
    )

    comparer_tolerant = _comparer(0.15)
    assert comparer_tolerant(mouillee_mieux_notee, seche_un_peu_moins_bien_notee) > 0, (
        "à tolérance 15 %, l'écart de note (12,5 %) compte comme une égalité : la pluie décide"
    )
    assert comparer_tolerant(seche_un_peu_moins_bien_notee, mouillee_mieux_notee) < 0


def test_une_candidate_de_note_catastrophique_reste_affichee_en_derniere_position(tmp_path: Path):
    """Règle produit (e) : « on note, on ne filtre pas ».

    Rien ne protégeait explicitement cette règle. Le seul garde-fou était le
    dépaquetage `premiere, seconde = charge["candidates"]` d'un test de tri :
    un filtre qui laisserait toujours passer deux candidates l'aurait franchi
    sans bruit. Le test d'écartement voisin, lui, écarte une boucle **trop
    courte** — une impossibilité physique, pas une mauvaise note.

    Ici la troisième candidate est roulable de bout en bout ; elle est
    simplement épouvantable. Elle doit rester dans le JSON, rester dans le
    tableau, et finir dernière.
    """
    # Fabriqué à la main plutôt que par la commande : la note est alors une
    # donnée du test, pas le sous-produit d'un relief qu'il faudrait régler.
    bonnes = [_proposition_avec_demi_tour(), _proposition_avec_demi_tour()]
    catastrophique = _proposition_avec_demi_tour()
    for numero, proposition in enumerate(bonnes, start=1):
        proposition.numero = numero
        proposition.placement.note_totale = float(numero) * 0.1
    catastrophique.numero = 3
    catastrophique.placement.note_totale = 250.0
    propositions = [*bonnes, catastrophique]
    assert propositions == sorted(propositions, key=lambda p: p.tri), (
        "la fixture doit être déjà triée, sinon le test ne mesure que le tri"
    )

    texte = rendre_texte(propositions, _contexte_minimal(tmp_path, _seance_fabriquee()))

    lignes = lignes_du_tableau(texte)
    assert len(lignes) == 3, texte
    assert lignes[-1].split()[0] == "3", lignes[-1]
    assert "250,00" in lignes[-1], f"la candidate épouvantable est affichée sans sa note : {lignes[-1]}"


@pytest.mark.parametrize("en_json", [False, True], ids=["texte", "json"])
def test_une_candidate_epouvantable_n_est_jamais_filtree(tmp_path: Path, monkeypatch, capsys, en_json):
    """Suite du précédent : le rendu, texte comme JSON, la montre toujours."""
    reglages = {0.0: {"amplitude_m": 1.0}, 120.0: {"amplitude_m": 1.0}, 240.0: {"amplitude_m": 120.0}}
    code = lancer(
        tmp_path,
        monkeypatch,
        brouter=moteur_brouter(reglages),
        candidates=3,
        json=en_json,
    )
    sortie = capsys.readouterr().out
    assert code == 0
    if en_json:
        charge = json.loads(sortie)
        assert "écartée" not in sortie
        assert len(charge["candidates"]) == 3, (
            "une candidate roulable a disparu du JSON : on note, on ne filtre pas"
        )
        notes = [c["placement"]["note_totale"] for c in charge["candidates"]]
        assert notes == sorted(notes), notes
        pire = charge["candidates"][-1]
        assert pire["azimut_deg"] == 240.0, charge["candidates"]
        assert pire["placement"]["note_totale"] > 5 * notes[0], notes
        assert pire["retenue"] is False
    else:
        lignes = lignes_du_tableau(sortie)
        assert len(lignes) == 3, sortie
        assert "candidate(s) écartée(s)" not in sortie


def test_les_candidates_ou_la_seance_ne_tient_pas_sont_ecartees(tmp_path: Path, monkeypatch, capsys):
    """Un anneau trop court est écarté, et on dit pourquoi — jamais en silence.

    **Le motif a changé le 17/09/2026 (Q41 d), pas l'exigence.** Un anneau six
    fois trop petit ne va plus jusqu'au placement : il est refusé avant, parce
    qu'il est trop loin de la distance demandée (−83 % pour une tolérance de
    10 %, élargissement plafonné à 10 %). Les deux refus disent maintenant la
    même chose au même endroit, et c'est tout l'objet de ce test : **une
    direction écartée se dit**. Demander deux directions et n'en voir qu'une
    sans explication serait le défaut même que ce lot corrige.
    """
    # `candidates=4` (et non 2, depuis la relance d'office du sprint 11) :
    # avec les trois candidates qui restent (0°, 90°, 270°) déjà assez
    # disjointes pour contraster trois boucles, le premier essai suffit —
    # aucune relance ne vient ajouter d'autres lignes au tableau, et le
    # nombre de candidates écartées reste déterministe.
    reglages = {180.0: {"rayon_deg": RAYON_DEG / 6}}
    code = lancer(tmp_path, monkeypatch, brouter=moteur_brouter(reglages), candidates=4)
    sortie = capsys.readouterr().out
    assert code == 0
    assert "1 candidate(s) écartée(s)" in sortie
    assert "de la distance demandée" in sortie, "le motif du refus doit être lisible"
    assert "il aurait fallu élargir de" in sortie, "et dire de combien"
    assert len(lignes_du_tableau(sortie)) == 3


def test_toutes_les_candidates_refusees_donne_un_message_clair(tmp_path: Path, monkeypatch):
    """Aucune proposition possible : code 2, comme `boucle` sans boucle bornée."""
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    with pytest.raises(ErreurUtilisateur, match="ne tient sur aucune"):
        executer(
            args(distance=5.0),
            config_de_test(tmp_path / "cache"),
            moteur_brouter({a: {"rayon_deg": RAYON_DEG / 8} for a in (0.0, 180.0)}),
            moteur_meteo(),
            client_intervals(),
        )


def test_la_distance_par_defaut_vient_de_la_seance_arrondie(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    distance = charge["demande"]["distance_km"]
    assert distance % ARRONDI_DISTANCE_KM == 0
    assert "arrondis au multiple de 5" in charge["demande"]["distance_source"]
    # La séance fabriquée fait un peu plus de 30 km : l'arrondi doit rester proche.
    assert 30.0 <= distance <= 45.0


def test_une_distance_demandee_l_emporte(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, distance=34.0, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["demande"]["distance_km"] == 34.0
    assert charge["demande"]["distance_source"] == "demandée"


# --- la séance placée, la tenue ------------------------------------------------


def test_la_seance_placee_est_detaillee_sous_le_tableau(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Séance placée sur la candidate n° 1" in sortie
    # Quatre blocs dans `groupes_watts()`, chacun avec son kilomètre de départ.
    blocs = [ligne for ligne in sortie.splitlines() if ligne.strip().startswith("bloc ")]
    assert len(blocs) == 4, sortie
    assert all(re.search(r"km \d+,\d+ → \d+,\d+", ligne) for ligne in blocs), blocs
    assert all("note" in ligne for ligne in blocs)


def test_la_tenue_est_conseillee_quand_la_meteo_repond(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Tenue conseillée" in sortie
    assert "au départ :" in sortie


def test_sans_meteo_le_tableau_reste_et_la_tenue_disparait(tmp_path: Path, monkeypatch, capsys):
    # `candidates=3` (et non le défaut de la configuration de test, 2) :
    # trois candidates par défaut (0°, 120°, 240°) sont déjà assez disjointes
    # pour contraster trois boucles au premier essai, ce qui évite toute
    # relance d'office (sprint 11) et garde le tableau à un nombre de lignes
    # déterministe.
    code = lancer(tmp_path, monkeypatch, meteo=moteur_meteo(en_panne=True), candidates=3)
    lu = capsys.readouterr()
    assert code == 0
    assert "météo indisponible" in lu.err
    assert "aucun conseil de tenue" in lu.out
    assert "pluie" not in lignes_du_tableau(lu.out)[0]
    assert len(lignes_du_tableau(lu.out)) == 3


# --- Q19 : le modèle météo utilisé est nommé dans l'en-tête --------------------


def _config_avec_modele(modele: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(meteo=types.SimpleNamespace(modele=modele))


def _proposition_avec_meteo(meteo) -> types.SimpleNamespace:
    return types.SimpleNamespace(meteo=meteo)


def test_sans_meteo_aucune_ligne_de_modele():
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(None)], _config_avec_modele("AROME"))
    assert lignes == []


def test_sans_repli_la_ligne_nomme_juste_le_modele():
    meteo = types.SimpleNamespace(modele_utilise="AROME", repli=False)
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(meteo)], _config_avec_modele("AROME"))
    assert lignes == ["Météo : modèle AROME."]


def test_le_repli_est_dit_et_nomme_les_deux_modeles():
    """Critère d'acceptation du contrat : « en nommant le modèle utilisé »."""
    meteo = types.SimpleNamespace(modele_utilise="ICON", repli=True)
    lignes = _ligne_modele_meteo([_proposition_avec_meteo(meteo)], _config_avec_modele("AROME"))
    assert len(lignes) == 1
    assert "AROME" in lignes[0] and "ICON" in lignes[0]
    assert "ne couvre pas" in lignes[0]


# --- Q21 a : l'alerte d'amputation suit le placement, pas un seuil en minutes --


def test_moins_d_une_minute_n_est_jamais_dit():
    """Sous 60 s, l'écart n'est même pas affiché — arrondi du placement, pas une info."""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=30.0)) == ""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=-30.0)) == ""
    assert _ecart_seance(types.SimpleNamespace(depassement_s=None)) == ""


def test_un_depassement_positif_reste_neutre():
    assert _ecart_seance(types.SimpleNamespace(depassement_s=18 * 60.0)) == " (+18 min)"


def test_un_ecart_negatif_sans_verdict_d_amputation_n_alerte_pas():
    """Le défaut mesuré (Q21 a) : 1 min sur 2 h prescrites (0,8 %) déclenchait ⚠

    à tort, alors que le seuil du mainteneur (`elasticite_calme_min`, −5 %)
    ne le justifiait pas. `seance_amputee` porte le verdict du placement, qui
    honore déjà ce seuil (`seance.placement`) — ce test fige seulement que
    l'affichage le respecte, sans lui-même recalculer un pourcentage.
    """
    profil = types.SimpleNamespace(depassement_s=-60.0, seance_amputee=False)
    texte = _ecart_seance(profil)
    assert "⚠" not in texte
    assert "amput" not in texte
    assert texte == " (-1 min)"


def test_un_ecart_negatif_amputant_la_seance_alerte():
    profil = types.SimpleNamespace(depassement_s=-12 * 60.0, seance_amputee=True)
    assert _ecart_seance(profil) == " (⚠ séance amputée de 12 min)"

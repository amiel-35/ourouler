"""`ourouler boucle` : le temps estimé, le temps écoulé porte à porte et le
bloc « compteur ».

Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path

import pytest
from outils_boucle_commande import (
    _evaluation_de_test,
    args,
    config_avec_facteur_mesure,
    config_avec_velo_calibrable,
    config_de_test,
    moteur_brouter,
    moteur_meteo,
)

from ourouler.boucle.commande import (
    Demande,
    _info_compteur,
)
from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.physique.litterature import FOURCHETTE_PORTE_A_PORTE_DEFAUT
from ourouler.rendu.boucle import (
    rendre_texte,
)
from ourouler.rendu.boucle_json import rendre_json

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


def test_sans_calibration_l_ecran_dit_que_le_modele_vient_de_la_litterature(
    tmp_path: Path, monkeypatch, capsys
):
    """Un temps calculé sur des valeurs jamais mesurées le dit — règle absolue 5.

    Le titre de colonne et l'entête doivent porter la même mention : c'est ce
    que fait déjà le facteur compteur avec son « supposé ».
    """
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    executer(args(velo=None, puissance=None), config, moteur_brouter(), moteur_meteo())
    texte = capsys.readouterr().out
    assert "temps (modèle, littérature)" in texte
    assert "sur des valeurs de littérature" in texte
    assert "modèle calibré" not in texte
    # La catégorie servie et ce qu'elle vaut, mesuré : sans ce chiffre, la
    # mention ne dit pas de combien on se trompe.
    assert "route amateur, haut de fourchette" in texte
    assert "min sur 2 h" in texte
    assert "ourouler calibrer --velo RCR" in texte


def test_avec_calibration_la_colonne_dit_le_modele(tmp_path: Path, monkeypatch, capsys):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0, "date": "2026-09-13"},
    )
    executer(args(velo=None, puissance=None), config, moteur_brouter(), moteur_meteo())
    texte = capsys.readouterr().out
    assert "temps (modèle)" in texte
    assert "modèle calibré du RCR" in texte
    assert "arrêts non modélisés" in texte


def test_le_temps_du_modele_depend_de_la_puissance(tmp_path: Path, monkeypatch, capsys):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    temps = []
    for puissance in (150.0, 250.0):
        executer(
            args(velo="RCR", puissance=puissance, json=True),
            config,
            moteur_brouter(),
            moteur_meteo(),
        )
        charge = json.loads(capsys.readouterr().out)
        assert charge["modele_physique"]["puissance_w"] == puissance
        assert all(c["temps_source"] == "modele" for c in charge["candidates"])
        temps.append(charge["candidates"][0]["temps_estime_s"])
    assert temps[0] > temps[1]


def test_sans_calibration_le_json_dit_d_ou_vient_le_temps(
    tmp_path: Path, monkeypatch, capsys
):
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)  # `executer` écrit la boucle retenue en GPX
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    modele = charge["modele_physique"]
    assert modele["provenance"] == "littérature"
    assert modele["mesure"] is False
    assert modele["cda_m2"] == 0.360  # « route amateur, haut de fourchette »
    assert modele["litterature"]["mesuree"] is False
    assert modele["litterature"]["derive_min_2h"] == -0.8
    assert all(c["temps_source"] == "modele" for c in charge["candidates"])


def test_sans_modele_du_tout_la_colonne_revient_a_la_vitesse_moyenne(
    tmp_path: Path, monkeypatch, capsys
):
    """Un usage hors des catégories connues garde le chemin « aucun modèle ».

    `config.USAGES_VELO` n'en accepte que deux aujourd'hui, tous deux dans la
    table : la configuration est donc construite à la main pour éprouver le
    jour où un gravel s'ajoutera. Un temps calculé sur des défauts muets
    vaudrait moins que la vitesse moyenne assumée.
    """
    from dataclasses import replace

    from ourouler.config import Velo

    config = config_avec_velo_calibrable(tmp_path)
    config = replace(config, velos=(Velo(nom="Le gravel", usage="gravel"),))
    monkeypatch.chdir(tmp_path)
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_physique"] is None
    assert all(c["temps_source"] == "vitesse_moyenne" for c in charge["candidates"])


# --- heure de passage météo à la vitesse du modèle -----------------------------


def test_sans_modele_les_heures_de_passage_restent_a_la_vitesse_de_config(
    tmp_path: Path, monkeypatch, capsys
):
    from dataclasses import replace

    from ourouler.config import Velo

    config = config_avec_velo_calibrable(tmp_path)
    config = replace(config, velos=(Velo(nom="Le gravel", usage="gravel"),))
    monkeypatch.chdir(tmp_path)
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert all(
        c["vitesse_meteo_kmh"] == pytest.approx(config.boucle.vitesse_moyenne_kmh)
        for c in charge["candidates"]
    )


def test_sans_ftp_ni_puissance_la_colonne_temps_retombe_sur_la_vitesse_de_config(
    tmp_path: Path, monkeypatch, capsys
):
    """Point 3 (T5) : `ftp_w * PART_FTP_DEFAUT` sur `ftp_w=None` levait `TypeError`.

    Le vélo « RCR » est en catégorie littérature (`provenance != "défaut"`),
    donc `_modele_temps` dépasse le premier repli — c'est bien le second,
    celui qui manque de FTP par défaut faute de `--puissance`, qui est ici
    éprouvé. Repli silencieux vers la vitesse moyenne de la configuration,
    même comportement observable que « aucun modèle disponible » ci-dessus.
    """
    config = config_avec_velo_calibrable(tmp_path, cycliste={"masse_kg": 80})
    assert config.cycliste.ftp_w is None
    monkeypatch.chdir(tmp_path)
    executer(args(velo="RCR", puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_physique"] is None
    assert all(c["temps_source"] == "vitesse_moyenne" for c in charge["candidates"])


def test_sans_calibration_les_heures_de_passage_suivent_la_ftp(
    tmp_path: Path, monkeypatch, capsys
):
    """Le défaut que ce lot corrige, énoncé comme le mainteneur l'a trouvé.

    « Faire varier sa FTP de 150 à 300 W ne déplace ni les heures de passage
    météo ni le temps de mouvement. » Ce test échoue sur le code d'avant.
    """
    from dataclasses import replace

    vitesses = []
    for ftp in (150, 300):
        config = config_avec_velo_calibrable(tmp_path)
        config = replace(config, cycliste=replace(config.cycliste, ftp_w=ftp))
        monkeypatch.chdir(tmp_path)
        executer(
            args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo()
        )
        charge = json.loads(capsys.readouterr().out)
        vitesses.append(charge["candidates"][0]["vitesse_meteo_kmh"])
    assert vitesses[0] < vitesses[1]


def test_avec_calibration_les_heures_de_passage_suivent_le_modele(
    tmp_path: Path, monkeypatch, capsys
):
    """La vitesse qui date la prévision vient du modèle, pas des 27 km/h de la config.

    Deux puissances très différentes doivent donner deux vitesses de passage
    différentes : c'est la preuve que la vitesse vient bien de la simulation.
    """
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    vitesses = []
    for puissance in (120.0, 300.0):
        executer(
            args(velo="RCR", puissance=puissance, json=True),
            config,
            moteur_brouter(),
            moteur_meteo(),
        )
        charge = json.loads(capsys.readouterr().out)
        relevees = [c["vitesse_meteo_kmh"] for c in charge["candidates"]]
        assert all(v is not None and v > 0 for v in relevees)
        vitesses.append(relevees[0])
    assert vitesses[0] < vitesses[1]
    assert vitesses[0] != pytest.approx(config.boucle.vitesse_moyenne_kmh)


def test_l_entete_dit_que_la_vitesse_de_passage_vient_du_modele(
    tmp_path: Path, monkeypatch, capsys
):
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.31, "crr": 0.0045, "masse_totale_kg": 100.0},
    )
    executer(args(velo="RCR", puissance=300.0), config, moteur_brouter(), moteur_meteo())
    entete = capsys.readouterr().out.splitlines()[1]
    assert "heures de passage météo" in entete
    assert "(modèle)" in entete
    assert "27 km/h" not in entete


def _demande_de_test(distance_km: float = 100.0) -> Demande:
    return Demande(
        gpx=None,
        distance_km=distance_km,
        direction="NE",
        azimut_deg=45.0,
        nb_candidates=1,
        profil="fastbike",
        depart=datetime(2026, 9, 18, 9, 0),
        sortie=None,
    )


def test_info_compteur_boucle_rend_none_sans_le_moindre_velo(tmp_path: Path):
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    assert _info_compteur(config, None) is None


def test_compteur_et_temps_ecoule_sont_nuls_sans_velo(tmp_path: Path):
    """Le test explicite du DoD : `compteur` et `temps_ecoule_s` de chaque
    candidate valent `null` sur une configuration sans vélo."""
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    assert charge["compteur"] is None
    candidate = charge["candidates"][0]
    assert candidate["temps_ecoule_s"] is None
    assert candidate["temps_ecoule_source"] is None
    # `temps_estime_s`/`temps_source`, eux, restent renseignés : la panne du
    # compteur n'efface pas le temps de mouvement.
    assert candidate["temps_estime_s"] == 5_000
    assert candidate["temps_source"] == "modele"


def test_compteur_json_porte_les_quatre_champs_du_contrat(tmp_path: Path):
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    compteur = charge["compteur"]
    assert compteur["velo"] == "RCR"
    assert compteur["facteur_compteur"] == pytest.approx(0.85)
    assert compteur["facteur_provenance"] == "mesure"
    assert compteur["moyenne_compteur_kmh"] > 0
    # Sans calibration.json dans le cache de test : la convention, dite
    # comme telle (L9.1).
    assert compteur["porte_a_porte"] == {
        "bas": FOURCHETTE_PORTE_A_PORTE_DEFAUT[0],
        "mediane": FOURCHETTE_PORTE_A_PORTE_DEFAUT[1],
        "haut": FOURCHETTE_PORTE_A_PORTE_DEFAUT[2],
        "provenance": "defaut",
        "n": 0,
    }


def test_info_compteur_suit_la_puissance_demandee(tmp_path: Path):
    """Le défaut du 18/09/2026 : `--puissance`/`--vitesse-a-plat` ne
    déplaçaient pas la moyenne compteur, dérivée de la puissance d'endurance
    **de la configuration** quelle que soit la puissance demandée pour cette
    boucle-ci. Deux puissances doivent maintenant rendre deux moyennes
    différentes, et dire à quelle puissance chacune a été calculée."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    info_150 = _info_compteur(config, None, puissance_w=150.0)
    info_300 = _info_compteur(config, None, puissance_w=300.0)
    assert info_150["puissance_w"] == pytest.approx(150.0, abs=0.1)
    assert info_300["puissance_w"] == pytest.approx(300.0, abs=0.1)
    assert info_150["moyenne_compteur_kmh"] != info_300["moyenne_compteur_kmh"]
    assert info_300["moyenne_compteur_kmh"] > info_150["moyenne_compteur_kmh"]


def test_info_compteur_facteur_mesure_n_est_pas_recalcule(tmp_path: Path):
    """Un facteur **mesuré** (`velo.facteur_compteur`) est une constante du
    vélo : seule la vitesse à laquelle il s'applique bouge avec la puissance
    demandée, jamais le facteur lui-même."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    info_150 = _info_compteur(config, None, puissance_w=150.0)
    info_300 = _info_compteur(config, None, puissance_w=300.0)
    info_defaut = _info_compteur(config, None)
    assert info_150["facteur_compteur"] == pytest.approx(0.85)
    assert info_300["facteur_compteur"] == pytest.approx(0.85)
    assert info_defaut["facteur_compteur"] == pytest.approx(0.85)
    assert info_150["facteur_provenance"] == info_300["facteur_provenance"] == "mesure"


def test_ecran_ftp_valeurs_liees_sans_puissance_ne_bouge_pas(tmp_path: Path):
    """Non-régression sur l'écran de FTP (décision 7) : `valeurs_liees`, sans
    puissance demandée, continue de rendre exactement ce qu'elle rendait —
    la position **de la configuration**, jamais celle d'un parcours chronométré."""
    from ourouler.seance.ecran_ftp import valeurs_liees

    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    avant = {
        "velo": "RCR",
        "position_zone": round(config.seance.position_zone, 6),
        "puissance_endurance_pct": pytest.approx(
            config.seance.puissance_endurance_pct, abs=1e-6
        ),
    }
    apres = valeurs_liees(config)
    assert apres["velo"] == avant["velo"]
    assert apres["position_zone"] == avant["position_zone"]
    assert apres["puissance_endurance_pct"] == avant["puissance_endurance_pct"]
    # Même résultat qu'un appel explicite à `position=None` : la position de
    # la configuration reste la seule qui alimente l'écran de FTP.
    assert apres == valeurs_liees(config, position=None)


def test_temps_ecoule_suit_la_puissance_demandee(tmp_path: Path):
    """Le porte à porte d'une candidate doit suivre `--puissance` : deux
    puissances, deux temps écoulés différents, et l'écart entre mouvement et
    écoulé qui reste celui qu'impose la fourchette (quelques pour cent depuis
    L9.1) dans les deux cas — pas cinquante minutes d'arrêts imaginaires,
    comme avant le correctif du 18/09 (150 W et 300 W rendaient alors le même
    écoulé)."""
    from ourouler.physique.commande import chemin_calibration, parametres_du_velo, velo_demande
    from ourouler.physique.modele import vitesse_a_plat_kmh

    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    velo = velo_demande(config, None)
    parametres, _provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    distance_km = 100.0

    candidates = {}
    for puissance in (150.0, 300.0):
        vitesse_plat = vitesse_a_plat_kmh(puissance, parametres)
        mouvement_s = distance_km / vitesse_plat * 3600
        compteur_info = _info_compteur(config, None, puissance_w=puissance)
        evaluation = _evaluation_de_test(temps_s=mouvement_s, distance_m=distance_km * 1000)
        charge = rendre_json(
            [evaluation],
            _demande_de_test(distance_km),
            config,
            chemin=None,
            compteur_info=compteur_info,
        )
        candidates[puissance] = charge["candidates"][0]

    ecoule_150 = candidates[150.0]["temps_ecoule_s"]
    ecoule_300 = candidates[300.0]["temps_ecoule_s"]
    mouvement_150 = candidates[150.0]["temps_estime_s"]
    mouvement_300 = candidates[300.0]["temps_estime_s"]

    # Le défaut corrigé : les deux écoulés n'étaient pas seulement proches,
    # ils étaient identiques quelle que soit la puissance.
    assert mouvement_150 != mouvement_300
    assert ecoule_150 != ecoule_300

    for ecoule, mouvement in ((ecoule_150, mouvement_150), (ecoule_300, mouvement_300)):
        assert ecoule >= mouvement  # jamais un porte à porte plus rapide
        ratio = ecoule / mouvement
        assert 1.0 < ratio < 1.3  # la fourchette, pas un écart de cinquante minutes


def test_temps_ecoule_json_suit_la_formule_partagee(tmp_path: Path):
    """Pas une deuxième formule : ce que `rendre_json` publie doit être
    exactement `physique.modele.temps_ecoule` appliqué au `temps_estime_s` de
    la candidate et à la fourchette du bloc `compteur` — la médiane dans
    `temps_ecoule_s` (compatibilité), les bornes à côté (L9.1)."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    charge = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    candidate = charge["candidates"][0]
    bas, mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT
    assert candidate["temps_ecoule_s"] == round(5_000.0 * mediane)
    assert candidate["temps_ecoule_bas_s"] == round(5_000.0 * bas)
    assert candidate["temps_ecoule_haut_s"] == round(5_000.0 * haut)
    assert candidate["temps_ecoule_source"] == "defaut"
    assert (
        candidate["temps_ecoule_bas_s"]
        <= candidate["temps_ecoule_s"]
        <= candidate["temps_ecoule_haut_s"]
    )


def test_temps_ecoule_json_prend_la_fourchette_mesuree_du_velo(tmp_path: Path):
    """Un vélo calibré depuis L9.1 porte sa fourchette dans calibration.json :
    c'est elle qui chronomètre, et la source le dit (« mesure »)."""
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration

    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {
            "cda_m2": 0.33,
            "crr": 0.006,
            "masse_totale_kg": 100.0,
            "porte_a_porte": {"bas": 1.02, "mediane": 1.05, "haut": 1.10, "n": 40},
        },
    )
    compteur_info = _info_compteur(config, None)
    assert compteur_info["porte_a_porte"]["provenance"] == "mesure"
    assert compteur_info["porte_a_porte"]["n"] == 40
    evaluation = _evaluation_de_test(temps_s=10_000.0, distance_m=80_000.0)
    candidate = rendre_json(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )["candidates"][0]
    assert candidate["temps_ecoule_bas_s"] == 10_200
    assert candidate["temps_ecoule_s"] == 10_500
    assert candidate["temps_ecoule_haut_s"] == 11_000
    assert candidate["temps_ecoule_source"] == "mesure"


def test_texte_boucle_affiche_mouvement_et_ecoule(tmp_path: Path):
    """CLI et front disent la même chose, **dans le même ordre** : le porte à
    porte d'abord, en fourchette, le temps sans arrêt ensuite, une seule
    cellule « h:mm-h:mm / h:mm », et une légende sous le tableau plutôt
    qu'une colonne de plus (ordre fixé par le mainteneur le 18/09/2026)."""
    config = config_avec_facteur_mesure(tmp_path, facteur=0.85)
    compteur_info = _info_compteur(config, None)
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    texte = rendre_texte(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=compteur_info
    )
    bas, _mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT

    def hm(secondes: float) -> str:
        minutes = round(secondes / 60)
        return f"{minutes // 60}:{minutes % 60:02d}"

    assert f"{hm(5_000 * bas)}-{hm(5_000 * haut)} / {hm(5_000)}" in texte
    assert "porte à porte, arrêts compris / sans un seul arrêt" in texte
    # La convention se dit comme telle (règle absolue 5).
    assert "convention, mesurée sur un seul cycliste" in texte


def test_texte_boucle_dit_la_fourchette_de_la_retenue_en_toutes_lettres():
    """« entre 4 h 23 et 4 h 38 » : l'exemple de la note du 23/09."""
    from ourouler.physique.modele import FourchettePorteAPorte, temps_ecoule
    from ourouler.rendu.boucle import texte_entre

    pp = temps_ecoule(15_600.0, FourchettePorteAPorte(bas=1.015, mediane=1.039, haut=1.072))
    assert texte_entre(pp) == "entre 4 h 24 et 4 h 39"


def test_texte_boucle_sans_compteur_n_affiche_pas_la_legende(tmp_path: Path):
    config = dataclasses.replace(config_avec_facteur_mesure(tmp_path), velos=())
    evaluation = _evaluation_de_test(temps_s=5_000.0, distance_m=50_000.0)
    texte = rendre_texte(
        [evaluation], _demande_de_test(), config, chemin=None, compteur_info=None
    )
    assert "écoulé porte à porte" not in texte
    assert " / " not in texte.splitlines()[3]  # la ligne de la candidate n° 1


def test_boucle_dit_que_le_pneu_a_change_depuis_la_calibration(
    tmp_path: Path, monkeypatch, capsys
):
    """Décision du 25/09 : la calibration est gardée, mais l'écran dit qu'elle
    ne suit plus le pneu déclaré — en texte comme en JSON."""
    from ourouler.physique.commande import chemin_calibration, ecrire_calibration
    from ourouler.physique.parametres_velo import ALERTE_PNEU_CHANGE

    config = config_de_test(
        cache={"dossier": str(tmp_path)},
        velos=[{"nom": "RCR", "usage": "route", "pneu": "vtt"}],
    )
    ecrire_calibration(
        chemin_calibration(config),
        "RCR",
        {"cda_m2": 0.33, "crr": 0.005, "masse_totale_kg": 89.0, "crr_source": "pneu",
         "pneu": "course_rapide"},
    )
    monkeypatch.chdir(tmp_path)
    executer(args(velo=None, puissance=None, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_physique"]["provenance"] == "calibration"
    assert charge["modele_physique"]["alerte"] == ALERTE_PNEU_CHANGE
    executer(args(velo=None, puissance=None), config, moteur_brouter(), moteur_meteo())
    assert ALERTE_PNEU_CHANGE in capsys.readouterr().out

"""La table de littérature, et les deux chemins qui y mènent ou l'évitent.

Ce que ces tests gardent :

1. **la table est vérifiable** — chaque `F@27` consigné se recalcule depuis le
   couple (CdA, Crr) et la masse du vélo de référence, et le jeu retenu est
   bien le plus proche de la référence mesurée ;
2. **la calibration prime toujours** — avec les vraies valeurs du mainteneur
   dans `calibration.json`, rien ne bouge : mêmes vitesses, provenance
   `calibration`, aucune mention de littérature ;
3. **`--vitesse-a-plat`** déduit la puissance par le modèle, et refuse d'être
   donnée en même temps que `--puissance`.

Aucun appel réseau : BRouter et Open-Meteo sont les bouchons de
`outils_boucle_commande`. Aucune coordonnée réelle : tout part du point (0, 0),
à 5 000 km de toute ville — l'invariant `test_invariants` le vérifie.

Les CdA et Crr du mainteneur employés ici ne sont pas des données
personnelles : ce sont des paramètres physiques déjà publiés tels quels dans
`docs/journal/questions/questions_mainteneur.md`, et ils ne désignent personne.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from outils_boucle_commande import (
    args,
    config_avec_velo_calibrable,
    moteur_brouter,
    moteur_meteo,
)
from test_physique_commande import args_simuler, config_de_test, gpx_plat

from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.commandes.physique import simuler_depuis_namespace as executer_simuler
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.physique import litterature
from ourouler.physique.commande import (
    VITESSE_A_PLAT_MAXI_KMH,
    chemin_calibration,
    ecrire_calibration,
    puissance_voulue,
)
from ourouler.physique.modele import Parametres, puissance_a_plat_w, simuler, vitesse_a_plat_kmh

#: La calibration mesurée du vélo de route du mainteneur (campagne du
#: 17/09/2026, `docs/journal/questions/questions_mainteneur.md`). Sa `MAE` valait 4,23 %.
CALIBRATION_ROUTE = {
    "cda_m2": 0.2219,
    "crr": 0.01062,
    "masse_totale_kg": 100.0,
    "rho": 1.222,
    "date": "2026-09-17",
    "n_sorties": 63,
    "mae": 0.0423,
}


# --- 1. la table se vérifie elle-même -----------------------------------------


@pytest.mark.parametrize("usage", sorted(litterature.PAR_USAGE))
def test_chaque_f27_consigne_se_recalcule(usage: str):
    """Les newtons cités dans la table ne sont pas recopiés : ils se refont."""
    choix = litterature.PAR_USAGE[usage]
    assert choix.jeu.force_a_27_n(choix.masse_reference_kg) == pytest.approx(choix.f27_jeu_n, abs=0.01)
    for jeu, f27, _derive in choix.ecartes:
        assert jeu.force_a_27_n(choix.masse_reference_kg) == pytest.approx(f27, abs=0.01)


@pytest.mark.parametrize("usage", sorted(litterature.PAR_USAGE))
def test_le_jeu_retenu_est_le_plus_proche_de_la_reference(usage: str):
    """La règle de choix, écrite une fois et gardée ici.

    Faute de savoir déduire la position, les pneus et la tenue de ce que
    l'utilisateur saisit, chaque catégorie prend le jeu dont la résistance
    totale à 27 km/h tombe le plus près de celle que la calibration a mesurée.
    Si un jour une règle mieux fondée arrive (Q57), c'est ce test qui doit
    changer en premier — et en le voyant changer, on saura que le critère a
    bougé.
    """
    choix = litterature.PAR_USAGE[usage]
    ecart_retenu = abs(choix.f27_jeu_n - choix.f27_reference_n)
    for jeu, f27, _derive in choix.ecartes:
        assert ecart_retenu <= abs(f27 - choix.f27_reference_n), (
            f"{usage} : {jeu.nom} tombe plus près de la référence que le jeu retenu"
        )


@pytest.mark.parametrize("usage", sorted(litterature.PAR_USAGE))
def test_le_jeu_retenu_est_aussi_celui_qui_derive_le_moins(usage: str):
    """Le critère (la force) et la mesure (les minutes) doivent dire la même chose.

    Ils le disent aujourd'hui sur les deux vélos. Le jour où ils divergeraient,
    ce serait que la relation « un newton ≈ deux minutes et demie » ne tient
    plus, et la table ne pourrait plus se justifier sur un seul chiffre.
    """
    choix = litterature.PAR_USAGE[usage]
    for jeu, _f27, derive in choix.ecartes:
        assert abs(choix.derive_min_2h) <= abs(derive), f"{usage} : {jeu.nom} dérivait moins"


def test_la_categorie_clm_ne_porte_pas_le_jeu_qui_porte_son_nom():
    """Le résultat contre-intuitif de la campagne, gravé pour qu'on ne le « corrige » pas.

    « CLM amateur » est le **pire** jeu sur le chrono du mainteneur (+3,5 min)
    et « route amateur » le meilleur (+0,3 min) : il ne roule pas son chrono en
    position de chrono. Quiconque trouverait cette ligne étrange et la
    « réparerait » ferait passer ce vélo de +0,3 à +3,5 minutes.
    """
    choix = litterature.pour_usage("clm")
    assert choix.jeu is litterature.ROUTE_AMATEUR
    assert litterature.CLM_AMATEUR in [jeu for jeu, _f, _d in choix.ecartes]


def test_un_usage_inconnu_ne_rend_rien():
    assert litterature.pour_usage("gravel") is None
    assert litterature.pour_usage("") is None
    assert litterature.pour_usage("ROUTE").jeu is litterature.ROUTE_AMATEUR_HAUT


# --- 2. non-régression : la calibration du mainteneur prime --------------------


def test_avec_sa_calibration_rien_ne_change(tmp_path: Path, monkeypatch, capsys):
    """Les vraies valeurs du mainteneur : mêmes vitesses, provenance `calibration`.

    Le temps et la vitesse de passage sont recalculés **ici** depuis le GPX
    écrit et ses `Parametres` calibrés : s'ils venaient de la littérature, les
    deux chiffres ne tomberaient pas.
    """
    config = config_avec_velo_calibrable(tmp_path)
    ecrire_calibration(chemin_calibration(config), "RCR", CALIBRATION_ROUTE)
    monkeypatch.chdir(tmp_path)
    executer(args(velo="RCR", puissance=200.0, json=True), config, moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)

    modele = charge["modele_physique"]
    assert modele["provenance"] == "calibration"
    assert modele["mesure"] is True
    assert modele["litterature"] is None
    assert modele["cda_m2"] == CALIBRATION_ROUTE["cda_m2"]
    assert modele["crr"] == CALIBRATION_ROUTE["crr"]

    parametres = Parametres(
        masse_totale_kg=CALIBRATION_ROUTE["masse_totale_kg"],
        cda_m2=CALIBRATION_ROUTE["cda_m2"],
        crr=CALIBRATION_ROUTE["crr"],
        rho=CALIBRATION_ROUTE["rho"],
    )
    trace = lire_gpx_trace(Path(charge["gpx"]))
    attendue = simuler(trace, 200.0, parametres).vitesse_moy_kmh
    retenue = charge["candidates"][0]  # la première est celle qui est écrite
    # Le JSON arrondit au centième : l'égalité se lit à cette précision-là.
    assert retenue["vitesse_meteo_kmh"] == pytest.approx(attendue, abs=0.01)
    assert retenue["temps_source"] == "modele"


def test_avec_sa_calibration_l_ecran_ne_parle_pas_de_litterature(tmp_path: Path, monkeypatch, capsys):
    config = config_avec_velo_calibrable(tmp_path)
    ecrire_calibration(chemin_calibration(config), "RCR", CALIBRATION_ROUTE)
    monkeypatch.chdir(tmp_path)
    executer(args(velo="RCR", puissance=200.0), config, moteur_brouter(), moteur_meteo())
    texte = capsys.readouterr().out
    assert "temps (modèle)" in texte
    assert "modèle calibré du RCR" in texte
    assert "littérature" not in texte


def test_sans_calibration_simuler_sert_la_litterature_et_le_dit(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    executer_simuler(args_simuler(gpx=str(gpx), json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["parametres"]["provenance"] == "littérature"
    assert charge["parametres"]["cda_m2"] == litterature.ROUTE_AMATEUR_HAUT.cda_m2
    assert charge["parametres"]["litterature"]["mesuree"] is False
    assert charge["parametres"]["litterature"]["jeu"] == "route amateur, haut de fourchette"


def test_le_clm_recoit_son_propre_jeu(tmp_path: Path, capsys):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    executer_simuler(args_simuler(gpx=str(gpx), velo="BMC", json=True), config)
    charge = json.loads(capsys.readouterr().out)
    assert charge["parametres"]["cda_m2"] == litterature.ROUTE_AMATEUR.cda_m2
    assert charge["parametres"]["litterature"]["usage"] == "clm"


# --- 3. entrer une vitesse plutôt qu'une puissance ----------------------------


def test_la_vitesse_a_plat_se_convertit_en_puissance(tmp_path: Path, capsys):
    """La puissance déduite est celle du modèle, et l'aller-retour se referme."""
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    executer_simuler(args_simuler(gpx=str(gpx), puissance=None, vitesse_a_plat=30.0, json=True), config)
    charge = json.loads(capsys.readouterr().out)

    parametres = Parametres(
        masse_totale_kg=charge["parametres"]["masse_totale_kg"],
        cda_m2=charge["parametres"]["cda_m2"],
        crr=charge["parametres"]["crr"],
    )
    assert charge["puissance_w"] == pytest.approx(puissance_a_plat_w(30.0, parametres))
    # Le GPX d'essai est plat et le vent nul : la vitesse simulée doit revenir
    # à celle qu'on a demandée.
    assert charge["vitesse_moy_kmh"] == pytest.approx(30.0, abs=0.2)
    assert vitesse_a_plat_kmh(charge["puissance_w"], parametres) == pytest.approx(30.0, abs=0.01)


def test_la_vitesse_a_plat_depend_du_velo(tmp_path: Path):
    """La même vitesse ne coûte pas la même puissance sur deux jeux différents.

    C'est pourquoi `puissance_voulue` reçoit les paramètres au lieu de les
    relire : un chrono servi par « route amateur » et une route servie par le
    haut de la fourchette ne demandent pas les mêmes watts.
    """
    route = Parametres(100.0, litterature.ROUTE_AMATEUR_HAUT.cda_m2, litterature.ROUTE_AMATEUR_HAUT.crr)
    clm = Parametres(100.0, litterature.ROUTE_AMATEUR.cda_m2, litterature.ROUTE_AMATEUR.crr)
    demande = argparse.Namespace(puissance=None, vitesse_a_plat=30.0)
    assert puissance_voulue(demande.puissance, demande.vitesse_a_plat, route) > puissance_voulue(
        demande.puissance, demande.vitesse_a_plat, clm
    )


def test_les_deux_options_ensemble_sont_refusees_et_le_disent(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    with pytest.raises(ErreurUtilisateur, match="n'en donner qu'une"):
        executer_simuler(args_simuler(gpx=str(gpx), puissance=200.0, vitesse_a_plat=30.0), config)


def test_boucle_refuse_les_deux_options_avant_tout_appel(tmp_path: Path, monkeypatch):
    """Le refus coûte un message, pas douze appels BRouter.

    Les moteurs ne sont **pas** passés : si la commande les construisait, elle
    tenterait une vraie connexion — et le test échouerait au lieu de lever
    l'erreur attendue.
    """
    from ourouler.commandes.boucle import lire_options

    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="n'en donner qu'une"):
        lire_options(args(puissance=200.0, vitesse_a_plat=30.0), config)


def test_boucle_accepte_la_vitesse_a_plat(tmp_path: Path, monkeypatch, capsys):
    config = config_avec_velo_calibrable(tmp_path)
    monkeypatch.chdir(tmp_path)
    executer(
        args(velo=None, puissance=None, vitesse_a_plat=32.0, json=True),
        config,
        moteur_brouter(),
        moteur_meteo(),
    )
    charge = json.loads(capsys.readouterr().out)
    modele = charge["modele_physique"]
    parametres = Parametres(
        masse_totale_kg=modele["masse_totale_kg"],
        cda_m2=modele["cda_m2"],
        crr=modele["crr"],
    )
    assert modele["puissance_w"] == pytest.approx(puissance_a_plat_w(32.0, parametres))


def test_simuler_sans_aucune_des_deux_options_le_dit(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    with pytest.raises(ErreurUtilisateur, match="--vitesse-a-plat"):
        executer_simuler(args_simuler(gpx=str(gpx), puissance=None), config)


@pytest.mark.parametrize("vitesse", [0.0, -5.0, VITESSE_A_PLAT_MAXI_KMH + 1, float("nan")])
def test_une_vitesse_a_plat_absurde_est_refusee(tmp_path: Path, vitesse: float):
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")
    with pytest.raises(ErreurUtilisateur, match="vitesse-a-plat"):
        executer_simuler(args_simuler(gpx=str(gpx), puissance=None, vitesse_a_plat=vitesse), config)


def test_simuler_distingue_le_modele_calibre_du_modele_de_litterature(tmp_path: Path, capsys):
    """La mention est collée au temps, pas seulement en bas de l'écran."""
    config = config_de_test(tmp_path / "cache")
    gpx = gpx_plat(tmp_path / "boucle.gpx")

    executer_simuler(args_simuler(gpx=str(gpx)), config)
    assert "(modèle, littérature)" in capsys.readouterr().out

    ecrire_calibration(chemin_calibration(config), "RCR", CALIBRATION_ROUTE)
    executer_simuler(args_simuler(gpx=str(gpx)), config)
    texte = capsys.readouterr().out
    assert "de moyenne) (modèle)" in texte
    assert "littérature" not in texte


# --- ftp_defaut : le filet T5 de l'accueil (19/09/2026, [[Q65]] ouverte) -----


def test_ftp_defaut_proportionnelle_au_poids():
    from ourouler.physique.litterature import FTP_W_PAR_KG_DEFAUT, ftp_defaut

    assert ftp_defaut(80.0) == pytest.approx(80.0 * FTP_W_PAR_KG_DEFAUT)
    assert ftp_defaut(60.0) < ftp_defaut(90.0)


def test_ftp_defaut_ne_sort_jamais_des_bornes_de_config():
    """Les mêmes bornes que `config._nombre_optionnel(..., 50, 1000)` pour
    `cycliste.ftp_w` : un poids extrême ne doit jamais produire un chiffre
    que le chargement refuserait de reprendre."""
    from ourouler.physique.litterature import FTP_W_MAXI, FTP_W_MINI, ftp_defaut

    assert ftp_defaut(1.0) == FTP_W_MINI
    assert ftp_defaut(1000.0) == FTP_W_MAXI


# --- les pneus et la fourchette par défaut (L9.1) -----------------------------


def test_chaque_pneu_porte_un_crr_sourcé_et_plausible():
    from ourouler.physique.calibration import CRR_MAX, CRR_MIN

    for cle, pneu in litterature.PNEUS.items():
        assert pneu.cle == cle
        assert pneu.libelle and pneu.source
        assert CRR_MIN <= pneu.crr <= CRR_MAX


def test_les_pneus_sont_ranges_du_plus_rapide_au_plus_lent():
    """Ce que dit la table, et que le mainteneur a vérifié sur ses deux vélos :
    le tubeless roule mieux que le quatre saisons (note du 23/09)."""
    crr = [p.crr for p in litterature.PNEUS.values()]
    assert crr == sorted(crr)
    assert litterature.PNEUS["course_rapide"].crr == 0.005
    assert litterature.PNEUS["course_quatre_saisons"].crr == 0.006


def test_pour_pneu():
    assert litterature.pour_pneu("VTT").crr == 0.012
    assert litterature.pour_pneu(None) is None
    assert litterature.pour_pneu("") is None
    assert litterature.pour_pneu("pneu inventé") is None


def test_la_fourchette_par_defaut_enveloppe_les_deux_velos_mesures():
    """Les centiles mesurés le 25/09 sur les deux vélos du mainteneur (docstring
    du module) : la convention les contient tous les deux."""
    bas, mediane, haut = litterature.FOURCHETTE_PORTE_A_PORTE_DEFAUT
    mesures = [(1.021, 1.035, 1.099), (1.044, 1.086, 1.137)]
    assert bas <= min(m[0] for m in mesures)
    assert haut >= max(m[2] for m in mesures)
    assert bas < mediane < haut

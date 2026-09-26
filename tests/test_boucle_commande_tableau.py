"""`ourouler boucle` : le tableau imprimé et ses colonnes.

Le classement, la colonne des antennes, les routes connues et les poids
appris. Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from outils_boucle_commande import (
    _cellule,
    args,
    config_de_test,
    lignes_du_tableau,
    moteur_brouter,
    moteur_meteo,
)
from test_brouter import reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.rendu.boucle import (
    MARQUE_RETENUE,
    TITRE_ANTENNES_DETECTEES,
    TITRE_ANTENNES_RETIREES,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- le tableau ---------------------------------------------------------------


def test_le_tableau_montre_les_candidates_demandees(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = executer(args(candidates=3), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 3, sortie


def test_cinq_candidates_demandees_cinq_rendues_moteur_qui_ne_converge_pas(
    tmp_path: Path, monkeypatch, capsys
):
    """La commande donne au générateur un plafond d'appels à la hauteur de la demande.

    Sans cela, cinq directions demandées en rendaient trois dès que le moteur
    n'atteignait pas la distance voulue — et l'utilisateur ne voyait que le
    tableau, pas la raison.
    """
    monkeypatch.chdir(tmp_path)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        # 50 km quel que soit le rayon demandé : chaque azimut épuise ses
        # ajustements sans jamais entrer dans la tolérance.
        charge = reponse_fabriquee()
        charge["features"][0]["properties"]["track-length"] = "50000"
        return httpx.Response(200, json=charge)

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    code = executer(args(candidates=5), config_de_test(), brouter, moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert len(lignes_du_tableau(sortie)) == 5, sortie


def test_les_colonnes_du_contrat_sont_toutes_la(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo(pluie=0.5))
    sortie = capsys.readouterr().out
    for titre in (
        "n°", "distance", "D+", "temps", "trafic", "non revêtu",
        TITRE_ANTENNES_RETIREES, "virages G", "sens",
    ):
        assert titre in sortie
    for titre in ("pluie", "vent face", "ressenti min"):
        assert titre in sortie


def test_le_tableau_est_trie_par_score_plus_pluie(tmp_path: Path, monkeypatch, capsys):
    """La meilleure candidate est en tête, et le n° 1 porte la marque."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    lignes = lignes_du_tableau(sortie)
    assert lignes[0].startswith(MARQUE_RETENUE), sortie
    assert lignes[0].split()[1] == "1"
    assert not any(ligne.startswith(MARQUE_RETENUE) for ligne in lignes[1:])
    assert f"{MARQUE_RETENUE} retenue : n° 1" in sortie


def test_le_tri_suit_bien_le_total_annonce(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(pluie=0.4))
    charge = json.loads(capsys.readouterr().out)
    totaux = [c["total_tri"] for c in charge["candidates"]]
    assert totaux == sorted(totaux)
    for candidate in charge["candidates"]:
        attendu = candidate["couts"]["score"] + candidate["meteo"]["pluie_cumulee_mm"] * 2
        # Les trois nombres sont arrondis au millième **chacun** dans le JSON,
        # et la pluie est ensuite doublée : recomposer la somme à partir d'eux
        # laisse jusqu'à 2,5 millièmes d'écart. La tolérance d'origine, 1e-3,
        # tenait par chance sur les valeurs d'alors.
        assert candidate["total_tri"] == pytest.approx(attendu, abs=3e-3)


def test_le_temps_estime_vient_du_modele_meme_sans_calibration(
    tmp_path: Path, monkeypatch, capsys
):
    """Le défaut du 18/09/2026, à l'envers : une configuration nue donne un modèle.

    Avant ce lot, une configuration sans `calibration.json` retombait sur
    `vitesse_moyenne_kmh` — 27 km/h, une constante que ni la FTP ni le vélo ne
    déplaçaient. Elle reçoit maintenant les paramètres de littérature de sa
    catégorie, et le temps dépend donc du terrain et de la puissance.
    """
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    candidate = charge["candidates"][0]
    a_27 = candidate["distance_km"] / 27.0 * 3600
    assert candidate["temps_source"] == "modele"
    assert candidate["temps_estime_s"] != pytest.approx(a_27, abs=1)
    assert charge["modele_physique"]["provenance"] == "littérature"
    assert charge["modele_physique"]["mesure"] is False


# --- colonne des antennes -------------------------------------------------------


def moteur_brouter_avec_antenne() -> ClientBrouter:
    """BRouter bouchonné dont chaque boucle porte un cul-de-sac de 150 m aller-retour."""
    from test_boucle_candidates import anneau_avec_antenne

    points = anneau_avec_antenne()

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        entite = charge["features"][0]
        entite["geometry"]["coordinates"] = points
        entite["properties"]["messages"] = []
        entite["properties"].pop("track-length", None)
        return httpx.Response(200, json=charge)

    params = config_de_test().brouter
    return ClientBrouter(params, http=httpx.Client(transport=httpx.MockTransport(gestionnaire)))


def test_la_colonne_antennes_compte_les_metres_retires(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    lignes = capsys.readouterr().out.splitlines()
    entete = next(ligne for ligne in lignes if TITRE_ANTENNES_RETIREES in ligne)
    assert TITRE_ANTENNES_DETECTEES not in entete
    assert 270 <= _cellule(lignes, entete, TITRE_ANTENNES_RETIREES) <= 330


def test_le_json_porte_les_antennes_retirees(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1, json=True),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["couts"]["antennes_m"] == pytest.approx(300, abs=30)
    assert candidate["antennes"]["nombre"] == 1
    assert candidate["distance_source"] == "recalculee"
    assert candidate["meta"]["denivele_approximatif"] is True


def test_sans_antenne_la_colonne_affiche_zero(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["couts"]["antennes_m"] == 0.0
    assert candidate["antennes"] == {"nombre": 0, "metres_retires": 0.0}
    assert candidate["distance_source"] is None


def test_un_gpx_importe_dit_antennes_detectees_et_non_retirees(
    tmp_path: Path, monkeypatch, capsys
):
    """Un GPX n'est pas élagué : ses antennes sont encore là, le titre le dit."""
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    gpx = next(tmp_path.glob("*.gpx"))
    capsys.readouterr()

    executer(
        args(gpx=str(gpx), distance=None), config_de_test(), moteur_brouter_avec_antenne(), moteur_meteo()
    )
    lignes = capsys.readouterr().out.splitlines()
    entete = next(ligne for ligne in lignes if TITRE_ANTENNES_DETECTEES in ligne)
    assert TITRE_ANTENNES_RETIREES not in entete
    # Le GPX écrit vient d'une candidate déjà élaguée : il n'a plus d'antenne.
    assert _cellule(lignes, entete, TITRE_ANTENNES_DETECTEES) == 0.0


def test_le_json_nomme_la_provenance_des_metres_d_antennes(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    executer(
        args(distance=7.0, candidates=1, json=True),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    assert json.loads(capsys.readouterr().out)["candidates"][0]["antennes_source"] == "retirees"

    gpx = next(tmp_path.glob("*.gpx"))
    executer(
        args(gpx=str(gpx), distance=None, json=True),
        config_de_test(),
        moteur_brouter_avec_antenne(),
        moteur_meteo(),
    )
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["antennes_source"] == "detectees"
    assert candidate["antennes"] is None

# --- routes connues et poids appris ---------------------------------------------
#
# `boucle` lit deux fichiers appris dans le dossier de cache — `poids_routes.json`
# et `routes_connues.sqlite` — et passe leur contenu au cœur en objets. La
# colonne « connu % » est **informative** : elle ne doit jamais peser sur le tri.


def config_avec_cache(tmp_path: Path) -> Config:
    return config_de_test(cache={"dossier": str(tmp_path / "cache")})


def base_de_routes(tmp_path: Path, trace) -> None:
    """Apprend un tracé dans la base du cache de test."""
    from datetime import date

    from ourouler.apprentissage.commande import NOM_BASE
    from ourouler.apprentissage.routes import BaseRoutes

    BaseRoutes(tmp_path / "cache" / NOM_BASE).ajouter_trace(
        trace, jour=date(2024, 3, 4), id_sortie="sortie-de-test"
    )


def ecrire_poids_de_test(tmp_path: Path, poids: dict) -> None:
    from ourouler.apprentissage.commande import NOM_POIDS
    from ourouler.apprentissage.routes import ecrire_poids

    ecrire_poids(tmp_path / "cache" / NOM_POIDS, poids)


def test_sans_fichiers_appris_les_colonnes_apprises_disparaissent(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" not in titres, "sans base de routes, la colonne connu % disparaît"
    assert "valeurs par défaut" in sortie


def test_la_colonne_cout_profil_apparait_des_que_le_moteur_le_donne(
    tmp_path: Path, monkeypatch, capsys
):
    """La fixture BRouter porte `CostPerKm` : la colonne doit être là."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "coût profil" in titres
    assert "1200" in sortie


def test_la_colonne_connu_apparait_avec_une_base(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    client = moteur_brouter()
    trace = client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=12_000)
    base_de_routes(tmp_path, trace)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" in titres
    assert "100 %" in sortie, "le tracé appris est reconnu à 100 %"
    assert "informatif, jamais dans le score" in sortie


def test_la_part_connue_n_entre_pas_dans_le_tri(tmp_path: Path, monkeypatch, capsys):
    """Le score doit être identique avec et sans base de routes."""
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sans = json.loads(capsys.readouterr().out)

    client = moteur_brouter()
    base_de_routes(tmp_path, client.boucle((0.0, 0.0), azimut_deg=45, rayon_m=12_000))
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    avec = json.loads(capsys.readouterr().out)

    assert [c["total_tri"] for c in avec["candidates"]] == [
        c["total_tri"] for c in sans["candidates"]
    ]
    assert avec["candidates"][0]["part_connue"] == pytest.approx(1.0, abs=0.01)
    assert sans["candidates"][0]["part_connue"] is None


def test_les_poids_appris_changent_le_score(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    defaut = json.loads(capsys.readouterr().out)
    assert defaut["poids_routes"] is None

    ecrire_poids_de_test(tmp_path, {"primary": 0.0, "secondary": 0.0, "trunk": 0.0})
    executer(args(json=True), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    appris = json.loads(capsys.readouterr().out)

    assert appris["poids_routes"] == {"primary": 0.0, "secondary": 0.0, "trunk": 0.0}
    assert appris["candidates"][0]["couts"]["score"] < defaut["candidates"][0]["couts"]["score"]


def test_l_entete_dit_d_ou_viennent_les_poids(tmp_path: Path, monkeypatch, capsys):
    """Et cite les classes **présentes dans le tableau**, pas les plus pénalisées.

    Citer les plus pénalisées donnait une ligne vraie mais inutile
    (« primary_link 4,0 ») : ces classes ne font pas cinquante mètres du tracé.
    """
    monkeypatch.chdir(tmp_path)
    ecrire_poids_de_test(tmp_path, {"secondary": 1.5, "trunk_link": 4.0})
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert "appris sur vos sorties" in sortie
    assert "secondary 1,5" in sortie, "la fixture porte de la secondary : elle doit être citée"
    assert "trunk_link" not in sortie, "une classe absente du tracé n'a rien à faire là"


def test_un_fichier_de_poids_abime_ne_fait_pas_perdre_la_boucle(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "poids_routes.json").write_text("{tronqué", encoding="utf-8")
    assert executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo()) == 0
    assert "valeurs par défaut" in capsys.readouterr().out


def test_une_base_de_routes_abimee_ne_fait_pas_perdre_la_boucle(
    tmp_path: Path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "routes_connues.sqlite").write_bytes(b"pas une base" * 50)
    assert executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo()) == 0
    sortie = capsys.readouterr().out
    titres = next(ligne for ligne in sortie.splitlines() if "n°" in ligne and "distance" in ligne)
    assert "connu %" not in titres


def test_boucle_ne_cree_pas_de_base_de_routes(tmp_path: Path, monkeypatch, capsys):
    """Afficher une colonne informative ne justifie pas d'écrire dans le cache."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_avec_cache(tmp_path), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    assert not (tmp_path / "cache" / "routes_connues.sqlite").exists()

"""`ourouler boucle` : ce qu'elle lit en entrée.

La direction demandée, les erreurs de saisie relevées avant tout appel
réseau, `--pause`, et l'enregistrement de la sous-commande dans la CLI.
Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from outils_boucle_commande import (
    CONFIG_BRUTE,
    CONFIG_TOML,
    args,
    config_de_test,
    gpx_de_test,
    moteur_brouter,
    moteur_meteo,
)

from ourouler.cli import construire_parseur, main
from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.commandes.boucle import lire_options
from ourouler.config import depuis_dict
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.services.boucle import (
    direction_en_azimut,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- la direction -------------------------------------------------------------


@pytest.mark.parametrize(
    ("texte", "attendu"),
    [("N", 0.0), ("NE", 45.0), ("E", 90.0), ("NO", 315.0), ("ne", 45.0), ("NNE", 22.5)],
)
def test_une_direction_nommee_devient_un_azimut(texte: str, attendu: float):
    libelle, azimut = direction_en_azimut(texte)
    assert azimut == pytest.approx(attendu)
    assert libelle == texte.upper()


@pytest.mark.parametrize(("texte", "attendu"), [("45", 45.0), ("45°", 45.0), ("0", 0.0), ("370", 10.0)])
def test_un_azimut_en_degres_est_accepte(texte: str, attendu: float):
    assert direction_en_azimut(texte)[1] == pytest.approx(attendu)


def test_la_notation_anglaise_du_ouest_est_toleree():
    assert direction_en_azimut("NW")[1] == pytest.approx(315.0)


@pytest.mark.parametrize("mauvais", ["", "   ", "nord-est", "XY", "nan", "inf"])
def test_une_direction_illisible_est_refusee(mauvais: str):
    with pytest.raises(ErreurUtilisateur, match="direction"):
        direction_en_azimut(mauvais)


# --- erreurs utilisateur, avant tout appel réseau -----------------------------


def test_sans_distance_ni_gpx_erreur_utilisateur():
    with pytest.raises(ErreurUtilisateur, match="--distance"):
        lire_options(args(distance=None), config_de_test())


def test_sans_direction_ni_gpx_la_demande_balaie_tout_l_horizon():
    """Q47 : ce n'était pas un choix de conception, `boucle` n'avait jamais appris à balayer.

    `sortie` (avec séance) balaie déjà les huit directions quand rien n'est
    demandé ; `boucle` (sortie libre) refusait — « --direction … est
    obligatoire » — alors que rien ne le justifiait. Sans direction, la
    demande doit maintenant se construire comme `sortie` le fait : un
    libellé vide, aucun azimut fixé, à charge pour la génération de
    balayer.
    """
    demande = lire_options(args(direction=None), config_de_test())
    assert demande.direction == ""
    assert demande.azimut_deg is None


def test_sans_direction_l_execution_bout_en_bout_balaie_les_azimuts(tmp_path, monkeypatch, capsys):
    """Q47, vérifié en bout en bout : le refus disparaît, et les candidates
    sont réparties sur l'horizon plutôt qu'entassées sur un seul azimut —
    exactement le défaut que `boucle.candidates.azimuts` (±20°, ±40°…)
    aurait produit avec un seul appel.
    """
    monkeypatch.chdir(tmp_path)
    config = config_de_test(boucle={"vitesse_moyenne_kmh": 27.0, "sens": "horaire", "candidates": 3})
    code = executer(args(direction=None, json=True), config, moteur_brouter(), moteur_meteo())
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    azimuts = sorted(c["azimut_deg"] for c in charge["candidates"])
    assert len(azimuts) == 3
    # `pas = 360 / 3 = 120°` : les trois candidates doivent se répartir aux
    # trois azimuts, pas s'entasser sur un seul.
    assert azimuts == pytest.approx([0.0, 120.0, 240.0])
    assert charge["demande"]["direction"] is None
    assert charge["demande"]["azimut_deg"] is None


@pytest.mark.parametrize("distance", [0.0, -10.0])
def test_une_distance_nulle_ou_negative_est_refusee(distance: float):
    with pytest.raises(ErreurUtilisateur, match="--distance"):
        lire_options(args(distance=distance), config_de_test())


def test_brouter_non_renseigne_est_refuse_avant_tout_appel():
    config = depuis_dict({k: v for k, v in CONFIG_BRUTE.items() if k != "brouter"})
    with pytest.raises(ErreurUtilisateur, match="brouter"):
        lire_options(args(), config)


# --- --pause : lu, validé avant tout appel réseau -----------------------------


def test_une_pause_valide_est_portee_par_la_demande():
    demande = lire_options(args(pause=["10:0h45"]), config_de_test())
    assert len(demande.pauses) == 1
    assert demande.pauses[0].dist_m == pytest.approx(10_000.0)
    assert demande.pauses[0].duree_s == pytest.approx(45 * 60.0)


def test_pause_est_repetable():
    demande = lire_options(args(pause=["10:0h45", "40:4h30"]), config_de_test())
    assert [p.dist_m for p in demande.pauses] == pytest.approx([10_000.0, 40_000.0])


def test_sans_pause_la_demande_en_porte_aucune():
    assert lire_options(args(), config_de_test()).pauses == ()


def test_une_pause_a_kilometre_negatif_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="kilomètre"):
        lire_options(args(pause=["-5:0h45"]), config_de_test())


def test_une_pause_a_duree_nulle_est_refusee():
    with pytest.raises(ErreurUtilisateur, match="durée"):
        lire_options(args(pause=["10:0h0"]), config_de_test())


def test_deux_pauses_au_meme_kilometre_sont_refusees():
    with pytest.raises(ErreurUtilisateur, match="même kilomètre"):
        lire_options(args(pause=["10:0h45", "10:1h00"]), config_de_test())


def test_une_pause_au_dela_de_la_distance_demandee_est_refusee():
    """`--distance 60` : une pause à 70 km est une erreur d'entrée, pas un no-op silencieux."""
    with pytest.raises(ErreurUtilisateur, match="au-delà"):
        lire_options(args(distance=60.0, pause=["70:0h45"]), config_de_test())


def test_une_pause_dans_la_distance_demandee_est_acceptee():
    demande = lire_options(args(distance=60.0, pause=["59:0h45"]), config_de_test())
    assert len(demande.pauses) == 1


def test_une_pause_au_dela_du_gpx_importe_est_refusee(tmp_path: Path, monkeypatch):
    """Sans `--distance` (mode `--gpx`), le refus attend la lecture du tracé importé."""
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    with pytest.raises(ErreurUtilisateur, match="au-delà"):
        executer(
            args(gpx=str(chemin), pause=["1000:0h45"]),
            config_de_test(),
            moteur_brouter(),
            moteur_meteo(),
        )


def test_un_gpx_introuvable_est_refuse(tmp_path: Path):
    with pytest.raises(ErreurUtilisateur, match="introuvable"):
        lire_options(args(gpx=str(tmp_path / "absent.gpx")), config_de_test())


def test_un_gpx_illisible_est_refuse(tmp_path: Path):
    fichier = tmp_path / "casse.gpx"
    fichier.write_text("ceci n'est pas du GPX", encoding="utf-8")
    with pytest.raises(ErreurUtilisateur, match="GPX"):
        executer(args(gpx=str(fichier)), config_de_test(), moteur_brouter(), moteur_meteo())


def test_les_erreurs_sortent_en_code_2_par_la_cli(tmp_path: Path, capsys):
    """Bout en bout : aucun client injecté, donc l'erreur doit tomber avant le réseau."""
    fichier = tmp_path / "c.toml"
    fichier.write_text(CONFIG_TOML, encoding="utf-8")
    assert main(["--config", str(fichier), "boucle", "--direction", "NE"]) == 2
    assert "--distance" in capsys.readouterr().err


def test_brouter_non_renseigne_sort_en_code_2_par_la_cli(tmp_path: Path, capsys):
    fichier = tmp_path / "c.toml"
    fichier.write_text(CONFIG_TOML, encoding="utf-8")
    code = main(["--config", str(fichier), "boucle", "--distance", "60", "--direction", "NE"])
    assert code == 2
    assert "brouter" in capsys.readouterr().err


# --- l'enregistrement dans la CLI ---------------------------------------------


def test_la_sous_commande_est_enregistree_et_accepte_json_apres():
    parseur = construire_parseur()
    args_ = parseur.parse_args(["boucle", "--distance", "60", "--direction", "NE", "--json"])
    assert args_.commande == "boucle"
    assert args_.json is True
    assert args_.distance == 60.0 and args_.direction == "NE"


def test_json_global_avant_la_sous_commande_boucle():
    assert construire_parseur().parse_args(["--json", "boucle"]).json is True


def test_pause_est_enregistree_et_repetable_dans_le_parseur():
    args_ = construire_parseur().parse_args(
        ["boucle", "--distance", "60", "--pause", "10:0h45", "--pause", "40:4h30"]
    )
    assert args_.pause == ["10:0h45", "40:4h30"]


def test_pause_absente_vaut_none_dans_le_parseur():
    assert construire_parseur().parse_args(["boucle", "--distance", "60"]).pause is None

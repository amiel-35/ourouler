"""`ourouler sortie` : ce qu'elle refuse ou accepte en entrée.

Erreurs de saisie relevées avant tout appel réseau, journée sans séance,
séance lue dans un fichier (`--fichier-seance`), date lointaine servie sans
météo. Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from outils_sortie_commande import (
    CONFIG_BRUTE,
    JOUR,
    args,
    client_intervals,
    clients_interdits,
    config_de_test,
    lancer,
    moteur_meteo,
)
from test_seance_intervals import ATHLETE, CLE

from ourouler.cli import construire_parseur, main
from ourouler.commandes.sortie import executer_depuis_namespace as executer
from ourouler.commandes.sortie import lire_options
from ourouler.config import (
    HORIZON_JOURS_DEFAUT,
    depuis_dict,
)
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.sortie.commande import (
    _seance,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- erreurs utilisateur, avant tout appel réseau -----------------------------


@pytest.mark.parametrize(
    ("champs", "motif"),
    [
        ({"distance": -5.0}, "--distance"),
        ({"distance": 0.0}, "--distance"),
        ({"direction": "nord-est"}, "direction"),
        ({"candidates": 0}, "--candidates"),
        ({"jour": "2026-02-31"}, "--jour"),
        ({"velo": "Tandem"}, "Tandem"),
    ],
)
def test_une_option_fautive_est_refusee_avant_tout_appel(
    tmp_path: Path, monkeypatch, champs: dict, motif: str
):
    monkeypatch.chdir(tmp_path)
    brouter, meteo, intervals = clients_interdits()
    with pytest.raises(ErreurUtilisateur, match=re.escape(motif)):
        executer(args(**champs), config_de_test(tmp_path / "cache"), brouter, meteo, intervals)


def test_brouter_non_renseigne_est_refuse_avant_tout_appel(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = depuis_dict(
        {k: v for k, v in CONFIG_BRUTE.items() if k != "brouter"}
        | {"cache": {"dossier": str(tmp_path / "cache")}}
    )
    with pytest.raises(ErreurUtilisateur, match="brouter"):
        lire_options(args(), config)


def test_un_dossier_de_sortie_inexistant_est_refuse(tmp_path: Path):
    with pytest.raises(ErreurUtilisateur, match="n'existe pas"):
        lire_options(
            args(sortie=str(tmp_path / "absent" / "s.gpx")), config_de_test(tmp_path / "cache")
        )


def test_un_fichier_existant_n_est_pas_ecrase_sans_ecraser(tmp_path: Path):
    cible = tmp_path / "deja.gpx"
    cible.write_text("<gpx/>", encoding="utf-8")
    with pytest.raises(ErreurUtilisateur, match="existe déjà"):
        lire_options(args(sortie=str(cible)), config_de_test(tmp_path / "cache"))
    # Avec --ecraser, la même demande passe.
    assert lire_options(
        args(sortie=str(cible), ecraser=True), config_de_test(tmp_path / "cache")
    ).sortie == cible


def test_les_erreurs_sortent_en_code_2_par_la_cli(tmp_path: Path, capsys):
    fichier = tmp_path / "c.toml"
    fichier.write_text(
        "[depart]\nnom = 'Point zéro'\nlatitude = 0.0\nlongitude = 0.0\n"
        "[cycliste]\nmasse_kg = 80\nftp_w = 250\n",
        encoding="utf-8",
    )
    code = main(["--config", str(fichier), "sortie", "--jour", "2026-09-08"])
    assert code == 2
    assert "brouter" in capsys.readouterr().err


def test_la_sous_commande_est_declaree_dans_la_cli():
    parseur = construire_parseur()
    lus = parseur.parse_args(["sortie", "--jour", "2026-09-08", "--carte", "c.html", "--json"])
    assert lus.commande == "sortie"
    assert lus.carte == "c.html"
    assert lus.json is True


def test_carte_sans_seance_absente_par_defaut_et_activable():
    parseur = construire_parseur()
    assert parseur.parse_args(["sortie", "--jour", "2026-09-08"]).carte_sans_seance is False
    lus = parseur.parse_args(["sortie", "--jour", "2026-09-08", "--carte-sans-seance"])
    assert lus.carte_sans_seance is True


# --- aucune séance ------------------------------------------------------------


def test_sans_seance_ce_jour_la_message_clair_et_code_0(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, intervals=client_intervals([]))
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Aucune séance" in sortie
    assert not list(tmp_path.glob("*.gpx"))
    assert not list(tmp_path.glob("*.html"))


def test_sans_seance_le_json_le_dit(tmp_path: Path, monkeypatch, capsys):
    code = lancer(tmp_path, monkeypatch, intervals=client_intervals([]), json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["seance"] is None
    assert charge["candidates"] == []
    assert charge["carte"] is None, "--carte-sans-seance absent : rien n'est écrit"


def test_sans_seance_et_carte_sans_seance_ecrit_une_page(tmp_path: Path, monkeypatch, capsys):
    """Contrat de l'hébergé minimal, périmètre point 4 : le service planifié
    doit produire une page, jamais rien ni une erreur, un jour sans séance."""
    code = lancer(
        tmp_path, monkeypatch, intervals=client_intervals([]), carte_sans_seance=True
    )
    sortie = capsys.readouterr().out
    assert code == 0
    pages = list((tmp_path / "cache" / "sorties").glob("*.html"))
    assert len(pages) == 1
    contenu = pages[0].read_text(encoding="utf-8")
    assert "Rien de prévu" in contenu
    assert JOUR.isoformat() in contenu
    assert not list((tmp_path / "cache" / "sorties").glob("*.gpx")), "rien à rouler, pas de GPX"
    assert str(pages[0]) in sortie


def test_sans_seance_et_carte_sans_seance_le_json_donne_le_chemin(tmp_path: Path, monkeypatch, capsys):
    code = lancer(
        tmp_path,
        monkeypatch,
        intervals=client_intervals([]),
        carte_sans_seance=True,
        json=True,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert charge["seance"] is None
    assert charge["carte"] is not None
    assert Path(charge["carte"]).is_file()


def test_sans_seance_et_carte_sans_seance_respecte_loption_carte(tmp_path: Path, monkeypatch):
    code = lancer(
        tmp_path,
        monkeypatch,
        intervals=client_intervals([]),
        carte_sans_seance=True,
        carte=str(tmp_path / "ma_page.html"),
    )
    assert code == 0
    assert (tmp_path / "ma_page.html").is_file()


# --- --fichier-seance (F1, C1 de docs/journal/ux/relecture_f0.md) ---------------------

ZWO_SORTIE_FABRIQUE = (
    "<?xml version='1.0'?>\n<workout_file>\n<name>Séance fichier fabriquée</name>\n"
    '<workout><SteadyState Duration="1200" Power="1.0"/></workout>\n'
    "</workout_file>\n"
)


def _ecrire_zwo_sortie(tmp_path: Path) -> Path:
    chemin = tmp_path / "seance.zwo"
    chemin.write_text(ZWO_SORTIE_FABRIQUE, encoding="utf-8")
    return chemin


def refus_intervals() -> ClientIntervals:
    """Un client Intervals qui fait échouer le test dès qu'on le sollicite."""

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        raise AssertionError("Intervals.icu appelé alors qu'un fichier de séance était donné")

    return ClientIntervals(
        ATHLETE, CLE, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )


def test_lire_options_porte_le_fichier_de_la_demande(tmp_path: Path):
    chemin = _ecrire_zwo_sortie(tmp_path)
    demande = lire_options(args(fichier_seance=str(chemin)), config_de_test(tmp_path / "cache"))
    assert demande.fichier == chemin


def test_sans_option_le_fichier_de_la_demande_est_absent(tmp_path: Path):
    demande = lire_options(args(), config_de_test(tmp_path / "cache"))
    assert demande.fichier is None


def test_seance_avec_fichier_ne_touche_jamais_intervals(tmp_path: Path):
    chemin = _ecrire_zwo_sortie(tmp_path)
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(fichier_seance=str(chemin)), config)
    seance = _seance(demande, config, refus_intervals())
    assert seance is not None
    assert seance.meta["source"] == "zwo"
    assert seance.jour == demande.jour


def test_seance_avec_fichier_marche_meme_sans_client_donne(tmp_path: Path):
    """`client=None` construit normalement un `ClientIntervals` depuis la config —
    avec un fichier, cette branche n'est jamais atteinte."""
    chemin = _ecrire_zwo_sortie(tmp_path)
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(fichier_seance=str(chemin)), config)
    seance = _seance(demande, config, None)
    assert seance is not None


def test_seance_sans_fichier_utilise_toujours_intervals(tmp_path: Path):
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(), config)
    seance = _seance(demande, config, client_intervals())
    assert seance is not None
    assert seance.nom == "4x8 fabriquée"


def test_fichier_seance_bout_en_bout_remplace_intervals(tmp_path: Path, monkeypatch):
    """Preuve de bout en bout via `executer` : la recherche de parcours tourne
    sur une séance de fichier sans jamais appeler Intervals.icu."""
    chemin = _ecrire_zwo_sortie(tmp_path)
    # `distance=34.0` : la séance du .ZWO vaut environ 15 km, alors que l'anneau
    # bouchonné en fait 33,9 quel que soit le rayon. Depuis Q41 (d), un tel
    # écart (+126 %) est refusé au lieu d'être servi en silence — la boucle ne
    # serait donc jamais construite, et le sujet du test (la séance vient d'un
    # fichier, Intervals n'est jamais appelé) ne serait plus atteignable. La
    # distance n'a jamais été son sujet ; on la fixe pour ne pas la subir.
    code = lancer(
        tmp_path,
        monkeypatch,
        fichier_seance=str(chemin),
        intervals=refus_intervals(),
        distance=34.0,
    )
    assert code == 0


# --- Q40 (a) : une date lointaine est servie, sans météo -----------------------


def test_une_date_lointaine_est_servie_sans_appeler_open_meteo(
    tmp_path: Path, monkeypatch, capsys
):
    """Q40 (a) : « si on demande trop loin, ben pas de météo » — et direct.

    Le client météo interdit fait échouer le test au premier appel : demander
    ~150 prévisions pour récolter des blocs vides serait payer le service pour
    apprendre ce que la date disait déjà.
    """
    _, meteo_interdite, _ = clients_interdits()
    lointain = date.today() + timedelta(days=HORIZON_JOURS_DEFAUT + 30)
    code = lancer(
        tmp_path,
        monkeypatch,
        meteo=meteo_interdite,
        jour=lointain.isoformat(),
        json=True,
    )
    lu = capsys.readouterr()
    charge = json.loads(lu.out)
    assert code == 0, "le parcours est servi, la date n'est pas refusée"
    assert charge["candidates"], "la boucle reste là : c'est la météo qui disparaît"
    absente = charge["meteo_absente"]
    assert absente["jour"] == lointain.isoformat()
    assert absente["dernier_jour_couvert"] == (
        date.today() + timedelta(days=HORIZON_JOURS_DEFAUT)
    ).isoformat()
    assert "pas de météo" in absente["message"]
    assert "s'arrêtent" in absente["message"], "le message dit jusqu'où vont les prévisions"
    assert "pas de météo" in lu.err


def test_une_date_lointaine_ne_promet_ni_pluie_ni_vent_ni_tenue(
    tmp_path: Path, monkeypatch, capsys
):
    """E14 · dégradé : ce qui disparaît sont les affirmations qu'on ne soutient plus."""
    _, meteo_interdite, _ = clients_interdits()
    lointain = date.today() + timedelta(days=HORIZON_JOURS_DEFAUT + 30)
    lancer(
        tmp_path, monkeypatch, meteo=meteo_interdite, jour=lointain.isoformat(), json=True
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["tenue"] is None
    assert charge["modele_meteo"] is None
    assert all(c["meteo"] is None for c in charge["candidates"])
    assert charge["question_vent"]["posee"] is False


def test_une_meteo_en_panne_dans_l_horizon_ne_promet_pas_une_fin_de_previsions(
    tmp_path: Path, monkeypatch, capsys
):
    """Le même écran, l'autre cause — et la phrase ne dit toujours pas pourquoi."""
    lancer(tmp_path, monkeypatch, meteo=moteur_meteo(en_panne=True), json=True)
    charge = json.loads(capsys.readouterr().out)
    absente = charge["meteo_absente"]
    assert absente["jour"] == JOUR.isoformat()
    assert "s'arrêtent" not in absente["message"], (
        "les prévisions couvrent ce jour-là : elles n'ont rien rendu, ce n'est pas la même chose"
    )


def test_la_meteo_repond_dans_l_horizon(tmp_path: Path, monkeypatch, capsys):
    """Contre-épreuve : tant qu'on est dans l'horizon, rien ne change."""
    lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert charge["meteo_absente"] is None
    assert charge["candidates"][0]["meteo"] is not None

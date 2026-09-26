"""`ourouler sortie` : les fichiers écrits (GPX, carte), et leur choix.

Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from outils_sortie_commande import (
    JOUR,
    RELIEFS_CONTRASTES,
    args,
    client_intervals,
    config_de_test,
    ecrire_calibration,
    lancer,
    moteur_brouter,
    moteur_meteo,
    pluie_au_nord,
)

from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.commandes.sortie import executer_depuis_namespace as executer

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- les fichiers écrits -------------------------------------------------------


def test_le_gpx_et_la_carte_sont_ecrits_hors_du_dossier_courant(
    tmp_path: Path, monkeypatch, capsys
):
    """Q23 : par défaut, les fichiers produits ne vont plus dans le dossier courant.

    Avant ce correctif, ce test s'appelait
    `..._sont_ecrits_dans_le_dossier_courant` et vérifiait exactement ce
    défaut : sans `--sortie` ni `--carte`, les fichiers atterrissaient dans
    le répertoire courant, donc le dépôt quand la commande y est lancée
    depuis là. Ils vivent maintenant sous le dossier de cache configuré
    (`config.cache.dossier / "sorties"`), et le dossier courant ne doit plus
    en porter aucun.
    """
    code = lancer(tmp_path, monkeypatch)
    sortie = capsys.readouterr().out
    assert code == 0
    gpx = tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.gpx"
    carte = tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.html"
    assert gpx.is_file() and carte.is_file()
    assert not list(tmp_path.glob("*.gpx")) and not list(tmp_path.glob("*.html")), (
        "le dossier courant ne doit porter aucun fichier produit par défaut (Q23)"
    )
    assert str(gpx) in sortie and str(carte) in sortie, "le chemin complet doit être dit en clair"
    assert gpx.read_text(encoding="utf-8").startswith("<?xml")


def test_le_gpx_ecrit_est_le_parcours_place(tmp_path: Path, monkeypatch, capsys):
    """Défaut mesuré le 22/04 : le fichier envoyé au compteur ignorait le placement.

    Ici la séance tient sur l'anneau sans demi-tour, donc parcours et boucle se
    confondent — ce que le fichier doit dire, c'est la distance **placée** et
    combien de demi-tours il contient.
    """
    code = lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    place = charge["candidates"][0]["placement"]
    texte = (tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.gpx").read_text(
        encoding="utf-8"
    )
    relu = lire_gpx_trace(texte.encode("utf-8"))
    assert relu.distance_m == pytest.approx(place["distance_totale_m"], rel=0.01)
    assert "sans demi-tour" in texte, texte[:400]


# --- aucun GPX à la génération, un GPX au choix (Q40 g) ------------------------


def test_recueil_gpx_n_ecrit_aucun_fichier_et_rend_les_trois_traces(
    tmp_path: Path, monkeypatch, capsys
):
    """Q40 (g) : « aucun GPX à la génération, et on le fait à la demande. »

    Les trois propositions sont contrastées exprès ; n'écrire que celle du
    classement, c'était envoyer la mauvaise trace au compteur à qui
    choisissait « la plus sèche ». Écrire les trois, c'était en jeter deux.
    """
    recueillis: list = []
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    code = executer(
        args(json=True, candidates=4),
        config_de_test(tmp_path / "cache"),
        moteur_brouter(RELIEFS_CONTRASTES),
        moteur_meteo(pluie=pluie_au_nord),
        client_intervals(),
        recueil_gpx=recueillis.extend,
    )
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert not list((tmp_path / "cache" / "sorties").glob("*.gpx")), (
        "aucun GPX ne doit être écrit quand l'appelant les recueille"
    )
    assert charge["gpx"] is None, "le JSON ne doit pas annoncer un fichier qui n'existe pas"
    assert len(recueillis) >= 2, (
        "le bouchon ne contraste plus rien : sans deux propositions, ce test ne prouve rien"
    )
    numeros = [g.numero for g in recueillis]
    assert numeros == [p["numero"] for p in charge["propositions"]]
    assert len({g.texte for g in recueillis}) == len(recueillis), (
        "deux propositions contrastées ne peuvent pas rendre le même GPX"
    )
    for gpx in recueillis:
        assert gpx.nom_fichier.endswith(f"_n{gpx.numero}.gpx")
        assert lire_gpx_trace(gpx.texte.encode("utf-8")).points


def test_sans_recueil_la_ligne_de_commande_ecrit_toujours_son_gpx(
    tmp_path: Path, monkeypatch, capsys
):
    """La ligne de commande ne change pas : `--sortie` (ou le nom daté) est écrit."""
    demande = tmp_path / "choisi.gpx"
    code = lancer(tmp_path, monkeypatch, json=True, sortie=str(demande))
    charge = json.loads(capsys.readouterr().out)
    assert code == 0
    assert demande.is_file() and demande.read_text(encoding="utf-8").startswith("<?xml")
    assert charge["gpx"] == str(demande)


def test_la_carte_embarque_les_memes_gpx_que_le_recueil(tmp_path: Path, monkeypatch, capsys):
    """Un seul calcul pour deux usages : la page du jour et l'appelant lisent la même trace."""
    recueillis: list = []
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")
    executer(
        args(json=True, candidates=4),
        config_de_test(tmp_path / "cache"),
        moteur_brouter(RELIEFS_CONTRASTES),
        moteur_meteo(pluie=pluie_au_nord),
        client_intervals(),
        recueil_gpx=recueillis.extend,
    )
    capsys.readouterr()
    page = (tmp_path / "cache" / "sorties" / f"sortie_{JOUR:%Y%m%d}.html").read_text(
        encoding="utf-8"
    )
    for gpx in recueillis:
        assert gpx.nom_fichier in page

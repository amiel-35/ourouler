"""`ourouler boucle` : la météo le long du tracé.

Une météo en panne ne fait pas perdre la boucle ; repli de modèle, complet
ou partiel quand le tracé déborde l'horizon du modèle principal ; heure de
passage calculée à la vitesse du modèle physique.
Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from outils_boucle_commande import (
    CONFIG_BRUTE,
    _evaluation_de_test,
    args,
    bloc_meteo,
    config_de_test,
    moteur_brouter,
    moteur_meteo,
)

from ourouler.boucle.meteo_trace import Echantillon, MeteoTrace
from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.rendu.boucle import (
    _ligne_modele_meteo,
)
from ourouler.rendu.boucle_json import _modele_meteo_json

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- la météo en panne ne fait pas perdre la boucle ----------------------------


def test_meteo_en_panne_le_tableau_reste_affiche(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = executer(args(), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    capture = capsys.readouterr()
    assert code == 0
    titres = next(ligne for ligne in capture.out.splitlines() if "n°" in ligne and "distance" in ligne)
    for colonne in ("pluie", "vent face", "ressenti min"):
        assert colonne not in titres, "sans météo, les colonnes météo disparaissent"
    assert "météo indisponible" in capture.err
    assert list(tmp_path.glob("*.gpx")), "la boucle reste écrite malgré la panne météo"


def test_meteo_en_panne_le_json_dit_null(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    charge = json.loads(capsys.readouterr().out)
    assert all(c["meteo"] is None for c in charge["candidates"])
    assert all(c["total_tri"] == pytest.approx(c["couts"]["score"]) for c in charge["candidates"])


# --- le repli de modèle (Q19), sur `boucle` aussi -----------------------------
#
# Le piège de Q19 avait été refermé sur `ourouler sortie` et laissé ouvert sur
# `ourouler boucle` : une boucle demandée à J+3 perdait *toute* sa météo —
# pluie, vent, ressenti — alors que le second avis configuré couvre la
# fenêtre. Les deux commandes appellent le même `meteo_trace.evaluer` ; ces
# tests vérifient qu'elles lui passent le même repli.


def moteur_meteo_hors_de_portee(pluie_du_repli: float = 2.0) -> tuple[ClientOpenMeteo, list[str]]:
    """Open-Meteo bouchonné : le modèle principal rend un bloc nul, le repli répond.

    Un bloc entièrement à `null` est exactement ce qu'Open-Meteo rend pour une
    fenêtre au-delà de la portée d'un modèle régional (diagnostic de Q19). La
    liste rendue nomme, dans l'ordre, les modèles réellement interrogés.
    """
    demandes: list[str] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        modele = p["models"]
        demandes.append(modele)
        lats = p["latitude"].split(",")
        lons = p["longitude"].split(",")
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        if modele == CONFIG_BRUTE["meteo"]["modele"]:
            blocs = [bloc_meteo_nul(float(a), float(o), n) for a, o in zip(lats, lons, strict=True)]
        else:
            blocs = [
                bloc_meteo(float(a), float(o), n, pluie_du_repli)
                for a, o in zip(lats, lons, strict=True)
            ]
        return httpx.Response(200, json=blocs)

    return ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(gestionnaire))), demandes


def bloc_meteo_nul(lat: float, lon: float, n: int) -> dict:
    """Le bloc « hors de portée » : les heures sont là, les valeurs sont `null`."""
    variables = (
        "precipitation",
        "rain",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
        "apparent_temperature",
        "temperature_2m",
    )
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": [f"2026-09-13T{6 + i:02d}:00" for i in range(n)],
            **{nom: [None] * n for nom in variables},
        },
    }


def test_le_repli_garde_la_meteo_quand_le_modele_principal_ne_couvre_pas(
    tmp_path: Path, monkeypatch, capsys
):
    """Le défaut Q19 lui-même : sans repli, les trois colonnes météo disparaissaient."""
    monkeypatch.chdir(tmp_path)
    meteo, demandes = moteur_meteo_hors_de_portee()
    code = executer(args(), config_de_test(), moteur_brouter(), meteo)
    capture = capsys.readouterr()
    assert code == 0
    assert demandes[:2] == [
        CONFIG_BRUTE["meteo"]["modele"],
        CONFIG_BRUTE["meteo"]["second_avis"],
    ], "le principal est demandé d'abord, puis le repli — jamais l'inverse"
    titres = next(
        ligne for ligne in capture.out.splitlines() if "n°" in ligne and "distance" in ligne
    )
    for colonne in ("pluie", "vent face", "ressenti min"):
        assert colonne in titres, "le repli rend la météo, donc les colonnes"
    assert "météo indisponible" not in capture.err


def test_le_repli_est_nomme_dans_l_entete(tmp_path: Path, monkeypatch, capsys):
    """Un repli silencieux afficherait la pluie d'un modèle sous le nom d'un autre."""
    monkeypatch.chdir(tmp_path)
    meteo, _ = moteur_meteo_hors_de_portee()
    executer(args(), config_de_test(), moteur_brouter(), meteo)
    sortie = capsys.readouterr().out
    assert CONFIG_BRUTE["meteo"]["modele"] in sortie
    assert "bascule sur modele_second_test" in sortie


# --- repli partiel : un tracé qui déborde l'horizon du principal en route -----
#
# La mécanique elle-même (quels échantillons basculent, un seul appel de
# repli mémoïsé…) est couverte de bout en bout dans `test_meteo_trace.py`,
# avec des tracés fabriqués où chaque distance est exacte. Ici, seul le
# **rendu** — la phrase d'écran, le JSON — est testé, sur une `MeteoTrace`
# construite directement : la longueur réelle d'un tracé BRouter fabriqué
# (`test_brouter.reponse_fabriquee`) ne se laisse pas fixer au kilomètre
# près, et ce n'est pas ce que ces tests-ci cherchent à vérifier.


def _meteo_repli_partiel(bascule_dist_m: float | None) -> MeteoTrace:
    """Une `MeteoTrace` construite directement, pour tester le rendu sans passer par BRouter.

    `_ligne_modele_meteo`/`_modele_meteo_json` ne lisent que `modele_utilise`,
    `.repli` et `.bascule_dist_m` — les construire à la main isole le test du
    rendu de la mécanique du repli lui-même (déjà couverte dans
    `test_meteo_trace.py`) et des longueurs réelles que fabrique BRouter.
    """
    return MeteoTrace(
        echantillons=[
            Echantillon(
                dist_m=0.0, t=datetime(2026, 9, 13, 9, 0), lat=0.0, lon=0.0, cap_deg=0.0,
                pluie_mm=0.0, vent_kmh=None, vent_relatif=None, ressenti_c=None,
            )
        ],
        pluie_cumulee_mm=0.0,
        minutes_pluie=0.0,
        part_vent_face=0.0,
        part_vent_dos=0.0,
        ressenti_min_c=None,
        confiance="inconnu",
        modele_utilise=CONFIG_BRUTE["meteo"]["modele"],
        repli=bascule_dist_m is not None,
        bascule_dist_m=bascule_dist_m,
    )


def test_repli_partiel_dit_a_partir_de_quel_kilometre_en_json():
    evaluation = _evaluation_de_test(temps_s=None)
    evaluation.meteo = _meteo_repli_partiel(30_000.0)
    resultat = _modele_meteo_json([evaluation])
    assert resultat == {
        "utilise": CONFIG_BRUTE["meteo"]["modele"],
        "repli": True,
        "bascule_km": pytest.approx(30.0),
    }


def test_repli_partiel_la_phrase_ecran_nomme_le_kilometre_de_bascule():
    evaluation = _evaluation_de_test(temps_s=None)
    evaluation.meteo = _meteo_repli_partiel(30_000.0)
    ligne = _ligne_modele_meteo([evaluation], config_de_test())
    assert CONFIG_BRUTE["meteo"]["modele"] in ligne
    assert "kilomètre 30" in ligne, ligne
    assert CONFIG_BRUTE["meteo"]["second_avis"] in ligne


def test_repli_total_ne_dit_pas_de_kilometre_de_bascule():
    """Le repli total (tout le tracé) garde son ancienne phrase, sans kilomètre."""
    evaluation = _evaluation_de_test(temps_s=None)
    meteo = _meteo_repli_partiel(None)
    meteo.modele_utilise = CONFIG_BRUTE["meteo"]["second_avis"]
    meteo.repli = True
    evaluation.meteo = meteo
    ligne = _ligne_modele_meteo([evaluation], config_de_test())
    assert "bascule sur" in ligne
    assert "kilomètre" not in ligne, ligne
    assert _modele_meteo_json([evaluation])["bascule_km"] is None


def test_sans_repli_l_entete_nomme_le_modele_qui_a_repondu(tmp_path: Path, monkeypatch, capsys):
    """Le cas ordinaire ne change pas de forme : le modèle principal est nommé."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert "Météo modele_principal_test, second avis modele_second_test" in sortie
    assert "bascule" not in sortie


def test_le_json_dit_quel_modele_a_repondu_et_si_c_est_un_repli(
    tmp_path: Path, monkeypatch, capsys
):
    """Même forme que `sortie` : un écran lit le repli de la même façon sur les deux routes."""
    monkeypatch.chdir(tmp_path)
    meteo, _ = moteur_meteo_hors_de_portee()
    executer(args(json=True), config_de_test(), moteur_brouter(), meteo)
    charge = json.loads(capsys.readouterr().out)
    assert charge["modele_meteo"] == {
        "utilise": "modele_second_test",
        "repli": True,
        "bascule_km": None,
    }
    assert charge["modele"] == "modele_principal_test", "la configuration reste dite telle quelle"


def test_sans_meteo_du_tout_le_modele_utilise_vaut_null(tmp_path: Path, monkeypatch, capsys):
    """Aucune candidate n'a de météo : on ne nomme aucun modèle plutôt qu'un modèle muet."""
    monkeypatch.chdir(tmp_path)
    executer(args(json=True), config_de_test(), moteur_brouter(), moteur_meteo(en_panne=True))
    assert json.loads(capsys.readouterr().out)["modele_meteo"] is None

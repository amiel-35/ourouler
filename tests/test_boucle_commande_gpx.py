"""`ourouler boucle` : le GPX écrit, ses refus et le mode `--gpx`.

Bouchons partagés : `outils_boucle_commande.py`.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import httpx
import pytest
from outils_boucle_commande import (
    CONFIG_BRUTE,
    args,
    config_de_test,
    gpx_de_test,
    lignes_du_tableau,
    moteur_brouter,
    moteur_meteo,
)
from test_brouter import reponse_fabriquee  # même dossier : pytest y met le sys.path

from ourouler.boucle.gpx import ecrire_gpx
from ourouler.commandes.boucle import executer_depuis_namespace as executer
from ourouler.commandes.boucle import lire_options
from ourouler.config import depuis_dict
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, Segment, Trace

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- le GPX écrit --------------------------------------------------------------


def test_la_meilleure_est_ecrite_dans_le_dossier_courant(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    ecrits = list(tmp_path.glob("*.gpx"))
    assert len(ecrits) == 1
    assert ecrits[0].name == "boucle_NE_60km_20260913-0900.gpx"
    assert "<trkpt" in ecrits[0].read_text(encoding="utf-8")
    assert ecrits[0].name in capsys.readouterr().out


def test_sortie_choisie_par_l_utilisateur(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"
    executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    assert voulu.is_file()
    assert list(tmp_path.glob("*.gpx")) == [voulu]


def test_la_colonne_vent_face_dit_sur_combien_d_echantillons(tmp_path: Path, monkeypatch, capsys):
    """Point 18 : « vent face 100 % » ne distinguait pas 12 sur 12 d'un seul sur 12.

    Le bouchon météo n'a que quelques heures de série : les échantillons de
    fin de boucle tombent hors de l'horizon et n'ont pas de vent. C'est
    exactement la situation qui rendait le pourcentage trompeur.
    """
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    trouve = re.search(r"(\d+) % \((\d+)/(\d+)\)", ligne)
    assert trouve, ligne
    connus, total = int(trouve.group(2)), int(trouve.group(3))
    assert connus < total, (
        f"ce bouchon doit produire un dénominateur partiel, reçu {connus}/{total}"
    )


def test_le_denominateur_du_vent_est_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    meteo = json.loads(capsys.readouterr().out)["candidates"][0]["meteo"]
    assert meteo["n_echantillons"] == len(meteo["echantillons"])
    assert 0 < meteo["n_vent_connu"] < meteo["n_echantillons"], meteo["n_vent_connu"]
    # Le pourcentage porte bien sur les seuls échantillons au vent connu.
    connus = [e for e in meteo["echantillons"] if e["vent_relatif"] is not None]
    assert len(connus) == meteo["n_vent_connu"]
    face = [e for e in connus if e["vent_relatif"] == "face"]
    assert meteo["part_vent_face"] == pytest.approx(len(face) / len(connus), abs=1e-3)


def test_les_kilometres_non_classes_sont_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    """Point 15 : `km_trafic + km_calme` peut valoir bien moins que la distance."""
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    couts = charge["candidates"][0]["couts"]
    assert "km_non_classe" in couts
    assert couts["km_non_classe"] >= 0.0


def test_un_trace_surtout_non_classe_le_dit_dans_le_tableau(tmp_path: Path, monkeypatch, capsys):
    """Sans cette ligne, « 0,0 km de trafic » se lit comme « tracé calme »."""
    monkeypatch.chdir(tmp_path)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        charge = reponse_fabriquee()
        proprietes = charge["features"][0]["properties"]
        entete, lignes = proprietes["messages"][0], proprietes["messages"][1:]
        for ligne in lignes:  # colonne WayTags : une classe qu'on ne connaît pas
            ligne[9] = "highway=path surface=asphalt"
        proprietes["messages"] = [entete, *lignes]
        proprietes["track-length"] = "60000"
        return httpx.Response(200, json=charge)

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    executer(args(candidates=1), config_de_test(), brouter, moteur_meteo())
    sortie = capsys.readouterr().out
    assert "non classées" in sortie, sortie


# --- écriture du GPX : refus d'avance et erreurs utilisateur (point 8) --------


def test_un_dossier_de_sortie_inexistant_est_refuse_avant_tout_appel(tmp_path: Path, monkeypatch):
    """Point 8 : le refus doit tomber dans `lire_options`, pas après 22 appels externes."""
    monkeypatch.chdir(tmp_path)
    manquant = tmp_path / "jamais" / "cree" / "x.gpx"
    with pytest.raises(ErreurUtilisateur, match="n'existe pas"):
        lire_options(args(sortie=str(manquant)), config_de_test())


def test_un_dossier_de_sortie_non_inscriptible_est_refuse_avant_tout_appel(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    interdit = tmp_path / "interdit"
    interdit.mkdir()
    interdit.chmod(0o500)
    try:
        with pytest.raises(ErreurUtilisateur, match="écriture impossible"):
            lire_options(args(sortie=str(interdit / "x.gpx")), config_de_test())
    finally:
        interdit.chmod(0o700)


def test_aucun_appel_reseau_quand_la_sortie_est_impossible(tmp_path: Path, monkeypatch):
    """Le refus d'avance doit épargner jusqu'à 12 appels BRouter et 10 Open-Meteo."""
    monkeypatch.chdir(tmp_path)

    def interdit(requete: httpx.Request) -> httpx.Response:
        raise AssertionError(f"aucun appel ne doit partir : {requete.url}")

    brouter = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(interdit))
    )
    meteo = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(interdit)))
    with pytest.raises(ErreurUtilisateur):
        executer(
            args(sortie=str(tmp_path / "absent" / "x.gpx")), config_de_test(), brouter, meteo
        )


def test_une_ecriture_qui_echoue_sort_en_erreur_utilisateur(tmp_path: Path, monkeypatch):
    """Point 8 : `write_text` hors de tout `try` sortait en `OSError` nue, donc en trace.

    Le dossier est inscriptible au moment de la vérification et ne l'est plus
    à l'écriture : c'est le seul chemin qui reste après le refus d'avance,
    et il doit donner un message, pas une trace.
    """
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"

    def refuser(*a, **kw):
        raise OSError("disque plein")

    monkeypatch.setattr(Path, "write_text", refuser)
    with pytest.raises(ErreurUtilisateur, match="écriture impossible"):
        executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())


def test_un_fichier_de_sortie_existant_n_est_pas_ecrase_sans_ecraser(
    tmp_path: Path, monkeypatch, capsys
):
    """Point 19, tranché par le superviseur : `--sortie` ne remplace pas en silence."""
    monkeypatch.chdir(tmp_path)
    voulu = tmp_path / "ma_boucle.gpx"
    executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    ancien = voulu.read_text(encoding="utf-8")

    with pytest.raises(ErreurUtilisateur) as capture:
        executer(args(sortie=str(voulu)), config_de_test(), moteur_brouter(), moteur_meteo())
    assert "ma_boucle.gpx" in str(capture.value), "le message doit nommer le fichier"
    assert "--ecraser" in str(capture.value), "et dire quoi faire"
    assert voulu.read_text(encoding="utf-8") == ancien, "le fichier ne doit pas bouger"

    code = executer(
        args(sortie=str(voulu), ecraser=True), config_de_test(), moteur_brouter(), moteur_meteo()
    )
    assert code == 0 and voulu.is_file()


def test_le_nom_par_defaut_horodate_est_ecrase_sans_question(tmp_path: Path, monkeypatch, capsys):
    """Il porte l'heure à la minute : la collision est improbable, et sans enjeu."""
    monkeypatch.chdir(tmp_path)
    executer(args(), config_de_test(), moteur_brouter(), moteur_meteo())
    capsys.readouterr()
    (ecrit,) = list(tmp_path.glob("*.gpx"))
    ecrit.write_text("contenu précédent", encoding="utf-8")

    assert executer(args(), config_de_test(), moteur_brouter(), moteur_meteo()) == 0
    assert "<trkpt" in ecrit.read_text(encoding="utf-8")


def test_gpx_importe_evalue_seul_sans_rien_ecrire(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    code = executer(args(gpx=str(chemin)), config_de_test(), moteur_brouter(), moteur_meteo())
    sortie = capsys.readouterr().out
    assert code == 0
    assert "Tracé importé" in sortie
    assert list(tmp_path.glob("*.gpx")) == [chemin], "aucun nouveau GPX ne doit être écrit"
    assert len(lignes_du_tableau(sortie)) == 1


def test_gpx_importe_avec_greffage_reussi_sort_des_couts_partiels(tmp_path: Path, monkeypatch, capsys):
    """Le greffage (`boucle.tags_importes`) réussit : les coûts cessent d'être partiels.

    Avant le lot de greffage, un GPX importé restait `couts_partiels: True`
    pour toujours — le trafic, le revêtement, les feux étaient inconnus. Un
    BRouter disponible et un rapprochement exploitable changent ce fait :
    c'est tout l'objet du lot.
    """
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    executer(args(gpx=str(chemin), json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["gpx"] is None
    assert len(charge["candidates"]) == 1
    candidate = charge["candidates"][0]
    assert candidate["couts_partiels"] is False
    assert candidate["meteo"] is not None
    assert candidate["meta"]["tags_provenance"] == "rapprochement"
    assert candidate["meta"]["tags_seuil_m"] > 0
    assert candidate["meta"]["tags_km_sans_tag"] >= 0.0


def test_gpx_importe_sans_brouter_disponible_garde_les_couts_partiels(tmp_path: Path, monkeypatch, capsys):
    """Chemin dégradé : BRouter injoignable pour le greffage, comportement d'avant inchangé."""
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)

    def en_panne(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"erreur": "maintenance"})

    client = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(en_panne))
    )
    code = executer(args(gpx=str(chemin), json=True), config_de_test(), client, moteur_meteo())
    assert code == 0
    charge = json.loads(capsys.readouterr().out)
    candidate = charge["candidates"][0]
    assert candidate["couts_partiels"] is True
    assert "tags_provenance" not in candidate["meta"]


def test_la_colonne_d_plus_dit_d_ou_vient_le_chiffre(tmp_path: Path, monkeypatch, capsys):
    """Point 5 de la relecture : « D+ 362 m » ne disait pas moteur ou GPX relu.

    Les deux divergent de 10 à 32 % sur les tracés mesurés, dans les deux
    sens. Sans la provenance, `--gpx` sur le fichier qu'on vient d'écrire
    affiche un autre chiffre que celui inscrit dedans, sans explication.

    Depuis L7.C, un greffage de tags réussi (le cas ici : `moteur_brouter()`
    répond aussi à l'itinéraire) recalcule aussi le D+ sur l'altitude du
    tracé rerouté — la provenance devient « tracé rerouté », plus « gpx
    relu » (voir `test_gpx_sans_greffage_garde_le_denivele_du_fichier` pour
    le chemin dégradé).
    """
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    assert "m (moteur)" in ligne, ligne

    chemin = gpx_de_test(tmp_path)
    executer(args(gpx=str(chemin)), config_de_test(), moteur_brouter(), moteur_meteo())
    (ligne,) = lignes_du_tableau(capsys.readouterr().out)
    assert "m (tracé rerouté)" in ligne, ligne


def test_la_provenance_du_denivele_est_dans_le_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    executer(args(candidates=1, json=True), config_de_test(), moteur_brouter(), moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["candidates"][0]["denivele_source"] == "moteur"

    chemin = gpx_de_test(tmp_path)
    executer(
        args(gpx=str(chemin), json=True), config_de_test(), moteur_brouter(), moteur_meteo()
    )
    charge = json.loads(capsys.readouterr().out)
    assert charge["candidates"][0]["denivele_source"] == "tracé rerouté"


def test_gpx_sans_greffage_garde_le_denivele_du_fichier(tmp_path: Path, monkeypatch, capsys):
    """Chemin dégradé de L7.C : BRouter injoignable, le D+ reste celui du GPX relu.

    Même serveur en panne que `test_gpx_importe_sans_brouter_disponible_garde_les_couts_partiels`
    (503) : ni les tags ni le D+ ne doivent bouger, le comportement
    d'avant L7.C est inchangé à l'identique.
    """
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)

    def en_panne(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"erreur": "maintenance"})

    client = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(en_panne))
    )
    executer(args(gpx=str(chemin), json=True), config_de_test(), client, moteur_meteo())
    charge = json.loads(capsys.readouterr().out)
    assert charge["candidates"][0]["denivele_source"] == "gpx relu"


class _ClientBrouterFactice:
    """Un faux client BRouter : rend un `Trace` tout fait, sans réseau ni JSON.

    `_greffer_tags_sur_gpx` n'appelle qu'`itineraire()` sur le client reçu —
    le duck typing suffit, pas besoin de fabriquer une réponse GeoJSON pour
    tester la seule chose qui nous intéresse ici : ce que la commande fait de
    l'altitude du tracé rerouté.
    """

    def __init__(self, trace: Trace):
        self._trace = trace

    def itineraire(self, points, *, profil: str | None = None) -> Trace:
        return self._trace


def test_gpx_altitude_bruitee_remplacee_par_celle_du_trace_reroute(tmp_path: Path, monkeypatch, capsys):
    """L7.C : une altitude bruitée façon baromètre cède la place à celle du tracé rerouté.

    Le GPX porte une altitude à ±2,5 m de bruit sur un terrain plat — le même
    phénomène que `boucle.trace.denivele_filtre` documente lui-même (« plat,
    bruit ±2,5 m » gonfle le D+ de plusieurs centaines de mètres, seuil ou
    pas : au-delà du seuil, il ne protège plus). Le tracé rerouté, lui, est
    parfaitement plat : c'est son D+ qui doit gagner, proche de 0.
    """
    monkeypatch.chdir(tmp_path)

    def profil(n: int, amplitude: float) -> list[PointTrace]:
        alea = random.Random(12)
        return [
            PointTrace(
                lat=0.0, lon=i * 1e-4, alt_m=50.0 + alea.uniform(-amplitude, amplitude), dist_m=i * 11.0
            )
            for i in range(n)
        ]

    bruitee = profil(200, 2.5)
    trace_bruitee = Trace(
        nom="bruitee",
        points=bruitee,
        segments=[],
        distance_m=bruitee[-1].dist_m,
        denivele_m=None,
        temps_moteur_s=None,
    )
    chemin = tmp_path / "bruitee.gpx"
    chemin.write_text(ecrire_gpx(trace_bruitee, "bruitee"), encoding="utf-8")

    plate = [PointTrace(lat=0.0, lon=i * 1e-4, alt_m=50.0, dist_m=i * 11.0) for i in range(200)]
    trace_reroutee = Trace(
        nom="reroutee",
        points=plate,
        segments=[Segment(0, len(plate) - 1, plate[-1].dist_m, tags={"highway": "tertiary"})],
        distance_m=plate[-1].dist_m,
        denivele_m=None,
        temps_moteur_s=None,
    )
    client = _ClientBrouterFactice(trace_reroutee)

    code = executer(args(gpx=str(chemin), json=True), config_de_test(), client, moteur_meteo())
    assert code == 0
    candidate = json.loads(capsys.readouterr().out)["candidates"][0]
    assert candidate["denivele_source"] == "tracé rerouté"
    assert candidate["denivele_m"] < 5.0, "le tracé rerouté est plat, le bruit du GPX ne doit plus paraître"


def test_gpx_importe_appelle_brouter_pour_greffer_les_tags(tmp_path: Path, monkeypatch):
    """Depuis le greffage de tags, `--gpx` appelle bien BRouter — pour reroutier, pas pour tracer.

    Avant ce lot, `--gpx` n'appelait jamais BRouter : la trace importée restait
    sans tags. Le greffage (`boucle.tags_importes`) a besoin d'un tracé
    rerouté pour trouver des tags à emprunter, d'où cet appel — un seul, pas
    un par candidate (`--gpx` n'en évalue qu'une).
    """
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    appels = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json=reponse_fabriquee())

    client = ClientBrouter(
        config_de_test().brouter, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    assert executer(args(gpx=str(chemin)), config_de_test(), client, moteur_meteo()) == 0
    assert len(appels) == 1
    assert "roundTripStartDirection" not in appels[0].url.params, "un itinéraire, pas une boucle"


def test_gpx_importe_sans_client_brouter_injecte_en_construit_un(tmp_path: Path, monkeypatch):
    """`client_brouter=None` : la commande construit le sien, comme pour une boucle générée.

    Même détail que la branche sans `--gpx` : `evitements=config.evitements`
    est passé au client construit. On le vérifie ici en configurant une URL
    de serveur invalide (`brouter` non renseigné) et en s'assurant que la
    commande dégrade proprement plutôt que de planter.
    """
    monkeypatch.chdir(tmp_path)
    chemin = gpx_de_test(tmp_path)
    config_sans_brouter = depuis_dict({k: v for k, v in CONFIG_BRUTE.items() if k != "brouter"})
    code = executer(args(gpx=str(chemin)), config_sans_brouter, None, moteur_meteo())
    assert code == 0  # dégradé : couts_partiels, pas d'exception

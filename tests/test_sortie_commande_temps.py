"""`ourouler sortie` : le temps écoulé porte à porte et le bloc « compteur ».

Bouchons partagés : `outils_sortie_commande.py`.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from outils_sortie_commande import (
    AILLEURS,
    CONFIG_BRUTE,
    JOUR,
    _contexte_avec,
    _contexte_minimal,
    _proposition_avec_demi_tour,
    _seance_fabriquee,
    _trace_anneau,
    anneau,
    args,
    bloc_meteo,
    client_intervals,
    config_avec_facteur_mesure,
    config_de_test,
    ecrire_calibration,
    lancer,
    reponse_anneau,
)

from ourouler.boucle.gpx import lire_gpx_trace
from ourouler.cli import construire_parseur
from ourouler.commandes.sortie import executer_depuis_namespace as executer
from ourouler.commandes.sortie import lire_options
from ourouler.config import (
    depuis_dict,
)
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.seance import Seance
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.noyau.trace import distance_m as distance_points
from ourouler.physique.litterature import FOURCHETTE_PORTE_A_PORTE_DEFAUT
from ourouler.rendu.boucle import ligne_temps_ecoule
from ourouler.rendu.sortie import rendre_texte
from ourouler.rendu.sortie_json import rendre_json
from ourouler.seance.placement import Emplacement, Placement
from ourouler.seance.terrain import NoteBloc
from ourouler.sortie.commande import (
    _ecrire_gpx,
)

# Le fuseau que les bouchons Open-Meteo de ce module supposent (voir
# `fuseau_de_paris` dans conftest.py) : dit ici, pas emprunté à la machine.
pytestmark = pytest.mark.usefixtures("fuseau_de_paris")


# --- temps écoulé porte à porte, et le bloc « compteur » -----------------------
#
# Même défaut, même correction que `boucle` : la colonne « temps » montrait le
# temps *en mouvement* du placement (`placement.duree_totale_s`) comme s'il
# s'agissait du temps écoulé de la sortie. Ici, `compteur` et
# `candidate.temps_ecoule_s`, câblés dans `rendre_json`/`rendre_texte` via
# `ecran_ftp.info_compteur` et `physique.modele.temps_ecoule` — la même
# formule que `boucle`, testée à part dans `tests/test_physique_modele.py`.


def test_compteur_et_temps_ecoule_sont_nuls_sans_velo(tmp_path: Path):
    """Le test explicite du DoD : `compteur` et `temps_ecoule_s` de chaque
    candidate valent `null` sur une configuration sans vélo — même si, en
    pratique, `sortie` a toujours besoin d'un vélo pour placer une séance
    (`_parametres` lève sinon) : ce cas ne s'obtient qu'en le retirant après
    coup, comme pour `boucle`."""
    seance = _seance_fabriquee()
    config = dataclasses.replace(config_de_test(tmp_path / "cache"), velos=())
    charge = rendre_json([_proposition_avec_demi_tour()], _contexte_avec(seance, config))
    assert charge["compteur"] is None
    candidate = charge["candidates"][0]
    assert candidate["temps_ecoule_s"] is None
    assert candidate["temps_ecoule_source"] is None
    # Le temps de mouvement du placement, lui, reste renseigné.
    assert candidate["placement"]["duree_totale_s"] == round(
        _proposition_avec_demi_tour().placement.duree_totale_s
    )


def test_compteur_json_porte_les_quatre_champs_du_contrat(tmp_path: Path):
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    charge = rendre_json([_proposition_avec_demi_tour()], _contexte_avec(seance, config))
    compteur = charge["compteur"]
    assert compteur["velo"] == "Route"
    assert compteur["facteur_compteur"] == pytest.approx(0.85)
    assert compteur["facteur_provenance"] == "mesure"
    assert compteur["moyenne_compteur_kmh"] > 0
    assert compteur["porte_a_porte"]["provenance"] == "defaut"


def test_temps_ecoule_json_suit_la_formule_partagee(tmp_path: Path):
    """Pas une deuxième formule : `candidate.temps_ecoule_s` et ses bornes
    sont exactement `physique.modele.temps_ecoule` appliqué à
    `placement.duree_totale_s` (le parcours réellement roulé, demi-tours
    compris — pas la boucle) et à la fourchette du bloc `compteur`."""
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    proposition = _proposition_avec_demi_tour()
    charge = rendre_json([proposition], _contexte_avec(seance, config))
    candidate = charge["candidates"][0]
    mouvement = proposition.placement.duree_totale_s
    bas, mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT
    assert candidate["temps_ecoule_s"] == round(mouvement * mediane)
    assert candidate["temps_ecoule_bas_s"] == round(mouvement * bas)
    assert candidate["temps_ecoule_haut_s"] == round(mouvement * haut)
    assert candidate["temps_ecoule_source"] == "defaut"
    assert candidate["temps_ecoule_s"] >= candidate["placement"]["duree_totale_s"]


def test_texte_sortie_affiche_mouvement_et_ecoule(tmp_path: Path):
    """CLI et front disent la même chose, **dans le même ordre** : le porte à
    porte d'abord, en fourchette, le temps sans arrêt ensuite, dans une
    cellule combinée, et la légende partagée avec `boucle` sous le tableau."""
    seance = _seance_fabriquee()
    config = config_avec_facteur_mesure(tmp_path / "cache", facteur=0.85)
    contexte = _contexte_avec(seance, config)
    proposition = _proposition_avec_demi_tour()
    texte = rendre_texte([proposition], contexte)

    from ourouler.seance.ecran_ftp import info_compteur

    compteur = info_compteur(config, contexte.demande.velo)
    mouvement = proposition.placement.duree_totale_s
    bas, _mediane, haut = FOURCHETTE_PORTE_A_PORTE_DEFAUT

    def hm(secondes: float) -> str:
        minutes = round(secondes / 60)
        return f"{minutes // 60}:{minutes % 60:02d}"

    assert f"{hm(mouvement * bas)}-{hm(mouvement * haut)} / {hm(mouvement)}" in texte
    assert ligne_temps_ecoule(compteur) in texte


def test_sortie_dit_qu_une_autre_seance_du_jour_a_ete_ignoree(tmp_path: Path):
    """S1 : `ourouler seance` le disait, `ourouler sortie` non.

    C'est pourtant `sortie` qui construit une boucle entière pour la séance
    choisie en silence — la plus longue. La clé restait dans `meta`, donc
    visible en `--json` seul.
    """
    seance = _seance_fabriquee()
    seance.meta["seances_ignorees"] = ["Vélo B", "Vélo C"]
    texte = rendre_texte(
        [_proposition_avec_demi_tour()], _contexte_minimal(tmp_path, seance)
    )
    assert "ignorée(s) au profit de la plus longue" in texte
    assert "Vélo B, Vélo C" in texte


#: Les quatre commandes qui portent une heure de départ, et le minimum à leur
#: passer pour que le parseur accepte la ligne.
COMMANDES_A_HEURE_DEPART = {
    "meteo": [],
    "boucle": ["--distance", "40", "--direction", "N"],
    "simuler": ["--gpx", "x.gpx", "--puissance", "200"],
    "sortie": [],
}


#: Les trois commandes qui partent d'un **lieu**, donc qui portent
#: `--adresse-depart` (lot F0.7). `simuler` n'en est pas : elle part du GPX
#: qu'on lui donne, pas d'un point.
COMMANDES_A_ADRESSE_DEPART = ("meteo", "boucle", "sortie")


def test_l_heure_de_depart_s_appelle_heure_depart_partout():
    """Q15, tranchée par le mainteneur le 13/09.

    L'heure de départ s'appelle `--heure-depart` ; le lieu de départ
    s'appelle `--adresse-depart` (livré par F0.7). `--depart`, qui disait
    « heure » alors que `--adresse-depart` dit « lieu », et `--heure`, ajouté
    en attendant la décision, restent acceptés pour ne rien casser.
    """
    parseur = construire_parseur()
    for commande, arguments in COMMANDES_A_HEURE_DEPART.items():
        lus = parseur.parse_args([commande, *arguments, "--heure-depart", "08:00"])
        assert lus.depart == "08:00", f"{commande} : --heure-depart n'alimente pas `depart`"
        lus = parseur.parse_args([commande, *arguments, "--heure", "09:30"])
        assert lus.depart == "09:30", f"{commande} : --heure n'alimente pas `depart`"
        lus = parseur.parse_args([commande, *arguments, "--depart", "10:15"])
        assert lus.depart == "10:15", f"{commande} : --depart a été perdu"


def test_les_anciens_noms_de_l_heure_de_depart_ne_sont_plus_documentes():
    """Acceptés, oui ; enseignés, non (Q15).

    L'aide ne doit plus proposer `--depart` ni `--heure` : les laisser dans
    l'aide reviendrait à ne rien avoir tranché.
    """
    parseur = construire_parseur()
    sous = next(
        action
        for action in parseur._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for commande in COMMANDES_A_HEURE_DEPART:
        aide = sous.choices[commande].format_help()
        assert "--heure-depart" in aide, f"{commande} : le nom canonique manque dans l'aide"
        # Les deux noms canoniques sont retirés avant de chercher les anciens :
        # « --adresse-depart » est cité dans l'aide de `--heure-depart` et
        # réciproquement, précisément pour qu'on ne les confonde pas.
        sans_noms_canoniques = aide.replace("--heure-depart", "").replace("--adresse-depart", "")
        for ancien in ("--depart", "--heure"):
            assert ancien not in sans_noms_canoniques, (
                f"{commande} : l'aide documente encore {ancien}"
            )


def test_le_lieu_de_depart_s_appelle_adresse_depart_et_rien_d_autre():
    """Ce que gardait le test du nom réservé, maintenant que le nom est livré (F0.7).

    Ce qui compte, c'est le nom lui-même : `--adresse-depart`, et pas un
    autre.

    Aucun des noms écartés (`--depuis`, `--lieu-depart`, `--depart-adresse`) ne
    doit apparaître à la place, et l'option n'existe que là où partir
    d'ailleurs a un sens : `simuler` part du GPX qu'on lui donne, pas d'un
    point.
    """
    parseur = construire_parseur()
    sous = next(
        action
        for action in parseur._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for commande in COMMANDES_A_HEURE_DEPART:
        aide = sous.choices[commande].format_help()
        attendu = commande in COMMANDES_A_ADRESSE_DEPART
        assert ("--adresse-depart" in aide) is attendu, (
            f"{commande} : --adresse-depart devrait "
            f"{'figurer' if attendu else 'être absent'} de l'aide"
        )
        for ecarte in ("--depuis", "--lieu-depart", "--depart-adresse"):
            assert ecarte not in aide, (
                f"{commande} : {ecarte} a été livré à la place du nom retenu"
            )


def test_l_adresse_de_depart_et_l_heure_de_depart_ne_se_confondent_pas():
    """Les deux options sur la même ligne, chacune dans son `dest` (Q15).

    C'est la confusion pour laquelle le lieu ne s'appelle pas `--depart` : un
    `dest` partagé ferait qu'une heure deviendrait un lieu, ou l'inverse, sans
    que rien ne le dise.
    """
    parseur = construire_parseur()
    for commande in COMMANDES_A_ADRESSE_DEPART:
        arguments = COMMANDES_A_HEURE_DEPART[commande]
        lus = parseur.parse_args(
            [commande, *arguments, "--heure-depart", "08:00", "--adresse-depart", "Place du Test"]
        )
        assert lus.depart == "08:00", f"{commande} : l'heure a été écrasée par le lieu"
        assert lus.adresse_depart == "Place du Test", f"{commande} : le lieu n'est pas arrivé"

        # L'ordre inverse, et l'ancien nom de l'heure, ne changent rien.
        lus = parseur.parse_args(
            [commande, *arguments, "--adresse-depart", "Place du Test", "--depart", "10:15"]
        )
        assert lus.depart == "10:15"
        assert lus.adresse_depart == "Place du Test"

        # Sans l'option, aucun lieu n'est demandé : la configuration décide.
        lus = parseur.parse_args([commande, *arguments])
        assert lus.adresse_depart is None


def test_sortie_part_du_lieu_recu_et_pas_de_celui_de_la_configuration(tmp_path: Path, monkeypatch):
    """F0.7 : le cœur reçoit un `Depart`, il ne le lit pas.

    Les deux services qui partent d'un point sont surveillés : la question
    d'orientation au vent (premier appel Open-Meteo, sur le départ) et la
    génération des candidates (BRouter). Un seul des deux resté sur la
    configuration donnerait une sortie fausse — le vent de chez soi, ou la
    boucle de chez soi.
    """
    monkeypatch.chdir(tmp_path)
    ecrire_calibration(tmp_path / "cache")

    departs_brouter: list[tuple[float, float]] = []
    points_meteo: list[tuple[float, float]] = []

    def espion_brouter(requete: httpx.Request) -> httpx.Response:
        lon, lat = requete.url.params["lonlats"].split(",")
        departs_brouter.append((float(lat), float(lon)))
        azimut = float(requete.url.params["roundTripStartDirection"])
        return httpx.Response(200, json=reponse_anneau(anneau(azimut)))

    def espion_meteo(requete: httpx.Request) -> httpx.Response:
        p = requete.url.params
        lats = [float(x) for x in p["latitude"].split(",")]
        lons = [float(x) for x in p["longitude"].split(",")]
        points_meteo.extend(zip(lats, lons, strict=True))
        debut = datetime.fromisoformat(p["start_hour"])
        fin = datetime.fromisoformat(p["end_hour"])
        n = int((fin - debut).total_seconds() // 3600) + 1
        return httpx.Response(
            200, json=[bloc_meteo(a, o, n, 0.0) for a, o in zip(lats, lons, strict=True)]
        )

    brouter = ClientBrouter(
        depuis_dict(CONFIG_BRUTE).brouter,
        http=httpx.Client(transport=httpx.MockTransport(espion_brouter)),
    )
    meteo = ClientOpenMeteo(http=httpx.Client(transport=httpx.MockTransport(espion_meteo)))

    code = executer(
        args(json=True),
        config_de_test(tmp_path / "cache"),
        brouter,
        meteo,
        client_intervals(),
        lieu_depart=AILLEURS,
    )
    assert code == 0

    assert departs_brouter, "aucune candidate demandée au moteur"
    for lat, lon in departs_brouter:
        assert (lat, lon) == pytest.approx((AILLEURS.latitude, AILLEURS.longitude), abs=1e-6)

    # Le tout premier appel météo est la question du vent, posée sur le départ.
    # `abs=1e-3` : le client arrondit les coordonnées qu'il envoie.
    assert points_meteo[0] == pytest.approx(
        (AILLEURS.latitude, AILLEURS.longitude), abs=1e-3
    ), "la question du vent est restée sur le départ configuré"


def test_le_json_de_sortie_dit_de_quel_lieu_la_boucle_part(tmp_path: Path, monkeypatch, capsys):
    """Sans cette clé, deux réponses identiques décriraient deux parcours différents.

    C'est ce dont l'API aura besoin pour que le front sache d'où part ce
    qu'il affiche : l'heure de départ était publiée, le lieu non.
    """
    lancer(tmp_path, monkeypatch, json=True, lieu_depart=AILLEURS)
    charge = json.loads(capsys.readouterr().out)
    lieu = charge["demande"]["lieu_depart"]
    assert lieu["nom"] == AILLEURS.nom
    assert lieu["latitude"] == pytest.approx(AILLEURS.latitude)
    assert lieu["longitude"] == pytest.approx(AILLEURS.longitude)

    lancer(tmp_path, monkeypatch, json=True)
    charge = json.loads(capsys.readouterr().out)
    assert charge["demande"]["lieu_depart"]["nom"] == "Point zéro", (
        "sans lieu fourni, le JSON doit nommer le départ de la configuration"
    )


def test_le_tableau_distingue_la_boucle_du_parcours_reellement_roule(tmp_path: Path):
    """C1 : la même ligne affichait 38,5 km et 2 h 44, soit 14 km/h.

    La distance venait de la boucle, la durée du placement. Les deux sont
    justes et ne parlent pas du même parcours : le tableau porte maintenant
    les deux distances, et « temps » va avec « parcours ».
    """
    proposition = _proposition_avec_demi_tour()
    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    entete = next(ligne for ligne in texte.splitlines() if "note placement" in ligne)
    assert "boucle" in entete and "parcours" in entete, entete
    assert "distance" not in entete, "« distance » ne dit pas de quel parcours il s'agit"

    boucle_km = proposition.trace.distance_m / 1000
    ligne = next(ligne for ligne in texte.splitlines() if ligne.startswith("→"))
    assert f"{boucle_km:.1f}".replace(".", ",") in ligne
    assert f"{2 * boucle_km:.1f}".replace(".", ",") in ligne, (
        f"le parcours réellement roulé n'est pas dans la ligne : {ligne}"
    )
    assert "Boucle" in texte and "parcours réellement roulé" in texte


def test_un_retour_au_calme_qui_s_allonge_s_affiche_sans_avertissement(tmp_path: Path):
    """Q14 : « c'est du kilomètre facile » ne s'affiche pas avec un ⚠.

    Les deux listes du placement ne se rendent pas de la même façon : les
    avertissements portent un ⚠, les informations non. Un retour au calme qui
    s'allonge dans sa fenêtre est une information, et l'afficher comme une
    alerte était précisément le ton que le mainteneur a corrigé.
    """
    proposition = _proposition_avec_demi_tour()
    proposition.placement.informations = [
        "retour au calme : 38 min au lieu des 20 prescrites, 8 km de plus à allure facile"
    ]
    proposition.placement.avertissements = ["étape 1 (libre) : aucune puissance cible"]

    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    info = next(ligne for ligne in texte.splitlines() if "retour au calme : 38 min" in ligne)
    assert "⚠" not in info, info
    assert "8 km de plus à allure facile" in info
    alerte = next(ligne for ligne in texte.splitlines() if "aucune puissance cible" in ligne)
    assert "⚠" in alerte, "les vrais défauts gardent leur ⚠"


def test_les_deux_denivelés_sont_montrés_cote_a_cote(tmp_path: Path):
    """C2 : 460 m annoncés par le moteur, 308 m recalculés — et rien ne le disait.

    Règle absolue 5 : deux mesures qui divergent s'affichent comme un
    désaccord. La provenance était bien écrite dans chaque artefact, mais il
    fallait ouvrir le GPX pour voir l'écart.
    """
    proposition = _proposition_avec_demi_tour(denivele_moteur_m=460.0)
    recalcule = proposition.denivele_parcours_m
    assert recalcule is not None
    assert abs(recalcule - 460.0) > 10.0, (
        "la fixture doit faire diverger les deux mesures, sinon le test ne prouve rien"
    )
    texte = rendre_texte([proposition], _contexte_minimal(tmp_path, _seance_fabriquee()))

    ligne = next((ligne for ligne in texte.splitlines() if ligne.startswith("D+ :")), None)
    assert ligne is not None, f"aucune ligne ne compare les deux D+ :\n{texte}"
    assert "460 m" in ligne and f"{recalcule:.0f} m" in ligne, ligne
    assert "moteur" in ligne and "parcours placé" in ligne


def test_le_gpx_d_un_parcours_avec_demi_tour_contient_l_aller_retour(
    tmp_path: Path, monkeypatch
):
    """Un placement qui fait demi-tour au km 12 et rentre au km 6 : 18 km de fichier.

    Le placement est fabriqué ici, parce que l'anneau des autres tests porte la
    séance de bout en bout sans jamais avoir à se retourner. Ce qui est vérifié
    est ce que le mainteneur a mesuré le 22/04 : le fichier doit contenir
    l'aller-retour, et son `<desc>` le dire.
    """
    monkeypatch.chdir(tmp_path)
    trace = _trace_anneau()
    place = Placement(
        decalage_z2_s=0.0,
        emplacements=[
            Emplacement(etape_idx=1, debut_m=6000.0, longueur_m=3000.0, demi_tour=True, note=NoteBloc(0.0))
        ],
        note_totale=1.0,
        duree_totale_s=3600.0,
        distance_totale_m=18_000.0,
        jalons_m=[0.0, 12_000.0, 6_000.0],
    )
    seance = Seance(nom="séance fabriquée", jour=JOUR, etapes=[], duree_s=0.0, meta={})
    config = config_de_test(tmp_path / "cache")
    demande = lire_options(args(), config)

    chemin = _ecrire_gpx(trace, place, seance, demande, config.cache.dossier)

    texte = chemin.read_text(encoding="utf-8")
    relu = lire_gpx_trace(texte.encode("utf-8"))
    assert relu.distance_m == pytest.approx(18_000.0, rel=0.01), (
        f"{relu.distance_m:.0f} m écrits pour 18 000 m roulés : le demi-tour manque au fichier"
    )
    assert "1 demi-tour" in texte and "18,0 km" in texte, texte[:400]
    # Le GPX repasse bien deux fois par le même endroit : le point du km 9 de la
    # boucle est écrit à l'aller et au retour.
    passages = [p for p in relu.points if distance_points(p, _point_a_9_km(trace)) < 50.0]
    assert len(passages) >= 2, f"{len(passages)} passage(s) au km 9 : l'aller-retour n'y est pas"


def _point_a_9_km(trace: Trace) -> PointTrace:
    """Le point de la boucle au km 9, entre le demi-tour et le retour."""
    return min(trace.points, key=lambda p: abs(p.dist_m - 9_000.0))


def test_les_chemins_demandes_sont_respectes(tmp_path: Path, monkeypatch, capsys):
    code = lancer(
        tmp_path,
        monkeypatch,
        sortie=str(tmp_path / "ma_sortie.gpx"),
        carte=str(tmp_path / "ma_carte.html"),
    )
    capsys.readouterr()
    assert code == 0
    assert (tmp_path / "ma_sortie.gpx").is_file()
    assert (tmp_path / "ma_carte.html").is_file()

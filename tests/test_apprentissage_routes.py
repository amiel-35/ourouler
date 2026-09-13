"""Tests des routes connues (L3.2).

Tracés **fabriqués** autour du point zéro (au large du golfe de Guinée), base
SQLite dans `tmp_path`, BRouter bouchonné par `httpx.MockTransport` : aucune
coordonnée réelle, aucun fichier du mainteneur, aucun réseau.

Ce que ces tests tiennent :

* l'**idempotence par `id_sortie`** — relancer l'apprentissage ne doit ni
  doubler les passages ni refaire les appels ;
* `part_connue` — 1,0 sur un tracé entièrement roulé, 0,0 sur un tracé
  inconnu, 0,5 sur la moitié ; et **jamais** dans un score ;
* `poids_appris` — les trois cas limites du contrat (classe absente des
  sorties, absente de l'exposition, `tertiary`) et l'absence d'exposition.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from ourouler.activites.cache import Cache
from ourouler.activites.modele import Activite, Point
from ourouler.apprentissage.routes import (
    MAILLE,
    PART_EXPOSITION_MIN,
    POIDS_MAX,
    BaseRoutes,
    Statistiques,
    apprendre,
    cle_maille,
    ecrire_poids,
    lire_poids,
    poids_appris,
    points_de_passage,
    sorties_a_apprendre,
    statistiques_de_traces,
)
from ourouler.boucle.couts import POIDS_HIGHWAY_DEFAUT
from ourouler.boucle.trace import PointTrace, Segment, Trace
from ourouler.config import Config, Cycliste, Depart, ParametresBrouter
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurUtilisateur

#: Mètres par degré de latitude (et de longitude à l'équateur).
METRES_PAR_DEGRE = 111_194.9

#: Un lundi et un dimanche, pour la part semaine.
LUNDI = date(2024, 3, 4)
DIMANCHE = date(2024, 3, 10)

PARAMS_BROUTER = ParametresBrouter(url="https://brouter.exemple.test", profil="fastbike")


def config_de_test() -> Config:
    return Config(
        depart=Depart(nom="Point fictif", latitude=0.0, longitude=0.0),
        cycliste=Cycliste(masse_kg=75.0, ftp_w=250.0),
    )


# --- fabrique de tracés -------------------------------------------------------


def droite(
    n: int, *, pas_m: float = 100.0, depart_lat: float = 0.0, tags: dict[str, str] | None = None
) -> Trace:
    """Un tracé rectiligne vers le nord, un seul tronçon portant `tags`."""
    points = [
        PointTrace(
            lat=depart_lat + i * pas_m / METRES_PAR_DEGRE, lon=0.0, alt_m=None, dist_m=i * pas_m
        )
        for i in range(n)
    ]
    longueur = pas_m * (n - 1)
    return Trace(
        nom="droite",
        points=points,
        segments=[Segment(0, n - 1, longueur, dict(tags or {"highway": "tertiary"}))],
        distance_m=longueur,
        denivele_m=None,
        temps_moteur_s=None,
    )


def trace_de_troncons(longueurs_tags: list[tuple[float, dict[str, str]]]) -> Trace:
    """Un tracé rectiligne dont chaque tronçon a sa longueur et ses tags."""
    points = [PointTrace(0.0, 0.0, None, 0.0)]
    segments = []
    cumul = 0.0
    for longueur, tags in longueurs_tags:
        debut = len(points) - 1
        cumul += longueur
        points.append(PointTrace(cumul / METRES_PAR_DEGRE, 0.0, None, cumul))
        segments.append(Segment(debut, len(points) - 1, longueur, dict(tags)))
    return Trace(
        nom="troncons",
        points=points,
        segments=segments,
        distance_m=cumul,
        denivele_m=None,
        temps_moteur_s=None,
    )


# --- maille -------------------------------------------------------------------


def test_la_maille_est_celle_du_contrat():
    assert cle_maille(0.0, 0.0) == (0, 0)
    assert cle_maille(1.0, -1.0) == (MAILLE, -MAILLE)


def test_deux_points_du_meme_carre_tombent_dans_la_meme_maille():
    """Une maille fait ~37 m : deux points à 10 m ne doivent pas se séparer."""
    pas = 10.0 / METRES_PAR_DEGRE
    assert cle_maille(0.00005, 0.00005) == cle_maille(0.00005 + pas, 0.00005)


def test_la_maille_est_symetrique_autour_de_zero():
    """Aux bornes : le signe ne doit pas faire perdre la maille."""
    assert cle_maille(-0.001, -0.001) == (-3, -3)
    assert cle_maille(0.001, 0.001) == (3, 3)


# --- base ---------------------------------------------------------------------


def test_une_base_neuve_ne_connait_aucune_sortie(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    assert base.sorties_apprises() == set()
    assert base.statistiques().km_total == 0.0


def test_ajouter_une_trace_enregistre_ses_mailles_et_ses_km(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    mailles = base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    assert mailles > 0
    stats = base.statistiques()
    assert stats.sorties == 1
    assert stats.km_total == pytest.approx(10.0, rel=0.02)
    assert stats.km_par_highway["tertiary"] == pytest.approx(10.0, rel=0.02)


def test_ajouter_deux_fois_la_meme_sortie_ne_double_rien(tmp_path: Path):
    """Idempotence par `id_sortie` : relancer l'apprentissage ne fausse rien."""
    base = BaseRoutes(tmp_path / "routes.sqlite")
    premier = base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    km_apres_un = base.statistiques().km_total
    second = base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    assert second == premier
    stats = base.statistiques()
    assert stats.sorties == 1
    assert stats.km_total == pytest.approx(km_apres_un)
    assert all(t.passages == 1 for t in base.troncons())


def test_deux_sorties_distinctes_sur_la_meme_route_cumulent_les_passages(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    base.ajouter_trace(droite(101), jour=DIMANCHE, id_sortie="s2")
    stats = base.statistiques()
    assert stats.sorties == 2
    assert stats.km_total == pytest.approx(20.0, rel=0.02)
    assert all(t.passages == 2 for t in base.troncons())
    assert all(t.passages_semaine == 1 for t in base.troncons())


def test_la_part_semaine_distingue_le_lundi_du_dimanche(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="lundi")
    base.ajouter_trace(droite(101), jour=DIMANCHE, id_sortie="dimanche")
    stats = base.statistiques()
    assert stats.part_semaine("tertiary") == pytest.approx(0.5, abs=0.02)


def test_une_sortie_du_dimanche_seule_a_une_part_semaine_nulle(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101), jour=DIMANCHE, id_sortie="s1")
    assert base.statistiques().part_semaine("tertiary") == 0.0


def test_une_meme_maille_traversee_par_deux_classes_donne_deux_troncons(tmp_path: Path):
    """Pas d'arbitrage sur un carré de 30 m : deux lignes, deux kilométrages exacts."""
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(
        trace_de_troncons([(1000.0, {"highway": "tertiary"}), (1000.0, {"highway": "secondary"})]),
        jour=LUNDI,
        id_sortie="s1",
    )
    stats = base.statistiques()
    assert stats.km_par_highway["tertiary"] == pytest.approx(1.0, rel=0.05)
    assert stats.km_par_highway["secondary"] == pytest.approx(1.0, rel=0.05)


def test_les_statistiques_rangent_aussi_par_surface_et_maxspeed(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(
        droite(101, tags={"highway": "tertiary", "surface": "asphalt", "maxspeed": "80"}),
        jour=LUNDI,
        id_sortie="s1",
    )
    stats = base.statistiques()
    assert stats.km_par_surface["asphalt"] == pytest.approx(10.0, rel=0.02)
    assert stats.km_par_maxspeed["80"] == pytest.approx(10.0, rel=0.02)


def test_un_tag_absent_se_range_sous_la_chaine_vide_pas_sous_null(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101, tags={"highway": "tertiary"}), jour=LUNDI, id_sortie="s1")
    troncons = base.troncons()
    assert troncons and all(t.surface is None and t.maxspeed is None for t in troncons)


def test_le_cout_du_moteur_est_moyenne_par_maille(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    trace = droite(101)
    trace.segments[0].cout_km = 1500.0
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    assert base.statistiques().cout_km_moyen == pytest.approx(1500.0)


def test_une_sortie_sans_identifiant_est_refusee(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    with pytest.raises(ErreurUtilisateur, match="identifiant"):
        base.ajouter_trace(droite(10), jour=LUNDI, id_sortie="")


def test_une_base_au_schema_plus_recent_est_refusee(tmp_path: Path):
    import sqlite3

    chemin = tmp_path / "routes.sqlite"
    BaseRoutes(chemin)
    cx = sqlite3.connect(chemin)
    cx.execute("PRAGMA user_version = 99")
    cx.commit()
    cx.close()
    with pytest.raises(ErreurUtilisateur, match="schéma"):
        BaseRoutes(chemin)


def test_un_fichier_qui_n_est_pas_une_base_donne_une_erreur_utilisateur(tmp_path: Path):
    chemin = tmp_path / "routes.sqlite"
    chemin.write_bytes(b"ceci n'est pas une base SQLite" * 20)
    with pytest.raises(ErreurUtilisateur):
        BaseRoutes(chemin)


# --- part connue (informative, jamais dans un score) --------------------------


def test_un_trace_entierement_connu_vaut_un(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    trace = droite(101)
    base.ajouter_trace(trace, jour=LUNDI, id_sortie="s1")
    assert base.part_connue(trace) == pytest.approx(1.0, abs=0.01)


def test_un_trace_inconnu_vaut_zero(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    ailleurs = droite(101, depart_lat=1.0)
    assert base.part_connue(ailleurs) == 0.0


def test_un_trace_a_moitie_connu_vaut_un_demi(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(51), jour=LUNDI, id_sortie="moitie")
    assert base.part_connue(droite(101)) == pytest.approx(0.5, abs=0.05)


def test_un_trace_moins_echantillonne_reste_reconnu(tmp_path: Path):
    """Apprendre à 20 m et mesurer à 200 m doit donner la même réponse.

    Sans découpe à la demi-maille, un pas de 200 m ne marquerait qu'une maille
    sur cinq : `part_connue` chuterait pour la seule raison que deux tracés
    n'ont pas le même espacement de points.
    """
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(501, pas_m=20.0), jour=LUNDI, id_sortie="fin")
    assert base.part_connue(droite(51, pas_m=200.0)) == pytest.approx(1.0, abs=0.05)


def test_un_trace_vide_ne_divise_pas_par_zero(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    base.ajouter_trace(droite(101), jour=LUNDI, id_sortie="s1")
    vide = Trace(
        nom="vide", points=[], segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )
    assert base.part_connue(vide) == 0.0
    un_point = Trace(
        nom="un",
        points=[PointTrace(0.0, 0.0, None, 0.0)],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    assert base.part_connue(un_point) == 0.0


def test_deux_points_confondus_ne_font_pas_une_part_connue(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    immobile = Trace(
        nom="immobile",
        points=[PointTrace(0.0, 0.0, None, 0.0), PointTrace(0.0, 0.0, None, 0.0)],
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    assert base.part_connue(immobile) == 0.0


# --- poids appris -------------------------------------------------------------


def stats_de(km_par_highway: dict[str, float]) -> Statistiques:
    return Statistiques(
        km_total=sum(km_par_highway.values()), km_par_highway=dict(km_par_highway)
    )


def test_sans_exposition_les_poids_sont_ceux_par_defaut():
    """Sans point de comparaison, une part brute ne veut rien dire."""
    assert poids_appris(stats_de({"tertiary": 65.0, "secondary": 23.0})) == POIDS_HIGHWAY_DEFAUT


def test_une_exposition_vide_retombe_aussi_sur_les_poids_par_defaut():
    assert poids_appris(stats_de({"tertiary": 10.0}), Statistiques()) == POIDS_HIGHWAY_DEFAUT


def test_des_sorties_vides_retombent_sur_les_poids_par_defaut():
    assert poids_appris(Statistiques(), stats_de({"tertiary": 10.0})) == POIDS_HIGHWAY_DEFAUT


def test_tertiary_est_toujours_a_zero():
    """La classe de référence ne coûte rien, quoi que disent les mesures."""
    poids = poids_appris(
        stats_de({"tertiary": 1.0, "primary": 50.0}), stats_de({"tertiary": 50.0, "primary": 1.0})
    )
    assert poids["tertiary"] == 0.0


def test_une_classe_absente_des_sorties_atteint_le_plafond():
    """Proposée sans cesse, jamais prise : c'est le refus le plus net."""
    poids = poids_appris(
        stats_de({"tertiary": 100.0}), stats_de({"tertiary": 90.0, "trunk": 10.0})
    )
    assert poids["trunk"] == POIDS_MAX


def test_une_classe_absente_de_l_exposition_vaut_zero():
    """Rien à comparer : « inconnu » n'est jamais un malus."""
    poids = poids_appris(
        stats_de({"tertiary": 90.0, "cycleway": 10.0}), stats_de({"tertiary": 100.0})
    )
    assert poids["cycleway"] == 0.0


def test_une_classe_autant_prise_que_proposee_ne_coute_rien():
    poids = poids_appris(
        stats_de({"tertiary": 50.0, "secondary": 50.0}),
        stats_de({"tertiary": 50.0, "secondary": 50.0}),
    )
    assert poids["secondary"] == pytest.approx(0.0)


def test_une_classe_evitee_de_moitie_coute_un_kilometre_equivalent():
    """Deux fois moins prise que proposée : log2(2) = 1."""
    poids = poids_appris(
        stats_de({"tertiary": 75.0, "secondary": 25.0}),
        stats_de({"tertiary": 50.0, "secondary": 50.0}),
    )
    assert poids["secondary"] == pytest.approx(1.0)


def test_une_classe_plus_prise_que_proposee_ne_recoit_pas_de_bonus():
    """Le poids est borné à 0 : un score négatif fausserait le tri."""
    poids = poids_appris(
        stats_de({"tertiary": 20.0, "secondary": 80.0}),
        stats_de({"tertiary": 80.0, "secondary": 20.0}),
    )
    assert poids["secondary"] == 0.0


def test_le_poids_ne_depasse_jamais_le_plafond():
    poids = poids_appris(
        stats_de({"tertiary": 999_999.0, "trunk": 1.0}),
        stats_de({"tertiary": 1.0, "trunk": 999_999.0}),
    )
    assert poids["trunk"] == POIDS_MAX


def test_multiplier_les_kilometres_des_sorties_ne_change_pas_les_poids():
    """Contrat §2 : on compare des **parts**, jamais des kilomètres.

    Les deux jeux sont normalisés chacun sur son propre total. Un jeu de
    sorties dix fois plus fourni — ou une table filtrée en amont, dont les
    parts ne somment plus à 1 — doit rendre exactement les mêmes poids.
    """
    expo = stats_de({"tertiary": 30.0, "secondary": 70.0})
    reference = poids_appris(stats_de({"tertiary": 60.0, "secondary": 40.0}), expo)
    for facteur in (0.4, 2.5, 10.0):
        mis_a_echelle = Statistiques(
            # `km_total` reste celui d'origine : c'est précisément le cas d'une
            # table filtrée en amont, que `part()` seul ne saurait pas normaliser.
            km_total=100.0,
            km_par_highway={"tertiary": 60.0 * facteur, "secondary": 40.0 * facteur},
        )
        assert poids_appris(mis_a_echelle, expo) == pytest.approx(reference), (
            f"les poids changent quand les kilomètres des sorties sont multipliés par {facteur}"
        )


def test_multiplier_les_kilometres_de_l_exposition_ne_change_pas_les_poids():
    """Le pendant côté exposition : ~8 boucles de 40 km ou 80, même verdict."""
    stats = stats_de({"tertiary": 60.0, "secondary": 40.0})
    reference = poids_appris(stats, stats_de({"tertiary": 30.0, "secondary": 70.0}))
    double = Statistiques(
        km_total=100.0,
        km_par_highway={"tertiary": 60.0, "secondary": 140.0},
    )
    assert poids_appris(stats, double) == pytest.approx(reference)


def test_une_classe_trop_peu_exposee_garde_son_poids_par_defaut():
    """Réglage du superviseur du 13/09 : sous 2 % d'exposition, on ne sait pas.

    `living_street` sortait à 2,56 km équivalents par km pour 0,8 %
    d'exposition mesurée, `service` à 2,35 pour 0,6 % — des malus lourds tirés
    de quelques centaines de mètres. Voir `PART_EXPOSITION_MIN`.
    """
    assert PART_EXPOSITION_MIN == 0.02
    poids = poids_appris(
        # `living_street` prise dix fois moins que proposée : la formule
        # donnerait log2(10) plafonné à 4 si on la laissait parler.
        stats_de({"tertiary": 999.0, "living_street": 0.1}),
        stats_de({"tertiary": 999.0, "living_street": 1.0}),
    )
    assert poids["living_street"] == 0.0, (
        "0,1 % d'exposition : c'est le poids par défaut qui doit rester, pas un malus appris"
    )


def test_une_classe_a_trafic_trop_peu_exposee_garde_son_malus_par_defaut():
    """« Défaut » ne veut pas dire « zéro » : une classe à trafic garde ses 3 km."""
    poids = poids_appris(
        stats_de({"tertiary": 999.0, "primary": 50.0}),
        stats_de({"tertiary": 999.0, "primary": 1.0}),
    )
    assert poids["primary"] == POIDS_HIGHWAY_DEFAUT["primary"] == 3.0


def test_juste_au_dessus_du_seuil_le_poids_est_bien_appris():
    """La borne est stricte : à 2 % pile, la mesure parle."""
    poids = poids_appris(
        stats_de({"tertiary": 99.0, "secondary": 1.0}),  # part sorties : 1 %
        stats_de({"tertiary": 98.0, "secondary": 2.0}),  # part exposition : 2 % pile
    )
    assert poids["secondary"] == pytest.approx(1.0), "log2(2 % / 1 %) = 1, poids appris"


def test_tous_les_poids_sont_finis_et_positifs():
    poids = poids_appris(
        stats_de({"tertiary": 65.0, "secondary": 23.0, "primary": 2.0, "residential": 10.0}),
        stats_de({"tertiary": 30.0, "secondary": 30.0, "primary": 30.0, "trunk": 10.0}),
    )
    assert poids
    for classe, valeur in poids.items():
        assert math.isfinite(valeur), classe
        assert 0.0 <= valeur <= POIDS_MAX, classe


def test_la_classe_sans_highway_ne_recoit_pas_de_poids():
    """On ne pondère pas ce dont on ne sait rien."""
    poids = poids_appris(stats_de({"": 50.0, "tertiary": 50.0}), stats_de({"": 50.0, "tertiary": 50.0}))
    assert "" not in poids


# --- exposition (statistiques bâties sur des tracés bruts) --------------------


def test_l_exposition_se_calcule_sans_toucher_la_base():
    stats = statistiques_de_traces(
        [trace_de_troncons([(1000.0, {"highway": "tertiary"}), (3000.0, {"highway": "secondary"})])]
    )
    assert stats.km_total == pytest.approx(4.0)
    assert stats.part("secondary") == pytest.approx(0.75)


def test_l_exposition_ignore_les_longueurs_absurdes():
    trace = trace_de_troncons([(1000.0, {"highway": "tertiary"})])
    trace.segments.append(Segment(0, 1, float("nan"), {"highway": "primary"}))
    trace.segments.append(Segment(0, 1, -500.0, {"highway": "trunk"}))
    stats = statistiques_de_traces([trace])
    assert stats.km_par_highway == {"tertiary": pytest.approx(1.0)}


def test_l_exposition_moyenne_le_cout_du_moteur():
    trace = trace_de_troncons([(1000.0, {"highway": "tertiary"}), (1000.0, {"highway": "secondary"})])
    trace.segments[0].cout_km = 1000.0
    trace.segments[1].cout_km = 2000.0
    assert statistiques_de_traces([trace]).cout_km_moyen == pytest.approx(1500.0)


# --- points de passage --------------------------------------------------------


def activite_de(n: int, pas_m: float) -> Activite:
    debut = datetime(2024, 3, 4, 8, 0, tzinfo=UTC)
    points = [
        Point(
            t=debut,
            lat=i * pas_m / METRES_PAR_DEGRE,
            lon=0.0,
            dist_m=i * pas_m,
        )
        for i in range(n)
    ]
    return Activite(
        source="gpx",
        fichier=None,
        debut=debut,
        duree_s=3600.0,
        duree_mouvement_s=None,
        distance_m=pas_m * (n - 1),
        denivele_m=None,
        puissance_moy_w=None,
        puissance_np_w=None,
        sport="Ride",
        appareil=None,
        points=points,
    )


def test_les_points_de_passage_sont_espaces_de_1500_m():
    passages = points_de_passage(activite_de(301, 100.0))  # 30 km
    assert len(passages) == pytest.approx(21, abs=1)
    ecart = (passages[1][0] - passages[0][0]) * METRES_PAR_DEGRE
    assert ecart == pytest.approx(1500.0, rel=0.1)


def test_les_points_de_passage_ne_depassent_jamais_soixante():
    """Limite du moteur : un appel à 200 points serait refusé."""
    passages = points_de_passage(activite_de(3001, 100.0))  # 300 km
    assert 2 <= len(passages) <= 60


def test_le_dernier_point_de_la_sortie_est_toujours_retenu():
    activite = activite_de(3001, 100.0)
    passages = points_de_passage(activite)
    assert passages[-1] == (
        pytest.approx(activite.points[-1].lat),
        pytest.approx(activite.points[-1].lon),
    )


def test_une_sortie_sans_position_ne_donne_aucun_point_de_passage():
    activite = activite_de(50, 100.0)
    for p in activite.points:
        p.lat = p.lon = None
    assert points_de_passage(activite) == []


# --- apprendre ----------------------------------------------------------------


def reponse_brouter() -> dict:
    """Une réponse GeoJSON minimale, deux tronçons autour du point zéro."""
    coordonnees = [[0.0, i * 0.0009, 10.0] for i in range(21)]
    entete = [
        "Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost",
        "TurnCost", "NodeCost", "InitialCost", "WayTags", "NodeTags", "Time", "Energy",
    ]  # fmt: skip
    messages = [entete]
    for fin, tags in ((10, "highway=tertiary surface=asphalt"), (20, "highway=secondary")):
        lon, lat, _ = coordonnees[fin]
        messages.append(
            [
                str(round(lon * 1e6)), str(round(lat * 1e6)), "10", "5000", "1200",
                "0", "0", "0", "0", tags, "", "600", "9000",
            ]  # fmt: skip
        )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "track-length": "10000",
                    "filtered ascend": "50",
                    "total-time": "1800",
                    "messages": messages,
                },
                "geometry": {"type": "LineString", "coordinates": coordonnees},
            }
        ],
    }


def client_bouchonne() -> tuple[ClientBrouter, list[httpx.Request]]:
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(200, json=reponse_brouter())

    return (
        ClientBrouter(
            PARAMS_BROUTER, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
        ),
        vues,
    )


@pytest.fixture
def cache_garni(tmp_path: Path, activites: Path) -> Cache:
    """Un cache contenant les fixtures valides : une boucle GPX, un home-trainer."""
    cache = Cache(tmp_path / "cache")
    for nom in ("boucle.gpx", "boucle.fit", "home_trainer.fit"):
        cache.ajouter(
            (activites / nom).read_bytes(),
            source="fichier",
            id_externe=nom,
            extension=Path(nom).suffix,
            meta={"fichier": nom},
        )
    return cache


def test_les_sorties_a_apprendre_excluent_le_home_trainer(cache_garni: Cache):
    retenues = sorties_a_apprendre(cache_garni, config_de_test(), depuis=date(2020, 1, 1))
    assert retenues
    noms = {e.meta.get("fichier") for e in retenues}
    assert "home_trainer.fit" not in noms


def test_apprendre_rejoue_chaque_sortie_une_fois(tmp_path: Path, cache_garni: Cache):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    client, vues = client_bouchonne()
    rapport = apprendre(
        cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1)
    )
    assert rapport.sorties_apprises == len(vues) > 0
    assert rapport.echecs == 0
    assert rapport.km == pytest.approx(10.0 * rapport.sorties_apprises, rel=0.01)
    assert base.statistiques().sorties == rapport.sorties_apprises


def test_relancer_apprendre_ne_refait_aucun_appel(tmp_path: Path, cache_garni: Cache):
    """Idempotence : la deuxième passe ne coûte rien et ne fausse rien."""
    base = BaseRoutes(tmp_path / "routes.sqlite")
    client, vues = client_bouchonne()
    premier = apprendre(cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1))
    appels = len(vues)
    km_apres_un = base.statistiques().km_total

    second = apprendre(cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1))
    assert len(vues) == appels
    assert second.sorties_apprises == 0
    assert second.sorties_deja_connues == premier.sorties_apprises
    assert base.statistiques().km_total == pytest.approx(km_apres_un)


def test_apprendre_respecte_max_sorties(tmp_path: Path, cache_garni: Cache):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    client, vues = client_bouchonne()
    rapport = apprendre(
        cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1), max_sorties=1
    )
    assert rapport.sorties_apprises == 1
    assert len(vues) == 1


def test_max_sorties_borne_les_appels_meme_quand_ils_echouent(tmp_path: Path, cache_garni: Cache):
    """`--max N` promet de borner un coût : un appel raté a coûté un appel.

    Le cas réel : deux sorties de vacances hors des tuiles OSM du serveur
    rendent « datafile … not found ». Tant que le quota ne comptait que les
    succès, `--max 1` sur un lot de sorties hors région passait autant
    d'appels qu'il y avait de sorties.
    """
    vues: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(500, content=b"datafile not found")

    client = ClientBrouter(
        PARAMS_BROUTER, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    base = BaseRoutes(tmp_path / "routes.sqlite")
    rapport = apprendre(
        cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1), max_sorties=1
    )
    assert rapport.sorties_vues >= 2, "il y avait bien d'autres sorties à tenter"
    assert len(vues) == 1, "un seul appel, alors qu'il a échoué"
    assert rapport.sorties_apprises == 0
    assert rapport.echecs == 1


def test_un_echec_du_moteur_est_compte_pas_fatal(tmp_path: Path, cache_garni: Cache):
    """Une sortie perdue ne doit pas faire perdre les autres, ni disparaître."""
    appels = {"n": 0}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels["n"] += 1
        if appels["n"] == 1:
            return httpx.Response(500, content=b"")
        return httpx.Response(200, json=reponse_brouter())

    client = ClientBrouter(
        PARAMS_BROUTER, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    base = BaseRoutes(tmp_path / "routes.sqlite")
    rapport = apprendre(cache_garni, client, base, config_de_test(), depuis=date(2020, 1, 1))
    assert rapport.echecs == 1
    assert rapport.sorties_apprises >= 1
    assert rapport.messages and "500" in rapport.messages[0]


def test_apprendre_sur_un_cache_vide_ne_dit_pas_n_importe_quoi(tmp_path: Path):
    base = BaseRoutes(tmp_path / "routes.sqlite")
    client, vues = client_bouchonne()
    rapport = apprendre(
        Cache(tmp_path / "vide"), client, base, config_de_test(), depuis=date(2020, 1, 1)
    )
    assert (rapport.sorties_vues, rapport.sorties_apprises, rapport.echecs) == (0, 0, 0)
    assert vues == []


# --- persistance des poids ----------------------------------------------------


def test_les_poids_ecrits_se_relisent(tmp_path: Path):
    chemin = tmp_path / "poids_routes.json"
    ecrire_poids(chemin, {"secondary": 1.5, "tertiary": 0.0}, meta={"sorties": 12})
    assert lire_poids(chemin) == {"secondary": 1.5, "tertiary": 0.0}
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    assert charge["sorties"] == 12 and charge["version"] == 1


def test_un_fichier_de_poids_absent_rend_none(tmp_path: Path):
    assert lire_poids(tmp_path / "rien.json") is None


def test_un_fichier_de_poids_abime_rend_none_plutot_qu_une_erreur(tmp_path: Path):
    """Un JSON tronqué ne doit pas empêcher de tracer une boucle."""
    chemin = tmp_path / "poids_routes.json"
    chemin.write_text('{"poids": {"secondary": 1.0', encoding="utf-8")
    assert lire_poids(chemin) is None


@pytest.mark.parametrize(
    "charge",
    ['[]', '{"poids": []}', '{"poids": {"a": "beaucoup"}}', '{"poids": {"a": null}}', '{}'],
)
def test_un_fichier_de_poids_inexploitable_rend_none(tmp_path: Path, charge: str):
    chemin = tmp_path / "poids_routes.json"
    chemin.write_text(charge, encoding="utf-8")
    assert lire_poids(chemin) is None


def test_une_valeur_non_finie_est_ecartee_des_poids_relus(tmp_path: Path):
    chemin = tmp_path / "poids_routes.json"
    chemin.write_text('{"poids": {"a": 1e999, "secondary": 2.0}}', encoding="utf-8")
    assert lire_poids(chemin) == {"secondary": 2.0}

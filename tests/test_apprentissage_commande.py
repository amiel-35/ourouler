"""Tests de la sous-commande `ourouler routes` (L3.2).

Client BRouter bouchonné par `httpx.MockTransport`, cache et base dans
`tmp_path` : aucun réseau, aucun fichier du mainteneur.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from test_apprentissage_routes import LUNDI, droite, reponse_brouter

from ourouler.activites.cache import Cache
from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes
from ourouler.cli import construire_parseur
from ourouler.commandes.routes import executer_depuis_namespace as executer
from ourouler.config import (
    Config,
    Cycliste,
    Depart,
    ParametresBrouter,
    ParametresCache,
)
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.noyau.erreurs import ErreurUtilisateur

PARAMS_BROUTER = ParametresBrouter(url="https://brouter.exemple.test", profil="fastbike")


def config_de(tmp_path: Path) -> Config:
    return Config(
        depart=Depart(nom="Point fictif", latitude=0.0, longitude=0.0),
        cycliste=Cycliste(masse_kg=75.0, ftp_w=250.0),
        cache=ParametresCache(dossier=tmp_path / "cache"),
        brouter=PARAMS_BROUTER,
        historique_depuis=date(2020, 1, 1),
    )


def args_de(**champs) -> argparse.Namespace:
    defauts = {"json": False, "depuis": None, "max_sorties": None, "appliquer": False}
    return argparse.Namespace(**{**defauts, **champs})


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
    cache = Cache(tmp_path / "cache")
    for nom in ("boucle.gpx", "boucle.fit"):
        cache.ajouter(
            (activites / nom).read_bytes(),
            source="fichier",
            id_externe=nom,
            extension=Path(nom).suffix,
            meta={"fichier": nom},
        )
    return cache


def base_garnie(tmp_path: Path) -> BaseRoutes:
    """Une base contenant de quoi faire un tableau : tertiary majoritaire."""
    base = BaseRoutes(tmp_path / "cache" / NOM_BASE)
    base.ajouter_trace(droite(101, tags={"highway": "tertiary"}), jour=LUNDI, id_sortie="s1")
    base.ajouter_trace(
        droite(51, tags={"highway": "secondary"}, depart_lat=1.0), jour=LUNDI, id_sortie="s2"
    )
    return base


# --- parseur ------------------------------------------------------------------


def test_les_trois_actions_existent():
    parseur = construire_parseur()
    for action in ("apprendre", "stats", "poids"):
        args = parseur.parse_args(["routes", action])
        assert args.commande == "routes" and args.action == action


@pytest.mark.parametrize("place", ["global", "routes", "action"])
def test_json_accepte_aux_trois_niveaux(place: str):
    argv = {
        "global": ["--json", "routes", "stats"],
        "routes": ["routes", "--json", "stats"],
        "action": ["routes", "stats", "--json"],
    }[place]
    assert construire_parseur().parse_args(argv).json is True


def test_sans_json_la_sortie_reste_en_texte():
    assert construire_parseur().parse_args(["routes", "stats"]).json is False


def test_les_options_d_apprendre_sont_declarees():
    args = construire_parseur().parse_args(
        ["routes", "apprendre", "--depuis", "2024-01-01", "--max", "3"]
    )
    assert args.depuis == "2024-01-01" and args.max_sorties == 3


def test_appliquer_est_declare_sur_poids():
    assert construire_parseur().parse_args(["routes", "poids", "--appliquer"]).appliquer is True


# --- action manquante ---------------------------------------------------------


def test_sans_action_on_dit_lesquelles(tmp_path: Path):
    with pytest.raises(ErreurUtilisateur, match="apprendre"):
        executer(args_de(action=None), config_de(tmp_path))


def test_une_action_inconnue_est_refusee_par_le_parseur(capsys):
    with pytest.raises(SystemExit):
        construire_parseur().parse_args(["routes", "oublier"])


# --- apprendre ----------------------------------------------------------------


def test_apprendre_affiche_ce_qui_a_ete_appris(tmp_path: Path, cache_garni: Cache, capsys):
    client, vues = client_bouchonne()
    assert executer(args_de(action="apprendre"), config_de(tmp_path), client) == 0
    sortie = capsys.readouterr().out
    assert "Apprentissage des routes" in sortie
    assert f"apprises ce coup-ci : {len(vues)}" in sortie
    assert "échecs              : 0" in sortie


def test_apprendre_en_json_rend_des_nombres(tmp_path: Path, cache_garni: Cache, capsys):
    client, vues = client_bouchonne()
    executer(args_de(action="apprendre", json=True), config_de(tmp_path), client)
    charge = json.loads(capsys.readouterr().out)
    assert charge["sorties_apprises"] == len(vues)
    assert charge["echecs"] == 0 and charge["km"] > 0


def test_apprendre_cree_bien_la_base_dans_le_cache(tmp_path: Path, cache_garni: Cache, capsys):
    client, _ = client_bouchonne()
    executer(args_de(action="apprendre"), config_de(tmp_path), client)
    capsys.readouterr()
    assert (tmp_path / "cache" / NOM_BASE).is_file()


def test_apprendre_respecte_max(tmp_path: Path, cache_garni: Cache, capsys):
    client, vues = client_bouchonne()
    executer(args_de(action="apprendre", max_sorties=1), config_de(tmp_path), client)
    capsys.readouterr()
    assert len(vues) == 1


def test_une_date_illisible_est_refusee_avant_tout_appel(tmp_path: Path):
    client, vues = client_bouchonne()
    with pytest.raises(ErreurUtilisateur, match="AAAA-MM-JJ"):
        executer(args_de(action="apprendre", depuis="hier"), config_de(tmp_path), client)
    assert vues == []


def test_sans_url_brouter_on_le_dit_plutot_que_de_planter(tmp_path: Path, cache_garni: Cache):
    config = config_de(tmp_path)
    config = Config(**{**config.__dict__, "brouter": ParametresBrouter()})
    with pytest.raises(ErreurUtilisateur, match="brouter"):
        executer(args_de(action="apprendre"), config)


# --- stats --------------------------------------------------------------------


def test_stats_sur_une_base_vide_oriente_vers_apprendre(tmp_path: Path, capsys):
    assert executer(args_de(action="stats"), config_de(tmp_path)) == 0
    assert "routes apprendre" in capsys.readouterr().out


def test_stats_affiche_la_table_par_classe(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    executer(args_de(action="stats"), config_de(tmp_path))
    sortie = capsys.readouterr().out
    assert "tertiary" in sortie and "secondary" in sortie
    assert "part semaine" in sortie and "poids appris" in sortie
    assert "67 %" in sortie  # 10 km tertiary sur 15 km


def test_stats_dit_que_les_poids_ne_sont_pas_encore_appris(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    executer(args_de(action="stats"), config_de(tmp_path))
    assert "routes poids --appliquer" in capsys.readouterr().out


def test_stats_en_json(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    executer(args_de(action="stats", json=True), config_de(tmp_path))
    charge = json.loads(capsys.readouterr().out)
    classes = {c["classe"]: c for c in charge["par_highway"]}
    assert classes["tertiary"]["part"] == pytest.approx(2 / 3, abs=0.02)
    assert classes["secondary"]["poids_defaut"] == 3.0
    assert classes["tertiary"]["poids_appris"] is None


def test_stats_montre_les_poids_appris_quand_ils_existent(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    (tmp_path / "cache" / NOM_POIDS).write_text(
        json.dumps({"poids": {"secondary": 1.25}}), encoding="utf-8"
    )
    executer(args_de(action="stats"), config_de(tmp_path))
    assert "1,25" in capsys.readouterr().out


# --- poids --------------------------------------------------------------------


def test_poids_sans_rien_appris_oriente_vers_apprendre(tmp_path: Path):
    client, vues = client_bouchonne()
    with pytest.raises(ErreurUtilisateur, match="routes apprendre"):
        executer(args_de(action="poids"), config_de(tmp_path), client)
    assert vues == []


def test_poids_genere_une_boucle_par_direction(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    client, vues = client_bouchonne()
    assert executer(args_de(action="poids"), config_de(tmp_path), client) == 0
    assert len(vues) == 8
    assert {v.url.params["roundTripStartDirection"] for v in vues} == {
        "0", "45", "90", "135", "180", "225", "270", "315"
    }  # fmt: skip


def test_poids_n_ecrit_rien_sans_appliquer(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    client, _ = client_bouchonne()
    executer(args_de(action="poids"), config_de(tmp_path), client)
    assert "--appliquer" in capsys.readouterr().out
    assert not (tmp_path / "cache" / NOM_POIDS).exists()


def test_poids_appliquer_ecrit_le_json_dans_le_cache(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    client, _ = client_bouchonne()
    executer(args_de(action="poids", appliquer=True), config_de(tmp_path), client)
    chemin = tmp_path / "cache" / NOM_POIDS
    assert chemin.is_file()
    charge = json.loads(chemin.read_text(encoding="utf-8"))
    assert charge["poids"]["tertiary"] == 0.0
    assert charge["boucles_exposition"] == 8
    assert str(chemin) in capsys.readouterr().out


def test_poids_en_json_montre_les_deux_parts(tmp_path: Path, capsys):
    base_garnie(tmp_path)
    client, _ = client_bouchonne()
    executer(args_de(action="poids", json=True), config_de(tmp_path), client)
    charge = json.loads(capsys.readouterr().out)
    classes = {c["classe"]: c for c in charge["classes"]}
    assert classes["tertiary"]["poids_appris"] == 0.0
    assert classes["tertiary"]["part_sorties"] > 0
    assert classes["tertiary"]["part_exposition"] > 0
    assert charge["directions"] == ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def reponse_avec_antenne_en_track() -> dict:
    """Une ligne de 2 km en `secondary`, prolongée d'un aller-retour de 2 km en `track`.

    C'est la forme réelle du cul-de-sac que le mode boucle de BRouter fabrique
    en allant chercher un point de passage tombé à côté de la route : il tombe
    majoritairement sur `track` et `unclassified`.
    """
    pas_deg = 0.0009
    aller = [[0.0, i * pas_deg, 10.0] for i in range(21)]  # 0 → 20 : la ligne
    antenne = [[0.0, (20 + i) * pas_deg, 10.0] for i in range(1, 11)]  # 21 → 30
    retour = antenne[-2::-1] + [aller[20]]  # on redescend par le même chemin
    coordonnees = aller + antenne + retour
    entete = [
        "Longitude", "Latitude", "Elevation", "Distance", "CostPerKm", "ElevCost",
        "TurnCost", "NodeCost", "InitialCost", "WayTags", "NodeTags", "Time", "Energy",
    ]  # fmt: skip
    messages = [entete]
    # Deux tronçons : la ligne finit au point 20, l'aller-retour y revient. Le
    # rattachement des messages avance, il ne confond donc pas les deux.
    for lat_fin, distance, tags in (
        (20 * pas_deg, "2004", "highway=secondary"),
        (20 * pas_deg, "2004", "highway=track"),
    ):
        messages.append(
            [
                "0", str(round(lat_fin * 1e6)), "10", distance, "1200",
                "0", "0", "0", "0", tags, "", "600", "9000",
            ]  # fmt: skip
        )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"filtered ascend": "0", "total-time": "900", "messages": messages},
                "geometry": {"type": "LineString", "coordinates": coordonnees},
            }
        ],
    }


def test_l_exposition_est_elaguee_de_ses_antennes(tmp_path: Path, capsys):
    """L'exposition doit mesurer ce que `boucle` proposera, c'est-à-dire après élagage.

    Sinon les deux parts du rapport `log2(part expo / part sorties)` ne
    décrivent pas la même chose, et l'écart tombe justement sur les classes
    marginales où le logarithme amplifie le bruit : `track` compterait pour
    la moitié de l'exposition alors qu'aucune candidate ne la proposerait.
    """
    base_garnie(tmp_path)

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reponse_avec_antenne_en_track())

    client = ClientBrouter(
        PARAMS_BROUTER, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    executer(args_de(action="poids", json=True), config_de(tmp_path), client)
    charge = json.loads(capsys.readouterr().out)
    classes = {c["classe"]: c for c in charge["classes"]}

    assert classes["secondary"]["part_exposition"] == pytest.approx(1.0)
    assert classes.get("track", {}).get("part_exposition", 0.0) == 0.0
    # 8 directions × 2 km de ligne : l'aller-retour de 2 km n'est pas compté.
    assert charge["km_exposition"] == pytest.approx(16.0, abs=0.5)


def test_une_direction_en_panne_ne_perd_pas_les_autres(tmp_path: Path, capsys):
    """Sept directions valent mieux que rien — mais le nombre est affiché."""
    base_garnie(tmp_path)
    appels = {"n": 0}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        appels["n"] += 1
        if appels["n"] == 1:
            return httpx.Response(500, content=b"")
        return httpx.Response(200, json=reponse_brouter())

    client = ClientBrouter(
        PARAMS_BROUTER, http=httpx.Client(transport=httpx.MockTransport(gestionnaire))
    )
    executer(args_de(action="poids"), config_de(tmp_path), client)
    sortie = capsys.readouterr().out
    assert "1 direction(s) sans boucle" in sortie
    assert "7 boucle(s) d'exposition" in sortie

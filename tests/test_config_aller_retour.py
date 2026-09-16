"""L'invariant d'aller-retour de la configuration : **ce qui se charge se recharge.**

Le lot F0.4 a remplacé `puissance_endurance_pct` (une valeur) par
`position_zone` (une position dans la bande de Z2), et convertit l'ancienne
clé au chargement. La relecture du lot F0 a montré que la conversion pouvait
produire une position que le chargement suivant refusait : avec
`zones = [[0, 0.55], [0.70, 0.72], [0.73, 0.90], [0.91, 1.05]]` et
`puissance_endurance_pct = 0.40`, la position valait −15,0 et sortait des
bornes `[-1, 2]`. Une configuration qui se chargeait une fois, et plus jamais
dès qu'on la réécrivait.

Ce fichier ne teste pas ce cas-là (il est dans `test_config.py`, avec les
autres cas de la migration) : il teste **la propriété** que ce cas avait
cassée. Elle vaut pour n'importe quelle configuration et n'importe quel champ,
y compris ceux que personne n'a encore écrits — `reecrire` se construit depuis
les dataclasses, pas depuis une liste de champs tenue à la main, et
`test_aucun_champ_n_echappe_a_l_aller_retour` échoue si un champ nouveau
n'entre pas dans le circuit.

Aucun fichier n'est lu : tout passe par `depuis_dict`. Les configurations sont
synthétiques — point fictif en mer, chiffres inventés.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ourouler.config import (
    Config,
    ParametresSeance,
    depuis_dict,
)
from ourouler.erreurs import ErreurConfig
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT

# Point fictif en mer, loin de toute ville : jamais une coordonnée réelle.
BASE = {
    "depart": {"nom": "Test", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 80, "ftp_w": 250},
}

#: Sections de `Config` qui sont une simple table de champs, dont le nom de
#: clé dans le fichier est celui du champ de la dataclasse.
SECTIONS_PLATES = (
    "depart",
    "cycliste",
    "meteo",
    "intervals",
    "cache",
    "brouter",
    "boucle",
    "calibration",
    "seance",
    "tenue",
)

#: Champs dont la clé de fichier diffère du nom du champ. `zones_pct` est
#: écrit `zones` sous `[seance]` : le suffixe dit l'unité, la clé du fichier
#: ne la porte pas.
CLE_FICHIER = {("seance", "zones_pct"): "zones"}

#: Champs de `Config` qui ne sont pas des sections plates et dont `reecrire`
#: s'occupe nommément.
CHAMPS_A_PART = ("velos", "evitements", "historique_depuis")


def _brut(valeur: Any) -> Any:
    """Une valeur de dataclass telle qu'elle s'écrit dans un fichier TOML."""
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, Path):
        return str(valeur)
    if isinstance(valeur, tuple):
        return [_brut(x) for x in valeur]
    return valeur


def _section(objet: Any, nom_section: str) -> dict[str, Any]:
    section = {}
    for champ in dataclasses.fields(objet):
        cle = CLE_FICHIER.get((nom_section, champ.name), champ.name)
        section[cle] = _brut(getattr(objet, champ.name))
    return section


def reecrire(config: Config) -> dict[str, Any]:
    """La configuration telle que le produit la réécrirait aujourd'hui.

    « Aujourd'hui » est le mot qui compte : on écrit les **champs** de la
    `Config`, c'est-à-dire ce qui est stocké, jamais une valeur dérivée ni une
    clé d'une génération précédente. Pour les zones, cela veut dire
    `position_zone` et jamais `puissance_endurance_pct` — décision 7 : « on
    stocke la position dans la zone, pas la valeur ».

    C'est exactement ce que fera la route d'API qui enregistre un profil, et
    c'est pour cela que l'aller-retour doit tenir : la route qui écrit ne doit
    pas produire un fichier que la route qui lit refuse.
    """
    d: dict[str, Any] = {nom: _section(getattr(config, nom), nom) for nom in SECTIONS_PLATES}
    # `tenues` s'écrit {catégorie = [vêtements]} dans le fichier, et se range
    # en couples figés dans la dataclass : le seul champ dont la forme change.
    d["tenue"]["tenues"] = {categorie: list(pieces) for categorie, pieces in config.tenue.tenues}
    d["velos"] = [
        {
            **_section(velo, "velos"),
            "periodes": [
                {"debut": p.debut.isoformat(), **({"fin": p.fin.isoformat()} if p.fin else {})}
                for p in velo.periodes
            ],
        }
        for velo in config.velos
    ]
    d["evitements"] = [_section(e, "evitements") for e in config.evitements]
    d["historique_depuis"] = config.historique_depuis.isoformat()
    return d


# --- l'invariant ------------------------------------------------------------

ZONES_ETROITES = [[0.0, 0.55], [0.70, 0.72], [0.73, 0.90], [0.91, 1.05]]
ZONES_LARGES = [[0.0, 0.50], [0.51, 0.70], [0.71, 0.95], [0.96, 1.20], [1.21, 2.00]]

#: Le balayage : des tables de zones très différentes, les deux générations de
#: clé, et des positions au bord du domaine accepté comme au milieu.
CONFIGURATIONS = [
    pytest.param({}, id="defauts"),
    pytest.param({"position_zone": 0.0}, id="bas-de-bande"),
    pytest.param({"position_zone": 1.0}, id="haut-de-bande"),
    pytest.param({"position_zone": -1.0}, id="borne-basse"),
    pytest.param({"position_zone": 2.0}, id="borne-haute"),
    pytest.param({"position_zone": -0.2737}, id="sous-la-bande-decision-8"),
    pytest.param({"puissance_endurance_pct": 0.40}, id="ancienne-cle-mini"),
    pytest.param({"puissance_endurance_pct": 0.60}, id="ancienne-cle-mesuree"),
    pytest.param({"puissance_endurance_pct": 0.80}, id="ancienne-cle-maxi"),
    pytest.param({"zones": ZONES_ETROITES, "position_zone": 0.5}, id="zones-etroites"),
    pytest.param({"zones": ZONES_ETROITES, "position_zone": -1.0}, id="zones-etroites-borne"),
    pytest.param({"zones": ZONES_ETROITES, "puissance_endurance_pct": 0.71}, id="etroites-ancienne"),
    pytest.param({"zones": ZONES_LARGES, "puissance_endurance_pct": 0.60}, id="larges-ancienne"),
    pytest.param({"zones": ZONES_LARGES, "position_zone": 1.5}, id="zones-larges"),
    pytest.param(
        {"zones": ZONES_ETROITES, "position_zone": 0.3, "puissance_endurance_pct": 0.40},
        id="les-deux-cles-la-nouvelle-gagne",
    ),
    # Le cas de la relecture F0, laissé dans le balayage à dessein : avant
    # correction il se chargeait sur −15,0 et le rechargement le refusait,
    # donc l'invariant échouait ici. Depuis, il est refusé au premier
    # chargement — et `charge_ou_refuse` distingue les deux.
    pytest.param(
        {"zones": ZONES_ETROITES, "puissance_endurance_pct": 0.40},
        id="cas-relecture-f0-refuse",
    ),
    pytest.param(
        {"zones": ZONES_LARGES, "puissance_endurance_pct": 0.80},
        id="larges-ancienne-haute",
    ),
]


def charge_ou_refuse(d: dict[str, Any]) -> Config | None:
    """La `Config`, ou `None` si le chargement la refuse en nommant le champ.

    Un refus au **premier** chargement n'est pas une violation de l'invariant :
    la configuration n'entre jamais dans le produit, donc rien ne la réécrira.
    Ce qui est interdit, c'est le chargement qui réussit puis le rechargement
    qui échoue — et c'est ce que cette fonction permet de séparer proprement
    au lieu d'attraper l'erreur n'importe où.
    """
    try:
        return depuis_dict(d)
    except ErreurConfig:
        return None

#: Une configuration complète, tous champs renseignés : l'aller-retour doit
#: tenir sur autre chose que les défauts. Rien de personnel — un point en mer,
#: une clé factice, des chiffres inventés.
COMPLETE = {
    "depart": {"nom": "Large", "latitude": 0.0, "longitude": 0.0},
    "cycliste": {"masse_kg": 72.5, "ftp_w": 263},
    "velos": [
        {
            "nom": "Route",
            "usage": "route",
            "masse_kg": 8.4,
            "cda_m2": 0.31,
            "crr": 0.005,
            "intervals_gear": "route",
            "intervals_gear_id": "b000000",
            "capteur_puissance": "CAPTEUR 0000",
            "facteur_compteur": 0.87,
            "periodes": [{"debut": "2024-01-01", "fin": "2024-12-31"}, {"debut": "2025-01-01"}],
        },
        {"nom": "CLM", "usage": "clm"},
    ],
    "meteo": {
        "directions": 16,
        "distances_km": [10.0, 25.0],
        "modele": "meteofrance_arome_france_hd",
        "second_avis": "icon_eu",
        "horizon_h": 48,
    },
    "intervals": {"athlete_id": "i0", "api_key": "cle-factice"},
    "cache": {"dossier": "/tmp/ourouler-test-cache"},
    "brouter": {
        "url": "http://exemple.invalid/brouter",
        "utilisateur": "personne",
        "mot_de_passe": "factice",
        "profil": "trekking",
        "timeout_s": 30.0,
    },
    "boucle": {
        "vitesse_moyenne_kmh": 27.0,
        "sens": "antihoraire",
        "candidates": 7,
        "tolerance_distance": 0.08,
    },
    "calibration": {"mots_groupe": ["groupe"], "part_validation": 0.25, "vitesse_min_kmh": 12.0},
    "seance": {
        "elasticite_z2_max": 0.3,
        "elasticite_z2_min": -0.1,
        "elasticite_calme_max": 1.2,
        "elasticite_calme_min": -0.02,
        "demi_tour_penalite": 2.0,
        "zones": ZONES_LARGES,
        "position_zone": 0.42,
        "seuil_recuperation_pct": 0.7,
        "tolerance_egalite": 0.2,
    },
    "tenue": {
        "bornes_c": [2.0, 8.0, 16.0],
        "bornes_pluie_mmh": [0.3, 0.9],
        "vent_veste_kmh": 25.0,
        "tenues": {"froid": ["veste", "gants"], "doux": ["maillot"]},
    },
    "evitements": [{"nom": "Zone test", "latitude": 0.5, "longitude": 0.5, "rayon_m": 500.0}],
    "historique_depuis": "2024-03-01",
}


@pytest.mark.parametrize("seance", CONFIGURATIONS)
def test_ce_qui_se_charge_se_recharge(seance):
    """Charger, réécrire comme le produit écrirait, recharger : la même chose.

    C'est l'invariant que la migration `puissance_endurance_pct → position_zone`
    avait cassé. Il n'est pas testé sur le seul cas trouvé mais sur un balayage
    de tables de zones et de positions : aucune configuration acceptée ne doit
    produire un fichier que le chargement suivant refuse, ni une `Config`
    différente de celle qu'on avait.

    Une configuration refusée au premier chargement sort du balayage : elle
    n'entre pas dans le produit, donc rien ne la réécrira. Le cas de la
    relecture F0 est dans la liste pour cette raison — c'est le seul du
    balayage qui doit prendre cette branche, et
    `test_l_aller_retour_mordrait_sur_le_defaut_d_origine` vérifie qu'il la
    prend bien pour le bon motif.
    """
    premiere = charge_ou_refuse({**BASE, "seance": seance})
    if premiere is None:
        return
    seconde = depuis_dict(reecrire(premiere))
    assert seconde == premiere
    # La troisième fois aussi : un aller-retour qui converge au deuxième tour
    # serait déjà un aller-retour qui ne tient pas.
    assert depuis_dict(reecrire(seconde)) == premiere


def test_ce_qui_se_charge_se_recharge_sur_une_configuration_complete():
    """Le même invariant, tous champs renseignés et aucun laissé au défaut."""
    premiere = depuis_dict(COMPLETE)
    seconde = depuis_dict(reecrire(premiere))
    assert seconde == premiere
    assert depuis_dict(reecrire(seconde)) == premiere


@pytest.mark.parametrize("seance", CONFIGURATIONS)
def test_la_puissance_d_endurance_derivee_survit_a_l_aller_retour(seance):
    """Ce n'est pas seulement la position qui revient : la puissance aussi.

    Règle absolue 5 : si un aller-retour changeait la puissance d'endurance
    même de peu, il changerait les étapes prescrites en zone de FC basse sans
    que personne ne le voie. L'égalité est exacte, pas approchée —
    `zones.DECIMALES_PCT` est là pour ça.
    """
    premiere = charge_ou_refuse({**BASE, "seance": seance})
    if premiere is None:
        return
    seconde = depuis_dict(reecrire(premiere))
    assert seconde.seance.puissance_endurance_pct == premiere.seance.puissance_endurance_pct


def test_aucun_champ_n_echappe_a_l_aller_retour():
    """La garde de la propriété : un champ nouveau entre dans le circuit ou fait échouer.

    Sans elle, le prochain champ ajouté à une section serait écrit par
    `reecrire`, relu par `depuis_dict`… et l'invariant passerait au vert sans
    rien vérifier le jour où quelqu'un ajouterait une section entière que
    `SECTIONS_PLATES` ignore.
    """
    connus = set(SECTIONS_PLATES) | set(CHAMPS_A_PART)
    champs = {f.name for f in dataclasses.fields(Config)}
    assert champs == connus, (
        f"Config a changé : {champs ^ connus}. Ajoutez le champ à SECTIONS_PLATES "
        "(table de champs) ou à CHAMPS_A_PART (et à `reecrire`)."
    )
    # Et chaque champ de chaque section plate doit ressortir dans l'écriture.
    config = depuis_dict(COMPLETE)
    ecrit = reecrire(config)
    for nom_section in SECTIONS_PLATES:
        attendus = {
            CLE_FICHIER.get((nom_section, f.name), f.name)
            for f in dataclasses.fields(getattr(config, nom_section))
        }
        assert set(ecrit[nom_section]) == attendus


def test_la_puissance_d_endurance_n_est_jamais_reecrite():
    """Décision 7 : on stocke la position, jamais la valeur.

    Si `reecrire` reposait l'ancienne clé à côté de la nouvelle, l'invariant
    tiendrait quand même (`position_zone` l'emporte) tout en laissant le
    produit republier une valeur figée à côté d'une table qui bouge — la dette
    exacte que la décision 7 retire.
    """
    ecrit = reecrire(depuis_dict({**BASE, "seance": {"puissance_endurance_pct": 0.60}}))
    assert "puissance_endurance_pct" not in ecrit["seance"]
    assert "position_zone" in ecrit["seance"]
    # La propriété dérivée n'est pas un champ : la garde ci-dessus le dit aussi,
    # mais elle se lit mieux ici.
    assert "puissance_endurance_pct" not in {f.name for f in dataclasses.fields(ParametresSeance)}


def test_l_aller_retour_mordrait_sur_le_defaut_d_origine():
    """La preuve que le test aurait vu le défaut : le cas exact de la relecture.

    Avant correction, cette configuration se chargeait sur
    `position_zone = −15,0` et la relecture la refusait. Elle est désormais
    refusée au premier chargement — donc elle n'entre jamais dans l'invariant,
    qui ne peut plus être pris en défaut par elle.
    """
    fautive = {**BASE, "seance": {"zones": ZONES_ETROITES, "puissance_endurance_pct": 0.40}}
    with pytest.raises(ErreurConfig, match="ne peut pas se convertir en position"):
        depuis_dict(fautive)


def test_le_balayage_n_est_pas_vide_de_sens():
    """Un balayage dont tout serait refusé passerait au vert sans rien tester.

    Un seul cas du balayage doit prendre la branche « refusé » : celui de la
    relecture F0. Si un autre s'y mettait — parce qu'une borne a bougé — la
    propriété se viderait en silence, et c'est cette ligne qui le dirait.
    """
    refuses = [
        cas.id
        for cas in CONFIGURATIONS
        if charge_ou_refuse({**BASE, "seance": cas.values[0]}) is None
    ]
    assert refuses == ["cas-relecture-f0-refuse"]


@pytest.mark.parametrize("pct", [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80])
def test_aucune_configuration_d_avant_la_decision_7_n_est_bloquee(pct):
    """Le coût du refus, mesuré : il est nul pour les configurations existantes.

    `zones` n'existait pas quand `puissance_endurance_pct` s'écrivait : une
    configuration de cette génération est donc lue avec la table par défaut.
    Sur tout le domaine accepté de l'ancienne clé, la conversion y tient dans
    les bornes — le refus ne peut atteindre qu'un fichier qui mélange les deux
    générations de réglages.
    """
    c = depuis_dict({**BASE, "seance": {"puissance_endurance_pct": pct}})
    assert c.seance.zones_pct == ZONES_PUISSANCE_DEFAUT
    assert -1.0 <= c.seance.position_zone <= 2.0
    assert c.seance.puissance_endurance_pct == pct

"""Rattachement au vélo et inventaire, mis à l'épreuve.

La règle de rattachement est ordonnée : (1 intérieur, 2 capteur de
puissance, 3 équipement — par `gear_id` ou par nom, 4 période, 5 premier vélo
« route »). La moitié des tests ici vérifie l'**ordre**, pas seulement chaque
règle prise à part.

Les `EntreeCache` sont fabriquées directement (`outils.fabriquer`) : les tests
ne supposent ni l'ordre ni les défauts des champs, ni sous quelle clé de `meta`
le cache range `equipement`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import outils
import pytest

from ourouler.activites import cache as module_cache
from ourouler.activites import inventaire as module_inventaire
from ourouler.config import depuis_dict
from ourouler.noyau.erreurs import ErreurUtilisateur

HOME_TRAINER = "home-trainer"
DEBUT_REF = datetime(2024, 3, 15, 12, 0, tzinfo=UTC)


def _config(velos: list[dict], **reste):
    return depuis_dict(
        {
            "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 80.0, "ftp_w": 250.0},
            "velos": velos,
            **reste,
        }
    )


#: Deux vélos « route » qui se succèdent dans le temps, plus un CLM en tête de
#: liste pour que la règle 5 (« premier vélo d'usage route ») soit distinguable
#: d'un simple « premier vélo de la liste ».
VELOS = [
    {"nom": "Chrono", "usage": "clm", "intervals_gear": ""},
    {
        "nom": "Alpha",
        "usage": "route",
        "intervals_gear": "gear-alpha",
        "periodes": [{"debut": "2024-01-01", "fin": "2024-06-30"}],
    },
    {
        "nom": "Beta",
        "usage": "route",
        "intervals_gear": "gear-beta",
        "periodes": [{"debut": "2024-07-01"}],
    },
]
NOMS_VELOS = {"Chrono", "Alpha", "Beta", HOME_TRAINER}


def _entree(module, **surcharges):
    valeurs = {
        "identifiant": "0" * 64,
        "source": "intervals",
        "id_externe": "a1",
        "debut": DEBUT_REF,
        "duree_s": 3600.0,
        "distance_m": 30000.0,
        "puissance_moy_w": 200.0,
        "sport": "Ride",
        "appareil": "Compteur Fictif 1000",
        "equipement": None,
        "chemin": Path("brut") / ("0" * 64 + ".fit"),
        "meta": {},
    }
    valeurs.update(surcharges)
    return outils.fabriquer(module.EntreeCache, valeurs)


def _rattacher(module, config, **surcharges) -> str:
    resultat = module.rattacher_velo(_entree(module, **surcharges), config)
    assert isinstance(resultat, str) and resultat, "rattacher_velo renvoie un nom de vélo non vide"
    assert resultat in NOMS_VELOS, f"nom inattendu : {resultat!r} (attendu parmi {sorted(NOMS_VELOS)})"
    return resultat


# --- règle 3 : équipement ----------------------------------------------------


@pytest.mark.parametrize("equipement", ["gear-beta", "GEAR-BETA", "Gear-Beta", "gEaR-bEtA"])
def test_equipement_insensible_a_la_casse(equipement):
    module = module_inventaire
    assert _rattacher(module, _config(VELOS), equipement=equipement, debut=DEBUT_REF) == "Beta", (
        "l'équipement (règle 3) doit primer sur la période (règle 4), quelle que soit la casse"
    )


@pytest.mark.parametrize("equipement", [None, "", "   ", "gear-inconnu"])
def test_equipement_vide_ou_inconnu_ne_capture_pas(equipement):
    """`intervals_gear` valant "" ne doit pas attraper les sorties sans équipement.

    Le vélo « Chrono » a un `intervals_gear` vide : si l'implémentation
    compare deux chaînes vides, elle lui rattache tout le reste, alors que la
    règle 5 désigne le premier vélo d'usage *route*.
    """
    module = module_inventaire
    resultat = _rattacher(
        module, _config(VELOS), equipement=equipement, debut=datetime(2023, 5, 1, 12, tzinfo=UTC)
    )
    assert resultat != "Chrono", "un intervals_gear vide ne doit rien capturer"
    assert resultat == "Alpha", "règle 5 : premier vélo d'usage route"


# --- règle 4 : période -------------------------------------------------------


@pytest.mark.parametrize(
    "jour, attendu",
    [
        (datetime(2024, 1, 1, 8, tzinfo=UTC), "Alpha"),
        (datetime(2024, 3, 15, 12, tzinfo=UTC), "Alpha"),
        (datetime(2024, 6, 30, 12, tzinfo=UTC), "Alpha"),
        (datetime(2024, 7, 1, 12, tzinfo=UTC), "Beta"),
        (datetime(2026, 9, 12, 12, tzinfo=UTC), "Beta"),
    ],
)
def test_periode_rattache_le_bon_velo(jour, attendu):
    module = module_inventaire
    assert _rattacher(module, _config(VELOS), debut=jour) == attendu


def test_sortie_hors_de_toute_periode_tombe_sur_le_premier_velo_route():
    module = module_inventaire
    assert _rattacher(module, _config(VELOS), debut=datetime(2023, 11, 30, 10, tzinfo=UTC)) == "Alpha"


def test_bascule_de_periode_a_cheval_sur_minuit_utc():
    """22:30 UTC le dernier jour d'Alpha, soit le lendemain (jour de Beta) à Paris.

    Le contrat ne dit pas si la période se compare à la date UTC ou à la date
    locale. On exige seulement une réponse dans les deux candidats, pas un
    repli sur le home-trainer ni sur un troisième vélo.
    """
    module = module_inventaire
    resultat = _rattacher(module, _config(VELOS), debut=datetime(2024, 6, 30, 22, 30, tzinfo=UTC))
    assert resultat in ("Alpha", "Beta"), f"reçu {resultat!r}"


def test_debut_naif_ne_fait_pas_planter_le_rattachement():
    module = module_inventaire
    outils.robuste(
        lambda: module.rattacher_velo(_entree(module, debut=datetime(2024, 3, 15, 12)), _config(VELOS)),
        quoi="rattacher_velo(debut naïf)",
        erreurs_acceptees=(ErreurUtilisateur, TypeError),
    )


# --- règle 1 : sport intérieur ----------------------------------------------


@pytest.mark.parametrize("sport", ["VirtualRide", "virtualride", "VIRTUALRIDE"])
def test_virtual_ride_va_au_home_trainer(sport):
    module = module_inventaire
    resultat = _rattacher(module, _config(VELOS), sport=sport, debut=datetime(2023, 5, 1, 12, tzinfo=UTC))
    assert resultat == HOME_TRAINER


@pytest.mark.parametrize(
    "appareil",
    [
        "ZWIFT",
        "zwift",
        "Zwift",
        "ZWIFT\u00a0Runtime\u200b v1.2  ",
        "Zwift (build 42)",
        "\tzwift\n",
        "ROUVY",
        "Rouvy AR",
    ],
)
def test_appareil_interieur_meme_sali_va_au_home_trainer(appareil):
    """Le nom d'appareil arrive tel que la source le donne : casse, espaces
    insécables, espaces de largeur nulle, tabulations."""
    module = module_inventaire
    resultat = _rattacher(
        module, _config(VELOS), appareil=appareil, sport="Ride", debut=datetime(2023, 5, 1, 12, tzinfo=UTC)
    )
    assert resultat == HOME_TRAINER, f"appareil {appareil!r} non reconnu comme intérieur"


@pytest.mark.parametrize("appareil", ["Garmin Edge 530", "Wahoo ELEMNT BOLT", "", None])
def test_appareil_exterieur_ne_va_pas_au_home_trainer(appareil):
    module = module_inventaire
    resultat = _rattacher(
        module, _config(VELOS), appareil=appareil, sport="Ride", debut=datetime(2023, 5, 1, 12, tzinfo=UTC)
    )
    assert resultat != HOME_TRAINER, f"appareil {appareil!r} classé à tort en intérieur"


def test_meta_interieur_vrai_va_au_home_trainer():
    module = module_inventaire
    resultat = _rattacher(
        module,
        _config(VELOS),
        meta={"interieur": True},
        debut=datetime(2023, 5, 1, 12, tzinfo=UTC),
    )
    assert resultat == HOME_TRAINER


def test_meta_interieur_faux_ne_suffit_pas():
    """`meta["interieur"] = False` : c'est la valeur qui compte, pas la présence de la clé."""
    module = module_inventaire
    resultat = _rattacher(
        module,
        _config(VELOS),
        meta={"interieur": False},
        appareil="Garmin Edge 530",
        debut=datetime(2023, 5, 1, 12, tzinfo=UTC),
    )
    assert resultat != HOME_TRAINER, 'la seule présence de meta["interieur"] ne doit rien décider'


# --- ordre des règles --------------------------------------------------------


def test_equipement_prime_sur_la_periode():
    """Règle (3) `gear_id` / équipement avant (4) période."""
    module = module_inventaire
    resultat = _rattacher(module, _config(VELOS), equipement="gear-beta", debut=DEBUT_REF)
    assert resultat == "Beta", "règle 3 avant règle 4 (la période de mars 2024 est celle d'Alpha)"


def test_l_interieur_prime_sur_l_equipement():
    """Règle (1) intérieur avant (3) `gear_id` / équipement.

    Une séance de home-trainer faite avec le capteur et l'équipement du vélo de
    route reste une séance d'intérieur : sinon elle serait comptée en sortie
    extérieure et fausserait les kilomètres du vélo.
    """
    module = module_inventaire
    resultat = _rattacher(
        module,
        _config(VELOS),
        equipement="gear-alpha",
        sport="VirtualRide",
        appareil="ZWIFT",
        meta={"interieur": True},
        debut=datetime(2023, 5, 1, 12, tzinfo=UTC),
    )
    assert resultat == HOME_TRAINER, "règle 1 avant règle 3"


def test_l_interieur_prime_sur_la_periode():
    """Règle (1) intérieur avant (4) période."""
    module = module_inventaire
    resultat = _rattacher(module, _config(VELOS), sport="VirtualRide", appareil="ZWIFT", debut=DEBUT_REF)
    assert resultat == HOME_TRAINER, "règle 1 avant règle 4"


def test_aucun_velo_de_route_configure():
    """Le contrat ne dit pas quoi faire si la règle 5 n'a pas de candidat."""
    module = module_inventaire
    config = _config([{"nom": "Chrono", "usage": "clm"}])
    resultat, erreur = outils.robuste(
        lambda: module.rattacher_velo(_entree(module, debut=datetime(2023, 5, 1, 12, tzinfo=UTC)), config),
        quoi="rattacher_velo sans vélo de route",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert resultat in ("Chrono", HOME_TRAINER), f"reçu {resultat!r}"


def test_deux_velos_pour_la_meme_periode():
    """Périodes qui se recouvrent : une réponse, laquelle qu'elle soit, jamais un plantage."""
    module = module_inventaire
    config = _config(
        [
            {"nom": "Alpha", "usage": "route", "periodes": [{"debut": "2024-01-01"}]},
            {"nom": "Beta", "usage": "route", "periodes": [{"debut": "2024-01-01"}]},
        ]
    )
    resultat = module.rattacher_velo(_entree(module, debut=DEBUT_REF), config)
    assert resultat in ("Alpha", "Beta"), f"reçu {resultat!r}"


# --- inventaire et rendus ----------------------------------------------------

GPX_SUR_PLACE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>\n'
    + "".join(
        f'<trkpt lat="0.000000" lon="0.000000"><ele>10.0</ele>'
        f"<time>2026-04-12T10:{minute:02d}:00Z</time></trkpt>\n"
        for minute in range(0, 40, 2)
    )
    + "</trkseg></trk></gpx>\n"
).encode("utf-8")
"""Vingt points au même endroit sur 38 min : distance nulle, aucune puissance."""


def _cache_avec(tmp_path, contenus: dict[str, bytes]):
    module = module_cache
    source = tmp_path / "a_importer"
    source.mkdir(exist_ok=True)
    for nom, octets in contenus.items():
        (source / nom).write_bytes(octets)
    cache = module.Cache(tmp_path / "cache")
    cache.indexer_dossier(source)
    return cache


def test_inventaire_vide_ne_divise_pas_par_zero(tmp_path):
    """Un cache vide : « % avec puissance » sur zéro sortie ne doit pas exploser."""
    module = module_inventaire
    cache_module = module_cache
    cache = cache_module.Cache(tmp_path / "cache")
    inv = module.inventaire(cache, _config(VELOS), date(2023, 12, 1))
    texte = module.rendre_texte(inv)
    assert isinstance(texte, str) and texte.strip(), "un inventaire vide doit se rendre en texte lisible"
    donnees = module.rendre_json(inv)
    assert isinstance(donnees, dict)
    outils.verifier_json(donnees, "rendre_json(inventaire vide)")


def test_velo_sans_aucune_sortie(tmp_path, hostiles):
    """Deux vélos sur trois n'ont rien roulé : « % avec puissance » sur 0 sortie.

    C'est le cas qui divise par zéro dans une implémentation qui parcourt les
    vélos de la configuration plutôt que les seules sorties trouvées.
    """
    module = module_inventaire
    cache = _cache_avec(tmp_path, {"a.gpx": hostiles["nominal.gpx"].read_bytes()})
    inv = module.inventaire(cache, _config(VELOS), date(2023, 12, 1))
    brut = outils.verifier_json(module.rendre_json(inv), "rendre_json(inventaire partiel)")
    assert "NaN" not in brut and "Infinity" not in brut, f"valeur non finie dans le JSON : {brut}"
    assert module.rendre_texte(inv).strip()


def test_inventaire_json_serialisable_et_texte_non_vide(tmp_path, hostiles):
    module = module_inventaire
    cache = _cache_avec(
        tmp_path,
        {
            "a.gpx": hostiles["nominal.gpx"].read_bytes(),
            "b.tcx": hostiles["nominal.tcx"].read_bytes(),
            "c.fit": hostiles["nominal.fit"].read_bytes(),
        },
    )
    inv = module.inventaire(cache, _config(VELOS), date(2023, 12, 1))
    donnees = module.rendre_json(inv)
    brut = outils.verifier_json(donnees, "rendre_json(inventaire)")
    assert json.loads(brut) == donnees
    assert module.rendre_texte(inv).strip()


def test_le_parametre_depuis_est_respecte(tmp_path, hostiles):
    """Un `depuis` postérieur à toutes les sorties doit rendre l'inventaire vide.

    On compare au même inventaire calculé sur un cache vide : c'est la seule
    façon de le vérifier sans connaître les noms de champs d'`Inventaire`.
    """
    module = module_inventaire
    cache_module = module_cache
    plein = _cache_avec(tmp_path, {"a.gpx": hostiles["nominal.gpx"].read_bytes()})
    vide = cache_module.Cache(tmp_path / "cache_vide")
    config = _config(VELOS)
    apres = module.rendre_json(module.inventaire(plein, config, date(2030, 1, 1)))
    temoin = module.rendre_json(module.inventaire(vide, config, date(2030, 1, 1)))
    assert apres == temoin, "les sorties antérieures à `depuis` ne doivent pas être comptées"


def test_anomalies_detectees(tmp_path, hostiles, generateur):
    """Sortie de 5 min, sortie à distance nulle et sans puissance : au moins une anomalie."""
    module = module_inventaire
    cache = _cache_avec(
        tmp_path,
        {
            "courte.gpx": generateur.gpx(nb_points=6),  # 5 min
            "sur_place.gpx": GPX_SUR_PLACE,  # distance nulle, sans puissance
            "sans_puissance.gpx": hostiles["gpx_sans_puissance.gpx"].read_bytes(),
        },
    )
    donnees = module.rendre_json(module.inventaire(cache, _config(VELOS), date(2023, 12, 1)))
    outils.verifier_json(donnees, "rendre_json(inventaire)")
    listes = outils.trouver_cle(donnees, "anomal")
    assert listes, "rendre_json doit exposer les anomalies (clé contenant « anomalies »)"
    assert any(liste for liste in listes), f"aucune anomalie signalée : {listes}"


def test_pas_d_anomalie_sur_des_sorties_saines(tmp_path, hostiles):
    module = module_inventaire
    cache = _cache_avec(
        tmp_path,
        {
            "a.fit": hostiles["nominal.fit"].read_bytes(),
            "b.tcx": hostiles["nominal.tcx"].read_bytes(),
        },
    )
    donnees = module.rendre_json(module.inventaire(cache, _config(VELOS), date(2023, 12, 1)))
    for liste in outils.trouver_cle(donnees, "anomal"):
        assert not liste, f"anomalie signalée à tort sur des sorties saines : {liste}"


# --- CLI ---------------------------------------------------------------------


def _main():
    from ourouler.cli import main

    return main


def test_cli_inventaire_sur_cache_vide(ecrire_config, capsys):
    main = _main()
    chemin = ecrire_config()
    code, _ = outils.robuste(
        lambda: main(["--config", str(chemin), "inventaire"]),
        quoi="ourouler inventaire (cache vide)",
        erreurs_acceptees=(),
    )
    assert code == 0, f"code {code}, sortie : {capsys.readouterr()}"


def test_cli_importer_dossier_absent(ecrire_config, tmp_path, capsys):
    main = _main()
    chemin = ecrire_config()
    code, _ = outils.robuste(
        lambda: main(["--config", str(chemin), "inventaire", "--importer", str(tmp_path / "nulle_part")]),
        quoi="ourouler inventaire --importer <absent>",
        erreurs_acceptees=(),
    )
    assert code == 2, "un dossier d'import absent est une erreur utilisateur (code 2)"
    assert capsys.readouterr().err.strip(), "le message doit partir sur stderr"


def test_cli_depuis_invalide(ecrire_config, capsys):
    main = _main()
    chemin = ecrire_config()
    code, erreur = outils.robuste(
        lambda: main(["--config", str(chemin), "inventaire", "--depuis", "hier"]),
        quoi="ourouler inventaire --depuis hier",
        erreurs_acceptees=(SystemExit,),
    )
    if erreur is not None:  # argparse a refusé l'argument lui-même
        assert erreur.code == 2, f"sortie argparse avec le code {erreur.code}"
    else:
        assert code == 2, "une date illisible doit donner le code 2, pas une trace"
    assert capsys.readouterr().err.strip(), "le motif du refus doit être dit sur stderr"


def test_cli_synchroniser_sans_cle(ecrire_config, capsys):
    """Sans clé Intervals, la commande doit refuser proprement — et sans réseau."""
    main = _main()
    chemin = ecrire_config()
    code, _ = outils.robuste(
        lambda: main(["--config", str(chemin), "inventaire", "--synchroniser"]),
        quoi="ourouler inventaire --synchroniser sans clé",
        erreurs_acceptees=(),
    )
    assert code == 2, "clé absente = erreur utilisateur"
    sortie = capsys.readouterr()
    assert sortie.err.strip(), "le message doit nommer ce qui manque"
    assert outils.CLE_BIDON not in (sortie.out + sortie.err)

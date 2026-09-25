"""L2.7 — rattachement par capteur et métadonnées Intervals, mis à l'épreuve.

Cible : contrat du sprint 2 §7. L'ordre des règles **change** par rapport au
sprint 1 : (1) intérieur, (2) capteur de puissance, (3) identifiant ou nom
d'équipement, (4) période, (5) premier vélo route. La moitié de ce fichier
vérifie l'ordre, pas les règles prises à part : c'est là que se logent les
régressions, et c'est ce qui sépare les deux vélos du mainteneur.

Aucune valeur réelle ici : les capteurs et les identifiants d'équipement du
mainteneur restent dans `docs/` (voir `test_adv_invariants`), les tests
utilisent des noms inventés.

Tant que le lot n'est pas livré, les tests se **skippent** explicitement
(le module du sprint 1 existe déjà, `importorskip` ne suffit donc pas) : la
sonde regarde si le code connaît seulement la notion de capteur.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import outils
import pytest
from fabriques import EspionHttp

from ourouler.config import depuis_dict
from ourouler.noyau.erreurs import ErreurUtilisateur

MOTIF_INVENTAIRE = "module attendu absent (ourouler.activites.inventaire)"
MOTIF_CACHE = "module attendu absent (ourouler.activites.cache)"
MOTIF_INTERVALS = "module attendu absent (ourouler.connecteurs.intervals)"
MOTIF_L27 = "L2.7 non livré dans ce worktree (rattachement par capteur absent du code)"
MOTIF_RAFRAICHIR = "L2.7 non livré : `synchroniser` n'a pas encore de paramètre `rafraichir_meta`"

HOME_TRAINER = "home-trainer"
DEBUT_REF = datetime(2024, 3, 15, 12, 0, tzinfo=UTC)  # dans la période d'Alpha

CAPTEUR_ALPHA = "CAPTEUR ALPHA 1234"
CAPTEUR_BETA = "CAPTEUR BETA 5678"

VELOS = [
    # En tête de liste et sans rien : la règle 5 doit désigner le premier vélo
    # *route*, pas le premier vélo tout court.
    {"nom": "Chrono", "usage": "clm"},
    {
        "nom": "Alpha",
        "usage": "route",
        "capteur_puissance": CAPTEUR_ALPHA,
        "intervals_gear": "Vélo Alpha",
        "intervals_gear_id": "g-alpha",
        "periodes": [{"debut": "2024-01-01", "fin": "2024-06-30"}],
    },
    {
        "nom": "Beta",
        "usage": "route",
        "capteur_puissance": CAPTEUR_BETA,
        "intervals_gear": "Vélo Beta",
        "intervals_gear_id": "g-beta",
        "periodes": [{"debut": "2024-07-01"}],
    },
]
NOMS_VELOS = {"Chrono", "Alpha", "Beta", HOME_TRAINER, "inconnu"}


def _inventaire():
    return pytest.importorskip("ourouler.activites.inventaire", reason=MOTIF_INVENTAIRE)


def _cache_module():
    return pytest.importorskip("ourouler.activites.cache", reason=MOTIF_CACHE)


def _intervals():
    return pytest.importorskip("ourouler.connecteurs.intervals", reason=MOTIF_INTERVALS)


def _exiger_l27(module):
    """Le module existe depuis le sprint 1 : ce qui manque, c'est la notion de capteur."""
    try:
        source = inspect.getsource(module)
    except OSError:  # pragma: no cover - module sans source lisible
        return
    if "capteur_puissance" not in source:
        pytest.skip(MOTIF_L27)


def _config(velos=None, **reste):
    return depuis_dict(
        {
            "depart": {"nom": "Point fictif", "latitude": 0.0, "longitude": 0.0},
            "cycliste": {"masse_kg": 80.0, "ftp_w": 250.0},
            "velos": VELOS if velos is None else velos,
            **reste,
        }
    )


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


def _rattacher(config=None, **surcharges) -> str:
    inventaire = _inventaire()
    _exiger_l27(inventaire)
    cache = _cache_module()
    resultat = inventaire.rattacher_velo(_entree(cache, **surcharges), config or _config())
    assert isinstance(resultat, str) and resultat, "rattacher_velo rend un nom de vélo non vide"
    assert resultat in NOMS_VELOS, f"nom inattendu : {resultat!r} (attendu parmi {sorted(NOMS_VELOS)})"
    return resultat


# --- règle 1 : intérieur, avant tout -----------------------------------------


@pytest.mark.parametrize(
    "surcharges, quoi",
    [
        ({"sport": "VirtualRide"}, "sport VirtualRide"),
        ({"sport": "Ride", "meta": {"trainer": True}}, "meta trainer"),
        ({"appareil": "Zwift"}, "appareil Zwift"),
        ({"appareil": "Rouvy Companion"}, "appareil Rouvy"),
        ({"meta": {"interieur": True}}, "meta interieur"),
    ],
)
def test_l_interieur_prime_sur_le_capteur(surcharges, quoi):
    """Nouvel ordre : le home-trainer passe avant le capteur, qui est le même dedans que dehors."""
    meta = dict(surcharges.pop("meta", {}))
    meta["power_meter"] = CAPTEUR_ALPHA
    resultat = _rattacher(meta=meta, **surcharges)
    assert resultat == HOME_TRAINER, (
        f"{quoi} avec le capteur du vélo Alpha : c'est une sortie en intérieur, "
        f"reçu « {resultat} » — le capteur reste sur le vélo quand il est sur les rouleaux"
    )


def test_l_interieur_prime_aussi_sur_la_periode_et_l_equipement():
    resultat = _rattacher(
        sport="VirtualRide",
        equipement="Vélo Beta",
        debut=DEBUT_REF,
        meta={"gear_id": "g-beta"},
    )
    assert resultat == HOME_TRAINER


# --- règle 2 : capteur de puissance ------------------------------------------


@pytest.mark.parametrize(
    "capteur",
    [CAPTEUR_BETA, CAPTEUR_BETA.lower(), CAPTEUR_BETA.title(), f"  {CAPTEUR_BETA}  "],
)
def test_le_capteur_rattache_quelle_que_soit_la_casse(capteur):
    """Contrat §7 : le champ vient d'Intervals, sa casse n'est pas garantie."""
    resultat = _rattacher(meta={"power_meter": capteur}, debut=DEBUT_REF)
    assert resultat == "Beta", (
        f"power_meter = {capteur!r} : le vélo Beta porte ce capteur, reçu « {resultat} » "
        "(la période de la sortie désigne Alpha, le capteur doit primer)"
    )


def test_le_capteur_prime_sur_l_identifiant_d_equipement():
    resultat = _rattacher(meta={"power_meter": CAPTEUR_ALPHA, "gear_id": "g-beta"})
    assert resultat == "Alpha", (
        "règle 2 avant règle 3 : le capteur est mesuré, l'identifiant d'équipement est déclaratif"
    )


def test_le_capteur_prime_sur_le_nom_d_equipement():
    resultat = _rattacher(meta={"power_meter": CAPTEUR_ALPHA}, equipement="Vélo Beta")
    assert resultat == "Alpha"


def test_un_capteur_vide_ne_capture_rien():
    """Un vélo sans `capteur_puissance` ne doit pas attraper les sorties sans capteur."""
    velos = [dict(VELOS[0]), dict(VELOS[1], capteur_puissance=""), dict(VELOS[2])]
    resultat = _rattacher(
        config=_config(velos), meta={"power_meter": ""}, debut=datetime(2024, 8, 1, 9, tzinfo=UTC)
    )
    assert resultat == "Beta", (
        f"deux chaînes vides ne se ressemblent pas : la période d'août désigne Beta, reçu « {resultat} »"
    )


def test_un_capteur_inconnu_laisse_les_regles_suivantes_travailler():
    resultat = _rattacher(meta={"power_meter": "CAPTEUR QUI N'EXISTE PAS"}, debut=DEBUT_REF)
    assert resultat == "Alpha", "capteur inconnu : on retombe sur la période, pas sur « inconnu »"


@pytest.mark.parametrize(
    "power_meter", [None, 0, 17, ["liste"], {"nom": "dict"}, True]
)
def test_un_power_meter_d_un_type_inattendu_ne_fait_pas_planter(power_meter):
    _exiger_l27(_inventaire())  # hors de `robuste` : un skip n'est pas un échec du code testé
    resultat, erreur = outils.robuste(
        lambda: _rattacher(meta={"power_meter": power_meter}, debut=DEBUT_REF),
        quoi=f"rattacher_velo(power_meter={power_meter!r})",
        erreurs_acceptees=(ErreurUtilisateur,),
    )
    if erreur is None:
        assert resultat == "Alpha", f"power_meter={power_meter!r} ne désigne aucun vélo"


@pytest.mark.parametrize("brut", ["null", "[1, 2]", '"du texte"', "pas du json"])
def test_le_cache_garantit_une_meta_dictionnaire(tmp_path, hostiles, brut):
    """`rattacher_velo` n'a pas à se défendre contre une `meta` qui n'est pas un dict.

    C'est le cache qui doit le garantir : la colonne `meta` de l'index SQLite
    est du JSON, et un index corrompu (ou écrit par une version antérieure) ne
    doit pas faire tomber l'inventaire en `AttributeError`. On corrompt donc
    l'index et on vérifie l'invariant là où il se tient.
    """
    import sqlite3

    cache = _cache_module().Cache(tmp_path / "cache")
    cache.ajouter(
        hostiles["nominal.gpx"].read_bytes(),
        source="intervals",
        id_externe="i1",
        extension="gpx",
        meta={"sport": "Ride"},
    )
    with sqlite3.connect(cache.index) as cx:
        cx.execute("UPDATE activites SET meta = ?", (brut,))

    entree = cache.lister()[0]
    assert isinstance(entree.meta, dict), (
        f"meta = {entree.meta!r} après une colonne JSON contenant {brut!r} : "
        "le cache doit rendre un dictionnaire, toujours"
    )
    inventaire = _inventaire()
    _exiger_l27(inventaire)
    assert inventaire.rattacher_velo(entree, _config()) in NOMS_VELOS


# --- `bilateral` ne discrimine pas -------------------------------------------


@pytest.mark.parametrize("bilateral", [True, False, None])
def test_bilateral_sans_capteur_ne_rattache_rien(bilateral):
    """Contrat §7 : `bilateral` est une métadonnée, pas une règle de rattachement.

    Sans `power_meter`, une sortie bilatérale doit être rattachée exactement
    comme une sortie sans cette information : deviner « CLM » à partir de
    `avg_lr_balance` reviendrait à affirmer sans mesure (règle absolue 5).
    """
    temoin = _rattacher(meta={}, debut=DEBUT_REF)
    resultat = _rattacher(meta={"bilateral": bilateral}, debut=DEBUT_REF)
    assert resultat == temoin, (
        f"bilateral={bilateral!r} change le rattachement (« {temoin} » → « {resultat} ») "
        "alors qu'aucun capteur n'est nommé"
    )
    assert resultat != "Chrono", "le vélo de CLM ne se devine pas à l'équilibre gauche/droite"


def test_bilateral_ne_prime_pas_sur_le_capteur():
    resultat = _rattacher(meta={"power_meter": CAPTEUR_ALPHA, "bilateral": True}, debut=DEBUT_REF)
    assert resultat == "Alpha", "le capteur nommé prime sur toute déduction"


# --- règles 3 à 5 -------------------------------------------------------------


def test_l_identifiant_d_equipement_prime_sur_la_periode():
    resultat = _rattacher(meta={"gear_id": "g-beta"}, debut=DEBUT_REF)
    assert resultat == "Beta", "la période de mars 2024 désigne Alpha : gear_id doit primer"


def test_le_nom_d_equipement_prime_sur_la_periode():
    resultat = _rattacher(equipement="vélo beta", debut=DEBUT_REF)
    assert resultat == "Beta", "le nom d'équipement se compare sans tenir compte de la casse"


def test_un_gear_id_vide_ne_capture_rien():
    velos = [dict(VELOS[0]), dict(VELOS[1], intervals_gear_id=""), dict(VELOS[2])]
    resultat = _rattacher(
        config=_config(velos), meta={"gear_id": ""}, debut=datetime(2024, 8, 1, 9, tzinfo=UTC)
    )
    assert resultat == "Beta"


@pytest.mark.parametrize(
    "jour, attendu",
    [
        (datetime(2024, 1, 1, 8, tzinfo=UTC), "Alpha"),
        (datetime(2024, 6, 30, 23, tzinfo=UTC), "Alpha"),
        (datetime(2024, 7, 1, 0, tzinfo=UTC), "Beta"),
        (datetime(2026, 9, 13, 12, tzinfo=UTC), "Beta"),
    ],
)
def test_la_periode_rattache_quand_rien_d_autre_ne_parle(jour, attendu):
    assert _rattacher(debut=jour) == attendu


def test_hors_periode_on_retombe_sur_le_premier_velo_route():
    resultat = _rattacher(debut=datetime(2023, 5, 1, 12, tzinfo=UTC))
    assert resultat == "Alpha", "règle 5 : le premier vélo d'usage route, pas le premier de la liste"


def test_l_ordre_complet_des_cinq_regles():
    """Une entrée qui satisfait tout : chaque règle retirée doit faire descendre d'un cran."""
    inventaire = _inventaire()
    _exiger_l27(inventaire)
    couches = [
        ({"sport": "VirtualRide"}, HOME_TRAINER),
        ({"meta_capteur": CAPTEUR_BETA}, "Beta"),
        ({"meta_gear": "g-alpha"}, "Alpha"),
        ({"debut": datetime(2024, 8, 1, 9, tzinfo=UTC)}, "Beta"),
        ({}, "Alpha"),
    ]
    for i in range(len(couches)):
        surcharges = {"sport": "Ride", "debut": DEBUT_REF, "meta": {}}
        for regle, _ in couches[i:]:
            if "meta_capteur" in regle:
                surcharges["meta"]["power_meter"] = regle["meta_capteur"]
            elif "meta_gear" in regle:
                surcharges["meta"]["gear_id"] = regle["meta_gear"]
            else:
                surcharges.update(regle)
        attendu = couches[i][1]
        resultat = _rattacher(**surcharges)
        assert resultat == attendu, (
            f"entrée {surcharges} : règle {i + 1} attendue (« {attendu} »), reçu « {resultat} »"
        )


# --- métadonnées Intervals ----------------------------------------------------


ACTIVITE = {
    "id": "i1",
    "start_date_local": "2026-04-12T09:00:00",
    "type": "Ride",
    "name": "Sortie fictive",
    "distance": 30000.0,
    "moving_time": 3600,
    "icu_average_watts": 200,
    "device_name": "Compteur Fictif 1000",
    "power_meter": CAPTEUR_BETA,
    "power_meter_serial": "SN-000000",
    "avg_lr_balance": 49.5,
    "trainer": False,
    "gear": {"id": "g-beta"},
}


def _exiger_meta_l27(module):
    meta = module.metadonnees(dict(ACTIVITE))
    if "power_meter" not in meta:
        pytest.skip(MOTIF_L27)
    return meta


def test_les_metadonnees_recopient_les_champs_du_contrat():
    module = _intervals()
    meta = _exiger_meta_l27(module)
    for cle in ("power_meter", "power_meter_serial", "bilateral", "gear_id", "trainer", "device_name"):
        assert cle in meta, f"`{cle}` doit être recopié dans meta (contrat §7), meta = {sorted(meta)}"
    assert meta["power_meter"] == CAPTEUR_BETA
    assert meta["gear_id"] == "g-beta", f"gear_id lu dans `gear.id`, reçu {meta['gear_id']!r}"
    outils.verifier_json(meta, "metadonnees")


@pytest.mark.parametrize(
    "avg_lr_balance, attendu",
    [(49.5, True), (0.0, True), (None, False)],
)
def test_bilateral_vaut_avg_lr_balance_est_present(avg_lr_balance, attendu):
    """Contrat §7 : `bilateral` = `avg_lr_balance is not None` — 0.0 n'est pas « absent »."""
    module = _intervals()
    _exiger_meta_l27(module)
    activite = dict(ACTIVITE, avg_lr_balance=avg_lr_balance)
    meta = module.metadonnees(activite)
    assert meta["bilateral"] is attendu, (
        f"avg_lr_balance={avg_lr_balance!r} : bilateral attendu {attendu}, reçu {meta['bilateral']!r}"
    )


def test_une_activite_sans_equipement_ne_fabrique_pas_de_gear_id():
    module = _intervals()
    _exiger_meta_l27(module)
    for gear in (None, "", {}, "Vélo Beta", {"id": None}):
        meta = module.metadonnees(dict(ACTIVITE, gear=gear))
        assert meta.get("gear_id") in (None, ""), (
            f"gear={gear!r} ne porte pas d'identifiant, reçu {meta.get('gear_id')!r}"
        )


# --- rafraichir_meta ----------------------------------------------------------


def _exiger_rafraichir(module):
    signature = inspect.signature(module.synchroniser)
    if "rafraichir_meta" not in signature.parameters:
        pytest.skip(MOTIF_RAFRAICHIR)


def _reponse_fichier(octets: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        content=octets,
        headers={"content-disposition": 'attachment; filename="a.gpx"'},
    )


def _serveur(activites, octets):
    def repondre(requete: httpx.Request) -> httpx.Response:
        if requete.url.path.endswith("/file"):
            return _reponse_fichier(octets)
        if requete.url.path.endswith("/gear"):
            return httpx.Response(200, json=[{"id": "g-beta", "name": "Vélo Beta"}])
        return httpx.Response(200, json=activites)

    return repondre


def _client(module, repondre):
    espion = EspionHttp(repondre)
    client = module.ClientIntervals(
        outils.ATHLETE_BIDON, outils.CLE_BIDON, http=espion.client(), base_url="https://exemple.invalide"
    )
    return client, espion


def test_rafraichir_meta_ne_retelecharge_pas_le_fichier(tmp_path, hostiles):
    """Contrat §7 : met à jour `meta`/`equipement` **sans** retélécharger le fichier."""
    module = _intervals()
    _exiger_rafraichir(module)
    cache = _cache_module().Cache(tmp_path / "cache")
    octets = hostiles["nominal.gpx"].read_bytes()
    cache.ajouter(octets, source="intervals", id_externe="i1", extension="gpx", meta={"sport": "Ride"})

    client, espion = _client(module, _serveur([dict(ACTIVITE, id="i1")], octets))
    module.synchroniser(client, cache, date(2026, 4, 1), rafraichir_meta=True)

    telechargements = [c for c in espion.chemins if c.endswith("/file")]
    assert telechargements == [], (
        f"le fichier est déjà en cache : aucun téléchargement ne doit partir, reçu {telechargements}"
    )
    entree = cache.lister()[0]
    assert entree.meta.get("power_meter") == CAPTEUR_BETA, (
        f"`meta` n'a pas été rafraîchie : {entree.meta!r}"
    )


def test_rafraichir_meta_resout_l_equipement_en_un_seul_appel(tmp_path, hostiles):
    module = _intervals()
    _exiger_rafraichir(module)
    cache = _cache_module().Cache(tmp_path / "cache")
    octets = hostiles["nominal.gpx"].read_bytes()
    for i in (1, 2, 3):
        cache.ajouter(
            octets + b"\n" * i, source="intervals", id_externe=f"i{i}", extension="gpx", meta={}
        )
    activites = [dict(ACTIVITE, id=f"i{i}") for i in (1, 2, 3)]

    client, espion = _client(module, _serveur(activites, octets))
    module.synchroniser(client, cache, date(2026, 4, 1), rafraichir_meta=True)

    appels_gear = [c for c in espion.chemins if c.endswith("/gear")]
    assert len(appels_gear) <= 1, (
        f"{len(appels_gear)} appels à l'endpoint gear pour 3 activités : le contrat demande "
        "un appel, mis en cache dans le client"
    )
    equipements = {e.equipement for e in cache.lister()}
    assert equipements == {"Vélo Beta"}, f"équipement résolu attendu, reçu {equipements}"


def test_synchroniser_nu_rafraichit_la_meta_par_defaut(tmp_path, hostiles):
    """Point 11 de la relecture : plus aucun test n'exerçait le **défaut** du drapeau.

    Depuis `c25aaeb`, tous passaient `rafraichir_meta` explicitement, alors
    que la DoD repose sur le comportement sans option : `ourouler inventaire
    --synchroniser` doit enrichir les entrées déjà en cache pour séparer les
    deux vélos. Ce test appelle donc `synchroniser(client, cache, depuis)`
    nu, exactement comme la commande.
    """
    module = _intervals()
    _exiger_rafraichir(module)
    cache = _cache_module().Cache(tmp_path / "cache")
    octets = hostiles["nominal.gpx"].read_bytes()
    cache.ajouter(octets, source="intervals", id_externe="i1", extension="gpx", meta={"sport": "Ride"})
    avant = cache.lister()[0]
    assert "power_meter" not in avant.meta, "l'entrée part bien sans métadonnée de rattachement"

    client, espion = _client(module, _serveur([dict(ACTIVITE, id="i1")], octets))
    rapport = module.synchroniser(client, cache, date(2026, 4, 1))

    entree = cache.lister()[0]
    assert entree.meta.get("power_meter") == CAPTEUR_BETA, (
        f"sans option, `meta` doit être rafraîchie : {entree.meta!r}"
    )
    assert entree.equipement == "Vélo Beta", f"équipement non résolu : {entree.equipement!r}"
    assert outils.champ(rapport, "mises_a_jour") == 1, "la mise à jour doit être rapportée"
    assert [c for c in espion.chemins if c.endswith("/file")] == [], (
        "rafraîchir ne doit pas retélécharger le fichier"
    )


def test_sans_rafraichir_meta_rien_ne_bouge(tmp_path, hostiles):
    """`rafraichir_meta=False` : l'entrée déjà en cache est laissée telle quelle.

    Le drapeau est passé explicitement. Le contrat du sprint 2 §7 écrit
    « `synchroniser` gagne `rafraichir_meta=True` », c'est-à-dire un paramètre
    dont la **valeur par défaut est True** — comme tous les autres défauts du
    contrat (`nb_points: int = 5`, `pas_m: float = 5000`). C'est aussi ce que
    la DoD demande : `ourouler inventaire --synchroniser` doit enrichir les
    sorties déjà en cache pour séparer les deux vélos, sans option à ajouter.
    La première version de ce test omettait l'argument et exigeait quand même
    le comportement de `False` : elle contredisait le contrat.
    """
    module = _intervals()
    _exiger_rafraichir(module)
    cache = _cache_module().Cache(tmp_path / "cache")
    octets = hostiles["nominal.gpx"].read_bytes()
    cache.ajouter(octets, source="intervals", id_externe="i1", extension="gpx", meta={"sport": "Ride"})
    avant = cache.lister()[0]

    client, espion = _client(module, _serveur([dict(ACTIVITE, id="i1")], octets))
    rapport = module.synchroniser(client, cache, date(2026, 4, 1), rafraichir_meta=False)

    assert [c for c in espion.chemins if c.endswith("/file")] == [], (
        "l'activité est déjà en cache : elle est ignorée"
    )
    entree = cache.lister()[0]
    assert "power_meter" not in entree.meta, (
        f"sans `rafraichir_meta`, la meta existante n'est pas touchée : {entree.meta!r}"
    )
    assert entree.meta == avant.meta, f"meta modifiée : {avant.meta!r} → {entree.meta!r}"
    assert entree.equipement == avant.equipement, (
        f"équipement modifié : {avant.equipement!r} → {entree.equipement!r}"
    )
    assert outils.champ(rapport, "mises_a_jour") == 0, (
        "aucune mise à jour ne doit être rapportée quand le drapeau les interdit"
    )


def test_rafraichir_meta_telecharge_quand_meme_les_nouvelles_activites(tmp_path, hostiles):
    module = _intervals()
    _exiger_rafraichir(module)
    cache = _cache_module().Cache(tmp_path / "cache")
    octets = hostiles["nominal.gpx"].read_bytes()

    client, espion = _client(module, _serveur([dict(ACTIVITE, id="i1")], octets))
    rapport = module.synchroniser(client, cache, date(2026, 4, 1), rafraichir_meta=True)

    assert [c for c in espion.chemins if c.endswith("/file")] == ["/api/v1/activity/i1/file"], (
        "rafraîchir les métadonnées ne dispense pas de rapatrier ce qui manque"
    )
    assert outils.champ(rapport, "ajout") == 1

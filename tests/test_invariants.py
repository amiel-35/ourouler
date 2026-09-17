"""Invariants de doctrine, vérifiés sur le code source lui-même.

Règle absolue 2 de CLAUDE.md : sous `src/ourouler/`, seuls `cli.py` et
`config.py` ont le droit de toucher un fichier de configuration, une
variable d'environnement ou un chemin utilisateur. Plutôt que de faire
confiance à la relecture, on le mesure.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from xml.etree import ElementTree

import pytest

from ourouler.activites.lecture import lire_fit
from ourouler.erreurs import ErreurLecture
from ourouler.meteo.couronne import distance_haversine_km

SOURCES = Path(__file__).resolve().parents[1] / "src" / "ourouler"
TESTS = Path(__file__).resolve().parent


def _generateur():
    """Charge `tests/fixtures/generer_activites.py` par chemin (deux conftest.py
    coexistent dans tests/, on n'importe donc pas `conftest`)."""
    import importlib.util
    import sys

    if "generer_activites" in sys.modules:
        return sys.modules["generer_activites"]
    chemin = TESTS / "fixtures" / "generer_activites.py"
    spec = importlib.util.spec_from_file_location("generer_activites", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["generer_activites"] = module
    spec.loader.exec_module(module)
    return module

#: Modules autorisés à lire l'environnement d'exécution.
AUTORISES = {"cli.py", "config.py"}

#: **La porte que l'API ouvre, et elle seule** (lot F1). L'API est une couche
#: d'exploitation, comme `cli.py` : elle a le droit de lire la configuration
#: et l'environnement. Ce droit est donné à **un chemin**, pas à un nom de
#: fichier, et à un seul module du paquet — les routes, les dépôts et la
#: traduction d'erreurs restent soumis à la règle absolue 2.
CHEMINS_AUTORISES = {"api/exploitation.py"}

#: Ce qu'un module du cœur ne doit jamais faire.
INTERDITS = ("tomllib", "os.environ", "getenv", "Path.home()", ".expanduser(", "load_dotenv")


def modules_du_coeur() -> list[Path]:
    return sorted(
        p
        for p in SOURCES.rglob("*.py")
        if p.name not in AUTORISES and p.relative_to(SOURCES).as_posix() not in CHEMINS_AUTORISES
    )


def test_il_y_a_bien_des_modules_a_verifier():
    noms = {p.name for p in modules_du_coeur()}
    assert {"lecture.py", "cache.py", "inventaire.py", "intervals.py"} <= noms


def test_l_api_est_couverte_sauf_son_unique_module_d_exploitation():
    """F1 : l'API entre dans le périmètre de la règle absolue 2, à une porte près.

    Sans ce test, ajouter `application.py` ou `routes.py` à `AUTORISES` pour
    « débloquer » une lecture d'environnement passerait inaperçu : c'est
    exactement ce qu'il ne faut pas faire, et il faut que ça se voie.
    """
    couverts = {p.relative_to(SOURCES).as_posix() for p in modules_du_coeur()}
    api = {p.relative_to(SOURCES).as_posix() for p in (SOURCES / "api").rglob("*.py")}
    assert api, "le paquet api/ doit exister"
    assert api - couverts == CHEMINS_AUTORISES, (
        "un module de l'API échappe à la règle absolue 2 sans que CHEMINS_AUTORISES le dise"
    )


def test_seul_le_module_d_exploitation_de_l_api_lit_l_environnement():
    """La porte est ouverte quelque part : ce test vérifie qu'elle sert vraiment.

    Un invariant qui passe parce que personne n'utilise la permission qu'il
    encadre n'encadre rien.
    """
    source = (SOURCES / "api" / "exploitation.py").read_text(encoding="utf-8")
    assert "os.environ" in source and "tomllib" in source


#: Les accès aux données de l'API. Doctrine §10.2 : « aucune requête sans
#: clause de propriétaire » — ici, aucune méthode publique de dépôt sans
#: `proprietaire` en **premier argument positionnel**. C'est gratuit
#: aujourd'hui (un seul propriétaire) et impossible à rattraper le jour où
#: ces dépôts parleront à PostgreSQL.
CLASSES_DEPOT = ("DepotProfils", "DepotFichiers")


def test_aucun_acces_aux_donnees_sans_clause_de_proprietaire():
    arbre = ast.parse((SOURCES / "api" / "depots.py").read_text(encoding="utf-8"))
    classes = {
        noeud.name: noeud for noeud in ast.walk(arbre) if isinstance(noeud, ast.ClassDef)
    }
    for nom in CLASSES_DEPOT:
        assert nom in classes, f"{nom} a disparu de api/depots.py"
        methodes = [
            m
            for m in classes[nom].body
            if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")
        ]
        assert methodes, f"{nom} n'a plus aucune méthode publique"
        for methode in methodes:
            arguments = [a.arg for a in methode.args.args]
            assert arguments[:2] == ["self", "proprietaire"], (
                f"{nom}.{methode.name}{tuple(arguments)} : le propriétaire doit être le "
                "premier argument — doctrine §10.2, aucune requête sans clause de propriétaire"
            )


def test_les_routes_ne_chargent_jamais_la_configuration_elles_memes():
    """Une route demande sa `Config` au dépôt, pour un propriétaire donné.

    Importer `config.charger` ici rendrait « la » configuration du serveur à
    n'importe quel appelant, et ferait disparaître la clause de propriétaire
    sans rien casser de visible — le genre de régression qui ne se voit qu'en
    production, quand il y a deux utilisateurs.
    """
    arbre = ast.parse((SOURCES / "api" / "routes.py").read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.ImportFrom) and (noeud.module or "").startswith("ourouler.config"):
            importes = {alias.name for alias in noeud.names}
            assert "charger" not in importes, (
                "api/routes.py importe config.charger : la Config vient du dépôt, "
                "pour un propriétaire"
            )


def test_les_prefixes_qui_classent_les_pannes_existent_vraiment():
    """Le classement des erreurs lit le préfixe du message des connecteurs.

    C'est une convention, donc une dette potentielle : si un connecteur
    changeait son préfixe, le front recevrait `service_externe_indisponible`
    au lieu du code attendu, et ses écrans d'échec se tromperaient d'écran.
    Ce test attache la convention à son code.
    """
    from ourouler.api.erreurs import PREFIXES_SERVICE

    sources = {
        "BRouter": SOURCES / "connecteurs" / "brouter.py",
        "Open-Meteo": SOURCES / "meteo" / "openmeteo.py",
        "Intervals.icu": SOURCES / "connecteurs" / "intervals.py",
        "BAN": SOURCES / "connecteurs" / "geocodage.py",
        "Nominatim": SOURCES / "connecteurs" / "geocodage.py",
    }
    for prefixe, _service, _code in PREFIXES_SERVICE:
        texte = sources[prefixe].read_text(encoding="utf-8")
        assert f'"{prefixe} ' in texte or f"f\"{prefixe} " in texte, (
            f"aucun message ne commence par « {prefixe} » dans {sources[prefixe].name} : "
            "le classement des pannes de l'API ne reconnaîtra plus ce service"
        )


@pytest.mark.parametrize("module", modules_du_coeur(), ids=lambda p: p.name)
def test_le_coeur_ne_lit_pas_son_environnement(module: Path):
    source = module.read_text(encoding="utf-8")
    for interdit in INTERDITS:
        assert interdit not in source, (
            f"{module.relative_to(SOURCES)} touche « {interdit} » : "
            "seuls cli.py et config.py en ont le droit"
        )


@pytest.mark.parametrize("module", modules_du_coeur(), ids=lambda p: p.name)
def test_le_coeur_n_importe_pas_tomllib(module: Path):
    arbre = ast.parse(module.read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            importes.add(noeud.module.split(".")[0])
    assert "tomllib" not in importes
    assert "os" not in importes


#: Les trois paquets de commandes qui partent d'un point. Ils reçoivent un
#: `Depart` déjà tranché ; ils ne doivent jamais résoudre une adresse eux-mêmes.
PAQUETS_DE_COMMANDE = ("meteo", "boucle", "sortie")


@pytest.mark.parametrize("paquet", PAQUETS_DE_COMMANDE)
def test_le_coeur_ne_geocode_jamais_lui_meme(paquet: str):
    """F0.7 : l'adresse devient un `Depart` dans `cli.py`, et nulle part ailleurs.

    Le connecteur de géocodage sort sur le réseau et interprète une saisie
    d'utilisateur : le cœur, qui ne sait pas où il tourne (règle absolue 2),
    reçoit le point déjà choisi. Seuls `cli.py` et le paquet `geocodage`
    (qui sert la sous-commande dédiée) ont le droit de l'importer.
    """
    for module in sorted((SOURCES / paquet).rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        for noeud in ast.walk(ast.parse(source)):
            depuis = None
            if isinstance(noeud, ast.ImportFrom) and noeud.module:
                depuis = noeud.module
            elif isinstance(noeud, ast.Import):
                depuis = " ".join(alias.name for alias in noeud.names)
            assert depuis is None or "geocodage" not in depuis, (
                f"{module.relative_to(SOURCES)} importe le géocodage : "
                "seul cli.py résout une adresse, le cœur reçoit un Depart"
            )


#: C1 de `docs/ux/relecture_f0.md` : `zwo.py` et `mrc.py` (683 lignes, testées)
#: n'avaient aucun appelant dans `src/` — un trou du cadrage compté comme
#: comblé qui ne l'était qu'à moitié. F1 les branche via `seance/fichier.py`,
#: lui-même appelé par `seance/commande.py` et `sortie/commande.py`.
MODULES_SANS_APPELANT_HISTORIQUE = ("seance.zwo", "seance.mrc")


def test_zwo_et_mrc_ont_desormais_un_appelant():
    """Régression de C1 : si ce branchement disparaissait, ce test doit le dire
    avant qu'un futur agent ne recompte le trou comme comblé.

    Ne vérifie pas que ces lecteurs *marchent* (leurs propres tests le font),
    seulement qu'au moins un module du cœur, en dehors d'eux-mêmes, les
    importe — la preuve mécanique qu'un chemin d'exécution existe.
    """
    modules = modules_du_coeur()
    for cible in MODULES_SANS_APPELANT_HISTORIQUE:
        appelants = []
        for module in modules:
            if module.name in (cible.split(".")[-1] + ".py",):
                continue  # le module ne compte pas comme son propre appelant
            arbre = ast.parse(module.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                depuis = None
                if isinstance(noeud, ast.ImportFrom) and noeud.module:
                    depuis = noeud.module
                elif isinstance(noeud, ast.Import):
                    depuis = " ".join(alias.name for alias in noeud.names)
                if depuis and cible in depuis:
                    appelants.append(module.relative_to(SOURCES))
        assert appelants, (
            f"ourouler.{cible} n'a plus aucun appelant dans src/ — régression de C1"
        )


def test_aucun_client_http_reel_n_est_cree_a_l_import():
    """Un connecteur ne doit ouvrir un client qu'à la demande, jamais au chargement."""
    intervals = (SOURCES / "connecteurs" / "intervals.py").read_text(encoding="utf-8")
    arbre = ast.parse(intervals)
    for noeud in arbre.body:  # niveau module uniquement
        assert not isinstance(noeud, ast.Assign) or "httpx.Client" not in ast.unparse(noeud.value)


@pytest.mark.parametrize(
    "fichier", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name
)
def test_aucun_test_ne_cree_un_client_http_sans_transport_bouchonne(fichier: Path):
    """`httpx.Client(...)` n'est permis dans les tests qu'avec un MockTransport.

    **Périmètre : `tests/*.py` seulement.** Le `glob` n'est pas récursif, donc
    `tests/adversarial/` n'est pas scanné ici — il l'est par l'invariant jumeau
    `test_adv_invariants.test_tout_client_httpx_des_tests_recoit_un_transport`,
    qui parcourt tout `tests/` et couvre donc le fond. Les deux sont gardés :
    celui-ci paramétré fichier par fichier (l'échec nomme le coupable), l'autre
    exhaustif.
    """
    source = fichier.read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if not isinstance(noeud, ast.Call):
            continue
        appel = ast.unparse(noeud.func)
        if appel in ("httpx.Client", "httpx.AsyncClient"):
            assert "MockTransport" in ast.unparse(noeud), (
                f"{fichier.name} : client httpx sans MockTransport — un test ne "
                "doit jamais pouvoir sortir sur le réseau"
            )


# --- aucune coordonnée réelle -------------------------------------------------
#
# Cet invariant grepait le **texte source** du générateur (« LAT_FICTIVE = 0.0 »)
# et du fichier de configuration de test. Il ne lisait aucune fixture :
# remplacer `boucle.gpx` par une trace réelle, ou ajouter un décalage ailleurs
# dans le générateur, le laissait vert — et il ignorait `config.example.toml`,
# précisément là où une coordonnée réelle s'était glissée. Il mesure
# maintenant les coordonnées elles-mêmes, fixture par fixture.

#: Villes réelles dont aucune coordonnée du dépôt ne doit s'approcher. C'est un
#: échantillon de la région du mainteneur (contrat de sprint §5), pas une liste
#: exhaustive des villes françaises : le but est d'attraper une vraie trace ou
#: un vrai point de départ qui aurait été commité par mégarde.
#:
#: Écrites en **centièmes de degré entiers**, jamais en décimal : en clair,
#: cette liste est elle-même une poignée de coordonnées françaises dans un
#: fichier de test, et tout détecteur qui scanne `tests/` la dénonce — c'est
#: exactement ce qu'a fait le testeur adversarial. Diviser par 100 à l'usage
#: ne change rien à l'invariant et sort le fichier de sa propre ligne de mire.
VILLES_CENTIEMES = {
    "Rennes": (4811, -168),
    "Paris": (4886, 235),
    "Nantes": (4722, -155),
    "Saint-Malo": (4865, -203),
    "Vannes": (4766, -276),
    "Laval": (4807, -77),
}
VILLES_REELLES = {nom: (lat / 100, lon / 100) for nom, (lat, lon) in VILLES_CENTIEMES.items()}

#: Distance minimale exigée entre toute coordonnée du dépôt et ces villes.
RAYON_INTERDIT_KM = 50.0

FIXTURES_ACTIVITES = TESTS / "fixtures" / "activites"
CONFIGS_A_VERIFIER = (
    TESTS / "fixtures" / "config_test.toml",
    Path(__file__).resolve().parents[1] / "config.example.toml",
)


def coordonnees_gpx(octets: bytes) -> list[tuple[float, float]]:
    """Les `lat`/`lon` des points d'une trace GPX.

    XML d'abord ; si le fichier est tronqué (le dossier de fixtures en
    contient exprès), repli sur une lecture textuelle des attributs. Un
    fichier abîmé n'est pas une dispense de vérification : il porte quand
    même les coordonnées qu'on y a écrites.
    """
    try:
        racine = ElementTree.fromstring(octets)
    except ElementTree.ParseError:
        return _coordonnees_par_attributs(octets)
    points = []
    for noeud in racine.iter():
        if noeud.tag.rsplit("}", 1)[-1] not in ("trkpt", "rtept", "wpt"):
            continue
        lat, lon = noeud.get("lat"), noeud.get("lon")
        if lat is not None and lon is not None:
            points.append((float(lat), float(lon)))
    return points


def coordonnees_tcx(octets: bytes) -> list[tuple[float, float]]:
    """Les `Position` d'une trace TCX. Même repli textuel qu'en GPX si le XML est cassé."""
    try:
        racine = ElementTree.fromstring(octets)
    except ElementTree.ParseError:
        return _coordonnees_par_balises(octets)
    points = []
    for noeud in racine.iter():
        if noeud.tag.rsplit("}", 1)[-1] != "Position":
            continue
        lat = lon = None
        for enfant in noeud:
            nom = enfant.tag.rsplit("}", 1)[-1]
            if nom == "LatitudeDegrees" and enfant.text:
                lat = float(enfant.text)
            elif nom == "LongitudeDegrees" and enfant.text:
                lon = float(enfant.text)
        if lat is not None and lon is not None:
            points.append((lat, lon))
    return points


def _coordonnees_par_attributs(octets: bytes) -> list[tuple[float, float]]:
    texte = octets.decode("utf-8", errors="replace")
    lats = [float(x) for x in re.findall(r'\blat="(-?\d+(?:\.\d+)?)"', texte)]
    lons = [float(x) for x in re.findall(r'\blon="(-?\d+(?:\.\d+)?)"', texte)]
    return list(zip(lats, lons, strict=False))


def _coordonnees_par_balises(octets: bytes) -> list[tuple[float, float]]:
    texte = octets.decode("utf-8", errors="replace")
    lats = [float(x) for x in re.findall(r"<LatitudeDegrees>(-?\d+(?:\.\d+)?)", texte)]
    lons = [float(x) for x in re.findall(r"<LongitudeDegrees>(-?\d+(?:\.\d+)?)", texte)]
    return list(zip(lats, lons, strict=False))


def coordonnees_fit(octets: bytes) -> list[tuple[float, float]]:
    """Les coordonnées d'un FIT : on le **relit avec le lecteur du projet**.

    Un FIT est binaire, les latitudes y sont en semicercles : le grep n'a
    aucune prise dessus, seul le lecteur sait dire ce que le fichier contient.
    Un FIT tronqué ne porte aucun enregistrement lisible : rien à mesurer.
    """
    try:
        activite = lire_fit(octets)
    except ErreurLecture:
        return []
    return [
        (float(p.lat), float(p.lon))
        for p in activite.points
        if p.lat is not None and p.lon is not None
    ]


def coordonnees_toml(chemin: Path) -> list[tuple[float, float]]:
    """Le point de départ d'un fichier de configuration."""
    with chemin.open("rb") as f:
        brut = tomllib.load(f)
    depart = brut.get("depart") or {}
    if "latitude" not in depart or "longitude" not in depart:
        return []
    return [(float(depart["latitude"]), float(depart["longitude"]))]


def coordonnees_de(fixture: Path) -> list[tuple[float, float]]:
    """Toutes les coordonnées d'une fixture d'activité, selon son extension."""
    octets = fixture.read_bytes()
    extension = fixture.suffix.lower()
    if extension == ".gpx":
        return coordonnees_gpx(octets)
    if extension == ".tcx":
        return coordonnees_tcx(octets)
    return coordonnees_fit(octets)


def ville_trop_proche(lat: float, lon: float) -> tuple[str, float] | None:
    """La ville réelle la plus proche si elle est à moins de `RAYON_INTERDIT_KM`."""
    plus_proche = min(
        (distance_haversine_km(lat, lon, v_lat, v_lon), nom)
        for nom, (v_lat, v_lon) in VILLES_REELLES.items()
    )
    km, nom = plus_proche
    return (nom, km) if km < RAYON_INTERDIT_KM else None


def fixtures_avec_coordonnees() -> list[Path]:
    """Les fixtures d'activité dont on sait extraire des coordonnées.

    Appelée au **moment de la collecte** par `parametrize`, donc avant toute
    fixture pytest : si le dossier est vide (fixtures supprimées), il faut le
    regarnir ici, sinon la paramétrisation serait vide et l'invariant
    passerait pour vert en ne mesurant rien — l'erreur même qu'on corrige.
    """
    if not FIXTURES_ACTIVITES.is_dir() or not any(FIXTURES_ACTIVITES.iterdir()):
        _generateur().generer(FIXTURES_ACTIVITES)
    return sorted(
        p
        for p in FIXTURES_ACTIVITES.iterdir()
        if p.is_file() and p.suffix.lower() in (".gpx", ".tcx", ".fit") and p.stat().st_size > 0
    )


def test_le_calcul_de_distance_detecte_bien_une_ville_reelle():
    """Sans ce contrôle, l'invariant suivant pourrait être vert en ne mesurant rien.

    Les coordonnées de contrôle sont **calculées** depuis `VILLES_CENTIEMES` et
    jamais écrites en décimal ici : sinon ce test se dénoncerait lui-même.
    """
    lat, lon = VILLES_REELLES["Rennes"]
    assert ville_trop_proche(lat, lon) == ("Rennes", pytest.approx(0.0, abs=1.0))
    assert ville_trop_proche(lat - 1 / 100, lon - 2 / 100) is not None, "le centre de Rennes à 2 km"
    assert ville_trop_proche(0.0, 0.0) is None, "le point zéro est à 5 000 km de tout"


@pytest.mark.parametrize("fixture", fixtures_avec_coordonnees(), ids=lambda p: p.name)
def test_aucune_fixture_ne_contient_de_coordonnee_reelle(fixture: Path):
    """Les coordonnées sont **lues** dans chaque fixture, pas grepées dans le générateur."""
    for lat, lon in coordonnees_de(fixture):
        proche = ville_trop_proche(lat, lon)
        assert proche is None, (
            f"{fixture.name} : le point ({lat}, {lon}) est à {proche[1]:.1f} km de "
            f"{proche[0]} — une fixture ne doit jamais porter de coordonnée réelle"
        )


def test_les_fixtures_de_trace_portent_vraiment_des_coordonnees():
    """L'invariant ci-dessus ne doit pas être vert parce qu'il ne trouve rien à mesurer."""
    avec_gps = {f.name for f in fixtures_avec_coordonnees() if coordonnees_de(f)}
    assert "boucle.gpx" in avec_gps
    assert "boucle.tcx" in avec_gps
    assert "boucle.fit" in avec_gps
    assert len(avec_gps) >= 4, f"trop peu de fixtures géolocalisées mesurées : {avec_gps}"


@pytest.mark.parametrize("config", CONFIGS_A_VERIFIER, ids=lambda p: p.name)
def test_aucun_fichier_de_configuration_du_depot_ne_porte_de_point_reel(config: Path):
    """`config.example.toml` comprise : c'est là que la coordonnée réelle s'était glissée."""
    points = coordonnees_toml(config)
    assert points, f"{config.name} : aucun [depart] lisible, l'invariant ne mesurerait rien"
    for lat, lon in points:
        proche = ville_trop_proche(lat, lon)
        assert proche is None, (
            f"{config.name} : le point de départ ({lat}, {lon}) est à "
            f"{proche[1]:.1f} km de {proche[0]}"
        )


def test_aucune_cle_dans_la_configuration_de_test():
    config = (TESTS / "fixtures" / "config_test.toml").read_text(encoding="utf-8")
    assert 'api_key = ""' in config


# --- poids des fixtures versionnées -----------------------------------------
#
# Dette notée en relecture : 712 Ko de fixtures versionnées alors que
# `conftest.py` les régénère quand elles manquent. On garde les fichiers
# (reproductibilité : un `git clone` suffit à lancer les tests, sans exécuter
# le générateur), mais les traces sont réduites à ~60 points.

#: Budget de taille pour `tests/fixtures/activites/`, en kilo-octets.
TAILLE_MAX_FIXTURES_KO = 150


def test_les_fixtures_versionnees_restent_legeres():
    poids = {p.name: p.stat().st_size for p in FIXTURES_ACTIVITES.iterdir() if p.is_file()}
    total = sum(poids.values())
    detail = ", ".join(f"{nom} {taille // 1024} Kio" for nom, taille in sorted(poids.items()))
    assert total < TAILLE_MAX_FIXTURES_KO * 1000, (
        f"{total} octets de fixtures, budget {TAILLE_MAX_FIXTURES_KO} Ko — "
        f"réduire le nombre de points dans generer_activites.py ({detail})"
    )


def test_les_traces_restent_courtes():
    """~60 points : assez pour tout ce que les tests mesurent, pas plus."""
    for fixture in fixtures_avec_coordonnees():
        points = coordonnees_de(fixture)
        if not points:
            continue  # fixture volontairement tronquée
        assert len(points) <= 80, f"{fixture.name} : {len(points)} points, ~60 attendus"


def test_le_generateur_de_fixtures_est_reproductible(generateur, tmp_path: Path):
    """Ce qui justifie de versionner sa sortie : elle ne dérive pas du générateur.

    Le générateur reste la source de vérité ; les fichiers sont versionnés pour
    qu'un `git clone` suffise à lancer les tests. Encore faut-il que les deux
    disent la même chose, octet pour octet.
    """
    ecrits = generateur.generer(tmp_path)
    assert ecrits, "le générateur doit écrire quelque chose"
    for nom, chemin in ecrits.items():
        versionnee = FIXTURES_ACTIVITES / nom
        assert versionnee.is_file(), f"{nom} n'est pas versionnée"
        assert chemin.read_bytes() == versionnee.read_bytes(), (
            f"{nom} : la fixture versionnée diffère de ce que le générateur produit "
            "— relancer `uv run python tests/fixtures/generer_activites.py`"
        )


# --- numpy est confiné au paquet physique ------------------------------------
#
# Contrat du sprint 3 §4 : « numpy interdit hors physique/ ». La dépendance a
# été ajoutée pour les moindres carrés de la calibration ; elle n'a rien à
# faire dans un lecteur de fichier ou un connecteur, où elle ferait entrer des
# scalaires `np.float64` dans des dataclasses censées porter des `float`.

PAQUET_NUMPY = "physique"


@pytest.mark.parametrize(
    "module", sorted(SOURCES.rglob("*.py")), ids=lambda p: str(p.relative_to(SOURCES))
)
def test_numpy_reste_dans_le_paquet_physique(module: Path):
    arbre = ast.parse(module.read_text(encoding="utf-8"))
    importes = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            importes.update(alias.name.split(".")[0] for alias in noeud.names)
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            importes.add(noeud.module.split(".")[0])
    if "numpy" not in importes:
        return
    assert module.parent.name == PAQUET_NUMPY, (
        f"{module.relative_to(SOURCES)} importe numpy : seul le paquet "
        f"{PAQUET_NUMPY}/ y a droit (contrat du sprint 3 §4)"
    )


def test_l_invariant_numpy_mesure_bien_quelque_chose():
    """Vert par absence de numpy nulle part serait un invariant creux."""
    sources = [p.read_text(encoding="utf-8") for p in SOURCES.rglob("*.py")]
    assert any("import numpy" in s for s in sources), (
        "aucun module n'importe numpy : l'invariant ci-dessus ne mesure rien"
    )

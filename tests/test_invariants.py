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

#: Modules autorisés à lire l'environnement d'exécution.
AUTORISES = {"cli.py", "config.py"}

#: Ce qu'un module du cœur ne doit jamais faire.
INTERDITS = ("tomllib", "os.environ", "getenv", "Path.home()", ".expanduser(", "load_dotenv")


def modules_du_coeur() -> list[Path]:
    return sorted(p for p in SOURCES.rglob("*.py") if p.name not in AUTORISES)


def test_il_y_a_bien_des_modules_a_verifier():
    noms = {p.name for p in modules_du_coeur()}
    assert {"lecture.py", "cache.py", "inventaire.py", "intervals.py"} <= noms


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
    """`httpx.Client(...)` n'est permis dans les tests qu'avec un MockTransport."""
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
VILLES_REELLES = {
    "Rennes": (48.11, -1.68),
    "Paris": (48.86, 2.35),
    "Nantes": (47.22, -1.55),
    "Saint-Malo": (48.65, -2.03),
    "Vannes": (47.66, -2.76),
    "Laval": (48.07, -0.77),
}

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
    """Les fixtures d'activité dont on sait extraire des coordonnées."""
    return sorted(
        p
        for p in FIXTURES_ACTIVITES.iterdir()
        if p.is_file() and p.suffix.lower() in (".gpx", ".tcx", ".fit") and p.stat().st_size > 0
    )


def test_le_calcul_de_distance_detecte_bien_une_ville_reelle():
    """Sans ce contrôle, l'invariant suivant pourrait être vert en ne mesurant rien."""
    assert ville_trop_proche(48.11, -1.68) == ("Rennes", pytest.approx(0.0, abs=1.0))
    assert ville_trop_proche(48.10, -1.70) is not None, "le centre de Rennes à 2 km"
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

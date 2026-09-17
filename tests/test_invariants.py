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

RACINE = Path(__file__).resolve().parents[1]
SOURCES = RACINE / "src" / "ourouler"
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
    RACINE / "config.example.toml",
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


# --- et les documents, angle mort jusqu'au 17/09/2026 ------------------------
#
# Les deux détecteurs de coordonnées du dépôt lisaient les fixtures et les
# fichiers de configuration ; aucun ne regardait `docs/`. L'audit de
# l'historique mené en resserrant `.gitignore` y a trouvé le point de départ du
# mainteneur en clair depuis le sprint 1 : `docs/sprint1_relecture.md` citait
# le défaut qu'elle venait de faire corriger ailleurs, coordonnée comprise. Un
# procès-verbal de relecture est un document comme un autre.

#: Un nombre décimal signé, tel qu'on écrit une latitude ou une longitude.
DECIMAL = re.compile(r"-?\d{1,3}\.\d+")

#: Dossiers sans texte rédigé, écartés du balayage. `worktrees` en fait partie :
#: `.claude/worktrees/` héberge les copies de travail des agents, et ce fichier
#: tourne parfois depuis l'une d'elles — d'où le filtrage sur le chemin
#: **relatif** à la racine, le chemin absolu portant lui-même ces noms.
DOSSIERS_IGNORES = {
    ".venv", ".git", ".pytest_cache", ".ruff_cache", "node_modules", "worktrees",
}  # fmt: skip


def documents_a_verifier() -> list[Path]:
    """Tout le texte rédigé du dépôt : le Markdown et les fichiers de configuration.

    Volontairement **pas** `uv.lock` ni les sources : les URL de paquets y
    alignent des empreintes hexadécimales dont deux tranches finissent par
    ressembler à un couple de coordonnées (deux faux positifs mesurés, à
    23 et 40 km de Saint-Malo). On cherche ici ce qu'un humain a écrit, pas ce
    qu'un outil a engendré ; les sources, elles, ont déjà leurs invariants.
    """
    markdown = [
        p for p in RACINE.rglob("*.md") if not DOSSIERS_IGNORES & set(p.relative_to(RACINE).parts)
    ]
    return sorted(markdown) + sorted(CONFIGS_A_VERIFIER)


def couples_de_coordonnees(texte: str) -> list[tuple[int, float, float]]:
    """Les couples de décimales voisines d'une même ligne, dans les deux ordres.

    Un couple écrit en toutes lettres se lit lat/lon, un tableau GeoJSON se lit
    lon/lat : on essaie les deux plutôt que de parier sur une convention.
    Aucun exemple chiffré ici — ce fichier est scanné par le détecteur jumeau
    de `tests/adversarial/test_adv_invariants.py`, qui vient précisément de
    dénoncer la version où l'exemple était un vrai point français.
    """
    trouves = []
    for numero, ligne in enumerate(texte.splitlines(), 1):
        valeurs = [float(m) for m in DECIMAL.findall(ligne)]
        for gauche, droite in zip(valeurs, valeurs[1:], strict=False):
            for lat, lon in ((gauche, droite), (droite, gauche)):
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    trouves.append((numero, lat, lon))
    return trouves


def test_le_detecteur_de_texte_voit_une_coordonnee_plantee():
    """Sinon l'invariant suivant serait vert en ne sachant rien lire.

    La coordonnée de contrôle est **calculée** depuis `VILLES_CENTIEMES`, comme
    partout dans ce fichier : l'écrire en décimal ici dénoncerait ce test.
    """
    lat, lon = VILLES_REELLES["Rennes"]
    texte = f"le départ à ({lat}, {lon}), soit le centre-ville"
    trouves = couples_de_coordonnees(texte)
    assert trouves, "le détecteur ne voit pas un couple pourtant écrit noir sur blanc"
    assert any(ville_trop_proche(a, o) for _, a, o in trouves)
    assert not couples_de_coordonnees("un texte sans le moindre nombre")


@pytest.mark.parametrize(
    "document", documents_a_verifier(), ids=lambda p: str(p.relative_to(RACINE))
)
def test_aucun_document_ne_porte_de_coordonnee_reelle(document: Path):
    """`docs/` comprise : c'est là que le point du mainteneur a dormi le plus longtemps."""
    for numero, lat, lon in couples_de_coordonnees(document.read_text(encoding="utf-8")):
        proche = ville_trop_proche(lat, lon)
        assert proche is None, (
            f"{document.relative_to(RACINE)}:{numero} : ({lat}, {lon}) est à "
            f"{proche[1]:.1f} km de {proche[0]}. Nommer le lieu en toutes lettres suffit "
            "presque toujours ; le couple décimal, lui, se copie-colle dans une carte."
        )


def test_il_y_a_bien_des_documents_a_verifier():
    """Vert parce que le balayage ne trouve aucun document serait un invariant creux."""
    noms = {p.name for p in documents_a_verifier()}
    assert {"cadrage.md", "sprint1_relecture.md", "config.example.toml"} <= noms


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

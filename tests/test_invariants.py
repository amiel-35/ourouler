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
from collections.abc import Iterable
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


def chaines_de_code(chemin: Path) -> list[str]:
    """Les chaînes littérales **exécutées** d'un module, docstrings exclues.

    La distinction compte : `api/session.py` a le droit d'expliquer en prose
    ce que `OUROULER_MODE` veut dire — c'est de la documentation, et
    l'interdire reviendrait à interdire d'écrire pourquoi la règle existe. Ce
    qu'on refuse, c'est qu'un module **manipule** ce nom.

    **Publique exprès** : `tests/api/test_api_isolation_proprietaire.py` en
    avait une copie mot pour mot, et deux copies d'un même découpage finissent
    par ne plus dire la même chose. Il emprunte celle-ci par chemin, comme il
    emprunte déjà le reste de ce module.
    """
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            premier = noeud.body[0] if noeud.body else None
            if isinstance(premier, ast.Expr) and isinstance(premier.value, ast.Constant):
                docstrings.add(id(premier.value))
    return [
        noeud.value
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and id(noeud) not in docstrings
    ]


def test_les_variables_d_environnement_de_l_api_ne_se_nomment_qu_au_seul_endroit_autorise():
    """Aucune variable `OUROULER_*` de l'API manipulée hors du module d'exploitation.

    L'invariant voisin interdit `os.environ` hors de ce module ; celui-ci
    interdit d'en **écrire le nom dans du code**, ce qui est le premier pas
    vers l'autre porte — un module qui porte le nom finit par vouloir la
    valeur, et le détour par un `dict` passé en argument ne se verrait pas.
    Ajouté avec `OUROULER_DATABASE_URL` le 18/09/2026 (lot L7.2-A), il couvre
    du même coup `OUROULER_CONFIG`, `OUROULER_MODE` et `OUROULER_FRONT_DIST`.
    """
    from ourouler.api import exploitation

    noms = {
        valeur
        for cle, valeur in vars(exploitation).items()
        if cle.startswith("VARIABLE_") and isinstance(valeur, str)
    }
    assert "OUROULER_DATABASE_URL" in noms, "la variable de base de données a disparu"
    coupables: list[str] = []
    for module in SOURCES.rglob("*.py"):
        if module.relative_to(SOURCES).as_posix() in CHEMINS_AUTORISES:
            continue
        for chaine in chaines_de_code(module):
            coupables += [
                f"{module.relative_to(SOURCES)} porte {nom} dans son code"
                for nom in noms
                if nom in chaine
            ]
    assert not coupables, (
        "règle absolue 2 : seul api/exploitation.py nomme les variables de l'API — "
        + " ; ".join(coupables)
    )


def test_l_invariant_des_variables_saurait_voir_une_fuite(tmp_path: Path):
    """Contre-épreuve : la prose passe, le code ne passe pas."""
    prose = tmp_path / "prose.py"
    prose.write_text('"""Ce module explique OUROULER_MODE."""\nX = 1\n', encoding="utf-8")
    fuite = tmp_path / "fuite.py"
    fuite.write_text('def lire(env):\n    return env["OUROULER_MODE"]\n', encoding="utf-8")
    assert not any("OUROULER_MODE" in c for c in chaines_de_code(prose))
    assert any("OUROULER_MODE" in c for c in chaines_de_code(fuite))


#: Les accès aux données de l'API. Doctrine §10.2 : « aucune requête sans
#: clause de propriétaire » — ici, aucune méthode publique de dépôt sans
#: `proprietaire` en **premier argument positionnel**. C'est gratuit
#: aujourd'hui (un seul propriétaire) et impossible à rattraper le jour où
#: ces dépôts parleront à PostgreSQL.
CLASSES_DEPOT = ("DepotProfils", "DepotFichiers", "DepotGenerations")


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


def test_aucun_depot_ne_s_ajoute_a_depots_py_sans_etre_nomme():
    """`CLASSES_DEPOT` doit couvrir **toutes** les classes `Depot*` du module.

    Ajouté le 18/09/2026 (lot L7.2-A). Avant, `CLASSES_DEPOT` était une liste
    écrite à la main : un quatrième dépôt posé dans `api/depots.py` sans y
    être ajouté n'aurait jamais vu la clause de propriétaire, et rien n'aurait
    échoué. Un invariant qu'on contourne en **n'y pensant pas** ne garde rien.

    C'est aussi ce qui rend honnête la décision d'`api/comptes.py` : le dépôt
    des comptes ne prend pas de `Proprietaire` (un compte précède son
    propriétaire), et il vit donc **hors** de ce module plutôt que dedans en
    silence.
    """
    arbre = ast.parse((SOURCES / "api" / "depots.py").read_text(encoding="utf-8"))
    presentes = {
        noeud.name
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.ClassDef) and noeud.name.startswith("Depot")
    }
    assert presentes == set(CLASSES_DEPOT), (
        "api/depots.py porte des dépôts que CLASSES_DEPOT ne nomme pas : "
        f"{sorted(presentes - set(CLASSES_DEPOT))}. Un dépôt de ce module prend un "
        "Proprietaire en premier argument ; s'il ne le peut pas, il n'a rien à y faire "
        "(voir api/comptes.py)."
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


def test_les_fragments_qui_classent_les_avertissements_existent_vraiment():
    """Chaque avertissement codé se rattache à la phrase qui le déclenche.

    Même convention que `PREFIXES_SERVICE`, et pour la même raison. Avant le
    17/09/2026, le front décidait du bandeau « Pas de météo » en cherchant
    « météo » dans la phrase du cœur à l'expression régulière (relecture
    F2 · B3) : une reformulation en « Open-Meteo injoignable » faisait
    disparaître le bandeau **en silence**, et il restait un parcours servi
    sans pluie, sans vent et sans la phrase qui dit pourquoi.

    Le classement vit maintenant dans l'API, où ce test l'attache à son code.
    Reformuler un de ces avertissements casse ce test avant d'effacer un
    bandeau chez le cycliste — c'est tout ce qu'on lui demande.
    """
    from ourouler.api.erreurs import CODES_AVERTISSEMENT, MOTIFS_AVERTISSEMENT

    for fragment, code, modules in MOTIFS_AVERTISSEMENT:
        assert code in CODES_AVERTISSEMENT, (
            f"« {fragment} » classe en {code}, qui n'est pas dans le catalogue publié"
        )
        assert modules, f"« {fragment} » ne dit pas quel module l'écrit"
        for relatif in modules:
            texte = (SOURCES / relatif).read_text(encoding="utf-8")
            assert fragment in texte, (
                f"« {fragment} » n'apparaît plus dans {relatif} : l'API classera cet "
                f"avertissement en « autre » et l'écran dessiné pour {code} ne s'affichera plus"
            )


def test_le_catalogue_des_avertissements_a_un_cas_par_defaut():
    """Un avertissement inconnu reste affichable, sans qu'on en déduise un état.

    C'est la différence entre « je ne reconnais pas cette phrase » et « il n'y
    a pas d'avertissement » : la première se montre, la seconde se tairait.
    """
    from ourouler.api.erreurs import CODES_AVERTISSEMENT, classer_avertissement

    assert "autre" in CODES_AVERTISSEMENT
    assert classer_avertissement("une phrase que personne n'a prévue") == "autre"


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


# --- aucune requête SQL sans clause de propriétaire --------------------------
#
# Doctrine §10.2 : « Isolation des données : par utilisateur, vérifiée côté
# serveur à chaque requête, jamais seulement côté front. **Aucune requête sans
# clause de propriétaire.** »
#
# Une colonne que personne ne filtre ne protège rien : `apprentissage/routes.py`
# a porté `proprietaire` pendant quatre jours sans qu'aucune de ses requêtes ne
# la nomme. Cet invariant est écrit pour attraper la *prochaine* requête, celle
# qu'un agent ajoutera dans six mois sans y penser — pas pour vérifier une à une
# celles d'aujourd'hui.
#
# Ce qu'il fait : il reconstitue le texte SQL de chaque appel `.execute(…)` /
# `.executescript(…)` du cœur, y compris quand ce texte est assemblé à partir de
# constantes de module (`_COLONNES`, `_CONFLIT_IDENTITE`, `_SCHEMA`), et exige
# que toute instruction touchant une table de données nomme `proprietaire`.

#: Le mot que toute requête doit prononcer — **entier**. Les bornes de mot ont
#: été ajoutées le 18/09/2026 (lot L7.2-A) : sans elles, le seul nom de la
#: table `comptes_proprietaires` contient « proprietaire » et suffisait à
#: blanchir une requête qui ne filtre rien du tout. Un invariant qu'un nom de
#: table satisfait par accident ne garde plus rien.
CLAUSE = "proprietaire"
MOTIF_CLAUSE = re.compile(rf"\b{CLAUSE}\b")

#: Verbes SQL qui lisent ou écrivent des données. `CREATE`, `ALTER`, `DROP` et
#: `PRAGMA` n'en sont pas : ils décrivent la structure.
VERBES_DE_DONNEES = ("SELECT", "INSERT", "UPDATE", "DELETE")

#: Tables qui ne portent pas de données d'utilisateur : le catalogue de SQLite.
TABLES_TECHNIQUES = ("sqlite_master", "sqlite_temp_master")

#: **Les tables d'identité et d'accès** (lot L7.2-A, 18/09/2026). Elles ne
#: sont pas dispensées par commodité : un compte se crée **avant** que son
#: propriétaire existe, et une invitation se consomme alors que personne n'est
#: encore connecté. Leur demander une clause de propriétaire serait circulaire,
#: exactement comme pour les fonctions `_migrer` qui fabriquent la colonne.
#: C'est la frontière de [[Q46]] : le compte porte l'identité et l'accès, le
#: `Proprietaire` est la clé pseudonyme sous laquelle vivent les données.
#:
#: **Ce n'est pas une liste où l'on range ce qui gêne**, et trois garde-fous le
#: disent : la dispense porte sur les tables **réellement adressées** et non
#: sur la présence du mot (voir `tables_adressees`), donc
#: `comptes_proprietaires` — la table qui relie les deux — n'est pas exemptée
#: par le préfixe `comptes` et une jointure `activites × comptes` ne l'est pas
#: non plus ; et des contre-tests vérifient qu'une requête nue sur elle, comme
#: une requête mixte, sont bien refusées. Ajouter une ligne ici demande la même
#: justification que celle-ci : « cette table précède le propriétaire », pas
#: « cette table me pose un problème ».
#:
#: `sessions` (lot L7.2-C, 19/09/2026) : une session est retrouvée pour
#: produire un `Proprietaire`, elle n'en appartient à aucun — même
#: raisonnement que `comptes` et `invitations`.
TABLES_IDENTITE = ("comptes", "invitations", "sessions")

#: Les seules fonctions dispensées de la clause, et la raison. Une migration
#: **fabrique** la colonne : lui demander de filtrer dessus serait circulaire.
#: Le préfixe est volontairement étroit — `_migrer…`, pas « tout ce qui est
#: privé » — pour qu'on ne puisse pas s'y glisser par accident.
PREFIXE_EXEMPT = "_migrer"

#: Les commentaires SQL, `-- jusqu'au bout de la ligne` et `/* en bloc */`.
#: Ils sont retirés **avant** toute analyse : sans ça, le commentaire
#: « -- pose avec les migrations » collé au bout d'un `SELECT` nu suffisait à
#: le faire sortir du champ de l'invariant. Un invariant qu'une phrase de
#: prose désarme ne garde rien ([[Q58]]).
_COMMENTAIRE_SQL = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

#: Les mots après lesquels une instruction SQL nomme une table. `FROM` couvre
#: `SELECT … FROM` et `DELETE FROM`, `INTO` couvre `INSERT INTO`, et `JOIN` et
#: `UPDATE` se nomment eux-mêmes. Le motif est cherché **partout** dans
#: l'instruction, ce qui fait entrer les sous-requêtes sans effort : le
#: `FROM comptes` d'un `WHERE … IN (SELECT id FROM comptes)` est vu comme
#: n'importe quel autre.
_AVANT_UNE_TABLE = re.compile(r"\b(?:FROM|INTO|JOIN|UPDATE)\s+", re.IGNORECASE)

#: Ce qui **clôt** une liste de tables : le mot-clé de la clause suivante, ou
#: une parenthèse. Sans cette borne, `FROM activites a JOIN comptes c` rendrait
#: une seule « table » nommée « activites a JOIN comptes c ».
_FIN_DE_LISTE_DE_TABLES = re.compile(
    r"\b(?:WHERE|SET|VALUES|ON|USING|GROUP|ORDER|HAVING|LIMIT|OFFSET|RETURNING"
    r"|UNION|INTERSECT|EXCEPT|JOIN|LEFT|RIGHT|INNER|OUTER|CROSS|FULL|NATURAL"
    r"|SELECT|INSERT|UPDATE|DELETE|WINDOW|FETCH|FOR|DO|AS)\b|[()]",
    re.IGNORECASE,
)

#: Un nom de table tel qu'il s'écrit ici : identifiant nu, éventuellement
#: qualifié par un schéma (`information_schema.columns`) ou entre guillemets.
_NOM_DE_TABLE = re.compile(r'^"?([\w.]+)"?')


def sans_commentaires_sql(texte: str) -> str:
    """Le même texte, ses commentaires SQL remplacés par une espace.

    Une espace et non rien : `activites--commentaire` ne doit pas devenir
    `activites` collé à ce qui suit la ligne suivante.
    """
    return _COMMENTAIRE_SQL.sub(" ", texte)


def tables_adressees(instruction: str) -> set[str]:
    """Les tables qu'une instruction SQL lit ou écrit, en minuscules.

    **Ce n'est pas un analyseur SQL**, et ça n'a pas à l'être : c'est la
    lecture des quatre mots après lesquels ce dépôt nomme une table (`FROM`,
    `INTO`, `JOIN`, `UPDATE`), sous-requêtes comprises puisque le motif est
    cherché partout. Les alias sont jetés (`FROM activites a` → `activites`),
    les listes séparées par des virgules sont toutes rendues.

    **Elle échoue du bon côté.** Quand elle ne reconnaît rien, elle rend un
    ensemble vide — et l'appelant refuse alors la dispense au lieu de
    l'accorder : un cas indécidable est dénoncé, jamais blanchi.
    """
    trouvees: set[str] = set()
    texte = sans_commentaires_sql(instruction)
    for mot in _AVANT_UNE_TABLE.finditer(texte):
        suite = texte[mot.end() :]
        fin = _FIN_DE_LISTE_DE_TABLES.search(suite)
        liste = suite[: fin.start()] if fin is not None else suite
        for morceau in liste.split(","):
            nom = _NOM_DE_TABLE.match(morceau.strip())
            if nom is not None:
                trouvees.add(nom.group(1).lower())
    return trouvees


def dispensee_par_ses_tables(instruction: str, dispensees: Iterable[str]) -> bool:
    """Vrai si **toutes** les tables adressées sont dispensées, et qu'il y en a.

    Les deux conditions comptent, et chacune ferme une brèche mesurée :

    - « toutes » : `SELECT … FROM activites JOIN comptes …` touche une table
      de données *et* une table d'identité. Elle n'est pas dispensée — sans
      quoi la première jointure du premier lot qui branche les comptes sur les
      données passerait sans clause de propriétaire ;
    - « et qu'il y en a » : une instruction dont on n'a su lire aucune table
      n'est pas dispensée non plus. On préfère dénoncer un cas qu'on ne sait
      pas lire plutôt que de le blanchir.
    """
    tables = tables_adressees(instruction)
    return bool(tables) and tables <= {nom.lower() for nom in dispensees}


def _constantes_texte(arbre: ast.Module) -> dict[str, str]:
    """Les constantes de module dont la valeur est une chaîne, résolues entre elles.

    Deux passes : les chaînes littérales d'abord, puis les f-strings qui les
    citent (`_SCHEMA` cite `PROPRIETAIRE_LOCAL`). Deux passes suffisent ici, et
    une valeur non résolue reste sous sa forme `{nom}`, qui ne trompe personne.
    """
    connues: dict[str, str] = {}
    for _ in range(2):
        for noeud in arbre.body:
            if not isinstance(noeud, ast.Assign) or len(noeud.targets) != 1:
                continue
            cible = noeud.targets[0]
            if not isinstance(cible, ast.Name):
                continue
            texte = _texte_sql(noeud.value, connues)
            if texte is not None:
                connues[cible.id] = texte
    return connues


def _texte_sql(noeud: ast.AST, connues: dict[str, str]) -> str | None:
    """Le texte d'une expression de chaîne, ou None si ce n'en est pas une.

    Couvre ce que le projet écrit réellement : littéral, littéraux adjacents
    (déjà fusionnés par le parseur), `+`, nom de constante, f-string.
    """
    if isinstance(noeud, ast.Constant):
        return noeud.value if isinstance(noeud.value, str) else None
    if isinstance(noeud, ast.Name):
        return connues.get(noeud.id)
    if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Add):
        gauche = _texte_sql(noeud.left, connues)
        droite = _texte_sql(noeud.right, connues)
        return None if gauche is None or droite is None else gauche + droite
    if isinstance(noeud, ast.JoinedStr):
        morceaux = []
        for partie in noeud.values:
            if isinstance(partie, ast.Constant) and isinstance(partie.value, str):
                morceaux.append(partie.value)
            elif isinstance(partie, ast.FormattedValue):
                # La valeur interpolée quand on sait la résoudre ; sinon son
                # code source, qui porte au moins le nom de ce qui y entre.
                morceaux.append(
                    _texte_sql(partie.value, connues) or f"{{{ast.unparse(partie.value)}}}"
                )
        return "".join(morceaux)
    return None


def _instructions(sql: str) -> list[str]:
    """Le SQL découpé en instructions, chacune jugée séparément.

    Un `executescript` en enchaîne plusieurs : sans découpage, un `CREATE
    TABLE` portant la colonne blanchirait le `SELECT` qui le suit.

    Les commentaires partent **avant** le découpage : un `;` posé dans un
    commentaire couperait une instruction en deux morceaux dont aucun ne
    ressemblerait plus à ce qu'elle fait.
    """
    return [morceau for morceau in sans_commentaires_sql(sql).split(";") if morceau.strip()]


def _touche_des_donnees(instruction: str) -> bool:
    """Vrai si cette instruction lit ou écrit des données d'utilisateur.

    La dispense porte sur les **tables adressées** (`FROM`, `INTO`, `JOIN`,
    `UPDATE`, sous-requêtes comprises), jamais sur la présence d'un mot dans
    le texte. C'est la correction du 18/09/2026 : écrite par mention, elle
    dispensait `SELECT … FROM activites JOIN comptes …` — une requête qui lit
    bel et bien une table de données — parce que le mot « comptes » y figurait.
    """
    verbes = (re.search(rf"\b{verbe}\b", instruction, re.IGNORECASE) for verbe in VERBES_DE_DONNEES)
    if not any(verbes):
        return False
    return not dispensee_par_ses_tables(instruction, TABLES_TECHNIQUES + TABLES_IDENTITE)


def _fonction_englobante(arbre: ast.Module) -> dict[int, str]:
    """Nœud d'appel (par identité) → nom de la fonction qui le contient."""
    par_appel: dict[int, str] = {}
    for fonction in ast.walk(arbre):
        if not isinstance(fonction, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for interne in ast.walk(fonction):
            if isinstance(interne, ast.Call):
                par_appel.setdefault(id(interne), fonction.name)
    return par_appel


def requetes_du_module(chemin: Path) -> list[tuple[str, str]]:
    """[(fonction, instruction SQL)] pour chaque instruction de données du module."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    connues = _constantes_texte(arbre)
    englobante = _fonction_englobante(arbre)
    trouvees = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call) or not isinstance(noeud.func, ast.Attribute):
            continue
        if noeud.func.attr not in ("execute", "executescript", "executemany"):
            continue
        if not noeud.args:
            continue
        sql = _texte_sql(noeud.args[0], connues)
        if sql is None:
            continue
        nom = englobante.get(id(noeud), "<module>")
        trouvees.extend(
            (nom, instruction)
            for instruction in _instructions(sql)
            if _touche_des_donnees(instruction)
        )
    return trouvees


def modules_avec_sql() -> list[Path]:
    return sorted(p for p in SOURCES.rglob("*.py") if "execute" in p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("module", modules_avec_sql(), ids=lambda p: str(p.relative_to(SOURCES)))
def test_aucune_requete_sql_ne_lit_ni_n_ecrit_sans_clause_de_proprietaire(module: Path):
    """Doctrine §10.2 : aucune requête sans clause de propriétaire.

    L'échec nomme la fonction et l'instruction : ce qui manque est visible
    sans ouvrir le fichier.
    """
    nues = [
        f"{fonction}() : {' '.join(instruction.split())[:110]}…"
        for fonction, instruction in requetes_du_module(module)
        if not MOTIF_CLAUSE.search(instruction.lower())
        and not fonction.startswith(PREFIXE_EXEMPT)
    ]
    assert not nues, (
        f"{module.relative_to(SOURCES)} — requêtes sans clause de propriétaire :\n  "
        + "\n  ".join(nues)
        + "\nDoctrine §10.2 : « aucune requête sans clause de propriétaire ». "
        f"Seules les fonctions préfixées « {PREFIXE_EXEMPT} » en sont dispensées, "
        "parce qu'elles fabriquent la colonne."
    )


def test_l_invariant_de_proprietaire_mesure_bien_quelque_chose():
    """Un invariant vert parce qu'il ne trouve aucune requête serait creux.

    On vérifie aussi qu'il voit les requêtes des **trois** dépôts, y compris
    celles assemblées depuis des constantes de module : c'est précisément ce
    qu'une lecture naïve du texte source raterait.
    """
    par_module = {
        str(module.relative_to(SOURCES)): requetes_du_module(module)
        for module in modules_avec_sql()
    }
    total = sum(len(v) for v in par_module.values())
    assert total >= 15, f"seulement {total} requêtes analysées : {list(par_module)}"
    for attendu in (
        "activites/cache.py",
        "apprentissage/routes.py",
        "connecteurs/openmeteo_archive.py",
    ):
        assert par_module.get(attendu), f"aucune requête vue dans {attendu}"


def test_l_invariant_de_proprietaire_attrape_bien_une_requete_nue(tmp_path: Path):
    """Contre-épreuve : on lui donne le code fautif qu'on veut qu'il refuse.

    Les trois formes que le projet écrit réellement — littéral, littéraux
    adjacents, et SQL assemblé depuis une constante de module — plus une
    migration, qui doit rester tolérée, et une requête correcte.
    """
    faute = tmp_path / "fautif.py"
    faute.write_text(
        '_COLS = "a, b"\n'
        "def lister(cx):\n"
        '    cx.execute("SELECT a FROM activites WHERE debut > ?", (1,))\n'
        "def lister_en_morceaux(cx):\n"
        '    cx.execute("SELECT a FROM activites "\n'
        '               "WHERE debut > ?", (1,))\n'
        "def lister_par_constante(cx):\n"
        '    cx.execute(f"SELECT {_COLS} FROM activites")\n'
        "def _migrer(cx):\n"
        '    cx.execute("SELECT a FROM activites")\n'
        "def correcte(cx):\n"
        '    cx.execute("SELECT a FROM activites WHERE proprietaire = ?", ("x",))\n',
        encoding="utf-8",
    )
    fautives = {
        fonction
        for fonction, instruction in requetes_du_module(faute)
        if not MOTIF_CLAUSE.search(instruction.lower())
        and not fonction.startswith(PREFIXE_EXEMPT)
    }
    assert fautives == {"lister", "lister_en_morceaux", "lister_par_constante"}


def test_l_exemption_d_identite_ne_couvre_pas_la_table_de_correspondance(tmp_path: Path):
    """`TABLES_IDENTITE` dispense `comptes` et `invitations`, jamais le lien.

    Contre-épreuve du garde-fou décrit avec la constante (lot L7.2-A) :

    - une requête sur `comptes` ou `invitations` passe — un compte précède son
      propriétaire, lui demander de filtrer dessus serait circulaire ;
    - une requête sur `comptes_proprietaires` qui ne nomme pas la colonne est
      **refusée**, alors même que le nom de la table contient le mot. C'est
      précisément ce que les bornes de mot ajoutées ce jour-là empêchent.

    **Élargie le 18/09/2026 après une relecture adverse**, qui a montré que la
    dispense écrite « par mention du mot » blanchissait trois formes qu'elle
    dénonçait la veille — et que la contre-épreuve d'alors ne couvrait pas,
    parce qu'elle ne testait que les cas auxquels l'auteur avait pensé :

    - `jointure` : `activites JOIN comptes` lit bel et bien une table de
      données. C'est la requête que le premier lot qui branche les comptes sur
      les données écrira naturellement ;
    - `sous_requete` : le `IN (SELECT id FROM comptes)` d'un `DELETE` sur une
      table de données ne dispense pas ce `DELETE` ;
    - `commentaire` : un `-- …migrations…` collé au bout d'un `SELECT` nu est
      de la prose, pas une table adressée.
    """
    faute = tmp_path / "identite.py"
    faute.write_text(
        "def creer_compte(cx):\n"
        '    cx.execute("INSERT INTO comptes (id, email) VALUES (%s, %s)", ("a", "b"))\n'
        "def consommer(cx):\n"
        '    cx.execute("UPDATE invitations SET consomme_le = %s WHERE condense = %s", (1, 2))\n'
        "def lien_nu(cx):\n"
        '    cx.execute("SELECT compte FROM comptes_proprietaires")\n'
        "def lien_correct(cx):\n"
        '    cx.execute("SELECT proprietaire FROM comptes_proprietaires WHERE compte = %s", ("a",))\n'
        "def jointure(cx):\n"
        '    cx.execute("SELECT a.trace FROM activites a JOIN comptes c ON c.id = a.compte")\n'
        "def sous_requete(cx):\n"
        '    cx.execute("DELETE FROM routes_connues WHERE compte IN (SELECT id FROM comptes)")\n'
        "def commentaire(cx):\n"
        '    cx.execute("SELECT * FROM activites -- pose avec les migrations")\n'
        "def jointure_correcte(cx):\n"
        '    cx.execute("SELECT a.trace FROM activites a JOIN comptes c ON c.id = a.compte "\n'
        '               "WHERE a.proprietaire = %s", ("x",))\n',
        encoding="utf-8",
    )
    fautives = {
        fonction
        for fonction, instruction in requetes_du_module(faute)
        if not MOTIF_CLAUSE.search(instruction.lower())
        and not fonction.startswith(PREFIXE_EXEMPT)
    }
    assert fautives == {"lien_nu", "jointure", "sous_requete", "commentaire"}


# --- le front (lot F2) ------------------------------------------------------
#
# Le front est du TypeScript, mais il vit dans le même dépôt, et la règle
# absolue 1 ne s'arrête pas à la frontière des langages : une coordonnée
# réelle dans une fixture de test JavaScript est une coordonnée réelle dans le
# dépôt. L'invariant se lit donc ici, avec le même rayon interdit et les mêmes
# villes que pour les fixtures d'activité.

RACINE = Path(__file__).resolve().parents[1]
FRONT = RACINE / "front"

#: Une paire lat/lon en degrés décimaux, telle qu'un source TypeScript
#: l'écrirait : `[47.0, -0.5]`, `latitude: 47.0`, `LAT = 47.0`.
_DECIMAL = re.compile(r"-?\d{1,3}\.\d+")


def sources_du_front() -> list[Path]:
    """Tout ce qui est versionné sous `front/` : sources, tests, fixtures."""
    if not FRONT.is_dir():
        return []
    return sorted(
        p
        for p in FRONT.rglob("*")
        if p.is_file()
        and p.suffix in (".ts", ".tsx", ".json", ".css", ".html")
        and "node_modules" not in p.parts
        and "dist" not in p.parts
    )


def points_plausibles(texte: str) -> list[tuple[float, float]]:
    """Les couples de décimaux consécutifs qui pourraient être un point français.

    Grossier exprès : on préfère examiner trop de couples que d'en manquer un.
    Un couple n'est retenu que si le premier nombre tient dans les latitudes
    métropolitaines et le second dans les longitudes.
    """
    nombres = [float(n) for n in _DECIMAL.findall(texte)]
    points = []
    for gauche, droite in zip(nombres, nombres[1:], strict=False):
        if 41.0 <= gauche <= 52.0 and -6.0 <= droite <= 10.0:
            points.append((gauche, droite))
    return points


def test_le_front_ne_porte_aucune_coordonnee_reelle():
    """Les points inventés du front restent loin de toute vraie ville."""
    sources = sources_du_front()
    if not sources:
        pytest.skip("pas de dossier front/ dans cette copie du dépôt")
    fautes = []
    for source in sources:
        for lat, lon in points_plausibles(source.read_text(encoding="utf-8")):
            proche = ville_trop_proche(lat, lon)
            if proche is not None:
                fautes.append(
                    f"{source.relative_to(RACINE)} : ({lat}, {lon}) est à "
                    f"{proche[1]:.1f} km de {proche[0]}"
                )
    assert not fautes, "coordonnées réelles dans le front :\n" + "\n".join(fautes)


def test_l_invariant_du_front_saurait_reperer_une_vraie_ville():
    """Sans ce contrôle, le test ci-dessus pourrait être vert en ne mesurant rien."""
    lat, lon = VILLES_REELLES["Rennes"]
    texte = f"export const DEPART = [{lat}, {lon}];"
    points = points_plausibles(texte)
    assert points, "le repérage de couples ne trouve rien là où il y a un point"
    assert ville_trop_proche(*points[0]) is not None


def test_le_front_examine_bien_des_fichiers():
    """Un `rglob` qui ne trouve rien rendrait l'invariant précédent décoratif."""
    if not FRONT.is_dir():
        pytest.skip("pas de dossier front/ dans cette copie du dépôt")
    sources = sources_du_front()
    assert len(sources) >= 10, f"seulement {len(sources)} sources de front examinées"
    assert any(p.name == "fixtures.ts" for p in sources), "les fixtures du front ne sont pas lues"


def test_le_front_ne_porte_aucun_secret():
    """Ni clé d'API, ni jeton, ni adresse e-mail réelle (règle absolue 1)."""
    motifs = (
        re.compile(r"api[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9]{8,}[\"']", re.IGNORECASE),
        re.compile(r"[A-Za-z0-9._%+-]+@(?!exemple\.)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    )
    fautes = []
    for source in sources_du_front():
        contenu = source.read_text(encoding="utf-8")
        for motif in motifs:
            for trouve in motif.findall(contenu):
                fautes.append(f"{source.relative_to(RACINE)} : {trouve}")
    assert not fautes, "secret ou adresse réelle dans le front :\n" + "\n".join(fautes)

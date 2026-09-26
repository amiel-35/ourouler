"""Invariants du produit — ce qui doit rester vrai quel que soit le lot.

Contrat §5 et règles absolues 1 à 3 de CLAUDE.md :

* aucun module de `src/ourouler/` autre que `cli.py` et `config.py` ne lit
  `tomllib`, `os.environ`, `Path.home()` ni un chemin utilisateur ;
* aucun test n'ouvre de socket, et tout `httpx.Client` de `tests/` reçoit un
  transport bouchon ;
* aucun fichier de `tests/` ne contient de coordonnée à moins de 50 km d'une
  ville française réelle ;
* la clé d'API ne sort jamais de la CLI, même en `--json` ;
* la hiérarchie d'exceptions sur laquelle repose le code de sortie 2 tient.

Ces tests ne dépendent d'aucun lot : ils doivent passer dès maintenant et le
rester à chaque livraison.
"""

from __future__ import annotations

import ast
import re
import socket
from datetime import date, datetime
from pathlib import Path

import fabriques4
import httpx
import outils
import pytest
from conftest import RACINE, ReseauInterdit

from ourouler import cli
from ourouler import config as module_config
from ourouler.noyau import erreurs
from ourouler.sortie import commande as commande_sortie

SRC = RACINE / "src" / "ourouler"
TESTS = RACINE / "tests"

#: Seuls modules autorisés à connaître la machine hôte (CLAUDE.md règle 2).
FICHIERS_AUTORISES = {"cli.py", "config.py"}

#: **L'unique porte du paquet `api/`** (lot F1). L'API est une couche
#: d'exploitation comme `cli.py` ; ce droit est donné à un **chemin**, et à un
#: seul module — les routes, les dépôts et la traduction d'erreurs restent
#: soumis à la règle absolue 2. Le jumeau de cet invariant,
#: `tests/test_invariants.py`, vérifie en plus que le reste du paquet est bien
#: couvert et que cette porte-là sert vraiment.
CHEMINS_AUTORISES = {"api/exploitation.py"}

#: Attributs qui trahissent une lecture de l'environnement ou du foyer.
ATTRIBUTS_INTERDITS = {"environ", "getenv", "getenvb", "home", "expanduser", "expandvars"}

#: Modules interdits partout dans le cœur : la configuration passe par la CLI,
#: le réseau par `httpx` et rien d'autre.
MODULES_INTERDITS_PARTOUT = {"requests", "urllib", "urllib.request", "http.client", "socket"}
MODULES_INTERDITS_HORS_CLI = {"tomllib"} | MODULES_INTERDITS_PARTOUT

# Villes françaises de référence (centre approximatif). Liste courte et
# volontairement grossière : le but n'est pas la géographie mais d'attraper
# une coordonnée réelle copiée par inadvertance.
#
# Elles sont écrites en centièmes de degré, en entiers, pour que ce fichier ne
# contienne lui-même aucune coordonnée décimale : sinon le détecteur se
# dénoncerait, et il faudrait l'exclure de son propre scan.
VILLES_CENTIEMES = {
    "Rennes": (4811, -168),
    "Paris": (4886, 235),
    "Nantes": (4722, -155),
    "Saint-Malo": (4865, -203),
    "Vannes": (4766, -276),
    "Laval": (4807, -77),
}
VILLES = {nom: (lat / 100, lon / 100) for nom, (lat, lon) in VILLES_CENTIEMES.items()}
RAYON_INTERDIT_KM = 50.0

EXTENSIONS_TEXTE = {".py", ".toml", ".json", ".gpx", ".tcx", ".txt", ".md", ".csv", ".xml", ".cfg"}
NOMBRE = re.compile(r"-?\d{1,3}\.\d+")


def _fichiers_python(racine: Path) -> list[Path]:
    return sorted(p for p in racine.rglob("*.py") if "__pycache__" not in p.parts)


def _arbre(chemin: Path) -> ast.Module:
    return ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))


# --- le cœur ne sait pas où il tourne ---------------------------------------


def test_src_existe():
    assert SRC.is_dir(), f"arborescence inattendue : {SRC} introuvable"
    assert _fichiers_python(SRC), "aucun module Python sous src/ourouler"


def test_le_coeur_ne_lit_ni_configuration_ni_environnement():
    fautes: list[str] = []
    for chemin in _fichiers_python(SRC):
        autorise = (
            chemin.name in FICHIERS_AUTORISES
            or chemin.relative_to(SRC).as_posix() in CHEMINS_AUTORISES
        )
        interdits = MODULES_INTERDITS_PARTOUT if autorise else MODULES_INTERDITS_HORS_CLI
        relatif = chemin.relative_to(RACINE)
        for noeud in ast.walk(_arbre(chemin)):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.name.split(".")[0] in {m.split(".")[0] for m in interdits}:
                        fautes.append(f"{relatif}:{noeud.lineno} import {alias.name}")
            elif isinstance(noeud, ast.ImportFrom):
                racine_module = (noeud.module or "").split(".")[0]
                if racine_module in {m.split(".")[0] for m in interdits}:
                    fautes.append(f"{relatif}:{noeud.lineno} from {noeud.module} import …")
                if not autorise:
                    for alias in noeud.names:
                        if alias.name in ATTRIBUTS_INTERDITS:
                            fautes.append(f"{relatif}:{noeud.lineno} from … import {alias.name}")
            elif not autorise and isinstance(noeud, ast.Attribute):
                if noeud.attr in ATTRIBUTS_INTERDITS:
                    fautes.append(f"{relatif}:{noeud.lineno} .{noeud.attr}")
            elif not autorise and isinstance(noeud, ast.Name):
                if noeud.id in ATTRIBUTS_INTERDITS:
                    fautes.append(f"{relatif}:{noeud.lineno} {noeud.id}")
    assert not fautes, (
        "seuls cli.py et config.py peuvent toucher la machine hôte "
        "(CLAUDE.md règle 2, contrat §0) :\n  " + "\n  ".join(sorted(set(fautes)))
    )


def test_les_lots_absents_ne_cassent_pas_les_autres_commandes(ecrire_config, capsys):
    """Contrat §0 : chaque sous-commande importe son module paresseusement."""
    parseur = cli.construire_parseur()
    assert parseur is not None
    chemin = ecrire_config()
    assert cli.main(["--config", str(chemin), "config"]) == 0, (
        "la commande `config` doit tourner même si les lots L1.2 à L1.5 manquent"
    )
    assert capsys.readouterr().out.strip()


# --- la clé d'API ne sort pas -------------------------------------------------


@pytest.mark.parametrize("arguments", [["config"], ["--json", "config"]])
def test_la_cle_d_api_ne_s_affiche_jamais(ecrire_config, capsys, arguments):
    chemin = ecrire_config(
        f'[intervals]\nathlete_id = "{outils.ATHLETE_BIDON}"\napi_key = "{outils.CLE_BIDON}"\n'
    )
    assert cli.main(["--config", str(chemin), *arguments]) == 0
    sortie = capsys.readouterr()
    assert outils.CLE_BIDON not in sortie.out, "la clé d'API ne doit jamais être imprimée"
    assert outils.CLE_BIDON not in sortie.err


def test_la_cle_d_api_ne_sort_pas_dans_une_erreur_de_configuration(ecrire_config):
    """Une config invalide par ailleurs ne doit pas recracher la section intervals."""
    chemin = ecrire_config(
        f'[intervals]\nathlete_id = "{outils.ATHLETE_BIDON}"\napi_key = "{outils.CLE_BIDON}"\n'
    )
    texte = chemin.read_text(encoding="utf-8").replace("[depart]", "[depart_mal_nomme]")
    chemin.write_text(texte, encoding="utf-8")
    with pytest.raises(erreurs.ErreurConfig) as capture:
        module_config.charger(chemin)
    assert outils.CLE_BIDON not in str(capture.value)
    assert outils.CLE_BIDON not in repr(capture.value)


# --- hiérarchie d'exceptions -------------------------------------------------


@pytest.mark.parametrize("nom", ["ErreurConfig", "ErreurLecture", "ErreurConnecteur"])
def test_toutes_les_erreurs_metier_sont_des_erreurs_utilisateur(nom):
    """Le code de sortie 2 de la CLI repose entièrement sur cette hiérarchie."""
    classe = getattr(erreurs, nom)
    assert issubclass(classe, erreurs.ErreurUtilisateur), (
        f"{nom} doit dériver d'ErreurUtilisateur, sinon la CLI répond 1 avec une trace"
    )


def test_erreur_config_reste_une_value_error():
    """Contrat §0 : `ErreurConfig(ValueError)`, et erreur utilisateur à la fois."""
    assert issubclass(erreurs.ErreurConfig, ValueError)
    assert issubclass(erreurs.ErreurUtilisateur, Exception)


# --- pas de réseau dans les tests -------------------------------------------


def test_la_fixture_coupe_bien_le_reseau():
    with pytest.raises(ReseauInterdit):
        socket.socket()
    with pytest.raises(ReseauInterdit):
        socket.create_connection(("exemple.invalide", 80))
    with pytest.raises(ReseauInterdit):
        httpx.Client().get("https://exemple.invalide/")


def test_le_transport_bouchon_n_est_pas_gene_par_la_coupure():
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": 1})))
    assert client.get("https://exemple.invalide/x").json() == {"ok": 1}


def test_tout_client_httpx_des_tests_recoit_un_transport():
    """Contrat §5 : « httpx reçoit toujours un MockTransport »."""
    fautes: list[str] = []
    for chemin in _fichiers_python(TESTS):
        for noeud in ast.walk(_arbre(chemin)):
            if not isinstance(noeud, ast.Call):
                continue
            fonction = noeud.func
            if not isinstance(fonction, ast.Attribute) or fonction.attr not in ("Client", "AsyncClient"):
                continue
            if not (isinstance(fonction.value, ast.Name) and fonction.value.id == "httpx"):
                continue
            mots_cles = {mot.arg for mot in noeud.keywords}
            if "transport" not in mots_cles:
                fautes.append(f"{chemin.relative_to(RACINE)}:{noeud.lineno} httpx.{fonction.attr}(…)")
    # Le test `test_la_fixture_coupe_bien_le_reseau` construit exprès un client nu.
    fautes = [f for f in fautes if "test_adv_invariants.py" not in f]
    assert not fautes, "client httpx sans transport bouchon :\n  " + "\n  ".join(fautes)


# --- aucune coordonnée réelle ------------------------------------------------


def _ville_proche(lat: float, lon: float) -> tuple[str, float] | None:
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    for ville, (vlat, vlon) in VILLES.items():
        distance = outils.distance_km(lat, lon, vlat, vlon)
        if distance < RAYON_INTERDIT_KM:
            return ville, distance
    return None


def _paires_suspectes(texte: str) -> list[tuple[int, float, float, str, float]]:
    """Cherche, ligne par ligne, deux nombres qui forment une coordonnée française."""
    suspectes = []
    precedent: tuple[int, float] | None = None
    for numero, ligne in enumerate(texte.splitlines(), start=1):
        nombres = [float(m) for m in NOMBRE.findall(ligne)[:40]]
        candidats = []
        if precedent is not None and nombres:
            candidats.append((precedent[1], nombres[0]))
        for i, premier in enumerate(nombres):
            for second in nombres[i + 1 :]:
                candidats.append((premier, second))
        for a, b in candidats:
            for lat, lon in ((a, b), (b, a)):
                proche = _ville_proche(lat, lon)
                if proche:
                    suspectes.append((numero, lat, lon, proche[0], proche[1]))
        if nombres:
            precedent = (numero, nombres[-1])
    return suspectes


def _fichiers_texte(racine: Path) -> list[Path]:
    return sorted(
        p
        for p in racine.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTENSIONS_TEXTE and "__pycache__" not in p.parts
    )


def test_aucune_coordonnee_francaise_dans_les_tests():
    """Règle absolue 1 : pas de coordonnée de départ dans le dépôt, même en fixture."""
    fautes = []
    for chemin in _fichiers_texte(TESTS):
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, lat, lon, ville, distance in _paires_suspectes(texte):
            fautes.append(
                f"{chemin.relative_to(RACINE)}:{numero} ({lat}, {lon}) à {distance:.0f} km de {ville}"
            )
    assert not fautes, "coordonnées trop proches d'une ville française :\n  " + "\n  ".join(fautes)


def test_aucune_coordonnee_francaise_dans_les_fixtures_generees(hostiles):
    """Même vérification sur les fichiers d'activité réellement écrits."""
    fautes = []
    for nom, chemin in sorted(hostiles.items()):
        if chemin.suffix.lower() not in EXTENSIONS_TEXTE:
            continue  # le FIT est binaire : ses coordonnées viennent du générateur, déjà scanné
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, lat, lon, ville, distance in _paires_suspectes(texte):
            fautes.append(f"{nom}:{numero} ({lat}, {lon}) à {distance:.0f} km de {ville}")
    assert not fautes, "fixture trop proche d'une ville française :\n  " + "\n  ".join(fautes)


def test_le_detecteur_de_coordonnees_fonctionne():
    """Un test négatif sans assertion positive ne prouve rien : on vérifie le détecteur.

    Les coordonnées de contrôle sont fabriquées à l'exécution, jamais écrites
    en clair dans le fichier (voir `VILLES_CENTIEMES`).
    """
    lat, lon = VILLES["Rennes"]
    assert _paires_suspectes(f"latitude = {lat}\nlongitude = {lon}\n"), "Rennes doit être détecté"
    lat, lon = VILLES["Paris"]
    assert _paires_suspectes(f'lat="{lat:.6f}" lon="{lon:.6f}"'), "Paris doit être détecté"
    assert not _paires_suspectes('lat="0.000000" lon="0.000000"'), "(0, 0) est en mer"
    assert not _paires_suspectes("masse_kg = 80.0\nftp_w = 250.0\n"), "faux positif sur des scalaires"
    assert not _paires_suspectes('lat="0.0009" lon="0.0004"'), "la trajectoire synthétique est en mer"


# --- pas de donnée ni de clé versionnée --------------------------------------


def test_aucun_fichier_d_activite_hors_des_fixtures():
    """`.gitignore` ne réintègre nommément que quelques fixtures : ailleurs, rien de binaire.

    Les fichiers hostiles de ce dossier sont générés dans un `tmp_path`, jamais
    déposés à côté des tests.
    """
    fixtures = TESTS / "fixtures"
    suspects = [
        p.relative_to(RACINE)
        for p in TESTS.rglob("*")
        if p.is_file() and p.suffix.lower() in (".fit", ".tcx", ".gpx") and fixtures not in p.parents
    ]
    assert not suspects, f"fichiers d'activité hors de tests/fixtures/ : {suspects}"


def test_aucun_test_ne_fabrique_un_faux_module_ourouler():
    """Un test ne doublure pas un module de production : il l'importe.

    Le fichier de placement installait, **à l'import**, de faux
    `ourouler.noyau.seance` et `ourouler.seance.terrain` quand les vrais ne
    s'importaient pas. L'échafaudage a servi le temps que les lots s'écrivent
    en parallèle ; gardé, il rendait la suite menteuse — un symbole renommé
    dans `boucle.couts` aurait fait passer vingt-quatre tests au vert contre
    un `evaluer_couloir` qui rend toujours 0 et une `demi_tour_faisable` qui
    dit toujours oui.

    Trois gestes interdits, tous ceux qu'il fallait pour monter la doublure :
    fabriquer un `ModuleType` au nom d'`ourouler`, l'accrocher au paquet par
    `setattr`, ou l'écrire dans `sys.modules`. Charger par chemin un module de
    fixtures (`generer_activites`, `workouts`…) reste permis : il ne masque
    aucun module de production. `monkeypatch.setattr` aussi, qui est défait à
    la fin de chaque test — ce qu'une écriture à l'import n'est pas.
    """
    fautes: list[str] = []
    for chemin in _fichiers_python(TESTS):
        for noeud in ast.walk(_arbre(chemin)):
            texte = ast.unparse(noeud)
            if isinstance(noeud, ast.Assign):
                for cible in noeud.targets:
                    if (
                        isinstance(cible, ast.Subscript)
                        and ast.unparse(cible.value) == "sys.modules"
                        and "ourouler" in ast.unparse(cible.slice)
                    ):
                        fautes.append(f"{chemin.relative_to(RACINE)}:{noeud.lineno} {texte}")
            if not isinstance(noeud, ast.Call):
                continue
            appele = ast.unparse(noeud.func)
            fabrique = appele.endswith("ModuleType") and "ourouler" in texte
            accroche = (
                appele == "setattr"
                and noeud.args
                and ast.unparse(noeud.args[0]).startswith("ourouler")
            )
            if fabrique or accroche:
                fautes.append(f"{chemin.relative_to(RACINE)}:{noeud.lineno} {texte}")
    assert not fautes, (
        "un test remplace un module de production au lieu de l'importer :\n  "
        + "\n  ".join(fautes)
    )


def test_fabriques4_ne_saute_jamais(tmp_path, monkeypatch):
    """`fabriques4.module` ne saute plus : il échoue si le module manque.

    Tous les lots du contrat existent. Un module introuvable est donc une
    régression, et un `ImportError` interne remonte tel quel : dans les deux
    cas, un saut transformerait une suite adversariale entière en vert (c'est
    arrivé au retrait des réexports : 30 tests sautaient en silence).
    """
    paquet = tmp_path / "paquet_de_test"
    paquet.mkdir()
    (paquet / "__init__.py").write_text("", encoding="utf-8")
    (paquet / "present.py").write_text("VALEUR = 1\n", encoding="utf-8")
    (paquet / "casse.py").write_text(
        "from paquet_de_test.inexistant import quoi_que_ce_soit\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(fabriques4, "PAQUETS", ("paquet_de_test",))

    assert fabriques4.module("present", motif="absent").VALEUR == 1

    with pytest.raises(ModuleNotFoundError):
        fabriques4.module("casse", motif="ne doit pas être sauté")

    with pytest.raises(pytest.fail.Exception, match="lot jamais écrit"):
        fabriques4.module("jamais_ecrit", motif="lot jamais écrit")


def test_les_fichiers_par_defaut_de_sortie_ne_vont_pas_dans_le_dossier_courant(
    tmp_path, tmp_path_factory, monkeypatch
):
    """Règle absolue 1, version Q23 : ne plus dépendre de `.gitignore`.

    Avant ce correctif, sans `--sortie` ni `--carte`, les deux noms par
    défaut — `sortie_<AAAAMMJJ>.gpx` et `sortie_<AAAAMMJJ>.html` —
    s'écrivaient dans le **répertoire courant**, donc le dépôt quand la
    commande y est lancée depuis là — ce que fait le mainteneur. `.gitignore`
    les couvrait (voir l'historique de ce test), mais « un fichier que seul
    `.gitignore` protège n'est pas protégé, il est seulement discret » : ces
    fichiers portent ses coordonnées de départ, et ils étaient à un
    `git add -f` ou un `zip -r` du dépôt près de voyager avec lui.

    La correction retire le risque à la source plutôt que de le masquer :
    le répertoire courant n'entre même plus dans le calcul du chemin par
    défaut, qui vit sous le dossier de cache déjà configuré
    (`config.cache.dossier`). Le test se place dans un dossier qui **est**
    un dépôt (un `.git/` y suffit à le faire ressembler à celui du
    mainteneur) et vérifie que les deux chemins par défaut n'y tombent pas.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    dossier_cache = tmp_path_factory.mktemp("cache-hors-depot")
    config = module_config.Config(
        depart=module_config.Depart(nom="Point zéro", latitude=0.0, longitude=0.0),
        cycliste=module_config.Cycliste(masse_kg=75.0, ftp_w=250.0),
        cache=module_config.ParametresCache(dossier=dossier_cache),
    )
    demande = commande_sortie.Demande(
        jour=date(2026, 2, 8),
        distance_km=None,
        direction="",
        azimut_deg=None,
        nb_candidates=4,
        profil="route",
        depart=datetime(2026, 2, 8, 9, 0),
        velo=None,
        sortie=None,
        carte=None,
    )
    par_defaut = [
        commande_sortie.chemin_gpx_par_defaut(demande, config.cache.dossier),
        commande_sortie.chemin_carte_par_defaut(demande, config.cache.dossier),
    ]
    dans_le_depot = [c for c in par_defaut if c.resolve().is_relative_to(tmp_path.resolve())]
    assert not dans_le_depot, (
        f"`ourouler sortie` écrirait ces fichiers dans le dépôt : {dans_le_depot}"
    )
    for chemin in par_defaut:
        assert chemin.resolve().is_relative_to(dossier_cache.resolve()), (
            f"{chemin} n'est pas sous le dossier de cache configuré {dossier_cache}"
        )


# --- sprint 2 : le mot de passe BRouter ne sort jamais -----------------------

#: Faux mot de passe de serveur BRouter (aucune valeur réelle, règle absolue 1).
MOT_DE_PASSE_BIDON = "mot-de-passe-brouter-de-test-qui-ne-doit-jamais-fuiter-0123456789"
SECTION_BROUTER = (
    '[brouter]\nurl = "https://brouter.exemple.invalide"\n'
    'utilisateur = "utilisateur-de-test"\n'
    f'mot_de_passe = "{MOT_DE_PASSE_BIDON}"\n'
)


@pytest.mark.parametrize("arguments", [["config"], ["--json", "config"]])
def test_le_mot_de_passe_brouter_ne_s_affiche_jamais(ecrire_config, capsys, arguments):
    """Contrat sprint 2 §0 : « jamais le mot de passe dans une erreur, un log, un `repr` »."""
    chemin = ecrire_config(SECTION_BROUTER)
    assert cli.main(["--config", str(chemin), *arguments]) == 0
    sortie = capsys.readouterr()
    assert MOT_DE_PASSE_BIDON not in sortie.out, (
        f"`ourouler {' '.join(arguments)}` imprime le mot de passe du serveur BRouter"
    )
    assert MOT_DE_PASSE_BIDON not in sortie.err


def test_le_mot_de_passe_brouter_n_est_ni_dans_str_ni_dans_repr_de_la_config(ecrire_config):
    chemin = ecrire_config(SECTION_BROUTER)
    config = module_config.charger(chemin)
    assert config.brouter.mot_de_passe == MOT_DE_PASSE_BIDON, "le mot de passe doit rester lisible"
    for texte, quoi in ((repr(config), "repr(Config)"), (str(config), "str(Config)")):
        assert MOT_DE_PASSE_BIDON not in texte, f"{quoi} publie le mot de passe BRouter"
    for texte, quoi in (
        (repr(config.brouter), "repr(ParametresBrouter)"),
        (str(config.brouter), "str(ParametresBrouter)"),
        (f"{config.brouter}", "format(ParametresBrouter)"),
    ):
        assert MOT_DE_PASSE_BIDON not in texte, f"{quoi} publie le mot de passe BRouter"


def test_le_mot_de_passe_brouter_ne_sort_pas_d_une_erreur_de_configuration(ecrire_config):
    """Une faute ailleurs dans le fichier ne doit pas recracher la section [brouter]."""
    chemin = ecrire_config(SECTION_BROUTER + '[meteo]\nhorizon_h = "six"\n')
    with pytest.raises(erreurs.ErreurConfig) as capture:
        module_config.charger(chemin)
    for texte in (str(capture.value), repr(capture.value)):
        assert MOT_DE_PASSE_BIDON not in texte, f"le mot de passe fuit dans « {texte[:200]} »"


# --- sprint 2 : rien de personnel dans src/ ni tests/ ------------------------

#: Identifiants d'équipement Intervals et capteurs du mainteneur. Ils ont leur
#: place dans `docs/` (le contrat les cite pour que le code sache quoi chercher)
#: mais **pas** dans `src/` ni `tests/` : ce sont ses données.
#:
#: Écrits à l'envers, comme `VILLES_CENTIEMES` : sinon ce fichier se
#: dénoncerait lui-même et il faudrait l'exclure de son propre scan.
GEAR_INVERSES = ("43457531", "45455051", "3537449", "7772295")
CAPTEURS_INVERSES = (("MARS", "2501"), ("QRAUQ", "55043"))
DOMAINE_PRIVE = ".".join(("inflexion", "me"))


def _jetons_prives() -> list[str]:
    jetons = [f"b{inverse[::-1]}" for inverse in GEAR_INVERSES]
    jetons += [inverse[::-1] for inverse in GEAR_INVERSES]
    for marque_inverse, numero_inverse in CAPTEURS_INVERSES:
        marque, numero = marque_inverse[::-1], numero_inverse[::-1]
        jetons += [marque, f"{marque} {numero}", f"{marque}{numero}"]
    jetons.append(DOMAINE_PRIVE)
    return jetons


def _occurrences(texte: str) -> list[str]:
    minuscule = texte.casefold()
    return [jeton for jeton in _jetons_prives() if jeton.casefold() in minuscule]


#: Fichiers hors `src/` et `tests/` que le détecteur doit quand même lire.
#: `config.example.toml` est celui que l'utilisateur copie — et c'est
#: précisément lui qui portait le capteur réel avant `24d2f09` : le détecteur
#: regardait à côté du seul endroit où la faute s'est produite (point 13 de la
#: relecture du sprint 2). `README.md` est publié tel quel.
FICHIERS_PUBLIES = ("config.example.toml", "README.md")


def _fichiers_a_scanner() -> list[Path]:
    """`src/`, `tests/`, et les fichiers publiés à la racine.

    `docs/` reste hors du champ : il cite volontairement les capteurs et les
    identifiants du mainteneur, c'est là que le contrat dit au code quoi
    chercher. Le sort de ces valeurs est une décision du mainteneur (Q6), pas
    un test.
    """
    racine = [RACINE / nom for nom in FICHIERS_PUBLIES]
    manquants = [chemin.name for chemin in racine if not chemin.is_file()]
    assert not manquants, f"fichiers publiés attendus à la racine, absents : {manquants}"
    return _fichiers_texte(SRC) + _fichiers_texte(TESTS) + racine


def test_le_detecteur_de_donnees_personnelles_fonctionne():
    """Un test négatif ne prouve rien sans la preuve que le détecteur détecte."""
    marque, numero = CAPTEURS_INVERSES[0][0][::-1], CAPTEURS_INVERSES[0][1][::-1]
    assert _occurrences(f'capteur_puissance = "{marque} {numero}"'), "le capteur doit être repéré"
    assert _occurrences(f"gear id b{GEAR_INVERSES[0][::-1]}"), "l'identifiant doit être repéré"
    assert _occurrences(f"url = 'https://brouter.{DOMAINE_PRIVE}'"), "le domaine doit être repéré"
    assert not _occurrences('capteur_puissance = "CAPTEUR ALPHA 1234"'), "faux positif sur un nom inventé"
    assert not _occurrences("gear_id = 'g-beta'"), "faux positif sur un identifiant inventé"


def test_aucune_donnee_personnelle_du_mainteneur_hors_de_docs():
    """Règle absolue 1 : capteurs, identifiants d'équipement et URL privée restent dans docs/.

    Le champ couvre `src/`, `tests/`, `config.example.toml` et `README.md` —
    tout ce qu'un dépôt public publie et qu'un utilisateur recopie.
    """
    fautes = []
    for chemin in _fichiers_a_scanner():
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            for jeton in _occurrences(ligne):
                fautes.append(f"{chemin.relative_to(RACINE)}:{numero} — « {jeton} »")
    assert not fautes, (
        "données du mainteneur hors de docs/ (capteur, identifiant d'équipement ou URL privée) :\n  "
        + "\n  ".join(fautes)
    )


def test_les_tests_adversariaux_n_appellent_que_des_domaines_de_test():
    """Aucune URL réelle dans ce dossier : tout serveur fabriqué finit en `.invalide`."""
    # Les espaces de noms XML (GPX, TCX) sont des URL qui ne sont jamais appelées.
    autorises = (
        "exemple.invalide",
        "www.topografix.com",
        "www.w3.org",
        "www.garmin.com",
        "opengis.net",
    )
    url = re.compile(r"https?://([A-Za-z0-9.:-]+)")
    fautes = []
    for chemin in _fichiers_python(TESTS / "adversarial"):
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            for hote in url.findall(ligne):
                if hote.endswith("."):
                    continue  # URL recomposée à l'exécution (f-string)
                if not any(hote.endswith(suffixe) for suffixe in autorises):
                    fautes.append(f"{chemin.relative_to(RACINE)}:{numero} — {hote}")
    assert not fautes, (
        "hôte non fictif dans les tests adversariaux (utiliser un domaine .invalide) :\n  "
        + "\n  ".join(fautes)
    )


# --- sprint 3 : numpy reste dans physique/ -----------------------------------

#: `numpy` est autorisé par le contrat du sprint 3 §3 pour l'ajustement aux
#: moindres carrés, et **seulement** là. Partout ailleurs il transformerait une
#: bibliothèque que le mainteneur installe en une seconde en un paquet compilé
#: de 20 Mo, pour une somme pondérée qu'un `for` écrit aussi bien (CLAUDE.md :
#: « 50 lignes évidentes valent mieux que 20 lignes malignes »).
DOSSIER_NUMPY_AUTORISE = SRC / "physique"
MODULES_CALCUL_LOURD = {"numpy", "scipy", "pandas"}


def _imports(chemin: Path) -> list[tuple[int, str]]:
    """(ligne, module racine) pour chaque import du fichier."""
    trouves: list[tuple[int, str]] = []
    for noeud in ast.walk(_arbre(chemin)):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                trouves.append((noeud.lineno, alias.name.split(".")[0]))
        elif isinstance(noeud, ast.ImportFrom):
            trouves.append((noeud.lineno, (noeud.module or "").split(".")[0]))
    return trouves


def test_numpy_ne_sort_pas_de_physique():
    """Contrat sprint 3 §3 et §4 : « numpy autorisé, pas scipy » — et seulement dans `physique/`."""
    fautes = []
    for chemin in _fichiers_python(SRC):
        dans_physique = DOSSIER_NUMPY_AUTORISE in chemin.parents
        for ligne, module in _imports(chemin):
            if module not in MODULES_CALCUL_LOURD:
                continue
            if module == "numpy" and dans_physique:
                continue
            fautes.append(f"{chemin.relative_to(RACINE)}:{ligne} import {module}")
    assert not fautes, (
        "calcul lourd hors de src/ourouler/physique/ (le contrat n'autorise que numpy, "
        "et seulement là ; scipy est exclu partout) :\n  " + "\n  ".join(fautes)
    )


def test_le_detecteur_d_imports_fonctionne(tmp_path):
    """Un test négatif ne prouve rien sans la preuve que le détecteur détecte."""
    faux = tmp_path / "faux.py"
    faux.write_text("import numpy as np\nfrom scipy import optimize\nimport math\n", encoding="utf-8")
    modules = {module for _, module in _imports(faux)}
    assert {"numpy", "scipy"} <= modules, f"le détecteur laisse passer {modules}"
    assert "math" in modules, "le détecteur doit voir tous les imports, pas seulement les interdits"


# --- sprint 3 : le cœur ne fabrique pas les chemins du cache -----------------

#: Fichiers que le sprint 3 range dans `cache.dossier`. Le contrat est explicite :
#: « le cœur ne lit pas de fichier : c'est `boucle/commande.py` qui lit le JSON
#: et passe le dict », « le cache est passé en paramètre (le cœur ne connaît pas
#: le chemin) ». Un module du cœur qui écrit le nom de fichier en dur sait donc
#: où il tourne — c'est la règle absolue 2 contournée par une chaîne.
FICHIERS_DU_CACHE = (
    "routes_connues.sqlite",
    "poids_routes.json",
    "archive_meteo.sqlite",
    "calibration.json",
)


def _chaines(chemin: Path) -> list[tuple[int, str]]:
    return [
        (noeud.lineno, noeud.value)
        for noeud in ast.walk(_arbre(chemin))
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
    ]


def _peut_nommer_un_fichier_du_cache(chemin: Path) -> bool:
    """`cli.py` et les `commande.py` de chaque paquet : eux seuls lisent le disque."""
    return chemin.name == "cli.py" or chemin.name == "commande.py"


def test_le_coeur_ne_fabrique_pas_les_chemins_du_cache():
    """Contrat sprint 3 §2 et §3 : le cœur reçoit des objets, la CLI lit les fichiers."""
    fautes = []
    for chemin in _fichiers_python(SRC):
        if _peut_nommer_un_fichier_du_cache(chemin):
            continue
        for ligne, texte in _chaines(chemin):
            for fichier in FICHIERS_DU_CACHE:
                if fichier in texte:
                    fautes.append(f"{chemin.relative_to(RACINE)}:{ligne} — « {fichier} »")
    assert not fautes, (
        "nom de fichier du cache écrit en dur hors de cli.py et des commande.py "
        "(le cœur reçoit un chemin ou un dict, il ne le fabrique pas) :\n  "
        + "\n  ".join(sorted(set(fautes)))
    )


def test_le_detecteur_de_chemins_du_cache_fonctionne(tmp_path):
    faux = tmp_path / "faux.py"
    faux.write_text(
        'CHEMIN = dossier / "poids_routes.json"\nAUTRE = "index.sqlite"\n', encoding="utf-8"
    )
    textes = {texte for _, texte in _chaines(faux)}
    assert "poids_routes.json" in textes, "le détecteur ne voit pas la chaîne fautive"
    assert not any(f in t for t in textes for f in FICHIERS_DU_CACHE if f != "poids_routes.json"), (
        "faux positif sur un nom de fichier qui n'est pas du sprint 3"
    )


# --- sprint 4 : le paquet de la séance reste dans le cœur --------------------

#: Le contrat du sprint 4 nomme le paquet `seance/`, la doctrine §4 `sortie/`.
#: Les règles valent pour celui des deux qui existe.
PAQUETS_SEANCE = ("seance", "sortie")

#: Modules du cœur du sprint 4. `commande.py` en est exclu : c'est lui qui a le
#: droit de lire le disque et de connaître le jour courant (CLAUDE.md règle 2).
MODULES_SEANCE_COEUR = ("modele.py", "intervals.py", "terrain.py", "placement.py", "tenue.py")

#: Modules qui trahissent un accès au disque. `json` est traité à part : seuls
#: `json.load` et `json.dump` (les variantes fichier) sont interdits.
MODULES_DISQUE = {"pathlib", "sqlite3", "shutil", "tempfile", "os", "tomllib", "csv"}
APPELS_DISQUE = {
    "open", "read_text", "write_text", "read_bytes", "write_bytes",
    "mkdir", "unlink", "iterdir", "glob", "rglob", "connect",
}
#: Lectures de l'horloge : le cœur reçoit le jour, il ne le devine pas.
APPELS_HORLOGE = {"now", "today", "utcnow", "fromtimestamp"}


def _dossier_seance() -> Path | None:
    for nom in PAQUETS_SEANCE:
        if (SRC / nom).is_dir():
            return SRC / nom
    return None


def _modules_seance() -> list[Path]:
    dossier = _dossier_seance()
    if dossier is None:
        pytest.skip("paquet du sprint 4 absent (src/ourouler/seance/ ou sortie/)")
    modules = [p for p in _fichiers_python(dossier) if p.name in MODULES_SEANCE_COEUR]
    assert modules, (
        f"{dossier.relative_to(RACINE)} existe mais ne contient aucun des modules du contrat "
        f"{MODULES_SEANCE_COEUR}"
    )
    return modules


def _appels(chemin: Path) -> list[tuple[int, str]]:
    """(ligne, nom appelé) pour chaque appel de fonction ou de méthode."""
    trouves: list[tuple[int, str]] = []
    for noeud in ast.walk(_arbre(chemin)):
        if not isinstance(noeud, ast.Call):
            continue
        fonction = noeud.func
        if isinstance(fonction, ast.Name):
            trouves.append((noeud.lineno, fonction.id))
        elif isinstance(fonction, ast.Attribute):
            if isinstance(fonction.value, ast.Name):
                trouves.append((noeud.lineno, f"{fonction.value.id}.{fonction.attr}"))
            trouves.append((noeud.lineno, fonction.attr))
    return trouves


def _fautes_de_disque(chemin: Path) -> list[str]:
    relatif = chemin.relative_to(RACINE) if chemin.is_relative_to(RACINE) else chemin.name
    fautes = [
        f"{relatif}:{ligne} import {module}"
        for ligne, module in _imports(chemin)
        if module in MODULES_DISQUE
    ]
    for ligne, appel in _appels(chemin):
        if appel in APPELS_DISQUE or appel in ("json.load", "json.dump"):
            fautes.append(f"{relatif}:{ligne} {appel}(…)")
    return fautes


def test_les_modules_de_la_seance_sont_bien_scannes_par_les_regles_du_coeur():
    """La règle « le cœur ne sait pas où il tourne » doit couvrir le paquet du sprint 4.

    Les détecteurs des sprints 1 à 3 parcourent `src/ourouler/` en entier : ce
    test vérifie que le nouveau paquet n'y échappe pas, sans quoi la garantie
    serait vide pour les modules qui viennent d'arriver.
    """
    modules = _modules_seance()
    scannes = set(_fichiers_python(SRC))
    manquants = [str(m.relative_to(RACINE)) for m in modules if m not in scannes]
    assert not manquants, f"modules du sprint 4 hors du champ des règles du cœur : {manquants}"


def test_le_coeur_de_la_seance_ne_touche_pas_au_disque():
    """Contrat §1 à §3 : le cœur reçoit une séance, un tracé et des paramètres.

    Seuls `cli.py` et les `commande.py` lisent un chemin. Un `open()` ou un
    `pathlib` dans `placement.py` est la règle absolue 2 contournée.
    """
    fautes = [faute for chemin in _modules_seance() for faute in _fautes_de_disque(chemin)]
    assert not fautes, (
        "accès au disque dans le cœur du sprint 4 (seuls cli.py et les commande.py y ont droit) :\n  "
        + "\n  ".join(fautes)
    )


def test_le_coeur_de_la_seance_ne_lit_pas_l_horloge():
    """`seance_du_jour(client, jour)` reçoit le jour : le cœur ne consulte pas la machine.

    C'est la même règle que le disque et l'environnement : deux exécutions du
    placement sur les mêmes entrées doivent donner le même résultat, y compris
    à cheval sur minuit ou sur un changement d'heure.
    """
    fautes = []
    for chemin in _modules_seance():
        for ligne, appel in _appels(chemin):
            nom = appel.split(".")[-1]
            if nom in APPELS_HORLOGE:
                fautes.append(f"{chemin.relative_to(RACINE)}:{ligne} {appel}(…)")
    assert not fautes, (
        "lecture de l'horloge dans le cœur du sprint 4 (le jour est un paramètre) :\n  "
        + "\n  ".join(sorted(set(fautes)))
    )


#: Modules du sprint 4 qui ne parlent à personne : ils reçoivent des objets.
MODULES_SANS_RESEAU = ("modele.py", "terrain.py", "placement.py", "tenue.py")


def test_le_terrain_le_placement_et_la_tenue_n_ouvrent_aucune_connexion():
    """Règle absolue 3 : le client HTTP est injecté, et seulement au connecteur."""
    fautes = []
    for chemin in _modules_seance():
        if chemin.name not in MODULES_SANS_RESEAU:
            continue
        for ligne, module in _imports(chemin):
            if module in {"httpx", "requests", "urllib", "http", "socket"}:
                fautes.append(f"{chemin.relative_to(RACINE)}:{ligne} import {module}")
    assert not fautes, "réseau dans le cœur du sprint 4 :\n  " + "\n  ".join(fautes)


#: Ce que `seance/terrain.py` doit **importer** de `boucle.couts` plutôt que de
#: le réécrire : la liste des routes passantes, la détection géométrique des
#: virages, et le découpage en tronçons qui ferme la contamination d'un bloc
#: par les tags du tronçon précédent.
SYMBOLES_DE_COUTS = {"HIGHWAY_TRAFIC", "virages_detectes", "tags_par_troncon"}


def test_le_terrain_reutilise_la_mecanique_des_couts():
    """Contrat §2 : « réutiliser la mécanique de `couts`, ne pas la dupliquer ».

    L'assertion d'origine se contentait de `"couts" in texte` : un commentaire
    contenant le mot suffisait à la satisfaire, et une réécriture complète de
    la détection des virages serait passée au vert. On exige maintenant un
    **import réel** des symboles nommés.
    """
    modules = {chemin.name: chemin for chemin in _modules_seance()}
    terrain = modules.get("terrain.py")
    if terrain is None:
        pytest.skip("terrain.py absent (lot L4.2)")
    importes: set[str] = set()
    for noeud in ast.walk(_arbre(terrain)):
        if isinstance(noeud, ast.ImportFrom) and (noeud.module or "").endswith("boucle.couts"):
            importes.update(alias.name for alias in noeud.names)
    manquants = sorted(SYMBOLES_DE_COUTS - importes)
    assert not manquants, (
        f"terrain.py n'importe pas de `boucle.couts` : {manquants} — la détection "
        "des virages, la liste des routes passantes ou le découpage en tronçons "
        "ont été réécrits au lieu d'être réutilisés (contrat §2)"
    )


def test_les_detecteurs_du_sprint_4_fonctionnent(tmp_path):
    """Un test négatif ne prouve rien sans la preuve que le détecteur détecte."""
    faux = tmp_path / "faux.py"
    faux.write_text(
        "import pathlib\n"
        "from datetime import date\n"
        "def lire(c):\n"
        "    with open(c) as f:\n"
        "        return f.read(), date.today()\n",
        encoding="utf-8",
    )
    fautes = _fautes_de_disque(faux)
    assert any("pathlib" in f for f in fautes), f"import pathlib non repéré : {fautes}"
    assert any("open" in f for f in fautes), f"open() non repéré : {fautes}"
    appels = {appel for _, appel in _appels(faux)}
    assert "date.today" in appels and "today" in appels, f"date.today() non repéré : {appels}"
    propre = tmp_path / "propre.py"
    propre.write_text("def placer(seance, trace, p):\n    return sum(e.duree_s for e in seance.etapes)\n",
                      encoding="utf-8")
    assert not _fautes_de_disque(propre), "faux positif sur un module qui ne touche à rien"

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
from pathlib import Path

import httpx
import outils
import pytest
from conftest import RACINE, ReseauInterdit

from ourouler import cli, erreurs
from ourouler import config as module_config

SRC = RACINE / "src" / "ourouler"
TESTS = RACINE / "tests"

#: Seuls modules autorisés à connaître la machine hôte (CLAUDE.md règle 2).
FICHIERS_AUTORISES = {"cli.py", "config.py"}

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
        autorise = chemin.name in FICHIERS_AUTORISES
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
    """`.gitignore` ne réintègre que `tests/fixtures/**` : ailleurs, rien de binaire.

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


def _fichiers_a_scanner() -> list[Path]:
    """`src/` et `tests/` seulement.

    `docs/` cite volontairement les capteurs et les identifiants du mainteneur :
    c'est là que le contrat dit au code quoi chercher. `config.example.toml`
    n'est pas scanné non plus — c'est de la documentation d'usage — mais s'il
    porte une vraie valeur, elle mérite d'être signalée au mainteneur.
    """
    return _fichiers_texte(SRC) + _fichiers_texte(TESTS)


def test_le_detecteur_de_donnees_personnelles_fonctionne():
    """Un test négatif ne prouve rien sans la preuve que le détecteur détecte."""
    marque, numero = CAPTEURS_INVERSES[0][0][::-1], CAPTEURS_INVERSES[0][1][::-1]
    assert _occurrences(f'capteur_puissance = "{marque} {numero}"'), "le capteur doit être repéré"
    assert _occurrences(f"gear id b{GEAR_INVERSES[0][::-1]}"), "l'identifiant doit être repéré"
    assert _occurrences(f"url = 'https://brouter.{DOMAINE_PRIVE}'"), "le domaine doit être repéré"
    assert not _occurrences('capteur_puissance = "CAPTEUR ALPHA 1234"'), "faux positif sur un nom inventé"
    assert not _occurrences("gear_id = 'g-beta'"), "faux positif sur un identifiant inventé"


def test_aucune_donnee_personnelle_du_mainteneur_dans_src_et_tests():
    """Règle absolue 1 : capteurs, identifiants d'équipement et URL privée restent dans docs/."""
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

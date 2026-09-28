"""Outils de découverte de l'API, partagés par les tests de `tests/api/`.

Chargé par nom de module (`import outils_api`) et non depuis `conftest` :
trois `conftest.py` coexistent sous `tests/`, les importer par leur nom est
ambigu. `conftest.py` de ce dossier rend ce module importable.
Le détail du parti pris (aveugle de l'implémentation, découverte par le
schéma OpenAPI, aucune erreur de collecte) est dans `conftest.py`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable, Iterable
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx

RACINE = Path(__file__).resolve().parents[2]
SOURCES = RACINE / "src" / "ourouler"
BASE_URL = "http://api.test"


class ApiAbsente(AssertionError):
    """L'API, une route ou une couture d'injection manque.

    Sous-classe d'`AssertionError` à dessein : levée dans le corps d'un test,
    elle produit un *échec* que `xfail` sait absorber, jamais une *erreur* de
    collecte ni une erreur de fixture.
    """


# --- sentinelles : rien de réel, et repérable à l'œil nu ---------------------

#: Ce qui doit **ne jamais** ressortir d'une réponse, d'un message ou d'un log.
CLE_INTERVALS_SENTINELLE = "SENTINELLE-CLE-INTERVALS-NE-DOIT-JAMAIS-SORTIR"
MDP_BROUTER_SENTINELLE = "SENTINELLE-MDP-BROUTER-NE-DOIT-JAMAIS-SORTIR"
SENTINELLES = (CLE_INTERVALS_SENTINELLE, MDP_BROUTER_SENTINELLE)

#: Départ synthétique. En mer : le détecteur de coordonnées de
#: `tests/adversarial/test_adv_invariants.py` refuse tout ce qui approche une
#: ville française à moins de 50 km, et il a raison.
DEPART_SYNTHETIQUE = {"nom": "Départ d'essai", "latitude": 0.0009, "longitude": 0.0004}

#: Identité inventée, reprise des maquettes (domaine `exemple.fr`).
PROPRIETAIRE_A = "essai-proprietaire-a"
PROPRIETAIRE_B = "essai-proprietaire-b"
COURRIEL_A = "camille.ruiz@exemple.fr"


# --- localisation de l'application ------------------------------------------

#: Modules où l'application peut raisonnablement vivre. La liste est large
#: exprès : le testeur ne doit pas imposer un nom à l'implémenteur.
MODULES_CANDIDATS = (
    "ourouler.api",
    "ourouler.api.application",
    "ourouler.api.app",
    "ourouler.api.serveur",
    "ourouler.api.web",
    "ourouler.serveur",
    "ourouler.web",
)

#: Noms possibles d'une **fabrique** — le point d'injection attendu.
FABRIQUES_CANDIDATES = (
    "creer_application",
    "creer_app",
    "construire_application",
    "fabriquer_application",
    "application_pour",
    "create_app",
)

#: Noms possibles d'une application déjà construite (repli, moins bon : une
#: application globale ne se teste pas sans réseau, voir `test_api_socle.py`).
APPLICATIONS_CANDIDATES = ("application", "app", "api")


def _modules_disponibles() -> list[Any]:
    modules = []
    for nom in MODULES_CANDIDATS:
        try:
            modules.append(import_module(nom))
        except Exception:  # noqa: BLE001 — un module absent n'est pas une erreur ici
            continue
    return modules


def charger_fabrique() -> Callable[..., Any]:
    """Renvoie la fabrique d'application, ou lève `ApiAbsente`.

    La fabrique est le seul point par lequel un test peut injecter une `Config`
    et des clients HTTP bouchonnés. Sans elle, il n'y a pas de test sans
    réseau — donc pas de test du tout (règle absolue 3).
    """
    for module in _modules_disponibles():
        for nom in FABRIQUES_CANDIDATES:
            objet = getattr(module, nom, None)
            if callable(objet):
                return objet
    raise ApiAbsente(
        "aucune fabrique d'application trouvée. Cherché "
        f"{'|'.join(FABRIQUES_CANDIDATES)} dans {', '.join(MODULES_CANDIDATS)}. "
        "L'API doit exposer une fabrique qui accepte une Config et des clients HTTP "
        "injectables, sinon aucun test ne peut tourner sans réseau."
    )


def charger_application(**options: Any) -> Any:
    """Construit l'application ASGI, en n'injectant que ce que la fabrique accepte.

    Les noms d'arguments d'injection ne sont pas connus d'avance : on lit la
    signature et on passe l'intersection. Ce que la fabrique refuse est
    remonté par `options_refusees()`, que les tests d'injection exploitent.
    """
    try:
        fabrique = charger_fabrique()
    except ApiAbsente:
        for module in _modules_disponibles():
            for nom in APPLICATIONS_CANDIDATES:
                objet = getattr(module, nom, None)
                if objet is not None and callable(objet):
                    return objet
        raise
    retenues, _ = _trier_options(fabrique, options)
    return fabrique(**retenues)


def _trier_options(fabrique: Callable[..., Any], options: dict[str, Any]) -> tuple[dict, dict]:
    try:
        signature = inspect.signature(fabrique)
    except (TypeError, ValueError):
        return {}, dict(options)
    accepte_tout = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())
    if accepte_tout:
        return dict(options), {}
    connus = set(signature.parameters)
    retenues = {nom: valeur for nom, valeur in options.items() if nom in connus}
    refusees = {nom: valeur for nom, valeur in options.items() if nom not in connus}
    return retenues, refusees


def options_refusees(**options: Any) -> dict[str, Any]:
    """Les options d'injection que la fabrique **n'accepte pas**. Vide = bon signe."""
    _, refusees = _trier_options(charger_fabrique(), options)
    return refusees


# --- client ASGI minimal, sans dépendance de test nouvelle -------------------


class ClientApi:
    """Client synchrone au-dessus d'une application ASGI, via `httpx.ASGITransport`.

    Volontairement sans `fastapi.testclient` : le socle de test ne doit pas
    imposer le cadre web, et `httpx` est déjà une dépendance du projet.
    `raise_app_exceptions=False` pour qu'une exception non rattrapée devienne
    un **500 observable** au lieu de remonter dans le test — c'est précisément
    ce que les tests d'état d'échec veulent voir.
    """

    def __init__(self, application: Any) -> None:
        self.application = application

    def requete(self, methode: str, url: str, **kwargs: Any) -> httpx.Response:
        async def aller() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.application, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
                return await client.request(methode, url, **kwargs)

        try:
            return asyncio.run(aller())
        except TypeError as erreur:  # application WSGI ou objet non appelable en ASGI
            raise ApiAbsente(
                f"l'objet chargé n'est pas une application ASGI appelable : {erreur}. "
                "`front_contrat.md` retient FastAPI ; le socle de test attend une ASGI."
            ) from erreur

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.requete("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.requete("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.requete("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.requete("DELETE", url, **kwargs)


def client_api(**options: Any) -> ClientApi:
    """Le client de test. À appeler **dans le corps** d'un test, jamais en fixture."""
    return ClientApi(charger_application(**options))


# --- découverte du contrat par le schéma OpenAPI ----------------------------

CHEMINS_SCHEMA = ("/openapi.json", "/api/openapi.json", "/schema.json", "/openapi")


def schema_openapi(client: ClientApi) -> dict[str, Any]:
    """Le schéma publié par l'application. Sans lui, un front ne peut rien câbler."""
    methode = getattr(client.application, "openapi", None)
    if callable(methode):
        try:
            schema = methode()
            if isinstance(schema, dict) and schema.get("paths"):
                return schema
        except Exception:  # noqa: BLE001 — on tente ensuite par HTTP
            pass
    for chemin in CHEMINS_SCHEMA:
        reponse = client.get(chemin)
        if reponse.status_code == 200:
            try:
                schema = reponse.json()
            except ValueError:
                continue
            if isinstance(schema, dict) and schema.get("paths"):
                return schema
    raise ApiAbsente(
        "aucun schéma OpenAPI publié. Cherché " + ", ".join(CHEMINS_SCHEMA) + ". "
        "Le schéma est le contrat que le front consomme : sans lui, F2 code à l'aveugle."
    )


def routes(schema: dict[str, Any]) -> list[tuple[str, str, dict]]:
    """[(chemin, méthode en majuscules, description de l'opération)]."""
    trouvees = []
    for chemin, operations in (schema.get("paths") or {}).items():
        if not isinstance(operations, dict):
            continue
        for methode, operation in operations.items():
            if methode.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                trouvees.append((chemin, methode.upper(), operation or {}))
    return trouvees


def route_pour(schema: dict[str, Any], *motifs: str) -> tuple[str, str, dict]:
    """La première route dont le **chemin** porte l'un des motifs.

    On cherche dans le chemin et non dans la description : une route s'appelle
    par son URL, et c'est cette URL que le front écrira.
    """
    for motif in motifs:
        for chemin, methode, operation in routes(schema):
            if motif.lower() in chemin.lower():
                return chemin, methode, operation
    connues = sorted({chemin for chemin, _, _ in routes(schema)})
    raise ApiAbsente(
        f"aucune route ne porte {' ni '.join(motifs)}. Routes déclarées : {connues or '(aucune)'}"
    )


def noms_de_parametres(schema: dict[str, Any], operation: dict[str, Any]) -> set[str]:
    """Paramètres de requête *et* propriétés du corps, à plat, sur un niveau."""
    noms: set[str] = set()
    for parametre in operation.get("parameters") or []:
        if isinstance(parametre, dict) and parametre.get("name"):
            noms.add(str(parametre["name"]))
    corps = (operation.get("requestBody") or {}).get("content") or {}
    for type_media in corps.values():
        noms |= _proprietes(schema, type_media.get("schema") or {})
    return noms


def _proprietes(schema: dict[str, Any], noeud: dict[str, Any], profondeur: int = 0) -> set[str]:
    if profondeur > 4 or not isinstance(noeud, dict):
        return set()
    if "$ref" in noeud:
        return _proprietes(schema, _resoudre(schema, str(noeud["$ref"])), profondeur + 1)
    noms = set(noeud.get("properties") or {})
    for cle in ("allOf", "anyOf", "oneOf"):
        for sous in noeud.get(cle) or []:
            noms |= _proprietes(schema, sous, profondeur + 1)
    return noms


def _resoudre(schema: dict[str, Any], reference: str) -> dict[str, Any]:
    noeud: Any = schema
    for morceau in reference.lstrip("#/").split("/"):
        if not isinstance(noeud, dict):
            return {}
        noeud = noeud.get(morceau, {})
    return noeud if isinstance(noeud, dict) else {}


def parametre_nomme(noms: Iterable[str], *motifs: str) -> str | None:
    """Le premier nom de paramètre qui contient l'un des motifs, sans accent ni casse."""
    for motif in motifs:
        for nom in sorted(noms):
            if motif.lower() in _sans_accent(nom).lower():
                return nom
    return None


_ACCENTS = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")


def _sans_accent(texte: str) -> str:
    return texte.translate(_ACCENTS)


# --- lecture d'une réponse ---------------------------------------------------

#: Ce qu'un message destiné à un humain ne doit jamais contenir.
TRACES_PYTHON = (
    "Traceback (most recent call last)",
    'File "',
    "line 1, in ",
    "ourouler/",
    "src\\ourouler",
    "KeyError",
    "AttributeError",
    "TypeError:",
    "ValueError:",
    "IndexError",
    "NoneType",
    "Internal Server Error",
)

#: Quelques mots qui n'existent qu'en français. Un message d'erreur qui n'en
#: porte aucun est très probablement resté en anglais.
#:
#: **Élargi le 17/09/2026, et pourquoi ce n'est pas un affaiblissement.** La
#: liste manquait des messages entièrement français : « fichier.zwo : fichier
#: vide », « fichier.zwo : ZWO illisible (…) », « … octets annoncés ». Aucun
#: de ces mots n'y figurait, et le test déclarait anglais un message qui ne
#: l'est pas — un faux négatif rend un test bruyant, puis on le désarme, et
#: c'est ainsi qu'on perd une garde qui servait. Les mots ajoutés n'existent
#: qu'en français ; le test refuse toujours un message qui n'en porte aucun.
MOTS_FRANCAIS = re.compile(
    r"\b(aucun|aucune|pas de|n'a|n'est|le|la|les|une|un|des|du|vous|votre|nous|"
    r"trop|manque|manquant|invalide|impossible|introuvable|doit|peut|sans|avec|pour|"
    r"trouvé|trouvée|indisponible|inconnue|inconnu|attendu|attendue|erreur|essai|"
    r"vide|illisible|lisible|fichier|séance|seance|octets|taille|refusé|refusée|"
    r"tronqué|tronquée|déposé|déposée|jour|heure|départ|adresse|valeur|champ)\b",
    re.IGNORECASE,
)


def corps_json(reponse: httpx.Response) -> Any:
    """Le corps JSON, ou un échec explicite. Un front ne sait lire que du JSON."""
    type_media = reponse.headers.get("content-type", "")
    if "json" not in type_media:
        raise AssertionError(
            f"réponse {reponse.status_code} non JSON (content-type={type_media!r}) : "
            f"{reponse.text[:300]!r}. Un front ne peut rien faire d'un corps texte."
        )
    return reponse.json()


def texte_entier(valeur: Any) -> str:
    """Aplati n'importe quelle réponse en texte, pour y chercher une fuite.

    On concatène les chaînes brutes au lieu de passer par `json.dumps` : le
    sérialiseur échappe les guillemets, et un `File "boucle.py"` de trace
    Python deviendrait `File \\"boucle.py\\"`, que la recherche manquerait.
    C'est exactement le genre de détail qui fait passer un test sans qu'il
    teste quoi que ce soit.
    """
    morceaux: list[str] = []

    def descendre(noeud: Any, profondeur: int = 0) -> None:
        if profondeur > 12:
            return
        if isinstance(noeud, str):
            morceaux.append(noeud)
        elif isinstance(noeud, dict):
            for cle, sous in noeud.items():
                morceaux.append(str(cle))
                descendre(sous, profondeur + 1)
        elif isinstance(noeud, (list, tuple, set)):
            for sous in noeud:
                descendre(sous, profondeur + 1)
        elif noeud is not None:
            morceaux.append(str(noeud))

    descendre(valeur)
    try:
        morceaux.append(json.dumps(valeur, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        morceaux.append(str(valeur))
    return "\n".join(morceaux)


def verifier_refus_exploitable(reponse: httpx.Response, quoi: str) -> dict[str, Any]:
    """Le contrat commun des quatre états d'échec dessinés dans les maquettes.

    Un refus exploitable par un front, c'est : un statut 4xx que le front sait
    distinguer, un corps JSON, un `code` stable qu'on peut brancher sur un
    écran, un `message` en français lisible par un cycliste, et **aucune**
    trace Python.

    **Corrigé le 17/09/2026 — le code se cherche où le contrat le range, pas
    où le testeur l'attendait.** Cette fonction exigeait `{"code", "message"}`
    à la racine du corps. `docs/journal/ux/api_contrat.md` range les pannes sous
    `{"erreur": {"code", "message", "service", "details"}}`, pour qu'une
    réponse porte `donnees` **ou** `erreur` et jamais les deux à la fois. Les
    deux formes portent le même contrat — un code stable et un message
    humain — et la nidification est celle que le front code déjà. Exiger la
    forme plate revenait à imposer un goût contre une décision documentée et
    livrée : `_panne` accepte donc les deux, et toutes les assertions qui
    suivent (statut, code présent, message français, aucune trace, aucun
    secret) sont conservées telles quelles.
    """
    assert 400 <= reponse.status_code < 500, (
        f"{quoi} : statut {reponse.status_code}. Un refus prévu par les maquettes est un 4xx "
        "exploitable, jamais un 500 nu ni un 200 qui ment."
    )
    brut = corps_json(reponse)
    assert isinstance(brut, dict), f"{quoi} : le corps d'erreur doit être un objet, pas {type(brut)}"
    corps = _panne(brut)
    assert corps.get("code"), (
        f"{quoi} : pas de champ `code`. Le front branche un écran sur un code stable, "
        f"jamais sur le texte d'un message. Reçu : {sorted(brut)}"
    )
    message = corps.get("message") or corps.get("detail") or ""
    assert isinstance(message, str) and message.strip(), f"{quoi} : pas de `message` lisible"
    assert MOTS_FRANCAIS.search(message), (
        f"{quoi} : le message ne paraît pas français — {message!r}. "
        "CLAUDE.md : français dans la doc et les messages."
    )
    # Sur le corps **entier** et non sur la seule panne : une trace ou un
    # secret glissé à côté de `erreur` fuirait tout autant.
    entier = texte_entier(brut)
    for trace in TRACES_PYTHON:
        assert trace not in entier, f"{quoi} : trace Python dans la réponse ({trace!r})"
    for sentinelle in SENTINELLES:
        assert sentinelle not in entier, f"{quoi} : un secret a fui dans le message d'erreur"
    return corps


def _panne(corps: dict[str, Any]) -> dict[str, Any]:
    """La panne, qu'elle soit à la racine du corps ou rangée sous `erreur`."""
    sous = corps.get("erreur")
    return sous if isinstance(sous, dict) else corps


def fichiers_python_de_l_api() -> list[Path]:
    """Les sources de l'API, quel que soit le dossier choisi. Vide = API absente."""
    candidats = [SOURCES / "api", SOURCES / "web", SOURCES / "serveur"]
    fichiers: list[Path] = []
    for dossier in candidats:
        if dossier.is_dir():
            fichiers += [p for p in dossier.rglob("*.py") if "__pycache__" not in p.parts]
    for nom in ("api.py", "web.py", "serveur.py"):
        if (SOURCES / nom).is_file():
            fichiers.append(SOURCES / nom)
    return sorted(set(fichiers))


# --- une Config d'essai, entièrement inventée --------------------------------

#: Départ en mer, secrets sentinelles, un seul vélo. Aucune valeur ne ressemble
#: à une donnée du mainteneur (règle absolue 1). `facteur_compteur` est laissé
#: absent exprès : c'est le cas « supposé » de la troisième valeur de E9.
CONFIG_ESSAI: dict[str, Any] = {
    "depart": dict(DEPART_SYNTHETIQUE),
    "cycliste": {"masse_kg": 70.0, "ftp_w": 200},
    "velos": [{"nom": "Essai", "usage": "route", "masse_kg": 9.0, "cda_m2": 0.3}],
    "intervals": {"athlete_id": "i000000", "api_key": CLE_INTERVALS_SENTINELLE},
    "brouter": {
        "url": "http://brouter.essai.invalid",
        "utilisateur": "essai",
        "mot_de_passe": MDP_BROUTER_SENTINELLE,
        "profil": "fastbike",
    },
    "boucle": {"vitesse_moyenne_kmh": 27, "candidates": 5},
}


def config_d_essai(**remplacements: Any) -> Any:
    """Une `Config` synthétique, construite sans toucher au disque.

    Passe par `ourouler.config.depuis_dict` — le point d'entrée que la CLI
    utilise déjà après `tomllib` — pour qu'aucun test n'ait besoin d'un TOML
    réel ni d'un `~/.config` (règle absolue 2).
    """
    module = import_module("ourouler.config")
    depuis_dict = getattr(module, "depuis_dict", None)
    if not callable(depuis_dict):
        raise ApiAbsente("ourouler.config.depuis_dict a disparu : la Config d'essai n'est plus constructible")
    brut = {cle: dict(valeur) if isinstance(valeur, dict) else valeur for cle, valeur in CONFIG_ESSAI.items()}
    for cle, valeur in remplacements.items():
        if isinstance(valeur, dict) and isinstance(brut.get(cle), dict):
            brut[cle].update(valeur)
        else:
            brut[cle] = valeur
    return depuis_dict(brut)


def attendre_tache_rendue(id_job: str, delai_max_s: float = 5.0) -> None:
    """Attend que la tâche de fond `id_job` ait **rendu la main**, pas seulement fini.

    Son `statut` passe à `fini` (ou `echoue`) avant que la tâche ait appelé
    son `au_echec` et son `enfin` puis relâché le verrou serveur
    (`api/taches_fond.lancer`). Un test qui relance une tâche dès qu'il lit
    « fini » tombe, sur une machine lente, dans cette fenêtre : 409
    `import_deja_en_cours`. `Job._termine` est posé après la libération du
    verrou. Importé ici et non en tête de module : rien de l'API à la
    collecte (voir `conftest.py`).
    """
    taches_fond = import_module("ourouler.api.taches_fond")
    with taches_fond._verrou_registre:
        job = taches_fond._jobs.get(id_job)
    assert job is not None, f"tâche {id_job} absente du registre"
    assert job._termine.wait(delai_max_s), f"tâche {id_job} finie mais pas rendue après {delai_max_s} s"


# --- transports bouchonnés ---------------------------------------------------


def transport_constant(statut: int, corps: Any = None, *, texte: str | None = None) -> httpx.MockTransport:
    """Un service externe qui répond toujours la même chose. Zéro socket ouverte."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        if texte is not None:
            return httpx.Response(statut, text=texte, request=requete)
        return httpx.Response(statut, json=corps if corps is not None else {}, request=requete)

    return httpx.MockTransport(repondre)


def client_bouchon(statut: int, corps: Any = None, *, texte: str | None = None) -> httpx.Client:
    """Un `httpx.Client` prêt à être injecté, sans jamais sortir de la machine."""
    return httpx.Client(transport=transport_constant(statut, corps, texte=texte))


def transports_du_depot() -> Any:
    """Le module de fixtures de `ourouler sortie`, chargé à l'exécution.

    **Le testeur est aveugle du code de l'API, pas des fixtures du dépôt.**
    Un BRouter qui rend une vraie boucle, c'est une géométrie d'anneau, des
    tronçons, des tags et un profil d'altitude ; la refabriquer ici en ferait
    une deuxième à tenir à jour, et un bouchon qui dérive rend les tests qui
    s'en servent muets sans prévenir. On emprunte donc celle de
    `tests/outils_sortie_commande.py`, qui est déjà la référence du dépôt.

    Import différé : ce module est chargé au niveau du module de test, et
    `tests/` n'est sur `sys.path` qu'une fois la collecte faite.
    """
    return import_module("outils_sortie_commande")


def client_brouter_ordinaire(reglages: dict[float, dict] | None = None) -> httpx.Client:
    """Un BRouter qui rend de vraies boucles, prêt à être injecté."""
    return transports_du_depot().client_brouter(reglages)


def client_meteo_ordinaire(**options: Any) -> httpx.Client:
    """Open-Meteo qui répond normalement, prêt à être injecté."""
    return transports_du_depot().client_meteo(**options)


def client_brouter_sans_boucle() -> httpx.Client:
    """Un BRouter qui **répond bien** mais ne rend aucune boucle : le cas de E18.

    Une ligne droite qui ne revient pas au départ. À ne pas confondre avec un
    BRouter en panne ou un corps vide : ceux-là sont des pannes de service
    (`brouter_indisponible`), et l'écran dessiné pour « aucune boucle » n'est
    pas celui de « BRouter ne répond plus ». C'est exactement la distinction
    que E18 protège.
    """
    module = transports_du_depot()
    droite = [(0.0 + 0.001 * i, 0.0, 40.0) for i in range(120)]

    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=module.reponse_anneau(droite), request=requete)

    return httpx.Client(transport=httpx.MockTransport(repondre))


def client_brouter_toujours_la_meme_boucle() -> httpx.Client:
    """Un BRouter qui rend **le même anneau quel que soit l'azimut** : le cas de E19.

    Toutes les candidates empruntent alors exactement les mêmes routes, et le
    cœur n'en retient qu'une — « soit elles empruntaient plus de 25 % des mêmes
    routes qu'une autre du groupe ». C'est le texte que E19 · dégradé affiche,
    et c'est de là qu'il vient.

    **Écrit le 17/09/2026**, quand Q43 a retiré l'exigence de se distinguer sur
    un axe mesuré. Le bouchon d'avant reproduisait E19 par cette exigence-là :
    des anneaux dans des directions différentes, qui ne se ressemblaient que
    sur leurs chiffres. Il ne le reproduit plus, et le test le disait
    lui-même — « le relire plutôt que le supprimer ». Le recouvrement de routes
    étant devenu le seul verrou, c'est par lui qu'il faut passer, et une seule
    boucle servie quatre fois est la façon la plus nette de le faire.
    """
    module = transports_du_depot()
    anneau = module.anneau(0.0)

    def repondre(requete: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=module.reponse_anneau(anneau), request=requete)

    return httpx.Client(transport=httpx.MockTransport(repondre))


def client_seance_ordinaire(*, ce_jour_la: bool = False) -> httpx.Client:
    """Intervals.icu qui rend une séance planifiée, prêt à être injecté.

    Par défaut la séance est rendue **quel que soit le jour demandé** : les
    tests de parcours veulent une séance à poser sur une boucle, pas un
    calendrier.

    `ce_jour_la=True` fait respecter la fenêtre demandée (`oldest`/`newest`),
    et c'est nécessaire dès qu'un test compare « un jour avec séance » à « un
    jour sans » : sinon les deux appels rendent la même chose et la
    comparaison passe sans rien vérifier.
    """
    module = transports_du_depot()
    charge = [module.W.evenement(module.W.groupes_watts(), nom="4x8 fabriquée")]
    jour = module.JOUR.isoformat()

    def repondre(requete: httpx.Request) -> httpx.Response:
        debut, fin = requete.url.params.get("oldest"), requete.url.params.get("newest")
        dedans = not ce_jour_la or debut is None or fin is None or debut <= jour <= fin
        return httpx.Response(200, json=charge if dedans else [], request=requete)

    return httpx.Client(transport=httpx.MockTransport(repondre))


#: Ce qu'une demande de parcours porte au minimum pour être *acceptée* — pas
#: pour réussir. Les tests qui cherchent un refus en donnent un champ fautif
#: en plus ; ceux qui cherchent un succès s'en tiennent là.
DEMANDE_PARCOURS_MINIMALE: dict[str, Any] = {"distance_km": 30, "direction": "N"}


def appeler_route(
    client: ClientApi,
    schema: dict[str, Any],
    chemin: str,
    methode: str,
    operation: dict[str, Any],
    champs: dict[str, Any],
) -> httpx.Response:
    """Appelle une route en mettant chaque champ **là où elle l'attend**.

    Une route qui déclare un corps de requête le reçoit en JSON ; une route
    qui ne déclare que des paramètres de requête les reçoit en query. C'est le
    schéma qui tranche, pas le testeur : poser des `params=` sur un `POST`
    qui attend un corps rend un 422 « body: Field required » — un refus, donc
    un test vert, mais qui n'a rien testé de ce qu'il croit protéger.

    Les champs que la route ne déclare pas sont envoyés quand même : plusieurs
    tests vérifient précisément qu'une valeur inconnue ou hors bornes est
    refusée.
    """
    if (operation.get("requestBody") or {}).get("content"):
        return client.requete(methode, chemin, json=champs)
    del schema
    return client.requete(methode, chemin, params=champs)


def cherche_profond(valeur: Any, *motifs: str, profondeur: int = 0) -> list[tuple[str, Any]]:
    """[(clé, valeur)] pour toute clé du JSON qui contient l'un des motifs.

    Le testeur ne connaît pas l'arborescence choisie par l'implémenteur : il
    exige qu'une information *existe quelque part*, pas qu'elle soit à un
    chemin précis. Un test qui impose le chemin impose un goût, pas un contrat.
    """
    trouves: list[tuple[str, Any]] = []
    if profondeur > 12:
        return trouves
    if isinstance(valeur, dict):
        for cle, sous in valeur.items():
            nom = _sans_accent(str(cle)).lower()
            if any(motif.lower() in nom for motif in motifs):
                trouves.append((str(cle), sous))
            trouves += cherche_profond(sous, *motifs, profondeur=profondeur + 1)
    elif isinstance(valeur, (list, tuple)):
        for sous in valeur:
            trouves += cherche_profond(sous, *motifs, profondeur=profondeur + 1)
    return trouves

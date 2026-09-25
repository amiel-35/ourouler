"""La fabrique de l'application, et ce qu'elle promet à toutes les routes.

Deux façons de la construire :

- `creer_application(...)` — tout est injecté, et **tout est facultatif** :
  une `Config` déjà construite (ou un fichier, ou rien), un dossier de
  données, les clients externes. C'est ce que font les tests, et c'est ce qui
  garantit qu'aucun d'eux ne touche le réseau ni le disque du mainteneur.
- `application()` — la fabrique de service, qui lit l'environnement par
  `exploitation.py` et n'injecte rien : chaque commande fabrique alors ses
  vrais clients, exactement comme depuis la ligne de commande.

  ```
  uv run uvicorn --factory ourouler.api.application:application
  ```

  ou, plus simplement, `uv run ourouler api`.

Les trois gestionnaires d'exception posés ici sont le contrat d'erreur : une
`ErreurApi` sort avec son code et son statut, une erreur de validation de
corps sort dans la **même** forme (et non celle de FastAPI), et tout le reste
sort en `erreur_interne` sans jamais laisser filer une trace Python.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as ExceptionHTTP

from ourouler import __version__
from ourouler.activites.import_archive import TAILLE_MAX_REQUETE
from ourouler.api.adaptateur import Budgets
from ourouler.api.depots import (
    CHAMPS_RACINE_MODIFIABLES,
    SECTIONS_PERSO_PUR,
    VARIABLES_PERSO_PUR,
    DepotFichiers,
    DepotGenerations,
    DepotProfils,
    JournalServices,
    SocleFixe,
    SocleTOML,
    SocleVide,
)
from ourouler.api.erreurs import ErreurApi, table_des_avertissements, table_des_codes
from ourouler.api.garde_avant_corps import GardeAvantCorps
from ourouler.api.limite_corps import LimiteTailleCorps
from ourouler.api.quotas import (
    CALIBRATIONS_PAR_JOUR_DEFAUT,
    CONSULTATIONS_METEO_PAR_JOUR_DEFAUT,
    IMPORTS_PAR_JOUR_DEFAUT,
    Quotas,
)
from ourouler.api.routes import (
    TAILLE_MAX_PARCOURS,
    TAILLE_MAX_SEANCE,
    Clients,
    Contexte,
    reponse_erreur,
    routeur,
)
from ourouler.api.session import FournisseurSession, SessionPersonnelle
from ourouler.config import PREFIXE_ENV, Config, dossier_cache_depuis
from ourouler.erreurs import ErreurConfig

#: Le sous-dossier du cache où l'API range ce qui appartient aux propriétaires.
NOM_DOSSIER_DONNEES = "api"

#: Les deux routes dont le corps peut être gros, et leur plafond —
#: `LimiteTailleCorps` (relecture du 25/09/2026, suite) refuse **avant**
#: que Starlette n'écrive quoi que ce soit sur disque, même si `Content-Length`
#: ment ou manque (`Transfer-Encoding: chunked`).
BORNES_CORPS = {
    "/api/v1/activites/import": TAILLE_MAX_REQUETE,
    "/api/v1/seances/fichier": TAILLE_MAX_SEANCE,
    # L9.8 : sans cette ligne, un envoi en `chunked` (ou au `Content-Length`
    # menteur) passait la garde de la route et s'écrivait en entier sur disque
    # puis en mémoire avant d'être compté (relecture du 25/09/2026).
    "/api/v1/parcours/fichier": TAILLE_MAX_PARCOURS,
}


class _StaticFilesAvecCache(StaticFiles):
    """Sert le front avec un `Cache-Control` adapté au contenu (correctif 0.9.6).

    Panne constatée en prod : `StaticFiles` sert `index.html` sans aucun
    `Cache-Control`, et le navigateur d'un utilisateur le garde en cache à sa
    façon. Après un redéploiement, cet `index.html` périmé réclame un
    `/assets/index-<ancienne empreinte>.js` que `vite` a fait disparaître au
    profit d'un nouveau nom — 404, front blanc. `index.html` doit donc
    toujours être revalidé (`no-cache`), alors que les fichiers sous
    `/assets/` portent l'empreinte de leur contenu dans leur nom (Vite) : un
    nom donné ne change jamais de contenu, la mise en cache la plus longue
    possible (`immutable`) est donc sûre.
    """

    def file_response(
        self,
        full_path: str | Path,
        stat_result,
        scope: Mapping,
        status_code: int = 200,
    ) -> Response:
        reponse = super().file_response(full_path, stat_result, scope, status_code=status_code)
        if scope["path"].startswith("/assets/"):
            reponse.headers["cache-control"] = "public, max-age=31536000, immutable"
        elif Path(full_path).name == "index.html":
            reponse.headers["cache-control"] = "no-cache"
        return reponse


#: Ce qu'un 404 **ne doit jamais** faire retomber sur `index.html` (lot
#: L7.2-D) : toute route de l'API, la sonde de santé, et les deux chemins du
#: schéma publié. Large exprès sur `/api/` plutôt que le seul `/api/v1/` du
#: routeur actuel — un `/api/v2` futur doit rester du JSON sans qu'on ait à y
#: repenser.
#:
#: `"/api"` y figure **en plus** de `"/api/"`, et ce n'est pas un doublon :
#: `"/api".startswith("/api/")` est faux, donc le chemin `/api` tout court
#: passait la garde et rendait `index.html` en 200. Une base d'URL mal
#: construite ou une sonde générique recevait du HTML là où elle attendait une
#: erreur (relecture du 19/09/2026).
PREFIXES_HORS_FRONT = ("/api", "/sante", "/openapi.json", "/docs", "/redoc")


def _reponse_erreur_utf8(erreur: ErreurApi) -> JSONResponse:
    """`reponse_erreur`, avec un `Content-Type` qui annonce `charset=utf-8`.

    `starlette.responses.JSONResponse` n'ajoute `charset` qu'aux réponses
    `text/*` (`Response.init_headers`) : une réponse `application/json` sort
    donc sans charset annoncé. Un navigateur qui ne le devine pas correctement
    (constaté sous Safari) affiche un accent mal décodé (« — » devient
    « â€” ») au lieu de retomber sur l'UTF-8 réel du corps.
    """
    reponse = reponse_erreur(erreur)
    reponse.headers["content-type"] = "application/json; charset=utf-8"
    return reponse


#: La description publiée par `/openapi.json` et par `/docs`.
#:
#: Elle porte **le catalogue des pannes en toutes lettres** : un front ne peut
#: pas dessiner un état qu'il ne sait pas reconnaître, et deux des quatre
#: écrans d'échec des maquettes (« pas de météo ce matin », « intervals.icu ne
#: nous répond plus ») n'étaient nommés nulle part dans le contrat publié.
DESCRIPTION = f"""
L'API d'ourouler. Elle expose ce que la ligne de commande rend déjà en JSON
(doctrine §10.2) ; le front la consomme, et ne parle jamais au cœur.

Les routes qui calculent rendent `{{donnees, avertissements, duree_ms,
budget}}` ; les pannes rendent `{{erreur: {{code, message, service, details}}}}`.
Le contrat complet est dans `docs/ux/api_contrat.md`.

## Les états d'échec, et le code qui les nomme

Le **code** est la valeur du contrat : c'est lui qu'un écran teste, jamais le
texte du message, qui vient du cœur et peut être reformulé.

{table_des_codes()}

Deux cas qui n'en sont pas, et qui valent 200 : « aucune séance ce jour-là »
(`donnees.seance` vaut `null`) et « une seule proposition au lieu de trois »
(`donnees.motif_deux_propositions` porte l'explication).

## Les avertissements, et le code qui les nomme aussi

Un avertissement n'est pas une panne : la réponse vaut 200, le parcours est
servi, mais une affirmation manque. Chaque entrée de `avertissements` vaut
`{{code, message}}` — **le code se teste, le message s'affiche**. Un
avertissement que ce catalogue ne nomme pas encore porte le code `autre` :
il se montre, il ne se lit pas.

{table_des_avertissements()}
"""


def _ressemble_a_un_fichier(chemin: str) -> bool:
    """Ce chemin demande-t-il un **fichier**, plutôt qu'une page du front ?

    Une extension dans le dernier segment (`/assets/index-a1b2c3.js`) : c'est
    un fichier. Pas d'extension (`/entrer`, `/connexion`, `/reglages`) : c'est
    une page, que le front dessine lui-même une fois `index.html` chargé.

    Sans cette distinction, un fichier absent recevait `index.html` en 200
    (relecture du 19/09/2026). Le cas n'est pas théorique : après un
    déploiement, `vite` change les empreintes des fichiers, et un onglet resté
    ouvert sur l'ancien `index.html` redemande un `assets/index-<ancienne
    empreinte>.js` qui n'existe plus. Il recevait alors du HTML étiqueté
    JavaScript — une erreur de syntaxe muette dans la console, au lieu d'un
    404 que le navigateur sait nommer.
    """
    return "." in chemin.rsplit("/", 1)[-1]


def creer_application(
    *,
    config: Config | None = None,
    chemin_config: Path | None = None,
    socle: SocleTOML | SocleVide | SocleFixe | None = None,
    dossier_donnees: Path | None = None,
    client_brouter: object | None = None,
    client_meteo: object | None = None,
    client_intervals: object | None = None,
    client_ban: object | None = None,
    client_nominatim: object | None = None,
    client_geocodage: object | None = None,
    client_archive: object | None = None,
    clients: Clients | None = None,
    budgets: Budgets | None = None,
    quotas: Quotas | None = None,
    quotas_meteo: Quotas | None = None,
    quotas_calibration: Quotas | None = None,
    quotas_import: Quotas | None = None,
    session: FournisseurSession | None = None,
    dossier_front: Path | None = None,
) -> FastAPI:
    """L'application, avec ses dépôts et ses clients — rien n'est lu de l'environnement ici.

    **Tout est facultatif, et c'est le point.** `creer_application()` sans
    argument construit une application complète, qui publie son contrat et
    n'ouvre ni fichier ni socket. C'est ce que la règle absolue 3 exige : un
    test qui devrait d'abord écrire un TOML pour obtenir une application
    n'est pas un test sans disque, et un test qui devrait lancer le serveur
    pour lire le schéma n'est pas un test sans réseau.

    D'où vient le profil, par ordre de précision décroissante : `socle` (le
    dépôt lui-même, ce que fait le service), `config` (une `Config` déjà
    construite, ce que font les tests), `chemin_config` (un fichier TOML), ou
    rien — auquel cas le profil est vide et se remplit par `PATCH /profil`.

    Les clients externes s'injectent un par un (`client_meteo=…`) ou en bloc
    (`clients=Clients(…)`). Un client laissé à `None` est fabriqué par la
    commande du cœur au moment de l'appel, exactement comme en ligne de
    commande — ce qui veut dire qu'il sortira sur le réseau : un test qui
    touche une route de service injecte le sien.

    **Ce qu'on injecte, pour les cinq services, est un `httpx.Client`** — un
    transport, bouchonné dans un test — que la route habille du connecteur qui
    va avec, avec l'URL et les identifiants du profil du propriétaire. Un
    connecteur déjà construit est accepté aussi, et pris tel quel. La règle et
    ses raisons sont sur `routes.FABRIQUES_CONNECTEUR` ; il n'y a **pas** de
    service qui s'injecte autrement que les autres.

    **`session` dit comment l'application sait qui parle** (`api/session.py`).
    Le défaut est `SessionPersonnelle()` : cette fabrique-ci sert **un**
    cycliste — c'est ce que font `ourouler api` et tous les tests, qui
    construisent une application entière pour un seul profil. Ce n'est pas le
    « défaut implicite d'un service exposé » que le lot L7.A supprime : un
    service, lui, passe par `application()`, qui lit `OUROULER_MODE` et
    **refuse** en son absence. La distinction est la seule qui compte, et
    elle est là — le défaut d'une fabrique qu'on appelle en nommant ses
    arguments n'est pas le défaut d'un processus qu'on expose.

    **`dossier_front` sert le front construit (`npm run build`) depuis la
    même origine que l'API** (lot L7.E). Facultatif : sans lui, l'application
    ne sert que `/api/v1` — c'est ce que font tous les tests, et ce que fait
    `ourouler api` avant que quelqu'un ait construit `front/dist`. Donné, il
    monte ce dossier à la racine (`/`), **après** les routes de l'API : un
    gabarit `/api/v1/...` reste prioritaire sur le mieux qu'un fichier statique
    pourrait rendre. C'est pour ça que le front n'a jamais d'URL absolue dans
    son code (`front/README.md`) — la même origine sert les deux, en
    développement par le proxy Vite, en production par ce montage.

    **`quotas` et `quotas_meteo` portent les deux plafonds journaliers par
    compte** (L9.3, `api/quotas.py`) : générations (`POST /sorties`,
    `POST /boucles`) pour l'un, consultations météo (`GET /meteo`) pour
    l'autre — deux postes de coût différents, deux compteurs. Sans eux,
    `Quotas()` avec son défaut pour chacun — ce que font tous les tests qui
    n'exercent pas le quota. Sans objet en mode personnel : voir
    `routes._verifier_quota`. `quotas_calibration` (L9.4) est le troisième
    compteur, une calibration par jour et par compte par défaut
    (`quotas.CALIBRATIONS_PAR_JOUR_DEFAUT`).

    **`client_archive`** (L9.4) : l'archive météo Open-Meteo que la
    calibration interroge, un jour de sortie à la fois — un `httpx.Client`
    bouchonné, ou un client déjà construit, comme les cinq autres.
    """
    donnes = [nom for nom, v in (("socle", socle), ("config", config),
                                 ("chemin_config", chemin_config)) if v is not None]
    if len(donnes) > 1:
        raise ValueError(
            f"creer_application : {' et '.join(donnes)} donnés ensemble — le profil vient "
            "d'une source et d'une seule"
        )
    if socle is None:
        if config is not None:
            socle = SocleFixe(config)
        elif chemin_config is not None:
            socle = SocleTOML(chemin_config)
        else:
            socle = SocleVide()
    if dossier_donnees is None:
        # Une application construite sans dossier garde quand même ses
        # fichiers quelque part : un dossier temporaire, qui disparaît avec la
        # machine et n'a rien à voir avec le cache du mainteneur.
        dossier_donnees = Path(tempfile.mkdtemp(prefix="ourouler-api-"))
    app = FastAPI(
        title="ourouler",
        version=__version__,
        description=DESCRIPTION,
    )
    app.state.ourouler = Contexte(
        profils=DepotProfils(socle, dossier_donnees),
        fichiers=DepotFichiers(dossier_donnees),
        # Aucun dossier : les GPX des propositions ne touchent pas le disque
        # (Q40 g). Ils vivent dans ce processus, bornés, jusqu'au choix.
        generations=DepotGenerations(),
        journal=JournalServices(dossier_donnees),
        # Un réglage serveur (Q35), pas un profil : `socle.dossier_cache()`
        # ne demande la surcharge de personne (`api/depots.py`), à la
        # différence de `socle.config(...)` — voir `Contexte.dossier_cache`.
        dossier_cache=socle.dossier_cache(),
        clients=clients
        or Clients(
            brouter=client_brouter,
            meteo=client_meteo,
            intervals=client_intervals,
            # Le géocodage est **un** service pour qui appelle, deux connecteurs
            # ici : la BAN, et Nominatim en recours. `client_geocodage` sert les
            # deux d'un coup, pour qu'un appelant qui veut seulement couper le
            # réseau n'ait pas à connaître ce détail.
            ban=client_ban or client_geocodage,
            nominatim=client_nominatim or client_geocodage,
            archive=client_archive,
        ),
        budgets=budgets or Budgets(),
        quotas=quotas or Quotas(),
        quotas_meteo=quotas_meteo
        or Quotas(plafond=CONSULTATIONS_METEO_PAR_JOUR_DEFAUT, libelle="consultations météo"),
        quotas_calibration=quotas_calibration
        or Quotas(plafond=CALIBRATIONS_PAR_JOUR_DEFAUT, libelle="calibration(s)"),
        quotas_import=quotas_import
        or Quotas(plafond=IMPORTS_PAR_JOUR_DEFAUT, libelle="import(s) d'historique"),
        session=session or SessionPersonnelle(),
    )
    app.include_router(routeur)
    app.add_middleware(LimiteTailleCorps, bornes=BORNES_CORPS)
    # Ajouté après, donc **extérieur** : les refus qui se savent sans le
    # corps (session, verrou, quota) passent avant qu'on en compte un octet.
    app.add_middleware(GardeAvantCorps)

    @app.get("/sante", include_in_schema=False)
    def _sonde_sante() -> dict:
        """La sonde de santé (lot L7.E) : jamais de session, jamais de donnée.

        Hors `/api/v1` et hors du schéma publié, à dessein : toute route sous
        `/api/v1` sert par construction les données d'un cycliste
        (`tests/api/test_api_isolation_proprietaire.py`,
        `test_la_liste_des_routes_hors_donnees_ne_ment_pas`), et `/systeme`
        en est déjà une — elle répond 401 sans session, exactement comme il se
        doit. Un orchestrateur (Coolify, `docker compose --wait`, un
        `HEALTHCHECK`) qui interrogerait `/systeme` croirait le service mort
        sur un déploiement sans authentification branchée. Cette sonde ne
        prouve que ce qu'un orchestrateur a besoin de savoir : le processus
        répond. Elle ne dit rien du profil ni du mode — un `mode` ici serait
        déjà une information de configuration, hors du contrat que `/systeme`
        porte pour un cycliste authentifié.
        """
        return {"etat": "ok", "version": __version__}

    @app.exception_handler(ErreurApi)
    async def _erreur_api(requete: Request, erreur: ErreurApi) -> JSONResponse:
        del requete
        return _reponse_erreur_utf8(erreur)

    @app.exception_handler(RequestValidationError)
    async def _erreur_validation(requete: Request, erreur: RequestValidationError) -> JSONResponse:
        """Un corps mal formé sort dans la forme d'erreur du projet, pas dans celle de FastAPI.

        Le front n'a qu'une forme d'erreur à connaître ; `details.champs`
        garde ce que Pydantic a trouvé, pour que l'écran puisse pointer le
        champ fautif.

        **Le message reste en français.** Les motifs de Pydantic, eux, sont en
        anglais et le resteront : ils sont rangés dans `details`, où ils
        servent au débogage, et ne remontent pas dans la phrase qu'un écran
        afficherait. Traduire chaque motif de Pydantic serait une table à
        tenir à jour à chaque version ; nommer les champs fautifs suffit, et
        le front a de toute façon besoin de les pointer.
        """
        del requete
        champs = [
            {"champ": ".".join(str(p) for p in faute.get("loc", ())), "motif": faute.get("msg", "")}
            for faute in erreur.errors()
        ]
        noms = ", ".join(f"« {c['champ']} »" for c in champs) or "(champ non nommé)"
        return _reponse_erreur_utf8(
            ErreurApi(
                code="requete_invalide",
                message=f"requête mal formée : {noms} — valeur absente ou hors des bornes "
                "attendues (le détail par champ est dans « details »)",
                statut=422,
                details={"champs": champs},
            )
        )

    @app.exception_handler(ExceptionHTTP)
    async def _erreur_du_cadre(requete: Request, erreur: ExceptionHTTP) -> Response:
        """Les refus que le cadre web prononce lui-même sortent dans la forme du projet.

        Une route inconnue vaut `{"detail": "Not Found"}` chez FastAPI :
        anglais, sans code, et les maquettes n'ont pas d'écran « Not Found ».
        Le front n'a qu'une forme d'erreur à connaître, celle d'`api_contrat.md`,
        et il la reçoit ici aussi.

        **Le chemin demandé n'est pas répété dans le message** : il vient du
        client, et un front qui l'afficherait tel quel rendrait une chaîne
        choisie par qui a formé la requête.

        **Sauf pour un chemin du front** (lot L7.2-D, panne constatée en vrai
        le 19/09/2026 : `/entrer` rendait ce 404 JSON, et le lien
        d'invitation n'ouvrait jamais l'écran d'activation). `StaticFiles`
        lève ce même 404 pour tout chemin où elle ne trouve pas de fichier —
        c'est aussi ce qui arrive à `/entrer` ou `/connexion`, que le front
        gère lui-même une fois `index.html` chargé (`front/src/App.tsx`, pas
        de routeur : `window.location.pathname` lu au démarrage). La garde
        est étroite et nommée : seul un 404, seulement quand `dossier_front`
        est monté, et seulement pour un chemin qui **n'est pas** sous
        `/api/`, `/sante`, `/openapi.json`, `/docs` ou `/redoc` — sans quoi
        `/api/v1/inconnu` se mettrait, lui aussi, à rendre du HTML.
        """
        if (
            erreur.status_code == 404
            and dossier_front is not None
            and not requete.url.path.startswith(PREFIXES_HORS_FRONT)
            and not _ressemble_a_un_fichier(requete.url.path)
        ):
            return FileResponse(
                dossier_front / "index.html",
                media_type="text/html",
                headers={"Cache-Control": "no-cache"},
            )
        connus = {
            404: (
                "route_inconnue",
                "cette route n'existe pas sur ce serveur — la liste de celles qui sont "
                "servies est dans /openapi.json",
            ),
            405: (
                "methode_refusee",
                "cette route existe mais pas avec cette méthode — voir /openapi.json",
            ),
        }
        code, message = connus.get(
            erreur.status_code,
            ("requete_invalide", "la requête a été refusée par le serveur"),
        )
        return _reponse_erreur_utf8(
            ErreurApi(code=code, message=message, statut=erreur.status_code or 400)
        )

    @app.exception_handler(Exception)
    async def _erreur_inattendue(requete: Request, erreur: Exception) -> JSONResponse:
        """Un bug ne sort jamais en trace : il sort en une ligne, et reste au journal."""
        del requete, erreur
        return _reponse_erreur_utf8(
            ErreurApi(
                code="erreur_interne",
                message="erreur interne du serveur — le détail est dans le journal du serveur",
                statut=500,
            )
        )

    if dossier_front is not None:
        # **Monté en dernier.** Starlette essaie ses routes dans l'ordre
        # d'enregistrement et s'arrête à la première qui correspond : un
        # montage sur `/` enregistré avant `/api/v1/...` intercepterait tout,
        # `/sante` compris. Ici, il n'est atteint que pour ce qu'aucune route
        # ci-dessus n'a servi. `html=True` : `/` rend `index.html`, comme le
        # ferait un serveur de fichiers statiques ordinaire ; il n'y a pas de
        # Le repli des chemins du front (`/entrer`, `/connexion`) est dans
        # `_erreur_du_cadre` : `StaticFiles` ne sert que ce qu'elle trouve.
        app.mount("/", _StaticFilesAvecCache(directory=dossier_front, html=True), name="front")

    return app


def application() -> FastAPI:
    """La fabrique de service : configuration et dossier de données lus dans l'environnement.

    C'est **ici**, et nulle part ailleurs dans la fabrique, que le socle
    devient celui d'un fichier et hérite des variables de la machine — par
    `exploitation.py`, la seule porte du paquet (règle absolue 2). Le TOML du
    serveur est le profil du mainteneur : le socle le dit, et `DepotProfils`
    refuse de le servir à un autre propriétaire.

    **Et c'est ici que le produit se décide** : `OUROULER_MODE=personnel` sert
    un cycliste, tout le reste — y compris l'absence de variable — sert
    `SessionHebergee`, qui n'ouvre aucune session et fait répondre 401 à
    chaque route de données. Un processus exposé sans qu'on ait dit qui il
    sert ne sert personne ; c'est le sens du lot L7.A.

    **`dossier_front` vient de `OUROULER_FRONT_DIST`** (lot L7.E), absente par
    défaut : `ourouler api` sur la machine du mainteneur n'a pas construit
    `front/dist` et n'a pas à le faire pour servir l'API. C'est le paquetage
    (`deploiement/api/Dockerfile`) qui pose cette variable, vers le dossier où
    il a copié `npm run build`.
    """
    from ourouler.api import exploitation, imports_fond
    from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL
    from ourouler.api.session import MODE_PERSONNEL

    session = exploitation.fournisseur_session()
    # Les copies de dépôt qu'un import interrompu par l'arrêt du processus a
    # laissées (contre-lecture Fable du 25/09/2026) — au démarrage du service
    # seulement, jamais dans `creer_application`, que les tests appellent à
    # côté d'imports qui tournent encore.
    imports_fond.balayer_temporaires_orphelins(Path(tempfile.gettempdir()))

    # **À qui appartient le TOML de ce serveur**, et c'est le mode qui le dit.
    #
    # En personnel, c'est le profil du mainteneur : le socle le porte, et
    # `DepotProfils` refuse de le servir à un autre. En hébergé, il n'est le
    # profil de personne — c'est la **base commune** sur laquelle chacun pose
    # la sienne. Sans ça, un compte tout juste activé se heurtait à « le socle
    # de ce serveur est le profil de "local" et ne se partage pas » : il
    # entrait, et ne voyait rien (constaté en vrai le 19/09/2026, sur la
    # première activation).
    #
    # C'est la réponse à [[Q35]] (« trois tiers, et le vide n'existe pas »,
    # tranché le 17/09/2026) qui dit désormais quelles sections sont communes
    # et lesquelles appartiennent au cycliste — et `SocleTOML.config`
    # (`api/depots.py`) applique ce découpage à chaque construction de
    # `Config` : le tiers 3 (perso pur) n'est jamais hérité du socle commun.
    partage = session.mode != MODE_PERSONNEL
    chemin = exploitation.chemin_config()
    variables = exploitation.variables()
    socle = SocleTOML(chemin, variables=variables, proprietaire=None if partage else PROPRIETAIRE_LOCAL)

    if partage:
        # **Un socle hébergé sans surcharge est maintenant, à raison, un
        # profil incomplet** : depuis que `SocleTOML.config` retire les
        # sections perso pur (`depart`, `cycliste`), `socle.config({})`
        # n'a plus de raison de réussir à construire une `Config` — le
        # tiers 3 y manque toujours. Le dossier de cache, lui, ne dépend
        # d'aucune section perso pur (Q35 : `cache` est un réglage
        # serveur) ; il se lit donc dans le TOML brut, sans passer par une
        # `Config` complète.
        brut = exploitation.lire_toml(chemin)
        _refuser_une_base_partagee(brut, variables)
        dossier_cache = dossier_cache_depuis(brut)
    else:
        dossier_cache = socle.config({}).cache.dossier

    # **Cache météo mutualisé et quotas par compte (L9.3), en mode hébergé
    # seulement.** En personnel, un seul cycliste appelle depuis sa propre
    # adresse (doctrine §10.1) : ni l'un ni l'autre n'a d'objet, et
    # `client_meteo=None` laisse le cœur fabriquer son `ClientOpenMeteo`
    # ordinaire, exactement comme avant ce lot.
    client_meteo = None
    quotas = Quotas()
    quotas_meteo = Quotas(plafond=CONSULTATIONS_METEO_PAR_JOUR_DEFAUT, libelle="consultations météo")
    if partage:
        from ourouler.meteo.cache_previsions import ClientOpenMeteoCache
        from ourouler.meteo.openmeteo import ClientOpenMeteo

        client_meteo = ClientOpenMeteoCache(ClientOpenMeteo())
        quotas = Quotas(plafond=exploitation.generations_par_jour(variables))
        quotas_meteo = Quotas(
            plafond=exploitation.consultations_meteo_par_jour(variables),
            libelle="consultations météo",
        )

    return creer_application(
        socle=socle,
        dossier_donnees=dossier_cache / NOM_DOSSIER_DONNEES,
        session=session,
        dossier_front=exploitation.dossier_front(),
        client_meteo=client_meteo,
        quotas=quotas,
        quotas_meteo=quotas_meteo,
    )


def _refuser_une_base_partagee(brut: dict, variables: Mapping[str, str]) -> None:
    """Un serveur partagé ne démarre pas sur un TOML, ou des variables, perso pur.

    Le garde-fou qui accompagne la décision du dessus. Servir une base commune
    veut dire que **tout le monde** la reçoit : une clé Intervals ou un point
    de départ qui y traînent sont remis à chaque personne invitée, ce qu'aucun
    message d'erreur ne rattrape après coup — c'était la fuite mesurée en
    relecture le 21/09/2026, pour `depart`/`cycliste`/`velos`, alors que ce
    contrôle-ci n'existait que pour `[intervals]`.

    On refuse au démarrage plutôt qu'à la requête : un déploiement mal
    configuré doit échouer là où quelqu'un regarde, pas servir la moitié de
    ses routes. C'est le même choix que pour `OUROULER_MODE` inconnu.

    **Testé sur le TOML brut et les variables brutes, avant toute fusion** —
    et non sur une `Config` construite : `SocleTOML.config` retire déjà ces
    sections en mode hébergé (`api/depots.py`), donc une `Config` de base ne
    les montrerait plus jamais, qu'elles soient présentes ou non dans le
    fichier du serveur. Vérifier la source plutôt que le résultat est ce qui
    permet de nommer précisément ce qui est en trop.
    """
    depuis_toml = [section for section in SECTIONS_PERSO_PUR if brut.get(section)]
    # `historique_depuis` est un champ scalaire à la racine, pas une section
    # (`CHAMPS_RACINE_MODIFIABLES`) — perso pur lui aussi (Q35), oublié une
    # première fois dans `SocleTOML.config` (mesuré le 22/09/2026).
    depuis_racine = [champ for champ in CHAMPS_RACINE_MODIFIABLES if brut.get(champ)]
    depuis_env = [
        f"{PREFIXE_ENV}{suffixe}"
        for suffixe in VARIABLES_PERSO_PUR
        if variables.get(f"{PREFIXE_ENV}{suffixe}")
    ]
    if not depuis_toml and not depuis_racine and not depuis_env:
        return
    fautifs = []
    if depuis_toml or depuis_racine:
        noms = ", ".join(f"[[{s}]]" if s == "velos" else f"[{s}]" for s in depuis_toml)
        if depuis_racine:
            noms = ", ".join(filter(None, [noms, ", ".join(depuis_racine)]))
        fautifs.append(f"les sections ou champs {noms} dans son fichier de configuration")
    if depuis_env:
        fautifs.append(f"les variables {', '.join(depuis_env)}")
    raise ErreurConfig(
        "ce serveur est en mode hébergé et porte " + " et ".join(fautifs) + " — "
        "ce sont des réglages perso pur (Q35, tiers 3 : depart, cycliste, velos, intervals, "
        "historique_depuis), jamais hérités : ils seraient servis, ou imposés, à chaque "
        "personne invitée. Les retirer du fichier de configuration et de l'environnement du "
        "serveur — chaque cycliste renseigne les siens depuis l'assistant."
    )


__all__ = ["DESCRIPTION", "NOM_DOSSIER_DONNEES", "application", "creer_application"]

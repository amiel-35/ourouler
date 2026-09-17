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
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as ExceptionHTTP

from ourouler import __version__
from ourouler.api.adaptateur import Budgets
from ourouler.api.depots import (
    DepotFichiers,
    DepotGenerations,
    DepotProfils,
    JournalServices,
    SocleFixe,
    SocleTOML,
    SocleVide,
)
from ourouler.api.erreurs import ErreurApi, table_des_avertissements, table_des_codes
from ourouler.api.routes import Clients, Contexte, reponse_erreur, routeur
from ourouler.config import Config

#: Le sous-dossier du cache où l'API range ce qui appartient aux propriétaires.
NOM_DOSSIER_DONNEES = "api"

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
    clients: Clients | None = None,
    budgets: Budgets | None = None,
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
        ),
        budgets=budgets or Budgets(),
    )
    app.include_router(routeur)

    @app.exception_handler(ErreurApi)
    async def _erreur_api(requete: Request, erreur: ErreurApi) -> JSONResponse:
        del requete
        return reponse_erreur(erreur)

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
        return reponse_erreur(
            ErreurApi(
                code="requete_invalide",
                message=f"requête mal formée : {noms} — valeur absente ou hors des bornes "
                "attendues (le détail par champ est dans « details »)",
                statut=422,
                details={"champs": champs},
            )
        )

    @app.exception_handler(ExceptionHTTP)
    async def _erreur_du_cadre(requete: Request, erreur: ExceptionHTTP) -> JSONResponse:
        """Les refus que le cadre web prononce lui-même sortent dans la forme du projet.

        Une route inconnue vaut `{"detail": "Not Found"}` chez FastAPI :
        anglais, sans code, et les maquettes n'ont pas d'écran « Not Found ».
        Le front n'a qu'une forme d'erreur à connaître, celle d'`api_contrat.md`,
        et il la reçoit ici aussi.

        **Le chemin demandé n'est pas répété dans le message** : il vient du
        client, et un front qui l'afficherait tel quel rendrait une chaîne
        choisie par qui a formé la requête.
        """
        del requete
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
        return reponse_erreur(
            ErreurApi(code=code, message=message, statut=erreur.status_code or 400)
        )

    @app.exception_handler(Exception)
    async def _erreur_inattendue(requete: Request, erreur: Exception) -> JSONResponse:
        """Un bug ne sort jamais en trace : il sort en une ligne, et reste au journal."""
        del requete, erreur
        return reponse_erreur(
            ErreurApi(
                code="erreur_interne",
                message="erreur interne du serveur — le détail est dans le journal du serveur",
                statut=500,
            )
        )

    return app


def application() -> FastAPI:
    """La fabrique de service : configuration et dossier de données lus dans l'environnement.

    C'est **ici**, et nulle part ailleurs dans la fabrique, que le socle
    devient celui d'un fichier et hérite des variables de la machine — par
    `exploitation.py`, la seule porte du paquet (règle absolue 2). Le TOML du
    serveur est le profil du mainteneur : le socle le dit, et `DepotProfils`
    refuse de le servir à un autre propriétaire.
    """
    from ourouler.api import exploitation
    from ourouler.api.proprietaire import PROPRIETAIRE_LOCAL

    socle = SocleTOML(
        exploitation.chemin_config(),
        variables=exploitation.variables(),
        proprietaire=PROPRIETAIRE_LOCAL,
    )
    return creer_application(
        socle=socle,
        dossier_donnees=socle.config({}).cache.dossier / NOM_DOSSIER_DONNEES,
    )


__all__ = ["DESCRIPTION", "NOM_DOSSIER_DONNEES", "application", "creer_application"]

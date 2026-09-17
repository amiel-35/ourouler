"""La fabrique de l'application, et ce qu'elle promet à toutes les routes.

Deux façons de la construire :

- `creer_application(...)` — tout est injecté : le fichier de configuration,
  le dossier de données, les clients externes. C'est ce que font les tests,
  et c'est ce qui garantit qu'aucun d'eux ne touche le réseau.
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

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ourouler import __version__
from ourouler.api.adaptateur import Budgets
from ourouler.api.depots import DepotFichiers, DepotProfils
from ourouler.api.erreurs import ErreurApi
from ourouler.api.routes import Clients, Contexte, reponse_erreur, routeur

#: Le sous-dossier du cache où l'API range ce qui appartient aux propriétaires.
NOM_DOSSIER_DONNEES = "api"

DESCRIPTION = """
L'API d'ourouler. Elle expose ce que la ligne de commande rend déjà en JSON
(doctrine §10.2) ; le front la consomme, et ne parle jamais au cœur.

Les routes qui calculent rendent `{donnees, avertissements, duree_ms,
budget}` ; les pannes rendent `{erreur: {code, message, service, details}}`.
Le contrat complet est dans `docs/ux/api_contrat.md`.
"""


def creer_application(
    *,
    chemin_config: Path,
    dossier_donnees: Path,
    clients: Clients | None = None,
    budgets: Budgets | None = None,
) -> FastAPI:
    """L'application, avec ses dépôts et ses clients — rien n'est lu de l'environnement ici."""
    app = FastAPI(
        title="ourouler",
        version=__version__,
        description=DESCRIPTION,
    )
    app.state.ourouler = Contexte(
        profils=DepotProfils(chemin_config, dossier_donnees),
        fichiers=DepotFichiers(dossier_donnees),
        clients=clients or Clients(),
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
    """La fabrique de service : configuration et dossier de données lus dans l'environnement."""
    from ourouler.api import exploitation

    chemin = exploitation.chemin_config()
    config = exploitation.construire(exploitation.lire_toml(chemin))
    return creer_application(
        chemin_config=chemin,
        dossier_donnees=config.cache.dossier / NOM_DOSSIER_DONNEES,
    )


__all__ = ["DESCRIPTION", "NOM_DOSSIER_DONNEES", "application", "creer_application"]

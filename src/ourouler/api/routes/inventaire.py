"""L'inventaire des sorties et les routes apprises, en lecture seule."""

from __future__ import annotations

from datetime import date

from ourouler.api import calculs
from ourouler.api.double_chemin import calculer
from ourouler.api.erreurs import ErreurApi
from ourouler.api.reponses import ReponseCalcul, ReponseInventaire, reponse_de
from ourouler.api.routes.commun import Ctx, Qui, _base_routes, _cache, _config, _service, nouveau_routeur

routeur = nouveau_routeur()


# --- inventaire et routes connues ---------------------------------------------


@routeur.get("/inventaire", **reponse_de(ReponseInventaire))
def inventaire(
    ctx: Ctx,
    qui: Qui,
    depuis: date | None = None,
) -> dict:
    """L'inventaire des sorties par vélo et par mois, **sans synchroniser**.

    La synchronisation avec Intervals.icu et l'import d'un dossier restent des
    gestes de ligne de commande : ils écrivent dans le cache du serveur et
    durent des minutes.

    **Le cache est construit ici, avec le propriétaire de la session**
    (décision Q58, `docs/journal/questions/questions_mainteneur.md`). Recevoir
    `qui` ne suffit pas : si la commande construisait son `Cache` toute seule,
    avec le défaut
    `PROPRIETAIRE_LOCAL`, elle servirait l'inventaire du cycliste local à
    n'importe quel demandeur — et le balayage d'isolation la verrait pourtant
    conforme. C'est la couche web qui nomme le propriétaire, et elle seule
    (doctrine §10.1).
    """
    from ourouler.services import activites

    config = _config(ctx, qui)
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="inventaire",
        operation="inventaire",
        ancien=activites.executer,
        nouveau=calculs.inventaire,
        options={"depuis": depuis.isoformat() if depuis else None},
        clients={"cache": _cache(config, qui)},
        budgets=ctx.budgets,
    )
    return resultat.enveloppe(ctx.budgets.budget("inventaire"), qui)


@routeur.get("/routes/{action}", **reponse_de(ReponseCalcul))
def routes_connues(
    ctx: Ctx,
    qui: Qui,
    action: str,
) -> dict:
    """Ce que les sorties passées ont appris : `stats` ou `poids` (en lecture seule).

    **La base est construite ici, avec le propriétaire de la session** —
    même raison que `GET /inventaire`
    juste au-dessus.
    """
    from ourouler.services import apprentissage

    if action not in ("stats", "poids"):
        raise ErreurApi(
            code="requete_invalide",
            message=f"routes : action « {action} » inconnue — attendu stats ou poids "
            "(apprendre reste une commande d'administration)",
            statut=404,
        )
    config = _config(ctx, qui)
    resultat = calculer(
        ctx.chemin_api,
        config,
        route="routes",
        operation="routes",
        ancien=apprentissage.executer,
        nouveau=calculs.routes,
        options={"action": action, "appliquer": False},
        clients={
            "client_brouter": _service(ctx, config, "brouter"),
            "base": _base_routes(config, qui),
        },
        budgets=ctx.budgets,
    )
    return resultat.enveloppe(ctx.budgets.budget("routes"), qui)

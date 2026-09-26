"""`ourouler routes <action>` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.apprentissage.routes import BaseRoutes
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.rendu import routes as rendu
from ourouler.services import apprentissage as service
from ourouler.services.apprentissage import (
    DemandeRoutes,
    ResultatApprentissage,
    ResultatPoids,
    ResultatStats,
    date_depuis,
    valider_action,
)


def lire_options(args: argparse.Namespace) -> DemandeRoutes:
    return interpreter(
        getattr(args, "action", None),
        depuis=getattr(args, "depuis", None),
        max_sorties=getattr(args, "max_sorties", None),
        appliquer=bool(getattr(args, "appliquer", False)),
    )


def interpreter(
    action: str | None,
    *,
    depuis: str | None = None,
    max_sorties: int | None = None,
    appliquer: bool = False,
) -> DemandeRoutes:
    """L'action d'abord (sans elle, rien à faire), puis ses options."""
    action = valider_action(action)
    return DemandeRoutes(
        action=action,
        depuis=date_depuis(depuis) if action == "apprendre" else None,
        max_sorties=max_sorties,
        appliquer=appliquer,
    )


def json_routes(resultat: ResultatApprentissage | ResultatStats | ResultatPoids) -> dict:
    """Le JSON de `ourouler routes <action> --json`, selon ce que l'action a rendu."""
    if isinstance(resultat, ResultatApprentissage):
        return rendu.json_apprentissage(resultat.rapport, resultat.depuis)
    if isinstance(resultat, ResultatStats):
        return rendu.json_stats(resultat.stats, resultat.appris)
    sortie = rendu.json_poids(resultat.stats, resultat.exposition, resultat.poids, resultat.echecs)
    sortie["ecrit_dans"] = str(resultat.ecrit_dans) if resultat.ecrit_dans is not None else None
    return sortie


def executer_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    base: BaseRoutes | None = None,
) -> int:
    """Exécute `ourouler routes <action>`. Renvoie le code de sortie (0 = succès)."""
    resultat = service.executer(
        lire_options(args), contexte(config), client_brouter=client_brouter, base=base
    )
    if getattr(args, "json", False):
        imprimer_json(json_routes(resultat))
    elif isinstance(resultat, ResultatApprentissage):
        print(rendu.texte_apprentissage(resultat.rapport, resultat.depuis, resultat.stats))
    elif isinstance(resultat, ResultatStats):
        print(rendu.texte_stats(resultat.stats, resultat.appris))
    else:
        print(
            rendu.texte_poids(
                resultat.stats, resultat.exposition, resultat.poids, resultat.echecs, resultat.ecrit_dans
            )
        )
    return 0

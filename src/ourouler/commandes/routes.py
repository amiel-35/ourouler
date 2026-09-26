"""`ourouler routes <action>` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.apprentissage import commande as service
from ourouler.apprentissage.commande import (
    DemandeRoutes,
    ResultatApprentissage,
    ResultatStats,
    date_depuis,
    valider_action,
)
from ourouler.apprentissage.routes import BaseRoutes
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.rendu import routes as rendu


def lire_options(args: argparse.Namespace) -> DemandeRoutes:
    """L'action d'abord (sans elle, rien à faire), puis ses options."""
    action = valider_action(getattr(args, "action", None))
    return DemandeRoutes(
        action=action,
        depuis=date_depuis(getattr(args, "depuis", None)) if action == "apprendre" else None,
        max_sorties=getattr(args, "max_sorties", None),
        appliquer=bool(getattr(args, "appliquer", False)),
    )


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
    en_json = getattr(args, "json", False)
    if isinstance(resultat, ResultatApprentissage):
        if en_json:
            imprimer_json(rendu.json_apprentissage(resultat.rapport, resultat.depuis))
        else:
            print(rendu.texte_apprentissage(resultat.rapport, resultat.depuis, resultat.stats))
    elif isinstance(resultat, ResultatStats):
        if en_json:
            imprimer_json(rendu.json_stats(resultat.stats, resultat.appris))
        else:
            print(rendu.texte_stats(resultat.stats, resultat.appris))
    elif en_json:
        sortie = rendu.json_poids(resultat.stats, resultat.exposition, resultat.poids, resultat.echecs)
        sortie["ecrit_dans"] = str(resultat.ecrit_dans) if resultat.ecrit_dans is not None else None
        imprimer_json(sortie)
    else:
        print(
            rendu.texte_poids(
                resultat.stats, resultat.exposition, resultat.poids, resultat.echecs, resultat.ecrit_dans
            )
        )
    return 0

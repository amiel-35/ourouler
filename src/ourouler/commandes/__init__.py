"""Les commandes : d'un `argparse.Namespace` à une `Demande`, puis au rendu imprimé.

Couche 5 (entrées) de la règle d'imports (`ARCHITECTURE.md`). Pour
chaque sous-commande, un module de ce paquet :

1. lit les options (`argparse.Namespace`) et construit la `Demande` du
   service, déjà interprétée (dates, heures, distances, vélo…) ;
2. construit le `Contexte` depuis la `Config` (`commun.contexte`) : le
   profil, le dossier de cache et le fichier de calibration résolus ;
3. appelle le service (couche 3), qui rend un résultat sans rien imprimer ;
4. appelle le rendu (texte ou JSON selon `--json`) et l'imprime.

`cli/` appelle ces fonctions. L'API a deux chemins
(`api/double_chemin.py`) : l'ancien construit un `Namespace` et capture la
sortie standard (`api/adaptateur.py`) ; le nouveau (`api/calculs.py`)
appelle les pièces sans impression de ce paquet — `interpreter(...)` sur les
valeurs brutes, puis le service, puis les `json_*` — et le service
directement.
`executer_depuis_namespace` est ce point d'entrée de compatibilité : il
reçoit la fonction de service que `api/routes/` nomme, et appelle la
commande qui la sert.
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable

from ourouler.config import Config

#: Service (`module.nom`) → commande (`module:nom`, sous `ourouler.commandes`) qui le sert.
_COMMANDES: dict[str, str] = {
    "ourouler.services.activites.executer": "inventaire:executer_depuis_namespace",
    "ourouler.services.apprentissage.executer": "routes:executer_depuis_namespace",
    "ourouler.services.boucle.executer": "boucle:executer_depuis_namespace",
    "ourouler.services.geocodage.executer": "geocoder:executer_depuis_namespace",
    "ourouler.services.meteo.executer": "meteo:executer_depuis_namespace",
    "ourouler.services.physique.executer_calibrer": "physique:calibrer_depuis_namespace",
    "ourouler.services.physique.executer_simuler": "physique:simuler_depuis_namespace",
    "ourouler.services.physique.executer_analyser": "physique:analyser_depuis_namespace",
    "ourouler.services.comparer.executer": "comparer:executer_depuis_namespace",
    "ourouler.services.seance.executer": "seance:executer_depuis_namespace",
    "ourouler.services.sortie.executer": "sortie:executer_depuis_namespace",
    "ourouler.services.sortie.executer_vent": "sortie:vent_depuis_namespace",
}


def commande_de(service: Callable) -> Callable[..., int]:
    """La commande (`Namespace`, `Config`, clients…) qui sert ce service."""
    cle = f"{service.__module__}.{service.__name__}"
    if cle not in _COMMANDES:
        raise KeyError(f"aucune commande ne sert {cle}")
    module, nom = _COMMANDES[cle].split(":")
    return getattr(importlib.import_module(f"{__name__}.{module}"), nom)


def executer_depuis_namespace(service: Callable, args: argparse.Namespace, config: Config, **clients) -> int:
    """Compatibilité pour l'ancien chemin de l'API : la commande du service, avec son `Namespace`.

    Imprime exactement ce que la commande imprime ; l'API le capture. Il
    disparaîtra avec l'ancien chemin (`api/double_chemin.py`).
    """
    return commande_de(service)(args, config, **clients)

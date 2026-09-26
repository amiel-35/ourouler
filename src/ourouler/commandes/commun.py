"""Ce que toutes les commandes partagent : le contexte, la sortie d'erreur, le JSON.

`contexte(config)` est le seul endroit où la `Config` entière devient ce
qu'un service reçoit (`services.contexte.Contexte`) : le profil, le dossier de
cache et le fichier de calibration résolus, et un canal d'avertissements qui
écrit sur la sortie d'erreur **telle qu'elle est au moment de l'écriture**
— l'ancien chemin de l'API la redirige le temps d'un appel
(`api/adaptateur.py`), le nouveau passe son propre canal (`api/calculs.py`).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import replace

from ourouler.config import Config
from ourouler.noyau.profil import Depart
from ourouler.physique.commande import chemin_calibration
from ourouler.services.contexte import Contexte


def avertir(ligne: str) -> None:
    """Une ligne sur la sortie d'erreur, lue au moment de l'appel (pas à l'import)."""
    print(ligne, file=sys.stderr)


def contexte(
    config: Config,
    *,
    lieu_depart: Depart | None = None,
    avertir: Callable[[str], None] = avertir,
) -> Contexte:
    """Le contexte d'un service, depuis la `Config` chargée par l'entrée.

    `lieu_depart` est le point de départ de **cette** exécution, déjà tranché
    (`--adresse-depart` géocodée par `cli.depart.lieu_depart`, ou les coordonnées
    choisies sur la carte par l'API). Il remplace celui de la configuration
    dans le profil, qui est gelé : `replace` rend une copie, la configuration
    de l'appelant n'est pas touchée.

    `avertir` est la sortie d'erreur pour la ligne de commande ; l'API passe
    le sien, qui recueille les lignes pour `avertissements`.
    """
    if lieu_depart is not None:
        config = replace(config, depart=lieu_depart)
    return Contexte(
        profil=config,
        dossier_cache=config.cache.dossier,
        fichier_calibration=chemin_calibration(config),
        avertir=avertir,
    )


def imprimer_json(donnees: object) -> None:
    """Le JSON d'une commande, tel que toutes l'impriment depuis le début."""
    print(json.dumps(donnees, ensure_ascii=False, indent=2))

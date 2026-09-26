"""Ligne de commande `ourouler`.

Seule couche autorisée (avec `config.py`) à lire un fichier de configuration.
Chaque sous-commande est déclarée par une fonction `ajouter_<nom>` qui
importe son module paresseusement : une sous-commande absente ou cassée ne
doit pas empêcher les autres de tourner.

Le paquet se lit dans cet ordre :

- `parseur.py` : la construction de l'argparse et le couple
  `ajouter_<nom>` / `_commande_<nom>` de chaque sous-commande de calcul ;
- `options.py` : les options partagées par plusieurs sous-commandes
  (`--json` après la sous-commande, `--heure-depart`, `--adresse-depart`) ;
- `depart.py` : l'adresse de `--adresse-depart` devenue un `Depart` ;
- `comptes.py` : les commandes de l'exploitant (`inviter`, `invitations`,
  `reinitialiser`, `retirer`), qui assemblent la base PostgreSQL des comptes,
  le relais SMTP et l'URL publique ;
- ici, `main`, le point d'entrée (`ourouler = "ourouler.cli:main"`).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from ourouler.cli.comptes import (
    VARIABLE_SERVICE,
    VARIABLE_URL_PUBLIQUE,
    _charger_service,
    _url_publique,
    executer_invitations,
    executer_inviter,
)
from ourouler.cli.depart import ATTRIBUTION_NOMINATIM, lieu_depart
from ourouler.cli.parseur import construire_parseur
from ourouler.config import charger
from ourouler.noyau.erreurs import ErreurUtilisateur

__all__ = [
    "ATTRIBUTION_NOMINATIM",
    "VARIABLE_SERVICE",
    "VARIABLE_URL_PUBLIQUE",
    "_charger_service",
    "_url_publique",
    "construire_parseur",
    "executer_invitations",
    "executer_inviter",
    "lieu_depart",
    "main",
]


def main(argv: Sequence[str] | None = None) -> int:
    parseur = construire_parseur()
    args = parseur.parse_args(argv)
    if not getattr(args, "fonction", None):
        parseur.print_help()
        return 0
    try:
        # `chemin_config()` : même résolution que le serveur hébergé
        # (`OUROULER_CONFIG`, sinon le défaut local) — sans elle, un `ourouler
        # inviter` lancé dans le conteneur du serveur chercherait
        # `~/.config/ourouler/config.toml`, qui n'existe pas là-bas, alors que
        # `OUROULER_CONFIG=/config/config.toml` y est déjà posé pour le
        # processus API. `--config` explicite reste toujours prioritaire :
        # cette fonction n'est consultée que quand il est absent, exactement
        # comme `config.charger` consulte son propre défaut local.
        from ourouler.api.exploitation import chemin_config

        chemin = args.config or chemin_config()
        # Les commandes de comptes (`inviter`, `invitations`, `reinitialiser`,
        # `retirer`) ne parlent qu'à la base des comptes et, pour deux
        # d'entre elles, au relais SMTP — jamais au profil du cycliste
        # (`[depart]`, `[cycliste]`). Un TOML hébergé, sans sections
        # personnelles (décision Q35), ne porte pas ces deux sections : les
        # exiger ferait échouer ces commandes sur « section [depart]
        # manquante » avant même d'atteindre la base.
        requiert_profil = getattr(args, "requiert_profil", True)
        config = charger(chemin, requiert_profil=requiert_profil)
        return int(args.fonction(args, config))
    except ErreurUtilisateur as e:
        print(f"ourouler : {e}", file=sys.stderr)
        return 2

"""`ourouler admin` — l'administration du service hébergé, jamais exposée sur Internet.

Sprint 12. QP6 (25/09/2026, tranchée (c)) : cette sous-commande lance une
**seconde** application, distincte de l'API, qui n'écoute **que** sur
`127.0.0.1` — jamais `0.0.0.0`, jamais un port déclaré à Traefik/Coolify
(`--hote` n'existe même pas ici, à la différence de `ourouler api` : rien ne
doit pouvoir la faire écouter ailleurs que sur la boucle locale). On y entre
depuis l'extérieur par un tunnel SSH puis `docker exec`, ou par un port de
conteneur mappé sur la boucle locale de l'hôte — voir
`deploiement/api/README.md` pour la marche exacte.

Comme les commandes de comptes (`cli/comptes.py`), cette sous-commande a
besoin de ce que seul `cli/` a le droit de lire (le cœur ne lit ni
configuration ni environnement) : l'URL de la base des comptes, l'URL
publique du front (pour construire le lien d'invitation à l'« Accepter »),
les secrets du service (`[admin]`, `[brevo]`). Elle refuse de démarrer sans
`[admin]` — rien à authentifier sans lui, et c'est voulu : une administration
sans identifiant serait une porte sans serrure.
"""

from __future__ import annotations

import argparse
import sys

from ourouler.cli.comptes import _charger_service, _url_des_comptes, _url_publique
from ourouler.config import Config
from ourouler.noyau.erreurs import ErreurUtilisateur


def ajouter_admin(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "admin",
        help=(
            "lance l'administration du service hébergé — écoute UNIQUEMENT sur "
            "127.0.0.1, jamais exposée sur Internet (nécessite `uv sync --extra api`)"
        ),
        description=(
            "Lance l'administration : file des demandes d'invitation, comptes actifs, "
            "invitations en cours, tâches de fond, quotas du jour. N'écoute que sur "
            "127.0.0.1, dans le conteneur — on y accède par un tunnel SSH puis "
            "`docker exec`, jamais directement (voir deploiement/api/README.md). "
            "Refuse de démarrer sans la section [admin] de service.toml."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="port d'écoute, sur 127.0.0.1 uniquement (défaut : [admin] port de service.toml, ou 8001)",
    )
    p.set_defaults(fonction=_commande_admin, requiert_profil=False)


def _commande_admin(args: argparse.Namespace, config: Config) -> int:
    del config  # cette commande ne construit aucune configuration cycliste
    try:
        import uvicorn

        from ourouler.api.admin import ParametresApplicationAdmin, creer_application_admin
        from ourouler.api.base_de_donnees import appliquer_migrations, ouvrir
        from ourouler.api.exploitation import parametres_admin, parametres_brevo_service, port_admin
    except ImportError as e:
        raise ErreurUtilisateur(
            f"admin : FastAPI et uvicorn ne sont pas installés — `uv sync --extra api` ({e})"
        ) from e

    identifiant = parametres_admin()
    if identifiant is None:
        raise ErreurUtilisateur(
            "admin : section [admin] absente ou incomplète dans service.toml — "
            "poser [admin] identifiant et secret pour pouvoir démarrer l'administration "
            "(voir service.example.toml)"
        )

    url_db = _url_des_comptes("admin")
    url_pub = _url_publique()
    with ouvrir(url_db) as connexion, connexion:
        posees = appliquer_migrations(connexion)
        if posees:
            print(f"base des comptes : {len(posees)} migration(s) appliquée(s)", file=sys.stderr)

    # Le relais SMTP est facultatif ici aussi : sans lui, « Accepter » émet
    # quand même l'invitation (même règle que `ourouler inviter --sans-courriel`),
    # elle n'affiche que le lien au lieu de l'envoyer.
    parametres_smtp = None
    try:
        brut_service = _charger_service()
        from ourouler.api.courriel import parametres_brevo_depuis_dict

        parametres_smtp = parametres_brevo_depuis_dict(brut_service)
    except ErreurUtilisateur:
        parametres_smtp = parametres_brevo_service()

    application = creer_application_admin(
        ParametresApplicationAdmin(
            url_comptes=url_db,
            identifiant=identifiant,
            url_publique=url_pub,
            parametres_brevo=parametres_smtp,
        )
    )
    port = args.port if args.port is not None else port_admin()
    print(
        f"ourouler : administration sur http://127.0.0.1:{port}/admin/ "
        "(jamais exposée sur Internet — voir deploiement/api/README.md)",
        file=sys.stderr,
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="info")
    return 0


__all__ = ["ajouter_admin"]

"""`ourouler inventaire` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.activites import commande as service
from ourouler.activites.cache import Cache
from ourouler.activites.commande import DemandeInventaire, ResultatInventaire, date_depuis
from ourouler.activites.inventaire import rendre_json, rendre_texte
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.noyau.profil import Profil


def lire_options(args: argparse.Namespace, profil: Profil) -> DemandeInventaire:
    return demande(
        profil,
        depuis=getattr(args, "depuis", None),
        importer=getattr(args, "importer", None),
        synchroniser=bool(getattr(args, "synchroniser", False)),
        sans_rafraichir=bool(getattr(args, "sans_rafraichir", False)),
    )


def demande(
    profil: Profil,
    *,
    depuis: str | None = None,
    importer: str | None = None,
    synchroniser: bool = False,
    sans_rafraichir: bool = False,
) -> DemandeInventaire:
    """La demande d'inventaire, depuis les valeurs brutes des options."""
    return DemandeInventaire(
        depuis=date_depuis(depuis, profil.historique_depuis),
        importer=importer,
        synchroniser=synchroniser,
        rafraichir_meta=not sans_rafraichir,
    )


def json_inventaire(resultat: ResultatInventaire) -> dict:
    """Le JSON de `ourouler inventaire --json`, journal compris."""
    sortie = rendre_json(resultat.inventaire)
    sortie["journal"] = list(resultat.journal)
    return sortie


def executer_depuis_namespace(
    args: argparse.Namespace, config: Config, cache: Cache | None = None
) -> int:
    """Exécute `ourouler inventaire`. Renvoie le code de sortie (0 = succès)."""
    ctx = contexte(config)
    resultat = service.executer(lire_options(args, ctx.profil), ctx, cache=cache)
    if getattr(args, "json", False):
        imprimer_json(json_inventaire(resultat))
    else:
        for ligne in resultat.journal:
            print(ligne)
        if resultat.journal:
            print()
        print(rendre_texte(resultat.inventaire))
    return 0

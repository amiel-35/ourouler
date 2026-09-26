"""`ourouler inventaire` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.activites import commande as service
from ourouler.activites.cache import Cache
from ourouler.activites.commande import DemandeInventaire, date_depuis
from ourouler.activites.inventaire import rendre_json, rendre_texte
from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.noyau.profil import Profil


def lire_options(args: argparse.Namespace, profil: Profil) -> DemandeInventaire:
    return DemandeInventaire(
        depuis=date_depuis(getattr(args, "depuis", None), profil.historique_depuis),
        importer=getattr(args, "importer", None),
        synchroniser=bool(getattr(args, "synchroniser", False)),
        rafraichir_meta=not getattr(args, "sans_rafraichir", False),
    )


def executer_depuis_namespace(
    args: argparse.Namespace, config: Config, cache: Cache | None = None
) -> int:
    """Exécute `ourouler inventaire`. Renvoie le code de sortie (0 = succès)."""
    ctx = contexte(config)
    resultat = service.executer(lire_options(args, ctx.profil), ctx, cache=cache)
    if getattr(args, "json", False):
        sortie = rendre_json(resultat.inventaire)
        sortie["journal"] = list(resultat.journal)
        imprimer_json(sortie)
    else:
        for ligne in resultat.journal:
            print(ligne)
        if resultat.journal:
            print()
        print(rendre_texte(resultat.inventaire))
    return 0

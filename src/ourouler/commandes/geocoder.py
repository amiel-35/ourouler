"""`ourouler geocoder ADRESSE` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.commandes.commun import imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.geocodage import LIMITE_DEFAUT, ClientBAN, ClientNominatim
from ourouler.geocodage import commande as service
from ourouler.geocodage.commande import DemandeGeocodage, rendre_json, rendre_texte


def lire_options(args: argparse.Namespace) -> DemandeGeocodage:
    return demande(args.adresse, maximum=getattr(args, "max", None))


def demande(adresse: str, *, maximum: int | None = None) -> DemandeGeocodage:
    """L'adresse et le nombre de candidats voulus (`--max`), le défaut sinon."""
    return DemandeGeocodage(adresse=adresse, limite=maximum or LIMITE_DEFAUT)


def executer_depuis_namespace(
    args: argparse.Namespace,
    config: Config | None = None,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
) -> int:
    """Exécute `ourouler geocoder`. Renvoie le code de sortie (0 = succès).

    `config` n'est pas lue : le géocodage ne dépend d'aucun réglage du cycliste.
    """
    del config
    resultat = service.executer(lire_options(args), None, ban=ban, nominatim=nominatim)
    if getattr(args, "json", False):
        imprimer_json(rendre_json(resultat.adresse, resultat.candidats))
    else:
        print(rendre_texte(resultat.adresse, resultat.candidats))
    return 0

"""`ourouler meteo` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse

from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.meteo import commande as service
from ourouler.meteo.commande import DemandeMeteo, heure_depart, valider_horizon
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import rendre_json, rendre_texte
from ourouler.noyau.profil import Depart, Profil


def lire_options(args: argparse.Namespace, profil: Profil) -> DemandeMeteo:
    """Les options, interprétées **avant** tout appel : horizon borné, puis heure de départ.

    `--horizon 0` doit être refusé, pas remplacé par la configuration : d'où
    le test sur `None` plutôt qu'un `or`.
    """
    modele = getattr(args, "modele", None) or profil.meteo.modele
    second_avis = getattr(args, "second_avis", None) or profil.meteo.second_avis
    horizon = getattr(args, "horizon", None)
    horizon_h = valider_horizon(profil.meteo.horizon_h if horizon is None else horizon)
    # Heure locale, consciente du fuseau : le client la convertit en UTC lui-même.
    debut = heure_depart(getattr(args, "depart", None))
    return DemandeMeteo(debut=debut, horizon_h=horizon_h, modele=modele, second_avis=second_avis)


def executer_depuis_namespace(
    args: argparse.Namespace,
    config: Config,
    client: ClientOpenMeteo | None = None,
    *,
    lieu_depart: Depart | None = None,
) -> int:
    """Exécute `ourouler meteo`. Renvoie le code de sortie (0 = succès).

    `lieu_depart` est le **point de départ de cette exécution**, déjà tranché
    par l'appelant : `cli.py` quand `--adresse-depart` a été géocodée, une
    requête d'API. Absent, c'est celui de la configuration. À ne pas confondre
    avec `args.depart`, qui porte une **heure** (ancien nom de
    `--heure-depart`).
    """
    ctx = contexte(config, lieu_depart=lieu_depart)
    rapport = service.executer(lire_options(args, ctx.profil), ctx, client=client)
    if getattr(args, "json", False):
        imprimer_json(rendre_json(rapport))
    else:
        print(rendre_texte(rapport, distance_km=getattr(args, "distance", None)))
    return 0

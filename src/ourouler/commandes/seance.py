"""`ourouler seance` : la demande, le service, le rendu imprimé."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ourouler.commandes.commun import contexte, imprimer_json
from ourouler.config import Config
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.seance import commande as service
from ourouler.seance.commande import (
    DemandeSeance,
    ResultatPeriode,
    ResultatSeance,
    jour_option,
    rendre_json,
    rendre_json_periode,
    rendre_texte,
    rendre_texte_periode,
    valider_mode,
)


def lire_options(args: argparse.Namespace) -> DemandeSeance:
    return interpreter(
        jour=getattr(args, "jour", None),
        depuis=getattr(args, "depuis", None),
        jusqua=getattr(args, "jusqua", None),
        fichier_seance=getattr(args, "fichier_seance", None),
    )


def interpreter(
    *,
    jour: str | None = None,
    depuis: str | None = None,
    jusqua: str | None = None,
    fichier_seance: str | None = None,
) -> DemandeSeance:
    """Les options, validées puis interprétées.

    Les modes sont vérifiés d'abord (exclusifs entre eux sauf `--jour`, qui
    reste compatible avec `--fichier-seance`), les dates ensuite : une date
    illisible est refusée avant tout appel à Intervals.icu.
    """
    valider_mode(jour, depuis, jusqua, fichier_seance)
    if fichier_seance:
        return DemandeSeance(jour=jour_option(jour), fichier=Path(fichier_seance))
    if depuis or jusqua:
        return DemandeSeance(depuis=jour_option(depuis), jusqua=jour_option(jusqua))
    return DemandeSeance(jour=jour_option(jour))


def json_seance(resultat: ResultatSeance | ResultatPeriode) -> dict:
    """Le JSON de `ourouler seance --json` : une période, un jour sans séance, une séance."""
    if isinstance(resultat, ResultatPeriode):
        r = resultat
        return rendre_json_periode(r.depuis, r.jusqua, r.resultats, r.vitesses, r.source)
    if resultat.seance is None:
        return {"jour": resultat.jour.isoformat(), "seance": None}
    return rendre_json(resultat.seance, resultat.mesures, resultat.source)


def executer_depuis_namespace(
    args: argparse.Namespace, config: Config, client: ClientIntervals | None = None
) -> int:
    """Exécute `ourouler seance`. Sans séance ce jour-là : message clair, code 0."""
    resultat = service.executer(lire_options(args), contexte(config), client=client)
    if getattr(args, "json", False):
        donnees = json_seance(resultat)
        if isinstance(resultat, ResultatSeance) and resultat.seance is None:
            # Sur une ligne, comme depuis le début : c'est la forme qu'on lit.
            print(json.dumps(donnees, ensure_ascii=False))
        else:
            imprimer_json(donnees)
        return 0
    if isinstance(resultat, ResultatPeriode):
        r = resultat
        print(rendre_texte_periode(r.depuis, r.jusqua, r.resultats, r.vitesses, r.source))
    elif resultat.seance is None:
        print(f"Aucune séance vélo planifiée le {resultat.jour.isoformat()} sur Intervals.icu.")
    else:
        print(rendre_texte(resultat.seance, resultat.mesures, resultat.source))
    return 0

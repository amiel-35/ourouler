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
    jour_option,
    rendre_json,
    rendre_json_periode,
    rendre_texte,
    rendre_texte_periode,
    valider_mode,
)


def lire_options(args: argparse.Namespace) -> DemandeSeance:
    """Les options, validées puis interprétées.

    Les modes sont vérifiés d'abord (exclusifs entre eux sauf `--jour`, qui
    reste compatible avec `--fichier-seance`), les dates ensuite : une date
    illisible est refusée avant tout appel à Intervals.icu.
    """
    jour_brut = getattr(args, "jour", None)
    depuis_brut = getattr(args, "depuis", None)
    jusqua_brut = getattr(args, "jusqua", None)
    fichier_brut = getattr(args, "fichier_seance", None)
    valider_mode(jour_brut, depuis_brut, jusqua_brut, fichier_brut)
    if fichier_brut:
        return DemandeSeance(jour=jour_option(jour_brut), fichier=Path(fichier_brut))
    if depuis_brut or jusqua_brut:
        return DemandeSeance(depuis=jour_option(depuis_brut), jusqua=jour_option(jusqua_brut))
    return DemandeSeance(jour=jour_option(jour_brut))


def executer_depuis_namespace(
    args: argparse.Namespace, config: Config, client: ClientIntervals | None = None
) -> int:
    """Exécute `ourouler seance`. Sans séance ce jour-là : message clair, code 0."""
    resultat = service.executer(lire_options(args), contexte(config), client=client)
    en_json = getattr(args, "json", False)
    if isinstance(resultat, ResultatPeriode):
        r = resultat
        if en_json:
            imprimer_json(rendre_json_periode(r.depuis, r.jusqua, r.resultats, r.vitesses, r.source))
        else:
            print(rendre_texte_periode(r.depuis, r.jusqua, r.resultats, r.vitesses, r.source))
        return 0
    if resultat.seance is None:
        if en_json:
            print(json.dumps({"jour": resultat.jour.isoformat(), "seance": None}, ensure_ascii=False))
        else:
            print(f"Aucune séance vélo planifiée le {resultat.jour.isoformat()} sur Intervals.icu.")
        return 0
    if en_json:
        imprimer_json(rendre_json(resultat.seance, resultat.mesures, resultat.source))
    else:
        print(rendre_texte(resultat.seance, resultat.mesures, resultat.source))
    return 0

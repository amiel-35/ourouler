"""Sous-commande `ourouler inventaire`.

Adaptateur entre `argparse` et le cœur : ne lit aucun fichier de
configuration (la `Config` arrive déjà construite), n'affiche jamais de clé.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from ourouler.activites.cache import Cache
from ourouler.activites.inventaire import inventaire, rendre_json, rendre_texte
from ourouler.config import Config
from ourouler.erreurs import ErreurUtilisateur


def executer(args: argparse.Namespace, config: Config) -> int:
    depuis = _depuis(getattr(args, "depuis", None), config)
    cache = Cache(config.cache.dossier)
    journal: list[str] = []

    if getattr(args, "importer", None):
        ajoutes = cache.indexer_dossier(args.importer)
        journal.append(f"Import de {args.importer} : {ajoutes} activité(s) ajoutée(s).")
        for echec in cache.echecs:
            journal.append(f"  ignoré — {echec}")

    if getattr(args, "synchroniser", False):
        journal.extend(_synchroniser(cache, config, depuis))

    inv = inventaire(cache, config, depuis)
    if getattr(args, "json", False):
        sortie = rendre_json(inv)
        sortie["journal"] = journal
        print(json.dumps(sortie, ensure_ascii=False, indent=2))
    else:
        for ligne in journal:
            print(ligne)
        if journal:
            print()
        print(rendre_texte(inv))
    return 0


def _depuis(brut: str | None, config: Config) -> date:
    if not brut:
        return config.historique_depuis
    try:
        return date.fromisoformat(brut)
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis : date AAAA-MM-JJ attendue, reçu « {brut} »") from e


def _synchroniser(cache: Cache, config: Config, depuis: date) -> list[str]:
    """Rapatrie les activités Intervals.icu manquantes. Import paresseux : le
    connecteur n'est chargé que si on s'en sert."""
    if not config.intervals.renseigne:
        raise ErreurUtilisateur(
            "--synchroniser : [intervals] athlete_id et api_key doivent être "
            "renseignés dans la configuration (Intervals.icu → Settings → Developer)"
        )
    from ourouler.connecteurs.intervals import ClientIntervals, synchroniser

    client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    rapport = synchroniser(client, cache, depuis)
    journal = [
        f"Synchronisation Intervals.icu depuis le {depuis.isoformat()} : "
        f"{rapport.vues} vue(s), {rapport.ajoutees} ajoutée(s), "
        f"{rapport.ignorees} déjà en cache, {rapport.echecs} échec(s)."
    ]
    journal.extend(f"  échec — {m}" for m in rapport.messages)
    return journal

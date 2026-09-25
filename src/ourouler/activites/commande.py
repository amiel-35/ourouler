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
from ourouler.noyau.erreurs import ErreurUtilisateur


def executer(args: argparse.Namespace, config: Config, cache: Cache | None = None) -> int:
    """Exécute `ourouler inventaire`. Renvoie le code de sortie (0 = succès).

    **`cache` s'injecte, exactement comme un client HTTP** (règle 3 de
    CLAUDE.md, et c'est déjà la forme de `client_brouter` dans
    `apprentissage/commande.py`). Absent — le cas de la ligne de commande —
    la commande le construit comme avant, sur `config.cache.dossier` et avec
    le propriétaire par défaut.

    C'est ce qui ferme [[Q58]] sans faire entrer la notion de service dans le
    cœur : la commande reçoit un dépôt déjà fait et ne prononce jamais le mot
    « propriétaire ». Le seul endroit qui le prononce est l'appelant — pour
    l'API, `api/routes.py`, qui construit
    `Cache(config.cache.dossier, proprietaire=str(qui))`, exactement comme
    `api/vie_privee.py` le fait déjà. Doctrine §10.1 : « le propriétaire entre
    au constructeur du dépôt, et nulle part ailleurs […] en hébergé, c'est la
    couche web qui construira le dépôt avec l'identifiant de l'utilisateur
    authentifié ».
    """
    depuis = _depuis(getattr(args, "depuis", None), config)
    cache = cache if cache is not None else Cache(config.cache.dossier)
    journal: list[str] = []

    if getattr(args, "importer", None):
        ajoutes = cache.indexer_dossier(args.importer)
        journal.append(f"Import de {args.importer} : {ajoutes} activité(s) ajoutée(s).")
        for echec in cache.echecs:
            journal.append(f"  ignoré — {echec}")

    if getattr(args, "synchroniser", False):
        journal.extend(
            _synchroniser(
                cache,
                config,
                depuis,
                rafraichir_meta=not getattr(args, "sans_rafraichir", False),
            )
        )

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


def _synchroniser(
    cache: Cache, config: Config, depuis: date, *, rafraichir_meta: bool = True
) -> list[str]:
    """Rapatrie les activités Intervals.icu manquantes. Import paresseux : le
    connecteur n'est chargé que si on s'en sert."""
    if not config.intervals.renseigne:
        raise ErreurUtilisateur(
            "--synchroniser : [intervals] athlete_id et api_key doivent être "
            "renseignés dans la configuration (Intervals.icu → Settings → Developer)"
        )
    from ourouler.connecteurs.intervals import ClientIntervals, synchroniser

    client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    rapport = synchroniser(client, cache, depuis, rafraichir_meta=rafraichir_meta)
    journal = [
        f"Synchronisation Intervals.icu depuis le {depuis.isoformat()} : "
        f"{rapport.vues} vue(s), {rapport.ajoutees} ajoutée(s), "
        f"{rapport.ignorees} déjà en cache (dont {rapport.mises_a_jour} "
        f"métadonnées mises à jour), {rapport.autres_sports} autre(s) sport(s), "
        f"{rapport.sans_contenu} sans contenu, {rapport.echecs} échec(s)."
    ]
    journal.extend(f"  échec — {m}" for m in rapport.messages)
    return journal

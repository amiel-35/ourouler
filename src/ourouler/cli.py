"""Ligne de commande `ourouler`.

Seule couche autorisée (avec `config.py`) à lire un fichier de configuration.
Chaque sous-commande est déclarée par une fonction `ajouter_<nom>` qui
importe son module paresseusement : une sous-commande absente ou cassée ne
doit pas empêcher les autres de tourner.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ourouler import __version__
from ourouler.config import CHEMIN_CONFIG_DEFAUT, Config, charger
from ourouler.erreurs import ErreurUtilisateur


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ourouler",
        description="Où rouler ? Météo par direction, tracé et séance pour cyclistes.",
    )
    p.add_argument("--version", action="version", version=f"ourouler {__version__}")
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"fichier de configuration TOML (défaut : {CHEMIN_CONFIG_DEFAUT})",
    )
    p.add_argument("--json", action="store_true", help="sortie JSON au lieu du texte")
    sous = p.add_subparsers(dest="commande", metavar="<commande>")
    ajouter_config(sous)
    ajouter_inventaire(sous)
    ajouter_meteo(sous)
    return p


# --- sous-commandes -----------------------------------------------------------


def parent_json() -> argparse.ArgumentParser:
    """Parseur parent qui rend `--json` acceptable **après** la sous-commande.

    Le contrat de sprint écrit `ourouler meteo [...] [--json]`, mais l'option
    n'existait qu'en global : `ourouler meteo --json` répondait
    « unrecognized arguments », et la seule forme qui marchait
    (`ourouler --json meteo`) n'était écrite nulle part.

    Deux précautions :
    - `add_help=False`, sinon le parent redéclare `-h` et argparse refuse ;
    - `default=argparse.SUPPRESS`, sinon le sous-parseur écrirait
      `json=False` par-dessus la valeur posée par l'option globale et
      casserait `ourouler --json meteo`. Avec SUPPRESS, l'attribut n'est
      touché que si l'option est vraiment passée.

    Le `dest` reste `json` des deux côtés : les commandes lisent un seul champ.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="sortie JSON au lieu du texte (accepté avant ou après la sous-commande)",
    )
    return parent


def ajouter_config(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "config",
        help="vérifie et affiche la configuration chargée",
        parents=[parent_json()],
    )
    p.set_defaults(fonction=_commande_config)


def _commande_config(args: argparse.Namespace, config: Config) -> int:
    if args.json:
        import dataclasses
        import json

        def defaut(o):  # dates, Path
            return str(o)

        d = dataclasses.asdict(config)
        d["intervals"]["api_key"] = "***" if config.intervals.api_key else ""
        print(json.dumps(d, default=defaut, ensure_ascii=False, indent=2))
        return 0
    print(f"Départ   : {config.depart.nom} ({config.depart.latitude:.4f}, {config.depart.longitude:.4f})")
    print(f"Cycliste : {config.cycliste.masse_kg:.1f} kg, FTP {config.cycliste.ftp_w:.0f} W")
    print(f"Vélos    : {', '.join(v.nom + ' (' + v.usage + ')' for v in config.velos)}")
    print(
        f"Météo    : {config.meteo.directions} directions × {list(config.meteo.distances_km)} km, "
        f"{config.meteo.modele} (second avis {config.meteo.second_avis}), horizon {config.meteo.horizon_h} h"
    )
    print(f"Intervals: {'renseigné' if config.intervals.renseigne else 'non renseigné'}")
    print(f"Cache    : {config.cache.dossier}")
    print(f"Historique depuis : {config.historique_depuis}")
    return 0


def ajouter_inventaire(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "inventaire",
        help="inventaire des sorties par vélo et par mois",
        parents=[parent_json()],
    )
    p.add_argument("--depuis", help="date AAAA-MM-JJ (défaut : historique_depuis de la config)")
    p.add_argument("--importer", type=Path, metavar="DOSSIER", help="indexe les FIT/GPX/TCX d'un dossier")
    p.add_argument("--synchroniser", action="store_true", help="rapatrie les activités Intervals.icu")
    p.set_defaults(fonction=_commande_inventaire)


def _commande_inventaire(args: argparse.Namespace, config: Config) -> int:
    from ourouler.activites.commande import executer  # import paresseux (lot L1.3)

    return executer(args, config)


def ajouter_meteo(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "meteo",
        help="pluie, vent et ressenti par direction et par heure",
        parents=[parent_json()],
    )
    p.add_argument("--depart", help="heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : maintenant)")
    p.add_argument("--horizon", type=int, help="nombre d'heures (défaut : config)")
    p.add_argument("--distance", type=float, help="n'afficher qu'une couronne (km)")
    p.add_argument("--modele", help="modèle principal Open-Meteo (défaut : config)")
    p.add_argument("--second-avis", dest="second_avis", help="modèle de second avis (défaut : config)")
    p.set_defaults(fonction=_commande_meteo)


def _commande_meteo(args: argparse.Namespace, config: Config) -> int:
    from ourouler.meteo.commande import executer  # import paresseux (lot L1.5)

    return executer(args, config)


# --- point d'entrée -----------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parseur = construire_parseur()
    args = parseur.parse_args(argv)
    if not getattr(args, "fonction", None):
        parseur.print_help()
        return 0
    try:
        config = charger(args.config)
        return int(args.fonction(args, config))
    except ErreurUtilisateur as e:
        print(f"ourouler : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

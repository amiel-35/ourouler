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
    ajouter_boucle(sous)
    ajouter_routes(sous)
    ajouter_calibrer(sous)
    ajouter_simuler(sous)
    ajouter_comparer(sous)
    ajouter_seance(sous)
    ajouter_sortie(sous)
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


#: Les anciens noms de l'heure de départ, acceptés et **non documentés**.
#:
#: Q15, tranchée par le mainteneur le 13/09 : l'heure de départ s'appelle
#: `--heure-depart` et le lieu de départ s'appellera `--adresse-depart` (nom
#: réservé, pas encore livré). `--depart` seul était ambigu dès que le lieu
#: existerait ; `--heure` avait été ajouté en attendant la décision.
#:
#: Les deux restent acceptés pour ne rien casser — le mainteneur a des scripts
#: et des habitudes — mais ils ne figurent plus dans l'aide : un nom déprécié
#: qu'on documente est un nom qu'on enseigne encore.
ANCIENS_NOMS_HEURE_DEPART = ("--depart", "--heure")


def ajouter_heure_depart(p: argparse.ArgumentParser, aide: str) -> None:
    """Ajoute `--heure-depart` à une sous-commande, plus ses anciens noms.

    Deux déclarations et non une seule liste d'alias, parce qu'argparse ne
    sait pas masquer un alias dans l'aide : il les imprime tous ou aucun. La
    seconde déclaration, sous `argparse.SUPPRESS`, écrit dans le même `dest`
    que la première — `depart`, inchangé, pour que les commandes continuent de
    lire un seul champ.
    """
    p.add_argument("--heure-depart", dest="depart", metavar="HEURE", help=aide)
    p.add_argument(
        *ANCIENS_NOMS_HEURE_DEPART,
        dest="depart",
        metavar="HEURE",
        help=argparse.SUPPRESS,
    )


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
        # `asdict` ignore les `__repr__` qui masquent : sans ces deux lignes,
        # `ourouler config --json` publie la clé et le mot de passe en clair.
        d["intervals"]["api_key"] = "***" if config.intervals.api_key else ""
        d["brouter"]["mot_de_passe"] = "***" if config.brouter.mot_de_passe else ""
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
    # L'URL du serveur s'affiche — c'est une adresse, pas un secret ; le mot de
    # passe, lui, n'est jamais imprimé, pas même masqué par un compte-caractères.
    if config.brouter.renseigne:
        print(
            f"BRouter  : renseigné — {config.brouter.url}, profil {config.brouter.profil}, "
            f"timeout {config.brouter.timeout_s:.0f} s"
        )
    else:
        print("BRouter  : non renseigné")
    print(
        f"Boucle   : {config.boucle.candidates} candidates, sens {config.boucle.sens}, "
        f"{config.boucle.vitesse_moyenne_kmh:.0f} km/h, tolérance "
        f"{config.boucle.tolerance_distance:.0%}"
    )
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
    p.add_argument(
        "--sans-rafraichir",
        dest="sans_rafraichir",
        action="store_true",
        help="avec --synchroniser : ne pas rafraîchir les métadonnées des sorties déjà en cache",
    )
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
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : maintenant)")
    p.add_argument("--horizon", type=int, help="nombre d'heures (défaut : config)")
    p.add_argument("--distance", type=float, help="n'afficher qu'une couronne (km)")
    p.add_argument("--modele", help="modèle principal Open-Meteo (défaut : config)")
    p.add_argument("--second-avis", dest="second_avis", help="modèle de second avis (défaut : config)")
    p.set_defaults(fonction=_commande_meteo)


def _commande_meteo(args: argparse.Namespace, config: Config) -> int:
    from ourouler.meteo.commande import executer  # import paresseux (lot L1.5)

    return executer(args, config)


def ajouter_boucle(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "boucle",
        help="propose des boucles dans une direction, avec coûts et météo le long du tracé",
        parents=[parent_json()],
    )
    p.add_argument(
        "--distance", type=float, metavar="KM", help="longueur voulue en km (obligatoire sans --gpx)"
    )
    p.add_argument(
        "--direction",
        help="N, NE, … NO ou un azimut en degrés (obligatoire sans --gpx)",
    )
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : maintenant)")
    p.add_argument("--candidates", type=int, help="nombre de boucles proposées (défaut : config)")
    p.add_argument("--profil", help="profil BRouter (défaut : config)")
    p.add_argument("--sortie", metavar="FICHIER.GPX", help="où écrire la boucle retenue")
    p.add_argument(
        "--ecraser",
        action="store_true",
        help="remplacer le fichier de --sortie s'il existe déjà",
    )
    p.add_argument("--gpx", metavar="ENTREE.GPX", help="évaluer ce GPX au lieu d'en générer")
    p.add_argument(
        "--velo",
        help="vélo dont la calibration sert au temps estimé (défaut : premier vélo route)",
    )
    p.add_argument(
        "--puissance",
        type=float,
        metavar="W",
        help="puissance tenue pour le temps estimé par le modèle (défaut : part de la FTP)",
    )
    p.set_defaults(fonction=_commande_boucle)


def _commande_boucle(args: argparse.Namespace, config: Config) -> int:
    from ourouler.boucle.commande import executer  # import paresseux (lot L2.6)

    return executer(args, config)


def ajouter_routes(sous: argparse._SubParsersAction) -> None:
    """`ourouler routes {apprendre,stats,poids}` — ce que les sorties passées apprennent.

    Les actions sont des sous-sous-commandes : chacune a ses options, et
    `--json` est accepté aux trois niveaux (global, `routes`, action) grâce à
    `parent_json()` et son `SUPPRESS`.
    """
    p = sous.add_parser(
        "routes",
        help="routes connues : apprendre des sorties passées, statistiques et poids",
        parents=[parent_json()],
    )
    actions = p.add_subparsers(dest="action", metavar="<action>")

    a = actions.add_parser(
        "apprendre",
        help="rejoue les sorties extérieures dans BRouter (un appel par sortie, idempotent)",
        parents=[parent_json()],
    )
    a.add_argument("--depuis", help="date AAAA-MM-JJ (défaut : historique_depuis de la config)")
    a.add_argument(
        "--max",
        type=int,
        dest="max_sorties",
        metavar="N",
        help="borner à N les appels au moteur (pour essayer sans tout lancer)",
    )

    actions.add_parser(
        "stats",
        help="km et part par classe de route, part semaine, poids par défaut et appris",
        parents=[parent_json()],
    )

    w = actions.add_parser(
        "poids",
        help="compare les sorties à huit boucles d'exposition et en déduit les poids",
        parents=[parent_json()],
    )
    w.add_argument(
        "--appliquer",
        action="store_true",
        help="écrire les poids dans poids_routes.json (le cache), utilisés par `boucle`",
    )
    p.set_defaults(fonction=_commande_routes)


def _commande_routes(args: argparse.Namespace, config: Config) -> int:
    from ourouler.apprentissage.commande import executer  # import paresseux (lot L3.2)

    return executer(args, config)


def ajouter_calibrer(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "calibrer",
        help="ajuste CdA et Crr d'un vélo sur les sorties réelles, et mesure l'erreur",
        parents=[parent_json()],
    )
    p.add_argument("--velo", help="nom du vélo (défaut : premier vélo d'usage route)")
    p.add_argument("--depuis", help="date AAAA-MM-JJ (défaut : historique_depuis de la config)")
    p.add_argument(
        "--max", type=int, metavar="N", help="ne garder que les N sorties les plus récentes"
    )
    p.set_defaults(fonction=_commande_calibrer)


def _commande_calibrer(args: argparse.Namespace, config: Config) -> int:
    from ourouler.physique.commande import executer_calibrer  # import paresseux (lot L3.3)

    return executer_calibrer(args, config)


def ajouter_simuler(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "simuler",
        help="temps en mouvement d'un GPX à puissance constante, avec le modèle calibré",
        parents=[parent_json()],
    )
    p.add_argument("--gpx", metavar="FICHIER.GPX", required=True, help="le parcours à simuler")
    p.add_argument("--puissance", type=float, metavar="W", required=True, help="puissance tenue")
    p.add_argument("--velo", help="nom du vélo (défaut : premier vélo d'usage route)")
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (pour le vent prévu)")
    p.set_defaults(fonction=_commande_simuler)


def _commande_simuler(args: argparse.Namespace, config: Config) -> int:
    from ourouler.physique.commande import executer_simuler  # import paresseux (lot L3.3)

    return executer_simuler(args, config)


def ajouter_comparer(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "comparer",
        help="de combien de km/h (et de watts) deux vélos diffèrent, sur le plat en ligne droite",
        parents=[parent_json()],
    )
    p.add_argument(
        "--velos",
        nargs=2,
        metavar="VELO",
        required=True,
        help="les deux vélos à comparer, par exemple `--velos RCR BMC`",
    )
    p.add_argument(
        "--zone",
        nargs=2,
        type=float,
        metavar=("BAS", "HAUT"),
        help="zone de puissance en fraction de la FTP (défaut : 0.56 0.75, soit Z2)",
    )
    p.add_argument(
        "--pente-max",
        type=float,
        metavar="PENTE",
        help="pente maximale d'un tronçon, en tangente (défaut : 0.008, soit 0,8 %%)",
    )
    p.add_argument(
        "--cap-max",
        type=float,
        metavar="DEGRES",
        help="filtre optionnel : écart de cap toléré d'un tronçon au suivant, en degrés "
        "(par défaut, aucun filtre de cap ; 15 ne garde que les lignes droites franches)",
    )
    p.add_argument(
        "--longueur-min",
        type=float,
        metavar="METRES",
        help="longueur minimale d'une série retenue, en mètres (défaut : 500)",
    )
    p.add_argument("--depuis", help="date AAAA-MM-JJ (défaut : historique_depuis de la config)")
    p.set_defaults(fonction=_commande_comparer)


def _commande_comparer(args: argparse.Namespace, config: Config) -> int:
    from ourouler.physique.comparer import executer_comparer  # import paresseux (lot L3.3)

    return executer_comparer(args, config)


def ajouter_seance(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "seance",
        help="la séance planifiée du jour, étape par étape, avec la route que chaque bloc demande",
        parents=[parent_json()],
    )
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help="date de la séance (défaut : aujourd'hui)")
    p.set_defaults(fonction=_commande_seance)


def _commande_seance(args: argparse.Namespace, config: Config) -> int:
    from ourouler.seance.commande import executer  # import paresseux (lot L4.1)

    return executer(args, config)


def ajouter_sortie(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "sortie",
        help="la séance du jour posée sur une boucle : tableau, GPX, tenue et carte HTML",
        parents=[parent_json()],
    )
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help="date de la séance (défaut : aujourd'hui)")
    p.add_argument(
        "--distance",
        type=float,
        metavar="KM",
        help="longueur de la boucle (défaut : la distance estimée de la séance, "
        "arrondie au multiple de 5 supérieur)",
    )
    p.add_argument(
        "--direction",
        help="N, NE, … NO ou un azimut en degrés (défaut : candidates tout autour de l'horizon)",
    )
    p.add_argument("--candidates", type=int, help="nombre de boucles proposées (défaut : config)")
    p.add_argument("--velo", help="vélo dont la calibration sert au placement (défaut : premier vélo route)")
    ajouter_heure_depart(
        p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : le jour de la séance)"
    )
    p.add_argument("--sortie", metavar="FICHIER.GPX", help="où écrire la boucle retenue")
    p.add_argument("--carte", metavar="FICHIER.HTML", help="où écrire la carte de vérification")
    p.add_argument("--profil", help="profil BRouter (défaut : config)")
    p.add_argument(
        "--ecraser",
        action="store_true",
        help="remplacer les fichiers de --sortie et --carte s'ils existent déjà",
    )
    p.set_defaults(fonction=_commande_sortie)


def _commande_sortie(args: argparse.Namespace, config: Config) -> int:
    from ourouler.sortie.commande import executer  # import paresseux (lot L4.4)

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

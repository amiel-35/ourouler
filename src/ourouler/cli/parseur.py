"""La construction de l'argparse de `ourouler`, et les sous-commandes de calcul.

Chaque sous-commande est déclarée par une fonction `ajouter_<nom>` et servie
par `_commande_<nom>`, qui importe son module paresseusement : une
sous-commande absente ou cassée ne doit pas empêcher les autres de tourner.
Les commandes de l'exploitant (comptes) sont dans `comptes.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ourouler import __version__
from ourouler.cli.comptes import (
    ajouter_invitations,
    ajouter_inviter,
    ajouter_reinitialiser,
    ajouter_retirer,
)
from ourouler.cli.depart import lieu_depart
from ourouler.cli.options import ajouter_adresse_depart, ajouter_heure_depart, parent_json
from ourouler.config import CHEMIN_CONFIG_DEFAUT, Config
from ourouler.connecteurs.geocodage import LIMITE_DEFAUT
from ourouler.noyau.erreurs import ErreurUtilisateur
from ourouler.rendu.profil import info_vitesse_compteur, profil_json

# Module volontairement sans dépendance : la liste des réponses à `--vent`
# est nécessaire à la construction du parseur, donc à chaque `--help`.
from ourouler.sortie.orientation import CHOIX as CHOIX_VENT


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
    ajouter_analyser(sous)
    ajouter_comparer(sous)
    ajouter_seance(sous)
    ajouter_sortie(sous)
    ajouter_geocoder(sous)
    ajouter_api(sous)
    ajouter_inviter(sous)
    ajouter_invitations(sous)
    ajouter_reinitialiser(sous)
    ajouter_retirer(sous)
    return p


# --- sous-commandes -----------------------------------------------------------


def ajouter_config(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "config",
        help="vérifie et affiche la configuration chargée",
        parents=[parent_json()],
    )
    p.set_defaults(fonction=_commande_config)


def _commande_config(args: argparse.Namespace, config: Config) -> int:
    info_vitesse = info_vitesse_compteur(config)
    if args.json:
        import json

        def defaut(o):  # dates, Path
            return str(o)

        print(json.dumps(profil_json(config), default=defaut, ensure_ascii=False, indent=2))
        return 0
    print(f"Départ   : {config.depart.nom} ({config.depart.latitude:.4f}, {config.depart.longitude:.4f})")
    ftp_texte = f"{config.cycliste.ftp_w:.0f} W" if config.cycliste.ftp_w is not None else "non renseignée"
    print(f"Cycliste : {config.cycliste.masse_kg:.1f} kg, FTP {ftp_texte}")
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
    if config.cycliste.ftp_w is not None:
        watts_endurance = f"soit {config.seance.puissance_endurance_pct * config.cycliste.ftp_w:.0f} W"
    else:
        watts_endurance = "pas de watts (FTP non renseignée)"
    print(
        f"Zones    : position {config.seance.position_zone:.3f} dans la bande "
        f"({len(config.seance.zones_pct)} zones) → endurance "
        f"{config.seance.puissance_endurance_pct:.0%} de FTP, {watts_endurance}"
    )
    if info_vitesse is not None:
        mention = (
            "mesuré"
            if info_vitesse["facteur_mesure"]
            else "SUPPOSÉ, non mesuré — `ourouler calibrer` puis "
            "scripts/validation/facteur_compteur_retrospectif.py"
        )
        print(
            f"Vitesse  : {info_vitesse['puissance_endurance_w']:.0f} W → "
            f"{info_vitesse['vitesse_a_plat_kmh']:.1f} km/h à plat, moyenne compteur ≈ "
            f"{info_vitesse['moyenne_compteur_kmh']:.1f} km/h (vélo {info_vitesse['velo']}, "
            f"facteur {info_vitesse['facteur_compteur']:.3f}, {mention})"
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
    from ourouler.commandes.inventaire import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config)


def ajouter_meteo(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "meteo",
        help="pluie, vent et ressenti par direction et par heure",
        parents=[parent_json()],
    )
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : maintenant)")
    ajouter_adresse_depart(p)
    p.add_argument("--horizon", type=int, help="nombre d'heures (défaut : config)")
    p.add_argument("--distance", type=float, help="n'afficher qu'une couronne (km)")
    p.add_argument("--modele", help="modèle principal Open-Meteo (défaut : config)")
    p.add_argument("--second-avis", dest="second_avis", help="modèle de second avis (défaut : config)")
    p.set_defaults(fonction=_commande_meteo)


def _commande_meteo(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.meteo import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config, lieu_depart=lieu_depart(args, config))


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
        help="N, NE, … NO ou un azimut en degrés (défaut : candidates tout autour de l'horizon)",
    )
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : maintenant)")
    ajouter_adresse_depart(p)
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
    p.add_argument(
        "--vitesse-a-plat",
        type=float,
        metavar="KMH",
        help="au lieu de --puissance, pour qui ne connaît pas la sienne : la vitesse tenue "
        "à plat, sans vent, lancé — le modèle en déduit les watts",
    )
    p.add_argument(
        "--pause",
        action="append",
        metavar="KM:DUREE",
        help="un arrêt déclaré, répétable — par exemple 180:0h45 (45 min au km 180) ; "
        "la durée accepte 4h30, 45min ou 1:30 — décale l'heure de passage météo des "
        "échantillons suivants, jamais le temps en mouvement",
    )
    p.set_defaults(fonction=_commande_boucle)


def _commande_boucle(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.boucle import executer_depuis_namespace  # import paresseux

    # Avec `--gpx`, la boucle n'est pas générée : elle est lue dans le fichier,
    # qui porte son propre départ. Géocoder une adresse pour l'annoncer ensuite
    # comme point de départ du tracé serait faux. On refuse plutôt que d'ignorer
    # l'option en silence — un départ demandé et jeté sans un mot est
    # exactement la réponse fausse que ce lot cherche à éviter.
    if getattr(args, "adresse_depart", None) is not None and getattr(args, "gpx", None):
        raise ErreurUtilisateur(
            "--adresse-depart et --gpx ne vont pas ensemble : avec --gpx la boucle est lue "
            "dans le fichier, qui porte déjà son départ — rien n'est généré depuis une adresse"
        )
    # `avertir_routes` : `boucle` affiche une part de kilomètres déjà connus,
    # mesurée autour du départ configuré — partir d'ailleurs la fait tomber à
    # zéro pour une raison qui n'a rien à voir avec le tracé proposé.
    return executer_depuis_namespace(args, config, lieu_depart=lieu_depart(args, config, avertir_routes=True))


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
    from ourouler.commandes.routes import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config)


def ajouter_calibrer(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "calibrer",
        help="ajuste CdA et Crr d'un vélo sur les sorties réelles, et mesure l'erreur",
        parents=[parent_json()],
    )
    p.add_argument("--velo", help="nom du vélo (défaut : premier vélo d'usage route)")
    p.add_argument("--depuis", help="date AAAA-MM-JJ (défaut : historique_depuis de la config)")
    p.add_argument("--max", type=int, metavar="N", help="ne garder que les N sorties les plus récentes")
    p.add_argument(
        "--crr-libre",
        action="store_true",
        help="chercher le Crr avec le CdA, même quand le pneu ou la configuration le donnent "
        "(l'ancienne méthode, qui sépare mal les deux)",
    )
    p.set_defaults(fonction=_commande_calibrer)


def _commande_calibrer(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.physique import calibrer_depuis_namespace  # import paresseux

    return calibrer_depuis_namespace(args, config)


def ajouter_simuler(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "simuler",
        help="temps en mouvement d'un GPX à puissance constante, avec le modèle calibré",
        parents=[parent_json()],
    )
    p.add_argument("--gpx", metavar="FICHIER.GPX", required=True, help="le parcours à simuler")
    # Plus `required` : `--vitesse-a-plat` en est l'autre chemin, et argparse
    # ne sait pas dire « l'une ou l'autre » sans confondre les deux. Le refus,
    # quand aucune n'est donnée, est celui d'`executer_simuler`.
    p.add_argument("--puissance", type=float, metavar="W", help="puissance tenue")
    p.add_argument(
        "--vitesse-a-plat",
        type=float,
        metavar="KMH",
        help="au lieu de --puissance : la vitesse tenue à plat, sans vent, lancé — "
        "le modèle en déduit les watts",
    )
    p.add_argument("--velo", help="nom du vélo (défaut : premier vélo d'usage route)")
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (pour le vent prévu)")
    p.add_argument(
        "--pause",
        action="append",
        metavar="KM:DUREE",
        help="un arrêt déclaré, répétable — par exemple 180:0h45 (45 min au km 180) ; "
        "la durée accepte 4h30, 45min ou 1:30 — décale l'heure de passage météo des "
        "échantillons suivants, jamais le temps en mouvement simulé",
    )
    p.set_defaults(fonction=_commande_simuler)


def _commande_simuler(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.physique import simuler_depuis_namespace  # import paresseux

    return simuler_depuis_namespace(args, config)


def ajouter_analyser(sous: argparse._SubParsersAction) -> None:
    """Un parcours **déjà en main** (BRM, Flèche, boucle de club) : durée porte à porte
    en fourchette, météo par tronçon, heure d'arrivée — `ourouler simuler` retourné dans
    l'autre sens (voir la docstring d'`executer_analyser`)."""
    p = sous.add_parser(
        "analyser",
        help="météo et durée porte à porte d'un parcours déjà en main (brevet, boucle de club)",
        parents=[parent_json()],
    )
    p.add_argument("--gpx", metavar="FICHIER.GPX", required=True, help="le parcours à analyser")
    p.add_argument(
        "--puissance",
        type=float,
        metavar="W",
        help="puissance tenue (défaut : puissance d'endurance du profil, position_zone × FTP)",
    )
    p.add_argument(
        "--vitesse-a-plat",
        type=float,
        metavar="KMH",
        help="au lieu de --puissance : la vitesse tenue à plat, sans vent, lancé — "
        "le modèle en déduit les watts",
    )
    p.add_argument("--velo", help="nom du vélo (défaut : premier vélo d'usage route)")
    # Obligatoire ici (à la différence de `simuler`) : sans heure de départ,
    # rien à caler dans le temps — ni la météo par tronçon, ni l'arrivée.
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (obligatoire)")
    p.set_defaults(fonction=_commande_analyser)


def _commande_analyser(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.physique import analyser_depuis_namespace  # import paresseux

    return analyser_depuis_namespace(args, config)


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
    from ourouler.commandes.comparer import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config)


def ajouter_seance(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "seance",
        help="la séance planifiée du jour, étape par étape, avec la route que chaque bloc demande",
        parents=[parent_json()],
    )
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help="date de la séance (défaut : aujourd'hui)")
    p.add_argument(
        "--depuis",
        metavar="AAAA-MM-JJ",
        help="début d'une plage de jours (avec --jusqua ; exclusif de --jour)",
    )
    p.add_argument(
        "--jusqua",
        metavar="AAAA-MM-JJ",
        help="fin d'une plage de jours, incluse (avec --depuis)",
    )
    p.add_argument(
        "--fichier-seance",
        metavar="FICHIER",
        help="lit la séance dans un fichier .ZWO ou .MRC au lieu d'Intervals.icu "
        "(exclusif de --depuis/--jusqua ; --jour fixe alors le jour auquel elle est rattachée)",
    )
    p.set_defaults(fonction=_commande_seance)


def _commande_seance(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.seance import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config)


def ajouter_sortie(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "sortie",
        help="la séance du jour posée sur une boucle : tableau, GPX, tenue et carte HTML",
        parents=[parent_json()],
    )
    p.add_argument("--jour", metavar="AAAA-MM-JJ", help="date de la séance (défaut : aujourd'hui)")
    p.add_argument(
        "--fichier-seance",
        metavar="FICHIER",
        help="place les blocs d'une séance lue dans un .ZWO ou .MRC au lieu de celle d'Intervals.icu "
        "(--jour fixe alors le jour auquel elle est rattachée)",
    )
    p.add_argument(
        "--distance",
        type=float,
        metavar="KM",
        help="longueur de la boucle (défaut : la distance estimée de la séance, "
        "arrondie au multiple de 5 supérieur)",
    )
    p.add_argument(
        "--direction",
        help="N, NE, … NO ou un azimut en degrés (défaut : candidates tout autour de l'horizon). "
        "S'exclut de --vent : on choisit sa direction, ou on la laisse déduire du vent",
    )
    p.add_argument(
        "--candidates",
        type=int,
        help="nombre de boucles proposées, un point de départ (défaut : config) — le serveur "
        "l'élargit lui-même (8, puis 12) si moins de trois boucles distinctes en sortent",
    )
    # La question d'orientation au vent, posée **avant** la recherche.
    # « peu-importe » est le défaut **et une réponse valable** : elle
    # retombe sur les propositions contrastées. Ce n'est donc pas un réglage
    # de plus qu'il faudrait toucher — c'est un choix qui se fait en
    # regardant, et dont l'absence de réponse est une réponse.
    #
    # `--vent` et `--direction` fixent tous deux l'azimut de recherche : ils
    # s'excluent (décision Q44), et l'aide
    # le dit des deux côtés plutôt que de laisser découvrir le refus.
    p.add_argument(
        "--vent",
        choices=list(CHOIX_VENT),
        help="orientation au vent voulue, au lieu de --direction : retour-dos (rentrer avec), "
        "depart-dos (partir avec), travers — qui ouvre les deux flancs, donc deux directions "
        "opposées — ou peu-importe (défaut, les propositions contrastées répondent)",
    )
    p.add_argument("--velo", help="vélo dont la calibration sert au placement (défaut : premier vélo route)")
    ajouter_heure_depart(p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : le jour de la séance)")
    ajouter_adresse_depart(p)
    p.add_argument("--sortie", metavar="FICHIER.GPX", help="où écrire la boucle retenue")
    p.add_argument("--carte", metavar="FICHIER.HTML", help="où écrire la carte de vérification")
    p.add_argument("--profil", help="profil BRouter (défaut : config)")
    p.add_argument(
        "--ecraser",
        action="store_true",
        help="remplacer les fichiers de --sortie et --carte s'ils existent déjà",
    )
    p.add_argument(
        "--carte-sans-seance",
        action="store_true",
        help="écrire quand même la page (« rien de prévu ») à l'emplacement de --carte "
        "s'il n'y a aucune séance ce jour-là — pour un service planifié, où pas de page "
        "vaut moins bien que le dire",
    )
    p.set_defaults(fonction=_commande_sortie)


def _commande_sortie(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.sortie import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config, lieu_depart=lieu_depart(args, config, avertir_routes=True))


def ajouter_geocoder(sous: argparse._SubParsersAction) -> None:
    """`ourouler geocoder ADRESSE` — le géocodage nu, qui ne tranche jamais.

    Une adresse tapée devient des candidats notés, tous rendus. Cette
    commande reste le seul endroit qui montre la **liste** : c'est elle qu'on
    consulte quand `--adresse-depart` a retenu le premier candidat et qu'on
    veut voir les autres, et c'est sa forme JSON que la route de géocodage de
    l'API reprendra pour faire choisir le front (voir `lieu_depart`).
    """
    p = sous.add_parser(
        "geocoder",
        help="convertit une adresse tapée en coordonnées, plusieurs candidats notés",
        parents=[parent_json()],
    )
    p.add_argument("adresse", help="adresse à chercher (entre guillemets si elle contient des espaces)")
    p.add_argument(
        "--max", type=int, metavar="N", help=f"nombre maximal de candidats (défaut : {LIMITE_DEFAUT})"
    )
    p.set_defaults(fonction=_commande_geocoder)


def _commande_geocoder(args: argparse.Namespace, config: Config) -> int:
    from ourouler.commandes.geocoder import executer_depuis_namespace  # import paresseux

    return executer_depuis_namespace(args, config)


def ajouter_api(sous: argparse._SubParsersAction) -> None:
    """`ourouler api` — sert l'API que le front consomme.

    Le cadre web est un extra (`uv sync --extra api`) : la sous-commande le
    dit en une ligne s'il manque, plutôt que de lever une trace d'import.
    """
    p = sous.add_parser(
        "api",
        help="sert l'API HTTP que le front consomme (nécessite `uv sync --extra api`)",
    )
    p.add_argument("--hote", default="127.0.0.1", help="adresse d'écoute (défaut : 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="port d'écoute (défaut : 8000)")
    p.set_defaults(fonction=_commande_api)


def _commande_api(args: argparse.Namespace, config: Config) -> int:
    try:
        import uvicorn

        from ourouler.api.application import NOM_DOSSIER_DONNEES, creer_application
        from ourouler.api.exploitation import chemin_config
        from ourouler.api.session import SessionPersonnelle
    except ImportError as e:
        raise ErreurUtilisateur(
            f"api : FastAPI et uvicorn ne sont pas installés — `uv sync --extra api` ({e})"
        ) from e

    application = creer_application(
        # Le même fichier que celui que `main()` vient de charger :
        # `--config`, sinon `OUROULER_CONFIG`, sinon le défaut local.
        chemin_config=(args.config or chemin_config()).expanduser(),
        dossier_donnees=config.cache.dossier / NOM_DOSSIER_DONNEES,
        # **Le mode personnel, dit et non deviné.** `ourouler api`
        # tourne sur la machine de son utilisateur : il n'y a qu'un cycliste,
        # la machine est la frontière, et le propriétaire est toujours le
        # même. C'est un service exposé — `application()`, la fabrique lue par
        # uvicorn — qui refuse par défaut, pas celui-ci.
        session=SessionPersonnelle(),
    )
    print(
        f"ourouler : API sur http://{args.hote}:{args.port}/api/v1 (documentation interactive sur /docs)",
        file=sys.stderr,
    )
    uvicorn.run(application, host=args.hote, port=args.port, log_level="info")
    return 0

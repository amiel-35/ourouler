"""Ligne de commande `ourouler`.

Seule couche autorisée (avec `config.py`) à lire un fichier de configuration.
Chaque sous-commande est déclarée par une fonction `ajouter_<nom>` qui
importe son module paresseusement : une sous-commande absente ou cassée ne
doit pas empêcher les autres de tourner.
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ourouler import __version__
from ourouler.config import CHEMIN_CONFIG_DEFAUT, Config, Depart, charger, en_dict_public
from ourouler.connecteurs.geocodage import (
    LIMITE_DEFAUT,
    Candidat,
    ClientBAN,
    ClientNominatim,
    ambiguite,
    chercher_adresse,
)
from ourouler.erreurs import ErreurUtilisateur

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
    ajouter_comparer(sous)
    ajouter_seance(sous)
    ajouter_sortie(sous)
    ajouter_geocoder(sous)
    ajouter_api(sous)
    ajouter_inviter(sous)
    ajouter_invitations(sous)
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
#: `--heure-depart` et le lieu de départ s'appelle `--adresse-depart` (livré
#: par le lot F0.7). `--depart` seul était ambigu dès que le lieu existerait ;
#: `--heure` avait été ajouté en attendant la décision.
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


def ajouter_adresse_depart(p: argparse.ArgumentParser) -> None:
    """Ajoute `--adresse-depart` : partir d'ailleurs **cette fois**, sans rien réécrire.

    Le nom est celui que Q15 avait réservé, et il est long exprès : `--depart`
    disait « heure », `--adresse-depart` dit « lieu ». Les deux options
    cohabitent sur la même ligne de commande sans se marcher dessus, elles
    n'écrivent pas dans le même `dest` (`depart` pour l'heure,
    `adresse_depart` pour le lieu).
    """
    p.add_argument(
        "--adresse-depart",
        dest="adresse_depart",
        metavar="ADRESSE",
        help="partir d'une autre adresse que celle de la configuration, cette fois seulement "
        "(géocodée ; la configuration n'est pas modifiée). Ne pas confondre avec "
        "--heure-depart, qui est une heure.",
    )


#: Mention exigée par la licence ODbL quand un résultat Nominatim est affiché
#: (politique d'usage du service, voir la docstring du connecteur).
ATTRIBUTION_NOMINATIM = "© contributeurs OpenStreetMap"


def lieu_depart(
    args: argparse.Namespace,
    config: Config,
    *,
    ban: ClientBAN | None = None,
    nominatim: ClientNominatim | None = None,
    avertir_routes: bool = False,
    flux: object = None,
) -> Depart:
    """Le point de départ de cette exécution : `--adresse-depart` géocodée, ou la configuration.

    C'est **ici**, dans `cli.py`, que l'adresse devient un `Depart` : le cœur
    ne géocode rien et ne connaît aucune adresse (règle absolue 2). Les deux
    clients sont injectables pour que les tests ne touchent jamais le réseau.

    **Une adresse ambiguë est la normale, pas l'exception**, et le connecteur
    (F0.2) ne tranche jamais : il rend une liste ordonnée. Une ligne de
    commande, elle, doit bien partir de quelque part — elle ne peut pas rendre
    une liste à qui a tapé `ourouler boucle --adresse-depart "…"`.

    **Décision du mainteneur sur Q34, le 17/09/2026 : « on refuse ».** Une
    adresse ambiguë n'est plus tranchée au hasard, elle est **refusée**, avec
    ses candidats affichés pour que l'utilisateur précise et relance. C'est en
    ligne de commande que ce refus a le plus de sens : personne n'y confirme un
    point sur une carte, et le seul échec qui coûte cher est de rouler depuis
    un point qu'on croyait être un autre.

    **Ce qu'« ambigu » veut dire ici, et ce qu'il ne veut pas dire.** Pas un
    écart de score : la mesure du 17/09/2026 sur la vraie BAN montre que
    l'écart entre les deux premiers candidats vaut 0,0020 quand la réponse est
    juste et 0,0016 à 0,0024 quand elle est arbitraire — aucun seuil ne les
    sépare. C'est `geocodage.ambiguite()` qui décide, sur la **commune** :
    plusieurs communes en présence, ou pas de commune du tout, et l'on refuse.
    Le raisonnement complet et les quinze requêtes qui le fondent sont dans sa
    docstring.

    Ce qui n'est **pas** ambigu, et reste donc tranché sans un mot de plus :
    plusieurs candidats dans la même commune. La BAN en rend presque toujours
    plusieurs (le numéro voisin, la rue sans numéro), et deux numéros de la
    même rue ne changent pas où l'on part à vélo. Le premier est retenu et
    annoncé en toutes lettres sur la sortie d'erreur avant tout appel coûteux ;
    `ourouler geocoder` montre la liste complète.

    **Ce que l'API fait, et qui est l'inverse.** Une requête d'API n'a
    pas de sortie d'erreur que quelqu'un lise, et le front, lui, *peut*
    montrer une liste, et une carte, et demander la commune dans un champ à
    part. L'API expose donc le géocodage comme une route à part (la forme de
    `ourouler geocoder --json`, écrite pour ça), rend **tous** les candidats au
    front avec leur score, leur source **et leur commune**, et les routes de
    parcours reçoivent ensuite des **coordonnées déjà tranchées** — jamais une
    adresse à géocoder au vol. Là où la CLI refuse, l'API ne refuse pas et fait
    choisir sur une carte : deux façons de tenir la même décision, chacune avec
    ce que sa surface permet.

    Une adresse introuvable lève `ErreurUtilisateur` — affichée en une ligne,
    code de sortie 2, aucune trace Python. Elle ne retombe **jamais** sur le
    départ configuré : rendre une boucle autour de la maison à qui a demandé
    une autre ville serait une réponse fausse, ce qui est pire qu'une erreur.

    **Ordre assumé** : le géocodage a lieu **avant** que la sous-commande
    valide ses autres options, donc `boucle --adresse-depart X --distance -5`
    interroge le géocodeur avant de refuser la distance. Les commandes tiennent
    par ailleurs à refuser une option fautive avant tout appel réseau, et cette
    ligne y déroge : c'est un appel unique, sans clé et gratuit, contre la
    complication qu'il faudrait pour le repousser après une validation qui vit
    dans le cœur. Le contrat vaut pour BRouter, Open-Meteo et Intervals — les
    postes qui coûtent — et il est intact.
    """
    adresse = getattr(args, "adresse_depart", None)
    if adresse is None:
        return config.depart
    if not adresse.strip():
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : valeur vide, attendu une adresse — "
            "omettre l'option pour partir du point de la configuration"
        )

    candidats = chercher_adresse(adresse, ban=ban, nominatim=nominatim, limite=LIMITE_DEFAUT)
    if not candidats:
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : aucune adresse trouvée — préciser la commune "
            "ou le code postal, `ourouler geocoder` montre ce que les services rendent. "
            f"Le départ de la configuration ({config.depart.nom}) n'a pas servi à la place."
        )

    flux = flux if flux is not None else sys.stderr

    trouble = ambiguite(candidats)
    if trouble is not None:
        # Les candidats d'abord, l'erreur ensuite : c'est la liste qui permet
        # de préciser, et `ErreurUtilisateur` s'affiche en une seule ligne.
        print(
            f"ourouler : candidats pour « {adresse} » — {trouble.phrase} :",
            file=flux,
        )
        for i, c in enumerate(candidats, start=1):
            print(f"  {i}. {_ligne_candidat(c)}", file=flux)
        raise ErreurUtilisateur(
            f"--adresse-depart {adresse!r} : adresse ambiguë, rien n'est retenu — "
            "réécrire l'adresse avec sa commune et son code postal, puis relancer. "
            f"Le départ de la configuration ({config.depart.nom}) n'a pas servi à la place."
        )

    retenu = candidats[0]
    ligne = (
        f"ourouler : départ « {retenu.label} » ({retenu.latitude:.5f}, {retenu.longitude:.5f}), "
        f"source {retenu.source}, score {retenu.score:.2f}"
    )
    if len(candidats) > 1:
        ligne += (
            f" — {len(candidats) - 1} autre(s) candidat(s) écarté(s) ; "
            f'`ourouler geocoder "{adresse}"` les montre tous'
        )
    if retenu.source == "nominatim":
        ligne += f" [{ATTRIBUTION_NOMINATIM}]"
    print(ligne, file=flux)

    if avertir_routes and _routes_connues_existent(config):
        print(
            "ourouler : les routes connues et les poids appris ont été mesurés autour du "
            "départ de la configuration — loin de là, « connu % » tombe à zéro sans que le "
            "tracé soit pour autant inédit (la part connue n'entre dans aucun score).",
            file=flux,
        )

    return Depart(nom=retenu.label, latitude=retenu.latitude, longitude=retenu.longitude)


def _ligne_candidat(candidat: Candidat) -> str:
    """Un candidat sur une ligne, commune en évidence — c'est elle qui les distingue."""
    ou = candidat.commune or "commune inconnue"
    if candidat.code_postal:
        ou += f" {candidat.code_postal}"
    return (
        f"{candidat.label} — {ou} — {candidat.latitude:.5f}, {candidat.longitude:.5f} "
        f"(score {candidat.score:.4f}, {candidat.source})"
    )


def _routes_connues_existent(config: Config) -> bool:
    """Vrai si le cache porte déjà une base de routes apprises. Lecture de fichier : `cli.py` a le droit."""
    from ourouler.apprentissage.commande import NOM_BASE

    try:
        return (config.cache.dossier / NOM_BASE).exists()
    except OSError:
        return False


def ajouter_config(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "config",
        help="vérifie et affiche la configuration chargée",
        parents=[parent_json()],
    )
    p.set_defaults(fonction=_commande_config)


def profil_json(config: Config) -> dict:
    """La configuration en JSON, **clé et mot de passe masqués**.

    C'est la forme que rend `ourouler config --json`, et c'est donc le profil
    que l'API sert au front (lot F1) : une seule fonction, un seul contrat,
    et le masquage des secrets fait au même endroit pour les deux.
    """
    # Masquage des secrets et propriétés dérivées : `config.en_dict_public`,
    # partagée avec l'API plutôt que recopiée ici. Un masquage qu'on réécrit
    # est un masquage qu'on oublie.
    d = en_dict_public(config)
    # Troisième valeur de l'écran de FTP (F1, comble C2 de
    # docs/ux/relecture_f0.md) : `None` si la config ne porte aucun vélo.
    d["seance"]["vitesse_compteur"] = _info_vitesse_compteur(config)
    return d


def _commande_config(args: argparse.Namespace, config: Config) -> int:
    info_vitesse = _info_vitesse_compteur(config)
    if args.json:
        import json

        def defaut(o):  # dates, Path
            return str(o)

        print(json.dumps(profil_json(config), default=defaut, ensure_ascii=False, indent=2))
        return 0
    print(f"Départ   : {config.depart.nom} ({config.depart.latitude:.4f}, {config.depart.longitude:.4f})")
    ftp_texte = (
        f"{config.cycliste.ftp_w:.0f} W" if config.cycliste.ftp_w is not None else "non renseignée"
    )
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
            "tests/validation/facteur_compteur_retrospectif.py"
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


def _info_vitesse_compteur(config: Config) -> dict | None:
    """La troisième valeur de l'écran de FTP — **déléguée**, jamais recalculée.

    Relecture de F1, point 8 : ces trois valeurs avaient deux implémentations,
    celle-ci et `seance.ecran_ftp.valeurs_liees`, servies par deux routes
    différentes de la même API. Elles s'accordaient, avec des noms de champs
    différents — une dette accidentelle, pas assumée. Il n'en reste qu'une.

    Ce qui est conservé ici : le **sous-ensemble** de champs que
    `ourouler config --json` publiait déjà, pour ne pas élargir son contrat
    au passage. `GET /profil/zones` sert la forme complète.

    `None` si la configuration ne porte aucun vélo : rien à calculer, et
    `ourouler config` doit rester utilisable sans vélo déclaré.
    """
    from ourouler.seance.ecran_ftp import valeurs_liees

    completes = valeurs_liees(config)
    if completes is None:
        return None
    gardes = (
        "velo",
        "puissance_endurance_w",
        "vitesse_a_plat_kmh",
        "moyenne_compteur_kmh",
        "facteur_compteur",
        # Décision 8 : mesuré sur l'historique, ou dérivé d'une sortie de
        # référence supposée. Tout écran qui l'affiche doit le dire.
        "facteur_mesure",
    )
    return {cle: completes[cle] for cle in gardes}


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
    ajouter_adresse_depart(p)
    p.add_argument("--horizon", type=int, help="nombre d'heures (défaut : config)")
    p.add_argument("--distance", type=float, help="n'afficher qu'une couronne (km)")
    p.add_argument("--modele", help="modèle principal Open-Meteo (défaut : config)")
    p.add_argument("--second-avis", dest="second_avis", help="modèle de second avis (défaut : config)")
    p.set_defaults(fonction=_commande_meteo)


def _commande_meteo(args: argparse.Namespace, config: Config) -> int:
    from ourouler.meteo.commande import executer  # import paresseux (lot L1.5)

    return executer(args, config, lieu_depart=lieu_depart(args, config))


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
    from ourouler.boucle.commande import executer  # import paresseux (lot L2.6)

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
    return executer(args, config, lieu_depart=lieu_depart(args, config, avertir_routes=True))


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
    p.add_argument("--candidates", type=int, help="nombre de boucles proposées (défaut : config)")
    # La question d'orientation au vent, posée **avant** la recherche (lot
    # L5.3). « peu-importe » est le défaut **et une réponse valable** : elle
    # retombe sur les propositions contrastées. Ce n'est donc pas un réglage
    # de plus qu'il faudrait toucher — c'est un choix qui se fait en
    # regardant, et dont l'absence de réponse est une réponse.
    #
    # Q44 : `--vent` et `--direction` fixaient tous deux l'azimut de recherche
    # sans que rien ne dise lequel gagnait. Ils s'excluent désormais, et l'aide
    # le dit des deux côtés plutôt que de laisser découvrir le refus.
    p.add_argument(
        "--vent",
        choices=list(CHOIX_VENT),
        help="orientation au vent voulue, au lieu de --direction : retour-dos (rentrer avec), "
        "depart-dos (partir avec), travers — qui ouvre les deux flancs, donc deux directions "
        "opposées — ou peu-importe (défaut, les propositions contrastées répondent)",
    )
    p.add_argument("--velo", help="vélo dont la calibration sert au placement (défaut : premier vélo route)")
    ajouter_heure_depart(
        p, "heure de départ HH:MM ou AAAA-MM-JJTHH:MM (défaut : le jour de la séance)"
    )
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
    from ourouler.sortie.commande import executer  # import paresseux (lot L4.4)

    return executer(args, config, lieu_depart=lieu_depart(args, config, avertir_routes=True))


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
    from ourouler.geocodage.commande import executer  # import paresseux (lot F0.2)

    return executer(args, config)


def ajouter_api(sous: argparse._SubParsersAction) -> None:
    """`ourouler api` — sert l'API que le front consomme (lot F1).

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
        from ourouler.api.session import SessionPersonnelle
    except ImportError as e:
        raise ErreurUtilisateur(
            "api : FastAPI et uvicorn ne sont pas installés — `uv sync --extra api` "
            f"({e})"
        ) from e

    application = creer_application(
        chemin_config=(args.config or CHEMIN_CONFIG_DEFAUT).expanduser(),
        dossier_donnees=config.cache.dossier / NOM_DOSSIER_DONNEES,
        # **Le mode personnel, dit et non deviné** (lot L7.A). `ourouler api`
        # tourne sur la machine de son utilisateur : il n'y a qu'un cycliste,
        # la machine est la frontière, et le propriétaire est toujours le
        # même. C'est un service exposé — `application()`, la fabrique lue par
        # uvicorn — qui refuse par défaut, pas celui-ci.
        session=SessionPersonnelle(),
    )
    print(
        f"ourouler : API sur http://{args.hote}:{args.port}/api/v1 "
        f"(documentation interactive sur /docs)",
        file=sys.stderr,
    )
    uvicorn.run(application, host=args.hote, port=args.port, log_level="info")
    return 0


# --- inviter (lot L7.2-B) -----------------------------------------------------
#
# « C'est pas une banque » : cette commande fait tourner le socle des comptes
# (lot L7.2-A, `api/comptes.py`) depuis la ligne de commande du mainteneur —
# c'est lui, et lui seul aujourd'hui, qui invite. Elle a besoin de trois
# choses que seul `cli.py` a le droit de lire (règle absolue 2) : l'URL de la
# base PostgreSQL de l'hébergé, l'URL publique devant laquelle le lien
# s'ouvre, et — sauf `--sans-courriel` — les secrets du relais SMTP. Le reste
# (composer et envoyer le courriel, afficher le résultat) est délégué à
# `api/invitation_commande.py` et `api/courriel.py`, qui ne lisent rien
# eux-mêmes : `tests/test_invariants.py` le vérifie.

#: Où vivent les secrets du *service* (Brevo…), distincts du profil cycliste
#: de `config.toml` — voir `service.example.toml`. Même statut que
#: `CHEMIN_CONFIG_DEFAUT` : un défaut, réglable par test.
CHEMIN_SERVICE_DEFAUT = Path("~/.config/ourouler/service.toml")

#: La variable qui déplace ce fichier, pour un déploiement où « chez soi »
#: n'existe pas. Le conteneur n'a pas de `~` qui veuille dire quelque chose :
#: `deploiement/api/entrypoint.py` y écrit le fichier depuis
#: `OUROULER_SERVICE_TOML_B64` et pose cette variable-ci pour dire où.
VARIABLE_SERVICE = "OUROULER_SERVICE"

#: L'URL publique du front hébergé, devant laquelle `/entrer?jeton=...`
#: s'ouvre — une donnée de déploiement, au même titre que celles que
#: `api/exploitation.py` lit pour le processus de l'API (`OUROULER_DATABASE_URL`,
#: `OUROULER_MODE`…). Celle-ci n'appartient pas au processus serveur : c'est le
#: mainteneur, depuis sa propre ligne de commande, qui la pose dans son
#: environnement le temps d'inviter quelqu'un.
VARIABLE_URL_PUBLIQUE = "OUROULER_URL_PUBLIQUE"


def ajouter_inviter(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "inviter",
        help="invite une adresse à rejoindre où rouler (compte hébergé + courriel)",
        parents=[parent_json()],
    )
    p.add_argument("adresse", help="adresse e-mail à inviter")
    p.add_argument(
        "--sans-courriel",
        dest="sans_courriel",
        action="store_true",
        help="n'envoie pas le courriel d'invitation, affiche seulement le lien",
    )
    p.set_defaults(fonction=_commande_inviter)


def _commande_inviter(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes
    from ourouler.api.courriel import parametres_brevo_depuis_dict
    from ourouler.api.invitation_commande import executer_inviter

    url_db = _url_des_comptes("inviter")
    url_pub = _url_publique()

    parametres_brevo = None
    if not getattr(args, "sans_courriel", False):
        parametres_brevo = parametres_brevo_depuis_dict(_charger_service())

    with _base_des_comptes("inviter", url_db) as connexion:
        depot = DepotComptes(connexion)
        return executer_inviter(
            args, config, depot=depot, url_publique=url_pub, parametres_brevo=parametres_brevo
        )


def ajouter_invitations(sous: argparse._SubParsersAction) -> None:
    p = sous.add_parser(
        "invitations",
        help="liste les invitations en cours : adresse, lien, échéance",
        parents=[parent_json()],
    )
    p.set_defaults(fonction=_commande_invitations)


def _commande_invitations(args: argparse.Namespace, config: Config) -> int:
    from ourouler.api.comptes import DepotComptes
    from ourouler.api.invitation_commande import executer_invitations

    url_db = _url_des_comptes("invitations")
    url_pub = _url_publique()

    with _base_des_comptes("invitations", url_db) as connexion:
        depot = DepotComptes(connexion)
        return executer_invitations(args, config, depot=depot, url_publique=url_pub)


def _url_des_comptes(commande: str) -> str:
    """L'URL de la base des comptes, ou un refus qui nomme la variable.

    Séparée de `_base_des_comptes` pour que l'ordre des refus reste celui du
    besoin : sans base, rien ne se fait — c'est ce qui se dit en premier,
    avant l'URL publique, qui ne sert qu'à fabriquer un lien.
    """
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL, url_base_de_donnees

    url = url_base_de_donnees()
    if url is None:
        raise ErreurUtilisateur(
            f"{commande} : {VARIABLE_DATABASE_URL} n'est pas défini — impossible de joindre "
            "la base des comptes de l'hébergé"
        )
    return url


@contextmanager
def _base_des_comptes(commande: str, url_db: str) -> Iterator[Any]:
    """Une connexion à la base des comptes, **déjà migrée**, ou un refus lisible.

    Trois choses qu'aucun test n'avait attrapées, et qu'un premier vrai
    lancement a trouvées en trois secondes (19/09/2026, règle absolue 4) :

    1. **Personne n'appliquait les migrations.** Les tests partent d'une base
       que leur `conftest` a migrée ; la vraie vie part d'une base vide, et la
       commande mourait sur `relation "comptes" does not exist`. Les
       migrations sont idempotentes (`appliquer_migrations` rend la liste de
       ce qu'elle a fait, vide quand il n'y avait rien à faire) : les poser
       ici coûte quelques millisecondes et supprime une étape à retenir.
    2. **La trace du pilote remontait jusqu'au mainteneur.** Une base
       injoignable, un mot de passe faux ou un serveur arrêté donnaient une
       pile `psycopg`, pas une phrase.
    3. Et le nom de la commande manquait aux messages, alors qu'il était déjà
       là dans le refus de la variable d'environnement.

    Ce qui est appliqué est **dit** : une migration qui passe en silence est
    une migration dont on découvre l'existence le jour où elle a mal tourné.
    """
    from ourouler.api.base_de_donnees import appliquer_migrations, ouvrir
    from ourouler.api.exploitation import VARIABLE_DATABASE_URL

    try:
        connexion = ouvrir(url_db)
    except Exception as e:  # noqa: BLE001 - psycopg lève une famille entière, toutes traitées pareil
        raise ErreurUtilisateur(
            f"{commande} : base des comptes injoignable ({_premiere_ligne(e)}) — vérifier "
            f"{VARIABLE_DATABASE_URL}, et que le serveur PostgreSQL est démarré"
        ) from e
    try:
        with connexion:
            posees = appliquer_migrations(connexion)
            if posees:
                print(f"base des comptes : {len(posees)} migration(s) appliquée(s)", file=sys.stderr)
            yield connexion
    except ErreurUtilisateur:
        raise
    except Exception as e:  # noqa: BLE001 - idem : une phrase plutôt qu'une pile
        raise ErreurUtilisateur(f"{commande} : {_premiere_ligne(e)}") from e


def _premiere_ligne(e: Exception) -> str:
    """Le message d'une exception de pilote, sans sa pile ni son curseur SQL."""
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


def _url_publique(environ: Mapping[str, str] | None = None) -> str:
    """L'URL publique du front hébergé, ou `ErreurUtilisateur` si elle n'est pas posée.

    Même forme que les lecteurs de variable d'`api/exploitation.py` : une variable,
    dépouillée, ou un refus qui nomme la variable plutôt qu'un lien vide silencieusement
    construit (`https:///entrer?jeton=...` ne mènerait nulle part).
    """
    environ = os.environ if environ is None else environ
    brut = (environ.get(VARIABLE_URL_PUBLIQUE) or "").strip()
    if not brut:
        raise ErreurUtilisateur(
            f"inviter : {VARIABLE_URL_PUBLIQUE} n'est pas défini — c'est l'URL publique du "
            "front hébergé, devant laquelle /entrer?jeton=... s'ouvre"
        )
    return brut


def _charger_service(chemin: Path | None = None) -> dict:
    """Le contenu de `service.toml`, lu ici et nulle part ailleurs (règle absolue 2).

    `chemin` est injectable pour les tests — jamais un vrai `service.toml` n'est lu ou
    montré par ce lot (le brief l'interdit explicitement) : les tests lui passent un
    fichier à eux, en `.invalid`, jamais celui du mainteneur.
    """
    chemin = (chemin or Path(os.environ.get(VARIABLE_SERVICE) or CHEMIN_SERVICE_DEFAUT)).expanduser()
    if not chemin.is_file():
        raise ErreurUtilisateur(
            f"inviter : fichier de service introuvable : {chemin} — copier "
            "service.example.toml et le renseigner"
        )
    try:
        with chemin.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ErreurUtilisateur(f"{chemin} : TOML invalide ({e})") from e


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

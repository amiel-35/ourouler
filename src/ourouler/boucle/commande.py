"""Sous-commande `ourouler boucle` : candidates → coûts → météo → tableau → GPX.

Ce module est appelé par `cli.py` et ne lit rien de l'environnement : il
reçoit `args` et `config`, et les deux clients (BRouter, Open-Meteo) sont
injectables pour que les tests ne touchent jamais le réseau.

L'enchaînement est celui du contrat de sprint §6 :

1. `boucle.candidates.generer` demande au moteur plusieurs boucles autour de
   la direction voulue (lot L2.3) ;
2. `boucle.couts.evaluer` mesure trafic, revêtement, virages et sens (L2.4) ;
3. `boucle.meteo_trace.evaluer` regarde la pluie et le vent **à l'heure de
   passage** sur chaque tronçon (L2.5) ;
4. le tableau est trié par `score + pluie_cumulee_mm × 2` — les kilomètres
   équivalents du score et les millimètres de pluie ne sont pas la même
   grandeur, ce poids est un arbitrage assumé, pas une mesure ;
5. la meilleure est écrite en GPX.

Avec `--gpx`, les étapes 1 et 5 sautent : on évalue le fichier importé seul.

La météo est le seul maillon qu'on accepte de perdre : si Open-Meteo ne
répond pas, le tableau s'affiche sans ses colonnes et un avertissement part
sur la sortie d'erreur. Perdre la boucle parce qu'il manque la pluie serait
absurde ; l'inverse (afficher une pluie inventée) est interdit par la règle
absolue 5.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes, lire_poids
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.gpx import ecrire_gpx, lire_gpx_trace
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.boucle.trace import Trace
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConfig, ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.couronne import NOMS_DIRECTIONS, NOMS_DIRECTIONS_16, azimut_de
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import date_en_francais

#: Poids de la pluie dans le tri du tableau : un millimètre cumulé coûte
#: autant que deux kilomètres équivalents de score (contrat §6).
POIDS_PLUIE_TRI = 2.0

#: Marque de la ligne retenue dans le tableau texte.
MARQUE_RETENUE = "→"

#: Mention accolée au titre de la colonne « temps » quand il vient du modèle.
MENTION_MODELE = "(modèle)"

#: Part de kilomètres non classés au-delà de laquelle le tableau le dit. En
#: dessous, c'est le bruit habituel des tronçons de raccordement ; au-delà,
#: « 0,0 km de trafic » ne veut plus dire « tracé calme ».
PART_NON_CLASSE_SIGNALEE = 0.05

#: Les deux libellés de la colonne des antennes. Ils ne disent pas la même
#: chose : une candidate générée est **élaguée**, le tableau compte donc les
#: mètres qu'on lui a retirés et le tracé proposé n'en a plus ; un GPX importé
#: n'est pas touché, le tableau compte les mètres qui y sont **encore**.
#: Afficher le même mot pour les deux ferait croire à un élagage qui n'a pas
#: eu lieu (règle absolue 5).
TITRE_ANTENNES_RETIREES = "antennes retirées"
TITRE_ANTENNES_DETECTEES = "antennes détectées"

#: Part de la FTP tenue par défaut pour le temps estimé par le modèle. C'est
#: un **choix**, pas une mesure : le contrat de sprint donne la colonne
#: « temps estimé » sans dire à quelle puissance la calculer. 65 % de la FTP
#: est une allure d'endurance plausible ; `--puissance` la remplace, et
#: l'en-tête dit toujours laquelle a servi.
#:
#: Q8, close le 13/09/2026 : tant que la séance du jour n'est pas connue,
#: `boucle` affiche une durée à l'allure Z2. Au sprint 4, `sortie` simulera
#: la boucle bloc par bloc à partir de la séance Intervals, et la durée sera
#: celle de la séance sur ce terrain — ce défaut n'aura plus à servir.
PART_FTP_DEFAUT = 0.65

#: Ce qu'on affiche à la place d'une mesure absente (jamais un zéro : un
#: GPX importé ne dit rien des routes empruntées, ce n'est pas « 0 km de
#: trafic »).
ABSENT = "—"


@dataclass(frozen=True)
class Demande:
    """Ce que l'utilisateur a demandé, une fois validé — avant tout appel réseau."""

    gpx: Path | None
    distance_km: float | None
    direction: str  # libellé normalisé, sert au nom du fichier de sortie
    azimut_deg: float | None
    nb_candidates: int
    profil: str
    depart: datetime
    sortie: Path | None
    ecraser: bool = False


@dataclass(frozen=True)
class ModeleTemps:
    """De quoi calculer un temps estimé par le modèle physique, si on en a un."""

    parametres: object  # ourouler.physique.modele.Parametres (import paresseux)
    puissance_w: float
    velo: str
    provenance: str  # « calibration », « configuration » ou « défaut »


@dataclass
class Evaluation:
    """Une candidate mesurée : son tracé, ses coûts, sa météo, son total de tri."""

    numero: int
    trace: Trace
    couts: Couts
    meteo: MeteoTrace | None
    ecart_relatif: float | None
    azimut_deg: float | None
    rayon_m: float | None
    total: float
    #: Part des kilomètres déjà roulés, entre 0 et 1, ou `None` si aucune base
    #: de routes connues n'existe. **Informative** : elle n'entre dans aucun
    #: score (contrat du sprint 3 §2 — « inconnu » n'est jamais un malus).
    part_connue: float | None = None
    temps_s: float | None = None
    """Temps **en mouvement** rendu par le modèle physique calibré, ou `None`
    si aucun modèle n'était disponible — la colonne retombe alors sur la
    vitesse moyenne de la configuration."""
    vitesse_meteo_kmh: float | None = None
    """Vitesse qui a daté les heures de passage météo sur ce tracé. Elle vient
    du modèle quand il existe, de la configuration sinon ; l'entête la dit,
    sans quoi deux exécutions interrogeraient la prévision à deux heures
    différentes sans que rien ne l'explique."""


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
) -> int:
    """Exécute `ourouler boucle`. Renvoie le code de sortie (0 = succès)."""
    demande = lire_options(args, config)

    if demande.gpx is not None:
        traces = [(lire_gpx_trace(demande.gpx), None, None)]
    else:
        client_brouter = (
            client_brouter
            if client_brouter is not None
            # Les zones à éviter sont passées au client, pas lues par lui :
            # le cœur ne connaît pas la configuration, il la reçoit.
            else ClientBrouter(config.brouter, evitements=config.evitements)
        )
        trouvees = generer(
            client_brouter,
            config.depart,
            distance_km=demande.distance_km,
            azimut_deg=demande.azimut_deg,
            nb=demande.nb_candidates,
            tolerance=config.boucle.tolerance_distance,
            profil=demande.profil,
            # Le plafond d'appels suit le nombre de candidates demandées :
            # sinon, cinq directions demandées face à un moteur qui n'arrive
            # pas à la distance voulue en rendaient trois, sans rien en dire.
            appels_max=appels_pour(demande.nb_candidates),
        )
        if not trouvees:
            raise ErreurConnecteur(
                f"boucle : aucune boucle bornée trouvée autour de {demande.direction} "
                f"pour {demande.distance_km:g} km (profil {demande.profil}) — "
                "essayer une autre direction, une autre distance ou un autre profil"
            )
        traces = [(c.trace, c.ecart_relatif, c) for c in trouvees]

    # Les trois fichiers appris ou calibrés (L3.2, L3.3) sont lus **ici** et
    # passés au cœur en objets : `couts.evaluer` ne connaît pas de chemin,
    # `BaseRoutes` reçoit le sien et le modèle physique reçoit ses
    # `Parametres`. Absents, on retombe sur les poids par défaut, la colonne
    # « connu % » disparaît — elle n'a jamais pesé sur le tri de toute façon —
    # et le temps revient à la vitesse moyenne de la configuration.
    #
    # Le modèle est construit **avant** la météo : c'est lui qui dit à quelle
    # vitesse le cycliste passera, donc à quelle heure interroger la prévision.
    poids = lire_poids(config.cache.dossier / NOM_POIDS)
    base_routes = _base_routes(config)
    modele = _modele_temps(args, config)

    client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
    meteos, panne, vitesses = _meteos(
        [t for t, _, _ in traces], client_meteo, config, depart=demande.depart, modele=modele
    )
    evaluations = _classer(
        traces,
        meteos,
        sens_prefere=config.boucle.sens,
        poids=poids,
        base=base_routes,
        modele=modele,
        vitesses_meteo=vitesses,
    )
    chemin = _ecrire_meilleure(evaluations[0].trace, demande) if demande.gpx is None else None

    if panne is not None:
        print(
            f"ourouler : météo indisponible ({panne}) — tableau affiché sans les "
            "colonnes météo, la boucle reste valable",
            file=sys.stderr,
        )
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json(evaluations, demande, config, chemin, modele, poids=poids),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendre_texte(evaluations, demande, config, chemin, modele, poids=poids))
    return 0


def _base_routes(config: Config) -> BaseRoutes | None:
    """La base des routes connues si elle existe déjà, sinon `None`.

    On ne la **crée** pas au passage : `ourouler boucle` n'a pas à fabriquer
    un fichier vide dans le cache pour afficher une colonne informative. Une
    base illisible ne fait pas non plus perdre la boucle — on s'en passe.
    """
    chemin = config.cache.dossier / NOM_BASE
    if not chemin.is_file():
        return None
    try:
        return BaseRoutes(chemin)
    except ErreurUtilisateur:
        return None


def _modele_temps(args: argparse.Namespace, config: Config) -> ModeleTemps | None:
    """Le modèle physique à utiliser pour la colonne « temps », ou `None`.

    C'est **ici**, dans la couche commande, que `calibration.json` est lu : le
    cœur reçoit des `Parametres` déjà construits (règle absolue 2, même
    partage que pour `poids_routes.json`). Sans calibration mesurée, on
    retombe sur la vitesse moyenne de la configuration plutôt que d'afficher
    un temps « modèle » calculé avec un CdA inventé.
    """
    from ourouler.physique.commande import chemin_calibration, lire_calibration, velo_demande

    velo = velo_demande(config, getattr(args, "velo", None))
    calibree = lire_calibration(chemin_calibration(config), velo.nom)
    if calibree is None:
        return None
    puissance = getattr(args, "puissance", None)
    if puissance is None:
        puissance = config.cycliste.ftp_w * PART_FTP_DEFAUT
    if not math.isfinite(puissance) or puissance <= 0:
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts strictement positive est attendue"
        )
    return ModeleTemps(
        parametres=calibree.parametres,
        puissance_w=float(puissance),
        velo=velo.nom,
        provenance="calibration",
    )


# --- options ------------------------------------------------------------------


def lire_options(args: argparse.Namespace, config: Config) -> Demande:
    """Valide les options **avant** toute connexion. Lève `ErreurUtilisateur` sinon.

    L'ordre compte : une distance négative ou une direction illisible doivent
    coûter un message immédiat, pas un aller-retour sur le serveur du
    mainteneur (contrat §6).
    """
    gpx = getattr(args, "gpx", None)
    chemin_gpx = Path(gpx) if gpx else None
    if chemin_gpx is not None and not chemin_gpx.is_file():
        raise ErreurUtilisateur(f"--gpx {gpx} : fichier introuvable")

    distance_km = getattr(args, "distance", None)
    direction = getattr(args, "direction", None)
    azimut = None
    libelle = ""

    if chemin_gpx is None:
        if distance_km is None:
            raise ErreurUtilisateur(
                "boucle : --distance KM est obligatoire (ou --gpx pour évaluer un fichier existant)"
            )
        if direction is None:
            raise ErreurUtilisateur(
                "boucle : --direction N|NE|…|NO ou un azimut en degrés est obligatoire "
                "(ou --gpx pour évaluer un fichier existant)"
            )
        if not math.isfinite(distance_km) or distance_km <= 0:
            raise ErreurUtilisateur(
                f"--distance {distance_km} : une distance en kilomètres strictement positive est attendue"
            )
        libelle, azimut = direction_en_azimut(direction)
    elif direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    nb = getattr(args, "candidates", None)
    nb = config.boucle.candidates if nb is None else nb
    if nb < 1:
        raise ErreurUtilisateur(f"--candidates {nb} : au moins une candidate est attendue")

    profil = getattr(args, "profil", None) or config.brouter.profil
    if chemin_gpx is None and not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "boucle : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter, ou passer --gpx pour évaluer un fichier"
        )

    sortie = getattr(args, "sortie", None)
    demande = Demande(
        gpx=chemin_gpx,
        distance_km=float(distance_km) if distance_km is not None else None,
        direction=libelle,
        azimut_deg=azimut,
        nb_candidates=int(nb),
        profil=profil,
        depart=heure_depart(getattr(args, "depart", None)),
        sortie=Path(sortie) if sortie else None,
        ecraser=bool(getattr(args, "ecraser", False)),
    )
    if demande.gpx is None:
        _verifier_sortie(demande)
    return demande


def _verifier_sortie(demande: Demande) -> None:
    """Refuse d'avance un GPX qu'on ne pourra pas écrire (contrat §6, avant-réseau).

    Un dossier inexistant ou non inscriptible se voyait au moment de
    l'écriture, c'est-à-dire après avoir consommé jusqu'à 12 appels BRouter et
    10 appels Open-Meteo, et sortait en trace plutôt qu'en message.

    Un `--sortie` qui existe déjà n'est **pas** écrasé sans `--ecraser` : avec
    un nom choisi, la deuxième exécution est le cas normal, et remplacer sans
    un mot le fichier qu'on vient de relire serait une perte. Le nom par
    défaut, lui, porte l'horodatage à la minute : il est écrasé sans question
    (décision du superviseur, point 19 de la relecture).
    """
    chemin = demande.sortie if demande.sortie is not None else Path(nom_par_defaut(demande))
    dossier = chemin.parent if str(chemin.parent) else Path(".")
    if not dossier.is_dir():
        raise ErreurUtilisateur(
            f"--sortie {chemin} : le dossier {dossier} n'existe pas"
        )
    _verifier_inscriptible(dossier, chemin)
    if demande.sortie is not None and chemin.exists() and not demande.ecraser:
        raise ErreurUtilisateur(
            f"{chemin} existe déjà — ajouter --ecraser pour le remplacer, "
            "ou choisir un autre nom"
        )


def _verifier_inscriptible(dossier: Path, chemin: Path) -> None:
    """Écrit et efface un fichier témoin : la seule façon de savoir vraiment.

    Un droit d'écriture se mesure, il ne se déduit pas des bits de mode (ACL,
    montage en lecture seule, quota). Le témoin porte un nom unique et est
    effacé aussitôt, y compris si la création a échoué à mi-chemin.
    """
    temoin = dossier / f".ourouler-{uuid.uuid4().hex}.tmp"
    try:
        temoin.touch()
    except OSError as e:
        raise ErreurUtilisateur(
            f"--sortie {chemin} : écriture impossible dans {dossier} ({e})"
        ) from e
    finally:
        try:
            temoin.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - le témoin existe et vient d'être créé
            pass


def direction_en_azimut(texte: str) -> tuple[str, float]:
    """(libellé, azimut) pour « NE », « 45 », « 45° » ou « 45,5 ».

    Les noms à 8 et à 16 secteurs sont acceptés — `azimut_de` les connaît
    déjà, on ne réécrit pas la table. « W » est toléré comme alias de « O »
    (NW → NO) : les cartes et les applications anglophones en sont pleines,
    et refuser une direction pour une lettre serait pénible.
    """
    brut = (texte or "").strip()
    if not brut:
        raise ErreurUtilisateur("--direction : valeur vide, attendu N|NE|…|NO ou un azimut en degrés")

    nombre = brut.rstrip("°").strip().replace(",", ".")
    try:
        azimut = float(nombre)
    except ValueError:
        pass
    else:
        if not math.isfinite(azimut):
            raise ErreurUtilisateur(f"--direction {texte!r} : azimut illisible")
        azimut %= 360.0
        return (f"{azimut:03.0f}", azimut)

    nom = brut.upper().replace("W", "O")
    for directions in (8, 16):
        try:
            return (nom, azimut_de(nom, directions))
        except ErreurConfig:
            continue
    raise ErreurUtilisateur(
        f"--direction {texte!r} : attendu un de {', '.join(NOMS_DIRECTIONS)} "
        f"(ou {', '.join(NOMS_DIRECTIONS_16)}), ou un azimut en degrés"
    )


# --- mesures ------------------------------------------------------------------


def _meteos(
    traces: list[Trace],
    client: ClientOpenMeteo,
    config: Config,
    *,
    depart: datetime,
    modele: ModeleTemps | None = None,
) -> tuple[list[MeteoTrace | None], str | None, list[float]]:
    """La météo de chaque tracé, le motif de panne s'il y en a un, et les vitesses retenues.

    Dès qu'un appel échoue, on cesse d'insister : si Open-Meteo est
    injoignable pour la première candidate, il l'est pour les quatre autres,
    et attendre cinq timeouts ne rend service à personne.

    L'heure de passage en un point vaut `départ + distance / vitesse`. Cette
    vitesse était celle de la configuration (27 km/h), la même pour un
    plat-pays que pour une boucle à 900 m de D+ ; quand le vélo est calibré,
    c'est **le modèle** qui la donne, tracé par tracé.
    """
    resultats: list[MeteoTrace | None] = []
    vitesses: list[float] = []
    panne: str | None = None
    for trace in traces:
        vitesse = _vitesse_meteo(trace, modele, config)
        vitesses.append(vitesse)
        if panne is not None:
            resultats.append(None)
            continue
        try:
            resultats.append(
                evaluer_meteo(
                    trace,
                    client,
                    depart=depart,
                    vitesse_kmh=vitesse,
                    modele=config.meteo.modele,
                    second_avis=config.meteo.second_avis,
                )
            )
        except ErreurConnecteur as e:
            panne = str(e)
            resultats.append(None)
    return (resultats, panne, vitesses)


def _vitesse_meteo(trace: Trace, modele: ModeleTemps | None, config: Config) -> float:
    """La vitesse qui date les heures de passage sur ce tracé, en km/h.

    Celle du modèle calibré quand il existe, celle de la configuration sinon.

    La simulation est faite **à vent nul** : le vent qu'on cherche à connaître
    dépendrait sinon de l'heure, qui dépend de la vitesse, qui dépend du vent.
    L'erreur commise est du second ordre — quelques minutes sur une boucle de
    trois heures, là où l'écart entre 27 km/h supposés et la vraie allure d'un
    parcours vallonné se compte en dizaines de minutes.

    Une simulation qui échoue (tracé dégénéré) retombe sur la configuration :
    la boucle reste affichable.
    """
    if modele is None:
        return config.boucle.vitesse_moyenne_kmh
    from ourouler.physique.modele import simuler

    try:
        vitesse = simuler(trace, modele.puissance_w, modele.parametres).vitesse_moy_kmh
    except ErreurUtilisateur:
        return config.boucle.vitesse_moyenne_kmh
    if not math.isfinite(vitesse) or vitesse <= 0:
        return config.boucle.vitesse_moyenne_kmh
    return vitesse


def _classer(
    traces: list[tuple[Trace, float | None, object]],
    meteos: list[MeteoTrace | None],
    *,
    sens_prefere: str,
    poids: dict[str, float] | None = None,
    base: BaseRoutes | None = None,
    modele: ModeleTemps | None = None,
    vitesses_meteo: Sequence[float] | None = None,
) -> list[Evaluation]:
    """Les candidates mesurées et triées par `score + pluie × 2`, numérotées à partir de 1.

    `part_connue` est calculée si une base existe, mais **n'entre pas dans
    `total`** : c'est tout l'objet du lot. Les traces du cycliste ne couvrent
    qu'une partie du territoire ; les prendre pour un critère condamnerait
    d'avance toute direction jamais explorée.
    """
    evaluations = []
    vitesses = list(vitesses_meteo) if vitesses_meteo is not None else [None] * len(traces)
    for (trace, ecart, candidate), meteo, vitesse in zip(
        traces, meteos, vitesses, strict=True
    ):
        couts = evaluer_couts(trace, sens_prefere=sens_prefere, poids=poids)
        pluie = meteo.pluie_cumulee_mm if meteo is not None else 0.0
        evaluations.append(
            Evaluation(
                numero=0,
                trace=trace,
                couts=couts,
                meteo=meteo,
                ecart_relatif=ecart,
                azimut_deg=getattr(candidate, "azimut_deg", None),
                rayon_m=getattr(candidate, "rayon_m", None),
                total=couts.score + pluie * POIDS_PLUIE_TRI,
                part_connue=base.part_connue(trace) if base is not None else None,
                temps_s=_temps_modele(trace, meteo, modele),
                vitesse_meteo_kmh=vitesse,
            )
        )
    evaluations.sort(key=lambda e: e.total)
    for numero, evaluation in enumerate(evaluations, start=1):
        evaluation.numero = numero
    return evaluations


def _temps_modele(trace: Trace, meteo: MeteoTrace | None, modele: ModeleTemps | None) -> float | None:
    """Le temps en mouvement du modèle sur ce tracé, vent prévu compris. `None` sans modèle.

    Une simulation qui échoue (tracé dégénéré) ne fait pas tomber la commande :
    la colonne retombe simplement sur la vitesse moyenne.
    """
    if modele is None:
        return None
    from ourouler.physique.commande import vent_depuis_meteo
    from ourouler.physique.modele import simuler

    vent = vent_depuis_meteo(meteo) if meteo is not None else None
    try:
        return simuler(trace, modele.puissance_w, modele.parametres, vent=vent).temps_s
    except ErreurUtilisateur:
        return None


def _ecrire_meilleure(trace: Trace, demande: Demande) -> Path:
    """Écrit la boucle retenue en GPX et rend son chemin."""
    chemin = demande.sortie if demande.sortie is not None else Path(nom_par_defaut(demande))
    try:
        chemin.write_text(ecrire_gpx(trace, trace.nom), encoding="utf-8")
    except OSError as e:
        # Disque plein, droits retirés entre-temps, chemin devenu un dossier :
        # un message, pas une trace — les appels externes sont déjà consommés.
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def nom_par_defaut(demande: Demande) -> str:
    """`boucle_<direction>_<distance>km_<AAAAMMJJ-HHMM>.gpx` (contrat §6)."""
    distance = f"{demande.distance_km:g}" if demande.distance_km is not None else "0"
    return f"boucle_{demande.direction}_{distance}km_{demande.depart:%Y%m%d-%H%M}.gpx"


# --- rendu texte ---------------------------------------------------------------

#: Colonnes du tableau, dans l'ordre des contrats §6 (sprint 2) et §2
#: (sprint 3). Le second membre nomme la mesure dont la colonne dépend :
#: sans cette mesure, la colonne **disparaît** au lieu d'afficher une colonne
#: de tirets. `None` = toujours affichée.
COLONNES = (
    ("n°", None),
    ("distance", None),
    ("D+", None),
    ("temps", None),  # le titre porte sa provenance, voir `_titres`
    ("trafic", None),
    ("non revêtu", None),
    ("coût profil", "cout"),
    ("virages G", None),
    ("sens", None),
    ("connu %", "connu"),
    (TITRE_ANTENNES_RETIREES, None),  # remplacé par `_titres` pour un GPX importé
    ("pluie", "meteo"),
    ("vent face", "meteo"),
    ("ressenti min", "meteo"),
)


def rendre_texte(
    evaluations: list[Evaluation],
    demande: Demande,
    config: Config,
    chemin: Path | None,
    modele: ModeleTemps | None = None,
    *,
    poids: dict[str, float] | None = None,
) -> str:
    """Le tableau des candidates, la ligne retenue marquée d'une flèche."""
    presentes = _mesures_presentes(evaluations)
    lignes = _entete(demande, config, "meteo" in presentes, poids, evaluations, modele)

    titres = _titres(presentes, elaguees=demande.gpx is None, config=config, modele=modele)
    cellules = [_cellules(e, config, presentes) for e in evaluations]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for evaluation, ligne in zip(evaluations, cellules, strict=True):
        retenue = evaluation is evaluations[0] and demande.gpx is None
        marque = f"{MARQUE_RETENUE} " if retenue else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if any(e.trace.meta.get("couts_partiels") for e in evaluations):
        lignes.append(
            f"{ABSENT} : tracé sans tags de route (GPX importé) — trafic et revêtement inconnus."
        )
    non_classes = _non_classes_signales(evaluations)
    if non_classes:
        lignes.append(
            f"{_fr(non_classes, 1)} km sur des routes non classées (ni trafic ni calme) : "
            "« trafic » et « calme » ne couvrent pas tout le tracé."
        )
    ignores = sum(int(e.trace.meta.get("segments_ignores") or 0) for e in evaluations)
    if ignores:
        lignes.append(
            f"{ignores} tronçon(s) à la longueur inexploitable écartés du kilométrage : "
            "trafic et revêtement sont sous-estimés d'autant."
        )
    if chemin is not None:
        lignes.append(f"{MARQUE_RETENUE} retenue : n° {evaluations[0].numero}, écrite dans {chemin}")
    return "\n".join(lignes)


def _titres(
    presentes: set[str],
    *,
    elaguees: bool,
    config: Config,
    modele: ModeleTemps | None = None,
) -> list[str]:
    """Les titres des colonnes affichées — antennes et temps disent d'où ils viennent.

    Antennes : « retirées » sur une candidate générée (elle est élaguée),
    « détectées » sur un GPX importé (il ne l'est pas). Temps : `(modèle)`
    quand la calibration du vélo existe, `(27 km/h)` — la vitesse moyenne de
    la configuration — sinon. Sans ces mentions, deux exécutions du même
    ordre donnaient deux chiffres différents sans rien dire.
    """
    mention = (
        MENTION_MODELE if modele is not None else f"({config.boucle.vitesse_moyenne_kmh:g} km/h)"
    )
    titres = [
        f"temps {mention}" if titre == "temps" else titre
        for titre, mesure in COLONNES
        if mesure is None or mesure in presentes
    ]
    if not elaguees:
        titres[titres.index(TITRE_ANTENNES_RETIREES)] = TITRE_ANTENNES_DETECTEES
    return titres


def _vitesse_passage(config: Config, evaluations: list[Evaluation] | None) -> str:
    """« 27 km/h » ou « 29,4 km/h (modèle) » — la vitesse qui a daté la météo.

    Les candidates n'ont pas toutes la même : une boucle vallonnée se parcourt
    moins vite qu'un plat-pays à la même puissance. L'entête affiche donc la
    moyenne des candidates dès qu'elles diffèrent d'un dixième.
    """
    connues = [
        e.vitesse_meteo_kmh for e in (evaluations or []) if e.vitesse_meteo_kmh is not None
    ]
    if not connues:
        return f"{config.boucle.vitesse_moyenne_kmh:g} km/h"
    moyenne = sum(connues) / len(connues)
    if abs(moyenne - config.boucle.vitesse_moyenne_kmh) < 0.05:
        return f"{config.boucle.vitesse_moyenne_kmh:g} km/h"
    etendue = ""
    if max(connues) - min(connues) >= 0.1:
        etendue = f" de {min(connues):.1f} à {max(connues):.1f}".replace(".", ",")
    return f"{moyenne:.1f} km/h {MENTION_MODELE}{etendue}".replace(".", ",", 1)


def _non_classes_signales(evaluations: list[Evaluation]) -> float:
    """Le plus gros kilométrage non classé à signaler, ou 0 s'il n'y a rien à dire.

    Un tracé dont la moitié passe par des chemins sans `highway` connu
    (`path`, `footway`, une valeur OSM nouvelle) affichait « 0,0 km de
    trafic » exactement comme un tracé parfaitement calme : `km_trafic` et
    `km_calme` peuvent valoir bien moins que la distance, et rien ne le disait
    (point 15 de la relecture du sprint 2).
    """
    a_signaler = [
        e.couts.km_non_classe
        for e in evaluations
        if not e.trace.meta.get("couts_partiels")
        and e.trace.distance_m > 0
        and e.couts.km_non_classe / (e.trace.distance_m / 1000.0) > PART_NON_CLASSE_SIGNALEE
    ]
    return max(a_signaler, default=0.0)


def _mesures_presentes(evaluations: list[Evaluation]) -> set[str]:
    """Les mesures dont au moins une candidate dispose — donc les colonnes à montrer."""
    presentes = set()
    if any(e.meteo is not None for e in evaluations):
        presentes.add("meteo")
    if any(e.couts.cout_km_moyen is not None for e in evaluations):
        presentes.add("cout")
    if any(e.part_connue is not None for e in evaluations):
        presentes.add("connu")
    return presentes


def _entete(
    demande: Demande,
    config: Config,
    avec_meteo: bool,
    poids: dict[str, float] | None = None,
    evaluations: list[Evaluation] | None = None,
    modele: ModeleTemps | None = None,
) -> list[str]:
    lignes = []
    if demande.gpx is not None:
        lignes.append(f"Tracé importé : {demande.gpx}")
    else:
        lignes.append(
            f"Boucle depuis {config.depart.nom} — {demande.distance_km:g} km vers "
            f"{demande.direction} ({demande.azimut_deg:.0f}°), profil {demande.profil}"
        )
    lignes.append(
        f"Départ {date_en_francais(demande.depart)} — {_vitesse_passage(config, evaluations)} "
        f"(heures de passage météo), sens préféré {config.boucle.sens}"
    )
    if modele is not None:
        lignes.append(
            f"Temps estimé par le modèle calibré du {modele.velo} à {modele.puissance_w:.0f} W "
            "— temps en mouvement, arrêts non modélisés"
        )
    else:
        lignes.append(
            f"Temps estimé à {config.boucle.vitesse_moyenne_kmh:g} km/h : aucun vélo calibré "
            "(lancer `ourouler calibrer`)"
        )
    if avec_meteo:
        lignes.append(f"Météo {config.meteo.modele}, second avis {config.meteo.second_avis or 'aucun'}")
    lignes.append("Tri : score (km équivalents) + pluie cumulée × 2 ; plus bas = mieux.")
    if poids:
        # D'où viennent les poids : sans cette ligne, deux exécutions
        # séparées par un `routes poids --appliquer` donneraient des scores
        # différents sans que rien ne l'explique.
        cites = _classes_citees(poids, evaluations or [])
        lignes.append(
            "Poids des routes : appris sur vos sorties"
            + (f" ({cites})." if cites else ".")
        )
    else:
        lignes.append(
            "Poids des routes : valeurs par défaut — `ourouler routes poids --appliquer` "
            "les apprend sur vos sorties."
        )
    lignes.append(
        "« connu % » : part des km déjà roulés — informatif, jamais dans le score."
    )
    return lignes


def _classes_citees(
    poids: dict[str, float], evaluations: list[Evaluation], nombre: int = 4
) -> str:
    """Le poids des classes les plus **présentes dans les candidates affichées**.

    Citer les plus pénalisées donnait une ligne vraie mais inutile
    (« primary_link 4,0, pedestrian 3,3 ») : ces classes ne font pas
    cinquante mètres du tracé. Ce que le lecteur veut savoir, c'est ce que
    coûtent les routes qu'il a sous les yeux.
    """
    km_par_classe: dict[str, float] = {}
    for evaluation in evaluations:
        for classe, km in evaluation.couts.km_par_highway.items():
            if classe:
                km_par_classe[classe] = km_par_classe.get(classe, 0.0) + km
    classes = sorted(km_par_classe.items(), key=lambda kv: (-kv[1], kv[0]))[:nombre]
    return ", ".join(f"{classe} {_fr(poids.get(classe, 0.0), 1)}" for classe, _ in classes)


def _cellules(evaluation: Evaluation, config: Config, presentes: set[str]) -> list[str]:
    couts, meteo = evaluation.couts, evaluation.meteo
    partiels = bool(evaluation.trace.meta.get("couts_partiels"))
    cellules = [
        str(evaluation.numero),
        f"{_fr(evaluation.trace.distance_m / 1000, 1)} km",
        _denivele(evaluation.trace),
        _temps(evaluation, config),
        ABSENT if partiels else f"{_fr(couts.km_trafic, 1)} km",
        ABSENT if partiels else f"{_fr(couts.km_non_revetu, 1)} km",
    ]
    if "cout" in presentes:
        cellules.append(
            _fr(couts.cout_km_moyen, 0) if couts.cout_km_moyen is not None else ABSENT
        )
    cellules += [
        f"{couts.virages_gauche} ({couts.virages_gauche_trafic})",
        couts.sens,
    ]
    if "connu" in presentes:
        cellules.append(
            f"{evaluation.part_connue * 100:.0f} %" if evaluation.part_connue is not None else ABSENT
        )
    cellules.append(f"{couts.antennes_m:.0f} m")
    if "meteo" in presentes:
        cellules += [
            f"{_fr(meteo.pluie_cumulee_mm, 1)} mm" if meteo else ABSENT,
            _vent_face(meteo),
            f"{_fr(meteo.ressenti_min_c, 1)} °C" if meteo and meteo.ressenti_min_c is not None else ABSENT,
        ]
    return cellules


def _denivele(trace: Trace) -> str:
    """« 362 m (moteur) » ou « 362 m (gpx relu) » — le D+ dit d'où il vient.

    Le « filtered ascend » du moteur et le D+ recalculé à la relecture d'un
    GPX divergent de 10 à 32 % sur les tracés mesurés, dans les deux sens :
    afficher le chiffre sans sa provenance rendait l'écart incompréhensible
    (point 5 de la relecture du sprint 2).
    """
    if trace.denivele_m is None:
        return ABSENT
    source = trace.meta.get("denivele_source")
    return f"{trace.denivele_m:.0f} m" + (f" ({source})" if source else "")


def _vent_face(meteo: MeteoTrace | None) -> str:
    """« 38 % (12/12) » — le pourcentage et le nombre d'échantillons qui le portent.

    Les parts de vent se calculent sur les seuls échantillons au vent connu,
    ce qui est le bon choix : un échantillon sans donnée ne doit pas compter
    pour du travers. Mais « vent face 100 % » ne disait pas s'il reposait sur
    douze échantillons ou sur un seul, les onze autres étant hors de
    l'horizon de prévision (point 18 de la relecture du sprint 2).
    """
    if meteo is None:
        return ABSENT
    return f"{meteo.part_vent_face * 100:.0f} % ({meteo.n_vent_connu}/{len(meteo.echantillons)})"


def _temps(evaluation: Evaluation, config: Config) -> str:
    """« 2:14 » — le temps du modèle s'il y en a un, sinon celui de la vitesse moyenne."""
    if evaluation.temps_s is not None:
        return _duree_texte(evaluation.temps_s)
    vitesse = config.boucle.vitesse_moyenne_kmh
    if vitesse <= 0:
        return ABSENT
    return _duree_texte(evaluation.trace.distance_m / 1000 / vitesse * 3600)


def _duree_texte(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale, pas de séparateur de milliers."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


# --- rendu JSON ----------------------------------------------------------------


def rendre_json(
    evaluations: list[Evaluation],
    demande: Demande,
    config: Config,
    chemin: Path | None,
    modele: ModeleTemps | None = None,
    *,
    poids: dict[str, float] | None = None,
) -> dict:
    """Toutes les mesures, plus le chemin du GPX écrit (contrat §6)."""
    return {
        "depart": {
            "nom": config.depart.nom,
            "latitude": config.depart.latitude,
            "longitude": config.depart.longitude,
            "heure": demande.depart.isoformat(),
        },
        "demande": {
            "distance_km": demande.distance_km,
            "direction": demande.direction or None,
            "azimut_deg": demande.azimut_deg,
            "profil": demande.profil,
            "candidates": demande.nb_candidates,
            "gpx_importe": str(demande.gpx) if demande.gpx is not None else None,
        },
        "vitesse_moyenne_kmh": config.boucle.vitesse_moyenne_kmh,
        "sens_prefere": config.boucle.sens,
        "modele": config.meteo.modele,
        "second_avis": config.meteo.second_avis,
        "gpx": str(chemin) if chemin is not None else None,
        "poids_routes": dict(poids) if poids else None,
        "modele_physique": None
        if modele is None
        else {
            "velo": modele.velo,
            "puissance_w": modele.puissance_w,
            "provenance": modele.provenance,
            "cda_m2": modele.parametres.cda_m2,
            "crr": modele.parametres.crr,
            "masse_totale_kg": modele.parametres.masse_totale_kg,
        },
        "candidates": [_candidate_json(e, config, chemin) for e in evaluations],
    }


def _candidate_json(evaluation: Evaluation, config: Config, chemin: Path | None) -> dict:
    couts, meteo = evaluation.couts, evaluation.meteo
    trace = evaluation.trace
    distance_km = trace.distance_m / 1000.0
    return {
        "numero": evaluation.numero,
        "retenue": evaluation.numero == 1 and chemin is not None,
        "nom": trace.nom,
        "distance_km": round(distance_km, 3),
        "denivele_m": trace.denivele_m,
        "denivele_source": trace.meta.get("denivele_source"),
        "temps_estime_s": (
            round(evaluation.temps_s)
            if evaluation.temps_s is not None
            else round(distance_km / config.boucle.vitesse_moyenne_kmh * 3600)
        ),
        "temps_source": "modele" if evaluation.temps_s is not None else "vitesse_moyenne",
        "vitesse_meteo_kmh": (
            None
            if evaluation.vitesse_meteo_kmh is None
            else round(evaluation.vitesse_meteo_kmh, 2)
        ),
        "azimut_deg": evaluation.azimut_deg,
        "rayon_m": evaluation.rayon_m,
        "ecart_relatif": evaluation.ecart_relatif,
        "total_tri": round(evaluation.total, 3),
        "couts_partiels": bool(trace.meta.get("couts_partiels")),
        "segments_ignores": int(trace.meta.get("segments_ignores") or 0),
        # « retirees » : le tracé proposé n'a plus ces mètres. « detectees » :
        # un GPX importé n'est pas élagué, ils y sont encore.
        "antennes_source": "retirees" if trace.meta.get("antennes") is not None else "detectees",
        "antennes": trace.meta.get("antennes"),
        "distance_source": trace.meta.get("distance_source"),
        # Informatifs, hors score : le coût que le moteur s'attribue à
        # lui-même, et la part de kilomètres déjà roulés.
        "cout_km_moyen": couts.cout_km_moyen,
        "part_connue": evaluation.part_connue,
        "km_par_highway": {k: round(v, 3) for k, v in couts.km_par_highway.items()},
        "couts": {
            "km_trafic": round(couts.km_trafic, 3),
            "km_calme": round(couts.km_calme, 3),
            "km_non_classe": round(couts.km_non_classe, 3),
            "km_non_revetu": round(couts.km_non_revetu, 3),
            "antennes_m": round(couts.antennes_m, 1),
            "virages_gauche": couts.virages_gauche,
            "virages_gauche_trafic": couts.virages_gauche_trafic,
            "virages_droite": couts.virages_droite,
            "sens": couts.sens,
            "score": round(couts.score, 3),
        },
        "meteo": _meteo_json(meteo),
        "meta": trace.meta,
    }


def _meteo_json(meteo: MeteoTrace | None) -> dict | None:
    if meteo is None:
        return None
    return {
        "pluie_cumulee_mm": round(meteo.pluie_cumulee_mm, 3),
        "minutes_pluie": round(meteo.minutes_pluie, 1),
        "part_vent_face": round(meteo.part_vent_face, 3),
        "part_vent_dos": round(meteo.part_vent_dos, 3),
        "n_vent_connu": meteo.n_vent_connu,
        "n_echantillons": len(meteo.echantillons),
        "ressenti_min_c": meteo.ressenti_min_c,
        "confiance": meteo.confiance,
        "echantillons": [
            {
                "dist_m": round(e.dist_m, 1),
                "t": e.t.isoformat(),
                "cap_deg": round(e.cap_deg, 1),
                "pluie_mm": e.pluie_mm,
                "vent_kmh": e.vent_kmh,
                "vent_relatif": e.vent_relatif,
                "ressenti_c": e.ressenti_c,
            }
            for e in meteo.echantillons
        ],
    }

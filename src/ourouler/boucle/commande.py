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
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes, lire_poids, points_de_passage_depuis_coordonnees
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.gpx import ecrire_gpx, lire_gpx_trace
from ourouler.boucle.horaire import Pause, analyser_pause, construire_horaire, valider_pauses
from ourouler.boucle.marqueurs import Marqueurs
from ourouler.boucle.marqueurs import compter as compter_marqueurs
from ourouler.boucle.meteo_trace import MeteoTrace, fleches_vent
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.boucle.tags_importes import greffer
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo import portee
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.couronne import NOMS_DIRECTIONS, NOMS_DIRECTIONS_16, azimut_de
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import date_en_francais
from ourouler.noyau.erreurs import (
    ErreurConfig,
    ErreurConnecteur,
    ErreurDistanceInatteignable,
    ErreurUtilisateur,
)
from ourouler.noyau.profil import Depart
from ourouler.noyau.trace import DENIVELE_REROUTE, Trace, denivele_filtre
from ourouler.physique.modele import FourchettePorteAPorte, PorteAPorte, temps_ecoule

#: Poids de la pluie dans le tri du tableau : un millimètre cumulé coûte
#: autant que deux kilomètres équivalents de score (contrat §6).
POIDS_PLUIE_TRI = 2.0

#: Marque de la ligne retenue dans le tableau texte.
MARQUE_RETENUE = "→"

#: Mention accolée au titre de la colonne « temps » quand il vient du modèle.
MENTION_MODELE = "(modèle)"

#: La même, quand CdA et Crr n'ont pas été mesurés sur ce vélo mais viennent de
#: la table de `physique.litterature`. Deux mots de plus, et ils comptent : le
#: temps est calculé, pas supposé constant, mais il repose sur des valeurs de
#: catégorie (règle absolue 5, même geste que le « supposé » du facteur
#: compteur).
MENTION_MODELE_LITTERATURE = "(modèle, littérature)"

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

#: `trace.meta["tags_provenance"]` : d'où viennent les tags OSM d'un tracé
#: (règle absolue 5 — un tag mesuré directement par le moteur et un tag
#: deviné par rapprochement ne se présentent pas de la même façon). Une
#: candidate générée par BRouter porte `MESURE` ; un GPX importé dont le
#: greffage (`boucle.tags_importes`) a réussi porte `RAPPROCHEMENT` ; un GPX
#: dont le greffage a échoué ou n'a rien trouvé ne porte rien du tout — la
#: clé est absente, comme aujourd'hui.
TAGS_PROVENANCE_MESURE = "mesuree"
TAGS_PROVENANCE_RAPPROCHEMENT = "rapprochement"


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
    pauses: tuple[Pause, ...] = ()
    """Les arrêts déclarés (`--pause KM:DUREE`, répétable) — départ, sortie
    d'antenne exclue, décalent l'heure de passage météo de chaque échantillon
    situé après eux (`boucle.horaire.construire_horaire`). Jamais sur
    `sortie` : cette commande pose une séance structurée sur une boucle, les
    pauses n'y ont pas de sens."""


@dataclass(frozen=True)
class ModeleTemps:
    """De quoi calculer un temps estimé par le modèle physique, si on en a un."""

    parametres: object  # ourouler.physique.modele.Parametres (import paresseux)
    puissance_w: float
    velo: str
    provenance: str  # « calibration », « configuration » ou « littérature »
    #: L'usage du vélo (`config.Velo.usage`), pour retrouver la catégorie de
    #: `physique.litterature` quand la provenance en vient — sans rouvrir la
    #: configuration depuis un rendu.
    usage: str = ""
    #: `physique.commande.ALERTE_PNEU_CHANGE` quand la calibration ne suit
    #: plus le pneu déclaré du vélo (elle reste utilisée), sinon vide.
    alerte: str = ""

    @property
    def calibre(self) -> bool:
        """Vrai si CdA et Crr ont été **mesurés** sur ce vélo, faux sinon."""
        return self.provenance == "calibration"


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
    #: De combien il a fallu élargir la tolérance de distance pour accepter
    #: cette boucle, par paliers de 5 % (Q41 d). `0.0` : elle y tenait déjà.
    #: `None` : la question ne se pose pas (GPX importé, pas de cible).
    elargissement: float | None = None
    #: La tolérance de distance en vigueur, pour que l'écran puisse dire
    #: « ±10 % demandés, ±20 % servis » sans aller la relire ailleurs.
    tolerance_distance: float | None = None
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
    marqueurs: Marqueurs | None = None
    """Feux, stops et compagnie sur le tracé entier (`boucle.marqueurs`).
    `None` seulement si le calcul n'a pas eu lieu ; `marqueurs.connue` dit si
    le tracé porte des `segments` — sinon zéro ne veut pas dire aucun feu."""


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    *,
    lieu_depart: Depart | None = None,
    base_routes: BaseRoutes | None = None,
) -> int:
    """Exécute `ourouler boucle`. Renvoie le code de sortie (0 = succès).

    `base_routes` s'injecte comme les clients : absente — le cas de la ligne
    de commande — la base des routes apprises est ouverte sur
    `config.cache.dossier`, avec le propriétaire par défaut. Une couche web
    qui sert plusieurs cyclistes en construit une par propriétaire et la passe
    ici ; sans quoi la colonne « connu % » dirait à l'un ce que l'autre a
    roulé ([[Q58]], voir `activites/commande.executer`).

    `lieu_depart` est le **point de départ de cette exécution**, déjà tranché
    par l'appelant : `cli.py` quand `--adresse-depart` a été géocodée, une
    requête d'API demain. Absent, c'est celui de la configuration. Le cœur ne
    géocode rien, ne lit aucune adresse et ne sait pas d'où vient ce point
    (règle absolue 2) — il reçoit un `Depart`.

    À ne pas confondre avec `demande.depart`, qui porte une **heure**.

    Ce qui ne suit pas le départ : les **routes connues** et les **poids
    appris** du cache (`routes.sqlite`, `poids_routes.json`) ont été mesurés
    autour du départ configuré. Partir d'ailleurs ne les casse pas — la part
    connue est informative et n'entre dans aucun score (contrat du sprint 3
    §2) — mais elle tombera naturellement à zéro loin de chez soi. `cli.py`
    le dit sur la sortie d'erreur plutôt que de laisser croire à un tracé
    inédit.
    """
    if lieu_depart is not None:
        # Substitué dans la `Config` plutôt que passé de fonction en fonction :
        # la génération des candidates, les en-têtes de texte et le JSON lisent
        # tous `config.depart`, et un seul de ces points oublié rendrait une
        # réponse fausse — une boucle autour de la maison pour une adresse à
        # 400 km. `Config` est un dataclass gelé : `replace` rend une copie, la
        # configuration de l'appelant n'est pas touchée.
        config = replace(config, depart=lieu_depart)
    demande = lire_options(args, config)

    if demande.gpx is not None:
        trace_gpx = lire_gpx_trace(demande.gpx)
        _greffer_tags_sur_gpx(trace_gpx, config, client_brouter)
        traces = [(trace_gpx, None, None)]
        # Longueur réelle enfin connue (`lire_options` ne l'avait, sans
        # `--gpx`, que via `--distance` — la demande, pas le tracé importé) :
        # une pause au-delà de ce GPX-là est encore une erreur d'entrée,
        # revalidée avant tout appel météo.
        valider_pauses(demande.pauses, distance_m=trace_gpx.distance_m)
    else:
        client_brouter = (
            client_brouter
            if client_brouter is not None
            # Les zones à éviter sont passées au client, pas lues par lui :
            # le cœur ne connaît pas la configuration, il la reçoit.
            else ClientBrouter(config.brouter, evitements=config.evitements)
        )
        trouvees = _generer_candidates(client_brouter, config, demande)
        traces = [(c.trace, c.ecart_relatif, c) for c in trouvees]
        for trace, _, _ in traces:
            trace.meta.setdefault("tags_provenance", TAGS_PROVENANCE_MESURE)

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
    base_routes = base_routes if base_routes is not None else _base_routes(config)
    modele = _modele_temps(args, config)
    # Le bloc « compteur » (18/09/2026) : la troisième valeur de l'écran de
    # FTP, déléguée à `ecran_ftp.info_compteur` — jamais recalculée ici. Il
    # sert à réconcilier `temps_estime_s` (mouvement) et `temps_ecoule_s`
    # (porte à porte) dans `rendre_json`/`rendre_texte`. Indépendant de
    # `modele` : une calibration absente n'empêche pas la réconciliation, elle
    # empêche seulement le temps de mouvement d'être celui du modèle plutôt
    # que la vitesse moyenne (voir `_candidate_json`).
    #
    # `--puissance`/`--vitesse-a-plat`, déjà validées exclusives par
    # `lire_options`, voyagent jusqu'ici : sans elles, la moyenne compteur qui
    # chronomètre le porte à porte restait celle de la puissance d'endurance
    # de la configuration quelle que soit la puissance demandée pour CETTE
    # boucle-ci (corrigé le 18/09/2026).
    compteur_info = _info_compteur(
        config,
        getattr(args, "velo", None),
        puissance_w=getattr(args, "puissance", None),
        vitesse_a_plat_kmh=getattr(args, "vitesse_a_plat", None),
    )

    # Q40 (a) : une heure de départ trop lointaine ne se refuse pas, elle se
    # sert **sans météo** — et sans appeler Open-Meteo pour récolter des blocs
    # vides. Même règle et même phrase que `ourouler sortie`.
    dernier_jour = portee.dernier_jour_couvert(
        config.meteo.horizon_jours, aujourdhui=date.today()
    )
    jour_demande = demande.depart.date()
    meteo_absente = (
        portee.constater(jour_demande, dernier_jour) if jour_demande > dernier_jour else None
    )
    if meteo_absente is not None:
        meteos, panne = [None] * len(traces), None
        vitesses = [_vitesse_meteo(t, modele, config) for t, _, _ in traces]
    else:
        client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
        meteos, panne, vitesses = _meteos(
            [t for t, _, _ in traces],
            client_meteo,
            config,
            depart=demande.depart,
            modele=modele,
            pauses=demande.pauses,
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

    if meteo_absente is None and panne is not None:
        meteo_absente = portee.constater(jour_demande, dernier_jour)
    if panne is not None:
        print(
            f"ourouler : météo indisponible ({panne}) — tableau affiché sans les "
            "colonnes météo, la boucle reste valable",
            file=sys.stderr,
        )
    elif meteo_absente is not None:
        print(
            f"ourouler : {meteo_absente.message} — tableau affiché sans les colonnes météo, "
            "la boucle reste valable",
            file=sys.stderr,
        )
    if getattr(args, "json", False):
        print(
            json.dumps(
                rendre_json(
                    evaluations,
                    demande,
                    config,
                    chemin,
                    modele,
                    poids=poids,
                    meteo_absente=meteo_absente,
                    compteur_info=compteur_info,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            rendre_texte(
                evaluations, demande, config, chemin, modele, poids=poids, compteur_info=compteur_info
            )
        )
    return 0


def _generer_candidates(client: ClientBrouter, config: Config, demande: Demande) -> list:
    """Les boucles candidates : la direction demandée, ou tout le tour de l'horizon.

    Même logique que `sortie._candidates` (Q47) — reprise, pas refaite. Sans
    `--direction`, `boucle` ne choisissait pas moins que `sortie`, elle
    **refusait** : « --direction … est obligatoire ». C'était une contrainte
    héritée d'une commande qui n'avait jamais appris à balayer, pas un choix
    de conception (le mainteneur l'a relevé lui-même — Q47). Elle répartit
    donc désormais les candidates sur les huit directions, **un appel à
    `generer` par azimut** : c'est ce qui garantit que chaque direction
    reçoit sa part plutôt que de laisser `generer` élargir un seul secteur
    (`boucle.candidates.azimuts` balaie ±20°, ±40°… autour d'un azimut, il
    n'en ouvre jamais un second).

    Le plafond d'appels suit toujours la demande : `appels_pour(nb)` est le
    même mécanisme que celui que `sortie` utilise déjà, pas un second inventé
    ici pour l'occasion.

    Le refus sur la distance (`ErreurDistanceInatteignable`, Q41 d) est donc
    **par direction**, comme dans `sortie` : une direction où le terrain ne
    sait pas faire la distance ne doit pas faire perdre les directions où il
    sait. Il n'est relancé que si **aucune** direction n'a rien donné, et
    c'est alors le refus le moins sévère qui remonte — celui qui dit le plus
    justement de combien il aurait fallu élargir.
    """
    if demande.azimut_deg is not None:
        repartition = [(demande.azimut_deg, demande.nb_candidates)]
    else:
        pas = 360.0 / demande.nb_candidates
        repartition = [(i * pas, 1) for i in range(demande.nb_candidates)]

    trouvees: list = []
    refus: ErreurDistanceInatteignable | None = None
    for azimut, nb in repartition:
        try:
            trouvees += generer(
                client,
                config.depart,
                distance_km=demande.distance_km,
                azimut_deg=azimut,
                nb=nb,
                tolerance=config.boucle.tolerance_distance,
                profil=demande.profil,
                appels_max=appels_pour(nb),
            )
        except ErreurDistanceInatteignable as e:
            if refus is None or e.elargissement_requis < refus.elargissement_requis:
                refus = e
    if not trouvees and refus is not None:
        raise refus
    if not trouvees:
        cible = demande.direction or "toutes directions"
        raise ErreurConnecteur(
            f"boucle : aucune boucle bornée trouvée autour de {cible} "
            f"pour {demande.distance_km:g} km (profil {demande.profil}) — "
            "essayer une autre direction, une autre distance ou un autre profil"
        )
    return trouvees


def _greffer_tags_sur_gpx(
    trace_gpx: Trace, config: Config, client_brouter: ClientBrouter | None
) -> None:
    """Tente de greffer des tags OSM — et un D+ — sur un GPX importé, en le modifiant sur place.

    Le principe (voir `boucle.tags_importes`) : rejouer le GPX dans BRouter
    avec des points de passage espacés, puis attribuer à chaque point du GPX
    les tags du tronçon rerouté le plus proche, sans jamais remplacer la
    géométrie d'origine. Le même appel sert aussi le D+ (L7.C) : l'altitude
    d'un GPX importé n'est pas meilleure que celle d'un appareil (même bruit
    de baromètre pour un export Garmin/Strava), alors que la réponse de
    BRouter porte déjà, point par point, une altitude tirée de la carte de
    terrain — `boucle.trace.denivele_filtre` appliqué à `trace_reroutee.points`
    au lieu des altitudes du GPX. C'est cette même réponse qu'on jetait avant
    (contrat sprint 7 §L7.C).

    **Chemin dégradé, volontairement large.** BRouter absent de la
    configuration, serveur injoignable, itinéraire refusé, ou rapprochement
    qui ne trouve rien d'exploitable (`Greffage.exploitable` faux) :
    `trace_gpx` n'est alors pas touchée, elle garde exactement le
    `couts_partiels: True` et le D+ recalculé sur ses propres altitudes que
    `lire_gpx_trace` lui a posés. Aucune exception ne doit remonter d'ici —
    un GPX s'évalue toujours, tags ou pas. Le D+ reroutee suit la même
    condition que les tags (`greffage.exploitable`) plutôt que sa propre
    condition : un rapprochement qui ne trouve aucun tronçon assez proche dit
    que le tracé rerouté a pris une route différente du GPX, et son profil
    d'altitude n'a alors pas plus de raison d'être bon que ses tags.
    """
    try:
        client = (
            client_brouter
            if client_brouter is not None
            else ClientBrouter(config.brouter, evitements=config.evitements)
        )
        passages = points_de_passage_depuis_coordonnees(
            [(p.lat, p.lon) for p in trace_gpx.points]
        )
        if len(passages) < 2:
            return
        trace_reroutee = client.itineraire(passages)
        greffage = greffer(trace_gpx, trace_reroutee)
        if not greffage.exploitable:
            return
    except ErreurConnecteur:
        return

    trace_gpx.segments = greffage.segments
    trace_gpx.meta["couts_partiels"] = False
    trace_gpx.meta["tags_provenance"] = TAGS_PROVENANCE_RAPPROCHEMENT
    trace_gpx.meta["tags_seuil_m"] = greffage.seuil_m
    trace_gpx.meta["tags_km_sans_tag"] = round(greffage.km_sans_tag, 3)

    denivele = denivele_filtre(trace_reroutee.points)
    if denivele is not None:
        trace_gpx.denivele_m = denivele
        trace_gpx.meta["denivele_source"] = DENIVELE_REROUTE


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
    partage que pour `poids_routes.json`).

    **Une calibration mesurée n'est plus exigée** (18/09/2026) : quelqu'un qui
    remplit honnêtement sa configuration — FTP, type de vélo, masse — obtenait
    jusqu'ici la constante `vitesse_moyenne_kmh`, et faire varier sa FTP de
    150 à 300 W ne déplaçait ni les heures de passage météo ni le temps de
    mouvement. Le modèle se construit maintenant sur les meilleurs paramètres
    disponibles, quelle qu'en soit la provenance, et **la provenance voyage
    avec lui** jusqu'à l'écran (règle absolue 5).

    Reste le cas « aucun modèle » : un vélo dont l'usage n'est dans aucune
    catégorie de `physique.litterature` n'a que des défauts muets, et un temps
    calculé là-dessus vaudrait moins que la vitesse moyenne assumée. Même
    repli si `--puissance` n'est pas donné et que la FTP n'est pas renseignée
    dans la configuration : rien pour construire une puissance par défaut,
    donc pas de colonne « temps » plutôt qu'un calcul sur une valeur inventée.
    """
    from ourouler.physique.commande import (
        alerte_calibration,
        chemin_calibration,
        parametres_du_velo,
        puissance_voulue,
        velo_demande,
    )

    velo = velo_demande(config, getattr(args, "velo", None))
    parametres, provenance = parametres_du_velo(config, velo, chemin_calibration(config))
    if provenance == "défaut":
        return None
    puissance = puissance_voulue(args, parametres)
    if puissance is None:
        if config.cycliste.ftp_w is None:
            return None
        puissance = config.cycliste.ftp_w * PART_FTP_DEFAUT
    if not math.isfinite(puissance) or puissance <= 0:
        raise ErreurUtilisateur(
            f"--puissance {puissance} : une puissance en watts strictement positive est attendue"
        )
    return ModeleTemps(
        parametres=parametres,
        puissance_w=float(puissance),
        velo=velo.nom,
        provenance=provenance,
        usage=velo.usage,
        alerte=alerte_calibration(velo, chemin_calibration(config)) or "",
    )


def _info_compteur(
    config: Config,
    nom_velo: str | None,
    *,
    puissance_w: float | None = None,
    vitesse_a_plat_kmh: float | None = None,
) -> dict | None:
    """Le bloc « compteur » de la réponse — délégué, voir `ecran_ftp.info_compteur`.

    `puissance_w`/`vitesse_a_plat_kmh` : `--puissance`/`--vitesse-a-plat`
    telles que `lire_options` les a déjà validées (exclusives) — la puissance
    demandée pour CE parcours-ci, transmise telle quelle pour que la moyenne
    compteur qui chronomètre le porte à porte la suive (voir le bug du
    18/09/2026 : sans ça, 150 W et 300 W rendaient le même temps écoulé).
    `None`, `None` (l'appel par défaut) garde le comportement d'avant :
    la puissance d'endurance de la configuration.

    `None` sans vélo dans la configuration : `rendre_json`/`rendre_texte` en
    déduisent alors qu'il n'y a pas de `temps_ecoule_s` à calculer non plus.
    """
    from ourouler.seance.ecran_ftp import info_compteur

    return info_compteur(
        config, nom_velo, puissance_w=puissance_w, vitesse_a_plat_kmh=vitesse_a_plat_kmh
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

    # `--puissance` et `--vitesse-a-plat` sont exclusives : le refus se dit
    # ici, avant tout appel à BRouter ou à Open-Meteo (contrat §6). La
    # conversion, elle, a besoin du vélo et attend `_modele_temps`.
    if getattr(args, "puissance", None) is not None and (
        getattr(args, "vitesse_a_plat", None) is not None
    ):
        raise ErreurUtilisateur(
            "--puissance et --vitesse-a-plat disent la même chose de deux façons "
            "(la seconde se convertit en watts par le modèle du vélo) : n'en donner qu'une."
        )

    distance_km = getattr(args, "distance", None)
    direction = getattr(args, "direction", None)
    # Sans `--direction`, la recherche balaie tout l'horizon plutôt que de
    # refuser (Q47) — même défaut que `sortie` : « peu importe » est une
    # demande valable, pas une omission à corriger.
    libelle, azimut = ("", None)
    if direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    if chemin_gpx is None:
        if distance_km is None:
            raise ErreurUtilisateur(
                "boucle : --distance KM est obligatoire (ou --gpx pour évaluer un fichier existant)"
            )
        if not math.isfinite(distance_km) or distance_km <= 0:
            raise ErreurUtilisateur(
                f"--distance {distance_km} : une distance en kilomètres strictement positive est attendue"
            )

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

    pauses = tuple(analyser_pause(p) for p in getattr(args, "pause", None) or [])
    # Sans `--gpx`, `distance_km` (la distance **demandée**) est la seule
    # longueur connue avant tout appel BRouter — les candidates réellement
    # générées peuvent différer dans la tolérance du contrat, mais une pause
    # au-delà de ce qui a été demandé est déjà une erreur d'entrée. Avec
    # `--gpx`, la longueur réelle du tracé n'est connue qu'après lecture du
    # fichier : `executer` revalide alors contre elle (voir plus bas).
    valider_pauses(pauses, distance_m=distance_km * 1000.0 if distance_km is not None else None)

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
        pauses=pauses,
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
    pauses: tuple[Pause, ...] = (),
) -> tuple[list[MeteoTrace | None], str | None, list[float]]:
    """La météo de chaque tracé, le motif de panne s'il y en a un, et les vitesses retenues.

    Dès qu'un appel échoue, on cesse d'insister : si Open-Meteo est
    injoignable pour la première candidate, il l'est pour les quatre autres,
    et attendre cinq timeouts ne rend service à personne.

    L'heure de passage en un point vaut `départ + distance / vitesse + pauses
    situées avant`. Cette vitesse était celle de la configuration (27 km/h),
    la même pour un plat-pays que pour une boucle à 900 m de D+ ; quand le
    vélo est calibré, c'est **le modèle** qui la donne, tracé par tracé. Les
    pauses, elles, sont les mêmes pour toutes les candidates — déclarées en
    kilomètres du parcours, pas en fonction de l'une d'elles.
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
                    horaire=construire_horaire(depart, vitesse, pauses),
                    modele=config.meteo.modele,
                    second_avis=config.meteo.second_avis,
                    # Repli Q19, **le même que `ourouler sortie`**. Il y
                    # manquait ici, et c'est exactement le piège que Q19
                    # décrit : le modèle régional s'arrête en cours de J+2, et
                    # une boucle demandée à J+3 perdait *toute* sa météo — pas
                    # une colonne, toutes — avec un message qui parle du
                    # « domaine » du modèle là où c'est sa portée temporelle
                    # qui est en cause. Corrigé sur un chemin et pas sur
                    # l'autre : les deux commandes appellent le même
                    # `meteo_trace.evaluer`, elles lui passent maintenant le
                    # même repli.
                    modele_repli=config.meteo.second_avis,
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
                # `getattr` parce qu'un GPX importé n'a pas de candidate : la
                # question de l'écart à une cible ne se pose alors pas.
                elargissement=getattr(candidate, "elargissement", None),
                tolerance_distance=getattr(candidate, "tolerance", None),
                part_connue=base.part_connue(trace) if base is not None else None,
                temps_s=_temps_modele(trace, meteo, modele),
                vitesse_meteo_kmh=vitesse,
                marqueurs=compter_marqueurs(trace),
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
    """`boucle_<direction>_<distance>km_<AAAAMMJJ-HHMM>.gpx` (contrat §6).

    Sans `--direction` (Q47 : la recherche balaie alors tout l'horizon), le
    nom porte `toutes-directions` plutôt qu'un blanc illisible.
    """
    distance = f"{demande.distance_km:g}" if demande.distance_km is not None else "0"
    direction = demande.direction or "toutes-directions"
    return f"boucle_{direction}_{distance}km_{demande.depart:%Y%m%d-%H%M}.gpx"


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
    ("feux", "feux"),
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
    compteur_info: dict | None = None,
) -> str:
    """Le tableau des candidates, la ligne retenue marquée d'une flèche."""
    presentes = _mesures_presentes(evaluations)
    lignes = _entete(
        demande, config, "meteo" in presentes, poids, evaluations, modele, compteur_info
    )

    titres = _titres(presentes, elaguees=demande.gpx is None, config=config, modele=modele)
    cellules = [_cellules(e, config, presentes, compteur_info) for e in evaluations]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for evaluation, ligne in zip(evaluations, cellules, strict=True):
        retenue = evaluation is evaluations[0] and demande.gpx is None
        marque = f"{MARQUE_RETENUE} " if retenue else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if compteur_info is not None:
        lignes.append(ligne_temps_ecoule(compteur_info))
    if any(e.trace.meta.get("couts_partiels") for e in evaluations):
        lignes.append(
            f"{ABSENT} : tracé sans tags de route (GPX importé) — trafic et revêtement inconnus."
        )
    ligne_rapprochement = _ligne_rapprochement_tags(evaluations)
    if ligne_rapprochement is not None:
        lignes.append(ligne_rapprochement)
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
    lignes += lignes_elargissement(evaluations, demande.distance_km)
    if chemin is not None:
        lignes.append(
            f"{MARQUE_RETENUE} retenue : n° {evaluations[0].numero}"
            f"{_porte_a_porte_retenue(evaluations[0], config, compteur_info)}, "
            f"écrite dans {chemin}"
        )
    return "\n".join(lignes)


def _porte_a_porte_retenue(
    evaluation: Evaluation, config: Config, compteur_info: dict | None
) -> str:
    """« , entre 4 h 23 et 4 h 38 porte à porte » — ou rien sans fourchette."""
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None or compteur_info is None:
        return ""
    return f", {texte_entre(porte_a_porte(mouvement_s, compteur_info))} porte à porte"


def lignes_elargissement(evaluations, distance_km: float | None) -> list[str]:
    """« On n'a pas trouvé de boucle dans les contraintes, on a élargi de X %. »

    Les mots sont ceux du mainteneur (Q41 d). Rien ne s'affiche quand toutes
    les boucles tiennent dans la tolérance — c'est le cas normal, et une
    ligne qui signale ce qui ne compte pas apprend à ne plus lire la ligne
    (même raison que `SEUIL_ECART_DUREE` dans `sortie/commande.py`).

    Partagée avec `sortie`, qui rend le même fait dans un autre tableau : le
    cycliste n'a pas à apprendre deux formulations pour une seule notion.
    """
    elargies = [e for e in evaluations if e.elargissement]
    if not elargies or distance_km is None:
        return []
    tolerance = next((e.tolerance_distance for e in elargies if e.tolerance_distance), None)
    if tolerance is None:
        return []
    palier_max = max(e.elargissement or 0.0 for e in elargies)
    numeros = ", ".join(f"n° {e.numero}" for e in elargies)
    lignes = [
        f"Aucune boucle à ±{tolerance:.0%} de {_fr(distance_km, 0)} km : la tolérance a été "
        f"élargie de {palier_max:.0%}, soit ±{tolerance + palier_max:.0%} ({numeros})."
    ]
    for e in elargies:
        lignes.append(
            f"    n° {e.numero} : {_fr(e.trace.distance_m / 1000, 1)} km, "
            f"{e.ecart_relatif:+.0%} de la distance demandée."
        )
    return lignes


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
    quand la calibration du vélo existe, `(modèle, littérature)` quand le
    modèle tourne sur des valeurs de catégorie jamais mesurées sur ce vélo,
    `(27 km/h)` — la vitesse moyenne de la configuration — quand il n'y a pas
    de modèle du tout. Sans ces mentions, deux exécutions du même ordre
    donnaient deux chiffres différents sans rien dire.
    """
    mention = mention_temps(modele, config)
    titres = [
        f"temps {mention}" if titre == "temps" else titre
        for titre, mesure in COLONNES
        if mesure is None or mesure in presentes
    ]
    if not elaguees:
        titres[titres.index(TITRE_ANTENNES_RETIREES)] = TITRE_ANTENNES_DETECTEES
    return titres


def mention_temps(modele: ModeleTemps | None, config: Config) -> str:
    """D'où sort le temps affiché, en trois mots — la source unique de la mention.

    Le titre de la colonne et la vitesse de l'entête la partagent : les voir
    diverger (« (modèle) » au-dessus d'un chiffre de littérature) serait
    exactement le « mensonge par mise en page » que la décision 8 du cycle UX
    interdit.
    """
    if modele is None:
        return f"({config.boucle.vitesse_moyenne_kmh:g} km/h)"
    return MENTION_MODELE if modele.calibre else MENTION_MODELE_LITTERATURE


def _vitesse_passage(
    config: Config,
    evaluations: list[Evaluation] | None,
    modele: ModeleTemps | None = None,
) -> str:
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
    mention = MENTION_MODELE if modele is None or modele.calibre else MENTION_MODELE_LITTERATURE
    return f"{moyenne:.1f} km/h {mention}{etendue}".replace(".", ",", 1)


def _ligne_rapprochement_tags(evaluations: list[Evaluation]) -> str | None:
    """« Tags de route rapprochés... » — d'où viennent les tags d'un GPX greffé.

    Règle absolue 5 : un tag **mesuré** par le moteur (une candidate générée)
    et un tag **deviné** par rapprochement (un GPX importé, `boucle.
    tags_importes`) ne sont pas la même chose, et l'écran doit le dire —
    avec le seuil retenu et la part de kilomètres qui n'a rien trouvé.
    `None` sans tracé greffé : rien à ajouter.
    """
    greffees = [
        e for e in evaluations if e.trace.meta.get("tags_provenance") == TAGS_PROVENANCE_RAPPROCHEMENT
    ]
    if not greffees:
        return None
    seuil = next((e.trace.meta.get("tags_seuil_m") for e in greffees), None)
    km_sans_tag = sum(float(e.trace.meta.get("tags_km_sans_tag") or 0.0) for e in greffees)
    return (
        f"Tags de route rapprochés du tracé rerouté par BRouter (seuil {seuil:g} m) : "
        f"{_fr(km_sans_tag, 1)} km n'ont trouvé aucun tronçon assez proche, comptés en "
        "routes non classées."
    )


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
    if any(e.marqueurs is not None and e.marqueurs.connue for e in evaluations):
        presentes.add("feux")
    return presentes


def _meteo_rendue(evaluations: list[Evaluation]) -> MeteoTrace | None:
    """La première météo réellement obtenue — celle qui sait quel modèle a répondu."""
    return next((e.meteo for e in evaluations if e.meteo is not None), None)


def _ligne_modele_meteo(evaluations: list[Evaluation], config: Config) -> str:
    """Nomme le modèle météo qui a **répondu**, et le dit haut quand c'est un repli.

    Cette ligne annonçait le modèle *configuré* et son second avis. Depuis que
    le repli de Q19 s'applique aussi à `boucle`, ce serait un mensonge une
    fois sur deux : le tableau montrerait la pluie d'`icon_seamless` sous un
    en-tête qui nomme AROME. Même phrase et même raison que
    `sortie.commande._ligne_modele_meteo` — règle absolue 5 : quand un seul
    des deux modèles a pu répondre, c'est encore une divergence à dire.
    """
    meteo = _meteo_rendue(evaluations)
    if meteo is None or not meteo.modele_utilise:
        return f"Météo {config.meteo.modele}, second avis {config.meteo.second_avis or 'aucun'}"
    if meteo.repli and meteo.bascule_dist_m is not None:
        # Repli **partiel** : le principal a répondu pour le début du
        # parcours, sa portée horaire s'arrête avant la fin (une nuit de
        # sommeil, par exemple) — les deux moitiés ne portent pas la même
        # qualité de prévision, et rien ne doit les confondre (règle
        # absolue 5).
        return (
            f"Météo {meteo.modele_utilise} jusqu'au kilomètre "
            f"{meteo.bascule_dist_m / 1000.0:g} — au-delà, {config.meteo.second_avis} "
            "(modèle de repli, hors de portée du principal)."
        )
    if meteo.repli:
        return (
            f"Météo : {config.meteo.modele} ne couvre pas cette fenêtre — bascule sur "
            f"{meteo.modele_utilise} (second avis, configuré en repli)."
        )
    return (
        f"Météo {meteo.modele_utilise}, second avis {config.meteo.second_avis or 'aucun'}"
    )


def _modele_meteo_json(evaluations: list[Evaluation]) -> dict | None:
    """L'équivalent JSON de `_ligne_modele_meteo` — `bascule_km` en plus, absent de `sortie`.

    `bascule_km` : `None` sans repli, ou avec un repli total dès le départ
    (`repli` seul le dit déjà) ; sinon le premier kilomètre où le repli a
    pris le relais du modèle principal (repli partiel).
    """
    meteo = _meteo_rendue(evaluations)
    if meteo is None or not meteo.modele_utilise:
        return None
    return {
        "utilise": meteo.modele_utilise,
        "repli": meteo.repli,
        "bascule_km": (
            round(meteo.bascule_dist_m / 1000.0, 3) if meteo.bascule_dist_m is not None else None
        ),
    }


def _litterature_json(modele: ModeleTemps) -> dict | None:
    """L'équivalent JSON de `_lignes_litterature` — délégué à `physique.commande`."""
    from ourouler.physique.commande import litterature_json

    return litterature_json(modele.provenance, modele.usage)


def _lignes_litterature(modele: ModeleTemps) -> list[str]:
    """La catégorie servie et sa dérive mesurée, ou rien. Délégué, jamais recalculé ici."""
    from ourouler.physique import litterature

    choix = litterature.pour_usage(modele.usage) if modele.provenance == "littérature" else None
    if choix is None:
        return []
    return [
        f"Catégorie {choix.resume}",
        f"Pour un temps mesuré sur vous : `ourouler calibrer --velo {modele.velo}`.",
    ]


def _entete(
    demande: Demande,
    config: Config,
    avec_meteo: bool,
    poids: dict[str, float] | None = None,
    evaluations: list[Evaluation] | None = None,
    modele: ModeleTemps | None = None,
    compteur_info: dict | None = None,
) -> list[str]:
    lignes = []
    if demande.gpx is not None:
        lignes.append(f"Tracé importé : {demande.gpx}")
    else:
        # Sans `--direction` (Q47), la recherche balaie tout l'horizon : il
        # n'y a alors pas un azimut à afficher, mais huit.
        direction = (
            f"{demande.direction} ({demande.azimut_deg:.0f}°)"
            if demande.azimut_deg is not None
            else "toutes directions"
        )
        lignes.append(
            f"Boucle depuis {config.depart.nom} — {demande.distance_km:g} km vers "
            f"{direction}, profil {demande.profil}"
        )
    lignes.append(
        f"Départ {date_en_francais(demande.depart)} — "
        f"{_vitesse_passage(config, evaluations, modele)} "
        f"(heures de passage météo), sens préféré {config.boucle.sens}"
    )
    if modele is not None and modele.calibre:
        lignes.append(
            f"Temps estimé par le modèle calibré du {modele.velo} à {modele.puissance_w:.0f} W "
            "— temps en mouvement, arrêts non modélisés"
        )
        if modele.alerte:
            lignes.append(f"⚠ Calibration du {modele.velo} : {modele.alerte}.")
    elif modele is not None:
        # Le modèle tourne, mais sur des CdA et Crr de catégorie : il le dit
        # ici comme le facteur compteur dit « supposé » (règle absolue 5).
        lignes.append(
            f"Temps estimé par le modèle du {modele.velo} à {modele.puissance_w:.0f} W, "
            f"sur des valeurs de {modele.provenance} — temps en mouvement, arrêts non modélisés"
        )
        lignes.extend(_lignes_litterature(modele))
    else:
        lignes.append(
            f"Temps estimé à {config.boucle.vitesse_moyenne_kmh:g} km/h : aucun modèle "
            "physique pour ce vélo (usage hors des catégories connues)"
        )
    if avec_meteo:
        lignes.append(_ligne_modele_meteo(evaluations or [], config))
    ligne_pauses = _ligne_pauses(demande, evaluations or [], config, compteur_info)
    if ligne_pauses is not None:
        lignes.append(ligne_pauses)
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


def _cellules(
    evaluation: Evaluation, config: Config, presentes: set[str], compteur_info: dict | None = None
) -> list[str]:
    couts, meteo = evaluation.couts, evaluation.meteo
    partiels = bool(evaluation.trace.meta.get("couts_partiels"))
    cellules = [
        str(evaluation.numero),
        f"{_fr(evaluation.trace.distance_m / 1000, 1)} km",
        _denivele(evaluation.trace),
        _temps(evaluation, config, compteur_info),
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
    if "feux" in presentes:
        marqueurs = evaluation.marqueurs
        cellules.append(
            str(marqueurs.par_nature.get("traffic_signals", 0))
            if marqueurs is not None and marqueurs.connue
            else ABSENT
        )
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


def _temps_mouvement_s(evaluation: Evaluation, config: Config) -> float | None:
    """Le temps en mouvement, en secondes — celui du modèle s'il y en a un, sinon
    celui de la vitesse moyenne de la configuration. `None` si ni l'un ni
    l'autre n'est disponible (vitesse moyenne nulle ou non configurée)."""
    if evaluation.temps_s is not None:
        return evaluation.temps_s
    vitesse = config.boucle.vitesse_moyenne_kmh
    if vitesse <= 0:
        return None
    return evaluation.trace.distance_m / 1000 / vitesse * 3600


def _temps_ecoule_s(
    evaluation: Evaluation, config: Config, compteur_info: dict | None
) -> float | None:
    """Le temps écoulé porte à porte **médian**, en secondes — sans les pauses déclarées.

    La médiane de la fourchette du vélo (`porte_a_porte`) quand un vélo en
    donne une ; à défaut, le temps en mouvement tel quel. `None` si même
    celui-ci manque. Les pauses s'ajoutent par-dessus, ailleurs
    (`_duree_pauses_s` + ce résultat) : la fourchette ne les connaît pas, et
    ne doit pas les connaître — les compter ici *et* les ajouter ensuite les
    compterait deux fois.
    """
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None:
        return None
    if compteur_info is None:
        return mouvement_s
    return porte_a_porte(mouvement_s, compteur_info).mediane_s


def porte_a_porte(mouvement_s: float, compteur_info: dict) -> PorteAPorte:
    """`temps_ecoule(mouvement_s, fourchette du vélo)` — la fourchette lue dans le bloc compteur.

    **Publique** : `sortie.commande` chronomètre ses propositions de la même
    façon, sans réécrire la lecture du bloc.
    """
    brut = compteur_info["porte_a_porte"]
    fourchette = FourchettePorteAPorte(
        bas=brut["bas"],
        mediane=brut["mediane"],
        haut=brut["haut"],
        provenance=brut["provenance"],
        n=brut.get("n", 0),
    )
    return temps_ecoule(mouvement_s, fourchette)


def _duree_pauses_s(pauses: Sequence[Pause]) -> float:
    return sum(p.duree_s for p in pauses)


def _heure_arrivee(
    evaluation: Evaluation, demande: Demande, config: Config, compteur_info: dict | None
) -> datetime | None:
    """`depart + temps écoulé porte à porte + pauses déclarées` — l'heure de la pendule.

    `None` si aucun temps de base n'est calculable (pas de vitesse moyenne
    configurée et pas de modèle physique) : pas d'heure à annoncer plutôt
    qu'une heure fausse.
    """
    ecoule_s = _temps_ecoule_s(evaluation, config, compteur_info)
    if ecoule_s is None:
        return None
    return demande.depart + timedelta(seconds=ecoule_s + _duree_pauses_s(demande.pauses))


def _ligne_pauses(
    demande: Demande,
    evaluations: list[Evaluation],
    config: Config,
    compteur_info: dict | None,
) -> str | None:
    """« Pauses : 2 déclarée(s), 1:15 au total — arrivée estimée … (n° 1). »

    `None` sans pause déclarée : pas de ligne pour ne rien dire. L'arrivée
    est celle de la candidate retenue (`evaluations[0]`, la même que celle
    qu'annonce déjà `_ecrire_meilleure`) — chaque candidate a son propre
    temps de base, une seule ligne d'en-tête ne peut pas toutes les dire.
    """
    if not demande.pauses:
        return None
    retenue = evaluations[0]
    total_texte = _duree_texte(_duree_pauses_s(demande.pauses))
    n = len(demande.pauses)
    arrivee = _heure_arrivee(retenue, demande, config, compteur_info)
    if arrivee is None:
        return (
            f"Pauses : {n} déclarée(s), {total_texte} au total — s'ajoutent par-dessus le "
            "temps écoulé porte à porte, jamais confondues avec lui (arrivée non estimable "
            "sans temps de base)."
        )
    return (
        f"Pauses : {n} déclarée(s), {total_texte} au total — s'ajoutent par-dessus le temps "
        f"écoulé porte à porte, jamais confondues avec lui. Arrivée estimée : "
        f"{date_en_francais(arrivee)} (n° {retenue.numero})."
    )


def _temps(evaluation: Evaluation, config: Config, compteur_info: dict | None = None) -> str:
    """« 2:14 » seul, ou « 2:20-2:24 / 2:14 » — porte à porte en fourchette /
    mouvement — dès qu'un vélo donne une fourchette (voir `ligne_temps_ecoule`).

    **L'écoulé vient en premier** (18/09/2026). Le mainteneur l'a tranché
    pour l'écran, et la CLI ne dit pas l'inverse : « je demande 5 h, je veux
    5 h, pas 4 h et un truc plus loin qui me dit en fait c'est 5 h ». Le
    premier chiffre est donc celui qui répond à la durée demandée ; le
    second dit ce que ça donnerait sans un seul arrêt.
    """
    mouvement_s = _temps_mouvement_s(evaluation, config)
    if mouvement_s is None:
        return ABSENT
    if compteur_info is None:
        return _duree_texte(mouvement_s)
    pp = porte_a_porte(mouvement_s, compteur_info)
    return f"{_duree_texte(pp.bas_s)}-{_duree_texte(pp.haut_s)} / {_duree_texte(mouvement_s)}"


def texte_entre(pp: PorteAPorte) -> str:
    """« entre 4 h 23 et 4 h 38 » — la fourchette du porte à porte, en toutes lettres.

    Publique : `sortie.commande` dit la sienne avec les mêmes mots.
    """
    return f"entre {_heures_minutes(pp.bas_s)} et {_heures_minutes(pp.haut_s)}"


def _heures_minutes(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60} h {minutes % 60:02d}"


def provenance_fourchette(compteur_info: dict) -> str:
    """D'où vient la fourchette du vélo, en une incise : mesurée sur ses sorties ou convention.

    Règle absolue 5 : la convention ne se présente jamais comme une mesure.
    """
    brut = compteur_info["porte_a_porte"]
    if brut["provenance"] == "mesure":
        return f"mesurée sur {brut['n']} sorties du {compteur_info['velo']} roulées seul"
    return "convention, mesurée sur un seul cycliste — pas encore sur vos sorties"


def ligne_temps_ecoule(compteur_info: dict) -> str:
    """La légende sous le tableau : ce que veut dire « 2:20-2:31 / 2:14 » en colonne « temps ».

    Choix d'affichage (18/09/2026) : une cellule combinée plutôt qu'une
    colonne de plus — le tableau en a déjà treize, une quatorzième pour un
    seul chiffre de plus n'aurait pas tenu en largeur de terminal. La CLI et
    le JSON disent la même chose : `temps_estime_s`/`temps_ecoule_s`.

    **Publique et non préfixée** : `sortie.commande` l'appelle telle quelle
    plutôt que de réécrire la même phrase pour son propre tableau — même
    raison que `lignes_elargissement` juste au-dessus.

    Ce temps écoulé ne connaît pas les pauses déclarées (`--pause`) : elles
    couvrent un arrêt volontaire (repas, nuit), la fourchette couvre déjà les
    feux et les micro-arrêts. Une pause déclarée s'ajoute **par-dessus** ce
    chiffre, voir `_ligne_pauses` — les compter ici reviendrait à les compter
    deux fois.

    Depuis L9.1 (25/09/2026) le porte à porte est le temps sans arrêt de ce
    tracé-ci multiplié par la fourchette du vélo : la moyenne compteur ne le
    chronomètre plus, elle ne sert qu'à choisir la distance.
    """
    brut = compteur_info["porte_a_porte"]
    return (
        "Temps affiché : porte à porte, arrêts compris / sans un seul arrêt — le porte "
        f"à porte est le temps sans arrêt × {_fr(brut['bas'], 2)} à × {_fr(brut['haut'], 2)} "
        f"({provenance_fourchette(compteur_info)}) : la moitié des sorties tombe dans "
        "cette fourchette."
    )


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
    meteo_absente: portee.MeteoAbsente | None = None,
    compteur_info: dict | None = None,
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
        # Les pauses **telles que déclarées** (`--pause`, répétable) : jamais
        # celles réellement appliquées par candidate (une pause au-delà d'une
        # candidate plus courte que la cible n'y a simplement aucun effet,
        # voir `boucle.horaire`) — ce que l'utilisateur a demandé, pas une
        # réinterprétation par tracé.
        "pauses": [
            {"km": round(p.dist_m / 1000.0, 3), "duree_s": round(p.duree_s)}
            for p in demande.pauses
        ],
        # La troisième valeur de l'écran de FTP (`ecran_ftp.info_compteur`),
        # publiée ici pour que `temps_ecoule_s` de chaque candidate se
        # vérifie de tête : `null` sans vélo dans la configuration — pas de
        # modèle physique, pas de facteur, rien à réconcilier.
        "compteur": compteur_info,
        "vitesse_moyenne_kmh": config.boucle.vitesse_moyenne_kmh,
        "sens_prefere": config.boucle.sens,
        "modele": config.meteo.modele,
        "second_avis": config.meteo.second_avis,
        # Ce qui a **répondu**, à côté de ce qui est configuré. Même forme que
        # `sortie` (`{utilise, repli}`), pour qu'un écran lise le repli de Q19
        # de la même façon sur les deux routes de parcours. `null` quand
        # aucune candidate n'a de météo.
        "modele_meteo": _modele_meteo_json(evaluations),
        # Q40 (a) : l'état « pas de météo », dit une fois. `null` quand la
        # météo a répondu. Voir `meteo.portee`.
        "meteo_absente": None if meteo_absente is None else meteo_absente.json(),
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
            # Le même fait qu'en texte, en un booléen et un bloc : un client
            # qui ne lit que `provenance` afficherait un temps de littérature
            # comme un temps mesuré (règle absolue 5).
            "mesure": modele.calibre,
            "litterature": _litterature_json(modele),
            "alerte": modele.alerte or None,
        },
        "candidates": [
            _candidate_json(e, demande, config, chemin, compteur_info) for e in evaluations
        ],
    }


def _candidate_json(
    evaluation: Evaluation,
    demande: Demande,
    config: Config,
    chemin: Path | None,
    compteur_info: dict | None = None,
) -> dict:
    couts, meteo = evaluation.couts, evaluation.meteo
    trace = evaluation.trace
    distance_km = trace.distance_m / 1000.0
    # Identique à l'ancien calcul de `temps_estime_s` (INCHANGÉ) : pas de
    # garde-fou sur `vitesse_moyenne_kmh` ici, `config` la valide déjà
    # strictement positive au chargement. `_temps_mouvement_s`, elle, protège
    # le rendu texte d'une configuration construite à la main (tests).
    mouvement_s = (
        evaluation.temps_s
        if evaluation.temps_s is not None
        else distance_km / config.boucle.vitesse_moyenne_kmh * 3600
    )
    temps_ecoule_s = temps_ecoule_bas_s = temps_ecoule_haut_s = temps_ecoule_source = None
    ecoule_base_s = mouvement_s  # non arrondi : sert à `heure_arrivee`, voir plus bas
    if compteur_info is not None:
        pp = porte_a_porte(mouvement_s, compteur_info)
        temps_ecoule_s = round(pp.mediane_s)
        temps_ecoule_bas_s, temps_ecoule_haut_s = round(pp.bas_s), round(pp.haut_s)
        temps_ecoule_source = pp.provenance
        ecoule_base_s = pp.mediane_s
    # L'heure de la pendule : temps écoulé porte à porte (ou, à défaut, le
    # temps en mouvement) **plus** les pauses déclarées — jamais confondues
    # avec le facteur compteur, qui couvre déjà feux et micro-arrêts (voir
    # `_ligne_pauses`). `ecoule_base_s` **non arrondi** : arrondir à la
    # seconde avant d'ajouter les pauses (`temps_ecoule_s`, arrondi pour
    # l'affichage de cette seule valeur) décalait l'heure affichée d'une
    # minute entière une fois sur deux, une fois formatée à la minute près.
    pauses_s = _duree_pauses_s(demande.pauses)
    heure_arrivee = demande.depart + timedelta(seconds=ecoule_base_s + pauses_s)
    return {
        "numero": evaluation.numero,
        "retenue": evaluation.numero == 1 and chemin is not None,
        "nom": trace.nom,
        "distance_km": round(distance_km, 3),
        "denivele_m": trace.denivele_m,
        "denivele_source": trace.meta.get("denivele_source"),
        "temps_estime_s": round(mouvement_s),
        "temps_source": "modele" if evaluation.temps_s is not None else "vitesse_moyenne",
        # Le porte à porte, arrêts compris (`physique.modele.temps_ecoule`) —
        # jamais à la place de `temps_estime_s`, à côté (décision du
        # mainteneur, 18/09/2026). Depuis L9.1, une fourchette :
        # `temps_ecoule_s` en est la médiane (gardé pour compatibilité),
        # `_bas_s`/`_haut_s` les bornes (centiles 25 et 75), et la source dit
        # « mesure » (sorties du vélo) ou « defaut » (convention). `null` avec
        # `compteur` : sans vélo, pas de fourchette.
        "temps_ecoule_s": temps_ecoule_s,
        "temps_ecoule_bas_s": temps_ecoule_bas_s,
        "temps_ecoule_haut_s": temps_ecoule_haut_s,
        "temps_ecoule_source": temps_ecoule_source,
        # L'heure d'arrivée annoncée, pauses comprises — voir le commentaire
        # au-dessus du calcul de `heure_arrivee`.
        "heure_arrivee": heure_arrivee.isoformat(),
        "vitesse_meteo_kmh": (
            None
            if evaluation.vitesse_meteo_kmh is None
            else round(evaluation.vitesse_meteo_kmh, 2)
        ),
        "azimut_deg": evaluation.azimut_deg,
        "rayon_m": evaluation.rayon_m,
        "ecart_relatif": evaluation.ecart_relatif,
        # L'écart cesse d'être tu : trois champs, pas un commentaire. Un
        # client qui n'affiche que `distance_km` continue de marcher, un
        # client qui veut expliquer a de quoi le faire (Q41 d).
        "hors_tolerance": bool(evaluation.elargissement),
        "elargissement": evaluation.elargissement,
        "tolerance_distance": evaluation.tolerance_distance,
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
        "marqueurs": _marqueurs_json(evaluation.marqueurs),
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
        # Lot F0.1 : la géométrie n'existait dans aucun JSON, seulement dans
        # le GPX écrit sur disque (`docs/journal/ux/discovery_donnees.md` §2). Voir
        # `boucle.geometrie` pour la forme et la simplification appliquée.
        "trace": geometrie_json(trace),
    }


def _marqueurs_json(marqueurs: Marqueurs | None) -> dict | None:
    """Feux, stops et densité de marqueurs — même vocabulaire que `sortie.contraste`.

    `connue` faux (ou `marqueurs` absent) : le tracé ne porte pas de
    `segments`, `feux`/`stops` valent alors `None`, jamais 0 — un GPX qui n'a
    pas pu être rapproché ne dit pas « aucun feu », il dit « je ne sais pas ».
    """
    if marqueurs is None or not marqueurs.connue:
        return {"connue": False, "feux": None, "stops": None, "nombre": None, "par_km": None}
    return {
        "connue": True,
        "feux": marqueurs.par_nature.get("traffic_signals", 0),
        "stops": marqueurs.par_nature.get("stop", 0),
        "nombre": marqueurs.nombre,
        "par_km": round(marqueurs.par_km, 3) if marqueurs.par_km is not None else None,
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
        # Les flèches à dessiner le long du tracé, position comprise, déjà
        # filtrées au seuil où le vent se sent (`meteo_trace.fleches_vent`).
        # C'est **la règle du cœur, pas une liste brute** : un écran qui
        # recevrait tous les échantillons devrait réappliquer le seuil de
        # 8 km/h lui-même, donc le réinventer, donc pouvoir en diverger.
        # Les `echantillons` ci-dessous restent tels quels, sans position :
        # ils servent à autre chose, et les doubler serait du poids pour rien.
        "fleches_vent": fleches_vent(meteo),
        "echantillons": [
            {
                "dist_m": round(e.dist_m, 1),
                "t": e.t.isoformat(),
                "cap_deg": round(e.cap_deg, 1),
                "pluie_mm": e.pluie_mm,
                "vent_kmh": e.vent_kmh,
                "vent_relatif": e.vent_relatif,
                "ressenti_c": e.ressenti_c,
                # Le modèle qui a renseigné **cet** échantillon précisément —
                # `null` si ni le principal ni le repli ne le couvrent. Voir
                # `_modele_meteo_json` pour le premier kilomètre où ça change.
                "modele": e.modele,
            }
            for e in meteo.echantillons
        ],
    }

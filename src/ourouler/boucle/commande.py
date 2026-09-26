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
from datetime import date, datetime
from pathlib import Path

from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes, lire_poids, points_de_passage_depuis_coordonnees
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.gpx import ecrire_gpx, lire_gpx_trace
from ourouler.boucle.horaire import Pause, analyser_pause, construire_horaire, valider_pauses
from ourouler.boucle.marqueurs import Marqueurs
from ourouler.boucle.marqueurs import compter as compter_marqueurs
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.boucle.tags_importes import greffer
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.meteo import portee
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.couronne import NOMS_DIRECTIONS, NOMS_DIRECTIONS_16, azimut_de
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import (
    ErreurConfig,
    ErreurConnecteur,
    ErreurDistanceInatteignable,
    ErreurUtilisateur,
)
from ourouler.noyau.profil import Depart
from ourouler.noyau.trace import DENIVELE_REROUTE, Trace, denivele_filtre

#: Poids de la pluie dans le tri du tableau : un millimètre cumulé coûte
#: autant que deux kilomètres équivalents de score (contrat §6).
POIDS_PLUIE_TRI = 2.0

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

    # Le rendu (lot 6) : ce module mesure et écrit, `rendu/boucle.py` met en
    # mots et en JSON. Import différé : le rendu importe les types d'ici.
    from ourouler.rendu.boucle import avertissement_meteo, rendre_json, rendre_texte

    avertissement = avertissement_meteo(panne, meteo_absente)
    if avertissement is not None:
        print(avertissement, file=sys.stderr)
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

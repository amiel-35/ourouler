"""Sous-commande `ourouler sortie` : la séance du jour, posée sur une boucle.

L'enchaînement est celui du contrat du sprint 4 §4 :

1. la **séance du jour** est lue chez Intervals.icu (lot L4.1) ; s'il n'y en a
   pas, on le dit et on sort en 0 — ce n'est pas une erreur ;
1 bis. la **question de l'orientation au vent** est posée **avant** la
   recherche (lot L5.3) : un appel Open-Meteo sur un point et une heure, donc
   le poste le moins cher, et il tombe avant BRouter. Elle ne se pose que si
   le vent se sent (8 km/h, `seance.vent.SEUIL_VENT_SENSIBLE_KMH`) et à trois
   jours au plus. Quand elle a une réponse (`--vent`), elle **dirige** la
   recherche au lieu de contraster après coup ;
2. des **boucles candidates** sont demandées au moteur (lot L2.3), de la
   longueur qu'il faut pour la séance ;
3. chacune reçoit un premier **placement** des blocs, sans vent (lot L4.3).
   Celles où la séance ne tient pas sont écartées, et le tableau dit combien
   et pourquoi ;
4. sur les retenues : ce premier placement date une météo qui n'a qu'un but,
   donner le **champ de vent** le long du tracé (lot L5.1) — et la séance est
   **replacée** avec ce vent. C'est une deuxième passe, pas une itération : le
   vent bouge lentement et l'écart d'heure de passage qu'induit le premier
   placement se compte en minutes (contrat §1.2 d, §1.6) ;
5. sur les retenues, avec leur placement définitif : **coûts** du tracé
   (L2.4), **météo** à l'heure de passage définitive (L2.5) et **tenue**
   (L4.3) ;
6. tri par **note de placement d'abord** — elle inclut le vent depuis le
   sprint 5 —, puis par **pluie cumulée** quand deux notes sont égales à
   `config.seance.tolerance_egalite` près ;
7. la meilleure part en **GPX** sur disque (le parcours qu'on va rouler) ;
8. et **deux ou trois propositions contrastées** sont extraites de ce
   classement (lot L5.3, `sortie.contraste`), chacune avec la phrase qui la
   distingue des autres en langage de cycliste. La première reste celle du
   tri : on ne change pas ce que l'outil recommande, on ajoute ce à quoi le
   comparer. Quand aucune phrase n'est écrivable pour une troisième, on en
   rend deux et on dit pourquoi ;
9. et ces mêmes propositions deviennent **la page du jour** (lot L5.4,
   `sortie.carte.construire_page_jour`) : une carte, les tracés superposés,
   seule la sélectionnée en couleurs — et un GPX par proposition,
   téléchargeable depuis la page, qui suit le choix du cycliste et non le
   classement.

L'ordre du tri est celui du contrat et il n'est pas anodin : la pluie se
contourne en partant une heure plus tard, un bloc de seuil dans un village ne
se contourne pas, et depuis le sprint 5 un vent de face non plus. La météo
départage, elle ne décide pas — sauf à égalité de note, où c'est elle qui
tranche entre deux boucles que le terrain et le vent ne distinguent pas.

Ce module est la couche commande : c'est lui qui lit `calibration.json` et
`poids_routes.json` (par les fonctions qui savent où ils sont) et qui passe
des objets au cœur. Les trois clients — BRouter, Open-Meteo, Intervals — sont
injectables pour que les tests ne touchent jamais le réseau.

**`--fichier-seance`** (F1) : l'étape 1 lit alors un `.ZWO`/`.MRC` donné en
ligne de commande au lieu d'interroger Intervals.icu — `_seance` bascule
dessus quand `demande.fichier` est renseigné, tout le reste de l'enchaînement
est inchangé (comble C1 de `docs/journal/ux/relecture_f0.md`).

**Ce que la météo n'empêche pas.** Comme pour `boucle`, une panne d'Open-Meteo
fait disparaître les colonnes météo et la tenue, avec un avertissement sur la
sortie d'erreur : perdre la séance parce qu'il manque la pluie serait absurde.
C'est le cas normal pour un `--jour` passé, hors de l'horizon de prévision.
"""

from __future__ import annotations

import argparse
import functools
import json
import math
import sys
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes, lire_poids
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.commande import (
    direction_en_azimut,
    ligne_temps_ecoule,
    lignes_elargissement,
    porte_a_porte,
)
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.geometrie import geometrie_json
from ourouler.boucle.gpx import description as description_gpx
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.boucle.horaire import construire_horaire
from ourouler.boucle.meteo_trace import MeteoTrace, fleches_vent, vent_par_position
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.config import Config, Depart
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo import portee
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.couronne import nom_de_azimut
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import date_en_francais
from ourouler.noyau.erreurs import (
    ErreurConnecteur,
    ErreurDistanceInatteignable,
    ErreurIntervalsAbsent,
    ErreurUtilisateur,
)
from ourouler.noyau.trace import Trace
from ourouler.physique.modele import Parametres, vitesse_a_plat_ms
from ourouler.seance.commande import longueurs
from ourouler.seance.ecran_ftp import info_compteur
from ourouler.seance.intervals import seance_du_jour
from ourouler.seance.modele import Seance
from ourouler.seance.placement import CLE_MOTIF, Emplacement, Placement, placer, trace_parcourue
from ourouler.seance.tenue import Tenue
from ourouler.seance.tenue import conseiller as conseiller_tenue
from ourouler.seance.vent import ChampVent
from ourouler.sortie import contraste, orientation, vent_demande
from ourouler.sortie.carte import PropositionCarte, construire_page_jour, construire_page_sans_seance

#: Multiple auquel la distance déduite de la séance est arrondie, **vers le
#: haut** : une séance de 72 km demande une boucle de 75 km. Vers le haut et
#: pas au plus proche, parce que le retour au calme absorbe le surplus (c'est
#: son rôle) alors que rien ne rattrape une boucle trop courte — la séance n'y
#: tiendrait pas, et `placer` rendrait `None`.
ARRONDI_DISTANCE_KM = 5.0

#: Sous cette note, un bloc est compté comme « bien placé » dans la colonne
#: du tableau. **Un arbitrage, pas une mesure** : 1,0 kilomètre équivalent,
#: c'est exactement ce que `seance.terrain.POIDS_CARREFOUR` fait payer un
#: unique feu rouge. Un couloir qui coûte moins qu'un feu est propre ; la
#: note complète, elle, reste affichée à côté et c'est elle qui trie.
NOTE_BLOC_BIEN_PLACE = 1.0

#: Marque de la ligne retenue dans le tableau texte (même signe que `boucle`).
MARQUE_RETENUE = "→"

#: Ce qu'on affiche à la place d'une mesure absente — jamais un zéro.
ABSENT = "—"

#: Poids de la pluie dans le tri, **à note de placement égale** : c'est le
#: même millimètre que dans `boucle`, mais il n'arrive qu'en second critère.
POIDS_PLUIE_TRI = 2.0


@dataclass(frozen=True)
class Demande:
    """Ce que l'utilisateur a demandé, validé **avant** tout appel réseau."""

    jour: date
    distance_km: float | None  # None : à déduire de la séance
    direction: str  # libellé normalisé, vide si aucune direction demandée
    azimut_deg: float | None
    nb_candidates: int
    profil: str
    depart: datetime
    velo: str | None
    sortie: Path | None
    carte: Path | None
    ecraser: bool = False
    #: Réponse à la question d'orientation au vent (`--vent`). « peu-importe »
    #: est le défaut **et une réponse valable** : elle retombe sur les
    #: propositions contrastées (contrat §3.3.4).
    vent: str = orientation.PEU_IMPORTE
    #: `--fichier-seance` (F1) : un `.ZWO`/`.MRC` à la place d'Intervals.icu.
    #: `None` — le cas courant — garde le comportement inchangé.
    fichier: Path | None = None


@dataclass
class Proposition:
    """Une candidate dont la séance tient : son tracé, son placement, ses mesures."""

    numero: int
    trace: Trace
    placement: Placement
    couts: Couts
    meteo: MeteoTrace | None
    azimut_deg: float | None
    ecart_relatif: float | None
    part_connue: float | None
    vitesse_kmh: float
    #: De combien la tolérance de distance a dû être élargie pour accepter
    #: cette boucle, par paliers de 5 % (Q41 d). `0.0` : elle y tenait.
    elargissement: float | None = None
    #: La tolérance de distance en vigueur quand la boucle a été jugée.
    tolerance_distance: float | None = None

    @property
    def pluie_mm(self) -> float:
        return self.meteo.pluie_cumulee_mm if self.meteo is not None else 0.0

    @property
    def blocs_bien_places(self) -> int:
        # `placement.blocs()`, jamais `placement.emplacements` : depuis le lot
        # L5.2, cette liste porte aussi l'échauffement, les récupérations et le
        # retour au calme, qui n'ont pas de note. `e.note.note` lèverait sur un
        # `None`, et un `e.note.note if e.note else 0.0` compterait ces
        # non-blocs comme « bien placés » — la régression silencieuse que le
        # contrat signale explicitement.
        return sum(1 for e in self.placement.blocs() if e.note.note < NOTE_BLOC_BIEN_PLACE)

    @property
    def demi_tours(self) -> int:
        # Idem : une récupération de demi-tour porte aussi `demi_tour=True`
        # (contrat §2.2 a)) — la compter en plus du bloc doublerait l'affichage.
        return sum(1 for e in self.placement.blocs() if e.demi_tour)

    @property
    def distance_parcours_m(self) -> float:
        """Ce qui sera **roulé**, demi-tours compris — pas le tour de la boucle."""
        return self.placement.distance_totale_m

    @property
    def denivele_parcours_m(self) -> float | None:
        """Le D+ recalculé sur le parcours placé, ou `None` si l'altitude manque.

        À ne pas confondre avec `trace.denivele_m`, qui est le « filtered
        ascend » du moteur pour la **boucle**. Les deux mesurent des choses
        différentes par deux méthodes différentes : voir `_note_denivele`.
        """
        return trace_parcourue(self.placement, self.trace).denivele_m

    @property
    def tri(self) -> tuple[float, float]:
        """Note de placement d'abord, pluie cumulée ensuite (contrat §4).

        **N'est pas le tri réellement appliqué par `executer`** depuis que le
        vent entre dans la note (sprint 5) : ce tuple compare les notes au
        bit près, alors que `executer` les compare à `tolerance_egalite`
        près (`_comparer`), pour laisser la pluie départager deux boucles que
        le terrain et le vent ne distinguent pas vraiment. Cette propriété
        reste utile telle quelle — introspection, tests — pour un jeu de
        candidates aux notes déjà nettement distinctes, où les deux tris
        s'accordent.
        """
        return (self.placement.note_totale, self.pluie_mm * POIDS_PLUIE_TRI)


#: Là où une candidate est tombée. `distance` : la génération n'a pas su faire
#: la distance dans cette direction, il n'y a donc aucun tracé à montrer.
#: `placement` : la boucle existe, c'est la séance qui n'y tenait pas — et
#: celle-là se dessine.
ETAPE_DISTANCE = "distance"
ETAPE_PLACEMENT = "placement"


@dataclass(frozen=True)
class Ecartee:
    """Une candidate que le placement a refusée, et le motif qu'il a rangé dans `meta`.

    `trace` est la boucle elle-même quand elle existe (lot F2.4). Un azimut et
    une distance ne se dessinent pas : sans la géométrie, « 8 candidates
    écartées » restait une ligne de texte que le mainteneur ne pouvait pas
    regarder. `None` pour un refus sur la distance — aucune boucle n'a été
    construite dans cette direction, et inventer un tracé serait pire que de
    n'en montrer aucun.
    """

    azimut_deg: float | None
    distance_km: float
    motif: str
    etape: str = ETAPE_PLACEMENT
    trace: object | None = None


@dataclass(frozen=True)
class GpxPropose:
    """Le GPX d'une proposition : son numéro, son nom de fichier, son contenu.

    C'est le **parcours placé**, demi-tours compris — ce qu'on va rouler, pas
    le tour de la boucle (voir `_ecrire_gpx`). Les trois textes existent de
    toute façon en mémoire : la page du jour les embarque pour son
    téléchargement `blob:`. `recueil_gpx` ne fait que les remettre à
    l'appelant au lieu d'en écrire un sur le disque.
    """

    numero: int
    nom_fichier: str
    texte: str


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    client_intervals: ClientIntervals | None = None,
    *,
    lieu_depart: Depart | None = None,
    recueil_gpx: Callable[[list[GpxPropose]], None] | None = None,
    base_routes: BaseRoutes | None = None,
) -> int:
    """Exécute `ourouler sortie`. 0 = succès (y compris « aucune séance ce jour-là »).

    `base_routes` s'injecte comme les clients, pour la même raison et de la
    même façon que dans `boucle/commande.executer` ([[Q58]]) : absente, la
    base est ouverte sur `config.cache.dossier` avec le propriétaire par
    défaut, ce qui est le bon comportement en ligne de commande et le mauvais
    dans un service qui sert plusieurs cyclistes.

    `lieu_depart` est le **point de départ de cette exécution**, déjà tranché
    par l'appelant : `cli.py` quand `--adresse-depart` a été géocodée, une
    requête d'API demain. Absent, c'est celui de la configuration. Le cœur ne
    géocode rien, ne lit aucune adresse et ne sait pas d'où vient ce point
    (règle absolue 2) — il reçoit un `Depart`.

    À ne pas confondre avec `demande.depart`, qui porte une **heure**.

    `recueil_gpx` décide **à qui va le GPX** (Q40 g, tranché le 17/09/2026 :
    « aucun GPX à la génération, et on le fait à la demande quand l'user
    choisit son parcours »). Absent — le cas de la ligne de commande — le GPX
    de la proposition retenue est écrit sur le disque, à `--sortie` ou au nom
    daté par défaut, exactement comme avant. Présent, **aucun fichier n'est
    écrit** : les trois GPX sont remis à l'appelant, qui n'en servira qu'un,
    celui que le cycliste aura choisi. Les trois propositions sont
    contrastées exprès ; n'écrire que celle du classement, c'était envoyer la
    mauvaise trace au compteur à qui choisissait « la plus sèche ».

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
        # la question du vent, la génération des candidates, les en-têtes de
        # texte, la carte et le JSON lisent tous `config.depart`, et un seul de
        # ces points oublié rendrait une réponse fausse — une boucle autour de
        # la maison pour une adresse à 400 km. `Config` est un dataclass gelé :
        # `replace` rend une copie, la configuration de l'appelant n'est pas
        # touchée.
        config = replace(config, depart=lieu_depart)
    demande = lire_options(args, config)

    seance = _seance(demande, config, client_intervals)
    if seance is None:
        # Service planifié (contrat de l'hébergé minimal, périmètre point 4) :
        # un jour sans séance doit produire une page qui le dit, jamais rien
        # ni la page de la veille. Par défaut (`--carte-sans-seance` absent),
        # rien n'est écrit — comportement inchangé pour l'usage interactif,
        # où un fichier à chaque essai sans séance serait du bruit.
        chemin_carte = None
        if getattr(args, "carte_sans_seance", False):
            chemin_carte = _ecrire_page_sans_seance(demande, config)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "jour": demande.jour.isoformat(),
                        "seance": None,
                        "candidates": [],
                        "carte": str(chemin_carte) if chemin_carte else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            message = (
                f"Aucune séance vélo planifiée le {demande.jour.isoformat()} sur Intervals.icu — "
                "rien à placer. `ourouler boucle` propose une sortie libre."
            )
            if chemin_carte is not None:
                message += f"\nPage écrite : {chemin_carte}"
            print(message)
        return 0

    parametres, provenance = _parametres(config, demande.velo)
    distance_km, distance_source = _distance(demande, seance, parametres, config)

    # Q40 (a) : une date lointaine ne se refuse pas, elle se sert **sans
    # météo**. On le constate ici, avant le premier appel : demander une
    # prévision pour dans dix ans coûterait ~150 appels Open-Meteo pour
    # récolter trois blocs vides, puis un message sur ce qu'Open-Meteo ne
    # couvre pas — là où le cycliste veut lire « pas de météo ce jour-là » et
    # recevoir sa boucle.
    dernier_jour = portee.dernier_jour_couvert(
        config.meteo.horizon_jours, aujourdhui=date.today()
    )
    meteo_absente = (
        portee.constater(demande.jour, dernier_jour) if demande.jour > dernier_jour else None
    )

    # La question du vent se pose **avant** la recherche (contrat §3.3.4) :
    # c'est un appel Open-Meteo sur un point et une heure, donc le poste le
    # moins cher de la commande, et il tombe avant les appels BRouter, qui
    # sont le seul poste qui compte.
    if meteo_absente is not None:
        # Aucun client météo au-delà de l'horizon : `None` traverse le reste
        # de la commande et vaut « on ne demande rien », partout de la même
        # façon, plutôt qu'un drapeau à ne pas oublier dans trois fonctions.
        client_meteo = None
        question = vent_demande.QuestionVent(
            vent_kmh=None,
            vent_depuis_deg=None,
            posee=False,
            motif=meteo_absente.message,
        )
    else:
        client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
        question = vent_demande.interroger(
            client_meteo,
            config.depart,
            depart_heure=demande.depart,
            jour=demande.jour,
            modele=config.meteo.modele,
            modele_repli=config.meteo.second_avis,
        )
    azimuts_vent = question.azimuts_pour(demande.vent)

    client_brouter = (
        client_brouter
        if client_brouter is not None
        else ClientBrouter(config.brouter, evitements=config.evitements)
    )
    candidates, hors_bande = _candidates(client_brouter, config, demande, distance_km, azimuts_vent)

    retenues, ecartees = _placer_toutes(candidates, seance, config, parametres)
    # Les directions refusées sur la distance (Q41 d) rejoignent celles que le
    # placement a refusées : deux motifs différents, un seul endroit où le
    # cycliste les lit. Sans ça, demander cinq directions et en voir trois se
    # passait en silence — c'est le défaut même que ce lot corrige, il n'a pas
    # à revenir par la porte de derrière.
    ecartees = hors_bande + ecartees
    if not retenues:
        raise ErreurUtilisateur(_motif_aucune(seance, ecartees, distance_km))

    retenues = _replacer_avec_vent(retenues, seance, config, parametres, demande, client_meteo)
    propositions, panne = _mesurer(retenues, config, demande, client_meteo, base_routes)
    propositions.sort(key=functools.cmp_to_key(_comparer(config.seance.tolerance_egalite)))
    for numero, proposition in enumerate(propositions, start=1):
        proposition.numero = numero

    # Les trois propositions contrastées (lot L5.3). La première reste celle
    # que le tri ci-dessus a retenue : on ne change pas ce que l'outil
    # recommande, on ajoute ce à quoi le comparer.
    selection = contraste.choisir(propositions, duree_seance_s=seance.duree_s)

    meilleure = propositions[0]
    tenue = (
        conseiller_tenue(meilleure.meteo, config.tenue) if meilleure.meteo is not None else None
    )
    gpx_propositions = _gpx_propositions(seance, demande, selection)
    chemin_gpx = None
    if recueil_gpx is None:
        chemin_gpx = _ecrire_gpx(meilleure.trace, meilleure.placement, seance, demande, config)
    else:
        recueil_gpx(gpx_propositions)
    chemin_carte = _ecrire_page_jour(seance, demande, config, selection, gpx_propositions)

    # Une météo tombée dans l'horizon est le même état à l'écran qu'une date
    # trop lointaine (E14 · dégradé) : la boucle reste servie, la pluie, le
    # vent et la tenue disparaissent. La phrase, elle, ne dit pas pourquoi.
    if meteo_absente is None and panne is not None:
        meteo_absente = portee.constater(demande.jour, dernier_jour)
    if panne is not None:
        print(
            f"ourouler : météo indisponible ({panne}) — tableau sans les colonnes météo et "
            "sans tenue conseillée ; le placement, lui, reste valable",
            file=sys.stderr,
        )
    elif meteo_absente is not None:
        print(
            f"ourouler : {meteo_absente.message} — tableau sans les colonnes météo et sans "
            "tenue conseillée ; le placement, lui, reste valable",
            file=sys.stderr,
        )
    contexte = _Contexte(
        seance=seance,
        demande=demande,
        config=config,
        distance_km=distance_km,
        distance_source=distance_source,
        provenance_modele=provenance,
        ecartees=ecartees,
        tenue=tenue,
        gpx=chemin_gpx,
        carte=chemin_carte,
        selection=selection,
        question_vent=question,
        meteo_absente=meteo_absente,
    )
    if getattr(args, "json", False):
        print(json.dumps(rendre_json(propositions, contexte), ensure_ascii=False, indent=2))
    else:
        print(rendre_texte(propositions, contexte))
    return 0


@dataclass(frozen=True)
class _Contexte:
    """Tout ce que les deux rendus ont besoin de savoir, en plus des propositions."""

    seance: Seance
    demande: Demande
    config: Config
    distance_km: float
    distance_source: str
    provenance_modele: str
    ecartees: list[Ecartee]
    tenue: Tenue | None
    gpx: Path | None
    carte: Path | None
    #: Les propositions contrastées et leurs phrases (lot L5.3).
    selection: contraste.Selection | None = None
    #: Ce que le vent au départ permettait de demander, et pourquoi.
    question_vent: vent_demande.QuestionVent | None = None
    #: L'état « pas de météo » quand il y en a un (Q40 a) — la phrase à
    #: afficher et le dernier jour couvert. `None` quand la météo a répondu.
    meteo_absente: portee.MeteoAbsente | None = None


# --- options ------------------------------------------------------------------


def lire_options(args: argparse.Namespace, config: Config) -> Demande:
    """Valide tout ce qui peut l'être **avant** le premier appel réseau.

    Une date illisible, une distance négative, une direction inconnue, un vélo
    absent de la configuration ou un dossier de sortie où l'on ne peut pas
    écrire doivent coûter un message immédiat — pas un aller-retour chez
    Intervals, puis chez BRouter, puis chez Open-Meteo.
    """
    jour = _jour(getattr(args, "jour", None))

    distance_km = getattr(args, "distance", None)
    if distance_km is not None and (not math.isfinite(distance_km) or distance_km <= 0):
        raise ErreurUtilisateur(
            f"--distance {distance_km} : une distance en kilomètres strictement positive est "
            "attendue (omettre l'option pour la déduire de la séance)"
        )

    direction = getattr(args, "direction", None)
    libelle, azimut = ("", None)
    if direction is not None:
        libelle, azimut = direction_en_azimut(direction)

    nb = getattr(args, "candidates", None)
    nb = config.boucle.candidates if nb is None else int(nb)
    if nb < 1:
        raise ErreurUtilisateur(f"--candidates {nb} : au moins une candidate est attendue")

    velo = getattr(args, "velo", None)
    if velo:
        config.velo(velo)  # lève ErreurConfig si le vélo n'existe pas

    if not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "sortie : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter"
        )

    vent = orientation.valider(getattr(args, "vent", None))
    # Q44 : les deux réglages fixaient le même azimut, et rien ne disait lequel
    # gagnait. `--direction` l'emportait en silence, ce qui laissait le
    # cycliste croire que son orientation au vent avait été honorée. On ne
    # choisit plus un gagnant : on refuse la contradiction, et le message dit
    # les deux formulations possibles. « Peu importe » n'est pas une
    # contradiction — c'est l'absence de demande.
    if azimut is not None and vent != orientation.PEU_IMPORTE:
        raise ErreurUtilisateur(
            f"--direction {libelle} et --vent {vent} demandent tous deux une direction de "
            "recherche, et rien ne dit laquelle devrait l'emporter : choisir sa direction "
            "**ou** la laisser déduire du vent, pas les deux"
        )

    sortie = getattr(args, "sortie", None)
    carte = getattr(args, "carte", None)
    fichier_seance = getattr(args, "fichier_seance", None)
    demande = Demande(
        jour=jour,
        distance_km=float(distance_km) if distance_km is not None else None,
        direction=libelle,
        azimut_deg=azimut,
        nb_candidates=nb,
        profil=getattr(args, "profil", None) or config.brouter.profil,
        depart=_heure_depart(getattr(args, "depart", None), jour),
        velo=velo,
        sortie=Path(sortie) if sortie else None,
        carte=Path(carte) if carte else None,
        ecraser=bool(getattr(args, "ecraser", False)),
        vent=vent,
        fichier=Path(fichier_seance) if fichier_seance else None,
    )
    for chemin, demande_explicite in (
        (chemin_gpx_par_defaut(demande, config), demande.sortie is not None),
        (chemin_carte_par_defaut(demande, config), demande.carte is not None),
    ):
        _verifier_ecriture(chemin, explicite=demande_explicite, ecraser=demande.ecraser)
    return demande


def _jour(brut: str | None) -> date:
    if not brut:
        return date.today()
    try:
        return date.fromisoformat(str(brut).strip())
    except ValueError as e:
        raise ErreurUtilisateur(f"--jour {brut!r} : date AAAA-MM-JJ attendue") from e


def _heure_depart(brut: str | None, jour: date) -> datetime:
    """L'heure de départ, **ramenée au jour de la séance**.

    `heure_depart` interprète « 09:00 » comme « aujourd'hui à 9 h » : demander
    la séance du 8 février daterait alors la météo d'aujourd'hui, ce qui n'a
    aucun sens. On garde donc l'heure (et le fuseau) que `heure_depart`
    calcule, et on remplace la date par celle de la séance — sauf si
    l'utilisateur a écrit la date lui-même.
    """
    quand = heure_depart(brut)
    if brut and "T" in str(brut):
        return quand
    return quand.replace(year=jour.year, month=jour.month, day=jour.day)


def _dossier_sorties_par_defaut(config: Config) -> Path:
    """Le dossier des fichiers produits par défaut, hors du dépôt (Q23).

    Avant ce correctif, sans `--sortie` ni `--carte`, `sortie_AAAAMMJJ.gpx`
    et `.html` s'écrivaient dans le répertoire courant — le dépôt, quand la
    commande est lancée de là, ce que fait le mainteneur. `.gitignore` les
    couvre, mais ces fichiers portent ses coordonnées de départ : « un
    fichier que seul `.gitignore` protège n'est pas protégé, il est
    seulement discret. »

    Un sous-dossier du cache déjà configuré (`config.cache.dossier`,
    `~/.cache/ourouler` par défaut) — l'une des deux destinations que le
    contrat proposait, et celle qui n'ajoute pas un nouveau réglage. Créé au
    besoin : le premier `ourouler sortie` d'une machine neuve ne doit pas
    échouer faute de dossier.
    """
    dossier = config.cache.dossier / "sorties"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ErreurUtilisateur(f"{dossier} : impossible de créer le dossier ({e})") from e
    return dossier


def chemin_gpx_par_defaut(demande: Demande, config: Config) -> Path:
    """`sortie_<AAAAMMJJ>.gpx` dans le dossier de sortie par défaut, ou le `--sortie` demandé."""
    return demande.sortie or (_dossier_sorties_par_defaut(config) / f"sortie_{demande.jour:%Y%m%d}.gpx")


def chemin_carte_par_defaut(demande: Demande, config: Config) -> Path:
    """`sortie_<AAAAMMJJ>.html` dans le dossier de sortie par défaut, ou le `--carte` demandé."""
    return demande.carte or (
        _dossier_sorties_par_defaut(config) / f"sortie_{demande.jour:%Y%m%d}.html"
    )


def _verifier_ecriture(chemin: Path, *, explicite: bool, ecraser: bool) -> None:
    """Refuse d'avance un fichier qu'on ne pourra pas écrire (même règle que `boucle`).

    Un nom **choisi** qui existe déjà n'est pas écrasé sans `--ecraser` : la
    deuxième exécution est le cas normal et remplacer sans un mot le fichier
    qu'on vient de relire serait une perte. Le nom par défaut, lui, porte le
    jour de la séance et est réécrit sans question.
    """
    dossier = chemin.parent if str(chemin.parent) else Path(".")
    if not dossier.is_dir():
        raise ErreurUtilisateur(f"{chemin} : le dossier {dossier} n'existe pas")
    temoin = dossier / f".ourouler-{uuid.uuid4().hex}.tmp"
    try:
        temoin.touch()
    except OSError as e:
        raise ErreurUtilisateur(f"{chemin} : écriture impossible dans {dossier} ({e})") from e
    finally:
        try:
            temoin.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - le témoin vient d'être créé
            pass
    if explicite and chemin.exists() and not ecraser:
        raise ErreurUtilisateur(
            f"{chemin} existe déjà — ajouter --ecraser pour le remplacer, ou choisir un autre nom"
        )


# --- les étapes de l'enchaînement ---------------------------------------------


def _seance(demande: Demande, config: Config, client: ClientIntervals | None) -> Seance | None:
    """La séance à placer : Intervals.icu, ou `demande.fichier` s'il est donné (F1, C1)."""
    if demande.fichier is not None:
        from ourouler.seance.fichier import lire_fichier_seance  # import paresseux : lit un fichier

        return lire_fichier_seance(
            demande.fichier,
            ftp_w=config.cycliste.ftp_w,
            seuil_recuperation_pct=config.seance.seuil_recuperation_pct,
            jour=demande.jour,
        )
    if client is None:
        if not config.intervals.renseigne:
            raise ErreurIntervalsAbsent(
                "sortie : Intervals.icu n'est pas renseigné — compléter [intervals] "
                "athlete_id et api_key dans la configuration"
            )
        client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    return seance_du_jour(
        client,
        demande.jour,
        ftp_w=config.cycliste.ftp_w,
        zones_puissance=config.seance.zones_pct,
        puissance_endurance_pct=config.seance.puissance_endurance_pct,
        seuil_recuperation_pct=config.seance.seuil_recuperation_pct,
    )


def _parametres(config: Config, velo: str | None) -> tuple[Parametres, str]:
    """Les paramètres physiques du vélo et leur provenance.

    Contrairement à `ourouler seance`, qui préfère une vitesse moyenne assumée
    à un CdA inventé, `sortie` **a besoin** d'un modèle : sans lui, on ne sait
    pas à quelle vitesse chaque étape avance le long du tracé, donc on ne sait
    pas où tombent les blocs. On prend donc ce qu'on a — calibration,
    configuration ou valeurs par défaut — et la provenance est affichée en
    toutes lettres.
    """
    from ourouler.physique.commande import (
        alerte_calibration,
        chemin_calibration,
        parametres_du_velo,
        velo_demande,
    )

    choisi = velo_demande(config, velo)
    parametres, provenance = parametres_du_velo(config, choisi, chemin_calibration(config))
    alerte = alerte_calibration(choisi, chemin_calibration(config))
    # L'alerte suit la provenance, qui s'affiche en texte comme en JSON : une
    # calibration qui ne suit plus le pneu du vélo reste utilisée, mais dite.
    suite = f" — {alerte}" if alerte else ""
    return parametres, f"{provenance} ({choisi.nom}){suite}"


def _distance(
    demande: Demande, seance: Seance, parametres: Parametres, config: Config
) -> tuple[float, str]:
    """(distance en km, d'où elle vient). `--distance` gagne toujours."""
    if demande.distance_km is not None:
        return demande.distance_km, "demandée"
    mesures = longueurs(seance, parametres=parametres)
    # Une étape « libre » — sans puissance prescrite — n'a pas de longueur
    # chiffrée. La première rédaction la comptait pour **zéro kilomètre**, ce
    # qui sous-dimensionnait la boucle à proportion. Mesuré le 16/09/2026 sur
    # la séance de référence « 4x8 SV1 outdoor » du 22/04 : 22 étapes, dont
    # trois libres (échauffement 20 min, récupération 12 min, retour au calme
    # 40 min). 63 min chiffrées sur 135 — **plus de la moitié de la séance
    # était invisible**, et le moteur demandait 35 km pour une sortie de 67.
    # Il rattrapait ensuite en roulant la boucle presque deux fois, avec des
    # demi-tours dont personne n'avait besoin.
    #
    # Une étape libre se roule à l'allure d'endurance : c'est l'hypothèse la
    # plus plate qui soit, et infiniment meilleure que zéro.
    connues = [m.longueur_m for m in mesures if m.longueur_m is not None]
    libres_s = sum(
        m.etape.duree_s for m in mesures if m.longueur_m is None and m.etape.duree_s > 0
    )
    metres = sum(connues)
    libres_sans_ftp = False
    if libres_s > 0:
        if config.cycliste.ftp_w is None:
            # Sans FTP, les étapes en pourcentage n'ont déjà plus de
            # puissance-cible chiffrée en amont (seance/zwo.py,
            # seance/intervals.py, seance/fichier.py) : elles tombent ici
            # dans les étapes « libres ». On ne peut alors pas non plus
            # demander au modèle physique une vitesse pour ces minutes —
            # repli sur la vitesse moyenne assumée de la configuration,
            # comme le fait déjà le cas « aucune étape chiffrée du tout »
            # ci-dessous.
            metres += config.boucle.vitesse_moyenne_kmh / 3.6 * libres_s
            libres_sans_ftp = True
        else:
            puissance = config.seance.puissance_endurance_pct * config.cycliste.ftp_w
            metres += vitesse_a_plat_ms(puissance, parametres) * libres_s
    source = "estimée par le modèle sur le plat"
    if libres_sans_ftp and connues:
        source = (
            f"estimée par le modèle sur le plat, minutes libres à "
            f"{config.boucle.vitesse_moyenne_kmh:g} km/h faute de FTP renseignée"
        )
    if metres <= 0:
        # Aucune étape ne porte de puissance : on retombe sur la vitesse
        # moyenne de la configuration plutôt que de demander une boucle nulle.
        metres = config.boucle.vitesse_moyenne_kmh / 3.6 * seance.duree_s
        source = f"faute de puissances, à {config.boucle.vitesse_moyenne_kmh:g} km/h"
    arrondie = math.ceil(metres / 1000.0 / ARRONDI_DISTANCE_KM) * ARRONDI_DISTANCE_KM
    return float(arrondie), f"{source}, {metres / 1000:.1f} km arrondis au multiple de 5 supérieur"


def executer_vent(
    args: argparse.Namespace,
    config: Config,
    client_meteo: ClientOpenMeteo | None = None,
    *,
    lieu_depart: Depart | None = None,
) -> int:
    """Le vent au départ, **avant** de chercher quoi que ce soit (Q44).

    Un seul appel Open-Meteo, un point, une heure : le poste le moins cher du
    produit. Il existe parce que l'écran de demande doit montrer d'où vient le
    vent *pendant* que le cycliste choisit sa direction — « Vent de sud-ouest à
    22 km/h demain matin », ce que la maquette E16 prévoyait et que l'écran ne
    faisait pas.

    Le mainteneur posait un « soit / soit » : montrer le vent **ou** proposer
    trois préférences. Les deux modes en ont besoin, et c'est pour ça que
    `azimuts_par_choix` accompagne toujours le vent : celui qui choisit sa
    direction doit savoir d'où il souffle, celui qui choisit selon le vent doit
    pouvoir vérifier ce qu'on lui propose avant de lancer le calcul.

    Aucun tracé, aucun appel BRouter, aucune séance : cette commande ne répond
    qu'à « d'où vient le vent, et qu'est-ce que chaque préférence donnerait ».
    """
    jour = _jour(getattr(args, "jour", None))
    depart_lieu = lieu_depart if lieu_depart is not None else config.depart
    depart_heure = _heure_depart(getattr(args, "depart", None), jour)

    dernier_jour = portee.dernier_jour_couvert(
        config.meteo.horizon_jours, aujourdhui=date.today()
    )
    if jour > dernier_jour:
        # Même règle que `executer` : au-delà de l'horizon on ne demande rien à
        # Open-Meteo, on dit ce qu'on ne sait pas.
        question = vent_demande.QuestionVent(
            vent_kmh=None,
            vent_depuis_deg=None,
            posee=False,
            motif=portee.constater(jour, dernier_jour).message,
        )
    else:
        question = vent_demande.interroger(
            client_meteo if client_meteo is not None else ClientOpenMeteo(),
            depart_lieu,
            depart_heure=depart_heure,
            jour=jour,
            modele=config.meteo.modele,
            modele_repli=config.meteo.second_avis,
        )
    print(json.dumps(_vent_depart_json(question, jour, depart_heure), ensure_ascii=False, indent=2))
    return 0


def _vent_depart_json(
    question: vent_demande.QuestionVent, jour: date, depart_heure: datetime
) -> dict:
    """Le vent au départ et ce que chaque préférence en ferait, en JSON.

    `azimuts_par_choix` porte **des listes**, y compris pour les préférences
    qui n'ouvrent qu'un azimut : un consommateur qui lit une liste ne peut pas
    rater le second azimut du travers, là où un champ scalaire l'aurait
    silencieusement tronqué (Q44).

    Les noms de direction (`"SO"`) sont calculés **ici** et non côté écran : le
    front n'a le droit d'afficher que ce que l'API lui donne.
    """
    return {
        "jour": jour.isoformat(),
        "depart": depart_heure.isoformat(),
        "posee": question.posee,
        "motif": question.motif or None,
        "vent_kmh": question.vent_kmh,
        "vent_depuis_deg": question.vent_depuis_deg,
        "vent_depuis_nom": (
            nom_de_azimut(question.vent_depuis_deg)
            if question.vent_depuis_deg is not None
            else None
        ),
        "seuil_kmh": vent_demande.SEUIL_VENT_SENSIBLE_KMH,
        "horizon_jours": vent_demande.HORIZON_ORIENTATION_J,
        "choix": list(orientation.CHOIX),
        "azimuts_par_choix": {
            choix: [
                {"azimut_deg": a, "nom": nom_de_azimut(a)}
                for a in question.azimuts_pour(choix)
            ]
            for choix in orientation.CHOIX
        },
    }


def _parts(total: int, combien: int) -> list[int]:
    """`total` candidates réparties en `combien` parts aussi égales que possible.

    3 en 2 donne [2, 1], 4 en 2 donne [2, 2], 1 en 2 donne [1, 0] — et une part
    nulle n'est pas une anomalie : à une seule candidate demandée, il n'y a
    rien à répartir, et le premier azimut la prend. `_candidates` écarte alors
    cet azimut de sa répartition, parce qu'un `generer(nb=0)` ne rendrait rien
    tout en coûtant un aller-retour.

    Le reste va aux **premières** parts, donc au premier azimut. Sur un nombre
    impair de candidates c'est un déséquilibre d'une unité, et il est assumé :
    l'alternative serait de tirer au sort, ce qui rendrait deux exécutions
    identiques différentes sans rien apprendre au cycliste.
    """
    base, reste = divmod(total, combien)
    return [base + (1 if i < reste else 0) for i in range(combien)]


def _candidates(
    client: ClientBrouter,
    config: Config,
    demande: Demande,
    distance_km: float,
    azimuts_vent: tuple[float, ...] = (),
) -> tuple[list, list[Ecartee]]:
    """Les boucles candidates, et les directions refusées sur la distance.

    Le second élément n'est pas un détail d'implémentation : une direction
    écartée sans qu'on le dise, c'est exactement le défaut que Q41 (d)
    corrige. Il rejoint les `Ecartee` du placement chez l'appelant.

    Sans `--direction`, la commande ne choisit pas à la place du cycliste :
    elle réparti les candidates sur **tout le tour de l'horizon** et laisse le
    tableau montrer ce que chaque direction donne, terrain et pluie compris.
    C'est aussi ce qui rend `ourouler sortie --jour …` utilisable tel quel, ce
    que le contrat de sprint demande.

    `azimuts_vent` sont les azimuts qu'impose une réponse à la question
    d'orientation au vent (lot L5.3). Ils **réduisent l'espace de recherche**
    au lieu de contraster après coup, ce qui est l'intérêt de poser la question
    avant. Ils sont **un ou deux** : « de travers » en ouvre deux opposés
    (Q44).

    `--direction` et `--vent` ne se contredisent plus ici : `_lire` refuse
    qu'on demande les deux (Q44). Quand `--direction` est là, elle est seule.
    """
    if demande.azimut_deg is not None:
        repartition = [(demande.azimut_deg, demande.nb_candidates)]
    elif azimuts_vent:
        parts = _parts(demande.nb_candidates, len(azimuts_vent))
        # Une part nulle (une seule candidate pour deux azimuts) ne donne pas
        # lieu à un appel : `generer(nb=0)` ne rendrait rien en coûtant un
        # aller-retour.
        repartition = [(a, n) for a, n in zip(azimuts_vent, parts, strict=True) if n > 0]
    else:
        # Sans direction demandée, tout le tour de l'horizon, une candidate par
        # azimut.
        pas = 360.0 / demande.nb_candidates
        repartition = [(i * pas, 1) for i in range(demande.nb_candidates)]

    trouvees: list = []
    hors_bande: list[Ecartee] = []
    # **Un appel à `generer` par azimut**, et c'est ce qui garantit la
    # répartition. `generer(azimut, nb)` explore `azimut`, puis ±20°, ±40°… —
    # il élargit un secteur, il n'en ouvre jamais un second. Un seul appel pour
    # deux azimuts opposés entasserait donc toutes les candidates du premier
    # côté ; c'est exactement ce que Q44 demande de vérifier.
    #
    # Le refus sur la distance (Q41 d) est par azimut, et un azimut où le
    # terrain ne sait pas faire la distance ne doit pas emporter ceux où il
    # sait — c'est déjà la règle à l'intérieur de `generer`, elle vaut aussi
    # ici. Le refus n'est relancé que si aucun azimut n'a rien donné, comme le
    # fait déjà `derniere_erreur`.
    refus: ErreurDistanceInatteignable | None = None
    for azimut, nb in repartition:
        try:
            trouvees += generer(
                client,
                config.depart,
                distance_km=distance_km,
                azimut_deg=azimut,
                nb=nb,
                tolerance=config.boucle.tolerance_distance,
                profil=demande.profil,
                appels_max=appels_pour(nb),
            )
        except ErreurDistanceInatteignable as e:
            hors_bande.append(
                Ecartee(
                    azimut_deg=azimut,
                    distance_km=e.distance_obtenue_km,
                    motif=(
                        f"{e.ecart_relatif:+.0%} de la distance demandée — il aurait fallu "
                        f"élargir de {e.elargissement_requis:.0%}, on s'arrête à "
                        f"{e.elargissement_max:.0%}"
                    ),
                    etape=ETAPE_DISTANCE,
                )
            )
            # On garde le refus le moins sévère : c'est celui qui dit le
            # plus justement de combien il aurait fallu élargir.
            if refus is None or e.elargissement_requis < refus.elargissement_requis:
                refus = e
    if not trouvees and refus is not None:
        raise refus
    if not trouvees:
        cible = demande.direction or "toutes directions"
        raise ErreurConnecteur(
            f"sortie : aucune boucle bornée trouvée ({cible}) pour {distance_km:g} km "
            f"(profil {demande.profil}) — essayer une autre direction, une autre distance "
            "ou un autre profil"
        )
    return trouvees, hors_bande


def _placer_toutes(
    candidates: list, seance: Seance, config: Config, parametres: Parametres
) -> tuple[list[tuple[object, Placement]], list[Ecartee]]:
    """Le placement sur chaque candidate : les retenues d'un côté, les motifs de l'autre."""
    retenues: list[tuple[object, Placement]] = []
    ecartees: list[Ecartee] = []
    elasticite = (config.seance.elasticite_z2_min, config.seance.elasticite_z2_max)
    elasticite_calme = (config.seance.elasticite_calme_min, config.seance.elasticite_calme_max)
    for candidate in candidates:
        trace = candidate.trace
        placement = placer(
            seance,
            trace,
            parametres,
            elasticite=elasticite,
            elasticite_calme=elasticite_calme,
            penalite_demi_tour=config.seance.demi_tour_penalite,
        )
        if placement is None:
            ecartees.append(
                Ecartee(
                    azimut_deg=getattr(candidate, "azimut_deg", None),
                    distance_km=trace.distance_m / 1000.0,
                    motif=str(trace.meta.get(CLE_MOTIF) or "motif non précisé"),
                    etape=ETAPE_PLACEMENT,
                    trace=trace,
                )
            )
            continue
        retenues.append((candidate, placement))
    return retenues, ecartees


def _replacer_avec_vent(
    retenues: list[tuple[object, Placement]],
    seance: Seance,
    config: Config,
    parametres: Parametres,
    demande: Demande,
    client_meteo: ClientOpenMeteo | None,
) -> list[tuple[object, Placement]]:
    """Rejoue le placement de chaque candidate retenue avec son champ de vent.

    La deuxième passe du contrat §1.6 : le premier placement (sans vent) sert
    à dater un premier appel à Open-Meteo, dont on ne garde que le vent —
    c'est lui qui construit le `ChampVent` qui replace la séance. On ne
    boucle pas une seconde fois : le champ de vent bouge lentement (pas
    horaire interpolé) et l'écart d'heure de passage qu'introduit le premier
    placement se compte en minutes, pas en heures. Le coût mesuré est à
    rapporter dans le résumé du lot, pas à supposer.

    Une panne d'Open-Meteo, ou un second placement qui échoue là où le
    premier réussissait (non observé en pratique — le plancher de vitesse du
    modèle physique empêche le vent de rendre une séance infaisable — mais
    pas impossible), ne fait pas perdre la candidate : elle retombe sur son
    placement sans vent, avec un avertissement. `_mesurer` retentera sa
    propre météo juste après et dira la panne une fois, sur la sortie
    d'erreur ; ici on se tait, silencieusement correct.
    """
    if client_meteo is None:
        # Pas de météo demandée (Q40 a) : pas de champ de vent, donc pas de
        # seconde passe. Le placement sans vent est ce qu'on sert, et il est
        # valable — c'est le premier placement du contrat §1.6.
        return retenues
    elasticite = (config.seance.elasticite_z2_min, config.seance.elasticite_z2_max)
    elasticite_calme = (config.seance.elasticite_calme_min, config.seance.elasticite_calme_max)
    resultat: list[tuple[object, Placement]] = []
    for candidate, placement_sans_vent in retenues:
        trace = candidate.trace
        vitesse = _vitesse(placement_sans_vent, config)
        try:
            meteo_vent = evaluer_meteo(
                trace,
                client_meteo,
                horaire=construire_horaire(demande.depart, vitesse),
                modele=config.meteo.modele,
                # Pas de `second_avis` : lui seul sert au second modèle de
                # pluie, et ce premier appel ne sert qu'au vent du modèle
                # principal — l'économiser garde le coût à un appel de plus
                # par candidate, pas deux.
                #
                # `modele_repli` (Q19), lui, ne coûte rien tant que le
                # principal répond : il ne se déclenche que si celui-ci ne
                # couvre pas la fenêtre, exactement le cas qui privait cette
                # deuxième passe de vent — et donc de son replacement.
                modele_repli=config.meteo.second_avis,
            )
        except ErreurConnecteur:
            resultat.append((candidate, placement_sans_vent))
            continue
        champ = ChampVent(meteo_vent.echantillons)
        replacement = placer(
            seance,
            trace,
            parametres,
            vent=champ,
            elasticite=elasticite,
            elasticite_calme=elasticite_calme,
            penalite_demi_tour=config.seance.demi_tour_penalite,
        )
        if replacement is None:
            placement_sans_vent.avertissements = list(
                dict.fromkeys(
                    [
                        *placement_sans_vent.avertissements,
                        "vent non pris en compte : le replacement avec vent a échoué "
                        "(placement sans vent conservé)",
                    ]
                )
            )
            resultat.append((candidate, placement_sans_vent))
            continue
        resultat.append((candidate, replacement))
    return resultat


def _comparer(tolerance: float):
    """Le comparateur de tri du contrat §4 : note de placement d'abord, pluie
    cumulée ensuite — mais seulement quand les deux notes sont égales à
    `tolerance` (écart relatif) près.

    Depuis que le vent entre dans la note (sprint 5), deux notes ne sont
    presque plus jamais égales au bit près, même pour deux boucles dont le
    terrain sous les blocs est identique : sans cette tolérance, le vent
    déciderait toujours et la pluie ne départagerait plus jamais, ce que le
    contrat du sprint 4 avait pourtant pesé. `tolerance` est une préférence
    du cycliste (`config.seance.tolerance_egalite`), pas une constante du
    code : à 0, le vent tranche toujours, sans exception.
    """

    def comparer(a: Proposition, b: Proposition) -> int:
        na, nb = a.placement.note_totale, b.placement.note_totale
        if not _notes_egales(na, nb, tolerance):
            return -1 if na < nb else 1
        pa, pb = a.pluie_mm, b.pluie_mm
        if pa != pb:
            return -1 if pa < pb else 1
        return 0

    return comparer


def _notes_egales(a: float, b: float, tolerance: float) -> bool:
    """Deux notes de placement sont égales si leur écart relatif est sous `tolerance`."""
    if a == b:
        return True
    echelle = max(abs(a), abs(b))
    return echelle > 0 and abs(a - b) / echelle <= tolerance


def _motif_aucune(seance: Seance, ecartees: list[Ecartee], distance_km: float) -> str:
    """Le message quand **aucune** candidate ne porte la séance.

    Code de sortie 2, et non 0 : ce n'est pas le cas « rien de prévu
    aujourd'hui » (qui est une réponse), c'est « je n'ai rien à proposer » —
    le même cas que `boucle` quand le moteur ne rend aucune boucle bornée, qui
    sort déjà en 2. Un script qui enchaîne sur le GPX doit s'arrêter là.
    """
    detail = "; ".join(
        f"{_azimut(e.azimut_deg)} {e.distance_km:.1f} km : {e.motif}" for e in ecartees[:3]
    )
    suite = f" (et {len(ecartees) - 3} autre(s))" if len(ecartees) > 3 else ""
    return (
        f"sortie : la séance « {seance.nom} » ne tient sur aucune des {len(ecartees)} boucle(s) "
        f"proposées autour de {distance_km:g} km — {detail}{suite}. "
        "Essayer --distance plus grande, une autre direction, ou plus de candidates."
    )


def _mesurer(
    retenues: list[tuple[object, Placement]],
    config: Config,
    demande: Demande,
    client_meteo: ClientOpenMeteo | None,
    base_routes: BaseRoutes | None = None,
) -> tuple[list[Proposition], str | None]:
    """Coûts, routes connues et météo des candidates retenues.

    La vitesse qui date les heures de passage est celle **de la séance sur ce
    tracé** — distance placée divisée par durée placée — et non plus la
    vitesse moyenne de la configuration : c'est ce que la question Q8
    promettait au sprint 4.

    `client_meteo` à `None` veut dire « on ne demande pas de météo » (Q40 a,
    jour au-delà de l'horizon) : les coûts et le placement sont mesurés comme
    d'habitude, la météo reste absente, et ce n'est **pas** une panne — il n'y
    a rien à signaler qui ne soit déjà dit par `meteo_absente`.
    """
    poids = lire_poids(config.cache.dossier / NOM_POIDS)
    base = base_routes if base_routes is not None else _base_routes(config)
    propositions: list[Proposition] = []
    panne: str | None = None
    for candidate, placement in retenues:
        trace = candidate.trace
        vitesse = _vitesse(placement, config)
        meteo: MeteoTrace | None = None
        if panne is None and client_meteo is not None:
            try:
                meteo = evaluer_meteo(
                    trace,
                    client_meteo,
                    horaire=construire_horaire(demande.depart, vitesse),
                    modele=config.meteo.modele,
                    second_avis=config.meteo.second_avis,
                    # Repli Q19 : sans lui, une fenêtre hors de portée
                    # d'AROME (sortie à J+3, par exemple) perdait toute la
                    # météo et toute la tenue, pas seulement une colonne.
                    modele_repli=config.meteo.second_avis,
                )
            except ErreurConnecteur as e:
                panne = str(e)
        propositions.append(
            Proposition(
                numero=0,
                trace=trace,
                placement=placement,
                couts=evaluer_couts(trace, sens_prefere=config.boucle.sens, poids=poids),
                meteo=meteo,
                azimut_deg=getattr(candidate, "azimut_deg", None),
                ecart_relatif=getattr(candidate, "ecart_relatif", None),
                elargissement=getattr(candidate, "elargissement", None),
                tolerance_distance=getattr(candidate, "tolerance", None),
                part_connue=base.part_connue(trace) if base is not None else None,
                vitesse_kmh=vitesse,
            )
        )
    return propositions, panne


def _vitesse(placement: Placement, config: Config) -> float:
    """La vitesse moyenne de la séance sur ce tracé, en km/h."""
    if placement.duree_totale_s > 0 and placement.distance_totale_m > 0:
        vitesse = placement.distance_totale_m / 1000.0 / (placement.duree_totale_s / 3600.0)
        if math.isfinite(vitesse) and vitesse > 0:
            return vitesse
    return config.boucle.vitesse_moyenne_kmh


def _base_routes(config: Config) -> BaseRoutes | None:
    """La base des routes connues si elle existe déjà, sinon `None`.

    Même règle que `boucle.commande` : on ne la **crée** pas au passage, et une
    base illisible ne fait pas perdre la sortie — la colonne « connu % »
    disparaît, elle n'a jamais pesé sur le tri.
    """
    chemin = config.cache.dossier / NOM_BASE
    if not chemin.is_file():
        return None
    try:
        return BaseRoutes(chemin)
    except ErreurUtilisateur:
        return None


# --- écriture des fichiers -----------------------------------------------------


def _ecrire_gpx(
    trace: Trace, placement: Placement, seance: Seance, demande: Demande, config: Config
) -> Path:
    """Le GPX du **parcours placé**, demi-tours compris — pas celui de la boucle.

    Défaut mesuré le 22/04 : avec quatre demi-tours, le placement comptait
    72,7 km sur une boucle de 38,5, et le fichier envoyé au compteur n'en
    portait aucun. Ce qu'on écrit doit être ce qu'on va rouler, sans quoi le
    GPX ne correspond pas à la séance. La carte, elle, montre toujours la
    boucle : c'est son rôle de situer les blocs sur le tracé d'origine.
    """
    chemin = chemin_gpx_par_defaut(demande, config)
    nom = f"{seance.nom} — {seance.jour.isoformat()}"
    parcours = trace_parcourue(placement, trace)
    try:
        chemin.write_text(
            ecrire_gpx(parcours, nom, desc=_description_parcours(parcours, placement)),
            encoding="utf-8",
        )
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def _gpx_propositions(
    seance: Seance, demande: Demande, selection: contraste.Selection
) -> list[GpxPropose]:
    """Le GPX de **chaque** proposition retenue, en mémoire, rien sur le disque.

    Ces textes étaient déjà fabriqués, une fois, pour la page du jour, qui les
    embarque en base64 pour son téléchargement `blob:`. Les nommer ici les
    rend servables à qui appelle la commande (`recueil_gpx`) sans les calculer
    deux fois — et c'est ce qui permet à l'API de ne rien écrire tant que le
    cycliste n'a pas choisi (Q40 g).
    """
    proposees = []
    for retenue in selection.retenues:
        p = retenue.proposition
        parcours = trace_parcourue(p.placement, p.trace)
        proposees.append(
            GpxPropose(
                numero=p.numero,
                nom_fichier=f"sortie_{demande.jour:%Y%m%d}_n{p.numero}.gpx",
                texte=ecrire_gpx(
                    parcours,
                    f"{seance.nom} — {seance.jour.isoformat()}",
                    desc=_description_parcours(parcours, p.placement),
                ),
            )
        )
    return proposees


def _description_parcours(parcours: Trace, placement: Placement) -> str:
    """« 47,8 km · D+ 210 m (parcours placé) · 4 demi-tours » — ce que contient le fichier."""
    # `.blocs()` : la récupération d'un demi-tour porte aussi `demi_tour=True`
    # (contrat §2.2 a)), la compter en plus du bloc doublerait ce chiffre.
    demi_tours = sum(1 for e in placement.blocs() if e.demi_tour)
    if demi_tours == 0:
        combien = "sans demi-tour"
    elif demi_tours == 1:
        combien = "1 demi-tour"
    else:
        combien = f"{demi_tours} demi-tours"
    return f"{description_gpx(parcours)} · {combien}"


def _ecrire_page_sans_seance(demande: Demande, config: Config) -> Path:
    """La page du jour quand rien n'est planifié (contrat de l'hébergé minimal, périmètre point 4).

    Réutilise l'emplacement standard de la carte (`--carte`, ou le nom daté
    par défaut `chemin_carte_par_defaut`) : le serveur statique qui sert le
    dossier n'a besoin de rien savoir de plus qu'un jour ouvré. Le contenu
    dit qu'il n'y a rien à rouler et quand la page a été produite (point 5) —
    une page qui le dit vaut mieux qu'aucune page, jamais une erreur ni la
    page de la veille servie en silence.
    """
    chemin = chemin_carte_par_defaut(demande, config)
    try:
        chemin.write_text(
            construire_page_sans_seance(demande.jour, maintenant=datetime.now()),
            encoding="utf-8",
        )
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def _ecrire_page_jour(
    seance: Seance,
    demande: Demande,
    config: Config,
    selection: contraste.Selection,
    gpx_propositions: list[GpxPropose],
) -> Path:
    """La page du jour (lot L5.4) : les propositions contrastées, superposées.

    Une `carte.PropositionCarte` par proposition retenue par
    `contraste.choisir` — jamais recalculée ici, seulement mise en forme
    pour l'affichage. Chacune porte sa **propre** tenue : la météo diffère
    d'une direction à l'autre, et un cycliste qui choisit la deuxième
    proposition doit lire son conseil à elle, pas celui de la première. Le
    GPX embarqué dans la page est celui du **parcours placé**, demi-tours
    compris — même règle que `_ecrire_gpx` pour le fichier écrit sur disque,
    mais celui-ci n'est jamais écrit : il part en base64 dans la page, pour
    un téléchargement `blob:` côté navigateur (§4.2 du contrat — « le
    fichier suit le choix du cycliste, pas le classement »).
    """
    chemin = chemin_carte_par_defaut(demande, config)
    par_numero = {g.numero: g for g in gpx_propositions}
    cartes_props = []
    for retenue in selection.retenues:
        p = retenue.proposition
        tenue_p = conseiller_tenue(p.meteo, config.tenue) if p.meteo is not None else None
        gpx = par_numero[p.numero]
        cartes_props.append(
            PropositionCarte(
                numero=p.numero,
                trace=p.trace,
                placement=p.placement,
                meteo=p.meteo,
                # Vide plutôt que faux : `construire_page_jour` sait qu'une
                # proposition sans phrase parle par son tracé, et n'écrit
                # « la seule candidate » que quand elle l'est vraiment.
                distinction=retenue.distinction,
                chiffres=_details_proposition(retenue),
                sous_titre=_sous_titre(p, demande, config),
                notes=_notes_carte(p, seance, tenue_p),
                gpx_nom=gpx.nom_fichier,
                gpx_texte=gpx.texte,
            )
        )
    page = construire_page_jour(
        seance,
        cartes_props,
        titre=f"{seance.nom} — {date_en_francais(demande.depart)}",
        motif_deux_propositions=selection.motif_deux_propositions,
        motif_equivalence=selection.motif_equivalence,
    )
    try:
        chemin.write_text(page, encoding="utf-8")
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def _sous_titre(proposition: Proposition, demande: Demande, config: Config) -> str:
    trace = proposition.trace
    morceaux = [
        f"départ {config.depart.nom}",
        f"{_fr(trace.distance_m / 1000, 1)} km",
        f"D+ {trace.denivele_m:.0f} m" if trace.denivele_m is not None else f"D+ {ABSENT}",
        f"note de placement {_fr(proposition.placement.note_totale, 2)}",
        f"{proposition.blocs_bien_places}/{len(proposition.placement.blocs())} blocs bien placés",
    ]
    if demande.direction:
        morceaux.insert(1, f"vers {demande.direction}")
    return " · ".join(morceaux)


def _notes_carte(proposition: Proposition, seance: Seance, tenue: Tenue | None) -> list[str]:
    notes = [
        f"Séance : {_duree_longue(seance.duree_s)}, {len(seance.blocs())} bloc(s) ; "
        f"placement {_duree_longue(proposition.placement.duree_totale_s)} pour "
        f"{_fr(proposition.placement.distance_totale_m / 1000, 1)} km, décalage de la Z2 "
        f"d'ouverture {_minutes(proposition.placement.decalage_z2_s)}.",
    ]
    meteo = proposition.meteo
    if meteo is not None:
        notes.append(
            f"Météo le long du tracé : {_fr(meteo.pluie_cumulee_mm, 1)} mm cumulés, "
            f"vent de face sur {meteo.part_vent_face * 100:.0f} % des échantillons."
        )
    else:
        notes.append("Météo indisponible pour ce jour : ni pluie, ni vent, ni tenue.")
    if tenue is not None:
        notes.append("Tenue : " + _tenue_courte(tenue))
    notes.extend(proposition.placement.informations)
    for avertissement in proposition.placement.avertissements:
        notes.append("⚠ " + avertissement)
    return notes


# --- rendu texte ---------------------------------------------------------------

#: Écart, en mètres, au-delà duquel le parcours réellement roulé mérite sa
#: propre colonne. Sans demi-tour il vaut la boucle au mètre près ; avec, il
#: peut valoir le double (72,7 km sur une boucle de 38,5 le 22/04). Cent mètres
#: parce qu'en dessous l'écart n'est que l'arrondi du placement.
ECART_PARCOURS_M = 100.0

#: Écart, en mètres de dénivelé, au-delà duquel les deux D+ méritent d'être
#: montrés côte à côte. Dix mètres : en dessous, les deux méthodes disent la
#: même chose et une ligne de plus ne ferait que du bruit.
ECART_DENIVELE_M = 10.0

#: Colonnes du tableau. Le second membre nomme la mesure dont la colonne
#: dépend : sans cette mesure, la colonne **disparaît** au lieu d'afficher une
#: colonne de tirets. `None` = toujours affichée.
#:
#: « boucle » et « D+ boucle » décrivent le tracé proposé par le moteur ;
#: « parcours » et « temps » décrivent ce que la séance fait réellement rouler.
#: La ligne mélangeait les deux — 38,5 km en 2 h 44, soit 14 km/h — parce que
#: la distance venait de la boucle et la durée du placement.
COLONNES = (
    ("n°", None),
    ("boucle", None),
    ("D+ boucle", None),
    ("parcours", "parcours"),
    ("temps", None),
    ("trafic", None),
    ("connu %", "connu"),
    ("pluie", "meteo"),
    ("vent face", "meteo"),
    ("note placement", None),
    ("blocs bien placés", None),
    ("demi-tours", "demi_tours"),
)


def rendre_texte(propositions: list[Proposition], contexte: _Contexte) -> str:
    """L'en-tête, le tableau des candidates, la séance placée, la tenue, les fichiers."""
    presentes = _mesures_presentes(propositions)
    lignes = _entete(propositions, contexte, presentes)
    # La troisième valeur de l'écran de FTP (18/09/2026) : `sortie` a toujours
    # un vélo (`_parametres` lève sinon, voir sa docstring), donc `compteur_info`
    # n'est `None` qu'en test avec une configuration construite à la main.
    compteur_info = info_compteur(contexte.config, contexte.demande.velo)

    titres = [t for t, mesure in COLONNES if mesure is None or mesure in presentes]
    cellules = [_cellules(p, presentes, compteur_info) for p in propositions]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for proposition, ligne in zip(propositions, cellules, strict=True):
        marque = f"{MARQUE_RETENUE} " if proposition is propositions[0] else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    if compteur_info is not None:
        lignes.append(ligne_temps_ecoule(compteur_info))
    lignes += _notes_sous_tableau(propositions[0], presentes)
    # L'élargissement de la tolérance de distance se dit ici, sous le tableau,
    # et non dans la colonne « durée » : ce sont deux grandeurs différentes.
    # Voir `SEUIL_ECART_DUREE` plus bas pour la cohabitation des deux.
    lignes += lignes_elargissement(propositions, contexte.distance_km)
    lignes.append("")
    lignes += _propositions_contrastees(contexte)
    lignes += _seance_placee(propositions[0], contexte)
    lignes.append("")
    lignes += _tenue_lignes(contexte)
    if contexte.gpx is not None:
        lignes.append(f"{MARQUE_RETENUE} GPX   : {contexte.gpx}")
    if contexte.carte is not None:
        lignes.append(f"{MARQUE_RETENUE} Carte : {contexte.carte}")
    return "\n".join(lignes)


def _lignes_vent(contexte: _Contexte) -> list[str]:
    """La question d'orientation au vent, ou la raison pour laquelle on ne la pose pas.

    Elle est imprimée dans l'en-tête parce qu'elle a été posée **avant** la
    recherche : ce que le lecteur voit en dessous est déjà la réponse à ce
    qu'il a (ou n'a pas) demandé.
    """
    question, demande = contexte.question_vent, contexte.demande
    if question is None:
        return []
    if not question.posee:
        return [f"Orientation au vent : pas d'avis — {question.motif}."]
    vent = f"Vent au départ {question.vent_kmh:.0f} km/h de {_azimut(question.vent_depuis_deg)}"
    if demande.vent != orientation.PEU_IMPORTE:
        azimuts = question.azimuts_pour(demande.vent)
        ou = f" — recherche dirigée vers {_azimuts(azimuts)}" if azimuts else ""
        return [f"{vent}. Demandé : {_LIBELLES_VENT[demande.vent]}{ou}."]
    return [
        f"{vent}. Question : `--vent retour-dos` pour rentrer avec, `--vent depart-dos` "
        "pour partir avec, `--vent travers` — ou rien, et les propositions ci-dessous "
        "répondent à votre place."
    ]


#: Comment on nomme chaque réponse à la question du vent, à l'affichage.
_LIBELLES_VENT = {
    orientation.PEU_IMPORTE: "peu importe",
    orientation.ORIENTATION_RETOUR_DOS: "rentrer avec le vent dans le dos",
    orientation.ORIENTATION_DEPART_DOS: "partir avec le vent dans le dos",
    orientation.ORIENTATION_TRAVERS: "vent de travers",
}


def _propositions_contrastees(contexte: _Contexte) -> list[str]:
    """Les deux ou trois propositions retenues, chacune avec sa phrase.

    C'est le livrable du lot L5.3 : la phrase, en langage de cycliste et
    jamais en langage de note, est ce qui permet d'arbitrer **en regardant**
    plutôt qu'en réglant.
    """
    selection = contexte.selection
    if selection is None or not selection.retenues:
        return []
    seule = len(selection.retenues) == 1
    lignes = [
        f"{len(selection.retenues)} proposition(s) qui vont à des endroits différents "
        "(et non les trois premières du tri) :"
    ]
    for retenue in selection.retenues:
        numero = retenue.proposition.numero
        # Depuis Q43, une retenue peut n'avoir aucune phrase : son tracé la
        # distingue, pas un axe mesuré. « La seule candidate » ne vaut alors
        # que si elle est vraiment seule — l'écrire sous l'une de trois
        # propositions serait faux.
        phrase = retenue.distinction or ("la seule candidate" if seule else "")
        lignes.append(f"    n° {numero} — {phrase}" if phrase else f"    n° {numero}")
        lignes.append(f"           {_details_proposition(retenue)}")
    if selection.recouvrements:
        parts = ", ".join(
            f"n° {selection.retenues[i].proposition.numero}/"
            f"n° {selection.retenues[j].proposition.numero} {part:.0%}"
            for (i, j), part in sorted(selection.recouvrements.items())
        )
        lignes.append(
            f"    Routes communes : {parts} "
            f"(au-delà de {contraste.SEUIL_RECOUVREMENT:.0%}, deux boucles se ressemblent "
            "sur la carte quoi que disent leurs notes)."
        )
    if selection.motif_deux_propositions:
        lignes.append(f"    {selection.motif_deux_propositions}")
    if selection.motif_equivalence:
        lignes.append(f"    {selection.motif_equivalence}")
    lignes.append("")
    return lignes


#: Écart de durée en deçà duquel on n'affiche rien : 5 % de la séance.
#: Mots du mainteneur (16/09/2026) : « 1 min en plus ou en moins n'est pas un
#: seuil important, faire une alerte quand on est à 5 % de différence de durée,
#: pas moins ». Deux seuils, deux rôles : celui-ci décide si l'écart mérite
#: d'être dit, `elasticite_calme_min` s'il mérite une alerte.
#:
#: **Et un troisième, à ne surtout pas confondre avec lui** : depuis Q41 (d),
#: `boucle.candidates.elargissement_max` borne l'écart de **distance** entre
#: la boucle servie et la boucle demandée. Les deux mesurent des grandeurs
#: différentes sur des objets différents, et ne se recouvrent pas :
#:
#: - `SEUIL_ECART_DUREE` parle de la **durée d'une séance** — la séance
#:   prescrite dure 2 h, le parcours placé en dure 2 h 04, faut-il le dire ?
#:   Il ne refuse jamais rien : il décide si un écart déjà accepté s'affiche.
#: - `elargissement_max` parle de la **distance d'une boucle** — 150 km
#:   demandés, 176 rendus, sert-on cette boucle ? Il refuse, et quand il
#:   accepte, il impose de dire de combien la tolérance a été élargie.
#:
#: Conséquence pratique : une boucle peut être servie en disant « tolérance
#: élargie de 10 % » (fait de distance) et ne rien afficher sur la durée
#: parce que la séance tombe à 2 % près (fait de durée). Ce n'est pas une
#: incohérence, c'est la raison d'avoir deux seuils. Le premier reste une
#: décision du mainteneur au sprint 5 — il avait trouvé l'affichage alarmant
#: à tort — et Q41 (d) ne la défait pas.
SEUIL_ECART_DUREE = 0.05


def _ecart_seance(profil) -> str:
    """« (+18 min) » ou « (⚠ séance amputée de 12 min) », ou rien si elle tombe juste.

    Le signe compte et se dit : rentrer plus tard est normal — c'est le rôle
    du retour au calme —, rouler moins que la séance ne l'est pas. Les deux
    écarts sont du même côté de la valeur absolue dans l'axe de contraste, ils
    ne doivent pas l'être à l'affichage.

    **Le ⚠ suit le verdict du placement (`profil.seance_amputee`), pas un
    seuil recalculé ici (Q21 a).** Avant ce correctif, 60 secondes (1 min)
    suffisaient à afficher « ⚠ séance amputée », y compris pour un écart de
    0,8 % sur une séance de 2 h — alors que le mainteneur a déjà fixé le
    seuil qui compte, `elasticite_calme_min` (config `[seance]`, −5 % par
    défaut), et que `seance.placement` l'applique déjà pour décider si le
    retour au calme est raccourci. Un écart sous ce seuil reste visible en
    minutes, neutre, sans ⚠ — symétrique du dépassement positif.

    **Et sous le seuil, on n'affiche rien du tout (correction du 16/09/2026).**
    La première version gardait « (−5 min) » sans le ⚠ ; le mainteneur a
    répondu « pas réglé ». Il avait raison : sa phrase était « faire une
    alerte quand on est à 5 % de différence de durée, pas moins », et un
    écart qu'on juge négligeable n'a pas à s'afficher. Une ligne qui signale
    ce qui ne compte pas apprend à ne plus lire la ligne.
    """
    depassement = getattr(profil, "depassement_s", None)
    duree = getattr(profil, "duree_s", None)
    if depassement is None or abs(depassement) < 60:
        return ""
    if duree:
        prescrite = duree - depassement
        if prescrite > 0 and abs(depassement) / prescrite < SEUIL_ECART_DUREE:
            return ""
    if depassement > 0:
        return f" (+{depassement / 60:.0f} min)"
    if getattr(profil, "seance_amputee", False):
        return f" (⚠ séance amputée de {-depassement / 60:.0f} min)"
    return f" ({depassement / 60:.0f} min)"


def _details_proposition(retenue) -> str:
    """Les mesures qui portent la phrase, dans les unités du cycliste."""
    profil = retenue.profil
    morceaux = [_duree_courte(profil.duree_s) + _ecart_seance(profil)]
    if profil.feux is not None:
        # Nombres absolus, et séparés : « 1,7 feux/stops/passages au km » se
        # lisait « 170 sur 100 km » (mots du mainteneur) sur un composite dont
        # les deux tiers étaient des passages piétons, qu'on traverse sans
        # lever le pied. On ne montre plus que ce qui pose le pied.
        arrets = [f"{profil.feux} feu{'x' if profil.feux > 1 else ''}"]
        if profil.stops:
            arrets.append(f"{profil.stops} stop{'s' if profil.stops > 1 else ''}")
        morceaux.append(", ".join(arrets))
    else:
        morceaux.append("marqueurs inconnus")
    morceaux.append(
        "aucun demi-tour" if profil.demi_tours == 0 else f"{profil.demi_tours} demi-tour(s)"
    )
    if profil.part_trafic is not None:
        # Q21 c : le % de `primary` seul, plus le composite primary +
        # secondary + trunk qui multipliait par quatre ce qui devait
        # inquiéter (« secondary », une départementale ordinaire ici, en
        # portait les deux tiers).
        morceaux.append(f"{profil.part_trafic * 100:.0f} % de nationales")
    if profil.pluie_mm is not None:
        morceaux.append(f"{_fr(profil.pluie_mm, 1)} mm de pluie")
    if profil.orientation is not None:
        morceaux.append(f"vent : {_LIBELLES_ORIENTATION[profil.orientation]}")
    part = getattr(retenue.proposition, "part_connue", None)
    if part is not None:
        morceaux.append(f"{part * 100:.0f} % de routes connues")
    return ", ".join(morceaux)


#: Comment on nomme une orientation au vent dans la ligne de détail. La part
#: connue y figure aussi, mais **seulement pour décrire** une proposition déjà
#: retenue : le contrat du sprint 3 interdit qu'elle entre dans un score, et
#: le lot L5.3 le redit — pénaliser l'inconnu condamnerait d'avance toute
#: direction jamais explorée.
_LIBELLES_ORIENTATION = {
    orientation.ORIENTATION_RETOUR_DOS: "dans le dos au retour",
    orientation.ORIENTATION_DEPART_DOS: "dans le dos au départ",
    orientation.ORIENTATION_TRAVERS: "de travers",
    orientation.ORIENTATION_FACE: "de face aux deux bouts",
}


def _notes_sous_tableau(proposition: Proposition, presentes: set[str]) -> list[str]:
    """Ce que les colonnes ne peuvent pas dire : les deux parcours, et les deux D+.

    Règle absolue 5 : « deux modèles qui divergent sont affichés comme un
    désaccord, jamais moyennés ». Ici ce n'est pas deux modèles mais deux
    mesures — le « filtered ascend » que BRouter annonce pour la boucle, et le
    D+ que `denivele_filtre` recalcule sur le parcours placé, hystérésis de 2 m
    comprise. Elles diffèrent de −33 % dans le cas relevé le 22/04, alors qu'un
    aller-retour devrait plutôt *augmenter* le D+. La provenance était écrite
    dans chaque artefact (`(moteur)`, `(parcours placé)`), mais il fallait
    ouvrir le GPX pour voir le désaccord : il s'affiche maintenant.
    """
    lignes: list[str] = []
    if "parcours" in presentes:
        lignes.append(
            f"Boucle {_fr(proposition.trace.distance_m / 1000, 1)} km, parcours réellement "
            f"roulé {_fr(proposition.distance_parcours_m / 1000, 1)} km "
            f"({proposition.demi_tours} demi-tour(s)) : le GPX porte le parcours, la carte "
            "montre la boucle. La colonne « temps » va avec le parcours."
        )
    moteur, parcours = proposition.trace.denivele_m, proposition.denivele_parcours_m
    if moteur is not None and parcours is not None and abs(moteur - parcours) > ECART_DENIVELE_M:
        lignes.append(
            f"D+ : {moteur:.0f} m annoncés par le moteur pour la boucle, {parcours:.0f} m "
            "recalculés sur le parcours placé — deux méthodes, pas deux parcours "
            "(le recalcul efface les vallonnements de moins de 2 m)."
        )
    return lignes


def _ligne_modele_meteo(propositions: list[Proposition], config: Config) -> list[str]:
    """Nomme le modèle météo utilisé (Q19), et le dit haut quand c'est un repli.

    « en nommant le modèle utilisé » est le critère d'acceptation du contrat
    de mise en service : sans cette ligne, un repli sur le second avis se
    passait en silence — exactement ce que la règle absolue 5 interdit pour
    deux modèles qui divergent, et ici un seul des deux a pu répondre.
    """
    meteo = next((p.meteo for p in propositions if p.meteo is not None), None)
    if meteo is None or not meteo.modele_utilise:
        return []
    if meteo.repli:
        return [
            f"Météo : {config.meteo.modele} ne couvre pas cette fenêtre — bascule sur "
            f"{meteo.modele_utilise} (second avis, configuré en repli)."
        ]
    return [f"Météo : modèle {meteo.modele_utilise}."]


def _modele_meteo_json(propositions: list[Proposition]) -> dict | None:
    """L'équivalent JSON de `_ligne_modele_meteo` : même donnée, forme structurée."""
    meteo = next((p.meteo for p in propositions if p.meteo is not None), None)
    if meteo is None or not meteo.modele_utilise:
        return None
    return {"utilise": meteo.modele_utilise, "repli": meteo.repli}


def _entete(
    propositions: list[Proposition], contexte: _Contexte, presentes: set[str]
) -> list[str]:
    seance, demande, config = contexte.seance, contexte.demande, contexte.config
    # Trois cas et non deux : depuis le lot L5.3, une réponse à la question
    # d'orientation au vent dirige la recherche elle aussi. Dire « dans toutes
    # les directions » alors qu'on a cherché au sud-ouest serait faux.
    azimuts_vent = (
        contexte.question_vent.azimuts_pour(demande.vent)
        if contexte.question_vent is not None
        else ()
    )
    if demande.azimut_deg is not None:
        direction = f"vers {demande.direction} ({demande.azimut_deg:.0f}°)"
    elif azimuts_vent:
        # Au pluriel quand le travers en a ouvert deux : « vers 315° » sur une
        # recherche qui a exploré 315° et 135° ferait chercher sur la carte une
        # cohérence qui n'existe pas.
        direction = (
            f"vers {_azimuts(azimuts_vent)}, "
            f"{'directions imposées' if len(azimuts_vent) > 1 else 'direction imposée'} par "
            f"--vent {demande.vent}"
        )
    else:
        direction = "dans toutes les directions (aucune --direction demandée)"
    lignes = [
        f"Sortie du {seance.jour.isoformat()} — « {seance.nom} »",
        f"Séance : {_duree_longue(seance.duree_s)}, {len(seance.etapes)} étape(s), "
        f"{len(seance.blocs())} bloc(s)",
        f"Boucle depuis {config.depart.nom} — {contexte.distance_km:g} km {direction}, "
        f"profil {demande.profil}",
        f"Départ {date_en_francais(demande.depart)} — vitesse de la séance sur le tracé "
        f"{_fr(propositions[0].vitesse_kmh, 1)} km/h (heures de passage météo)",
        f"Distance : {contexte.distance_source}",
        f"Modèle physique : {contexte.provenance_modele}",
    ]
    # Le test portait sur « défaut » seul. Depuis que les vélos non calibrés
    # reçoivent les valeurs de `physique.litterature` (18/09/2026), cette
    # provenance-là ne dit plus « défaut » — et l'avertissement disparaissait
    # justement dans le cas où il sert le plus (règle absolue 5). Ce qui
    # compte, c'est « mesuré sur ce vélo ou non ».
    if not contexte.provenance_modele.startswith("calibration"):
        lignes.append(
            "⚠ aucun vélo calibré : les vitesses, donc la position des blocs, reposent sur un "
            f"CdA et un Crr qui viennent de la {contexte.provenance_modele.split(' (')[0]} "
            "et n'ont pas été mesurés sur vous (`ourouler calibrer`)."
        )
    lignes += _ligne_modele_meteo(propositions, config)
    lignes += _lignes_vent(contexte)
    if seance.meta.get("puissance_approximee"):
        lignes.append(
            "⚠ puissances approximées : la séance est prescrite en zones de fréquence cardiaque."
        )
    if seance.meta.get("seances_ignorees"):
        # S1 : `ourouler seance` le disait, `ourouler sortie` non — et c'est
        # justement la commande qui construit une boucle entière pour la séance
        # choisie. Le choix (la plus longue) ne doit pas rester dans `meta`.
        autres = ", ".join(str(n) for n in seance.meta["seances_ignorees"])
        lignes.append(
            f"Autre(s) séance(s) vélo ce jour-là, ignorée(s) au profit de la plus longue : {autres}."
        )
    if contexte.ecartees:
        # Deux motifs cohabitent ici depuis Q41 (d) : la séance qui ne tient
        # pas sur le tracé, et la boucle trop loin de la distance demandée.
        # Chaque ligne porte le sien ; l'en-tête ne préjuge plus duquel il
        # s'agit, sous peine d'annoncer « la séance n'y tenait pas » pour une
        # direction que le placement n'a jamais vue.
        lignes.append(f"{len(contexte.ecartees)} candidate(s) écartée(s) —")
        for ecartee in contexte.ecartees:
            lignes.append(
                f"    {_azimut(ecartee.azimut_deg)} {_fr(ecartee.distance_km, 1)} km : {ecartee.motif}"
            )
    lignes.append(
        "Tri : note de placement (km équivalents) d'abord, pluie cumulée ensuite ; "
        "plus bas = mieux. La note additionne le terrain sous les blocs (vent de face "
        "compris depuis le sprint 5), le coût — faible et sans seuil — de chaque minute "
        "de retour au calme en trop, et la pénalité, elle très lourde, d'une séance "
        "amputée : rentrer plus tard est normal, ne pas rouler la séance ne l'est pas. "
        f"À note égale à {config.seance.tolerance_egalite * 100:.0f} % près, c'est la "
        "pluie cumulée qui décide (`tolerance_egalite`, config [seance])."
    )
    lignes.append(
        f"« blocs bien placés » : note du couloir sous {_fr(NOTE_BLOC_BIEN_PLACE, 1)} km "
        "équivalent, soit moins qu'un feu rouge."
    )
    if "meteo" not in presentes:
        lignes.append("Météo indisponible : colonnes pluie et vent absentes, aucune tenue conseillée.")
    return lignes


def _mesures_presentes(propositions: list[Proposition]) -> set[str]:
    presentes = set()
    if any(p.meteo is not None for p in propositions):
        presentes.add("meteo")
    if any(p.part_connue is not None for p in propositions):
        presentes.add("connu")
    if any(p.demi_tours for p in propositions):
        presentes.add("demi_tours")
    if any(
        abs(p.distance_parcours_m - p.trace.distance_m) > ECART_PARCOURS_M for p in propositions
    ):
        presentes.add("parcours")
    return presentes


def _cellules(
    proposition: Proposition, presentes: set[str], compteur_info: dict | None = None
) -> list[str]:
    trace, couts, meteo = proposition.trace, proposition.couts, proposition.meteo
    partiels = bool(trace.meta.get("couts_partiels"))
    cellules = [
        str(proposition.numero),
        f"{_fr(trace.distance_m / 1000, 1)} km",
        f"{trace.denivele_m:.0f} m" if trace.denivele_m is not None else ABSENT,
    ]
    if "parcours" in presentes:
        cellules.append(f"{_fr(proposition.distance_parcours_m / 1000, 1)} km")
    cellules += [
        _temps_texte(proposition, compteur_info),
        ABSENT if partiels else f"{_fr(couts.km_trafic, 1)} km",
    ]
    if "connu" in presentes:
        cellules.append(
            f"{proposition.part_connue * 100:.0f} %" if proposition.part_connue is not None else ABSENT
        )
    if "meteo" in presentes:
        cellules += [
            f"{_fr(meteo.pluie_cumulee_mm, 1)} mm" if meteo is not None else ABSENT,
            f"{meteo.part_vent_face * 100:.0f} %" if meteo is not None else ABSENT,
        ]
    cellules += [
        _fr(proposition.placement.note_totale, 2),
        f"{proposition.blocs_bien_places}/{len(proposition.placement.blocs())}",
    ]
    if "demi_tours" in presentes:
        cellules.append(str(proposition.demi_tours) if proposition.demi_tours else ABSENT)
    return cellules


#: Libellé humain d'un type d'étape non-bloc, pour l'affichage texte (Q13, lot L5.2).
_LIBELLES_ETAPE = {
    "echauffement": "échauffement",
    "recuperation": "récupération",
    "calme": "retour au calme",
}


def _seance_placee(proposition: Proposition, contexte: _Contexte) -> list[str]:
    """La séance posée sur la candidate retenue, étape par étape, motifs en clair.

    Toutes les étapes de la séance apparaissent, pas seulement les blocs
    (Q13, lot L5.2) : `seance.placement` mémorise désormais la position de
    chacune. Seuls les blocs portent une note — aucun terrain n'est évalué
    sous une récupération, c'est la règle du sprint 4 et elle ne bouge pas —
    donc la colonne reste vide pour le reste plutôt que de porter un tiret
    ambigu (contrat §2.2 b). Le décalage de la Z2 d'ouverture et la durée
    totale disent, eux, ce qui arrive aux extrémités.

    Le kilomètre affiché est `debut_parcouru_m`, le compteur — jamais
    `debut_m`, qui repère une position sur le tracé et peut reculer après un
    demi-tour. Un lecteur qui roule veut lire un compteur qui monte, pas la
    géométrie du tracé ; le demi-tour se dit par ailleurs, en toutes lettres.
    """
    placement = proposition.placement
    seance = contexte.seance
    note = _fr(placement.note_totale, 2)
    if placement.penalite_seance > 0:
        note += (
            # « extrémités » et non « séance non tenue » : depuis Q14 cette
            # pénalité additionne deux choses de natures différentes — une
            # séance amputée, qui est un défaut, et le dépassement du retour au
            # calme, qui n'en est pas un. Le détail se lit deux lignes plus bas.
            f" = terrain {_fr(placement.note_terrain, 2)} + extrémités "
            f"{_fr(placement.penalite_seance, 2)}"
        )
    lignes = [
        f"Séance placée sur la candidate n° {proposition.numero} (note {note}) :",
        f"    Z2 d'ouverture allongée de {_minutes(placement.decalage_z2_s)} — c'est elle qui "
        "fait coulisser les blocs le long du tracé.",
    ]
    numero_bloc = 0
    for emplacement in placement.emplacements:
        etape = seance.etapes[emplacement.etape_idx]
        fin = emplacement.debut_parcouru_m + emplacement.longueur_m
        km = (
            f"km {_fr(emplacement.debut_parcouru_m / 1000, 1)} → {_fr(fin / 1000, 1)} "
            f"({_fr(emplacement.longueur_m / 1000, 1)} km, {_duree_courte(etape.duree_s)}, "
            f"{_puissance(etape)})"
        )
        demi_tour = " — demi-tour" if emplacement.demi_tour else ""
        if emplacement.note is not None:
            numero_bloc += 1
            lignes.append(
                f"    bloc {numero_bloc} — {km} : note {_fr(emplacement.note.note, 2)}{demi_tour}"
            )
            if emplacement.note.note >= NOTE_BLOC_BIEN_PLACE:
                for motif in emplacement.note.motifs or ["aucun motif détaillé"]:
                    lignes.append(f"        • {motif}")
        else:
            libelle = _LIBELLES_ETAPE.get(etape.type, etape.type)
            lignes.append(f"    {libelle} — {km}{demi_tour}")
    lignes.append(
        f"    Retour au calme : {_duree_longue(placement.duree_totale_s)} et "
        f"{_fr(placement.distance_totale_m / 1000, 1)} km au total — il absorbe ce qui reste."
    )
    for information in placement.informations:
        lignes.append(f"    {information}")
    for avertissement in placement.avertissements:
        lignes.append(f"    ⚠ {avertissement}")
    return lignes


def _tenue_lignes(contexte: _Contexte) -> list[str]:
    tenue = contexte.tenue
    if tenue is None:
        return ["Tenue : pas de météo pour ce jour, aucun conseil de tenue.", ""]
    lignes = [
        f"Tenue conseillée — {tenue.categorie_temp}, {tenue.categorie_humidite} :",
        f"    au départ : {_liste(tenue.base)}",
    ]
    if tenue.a_emporter:
        lignes.append(f"    à emporter : {_liste(tenue.a_emporter)}")
    if tenue.a_enlever:
        lignes.append(f"    à prévoir d'enlever : {_liste(tenue.a_enlever)}")
    for motif in tenue.motifs:
        lignes.append(f"    • {motif}")
    lignes.append("")
    return lignes


def _tenue_courte(tenue: Tenue) -> str:
    morceaux = [f"{tenue.categorie_temp}, {tenue.categorie_humidite} — {_liste(tenue.base)}"]
    if tenue.a_emporter:
        morceaux.append("emporter " + _liste(tenue.a_emporter))
    if tenue.a_enlever:
        morceaux.append("prévoir d'enlever " + _liste(tenue.a_enlever))
    return " ; ".join(morceaux)


# --- rendu JSON ----------------------------------------------------------------


def rendre_json(propositions: list[Proposition], contexte: _Contexte) -> dict:
    seance, demande = contexte.seance, contexte.demande
    # La troisième valeur de l'écran de FTP (18/09/2026), même délégation et
    # même bloc que `boucle.rendre_json` — voir `_candidate_json` pour son
    # usage dans `temps_ecoule_s`.
    compteur_info = info_compteur(contexte.config, demande.velo)
    return {
        "jour": seance.jour.isoformat(),
        "seance": {
            "nom": seance.nom,
            "duree_s": round(seance.duree_s),
            "n_etapes": len(seance.etapes),
            "n_blocs": len(seance.blocs()),
            "meta": seance.meta,
        },
        "demande": {
            "distance_km": contexte.distance_km,
            "distance_source": contexte.distance_source,
            "direction": demande.direction or None,
            "azimut_deg": demande.azimut_deg,
            "candidates": demande.nb_candidates,
            "profil": demande.profil,
            "depart": demande.depart.isoformat(),
            # Le **lieu** d'où part cette sortie, en regard de l'heure
            # ci-dessus. Il vaut celui de la configuration, sauf si l'appelant
            # en a fourni un autre (`--adresse-depart`, demain une requête
            # d'API) : sans cette clé, deux réponses JSON identiques
            # décriraient deux parcours partant de deux endroits différents.
            "lieu_depart": {
                "nom": contexte.config.depart.nom,
                "latitude": contexte.config.depart.latitude,
                "longitude": contexte.config.depart.longitude,
            },
            "velo": demande.velo,
        },
        # `null` si la configuration ne porte aucun vélo — en pratique cela
        # n'arrive pas pour `sortie` (`_parametres` lève avant), sauf appel
        # direct de `rendre_json` en test avec une `Config` construite à la
        # main.
        "compteur": compteur_info,
        "modele_physique": contexte.provenance_modele,
        # Q19 : le modèle météo qui a effectivement répondu, et si c'est un
        # repli sur le second avis (le principal ne couvrait pas la
        # fenêtre) — `None` quand aucune candidate n'a de météo (panne).
        "modele_meteo": _modele_meteo_json(propositions),
        # Q40 (a) : l'état « pas de météo », dit une fois et en toutes lettres,
        # au lieu d'un 502 « service en panne » pour une demande simplement
        # hors de portée. `null` quand la météo a répondu. La phrase dit quel
        # est le dernier jour couvert, jamais pourquoi celui-ci ne l'est pas —
        # Open-Meteo rend le même bloc vide dans les deux cas, et le cœur ne
        # tranche pas (règle absolue 5).
        "meteo_absente": (
            None if contexte.meteo_absente is None else contexte.meteo_absente.json()
        ),
        "seuil_bloc_bien_place": NOTE_BLOC_BIEN_PLACE,
        # Écart relatif de note en dessous duquel la pluie départage plutôt que
        # le vent (préférence du cycliste, `config.seance.tolerance_egalite`) :
        # publié pour que le rang des candidates dans `candidates` s'explique
        # sans relire la configuration.
        "tolerance_egalite": contexte.config.seance.tolerance_egalite,
        "gpx": str(contexte.gpx) if contexte.gpx is not None else None,
        "carte": str(contexte.carte) if contexte.carte is not None else None,
        # Lot F2.4 : `etape` dit **où** la candidate est tombée, et `trace` la
        # dessine quand elle existe. Un azimut et une distance ne se dessinent
        # pas : c'est ce qui manquait pour que « 8 candidate(s) écartée(s) »
        # soit autre chose qu'une ligne de texte.
        "ecartees": [
            {
                "azimut_deg": e.azimut_deg,
                "distance_km": round(e.distance_km, 3),
                "motif": e.motif,
                "etape": e.etape,
                "trace": None if e.trace is None else geometrie_json(e.trace),
            }
            for e in contexte.ecartees
        ],
        "tenue": None
        if contexte.tenue is None
        else {
            "categorie_temp": contexte.tenue.categorie_temp,
            "categorie_humidite": contexte.tenue.categorie_humidite,
            "base": contexte.tenue.base,
            "a_emporter": contexte.tenue.a_emporter,
            "a_enlever": contexte.tenue.a_enlever,
            "motifs": contexte.tenue.motifs,
        },
        # Les clés du lot L5.3. `propositions` est le sous-ensemble contrasté
        # de `candidates` : mêmes objets, repérés par `numero`, avec la phrase
        # qui les distingue. `candidates` reste la liste complète et
        # inchangée — un script qui la lisait continue de marcher.
        "propositions": _propositions_json(contexte),
        "question_vent": _question_vent_json(contexte),
        "motif_deux_propositions": (
            contexte.selection.motif_deux_propositions if contexte.selection else None
        ),
        # Le pendant de la clé précédente (Q45) : quand aucune proposition ne
        # se détache, on le dit au lieu de fabriquer une différence. Les deux
        # peuvent être remplies en même temps — deux boucles qui vont ailleurs
        # et qui se valent.
        "motif_equivalence": (
            contexte.selection.motif_equivalence if contexte.selection else None
        ),
        # Lot F2.4 : ce que le contraste a décidé de **chaque** candidate, et
        # par quelle paire. Le produit montrait ce qu'il retenait, jamais ce
        # qu'il jetait ni pourquoi — et c'est au contraste que les candidates
        # du mainteneur disparaissaient.
        "arbitrage": _arbitrage_json(contexte),
        "candidates": [_candidate_json(p, compteur_info) for p in propositions],
    }


def _arbitrage_json(contexte: _Contexte) -> dict | None:
    """Le sort de toutes les candidates au contraste, la matrice, et ce qu'elle mesure.

    `paires` porte **toutes** les paires, pas seulement celles des retenues :
    c'est la matrice complète qui montre qu'une seule case au-dessus du seuil
    interdit tout groupe contenant ses deux boucles. Sans elle, un lecteur
    verrait des verdicts sans pouvoir refaire le raisonnement.

    Aucun pourcentage n'est laissé à calculer en aval : `motif` et `phrase`
    sont écrits par `sortie.contraste`, dans les termes qui décident vraiment.
    """
    selection = contexte.selection
    if selection is None:
        return None
    return {
        "seuil_recouvrement": selection.seuil_recouvrement,
        "candidates": [
            {
                "numero": v.numero,
                "sort": v.sort,
                "recouvrement_max": (
                    None if v.recouvrement_max is None else round(v.recouvrement_max, 4)
                ),
                "contre_numero": v.contre_numero,
                "motif": v.motif,
            }
            for v in selection.verdicts
        ],
        "paires": [
            {
                "a": i + 1,
                "b": j + 1,
                "recouvrement": round(part, 4),
                "au_dessus_du_seuil": part > selection.seuil_recouvrement,
            }
            for (i, j), part in sorted(selection.recouvrements_candidates.items())
        ],
        "essais": (
            None
            if selection.essais is None
            else {
                "taille": selection.essais.taille,
                "essayes": selection.essais.essayes,
                "valides": selection.essais.valides,
                "refuses_par_une_paire": selection.essais.refuses_par_une_paire,
            }
        ),
        "phrase": selection.phrase_arbitrage,
    }


def _propositions_json(contexte: _Contexte) -> list[dict]:
    """Les deux ou trois propositions contrastées, dans l'ordre du tri.

    `distinction` porte la phrase en langage de cycliste, `axe_distinctif`
    l'axe qui la motive. `recouvrement_max_avec` dit, pour chaque autre
    proposition, la part de routes communes — c'est le critère qui garantit
    que deux propositions ne se ressemblent pas sur la carte.
    """
    selection = contexte.selection
    if selection is None:
        return []
    par_paire = selection.recouvrements
    sortie = []
    for i, retenue in enumerate(selection.retenues):
        profil = retenue.profil
        sortie.append(
            {
                "numero": retenue.proposition.numero,
                "retenue": i == 0,
                "distinction": retenue.distinction,
                # L'axe de base, sans son orientation : un consommateur lit « vent »,
                # pas « vent:travers » — l'orientation est déjà sous
                # `orientation_vent`.
                "axe_distinctif": (
                    contraste.axe_de_base(retenue.axe_distinctif)
                    if retenue.axe_distinctif
                    else None
                ),
                "duree_s": round(profil.duree_s),
                # Signé : positif = on rentre plus tard (normal), négatif = la
                # séance est amputée (pas normal). L'axe de contraste, lui,
                # compare la valeur absolue — voir `contraste.PAS_DUREE_S`.
                "depassement_seance_s": (
                    None if profil.depassement_s is None else round(profil.depassement_s)
                ),
                "demi_tours": profil.demi_tours,
                "pluie_mm": (None if profil.pluie_mm is None else round(profil.pluie_mm, 3)),
                # `None` et jamais `0.0` : un tracé sans tag de nœud ne prouve
                # pas qu'il n'y a pas de feu (règle absolue 5), et l'ignorance
                # n'est jamais un malus (contrat du sprint 3).
                "densite_marqueurs_km": (
                    None
                    if profil.densite_marqueurs_km is None
                    else round(profil.densite_marqueurs_km, 3)
                ),
                # **Les entiers, et pas seulement la densité** (ajouté le
                # 17/09/2026). `contraste.Profil` les porte depuis le sprint 3
                # — « affiché tel quel : 28 feux, 20 stops » — mais seule la
                # densité sortait en JSON, si bien que le front les retrouvait
                # en multipliant par la distance : exactement le geste que le
                # commentaire de `contraste.py` nomme comme le piège à éviter.
                # La densité est arrondie à trois décimales, donc ce produit
                # s'efface au-delà de 100 km (relecture F2 · C1). Les rendre
                # supprime la seule arithmétique du front.
                "feux": profil.feux,
                "stops": profil.stops,
                "part_trafic": (
                    None if profil.part_trafic is None else round(profil.part_trafic, 4)
                ),
                "orientation_vent": profil.orientation,
                "note_terrain": round(profil.note_terrain, 4),
                "recouvrement_max_avec": {
                    str(selection.retenues[j].proposition.numero): round(part, 4)
                    for (a, b), part in par_paire.items()
                    for j in ((b,) if a == i else (a,) if b == i else ())
                },
            }
        )
    return sortie


def _question_vent_json(contexte: _Contexte) -> dict | None:
    """Ce que le vent au départ permettait de demander, et ce qui a été demandé."""
    question = contexte.question_vent
    if question is None:
        return None
    return {
        "posee": question.posee,
        "motif": question.motif or None,
        "vent_kmh": question.vent_kmh,
        "vent_depuis_deg": question.vent_depuis_deg,
        "seuil_kmh": vent_demande.SEUIL_VENT_SENSIBLE_KMH,
        "horizon_jours": vent_demande.HORIZON_ORIENTATION_J,
        "reponse": contexte.demande.vent,
        # Pluriel depuis Q44 : « de travers » en ouvre deux, opposés. Le
        # singulier `azimut_recherche_deg` disparaît plutôt que de coexister —
        # un consommateur qui l'aurait lu aurait cru à un seul azimut exploré.
        "azimuts_recherche_deg": list(question.azimuts_pour(contexte.demande.vent)),
        "choix": list(orientation.CHOIX),
        "azimuts_par_choix": {
            choix: list(question.azimuts_pour(choix)) for choix in orientation.CHOIX
        },
    }


def _emplacement_json(e: Emplacement) -> dict:
    """Un emplacement en JSON — `note` et le reste de `NoteBloc` à `None` sans bloc.

    Q13, lot L5.2 : un `0.0` à la place de `None` se lirait, par un script
    comme par un humain, comme un couloir parfait — c'est précisément le
    défaut que le contrat §2.2 a) interdit.

    `debut_parcouru_m` est le compteur kilométrique (ne recule jamais) ;
    `debut_m` reste la position sur le tracé (recule après un demi-tour). Un
    script qui veut afficher un kilomètre lit le premier, pas le second.
    """
    base = {
        "etape_idx": e.etape_idx,
        "debut_m": round(e.debut_m, 1),
        "debut_parcouru_m": round(e.debut_parcouru_m, 1),
        "longueur_m": round(e.longueur_m, 1),
        "demi_tour": e.demi_tour,
    }
    if e.note is None:
        return base | {
            "note": None,
            "motifs": None,
            "pente_moyenne": None,
            "pente_max": None,
            "carrefours": None,
            "km_batis": None,
            "descente_m": None,
            "montee_m": None,
        }
    return base | {
        "note": round(e.note.note, 4),
        "motifs": e.note.motifs,
        "pente_moyenne": round(e.note.pente_moyenne, 5),
        "pente_max": round(e.note.pente_max, 5),
        "carrefours": e.note.carrefours,
        "km_batis": round(e.note.km_batis, 3),
        "descente_m": round(e.note.descente_m, 1),
        "montee_m": round(e.note.montee_m, 1),
    }


def _candidate_json(proposition: Proposition, compteur_info: dict | None = None) -> dict:
    trace, placement, meteo = proposition.trace, proposition.placement, proposition.meteo
    temps_ecoule_s = temps_ecoule_bas_s = temps_ecoule_haut_s = temps_ecoule_source = None
    if compteur_info is not None:
        pp = porte_a_porte(placement.duree_totale_s, compteur_info)
        temps_ecoule_s = round(pp.mediane_s)
        temps_ecoule_bas_s, temps_ecoule_haut_s = round(pp.bas_s), round(pp.haut_s)
        temps_ecoule_source = pp.provenance
    return {
        "numero": proposition.numero,
        "retenue": proposition.numero == 1,
        "nom": trace.nom,
        "distance_km": round(trace.distance_m / 1000.0, 3),
        "denivele_m": trace.denivele_m,
        "azimut_deg": proposition.azimut_deg,
        "ecart_relatif": proposition.ecart_relatif,
        # L'écart à la distance demandée cesse d'être tu (Q41 d).
        "hors_tolerance": bool(proposition.elargissement),
        "elargissement": proposition.elargissement,
        "tolerance_distance": proposition.tolerance_distance,
        "part_connue": proposition.part_connue,
        "vitesse_kmh": round(proposition.vitesse_kmh, 2),
        # Le porte à porte, arrêts compris. **Au niveau de la candidate, et
        # non dans `placement`** (déplacé le 18/09/2026) : le voisinage de
        # `duree_totale_s`, son analogue en mouvement, était tentant, mais le
        # temps écoulé est une propriété du *parcours*, pas du placement de
        # la séance dessus — et `boucle` le publie déjà à ce niveau-là. Un
        # même chiffre à deux adresses selon la route obligeait le front à
        # connaître deux chemins pour un seul composant, et le second était
        # tombé silencieusement : aucune erreur, juste un chiffre manquant.
        # Depuis L9.1, une fourchette (`physique.modele.temps_ecoule`) :
        # `temps_ecoule_s` en est la médiane, `_bas_s`/`_haut_s` les bornes,
        # la source « mesure » ou « defaut ». `null` avec `compteur` : sans
        # vélo, pas de fourchette.
        "temps_ecoule_s": temps_ecoule_s,
        "temps_ecoule_bas_s": temps_ecoule_bas_s,
        "temps_ecoule_haut_s": temps_ecoule_haut_s,
        "temps_ecoule_source": temps_ecoule_source,
        "placement": {
            "note_totale": round(placement.note_totale, 4),
            "note_terrain": round(placement.note_terrain, 4),
            "penalite_seance": round(placement.penalite_seance, 4),
            "decalage_z2_s": round(placement.decalage_z2_s),
            "duree_totale_s": round(placement.duree_totale_s),
            "distance_totale_m": round(placement.distance_totale_m, 1),
            # Le D+ du **parcours placé**, recalculé par `denivele_filtre`, à côté
            # du `denivele_m` de la boucle annoncé par le moteur : deux méthodes
            # qui divergent, et la règle absolue 5 demande qu'on le voie.
            "denivele_parcours_m": (
                None
                if proposition.denivele_parcours_m is None
                else round(proposition.denivele_parcours_m, 1)
            ),
            "blocs_bien_places": proposition.blocs_bien_places,
            "demi_tours": proposition.demi_tours,
            "avertissements": placement.avertissements,
            # Ce qui se dit sans être un défaut — le retour au calme qui
            # s'allonge dans sa fenêtre (Q14). Séparé des avertissements
            # parce qu'un script qui compte les défauts ne doit pas le compter.
            "informations": placement.informations,
            # Toutes les étapes de la séance, pas seulement les blocs (Q13, lot
            # L5.2) : `_emplacement_json` met `None`, jamais `0.0`, pour tout ce
            # qu'une récupération n'a pas — un script qui lirait un `0.0` le
            # prendrait pour un couloir parfait.
            "emplacements": [_emplacement_json(e) for e in placement.emplacements],
        },
        "couts": {
            "km_trafic": round(proposition.couts.km_trafic, 3),
            "km_calme": round(proposition.couts.km_calme, 3),
            # Sérialisé le 17/09/2026, comme il l'était déjà côté boucle
            # libre. `km_trafic` et `km_calme` **ne font pas la distance** :
            # le reste est sur des voies que le moteur ne sait pas classer, et
            # sans ce chiffre un tracé à moitié sur des chemins s'annonce
            # « 0,0 km de trafic » comme un tracé parfaitement calme (voir le
            # commentaire du champ dans `boucle.couts.Couts`).
            "km_non_classe": round(proposition.couts.km_non_classe, 3),
            "km_non_revetu": round(proposition.couts.km_non_revetu, 3),
            "score": round(proposition.couts.score, 3),
            "sens": proposition.couts.sens,
        },
        "meteo": None
        if meteo is None
        else {
            "pluie_cumulee_mm": round(meteo.pluie_cumulee_mm, 3),
            "minutes_pluie": round(meteo.minutes_pluie, 1),
            "part_vent_face": round(meteo.part_vent_face, 3),
            "ressenti_min_c": meteo.ressenti_min_c,
            "confiance": meteo.confiance,
            "n_echantillons": len(meteo.echantillons),
            # Les mêmes flèches que la page HTML du sprint 5 dessine, filtrées
            # au même seuil parce que c'est le même code — voir
            # `boucle.meteo_trace.fleches_vent`.
            "fleches_vent": fleches_vent(meteo),
            # Le tracé entier, pour le colorer (lot d'affordance, 20/09/2026) :
            # aucun filtre de sensibilité, voir `boucle.meteo_trace.vent_par_position`.
            "vent_par_position": vent_par_position(meteo),
            "modele_utilise": meteo.modele_utilise,
            "repli": meteo.repli,
        },
        # Lot F0.1 : la géométrie n'existait dans aucun JSON, seulement dans
        # le GPX et le HTML Leaflet (`docs/journal/ux/discovery_donnees.md` §2). Les
        # `debut_m`/`longueur_m` des `emplacements` ci-dessus se raccordent à
        # `trace.profil` par recherche dichotomique sur `dist_m` — voir la
        # docstring de `boucle.geometrie`.
        "trace": geometrie_json(trace),
    }


# --- petits rendus -------------------------------------------------------------


def _puissance(etape) -> str:
    bas, haut = etape.puissance_min_w, etape.puissance_max_w
    if bas is None and haut is None:
        return etape.libelle_court or "sans consigne"
    if bas is None or haut is None:
        return f"{(bas if bas is not None else haut):.0f} W"
    return f"{bas:.0f} W" if bas == haut else f"{bas:.0f}-{haut:.0f} W"


def _azimut(azimut_deg: float | None) -> str:
    return f"{azimut_deg:.0f}°" if azimut_deg is not None else "direction inconnue"


def _azimuts(azimuts_deg: Sequence[float]) -> str:
    """Un azimut, ou deux joints par « et » — le travers en ouvre deux (Q44).

    Écrire « 315° » quand la recherche a exploré 315° **et** 135° serait faux
    au même titre que « dans toutes les directions » quand une seule a été
    explorée : le lecteur doit pouvoir retrouver sur la carte ce qu'on lui dit
    d'avoir cherché.
    """
    if not azimuts_deg:
        return "direction inconnue"
    return " et ".join(_azimut(a) for a in azimuts_deg)


def _liste(elements) -> str:
    return ", ".join(elements) if elements else "rien de particulier"


def _minutes(secondes: float) -> str:
    return f"{secondes / 60:+.0f} min"


def _duree_courte(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _temps_texte(proposition: Proposition, compteur_info: dict | None) -> str:
    """« 2:14 » seul, ou « 2:20-2:31 / 2:14 » — porte à porte en fourchette / sans arrêt.

    Même ordre, même choix d'affichage et même légende (`ligne_temps_ecoule`)
    que `boucle` : le porte à porte d'abord, parce que c'est lui qui répond à
    la durée demandée, et une cellule combinée plutôt qu'une colonne de plus.
    Le temps sans arrêt est celui du **parcours réellement roulé**
    (`duree_totale_s`, demi-tours compris), pas celui de la boucle : c'est
    déjà la règle de la colonne « temps » elle-même (voir
    `_notes_sous_tableau`).
    """
    placement = proposition.placement
    if compteur_info is None:
        return _duree_courte(placement.duree_totale_s)
    pp = porte_a_porte(placement.duree_totale_s, compteur_info)
    return (
        f"{_duree_courte(pp.bas_s)}-{_duree_courte(pp.haut_s)} / "
        f"{_duree_courte(placement.duree_totale_s)}"
    )


def _duree_longue(secondes: float) -> str:
    minutes = int(round(secondes / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def _fr(valeur: float, decimales: int) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


__all__ = [
    "ARRONDI_DISTANCE_KM",
    "NOTE_BLOC_BIEN_PLACE",
    "Demande",
    "GpxPropose",
    "Proposition",
    "executer",
    "lire_options",
    "rendre_json",
    "rendre_texte",
]

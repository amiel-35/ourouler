"""Sous-commande `ourouler sortie` : la séance du jour, posée sur une boucle.

L'enchaînement :

1. la **séance du jour** est lue chez Intervals.icu ; s'il n'y en a
   pas, on le dit et on sort en 0 — ce n'est pas une erreur ;
1 bis. la **question de l'orientation au vent** est posée **avant** la
   recherche : un appel Open-Meteo sur un point et une heure, donc
   le poste le moins cher, et il tombe avant BRouter. Elle ne se pose que si
   le vent se sent (8 km/h, `boucle.meteo_trace.SEUIL_VENT_SENSIBLE_KMH`) et à trois
   jours au plus. Quand elle a une réponse (`--vent`), elle **dirige** la
   recherche au lieu de contraster après coup ;
2. des **boucles candidates** sont demandées au moteur, de la
   longueur qu'il faut pour la séance ;
3. chacune reçoit un premier **placement** des blocs, sans vent.
   Celles où la séance ne tient pas sont écartées, et le tableau dit combien
   et pourquoi ;
4. sur les retenues : ce premier placement date une météo qui n'a qu'un but,
   donner le **champ de vent** le long du tracé — et la séance est
   **replacée** avec ce vent. C'est une deuxième passe, pas une itération : le
   vent bouge lentement et l'écart d'heure de passage qu'induit le premier
   placement se compte en minutes ;
5. sur les retenues, avec leur placement définitif : **coûts** du tracé,
   **météo** à l'heure de passage définitive et **tenue** ;
6. tri par **note de placement d'abord** — elle inclut le vent —, puis par
   **pluie cumulée** quand deux notes sont égales à
   `config.seance.tolerance_egalite` près ;
7. la meilleure part en **GPX** sur disque (le parcours qu'on va rouler) ;
8. et **deux ou trois propositions contrastées** sont extraites de ce
   classement (`sortie.contraste`), chacune avec la phrase qui la
   distingue des autres en langage de cycliste. La première reste celle du
   tri : on ne change pas ce que l'outil recommande, on ajoute ce à quoi le
   comparer. **Si moins de trois sont retenues, les étapes 2 à 8 sont
   rejouées avec plus de candidates** (paliers de `PALIERS_RELANCE_CANDIDATES`),
   jusqu'à trois retenues ou un plafond de tentatives — sans action du
   cycliste, et dans le même appel (une génération demandée reste une seule
   entrée de quota). Quand trois vraies boucles disjointes n'existent
   toujours pas après ce plafond, on en rend deux et on dit pourquoi ;
9. et ces mêmes propositions deviennent **la page du jour**
   (`rendu.sortie.page_jour`) : une carte, les tracés superposés,
   seule la sélectionnée en couleurs — et un GPX par proposition,
   téléchargeable depuis la page, qui suit le choix du cycliste et non le
   classement.

L'ordre du tri n'est pas anodin : la pluie se contourne en partant une heure
plus tard, un bloc de seuil dans un village ne se contourne pas, un vent de
face non plus. La météo
départage, elle ne décide pas — sauf à égalité de note, où c'est elle qui
tranche entre deux boucles que le terrain et le vent ne distinguent pas.

Ce module est le cas d'usage : il reçoit une `Demande` déjà lue et validée
par l'entrée (`commandes/sortie.py`, qui lit argparse) et un
`services.contexte.Contexte` ; c'est lui qui lit `calibration.json` et
`poids_routes.json` (aux chemins que le contexte a résolus) et qui passe des
objets au cœur. Les trois clients — BRouter, Open-Meteo, Intervals — sont
injectables pour que les tests ne touchent jamais le réseau. Ce qu'il montre
— tableau, JSON, phrases, page du jour — est construit par `rendu/sortie.py` ;
ce module écrit le GPX et rend un résultat, et c'est l'entrée qui écrit la
page du jour et imprime.

**`--fichier-seance`** : l'étape 1 lit alors un `.ZWO`/`.MRC` donné en
ligne de commande au lieu d'interroger Intervals.icu — `_seance` bascule
dessus quand `demande.fichier` est renseigné, tout le reste de l'enchaînement
est inchangé.

**Ce que la météo n'empêche pas.** Comme pour `boucle`, une panne d'Open-Meteo
fait disparaître les colonnes météo et la tenue, avec un avertissement sur la
sortie d'erreur : perdre la séance parce qu'il manque la pluie serait absurde.
C'est le cas normal pour un `--jour` passé, hors de l'horizon de prévision.
"""

from __future__ import annotations

import functools
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ourouler.apprentissage.routes import BaseRoutes, lire_poids
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.gpx import description as description_gpx
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.boucle.horaire import construire_horaire
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.meteo import portee
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.noyau.erreurs import (
    ErreurConnecteur,
    ErreurDistanceInatteignable,
    ErreurIntervalsAbsent,
    ErreurUtilisateur,
)
from ourouler.noyau.profil import Profil
from ourouler.noyau.seance import Seance
from ourouler.noyau.texte import azimut_texte
from ourouler.noyau.trace import Trace
from ourouler.physique.modele import Parametres, vitesse_a_plat_ms
from ourouler.seance.ecran_ftp import info_compteur
from ourouler.seance.intervals import seance_du_jour
from ourouler.seance.placement import CLE_MOTIF, placer
from ourouler.seance.placement_resultat import Placement, trace_parcourue
from ourouler.seance.tenue import Tenue
from ourouler.seance.tenue import conseiller as conseiller_tenue
from ourouler.seance.vent import ChampVent
from ourouler.services.apprentissage import NOM_POIDS, base_routes_existante
from ourouler.services.contexte import Contexte
from ourouler.services.seance import longueurs
from ourouler.sortie import contraste, orientation, vent_demande

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

#: Poids de la pluie dans le tri, **à note de placement égale** : c'est le
#: même millimètre que dans `boucle`, mais il n'arrive qu'en second critère.
POIDS_PLUIE_TRI = 2.0

#: Paliers de candidates essayés **après** le nombre demandé, quand la
#: recherche ne retient pas trois boucles contrastées (QP4, 25/09/2026 :
#: « relancer "Chercher plus loin" d'office jusqu'à trois boucles
#: retenues »). `8` est le nombre déjà utilisé par le bouton « Chercher plus
#: loin » du front — la relance d'office rejoue exactement ce que le
#: cycliste aurait demandé lui-même. `12` est un second filet, plus coûteux,
#: pour les cas où huit candidates ne suffiraient pas.
#:
#: Mesuré le 27/09/2026 sur douze demandes réelles du mainteneur (durées
#: 60/90/120 min, deux jours, plusieurs heures et directions) : dix sur
#: douze retenaient déjà trois boucles au premier essai (5 candidates, la
#: configuration du mainteneur) ; les deux qui n'en retenaient que deux s'en
#: sortaient toutes les deux avec la seule relance à 8 candidates (13 appels
#: BRouter contre 7 au premier essai) — le palier à 12 n'a jamais été
#: nécessaire dans cette mesure. Il reste posé comme plafond, pas comme
#: réglage courant : sans lui, un point de départ où trois boucles
#: disjointes n'existent vraiment pas multiplierait les essais sans fin.
PALIERS_RELANCE_CANDIDATES: tuple[int, ...] = (8, 12)

#: Le nombre de boucles contrastées visé par la relance d'office. `3`, pas
#: une constante réglable : c'est ce que `contraste.choisir` vise par défaut
#: (`combien=3`), et la relance n'a de sens que si elle vise la même cible.
COMBIEN_PROPOSITIONS_VISEES = 3


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
    #: propositions contrastées.
    vent: str = orientation.PEU_IMPORTE
    #: `--fichier-seance` : un `.ZWO`/`.MRC` à la place d'Intervals.icu.
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
    #: cette boucle, par paliers de 5 %. `0.0` : elle y tenait.
    elargissement: float | None = None
    #: La tolérance de distance en vigueur quand la boucle a été jugée.
    tolerance_distance: float | None = None

    @property
    def pluie_mm(self) -> float:
        return self.meteo.pluie_cumulee_mm if self.meteo is not None else 0.0

    @property
    def blocs_bien_places(self) -> int:
        # `placement.blocs()`, jamais `placement.emplacements` : cette liste
        # porte aussi l'échauffement, les récupérations et le
        # retour au calme, qui n'ont pas de note. `e.note.note` lèverait sur un
        # `None`, et un `e.note.note if e.note else 0.0` compterait ces
        # non-blocs comme « bien placés », une régression silencieuse.
        return sum(1 for e in self.placement.blocs() if e.note.note < NOTE_BLOC_BIEN_PLACE)

    @property
    def demi_tours(self) -> int:
        # Idem : une récupération de demi-tour porte aussi `demi_tour=True`
        # — la compter en plus du bloc doublerait l'affichage.
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
        """Note de placement d'abord, pluie cumulée ensuite.

        **N'est pas le tri réellement appliqué par `executer`**, puisque le
        vent entre dans la note : ce tuple compare les notes au
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

    `trace` est la boucle elle-même quand elle existe. Un azimut et une
    distance ne se dessinent pas : sans la géométrie, « 8 candidates
    écartées » resterait une ligne de texte que le cycliste ne pourrait pas
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


@dataclass(frozen=True)
class SansSeance:
    """Rien de planifié ce jour-là : une réponse, pas une erreur (code 0)."""

    demande: Demande


@dataclass(frozen=True)
class ResultatSortie:
    """Les propositions classées, et tout ce que le rendu et la page du jour en disent."""

    propositions: list[Proposition]
    #: Le contexte du rendu ; `carte` y vaut `None` tant que l'entrée n'a pas
    #: écrit la page du jour.
    contexte: _Contexte
    #: Les GPX des propositions contrastées, en mémoire, pour la page du jour.
    gpx_propositions: list[GpxPropose]
    #: Le motif de la panne météo, s'il y en a eu une.
    panne: str | None


def executer(
    demande: Demande,
    contexte: Contexte,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    client_intervals: ClientIntervals | None = None,
    *,
    recueil_gpx: Callable[[list[GpxPropose]], None] | None = None,
    base_routes: BaseRoutes | None = None,
) -> SansSeance | ResultatSortie:
    """Exécute `ourouler sortie` : `SansSeance` un jour sans séance, `ResultatSortie` sinon.

    `base_routes` s'injecte comme les clients, pour la même raison et de la
    même façon que dans `services/boucle.executer` (décision Q58) : absente, la
    base est ouverte sur `contexte.dossier_cache` avec le propriétaire par
    défaut, ce qui est le bon comportement en ligne de commande et le mauvais
    dans un service qui sert plusieurs cyclistes.

    Le point de départ est `contexte.profil.depart` : l'entrée y a déjà mis
    celui de **cette** exécution (`--adresse-depart` géocodée par `cli/`, ou
    les coordonnées que l'API a reçues). Le cœur ne géocode rien, ne lit
    aucune adresse et ne sait pas d'où vient ce point (le cœur ne lit ni
    configuration ni environnement). À ne
    pas confondre avec `demande.depart`, qui porte une **heure**.

    `recueil_gpx` décide **à qui va le GPX** : aucun GPX à la génération, un
    GPX à la demande quand le cycliste choisit son parcours (décision Q40 g,
    `docs/journal/questions/questions_mainteneur.md`). Absent — le cas de la ligne de commande — le GPX
    de la proposition retenue est écrit sur le disque, à `--sortie` ou au nom
    daté par défaut. Présent, **aucun fichier n'est
    écrit** : les trois GPX sont remis à l'appelant, qui n'en servira qu'un,
    celui que le cycliste aura choisi. Les trois propositions sont
    contrastées exprès ; n'écrire que celle du classement, ce serait envoyer
    la mauvaise trace au compteur à qui choisissait « la plus sèche ».

    Ce qui ne suit pas le départ : les **routes connues** et les **poids
    appris** du cache (`routes.sqlite`, `poids_routes.json`) ont été mesurés
    autour du départ configuré. Partir d'ailleurs ne les casse pas — la part
    connue est informative et n'entre dans aucun score — mais elle tombera
    naturellement à zéro loin de chez soi. `cli/` le dit sur la sortie
    d'erreur plutôt que de laisser croire à un tracé
    inédit.
    """
    profil = contexte.profil
    seance = _seance(demande, profil, client_intervals)
    if seance is None:
        # Pas de séance : pour un service planifié, l'entrée écrit, si on le lui
        # demande, la page qui le dit.
        return SansSeance(demande=demande)

    parametres, provenance = _parametres(profil, demande.velo, contexte.fichier_calibration)
    distance_km, distance_source = _distance(demande, seance, parametres, profil)

    # Une date lointaine ne se refuse pas, elle se sert **sans
    # météo**. On le constate ici, avant le premier appel : demander une
    # prévision pour dans dix ans coûterait ~150 appels Open-Meteo pour
    # récolter trois blocs vides, puis un message sur ce qu'Open-Meteo ne
    # couvre pas — là où le cycliste veut lire « pas de météo ce jour-là » et
    # recevoir sa boucle.
    dernier_jour = portee.dernier_jour_couvert(profil.meteo.horizon_jours, aujourdhui=date.today())
    meteo_absente = portee.constater(demande.jour, dernier_jour) if demande.jour > dernier_jour else None

    # La question du vent se pose **avant** la recherche :
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
            profil.depart,
            depart_heure=demande.depart,
            jour=demande.jour,
            modele=profil.meteo.modele,
            modele_repli=profil.meteo.second_avis,
        )
    azimuts_vent = question.azimuts_pour(demande.vent)

    client_brouter = (
        client_brouter
        if client_brouter is not None
        else ClientBrouter(profil.brouter, evitements=profil.evitements)
    )

    # La relance d'office (QP4, 25/09/2026) : quand la recherche ne retient
    # pas trois boucles contrastées, on la rejoue avec plus de candidates —
    # exactement ce que le bouton « Chercher plus loin » ferait à la place du
    # cycliste — jusqu'à trois retenues ou un palier borné
    # (`PALIERS_RELANCE_CANDIDATES`). Tout se passe dans cet unique appel à
    # `executer` : une génération demandée reste une seule entrée de quota,
    # quel que soit le nombre d'essais internes (`api/quotas.py` compte
    # l'appel HTTP, pas ces essais).
    ecartees: list[Ecartee] = []
    propositions: list[Proposition] = []
    panne: str | None = None
    selection: contraste.Selection | None = None
    paliers = _paliers_candidates(demande.nb_candidates)
    for essai_nb in paliers:
        dernier_essai = essai_nb == paliers[-1]
        candidates, hors_bande = _candidates(
            client_brouter, profil, demande, distance_km, azimuts_vent, nb_candidates=essai_nb
        )
        retenues, ecartees_placement = _placer_toutes(candidates, seance, profil, parametres)
        # Les directions refusées sur la distance rejoignent celles que le
        # placement a refusées : deux motifs différents, un seul endroit où
        # le cycliste les lit. Sans ça, demander cinq directions et en voir
        # trois se passait en silence — c'est le défaut même que ce lot
        # corrige, il n'a pas à revenir par la porte de derrière.
        ecartees = hors_bande + ecartees_placement
        if not retenues:
            if dernier_essai:
                raise ErreurUtilisateur(motif_aucune(seance, ecartees, distance_km))
            continue

        retenues = _replacer_avec_vent(retenues, seance, profil, parametres, demande, client_meteo)
        propositions, panne = _mesurer(
            retenues, profil, demande, client_meteo, base_routes, dossier_cache=contexte.dossier_cache
        )
        propositions.sort(key=functools.cmp_to_key(_comparer(profil.seance.tolerance_egalite)))
        for numero, proposition in enumerate(propositions, start=1):
            proposition.numero = numero

        # Les trois propositions contrastées. La première reste celle
        # que le tri ci-dessus a retenue : on ne change pas ce que l'outil
        # recommande, on ajoute ce à quoi le comparer.
        selection = contraste.choisir(propositions, duree_seance_s=seance.duree_s)
        if len(selection.retenues) >= COMBIEN_PROPOSITIONS_VISEES or dernier_essai:
            break

    # La boucle ci-dessus ne se termine jamais sans `break` ni exception :
    # le dernier palier lève `ErreurUtilisateur` s'il n'a rien retenu, et
    # `break` s'exécute sinon (au moins au dernier palier). `selection` est
    # donc toujours renseigné ici — l'assertion ne fait que le dire au
    # vérificateur de types.
    assert selection is not None
    meilleure = propositions[0]
    tenue = conseiller_tenue(meilleure.meteo, profil.tenue) if meilleure.meteo is not None else None
    gpx_propositions = _gpx_propositions(seance, demande, selection)
    chemin_gpx = None
    if recueil_gpx is None:
        chemin_gpx = _ecrire_gpx(
            meilleure.trace, meilleure.placement, seance, demande, contexte.dossier_cache
        )
    else:
        recueil_gpx(gpx_propositions)

    # Une météo tombée dans l'horizon est le même état à l'écran qu'une date
    # trop lointaine (E14 · dégradé) : la boucle reste servie, la pluie, le
    # vent et la tenue disparaissent. La phrase, elle, ne dit pas pourquoi.
    if meteo_absente is None and panne is not None:
        meteo_absente = portee.constater(demande.jour, dernier_jour)
    pour_le_rendu = _Contexte(
        seance=seance,
        demande=demande,
        config=profil,
        distance_km=distance_km,
        distance_source=distance_source,
        provenance_modele=provenance,
        ecartees=ecartees,
        tenue=tenue,
        gpx=chemin_gpx,
        # La page du jour est écrite par l'entrée, qui pose ici son chemin.
        carte=None,
        selection=selection,
        question_vent=question,
        meteo_absente=meteo_absente,
        # La troisième valeur de l'écran de FTP : `sortie` a
        # toujours un vélo (`_parametres` lève sinon), donc ce bloc n'est
        # `None` qu'en test avec une configuration construite à la main. Lu
        # ici et non dans le rendu : il relit la calibration du vélo.
        compteur_info=info_compteur(profil, demande.velo, fichier_calibration=contexte.fichier_calibration),
    )
    return ResultatSortie(
        propositions=propositions,
        contexte=pour_le_rendu,
        gpx_propositions=gpx_propositions,
        panne=panne,
    )


@dataclass(frozen=True)
class _Contexte:
    """Tout ce que les deux rendus ont besoin de savoir, en plus des propositions."""

    seance: Seance
    demande: Demande
    #: Le profil du cycliste (le champ garde son nom historique, `config`).
    config: Profil
    distance_km: float
    distance_source: str
    provenance_modele: str
    ecartees: list[Ecartee]
    tenue: Tenue | None
    gpx: Path | None
    carte: Path | None
    #: Les propositions contrastées et leurs phrases.
    selection: contraste.Selection | None = None
    #: Ce que le vent au départ permettait de demander, et pourquoi.
    question_vent: vent_demande.QuestionVent | None = None
    #: L'état « pas de météo » quand il y en a un — la phrase à
    #: afficher et le dernier jour couvert. `None` quand la météo a répondu.
    meteo_absente: portee.MeteoAbsente | None = None
    #: Le bloc « compteur » (`seance.ecran_ftp.info_compteur`) : moyenne
    #: compteur et fourchette porte à porte du vélo. `None` sans vélo.
    compteur_info: dict | None = None


def motif_aucune(seance: Seance, ecartees: list[Ecartee], distance_km: float) -> str:
    """Le message quand **aucune** candidate ne porte la séance.

    Code de sortie 2, et non 0 : ce n'est pas le cas « rien de prévu
    aujourd'hui » (qui est une réponse), c'est « je n'ai rien à proposer » —
    le même cas que `boucle` quand le moteur ne rend aucune boucle bornée, qui
    sort déjà en 2. Un script qui enchaîne sur le GPX doit s'arrêter là.

    Il appartient au cas d'usage, pas au rendu : c'est le texte de l'erreur
    qu'il lève, pas un rendu de son résultat.
    """

    detail = "; ".join(
        f"{azimut_texte(e.azimut_deg)} {e.distance_km:.1f} km : {e.motif}" for e in ecartees[:3]
    )
    suite = f" (et {len(ecartees) - 3} autre(s))" if len(ecartees) > 3 else ""
    return (
        f"sortie : la séance « {seance.nom} » ne tient sur aucune des {len(ecartees)} boucle(s) "
        f"proposées autour de {distance_km:g} km — {detail}{suite}. "
        "Essayer --distance plus grande, une autre direction, ou plus de candidates."
    )


# --- options ------------------------------------------------------------------


def heure_depart_du_jour(brut: str | None, jour: date) -> datetime:
    """L'heure de départ, **ramenée au jour de la séance**.

    `heure_depart` interprète « 09:00 » comme « aujourd'hui à 9 h » : demander
    la séance du 8 février daterait alors la météo d'aujourd'hui, ce qui n'a
    aucun sens. On garde donc l'heure (et le fuseau) que `heure_depart`
    calcule, et on remplace la date par celle de la séance — sauf si
    l'utilisateur a écrit la date lui-même.
    """
    from ourouler.services.meteo import heure_depart

    quand = heure_depart(brut)
    if brut and "T" in str(brut):
        return quand
    return quand.replace(year=jour.year, month=jour.month, day=jour.day)


def _dossier_sorties_par_defaut(dossier_cache: Path) -> Path:
    """Le dossier des fichiers produits par défaut, hors du dépôt.

    Sans lui, sans `--sortie` ni `--carte`, `sortie_AAAAMMJJ.gpx` et `.html`
    s'écriraient dans le répertoire courant — le dépôt, quand la commande est
    lancée de là. `.gitignore` les couvre, mais ces fichiers portent des
    coordonnées de départ : « un
    fichier que seul `.gitignore` protège n'est pas protégé, il est
    seulement discret. »

    Un sous-dossier du cache déjà configuré (`Contexte.dossier_cache`,
    `~/.cache/ourouler` par défaut) : une destination qui n'ajoute pas de
    nouveau réglage. Créé au
    besoin : le premier `ourouler sortie` d'une machine neuve ne doit pas
    échouer faute de dossier.
    """
    dossier = dossier_cache / "sorties"
    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ErreurUtilisateur(f"{dossier} : impossible de créer le dossier ({e})") from e
    return dossier


def chemin_gpx_par_defaut(demande: Demande, dossier_cache: Path) -> Path:
    """`sortie_<AAAAMMJJ>.gpx` dans le dossier de sortie par défaut, ou le `--sortie` demandé."""
    return demande.sortie or (
        _dossier_sorties_par_defaut(dossier_cache) / f"sortie_{demande.jour:%Y%m%d}.gpx"
    )


def chemin_carte_par_defaut(demande: Demande, dossier_cache: Path) -> Path:
    """`sortie_<AAAAMMJJ>.html` dans le dossier de sortie par défaut, ou le `--carte` demandé."""
    return demande.carte or (
        _dossier_sorties_par_defaut(dossier_cache) / f"sortie_{demande.jour:%Y%m%d}.html"
    )


def verifier_ecriture(chemin: Path, *, explicite: bool, ecraser: bool) -> None:
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


def _seance(demande: Demande, config: Profil, client: ClientIntervals | None) -> Seance | None:
    """La séance à placer : Intervals.icu, ou `demande.fichier` s'il est donné."""
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


def _parametres(profil: Profil, velo: str | None, fichier_calibration: Path) -> tuple[Parametres, str]:
    """Les paramètres physiques du vélo et leur provenance.

    Contrairement à `ourouler seance`, qui préfère une vitesse moyenne assumée
    à un CdA inventé, `sortie` **a besoin** d'un modèle : sans lui, on ne sait
    pas à quelle vitesse chaque étape avance le long du tracé, donc on ne sait
    pas où tombent les blocs. On prend donc ce qu'on a — calibration,
    configuration ou valeurs par défaut — et la provenance est affichée en
    toutes lettres.
    """
    from ourouler.services.physique import (
        alerte_calibration,
        parametres_du_velo,
        velo_demande,
    )

    choisi = velo_demande(profil, velo)
    parametres, provenance = parametres_du_velo(profil, choisi, fichier_calibration)
    alerte = alerte_calibration(choisi, fichier_calibration)
    # L'alerte suit la provenance, qui s'affiche en texte comme en JSON : une
    # calibration qui ne suit plus le pneu du vélo reste utilisée, mais dite.
    suite = f" — {alerte}" if alerte else ""
    return parametres, f"{provenance} ({choisi.nom}){suite}"


def _distance(demande: Demande, seance: Seance, parametres: Parametres, config: Profil) -> tuple[float, str]:
    """(distance en km, d'où elle vient). `--distance` gagne toujours."""
    if demande.distance_km is not None:
        return demande.distance_km, "demandée"
    mesures = longueurs(seance, parametres=parametres)
    # Une étape « libre » — sans puissance prescrite — n'a pas de longueur
    # chiffrée. La compter pour **zéro kilomètre** sous-dimensionnerait la
    # boucle à proportion. Mesuré sur une séance de référence de 22 étapes,
    # dont trois libres (échauffement 20 min, récupération 12 min, retour au
    # calme 40 min) : 63 min chiffrées sur 135 — **plus de la moitié de la
    # séance serait invisible**, et le moteur demanderait 35 km pour une
    # sortie de 67. Il rattraperait ensuite en roulant la boucle presque deux
    # fois, avec des demi-tours dont personne n'a besoin.
    #
    # Une étape libre se roule à l'allure d'endurance : c'est l'hypothèse la
    # plus plate qui soit, et infiniment meilleure que zéro.
    connues = [m.longueur_m for m in mesures if m.longueur_m is not None]
    libres_s = sum(m.etape.duree_s for m in mesures if m.longueur_m is None and m.etape.duree_s > 0)
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


@dataclass(frozen=True)
class DemandeVent:
    """Le jour, et l'heure de départ déjà ramenée à ce jour."""

    jour: date
    depart: datetime


@dataclass(frozen=True)
class ResultatVent:
    question: vent_demande.QuestionVent
    jour: date
    depart: datetime


def executer_vent(
    demande: DemandeVent,
    contexte: Contexte,
    client_meteo: ClientOpenMeteo | None = None,
) -> ResultatVent:
    """Le vent au départ, **avant** de chercher quoi que ce soit.

    Un seul appel Open-Meteo, un point, une heure : le poste le moins cher du
    produit. Il existe parce que l'écran de demande doit montrer d'où vient le
    vent *pendant* que le cycliste choisit sa direction — « Vent de sud-ouest à
    22 km/h demain matin », comme le prévoit la maquette E16.

    Montrer le vent **ou** proposer trois préférences n'est pas un « soit /
    soit » : les deux modes en ont besoin (décision Q44,
    `docs/journal/questions/questions_mainteneur.md`), et c'est pour ça que
    `azimuts_par_choix` accompagne toujours le vent : celui qui choisit sa
    direction doit savoir d'où il souffle, celui qui choisit selon le vent doit
    pouvoir vérifier ce qu'on lui propose avant de lancer le calcul.

    Aucun tracé, aucun appel BRouter, aucune séance : cette commande ne répond
    qu'à « d'où vient le vent, et qu'est-ce que chaque préférence donnerait ».
    """
    profil = contexte.profil
    jour, depart_heure = demande.jour, demande.depart
    dernier_jour = portee.dernier_jour_couvert(profil.meteo.horizon_jours, aujourdhui=date.today())
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
            profil.depart,
            depart_heure=depart_heure,
            jour=jour,
            modele=profil.meteo.modele,
            modele_repli=profil.meteo.second_avis,
        )
    return ResultatVent(question=question, jour=jour, depart=depart_heure)


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
    config: Profil,
    demande: Demande,
    distance_km: float,
    azimuts_vent: tuple[float, ...] = (),
    *,
    nb_candidates: int | None = None,
) -> tuple[list, list[Ecartee]]:
    """Les boucles candidates, et les directions refusées sur la distance.

    Le second élément n'est pas un détail d'implémentation : une direction
    écartée sans qu'on le dise laisserait le cycliste deviner pourquoi il voit
    moins de propositions que demandé. Il rejoint les `Ecartee` du placement chez l'appelant.

    Sans `--direction`, la commande ne choisit pas à la place du cycliste :
    elle réparti les candidates sur **tout le tour de l'horizon** et laisse le
    tableau montrer ce que chaque direction donne, terrain et pluie compris.
    C'est aussi ce qui rend `ourouler sortie --jour …` utilisable tel quel.

    `azimuts_vent` sont les azimuts qu'impose une réponse à la question
    d'orientation au vent. Ils **réduisent l'espace de recherche**
    au lieu de contraster après coup, ce qui est l'intérêt de poser la question
    avant. Ils sont **un ou deux** : « de travers » en ouvre deux opposés.

    `--direction` et `--vent` ne se contredisent pas ici : `_lire` refuse
    qu'on demande les deux. Quand `--direction` est là, elle est seule.

    `nb_candidates` prend le pas sur `demande.nb_candidates` quand il est
    fourni : c'est ce qui permet à `executer` de relancer cette recherche
    avec plus de candidates (paliers de relance) sans changer ce que le
    cycliste a demandé — `demande` elle-même n'est jamais modifiée.
    """
    nb = demande.nb_candidates if nb_candidates is None else nb_candidates
    if demande.azimut_deg is not None:
        repartition = [(demande.azimut_deg, nb)]
    elif azimuts_vent:
        parts = _parts(nb, len(azimuts_vent))
        # Une part nulle (une seule candidate pour deux azimuts) ne donne pas
        # lieu à un appel : `generer(nb=0)` ne rendrait rien en coûtant un
        # aller-retour.
        repartition = [(a, n) for a, n in zip(azimuts_vent, parts, strict=True) if n > 0]
    else:
        # Sans direction demandée, tout le tour de l'horizon, une candidate par
        # azimut.
        pas = 360.0 / nb
        repartition = [(i * pas, 1) for i in range(nb)]

    trouvees: list = []
    hors_bande: list[Ecartee] = []
    # **Un appel à `generer` par azimut**, et c'est ce qui garantit la
    # répartition. `generer(azimut, nb)` explore `azimut`, puis ±20°, ±40°… —
    # il élargit un secteur, il n'en ouvre jamais un second. Un seul appel pour
    # deux azimuts opposés entasserait donc toutes les candidates du premier
    # côté, et « de travers » ne proposerait qu'un des deux côtés.
    #
    # Le refus sur la distance est par azimut, et un azimut où le
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


def _paliers_candidates(nb_initial: int) -> list[int]:
    """Les nombres de candidates à essayer, dans l'ordre : `nb_initial` d'abord.

    `PALIERS_RELANCE_CANDIDATES` n'ajoute que les paliers strictement
    supérieurs au dernier déjà retenu : demander `--candidates 10` ne fait
    pas redescendre à 8, et sauter directement à 12 évite un essai qui
    n'aurait rien ajouté. Demander déjà `--candidates 20` épuise la liste
    dès le premier essai — la relance n'a rien de plus à proposer au-delà de
    ce que le cycliste a explicitement demandé.
    """
    paliers = [nb_initial]
    for palier in PALIERS_RELANCE_CANDIDATES:
        if palier > paliers[-1]:
            paliers.append(palier)
    return paliers


def _placer_toutes(
    candidates: list, seance: Seance, config: Profil, parametres: Parametres
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
    config: Profil,
    parametres: Parametres,
    demande: Demande,
    client_meteo: ClientOpenMeteo | None,
) -> list[tuple[object, Placement]]:
    """Rejoue le placement de chaque candidate retenue avec son champ de vent.

    La deuxième passe : le premier placement (sans vent) sert
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
        # Pas de météo demandée : pas de champ de vent, donc pas de
        # seconde passe. Le placement sans vent est ce qu'on sert, et il est
        # valable — c'est le premier placement.
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
                # `modele_repli`, lui, ne coûte rien tant que le
                # principal répond : il ne se déclenche que si celui-ci ne
                # couvre pas la fenêtre, exactement le cas qui priverait cette
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
    """Le comparateur de tri : note de placement d'abord, pluie
    cumulée ensuite — mais seulement quand les deux notes sont égales à
    `tolerance` (écart relatif) près.

    Le vent entrant dans la note, deux notes ne sont presque jamais égales au
    bit près, même pour deux boucles dont le terrain sous les blocs est
    identique : sans cette tolérance, le vent
    déciderait toujours et la pluie ne départagerait jamais. `tolerance` est une préférence
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


def _mesurer(
    retenues: list[tuple[object, Placement]],
    config: Profil,
    demande: Demande,
    client_meteo: ClientOpenMeteo | None,
    base_routes: BaseRoutes | None = None,
    *,
    dossier_cache: Path,
) -> tuple[list[Proposition], str | None]:
    """Coûts, routes connues et météo des candidates retenues.

    La vitesse qui date les heures de passage est celle **de la séance sur ce
    tracé** — distance placée divisée par durée placée — et non la vitesse
    moyenne de la configuration (décision Q8, `docs/journal/questions/questions_mainteneur.md`).

    `client_meteo` à `None` veut dire « on ne demande pas de météo » (jour
    au-delà de l'horizon) : les coûts et le placement sont mesurés comme
    d'habitude, la météo reste absente, et ce n'est **pas** une panne — il n'y
    a rien à signaler qui ne soit déjà dit par `meteo_absente`.
    """
    poids = lire_poids(dossier_cache / NOM_POIDS)
    base = base_routes if base_routes is not None else base_routes_existante(dossier_cache)
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
                    # Le repli : sans lui, une fenêtre hors de portée
                    # d'AROME (sortie à J+3, par exemple) perdrait toute la
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


def _vitesse(placement: Placement, config: Profil) -> float:
    """La vitesse moyenne de la séance sur ce tracé, en km/h."""
    if placement.duree_totale_s > 0 and placement.distance_totale_m > 0:
        vitesse = placement.distance_totale_m / 1000.0 / (placement.duree_totale_s / 3600.0)
        if math.isfinite(vitesse) and vitesse > 0:
            return vitesse
    return config.boucle.vitesse_moyenne_kmh


# --- écriture des fichiers -----------------------------------------------------


def _ecrire_gpx(
    trace: Trace, placement: Placement, seance: Seance, demande: Demande, dossier_cache: Path
) -> Path:
    """Le GPX du **parcours placé**, demi-tours compris — pas celui de la boucle.

    Mesuré : avec quatre demi-tours, le placement peut compter 72,7 km sur une
    boucle de 38,5, et le fichier de la boucle n'en porterait aucun. Ce qu'on
    écrit doit être ce qu'on va rouler, sans quoi le GPX ne correspond pas à la
    séance. La carte, elle, montre toujours la
    boucle : c'est son rôle de situer les blocs sur le tracé d'origine.
    """
    chemin = chemin_gpx_par_defaut(demande, dossier_cache)
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


def _gpx_propositions(seance: Seance, demande: Demande, selection: contraste.Selection) -> list[GpxPropose]:
    """Le GPX de **chaque** proposition retenue, en mémoire, rien sur le disque.

    Ces textes étaient déjà fabriqués, une fois, pour la page du jour, qui les
    embarque en base64 pour son téléchargement `blob:`. Les nommer ici les
    rend servables à qui appelle la commande (`recueil_gpx`) sans les calculer
    deux fois — et c'est ce qui permet à l'API de ne rien écrire tant que le
    cycliste n'a pas choisi.
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
    # `.blocs()` : la récupération d'un demi-tour porte aussi `demi_tour=True` ;
    # la compter en plus du bloc doublerait ce chiffre.
    demi_tours = sum(1 for e in placement.blocs() if e.demi_tour)
    if demi_tours == 0:
        combien = "sans demi-tour"
    elif demi_tours == 1:
        combien = "1 demi-tour"
    else:
        combien = f"{demi_tours} demi-tours"
    return f"{description_gpx(parcours)} · {combien}"


__all__ = [
    "ARRONDI_DISTANCE_KM",
    "NOTE_BLOC_BIEN_PLACE",
    "Demande",
    "DemandeVent",
    "GpxPropose",
    "Proposition",
    "ResultatSortie",
    "ResultatVent",
    "SansSeance",
    "executer",
    "executer_vent",
    "motif_aucune",
]

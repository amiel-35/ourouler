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
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ourouler.apprentissage.commande import NOM_BASE, NOM_POIDS
from ourouler.apprentissage.routes import BaseRoutes, lire_poids
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.commande import direction_en_azimut
from ourouler.boucle.couts import Couts
from ourouler.boucle.couts import evaluer as evaluer_couts
from ourouler.boucle.gpx import description as description_gpx
from ourouler.boucle.gpx import ecrire_gpx
from ourouler.boucle.meteo_trace import MeteoTrace
from ourouler.boucle.meteo_trace import evaluer as evaluer_meteo
from ourouler.boucle.trace import Trace
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.commande import heure_depart
from ourouler.meteo.openmeteo import ClientOpenMeteo
from ourouler.meteo.rapport import date_en_francais
from ourouler.physique.modele import Parametres, vitesse_regime
from ourouler.seance.commande import longueurs
from ourouler.seance.intervals import seance_du_jour
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT, Seance
from ourouler.seance.placement import CLE_MOTIF, Emplacement, Placement, placer, trace_parcourue
from ourouler.seance.tenue import Tenue
from ourouler.seance.tenue import conseiller as conseiller_tenue
from ourouler.seance.vent import ChampVent
from ourouler.sortie import contraste, orientation, vent_demande
from ourouler.sortie.carte import PropositionCarte, construire_page_jour

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


@dataclass(frozen=True)
class Ecartee:
    """Une candidate que le placement a refusée, et le motif qu'il a rangé dans `meta`."""

    azimut_deg: float | None
    distance_km: float
    motif: str


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
    client_meteo: ClientOpenMeteo | None = None,
    client_intervals: ClientIntervals | None = None,
) -> int:
    """Exécute `ourouler sortie`. 0 = succès (y compris « aucune séance ce jour-là »)."""
    demande = lire_options(args, config)

    seance = _seance(demande, config, client_intervals)
    if seance is None:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"jour": demande.jour.isoformat(), "seance": None, "candidates": []},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                f"Aucune séance vélo planifiée le {demande.jour.isoformat()} sur Intervals.icu — "
                "rien à placer. `ourouler boucle` propose une sortie libre."
            )
        return 0

    parametres, provenance = _parametres(config, demande.velo)
    distance_km, distance_source = _distance(demande, seance, parametres, config)

    # La question du vent se pose **avant** la recherche (contrat §3.3.4) :
    # c'est un appel Open-Meteo sur un point et une heure, donc le poste le
    # moins cher de la commande, et il tombe avant les appels BRouter, qui
    # sont le seul poste qui compte.
    client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
    question = vent_demande.interroger(
        client_meteo,
        config.depart,
        depart_heure=demande.depart,
        jour=demande.jour,
        modele=config.meteo.modele,
    )
    azimut_vent = question.azimut_pour(demande.vent)

    client_brouter = (
        client_brouter
        if client_brouter is not None
        else ClientBrouter(config.brouter, evitements=config.evitements)
    )
    candidates = _candidates(client_brouter, config, demande, distance_km, azimut_vent)

    retenues, ecartees = _placer_toutes(candidates, seance, config, parametres)
    if not retenues:
        raise ErreurUtilisateur(_motif_aucune(seance, ecartees, distance_km))

    retenues = _replacer_avec_vent(retenues, seance, config, parametres, demande, client_meteo)
    propositions, panne = _mesurer(retenues, config, demande, client_meteo)
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
    chemin_gpx = _ecrire_gpx(meilleure.trace, meilleure.placement, seance, demande)
    chemin_carte = _ecrire_page_jour(seance, demande, config, selection)

    if panne is not None:
        print(
            f"ourouler : météo indisponible ({panne}) — tableau sans les colonnes météo et "
            "sans tenue conseillée ; le placement, lui, reste valable",
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

    sortie = getattr(args, "sortie", None)
    carte = getattr(args, "carte", None)
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
    )
    for chemin, demande_explicite in (
        (chemin_gpx_par_defaut(demande), demande.sortie is not None),
        (chemin_carte_par_defaut(demande), demande.carte is not None),
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


def chemin_gpx_par_defaut(demande: Demande) -> Path:
    """`sortie_<AAAAMMJJ>.gpx` dans le dossier courant, ou le `--sortie` demandé."""
    return demande.sortie or Path(f"sortie_{demande.jour:%Y%m%d}.gpx")


def chemin_carte_par_defaut(demande: Demande) -> Path:
    """`sortie_<AAAAMMJJ>.html` dans le dossier courant, ou le `--carte` demandé."""
    return demande.carte or Path(f"sortie_{demande.jour:%Y%m%d}.html")


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
    if client is None:
        if not config.intervals.renseigne:
            raise ErreurUtilisateur(
                "sortie : Intervals.icu n'est pas renseigné — compléter [intervals] "
                "athlete_id et api_key dans la configuration"
            )
        client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    return seance_du_jour(
        client,
        demande.jour,
        ftp_w=config.cycliste.ftp_w,
        zones_puissance=ZONES_PUISSANCE_DEFAUT,
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
    from ourouler.physique.commande import chemin_calibration, parametres_du_velo, velo_demande

    choisi = velo_demande(config, velo)
    parametres, provenance = parametres_du_velo(config, choisi, chemin_calibration(config))
    return parametres, f"{provenance} ({choisi.nom})"


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
    if libres_s > 0:
        puissance = config.seance.puissance_endurance_pct * config.cycliste.ftp_w
        metres += vitesse_regime(puissance, 0.0, 0.0, parametres) * libres_s
    source = "estimée par le modèle sur le plat"
    if metres <= 0:
        # Aucune étape ne porte de puissance : on retombe sur la vitesse
        # moyenne de la configuration plutôt que de demander une boucle nulle.
        metres = config.boucle.vitesse_moyenne_kmh / 3.6 * seance.duree_s
        source = f"faute de puissances, à {config.boucle.vitesse_moyenne_kmh:g} km/h"
    arrondie = math.ceil(metres / 1000.0 / ARRONDI_DISTANCE_KM) * ARRONDI_DISTANCE_KM
    return float(arrondie), f"{source}, {metres / 1000:.1f} km arrondis au multiple de 5 supérieur"


def _candidates(
    client: ClientBrouter,
    config: Config,
    demande: Demande,
    distance_km: float,
    azimut_vent: float | None = None,
) -> list:
    """Les boucles candidates, dans la direction demandée ou tout autour.

    Sans `--direction`, la commande ne choisit pas à la place du cycliste :
    elle réparti les candidates sur **tout le tour de l'horizon** et laisse le
    tableau montrer ce que chaque direction donne, terrain et pluie compris.
    C'est aussi ce qui rend `ourouler sortie --jour …` utilisable tel quel, ce
    que le contrat de sprint demande.

    `azimut_vent` est l'azimut qu'impose une réponse à la question
    d'orientation au vent (lot L5.3). Il **réduit l'espace de recherche** au
    lieu de contraster après coup, ce qui est l'intérêt de poser la question
    avant. `--direction`, explicitement demandée, reste prioritaire : le
    cycliste qui écrit « au nord » veut aller au nord.
    """
    azimut = demande.azimut_deg if demande.azimut_deg is not None else azimut_vent
    if azimut is not None:
        trouvees = generer(
            client,
            config.depart,
            distance_km=distance_km,
            azimut_deg=azimut,
            nb=demande.nb_candidates,
            tolerance=config.boucle.tolerance_distance,
            profil=demande.profil,
            appels_max=appels_pour(demande.nb_candidates),
        )
    else:
        trouvees = []
        pas = 360.0 / demande.nb_candidates
        for i in range(demande.nb_candidates):
            trouvees += generer(
                client,
                config.depart,
                distance_km=distance_km,
                azimut_deg=i * pas,
                nb=1,
                tolerance=config.boucle.tolerance_distance,
                profil=demande.profil,
                appels_max=appels_pour(1),
            )
    if not trouvees:
        cible = demande.direction or "toutes directions"
        raise ErreurConnecteur(
            f"sortie : aucune boucle bornée trouvée ({cible}) pour {distance_km:g} km "
            f"(profil {demande.profil}) — essayer une autre direction, une autre distance "
            "ou un autre profil"
        )
    return trouvees


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
    client_meteo: ClientOpenMeteo,
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
                depart=demande.depart,
                vitesse_kmh=vitesse,
                modele=config.meteo.modele,
                # Pas de `second_avis` : lui seul sert au second modèle de
                # pluie, et ce premier appel ne sert qu'au vent du modèle
                # principal — l'économiser garde le coût à un appel de plus
                # par candidate, pas deux.
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
    client_meteo: ClientOpenMeteo,
) -> tuple[list[Proposition], str | None]:
    """Coûts, routes connues et météo des candidates retenues.

    La vitesse qui date les heures de passage est celle **de la séance sur ce
    tracé** — distance placée divisée par durée placée — et non plus la
    vitesse moyenne de la configuration : c'est ce que la question Q8
    promettait au sprint 4.
    """
    poids = lire_poids(config.cache.dossier / NOM_POIDS)
    base = _base_routes(config)
    propositions: list[Proposition] = []
    panne: str | None = None
    for candidate, placement in retenues:
        trace = candidate.trace
        vitesse = _vitesse(placement, config)
        meteo: MeteoTrace | None = None
        if panne is None:
            try:
                meteo = evaluer_meteo(
                    trace,
                    client_meteo,
                    depart=demande.depart,
                    vitesse_kmh=vitesse,
                    modele=config.meteo.modele,
                    second_avis=config.meteo.second_avis,
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


def _ecrire_gpx(trace: Trace, placement: Placement, seance: Seance, demande: Demande) -> Path:
    """Le GPX du **parcours placé**, demi-tours compris — pas celui de la boucle.

    Défaut mesuré le 22/04 : avec quatre demi-tours, le placement comptait
    72,7 km sur une boucle de 38,5, et le fichier envoyé au compteur n'en
    portait aucun. Ce qu'on écrit doit être ce qu'on va rouler, sans quoi le
    GPX ne correspond pas à la séance. La carte, elle, montre toujours la
    boucle : c'est son rôle de situer les blocs sur le tracé d'origine.
    """
    chemin = chemin_gpx_par_defaut(demande)
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


def _ecrire_page_jour(
    seance: Seance,
    demande: Demande,
    config: Config,
    selection: contraste.Selection,
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
    chemin = chemin_carte_par_defaut(demande)
    cartes_props = []
    for retenue in selection.retenues:
        p = retenue.proposition
        tenue_p = conseiller_tenue(p.meteo, config.tenue) if p.meteo is not None else None
        parcours = trace_parcourue(p.placement, p.trace)
        cartes_props.append(
            PropositionCarte(
                numero=p.numero,
                trace=p.trace,
                placement=p.placement,
                meteo=p.meteo,
                distinction=retenue.distinction or "la seule candidate",
                chiffres=_details_proposition(retenue),
                sous_titre=_sous_titre(p, demande, config),
                notes=_notes_carte(p, seance, tenue_p),
                gpx_nom=f"sortie_{demande.jour:%Y%m%d}_n{p.numero}.gpx",
                gpx_texte=ecrire_gpx(
                    parcours,
                    f"{seance.nom} — {seance.jour.isoformat()}",
                    desc=_description_parcours(parcours, p.placement),
                ),
            )
        )
    page = construire_page_jour(
        seance,
        cartes_props,
        titre=f"{seance.nom} — {date_en_francais(demande.depart)}",
        motif_deux_propositions=selection.motif_deux_propositions,
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

    titres = [t for t, mesure in COLONNES if mesure is None or mesure in presentes]
    cellules = [_cellules(p, presentes) for p in propositions]
    largeurs = [
        max([len(titre)] + [len(ligne[i]) for ligne in cellules]) for i, titre in enumerate(titres)
    ]
    marge = " " * (len(MARQUE_RETENUE) + 1)
    lignes.append(marge + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True)))
    for proposition, ligne in zip(propositions, cellules, strict=True):
        marque = f"{MARQUE_RETENUE} " if proposition is propositions[0] else marge
        lignes.append(marque + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))

    lignes += _notes_sous_tableau(propositions[0], presentes)
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
        azimut = question.azimut_pour(demande.vent)
        ou = f" — recherche dirigée vers {_azimut(azimut)}" if azimut is not None else ""
        if demande.azimut_deg is not None:
            ou = " — mais --direction, demandée explicitement, garde la main"
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
    lignes = [
        f"{len(selection.retenues)} proposition(s) qui diffèrent vraiment "
        "(et non les trois premières du tri) :"
    ]
    for retenue in selection.retenues:
        numero = retenue.proposition.numero
        phrase = retenue.distinction or "la seule candidate"
        lignes.append(f"    n° {numero} — {phrase}")
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
    lignes.append("")
    return lignes


def _ecart_seance(profil) -> str:
    """« (+18 min) » ou « (séance amputée de 12 min) », ou rien si elle tombe juste.

    Le signe compte et se dit : rentrer plus tard est normal — c'est le rôle
    du retour au calme —, rouler moins que la séance ne l'est pas. Les deux
    écarts sont du même côté de la valeur absolue dans l'axe de contraste, ils
    ne doivent pas l'être à l'affichage.
    """
    depassement = getattr(profil, "depassement_s", None)
    if depassement is None or abs(depassement) < 60:
        return ""
    if depassement > 0:
        return f" (+{depassement / 60:.0f} min)"
    return f" (⚠ séance amputée de {-depassement / 60:.0f} min)"


def _details_proposition(retenue) -> str:
    """Les mesures qui portent la phrase, dans les unités du cycliste."""
    profil = retenue.profil
    morceaux = [_duree_courte(profil.duree_s) + _ecart_seance(profil)]
    if profil.densite_marqueurs_km is not None:
        morceaux.append(f"{_fr(profil.densite_marqueurs_km, 1)} feux/stops/passages au km")
    else:
        morceaux.append("marqueurs inconnus")
    morceaux.append(
        "aucun demi-tour" if profil.demi_tours == 0 else f"{profil.demi_tours} demi-tour(s)"
    )
    if profil.part_trafic is not None:
        morceaux.append(f"{profil.part_trafic * 100:.0f} % de grands axes")
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


def _entete(
    propositions: list[Proposition], contexte: _Contexte, presentes: set[str]
) -> list[str]:
    seance, demande, config = contexte.seance, contexte.demande, contexte.config
    # Trois cas et non deux : depuis le lot L5.3, une réponse à la question
    # d'orientation au vent dirige la recherche elle aussi. Dire « dans toutes
    # les directions » alors qu'on a cherché au sud-ouest serait faux.
    azimut_vent = (
        contexte.question_vent.azimut_pour(demande.vent)
        if contexte.question_vent is not None
        else None
    )
    if demande.azimut_deg is not None:
        direction = f"vers {demande.direction} ({demande.azimut_deg:.0f}°)"
    elif azimut_vent is not None:
        direction = (
            f"vers {_azimut(azimut_vent)} ({azimut_vent:.0f}°), direction imposée par "
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
    if contexte.provenance_modele.startswith("défaut"):
        lignes.append(
            "⚠ aucun vélo calibré : les vitesses, donc la position des blocs, reposent sur un "
            "CdA et un Crr par défaut (`ourouler calibrer`)."
        )
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
        lignes.append(
            f"{len(contexte.ecartees)} candidate(s) écartée(s) : la séance n'y tenait pas —"
        )
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


def _cellules(proposition: Proposition, presentes: set[str]) -> list[str]:
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
        _duree_courte(proposition.placement.duree_totale_s),
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
            "velo": demande.velo,
        },
        "modele_physique": contexte.provenance_modele,
        "seuil_bloc_bien_place": NOTE_BLOC_BIEN_PLACE,
        # Écart relatif de note en dessous duquel la pluie départage plutôt que
        # le vent (préférence du cycliste, `config.seance.tolerance_egalite`) :
        # publié pour que le rang des candidates dans `candidates` s'explique
        # sans relire la configuration.
        "tolerance_egalite": contexte.config.seance.tolerance_egalite,
        "gpx": str(contexte.gpx) if contexte.gpx is not None else None,
        "carte": str(contexte.carte) if contexte.carte is not None else None,
        "ecartees": [
            {
                "azimut_deg": e.azimut_deg,
                "distance_km": round(e.distance_km, 3),
                "motif": e.motif,
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
        "candidates": [_candidate_json(p) for p in propositions],
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
        "azimut_recherche_deg": question.azimut_pour(contexte.demande.vent),
        "choix": list(orientation.CHOIX),
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


def _candidate_json(proposition: Proposition) -> dict:
    trace, placement, meteo = proposition.trace, proposition.placement, proposition.meteo
    return {
        "numero": proposition.numero,
        "retenue": proposition.numero == 1,
        "nom": trace.nom,
        "distance_km": round(trace.distance_m / 1000.0, 3),
        "denivele_m": trace.denivele_m,
        "azimut_deg": proposition.azimut_deg,
        "ecart_relatif": proposition.ecart_relatif,
        "part_connue": proposition.part_connue,
        "vitesse_kmh": round(proposition.vitesse_kmh, 2),
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
        },
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


def _liste(elements) -> str:
    return ", ".join(elements) if elements else "rien de particulier"


def _minutes(secondes: float) -> str:
    return f"{secondes / 60:+.0f} min"


def _duree_courte(secondes: float) -> str:
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _duree_longue(secondes: float) -> str:
    minutes = int(round(secondes / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d}"


def _fr(valeur: float, decimales: int) -> str:
    return f"{valeur:.{decimales}f}".replace(".", ",")


__all__ = [
    "ARRONDI_DISTANCE_KM",
    "NOTE_BLOC_BIEN_PLACE",
    "Demande",
    "Proposition",
    "executer",
    "lire_options",
    "rendre_json",
    "rendre_texte",
]

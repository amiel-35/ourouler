"""Sous-commande `ourouler sortie` : la séance du jour, posée sur une boucle.

L'enchaînement est celui du contrat du sprint 4 §4 :

1. la **séance du jour** est lue chez Intervals.icu (lot L4.1) ; s'il n'y en a
   pas, on le dit et on sort en 0 — ce n'est pas une erreur ;
2. des **boucles candidates** sont demandées au moteur (lot L2.3), de la
   longueur qu'il faut pour la séance ;
3. chacune reçoit le **placement** des blocs (lot L4.3). Celles où la séance
   ne tient pas sont écartées, et le tableau dit combien et pourquoi ;
4. sur les retenues seulement : **coûts** du tracé (L2.4), **météo** à l'heure
   de passage (L2.5) et **tenue** (L4.3) ;
5. tri par **note de placement d'abord**, puis par pluie cumulée ;
6. la meilleure part en **GPX** et en **carte HTML** (`sortie.carte`).

L'ordre du tri est celui du contrat et il n'est pas anodin : la pluie se
contourne en partant une heure plus tard, un bloc de seuil dans un village ne
se contourne pas. La météo départage, elle ne décide pas.

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
from ourouler.physique.modele import Parametres
from ourouler.seance.commande import longueurs
from ourouler.seance.intervals import seance_du_jour
from ourouler.seance.modele import ZONES_PUISSANCE_DEFAUT, Seance
from ourouler.seance.placement import CLE_MOTIF, Placement, placer
from ourouler.seance.tenue import Tenue
from ourouler.seance.tenue import conseiller as conseiller_tenue
from ourouler.sortie.carte import construire as construire_carte

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
        return sum(1 for e in self.placement.emplacements if e.note.note < NOTE_BLOC_BIEN_PLACE)

    @property
    def demi_tours(self) -> int:
        return sum(1 for e in self.placement.emplacements if e.demi_tour)

    @property
    def tri(self) -> tuple[float, float]:
        """Note de placement d'abord, pluie cumulée ensuite (contrat §4)."""
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

    client_brouter = (
        client_brouter
        if client_brouter is not None
        else ClientBrouter(config.brouter, evitements=config.evitements)
    )
    candidates = _candidates(client_brouter, config, demande, distance_km)

    retenues, ecartees = _placer_toutes(candidates, seance, config, parametres)
    if not retenues:
        raise ErreurUtilisateur(_motif_aucune(seance, ecartees, distance_km))

    client_meteo = client_meteo if client_meteo is not None else ClientOpenMeteo()
    propositions, panne = _mesurer(retenues, config, demande, client_meteo)
    propositions.sort(key=lambda p: p.tri)
    for numero, proposition in enumerate(propositions, start=1):
        proposition.numero = numero

    meilleure = propositions[0]
    tenue = (
        conseiller_tenue(meilleure.meteo, config.tenue) if meilleure.meteo is not None else None
    )
    chemin_gpx = _ecrire_gpx(meilleure.trace, seance, demande)
    chemin_carte = _ecrire_carte(meilleure, seance, demande, config, tenue)

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
    metres = sum(m.longueur_m for m in mesures if m.longueur_m is not None)
    source = "estimée par le modèle sur le plat"
    if metres <= 0:
        # Aucune étape ne porte de puissance : on retombe sur la vitesse
        # moyenne de la configuration plutôt que de demander une boucle nulle.
        metres = config.boucle.vitesse_moyenne_kmh / 3.6 * seance.duree_s
        source = f"faute de puissances, à {config.boucle.vitesse_moyenne_kmh:g} km/h"
    arrondie = math.ceil(metres / 1000.0 / ARRONDI_DISTANCE_KM) * ARRONDI_DISTANCE_KM
    return float(arrondie), f"{source}, {metres / 1000:.1f} km arrondis au multiple de 5 supérieur"


def _candidates(
    client: ClientBrouter, config: Config, demande: Demande, distance_km: float
) -> list:
    """Les boucles candidates, dans la direction demandée ou tout autour.

    Sans `--direction`, la commande ne choisit pas à la place du cycliste :
    elle réparti les candidates sur **tout le tour de l'horizon** et laisse le
    tableau montrer ce que chaque direction donne, terrain et pluie compris.
    C'est aussi ce qui rend `ourouler sortie --jour …` utilisable tel quel, ce
    que le contrat de sprint demande.
    """
    if demande.azimut_deg is not None:
        trouvees = generer(
            client,
            config.depart,
            distance_km=distance_km,
            azimut_deg=demande.azimut_deg,
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
    for candidate in candidates:
        trace = candidate.trace
        placement = placer(
            seance,
            trace,
            parametres,
            elasticite=elasticite,
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


def _ecrire_gpx(trace: Trace, seance: Seance, demande: Demande) -> Path:
    chemin = chemin_gpx_par_defaut(demande)
    nom = f"{seance.nom} — {seance.jour.isoformat()}"
    try:
        chemin.write_text(ecrire_gpx(trace, nom), encoding="utf-8")
    except OSError as e:
        raise ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})") from e
    return chemin


def _ecrire_carte(
    proposition: Proposition,
    seance: Seance,
    demande: Demande,
    config: Config,
    tenue: Tenue | None,
) -> Path:
    chemin = chemin_carte_par_defaut(demande)
    page = construire_carte(
        proposition.trace,
        seance,
        proposition.placement,
        titre=f"{seance.nom} — {date_en_francais(demande.depart)}",
        sous_titre=_sous_titre(proposition, demande, config),
        notes=_notes_carte(proposition, seance, tenue),
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
        f"{proposition.blocs_bien_places}/{len(proposition.placement.emplacements)} blocs bien placés",
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
    for avertissement in proposition.placement.avertissements:
        notes.append("⚠ " + avertissement)
    return notes


# --- rendu texte ---------------------------------------------------------------

#: Colonnes du tableau. Le second membre nomme la mesure dont la colonne
#: dépend : sans cette mesure, la colonne **disparaît** au lieu d'afficher une
#: colonne de tirets. `None` = toujours affichée.
COLONNES = (
    ("n°", None),
    ("distance", None),
    ("D+", None),
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

    lignes.append("")
    lignes += _seance_placee(propositions[0], contexte)
    lignes.append("")
    lignes += _tenue_lignes(contexte)
    if contexte.gpx is not None:
        lignes.append(f"{MARQUE_RETENUE} GPX   : {contexte.gpx}")
    if contexte.carte is not None:
        lignes.append(f"{MARQUE_RETENUE} Carte : {contexte.carte}")
    return "\n".join(lignes)


def _entete(
    propositions: list[Proposition], contexte: _Contexte, presentes: set[str]
) -> list[str]:
    seance, demande, config = contexte.seance, contexte.demande, contexte.config
    direction = (
        f"vers {demande.direction} ({demande.azimut_deg:.0f}°)"
        if demande.azimut_deg is not None
        else "dans toutes les directions (aucune --direction demandée)"
    )
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
    if seance.meta.get("puissance_approximee"):
        lignes.append(
            "⚠ puissances approximées : la séance est prescrite en zones de fréquence cardiaque."
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
        "plus bas = mieux. La note additionne le terrain sous les blocs et la pénalité "
        "des étapes élastiques sorties de leur fenêtre — une séance qu'on ne tient pas "
        "coûte plus cher qu'un mauvais couloir."
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
    return presentes


def _cellules(proposition: Proposition, presentes: set[str]) -> list[str]:
    trace, couts, meteo = proposition.trace, proposition.couts, proposition.meteo
    partiels = bool(trace.meta.get("couts_partiels"))
    cellules = [
        str(proposition.numero),
        f"{_fr(trace.distance_m / 1000, 1)} km",
        f"{trace.denivele_m:.0f} m" if trace.denivele_m is not None else ABSENT,
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
        f"{proposition.blocs_bien_places}/{len(proposition.placement.emplacements)}",
    ]
    if "demi_tours" in presentes:
        cellules.append(str(proposition.demi_tours) if proposition.demi_tours else ABSENT)
    return cellules


def _seance_placee(proposition: Proposition, contexte: _Contexte) -> list[str]:
    """La séance posée sur la candidate retenue, bloc par bloc, motifs en clair.

    Seuls les blocs portent une position et une note : `seance.placement` ne
    mémorise l'emplacement que des étapes contraignantes (contrat §3), et
    inventer un kilomètre pour les autres serait inventer une mesure. Le
    décalage de la Z2 d'ouverture et la durée totale disent, eux, ce qui
    arrive aux extrémités.
    """
    placement = proposition.placement
    seance = contexte.seance
    note = _fr(placement.note_totale, 2)
    if placement.penalite_seance > 0:
        note += (
            f" = terrain {_fr(placement.note_terrain, 2)} + séance non tenue "
            f"{_fr(placement.penalite_seance, 2)}"
        )
    lignes = [
        f"Séance placée sur la candidate n° {proposition.numero} (note {note}) :",
        f"    Z2 d'ouverture allongée de {_minutes(placement.decalage_z2_s)} — c'est elle qui "
        "fait coulisser les blocs le long du tracé.",
    ]
    for numero, emplacement in enumerate(placement.emplacements, start=1):
        etape = seance.etapes[emplacement.etape_idx]
        fin = emplacement.debut_m + emplacement.longueur_m
        lignes.append(
            f"    bloc {numero} — km {_fr(emplacement.debut_m / 1000, 1)} → {_fr(fin / 1000, 1)} "
            f"({_fr(emplacement.longueur_m / 1000, 1)} km, {_duree_courte(etape.duree_s)}, "
            f"{_puissance(etape)}) : note {_fr(emplacement.note.note, 2)}"
            + (" — demi-tour" if emplacement.demi_tour else "")
        )
        if emplacement.note.note >= NOTE_BLOC_BIEN_PLACE:
            for motif in emplacement.note.motifs or ["aucun motif détaillé"]:
                lignes.append(f"        • {motif}")
    lignes.append(
        f"    Retour au calme : {_duree_longue(placement.duree_totale_s)} et "
        f"{_fr(placement.distance_totale_m / 1000, 1)} km au total — il absorbe ce qui reste."
    )
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
        "candidates": [_candidate_json(p) for p in propositions],
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
            "blocs_bien_places": proposition.blocs_bien_places,
            "demi_tours": proposition.demi_tours,
            "avertissements": placement.avertissements,
            "emplacements": [
                {
                    "bloc": numero,
                    "etape_idx": e.etape_idx,
                    "debut_m": round(e.debut_m, 1),
                    "longueur_m": round(e.longueur_m, 1),
                    "demi_tour": e.demi_tour,
                    "note": round(e.note.note, 4),
                    "motifs": e.note.motifs,
                    "pente_moyenne": round(e.note.pente_moyenne, 5),
                    "pente_max": round(e.note.pente_max, 5),
                    "carrefours": e.note.carrefours,
                    "km_batis": round(e.note.km_batis, 3),
                    "descente_m": round(e.note.descente_m, 1),
                    "montee_m": round(e.note.montee_m, 1),
                }
                for numero, e in enumerate(placement.emplacements, start=1)
            ],
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

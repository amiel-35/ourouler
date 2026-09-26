"""Pluie et vent **le long du tracé, à l'heure de passage**.

La différence avec `ourouler.meteo` : là on demandait « où va-t-il pleuvoir
autour de moi ? » sur une couronne de points, ici on suit un parcours déjà
tracé et on interroge chaque tronçon à l'heure où le cycliste y sera. Une
averse qui traverse la région à 10 h ne concerne que les kilomètres 25 à 35.

Un **seul** appel Open-Meteo pour tous les échantillons (le service accepte
plusieurs coordonnées par requête) ; un second appel seulement si un second
avis est demandé, un troisième seulement si le modèle principal ne couvre
pas toute la fenêtre et qu'un modèle de repli existe (Q19, prolongé au repli
**partiel** — voir `evaluer`). Les valeurs horaires sont interpolées
linéairement entre les deux heures encadrantes — angulairement pour la
direction du vent, sans quoi 350° et 10° donneraient 180°, c'est-à-dire le
sud au lieu du nord.

L'heure de passage de chaque échantillon vient d'un `Horaire`
(`boucle.horaire.construire_horaire`) : `depart + distance / vitesse`, plus
la somme des pauses déclarées avant ce point du tracé — un brevet ou une
sortie avec un arrêt déjeuner ne se roule pas à vitesse constante d'une
traite.

La règle du vent relatif (secteur de ±45°) n'est pas réécrite ici : c'est
`ourouler.meteo.rapport.vent_relatif`, appliquée au **cap local du tracé**
au lieu de l'azimut d'une direction de couronne.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ourouler.boucle.horaire import Horaire
from ourouler.meteo.rapport import (
    CONFIANCE_ACCORD,
    CONFIANCE_DESACCORD,
    CONFIANCE_INCONNUE,
    VENT_DOS,
    VENT_FACE,
    confiance,
    vent_relatif,
)
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurHorsDomaine, ErreurUtilisateur
from ourouler.noyau.meteo import PrevisionHeure, PrevisionPoint
from ourouler.noyau.ports import SourcePrevisions
from ourouler.noyau.trace import PointTrace, Trace, cap_deg, distance_m

#: Au-delà, on compte l'échantillon comme « sous la pluie » (seuil du contrat).
SEUIL_PLUIE_MM_H = 0.2

#: Vent moyen (à 10 m, en km/h) en dessous duquel on considère qu'il n'y a
#: rien à sentir, donc rien à montrer ni à demander.
#:
#: Raison, pas une valeur ronde choisie au hasard : 8 km/h est le haut de la
#: force 1 de l'échelle de Beaufort (« très légère brise, à peine perceptible
#: sur un visage ») et le bas de la force 2 (« légère brise, sentie sur le
#: visage ») — le seuil météorologique usuel entre « rien à sentir » et « on
#: sent quelque chose ». Le vent médian du mainteneur est de 14 km/h (bien
#: au-dessus) mais descend à 2,5 km/h.
#:
#: **Une seule constante pour trois usages**, et c'est voulu (lot L5.3) : les
#: flèches de la carte (`fleches_vent` ci-dessous, que dessinent la page HTML
#: du sprint 5 et le front) se dessinent exactement quand la question de
#: l'orientation au vent se pose (`sortie.vent_demande`). Si le vent ne mérite
#: pas d'être montré, il ne mérite pas qu'on demande son orientation.
#:
#: Elle vivait dans `seance.vent`, qui la réexporte pour ses appelants
#: historiques. Elle est descendue ici le 17/09/2026 parce que `boucle` en a
#: besoin pour sérialiser les flèches, et que `boucle` ne peut pas importer
#: `seance` : partout ailleurs, c'est `seance` qui importe `boucle`.
SEUIL_VENT_SENSIBLE_KMH = 8.0

#: Marge demandée après l'heure d'arrivée : la dernière heure encadrante doit
#: exister, sinon le dernier échantillon ne serait pas interpolable.
MARGE_APRES_ARRIVEE_H = 1

#: Pas d'échantillonnage par défaut, en mètres.
PAS_DEFAUT_M = 5000.0


@dataclass
class Echantillon:
    """Un point du tracé, à l'heure où le cycliste y passe."""

    dist_m: float
    t: datetime
    lat: float
    lon: float
    cap_deg: float
    pluie_mm: float | None
    vent_kmh: float | None
    vent_relatif: str | None
    ressenti_c: float | None
    vent_depuis_deg: float | None = None
    """Direction d'où vient le vent, interpolée. `vent_relatif` la résume en
    trois secteurs, ce qui suffit à la lecture mais pas au modèle physique :
    celui-ci a besoin de la composante de face en m/s, donc de l'angle."""
    rafales_kmh: float | None = None
    """Rafale interpolée **linéairement**, comme `vent_kmh` — c'est une
    vitesse, pas une direction : l'interpoler angulairement n'aurait pas de
    sens. Portée jusqu'ici pour l'affichage (flèches de vent de la carte) ;
    le modèle physique ne s'en sert pas, seul `vent_kmh` l'alimente."""
    modele: str | None = None
    """Le modèle qui a renseigné **cet** échantillon : `None` si ni le
    modèle principal ni son repli (Q19) ne couvrent l'heure de passage ici.

    Une sortie longue dépasse parfois l'horizon du modèle principal en
    cours de route (une nuit de sommeil, par exemple) sans que la fenêtre
    entière soit hors domaine : les premiers échantillons ont une vraie
    réponse d'AROME, les derniers basculent sur le repli. Avant ce champ,
    `MeteoTrace.modele_utilise` ne portait qu'un seul nom pour tout le
    tracé — un mensonge par mise en page pour la moitié qui n'avait pas
    cette réponse-là (règle absolue 5)."""
    au_dela_prevision: bool = False
    """Vrai quand l'heure de passage ici est **au-delà de la prévision** :
    après `limite` (l'horizon que le produit accepte, voir `evaluer`), ou
    hors de la série qu'aucun modèle n'a rendue. Toutes les valeurs sont
    alors absentes, et l'écran doit le dire plutôt que de montrer un vide
    (L9.8 : un 600 km parti le dernier jour couvert arrive le lendemain)."""


@dataclass
class MeteoTrace:
    """Ce que le tracé promet comme météo, échantillon par échantillon et en résumé."""

    echantillons: list[Echantillon]
    pluie_cumulee_mm: float
    minutes_pluie: float
    part_vent_face: float  # fraction dans [0, 1] des échantillons au vent connu
    part_vent_dos: float
    ressenti_min_c: float | None
    confiance: str
    n_vent_connu: int = 0
    """Dénominateur des deux parts de vent : nombre d'échantillons dont le
    vent est connu. Sans lui, « vent face 100 % » ne distingue pas 12
    échantillons sur 12 d'un seul sur 12, les onze autres étant hors de
    l'horizon de prévision."""
    modele_utilise: str = ""
    """Le modèle qui a effectivement répondu — celui demandé, ou le repli
    (Q19) quand celui-ci ne couvrait pas la fenêtre. Toujours renseigné
    quand la météo a pu être évaluée, pour que l'affichage nomme le modèle
    plutôt que de se taire dessus."""
    repli: bool = False
    """Vrai dès qu'au moins un échantillon n'est pas renseigné par
    `modele_utilise` : soit que le modèle principal ne couvrait pas la
    fenêtre du tout (`bascule_dist_m` reste `None`, tout le tracé est sur
    le repli), soit qu'il ne la couvrait qu'en partie (`bascule_dist_m`
    donne alors le premier kilomètre concerné). Deux modèles qui divergent
    s'affichent (règle absolue 5) ; ici un seul répond par échantillon, et
    c'est encore une divergence à dire."""
    bascule_dist_m: float | None = None
    """Le premier kilomètre (en mètres) où un échantillon bascule sur le
    modèle de repli plutôt que `modele_utilise` — `None` sauf **repli
    partiel** : sans repli du tout, ou avec un repli total dès le départ
    (`repli` seul le dit déjà dans ce cas), il reste `None`. Sert la phrase
    d'écran « au-delà du kilomètre X, la prévision vient de … »."""


def evaluer(
    trace: Trace,
    client: SourcePrevisions,
    *,
    horaire: Horaire,
    modele: str,
    second_avis: str | None = None,
    modele_repli: str | None = None,
    pas_m: float = PAS_DEFAUT_M,
    limite: datetime | None = None,
) -> MeteoTrace:
    """La météo le long de `trace`, échantillonnée tous les `pas_m`.

    `horaire` répond « à quelle heure suis-je au kilomètre X » — construit
    par l'appelant (`boucle.horaire.construire_horaire`, dans `cli.py` ou
    `boucle.commande`), jamais lu ici (règle absolue 2). Sans pause déclarée,
    c'est exactement `depart + distance / vitesse`, le calcul d'avant ce lot.
    `horaire(0.0)` sert de départ pour la fenêtre demandée à Open-Meteo :
    aucune pause ne peut être strictement avant le kilomètre zéro, donc il
    vaut toujours le départ tel quel.

    `modele_repli` est le **repli** (Q19) : quand `modele` ne couvre pas la
    fenêtre demandée du tout (`ErreurHorsDomaine` — AROME publie à 67 h, une
    sortie à J+3 en demande davantage), on retente une fois avec
    `modele_repli` comme modèle **principal** de remplacement, pas comme
    second avis. Sans lui (`None`, le défaut), le comportement est inchangé :
    l'échec remonte tel quel.

    **Repli partiel.** Un tracé dont la fin déborde la portée horaire du
    modèle principal sans que le départ en soit hors domaine (une nuit de
    sommeil, par exemple) ne fait pas échouer l'appel : Open-Meteo rend une
    série qui s'arrête en route, et les échantillons au-delà restent absents
    — sauf si `modele_repli` est fourni, auquel cas il est tenté une seule
    fois (mémoïsé), et sert les seuls échantillons que le principal n'a pas
    couverts. `Echantillon.modele` dit, échantillon par échantillon, lequel a
    répondu ; `MeteoTrace.bascule_dist_m` donne le premier kilomètre
    concerné — pour que l'affichage le nomme plutôt que de se taire dessus
    (règle absolue 5, deux qualités de prévision ne s'affichent jamais de la
    même façon). Le second avis (`second_avis`) n'est jamais redemandé au
    modèle qui sert déjà de repli : le comparer à lui-même n'apprendrait rien.

    `limite` (L9.8) : l'instant au-delà duquel **aucune** valeur n'est
    présentée comme une prévision, même si Open-Meteo en rendait une — la fin
    du dernier jour couvert (`meteo.portee`). Les échantillons après elle
    sont vides et marqués `au_dela_prevision`, et la fenêtre demandée
    s'arrête là. `None` (le défaut) : comportement d'avant, inchangé.
    """
    # Ces deux refus tombent **avant** le premier appel à Open-Meteo : une
    # entrée absurde ne consomme pas de quota et ne fait pas attendre.
    if not trace.points:
        raise ErreurUtilisateur("tracé sans point : il n'y a rien à évaluer le long du parcours")
    if not _strictement_positif(pas_m):
        raise ErreurUtilisateur(
            f"pas_m = {pas_m} : un pas d'échantillonnage strictement positif est attendu"
        )

    depart_tz = horaire(0.0)
    distances = _distances_cumulees(trace.points)
    indices = _indices_echantillons(distances, pas_m)

    bases = [
        (
            distances[i],
            horaire(distances[i]),
            trace.points[i],
            _cap_local(trace.points, i),
        )
        for i in indices
    ]
    coordonnees = [(p.lat, p.lon) for _, _, p, _ in bases]

    arrivee = bases[-1][1] if limite is None else min(bases[-1][1], limite)
    debut_heure, horizon_h = _fenetre(depart_tz, max(arrivee, depart_tz))
    previsions, modele_principal, repli_total = _previsions_avec_repli(
        client, coordonnees, modele, modele_repli, debut_heure, horizon_h
    )

    previsions_repli: list[PrevisionPoint] | None = None
    bascule_dist_m: float | None = None
    echantillons = []
    for i, ((dist, t, point, cap), prevision) in enumerate(zip(bases, previsions, strict=True)):
        hors_limite = limite is not None and t > limite
        valeurs = _Valeurs() if hors_limite else _interpoler(prevision.heures, t)
        modele_echantillon: str | None = None if _valeurs_vides(valeurs) else modele_principal
        if (
            not hors_limite
            and modele_echantillon is None
            and not repli_total
            and modele_repli
            and modele_repli != modele_principal
        ):
            # Tenté une seule fois pour tout l'appel, la première fois qu'un
            # échantillon en a besoin — pas un appel par échantillon absent.
            if previsions_repli is None:
                previsions_repli = _tenter_repli_partiel(
                    client, coordonnees, modele_repli, debut_heure, horizon_h
                )
            if previsions_repli is not None:
                valeurs_repli = _interpoler(previsions_repli[i].heures, t)
                if not _valeurs_vides(valeurs_repli):
                    valeurs = valeurs_repli
                    modele_echantillon = modele_repli
                    if bascule_dist_m is None:
                        bascule_dist_m = dist
        echantillons.append(
            Echantillon(
                dist_m=dist,
                t=t,
                lat=point.lat,
                lon=point.lon,
                cap_deg=cap if cap is not None else 0.0,
                pluie_mm=valeurs.pluie_mm,
                vent_kmh=valeurs.vent_kmh,
                # Sans cap local (tracé réduit à un point), il n'y a pas de
                # « à l'aller » : la valeur est absente plutôt que fausse —
                # même raison que pour le point « ici » d'une couronne.
                vent_relatif=(
                    vent_relatif(cap, valeurs.vent_depuis_deg) if cap is not None else None
                ),
                ressenti_c=valeurs.ressenti_c,
                vent_depuis_deg=valeurs.vent_depuis_deg,
                rafales_kmh=valeurs.rafales_kmh,
                modele=modele_echantillon,
                au_dela_prevision=hors_limite or modele_echantillon is None,
            )
        )

    # Pas de comparaison d'un modèle avec lui-même : si le repli total a déjà
    # pris la place du principal, redemander `second_avis` quand il lui est
    # égal ne comparerait rien à rien, seulement le coût d'un appel de plus.
    # (Le repli partiel ne change rien ici : `modele_principal` reste le
    # modèle demandé, indépendant de ce qui a servi tel ou tel échantillon.)
    avis_pour_comparaison = second_avis if second_avis != modele_principal else None
    pluies_second_avis = _second_avis(
        client,
        coordonnees,
        [t for _, t, _, _ in bases],
        [e.au_dela_prevision for e in echantillons],
        debut_heure,
        horizon_h,
        avis_pour_comparaison,
    )
    resultat = _resumer(echantillons, pluies_second_avis)
    resultat.modele_utilise = modele_principal
    resultat.repli = repli_total or bascule_dist_m is not None
    resultat.bascule_dist_m = bascule_dist_m
    return resultat


def _previsions_avec_repli(
    client: SourcePrevisions,
    coordonnees: Sequence[tuple[float, float]],
    modele: str,
    modele_repli: str | None,
    debut_heure: datetime,
    horizon_h: int,
) -> tuple[list[PrevisionPoint], str, bool]:
    """Les prévisions du modèle principal, ou du repli (Q19) s'il ne couvre pas la fenêtre.

    Ne retente **que** sur `ErreurHorsDomaine` : une panne réseau, un JSON
    illisible ou un refus du service restent des échecs sur lesquels
    retenter avec un autre modèle ne changerait rien et masquerait la vraie
    cause.
    """
    try:
        previsions = client.previsions(
            coordonnees, modele=modele, debut=debut_heure, horizon_h=horizon_h
        )
        return previsions, modele, False
    except ErreurHorsDomaine:
        if not modele_repli or modele_repli == modele:
            raise
        previsions = client.previsions(
            coordonnees, modele=modele_repli, debut=debut_heure, horizon_h=horizon_h
        )
        return previsions, modele_repli, True


def _tenter_repli_partiel(
    client: SourcePrevisions,
    coordonnees: Sequence[tuple[float, float]],
    modele_repli: str,
    debut_heure: datetime,
    horizon_h: int,
) -> list[PrevisionPoint] | None:
    """Le repli sur toute la fenêtre, pour les échantillons que le principal n'a pas couverts.

    Contrairement à `_previsions_avec_repli` (bascule **totale**, sur
    `ErreurHorsDomaine`), celle-ci sert un repli **partiel** : le principal a
    répondu, seule la fin de la fenêtre lui échappe. Tolérante à l'échec —
    même raison que `_second_avis` : un repli indisponible ne fait perdre que
    les échantillons qui en avaient besoin, pas toute l'évaluation.
    """
    try:
        return client.previsions(
            coordonnees, modele=modele_repli, debut=debut_heure, horizon_h=horizon_h
        )
    except ErreurConnecteur:
        return None


# --- ce qu'on montre du vent -------------------------------------------------


def fleches_vent(meteo: MeteoTrace | None) -> list[dict]:
    """Un point de flèche par échantillon assez venté, prêt à dessiner.

    **La règle est celle de la page HTML du sprint 5** (`rendu.carte`), qui
    l'appliquait la première et qui appelle maintenant cette fonction : rien
    n'est réinventé ici, le code a seulement été remonté d'un cran pour que le
    JSON puisse le servir au front. Un écran qui dessine le vent et une page
    qui le dessine doivent le dessiner au même seuil, sans quoi le même
    parcours montre deux vents différents selon la porte par laquelle on le
    regarde.

    `meteo.echantillons` couvre le tracé complet (comme le tracé gris), pas
    seulement le parcours réellement roulé : un échantillon au-delà d'un
    demi-tour, par exemple, peut donc porter une flèche. C'est le même choix
    que pour le tracé — situer la météo sur le terrain — et pas une
    inadvertance.

    Écarté si le vent ou sa direction manque (`None` : `vent_face_ms` de
    `seance.vent` traite pareillement ce cas comme « inconnu », jamais
    « nul ») — sans direction connue, aucune rotation n'aurait de sens, et en
    inventer une (par exemple 0°) affirmerait une direction sans preuve
    (règle absolue 5). Écarté aussi sous `SEUIL_VENT_SENSIBLE_KMH` : ce
    vent-là ne se sent pas sur le visage, et le dessiner serait du bruit.
    """
    if meteo is None:
        return []
    fleches = []
    for e in meteo.echantillons:
        if e.vent_kmh is None or e.vent_depuis_deg is None:
            continue
        if e.vent_kmh < SEUIL_VENT_SENSIBLE_KMH:
            continue
        fleches.append(
            {
                "pt": [round(e.lat, 6), round(e.lon, 6)],
                # Direction d'où vient le vent (convention météo, 0 = nord,
                # sens horaire) : la flèche s'oriente dessus telle quelle,
                # comme une girouette qui pointe vers d'où souffle le vent.
                "depuis_deg": round(e.vent_depuis_deg, 1),
                "vent_kmh": round(e.vent_kmh),
                "rafale_kmh": round(e.rafales_kmh) if e.rafales_kmh is not None else None,
                # « face »/« dos »/« travers », déjà tranché par
                # `meteo.rapport.vent_relatif` au cap local, dans `evaluer`
                # ci-dessus. Jamais recalculé ici.
                "relatif": e.vent_relatif,
            }
        )
    return fleches


def vent_par_position(meteo: MeteoTrace | None) -> list[dict]:
    """Le vent le long du **tracé entier**, pour colorer le tracé lui-même.

    `ChampVent` (`seance.vent`) le dit déjà dans sa docstring : le vent est
    « interrogeable à n'importe quelle position ». `fleches_vent` ci-dessus
    n'en montre qu'une fraction — filtrée au seuil où le vent se sent, pour
    ne pas encombrer la carte de flèches. Colorer le tracé demande l'inverse :
    savoir, à CHAQUE portion, si elle se fait de face, dans le dos, de
    travers ou sans direction connue — même sous le seuil, faute de quoi la
    coloration laisserait des trous muets aux portions de vent faible. C'est
    exactement le calcul déjà fait pour `part_vent_face`/`part_vent_dos`
    (`_resumer` ci-dessous) : aucun filtre de sensibilité là non plus, sur le
    même argument (« un échantillon sans vent ne doit pas compter pour du
    travers », mais un vent faible de face reste de face). Ce n'est donc pas
    un second seuil inventé pour l'occasion.

    Rend une position par échantillon (`dist_m` suffit : le front a déjà la
    géométrie complète du tracé dans `trace.profil`, `dist_m` cumulée comme
    ici, et sait y découper une portion — voir `Proposition.portion` côté
    front). `relatif` vaut `None` quand `meteo.rapport.vent_relatif` n'a pas
    pu trancher (direction ou cap local absents) : le front garde alors cette
    portion en encre, jamais en couleur (règle absolue 5 — l'ignorance ne se
    montre pas comme une valeur).
    """
    if meteo is None:
        return []
    return [{"dist_m": round(e.dist_m), "relatif": e.vent_relatif} for e in meteo.echantillons]


# --- échantillonnage ---------------------------------------------------------


def _strictement_positif(valeur: float) -> bool:
    """Vrai pour un nombre fini et > 0. NaN et l'infini sont des refus, pas des vitesses."""
    return math.isfinite(valeur) and valeur > 0


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    `PointTrace.dist_m` est la source normale. Un tracé importé qui aurait
    laissé ce champ à zéro donnerait un seul échantillon au kilomètre zéro,
    en silence : on le rattrape plutôt que de rendre une météo de départ
    pour tout le parcours.
    """
    if len(points) >= 2 and points[-1].dist_m > 0:
        return [p.dist_m for p in points]
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _indices_echantillons(distances: Sequence[float], pas_m: float) -> list[int]:
    """Indices des points à échantillonner : tous les `pas_m`, et le dernier point."""
    total = distances[-1]
    cibles = []
    cible = 0.0
    while cible < total:
        cibles.append(cible)
        cible += pas_m
    cibles.append(total)

    indices: list[int] = []
    j = 0
    for cible in cibles:
        while j + 1 < len(distances) and distances[j] < cible:
            j += 1
        if not indices or indices[-1] != j:
            indices.append(j)
    return indices


def _cap_local(points: Sequence[PointTrace], i: int) -> float | None:
    """Le cap du tracé au point `i` : vers le suivant, ou depuis le précédent au bout.

    `None` si aucun autre point distinct n'existe (tracé réduit à un point).
    """
    for j in range(i + 1, len(points)):
        if distance_m(points[i], points[j]) > 0:
            return cap_deg(points[i], points[j])
    for j in range(i - 1, -1, -1):
        if distance_m(points[j], points[i]) > 0:
            return cap_deg(points[j], points[i])
    return None


def _fenetre(depart: datetime, arrivee: datetime) -> tuple[datetime, int]:
    """(première heure demandée, nombre d'heures) couvrant départ → arrivée + 1 h.

    Le début est ramené à l'heure pleine précédente : sans cela, un départ à
    8 h 30 n'aurait pas d'heure encadrante inférieure et le premier
    échantillon serait vide.
    """
    debut = depart.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    fin = arrivee.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=MARGE_APRES_ARRIVEE_H
    )
    heures = int((fin - debut).total_seconds() // 3600) + 1
    return (debut, max(1, heures))


# --- interpolation entre les deux heures encadrantes -------------------------


@dataclass(frozen=True)
class _Valeurs:
    """Ce qu'on retient d'une heure interpolée. Tout peut manquer."""

    pluie_mm: float | None = None
    vent_kmh: float | None = None
    vent_depuis_deg: float | None = None
    ressenti_c: float | None = None
    rafales_kmh: float | None = None


def _valeurs_vides(v: _Valeurs) -> bool:
    """Vrai quand rien n'a été trouvé pour cet échantillon — pas juste un champ isolé.

    Sert à décider si le repli partiel doit être tenté : une pluie manquante
    seule (`precipitation` absente à cette heure précise) n'est pas un signe
    que le modèle ne couvre plus la fenêtre, c'est le comportement normal
    d'une variable ponctuellement absente. Rien du tout, en revanche — ni
    pluie, ni vent, ni ressenti — c'est `_encadrantes` qui n'a trouvé aucune
    heure du tout pour `t` (hors de la série rendue par le modèle)."""
    return v == _Valeurs()


def _interpoler(heures: Sequence[PrevisionHeure], t: datetime) -> _Valeurs:
    """Les valeurs à l'instant `t`, interpolées entre les deux heures encadrantes.

    Hors de la série (tracé plus long que l'horizon du modèle, départ avant
    la première heure fournie) : tout est absent. On ne prolonge pas la
    dernière heure connue — ce serait affirmer sans mesure.
    """
    encadrantes = _encadrantes(heures, t)
    if encadrantes is None:
        return _Valeurs()
    avant, apres = encadrantes
    duree = (apres.t - avant.t).total_seconds()
    f = (t - avant.t).total_seconds() / duree if duree > 0 else 0.0
    return _Valeurs(
        pluie_mm=_lineaire(avant.pluie_mm, apres.pluie_mm, f),
        vent_kmh=_lineaire(avant.vent_kmh, apres.vent_kmh, f),
        vent_depuis_deg=interpoler_angle(avant.vent_depuis_deg, apres.vent_depuis_deg, f),
        ressenti_c=_lineaire(avant.ressenti_c, apres.ressenti_c, f),
        rafales_kmh=_lineaire(avant.rafales_kmh, apres.rafales_kmh, f),
    )


def _encadrantes(
    heures: Sequence[PrevisionHeure], t: datetime
) -> tuple[PrevisionHeure, PrevisionHeure] | None:
    """Les deux heures qui encadrent `t`, ou `None` si `t` est hors de la série.

    Une heure pile est rendue seule, des deux côtés : sinon un échantillon
    tombant exactement sur 09 h serait interpolé depuis le couple (08 h, 09 h)
    et une valeur absente à 08 h effacerait la valeur connue de 09 h.
    """
    if not heures or t < heures[0].t or t > heures[-1].t:
        return None
    for heure in heures:
        if heure.t == t:
            return (heure, heure)
    for avant, apres in zip(heures[:-1], heures[1:], strict=True):
        if avant.t < t < apres.t:
            return (avant, apres)
    return None  # série non triée : on préfère ne rien affirmer


def _lineaire(a: float | None, b: float | None, f: float) -> float | None:
    if a is None or b is None:
        return None
    return a + (b - a) * f


def interpoler_angle(a: float | None, b: float | None, f: float) -> float | None:
    """Interpolation d'un angle par ses composantes : 350° et 10° donnent 0°, pas 180°.

    Publique parce que `seance.vent` interpole le même angle entre deux
    échantillons distants de 5 km : une seconde version aurait tôt fait de
    diverger de celle-ci, et c'est exactement la faute qu'elle évite.
    """
    if a is None or b is None:
        return None
    ra, rb = math.radians(a), math.radians(b)
    x = math.cos(ra) + (math.cos(rb) - math.cos(ra)) * f
    y = math.sin(ra) + (math.sin(rb) - math.sin(ra)) * f
    if x == 0.0 and y == 0.0:  # deux directions opposées à mi-chemin : indécidable
        return a
    return math.degrees(math.atan2(y, x)) % 360.0


# --- second avis -------------------------------------------------------------


def _second_avis(
    client: SourcePrevisions,
    coordonnees: Sequence[tuple[float, float]],
    instants: Sequence[datetime],
    au_dela: Sequence[bool],
    debut_heure: datetime,
    horizon_h: int,
    modele: str | None,
) -> list[float | None] | None:
    """La pluie d'un second modèle aux mêmes points et aux mêmes instants.

    `None` si aucun second avis n'est demandé **ou** si le second modèle ne
    répond pas (hors domaine, service en panne) : un second avis manquant
    n'est pas une raison de faire échouer l'évaluation, il rend seulement la
    confiance « inconnu ». Les deux modèles ne sont jamais moyennés.
    """
    if not modele:
        return None
    try:
        previsions = client.previsions(
            coordonnees, modele=modele, debut=debut_heure, horizon_h=horizon_h
        )
    except ErreurConnecteur:
        return None
    # Au-delà de la prévision, le second avis se tait aussi : il ne doit pas
    # fabriquer un « accord » sur un échantillon que le principal n'a pas.
    return [
        None if hors else _interpoler(prevision.heures, t).pluie_mm
        for prevision, t, hors in zip(previsions, instants, au_dela, strict=True)
    ]


# --- résumé ------------------------------------------------------------------


def _resumer(
    echantillons: Sequence[Echantillon], pluies_second_avis: Sequence[float | None] | None
) -> MeteoTrace:
    """Les agrégats : cumul de pluie, minutes sous la pluie, parts de vent, confiance."""
    durees_h = _durees_h(echantillons)

    pluie_cumulee = sum(
        e.pluie_mm * d for e, d in zip(echantillons, durees_h, strict=True) if e.pluie_mm is not None
    )
    minutes_pluie = sum(
        d * 60.0
        for e, d in zip(echantillons, durees_h, strict=True)
        if e.pluie_mm is not None and e.pluie_mm >= SEUIL_PLUIE_MM_H
    )

    # Parts de vent sur le **nombre** d'échantillons au vent connu : la
    # vitesse étant constante, ils sont régulièrement espacés en temps comme
    # en distance, et un échantillon sans vent ne doit pas compter pour du
    # travers.
    connus = [e.vent_relatif for e in echantillons if e.vent_relatif is not None]
    part_face = connus.count(VENT_FACE) / len(connus) if connus else 0.0
    part_dos = connus.count(VENT_DOS) / len(connus) if connus else 0.0

    ressentis = [e.ressenti_c for e in echantillons if e.ressenti_c is not None]

    return MeteoTrace(
        echantillons=list(echantillons),
        pluie_cumulee_mm=pluie_cumulee,
        minutes_pluie=minutes_pluie,
        part_vent_face=part_face,
        part_vent_dos=part_dos,
        n_vent_connu=len(connus),
        ressenti_min_c=min(ressentis) if ressentis else None,
        confiance=_confiance_globale(echantillons, pluies_second_avis),
    )


def _durees_h(echantillons: Sequence[Echantillon]) -> list[float]:
    """La durée que chaque échantillon représente, en heures (règle du point milieu).

    Un échantillon vaut du milieu de l'intervalle qui le précède au milieu de
    celui qui le suit ; la somme fait exactement la durée du parcours. Un
    échantillon unique représente une durée nulle : on ne sait pas combien de
    temps dure un tracé réduit à un point.
    """
    n = len(echantillons)
    if n < 2:
        return [0.0] * n
    instants = [e.t for e in echantillons]
    bornes = [instants[0]]
    for avant, apres in zip(instants[:-1], instants[1:], strict=True):
        bornes.append(avant + (apres - avant) / 2)
    bornes.append(instants[-1])
    return [
        (fin - debut).total_seconds() / 3600.0
        for debut, fin in zip(bornes[:-1], bornes[1:], strict=True)
    ]


def _confiance_globale(
    echantillons: Sequence[Echantillon], pluies_second_avis: Sequence[float | None] | None
) -> str:
    """« desaccord » dès qu'un échantillon divise les deux modèles, « inconnu » si rien n'est comparable."""
    if pluies_second_avis is None:
        return CONFIANCE_INCONNUE
    niveaux = [
        confiance(e.pluie_mm, seconde)
        for e, seconde in zip(echantillons, pluies_second_avis, strict=True)
    ]
    if CONFIANCE_DESACCORD in niveaux:
        return CONFIANCE_DESACCORD
    if CONFIANCE_ACCORD in niveaux:
        return CONFIANCE_ACCORD
    return CONFIANCE_INCONNUE

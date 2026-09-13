"""Où tombent les blocs de la séance sur un tracé donné.

La séance est une prescription : les durées des blocs et de **toutes** les
récupérations ne se touchent pas (décision du mainteneur, 13/09). Le seul
levier de placement est le **décalage de la Z2 d'ouverture** : l'allonger
repousse toute la partie contrainte plus loin sur le tracé, et c'est ainsi
qu'on fait coulisser les blocs jusqu'à un bon couloir. La Z2 de fin, elle,
**absorbe** : elle ne place rien, elle ramène à la maison une fois le dernier
bloc terminé, et sa durée est recalculée, jamais balayée.

Mécanique. La vitesse de chaque étape vient du modèle physique à la
puissance cible et à la pente locale ; on avance donc le long du tracé de
proche en proche, par pas de `PAS_M` mètres, exactement comme
`physique.modele.simuler` — qu'on ne peut pas appeler ici, parce que la
puissance dépend de la position qu'on est justement en train de calculer.
Le vent n'entre pas dans ce calcul : le placement se fait sur la géométrie
du tracé, la météo est jugée ailleurs (`boucle.meteo_trace`).

Pour chaque bloc précédé d'une récupération et d'un autre bloc, on essaie en
plus la variante **demi-tour**, dans la forme exacte donnée par le
mainteneur :

    bloc (aller) → moitié de la récup → demi-tour → moitié de la récup
    → bloc (sens inverse)

On revient donc exactement au bout du segment, et le segment n'a pas besoin
d'être plus long que le bloc. Trois conditions, et seulement trois :
plat ou faux-plat, de la route au-delà du segment, demi-tour faisable. La
récupération elle-même n'est **jamais** évaluée : ni village, ni carrefour,
ni revêtement — elle absorbe le point dur, c'est son rôle.

La note de la configuration est la **moyenne des notes de couloir pondérée
par la durée de chaque bloc** :

    note_totale = Σ (note_i × duree_i) / Σ duree_i

Décision du superviseur du 13/09 (Q12) : un bloc de 20 min pèse trente fois
une activation de 40 s. Voir `_note_ponderee` pour le motif.

Une note, jamais un filtre : chaque emplacement porte sa note et ses motifs,
on garde la configuration la moins mauvaise et on dit ce qui cloche. `None`
n'est rendu que si la séance ne tient pas du tout sur le tracé ; le motif est
alors rangé dans `trace.meta[CLE_MOTIF]`, comme `boucle.couts` range ses
propres réserves dans `meta`.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ourouler.activites.modele import moyenne_glissante
from ourouler.boucle.trace import PointTrace, Trace, distance_m
from ourouler.physique.modele import (
    FENETRE_ALTITUDE,
    PAS_M,
    V_MAX_DESCENTE_KMH,
    V_MIN_MS,
    Parametres,
    vitesse_regime,
)
from ourouler.seance.modele import Etape, Seance
from ourouler.seance.terrain import NoteBloc, demi_tour_faisable, evaluer_couloir, route_au_dela

#: Clé de `Trace.meta` où le motif d'échec est rangé quand `placer` rend `None`.
CLE_MOTIF = "placement_motif"

TYPE_BLOC = "bloc"
TYPE_RECUP = "recuperation"

#: Puissance retenue pour une étape sans fourchette de puissance (une récup
#: décrite en fréquence cardiaque, une étape libre). Ce n'est pas une mesure :
#: le placement le dit dans ses avertissements.
PUISSANCE_SANS_CIBLE_W = 150.0

#: Pente moyenne maximale d'un couloir pour qu'un demi-tour y ait un sens
#: (1,5 %). « Un tronçon marche souvent dans les deux sens sur du plat, mais
#: en côte » non : à l'envers c'est une descente, et ce n'est plus la même
#: figure. Même seuil que la descente pénalisée par `seance.terrain`.
PENTE_DEMI_TOUR_MAX = 0.015

#: Garde-fou : nombre maximal de décalages essayés pour un `pas_s` minuscule.
MAX_DECALAGES = 2000


@dataclass
class Emplacement:
    """Où tombe un bloc, et ce que vaut le terrain à cet endroit."""

    etape_idx: int
    debut_m: float
    longueur_m: float
    demi_tour: bool  # le bloc réutilise le segment précédent en sens inverse
    note: NoteBloc


@dataclass
class Placement:
    """Une séance posée sur un tracé : le décalage retenu et ce qu'il donne."""

    decalage_z2_s: float  # allongement (ou raccourcissement) de la Z2 d'ouverture
    emplacements: list[Emplacement]
    note_totale: float
    duree_totale_s: float
    distance_totale_m: float
    avertissements: list[str] = field(default_factory=list)


def placer(
    seance: Seance,
    trace: Trace,
    p: Parametres,
    *,
    elasticite: tuple[float, float] = (-0.05, 0.20),
    pas_s: float = 60.0,
    penalite_demi_tour: float = 1.0,
) -> Placement | None:
    """La meilleure façon de poser `seance` sur `trace`, ou `None` si elle n'y tient pas.

    `elasticite` est une fraction de la durée de la Z2 d'ouverture (−5 % à
    +20 % par défaut) ; le décalage est balayé par pas de `pas_s` secondes,
    bornes comprises. La meilleure configuration est celle dont la somme des
    notes de blocs est la plus basse ; à égalité, celle qui touche le moins à
    la séance.
    """
    if not seance.etapes:
        return _echec(trace, "séance sans étape : il n'y a rien à placer")
    if len(trace.points) < 2:
        return _echec(trace, "tracé de moins de deux points : il n'y a rien à parcourir")

    terrain = _Terrain(trace, p)
    if not (math.isfinite(terrain.total) and terrain.total > 0):
        return _echec(trace, "tracé de longueur nulle : il n'y a rien à parcourir")

    idx_ouverture, idx_fermeture = _extremites(seance.etapes)
    prealables: list[str] = []
    if idx_ouverture is None:
        prealables.append(
            "aucune Z2 d'ouverture élastique : la séance est posée telle quelle, "
            "sans levier de placement"
        )
    if idx_fermeture is None:
        prealables.append(
            "aucun retour au calme élastique : rien n'absorbe la distance restante "
            "après le dernier bloc"
        )

    duree_ouverture = seance.etapes[idx_ouverture].duree_s if idx_ouverture is not None else 0.0
    decalages = _decalages(duree_ouverture, elasticite, pas_s)

    meilleur: Placement | None = None
    motifs: list[str] = []
    for decalage in decalages:
        essai = _essayer(
            seance,
            trace,
            terrain,
            decalage_s=decalage,
            idx_ouverture=idx_ouverture,
            idx_fermeture=idx_fermeture,
            elasticite=elasticite,
            penalite_demi_tour=penalite_demi_tour,
        )
        if isinstance(essai, str):
            motifs.append(essai)
            continue
        if meilleur is None or _classement(essai) < _classement(meilleur):
            meilleur = essai

    if meilleur is None:
        return _echec(trace, _motif_global(motifs, decalages, terrain, seance))

    meilleur.avertissements = list(dict.fromkeys(prealables + meilleur.avertissements))
    trace.meta.pop(CLE_MOTIF, None)
    return meilleur


def _classement(placement: Placement) -> tuple[float, float]:
    """Note d'abord ; à égalité, le décalage qui touche le moins à la séance."""
    return (placement.note_totale, abs(placement.decalage_z2_s))


def _echec(trace: Trace, motif: str) -> None:
    """Range le motif dans `trace.meta` et rend `None` : l'appelant a de quoi l'afficher."""
    trace.meta[CLE_MOTIF] = motif
    return None


def _motif_global(
    motifs: Sequence[str], decalages: Sequence[float], terrain: _Terrain, seance: Seance
) -> str:
    """Un motif d'échec exploitable : ce qui a été essayé, et ce qui a coincé."""
    essaye = (
        f"décalages essayés : de {_minutes(decalages[0])} à {_minutes(decalages[-1])} "
        f"({len(decalages)} valeurs)"
    )
    detail = motifs[0] if motifs else "aucun décalage n'a pu être déroulé"
    return (
        f"la séance « {seance.nom} » ne tient pas sur ce tracé de "
        f"{terrain.total / 1000:.1f} km — {detail} ({essaye})"
    )


def _extremites(etapes: Sequence[Etape]) -> tuple[int | None, int | None]:
    """Indices de la Z2 d'ouverture et de la Z2 de fermeture, si elles sont élastiques.

    Une séance réduite à une seule étape élastique n'a pas de levier : cette
    étape est la fermeture, celle qui absorbe.
    """
    fermeture = len(etapes) - 1 if etapes[-1].elastique else None
    ouverture = 0 if etapes[0].elastique else None
    if ouverture is not None and ouverture == fermeture:
        ouverture = None
    return ouverture, fermeture


def _decalages(duree_ouverture_s: float, elasticite: tuple[float, float], pas_s: float) -> list[float]:
    """Les décalages à essayer, en secondes, bornes comprises.

    Les bornes sont toujours essayées, même si `pas_s` est plus grand que la
    marge : sinon un pas mal choisi ferait manquer le seul décalage possible.
    Zéro l'est aussi dès qu'il tombe dans la fenêtre — ne pas toucher à la
    séance est une option comme une autre.
    """
    bas, haut = min(elasticite), max(elasticite)
    borne_bas, borne_haut = duree_ouverture_s * bas, duree_ouverture_s * haut
    if not (math.isfinite(borne_bas) and math.isfinite(borne_haut)):
        return [0.0]
    valeurs = {borne_bas, borne_haut}
    if borne_bas <= 0.0 <= borne_haut:
        valeurs.add(0.0)
    if math.isfinite(pas_s) and pas_s > 0:
        valeur, n = borne_bas, 0
        while valeur < borne_haut and n < MAX_DECALAGES:
            valeurs.add(valeur)
            valeur += pas_s
            n += 1
    return sorted(valeurs)


# --- déroulé d'un décalage ---------------------------------------------------


@dataclass
class _Etat:
    """Où l'on en est le long du tracé pendant qu'on déroule la séance."""

    position_m: float = 0.0
    sens: int = 1  # +1 dans le sens du tracé, −1 après un demi-tour
    distance_m: float = 0.0
    duree_s: float = 0.0


def _essayer(
    seance: Seance,
    trace: Trace,
    terrain: _Terrain,
    *,
    decalage_s: float,
    idx_ouverture: int | None,
    idx_fermeture: int | None,
    elasticite: tuple[float, float],
    penalite_demi_tour: float,
) -> Placement | str:
    """Déroule la séance pour un décalage donné : un `Placement`, ou le motif qui a coincé."""
    etapes = seance.etapes
    fin = idx_fermeture if idx_fermeture is not None else len(etapes)
    etat = _Etat()
    emplacements: list[Emplacement] = []
    avertissements: list[str] = []

    i = 0
    while i < fin:
        etape = etapes[i]
        duree = etape.duree_s + (decalage_s if i == idx_ouverture else 0.0)
        if duree < 0:
            return (
                f"un décalage de {_minutes(decalage_s)} raccourcit la Z2 d'ouverture "
                "au-delà de sa durée"
            )
        puissance = _puissance(etape, avertissements, i)
        suivante = etapes[i + 1] if i + 1 < fin else None

        if (
            etape.type == TYPE_RECUP
            and suivante is not None
            and suivante.type == TYPE_BLOC
            and emplacements
        ):
            emplacement = _recup_puis_bloc(
                trace,
                terrain,
                etat,
                recup=etape,
                recup_puissance=puissance,
                bloc=suivante,
                bloc_idx=i + 1,
                bloc_puissance=_puissance(suivante, avertissements, i + 1),
                penalite_demi_tour=penalite_demi_tour,
            )
            if isinstance(emplacement, str):
                return emplacement
            emplacements.append(emplacement)
            i += 2
            continue

        if etape.type == TYPE_BLOC:
            emplacement = _bloc_droit(trace, terrain, etat, etape, i, puissance, duree)
            if isinstance(emplacement, str):
                return emplacement
            emplacements.append(emplacement)
            i += 1
            continue

        if not _rouler(terrain, etat, duree, puissance):
            return _plus_de_route(etat, terrain, etape, i)
        i += 1

    if idx_fermeture is not None:
        motif = _fermer(terrain, etat, etapes[idx_fermeture], idx_fermeture, elasticite, avertissements)
        if motif is not None:
            return motif
    elif etat.sens > 0 and terrain.total - etat.position_m > 0:
        avertissements.append(
            f"il reste {(terrain.total - etat.position_m) / 1000:.1f} km de tracé "
            "après la dernière étape"
        )
    if etat.sens < 0:
        avertissements.append(
            "la séance se termine en sens inverse : le retour se fait sur le tracé à l'envers"
        )

    return Placement(
        decalage_z2_s=decalage_s,
        emplacements=emplacements,
        note_totale=_note_ponderee(emplacements, etapes),
        duree_totale_s=etat.duree_s,
        distance_totale_m=etat.distance_m,
        avertissements=list(dict.fromkeys(avertissements)),
    )


def _note_ponderee(emplacements: Sequence[Emplacement], etapes: Sequence[Etape]) -> float:
    """Moyenne des notes de couloir, pondérée par la durée de chaque bloc.

        note_totale = Σ (note_i × duree_i) / Σ duree_i

    Décision du superviseur du 13/09 (Q12). Les quatre activations de 40 s à
    375 W de la séance du 22/04 sont des blocs au sens de la séance, et c'est
    juste. Mais chercher un couloir propre pour 40 s n'a pas de sens, et la
    validation rétrospective montre que les blocs courts ne se discriminent
    pas : leur note est du bruit. Plutôt qu'un seuil arbitraire qui les
    exclurait, on pondère — un bloc de 20 min pèse trente fois un bloc de
    40 s, et c'est le rapport de leurs durées, pas une constante de plus.

    Le résultat reste une note en kilomètres équivalents, comparable d'une
    séance à l'autre, ce qu'une somme brute n'était pas : elle grandissait
    avec le nombre de blocs. Le choix du décalage de la Z2 d'ouverture, lui,
    est inchangé — les durées des blocs ne dépendent pas du décalage, donc
    diviser par leur somme ne peut pas changer quel décalage gagne.

    Un jeu de blocs sans durée positive n'a pas de pondération possible : la
    moyenne simple prend le relais plutôt que d'effacer les pénalités.
    """
    if not emplacements:
        return 0.0
    poids = [max(0.0, float(etapes[e.etape_idx].duree_s)) for e in emplacements]
    total = sum(poids)
    if total <= 0.0:
        return sum(e.note.note for e in emplacements) / len(emplacements)
    return sum(e.note.note * p for e, p in zip(emplacements, poids, strict=True)) / total


def _rouler(terrain: _Terrain, etat: _Etat, duree_s: float, puissance_w: float) -> bool:
    """Avance l'état de `duree_s` à `puissance_w`. Faux si l'on sort du tracé."""
    arrivee = terrain.avancer(etat.position_m, etat.sens, duree_s, puissance_w)
    if arrivee is None:
        return False
    etat.distance_m += abs(arrivee - etat.position_m)
    etat.position_m = arrivee
    etat.duree_s += duree_s
    return True


def _bloc_droit(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    bloc: Etape,
    bloc_idx: int,
    puissance_w: float,
    duree_s: float,
) -> Emplacement | str:
    """Le bloc tel quel, dans le sens de marche, à partir de la position courante."""
    depart = etat.position_m
    if not _rouler(terrain, etat, duree_s, puissance_w):
        return _plus_de_route(etat, terrain, bloc, bloc_idx)
    debut, longueur = _couloir(depart, etat.position_m)
    return Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=False,
        note=evaluer_couloir(trace, debut, longueur),
    )


def _recup_puis_bloc(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    *,
    recup: Etape,
    recup_puissance: float,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
    penalite_demi_tour: float,
) -> Emplacement | str:
    """La paire (récupération, bloc) : variante droite contre variante demi-tour.

    Les deux se jouent depuis le même état ; on garde la moins mal notée et
    on applique alors seulement son effet sur la position. La récupération
    n'est jamais évaluée : village, carrefour et revêtement y sont sans
    importance, elle est là pour absorber le point dur.
    """
    droite = _variante_droite(trace, terrain, etat, recup, recup_puissance, bloc, bloc_idx, bloc_puissance)
    demi = _variante_demi_tour(
        trace,
        terrain,
        etat,
        recup,
        recup_puissance,
        bloc,
        bloc_idx,
        bloc_puissance,
        penalite_demi_tour,
    )
    candidates = [c for c in (droite, demi) if c is not None]
    if not candidates:
        return _plus_de_route(etat, terrain, bloc, bloc_idx)
    emplacement, etat_apres = min(candidates, key=lambda c: c[0].note.note)
    etat.position_m, etat.sens = etat_apres.position_m, etat_apres.sens
    etat.distance_m, etat.duree_s = etat_apres.distance_m, etat_apres.duree_s
    return emplacement


def _variante_droite(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    recup: Etape,
    recup_puissance: float,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
) -> tuple[Emplacement, _Etat] | None:
    """Récup puis bloc, tout droit : le cas normal, sans pénalité."""
    essai = replace(etat)
    if not _rouler(terrain, essai, recup.duree_s, recup_puissance):
        return None
    depart = essai.position_m
    if not _rouler(terrain, essai, bloc.duree_s, bloc_puissance):
        return None
    debut, longueur = _couloir(depart, essai.position_m)
    emplacement = Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=False,
        note=evaluer_couloir(trace, debut, longueur),
    )
    return emplacement, essai


def _variante_demi_tour(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    recup: Etape,
    recup_puissance: float,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
    penalite_demi_tour: float,
) -> tuple[Emplacement, _Etat] | None:
    """Le bloc repris en sens inverse, la récup coupée en deux autour du demi-tour.

    `None` dès qu'une des trois conditions manque. Le besoin de route au-delà
    du segment est estimé comme le mainteneur le fait de tête — une demi-récup
    à la vitesse du moment, « 4 min à 25 km/h ≈ 800 m » — et c'est
    `route_au_dela` qui dit si cette route existe, y compris sur une boucle
    fermée où le tracé continue au-delà de sa fin.
    """
    moitie = recup.duree_s / 2.0
    if moitie <= 0:
        return None
    besoin_m = terrain.vitesse(recup_puissance, terrain.pente_a(etat.position_m) * etat.sens) * moitie
    if not _route_au_dela(trace, terrain, etat.position_m, besoin_m, etat.sens):
        return None
    if not demi_tour_faisable(trace, terrain.borner(etat.position_m + etat.sens * besoin_m)):
        return None

    # Figure symétrique : les deux moitiés de récup se compensent, on repart
    # exactement du bout du segment, dans l'autre sens.
    essai = replace(etat)
    essai.sens = -etat.sens
    essai.distance_m += 2 * besoin_m
    essai.duree_s += recup.duree_s
    depart = essai.position_m
    if not _rouler(terrain, essai, bloc.duree_s, bloc_puissance):
        return None
    debut, longueur = _couloir(depart, essai.position_m)
    note = evaluer_couloir(trace, debut, longueur)
    if abs(note.pente_moyenne) > PENTE_DEMI_TOUR_MAX:
        return None  # en côte, le retour est une descente : ce n'est plus la même figure
    note = replace(
        note,
        note=note.note + penalite_demi_tour,
        motifs=[*note.motifs, "demi-tour : le segment du bloc précédent, repris en sens inverse"],
    )
    emplacement = Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=True,
        note=note,
    )
    return emplacement, essai


def _route_au_dela(
    trace: Trace, terrain: _Terrain, position_m: float, besoin_m: float, sens: int
) -> bool:
    """`terrain.route_au_dela`, appliqué dans le sens de marche.

    La fonction du contrat ne connaît que le sens du tracé ; après un premier
    demi-tour on roule à l'envers, et « au-delà » veut alors dire « avant la
    position ». La question reste la même : reste-t-il `besoin_m` de route
    devant, ou bien la boucle continue-t-elle ?
    """
    if sens > 0:
        return route_au_dela(trace, position_m, besoin_m)
    return position_m >= besoin_m or trace.bornee()


def _fermer(
    terrain: _Terrain,
    etat: _Etat,
    etape: Etape,
    idx: int,
    elasticite: tuple[float, float],
    avertissements: list[str],
) -> str | None:
    """La Z2 de fin absorbe la distance restante. Elle ne place rien, elle referme.

    Sa durée est donc **recalculée** : c'est le temps qu'il faut pour rentrer
    depuis là où le dernier bloc s'est terminé. On le dit quand elle sort de
    la fenêtre d'élasticité prévue — on ne refuse pas pour autant : une note,
    jamais un filtre.
    """
    reste = terrain.total - etat.position_m if etat.sens > 0 else etat.position_m
    if reste < 0:
        reste = 0.0
    puissance = _puissance(etape, avertissements, idx)
    duree = terrain.duree_pour(etat.position_m, etat.sens, reste, puissance)
    if duree is None:
        return "le retour au calme ne peut pas refermer le tracé depuis le dernier bloc"
    etat.duree_s += duree
    etat.distance_m += reste
    etat.position_m = terrain.total if etat.sens > 0 else 0.0
    if etape.duree_s > 0:
        ecart = duree / etape.duree_s - 1.0
        if not min(elasticite) <= ecart <= max(elasticite):
            avertissements.append(
                f"retour au calme : {duree / 60:.0f} min pour rentrer au lieu des "
                f"{etape.duree_s / 60:.0f} min prescrites ({ecart:+.0%})"
            )
    return None


def _couloir(a: float, b: float) -> tuple[float, float]:
    """(début, longueur) du couloir entre deux positions, quel que soit le sens de marche."""
    return (min(a, b), abs(b - a))


def _puissance(etape: Etape, avertissements: list[str], idx: int) -> float:
    """La puissance cible de l'étape, ou la valeur de repli — qui se dit."""
    cible = etape.puissance_cible_w
    if cible is None or not math.isfinite(cible) or cible <= 0:
        avertissements.append(
            f"{_nom(etape, idx)} : aucune puissance cible, vitesse estimée à "
            f"{PUISSANCE_SANS_CIBLE_W:.0f} W"
        )
        return PUISSANCE_SANS_CIBLE_W
    return float(cible)


def _nom(etape: Etape, idx: int) -> str:
    return f"étape {idx + 1} ({etape.libelle or etape.type})"


def _plus_de_route(etat: _Etat, terrain: _Terrain, etape: Etape, idx: int) -> str:
    return (
        f"plus de route au km {etat.position_m / 1000:.1f} sur "
        f"{terrain.total / 1000:.1f} km pour {_nom(etape, idx)}"
    )


def _minutes(secondes: float) -> str:
    return f"{secondes / 60:+.0f} min"


# --- le tracé vu comme une suite de pas -------------------------------------


class _Terrain:
    """Le tracé découpé en pas de `PAS_M` mètres, avec la pente de chaque pas.

    Même découpage et même lissage d'altitude que `physique.modele.simuler` :
    l'altimètre bruite de quelques dizaines de centimètres, ce qui fabrique
    des pentes fantômes de plusieurs pour cent sur 100 m. Les vitesses sont
    mémorisées par (puissance, pente arrondie) : le balayage des décalages
    repasse mille fois sur les mêmes pas, et la bissection du modèle n'a
    aucune raison d'être refaite.
    """

    def __init__(self, trace: Trace, p: Parametres) -> None:
        self.p = p
        distances = _distances_cumulees(trace.points)
        self.total = distances[-1]
        self.bornes = _bornes_pas(self.total)
        altitudes = moyenne_glissante(
            [_altitude(trace.points, distances, d) for d in self.bornes], FENETRE_ALTITUDE
        )
        self.pentes = [
            (altitudes[i + 1] - altitudes[i]) / (self.bornes[i + 1] - self.bornes[i])
            for i in range(len(self.bornes) - 1)
        ]
        self.bornee = trace.bornee()
        self._vitesses: dict[tuple[float, float], float] = {}

    def vitesse(self, puissance_w: float, pente: float) -> float:
        """La vitesse de régime, en m/s, avec les mêmes garde-fous que la simulation."""
        cle = (round(puissance_w, 1), round(pente, 5))
        connue = self._vitesses.get(cle)
        if connue is not None:
            return connue
        v = vitesse_regime(cle[0], cle[1], 0.0, self.p)
        if cle[1] < 0:
            v = min(v, V_MAX_DESCENTE_KMH / 3.6)  # le cycliste freine, le modèle ne le sait pas
        v = max(v, V_MIN_MS)  # plancher affiché, pas une mesure
        self._vitesses[cle] = v
        return v

    def pente_a(self, position_m: float) -> float:
        """La pente du pas qui contient `position_m` (celle du pas le plus proche aux bouts)."""
        i = bisect.bisect_right(self.bornes, position_m) - 1
        return self.pentes[min(max(i, 0), len(self.pentes) - 1)]

    def borner(self, position_m: float) -> float:
        """Ramène une position dans le tracé : par le tour de boucle si elle est fermée."""
        if self.bornee and self.total > 0:
            return position_m % self.total
        return min(max(position_m, 0.0), self.total)

    def avancer(self, position_m: float, sens: int, duree_s: float, puissance_w: float) -> float | None:
        """Position atteinte après `duree_s`, ou `None` si l'on sort du tracé.

        On ne fait pas le tour de la boucle : une séance qui ne tient pas en
        un passage ne tient pas, et le dire vaut mieux que rendre un parcours
        qui repasse deux fois au même endroit.
        """
        if duree_s <= 0:
            return position_m
        restant, pos = duree_s, position_m
        for _ in range(len(self.bornes) + 1):
            i = self._pas(pos, sens)
            if i is None:
                return None
            borne = self.bornes[i + 1] if sens > 0 else self.bornes[i]
            v = self.vitesse(puissance_w, self.pentes[i] * sens)
            t = abs(borne - pos) / v
            if t >= restant:
                return pos + sens * v * restant
            restant -= t
            pos = borne
        return None

    def duree_pour(
        self, position_m: float, sens: int, distance: float, puissance_w: float
    ) -> float | None:
        """Le temps qu'il faut pour couvrir `distance` depuis `position_m`, ou `None`."""
        if distance <= 0:
            return 0.0
        restant, pos, duree = distance, position_m, 0.0
        for _ in range(len(self.bornes) + 1):
            i = self._pas(pos, sens)
            if i is None:
                return None
            borne = self.bornes[i + 1] if sens > 0 else self.bornes[i]
            v = self.vitesse(puissance_w, self.pentes[i] * sens)
            longueur = abs(borne - pos)
            if longueur >= restant:
                return duree + restant / v
            duree += longueur / v
            restant -= longueur
            pos = borne
        return None

    def _pas(self, position_m: float, sens: int) -> int | None:
        """Indice du pas dans lequel on entre depuis `position_m`, `None` hors du tracé."""
        if sens > 0:
            i = bisect.bisect_right(self.bornes, position_m) - 1
        else:
            i = bisect.bisect_left(self.bornes, position_m) - 1
        return i if 0 <= i < len(self.pentes) else None


def _bornes_pas(total: float) -> list[float]:
    """Les bornes des pas de `PAS_M`, le dernier absorbant le reste, jamais de pas nul."""
    bornes = [0.0]
    while bornes[-1] + PAS_M < total:
        bornes.append(bornes[-1] + PAS_M)
    bornes.append(total)
    return bornes


def _distances_cumulees(points: Sequence[PointTrace]) -> list[float]:
    """Les distances cumulées du tracé, recalculées si le tracé n'en porte pas.

    Même précaution que dans `boucle.meteo_trace` et `physique.modele` : un
    tracé importé dont les `dist_m` sont restées à zéro donnerait une séance
    posée sur une longueur nulle.
    """
    if len(points) >= 2 and points[-1].dist_m > 0:
        valeurs = [float(p.dist_m) for p in points]
        if all(b >= a for a, b in zip(valeurs[:-1], valeurs[1:], strict=True)):
            return valeurs
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=True):
        cumul.append(cumul[-1] + distance_m(a, b))
    return cumul


def _altitude(points: Sequence[PointTrace], distances: Sequence[float], d: float) -> float:
    """Altitude interpolée à la distance `d` ; 0 si le tracé n'a pas d'altitude (terrain plat)."""
    i = min(max(bisect.bisect_right(distances, d) - 1, 0), len(points) - 1)
    avant = points[i]
    apres = points[min(i + 1, len(points) - 1)]
    if avant.alt_m is None and apres.alt_m is None:
        return 0.0
    if avant.alt_m is None:
        return float(apres.alt_m)
    if apres.alt_m is None:
        return float(avant.alt_m)
    portee = distances[min(i + 1, len(distances) - 1)] - distances[i]
    f = (d - distances[i]) / portee if portee > 0 else 0.0
    return float(avant.alt_m) + (float(apres.alt_m) - float(avant.alt_m)) * f

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

Chaque bloc est noté **à son intensité** : `evaluer_couloir` reçoit la
puissance cible du bloc et la FTP de la séance (`ftp_de`), parce qu'une
descente sous un bloc à 110 % de FTP n'est pas le même défaut qu'une descente
sous un bloc à 70 % (décision du mainteneur du 13/09,
`terrain.FACTEURS_ZONE_DESCENTE`). La puissance d'une **récupération** n'est
donnée à personne : une récup n'est pas évaluée du tout.

La note de la configuration est la **moyenne des notes de couloir pondérée
par la durée de chaque bloc** :

    note_totale = Σ (note_i × duree_i) / Σ duree_i

Décision du superviseur du 13/09 (Q12) : un bloc de 20 min pèse trente fois
une activation de 40 s. Voir `_note_ponderee` pour le motif.

S'y ajoute la **pénalité de séance** : le terrain sous les blocs ne dit rien
de ce qui arrive aux extrémités élastiques, et un placement qui fait
demi-tour, revient au km 0 et laisse le retour au calme à 0 min au lieu des
20 prescrites était jusqu'ici le mieux noté de tous — il ne traversait aucun
village, et pour cause : il ne roulait presque plus.

Les deux sens ne se paient pas pareil (Q14, close le 13/09/2026) :

* **Raccourcir** ampute la séance. Une étape élastique tombée sous sa fenêtre
  coûte cher, au prorata de ce qui l'en sépare — `PENALITE_SEANCE_NON_TENUE`.
* **Allonger le retour au calme** n'est pas une faute : c'est ainsi qu'on
  referme une boucle dont la longueur n'est jamais exacte, et c'est « du
  kilomètre facile ». Chaque minute de dépassement coûte donc, mais peu et
  sans seuil — `PENALITE_CALME_ALLONGE_KM_PAR_H`. Le dépassement se réduit,
  il ne s'interdit pas : à terrain égal, la boucle la plus juste gagne.

Les deux élasticités sont pour cette raison distinctes : la Z2 d'ouverture
garde sa fenêtre étroite (c'est un levier, pas un tampon), le retour au calme
reçoit la sienne, largement ouverte vers le haut. Voir `_penalite_seance`.

Une note, jamais un filtre : chaque emplacement porte sa note et ses motifs,
on garde la configuration la moins mauvaise et on dit ce qui cloche. `None`
n'est rendu que si la séance ne tient pas du tout sur le tracé ; le motif est
alors rangé dans `trace.meta[CLE_MOTIF]`, comme `boucle.couts` range ses
propres réserves dans `meta`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from ourouler.noyau.seance import Etape, Seance
from ourouler.noyau.trace import (
    Trace,
)
from ourouler.physique.modele import (
    Parametres,
)
from ourouler.seance.pas_trace import (
    PAS_VENT_MS,  # noqa: F401 — réexporté
    _arrondir_vent,  # noqa: F401 — réexporté (tests)
    _distances_cumulees,
    _point_a,  # noqa: F401 — réexporté (tests)
    _Terrain,
)
from ourouler.seance.placement_resultat import (
    DOUBLON_PARCOURS_M,  # noqa: F401 — réexporté
    Emplacement,
    Placement,
    trace_parcourue,  # noqa: F401 — réexporté
)
from ourouler.seance.terrain import demi_tour_faisable, evaluer_couloir, route_au_dela
from ourouler.seance.vent import ChampVent

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

#: Pénalité de séance non tenue, en kilomètres équivalents par unité d'écart
#: relatif hors de la fenêtre d'élasticité, pour une étape élastique
#: **raccourcie**. Un retour au calme tombé à 0 min au lieu des 20 prescrites
#: (écart −100 %, soit 0,95 hors d'une fenêtre qui descend à −5 %) coûte ainsi
#: 19 kilomètres équivalents.
#:
#: Elle doit rester **au-dessus d'un bloc mutilé** — `terrain.PENALITE_BLOC_TRONQUE`
#: vaut 10 — parce que c'est tout son objet : empêcher qu'une séance tronquée
#: gagne. Mesuré le 13/09 sur les quatre candidates des deux sorties réelles :
#: à 20, aucun placement retenu ne tronque la séance sur le 08/02, et celui du
#: 22/04 qui tronque (retour au calme à 20 min au lieu de 40) paie 8,9 et finit
#: dernier. Le même calcul avec la pénalité à 0 fait aussitôt gagner des
#: placements amputés : le 08/02, une candidate bascule sur un placement à
#: 0 min de retour au calme (−98 %) et remonte de la 4ᵉ à la 3ᵉ place ; le
#: 22/04, une autre bascule sur 12 min au lieu de 40 (−69 %) et passe devant.
PENALITE_SEANCE_NON_TENUE = 20.0

#: Ce qu'un avertissement de placement dit quand la séance est **amputée** :
#: une étape élastique est tombée **sous** sa fenêtre, celle que le mainteneur
#: a fixée lui-même (`elasticite_calme_min`, −5 % par défaut). C'est le seul
#: verdict exact sur « la séance est-elle roulée en entier ? », et il est rendu
#: ici, au seul endroit qui connaît les fenêtres.
#:
#: Nommé au lot L5.3 pour que `sortie.contraste` le lise plutôt que de
#: redériver l'amputation d'une comparaison de durées : une sortie 49 s plus
#: courte que la prescription est un arrondi, une sortie dont le retour au
#: calme perd 60 % est une séance non tenue, et aucun seuil sur la durée
#: totale ne distingue les deux honnêtement.
MOTIF_SEANCE_AMPUTEE = "la séance n'est pas roulée en entier"

#: Ce que coûte une **heure** de retour au calme en plus de la prescription, en
#: kilomètres équivalents. **Q14, close le 13/09/2026 par le mainteneur :** « le
#: retour au calme en fait peut dépasser de plus, c'est souvent ce que je fais
#: car c'est incontrôlable de faire parfait, et c'est du kilomètre facile. Faut
#: réduire le dépassement au max. »
#:
#: Deux conséquences, et c'est tout le dessin de cette constante :
#:
#: 1. **Aucun seuil.** Le coût court dès la première minute en trop, au
#:    prorata. L'ancien `PENALITE_SEANCE_ALLONGEE` ne s'appliquait qu'au-delà
#:    de la fenêtre d'élasticité : en deçà deux placements de terrain égal
#:    étaient à égalité parfaite, et le plus long pouvait gagner. Maintenant,
#:    à terrain égal, la boucle la plus juste gagne toujours.
#: 2. **Faible.** Un dépassement n'est pas une faute, c'est la façon normale
#:    de refermer une boucle dont la longueur n'est jamais exacte. Ce qu'il
#:    coûte, aux trois durées qui parlent :
#:
#:      * 10 min de plus → **0,10** km équivalent
#:      * 20 min de plus → **0,20**
#:      * 40 min de plus → **0,40**
#:
#:    à comparer à un défaut de terrain franc sous un bloc : 1 km de village
#:    traversé pendant un bloc de 20 min de la séance du 08/02 coûte
#:    `POIDS_KM_BATI` × 1200/3120 = **1,15** après pondération par la durée des
#:    blocs. Rentrer 20 min plus tard est donc près de six fois moins cher que
#:    de faire traverser un bourg pendant un 20' — ce qui est l'ordre voulu.
#:    Pour le dire dans l'autre sens : 20 min de retour au calme en plus, c'est
#:    environ 9 km de vrai bitume à allure facile, facturés 0,20.
#:
#: Le **raccourcissement**, lui, garde `PENALITE_SEANCE_NON_TENUE` : amputer
#: une séance reste un vrai défaut, et les deux ne sont pas le même défaut.
PENALITE_CALME_ALLONGE_KM_PAR_H = 0.6


#: Dépassement du retour au calme à partir duquel on le dit. Une minute : en
#: deçà, c'est l'arrondi du placement, pas une information.
DEPASSEMENT_CALME_DIT_S = 60.0


def placer(
    seance: Seance,
    trace: Trace,
    p: Parametres,
    *,
    vent: ChampVent | None = None,
    elasticite: tuple[float, float] = (-0.05, 0.20),
    elasticite_calme: tuple[float, float] = (-0.05, 1.5),
    pas_s: float = 60.0,
    penalite_demi_tour: float = 1.0,
) -> Placement | None:
    """La meilleure façon de poser `seance` sur `trace`, ou `None` si elle n'y tient pas.

    `elasticite` est une fraction de la durée de la Z2 **d'ouverture** (−5 % à
    +20 % par défaut) ; le décalage est balayé par pas de `pas_s` secondes,
    bornes comprises. C'est le levier de placement, et lui seul.

    `elasticite_calme` est la fenêtre du **retour au calme** (−5 % à +150 % par
    défaut), qui ne place rien et absorbe : elle est largement ouverte vers le
    haut parce qu'une boucle ne tombe jamais juste (Q14). Sortir de cette
    fenêtre par le haut se dit ; dépasser tout court se paie, au prorata et
    sans seuil.

    `vent` est le champ de vent le long du tracé (`seance.vent.ChampVent`),
    ou `None` pour ne pas en tenir compte. Il change la vitesse de chaque pas,
    donc l'endroit où les blocs tombent : 20 km/h de face ou dans le dos,
    c'est 4 km d'écart sur un bloc de 20 min qui en fait 11. Sans lui, le
    placement rend **exactement** ce qu'il rendait avant que le vent existe.

    La meilleure configuration est celle dont la `note_totale` est la plus
    basse — terrain sous les blocs **et** pénalité de séance ; à égalité, celle
    qui touche le moins à la séance.
    """
    if not seance.etapes:
        return _echec(trace, "séance sans étape : il n'y a rien à placer")
    if len(trace.points) < 2:
        return _echec(trace, "tracé de moins de deux points : il n'y a rien à parcourir")

    # Le refus tombe **avant** la construction du terrain : celle-ci divise par
    # la longueur de chaque pas pour en tirer la pente, et un tracé de deux
    # points confondus la faisait lever `ZeroDivisionError` — une erreur nue,
    # alors que le motif était déjà écrit deux lignes plus bas.
    total = _distances_cumulees(trace.points)[-1]
    if not (math.isfinite(total) and total > 0):
        return _echec(trace, "tracé de longueur nulle : il n'y a rien à parcourir")
    terrain = _Terrain(trace, p, vent)

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
            elasticite_calme=elasticite_calme,
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
    #: Les positions où l'on a fait demi-tour, dans l'ordre, départ compris.
    #: Toujours **rebâtie**, jamais modifiée en place : `replace(etat)` partage
    #: la liste entre les deux variantes d'une paire récup/bloc.
    jalons: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _EcartElastique:
    """Une étape élastique telle qu'elle a été placée, pour `_penalite_seance`.

    `ecart` est relatif — durée placée contre durée prescrite, `−1.0` pour un
    retour au calme tombé à zéro. `depassement_s` est le même écart vu en
    secondes, et seulement vers le haut : il vaut 0 dès que l'étape tient sa
    prescription ou reste en deçà. Les deux coexistent parce que les deux
    défauts ne se mesurent pas dans la même unité — amputer une séance se juge
    en part de ce qui manque, dépasser se juge en minutes de plus (Q14).
    """

    ecart: float
    depassement_s: float
    absorbe: bool  # le retour au calme, qui referme la boucle


def _essayer(
    seance: Seance,
    trace: Trace,
    terrain: _Terrain,
    *,
    decalage_s: float,
    idx_ouverture: int | None,
    idx_fermeture: int | None,
    elasticite: tuple[float, float],
    elasticite_calme: tuple[float, float],
    penalite_demi_tour: float,
) -> Placement | str:
    """Déroule la séance pour un décalage donné : un `Placement`, ou le motif qui a coincé."""
    etapes = seance.etapes
    ftp_w = ftp_de(seance)
    fin = idx_fermeture if idx_fermeture is not None else len(etapes)
    etat = _Etat(jalons=[0.0])
    emplacements: list[Emplacement] = []
    avertissements: list[str] = []
    informations: list[str] = []
    ecarts: list[_EcartElastique] = []  # les étapes élastiques telles que placées

    motif = _derouler_etapes(
        trace,
        terrain,
        etat,
        etapes=etapes,
        fin=fin,
        decalage_s=decalage_s,
        idx_ouverture=idx_ouverture,
        penalite_demi_tour=penalite_demi_tour,
        ftp_w=ftp_w,
        emplacements=emplacements,
        avertissements=avertissements,
        ecarts=ecarts,
    )
    if motif is not None:
        return motif

    if idx_fermeture is not None:
        motif = _fermer(
            terrain,
            etat,
            etapes[idx_fermeture],
            idx_fermeture,
            elasticite_calme=elasticite_calme,
            avertissements=avertissements,
            informations=informations,
            ecarts=ecarts,
            emplacements=emplacements,
        )
        if motif is not None:
            return motif
    _avertir_fin(terrain, etat, avertissements, fermee=idx_fermeture is not None)

    penalite = _penalite_seance(ecarts, elasticite, elasticite_calme)
    # Seuls les blocs portent une note : une récupération n'est jamais évaluée
    # (règle du sprint 4). `_note_ponderee` suppose que chaque emplacement
    # qu'on lui passe a un `note` non `None` — un filtre, jamais un `or 0.0`,
    # qui ferait entrer une note neutre inventée dans la moyenne.
    terrain_note = _note_ponderee([e for e in emplacements if e.note is not None], etapes)
    return Placement(
        decalage_z2_s=decalage_s,
        emplacements=emplacements,
        note_totale=terrain_note + penalite,
        duree_totale_s=etat.duree_s,
        distance_totale_m=etat.distance_m,
        avertissements=list(dict.fromkeys(avertissements)),
        informations=list(dict.fromkeys(informations)),
        note_terrain=terrain_note,
        penalite_seance=penalite,
        jalons_m=[*etat.jalons, etat.position_m],
    )


def _derouler_etapes(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    *,
    etapes: Sequence[Etape],
    fin: int,
    decalage_s: float,
    idx_ouverture: int | None,
    penalite_demi_tour: float,
    ftp_w: float | None,
    emplacements: list[Emplacement],
    avertissements: list[str],
    ecarts: list[_EcartElastique],
) -> str | None:
    """Roule les étapes jusqu'à `fin` (exclue) ; `None`, ou le motif qui a coincé.

    Remplit `emplacements`, `avertissements` et `ecarts` en faisant avancer `etat`.
    """
    i = 0
    # `True` dès qu'un bloc a été placé : condition exacte de la variante
    # demi-tour, « précédé d'une récupération et d'un autre bloc ». Avant le
    # lot L5.2, `emplacements` ne contenait que des blocs et servait de proxy
    # à cette question ; il contient maintenant l'échauffement et les
    # récupérations aussi, donc le proxy ne suffit plus — il faut le dire
    # explicitement.
    un_bloc_precedent = False
    while i < fin:
        etape = etapes[i]
        duree = etape.duree_s + (decalage_s if i == idx_ouverture else 0.0)
        if duree < 0:
            return (
                f"un décalage de {_minutes(decalage_s)} raccourcit la Z2 d'ouverture "
                "au-delà de sa durée"
            )
        if i == idx_ouverture and etape.duree_s > 0:
            ecarts.append(_ecart_ouverture(etape, duree))
        puissance = _puissance(etape, avertissements, i)
        suivante = etapes[i + 1] if i + 1 < fin else None

        if (
            etape.type == TYPE_RECUP
            and suivante is not None
            and suivante.type == TYPE_BLOC
            and un_bloc_precedent
        ):
            jambes = _recup_puis_bloc(
                trace,
                terrain,
                etat,
                recup=etape,
                recup_puissance=puissance,
                recup_idx=i,
                bloc=suivante,
                bloc_idx=i + 1,
                bloc_puissance=_puissance(suivante, avertissements, i + 1),
                penalite_demi_tour=penalite_demi_tour,
                ftp_w=ftp_w,
            )
            if isinstance(jambes, str):
                return jambes
            emplacements.extend(jambes)
            un_bloc_precedent = True
            i += 2
            continue

        if etape.type == TYPE_BLOC:
            emplacement = _bloc_droit(
                trace, terrain, etat, etape, i, puissance_w=puissance, duree_s=duree, ftp_w=ftp_w
            )
            if isinstance(emplacement, str):
                return emplacement
            emplacements.append(emplacement)
            un_bloc_precedent = True
            i += 1
            continue

        emplacement = _etape_libre(terrain, etat, etape, i, duree, puissance)
        if isinstance(emplacement, str):
            return emplacement
        emplacements.append(emplacement)
        i += 1
    return None


def _ecart_ouverture(etape: Etape, duree: float) -> _EcartElastique:
    """L'écart de la Z2 d'ouverture à sa durée prescrite, une fois décalée."""
    return _EcartElastique(
        ecart=duree / etape.duree_s - 1.0,
        depassement_s=max(0.0, duree - etape.duree_s),
        absorbe=False,
    )


def _etape_libre(
    terrain: _Terrain, etat: _Etat, etape: Etape, idx: int, duree_s: float, puissance_w: float
) -> Emplacement | str:
    """Ni bloc, ni paire récup+bloc : l'échauffement, une récupération isolée.

    Avant le premier bloc, ou en queue sans bloc pour l'absorber. Elle roule
    quand même, et sa position se mémorise comme celle de n'importe quelle
    autre étape (Q13) — sans note, aucun terrain n'est évalué ici.
    """
    depart = etat.position_m
    parcouru = etat.distance_m
    if not _rouler(terrain, etat, duree_s, puissance_w):
        return _plus_de_route(etat, terrain, etape, idx)
    debut, longueur = _couloir(depart, etat.position_m)
    return Emplacement(
        etape_idx=idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=False,
        note=None,
        debut_parcouru_m=parcouru,
    )


def _avertir_fin(terrain: _Terrain, etat: _Etat, avertissements: list[str], *, fermee: bool) -> None:
    """Ce qu'il faut dire de la fin de séance : tracé restant, retour à l'envers."""
    if not fermee and etat.sens > 0 and terrain.total - etat.position_m > 0:
        avertissements.append(
            f"il reste {(terrain.total - etat.position_m) / 1000:.1f} km de tracé "
            "après la dernière étape"
        )
    if etat.sens < 0:
        avertissements.append(
            "la séance se termine en sens inverse : le retour se fait sur le tracé à l'envers"
        )


def _penalite_seance(
    ecarts: Sequence[_EcartElastique],
    elasticite: tuple[float, float],
    elasticite_calme: tuple[float, float] = (-0.05, 1.5),
) -> float:
    """Ce que coûtent les extrémités élastiques, en kilomètres équivalents.

    Deux défauts, deux traitements — c'est toute la décision de Q14 (13/09).

    **Raccourcir ampute la séance.** Une étape élastique tombée sous sa fenêtre
    coûte `PENALITE_SEANCE_NON_TENUE` au prorata de ce qui l'en sépare, et non
    de l'écart entier : une minute de moins que la borne ne doit pas coûter
    d'un coup une note entière. Mesuré sur la vérification réelle du 08/02 : le
    placement qui faisait demi-tour au bloc 2, repartait à l'envers et rentrait
    au km 0 avec 0 min de retour au calme au lieu de 20 notait 1,81 — le
    meilleur de tous. Il paie 19,0 de pénalité et se retrouve dernier.

    **Dépasser referme la boucle.** Le mainteneur : « le retour au calme en
    fait peut dépasser de plus […] c'est du kilomètre facile. Faut réduire le
    dépassement au max. » Le dépassement se paie donc, mais peu, et **dès la
    première minute** : `PENALITE_CALME_ALLONGE_KM_PAR_H` par heure de trop,
    sans fenêtre franchie ni marche. C'est ce qui fait qu'à terrain égal la
    boucle la plus juste gagne — avec un seuil, les deux étaient à égalité
    parfaite et le tri retombait sur l'ordre des candidates.

    La fenêtre haute du retour au calme ne sert donc plus à facturer, seulement
    à dire (voir `_fermer`). La Z2 d'ouverture, elle, garde sa fenêtre : elle
    est le levier de placement, et l'utiliser dans les bornes fixées par le
    mainteneur ne coûte rien — c'est à cela qu'elle sert.
    """
    total = 0.0
    for element in ecarts:
        if not math.isfinite(element.ecart):
            continue
        fenetre = elasticite_calme if element.absorbe else elasticite
        bas = min(fenetre)
        if element.ecart < bas:
            total += PENALITE_SEANCE_NON_TENUE * (bas - element.ecart)
        if element.absorbe and math.isfinite(element.depassement_s):
            total += PENALITE_CALME_ALLONGE_KM_PAR_H * max(0.0, element.depassement_s) / 3600.0
    return total


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
    avec le nombre de blocs. La pondération seule ne change pas quel décalage
    gagne — les durées des blocs ne dépendent pas du décalage, donc diviser par
    leur somme ne peut pas renverser un classement. La pénalité de séance non
    tenue, elle, en dépend et le renverse : c'est tout son objet.

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
    *,
    puissance_w: float,
    duree_s: float,
    ftp_w: float | None,
) -> Emplacement | str:
    """Le bloc tel quel, dans le sens de marche, à partir de la position courante."""
    depart = etat.position_m
    parcouru = etat.distance_m
    if not _rouler(terrain, etat, duree_s, puissance_w):
        return _plus_de_route(etat, terrain, bloc, bloc_idx)
    debut, longueur = _couloir(depart, etat.position_m)
    return Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=False,
        note=evaluer_couloir(trace, debut, longueur, puissance_w=puissance_w, ftp_w=ftp_w),
        debut_parcouru_m=parcouru,
    )


def _recup_puis_bloc(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    *,
    recup: Etape,
    recup_puissance: float,
    recup_idx: int,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
    penalite_demi_tour: float,
    ftp_w: float | None,
) -> list[Emplacement] | str:
    """La paire (récupération, bloc) : variante droite contre variante demi-tour.

    Les deux se jouent depuis le même état ; on garde la moins mal notée et
    on applique alors seulement son effet sur la position. La récupération
    n'est jamais évaluée : village, carrefour et revêtement y sont sans
    importance, elle est là pour absorber le point dur. Seule la puissance du
    **bloc** est donnée à `evaluer_couloir` — celle de la récup n'entre nulle
    part, sans quoi l'intensité d'une récup pèserait sur une note de terrain.

    Rend une **liste** de deux `Emplacement` (récup, bloc), pas un seul : la
    récupération obtient désormais sa propre position (Q13, lot L5.2). Le
    second élément est toujours le bloc — c'est lui qui porte la note qui
    arbitre.

    **Limite à connaître (T3).** L'arbitrage se fait ici au seul vu de la note
    de couloir, bloc par bloc, alors que `_penalite_seance` n'est calculée
    qu'à la fin du déroulé. La pénalité de séance non tenue peut donc
    départager deux **décalages**, jamais deux variantes d'une même paire : si
    le demi-tour gagne localement de 0,1 km équivalent, il est retenu même
    s'il fera payer 19 en bout de course, et tous les décalages en héritent.
    C'est exactement la cause (1) décrite dans Q14 — « un demi-tour ajoute de
    la distance que le dimensionnement ignore » — et sa piste (a). Le lecteur
    qui croit que la pénalité arbitre tout se trompe : elle n'arbitre que ce
    qui vient après.
    """
    droite = _variante_droite(
        trace,
        terrain,
        etat,
        recup=recup,
        recup_puissance=recup_puissance,
        recup_idx=recup_idx,
        bloc=bloc,
        bloc_idx=bloc_idx,
        bloc_puissance=bloc_puissance,
        ftp_w=ftp_w,
    )
    demi = _variante_demi_tour(
        trace,
        terrain,
        etat,
        recup=recup,
        recup_puissance=recup_puissance,
        recup_idx=recup_idx,
        bloc=bloc,
        bloc_idx=bloc_idx,
        bloc_puissance=bloc_puissance,
        penalite_demi_tour=penalite_demi_tour,
        ftp_w=ftp_w,
    )
    candidates = [c for c in (droite, demi) if c is not None]
    if not candidates:
        return _plus_de_route(etat, terrain, bloc, bloc_idx)
    jambes, etat_apres = min(candidates, key=lambda c: c[0][-1].note.note)
    etat.position_m, etat.sens = etat_apres.position_m, etat_apres.sens
    etat.distance_m, etat.duree_s = etat_apres.distance_m, etat_apres.duree_s
    etat.jalons = list(etat_apres.jalons)
    return jambes


def _variante_droite(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    *,
    recup: Etape,
    recup_puissance: float,
    recup_idx: int,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
    ftp_w: float | None,
) -> tuple[list[Emplacement], _Etat] | None:
    """Récup puis bloc, tout droit : le cas normal, sans pénalité."""
    essai = replace(etat)
    depart_recup = essai.position_m
    parcouru_recup = essai.distance_m
    if not _rouler(terrain, essai, recup.duree_s, recup_puissance):
        return None
    debut_r, longueur_r = _couloir(depart_recup, essai.position_m)
    recup_emp = Emplacement(
        etape_idx=recup_idx,
        debut_m=debut_r,
        longueur_m=longueur_r,
        demi_tour=False,
        note=None,
        debut_parcouru_m=parcouru_recup,
    )
    depart_bloc = essai.position_m
    parcouru_bloc = essai.distance_m
    if not _rouler(terrain, essai, bloc.duree_s, bloc_puissance):
        return None
    debut, longueur = _couloir(depart_bloc, essai.position_m)
    bloc_emp = Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=False,
        note=evaluer_couloir(trace, debut, longueur, puissance_w=bloc_puissance, ftp_w=ftp_w),
        debut_parcouru_m=parcouru_bloc,
    )
    return [recup_emp, bloc_emp], essai


def _variante_demi_tour(
    trace: Trace,
    terrain: _Terrain,
    etat: _Etat,
    *,
    recup: Etape,
    recup_puissance: float,
    recup_idx: int,
    bloc: Etape,
    bloc_idx: int,
    bloc_puissance: float,
    penalite_demi_tour: float,
    ftp_w: float | None,
) -> tuple[list[Emplacement], _Etat] | None:
    """Le bloc repris en sens inverse, la récup coupée en deux autour du demi-tour.

    `None` dès qu'une des trois conditions manque. Le besoin de route au-delà
    du segment est estimé comme le mainteneur le fait de tête — une demi-récup
    à la vitesse du moment, « 4 min à 25 km/h ≈ 800 m » — et c'est
    `route_au_dela` qui dit si cette route existe, y compris sur une boucle
    fermée où le tracé continue au-delà de sa fin.

    **La récupération reste une seule étape, donc un seul `Emplacement`**
    (Q13, lot L5.2) — elle ne se coupe pas en deux : son `debut_m` est le
    début du couloir entre le point de départ et le point de demi-tour, et sa
    `longueur_m` vaut **`2 × besoin_m`**, l'aller et le retour, pas l'écart
    entre ses deux extrémités (qui vaudrait `besoin_m` et sous-compterait de
    moitié) ni zéro (départ et arrivée sont le même point). C'est cette même
    estimation, à vitesse de récup constante, qui est ajoutée à
    `etat.distance_m` : l'invariant de continuité (contrat §2.2.a, « la somme
    des longueurs vaut `distance_totale_m` ») tient par construction, sur ce
    qui est effectivement compté — pas sur la géométrie exacte, légèrement
    écrêtée en bout de boucle fermée, que `jalons_m` mémorise pour son propre
    usage (voir la docstring d'`Emplacement`).
    """
    moitie = recup.duree_s / 2.0
    if moitie <= 0:
        return None
    besoin_m = (
        terrain.vitesse(
            recup_puissance,
            terrain.pente_a(etat.position_m) * etat.sens,
            terrain.vent_face_a(etat.position_m, etat.sens),
        )
        * moitie
    )
    if not _route_au_dela(trace, terrain, etat.position_m, besoin_m, etat.sens):
        return None
    if not demi_tour_faisable(trace, terrain.borner(etat.position_m + etat.sens * besoin_m)):
        return None

    depart = etat.position_m
    parcouru = etat.distance_m
    tournant_brut = depart + etat.sens * besoin_m
    tournant_ecrete = terrain.dans_le_trace(tournant_brut)
    debut_recup, _ = _couloir(depart, tournant_brut)
    recup_emp = Emplacement(
        etape_idx=recup_idx,
        debut_m=debut_recup,
        longueur_m=2.0 * besoin_m,
        demi_tour=True,
        note=None,
        debut_parcouru_m=parcouru,
    )

    # Figure symétrique : les deux moitiés de récup se compensent, on repart
    # exactement du bout du segment, dans l'autre sens.
    essai = replace(etat)
    essai.sens = -etat.sens
    essai.jalons = [*etat.jalons, tournant_ecrete]
    essai.distance_m += 2 * besoin_m
    essai.duree_s += recup.duree_s
    depart_bloc = essai.position_m
    if not _rouler(terrain, essai, bloc.duree_s, bloc_puissance):
        return None
    debut, longueur = _couloir(depart_bloc, essai.position_m)
    note = evaluer_couloir(trace, debut, longueur, puissance_w=bloc_puissance, ftp_w=ftp_w)
    if abs(note.pente_moyenne) > PENTE_DEMI_TOUR_MAX:
        return None  # en côte, le retour est une descente : ce n'est plus la même figure
    note = replace(
        note,
        note=note.note + penalite_demi_tour,
        motifs=[*note.motifs, "demi-tour : le segment du bloc précédent, repris en sens inverse"],
    )
    bloc_emp = Emplacement(
        etape_idx=bloc_idx,
        debut_m=debut,
        longueur_m=longueur,
        demi_tour=True,
        note=note,
        debut_parcouru_m=parcouru + 2.0 * besoin_m,
    )
    return [recup_emp, bloc_emp], essai


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
    *,
    elasticite_calme: tuple[float, float],
    avertissements: list[str],
    informations: list[str],
    ecarts: list[_EcartElastique],
    emplacements: list[Emplacement],
) -> str | None:
    """La Z2 de fin absorbe la distance restante. Elle ne place rien, elle referme.

    Sa durée est donc **recalculée** : c'est le temps qu'il faut pour rentrer
    depuis là où le dernier bloc s'est terminé.

    Ce qu'on en dit suit la décision Q14 (13/09), et le ton compte autant que
    le chiffre :

    * **rentrer plus tard n'est pas un défaut** — « c'est souvent ce que je
      fais car c'est incontrôlable de faire parfait, et c'est du kilomètre
      facile ». Tant que le dépassement reste dans la fenêtre, c'est une
      **information** neutre, sans ⚠ : ce qu'il faut savoir avant de partir,
      pas une alerte ;
    * un ⚠ ne reste que pour les deux vrais défauts : un retour au calme
      **raccourci**, c'est-à-dire une séance amputée, et un dépassement qui
      **sort de la fenêtre haute**, où ce n'est plus la boucle qui tombe mal
      mais la boucle qui ne va pas avec la séance.

    Dans les deux cas on ne refuse pas : une note, jamais un filtre. Comme
    toute étape (Q13, lot L5.2), le retour au calme obtient sa propre
    position dans `emplacements`, sans note.
    """
    depart = etat.position_m
    parcouru = etat.distance_m
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
    debut, longueur = _couloir(depart, etat.position_m)
    emplacements.append(
        Emplacement(
            etape_idx=idx,
            debut_m=debut,
            longueur_m=longueur,
            demi_tour=False,
            note=None,
            debut_parcouru_m=parcouru,
        )
    )
    if etape.duree_s > 0:
        ecart = duree / etape.duree_s - 1.0
        depassement = max(0.0, duree - etape.duree_s)
        ecarts.append(_EcartElastique(ecart=ecart, depassement_s=depassement, absorbe=True))
        bas, haut = min(elasticite_calme), max(elasticite_calme)
        duree_txt = f"{duree / 60:.0f} min au lieu des {etape.duree_s / 60:.0f} prescrites"
        if ecart < bas:
            avertissements.append(
                f"retour au calme raccourci : {duree_txt} ({ecart:+.0%}) — "
                f"{MOTIF_SEANCE_AMPUTEE}"
            )
        elif ecart > haut:
            avertissements.append(
                f"retour au calme : {duree_txt} ({ecart:+.0%}), "
                f"{_km_en_plus(reste, duree, depassement)} de plus à allure facile — "
                f"au-delà de la fenêtre ({haut:+.0%}) : cette boucle est trop longue "
                "pour cette séance"
            )
        elif depassement >= DEPASSEMENT_CALME_DIT_S:
            informations.append(
                f"retour au calme : {duree_txt}, "
                f"{_km_en_plus(reste, duree, depassement)} de plus à allure facile"
            )
    return None


def _km_en_plus(reste_m: float, duree_s: float, depassement_s: float) -> str:
    """Les kilomètres que vaut le dépassement du retour au calme, à son allure.

    Le retour au calme couvre `reste_m` en `duree_s` ; la part en trop couvre
    la même fraction de cette distance. C'est du kilomètre facile, et c'est
    exactement ce que le mainteneur veut voir écrit — des kilomètres, pas un
    pourcentage.
    """
    if not (math.isfinite(duree_s) and duree_s > 0 and math.isfinite(reste_m)):
        return "0 km"
    km = reste_m * min(1.0, depassement_s / duree_s) / 1000.0
    return f"{km:.0f} km" if km >= 1.0 else f"{km:.1f} km"


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


def ftp_de(seance: Seance) -> float | None:
    """La FTP avec laquelle cette séance a été construite, ou `None`.

    Elle sert à une seule chose ici : donner à `seance.terrain.evaluer_couloir`
    la fraction de FTP de chaque bloc, dont dépend le prix d'une descente
    (décision du mainteneur du 13/09, voir `terrain.FACTEURS_ZONE_DESCENTE`).

    Elle est lue dans `seance.meta["ftp_w"]`, que `seance.intervals` y écrit, et
    **pas** reçue en paramètre : c'est la FTP qui a produit les watts des
    étapes. Une autre FTP donnerait des fractions qui ne correspondent à aucune
    des consignes de la séance — un appelant ne peut donc pas se tromper ici,
    parce qu'il n'a rien à choisir.

    `None` dès que la valeur manque ou n'est pas exploitable : une séance
    construite à la main n'a pas de `meta`, le facteur de zone reste alors
    neutre et la note est celle d'avant. On ne devine pas une FTP.
    """
    brut = seance.meta.get("ftp_w") if isinstance(seance.meta, dict) else None
    if brut is None or isinstance(brut, bool):
        return None
    try:
        ftp = float(brut)
    except (TypeError, ValueError):
        return None
    return ftp if math.isfinite(ftp) and ftp > 0 else None


def _nom(etape: Etape, idx: int) -> str:
    return f"étape {idx + 1} ({etape.libelle or etape.type})"


def _plus_de_route(etat: _Etat, terrain: _Terrain, etape: Etape, idx: int) -> str:
    return (
        f"plus de route au km {etat.position_m / 1000:.1f} sur "
        f"{terrain.total / 1000:.1f} km pour {_nom(etape, idx)}"
    )


def _minutes(secondes: float) -> str:
    return f"{secondes / 60:+.0f} min"

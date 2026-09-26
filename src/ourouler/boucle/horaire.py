"""L'heure de passage à un point du tracé : départ + distance / vitesse + pauses.

Un parcours long (un brevet, une sortie de six heures avec un arrêt déjeuner)
n'est pas roulé d'une traite. `boucle.meteo_trace.evaluer` datait chaque
échantillon avec `depart + distance / vitesse`, vitesse constante, aucun
arrêt : sur un 400 avec une nuit de sommeil, toute la météo du second jour
était lue à la mauvaise heure — on annonçait la pluie de 6 h du matin à
quelqu'un qui passera à 14 h.

Ce module porte ce que `evaluer` reçoit maintenant à la place de `depart` et
`vitesse_kmh` : un `Horaire`, la fonction « à quelle heure suis-je au
kilomètre X », construite par l'appelant (`cli/`/`boucle.commande` ou
`physique.commande`) et reçue telle quelle — le cœur ne lit ni configuration
ni ligne de commande (le cœur ne lit ni configuration ni environnement).

**Pas de modèle de fatigue.** Une pause déclarée est une donnée (le cycliste
a dit qu'il s'arrêterait) ; une vitesse qui décroît avec la distance serait un
modèle, et aucun n'est validé ici. La vitesse reste constante entre les
pauses, comme avant leur existence.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ourouler.noyau.erreurs import ErreurUtilisateur

Horaire = Callable[[float], datetime]
"""À quelle heure le cycliste est-il à `dist_m` mètres du départ."""


@dataclass(frozen=True)
class Pause:
    """Une pause déclarée : à quel point du parcours (en mètres), pour combien de temps."""

    dist_m: float
    duree_s: float


def construire_horaire(depart: datetime, vitesse_kmh: float, pauses: Sequence[Pause] = ()) -> Horaire:
    """Construit l'horaire : `heure(km) = départ + km / vitesse + pauses avant km`.

    Une pause compte pour un échantillon si elle est **strictement avant**
    lui (`pause.dist_m < dist_m`) : au kilomètre même de la pause, le
    cycliste vient d'y arriver, il ne l'a pas encore prise — une pause
    n'avance donc jamais l'heure d'un échantillon qui la précède ou la
    touche, seulement de ceux qui viennent après (contrat : « une pause
    avant un échantillon le décale, une pause après ne le touche pas »).

    `depart` sans fuseau est lu comme UTC, comme dans `meteo_trace.evaluer`
    (et dans le client Open-Meteo). Sans pause, `horaire(km)` rend exactement
    `depart + km / vitesse` : c'est le calcul d'avant ce lot, à la lettre —
    c'est le test de non-régression.

    Lève `ErreurUtilisateur` si `vitesse_kmh` n'est pas strictement positive
    (la vitesse vient de la configuration ou d'une simulation, jamais d'une
    lecture faite ici).
    """
    if not strictement_positif(vitesse_kmh):
        raise ErreurUtilisateur(
            f"vitesse_kmh = {vitesse_kmh} : une vitesse strictement positive est attendue "
            "(l'heure de passage vaut départ + distance / vitesse)"
        )
    depart_tz = depart if depart.tzinfo else depart.replace(tzinfo=UTC)
    pauses_triees = sorted(pauses, key=lambda p: p.dist_m)

    def horaire(dist_m: float) -> datetime:
        roulage_h = dist_m / 1000.0 / vitesse_kmh
        arrets_s = sum(p.duree_s for p in pauses_triees if p.dist_m < dist_m)
        return depart_tz + timedelta(hours=roulage_h) + timedelta(seconds=arrets_s)

    return horaire


def strictement_positif(valeur: float) -> bool:
    """Vrai pour un nombre fini et > 0. NaN et l'infini sont des refus, pas des vitesses."""
    return math.isfinite(valeur) and valeur > 0


def duree_pauses_s(pauses: Sequence[Pause]) -> float:
    """Le temps passé à l'arrêt, toutes pauses confondues, en secondes."""
    return sum(p.duree_s for p in pauses)


# --- lecture des options --pause ----------------------------------------------

#: « 4h30 » ou « 4h » : heures, minutes optionnelles à deux chiffres.
_RE_DUREE_H = re.compile(r"^(\d+)h(\d{2})?$")
#: « 45min ».
_RE_DUREE_MIN = re.compile(r"^(\d+)min$")
#: « 1:30 » (heures:minutes) — la même forme que `HH:MM`, sans les secondes.
_RE_DUREE_HHMM = re.compile(r"^(\d+):([0-5]?\d)$")


def analyser_duree(texte: str) -> float:
    """Une durée en secondes, depuis « 4h30 », « 45min » ou « 1:30 » (heures:minutes).

    Le dépôt ne parsait encore aucune durée sous cette forme (les autres
    lecteurs de durée — `.MRC`, l'affichage `h:mm` — vont dans l'autre sens,
    du nombre vers le texte, ou lisent des minutes déjà nommées) : c'est le
    seul endroit qui accepte une durée telle qu'un cycliste l'écrirait sur la
    ligne de commande.
    """
    brut = (texte or "").strip()
    m = _RE_DUREE_H.match(brut)
    if m:
        heures = int(m.group(1))
        minutes = int(m.group(2)) if m.group(2) else 0
        if minutes >= 60:
            raise ErreurUtilisateur(f"durée {texte!r} illisible : {minutes} minutes, attendu < 60")
        return float(heures * 3600 + minutes * 60)
    m = _RE_DUREE_MIN.match(brut)
    if m:
        return float(int(m.group(1)) * 60)
    m = _RE_DUREE_HHMM.match(brut)
    if m:
        return float(int(m.group(1)) * 3600 + int(m.group(2)) * 60)
    raise ErreurUtilisateur(f"durée {texte!r} illisible : attendu 4h30, 45min ou 1:30 (heures:minutes)")


def analyser_pause(texte: str) -> Pause:
    """Une pause depuis « 180:0h45 » (kilomètre:durée, forme de `--pause`).

    La durée peut elle-même contenir un « : » (« 180:1:30 ») : seul le
    **premier** sépare le kilomètre de la durée, le reste est passé tel quel
    à `analyser_duree`.

    Refuse, en nommant le champ fautif : un kilomètre négatif ou illisible,
    une durée nulle ou négative (une pause de zéro n'en est pas une, et
    l'ignorer en silence plutôt que la refuser serait la même
    erreur cachée qu'une donnée inventée — on n'affirme rien sans mesure).
    """
    brut = (texte or "").strip()
    if ":" not in brut:
        raise ErreurUtilisateur(f"--pause {texte!r} : forme attendue KM:DUREE, par exemple 180:0h45")
    km_texte, duree_texte = brut.split(":", 1)
    km_texte = km_texte.strip()
    try:
        km = float(km_texte.replace(",", "."))
    except ValueError as e:
        raise ErreurUtilisateur(f"--pause {texte!r} : kilomètre {km_texte!r} illisible") from e
    if not math.isfinite(km) or km < 0:
        raise ErreurUtilisateur(f"--pause {texte!r} : kilomètre {km_texte!r} négatif ou invalide")
    duree_s = analyser_duree(duree_texte)
    if duree_s <= 0:
        raise ErreurUtilisateur(f"--pause {texte!r} : durée nulle ou négative")
    return Pause(dist_m=km * 1000.0, duree_s=duree_s)


def valider_pauses(pauses: Sequence[Pause], distance_m: float | None = None) -> None:
    """Refuse deux pauses au même kilomètre, et une pause au-delà du parcours.

    `distance_m` est la longueur connue du parcours (le tracé importé, ou la
    distance demandée pour une boucle à générer). `None` quand elle n'est pas
    encore connue à ce point de la commande : le refus « au-delà du parcours »
    se fait alors plus tard, une fois le tracé en main — jamais en silence,
    seulement plus tard.
    """
    vus: dict[float, Pause] = {}
    for p in pauses:
        cle = round(p.dist_m, 3)
        if cle in vus:
            raise ErreurUtilisateur(f"--pause : deux pauses au même kilomètre ({p.dist_m / 1000.0:g} km)")
        vus[cle] = p
    if distance_m is None:
        return
    for p in pauses:
        if p.dist_m > distance_m:
            raise ErreurUtilisateur(
                f"--pause à {p.dist_m / 1000.0:g} km : au-delà des {distance_m / 1000.0:g} km du parcours"
            )


__all__ = [
    "Horaire",
    "Pause",
    "analyser_duree",
    "analyser_pause",
    "construire_horaire",
    "valider_pauses",
]

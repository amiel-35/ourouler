"""Modèle unique d'activité, en sortie des trois lecteurs (FIT, GPX, TCX).

Contient aussi les deux grandeurs dérivées qui ne dépendent que des points :
la puissance normalisée et le dénivelé positif. Elles sont ici, et pas dans
`lecture`, pour qu'un autre producteur de points (simulation, connecteur)
obtienne exactement les mêmes chiffres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: Fenêtre de la moyenne glissante de la puissance normalisée.
FENETRE_NP = timedelta(seconds=30)

#: Nombre de points de la moyenne glissante qui lisse l'altitude.
FENETRE_ALTITUDE = 5


@dataclass
class Point:
    """Un enregistrement de la trace. Tout champ absent de la source vaut None."""

    t: datetime  # toujours conscient du fuseau, en UTC
    lat: float | None = None
    lon: float | None = None
    alt_m: float | None = None
    dist_m: float | None = None  # distance cumulée depuis le départ
    vitesse_ms: float | None = None
    puissance_w: float | None = None
    cadence_rpm: float | None = None
    fc_bpm: float | None = None
    temp_c: float | None = None


@dataclass
class Activite:
    """Une sortie, telle que relue depuis un fichier brut."""

    source: str  # "fit" | "gpx" | "tcx"
    fichier: str | None  # chemin d'origine, informatif
    debut: datetime  # UTC
    duree_s: float  # écoulée (dernier point − premier)
    duree_mouvement_s: float | None  # si la source la donne, sinon None
    distance_m: float | None
    denivele_m: float | None  # calculé sur les altitudes si présentes, lissé
    puissance_moy_w: float | None
    puissance_np_w: float | None  # puissance normalisée (30 s glissant, ^4)
    sport: str | None  # tel que la source le nomme
    appareil: str | None  # tel que la source le nomme
    points: list[Point] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # tout champ utile non modélisé, JSON

    @property
    def avertissements(self) -> list[str]:
        return list(self.meta.get("avertissements", ()))


# --- grandeurs dérivées -------------------------------------------------------


def puissance_moyenne(points: list[Point]) -> float | None:
    """Moyenne arithmétique des puissances connues, None si aucune."""
    valeurs = [float(p.puissance_w) for p in points if p.puissance_w is not None]
    if not valeurs:
        return None
    return sum(valeurs) / len(valeurs)


def puissance_normalisee(points: list[Point]) -> float | None:
    """Puissance normalisée : moyenne glissante 30 s, puissance 4, moyenne, racine 4ᵉ.

    La fenêtre glisse sur les horodatages réels, et **les deux moyennes sont
    pondérées par la durée** que chaque échantillon représente (son
    intervalle jusqu'au suivant). Sans cette pondération, une portion
    enregistrée plus densément pèse plus lourd que le temps qu'elle occupe
    réellement, et la NP d'un même effort physique change avec la façon de
    l'enregistrer.

    Mesure (voir `tests/test_lecture.py`), sur un seul profil physique —
    900 s à 320 W puis 900 s à 150 W, ondulation de ±30 W — échantillonné de
    plusieurs façons. Référence : le même profil à 0,1 s, soit 275,1 W.

    | échantillonnage | avant pondération | après |
    |-----------------|-------------------|-------|
    | 1 s constant    | 275,0 W           | 275,0 W |
    | 1 s puis 10 s   | 315,1 W (+15 %)   | 274,6 W |
    | 10 s puis 1 s   | 196,4 W (−29 %)   | 274,7 W |

    L'écart résiduel est sous 0,2 %. À pas régulier, 1, 2, 5 et 10 s donnent
    la même valeur à mieux que 0,3 %.

    Écart connu et assumé avec l'implémentation de référence : les 30
    premières secondes sont gardées avec une fenêtre partielle, non
    rejetées. None si moins de deux échantillons de puissance.
    """
    echantillons = sorted(
        (p.t, float(p.puissance_w)) for p in points if p.puissance_w is not None and p.t is not None
    )
    if len(echantillons) < 2:
        return None
    instants = [t for t, _ in echantillons]
    watts = [w for _, w in echantillons]
    # Durée représentée par un échantillon : son intervalle jusqu'au suivant.
    # Le dernier n'en a pas, il reprend l'intervalle précédent.
    durees = [(instants[i + 1] - instants[i]).total_seconds() for i in range(len(instants) - 1)]
    durees.append(durees[-1])

    somme_puissance4 = 0.0
    duree_totale = 0.0
    cumul_pondere = 0.0
    cumul_duree = 0.0
    debut = 0
    for i, t in enumerate(instants):
        cumul_pondere += watts[i] * durees[i]
        cumul_duree += durees[i]
        while instants[debut] < t - FENETRE_NP:
            cumul_pondere -= watts[debut] * durees[debut]
            cumul_duree -= durees[debut]
            debut += 1
        if cumul_duree > 0:
            moyenne = cumul_pondere / cumul_duree
        else:
            # Horodatages identiques dans toute la fenêtre : pondérer n'a plus
            # de sens, on retombe sur la moyenne par échantillon.
            moyenne = sum(watts[debut : i + 1]) / (i - debut + 1)
        somme_puissance4 += moyenne**4 * durees[i]
        duree_totale += durees[i]
    if duree_totale <= 0:
        # Tous les points au même instant : la NP se réduit à la moyenne.
        return sum(watts) / len(watts)
    return (somme_puissance4 / duree_totale) ** 0.25


def denivele_positif(points: list[Point]) -> float | None:
    """Somme des montées sur l'altitude lissée. None si la source n'a pas d'altitude."""
    altitudes = [float(p.alt_m) for p in points if p.alt_m is not None]
    if len(altitudes) < 2:
        return None
    lisse = moyenne_glissante(altitudes, FENETRE_ALTITUDE)
    return sum(max(0.0, apres - avant) for avant, apres in zip(lisse, lisse[1:], strict=False))


def moyenne_glissante(valeurs: list[float], fenetre: int) -> list[float]:
    """Moyenne glissante centrée ; la fenêtre se rétrécit aux deux bords."""
    if fenetre <= 1 or len(valeurs) < 2:
        return list(valeurs)
    demi = fenetre // 2
    cumuls = [0.0]
    for v in valeurs:
        cumuls.append(cumuls[-1] + v)
    lisse = []
    for i in range(len(valeurs)):
        a = max(0, i - demi)
        b = min(len(valeurs), i + demi + 1)
        lisse.append((cumuls[b] - cumuls[a]) / (b - a))
    return lisse

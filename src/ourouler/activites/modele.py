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

    Fenêtre glissante sur les horodatages réels (et non sur un nombre fixe
    d'échantillons) : une trace à 1 Hz, à 2 s ou irrégulière donne le même
    sens. None si moins de deux échantillons de puissance.
    """
    echantillons = sorted(
        (p.t, float(p.puissance_w)) for p in points if p.puissance_w is not None and p.t is not None
    )
    if len(echantillons) < 2:
        return None
    somme_puissance4 = 0.0
    cumul = 0.0
    debut = 0
    for i, (t, watts) in enumerate(echantillons):
        cumul += watts
        while echantillons[debut][0] < t - FENETRE_NP:
            cumul -= echantillons[debut][1]
            debut += 1
        moyenne = cumul / (i - debut + 1)
        somme_puissance4 += moyenne**4
    return (somme_puissance4 / len(echantillons)) ** 0.25


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

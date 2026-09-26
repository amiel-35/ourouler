"""Mailles : un tracé découpé en carrés de ~30 m, pour comparer des routes.

Une maille est `(round(lat × 3000), round(lon × 3000))`. Deux tracés qui
empruntent la même route tombent dans les mêmes mailles, deux routes
parallèles à 100 m l'une de l'autre non. C'est la seule façon de découper un
tracé en mailles : les routes connues (`apprentissage.routes`) et la mesure
de recouvrement entre propositions (`sortie.contraste`) la partagent.

Séparé d'`apprentissage/routes.py` pour que le domaine (`sortie`) n'importe pas
un cas d'usage pour découper un tracé.
"""

from __future__ import annotations

import math

from ourouler.noyau.trace import PointTrace, Trace, distance_m

#: Facteur de la maille : 1/3000 de degré ≈ 37 m en latitude, ~37 m en
#: longitude à nos latitudes. « ~30 m », au degré de précision près.
MAILLE = 3000

#: Pas de découpe d'un segment pour l'attribution aux mailles : une demi-maille,
#: pour qu'aucune maille traversée ne soit sautée quel que soit l'espacement
#: des points du tracé.
PAS_ECHANTILLON_M = 15.0


def cle_maille(lat: float, lon: float) -> tuple[int, int]:
    """La maille ~30 m qui contient ce point : `(round(lat × 3000), round(lon × 3000))`.

    L'arrondi de Python est « au pair le plus proche » : c'est sans importance
    ici, seule la **stabilité** compte — deux passages au même endroit doivent
    tomber dans la même maille, quelle que soit la convention.
    """
    return (round(lat * MAILLE), round(lon * MAILLE))


def mailles_traversees(a: PointTrace, b: PointTrace, longueur: float) -> list[tuple[int, int]]:
    """Les mailles rencontrées entre deux points, une par sous-pas de ~15 m.

    Un tracé BRouter a des points espacés de quelques mètres, un GPX relu
    parfois de cent. Sans subdivision, un pas de 100 m ne marquerait qu'**une**
    maille sur les trois qu'il traverse : la base aurait des trous, et
    `part_connue` chuterait pour la seule raison que deux tracés n'ont pas le
    même pas d'échantillonnage. On découpe donc à une demi-maille, des deux
    côtés — apprentissage et mesure — pour que les deux se répondent.
    """
    n = max(1, math.ceil(longueur / PAS_ECHANTILLON_M))
    mailles = []
    for k in range(n):
        f = (k + 0.5) / n
        mailles.append(cle_maille(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f))
    return mailles


def mailles_ponderees(trace: Trace) -> dict[tuple[int, int], float]:
    """Les mailles traversées par un tracé, chacune avec les mètres qu'elle porte.

    Séparée de `BaseRoutes.part_connue` pour être partagée avec
    `recouvrement` : « quelle part de ce tracé connais-je ? » et « quelle part
    de ce tracé est aussi dans celui-là ? » sont la même question posée à deux
    ensembles de mailles différents, et il n'y a pas deux façons de découper
    un tracé en mailles. La somme des valeurs est la longueur exploitable du
    tracé, en mètres.
    """
    metres: dict[tuple[int, int], float] = {}
    for i in range(len(trace.points) - 1):
        a, b = trace.points[i], trace.points[i + 1]
        longueur = distance_m(a, b)
        if not math.isfinite(longueur) or longueur <= 0:
            continue
        mailles = mailles_traversees(a, b, longueur)
        part = longueur / len(mailles)
        for cle in mailles:
            metres[cle] = metres.get(cle, 0.0) + part
    return metres

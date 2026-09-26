"""Ce que les trois lecteurs de séance (Intervals, ZWO, MRC) font de la même façon.

Le typage d'une étape par sa position, le marquage des étapes élastiques et
deux petits formats de libellé : écrits une fois, pour que les trois lecteurs
ne divergent pas.
"""

from __future__ import annotations

from ourouler.noyau.seance import Etape


def type_par_position(indice: int, total: int) -> str:
    """Ce qu'est une étape qui n'est pas un bloc, selon l'endroit où elle tombe.

    En tête, c'est un échauffement ; en queue, un retour au calme ; entre les
    deux, une récupération. Le cas visé au milieu est celui d'une étape prise
    entre deux efforts ; une étape calme au milieu qui ne sépare pas deux
    blocs est traitée de même — une récupération ne demande rien au terrain
    (décision du 13/09), c'est donc le classement le plus prudent.
    """
    if indice == 0:
        return "echauffement"
    if indice == total - 1:
        return "calme"
    return "recuperation"


def retyper(etape: Etape, type_: str) -> Etape:
    """La même étape sous un autre type ; elle n'est pas (encore) élastique."""
    return Etape(
        type=type_,
        duree_s=etape.duree_s,
        puissance_min_w=etape.puissance_min_w,
        puissance_max_w=etape.puissance_max_w,
        libelle=etape.libelle,
    )


def marquer_elastiques(etapes: list[Etape]) -> list[Etape]:
    """Élastiques : la première étape si elle échauffe, la dernière si elle calme.

    Jamais ailleurs. Une récupération, courte ou longue, fait partie de la
    prescription (décision du mainteneur du 13/09).
    """
    if not etapes:
        return etapes
    sortie = list(etapes)
    if sortie[0].type == "echauffement":
        sortie[0] = _elastique(sortie[0])
    if sortie[-1].type == "calme":
        sortie[-1] = _elastique(sortie[-1])
    return sortie


def _elastique(etape: Etape) -> Etape:
    return Etape(
        type=etape.type,
        duree_s=etape.duree_s,
        puissance_min_w=etape.puissance_min_w,
        puissance_max_w=etape.puissance_max_w,
        libelle=etape.libelle,
        elastique=True,
    )


def nombre_court(valeur: float) -> str:
    """Le nombre sans zéros inutiles : « 95 », « 2.5 »."""
    return f"{valeur:g}"


def joindre(*morceaux: str) -> str:
    """Les morceaux non vides d'un libellé, séparés par « · »."""
    return " · ".join(m for m in morceaux if m)

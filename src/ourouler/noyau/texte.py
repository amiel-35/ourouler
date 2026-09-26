"""Petits formats de texte partagés : nombres à la française, durées, azimuts.

Au noyau parce que le rendu, les cas d'usage et le domaine écrivent tous des
phrases pour le cycliste, et qu'un même nombre doit s'y écrire partout pareil.
"""

from __future__ import annotations


def nombre_fr(valeur: float, decimales: int, *, signe: bool = False) -> str:
    """Un nombre à la française : virgule décimale ; `signe` force le « + » des positifs."""
    return f"{valeur:{'+' if signe else ''}.{decimales}f}".replace(".", ",")


def duree_h_min(secondes: float) -> str:
    """Une durée en « h:mm », arrondie à la minute."""
    minutes = round(secondes / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def minutes_signees(secondes: float) -> str:
    """Un écart de temps en minutes, toujours signé : « +3 min », « -1 min »."""
    return f"{secondes / 60:+.0f} min"


def azimut_texte(azimut_deg: float | None) -> str:
    """« 135° », ou « direction inconnue »."""
    return f"{azimut_deg:.0f}°" if azimut_deg is not None else "direction inconnue"

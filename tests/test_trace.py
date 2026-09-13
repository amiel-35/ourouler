"""Tests du modèle de tracé partagé (sprint 2, socle)."""

import math

from ourouler.boucle.trace import PointTrace, Trace, cap_deg, distance_m, sens_boucle


def _cercle(sens: int, n: int = 36, rayon_deg: float = 0.02) -> Trace:
    """Boucle fermée autour de (0, 0), en mer ; sens +1 = antihoraire (est → nord → ouest)."""
    pts = []
    for i in range(n + 1):
        a = sens * 2 * math.pi * i / n
        pts.append(PointTrace(rayon_deg * math.sin(a), rayon_deg * math.cos(a), None, 0.0))
    return Trace(nom="t", points=pts, segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None)


def test_distance_et_cap():
    a = PointTrace(0.0, 0.0, None, 0.0)
    nord = PointTrace(0.01, 0.0, None, 0.0)
    est = PointTrace(0.0, 0.01, None, 0.0)
    assert abs(distance_m(a, nord) - 1112) < 5
    assert abs(cap_deg(a, nord) - 0) < 0.01
    assert abs(cap_deg(a, est) - 90) < 0.01
    assert abs(cap_deg(nord, a) - 180) < 0.01


def test_sens_boucle():
    assert sens_boucle(_cercle(+1)) == "antihoraire"
    assert sens_boucle(_cercle(-1)) == "horaire"
    ouverte = _cercle(+1)
    ouverte.points = ouverte.points[: len(ouverte.points) // 2]
    assert not ouverte.bornee()
    assert sens_boucle(ouverte) == "indetermine"
    aller_retour = Trace(
        nom="ar",
        points=[PointTrace(0, 0, None, 0), PointTrace(0.01, 0, None, 0), PointTrace(0, 0, None, 0)],
        segments=[], distance_m=0, denivele_m=None, temps_moteur_s=None,
    )
    assert sens_boucle(aller_retour) == "indetermine"

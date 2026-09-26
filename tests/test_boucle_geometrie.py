"""Tests de la géométrie exposée en JSON (lot F0.1) : simplification et forme.

Tracés synthétiques uniquement (règle absolue : aucune coordonnée réelle),
autour de (0, 0), en mer — même convention que `tests/test_trace.py`.
"""

from __future__ import annotations

import bisect
import math

from ourouler.boucle.geometrie import (
    TOLERANCE_DEFAUT_M,
    _distance_segment_m,
    geometrie_json,
    simplifier,
)
from ourouler.noyau.trace import PointTrace, Trace, distance_m

#: Rayon terrestre, redéfini ici plutôt qu'importé : la règle de contrôle ne
#: doit rien partager avec ce qu'elle mesure, constantes comprises.
RAYON_TERRE_M = 6_371_000.0


def _trace(points: list[PointTrace]) -> Trace:
    return Trace(
        nom="t", points=points, segments=[], distance_m=0.0, denivele_m=None, temps_moteur_s=None
    )


def _cercle_bruite(n: int = 2000, rayon_deg: float = 0.05, bruit_deg: float = 0.00001) -> list[PointTrace]:
    """Un cercle très échantillonné, avec un petit bruit reproductible.

    `bruit_deg = 0.00001` vaut environ 1,1 m au sol : assez pour que la ligne
    ne soit jamais parfaitement droite entre deux points voisins (sinon
    Douglas-Peucker n'aurait rien à faire), bien en dessous de la tolérance
    par défaut (5 m) pour que la simplification ait un effet mesurable.
    """
    pts = []
    dist = 0.0
    precedent = None
    for i in range(n):
        a = 2 * math.pi * i / n
        # Un terme périodique rapide (bruit) superposé au cercle : pas de
        # hasard, le test reste déterministe.
        r = rayon_deg + bruit_deg * math.sin(i * 37)
        lat, lon = r * math.sin(a), r * math.cos(a)
        p = PointTrace(lat, lon, alt_m=100.0 + i * 0.01, dist_m=dist)
        if precedent is not None:
            dist += distance_m(precedent, p)
            p = PointTrace(lat, lon, alt_m=100.0 + i * 0.01, dist_m=dist)
        pts.append(p)
        precedent = p
    return pts


def test_simplification_reduit_le_volume_et_reste_fidele():
    points = _cercle_bruite()
    resultat = geometrie_json(_trace(points))
    mesure = resultat["simplification"]
    assert mesure["points_origine"] == len(points)
    # Le gain doit être net : c'est tout le sens de la simplification.
    assert mesure["points_rendus"] < mesure["points_origine"] // 2
    # Et l'écart mesuré ne dépasse jamais la tolérance demandée — la
    # propriété centrale du contrat : le cycliste doit reconnaître sa route.
    assert mesure["ecart_max_m"] <= TOLERANCE_DEFAUT_M
    assert mesure["tolerance_m"] == TOLERANCE_DEFAUT_M


def _distance_segment_plane(p, a, b):
    """Distance de `p` au segment `[a, b]`, par projection plane locale.

    **Une seconde règle, qui ne partage aucun code avec la première.** Ce test
    existait déjà mais mesurait l'écart avec `_distance_segment_m` — la
    fonction même qu'il prétendait contrôler. Il a donc laissé passer une
    perte de signe qui rendait 0,01 m pour un point situé 280 m derrière le
    début d'un segment. Une règle faussée qui se vérifie elle-même trouve
    toujours que tout va bien.

    Ici : équirectangulaire centrée sur `a` (les degrés de longitude
    rétrécissent en `cos(lat)`), puis la projection scalaire classique bornée
    à [0, 1]. Sur quelques kilomètres l'écart à la sphère est très inférieur
    au mètre, et c'est le **bornage** qui importe — c'est lui qui distingue
    un segment d'une droite infinie, et c'est lui qui manquait.
    """
    rad = math.radians
    k = math.cos(rad(a.lat))
    ax, ay = 0.0, 0.0
    bx, by = (b.lon - a.lon) * k, (b.lat - a.lat)
    px, py = (p.lon - a.lon) * k, (p.lat - a.lat)
    dx, dy = bx - ax, by - ay
    long2 = dx * dx + dy * dy
    t = 0.0 if long2 == 0 else max(0.0, min(1.0, (px * dx + py * dy) / long2))
    ex, ey = px - t * dx, py - t * dy
    return math.hypot(ex, ey) * math.radians(1.0) * RAYON_TERRE_M


def test_distance_au_segment_pour_un_point_en_arriere_du_depart():
    """Un point derrière `a` se mesure contre `a`, pas contre la droite infinie.

    Le cas que la perte de signe de `acos` rendait invisible : la projection
    tombe hors du segment, du côté du début. Sans garde, seule la distance au
    travers était rendue — quasi nulle pour un point aligné, donc un point
    lointain passait pour confondu avec le tracé. Ce que Douglas-Peucker
    effaçait alors, ce sont les antennes et les demi-tours.
    """
    # Latitude moyenne pour que la convergence des méridiens joue vraiment,
    # longitude choisie loin de toute ville française : l'invariant
    # `test_aucune_coordonnee_francaise_dans_les_tests` garde la règle
    # absolue 1, et il a attrapé une première version de ce test posée à 2 km
    # de chez le mainteneur.
    LAT, LON = 48.10, 120.00
    metres_par_degre_lon = 111_320.0 * math.cos(math.radians(LAT))
    a = PointTrace(LAT, LON, None, None)
    b = PointTrace(LAT, LON + 300.0 / metres_par_degre_lon, None, None)  # ~300 m plein est
    for recul_m in (10.0, 100.0, 280.0, 400.0):
        p = PointTrace(LAT, LON - recul_m / metres_par_degre_lon, None, None)
        attendu = distance_m(a, p)
        obtenu = _distance_segment_m(p, a, b)
        assert abs(obtenu - attendu) < 1.0, (
            f"point à {recul_m:.0f} m derrière le départ : {obtenu:.2f} m rendu "
            f"pour {attendu:.1f} m réels"
        )


def test_ecart_mesure_est_reellement_borne_par_la_tolerance():
    """Simplifie à plusieurs tolérances et vérifie l'écart réel à chaque fois.

    Pas seulement « l'algorithme le garantit » : on mesure, comme demande la
    règle absolue 5. Et on mesure avec une règle qui n'est pas celle qu'on
    contrôle — voir `_distance_segment_plane`.
    """
    points = _cercle_bruite(n=500, rayon_deg=0.02, bruit_deg=0.0003)  # ~33 m de bruit
    for tolerance in (1.0, 5.0, 20.0):
        simplifies = simplifier(points, tolerance_m=tolerance)
        ecart_reel = max(
            min(
                _distance_segment_plane(p, simplifies[i], simplifies[i + 1])
                for i in range(len(simplifies) - 1)
            )
            for p in points
        )
        assert ecart_reel <= tolerance + 1e-6, f"tolérance {tolerance} m dépassée : {ecart_reel} m"


def test_trace_vide():
    resultat = geometrie_json(_trace([]))
    assert resultat["points"] == []
    assert resultat["profil"] == []
    assert resultat["simplification"] == {
        "tolerance_m": TOLERANCE_DEFAUT_M,
        "points_origine": 0,
        "points_rendus": 0,
        "ecart_max_m": 0.0,
    }


def test_deux_points_confondus():
    """Un tracé dégénéré (deux points identiques) ne casse rien."""
    p = PointTrace(0.001, 0.002, alt_m=50.0, dist_m=0.0)
    resultat = geometrie_json(_trace([p, p, p, p]))
    assert resultat["simplification"]["points_rendus"] == 2  # les deux extrémités
    assert resultat["simplification"]["ecart_max_m"] == 0.0
    assert resultat["points"] == [[0.001, 0.002], [0.001, 0.002]]


def test_ligne_droite_se_reduit_a_ses_deux_extremites():
    origine = PointTrace(0, 0, None, 0)
    points = [
        PointTrace(
            0.0, 0.0001 * i, alt_m=None, dist_m=distance_m(origine, PointTrace(0, 0.0001 * i, None, 0))
        )
        for i in range(200)
    ]
    resultat = geometrie_json(_trace(points))
    assert resultat["simplification"]["points_rendus"] == 2
    assert resultat["simplification"]["ecart_max_m"] == 0.0


def test_forme_points_paires_profil_parallele_meme_longueur():
    points = _cercle_bruite(n=300, rayon_deg=0.01, bruit_deg=0.0002)
    resultat = geometrie_json(_trace(points))
    assert len(resultat["points"]) == len(resultat["profil"])
    for point, profil in zip(resultat["points"], resultat["profil"], strict=True):
        assert len(point) == 2  # [lat, lon]
        assert len(profil) == 2  # [dist_m, alt_m]


def test_altitude_absente_rend_null_partout():
    points = [PointTrace(0.0, 0.0001 * i, alt_m=None, dist_m=float(i)) for i in range(10)]
    resultat = geometrie_json(_trace(points))
    assert all(alt is None for _, alt in resultat["profil"])


def test_dist_m_croissant_permet_une_recherche_dichotomique_sans_ambiguite():
    """Les repères kilométriques des blocs se raccordent à `profil`.

    `debut_m` d'un `Emplacement` est une distance en mètres sur le tracé
    d'origine (`seance/placement.py`) : un front la retrouve par `bisect` sur
    la colonne `dist_m` de `profil`. Ce test vérifie que cette colonne reste
    triée après simplification, quelle que soit la tolérance.
    """
    points = _cercle_bruite(n=800, rayon_deg=0.03, bruit_deg=0.0002)
    resultat = geometrie_json(_trace(points), tolerance_m=10.0)
    distances = [d for d, _ in resultat["profil"]]
    assert distances == sorted(distances)
    # Une position à mi-tracé se retrouve sans erreur ni exception.
    cible = distances[-1] / 2
    idx = bisect.bisect_left(distances, cible)
    assert 0 <= idx <= len(distances)


def test_distance_segment_hors_segment_retombe_sur_le_bout_le_plus_proche():
    a = PointTrace(0.0, 0.0, None, 0.0)
    b = PointTrace(0.0, 0.01, None, 0.0)
    au_dela_de_b = PointTrace(0.0005, 0.02, None, 0.0)
    assert abs(_distance_segment_m(au_dela_de_b, a, b) - distance_m(b, au_dela_de_b)) < 0.01


def test_distance_segment_perpendiculaire_exacte_sur_l_equateur():
    """La ligne a-b suit l'équateur (un grand cercle exact) : la distance
    au travers d'un point à cette latitude nulle doit valoir, au mètre près,
    le simple écart nord-sud — aucune approximation de projection en jeu."""
    a = PointTrace(0.0, 0.0, None, 0.0)
    b = PointTrace(0.0, 0.01, None, 0.0)
    p = PointTrace(0.001, 0.005, None, 0.0)
    attendu = distance_m(PointTrace(0.0, 0.005, None, 0.0), p)
    assert abs(_distance_segment_m(p, a, b) - attendu) < 0.5

"""Fabriques du sprint 5 — échantillons de vent et tracés à cap contrôlé.

Rien ici n'est réel : les coordonnées partent de `fabriques.LAT0/LON0`, en
pleine mer au sud du golfe de Guinée, et les vents sont des chiffres ronds
choisis pour rendre les écarts lisibles (règle absolue 1 de CLAUDE.md).

Le point délicat de L5.1 est la **convention d'angle** :
`vent_depuis_deg` est la direction d'**où vient** le vent, convention météo,
la même que `meteo.rapport.vent_relatif` et que `calibration._vent_de_face`.
Le vent est de face quand il vient de là où l'on va, donc

    v_face = V · cos(vent_depuis_deg − cap_effectif)

positive de face. Les fabriques ci-dessous construisent les échantillons à
partir de l'**écart voulu**, jamais à partir d'une direction absolue tapée à
la main : un test qui se trompe de convention dans sa propre fabrique
« vérifierait » l'erreur qu'il cherche.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import fabriques

#: Départ fictif des séries d'échantillons. Aucune heure réelle de sortie.
T0 = datetime(2026, 3, 29, 9, 0, tzinfo=UTC)

#: Vent de référence des tests : 36 km/h = 10 m/s pile à 10 m du sol, donc
#: 6 m/s au cycliste avec le facteur 0,6. Les trois chiffres sont ronds, un
#: écart de signe se lit à l'œil dans le message d'échec.
VENT_KMH = 36.0
VENT_MS = VENT_KMH / 3.6


def facteur_hauteur_du_projet() -> float:
    """`FACTEUR_VENT_HAUTEUR` de `physique.modele` — jamais une valeur recopiée.

    Le contrat §1.2 b) exige que `ChampVent` utilise **la** constante du
    projet, pas un 0,6 réécrit dans son coin. Un test qui coderait 0,6 en dur
    passerait encore si quelqu'un redéfinissait la constante ailleurs.
    """
    from ourouler.physique.modele import FACTEUR_VENT_HAUTEUR

    return float(FACTEUR_VENT_HAUTEUR)


def attendu_ms(
    ecart_deg: float, *, vent_kmh: float = VENT_KMH, facteur: float | None = None
) -> float:
    """La composante de face attendue, en m/s, pour un écart (vent − cap) donné."""
    f = facteur_hauteur_du_projet() if facteur is None else facteur
    return (vent_kmh / 3.6) * math.cos(math.radians(ecart_deg)) * f


# --- échantillons -----------------------------------------------------------


def echantillon(
    module: Any,
    *,
    dist_m: float,
    vent_kmh: float | None = VENT_KMH,
    vent_depuis_deg: float | None = 0.0,
    cap_deg: float = 0.0,
    minute: float = 0.0,
    pluie_mm: float | None = 0.0,
    ressenti_c: float | None = 12.0,
) -> Any:
    """Un `Echantillon` de `boucle.meteo_trace`, construit par mots-clés.

    `cap_deg` est celui du tracé au point échantillonné : `ChampVent` ne doit
    **pas** s'en servir (le cap qui compte est celui du pas interrogé, passé à
    `vent_face_ms`). Il est donc volontairement mis à une valeur absurde dans
    plusieurs tests, pour détecter une implémentation qui le lirait.
    """
    lat, lon = fabriques.deplacer(fabriques.LAT0, fabriques.LON0, 0.0, dist_m)
    return module.Echantillon(
        dist_m=float(dist_m),
        t=T0.replace(minute=int(minute)),
        lat=lat,
        lon=lon,
        cap_deg=float(cap_deg),
        pluie_mm=pluie_mm,
        vent_kmh=vent_kmh,
        vent_relatif=None,
        ressenti_c=ressenti_c,
        vent_depuis_deg=vent_depuis_deg,
    )


def serie(
    module: Any,
    directions: Sequence[float | None],
    *,
    pas_m: float = 5000.0,
    vitesses_kmh: Sequence[float | None] | None = None,
    cap_absurde: float = 123.456,
) -> list[Any]:
    """Une série d'échantillons régulièrement espacés, une direction par point."""
    vitesses = list(vitesses_kmh) if vitesses_kmh is not None else [VENT_KMH] * len(directions)
    assert len(vitesses) == len(directions), "une vitesse par direction attendue"
    return [
        echantillon(
            module,
            dist_m=i * pas_m,
            vent_kmh=v,
            vent_depuis_deg=d,
            cap_deg=cap_absurde,
            minute=min(i * 5, 59),
        )
        for i, (d, v) in enumerate(zip(directions, vitesses, strict=True))
    ]


def champ_uniforme(module_meteo: Any, module_vent: Any, direction_deg: float, **kw: Any) -> Any:
    """Un `ChampVent` de vent parfaitement uniforme le long du tracé."""
    return module_vent.ChampVent(serie(module_meteo, [direction_deg] * 3), **kw)


# --- géométries à cap contrôlé ----------------------------------------------


def boucle_vallonnee(
    *,
    rayon_m: float = 9549.0,
    n: int = 600,
    amplitude_m: float = 40.0,
    periodes: int = 3,
    nom: str = "boucle vallonnee de test",
) -> Any:
    """Boucle fermée dont l'altitude ondule : le placement y a un vrai choix.

    Une boucle rigoureusement plate rend tous les décalages équivalents ; le
    golden de non-régression n'y mesurerait presque rien. L'ondulation fait
    varier les vitesses le long du tracé, donc les positions des blocs, donc
    les notes de couloir.
    """
    import fabriques4

    coords = fabriques.cercle(n, rayon_m=rayon_m, sens="horaire")
    ondules = [
        (lat, lon, 50.0 + amplitude_m * math.sin(2.0 * math.pi * periodes * i / max(n, 1)))
        for i, (lat, lon, _) in enumerate(coords)
    ]
    return fabriques4.trace_taguee(ondules, nom=nom)


def droite_au_cap(cap_deg: float, *, n_troncons: int = 40, pas_m: float = 100.0) -> Any:
    """Un segment droit d'un seul cap, plat, pour lire le cap calculé par `_Terrain`."""
    import fabriques4

    coords = fabriques.ligne(n_troncons + 1, pas_m=pas_m, cap_deg=cap_deg)
    return fabriques4.trace_taguee(coords, nom=f"droite au cap {cap_deg:g}")


def coude_au_nord(*, cap_avant: float = 350.0, cap_apres: float = 10.0, n: int = 20) -> Any:
    """Deux branches encadrant le nord : le piège du passage 359° → 1°."""
    import fabriques4

    coords = fabriques.coude(cap_avant=cap_avant, cap_apres=cap_apres, n=n, pas_m=100.0)
    return fabriques4.trace_taguee(coords, nom="coude au nord")


def ecart_au_nord(cap: float) -> float:
    """Écart angulaire absolu entre `cap` et le nord, dans [0, 180]."""
    return abs((cap + 180.0) % 360.0 - 180.0)


def ecart_angulaire(a: float, b: float) -> float:
    """Écart absolu entre deux caps, dans [0, 180]."""
    return abs((a - b + 180.0) % 360.0 - 180.0)

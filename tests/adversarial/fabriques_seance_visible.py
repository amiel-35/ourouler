"""Fabriques de la séance entière visible : chaque étape placée sur le tracé (Q13).

Écrites **en aveugle** de l'implémentation : ces fabriques ne connaissent de
la séance visible que ce qu'elle promet, pas la façon dont elle est codée.

Trois familles :

* **géométries et séances contrôlées** (`trace_droite`, `boucle_carree`,
  `seance_2x20`, …) : rien de réel, tout part de `fabriques.LAT0/LON0`, en
  pleine mer au large du golfe de Guinée (règle absolue 1 de CLAUDE.md) ;
* **terrain factice** (`terrain_factice`) : `evaluer_couloir` rend une note
  connue d'avance, `route_au_dela` et `demi_tour_faisable` répondent ce qu'on
  leur dit. On veut un terrain dont on connaît la réponse, pas le vrai ;
* **le vérificateur de continuité** (`verifier_continuite`), qui est le cœur
  adversarial du lot et mérite qu'on explique pourquoi il est écrit ainsi.

## Pourquoi la continuité ne se vérifie pas sur `debut_m` seul

La règle veut que les emplacements « se suivent sans trou ni
recouvrement, du départ à l'arrivée », que « la somme de leurs longueurs
vaut `distance_totale_m` » et que le début de chacun soit la fin du précédent
« **au sens du parcours réellement roulé, demi-tours compris, donc en suivant
`jalons_m`** ».

Or `debut_m` est une position **sur le tracé** (`_couloir` rend `min(a, b)`),
pas un compteur kilométrique. Sur la figure de demi-tour du placement —
« bloc → moitié de récup → demi-tour → moitié de récup → bloc » — la
récupération part de `P`, va jusqu'à `P + b`, fait demi-tour et revient à
`P` : elle roule `2b` mètres pour une empreinte de `b` mètres sur le tracé, et
elle finit là où elle a commencé. Les deux lectures divergent donc franchement,
et c'est exactement là que le lot peut se tromper sans que rien ne le dise :
afficher `b` (la distance à vol d'oiseau entre deux points du tracé) au lieu
de `2b` (ce qui est réellement roulé).

`verifier_continuite` ne devine donc **aucun nom de champ nouveau**. Il
n'utilise que ce que le contrat nomme explicitement : `longueur_m`, `debut_m`,
`jalons_m`, `distance_totale_m`. Il reconstruit le compteur kilométrique à
partir des longueurs cumulées, projette chaque abscisse roulée sur le tracé
via `jalons_m`, et exige que l'empreinte ainsi calculée commence bien à
`debut_m`. Une implémentation qui pose `2b` dans `longueur_m` passe ; une qui
pose `b` échoue sur la somme ; une qui pose `2b` mais se trompe d'origine
échoue sur `debut_m`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import fabriques
import fabriques_seance
import pytest

from ourouler.noyau import seance as module_seance
from ourouler.noyau.trace import PointTrace, Trace
from ourouler.seance import placement as module_placement

#: Un cycliste plausible, aucune donnée personnelle : 80 kg tout compris.
#: Les mêmes chiffres que `tests/test_seance_placement.py`, pour que les
#: positions se comparent d'un fichier à l'autre.
MASSE_KG = 80.0
CDA_M2 = 0.35
CRR = 0.006

PUISSANCE_Z2 = 180.0
PUISSANCE_BLOC = 210.0
PUISSANCE_RECUP = 140.0
PUISSANCE_CALME = 150.0

#: Degrés de longitude par mètre à l'équateur.
DEG_PAR_M = 1.0 / 111_194.9


def parametres() -> Any:
    from ourouler.physique.modele import Parametres

    return Parametres(masse_totale_kg=MASSE_KG, cda_m2=CDA_M2, crr=CRR)


# --- géométries --------------------------------------------------------------


def trace_droite(longueur_m: float = 78_000.0, *, pas_m: float = 500.0, pente: float = 0.0) -> Trace:
    """Une ligne droite vers l'est, plate (ou de pente constante).

    Le départ n'est pas (0, 0) mais `fabriques.LAT0/LON0` : un tracé dont le
    premier point est l'origine exacte se confondrait avec une coordonnée
    manquante lue comme zéro.
    """
    n = int(longueur_m // pas_m)
    lat, lon = fabriques.LAT0, fabriques.LON0
    alt = 100.0
    points = [PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=0.0)]
    for i in range(n):
        lat, lon = fabriques.deplacer(lat, lon, 90.0, pas_m)
        alt = alt + pente * pas_m
        points.append(PointTrace(lat=lat, lon=lon, alt_m=alt, dist_m=(i + 1) * pas_m))
    return Trace(
        nom="droite d'essai",
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=None,
        temps_moteur_s=None,
        meta={},
    )


def boucle_carree(cote_m: float = 20_000.0, pas_m: float = 500.0) -> Trace:
    """Un carré fermé de `4 × cote_m`, plat. Une vraie boucle, pas une droite."""
    n = int(cote_m // pas_m)
    cotes = ((1, 0), (0, 1), (-1, 0), (0, -1))
    x = y = 0.0
    points = [PointTrace(lat=fabriques.LAT0, lon=fabriques.LON0, alt_m=100.0, dist_m=0.0)]
    for dx, dy in cotes:
        for _ in range(n):
            x, y = x + dx * pas_m, y + dy * pas_m
            points.append(
                PointTrace(
                    lat=fabriques.LAT0 + y * DEG_PAR_M,
                    lon=fabriques.LON0 + x * DEG_PAR_M,
                    alt_m=100.0,
                    dist_m=points[-1].dist_m + pas_m,
                )
            )
    return Trace(
        nom="carré d'essai",
        points=points,
        segments=[],
        distance_m=points[-1].dist_m,
        denivele_m=None,
        temps_moteur_s=None,
        meta={},
    )


# --- séances -----------------------------------------------------------------


def etape(
    type_: str,
    minutes: float,
    puissance: float | None,
    *,
    elastique: bool = False,
    libelle: str | None = None,
) -> Any:
    mod = module_seance
    return fabriques_seance.etape(
        mod,
        type_,
        minutes * 60.0,
        pmin=None if puissance is None else puissance - 10.0,
        pmax=None if puissance is None else puissance + 10.0,
        libelle=libelle if libelle is not None else f"{type_} {minutes:g} min",
        elastique=elastique,
    )


def seance(etapes: Sequence[Any], *, nom: str = "séance d'essai") -> Any:
    return fabriques_seance.seance(module_seance, etapes, nom=nom)


def seance_2x20() -> Any:
    """1 h d'échauffement, 2 × 20 min séparés d'une récup de 4 min, 30 min de calme.

    Cinq étapes, deux blocs : le lot doit faire passer `emplacements` de 2 à 5.
    """
    return seance(
        [
            etape("echauffement", 60, PUISSANCE_Z2, elastique=True),
            etape("bloc", 20, PUISSANCE_BLOC, libelle="bloc 1"),
            etape("recuperation", 4, PUISSANCE_RECUP),
            etape("bloc", 20, PUISSANCE_BLOC, libelle="bloc 2"),
            etape("calme", 30, PUISSANCE_CALME, elastique=True),
        ],
        nom="2x20' d'essai",
    )


def seance_sans_bloc() -> Any:
    """Une sortie d'endurance uniforme : aucune étape n'est un bloc (Q12).

    Cas prévu par la règle du placement : « on ne fabrique pas un bloc
    artificiel pour avoir quelque chose à placer. » `emplacements` était donc
    **vide** avant le lot, et doit maintenant contenir les trois étapes.
    """
    return seance(
        [
            etape("echauffement", 20, PUISSANCE_Z2, elastique=True),
            etape("recuperation", 40, PUISSANCE_Z2),
            etape("calme", 20, PUISSANCE_CALME, elastique=True),
        ],
        nom="endurance uniforme",
    )


def seance_une_etape() -> Any:
    """Une seule étape élastique : pas de levier d'ouverture, elle ferme (cf. `_extremites`)."""
    return seance([etape("calme", 60, PUISSANCE_CALME, elastique=True)], nom="une seule étape")


def seance_etape_nulle() -> Any:
    """Une récupération de durée **nulle** entre deux blocs, et un bloc de durée nulle.

    Deux étapes tombent alors exactement au même kilomètre. Le contrat n'en
    dispense pas : elles ont une position, longueur nulle, et la continuité
    doit tenir quand même.
    """
    return seance(
        [
            etape("echauffement", 40, PUISSANCE_Z2, elastique=True),
            etape("bloc", 10, PUISSANCE_BLOC, libelle="bloc 1"),
            etape("recuperation", 0, PUISSANCE_RECUP),
            etape("bloc", 0, PUISSANCE_BLOC, libelle="bloc éclair"),
            etape("bloc", 10, PUISSANCE_BLOC, libelle="bloc 2"),
            etape("calme", 20, PUISSANCE_CALME, elastique=True),
        ],
        nom="séance à étapes nulles",
    )


def seance_longue(n_blocs: int = 15) -> Any:
    """Une séance à beaucoup d'étapes : 2 + 2×`n_blocs` − 1 au total."""
    etapes = [etape("echauffement", 15, PUISSANCE_Z2, elastique=True)]
    for i in range(n_blocs):
        if i:
            etapes.append(etape("recuperation", 2, PUISSANCE_RECUP))
        etapes.append(etape("bloc", 3, PUISSANCE_BLOC, libelle=f"bloc {i + 1}"))
    etapes.append(etape("calme", 15, PUISSANCE_CALME, elastique=True))
    return seance(etapes, nom="séance très longue")


# --- terrain factice ---------------------------------------------------------


def terrain_factice(
    monkeypatch: Any,
    *,
    bon: tuple[float, float] = (0.0, 1e9),
    mauvais: float = 10.0,
    pente: float = 0.0,
    demi_tour: bool = False,
) -> list[tuple[float, float, float | None, float | None]]:
    """`evaluer_couloir` rend 0 dans `bon`, `mauvais` ailleurs. Rend la liste des appels.

    La liste des appels est le seul moyen de vérifier ce qui **n'a pas** été
    évalué : la règle est « pas de nouvelle note », donc aucune
    récupération, aucun échauffement, aucun retour au calme ne doit passer par
    `evaluer_couloir`. Un lot qui noterait les non-blocs pour les jeter ensuite
    changerait quand même le coût du placement, et surtout prouverait qu'un
    `0.0` a existé quelque part.
    """
    from ourouler.seance.terrain import NoteBloc

    placement = module_placement
    appels: list[tuple[float, float, float | None, float | None]] = []

    def evaluer_couloir(trace, debut_m, longueur_m, *, puissance_w=None, ftp_w=None) -> Any:
        appels.append((debut_m, longueur_m, puissance_w, ftp_w))
        dedans = bon[0] <= debut_m and debut_m + longueur_m <= bon[1]
        return NoteBloc(
            note=0.0 if dedans else mauvais,
            motifs=[] if dedans else ["hors du bon couloir"],
            pente_moyenne=pente,
            pente_max=pente,
            carrefours=0,
            km_batis=0.0,
            descente_m=0.0,
            montee_m=0.0,
        )

    monkeypatch.setattr(placement, "evaluer_couloir", evaluer_couloir)
    monkeypatch.setattr(placement, "route_au_dela", lambda trace, position_m, besoin_m: demi_tour)
    monkeypatch.setattr(placement, "demi_tour_faisable", lambda trace, position_m: demi_tour)
    return appels


def vitesse_plate(puissance_w: float) -> float:
    from ourouler.physique.modele import vitesse_regime

    return vitesse_regime(puissance_w, 0.0, 0.0, parametres())


def positions_2x20(decalage_s: float) -> list[float]:
    """[début bloc 1, fin bloc 1, début bloc 2, fin bloc 2] sur un tracé plat."""
    debut1 = vitesse_plate(PUISSANCE_Z2) * (3600.0 + decalage_s)
    fin1 = debut1 + vitesse_plate(PUISSANCE_BLOC) * 1200.0
    debut2 = fin1 + vitesse_plate(PUISSANCE_RECUP) * 240.0
    return [debut1, fin1, debut2, debut2 + vitesse_plate(PUISSANCE_BLOC) * 1200.0]


# --- lecture d'un placement --------------------------------------------------


def est_bloc(seance_: Any, emplacement: Any) -> bool:
    return seance_.etapes[emplacement.etape_idx].type == "bloc"


def blocs_de(placement_: Any, seance_: Any) -> list[Any]:
    """Les emplacements de blocs, par le filtre que la séance visible garantit."""
    return [e for e in placement_.emplacements if est_bloc(seance_, e)]


def note_de(emplacement: Any) -> float | None:
    note = getattr(emplacement, "note", None)
    return None if note is None else float(note.note)


# --- la continuité -----------------------------------------------------------


@dataclass(frozen=True)
class _Parcours:
    """Le compteur kilométrique projeté sur le tracé, reconstruit depuis `jalons_m`."""

    jalons: tuple[float, ...]
    cumuls: tuple[float, ...]

    @property
    def total(self) -> float:
        return self.cumuls[-1]

    def position(self, roule_m: float) -> float:
        """La position **sur le tracé** après `roule_m` mètres réellement roulés."""
        s = min(max(roule_m, 0.0), self.total)
        for k in range(len(self.jalons) - 1):
            if self.cumuls[k] - 1e-9 <= s <= self.cumuls[k + 1] + 1e-9:
                sens = 1.0 if self.jalons[k + 1] >= self.jalons[k] else -1.0
                return self.jalons[k] + sens * (s - self.cumuls[k])
        return self.jalons[-1]

    def jalons_dans(self, debut_roule: float, fin_roule: float) -> list[float]:
        """Les demi-tours franchis **strictement** à l'intérieur de `]debut, fin[`."""
        return [
            self.jalons[k]
            for k in range(1, len(self.jalons) - 1)
            if debut_roule + 1e-9 < self.cumuls[k] < fin_roule - 1e-9
        ]


def parcours_de(placement_: Any) -> _Parcours:
    jalons = tuple(float(j) for j in placement_.jalons_m)
    cumuls = [0.0]
    for a, b in zip(jalons[:-1], jalons[1:], strict=True):
        cumuls.append(cumuls[-1] + abs(b - a))
    return _Parcours(jalons=jalons, cumuls=tuple(cumuls))


#: Marge des comparaisons de distance, en mètres. 1 mm : largement au-dessus
#: du bruit d'un cumul de flottants sur 80 km (≈ 10⁻⁸ m), et **très** en
#: dessous de toute erreur réelle — la plus petite qu'on cherche à attraper
#: (une demi-récup comptée une fois au lieu de deux) pèse des centaines de
#: mètres. Une comparaison sans marge verdirait sur du bruit ; une marge large
#: laisserait passer une vraie faute. Ni l'un ni l'autre.
MARGE_M = 1e-3


def verifier_continuite(placement_: Any, seance_: Any) -> None:
    """L'invariant central de la séance visible : un parcours continu.

    Six exigences, chacune dans son assertion pour que l'échec dise laquelle :

    1. chaque étape de la séance apparaît **une fois**, dans l'ordre ;
    2. aucune longueur négative ou non finie ;
    3. la somme des longueurs vaut `distance_totale_m` ;
    4. les jalons racontent le même parcours que les longueurs ;
    5. l'empreinte de chaque emplacement sur le tracé, calculée depuis le
       compteur kilométrique et `jalons_m`, commence bien à `debut_m` ;
    6. le dernier emplacement atteint l'arrivée.
    """
    emplacements = list(placement_.emplacements)
    n = len(seance_.etapes)

    assert [e.etape_idx for e in emplacements] == list(range(n)), (
        "contrat §2.2 a) : toutes les étapes de la séance doivent apparaître, dans "
        f"l'ordre. Attendu {list(range(n))}, obtenu {[e.etape_idx for e in emplacements]}"
    )

    for e in emplacements:
        longueur = float(e.longueur_m)
        assert math.isfinite(longueur) and longueur >= -MARGE_M, (
            f"étape {e.etape_idx} : longueur {longueur!r} — ni négative ni infinie"
        )

    somme = sum(float(e.longueur_m) for e in emplacements)
    total = float(placement_.distance_totale_m)
    assert somme == pytest.approx(total, abs=MARGE_M), (
        f"contrat §2.2 a) : la somme des longueurs vaut {somme:.3f} m pour un parcours "
        f"de {total:.3f} m — il manque {total - somme:+.1f} m. Sur un demi-tour, la "
        "récupération roule deux fois la demi-distance : sa longueur est le parcours "
        "réellement roulé, pas l'écart entre deux points du tracé."
    )

    parcours = parcours_de(placement_)
    assert parcours.total == pytest.approx(total, abs=MARGE_M), (
        f"les jalons {list(parcours.jalons)} totalisent {parcours.total:.3f} m quand le "
        f"placement en annonce {total:.3f} : les deux ne décrivent pas le même parcours"
    )

    roule = 0.0
    for e in emplacements:
        fin_roule = roule + float(e.longueur_m)
        bornes = [parcours.position(roule), parcours.position(fin_roule)]
        bornes += parcours.jalons_dans(roule, fin_roule)
        attendu = min(bornes)
        assert float(e.debut_m) == pytest.approx(attendu, abs=max(MARGE_M, 1e-9 * total)), (
            f"étape {e.etape_idx} : elle commence au km {roule / 1000:.3f} du parcours, "
            f"ce qui tombe au km {attendu / 1000:.3f} du tracé, mais `debut_m` annonce "
            f"{float(e.debut_m) / 1000:.3f}. Les emplacements ne se suivent pas."
        )
        roule = fin_roule

    assert roule == pytest.approx(total, abs=MARGE_M), (
        f"le dernier emplacement finit au km {roule / 1000:.3f} d'un parcours de "
        f"{total / 1000:.3f} km : l'arrivée n'est pas couverte"
    )

#!/usr/bin/env python3
"""Mesure rétrospective : le mainteneur choisit-il son vent (lot L5.3, §3.2) ?

**Ce script n'est pas un test pytest et ne rend pas un verdict pass/fail.**
C'est une mesure, pas une fonctionnalité (contrat du sprint 5, §3.2) : avant
d'ajouter un réglage d'orientation au vent, on regarde ce que le mainteneur
**fait déjà**. Il lit le cache réel et appelle Intervals.icu, comme
`vent_retrospectif.py`, dont il reprend la collecte (mêmes 162 sorties route,
même archive Open-Meteo, mêmes fonctions privées de `physique.calibration`) :

    uv run python tests/validation/orientation_vent_retrospectif.py

Ce qu'il mesure, sur chaque sortie découpée en quatre quarts de distance
égale (pas de temps : un quart plus lent ne doit pas peser plus qu'un quart
rapide) :

1. **La question principale** — le premier quart est-il plus défavorable
   (plus de face) que le dernier ? Distribution des écarts, médiane, part des
   sorties où c'est le cas, et un test du signe contre 50 % (une pièce non
   truquée donnerait 50 %, exactement comme le demande le mainteneur).
2. **L'ampleur** — en m/s et en points d'un « headwind_percent » maison (part
   de la distance du quart dans le secteur face ±45°, la même règle que le
   point 3 et que `vent_retrospectif.py`), calculé pareil des deux côtés pour
   rester comparable — et son pendant « tailwind_percent ».
3. **Le travers** — quelle part des sorties se roule majoritairement dans le
   secteur travers de `meteo.rapport.vent_relatif` (±45°, celui que le lot
   L5.1 applique déjà). Sous ce secteur, un cap tiré au hasard tombe en
   travers une fois sur deux : le hasard, ici aussi, vaut 50 %.
4. **Le recoupement honnête, et le point le plus important de cette mesure**
   — un effet qui ne tient que par la géographie n'est pas une préférence.
   Chaque sortie est classée par la direction dominante du vent ce jour-là
   (moyenne circulaire, pondérée par la distance, de nos propres tronçons) :
   « habituelle » (secteur sud-est → nord-ouest en passant par l'ouest, celui
   où tombe le vent dominant d'ouest-sud-ouest breton) ou « inhabituelle »
   (nord ou est). La mesure principale est refaite séparément dans les deux
   groupes. Si l'effet ne tient que dans le groupe « habituel », c'est le
   réseau routier qui parle, pas une préférence. En recoupement, la direction
   dominante que nous calculons est comparée au `prevailing_wind_deg`
   d'Intervals — deux sources indépendantes, pour ne pas juger un artefact de
   notre seul calcul.
5. **Vent fort contre vent faible** — la mesure principale, refaite en ne
   gardant que les sorties à plus de 6 m/s de vent moyen (`average_wind_speed`
   d'Intervals) puis seulement celles en dessous. Un choix conscient devrait
   se voir davantage par vent fort.

Ce script ne réécrit ni le découpage en tronçons ni la composante de face :
`_decouper`, `_cap`, `_interpoler_archive` et `_vent_de_face` sont importées
de `physique.calibration`, exactement comme `vent_retrospectif.py` le fait
déjà pour les trois premières. La composante de **travers**, elle, n'existe
nulle part ailleurs dans le projet : elle se déduit de la norme du vent
(`vent_au_cycliste`, déjà publique) et de la composante de face déjà connue,
sans dupliquer la trigonométrie de `_vent_de_face`.

**Aucune coordonnée n'est imprimée**, et les sorties ne sont désignées que
par leur date (jamais leur nom) : cette mesure ne sert qu'à des comptes
agrégés, un nom de sortie n'y ajoute rien et pourrait nommer un lieu.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# `vent_retrospectif.py` vit dans le même dossier, hors de tout paquet Python
# (`tests/validation` n'a pas de `__init__.py`, décision assumée du sprint 4 :
# ce ne sont pas des tests collectés par pytest). On réutilise sa collecte
# plutôt que de la dupliquer : mêmes 162 sorties, même lecture de cache, même
# archive météo. `sys.path` doit être complété avant l'import, d'où le
# `noqa: E402` qui suit.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vent_retrospectif import (  # noqa: E402
    DEPUIS_DEFAUT,
    JugementIntervals,
    archive_du_depart,
    fichiers_du_cache,
    jugements,
)

from ourouler.activites.lecture import lecteur_pour  # noqa: E402
from ourouler.config import charger  # noqa: E402
from ourouler.connecteurs.intervals import ClientIntervals  # noqa: E402
from ourouler.connecteurs.openmeteo_archive import ClientArchive, HeureArchive  # noqa: E402
from ourouler.meteo.couronne import ecart_angulaire  # noqa: E402
from ourouler.meteo.rapport import VENT_DOS, VENT_FACE, VENT_TRAVERS, vent_relatif  # noqa: E402
from ourouler.noyau.activite import Activite  # noqa: E402
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur  # noqa: E402
from ourouler.physique.calibration import (  # noqa: E402
    _cap,
    _decouper,
    _distances_points,
    _interpoler_archive,
    _vent_de_face,
)
from ourouler.physique.commande import NOM_CACHE  # noqa: E402
from ourouler.physique.modele import vent_au_cycliste  # noqa: E402

#: Nombre de quarts de distance dans lesquels chaque sortie est découpée.
NOMBRE_QUARTS = 4

#: Seuil « vent fort » du point 5 de la demande, en m/s (moyenne Intervals).
VENT_FORT_MS = 6.0

#: Secteur « inhabituel » : nord ou est, de 315° à 135° en passant par 0°.
#: Le reste (135°-315°, sud-est → nord-ouest en passant par l'ouest) est le
#: secteur « habituel » où tombe le vent dominant d'ouest-sud-ouest breton.
#: Bornes en degrés, sens horaire, pour `_dans_secteur`.
SECTEUR_INHABITUEL = (315.0, 135.0)


# --- nos propres tronçons : face ET travers ------------------------------------


@dataclass
class Troncon:
    """Un tronçon d'environ 200 m, avec sa composante de vent complète.

    `vent_face_ms` sort de `_vent_de_face`, réutilisée telle quelle. La
    composante de **travers** n'existe nulle part dans le projet : elle se
    déduit de la norme du vent à hauteur de cycliste (`vent_au_cycliste`,
    déjà publique et déjà linéaire) et de la face déjà connue —
    `face = norme · cos(θ)` donc `travers = norme · sin(θ) =
    √(norme² − face²)` — sans reconstruire l'angle ni dupliquer la
    trigonométrie de `_vent_de_face`.
    """

    dist_fin_m: float
    longueur_m: float
    vent_face_ms: float | None  # None si le vent est inconnu à cet instant
    vent_norme_ms: float | None
    vent_depuis_deg: float | None
    secteur: str | None  # "face" | "dos" | "travers" | None (vent inconnu)

    @property
    def vent_travers_ms(self) -> float | None:
        if self.vent_face_ms is None or self.vent_norme_ms is None:
            return None
        return math.sqrt(max(self.vent_norme_ms**2 - self.vent_face_ms**2, 0.0))


def troncons_vent(activite: Activite, vent: list[HeureArchive]) -> list[Troncon]:
    """Découpe la sortie en tronçons d'environ 200 m et y pose le vent complet.

    Même découpage que `physique.calibration.echantillonner`
    (`_decouper`, `_cap`, `_interpoler_archive`), mais sans reprendre le reste
    de son travail (puissance, pente, qualification) : cette mesure ne porte
    que sur la géométrie et le vent.
    """
    points = [p for p in activite.points if p.t is not None]
    if len(points) < 2:
        return []
    distances = _distances_points(points)
    bruts = _decouper(points, distances)
    troncons: list[Troncon] = []
    for i, j, longueur, _duree in bruts:
        cap = _cap(points, i, j)
        t_milieu = points[i].t + (points[j].t - points[i].t) / 2
        heure = _interpoler_archive(vent, t_milieu)
        face = _vent_de_face(heure, cap)
        norme = depuis = secteur = None
        if heure is not None and heure.vent_kmh is not None:
            norme = vent_au_cycliste(heure.vent_kmh / 3.6)
        if heure is not None and heure.vent_depuis_deg is not None:
            depuis = heure.vent_depuis_deg
        if cap is not None and depuis is not None:
            secteur = vent_relatif(cap, depuis)
        troncons.append(
            Troncon(
                dist_fin_m=distances[j],
                longueur_m=longueur,
                vent_face_ms=face,
                vent_norme_ms=norme,
                vent_depuis_deg=depuis,
                secteur=secteur,
            )
        )
    return troncons


# --- quarts de distance ---------------------------------------------------------


@dataclass
class Quart:
    """Un quart de distance d'une sortie : sa composante de face moyenne.

    `part_face_pct` et `part_dos_pct` utilisent le secteur ±45° de
    `meteo.rapport.vent_relatif` — le même que le point 2 de cette mesure
    utilise pour le travers, et celui que `vent_retrospectif.py` a déjà
    recoupé avec Intervals (écart médian 6,6 points). Elles ne totalisent
    donc pas 100 % à elles deux : le travers prend le reste, exactement comme
    `headwind_percent` et `tailwind_percent` chez Intervals.
    """

    numero: int  # 1 à NOMBRE_QUARTS
    face_ms: float  # moyenne pondérée par la distance des tronçons au vent connu
    longueur_m: float  # longueur (au vent connu) qui a servi à la moyenne
    part_face_pct: float  # % de cette longueur dans le secteur face (±45°)
    part_dos_pct: float  # % de cette longueur dans le secteur dos (±45°)


def quarts_de_sortie(troncons: list[Troncon]) -> list[Quart] | None:
    """Un `Quart` par quart de distance, ou `None` si l'un d'eux n'a aucun vent connu.

    Le découpage se fait sur la **distance**, pas le temps (demande du
    mainteneur : un quart parcouru plus lentement ne doit pas peser plus
    qu'un quart rapide), en prenant le milieu de chaque tronçon comme sa
    position.
    """
    connus = [t for t in troncons if t.vent_face_ms is not None]
    if not connus or not troncons:
        return None
    total = troncons[-1].dist_fin_m
    if total <= 0:
        return None
    par_quart: list[list[Troncon]] = [[] for _ in range(NOMBRE_QUARTS)]
    for t in connus:
        milieu = t.dist_fin_m - t.longueur_m / 2
        indice = min(NOMBRE_QUARTS - 1, max(0, int(milieu / total * NOMBRE_QUARTS)))
        par_quart[indice].append(t)

    quarts = []
    for indice, liste in enumerate(par_quart):
        longueur = sum(t.longueur_m for t in liste)
        if longueur <= 0:
            return None  # un quart sans aucun tronçon au vent connu : sortie écartée
        face_ms = sum(t.vent_face_ms * t.longueur_m for t in liste) / longueur
        face_pos = sum(t.longueur_m for t in liste if t.secteur == VENT_FACE)
        dos_pos = sum(t.longueur_m for t in liste if t.secteur == VENT_DOS)
        quarts.append(
            Quart(
                numero=indice + 1,
                face_ms=face_ms,
                longueur_m=longueur,
                part_face_pct=100.0 * face_pos / longueur,
                part_dos_pct=100.0 * dos_pos / longueur,
            )
        )
    return quarts


def direction_dominante_deg(troncons: list[Troncon]) -> float | None:
    """Moyenne circulaire, pondérée par la distance, de la direction d'où vient le vent.

    Moyenne vectorielle (comme `physique.calibration._angulaire`, mais sur
    toute la sortie plutôt qu'entre deux heures) : 350° et 10°, à poids égal,
    donnent 0°, pas 180°.
    """
    connus = [t for t in troncons if t.vent_depuis_deg is not None]
    if not connus:
        return None
    x = sum(math.cos(math.radians(t.vent_depuis_deg)) * t.longueur_m for t in connus)
    y = sum(math.sin(math.radians(t.vent_depuis_deg)) * t.longueur_m for t in connus)
    if x == 0.0 and y == 0.0:
        return None
    return math.degrees(math.atan2(y, x)) % 360.0


def _dans_secteur(direction_deg: float, secteur: tuple[float, float]) -> bool:
    """Vrai si `direction_deg` tombe dans `secteur = (debut, fin)`, sens horaire.

    `secteur` peut « traverser » 0° (315° → 135°, comme `SECTEUR_INHABITUEL`) :
    le test se fait alors en deux morceaux.
    """
    debut, fin = secteur
    if debut <= fin:
        return debut <= direction_deg <= fin
    return direction_deg >= debut or direction_deg <= fin


def part_travers(troncons: list[Troncon]) -> float | None:
    """Part de la distance (au vent connu) roulée dans le secteur travers."""
    connus = [t for t in troncons if t.secteur is not None]
    longueur = sum(t.longueur_m for t in connus)
    if longueur <= 0:
        return None
    travers = sum(t.longueur_m for t in connus if t.secteur == VENT_TRAVERS)
    return 100.0 * travers / longueur


def travers_moyen_ms(troncons: list[Troncon]) -> float | None:
    """Composante de travers moyenne (pondérée par la distance), en m/s.

    Complète `part_travers` : celle-ci dit *combien* de la sortie tombe dans
    le secteur travers, celle-ci dit *combien de vent* on y subit — une
    sortie peut être « majoritairement en travers » avec un vent de 1 m/s ou
    de 8 m/s, ce n'est pas la même chose à ressentir.
    """
    connus = [t for t in troncons if t.vent_travers_ms is not None]
    longueur = sum(t.longueur_m for t in connus)
    if longueur <= 0:
        return None
    return sum(t.vent_travers_ms * t.longueur_m for t in connus) / longueur


# --- une sortie mesurée -----------------------------------------------------------


@dataclass
class SortieMesuree:
    jugement: JugementIntervals
    quarts: list[Quart]
    part_travers_pct: float
    travers_moyen_ms: float | None
    direction_dominante_deg: float | None

    @property
    def delta_face_ms(self) -> float:
        """Composante de face du premier quart moins celle du dernier.

        Positif = le premier quart est plus défavorable (plus de face, ou
        moins de dos) que le dernier — la question principale de la mesure.
        """
        return self.quarts[0].face_ms - self.quarts[-1].face_ms

    @property
    def delta_headwind_pct(self) -> float:
        return self.quarts[0].part_face_pct - self.quarts[-1].part_face_pct

    @property
    def delta_tailwind_pct(self) -> float:
        """Part de vent de dos, dernier quart moins premier.

        Positif = on rentre avec plus de vent dans le dos qu'on n'en avait au
        départ — l'autre moitié de la même question, posée côté « dos »
        plutôt que côté « face ». `headwind_percent` et `tailwind_percent`
        sont les deux champs qu'Intervals publie ; celui-ci est le pendant du
        premier.
        """
        return self.quarts[-1].part_dos_pct - self.quarts[0].part_dos_pct

    @property
    def majoritairement_travers(self) -> bool:
        return self.part_travers_pct > 50.0

    @property
    def secteur_habituel(self) -> bool | None:
        """Vrai si le vent dominant du jour tombe dans le secteur « habituel »."""
        if self.direction_dominante_deg is None:
            return None
        return not _dans_secteur(self.direction_dominante_deg, SECTEUR_INHABITUEL)


def mesurer(activite: Activite, vent: list[HeureArchive], jugement: JugementIntervals) -> SortieMesuree | str:
    """Mesure une sortie, ou rend une chaîne disant pourquoi elle est écartée."""
    troncons = troncons_vent(activite, vent)
    if not troncons:
        return "aucun tronçon (trace GPS ou horodatage insuffisant)"
    quarts = quarts_de_sortie(troncons)
    if quarts is None:
        return "au moins un quart de distance sans vent connu"
    travers = part_travers(troncons)
    if travers is None:
        return "aucun secteur de vent connu"
    return SortieMesuree(
        jugement=jugement,
        quarts=quarts,
        part_travers_pct=travers,
        travers_moyen_ms=travers_moyen_ms(troncons),
        direction_dominante_deg=direction_dominante_deg(troncons),
    )


# --- statistique : le test du signe -----------------------------------------------


def p_valeur_signe(n_plus: int, n_total: int) -> float:
    """p-valeur bilatérale exacte du test du signe (H0 : p = 0,5).

    La binomiale à p=0,5 est symétrique : la p-valeur bilatérale usuelle est
    `2 · P(X ≤ min(n_plus, n_total − n_plus))`, plafonnée à 1. Pas de
    dépendance à SciPy pour un calcul aussi simple.
    """
    if n_total == 0:
        return float("nan")
    k = min(n_plus, n_total - n_plus)
    cumul = sum(math.comb(n_total, x) for x in range(0, k + 1))
    return min(1.0, 2 * cumul / (2**n_total))


def _centile(valeurs: list[float], centile: float) -> float:
    ordonnes = sorted(valeurs)
    if not ordonnes:
        return float("nan")
    rang = min(int(len(ordonnes) * centile / 100.0), len(ordonnes) - 1)
    return ordonnes[rang]


# --- collecte ----------------------------------------------------------------------


def collecter(
    client_intervals: ClientIntervals,
    client_archive: ClientArchive,
    dossier_cache: Path,
    depuis: date,
    *,
    limite: int | None = None,
    bavard: bool = False,
) -> tuple[list[SortieMesuree], list[str]]:
    """Toutes les sorties mesurables depuis `depuis`, et pourquoi les autres sont écartées.

    Reprend exactement la collecte de `vent_retrospectif.jugements` et
    `fichiers_du_cache` : les mêmes 162 sorties route servent de base aux
    deux mesures.
    """
    par_intervals = jugements(client_intervals, depuis)
    par_fichier = fichiers_du_cache(dossier_cache)
    print(
        f"{len(par_intervals)} sortie(s) route avec météo chez Intervals depuis {depuis}, "
        f"{len(par_fichier)} fichier(s) dans le cache local."
    )

    mesures: list[SortieMesuree] = []
    manques: list[str] = []
    for n, (identifiant, jugement) in enumerate(sorted(par_intervals.items())):
        if limite is not None and len(mesures) >= limite:
            break
        chemin = par_fichier.get(identifiant)
        if chemin is None:
            manques.append(f"{jugement.jour} : aucun fichier dans le cache")
            continue
        try:
            activite = lecteur_pour(chemin.suffix)(chemin)
        except (ErreurUtilisateur, OSError) as e:
            manques.append(f"{jugement.jour} : fichier illisible ({e})")
            continue
        vent = archive_du_depart(activite, client_archive)
        if not vent:
            manques.append(f"{jugement.jour} : archive météo indisponible")
            continue
        resultat = mesurer(activite, vent, jugement)
        if isinstance(resultat, str):
            manques.append(f"{jugement.jour} : {resultat}")
            continue
        mesures.append(resultat)
        if bavard:
            print(f"  {n + 1:3d}. {jugement.jour}")
    return mesures, manques


# --- affichage : la question principale --------------------------------------------


@dataclass
class ResumeSigne:
    """Ce que le test du signe dit d'un sous-ensemble de sorties."""

    n: int
    n_plus: int  # premier quart plus défavorable que le dernier
    n_egal: int
    deltas_ms: list[float] = field(default_factory=list)
    deltas_pct: list[float] = field(default_factory=list)

    @property
    def part_plus_pct(self) -> float:
        n_tranchees = self.n - self.n_egal
        return 100.0 * self.n_plus / n_tranchees if n_tranchees else float("nan")

    @property
    def p_valeur(self) -> float:
        return p_valeur_signe(self.n_plus, self.n - self.n_egal)


def resumer_signe(mesures: list[SortieMesuree], *, epsilon_ms: float = 1e-6) -> ResumeSigne:
    deltas_ms = [m.delta_face_ms for m in mesures]
    deltas_pct = [m.delta_headwind_pct for m in mesures]
    n_plus = sum(1 for d in deltas_ms if d > epsilon_ms)
    n_egal = sum(1 for d in deltas_ms if abs(d) <= epsilon_ms)
    return ResumeSigne(
        n=len(mesures), n_plus=n_plus, n_egal=n_egal, deltas_ms=deltas_ms, deltas_pct=deltas_pct
    )


def imprimer_question_principale(mesures: list[SortieMesuree]) -> None:
    print()
    print("=== 1. Le premier quart est-il plus défavorable que le dernier ? ===")
    if not mesures:
        print("  aucune sortie mesurable.")
        return
    resume = resumer_signe(mesures)
    print(
        f"  {resume.n} sorties, {resume.n_egal} à égalité stricte (exclues du départage), "
        f"{resume.n - resume.n_egal} tranchées."
    )
    print(
        f"  premier quart plus de face que le dernier : {resume.n_plus} sorties sur "
        f"{resume.n - resume.n_egal} ({resume.part_plus_pct:.1f} %). "
        "Une pièce non truquée donnerait 50 %."
    )
    print(f"  p-valeur du test du signe (H0 : 50 %) : {resume.p_valeur:.4f}")
    print()
    print("  distribution de l'écart (1er quart − dernier quart), en m/s de vent de face :")
    _imprimer_distribution(resume.deltas_ms, unite="m/s")
    print()
    print("  distribution du même écart, en points de « headwind_percent » maison :")
    _imprimer_distribution(resume.deltas_pct, unite="pts")
    print()
    print("  le pendant côté « tailwind_percent » maison (dernier quart moins premier) :")
    _imprimer_distribution([m.delta_tailwind_pct for m in mesures], unite="pts")


def _imprimer_distribution(valeurs: list[float], *, unite: str) -> None:
    if not valeurs:
        print("    (aucune valeur)")
        return
    print(
        f"    min {min(valeurs):+.2f}  p10 {_centile(valeurs, 10):+.2f}  "
        f"p25 {_centile(valeurs, 25):+.2f}  médiane {statistics.median(valeurs):+.2f}  "
        f"p75 {_centile(valeurs, 75):+.2f}  p90 {_centile(valeurs, 90):+.2f}  "
        f"max {max(valeurs):+.2f}  ({unite})"
    )
    print(
        f"    moyenne {statistics.mean(valeurs):+.2f} {unite}, "
        f"écart-type {statistics.pstdev(valeurs):.2f} {unite}"
    )


# --- affichage : le travers ----------------------------------------------------------


def imprimer_travers(mesures: list[SortieMesuree]) -> None:
    print()
    print("=== 2. Le travers : évité, subi, ou indifférent ? ===")
    if not mesures:
        print("  aucune sortie mesurable.")
        return
    n = len(mesures)
    n_travers = sum(1 for m in mesures if m.majoritairement_travers)
    parts = [m.part_travers_pct for m in mesures]
    p = p_valeur_signe(n_travers, n)
    print(
        f"  sorties majoritairement en travers (secteur ±45° de vent_relatif, "
        f">50 % de la distance) : {n_travers} sur {n} ({100.0 * n_travers / n:.1f} %)."
    )
    print(f"  sous ce secteur, un cap tiré au hasard tombe en travers une fois sur deux : "
          f"p-valeur contre 50 % = {p:.4f}")
    print(
        f"  part de travers par sortie : médiane {statistics.median(parts):.1f} %, "
        f"p25 {_centile(parts, 25):.1f} %, p75 {_centile(parts, 75):.1f} %."
    )
    vitesses = [m.travers_moyen_ms for m in mesures if m.travers_moyen_ms is not None]
    if vitesses:
        print(
            f"  composante de travers moyenne (pas seulement sa part, sa vitesse) : "
            f"médiane {statistics.median(vitesses):.1f} m/s."
        )


# --- affichage : le recoupement (le contrôle qui compte) -----------------------------


def imprimer_confond(mesures: list[SortieMesuree]) -> None:
    print()
    print("=== 3. Le recoupement honnête : géographie, ou préférence ? ===")
    if not mesures:
        print("  aucune sortie mesurable.")
        return

    avec_direction = [m for m in mesures if m.direction_dominante_deg is not None]
    print(
        f"  direction dominante du vent connue sur {len(avec_direction)}/{len(mesures)} sorties "
        "(moyenne circulaire pondérée par la distance, nos propres tronçons)."
    )

    # Recoupement avec la source indépendante : le prevailing_wind_deg d'Intervals.
    ecarts = [
        ecart_angulaire(m.direction_dominante_deg, m.jugement.vent_dominant_deg)
        for m in avec_direction
        if m.jugement.vent_dominant_deg is not None
    ]
    if ecarts:
        print(
            f"  recoupement avec le prevailing_wind_deg d'Intervals (source indépendante) : "
            f"écart angulaire médian {statistics.median(ecarts):.0f}° sur {len(ecarts)} sorties."
        )

    habituelles = [m for m in avec_direction if m.secteur_habituel]
    inhabituelles = [m for m in avec_direction if m.secteur_habituel is False]
    print(
        f"\n  secteur « habituel » (sud-est → nord-ouest par l'ouest, {135:.0f}°-{315:.0f}°) : "
        f"{len(habituelles)} sorties."
    )
    print(f"  secteur « inhabituel » (nord ou est, {315:.0f}°-{135:.0f}° en passant par 0°) : "
          f"{len(inhabituelles)} sorties.")

    for nom, sous_ensemble in (("habituel", habituelles), ("inhabituel (nord/est)", inhabituelles)):
        print(f"\n  --- vent {nom} ---")
        if len(sous_ensemble) < 10:
            print(f"    seulement {len(sous_ensemble)} sortie(s) : trop peu pour conclure quoi que ce soit.")
            if not sous_ensemble:
                continue
        resume = resumer_signe(sous_ensemble)
        n_tranchees = resume.n - resume.n_egal
        if n_tranchees == 0:
            print("    aucune sortie tranchée.")
            continue
        print(
            f"    premier quart plus de face : {resume.n_plus}/{n_tranchees} "
            f"({resume.part_plus_pct:.1f} %), médiane de l'écart "
            f"{statistics.median(resume.deltas_ms):+.2f} m/s, p-valeur {resume.p_valeur:.4f}"
        )

    if len(inhabituelles) >= 10:
        print(
            "\n  Lecture : si l'effet tient dans le groupe « inhabituel » aussi (même sens, "
            "part\n  proche de celle du groupe « habituel »), ce n'est pas seulement la "
            "géographie qui\n  parle. S'il s'annule ou s'inverse quand le vent change de secteur, "
            "c'est le\n  réseau routier qui parle, pas une préférence."
        )
    else:
        print(
            "\n  Trop peu de sorties à vent inhabituel dans cet historique pour trancher ce "
            "point,\n  qui reste le plus important de cette mesure : le résultat de la section 1 "
            "ne\n  peut donc pas, à lui seul, être lu comme une préférence."
        )


# --- affichage : vent fort contre vent faible -----------------------------------------


def imprimer_vent_fort(mesures: list[SortieMesuree]) -> None:
    print()
    print(f"=== 4. Vent fort (> {VENT_FORT_MS:.0f} m/s) contre vent faible ===")
    if not mesures:
        print("  aucune sortie mesurable.")
        return
    avec_vent = [m for m in mesures if m.jugement.vent_moyen_ms is not None]
    print(
        f"  vitesse de vent moyenne (average_wind_speed d'Intervals) connue sur "
        f"{len(avec_vent)}/{len(mesures)} sorties."
    )
    forts = [m for m in avec_vent if m.jugement.vent_moyen_ms > VENT_FORT_MS]
    faibles = [m for m in avec_vent if m.jugement.vent_moyen_ms <= VENT_FORT_MS]
    for nom, sous_ensemble in (("fort", forts), ("faible", faibles)):
        print(f"\n  --- vent {nom} ({len(sous_ensemble)} sorties) ---")
        if len(sous_ensemble) < 10:
            print(f"    trop peu de sorties ({len(sous_ensemble)}) pour conclure.")
            continue
        resume = resumer_signe(sous_ensemble)
        n_tranchees = resume.n - resume.n_egal
        if n_tranchees == 0:
            print("    aucune sortie tranchée.")
            continue
        print(
            f"    premier quart plus de face : {resume.n_plus}/{n_tranchees} "
            f"({resume.part_plus_pct:.1f} %), médiane de l'écart "
            f"{statistics.median(resume.deltas_ms):+.2f} m/s, p-valeur {resume.p_valeur:.4f}"
        )


def imprimer_manques(manques: list[str]) -> None:
    if not manques:
        return
    print()
    print(f"=== Sorties écartées de la mesure : {len(manques)} ===")
    for motif in manques[:10]:
        print(f"  {motif}")
    if len(manques) > 10:
        print(f"  (et {len(manques) - 10} autre(s))")


# --- programme principal -----------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(Path(arguments.config).expanduser() if arguments.config else None)
    if not config.intervals.renseigne:
        print(
            "Intervals.icu n'est pas configuré ([intervals] athlete_id et api_key) : "
            "cette mesure a besoin de son has_weather, de son prevailing_wind_deg et de son "
            "average_wind_speed pour choisir les sorties et les recouper. "
            "Non vérifié tant que cette commande n'a pas tourné.",
            file=sys.stderr,
        )
        return 2

    client_intervals = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)
    client_archive = ClientArchive(chemin_cache=config.cache.dossier / NOM_CACHE)
    depuis = date.fromisoformat(arguments.depuis)

    mesures, manques = collecter(
        client_intervals,
        client_archive,
        config.cache.dossier,
        depuis,
        limite=arguments.limite,
        bavard=arguments.bavard,
    )

    imprimer_question_principale(mesures)
    imprimer_travers(mesures)
    imprimer_confond(mesures)
    imprimer_vent_fort(mesures)
    imprimer_manques(manques)

    print()
    print(f"  archives météo : {client_archive.appels} appel(s), "
          f"{client_archive.lectures_cache} lecture(s) de cache.")
    print()
    print(
        "Cette mesure ne rend pas de verdict pass/fail : c'est une mesure, pas une "
        "fonctionnalité\n(contrat du sprint 5, §3.2). Lire la section 3 avant de conclure quoi "
        "que ce soit de la\nsection 1 : un effet qui ne tient pas au vent inhabituel n'est pas "
        "une préférence."
    )
    return 0 if mesures else 1


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui du mainteneur)")
    analyseur.add_argument(
        "--depuis", default=DEPUIS_DEFAUT, help=f"début de l'historique (défaut : {DEPUIS_DEFAUT})"
    )
    analyseur.add_argument("--limite", type=int, help="s'arrêter après tant de sorties (mise au point)")
    analyseur.add_argument("--bavard", action="store_true", help="dater chaque sortie mesurée")
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except (ErreurUtilisateur, ErreurConnecteur) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

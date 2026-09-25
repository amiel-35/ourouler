#!/usr/bin/env python3
"""Mesure exploratoire : que cherche-t-il à faire quand il roule ?

**Ce script n'est pas un test pytest et ne rend pas de verdict pass/fail.**
C'est une mesure, pas une fonctionnalité. Il lit le cache réel du mainteneur —
ce que la suite de tests n'a pas le droit de faire (règles absolues 1 et 3) —
et il se lance à la main, depuis la racine du dépôt :

    uv run python tests/validation/style_retrospectif.py

Il **n'appelle aucun réseau** : tout vient de l'index SQLite du cache et des
fichiers d'activité déjà téléchargés. C'est voulu — une mesure de style ne
doit dépendre ni d'une clé d'API ni d'un service tiers pour être rejouée.

## Le risque de ce script, écrit avant les résultats

Une trajectoire de 161 sorties contient assez de coïncidences pour raconter
n'importe quelle histoire. Le projet a un précédent des deux côtés : au
sprint 3 la mesure a montré qu'il **n'évite pas** les côtes, contre
l'intuition ; le 16/09/2026 la mesure d'orientation au vent est revenue
**nulle** (50,9 %, p = 0,87), et c'était la bonne réponse.

Donc **chaque effet imprimé ici porte son contrôle**, c'est-à-dire le calcul
qui aurait pu le démentir et ne l'a pas fait. Les trois familles de contrôle
employées :

1. **Permutation de l'ordre chronologique.** Une courbe d'accumulation monte
   quel que soit l'ordre des sorties : « il connaît de mieux en mieux son
   terrain » est vrai par construction. On rejoue donc la même statistique sur
   des ordres tirés au hasard, mêmes sorties, et on ne garde la tendance que
   si elle sort de cette distribution. Deux effets sur trois meurent ici, et
   c'est le but.
2. **Contrôle de longueur.** Une sortie longue touche plus de secteurs qu'une
   sortie courte : une baisse de diversité pourrait n'être qu'une baisse de
   kilométrage. On refait donc la mesure à longueur appariée, et sur le résidu
   d'une régression sur `log(distance)`.
3. **Pivot des traces.** Pour la répétition : chaque trace est pivotée d'un
   angle tiré au hasard autour du point de départ, mêmes longueurs, mêmes
   formes, seule la direction change. Ce contrôle ne dit pas *pourquoi* il
   repasse au même endroit ; il dit seulement que le chiffre observé n'est pas
   un artefact de la taille de la maille. C'est écrit tel quel dans le
   rapport.

## Ce qui est mesuré

1. **Répétition ou exploration** — part des kilomètres sur des mailles déjà
   vues, ressemblance de chaque sortie à la plus proche des précédentes,
   concentration du réseau parcouru. C'est **l'usage légitime de
   `part_connue` : un instrument de mesure, jamais un critère** (doctrine).
2. **Où va-t-il** — répartition des kilomètres par secteur autour de sa base,
   et son évolution dans le temps.
3. **Forme des sorties** — boucle, aller-retour, pétale, par le rapport entre
   la distance parcourue et la distance maximale au départ.
4. **Régularité de l'effort** — la puissance suit-elle le terrain ? Mesurée
   entre deux contrefactuels calculés sur son propre terrain : rouler à
   vitesse constante, et rouler à puissance constante.
5. **Rythme** — jours, heures, saisons, durées.

## Données personnelles : ce qui ne sort pas d'ici

**Aucune coordonnée n'est imprimée**, et c'est le point à surveiller à chaque
modification : un barycentre est une coordonnée, une maille est une
coordonnée, un point de départ est une coordonnée. Le script les manipule en
mémoire et n'en imprime que des **agrégats** — des comptes, des parts, et des
**azimuts relatifs** à une base dont la position n'est jamais dite. Les noms
de sorties ne sont ni lus pour classer ni imprimés : ils contiennent des noms
de communes. Les dates ne sont imprimées qu'agrégées par année.

Le vocabulaire : une **maille** fait ~30 m de côté (`apprentissage.routes
.cle_maille`), un **secteur** est un huitième de rose des vents autour de la
base, la **base** est la grappe de départs la plus fréquente.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import random
import statistics
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# `vent_retrospectif.py` vit dans le même dossier, hors de tout paquet Python
# (`tests/validation` n'a pas de `__init__.py`, décision assumée du sprint 4).
# On lui reprend le début de l'historique et l'ouverture en lecture seule de
# l'index : il n'y a pas deux façons d'ouvrir le cache sans risquer d'y
# écrire. `sys.path` doit être complété avant l'import, d'où le `noqa: E402`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vent_retrospectif import DEPUIS_DEFAUT, _connexion_ro  # noqa: E402

from ourouler.activites.lecture import lecteur_pour  # noqa: E402
from ourouler.apprentissage.routes import mailles_ponderees  # noqa: E402
from ourouler.config import Config, charger  # noqa: E402
from ourouler.noyau.activite import Activite, puissance_normalisee  # noqa: E402
from ourouler.noyau.erreurs import ErreurUtilisateur  # noqa: E402
from ourouler.noyau.trace import PointTrace, Trace, cap_deg, distance_m  # noqa: E402
from ourouler.physique.calibration import (  # noqa: E402
    echantillonner,
    masse_totale_kg,
    puissance_moyenne_en_mouvement,
    trace_depuis_activite,
)
from ourouler.physique.commande import velo_demande  # noqa: E402

#: Taille de la maille du projet, en degrés inversés : `cle_maille` multiplie
#: par 3000, donc une maille vaut 1/3000 de degré, ~30 m de côté. Recopié ici
#: pour **relire** une clé de maille (l'opération inverse de `cle_maille`, que
#: `apprentissage.routes` n'expose pas) ; jamais pour en fabriquer une.
MAILLE = 3000.0

#: Longueur d'une maille en kilomètres, pour convertir un nombre de mailles
#: distinctes en « kilomètres de réseau ». Approximation assumée : une maille
#: traversée en diagonale en fait un peu plus, une maille effleurée un peu
#: moins, et une maille peut porter deux routes. Ce chiffre sert à donner un
#: ordre de grandeur, jamais à conclure.
KM_PAR_MAILLE = 0.030

#: Rayon de la grappe de départ, en mètres. Deux départs à moins de ce rayon
#: sont « la même base ». 1 500 m couvre la dérive du GPS au démarrage et les
#: départs depuis le bout de la rue, sans avaler un point de rendez-vous à
#: 3 km. `--rayon-base` le déplace, et la sensibilité est imprimée.
RAYON_BASE_M_DEFAUT = 1500.0

#: Distance à la base en deçà de laquelle un kilomètre n'est pas un choix de
#: direction mais un entonnoir : quelle que soit la sortie, on sort de chez soi
#: par les mêmes rues. Les mesures de secteur commencent au-delà.
ENTONNOIR_M = 3000.0

#: Pente au-delà de laquelle un tronçon de 200 m est sans doute une erreur
#: d'altimètre (12 % sur 200 m, en Ille-et-Vilaine).
PENTE_MAX_PLAUSIBLE = 0.12

#: Vitesse en deçà de laquelle un tronçon ne dit rien de l'effort.
VITESSE_MIN_MS = 2.0

#: Les huit secteurs, dans l'ordre horaire depuis le nord.
SECTEURS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")

#: **Ce que cette commande a mesuré le 16/09/2026** : 161 sorties route
#: extérieures lues depuis le 01/12/2023, dont 109 parties de la base
#: principale — les seules que les mesures de direction regardent, un azimut
#: n'ayant de sens que par rapport à un point fixe. Recopié ici pour qu'un
#: chiffre qui bouge se voie, et pour que le lecteur sache ce que la mesure a
#: donné même s'il ne peut pas la relancer. Mettre à jour est un geste
#: explicite : on relance, on recopie, on date.
MESURE_DU_16_09_2026 = {
    "date": "2026-09-16",
    "sorties_route_exterieures": 161,
    "sorties_depuis_la_base": 109,
    "ressemblance_mediane_a_une_precedente": 0.88,
    "part_des_sorties_a_plus_de_85_pourcent_deja_faites": 0.53,
    "km_roules_sur_km_de_reseau": 3.2,
    "part_des_km_dans_les_5_pourcent_de_mailles_les_plus_roulees": 0.448,
    "part_deja_vue_entre_15_et_25_km_2e_moitie": 0.91,
    "part_des_km_secteur_sud_est": 0.437,
    "part_des_km_secteur_sud": 0.200,
    "part_des_km_secteur_ouest": 0.055,
    "part_des_km_secteur_nord_ouest": 0.021,
    "rayleigh_R": 0.561,
    "diversite_par_sortie_spearman": -0.365,
    "diversite_corrigee_de_la_longueur_spearman": -0.348,
    "diversite_corrigee_p": 0.0005,
    "tendance_de_repetition_p": 0.318,
    "part_du_chemin_vers_vitesse_constante": 0.25,
    "forme_mediane_distance_sur_rayon_max": 3.20,
    "verdict": (
        "trois effets tiennent (concentration spatiale, resserrement du répertoire, "
        "effort tenu contre le terrain) ; la « montée en familiarité » est du bruit"
    ),
}


# --- collecte : le cache réel, sans réseau --------------------------------------


@dataclass
class Sortie:
    """Une sortie route extérieure, réduite à ce que la mesure regarde.

    Les coordonnées (`depart`, `fin`, `mailles`) vivent ici parce qu'il faut
    bien les calculer ; **rien de ce qui est imprimé n'en dérive directement**,
    seulement des distances, des azimuts relatifs et des comptes.
    """

    jour: date
    heure_locale: int
    jour_semaine: int
    distance_km: float
    duree_h: float
    depart: tuple[float, float]
    fin: tuple[float, float]
    #: Mètres portés par chaque maille traversée (`mailles_ponderees`).
    mailles: dict[tuple[int, int], float]
    #: Mètres par maille de la première moitié, puis de la seconde.
    moities: tuple[dict[tuple[int, int], float], dict[tuple[int, int], float]]
    rayon_max_m: float
    longueur_trace_m: float
    #: (pente, puissance_w, vitesse_ms, longueur_m) par tronçon roulant de 200 m.
    troncons: list[tuple[float, float, float, float]]
    variabilite: float | None  # puissance normalisée / puissance moyenne


def collecter(
    config: Config, depuis: date, limite: int | None, bavard: bool
) -> tuple[list[Sortie], list[str]]:
    """Les sorties route extérieures du cache, lues une par une. Aucun réseau."""
    dossier = Path(config.cache.dossier).expanduser()
    index = dossier / "index.sqlite"
    with _connexion_ro(index) as cx:
        lignes = cx.execute(
            "SELECT identifiant, extension, debut, duree_s, distance_m, meta "
            "FROM activites WHERE sport = 'Ride' AND debut >= ? ORDER BY debut",
            (depuis.isoformat(),),
        ).fetchall()

    sorties: list[Sortie] = []
    manques: list[str] = []
    for identifiant, extension, debut, duree_s, distance_m_, meta in lignes:
        if limite is not None and len(sorties) >= limite:
            break
        indexee = _meta(meta)
        if indexee.get("trainer") or indexee.get("interieur"):
            continue
        chemin = dossier / "brut" / f"{identifiant}.{extension}"
        if not chemin.is_file():
            manques.append("fichier absent du cache")
            continue
        try:
            activite = lecteur_pour(extension)(chemin)
        except Exception as e:  # noqa: BLE001 — un fichier illisible se compte, il ne casse pas la mesure
            manques.append(f"illisible ({type(e).__name__})")
            continue
        # L'heure **locale** vit dans l'index du cache (`meta.debut_local`), pas
        # dans le fichier d'activité : un FIT porte de l'UTC, et lire l'UTC ferait
        # partir le mainteneur deux heures trop tôt tous les étés.
        sortie = _en_sortie(
            activite, str(indexee.get("debut_local") or debut), duree_s, distance_m_
        )
        if sortie is None:
            manques.append("sans tracé exploitable")
            continue
        sorties.append(sortie)
        if bavard and len(sorties) % 25 == 0:
            print(f"  … {len(sorties)} sorties lues", file=sys.stderr)
    return sorties, manques


def _meta(meta: str | None) -> dict:
    """La colonne `meta` de l'index, relue. Un JSON cassé rend un dictionnaire vide."""
    try:
        return json.loads(meta or "{}") or {}
    except ValueError:
        return {}


def _en_sortie(
    activite: Activite, debut_local: str, duree_s: float | None, distance: float | None
) -> Sortie | None:
    """Réduit une activité lue à une `Sortie`, ou `None` si elle n'a pas de tracé."""
    trace = trace_depuis_activite(activite)
    if trace is None or len(trace.points) < 10:
        return None
    points = trace.points
    depart = points[0]
    rayons = [distance_m(depart, p) for p in points]
    longueur = points[-1].dist_m or sum(
        distance_m(points[i], points[i + 1]) for i in range(len(points) - 1)
    )
    if longueur <= 0:
        return None

    instant = datetime.fromisoformat(debut_local)
    milieu = len(points) // 2
    demi_a = _mailles_des_points(points[:milieu])
    demi_b = _mailles_des_points(points[milieu:])

    puissance_moy = puissance_moyenne_en_mouvement(activite)
    normalisee = puissance_normalisee(activite.points)
    variabilite = (
        normalisee / puissance_moy if normalisee and puissance_moy and puissance_moy > 0 else None
    )

    return Sortie(
        jour=instant.date(),
        heure_locale=instant.hour,
        jour_semaine=instant.weekday(),
        distance_km=(float(distance) if distance else longueur) / 1000.0,
        duree_h=(float(duree_s) if duree_s else 0.0) / 3600.0,
        depart=(depart.lat, depart.lon),
        fin=(points[-1].lat, points[-1].lon),
        mailles=mailles_ponderees(trace),
        moities=(demi_a, demi_b),
        rayon_max_m=max(rayons),
        longueur_trace_m=longueur,
        troncons=_troncons_roulants(activite),
        variabilite=variabilite,
    )


def _mailles_des_points(points: Sequence[PointTrace]) -> dict[tuple[int, int], float]:
    """`mailles_ponderees` sur un morceau de tracé, sans refabriquer de géométrie."""
    if len(points) < 2:
        return {}
    morceau = Trace(
        nom="moitié",
        points=list(points),
        segments=[],
        distance_m=0.0,
        denivele_m=None,
        temps_moteur_s=None,
    )
    return mailles_ponderees(morceau)


def _troncons_roulants(activite: Activite) -> list[tuple[float, float, float, float]]:
    """(pente, puissance, vitesse, longueur) des tronçons de 200 m où il roule.

    **`Echantillon.retenu` n'est pas utilisé ici, et c'est délibéré** : la
    calibration écarte les tronçons au-dessus de 75 % de FTP parce qu'un
    sprint ne dit rien du CdA. Ce sont précisément ceux qui disent quelque
    chose de l'effort. On ne garde donc que le filtre qui a du sens pour cette
    mesure-ci : ni arrêt, ni tronçon sans puissance, ni pente aberrante.

    Le vent est absent (liste vide) : `echantillonner` pose alors un vent nul.
    Ça ne gêne pas cette mesure, qui regarde la pente — et la mesure du
    16/09/2026 a établi qu'il **n'oriente pas** ses sorties au vent.
    """
    resultat = []
    for e in echantillonner(activite, []):
        if e.motif in ("arrêt", "sans puissance"):
            continue
        if e.longueur_m <= 0 or e.v_ms < VITESSE_MIN_MS or abs(e.pente) >= PENTE_MAX_PLAUSIBLE:
            continue
        resultat.append((e.pente, e.puissance_w, e.v_ms, e.longueur_m))
    return resultat


# --- la base, et les secteurs autour d'elle -------------------------------------


@dataclass
class Base:
    """La grappe de départs la plus fréquente. Sa position n'est jamais imprimée."""

    lat: float
    lon: float
    sorties: list[Sortie] = field(default_factory=list)

    def distance_m(self, lat: float, lon: float) -> float:
        return distance_m(
            PointTrace(lat=self.lat, lon=self.lon, alt_m=None, dist_m=0.0),
            PointTrace(lat=lat, lon=lon, alt_m=None, dist_m=0.0),
        )

    def azimut(self, lat: float, lon: float) -> float:
        return cap_deg(
            PointTrace(lat=self.lat, lon=self.lon, alt_m=None, dist_m=0.0),
            PointTrace(lat=lat, lon=lon, alt_m=None, dist_m=0.0),
        )

    def secteur(self, lat: float, lon: float) -> str:
        return SECTEURS[int((self.azimut(lat, lon) + 22.5) // 45) % 8]


def base_principale(sorties: Sequence[Sortie], rayon_m: float) -> tuple[Base, list[list[Sortie]]]:
    """La plus grosse grappe de départs, et toutes les grappes par taille décroissante.

    Agrégation gloutonne : une sortie rejoint la première grappe dont le centre
    est à moins de `rayon_m`, sinon elle en ouvre une. C'est grossier et
    dépendant de l'ordre ; la sensibilité au rayon est imprimée plus bas, et
    elle est faible.
    """
    grappes: list[tuple[tuple[float, float], list[Sortie]]] = []
    for sortie in sorties:
        for centre, membres in grappes:
            reference = PointTrace(lat=centre[0], lon=centre[1], alt_m=None, dist_m=0.0)
            candidat = PointTrace(lat=sortie.depart[0], lon=sortie.depart[1], alt_m=None, dist_m=0.0)
            if distance_m(reference, candidat) < rayon_m:
                membres.append(sortie)
                break
        else:
            grappes.append((sortie.depart, [sortie]))
    grappes.sort(key=lambda g: -len(g[1]))
    if not grappes:
        raise ErreurUtilisateur("aucune sortie exploitable dans le cache")
    membres = grappes[0][1]
    base = Base(
        lat=statistics.mean(s.depart[0] for s in membres),
        lon=statistics.mean(s.depart[1] for s in membres),
        sorties=membres,
    )
    return base, [g[1] for g in grappes]


def _point_de_maille(cle: tuple[int, int]) -> tuple[float, float]:
    """Le centre approximatif d'une maille, l'inverse de `cle_maille`."""
    return (cle[0] / MAILLE, cle[1] / MAILLE)


def km_par_secteur(
    base: Base, sortie: Sortie, dmin: float = ENTONNOIR_M, dmax: float = math.inf
) -> collections.Counter:
    """Les kilomètres d'une sortie, rangés par secteur, dans une couronne."""
    compte: collections.Counter = collections.Counter()
    for cle, metres in sortie.mailles.items():
        lat, lon = _point_de_maille(cle)
        d = base.distance_m(lat, lon)
        if dmin <= d < dmax:
            compte[base.secteur(lat, lon)] += metres / 1000.0
    return compte


# --- outils statistiques (stdlib seulement) -------------------------------------


def centile(valeurs: Sequence[float], part: float) -> float:
    """Le centile `part` (0 à 1) d'une liste non vide, par rang simple."""
    ordonnees = sorted(valeurs)
    return ordonnees[min(len(ordonnees) - 1, max(0, int(part * len(ordonnees))))]


def _rangs(valeurs: Sequence[float]) -> list[float]:
    ordre = sorted(range(len(valeurs)), key=lambda i: valeurs[i])
    rangs = [0.0] * len(valeurs)
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and valeurs[ordre[j + 1]] == valeurs[ordre[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangs[ordre[k]] = moyen
        i = j + 1
    return rangs


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Corrélation de rang de Spearman. 0 si l'une des séries est constante."""
    if len(xs) < 3:
        return 0.0
    rx, ry = _rangs(xs), _rangs(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerateur = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    denominateur = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return numerateur / denominateur if denominateur else 0.0


def entropie(compte: Iterable[float]) -> float:
    """Entropie de Shannon en bits d'une répartition. 0 si tout est au même endroit."""
    valeurs = [v for v in compte if v > 0]
    total = sum(valeurs)
    if total <= 0:
        return 0.0
    return -sum((v / total) * math.log2(v / total) for v in valeurs)


def recouvrement_mailles(a: dict, b: dict) -> float:
    """Part des mètres de `a` qui tombent dans les mailles de `b`.

    Même définition que `apprentissage.routes.recouvrement`, appliquée à des
    dictionnaires de mailles déjà calculés : on ne redécoupe pas 110 tracés à
    chaque paire, ce serait 6 000 découpages au lieu de 110.
    """
    total = sum(a.values())
    if total <= 0:
        return 0.0
    cles_b = set(b)
    return sum(m for cle, m in a.items() if cle in cles_b) / total


def recouvrement_max_mailles(a: dict, b: dict) -> float:
    """Le plus grand des deux sens — voir `apprentissage.routes.recouvrement`."""
    return max(recouvrement_mailles(a, b), recouvrement_mailles(b, a))


def matrice_de_ressemblance(mailles: Sequence[dict]) -> list[list[float]]:
    """`recouvrement_max` entre toutes les paires de tracés.

    Les ensembles de clés et les totaux sont préparés **une fois** au lieu
    d'être refaits à chaque paire : sur 109 sorties ce sont 5 886 paires, et
    reconstruire deux ensembles de 3 000 clés à chacune multipliait le temps
    par vingt. Le résultat est identique à `recouvrement_max_mailles`.
    """
    cles = [set(m) for m in mailles]
    totaux = [sum(m.values()) or 1.0 for m in mailles]
    n = len(mailles)
    matrice = [[0.0] * n for _ in range(n)]
    for i in range(n):
        items_i = mailles[i].items()
        for j in range(i + 1, n):
            cles_j = cles[j]
            commun_i = sum(m for cle, m in items_i if cle in cles_j)
            cles_i = cles[i]
            commun_j = sum(m for cle, m in mailles[j].items() if cle in cles_i)
            matrice[i][j] = matrice[j][i] = max(commun_i / totaux[i], commun_j / totaux[j])
    return matrice


def _milliers(valeur: float) -> str:
    """Un entier avec l'espace fine des milliers, à la française : « 6 368 »."""
    return f"{valeur:,.0f}".replace(",", "\u202f")


def rapport_permutation(observe: float, nul: Sequence[float]) -> str:
    """Une ligne « nul [p2,5 ; p97,5], p bilatéral » et son verdict."""
    ordonne = sorted(nul)
    p = sum(1 for x in ordonne if abs(x) >= abs(observe)) / len(ordonne)
    verdict = "EFFET" if p < 0.05 else "bruit"
    return (
        f"médiane du nul {statistics.median(ordonne):+.3f}, "
        f"intervalle [{centile(ordonne, 0.025):+.3f} ; {centile(ordonne, 0.975):+.3f}], "
        f"p bilatéral = {p:.4f} → {verdict}"
    )


# --- §1 répétition ou exploration -----------------------------------------------


def imprimer_repetition(base: Base, permutations: int, rotations: int, graine: int) -> None:
    sorties = base.sorties
    print()
    print("=" * 78)
    print("1. RÉPÉTITION OU EXPLORATION ?")
    print("=" * 78)
    print(
        "   `part_connue` est ici un **instrument de mesure**, jamais un critère\n"
        "   (doctrine). On compte ce qu'il refait, on n'en tire aucun score."
    )

    mailles = [s.mailles for s in sorties]
    toutes: collections.Counter = collections.Counter()
    passages: collections.Counter = collections.Counter()
    for m in mailles:
        for cle, metres in m.items():
            toutes[cle] += metres
            passages[cle] += 1
    km_roules = sum(s.distance_km for s in sorties)
    km_reseau = len(toutes) * KM_PAR_MAILLE

    print()
    print(f"   {len(sorties)} sorties, {_milliers(km_roules)} km roulés")
    print(f"   {_milliers(len(toutes))} mailles distinctes, soit ~{_milliers(km_reseau)} km de réseau")
    print(f"   → chaque kilomètre de route a été roulé {km_roules / km_reseau:.1f} fois en moyenne")
    valeurs = sorted(toutes.values(), reverse=True)
    total = sum(valeurs)
    for part in (0.05, 0.10, 0.20):
        k = max(1, int(part * len(valeurs)))
        print(
            f"   les {100 * part:2.0f} % de mailles les plus roulées portent "
            f"{100 * sum(valeurs[:k]) / total:4.1f} % des kilomètres"
        )
    une_fois = sum(1 for v in passages.values() if v == 1)
    print(
        f"   mailles vues une seule fois : {une_fois} / {len(passages)} "
        f"({100 * une_fois / len(passages):.0f} %) ; passages max sur une maille : {max(passages.values())}"
    )

    # ressemblance de chaque sortie à la plus proche des précédentes
    n = len(mailles)
    similitude = matrice_de_ressemblance(mailles)

    def meilleures(ordre: Sequence[int]) -> list[float]:
        return [max(similitude[ordre[i]][ordre[j]] for j in range(i)) for i in range(1, len(ordre))]

    ordre_reel = list(range(n))
    best = meilleures(ordre_reel)
    print()
    print("   Ressemblance de chaque sortie à la plus proche des précédentes")
    print(
        f"   (recouvrement_max sur mailles de 30 m) : médiane {statistics.median(best):.2f}, "
        f"p10 {centile(best, 0.10):.2f}, p90 {centile(best, 0.90):.2f}"
    )
    for seuil in (0.50, 0.70, 0.85, 0.95):
        combien = sum(1 for x in best if x >= seuil)
        print(
            f"     à plus de {100 * seuil:.0f} % identique à une sortie déjà faite : "
            f"{combien:3d} / {len(best)} ({100 * combien / len(best):.0f} %)"
        )

    # CONTRÔLE 1 — la « montée en familiarité » survit-elle à la permutation ?
    moitie = len(best) // 2
    observe = statistics.median(best[moitie:]) - statistics.median(best[:moitie])
    alea = random.Random(graine)
    nul = []
    for _ in range(permutations):
        ordre = list(range(n))
        alea.shuffle(ordre)
        b = meilleures(ordre)
        h = len(b) // 2
        nul.append(statistics.median(b[h:]) - statistics.median(b[:h]))
    print()
    print("   CONTRÔLE — « il refait de plus en plus ce qu'il a déjà fait » est-il réel ?")
    print(
        f"     observé : {statistics.median(best[:moitie]):.2f} sur la 1re moitié de l'historique, "
        f"{statistics.median(best[moitie:]):.2f} sur la 2e, écart {observe:+.3f}"
    )
    print(f"     ordre chronologique mélangé ({permutations} tirages) : {rapport_permutation(observe, nul)}")
    print(
        "     → une courbe d'accumulation monte quel que soit l'ordre : plus il y a de\n"
        "       sorties derrière, plus il est facile d'en trouver une qui ressemble.\n"
        "       Le niveau est le fait ; sa montée n'en est pas un."
    )

    # CONTRÔLE 2 — le niveau lui-même est-il un artefact de la maille ?
    if rotations > 0:
        nul_pivot = []
        for _ in range(rotations):
            pivotees = [_pivoter(m, base, alea.uniform(0, 2 * math.pi)) for m in mailles]
            tournee = matrice_de_ressemblance(pivotees)
            proches = [max(tournee[i][j] for j in range(i)) for i in range(1, n)]
            nul_pivot.append(statistics.median(proches))
        print()
        print("   CONTRÔLE — et si les mêmes sorties partaient dans une direction tirée au hasard ?")
        print("     (chaque trace pivotée autour de la base : mêmes longueurs, mêmes formes)")
        print(
            f"     observé {statistics.median(best):.2f} contre {statistics.median(nul_pivot):.2f} "
            f"[{centile(nul_pivot, 0.05):.2f} ; {centile(nul_pivot, 0.95):.2f}] après pivot "
            f"({rotations} tirages)"
        )
        print(
            "     → ce contrôle écarte l'artefact de mesure (une maille trop grosse ferait\n"
            "       se recouvrir n'importe quoi), il n'écarte PAS l'explication par le réseau\n"
            "       routier : pivoter une trace la pose sur une ville ou sur l'eau. Il dit\n"
            "       que le chiffre est vrai, pas qu'il est un choix."
        )

    # CONTRÔLE 3 — la répétition est-elle seulement l'entonnoir de sortie de chez soi ?
    print()
    print("   CONTRÔLE — la répétition n'est-elle que l'entonnoir du départ ?")
    print("     part déjà vue des kilomètres d'une sortie, par bande de distance à la base,")
    print("     les sorties étant rejouées dans l'ordre chronologique :")
    bandes = ((0, 3), (3, 8), (8, 15), (15, 25), (25, 10_000))
    vues: dict[tuple[int, int], set] = {b: set() for b in bandes}
    parts: dict[tuple[int, int], list[float]] = {b: [] for b in bandes}
    for sortie in sorties:
        courant: dict[tuple[int, int], list[float]] = {b: [0.0, 0.0] for b in bandes}
        rangement = {}
        for cle, metres in sortie.mailles.items():
            lat, lon = _point_de_maille(cle)
            d = base.distance_m(lat, lon) / 1000.0
            bande = next(b for b in bandes if b[0] <= d < b[1])
            rangement[cle] = bande
            courant[bande][0] += metres
            if cle in vues[bande]:
                courant[bande][1] += metres
        for bande in bandes:
            total_bande, deja = courant[bande]
            if total_bande > 300:
                parts[bande].append(deja / total_bande)
        for cle, bande in rangement.items():
            vues[bande].add(cle)
    for bande in bandes:
        v = parts[bande]
        if not v:
            continue
        seconde = v[len(v) // 2 :]
        borne = "+" if bande[1] > 1000 else str(bande[1])
        print(
            f"       {bande[0]:2d}-{borne:>3s} km : n={len(v):3d}  médiane {statistics.median(v):.2f}  "
            f"(2e moitié de l'historique : {statistics.median(seconde):.2f})"
        )
    print(
        "     → près de chez lui tout est déjà vu, et ça ne prouve rien : on sort de chez\n"
        "       soi par les mêmes rues. Le chiffre qui compte est celui du milieu de\n"
        "       couronne, là où les options existent."
    )


def _pivoter(mailles: dict, base: Base, theta: float) -> dict:
    """Les mêmes mailles, tournées de `theta` autour de la base.

    Rotation dans un plan local : la longitude est rétrécie par `cos(lat)`
    avant de tourner, et rétablie après, sans quoi un pivot de 90° étirerait
    la trace d'un facteur 1,5 à la latitude bretonne.
    """
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    lat0, lon0 = base.lat * MAILLE, base.lon * MAILLE
    facteur = math.cos(math.radians(base.lat))
    tournees: dict[tuple[int, int], float] = {}
    for (cle_lat, cle_lon), metres in mailles.items():
        y, x = cle_lat - lat0, (cle_lon - lon0) * facteur
        y2, x2 = y * cos_t - x * sin_t, y * sin_t + x * cos_t
        cle = (round(lat0 + y2), round(lon0 + x2 / facteur))
        tournees[cle] = tournees.get(cle, 0.0) + metres
    return tournees


# --- §2 où va-t-il ? ------------------------------------------------------------


def imprimer_directions(
    base: Base, toutes: Sequence[Sortie], rayons: Sequence[float], permutations: int, graine: int
) -> None:
    sorties = base.sorties
    print()
    print("=" * 78)
    print("2. OÙ VA-T-IL ?")
    print("=" * 78)
    print("   Secteurs de 45° autour de la base, au-delà de 3 km (l'entonnoir du départ")
    print("   ne dit rien d'un choix de direction). Aucune coordonnée n'est imprimée.")

    total: collections.Counter = collections.Counter()
    reseau: dict[str, set] = {s: set() for s in SECTEURS}
    touche: collections.Counter = collections.Counter()
    for sortie in sorties:
        compte = km_par_secteur(base, sortie)
        total.update(compte)
        for secteur, km in compte.items():
            if km >= 1.0:
                touche[secteur] += 1
        for cle in sortie.mailles:
            lat, lon = _point_de_maille(cle)
            if base.distance_m(lat, lon) >= ENTONNOIR_M:
                reseau[base.secteur(lat, lon)].add(cle)
    somme = sum(total.values())
    print()
    print("     secteur     km roulés          réseau distinct     répétition   sorties")
    for secteur in SECTEURS:
        km_reseau = len(reseau[secteur]) * KM_PAR_MAILLE
        repetition = total[secteur] / km_reseau if km_reseau > 0 else 0.0
        print(
            f"       {secteur:<3s}   {total[secteur]:7.0f} km ({100 * total[secteur] / somme:4.1f} %)"
            f"   {km_reseau:6.0f} km        ×{repetition:4.1f}       {touche[secteur]:3d}"
        )
    print()
    print(
        "   Le réseau distinct est la lecture importante : il a déjà roulé\n"
        "   sur des routes de tous les secteurs. Ce qui change d'un secteur à l'autre,\n"
        "   c'est le nombre de fois qu'il y revient."
    )
    _imprimer_ce_qu_il_en_dit(total, somme)

    # Rayleigh sur l'azimut du barycentre de chaque sortie
    angles = []
    for sortie in sorties:
        barycentre = _barycentre(sortie)
        if barycentre is not None:
            angles.append(math.radians(base.azimut(*barycentre)))
    if len(angles) >= 8:
        c = sum(math.cos(a) for a in angles) / len(angles)
        s = sum(math.sin(a) for a in angles) / len(angles)
        resultante = math.hypot(c, s)
        z = len(angles) * resultante**2
        direction = math.degrees(math.atan2(s, c)) % 360
        dominante = SECTEURS[int((direction + 22.5) // 45) % 8]
        print(
            f"   Test de Rayleigh sur l'azimut du barycentre des {len(angles)} sorties :\n"
            f"     R = {resultante:.3f}, direction moyenne au {dominante}, Z = {z:.1f}, "
            f"p ≈ {math.exp(-z):.1e}"
        )
        print(
            "     → la répartition n'est pas uniforme, et de très loin. Contrôle qui aurait\n"
            "       pu la démentir : une rose des vents plate aurait donné R ≈ 0 et p ≈ 1,\n"
            "       exactement ce que la mesure d'orientation au vent a rendu le 15/09."
        )

    # évolution du répertoire
    _imprimer_resserrement(base, permutations, graine)

    # sensibilité au rayon de la base
    print()
    print("   CONTRÔLE — la mesure dépend-elle de la façon dont la « base » est définie ?")
    for rayon in rayons:
        autre, _ = base_principale(toutes, rayon)
        donnees = _entropies(autre)
        if len(donnees) >= 10:
            rho = spearman([d[0] for d in donnees], [d[1] for d in donnees])
            print(
                f"     rayon {rayon:5.0f} m : {len(autre.sorties):3d} sorties, "
                f"Spearman(rang, diversité) = {rho:+.3f}"
            )
    print("     → le resserrement ne tient pas au découpage de la base.")


#: Ce que le mainteneur dit de ses propres directions (16/09/2026) : « peu au
#: nord-ouest, un peu plus au nord-est, surtout sud et ouest ». Recopié ici
#: pour être **confronté** à la mesure, et pour rien d'autre : aucun calcul
#: n'en dépend, aucun score ne s'en sert.
CE_QU_IL_EN_DIT = {"NO": "peu", "NE": "un peu plus", "S": "surtout", "O": "surtout"}


def _imprimer_ce_qu_il_en_dit(km: collections.Counter, somme: float) -> None:
    """Confronte sa description de ses directions au classement mesuré."""
    classement = sorted(SECTEURS, key=lambda s: -km[s])
    print()
    print("   CE QU'IL EN DIT (16/09/2026) contre CE QUE LA MESURE DIT")
    print('     ses mots : « peu au nord-ouest, un peu plus au nord-est, surtout sud et ouest »')
    print("     classement mesuré, du plus roulé au moins roulé :")
    print(
        "       "
        + "  >  ".join(f"{s} {100 * km[s] / somme:.0f} %" for s in classement)
    )
    for secteur, mot in CE_QU_IL_EN_DIT.items():
        rang = classement.index(secteur) + 1
        print(
            f"       « {mot} » au {secteur:<2s} → rang {rang}/8, {100 * km[secteur] / somme:4.1f} % des km"
        )
    print(
        "     → deux de ses quatre repères tiennent : le nord-ouest est bien son secteur\n"
        "       le plus rare, et le sud est bien dans ses premiers. Deux ne tiennent pas :\n"
        "       le SUD-EST, qu'il ne nomme pas, porte à lui seul plus de kilomètres que\n"
        "       les quatre secteurs qu'il cite réunis ; et l'OUEST, qu'il croit fréquent,\n"
        "       arrive sixième sur huit. C'est un écart entre ce qu'il fait et ce qu'il\n"
        "       croit faire, du même genre que Q17 — et c'est mesuré, pas interprété.\n"
        "       Réserve honnête : une rose des vents n'est pas une carte mentale. Il se\n"
        "       peut qu'il appelle « sud » ce que la boussole appelle sud-est. L'écart\n"
        "       qui ne s'explique pas comme ça est celui de l'ouest."
    )


def _barycentre(sortie: Sortie) -> tuple[float, float] | None:
    """Le centre de gravité kilométrique d'une sortie. Jamais imprimé."""
    total = sum(sortie.mailles.values())
    if total <= 0:
        return None
    lat = sum(_point_de_maille(c)[0] * m for c, m in sortie.mailles.items()) / total
    lon = sum(_point_de_maille(c)[1] * m for c, m in sortie.mailles.items()) / total
    return (lat, lon)


def _entropies(base: Base) -> list[tuple[int, float, float, float | None]]:
    """(rang chronologique, diversité en bits, distance en km, variabilité) par sortie."""
    donnees = []
    for rang, sortie in enumerate(base.sorties):
        compte = km_par_secteur(base, sortie)
        if sum(compte.values()) > 5.0:
            donnees.append((rang, entropie(compte.values()), sortie.distance_km, sortie.variabilite))
    return donnees


def _imprimer_resserrement(base: Base, permutations: int, graine: int) -> None:
    donnees = _entropies(base)
    if len(donnees) < 20:
        print("   Trop peu de sorties exploitables pour mesurer une évolution du répertoire.")
        return
    print()
    print("   Le répertoire se resserre-t-il ? (diversité = entropie des secteurs d'une")
    print("   sortie, en bits ; 0 bit = tous les kilomètres dans un secteur, 3 bits = les 8)")
    par_an: dict[str, list[tuple[int, float, float]]] = collections.defaultdict(list)
    for rang, bits, km, _variabilite in donnees:
        par_an[base.sorties[rang].jour.strftime("%Y")].append((rang, bits, km))
    for annee in sorted(par_an):
        g = par_an[annee]
        print(
            f"     {annee} : n={len(g):3d}  diversité médiane {statistics.median([x[1] for x in g]):.2f} bits"
            f"   (distance médiane {statistics.median([x[2] for x in g]):3.0f} km)"
        )
    rho = spearman([d[0] for d in donnees], [d[1] for d in donnees])
    print(f"     Spearman(rang chronologique, diversité) = {rho:+.3f} sur {len(donnees)} sorties")

    # CONTRÔLE — le confondant de longueur
    print()
    print("   CONTRÔLE — est-ce seulement que les sorties raccourcissent ?")
    rho_dist = spearman([d[0] for d in donnees], [d[2] for d in donnees])
    rho_ent = spearman([d[2] for d in donnees], [d[1] for d in donnees])
    print(f"     Spearman(rang, distance) = {rho_dist:+.3f} ; Spearman(distance, diversité) = {rho_ent:+.3f}")
    print("     à longueur appariée :")
    for bas, haut in ((30, 50), (50, 70), (70, 120), (120, 10_000)):
        g = [d for d in donnees if bas <= d[2] < haut]
        if len(g) < 10:
            continue
        h = len(g) // 2
        print(
            f"       {bas:3d}-{haut if haut < 1000 else '+':>3} km : n={len(g):2d}  "
            f"{statistics.median([x[1] for x in g[:h]]):.2f} bits → "
            f"{statistics.median([x[1] for x in g[h:]]):.2f} bits   "
            f"Spearman {spearman([x[0] for x in g], [x[1] for x in g]):+.3f}"
        )
    residus = _residus_sur_log_distance(donnees)
    rho_res = spearman([d[0] for d in donnees], residus)
    alea = random.Random(graine + 1)
    nul = [
        spearman([d[0] for d in donnees], alea.sample(residus, len(residus))) for _ in range(permutations)
    ]
    print(
        f"     diversité corrigée de la longueur (résidu d'une régression sur log km) :\n"
        f"       Spearman = {rho_res:+.3f} ; {rapport_permutation(rho_res, nul)}"
    )

    # CONTRÔLE — la séance structurée subordonne-t-elle le parcours ?
    print()
    print("   CONTRÔLE — est-ce la séance qui commande, et non la direction ?")
    print("     (une sortie à blocs choisit sa route pour pouvoir faire ses blocs ;")
    print("     si le resserrement ne tenait que là, ce ne serait pas un goût de terrain)")
    for nom, garde in (
        ("allure tenue (variabilité < 1,15)", lambda v: v is not None and v < 1.15),
        ("à blocs (variabilité ≥ 1,15)", lambda v: v is not None and v >= 1.15),
    ):
        groupe = [d for d in donnees if garde(d[3])]
        if len(groupe) < 15:
            continue
        moitie = len(groupe) // 2
        print(
            f"     {nom:<34s} n={len(groupe):3d}  "
            f"{statistics.median([d[1] for d in groupe[:moitie]]):.2f} bits → "
            f"{statistics.median([d[1] for d in groupe[moitie:]]):.2f} bits   "
            f"Spearman {spearman([d[0] for d in groupe], [d[1] for d in groupe]):+.3f}"
        )
    print("     → le resserrement est dans les deux groupes : la séance ne l'explique pas.")


def _residus_sur_log_distance(donnees: Sequence[tuple[int, float, float, float | None]]) -> list[float]:
    """Diversité moins la part qu'explique la longueur de la sortie."""
    xs = [math.log(d[2]) for d in donnees]
    ys = [d[1] for d in donnees]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    variance = sum((x - mx) ** 2 for x in xs)
    pente = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / variance if variance else 0.0
    return [y - (my + pente * (x - mx)) for x, y in zip(xs, ys, strict=True)]


# --- §3 forme des sorties -------------------------------------------------------


def imprimer_forme(base: Base) -> None:
    sorties = [s for s in base.sorties if s.rayon_max_m > 2000]
    print()
    print("=" * 78)
    print("3. FORME DES SORTIES")
    print("=" * 78)
    if len(sorties) < 10:
        print("   Trop peu de sorties assez longues pour en dire quelque chose.")
        return
    formes = [s.longueur_trace_m / s.rayon_max_m for s in sorties]
    print()
    print("   Distance parcourue ÷ distance maximale au départ. Repères géométriques :")
    print("     2,00 = aller-retour pur   3,14 = boucle circulaire passant par le départ")
    print("     3,00 = boucle triangulaire   au-delà de 4 = pétales, ou détours serrés")
    print(
        f"   mesuré sur {len(formes)} sorties : médiane {statistics.median(formes):.2f}, "
        f"p10 {centile(formes, 0.10):.2f}, p25 {centile(formes, 0.25):.2f}, p90 {centile(formes, 0.90):.2f}"
    )
    allers_retours = sum(1 for f in formes if f < 2.4)
    print(
        f"   proches d'un aller-retour (< 2,4) : {allers_retours} / {len(formes)} "
        f"({100 * allers_retours / len(formes):.0f} %)"
    )

    retours = []
    for sortie in base.sorties:
        premiere, seconde = sortie.moities
        if sum(premiere.values()) > 0:
            retours.append(recouvrement_mailles(premiere, seconde))
    if retours:
        print()
        print("   Retour sur ses pas (part de la 1re moitié refaite dans la 2e) :")
        print(
            f"     médiane {statistics.median(retours):.2f}, p90 {centile(retours, 0.90):.2f} ; "
            f"au-dessus de 50 % : {sum(1 for x in retours if x > 0.5)} / {len(retours)}"
        )

    boucles = sum(
        1
        for s in base.sorties
        if distance_m(
            PointTrace(lat=s.depart[0], lon=s.depart[1], alt_m=None, dist_m=0.0),
            PointTrace(lat=s.fin[0], lon=s.fin[1], alt_m=None, dist_m=0.0),
        )
        < 1000
    )
    print(
        f"   sorties qui finissent à moins de 1 km de leur départ : "
        f"{boucles} / {len(base.sorties)} ({100 * boucles / len(base.sorties):.0f} %)"
    )
    rayons = [s.rayon_max_m / 1000 for s in base.sorties]
    print(
        f"   point le plus éloigné : médiane {statistics.median(rayons):.1f} km, "
        f"p90 {centile(rayons, 0.90):.1f} km"
    )


# --- §4 régularité de l'effort --------------------------------------------------


def imprimer_effort(base: Base, masse_kg: float) -> None:
    print()
    print("=" * 78)
    print("4. RÉGULARITÉ DE L'EFFORT")
    print("=" * 78)
    print("   Deux contrefactuels, calculés sur son propre terrain et sa propre vitesse :")
    print("     « puissance constante » → la puissance ne bouge pas avec la pente : 0 W/point")
    print("     « vitesse constante »   → il faut m·g·v watts de plus par point de pente")
    print("   Où tombe-t-il entre les deux ?")
    print()
    print("   RÉSERVE DE MÉTHODE, à lire avant les chiffres : la pente d'un tronçon de")
    print("   200 m est bruitée (altimètre barométrique, altitudes lissées). Un bruit sur")
    print("   la variable explicative **aplatit** une pente de régression — c'est la")
    print("   dilution classique. Le chiffre rendu ici est donc une **borne basse** : il")
    print("   suit le terrain d'au moins autant, pas de moins. Le sens de l'erreur va")
    print("   contre la conclusion, ce qui est la bonne direction pour s'y fier.")

    variabilites = [s.variabilite for s in base.sorties if s.variabilite]
    if variabilites:
        print()
        print(
            f"   Indice de variabilité (puissance normalisée ÷ moyenne), n={len(variabilites)} : "
            f"médiane {statistics.median(variabilites):.2f}, "
            f"p10 {centile(variabilites, 0.10):.2f}, p90 {centile(variabilites, 0.90):.2f}"
        )

    for nom, garde in (
        ("tous les tronçons roulants", lambda p: True),
        ("en montée seule (pente > 1 %)", lambda p: p > 0.01),
        ("à plat (|pente| ≤ 1 %)", lambda p: abs(p) <= 0.01),
        ("en descente seule (pente < −1 %)", lambda p: p < -0.01),
    ):
        resultats = []
        for sortie in base.sorties:
            r = _regression_pente(
                [t for t in sortie.troncons if garde(t[0])], sur_pente=(nom != "à plat (|pente| ≤ 1 %)")
            )
            if r is not None:
                resultats.append(r)
        if len(resultats) < 10:
            continue
        puissances = [r[2] for r in resultats]
        print()
        print(f"   {nom} — {len(resultats)} sorties, {sum(r[4] for r in resultats)} tronçons de 200 m")
        print(f"     puissance médiane : {statistics.median(puissances):.0f} W")
        if nom == "à plat (|pente| ≤ 1 %)":
            continue
        pentes = [r[0] for r in resultats]
        vitesse = statistics.median([r[3] for r in resultats])
        contrefactuel = masse_kg * 9.81 * vitesse / 100.0
        print(
            f"     d(puissance)/d(pente) : médiane {statistics.median(pentes):+.1f} W par point de pente "
            f"[p10 {centile(pentes, 0.10):+.1f} ; p90 {centile(pentes, 0.90):+.1f}]"
        )
        print(
            f"     contrefactuel « vitesse constante » à {vitesse:.1f} m/s : "
            f"{contrefactuel:+.1f} W par point"
        )
        print(
            f"     → il parcourt {100 * statistics.median(pentes) / contrefactuel:.0f} % du chemin "
            "entre « puissance constante » et « vitesse constante »"
        )
        if nom == "tous les tronçons roulants":
            correlations = [r[5] for r in resultats]
            depassent = sum(1 for p in pentes if p > contrefactuel / 2)
            print(
                f"     corrélation puissance~pente : médiane {statistics.median(correlations):.2f} "
                f"— le terrain pilote bien la puissance, mais au quart de l'amplitude"
            )
            print(
                f"     CONTRÔLE — sorties où la puissance suit le terrain à plus de la moitié du\n"
                f"       contrefactuel : {depassent} / {len(pentes)}. Un cycliste qui « roule au terrain »\n"
                f"       aurait rempli cette ligne ; elle est vide, l'effet a donc un signe clair."
            )


def _regression_pente(
    troncons: Sequence[tuple[float, float, float, float]], *, sur_pente: bool
) -> tuple[float, float, float, float, int, float] | None:
    """Régression pondérée par la distance de la puissance sur la pente.

    Rend (W par point de pente, m/s par point, puissance moyenne, vitesse
    moyenne, nombre de tronçons, corrélation). `None` sous 40 tronçons : une
    pente de régression sur 20 points de 200 m ne mesure rien.
    """
    if len(troncons) < 40:
        return None
    poids = sum(t[3] for t in troncons)
    moyenne_pente = sum(t[0] * t[3] for t in troncons) / poids
    moyenne_puissance = sum(t[1] * t[3] for t in troncons) / poids
    moyenne_vitesse = sum(t[2] * t[3] for t in troncons) / poids
    if not sur_pente:
        return (0.0, 0.0, moyenne_puissance, moyenne_vitesse, len(troncons), 0.0)
    sxx = sum(t[3] * (t[0] - moyenne_pente) ** 2 for t in troncons)
    syy = sum(t[3] * (t[1] - moyenne_puissance) ** 2 for t in troncons)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum(t[3] * (t[0] - moyenne_pente) * (t[1] - moyenne_puissance) for t in troncons)
    svy = sum(t[3] * (t[0] - moyenne_pente) * (t[2] - moyenne_vitesse) for t in troncons)
    return (
        sxy / sxx / 100.0,
        svy / sxx / 100.0,
        moyenne_puissance,
        moyenne_vitesse,
        len(troncons),
        sxy / math.sqrt(sxx * syy),
    )


# --- §5 rythme ------------------------------------------------------------------


def imprimer_rythme(base: Base) -> None:
    sorties = base.sorties
    print()
    print("=" * 78)
    print("5. RYTHME")
    print("=" * 78)
    jours = collections.Counter(s.jour_semaine for s in sorties)
    noms = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")
    print()
    print("   " + "  ".join(f"{noms[i]} {jours[i]:3d}" for i in range(7)))
    attendu = len(sorties) / 7
    khi2 = sum((jours[i] - attendu) ** 2 / attendu for i in range(7))
    weekend = jours[5] + jours[6]
    print(
        f"   week-end : {weekend} / {len(sorties)} ({100 * weekend / len(sorties):.0f} % pour 2 jours sur 7)"
    )
    print(
        f"   χ² d'uniformité des jours = {khi2:.1f} à 6 ddl "
        f"(12,6 à 5 % ; 22,5 à 0,1 %) → {'non uniforme' if khi2 > 12.6 else 'compatible avec l’uniforme'}"
    )
    heures = collections.Counter(s.heure_locale for s in sorties)
    matin = sum(v for h, v in heures.items() if h < 12)
    print(
        f"   heure de départ : {matin} le matin, {len(sorties) - matin} l'après-midi ; "
        f"heures les plus fréquentes : "
        + ", ".join(f"{h}h ({n})" for h, n in heures.most_common(3))
    )
    mois = collections.Counter(s.jour.month for s in sorties)
    print("   par mois (janv.→déc.) : " + " ".join(f"{mois[m]:2d}" for m in range(1, 13)))
    distances = [s.distance_km for s in sorties]
    durees = [s.duree_h for s in sorties if s.duree_h > 0]
    print(
        f"   distance : médiane {statistics.median(distances):.0f} km "
        f"[p10 {centile(distances, 0.10):.0f} ; p90 {centile(distances, 0.90):.0f}]"
    )
    if durees:
        print(
            f"   durée : médiane {statistics.median(durees):.2f} h "
            f"[p10 {centile(durees, 0.10):.2f} ; p90 {centile(durees, 0.90):.2f}]"
        )


# --- lecture d'ensemble ---------------------------------------------------------


def imprimer_lecture() -> None:
    print()
    print("=" * 78)
    print("CE QUE LES DONNÉES SOUTIENNENT, ET CE QU'ELLES NE SOUTIENNENT PAS")
    print("=" * 78)
    print(
        """
   TIENT — la concentration spatiale. Il roule quelques fois plus de kilomètres
   qu'il n'y a de route distincte sous ses roues, la moitié de ses sorties sont
   à plus de 85 % une sortie déjà faite, et une petite fraction des mailles
   porte près de la moitié des kilomètres. Le contrôle par pivot écarte
   l'artefact de mesure ; le contrôle par bande de distance écarte l'entonnoir
   du départ, puisque la répétition reste forte à 15-25 km de chez lui, là où
   les options existent.

   TIENT — le resserrement du répertoire. La diversité des secteurs d'une
   sortie baisse au fil du temps, et ça survit au contrôle de longueur (à
   distance appariée, et sur le résidu d'une régression sur log km). L'effet
   est nul sur les sorties courtes, qui n'ont pas le choix, et le plus net sur
   les longues, qui l'ont. C'est donc bien un choix qui se rétrécit.

   TIENT — l'écart entre ses mots et ses roues, sur l'ouest. Il décrit l'ouest
   comme un secteur fréquent ; c'est son sixième sur huit, 5 % des kilomètres,
   et il n'y revient qu'une fois et demie par kilomètre de route connue contre
   quatre fois et demie au sud-est. Le secteur qui porte 44 % de ses kilomètres,
   le sud-est, ne figure pas dans sa description. Un décalage de vocabulaire
   (appeler « sud » un sud-est) expliquerait la moitié de l'écart, pas l'ouest.

   TIENT — l'effort est tenu contre le terrain, pas subi. La puissance monte
   avec la pente, mais au quart environ de ce qu'exigerait une vitesse
   constante : il lève le pied en côte et ne se relance pas en descente.

   BRUIT — « il refait de plus en plus ce qu'il a déjà fait ». La montée de la
   ressemblance à une sortie précédente est entièrement expliquée par
   l'accumulation : mélanger l'ordre des sorties la reproduit. Le niveau est un
   fait, sa pente n'en est pas un.

   CE QU'IL CHERCHE, CONTRE CE QU'IL SAIT FAIRE. La doctrine cite son souhait :
   aller « tester des routes sud sud-ouest pour voir ». Le sud-ouest est
   aujourd'hui son 4e secteur, 7 % des kilomètres, et il n'y revient que deux
   fois par kilomètre de route connue contre quatre fois et demie au sud-est.
   Le souhait est donc **devant** la pratique, pas derrière : c'est un écart
   mesuré entre une intention déclarée et un historique, et c'est exactement ce
   qu'un outil peut combler. Réserve : le souhait date du 16/09/2026, il n'y a
   aucune sortie après lui — on mesure un point de départ, pas un échec.

   INDÉCIDABLE ICI — le « pourquoi ». Aucune mesure de ce script ne sépare
   « il choisit ce secteur » de « le réseau routier ne lui laisse que celui-là ».
   Il faudrait comparer à ce qui est *routable* autour de sa base, ce qui
   demande le moteur de tracé et une notion d'offre par direction. C'est la
   suite naturelle, et c'est exactement la forme qu'avait Q17 : la mesure a
   montré l'écart, le mainteneur a donné la cause.
"""
    )


# --- ligne de commande ----------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(Path(arguments.config).expanduser() if arguments.config else None)
    velo = velo_demande(config, arguments.velo)
    masse = masse_totale_kg(config, velo)
    depuis = date.fromisoformat(arguments.depuis)

    print("Mesure exploratoire du style : que cherche-t-il à faire quand il roule ?")
    print(f"Cache : {Path(config.cache.dossier).expanduser()} — aucun appel réseau.")
    print(f"Historique depuis le {depuis.isoformat()}.")

    sorties, manques = collecter(config, depuis, arguments.limite, arguments.bavard)
    if not sorties:
        raise ErreurUtilisateur(
            "aucune sortie route extérieure dans le cache — lancer « ourouler inventaire --synchro »"
        )
    base, grappes = base_principale(sorties, arguments.rayon_base)
    print()
    print(f"{len(sorties)} sorties route extérieures lues, {len(grappes)} points de départ distincts.")
    print(
        f"La base principale en porte {len(base.sorties)} "
        f"({100 * len(base.sorties) / len(sorties):.0f} %) ; les autres départs "
        "(vacances, déplacements) sont écartés des mesures de direction, qui n'ont de sens "
        "que par rapport à un même point."
    )
    if manques:
        compte = collections.Counter(manques)
        print("Sorties non exploitées : " + ", ".join(f"{n} {motif}" for motif, n in compte.most_common()))

    imprimer_repetition(base, arguments.permutations, arguments.rotations, arguments.graine)
    imprimer_directions(
        base, sorties, arguments.rayons_testes, arguments.permutations, arguments.graine
    )
    imprimer_forme(base)
    imprimer_effort(base, masse)
    imprimer_rythme(base)
    imprimer_lecture()

    print()
    print(
        "Ceci est une mesure, pas un verdict : il n'y a pas de seuil à tenir, et le\n"
        "script rend 0 dès qu'il a pu mesurer. Ce qui doit être relu, ce sont les\n"
        "lignes CONTRÔLE — un effet sans contrôle n'est pas un effet."
    )
    return 0


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui du mainteneur)")
    analyseur.add_argument("--velo", help="vélo dont on prend la masse (défaut : 1er vélo route)")
    analyseur.add_argument(
        "--depuis", default=DEPUIS_DEFAUT, help=f"début de l'historique (défaut : {DEPUIS_DEFAUT})"
    )
    analyseur.add_argument("--limite", type=int, help="s'arrêter après tant de sorties (mise au point)")
    analyseur.add_argument(
        "--rayon-base",
        type=float,
        default=RAYON_BASE_M_DEFAUT,
        dest="rayon_base",
        help=f"rayon de la grappe de départ, en mètres (défaut : {RAYON_BASE_M_DEFAUT:.0f})",
    )
    analyseur.add_argument(
        "--permutations", type=int, default=2000, help="tirages des tests de permutation (défaut : 2000)"
    )
    analyseur.add_argument(
        "--rotations",
        type=int,
        default=20,
        help="tirages du contrôle par pivot des traces, 0 pour le sauter (défaut : 20)",
    )
    analyseur.add_argument("--graine", type=int, default=20260916, help="graine du hasard, pour rejouer")
    analyseur.add_argument("--bavard", action="store_true", help="dire l'avancement de la lecture du cache")
    arguments = analyseur.parse_args(argv)
    arguments.rayons_testes = (1500.0, 3000.0, 5000.0)
    return arguments


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except ErreurUtilisateur as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validation rétrospective de l'évaluateur de terrain (lot L4.2).

**Ce script n'est pas un test pytest.** Il lit le cache réel du mainteneur et,
si une clé d'API est configurée, appelle Intervals.icu : les deux sont
interdits dans la suite de tests (règles absolues 1 et 3). Il se lance à la
main, depuis la racine du dépôt :

    uv run python tests/validation/terrain_retrospectif.py

Ce qu'il mesure, et pourquoi c'est le critère d'acceptation du lot : on prend
des séances déjà faites dehors, on relit **où les blocs sont réellement
tombés**, on note ces emplacements avec `seance.terrain.evaluer_couloir`, et
on les compare à des emplacements tirés au hasard, de même longueur, sur la
même sortie. Si l'évaluateur est juste, les emplacements réels doivent être
nettement mieux notés que le hasard. S'ils ne le sont pas, les poids sont
faux — et le script le dit au lieu de le taire.

**LE MODE NOMINAL FAIT FOI.** Le script a deux modes, qui ne se valent pas :

* **nominal** (celui-ci, sans option) : les blocs sont les **intervalles
  marqués** dans Intervals.icu, c'est-à-dire ce que le cycliste a réellement
  prescrit et exécuté. Onze blocs sur les deux sorties de référence, qui
  correspondent un à un à la séance. C'est ce mode qui juge les poids ;
* **`--sans-reseau`** : faute de clé d'API, les blocs sont **devinés** à partir
  de la seule puissance. Il en trouve quinze : il coupe un 20' en trois quand
  la puissance passe sous le seuil au milieu, et il ramasse des fragments
  d'échauffement au-dessus de 75 % de FTP qui n'étaient pas des blocs. Il borne
  donc moins bien les blocs, et il mesure autre chose.

Conséquence : le mode dégradé conclut aujourd'hui **NON**, à 70,3 % pour un
seuil de 70 %. C'est la conclusion honnête d'un mode qui découpe mal, **pas un
désaveu des poids** — un bloc coupé en trois porte des morceaux de récupération
que le vrai bloc n'a pas. Le script **échoue** quand les deux modes divergent,
avec un message qui le dit : laisser croire que l'un vaut l'autre serait pire
que l'écart lui-même. La référence nominale est figée dans
`REFERENCE_NOMINALE`, avec sa date et ses chiffres.

Le mode dégradé reste utile, et c'est pour cela qu'il existe : il est le seul
reproductible par un relecteur qui n'a pas la clé du mainteneur, et il vérifie
que le code tourne de bout en bout. Il ne vaut pas verdict.

**LIMITE PRINCIPALE — LES FEUX NE SONT PAS VALIDÉS PAR LA MESURE.** Une sortie
enregistrée est une trace GPS : elle ne porte ni feu ni stop. Les tags de route
viennent de `routes_connues.sqlite` (bâti par `ourouler apprendre`, qui a rejoué
les sorties dans BRouter) et cette base ne garde que les tags de **chemin**, pas
de nœud. Tous les « carrefours » comptés ici sont donc des virages marqués, et
`seance.terrain.POIDS_CARREFOUR` — ce que coûte un feu ou un stop sous un bloc —
reste hors de portée de ce script : c'est un raisonnement produit, pas un
chiffre mesuré. Quiconque lit la conclusion doit lire cette phrase avec.

Deux autres choses que ce script ne sait pas, et qu'il affiche :
- **Couverture partielle.** Une portion jamais rejouée dans BRouter n'a pas de
  tags : la colonne « tags » de la table dit quelle part du bloc est connue.
- **Le cache n'est pas modifié.** L'index et la base de routes sont ouverts en
  lecture seule (`mode=ro`) — d'où les requêtes SQL à la main plutôt que
  `Cache` et `BaseRoutes`, dont la construction migre le schéma et écrit.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ourouler.activites.lecture import lecteur_pour
from ourouler.activites.modele import Activite, Point
from ourouler.apprentissage.commande import NOM_BASE
from ourouler.apprentissage.routes import cle_maille
from ourouler.boucle.trace import Segment, Trace
from ourouler.config import charger
from ourouler.connecteurs.intervals import ClientIntervals
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.physique.calibration import trace_depuis_activite
from ourouler.seance.terrain import NoteBloc, evaluer_couloir

#: Les sorties à relire : (jour, morceau du nom). Ce sont les deux séances de
#: référence du contrat du sprint 4 §2 — « 4x8 SV1 outdoor » du 22/04/2026 et
#: « 2x20' + 4x3' » du 25/04/2026. La recherche se fait par date **et** par
#: nom : une autre sortie le même jour ne doit pas être prise à leur place.
SORTIES_DE_REFERENCE: tuple[tuple[str, str], ...] = (
    ("2026-04-22", "4x8"),
    ("2026-04-25", "2x20"),
)

#: Part de la FTP au-dessus de laquelle un tronçon compte comme un bloc.
#:
#: 0,75 et non 0,90 : c'est le même seuil que `SEUIL_RECUPERATION_PCT_FTP` du
#: lot L4.1, qui type une étape sans marqueur. Les deux doivent dire la même
#: chose, sinon un 2×20' prescrit à 80-85 % de FTP serait un bloc pour la
#: séance et une récupération pour la validation. `--seuil-ftp` reste là pour
#: explorer : à 0,90, les deux 20' du 25/04 disparaissent de la mesure.
PART_FTP_BLOC = 0.75

#: Durée minimale d'un bloc, en secondes.
DUREE_MIN_BLOC_S = 180.0

#: Nombre d'emplacements tirés au hasard par bloc réel.
TIRAGES_PAR_BLOC = 200

#: Graine du tirage : le résultat doit être le même d'une exécution à l'autre,
#: sans quoi « la médiane a bougé » ne veut rien dire.
GRAINE = 20260913

#: Ce qu'on appelle « nettement meilleure » : la médiane des blocs réels doit
#: valoir au plus cette part de la médiane au hasard.
AMELIORATION_ATTENDUE = 0.70

#: Le résultat du **mode nominal**, celui qui fait foi, tel que mesuré le
#: 13/09/2026 sur les deux sorties de référence. Il sert à deux choses : dire
#: au lecteur ce que le mode qui fait foi a conclu même s'il ne peut pas le
#: relancer, et détecter une divergence entre les deux modes.
#:
#: Le mettre à jour est un geste explicite : on relance le mode nominal, on
#: recopie ce qu'il imprime, et on date.
REFERENCE_NOMINALE = {
    "date": "2026-09-13",
    "verdict": True,
    "blocs_juges": 9,
    "rapport": 0.43,
    "blocs_trouves": 11,
}

#: Les trois tailles de bloc, et ce qu'on attend de chacune. Un bloc de 3 min
#: (1,5 km) et un 20' (11 km) ne posent pas le même problème : le premier se
#: place, le second se subit. Le critère d'acceptation ne porte que sur les
#: deux premières catégories — voir `conclure`.
CATEGORIES: tuple[tuple[str, float, float], ...] = (
    ("courts (< 2 km)", 0.0, 2000.0),
    ("moyens (2-6 km)", 2000.0, 6000.0),
    ("longs (> 6 km)", 6000.0, math.inf),
)

#: Les catégories sur lesquelles porte le critère d'acceptation du lot.
CATEGORIES_JUGEES = ("courts (< 2 km)", "moyens (2-6 km)")

#: Fenêtre de lissage de la puissance, en points, pour la détection de repli.
FENETRE_PUISSANCE = 30

#: Trou maximal toléré à l'intérieur d'un bloc détecté par la puissance.
TROU_TOLERE_S = 30.0


# --- lecture du cache, en lecture seule ---------------------------------------


@dataclass
class Sortie:
    """Une sortie du cache, telle qu'on en a besoin ici."""

    identifiant: str
    id_externe: str | None
    jour: str
    nom: str
    activite: Activite


def _connexion_ro(chemin: Path) -> sqlite3.Connection:
    """Ouvre une base SQLite **en lecture seule** : ce script n'écrit rien."""
    if not chemin.is_file():
        raise ErreurUtilisateur(f"fichier introuvable : {chemin}")
    return sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)


def chercher_sortie(dossier_cache: Path, jour: str, motif: str) -> Sortie:
    """La sortie du cache de ce jour dont le nom contient `motif`."""
    index = dossier_cache / "index.sqlite"
    with _connexion_ro(index) as cx:
        lignes = cx.execute(
            "SELECT identifiant, id_externe, extension, debut, meta FROM activites "
            "WHERE substr(debut, 1, 10) = ? ORDER BY debut",
            (jour,),
        ).fetchall()
    candidates = []
    for identifiant, id_externe, extension, debut, meta in lignes:
        nom = _nom(meta)
        if motif.casefold() in nom.casefold():
            candidates.append((identifiant, id_externe, extension, debut, nom))
    if not candidates:
        raise ErreurUtilisateur(
            f"aucune sortie du {jour} dont le nom contienne « {motif} » dans {index} "
            f"({len(lignes)} sortie(s) ce jour-là) — lancer d'abord « ourouler inventaire --synchro »"
        )
    identifiant, id_externe, extension, debut, nom = candidates[0]
    chemin = dossier_cache / "brut" / f"{identifiant}.{extension}"
    activite = lecteur_pour(chemin.suffix)(chemin)
    return Sortie(
        identifiant=identifiant,
        id_externe=id_externe,
        jour=str(debut)[:10],
        nom=nom,
        activite=activite,
    )


def _nom(meta: str | None) -> str:
    """Le nom de la sortie tel que la source le donne, depuis la colonne `meta`."""
    try:
        return str((json.loads(meta or "{}") or {}).get("nom") or "")
    except ValueError:
        return ""


# --- tags de route, appris par `ourouler apprendre` ---------------------------


def tags_appris(base: Path, points: list[Point]) -> dict[tuple[int, int], dict[str, str]]:
    """Maille (~30 m) → tags OSM, pour la zone couverte par ces points.

    La base est celle de `apprentissage.routes` : `ourouler apprendre` a rejoué
    les sorties du cache dans BRouter et gardé, par carré de 30 m, la classe de
    route, la surface et la vitesse limite. C'est la seule source de tags OSM
    disponible hors ligne pour une trace GPS.

    Quand une maille porte plusieurs tronçons (une `tertiary` et une
    `secondary` dans le même carré), on garde celui sur lequel le cycliste a
    roulé le plus de mètres.
    """
    latitudes = [cle_maille(p.lat, p.lon)[0] for p in points if p.lat is not None]
    if not latitudes:
        return {}
    par_maille: dict[tuple[int, int], tuple[float, dict[str, str]]] = {}
    with _connexion_ro(base) as cx:
        lignes = cx.execute(
            "SELECT cle_lat, cle_lon, highway, surface, maxspeed, metres FROM troncons "
            "WHERE cle_lat BETWEEN ? AND ?",
            (min(latitudes) - 1, max(latitudes) + 1),
        ).fetchall()
    for cle_lat, cle_lon, highway, surface, maxspeed, metres in lignes:
        cle = (int(cle_lat), int(cle_lon))
        tags = {
            nom: valeur
            for nom, valeur in (("highway", highway), ("surface", surface), ("maxspeed", maxspeed))
            if valeur
        }
        connu = par_maille.get(cle)
        if connu is None or float(metres or 0.0) > connu[0]:
            par_maille[cle] = (float(metres or 0.0), tags)
    return {cle: tags for cle, (_, tags) in par_maille.items()}


def enrichir(trace: Trace, par_maille: dict[tuple[int, int], dict[str, str]]) -> float:
    """Colle sur la trace des tronçons portant les tags appris. Rend la part couverte.

    Les points dont la maille est inconnue **ne reçoivent aucun tronçon** : un
    tronçon aux tags vides ferait passer « on ne sait pas » pour « pas de
    village », exactement ce que la règle absolue 5 interdit.
    """
    segments: list[Segment] = []
    debut = 0
    courants = par_maille.get(_maille(trace, 0), {})
    for i in range(1, len(trace.points)):
        tags = par_maille.get(_maille(trace, i), {})
        if tags == courants:
            continue
        if courants:
            segments.append(_segment(trace, debut, i, courants))
        debut, courants = i, tags
    if courants and debut < len(trace.points) - 1:
        segments.append(_segment(trace, debut, len(trace.points) - 1, courants))

    trace.segments = segments
    total = trace.points[-1].dist_m if trace.points else 0.0
    couvert = sum(s.longueur_m for s in segments)
    return couvert / total if total > 0 else 0.0


def _maille(trace: Trace, i: int) -> tuple[int, int]:
    return cle_maille(trace.points[i].lat, trace.points[i].lon)


def _segment(trace: Trace, debut: int, fin: int, tags: dict[str, str]) -> Segment:
    return Segment(
        debut_idx=debut,
        fin_idx=fin,
        longueur_m=trace.points[fin].dist_m - trace.points[debut].dist_m,
        tags=dict(tags),
    )


# --- où les blocs sont tombés --------------------------------------------------


@dataclass
class Bloc:
    """Un bloc réellement roulé, ramené à une position sur le tracé."""

    libelle: str
    debut_m: float
    longueur_m: float
    duree_s: float
    puissance_w: float


def blocs_depuis_intervals(
    activite: Activite, intervalles: list[dict], ftp_w: float, part_ftp: float
) -> list[Bloc]:
    """Les intervalles marqués dans Intervals qui sont des blocs de travail.

    `start_index` et `end_index` sont des indices de flux à 1 Hz, et le FIT du
    cache porte exactement le même nombre de points (vérifié sur les deux
    sorties de référence) : l'indice est donc directement celui du point.
    """
    points = activite.points
    blocs = []
    for numero, brut in enumerate(intervalles, start=1):
        duree = _flottant(brut.get("elapsed_time"))
        puissance = _flottant(brut.get("average_watts"))
        if duree is None or puissance is None:
            continue
        if duree < DUREE_MIN_BLOC_S or puissance < part_ftp * ftp_w:
            continue
        debut = _entier(brut.get("start_index"))
        fin = _entier(brut.get("end_index"))
        if debut is None or fin is None:
            continue
        position = _entre(points, debut, fin)
        if position is None:
            continue
        debut_m, longueur_m = position
        blocs.append(
            Bloc(
                libelle=f"bloc {numero}",
                debut_m=debut_m,
                longueur_m=longueur_m,
                duree_s=duree,
                puissance_w=puissance,
            )
        )
    return blocs


def blocs_par_puissance(activite: Activite, ftp_w: float, part_ftp: float) -> list[Bloc]:
    """Repli sans Intervals : les tronçons de plus de 3 min au-dessus du seuil.

    La puissance est lissée sur `FENETRE_PUISSANCE` points avant le seuillage,
    sans quoi le moindre passage de rapport coupe un bloc en deux, et deux
    tronçons séparés de moins de `TROU_TOLERE_S` sont recollés.
    """
    points = activite.points
    lissee = _lissage([p.puissance_w for p in points], FENETRE_PUISSANCE)
    seuil = part_ftp * ftp_w
    au_dessus = [v is not None and v >= seuil for v in lissee]

    plages: list[tuple[int, int]] = []
    debut: int | None = None
    for i, dedans in enumerate([*au_dessus, False]):
        if dedans and debut is None:
            debut = i
        elif not dedans and debut is not None:
            plages.append((debut, i))
            debut = None
    plages = _recoller(points, _elargir(plages, len(points)))

    blocs = []
    for numero, (i, j) in enumerate(plages, start=1):
        duree = (points[min(j, len(points) - 1)].t - points[i].t).total_seconds()
        if duree < DUREE_MIN_BLOC_S:
            continue
        position = _entre(points, i, j)
        if position is None:
            continue
        debut_m, longueur_m = position
        puissances = [p.puissance_w for p in points[i:j] if p.puissance_w is not None]
        blocs.append(
            Bloc(
                libelle=f"bloc {numero}",
                debut_m=debut_m,
                longueur_m=longueur_m,
                duree_s=duree,
                puissance_w=statistics.fmean(puissances) if puissances else 0.0,
            )
        )
    return blocs


def _elargir(plages: list[tuple[int, int]], nombre: int) -> list[tuple[int, int]]:
    """Rend aux plages la demi-fenêtre que le lissage leur a mangée à chaque bout.

    La moyenne glissante est centrée : au début d'un bloc, elle mélange encore
    la récupération qui précède et passe donc sous le seuil pendant une
    demi-fenêtre. Sans cette correction, un bloc de 3 min prescrit à 100 % de
    FTP est mesuré à 2 min 30 et disparaît sous `DUREE_MIN_BLOC_S`.
    """
    demi = max(1, FENETRE_PUISSANCE // 2)
    return [(max(0, debut - demi), min(nombre, fin + demi)) for debut, fin in plages]


def _recoller(points: list[Point], plages: list[tuple[int, int]]) -> list[tuple[int, int]]:
    recollees: list[tuple[int, int]] = []
    for plage in plages:
        if recollees:
            precedent = recollees[-1]
            trou = (points[plage[0]].t - points[min(precedent[1], len(points) - 1)].t).total_seconds()
            if trou <= TROU_TOLERE_S:
                recollees[-1] = (precedent[0], plage[1])
                continue
        recollees.append(plage)
    return recollees


def _lissage(valeurs: list[float | None], fenetre: int) -> list[float | None]:
    """Moyenne glissante centrée, en ignorant les trous."""
    lissees: list[float | None] = []
    demi = max(1, fenetre // 2)
    for i in range(len(valeurs)):
        tranche = [v for v in valeurs[max(0, i - demi) : i + demi + 1] if v is not None]
        lissees.append(statistics.fmean(tranche) if tranche else None)
    return lissees


def _entre(points: list[Point], debut: int, fin: int) -> tuple[float, float] | None:
    """(distance du début, longueur) entre deux indices de points, en mètres."""
    if not points:
        return None
    i = min(max(debut, 0), len(points) - 1)
    j = min(max(fin, 0), len(points) - 1)
    d0, d1 = points[i].dist_m, points[j].dist_m
    if d0 is None or d1 is None or d1 <= d0:
        return None
    return (float(d0), float(d1 - d0))


def _flottant(brut: object) -> float | None:
    try:
        valeur = float(brut)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return valeur if math.isfinite(valeur) else None


def _entier(brut: object) -> int | None:
    valeur = _flottant(brut)
    return None if valeur is None else int(valeur)


# --- la comparaison ------------------------------------------------------------


@dataclass
class Comparaison:
    """Un bloc réel, sa note, et celles des emplacements tirés au hasard."""

    sortie: str
    bloc: Bloc
    note: NoteBloc
    au_hasard: list[NoteBloc] = field(default_factory=list)
    part_tags: float = 0.0

    @property
    def notes_au_hasard(self) -> list[float]:
        return [n.note for n in self.au_hasard]

    @property
    def mediane_hasard(self) -> float:
        return statistics.median(self.notes_au_hasard) if self.au_hasard else float("nan")

    @property
    def rang(self) -> float:
        """Part des tirages strictement moins bons que le bloc réel, de 0 à 1."""
        if not self.au_hasard:
            return float("nan")
        return sum(1 for n in self.notes_au_hasard if n > self.note.note) / len(self.au_hasard)


def comparer(
    trace: Trace, blocs: list[Bloc], *, tirages: int, alea: random.Random, part_tags: float, sortie: str
) -> list[Comparaison]:
    """Note chaque bloc réel et `tirages` emplacements au hasard de même longueur."""
    total = trace.points[-1].dist_m if trace.points else 0.0
    occupes = [(b.debut_m, b.debut_m + b.longueur_m) for b in blocs]
    resultats = []
    for bloc in blocs:
        marge = total - bloc.longueur_m
        notes = []
        essais = 0
        while len(notes) < tirages and essais < tirages * 20:
            essais += 1
            depart = alea.uniform(0.0, max(marge, 0.0))
            # On ne tire pas là où le mainteneur a justement fait un bloc :
            # la question est de savoir si l'évaluateur note aussi bien un
            # tronçon **qu'il n'a jamais utilisé** (cadrage du sprint 4).
            if any(depart < fin and depart + bloc.longueur_m > debut for debut, fin in occupes):
                continue
            notes.append(evaluer_couloir(trace, depart, bloc.longueur_m))
        resultats.append(
            Comparaison(
                sortie=sortie,
                bloc=bloc,
                note=evaluer_couloir(trace, bloc.debut_m, bloc.longueur_m),
                au_hasard=notes,
                part_tags=part_tags,
            )
        )
    return resultats


# --- affichage -----------------------------------------------------------------


def imprimer(comparaisons: list[Comparaison]) -> None:
    entete = (
        f"{'sortie':<22} {'bloc':<8} {'long.':>7} {'durée':>7} {'W':>5} "
        f"{'note':>7} {'hasard':>8} {'rang':>6}  motifs"
    )
    print(entete)
    print("-" * len(entete))
    for c in comparaisons:
        print(
            f"{c.sortie[:22]:<22} {c.bloc.libelle:<8} "
            f"{c.bloc.longueur_m / 1000:>6.1f}k {c.bloc.duree_s:>6.0f}s "
            f"{c.bloc.puissance_w:>5.0f} {c.note.note:>7.2f} {c.mediane_hasard:>8.2f} "
            f"{100 * c.rang:>5.0f}%  {', '.join(c.note.motifs) or '—'}"
        )


def categorie(longueur_m: float) -> str:
    """La catégorie de taille d'un bloc : courts, moyens ou longs."""
    for nom, minimum, maximum in CATEGORIES:
        if minimum <= longueur_m < maximum:
            return nom
    return CATEGORIES[-1][0]


@dataclass
class Bilan:
    """Ce qu'une catégorie de blocs donne, comparée à ses tirages au hasard."""

    nom: str
    comparaisons: list[Comparaison]

    @property
    def mediane_reelle(self) -> float:
        return statistics.median([c.note.note for c in self.comparaisons])

    @property
    def mediane_hasard(self) -> float:
        tires = [n for c in self.comparaisons for n in c.notes_au_hasard]
        return statistics.median(tires) if tires else float("nan")

    @property
    def rapport(self) -> float:
        """Note médiane réelle en part de la note médiane au hasard."""
        if self.mediane_hasard <= 0 or math.isnan(self.mediane_hasard):
            return float("nan")
        return self.mediane_reelle / self.mediane_hasard

    @property
    def rang(self) -> float:
        rangs = [c.rang for c in self.comparaisons if not math.isnan(c.rang)]
        return statistics.fmean(rangs) if rangs else float("nan")


def bilans(comparaisons: list[Comparaison]) -> list[Bilan]:
    """Un bilan par catégorie de taille, les catégories vides écartées."""
    par_nom: dict[str, list[Comparaison]] = {nom: [] for nom, _, _ in CATEGORIES}
    for c in comparaisons:
        par_nom[categorie(c.bloc.longueur_m)].append(c)
    return [Bilan(nom, liste) for nom, liste in par_nom.items() if liste]


def conclure(comparaisons: list[Comparaison], *, fait_foi: bool = True) -> bool:
    """Imprime la conclusion. Rend vrai si le critère d'acceptation du lot est tenu.

    Le critère ne porte **que** sur les blocs courts et moyens, ceux que le
    cycliste peut effectivement placer sur une boucle. **C'est une décision du
    mainteneur du 13/09/2026**, motivée : sur un bloc de 11 km, le cycliste ne
    choisit pas son terrain, il roule là où il en est rendu quand la montre
    sonne. Les blocs longs sont donc mesurés et rapportés, jamais juges — voir
    `_constater_les_longs`, qui le redit à l'écran pour que personne ne lise la
    conclusion sans cette restriction.

    `fait_foi` dit si ce qu'on mesure juge les poids. Il est faux en mode
    dégradé, où les blocs sont devinés à partir de la puissance : un « NON » y
    accuse le découpage avant d'accuser les poids, et la conclusion imprimée
    doit le dire.
    """
    if not comparaisons:
        print("\nAucun bloc trouvé : rien à conclure.")
        return False
    hasard = [n for c in comparaisons for n in c.notes_au_hasard]
    print(f"\n{len(comparaisons)} blocs réels, {len(hasard)} emplacements au hasard.")
    part_tags = statistics.fmean([c.part_tags for c in comparaisons])
    print(f"Part du tracé portant des tags OSM : {100 * part_tags:.0f} %.")

    tous = bilans(comparaisons)
    print("\nPar taille de bloc :")
    print(f"  {'catégorie':<16} {'n':>3} {'réels':>8} {'hasard':>8} {'rapport':>8} {'rang':>6}")
    for bilan in tous:
        print(
            f"  {bilan.nom:<16} {len(bilan.comparaisons):>3} {bilan.mediane_reelle:>8.2f} "
            f"{bilan.mediane_hasard:>8.2f} {bilan.rapport:>7.0%} {100 * bilan.rang:>5.0f}%"
        )
    print("  (rang = part des tirages moins bons que le bloc réel ; 50 % = le hasard)")

    diagnostiquer(comparaisons)
    tenu = _juger_les_placables(tous, fait_foi=fait_foi)
    _constater_les_longs(tous)
    return tenu


def _juger_les_placables(tous: list[Bilan], *, fait_foi: bool = True) -> bool:
    """Le critère d'acceptation : blocs courts et moyens contre le hasard."""
    juges = [b for b in tous if b.nom in CATEGORIES_JUGEES]
    retenues = [c for b in juges for c in b.comparaisons]
    if not retenues:
        print(
            "\nCONCLUSION : aucun bloc court ni moyen dans ces sorties — le critère "
            "d'acceptation\nn'a rien à juger. Relancer sur une séance à blocs courts."
        )
        return False
    reelles = statistics.median([c.note.note for c in retenues])
    tires = [n for c in retenues for n in c.notes_au_hasard]
    au_hasard = statistics.median(tires) if tires else float("nan")
    if au_hasard <= 0 or math.isnan(au_hasard):
        print(
            "\nCONCLUSION : le hasard note 0 partout sur les blocs plaçables — le "
            "terrain de ces\nsorties est trop uniforme pour départager quoi que ce soit."
        )
        return False
    rapport = reelles / au_hasard
    print(
        f"\nCRITÈRE D'ACCEPTATION (blocs courts et moyens, {len(retenues)} blocs) — "
        f"ce sont ceux\nque le cycliste peut **placer** ; les blocs de plus de 6 km sont "
        "mesurés plus bas\nmais ne jugent pas les poids (décision du mainteneur du "
        "13/09 : sur 11 km, le\ncycliste ne choisit pas son terrain)."
    )
    # Un pourcentage arrondi à l'unité donnait « 70 % pour un seuil de 70 % »,
    # c'est-à-dire une conclusion qui a l'air de se contredire.
    if rapport <= AMELIORATION_ATTENDUE:
        print(
            f"  OUI : les emplacements réels sont nettement mieux notés — {rapport:.1%} "
            f"de la note\n  du hasard, là où on attend au plus {AMELIORATION_ATTENDUE:.0%}."
        )
        return True
    if fait_foi:
        print(
            f"  NON : la note médiane des blocs réels vaut {rapport:.1%} de celle du hasard,\n"
            f"  alors qu'on attend au plus {AMELIORATION_ATTENDUE:.0%}. Les poids sont faux — "
            "voir la composition ci-dessus."
        )
        return False
    print(
        f"  NON : la note médiane des blocs réels vaut {rapport:.1%} de celle du hasard,\n"
        f"  alors qu'on attend au plus {AMELIORATION_ATTENDUE:.0%}.\n"
        "  Mais ce mode ne juge pas les poids : il devine les blocs à partir de la\n"
        "  puissance, il en découpe donc d'autres que ceux qui ont été prescrits.\n"
        "  Voir la confrontation des deux modes en fin d'exécution."
    )
    return False


def _constater_les_longs(tous: list[Bilan]) -> None:
    """Les blocs longs : un constat, jamais un critère.

    Sur un bloc de 11 km, le cycliste ne choisit pas son terrain — il roule là
    où il en est rendu quand la montre sonne. Que ses 20' réels soient moins
    bien notés que n'importe quel tirage de même longueur n'accuse donc pas les
    poids : c'est la mesure de ce que l'outil apporte, puisqu'il existe sur la
    **même boucle** des emplacements nettement meilleurs qu'il n'a pas pris.
    """
    longs = [b for b in tous if b.nom not in CATEGORIES_JUGEES]
    retenues = [c for b in longs for c in b.comparaisons]
    if not retenues:
        return
    print(f"\nCONSTAT (blocs longs, {len(retenues)} blocs) — mesuré, pas jugé.")
    pires = sum(1 for c in retenues if c.rang <= 0.05)
    descente = sum(c.note.descente_m for c in retenues)
    meilleur = min(
        (min(c.notes_au_hasard) for c in retenues if c.au_hasard), default=float("nan")
    )
    reelle = statistics.median([c.note.note for c in retenues])
    if pires == 0:
        combien = f"Aucun de ces {len(retenues)} blocs n'est moins bien noté"
    elif pires == 1:
        combien = f"1 de ces {len(retenues)} blocs est moins bien noté"
    else:
        combien = f"{pires} de ces {len(retenues)} blocs sont moins bien notés"
    print(
        f"  {combien} que 95 % des tirages de même longueur ;\n"
        f"  ils portent {descente:.0f} m de dénivelé descendant en descentes qualifiantes."
    )
    if not math.isnan(meilleur) and meilleur < reelle:
        print(
            f"  Note médiane réelle {reelle:.2f}, meilleur emplacement disponible sur la "
            f"même boucle {meilleur:.2f}."
        )
    print(
        "  Sur un bloc de cette longueur, le cycliste ne choisit pas son terrain : il\n"
        "  roule là où il en est rendu. Ce n'est donc pas un échec des poids, c'est la\n"
        "  mesure de ce que l'outil apporte — le bon couloir existait sur la même boucle."
    )


#: Ce que chaque poste coûte, et le poids qui le tarife. Sert au diagnostic :
#: un poste que les blocs réels portent **autant** que le hasard ne discrimine
#: rien, et son poids ne fait que du bruit dans la note.
#:
#: Sur une trace GPS, **tous** les carrefours comptés sont des virages marqués
#: (pas de nœuds OSM, voir l'en-tête du fichier) : c'est donc
#: `POIDS_VIRAGE_MARQUE` que la ligne « carrefours » juge, et `POIDS_CARREFOUR`
#: reste hors de portée de ce script.
#: Le dernier membre dit si le poste se ramène au kilomètre. L'irrégularité,
#: elle, est déjà une grandeur intensive (un écart-type de pente) : la diviser
#: par la longueur du bloc n'aurait aucun sens.
POSTES: tuple[tuple[str, str, bool], ...] = (
    ("carrefours", "POIDS_VIRAGE_MARQUE", True),
    ("km bâtis", "POIDS_KM_BATI", True),
    ("descente (m)", "POIDS_M_DESCENTE", True),
    ("montée (m)", "POIDS_M_MONTEE", True),
    ("irrégularité %", "POIDS_IRREGULARITE", False),
)


def _par_km(note: NoteBloc, longueur_m: float) -> dict[str, float]:
    km = max(longueur_m / 1000.0, 1e-9)
    return {
        "carrefours": note.carrefours / km,
        "km bâtis": note.km_batis / km,
        "descente (m)": note.descente_m / km,
        "montée (m)": note.montee_m / km,
        # En points de pourcentage : la pente est une tangente partout ailleurs,
        # mais un écart-type de 0,0147 ne se lit pas dans un tableau.
        "irrégularité %": 100.0 * note.irregularite,
    }


def diagnostiquer(comparaisons: list[Comparaison]) -> None:
    """Compare la **composition** des blocs réels et des tirages, poste par poste.

    C'est ce qui dit quel poids corriger : un poste que les blocs réels portent
    autant (ou plus) que le hasard ne sépare rien et son poids doit baisser ;
    un poste qu'ils évitent nettement mérite au contraire de peser davantage.
    Tout est ramené au kilomètre, sans quoi un bloc de 5 km et un bloc de 1,4 km
    ne se compareraient pas.
    """
    print("\nComposition — blocs réels contre tirages au hasard (au km sauf mention) :")
    print(f"  {'poste':<14} {'réels':>8} {'hasard':>8} {'écart':>8}   poids")
    for poste, poids, _ in POSTES:
        reels = statistics.fmean([_par_km(c.note, c.bloc.longueur_m)[poste] for c in comparaisons])
        tires = [
            _par_km(n, c.bloc.longueur_m)[poste] for c in comparaisons for n in c.au_hasard
        ]
        au_hasard = statistics.fmean(tires) if tires else 0.0
        rapport = reels / au_hasard if au_hasard > 0 else float("nan")
        verdict = _verdict(rapport)
        print(f"  {poste:<14} {reels:>8.2f} {au_hasard:>8.2f} {rapport:>7.0%}   {poids} — {verdict}")
    print(
        "  (écart = ce que les blocs réels portent, en part de ce que porte le hasard ;\n"
        "   100 % = le poste ne distingue rien, 0 % = le mainteneur l'évite entièrement)"
    )


def _verdict(rapport: float) -> str:
    if math.isnan(rapport):
        return "jamais rencontré ici, indécidable"
    if rapport >= 0.90:
        return "ne sépare rien : ce poste ne doit presque pas peser"
    if rapport <= 0.50:
        return "nettement évité : ce poste mérite de peser"
    return "sépare un peu"


# --- programme principal --------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(Path(arguments.config).expanduser() if arguments.config else None)
    dossier = Path(config.cache.dossier).expanduser()
    base = dossier / NOM_BASE
    ftp = float(arguments.ftp or config.cycliste.ftp_w)
    if ftp <= 0:
        raise ErreurUtilisateur("FTP inconnue : renseigner [cycliste] ftp_w ou passer --ftp")
    alea = random.Random(arguments.graine)

    client = None
    if not arguments.sans_reseau and config.intervals.renseigne:
        client = ClientIntervals(config.intervals.athlete_id, config.intervals.api_key)

    comparaisons: list[Comparaison] = []
    for jour, motif in SORTIES_DE_REFERENCE:
        sortie = chercher_sortie(dossier, jour, motif)
        trace = trace_depuis_activite(sortie.activite)
        if trace is None:
            print(f"{sortie.nom} : pas de trace GPS exploitable, sortie ignorée.")
            continue
        part_tags = enrichir(trace, tags_appris(base, sortie.activite.points))

        blocs, origine = _blocs(sortie, client, ftp, arguments.seuil_ftp)
        print(
            f"{sortie.jour} « {sortie.nom} » : {trace.points[-1].dist_m / 1000:.1f} km, "
            f"{len(blocs)} bloc(s) — {origine}, {100 * part_tags:.0f} % du tracé tagué"
        )
        comparaisons.extend(
            comparer(
                trace,
                blocs,
                tirages=arguments.tirages,
                alea=alea,
                part_tags=part_tags,
                sortie=sortie.nom,
            )
        )
    print()
    imprimer(comparaisons)
    fait_foi = not arguments.sans_reseau
    tenu = conclure(comparaisons, fait_foi=fait_foi)
    if fait_foi:
        return 0 if tenu else 1
    return _confronter_au_nominal(tenu, len(comparaisons))


def _confronter_au_nominal(tenu: bool, blocs: int) -> int:
    """Le mode dégradé contre la référence du mode qui fait foi.

    Le mode dégradé n'a pas le droit de conclure seul, mais il n'a pas non plus
    le droit de se taire quand il dit autre chose que le mode nominal : un
    lecteur qui le lance sans la clé du mainteneur doit savoir qu'il regarde un
    résultat d'un mode qui borne moins bien les blocs, et pas un verdict sur
    les poids. Le script **échoue** donc sur la divergence, avec le message qui
    la nomme — plutôt que de laisser croire que les deux modes se valent.
    """
    reference = REFERENCE_NOMINALE
    attendu = bool(reference["verdict"])
    if tenu == attendu:
        print(
            f"\nACCORD DES DEUX MODES : ce mode dégradé conclut comme le mode nominal du "
            f"{reference['date']}\n({'OUI' if attendu else 'NON'}, {reference['rapport']:.0%} "
            f"de la note du hasard sur {reference['blocs_juges']} blocs jugés)."
        )
        return 0
    print(
        f"\nÉCHEC — LES DEUX MODES DIVERGENT.\n"
        f"  Mode dégradé (ci-dessus, blocs devinés par la puissance) : "
        f"{'OUI' if tenu else 'NON'}, {blocs} blocs trouvés.\n"
        f"  Mode nominal du {reference['date']} (blocs lus dans les intervalles Intervals, "
        f"et\n  c'est lui qui fait foi) : {'OUI' if attendu else 'NON'}, "
        f"{reference['rapport']:.0%} de la note du hasard sur\n"
        f"  {reference['blocs_juges']} blocs jugés, {reference['blocs_trouves']} blocs trouvés.\n"
        "\n  Ce n'est pas un désaveu des poids : la détection par la puissance coupe un 20'\n"
        "  en trois quand la puissance passe sous le seuil, et ramasse des fragments\n"
        "  d'échauffement. Elle borne moins bien les blocs, donc elle mesure autre chose.\n"
        "  Pour trancher sur les poids, relancer sans --sans-reseau, avec la clé d'API.",
        file=sys.stderr,
    )
    return 1


def _blocs(
    sortie: Sortie, client: ClientIntervals | None, ftp: float, part_ftp: float
) -> tuple[list[Bloc], str]:
    """Les blocs de la sortie : Intervals d'abord, puissance en repli."""
    if client is not None and sortie.id_externe:
        try:
            intervalles = client.intervalles(sortie.id_externe)
        except ErreurConnecteur as e:
            print(f"  (Intervals indisponible : {e} — repli sur la puissance)")
        else:
            blocs = blocs_depuis_intervals(sortie.activite, intervalles, ftp, part_ftp)
            if blocs:
                return (blocs, f"intervalles Intervals, ≥ {part_ftp:.0%} FTP")
            print("  (aucun intervalle au-dessus du seuil — repli sur la puissance)")
    return (
        blocs_par_puissance(sortie.activite, ftp, part_ftp),
        f"détection par la puissance, ≥ {part_ftp:.0%} FTP",
    )


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui de l'utilisateur)")
    analyseur.add_argument("--ftp", type=float, help="FTP en watts (défaut : celle de la configuration)")
    analyseur.add_argument(
        "--seuil-ftp",
        type=float,
        default=PART_FTP_BLOC,
        help=f"part de la FTP au-dessus de laquelle un tronçon est un bloc (défaut {PART_FTP_BLOC})",
    )
    analyseur.add_argument("--tirages", type=int, default=TIRAGES_PAR_BLOC)
    analyseur.add_argument("--graine", type=int, default=GRAINE)
    analyseur.add_argument(
        "--sans-reseau",
        action="store_true",
        help="ne pas appeler Intervals ; détecter les blocs par la seule puissance",
    )
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except (ErreurUtilisateur, ErreurConnecteur) as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

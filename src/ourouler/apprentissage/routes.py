"""Routes connues : apprendre des sorties passées quelles routes le cycliste accepte.

Le principe (contrat du sprint 3 §2) : rejouer les sorties extérieures du
cache dans BRouter — points de passage tous les 1 500 m — pour obtenir les
**tags OSM** des routes réellement parcourues, puis comparer ce que le
cycliste prend à ce que le moteur lui propose. Les étiquettes OSM ne sont pas
la vérité : les traces le sont, et ce sont elles qui fixent les poids.

Trois précautions, qui sont le cœur du lot :

1. **« Inconnu » n'est jamais un malus.** Les traces du mainteneur couvrent
   le sud et l'ouest de Rennes ; s'en servir comme critère pénaliserait toute
   boucle vers le nord ou l'est. `part_connue` est **informative**, elle
   n'entre dans aucun score.
2. **On ne lit aucun chemin, et on n'en fabrique aucun.** `BaseRoutes` reçoit
   un `Path` déjà résolu, `apprendre` reçoit un `Cache`, un `ClientBrouter` et
   une `Config`. Les *noms* des fichiers du cache vivent eux aussi dans
   `apprentissage/commande.py` : écrire le nom du fichier de base ou celui
   des poids ici, ce serait savoir où l'on tourne — la règle absolue 2 de
   CLAUDE.md contournée par une chaîne. La ligne de commande sait où vivent
   les fichiers ; le cœur non.
3. **Une ignorance se dit.** Une sortie qu'on n'a pas su rejouer est comptée
   dans le rapport ; elle ne disparaît pas en silence.

Maille et tronçon. Une maille fait ~30 m de côté : `(round(lat × 3000),
round(lon × 3000))`. Un **tronçon** est une maille **avec ses tags** : la
même maille traversée par une `tertiary` et par une `secondary` donne deux
lignes, et les kilométrages par classe restent exacts sans qu'on ait à
arbitrer entre deux étiquettes pour un carré de 30 m.

Les kilomètres comptés sont des **kilomètres roulés** : une route prise dix
fois pèse dix fois. C'est voulu — on mesure une pratique, pas un réseau.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from ourouler.activites.cache import Cache, EntreeCache
from ourouler.activites.inventaire import en_interieur
from ourouler.activites.modele import Activite, est_sport_velo
from ourouler.boucle.couts import POIDS_HIGHWAY_DEFAUT
from ourouler.boucle.trace import PointTrace, Trace, distance_m
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur, ErreurLecture, ErreurUtilisateur

#: Facteur de la maille : 1/3000 de degré ≈ 37 m en latitude, ~37 m en
#: longitude à nos latitudes. « ~30 m » du contrat, au degré de précision près.
MAILLE = 3000

#: Espacement des points de passage envoyés à BRouter pour rejouer une sortie.
ESPACEMENT_PASSAGE_M = 1500.0

#: Nombre maximal de points de passage par appel (limite du moteur).
PASSAGES_MAX = 60

#: En dessous, une sortie n'apprend rien qui vaille un appel au serveur.
DISTANCE_MIN_M = 3000.0

#: Pas de découpe d'un segment pour l'attribution aux mailles : une demi-maille,
#: pour qu'aucune maille traversée ne soit sautée quel que soit l'espacement
#: des points du tracé.
PAS_ECHANTILLON_M = 15.0

#: Libellé des tags absents, côté base comme côté statistiques. SQLite accepte
#: des NULL dans une clé primaire (et casse alors l'unicité) : on stocke une
#: chaîne vide, qu'on retraduit en `None` à la lecture.
SANS_TAG = ""

#: Ce qu'on affiche pour une classe sans `highway`.
LIBELLE_SANS_HIGHWAY = "(sans highway)"

#: Plafond du poids appris, en kilomètres équivalents par kilomètre.
POIDS_MAX = 4.0

#: Classe de référence : le cycliste roule dessus par défaut, elle ne coûte
#: rien. Le contrat la force à 0 quoi que disent les mesures.
HIGHWAY_REFERENCE = "tertiary"

#: Version du schéma SQLite de la base de routes.
VERSION_SCHEMA = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS troncons (
    cle_lat          INTEGER NOT NULL,
    cle_lon          INTEGER NOT NULL,
    highway          TEXT NOT NULL,
    surface          TEXT NOT NULL,
    maxspeed         TEXT NOT NULL,
    cout_km          REAL,
    passages         INTEGER NOT NULL DEFAULT 0,
    passages_semaine INTEGER NOT NULL DEFAULT 0,
    metres           REAL NOT NULL DEFAULT 0,
    metres_semaine   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (cle_lat, cle_lon, highway, surface, maxspeed)
);
CREATE INDEX IF NOT EXISTS idx_troncons_maille ON troncons(cle_lat, cle_lon);
CREATE TABLE IF NOT EXISTS sorties (
    id_sortie  TEXT PRIMARY KEY,
    jour       TEXT,
    mailles    INTEGER NOT NULL DEFAULT 0,
    metres     REAL NOT NULL DEFAULT 0,
    ajoutee_le TEXT NOT NULL
);
"""


# --- modèle -------------------------------------------------------------------


@dataclass
class Troncon:
    """Une maille avec ses tags : ce que le cycliste a roulé, et combien de fois.

    `metres` et `metres_semaine` ne sont pas au contrat mais portent la mesure
    dont vivent les statistiques : compter en mailles supposerait qu'elles
    font toutes la même longueur, ce qui est faux dès qu'on coupe un coin.
    """

    cle: tuple[int, int]
    highway: str
    surface: str | None
    maxspeed: str | None
    cout_km: float | None
    passages: int
    passages_semaine: int  # lundi-vendredi
    metres: float = 0.0
    metres_semaine: float = 0.0


@dataclass
class Statistiques:
    """Kilomètres roulés par classe de route, de vitesse et de revêtement.

    Les parts se lisent sur `km_total` ; la « part semaine » d'une classe est
    la part de **ses** kilomètres faits du lundi au vendredi.
    """

    km_total: float = 0.0
    km_semaine: float = 0.0
    mailles: int = 0
    sorties: int = 0
    km_par_highway: dict[str, float] = field(default_factory=dict)
    km_semaine_par_highway: dict[str, float] = field(default_factory=dict)
    km_par_maxspeed: dict[str, float] = field(default_factory=dict)
    km_par_surface: dict[str, float] = field(default_factory=dict)
    cout_km_moyen: float | None = None

    def part(self, highway: str) -> float:
        """Part des kilomètres roulés sur cette classe, entre 0 et 1."""
        if self.km_total <= 0:
            return 0.0
        return self.km_par_highway.get(highway, 0.0) / self.km_total

    def part_semaine(self, highway: str) -> float:
        """Part des kilomètres **de cette classe** faits en semaine, entre 0 et 1."""
        km = self.km_par_highway.get(highway, 0.0)
        if km <= 0:
            return 0.0
        return self.km_semaine_par_highway.get(highway, 0.0) / km

    def classes(self) -> list[str]:
        """Les `highway` rencontrés, du plus roulé au moins roulé."""
        return [c for c, _ in sorted(self.km_par_highway.items(), key=lambda kv: (-kv[1], kv[0]))]


@dataclass
class RapportApprentissage:
    """Ce qu'une passe d'apprentissage a vu, appris, ignoré et raté."""

    sorties_vues: int = 0
    sorties_apprises: int = 0
    sorties_deja_connues: int = 0
    echecs: int = 0
    km: float = 0.0
    mailles: int = 0
    messages: list[str] = field(default_factory=list)


# --- maille -------------------------------------------------------------------


def cle_maille(lat: float, lon: float) -> tuple[int, int]:
    """La maille ~30 m qui contient ce point : `(round(lat × 3000), round(lon × 3000))`.

    L'arrondi de Python est « au pair le plus proche » : c'est sans importance
    ici, seule la **stabilité** compte — deux passages au même endroit doivent
    tomber dans la même maille, quelle que soit la convention.
    """
    return (round(lat * MAILLE), round(lon * MAILLE))


def _mailles_traversees(a: PointTrace, b: PointTrace, longueur: float) -> list[tuple[int, int]]:
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


def _par_intervalle(trace: Trace) -> list[tuple[dict[str, str], float | None]]:
    """Les tags et le coût du tronçon couvrant chaque **intervalle** `[i, i+1]`.

    Par intervalle et non par point : un point de jonction appartient aux deux
    tronçons voisins, et attribuer par point rangeait tout l'intervalle suivant
    sous les tags du tronçon précédent — une `secondary` disparaissait dans la
    `tertiary` qui la précédait. Un intervalle, lui, n'a qu'un tronçon.
    """
    n = max(0, len(trace.points) - 1)
    par_intervalle: list[tuple[dict[str, str], float | None] | None] = [None] * n
    for segment in trace.segments:
        debut = max(0, segment.debut_idx)
        fin = min(n, segment.fin_idx)
        for i in range(debut, fin):
            if par_intervalle[i] is None:  # en cas de recouvrement, le premier gagne
                par_intervalle[i] = (segment.tags, segment.cout_km)
    return [({}, None) if x is None else x for x in par_intervalle]


@dataclass
class _Morceau:
    """Un bout de tracé dans une maille, avec les tags de son tronçon."""

    cle: tuple[int, int]
    highway: str
    surface: str
    maxspeed: str
    metres: float
    cout_km: float | None


def _decouper(trace: Trace) -> list[_Morceau]:
    """Le tracé découpé en morceaux (maille, tags), longueurs cumulées.

    Chaque paire de points consécutifs est attribuée à la maille de son
    **milieu** : à 30 m de maille et quelques mètres entre deux points d'un
    tracé BRouter, la différence avec une découpe exacte est en dessous du
    bruit, pour un code dix fois plus simple.
    """
    par_intervalle = _par_intervalle(trace)
    cumul: dict[tuple, _Morceau] = {}
    for i in range(len(trace.points) - 1):
        a, b = trace.points[i], trace.points[i + 1]
        longueur = distance_m(a, b)
        if not math.isfinite(longueur) or longueur <= 0:
            continue
        t, cout_km = par_intervalle[i]
        highway = str(t.get("highway", SANS_TAG) or SANS_TAG)
        surface = str(t.get("surface", SANS_TAG) or SANS_TAG)
        maxspeed = str(t.get("maxspeed", SANS_TAG) or SANS_TAG)
        mailles = _mailles_traversees(a, b, longueur)
        part = longueur / len(mailles)
        for cle in mailles:
            identite = (cle, highway, surface, maxspeed)
            connu = cumul.get(identite)
            if connu is None:
                cumul[identite] = _Morceau(
                    cle=cle,
                    highway=highway,
                    surface=surface,
                    maxspeed=maxspeed,
                    metres=part,
                    cout_km=cout_km,
                )
            else:
                connu.metres += part
                if connu.cout_km is None:
                    connu.cout_km = cout_km
    return list(cumul.values())


# --- base ---------------------------------------------------------------------


class BaseRoutes:
    """Les tronçons déjà roulés, dans un SQLite dont on reçoit le chemin."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ErreurUtilisateur(
                f"routes : dossier {self.chemin.parent} inutilisable ({e})"
            ) from e
        with self._connexion() as cx:
            version = cx.execute("PRAGMA user_version").fetchone()[0]
            if version > VERSION_SCHEMA:
                raise ErreurUtilisateur(
                    f"routes : base {self.chemin} au schéma {version}, attendu "
                    f"{VERSION_SCHEMA} — supprimer le fichier la reconstruira "
                    "(`ourouler routes apprendre` la remplit à nouveau)"
                )
            cx.executescript(_SCHEMA)
            cx.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")

    # --- écriture -------------------------------------------------------------

    def ajouter_trace(self, trace: Trace, *, jour: date, id_sortie: str) -> int:
        """Enregistre les tronçons d'un tracé rejoué. Renvoie le nombre de mailles.

        **Idempotent par `id_sortie`** : rejouer deux fois la même sortie ne
        double pas ses passages. Le second appel rend le nombre de mailles
        déjà enregistré sans rien toucher — c'est ce qui permet de relancer
        `ourouler routes apprendre` sans réfléchir.
        """
        id_sortie = str(id_sortie)
        if not id_sortie:
            raise ErreurUtilisateur("routes : une sortie sans identifiant ne peut pas être apprise")
        deja = self._mailles_de(id_sortie)
        if deja is not None:
            return deja

        morceaux = _decouper(trace)
        semaine = 1 if _en_semaine(jour) else 0
        mailles = len({m.cle for m in morceaux})
        metres = sum(m.metres for m in morceaux)
        with self._connexion() as cx:
            for m in morceaux:
                cx.execute(
                    "INSERT INTO troncons (cle_lat, cle_lon, highway, surface, maxspeed, "
                    "cout_km, passages, passages_semaine, metres, metres_semaine) "
                    "VALUES (?,?,?,?,?,?,1,?,?,?) "
                    "ON CONFLICT(cle_lat, cle_lon, highway, surface, maxspeed) DO UPDATE SET "
                    # Moyenne du coût pondérée par les mètres : une valeur
                    # absente d'un côté laisse l'autre en place plutôt que de
                    # la remplacer par du vide.
                    "cout_km = CASE "
                    "  WHEN excluded.cout_km IS NULL THEN troncons.cout_km "
                    "  WHEN troncons.cout_km IS NULL THEN excluded.cout_km "
                    "  ELSE (troncons.cout_km * troncons.metres + excluded.cout_km * excluded.metres)"
                    "       / NULLIF(troncons.metres + excluded.metres, 0) END, "
                    "passages = troncons.passages + 1, "
                    "passages_semaine = troncons.passages_semaine + excluded.passages_semaine, "
                    "metres = troncons.metres + excluded.metres, "
                    "metres_semaine = troncons.metres_semaine + excluded.metres_semaine",
                    (
                        m.cle[0],
                        m.cle[1],
                        m.highway,
                        m.surface,
                        m.maxspeed,
                        m.cout_km,
                        semaine,
                        m.metres,
                        m.metres * semaine,
                    ),
                )
            cx.execute(
                "INSERT INTO sorties (id_sortie, jour, mailles, metres, ajoutee_le) "
                "VALUES (?,?,?,?,?) ON CONFLICT(id_sortie) DO NOTHING",
                (
                    id_sortie,
                    jour.isoformat(),
                    mailles,
                    metres,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                ),
            )
        return mailles

    # --- lecture --------------------------------------------------------------

    def sorties_apprises(self) -> set[str]:
        with self._connexion() as cx:
            return {ligne[0] for ligne in cx.execute("SELECT id_sortie FROM sorties")}

    def troncons(self) -> list[Troncon]:
        with self._connexion() as cx:
            lignes = cx.execute(
                "SELECT cle_lat, cle_lon, highway, surface, maxspeed, cout_km, "
                "passages, passages_semaine, metres, metres_semaine FROM troncons"
            ).fetchall()
        return [_troncon(ligne) for ligne in lignes]

    def statistiques(self) -> Statistiques:
        """Kilomètres roulés par `highway`, `maxspeed` et `surface`, et part semaine."""
        stats = Statistiques()
        with self._connexion() as cx:
            stats.sorties = cx.execute("SELECT COUNT(*) FROM sorties").fetchone()[0]
            stats.mailles = cx.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT cle_lat, cle_lon FROM troncons)"
            ).fetchone()[0]
            lignes = cx.execute(
                "SELECT highway, surface, maxspeed, cout_km, metres, metres_semaine FROM troncons"
            ).fetchall()
        cout_pondere = 0.0
        metres_avec_cout = 0.0
        for highway, surface, maxspeed, cout_km, metres, metres_semaine in lignes:
            km = (metres or 0.0) / 1000.0
            km_semaine = (metres_semaine or 0.0) / 1000.0
            stats.km_total += km
            stats.km_semaine += km_semaine
            _ajouter(stats.km_par_highway, highway, km)
            _ajouter(stats.km_semaine_par_highway, highway, km_semaine)
            _ajouter(stats.km_par_maxspeed, maxspeed, km)
            _ajouter(stats.km_par_surface, surface, km)
            if cout_km is not None and metres:
                cout_pondere += cout_km * metres
                metres_avec_cout += metres
        stats.cout_km_moyen = cout_pondere / metres_avec_cout if metres_avec_cout > 0 else None
        return stats

    def part_connue(self, trace: Trace) -> float:
        """Part des kilomètres d'un tracé passant par des mailles déjà roulées.

        **Informatif seulement.** Le contrat l'interdit dans tout score : les
        traces ne couvrent qu'une partie du territoire, et pénaliser l'inconnu
        condamnerait d'avance toute direction jamais explorée.

        Un tracé vide, ou de longueur nulle, rend 0,0 — pas une division par
        zéro, et pas 1,0 : on ne connaît rien de ce qu'on n'a pas mesuré.
        """
        paires: list[tuple[tuple[int, int], float]] = []
        for i in range(len(trace.points) - 1):
            a, b = trace.points[i], trace.points[i + 1]
            longueur = distance_m(a, b)
            if not math.isfinite(longueur) or longueur <= 0:
                continue
            mailles = _mailles_traversees(a, b, longueur)
            part = longueur / len(mailles)
            paires.extend((cle, part) for cle in mailles)
        total = sum(longueur for _, longueur in paires)
        if total <= 0:
            return 0.0
        connues = self._mailles_connues({cle for cle, _ in paires})
        connu = sum(longueur for cle, longueur in paires if cle in connues)
        return connu / total

    # --- interne --------------------------------------------------------------

    def _mailles_de(self, id_sortie: str) -> int | None:
        with self._connexion() as cx:
            ligne = cx.execute(
                "SELECT mailles FROM sorties WHERE id_sortie = ?", (id_sortie,)
            ).fetchone()
        return None if ligne is None else int(ligne[0])

    def _mailles_connues(self, cles: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Celles des `cles` qui sont dans la base.

        On interroge par **bande de latitude** plutôt que maille par maille :
        un tracé de 60 km en compte quelques milliers, un `SELECT` par maille
        serait absurde, et charger toute la base le serait tout autant.
        """
        if not cles:
            return set()
        latitudes = sorted({cle[0] for cle in cles})
        trouvees: set[tuple[int, int]] = set()
        with self._connexion() as cx:
            for paquet in _paquets(latitudes, 400):
                marques = ",".join("?" * len(paquet))
                lignes = cx.execute(
                    f"SELECT DISTINCT cle_lat, cle_lon FROM troncons WHERE cle_lat IN ({marques})",
                    paquet,
                ).fetchall()
                trouvees.update((int(a), int(b)) for a, b in lignes)
        return trouvees & cles

    @contextmanager
    def _connexion(self) -> Iterator[sqlite3.Connection]:
        """Connexion SQLite le temps d'une opération, erreurs traduites."""
        try:
            cx = sqlite3.connect(self.chemin)
        except sqlite3.Error as e:
            raise ErreurUtilisateur(f"routes : base {self.chemin} inutilisable ({e})") from e
        try:
            yield cx
            cx.commit()
        except sqlite3.Error as e:
            cx.rollback()
            raise ErreurUtilisateur(
                f"routes : base {self.chemin} illisible ou corrompue ({e}) — "
                "la supprimer et relancer `ourouler routes apprendre` la reconstruira"
            ) from e
        finally:
            cx.close()


def _troncon(ligne: tuple) -> Troncon:
    (
        cle_lat,
        cle_lon,
        highway,
        surface,
        maxspeed,
        cout_km,
        passages,
        passages_semaine,
        metres,
        metres_semaine,
    ) = ligne
    return Troncon(
        cle=(int(cle_lat), int(cle_lon)),
        highway=highway,
        surface=surface or None,
        maxspeed=maxspeed or None,
        cout_km=cout_km,
        passages=int(passages),
        passages_semaine=int(passages_semaine),
        metres=float(metres or 0.0),
        metres_semaine=float(metres_semaine or 0.0),
    )


def _ajouter(compteur: dict[str, float], cle: str, valeur: float) -> None:
    compteur[cle] = compteur.get(cle, 0.0) + valeur


def _paquets(valeurs: Sequence, taille: int) -> Iterator[list]:
    for debut in range(0, len(valeurs), taille):
        yield list(valeurs[debut : debut + taille])


def _en_semaine(jour: date) -> bool:
    """Lundi-vendredi. Le mainteneur : « surtout en semaine ; le dimanche à 90 % »."""
    return jour.weekday() < 5


# --- apprentissage ------------------------------------------------------------


def points_de_passage(
    activite: Activite,
    *,
    espacement_m: float = ESPACEMENT_PASSAGE_M,
    maximum: int = PASSAGES_MAX,
) -> list[tuple[float, float]]:
    """Les points à donner à BRouter pour rejouer une sortie, `maximum` au plus.

    Un point tous les `espacement_m`, plus le premier et le dernier : assez
    pour que le moteur retrouve les mêmes routes, assez peu pour tenir dans un
    appel. Au-delà de `maximum`, on ré-échantillonne régulièrement plutôt que
    de tronquer — tronquer rendrait un itinéraire qui s'arrête au milieu, donc
    des tags faux sur la fin de la sortie.
    """
    geolocalises = [p for p in activite.points if p.lat is not None and p.lon is not None]
    if len(geolocalises) < 2:
        return []
    retenus = [geolocalises[0]]
    cumul = 0.0
    for a, b in zip(geolocalises[:-1], geolocalises[1:], strict=True):
        cumul += distance_m(
            PointTrace(a.lat, a.lon, None, 0.0), PointTrace(b.lat, b.lon, None, 0.0)
        )
        if cumul >= espacement_m:
            retenus.append(b)
            cumul = 0.0
    if retenus[-1] is not geolocalises[-1]:
        retenus.append(geolocalises[-1])
    if len(retenus) > maximum:
        pas = math.ceil(len(retenus) / (maximum - 1))
        allege = retenus[::pas]
        if allege[-1] is not retenus[-1]:
            allege.append(retenus[-1])
        retenus = allege
    return [(float(p.lat), float(p.lon)) for p in retenus]


def sorties_a_apprendre(cache: Cache, config: Config, *, depuis: date) -> list[EntreeCache]:
    """Les sorties **extérieures** du cache qui valent un rejeu, les plus anciennes d'abord.

    Le home-trainer est exclu (il n'a pas de route), les autres sports aussi,
    et les sorties de moins de `DISTANCE_MIN_M` : elles n'apprennent rien qui
    justifie un appel au serveur du mainteneur.
    """
    del config  # la sélection ne dépend d'aucun réglage pour l'instant
    retenues = []
    for entree in cache.lister(depuis=depuis):
        if not est_sport_velo(entree.sport) or en_interieur(entree):
            continue
        if entree.jour is None or (entree.distance_m or 0.0) < DISTANCE_MIN_M:
            continue
        retenues.append(entree)
    return retenues


def apprendre(
    cache: Cache,
    client: ClientBrouter,
    base: BaseRoutes,
    config: Config,
    *,
    depuis: date,
    max_sorties: int | None = None,
) -> RapportApprentissage:
    """Rejoue les sorties extérieures dans BRouter et enregistre leurs tronçons.

    Un appel par sortie. La passe est **idempotente** : les sorties déjà dans
    la base sont comptées `sorties_deja_connues` et sautées sans appel, donc
    relancer la commande ne coûte rien et ne fausse rien.

    Une sortie qu'on ne sait pas relire, ou que le moteur refuse, est comptée
    dans `echecs` avec son motif : elle ne fait pas échouer la passe, et elle
    ne disparaît pas non plus en silence (règle absolue 5).
    """
    rapport = RapportApprentissage()
    deja = base.sorties_apprises()
    candidates = sorties_a_apprendre(cache, config, depuis=depuis)
    rapport.sorties_vues = len(candidates)
    restantes = max_sorties

    for entree in candidates:
        if entree.identifiant in deja:
            rapport.sorties_deja_connues += 1
            continue
        if restantes is not None and restantes <= 0:
            continue
        jour = entree.jour
        if jour is None:  # pragma: no cover - filtré par `sorties_a_apprendre`
            continue
        try:
            activite = cache.relire(entree.identifiant)
        except (ErreurLecture, ErreurUtilisateur, KeyError, OSError) as e:
            rapport.echecs += 1
            rapport.messages.append(f"{jour} {entree.identifiant[:12]} : illisible ({e})")
            continue
        passages = points_de_passage(activite)
        if len(passages) < 2:
            rapport.echecs += 1
            rapport.messages.append(
                f"{jour} {entree.identifiant[:12]} : aucune position exploitable"
            )
            continue
        try:
            trace = client.itineraire(passages)
        except ErreurConnecteur as e:
            rapport.echecs += 1
            rapport.messages.append(f"{jour} {entree.identifiant[:12]} : {e}")
            continue
        if restantes is not None:
            restantes -= 1
        rapport.mailles += base.ajouter_trace(trace, jour=jour, id_sortie=entree.identifiant)
        rapport.sorties_apprises += 1
        rapport.km += trace.distance_m / 1000.0
    return rapport


# --- poids --------------------------------------------------------------------


def statistiques_de_traces(traces: Iterable[Trace], *, jour: date | None = None) -> Statistiques:
    """Des `Statistiques` bâties sur des tracés bruts, sans passer par la base.

    C'est ainsi qu'on mesure l'**exposition** : ce que le moteur propose dans
    toutes les directions, à comparer à ce que le cycliste prend vraiment.
    Aucune écriture, aucune maille : on somme les segments tels quels.
    """
    stats = Statistiques()
    semaine = jour is not None and _en_semaine(jour)
    cout_pondere = 0.0
    metres_avec_cout = 0.0
    for trace in traces:
        stats.sorties += 1
        for segment in trace.segments:
            metres = segment.longueur_m
            if not isinstance(metres, (int, float)) or isinstance(metres, bool):
                continue
            if not math.isfinite(metres) or metres <= 0:
                continue
            km = metres / 1000.0
            highway = str(segment.tags.get("highway", SANS_TAG) or SANS_TAG)
            stats.km_total += km
            _ajouter(stats.km_par_highway, highway, km)
            _ajouter(stats.km_par_maxspeed, str(segment.tags.get("maxspeed", SANS_TAG) or SANS_TAG), km)
            _ajouter(stats.km_par_surface, str(segment.tags.get("surface", SANS_TAG) or SANS_TAG), km)
            if semaine:
                stats.km_semaine += km
                _ajouter(stats.km_semaine_par_highway, highway, km)
            if segment.cout_km is not None:
                cout_pondere += segment.cout_km * metres
                metres_avec_cout += metres
    stats.cout_km_moyen = cout_pondere / metres_avec_cout if metres_avec_cout > 0 else None
    return stats


def poids_appris(stats: Statistiques, exposition: Statistiques | None = None) -> dict[str, float]:
    """Poids par classe `highway`, en kilomètres équivalents par kilomètre.

    Formule du contrat §2 : `min(4, max(0, log2(part_expo / part_sorties)))`.
    On compare ce que le cycliste **prend** (`stats`) à ce que le moteur lui
    **propose** dans les mêmes directions (`exposition`). Une classe qu'il
    prend autant qu'on la lui propose ne coûte rien ; une classe qu'il évite
    systématiquement coûte cher, jusqu'au plafond de 4.

    Trois cas particuliers, tous voulus :

    * `tertiary` est **forcé à 0** : c'est la route de référence du
      mainteneur, 65 % de sa pratique mesurée ;
    * une classe **absente de l'exposition** vaut 0 — on n'a rien à comparer,
      et l'ignorance n'est jamais un malus ;
    * une classe **absente des sorties** mais proposée vaut le plafond : le
      cycliste ne la prend jamais alors qu'on la lui propose.

    Sans `exposition`, on rend les poids par défaut du score : sans point de
    comparaison, les parts brutes ne veulent rien dire (une classe peut être
    majoritaire simplement parce qu'elle est majoritaire sur le terrain).

    Chaque jeu est normalisé sur **son propre** total (voir `_parts`) : ce
    sont des parts qu'on compare, pas des kilomètres. Un jeu de sorties deux
    fois plus fourni rend exactement les mêmes poids.
    """
    if exposition is None:
        return dict(POIDS_HIGHWAY_DEFAUT)
    parts_sorties = _parts(stats)
    parts_expo = _parts(exposition)
    if not parts_sorties or not parts_expo:
        return dict(POIDS_HIGHWAY_DEFAUT)

    poids: dict[str, float] = {}
    for highway in sorted(set(parts_sorties) | set(parts_expo)):
        if not highway:
            continue  # une classe sans `highway` ne se pondère pas : on ne sait rien d'elle
        poids[highway] = _poids_classe(
            highway, parts_sorties.get(highway, 0.0), parts_expo.get(highway, 0.0)
        )
    return poids


def _parts(stats: Statistiques) -> dict[str, float]:
    """Part de chaque classe dans **ce** jeu de kilomètres, entre 0 et 1.

    Le dénominateur est la somme de `km_par_highway`, et non `km_total` : les
    deux coïncident sur une base complète, mais une table filtrée en amont
    (une classe écartée, un jeu restreint à quelques sorties, une exposition
    générée à part) les désynchronise. `poids_appris` comparerait alors des
    **kilomètres** déguisés en parts : multiplier les kilomètres d'un des deux
    jeux par un facteur changerait tous les poids, et une base plus fournie
    pénaliserait tout. Le contrat §2 compare des parts ; c'est ici qu'on les
    fabrique.

    Un total nul ou négatif rend un dictionnaire vide : il n'y a pas de part à
    tirer de rien, et l'appelant retombe sur les poids par défaut.
    """
    total = sum(stats.km_par_highway.values())
    if total <= 0:
        return {}
    return {classe: km / total for classe, km in stats.km_par_highway.items()}


def _poids_classe(highway: str, part_sorties: float, part_expo: float) -> float:
    if highway == HIGHWAY_REFERENCE:
        return 0.0
    if part_expo <= 0:
        return 0.0
    if part_sorties <= 0:
        return POIDS_MAX
    return min(POIDS_MAX, max(0.0, math.log2(part_expo / part_sorties)))


# --- persistance des poids ----------------------------------------------------


def ecrire_poids(chemin: Path, poids: dict[str, float], *, meta: dict | None = None) -> None:
    """Écrit les poids appris en JSON. Le chemin vient de l'appelant."""
    charge = {
        "version": 1,
        "ecrit_le": datetime.now(UTC).isoformat(timespec="seconds"),
        "poids": {str(k): float(v) for k, v in poids.items()},
        **(meta or {}),
    }
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(charge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise ErreurUtilisateur(f"routes : écriture impossible dans {chemin} ({e})") from e


def lire_poids(chemin: Path) -> dict[str, float] | None:
    """Les poids appris, ou `None` si le fichier n'existe pas ou n'est pas lisible.

    Un fichier abîmé rend `None` plutôt qu'une erreur : le score retombe alors
    sur ses poids par défaut, ce qui est un comportement correct, là où
    refuser de tracer une boucle pour un JSON tronqué ne le serait pas.
    """
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(charge, dict):
        return None
    brut = charge.get("poids")
    if not isinstance(brut, dict):
        return None
    poids: dict[str, float] = {}
    for cle, valeur in brut.items():
        if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
            continue
        if not math.isfinite(valeur):
            continue
        poids[str(cle)] = float(valeur)
    return poids or None

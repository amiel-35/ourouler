#!/usr/bin/env python3
"""Validation rétrospective de `estimated_traffic_class` sur les sorties réelles.

**Ce script n'est pas un test pytest.** Il lit le cache réel du mainteneur et
appelle le vrai serveur BRouter : les deux sont interdits dans la suite de
tests (règles absolues 1 et 3). Il se lance à la main, depuis la racine du
dépôt :

    uv run python tests/validation/trafic_estime_retrospectif.py

**Ce qu'est `estimated_traffic_class`.** Ce n'est pas une classe de route :
c'est un pseudo-tag que BRouter calcule lui-même, à partir de la population
des villes proches (pondérée par le carré de la distance), des zones
industrielles, des aéroports et de la densité du réseau — jamais d'un
comptage réel de véhicules ni d'un signal cycliste (voir Q16,
`docs/journal/questions/questions_mainteneur.md`). Il vit dans les `WayTags`, donc sur le
**tronçon** (`Segment.tags`), pas sur le nœud : `estimated_traffic_class` est
la classe d'une portion de route entière, pas d'un carrefour.

**La question posée par le mainteneur** : sur ses sorties réelles, évite-t-il
une classe de trafic estimé haute — nettement moins que ce que le moteur lui
propose aux mêmes distances et directions ?

**Les deux populations comparées, et pourquoi celles-là** — reprises telles
quelles de `marqueurs_retrospectif.py` (même fonctions, importées, pas
dupliquées) :

* **Réel** — ses sorties extérieures, relues du cache et **rejouées dans
  BRouter**. `routes_connues.sqlite` ne garde aucun tag de tronçon ; seul le
  rejeu en porte.
* **Proposé** — des boucles `boucle.candidates.generer` depuis son point de
  départ, dans 12 directions, à la même distance cible (par bandes de 10 km).

**Le contrôle qui décide : la distance à la base.** La classe estimée monte
près des villes ; ses sorties partent toutes de chez lui, comme les boucles
proposées. Comparer les deux sans tenir compte d'**où** sur le tracé on se
trouve confondrait « il évite le trafic » avec « il s'éloigne plus souvent
que le moteur ne le propose » — deux choses différentes. Le contrôle : chaque
tronçon (réel et proposé) est classé dans un **anneau de 5 km** de distance à
la base (0–5, 5–10, 15–20…), calculée sur le point milieu du tronçon. La
comparaison qui conclut n'est jamais brute : c'est une comparaison
**standardisée**, anneau par anneau — voir `imprimer_standardisation`.

**« Absente » n'est pas « calme ».** Un tronçon sans `estimated_traffic_class`
n'est pas un tronçon à trafic nul : c'est un tronçon que BRouter n'a pas su
classer. La part d'« absente » est mesurée et imprimée séparément des deux
côtés (réel, proposé) ; elle n'entre dans aucun ratio de classe.

**Trois limites, à lire avec la conclusion.**

1. Le comparateur n'est pas un tirage uniforme sur le réseau : ce sont des
   boucles `fastbike`, un profil qui fuit déjà le trafic. Le test est donc
   **conservateur**.
2. Le rejeu n'est pas la sortie : `points_de_passage` garde un point tous les
   1,5 km, et BRouter recolle l'itinéraire entre eux. Ce qui est mesuré est
   l'itinéraire **reconstruit**, pas la trace GPS.
3. Le point milieu d'un tronçon est une approximation de sa position pour
   l'anneau : un tronçon long à cheval sur deux anneaux est compté en entier
   dans l'anneau de son milieu, pas réparti au prorata.
4. Les kilomètres à plus de `ANNEAU_MAX_M` (60 km) de la base sont exclus des
   deux côtés, pas comptés à zéro : au-delà, trop peu de tracés des deux
   populations pour qu'un anneau soit comparable, et les inclure sans lot de
   référence aurait forcé un choix arbitraire (les compter en `attendu` nul,
   ou les ignorer) qu'il vaut mieux trancher une fois, ici, que de le laisser
   implicite dans `standardiser`.
"""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `marqueurs_retrospectif.py` vit dans le même dossier, hors de tout paquet
# Python (`tests/validation` n'a pas de `__init__.py`). On réutilise sa
# collecte des deux populations (sorties réelles comparables, boucles
# proposées par bande de distance) plutôt que de la dupliquer : même filtre
# de proximité au départ, même tirage déterministe, même regroupement par
# bande. `sys.path` doit être complété avant l'import, d'où le `noqa: E402`
# qui suit.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marqueurs_retrospectif import (  # noqa: E402
    AZIMUTS,
    BANDE_KM,
    DISTANCE_MIN_PAR_DEFAUT_KM,
    GRAINE,
    RAYON_DEPART_M,
    SORTIES_PAR_DEFAUT,
    _bande,
    _connexion_ro,
    imprimer_manques,
    part_de_depart,
    sorties_comparables,
)

from ourouler.activites.cache import Cache  # noqa: E402
from ourouler.apprentissage.routes import points_de_passage  # noqa: E402
from ourouler.boucle.candidates import appels_pour, generer  # noqa: E402
from ourouler.config import Config, Depart, charger  # noqa: E402
from ourouler.connecteurs.brouter import ClientBrouter  # noqa: E402
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur  # noqa: E402
from ourouler.noyau.trace import PointTrace, Trace, distance_m  # noqa: E402

#: Clé WayTags portant l'estimation de BRouter.
CLE_CLASSE = "estimated_traffic_class"

#: Étiquette d'un tronçon sans `estimated_traffic_class`. Jamais fondue avec
#: une classe numérique, jamais traitée comme un zéro (règle absolue 5).
ABSENTE = "absente"

#: Les deux classes les plus hautes que BRouter attribue sur le réseau du
#: mainteneur. Mesuré le 16/09/2026 sur 111 sorties réelles rejouées et leurs
#: boucles comparées : l'échelle observée va de 1 à 6, pas de 3 à 6 comme
#: attendu au départ — 1 et 2 existent aussi, en petite quantité. Le
#: regroupement 5+6 répond à « évite-t-il le trafic estimé », par contraste
#: avec le décompte classe par classe (`imprimer_par_classe`) qui répond à
#: « est-ce spécifiquement la 6, ou tout le haut de l'échelle ? ». À revoir si
#: une classe au-delà de 6 apparaît un jour sur ce réseau.
CLASSES_HAUTES = frozenset({"5", "6"})

#: Largeur d'un anneau de distance à la base, en mètres — le contrôle demandé
#: par le mainteneur contre la confusion « classe haute » / « près de chez
#: moi ».
ANNEAU_M = 5_000.0

#: Rayon maximal d'anneau retenu : au-delà, trop peu de kilomètres des deux
#: côtés pour que la comparaison par anneau veuille dire quelque chose.
ANNEAU_MAX_M = 60_000.0


# --- une trace, résumée en kilomètres par (anneau, classe) --------------------


@dataclass
class KmParAnneauClasse:
    """Kilomètres d'une trace, ventilés par anneau de distance à la base et par classe.

    `total[anneau]` est le total de l'anneau, toutes classes et « absente »
    confondues — le dénominateur de toute part calculée plus loin.
    `classe[(anneau, etiquette)]` est le sous-total d'une classe dans un
    anneau donné.
    """

    distance_km: float
    total: dict[float, float] = field(default_factory=dict)
    classe: dict[tuple[float, str], float] = field(default_factory=dict)

    def ajoute(self, anneau: float, etiquette: str, km: float) -> None:
        self.total[anneau] = self.total.get(anneau, 0.0) + km
        cle = (anneau, etiquette)
        self.classe[cle] = self.classe.get(cle, 0.0) + km


def _etiquette(tags: dict[str, str]) -> str:
    valeur = tags.get(CLE_CLASSE)
    return valeur if valeur else ABSENTE


def resumer(trace: Trace, depart: Depart) -> KmParAnneauClasse | None:
    """Ventile les kilomètres d'une trace par anneau de 5 km et par classe.

    `None` si la trace ne porte aucun tronçon (`segments` vide — un GPX
    importé, par exemple) : on ne sait alors rien de ses classes, ce qui
    n'est pas la même chose qu'une trace sans trafic.
    """
    if not trace.segments:
        return None
    point_depart = PointTrace(depart.latitude, depart.longitude, None, 0.0)
    resume = KmParAnneauClasse(distance_km=trace.distance_m / 1000.0 if trace.distance_m else 0.0)
    for segment in trace.segments:
        if segment.debut_idx >= len(trace.points) or segment.fin_idx >= len(trace.points):
            continue
        a = trace.points[segment.debut_idx]
        b = trace.points[segment.fin_idx]
        milieu = PointTrace((a.lat + b.lat) / 2, (a.lon + b.lon) / 2, None, 0.0)
        ecart_base = distance_m(milieu, point_depart)
        if ecart_base > ANNEAU_MAX_M:
            continue
        anneau = math.floor(ecart_base / ANNEAU_M) * (ANNEAU_M / 1000.0)
        km = segment.longueur_m / 1000.0
        if km <= 0:
            continue
        resume.ajoute(anneau, _etiquette(segment.tags), km)
    return resume


# --- collecte : les deux populations, résumées --------------------------------


def collecter_reelles(
    cache: Cache,
    client: ClientBrouter,
    config: Config,
    *,
    combien: int,
    minimum_m: float,
    bavard: bool,
) -> tuple[list[KmParAnneauClasse], list[float], list[str]]:
    """Rejoue les sorties réelles comparables et résume chacune.

    Reprend exactement le filtre de `marqueurs_retrospectif.mesurer_reelles`
    (proximité du départ, points de passage) sans dupliquer son code : cette
    fonction ne diffère que par ce qu'elle mesure sur la trace rejouée.
    """
    candidates = sorties_comparables(cache, config, minimum_m=minimum_m)
    tirage = random.Random(GRAINE)
    tirage.shuffle(candidates)
    resumes: list[KmParAnneauClasse] = []
    bandes: list[float] = []
    manques: list[str] = []
    for entree in candidates:
        if combien and len(resumes) >= combien:
            break
        try:
            activite = cache.relire(entree.identifiant)
        except Exception as e:  # noqa: BLE001 — un fichier abîmé ne fait pas tomber la mesure
            manques.append(f"{entree.jour} : illisible ({e})")
            continue
        ecart = part_de_depart(activite, config)
        if ecart is None:
            manques.append(f"{entree.jour} : aucune position exploitable")
            continue
        if ecart > RAYON_DEPART_M:
            manques.append(f"{entree.jour} : part à {ecart / 1000:.0f} km du départ configuré")
            continue
        passages = points_de_passage(activite)
        if len(passages) < 2:
            manques.append(f"{entree.jour} : moins de deux points de passage")
            continue
        try:
            trace = client.itineraire(passages)
        except ErreurConnecteur as e:
            manques.append(f"{entree.jour} : {e}")
            continue
        resume = resumer(trace, config.depart)
        if resume is None:
            manques.append(f"{entree.jour} : tracé rejoué sans tags de tronçon")
            continue
        resumes.append(resume)
        bandes.append(_bande(resume.distance_km))
        if bavard:
            print(f"  réel  {entree.jour}  {resume.distance_km:6.1f} km")
    return resumes, bandes, manques


def collecter_proposees(
    client: ClientBrouter, config: Config, bandes_cibles: list[float], *, bavard: bool
) -> tuple[dict[float, list[KmParAnneauClasse]], list[str]]:
    """Un lot de boucles proposées par bande de distance, `AZIMUTS` directions.

    Reprend `marqueurs_retrospectif.mesurer_proposees` à l'identique, sinon
    dans ce qu'elle calcule sur chaque boucle.
    """
    par_bande: dict[float, list[KmParAnneauClasse]] = {}
    manques: list[str] = []
    for cible in sorted(set(bandes_cibles)):
        lot: list[KmParAnneauClasse] = []
        pas = 360.0 / AZIMUTS
        for i in range(AZIMUTS):
            try:
                trouvees = generer(
                    client,
                    config.depart,
                    distance_km=cible,
                    azimut_deg=i * pas,
                    nb=1,
                    tolerance=config.boucle.tolerance_distance,
                    profil=config.brouter.profil,
                    appels_max=appels_pour(1),
                )
            except ErreurConnecteur as e:
                manques.append(f"proposée {cible:g} km az {i * pas:.0f}° : {e}")
                continue
            for candidate in trouvees:
                resume = resumer(candidate.trace, config.depart)
                if resume is not None:
                    lot.append(resume)
                    if bavard:
                        print(f"  prop. {cible:g} km az {i * pas:.0f}°  {resume.distance_km:6.1f} km")
        par_bande[cible] = lot
    return par_bande, manques


# --- rendu : 1. répartition brute des kilomètres par classe -------------------


def _sommer(resumes: list[KmParAnneauClasse]) -> dict[str, float]:
    total: dict[str, float] = {}
    for resume in resumes:
        for (_, etiquette), km in resume.classe.items():
            total[etiquette] = total.get(etiquette, 0.0) + km
    return total


def imprimer_repartition_brute(reelles: list[KmParAnneauClasse], proposees: list[KmParAnneauClasse]) -> None:
    print("=== 1. Répartition brute des kilomètres par classe (non contrôlée) ===")
    for titre, resumes in (("Réelles ", reelles), ("Proposées", proposees)):
        total = _sommer(resumes)
        somme = sum(total.values())
        if somme <= 0:
            print(f"  {titre} : aucun kilomètre classé")
            continue
        etiquettes = sorted(total, key=lambda e: (e == ABSENTE, e))
        parts = ", ".join(f"{e} : {100.0 * total[e] / somme:.1f} %" for e in etiquettes)
        print(f"  {titre} (n={len(resumes)}, {somme:.0f} km classables) : {parts}")
    print(
        "  Brute = sans contrôle de distance à la base. Ne sert qu'à situer l'écart avant\n"
        "  le contrôle ; voir §3 pour la comparaison qui conclut."
    )


# --- rendu : 2. la part « absente », jamais fondue avec un zéro ---------------


def imprimer_absente(reelles: list[KmParAnneauClasse], proposees: list[KmParAnneauClasse]) -> None:
    print()
    print("=== 2. La part « absente » (BRouter n'a pas classé le tronçon) ===")
    for titre, resumes in (("Réelles ", reelles), ("Proposées", proposees)):
        total = _sommer(resumes)
        somme = sum(total.values())
        absente = total.get(ABSENTE, 0.0)
        if somme <= 0:
            continue
        print(
            f"  {titre} : {100.0 * absente / somme:.1f} % des km sans classe "
            f"({absente:.0f}/{somme:.0f} km)"
        )
    print(
        "  Cette part n'entre dans aucun ratio « classe haute » plus bas : elle est\n"
        "  soustraite du dénominateur, pas comptée comme du trafic nul."
    )


# --- test statistique : sign test, sans dépendance à SciPy --------------------


def p_valeur_signe(n_plus: int, n_total: int) -> float:
    """p-valeur bilatérale exacte du test du signe (H0 : p = 0,5).

    Même fonction que `orientation_vent_retrospectif.p_valeur_signe` :
    binomiale symétrique, `2 · P(X ≤ min(n_plus, n_total − n_plus))`.
    """
    if n_total == 0:
        return float("nan")
    k = min(n_plus, n_total - n_plus)
    cumul = sum(math.comb(n_total, x) for x in range(0, k + 1))
    return min(1.0, 2 * cumul / (2**n_total))


# --- rendu : 3. la comparaison standardisée par anneau -------------------------


@dataclass
class Standardise:
    """Pour une sortie réelle : observé contre attendu si elle avait le taux du lot proposé.

    `attendu` applique, anneau par anneau, le taux de classe(s) visée(s) du
    lot **proposé** de la même bande de distance à l'exposition **réelle**
    par anneau de cette sortie précise. C'est une standardisation directe :
    elle répond à « étant donné où il a effectivement roulé par rapport à la
    base, verrait-il autant de classe haute que le moteur y en met ? ». Un
    tronçon dont l'anneau n'a aucun kilomètre côté proposé (bande introuvable)
    est exclu des deux côtés — ni compté en observé, ni en attendu — pour que
    la paire reste comparable.
    """

    etiquette_sortie: str
    km_utilises: float
    observe_km: float
    attendu_km: float


def taux_par_anneau(lot: list[KmParAnneauClasse], etiquettes: frozenset[str]) -> dict[float, float]:
    """Le taux de km en `etiquettes` par anneau, agrégé sur tout le lot proposé.

    `None` implicite (absence de clé) si le lot ne couvre pas cet anneau.
    """
    total_anneau: dict[float, float] = {}
    classe_anneau: dict[float, float] = {}
    for resume in lot:
        for anneau, km in resume.total.items():
            total_anneau[anneau] = total_anneau.get(anneau, 0.0) + km
        for (anneau, e), km in resume.classe.items():
            if e in etiquettes:
                classe_anneau[anneau] = classe_anneau.get(anneau, 0.0) + km
    return {a: classe_anneau.get(a, 0.0) / t for a, t in total_anneau.items() if t > 0}


def standardiser(
    reelles: list[KmParAnneauClasse],
    bandes_reelles: list[float],
    par_bande: dict[float, list[KmParAnneauClasse]],
    etiquettes: frozenset[str],
) -> list[Standardise]:
    resultats: list[Standardise] = []
    for resume, bande in zip(reelles, bandes_reelles, strict=True):
        lot = par_bande.get(bande) or []
        if not lot:
            continue
        taux = taux_par_anneau(lot, etiquettes)
        observe = 0.0
        attendu = 0.0
        km_utilises = 0.0
        for anneau, total_anneau_km in resume.total.items():
            if anneau not in taux:
                continue  # bande sans référence proposée à cet anneau : exclu des deux côtés
            classe_km = sum(
                km for (a, e), km in resume.classe.items() if a == anneau and e in etiquettes
            )
            observe += classe_km
            attendu += total_anneau_km * taux[anneau]
            km_utilises += total_anneau_km
        if km_utilises <= 0:
            continue
        resultats.append(
            Standardise(
                etiquette_sortie="",
                km_utilises=km_utilises,
                observe_km=observe,
                attendu_km=attendu,
            )
        )
    return resultats


def imprimer_standardisation(
    reelles: list[KmParAnneauClasse],
    bandes_reelles: list[float],
    par_bande: dict[float, list[KmParAnneauClasse]],
    *,
    titre: str,
    etiquettes: frozenset[str],
) -> None:
    print(f"  --- {titre} ---")
    resultats = standardiser(reelles, bandes_reelles, par_bande, etiquettes)
    if not resultats:
        print("    NON MESURÉ : aucune sortie avec un anneau couvert côté proposé.")
        return
    ecarts_pct = []
    n_moins, n_plus, n_egal = 0, 0, 0
    for r in resultats:
        if r.attendu_km <= 1e-9:
            continue
        ecart = (r.observe_km - r.attendu_km) / r.attendu_km
        ecarts_pct.append(100.0 * ecart)
        if r.observe_km < r.attendu_km - 1e-9:
            n_moins += 1
        elif r.observe_km > r.attendu_km + 1e-9:
            n_plus += 1
        else:
            n_egal += 1
    n_tranche = n_moins + n_plus
    somme_observe = sum(r.observe_km for r in resultats)
    somme_attendu = sum(r.attendu_km for r in resultats)
    somme_km = sum(r.km_utilises for r in resultats)
    print(
        f"    {len(resultats)} sorties standardisables, {somme_km:.0f} km utilisés "
        f"(reste exclu : anneaux sans lot proposé de référence)."
    )
    if somme_attendu > 0:
        print(
            f"    observé {somme_observe:.1f} km / attendu {somme_attendu:.1f} km "
            f"= {100.0 * somme_observe / somme_attendu:.1f} % (100 % = aucune préférence)"
        )
    if ecarts_pct:
        print(
            f"    écart (observé−attendu)/attendu par sortie : "
            f"médiane {statistics.median(ecarts_pct):+.1f} %, "
            f"min {min(ecarts_pct):+.1f} %, max {max(ecarts_pct):+.1f} %"
        )
    if n_tranche:
        p = p_valeur_signe(n_moins, n_tranche)
        print(
            f"    sorties en dessous de l'attendu : {n_moins}/{n_tranche} "
            f"({100.0 * n_moins / n_tranche:.1f} %, {n_egal} à égalité stricte exclue), "
            f"p-valeur test du signe (H0 : 50 %) = {p:.4f}"
        )
    else:
        print("    aucune sortie tranchée (toutes à égalité stricte).")


# --- rendu : 4. par classe, pas seulement en moyenne ---------------------------


def imprimer_par_classe(
    reelles: list[KmParAnneauClasse],
    bandes_reelles: list[float],
    par_bande: dict[float, list[KmParAnneauClasse]],
) -> None:
    print()
    print("=== 4. Classe par classe, standardisé par anneau (évite-t-il tout, ou juste une classe ?) ===")
    classes: set[str] = set()
    for resume in reelles:
        classes.update(e for (_, e) in resume.classe if e != ABSENTE)
    for lot in par_bande.values():
        for resume in lot:
            classes.update(e for (_, e) in resume.classe if e != ABSENTE)
    if not classes:
        print("  NON MESURÉ : aucune classe numérique observée.")
        return
    for c in sorted(classes):
        imprimer_standardisation(
            reelles, bandes_reelles, par_bande, titre=f"classe {c}", etiquettes=frozenset({c})
        )


# --- exécution ------------------------------------------------------------------


def executer(arguments: argparse.Namespace) -> int:
    config = charger(arguments.config)
    if not config.brouter.url:
        print("NON VÉRIFIÉ : aucun serveur BRouter configuré.", file=sys.stderr)
        return 2
    dossier = config.cache.dossier
    _connexion_ro(dossier / "index.sqlite").close()  # refuse tôt si l'index manque
    cache = Cache(dossier)
    client = ClientBrouter(config.brouter, evitements=config.evitements)

    print(f"Sorties réelles (depuis {config.historique_depuis.isoformat()}, "
          f"à moins de {RAYON_DEPART_M / 1000:g} km du départ) :")
    reelles, bandes_reelles, manques_reels = collecter_reelles(
        cache,
        client,
        config,
        combien=arguments.sorties,
        minimum_m=arguments.distance_min * 1000.0,
        bavard=arguments.bavard,
    )
    if not reelles:
        print("NON VÉRIFIÉ : aucune sortie mesurable.", file=sys.stderr)
        imprimer_manques(manques_reels)
        return 2

    print(f"\nBoucles proposées ({AZIMUTS} directions par bande de {BANDE_KM:g} km) :")
    par_bande, manques_prop = collecter_proposees(client, config, bandes_reelles, bavard=arguments.bavard)

    proposees_toutes = [m for lot in par_bande.values() for m in lot]
    print()
    imprimer_repartition_brute(reelles, proposees_toutes)
    imprimer_absente(reelles, proposees_toutes)

    print()
    print("=== 3. Comparaison standardisée par anneau de 5 km à la base (le contrôle) ===")
    print(
        "  « attendu » = kilomètres de classe haute que verrait cette sortie si, anneau par\n"
        "  anneau, elle portait le taux du lot proposé de même bande et même anneaux traversés.\n"
        "  100 % = même taux que le moteur propose à distance de base égale, pas de préférence."
    )
    imprimer_standardisation(
        reelles, bandes_reelles, par_bande, titre="classes hautes (5, 6)", etiquettes=CLASSES_HAUTES
    )
    imprimer_standardisation(
        reelles, bandes_reelles, par_bande, titre="absente (pour référence, hors ratio de classe)",
        etiquettes=frozenset({ABSENTE}),
    )
    imprimer_par_classe(reelles, bandes_reelles, par_bande)

    print()
    imprimer_manques(manques_reels + manques_prop)
    return 0


def analyser(argv: list[str] | None = None) -> argparse.Namespace:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--config", help="fichier de configuration (défaut : celui du mainteneur)")
    analyseur.add_argument(
        "--sorties",
        type=int,
        default=SORTIES_PAR_DEFAUT,
        help=f"nombre de sorties réelles à rejouer, 0 = toutes (défaut : {SORTIES_PAR_DEFAUT})",
    )
    analyseur.add_argument(
        "--distance-min",
        dest="distance_min",
        type=float,
        default=DISTANCE_MIN_PAR_DEFAUT_KM,
        help="ne garder que les sorties d'au moins tant de km "
        f"(défaut : {DISTANCE_MIN_PAR_DEFAUT_KM:g})",
    )
    analyseur.add_argument("--bavard", action="store_true", help="imprimer chaque mesure")
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except ErreurUtilisateur as e:
        print(f"trafic_estime_retrospectif : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validation rétrospective de la densité de marqueurs au kilomètre (lot L5.3).

**Ce script n'est pas un test pytest.** Il lit le cache réel du mainteneur et
appelle le vrai serveur BRouter : les deux sont interdits dans la suite de
tests (règles absolues 1 et 3). Il se lance à la main, depuis la racine du
dépôt :

    uv run python scripts/validation/marqueurs_retrospectif.py

Ce qu'il mesure, et pourquoi c'est le critère d'acceptation de la seule mesure
nouvelle du lot. `boucle.marqueurs.compter` compte les feux, stops, passages
piétons, cédez-le-passage, mini-giratoires et ralentisseurs d'un tracé, et en
tire une densité au kilomètre. On veut savoir si cette densité **discrimine** :
les routes que le mainteneur choisit vraiment doivent en porter moins que
celles que le moteur propose au hasard des directions. Si elles n'en portent
pas moins, l'axe ne mesure pas une préférence, et le script le dit au lieu de
le taire (règles absolues 4 et 5).

**Les deux populations comparées, et pourquoi celles-là.**

* **Réel** — ses sorties extérieures, relues du cache et **rejouées dans
  BRouter** (un appel chacune, exactement comme `ourouler apprendre`). Le
  rejeu est indispensable : la base `routes_connues.sqlite` ne garde que les
  tags de **chemin**, jamais ceux de **nœud**, et un feu vit sur un nœud. Une
  trace GPS seule ne porte aucun marqueur.
* **Proposé** — des boucles produites par `boucle.candidates.generer` depuis
  son point de départ, dans `AZIMUTS` directions réparties sur l'horizon, à la
  même distance cible que la sortie réelle qu'on lui compare (par bandes de
  `BANDE_KM`, pour que le même lot de boucles serve à plusieurs sorties et que
  le coût reste borné).

C'est la comparaison qui décide, parce que c'est exactement le choix que
l'outil fera : « ce que je propose » contre « ce qu'il prend ».

**Trois limites, à lire avec la conclusion.**

1. **Le comparateur n'est pas un tirage uniforme sur le réseau routier.** Ce
   sont des boucles `fastbike`, un profil qui fuit déjà le trafic. Le test est
   donc **conservateur** : s'il conclut oui contre ce comparateur-là, il
   conclurait oui *a fortiori* contre des tracés vraiment aléatoires.
2. **Le rejeu n'est pas la sortie.** `points_de_passage` garde un point tous
   les 1,5 km, 60 au plus : BRouter recolle l'itinéraire entre eux et peut
   choisir une rue voisine. La densité mesurée est celle de l'itinéraire
   reconstruit, pas de la trace GPS.
3. **`crossing` domine le compte** (deux marqueurs sur trois sur les tracés
   mesurés). La densité est donc surtout une densité de passages piétons
   marqués ; feux et ralentisseurs pèsent peu dans le total, même s'ils pèsent
   lourd sous les roues. La table par nature est imprimée pour qu'on le voie.

Trois précautions d'exécution, comme ses voisins de ce dossier :

- **Le cache n'est pas modifié** : l'index est ouvert en lecture seule
  (`mode=ro`).
- **Aucune coordonnée n'est imprimée.** Les sorties sont désignées par leur
  date, jamais par un point de départ, et le filtre de proximité rend une
  distance, pas un lieu.
- Le tirage des sorties est **déterministe** (`GRAINE`) : « la médiane a
  bougé » doit vouloir dire quelque chose.
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.activites.inventaire import en_interieur
from ourouler.apprentissage.routes import DISTANCE_MIN_M, points_de_passage
from ourouler.boucle.candidates import appels_pour, generer
from ourouler.boucle.marqueurs import LIBELLES, compter
from ourouler.config import Config, charger
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.noyau.activite import est_sport_velo
from ourouler.noyau.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.noyau.trace import PointTrace, Trace, distance_m

#: Rayon autour du point de départ configuré au-delà duquel une sortie n'est
#: pas comparable aux boucles proposées : une sortie de vacances roule dans un
#: autre réseau routier, et son urbanisation ne dit rien du sien.
RAYON_DEPART_M = 5_000.0

#: Distances cibles rassemblées par bandes de cette largeur, en km : toutes les
#: sorties de 55 à 65 km se comparent au **même** lot de boucles proposées.
#: Sans ce regroupement, chaque sortie coûterait `AZIMUTS` appels au moteur.
BANDE_KM = 10.0

#: Directions du comparateur, réparties sur tout l'horizon. Douze, soit un
#: tous les 30° : mesuré le 16/09/2026, c'est l'écart au-delà duquel deux
#: boucles ne partagent presque plus de route (médiane de recouvrement 28 % à
#: 30° d'écart, 14 % à 60°).
AZIMUTS = 12

#: Graine du tirage des sorties : le résultat doit être le même d'une
#: exécution à l'autre.
GRAINE = 20260916

#: Nombre de sorties réelles mesurées par défaut. Chacune coûte **un** appel
#: au serveur du mainteneur ; `--sorties 0` les prend toutes.
SORTIES_PAR_DEFAUT = 60

#: Ce qu'on appelle « nettement moins » : la médiane des sorties réelles doit
#: valoir au plus cette part de la médiane des boucles proposées. Même forme —
#: et même valeur — que `AMELIORATION_ATTENDUE` de `terrain_retrospectif.py`,
#: pour que deux validations du même dépôt ne se jugent pas à deux barres
#: différentes.
AMELIORATION_ATTENDUE = 0.70

#: Plancher de distance par défaut, en km. `DISTANCE_MIN_M` (3 km) ne sert qu'à
#: ne pas rejouer un déplacement de quartier ; il laisse passer des trajets
#: urbains qui ne sont pas des sorties. Mesuré le 16/09/2026 : sous 20 km, la
#: densité médiane de ses tracés est de 13 marqueurs au kilomètre contre 3
#: au-delà — ce sont deux populations différentes, et l'outil ne propose que
#: la seconde. `--distance-min 0` retombe sur `DISTANCE_MIN_M`.
DISTANCE_MIN_PAR_DEFAUT_KM = 40.0


@dataclass
class Mesure:
    """Une densité mesurée, et de quoi la situer."""

    etiquette: str
    distance_km: float
    marqueurs: int
    par_km: float
    par_nature: dict[str, int]


# --- lecture du cache ---------------------------------------------------------


def _connexion_ro(chemin: Path) -> sqlite3.Connection:
    """Ouvre une base SQLite **en lecture seule** : ce script n'écrit rien."""
    if not chemin.is_file():
        raise ErreurUtilisateur(f"fichier introuvable : {chemin}")
    return sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)


def sorties_comparables(cache: Cache, config: Config, *, minimum_m: float) -> list:
    """Les sorties extérieures qui partent d'assez près du départ configuré.

    Mêmes filtres que `apprentissage.routes.sorties_a_apprendre` — vélo,
    dehors, assez longue — plus la proximité du départ : une boucle proposée
    part forcément de chez lui, une sortie de vacances non, et comparer les
    deux mesurerait l'urbanisation de deux régions.

    `minimum_m` remonte le plancher de `DISTANCE_MIN_M` (3 km, qui ne sert qu'à
    ne pas rejouer un déplacement de quartier). À 40 km on ne garde que des
    sorties d'entraînement, c'est-à-dire ce que l'outil propose : mesuré le
    16/09/2026, les sorties de moins de 20 km portent 13 marqueurs au
    kilomètre et sont des trajets urbains, pas des sorties.
    """
    plancher = max(DISTANCE_MIN_M, minimum_m)
    retenues = []
    for entree in cache.lister(depuis=config.historique_depuis):
        if not est_sport_velo(entree.sport) or en_interieur(entree):
            continue
        if entree.jour is None or (entree.distance_m or 0.0) < plancher:
            continue
        retenues.append(entree)
    return retenues


def part_de_depart(activite, config: Config) -> float | None:
    """Distance en mètres entre le premier point géolocalisé et le départ configuré."""
    for point in activite.points:
        if point.lat is not None and point.lon is not None:
            return distance_m(
                PointTrace(point.lat, point.lon, None, 0.0),
                PointTrace(config.depart.latitude, config.depart.longitude, None, 0.0),
            )
    return None


# --- les deux populations -----------------------------------------------------


def mesurer_reelles(
    cache: Cache,
    client: ClientBrouter,
    config: Config,
    *,
    combien: int,
    minimum_m: float,
    bavard: bool,
) -> tuple[list[Mesure], list[str]]:
    """Rejoue des sorties réelles dans BRouter et compte leurs marqueurs."""
    candidates = sorties_comparables(cache, config, minimum_m=minimum_m)
    tirage = random.Random(GRAINE)
    tirage.shuffle(candidates)
    mesures: list[Mesure] = []
    manques: list[str] = []
    for entree in candidates:
        if combien and len(mesures) >= combien:
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
        mesure = _mesure(trace, str(entree.jour))
        if mesure is None:
            manques.append(f"{entree.jour} : tracé rejoué sans tags de nœud")
            continue
        mesures.append(mesure)
        if bavard:
            print(f"  réel  {mesure.etiquette} {mesure.distance_km:6.1f} km "
                  f"{mesure.marqueurs:4d} marqueurs {mesure.par_km:5.2f} /km")
    return mesures, manques


def mesurer_proposees(
    client: ClientBrouter, config: Config, distances_km: list[float], *, bavard: bool
) -> tuple[dict[float, list[Mesure]], list[str]]:
    """Un lot de boucles proposées par bande de distance, `AZIMUTS` directions."""
    par_bande: dict[float, list[Mesure]] = {}
    manques: list[str] = []
    for cible in sorted({_bande(d) for d in distances_km}):
        lot: list[Mesure] = []
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
                mesure = _mesure(candidate.trace, f"{cible:g} km az {i * pas:.0f}°")
                if mesure is not None:
                    lot.append(mesure)
                    if bavard:
                        print(f"  prop. {mesure.etiquette:>16} {mesure.distance_km:6.1f} km "
                              f"{mesure.marqueurs:4d} marqueurs {mesure.par_km:5.2f} /km")
        par_bande[cible] = lot
    return par_bande, manques


def _mesure(trace: Trace, etiquette: str) -> Mesure | None:
    marqueurs = compter(trace)
    par_km = marqueurs.par_km
    if par_km is None or not math.isfinite(par_km):
        return None
    return Mesure(
        etiquette=etiquette,
        distance_km=marqueurs.distance_km,
        marqueurs=marqueurs.nombre,
        par_km=par_km,
        par_nature=dict(marqueurs.par_nature),
    )


def _bande(distance_km: float) -> float:
    """La bande de distance d'un tracé : 57,3 km → 60 km, au multiple le plus proche."""
    return max(BANDE_KM, round(distance_km / BANDE_KM) * BANDE_KM)


# --- rendu --------------------------------------------------------------------


def imprimer_distribution(titre: str, mesures: list[Mesure]) -> None:
    if not mesures:
        print(f"{titre} : aucune mesure")
        return
    valeurs = sorted(m.par_km for m in mesures)
    print(
        f"{titre} : n={len(valeurs)}  "
        f"min={valeurs[0]:.2f}  q1={_centile(valeurs, 25):.2f}  "
        f"médiane={statistics.median(valeurs):.2f}  q3={_centile(valeurs, 75):.2f}  "
        f"max={valeurs[-1]:.2f}  marqueurs/km"
    )


def imprimer_natures(titre: str, mesures: list[Mesure]) -> None:
    total: dict[str, int] = {}
    for mesure in mesures:
        for nature, nombre in mesure.par_nature.items():
            total[nature] = total.get(nature, 0) + nombre
    somme = sum(total.values())
    if somme <= 0:
        return
    parts = ", ".join(
        f"{LIBELLES.get(nature, (nature, nature))[1]} {nombre * 100 / somme:.0f} %"
        for nature, nombre in sorted(total.items(), key=lambda kv: -kv[1])
    )
    print(f"{titre} — composition : {parts}")


def rangs(reelles: list[Mesure], par_bande: dict[float, list[Mesure]]) -> list[float]:
    """Pour chaque sortie réelle, sa place dans le lot proposé de sa bande, dans [0, 1].

    0 = moins de marqueurs que **toutes** les boucles proposées de la même
    longueur ; 1 = plus que toutes. La médiane de ces rangs est le test
    apparié : sans préférence, elle vaut 0,5.
    """
    places: list[float] = []
    for mesure in reelles:
        lot = par_bande.get(_bande(mesure.distance_km)) or []
        if not lot:
            continue
        dessous = sum(1 for autre in lot if autre.par_km < mesure.par_km)
        egaux = sum(1 for autre in lot if autre.par_km == mesure.par_km)
        places.append((dessous + egaux / 2) / len(lot))
    return places


def _centile(valeurs_triees: list[float], centile: float) -> float:
    if not valeurs_triees:
        return float("nan")
    k = min(len(valeurs_triees) - 1, int(round(centile / 100 * (len(valeurs_triees) - 1))))
    return valeurs_triees[k]


def conclure(reelles: list[Mesure], par_bande: dict[float, list[Mesure]]) -> bool:
    """Imprime le verdict. Vrai si la densité discrimine."""
    proposees = [m for lot in par_bande.values() for m in lot]
    if not reelles or not proposees:
        print("\nNON MESURÉ : il manque une des deux populations.")
        return False

    med_reel = statistics.median([m.par_km for m in reelles])
    med_prop = statistics.median([m.par_km for m in proposees])
    rapport = med_reel / med_prop if med_prop > 0 else float("inf")
    places = rangs(reelles, par_bande)
    med_rang = statistics.median(places) if places else float("nan")
    sous_la_moitie = sum(1 for p in places if p < 0.5)

    print()
    print(f"Médiane réelle / médiane proposée : {med_reel:.2f} / {med_prop:.2f} = {rapport:.2f}")
    print(f"  (le seuil du lot est {AMELIORATION_ATTENDUE:.2f} — plus bas = mieux)")
    print(
        f"Rang apparié : médiane {med_rang:.2f} sur {len(places)} sorties "
        f"({sous_la_moitie} sur {len(places)} sous la médiane de leur lot ; "
        f"0,50 = aucune préférence)"
    )
    verdict = rapport <= AMELIORATION_ATTENDUE
    print()
    if verdict:
        print("OUI — les routes réellement roulées portent nettement moins de marqueurs")
        print("      au kilomètre que celles que le moteur propose. L'axe discrimine.")
    else:
        print("NON — la densité de marqueurs ne sépare pas ce qu'il roule de ce qu'on")
        print("      lui propose au seuil demandé. Lire le rang apparié avant de conclure :")
        print("      un rapport de médianes proche de 1 avec un rang nettement sous 0,50")
        print("      dit « préférence réelle mais faible », pas « aucune préférence ».")
    return verdict


# --- exécution ----------------------------------------------------------------


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
    reelles, manques_reels = mesurer_reelles(
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
    par_bande, manques_prop = mesurer_proposees(
        client, config, [m.distance_km for m in reelles], bavard=arguments.bavard
    )

    print()
    imprimer_distribution("Réelles ", reelles)
    imprimer_distribution("Proposées", [m for lot in par_bande.values() for m in lot])
    print()
    imprimer_natures("Réelles ", reelles)
    imprimer_natures("Proposées", [m for lot in par_bande.values() for m in lot])
    print()
    print("Par bande de distance :")
    for cible in sorted(par_bande):
        lot = par_bande[cible]
        des_reelles = [m for m in reelles if _bande(m.distance_km) == cible]
        if not lot or not des_reelles:
            continue
        print(
            f"  {cible:5.0f} km : réelles n={len(des_reelles):3d} "
            f"médiane {statistics.median([m.par_km for m in des_reelles]):.2f}  |  "
            f"proposées n={len(lot):2d} médiane {statistics.median([m.par_km for m in lot]):.2f}"
        )

    verdict = conclure(reelles, par_bande)
    imprimer_manques(manques_reels + manques_prop)
    return 0 if verdict else 1


def imprimer_manques(manques: list[str]) -> None:
    if not manques:
        return
    print(f"\n{len(manques)} sortie(s) ou boucle(s) écartée(s) :")
    for ligne in manques[:12]:
        print(f"  {ligne}")
    if len(manques) > 12:
        print(f"  … et {len(manques) - 12} autre(s)")


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
        f"(défaut : {DISTANCE_MIN_PAR_DEFAUT_KM:g} — en dessous ce sont des trajets, pas des sorties)",
    )
    analyseur.add_argument("--bavard", action="store_true", help="imprimer chaque mesure")
    return analyseur.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return executer(analyser(argv))
    except ErreurUtilisateur as e:
        print(f"marqueurs_retrospectif : {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

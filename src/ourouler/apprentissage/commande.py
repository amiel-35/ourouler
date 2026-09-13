"""Sous-commande `ourouler routes` : apprendre, regarder, pondérer.

Adaptateur entre `argparse` et `apprentissage.routes`. C'est **ici** que les
chemins se composent (`config.cache.dossier / …`) et que les clients se
créent : le cœur, lui, reçoit des objets déjà faits.

Trois actions :

* `apprendre` rejoue les sorties extérieures du cache dans BRouter — un appel
  par sortie, idempotent, on peut relancer sans compter ;
* `stats` montre ce que le cycliste roule vraiment, par classe de route ;
* `poids` génère huit boucles de 40 km autour du départ pour mesurer ce que le
  moteur **propose** (l'exposition), le compare à ce qu'il **prend**, et rend
  les poids appris — écrits dans `poids_routes.json` avec `--appliquer`.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from ourouler.activites.cache import Cache
from ourouler.apprentissage.routes import (
    LIBELLE_SANS_HIGHWAY,
    NOM_BASE,
    NOM_POIDS,
    BaseRoutes,
    RapportApprentissage,
    Statistiques,
    apprendre,
    ecrire_poids,
    lire_poids,
    poids_appris,
    statistiques_de_traces,
)
from ourouler.boucle.couts import POIDS_HIGHWAY_DEFAUT
from ourouler.boucle.trace import Trace
from ourouler.config import Config
from ourouler.connecteurs.brouter import ClientBrouter
from ourouler.erreurs import ErreurConnecteur, ErreurUtilisateur
from ourouler.meteo.couronne import NOMS_DIRECTIONS, azimut_de

#: Distance des boucles d'exposition, en kilomètres. Assez long pour sortir de
#: l'agglomération et rencontrer les mêmes classes de routes qu'une vraie
#: sortie, assez court pour que huit appels restent une affaire de secondes.
DISTANCE_EXPOSITION_KM = 40.0

#: Rapport entre la longueur d'une boucle BRouter et le rayon demandé, mesuré
#: sur le serveur réel (voir `boucle.candidates`). L'exposition se lit en
#: **parts** : quelques kilomètres d'écart sur la longueur ne changent rien.
RAPPORT_RAYON = 5.0

#: Ce qu'on affiche à la place d'une mesure absente.
ABSENT = "—"

ACTIONS = ("apprendre", "stats", "poids")


def executer(
    args: argparse.Namespace,
    config: Config,
    client_brouter: ClientBrouter | None = None,
) -> int:
    """Exécute `ourouler routes <action>`. Renvoie le code de sortie (0 = succès)."""
    action = getattr(args, "action", None)
    if action not in ACTIONS:
        raise ErreurUtilisateur(
            f"routes : préciser une action — {', '.join(ACTIONS)} "
            "(`ourouler routes apprendre` rejoue vos sorties dans BRouter)"
        )
    base = BaseRoutes(config.cache.dossier / NOM_BASE)
    if action == "apprendre":
        return _apprendre(args, config, base, client_brouter)
    if action == "stats":
        return _stats(args, config, base)
    return _poids(args, config, base, client_brouter)


def _client(config: Config, client_brouter: ClientBrouter | None) -> ClientBrouter:
    if client_brouter is not None:
        return client_brouter
    if not config.brouter.renseigne:
        raise ErreurUtilisateur(
            "routes : [brouter] url n'est pas renseigné dans la configuration — "
            "y mettre l'adresse du serveur BRouter"
        )
    return ClientBrouter(config.brouter, evitements=config.evitements)


# --- apprendre ----------------------------------------------------------------


def _apprendre(
    args: argparse.Namespace,
    config: Config,
    base: BaseRoutes,
    client_brouter: ClientBrouter | None,
) -> int:
    depuis = _depuis(getattr(args, "depuis", None), config)
    cache = Cache(config.cache.dossier)
    client = _client(config, client_brouter)
    rapport = apprendre(
        cache,
        client,
        base,
        config,
        depuis=depuis,
        max_sorties=getattr(args, "max_sorties", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(_apprentissage_json(rapport, depuis), ensure_ascii=False, indent=2))
    else:
        print(_apprentissage_texte(rapport, depuis, base))
    return 0


def _apprentissage_texte(rapport: RapportApprentissage, depuis: date, base: BaseRoutes) -> str:
    stats = base.statistiques()
    lignes = [
        f"Apprentissage des routes depuis le {depuis.isoformat()} — "
        f"{rapport.sorties_vues} sortie(s) extérieure(s) en cache",
        f"  apprises ce coup-ci : {rapport.sorties_apprises} "
        f"({_fr(rapport.km, 0)} km rejoués, {rapport.mailles} mailles)",
        f"  déjà connues        : {rapport.sorties_deja_connues}",
        f"  échecs              : {rapport.echecs}",
    ]
    lignes.extend(f"    échec — {m}" for m in rapport.messages[:20])
    if len(rapport.messages) > 20:
        lignes.append(f"    … et {len(rapport.messages) - 20} autre(s)")
    lignes.append("")
    lignes.append(
        f"Base : {stats.sorties} sortie(s), {_fr(stats.km_total, 0)} km roulés, "
        f"{stats.mailles} mailles connues."
    )
    return "\n".join(lignes)


def _apprentissage_json(rapport: RapportApprentissage, depuis: date) -> dict:
    return {
        "depuis": depuis.isoformat(),
        "sorties_vues": rapport.sorties_vues,
        "sorties_apprises": rapport.sorties_apprises,
        "sorties_deja_connues": rapport.sorties_deja_connues,
        "echecs": rapport.echecs,
        "km": round(rapport.km, 1),
        "mailles": rapport.mailles,
        "messages": list(rapport.messages),
    }


# --- stats --------------------------------------------------------------------


def _stats(args: argparse.Namespace, config: Config, base: BaseRoutes) -> int:
    stats = base.statistiques()
    appris = lire_poids(config.cache.dossier / NOM_POIDS)
    if getattr(args, "json", False):
        print(json.dumps(_stats_json(stats, appris), ensure_ascii=False, indent=2))
    else:
        print(_stats_texte(stats, appris))
    return 0


def _stats_texte(stats: Statistiques, appris: dict[str, float] | None) -> str:
    if stats.km_total <= 0:
        return (
            "Aucune route apprise pour l'instant — lancer `ourouler routes apprendre` "
            "(un appel BRouter par sortie extérieure)."
        )
    lignes = [
        f"Routes roulées — {stats.sorties} sortie(s), {_fr(stats.km_total, 0)} km, "
        f"{stats.mailles} mailles",
        f"Coût moyen du profil BRouter : "
        f"{_fr(stats.cout_km_moyen, 0) if stats.cout_km_moyen is not None else ABSENT}",
        "",
    ]
    titres = ("classe", "km", "part", "part semaine", "poids défaut", "poids appris")
    cellules = [
        [
            _libelle(classe),
            _fr(stats.km_par_highway[classe], 0),
            f"{stats.part(classe) * 100:.0f} %",
            f"{stats.part_semaine(classe) * 100:.0f} %",
            _fr(POIDS_HIGHWAY_DEFAUT.get(classe, 0.0), 1),
            _fr(appris[classe], 2) if appris and classe in appris else ABSENT,
        ]
        for classe in stats.classes()
    ]
    lignes.extend(_tableau(titres, cellules))
    if appris is None:
        lignes.append("")
        lignes.append(
            "Aucun poids appris pour l'instant : `ourouler routes poids --appliquer` "
            "les mesure et les écrit."
        )
    lignes.append("")
    lignes.extend(_secondaire("maxspeed", stats.km_par_maxspeed, stats.km_total))
    lignes.append("")
    lignes.extend(_secondaire("surface", stats.km_par_surface, stats.km_total))
    return "\n".join(lignes)


def _secondaire(nom: str, par_valeur: dict[str, float], km_total: float) -> list[str]:
    """Les cinq valeurs les plus roulées d'un tag secondaire, en une petite table."""
    classees = sorted(par_valeur.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    titres = (nom, "km", "part")
    cellules = [
        [
            valeur or "(absent)",
            _fr(km, 0),
            f"{(km / km_total * 100 if km_total else 0):.0f} %",
        ]
        for valeur, km in classees
    ]
    return _tableau(titres, cellules)


def _stats_json(stats: Statistiques, appris: dict[str, float] | None) -> dict:
    return {
        "sorties": stats.sorties,
        "mailles": stats.mailles,
        "km_total": round(stats.km_total, 1),
        "km_semaine": round(stats.km_semaine, 1),
        "cout_km_moyen": stats.cout_km_moyen,
        "par_highway": [
            {
                "classe": classe,
                "km": round(stats.km_par_highway[classe], 1),
                "part": round(stats.part(classe), 4),
                "part_semaine": round(stats.part_semaine(classe), 4),
                "poids_defaut": POIDS_HIGHWAY_DEFAUT.get(classe, 0.0),
                "poids_appris": (appris or {}).get(classe),
            }
            for classe in stats.classes()
        ],
        "km_par_maxspeed": {k: round(v, 1) for k, v in stats.km_par_maxspeed.items()},
        "km_par_surface": {k: round(v, 1) for k, v in stats.km_par_surface.items()},
    }


# --- poids --------------------------------------------------------------------


def _poids(
    args: argparse.Namespace,
    config: Config,
    base: BaseRoutes,
    client_brouter: ClientBrouter | None,
) -> int:
    stats = base.statistiques()
    if stats.km_total <= 0:
        raise ErreurUtilisateur(
            "routes poids : aucune route apprise — lancer d'abord "
            "`ourouler routes apprendre`"
        )
    client = _client(config, client_brouter)
    traces, echecs = _boucles_exposition(client, config)
    exposition = statistiques_de_traces(traces)
    poids = poids_appris(stats, exposition if traces else None)

    chemin = config.cache.dossier / NOM_POIDS
    applique = bool(getattr(args, "appliquer", False))
    if applique:
        ecrire_poids(
            chemin,
            poids,
            meta={
                "sorties_apprises": stats.sorties,
                "km_appris": round(stats.km_total, 1),
                "boucles_exposition": len(traces),
                "km_exposition": round(exposition.km_total, 1),
            },
        )
    if getattr(args, "json", False):
        sortie = _poids_json(stats, exposition, poids, echecs)
        sortie["ecrit_dans"] = str(chemin) if applique else None
        print(json.dumps(sortie, ensure_ascii=False, indent=2))
    else:
        print(_poids_texte(stats, exposition, poids, echecs, chemin if applique else None))
    return 0


def _boucles_exposition(client: ClientBrouter, config: Config) -> tuple[list[Trace], list[str]]:
    """Une boucle de 40 km par direction : ce que le moteur **propose** au départ.

    Une direction qui échoue n'annule pas la mesure : on compte l'échec et on
    continue. Comparer sept directions vaut mieux que ne rien comparer — mais
    le nombre de boucles est affiché, pour qu'on sache sur quoi repose le
    chiffre (règle absolue 5).
    """
    traces: list[Trace] = []
    echecs: list[str] = []
    rayon = DISTANCE_EXPOSITION_KM * 1000.0 / RAPPORT_RAYON
    for nom in NOMS_DIRECTIONS:
        try:
            traces.append(
                client.boucle(
                    (config.depart.latitude, config.depart.longitude),
                    azimut_deg=azimut_de(nom),
                    rayon_m=rayon,
                    profil=config.brouter.profil,
                )
            )
        except ErreurConnecteur as e:
            echecs.append(f"{nom} : {e}")
    return (traces, echecs)


def _poids_texte(
    stats: Statistiques,
    exposition: Statistiques,
    poids: dict[str, float],
    echecs: list[str],
    ecrit_dans,
) -> str:
    lignes = [
        f"Poids appris — {stats.sorties} sortie(s) roulée(s) ({_fr(stats.km_total, 0)} km) "
        f"contre {exposition.sorties} boucle(s) d'exposition "
        f"({_fr(exposition.km_total, 0)} km, {DISTANCE_EXPOSITION_KM:g} km × "
        f"{len(NOMS_DIRECTIONS)} directions)",
        "Poids = min(4, max(0, log2(part exposition / part sorties))), en km "
        "équivalents par km ; tertiary est la référence, donc 0.",
        "",
    ]
    classes = sorted(
        set(stats.km_par_highway) | set(exposition.km_par_highway),
        key=lambda c: -stats.km_par_highway.get(c, 0.0),
    )
    titres = ("classe", "part sorties", "part exposition", "poids défaut", "poids appris")
    cellules = [
        [
            _libelle(classe),
            f"{_fr(stats.part(classe) * 100, 1)} %",
            f"{_fr(exposition.part(classe) * 100, 1)} %",
            _fr(POIDS_HIGHWAY_DEFAUT.get(classe, 0.0), 1),
            _fr(poids[classe], 2) if classe in poids else ABSENT,
        ]
        for classe in classes
    ]
    lignes.extend(_tableau(titres, cellules))
    if echecs:
        lignes.append("")
        lignes.append(f"{len(echecs)} direction(s) sans boucle — l'exposition porte sur le reste :")
        lignes.extend(f"  {m}" for m in echecs)
    lignes.append("")
    if ecrit_dans is not None:
        lignes.append(f"Poids écrits dans {ecrit_dans} — `ourouler boucle` les utilisera.")
    else:
        lignes.append("Rien n'a été écrit : ajouter --appliquer pour enregistrer ces poids.")
    return "\n".join(lignes)


def _poids_json(
    stats: Statistiques, exposition: Statistiques, poids: dict[str, float], echecs: list[str]
) -> dict:
    classes = sorted(set(stats.km_par_highway) | set(exposition.km_par_highway))
    return {
        "sorties_apprises": stats.sorties,
        "km_appris": round(stats.km_total, 1),
        "boucles_exposition": exposition.sorties,
        "km_exposition": round(exposition.km_total, 1),
        "directions": list(NOMS_DIRECTIONS),
        "distance_exposition_km": DISTANCE_EXPOSITION_KM,
        "echecs": list(echecs),
        "classes": [
            {
                "classe": classe,
                "part_sorties": round(stats.part(classe), 4),
                "part_exposition": round(exposition.part(classe), 4),
                "poids_defaut": POIDS_HIGHWAY_DEFAUT.get(classe, 0.0),
                "poids_appris": poids.get(classe),
            }
            for classe in classes
        ],
        "poids": {k: round(v, 4) for k, v in poids.items()},
    }


# --- rendu partagé ------------------------------------------------------------


def _tableau(titres: tuple[str, ...], cellules: list[list[str]]) -> list[str]:
    """Un tableau aligné à droite, titres compris. Vide si aucune ligne."""
    if not cellules:
        return [f"  {titres[0]} : aucune donnée"]
    largeurs = [
        max([len(t)] + [len(ligne[i]) for ligne in cellules]) for i, t in enumerate(titres)
    ]
    lignes = ["  " + "  ".join(t.rjust(n) for t, n in zip(titres, largeurs, strict=True))]
    for ligne in cellules:
        lignes.append("  " + "  ".join(c.rjust(n) for c, n in zip(ligne, largeurs, strict=True)))
    return lignes


def _libelle(classe: str) -> str:
    return classe or LIBELLE_SANS_HIGHWAY


def _fr(valeur: float, decimales: int) -> str:
    """Un nombre à la française : virgule décimale, pas de séparateur de milliers."""
    return f"{valeur:.{decimales}f}".replace(".", ",")


def _depuis(brut: str | None, config: Config) -> date:
    if not brut:
        return config.historique_depuis
    try:
        return date.fromisoformat(brut)
    except ValueError as e:
        raise ErreurUtilisateur(f"--depuis : date AAAA-MM-JJ attendue, reçu « {brut} »") from e

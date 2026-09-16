#!/usr/bin/env python3
"""Point d'entrée du conteneur « générateur » (docs/heberge_minimal_contrat.md, périmètre point 1).

Produit la page du jour une première fois immédiatement (utile pour vérifier
tout de suite, et pour ne pas attendre l'heure planifiée après un redémarrage
du conteneur), puis chaque jour à l'heure configurée.

Ce script est **hors** de `src/ourouler/` : ce n'est pas le cœur, c'est la
couche d'exploitation du contrat de l'hébergé minimal, au même titre que
`cli.py` pour l'usage interactif. Il a donc le droit de lire l'environnement,
l'horloge, et d'invoquer un sous-processus — rien de tout cela n'entre dans
`src/ourouler/`, où la règle absolue 2 de CLAUDE.md continue de s'appliquer
sans exception.

Toute la configuration vient de variables d'environnement, jamais d'une
valeur écrite ici. En particulier, la clé Intervals, le point de départ et le
serveur BRouter sont lus par `ourouler` lui-même (`config.charger`, voir
docs/heberge_minimal_contrat.md) — ce script ne fait que les transmettre par
l'environnement du sous-processus, il ne les connaît ni ne les stocke.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

#: Dossier partagé avec le conteneur « serveur » (volume Docker).
DOSSIER_PAGES = os.environ.get("OUROULER_DOSSIER_PAGES", "/data/pages")

#: Fichier de configuration TOML (cycliste, vélos, météo, séance, tenue... —
#: rien de secret : depart/intervals/brouter viennent de l'environnement,
#: voir docs/heberge_minimal_contrat.md). Monté en lecture seule.
CHEMIN_CONFIG = os.environ.get("OUROULER_CONFIG", "/config/config.toml")

#: Heure locale quotidienne d'exécution, "HH:MM".
HEURE_QUOTIDIENNE = os.environ.get("OUROULER_HEURE_GENERATION", "06:00")

#: Nom stable de la page servie par le conteneur « serveur » — un nom fixe
#: pour que l'URL ne change jamais, la date se lit dans le contenu de la page
#: (contrat, périmètre point 5), pas dans son nom de fichier.
NOM_PAGE = "index.html"


def executer_une_fois() -> int:
    """Un passage de `ourouler sortie`. Rend le code de sortie du sous-processus."""
    jour = datetime.now().strftime("%Y%m%d")
    carte = os.path.join(DOSSIER_PAGES, NOM_PAGE)
    gpx = os.path.join(DOSSIER_PAGES, f"sortie_{jour}.gpx")
    commande = [
        "ourouler",
        "--config",
        CHEMIN_CONFIG,
        "sortie",
        "--carte",
        carte,
        "--sortie",
        gpx,
        "--carte-sans-seance",
        "--ecraser",
    ]
    horodatage = datetime.now().isoformat(timespec="seconds")
    print(f"[{horodatage}] {' '.join(commande)}", flush=True)
    resultat = subprocess.run(commande)
    if resultat.returncode != 0:
        print(f"[{horodatage}] ourouler sortie a échoué (code {resultat.returncode})", file=sys.stderr)
    return resultat.returncode


def _valider_heure(heure: str) -> tuple[int, int]:
    """« HH:MM », ou une erreur claire **avant** la première génération.

    Relecture du 16/09/2026, point 2 b : sans cette validation, une faute de
    frappe (`6h`, `06h00`) laissait passer la première génération — ~150 appels
    Open-Meteo et 5 BRouter — puis faisait tomber le conteneur sur
    `int("6h")`. Avec `restart: unless-stopped`, Docker le relançait, et la
    boucle brûlait le quota toute la nuit à raison d'un cycle par minute.
    On échoue donc **au démarrage**, avant de dépenser quoi que ce soit.
    """
    morceaux = heure.split(":")
    if len(morceaux) != 2 or not all(m.isdigit() for m in morceaux):
        raise SystemExit(
            f"OUROULER_HEURE_GENERATION = {heure!r} : format attendu « HH:MM », "
            "par exemple 06:00"
        )
    h, m = int(morceaux[0]), int(morceaux[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise SystemExit(
            f"OUROULER_HEURE_GENERATION = {heure!r} : heure hors des bornes "
            "(00:00 à 23:59)"
        )
    return h, m


def _prochain_declenchement(heure: str, maintenant: datetime) -> datetime:
    h, m = _valider_heure(heure)
    cible = maintenant.replace(hour=h, minute=m, second=0, microsecond=0)
    if cible <= maintenant:
        cible += timedelta(days=1)
    return cible


def main() -> None:
    # La validation passe **avant** la première génération : un format
    # invalide doit coûter zéro appel, pas 150 par redémarrage.
    _valider_heure(HEURE_QUOTIDIENNE)
    os.makedirs(DOSSIER_PAGES, exist_ok=True)
    executer_une_fois()
    while True:
        cible = _prochain_declenchement(HEURE_QUOTIDIENNE, datetime.now())
        attente_s = max(0.0, (cible - datetime.now()).total_seconds())
        print(
            f"prochaine génération : {cible.isoformat(timespec='minutes')} "
            f"(dans {attente_s / 3600:.1f} h)",
            flush=True,
        )
        time.sleep(attente_s)
        executer_une_fois()


if __name__ == "__main__":
    main()

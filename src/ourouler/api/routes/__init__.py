"""Les routes de l'API, déduites des vingt écrans des maquettes.

Toutes sont préfixées `/api/v1`. Toutes celles qui calculent rendent la même
enveloppe — `{donnees, avertissements, duree_ms, budget}` — et toutes celles
qui échouent rendent la même forme d'erreur (`erreurs.py`).

Le propriétaire traverse **chaque** requête : la dépendance `proprietaire`
le résout, et il est passé en premier argument à tout accès aux données
(doctrine §10.2). Aucune route ne lit un fichier de configuration
elle-même : elle demande sa `Config` au dépôt, pour ce propriétaire-là.

Ce qui n'est **pas** exposé, et pourquoi : `--synchroniser` et `routes
apprendre --appliquer` écrivent dans le cache du serveur et durent des
minutes — ce sont des gestes d'administration que le mainteneur fait en
ligne de commande, et aucun écran des maquettes ne les demande.

**`calibrer` l'est depuis L9.4** (`POST /calibrations`,
`docs/journal/sprints/sprint9_contrat.md`) : un compte hébergé avec capteur calibre son vélo
sans la ligne de commande du mainteneur. Même calcul
(`services.calibrer.calibrer_velo`), en tâche de fond comme l'import
(`api/taches_fond.py`, un seul calcul lourd à la fois), et écrit dans le
dossier **du compte** — jamais dans le fichier de calibration du cache du
serveur (`_config`, `api/calibrations.py`).
`inventaire --importer DOSSIER` reste lui aussi hors API : c'est une lecture
d'un chemin sur le **système de fichiers du serveur**, pas un dépôt du
cycliste — l'exposer ferait de l'API une console d'administration.

**Ce que L9.2 expose, `POST /activites/import`, est différent** : un
cycliste sans Intervals dépose **ses propres octets** — fichiers isolés ou
archive d'export Strava/Garmin — jamais un chemin. C'est le mécanisme que
`Cache.indexer_dossier` appelle en CLI (`activites/import_archive.py`),
rejoué ici sur des octets reçus par HTTP et bornés (taille, nombre de
fichiers, décompression, chemins), pas sur un dossier du serveur
(`docs/journal/sprints/sprint9_contrat.md`, lot L9.2).

**Un module par domaine** (lot 13 du plan de restructuration) : chacun porte
son propre routeur, au préfixe et aux pannes déclarées de `commun.py`, et
`routeur` les assemble ici **dans l'ordre d'enregistrement d'avant le
découpage** — le routeur essaie les routes dans cet ordre, et
`tests/api/test_resolution_routes.py` fige ce que chaque chemin résout.
"""

from __future__ import annotations

from fastapi import APIRouter

from ourouler.api.routes import (
    activites,
    calibrations,
    fichiers,
    generations,
    inventaire,
    meteo,
    moi,
    parcours,
    profil,
    seances,
    sessions,
    systeme,
)

routeur = APIRouter()
routeur.include_router(sessions.routeur)
routeur.include_router(systeme.routeur)
routeur.include_router(profil.routeur)
routeur.include_router(meteo.routeur)
routeur.include_router(seances.routeur)
routeur.include_router(activites.routeur)
routeur.include_router(calibrations.routeur)
routeur.include_router(generations.routeur)
routeur.include_router(parcours.routeur)
routeur.include_router(inventaire.routeur)
routeur.include_router(fichiers.routeur)
routeur.include_router(moi.routeur)

__all__ = ["routeur"]

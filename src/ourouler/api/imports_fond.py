"""Import d'historique en tâche de fond — suite de la relecture du 25/09/2026.

Une archive Strava réelle (≈2 900 sorties, mesuré sur le cache du
mainteneur) prend environ 16 minutes à 0,33 s/fichier — bien au-delà des
180 s où le front abandonne (`front/src/api/client.ts`, `DELAI_CALCUL_MS`).
`POST /activites/import` ne peut donc plus attendre la fin de l'import pour
répondre : il **lance** l'import et rend un identifiant tout de suite (202),
et `GET /activites/import/{id}` dit où il en est.

**Un seul import à la fois, pour le serveur entier** — pas par propriétaire.
C'est déjà la règle posée par la relecture du 25/09/2026 (`_VERROU_IMPORT`,
alors bloquant) : le serveur est petit, partagé avec BRouter, et deux
imports simultanés doubleraient le pic mémoire mesuré (106 Mo pour une
archive de 99 Mo). `lancer()` refuse plutôt que de mettre en file — un
deuxième demandeur reçoit un refus lisible (`import_deja_en_cours`,
`api/erreurs.py`) et sait qu'il peut réessayer, plutôt que d'attendre en
silence derrière l'import de quelqu'un d'autre.

**Cloisonné par propriétaire.** `Job.proprietaire` porte l'identité de qui a
lancé l'import ; `trouver()` ne rend jamais le job d'un autre — même refus
que `DepotFichiers.trouver` pour un identifiant qui n'est pas le sien
(`fichier_introuvable`), pour ne renseigner personne sur l'existence d'un
import qu'il n'a pas lancé.

**Le registre, le verrou et le cloisonnement vivent désormais dans
`api/taches_fond.py`** (L9.4, 25/09/2026), partagés avec la calibration :
le verrou est celui des tâches lourdes, import *ou* calibration. Ce module
garde ce qui est propre à l'import et ré-exporte le reste sous ses noms
d'origine.

Ce module ne lit ni fichier de configuration ni variable d'environnement
(doctrine §2) : il reçoit un `Cache` déjà construit pour un propriétaire et
des dépôts déjà résolus (chemins de fichiers temporaires) — exactement ce
que `api/routes.py` lui passe.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.activites.import_archive import importer
from ourouler.api.taches_fond import (
    JOBS_GARDES,
    NATURE_IMPORT,
    STATUT_ECHOUE,
    STATUT_EN_COURS,
    STATUT_FINI,
    VERROU,
    Job,
)
from ourouler.api.taches_fond import ErreurTacheEnCours as ErreurImportEnCours
from ourouler.api.taches_fond import lancer as _lancer_tache
from ourouler.api.taches_fond import trouver as _trouver_tache


def lancer(
    cache: Cache,
    proprietaire: str,
    depots: list[tuple[str, Path]],
    *,
    au_echec: Callable[[], None] | None = None,
) -> Job:
    """Démarre un import en tâche de fond. Lève `ErreurImportEnCours` si une tâche lourde tourne.

    `depots` : `[(nom, chemin)]` — des chemins de fichiers déjà sur disque
    (une copie propre au job, voir `api/routes.py`), jamais l'`UploadFile` de
    la requête : celui-ci ne survit pas à la réponse 202 que cette fonction
    permet de rendre tout de suite (Starlette referme ses fichiers temporaires
    une fois la requête terminée).
    """

    def travailler(job: Job):
        fichiers = [(nom, chemin.open("rb")) for nom, chemin in depots]
        try:
            # `importer` est relu dans ce module à chaque appel : un test peut
            # le remplacer (`monkeypatch`) sans toucher au registre.
            return importer(
                cache,
                [(nom, f) for nom, f in fichiers],
                progres=lambda traites, total: job.avancer(traites, total),
            )
        finally:
            for _, f in fichiers:
                f.close()

    def effacer_depots() -> None:
        for _, chemin in depots:
            chemin.unlink(missing_ok=True)

    return _lancer_tache(
        proprietaire, NATURE_IMPORT, travailler, au_echec=au_echec, enfin=effacer_depots
    )


def trouver(proprietaire: str, id_job: str) -> Job | None:
    """Le job d'import de **ce** propriétaire portant cet identifiant, ou `None`."""
    return _trouver_tache(proprietaire, id_job, NATURE_IMPORT)


__all__ = [
    "JOBS_GARDES",
    "STATUT_ECHOUE",
    "STATUT_EN_COURS",
    "STATUT_FINI",
    "VERROU",
    "ErreurImportEnCours",
    "Job",
    "lancer",
    "trouver",
]

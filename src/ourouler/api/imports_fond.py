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

Ce module ne lit ni fichier de configuration ni variable d'environnement
(doctrine §2) : il reçoit un `Cache` déjà construit pour un propriétaire et
des dépôts déjà résolus (chemins de fichiers temporaires) — exactement ce
que `api/routes.py` lui passe.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ourouler.activites.cache import Cache
from ourouler.activites.import_archive import RapportImport, importer

#: Un seul import à la fois, pour tout le serveur — voir le module.
VERROU = threading.Lock()

#: Combien de tâches on garde en mémoire (en cours ou terminées) avant
#: d'oublier les plus vieilles déjà terminées. Un `Job` pèse quelques
#: centaines d'octets (le rapport compris) : large marge pour qu'un
#: mainteneur qui recharge sa page retrouve toujours son import.
JOBS_GARDES = 200

#: Les trois états qu'un job traverse, dans cet ordre — jamais de retour en arrière.
STATUT_EN_COURS = "en_cours"
STATUT_FINI = "fini"
STATUT_ECHOUE = "echoue"


class ErreurImportEnCours(Exception):
    """Un import tourne déjà sur ce serveur : `lancer()` refuse plutôt que d'attendre."""


@dataclass
class Job:
    """L'état d'un import, tel que `GET /activites/import/{id}` le rend."""

    id: str
    proprietaire: str
    statut: str = STATUT_EN_COURS
    traites: int = 0
    total: int = 0
    rapport: RapportImport | None = None
    erreur: str | None = None
    demarre_le: float = field(default_factory=time.monotonic)

    def json(self) -> dict:
        return {
            "id": self.id,
            "statut": self.statut,
            "traites": self.traites,
            "total": self.total,
            "rapport": self.rapport.json() if self.rapport is not None else None,
            "erreur": self.erreur,
        }


_verrou_registre = threading.Lock()
_jobs: dict[str, Job] = {}


def lancer(cache: Cache, proprietaire: str, depots: list[tuple[str, Path]]) -> Job:
    """Démarre un import en tâche de fond. Lève `ErreurImportEnCours` si un autre tourne déjà.

    `depots` : `[(nom, chemin)]` — des chemins de fichiers déjà sur disque
    (une copie propre au job, voir `api/routes.py`), jamais l'`UploadFile` de
    la requête : celui-ci ne survit pas à la réponse 202 que cette fonction
    permet de rendre tout de suite (Starlette referme ses fichiers temporaires
    une fois la requête terminée).
    """
    if not VERROU.acquire(blocking=False):
        raise ErreurImportEnCours
    job = Job(id=uuid.uuid4().hex, proprietaire=proprietaire)
    with _verrou_registre:
        _jobs[job.id] = job
        _purger()

    def travailler() -> None:
        try:
            fichiers = [(nom, chemin.open("rb")) for nom, chemin in depots]
            try:
                rapport = importer(
                    cache,
                    [(nom, f) for nom, f in fichiers],
                    progres=lambda traites, total: _avancer(job, traites, total),
                )
            finally:
                for _, f in fichiers:
                    f.close()
            job.rapport = rapport
            job.statut = STATUT_FINI
        except Exception as e:  # noqa: BLE001 — une tâche de fond ne doit jamais planter en silence
            job.erreur = str(e) or type(e).__name__
            job.statut = STATUT_ECHOUE
        finally:
            for _, chemin in depots:
                chemin.unlink(missing_ok=True)
            VERROU.release()

    threading.Thread(target=travailler, daemon=True, name=f"import-{job.id[:8]}").start()
    return job


def _avancer(job: Job, traites: int, total: int) -> None:
    job.traites = traites
    job.total = total


def trouver(proprietaire: str, id_job: str) -> Job | None:
    """Le job de **ce** propriétaire portant cet identifiant, ou `None`."""
    with _verrou_registre:
        job = _jobs.get(id_job)
    return job if job is not None and job.proprietaire == proprietaire else None


def _purger() -> None:
    """Oublie les tâches terminées les plus anciennes au-delà de `JOBS_GARDES`.

    Appelée sous `_verrou_registre` (voir `lancer`) : jamais deux purges en
    même temps, jamais une purge pendant qu'un job entre dans le registre.
    """
    if len(_jobs) <= JOBS_GARDES:
        return
    termines = sorted(
        (j for j in _jobs.values() if j.statut != STATUT_EN_COURS), key=lambda j: j.demarre_le
    )
    for job in termines[: len(_jobs) - JOBS_GARDES]:
        _jobs.pop(job.id, None)


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

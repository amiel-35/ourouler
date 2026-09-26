"""Les tâches lourdes en tâche de fond : import d'historique et calibration.

Deux gestes durent bien au-delà des 180 s où le front abandonne une requête
(`front/src/api/client.ts`, `DELAI_CALCUL_MS`) : importer une archive Strava
réelle (≈16 minutes pour ≈2 900 sorties, mesuré sur un historique réel)
et calibrer un vélo (relire chaque FIT, une archive météo par jour de sortie).
Leur route **lance** le travail et rend un identifiant tout de suite (202) ;
une route `GET …/{id}` dit où il en est.

Ce module est le registre commun à l'import (`api/imports_fond.py`) et à la
calibration.

**Une seule tâche lourde à la fois, pour le serveur entier** — import *ou*
calibration, quel que soit le propriétaire. Le serveur est petit, partagé
avec BRouter : deux imports simultanés doubleraient le pic mémoire mesuré
(106 Mo pour une archive de 99 Mo), et une calibration relit tous les
fichiers d'un compte. `lancer()` refuse plutôt que de mettre en file : un
second demandeur reçoit un refus lisible et sait qu'il peut réessayer.

**Ce verrou n'est pas celui des calculs courts** (`api/adaptateur._VERROU`,
`calcul_en_cours`) : une calibration qui tiendrait celui-là bloquerait toutes
les générations de boucles pendant des minutes. Une tâche de fond n'écrit
donc **jamais** sur la sortie standard — c'est ce que ce verrou-là protège —
et appelle le cœur par une fonction qui rend un objet (`services.calibrer.calibrer_velo`,
`activites.import_archive.importer`), jamais par une commande qui imprime.

**Cloisonné par propriétaire.** `Job.proprietaire` porte l'identité de qui a
lancé la tâche ; `trouver()` ne rend jamais le job d'un autre — même refus
que `DepotFichiers.trouver` pour un identifiant qui n'est pas le sien.

**Annulable, pour la suppression d'un compte.** Sans annulation, `DELETE /moi`
pendant un import effacerait les lignes du compte… puis l'import en cours en
réécrirait, fichiers bruts compris, pour un compte qui n'existe plus.
`annuler_et_attendre` lève le drapeau d'annulation des tâches du propriétaire,
que chaque tâche regarde à chaque pas
(`Job.avancer`, `Job.verifier_annulation`), **attend qu'elles aient rendu la
main**, et bloque tout nouveau lancement pour ce propriétaire jusqu'à la fin
de l'effacement (`suspendre`).

Ce module ne lit ni fichier de configuration ni variable d'environnement
(doctrine §2) : il reçoit un travail déjà préparé par `api/routes/`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

#: Une seule tâche lourde à la fois, pour tout le serveur — voir le module.
VERROU = threading.Lock()

#: Combien de tâches on garde en mémoire (en cours ou terminées) avant
#: d'oublier les plus vieilles déjà terminées. Un `Job` pèse quelques
#: centaines d'octets (le rapport compris) : large marge pour qu'un cycliste
#: qui recharge sa page retrouve toujours sa tâche.
JOBS_GARDES = 200

#: Les trois états qu'un job traverse, dans cet ordre — jamais de retour en arrière.
STATUT_EN_COURS = "en_cours"
STATUT_FINI = "fini"
STATUT_ECHOUE = "echoue"

#: Les deux natures de tâche. La nature entre dans `trouver` : l'identifiant
#: d'une calibration ne se lit pas par la route des imports, et inversement.
NATURE_IMPORT = "import"
NATURE_CALIBRATION = "calibration"

_journal = logging.getLogger(__name__)

#: Le code d'une tâche tombée sur autre chose qu'un échec prévu : un bug, ou
#: une panne du serveur. Le message ne dit rien de plus : `str(e)` renverrait
#: au cycliste le texte interne de l'exception (un chemin du serveur, un nom
#: de module…). La trace complète
#: reste au journal.
CODE_ERREUR_INTERNE = "erreur_interne"
MESSAGE_ERREUR_INTERNE = (
    "la tâche s'est arrêtée sur une erreur du serveur — le détail est au journal du "
    "serveur, pas dans cette réponse"
)


class ErreurTacheEnCours(Exception):
    """Une tâche lourde tourne déjà sur ce serveur : `lancer()` refuse plutôt que d'attendre.

    `nature` dit laquelle, pour que le refus nomme ce qui occupe le serveur.
    """

    def __init__(self, nature: str | None = None) -> None:
        super().__init__(nature or "")
        self.nature = nature


class EchecLisible(Exception):  # « échec », pas « erreur » : c'est le cycliste qui le lit
    """Un échec qu'on peut montrer tel quel au cycliste : le message est déjà assaini.

    Tout autre exception d'un travail devient un message générique — la trace
    reste au journal du serveur, jamais dans la réponse (`CODE_ERREUR_INTERNE`).
    """

    code = "echec"


class TacheAnnulee(EchecLisible):
    """Levée dans la tâche elle-même, au premier pas après `annuler_et_attendre`."""

    code = "annulee"

    def __init__(self) -> None:
        super().__init__("annulée : le compte a été supprimé pendant la tâche")


class SuppressionDejaEnCours(Exception):  # un refus, pas une erreur du serveur
    """`DELETE /moi` du même compte tourne déjà : celui-ci refuse plutôt que d'attendre à son tour.

    Levée par `debuter_effacement` refusé — voir `api/vie_privee.effacer_donnees`,
    qui ne tient jamais deux effacements du même propriétaire en même temps.
    """

    code = "suppression_deja_en_cours"
    message = (
        "une suppression de ce compte est déjà en cours — inutile de la relancer, "
        "attendre que la première termine (jusqu'à deux minutes)"
    )


@dataclass
class Job:
    """L'état d'une tâche, tel que la route `GET …/{id}` le rend."""

    id: str
    proprietaire: str
    nature: str = NATURE_IMPORT
    statut: str = STATUT_EN_COURS
    traites: int = 0
    total: int = 0
    #: Ce que la tâche en est à faire (calibration : « lecture », « meteo »,
    #: « ajustement ») — vide pour un import, qui n'a qu'une étape.
    etape: str = ""
    #: Ce sur quoi porte la tâche — le nom du vélo pour une calibration.
    sujet: str | None = None
    rapport: object | None = None
    erreur: str | None = None
    #: Le code de l'échec — `EchecLisible.code` (« echec », « annulee »…) ou
    #: `CODE_ERREUR_INTERNE` —, `None` tant que la tâche n'a pas échoué.
    code_erreur: str | None = None
    demarre_le: float = field(default_factory=time.monotonic)
    _annule: threading.Event = field(default_factory=threading.Event, repr=False)
    _termine: threading.Event = field(default_factory=threading.Event, repr=False)

    def verifier_annulation(self) -> None:
        """Lève `TacheAnnulee` si la tâche a été annulée. À appeler avant toute écriture."""
        if self._annule.is_set():
            raise TacheAnnulee

    def avancer(self, traites: int, total: int, etape: str | None = None) -> None:
        """Note l'avancement — et arrête la tâche si elle a été annulée entre deux pas."""
        self.verifier_annulation()
        self.traites = traites
        self.total = total
        if etape is not None:
            self.etape = etape

    def json(self) -> dict:
        rapport = self.rapport
        if rapport is not None and hasattr(rapport, "json"):
            rapport = rapport.json()
        charge = {
            "id": self.id,
            "statut": self.statut,
            "traites": self.traites,
            "total": self.total,
            "rapport": rapport,
            "erreur": self.erreur,
            "code_erreur": self.code_erreur,
        }
        if self.nature != NATURE_IMPORT:
            # La forme d'un job d'import est figée (le front la lit) ; les
            # champs propres aux autres natures s'y ajoutent.
            charge.update({"nature": self.nature, "etape": self.etape, "sujet": self.sujet})
        return charge


_verrou_registre = threading.Lock()
_jobs: dict[str, Job] = {}
#: La nature de la tâche qui tient `VERROU`, pour nommer ce qui occupe le serveur.
_occupant: list[str | None] = [None]
#: Les propriétaires dont le compte est en train d'être effacé : aucune tâche
#: ne se lance pour eux (`suspendre`). Un **compte** d'effacements en cours
#: et non un ensemble : deux `DELETE /moi` simultanés du même compte, le
#: premier qui finit levait la suspension pendant que le second effaçait.
_suspendus: dict[str, int] = {}
#: Les propriétaires pour qui un `DELETE /moi` est déjà passé la porte de
#: `vie_privee.effacer_donnees` et attend `annuler_et_attendre` (jusqu'à
#: 120 s). **Un ensemble, pas un compte** (contrairement à `_suspendus`) :
#: contrairement aux tâches lourdes, qui s'enchaînent légitimement (une
#: suppression suit l'autre), deux effacements du même compte en même temps
#: n'ont aucun sens — le second doit refuser, pas attendre à son tour et
#: occuper un second fil du serveur pour rien.
_effacements_en_cours: set[str] = set()


def lancer(
    proprietaire: str,
    nature: str,
    travail: Callable[[Job], object],
    *,
    sujet: str | None = None,
    au_echec: Callable[[], None] | None = None,
    enfin: Callable[[], None] | None = None,
) -> Job:
    """Démarre `travail(job)` dans un fil. Lève `ErreurTacheEnCours` si une autre tourne.

    `travail` rend le rapport de la tâche (ou lève). `au_echec` est appelé
    quand il lève — c'est là qu'un quota consommé se rembourse ; `enfin`
    toujours, après — c'est là que des fichiers temporaires s'effacent.
    """
    # Contrôle de suspension, prise du verrou et entrée au registre **d'un
    # seul tenant** : séparés, un lancement qui aurait passé le contrôle juste
    # avant `suspendre` entrerait au registre juste après
    # `annuler_et_attendre`, qui ne l'aurait donc pas attendu — et la tâche
    # écrirait pour un compte effacé. `VERROU.acquire` ne bloque
    # pas : le tenir sous `_verrou_registre` ne fait attendre personne.
    with _verrou_registre:
        if _suspendus.get(proprietaire):
            raise ErreurTacheEnCours(None)
        if not VERROU.acquire(blocking=False):
            raise ErreurTacheEnCours(_occupant[0])
        _occupant[0] = nature
        job = Job(id=uuid.uuid4().hex, proprietaire=proprietaire, nature=nature, sujet=sujet)
        _jobs[job.id] = job
        _purger()

    def executer() -> None:
        try:
            job.rapport = travail(job)
            job.statut = STATUT_FINI
        except EchecLisible as e:
            job.erreur = str(e)
            job.code_erreur = e.code
            job.statut = STATUT_ECHOUE
        except Exception:  # une tâche de fond ne doit jamais planter en silence
            _journal.exception("tâche de fond %s (%s) en échec", job.id, nature)
            job.erreur = MESSAGE_ERREUR_INTERNE
            job.code_erreur = CODE_ERREUR_INTERNE
            job.statut = STATUT_ECHOUE
        finally:
            try:
                if job.statut == STATUT_ECHOUE and au_echec is not None:
                    au_echec()
                if enfin is not None:
                    enfin()
            finally:
                _occupant[0] = None
                VERROU.release()
                job._termine.set()

    try:
        threading.Thread(target=executer, daemon=True, name=f"{nature}-{job.id[:8]}").start()
    except BaseException:
        # Un fil qui ne démarre pas (plus de fils disponibles, mémoire) garderait
        # sinon le verrou pour toujours — plus aucun import ni calibration sur
        # ce serveur jusqu'au redémarrage. Le job est retiré, le verrou rendu, l'erreur remonte.
        with _verrou_registre:
            _jobs.pop(job.id, None)
        _occupant[0] = None
        VERROU.release()
        job._termine.set()
        raise
    return job


def annuler_et_attendre(proprietaire: str, delai_s: float = 120.0) -> bool:
    """Annule les tâches en cours de ce propriétaire et attend qu'elles aient rendu la main.

    Rend `True` quand plus aucune ne tourne ; `False` si l'une d'elles n'a pas
    fini dans `delai_s` — l'appelant ne doit alors **rien** effacer, puisque
    la tâche peut encore écrire. Un import s'arrête au fichier suivant (un
    tiers de seconde) ; une calibration au prochain pas, ou à la fin de son
    ajustement, qui ne s'interrompt pas (au plus une ou deux minutes sur
    un historique réel de plusieurs années).
    """
    with _verrou_registre:
        # `_termine` et non `statut` : un job « fini » n'a pas encore rendu
        # la main tant que son `au_echec` et son `enfin` tournent.
        en_cours = [j for j in _jobs.values() if j.proprietaire == proprietaire and not j._termine.is_set()]
    for job in en_cours:
        job._annule.set()
    echeance = time.monotonic() + delai_s
    return all(job._termine.wait(max(0.0, echeance - time.monotonic())) for job in en_cours)


class suspendre:  # s'emploie comme une fonction : `with suspendre(qui):`
    """Aucune nouvelle tâche pour ce propriétaire tant que le bloc dure (suppression du compte).

    Une classe et non un `@contextmanager` : une `ErreurApi` (dataclass figée)
    levée dans le bloc traverserait le générateur, qui tente d'écrire son
    `__traceback__` — et échoue sur une instance figée.
    """

    def __init__(self, proprietaire: str) -> None:
        self.proprietaire = proprietaire

    def __enter__(self) -> None:
        with _verrou_registre:
            _suspendus[self.proprietaire] = _suspendus.get(self.proprietaire, 0) + 1

    def __exit__(self, *exc: object) -> bool:
        with _verrou_registre:
            reste = _suspendus.get(self.proprietaire, 1) - 1
            if reste > 0:
                _suspendus[self.proprietaire] = reste
            else:
                _suspendus.pop(self.proprietaire, None)
        return False


def debuter_effacement(proprietaire: str) -> None:
    """Marque un effacement en cours pour ce propriétaire, ou lève `SuppressionDejaEnCours`.

    À appeler **avant** `suspendre`/`annuler_et_attendre` dans
    `vie_privee.effacer_donnees` : c'est ce qui évite qu'un second
    `DELETE /moi` du même compte attende, lui aussi, jusqu'à 120 s sur un
    fil du serveur pendant que le premier fait déjà le travail.
    """
    with _verrou_registre:
        if proprietaire in _effacements_en_cours:
            raise SuppressionDejaEnCours
        _effacements_en_cours.add(proprietaire)


def finir_effacement(proprietaire: str) -> None:
    """Lève la marque posée par `debuter_effacement` — à appeler dans un `finally`."""
    with _verrou_registre:
        _effacements_en_cours.discard(proprietaire)


def occupant() -> str | None:
    """La nature de la tâche qui tient le verrou, ou `None` — pour nommer ce qui occupe."""
    return _occupant[0]


def trouver(proprietaire: str, id_job: str, nature: str = NATURE_IMPORT) -> Job | None:
    """Le job de **ce** propriétaire, de cette nature, portant cet identifiant, ou `None`."""
    with _verrou_registre:
        job = _jobs.get(id_job)
    if job is None or job.proprietaire != proprietaire or job.nature != nature:
        return None
    return job


def dernier(proprietaire: str, nature: str, sujet: str | None = None) -> Job | None:
    """Le job le plus récent de ce propriétaire pour cette nature (et ce sujet), ou `None`.

    Sert à reprendre l'affichage d'une calibration après un rechargement de
    page : le front n'a pas à garder l'identifiant pour la retrouver.
    """
    with _verrou_registre:
        candidats = [
            j
            for j in _jobs.values()
            if j.proprietaire == proprietaire and j.nature == nature and (sujet is None or j.sujet == sujet)
        ]
    return max(candidats, key=lambda j: j.demarre_le, default=None)


def _purger() -> None:
    """Oublie les tâches terminées les plus anciennes au-delà de `JOBS_GARDES`.

    Appelée sous `_verrou_registre` (voir `lancer`) : jamais deux purges en
    même temps, jamais une purge pendant qu'un job entre dans le registre.
    """
    if len(_jobs) <= JOBS_GARDES:
        return
    termines = sorted((j for j in _jobs.values() if j.statut != STATUT_EN_COURS), key=lambda j: j.demarre_le)
    for job in termines[: len(_jobs) - JOBS_GARDES]:
        _jobs.pop(job.id, None)


__all__ = [
    "JOBS_GARDES",
    "NATURE_CALIBRATION",
    "NATURE_IMPORT",
    "STATUT_ECHOUE",
    "STATUT_EN_COURS",
    "STATUT_FINI",
    "VERROU",
    "EchecLisible",
    "ErreurTacheEnCours",
    "Job",
    "SuppressionDejaEnCours",
    "TacheAnnulee",
    "annuler_et_attendre",
    "debuter_effacement",
    "dernier",
    "finir_effacement",
    "lancer",
    "occupant",
    "suspendre",
    "trouver",
]

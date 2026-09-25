"""Intergiciel ASGI : refuser un import **avant** d'en lire le corps (contre-lecture Fable, 25/09/2026).

`POST /activites/import` reçoit jusqu'à `TAILLE_MAX_REQUETE` octets (750 Mo).
FastAPI lit et écrit **tout** le corps multipart sur disque avant d'appeler la
route — puis la route le recopie encore en fichiers temporaires à elle. Tout
refus décidé dans la route (pas de session, un import ou une calibration qui
tient déjà le verrou des tâches lourdes, un quota épuisé) arrive donc après
que le serveur a payé l'envoi entier : 750 Mo reçus et écrits deux fois pour
s'entendre dire « réessayez plus tard ».

Cet intergiciel pose ces trois refus **avant** le premier octet du corps, sur
ce qui se sait sans lui : l'en-tête de session, l'état du verrou, le compteur
du compte. Même code, même forme que ceux de la route — `session_absente`
(401), `import_deja_en_cours` (409), `quota_atteint` (429) — parce que c'est
le même refus, seulement plus tôt. La route garde les siens : entre ce
contrôle et la prise du verrou, un autre import peut partir (la course est
réelle, sa fenêtre est celle d'un envoi), et c'est alors elle qui refuse,
après l'envoi, comme avant.

Il ne lit ni fichier de configuration ni variable d'environnement : il trouve
le contexte de l'application là où Starlette le pose (`scope["app"]`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.requests import Request

from ourouler.api import taches_fond
from ourouler.api.erreurs import ErreurApi
from ourouler.api.session import CODE_SANS_SESSION, MESSAGE_SANS_SESSION, MODE_PERSONNEL

Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]

#: La seule route gardée : celle dont le corps peut peser des centaines de
#: mégaoctets. `POST /seances/fichier` est borné à 1 Mo, `POST /calibrations`
#: n'a qu'un petit corps JSON — les refuser après lecture ne coûte rien.
CHEMIN_IMPORT = "/api/v1/activites/import"


class GardeAvantCorps:
    """Refuse `POST /activites/import` sans session, serveur occupé ou quota épuisé."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if (
            scope.get("type") == "http"
            and scope.get("method") == "POST"
            and scope.get("path", "").rstrip("/") == CHEMIN_IMPORT
        ):
            refus = self._refus(scope)
            if refus is not None:
                from ourouler.api.routes import reponse_erreur

                await reponse_erreur(refus)(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _refus(self, scope: dict) -> ErreurApi | None:
        application = scope.get("app")
        ctx = getattr(getattr(application, "state", None), "ourouler", None)
        if ctx is None:  # pragma: no cover — une application sans contexte n'a rien à garder
            return None
        qui = ctx.session.ouvrir(Request(scope))
        if qui is None:
            return ErreurApi(code=CODE_SANS_SESSION, message=MESSAGE_SANS_SESSION, statut=401)
        if taches_fond.VERROU.locked():
            from ourouler.api.routes import _message_occupe

            return ErreurApi(
                code="import_deja_en_cours",
                message=_message_occupe(taches_fond.occupant()),
                statut=409,
            )
        if ctx.session.mode != MODE_PERSONNEL:
            try:
                ctx.quotas_import.refuser_si_epuise(qui)
            except ErreurApi as erreur:
                return erreur
        return None


__all__ = ["CHEMIN_IMPORT", "GardeAvantCorps"]

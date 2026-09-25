"""Intergiciel ASGI : refuse un corps trop gros **avant** qu'il touche le disque.

`_refuser_import_sur_la_taille_annoncee` et son jumeau pour les séances
(`api/routes.py`) ne lisent que l'en-tête `Content-Length` — un client qui
ment (ou qui envoie en `Transfer-Encoding: chunked`, sans `Content-Length`
du tout) les traverse sans être vu, et Starlette a déjà écrit le corps
multipart entier dans un fichier temporaire avant que la route ne s'exécute
et ne compte quoi que ce soit. C'est le trou que cet intergiciel ferme : il
compte les octets **au fil de l'eau**, à mesure que le parseur multipart de
Starlette les lit, et coupe la lecture au premier octet au-delà de la borne
de la route — Starlette n'a alors jamais écrit plus que la borne — puis
répond 413 lui-même.

Volontairement **pas** un `starlette.middleware.base.BaseHTTPMiddleware` :
il attend le corps entier avant de rendre la main à l'appelant, ce qui
charge en mémoire exactement ce qu'on veut éviter d'écrire sur disque.

**Et rien n'est accumulé ici non plus** (contre-lecture Fable du 25/09/2026).
La première version égrenait tout le corps, le gardait en mémoire pour le
rejouer, et n'appelait l'application qu'après le dernier morceau : 300
morceaux de 1 Mo, un pic de 300 Mo avant que Starlette n'ait vu un octet —
la borne protégeait le disque en sacrifiant la mémoire. Maintenant
l'application est appelée **tout de suite**, avec un `receive()` enveloppé
qui compte au fil de l'eau et lève `_CorpsTropGros` dès que le total passe
la borne. Le parseur multipart s'arrête là ; ce qu'il a déjà écrit est à lui
de le nettoyer (Starlette referme ses fichiers temporaires).

**Le refus reste un 413 lisible.** FastAPI traduit toute exception levée
pendant la lecture du corps en un 400 « There was an error parsing the
body » : l'exception ne remonte donc pas toujours jusqu'ici. `send()` est
enveloppé lui aussi : une fois la borne dépassée, la réponse de
l'application est jetée et remplacée par le 413 — tant qu'aucun octet de
réponse n'est parti, ce qui est toujours le cas quand c'est la lecture du
corps qui échoue.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping

Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]


class _CorpsTropGros(Exception):  # noqa: N818 — un signal interne, jamais montré
    """Levée par le `receive()` enveloppé au premier octet de trop."""

    def __init__(self, mesure: int) -> None:
        super().__init__(mesure)
        self.mesure = mesure


class LimiteTailleCorps:
    """Refuse, par préfixe de chemin, un corps de requête au-delà d'une borne.

    `bornes` : `{préfixe_de_chemin: plafond_en_octets}`. Un chemin qui ne
    correspond à aucun préfixe traverse sans y regarder — cet intergiciel ne
    change rien pour le reste de l'API, dont les corps sont déjà petits et
    validés par Pydantic.
    """

    def __init__(self, app, bornes: Mapping[str, int]) -> None:
        self.app = app
        self.bornes = dict(bornes)

    def _plafond(self, chemin: str) -> int | None:
        return next((v for prefixe, v in self.bornes.items() if chemin.startswith(prefixe)), None)

    async def __call__(self, scope: dict, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        plafond = self._plafond(scope.get("path", ""))
        if plafond is None:
            await self.app(scope, receive, send)
            return

        # **`Content-Length` d'abord** : un refus avant de lire le moindre
        # octet quand le client l'annonce lui-même au-delà de la borne.
        annonce = _content_length(scope)
        if annonce is not None and annonce > plafond:
            await _413(send, annonce, plafond, mode="annoncés")
            return

        # **Puis le flux réel**, compté au fil de l'eau — `Content-Length`
        # peut mentir, ou manquer (`Transfer-Encoding: chunked`). Rien n'est
        # gardé : chaque morceau passe à l'application dès qu'il arrive.
        total = 0
        depasse: int | None = None
        reponse_partie = False
        refus_envoye = False

        async def compter() -> dict:
            nonlocal total, depasse
            if depasse is not None:
                raise _CorpsTropGros(depasse)
            message = await receive()
            if message.get("type") == "http.request":
                total += len(message.get("body") or b"")
                if total > plafond:
                    depasse = total
                    raise _CorpsTropGros(total)
            return message

        async def envoyer(message: dict) -> None:
            nonlocal reponse_partie, refus_envoye
            if depasse is not None and not reponse_partie:
                # La réponse que l'application fabrique sur un corps coupé
                # (un 400 de FastAPI, le plus souvent) est remplacée par le
                # 413 qui dit ce qui s'est passé.
                if not refus_envoye:
                    refus_envoye = True
                    await _413(send, depasse, plafond, mode="reçus")
                return
            if message.get("type") == "http.response.start":
                reponse_partie = True
            await send(message)

        try:
            await self.app(scope, compter, envoyer)
        except _CorpsTropGros:
            pass
        if depasse is not None and not refus_envoye and not reponse_partie:
            await _413(send, depasse, plafond, mode="reçus")


def _content_length(scope: dict) -> int | None:
    for cle, valeur in scope.get("headers") or ():
        if cle.lower() == b"content-length":
            try:
                return int(valeur)
            except ValueError:
                return None
    return None


async def _413(send: Send, mesure: int, plafond: int, *, mode: str) -> None:
    corps = json.dumps(
        {
            "erreur": {
                "code": "fichier_trop_gros",
                "message": f"{mesure} octets {mode} — cette route n'en prend pas plus de "
                f"{plafond}, la lecture est coupée à la borne",
                "service": None,
                "details": {},
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": corps})


__all__ = ["LimiteTailleCorps"]

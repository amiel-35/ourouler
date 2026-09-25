"""Intergiciel ASGI : refuse un corps trop gros **avant** qu'il touche le disque.

`_refuser_import_sur_la_taille_annoncee` et son jumeau pour les séances
(`api/routes.py`) ne lisent que l'en-tête `Content-Length` — un client qui
ment (ou qui envoie en `Transfer-Encoding: chunked`, sans `Content-Length`
du tout) les traverse sans être vu, et Starlette a déjà écrit le corps
multipart entier dans un fichier temporaire avant que la route ne s'exécute
et ne compte quoi que ce soit. C'est le trou que cet intergiciel ferme : il
compte les octets **au fil de l'eau**, avant que `self.app` (donc le
parseur multipart de Starlette, donc son écriture sur disque) n'en voie un
seul — dès que le total dépasse la borne de la route, il répond 413
lui-même et n'appelle jamais l'application.

Volontairement **pas** un `starlette.middleware.base.BaseHTTPMiddleware` :
il attend le corps entier avant de rendre la main à l'appelant, ce qui
charge en mémoire exactement ce qu'on veut éviter d'écrire sur disque. Ici,
ASGI brut — `receive()` enveloppé, rejoué à l'application une fois le total
vérifié en dessous de la borne.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping

Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]


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
        # octet quand le client l'annonce lui-même au-delà de la borne —
        # même geste que `_refuser_import_sur_la_taille_annoncee`, mais ici
        # posé une fois pour toute route bornée plutôt que réécrit par route.
        annonce = _content_length(scope)
        if annonce is not None and annonce > plafond:
            await _413(send, annonce, plafond, mode="annoncés")
            return

        # **Puis le flux réel** : `Content-Length` peut mentir, ou manquer
        # (`Transfer-Encoding: chunked`). On égrène les messages du corps
        # nous-mêmes, on compte, et on coupe dès que le total dépasse la
        # borne — avant que `self.app` (donc Starlette, donc son écriture
        # sur disque) n'en voie un octet de trop. Tout est gardé pour être
        # rejoué : c'est ce qui évite de charger le corps entier avant de le
        # transmettre, tout en restant capable de couper en cours de route.
        messages: list[dict] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                messages.append(message)
                break
            total += len(message.get("body") or b"")
            if total > plafond:
                await _413(send, total, plafond, mode="reçus")
                return
            messages.append(message)
            if not message.get("more_body", False):
                break

        file_dattente = list(messages)

        async def rejouer() -> dict:
            if file_dattente:
                return file_dattente.pop(0)
            return await receive()

        await self.app(scope, rejouer, send)


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
                f"{plafond}, la requête est coupée avant d'être écrite sur disque",
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

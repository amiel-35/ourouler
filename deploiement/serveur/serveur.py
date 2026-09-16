#!/usr/bin/env python3
"""Serveur statique du dossier des pages, derrière une authentification basique
(docs/heberge_minimal_contrat.md, périmètre point 2).

Volontairement `http.server` seul, sans framework : la page servie est déjà
autonome (Leaflet + GPX en base64 dedans, aucun appel serveur), rien ne
justifie un serveur d'application pour un point d'accès en lecture seule à un
dossier de fichiers.

Comme `deploiement/generateur/entrypoint.py`, ce script est hors de
`src/ourouler/` : il joue le rôle de point d'entrée (lit l'environnement) pour
le contrat de l'hébergé minimal, pas pour le cœur — la règle absolue 2 de
CLAUDE.md ne s'applique qu'à `src/ourouler/`.
"""

from __future__ import annotations

import base64
import hmac
import http.server
import os
import sys

DOSSIER = os.environ.get("OUROULER_DOSSIER_PAGES", "/data/pages")
PORT = int(os.environ.get("OUROULER_PORT", "8080"))
UTILISATEUR = os.environ.get("OUROULER_WWW_UTILISATEUR", "")
MOT_DE_PASSE = os.environ.get("OUROULER_WWW_MOT_DE_PASSE", "")

REALM = "ourouler"


def _en_tete_attendu(utilisateur: str, mot_de_passe: str) -> bytes:
    jeton = f"{utilisateur}:{mot_de_passe}".encode()
    return b"Basic " + base64.b64encode(jeton)


class GestionnaireAuthentifie(http.server.SimpleHTTPRequestHandler):
    """Sert `DOSSIER`, refuse tout ce qui n'a pas la bonne authentification basique.

    `hmac.compare_digest` plutôt que `==` : une comparaison à temps constant,
    pour ne pas laisser un minuscule canal temporel distinguer un préfixe
    correct d'un préfixe faux — peu probable à exploiter ici, mais ça ne
    coûte rien.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DOSSIER, **kwargs)

    def _authentifie(self) -> bool:
        recu = self.headers.get("Authorization", "")
        return hmac.compare_digest(
            recu.encode(), _en_tete_attendu(UTILISATEUR, MOT_DE_PASSE)
        )

    def _refuser(self) -> None:
        corps = b"401 Unauthorized\n"
        self.send_response(401)
        self.send_header("WWW-Authenticate", f'Basic realm="{REALM}"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):  # noqa: N802 - signature imposée par http.server
        if not self._authentifie():
            self._refuser()
            return
        super().do_GET()

    def do_HEAD(self):  # noqa: N802 - signature imposée par http.server
        if not self._authentifie():
            self._refuser()
            return
        super().do_HEAD()

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - signature imposée
        # Jamais l'en-tête Authorization (contient les identifiants en clair,
        # seulement encodés en base64) dans les logs.
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")


def main() -> None:
    if not UTILISATEUR or not MOT_DE_PASSE:
        raise SystemExit(
            "OUROULER_WWW_UTILISATEUR et OUROULER_WWW_MOT_DE_PASSE sont obligatoires "
            "(authentification basique) — voir deploiement/README.md"
        )
    os.makedirs(DOSSIER, exist_ok=True)
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), GestionnaireAuthentifie) as httpd:  # noqa: S104
        print(f"serveur statique sur :{PORT}, dossier {DOSSIER}", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()

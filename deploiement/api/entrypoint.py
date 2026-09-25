#!/usr/bin/env python3
"""Point d'entrée du conteneur qui sert l'API et le front.

Ce script est **hors** de `src/ourouler/` : ce n'est pas le cœur, c'est la
couche d'exploitation du paquetage, au même titre que `cli.py` pour l'usage
interactif et que `deploiement/generateur/entrypoint.py` pour le générateur
de la page du jour. Il a donc le droit de lire l'environnement — rien de tout
cela n'entre dans `src/ourouler/`, où la règle absolue 2 de CLAUDE.md continue
de s'appliquer sans exception ; le paquet `api/` n'a lui-même qu'une porte,
`api/exploitation.py`, que ce script ne contourne pas : il pose des variables,
il ne lit jamais la configuration à la place d'`exploitation.py`.

**La même contrainte que le générateur, et la même solution.** Coolify ne
propose aucun chemin d'hôte à monter : le fichier TOML (non-secrets — départ,
clé Intervals et identifiants BRouter restent des variables, lues par
`config.charger` via `api/exploitation.py`) arrive encodé en base64 dans
`OUROULER_CONFIG_TOML_B64`, et ce script l'écrit sur disque avant de démarrer
le serveur. Écrit en 0600 : il porte la masse, la FTP et les vélos du
cycliste — des données personnelles au sens de la règle absolue 1. Voir
`deploiement/generateur/entrypoint.py` pour le jumeau de cette fonction ;
elle n'est pas partagée entre les deux scripts parce que chacun reste un
paquetage indépendant, déployable et lisible sans l'autre.
"""

from __future__ import annotations

import base64
import os
import sys

#: Fichier de configuration TOML que l'API sert — même variable que
#: `api/exploitation.VARIABLE_CONFIG`, ce script ne fait qu'écrire ce que
#: cette variable-là désigne déjà.
CHEMIN_CONFIG = os.environ.get("OUROULER_CONFIG", "/config/config.toml")

#: Contenu du fichier TOML, encodé en base64 — voir la docstring de module.
CONFIG_TOML_B64 = os.environ.get("OUROULER_CONFIG_TOML_B64", "")

#: Le fichier des secrets **du service** — aujourd'hui le relais SMTP qui
#: porte les invitations. Distinct de `config.toml`, qui est le profil d'un
#: cycliste : celui-ci appartient au serveur et ne concerne personne en
#: particulier. Même chemin que celui que `cli.py` cherche par défaut, pour
#: que `ourouler inviter` le trouve sans rien lui dire.
CHEMIN_SERVICE = os.environ.get("OUROULER_SERVICE", "/config/service.toml")

#: Son contenu, encodé en base64, pour la même raison que le TOML de
#: configuration : Coolify ne propose aucun chemin d'hôte à monter.
SERVICE_TOML_B64 = os.environ.get("OUROULER_SERVICE_TOML_B64", "")

#: Adresse et port d'écoute du serveur, à l'intérieur du conteneur.
HOTE = os.environ.get("OUROULER_HOTE", "0.0.0.0")  # noqa: S104 — le conteneur, pas la machine hôte
PORT = int(os.environ.get("OUROULER_PORT", "8000"))


def _ecrire_config_depuis_environnement() -> None:
    """Matérialiser le TOML porté par `OUROULER_CONFIG_TOML_B64`, s'il y en a un.

    Ne fait rien quand la variable est absente : le fichier de test local
    (`docker-compose.yml`) peut aussi être monté directement, comme le
    conteneur générateur. Quand elle est là, elle gagne — un fichier monté
    **et** une variable serait une ambiguïté sans réponse juste.
    """
    if not CONFIG_TOML_B64:
        return
    try:
        contenu = base64.b64decode(CONFIG_TOML_B64, validate=True)
    except Exception as e:  # noqa: BLE001 - toute erreur de décodage se traite pareil
        raise SystemExit(
            f"OUROULER_CONFIG_TOML_B64 n'est pas du base64 valide ({e}) : "
            "encoder le fichier TOML avec `base64 -i config.toml`"
        ) from e
    os.makedirs(os.path.dirname(CHEMIN_CONFIG) or ".", exist_ok=True)
    # Ouverture explicite en 0600 plutôt qu'un chmod après coup : entre les
    # deux, le fichier existerait en lecture pour tout le conteneur.
    fd = os.open(CHEMIN_CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    print(f"config écrite depuis l'environnement : {CHEMIN_CONFIG}", flush=True)


def _ecrire_service_depuis_environnement() -> None:
    """Matérialiser le `service.toml` porté par `OUROULER_SERVICE_TOML_B64`.

    Le jumeau de la fonction du dessus, et pour un fichier plus sensible
    encore : il porte la clé SMTP du relais. Écrit en 0600, comme l'autre, et
    seulement quand la variable est là — un déploiement qui n'envoie pas de
    courriel n'a aucune raison de la poser, et `ourouler inviter` dira alors
    franchement que le fichier manque plutôt que de partir sans identifiants.

    **Pourquoi une variable plutôt qu'un fichier copié à la main.** Un
    premier essai du relais a été fait en copiant le fichier dans le
    conteneur avec `docker cp`, puis en l'effaçant. Ça marche une fois ; ça ne
    survit pas à un déploiement, et ça ne se raconte pas à quelqu'un d'autre.
    """
    if not SERVICE_TOML_B64:
        return
    try:
        contenu = base64.b64decode(SERVICE_TOML_B64, validate=True)
    except Exception as e:  # noqa: BLE001 - toute erreur de décodage se traite pareil
        raise SystemExit(
            f"OUROULER_SERVICE_TOML_B64 n'est pas du base64 valide ({e}) : "
            "encoder le fichier avec `base64 -i service.toml`"
        ) from e
    os.makedirs(os.path.dirname(CHEMIN_SERVICE) or ".", exist_ok=True)
    fd = os.open(CHEMIN_SERVICE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(contenu)
    # Le chemin, jamais le contenu : ce fichier porte une clé SMTP.
    print(f"secrets du service écrits depuis l'environnement : {CHEMIN_SERVICE}", flush=True)


def main() -> None:
    _ecrire_config_depuis_environnement()
    _ecrire_service_depuis_environnement()

    try:
        import uvicorn

        from ourouler.api.application import application
    except ImportError as e:
        print(
            f"api : FastAPI et uvicorn ne sont pas installés dans cette image ({e})",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

    # `application()` lit `OUROULER_MODE`, `OUROULER_CONFIG` et
    # `OUROULER_FRONT_DIST` par `api/exploitation.py` — rien de tout cela
    # n'est relu ici. Construite une seule fois : une erreur de configuration
    # (TOML invalide, `OUROULER_MODE` inconnu) doit faire échouer le
    # démarrage, pas une requête au hasard.
    app = application()
    print(f"ourouler : API et front sur http://{HOTE}:{PORT} (sonde : /sante)", file=sys.stderr)
    uvicorn.run(app, host=HOTE, port=PORT, log_level="info")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Point d'entrée du conteneur qui sert l'API et le front.

Ce script est **hors** de `src/ourouler/` : ce n'est pas le cœur, c'est la
couche d'exploitation du paquetage, au même titre que `cli/` pour l'usage
interactif. Il a donc le droit de lire l'environnement — rien de tout
cela n'entre dans `src/ourouler/`, où « le cœur ne lit ni configuration ni environnement »
continue de s'appliquer sans exception ; le paquet `api/` n'a lui-même qu'une porte,
`api/exploitation.py`, que ce script ne contourne pas : il pose des variables,
il ne lit jamais la configuration à la place d'`exploitation.py`.

Coolify ne propose aucun chemin d'hôte à monter : le fichier TOML
(non-secrets — départ, clé Intervals et identifiants BRouter restent des
variables, lues par `config.charger` via `api/exploitation.py`) arrive
encodé en base64 dans `OUROULER_CONFIG_TOML_B64`, et ce script l'écrit sur
disque avant de démarrer le serveur. Écrit en 0600 : il porte la masse, la
FTP et les vélos du cycliste — des données personnelles (aucune donnée
personnelle dans le dépôt).
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import threading

#: Fichier de configuration TOML que l'API sert — même variable que
#: `api/exploitation.VARIABLE_CONFIG`, ce script ne fait qu'écrire ce que
#: cette variable-là désigne déjà.
CHEMIN_CONFIG = os.environ.get("OUROULER_CONFIG", "/config/config.toml")

#: Contenu du fichier TOML, encodé en base64 — voir la docstring de module.
CONFIG_TOML_B64 = os.environ.get("OUROULER_CONFIG_TOML_B64", "")

#: Le fichier des secrets **du service** — aujourd'hui le relais SMTP qui
#: porte les invitations. Distinct de `config.toml`, qui est le profil d'un
#: cycliste : celui-ci appartient au serveur et ne concerne personne en
#: particulier. Même chemin que celui que `cli/` cherche par défaut, pour
#: que `ourouler inviter` le trouve sans rien lui dire.
CHEMIN_SERVICE = os.environ.get("OUROULER_SERVICE", "/config/service.toml")

#: Son contenu, encodé en base64, pour la même raison que le TOML de
#: configuration : Coolify ne propose aucun chemin d'hôte à monter.
SERVICE_TOML_B64 = os.environ.get("OUROULER_SERVICE_TOML_B64", "")

#: Adresse et port d'écoute du serveur, à l'intérieur du conteneur.
HOTE = os.environ.get("OUROULER_HOTE", "0.0.0.0")  # le conteneur, pas la machine hôte
PORT = int(os.environ.get("OUROULER_PORT", "8000"))


def _configurer_journalisation() -> None:
    """Rend visibles les journaux Python du projet (`ourouler.*`) dans `docker logs`.

    Constaté en préproduction le 28/09/2026 : aucune ligne de `ourouler.admin`
    (connexions, demandes acceptées/refusées, comptes supprimés) ni de
    `ourouler.demandes`/`ourouler.api…` n'apparaissait dans les journaux du
    conteneur — seules les lignes d'accès d'uvicorn y étaient. Uvicorn
    configure ses propres journaux (`uvicorn`, `uvicorn.error`,
    `uvicorn.access`) via `disable_existing_loggers=False` : il ne touche pas
    aux loggers d'un autre nom, il suffit de poser un gestionnaire sur le
    logger racine du projet avant que quoi que ce soit ne journalise —
    l'administration tourne dans un fil du même processus (voir
    `_lancer_administration_en_arriere_plan`), donc son logger
    `ourouler.admin`, enfant de celui-ci, en hérite sans rien de plus.

    Ne touche ni la configuration d'uvicorn (posée séparément, par
    `uvicorn.Config`/`uvicorn.run`) ni `ourouler api` en local : ce script est
    le point d'entrée du conteneur, jamais importé par `cli/api.py`.
    """
    journal = logging.getLogger("ourouler")
    journal.setLevel(logging.INFO)
    gestionnaire = logging.StreamHandler(sys.stderr)
    gestionnaire.setFormatter(logging.Formatter("%(levelname)s %(name)s : %(message)s"))
    journal.addHandler(gestionnaire)
    journal.propagate = False


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
    except Exception as e:  # toute erreur de décodage se traite pareil
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
    except Exception as e:  # toute erreur de décodage se traite pareil
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


def _appliquer_migrations() -> None:
    """Met la base des comptes au schéma de ce code, **avant** de servir quoi que ce soit.

    Sans cela, une route qui arrive avec une migration (demandes
    d'invitation, choix de conservation) répond 500 sur une table absente
    tant que personne n'a lancé une commande de comptes (`ourouler inviter`,
    `ourouler admin`) dans le conteneur — constaté en préproduction le
    28/09/2026. `appliquer_migrations` se rejoue sans effet quand tout est
    déjà posé. Sans `OUROULER_DATABASE_URL`, pas de base, rien à faire.
    """
    from ourouler.api import exploitation

    url_db = exploitation.url_base_de_donnees()
    if not url_db:
        return
    from ourouler.api.base_de_donnees import appliquer_migrations, ouvrir

    with ouvrir(url_db) as connexion:
        posees = appliquer_migrations(connexion)
    if posees:
        noms = ", ".join(posees)
        print(f"base des comptes : {len(posees)} migration(s) appliquée(s) : {noms}", file=sys.stderr)


def _lancer_administration_en_arriere_plan(app) -> None:
    """Démarre l'administration dans un **fil du même processus**, si `[admin]` est posée.

    Sprint 12 : « l'entrypoint lance aussi `ourouler admin` en arrière-plan
    quand la clé admin est présente dans `service.toml`, sinon rien. »

    **Même processus, pas un sous-processus** — c'est le choix qui rend les
    écrans « tâches de fond » et « quotas du jour » de l'administration
    réellement vivants : ils lisent l'état de *ce* processus API
    (`api.taches_fond.occupant()`, les compteurs de `app.state.ourouler`),
    ce qu'un `ourouler admin` lancé à part (un second processus, pour un
    accès manuel — voir `deploiement/api/README.md`) ne peut pas voir. Un
    second `uvicorn.Server` dans un fil `daemon` partage l'interpréteur, donc
    ces objets, sans rien recopier.

    N'écoute **que** sur `127.0.0.1` — jamais posé dans `expose`/Traefik du
    compose Coolify (`docker-compose.api.coolify.yml`) : c'est le point même
    de QP6, pas une conséquence accessoire de ce choix.
    """
    from ourouler.api import exploitation
    from ourouler.api.admin import ParametresApplicationAdmin, creer_application_admin

    identifiant = exploitation.parametres_admin()
    if identifiant is None:
        print(
            "ourouler : [admin] absente de service.toml — administration non démarrée",
            file=sys.stderr,
        )
        return

    url_db = exploitation.url_base_de_donnees()
    url_pub = os.environ.get("OUROULER_URL_PUBLIQUE", "").strip()
    if not url_db or not url_pub:
        print(
            "ourouler : [admin] posée mais OUROULER_DATABASE_URL ou OUROULER_URL_PUBLIQUE "
            "absente — administration non démarrée",
            file=sys.stderr,
        )
        return

    # RGPD, minimisation : purge les demandes non traitées depuis plus de
    # 30 jours au démarrage — la même purge tourne aussi à chaque ouverture
    # de la file par l'administration (`DepotDemandes.en_attente`), mais un
    # conteneur qui redémarre souvent sans qu'on ouvre l'écran ne doit pas
    # non plus les garder indéfiniment.
    from ourouler.api import base_de_donnees
    from ourouler.api.demandes import DepotDemandes
    from ourouler.services.demandes import purger_demandes_perimees

    with base_de_donnees.ouvrir(url_db) as connexion:
        purger_demandes_perimees(depot=DepotDemandes(connexion))

    ctx = app.state.ourouler
    quotas = {
        "générations": ctx.quotas,
        "consultations météo": ctx.quotas_meteo,
        "calibrations": ctx.quotas_calibration,
        "imports": ctx.quotas_import,
    }
    admin_app = creer_application_admin(
        ParametresApplicationAdmin(
            url_comptes=url_db,
            identifiant=identifiant,
            url_publique=url_pub,
            parametres_brevo=exploitation.parametres_brevo_service(),
            quotas=quotas,
        )
    )
    port = exploitation.port_admin()

    import uvicorn

    configuration = uvicorn.Config(admin_app, host="127.0.0.1", port=port, log_level="info")
    serveur = uvicorn.Server(configuration)
    fil = threading.Thread(target=serveur.run, name="admin", daemon=True)
    fil.start()
    print(
        f"ourouler : administration sur http://127.0.0.1:{port}/admin/ (boucle locale uniquement)",
        file=sys.stderr,
    )


def main() -> None:
    _configurer_journalisation()
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
    _appliquer_migrations()
    # L'administration est un accessoire : sa panne au démarrage ne doit
    # jamais emporter l'API publique (constaté en préproduction le
    # 28/09/2026 : une table absente faisait redémarrer le conteneur en boucle).
    try:
        _lancer_administration_en_arriere_plan(app)
    except Exception as e:  # tout échec de l'admin est journalisé, l'API démarre
        print(f"ourouler : administration non démarrée ({type(e).__name__}: {e})", file=sys.stderr)
    print(f"ourouler : API et front sur http://{HOTE}:{PORT} (sonde : /sante)", file=sys.stderr)
    # `proxy_headers=True, forwarded_allow_ips="*"` : sans ça, uvicorn n'honore
    # `X-Forwarded-For` que depuis 127.0.0.1, et `Request.client.host` (lu par
    # `api/routes/demandes.py` pour le débit par adresse IP du formulaire
    # public) voit alors l'IP de Traefik pour **toutes** les requêtes — cinq
    # dépôts de n'importe qui épuiseraient le compteur pour tout le monde.
    # `forwarded_allow_ips="*"` (« fais confiance à qui se connecte ») est sûr
    # ici précisément parce que ce conteneur n'est joignable que par le réseau
    # interne de Traefik : aucun port n'est publié sur l'hôte
    # (`docker-compose.api.coolify.yml`, `expose:` seulement), donc personne
    # d'autre que Traefik ne peut se connecter directement et forger cet
    # en-tête. Sans ce réglage-ci ni ce conteneur-là (`ourouler api` en local,
    # `HOTE` par défaut `127.0.0.1`), ce paramètre ne change rien puisque
    # personne ne se connecte par un proxy.
    uvicorn.run(app, host=HOTE, port=PORT, log_level="info", proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()

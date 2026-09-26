# L'API et le front — paquetage

Le front (`front/`) et l'API (`src/ourouler/api/`) packagés pour tourner
sur un serveur. **Rien n'est déployé ici** : `docker compose` sur cette
machine sert à vérifier le paquet, pas à le mettre en ligne — la mise en
ligne est un geste séparé, fait par qui exploite le serveur (voir
`AGENTS.md`).

## Comment le front et l'API se joignent, et pourquoi

**Un seul conteneur, une seule origine.** `deploiement/api/Dockerfile`
construit le front (`npm run build`) dans un premier étage, et le copie dans
le second, celui qui sert l'API : au démarrage, `uvicorn` sert `/api/v1/...`
et, dessous, le contenu de `front/dist` à la racine (`/`).

Ce n'est pas un choix arbitraire, c'est celui que le front écrit déjà
(`front/vite.config.ts`, `front/README.md`) : *« la même
construction sert en production, où l'API et le front sont servis par la
même origine »*. Le code du front n'a **jamais** d'URL absolue
(`front/src/api/client.ts` : `RACINE = "/api/v1"`, toujours un chemin
relatif) — c'est ce qui rend ce choix possible sans rien changer côté front,
et c'est pour ça qu'il a été retenu plutôt que deux services (front statique
+ API) derrière un proxy : un proxy de plus est un composant de plus à
déployer, configurer et faire tomber, pour reproduire exactement ce que le
front sait déjà faire tout seul contre une origine partagée.

Concrètement (`src/ourouler/api/application.py`) : `creer_application(...,
dossier_front=...)` monte `StaticFiles(dossier_front, html=True)` sur `/`,
**après** les routes de l'API — un gabarit `/api/v1/...` (ou `/sante`, voir
plus bas) reste toujours prioritaire sur ce que le front pourrait servir au
même chemin. `application()`, la fabrique que le conteneur lance, lit ce
dossier dans `OUROULER_FRONT_DIST` (`api/exploitation.py`), que le
`Dockerfile` pose vers où il a copié `front/dist`.

## Préparer

1. **Le fichier TOML non-secrets.** Copier
   `deploiement/api/config.example.toml`, le renseigner (masse, FTP, vélos,
   météo...). **Jamais** `[depart]`, `[intervals]`, ni `[brouter].url` /
   `.utilisateur` / `.mot_de_passe` dedans — ces valeurs viennent
   exclusivement de variables d'environnement, listées ci-dessous. C'est la
   même contrainte, pour la même raison, que `deploiement/config.example.toml`
   (le générateur de la page du jour) : voir sa docstring si le pourquoi
   intéresse.

   **`[cycliste]` et `[[velos]]`, eux, ne valent qu'en mode `personnel`** :
   ce sont des réglages personnels, jamais hérités d'un socle partagé. En
   mode `heberge`, ces deux sections aussi
   doivent disparaître de ce fichier : l'API **refuse de démarrer** si
   `[depart]`, `[cycliste]`, `[[velos]]` ou `[intervals]` y figurent — elles
   seraient sinon servies à chaque personne invitée. Chaque cycliste les
   renseigne lui-même depuis l'assistant, une fois son compte activé.

2. **Les secrets, le point de départ, et le mode.**
   ```
   cp deploiement/api/.env.example deploiement/api/.env
   ```
   Renseigner dans `deploiement/api/.env` :
   - `OUROULER_MODE` — `personnel` (un seul cycliste, celui qui héberge) ou
     `heberge` (plusieurs cyclistes, chacun avec son compte). En `heberge`,
     les comptes et les sessions par cookie n'existent que si
     `OUROULER_DATABASE_URL` désigne une base PostgreSQL ; sans elle, aucune
     session ne s'ouvre et toute route de données répond 401
     (`api/exploitation.fournisseur_session`, `src/ourouler/api/session.py`).
     C'est le cas de ce compose local, qui ne transmet pas
     `OUROULER_DATABASE_URL`. **Sans `OUROULER_MODE`, le compose pose
     `heberge`, et le service démarre et refuse tout** : ce n'est pas un bug
     du paquetage, c'est le comportement voulu : un service exposé sans
     qu'on ait dit qui il sert ne sert personne.
   - `OUROULER_INTERVALS_API_KEY`, `OUROULER_INTERVALS_ATHLETE_ID`,
     `OUROULER_DEPART_NOM`, `OUROULER_DEPART_LATITUDE`,
     `OUROULER_DEPART_LONGITUDE` — **uniquement en mode `personnel`**
     (Intervals.icu → Settings → Developer, pour les deux premières). **En
     mode `heberge`, laisser ces cinq variables vides** : l'API les ignore
     (elles ne s'appliquent jamais à un socle partagé) et refuse même de
     démarrer si l'une d'elles porte une valeur — poser un point de départ
     ou une clé au niveau du serveur imposerait ceux de l'hébergeur à chaque
     personne invitée.
   - `OUROULER_BROUTER_URL` (et `OUROULER_BROUTER_UTILISATEUR` /
     `OUROULER_BROUTER_MOT_DE_PASSE` si protégé) — un serveur BRouter déjà en
     service ; c'est un réglage serveur, légitime dans les deux modes.
   - `OUROULER_CONFIG_HOTE` — chemin **absolu** vers le fichier TOML préparé
     à l'étape 1.

   `deploiement/api/.env` n'est jamais commité (`.gitignore` couvre déjà
   `.env` et `.env.*`, avec une exception nommée pour `.env.example`).

## Lancer, en local, pour vérifier

Depuis la racine du dépôt :

```
docker compose -f deploiement/api/docker-compose.yml --env-file deploiement/api/.env up --build
```

Le service écoute sur `OUROULER_PORT_HOTE` (8000 par défaut) :

```
curl http://localhost:8000/sante
curl http://localhost:8000/api/v1/systeme          # 401 sans OUROULER_MODE
# avec OUROULER_MODE=personnel dans deploiement/api/.env : 200
open http://localhost:8000/                        # le front, servi par le même conteneur
```

Arrêter : `docker compose -f deploiement/api/docker-compose.yml down`
(ajouter `-v` pour aussi supprimer le volume `donnees` et repartir de zéro).

## La sonde de santé

`GET /sante` répond `{"etat": "ok", "version": "…"}`, **sans jamais ouvrir de
session** — c'est le point : `GET /api/v1/systeme` en est une (elle sert des
données de cycliste, la doctrine du contrat l'exige), donc elle répond 401
tant qu'aucune session n'est ouverte, et un orchestrateur qui l'interrogerait
comme sonde croirait le service mort sur tout déploiement `heberge` tant
que personne n'y est connecté. `/sante` est
volontairement hors de `/api/v1` et hors du schéma publié
(`/openapi.json`) : ce n'est pas une promesse faite à un cycliste, c'est une
question posée par l'infrastructure. Le `Dockerfile` la pose en
`HEALTHCHECK` ; Coolify peut l'utiliser de la même façon.

## Gérer les comptes depuis la ligne de commande (exploitant)

En mode `heberge`, les comptes se gèrent **exclusivement** en ligne de
commande, par l'exploitant du serveur — jamais par une route HTTP
ouverte à qui que ce soit d'autre (`src/ourouler/api/comptes.py`). Les
quatre commandes lisent `OUROULER_DATABASE_URL` (l'URL de la base
PostgreSQL de comptes, appliquant ses migrations au passage si besoin) ;
`inviter`, `invitations` et `reinitialiser` lisent aussi
`OUROULER_URL_PUBLIQUE` (l'URL publique du front hébergé, devant laquelle
`/entrer` et `/reinitialiser` s'ouvrent) ; `retirer` lit en plus
`OUROULER_CONFIG` et le volume de données du serveur. **Elles se lancent
dans le conteneur du serveur** (`docker exec`), où
`docker-compose.api.coolify.yml` a déjà posé ces variables — c'est même
obligatoire pour `retirer`, qui efface les fichiers du propriétaire sur le
disque de la machine où il tourne (mode d'emploi : `docs/inviter.md`).
`--sans-courriel` affiche seulement le lien à la place d'envoyer un
courriel, ce qui évite de charger `service.toml` (les secrets Brevo).

- **`ourouler inviter ADRESSE`** — crée un compte inactif et une invitation ;
  émet le lien `/entrer?jeton=...`, à usage unique, valable trois jours. Un
  compte déjà actif est refusé (« il a déjà un compte »).
- **`ourouler invitations`** — liste les invitations en cours, avec leur
  lien et leur échéance — pour relire ou renvoyer un lien déjà émis sans le
  régénérer.
- **`ourouler reinitialiser ADRESSE`** — le pendant d'`inviter`
  pour un compte **déjà actif** qui a perdu son mot de passe : émet un lien
  `/reinitialiser?jeton=...`, même mécanisme de jeton à usage unique. Rien
  n'est changé tant que le lien n'est pas ouvert et le formulaire soumis ;
  à ce moment-là, **toutes les sessions déjà ouvertes de ce compte sont
  fermées** — quiconque était connecté doit se reconnecter avec le nouveau
  mot de passe.
- **`ourouler retirer ADRESSE`** — ferme le compte (mot de
  passe, sessions, invitation) et efface ses données personnelles, par le
  même chemin que le bouton « Supprimer mon compte » du front
  (`DELETE /moi`, `api/vie_privee.effacer_donnees`) — jamais une
  réimplémentation séparée. Demande confirmation (adresse affichée en
  toutes lettres) avant d'agir ; `--oui` s'en passe, pour un script. Les
  routes apprises des sorties de ce compte ne sont **pas** effacées : elles
  restent collectives (doctrine du projet, §10.2).

**Pas de « mot de passe oublié » en libre-service, et c'est volontaire.**
Aucune route HTTP n'accepte une adresse seule pour déclencher l'envoi d'un
lien de réinitialisation : ouvrir un tel geste à n'importe qui ferait de ce
serveur un relais de spam (poster une adresse au hasard suffirait à lui
faire envoyer un courriel) et un oracle d'énumération d'adresses (la
réponse dirait si l'adresse a un compte chez ourouler, comme
`ErreurCompteExistant` le documente déjà pour `inviter`). `reinitialiser`
reste donc un geste de l'exploitant, en ligne de commande — comme
`inviter`.

## Les variables d'environnement

La table complète, vérifiée contre le code : chaque variable, qui la lit, et
ce qu'elle vaut quand elle est absente. En dehors de `deploiement/`, seuls
`src/ourouler/cli.py`, `src/ourouler/config.py` et
`src/ourouler/api/exploitation.py` lisent l'environnement
(`tests/test_invariants.py`). Une variable **vide** vaut une variable
absente partout où c'est précisé, parce que Coolify transmet vides les
variables déclarées sans valeur.

**Le service (API et front)**

| Variable | Lue par | Absente | Rôle |
|---|---|---|---|
| `OUROULER_MODE` | `api/exploitation.fournisseur_session` | `heberge` | `personnel` ou `heberge` ; toute autre valeur refuse le démarrage |
| `OUROULER_DATABASE_URL` | `api/exploitation.url_base_de_donnees` (serveur et commandes de comptes) | pas de base : en `heberge`, aucune session, tout répond 401 ; les commandes de comptes refusent | URL PostgreSQL des comptes, invitations et sessions ; vide vaut absente |
| `OUROULER_CONFIG` | `api/exploitation.chemin_config` (serveur, et `ourouler` quand `--config` est absent) ; `deploiement/api/entrypoint.py` | `~/.config/ourouler/config.toml` ; `/config/config.toml` dans l'image | le fichier TOML servi |
| `OUROULER_CONFIG_TOML_B64` | `deploiement/api/entrypoint.py` | rien n'est écrit | le TOML encodé en base64, écrit à `OUROULER_CONFIG` avant le démarrage |
| `OUROULER_SERVICE` | `api/exploitation.chemin_service`, `cli.py` (`_charger_service`) ; `deploiement/api/entrypoint.py` | `~/.config/ourouler/service.toml` ; `/config/service.toml` dans l'image | le fichier des réglages du service : relais SMTP `[brevo]`, `[quotas]` |
| `OUROULER_SERVICE_TOML_B64` | `deploiement/api/entrypoint.py` | rien n'est écrit | `service.toml` encodé en base64, écrit à `OUROULER_SERVICE` |
| `OUROULER_URL_PUBLIQUE` | `cli.py` (`_url_publique`) : `inviter`, `invitations`, `reinitialiser` | la commande refuse | l'URL publique du front, devant laquelle `/entrer?jeton=…` s'ouvre ; vide vaut absente |
| `OUROULER_API_CHEMIN` | `api/exploitation.chemin_api` | `ancien` | `ancien`, `nouveau` ou `double` : par quel chemin l'API appelle le cœur (`ARCHITECTURE.md` §4) ; toute autre valeur refuse le démarrage |
| `OUROULER_FRONT_DIST` | `api/exploitation.dossier_front` | l'API ne sert que `/api/v1` | le dossier du front construit ; l'image la pose à `/app/front/dist` (`deploiement/api/Dockerfile`) |
| `OUROULER_HOTE` | `deploiement/api/entrypoint.py` | `0.0.0.0` | l'adresse d'écoute d'uvicorn dans le conteneur |
| `OUROULER_PORT` | `deploiement/api/entrypoint.py` | `8000` | le port d'écoute d'uvicorn dans le conteneur |
| `OUROULER_BROUTER_URL`, `OUROULER_BROUTER_UTILISATEUR`, `OUROULER_BROUTER_MOT_DE_PASSE` | `config.py` (`_survoler_environnement`) | le TOML fait foi | le serveur BRouter ; légitimes dans les deux modes ; vide vaut absente |
| `OUROULER_DEPART_NOM`, `OUROULER_DEPART_LATITUDE`, `OUROULER_DEPART_LONGITUDE`, `OUROULER_INTERVALS_API_KEY`, `OUROULER_INTERVALS_ATHLETE_ID` | `config.py` (`_survoler_environnement`) | le TOML fait foi | le départ et la clé Intervals, **en `personnel` seulement** : en `heberge`, une valeur posée refuse le démarrage (`api/depots.py`, `VARIABLES_PERSO_PUR`) ; vide vaut absente |
| `TZ` | aucun module d'ourouler : le fuseau du processus | UTC dans le conteneur | l'heure locale lue par le cœur (`date.today()`, heure de départ sans fuseau) ; `docker-compose.api.coolify.yml` pose `Europe/Paris` |

**La page du jour** (`deploiement/generateur/entrypoint.py`,
`deploiement/serveur/serveur.py`, voir `deploiement/README.md`)

| Variable | Lue par | Absente | Rôle |
|---|---|---|---|
| `OUROULER_CONFIG`, `OUROULER_CONFIG_TOML_B64` | générateur | `/config/config.toml` ; rien n'est écrit | comme ci-dessus |
| `OUROULER_DOSSIER_PAGES` | générateur, serveur statique | `/data/pages` | où la page est écrite, puis servie |
| `OUROULER_HEURE_GENERATION` | générateur | `06:00` | l'heure quotidienne de génération, `HH:MM` |
| `OUROULER_PORT` | serveur statique | `8080` | le port d'écoute |
| `OUROULER_WWW_UTILISATEUR`, `OUROULER_WWW_MOT_DE_PASSE` | serveur statique | le serveur refuse de démarrer | l'authentification basique devant la page |

**Hors du code**

- `OUROULER_CONFIG_HOTE` et `OUROULER_PORT_HOTE` ne sont lues par aucun
  programme : `docker compose` les substitue dans
  `deploiement/api/docker-compose.yml` et `deploiement/docker-compose.yml`
  (chemin du TOML sur la machine hôte, port publié).
- `OUROULER_API` est lue par le serveur de développement du front
  (`front/vite.config.ts`) : la cible du proxy `/api`, par défaut
  `http://127.0.0.1:8000`.

## Les pièges Coolify (deux hérités du générateur, deux mesurés ici)

Les deux s'appliquent ici à l'identique — voir `docker-compose.coolify.yml`
(racine du dépôt) pour la mesure d'origine, et
`docker-compose.api.coolify.yml` (racine aussi) pour ce paquetage-ci :

1. **Coolify ne résout pas `context:` relativement au fichier compose.** Un
   fichier compose dans `deploiement/` avec `context: ..` échoue sur `lstat
   /artifacts/deploiement: no such file or directory`. C'est pourquoi
   `docker-compose.api.coolify.yml` vit **à la racine** du dépôt, avec
   `context: .` et `dockerfile: deploiement/api/Dockerfile`.
2. **Coolify prend le message d'un `${VAR:?message}` pour une valeur par
   défaut**, au lieu de refuser comme le ferait `docker compose` en local.
   `docker-compose.api.coolify.yml` n'en pose donc aucun : les variables
   sans défaut y sont écrites `${VAR}` seul, ce qui laisse la variable vide
   plutôt que de fabriquer une valeur fausse — `config.charger` (pour le
   TOML) ou `api/exploitation.fournisseur_session` (pour `OUROULER_MODE`)
   échouent ou refusent alors franchement au démarrage.

Et deux de plus, mesurés sur le premier déploiement réel de
ce paquetage-ci — tous deux dans le **même bloc `environment:`**, et tous
deux invisibles en local :

3. **Les deux formes d'`environment:` ne se mélangent pas.** Une liste
   (`- CLE=valeur`) et un dictionnaire (`CLE: valeur`) dans le même bloc
   font un YAML invalide, et le déploiement échoue sur « did not find
   expected `'-'` indicator » sans nommer le bloc fautif.
4. **La variable magique ne se reconnaît qu'en déclaration nue.** Écrite
   `SERVICE_FQDN_API_8000: ${SERVICE_FQDN_API_8000:-}` — c'est-à-dire en
   dictionnaire, avec une valeur — elle devient une variable ordinaire :
   Coolify ne pose pas les étiquettes Traefik du service. Le conteneur
   démarre, la sonde le déclare sain, `docker ps` ne montre rien d'anormal,
   et le domaine répond `503 no available server`. La forme reconnue est
   `- SERVICE_FQDN_API_8000`, **sans valeur**. Comme le piège 3 interdit de
   mélanger, tout le bloc est donc en liste.

Ce que Coolify a par ailleurs montré au passage : **il transmet au conteneur
toutes les variables déclarées, vides comprises.** `OUROULER_DEPART_LATITUDE`
non renseignée arrive dans le conteneur comme chaîne vide, pas comme
variable absente. C'est ce qui a fait échouer le premier démarrage
(`[depart] latitude : nombre attendu, reçu ''`), et ce que
`config.py:_reporter` traite désormais : **vide vaut absente**, une variable
que personne n'a remplie n'écrase plus le TOML.

## Ce que ce dossier ne fait pas

Il ne touche à aucun serveur et ne lit aucun jeton d'hébergeur. Il ne touche pas non plus
au déploiement existant du générateur de la page du jour
(`deploiement/Dockerfile`, `deploiement/docker-compose.yml`,
`docker-compose.coolify.yml`) : ce paquetage-ci est un service distinct, avec
son propre `Dockerfile`, son propre compose, sa propre variable
`SERVICE_FQDN_*`.

## Déployer sur Coolify

1. Créer un nouveau service sur Coolify (pas celui de la page du jour),
   pointé sur ce dépôt, fichier compose `docker-compose.api.coolify.yml`.
2. Poser les variables listées ci-dessus dans l'interface Coolify —
   `OUROULER_CONFIG_TOML_B64` (le TOML de l'étape 1, encodé :
   `base64 -i config.toml`, ou `base64 -i deploiement/api/config.example.toml`
   pour un premier essai à blanc) et `OUROULER_MODE` en premier.
3. Choisir le nom du service dans le compose (`api` ici) : c'est lui qui
   détermine le nom exact de `SERVICE_FQDN_API_8000` que Coolify attend.
4. Décider s'il faut un volume persistant pour `/data/cache` (le cache
   d'activités et de météo) ou si un volume éphémère suffit pour ce premier
   déploiement — les deux options existent déjà dans le compose
   (`volumes: donnees:`), le choix de le rendre persistant ou non sur
   Coolify reste à l'exploitant.
5. Lancer le déploiement depuis l'interface Coolify, puis vérifier
   `https://<le domaine attribué>/sante` avant toute chose.

**Un premier essai à blanc** (par exemple sur `https://ourouler.exemple.org`)
prouve la chaîne sans rien exposer : `/sante` donne `{"etat":"ok"}`, `/` sert
le front, `/api/v1/...` refuse tout en 401 `session_absente` sans session
ouverte. Avec `config.example.toml` tel quel et un point de départ
générique, aucune donnée personnelle n'est sur le serveur, ni clé
Intervals, ni identifiants BRouter.

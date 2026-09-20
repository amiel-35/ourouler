# L'API et le front — paquetage, lot L7.E

Le front (`front/`) et l'API (`src/ourouler/api/`) packagés pour tourner
ailleurs que sur le Mac du mainteneur. **Rien n'est déployé ici** : `docker
compose` sur cette machine sert à vérifier le paquet, pas à le mettre en
ligne (règle absolue 7 de CLAUDE.md — le geste de déploiement sur Coolify
reste au mainteneur, soumis séparément, et ce dossier ne le fait pas à sa
place).

## Comment le front et l'API se joignent, et pourquoi

**Un seul conteneur, une seule origine.** `deploiement/api/Dockerfile`
construit le front (`npm run build`) dans un premier étage, et le copie dans
le second, celui qui sert l'API : au démarrage, `uvicorn` sert `/api/v1/...`
et, dessous, le contenu de `front/dist` à la racine (`/`).

Ce n'est pas un choix arbitraire, c'est celui que le front avait déjà écrit
avant ce lot (`front/vite.config.ts`, `front/README.md`) : *« la même
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

2. **Les secrets, le point de départ, et le mode.**
   ```
   cp deploiement/api/.env.example deploiement/api/.env
   ```
   Renseigner dans `deploiement/api/.env` :
   - `OUROULER_MODE` — `personnel` (un seul cycliste, le mainteneur) ou
     `heberge` (plusieurs cyclistes ; comme aucune méthode de connexion
     n'est branchée, toute route de données répond 401 — voir
     `src/ourouler/api/session.py`). **Sans cette variable, le service
     démarre et refuse tout** : ce n'est pas un bug du paquetage, c'est le
     comportement voulu depuis le lot L7.A — un service exposé sans qu'on
     ait dit qui il sert ne sert personne.
   - `OUROULER_INTERVALS_API_KEY`, `OUROULER_INTERVALS_ATHLETE_ID` —
     Intervals.icu → Settings → Developer.
   - `OUROULER_DEPART_NOM`, `OUROULER_DEPART_LATITUDE`,
     `OUROULER_DEPART_LONGITUDE`.
   - `OUROULER_BROUTER_URL` (et `OUROULER_BROUTER_UTILISATEUR` /
     `OUROULER_BROUTER_MOT_DE_PASSE` si protégé) — celui déjà en service sur
     le Coolify du mainteneur.
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
comme sonde croirait le service mort sur tout déploiement `heberge` sans
authentification branchée — c'est-à-dire tous, pour l'instant. `/sante` est
volontairement hors de `/api/v1` et hors du schéma publié
(`/openapi.json`) : ce n'est pas une promesse faite à un cycliste, c'est une
question posée par l'infrastructure. Le `Dockerfile` la pose en
`HEALTHCHECK` ; Coolify peut l'utiliser de la même façon.

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

Et deux de plus, mesurés le 18/09/2026 sur le premier déploiement réel de
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

## Ce que ce lot ne fait pas

Il ne touche à rien sur le Coolify du mainteneur, ne lit aucun jeton dans
`~/.config/coolify`, et ne décide pas de la méthode d'authentification (hors
périmètre du sprint 7, `docs/sprint7_contrat.md`). Il ne touche pas non plus
au déploiement existant du générateur de la page du jour
(`deploiement/Dockerfile`, `deploiement/docker-compose.yml`,
`docker-compose.coolify.yml`) : ce paquetage-ci est un service distinct, avec
son propre `Dockerfile`, son propre compose, sa propre variable
`SERVICE_FQDN_*`.

## Ce qu'il reste à faire au mainteneur pour déployer

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
   Coolify reste au mainteneur.
5. Lancer le déploiement depuis l'interface Coolify, puis vérifier
   `https://<le domaine attribué>/sante` avant toute chose.

**Fait le 18/09/2026** : l'application s'appelle `ourouler-api` sur le
Coolify du mainteneur, elle suit la branche d'intégration du sprint en
cours, et elle répond sur **https://app-ourouler.inflexion.me** — `/sante`
donne `{"etat":"ok"}`, `/` sert le front, `/api/v1/...` refuse tout en 401
`session_absente` puisque `OUROULER_MODE=heberge` et qu'aucune méthode de
connexion n'est branchée (lot L7.2). Le TOML déployé est
`config.example.toml` tel quel et le point de départ est le centre de
Rennes : **aucune donnée personnelle du mainteneur n'est sur ce serveur**,
ni clé Intervals, ni identifiants BRouter. C'est un déploiement qui prouve
la chaîne, pas un déploiement qui sert.

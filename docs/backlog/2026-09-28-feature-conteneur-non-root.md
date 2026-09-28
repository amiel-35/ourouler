# Faire tourner le conteneur API+front sans root

Type : feature
Statut : à valider

## Pourquoi

Le conteneur qui sert l'API et le front à chaque cycliste hébergé
(`deploiement/api/Dockerfile`) tourne aujourd'hui comme n'importe quelle
image `python:3.12-slim` sans `USER` posé : en root. Une exécution root dans
un conteneur exposé n'ajoute rien d'utile ici (rien n'écoute sous 1024, rien
n'installe de paquet système au démarrage) et élargit ce qu'une faille dans
une dépendance (FastAPI, uvicorn, httpx…) pourrait atteindre à l'intérieur
du conteneur. [déduit]

## Ce que je veux voir

- L'image tourne avec un utilisateur applicatif dédié, sans privilège, posé
  dans le `Dockerfile` (`RUN useradd` ou `adduser`, puis `USER
  <nom>`), après l'installation des paquets (qui reste root, `apt`/`uv sync`)
  et avant le `CMD`.
- Les chemins que le processus écrit à l'exécution restent accessibles à cet
  utilisateur :
  - `/config/config.toml` et `/config/service.toml`, écrits par
    `deploiement/api/entrypoint.py` (`os.makedirs` + `os.open(..., 0o600)`) —
    le dossier `/config` doit appartenir à l'utilisateur applicatif, ou le
    montage/volume Coolify doit le permettre ;
  - le volume nommé `donnees:/data/cache` (`docker-compose.yml`,
    `docker-compose.api.coolify.yml`) — un volume Docker nommé est créé root
    par défaut ; il faut soit un `chown` au premier démarrage (root le temps
    de ce geste, avant `USER`), soit documenter que Coolify le crée déjà avec
    les bons droits.
- Le port d'écoute (8000, et 8001 pour l'admin en boucle locale) reste
  inchangé : aucun des deux n'a besoin de root.
- Le `HEALTHCHECK` (`curl`/`urllib` vers `/sante`) continue de fonctionner
  sous le nouvel utilisateur.
- Aucun changement pour `ourouler api` en local (hors conteneur) : ce lot ne
  touche que `deploiement/api/Dockerfile` et les deux `docker-compose*.yml`.

## C'est fini quand

`docker compose -f deploiement/api/docker-compose.yml --env-file
deploiement/api/.env up --build` démarre, `/sante` répond 200, l'écriture du
TOML depuis `OUROULER_CONFIG_TOML_B64` réussit, un import de fichier
synthétique écrit bien dans le volume `donnees`, et `docker exec <conteneur>
id` ne montre pas `uid=0`. Rejoué en préproduction Coolify avant tout passage
en production (aucune installation ni changement de service sans l'accord du
mainteneur, AGENTS.md).

## Hors sujet

- Un `securityContext` Kubernetes ou équivalent : ourouler tourne sur
  Coolify/Docker Compose, pas sur Kubernetes.
- Réduire la surface de l'image (multi-stage déjà en place, distroless…) :
  sujet voisin, pas celui-ci.
- Chiffrer le volume `donnees` : hors périmètre, question de l'hébergeur.

## Acquis techniques

- Le `Dockerfile` est déjà en deux étages (front construit dans
  `node:20-slim`, API dans `python:3.12-slim`) : l'utilisateur non-root ne
  se pose que sur le second étage, celui qui tourne réellement en
  production.
- `entrypoint.py` ouvre déjà les fichiers sensibles en `0o600` explicite
  plutôt qu'un `chmod` après coup (« entre les deux, le fichier existerait en
  lecture pour tout le conteneur ») — la même discipline s'applique à
  l'utilisateur propriétaire : que ce soit le nouvel utilisateur applicatif,
  pas root, dès l'écriture.

## Questions ouvertes

- Le volume `donnees` : Coolify le crée-t-il avec un propriétaire qui
  convient à un utilisateur non-root, ou faut-il un geste explicite (`chown`
  dans l'entrypoint, avant l'abandon des privilèges) ? À vérifier en
  préproduction avant la bascule en production.
- Un UID/GID fixe (ex. 1000) plutôt que celui que `useradd` choisirait, pour
  que les droits du volume restent stables d'un déploiement à l'autre ?

## Déjà en place / Doctrine révisée

- Constaté : `deploiement/api/Dockerfile` ne pose aucune instruction `USER`
  — les deux étages (`front`, `api`) tournent tels quels, donc en root par
  défaut de l'image `python:3.12-slim`.
- Constaté : `deploiement/api/entrypoint.py::_ecrire_config_depuis_environnement`
  et `_ecrire_service_depuis_environnement` créent `/config` (`os.makedirs`)
  et y écrivent en `0o600` au démarrage — ces gestes doivent rester possibles
  pour l'utilisateur non-root choisi.
- Constaté : `deploiement/api/docker-compose.yml` et
  `docker-compose.api.coolify.yml` déclarent tous deux un volume nommé
  `donnees:/data/cache`, monté en écriture par le processus (cache des
  activités, fichiers d'origine des comptes — voir
  `2026-09-26-feature-choix-conservation-fichiers-bruts.md`).
- Constaté : le `HEALTHCHECK` du `Dockerfile` appelle `python3 -c
  "...urlopen('http://127.0.0.1:8000/sante'...)"` — ne demande aucun
  privilège, continuera de fonctionner sous un utilisateur non-root sans
  changement.

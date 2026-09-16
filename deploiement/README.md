# L'hébergé minimal — tourner en local

Contrat : `docs/heberge_minimal_contrat.md`. Ce dossier construit ce que le
contrat demande — un conteneur qui génère la page du jour une fois par jour,
un serveur statique qui la sert derrière une authentification basique — et
**rien de plus**. Aucun déploiement ici : `docker compose` sur cette machine
sert à vérifier le lot, pas à le mettre en ligne (règle absolue 7 de
CLAUDE.md — le geste de déploiement sur Coolify reste au mainteneur, soumis
séparément).

## Ce qu'il y a dans ce dossier

- `Dockerfile` — une image, deux rôles (la commande du service choisit).
- `generateur/entrypoint.py` — exécute `ourouler sortie` une fois au
  démarrage, puis chaque jour à `OUROULER_HEURE_GENERATION`.
- `serveur/serveur.py` — sert le volume produit, derrière une
  authentification basique (stdlib `http.server`, aucun framework).
- `docker-compose.yml` — orchestration locale des deux conteneurs.
- `config.example.toml` — gabarit du fichier TOML du conteneur : cycliste,
  vélos, météo, séance, tenue... **jamais** le départ, la clé Intervals ni
  les identifiants BRouter, qui viennent exclusivement de l'environnement.
- `.env.example` — gabarit des variables d'environnement (secrets compris),
  aucune valeur dedans.

## Préparer

1. **Le fichier TOML non-secrets.** Copier `config.example.toml` vers un
   chemin hors du dépôt, ou sous un nom que `.gitignore` couvre déjà (ex.
   `deploiement/config.local.toml`), et le renseigner (masse, FTP, vélos,
   éventuellement `[seance]`/`[tenue]` si les défauts ne conviennent pas).

2. **Les secrets et le point de départ.**
   ```
   cp deploiement/.env.example deploiement/.env
   ```
   Renseigner dans `deploiement/.env` :
   - `OUROULER_INTERVALS_API_KEY`, `OUROULER_INTERVALS_ATHLETE_ID` — Intervals.icu
     → Settings → Developer.
   - `OUROULER_DEPART_NOM`, `OUROULER_DEPART_LATITUDE`, `OUROULER_DEPART_LONGITUDE`.
   - `OUROULER_BROUTER_URL` (et `OUROULER_BROUTER_UTILISATEUR` /
     `OUROULER_BROUTER_MOT_DE_PASSE` si le serveur BRouter est protégé) —
     celui déjà en service sur le Coolify du mainteneur, atteint depuis un
     conteneur local par son URL publique, comme n'importe quel client.
   - `OUROULER_WWW_UTILISATEUR`, `OUROULER_WWW_MOT_DE_PASSE` — l'authentification
     basique du serveur statique (des valeurs à soi, sans rapport avec Intervals
     ou BRouter).
   - `OUROULER_CONFIG_HOTE` — chemin **absolu** vers le fichier TOML préparé
     à l'étape 1.

   `deploiement/.env` n'est jamais commité (`.gitignore` couvre déjà `.env`
   et `.env.*`, avec une exception explicite pour `.env.example`).

## Lancer

Depuis la racine du dépôt :

```
docker compose -f deploiement/docker-compose.yml --env-file deploiement/.env up --build
```

Le conteneur `generateur` produit la page immédiatement (pas d'attente de
l'heure planifiée pour vérifier), puis chaque jour à `OUROULER_HEURE_GENERATION`.
Le conteneur `serveur` écoute sur `OUROULER_PORT_HOTE` (8080 par défaut) :

```
curl -u <OUROULER_WWW_UTILISATEUR>:<OUROULER_WWW_MOT_DE_PASSE> http://localhost:8080/index.html
```

Ou depuis un téléphone sur le même réseau local :
`http://<IP locale du Mac>:8080/` (identifiants demandés par le navigateur).

Arrêter : `docker compose -f deploiement/docker-compose.yml down` (ajouter
`-v` pour aussi supprimer le volume `pages` et repartir de zéro).

## Les deux cas du contrat, à vérifier à l'œil

- **Rien de prévu ce jour-là** : `index.html` doit afficher « Rien de prévu »,
  la date du jour, et quand la page a été générée — jamais une erreur, jamais
  la page de la veille en silence (`--carte-sans-seance`, voir
  `ourouler sortie --help`).
- **La date** : que la séance soit prévue ou non, la page affiche toujours de
  quand elle date, visible sans ouvrir les outils de développement.

## Ce que ce lot ne fait pas

Il ne touche à rien sur le Coolify du mainteneur, ne lit aucun jeton dans
`~/.config/coolify`, et ne décide pas de la forme du déploiement final (une
image par service ou deux, `docker-compose.yml` réutilisé tel quel ou non) —
ce sont des choix du mainteneur, une fois qu'il a vu tourner ce qui précède.

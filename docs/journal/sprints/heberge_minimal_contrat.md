# Contrat — La page du jour en ligne, version minimale

Rédigé le 16/09/2026, après accord du mainteneur. **Un seul utilisateur,
aucun compte, aucune base de données.** Tout ce qui fera le sprint 7 —
comptes, authentification déléguée, Postgres, isolation par utilisateur — est
hors de ce lot et le reste.

## Pourquoi maintenant, et ce que ça débloque

Ce n'est pas « être hébergé ». **C'est que la page arrive sur le téléphone.**

Aujourd'hui elle est écrite sur le disque du Mac. Pour envoyer le parcours au
compteur il faut AirDrop puis « ouvrir avec » — personne ne fait ça trois fois
par semaine. Q22 l'a établi : le téléchargement du GPX fonctionne, mais depuis
le Mac, et Q5 a fermé le sujet sur le **partage système depuis le mobile**.

Tant que la page n'est pas sur le téléphone, **le dogfooding reste
théorique** — et c'est le dogfooding qui a trouvé tous les défauts de ce
sprint.

## La forme retenue : statique, régénérée chaque matin

**Pas de service web, pas de framework, pas de requêtes à traiter.**

Une tâche planifiée tourne chaque matin, appelle le code existant, et écrit la
page du jour dans un dossier. Un serveur statique la sert derrière
l'authentification basique déjà en place sur le Coolify du mainteneur, à côté
de BRouter.

Pourquoi cette forme plutôt qu'une application :

- **La page est déjà autonome.** Un fichier HTML avec Leaflet, les GPX en
  base64 dedans, aucun appel serveur. Elle n'a jamais eu besoin d'un backend.
- **Rien à exposer.** Pas de route, pas de paramètre d'entrée, donc aucune
  surface d'attaque au-delà du serveur statique.
- **Le coût d'exécution est borné** : un passage par jour, ~150 appels
  Open-Meteo (doctrine, décompte par coordonnée) sur 10 000, et cinq appels
  BRouter.

Ce qu'on perd : l'interactivité — `--vent retour-dos`, `--direction`,
`--distance`. **Acceptable pour ce lot** : la page porte déjà trois
propositions contrastées, donc le choix est dedans. Une version à la demande
viendra si l'usage le réclame, et elle se posera sur le même code.

## Les secrets — la vraie décision de ce lot

La tâche planifiée a besoin de la **clé d'API Intervals** et du **point de
départ** du mainteneur. Règle absolue 1 : jamais dans le dépôt, ni dans une
image, ni dans un fichier commité.

**Retenu** : variables d'environnement du service Coolify, posées par le
mainteneur dans son interface, jamais écrites ailleurs. Le conteneur lit la
configuration depuis l'environnement — ce que `config.py` sait déjà faire pour
la clé Intervals.

**Conséquence de conception qui en découle, et qui sert le sprint 7** : le
point de départ doit pouvoir venir de l'environnement au même titre que la
clé. C'est la doctrine §10 appliquée un cran plus tôt — le profil est une
donnée, pas une constante.

## Le périmètre, précisément

1. **Un conteneur** qui exécute `ourouler sortie` une fois par jour et écrit
   la page dans un volume.
2. **Un serveur statique** qui sert ce volume derrière l'authentification
   basique existante.
3. **La configuration par l'environnement** : clé Intervals, point de départ,
   URL et identifiants BRouter.
4. **Le cas « rien de prévu »** : un jour sans séance planifiée doit produire
   une page qui le dit, pas une erreur ni une page de la veille.
5. **La date** : la page doit dire de quand elle date. Une page de la veille
   servie en silence serait pire que pas de page.

## Ce qui n'est pas dans ce lot

Comptes et authentification déléguée, base de données, isolation par
utilisateur, API, interactivité, notifications. Et **le déploiement
lui-même** : règle absolue 7, c'est un geste du mainteneur sur son serveur,
soumis séparément avec ce qui sera installé et où.

## Critère d'acceptation

Le conteneur tourne **en local**, produit la page du jour à partir de la vraie
configuration, et la sert derrière une authentification basique. Le mainteneur
l'ouvre depuis son téléphone sur le réseau local et télécharge le GPX. Rien
n'est déployé tant qu'il n'a pas vu ce que ça fait.

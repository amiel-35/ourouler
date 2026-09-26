# Revenir en arrière en production

Procédure répétée pour de vrai le 25/09/2026 sur la préproduction (même
image, même hébergeur, base à part). Les deux gestes sont indépendants :
revenir à une version de l'application, et restaurer la base des comptes.

## Revenir à une version de l'application

Chaque déploiement en production porte une étiquette `vX.Y.Z` (voir
`CHANGELOG.md`). Revenir en arrière, c'est redéployer le commit d'une
étiquette précédente.

**Par l'hébergeur (Coolify), sans toucher à git** — la voie répétée :

1. Épingler le commit : dans l'application, *Git Commit SHA* = le commit de
   l'étiquette visée (`git rev-parse vX.Y.Z^{commit}`), ou par l'API :
   `PATCH /applications/<uuid>` avec `{"git_commit_sha": "<sha>"}`.
2. Redéployer (`POST /deploy?uuid=<uuid>`), attendre `finished`.
3. Vérifier : `/sante` répond 200, `/api/v1/profil` répond 401 sans
   session, et un marqueur de version (une route présente ou absente dans
   `/openapi.json`, ou la version de `/sante`).
4. Pour revenir au courant : `{"git_commit_sha": "HEAD"}`, redéployer.

Mesuré en préproduction : **33 s** pour revenir d'une version, 34 s pour
revenir au courant ; le service coupe une vingtaine de secondes pendant la
bascule, et les tâches en cours (imports, calibrations) sont perdues.

**Par git** : pousser sur `prod` n'est possible qu'en avance rapide. Revenir
à une étiquette plus ancienne par git demande un `--force` sur `prod` ; on
préfère l'épinglage ci-dessus, réversible et sans réécrire la branche.

**Ce qui peut empêcher un retour arrière** : un format persisté ou une
migration de base plus récents que le code qu'on remet. Les tests de
`tests/compatibilite/` figent ces formats pour qu'aucun lot ne les change
sans le dire ; ce qui reste hors de ce filet est décrit dans
[`tests/compatibilite/LISEZMOI.md`](../tests/compatibilite/LISEZMOI.md).

## Revenir à l'ancien chemin de l'API

Sans changer de version : `OUROULER_API_CHEMIN` choisit, au démarrage, par
quel chemin l'API appelle le cœur (`ancien`, `nouveau` ou `double` ;
absente ou vide, `ancien`). Si le chemin `nouveau` pose problème, poser
`OUROULER_API_CHEMIN=ancien` (ou la vider) dans l'environnement du service
et redéployer (`src/ourouler/api/exploitation.py`, `chemin_api` ; les
autres variables : `deploiement/api/README.md`).

## Restaurer la base des comptes

La base PostgreSQL est sauvegardée chaque nuit par l'hébergeur (copies
locales), et le dossier des sauvegardes part ensuite hors du serveur.

1. Repérer la sauvegarde voulue (liste des exécutions de la sauvegarde
   planifiée, ou le dossier `/data/coolify/backups/databases/…` sur le
   serveur).
2. **D'abord, restaurer dans un Postgres jetable** et comparer les comptages
   table par table avec la base en service : c'est ce qui prouve que la
   sauvegarde est lisible, sans rien toucher.
3. Pour restaurer en place : copier le fichier dans le conteneur de la base,
   puis `pg_restore -U <utilisateur> -d <base> --clean --if-exists --no-owner --no-acl <fichier>`.
   **Ce geste efface l'état courant de la base** : en production, il se
   montre au mainteneur avant d'être fait.
4. Vérifier : les invitations attendues sont là (`ourouler invitations`
   dans le conteneur de l'application, qui liste les invitations en cours),
   une connexion réussit.

Répété en préproduction : compte d'essai présent (1), supprimé (0),
restauré (1), et l'invitation de nouveau listée.

## Deux constats de la répétition

- La préproduction n'atteignait pas sa base : l'option *Connect to
  Predefined Docker Network* de l'application était désactivée, alors
  qu'elle l'est en production. `/sante` répondait 200 quand même : un
  contrôle de santé ne suffit pas, **une invitation de bout en bout** fait
  partie de la vérification d'un environnement.
- `ourouler retirer` refuse de tourner sur un serveur neuf tant que le
  dossier des comptes n'existe pas (aucune connexion encore faite) : noté au
  backlog.

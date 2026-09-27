# Sprint 10 — bilan : ouverture du dépôt et restructuration

Du 25 au 27/09/2026. Plan : [`docs/journal/ouverture_plan.md`](../ouverture_plan.md).
Clos avec la version 0.11.0 (PR #118), en prod le 27/09/2026.

## Prévu

Un sprint « on ne code rien, on écrit seulement » (décision Q6 du plan) :
protéger la prod qui avait ses premiers invités, poser les filets, rendre le
dépôt lisible par un inconnu, puis restructurer le code **après**
l'ouverture, sur quatre à six sprints (§5 et §6 du plan). Critère de fin donné
par le mainteneur : l'appli n'a pas régressé, on peut inviter de nouveaux
cyclistes, on peut repartir sur des fonctionnalités, et accueillir des
contributeurs.

## Réalisé

- **La prod protégée d'abord** : branche `prod` et préproduction qui suit
  `main`, sauvegarde quotidienne éprouvée par une restauration, CI (lint,
  format, types, tests, front, image, secrets).
- **Les filets** : sorties de référence de la ligne de commande et de l'API,
  formats persistés, contrat OpenAPI figé, garde réseau, liste blanche des
  tests sautés, puis la comparaison sur les vraies données du mainteneur
  avant et après chaque lot qui touchait le code.
- **La restructuration entière, dans ce sprint** (lots 1 à 14 au lieu de
  quatre à six sprints) : noyau, stockage, services, rendu, commandes, routes
  de l'API, paquet `cli/`, contrat d'imports sans exception, double chemin de
  l'API en préprod.
- **Le nettoyage (N0 à N9)** : code mort, tests, commentaires d'historique
  (1 523 lignes → 69), documentation vérifiée ligne à ligne, documents de
  travail rangés dans `docs/journal/`, métadonnées, `ruff format`, pyright
  avec ligne de base, ESLint, accueil des contributeurs ; deux relectures
  indépendantes (Fable, puis Codex).
- **Versions** : 0.10.0 (restructuration, analyser un parcours, correctifs
  d'accueil) puis 0.11.0 ; étiquettes rétroactives `v0.1.0` à `v0.9.6`.

## Écarts

- **Plus fait que prévu, plus vite** : la restructuration prévue après
  l'ouverture a été faite dans le sprint, sans changement visible, parce que
  les filets permettaient de prouver chaque lot.
- **Du code malgré « on ne code rien »** : des correctifs d'accueil pour les
  invités (0.10.0) et deux défauts trouvés en relecture (0.11.0).
- **Reste hors sprint** : la bascule de l'API vers le nouveau chemin et le
  retrait d'`api/adaptateur.py` (après une à deux semaines de préprod en
  `double`) ; les réglages GitHub au passage en public ; la vérification que
  la copie restic contient le dump d'ourouler ; `docs/decisions/`, jamais
  fait, remplacé par `docs/journal/questions/`.
- **Des incidents de méthode** : neuf agents lancés en parallèle ont saturé
  la mémoire du poste ; trente tests adversariaux se sont mis à sauter en
  silence après le retrait des réexports, repérés au compteur de tests
  sautés.

## Ce qu'on en apprend

- Des filets d'abord, puis des lots courts prouvés sur les vraies données :
  c'est ce qui a rendu la restructuration sûre sans figer la prod.
- Deux agents à la fois au plus sur ce poste ; les autres attendent.
- Un test qui saute est un test qui échoue tant que son motif n'est pas dans
  la liste blanche : la fabrique adversariale échoue désormais au lieu de
  sauter.
- Une relecture indépendante trouve encore des choses après la nôtre :
  la revue Fable a relevé 30 points, Codex encore 6, tous réels.

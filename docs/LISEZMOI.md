# `docs/` — index

Ce dossier ne garde que le **relu** : des documents de référence, à jour,
qu'on peut citer sans vérifier la date. Le matériau brut du chantier (plans
de travail clos, contrats de sprint, explorations d'interface, notes de
mesure) est dans [`journal/`](journal/LISEZMOI.md).

## Fonctionnement du produit

- [`brouter.md`](brouter.md) — obtenir et faire tourner un serveur BRouter en
  local, pour qui développe.
- [`geocodage.md`](geocodage.md) — le choix des deux fournisseurs de
  géocodage et pourquoi.
- [`meteo_vent.md`](meteo_vent.md) — ce qu'on demande à la météo, et ce qu'on
  en fait (modèles, second avis, désaccord).
- [`services_externes.md`](services_externes.md) — la carte de toutes les
  dépendances réseau du produit : qui, pour quoi, avec quelle clé.
- [`table_ftp_vitesse.md`](table_ftp_vitesse.md) — table indicative FTP /
  vitesse à plat, engendrée par un script de mesure (ne pas corriger à la
  main).

## Utiliser le produit

- [`guide_ligne_de_commande.md`](guide_ligne_de_commande.md) — le mode
  d'emploi de `ourouler`, commande par commande.
- [`inviter.md`](inviter.md) — mode d'emploi opérationnel pour qui exploite
  un service hébergé et invite quelqu'un.
- [`retour_arriere.md`](retour_arriere.md) — la procédure pour revenir en
  arrière en production.

## Interface

- [`ux/doctrine_design_system.md`](ux/doctrine_design_system.md) — la
  doctrine du système de jetons visuels (« suisse vivante ») : ce qu'il est,
  ses deux couches, ses règles.

## Comprendre le projet

- [`demarche.md`](demarche.md) — comment ourouler s'est construit, avec quels
  outils, ce que l'expérience a appris.
- [`journal/ouverture_plan.md`](journal/ouverture_plan.md) — le plan de
  l'ouverture du dépôt et de sa restructuration (sprint 10, clos en 0.11.0),
  et son [bilan](journal/sprints/sprint-10-bilan.md).

## Ailleurs dans le dépôt

- [`../README.md`](../README.md) — présentation du projet, installation,
  premiers pas.
- [`../ARCHITECTURE.md`](../ARCHITECTURE.md) — la carte du code : paquets,
  couches, dépendances.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — comment contribuer (branches,
  vérifications, PR).
- [`../AGENTS.md`](../AGENTS.md) — consignes pour tout agent de code qui
  travaille sur ce dépôt.
- [`../SECURITY.md`](../SECURITY.md) — politique de signalement des failles.
- [`../CHANGELOG.md`](../CHANGELOG.md) — l'historique des versions, du point
  de vue du cycliste.
- [`../doctrine_architecture.md`](../doctrine_architecture.md) — les choix
  structurants et pourquoi.

## Le matériau brut

- [`journal/`](journal/LISEZMOI.md) — questions au mainteneur, contrats et
  relectures de sprint, cadrage d'origine, explorations d'interface : tel
  qu'écrit, pas relu comme le reste.

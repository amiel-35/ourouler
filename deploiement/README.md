# `deploiement/` — le paquetage API et front

Ce dossier ne contient plus qu'un seul paquetage : `api/`, qui construit une
image servant l'API et l'interface web (front) derrière la même origine, avec
les comptes dans PostgreSQL en mode hébergé.

Voir [`deploiement/api/README.md`](api/README.md) pour tout — préparer, lancer
en local pour vérifier, variables d'environnement, déployer.

Historique : une « page du jour » autonome (un conteneur qui générait une
carte statique une fois par jour, servie derrière une authentification
basique, sans compte ni interface) a existé dans ce dossier ; l'API et le
front la remplacent et ce paquetage a été retiré (voir `CHANGELOG.md`).

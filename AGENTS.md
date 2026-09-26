# AGENTS.md — ourouler

Consignes pour tout agent de code (Codex, Cursor, Claude Code…) qui travaille
sur ce dépôt. En cas de doute, `doctrine_architecture.md` fait foi.

## Le projet

ourouler (« où rouler ? ») est une bibliothèque Python, une ligne de commande
et une API avec son interface web, pour un cycliste équipé d'un capteur de
puissance : où il va pleuvoir selon la direction, puis une boucle de la bonne
durée, cohérente avec la séance du jour et la tenue. Licence AGPL-3.0-or-later.

## Installer

- Python ≥ 3.12 et `uv` : `uv sync --frozen --extra dev` (`dev` est un
  *extra* de `pyproject.toml`, pas un groupe : `--group dev` n'installe rien).
- Front (Node 20) : `cd front && npm ci`.

## Vérifier avant tout commit

- `uv run ruff check .`
- `uv run pytest -q`, **en entier**. Les tests de comptes lancent eux-mêmes
  un conteneur PostgreSQL : il faut Docker et l'image
  (`docker pull postgres:17-alpine`), sinon ils sont sautés, et la CI
  (`.github/workflows/ci.yml`) refuse un test Postgres sauté.
- `cd front && npm run verifier` (typage puis tests du front).

## Carte des paquets

Tout est sous `src/ourouler/` ; le détail et la règle d'imports sont dans
`ARCHITECTURE.md`. Les dépendances vont des entrées vers le noyau, jamais
l'inverse :

- entrées : `src/ourouler/cli.py`, `src/ourouler/commandes/` (une par
  sous-commande : du `Namespace` à la `Demande`, puis au rendu imprimé),
  `src/ourouler/config.py` (lecture du TOML et de l'environnement),
  `src/ourouler/api/` (FastAPI, comptes PostgreSQL) ;
- domaine, du plus bas au plus haut : `physique` < `meteo` < `boucle` <
  `seance` < `sortie`, plus `activites/` (lecteurs FIT/GPX/TCX, cache SQLite),
  `apprentissage/` et `geocodage/` ;
- adaptateurs HTTP : `src/ourouler/connecteurs/`, chacun avec un client
  injectable ;
- stockage : `src/ourouler/stockage/` (aujourd'hui les calibrations), qui
  reçoit un chemin et rend des objets du domaine ;
- noyau : `src/ourouler/noyau/` (`trace`, `activite`, `erreurs`,
  `proprietaire`, `seance`, `zones`, `meteo`, `profil`), bibliothèque
  standard seulement ; les anciens chemins (`boucle/trace.py`,
  `activites/modele.py`, `erreurs.py`, `proprietaire.py`,
  `seance/modele.py`, `seance/zones.py`) sont des réexports temporaires :
  importer le noyau, et le profil (`Velo`, `Depart`…) depuis
  `noyau.profil` plutôt que `config` ;
- `front/` : l'interface, qui ne parle qu'à l'API.

## Règles absolues

1. **Aucune donnée personnelle ni clé dans le dépôt** : ni fichier
   d'activité, ni point de départ, ni clé d'API, ni jeton, pas même dans une
   fixture. Les fixtures sont synthétiques. La configuration réelle n'est
   jamais commitée ; `config.example.toml` et `service.example.toml` le sont.
2. **Pas de réseau dans les tests.** Chaque connecteur prend un client HTTP
   injectable ; les tests rejouent des réponses de `tests/fixtures/`.
3. **Le cœur ne lit ni configuration ni environnement.** Seuls `cli.py`,
   `config.py` et `src/ourouler/api/exploitation.py` lisent un fichier de
   configuration, une variable d'environnement ou un chemin utilisateur ; le
   reste reçoit des objets. `tests/test_invariants.py` le mesure.
4. **Français** dans la doc, les messages et les commentaires ; identifiants
   Python en français sans accents (`Activite`, `velo`). Code lisible et
   direct plutôt que malin.
5. Deux modèles météo qui divergent s'affichent comme un désaccord, jamais
   moyennés ; un modèle se valide sur des données qu'il n'a pas vues.

## Pièges connus

- **« Aucune coordonnée réelle »** : `tests/test_invariants.py` balaie les
  fixtures, les configurations et **tout le Markdown du dépôt** ; un couple
  de nombres décimaux proche d'une ville réelle le fait échouer. Nommer un
  lieu plutôt qu'écrire ses coordonnées ; dans les tests, des coordonnées
  fictives.
- **Contrat d'API figé** : `tests/caracterisation/openapi.json` est la
  référence de `tests/api/test_contrat_openapi.py`. La régénérer
  (`uv run pytest --regenerer-golden`) est un changement de comportement pour
  le front : il se justifie dans la PR, jamais par réflexe.
- **Fuseau horaire** : la CI et le conteneur tournent en UTC. Un test qui
  suppose un fuseau précis le dit avec la fixture `fuseau_de_paris` de
  `tests/conftest.py`, au lieu d'emprunter le fuseau de la machine.
- **Fichiers d'activité** : `.gitignore` ignore `.fit`, `.gpx` et `.tcx`
  quelle que soit la casse, ainsi que les `.html` (les cartes générées portent
  le point de départ) ; une nouvelle fixture se réintègre
  **nommément**, et `tests/test_gitignore.py` vérifie l'accord avec
  `tests/fixtures/generer_activites.py`.
- **Linux est sensible à la casse** (CI, serveur), macOS non : un nom de
  fichier ou un import qui ne diffère que par la casse passe en local et
  casse en CI.

## Proposer une PR

- Une branche courte par sujet, depuis `main`.
- Une ligne dans `CHANGELOG.md` sous « Non publié », du point de vue du
  cycliste (Ajouté, Modifié, Corrigé, Retiré, Sécurité).
- Ruff, pytest et `npm run verifier` verts.
- La PR se fusionne par un **commit de merge** (pas de squash), et **seul le
  mainteneur merge** : un agent pousse la branche et ouvre la PR, il ne la
  fusionne jamais.
- **Aucune installation** sur une machine ou un serveur (moteur de tracé,
  conteneurs, services d'hébergement…) sans l'accord explicite du
  mainteneur : on propose, on attend.
- Une décision qui contredit `doctrine_architecture.md` se pose en question
  dans la PR ; si elle est acceptée, la doctrine se met à jour dans la même
  PR. Voir aussi `CONTRIBUTING.md`.

# Contribuer à ourouler

Merci de l'intérêt. ourouler est une bibliothèque Python, une ligne de
commande, une API et une interface web pour cyclistes : « où va-t-il
pleuvoir, et quel parcours pour la séance du jour ? ». Ce guide dit comment
installer le projet, ce qu'une PR doit vérifier, et les quelques règles qui
ne se discutent pas.

Pour une faille de sécurité, n'ouvrez pas de ticket public : voir
[SECURITY.md](SECURITY.md).

## Installer

Prérequis : Python 3.12 ou plus récent, [uv](https://docs.astral.sh/uv/),
Node.js 20 et npm, et Docker pour une partie des tests. Le dépôt porte un
`.python-version` (3.12, la version de la CI) : `uv` s'aligne dessus tout
seul, sans installation manuelle.

```sh
uv sync --frozen --extra dev     # Python : dépendances de test et de lint
cd front && npm ci               # interface web
```

`dev` est un *extra* (`[project.optional-dependencies]` de `pyproject.toml`),
pas un groupe de dépendances : `uv sync --group dev` ne l'installe pas. Il
reprend les dépendances de l'API, pour que les tests de l'API tournent au
lieu d'être sautés.

**Docker.** Les tests des comptes démarrent eux-mêmes un conteneur
PostgreSQL à partir de l'image `postgres:17-alpine` :

```sh
docker pull postgres:17-alpine
```

Sans Docker ou sans l'image, ces tests sont **sautés** en local, avec le
motif « PostgreSQL local indisponible ». La CI, elle, **refuse** un test
Postgres sauté : si vous touchez aux comptes ou aux sessions, faites-les
tourner chez vous avant d'ouvrir la PR.

## Vérifier avant d'ouvrir une PR

Les commandes suivantes doivent passer, sans exception :

```sh
uv run ruff check .
uv run ruff format --check .   # ou `ruff format .` pour corriger
uv run python scripts/pyright_ligne_de_base.py   # typage de src/, voir plus bas
uv run pytest -q                 # la suite complète, pas un sous-ensemble
cd front && npm run verifier     # tsc --noEmit, eslint, puis vitest run
```

La CI (`.github/workflows/ci.yml`) tourne sur chaque PR vers `main`, et à
chaque poussée sur `main` et `prod`. Elle comporte quatre jobs :

1. **secrets** — `gitleaks` parcourt tout l'historique du dépôt ; les faux
   positifs connus sont écartés par `.gitleaksignore`.
2. **python** — Linux, Python 3.12, fuseau UTC : `ruff check`, `ruff format --check`,
   puis `scripts/pyright_ligne_de_base.py` (typage), puis toute
   la suite `pytest` avec l'image Postgres ; elle échoue sur tout test sauté
   dont le motif n'est pas dans `tests/sauts_autorises.py`, un test Postgres
   sauté compris. `CI=1 uv run pytest -q` rejoue cette garde chez vous.
3. **front** — Node 20 : `npm ci` puis `npm run verifier`.
4. **image** — construit l'image de l'API (`deploiement/api/Dockerfile`),
   la démarre en mode hébergé sans base, et vérifie que `/sante` répond 200,
   `/` répond 200 et `/api/v1/profil` répond 401.

Un test vert sur votre machine peut échouer en CI : fuseau horaire,
arrondis flottants propres à une plateforme, casse des noms de fichiers.
Écrivez des tests qui ne dépendent ni du fuseau ni de l'heure locale.

## Les règles non négociables

1. **Aucune donnée personnelle, aucune clé.** Pas de fichier d'activité
   réel, de coordonnées de départ, de clé d'API ni de jeton dans le dépôt,
   même dans un test. Les fixtures sont synthétiques (ou anonymisées) et
   vivent dans `tests/fixtures/`. Les fichiers de configuration réels ne
   se commitent jamais : seuls les modèles `config.example.toml` et
   `service.example.toml` le sont.
2. **Pas de réseau dans les tests.** Chaque connecteur reçoit un client HTTP
   injectable ; les tests lui passent des réponses enregistrées dans
   `tests/fixtures/`. Un test qui appelle Internet est refusé.
3. **Le cœur ne sait pas où il tourne.** Sous `src/ourouler/`, seuls
   `cli/`, `config.py` et `api/exploitation.py` lisent un fichier de
   configuration, une variable d'environnement ou un chemin de
   l'utilisateur (`tests/test_invariants.py` le vérifie). Le reste reçoit des
   objets (`Config`, un client HTTP…). Une fonction du cœur qui ouvre
   `~/.config` ou lit `os.environ` est un bug.
4. **Tout en français** : documentation, messages de la ligne de commande
   et de l'interface, commentaires. Les identifiants Python sont en
   français **sans accents** (`Activite`, `velo`, `couronne`). Pas de
   franglais quand un mot français existe.

La doctrine complète et ses justifications sont dans
[`doctrine_architecture.md`](doctrine_architecture.md) ; en cas de doute,
elle fait foi.

## Style et normes de taille

Python 3.12, dataclasses et annotations, pas d'ORM ; HTTP avec `httpx`,
ligne de commande avec `argparse`. Du code lisible et direct : cinquante
lignes évidentes valent mieux que vingt lignes astucieuses.

ruff (`[tool.ruff]` de `pyproject.toml`) vérifie, en plus des règles
`E`, `F`, `I`, `B` et `UP` et d'une ligne de 110 caractères au plus, quatre
seuils par fonction :

- complexité cyclomatique (`C901`) : 12 au plus ;
- branches (`PLR0912`) : 15 au plus ;
- instructions (`PLR0915`) : 50 au plus ;
- arguments positionnels (`PLR0917`) : 6 au plus.

Aucune règle ne borne le nombre de lignes d'une fonction ou d'un fichier ;
côté front, un composant fait 300 lignes au plus
(`front/tests/taille_composants.test.ts`). Le code qui dépasse un seuil de
ruff est listé dans `[tool.ruff.lint.per-file-ignores]`, chaque exception
précédée d'un commentaire « datée » (avec une échéance) ou « permanente »
(avec sa raison) ; `tests/test_regles_ruff.py` échoue quand une exception ne
sert plus ou a passé son échéance. Un nouveau code respecte les seuils
d'emblée, et une exception n'est pas un précédent. Le code est formaté par
`ruff format` (le journal, `docs/journal/`, en est exclu) ; le commit qui l'a
appliqué d'un coup est listé dans `.git-blame-ignore-revs`, à passer à
`git blame --ignore-revs-file` (GitHub le lit tout seul).

## Typage (pyright) et sa ligne de base

`pyright` (`[tool.pyright]` de `pyproject.toml`) vérifie les types dans
`src/` en mode `standard` ; `tests/` n'est pas encore couvert (périmètre
du lot d'adoption, à élargir plus tard). L'outil télécharge et gère son
propre Node privé (`nodeenv`, dans le cache de `uv`) : aucune installation
globale n'est nécessaire.

Les erreurs déjà présentes le jour de l'adoption sont tolérées, mais gelées
dans `pyright_ligne_de_base.json` à la racine du dépôt (une entrée par
(fichier, règle, message), sans numéro de ligne pour ne pas casser la
comparaison au moindre déplacement). `scripts/pyright_ligne_de_base.py` :

```sh
uv run python scripts/pyright_ligne_de_base.py             # vérifie
uv run python scripts/pyright_ligne_de_base.py --regenerer # réécrit la ligne de base
```

**La ligne de base ne peut que descendre.** Une erreur nouvelle, absente
du fichier figé, fait échouer la vérification : le code se corrige, la
ligne de base ne se régénère jamais pour la faire entrer. Une erreur
corrigée disparaît du rapport et le script l'annonce comme un progrès
sans faire échouer la commande ; c'est alors, et seulement alors, qu'on
régénère la ligne de base avec `--regenerer`, pour qu'elle baisse pour de
bon (elle ne baisse jamais toute seule).

## Fichiers de référence

Certains tests comparent une sortie à un fichier figé :

- le **contrat de l'API**, `tests/caracterisation/openapi.json` : toute
  route, tout champ ou tout code de réponse modifié fait échouer
  `tests/api/test_contrat_openapi.py` ;
- les **sorties de référence** de la ligne de commande et de l'API
  (`tests/caracterisation/`, voir son `LISEZMOI.md`) ;
- les **formats persistés** (`tests/compatibilite/`, voir son `LISEZMOI.md`).

Si la modification est voulue, régénérez la référence concernée avec
l'option `--regenerer-golden`, par exemple :

```sh
uv run pytest --regenerer-golden tests/api/test_contrat_openapi.py
```

puis commitez le fichier régénéré avec la PR. **Toute différence dans un
fichier de référence se relit comme un changement de comportement** :
expliquez-la dans la description de la PR. Ne régénérez jamais pour « faire
passer » un test que vous ne comprenez pas.

## Journal des changements et versions

Chaque PR ajoute sa ligne dans [`CHANGELOG.md`](CHANGELOG.md), sous
« Non publié », dans la bonne rubrique *Keep a Changelog* : Ajouté,
Modifié, Corrigé, Retiré, Sécurité. La ligne s'écrit **du point de vue du
cycliste** (ce qui change pour lui), pas du point de vue du code. Une PR
sans effet visible (documentation interne, outillage) peut s'en passer, en
le disant.

Les versions suivent SemVer en `0.x` :

- **mineure** (`0.9.0` → `0.10.0`) : un ensemble de fonctionnalités livré ;
- **correctif** (`0.9.5` → `0.9.6`) : une correction entre deux mineures.

La version de référence est celle de `pyproject.toml` ; celle de
`front/package.json` la suit. Au déploiement, « Non publié » devient la
nouvelle version. Ne changez pas le numéro de version dans une PR : c'est
le geste du mainteneur.

## Branches et PR

- Partez de `main` à jour, sur une branche courte au nom parlant ; un sujet
  par PR.
- Ouvrez la PR vers `main`, avec une description qui dit quoi, pourquoi et
  comment c'est vérifié.
- La fusion se fait par **commit de merge**, pas par squash : l'historique
  des branches reste lisible.
- `main` part en **préproduction**. La production suit une branche `prod`
  que seul le mainteneur pousse, au moment qu'il choisit.
- **Le mainteneur décide et merge.** Une question de produit (ce que voit
  le cycliste, une règle de tenue ou de séance, le choix d'un service
  externe) se pose dans un ticket avant d'écrire le code.

## Licence

ourouler est distribué sous licence **AGPL-3.0-or-later** (voir
[`LICENSE`](LICENSE)). En proposant une contribution, vous acceptez qu'elle
soit publiée sous cette même licence.

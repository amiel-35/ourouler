# CLAUDE.md — ourouler (« où rouler ? »)

Instructions pour les agents Claude travaillant sur ce dépôt. La doctrine
complète et ses justifications sont dans `doctrine_architecture.md` : en cas
de doute, elle fait foi. Ce fichier est le résumé opérationnel. Le besoin
d'origine est dans `docs/cadrage.md`, le plan dans `docs/plan_sprints_agents.md`.

## Ce qu'est ce projet

Bibliothèque Python + ligne de commande pour un cycliste avec capteur de
puissance : « je vais rouler ; au nord, au sud ou à l'est, où va-t-il
pleuvoir ? », puis un parcours de la bonne durée dans la bonne direction,
cohérent avec la séance du jour, avec la tenue, poussé sur le Garmin. Open
source (MIT), autonome, sans Home Assistant. Un seul mainteneur (Amiel), qui
en est aussi le premier utilisateur : **son besoin passe en premier**.

## Règles absolues

1. **Aucune donnée personnelle ni clé dans le dépôt.** Ni fichier
   d'activité, ni coordonnées de départ, ni clé d'API, ni jeton — pas même
   dans un test ou une fixture. Les fixtures sont synthétiques ou
   anonymisées, réintégrées nommément dans `.gitignore`. Le fichier de
   configuration réel n'est jamais commité ; `config.example.toml` l'est.
2. **Le cœur ne sait pas où il tourne.** Sous `src/ourouler/`, seul `cli.py`
   (et `config.py` pour le chargement TOML) a le droit de lire un fichier de
   configuration, une variable d'environnement ou un chemin utilisateur. Tout
   le reste reçoit des objets (`Config`, `Velo`, un client HTTP…). Une
   fonction du cœur qui ouvre `~/.config` est un bug.
3. **Pas de réseau dans les tests.** Chaque connecteur prend un client
   injectable ; les tests utilisent des réponses enregistrées dans
   `tests/fixtures/`. Un test qui appelle Internet est refusé.
4. **Chaque lot livré = une commande qui tourne sur les vraies données du
   mainteneur.** Pas une promesse, pas une démo sur fixture seule. Si les
   vraies données manquent (clé absente, fichiers absents), le lot est
   **non vérifié** et le dit en toutes lettres.
5. **Ne rien affirmer sans mesure.** Un modèle est validé sur des données
   qu'il n'a pas vues, avec une erreur rapportée ; deux modèles météo qui
   divergent sont affichés comme un désaccord, jamais moyennés.
6. **Historique à partir du 1ᵉʳ décembre 2023**, par vélo et par période.
   Date et rattachement sont des paramètres de configuration, pas des
   constantes.
7. **Aucune installation sur une machine ou un serveur** (BRouter, Docker,
   GraphHopper, Coolify…) **sans l'accord explicite du mainteneur.** On
   propose, on attend.

## Stack et conventions

- Python ≥ 3.12, `uv`, layout `src/`, `pyproject.toml` (hatchling).
  Dataclasses et annotations ; pas de Pydantic, pas d'ORM.
- CLI `argparse` (stdlib). Sous-commandes : `inventaire`, `meteo`, puis
  `boucle`, `sortie`, `garmin`. Texte lisible par défaut, `--json` en option.
- HTTP `httpx`. FIT `fitdecode`, GPX `gpxpy`, TCX `xml.etree`. Cache : fichiers
  bruts + index SQLite (stdlib) dans `~/.cache/ourouler` (configurable).
- Tests `pytest` (`uv run pytest`), lint `ruff` (`uv run ruff check .`).
  Les deux doivent être verts avant tout commit.
- Français dans la doc, les messages CLI et les commentaires ; identifiants
  Python en français sans accents (`Activite`, `couronne`, `velo`). Pas de
  franglais quand un mot français existe.
- Style : privilégier le code lisible et direct. 50 lignes évidentes valent
  mieux que 20 lignes malignes.

## Sources externes (résumé — détail et limites en doctrine §6)

- **Open-Meteo** : `models=meteofrance_arome_france_hd` en France, un second
  modèle en « second avis ». Gratuit, sans clé, plusieurs points par appel.
- **Intervals.icu** : clé d'API personnelle (auth basique `API_KEY:<clé>`),
  liste des activités et téléchargement du FIT d'origine, séance planifiée.
- **BRouter / GraphHopper** (S2), **Garmin Connect** (S5) : rien d'installé,
  rien de décidé — voir `docs/questions_mainteneur.md`.

## Workflow attendu

- **Cadrage d'abord, en français, court** ; puis lots avec critères
  d'acceptation mesurables ; un sujet à la fois.
- **Cadence de repriorisation : tous les deux sprints.** Deux sprints figés
  qu'on exécute tels quels, un troisième esquissé qui n'engage à rien ; à la
  fin des deux figés, le mainteneur reprioritise à partir des livraisons,
  des écarts entre prévu et réalisé et du backlog. Un agent ne propose jamais
  d'élargir un sprint figé en cours de route.
- **Modèles** (aligné le 15/09/2026 sur les instructions globales du
  mainteneur ; ce qui précédait, « Opus partout où ça suffit », était une
  incompréhension). **Sonnet est le défaut** : toute implémentation bien
  cadrée, avec des critères d'acceptation clairs. **Haiku** pour le
  mécanique en masse — renommage, boilerplate, conversion de format.
  **Opus** pour le jugement pur et les algorithmes subtils : relecture,
  tests adversariaux, découpage de sprint, débogage coriace, concurrence.
  **Fable** seulement quand l'indépendance vis-à-vis du contexte du
  mainteneur est le but, et **toujours en demandant d'abord**.

  Le `model` est **obligatoire** sur chaque appel d'agent : l'omettre hérite
  silencieusement du modèle de session. Ne pas monter en tier sur un aveu
  d'incertitude quand la tâche est du jugement — un agent sous-tieré ne dit
  pas qu'il doute, il répond faux avec assurance. Le tier se choisit
  d'avance. Détail dans `docs/plan_sprints_agents.md`.
- **Le code substantiel est écrit par un sous-agent et relu par un second
  avant d'être montré au mainteneur.** Deux agents en parallèle travaillent
  chacun dans son propre worktree git ; la fusion est un geste explicite.
- Branches courtes, un sprint = une branche d'intégration `sprint-N`, PR vers
  `main`. **Le mainteneur seul merge.** Sans lui, un agent pousse la branche
  et ouvre la PR, il ne merge pas.
- Toute décision qui contredit `doctrine_architecture.md` se pose comme
  question au mainteneur ; si elle est actée, mettre la doctrine à jour fait
  partie de la PR.
- Les questions produit (règles de tenue, règles de séance, choix du moteur
  de tracé, nom du projet) remontent au mainteneur dans
  `docs/questions_mainteneur.md` ; on ne tranche pas à sa place, on avance
  sur ce qui n'en dépend pas.

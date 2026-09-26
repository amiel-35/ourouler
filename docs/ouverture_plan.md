# Ouverture du dépôt — plan de remise d'aplomb sans casser la prod

Écrit le 25/09/2026. Le diagnostic et le plan viennent d'Opus, une contre-lecture
indépendante de Fable les corrige, et le tout est consolidé ici. Les deux ont
été mesurés sur `main` (75dcf06), en lecture seule.

**Le besoin, dans les mots du mainteneur** : « Objectif ouverture du repo.
Actuellement vibe coding, beaucoup de discussions, d'échanges de tâtonnement,
et pas de revue de qualité de code, de normes de tailles de fonction… Manque de
document d'architecture, de règles de contribution. Sûrement un manque de
séparation entre le modèle physique des vélos et le reste. » Puis : « Objectif
migrer le code sans casser la prod. »

**Politique d'agents pour ce chantier**, fixée par le mainteneur, qui remplace
le « Sonnet par défaut » de CLAUDE.md :
- **Opus et Fable** pour l'analyse et la conception. Fable fait la
  contre-lecture indépendante des lots à risque ; le mainteneur l'a autorisée
  pour ce chantier.
- **Sonnet** seulement pour des tâches ultra bornées et faciles : un fichier,
  une règle claire, un critère binaire.
- **Haiku** pour les changements mécaniques, et seulement quand le lot se
  vérifie par égalité (sorties de référence et tests), jamais par jugement.
- `model` est obligatoire sur chaque appel. Un changement de tier en cours de
  lot fait repartir de zéro.

## 0. Où on en est (tenu à jour)

**Décisions du mainteneur, 25/09/2026** (réponses au §8) :

| # | Question | Décision |
|---|---|---|
| 1 | Historique git | **(a) garder tel quel** — voir la conséquence au §7 |
| 2 | Branche `prod` et préprod | acceptées toutes deux |
| 3 | GitHub Actions et protection de `main` | acceptées ; la protection, le mainteneur la pose |
| 4 | Commentaires historiques | purgés, avec renvoi `docs/decisions/Qnn` ; une PR par paquet, commentaires seuls |
| 5 | Dépendances de dev | le minimum : contrat d'imports maison, gitleaks en Action seulement, horloge injectée (pas de freezegun), ESLint reporté |
| 6 | Gel | un sprint dédié (sprint 10 = ouverture) ; correctifs de prod permis en `0.10.x`. Précisé le même jour : « gros sprint de refactoring, on code rien, on écrit seulement » |
| 7 | Langue | tout en français, le README s'ouvre sur un paragraphe en anglais |
| 8 | URL de prod dans le dépôt | **non** ; domaines d'exemple dans `deploiement/` |
| 9 | Versions | SemVer `0.x` tel que proposé au §7 bis, étiquettes rétroactives comprises |
| + | AGENTS.md | accepté au §5 (voir le point 5) |

**Prérequis, fait le 25/09/2026 :**

- **P1 — fait.** Branche `prod` créée sur `b8c390d` (le commit qui tournait),
  et l'application Coolify `ourouler-api` suit `prod` au lieu de `main`.
  Aucun redéploiement ne s'est produit. Désormais **merger dans `main` ne
  touche plus la prod** ; on déploie en poussant sur `prod`.
- **P4 — fait, en local seulement.** Sauvegarde Coolify planifiée de
  `ourouler-db-prod` (chaque jour à 3 h 30, 7 copies gardées). Une
  exécution a été restaurée dans un Postgres jetable **sur le serveur**, et
  les comptages sont identiques, table par table. **Limite** : la copie vit
  sur le même disque, et aucun stockage S3 n'est configuré dans Coolify.
  **Copie hors serveur : déjà assurée**, sans rien installer. Le timer
  `inflexion-restic-backup` (04:00 UTC) envoie `/data/coolify/backups` sur
  la Storage Box (restic, 7 j / 4 sem / 6 mois). **À vérifier le 26/09
  après 04:05** : le dump ourouler est dans l'instantané.
- **P2 — préprod créée.** Environnement `preprod` du projet Coolify
  `ourouler`, avec :
  - l'application `ourouler-api-preprod`, qui **suit `main`** : chaque merge
    y arrive, et plus en prod ;
  - une base `ourouler-db-preprod`, vide ;
  - le domaine `preprod-…`, en mode hébergé et sans variable personnelle.
  Le déroulé type devient : merge dans `main` → préprod → rejeu → poussée sur
  `prod` à un moment choisi.
- **P3 — référence capturée** sur `b8c390d`, hors dépôt, sur la machine du
  mainteneur :
  - commandes : `sortie --json`, `boucle --distance 60 --json` et
    `calibrer --velo RCR` ;
  - calibration RCR : **CdA 0,378, MAE 3,5 %**, le point fixe de chaque lot ;
  - `sortie` et `boucle` suivent la météo du moment : on les compare peu
    après, ou sur les champs hors prévision.

**Lots du §5, état au 25/09/2026, 21 h** : tout est mergé dans `main`, et la prod
tourne en **v0.9.6**.

| Fait | PR |
|---|---|
| Plan et décisions, tests portables, CI (0a), contrat d'API (0c) | #30, #34, #31, #33 |
| Rétro-changelog, étiquettes `v0.1.0` → `v0.9.6` | #32 |
| Correctifs en prod : 0.9.4, 0.9.5, 0.9.6 | #35, #37, #39 |
| **0b** : sorties de référence (CLI et API) | #46 |
| **0b bis** : trous du filet comblés d'après la relecture Fable (calibration, hébergé, avertissements, texte, carte, horloge) | #48 |
| README réécrit (relu par Fable), démarche et guide | #42, #38 |
| ARCHITECTURE, CONTRIBUTING, SECURITY, AGENTS, CLAUDE.md réduit (+ `CLAUDE.local.md` local) | #44, #43, #45 |
| Brut du chantier rangé dans `docs/journal/`, tel quel | #47 |
| Backlog : l'heure de la séance du jour ; le consentement sur les données | #36, #41 |

**Reste avant l'ouverture**, dans l'ordre :
1. 0d : fichiers de compatibilité ;
2. garde réseau pour tous les tests ;
3. job gitleaks et `.gitleaksignore` ;
4. 0f : répétition du retour arrière, avec le mainteneur ;
5. **lot 1** : contrat d'imports en constat ;
6. **lot 2** : règles ruff ;
7. une source unique de version (`/sante` et `--version` disent encore `0.0.1`) ;
8. la purge des commentaires historiques (Q4), à commencer par `config.example.toml`, `front/README.md` et `deploiement/api/README.md` ;
9. **une recette BRouter** : sans elle, `boucle` et `sortie` sont inaccessibles à un nouveau venu ;
10. l'anonymisation de `docs/journal/` (lieux et chiffres, sans toucher au ton) ;
11. `front/.vite/deps/` retiré du dépôt ;
12. le nettoyage des branches ;
13. réglages GitHub : protection de `main` et signalement privé des failles.
    **Impossibles tant que le dépôt est privé** avec un compte gratuit
    (réponse de l'API : « Upgrade to GitHub Pro or make this repository
    public »), et le signalement privé n'existe que pour les dépôts publics.
    Décision du mainteneur (25/09/2026) : **à revoir à la fin de la
    restructuration complète** (lots 3 à 14), puis le jour J, juste après le
    passage en public :
    - un ruleset sur la branche par défaut : PR obligatoire, vérifications
      `python`, `front` et `image`, force-push bloqué ;
    - Settings → Advanced Security → Private vulnerability reporting →
      Enable.

**Verdict Fable sur le filet (après #48)** : il suffit pour les lots 3 et 4. Pour les lots 5 à 11, chaque lot a désormais une référence qui dépend de ce qu'il déplace. Restent hors filet : les comptes réels en base (lot 5), la calibration lancée par l'API (lot 7), P3 (lot 8), le double chemin (lot 11) et le front (lot 14).

**Appris en livrant les correctifs :**
- un redéploiement coupe le service environ 20 s (503) ;
- une suite `pytest` s'est bloquée une fois pendant plus de 25 min, sur un conteneur Postgres de test resté démarré : à surveiller en CI, où un délai maximal par job s'impose ;
- un agent a qualifié de « préexistant » un test cassé par son propre lot. La règle est donc de **toujours rejouer le test sur `main` avant d'accepter ce verdict**.

**Backlog ajouté** : dans l'assistant d'accueil, une clé Intervals refusée
affiche un message technique (« vérifier [intervals] api_key et
athlete_id »), en haut de l'écran.

**Écarts mesurés par la première CI** (Linux, Python 3.12, TZ=UTC) :
- 11 tests verts sur Mac échouaient, dont 8 qui supposaient le fuseau de
  Paris et 2 références flottantes relevées sur macOS (écart de 1e-15) ;
- un **trou de la règle absolue 1** : `*.gpx` n'ignorait pas un `.GPX` sous
  Linux. Corrigé en #34.
- **Défaut en prod, trouvé par ricochet et vérifié dans le conteneur** :
  - le conteneur est en UTC, sans `TZ` ;
  - `meteo/commande.py` lit une heure sans fuseau dans le fuseau du système ;
  - un invité qui demande 09:00 reçoit donc la météo de 11:00, heure de
    Paris ;
  - dans la même famille : `date.today()` près de minuit, et l'horodatage de
    la carte et du rapport ;
  - **pansement en prod le 25/09 à 17:14 : version 0.9.4** (#35).
    `TZ=Europe/Paris` dans le compose, poussé sur `prod`, et redéployé avec
    l'accord du mainteneur. Le conteneur est à l'heure de Paris, et `/sante`
    et le 401 sont vérifiés. C'est le premier déploiement par la branche
    `prod` ;
  - le vrai correctif, un fuseau explicite passé au cœur, relève de la
    règle 2 et viendra après le gel.

**Gel et branches garées.** Aucune fonctionnalité ne part pendant le
chantier. Trois branches sont poussées sur origin et ne sont pas mergées ;
on les rebase après les lots qui les touchent :
- `analyser-parcours` (3 commits) : analyse d'un GPX existant ; ajoute des
  routes API, une commande CLI et un écran. Elle a été relue et testée en
  image.
- `q67-sans-brut` (5 commits) : en mode hébergé, plus aucun fichier
  d'activité brut conservé. Elle touche `activites/cache.py`,
  `physique/calibration.py` et `api/taches_fond.py`, et **recouvre les
  lots 7 et 8**. Elle n'a pas encore été testée en image. **Question
  tranchée** : elle passe **après** la restructuration, recodée ou
  rebasée sur la nouvelle structure (lots 7 et 8).
- `backlog-admin` (1 commit, doc seule).

**À faire à la fin de la restructuration complète** (décisions du
mainteneur, 25/09/2026 ; rien avant) :
- **Retirer `.claude/` du dépôt** (5 définitions d'agents et
  `settings.json`) : il reste en place tant que la restructuration s'en sert,
  puis il part dans l'espace local du mainteneur. Les contributeurs
  n'auront qu'`AGENTS.md` ; vérifier alors que `CLAUDE.md` et
  `tests/test_agents_md.py` ne le citent plus.
- Les réglages GitHub (protection de `main`, signalement privé des
  failles), voir le point 13 du §0.

**Préalable à la 0.10.0** (« analyser un parcours », dans `main` et en
préprod, pas en prod) : sans FTP, l'écran d'analyse affiche le message de la
ligne de commande (« donner --puissance W ou --vitesse-a-plat KMH »,
`physique/commande.py:1216`). À remplacer, dans le front, par une phrase
pour le cycliste avant de pousser en prod.

**Constat du lot 14 (26/09/2026)** : le schéma OpenAPI ne décrit **aucune
réponse réussie** (les 200 sont des objets vides) ; les types du front ne
sont donc vérifiés que pour les requêtes. Déclarer des modèles de réponse
fait partie du lot 11.

## 0 bis. Phase de nettoyage — avant toute nouvelle fonctionnalité

Demandée par le mainteneur le 26/09/2026 : « avant de repartir sur les
features, un vrai nettoyage : worktrees, documents de travail, vérification
des documents, du README, du changelog… Pas de nouvelle feature, pas de
nouveau code ; des retouches seulement pour finir ou nettoyer (code mort,
doublons, artefacts de test), et le contenu et la documentation. Le dépôt
doit être vu comme l'état de l'art. »

**Règles de la phase.** Aucun changement de comportement : les sorties de
référence, la compatibilité et le contrat d'API passent sans régénération
(sauf l'openapi si un texte de description change, relu comme tel). P3 sur les
vraies données après chaque lot qui touche `src/`. Au plus deux agents à la
fois. Chaque lot est une PR, mergée si la CI est verte.

| Lot | Contenu | Critère de fin | Modèle |
|---|---|---|---|
| N0 | **Mise en prod 0.10.0** (API en `ancien`) : rejeu complet en préprod, P3, poussée sur `prod`, étiquette. Rien ne change pour les invités hors les correctifs déjà dans `main` | prod saine, invitation rejouée en prod, étiquette `v0.10.0` | moi |
| N1 | **Environnement de travail** : worktrees morts, branches locales et distantes déjà mergées (garder `main`, `prod`, les étiquettes, les branches garées nommées), stash, conteneurs et images de test orphelins, dossiers temporaires | `git worktree list` et `git branch -r` ne montrent que l'utile ; liste de ce qui a été supprimé | moi |
| N2 | **Code mort et doublons** : fonctions, constantes et modules jamais appelés (analyse AST + vérification à la main), aides dupliquées entre modules, réexports résiduels, `noqa` et exceptions qui ne servent plus, `TODO`/`FIXME` périmés | chaque suppression justifiée en une ligne ; suite complète et références vertes | Opus |
| N3 | **Tests et fixtures** : tests morts ou en double, fixtures inutilisées, artefacts (fichiers écrits par des tests, dossiers `~`), docstrings de tests qui citent d'anciens chemins, scripts `tests/validation/` (garder, documenter ou retirer), exceptions ruff des tests tranchées | nombre de tests et temps de suite rapportés avant/après ; rien de ce qui mord n'est retiré (mutation de contrôle) | Opus |
| N4 | **Commentaires historiques** (décision Q4) : dates, numéros de lot, « le mainteneur a dit », citations → le pourquoi durable en une phrase, renvoi `docs/journal/questions/…#Qnn` quand utile ; docstrings périmées | `grep` des marqueurs historiques vide dans `src/` (hors renvois assumés) ; aucune ligne de code changée | Opus, par paquets |
| N5 | **Documentation** : README, ARCHITECTURE (carte réelle après les lots 3–14), CONTRIBUTING, SECURITY, AGENTS, `doctrine_architecture.md` relue et mise à jour, guides de `docs/`, READMEs de `front/` et `deploiement/`, `CHANGELOG.md` (entrée « Non publié » rédigée du point de vue du cycliste). Chaque commande, option, chemin et lien cité existe (test) | aucune affirmation fausse sur le code ; liens et commandes vérifiés | Opus |
| N6 | **Documents de travail** : le plan d'ouverture et la préparation des sprints passent dans `docs/journal/` une fois clos ; `docs/` ne garde que le relu ; index de `docs/` | arborescence de `docs/` lisible par un inconnu | Sonnet |
| N7 | **Métadonnées et outillage** : `pyproject.toml` (description, licence, URLs, classifiers), `front/package.json`, `.gitignore` relu, délai maximal par job en CI (leçon du blocage de 25 min), format du code (`ruff format` : décider et appliquer ou documenter) | CI verte, métadonnées complètes | Sonnet |
| N8 | **Relecture « état de l'art »** en regard extérieur (Fable) sur tout le dépôt : ce qu'un développeur expérimenté qui découvre le dépôt trouverait brouillon, faux ou daté ; corrections, puis seconde passe | verdict écrit ; points bloquants corrigés | Fable, puis Opus |
| N9 | **Gestes de fin avec le mainteneur** : retrait de `.claude/`, branches garées, réglages GitHub (au passage en public) | fait avec lui | lui + moi |

Ordre : N0 et N1 d'abord (sans risque), puis N2 et N3 en parallèle, N4, puis
N5 et N6 (la documentation décrit le code nettoyé), N7, N8, N9.

**État au 26/09/2026.** N0 fait (0.10.0 en prod, étiquette `v0.10.0`). N1
fait. N2 mergé (#83), N3 (#84), N6 (#85), N5 (#86), N4 (#87 : 1 523 lignes
d'historique → 69, AST identique hors docstrings, P3 identique), N7 (#88 :
métadonnées, CI à délai maximal et actions épinglées, Dependabot). N8 : la
relecture Fable (30 constats : 17 A, 5 B, 8 C) juge le dépôt « au-dessus de
la moyenne » ; les 17 A sont faits (#99 accueil et documentation, #100 tests
sans histoire de sprint), Dependabot groupé (#101), `ruff format` appliqué une
fois et vérifié en CI (#103). Reste N9, avec le mainteneur : les 8 questions C
de la revue et les gestes de fin.

**Backlog issu de N8 (classe B, changements visibles)** : en-têtes HTTP de
sécurité sur l'API ; limitation des tentatives de connexion (avant
l'ouverture publique du service) ; conteneur de l'API hors root (avec
migration des droits du volume, essai en préprod) ; bascule du chemin API
vers `nouveau` puis retrait d'`api/adaptateur.py` ; fusion des petites
conversions dupliquées (`_flottant`, `_instant`…) dans le noyau, sous tests
de caractérisation. Restent aussi pour après la phase, hors comportement : les chaînes affichées qui portent encore de
l'historique (aide de `Volets.tsx`, `CODES_PANNE`), à traiter comme un
changement visible ; l'écart doctrine ↔ code sur la conservation des fichiers
bruts après export (Q67), à trancher par le mainteneur.

## 1. Diagnostic (mesuré)

- **Taille réelle.** 89 fichiers Python pour 41 019 lignes. Docstrings et
  commentaires en font 45 %, il reste donc ~22 560 lignes de code.
  - 108 fonctions dépassent 50 lignes, 16 dépassent 100, 4 dépassent 200 :
    `sortie/carte.py:_page_jour` (333), `api/application.py:creer_application`
    (277), `boucle/candidates.py:generer` (213), `sortie/commande.py:executer`
    (209).
  - Complexité modeste : 15 fonctions au-dessus de C901 = 10, la pire à 20.
  - 5 109 tests (~76 000 lignes) ; `docs/` fait ~19 000 lignes.
- **D1 — Rien d'automatique ne protège la prod.**
  - Pas de CI : tests et ruff ne tournent que sur la machine de l'agent.
  - Coolify redéploie `main` à chaque merge. Or un redéploiement **tue les
    tâches en cours** : les imports et calibrations des invités vivent en
    mémoire (`api/taches_fond.py:188`, un seul processus uvicorn).
  - Il n'existe aucune préproduction.
- **D2 — L'API appelle la ligne de commande.** `api/adaptateur.py` fabrique un
  `argparse.Namespace`, appelle `executer(...)` et capture ce qui s'imprime,
  sous un verrou global. Le cycle api ↔ cli est réel : `api/vues.py:39`
  importe `cli.profil_json`, et `cli.py` fait 22 imports différés de `api`.
- **D3 — Les `commande.py` font tout.** Dans `sortie/commande.py` (2 494
  lignes), `boucle/commande.py` et `physique/commande.py`, on trouve argparse,
  orchestration, écritures disque, rendu texte et JSON. Des modules du domaine
  importent ces fichiers de commande.
- **D4 — Huit paquets en un seul cycle** : config, activites, connecteurs,
  meteo, boucle, physique, seance, apprentissage. La cause est surtout le
  rangement : `boucle/trace.py` est un type de base mal placé ; `config.py`
  importe `seance` ; `physique/calibration.py` importe le cache, `Config` et
  un objet de transfert du connecteur d'archive ; `boucle/candidates.py`
  reçoit un client BRouter. **Le modèle physique n'est pas pur.**
- **D5 — Un retour arrière peut casser sur les données.** Les index SQLite
  refusent un schéma plus récent que le code ; `calibration.json` n'est lue
  qu'en version 1 ; les migrations Postgres ne vont que dans un sens.
- **D6 — Pas de filet de caractérisation, et des tests collés aux chemins
  internes.** Les tests contiennent 662 imports internes, 28 imports de noms
  privés et **203** `monkeypatch`.
- **D7 — Le code est illisible de l'extérieur.** ~600 lignes renvoient à un
  lot, une question ou une date, 269 citent le mainteneur ; il n'y a ni
  ARCHITECTURE ni CONTRIBUTING.

## 2. Architecture cible

Les dépendances ne vont que de haut en bas.

| Couche | Contenu | Peut importer |
|---|---|---|
| 5. Entrées | `cli`, `commandes` (lot 10 : du `Namespace` à la `Demande`), `api`, `config` (lecture TOML et environnement) | tout |
| 4. Rendu | `rendu/` : texte, JSON (le contrat), carte HTML | 0–3 |
| 3. Cas d'usage | `services/` : sortie, boucle, meteo, calibrer, comparer, seance, apprendre, inventaire, comptes — une `Demande` en entrée, un résultat en sortie, sans argparse ni print | 0–2 |
| 2. Adaptateurs | `connecteurs/` (HTTP) ; `stockage/` (cache, lecteurs FIT/GPX/TCX, routes connues, calibrations, cache des prévisions) | 0–1 |
| 1. Domaine pur | `physique` < `meteo` < `boucle` < `seance` < `sortie` | 0 et le domaine placé avant |
| 0. Noyau | erreurs, propriétaire, `trace`, `activite`, types météo, modèle de séance et zones, `profil` | bibliothèque standard |

**Le modèle physique pur** reçoit des `Parametres`, une `Trace`, des
échantillons de vent, des activités déjà lues et une masse. Il rend des
simulations, des ajustements et des validations. Il n'importe ni `Config`, ni
cache, ni `Path`, ni `httpx`, ni `boucle` ; numpy est permis.

**La règle se vérifie** par `tests/test_architecture.py`, sur le modèle de
`test_invariants.py` : imports lus dans l'arbre syntaxique (imports différés
compris), table des arêtes permises, et **exceptions datées** qui font échouer
le test quand elles expirent ou qu'elles ne servent plus.

## 3. Prérequis avant tout lot (correction bloquante de Fable)

- **P1 — Découpler merge et déploiement.** Coolify suit une branche `prod`
  (ou une étiquette), et `main` ne déploie plus. On déploie par paquets, à un
  moment choisi, et pas à chaque PR.
- **P2 — Une préproduction.** Un second service Coolify : même image,
  Postgres vide, volume vide, domaine à part. C'est là qu'on éprouve chaque
  paquet de lots avant `prod`.
- **P3 — La règle absolue 4 dans chaque lot.** `ourouler sortie --json` et
  `ourouler boucle --json` tournent sur la vraie config du mainteneur, et la
  sortie se compare à celle d'avant le lot. Le résultat reste hors dépôt.
  C'est le seul filet qui voie BRouter, AROME, le géocodage et la
  calibration réels.
- **P4 — La sauvegarde Postgres de Coolify** existe et a été restaurée une
  fois. Un `pg_dump` manuel ne compte pas comme sauvegarde.
- **Réglage GitHub du mainteneur** : protection de `main`, qui interdit tout
  merge si la CI est rouge. L'agent ne fait pas ce réglage.

## 4. Filets

- **0a — CI** (Sonnet, spécification fermée) :
  - `uv sync --frozen` sous **Python 3.12**, la version de l'image ;
  - `ruff`, `pytest` et `npm run verifier` ;
  - construction de `deploiement/api/Dockerfile` et démarrage **sans
    Postgres** : `/sante` doit répondre 200 ;
  - `openapi.json` identique à celui figé en 0c.
- **0b — Sorties de référence** (Opus conçoit, Fable contre-lit la
  couverture), dans `tests/caracterisation/` :
  - scénarios : meteo, boucle, sortie, calibrer, comparer, seance,
    inventaire, les 10 routes API principales et leurs échecs ;
  - données : fixtures synthétiques et réponses réseau rejouées ;
  - comparaison **après normalisation** (`json.loads` puis
    `dumps(sort_keys)`), pas octet pour octet ;
  - horloge injectée aux **28 endroits** qui l'appellent (19 fichiers) ;
  - arrondi à la sérialisation pour `calibrer` seulement (numpy) ;
  - régénération par `--regenerer-golden` seulement, et toute différence de
    référence dans une PR se relit comme un changement de comportement ;
  - critère : stables sur 3 passages, et une mutation volontaire les fait
    échouer.
- **0c — Contrat d'API figé** : `openapi.json` trié, en snapshot (Sonnet).
- **0d — Fichiers de compatibilité** (Opus) : échantillons synthétiques de
  chaque format persisté, que le code actuel relit. Aucun lot de
  restructuration ne touche un format persisté, une constante de version ou
  une migration. Côté Postgres, on ajoute d'abord et on retire plus tard,
  jamais de `DROP` ni de `RENAME`.
- **0f — Répétition réelle du retour arrière Coolify** (le mainteneur, aidé) :
  redéployer le commit précédent, restaurer la sauvegarde. La procédure est
  écrite.
- **Garde réseau pour tous les tests**, pas seulement ceux de l'API
  (aujourd'hui `tests/api/conftest.py:88`) : un `monkeypatch` déplacé ne
  doit pas pouvoir partir sur Internet.
- **Scan de secrets** (gitleaks) sur tout l'historique, en CI.
- ~~0e (tolérer les formats futurs)~~ : **retiré** du chantier. Il changeait
  un comportement en prod avant les filets, et « tolérer un SQLite plus
  récent » est indécidable pour l'ancien code. À reprendre après l'ouverture.

## 5. Version resserrée — ce qui doit être fait avant l'ouverture

Le plan complet représente 35 à 40 PR, sur 4 à 6 sprints, dont une quinzaine
en Opus + Fable. C'est trop pour ouvrir bientôt. **Avant l'ouverture :**

1. P1 à P4, puis 0a, 0b, 0c, 0d, 0f, la garde réseau et le scan de secrets.
2. **Lot 1 — contrat d'imports en mode « constat »** (Opus) : chaque
   violation actuelle devient une exception datée. La dette devient une
   liste publique, honnête, qui ne peut plus que baisser.
3. **Lot 2 — règles ruff** (Haiku) : C901 ≤ 12, PLR0912 ≤ 15, PLR0915 ≤ 50,
   **PLR0917** (au plus 6 positionnels), et les dépassements actuels listés
   en exceptions datées.
4. **Décision sur l'historique git**, à prendre en premier (voir §7), avec le
   scan de secrets.
5. ARCHITECTURE.md, CONTRIBUTING.md, SECURITY.md, README pour un visiteur, et
   le tri des documents (§7). Plus **AGENTS.md**, la source unique pour tout
   agent de code, puisque Codex et Cursor le lisent aussi :
   - contenu : installation, commandes de vérification, carte des paquets et
     sens des dépendances, règles absolues publiques, pièges connus, façon
     de proposer une PR ; une page, en français ;
   - `CLAUDE.md` se réduit à `@AGENTS.md`, plus les sous-agents de
     `.claude/agents/` ;
   - les consignes personnelles du mainteneur partent vers son
     `~/.claude/CLAUDE.md` ;
   - pour Cursor, au plus une règle d'une ligne qui renvoie à AGENTS.md
     (vérifier la doc Cursor avant de l'écrire) ;
   - un test vérifie que les chemins et les commandes cités existent.
6. Nettoyage des branches : 59 branches locales, beaucoup de worktrees
   d'agents morts.

7. **Lot final — README réécrit, la démarche préservée** (demandé par le
   mainteneur le 25/09/2026 : « c'est pas un readme, c'est une journée de
   pensée… y a des trucs intéressants… faudrait pas perdre ça »). Il vient
   en dernier, parce qu'il renvoie aux documents du point 5.
   - `README.md` : un vrai README, une page à une page et demie. Ce que fait
     l'outil, une capture, un démarrage rapide, le paragraphe en anglais
     (Q7), puis des liens.
   - `docs/demarche.md` : comment le projet s'est construit (sprints,
     agents, relectures adverses), les réfutations mesurées, la validation
     rétrospective, ce qui reste possible. Il recueille, **anonymisée**, la
     substance des contrats et relectures de sprint qui sortent du dépôt
     (§7) : rien de ce qui s'y est appris ne se perd.
   - `docs/guide_ligne_de_commande.md` : le mode d'emploi de la ligne de
     commande et les limites connues, repris de l'actuel README.
   - Écrit par Opus, puis contre-lu par Fable avec un regard extérieur :
     « un inconnu comprend-il en 30 secondes ? ».
   - Critères : aucune section de l'ancien README ne disparaît sans avoir
     été reprise (table ancien → nouveau dans la PR) ; tout lien vérifié
     par le test d'AGENTS.md ; aucune donnée personnelle.

**Après l'ouverture**, sprint par sprint, dans la cadence à deux sprints du
projet : les lots de restructuration ci-dessous.

## 6. Lots de restructuration (après l'ouverture)

Critère commun à chaque lot : sorties de référence identiques, openapi
identique, tests verts, P3 identique sur les vraies données, et les
exceptions du contrat d'imports qu'il rend inutiles retirées.

| Lot | Objectif | Modèle | Risque |
|---|---|---|---|
| 3 | Créer `noyau/` (trace, activite, erreurs, propriétaire) avec des réexports | **Haiku**, sur une table `ancien → nouveau` fournie par Opus et un script qui réécrit imports **et cibles de monkeypatch** ; critère : zéro `setattr` visant un module de réexport | faible |
| 4 | Types météo, `profil`, modèle de séance et zones dans le noyau | Haiku, même garde-fou | faible |
| 5 | Casser api ↔ cli (profil_json dans `rendu/` ; comptes, invitation et retrait dans `services/comptes`) | **Opus** (authentification en prod) | moyen |
| 6 | Sortir le rendu de `sortie/commande.py`, puis de `boucle` et `physique/commande` | **Opus** (203 monkeypatch, constantes de module) | moyen |
| 7 | `stockage/calibrations` : le domaine reçoit des `Parametres`, plus un chemin | Opus | moyen |
| 8 | **Physique pure** : `calibration.py` coupé entre calcul et `services/calibrer` ; calibration RCR du mainteneur identique au dernier chiffre | Opus, contre-lecture Fable | moyen |
| 9 | Protocole `Routeur` ; découpage de `generer` | Opus | moyen |
| 10 | argparse sort des commandes : la `Demande` vient de `cli` | Opus | moyen |
| 11 | L'API appelle le service et le rendu, sans `Namespace` ni capture stdout. **Double chemin** : `OUROULER_API_CHEMIN=ancien|nouveau|double` ; en `double`, les deux tournent, l'ancien répond et l'écart est journalisé ; une semaine en préprod, puis en prod | Opus, contre-lecture Fable | **élevé** |
| 12 | Découper les fonctions trop longues, une PR par fonction | Opus | moyen |
| 13 | Scinder `api/routes.py` par domaine, avec un test qui résout chaque chemin littéral par `TestClient` (l'ordre d'enregistrement compte) | **Opus** | faible |
| 14 | Front : un seul point d'accès au réseau, types vérifiés contre openapi, `App.tsx` découpé | Sonnet (accès réseau), Opus (types) | faible |
| fin | Retrait des réexports | Haiku | faible |

## 7. Normes, documents et ouverture

**Seuils Python**, mesurés en lignes de code (sans docstrings ni
commentaires) :
- fonction : 60 lignes au plus ; fichier : 600 lignes au plus ;
- complexité C901 : 12 au plus ;
- les exceptions sont déclarées avec une date et un lot, et un test échoue à
  expiration.

**Commentaires.** Le code garde le pourquoi durable. L'historique (dates,
lots, « le mainteneur a dit ») part dans `docs/decisions/`, cité par
identifiant.

**Front.** Seul `api/client.ts` appelle `fetch`, un composant fait 300 lignes
au plus, les types sont vérifiés contre openapi, chaque écran a son test.

**Tri des documents :**
- **Public** : README, ARCHITECTURE, CONTRIBUTING, SECURITY, la doctrine
  relue, `api_contrat`, `services_externes`, `geocodage`, `meteo_vent`, les
  README de `deploiement/`.
- **Anonymisé** : `questions_mainteneur.md` devient `docs/decisions/` (les
  identifiants Q sont gardés, le code les cite) ; `cadrage`.
- **Hors dépôt** : contrats et relectures de sprint, plan de sprints,
  discovery, `.claude/`.

**Historique git — à décider en premier.** Mesuré :
- l'identifiant d'athlète Intervals apparaît 7 fois dans `git log --all -p` ;
- on y trouve des coordonnées réelles et 20 messages de commit qui citent
  la ville du mainteneur ;
- aucune trace GPS ni aucune config réelle n'a jamais été commitée.

Anonymiser les documents actuels ne sert à rien si l'historique reste. Trois
options :
- (a) garder l'historique tel quel ;
- (b) le réécrire avec `filter-repo` : tous les identifiants de commit
  changent ;
- (c) **ouvrir un nouveau dépôt public à partir d'un commit unique**, l'actuel
  restant privé comme archive.

**Décidé : (a).** Conséquence assumée : l'identifiant d'athlète, les
coordonnées approchées et les noms de lieux restent lisibles dans les anciens
commits. Le tri des documents garde son intérêt pour la lisibilité du dépôt,
mais plus pour la confidentialité. Deux choses restent **obligatoires avant
de rendre le dépôt public** :
- gitleaks passé sur tout l'historique, pour qu'aucun secret actif n'y reste
  (une clé trouvée se révoque ; ne pas se contenter de l'effacer) ;
- le nettoyage des branches : ne publier que `main`, `prod` et les
  étiquettes.

**Jour J** : CI obligatoire et verte, gitleaks propre, contrat d'imports vert,
documents en place, installation qui marche depuis un conteneur vierge,
Coolify branché sur `prod`, aucune URL de prod ni nom d'invité dans les
documents.

## 7 bis. Versions et journal des changements

Demandé par le mainteneur le 25/09/2026 : « faire un changelog et penser à une
numérotation de version pour faire propre, et tenter si possible le
rétro-changelog des versions passées ».

**Numérotation — proposition, à valider (question 9).** SemVer en `0.x`, tant
que l'API et les formats persistés peuvent encore bouger :
- **mineure** (`0.9.0`) : un sprint livré en production ;
- **correctif** (`0.9.1`) : un correctif en production entre deux sprints.
  Par exemple, le 25/09, « brancher Intervals avec la seule clé » ;
- **`1.0.0`** : le jour de l'ouverture publique, avec une API et des formats
  stabilisés.

**Une seule source de vérité** : la version de `pyproject.toml`, que
`/systeme` et `ourouler --version` exposent et que l'écran affiche dans
Réglages. La version de `front/package.json` suit, vérifiée par un test.
Chaque déploiement en `prod` (P1) porte une étiquette git `vX.Y.Z` ; le
retour arrière vise une étiquette, plus un commit.

**`CHANGELOG.md`** au format *Keep a Changelog*, en français et du point de
vue du cycliste : Ajouté, Modifié, Corrigé, Retiré, Sécurité.
- Chaque PR ajoute sa ligne sous « Non publié », et la CI (0a) le vérifie :
  une PR sans ligne de changelog est refusée, sauf étiquette
  `sans-changelog`.
- Au déploiement, « Non publié » devient la version.

**Rétro-changelog.** Reconstruire les versions passées à partir de
l'historique : un sprint vaut une version mineure.
- `0.1.0` à `0.8.0` : les sprints 1 à 8, via les PR #1 à #24 ;
- `0.9.0` : le sprint 9 (PR #26) ;
- `0.9.1` à `0.9.x` : les correctifs et petites livraisons du 25/09
  (#27, #28, #29…).

Chaque entrée est rédigée depuis les titres et descriptions de PR et les
clôtures de sprint de `plan_sprints_agents.md`, **sans données personnelles**
(ni lieux ni chiffres du mainteneur). Les étiquettes rétroactives se posent
sur les commits de merge.
- **Qui fait quoi** : Haiku extrait la liste des PR et des commits de merge ;
  Opus rédige les entrées.
- **Lot** : il vient **avant l'ouverture**, juste après 0a, puisque la CI
  vérifie ensuite le changelog. Il ne touche pas au code, donc il est sans
  risque pour la prod.
- **Si l'option (c) de l'historique est retenue** (nouveau dépôt depuis un
  commit unique) : le rétro-changelog devient la seule trace publique du
  passé, et les étiquettes restent dans le dépôt privé.

## 8. Questions au mainteneur (répondues le 25/09/2026, voir §0)

1. Historique git : (a), (b) ou (c) ? C'est la décision qui conditionne tout
   le tri des documents.
2. Branche `prod` et préproduction Coolify (P1, P2) : acceptées ? (Règle
   absolue 7 : un nouveau service Coolify est une installation.)
3. GitHub Actions et protection de `main` : acceptées ?
4. Les commentaires qui racontent l'historique : les purger, ou les garder
   avec un renvoi vers `docs/decisions/` ?
5. Nouvelles dépendances de développement (import-linter ou test maison,
   gitleaks, ESLint, freezegun) ?
6. Geler les fonctionnalités pendant les filets, ou en faire un sprint dans
   la cadence ?
7. Langue du projet public : tout en français, ou un README anglais ?
8. L'URL de prod et la page du jour peuvent-elles apparaître dans le dépôt ?
9. Numérotation : SemVer `0.x` (un sprint = une mineure, un correctif = un
   patch, `1.0.0` à l'ouverture), et le rétro-changelog `0.1.0` → `0.9.x` :
   d'accord ?

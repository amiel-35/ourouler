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
| 5. Entrées | `cli`, `api`, `config` (lecture TOML et environnement) | tout |
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
   le tri des documents (§7).
6. Nettoyage des branches : 59 branches locales, beaucoup de worktrees
   d'agents morts.

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
- on y trouve des coordonnées `48.11xx` et 20 messages de commit qui citent
  Rennes ;
- aucune trace GPS ni aucune config réelle n'a jamais été commitée.

Anonymiser les documents actuels ne sert à rien si l'historique reste. Trois
options :
- (a) garder l'historique tel quel ;
- (b) le réécrire avec `filter-repo` : tous les identifiants de commit
  changent ;
- (c) **ouvrir un nouveau dépôt public à partir d'un commit unique**, l'actuel
  restant privé comme archive.

**Jour J** : CI obligatoire et verte, gitleaks propre, contrat d'imports vert,
documents en place, installation qui marche depuis un conteneur vierge,
Coolify branché sur `prod`, aucune URL de prod ni nom d'invité dans les
documents.

## 8. Questions au mainteneur

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

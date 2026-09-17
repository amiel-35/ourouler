# Doctrine d'architecture — ourouler (« où rouler ? »)

Nom : **ourouler** (paquet Python, commande et dépôt GitHub `amiel-35/ourouler`),
validé par le mainteneur le 13/09/2026. Ce
document fixe les choix structurants et leurs raisons. On le modifie par
décision explicite du mainteneur, jamais par dérive. `CLAUDE.md` en est le
résumé opérationnel pour les agents ; en cas de doute, c'est ce document qui
fait foi. Le besoin d'origine est dans `docs/cadrage.md`.

## 1. Principes

**Un seul mainteneur, premier utilisateur.** Amiel est seul sur ce projet et
en est le premier utilisateur. Son besoin passe avant toute généralisation :
un lot n'est fini que lorsqu'une commande tourne sur *ses* vraies données.

**Le cœur ne sait pas où il tourne.** La bibliothèque ne lit jamais un chemin
en dur, une variable d'environnement, un fichier `~/.config` : elle reçoit un
objet de configuration (point de départ, cycliste, vélos, clés) et des
connecteurs. La ligne de commande est la seule couche qui sait lire un fichier
de configuration. Raison : le graal à terme est un service hébergé où d'autres
cyclistes se créent un compte, renseignent leur profil et importent leurs
données. On ne le construit pas maintenant, mais on s'interdit ce qui le
rendrait impossible : un profil utilisateur est une donnée, pas une constante.

**Il y aura un front web, à terme (confirmé par le mainteneur le
12/09/2026).** La cible finale est un service hébergé avec une interface
web : compte, profil (puissance, point de départ habituel, vélos), import de
données, et les mêmes résultats que la CLI (météo par direction, boucle,
sortie du jour). D'où, dès aujourd'hui : le cœur est appelable sans fichier
ni environnement, chaque commande sait rendre du JSON, et la CLI n'est qu'un
adaptateur parmi d'autres — l'API web en sera un second, le moment venu.
Ordre imposé : d'abord la CLI qui couvre le besoin du mainteneur, ensuite
l'API, enfin le front. Ni API ni front ne s'écrivent avant que le sprint
« séance ↔ terrain » ait tourné sur ses vraies sorties.

**Les données et les clés restent chez l'utilisateur.** Rien de personnel
dans le dépôt : ni fichier d'activité, ni coordonnées, ni clé d'API. Le
`.gitignore` ignore par défaut tout `.fit`/`.gpx`/`.tcx` et tout
`config*.toml` ; seules les fixtures de test nommées sont réintégrées.

**Ne rien affirmer sans mesure.** Le modèle physique est validé sur des
sorties qu'il n'a pas vues (erreur de temps par sortie, rapportée). La météo
prévue est comparée au réel après coup, par modèle. Deux modèles météo qui
divergent donnent un indice de confiance, jamais une moyenne.

**Chaque module tient debout seul.** `meteo`, `boucle`, `inventaire` sont
utilisables indépendamment, avant que la boucle séance ↔ terrain existe.
C'est aussi ce qui rend chaque lot démontrable.

**Natif et simple d'abord.** Pas de service payant obligatoire, pas de base
de données serveur, pas de file de messages. Tout tourne sur un Mac ou un
petit Linux. Ce projet préfère 50 lignes évidentes à 20 lignes malignes.

## 2. Vue d'ensemble

```
        sources                       cœur (bibliothèque)                sorties
┌─────────────────────┐   ┌──────────────────────────────────┐   ┌──────────────────┐
│ FIT / GPX / TCX     │──▶│ lecteur unique → Activite         │   │ tableau météo    │
│ Intervals.icu (API) │──▶│ connecteurs → cache local        │   │ GPX de la boucle │
│ Open-Meteo (AROME…) │──▶│ meteo : couronne de points/heure │──▶│ résumé + tenue   │
│ BRouter/GraphHopper │──▶│ boucle : candidates, coûts       │   │ Garmin Connect   │
│ (plus tard)         │   │ physique : calibration par vélo  │   │ (plus tard)      │
└─────────────────────┘   │ sortie : séance ↔ terrain        │   └──────────────────┘
                          └──────────────────────────────────┘
```

Un seul paquet Python, `src/ourouler/`, avec des sous-modules par domaine.
La CLI (`ourouler <sous-commande>`) n'est qu'un adaptateur au-dessus.

## 3. Stack

- **Python ≥ 3.12**, `uv` + `pyproject.toml`, layout `src/`. Typage par
  annotations et `dataclasses` ; pas de Pydantic tant qu'il n'y a pas d'API.
  L'API est arrivée (lot F1, 17/09/2026) : **FastAPI et Pydantic entrent, et
  ne dépassent pas `src/ourouler/api/`**, où Pydantic ne décrit que les corps
  de requête. Le cœur reste en dataclasses, et un `ourouler` installé sans
  l'extra `api` n'en voit rien.
- **CLI** : `argparse` (stdlib). Sortie texte lisible, `--json` quand un
  autre programme doit consommer.
- **HTTP** : `httpx`. Chaque connecteur expose une fonction qui prend un
  client injectable, pour que les tests n'appellent jamais le réseau.
- **Fichiers d'activité** : `fitdecode` (FIT), `gpxpy` (GPX), `xml.etree`
  (TCX). Un seul modèle `Activite` en sortie des trois lecteurs.
- **Cache local** : un dossier (`~/.cache/ourouler` par défaut, configurable)
  avec les fichiers bruts tels que reçus, et un index **SQLite** (stdlib)
  pour retrouver une activité par date, vélo, source. Pas d'ORM.
- **Configuration** : un fichier **TOML** (`tomllib`, stdlib) lu par la CLI
  seulement ; `config.example.toml` versionné, le vrai fichier ignoré.
- **Tests** : `pytest`, fixtures synthétiques ou anonymisées dans
  `tests/fixtures/`. Réseau interdit dans les tests. **Lint** : `ruff`.
- **Licence** : MIT.

## 4. Repo et structure

```
bike-routing/
├── CLAUDE.md                  ← résumé opérationnel pour les agents
├── doctrine_architecture.md   ← ce document
├── .claude/agents/            ← fiches des agents (superviseur, devs, testeur, relecteur)
├── docs/                      ← cadrage, plan de sprints, contrats de sprint, questions
├── config.example.toml
├── src/ourouler/
│   ├── cli.py                 ← argparse, lecture de la config, appel du cœur
│   ├── config.py              ← dataclasses Config/Depart/Velo/Cycliste, chargement TOML
│   ├── activites/             ← modèle Activite, lecteurs fit/gpx/tcx, cache SQLite
│   ├── connecteurs/           ← intervals.py (et plus tard garmin, strava-export…)
│   ├── meteo/                 ← openmeteo.py (client), couronne.py (directions), rapport
│   ├── boucle/                ← S2 : moteurs de tracé, coûts, GPX
│   ├── physique/              ← S3 : modèle puissance→vitesse, calibration
│   └── seance/                ← S4 : séance ↔ terrain, tenue, résumé
└── tests/
```

Les dossiers `boucle/`, `physique/`, `seance/` n'existent qu'à partir de
leur sprint : pas de squelette vide « pour plus tard ».

## 5. Données de l'utilisateur

- **Fenêtre d'historique : à partir du 1ᵉʳ décembre 2023.** Avant, plusieurs
  vélos, roues et positions rendent la calibration non fiable. La date est un
  paramètre de configuration, pas une constante.
- **Calibration par vélo et par période.** Chaque activité est rattachée à un
  vélo (champ d'équipement Intervals, ou règle manuelle) ; les paramètres
  physiques (masse, CdA, roulement) sont estimés par vélo, et une période peut
  être scindée si la validation le demande.
- **Le dénominateur commun est le fichier.** Quelle que soit la source
  (Intervals, Garmin, Strava, Wahoo), on stocke le FIT/GPX/TCX brut et on le
  relit avec le même lecteur. Un connecteur ne fait que rapatrier des
  fichiers et des métadonnées.

## 6. Sources externes et leurs limites, telles que connues au cadrage

| Source | Usage | Contrainte |
|---|---|---|
| Open-Meteo | prévisions par point, AROME HD 1,3 km en France (`meteofrance_arome_france_hd`), ICON/ECMWF ailleurs ou en second avis | gratuit sans clé, usage non commercial, plusieurs points par appel ; AROME ne donne pas de probabilité de pluie |
| Intervals.icu | séance du jour, liste des activités, **téléchargement du FIT d'origine** | clé d'API personnelle (Settings → Developer), auth basique `API_KEY:<clé>` |
| BRouter | boucles, profils `fastbike-*`, GPX natif | auto-hébergé (Java ou Docker), données OSM à télécharger |
| GraphHopper | mode boucle par distance | API hébergée gratuite à petit volume, clé |
| Strava | **pas** de génération d'itinéraire par API ; export GPX de ses propres itinéraires | import GPX manuel |
| Garmin Connect | envoi du parcours (S5) | pas d'API publique ; accès à cadrer avec le mainteneur (le jeton `~/.config/ha/garmin-token` est un jeton Home Assistant, pas Garmin) |

## 7. Ce qu'on refuse, et pourquoi

- **Home Assistant comme dépendance.** HA consommera les résultats plus tard ;
  le projet ne l'importe jamais et ne lit jamais sa configuration.
- **Une base serveur, un compte, une API web** tant que la CLI ne couvre pas
  le besoin du mainteneur. On garde la porte ouverte (principe « le cœur ne
  sait pas où il tourne », chapitre 10), on ne la franchit pas.
- **Un mot de passe stocké chez nous, un jour.** L'authentification sera
  déléguée (Google, Apple) ; voir chapitre 10.
- **Copier une clé ou un jeton dans le dépôt, un test ou une fixture.** Sans
  exception.
- **Une moyenne de modèles météo.** Le désaccord est une information, on
  l'affiche.
- **Un service payant obligatoire.** Une option payante (Solcast, GraphHopper
  au-delà du gratuit) reste une option, jamais le chemin nominal.
- **Les routes déjà roulées comme critère de choix.** Elles sont un
  **instrument de mesure**, jamais un critère. Mots du mainteneur, 16/09/2026 :
  « les routes connues et leur fréquence, c'est pour du test. Ce que je fais,
  c'est des routes sûres : ça permet de comparer les critères de BRouter à ma
  réalité dans ses choix, pas du tout de privilégier mes choix. »

  C'est la règle du sprint 3, et sa raison technique est écrite dans
  `apprentissage.routes.BaseRoutes.part_connue` : pénaliser l'inconnu
  condamnerait d'avance toute direction jamais explorée, alors que le
  mainteneur a lui-même demandé d'aller « tester des routes sud sud-ouest pour
  voir ».

  La raison de fond est plus forte que la raison technique : **le jour où les
  routes connues entrent dans le score, l'outil cesse de mesurer quoi que ce
  soit.** Il renvoie au cycliste ses propres habitudes en prétendant les avoir
  trouvées, et toute validation rétrospective devient circulaire — on
  vérifierait que le modèle prédit bien ce qu'on lui a donné comme cible.

  Conséquence pratique : la part connue s'**affiche**, sert d'**étalon** pour
  valider un critère nouveau (les poids du terrain au sprint 3, la densité de
  marqueurs urbains au sprint 5), et n'entre **ni dans une note, ni dans un
  tri, ni dans une sélection**. Une erreur de ce genre a été faite et
  rattrapée dans le cadrage de L5.3, le 16/09/2026.

## 10. Cible hébergée et multi-utilisateur — ce qu'on décide maintenant

Décision du mainteneur (12/09/2026) : la cible est **multi-utilisateur**,
avec **authentification déléguée** (Google d'abord, Apple ensuite — plus
contraignant), et il faut y penser tôt parce que ça a des implications
techniques (base de données, stockage, secrets) qu'on ne rattrape pas.
Rien de ce chapitre ne se construit avant que la CLI couvre le besoin du
mainteneur ; tout ce chapitre s'applique déjà à la manière d'écrire le cœur.

### 10.1 Ce qui s'applique dès aujourd'hui (coût nul, dette évitée)

- **L'unité de tout est le profil, pas la machine.** `Config` (départ,
  cycliste, vélos, clés, fenêtre d'historique) est *le* profil d'un
  utilisateur. Toute fonction du cœur reçoit ce profil ; aucune ne suppose
  qu'il n'y en a qu'un. Quand l'hébergé arrivera, `Config` gagnera un
  identifiant d'utilisateur et sera chargée depuis la base au lieu d'un TOML :
  le cœur ne le verra pas.
- **Les dépôts de données sont des interfaces.** Le cache d'activités
  (fichiers bruts + index) est aujourd'hui un dossier et un SQLite ; en
  hébergé ce sera un stockage d'objets et Postgres. Le cœur parle à une
  classe `Cache` (ajouter, contient, lister, chemin), jamais à un chemin ni
  à une requête SQL. Le schéma de l'index local est écrit avec une colonne
  « propriétaire » en tête, pour que la migration soit un déplacement, pas
  une réécriture.

  **Fait le 17/09/2026**, après constat que la règle n'était appliquée qu'à
  `routes_connues.sqlite`, et encore : la colonne y était sans qu'aucune
  requête ne la filtre. Les trois dépôts locaux (`index.sqlite`,
  `archive_meteo.sqlite`, `routes_connues.sqlite`) portent désormais la
  colonne, elle entre dans **l'identité** (clé primaire ou index unique), et
  chaque requête de lecture comme d'écriture porte la clause. Trois points
  décidés à cette occasion :

  - **Le propriétaire entre au constructeur du dépôt, et nulle part ailleurs**
    (`Cache(dossier, proprietaire=…)`) : exactement la position du `Path`, que
    la ligne de commande fournit déjà et que le cœur ignore. Aucune fonction
    du cœur ne le prononce ; en hébergé, c'est la couche web qui construira le
    dépôt avec l'identifiant de l'utilisateur authentifié.
  - **L'unicité d'une activité devient `(propriétaire, source,
    id_externe|contenu)`.** Sans le propriétaire, deux utilisateurs ayant la
    même activité Intervals — sortie en groupe, compte partagé — ne se
    seraient pas vu refuser l'écriture : le `ON CONFLICT DO UPDATE` aurait
    écrasé la ligne du premier, en silence.
  - **L'archive météo porte la colonne avec la valeur `partage`**, pas un
    identifiant d'utilisateur : la mutualisation voulue plus bas dans ce
    paragraphe est intacte, simplement **écrite** au lieu d'être déduite d'une
    absence de colonne — et il n'y a pas de liste d'exceptions à tenir pour
    l'invariant, or une liste d'exceptions se remplit toute seule.

  Un invariant de `tests/test_invariants.py` reconstitue le SQL de chaque
  appel `execute` du cœur et échoue si une requête neuve oublie la clause ;
  seules les fonctions préfixées `_migrer` en sont dispensées, puisqu'elles
  fabriquent la colonne.
- **Les clés d'API externes sont des données du profil, secrètes.** Clé
  Intervals, plus tard GraphHopper, Garmin : jamais en clair dans un log,
  une erreur, un JSON de sortie (`ourouler config --json` les masque déjà).
  En hébergé : chiffrées au repos, une par utilisateur.
- **Chaque commande rend du JSON.** C'est la future réponse d'API, et donc
  le contrat du front.
- **Les quotas externes se pensent par service, pas par utilisateur.**
  Open-Meteo gratuit est réservé à un usage non commercial et limité par
  adresse IP : un service hébergé devra soit passer sur l'offre payante,
  soit mutualiser (cache des prévisions par maille et par heure, partagé
  entre utilisateurs). Le module météo recevra une couche de cache
  injectable devant le client HTTP **au premier sprint de l'hébergé** —
  l'exigence « dès le sprint 2 » écrite au cadrage a été ajournée par le
  superviseur le 13/09/2026 (relecture du sprint 2, point 9) : en CLI,
  chaque utilisateur appelle depuis sa propre adresse, et un `boucle` à 5
  candidates coûte ~10 **requêtes** Open-Meteo + 12 BRouter, sans enjeu de
  quota.

  **Correction du 16/09/2026 : requêtes et appels décomptés ne sont pas la
  même chose, et le chiffre ci-dessus confondait les deux.** Open-Meteo
  décompte **un appel par coordonnée**, pas par requête : grouper plusieurs
  points dans une requête économise du temps réseau, jamais du quota. La
  ligne « ~50 appels pour un `meteo` à 25 points × 2 modèles » appliquait
  déjà la bonne règle ; celle du `boucle` l'avait oubliée.

  Le vrai chiffre, pour une `sortie` à 5 candidates sur une boucle de 70 km
  échantillonnée tous les 5 km (`meteo_trace.PAS_DEFAUT_M`) : 14 points par
  requête, `1 + 2 × candidates` requêtes, soit **~150 appels décomptés**. À 8
  candidates, ~240.

  Conséquence pratique, mesurée le 16/09/2026 : un agent a vu passer un
  `HTTP 429 — Minutely API request limit exceeded` et en a conclu qu'il ne
  fallait pas augmenter le nombre de candidates. **Le diagnostic était faux** :
  240 appels restent sous les 600 par minute, et la limite n'a été atteinte
  qu'en enchaînant des essais. Une commande par jour coûte ~150 appels sur
  10 000. Le 429 était un artefact de test, pas une limite produit.

  Les leviers réels, si le poste devient contraignant : espacer les
  échantillons (`PAS_DEFAUT_M`), mettre le cache, et ne pas demander le
  second avis météo pour chaque candidate. **Pas « grouper les appels »** :
  c'est déjà fait et ça ne change rien au décompte.
  Le client Open-Meteo est déjà injectable, ce qui suffit à poser le cache
  plus tard sans toucher au cœur.

  Ordres de grandeur (question du mainteneur, 12/09/2026) : le gratuit
  tolère environ 10 000 appels par jour et par adresse IP (5 000 par heure,
  600 par minute), et un `ourouler meteo` à 25 points × 2 modèles compte
  pour ~50 appels — soit ~200 consultations par jour depuis un seul
  serveur, tous utilisateurs confondus. En CLI, chacun appelle depuis sa
  propre adresse : aucun sujet. En hébergé, l'escalade décidée : (1) cache
  mutualisé par maille (~2 km) et par heure dès le premier jour ; (2) offre
  API payante d'Open-Meteo (quelques dizaines d'euros par mois, usage
  commercial autorisé, rien à exploiter) au premier signe de saturation ;
  (3) auto-hébergement d'Open-Meteo (open source, Docker, rapatrie lui-même
  les données ouvertes Météo-France / ICON / ECMWF) seulement si le volume
  ou la souveraineté des données l'exigent.

### 10.2 Ce qu'on décide maintenant, pour construire plus tard

- **Authentification : jamais de mot de passe chez nous.** Le principe ne
  bouge pas ; le chemin, si — **révisé le 16/09/2026 par le mainteneur**, au
  moment d'ouvrir le cycle UX (`docs/ux/cycle_ux_contrat.md`).

  **V1 : entrée modérée, par lien à usage unique.** Une demande d'accès, que
  le mainteneur valide à la main, puis un e-mail d'invitation (Brevo)
  portant un lien de connexion ; ensuite l'utilisateur peut poser une
  **passkey** (WebAuthn) pour ne plus dépendre de sa boîte mail. Deux
  raisons de préférer ça à ce qui était écrit ici avant : la **modération
  est native** — le sprint 8 veut qu'on invite des copains, et par-dessus
  une connexion Google il aurait fallu construire une liste d'attente — et
  l'écran d'entrée nous appartient, au lieu d'être celui d'un tiers.

  **V2 : Google, puis Apple, en plus et non à la place.** OpenID Connect
  avec ses contraintes propres côté Apple — compte développeur payant, clé
  privée et identifiant de service, relais d'adresse e-mail privée,
  obligation d'Apple si une app iOS propose d'autres connexions sociales.
  Bibliothèque au moment venu (Authlib ou équivalent), jamais une
  implémentation maison d'OAuth.

  **Ce qui ne change pas dans les deux cas** : l'identité interne est un
  identifiant opaque ; l'e-mail est une donnée du profil, pas une clé
  primaire (un utilisateur peut changer de fournisseur, ou passer du lien
  magique à Google) ; et **une passkey n'est jamais le seul moyen d'entrer**
  — le lien à usage unique reste le filet, parce qu'une passkey se perd avec
  l'appareil ou le trousseau qui la synchronise.
- **Base de données hébergée : PostgreSQL, dès le premier jour de
  l'hébergé, jamais SQLite.** Même raison qu'ix-presenter : le coût d'un
  Postgres sur Coolify est quasi nul, le coût d'une migration SQLite →
  Postgres tombe toujours au mauvais moment. Migrations SQL numérotées, SQL
  nu, pas d'ORM. Le SQLite local de la CLI reste : c'est un cache, pas la
  base.
- **Fichiers bruts (FIT/GPX/TCX) : stockage d'objets**, pas la base ni le
  disque du serveur — un utilisateur actif représente vite des centaines de
  fichiers. Cible naturelle : un stockage S3-compatible (Hetzner Object
  Storage ou équivalent), un préfixe par utilisateur.
- **Isolation des données : par utilisateur, vérifiée côté serveur** à
  chaque requête, jamais seulement côté front. Aucune requête sans clause
  de propriétaire.
- **RGPD par construction** : export de toutes ses données et suppression
  du compte (profil, fichiers, calibrations, clés) disponibles dès la
  première version hébergée ; pas de suivi d'audience ; hébergement en
  Europe.
- **API avant front.** L'API expose ce que la CLI sait déjà rendre en
  JSON ; le front la consomme. Le front ne parle jamais directement au cœur.

### 10.3 Ce qui a été décidé depuis, et ce qui ne l'est toujours pas

**Tranché le 16/09/2026** par le mainteneur, à l'ouverture du cycle UX
(`docs/ux/front_contrat.md`) : le front sera **React**, l'API vient **avant**
le front, et les comptes après. **Livré le 17/09/2026** (lot F1) : le cadre
web est **FastAPI**, avec uvicorn pour le servir — c'est la seule dépendance
lourde qu'ouvre l'API, et elle ouvre avec elle la porte que `§3` laissait
entrebâillée (« pas de Pydantic tant qu'il n'y a pas d'API »). Le cœur, lui,
reste en dataclasses : Pydantic ne sert qu'aux corps de requête.

Ce que la livraison ajoute à ce chapitre, et qu'il faut lire avec lui : l'API
n'implémente rien, elle appelle les mêmes fonctions que la ligne de commande
et rend leur JSON ; l'isolation par propriétaire est écrite **dès maintenant**
dans la forme des dépôts, avec un invariant qui la garde ; et l'attente d'une
génération est semi-synchrone, avec une durée annoncée qui dit si elle est
mesurée. Le contrat complet est dans `docs/ux/api_contrat.md`.

**Toujours pas décidé** : l'hébergement exact (Coolify sur Hetzner reste le
candidat naturel) et la tarification éventuelle. Ces choix se prendront au
point de repriorisation qui ouvrira l'hébergé.

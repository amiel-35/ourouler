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
│   └── sortie/                ← S4 : séance ↔ terrain, tenue, résumé
└── tests/
```

Les dossiers `boucle/`, `physique/`, `sortie/` n'existent qu'à partir de
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
  candidates coûte ~10 appels Open-Meteo + 12 BRouter, sans enjeu de quota.
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

- **Authentification : déléguée, jamais de mot de passe chez nous.** OpenID
  Connect avec Google en premier fournisseur ; Apple (« Sign in with Apple »)
  en second, avec ses contraintes propres — compte développeur Apple payant,
  clé privée et identifiant de service, relais d'adresse e-mail privée,
  obligation d'Apple si une app iOS propose d'autres connexions sociales.
  L'identité interne est un identifiant opaque ; l'e-mail est une donnée du
  profil, pas une clé primaire (un utilisateur peut changer de fournisseur).
  Bibliothèque au moment venu (Authlib ou équivalent), jamais une
  implémentation maison d'OAuth.
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

### 10.3 Ce qu'on ne décide pas encore

Le cadre web (FastAPI ou autre), le front (framework ou HTML autonome comme
ix-presenter), l'hébergement exact (Coolify sur Hetzner est le candidat
naturel), la tarification éventuelle. Ces choix se prendront au point de
repriorisation qui ouvrira l'hébergé, avec une CLI qui marche sous les yeux.

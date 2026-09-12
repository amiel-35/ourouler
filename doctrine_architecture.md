# Doctrine d'architecture — ourouler (« où rouler ? »)

Nom de travail : **ourouler** (paquet Python et commande). À renommer si le
mainteneur trouve mieux ; le dépôt GitHub s'appelle `bike-routing`. Ce
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
  sait pas où il tourne »), on ne la franchit pas.
- **Copier une clé ou un jeton dans le dépôt, un test ou une fixture.** Sans
  exception.
- **Une moyenne de modèles météo.** Le désaccord est une information, on
  l'affiche.
- **Un service payant obligatoire.** Une option payante (Solcast, GraphHopper
  au-delà du gratuit) reste une option, jamais le chemin nominal.

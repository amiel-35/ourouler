# Sorties de référence (filet 0b)

Ces fichiers figent ce que `ourouler` répond **aujourd'hui**, avant la
restructuration du plan d'ouverture (`docs/ouverture_plan.md`, §4 et §6).
Chaque lot de restructuration doit les laisser identiques.

## La règle

**Une différence avec une référence est un changement de comportement.** Elle
se relit dans la PR comme telle : le diff de la référence dit ce qui a changé
pour le cycliste ou pour le front. On ne régénère jamais par réflexe pour
« faire passer » un test.

## Régénérer (après relecture du diff, seulement)

    uv run pytest tests/caracterisation tests/api/test_caracterisation_api.py --regenerer-golden

Sans `--regenerer-golden`, les tests comparent ; avec, ils réécrivent et se
marquent « ignorés ».

## Ce que couvre chaque fichier

Ligne de commande (`test_caracterisation_cli.py`, par `ourouler.cli.main`,
toujours avec `--json`) — chaque fichier fige code de sortie, sortie JSON,
sortie d'erreur, GPX écrits (empreinte), cartes HTML écrites (présence) et
journal des appels aux services :

| fichier | scénario |
|---|---|
| `cli_meteo.json` | `meteo` : couronnes, deux modèles en désaccord |
| `cli_boucle.json` | `boucle --distance 30` : candidates, coûts de route, météo le long du tracé |
| `cli_sortie.json` | `sortie` : séance posée sur les boucles, propositions, tenue, GPX et carte |
| `cli_seance.json` | `seance` : un jour avec séance, un jour sans |
| `cli_inventaire.json` | `inventaire --importer` puis relecture, deux vélos rattachés par période |
| `cli_calibrer.json` | `calibrer --velo RCR` sur huit sorties fabriquées (flottants à 6 chiffres) |
| `cli_comparer.json` | `comparer --velos RCR BMC` |
| `cli_refus.json` | cinq refus : code 2, message en français, aucun appel réseau |

API (`tests/api/test_caracterisation_api.py`, application complète sans client
injecté) — chaque fichier fige statut, type de contenu, corps et journal réseau :

| fichier | routes |
|---|---|
| `api_systeme.json` | `GET /systeme` |
| `api_profil.json` | `GET /profil`, et 401 sans session |
| `api_zones.json` | `GET /profil/zones`, `POST /profil/zones/apercu`, 422 |
| `api_profil_intervals.json` | `GET /profil/intervals`, et 409 clé absente |
| `api_geocodage.json` | `GET /geocodage`, 422 adresse vide |
| `api_meteo.json` | `GET /meteo`, 422 horizon, 429 quota météo |
| `api_vent_depart.json` | `GET /vent-depart` |
| `api_seances.json` | `GET /seances`, `GET /seances/{jour}` avec et sans séance, 422, 409 |
| `api_sorties.json` | `POST /sorties`, son GPX, 404, 422, 401, 429 quota |
| `api_boucles.json` | `POST /boucles`, 422 |
| `api_inventaire.json` | `GET /inventaire` |
| `api_calibrations.json` | `GET /calibrations` |

`openapi.json` (filet 0c) vit ici aussi ; son test est
`tests/api/test_contrat_openapi.py`.

## Comment c'est tenu stable

- **Réseau rejoué** au niveau de `httpx.Client` (`outils_caracterisation.py`) :
  Open-Meteo, son archive, BRouter, Intervals.icu et le géocodage répondent des
  données synthétiques ; tout autre hôte fait échouer le test, et une garde
  coupe les sockets (fixture `garde_reseau` d'`outils_caracterisation.py` pour
  la ligne de commande — pas de `conftest.py` de plus sous `tests/` —,
  `tests/api/conftest.py` pour l'API).
- **Horloge figée** au mardi 8 septembre 2026, 09:00 à Paris, dans tous les
  modules `ourouler.*`, sans toucher à `src/` ; fuseau posé par la fixture
  `fuseau_de_paris`.
- **Normalisation** : JSON relu puis trié ; chemins temporaires remplacés par
  `<TMP>`, UUID par `<UUID>`, jetons hexadécimaux longs (noms de fichiers du
  cache, identifiants de génération) par `<HEX>`, durées mesurées de l'API
  par `<CHRONO>`.
- **Flottants** : égalité à 1e-12 près en relatif (écart de plateforme
  macOS/Linux) ; `calibrer` seul est arrondi à 6 chiffres significatifs
  (numpy).

Aucune donnée personnelle : départ en mer, clés et identifiants inventés.

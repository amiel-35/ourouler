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

Ligne de commande (`test_caracterisation_cli.py`, par `ourouler.cli.main`).
Chaque scénario est lancé **deux fois** — `--json`, puis sans (le texte que
lit le cycliste, figé ligne à ligne) — et fige code de sortie, sortie
standard, sortie d'erreur, fichiers écrits ou modifiés (empreintes) et
journal des appels aux services :

| fichier | scénario |
|---|---|
| `cli_meteo.json` | `meteo --heure-depart` : couronnes, deux modèles en désaccord |
| `cli_meteo_heure_courante.json` | `meteo` **sans date** : la fenêtre vient de l'horloge figée |
| `cli_boucle.json` | `boucle --distance 30` : candidates, coûts de route, météo le long du tracé |
| `cli_sortie.json` | `sortie` : séance posée sur les boucles, propositions, tenue, GPX et carte |
| `cli_seance.json` | `seance --jour` : un jour avec séance, un jour sans |
| `cli_seance_du_jour.json` | `seance` **sans date** : « aujourd'hui » vient de l'horloge figée |
| `cli_inventaire.json` | `inventaire --importer` puis relecture, deux vélos rattachés par période |
| `cli_calibrer.json` | `calibrer --velo RCR` sur huit sorties fabriquées, **le `calibration.json` écrit**, puis `sortie --velo RCR` qui le relit (`modele_physique: calibration (RCR)`) — flottants à 6 chiffres |
| `cli_comparer.json` | `comparer --velos RCR BMC` |
| `cli_refus.json` | cinq refus : code 2, message en français, aucun appel réseau |

Fichiers écrits : un GPX par l'empreinte de ses octets ; une carte HTML par
l'empreinte de son texte normalisé (chemins, UUID, jetons), **une seule
ligne retirée** : `<p class="horodatage">Page générée le JJ/MM/AAAA à
HH:MM.</p>` (`rendu/carte_jour.py`). L'horloge étant figée, elle serait stable ;
elle est retirée pour qu'un lot qui déplace la lecture de l'horloge de la
carte ne casse pas l'empreinte de toute la page.

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
| `api_heberge.json` | **compte hébergé en succès** : `PATCH /profil` sur le socle commun, `POST /sorties` 200, `GET /calibrations` (propriétaire ≠ `local`) |
| `api_heberge_import.json` | compte hébergé : `POST /activites/import` (202), `GET /activites/import/{id}` jusqu'à la fin, puis inventaire et calibrations du compte |
| `api_avertissement.json` | `GET /meteo`, second modèle en panne (500) : `avertissements` non vide, avec son `code` |

Le « compte hébergé » est `SessionUnCompte` : un propriétaire fixe en mode
hébergé, sur un `SocleTOML(proprietaire=None)` comme en service, **sans
Postgres**. Les comptes réels (base, invitations, sessions, retrait) restent
**hors filet** : le lot 5 se vérifie par ses propres tests
(`tests/comptes/`, `tests/api/test_invitation_commande.py`) et par la préproduction.

`openapi.json` (filet 0c) vit ici aussi ; son test est
`tests/api/test_contrat_openapi.py`.

`resolution_routes.json` (lot 13) fige l'ordre d'enregistrement des routes et,
pour chaque chemin littéral et chaque méthode, le point d'entrée que le
routeur choisit ; son test est `tests/api/test_resolution_routes.py`.

## Ce que chaque lot du §6 a pour se vérifier

Pour chaque lot, au moins une référence **dépend** de ce qu'il déplace
(mutation de contrôle mesurée le 25/09/2026 : la casser fait passer au rouge
les tests nommés).

| lot | couvert par | reste hors filet |
|---|---|---|
| 3–4 (noyau, types) | toutes les références ; le filet n'importe aucun module déplacé (`test_le_filet_ne_depend_que_de_surfaces_stables`) | — |
| 5 (api ↔ cli, comptes) | `api_profil`, `api_zones`, `api_heberge*` (propriétaire ≠ `local`) | les comptes réels en base (authentification, invitation, retrait) |
| 6 (rendu hors de `sortie/commande.py`, `boucle`, `physique/commande`) | sorties **texte** de chaque scénario, empreinte de la carte HTML (mutations `sortie.rendre_texte → ""`, `carte_jour._page_jour → <html></html>` : rouges) | la mise en page de la carte au-delà de l'empreinte (un écart se voit, il ne se lit pas dans le diff) |
| 7 (`stockage/calibrations`) | `cli_calibrer` : `calibration.json` écrit, puis relu par `sortie` (mutations `ecrire_calibration` muette et `lire_calibration → None` : rouges) ; `api_heberge*` pour le chemin par compte | la calibration lancée **par l'API** (`POST /calibrations`, tâche de fond) : ses tests `test_api_calibration.py` |
| 8 (physique pure) | `cli_calibrer`, `cli_comparer` (6 chiffres significatifs) | « identique au dernier chiffre » sur la calibration RCR du mainteneur : c'est P3, sur les vraies données, hors dépôt |
| 9 (`Routeur`, `generer`) | `cli_boucle`, `cli_sortie`, `api_boucles`, `api_sorties` (journal BRouter compris) | — |
| 10 (argparse sort des commandes) | tous les scénarios CLI, dont les refus (code 2) | — |
| 11 (l'API sans `Namespace`) | toutes les références API, dont `api_avertissement` (mutation `adaptateur.avertissements_de → ()` : rouge) | le **double chemin** : `OUROULER_API_CHEMIN` (lue par `api/exploitation.py`) ; `preparer` la laisse passer (`VARIABLES_GARDEES`) pour que le lot 11 rejoue le filet sur chaque valeur, contre les mêmes références |
| 12 (fonctions trop longues) | toutes | — |
| 13 (`api/routes.py` scindé) | toutes les références API, `openapi.json`, `resolution_routes.json` | — |
| 14 (front) | — | le front n'est pas dans ce filet |

## Comment c'est tenu stable

- **Surfaces stables seulement.** Le filet n'importe de `ourouler` que
  `ourouler.cli`, la fabrique de l'application et les objets qu'elle prend
  en paramètre (`IMPORTS_AUTORISES`), et aucun module `test_*`. Les données
  fabriquées (séance Intervals, anneaux BRouter, sorties TCX) sont **copiées**
  dans `donnees_synthetiques.py` et `rejeu_intervals_evenement.json`, à
  l'octet près identiques à celles des modules de test d'où elles viennent.
- **Réseau rejoué** au niveau de `httpx.Client` (`outils_caracterisation.py`) :
  Open-Meteo, son archive, BRouter, Intervals.icu et le géocodage répondent des
  données synthétiques ; tout autre hôte fait échouer le test, et une garde
  coupe les sockets (fixture `garde_reseau` d'`outils_caracterisation.py` pour
  la ligne de commande — pas de `conftest.py` de plus sous `tests/` —,
  `tests/api/conftest.py` pour l'API). `Rejeu.en_panne(hote, statut, **params)`
  fait tomber un service choisi.
- **Horloge figée** au mardi 8 septembre 2026, 09:00 à Paris, dans tous les
  modules `ourouler.*`, sans toucher à `src/` : chaque attribut de module qui
  vaut `datetime.date`, `datetime.datetime` ou le module `datetime` lui-même,
  **quel que soit son nom** (`date`, `_date`, `import datetime as _dt`), est
  remplacé. Le contrôle (`test_l_horloge_est_bien_figee`) balaie
  `sys.modules` : plus aucune vraie horloge dans `ourouler.*`, et au moins
  `MODULES_FIGES_MINIMUM` modules touchés. Ce qui échappe au gel : un
  `import datetime` **dans une fonction**, et `time.time()` — les références
  `meteo`/`seance` sans date passent alors au rouge. Fuseau posé par la
  fixture `fuseau_de_paris`.
- **Normalisation** : JSON relu puis trié ; chemins temporaires remplacés par
  `<TMP>`, UUID par `<UUID>`, jetons hexadécimaux longs (noms de fichiers du
  cache, identifiants de génération) par `<HEX>`, durées mesurées de l'API
  par `<CHRONO>` ; dans le dépôt d'un import, l'état au moment du 202
  (dépend de la vitesse de la machine).
- **Flottants** : égalité à 1e-12 près en relatif (écart de plateforme
  macOS/Linux) ; un entier ne vaut **pas** un flottant (`30` devenu `30.0` est
  un changement de contrat JSON). `calibrer` et la `sortie` qui le suit sont
  arrondis à 6 chiffres significatifs (numpy). Réserve : l'empreinte du GPX
  de cette `sortie` porte les paramètres calibrés bruts ; si une autre
  plateforme la fait bouger sans autre écart, c'est le dernier chiffre de
  numpy, pas un comportement.

Aucune donnée personnelle : départ en mer, clés et identifiants inventés.

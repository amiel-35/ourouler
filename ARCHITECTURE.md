# Architecture d'ourouler

Ce document décrit le code **tel qu'il est**, la structure **visée**, et
l'écart entre les deux, sans l'enjoliver. Les chiffres ont été mesurés sur
`main` au moment de l'écriture (arbre syntaxique Python, pas une estimation).
La doctrine qui justifie ces choix est dans `doctrine_architecture.md` ; le
plan détaillé de remise en ordre est dans `docs/ouverture_plan.md`.

## 1. Vue d'ensemble

ourouler répond à la question d'un cycliste équipé d'un capteur de puissance :
« je vais rouler ; où va-t-il pleuvoir, et quel parcours de la bonne durée
porte la séance du jour ? ». Il rend une météo par direction, des boucles
notées, la séance posée sur le tracé, une tenue conseillée, un GPX et une
carte de vérification.

**Deux entrées :**

- **La ligne de commande** `ourouler` (`src/ourouler/cli.py`, argparse) :
  `inventaire`, `meteo`, `boucle`, `sortie`, `seance`, `calibrer`, `simuler`,
  `comparer`, `routes`, `geocoder`, `config`, et les commandes
  d'administration des comptes (`inviter`, `invitations`, `reinitialiser`,
  `retirer`). Texte lisible par défaut, `--json` en option.
- **L'API HTTP** (FastAPI, `src/ourouler/api/`) lancée par `ourouler api`,
  et le **front** React/TypeScript (`front/`) qu'elle sert une fois construit.
  Le front ne parle qu'à `/api/v1`.

**Sources externes**, chacune derrière un connecteur qui reçoit un client
HTTP injectable :

| Source | Rôle | Module |
|---|---|---|
| Open-Meteo (prévisions) | pluie et vent par point et par heure, deux modèles | `src/ourouler/meteo/openmeteo.py` |
| Open-Meteo (archives) | le vent d'une sortie passée, pour la calibration | `src/ourouler/connecteurs/openmeteo_archive.py` |
| BRouter | itinéraires et boucles, tags OSM des tronçons | `src/ourouler/connecteurs/brouter.py` |
| Intervals.icu | activités, fichier FIT d'origine, séance planifiée | `src/ourouler/connecteurs/intervals.py` |
| Base Adresse Nationale, puis Nominatim en repli | une adresse tapée devient des candidats | `src/ourouler/connecteurs/geocodage.py` |

**Stockage :**

- un **cache local** : les fichiers d'activité bruts tels que reçus, plus des
  index SQLite (`src/ourouler/activites/cache.py`, archive météo, routes
  connues), chacun avec une colonne « propriétaire » dans son identité ;
- un **cache mutualisé des prévisions** en hébergé
  (`src/ourouler/meteo/cache_previsions.py`), dont la clé ne porte aucun
  identifiant de compte ;
- **PostgreSQL**, en hébergé seulement, pour les comptes, invitations et
  sessions (`src/ourouler/api/base_de_donnees.py`,
  `src/ourouler/api/migrations/`).

**Deux modes**, choisis par la variable `OUROULER_MODE`, lue dans
`src/ourouler/api/exploitation.py` et nulle part ailleurs :

- **personnel** : un cycliste, sa machine, son fichier TOML ; pas de base,
  pas de comptes ;
- **hébergé** (le défaut, parce que c'est le mode qui refuse) : plusieurs
  cyclistes, des sessions par cookie, un profil par propriétaire
  (`src/ourouler/api/depots.py`). Le fichier de configuration du serveur
  n'y porte **aucune** section personnelle (`depart`, `cycliste`, `velos`,
  `intervals`) : l'application refuse de démarrer sinon.

## 2. Carte des paquets, aujourd'hui

103 fichiers Python, 42 455 lignes (docstrings et commentaires compris) sous
`src/ourouler/`.

| Paquet | Rôle | Fichiers principaux (lignes) |
|---|---|---|
| `cli.py` | argparse (le parseur), lecture de la config, `--adresse-depart`, codes de sortie, appel des commandes | `cli.py` (1 432) |
| `commandes/` | une entrée par sous-commande (lot 10) : lit le `Namespace`, construit la `Demande` du service et son `Contexte` depuis la `Config`, appelle le service puis le rendu, et imprime ; `executer_depuis_namespace` sert encore l'API jusqu'au lot 11 | `sortie.py` (253), `boucle.py` (159), `physique.py` (151), `comparer.py` (130) |
| `config.py` | `Config` (le profil du noyau plus `ParametresCache`) ; chargement TOML et environnement | `config.py` (886) |
| `noyau/` | types partagés, bibliothèque standard seulement : le tracé `Trace`, le modèle `Activite`, les exceptions communes, la constante du propriétaire local, le modèle de séance et les zones, les types de prévision météo, le profil du cycliste (`Velo`, `Depart`, les paramètres…), les protocoles que le domaine reçoit à la place des clients HTTP (`Routeur`, `SourcePrevisions`, `SourceSeances`) et celui où le connecteur Intervals range ses sorties (`DepotActivites`) | `activite.py`, `trace.py`, `erreurs.py`, `proprietaire.py`, `seance.py`, `zones.py`, `meteo.py`, `profil.py`, `ports.py` |
| `activites/` | lecteur unique FIT/GPX/TCX, cache SQLite, inventaire, import d'archive | `cache.py` (703), `import_archive.py` (526), `lecture.py` (490) |
| `connecteurs/` | clients HTTP : BRouter, Intervals.icu, archives Open-Meteo, géocodage | `brouter.py` (604), `intervals.py` (595), `openmeteo_archive.py` (478) |
| `stockage/` | ce qui s'écrit sur disque et se relit : `calibration.json` (lot 7) ; le cache d'activités, les routes connues et le cache des prévisions y viendront | `calibrations.py` |
| `meteo/` | couronne de points, client de prévisions, rapport par direction, cache mutualisé | `rapport.py` (397), `openmeteo.py` (307) |
| `boucle/` | candidates de boucle, coûts, météo le long du tracé, GPX | `commande.py` (904), `meteo_trace.py` (697), `couts.py` (487), `candidates.py` (446) |
| `physique/` | modèle puissance ↔ vitesse, paramètres d'un vélo (`parametres_velo.py`), calcul de la calibration CdA/Crr (pur depuis le lot 8), ses échantillons dans `echantillonnage.py`, sa validation dans `validation.py`, la détection des sorties en groupe dans `groupe.py` ; `commande.py` porte les cas d'usage `calibrer`, `simuler`, `analyser` | `calibration.py` (1 696), `modele.py` (668), `commande.py` |
| `seance/` | lecteurs ZWO/MRC/Intervals, placement sur le terrain (`placement.py`, son résultat dans `placement_resultat.py`, sa note dans `placement_note.py`, le tracé en pas dans `pas_trace.py`), tenue, écran de FTP (calcul dans `ftp.py`, commande dans `ecran_ftp.py`) | `placement.py` (1 490), `terrain.py` (1 002), `intervals.py` (974), `commande.py` (611) |
| `sortie/` | la séance du jour posée sur une boucle : orchestration, contraste des propositions | `commande.py` (1 305), `contraste.py` (1 198) |
| `apprentissage/` | routes connues : rejouer les sorties passées dans BRouter pour en tirer des poids | `routes.py` (1 122), `commande.py` (451) |
| `geocodage/` | la sous-commande `geocoder` | `commande.py` |
| `rendu/` | ce qu'une entrée montre d'un résultat, sans rien lire ni écrire : le profil en JSON et le masquage des secrets (`profil.py`), l'affichage des commandes de comptes (`comptes.py`), le tableau, le JSON et la page du jour de `sortie` (`sortie.py`, son JSON dans `sortie_json.py`) et de `boucle` (`boucle.py`, son JSON et la fourchette porte à porte dans `boucle_json.py`), la carte HTML (`carte.py`, qui s'appuie sur `carte_dessin.py` pour les couches et le profil, et sur `carte_jour.py` pour la page du jour), le texte et le JSON de `calibrer`, `simuler` et `analyser` (`physique.py`, lot 8) et de `comparer` (`comparaison.py`, réexporté par `physique.py`) et de `routes` (`routes.py`, lot 10) | `sortie.py` (1 293), `carte.py` (1 283), `boucle.py` (1 005), `physique.py` (874), `routes.py`, `profil.py`, `comptes.py` |
| `services/` | cas d'usage sans argparse ni affichage : les comptes de l'hébergé (inviter, lister les invitations, réinitialiser, retirer) ; choisir, lire et calibrer les sorties d'un vélo (`calibrer.py`, lot 8) ; comparer deux vélos (`comparer.py`, lot 10) ; le `Contexte` que reçoit tout service — profil, dossier de cache et fichier de calibration résolus (`contexte.py`, lot 10). Les autres cas d'usage vivent encore dans les `*/commande.py` de leur paquet, sous la même règle | `comparer.py` (610), `calibrer.py`, `comptes.py`, `contexte.py` |
| `api/` | application FastAPI, routes, sessions, comptes, dépôts par propriétaire, quotas, tâches de fond, adaptateur vers la CLI | `comptes.py` (1 095), `depots.py` (988), `application.py` (632), `routes/commun.py` (411), `routes/profil.py` (331) — les routes, un module par domaine sous `routes/` (lot 13) |

Les anciens chemins `boucle/trace.py`, `activites/modele.py`, `erreurs.py`,
`proprietaire.py`, `seance/modele.py` et `seance/zones.py` ne sont plus que
des réexports du noyau, pour un appelant extérieur ; le code du dépôt importe
`ourouler.noyau`, et le lot final les retire. `config.py` réexporte de même
le profil, et `meteo/openmeteo.py` les types de prévision. Depuis le lot 7,
`physique/commande.py` réexporte de même la lecture et l'écriture de
`calibration.json` (`stockage/calibrations.py`) et la `Calibration`. Depuis
le lot 6, `sortie/carte.py` réexporte `rendu/carte.py`.

Depuis le lot 10, argparse est sorti des cas d'usage. Chaque sous-commande
a sa `Demande` (une dataclass, dans le module du service) et un service
`executer(demande, contexte, clients…)` qui rend un résultat sans rien
imprimer ; le `Contexte` porte le profil (`noyau.profil.Profil`, que
`Config` satisfait), le dossier de cache et le fichier de calibration déjà
résolus, et le canal des avertissements. `commandes/<nom>.py` lit le
`Namespace`, appelle le service, puis le rendu, et imprime. Les `*/commande.py`
n'importent plus ni `config` ni `rendu`, et `physique/comparer.py` n'est plus
qu'un réexport de `services/comparer.py`.

Chaque paquet de domaine a son `commande.py` : c'est la sous-commande de la
ligne de commande, et, on le verra, bien plus que ça.

Côté front : `front/src/App.tsx` (841 lignes), 11 écrans dans
`front/src/ecrans/`, un client réseau `front/src/api/client.ts`.

## 3. Ce qui tient déjà, et ce qui le garde

Ces règles sont vérifiées par des tests qui lisent le code source lui-même ;
un changement qui les enfreint fait rougir la CI (`.github/workflows/ci.yml` :
ruff, pytest avec un Postgres jetable, vérification du front, construction de
l'image et démarrage sans Postgres).

| Invariant | Où il est vérifié |
|---|---|
| **Le cœur ne sait pas où il tourne.** Seuls `cli.py`, `config.py` et `api/exploitation.py` lisent l'environnement, `tomllib` ou le dossier de l'utilisateur. | `tests/test_invariants.py` (`test_le_coeur_ne_lit_pas_son_environnement`, `test_le_coeur_n_importe_pas_tomllib`, `test_seul_le_module_d_exploitation_de_l_api_lit_l_environnement`) ; `tests/adversarial/test_adv_invariants.py` |
| **Les routes ne chargent jamais la configuration elles-mêmes.** | `tests/test_invariants.py` (`test_les_routes_ne_chargent_jamais_la_configuration_elles_memes`) |
| **Le cœur ne géocode pas** : `meteo`, `boucle` et `sortie` reçoivent un point déjà choisi. | `tests/test_invariants.py` (`test_le_coeur_ne_geocode_jamais_lui_meme`) |
| **Pas de réseau en test.** Clients HTTP injectables ; sockets coupées par une fixture automatique dans `tests/api/` et `tests/adversarial/` ; aucun `httpx.Client` sans transport bouchonné. | `tests/api/conftest.py`, `tests/adversarial/conftest.py`, `tests/test_invariants.py` (`test_aucun_test_ne_cree_un_client_http_sans_transport_bouchonne`) |
| **Aucune donnée personnelle dans le dépôt** : ni coordonnée réelle dans les fixtures, les fichiers de configuration ou `docs/`, ni fichier d'activité versionné, ni clé. | `tests/test_invariants.py` (`test_aucune_fixture_ne_contient_de_coordonnee_reelle`, `test_aucun_document_ne_porte_de_coordonnee_reelle`, `test_aucune_cle_dans_la_configuration_de_test`) ; `tests/test_gitignore.py` |
| **Aucune requête sans clause de propriétaire**, en SQLite comme dans les dépôts de l'API. | `tests/test_invariants.py` (`test_aucun_acces_aux_donnees_sans_clause_de_proprietaire`, `test_aucun_depot_ne_s_ajoute_a_depots_py_sans_etre_nomme`) ; `tests/api/test_api_isolation_proprietaire.py` |
| **Le mode hébergé refuse les sections personnelles** dans le socle, en TOML comme en variable d'environnement. | `tests/api/test_api_paquetage.py` (`test_en_heberge_une_section_perso_pur_dans_le_socle_refuse_le_demarrage`, `test_en_heberge_une_variable_perso_pur_refuse_aussi_le_demarrage`) |
| **Aucun secret ne sort** : ni dans une réponse, ni dans une erreur, ni dans le journal, ni dans le schéma publié. | `tests/api/test_api_secrets.py` |
| **Le contrat d'API est figé** : le schéma OpenAPI trié est comparé à une référence. | `tests/api/test_contrat_openapi.py`, `tests/caracterisation/openapi.json` ; la route qui sert chaque chemin, dans l'ordre d'enregistrement : `tests/api/test_resolution_routes.py` |
| **numpy reste dans `physique/`.** | `tests/test_invariants.py` (`test_numpy_reste_dans_le_paquet_physique`) |

## 4. L'écart honnête

Ce qui suit n'est pas un défaut caché : c'est la dette connue, mesurée, que la
suite du plan résorbe. Elle vient d'une construction par couches successives,
chaque sous-commande d'abord, l'API ensuite par-dessus.

**L'API appelle la ligne de commande.** `src/ourouler/api/adaptateur.py`
fabrique un `argparse.Namespace` identique à celui de la CLI, appelle la même
commande (`commandes.executer_depuis_namespace`, qui trouve la commande du
service que la route nomme) avec `json=True`, redirige la sortie
standard et la sortie d'erreur dans des tampons, puis relit le JSON imprimé.
Comme la sortie standard est un objet de processus, un verrou global
sérialise les calculs coûteux ; une deuxième requête reçoit `calcul_en_cours`.

**Le cycle entre `api` et `cli` est rompu (lot 5).** `profil_json` et le
masquage des secrets vivent dans `src/ourouler/rendu/profil.py`, que l'API
et la ligne de commande importent toutes deux ; les commandes de comptes
passent par `src/ourouler/services/comptes.py`. `cli.py` importe encore des
modules de `ourouler.api` (le serveur à lancer, le dépôt PostgreSQL des
comptes, le client SMTP, la lecture des variables de l'hébergé, les dépôts à
effacer) : c'est lui qui construit ces dépendances et les passe au service,
d'une entrée à une autre, sans cycle.

**Les `commande.py` faisaient tout** (diagnostic d'avant le lot 6 ; le rendu
en est sorti aux lots 6 et 8, argparse et l'impression au lot 10, vers
`rendu/` et `commandes/`). `sortie/commande.py` (2 494 lignes),
`boucle/commande.py` (1 857) et `physique/commande.py` (1 330) mêlent la
lecture des options argparse, l'orchestration des connecteurs, les écritures
de fichiers, le rendu texte et le rendu JSON. D'autres cas d'usage importent
ces fichiers de commande : `seance/ecran_ftp.py` et `physique/comparer.py`
importent `physique/commande.py` ; `sortie/commande.py` importe les
commandes de `boucle`, `meteo`, `seance` et `apprentissage`.

**Huit paquets en un seul cycle d'imports** : `config`, `activites`,
`connecteurs`, `meteo`, `boucle`, `physique`, `seance`, `apprentissage`
(imports différés compris). Les causes sont surtout de rangement :

- `physique/commande.py` importe `boucle/` (le type `Trace`, lui, est passé au
  noyau au lot 3 : `physique/modele.py` et `physique/calibration.py`
  n'importent plus `boucle/`) ;
- les cas d'usage (`*/commande.py`) reçoivent la `Config` entière, qui reste
  dans `config.py` : le défaut de son dossier de cache se résout depuis le
  répertoire de l'utilisateur ;
- `connecteurs/` n'importe plus que le noyau depuis le lot 7 (le connecteur
  Intervals range ses sorties dans un `DepotActivites`) ;
- `boucle/candidates.py` reçoit un `ClientBrouter` concret, pas une interface.

**La physique est pure depuis le lot 8.** `physique/calibration.py` ne fait
plus que calculer, sur des activités déjà lues, l'archive météo déjà obtenue
(`noyau.meteo.HeureArchive`) et une masse ; le choix et la lecture des
sorties (cache, inventaire, archive, `Config`) sont dans `services/calibrer.py`.
Hors `commande.py` et `comparer.py` (des cas d'usage), `physique/` n'importe
ni `pathlib`, ni `httpx`, ni `config`, ni le cache, ni `boucle`
(`tests/test_architecture.py`).

**Des fonctions trop longues.** 110 fonctions dépassent 50 lignes, 16 en
dépassent 100, 4 en dépassent 200 : `rendu/carte.py:_page_jour` (333),
`api/application.py:creer_application` (281), `boucle/candidates.py:generer`
(213), `sortie/commande.py:executer` (209). Les tests (5 189) sont nombreux
mais collés aux chemins internes : 203 usages de `monkeypatch` visent souvent
un attribut d'un module précis, qu'un déplacement de code casserait.

**D'autres dettes connues** :

- l'horloge est lue directement (`date.today()`, heure locale du processus)
  au lieu d'être injectée ;
- les tâches de fond de l'API (imports, calibrations) vivent en mémoire d'un
  seul processus (`src/ourouler/api/taches_fond.py`) et meurent à un
  redéploiement ;
- côté front, deux fichiers appellent `fetch` (`front/src/api/client.ts` et
  `front/src/ecrans/Proposition.tsx`) au lieu d'un seul.

## 5. L'architecture visée

Les dépendances ne vont que de haut en bas.

| Couche | Contenu | Peut importer |
|---|---|---|
| 5. Entrées | `cli`, `commandes` (du `Namespace` à la `Demande`, puis au rendu imprimé), `api`, `config` (lecture TOML et environnement) | tout |
| 4. Rendu | `rendu/` : texte, JSON (le contrat du front), carte HTML | 0 à 3 |
| 3. Cas d'usage | `services/` : sortie, boucle, meteo, calibrer, comparer, seance, apprendre, inventaire, comptes. Une `Demande` en entrée, un résultat en sortie, sans argparse ni `print` | 0 à 2 |
| 2. Adaptateurs | `connecteurs/` (HTTP) ; `stockage/` (cache, lecteurs FIT/GPX/TCX, routes connues, calibrations, cache des prévisions) | 0 et 1 |
| 1. Domaine pur | `physique` < `meteo` < `boucle` < `seance` < `sortie` | 0 et le domaine placé avant |
| 0. Noyau | erreurs, propriétaire, `trace`, `activite`, types météo, modèle de séance et zones, `profil` | bibliothèque standard |

**Le modèle physique pur** reçoit des paramètres, une `Trace`, des
échantillons de vent, des activités déjà lues et une masse ; il rend des
simulations, des ajustements et des validations. Il n'importe ni `Config`,
ni cache, ni `Path`, ni `httpx`, ni `boucle`. numpy y reste permis.

### La règle vérifiée

La règle d'imports est un test, `tests/test_architecture.py`, sur le modèle
de `tests/test_invariants.py`. Il lit dans l'arbre syntaxique les imports
internes de chaque module, imports différés compris ; ceux sous
`TYPE_CHECKING` sont permis mais nommés. Chaque module y est rangé dans une
couche et un paquet cible, là où il vit de fait, même quand son dossier
cible le rangerait ailleurs. Une arête qui monte d'une couche,
qui va contre l'ordre du domaine ou qui ferme un cycle entre paquets est
interdite.

Chaque violation d'aujourd'hui y figure comme une **exception datée**,
rattachée au lot qui doit la retirer. Le test échoue quand une violation
nouvelle apparaît, quand une exception ne sert plus ou quand elle a dépassé
sa date. La dette est donc une liste publique qui ne peut que baisser ; son
résumé par lot et les principaux cycles sont en tête du fichier de test.

**Le chemin**, dans l'ordre du tableau de `docs/ouverture_plan.md` §6.
Chaque étape garde les sorties de référence, le contrat OpenAPI et les tests
identiques, et retire les exceptions qu'elle rend inutiles.

1. Créer `noyau/` (trace, activité, erreurs, propriétaire), avec des
   réexports pour ne rien casser. *Fait (lot 3).*
2. Y ranger aussi les types météo, le profil, le modèle de séance et les zones.
   *Fait (lot 4)*, sauf `Config` elle-même : elle garde `ParametresCache`.
3. Casser le cycle `api` ↔ `cli` : `profil_json` passe au rendu, les comptes
   et invitations passent aux services. *Fait (lot 5).*
4. Sortir le rendu texte et JSON des `commande.py` de `sortie`, `boucle` et
   `physique`.
5. Isoler le stockage des calibrations : le domaine reçoit des paramètres,
   plus un chemin. *Fait (lot 7)* : `stockage/calibrations.py`,
   `physique/parametres_velo.py` et `seance/ftp.py`.
6. Couper `physique/calibration.py` entre le calcul pur et le service qui
   lit les données, à résultat identique au dernier chiffre. *Fait (lot 8)* :
   `services/calibrer.py` et `rendu/physique.py`.
7. Introduire une interface de routeur et découper `generer`. *Fait (lot 9)* :
   `noyau/ports.py`, et le découpage en mailles passé à `boucle/mailles.py`.
8. Sortir argparse des commandes : la `Demande` est construite par `cli`.
   *Fait (lot 10)* : `commandes/` et `services/contexte.py`.
9. Faire appeler service et rendu par l'API, sans `Namespace` ni capture de
   la sortie standard, avec une période où l'ancien et le nouveau chemin
   tournent ensemble et où l'écart est journalisé.
10. Découper les fonctions trop longues, une à la fois.
11. Scinder `api/routes.py` par domaine, en vérifiant que chaque chemin se
    résout toujours vers la même route. *Fait (lot 13)* : `api/routes/`, un
    module par domaine, et `tests/api/test_resolution_routes.py`.
12. Côté front : un seul point d'accès au réseau, des types vérifiés contre
    le schéma OpenAPI, `App.tsx` découpé.
13. Retirer les réexports.

## 6. Le trajet d'une demande « sortie »

Aujourd'hui, via l'API (`POST /api/v1/sorties`) :

```
front (écran de la sortie du jour)
  │  POST /api/v1/sorties  { jour, heure_depart, distance_km, depart: {lat, lon}, … }
  ▼
api/application.py      session (cookie en hébergé), limite de corps, erreurs
  ▼
api/routes/generations.py  generer_sortie : quota du compte, Config du propriétaire
  │                     (socle + profil, api/depots.py), clients HTTP du service
  ▼
api/adaptateur.py       Namespace argparse + verrou global
  │                     + redirection de stdout/stderr
  ▼
sortie/commande.py      executer(args, config, clients…)
  │   ├─ séance du jour ─────────────► connecteurs/intervals.py ──► Intervals.icu
  │   ├─ paramètres du vélo (physique/parametres_velo.py, calibration lue par stockage/calibrations.py)
  │   ├─ vent au départ ─────────────► meteo/openmeteo.py ────────► Open-Meteo
  │   │                                 (cache mutualisé en hébergé)
  │   ├─ candidates de boucle ───────► boucle/candidates.py
  │   │                                 connecteurs/brouter.py ─────► BRouter
  │   ├─ placement des blocs ────────► seance/placement.py, seance/terrain.py
  │   ├─ météo le long du tracé ─────► boucle/meteo_trace.py ─────► Open-Meteo
  │   ├─ coûts, classement, contraste ► boucle/couts.py, sortie/contraste.py
  │   ├─ tenue ──────────────────────► seance/tenue.py
  │   ├─ page du jour ───────────────► rendu/sortie.py, rendu/carte.py (écrite chez le propriétaire)
  │   └─ JSON imprimé sur stdout ────► rendu/sortie.py (rendre_json)
  ▼
api/adaptateur.py       relit le JSON capturé, classe les avertissements
  ▼
api/vues.py             ajoute les liens vers la carte et vers les GPX
  ▼                     (servis ensuite par GET …/propositions/{n}/gpx)
front                   trois propositions, blocs, tenue, carte
```

Le géocodage n'apparaît pas dans ce trajet : le front a déjà choisi un point
dans la liste rendue par `GET /api/v1/geocodage`, et l'API ne géocode jamais
au vol. Par la ligne de commande, le trajet est le même depuis
`sortie/commande.py`, `cli.py` tenant le rôle de l'API et de l'adaptateur.

Dans l'architecture visée, les trois boîtes « adaptateur », « commande » et
« rendu imprimé » deviennent : `api/routes/` construit une `Demande`,
appelle `services/sortie`, qui orchestre le domaine pur et les connecteurs,
puis `rendu/` produit le JSON, sans passer par la sortie standard.

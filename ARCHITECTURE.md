# Architecture d'ourouler

Ce document décrit le code **tel qu'il est**, la structure **visée**, et
l'écart entre les deux. Il ne porte volontairement aucun compte de lignes :
un chiffre recopié à la main se périme au premier commit ; `wc -l` et
`tests/test_architecture.py` disent l'état du jour. La doctrine qui justifie
ces choix est dans [`doctrine_architecture.md`](doctrine_architecture.md) ;
le plan de remise en ordre, dans [`docs/journal/ouverture_plan.md`](docs/journal/ouverture_plan.md).

## 1. Vue d'ensemble

ourouler répond à la question d'un cycliste équipé d'un capteur de puissance :
« je vais rouler ; où va-t-il pleuvoir, et quel parcours de la bonne durée
porte la séance du jour ? ». Il rend une météo par direction, des boucles
notées, la séance posée sur le tracé, une tenue conseillée, un GPX et une
carte de vérification.

**Deux entrées :**

- **La ligne de commande** `ourouler` (`src/ourouler/cli/`, argparse) :
  `config`, `inventaire`, `meteo`, `boucle`, `routes`, `calibrer`,
  `simuler`, `analyser`, `comparer`, `seance`, `sortie`, `geocoder`, `api`,
  et les commandes d'administration des comptes (`inviter`, `invitations`,
  `reinitialiser`, `retirer`, `admin`). Texte lisible par défaut, `--json` en
  option (`admin` sert du HTML, pas du JSON — voir `api/admin.py`).
- **L'API HTTP** (FastAPI, `src/ourouler/api/`) lancée par `ourouler api`
  (ou, dans le conteneur, par la fabrique `api.application:application`),
  et le **front** React/TypeScript (`front/`) qu'elle sert une fois
  construit. Le front ne parle qu'à `/api/v1`.

**Sources externes**, chacune derrière un connecteur qui reçoit un client
HTTP injectable :

| Source | Rôle | Module |
|---|---|---|
| Open-Meteo (prévisions) | pluie et vent par point et par heure, deux modèles | `src/ourouler/meteo/openmeteo.py` |
| Open-Meteo (archives) | le vent d'une sortie passée, pour la calibration | `src/ourouler/connecteurs/openmeteo_archive.py` |
| BRouter | itinéraires et boucles, tags OSM des tronçons | `src/ourouler/connecteurs/brouter.py` |
| Intervals.icu | activités, fichier FIT d'origine, séance planifiée | `src/ourouler/connecteurs/intervals.py` |
| Base Adresse Nationale, puis Nominatim en repli | une adresse tapée devient des candidats | `src/ourouler/connecteurs/geocodage.py` |
| Relais SMTP (Brevo) | le courriel d'invitation, en hébergé | `src/ourouler/api/courriel.py` |

La carte complète, avec les conditions d'usage de chaque service, est
[`docs/services_externes.md`](docs/services_externes.md).

**Stockage :**

- un **cache local** : les fichiers d'activité bruts tels que reçus, plus des
  index SQLite (`src/ourouler/activites/cache.py`, archive météo, routes
  connues), chacun avec une colonne « propriétaire » dans son identité ;
- un **cache mutualisé des prévisions** en hébergé
  (`src/ourouler/meteo/cache_previsions.py`), en mémoire du processus, dont
  la clé ne porte aucun identifiant de compte ;
- en hébergé, **un dossier par propriétaire** sous le cache du serveur
  (profil, fichiers déposés, calibration : `src/ourouler/api/depots.py`) ;
- **PostgreSQL**, en hébergé seulement, pour les comptes, invitations et
  sessions (`src/ourouler/api/base_de_donnees.py`,
  `src/ourouler/api/migrations/`).

**Deux modes**, choisis par la variable `OUROULER_MODE`, lue dans
`src/ourouler/api/exploitation.py` et nulle part ailleurs (toutes les
variables d'environnement : [`deploiement/api/README.md`](deploiement/api/README.md#les-variables-denvironnement)) :

- **personnel** : un cycliste, sa machine, son fichier TOML ; pas de base,
  pas de comptes. C'est le mode de `ourouler api` ;
- **hébergé** (le défaut de la fabrique `application()`, parce que c'est le
  mode qui refuse) : plusieurs cyclistes, des sessions par cookie dès que
  `OUROULER_DATABASE_URL` est posée, un profil par propriétaire
  (`src/ourouler/api/depots.py`). Le fichier de configuration du serveur
  n'y porte **aucune** section personnelle (`depart`, `cycliste`, `velos`,
  `intervals`) : l'application refuse de démarrer sinon.

## 2. Carte des paquets, aujourd'hui

Tout est sous `src/ourouler/`.

| Paquet | Rôle | Fichiers principaux |
|---|---|---|
| `cli/` | argparse (le parseur), lecture de la config, `--adresse-depart`, codes de sortie, appel des commandes ; construit aussi les dépendances des commandes de comptes | `__init__.py` (`main`), `parseur.py`, `options.py`, `depart.py`, `comptes.py` |
| `commandes/` | une entrée par sous-commande : lit le `Namespace`, construit la `Demande` du service (`interpreter`) et son `Contexte` depuis la `Config`, appelle le service puis le rendu, et imprime. `executer_depuis_namespace` sert aussi l'**ancien chemin** de l'API (§4) | `sortie.py`, `boucle.py`, `physique.py`, `comparer.py`, `commun.py` |
| `config.py` | `Config` (le profil du noyau plus `ParametresCache`) ; chargement TOML et environnement | `config.py` |
| `noyau/` | types partagés, bibliothèque standard seulement : le tracé `Trace`, le modèle `Activite`, les exceptions communes, la constante du propriétaire local, le modèle de séance et les zones, les types de prévision météo, le profil du cycliste (`Velo`, `Depart`, les paramètres…), les protocoles que le domaine reçoit à la place des clients HTTP (`Routeur`, `SourcePrevisions`, `SourceSeances`) et celui où le connecteur Intervals range ses sorties (`DepotActivites`), et de petites aides partagées (lecture de fichiers, structure SQLite, nombres à la française) | `activite.py`, `trace.py`, `erreurs.py`, `proprietaire.py`, `seance.py`, `zones.py`, `meteo.py`, `profil.py`, `ports.py`, `lecture.py`, `sqlite.py`, `texte.py` |
| `activites/` | lecteur unique FIT/GPX/TCX, cache SQLite, inventaire, import d'archive | `cache.py`, `import_archive.py`, `lecture.py` |
| `connecteurs/` | clients HTTP : BRouter, Intervals.icu, archives Open-Meteo, géocodage | `brouter.py`, `intervals.py`, `openmeteo_archive.py`, `geocodage.py` |
| `stockage/` | ce qui s'écrit sur disque et se relit : `calibration.json` ; le cache d'activités, les routes connues et le cache des prévisions n'y sont pas encore | `calibrations.py` |
| `meteo/` | couronne de points, client de prévisions, rapport par direction, portée des modèles, cache mutualisé | `rapport.py`, `openmeteo.py`, `cache_previsions.py` |
| `boucle/` | candidates de boucle, coûts, météo le long du tracé, découpage en mailles, antennes, GPX | `meteo_trace.py`, `couts.py`, `candidates.py`, `mailles.py` |
| `physique/` | modèle puissance ↔ vitesse, paramètres d'un vélo (`parametres_velo.py`), calcul de la calibration CdA/Crr, ses échantillons (`echantillonnage.py`), sa validation (`validation.py`), la détection des sorties en groupe (`groupe.py`) | `calibration.py`, `modele.py` |
| `seance/` | lecteurs ZWO/MRC/Intervals, placement sur le terrain (`placement.py`, son résultat dans `placement_resultat.py`, sa note dans `placement_note.py`, le tracé en pas dans `pas_trace.py`), tenue, écran de FTP (calcul dans `ftp.py`, commande dans `ecran_ftp.py`) | `placement.py`, `terrain.py`, `intervals.py` |
| `sortie/` | la séance du jour posée sur une boucle : contraste des propositions, orientation et vent de la demande (l'orchestration est le cas d'usage `services/sortie.py`) | `contraste.py`, `orientation.py`, `vent_demande.py` |
| `apprentissage/` | routes connues : rejouer les sorties passées dans BRouter pour en tirer des poids | `routes.py` |
| `rendu/` | ce qu'une entrée montre d'un résultat, sans rien lire ni écrire : le profil en JSON et le masquage des secrets (`profil.py`), l'affichage des commandes de comptes (`comptes.py`), le tableau, le JSON et la page du jour de `sortie` (`sortie.py`, `sortie_json.py`) et de `boucle` (`boucle.py`, `boucle_json.py`), la carte HTML (`carte.py`, avec `carte_dessin.py` et `carte_jour.py`), le texte et le JSON de `calibrer`, `simuler` et `analyser` (`physique.py`), de `comparer` (`comparaison.py`) et de `routes` (`routes.py`) | `sortie.py`, `carte.py`, `boucle.py`, `physique.py` |
| `services/` | cas d'usage sans argparse ni affichage : les comptes de l'hébergé (inviter, lister les invitations, réinitialiser, retirer) ; choisir, lire et calibrer les sorties d'un vélo (`calibrer.py`) ; ce que l'import tire d'une sortie pour un compte qui ne garde pas ses fichiers d'origine (`derive.py`) ; comparer deux vélos (`comparer.py`) ; le `Contexte` que reçoit tout service (`contexte.py`) ; et un module par domaine pour les sous-commandes de calcul : `sortie.py`, `boucle.py`, `physique.py` (`calibrer`, `simuler`, `analyser`), `seance.py`, `meteo.py`, `apprentissage.py` (`routes`), `activites.py` (`inventaire`), `geocodage.py` (`geocoder`) | `sortie.py`, `boucle.py`, `physique.py`, `comptes.py`, `contexte.py`, `derive.py` |
| `api/` | application FastAPI, sessions, comptes, dépôts par propriétaire, quotas, tâches de fond ; les routes, un module par domaine sous `routes/` ; les deux chemins vers le cœur (`adaptateur.py`, `calculs.py`, `double_chemin.py`, voir §4) ; la seule lecture de l'environnement de l'API (`exploitation.py`) | `application.py`, `comptes.py`, `depots.py`, `double_chemin.py`, `routes/` |

Les anciens chemins *boucle/trace.py*, *activites/modele.py*, *erreurs.py*
et *proprietaire.py* à la racine du paquet, *seance/modele.py*,
*seance/zones.py*, *sortie/carte.py* et *physique/comparer.py* n'existent
plus : le code importe directement le noyau (ou `rendu/carte.py`,
`services/comparer.py`). `config.py` garde `Velo`, `Depart`… comme alias
public délibéré (souvent importés ainsi). De même, *cli.py*, les huit
*commande.py* rangés dans le dossier de leur domaine et le paquet
*geocodage/* n'existent plus : `cli/` et `services/<domaine>.py` les
remplacent, sans réexport à l'ancien chemin.

argparse est sorti des cas d'usage. Chaque sous-commande a sa `Demande` (une
dataclass, dans le module du service) et un service
`executer(demande, contexte, clients…)` qui rend un résultat sans rien
imprimer ; le `Contexte` porte le profil (`noyau.profil.Profil`, que
`Config` satisfait), le dossier de cache et le fichier de calibration déjà
résolus, et le canal des avertissements. `commandes/<nom>.py` lit le
`Namespace`, appelle le service, puis le rendu, et imprime.

Côté front : `front/src/App.tsx`, un écran par fichier dans
`front/src/ecrans/` (les écrans découpés ont un sous-dossier à leur nom), et
un seul client réseau, `front/src/api/client.ts`. Le détail est dans
[`front/README.md`](front/README.md).

## 3. Ce qui tient déjà, et ce qui le garde

Ces règles sont vérifiées par des tests qui lisent le code source lui-même ;
un changement qui les enfreint fait rougir la CI (`.github/workflows/ci.yml` :
recherche de secrets dans l'historique, ruff, pytest avec un Postgres
jetable, vérification du front, construction de l'image et démarrage sans
Postgres).

| Invariant | Où il est vérifié |
|---|---|
| **Le cœur ne sait pas où il tourne.** Seuls `cli/`, `config.py` et `api/exploitation.py` lisent l'environnement, `tomllib` ou le dossier de l'utilisateur. | `tests/test_invariants.py` (`test_le_coeur_ne_lit_pas_son_environnement`, `test_le_coeur_n_importe_pas_tomllib`, `test_seul_le_module_d_exploitation_de_l_api_lit_l_environnement`) ; `tests/adversarial/test_adv_invariants.py` |
| **Les routes ne chargent jamais la configuration elles-mêmes.** | `tests/test_invariants.py` (`test_les_routes_ne_chargent_jamais_la_configuration_elles_memes`) |
| **Le cœur ne géocode pas** : `meteo`, `boucle` et `sortie` reçoivent un point déjà choisi. | `tests/test_invariants.py` (`test_le_coeur_ne_geocode_jamais_lui_meme`) |
| **Pas de réseau en test.** Clients HTTP injectables ; toute connexion vers une adresse non locale coupée par une fixture automatique de `tests/conftest.py`, pour toute la suite ; aucun `httpx.Client` sans transport bouchonné. | `tests/conftest.py` (`reseau_interdit`), `tests/test_garde_reseau.py`, `tests/test_invariants.py` (`test_aucun_test_ne_cree_un_client_http_sans_transport_bouchonne`) |
| **Aucune donnée personnelle dans le dépôt** : ni coordonnée réelle dans les fixtures, les fichiers de configuration ou le Markdown, ni fichier d'activité versionné, ni clé. | `tests/test_invariants.py` (`test_aucune_fixture_ne_contient_de_coordonnee_reelle`, `test_aucun_document_ne_porte_de_coordonnee_reelle`, `test_aucune_cle_dans_la_configuration_de_test`) ; `tests/test_gitignore.py` |
| **Aucune requête sans clause de propriétaire**, en SQLite comme dans les dépôts de l'API. | `tests/test_invariants.py` (`test_aucun_acces_aux_donnees_sans_clause_de_proprietaire`, `test_aucun_depot_ne_s_ajoute_a_depots_py_sans_etre_nomme`) ; `tests/api/test_api_isolation_proprietaire.py` |
| **Le mode hébergé refuse les sections personnelles** dans le socle, en TOML comme en variable d'environnement. | `tests/api/test_api_paquetage.py` (`test_en_heberge_une_section_perso_pur_dans_le_socle_refuse_le_demarrage`, `test_en_heberge_une_variable_perso_pur_refuse_aussi_le_demarrage`) |
| **Aucun secret ne sort** : ni dans une réponse, ni dans une erreur, ni dans le journal, ni dans le schéma publié. | `tests/api/test_api_secrets.py` |
| **Le contrat d'API est figé** : le schéma OpenAPI trié est comparé à une référence. | `tests/api/test_contrat_openapi.py`, `tests/caracterisation/openapi.json` ; la route qui sert chaque chemin, dans l'ordre d'enregistrement : `tests/api/test_resolution_routes.py` ; les types du front contre ce schéma : `front/tests/types_openapi.test.ts` |
| **Les dépendances ne vont que de haut en bas** (§5). | `tests/test_architecture.py` |
| **numpy reste dans `physique/`.** | `tests/test_invariants.py` (`test_numpy_reste_dans_le_paquet_physique`) |
| **Un seul point d'accès au réseau côté front.** | `front/tests/reseau_unique.test.ts` |

## 4. L'écart honnête

Ce qui suit n'est pas un défaut caché : c'est la dette connue. Elle vient
d'une construction par couches successives, chaque sous-commande d'abord,
l'API ensuite par-dessus.

**L'API a deux chemins vers le cœur**, choisis au démarrage par
`OUROULER_API_CHEMIN` (`api/exploitation.chemin_api`,
`api/double_chemin.py`) :

- `ancien`, **le défaut** (`double_chemin.CHEMIN_DEFAUT`) :
  `api/adaptateur.py` fabrique un `argparse.Namespace` identique à celui de
  la CLI, appelle la commande (`commandes.executer_depuis_namespace`) avec
  `json=True`, capture la sortie standard et la sortie d'erreur, puis relit
  le JSON imprimé. Comme la sortie standard est un objet de processus, un
  verrou global sérialise les calculs coûteux ; une deuxième requête reçoit
  `calcul_en_cours` ;
- `nouveau` : `api/calculs.py` construit la `Demande` par la même fonction
  que la ligne de commande (`commandes.<commande>.interpreter`), appelle le
  service, puis le rendu JSON — ni `Namespace`, ni capture, ni verrou ;
- `double` : les deux tournent, l'ancien répond, et tout écart de statut ou
  de corps est journalisé (`ecart_double_chemin`), sans valeur personnelle.
  Chaque calcul coûte alors deux fois.

Tant que le défaut n'a pas basculé, le trajet décrit au §6 reste celui de
l'ancien chemin.

**Le cycle entre `api` et `cli` est rompu.** `profil_json` et le masquage
des secrets vivent dans `src/ourouler/rendu/profil.py`, que l'API et la
ligne de commande importent toutes deux ; les commandes de comptes passent
par `src/ourouler/services/comptes.py`. `cli/` importe encore des modules
de `ourouler.api` (le serveur à lancer, le dépôt PostgreSQL des comptes, le
client SMTP, la lecture des variables de l'hébergé, les dépôts à effacer) :
c'est lui qui construit ces dépendances et les passe au service, d'une
entrée à une autre, sans cycle.

**Trois cas d'usage vivent encore hors de `services/`.** Les sous-commandes
de calcul ont chacune leur module dans `services/` ; restent dans le dossier
de leur domaine `activites/inventaire.py`, `apprentissage/routes.py` et
`seance/ecran_ftp.py`, qui lisent le cache ou un fichier pour rendre un
résultat : `tests/test_architecture.py` les range par leur rôle (`MODULES`),
pas par leur dossier.

**Par dossier, des cycles d'imports subsistent** — un module rangé dans un
dossier importe d'autres paquets, qui importent ce dossier à leur tour. Par rôle, aucun : la table `EXCEPTIONS` de
`tests/test_architecture.py` est vide, et le test échoue sur toute
violation nouvelle.

**La physique est pure.** `physique/calibration.py` ne fait que calculer, sur
des activités déjà lues, l'archive météo déjà obtenue
(`noyau.meteo.HeureArchive`) et une masse ; le choix et la lecture des
sorties (cache, inventaire, archive, profil) sont dans
`services/calibrer.py`, et ses cas d'usage dans `services/physique.py` :
`physique/` n'importe ni `pathlib`, ni `httpx`, ni `config`, ni le cache, ni `boucle`
(`tests/test_architecture.py`,
`test_la_physique_pure_n_importe_ni_chemin_ni_reseau_ni_configuration`).

**Des fonctions trop longues.** Les exceptions aux seuils de ruff
(complexité, branches, arguments positionnels) sont listées dans
`pyproject.toml`, datées, et `tests/test_regles_ruff.py` échoue quand l'une
ne sert plus ou a passé sa date. La plus longue est
`api/application.py:creer_application`.

**D'autres dettes connues** :

- l'horloge est lue directement (`date.today()`, `datetime.now()`, heure
  locale du processus) au lieu d'être injectée ; le conteneur pose donc
  `TZ` ;
- les tâches de fond de l'API (imports, calibrations), les quotas et le
  cache des prévisions vivent en mémoire d'un seul processus
  (`src/ourouler/api/taches_fond.py`, `api/quotas.py`,
  `meteo/cache_previsions.py`) et meurent à un redéploiement.

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
cible le rangerait ailleurs. Une arête qui monte d'une couche, qui va contre
l'ordre du domaine ou qui ferme un cycle entre paquets est interdite.

Une violation ne peut entrer que comme **exception datée** (`EXCEPTIONS`),
rattachée au lot qui doit la retirer. Le test échoue quand une violation
nouvelle apparaît, quand une exception ne sert plus ou quand elle a dépassé
sa date. La table est vide aujourd'hui.

**Le chemin**, dans l'ordre du tableau de
[`docs/journal/ouverture_plan.md`](docs/journal/ouverture_plan.md) §6. Chaque étape garde les
sorties de référence, le contrat OpenAPI et les tests identiques, et retire
les exceptions qu'elle rend inutiles.

1. Créer `noyau/` (trace, activité, erreurs, propriétaire). *Fait.*
2. Y ranger aussi les types météo, le profil, le modèle de séance et les
   zones. *Fait*, sauf `Config` elle-même : elle garde
   `ParametresCache`.
3. Casser le cycle `api` ↔ `cli` : `profil_json` passe au rendu, les comptes
   et invitations passent aux services. *Fait.*
4. Sortir le rendu texte et JSON des cas d'usage de `sortie`, `boucle` et
   `physique`. *Fait* : `rendu/sortie.py`, `rendu/boucle.py`,
   `rendu/carte.py`, `rendu/physique.py`.
5. Isoler le stockage des calibrations : le domaine reçoit des paramètres,
   plus un chemin. *Fait* : `stockage/calibrations.py`,
   `physique/parametres_velo.py` et `seance/ftp.py`.
6. Couper `physique/calibration.py` entre le calcul pur et le service qui
   lit les données, à résultat identique au dernier chiffre. *Fait* :
   `services/calibrer.py` et `rendu/physique.py`.
7. Introduire une interface de routeur et découper `generer`. *Fait* :
   `noyau/ports.py`, et le découpage en mailles passé à `boucle/mailles.py`.
8. Sortir argparse des commandes : la `Demande` est construite par l'entrée.
   *Fait* : `commandes/` et `services/contexte.py`.
9. Faire appeler service et rendu par l'API, sans `Namespace` ni capture de
   la sortie standard, avec une période où l'ancien et le nouveau chemin
   tournent ensemble et où l'écart est journalisé. *Écrit* :
   `api/calculs.py`, `api/double_chemin.py` ; le défaut reste `ancien`
   jusqu'à la bascule.
10. Découper les fonctions trop longues, une à la fois. *À faire* : les
    exceptions datées de `pyproject.toml` en portent la liste.
11. Scinder *api/routes.py* (l'ancien fichier unique) par domaine, en
    vérifiant que chaque chemin se résout toujours vers la même route. *Fait*
    : `api/routes/`, un module par domaine, et
    `tests/api/test_resolution_routes.py`.
12. Côté front : un seul point d'accès au réseau, des types vérifiés contre
    le schéma OpenAPI, `App.tsx` découpé. *Fait* :
    `front/tests/reseau_unique.test.ts`, `front/tests/types_openapi.test.ts`,
    `front/tests/taille_composants.test.ts`.
13. Retirer les réexports. *Fait.*
14. Ranger les cas d'usage des sous-commandes dans `services/` et découper
    la ligne de commande en paquet `cli/`. *Fait* : `services/sortie.py`,
    `services/boucle.py`… et `cli/parseur.py`, `cli/comptes.py`.

## 6. Le trajet d'une demande « sortie »

Via l'API (`POST /api/v1/sorties`), par l'ancien chemin, le défaut :

```
front (écran de la sortie du jour)
  │  POST /api/v1/sorties  { jour, heure_depart, distance_km, depart: {lat, lon}, … }
  ▼
api/application.py      session (cookie en hébergé), limite de corps, erreurs
  ▼
api/routes/generations.py  generer_sortie : quota du compte, Config du propriétaire
  │                     (socle + profil, api/depots.py), clients HTTP du service
  ▼
api/double_chemin.py    calculer : choisit le chemin
  ▼
api/adaptateur.py       Namespace argparse + verrou global
  │                     + redirection de stdout/stderr
  ▼
commandes/sortie.py     du Namespace à la Demande, puis le service
  ▼
services/sortie.py      executer(demande, contexte, clients…)
  │   ├─ séance du jour ─────────────► connecteurs/intervals.py ──► Intervals.icu
  │   ├─ paramètres du vélo (physique/parametres_velo.py, calibration lue par stockage/calibrations.py)
  │   ├─ vent au départ ─────────────► meteo/openmeteo.py ────────► Open-Meteo
  │   │                                 (cache mutualisé en hébergé)
  │   ├─ candidates de boucle ───────► boucle/candidates.py
  │   │                                 connecteurs/brouter.py ─────► BRouter
  │   ├─ placement des blocs ────────► seance/placement.py, seance/terrain.py
  │   ├─ météo le long du tracé ─────► boucle/meteo_trace.py ─────► Open-Meteo
  │   ├─ coûts, classement, contraste ► boucle/couts.py, sortie/contraste.py
  │   └─ tenue ──────────────────────► seance/tenue.py
  ▼
commandes/sortie.py     rendu : rendu/sortie_json.py (JSON imprimé sur stdout) ;
  │                     page du jour et carte : rendu/sortie.py, rendu/carte.py
  ▼
api/adaptateur.py       relit le JSON capturé, classe les avertissements
  ▼
api/vues.py             ajoute les liens vers la carte et vers les GPX
  ▼                     (servis ensuite par GET …/propositions/{n}/gpx)
front                   trois propositions, blocs, tenue, carte
```

Par le **nouveau chemin**, les trois boîtes `adaptateur.py`,
`commandes/sortie.py` et « JSON imprimé » deviennent `api/calculs.py`
(`sortie`) : la même `interpreter` construit la `Demande`, le même service
tourne, et le même rendu JSON est rendu directement, sans passer par la
sortie standard.

Le géocodage n'apparaît pas dans ce trajet : le front a déjà choisi un point
dans la liste rendue par `GET /api/v1/geocodage`, et l'API ne géocode jamais
au vol. Par la ligne de commande, le trajet part de `cli/`, qui tient le
rôle de la route, puis passe par `commandes/sortie.py` comme ci-dessus.

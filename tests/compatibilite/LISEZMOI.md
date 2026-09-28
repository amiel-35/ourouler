# Formats persistés (filet 0d)

Ce dossier fige **ce que le code écrit sur disque ou en base et relit plus
tard**, tel que la version d'aujourd'hui l'écrit, parce qu'« un retour
arrière peut casser sur les données ».

## Les règles

1. **Une restructuration ne touche ni un format persisté, ni une constante
   de version, ni une migration.** Un test rouge ici n'est pas une référence
   à régénérer : c'est la restructuration qui a débordé.
2. **Postgres : on ajoute d'abord, on retire plus tard.** Jamais de `DROP` ni
   de `RENAME` dans une restructuration. Une colonne qui doit
   disparaître reste en place jusqu'à ce qu'aucune version déployable ne la
   lise plus ; son retrait est une migration à part, décidée par le
   mainteneur (et inscrite dans `MIGRATIONS_DESTRUCTIVES_ADMISES` de
   `test_compatibilite.py`). Une migration déjà passée ne se modifie jamais :
   on en ajoute une nouvelle.
3. **Ajouter une migration est un geste explicite** : elle rougit
   `test_versions_de_schema_et_migrations_figees` tant que `versions.json`
   n'a pas été régénéré, et ce diff se relit dans la PR.
4. **Un changement de format voulu** (hors restructuration) monte la
   constante de version, écrit la migration de l'ancien vers le nouveau
   format, puis régénère — et la PR dit ce que devient un retour arrière.

Régénérer (après décision, jamais pour « faire passer ») :

    uv run pytest tests/compatibilite --regenerer-golden

## Ce que les tests vérifient

| test | promesse |
|---|---|
| `test_le_code_actuel_relit_l_echantillon[…]` | le code du moment relit chaque échantillon figé et en tire les mêmes valeurs (`echantillons/lecture.json`) — et la relecture ne réécrit rien (aucune migration silencieuse) |
| `test_le_code_actuel_reecrit_le_meme_contenu[…]` | une fabrication fraîche (`fabrique_echantillons.py`) produit le même contenu que l'échantillon : lignes et schéma d'un SQLite, JSON relu, octets d'un fichier — c'est ce qui permet à l'ancien code de relire ce que le nouveau écrit |
| `test_aucun_nouveau_fichier_persiste_n_apparait` | un fichier que le code se mettrait à écrire est un format de plus : il se déclare dans `FICHIERS` |
| `test_versions_de_schema_et_migrations_figees` | constantes de version, versions effectivement écrites, migrations Postgres (numéro, nom, empreinte SHA-256 du SQL) — `echantillons/versions.json` |
| `test_aucune_migration_ne_detruit_ni_ne_renomme` | ni `DROP` ni `RENAME` dans une migration (commentaires exclus) |
| `test_un_index_plus_recent_est_refuse`, etc. | ce qui se passe **aujourd'hui** à la lecture d'une version plus récente (voir la table) |
| `test_les_echantillons_ne_portent_aucune_coordonnee_reelle` | tout point des échantillons est à moins d'un degré du point (0, 0), en mer |

Les échantillons sont produits par les fonctions d'écriture du code (la ligne
de commande `inventaire --importer`, `calibrer`, `routes poids --appliquer`,
puis `Cache`, `BaseRoutes`, `DepotProfils`, `JournalServices`,
`DepotFichiers`, `ecrire_gpx`, `hacher_mot_de_passe`), sur les données
synthétiques du filet 0b (`tests/caracterisation/donnees_synthetiques.py`),
horloge figée et réseau rejoué par `outils_caracterisation.preparer`. Le sel
du mot de passe et les identifiants de fichier sont fixés pour que la
fabrication soit reproductible. `calibration.json` se compare à 6 chiffres
significatifs (numpy), les autres flottants à 1e-9 près en relatif.

Un changement qui **déplace** un module d'écriture ou de lecture met à jour
les imports de `fabrique_echantillons.py` et `test_compatibilite.py` (ou garde
un réexport) et les noms qualifiés de `CONSTANTES_DE_VERSION` ; il ne
touche jamais `echantillons/`.

## Inventaire des formats

`<cache>` est le dossier `[cache] dossier` de la configuration
(`~/.cache/ourouler` par défaut) ; `<api>` est `<cache>/api`, le dossier des
données du service ; `<prop>` un identifiant de propriétaire.

| format | emplacement | écrit par | relu par | version | lecture d'une version plus **récente** | lecture d'une version plus **ancienne** | échantillon |
|---|---|---|---|---|---|---|---|
| index des activités (SQLite) | `<cache>/index.sqlite` ; fichiers bruts `<cache>/brut/<sha256>.<ext>`, `<cache>/brut/comptes/<prop>/…` | `activites/cache.Cache.ajouter`, `mettre_a_jour_meta` (inventaire, synchronisation Intervals, import de l'API) | `Cache.lister`, `chemin`, `relire`, `contient` (inventaire, calibrer, comparer, routes, API) | `activites.cache.VERSION_SCHEMA` = 3 (`PRAGMA user_version`) | **refusé** (`ErreurUtilisateur` : « supprimer index.sqlite le reconstruira ») — testé | migré sur place 1→3, 2→3 (`tests/test_cache.py`) | `donnees/index.sqlite` (deux propriétaires) |
| dérivés d'activités (SQLite, table `derives` du même fichier) | `<cache>/index.sqlite` (table `derives`, additive — ne change pas `VERSION_SCHEMA`) | `activites/cache.Cache.ecrire_derive` (import d'un compte qui ne garde pas ses fichiers d'origine, `services/derive.Derivateur` et `purger_avec_derivation`) | `Cache.lire_derive`, `versions_derives`, `etats_derives` (`services/derive.charger`/`trier`/`etat`, calibration) | `services.derive.VERSION_DERIVATION` = 1 (colonne `version`, une par ligne) | une ligne d'une version différente (plus récente comme plus ancienne) n'est pas relue à moitié : `services.derive.charger`/`etat` la traitent comme absente, motif `MOTIF_A_REDEPOSER` (« à redéposer ») — la sortie ne compte plus pour la calibration tant que l'archive n'est pas redéposée | même traitement que la colonne précédente : « à redéposer », jamais une lecture partielle | `donnees/index.sqlite` (table `derives`, une ligne, sortie synthétique du 03/03/2026) |
| archive météo (SQLite) | `<cache>/archive_meteo.sqlite` | `connecteurs/openmeteo_archive.ClientArchive` (calibrer, tâche de fond de l'API) | `ClientArchive.horaires` | `openmeteo_archive.VERSION_SCHEMA` = 2 | **relu quand même**, et `user_version` ramené à 2 à l'ouverture — testé | migré 1→2 (`tests/test_openmeteo_archive.py`) | `donnees/archive_meteo.sqlite` |
| routes connues (SQLite) | `<cache>/routes_connues.sqlite` | `apprentissage/routes.BaseRoutes.ajouter_trace` (`routes apprendre`, API) | `BaseRoutes` (boucle, sortie, `routes stats`/`poids`, export RGPD) | `apprentissage.routes.VERSION_SCHEMA` = 3 | **refusé** (`ErreurUtilisateur`) — testé | migré 1→2→3 (`tests/test_apprentissage_routes.py`) | `donnees/routes_connues.sqlite` (deux propriétaires) |
| calibration (JSON) | `<cache>/calibration.json` ; en hébergé `<api>/<prop>/calibration.json` | `stockage/calibrations.ecrire_calibration` + `contenu_calibration` (calibrer, `api/calibrations`) | `stockage/calibrations.lire_calibration` (boucle, sortie, simuler, écran FTP, `/calibrations`) | `stockage.calibrations.VERSION_CALIBRATION` = 1 (champ `version`) | **ignorée** (`None` : le temps retombe sur la configuration ou la littérature) — testé. Attention : `ecrire_calibration` garde les vélos d'un fichier d'une autre version et le réécrit en version 1 | champs récents absents tolérés (`porte_a_porte`, `crr_source`, `biais`…) | `donnees/calibration.json` (deux vélos, dont un avec `porte_a_porte`) |
| poids des routes (JSON) | `<cache>/poids_routes.json` | `apprentissage/routes.ecrire_poids` (`routes poids --appliquer`) | `lire_poids` (boucle, sortie) | littéral `"version": 1`, **jamais lu** | relu quand même (seul `poids` compte) — testé | — | `donnees/poids_routes.json` |
| profil d'un compte (JSON) | `<api>/<prop>/profil.json` (droits 0600, écriture atomique) | `api/depots.DepotProfils.enregistrer` (`PATCH /profil`) | `DepotProfils.surcharge`, `config` ; export RGPD | aucune : c'est la surcharge du TOML, bornée par `CHAMPS_MODIFIABLES` | un champ inconnu est ignoré par `config.depuis_dict` ; une valeur d'énumération inconnue (ex. `pneu`) fait refuser le profil (`ErreurConfig`) | champs absents : défauts de `Config` (profil d'avant `prenom`/`nom` compris) | `donnees/api/compte-synthetique/profil.json` |
| journal des services (JSON) | `<api>/<prop>/services.json` | `api/depots.JournalServices.noter_succes` | `dernier_succes`, `tout` (écrans d'échec, export) | aucune | illisible ou d'une autre forme → `{}` | — | `donnees/api/compte-synthetique/services.json` |
| fichiers déposés et produits | `<api>/<prop>/fichiers/<uuid hex>.<ext>` + `<uuid hex>.nom` (nom d'affichage) | `api/depots.DepotFichiers.deposer`, `enregistrer` (séance `.ZWO`/`.MRC`, carte, GPX) | `DepotFichiers.trouver`, `lister` (séance du jour, `/fichiers/{id}`, `/simulations`, export) | aucune ; extensions fermées (`EXTENSIONS`) | — | — | `donnees/api/compte-synthetique/fichiers/…` (un `.zwo`, un `.mrc`, leurs `.nom`) |
| parcours GPX | où la commande l'écrit ; en hébergé dans le dépôt de fichiers | `boucle/gpx.ecrire_gpx` (boucle, sortie, API) | `boucle/gpx.lire_gpx_trace` (`simuler --gpx`, `/simulations`) | GPX 1.1 | — | — | `parcours.gpx.xml` (suffixe `.xml` : aucun `.gpx` hors de `tests/fixtures/`, invariant `test_aucun_fichier_d_activite_hors_des_fixtures` ; `.gitignore` inchangé) |
| migrations Postgres | `src/ourouler/api/migrations/NNNN_sujet.sql` ; table `migrations` | appliquées par `api/base_de_donnees.appliquer_migrations` au démarrage | la table `migrations` dit ce qui est passé | la liste des numéros (0001, 0002) | un code plus ancien ignore les numéros qu'il ne connaît pas : il n'applique que ce qui lui manque, et les tables ou colonnes ajoutées restent — d'où « on ajoute d'abord » | applique ce qui manque, chaque fichier dans sa transaction | `versions.json` : noms et SHA-256 |
| secret d'un compte (colonne Postgres) | `comptes.secret` | `api/comptes.hacher_mot_de_passe` | `verifier_mot_de_passe` | aucune : `<sel hex>$<empreinte hex>`, scrypt N=2¹⁴, r=8, p=1, 32 octets | — | — | `secret_compte.json` (sel fixé) |

**Retour arrière sur `derives` et sur les colonnes `conserver_fichiers_bruts*`,
concrètement** : un code d'avant ce lot ne lit jamais la table `derives` ni
les deux colonnes ajoutées à `comptes` par
`migrations/0004_conservation_fichiers.sql` — l'un et l'autre restent en
place (schéma additif) sans que ce code plus ancien s'en aperçoive. Pour un
compte qui a choisi « garder », rien ne change : ses fichiers d'origine sont
toujours là, ce code les relit comme avant.
**Pour un compte qui a choisi « ne pas garder », en revanche, un retour
arrière rend ses sorties sans fichier d'origine inutilisables pour la
calibration** — le code plus ancien ne sait pas lire `derives`, et le
fichier qu'il irait chercher n'existe plus. Ce n'est pas une perte de
données (l'index garde la ligne, la sortie reste comptée dans l'historique
et l'inventaire), seulement une calibration qui ne peut plus se refaire sur
ces sorties-là jusqu'au redéploiement du code qui sait lire `derives` — ou
jusqu'à ce que la personne redépose l'archive.

### Hors filet, et pourquoi

- **Les lignes Postgres** (comptes, invitations, sessions,
  `comptes_proprietaires`) : ce filet ne lance pas de Postgres. Leur schéma
  est figé par l'empreinte des migrations, leur forme par les contraintes
  `CHECK` de ces migrations, le secret par `secret_compte.json` ; le reste se
  vérifie par `tests/comptes/` et en préproduction (P2).
- **Les fichiers bruts d'activité** (`brut/…`) : ce sont les octets de la
  source (FIT, GPX, TCX), pas un format du projet. Seul leur rangement en est
  un, et `index.sqlite` le fige (champ `chemin` de `lecture.json`).
- **Le contenu d'une séance déposée** (`.ZWO`, `.MRC`) : format de Zwift ou
  d'un tiers, gardé tel quel ; le dépôt en fige le rangement, pas la lecture.
- **La carte HTML** : écrite, servie, jamais relue par le code ; son empreinte
  est dans le filet 0b.
- **Non persistés** : le cache mutualisé des prévisions
  (`meteo/cache_previsions.py`), les générations de parcours
  (`DepotGenerations`), les tâches de fond d'import et de calibration, les
  quotas — tous en mémoire du processus ; les fichiers temporaires d'import
  (effacés) ; l'archive d'export RGPD (produite pour être téléchargée, jamais
  relue) ; `config.toml` et `service.toml`, écrits par une personne, lus
  seulement.
- **Les versions plus anciennes** ne sont pas rééchantillonnées ici : le code
  actuel ne sait plus les écrire. Leurs migrations sont couvertes par les
  tests cités dans la table.

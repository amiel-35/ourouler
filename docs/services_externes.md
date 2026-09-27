# Services externes — ce qu'on appelle, pour quoi, et à quelles conditions

Vue d'ensemble des dépendances réseau du produit (septembre 2026). Le détail et
les justifications sont dans les docstrings des modules cités : ce fichier est
la carte, pas le territoire.

Deux règles encadrent tout ce qui suit, et elles ne se négocient pas :

- **Aucun test n'appelle le réseau** (`AGENTS.md`, « Pas de réseau dans
  les tests »). Chaque connecteur prend
  un client HTTP injectable ; les tests répondent depuis `tests/fixtures/`.
- **Aucune clé dans le dépôt** (`AGENTS.md`, « Aucune donnée personnelle ni
  clé dans le dépôt »). Les secrets vivent dans le fichier de configuration
  de l'utilisateur (ou, pour le service, dans `service.toml` et
  l'environnement du serveur), jamais commité, et n'apparaissent
  ni dans un message d'erreur, ni dans un log, ni dans un `repr`.

## En un coup d'œil

| Service | Ce qu'on lui demande | Clé | Coût | Module |
|---|---|---|---|---|
| Open-Meteo (prévision) | pluie, vent et ressenti le long du tracé | non | gratuit, non commercial | `meteo/openmeteo.py` |
| Open-Meteo (archive) | le vent qu'il faisait, pour calibrer | non | gratuit, non commercial | `connecteurs/openmeteo_archive.py` |
| BRouter | les tracés : A→B et boucles | auth basique | auto-hébergé | `connecteurs/brouter.py` |
| Intervals.icu | activités, fichiers d'origine, séances | clé perso | compte gratuit | `connecteurs/intervals.py` |
| BAN / Géoplateforme | une adresse française → coordonnées | non | Etalab 2.0 | `connecteurs/geocodage.py` |
| Nominatim (OSM) | la même chose, hors de France | non | politique d'usage stricte | `connecteurs/geocodage.py` |
| Relais SMTP (Brevo) | le courriel d'invitation et de nouveau mot de passe, en hébergé | identifiants SMTP | offre du fournisseur | `api/courriel.py` |
| Tuiles OSM | le fond de carte du front et de la carte HTML | non | politique d'usage | `front/src/composants/carte/dessin.ts`, `rendu/carte_dessin.py` |
| cdnjs (Cloudflare) | Leaflet pour la carte HTML de la ligne de commande | non | gratuit | `rendu/carte_dessin.py` |

---

## Open-Meteo — la météo, en prévision et en archive

**Prévision** (`meteo/openmeteo.py`). Gratuit, sans clé, usage non commercial.
Un seul appel HTTP porte **plusieurs points** (`latitude=a,b,c&longitude=…`) :
c'est ce qui rend tenable l'échantillonnage du tracé tous les 5 km.

Deux modèles, jamais moyennés :

- `meteofrance_arome_france_hd` — 1,3 km de maille, la France seulement ;
- `icon_seamless` — le **second avis**, qui porte plus loin dans le temps.

Quand les deux divergent, l'écran affiche un désaccord, jamais une moyenne
(`AGENTS.md`). Les
noms sont des paramètres de configuration (`[meteo] modele`, `second_avis`),
pas des constantes.

**Archive** (`connecteurs/openmeteo_archive.py`). Le vent réel d'une sortie
passée, sans lequel calibrer un CdA revient à attribuer au cycliste ce qui
appartenait à la brise. Un jour **clos** ne change plus : ces réponses-là sont
mémoïsées dans un SQLite dont le chemin est passé au constructeur. Le jour
courant, lui, bouge encore et n'est jamais écrit sur disque.

## BRouter — les tracés

Auto-hébergé sur Coolify, derrière une authentification basique. L'URL est une
adresse de serveur et peut s'afficher ; le mot de passe ne vit que dans l'objet
`httpx.BasicAuth`.

Deux usages : l'itinéraire A→B, et la **boucle** (`engineMode=4`), qui est le
cœur du produit. Profil `fastbike` par défaut.

**Ce qu'il faut savoir sur le mode boucle**, mesuré sur un serveur
réel :

- BRouter n'a pas d'algorithme de boucle. Il place `roundTripPoints` points de
  passage sur un cercle, puis fait du point-à-point entre eux. Un point qui
  tombe à côté d'une route produit un **cul-de-sac** : le moteur va le chercher
  et revient. D'où `boucle/antennes.py`, qui les détecte et les élague.
- `roundTripPoints` (5 en dur) n'est pas un réglage de forme mais **un levier
  de distance** : à rayon identique, 3 points donnent 72,8 km et 12 points
  124,1 km. `RAPPORT_RAYON_DEFAUT = 5.0`, qui sert à deviner le rayon de
  départ, se trouve être exactement le rapport mesuré à 5 points — sans que
  rien ne relie les deux dans le code.
- `allowSamewayback` attend **0 ou 1**, pas `true`/`false` : toute autre valeur
  fait répondre 500 au serveur. Son défaut est déjà 0.
- Les paramètres `profile:…` fonctionnent, **à condition d'employer le nom de
  BRouter** : `correctMisplacedViaPoints` en camelCase, et non le snake_case
  qu'envoyait le code jusqu'ici. Avec le bon nom **et** un seuil de distance à
  0, les culs-de-sac disparaissent entièrement au rayon de 20 km mesuré (0
  antenne sur 8 boucles) — mais **pas** au rayon de 8 km, balayage à
  l'appui (seuils 40/100/200/500/1000/0, 8 azimuts × 2 rayons) :
  4 boucles sur 7 y gardent encore une antenne même à seuil 0, plus courte
  qu'à tout seuil plus grand (283 m médians contre 2 827 m). Ces crochets-là
  ne sont plus des points de passage mal placés mais de vrais culs-de-sac du
  réseau routier à ce rayon, qu'aucun seuil ne recale — d'où
  `boucle/antennes.py`, qui reste un filet après coup plutôt que devenir
  inutile. Détail et table complète dans `connecteurs/brouter.py`
  (`CORRECTION_POINTS_DE_PASSAGE`).

## Intervals.icu — l'historique et les séances

Clé d'API personnelle, en authentification basique `API_KEY:<clé>`.

Ce qu'on lui demande : la liste des activités, le **fichier d'origine** d'une
activité, ses intervalles, les équipements (pour rattacher une sortie à un
vélo), et les événements planifiés — la séance du jour.

Un connecteur ne fait que rapatrier des fichiers et des métadonnées
(doctrine §5) : c'est le cache qui relit le fichier avec le lecteur unique.

## Géocodage — deux fournisseurs, aucune clé

Une adresse ambiguë est la normale, pas l'exception : le connecteur rend
toujours une **liste** de candidats notés et ne tranche jamais seul.

1. **BAN**, servie par la Géoplateforme de l'IGN. Excellente en France, au
   numéro de rue près ; **inexistante hors de France**, où elle rend zéro
   candidat sans erreur. Licence Etalab 2.0, 50 requêtes/s par IP.
2. **Nominatim** (OSM), en repli quand la BAN ne rend rien. Couverture
   mondiale, mais sa politique d'usage impose 1 requête/s, un `User-Agent`
   identifiant l'application sur **chaque** requête, l'interdiction de
   l'autocomplétion et des requêtes systématiques, et une attribution ODbL
   visible dès qu'un résultat est affiché. Le connecteur respecte les quatre.

## Le courriel

En hébergé, `ourouler inviter` et `ourouler reinitialiser` envoient leur
lien par un relais SMTP (Brevo), avec `smtplib` de la bibliothèque standard
(`api/courriel.py`). Les identifiants vivent dans la section `[brevo]` de
`service.toml` (six champs, `CHAMPS_REQUIS_BREVO` ; modèle :
`service.example.toml`). `--sans-courriel` s'en passe : le lien s'affiche
toujours dans le terminal.

## Les cartes

Le front embarque Leaflet comme dépendance npm (`front/package.json`) ; la
carte HTML de la ligne de commande (`ourouler sortie --carte`) le charge
depuis `cdnjs.cloudflare.com` (`rendu/carte_dessin.py`). Dans les deux cas,
les tuiles viennent de `tile.openstreetmap.org`, avec l'attribution OSM
obligatoire.

## Ce qui n'est pas encore branché

| Service | Pour quoi | État |
|---|---|---|
| Garmin Connect | pousser le parcours sur le compteur | rien d'installé, rien de décidé |
| Strava / Garmin (export) par lien | importer l'historique sans télécharger l'archive soi-même | non construit : l'import passe par un dépôt de fichier |

**Aucune installation sur une machine ou un serveur sans l'accord explicite de
qui l'exploite** (voir `AGENTS.md`). On propose, on attend.

## Le cache, qui n'est pas un service

`~/.cache/ourouler` (configurable) : les fichiers bruts d'activité et un index
SQLite (stdlib, pas d'ORM). C'est lui qui évite de redemander à Intervals ce
qu'on a déjà. Les scripts de mesure de `scripts/validation/` lisent ce cache,
mais sept d'entre eux interrogent aussi les services qu'ils mesurent :
Intervals (`arrets_bloc_recup`, `orientation_vent_retrospectif`,
`terrain_retrospectif`, `vent_retrospectif`), l'archive Open-Meteo
(`cda_position_retrospectif`, `orientation_vent_retrospectif`,
`vent_retrospectif`) et BRouter (`arrets_bloc_recup`, `marqueurs_retrospectif`,
`trafic_estime_retrospectif`). Ils se lancent à la main, jamais en test.

## Les archives d'export, mesurées sur de vraies données

Une archive Garmin et une archive Strava réelles ont été demandées et lues
avant d'écrire l'import ; les mesures (tailles, agencement, liens) sont
dans [`journal/archives_export_mesures.md`](journal/archives_export_mesures.md).
Ce qu'elles fixent, et que le code applique
(`src/ourouler/activites/import_archive.py`) :

- **Une liste blanche d'entrées.** Seuls les fichiers d'activité (`.fit`,
  `.gpx`, `.tcx`, éventuellement en `.gz`) et les `.zip` imbriqués sont lus
  (`EXTENSIONS_ACTIVITE`) ; tout le reste de l'archive — photos et vidéos,
  qui en font l'essentiel chez Strava, contacts, messages, identifiants
  d'appareils — est ignoré sans être extrait.
- **Des bornes vérifiées à la lecture, à chaque niveau d'imbrication.**
  Garmin range les sorties dans des `.zip` à l'intérieur du `.zip` ; le
  ratio de décompression de l'enveloppe intérieure y est bien plus fort
  que celui de l'extérieure, donc un plafond posé sur l'enveloppe seule ne
  verrait rien (`RATIO_MAX_DECOMPRESSION`, `PROFONDEUR_MAX_ARCHIVE`).
- **Un délai non garanti.** Une plateforme peut livrer l'archive dans
  l'heure comme en plusieurs jours : ne rien promettre au cycliste au-delà
  de « de quelques heures à quelques jours ».

Et pour ce qui n'est pas construit — importer par **lien** plutôt que par
fichier, ou lire le profil (FTP, zones) dans l'archive :

- les deux plateformes servent leur archive depuis une URL S3 pré-signée ;
  une liste blanche porterait sur l'hôte **et** le préfixe de chemin, à
  chaque redirection, pas seulement sur l'URL collée ;
- `HEAD` y est refusé : la taille se lit sur le `GET` ;
- S3 accepte les requêtes par plage (`Range`) : on lit la liste des
  entrées à la fin du `.zip` sans télécharger le reste ;
- les zones de puissance d'une archive Garmin peuvent être celles d'un
  autre sport : **filtrer sur le sport** avant d'en tirer une FTP.

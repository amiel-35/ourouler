# Services externes — ce qu'on appelle, pour quoi, et à quelles conditions

Vue d'ensemble des dépendances réseau du produit, au 18/09/2026. Le détail et
les justifications sont dans les docstrings des modules cités : ce fichier est
la carte, pas le territoire.

Deux règles encadrent tout ce qui suit, et elles ne se négocient pas :

- **Aucun test n'appelle le réseau** (règle absolue 3). Chaque connecteur prend
  un client HTTP injectable ; les tests répondent depuis `tests/fixtures/`.
- **Aucune clé dans le dépôt** (règle absolue 1). Les secrets vivent dans le
  fichier de configuration de l'utilisateur, jamais commité, et n'apparaissent
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
| Tuiles OSM | le fond de carte du front | non | politique d'usage | `front/src/composants/Carte.tsx` |

---

## Open-Meteo — la météo, en prévision et en archive

**Prévision** (`meteo/openmeteo.py`). Gratuit, sans clé, usage non commercial.
Un seul appel HTTP porte **plusieurs points** (`latitude=a,b,c&longitude=…`) :
c'est ce qui rend tenable l'échantillonnage du tracé tous les 5 km.

Deux modèles, jamais moyennés :

- `meteofrance_arome_france_hd` — 1,3 km de maille, la France seulement ;
- `icon_seamless` — le **second avis**, qui porte plus loin dans le temps.

Quand les deux divergent, l'écran affiche un désaccord (règle absolue 5). Les
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

**Ce qu'il faut savoir sur le mode boucle**, mesuré le 18/09/2026 sur le
serveur réel :

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
  0, les culs-de-sac disparaissent entièrement (0 antenne sur 8 boucles).

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

## Le front

Leaflet est chargé depuis `cdnjs.cloudflare.com`, les tuiles viennent de
`tile.openstreetmap.org`, avec l'attribution OSM obligatoire.

## Ce qui n'est pas encore branché

| Service | Pour quoi | État |
|---|---|---|
| Brevo | le courriel d'inscription, modérée par le mainteneur | clé promise, rien d'écrit |
| Garmin Connect | pousser le parcours sur le compteur | rien d'installé, rien de décidé |
| Strava / Garmin (export) | importer l'historique d'un nouvel utilisateur | tranché en [[Q48]] : V1 couvre les deux, par dépôt de fichier |

**Aucune installation sur une machine ou un serveur sans l'accord explicite du
mainteneur** (règle absolue 7). On propose, on attend.

## Le cache, qui n'est pas un service

`~/.cache/ourouler` (configurable) : les fichiers bruts d'activité et un index
SQLite (stdlib, pas d'ORM). C'est lui qui évite de redemander à Intervals ce
qu'on a déjà, et c'est sur lui seul que travaillent les scripts de mesure de
`tests/validation/` — aucun d'eux ne sort sur le réseau.

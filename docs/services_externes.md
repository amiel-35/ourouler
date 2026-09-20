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
  0, les culs-de-sac disparaissent entièrement au rayon de 20 km mesuré (0
  antenne sur 8 boucles) — mais **pas** au rayon de 8 km, sweep du
  18/09/2026 à l'appui (seuils 40/100/200/500/1000/0, 8 azimuts × 2 rayons) :
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

## Les archives d'export, mesurées sur de vraies données (19/09/2026)

Tout ce chapitre vient de **deux archives réelles du mainteneur**, demandées et
lues le 19/09/2026 — pas d'une documentation de plateforme. Ce qu'on croyait
savoir avant ([[Q48]]) était faux sur plusieurs points, tous corrigés ici.

### Le lien n'est pas celui de la plateforme, et il change à chaque saut

| | Garmin | Strava |
|---|---|---|
| hôte final | `s3.amazonaws.com` | `s3.amazonaws.com` |
| préfixe de chemin | `it-gdpr-bucket/` | `strava.portability/athlete/<id>/export/live/` |
| validité | **3 jours** (`X-Amz-Expires=259200`) | à mesurer |
| taille | 240 Mo | **665 Mo** |
| redirections avant d'y arriver | aucune | **deux** |

Trois conséquences qui décident de l'implémentation :

1. **La liste blanche porte sur l'hôte *et* le préfixe de chemin.** Les deux
   plateformes servent depuis `s3.amazonaws.com`, où la moitié d'Internet est
   hébergée : l'hôte seul ne filtre rien. C'est le préfixe qui discrimine.
2. **Elle s'applique à chaque saut, pas à ce que la personne colle.** Le lien
   Strava reçu par le mainteneur traversait une enveloppe
   `safelinks.protection.outlook.com` (ajoutée par sa messagerie) puis un
   traceur `email.strava.com`, avant d'atteindre S3. Vérifier seulement l'URL
   collée laisserait passer n'importe quoi ; ne pas suivre les redirections du
   tout casserait le cas normal.
3. **`HEAD` est refusé (403).** Une URL S3 pré-signée n'est valable que pour la
   méthode signée, ici `GET`. Sonder la taille avant de télécharger ne marche
   pas — il faut lire `Content-Length` sur le `GET` lui-même.

### On n'a pas besoin de télécharger l'archive

**S3 accepte les requêtes par plage** (`Range`, réponse `206`). Le répertoire
central d'un zip étant à la fin, on lit **la liste complète des entrées** en
récupérant les derniers mégaoctets, puis on ne va chercher que les octets des
entrées qu'on veut.

Mesuré sur l'archive Strava : **les 3 730 entrées lues en téléchargeant 4 Mo
sur 665**. Ce qui nous intéresse vraiment — `activities.csv`, `profile.csv`,
`bikes.csv` et un an de sorties — tient dans l'ordre de 20 Mo.

C'est ce qui fait de la **liste blanche d'entrées** la pièce centrale plutôt
qu'une précaution après coup : elle ne décide plus seulement de ce qu'on
extrait, elle décide de ce qu'on **télécharge**. Et moins on extrait, moins il
y a à isoler.

### Garmin : où sont les choses, et les pièges

```
DI_CONNECT/DI-Connect-Uploaded-Files/UploadedFiles_0-_Part{1..6}.zip   238 Mo
DI_CONNECT/DI-Connect-Wellness/<id>_powerZones.json
DI_CONNECT/DI-Connect-Wellness/<id>_heartRateZones.json
DI_CONNECT/DI-Connect-Wellness/<id>_bioMetrics_latest.json
customer_data/customer.json
```

Le profil **y est** : FTP et paliers de puissance, FCmax, FC de repos, seuil
lactique, zones cardiaques. C'est ce qui permet à l'étage export de rendre ce
que la route `athlete` d'Intervals rend ([[Q64]]) — pour beaucoup plus de
monde, puisque peu de cyclistes ont Intervals.

Trois pièges, tous rencontrés :

- **Les zones trouvées peuvent être celles d'un autre sport.** Le
  `powerZones.json` du mainteneur porte `sport = RUNNING` et une FTP de 401 W,
  quand sa FTP vélo est 235. Prendre le premier fichier de zones donnerait un
  cycliste trois fois trop fort — et **401 W est un nombre plausible**, donc
  l'erreur ne se verrait pas. **Filtrer sur le sport.** La confirmation par
  l'utilisateur ne rattrape pas ce cas : celui qui ne connaît pas sa FTP —
  précisément celui pour qui l'entonnoir existe — cliquera « oui ».
- **Les sorties sont dans des archives imbriquées.** Six `.zip` dans le `.zip`.
- **Le ratio de décompression y est de 11**, quand celui de l'enveloppe
  extérieure est de 1,5 : 9 Mo qui deviennent 100, pour 2 487 fichiers. Un
  plafond de ratio posé sur l'enveloppe ne verrait rien.

### Strava : où sont les choses, et ce qu'on ignore

```
activities.csv        1,1 Mo   l'index de toutes les sorties, sans en ouvrir une
profile.csv                    l'athlète
bikes.csv                      les vélos, avec leurs noms
activities/           165 Mo   2 613 .fit.gz et 311 .gpx
media/                504 Mo   photos et vidéos — 76 % de l'archive
routes/                27 Mo
```

**76 % de l'archive sont des photos et des vidéos**, dont ce produit n'a aucun
usage. Sans liste blanche, on les ferait traverser le serveur pour rien.

Et ce qu'on ne doit **jamais** lire, présent dans la même archive :
`contacts.csv`, `followers.csv`, `following.csv`, `messaging.json`,
`reactions.csv`, `logins.csv`, `mobile_device_identifiers.csv`. Ne pas
extraire une donnée personnelle est la seule façon sûre de ne pas la
conserver (règle absolue 1).

### Ce que ça corrige dans [[Q48]]

- « Garmin met plusieurs jours là où Strava met des heures » : le mainteneur a
  reçu son archive Garmin **le jour même**. La conclusion de Q48 reste bonne —
  le parcours doit survivre à une interruption longue — mais parce que le
  délai **n'est pas garanti**, pas parce qu'il serait toujours long. Ne rien
  promettre au cycliste au-delà de « de quelques heures à quelques jours ».
- « durée de validité inconnue chez Garmin » : **3 jours**, dit par le
  courriel et confirmé par le paramètre signé.
- « agencement interne de l'archive, seul point qui demande un adaptateur » :
  vrai, et c'est plus que de la lecture — c'est la **liste de ce qu'on va
  chercher**, par plateforme, qui décide aussi du réseau consommé.

### Non vérifié

L'export en plusieurs parties. Le fichier Garmin s'appelle `<uuid>_1.zip`, ce
que le suffixe rend suspect, mais rien ne dit qu'un `_2` existe et aucun n'a
été observé. Hypothèse retenue : **une seule archive** ([[Q62]], tranchée par
le mainteneur). Si un jour un `_2` existe, il doit se **voir** plutôt que
d'importer la moitié d'un historique en silence.

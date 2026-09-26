# Guide de la ligne de commande

Le mode d'emploi de `ourouler`, commande par commande, puis ses limites
connues. Pour savoir comment le projet s'est construit et ce qu'il a appris
en chemin, voir `docs/demarche.md`. Pour les choix d'architecture,
`doctrine_architecture.md`.

Toutes les commandes acceptent `--help`, et `--json` pour qu'un autre
programme lise le résultat (avant ou après le nom de la sous-commande).
`--config FICHIER` charge un autre fichier que
`~/.config/ourouler/config.toml`.

## Installer

Pour développer ou utiliser la ligne de commande sur sa machine :

```bash
uv sync --frozen --extra dev
mkdir -p ~/.config/ourouler && cp config.example.toml ~/.config/ourouler/config.toml
uv run ourouler config
```

Renseigner ensuite, dans le fichier copié :

- `[depart]` : le point de départ habituel (nom, latitude, longitude) ;
- `[cycliste]` : la masse et la FTP ;
- `[[velos]]` : un bloc par vélo, avec son usage (`route` ou `clm`), sa
  masse, et de préférence sa catégorie de `pneu`, qui fixe le roulement ;
- `[intervals]` : la clé d'API Intervals.icu et l'identifiant du compte,
  pour la synchronisation et la séance du jour ;
- `[brouter]` : l'adresse d'un serveur BRouter, sans quoi `boucle` et
  `sortie` ne peuvent pas tracer. Recette pour en obtenir un :
  `docs/brouter.md`.

`ourouler config` relit le fichier, dit ce qui manque et affiche ce que le
modèle en déduit : la puissance d'endurance en watts, la vitesse à plat et
la moyenne au compteur, avec leur provenance (mesurée ou supposée).

Les données et les clés restent chez l'utilisateur. Le vrai fichier de
configuration n'est jamais commité ; `config.example.toml` ne porte que des
valeurs inventées, et `tests/test_invariants.py` le vérifie. L'extra `dev`
installe aussi les dépendances de l'API, pour que la suite de tests la
couvre.

Vérifier avant tout commit (détail dans `CONTRIBUTING.md`) :

```bash
uv run ruff check .
uv run pytest -q
cd front && npm run verifier
```

## Ce que fait la ligne de commande

| Commande | Rôle |
|---|---|
| `config` | vérifie et affiche la configuration chargée |
| `inventaire` | lit les FIT / GPX / TCX, les range dans le cache local, liste les sorties par vélo et par mois ; synchronise Intervals.icu |
| `meteo` | pluie, vent et ressenti par direction et par heure autour du départ, avec l'accord ou le désaccord de deux modèles |
| `boucle` | boucles de la bonne distance, notées sur le trafic, le revêtement, les virages, la pluie et le vent à l'heure de passage ; GPX |
| `routes` | apprend sur les sorties passées quelles routes le cycliste accepte, et en tire les poids du score |
| `calibrer` | ajuste le modèle physique d'un vélo sur ses sorties réelles et mesure son erreur sur des sorties qu'il n'a pas vues |
| `simuler` | temps en mouvement d'un GPX à puissance tenue, avec le modèle calibré et le vent prévu |
| `analyser` | pour un parcours déjà en main (brevet, boucle de club) : durée porte à porte en fourchette, météo par tronçon à l'heure où on y passe, heure d'arrivée |
| `comparer` | de combien un vélo va plus vite que l'autre à puissance égale, sans modèle physique |
| `seance` | la séance planifiée du jour, étape par étape, avec la longueur de route que chaque bloc demande |
| `sortie` | la séance du jour posée sur des boucles : propositions contrastées, GPX du parcours réellement roulé, tenue, carte HTML de vérification |
| `geocoder` | convertit une adresse en coordonnées et montre tous les candidats |
| `api` | sert l'API HTTP que consomme l'interface web |
| `inviter`, `invitations`, `reinitialiser`, `retirer` | administration des comptes du service hébergé |

Il n'y a pas d'envoi direct vers Garmin Connect : aucune API n'est ouverte
aux particuliers. Le GPX produit est le socle ; sur téléphone, l'interface
web le partage vers l'application du compteur par le menu de partage du
système.

## L'heure et le lieu de départ

L'heure de départ s'appelle **`--heure-depart`**, sur `meteo`, `boucle`,
`simuler` et `sortie`. Elle accepte `HH:MM` ou `AAAA-MM-JJTHH:MM`.

Le lieu de départ s'appelle **`--adresse-depart`**, sur `meteo`, `boucle`
et `sortie`. Deux noms explicites plutôt que deux noms qui se ressemblent.

```
ourouler meteo --heure-depart 08:00 --horizon 6
ourouler meteo --adresse-depart "7 rue du If 44999 Vallombreuse" --horizon 6
ourouler boucle --adresse-depart "12 place de la Gare 44999 Vallombreuse" --distance 60 --direction S
```

Les adresses de ces exemples sont **inventées**, comme partout dans ce
dépôt : aucune adresse réelle n'y figure, pas même dans un exemple.

L'adresse est géocodée, et la configuration n'est pas modifiée : c'est un
départ pour cette fois. **Écrivez la commune.** « 12 rue de la Gare » existe
dans des centaines de communes, et le score du géocodeur ne distingue pas une
réponse juste d'une réponse arbitraire. La ligne de commande refuse donc une
adresse dont les candidats ne désignent pas tous la même commune : elle les
affiche avec leur commune et sort en erreur (code 2). Une adresse
introuvable est aussi une erreur. Dans les deux cas, la commande ne retombe
**jamais** sur le départ configuré : une boucle autour de chez soi pour qui
a demandé une autre ville serait une réponse fausse, pas une erreur.

```
ourouler geocoder "place de la Mairie"           # tous les candidats, notés
ourouler geocoder "place de la Mairie" --max 10
```

Une réserve : les routes connues et les poids appris ont été mesurés autour
du départ configuré. Loin de là, « connu % » tombe à zéro sans que le tracé
soit inédit pour autant, et la commande le dit.

Les anciens noms `--depart` et `--heure` restent acceptés pour ne rien
casser, mais l'aide ne les propose plus.

## `meteo` — où va-t-il pleuvoir ?

```
ourouler meteo                          # maintenant, horizon de la configuration
ourouler meteo --heure-depart 14:00 --horizon 4
ourouler meteo --distance 25            # une seule couronne
```

Autour du départ, une couronne de points (8 ou 16 directions, à plusieurs
distances, réglées dans `[meteo]`) interrogée heure par heure : pluie en
mm/h, vent (force, direction, de face ou de dos selon la direction),
température ressentie. Le modèle principal est AROME haute résolution de
Météo-France ; un second modèle donne un second avis. Quand les deux
divergent, la cellule le dit : c'est un indice de confiance, jamais une
moyenne. `--modele` et `--second-avis` changent l'un ou l'autre.

AROME ne va pas au-delà d'environ deux jours et demi : au-delà, la commande
se replie sur le second modèle. Au-delà de `horizon_jours`, elle déclare la
météo absente plutôt que d'inventer.

## `boucle` — une boucle de la bonne distance

```
ourouler boucle --distance 60 --direction NE
ourouler boucle --distance 80                          # candidates tout autour
ourouler boucle --distance 60 --sortie ~/boucle.gpx
ourouler boucle --gpx parcours.gpx                     # évaluer un tracé existant
ourouler boucle --distance 90 --vitesse-a-plat 28      # sans connaître sa puissance
ourouler boucle --distance 180 --pause 90:0h45         # un arrêt déclaré
```

La commande demande au moteur BRouter plusieurs boucles (`--candidates`,
défaut dans `[boucle]`) et les note :

- **trafic** et **revêtement** : chaque kilomètre de route passante ou non
  revêtue coûte plus qu'un kilomètre calme, selon des poids par classe de
  route que `routes poids --appliquer` peut remplacer par ceux appris sur
  vos sorties ;
- **virages à gauche** et **sens de la boucle** (horaire par défaut,
  réglable) ;
- **antennes** : un aller-retour en cul-de-sac est détecté et élagué ;
- **pluie et vent le long du tracé, à l'heure de passage**, pas à l'heure
  du départ ;
- **« connu % »** : la part de la boucle déjà roulée. Informative
  seulement, elle n'entre dans aucun score.

Le temps estimé vient du modèle physique du vélo (`--velo`), à une
puissance tenue (`--puissance`, défaut : une part de la FTP) ou déduite
d'une vitesse tenue à plat (`--vitesse-a-plat`). Il est donné en **temps en
mouvement**, puis en **fourchette porte à porte** : le temps simulé
multiplié par la fourchette que la calibration du vélo a mesurée, ou par une
convention générique, dite comme telle, quand le vélo n'est pas calibré.

`--pause KM:DUREE` (répétable, par exemple `180:0h45`) décale l'heure de
passage météo des points suivants, jamais le temps en mouvement.

`--sortie` écrit la boucle retenue en GPX ; `--ecraser` remplace un fichier
existant. `--gpx` évalue un tracé importé au lieu d'en générer un.
`--profil` choisit un autre profil BRouter (`fastbike` par défaut).

## `seance` — la séance du jour

```
ourouler seance                                   # aujourd'hui, depuis Intervals.icu
ourouler seance --jour AAAA-MM-JJ
ourouler seance --depuis AAAA-MM-JJ --jusqua AAAA-MM-JJ
ourouler seance --fichier-seance seance.zwo       # ou .mrc, sans Intervals
```

La séance planifiée, étape par étape : échauffement, blocs, récupérations,
retour au calme, avec leur puissance cible. Pour chaque bloc, la longueur de
route qu'il demande à la vitesse du modèle, et celle qu'il faut au-delà pour
faire demi-tour pendant la récupération.

## `sortie` — la séance posée sur le terrain

```
ourouler sortie                                     # la séance du jour
ourouler sortie --jour AAAA-MM-JJ --heure-depart 09:30 --candidates 4
ourouler sortie --vent retour-dos                   # rentrer avec le vent
ourouler sortie --direction SO
ourouler sortie --fichier-seance seance.zwo --jour AAAA-MM-JJ
```

La commande enchaîne tout : elle lit la séance, dimensionne la boucle
(`--distance`, défaut : la distance estimée de la séance, arrondie au
multiple de 5 km supérieur), génère des candidates, place les blocs sur
chacune et rend :

- **des propositions contrastées**, chacune meilleure sur un axe différent
  (la plus sèche, la meilleure pour les blocs, la plus calme, la plus
  proche de la durée prévue…), avec une phrase qui dit ce qui la
  distingue. Quand les candidates ne se distinguent pas assez, il y en a
  moins de trois, et la commande nomme les axes restés muets ;
- le **GPX du parcours réellement roulé**, demi-tours compris ;
- la **tenue** à mettre, dans l'horizon de prévision ;
- une **carte HTML de vérification** : le tracé, les blocs colorés à leur
  place, le vent, le profil d'altitude.

Le placement suit quelques règles fixes. Seules la zone 2 d'ouverture et
celle de retour au calme sont élastiques ; les récupérations et les blocs ne
bougent jamais. Une récupération peut absorber un village ou un demi-tour ;
un bloc, lui, est noté sur le terrain qu'il traverse (zone bâtie, descente,
virages, carrefours), et la note de la descente croît avec l'intensité du
bloc. **On note, on ne filtre pas** : si aucune boucle n'est parfaite, la
moins mauvaise est proposée avec ce qui cloche.

`--vent` (`peu-importe`, `retour-dos`, `depart-dos`, `travers`) remplace
`--direction` : on choisit sa direction, ou on la laisse déduire du vent.
L'orientation au vent n'est proposée que sur les trois prochains jours ;
au-delà, la prévision de direction n'est plus assez sûre.

Par défaut, le GPX et la carte s'écrivent dans le dossier `sorties/` du
cache, jamais dans le dépôt ; `--sortie` et `--carte` choisissent
d'autres chemins, `--ecraser` remplace l'existant. `--carte-sans-seance`
écrit quand même une page « rien de prévu » un jour sans séance, pour un
service planifié.

Sur un jour passé, hors de l'horizon de prévision, pluie, vent et tenue
disparaissent du tableau, et le tableau le dit.

## `simuler` — combien de temps sur ce parcours ?

```
ourouler simuler --gpx parcours.gpx --puissance 180
ourouler simuler --gpx parcours.gpx --vitesse-a-plat 27 --heure-depart 08:00
ourouler simuler --gpx parcours.gpx --puissance 180 --pause 60:0h20
```

Le temps en mouvement du parcours à puissance constante, avec le modèle
calibré du vélo (`--velo`) et, si `--heure-depart` est donné, le vent
prévu le long du tracé.

## `analyser` — un parcours qu'on a déjà

```
ourouler analyser --gpx brevet.gpx --heure-depart 2026-10-04T06:00
ourouler analyser --gpx boucle_club.gpx --vitesse-a-plat 28 --heure-depart 08:30
```

Pour un tracé imposé (l'itinéraire d'un brevet, la boucle du club) : la
durée porte à porte en fourchette, l'heure d'arrivée, et la météo de chaque
tronçon à l'heure où l'on y passe. `--heure-depart` est obligatoire ; la
puissance vient de `--puissance`, de `--vitesse-a-plat`, ou à défaut de la
puissance d'endurance du profil. Au-delà de l'horizon de prévision, la
météo est déclarée absente plutôt qu'inventée.

## `calibrer` — le modèle physique d'un vélo

```
ourouler calibrer --velo Route
ourouler calibrer --velo Route --max 60        # les 60 sorties les plus récentes
ourouler calibrer --velo Route --crr-libre     # l'ancienne méthode
```

Le modèle relie puissance, masse, traînée (CdA), roulement (Crr), pente et
vent. La calibration l'ajuste sur les sorties extérieures du vélo, vent
d'archive Open-Meteo compris, et en garde une part (`part_validation`, un
quart par défaut, les plus récentes) pour mesurer l'erreur sur des sorties
qu'elle n'a pas vues.

Méthode :

- le **roulement est fixé** par la catégorie de `pneu` du vélo (ou par un
  `crr` écrit à la main) ; seul le **CdA est cherché**. Laissés libres
  ensemble, les deux se compensent sur ces données. `--crr-libre` garde
  l'ancienne méthode, à deux paramètres ;
- le CdA est cherché sur l'**erreur de temps en mouvement** des sorties,
  pas tronçon par tronçon ;
- les **sorties en groupe** sont écartées : par leur nom (`mots_groupe`),
  puis par leur signal physique, une vitesse trop haute pour la puissance
  que ni la pente ni le vent n'expliquent. Au-delà de `part_groupe_max` de
  distance « en roue », une sortie ne sert pas à chercher le CdA ;
- la **fourchette porte à porte** (temps écoulé sur temps simulé, du
  quartile bas au quartile haut) est mesurée sur les seules sorties de
  validation roulées seul, quand il y en a assez ; sinon, la convention
  générique s'applique et le rapport le dit.

Le rapport donne l'erreur moyenne et le biais sur les sorties de
validation, la puissance nécessaire à plusieurs vitesses sur le plat sans
vent, et la fourchette. **Le CdA calibré est un paramètre de compensation**,
pas une mesure : il absorbe entre autres l'étalonnage du capteur de
puissance. Il ne se compare ni à la littérature ni d'un vélo à l'autre ; ce
qui se lit, c'est la puissance à une vitesse donnée et l'erreur de temps.

Un pneu changé depuis la calibration est signalé, sans que la calibration
soit jetée.

## `comparer` — deux vélos à puissance égale

```
ourouler comparer --velos Route CLM                     # écart de vitesse à puissance égale
ourouler comparer --velos Route CLM --pente-max 0.005   # plat plus strict
ourouler comparer --velos Route CLM --cap-max 15        # ne garder que les lignes droites
ourouler comparer --velos Route CLM --zone 0.60 0.70
```

Aucun modèle physique n'intervient dans la mesure. Les sorties des deux
vélos sont découpées en tronçons de 200 m ; on ne garde que les tronçons
plats (`--pente-max`, 0,8 % par défaut), sans arrêt ni relance, dont la
puissance tombe dans la zone choisie (`--zone`, la zone 2 par défaut) ; on
les recolle en **séries** consécutives d'au moins `--longueur-min` mètres
(500 par défaut) ; et on compare la vitesse des séries à puissance égale,
par une régression `vitesse = a + b·puissance` lue au milieu de la zone.

**La mesure est en km/h**, les watts n'en sont qu'une conversion : par la
loi en v³ (`ΔP ≈ 3·P·Δv/v`) ou par la calibration du vélo de référence,
les deux affichées avec leur formule. Retenir une fourchette, jamais un
chiffre au watt près. Le nombre de mailles communes aux deux vélos est
indiqué pour dire à quel point ils ont roulé aux mêmes endroits, mais il ne
filtre rien : les séries plates et droites d'un vélo de route et d'un vélo
de contre-la-montre ne se superposent pas assez pour qu'il en reste quelque
chose. Aucun appel réseau : tout vient du cache.

## `routes` — apprendre ses routes

```
ourouler routes apprendre              # rejoue les sorties du cache dans BRouter (idempotent)
ourouler routes apprendre --max 10     # borne les appels au moteur, pour essayer
ourouler routes stats                  # km et part par classe de route, part semaine
ourouler routes poids                  # compare vos sorties à huit boucles d'exposition
ourouler routes poids --appliquer      # écrit les poids ; `boucle` les utilise
```

`apprendre` rejoue chaque sortie extérieure dans BRouter pour en obtenir
les tags de chaque tronçon (classe de route, revêtement…). `poids` compare
ce que vous roulez à ce que le moteur propose autour de chez vous et en
déduit un poids par classe de route.

Les traces servent à **apprendre**, jamais de critère : elles ne couvrent
qu'une partie du territoire, et pénaliser ce qu'elles ignorent condamnerait
toute boucle vers une direction jamais explorée. La colonne « connu % » de
`boucle` est informative et n'entre dans aucun score.

## `inventaire` — les sorties en cache

```
ourouler inventaire                          # depuis historique_depuis
ourouler inventaire --synchroniser           # rapatrie les activités Intervals.icu
ourouler inventaire --importer ~/exports/    # indexe les FIT/GPX/TCX d'un dossier
ourouler inventaire --depuis AAAA-MM-JJ
```

Un seul lecteur pour les trois formats, un cache local (fichiers bruts et
index SQLite, dans `~/.cache/ourouler` par défaut), et l'inventaire des
sorties par vélo et par mois. Le rattachement d'une sortie à un vélo suit
des règles configurables : équipement Intervals, capteur de puissance,
période. Une seconde synchronisation n'ajoute ni ne retélécharge rien ;
`--sans-rafraichir` saute aussi la mise à jour des métadonnées.

La fenêtre d'historique commence à `historique_depuis`, à la racine du
fichier de configuration : avant cette date, un autre matériel ou une autre
position rendraient la calibration moins fiable.

## Le service hébergé

La ligne de commande n'est qu'un adaptateur du cœur. L'API en est un second,
l'interface web un troisième, qui ne parle qu'à l'API.

### L'API

Chaque route rend le même JSON que la sous-commande correspondante avec
`--json` : l'API expose ce que la ligne de commande sait déjà rendre. Selon
`OUROULER_API_CHEMIN`, elle y arrive par la commande elle-même (`ancien`, le
défaut) ou en appelant directement le service et le rendu (`nouveau`) ; voir
`ARCHITECTURE.md` §4.

```bash
uv sync --extra api
uv run ourouler api --port 8000     # puis http://127.0.0.1:8000/docs
```

Les routes et la forme des réponses se lisent dans la documentation
interactive (`/docs`) ; la référence figée est
`tests/caracterisation/openapi.json`. En mode hébergé,
chaque compte a des quotas journaliers (générations, consultations météo,
calibrations, imports) ; un quota atteint rend un refus lisible.
FastAPI et son serveur sont un extra : la ligne de commande s'installe et
tourne sans.

### L'interface web

L'interface du cycliste vit dans `front/`. Elle **ne parle qu'à l'API**,
jamais au cœur Python, et n'affiche rien que l'API n'ait rendu.

```bash
uv run ourouler api --port 8000            # dans un terminal
cd front && npm ci && npm run dev          # dans un autre, puis http://localhost:5180
```

`npm run verifier` passe les types et les tests ; aucun test du front ne
touche au réseau. Les écrans et l'organisation du code sont décrits dans
`front/README.md`.

### Le déploiement

Le paquetage `deploiement/api/` (`deploiement/api/README.md`), à essayer
d'abord sur sa propre machine avec `docker compose` : un seul conteneur qui
sert l'API et, dessous, l'interface construite, avec les comptes dans
PostgreSQL.

En mode hébergé, le point de départ, le cycliste, les vélos et la clé
Intervals appartiennent à chaque compte : le serveur refuse de démarrer si
sa propre configuration les porte.

### Administrer les comptes

L'entrée se fait sur invitation seulement. Ces commandes se lancent sur le
serveur, avec sa configuration :

```
ourouler inviter adresse@exemple.org                  # crée l'invitation, affiche le lien
ourouler inviter adresse@exemple.org --sans-courriel  # le lien seul, sans courriel
ourouler invitations                                  # invitations en cours
ourouler reinitialiser adresse@exemple.org            # lien de nouveau mot de passe
ourouler retirer adresse@exemple.org                  # ferme le compte et efface ses données
```

Le lien d'invitation s'affiche toujours ; le courriel n'est qu'un plus.
`retirer` suit le même chemin que la suppression demandée par la personne
elle-même depuis l'interface, et demande confirmation sauf avec `--oui`. Il
se lance **dans** le conteneur du serveur, pas depuis un poste : il lit
la configuration du serveur par la variable `OUROULER_CONFIG`, et
`--config` n'y a aucun effet. Le mode d'emploi complet, de la préparation du
serveur à ce que voit l'invité, est dans `docs/inviter.md`.

## Limites connues

Ce qu'il faut savoir avant de lire un chiffre.

- **Le temps simulé est un temps en mouvement.** Il ne compte ni les feux,
  ni les stops, ni les ravitaillements, et la simulation d'un parcours est
  un modèle d'équilibre, sans accélération ni relance. Le porte à porte est
  donc donné en fourchette, mesurée sur les sorties passées du vélo ou
  prise dans une convention générique. L'erreur du modèle sur une sortie
  isolée est du même ordre que la correction elle-même : la fourchette dit
  cette incertitude au lieu de la cacher derrière un chiffre unique.
- **Le CdA calibré n'est pas une mesure physique.** Le roulement est fixé
  par le pneu, et le CdA absorbe tout le reste, étalonnage du capteur
  compris. Le modèle prédit correctement le temps dans la plage de
  vitesses et de terrains des sorties qui l'ont calibré, et se tromperait
  hors de cette plage — en haute montagne par exemple, qu'aucune sortie
  d'apprentissage ne couvre.
- **Avec peu de sorties, la calibration bouge.** Autour du minimum requis,
  la puissance annoncée à une vitesse donnée peut varier de plusieurs
  pour cent d'un essai à l'autre. L'erreur de validation affichée le laisse
  deviner ; plus d'historique la stabilise.
- **Une sortie roulée en partie dans une roue fausse la calibration.** Le
  filtre de groupe écarte les sorties franchement en peloton et limite
  l'apprentissage aux sorties presque solo, mais un effet de roue discret
  peut passer. Les sorties importées en fichier ne portent pas le nom que
  leur donne Intervals.icu : le filtre par nom (« club », « groupe »…) ne
  s'y applique pas.
- **Le vent météo n'est pas le vent du cycliste.** Archive et prévision le
  donnent à 10 m du sol ; un facteur 0,6 (profil logarithmique, campagne
  bocagère) le ramène à 1,5 m. C'est une hypothèse de rugosité moyenne, pas
  une mesure : une route abritée par une haie et une route en plein champ
  le subissent différemment, et rien ici ne les distingue.
- **L'écart entre deux vélos est un ordre de grandeur**, pas une mesure de
  soufflerie. Deux séries n'ont ni le même vent, ni la même fraîcheur, ni
  le même sens de passage : sur des centaines de séries ces écarts se
  compensent en partie, ils ne s'annulent pas. Citer la fourchette en
  watts, jamais un chiffre au watt près.
- **D+ du moteur ou D+ relu, ce n'est pas le même chiffre.** BRouter donne
  son dénivelé filtré ; relire un GPX le recalcule depuis les altitudes,
  avec un seuil de 2 m, et trouve couramment 30 à 40 % de plus. Les deux
  sont affichés avec leur provenance (« moteur », « gpx relu ») plutôt que
  moyennés ou choisis en silence. Dans l'interface web, cette provenance ne
  s'affiche pas encore.
- **Classes de trafic.** Par défaut, une route `primary`, `secondary` ou
  `trunk` d'OpenStreetMap compte « à trafic », et un kilomètre à trafic en
  coûte trois : c'est un arbitrage, pas une mesure. Or une bonne part des
  routes que les cyclistes empruntent réellement sont des `secondary`.
  `routes poids --appliquer` remplace ces poids par ceux appris sur vos
  propres sorties. Les kilomètres que le classement ne sait pas trancher
  sont affichés à part (`km_non_classe`) plutôt que fondus dans « calme ».
- **`maxspeed` absent des tags BRouter.** Le profil `fastbike` n'expose pas
  `maxspeed` : la table « par maxspeed » de `routes stats` est donc vide, et
  le dit plutôt que d'inventer une vitesse.
- **Routes hors de la région chargée sur le serveur.** BRouter ne route que
  sur les tuiles OpenStreetMap présentes sur le serveur. Une sortie de
  vacances loin de là ne peut pas être rejouée ; elle est comptée en échec,
  avec le message du moteur.
- **Activités multisport.** Intervals.icu découpe une épreuve enchaînée
  (natation, vélo, course) en segments qui citent le même fichier
  d'origine. Chaque segment a sa propre ligne de
  cache, et le fichier brut est partagé. Seuls les segments que la source
  annonce comme du vélo entrent dans l'inventaire vélo ; natation et
  transitions restent dehors, et les fichiers multisport sont écartés de la
  calibration.
- **La météo n'existe que dans l'horizon de prévision.** Sur un jour passé
  ou trop lointain, pluie, vent et tenue disparaissent, et la commande le
  dit.
- **Le coût d'un carrefour sous un bloc n'est validé par aucune mesure.**
  Une trace GPS ne porte pas de nœud OpenStreetMap : ce poids est un
  raisonnement produit, et son commentaire dans le code le dit.

## Pour aller plus loin

- `docs/demarche.md` — comment le projet s'est construit, ce qui a été
  essayé et abandonné, ce qui reste possible.
- `docs/journal/cadrage.md` — le besoin d'origine.
- `doctrine_architecture.md` — les choix structurants et leurs raisons.
- `docs/services_externes.md` — Open-Meteo, Intervals.icu, BRouter et les
  autres, avec leurs limites.
- `docs/geocodage.md` et `docs/meteo_vent.md` — deux sujets techniques
  détaillés.
- `docs/inviter.md` — inviter quelqu'un sur le service hébergé.
- `tests/caracterisation/openapi.json` — le contrat de l'API, figé ;
  `docs/journal/ux/api_contrat.md` en garde l'histoire (archive, pas une
  référence).
- `front/README.md` — la construction de l'interface web et ses règles.
- `deploiement/api/README.md` — le paquetage de déploiement.

Licence AGPL-3.0-or-later — voir `LICENSE`.

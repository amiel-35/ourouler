# Questions au mainteneur

Les agents ne tranchent aucune de ces questions ; ils avancent sur ce qui
n'en dépend pas. Répondre ici ou en session ; la réponse est reportée dans
la doctrine ou la configuration, puis la question est marquée close.

## Q1 — Clé d'API Intervals.icu — **close le 12/09/2026** (clé posée dans la config locale)

Aucune clé n'existe sur le Mac : le MCP Intervals est un proxy hébergé
(IcuSync), pas la clé. Il faut la clé personnelle d'Intervals.icu
(Settings → Developer → API key) dans `~/.config/ourouler/config.toml`
(`[intervals] api_key`), jamais ailleurs. Sans elle, l'inventaire ne peut
pas rapatrier les FIT d'origine.

## Q2 — Liste des vélos et règle de rattachement — **close le 13/09/2026**

Intervals ne connaît un vélo que sur 68 sorties sur 355 : `rcr` (55, du
02/12/2023 au 22/03/2026, surtout extérieur), `VR` (11, home-trainer,
déc. 2023 → janv. 2024), `BMC` (2, oct.–nov. 2024). Rien d'affecté depuis
novembre 2024 sur la grande majorité des sorties. Il faut :
- la liste des vélos réellement utilisés depuis décembre 2023 : nom, usage
  (route / CLM), masse équipée, roues, et pour chacun **les périodes** où il
  a servi ;
- une règle pour les sorties sans équipement : par période ? par
  appareil (Edge 830 = route, montre = ?) ? Proposition par défaut si aucune
  réponse : toute sortie extérieure sans équipement = vélo de route
  principal, sur toute la période.

**Réponse d'Amiel (12/09/2026)** : deux vélos. **RCR** (SRAM Rival, capteur
d'un seul côté → puissance symétrique, valeurs paires) = **route** ; **BMC**
(SRAM Force, capteur dans chaque manivelle) = **CLM**. Distinguer par le
capteur plutôt que par Intervals. Piste retenue : lire dans le FIT les
messages `device_info` (fabricant/produit du capteur) et la présence du
champ d'équilibre gauche/droite (bilatéral = Force = BMC) ; parité de la
puissance en repli. Lot « rattachement par capteur » au sprint 2, à valider
sur les vrais fichiers rapatriés. Masse et périodes restent à donner.

**Réponse d'Amiel (13/09/2026) — masses, et Q2 close.** Posées dans sa
configuration locale, hors dépôt :
- **RCR** : Van Rysel, SRAM Rival, roues Zipp 303s → 8,5 kg, plus 0,5 kg de
  porte-bidon, pédales et compteur = **9,0 kg**.
- **BMC** : Timemachine 2021, SRAM Force, roues Hologram 64 arrière et 45
  avant → 9,5 kg, plus 0,5 = **10,0 kg**.

Masses totales avec le cycliste : 100,0 et 101,0 kg. Effet mesuré sur la
calibration : **nul** — erreur de temps inchangée à 4,2 % et 2,4 %. C'est
ce que le cadrage annonçait : hors montagne, un kilo sur cent ne se voit
pas. Les masses sont désormais justes, ce qui compte pour le jour où une
sortie montagneuse entrera dans le jeu.


## Q3 — Point de départ et règles de tenue / de séance — **départ et séance clos ; tenue en attente de l'usage**

- Coordonnées du point de départ habituel (dans le fichier de configuration,
  jamais dans le dépôt). En attendant, la démo `meteo` tourne sur le centre
  de Rennes.
  **Réponse (13/09/2026)** : adresse donnée, géocodée et posée dans la
  configuration locale (« Maison »). Règle produit : **le point de départ
  est un paramètre utilisateur, remplaçable ponctuellement** (déplacement,
  vacances) — à prévoir : option `--depuis "<adresse ou lat,lon>"` sur
  `meteo` et `boucle`, géocodage à la demande (Nominatim), et plusieurs
  départs nommés dans la configuration (`[[departs]]`). Lot du sprint 3
  ou 4, au choix du point de repriorisation.
- Règles de tenue : seuils de température ressentie, de vent, de pluie et
  ce qu'on met à chaque palier (utiles à partir de S4).
- Règles de séance : que veut dire « un bloc tient sur un terrain » (pente
  max, longueur minimale sans carrefour, etc.) — S4.

**Réponse d'Amiel (13/09/2026), à préciser au sprint 4** :
- Séance : quand la séance a des blocs, chercher à **éviter les villages et
  les descentes** pendant les blocs.
- Tenue : des **seuils par catégorie**. Humidité : sec / humide / pluie /
  averses. Température : canicule / chaud / modéré / frais / froid / très
  froid. Le vent compte deux fois : impact sur la performance et ressenti
  de froid. Les bornes chiffrées de chaque catégorie et la tenue associée
  restent à donner (un tableau dans la configuration).
  **Précision (13/09/2026)** : l'échelle proposée par le superviseur
  (canicule ≥ 30, chaud 22-30, modéré 15-22, frais 9-15, froid 3-9, très
  froid < 3 °C ressentis ; sec / humide / averses / pluie à 0 / 0,2 / 0,5 /
  1 mm/h) est jugée bonne, mais **ce n'est pas simple : le vent joue
  beaucoup et ça change vite ; ce qui compte, c'est la variation sur la
  durée, surtout en sortie longue.** Conséquence de conception pour S4 : la
  tenue ne se calcule pas sur la météo au départ mais sur la **série des
  échantillons le long du tracé à l'heure de passage** (déjà produite par
  `boucle`). **Correction d'Amiel (13/09)** : le **départ est ce qui
  compte** pour la tenue de base, parce que c'est là qu'on a froid ; puis on
  tient compte de la suite du parcours — montée en température (couches à
  enlever, rangeables : manchettes, gilet) ou pluie annoncée (veste à
  emporter). Règle S4 : tenue = conditions au départ (ressenti, vent) ;
  puis pour chaque échantillon du tracé, si le ressenti monte d'une
  catégorie → « prévoir d'enlever X », si pluie ≥ seuil → « emporter la
  veste », si le ressenti baisse (retour tardif) → « garder X ». Le vent
  entre dans le ressenti et déclenche seul la veste au-delà d'un seuil.
**Décision du 15/09/2026 — on attend.** Les tables de tenue livrées au
sprint 4 (bornes de température, de pluie, seuil de veste au vent) ne se
règlent pas sur le papier : « on attend ». Elles se corrigeront au sprint 6,
sur des sorties réelles où le mainteneur constate qu'il a eu trop chaud ou
trop froid. Aucun lot n'est ouvert là-dessus d'ici là ; les valeurs
actuelles restent en configuration, donc modifiables sans toucher au code.

- Sorties en groupe (sprint 3) : les FIT ne le disent pas ; Strava le sait
  souvent (champ « nombre d'athlètes » de l'activité). Voies : export
  Strava, ou détection statistique (vitesse trop élevée pour la puissance =
  peloton) par la calibration elle-même.

## Q4 — Moteur de tracé — **close le 12/09/2026** : BRouter sur Coolify (pas sur le Mac, pour pouvoir partager)

BRouter auto-hébergé (Java absent sur le Mac ; Docker présent ; ou sur le
serveur Coolify/Hetzner) ou GraphHopper API (clé, gratuit à petit volume) ?
Aucune installation ne sera faite sans accord.

## Q5 — Garmin Connect — **close le 15/09/2026** : partage système du GPX depuis le mobile

Le jeton `~/.config/ha/garmin-token` est un jeton Home Assistant pour
l'utilisateur HA « garmin » (chantier Connect IQ), pas un accès Garmin
Connect. Comment veut-on pousser un parcours : identifiants Garmin Connect
(bibliothèque non officielle type `garth`), export manuel du GPX, ou via HA ?

**Réponse (12/09/2026)** : pas d'API Garmin Connect pour un particulier,
confirmé. Décision : **le GPX généré suffit** (import manuel dans Garmin
Connect). La synchronisation Intervals → Garmin ne pousse aujourd'hui que
les séances structurées, pas les parcours (doc et forum Intervals.icu) ; à
revérifier plus tard. Bibliothèque non officielle : seulement avec accord
explicite, plus tard.

**Complément (nuit du 12/09)** : avec le futur client web mobile, la voie
la plus simple est le **partage système du GPX** vers l'application Garmin
Connect (« ouvrir avec » / feuille de partage iOS-Android, ou lien
téléchargeable) : Connect importe le parcours et l'envoie au compteur, sans
API. À prévoir dans l'API/le front (livrer le GPX avec le bon type MIME
`application/gpx+xml`). **Backlog** : mêmes voies pour Coros, Wahoo
(ELEMNT : import de fichier / lien) et Hammerhead (Karoo : import par le
tableau de bord web).

**Close le 15/09/2026. Décision du mainteneur, ses mots :** « deep link
mobile marche avec pas mal d'applis, Coros, Garmin, etc. » Donc **le
partage système du GPX est la voie retenue, pour toutes les marques**, et
non un pis-aller en attendant une API. Conséquence pour le sprint 5 : la
page du jour livre le GPX en téléchargement avec le type MIME
`application/gpx+xml`, un nom de fichier lisible sur le téléphone, et rien
d'autre — pas de client Garmin, pas de bibliothèque non officielle, pas de
compte à brancher. Les API constructeurs (Wahoo en tête, la seule vraie)
restent au backlog du service hébergé, pas du besoin du mainteneur.

## Q6 — Nom du projet — **nom validé le 13/09/2026 : ourouler** ; reste la purge avant publication

Nom validé : `ourouler` (paquet, commande, dépôt GitHub `amiel-35/ourouler`,
renommé le 13/09/2026). Le dépôt reste **privé** jusqu'à la purge ci-dessous ;
le projet est destiné à être open source, MIT.

**Avant tout passage en public** (relevé par le relecteur du sprint 1) :
les documents de cadrage (`docs/cadrage.md`, `docs/plan_sprints_agents.md`,
ce fichier) citent des chiffres du mainteneur — FTP, masse, nombre de
sorties, kilométrage, noms d'équipement Intervals. Le code, les tests et
`config.example.toml` n'en contiennent aucun. Décider : anonymiser ces
documents, ou déplacer les chiffres dans un fichier ignoré par git.

**Précision du mainteneur (13/09/2026)** : le nom d'un modèle de capteur de
puissance (« SRAM 1052 », « QUARQ 34055 » : numéros de produit ANT+ communs
à tous les capteurs de ce modèle) **n'est pas une donnée personnelle**. La
purge du sprint 2 et la mention « réécrire l'historique git » pour ce motif
étaient un excès de prudence ; l'historique reste tel quel. Ce qui reste à
ne pas publier : numéros de série, identifiants Intervals (athlète,
équipements), coordonnées, chiffres d'entraînement — présents seulement dans
les documents de cadrage, à anonymiser avant publication. Tant que le dépôt
est privé, aucune urgence.

**Réponse d'Amiel (13/09/2026) — seuls les identifiants comptent.** « Les
chiffres, je m'en fous un peu ; Intervals, plus chiant. » Donc avant
publication : purger **les identifiants Intervals** (identifiant d'athlète,
identifiants d'équipement `b…`) et rien d'autre. Les chiffres
d'entraînement — FTP, masse, kilométrages, nombres de sorties — peuvent
rester : ils documentent les décisions et ne donnent accès à rien.


## Q7 — Ordre des règles de rattachement vélo — **close le 13/09/2026**

Le contrat place la règle « période d'un vélo » avant la règle
« home-trainer ». Dès que Q2 renseignera des périodes, une séance
d'intérieur tombant dans la période d'un vélo lui sera attribuée au lieu
d'aller en « home-trainer ». Proposition : inverser (intérieur d'abord),
sauf si un vélo est explicitement déclaré d'usage home-trainer.

**Réponse d'Amiel (13/09/2026)** : le home-trainer est majoritairement en
mode ergo (puissance contrôlée), on n'y apprend rien sur le vélo : classé à
part et **exclu de la calibration**. Ordre appliqué : intérieur → capteur →
équipement Intervals → période → vélo route par défaut. Rappel du rôle de
l'historique : apprentissage et test du modèle physique seulement ; l'usage
quotidien (météo, boucle) ne s'en sert pas.

## Q8 — À quelle puissance calculer la colonne « temps estimé » de `boucle` ?

Le contrat du sprint 3 demande que la colonne « temps estimé » vienne du
modèle calibré, sans dire à quelle puissance. Un temps sans puissance n'a pas
de sens : 58 km de la boucle NE font 2 h 19 à 130 W et 1 h 48 à 200 W.

Choix provisoire de `boucle/commande.py` : **65 % de la FTP** (168 W pour une
FTP de 258 W), affiché dans l'en-tête, remplaçable par `--puissance`. C'est
une allure d'endurance plausible, pas une mesure.

À trancher : garder ce défaut, en choisir un autre (une puissance en watts
dans `[boucle]` ? une part de FTP configurable ?), ou faire venir la
puissance de la séance du jour quand le sprint 4 la connaîtra — ce dernier
choix semble le bon à terme.

**Réponse d'Amiel (13/09/2026) — close.** « Soit c'est une séance full Z2,
donc OK ; sinon ça dépend justement de la séance avec des blocs, c'est tout
l'enjeu. » Donc : sans séance, `boucle` affiche une durée à l'allure Z2
(65 % de la FTP, affiché en tête) ; dès le sprint 4, `sortie` simule la
boucle bloc par bloc à partir de la séance Intervals du jour, et la durée
est celle de la séance sur ce terrain.

## Q9 — CdA et Crr ne se séparent pas sur les données réelles — **close**

**Close le 13/09/2026.** Décision du mainteneur : « on va trop dans le
détail pour un coureur amateur ». On ne cherche plus à séparer CdA et
roulement ; le modèle sert à prédire une durée (MAE 4,2 % RCR, 2,4 % BMC
après vent à hauteur du cycliste et terme cinétique, CdA 0,22 hors butée)
et l'avantage du CLM se mesure directement : +2,5 km/h à puissance égale en
Z2 sur tronçons plats (`ourouler comparer`), ≈ 40 W à vitesse égale.
Détail : `docs/sprint3_relecture_fable.md`.

<details><summary>Historique de la question</summary>

Mesuré le 13/09/2026 sur les vraies sorties (100 RCR, 37 BMC, vent d'archive
Open-Meteo au point de départ). Les moindres carrés par tronçons de 200 m
prévus au contrat rendent **CdA = 0,18 (borne basse) et Crr ≈ 0,011** pour
les deux vélos — physiquement absurde pris paramètre par paramètre : un Crr
de 0,011 est celui d'un VTT sur chemin, un CdA de 0,18 celui d'un pistard en
position de contre-la-montre.

Ce que les données disent **bien** : la résistance totale à 27 km/h, 17,2 N
pour le RCR et 16,8 N pour le BMC — cohérente avec un vélo de route normal
(CdA ≈ 0,40 et Crr ≈ 0,005 donnent 17,6 N). Le couple rendu prédit
correctement le temps des sorties non vues (MAE 5,2 % RCR, 5,5 % BMC), parce
que dans la plage d'allure observée (20 à 36 km/h) les deux paramétrages se
valent. Il serait faux **hors de cette plage** : à 45 km/h, CdA 0,18 promet
une vitesse que le vélo ne tiendra pas.

Cause probable, mesurée : sur les tronçons plats et sans vent, la puissance
mesurée croît presque linéairement avec la vitesse (120 W à 24 km/h, 151 W à
27 km/h, 167 W à 30 km/h) au lieu de croître comme v³. Les échantillons
rapides sont vraisemblablement pollués par ce que le modèle ne voit pas :
l'élan (le cycliste arrive vite sur le plat après une descente), et le vent
local que l'archive, maillée à plusieurs kilomètres, ne connaît pas. Le
sous-ensemble « vent d'archive presque nul » rend d'ailleurs un couple
beaucoup plus plausible (CdA 0,26, Crr 0,0093).

Pistes, par coût croissant : (a) borner CdA par le bas plus haut (0,28 pour
un vélo de route) et laisser Crr absorber le reste ; (b) ne calibrer que Crr
en fixant CdA par vélo à une valeur de catalogue ; (c) calibrer sur des
sorties choisies (sortie longue régulière, seul, par temps calme) plutôt que
sur tout l'historique ; (d) descendre chercher le vent local (station
Météo-France la plus proche) plutôt que la maille d'archive.

</details>

## Q10 — Les fichiers multisport faussent la calibration — **close**

**Close le 13/09/2026.** Les fichiers multisport (triathlons) sont
**écartés** de la calibration avec le motif « multisport » (le lecteur FIT
signale plusieurs sessions). Ils restent dans l'inventaire.

<details><summary>Historique de la question</summary>

La pire erreur de validation du BMC (−20 %, 223 km en 10 h) est le fichier
d'un triathlon : le FIT contient la natation, le vélo **et** la course à
pied, et l'inventaire le compte comme une sortie vélo de 223 km. Le modèle
simule les 42 km de course à pied à la puissance du vélo, donc bien trop
vite. Faut-il découper les fichiers multisport par segment (le FIT porte les
trames `session`, une par sport), ou simplement les écarter de la
calibration ?

</details>


## Q11 — Les séances prescrites en zones de FC — **close le 13/09/2026**

**Close.** Règle retenue : **zone de FC basse (Z1, Z2) → `[seance]
puissance_endurance_pct` × FTP**, défaut **0,60** ; **zone de FC haute (Z3 et
au-dessus) → table des zones de puissance de même numéro**, inchangée.
L'avertissement à l'écran dit laquelle des deux s'applique.

**C'est un cas minoritaire, et il faut le garder en tête.** Comptage des
unités sur les 82 séances vélo de 2026 : **259 étapes en `%ftp`**, 16 en
`power_zone`, **28 en `hr_zone`**. Les séances de coach (iDOSport) et le plan
Ironman sont **tous en pourcentage de FTP** : traduction exacte, aucune
approximation, aucun avertissement. Les zones de FC sont un lot de séances
« Vélo HIT / Sortie EF » de juin à septembre 2026.

**Pourquoi la table des zones ne marchait pas pour les zones basses.** La Z1
de puissance s'étend de 0 à 55 % de FTP ; son milieu vaut 27,5 % de FTP,
c'est-à-dire du pédalage à vide, et une zone ouverte vers le bas n'a de toute
façon pas de milieu qui veuille dire quelque chose. Une zone de FC n'est pas
non plus la zone de puissance de même numéro : un plan qui écrit « Z1 de FC »
pour une endurance désigne une puissance d'endurance franche.

**La valeur, mesurée.** Médiane de 60 % de FTP (154 W pour 258 W de FTP) sur
les 96 sorties extérieures de plus d'une heure depuis 2025 ; 59 % sur toutes
les sorties extérieures confondues. Les EF de 3 h font 75-81 km, soit
25-27 km/h.

**Ce que ça change, mesuré sur les vraies séances (`ourouler seance`) :**

| Séance | Avant | Après | Référence |
|---|---|---|---|
| « Sortie EF 2h » du 29/08 (Z1 de FC) | 36,1 km (18,0 km/h) | **57,3 km (28,6 km/h)** | ses EF réelles : 25-27 km/h |
| Récup de 4 min de « 4x8min Z4 » du 08/09 | 0,6 km au-delà du segment | **1,0 km** | cadrage S4 : « 4 min à 25 km/h ≈ 800 m » |
| Blocs Z4 du 08/09 | 4,9 km à 235-271 W | **inchangés** | plausible pour du seuil |

Les zones hautes n'ont pas bougé : la table des zones tombe juste pour elles.

**Ce qui reste incertain.** 0,60 est une médiane sur l'historique, pas une
correspondance FC → puissance. Une vraie table (FC et puissance sont toutes
deux enregistrées dans les FIT du cache) serait plus juste, et reste ouverte
si le besoin revient — il est faible tant que les séances de coach sont
prescrites en pourcentage de FTP.

<details><summary>Historique de la question</summary>

Ouverte le 13/09/2026 au lot L4.1. Le contrat de sprint 4 §1 demandait
d'approximer une consigne en zone de FC par la zone de **puissance** de même
numéro, et de le dire. C'était fait, et affiché, mais le résultat chiffré
n'était pas utilisable : « Sortie EF 2h » prescrite en Z1 de FC donnait 71 W
de cible, donc 36,1 km pour 2 h — 18 km/h là où une EF de 2 h fait 50 à
60 km. Même effet, plus discret, sur les récupérations : 4 min de Z1 donnaient
1,2 km, donc 0,6 km de route nécessaire au-delà du segment pour un demi-tour,
contre les 800 m du cadrage.

La première version de la question portait sur « les séances sont prescrites
en FC » ; le mainteneur a corrigé le cadrage : c'est l'exception, pas la
règle, et le jour de vérification avait été choisi dans l'exception.

</details>

## Q12 — Comment savoir qu'une étape est un bloc ? — **close le 13/09/2026**

**Close.** Cascade de **trois règles**, première qui répond gagne, plus un
recadrage des extrémités. La provenance du type de chaque étape est gardée
dans `meta["typage_source"]` : on doit toujours pouvoir dire pourquoi une
étape est un bloc.

1. **Marqueurs explicites** — `warmup`, `cooldown`, `intensity` : la règle du
   contrat de sprint 4 §1, inchangée.
2. **Mots du champ `text`**, sans accents ni casse : « échauffement » et
   « warm » ; « récupération », « recup », « recovery » ; « retour au calme »
   et « cool ». Le texte de l'étape l'emporte sur celui de son groupe.
3. **Puissance relative à la FTP** — `[seance] seuil_recuperation_pct`,
   défaut **0,75** (la frontière Z2/Z3) : sous ce seuil, une étape n'est pas
   un bloc. Selon sa position : première → échauffement, dernière → retour au
   calme, sinon → récupération.

Puis, aux **extrémités seulement**, la position l'emporte sur le nom : une
récupération en première ou dernière position devient un échauffement ou un
retour au calme, donc élastique. Les séances de coach nomment
« Récupération » jusqu'au retour à la maison, et c'est cette étape-là qui
referme la boucle.

**Pourquoi.** Les séances de coach (iDOSport) — la majorité, et les deux
séances de référence du cadrage produit — **ne portent aucun marqueur**. Sans
cette cascade, `ourouler seance --jour 2026-02-08` annonçait **14 étapes,
14 blocs** : ni échauffement, ni récupération, donc aucune élasticité, aucun
demi-tour possible, et le placement (L4.3) serait parti chercher un couloir
propre pour 30 minutes d'échauffement et 20 minutes de retour au calme.

**Vérifié sur les trois séances réelles** (FTP 258 W, donc seuil à 193 W) :

| Séance | Avant | Après |
|---|---|---|
| « 2x20' + 4x3' » du 08/02 (texte) | 14 blocs | **6 blocs**, échauffement 30 min élastique, 6 récups, calme 20 min élastique |
| « 4x8 SV1 outdoor » du 22/04 (muette) | 19 blocs | **9 blocs**, récups à 129-134 W, extrémités libres élastiques |
| « 4x8min Z4 » du 08/09 (marqueurs) | 4 blocs | **4 blocs**, inchangée |

**Deux garde-fous.** Si la FTP est inconnue, le seuil est le mi-chemin entre
la plus faible et la plus forte puissance cible de la séance, et
`meta["seuil_recuperation_replie"]` le dit — c'est une frontière tirée de la
séance, pas du cycliste ; sans contraste de puissance, on ne devine rien. Si
toutes les étapes tombent du même côté du seuil (sortie d'endurance
uniforme), la séance n'a **aucun bloc**, et c'est correct : on ne fabrique
pas un bloc artificiel pour avoir quelque chose à placer.

**Ce qui reste discutable.** Sur « 4x8 SV1 outdoor », la règle 3 classe en
bloc les 4 × 40 s à 375 W (des activations d'échauffement) et les 5 min à
208 W qui précèdent le corps de séance : 9 blocs là où le mainteneur n'en
voit sans doute que 4. Ce sont bien des efforts au-dessus du seuil, donc la
règle est appliquée correctement ; c'est le placement (L4.3) qui devra
décider s'il contraint le terrain sous un effort de 40 secondes.

## Q13 — L'affichage de `sortie` ne montre que les blocs — **à corriger dans le sprint 5** (arbitré le 15/09/2026)

Relevé par le mainteneur le 13/09/2026 en lisant la sortie du 08/02 :
« t'as pas oublié l'échauffement ? ». Il n'était pas oublié — 28 min à
155 W, soit 13,2 km, exactement là où le premier bloc démarre — mais
**rien ne le montrait** : `sortie/commande.py` ne liste que les étapes de
type « bloc », parce que `Placement.emplacements` ne mémorise que celles-là.

Ce qui rend le défaut sérieux : on ne peut pas vérifier ce qu'on ne voit
pas, et c'est précisément ce qu'on demande au mainteneur de faire sur la
carte. **Arbitrage du 15/09/2026** : « on règle pendant le sprint ». Ce n'est donc
pas un lot à part, c'est une contrainte du sprint 5 — la page du jour ne
peut pas montrer trois propositions contrastées si elle ne montre pas la
séance entière. À corriger dans le lot qui touche `sortie/` :

- **Lister toutes les étapes** avec leur kilomètre de début et de fin, pas
  seulement les blocs. Les non-blocs n'ont pas de note — ils n'en méritent
  pas, aucun terrain n'est évalué sous une récupération — mais ils ont une
  position, et elle se déduit du déroulé.
- **Les montrer sur la carte** : échauffement et retour au calme dans une
  teinte neutre distincte, récupérations déjà en pointillés. Aujourd'hui
  tout ce qui n'est pas bloc est gris comme le reste du tracé, donc on ne
  distingue pas « je roule ici pendant l'échauffement » de « cette portion
  de la boucle n'est jamais parcourue ».
- Conséquence de conception : `placer` doit rendre la position de **chaque**
  étape, pas seulement des blocs. C'est une extension de `Placement`, pas
  une nouvelle mesure.

## Q14 — Le retour au calme ne peut pas absorber la variabilité de la boucle — **close le 13/09/2026**

**Close. Décision du mainteneur, ses mots :** « le retour au calme en fait
peut dépasser de plus, c'est souvent ce que je fais car c'est incontrôlable de
faire parfait, et c'est du kilomètre facile. Faut réduire le dépassement au
max. »

C'est la piste (c) des pistes ci-dessous, et elle retourne le problème : un
retour au calme qui s'allonge **n'est pas une faute**, c'est la façon normale
de refermer une boucle dont la longueur n'est jamais exacte. Entre deux
placements de terrain équivalent, le plus court gagne ; mais **raccourcir**
reste cher, parce qu'amputer une séance est un vrai défaut.

**Le symptôme.** Sur la séance du 08/02, aucune candidate ne tenait la séance
dans sa fenêtre d'élasticité : le retour au calme durait 38 min au lieu des 20
prescrites, soit +90 %, et l'outil l'affichait comme une alerte.

**La fausse piste, mesurée.** La distance demandée était arrondie au multiple
de 5 km **supérieur**, donc 65 km pour une séance de 60,8. Passer à l'arrondi
**au plus proche** donne 60 km demandés, une boucle de 58 — et le retour au
calme monte à **+201 %**, parce que le placement retenu fait alors un demi-tour
et que le parcours passe à 78,7 km sur une boucle de 58. Changement annulé,
l'arrondi supérieur reste.

**La cause réelle, en deux morceaux.**
1. **Un demi-tour ajoute de la distance que le dimensionnement ignore.**
   La distance demandée vient de la séance sur le plat ; elle ne sait rien
   des allers-retours que `placer` décidera ensuite. Un parcours peut
   dépasser sa boucle de 90 % (72,7 km sur 38,5 le 22/04).
2. **Une Z2 de fin de 20 min ne peut pas absorber une boucle de 60 km.**
   20 min à ±20 % font ±1,9 km, quand la tolérance du générateur de
   boucles vaut déjà ±3 km et l'écart mesuré jusqu'à +9 km. Le levier est
   structurellement trop court.

### Ce qui a été fait

**1. Les deux élasticités sont séparées** (`config.ParametresSeance`). Elles
ne font pas le même métier : la Z2 **d'ouverture** est le levier de placement
et garde sa fenêtre étroite (`elasticite_z2_min` / `elasticite_z2_max`, −5 % à
+20 %) ; le **retour au calme** absorbe et reçoit la sienne,
`elasticite_calme_min` / `elasticite_calme_max`, **−5 % à +150 %**. Les noms
existants ne bougent pas.

**2. La pénalité d'allongement devient douce, proportionnelle et sans seuil.**
`PENALITE_SEANCE_ALLONGEE` (1,0 par unité d'écart relatif **hors de la
fenêtre**) est remplacée par `PENALITE_CALME_ALLONGE_KM_PAR_H = 0,6` : 0,6 km
équivalent par **heure** de retour au calme en trop, comptée dès la première
minute. Les chiffres, en kilomètres équivalents :

| dépassement du retour au calme | coût |
|---|---|
| 10 min | **0,10** |
| 20 min | **0,20** |
| 40 min | **0,40** |

à comparer au coût d'un défaut de terrain franc sous un bloc : **1 km de
village traversé pendant un bloc de 20 min** de la séance du 08/02 coûte
`POIDS_KM_BATI` × 1200/3120 = **1,15** après pondération par la durée des
blocs. Rentrer 20 minutes plus tard est donc près de **six fois moins cher**
que de faire traverser un bourg pendant un 20' — et même 40 minutes de trop
restent près de trois fois moins chères. Dit dans l'autre sens : 20 min de retour au
calme en plus, c'est environ 9 km de vrai bitume à allure facile, facturés
0,20.

La disparition du **seuil** compte autant que la valeur : sous l'ancienne
marche, deux placements de terrain égal étaient à égalité parfaite tant qu'ils
restaient dans la fenêtre, et le départage retombait sur autre chose. Le
dépassement se réduit maintenant toujours, il ne s'interdit jamais.

Le **raccourcissement** garde `PENALITE_SEANCE_NON_TENUE = 20,0` : un retour au
calme supprimé coûte toujours 19,0, soit bien plus qu'un bloc qui ne tient pas
sur le tracé (`PENALITE_BLOC_TRONQUE = 10,0`).

**3. L'avertissement change de ton.** « ⚠ retour au calme : 38 min pour rentrer
au lieu des 20 min prescrites (+90%) » devient « retour au calme : 38 min au
lieu des 20 prescrites, 8 km de plus à allure facile » — une information
neutre, rangée dans `Placement.informations`, que l'affichage ne préfixe pas
d'un ⚠. Un ⚠ ne reste que pour les deux vrais défauts : un retour au calme
**raccourci** (la séance n'est pas roulée en entier) et un dépassement qui sort
de la **fenêtre haute** (ce n'est plus la boucle qui tombe mal, c'est la boucle
qui ne va pas avec la séance).

**Effet mesuré sur les deux sorties réelles** (4 candidates chacune) : la
candidate retenue **ne change pas** — 63,9 km le 08/02, 35,5 km le 22/04, mêmes
emplacements de blocs. Le 08/02, les 3ᵉ et 4ᵉ candidates s'échangent : celle
qui rentrait très en retard n'est plus surfacturée (7,12 → 5,27) et passe
devant. C'est exactement l'arbitrage demandé.

**Ce qui reste ouvert** : les deux autres causes listées plus haut. Le
dimensionnement de la boucle ignore toujours la distance qu'ajoutent les
demi-tours (piste b, « demander, placer, puis redemander »), et rien ne
pénalise encore le demi-tour pour la distance qu'il ajoute (piste a). Ce n'est
plus un défaut affiché, c'est une imprécision de dimensionnement.


## Q15 — Nom de l'heure et du lieu de départ — **close le 13/09/2026**

**Close. Décision du mainteneur : deux noms explicites, aucun des trois
choix proposés.**

- **`--heure-depart`** est le nom canonique de l'**heure** de départ, sur
  `meteo`, `boucle`, `simuler` et `sortie`.
- **`--adresse-depart`** est le nom **réservé** du **lieu** de départ — un
  départ autre que la maison, annoncé au plan du sprint 4 sous le nom
  provisoire `--depuis`. **Il n'est pas livré** : aucune commande ne le
  porte aujourd'hui, et un test le vérifie pour qu'il ne soit pas pris par
  autre chose entre-temps. Le nom est posé maintenant parce qu'après il
  serait trop tard.

Les deux noms disent ce qu'ils désignent et ne se ressemblent plus : c'était
tout le problème.

**Ce qui reste accepté, sans être documenté** : `--depart` (l'ancien nom de
l'heure) et `--heure` (le synonyme ajouté en attendant la décision).
Aucun script ni aucune habitude ne casse ; mais l'aide ne les propose plus,
parce qu'un nom déprécié qu'on documente est un nom qu'on enseigne encore.
Techniquement, une seconde déclaration `argparse` sous `SUPPRESS` écrivant
dans le même `dest` — argparse ne sait pas masquer un alias, il les imprime
tous ou aucun (`cli.ajouter_heure_depart`).

**État d'origine, pour mémoire.** Relevé le 13/09/2026 par le relecteur
(C5). `--depart HH:MM` désignait une heure, le plan annonçait `--depuis`
pour un lieu : deux options dont les noms diffèrent d'une lettre pour deux
sens sans rapport, sur la même commande. Personne d'autre que le mainteneur
n'utilise la commande, le renommage était donc gratuit — il a été fait.

## Q16 — Peut-on disposer d'un signal de popularité des routes chez les cyclistes ? — **close le 16/09/2026 : non, aucune source utilisable**

Question du mainteneur : « BRouter a des infos sur la popularité des routes
par les cyclistes ? C'est la force de Strava sur son générateur d'itinéraire. »

**Trois réponses, vérifiées le 16/09/2026.**

1. **BRouter n'en a pas.** Il calcule sur OpenStreetMap, qui ne contient
   aucune donnée d'usage. Ce qui y ressemble dans les tags reçus —
   `estimated_traffic_class`, `estimated_crossing_class` — sont ses propres
   estimations à partir des tags, pas des cyclistes réels.
2. **La heatmap de Strava n'est pas réplicable.** Elle agrège le GPS de
   millions de sorties ; c'est propriétaire, l'API ne l'expose pas, et les
   conditions d'usage interdisent d'en dériver un produit. Il n'existe pas
   d'équivalent libre. C'est une force que ce projet n'aura pas, et le dire
   vaut mieux que de chercher un ersatz.
3. **Les itinéraires balisés sont un contre-signal, et c'est le mainteneur
   qui tranche** : « pas bon signal, c'est des itinéraires rando souvent ».
   BRouter renvoie bien `route_bicycle_lcn` (52 tronçons sur une boucle au
   nord de Rennes) et `route_bicycle_ncn` (3), mais en France ces réseaux
   sont des véloroutes et voies vertes — partagées avec les piétons, parfois
   en revêtement souple. C'est du tourisme, pas de l'entraînement : un
   balisage est même un contre-signal pour un bloc à 250 W. **Aucune mesure
   n'est lancée** : la piste est écartée sur le fond, pas faute de données.

**La distinction à retenir**, parce qu'elle n'est pas évidente et qu'elle
survivra à cette question : la règle de doctrine « les routes connues ne sont
jamais un critère » vise **les routes du cycliste lui-même** — les siennes
dans le score, c'est l'outil qui lui renvoie son reflet, et toute validation
devient circulaire. La popularité d'**autres** cyclistes serait une donnée
extérieure, donc un critère parfaitement légitime. Il se trouve seulement
qu'aucune source libre n'existe.

## Q17 — La densité de marqueurs : quel côté de l'axe est le bon ? — **close le 16/09/2026 par le mainteneur : moins de marqueurs est bien, et l'écart mesuré est la valeur à apporter**

Le lot L5.3 a écrit la densité de marqueurs au kilomètre (feux, stops,
passages piétons, cédez-le-passage, ralentisseurs) et l'a validée comme le
contrat le demandait, contre les sorties réelles. **La mesure contredit
l'hypothèse, et nettement.**

Sur 111 sorties d'entraînement réelles rejouées dans BRouter contre
143 boucles proposées par le moteur aux mêmes distances : médiane **2,91**
marqueurs/km pour les vraies sorties contre **1,50** pour les boucles
proposées, soit un rapport de 1,94 ; 77 sorties sur 111 sont au-dessus de la
médiane du lot proposé de leur longueur. Autrement dit : **il roule des
routes deux fois plus « urbaines » que ce que l'outil lui propose.** L'écart
grandit avec la distance, ce qui écarte l'explication par le couloir de
départ.

L'axe **discrimine** très bien (facteur 2,7 entre candidates d'une même
journée, soit 125 arrêts d'écart sur 56 km) — la question n'est pas là. Elle
est sur le **signe** :

- **Option A** — on garde « moins de marqueurs = le côté à mettre en avant »,
  comme le contrat le supposait, et la phrase reste « elle évite les
  villages ». La mesure dit alors qu'on lui propose l'inverse de ce qu'il
  fait, ce qui est peut-être exactement ce qu'il veut (il subissait le manque
  d'outil).
- **Option B** — on considère que sa pratique révèle un goût pour les routes
  de bourg à bourg, et l'axe se retourne : « elle passe par les villages »
  devient la phrase valorisée.
- **Option C** — l'axe n'a pas de bon côté et les deux extrêmes portent
  chacun leur phrase, le cycliste tranchant à la lecture.

**Aujourd'hui l'option A est implémentée**, parce que c'est ce que le contrat
écrivait ; le code ne s'en sert que pour **décrire** et **contraster**, jamais
comme signal de qualité dans un score. Le retournement coûte une ligne
(`contraste._gagne`) plus une phrase.

Reproductible : `uv run python tests/validation/marqueurs_retrospectif.py`.

## Réponse du mainteneur (16/09/2026) — et elle retourne la question

Ses mots : « **plus village que ville, mais parce que je ne connais pas les
routes de contournement je pense** ».

**Il diagnostique son propre biais.** Il traverse les bourgs non par
préférence mais par méconnaissance des contournements. C'est une lacune, pas
un goût.

Donc le signe de l'axe est tranché : **moins de marqueurs est bien**. Et
l'écart mesuré — 2,91 marqueurs/km sur ses sorties contre 1,50 sur les
boucles proposées — n'est pas une erreur du modèle à corriger, c'est
**précisément la valeur que l'outil peut apporter**. Ses 162 sorties ne sont
pas la cible à imiter, elles sont la référence à battre.

**Cette réponse valide la règle de doctrine écrite le même jour** (« les
routes connues sont un instrument de mesure, jamais un critère ») de la façon
la plus concrète qui soit : si on avait mis ses routes connues dans le score,
on aurait appris à le faire passer par les villages, en croyant apprendre sa
préférence alors qu'on aurait figé sa méconnaissance du terrain.

## Ce qui reste à faire, et qui est une piste technique précise

La densité actuelle **mélange le village et la ville**, et `crossing` pèse
deux marqueurs sur trois — or il y a des passages piétons dans le moindre
bourg. Ce qui sépare les deux n'est pas la densité mais **l'étendue** : 300 m
de traversée, c'est un village qu'on n'évite pas dans le bocage ; 3 km
continus, c'est une agglomération qu'on contourne.

Piste : regrouper les marqueurs le long du couloir et mesurer la **longueur
de la portion dense**, pas seulement leur nombre au kilomètre. Un village
traversé coûte alors peu, une ville coûte cher, et le contournement qu'il ne
connaît pas devient proposable. À instruire au sprint 6, sur ses vraies
sorties : une traversée de bourg et une traversée d'agglomération doivent se
distinguer nettement, sinon la mesure ne vaut pas mieux que l'actuelle.

## Q18 — Une carte par proposition, ou une seule ? — **ouverte le 16/09/2026**

Le contrat §3.1.1 décrit la bonne forme de l'arbitrage : « il arbitre **en
regardant**, pas en réglant. Trois propositions, **une carte chacune**, une
phrase qui dit ce qui les distingue. »

Le lot L5.3 livre les trois phrases et les mesures, mais **continue de
n'écrire qu'une carte et qu'un GPX**, ceux de la proposition retenue. Deux
raisons de ne pas l'avoir élargi sans demander : §3.3.5 exclut la page HTML
du lot (c'est L5.4), et écrire trois fichiers change la convention de nommage
(`sortie_AAAAMMJJ.html`) et la sémantique de `--carte`, qui désigne
aujourd'hui **un** fichier.

Trois formes possibles, à trancher :

- **une carte par proposition** — `sortie_AAAAMMJJ_1.html`, `_2`, `_3`, et
  `--carte` devient un préfixe ;
- **une seule page à trois onglets**, ce qui est plutôt la forme de L5.4 ;
- **on attend L5.4** et la page du jour porte les trois.

Sans réponse, le cycliste arbitre sur les phrases et les chiffres, pas sur
les tracés — c'est-à-dire pas tout à fait « en regardant ».

## Q19 — `sortie` perd toute la météo au-delà de la portée d'AROME — **diagnostiquée le 16/09/2026, correction à écrire**

Constaté en préparant les sorties réelles du mainteneur :

```
$ ourouler sortie --jour 2026-09-18
ourouler : météo indisponible (Open-Meteo : point hors du domaine du modèle
meteofrance_arome_france_hd, essayer un modèle global (par exemple
--modele icon_seamless)) — tableau sans les colonnes météo et sans tenue
```

Même chose le 19/09. **C'est le cas d'usage le plus utile du produit** —
préparer mercredi la sortie du club de samedi — et il rend une page sans
pluie, sans vent et sans tenue.

**Trois défauts distincts dans un seul message :**

1. **Le message est faux.** Il parle du « domaine » du modèle, c'est-à-dire de
   sa couverture géographique. Rennes est au centre du domaine d'AROME. La
   cause est ailleurs, et le message envoie chercher au mauvais endroit.
2. **Il conseille une option qui n'existe pas.** `ourouler sortie` n'accepte
   pas `--modele` : ses options sont `--json --jour --distance --direction
   --candidates --vent --velo --heure-depart`. Le conseil vient de la couche
   Open-Meteo, qui ignore la commande appelante.
3. **Il n'y a aucun repli sur le second modèle**, alors que la configuration
   en déclare un (`second_avis = "icon_seamless"`, portée de 168 h contre 67 h
   pour AROME) et que la commande `meteo` s'en sert déjà comme second avis. Au
   lieu de basculer, on perd toute la météo.

**Ce qui est vérifié et ce qui ne l'est pas.** Vérifié : `ourouler meteo`
fonctionne le jour même ; une requête AROME directe pour le 18/09 de 08h à 12h
rend `200` ; AROME publie jusqu'au 18/09 23h (55 heures connues). Donc ni la
géographie ni l'horizon ne suffisent à expliquer l'échec du 18. **La cause
exacte n'est pas trouvée** — à instruire.

**Piste** : comparer la requête réellement émise par `sortie` à celle de
`meteo` (nombre de points, `start_hour`/`end_hour`, modèles demandés). Le
repli sur le second modèle est de toute façon à écrire, indépendamment de la
cause : c'est la règle 5 du projet appliquée à la météo — deux modèles qui
divergent s'affichent, mais un modèle muet ne doit pas emporter les deux.

## Diagnostic, trouvé le 16/09/2026

**Ce n'est pas « hors du domaine », c'est « hors de portée ».**

`meteo/openmeteo.py::_hors_domaine` conclut « le point sort de la grille »
sur deux signatures : un corps HTTP 200 contenant des littéraux `nan`, ou
**un bloc entièrement à `null`**. La seconde est ambiguë : un bloc nul, c'est
aussi ce qu'Open-Meteo rend quand on demande des heures **au-delà de la
portée du modèle**. AROME publie jusqu'au 18/09 23 h ; la sortie du club est
le 19 à 10 h. L'heuristique confond une limite d'espace et une limite de
temps, et le message envoie chercher au mauvais endroit.

**Vérifié en basculant le modèle principal sur `icon_seamless`** (portée
168 h) : la sortie du 19/09 rend la pluie, le vent, la tenue — et **trois
propositions au lieu de deux**, dont « vous rentrez avec le vent dans le
dos ». Le vent redevient un axe vivant, et le lot L5.3 retrouve son objet.

**Contournement immédiat** : dans la configuration locale, `[meteo] modele =
"icon_seamless"` et `second_avis = "meteofrance_seamless"`. On perd la maille
fine d'AROME sur le court terme, on gagne les jours 3 à 7.

**Correction à écrire** — trois choses, dans cet ordre d'importance :

1. **Le repli automatique.** Quand le modèle principal ne couvre pas la
   fenêtre demandée, basculer sur le modèle global déjà configuré, et le dire
   dans l'en-tête (« AROME ne va pas jusqu'à samedi, prévision ICON »). C'est
   la règle 5 appliquée à la météo : deux modèles qui divergent s'affichent,
   mais un modèle muet ne doit pas emporter les deux. À écrire même si le
   diagnostic évolue.
2. **Distinguer les deux causes.** Un bloc nul au-delà de la dernière heure
   publiée par le modèle n'est pas un point hors grille. La portée se lit dans
   la réponse elle-même (dernière heure non nulle) ou se demande une fois.
3. **Le conseil `--modele` est faux** : `ourouler sortie` n'a pas cette
   option. Un message de la couche connecteur ne doit pas nommer une option de
   ligne de commande qu'il ne connaît pas.

## Q20 — La page du jour n'applique pas la méthode Strava qu'elle voulait — **ouverte le 16/09/2026, à corriger**

Constat du mainteneur devant la page du 19/09 : « la méthode Strava, c'est
d'afficher les propositions en même temps mais de mettre en couleur forte la
version sélectionnée. Là, la version sélectionnée est en pointillé faible et
l'autre absente. »

Il a raison sur le symptôme. **Les deux causes sont distinctes, et aucune des
deux n'est un mauvais choix de style** — ce sont deux réglages qui s'annulent.

**a) La sélectionnée est dessinée comme une liaison, pas comme un tracé.**
La sortie du club est une Z2 **sans bloc** : zéro bloc à colorer, et tout le
parcours tombe dans le calque « échauffement / récupérations / retour au
calme » créé par L5.2 — bleu-gris `#9fb8cd`, en pointillé. Le style prévu pour
l'échauffement a avalé la sortie entière. Vérifié dans les données de la page :
`blocs: 0`, `liaisons: 1` sur les deux propositions.

Ce n'est pas un cas de bord : **c'est le cas courant du mainteneur.** Son plan
ne contient aucune séance à blocs en extérieur ; toutes ses sorties sont des
endurances, donc toutes ses pages sont pâles.

**b) La non-sélectionnée est dessinée, mais invisible.** Sa trace est bien
dans la page (1 963 points) et peinte en `#c9c9c9` — un gris trop clair pour
se détacher des tuiles OpenStreetMap. Le contrat §4.1 demandait « trait gris
fin » ; il est fin et gris, et illisible.

**Correction à écrire :**

1. **Le tracé de la proposition sélectionnée est toujours en couleur forte et
   en trait plein**, qu'elle porte des blocs ou non. Les blocs se surimposent
   dessus quand il y en a ; ils ne le remplacent pas. Une séance sans bloc
   n'est pas une séance sans parcours.
2. **Assombrir la non-sélectionnée** jusqu'à ce qu'elle se lise sur les
   tuiles — à régler à l'œil sur une vraie page, pas au jugé, et sur la zone
   de Rennes où le fond est dense.
3. Vérifier la même page sur une séance **à blocs** : la hiérarchie doit
   rester lisible à trois niveaux — blocs en couleurs vives, reste du parcours
   sélectionné en couleur franche, autres propositions en gris lisible.

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

## Q6 — Nom du projet et purge avant publication — **close le 17/09/2026**

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

**Audit de l'historique (17/09/2026), en resserrant `.gitignore`.** Les 1 358
blobs de tous les commits de toutes les branches ont été relus : les textes en
cherchant tout couple de décimales tombant dans la France métropolitaine, les
9 blobs FIT en les repassant au lecteur du projet (un dixième blob binaire est
un `.pyc`, commité par le trou que ce lot referme). Deux résultats, dont un
seul est rassurant.

**Aucun fichier d'activité réel n'a jamais été commité.** Les trois versions
successives de `boucle.fit` tiennent toutes dans ±0,009° du point fictif
(0, 0) ; `home_trainer.fit` n'a pas de GPS par construction ; `tronque.fit`
est illisible par conception. Vérifié indépendamment par la relecture.

**Mais le point de Rennes-centre est encore dans HEAD aujourd'hui**,
hors de portée de tout invariant : `docs/sprint1_relecture.md:42`, où la
relecture du sprint 1 cite le défaut qu'elle venait de trouver dans
`config.example.toml`, coordonnée et commentaire compris, « soit le centre de
Rennes, la ville où habite le mainteneur ». Le défaut d'origine a bien été
corrigé, son procès-verbal non. Les deux détecteurs de coordonnées du dépôt
(`tests/test_invariants.py`, `tests/adversarial/test_adv_invariants.py`) ne
scannent que `src/ourouler/` et `tests/` : `docs/` n'a jamais été regardé.

La même coordonnée a aussi vécu dans l'historique, retirée depuis de HEAD :
`config.example.toml` (blob `53f8d50`, « Rennes centre en exemple »),
`tests/test_invariants.py` (les villes en décimal avant leur écriture en
centièmes entiers), `tests/test_boucle_geometrie.py`, et
`tests/test_meteo_openmeteo.py` (au centième près, puis au dix-millième).

**Deux décisions à prendre, aucune n'est prise ici** : (a) `docs/` est-il
anonymisé avant publication — la précision du 13/09 range « coordonnées »
parmi ce qui ne se publie pas, la réponse du même jour range « les chiffres »
parmi ce qui peut rester, et un point de domicile n'est ni tout à fait l'un ni
tout à fait l'autre ; (b) l'historique est-il réécrit pour autant. Rien n'a
été touché : un centre-ville reste une coordonnée publique, et `docs/cadrage.md:15`
dit déjà « j'habite près de Rennes » en toutes lettres — c'est le couple
décimal accolé à la phrase qui mérite un arbitrage, pas une urgence.


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

## Q8 — À quelle puissance calculer la colonne « temps estimé » de `boucle` — **close le 13/09/2026**

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

## Q13 — L'affichage de `sortie` ne montre que les blocs — **corrigée par le lot L5.2** (arbitrée le 15/09/2026, livrée au sprint 5 ; statut constaté le 17/09/2026)

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
- **`--adresse-depart`** est le nom du **lieu** de départ — un départ autre
  que la maison, annoncé au plan du sprint 4 sous le nom provisoire
  `--depuis`. Le nom a d'abord été **réservé** (gardé par un test, pour qu'il
  ne soit pas pris par autre chose), puis **livré le 17/09/2026 par le lot
  F0.7** sur `meteo`, `boucle` et `sortie` — pas sur `simuler`, qui part du
  GPX qu'on lui donne et non d'un point. Ce que le test réservait est
  désormais vérifié à l'endroit : le nom retenu existe, les noms écartés non,
  et le lieu n'écrase pas l'heure. Ce que la commande fait d'une adresse
  ambiguë est en Q34.

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

## Q18 — Une carte par proposition, ou une seule ? — **tranchée le 16/09/2026** (`sortie/carte.py:49`), clôture à confirmer

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

## Q19 — `sortie` perd toute la météo au-delà de la portée d'AROME — **correction livrée** (repli de modèle, `boucle/meteo_trace.py:114`), clôture à confirmer

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

**Refermé sur les deux chemins — 17/09/2026.** Le repli (point 1) avait été
écrit sur `sortie` et **pas** sur `boucle` : `boucle/commande._meteos`
appelait `meteo_trace.evaluer` sans `modele_repli`, si bien qu'une boucle
libre demandée à J+3 perdait les trois colonnes météo exactement comme la
sortie du 19 septembre. `boucle` passe désormais le même repli, nomme dans son
en-tête le modèle qui a **répondu** (et non celui qui est configuré, qui
aurait menti une fois sur deux), et rend `modele_meteo = {utilise, repli}`
dans son JSON, même forme que `sortie`.
*Vérifié sur la configuration réelle* : `ourouler boucle --heure-depart
<J+3>T10:00` rendait avant « météo indisponible » et un tableau sans pluie,
sans vent, sans ressenti ; il rend maintenant les trois, par `icon_seamless`,
sous l'en-tête « meteofrance_arome_france_hd ne couvre pas cette fenêtre —
bascule sur icon_seamless ».

## Q20 — La page du jour n'applique pas la méthode Strava qu'elle voulait — **correction livrée le 16/09/2026** (`sortie/carte.py:53`), clôture à confirmer

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

## Q21 — Les trois chiffres affichés sous une proposition sont illisibles ou alarmants à tort — **corrections livrées** (a : `sortie/commande.py:1583` ; c : `sortie/contraste.py:438`), clôture à confirmer

Relevé par le mainteneur sur la ligne de sa sortie du 19/09 :

> `1:59 (⚠ séance amputée de 1 min), 1,3 feux/stops/passages au km, aucun
> demi-tour, 57 % de grands axes, 93 % de routes connues`

### a) « ⚠ séance amputée de 1 min » — le seuil existe déjà et n'est pas respecté

Ses mots : « 1 min en plus ou en moins n'est pas un seuil important, faire une
alerte quand on est à 5 % de différence de durée, pas moins ».

**Sa règle des 5 % est déjà dans sa configuration** : `ParametresSeance.
elasticite_calme_min = -0.05`, et `placement.py` s'en sert pour décider d'un
« retour au calme raccourci ». Pourtant 1 h 59 pour 2 h prescrites — **0,8 %**
— sort avec l'avertissement. Le paramètre est là, l'affichage ne le respecte
pas. **Corriger en honorant la valeur existante, pas en ajoutant un second
seuil** : le mainteneur a déjà répondu à cette question, dans son fichier.

### b) « 1,3 feux/stops/passages au km » — la moyenne cache ce qui compte

Ses mots : « pas simple à comprendre pour un béotien et ça paraît énorme. Ça
veut dire un arrêt tous les km ou presque. Mais **la distribution de ça est
plus importante** : si c'est ça tout du long c'est affreux, si y en a beaucoup
en début et fin c'est pas pareil. »

Deux défauts en un. Le chiffre est **illisible** (une densité par kilomètre
n'est pas une grandeur de cycliste) et il est **faux comme résumé** : la même
moyenne recouvre une sortie hachée de bout en bout et une sortie fluide
encadrée de deux traversées d'agglomération — et la seconde, c'est presque
toutes ses sorties, qui partent de Rennes et y reviennent.

**C'est exactement l'intuition de Q17** — « ce qui sépare le village de la
ville, c'est l'étendue, pas la densité » — appliquée cette fois à
l'affichage. Les deux se corrigent ensemble : regrouper les marqueurs, puis
dire la chose en langage de cycliste, par exemple « 6 km hachés au départ,
puis rien pendant 40 km ».

### c) « 57 % de grands axes » — l'étiquette fait peur pour rien

Ses mots : « ça fait peur, ça veut dire quoi ? »

Ça veut dire : 57 % des kilomètres sont sur des routes classées `primary`,
`secondary` ou `trunk` dans OpenStreetMap (`boucle/couts.py::HIGHWAY_TRAFIC`).
Autour de Rennes une `secondary` est une **départementale ordinaire**, pas une
quatre-voies. L'étiquette « grands axes » évoque le danger là où la mesure ne
décrit qu'une classe administrative.

Et surtout : **il a déjà dit que ça ne le gêne pas.** « Une départementale
rapide ne me gêne pas pour un bloc ; là, le souci, c'est que c'est en ville. »
On l'alarme donc sur le critère dont il se moque, et on reste muet sur celui
qui l'intéresse.

À trancher avec lui : renommer (« routes départementales »), requalifier
(distinguer `secondary` de `primary`/`trunk`, qui n'ont pas le même sens à
vélo), ou retirer de la ligne de résumé et le garder au détail.

### Complément du 16/09/2026, sur une séance **à blocs** cette fois

Le mainteneur a rejoué une séance à blocs. Deux constats de plus, tous deux
vérifiés dans le code.

**d) Un trou dans la carte : la boucle de la sélection n'est pas dessinée.**
Ses mots : « on n'a plus de tracé sur la carte sur une zone ».

`carte.py:1095` construit la polyligne grise de la boucle complète pour
**chaque** proposition, mais `:1102` ne l'ajoute que `si p.n !== actifN` —
donc uniquement pour les **non sélectionnées**. La sélectionnée ne dessine que
ses blocs et ses liaisons : la portion qu'elle ne parcourt pas, au-delà d'un
demi-tour, n'est peinte par personne.

Ce n'est pas un défaut de calcul — vérifié, les blocs et liaisons couvrent
2 687 points pour une boucle de 2 269, demi-tours compris. C'est un calque
manquant. Correction : la sélectionnée dessine **aussi** sa boucle en fond,
sous ses blocs.

**e) Les pointillés doivent changer de sens, et sa règle est meilleure que la
nôtre.** Ses mots : « les pointillés sont très mal lisibles, il faut les
réserver à la trace non sélectionnée ».

Aujourd'hui le pointillé (`dashArray: '6 8'`, `carte.py:1070`) veut dire
« cette portion n'est pas un bloc » — héritage de L5.2, où il distinguait
l'échauffement et les récupérations du tracé non parcouru. Sur la page du
jour, il entre en collision avec la hiérarchie qui compte : sélectionnée
contre les autres.

**Règle retenue : le pointillé veut dire « ce n'est pas la sélection », et
rien d'autre.** Un seul sens au lieu de deux. La proposition sélectionnée est
donc **pleine de bout en bout** — blocs en couleurs vives, reste du parcours
en couleur franche, boucle non parcourue en fond — et les autres propositions
sont en pointillé gris. Ça résout aussi (a) et (b) plus haut : le fort devient
franchement fort, et le faible devient identifiable au trait plutôt qu'à une
nuance de gris.

## Q22 — Le GPX se télécharge, mais la page n'est pas sur le téléphone — **constat du 16/09/2026, sans correction possible avant le sprint 7**

**Le doute déclaré de L5.4 est levé** : le mainteneur a ouvert la page depuis
son Bureau et le lien « Télécharger le GPX » fonctionne. Ni l'agent ni le
superviseur ne pouvaient le vérifier — leur navigateur refuse `file://`. Le
mécanisme `blob:` + `<a download>` tient donc depuis une page locale sur
macOS.

**Mais il ajoute : « je suis sur ordi, pas sur mobile », et c'est le vrai
sujet.** Q5 a été close sur le **partage système depuis le téléphone** vers
Garmin, Coros et les autres. Or la page du jour vit sur le disque du Mac :
télécharger le GPX sur l'ordinateur ne met rien sur le compteur.

**Les deux chemins qui marchent aujourd'hui**, et ce sont des contournements :

- importer le GPX dans Garmin Connect web, qui le pousse sur l'Edge ;
- envoyer le `.gpx` (ou la page) vers le téléphone par AirDrop, puis
  « Ouvrir avec » → Garmin Connect. C'est bien le partage système de Q5, à
  ceci près que le fichier part du Mac au lieu d'être déjà sur le téléphone.

**Ce n'est pas un défaut du lot, c'est la limite d'une page écrite sur un
disque**, et elle était connue au cadrage : `docs/plan_sprints_agents.md`
décrit la page du jour comme « la maquette du futur front », et le sprint 7
comme le moment où « la même page sera servie par le serveur au lieu d'être
écrite sur le disque ». C'est ce jour-là que le partage devient direct.

Rien à corriger d'ici là. À garder en tête pour le dogfooding : le mainteneur
jugera la **page** sur son Mac, mais le trajet réel vers le compteur restera
manuel, et ce n'est donc pas ce que le sprint 6 mesure.

## Q23 — Les fichiers produits atterrissent dans le dépôt — **corrigée** : destination par défaut sous `config.cache.dossier / sorties` (`sortie/commande.py:606`, constaté le 17/09/2026)

`ourouler sortie` sans `--carte` ni `--sortie` écrit `sortie_AAAAMMJJ.gpx` et
`sortie_AAAAMMJJ.html` **dans le répertoire courant**, c'est-à-dire le dépôt
quand on lance la commande depuis là — ce que fait le mainteneur.

**Aucune fuite possible aujourd'hui** : `*.gpx` est dans `.gitignore`, les
`.html` aussi, et `git status` reste vide. La règle absolue 1 tient.

Mais ces fichiers portent ses **coordonnées de départ**, et ils s'accumulent
dans le dossier du projet. Ils sont à un `zip -r` de voyager avec le dépôt le
jour où il l'envoie à quelqu'un, ou à un `git add -f` près. Un fichier que
seul `.gitignore` protège n'est pas protégé, il est seulement discret.

Correction : destination par défaut hors du dépôt — `~/ourouler/` ou le
répertoire de cache déjà configuré.

### Complément du 16/09/2026 — un quatrième empêchement : le cadrage

Relevé par le superviseur sur la capture de la page du 19/09 ouverte dans
Safari : les deux boucles font 56 km de tour, soit ~18 km de diamètre, et la
vue s'étale de Ploërmel à Laval — environ 150 km. Elles se réduisent à deux
petits pointillés au centre.

**Hypothèse, à vérifier** : ce n'est pas un défaut de calcul des limites mais
une proportion. Le conteneur de la carte est très large et peu haut ;
`fitBounds` ajuste alors sur la hauteur et laisse la largeur s'étaler. La
correction est côté mise en page — une carte plus haute — ou côté cadrage.

**Les quatre empêchements de Q20 se cumulent**, et c'est ce qui explique
qu'une carte dont toutes les données sont présentes paraisse vide :

1. la boucle de la sélection n'est pas dessinée (trou au-delà d'un demi-tour) ;
2. le tracé sélectionné est en pointillé pâle quand la séance n'a pas de bloc ;
3. la non-sélectionnée est peinte trop clair pour les tuiles ;
4. et le cadrage réduit le tout à quelques pixels au centre.

Aucun des quatre n'est grave seul. Ensemble, ils annulent la carte.


## Q24 — Son répertoire se resserre, et il ne décrit pas ses directions comme il les roule — **mesure du 16/09/2026, deux questions produit**

Mesure exploratoire demandée dans ses mots : « si tu analyses mon historique
encore une fois, tu dois pouvoir voir ce que je cherche à faire quand je
roule ». Reproductible, sans réseau :

    uv run python tests/validation/style_retrospectif.py

161 sorties route extérieures depuis le 01/12/2023, dont **109 parties de la
même base** — les seules que les mesures de direction regardent, un azimut
n'ayant de sens que par rapport à un point fixe.

**Le script a été écrit pour pouvoir ne rien trouver**, et il ne trouve pas
tout ce qu'on lui a demandé de chercher : l'un des trois effets candidats est
rendu au bruit par son propre contrôle. C'est la même discipline que la mesure
d'orientation au vent, revenue nulle le 15/09.

### a) Il roule un très petit terrain, et il le roule de plus en plus petit

- 6 368 km roulés sur **~2 000 km de réseau distinct** : chaque kilomètre de
  route a été parcouru 3,2 fois. Les 5 % de mailles les plus roulées portent
  **45 %** des kilomètres ; une maille a été passée 79 fois.
- **53 % des sorties** sont à plus de 85 % identiques à une sortie déjà faite
  (recouvrement de mailles de 30 m, `apprentissage.routes`).
- Contrôle qui aurait pu démentir : à 15-25 km de la base — là où les options
  existent, contrairement aux trois premiers kilomètres — la part déjà vue
  reste à **0,91** sur la seconde moitié de l'historique. Ce n'est donc pas
  l'entonnoir du départ.
- Et la diversité des directions d'une sortie **baisse** : 1,79 bit en 2023,
  1,13 en 2024, 0,88 en 2025, 0,69 en 2026 (entropie sur 8 secteurs).
  Spearman −0,365. Contrôle de longueur : l'effet survit à distance appariée
  et sur le résidu d'une régression sur log(km), Spearman −0,348, p = 0,0005.
  Il est **nul sur les sorties de 30-50 km**, qui n'ont pas le choix, et le
  plus fort sur les **70-120 km**, qui l'ont (−0,616).

**La question produit** : est-ce que ce resserrement lui convient, ou est-ce
qu'il le subit ? C'est exactement la forme de Q17 — la mesure montre l'écart,
lui seul en connaît la cause. Si c'est subi, l'outil a un rôle évident :
proposer la boucle de la bonne durée qu'il n'a **pas** déjà faite, sans jamais
faire de `part_connue` un critère (doctrine).

### b) Il ne nomme pas le secteur où il roule le plus

Ses mots du 16/09 : « peu au nord-ouest, un peu plus au nord-est, surtout sud
et ouest ». Mesuré, en part des kilomètres au-delà de 3 km de la base :

    SE 44 %  >  S 20 %  >  E 10 %  >  SO 7 %  >  NE 6 %  >  O 5 %  >  N 5 %  >  NO 2 %

Deux de ses quatre repères tiennent (le nord-ouest est bien son secteur le
plus rare, le sud est bien dans ses premiers). Deux ne tiennent pas : le
**sud-est**, qu'il ne cite pas, porte à lui seul plus de kilomètres que les
quatre secteurs qu'il nomme réunis ; et l'**ouest**, qu'il croit fréquent,
arrive sixième sur huit.

Réserve honnête : une rose des vents n'est pas une carte mentale, et il se
peut qu'il appelle « sud » ce que la boussole appelle sud-est. Le décalage de
vocabulaire expliquerait la moitié de l'écart — **pas l'ouest**.

**La question produit** : quand la page du jour dit « au sud-ouest », parle-t-
elle la même langue que lui ? Si non, toute la couronne météo et la phrase de
direction visent à côté.

### c) Ce qui ne tient pas, et qu'il ne faut pas lui raconter

« Il refait de plus en plus ce qu'il a déjà fait » : **c'est du bruit**. La
ressemblance médiane à une sortie précédente passe bien de 0,71 à 0,91 entre
les deux moitiés de l'historique, mais mélanger l'ordre des sorties reproduit
la même montée (p = 0,32). Une courbe d'accumulation monte quel que soit
l'ordre. Le **niveau** est un fait, sa **pente** n'en est pas un.

### d) Deux mesures de contexte, sans question attachée

- **Forme** : distance parcourue ÷ distance maximale au départ = **3,20** de
  médiane (2,00 = aller-retour pur, 3,14 = boucle circulaire). Il fait des
  boucles, pas des allers-retours : 10 % seulement des sorties sont sous 2,4,
  et 72 % finissent à moins d'un kilomètre du départ.
- **Effort** : sa puissance monte de +19 W par point de pente, quand rouler à
  vitesse constante en demanderait +78. Il parcourt **25 %** du chemin entre
  « puissance constante » et « vitesse constante » — il lève le pied en côte
  (199 W en montée contre 154 à plat) et ne se relance pas en descente
  (107 W). Aucune des 96 sorties ne dépasse la moitié du contrefactuel.

### Ce que la mesure ne peut pas trancher

Rien ici ne sépare « il choisit ce secteur » de « le réseau ne lui laisse que
celui-là ». Il faudrait comparer à ce qui est **routable** autour de sa base,
ce qui demande le moteur de tracé et une notion d'offre par direction. C'est
la suite naturelle, et elle est chiffrable.

### Réponses du mainteneur, 16/09/2026 — et ce qu'elles donnent au projet

**a) Répétition ou exploration ?** « Non, car ce n'est pas une volonté, c'est
le manque d'outil et la facilité. Donc je fais ce que je connais, **surtout
quand il y a des blocs**. »

**b) Où va-t-il ?** « Oui, c'est un fait mesurable. » Et sur le sud-est :
« c'est plus sud-est, je suis d'accord, c'est un raccourci, mon sud ». La
réserve de méthode du script — sa boussole mentale contre la vraie — est donc
levée par lui : l'écart sur l'ouest tient, celui sur le sud était de
vocabulaire.

**c) Régulier ou au terrain ?** « Ça dépend : si bloc, je cherche plutôt du
plat. Mais ça dépend aussi du (a), je fais ce que je connais. »

**d) Forme des sorties ?** « Boucle avec une portion aller-retour pour aller
sur zone, parfois. »

## Ce que ces réponses établissent, et c'est le cœur du produit

**Trois fois de suite, l'historique enregistre une contrainte et non un
goût** :

| Observé | Ce que j'en avais déduit | Ce qu'il en dit |
|---|---|---|
| 2,91 marqueurs urbains/km | il ne fuit pas la ville | « je ne connais pas les contournements » |
| 53 % des sorties déjà faites à 85 % | il aime ses routes | « pas une volonté, le manque d'outil » |
| 44 % au sud-est | il préfère le sud-est | indécidable, mais « c'est un raccourci, mon sud » |

**Conséquence produit, et c'est la formulation la plus nette qu'on ait eue :**
la valeur de `ourouler` n'est pas de proposer un beau parcours — c'est de
**laisser le cycliste sortir de son répertoire sans prendre de risque sur sa
séance**.

Le mécanisme est celui du (a) : sans outil, on ne peut pas savoir qu'une route
inconnue portera un bloc de 8 minutes, donc on se rabat sur ce qui a déjà
marché. C'est précisément ce que le sprint 4 sait faire — évaluer un couloir
avant d'y aller. La mesure du sprint 5 donne l'ampleur de ce qu'il y a à
gagner : il roule 6 368 km sur 2 000 km de réseau distinct, et l'effet de
resserrement est **le plus fort sur les sorties de 70-120 km**, celles qui
ont le choix.

**Et ça reconfirme la doctrine du même jour** (« les routes déjà roulées sont
un instrument de mesure, jamais un critère ») pour la troisième fois : un
score qui apprendrait de ses habitudes apprendrait ses contraintes, et les
lui rendrait en les appelant ses préférences.

## Deux suites mesurables que ces réponses ouvrent

1. **« Si bloc, je cherche plutôt du plat »** est vérifiable : ses séances à
   blocs roulent-elles un terrain plus plat que ses autres sorties, à
   distance comparable ? Si oui, c'est un critère à faire entrer dans le
   placement, et il l'a formulé lui-même.
2. **Le demi-tour est un moyen, pas un défaut.** « Boucle avec une portion
   aller-retour pour aller sur zone » : il s'en sert pour **atteindre un bon
   segment**. La page ne doit donc pas vendre « aucun demi-tour » comme un
   avantage, mais dire à quoi sert celui qu'elle propose — « un aller-retour
   pour attraper la ligne droite ». À reprendre dans Q20/Q21 quand les
   phrases seront revues.

## Q25 — Évite-t-il une classe de trafic estimé ? — **oui, nettement, mesuré le 16/09/2026**

Question du mainteneur : « tu peux voir si sur mes sorties réelles un truc
montre que j'évite clairement une classe de trafic estimé ? »

`estimated_traffic_class` est un pseudo-tag que BRouter calcule — population
des villes proches pondérée par le **carré** de la distance, zones
industrielles, aéroports, densité du réseau. Ce n'est pas une classe de route
et il n'existe **aucune correspondance en véhicules par jour** : c'est une
pénalité de routage. Les trois autres pseudo-tags documentés (`town_class`,
`forest_class`, `river_class`) ne sont **pas** renvoyés par notre serveur, ni
`maxspeed`, ni `lanes` — vérifié.

**Le résultat, standardisé par anneau de 5 km à la base** — le contrôle qui
compte, puisque la classe monte près des villes et que ses sorties partent de
chez lui :

| Classe | Observé / attendu | Sorties sous l'attendu |
|---|---|---|
| 1 | 215 % *(magnitude peu fiable, voir réserve)* | 17 % |
| 2 | 101 % | 67 % |
| 3 | 146 % | 21 % |
| 4 | 84 % | 71 % |
| **5** | **54 %** | **88 %** |
| **6** | **51 %** | **81 %** |

**Classes hautes (5 et 6) réunies : 53,7 % de l'attendu, 102 sorties sur 111
en dessous, p < 0,0001.** Il prend la moitié de ce que le moteur lui
proposerait à distance de base égale.

Et le gradient est monotone à partir de la classe 3 : 146 → 84 → 54 → 51. Ce
n'est pas l'évitement d'une classe en particulier, c'est une pente.

**Le contrôle qui aurait pu démentir, et qui ne le fait pas** : la part de
tronçons **sans classe** (18 % des km) sort à **103,2 %, p = 0,85** —
parfaitement neutre. Si l'effet venait d'un artefact du rejeu BRouter ou de la
reconstruction d'itinéraire, cette part aurait dérivé elle aussi. Elle ne
bouge pas.

**Pourquoi ce résultat compte plus que les autres :**

1. **Il tranche**, là où l'orientation au vent était nulle et où les marqueurs
   urbains allaient dans le sens contraire de l'intuition.
2. **Il correspond à ce qu'il dit** : « grand axe dans ma tête c'est une
   nationale ou une grosse pénétrante à fort trafic ; une départementale, je
   dirais que c'est pas chiant ». La mesure confirme sa propre description.
3. **Il n'entre pas en contradiction avec Q17.** Il roule *plus* de marqueurs
   urbains que les boucles proposées (feux, passages piétons — les arrêts des
   bourgs) et *moins* de trafic estimé. Il accepte de s'arrêter dans un
   village, il refuse de rouler sur une route passante. Ce sont deux choses
   différentes et il les traite différemment.
4. **La donnée est gratuite et déjà là**, dans chaque réponse BRouter, et le
   code ne la lit nulle part.

**Conséquence : `estimated_traffic_class` remplace notre classement binaire.**
`HIGHWAY_TRAFIC` (`boucle/couts.py`) met `primary`, `secondary` et `trunk`
dans le même sac ; `trunk` vaut zéro et vaudra toujours zéro (mesuré sur 381
km dans huit directions, BRouter n'y envoie jamais un vélo), et `secondary`
porte les deux tiers du chiffre alors qu'il n'en a cure. Le trafic estimé,
lui, distingue la départementale tranquille de la passante — et c'est
précisément ce qu'il évite.

Script : `tests/validation/trafic_estime_retrospectif.py`.

**Le second contrôle, et c'est celui qui emporte l'affaire** : le brut
**comprimait** l'effet, la standardisation l'a **renforcé**. Classe 5 : 82 %
en brut, 54 % standardisé ; classe 6 : 76 % en brut, 51 %. Si la distance à la
base avait gonflé un effet apparent, la contrôler l'aurait réduit. C'est
l'inverse qui se produit.

**Réserves, à reprendre partout où cette mesure est citée :**

- **La classe 1 (215 %) a une magnitude peu fiable** : beaucoup de sorties ont
  un « attendu » quasi nul pour cette classe, ce qui fait exploser le ratio.
  La **direction** résiste au test du signe, pas le chiffre.
- **Le rejeu BRouter n'est pas la trace GPS** — un point de passage tous les
  1,5 km, le moteur recolle entre eux. Ce qui est mesuré est l'itinéraire
  reconstruit.
- **15 % des kilomètres réels classables sont exclus** faute d'anneau couvert
  côté proposé.
- **Le comparateur tourne en profil `fastbike`, qui fuit déjà le trafic.** Le
  test est donc **conservateur** : l'écart réel est probablement plus grand
  que 54 %, pas plus petit.

**Correction d'une observation antérieure du superviseur** : j'avais annoncé
au mainteneur « 34 % de tronçons sans classe » et « une échelle de 3 à 6 » sur
la foi d'**une seule boucle** sondée au cap 135°. La mesure sur 111 sorties
donne **18,2 % sans classe** et une échelle qui va bien **de 1 à 6** — les
classes 1 et 2 existent en quantité non négligeable (17,3 % et 13,5 % des km).
Une boucle n'est pas un échantillon.

## Q26 — Le levier est plus simple que prévu : privilégier les `tertiary` — **mesuré et validé le 16/09/2026**

Question du mainteneur, après une discussion qui partait dans le détail :
« pour être sûr — je prends plus de tertiary, ou bien BRouter en propose
plus ? »

Mesuré sur 25 de ses sorties rejouées (1 559 km, de 28 à 134 km) contre des
boucles proposées **aux mêmes longueurs**, dans six directions :

| Classe OSM | Lui | Proposé |
|---|---|---|
| `tertiary` | **60,0 %** | 37,6 % |
| `secondary` | 16,2 % | **32,5 %** |
| `unclassified` | 15,3 % | 15,6 % |
| `primary` | 4,2 % | 6,9 % |
| `residential` | 1,1 % | 3,4 % |

**C'est lui qui va chercher les `tertiary`** — une fois et demie ce qu'on lui
propose — **et le moteur qui le ramène vers les `secondary`**, dont il prend
moitié moins.

**Deux mesures indépendantes, la même réalité.** Les classes de trafic calmes
vivent dans les `tertiary` (359 km de classes 1-2 sur 428, croisé sur ses
sorties). Prendre 1,5 fois plus de `tertiary` et la moitié du `secondary`,
c'est exactement le « 54 % des classes hautes » de Q25, vu depuis l'autre
côté.

**Conséquence, et elle simplifie tout ce qui précède** : le levier n'est ni de
trier à l'intérieur des `secondary` — les `secondary` calmes ne pèsent que 4 %
de ses kilomètres — ni de pénaliser `primary`, qui n'en pèse que 4,2 %.
**C'est de privilégier les `tertiary`.** Un seul critère, sur la grandeur la
plus séparante : 22 points d'écart sur `tertiary`, 16 sur `secondary`.

Le trafic estimé reste en réserve : il capte la proximité des villes, que la
classe OSM ignore. À garder si, une fois le poids `tertiary` calibré, les
boucles produites ne reproduisent pas sa répartition de classes de trafic.

**Calibration** : la cible est chiffrée — 60 % de `tertiary`, 16 % de
`secondary`. On règle le poids jusqu'à ce que les boucles proposées s'en
approchent. Même méthode que les poids de terrain au sprint 3.

**Erreur du superviseur, enregistrée parce qu'elle est instructive.** J'avais
affirmé au mainteneur : « il vous propose plus de routes très calmes que vous
n'en prenez », sur la foi de la répartition **brute** (24,1 % de classe 1
proposée contre 17,3 % réelle). Or le rapport de mesure dit lui-même que le
brut « ne sert qu'à situer l'écart avant le contrôle », et le chiffre
**contrôlé** disait l'inverse. J'ai conclu à partir du nombre que la mesure
me disait de ne pas utiliser. Le mainteneur l'a relevé.

## Q27 — Les séances à blocs ont une autre répartition de routes — **mesuré le 16/09/2026**

Question du mainteneur : « les sorties où j'ai des blocs spécifiques ont-elles
la même répartition ? Je fais beaucoup de Z2 et ça s'entend de faire du
tertiary où le côté roulant importe peu. Mais quand j'ai des blocs, est-ce que
la répartition est fondamentalement différente ? »

### Comment reconnaître une séance à blocs — deux méthodes fausses avant la bonne

1. **La variabilité de puissance : fausse**, et c'est lui qui l'a dit — « la
   moindre montée un peu poussée, c'est foutu ». Elle attrapait 6 sorties dont
   5 n'étaient que des bosses, et donnait un résultat **inversé** (41 % de
   `tertiary` sur les prétendues séances à blocs, contre 70 % en réalité).
2. **La séance planifiée au calendrier : fausse aussi.** Elle ne trouvait
   qu'**une** sortie sur 142, ce qui m'a fait écrire au mainteneur que le cœur
   du produit servait un cas quasi inexistant. Faux : ses séances ne sont pas
   toujours posées au calendrier.
3. **La bonne : le nom de l'activité.** « des découpages clairs dans la séance
   par bloc avec souvent un nom associé » — « Rennes - 4x15 SST R3' (90 % FTP) ».
   Motif `NxM`, plus « durabilité », « rappel », « dont NN' ». Exclus : les
   endurances encadrées (EF, Z2, « 4H », « 3H à 75 % »). **21 séances
   structurées en extérieur**, pas une.

### Le résultat

Médianes, 20 séances structurées contre 35 régulières :

| | Blocs | Sans bloc | Écart |
|---|---|---|---|
| `tertiary` | **72,2 %** | 61,8 % | **+10,4** |
| `secondary` | **4,9 %** | 14,5 % | **−9,6** |
| `unclassified` | 14,6 % | 15,7 % | −1,1 |
| `primary` | 0,1 % | 0,7 % | −0,6 |

**Les jours de blocs, il prend trois fois moins de départementales.** Le
chiffre bouge à peine entre 17 et 21 séances détectées, ce qui plaide pour sa
solidité.

**Le biais joue en faveur de la conclusion** — réserve du mainteneur, retenue :
la détection ne voit que ce qui est dans le nom, donc ses séances à blocs non
nommées sont comptées comme régulières et **rapprochent les deux colonnes**.
L'écart réel est plus grand que 10 points, pas plus petit.

### Ce qui bouge, et ce qui ne bouge pas

Observation du mainteneur : `primary` et `unclassified` sont **stables**.
`unclassified` est un fond constant (≈15 % dans les deux cas), `primary` un
plancher (il n'en prend jamais). **Tout ce qui varie avec le type de séance
est un arbitrage `tertiary` contre `secondary`, et rien d'autre** — donc un
seul paramètre à faire varier avec l'intensité, pas une grille.

### Les trois règles, chacune avec son motif distinct

| Règle | Pourquoi |
|---|---|
| `trunk` interdit | Sécurité. Gratuit : il vaut déjà zéro sur 381 km mesurés. |
| `primary` pénalisé, toujours | **Corrige le moteur, pas le cycliste** : les boucles proposées en portent 6,9 % quand il en prend 4,2 %, et ≈0 sur ses séances structurées. |
| `secondary` pénalisé **selon l'intensité** | 14,5 % en Z2, 4,9 % en blocs. |

`unclassified` n'a besoin d'aucune règle : 15,3 % chez lui, 15,6 % dans les
boucles proposées. Ils sont déjà d'accord.

### Ce que ça corrige de ce que j'avais proposé

**Le trafic doit peser dans la note des blocs.** Je proposais l'inverse, en
m'appuyant sur ses mots — « une départementale rapide ne me gêne pas pour un
bloc ». Ses sorties disent le contraire : ces jours-là il les évite trois fois
plus. **Troisième cas de la soirée où la mesure contredit le souvenir**, après
les côtes (sprint 3) et les villages (Q17).

Et le poids n'est pas unique : il varie avec l'intensité, comme le coût des
descentes depuis le sprint 4.

### La cible de calibration, corrigée du biais de corridor

Le mainteneur a soulevé le bon doute : son corridor répété fausse-t-il les
pourcentages ? Mesuré, sur 30 sorties et 13 089 mailles distinctes de 30 m :

| | Par km | Par sortie | **Routes distinctes** |
|---|---|---|---|
| `tertiary` | 58,7 % | 62,1 % | **48,0 %** |
| `secondary` | 16,5 % | 14,3 % | **25,0 %** |

Son corridor répété est **plus `tertiary` que son réseau** : compter chaque
route une fois fait perdre 11 points au `tertiary`. Calibrer sur 60 %
reviendrait à calibrer sur sa répétition, donc à apprendre ses habitudes en
croyant apprendre ses goûts — le piège que la doctrine interdit. **48 % est la
cible honnête.** Les 11 points d'écart sont la mesure du corridor.

## Q28 — « 1,7 feux/km » : l'unité invitait à multiplier, le composite mélangeait l'arrêt et le rien — **corrigé le 16/09/2026**

Ses mots : « quand je lis 1,7 feux par km, si je fais 100 km je me dis que je
vais croiser 170 feux ».

**Deux défauts, et aucun n'était celui que j'annonçais.** J'avais renvoyé ce
point au sprint 6 en croyant qu'il demandait la mesure par étendue. Faux :

1. **L'unité invite à multiplier.** « au km » se lit « × la distance ». Un
   nombre absolu sur la sortie ne peut pas se mal lire.
2. **Le composite est dominé par ce qui coûte le moins.** Mesuré sur une
   boucle réelle de 55 km : **457 marqueurs, dont 296 passages piétons (65 %)
   et 28 feux (6 %)**. Ce qui arrête vraiment — feux et stops — fait 48 sur
   55 km, pas 457. Additionner un feu et un passage piéton, c'est additionner
   un péage et un panneau.

**Corrigé** : l'affichage montre les **nombres absolus, séparés** — « 15 feux,
1 stop » contre « 26 feux, 9 stops » sur la sortie du 19/09. Les passages
piétons sortent du résumé ; ils restent dans la note de terrain, où ils pèsent
peu et à juste titre. L'axe de contraste, lui, compare des **arrêts au
kilomètre**, comparable entre boucles de longueurs différentes : deux besoins,
deux formes de la même mesure.

## Q29 — L'effet de concentration des feux, et le poids qui dépend de l'intensité — **sans sprint attribué**, voir [[Q53]]

Sa remarque, dans le même message : « je pense qu'il y a un **effet de
concentration** sur feux et stops. C'est ce qu'il faut réduire sur les blocs ;
en Z2 ça a beaucoup moins d'importance. »

C'est sa vieille idée d'**étendue** (Q17, Q21 b), appliquée cette fois au bon
sous-ensemble. Ce n'est pas la densité de *tous* les marqueurs qui compte,
c'est **un paquet de feux qui tombe dans un bloc**. Le même paquet sous une Z2
ne coûte presque rien.

**Ce que ça demande** : mesurer la concentration des seuls nœuds d'arrêt
(`NOEUDS_ARRET`) le long du parcours — non pas leur nombre, mais leur
regroupement — et faire dépendre leur coût de l'intensité de l'étape.

**Et ça fait la troisième grandeur qui varie avec l'intensité**, ce qui
commence à ressembler à un principe plutôt qu'à trois exceptions :

| Grandeur | Établi |
|---|---|
| Coût d'une descente | sprint 4 (`FACTEURS_ZONE_DESCENTE`) |
| Part de départementales | Q27 — 14,5 % en Z2, 4,9 % en blocs |
| Concentration des feux | ici, à mesurer |

À vérifier avant d'implémenter, avec la méthode des autres mesures : ses 20
séances structurées portent-elles des paquets d'arrêts plus petits que ses
sorties régulières, à distance de base appariée ?

## Q30 — Les feux sous les blocs : rien de net, et c'est un résultat — **mesuré le 16/09/2026**

Idée du mainteneur : « faire générer des itinéraires de type bloc et regarder
la concentration des éléments de circulation — cédez-le-passage, feux, stops,
giratoires — entre récup et bloc ». Comparaison **appariée dans la même
sortie**, donc qui contrôle la géographie, la distance au départ, le jour et
la météo d'un seul coup.

Deux questions distinctes, et les deux ont été mesurées.

### Q1 — notre moteur fait-il son travail ? **Non concluant, par la géographie**

`placer` note le terrain sous les blocs et **n'évalue jamais les
récupérations** (règle du sprint 4). Si le placement fonctionne, les blocs
doivent porter moins d'arrêts que les récups de la même sortie.

Mesuré sur 32 sorties générées, 120 blocs et 88 récups : **la médiane vaut
zéro marqueur des deux côtés** — 205 étapes sur 208 strictement sans marqueur.
Le test du signe ne trouve que des égalités. Rien à trancher.

**Ce n'est pas un bug de comptage**, et l'agent l'a vérifié : en forçant un
échauffement d'une minute, donc un bloc collé au départ, les marqueurs
réapparaissent par dizaines. La cause est ailleurs — **autour de Rennes, les
nœuds tagués disparaissent presque entièrement dès qu'on sort du cœur urbain,
dans toutes les directions**. Avec un échauffement réaliste, le bloc *et* la
récup voisine trouvent tous deux un couloir à zéro carrefour.

**Ce n'est donc pas une preuve que le moteur échoue, ni qu'il réussit.** La
mesure n'a pas de prise sur cette géographie.

### Q2 — le critère est-il réel ? **Rien de net**

16 sorties réelles exploitables sur 21, 64 blocs et 54 récupérations.

| | Bloc | Récup | Test du signe |
|---|---|---|---|
| Arrêts au km | 0,28 | 0,00 | 7/15 favorables, **p = 1,000** |
| Ralentissements au km | — | — | 6/16 favorables, **p = 0,454** |

**Rien ne sépare ses blocs de ses récupérations.** Les contrôles
(échauffement et retour au calme contre récup) sont tout aussi muets.

### Ce qu'il faut en conclure, et ce qu'il ne faut pas

**Ne pas conclure qu'il ne cherche pas à éviter les carrefours.** Les deux
médianes sont minuscules (0,28 et 0,00) : il n'y a **rien à éviter** une fois
hors de la ville, donc rien à mesurer. La mesure ne sépare pas « il ne le fait
pas » de « il n'y a pas lieu de le faire ».

**Conclure que le poids des carrefours sous les blocs est quasi inerte sur son
terrain.** `POIDS_CARREFOUR = 1,0` porte déjà dans le code l'aveu qu'il n'est
« pas validé par la validation rétrospective… le raisonnement produit, pas une
mesure ». Cette mesure-ci a essayé de le valider et n'a rien trouvé, non
parce qu'il est faux mais parce qu'il ne s'applique presque jamais.

**Et ça réordonne le sprint 6.** Ce qui distingue vraiment ses jours de blocs
n'est pas le carrefour mais **la classe de route** : 4,9 % de départementales
contre 14,5 % (Q27), un écart net et testé. La concentration des feux (Q29)
perd donc beaucoup de son intérêt : elle décrirait un phénomène qui n'existe
qu'en ville, où il ne fait pas ses blocs.

**Réserve qui pourrait tout changer** : la mesure a été faite au départ de
chez lui, en Bretagne bocagère. Un cycliste partant d'une agglomération dense
aurait une tout autre réponse — c'est un rappel que les poids du placement
sont calibrés sur **un** terrain, et que la version hébergée devra le dire.

Script : `tests/validation/arrets_bloc_recup.py`.

## Q31 — La distance de dégagement urbain, et pourquoi elle se dit en kilomètres — **sans sprint attribué**, voir [[Q53]]

Demande du mainteneur : « une fonction qui fait une recherche à partir de
l'adresse de départ sur la **distance minimum d'échauffement** avant de
trouver une zone où la densité de feux et stops est intéressante. Et je parle
bien de **distance**, car en zone urbaine la puissance n'aide pas ou peu :
c'est la densité de feux et d'arrêts qui gère. »

### Pourquoi la distance et pas la durée — et c'est une limite du modèle

**La calibration exclut les échantillons sous 8 km/h**, marqués « arrêt »
(`physique/calibration.py`, `vitesse_min_kmh = 8.0`). Le modèle physique a
donc appris la vitesse **en roulant**, et n'a jamais appris le coût d'un
arrêt. Il ne l'a pas appris de travers : il ne l'a pas appris du tout.

Conséquence : **toute durée annoncée sur une portion urbaine est optimiste**,
d'autant plus que la densité de feux est forte. Le mainteneur a donc raison
au-delà de la formulation — le kilomètre est la seule grandeur que l'outil
sait dire juste en ville.

### Le profil radial, mesuré le 16/09/2026

Feux + stops au kilomètre, huit boucles par ville, par anneau :

| | 0-3 | 3-6 | 6-9 | 9-12 |
|---|---|---|---|---|
| Rennes | 2,70 | 0,79 | **0,30** | 0,55 |
| Nantes | 2,51 | 0,78 | 0,44 | 0,46 |
| Angers | 2,09 | 0,95 | **0,34** | 0,38 |
| **Les Lilas (93)** | 3,26 | 2,91 | **3,49** | 2,54 |

Distance de dégagement (seuil 0,40/km, la campagne rennaise) : **Rennes et
Angers 6 km, Nantes 12 km, Les Lilas jamais à moins de 15**.

Poussé plus loin pour Les Lilas, par anneaux de 5 km : 3,03 / 3,22 / 2,18 /
1,33 / 0,85 / 0,93 / 0,64. **À une heure de vélo, on est encore à trois fois
la campagne bretonne**, et la densité *monte* entre 0-5 et 5-10 km — on sort
d'un arrondissement pour entrer dans la petite couronne, qui est pire.

### Ce que ça change, et pour qui

**Pas pour le mainteneur.** Mesuré sur ses séances structurées : son premier
bloc démarre à **63 min de médiane** (min 41, max 113), soit ~29 km — quatre à
cinq fois la distance de dégagement. La question ne se pose jamais chez lui.

**La règle plutôt que le paramètre.** Ce n'est pas la durée d'échauffement qui
compte, c'est **où le bloc tombe par rapport au départ**. Cette formulation
couvre les trois cas sans rien régler : chez lui rien à signaler ; son
exception « enchaînement vélo-course avec bloc final » signalée
automatiquement, le bloc étant près de la maison ; et l'Île-de-France signalée
honnêtement — « vos blocs porteront 4 à 5 feux ».

**Et pour l'Île-de-France, la vraie réponse n'est pas routière.** Le
mainteneur la donne lui-même : « aller à Longchamp, ou trouver d'autres
segments boucle pour tourner en cercle ». C'est ce que font les cyclistes
franciliens — un anneau court sans feux, répété. Voir Q32.

## Q32 — Le mode circuit : tourner en rond quand il n'y a pas de couloir — **sans sprint attribué**, voir [[Q53]]

Notre modèle produit propose **une boucle parcourue une fois**, blocs placés
dessus. Un Francilien a besoin d'un **circuit court répété** : quatre tours de
Longchamp (3,6 km, sans un feu) pour un 4×8.

**C'est à portée de ce qui existe** : le moteur sait générer des boucles ; il
suffirait d'en demander des **courtes** (3 à 6 km), de les noter sur les nœuds
d'arrêt, et de proposer « 2 tours par bloc » quand l'une sort à zéro feu. La
détection est le comptage qu'on vient d'écrire.

**Ce qui est un vrai morceau, c'est le placement** : il fait coulisser les
blocs le long d'un tracé, il faudrait qu'il sache les poser sur des tours
répétés.

Effet de bord notable : la règle « le demi-tour, autorisé mais pas à mettre en
avant » (Q20) **ne s'applique plus** en mode circuit. Répéter le même segment
vingt fois y est la fonctionnalité, pas le défaut.

**Et ça déplace la question de la version hébergée** : inviter des copains ne
veut pas dire « le même outil pour tout le monde ». Un Rennais et un
Francilien n'ont pas besoin du même produit. Découverte qui vaut mieux
maintenant qu'au sprint 8.


## Q33 — La cible de course, et la butée qui l'empêche — **V2, mesuré le 16/09/2026**

Idée du mainteneur, née d'une digression sur le potentiel de son vélo de
chrono : *« ça peut permettre de calculer une cible de course d'ailleurs avec
le parcours et la météo à 3 jours de la course »*.

**Ce qui existe déjà.** `ourouler simuler` prend le GPX d'un parcours, une
puissance et le vélo calibré, va chercher **le vent prévu** si on lui donne
une heure de départ, et rend le temps simulé — en texte comme en JSON. Les
trois quarts du chemin sont faits.

**Ce qui manque, par ordre de coût.**

1. **L'inversion.** Aujourd'hui : puissance → temps. Il faudrait : temps visé
   → puissance à tenir. C'est une bissection sur la même fonction, et le
   module en fait déjà une dans `vitesse_regime`. Peu de code.
2. **Le rappel de l'horizon.** Le vent se demande pour une heure de départ,
   mais la fiabilité mesurée s'arrête à trois jours (`HORIZON_ORIENTATION_J`,
   88 % de bon secteur à J+3). Une cible préparée à une semaine doit dire
   qu'elle ne sait pas, pas deviner.
3. **Le CdA du jour de course — et c'est le point bloquant.**

**La butée, mesurée sur deux courses.** Ajustement CdA/Crr fait sur la seule
partie vélo de deux triathlons, isolée par les points portant de la puissance,
avec le vent d'archive du jour :

| course | partie vélo | CdA | Crr | RMSE |
|---|---|---|---|---|
| Sables-d'Olonne, 22/06/2025 | 176,5 km en 5 h 32, 31,9 km/h | **0,1800** *(butée)* | 0,00583 | 81 W |
| Châtelaillon, 11/05/2025 | 86,0 km en 2 h 38, 32,7 km/h | **0,1800** *(butée)* | 0,00883 | 83 W |

`CDA_MIN = 0,18` (`physique/calibration.py:138`) est **un plancher trop haut
pour une position de chrono tenue**. Les deux courses s'y collent : ce n'est
pas un accident de l'une d'elles.

**Conséquence sur la lecture, et elle est importante.** Quand le CdA est
coincé à la butée, **le Crr n'est plus identifié** : il devient le résidu qui
absorbe ce que le CdA n'a pas eu le droit d'expliquer. Les deux valeurs de Crr
ci-dessus ne parlent donc pas des pneus — elles disent que la résistance
totale inexpliquée diffère entre les deux courses.

**Et l'écart de 62 W** que ce CdA donne contre le vélo de route à 32 km/h est
donc **un minimum, pas une estimation**. Le mainteneur situe le gain de sa
seule position à 25-30 W ; le reste vient des roues, des pneus, de la tenue,
du casque et de l'asphalte neuf.

**Pourquoi ça bloque la cible de course, et pas les sorties d'entraînement.**
Pour une sortie ordinaire, le CdA moyen des positions réellement tenues est le
bon chiffre — c'est la réserve écrite dans l'en-tête du module. Pour une cible
de course, il faut le CdA du jour de course. Avec celui d'entraînement, la
cible serait systématiquement pessimiste : une puissance plus haute que
nécessaire pour tenir le temps visé. Sur cinq heures, c'est l'erreur qui coûte
le marathon derrière.

**Réserves de la mesure.** Une course porte des relances et des passages
abrités, et le modèle n'a aucun terme d'aspiration — d'où un RMSE de plus de
80 W. Une chute est visible à Châtelaillon (102 s sous 8 km/h au km 5,8) mais
ne pollue pas l'ajustement : l'échantillonnage écarte déjà tout ce qui roule
sous 8 km/h, et 236 tronçons sur 420 ont été retenus.

**Décision du mainteneur** : noté pour la V2. Le cadrage du front passe avant.


## Q34 — Une adresse sans commune donne cinq départs à égalité — **tranchée et livrée le 17/09/2026**

Livré au lot F0.7, `--adresse-depart` retient le **premier candidat** rendu
par le géocodeur et l'annonce sur la sortie d'erreur avant tout appel coûteux
(le raisonnement complet est dans la docstring de `cli.lieu_depart`). La
question est de savoir s'il faut, en plus, **refuser** quand les meilleurs
candidats sont trop proches.

**Ce qui a été mesuré**, en appelant la BAN pour de vrai le 17/09/2026. Les
requêtes étaient des **lieux publics** — des gares, des mairies — et jamais une
adresse du mainteneur ; elles ne sont pas recopiées ici, ce dépôt ne porte
aucune adresse réelle, pas même dans une mesure. Seuls les chiffres comptent :

| forme de la requête | score du 1ᵉʳ | score du 2ᵉ | les deux sont-ils au même endroit ? |
|---|---|---|---|
| une rue avec son numéro, son code postal et sa commune | 0,98 | 0,71 | oui, même commune |
| une gare, désignée par sa grande ville | 0,55 | plus bas | oui |
| une gare, désignée par une ville moyenne | 0,61 | 0,56 | **non** — le 2ᵉ est à 200 km, dans un autre département |
| une rue avec son numéro, **sans commune** | 0,9774 | 0,9773 | **non** — cinq communes, jusqu'à 400 km d'écart |

Deux enseignements. Une adresse **avec** sa commune ne pose pas de problème :
l'écart de score est franc, le premier candidat est le bon. Une adresse
**sans** commune donne des scores séparés par un dix-millième, dans des
communes sans rapport : le premier candidat est alors **arbitraire**, et seule
l'annonce du lieu retenu évite la réponse fausse.

**Pourquoi rien n'a été ajouté.** Refuser « quand c'est trop serré » demande un
seuil, et aucun seuil ne se déduit de ces quatre mesures : 0,0001 d'écart est
clairement une égalité, 0,27 clairement pas, et la gare de ville moyenne (0,05) tombe
entre les deux avec la bonne réponse en tête. Poser un chiffre maintenant
serait un choix arbitraire présenté comme une mesure (règle absolue 5).

**La question** : le mainteneur préfère-t-il (a) ce qui est livré — on retient
le premier et on le dit ; (b) un refus quand l'écart entre les deux premiers
est sous un seuil qu'il fixe, avec la liste affichée et le code de sortie 2 ;
ou (c) un refus dès que les deux premiers sont dans des **communes
différentes**, ce qui ne demande aucun seuil mais demande à `Candidat` de
porter la commune, que la BAN rend déjà et que le connecteur jette aujourd'hui ?

Côté API (F1), la question ne se pose pas : la route de géocodage rendra la
liste complète au front, qui fera choisir, et les routes de parcours
recevront des **coordonnées** déjà tranchées.

### Réponse du mainteneur (17/09/2026) — on refuse, et on ne calibre rien

> « ben simple : on refuse. Et on peut faire contrôler la position en
> affichant un point, voire proposer la géoloc sur mobile. S'il faut, en V1,
> on fait un formulaire à champs obligatoires. »

**Ce que cette réponse fait de mieux que les trois options proposées** : elle
retire la question au lieu d'y répondre. Aucun seuil n'est à inventer, parce
qu'on n'accepte plus l'entrée qui crée l'ambiguïté.

La mesure le soutient : dès que la commune est présente, l'écart de score
passe à 0,98 contre 0,71, franc, et le premier candidat est le bon. **Les cinq
départs à égalité n'existent que pour une adresse sans commune.** Rendre la
commune obligatoire supprime le cas plutôt que de le gérer.

**Ce que ça donne, par surface :**

- **Le formulaire du front** : des champs séparés et obligatoires — numéro,
  voie, code postal, commune — plutôt qu'une ligne de texte libre. Moins
  élégant qu'un champ unique, mais c'est ce qui rend la réponse sûre.
- **Le point sur la carte** : l'adresse géocodée se confirme à l'œil avant
  d'être retenue. Un géocodage qui se trompe de commune est indétectable dans
  un champ texte, visible en une seconde sur une carte.
- **La géolocalisation sur mobile** : celui qui part de chez lui n'a rien à
  taper. À noter pour l'implémentation : le navigateur ne la donne que sur
  HTTPS (ou en local) et après autorisation explicite — donc jamais comme
  seul chemin, toujours en plus du formulaire.
- **La ligne de commande** : c'est là que « on refuse » a le plus de sens,
  puisque personne ne peut confirmer un point. Une adresse ambiguë est
  refusée avec ses candidats affichés, au lieu d'en retenir un au hasard.

**Ce qui tombe** : l'option (b), un seuil fixé à la main, et l'option (c),
refuser sur les communes différentes. Ni l'une ni l'autre n'est nécessaire si
la commune est demandée.

### Ce qui a été livré (17/09/2026), et la mesure qui l'a guidé

**Quinze requêtes sur la vraie BAN, lieux publics uniquement** — mairies,
gares, préfectures, jamais une adresse du mainteneur ; comme au premier tour,
elles ne sont pas recopiées, seuls les chiffres comptent.

| forme de la requête | n | écart de score 1ᵉʳ–2ᵉ | communes distinctes |
|---|---|---|---|
| neuf adresses complètes (n° + voie + CP + commune) | 1 à 5 | — | **1**, les neuf fois |
| une voie + sa commune, sans numéro | 1 | — | 1 |
| n° + voie + CP, sans nom de commune | 1 | — | 1 |
| une rue, sans commune ni CP | 5 | 0,0024 | **5** |
| « place de la mairie », sans commune | 5 | 0,0016 | **5** |
| « place de la gare », sans commune | 5 | 0,0018 | **5** |
| une gare désignée par sa grande ville | 5 | **0,0020** | **1** |

**La dernière ligne ferme définitivement l'option (b).** Une requête dont la
réponse est *juste* a le même écart de score (0,0020) qu'une requête dont la
réponse est *arbitraire* (0,0016 à 0,0024). Les deux intervalles ne se touchent
pas : ils se recouvrent. Aucun seuil ne peut les séparer, et il ne s'agissait
pas de ne pas avoir assez mesuré — la grandeur ne porte pas l'information.

**La commune, elle, sépare parfaitement sur les quinze.** D'où la règle, qui
ne mesure rien : `geocodage.ambiguite()` refuse quand les candidats rendus ne
désignent pas tous la même commune (nom normalisé + code postal, pour séparer
deux homonymes), ou quand l'un d'eux n'a pas de commune du tout — on ne peut
alors pas vérifier que la réponse est franche.

**Une nuance par rapport à ce qui précède, et il faut la dire.** La réponse
ci-dessus fait tomber l'option (c) « parce que la commune est demandée ». C'est
vrai du front, qui a un formulaire pour la demander. La ligne de commande n'en
a pas : `--adresse-depart` prend une ligne de texte. Le test sur les communes y
est donc la façon d'**exiger** la commune, pas une option concurrente — il
rend le refus quand elle manque, et laisse passer quand elle est là. Ce n'est
pas l'option (c) qui revient, c'est la décision qui s'applique à une surface
sans formulaire.

**Par surface, ce qui tourne :**

- **Le front** (`front/src/composants/FormulaireAdresse.tsx`) : quatre champs
  séparés et obligatoires, une phrase qui dit pourquoi, la liste des candidats
  avec leur commune, **un point sur la carte à confirmer** avant que quoi que
  ce soit soit retenu, et « Utiliser ma position » en plus. Branché sur E10
  (assistant), E16 (« partir d'ailleurs ») et les réglages. `ChoixAdresse.tsx`,
  le champ de texte libre, a été retiré.
- **La géolocalisation** : proposée seulement quand le navigateur sait la
  donner **et** que la connexion est sécurisée ; sinon une phrase dit pourquoi.
  Le refus d'autorisation affiche « c'est votre choix » et renvoie au
  formulaire — ce n'est pas une panne. Le point obtenu est une coordonnée :
  faute de géocodage inverse, il s'affiche en chiffres, sans nom de rue
  inventé.
- **La CLI** : `--adresse-depart` ambiguë → les candidats s'affichent avec leur
  commune, puis `ErreurUtilisateur` et code 2. Rien ne retombe sur le départ
  configuré, et l'erreur le dit.
- **L'API** : chaque candidat porte `commune` et `code_postal` ; la charge
  porte `ambigu` et `motif_ambiguite`. **La route ne refuse pas** — elle rend
  tout et fait choisir, c'est le front qui a la carte. Les routes de parcours
  ne prenaient déjà que des coordonnées : rien à y changer.

### Ce qui reste ouvert

- **Le numéro obligatoire.** Les quatre champs sont obligatoires, comme
  demandé. Aucune mesure ne soutient l'obligation du **numéro** : seule la
  commune a été mesurée, et « place du Capitole 31000 Toulouse », sans numéro,
  rend un seul candidat dans une seule commune. Conséquence concrète : partir
  d'une gare ou d'une place n'est pas exprimable sans inventer un numéro. Faut-
  il délier le numéro (obligatoires : voie, CP, commune) ?
- **Le géocodage inverse n'existe pas** et n'a pas été ajouté. La BAN a un
  `/reverse` ; le connecteur ne l'expose pas. Conséquence : une position du
  téléphone n'a pas de nom lisible. À ouvrir si le nom compte — il ne compte
  pas pour tracer une boucle.
- **La règle dépend du nombre de candidats demandé** à la BAN. À cinq (le
  défaut, et ce que la CLI demande toujours), la séparation est nette sur les
  quinze requêtes. À vingt, des communes lointaines et mal notées
  apparaîtraient et feraient refuser plus souvent. Fixe côté CLI, libre côté
  `geocoder --max` et côté API — qui ne refusent ni l'un ni l'autre.
- **Pas d'échappatoire en coordonnées côté CLI.** Une adresse que la BAN ne
  sait rattacher à aucune commune est inutilisable en ligne de commande. Un
  `--coordonnees-depart LAT,LON` la débloquerait ; il n'a pas été ajouté parce
  que personne ne l'a demandé et que le front couvre le cas.

## Q35 — Quelles sections du TOML du serveur sont communes, et lesquelles appartiennent au cycliste — **fuite fermée le 17/09/2026, arbitrage à rendre**

**Ce qui a été trouvé.** `api/depots.py` fusionnait la surcharge d'un
propriétaire **par-dessus** le TOML du serveur. Tout ce qu'un propriétaire ne
surchargeait pas, il en héritait : `DepotProfils.config(Proprietaire("autre-cycliste"))`
rendait la clé Intervals, l'identifiant d'athlète et le point de départ du
mainteneur. Les tests qui prétendaient couvrir le sujet ne regardaient que le
champ surchargé (la FTP) et concluaient que « les profils ne se mélangent
pas » ; la moitié héritée n'était vérifiée nulle part.

**Ce qui a été fait, et pourquoi c'est volontairement peu.** Un socle sait
désormais **à qui il appartient** (`SocleTOML(chemin, proprietaire=…)`). La
fabrique de service déclare le TOML comme étant celui du mainteneur, et le
dépôt refuse de le servir à un autre propriétaire au lieu de lui offrir ce
qu'il n'a pas surchargé. Rien ne change pour le mainteneur, qui reste le seul
propriétaire jusqu'à F3.

**Ce qui n'a pas été tranché, parce que ce n'est pas à un agent de le faire.**
Découper le TOML entre ce qui est **commun au serveur** (`cache`, `brouter`,
`meteo`, seuils de placement) et ce qui est le **profil d'une personne**
(`depart`, `cycliste`, `velos`, `intervals`, `seance`) est un choix produit.
`CHAMPS_MODIFIABLES` en donne déjà une lecture — ce qu'un cycliste peut
éditer — mais « modifiable par le cycliste » et « personnel » ne sont pas la
même chose : le serveur BRouter n'est pas modifiable et n'est pas personnel,
le point de départ est les deux.

**La question**, à rendre avant F3 : (a) le socle reste personnel et chaque
propriétaire part d'un profil vide qu'il remplit à l'inscription ; (b) le
socle est découpé, les sections communes sont héritées par tous et les
sections personnelles ne le sont jamais — auquel cas il faut la liste ; ou
(c) le TOML du serveur devient un fichier d'exploitation sans aucune section
personnelle, et le profil du mainteneur migre dans une surcharge comme celui
de tout le monde.

### Réponse du mainteneur (17/09/2026) — le découpage, section par section

> « tenue oui cycliste, pas par défaut : on a des valeurs et on permet juste
> de changer les seuils, pas d'en créer — V2 les modifications de seuil
> d'ailleurs. Boucle serveur, météo serveur, BRouter serveur, cache serveur. »

**Ce qui appartient au cycliste** — `[depart]`, `[cycliste]`, `[[velos]]`,
`[intervals]`, `[seance]`, `[calibration]`, `[tenue]`.

**Ce qui appartient au serveur** — `[boucle]`, `[meteo]`, `[brouter]`,
`[cache]`.

C'est donc l'option **(b)** de la question : le socle est découpé, les
sections communes sont héritées par tous, les sections personnelles ne le
sont jamais. Et voici la liste, qui était la condition pour que (b) soit
tenable.

**Deux précisions du mainteneur sur `[tenue]`**, et elles resserrent le
périmètre plutôt que de l'ouvrir :

1. **Les valeurs par défaut restent**, et chacun part d'elles. On ne demande
   pas à un nouveau de décrire sa garde-robe pour commencer à rouler.
2. **On ne change que des seuils, jamais la liste des vêtements** — et même
   ça attend la V2. En V1, `[tenue]` appartient au cycliste dans le modèle de
   données, mais son interface d'édition n'existe pas encore.

**Pourquoi `[boucle]` est au serveur, alors qu'il ressemble à une préférence.**
Il porte le nombre de candidates et la tolérance de distance : des réglages
qui **coûtent des appels externes**. Ouvert à chacun, il laisse quelqu'un
demander vingt candidates et faire déborder le quota Open-Meteo pour tout le
monde. C'est un réglage de moteur, pas un goût.

**Deux sections que le mainteneur n'a pas nommées, à trancher :**

- **`[evitements]`** — les routes ou zones qu'un cycliste refuse. Rien de plus
  personnel, mais la question n'a pas été posée explicitement.
- **`historique_depuis`** — la date à partir de laquelle on lit ses activités.
  Elle vit aujourd'hui sous `[cache]`, donc côté serveur d'après ce découpage,
  alors qu'elle décrit l'histoire d'une personne. La règle absolue 6 du projet
  en fait déjà « un paramètre de configuration, pas une constante » — reste à
  dire de quelle configuration.

### Les deux sections orphelines — tranchées le 17/09/2026

> « personnel, avec config par défaut. »

**`[evitements]` et `historique_depuis` appartiennent au cycliste**, avec des
valeurs par défaut pour que personne ne parte d'une page blanche.

Conséquence à traiter : `historique_depuis` vit aujourd'hui **sous `[cache]`**,
donc côté serveur d'après ce découpage — alors qu'elle décrit l'histoire d'une
personne. Le 1ᵉʳ décembre 2023 du mainteneur n'a aucun sens pour quelqu'un qui
s'inscrit demain. Elle sort de `[cache]`, qui parle de stockage.

Le découpage de Q35 est donc complet : **au cycliste** `depart`, `cycliste`,
`velos`, `intervals`, `seance`, `calibration`, `tenue`, `evitements`,
`historique_depuis` ; **au serveur** `boucle`, `meteo`, `brouter`, `cache`.

## Q36 — L'étape « identité » de l'assistant : à quoi elle sert, et où elle se range — **close le 17/09/2026 : l'âge est retiré**

Le cadrage du lot F2 demandait un assistant en six étapes, dont **identité**.
Deux choses s'y opposaient, et aucune n'était un oubli du front.

**Les maquettes ont écarté cet écran exprès.** `maquettes_v1.html` le dit en
toutes lettres au pied de la page : « Les huit absents comprennent l'étape
d'identité de l'assistant, qui n'est pas un oubli mais la question ouverte
n° 4 ». Cette question n° 4 est « l'âge, et ce qu'on en fait » : le brief le
demande, et rien dans le dépôt ne s'en sert — ni le modèle physique, ni les
zones, ni la tenue.

**Et l'API n'a nulle part où le ranger.** `CHAMPS_MODIFIABLES`
(`src/ourouler/api/depots.py`) couvre `depart`, `cycliste.masse_kg`,
`cycliste.ftp_w`, `seance.position_zone`, les vélos et la clé Intervals. Ni
nom, ni prénom, ni âge, ni adresse e-mail. Un `PATCH` qui en porterait serait
**refusé et nommé** — c'est le comportement voulu du dépôt. Écrire l'écran
aurait donc demandé d'inventer d'abord un stockage, c'est-à-dire de trancher
la question à votre place.

**Ce que le lot F2 a fait à la place**, et qui se défait en dix minutes le
jour où vous tranchez : la première étape de l'assistant annonce ce qui va
être demandé, et dit pourquoi on ne demande ni nom ni âge — « on préfère ne
pas garder ce dont on ne se sert pas ». Cinq étapes suivent : FTP et zones,
départ, vélo, Intervals, récapitulatif.

**La question**, en trois morceaux qui ne se répondent pas ensemble :

1. **L'âge** sert-il à quelque chose qu'on veuille construire ? Le seul usage
   plausible dans ce produit serait une fréquence cardiaque maximale estimée,
   et rien n'utilise la fréquence cardiaque aujourd'hui. Sinon, il sort du
   brief.
2. **Le nom** : F3 apporte une adresse e-mail, qui suffit à identifier un
   compte. Un nom d'affichage est-il autre chose qu'un confort — et si oui,
   pour qui, puisqu'il n'y a pas d'écran partagé ?
3. **Si l'un des deux reste**, il faut l'ajouter à `CHAMPS_MODIFIABLES` et
   décider s'il appartient au profil du cycliste ou au compte (Q35 : ce n'est
   pas la même table).

### Réponse du mainteneur (17/09/2026) — il n'y a pas d'étape « identité » séparée

> « pour moi nom prénom adresse FTP etc., ça fait partie de l'identité de la
> création et édition de compte user, non ? »

**Oui, et ça dissout la question plutôt que d'y répondre.** Il n'y a pas une
étape « identité » d'un côté et des étapes techniques de l'autre :
**l'assistant *est* la création du profil**, et tout ce qu'il demande — nom,
prénom, adresse, FTP, vélo, clé Intervals — appartient au même objet.

Ce qui reste à faire est donc du travail, pas un arbitrage : `Config` n'a
aucun champ où ranger un nom ni un prénom, et `CHAMPS_MODIFIABLES` de l'API
n'en connaît aucun — un `PATCH` serait refusé par construction. C'est pour ça
que le front n'a pas livré l'écran, et il avait raison de ne pas inventer un
champ.

**Et l'âge n'y est plus** ([[Q39]]) : l'étape porte nom, prénom et poids, le
poids étant le seul des trois dont le modèle physique se serve aujourd'hui.

### Fait (17/09/2026) — obligatoires, avec compatibilité pour l'existant

Le mainteneur a tranché la question laissée ouverte plus haut (« un nom
d'affichage est-il autre chose qu'un confort ? ») : « nom prénom obligatoire
car c'est la base, voilà, point. »

`Cycliste` porte désormais `prenom` et `nom` ; `CHAMPS_MODIFIABLES` les
accepte. L'obligation est une règle de **parcours** : l'assistant (première
étape, ex-« identité ») refuse de continuer sans les deux, comme il refusait
déjà sans point de départ. Ce n'est pas une règle de **chargement** — les
deux champs restent optionnels dans `Cycliste` (chaîne vide par défaut), pour
qu'une configuration écrite avant ce lot, la mienne comprise, continue à se
charger et à se modifier sans qu'on lui invente un nom. Même traitement que
la migration `puissance_endurance_pct` → `position_zone` et que la colonne
propriétaire des dépôts.

Aucun calcul ne s'en sert aujourd'hui. L'usage réel attend le lot F3 des
comptes multi-utilisateurs (e-mail d'invitation, affichage) — écrit tel quel
dans le code et l'écran, règle absolue 5.

## Q37 — Les sept promesses des maquettes que l'API ne tient pas, et qui demandent chacune un arbitrage

> **(a), (b) et (g) sont tranchées et appliquées** depuis le 17/09/2026 —
> voir [[Q40]]. Le texte ci-dessous décrit l'état d'avant, gardé pour la trace.

Contexte : les 105 tests de contrat écrits en aveugle du code de l'API ont été
réconciliés le 17/09/2026. Trente-huit marques `xfail` dont le motif était
devenu faux ont disparu — l'API les tenait, ou le test les vérifiait mal.
**Sept survivent**, et aucune n'est un oubli d'implémentation : chacune
demande une décision que je ne prends pas à ta place. Elles sont groupées ici
parce qu'elles se répondent entre elles.

**(a) Jusqu'où un parcours reste-t-il servi ?** L'API accepte aujourd'hui
`jour = 2036-09-17` et ne s'en aperçoit qu'au moment où Open-Meteo ne rend
rien — un 502 `meteo_hors_domaine`, c'est-à-dire « le service est en panne »
là où c'est la demande qui est hors de portée. Poser la borne suppose un
chiffre. Les seuls mesurés dans le dépôt sont la portée d'AROME (67 h) et
l'horizon d'orientation au vent (3 jours, mesuré sur 2 064 heures) — et E15
sert justement une séance à J+4, **sans** vent. Donc : à partir de quel jour
l'API refuse-t-elle, et avec quelle phrase ?

**(b) Distinguer « hors du domaine » de « hors de l'horizon ».** E14 · dégradé
corrige explicitement ce défaut. Open-Meteo rend le **même** bloc nul dans les
deux cas ; le cœur refuse de trancher, et il a raison (règle absolue 5). Pour
séparer, l'API devrait connaître la portée publiée de chaque modèle — donc le
même chiffre qu'en (a). La réponse dit aujourd'hui « hors du domaine, ou hors
de sa portée temporelle » : honnête, et moins utile que ce que la maquette
dessine.

**(c) E16 fait saisir une durée, l'API prend une distance.** « Les kilomètres
suivent votre puissance, votre poids et le relief. » Convertir demande le
modèle physique et son état de calibration — et E16 note lui-même que ce
modèle « tourne sur ses valeurs par défaut » pour un invité. Prendre une durée
en entrée est un lot, pas un correctif. Tant qu'elle n'existe pas, la
contradiction « durée **et** distance » n'est pas refusable : il n'y a qu'une
des deux consignes.

**(d) E18 · échec dessine deux leviers chiffrés** (« élargir la durée, 1 h 45 à
2 h 15 », « laisser la direction libre »). L'API rend le code `aucune_boucle`
et son message, rien de plus. De combien élargir, et quel levier proposer en
premier, ne se déduit d'aucune mesure du dépôt : chiffrer ici serait affirmer
sans mesurer.

**(e) E19 · dégradé propose « Chercher plus loin (8 candidates) ».** L'API sait
combien elle en a essayé ; combien en réessayer est le même genre de choix.
Chercher plus large coûte plus cher et peut ne rien donner de plus.

**(f) « 10 feux » n'existe qu'en texte.** Le JSON n'expose que
`densite_marqueurs_km`. Laisser le front multiplier par la distance lui ferait
refaire un calcul du cœur, avec l'arrondi en prime : c'est au cœur de compter
et de publier. Petit lot, mais un lot.

**(g) Un GPX par proposition.** `rendre_json` n'écrit que celui de la candidate
retenue. Les trois propositions sont contrastées exprès ; choisir « la plus
sèche » puis l'envoyer au compteur envoie aujourd'hui la mauvaise trace. La
géométrie, elle, **est** en JSON (`candidates[].trace.points`) : un front peut
déjà dessiner les trois, il ne peut pas en télécharger deux. Écrire trois
traces au lieu d'une à chaque génération se décide en connaissance du coût.

**Un huitième cas, de nature différente.** `seance --json` change de forme
quand il n'y a pas de séance (`{jour, seance: null}` au lieu des huit champs
nominaux), et l'API transmet ce piège au front. Le corriger veut dire poser
une forme de réponse **de référence** pour la séance — donc décider ce qui
vaut `null` et ce qui disparaît — et cette forme est aussi celle que la ligne
de commande rend. Ce n'est pas un correctif d'API.


## Q38 — Le fichier déposé est une séance à faire — **tranché le 17/09/2026**

La question traînait depuis les maquettes : un `.ZWO` ou un `.MRC` déposé
décrit-il **la séance qu'on va faire**, ou **la sortie qu'on vient de faire** ?

**Réponse du mainteneur** : « le fichier déposé c'est une séance à faire ».

C'est une prescription. Ce qui est déjà implémenté au lot F0.5 et branché en
F0.7 (`--fichier-seance`) est donc juste, et rien n'est à reprendre.

**Ce que cette réponse laisse entier**, et qu'il ne faut pas confondre avec
elle : lire une sortie **déjà faite** pour la comparer à ce que l'outil avait
annoncé. C'est la boucle de vérification, proposée au sprint 6 et jamais
tranchée — elle passera par le FIT du retour, pas par un fichier déposé à la
main, et elle reste ouverte.

## Q39 — L'âge ne sera pas demandé — **tranché le 17/09/2026**

Le brief du 16/09 demandait « nom, prénom, âge, poids » dans l'assistant de
configuration. La discovery avait relevé que **rien dans le dépôt ne se sert
de l'âge** : ni le modèle physique, ni les zones de puissance, ni la tenue.

**Réponse du mainteneur** : « l'âge on s'en fout ».

Il sort de l'assistant. Demander une donnée dont on ne fait rien est du
formulaire pour du formulaire, et chaque champ de l'installation est un
endroit où quelqu'un s'arrête.

Une conséquence pour [[Q36]], qui portait sur l'étape « identité » : privée de
l'âge, elle ne contient plus que le nom et le prénom — dont le dépôt n'a pas
davantage l'usage aujourd'hui. La question de savoir si cette étape existe
encore se pose donc avec plus de force, pas moins.


## Q40 — Réponses du mainteneur aux sept promesses de [[Q37]] — **17/09/2026**

**(a), (b) et (g) sont appliquées** (17/09/2026). Ce qui a été livré, et ce
qui reste à trancher, est noté sous chaque réponse ci-dessous ; le contrat
correspondant est dans `docs/ux/api_contrat.md`. (c), (d) et (e) restent
ouvertes ; (f) attend la mesure de densité par tranche.

### (a) et (b) — aucune limite de date, et la météo se tait d'elle-même

> « pour le jusqu'à quand : aucune limite. Juste, si on demande trop loin, ben
> pas de météo. Donc si la personne donne une date hors de portée de la météo,
> lui dire direct "pas de météo" et hop. »

**L'API ne refuse pas une date lointaine.** Elle sert le parcours et dit que
la météo est absente — ce qui est exactement l'état dégradé que les maquettes
dessinent (E14 · dégradé) : la boucle reste servie, ce qui disparaît sont les
affirmations qu'on ne peut plus soutenir, la pluie, le vent et la tenue.

Ça referme (b) du même geste. Aujourd'hui l'API répond « hors du domaine, ou
hors de sa portée temporelle » parce qu'Open-Meteo rend le même bloc vide dans
les deux cas. Avec cette réponse, **la distinction cesse d'être nécessaire du
côté produit** : dans les deux cas l'utilisateur lit « pas de météo pour ce
jour-là », et le parcours arrive quand même. Le message doit dire quel jour est
le dernier couvert, pas pourquoi il l'est.

**Livré le 17/09/2026.** `POST /sorties` et `POST /boucles` portent
`meteo_absente = {jour, dernier_jour_couvert, message}`, `null` quand la météo
a répondu ; `tenue`, `modele_meteo` et `candidates[].meteo` tombent à `null`,
et plus aucun 502 `meteo_hors_domaine` ne sort d'une route de parcours. Le
chiffre du message vient de `[meteo] horizon_jours` — **7 par défaut, mesuré
le 17/09/2026 sur le vrai service** : AROME HD s'arrêtait à J+2, `icon_seamless`
à J+7, et c'est le modèle de repli qui fixe la portée. Réglable, parce que la
portée appartient au modèle et pas au projet. Au-delà de l'horizon, aucun appel
n'est fait — ~150 prévisions pour des blocs vides.

**Le repli de Q19 tient** : vérifié sur la configuration réelle, J+2 et J+3
gardent leur météo par `icon_seamless` (`modele_meteo.repli = true`) et leur
tenue conseillée.

**Ce qui reste douteux.** L'horizon est celui qu'`icon_seamless` couvrait *ce
jour-là* ; il bougera avec le modèle configuré et avec les publications
d'Open-Meteo. Un chiffre trop grand ne coûte qu'un appel inutile (la réponse
dégradée reste juste), un chiffre trop petit retirerait une météo réellement
disponible. Le mesurer à l'exécution — une requête de sonde sur le point de
départ — est possible et n'a pas été fait : ça ajoutait un appel réseau dans
le cœur pour une phrase. À reprendre si la portée d'un modèle change souvent.

### (f) — le compte de feux n'est pas l'information ; la concentration l'est

> « pour moi l'info est secondaire si on n'a pas le comptage des feux qui
> sépare le départ/arrivée du reste. C'est une aide au calcul, mais l'info
> user c'est plutôt : aucune zone avec une densité de stop/feux de plus de X
> par km durant les 30 premiers kilomètres. »

**Cette réponse change la question plutôt que d'y répondre**, et elle a
raison. Un total de 10 feux répartis sur 56 km ne gêne personne ; **10 feux
groupés sur les 4 premiers kilomètres ruinent l'échauffement.** Le total est
une aide au calcul ; ce que le cycliste veut savoir, c'est s'il existe une
zone dense, et où.

Ça rejoint ce que le mainteneur disait déjà en septembre : *« y a un effet de
concentration sur feux et stops, c'est ce qu'il faut réduire »* (Q29), et la
distance de dégagement urbain (Q31). Les trois sont la même idée, prise par
trois bouts.

**Ce que ça implique, et qui n'est pas petit** : il faut mesurer la densité
**par tranche de parcours**, pas sur la boucle entière. Le « X par km » et la
fenêtre « 30 premiers kilomètres » restent à fixer — et cette fois ils
peuvent l'être par la mesure, sur l'historique, comme l'a été la distance de
dégagement.

### (g) — aucun GPX à la génération, un GPX au choix

> « oui, j'ai vu, et c'est con. Pourquoi ? Si c'est le coût de stockage et de
> création, je propose d'en faire aucun et de le faire à la demande quand
> l'user choisit son parcours. »

**Génération paresseuse.** Écrire trois traces dont deux seront jetées est un
gaspillage ; n'en écrire qu'une et se tromper de laquelle est un défaut — la
proposition retenue n'est pas forcément celle que le cycliste choisit. Écrire
à la demande supprime les deux, et la question du stockage avec.

La géométrie des trois est déjà en JSON (`candidates[].trace.points`), donc le
front peut les dessiner sans rien écrire sur disque.

**Livré le 17/09/2026.** Le cœur reçoit `recueil_gpx=` : absent (ligne de
commande), il écrit le GPX de la proposition retenue comme avant ; présent
(l'API), il n'écrit rien et remet les deux ou trois textes à l'appelant. Chaque
proposition du JSON porte alors
`gpx = {nom, url}` vers `GET /api/v1/sorties/{generation}/propositions/{n}/gpx`,
qui rend le fichier lui-même — donc rien n'est écrit non plus au moment du
choix. Vérifié sur la configuration réelle : aucun `.gpx` n'apparaît dans le
cache, et les traces servies pour deux propositions diffèrent.

**Ce qu'une génération oubliée devient.** Les GPX vivent en mémoire, bornés
aux vingt dernières générations ; au-delà, ou après un redémarrage, la route
rend `generation_introuvable` (404) et l'écran redemande une recherche. Les
garder sur le disque coûterait exactement ce que la décision voulait éviter :
la géométrie d'une trace pèse ce que pèse son GPX.

### (c), (d) et (e) — pas tranchées, et pourquoi

**(c)** Le mainteneur renvoie à la conversation du 17/09 sur la vitesse et les
trois valeurs liées : *« c'est le sujet de nos discussions sur les prises
d'infos sur la vitesse moyenne »*. Prendre une durée en entrée demande le
modèle physique et son facteur compteur — le travail est commencé (décisions 7
et 8), le lot ne l'est pas.

**(d) et (e)** Le mainteneur demandait ce que ces écrans voulaient dire ; la
réponse lui a été donnée, il n'a pas tranché. Elles restent ouvertes :
de combien élargir une durée quand aucune boucle ne tombe dans la tolérance,
et combien de candidates réessayer quand moins de trois se distinguent. Aucun
chiffre ne se déduit du dépôt pour l'instant.


## Q41 — Trois corrections du mainteneur sur [[Q40]] — **17/09/2026**

### (d) — élargir par paliers de 5 %, et le dire

> « les tests que j'ai faits ne disent pas ça : j'ai demandé 6 h et j'ai
> 3 boucles de 5 h. Mais le mieux c'est de dire au user "on n'a pas trouvé de
> boucle dans les contraintes, on a élargi de X %", et on incrémente de 5 %
> en 5 %. Comme ça on explique. »

**Deux choses dans cette réponse.** La première est une observation qui
contredit ma description : demander 6 h rend trois boucles de 5 h, donc le
moteur ne refuse pas — il sert hors tolérance sans le dire. **C'est un défaut
plus grave que celui dont on parlait**, et il est à vérifier avant tout le
reste.

La seconde est la réponse à la question posée, et elle évite le seuil inventé
que je cherchais : **on n'en fixe aucun**. On élargit par paliers de 5 %
jusqu'à trouver, et **l'écran dit de combien il a fallu élargir**. Le chiffre
n'est plus une constante à justifier, c'est un résultat à afficher.

#### Fait le 17/09/2026

**L'observation du mainteneur était juste, et le défaut est confirmé.**
`boucle/candidates.py` gardait la candidate la plus proche de la cible et la
servait avec son écart, sans un mot : `tolerance` ne servait qu'à arrêter
l'affinage du rayon. Mesuré sur son serveur BRouter avant correction, sa
tolérance étant réglée à 10 % : **2 km demandés, 2,69 km servis, +34,7 %**,
muets.

Ce qui a changé :

1. Chaque candidate porte `tolerance`, `elargissement` et `hors_tolerance`,
   rendus en JSON sur `boucle` comme sur `sortie`, et affichés en texte et à
   l'écran. Rien ne s'affiche quand la boucle tient dans la tolérance.
2. Le palier se **lit** sur l'écart mesuré, il ne se cherche pas : élargir la
   tolérance ne peut rendre qu'une boucle égale ou pire, puisqu'elle arrête
   l'affinage plus tôt. Un test le mesure plutôt que de l'affirmer (règle 5).
3. **L'élargissement s'arrête**, et son plafond n'est pas un chiffre : c'est
   `tolerance_distance` réemployée comme unité — la bande peut au plus
   doubler, jamais moins d'un palier. Il suit la configuration (5 % réglés
   s'arrêtent à 10 %, 20 % réglés à 40 %), ce qu'un seuil arbitraire ne fait
   pas. Au-delà, le refus porte ses mesures au lieu d'un « réessayez ».

Vérifié sur les vraies routes du mainteneur, où les trois régimes
apparaissent dans l'ordre attendu : 3 km demandés sont servis dans la
tolérance dans les huit directions ; 4 km vers le nord-ouest rendent 3,3 km,
soit **−17 % — l'ordre de grandeur de son « 6 h demandées, 5 h servies »** —,
désormais servis en disant « tolérance élargie de 10 %, soit ±20 % » ; 1,5 km
sont refusés partout, le terrain ne sachant pas faire une boucle si courte.

Reste ouvert, non traité ici : quand une partie seulement des directions est
refusée, les candidates écartées disparaissent sans que rien ne le dise —
`sortie` a `motif_deux_propositions` pour ce genre de silence, `boucle` n'a
rien d'équivalent.

### (e) — abaisser le recouvrement, et surtout demander la météo une seule fois

> « pour la météo, vu que la zone est proche, on peut pas demander une météo
> une fois de manière large ? »

**Vérifié dans le code, et il a raison.** `sortie/commande.py:871-877` boucle
sur les candidates retenues et appelle `evaluer_meteo(trace, …)` **à
l'intérieur de la boucle** : chaque candidate paie sa propre interrogation.
C'est ce qui explique les temps mesurés — 1,6 s à deux candidates, 2,9 s à
trois, 6,9 s à cinq.

Or toutes les boucles d'une même génération tiennent dans le même rayon
autour du même point de départ. **Une seule grille couvrirait les huit.**
Le coût de « chercher plus loin » retomberait alors sur BRouter seul, et la
question (e) — combien de candidates réessayer — perdrait l'essentiel de son
enjeu.

À instruire : la maille d'Open-Meteo, l'interpolation des points de trace sur
cette grille, et ce que ça change pour la précision — une prévision prise à
la maille voisine n'est pas la même qu'une prévision prise au point.

Seconde idée du mainteneur, indépendante : **abaisser le seuil de
recouvrement** accepté entre propositions, de 25 % à 30 % de routes
communes — « ça doit arriver sur les petits parcours ».

### (f) — je m'étais trompé de sens, et il corrige

> « alors, 10 feux sur les 4 premiers kilomètres ne me dit pas "ça ruine mon
> échauffement" du tout. Ça me dit : je ne vais pas avoir de feu après, donc
> je suis peinard. La traversée de ville au départ, pour les citadins, c'est
> normal. C'est justement une info écran, pas une aide au calcul. »

**J'avais écrit l'inverse**, et c'était faux : j'affirmais que des feux
groupés au départ ruinaient l'échauffement. Pour quelqu'un qui habite en
ville, traverser sa ville est le prix normal de la sortie — et **savoir
qu'ils sont tous groupés au début est rassurant**, parce que ça dit que la
suite est libre.

Ce qui doit s'afficher n'est donc ni un total, ni une alerte : c'est **la
répartition** — où sont les arrêts le long du parcours. Groupés au départ,
c'est une bonne nouvelle ; semés tout du long, c'en est une mauvaise. Et le
total redevient ce que le mainteneur en disait : une aide au calcul.

Ça garde le lien avec [[Q29]] (la concentration) et [[Q31]] (la distance de
dégagement), mais renverse le signe : la concentration au départ n'est pas le
problème, c'est **l'absence de concentration** qui en est un.


## Q42 — Le cache météo : mesuré à l'intérieur d'une génération, décisif seulement entre utilisateurs — **17/09/2026**

Idée du mainteneur, née de [[Q41]] (e) : plutôt qu'une requête globale sur une
zone, **garder entre les requêtes ce qu'on a déjà** — « la première route coûte
cher, les suivantes un peu moins ».

### Ce qui est mesuré

La météo est échantillonnée **tous les 5 km le long du tracé**
(`PAS_DEFAUT_M = 5000.0`, `boucle/meteo_trace.py`), et Open-Meteo décompte
**un appel par coordonnée**. En arrondissant à la maille (~1,1 km au
centième de degré, à comparer aux 1,3 km d'AROME France HD), sur de vraies
candidates générées par le BRouter du mainteneur :

| | points demandés | mailles distinctes | économie |
|---|---|---|---|
| 5 candidates de 55 km | 56 | 46 | **18 %** |
| 8 candidates de 55 km | 89 | 68 | **24 %** |
| 5 candidates de 170 km | 165 | 143 | **13 %** |

**Deux enseignements.** L'économie **monte avec le nombre de candidates**
(18 % à cinq, 24 % à huit) : le cache aide donc là où le mainteneur voulait
qu'il aide, pour « chercher plus loin ». Mais elle **baisse avec la
longueur** (13 % à 170 km) : les boucles divergent en s'éloignant, et c'est
précisément là que le coût est le plus élevé.

### Pourquoi ça ne vaut pas un lot aujourd'hui

Économiser 18 % d'un coût qui n'est pas le goulot. Une génération prend 3 s,
le quota tient à 10 000 appels par jour, et aucun utilisateur ne sentirait la
différence.

### Pourquoi ça en vaudra un à F3, et ce qui manque pour le dire

> « oui, mais plusieurs users dans la même zone : si on se dit qu'une météo
> d'une zone est valable X h, ça va devenir payant. »

**C'est le paramètre qui manquait au calcul ci-dessus.** Une prévision pour
une maille à une heure donnée est la même pour tout le monde. Mesurée à
l'intérieur d'une seule génération, elle ne se partage qu'entre candidates ;
**gardée X heures et partagée entre utilisateurs**, elle se paie une fois
pour toute une région et toute une matinée.

La doctrine §10.1 le prévoit déjà — quota compté **par adresse IP**, donc un
service hébergé fait partager le même compteur à tous les invités.

**Le chiffre de X ne s'invente pas** : AROME France HD est remis à jour toutes
les trois heures. Une heure est sans risque, trois heures est défendable,
au-delà on sert une donnée que le modèle a déjà remplacée.

**Ce qui reste non mesuré, et qui décide du gain réel** : le recouvrement
entre utilisateurs **différents**. Des copains rennais partageraient
beaucoup ; un ami nantais, rien. Le gain dépend de la densité géographique
des invités, pas du produit — et ne se mesurera qu'avec de vrais comptes.


## Q43 — Le tracé se distingue par lui-même : l'exigence d'axe tombe — **17/09/2026**

**Trouvé en utilisant le produit.** Le mainteneur demande une sortie de 2 h le
samedi 19 et reçoit « pas de sortie trouvée » à cinq candidates, deux à huit.
Reproduit en ligne de commande : la génération rend **5 candidates sur 5 et 8
sur 8**, toutes entre −6 % et +9 % de la cible. Ce ne sont donc pas les boucles
qui manquent.

C'est le **contraste** qui les élimine, et le message le dit :

> soit elles empruntaient plus de 25 % des mêmes routes, **soit** l'une des
> trois ne se distinguait des deux autres sur aucun axe d'une marge
> perceptible. Ce jour-là, l'orientation au vent, les demi-tours, la durée, la
> ville, la pluie et le terrain sous les blocs valaient la même chose sur
> toutes : il ne restait que les nationales.

**Et chercher plus loin aggrave le résultat.** À cinq candidates, trois axes
distinguaient encore (durée, ville, nationales) ; à huit, un seul (les
nationales). Plus on génère, plus deux candidates finissent par se ressembler
— et un seul doublon dans un trio le disqualifie entièrement.

### La réponse du mainteneur

> « oui, et en fait le parcours lui-même est distinctif en soi. »

**Le recouvrement mesure déjà ça.** Deux boucles qui partagent moins de 25 %
de leurs routes vont à des endroits différents, et la carte le montre en une
seconde. L'exigence supplémentaire de se distinguer **sur un axe mesuré**
visait les *descriptions*, pas les tracés — et elle empêche aujourd'hui de
montrer trois routes franchement différentes sous prétexte qu'on ne sait pas
dire en une phrase ce qui les sépare.

**Décision : le recouvrement devient le seul verrou.** Trois boucles sous
`SEUIL_RECOUVREMENT` sont trois propositions. Chacune dit ce qu'elle a de
vrai, sans qu'on exige un écart minimal entre les phrases.

### Ce que ce renversement coûte, assumé

Au sprint 5, le mainteneur avait posé l'exigence inverse : *« trois
propositions ne servent à rien si elles se ressemblent, et les trois
premières d'un même classement se ressemblent souvent »*. C'est cette phrase
qui avait fait naître l'axe de marge perceptible.

Le risque accepté aujourd'hui : **parfois, trois propositions porteront
presque la même phrase**. Le mainteneur juge que la carte parle d'elle-même,
ce qu'elle ne faisait pas au sprint 5 — à l'époque, la page du jour n'avait
pas encore la géométrie des trois tracés en JSON (lot F0.1).

### Une piste qui ne coûte rien et qui manque

Le **dénivelé** n'est pas un axe de distinction aujourd'hui. Or 358 m sur
59,5 km et 700 m sur la même distance ne se ressemblent pas du tout à rouler.
Il est déjà mesuré et déjà affiché — il lui manque seulement d'entrer dans ce
qui distingue une proposition d'une autre.


### Ce que l'implémentation a trouvé — **17/09/2026**

**Livré.** `sortie.contraste` ne retient plus que le recouvrement. Vérifié sur
le cas exact de [[Q44]] — séance du 19/09, préférence « de travers », quatre
candidates, contre le vrai BRouter et le vrai Open-Meteo :

| | avant | après |
|---|---|---|
| candidates générées | 4 | 4 |
| recouvrement médian des candidates | 1,4 % | 1,4 % |
| **propositions servies** | **2** | **3** |

Les trois retenues se recouvrent de 0,55 %, 17,3 % et 2,1 % — toutes sous le
seuil. Une seule porte une phrase (« vous rentrez avec le vent dans le dos ») ;
les deux autres n'en portent aucune, et c'est le cas que le mainteneur a
accepté.

**Une chose à savoir sur ce que le seuil refuse maintenant qu'il est seul.**
La mesure de [[Q44]] donne **33,2 %** de recouvrement médian à la préférence
« rentrer avec le vent », cinq de ses six paires au-dessus de 25 %. Rien à
corriger dans le seuil : cette préférence n'ouvre **qu'un azimut**, et
`boucle.candidates.azimuts` élargit ce secteur sans jamais en ouvrir un
second — les quatre candidates sont quatre variantes à 30° d'écart, la famille
même que la mesure du 16/09 chiffre à 28 % et dont le mainteneur dit qu'elle
va au même endroit. Le seuil fait son travail en les refusant.

**Ce qui en découle, et qui n'est pas tranché** : sur « rentrer avec le vent »,
le produit rendra souvent deux propositions au lieu de trois, en le disant.
Si c'est gênant, le remède est du côté des **azimuts ouverts** — ouvrir un
second secteur comme « de travers » le fait déjà — et c'est une décision de
conception qui appartient au mainteneur, pas un réglage de seuil. Rien n'a été
changé là.

### Une piste toujours ouverte

Le **dénivelé** n'est pas un axe de distinction, et ne l'est toujours pas :
358 m sur 59,5 km et 700 m sur la même distance ne se ressemblent pas à
rouler. Il est déjà mesuré et déjà affiché. Depuis que l'axe ne conditionne
plus l'appartenance au trio, l'ajouter ne changerait plus le **nombre** de
propositions — seulement la richesse des phrases. C'est un lot à part.


## Q44 — Deux réglages de direction qui se contredisent, et le vent qu'on ne montre pas — **17/09/2026**

> « par contre, un truc sur la demande de direction avant le calcul : c'est
> bien, et en même temps, sans connaître le sens du vent dominant, c'est un
> choix arbitraire. »

**Vérifié, et c'est pire que ce que le mainteneur décrit.** L'écran de demande
(`front/src/ecrans/Demander.tsx`) pose **deux réglages qui veulent la même
chose** :

- « **Orientation au vent** » — rentrer avec, partir avec, de travers, peu
  importe. C'est l'idée du mainteneur du sprint 5 : poser la question **avant**
  la recherche plutôt que de contraster après coup, ce qui réduit aussi
  l'espace de recherche.
- « **Direction** » — N, NE, E, SE…

Les deux fixent l'azimut de recherche. Et **l'écran ne dit nulle part d'où
vient le vent**, alors que la maquette E16 le prévoyait explicitement — « Vent
de sud-ouest à 22 km/h demain matin » sous le sélecteur.

On demande donc une direction sans donner l'information qui permettrait de la
choisir, pendant qu'un réglage voisin prétend s'en occuper. **Arbitraire deux
fois.**

**À trancher** : les deux réglages coexistent-ils (et alors lequel gagne quand
ils se contredisent ?), ou l'orientation au vent remplace-t-elle la direction
brute ? Dans les deux cas, le vent du jour doit s'afficher à côté.

Note : la direction recommandée par la météo est déjà calculée et déjà
affichée (`meilleure_direction`, avec son motif). Ce n'est pas la même chose
que le vent — elle vise le sec, pas l'orientation.

### Réponse du mainteneur (17/09/2026) — deux modes, et le latéral ouvre deux directions

> « c'est un choix UX. Soit on est capable de montrer au user le sens du vent,
> soit on lui dit de choisir avec 3 propositions : vent dans le dos au départ,
> vent dans le dos au retour, ou vent latéral majoritaire — et ça fait le job.
> Et il peut choisir sa direction, ou en fonction du sens du vent ; s'il
> choisit le sens du vent, on lui demande ses préférences. La préférence vent
> latéral ouvre 2 directions opposées d'ailleurs. »

**La forme retenue.** Un premier choix : *je choisis ma direction* ou *je
choisis selon le vent*. Les deux réglages ne coexistent plus côte à côte —
l'un remplace l'autre, et la contradiction disparaît.

Si le cycliste choisit selon le vent, trois préférences :

| préférence | ce que ça fixe |
|---|---|
| vent dans le dos **au départ** | un azimut |
| vent dans le dos **au retour** | un azimut, l'opposé |
| vent **latéral** | **deux azimuts opposés** |

**Et montrer le vent n'est pas une alternative, c'est le complément.** Le
mainteneur pose « soit / soit », mais les deux modes en ont besoin : celui qui
choisit sa direction doit savoir d'où souffle le vent pour la choisir, et
celui qui choisit selon le vent doit pouvoir vérifier ce qu'on lui propose.
La maquette E16 le prévoyait — « Vent de sud-ouest à 22 km/h demain matin ».

### La trouvaille : le latéral produit le contraste maximal

**Deux azimuts opposés, c'est le recouvrement le plus faible possible.**
Mesuré le 16/09 sur des boucles de 60 km depuis chez le mainteneur : deux
directions séparées de 180° partagent **0,4 % de leurs routes** (médiane), contre
28 % à 30° d'écart.

Donc la préférence qui contraint le moins l'azimut est aussi celle qui produit
les propositions les plus différentes. C'est une réponse **par la conception**
à [[Q43]] et [[Q45]] : là où « rentrer avec le vent » impose un secteur et rend
trois boucles qui se ressemblent, « de travers » en ouvre deux opposés.

À vérifier à l'implémentation : les candidates doivent alors se répartir entre
les deux azimuts, pas s'entasser sur le premier.

### Ce que l'implémentation a trouvé — **17/09/2026**

**Le piège était réel, et le code portait déjà le commentaire qui l'écartait à
tort.** `vent_demande` disait : « pour le travers, viser à 90° — un seul des
deux côtés, le moteur explorera l'autre par ses azimuts voisins ». C'est faux.
`boucle.candidates.azimuts` balaie ±20°, ±40°, ±60°… autour d'un azimut : il
**élargit un secteur, il n'en ouvre jamais un second**, et n'atteint donc
jamais 180° d'écart. Garder un seul azimut aurait entassé toutes les
candidates d'un côté tout en annonçant deux directions.

La génération fait maintenant **un appel par azimut**, les candidates réparties
en parts aussi égales que possible.

**Vérifié contre le vrai BRouter et le vrai Open-Meteo**, séance du 19/09 à
15 h, vent 15,8 km/h de 235°, quatre candidates par préférence. Recouvrement
mesuré avec la métrique du produit (`recouvrement_max`, celle que borne
`SEUIL_RECOUVREMENT`), sur les six paires :

| préférence | azimuts ouverts | azimuts obtenus | médiane | min | max |
|---|---|---|---|---|---|
| rentrer avec (retour-dos) | 235° | 275, 235, 255, 215 | **33,2 %** | 13,9 % | 43,3 % |
| partir avec (depart-dos) | 55° | 55, 75, 95, 35 | **8,6 %** | 3,8 % | 46,4 % |
| de travers | 325° **et** 145° | 345, 165, 325, 145 | **1,4 %** | 0,4 % | 26,3 % |

**La répartition tient : deux candidates de chaque côté.** Et le détail du
travers reproduit exactement la mesure du 16/09 — les quatre paires qui
enjambent les deux azimuts valent 0,4 %, 0,4 %, 0,6 % et 2,1 %, tandis que les
deux paires restées du même côté (20° d'écart) valent 17,1 % et 26,3 %.

La conclusion du mainteneur est donc confirmée sur une génération réelle : la
préférence qui contraint le moins l'azimut produit les propositions les plus
différentes, d'un facteur ~24 sur la médiane par rapport à « rentrer avec ».
Et « rentrer avec » est bien le pire cas : cinq de ses six paires dépassent le
seuil de 25 %.

**Mais le gain n'arrive pas jusqu'au cycliste, et ce n'est pas le vent qui
bloque.** Sur cette même génération, les quatre candidates — dont quatre
paires à moins de 2,2 % de recouvrement — ont rendu **une seule proposition**.
Le motif rendu le dit :

> soit elles empruntaient plus de 25 % des mêmes routes qu'une autre du
> groupe ; soit l'une des trois ne se distinguait des deux autres sur aucun
> axe d'une marge perceptible. […] il ne restait que la durée pour les
> distinguer.

C'est **exactement l'exigence que [[Q43]] a retirée** le 17/09 (« le
recouvrement devient le seul verrou »), et qui n'est pas encore retirée du
code. Tant qu'elle y est, le travers produit bien deux familles de boucles
franchement différentes, et la sélection les jette parce qu'on ne sait pas
dire en une phrase ce qui les sépare. **La trouvaille de Q44 est donc livrée
mais neutralisée en aval par Q43 non implémentée** — les deux lots se tiennent,
et celui de Q43 conditionne le bénéfice visible de celui-ci.

### Resté ouvert : la sortie libre n'a pas de question du vent

Les deux moitiés de l'écran de demande ne tapent pas la même route. « Ma
séance » va sur `POST /sorties`, qui accepte `vent` comme `direction`. «
Endurance Z2 » va sur `POST /boucles`, dont `direction` est **obligatoire** et
qui **n'a aucun champ `vent`** : `boucle/commande.py` ne pose pas la question
du vent du tout.

Le premier choix de Q44 est donc entier sur une séance, et amputé sur une
sortie libre — « selon le vent » y est montré désactivé, avec sa raison, plutôt
que caché. Le vent, lui, s'affiche dans les deux cas.

**Question au mainteneur : faut-il porter la question du vent dans `boucle`
aussi ?** C'est un lot à part — un `--vent` sur `ourouler boucle`, la question
posée avant la génération, et `direction` qui devient facultative. Rien n'a été
décidé ici, et rien n'a été fait dans `boucle` : Q44 parlait de l'écran de
demande, pas de la commande `boucle`.

## Q45 — Quand rien ne distingue rien, le dire — **17/09/2026**

> « ben, s'il n'y a pas de pluie et peu de vent et que tout est plat, à un
> moment rien ne change. »

Généralisation de [[Q43]] par le mainteneur, et elle vaut mieux que le
correctif qu'on y proposait. Certains jours, **aucun axe ne peut distinguer
quoi que ce soit** : pas de pluie, donc pas de plus sèche ; peu de vent, donc
pas d'orientation qui compte ; terrain homogène, donc pas de plus roulante.

Chercher une différence dans ces conditions revient à en fabriquer une.

**Ce que le produit devrait faire** : le dire. « Aujourd'hui ces trois boucles
se valent — choisissez où vous voulez aller. » C'est une information honnête,
et c'est même une bonne nouvelle : rien ne contraint le choix.

C'est le pendant exact de ce que le produit sait déjà faire quand il ne trouve
qu'une proposition au lieu de trois — il le dit et explique pourquoi, au lieu
de servir trois boucles qui se ressemblent. Ici il s'agit de dire l'inverse :
**trois boucles différentes, et aucune raison de préférer l'une.**

### Livré le 17/09/2026, avec [[Q43]]

`contraste.Selection.motif_equivalence`, publié en JSON sous `motif_equivalence`,
affiché par la ligne de commande, par la page du jour et par l'écran des
propositions (sous le titre « Au choix », et non sous un avertissement : c'est
une bonne nouvelle).

Il ne sort que si **aucune** proposition ne porte de phrase : dès qu'une seule
se détache, dire « elles se valent » serait faux, et c'est sa phrase à elle qui
parle.

**Et il se mesure, comme le reste** (règle absolue 5). Deux formulations, parce
que deux situations différentes sont vraies :

- les axes sont **muets** — « la pluie, les demi-tours et le terrain sous les
  blocs valaient la même chose sur les trois » ;
- ils **varient sans vainqueur** — « les nationales varient un peu de l'une à
  l'autre, mais d'un écart trop petit pour se dire ».

Confondre les deux ferait affirmer que deux boucles roulent autant sur les
nationales alors qu'elles n'y roulent pas autant.


#### Réponse du mainteneur (17/09/2026) — **l'âge dégage**

« L'âge, si on s'en sert pas pour dériver une FC, on dégage. »

**Vérifié avant d'appliquer, et la condition n'est pas remplie** : la méthode
retenue en [[Q50]] pour le cycliste sans capteur **ne dérive aucune fréquence
cardiaque maximale**. Elle refuse justement les formules du type « 220 − âge »,
au motif qu'elles abondent et qu'aucune vérité terrain ne permet de les
départager ; elle se calibre sur les cyclistes qui portent puissance **et** FC,
et rapporte son erreur. Le code confirme : ni `age`, ni `fc_max`, ni cette
formule nulle part sous `src/ourouler/`.

**Conséquences.** Pas de champ âge, donc pas de stockage à inventer, donc
**l'étape « identité » disparaît de l'assistant** — les maquettes l'avaient
écartée exprès, elles avaient raison. `CHAMPS_MODIFIABLES` reste tel quel.
L'identité qui subsiste, l'adresse e-mail, vient du **compte** de L7.2 (lien
d'invitation, puis passkey) et non du profil : c'est cohérent avec le découpage
que [[Q35]] doit trancher, où l'e-mail appartient au compte, pas au TOML.

**Si un jour l'âge revient**, ce sera parce qu'un lot en aura un usage mesuré —
pas parce qu'un formulaire d'inscription trouve normal de le demander.

## Q46 — Ce que le service a le droit d'apprendre des sorties de chacun — **tranchée le 17/09/2026**

> « au cycliste ses données, au serveur une partie qu'on veut utiliser pour
> comprendre. »

Phrase du mainteneur en marge de [[Q35]], et **elle ouvre un sujet qui vit
déjà dans le code sans avoir été posé.**

### Ce qui existe déjà et qui deviendra collectif

`src/ourouler/apprentissage/routes.py` **apprend les poids des routes à partir
de ce qui a été réellement roulé**. Aujourd'hui sur les seules sorties du
mainteneur, dans son cache. Le jour où plusieurs cyclistes roulent, la
question se pose d'elle-même : **ce que l'un a roulé améliore-t-il le parcours
de l'autre ?**

La réponse évidente est oui — c'est même ce qui fait la valeur d'un service
partagé, et Komoot ne fait pas autre chose avec ses données de trajets
anonymisées. Mais ça n'a jamais été décidé.

### Ce que la doctrine promet déjà, et qui contraint

§10.2 : *« RGPD par construction : export de toutes ses données et suppression
du compte (profil, fichiers, calibrations, clés) disponibles dès la première
version hébergée ; pas de suivi d'audience ; hébergement en Europe. »*

**Supprimer un compte devient alors ambigu.** Les poids de routes qu'il a
contribué à apprendre ne sont plus « ses données » — ils sont fondus dans un
modèle partagé, et les en retirer demanderait de tout réapprendre sans lui.

### Le spectre, du plus personnel au plus mutualisable

| donnée | nature |
|---|---|
| calibration CdA/Crr | **strictement personnelle**, aucune valeur collective |
| clé Intervals, départ, FTP | **strictement personnelle** |
| poids de routes appris | **collectif par nature** — c'est la géographie, pas le cycliste |
| cache météo par maille et par heure | **collectif par construction** ([[Q42]]) |
| mesures d'usage (densité de marqueurs, classes de trafic, facteur terrain) | entre les deux — faites cette nuit sur l'historique du mainteneur |

Les deux extrémités sont claires. **C'est la ligne du milieu qui demande une
décision**, et elle en demande trois :

1. **Qu'est-ce qui remonte** — la trace brute, ou seulement des agrégats par
   tronçon de route ?
2. **Qu'est-ce qu'on en dit au cycliste**, et le choix est-il explicite ? Un
   service qui apprend de vous sans le dire n'est pas le même produit que
   celui qui le demande.
3. **Que devient la contribution à la suppression du compte ?** Les poids
   appris survivent-ils, et si oui, est-ce compatible avec ce que §10.2
   promet ?

**Le mainteneur le pose comme « un sujet à part », et il a raison** : ça ne
bloque aucun lot en cours, et ça décide de ce qu'est le produit une fois
partagé.


### Réponse du mainteneur (17/09/2026) — la ligne passe entre la route et le lien

> « en fait, c'est : qu'est-ce qu'on conserve du point de routes qui concerne
> directement le cycliste ? »

**Meilleure formulation que la question d'origine**, et elle sépare ce que la
table mélange. `apprentissage/routes.py`, table `troncons` :

| colonnes | de quoi ça parle |
|---|---|
| `cle_lat`, `cle_lon`, `highway`, `surface`, `maxspeed`, `cout_km` | **la route** — elle existe indépendamment de qui l'a roulée |
| `passages`, `metres` | **le fait d'y être passé** |
| `proprietaire`, et la table `sorties` (`id_sortie`, `jour`) | **le cycliste** |

**Ce qui concerne la route se partage sans difficulté** : une petite route
agréable l'est pour tout le monde, et ça n'appartient à personne. **Ce qui est
personnel, c'est le lien** — que *cette personne* y est passée, *ce jour-là*,
sur *cette sortie*.

Et ça résout la tension avec la doctrine §10.2 sans compromis : si l'agrégat
collectif ne porte jamais l'identité, **il n'y a rien de personnel à supprimer
dedans**. Supprimer un compte retire ses sorties et son lien aux tronçons ; le
savoir sur les routes reste, parce qu'il n'a jamais parlé de lui.

### Le seuil de réidentification, et pourquoi il attend

J'avais signalé qu'avec peu d'utilisateurs, **un tronçon parcouru une seule
fois désigne une seule personne** : un compteur « 1 passage » sur une route de
campagne se réattribue tout seul. L'anonymat par agrégation n'existe qu'à
partir d'un certain nombre de contributeurs.

> « tant que c'est des copains, que je ne vends pas le service, je
> préciserais. »

**Position retenue, et elle est cohérente** : ce n'est pas une machinerie
d'anonymisation qui protège dans ce cas, c'est le fait que le mainteneur
connaisse les gens et le leur dise. La transparence tient lieu de seuil tant
que le cercle est petit et le service gratuit.

**Ce qui fait revenir la question**, et il faut le savoir d'avance : le
service vendu, ou des inconnus dedans. L'une des deux suffit. Le seuil de
contributeurs distincts devra alors être **mesuré**, pas posé.

Note d'une autre nature, indépendante de la vie privée : un tronçon roulé une
seule fois n'est pas non plus une **preuve** qu'il est bon. Le seuil sert donc
deux choses à la fois — et cette seconde raison-là vaut déjà aujourd'hui.


## Q47 — Quatre arbitrages de clôture du 17/09/2026

### Q37 (c) — résolu, et je l'avais mal lu

> « actuellement l'IHM demande bien une durée, c'est vérifié. »

**Exact.** `front/src/ecrans/Demander.tsx` envoie une **durée**, aucune
distance ; `kmDepuisKm` n'est qu'un formateur d'affichage, et la conversion se
fait côté serveur avec le modèle physique. Je listais cette question comme
ouverte alors qu'elle était close depuis le lot F2.

### Le frottement en Z2 — ce n'était pas un choix, c'est une incohérence

> « comment, avec séance, permet de choisir un azimut ? »

La question a levé ce que je m'apprêtais à faire arbitrer. **Deux chemins,
deux règles :**

- `sortie` (avec séance) : aucune direction nécessaire, le moteur **balaie les
  huit directions** si rien n'est demandé.
- `boucle` (sortie libre) : « `--direction N|NE|…|NO` ou un azimut en degrés
  est **obligatoire** » (`boucle/commande.py:377`).

Le bouton grisé en Z2 n'est donc pas une décision de conception mais une
contrainte héritée d'une commande qui n'a jamais appris à balayer. **Rien à
arbitrer : `boucle` doit se comporter comme `sortie`.**

### Q31 — informatif, et ça attend des vrais Franciliens

> « c'est informatif, donc pour l'instant on attend d'avoir des gens
> d'Île-de-France, on traitera après. »

La distance de dégagement urbain reste ouverte, sans travail engagé. Elle ne
sert qu'à quelqu'un dont la ville ne se dégage pas — et il n'y en a pas
encore. Même raison pour la question de la géographie, qui est la même prise
par l'autre bout.

### Q32 — après la V2

> « on voit après V2. »

Le mode circuit attend. Il dépend de [[Q31]], qui attend les mêmes gens.

### Q3 — close : des seuils existent, la personnalisation est en V2

> « on a déjà des seuils, non ? On n'a pas dit V2 pour permettre aux gens de
> personnaliser ? »

**Oui aux deux.** Les seuils de tenue existent et fonctionnent ; ce que la V2
apporte est le droit pour chacun de les déplacer. C'est exactement ce que
[[Q35]] a tranché pour `[tenue]` : valeurs par défaut en V1, édition des
seuils en V2. Q3 n'avait donc plus de question depuis ce matin.


### Q6 — clôture du 17/09/2026

L'identifiant d'athlète Intervals est retiré du dépôt (`docs/sprint1_relecture.md`),
et il vit désormais côté profil de l'utilisateur, conformément à [[Q35]].

**Ce que la vérification a établi, et qui change la gravité :**

| | fichiers suivis | historique git |
|---|---|---|
| identifiant d'athlète (7 caractères) | 0 | **4 commits** |
| clé d'API (25 caractères) | 0 | **0** |

**La clé n'a jamais touché le dépôt**, à aucun moment de son histoire. La
règle absolue 1 a tenu sur ce qui comptait.

Et un identifiant d'athlète **n'est pas un secret** : il désigne un profil
Intervals, il ne donne accès à rien. Sans la clé, on ne peut ni lire les
sorties ni écrire quoi que ce soit — c'est de l'ordre d'un nom d'utilisateur.

**Décision du mainteneur** : « ok, pas très grave ». L'historique n'est pas
réécrit — le faire changerait tous les sha du dépôt pour retirer une donnée
publique.

**Ce qui reste, et qui n'est pas un secret non plus** : la masse, la FTP et
« centre de Rennes » figurent dans cinq documents, dont `docs/cadrage.md`.
Décision du 13/09 maintenue — « seuls les identifiants Intervals sont à
purger, pas les chiffres ». Séparément ces chiffres ne disent rien ;
ensemble, ils décrivent quelqu'un. Signalé, assumé.
## Q48 — Importer son historique : par où, et ce qu'on en garde — **17/09/2026**

Point de départ : les API des plateformes se ferment. Strava a durci sa
politique au 1ᵉʳ juin 2026 — cache de sept jours, interdiction du *bulk
export*, interdiction d'entraîner un modèle, interdiction de facturer, et une
clause qui vise nommément le consentement de l'utilisateur (« even if a user of
your Developer Application consents »). Garmin a gelé les nouvelles
candidatures à son programme développeur vers septembre 2026, quelques mois
après que Strava l'a poursuivi. Suunto n'ouvre pas son API à l'usage personnel.
COROS demande une base d'utilisateurs établie. Wahoo reste la seule ouverte en
libre-service.

**Ce qui ne se ferme pas, c'est le fichier.** L'archive d'export appartient à
l'athlète (portabilité, RGPD article 20), et l'aveu est écrit noir sur blanc
dans l'interface d'Intervals.icu : *« Ces données ne sont pas soumises aux
conditions d'utilisation de l'API. »*

### Décisions du mainteneur (17/09/2026)

- **V1 couvre Strava et Garmin**, et rien d'autre : ce sont les deux qu'il peut
  vérifier lui-même, captures et import réel à l'appui (règle absolue 4).
- **Pas de ligne de commande pour les utilisateurs** — « les gens n'auront pas
  de CLI ». Le dépôt se fait sur le serveur. La CLI reste néanmoins le moteur
  qu'appelle la route, et le moyen de vérifier sur les vraies données.
- **On jette le brut, on garde le dérivé.** Les mailles de ~30 m avec leurs
  tags OSM et leurs kilomètres roulés, plus les coefficients de calibration,
  tiennent dans quelques kilo-octets ; les traces, elles, sont des données de
  localisation. Quand l'algorithme change, la personne redépose son archive.
  Écarté explicitement : garder le brut pour lui permettre de revoir ses
  sorties — *« mais on devient un Strava bis »*.

### Ce que l'import apporte, et qui n'est pas ce qu'on croit

Distinction du mainteneur, et elle découpe le travail :

> l'import permet de comprendre les routes, la puissance permet de comprendre
> le niveau — c'est 2 choses

| | a besoin de | couvre |
|---|---|---|
| **Routes** | GPS seul | tout le monde |
| **Niveau** | puissance | les porteurs de capteur |

L'import a donc une valeur immédiate et **universelle** même sans capteur : un
cycliste sans watts obtient déjà des itinéraires qui lui ressemblent.

### Le lien plutôt que le téléversement

Repris d'Intervals.icu : on ne fait pas traverser une archive de plusieurs
centaines de mégaoctets à un navigateur. La personne colle **le lien** que la
plateforme lui a envoyé par courriel, et le serveur va chercher l'archive.
Le téléversement reste en secours, pour qui a déjà le fichier sur son disque.

Trois conséquences qui se conçoivent dès le départ, pas après :

1. **Le lien est un secret.** Une URL d'export est pré-signée : quiconque la
   détient télécharge toute l'archive. Jamais journalisée, jamais en paramètre
   d'URL, jamais conservée après usage. Et elle expire — sept jours côté Strava.
2. **C'est une porte ouverte sur le serveur.** Une URL arbitraire que le serveur
   va chercher, c'est le vecteur SSRF classique : `169.254.169.254` et le
   conteneur récite ses identifiants d'hébergement. Liste blanche de domaines,
   refus des plages privées après résolution DNS, aucune redirection hors
   domaine, plafond de taille et de durée.
3. **Garmin met plusieurs jours** là où Strava met des heures. Le parcours ne
   tient donc pas en une session : état persistant, et notification au retour.

### Le mode aperçu, déjà écrit

L'interface d'Intervals dit : *« Si vous ne cochez pas l'une des cases, rien ne
sera fait et vous pourrez revoir ce qui a été trouvé. »* On lit l'archive, on
montre ce qu'elle contient, la personne décide ensuite.

La sonde écrite le 17/09 est déjà cet écran : structure de l'archive, extensions
rencontrées, part de fichiers gzippés, taux de lecture, et couverture réelle
(GPS, puissance, cadence, FC, température, altitude). Il lui manque une interface,
pas un moteur.

### Ce qui existe déjà dans le dépôt, et qu'il ne faut pas réécrire

- `activites/lecture.py` lit FIT, GPX et TCX, depuis un chemin **ou des octets**,
  avec les pièges Garmin couverts : repli `enhanced_altitude`/`enhanced_speed`,
  et sessions multiples cumulées avec avertissement. La richesse Garmin restante
  (laps, événements, champs développeur Connect IQ) vit dans des messages que le
  lecteur ignore sans s'y casser les dents.
- `activites/cache.py` → `indexer_dossier()` : parcours récursif, déduplication
  par `(source, id_externe)` et SHA-256, et **un fichier abîmé ne fait pas
  échouer l'import**.

**Le seul angle mort mesuré** : les archives sont des `.zip`, et Strava gzippe
ses fichiers à l'intérieur. `indexer_dossier` filtre sur l'extension et passera
à côté des `.gz`.

### Découpe proposée

- **L1 — le dépôt** : route serveur, lien ou téléversement, décompression
  (`.gz` compris), aperçu, extraction vers le dérivé, brut jeté, isolation par
  propriétaire. Critère : l'export Garmin réel du mainteneur monte, et le
  rapport dit combien lues, combien échouées, quelle couverture.
- **L2 — le guide** : `docs/`, Garmin et Strava seulement, avec les captures du
  mainteneur. Où demander son archive :
  - Strava — <https://www.strava.com/athlete/download_my_account>
  - Garmin — <https://www.garmin.com/en-US/account/datamanagement/>
  - Polar, pour mémoire — <https://support.polar.com/fr/how-to-download-all-your-data-from-polar-flow>

  **Chez Strava il y a deux pages, et le guide doit envoyer sur la bonne.**
  Précision du mainteneur, qui les a vues connecté : l'une propose le
  téléchargement **et** la suppression du compte, l'autre ne propose que le
  téléchargement. C'est la seconde qui est donnée ci-dessus, et c'est la seule
  à mettre dans le guide — la première fait refermer l'onglet à qui croit être
  sur le point de supprimer son compte. Intervals.icu doit d'ailleurs écrire
  « Vous n'avez pas besoin de supprimer votre compte ! », signe que la confusion
  arrive pour de bon.

  Les intitulés exacts des deux pages ne sont pas vérifiés d'ici : elles
  demandent une session connectée. À relever en capture au moment d'écrire le
  guide.
- **L3 — l'estimation de puissance sans capteur** : lot séparé, voir [[Q49]].

### Le parcours est générique — ce qui change la découpe

Constaté sur trois captures d'Intervals.icu (Strava, Garmin, Polar) : **le
parcours est rigoureusement le même**. Demander ses données à la plateforme,
attendre le courriel, clic droit sur le bouton, copier le lien, coller.

Donc une **seule** route de dépôt, et par plateforme un simple descriptif :

1. le **domaine autorisé** (la liste blanche du point 2 ci-dessus) ;
2. la **durée de validité du lien** — sept jours chez Strava, **deux semaines**
   chez Polar, inconnue chez Garmin — pour dire « ton lien a expiré, redemande
   une archive » plutôt que de rendre une erreur réseau ;
3. l'**agencement interne** de l'archive, seul point qui demande un adaptateur ;
4. le lien vers la notice de la plateforme, pour le guide.

**Conséquence** : « V1 = Strava et Garmin » est une limite de **vérification**
(règle absolue 4 — le mainteneur n'atteste que ce qu'il a fait tourner), pas une
limite d'architecture. Ajouter Polar, COROS ou Suunto ensuite ne coûte qu'un
descriptif, à condition que le point 3 tienne.

**Réserve à lever avant de le promettre** : la notice de Polar ne dit pas dans
quels formats elle exporte, et elle précise exclure les données dérivées de ses
algorithmes. Si l'archive Polar contient du JSON propriétaire plutôt que des
FIT, GPX ou TCX, `activites/lecture.py` ne la couvre pas et Polar devient un lot
à part entière, pas un descriptif. À mesurer sur une archive réelle, jamais à
supposer.

### Reste à trancher

Où ça atterrit : sprint suivant, ou lot isolé. Un sprint figé ne s'élargit pas
en cours de route.


## Q49 — Estimer la puissance sans capteur, et ce que ça vaut — **17/09/2026**

> en fait si j'ai le terrain la vitesse le poids et la FC, une météo, je
> commence à avoir pas mal d'info pour estimer vaguement une puissance pas trop
> dégueu

Et la précision attendue, qui change tout :

> nous la puissance on s'en sert pour dériver la vitesse sur les blocs, pas pour
> calibrer une puissance parfaite

On ne cherche donc pas un FTP exact, mais une estimation assez bonne pour
dimensionner la durée d'un bloc.

### Ce n'est pas un développement, c'est une mesure

Tout l'outillage existe : `physique/modele.py` → `puissance_requise(v, pente,
vent_face, Parametres)` est l'inversion exacte ; `physique/calibration.py` sait
découper en tronçons de 200 m avec pente, vent d'archive et densité de l'air,
ajuster CdA et Crr aux moindres carrés avec leurs incertitudes, repérer les
sorties en groupe, et valider sur des sorties jamais vues.

### Le piège, nommé avant de mesurer

Avant son Van Rysel RCR (carbone, fin 2023), le mainteneur a roulé un
Specialized qui est un **VTC** (lourd, peu roulant) et un **Van Rysel route en
alu** (jantes fines, non aéro).

Une estimation **aveugle au vélo** rendra mécaniquement une puissance basse sur
le VTC, qui monte à chaque changement de vélo. C'est un **artefact**, pas un
progrès du cycliste — d'autant que la mesure du 16/09 (docstring de
`calibration.py`) montre que sur ses deux vélos actuels, tout l'écart part dans
le Crr et non dans le CdA.

L'hypothèse du mainteneur est précisément que « c'est le vélo qui a changé, pas
le bonhomme ». Elle se lit dans les deux sens, et on ne tranche pas à sa place :
la manip produit **deux séries**, aveugle au vélo et consciente du vélo, et
c'est **l'écart entre les deux** qui est le résultat.

### Méthode : le verrou d'abord, et en aveugle

1. **Valider là où la vérité existe.** Sur des sorties **qui ont** la puissance,
   estimer depuis la seule vitesse + pente + vent + masse, et comparer au
   mesuré. Biais et dispersion, à l'échelle de la sortie et du tronçon de 200 m.
   Si l'erreur est telle que l'estimation ne vaut rien, le dire et s'arrêter :
   c'est une réponse valide (règles absolues 4 et 5).
2. **La masse est datée**, pas constante : le poids varie sur plusieurs années
   et entre linéairement dans les termes de roulement et de gravité. Intervals
   tient cet historique, et l'import Garmin le propose en case séparée.
3. **En aveugle du FTP connu** : l'estimation est figée dans un fichier horodaté
   avant toute consultation des valeurs de référence.
4. **La FC ne rentre pas dans le bilan de puissance**, qui est physique. Elle
   peut servir à repérer les sorties où la physique se trompe — aspiration en
   peloton, arrêts prolongés.

### Le FTP, et son biais

Sur des sorties d'endurance sans effort maximal, un FTP dérivé d'un
meilleur-20-minutes **sous-estime**, et d'autant plus que la période contient
moins d'efforts francs. La série ancienne est probablement dans ce cas : à lire
comme une série avec sa bande d'incertitude, jamais comme un chiffre.

### Lancé le 17/09/2026

Agent en aveugle, worktree isolé, sur les données Intervals. En attente.

### Ce qui manquera probablement

La **masse** et la **période d'usage** du Specialized et du Van Rysel alu : ils
ne sont pas dans la configuration, dont l'historique démarre au 1ᵉʳ décembre
2023 (règle absolue 6). À défaut, le résultat sort en fourchettes, avec une
analyse de sensibilité.


## Q50 — Déduire une zone 2 de la fréquence cardiaque, pour les cyclistes sans capteur — **17/09/2026, lot séparé**

> on va devoir gérer le cas sans capteur de puissance et vaguement en déduire
> la Z2 des gens sur leur FC — c'est un sujet à part entière

**Le piège** : les formules de zones cardiaques abondent, mais pour les gens
sans capteur on n'a **aucune vérité terrain** pour vérifier qu'on ne raconte pas
n'importe quoi — et la règle absolue 5 interdit d'affirmer sans mesure.

**La sortie** est dans les données du mainteneur : ses sorties portent puissance
**et** FC ensemble. La méthode se calibre sur les cyclistes qui ont les deux,
son erreur se rapporte, et elle s'applique aux autres **en affichant cette
erreur**. Ça fait du sujet un lot mesurable au lieu d'un vœu.

### La FC n'entre pas dans la physique — elle étiquette la zone

Distinction posée le 17/09, après une première formulation trop raide de ma
part. Le bilan de puissance reste **purement physique** : vitesse, pente, vent,
masse, densité de l'air. Rien de cardiaque dedans.

La FC sert d'**étiquette** : la physique dit *combien de watts*, la FC dit *dans
quelle zone la personne était*. Le croisement répond à la question qui compte
vraiment pour un cycliste sans capteur — **quelle puissance produit-il quand il
roule en Z2 ?** — et cette question-là n'a pas besoin d'une FTP pour être
posée.

### Trois façons d'obtenir la bande Z2, de la pire à la meilleure

1. **220 − âge → FCmax → pourcentage.** Universelle et gratuite : c'est la seule
   information disponible pour un inconnu. Et c'est le maillon faible de toute
   la chaîne — l'écart de la formule est large. À **mesurer** sur le mainteneur
   plutôt qu'à citer, puisqu'il a la FC et le capteur.
2. **La demander à la personne.** Proposition du mainteneur : beaucoup de
   cyclistes d'endurance connaissent leur plage cardiaque de Z2. Un champ de
   deux nombres remplace le maillon le plus faible par une donnée directe.
3. **La dériver de ses propres données**, ce qui suppose un capteur — donc
   circulaire pour la population visée, et hors de portée ici.

**Ce qui doit être mesuré avant de trancher** : laquelle des deux erreurs
domine, celle de la physique ou celle de l'étiquetage. Si l'étiquetage par
l'âge coûte plus cher que tout le modèle physique, raffiner la physique ne sert
à rien tant que la zone est posée à la louche — et le champ à deux nombres
devient le lot, pas le modèle.

**Un quatrième point de comparaison existe**, et il est gratuit : l'écart entre
la bande que le mainteneur **déclare** de mémoire et celle que ses propres
données montrent. Il dit ce que vaut la source 2 en pratique. Sa valeur
déclarée n'est pas consignée ici (règle absolue 1) et n'a pas été transmise à
l'agent pendant sa campagne en aveugle — elle sert de vérité terrain à la
levée.

### Ce qui peut salir l'étiquette

- **dérive cardiaque** : à puissance constante la FC monte au fil d'une longue
  sortie, et la même intensité change de zone en seconde moitié ;
- **chaleur** : une Z2 de juillet et une Z2 de février n'ont pas la même FC.
  Mesuré par ailleurs — sur le même vélo, l'hiver coûte +16,6 W à 30 km/h ;
- **sorties en groupe** : W/bpm mesuré à +19 % en club contre +3 % ailleurs.
  Le croisement devrait les faire ressortir seul, ce qui en fait un bon
  contrôle de cohérence de tout l'édifice.

Lot séparé, après [[Q49]].


## Q51 — Ce que la mesure a trouvé sur [[Q49]] et [[Q50]] — **17/09/2026**

Campagne en aveugle sur les données réelles, deux gels horodatés en lecture
seule, comparaison après coup. Les chiffres qui suivent sont mesurés, pas
supposés.

### Le recadrage du mainteneur, qui change le critère d'acceptation

> on ne cherche pas une perfection […] on va s'en servir pour lui donner une
> « vitesse ». Donc c'est refaire un étalonnage pour obtenir une échelle de
> « vitesse ».

La puissance n'est **jamais le livrable**. C'est un intermédiaire vers une
vitesse, donc vers une durée de boucle. Tout le budget d'erreur se juge dans
cette unité-là.

### Le cube sauve le produit

La chaîne complète — FC → zone → tronçons → physique → watts — tient à
**15,5 W de MAE**, soit 10,3 % de la puissance. Convertie par
`vitesse_regime` à l'allure d'endurance mesurée (151 W, 27,7 km/h) : **1,56
km/h, soit 5,6 %**. Le terme aérodynamique divise l'erreur relative par près
de trois, et d'autant mieux que l'allure monte.

Sur douze vraies traces (50 km, ~116 min simulées, vent d'archive du jour) :

| | minutes sur 2 h |
|---|---|
| chaîne complète sans capteur | **−6,8 / +8,3** |
| après étalonnage (voir plus bas) | ≈ 5, sans biais |
| **confondant de saison** | **14,1** |
| **tolérance déjà encaissée et déjà reprochée au tri** | **29 à 43** |

**L'absence de capteur coûte 16 à 28 % de ce que le produit absorbe déjà.**
Le lot est nettement moins risqué qu'il n'en avait l'air.

### La saison coûte le double, et les deux tiers sont gratuits

14,1 min contre 7-8 : c'est **elle** le vrai sujet. Décomposée :

- **9,3 min** parce que le cycliste appuie moins l'hiver (168 W l'été contre
  147 W en Z2). Ce n'est pas une erreur de modèle, c'est un fait — une
  **fenêtre glissante** sur la puissance d'endurance le capte sans une ligne
  de code ;
- **4,8 min** de vêtements (ΔCdA = 0,046 m²), qui demandent du code — un CdA
  par saison ou par température, que la calibration sait déjà séparer.

**Ordre de priorité qui en découle** : fenêtre glissante (gratuit, 9 min) →
CdA saisonnier (du code, 5 min) → estimation sans capteur (7-8 min, déjà
acceptable).

### Demander la plage de Z2 cardiaque : mesuré, et ça dégrade

Proposition du mainteneur, testée contre ses propres données :

| étiquetage | MAE |
|---|---|
| `220 − âge`, **aucune question posée** | **15,5 W** |
| ses réglages | 17,4 W |
| **sa réponse donnée de mémoire** | **18,7 W** |

Sa réponse de mémoire et ses réglages ne diffèrent que de 2,25 W : **la
question ne rapporte pas une mesure, elle rapporte ses réglages** — lesquels
décrivent une zone cardiaque qui ne coïncide pas avec sa zone de puissance
(10 W d'écart).

La recommandation « demander une borne de zone connue » est donc **retirée**.
Prudence : n = 1. Ce qui reste solide n'est pas « ne jamais demander une
zone », c'est **une plage de FC déclarée n'est pas une donnée fiable, et le
produit n'a aucun moyen de savoir d'où elle sort**.

Autre piège mesuré, contre-intuitif : `220 − âge` fait mieux que la **FCmax
réellement observée** (11,5 contre 17,9 W). FCmax observée 185, formule 171,
mais la Z2 réelle vaut 62-71 % de FCmax là où la convention dit 65-75 % — les
deux erreurs s'annulent. Chez quelqu'un dont la FCmax est *sous* la formule,
elles s'additionneraient. **Corriger la FCmax sans recalibrer la bande aggrave
l'estimation.**

### La question qui marche porte sur la vitesse, pas sur le cœur

> **« Sur une sortie tranquille au plat, tu tournes à combien de moyenne ? »**

Un facteur multiplicatif unique, étalonné sur les 41 sorties les plus
anciennes et testé **hors échantillon** sur les 63 suivantes :

| | biais | MAE | RMSE |
|---|---|---|---|
| sans étalonnage | +12,5 W | 16,5 W | 19,5 W |
| **avec** | **+1,1 W** | **11,5 W** | **14,1 W** |

Un seul nombre supprime le biais et réduit la MAE de 30 %, jusqu'au plancher
de la physique seule. Il ne fixe que le **niveau** : la dispersion restante
(σ 2,4 km/h) est le vent, le relief et la forme du jour — ce que la physique
sait rendre et qu'une moyenne ne saurait pas.

Et **le même réglage s'obtient de trois façons** : on le demande, il s'apprend
seul dès une dizaine de sorties importées, ou il se corrige quand l'utilisateur
rectifie une durée proposée. Un seul réglage, trois chemins — c'est exactement
le « le user peut changer » du mainteneur.

### L'angle mort structurel sur la capacité

Aucune des 22 fenêtres glissantes ne contient d'effort maximal : intensité
médiane 74, maximum 89 sur 139 sorties extérieures. Les quatre seuls efforts
maximaux depuis novembre 2023 sont **tous au home-trainer**, et l'estimateur ne
lit que l'extérieur. **Il ne peut structurellement jamais voir un effort
maximal de ce mainteneur.** Le rapport produit/capacité sort stable (80,6 %,
étendue 75-84 %) mais c'est une constante d'**habitude**, pas de physiologie :
appliquée, elle déduit deux capacités au-dessus du meilleur 20 min de toujours.

Ce qui confirme la conclusion de [[Q50]] : pour l'usage d'ourouler, la
grandeur utile est la **puissance habituellement produite**, pas la capacité.

### Trois valeurs de seuil qui semblaient se contredire, démêlées

Par l'historique daté du réglage : **258 W** = test du 27/10/2025 réglé le
06/11 ; **235 W** = réglé le **16/09/2026, la veille de l'étude**, à la reprise
après deux mois d'arrêt et sans test en 2026 ; **207-211 W** = seuil estimé
d'un trimestre sans effort maximal, donc un plancher. Trois grandeurs, pas un
désaccord.

### Deux défauts du dépôt trouvés en chemin, à instruire

1. **`masse_totale_kg` rend 100 kg** alors que la masse réelle sur la fenêtre
   de calibration était de 93-95 kg : 5 à 9 W d'erreur systématique, **qui
   dérive** (le poids a varié de 13,5 kg sur la période). La constante de la
   configuration est le poids d'aujourd'hui appliqué à hier. Le dépôt n'a aucun
   code de poids corporel — attention, `ourouler routes poids` concerne les
   **classes de routes**, pas le cycliste.
2. **`calibration.json` annonce un CdA et un Crr sans `bornes_atteintes`** qui
   sont physiquement impossibles à cette masse ; avec la masse datée,
   l'ajustement part en butée. Si cela se confirme, la mesure du 16/09 citée
   dans la docstring de `calibration.py` — « le même CdA à 0,7 % près sur les
   deux vélos, tout l'écart dans le Crr » — décrit une **dégénérescence de
   l'ajustement**, pas une propriété des vélos. **À vérifier avant de toucher à
   la docstring** : c'est une mesure documentée qu'on contredirait.
3. **Neuf TCX refusés au chargement** : « XML or text declaration not at start
   of entity: line 1, column 10 », probable BOM en tête de fichier. Défaut réel
   de `activites/lecture.py`, et il touche directement le lot d'import de
   [[Q48]].

### Deux réserves de méthode, déclarées

- L'agent a interrogé les **archives personnelles du mainteneur** sans accord
  explicite, et l'a signalé lui-même. Les seuls résultats exploités sont des
  reçus d'achat de vélo, qui ont fourni la datation indépendante manquante.
  Outil interdit depuis, en attente d'arbitrage.
- Au second gel, l'agent avait **déjà lu** le seuil et la FCmax réglés à
  l'étape précédente. L'atténuation est que l'estimateur n'utilise que
  `220 − âge` et une bande fixée d'avance. À garder en tête en lisant les
  11,5 W d'erreur d'étiquetage.

### Reste à trancher

- ~~L'usage d'`archives-perso` par un agent~~ — **autorisé** (17/09). Le
  mainteneur ne voyait pas le problème ; l'alerte venait de ce qu'un agent
  élargissait seul son périmètre de données, vers une source qui contient bien
  plus que ce que la tâche demandait, et que l'outil lui-même pose
  `inclure_perso` en garde-fou. Décision prise, et elle a payé : c'est de là
  qu'est sortie la datation indépendante des vélos.
- L'ordre de priorité ci-dessus vaut-il un lot, et lequel d'abord ?
- Les deux défauts de calibration : lot de correction, ou instruction d'abord ?
  (Explicités le 17/09 — voir ci-dessous.)

### Les deux défauts, expliqués

**1. La masse est celle d'aujourd'hui, appliquée à hier.** `masse_totale_kg`
lit **une seule** valeur de poids dans la configuration, la même pour toutes les
sorties quelle que soit leur date. Le poids du mainteneur a varié de 13,5 kg sur
la période : estimer une sortie de 2021 avec le poids de 2026 lui ajoute treize
kilos. La masse entrant linéairement dans le roulement et la gravité, l'erreur
**grandit à mesure qu'on remonte le temps** (+2,7 à +9,3 W selon l'année).
Correction simple : dater le poids, la série existe côté Intervals.

**2. La calibration ne peut pas séparer ce qu'elle prétend séparer.** Deux
résistances freinent : le roulement, force `Crr × masse × g`, à peu près
constante ; l'aéro, `½ ρ CdA v²`, qui grandit comme le carré de la vitesse. Les
distinguer demande des sorties à des vitesses **franchement différentes** —
c'est l'écart entre les deux courbes qui les identifie. Or l'endurance vit dans
une bande étroite (25-30 km/h), où les deux termes sont presque proportionnels :
l'ajustement peut **échanger** l'un contre l'autre sans que l'erreur bouge.

Les valeurs trouvées le disent : **CdA 0,222** est une valeur de contre-la-montre
pour quelqu'un aux cocottes, **Crr 0,0106** une valeur de VTT sur chemin. Aucune
n'est crédible seule ; ensemble elles reproduisent bien la résistance observée.
L'ajustement a glissé le long d'une vallée au lieu de tomber dans un puits.

**Les deux défauts se tiennent** : le roulement n'apparaît jamais que comme le
**produit** `Crr × masse`. Une erreur de masse part donc mécaniquement dans le
Crr — d'où l'ajustement qui file en butée dès qu'on corrige le poids.

**Ce que ça compromet** : la phrase de la docstring de `calibration.py` (16/09)
— « le même CdA à 0,7 % près sur les deux vélos, tout l'écart dans le Crr ».
Lue comme un fait physique elle est troublante ; lue comme une dégénérescence,
elle ne dit plus rien : quand l'ajustement peut échanger les deux, le CdA se
pose où le bruit le laisse. **Test avant de toucher à la docstring** : refaire
l'ajustement en fixant le CdA à plusieurs valeurs plausibles. Si l'erreur est
plate sur une large plage, c'est dégénéré.

**Ce que ça n'empêche pas.** Pour prédire une vitesse **dans la bande où la
personne roule**, rien : c'est la résistance **totale** qui compte, et elle est
juste — d'où les 12 W de la validation. Ça ne compte qu'à deux endroits : hors
de la bande (descente rapide, bosse lente), où les deux termes se séparent enfin
et où un mauvais partage donne une mauvaise vitesse ; et pour **comparer des
vélos**, usage explicitement mis hors périmètre par le mainteneur. L'usage
dangereux est donc déjà interdit.


## Q52 — Un seul réglage, deux visages, et le produit qui en découle — **17/09/2026**

Énoncé du mainteneur, qui referme [[Q49]], [[Q50]] et [[Q51]] :

> à partir de l'apprentissage, pouvoir dire à une personne « voici vaguement ta
> zone 2, es-tu d'accord ? » et tu peux ajuster — tu touches la puissance ou la
> vitesse sur le plat, et pour t'aider à jauger il y a ta vitesse moyenne de
> sortie. Les gens ajustent, et nous ça nous permet d'avoir un produit qui
> stocke un modèle de puissance, donc une dérivée de vitesse, donc on peut faire
> nos itinéraires avec ou sans bloc.

### Ce que ça résout

**La question cardiaque disparaît.** [[Q51]] a mesuré que demander une plage de
Z2 cardiaque *dégrade* l'estimation, parce que la réponse rapporte des réglages
et non une mesure. Ce design n'en demande aucune : il montre une vitesse et
laisse corriger. La contradiction se dissout au lieu d'être arbitrée.

### Les deux poignées existent déjà, et sont inverses

`puissance_a_plat_w(vitesse_kmh, p)` et `vitesse_a_plat_kmh(puissance_w, p)`
(`physique/modele.py`). C'est **le même nombre dans deux unités** : le porteur
de capteur touche des watts, celui qui n'en a pas touche des km/h, et le produit
stocke une seule grandeur.

Ce réglage unique est le facteur multiplicatif mesuré en [[Q51]] : hors
échantillon, il ramène le biais de +12,5 W à +1,1 W et la MAE de 30 %, jusqu'au
plancher de la physique. Il fixe le **niveau** de la courbe ; la physique rend
le reste — vent, relief, saison.

### Le piège à ne pas laisser passer

**La vitesse moyenne de sortie n'est pas la vitesse à plat en endurance.** La
première contient les côtes, le vent, les arrêts, la ville ; la seconde est un
régime. Les confondre ferait régler le modèle sur une grandeur plus basse que
celle qu'on croit toucher.

Mesuré chez le mainteneur : médiane en Z2 **27,0 km/h**, mais écart-type 2,4
km/h et étendue **22,2 à 31,5 km/h** d'une sortie à l'autre — et cette
dispersion est précisément ce que la physique explique.

Donc, dans l'écran : la moyenne de sortie est une **aide à jauger**, affichée
comme telle, jamais la valeur préremplie. Ce qu'on règle se nomme et s'affiche
comme « à plat, sans vent, en endurance ».

### Avec ou sans bloc, le même réglage suffit

Un facteur multiplicatif **met la courbe entière à l'échelle**. Une sortie libre
n'a besoin que du point d'endurance ; une séance à blocs a besoin de plusieurs
intensités — mais toutes se déduisent du même facteur. Un seul nombre stocké,
les deux usages servis.

### Trois chemins vers le même nombre

1. **On le demande** — « sur une sortie tranquille au plat, tu tournes à combien
   de moyenne ? ». Un cycliste sait répondre ; il ne sait pas donner son CdA.
2. **Il s'apprend seul** dès une dizaine de sorties importées ([[Q48]]).
3. **Il se corrige** quand la personne rectifie une durée proposée.

Le troisième est le plus précieux : il transforme chaque désaccord de
l'utilisateur en donnée d'étalonnage, sans lui demander de comprendre ce qu'il
règle.

### Ce que ça implique pour le découpage

L'estimation sans capteur cesse d'être un lot à part : elle devient la **valeur
initiale** d'un réglage que l'utilisateur possède. Le lot n'est donc pas « bien
estimer », c'est **« proposer, montrer, laisser corriger, et apprendre de la
correction »**. La qualité de l'estimation initiale décide seulement de combien
de personnes n'auront jamais besoin d'y toucher.

### Les deux chemins vers le tableau, et ce qui les menace

Objectif, dans les mots du mainteneur : **un tableau de puissance par zone,
dont la physique dérive une vitesse par zone** — donc une durée de bloc, donc
un itinéraire. Le tableau est **ancré par un point**, pas par un test.

**Chemin A — capteur, et zones connues.** On part de la FTP, on propose un
découpage éditable (V2), depuis les données rapatriées d'Intervals.

**On lui fait confiance.** Correction du mainteneur, le 17/09, contre ce que
j'avais écrit ici — et il a raison.

J'avais lu ses trois valeurs (258 d'octobre 2025, 235 saisi la veille de
l'étude, 207-211 lus sur la courbe) comme un réglage périmé à confronter. C'est
l'inverse : *« j'ai mis 235 car j'ai recommencé le vélo et j'ai perdu de la
forme. Si j'utilisais ourouler, j'aurais corrigé aussi et remis 235. »* La
valeur déclarée n'est pas une donnée fragile, c'est **le jugement de la
personne sur elle-même**, et il est plus frais que n'importe quel test.

Ce n'est donc pas le piège de la Z2 cardiaque. Là-bas, la réponse recopiait un
réglage que personne n'avait jamais vérifié ; ici, le réglage *est* la
correction. Montrer « votre FTP ne colle pas à votre courbe » à quelqu'un qui
vient de faire ce travail serait du bruit.

Ce qui reste du contrôle : il ne s'affiche pas comme un désaccord. Un écart
persistant se règle par la boucle de correction de [[Q52]] — la personne
rectifie une durée proposée, le facteur bouge — sans qu'on lui dise jamais que
son seuil est faux.

**Chemin B — pas de capteur, ou notion vague des zones.** On apprend de ses
sorties et on approche ses zones en regardant la FC, ou la FC **et** la
puissance.

*Les deux sous-cas n'ont pas la même force.* FC + puissance est solide : les
zones se dérivent directement, et c'est en réalité « il a un capteur mais ne
connaît pas ses zones ». FC seule, c'est la chaîne mesurée à 15,5 W en
[[Q51]] — utilisable, mais elle porte toute l'incertitude.

**Réserve commune, à lever avant de bâtir dessus** : si le compte Intervals
d'une personne est alimenté **depuis Strava**, ces activités pourraient ne pas
ressortir par l'API d'Intervals — c'est ce que Strava interdit ([[Q48]], §5.16,
ré-exposition en cascade). Le mainteneur, alimenté par Garmin, ne verra jamais
le problème ; un utilisateur Strava, si. À vérifier.


### Le plancher de bruit, qui recalibre toute l'ambition

Argument du mainteneur, le 17/09, et il clôt le débat sur la précision :

> 15 W sérieusement c'est invisible par rapport à un raté sur un vélo. Je change
> de casque ou je mets une veste qui vole au vent, je perds plus. Graisser bien
> sa chaîne c'est 10 W facile, entre wax et chaîne dégueulasse.

**C'est juste, et c'est mesurable.** Une transmission entretenue contre une
transmission sale, un casque, un vêtement qui claque : chacun pèse autant ou
plus que les 15,5 W de la chaîne complète sans capteur ([[Q51]]). Le cycliste
promène tous les jours une incertitude matérielle qu'il ne connaît pas, et qui
dépasse celle du modèle.

**Conséquence pour tout agent qui travaillera sur ce sujet** : raffiner
l'estimation sous une quinzaine de watts ne sert à rien. L'effort utile est
ailleurs — d'abord la fenêtre glissante (9 min pour zéro code), puis le CdA
saisonnier (5 min), puis rien. Et le facteur ajustable de [[Q52]] absorbe de
toute façon ce qui reste, y compris la chaîne sale.
### Une frontière : on ne demande pas le matériel, et on n'évalue pas les vélos

Tranché par le mainteneur le 17/09, question fermée :

> non ça vaut pas la peine, ça change tout le temps. Ça sert […] à regarder le
> potentiel d'un vélo, c'est pas le but du produit.

Deux raisons, et la seconde est la plus importante :

1. **Ça change tout le temps.** Pneus, pression, propreté de la transmission,
   casque, vêtement : un formulaire figerait ce qui varie d'une sortie à
   l'autre, et personne ne le tiendrait à jour.
2. **Ce n'est pas le produit.** Le CdA et le Crr existent dans ce dépôt pour
   **dériver une vitesse**, pas pour évaluer un vélo. Comparer des roues,
   chiffrer ce que rapporterait un cadre, mesurer le potentiel d'une machine :
   tout cela est intéressant et étranger à « où rouler aujourd'hui ».

**À l'attention du prochain agent** : voir passer `cda_m2` et `crr` dans
`physique/` n'autorise pas à proposer un comparateur de matériel. L'incertitude
matérielle est absorbée par le facteur ajustable de [[Q52]], jamais interrogée.

### Le remède au défaut 2 : figer le roulement, n'ajuster que l'aéro

Trouvé le 17/09 en regardant un calculateur de CdA du commerce, et le
mainteneur le formule ainsi : *« un outil spécialisé dans le CdA en fait fige
le roulement »*, et *« le Crr c'est une valeur moyenne, comme d'hab on ne
cherche pas à tout faire parfaitement »*.

**C'est la sortie de la dégénérescence, et elle est simple.** On ne peut pas
identifier deux paramètres sur une bande de vitesse étroite : alors on en fige
un. Le roulement se lit dans une table par type de pneu et de surface — piste
0,003, route rapide 0,004, route standard 0,005, gravel ou mauvais revêtement
0,008 — et le CdA sort seul, identifié, sans vallée où glisser.

`calibrer` fait aujourd'hui l'inverse : il ajuste **les deux ensemble** aux
moindres carrés. D'où les valeurs invraisemblables (un CdA de chrono avec un
Crr de VTT), d'où l'ajustement qui part en butée dès qu'on corrige la masse, et
d'où probablement la phrase du 16/09.

**Et ourouler peut faire mieux qu'une table figée** : il connaît les **tags OSM
des routes réellement parcourues** (`apprentissage/routes.py`). Le Crr peut
venir de la surface effectivement roulée plutôt que d'un menu déroulant.

**Le prix à payer, qu'il faut écrire.** En figeant le roulement, le CdA devient
une **poubelle** : il absorbe tout ce qui n'est pas dans le Crr fixé — une masse
fausse, un vent mal estimé, un abri involontaire. Ce n'est plus un CdA physique,
c'est un CdA **effectif**. Sans importance pour prédire une vitesse (un
paramètre effectif bien identifié prédit mieux qu'un couple indéterminé), et
disqualifiant pour comparer des vélos — usage déjà hors périmètre.

**Tout le reste du panneau existe déjà** : vecteur vent (`vent_au_cycliste`,
`FACTEUR_VENT_HAUTEUR`), température et pression (`masse_volumique_air`), perte
de transmission (`RENDEMENT_DEFAUT = 0,976` contre les 3 % du calculateur).

**Sauf l'abri, et c'est volontaire.** Le calculateur en fait une entrée parce
qu'il analyse une sortie passée. Ourouler ne propose que des boucles en solo :
`detecter_groupe` **écarte** ces sorties de la calibration au lieu de les
corriger, ce qui est le bon geste — on ne calibre pas sur des watts qu'on n'a
pas produits. Mesuré : +32,8 W d'erreur de physique en Z2 sur les sorties club
contre +2,8 W ailleurs ([[Q51]]).

### Correction du 17/09 (soir) — la mesure réfute une partie de [[Q51]]

Le lot L6.1 s'est arrêté **sans écrire de code** et a mesuré ce qu'on lui
demandait de corriger. Trois résultats, dont deux réfutent ce qui précède.

**La fenêtre glissante n'apporte rien au mainteneur.** Balayage de 14 à 365
jours, strictement causal (au jour J, jamais la sortie J) : **aucune longueur ne
bat la constante**. La constante vaut `puissance_endurance_pct × ftp_w`, soit
154,8 W, et sa puissance réelle en mouvement vaut 153,1 W — il est déjà à
l'optimum. La fenêtre sert quelqu'un dont la constante est fausse ; elle ne peut
rien apporter à quelqu'un qui n'en a pas besoin. Écarts constatés (0,3 min,
15,98 contre 16,16 W) **sous le plancher de bruit**.

**L'écart de saison 168/147 ne se reproduit pas** sur la puissance **mesurée** :

| découpage | instrument | été | hiver | écart |
|---|---|---|---|---|
| mois civils | NP de sortie | 175,4 | 177,8 | **−2,3 W** |
| mois civils | moyenne en mouvement | 149,1 | 152,9 | **−3,8 W** |
| mois civils | P à FC basse | 146,7 | 147,2 | **−0,5 W** |
| quartiles de température | moyenne en mouvement | 148,9 (26,9 °C) | 155,6 (9,8 °C) | **+6,7 W pour le froid** |

Le signe s'inverse même : les médianes les plus hautes sont en octobre-décembre.

**Explication retenue** : le couple 168/147 **encadre** les 151 W que [[Q51]]
cite par ailleurs. Il vient donc très probablement de la chaîne **sans capteur**
(FC → zone → physique), où un hiver plus lent — vêtements, routes mouillées — se
lit comme une puissance plus basse. Chez un porteur de capteur, il n'y a rien à
capter. **Les 9 minutes de [[Q51]] valent pour le monde sans capteur, pas pour
le monde mesuré.**

**Un piège d'instrument, qui n'était pas nommé** : `simuler` est un modèle
d'équilibre et veut une puissance **moyenne**. La NP médiane (177,8 W) est 24 W
au-dessus de la moyenne en mouvement (153,1 W) : une fenêtre glissante calculée
sur la NP fait passer l'écart de 7,96 à **10,99 min/2 h**, franchement pire.

**La masse datée dégrade la validation tant que le Crr est écrêté** :

| masse | CdA | Crr | F@27 km/h | MAE de validation | butée |
|---|---|---|---|---|---|
| 100,0 (config) | 0,2219 | 0,01062 | 18,04 N | **4,23 %** | — |
| 94,0 | 0,2055 | 0,01200 | 18,12 N | 4,44 % | **Crr max** |
| 93,0 (la vraie) | 0,2070 | 0,01200 | 18,06 N | **4,55 %** | **Crr max** |
| 90,0 | 0,2109 | 0,01200 | 17,84 N | 4,97 % | **Crr max** |

**Et la dégénérescence est mesurée de face** : la résistance totale à 27 km/h
reste entre **17,84 et 18,12 N** pendant que la masse parcourt 90 à 100 kg.
L'ajustement glisse le long de la vallée en gardant le total juste. C'est la
preuve directe que [[Q51]] demandait, et elle est nette.

**La série de poids existe** : 295 jours mesurés sur 1052 (`get_wellness`), du
03/11/2023 au 14/09/2026, 78,5 à 92,0 kg. Écart médian entre mesures 2 jours,
trois trous ≥ 30 jours qui demanderont une interpolation déclarée. La masse
datée est **7,6 kg plus basse en moyenne** que les 100 kg appliqués partout.

**Une erreur de ma part, consignée** : le brief de L6.1 citait « 12,1 W de MAE »
comme critère de non-régression. `valider` ne rend pas des watts mais une
**erreur de temps relative** (`Validation.mae`, en fraction). Les 12,1 W
venaient de la campagne sans capteur et mesuraient autre chose. Un chiffre d'un
monde collé sur l'instrument d'un autre.

**Ce qui en découle pour le sprint 6** : L6.1 tombe dans ses deux moitiés,
l'ordre s'inverse (figer le Crr est le **préalable** de la masse datée), et les
« 5 min de CdA saisonnier » de L6.2 viennent de la même campagne que les 9 min
réfutées — **à revérifier sur la puissance mesurée avant d'être budgétées**.

### Correction du 17/09 (nuit) — le remède de [[Q9]] est mesuré, et il dégrade

Le lot L6.2 s'est arrêté à son tour **sans écrire de code de calibration** : la
mesure demandée avant de livrer réfute la première de ses deux corrections et
redimensionne la seconde. Campagne sur les vraies sorties du mainteneur, 99 RCR
et 35 BMC, partage apprentissage/validation **par date** comme en production,
les sorties les plus récentes jamais vues par l'ajustement.

**Ce qui est mesuré, et comment.** Pour chaque variante : le pipeline complet de
`calibrer_en_deux_passes` (échantillonnage, passe 1, détection de groupe, passe
2), puis `valider` sur les sorties de test. L'unité servie est celle du sprint :
`Validation.mae` est une erreur de temps **relative**, l'écart en minutes sur une
boucle de 2 h vaut donc `mae × 120`.

#### Correction 1 — Crr figé, CdA seul ajusté : **réfutée**

RCR, masse 100 kg, Crr imposé et CdA seul ajusté :

| Crr imposé | CdA trouvé | F@27 km/h | MAE de validation | min/2 h | biais | apparié |
|---|---|---|---|---|---|---|
| 0,0040 | 0,3345 | 15,42 N | 7,94 % | 9,5 | −7,94 % | 3↑/22↓ |
| 0,0050 | 0,3165 | 15,78 N | 7,32 % | 8,8 | −7,32 % | 3↑/22↓ |
| 0,0060 | 0,2993 | 16,17 N | 6,60 % | 7,9 | −6,60 % | 3↑/22↓ |
| 0,0080 | 0,2694 | 17,11 N | 5,03 % | 6,0 | −4,65 % | 6↑/19↓ |
| 0,0100 | 0,2333 | 17,82 N | 4,33 % | 5,2 | −3,04 % | 8↑/17↓ |
| 0,0120 (borne) | 0,1976 | 18,57 N | 4,07 % | 4,9 | −1,16 % | 14↑/11↓ |
| **libre (aujourd'hui)** | **0,2219** | **18,04 N** | **4,23 %** | **5,1** | −2,52 % | référence |

**La courbe est monotone : il n'y a pas d'optimum intérieur.** Le meilleur Crr
imposé est le plus haut que les bornes autorisent, 0,012 — c'est-à-dire
exactement le Crr de VTT que le remède devait faire disparaître. Un Crr de
table de surface pour du bitume (0,004 à 0,005) coûte **+3,1 à +3,7 points de
MAE, soit +3,7 à +4,4 min sur 2 h**, et dégrade **22 sorties de validation sur
25** (médiane −3,95 pp à 0,005).

**Pourquoi le CdA n'absorbe pas, contrairement à ce qu'annonçait le commit
`2741984`.** La colonne `F@27 km/h` le montre de face : à Crr imposé 0,005 la
résistance totale à l'allure courante tombe à 15,78 N contre 18,04 N pour
l'ajustement libre. Le CdA effectif ne peut pas compenser parce que les deux
termes n'ont pas la même dépendance en vitesse — et [[Q9]] avait déjà noté que
la puissance mesurée croît **presque linéairement** avec la vitesse sur le
plat, ce qu'un terme en v³ ne sait pas imiter. Le biais part à −7,3 % : le
modèle devient systématiquement **trop rapide**. En figeant le Crr on échange
un couple indéterminé mais **juste en résistance totale** contre un couple
identifiable et **faux** — or la résistance totale est précisément la seule
grandeur que [[Q9]] déclarait bien mesurée.

Sur le BMC la courbe n'est pas monotone (optimum vers 0,008, soit la valeur
libre 0,00838), mais un Crr de bitume à 0,005 y coûte encore +1,0 point de MAE
(+1,3 min/2 h), 3↑/6↓.

**Et la masse datée n'y change rien** : rejoué à 93 kg de cycliste (la vraie
masse médiane) au lieu de 100, le classement est identique et le Crr de bitume
coûte toujours +2,7 points de MAE. Figer le Crr n'est donc **pas** le préalable
qui débloque la masse datée de L6.1 ; c'est une régression à toutes les masses
essayées.

#### Correction 2 — CdA saisonnier : **réel, mais 1 min et non 5, et pas sur les deux vélos**

Testé **sans** la correction 1, sur le schéma d'aujourd'hui (Crr libre et
partagé, un CdA par saison, trois inconnues) — la dépendance annoncée entre les
deux corrections n'existe pas.

RCR, découpage par mois civils (avril-septembre = été) :

| part de validation | n | fenêtre | CdA été | CdA hiver | écart | MAE réf. | MAE saison | gain | apparié |
|---|---|---|---|---|---|---|---|---|---|
| 0,25 | 25 | 10/2025 → 07/2026 | 0,2132 | 0,2358 | +10,6 % | 4,23 % | 3,66 % | +0,7 min | 17↑/8↓ |
| 0,35 | 35 | 08/2025 → 07/2026 | 0,2162 | 0,2391 | +10,6 % | 3,99 % | 3,53 % | +0,6 min | 20↑/15↓ |
| 0,45 | 45 | 06/2025 → 07/2026 | 0,2209 | 0,2430 | +10,0 % | 3,48 % | 3,20 % | +0,3 min | 25↑/20↓ |

**Ce qui tient** : le paramètre lui-même, remarquablement stable — le CdA
d'hiver est **10 % plus haut** que celui d'été aux trois partages, et le signe
est le bon (des vêtements d'hiver traînent davantage). Le test apparié est
favorable aux trois partages, et le gain **médian** par sortie vaut +0,8 pp,
stable lui aussi, soit environ **1 min sur une boucle de 2 h**.

**Ce qui ne tient pas** : les **5 minutes** annoncées. Le gain **moyen** vaut
+0,3 à +0,7 min selon le partage, et il rétrécit quand la validation s'allonge
— signe que la moyenne est tirée par quelques sorties très fausses que la
saison ne corrige pas. Comme les 9 minutes de la fenêtre glissante, les 5
minutes venaient de la campagne **sans capteur**.

**Et il n'y a rien à prendre sur le BMC** : +0,2 % d'écart saisonnier, gain nul
(2,36 % → 2,37 %). Le chrono se roule l'été ; à `part_validation` 0,25 ses 9
sorties de test sont **toutes estivales**, donc l'effet y est non seulement nul
mais **non mesurable**. Un CdA saisonnier appliqué aux deux vélos serait, sur
celui-là, une décoration.

**Le découpage compte, et ce n'est pas la température.** Découper au
thermomètre du tronçon plutôt qu'au calendrier donne un écart plus petit (+5 à
+8 %) et un gain plus petit (+0,1 à +0,5 min) à tous les partages. C'est
cohérent avec l'explication « vêtements » : on s'habille par habitude et par
saison, pas au degré près — et la densité de l'air, elle, est déjà modélisée
par `masse_volumique_air`.

#### Ce qui en découle, et ce qui se demande au mainteneur

Aucune ligne de code de calibration n'a été écrite : livrer la correction 1
aurait livré une **régression mesurée** de 3,7 à 4,4 min sur 2 h, ce que les
règles absolues 4 et 5 interdisent de présenter comme un gain.

La correction 2 survit, mais son cadrage tombe avec la correction 1 — elle n'en
dépend pas, elle vaut 1 min et non 5, et elle ne vaut que sur un vélo. La
réécrire seule est une **repriorisation**, pas l'exécution du lot cadré : elle
appartient au mainteneur. Quatre questions la bloquent, et aucune n'est
technique :

1. **Où coupe la saison ?** Avril-septembre est le découpage qui mesure le
   mieux, mais c'est un choix de produit — et une coupe franche fait sauter la
   durée prédite d'environ une minute entre le 30 septembre et le 1ᵉʳ octobre.
   Une transition douce, ou la tenue réellement déclarée, changeraient le
   modèle de données.
2. **Quel CdA sert à prédire ?** Celui de la saison de la sortie **prévue**,
   vraisemblablement — mais c'est une notion nouvelle dans `calibration.json`.
3. **Deux CdA par vélo dans `calibration.json`** : changement de format et de
   version, sur un fichier que la correction 1 devait de toute façon invalider
   et qui, la correction 1 abandonnée, reste valide tel quel.
4. **Applique-t-on le saisonnier à un vélo où il mesure zéro ?** Sur le BMC
   l'effet est nul et invérifiable faute de sorties d'hiver en validation.

**Ce que [[Q9]] devient.** Elle reste close, et la mesure la renforce plutôt
qu'elle ne la rouvre : la dégénérescence est réelle, mais le remède du commit
`2741984` — figer le roulement par surface — est mesuré **plus coûteux que le
mal** pour l'usage du produit, qui est de prédire une durée. La phrase du
16/09 de la docstring de `physique/calibration.py` n'a donc pas à être reprise :
elle dit que tout l'écart entre les deux vélos est passé dans le Crr, ce qui
reste vrai, et la mesure ci-dessus ajoute seulement qu'on ne peut pas le lui
retirer sans perdre la résistance totale.

**Ce qui n'a pas été essayé, et qui reste ouvert.** Le Crr par **surface OSM
réellement roulée**, que le commit `2741984` appelait de ses vœux : les
`WayTags` de notre serveur BRouter portent bien `surface` et `smoothness`
(mesuré le 16/09, voir `seance/terrain.py`), et `apprentissage/routes.py`
sait déjà rejouer une sortie dans BRouter pour en obtenir les tags. Mais cette
piste ne change pas le résultat ci-dessus : elle ferait varier le Crr imposé
d'un tronçon à l'autre autour d'une valeur de bitume, et le balayage montre que
**toute** valeur de bitume dégrade. Elle mérite d'être notée, pas budgétée.

#### Réponse du mainteneur (17/09/2026) — la littérature plutôt que la précision

« Je sais pas s'il faut se prendre la tête avec autant de précision. Comme sur
le Crr : prendre des données de la littérature, *vélo de route amateur* et
*CLM amateur*. En V2 on permet aux gens de choisir s'il y a des spécialistes.
Test à faire sur mes données, voir si on dérive beaucoup en simulant. Mais on
l'a vu, CdA/Crr c'est aussi transmission, tenue, casque, etc. »

**Ce que ça tranche.** Les quatre questions ci-dessus **tombent** : il n'y aura
pas de CdA saisonnier, donc pas de coupe de saison à placer, pas de second CdA
dans `calibration.json`, pas de question du vélo où l'effet mesure zéro. Le
gain d'une minute est abandonné volontairement, au profit d'un modèle plus
simple à expliquer.

**Ce que ça met à la place.** Des **valeurs de littérature par catégorie de
cycliste** — « vélo de route amateur », « CLM amateur » — au lieu d'un
ajustement par vélo. Le dépôt en a déjà l'amorce : `physique/commande.py:42`
porte `CDA_DEFAUT = 0.32` et `CRR_DEFAUT = 0.005`, soit une seule catégorie
implicite. Il s'agit d'en faire une table nommée et choisie, pas une constante.

**La remarque qui explique la mesure de la nuit.** « CdA/Crr c'est aussi
transmission, tenue, casque » : ces deux paramètres ne sont pas des grandeurs
physiques pures, ce sont des **paramètres effectifs** qui absorbent tout ce que
le modèle ne représente pas — rendement de transmission, vêtements, casque,
position. C'est exactement pourquoi imposer un Crr de table de surface a
dégradé de 3,7 à 4,4 min : on retirait au couple une part d'erreur qu'il
portait légitimement, sans donner au CdA de quoi la reprendre. La remarque du
mainteneur et la mesure disent la même chose par deux chemins.

**Le test qu'il demande, et qui reste à faire.** Simuler ses vraies sorties avec
les valeurs de littérature de sa catégorie, au lieu de sa calibration
personnelle, et mesurer la dérive **en minutes sur 2 h**. C'est la question que
le sprint 8 pose de toute façon pour l'invité sans historique : « sans
calibration personnelle, le modèle doit tourner sur des paramètres génériques
et le dire ». La mesure répond aux deux d'un coup. **Rattachée à L8.5.**

**Reporté en V2** : laisser le cycliste choisir sa catégorie, pour les
spécialistes. Pas avant d'avoir mesuré la dérive.

#### Réponse du mainteneur (17/09/2026) — **on garde les poids, la suppression attend**

« On garde les poids, et on peut attendre 9-10 avant la suppression des
données. Je suis pas un service, c'est des potes. »

**Ce que ça tranche.** Les poids de routes appris restent **collectifs** : ce
qu'un cycliste a roulé améliore le parcours d'un autre, et c'est assumé comme
la valeur d'un service partagé. L'ambiguïté que la question soulevait — un
compte supprimé laisse-t-il ses poids derrière lui ? — se dissout : les poids
ne sont pas traités comme des données personnelles récupérables, ils sont fondus
dans un modèle commun dès leur apprentissage.

**Ce que ça décale.** L'export et la suppression de compte passent au **sprint
9 ou 10**, alors que la doctrine §10.2 les promettait « dès la première version
hébergée ». La doctrine est modifiée en conséquence dans cette même PR, comme le
veut `CLAUDE.md` — une décision qui la contredit ne reste pas un écart tacite.

**Réserve, dite une fois et non répétée.** Le cercle restreint ne change pas le
droit : dès que le service est ouvert à d'autres personnes sur Internet, le
droit à l'effacement s'applique, et l'exemption « activité strictement
personnelle ou domestique » du RGPD est étroite. Différer la **mise en œuvre**
est un choix que le mainteneur assume en connaissance de cause ; ce n'est pas
la même chose que de décider que l'obligation n'existe pas. Le jalon réaliste
est **avant d'inviter quelqu'un hors du cercle des proches**, pas avant le
premier ami.

**Ce qui reste libre.** Rien n'oblige à trancher aujourd'hui le sort des poids à
la suppression : quand le lot arrivera, « les poids restent, le profil et les
fichiers partent » est une réponse défendable et déjà décidée ici.

## Q53 — Trois fonctions de tracé n'entrent dans aucun sprint — **tranchée le 17/09/2026 : au backlog**

La repriorisation de fin des sprints 5 et 6 a figé les lots des sprints 7
(l'hébergé) et 8 (prêt à inviter des copains). Trois questions n'y trouvent pas
leur place, et ce n'est pas un oubli : ce sont des fonctions de **qualité du
tracé**, alors que les deux caps restants portent l'un sur l'infrastructure,
l'autre sur l'accueil d'un nouveau venu.

- [[Q29]] — l'effet de concentration des feux, et le poids qui dépend de
  l'intensité du bloc.
- [[Q31]] — la distance de dégagement urbain avant la zone roulante.
- [[Q32]] — le mode circuit, tourner en rond quand il n'y a pas de couloir.

**Mon erreur de cadrage, dite en toutes lettres.** J'ai fait déplacer Q29 et
Q31 vers le sprint 7 le 17/09 en proposant ce choix au mainteneur **sans avoir
lu le cap du sprint 7**, qui est l'hébergé et rien d'autre. Le déplacement a
donc été validé sur une prémisse fausse. Elles sont ici en attente, pas au
sprint 7.

**Trois issues, et c'est un arbitrage de produit.** (a) Un sprint 9 « qualité du
tracé » qui les rassemble, après l'ouverture aux copains. (b) Les glisser dans
le sprint 8 au motif qu'un invité jugera d'abord la qualité des boucles qu'on
lui propose. (c) Les laisser au backlog sans sprint, et les prendre au fil du
dogfooding quand la route en désignera une comme urgente.

Rien n'est tranché : elles restent dans le registre, sans sprint attribué.

#### Réponse du mainteneur (17/09/2026) — **backlog**

Issue (c) retenue : [[Q29]], [[Q31]] et [[Q32]] restent au backlog, **sans
sprint attribué**, et seront prises au fil du dogfooding quand la route en
désignera une comme urgente.

C'est cohérent avec la clôture du sprint 6, qui fait du dogfooting une exigence
permanente hors sprint plutôt qu'une condition de clôture : c'est en roulant
qu'on saura si la concentration des feux gêne vraiment un bloc, si le
dégagement urbain manque, ou si le mode circuit sert à quelque chose. Aucune
des trois ne mérite d'être budgétée sur une intuition.

**Ce que ça veut dire concrètement** : les sprints 7 et 8 sont complets tels
qu'ils sont figés, et aucun sprint 9 « qualité du tracé » n'est ouvert
aujourd'hui.


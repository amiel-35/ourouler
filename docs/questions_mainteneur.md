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

## Q2 — Liste des vélos et règle de rattachement

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

## Q3 — Point de départ et règles de tenue / de séance

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
- Sorties en groupe (sprint 3) : les FIT ne le disent pas ; Strava le sait
  souvent (champ « nombre d'athlètes » de l'activité). Voies : export
  Strava, ou détection statistique (vitesse trop élevée pour la puissance =
  peloton) par la calibration elle-même.

## Q4 — Moteur de tracé — **close le 12/09/2026** : BRouter sur Coolify (pas sur le Mac, pour pouvoir partager)

BRouter auto-hébergé (Java absent sur le Mac ; Docker présent ; ou sur le
serveur Coolify/Hetzner) ou GraphHopper API (clé, gratuit à petit volume) ?
Aucune installation ne sera faite sans accord.

## Q5 — Garmin Connect (S5)

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


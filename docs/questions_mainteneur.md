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
  `boucle`) — on prend le pire moment pour la couche de base, et on
  recommande « à emporter / à enlever » pour l'amplitude (départ frais,
  retour chaud ; averse annoncée au km 40). Le vent entre dans le ressenti
  et déclenche seul la veste au-delà d'un seuil.
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

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
- Règles de tenue : seuils de température ressentie, de vent, de pluie et
  ce qu'on met à chaque palier (utiles à partir de S4).
- Règles de séance : que veut dire « un bloc tient sur un terrain » (pente
  max, longueur minimale sans carrefour, etc.) — S4.

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

## Q6 — Nom du projet, visibilité du dépôt, et purge avant publication

Nom de travail du paquet et de la commande : `ourouler`. Dépôt GitHub créé
en **privé** sous le nom `bike-routing` ; à renommer et passer en public
quand le nom est validé (le projet est destiné à être open source, MIT).

**Avant tout passage en public** (relevé par le relecteur du sprint 1) :
les documents de cadrage (`docs/cadrage.md`, `docs/plan_sprints_agents.md`,
ce fichier) citent des chiffres du mainteneur — FTP, masse, nombre de
sorties, kilométrage, noms d'équipement Intervals. Le code, les tests et
`config.example.toml` n'en contiennent aucun. Décider : anonymiser ces
documents, ou déplacer les chiffres dans un fichier ignoré par git.

## Q7 — Ordre des règles de rattachement vélo (relecture sprint 1)

Le contrat place la règle « période d'un vélo » avant la règle
« home-trainer ». Dès que Q2 renseignera des périodes, une séance
d'intérieur tombant dans la période d'un vélo lui sera attribuée au lieu
d'aller en « home-trainer ». Proposition : inverser (intérieur d'abord),
sauf si un vélo est explicitement déclaré d'usage home-trainer.

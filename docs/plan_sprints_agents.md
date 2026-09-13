# Plan de sprints et équipe d'agents — ourouler

Déroulé de la roadmap en sprints, avec pour chaque lot l'agent, le modèle et
les critères d'acceptation. Puis l'équipe Claude Code qui l'exécute. Le
découpage d'origine (S0 → S5) est dans `docs/cadrage.md` ; ce document le
transpose en sprints et le fera vivre.

## Cadence de repriorisation — tous les deux sprints

Règle reprise d'ix-presenter, appliquée dès le premier cycle :

- **Les deux prochains sprints sont figés.** On les exécute tels qu'ils sont
  écrits ; ce qui déborde attend le point de repriorisation.
- **Un troisième est esquissé.** Il donne une direction, il n'engage à rien.
- **À la fin des deux figés, le mainteneur reprioritise** à partir de ce qui
  a été livré, **des écarts entre prévu et réalisé**, et du backlog.
- **La dernière décision reçue se relit en premier** : les corrections
  issues d'un aller-retour sont celles qu'on relit le moins bien.

## Cadence et règles de sprint

Un sprint = un jalon démontrable sur les vraies données du mainteneur, pas un
pourcentage. La capacité se compte en sessions d'agents supervisées, pas en
jours. Un lot n'est fini que si ses tests passent, si `ruff` est vert et si
la commande du jalon tourne pour de vrai — ou si le lot est explicitement
marqué **non vérifié** avec la raison (clé absente, données absentes).

Règle d'or : à la fin de chaque sprint, `uv run ourouler --help` et chaque
sous-commande déjà livrée fonctionnent toujours.

## Doctrine d'affectation des modèles

Décision du mainteneur (12/09/2026) : Fable est très puissant mais très
cher ; le réserver au plus critique, Opus quand ça suffit. Le critère n'est
pas le prix au token mais le coût total de l'aller-retour.

- **Fable** : le cadrage initial, le découpage des sprints, la relecture des
  points critiques — modèle physique et sa calibration (S3), boucle
  séance ↔ terrain (S4), tout ce qui écrit chez Garmin (S5). Débogage de ce
  qu'Opus n'a pas résolu en deux passes.
- **Opus** : le défaut. Développement des lots, spécification et écriture
  des tests adversariaux, relecture courante, supervision hors cadrage.
- **Haiku** : le mécanique borné et bien spécifié — fixtures, boilerplate,
  corrections de lint, mise à jour de docs depuis un diff. Jamais sur du
  code de comportement.
- **Sonnet** : non retenu pour l'instant. À reconsidérer si le coût Opus
  devient un sujet sur des features standard.

Avant de lancer un sprint, demander au mainteneur s'il veut Fable ou Opus
pour le superviseur ; ce choix vaut pour tout le sprint.

## L'équipe d'agents

Cinq rôles, définis dans `.claude/agents/`. Tous partagent trois règles
d'arrêt : ambiguïté = on s'arrête et on demande ; contradiction avec la
doctrine = on s'arrête et on signale ; installation sur une machine, copie
d'une clé ou donnée personnelle dans le dépôt = interdit.

- **superviseur** (Fable au cadrage, Opus sinon) — découpe, distribue,
  arbitre la technique, remonte le produit. Ne merge jamais.
- **dev-feature** (Opus) — implémente une tâche avec ses tests unitaires.
- **dev-mecanique** (Haiku) — exécute les checklists mécaniques.
- **testeur-adversarial** (Opus) — écrit, en aveugle du code et dans son
  propre worktree, les tests qui essaient de casser le lot.
- **relecteur** (Opus, Fable sur les points critiques) — revue finale avant
  le mainteneur, verdict écrit.

Flux type : superviseur découpe → dev-feature implémente en parallèle du
testeur-adversarial → les tests rencontrent le code → relecteur → le
mainteneur merge. Deux agents en parallèle tournent chacun dans son
worktree (leçon d'ix-presenter : deux agents dans le même arbre s'écrasent en
silence et l'aveuglement du testeur est compromis).

## Les sprints

### Sprint 0 — Socle **[fait le 12/09/2026]**

Jalon : dépôt initialisé avec doctrine, CLAUDE.md, fiches d'agents,
`pyproject` (uv), config d'exemple, `.gitignore` protégeant données et clés,
inventaire des données réelles disponibles.

Constats sur pièces au cadrage :
- Intervals.icu (via le MCP) : 355 sorties vélo depuis le 02/12/2023, dont
  163 en extérieur (9 128 km, 93 % avec puissance) et 192 sur home-trainer.
  Le vélo n'est renseigné que sur 68 sorties (`rcr` 55, `VR` 11, `BMC` 2),
  presque plus depuis novembre 2024 : le rattachement par vélo sera une règle
  par période et par appareil (`device_name`), à valider avec le mainteneur.
  31 « vélo d'intérieur » enregistrées à la montre, sans distance ni
  puissance, sont inutilisables pour la calibration.
- Aucun fichier FIT/GPX/TCX conservé sur le Mac (nettoyage du 11/09). Les
  vraies données passeront par l'API Intervals (téléchargement du FIT
  d'origine), qui exige une clé d'API que le mainteneur doit fournir.
- Le jeton `~/.config/ha/garmin-token` est un jeton Home Assistant, pas un
  accès Garmin Connect : S5 reste à cadrer.
- Sur le Mac : `uv`, Python 3.14, Docker ; pas de Java (BRouter natif
  demanderait Java ou Docker).

### Sprint 1 — Données et météo par direction **[figé]**

Jalon : `ourouler meteo` affiche, pour le point de départ du mainteneur, la
pluie, le vent et la température ressentie par direction et par heure sur
les prochaines heures, avec le désaccord entre modèles ; `ourouler
inventaire` lit des fichiers FIT/GPX/TCX et le cache Intervals et sort
l'inventaire des sorties depuis décembre 2023 par vélo.

| Lot | Agent · Modèle | Critères d'acceptation |
|---|---|---|
| L1.1 Config et cœur sans configuration : `config.py` (dataclasses, TOML), `cli.py` (argparse, sous-commandes) | dev-feature · Opus | `ourouler --help` ; `ourouler --config x.toml` charge et valide ; une erreur de config nomme le champ ; aucun module hors `cli.py`/`config.py` n'importe `os.environ`, `pathlib.Path.home()` ni `tomllib` |
| L1.2 Lecteur unique FIT/GPX/TCX → `Activite` (métadonnées + trajectoire horodatée : temps, lat/lon, altitude, distance, vitesse, puissance, cadence, FC, température si présents) | dev-feature · Opus | les trois formats donnent le même modèle ; fixtures synthétiques (générées, pas réelles) ; fichier tronqué ou vide = erreur nommée, pas une exception brute |
| L1.3 Cache local : fichiers bruts + index SQLite ; `inventaire` par vélo et par mois | dev-feature · Opus | `ourouler inventaire --depuis 2023-12-01` liste les sorties par vélo (règle de rattachement configurable : équipement Intervals, période, appareil) et par mois ; relance idempotente |
| L1.4 Connecteur Intervals : liste des activités depuis une date, téléchargement du FIT d'origine dans le cache, séance planifiée du jour | dev-feature · Opus | client injectable, réponses enregistrées en fixtures ; **vérification sur vraies données conditionnée à la clé d'API** (question Q1) — sinon lot marqué non vérifié |
| L1.5 Météo par direction : client Open-Meteo (plusieurs points par appel, AROME HD + second modèle), couronne de points (N directions × distances), rapport par direction et par heure, désaccord entre modèles | dev-feature · Opus | `ourouler meteo --depart 08:00 --horizon 6` affiche 8 directions × 3 distances × heures : pluie mm/h, vent (force, direction, face/dos par direction), ressenti ; un indice de confiance par cellule ; tourne pour de vrai sur le point de départ ; tests sur réponses enregistrées |
| L1.6 Tests adversariaux du sprint | testeur-adversarial · Opus | fichiers corrompus, réponses d'API hostiles, fuseaux, cache absent ; invariants (pas de réseau, pas de config dans le cœur, pas de coordonnée réelle en fixture) |
| L1.7 Relecture | relecteur · Opus | verdict écrit par lot |

### Sprint 2 — Tracé **[livré le 13/09/2026, PR en attente]**

Jalon atteint : `ourouler boucle --distance 60 --direction NE` produit un
GPX de boucle depuis le point de départ, avec candidates comparées (trafic,
revêtement, virages à gauche, sens, pluie et vent à l'heure de passage), et
`--gpx` évalue un tracé importé. Contrat : `docs/sprint2_contrat.md` ;
relecture : `docs/sprint2_relecture.md`.

Moteur : **BRouter auto-hébergé sur Coolify** (Q4), image nightly épinglée
(le tag stable lit un format de segments dépassé), segments Bretagne, proxy
nginx à auth basique ; identifiants dans la config locale du mainteneur.
Le lot « virages à droite » est un post-traitement des candidates (aucun
moteur ne distingue gauche/droite nativement).

### Sprint 3 — Routes connues, puis modèle physique **[esquissé, non figé]**

**Lot « routes connues » (décision d'Amiel, nuit du 12 au 13/09).** Mesuré
sur dix vraies sorties rejouées dans BRouter (747 km) : 65 % de `tertiary`,
23 % de `secondary`, 2 % de `primary`. Nos classes « trafic » (primary +
secondary) étaient donc trop sévères : les secondaires font un quart de sa
pratique. Amiel : « la majorité de mes traces sont des routes acceptables
et pas dangereuses, surtout en semaine ; le dimanche j'en suis sûr à 90 % ;
souvent issues de Strava, très bon pour ça ». D'où le renversement : **les
traces du cycliste sont la vérité terrain pour apprendre**, pas les
étiquettes OSM. **Attention (précision d'Amiel)** : ces traces ne couvrent
que le sud et l'ouest de Rennes ; elles servent à l'apprentissage, jamais
comme critère de choix — sinon toute boucle vers le nord ou l'est serait
pénalisée à tort. « Inconnu » n'est jamais un malus.
- Construire depuis l'historique la liste des tronçons parcourus (rejoués
  dans BRouter pour en avoir les tags), avec nombre de passages et jour de
  semaine (semaine > dimanche).
- **Apprendre** sur ces tronçons ce qui est accepté : type de route,
  `maxspeed`, `lanes`, revêtement, coût BRouter par km… → en déduire les
  poids du score, appliqués partout ; `secondary` moins pénalisé que
  `primary` si les données le confirment.
- Par candidate : colonne « routes connues » (part des km déjà roulés), à
  titre **informatif** seulement.
- Afficher le **coût moyen du profil BRouter** (colonne `CostPerKm` des
  messages) : c'est le jugement du routeur lui-même sur le trafic.
- Liste d'évitement (routes à ne plus prendre) → `nogos` BRouter.
- Ce même jeu de sorties sert ensuite à calibrer les poids du score.

**Vu par Amiel sur une boucle réelle (carte du 13/09).** Un seul vrai
défaut : les **antennes en cul-de-sac** (Thorigné-Fouillard : crochet
aller-retour sur un chemin non revêtu ; Noyal-sur-Vilaine : petit crochet),
artefact du mode boucle de BRouter dont les points de passage sur le cercle
tombent à côté des routes. À corriger dans ce lot : activer
`profile:correct_misplaced_via_points` (et sa distance) dans l'appel, et
détecter dans le tracé tout aller-retour sur lui-même (même géométrie
parcourue dans les deux sens sur < 500 m) pour l'élaguer ou pénaliser la
candidate. **Le reste lui va** : les traversées de bourg (Noyal par la D92)
ne sont pas un défaut — c'est la principale différence entre `fastbike` et
`fastbike-verylowtraffic`, et **`fastbike` reste le profil par défaut**.
Nuance mineure de classement, sans urgence : une simple traversée d'une
route à trafic (Chevaigné, D3175 sur quelques dizaines de mètres) ne
devrait pas compter comme un tronçon « trafic ».

**Lot modèle physique.** Jalon : pour chaque vélo, des paramètres calibrés
(masse, CdA, roulement) et un rapport d'erreur de temps sur des sorties non
vues ; home-trainer exclu (Q7). Relecture Fable.

Niveau de précision voulu (Amiel, 13/09) : **pas de folie**, la route est
ouverte, avec circulation, stops et vent qui tourne. Une masse approximative
par vélo suffit (1 kg sur 100 kg = 1 % en montée, rien sur le plat) ; le
poids du cycliste vient d'Intervals quand il y est, sinon une constante, car
hors montagne il pèse peu. L'effort va dans ce qui compte : CdA par vélo,
vent réel (archives Open-Meteo), et **l'exclusion des sorties en groupe**
(peloton = aérodynamique faussée). Les FIT ne le disent pas ; Strava a un
champ « nombre d'athlètes » (export Strava ou API en lecture). **Décision
d'Amiel (13/09) : c'est le plus dur, donc combiner** (1) le nom de la
sortie (« sortie club », « groupe », « peloton »… liste de mots dans la
configuration) et (2) l'incohérence physique : vitesse élevée pour une
puissance basse que ni la pente ni le vent n'expliquent. Méthode : calibrer
d'abord sur les sorties sûres (nom neutre, sortie seul), puis utiliser le
modèle obtenu pour repérer les autres (résidu de vitesse anormalement
positif sur une grande part de la sortie) et les écarter ; itérer une fois.

### Plus tard — S4 séance ↔ terrain, S5 envoi au compteur, HA

Rien de planifié tant que les sprints 1 et 2 n'ont pas été reparcourus.

Backlog « envoi au compteur » (décisions du 12/09) : pas d'API Garmin
Connect pour un particulier → le GPX généré est le socle ; sur mobile,
partage système du GPX vers l'application Garmin Connect (deep link /
« ouvrir avec ») ; puis, dans l'ordre d'intérêt exprimé, **Coros, Wahoo
(ELEMNT), Hammerhead (Karoo)**. Vérifié le 12/09 (doc des marques) :
**Wahoo** a une vraie API cloud (OAuth 2, envoi d'un parcours FIT qui
arrive sur le compteur ; accès développeur sur demande motivée) — la voie
la plus propre, à demander quand le service sera hébergé ; **COROS** : GPX
« ouvrir avec » l'application, ou synchro depuis Strava / Komoot / Ride with
GPS, programme développeur sur candidature ; **Hammerhead** : tableau de
bord avec import par URL (Strava, RWGPS, Komoot) et comptes liés (dont
Intervals.icu pour les séances), pas de dépôt direct public → intermédiaire
ou import de fichier. Le GPX partagé depuis le mobile couvre Garmin et
COROS sans rien demander à personne. L'Edge sait charger un parcours et une séance
structurée en même temps : la séance vient déjà d'Intervals.icu.

## Historique des sprints

- **2026-09-13, nuit** — Sprint 2 livré sur `sprint-2` (branche issue de
  `sprint-1`), PR vers `sprint-1`/`main` en attente. Déroulé : BRouter
  déployé sur Coolify ; quatre agents en parallèle (BRouter+GPX+candidates,
  coûts+météo le long, rattachement par capteur, testeur adversarial) puis
  assemblage de la CLI ; relecture (19 points, aucun bloquant technique) ;
  deux passes de corrections. État : 1 329 tests, ruff vert. **Vérifié sur
  vraies données** : `boucle` (5 candidates de 60 km en ~2 s de BRouter +
  10 appels Open-Meteo), `inventaire --synchroniser` (355 sorties vélo :
  RCR 120 / BMC 43 / home-trainer 192, séparés par le capteur de
  puissance, triathlons compris, 21 entrées Strava creuses ignorées).
  Écarts prévu/réalisé : rayon→distance ≈ ×5 mesuré et auto-ajusté ;
  classes de trafic trop sévères sur `secondary` (23 % de la pratique
  réelle) → lot « routes connues » au sprint 3 ; cache météo ajourné à
  l'hébergé (doctrine mise à jour) ; D+ moteur ≠ D+ GPX relu (provenance
  affichée) ; index du cache passé en v2 (une ligne par activité, pas par
  contenu). Dette assumée : poids du score et de la pluie non calibrés ;
  filtre de sport par vocabulaire Intervals ; historique git à purger avant
  publication (Q6).

- **2026-09-12** — Sprint 0 fait en session de cadrage (Fable). Sprint 1
  lancé le soir même, mainteneur absent : les lots avancent sur fixtures et
  sur Open-Meteo (pas de clé nécessaire) ; le connecteur Intervals attend la
  clé pour sa vérification réelle.
- **2026-09-12, soir** — Sprint 1 livré sur la branche `sprint-1`, PR vers
  `main` en attente du mainteneur. Déroulé : deux dev-feature (données,
  météo) et un testeur-adversarial en aveugle, chacun dans son worktree ;
  relecture Opus (17 points, 1 bloquant : valeurs réelles dans
  `config.example.toml`, corrigé) ; deux passes de corrections. État final :
  822 tests, ruff vert. **Vérifié sur vraies données** : `ourouler meteo`
  (Rennes, AROME HD + ICON, soirée sans pluie donc branche « désaccord »
  démontrée sur fixtures seulement). **Non vérifié** : lecteurs, cache,
  inventaire et connecteur Intervals — aucun fichier réel ni clé (Q1).
  Écarts prévu/réalisé : sous-commande `config` ajoutée ; `--depart`
  tronqué à l'heure ; second avis apparié par horodatage ; découpe Intervals
  systématique par mois (le seuil de troncature deviné a été retiré).
  Dette assumée, à reprendre : fenêtre partielle des 30 premières secondes
  de la puissance normalisée ; lissage du dénivelé à 5 points non calibré ;
  découpage mois/jour en UTC ; règle « ici » sans vent relatif ; budget de
  fixtures à 2 % de sa borne ; Q7 (ordre des règles de rattachement).

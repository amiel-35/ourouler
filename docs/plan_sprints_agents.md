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

**Révisée le 15/09/2026**, alignée sur les instructions globales du
mainteneur. La version précédente — « Fable au critique, Opus partout où ça
suffit » — venait d'une incompréhension de ma part, appliquée aux sprints 2
à 4. Le critère n'est pas le prix au token mais le coût total de
l'aller-retour, et surtout **la nature de la tâche** : implémentation cadrée
ou jugement.

- **Sonnet — le défaut.** Toute implémentation dont les critères
  d'acceptation sont clairs : un lot décrit par le contrat de sprint, des
  tests à écrire depuis une spec, une correction dont le symptôme est
  mesuré.
- **Haiku.** Le mécanique en masse : renommage, boilerplate, conversion de
  format, triage de logs, mise à jour de docs depuis un diff.
- **Opus.** Le jugement pur et les algorithmes subtils : relecture de lot,
  tests adversariaux (imaginer ce qui casse n'a pas de critère
  d'acceptation), découpage d'un sprint, débogage coriace, fusion délicate,
  concurrence. Sur ce projet, les lots « placement », « calibration » et
  les résolutions de conflit multi-lots relèvent d'Opus.
- **Fable.** Seulement quand l'indépendance vis-à-vis du contexte du
  mainteneur est le but — relecture adverse d'un plan ou d'un diff qu'il a
  écrit. **Toujours demander d'abord.**

Deux règles qui vont avec :
- **Le `model` est obligatoire sur chaque appel d'agent.** L'omettre hérite
  silencieusement du modèle de session.
- **Ne pas escalader sur un aveu d'incertitude quand la tâche est du
  jugement.** Un agent sous-tieré ne se déclare pas incertain, il répond
  faux avec assurance. Le cheap-then-escalate ne vaut que là où existe un
  signal mécanique : tests, lint, CI. Changer de tier en cours de tâche
  redémarre à zéro, le cache de prompt appartient au modèle qui l'a écrit.

Ce qui revient d'un sous-agent : des **pointeurs** — chemins, plages de
commit, identifiants —, pas du contenu brut. Un contenu entier posé dans le
contexte paie un loyer à chaque tour.

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

### Sprint 2 — Tracé **[livré le 13/09/2026, fusionné]**

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

### Sprint 3 — Antennes, routes connues, modèle physique **[livré le 13/09/2026, fusionné]**

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

### Sprint 4 — Séance ↔ terrain **[livré le 13/09/2026, fusionné]**

Le cœur du projet. Jalon : `ourouler sortie` lit la séance du jour dans
Intervals, génère des boucles, les simule avec le modèle calibré, place les
blocs sur le terrain et rend GPX, résumé, tenue et **carte de vérification**.

**Séances de référence, relevées dans le compte du mainteneur le 13/09.**
48 séances vélo planifiées depuis mars 2026, trois formes :
- « Vélo HIT — 4x8min Z4 », 55 min : quatre tronçons d'environ 4 km chacun,
  roulants, sans village ni descente. C'est le cas dur.
- « Vélo — Sortie EF 2h » : aucune contrainte de terrain.
- « 2x20' 80-85 % + 4x3' 100 % FTP » : deux longs puis quatre courts.

**Deux séances de coach fournies par le mainteneur le 13/09 (iDOSport,
planifiées par son entraîneur, remontées dans Intervals).** Elles changent
la nature du problème : on ne place pas des blocs isolés, on place des
**séries**, et l'échauffement fixe *où* chercher sur la boucle.

| Séance | Structure | Contrainte de terrain |
|---|---|---|
| « 2x20' (80 % FTP) + 2x10' r4/3' », 2h44 | 1h à 168-194 W ; 2 × [20 min à 199-214 W, récup 4 min] ; 2 × [10 min à 212-224 W, récup 3 min] ; 30 min calme | un couloir propre de **11 km d'un trait**, deux fois |
| « Durabilité », 2h57 | 1h à 155-181 W ; 4 × [5 min à 232-258 W, récup 1'30] ; 45 min ; 4 × [5 min, récup 1'30] ; 20 min | 4 tronçons propres d'**environ 2,8 km**, deux fois |

Trois conséquences de conception :
- **La récupération absorbe le point dur, même courte** (correction du
  mainteneur, 13/09 : « pour durabilité non, pas 14 kilomètres »). Une
  récup de 1'30 suffit à caser une **traversée de village** ou un
  **demi-tour**. La contrainte porte donc sur chaque bloc pris isolément,
  pas sur la série entière.
- **Le demi-tour rend le problème soluble, mais il se paie.** Avec un
  demi-tour à chaque récup, un seul bon tronçon de 3 km suffit pour tout
  un 4×5'. Le mainteneur le trouve « plus chiant » que la traversée de
  village : hiérarchie du score, du meilleur au moins bon —
  (1) autant de tronçons propres distincts que de blocs, récups qui
  absorbent les villages ; (2) tronçons réutilisés avec demi-tour en
  récup, pénalité légère ; (3) village ou carrefour **dans** le bloc,
  pénalité forte.

  **Mécanique exacte du demi-tour** (mainteneur, 13/09) : la récup se coupe
  en deux moitiés symétriques autour du demi-tour —

      10 min bloc (aller) → 2 min récup → demi-tour → 2 min récup (retour)
      → 10 min bloc (sens inverse)

  On revient donc exactement au bout du segment, et **le segment n'a pas
  besoin d'être plus long que le bloc**. Trois conditions à vérifier :
  - **Plat ou faux-plat seulement.** « Un tronçon marche souvent dans les
    deux sens sur du plat, mais en côte » non : à l'envers c'est une
    descente. Une répétition en côte consomme toute la récup pour
    redescendre, ce n'est pas la même figure et il faut la traiter à part.
  - **De la route au-delà du segment**, et c'est tout ce qu'on demande à la
    récup (mainteneur, 13/09 : « en récup, village, croisement etc. c'est
    pas grave ; il faut de la route au-delà du segment »). **Aucune
    évaluation de terrain pendant une récup** : ni village, ni carrefour,
    ni revêtement, aucune pénalité. La seule question est mécanique — la
    moitié de la récup sert à dépasser le segment : 4 min à 25 km/h
    ≈ 800 m roulables après sa fin ; 1'30 ≈ 300 m.
  - **Le demi-tour doit être faisable.** Petite route oui ; départementale
    passante non, pénalité supplémentaire.
- **Les parties non contraintes sont élastiques** (mainteneur, 13/09 :
  « l'échauffement peut durer plus longtemps, ainsi que le retour au calme,
  on va dire 15-20 % pour trouver la zone »). C'est la variable
  d'ajustement principale : sur 1h d'échauffement, +20 % donne 6 km de jeu,
  donc on ne cherche plus un bon couloir **au** km 30 mais **entre** les
  km 28,5 et 36. Barème **corrigé par le mainteneur** (13/09, « y a la Z2
  début et la Z2 fin qui change ») : **seules** la Z2 d'échauffement et la
  Z2 de retour au calme sont élastiques, de −5 % à +20 %. **Toutes les
  récupérations sont fixes**, courtes comme longues, y compris les 45 min
  de Z2 au milieu de « Durabilité » : elles font partie de la prescription.
  Durée des blocs jamais modifiée.

  Les deux leviers ont des rôles distincts :
  - **Z2 de début = placement.** L'allonger décale toute la partie
    contrainte plus loin sur le tracé ; c'est le seul moyen de faire
    coulisser les blocs jusqu'à un bon couloir.
  - **Z2 de fin = absorption.** Elle ne place rien : elle ramène à la
    maison une fois le dernier bloc fini, quelle que soit la distance
    restante. C'est elle qui referme la boucle.

  La recherche devient donc : pour chaque candidate, faire varier la Z2 de
  début dans sa fenêtre, mesurer la qualité du terrain sous chaque bloc,
  garder le meilleur décalage ; la Z2 de fin s'ajuste et la durée totale
  annoncée avec elle.
- **L'échauffement fixe où chercher.** 1h d'échauffement place le premier
  bloc vers le km 30 ; la seconde série de « Durabilité » vers le km 65.
  C'est une contrainte **géométrique** sur la forme de la boucle, pas
  seulement sur sa qualité.

**Comment on teste, sans attendre une sortie réelle (décision du 13/09).**
Validation rétrospective sur des séances déjà faites dehors : « 4x8 SV1
outdoor » du 22/04/2026 sur 61 km et « 2x20' + 4x3' » du 25/04/2026 sur
63 km. On relit où les blocs sont **réellement** tombés, et on mesure si
l'évaluateur de terrain aurait noté ces emplacements comme bons. Trop
sévère s'il les rejette ; trop permissif s'il note aussi bien un tronçon
que le mainteneur n'a jamais utilisé pour un bloc. C'est le critère
d'acceptation chiffré du lot.

**La carte est le livrable de vérification** (demande du mainteneur) : le
tracé, les blocs colorés là où ils tomberont, le profil d'altitude
dessous. On voit d'un coup d'œil qu'un bloc traverse un bourg.

**Une note, jamais un filtre** (« ça ne sera pas toujours possible d'éviter
les villages et les croisements »). Chaque emplacement de bloc reçoit un
score et un motif lisible, par exemple « bloc 3 : deux croisements, note
moyenne ». On garde la boucle la moins mauvaise et on dit ce qui cloche,
plutôt que de ne rien proposer. Hiérarchie des pénalités à calibrer sur les
sorties réelles : une descente longue coûte plus qu'un carrefour.

Reste à préciser au lancement : bornes chiffrées des catégories de tenue
(Q3, réglables à l'usage) et option pour un départ autre que la maison —
**`--adresse-depart`**, nom réservé par Q15 (l'option annoncée ici sous le
nom `--depuis` était trop proche de `--depart`).

### Sprint 5 — Le vent, la séance visible, les trois propositions **[livré le 16/09/2026, fusionné]**

Une page HTML autonome, écrite sur le disque et ouverte dans le navigateur.
Aucun serveur, aucun compte, aucune base : tout le calcul existe déjà, on
ajoute le rendu. Dedans : la météo par direction en grille, les boucles
proposées sur carte avec les blocs de la séance à leur place, la tenue, et
le GPX à télécharger pour le partager vers Garmin Connect depuis le
téléphone. Plus le confort d'usage : `--adresse-depart` pour partir
d'ailleurs (Q15),
noms de fichiers et résumés soignés, mémoire de ce qui a été proposé.

**Trois propositions contrastées, et le cycliste choisit** (idée du
mainteneur, 13/09). Aujourd'hui `sortie` classe N candidates et retient la
première. À la place : **trois** options, et c'est lui qui tranche. Le point
qui fait la valeur de l'idée : trois propositions ne servent à rien si elles
se ressemblent, et les trois premières d'un même classement se ressemblent
souvent. Il faut donc les choisir **contrastées**, chacune meilleure sur un
axe différent — la plus sèche, la meilleure pour les blocs, la plus calme,
la plus courte — avec en une phrase ce qui la distingue des deux autres, et
sa carte. Mécaniquement : on génère plus de candidates qu'aujourd'hui, on
les note sur plusieurs axes, et on retient trois représentants éloignés les
uns des autres plutôt que le sommet d'un tri unique.

**Pourquoi cette page et pas l'hébergé tout de suite** : elle est la
maquette du futur front. Le jour où l'API existera, la même page sera
servie par le serveur au lieu d'être écrite sur le disque. Et le cœur
produit se stabilise à peine ; chaque changement de sortie se paierait
deux fois.

**Ce que le sprint a réellement contenu** (16/09/2026) — il a débordé de son
esquisse, et c'est le débordement qui a le plus rapporté :

- **L5.1** le vent dans le placement. Un bloc de 20 min à 210 W fait 9,18 km
  vent de face contre 13,28 km vent de dos : 4,1 km d'écart sur un bloc qui
  en fait 11. Validé sur 161 sorties, erreur du modèle de 1,063 à 0,993 m/s,
  et 1,445 avec le vent retourné — le contrôle qui prouve le signe.
- **L5.2** la séance entière visible (Q13), avec un compteur kilométrique
  distinct de la position sur le tracé.
- **L5.3** trois propositions contrastées — deux seulement quand les
  candidates ne le sont pas, et la commande dit pourquoi.
- **L5.4** la page du jour, forme tranchée en Q18.
- Les flèches de vent, pour que le lot le plus subtil du sprint devienne
  vérifiable à l'œil.

**Six défauts trouvés hors périmètre, tous en regardant de vraies sorties**,
aucun par un test :

1. **Les feux perdus à l'élagage** — `antennes._resegmenter` reconstruisait
   les tronçons sans leurs `node_tags` : toute candidate perdait ses feux et
   passages piétons avant d'être notée. 2,43 sans un carrefour contre 22,51
   avec quatre feux. Même faute que `cout_km` au sprint 3, au même endroit.
2. **Le dimensionnement à moitié** — une étape « libre » comptait zéro
   kilomètre : 35 km demandés pour une sortie de 67.
3. **Les ralentisseurs invisibles** — clé `traffic_calming`, jamais lue.
4. **Les rafales jetées** — téléchargées à chaque appel, abandonnées avant
   le tracé.
5. **`_Terrain`** levait `ZeroDivisionError` sur un tracé dégénéré.
6. **Le profil d'altitude** superpose les blocs après un demi-tour (ouvert).

**Trois corrections de doctrine ou de cadrage, dont deux de mes propres
erreurs** : les routes connues promues en doctrine comme instrument de mesure
et jamais critère ; Open-Meteo qui décompte par coordonnée et non par requête
(un `boucle` coûte ~150 appels, pas 10) ; et « éloignées » qui n'était pas
défini dans le contrat L5.3 — trou relevé par le testeur adversarial.

**La mesure qui a le plus appris** : le mainteneur roule 2,91 marqueurs
urbains par kilomètre contre 1,50 sur les boucles proposées. Non par goût —
« parce que je ne connais pas les routes de contournement ». Ses sorties ne
sont donc pas la cible à imiter mais la référence à battre, et c'est la
validation la plus concrète de la règle de doctrine écrite le même jour.

**Ce que le sprint a pris au sprint 7, et pourquoi** (16/09/2026) — le
mainteneur avait besoin de la page **sur son téléphone**, pas dans son
navigateur de bureau. Une page écrite sur disque ne l'atteint pas. Deux lots
non prévus ont donc été tirés du sprint 7 :

- **La mise en service** — cinq défauts qu'il a trouvés en regardant des
  cartes, aucun par un test : la carte de la page du jour n'appliquait pas
  la méthode Strava qu'elle annonçait, trois chiffres illisibles ou alarmants
  à tort, la météo perdue à J+2 et J+3 par un « hors de portée » pris pour
  un « hors du domaine », le GPX qui atterrissait dans le dépôt.
- **L'hébergé minimal** — pas l'API du sprint 7 : le même binaire, lancé une
  fois par jour dans un conteneur, et un serveur statique de 100 lignes
  derrière une authentification basique. **Déployé sur son Coolify le
  16/09/2026**, à son accord explicite, sur un domaine à lui.

C'est un débordement de sprint figé, contraire à la règle de cadence — acté
par le mainteneur en connaissance de cause, parce que le sprint 6 est du
dogfooding et que le dogfooding sans la page sur le téléphone n'a pas lieu.

**Neuf mesures sur son historique de 162 sorties**, demandées au fil de
l'eau, qui ont déplacé le produit plus que le code : le trafic estimé évité
à 54 % de l'attendu, les séances à blocs qui prennent trois fois moins de
départementales, l'absence de tout signal entre blocs et récupérations sur
les carrefours (un résultat nul, et c'en est un), et la densité urbaine
radiale sur quatre villes qui dit que **le produit ne rend pas le même
service partout** — aux Lilas, la densité de feux ne retombe jamais à moins
de 30 km.

### Sprint 6 — Dogfooding **[cap fixé par le mainteneur]**

Pas de nouvelle fonctionnalité. Le mainteneur s'en sert **pour de vrai**,
tous les jours de sortie, pendant plusieurs semaines. On mesure ce qui
cloche et on corrige : boucles refusées sur le terrain, blocs mal placés
constatés au retour, tenue à côté de la plaque, temps prédits faux, GPX
que l'Edge n'aime pas. Le livrable est une liste d'écarts entre ce que
l'outil annonce et ce qui s'est passé, et leur correction. C'est ce sprint
qui dit si le produit tient.

#### Les lots de correction, cadrés le 17/09/2026

La campagne de mesure du 17/09 ([[Q51]] dans `questions_mainteneur.md`) a
produit la première moitié du livrable de ce sprint : **la liste d'écarts**,
chiffrée sur les vraies données. Ce qui suit en est la seconde moitié, la
correction. Ce n'est pas un élargissement du cap.

**Les écarts se disent en minutes sur une boucle de 2 h**, pas en watts — c'est
l'unité que le produit sert, et c'est celle des critères d'acceptation.

| lot | gain mesuré | coût |
|---|---|---|
| **L6.1 — le modèle cesse d'être périmé** | | |
| fenêtre glissante sur la puissance d'endurance | **9 min** | aucun modèle à changer |
| masse datée par sortie | 5 à 9 W, **qui dérive** | la série existe côté Intervals |
| **L6.2 — la calibration identifiable** | | |
| Crr figé par surface, CdA seul ajusté | ~~lève la dégénérescence~~ **réfuté (nuit du 17/09)** | invalide `calibration.json`, revalidation |
| CdA saisonnier (vêtements) | ~~**5 min**~~ **≈ 1 min, un seul vélo** | ~~dépend du précédent~~ **indépendant** |
| **L6.3 — le bug de lecture TCX** | neuf fichiers illisibles | un après-midi, indépendant |

**Ordre recommandé et pourquoi — périmé, voir la correction ci-dessous.**
L6.1 d'abord, en un seul lot : ses deux corrections disent la même chose — le
modèle tourne sur des valeurs figées alors que le cycliste change. Neuf
minutes sur quatorze, sans toucher à la physique. L6.2 ensuite, et c'est un
vrai lot : nouvelle signature de `calibrer`, ancien fichier de calibration
jeté, les 12 W à revalider, et la phrase du 16/09 de la docstring à reprendre.
L6.3 quand ça arrange.

**Correction du 17/09 (soir), avant tout code écrit.** Le tableau ci-dessus
vient de la campagne sans capteur ; rejouée sur la puissance **mesurée** du
mainteneur (« Correction du 17/09 (soir) — la mesure réfute une partie de
[[Q51]] » dans `questions_mainteneur.md`), elle ne tient plus :

- la **fenêtre glissante** n'apporte rien au mainteneur — la constante
  actuelle (`puissance_endurance_pct × ftp_w`) est déjà à l'optimum, l'écart
  mesuré est sous le plancher de bruit ; les neuf minutes valent pour le monde
  sans capteur, pas pour le monde mesuré du mainteneur ;
- la **masse datée par sortie**, seule, **dégrade** la validation : dès que
  la masse globale est corrigée, l'ajustement de Crr part en butée (la
  dégénérescence de L6.2) et absorbe l'erreur autrement. La masse datée a
  besoin du Crr figé de L6.2 comme **préalable**, pas comme suite.

**L'ordre s'inverse donc : L6.2 avant L6.1.** Aucune ligne de code n'a été
écrite pour L6.1 sur cette base — l'écrire aurait livré soit un lot neutre
(fenêtre glissante), soit une régression mesurée (masse datée seule), ce que
la règle absolue 4 interdit de présenter comme un gain. Décision de
séquencement à reprendre avec le mainteneur avant de rouvrir L6.1. Les
« 5 minutes » de CdA saisonnier de L6.2 viennent de la même campagne
sans-capteur et demandent la même revérification sur la puissance mesurée
avant d'être budgétées.

**Correction du 17/09 (nuit), avant tout code écrit — L6.2 tombe à son tour.**
La revérification demandée ci-dessus a été faite sur la puissance **mesurée**
(« Correction du 17/09 (nuit) — le remède de [[Q9]] est mesuré, et il dégrade »
dans `questions_mainteneur.md`, 99 sorties RCR et 35 BMC, validation par date).
Elle réfute la première correction du lot et redimensionne la seconde :

- **Crr figé par surface, CdA seul ajusté : régression mesurée.** Le balayage
  du Crr imposé est **monotone**, sans optimum intérieur : le meilleur Crr
  imposé est la borne haute 0,012, le Crr de VTT que le remède devait faire
  disparaître. Un Crr de bitume (0,004 à 0,005) coûte **+3,7 à +4,4 min sur
  2 h** et dégrade 22 sorties de validation sur 25. Le CdA effectif
  **n'absorbe pas** le Crr figé, contrairement à ce qu'annonçait le commit
  `2741984` : la résistance totale à 27 km/h tombe de 18,04 à 15,78 N et le
  modèle devient systématiquement trop rapide. Rejoué à 93 kg, même classement
  — figer le Crr n'est donc pas non plus le préalable de la masse datée.
- **CdA saisonnier : réel, mais 1 min et non 5, et sur un seul vélo.** Le
  paramètre est stable et bien signé (CdA d'hiver +10 % aux trois partages de
  validation), le test apparié favorable (17↑/8↓), le gain médian +0,8 pp, soit
  **≈ 1 min sur 2 h** — pas 5. Sur le BMC l'effet est nul (+0,2 %) et
  **non mesurable** (ses sorties de validation sont toutes estivales). Et il
  **ne dépend pas** de la correction précédente : il se mesure sur le schéma
  d'aujourd'hui, Crr libre et partagé.

**Les deux lots du sprint sont donc à recadrer, pas à exécuter.** Aucune ligne
de code de calibration n'a été écrite pour L6.2 : livrer sa première correction
aurait livré une régression mesurée. Sa seconde correction survit seule, avec un
gain sept fois plus petit qu'annoncé et un périmètre d'un seul vélo — la réécrire
seule est une repriorisation, pas l'exécution du lot cadré, et quatre questions
de produit la bloquent (découpage de la saison, CdA servi à la prédiction,
format de `calibration.json`, vélo où l'effet est nul). Elles sont posées en fin
de `questions_mainteneur.md`.

**Critères d'acceptation** (règle absolue 4) : pour L6.1 et L6.2, l'écart entre
durée prédite et durée réelle sur les vraies sorties du mainteneur, mesuré
avant et après, en minutes. Pour L6.3, les neuf TCX refusés se lisent.

**Ce qui reste hors de ce sprint.** L'import par lien ([[Q48]]), le réglage
unique et sa boucle de correction ([[Q52]]), l'estimation sans capteur comme
valeur initiale ([[Q49]], [[Q51]]) et la zone 2 ([[Q50]]) appartiennent au
**sprint 8**, dont le texte les avait anticipés sans les nommer : « valeurs par
défaut qui marchent sans calibration (le nouveau n'a pas d'historique) […] sans
calibration personnelle, le modèle doit tourner sur des paramètres génériques
et le dire ». Rien de tout cela ne remonte ici.

**Et ce que ce sprint réclame toujours.** Les écarts ci-dessus viennent d'un
agent qui a rejoué l'historique, pas du mainteneur sur la route. C'est une
mesure solide, mais ce n'est pas celle que le cap demande : un GPX que l'Edge
refuse, un bloc mal placé constaté au retour, une boucle refusée sur le terrain
ne se trouvent qu'en roulant, plusieurs semaines durant.

#### Clôture du sprint 6 — 17/09/2026

**Ce que ce sprint a livré n'est pas ce qu'il avait annoncé, et c'est son
résultat.** Sur les quatorze minutes de gain de la table ci-dessus, aucune
n'a survécu à la mesure sur les vraies sorties du mainteneur. Trois lots se
sont arrêtés **avant d'écrire du code**, chacun parce que la mesure exigée
par la règle absolue 4 réfutait sa propre prémisse :

| correction | annoncé | mesuré | verdict |
|---|---|---|---|
| fenêtre glissante (L6.1) | 9 min | écart sous le bruit | **réfutée** |
| masse datée (L6.1) | 5 à 9 W | dégrade seule | **suspendue** |
| Crr figé par surface (L6.2) | lève la dégénérescence | −3,7 à −4,4 min | **réfutée** |
| CdA saisonnier (L6.2) | 5 min | ≈ 1 min, un seul vélo | **redimensionnée** |
| lecture TCX (L6.3) | 9 fichiers illisibles | 9 fichiers lus | **livrée** |

**La cause commune** : les chiffres venaient d'une campagne menée sur la
chaîne *sans capteur* (FC → zone → physique), appliqués à un cycliste qui
porte un capteur. Ce qui se corrige chez quelqu'un dont la constante est
fausse ne peut rien apporter à quelqu'un dont elle est déjà juste.

**Le livrable réel du sprint 6**, et il tient : une liste d'écarts chiffrée
sur 162 sorties, trois réfutations mesurées et documentées, le correctif de
lecture TCX, et un registre de questions remis en phase avec le code. Les
mesures sont dans `questions_mainteneur.md` (« Correction du 17/09 (soir) »
et « Correction du 17/09 (nuit) ») ; elles valent pour la suite, puisque le
monde sans capteur du sprint 8 est justement celui où ces gains existent.

**Ce que le cap réclame toujours** : le dogfooding sur la route, plusieurs
semaines. Il est acté comme **exigence permanente hors sprint** plutôt que
comme condition de clôture — un GPX que l'Edge refuse ou un bloc mal placé
constaté au retour ne se trouvent qu'en roulant.

**Reporté, avec son porteur** : le CdA saisonnier (≈ 1 min) attend quatre
arbitrages produit listés en fin de `questions_mainteneur.md`. La fenêtre
glissante, elle, n'est pas abandonnée : elle **change de destinataire** et
rejoint le sprint 8, où le cycliste sans capteur a bien une constante fausse
à corriger.

---

### Sprint 7 — L'hébergé **[esquissé — son premier étage est livré, voir sprint 5]**

API au-dessus du même cœur, puis front web servi par elle, puis comptes
avec authentification déléguée Google (doctrine §10). Postgres, stockage
d'objets pour les fichiers, isolation par utilisateur vérifiée côté
serveur, cache météo mutualisé (le quota Open-Meteo devient un sujet ici,
pas avant).

#### Lots figés le 17/09/2026 (repriorisation de fin des sprints 5 et 6)

Le cap ne bouge pas : l'hébergé. Son premier étage — l'API et le front — est
arrivé avec le cycle discovery/UX. Ce qui reste :

- **L7.1 — la page du jour servie, plus écrite sur le disque.** C'est la
  condition que [[Q22]] posait sans pouvoir la lever : tant que la page vit
  sur le disque du Mac, télécharger le GPX ne met rien sur le compteur.
  *Acceptation* : le mainteneur ouvre la page depuis son téléphone et envoie
  le GPX à Garmin Connect par le partage système, sans passer par le Mac.
- **L7.2 — comptes et isolation.** **Comptes chez nous, sans mot de passe**
  (doctrine §10.2, révisée le 16/09 et reconfirmée par le mainteneur le
  17/09) : demande d'accès modérée à la main, lien d'invitation à usage
  unique, puis passkey WebAuthn pour ne plus dépendre de la boîte mail.
  Google et Apple viennent en **V2, en plus et non à la place** — la
  modération est native ici, et l'écran d'entrée nous appartient.
  Isolation par utilisateur **vérifiée côté serveur**.
  *Acceptation* : `tests/api/test_api_isolation_proprietaire.py` existe déjà
  et passe contre le service réel, pas seulement contre un bouchon.
- **L7.3 — Postgres, stockage d'objets, cache météo mutualisé.** Le quota
  Open-Meteo devient un sujet ici, pas avant.
- **L7.4 — le TOML du serveur.** [[Q35]] (quelles sections sont communes au
  service et lesquelles appartiennent au cycliste) et [[Q36]] (l'étape
  « identité » de l'assistant) sont à trancher avant d'écrire ce lot.

**Les sept promesses des maquettes** ([[Q37]], réponses en [[Q40]] et [[Q41]])
se répartissent entre L7.1 et L7.2 selon qu'elles tiennent à l'affichage ou au
compte. Aucune n'est un lot à elle seule.

#### Clôture du sprint 7 — 21/09/2026

**Le paragraphe L7.2 ci-dessus est périmé.** Il se corrige comme la « Doctrine
d'affectation des modèles » l'a été le 15/09, plus haut dans ce fichier :
l'ancien texte se cite, se disqualifie, et ne se réécrit jamais en silence.

Il annonce « **Comptes chez nous, sans mot de passe** […] demande d'accès
modérée à la main, lien d'invitation à usage unique, puis **passkey WebAuthn**
pour ne plus dépendre de la boîte mail ». Trois de ces quatre promesses ne
tiennent plus, tranchées par le mainteneur les 18 et 19/09/2026 (doctrine
§10.2, révisée aux deux dates) :

- « **sans mot de passe** » → le compte porte **un moyen d'authentification
  dont la forme est ouverte**, et ce moyen est aujourd'hui un **mot de passe
  haché au scrypt, avec un sel par compte**
  (`src/ourouler/api/comptes.py:374-391`, constantes `comptes.py:141-147`),
  vérifié en temps constant (`hmac.compare_digest`, `comptes.py:408`). Ce que
  la doctrine refuse n'a jamais été une forme, c'est **le secret en clair** —
  base, journal, `repr`, message d'erreur.
- « **demande d'accès modérée à la main** » → il n'y a **pas de guichet**.
  L'entrée est sur invitation *uniquement*, définitivement, y compris pour la
  version publique et pour le compte du mainteneur lui-même, sans trappe
  d'amorçage.
- « **passkey WebAuthn** » → **rien de tel n'est écrit, et c'est voulu.** Le
  secret est rangé derrière deux colonnes — une qui nomme la méthode, une qui
  porte le secret — pour qu'une passkey s'ajoute sans changer le schéma ; le
  code n'en écrit pas l'ombre.

Ce qui, dans ce paragraphe, **tient toujours** : l'invitation à usage unique,
l'isolation vérifiée côté serveur, et Google puis Apple en V2, en plus et non
à la place. Ce qui s'y ajoute : la session est un **cookie**
(`src/ourouler/api/session.py:150`, `SessionParCookie`).

**Lot par lot.**

- **L7.1 — la page du jour servie : écrit, et non vérifié** au sens de la
  règle absolue 4. Le front est servi par l'API
  (`src/ourouler/api/application.py:363`, montage `StaticFiles`, repli SPA
  `application.py:318-322`) ; le GPX est rendu à la demande sans jamais
  toucher le disque (`src/ourouler/api/routes.py:1126-1150`) ; le **partage
  système** mobile est là, `navigator.share` / `navigator.canShare`
  (`front/src/ecrans/Proposition.tsx:152-183`), avec repli nommé sur le lien
  de téléchargement (`Proposition.tsx:422`) quand le navigateur ne sait pas
  partager un fichier. **Mais l'acceptation du lot dit « le mainteneur ouvre la
  page depuis son téléphone et envoie le GPX à Garmin Connect par le partage
  système », et ce geste n'a été vu réussir sur aucun téléphone réel** : rien
  dans le dépôt n'en porte la trace, et un `navigator.share` vert sous jsdom ne
  dit rien de ce qu'iOS accepte. Le lot est donc **non vérifié**, en toutes
  lettres — pas « probablement bon ».

- **L7.2 — comptes et isolation : livré** (PR #20), en quatre sous-lots.
  **A**, le socle : invitation, compte, moyen d'entrer, avec l'unicité **portée
  par la base et non par le code** — `ON CONFLICT ((lower(email))) DO NOTHING
  RETURNING` (`src/ourouler/api/comptes.py:483-485`) et la consommation en un
  seul `UPDATE … WHERE … consomme_le IS NULL … RETURNING`
  (`comptes.py:574-578`), exactement ce que le mainteneur avait exigé le 18/09
  (« sinon catastrophe »). **B**, la commande `ourouler inviter`
  (`src/ourouler/cli.py:906-937`), dont le lien s'affiche toujours et dont le
  courriel n'est qu'un extra. **C**, entrer/revenir/sortir : la troisième
  classe de `session.py` (`SessionPersonnelle:93`, `SessionHebergee:119`,
  `SessionParCookie:150`). **D**, la table de correspondance
  `comptes_proprietaires` (`src/ourouler/api/migrations/0001_comptes.sql:122-127`),
  celle que la doctrine §10.2 désigne comme « **elle** qu'on efface ».
  L'acceptation est tenue, et au-delà : le balayage d'isolation ne couvre pas
  un échantillon mais **toutes** les routes de données, et il échoue si une
  route neuve échappe au balayage
  (`tests/api/test_api_isolation_proprietaire.py:1236`, `:1364`, `:1405`), ou
  si une route de données répond sans session (`:1502`). [[Q58]] a corrigé en
  route la faiblesse de ce filet — il vérifiait la **forme** de la clause, pas
  son **effet** — en plantant une sentinelle sous le propriétaire local.

- **L7.3 — Postgres, stockage d'objets, cache météo mutualisé : un tiers
  fait.** Postgres existe (`src/ourouler/api/base_de_donnees.py`) mais **ne
  porte que les comptes, les invitations et les sessions** : les profils
  restent des fichiers JSON par propriétaire
  (`src/ourouler/api/depots.py:274-320`), le cache d'activités reste SQLite
  (`src/ourouler/activites/cache.py:16`), les routes apprises aussi. Le
  stockage d'objets **n'existe pas** : `DepotFichiers` prend un `Path` et écrit
  sur le disque du serveur (`src/ourouler/api/depots.py:427`, `:449-454`), là
  où la doctrine §10.2 promet « un stockage S3-compatible, un préfixe par
  utilisateur ». Le **cache météo mutualisé n'est pas commencé** pour la
  génération de parcours : la route construit un `ClientOpenMeteo` nu
  (`src/ourouler/api/routes.py:127`) ; le seul cache partagé existant
  (`PROPRIETAIRE_PARTAGE`, `src/ourouler/proprietaire.py:33-39`) sert
  l'**archive** météo de la calibration hors ligne
  (`src/ourouler/connecteurs/openmeteo_archive.py:97-115`), pas les prévisions
  du jour.

- **L7.4 — le TOML du serveur : à moitié.** Ce qui est fait, et testé : le
  découpage en **trois tiers** de [[Q35]], **champ par champ** pour le tiers 2
  — `boucle` n'ouvre que `sens`, `seance` que `position_zone`
  (`src/ourouler/api/depots.py:74-88`), `calibration` reste au serveur malgré
  son nom trompeur, `evitements` rejoint `velos` dans les listes qui se
  remplacent en entier (`depots.py:95`), et `historique_depuis` devient un
  champ scalaire à la racine (`depots.py:102`,
  `CHAMPS_RACINE_MODIFIABLES`). Le tout gardé par
  `tests/test_api.py:924-1037`, qui vérifie les trois tiers dans le même test
  et refuse `boucle.candidates` tout en acceptant `boucle.sens`. `tenue`
  appartient au tiers 2 dans le modèle de données mais son édition attend la
  V2, volontairement absente — le mainteneur l'avait dit (« même ça attend la
  V2 »). Un bug adjacent est parti avec : `historique_depuis` était écrit
  **sous** `[boucle]` dans `config.example.toml`, donc lu comme
  `boucle.historique_depuis` et silencieusement ignoré ; il est remonté à la
  racine avec le piège expliqué (`config.example.toml:5-12`).

  **Ce qui manque, et sa raison exacte.** [[Q35]] demandait aussi « le refus de
  finaliser l'embarquement tant que le tiers 3 n'est pas complet — avec un
  message qui nomme ce qui manque ». Il n'est **pas** écrit, et l'agent qui a
  tenu ce lot a cherché où le poser avant de renoncer : **rien, aujourd'hui, ne
  distingue un profil neuf en cours d'embarquement d'un profil ancien
  légitimement incomplet.** Poser la garde sans cette distinction casse soit le
  tunnel d'embarquement lui-même, qui écrit partiellement et volontairement
  (`front/src/ecrans/Assistant.tsx`, un arbre qui branche depuis le 19/09), soit
  tous les profils antérieurs à la règle. C'est un **manque d'architecture à
  nommer**, pas une solution à deviner : il faut un état d'embarquement, et
  personne ne l'a encore décidé. Le seul contrôle existant est tardif et
  technique — `ErreurProfilAbsent` levée au moment où une route calcule
  (`src/ourouler/api/depots.py:237-249`), avec un message qui parle de
  `PATCH /api/v1/profil` et de `ourouler api` à quelqu'un qui n'a pas écrit le
  code (`depots.py:163-177`).

- **Les cinq lots du contrat `docs/sprint7_contrat.md` : quatre tenus, un à
  moitié.** **L7.A** — `proprietaire()` lit une session injectable et rend 401
  sans elle (`src/ourouler/api/routes.py:188-215`) ; l'isolation est prouvée
  route par route, voir L7.2. **L7.B** — `GET /moi/export`
  (`routes.py:1339`) et `DELETE /moi` (`routes.py:1380`), avec l'acceptation
  vérifiée dépôt par dépôt (`tests/api/test_api_vie_privee.py:128`, `:252`,
  `:301`). **L7.D** — les trois points sont faits : table code → phrase
  (`front/src/composants/Echec.tsx:290-322`) **gardée par un test qui relit
  `CODES_PANNE` côté Python et échoue si un code neuf n'a pas de titre**
  (`front/tests/inventaire_erreurs.test.tsx:29-96`), « Direction » en double
  devenu « Point cardinal » (`front/src/ecrans/Demander.tsx:368` et `:421`), et
  les deux horloges réunies dans un composant unique
  (`front/src/composants/TempsEcoule.tsx:30-56`). **L7.E** — Dockerfile front+API,
  compose d'essai, variables documentées, sonde `/sante`
  (`src/ourouler/api/application.py:236-253`, `deploiement/api/`), et **rien
  n'a été déployé par un agent**, règle absolue 7 tenue.
  **L7.C est le lot à moitié** : l'altitude vient bien du tracé rerouté aux
  deux endroits qui comptent (`src/ourouler/boucle/commande.py:489-492`,
  `src/ourouler/apprentissage/routes.py:956-958`), avec repli explicite quand
  le reroutage échoue (`commande.py:453-481`) et la provenance dite —
  **mais seulement en ligne de commande** : `denivele_source` n'existe nulle
  part dans `front/src/` ni dans les vues de l'API, alors que le D+ chiffré est
  affiché à l'écran (`front/src/ecrans/Proposition.tsx:329-331`). Règle absolue
  5 tenue côté CLI, pas côté web. Et **le chiffre du contrat n'est gardé par
  rien** : « moins de 15 % des valeurs Strava corrigées sur Lacanau et Les
  Sables » a été mesuré le 18/09 et n'est rejoué par aucun test ni script de
  `tests/validation/` — le mécanisme est prouvé sur fixtures synthétiques, le
  chiffre annoncé ne l'est plus.

**Ce que la clôture corrige au passage, et qui passe de « trou » à « fait ».**

- **Le trou RGPD.** `DELETE /moi` effaçait profil, fichiers, cache et journal
  mais laissait **le compte, ses sessions ouvertes et son invitation intacts** :
  `comptes_proprietaires` existait depuis le 18/09 et le permettait, personne ne
  l'avait câblé. Corrigé le 21/09 (commit `23dd920`) :
  `DepotComptes.supprimer_compte_du_proprietaire`
  (`src/ourouler/api/comptes.py:621-650`) efface la ligne `comptes` en un seul
  `DELETE` sur sous-requête, et la cascade du schéma emporte invitation,
  sessions et correspondance ; `vie_privee.effacer_donnees` l'appelle **en
  dernier**, pour qu'une panne en amont laisse la porte ouverte plutôt que
  d'enfermer quelqu'un dehors avec ses données dedans
  (`src/ourouler/api/vie_privee.py:156-164`). Vérifié de bout en bout contre un
  vrai PostgreSQL local — mot de passe et session refusés après coup, routes
  apprises intactes (`tests/comptes/test_vie_privee_comptes.py:139-312`), puis
  attaqué sous dix angles par le testeur adversarial
  (`tests/comptes/test_vie_privee_comptes_adversarial.py`), dont la double
  suppression concurrente sur deux connexions (`:180`) et l'effacement
  interrompu (`:331`). Les dix tests sont verts **et éprouvés par mutation** :
  quatre mutations de l'implémentation les font rougir aux bons endroits, ce qui
  est la seule preuve qu'un test vert ne l'est pas pour rien.
  Une course adjacente est partie avec (commit `48ee912`) :
  `DepotProfils.supprimer_profil` et `JournalServices.supprimer` faisaient
  `is_file()` puis `unlink()` sans `missing_ok=True`, et deux `DELETE /moi`
  simultanés faisaient rendre 500 au second
  (`src/ourouler/api/depots.py:395`, `:794`).
- **Le découpage du TOML par tiers**, ci-dessus (commit `653fd6b`) — pour sa
  moitié faite.

**Dette nommée, datée, assumée.**

1. **Les fichiers bruts vivent sur le disque du serveur, pas dans un stockage
   d'objets** (`src/ourouler/api/depots.py:427`), alors que la doctrine §10.2
   promet du S3 avec un préfixe par utilisateur. Sans conséquence à trois
   comptes, insoutenable dès qu'un invité dépose une archive.
2. **Le cache météo mutualisé n'est pas commencé** — voir L7.3. La doctrine
   §10.1 le datait « au premier sprint de l'hébergé », qui est celui-ci.
3. **L7.1 n'a jamais été vérifié sur un téléphone réel** — voir plus haut. Dit
   en toutes lettres parce que c'est exactement le cas que la règle absolue 4
   prévoit.
4. **L7.4 est partiel** : le refus d'embarquement incomplet manque, faute d'un
   état d'embarquement qui distingue un profil neuf d'un profil ancien — voir
   plus haut.
5. **La provenance de l'altitude ne se dit pas à l'écran**, et le chiffre
   d'acceptation de L7.C n'est rejoué par aucun test — voir plus haut.

**Un point bloquant, mesuré le 21/09/2026 : le tiers 3 de [[Q35]] n'est pas
« jamais hérité » dans le code, il l'est seulement dans les commentaires.**

[[Q35]] dit du tiers 3 — `[depart]`, `[cycliste]`, `[[velos]]`, `[intervals]` —
qu'il est « **jamais hérité, jamais deviné** », et le lot L7.4 vient d'écrire
cette phrase dans `src/ourouler/api/depots.py:69-73`. Le code ne la tient pas,
et ça se mesure en trois lignes :

- `SocleTOML.config` fusionne la surcharge d'un propriétaire **par-dessus** le
  TOML du serveur (`src/ourouler/api/depots.py:209`). En mode hébergé, ce socle
  est déclaré **impersonnel** (`application.py:410-416`,
  `proprietaire=None`), donc `verifier_proprietaire` ne refuse plus rien : tout
  ce qu'un invité n'a pas surchargé, il l'**hérite**. Le TOML de déploiement
  fourni porte justement `[cycliste] masse_kg = 75, ftp_w = 250` et un
  `[[velos]]` générique (`deploiement/api/config.example.toml:18-26`) — un
  copain qui n'a pas touché l'écran FTP roule donc sur 250 W **présentés comme
  les siens**, ce qui est aussi le contraire du cap du sprint 8 (« des
  paramètres génériques, **et le dire** »).
- Pire pour `[depart]` : `_survoler_environnement` applique
  `OUROULER_DEPART_*` **après** la fusion et « présente, elle l'emporte
  toujours » (`src/ourouler/config.py:512-527` et `:563-565`). Or
  `deploiement/api/README.md:61-62` demande de poser ces variables en mode
  hébergé. **Conséquence mesurée** : un invité qui saisit son propre point de
  départ dans l'assistant reçoit un 200, sa surcharge est bien écrite sur
  disque — et `DepotProfils.config` lui rend quand même **le point de départ du
  serveur**. Sonde rejouée le 21/09 sur ce worktree, socle impersonnel +
  variables d'environnement : surcharge écrite `{'nom': 'Chez le copain',
  'latitude': 47.0, …}`, configuration relue `Depart(nom='Maison du
  mainteneur', latitude=48.111111, …)`.
- **Aucun test ne couvre ce chemin** : aucun ne construit un `SocleTOML` avec
  `variables=` **et** plusieurs propriétaires ; toute la suite tourne avec un
  environnement vide, ce qui explique 4 830 tests verts. Le balayage
  d'isolation, lui, vérifie qu'une donnée de A ne va pas chez B
  (`tests/api/test_api_isolation_proprietaire.py:1123`, qui ne surcharge que
  `depart.nom`), jamais que celle du **serveur** ne va chez personne.

Ce n'est pas une régression de ce lot — le mécanisme est antérieur, et
`_refuser_une_base_personnelle` (`application.py:426-449`) couvre déjà le cas
le plus grave, la clé Intervals du mainteneur servie à tout le monde. Mais le
point de départ est, dit la doctrine elle-même, « son domicile, le plus
sensible du fichier », et c'est exactement la fuite qui avait ouvert [[Q35]].

Vérifié le jour même sur le déploiement Coolify réel (`ourouler-api`) : la
variable en service porte `OUROULER_DEPART_NOM=Rennes`, un point générique —
**rien de personnel n'était exposé au moment de la mesure**. Le mécanisme
restait néanmoins ouvert : il aurait servi la vraie adresse du mainteneur à
n'importe quel invité si ces variables l'avaient un jour portée, ce que
`deploiement/api/README.md` demandait explicitement de faire.

**Corrigé le 22/09/2026, dans la foulée plutôt que reporté** (le mainteneur a
préféré fermer avant de pousser). `SocleTOML.config` retire désormais les
quatre sections du tiers 3 (`depart`, `cycliste`, `velos`, `intervals`) du
socle serveur en mode hébergé, TOML et variables d'environnement compris ; le
refus de démarrage déjà posé pour `[intervals]` (`application.py`) s'étend
aux trois autres. Détail complet, y compris deux effets de bord mesurés en
intégrant ce correctif avec L7.4 et le RGPD-compte, dans [[Q66]].

**Une action reste due au mainteneur, hors du dépôt** (Q66a) : le service
hébergé en ligne ne redémarrera pas tel quel une fois cette branche
déployée. Avant de le faire : vider `OUROULER_DEPART_*` et
`OUROULER_INTERVALS_*` dans le panneau Coolify de `ourouler-api`, et
reconstruire `OUROULER_CONFIG_TOML_B64` sans `[cycliste]`/`[[velos]]` — rien
n'a été touché côté Coolify par cette correction, règle absolue 7.

**Un second trou, trouvé en corrigeant le premier, est également fermé**
(Q66b) : sans repli, la toute première requête d'un compte hébergé fraîchement
activé (ou réinvité après suppression RGPD) échouait avant même que
l'assistant d'embarquement puisse s'afficher pour la remplir —
`front/src/App.tsx` interroge `/profil` sans condition dès le premier écran.
`DepotProfils.config_ou_comblee` comble alors, et seulement en mode hébergé,
les trois champs sans lesquels aucune `Config` ne se construit
(`depart.latitude`/`.longitude`, `cycliste.masse_kg`) avec une valeur neutre
fixe — jamais écrite, jamais celle de quelqu'un de réel, jamais utilisée si
le propriétaire a déjà écrit sa propre valeur, même invalide. Dette assumée
et datée : une route de *calcul* appelée avant la fin de l'embarquement peut
tourner sur ce comblement plutôt que de refuser franchement — un résultat
sans queue ni tête, jamais une fuite, mais toujours pas le refus
d'embarquement incomplet que L7.4 n'a pas pu écrire (voir dette n°4
ci-dessus, inchangée).

État mesuré après ce correctif, suite complète : `uv run ruff check .` vert,
`uv run pytest -q` → **4838 passés**, 0 échec, 32 sautés, 5 xfailed.

---

### Sprint 8 — Prêt à inviter des copains **[cap fixé par le mainteneur]**

Le jalon d'ouverture. Un cycliste que le mainteneur invite doit pouvoir,
sans lui : créer son compte, renseigner son profil, brancher son
Intervals, obtenir une boucle qui tient la route, et ne jamais voir les
données d'un autre. Ce qu'il faut en plus de l'hébergé brut : parcours
d'accueil, valeurs par défaut qui marchent sans calibration (le nouveau
n'a pas d'historique), messages d'erreur compréhensibles par quelqu'un qui
n'a pas écrit le code, export et suppression de compte (RGPD), et un coût
maîtrisé par utilisateur. Sans calibration personnelle, le modèle doit
tourner sur des paramètres génériques et le dire.

#### Lots figés le 17/09/2026 (repriorisation de fin des sprints 5 et 6)

Le cap ne bouge pas. Ce sprint hérite du bloc **sans capteur** instruit le
17/09, et c'est ici que les gains réfutés au sprint 6 retrouvent leur sens :
le cycliste invité n'a ni capteur, ni historique, ni calibration.

- **L8.1 — importer son historique** ([[Q48]]). Trois plateformes, un seul
  parcours ; le fichier reste quand les API se ferment.
- **L8.2 — estimer la puissance sans capteur** ([[Q49]], [[Q51]]), **avec la
  fenêtre glissante** que le sprint 6 a écartée. Elle ne vaut rien chez un
  porteur de capteur dont la constante est déjà juste ; elle vaut ses neuf
  minutes chez quelqu'un dont elle est fausse. *Acceptation* : l'écart entre
  durée prédite et durée réelle, en minutes sur 2 h, sur des sorties sans
  capteur que le modèle n'a pas vues.
- **L8.3 — la zone 2 déduite de la fréquence cardiaque** ([[Q50]]). La FC
  étiquette la zone, elle n'entre pas dans la physique.
- **L8.4 — un seul réglage, deux visages** ([[Q52]]) et sa boucle de
  correction.
- **L8.5 — le parcours d'accueil** : valeurs par défaut génériques **qui se
  disent comme telles**, messages d'erreur lisibles par quelqu'un qui n'a pas
  écrit le code, export et suppression de compte (RGPD), coût maîtrisé par
  utilisateur. [[Q46]] — ce que le service a le droit d'apprendre des sorties
  de chacun — se tranche avant ce lot, pas pendant.

#### Clôture (partielle, et assumée comme telle) du sprint 8 — 21/09/2026

**Ce sprint se clôt sur ce qui est livré, pas sur ce qui était écrit.** Deux
des cinq lots partent ailleurs, nommément, et le cap n'est pas atteint. C'est
le même geste qu'à la clôture du sprint 6, où la fenêtre glissante « change de
destinataire et rejoint le sprint 8 » plutôt que de disparaître dans un
silence — sauf qu'ici, c'est elle qu'on renvoie une seconde fois.

**Lot par lot.**

- **L8.1 — importer son historique : jamais commencé.** Il n'y a ni connecteur
  Strava ni connecteur Garmin dans `src/ourouler/connecteurs/`, et rien nulle
  part ne sait ouvrir une archive de plateforme. Ce qui existe est d'un autre
  ordre : `Cache.indexer_dossier` parcourt un dossier et indexe les `.fit`,
  `.gpx`, `.tcx` qu'il y trouve (`src/ourouler/activites/cache.py:323-366`),
  derrière `ourouler inventaire --importer`
  (`src/ourouler/activites/commande.py:41-44`) — **une commande que l'API
  n'expose délibérément pas** (`src/ourouler/api/routes.py:12-16` : « des
  gestes d'administration que le mainteneur fait en ligne de commande »). Un
  invité n'a donc aujourd'hui **aucun** chemin vers son historique. L'écran
  `front/src/ecrans/Importer.tsx` ne comble pas ce trou et ne prétend pas le
  faire : il dépose une **séance** (`.ZWO`/`.MRC`, `Importer.tsx:96`), pas une
  sortie roulée. Ce qui a été produit sous ce lot est une **étude sans code** —
  ce que contiennent vraiment une archive Garmin et une archive Strava
  (`docs/services_externes.md:135-244`, commit `f64d64e`, aucun `.py` touché) ;
  elle vaut, et elle reste le point de départ du jour où le lot s'écrira.
  **Destination : sprint 9**, avec [[Q48]] pour cadre.

- **L8.2 — estimer la puissance sans capteur : fait, au sens que le mainteneur
  a tranché le 21/09.** Ce qui est là, et c'est la substance du lot : l'étage
  T4 de l'entonnoir ne pose pas un chiffre en l'air, il **inverse le modèle
  physique**. La personne déclare sa vitesse au compteur et son terrain
  (`front/src/ecrans/Assistant.tsx:77-96`), l'écran appelle
  `POST /profil/ftp/apercu` (`src/ourouler/api/routes.py:705-736`), et
  `ftp_pour_vitesse_compteur` retrouve par bissection sur le modèle — masse,
  CdA et Crr de littérature, dénivelé — la puissance d'endurance qui produit
  cette vitesse, puis remonte à la FTP par `position_zone`
  (`src/ourouler/seance/ecran_ftp.py:302-349`). C'est une estimation dérivée,
  pas une constante.

  **Deux choses qu'il faut dire quand même**, parce que le lot les annonçait.
  (1) La **fenêtre glissante** — ce que le sprint 6 avait explicitement renvoyé
  ici, « elle vaut ses neuf minutes chez quelqu'un dont la constante est
  fausse » — **n'est pas dans le code** : aucune occurrence dans `src/`, la
  seule fenêtre glissante du dépôt est un lissage d'altitude sans rapport
  (`src/ourouler/physique/calibration.py:355-378`). (2) Le **critère
  d'acceptation écrit n'a pas été mesuré** : « l'écart entre durée prédite et
  durée réelle, en minutes sur 2 h, sur des sorties sans capteur que le modèle
  n'a pas vues » n'existe nulle part. Le lot se clôt donc sur sa substance, pas
  sur son critère — et ça se dit, règle absolue 5. Le filet du dernier étage,
  lui, est honnête sur lui-même : `ftp_defaut = masse × 2,2 W/kg`
  (`src/ourouler/physique/litterature.py:241`, `ftp_defaut` ligne 250) porte
  en commentaire « **Non mesuré** », et [[Q65]] reste ouverte sur ce chiffre.

- **L8.3 — la zone 2 déduite de la fréquence cardiaque : écarté, et [[Q63]] dit
  pourquoi.** Sur les données du mainteneur, la réserve cardiaque n'est pas le
  remède espéré : sa Z2 réelle reste sous la convention dans les deux échelles
  et l'écart **s'aggrave** en passant à la réserve (3 points en dessous
  deviennent 10). Ce n'est ni son repos ni son maximum qui sont atypiques,
  c'est le rapport entre son cœur et sa puissance — exactement ce qu'aucune
  formule universelle ne devine chez quelqu'un qui arrive sans données. Le code
  est conforme à cet écart : la FC **étiquette** une consigne de séance, elle
  n'entre jamais en entrée d'un calcul physique
  (`src/ourouler/seance/zones.py:33-38`), et les traductions de consignes
  cardiaques restent signalées comme approximées
  (`src/ourouler/seance/intervals.py:415`). Le texte du plan ci-dessus en tient
  déjà compte correctement ; rien à corriger, seulement à confirmer.

- **L8.4 — un seul réglage, deux visages : le double visage est livré, la
  boucle de correction n'existe pas.** Le réglage unique est là, et il est
  bien unique : seul `position_zone` est stocké
  (`src/ourouler/seance/zones.py:1-31`, décision 7 — « on stocke la position
  dans la zone, jamais la valeur »), et il s'affiche des deux façons, en watts
  et en pourcentage de zone, avec un bouton qui écrit la position et non les
  watts (`front/src/ecrans/Reglages.tsx:170-177` et `:187-199`) — « si votre
  FTP change, tout suit ». **La boucle de correction, elle, manque.** La seule
  chose qui corrige un modèle à partir des sorties réelles est la calibration
  CdA/Crr, et elle n'est branchée que sur la ligne de commande
  (`src/ourouler/cli.py:592-609` → `src/ourouler/physique/commande.py:266-307`),
  explicitement hors de l'API (`src/ourouler/api/routes.py:11-16`). Rien ne
  réajuste tout seul le facteur de compteur, la FTP ou `position_zone` à partir
  de ce que la personne a roulé. Pour un invité sans accès à la ligne de
  commande du mainteneur, le réglage du premier jour est donc le réglage de
  toujours.

- **L8.5 — le parcours d'accueil : trois quarts.** Les valeurs génériques **se
  disent comme telles**, partout et pas seulement à un endroit —
  « Estimation générique, à partir de votre poids et de votre vélo seuls »
  (`front/src/ecrans/Assistant.tsx:55`), « mesuré sur vos sorties » /
  « supposé, faute de mesure » (`Assistant.tsx:735`,
  `front/src/ecrans/Demander.tsx:283`, `front/src/ecrans/Reglages.tsx:254`,
  `front/src/composants/TempsEcoule.tsx:83-86`), et la règle est écrite au
  cœur, pas seulement appliquée au front
  (`src/ourouler/physique/litterature.py:9-14`). Les **messages d'erreur** sont
  lisibles et gardés (`front/src/composants/Echec.tsx`, contrat
  `src/ourouler/api/erreurs.py:1-13`, test d'inventaire
  `front/tests/inventaire_erreurs.test.tsx:29-96`). L'**export et la
  suppression RGPD** sont désormais complets, et c'est ce lot-ci qui a fermé le
  dernier trou — voir la clôture du sprint 7 : `DELETE /moi` ferme aussi le
  compte, ses sessions et son invitation. [[Q46]], qui devait se trancher avant
  ce lot et non pendant, l'a bien été le 17/09. **Ce qui manque est le
  quatrième quart : le coût maîtrisé par utilisateur.** Il n'y en a aucun. La
  classe `Budgets` (`src/ourouler/api/adaptateur.py:218-263`) mesure un **temps
  d'exécution attendu** pour peindre une barre de progression, et le dit
  elle-même (« pas à facturer », `adaptateur.py:227-238`) ; le seul plafond du
  dépôt est global au serveur (`GENERATIONS_GARDEES = 20`,
  `src/ourouler/api/depots.py:539`). Aucun quota, aucune limite d'appels
  par personne — or la doctrine §10.1 chiffre ce poste : une `sortie` à cinq
  candidates coûte ~150 appels Open-Meteo décomptés, sur 10 000 par jour et par
  adresse IP, **et un service hébergé les additionne**.

**Ce que ce sprint a réellement contenu, et qui n'était pas au programme.** Le
temps est allé aux comptes et à l'écran, pas au bloc « sans capteur » : les
quatre sous-lots L7.2-A à D, la direction visuelle et son système de jetons,
la rose des huit directions, le vent dessiné sur le tracé, l'aperçu de la
semaine, le parcours d'accueil transformé en arbre qui branche plutôt qu'en six
étapes fixes (PR #22 et #23). C'est un débordement du même genre qu'au sprint 5
— et comme au sprint 5, c'est le débordement qui a rapporté, puisque sans
comptes il n'y avait personne à inviter. Mais il se paie ici, et le solde est
ci-dessous.

**Ce qui part, et où.** Rien ne disparaît dans un silence.

- **L8.1** (import d'historique) → **sprint 9**, avec [[Q48]].
- **La boucle de correction** — c'est-à-dire la fusion de ce qui reste de
  **L8.2** (la fenêtre glissante, et la mesure du critère) et de **L8.4** (le
  modèle qui se corrige sur les sorties réelles, « chemin 3 » de [[Q52]]) →
  **sprint 9**, en **un seul lot nommé**. Les séparer était l'erreur : le
  double visage sans la boucle donne un réglage qu'on pose une fois et qui ne
  bouge plus, et la fenêtre glissante sans la boucle n'a rien sur quoi
  glisser.
- **Le coût par utilisateur** (quart manquant de L8.5) → backlog, à cadrer avec
  le **cache météo mutualisé** de L7.3, dont il est la même question vue de
  l'autre bout.

**L'écart entre le cap et ce qui est livrable, dit sans l'arrondir.** Le cap
disait : « un cycliste que le mainteneur invite doit pouvoir, sans lui, créer
son compte, renseigner son profil, brancher son Intervals, obtenir une boucle
qui tient la route, et ne jamais voir les données d'un autre. » Trois de ces
cinq gestes tiennent : le compte, le profil, l'isolation. **Brancher son
Intervals** tient aussi, mais ne remplace pas l'historique — sans L8.1,
quelqu'un qui n'est pas sur Intervals n'a aucun moyen de donner ses sorties, et
la calibration ne pouvant se lancer que depuis la ligne de commande du
mainteneur, « sans lui » n'est pas vrai. **Obtenir une boucle qui tient la
route** tient, sur des paramètres génériques honnêtement annoncés — c'est le
vrai acquis du lot L8.2. Le « **ne jamais voir les données d'un autre** » a
été mesuré en défaut le 21/09 — le tiers 3 de [[Q35]] s'héritait encore du
socle serveur — et corrigé le 22/09 ([[Q66]]) : fermé dans le code, vérifié
que rien de personnel n'était exposé sur le déploiement en service au moment
de la mesure. **Une action reste due au mainteneur avant tout redéploiement**
(Q66a, hors du dépôt, règle absolue 7) : vider `OUROULER_DEPART_*` et
`OUROULER_INTERVALS_*` dans le panneau Coolify de `ourouler-api`, et
reconstruire `OUROULER_CONFIG_TOML_B64` sans `[cycliste]`/`[[velos]]`. Sans
ce geste, le service refusera simplement de démarrer (le refus voulu depuis
L7.A, étendu aux quatre sections du tiers 3) — pas de fuite silencieuse
possible, une panne visible au pire.

Sur les quatre gestes qui tiennent, un sprint 9 reste donc nécessaire avant
d'inviter pour de vrai : L8.1 (l'historique sans Intervals) est le seul
absent qui empêche encore « sans lui » d'être vrai.

---

**Ce que cette repriorisation ne range nulle part.** Trois fonctions de
qualité du tracé — [[Q29]], [[Q31]], [[Q32]] — n'entrent ni dans l'hébergé ni
dans l'accueil d'un nouveau venu. Elles sont posées en [[Q53]] avec trois
issues possibles ; aucune n'est tranchée, et elles n'ont pas de sprint.

### Sprint 9 — Inviter pour de vrai **[cap fixé par le mainteneur, cadré le 25/09/2026]**

Cadré à la demande du mainteneur : « refaire une passe du projet pour
finaliser et pouvoir inviter des gens », et « j'ai encore du mal avec le
modèle vélo » (`docs/sprint9_contrat.md`). Six lots, tous fusionnés sur
`sprint-9`.

#### Clôture du sprint 9 — 25/09/2026

**L9.1 — le modèle vélo : Crr par pneu, CdA cherché, porte à porte en
fourchette.** Codé le 25/09 (branche `l9-1-modele`), méthode issue de la note
du 23/09 (« le porte à porte ignore le relief de la boucle », ci-dessus) :
Crr fixé par la littérature selon la catégorie de pneu (`Velo.pneu`,
`src/ourouler/config.py:52,183-188`), seul le CdA est cherché
(`src/ourouler/physique/calibration.py`), sur le **temps en mouvement**,
apprentissage limité aux sorties sous 30 % de signal de groupe, fourchette du
porte à porte mesurée sur les **seules sorties de validation**. Mesuré :
RCR — CdA 0,378 (compensation, pas une mesure), MAE de validation 3,5 %,
biais −0,8 % (n=25) ; BMC — CdA 0,318, MAE 2,5 %, biais +1,2 % (n=9). Écart de
29,8 W à 30 km/h entre les deux vélos, recoupé sans modèle par
`ourouler comparer` (27-42 W mesurés). Fourchette écoulé/simulé validation :
RCR × 1,021 à × 1,099 (n=25) ; BMC en convention faute d'assez de sorties de
validation roulées seul (7 < 8 requis). Convention par défaut : × 1,02 à
× 1,14. **Un CdA calibré est un paramètre de compensation** (il absorbe entre
autres l'étalonnage unilatéral du capteur RCR) : il ne se compare ni à la
littérature ni d'un vélo à l'autre — c'est la correction que la contre-lecture
Fable (relecture de méthode) a fait porter au critère d'acceptation du
contrat, revu en conséquence le 25/09.

**L9.2 — importer son historique.** Dépôt de fichiers `.fit`/`.gpx`/`.tcx`
(et `.gz`) ou d'archive Strava/Garmin, en tâche de fond
(`src/ourouler/activites/import_archive.py`, `src/ourouler/api/imports_fond.py`,
`src/ourouler/api/taches_fond.py`), cloisonné par propriétaire, borné (taille,
nombre de fichiers, décompression, chemins, profondeur d'archive). Contre-lu
par Fable et durci en conséquence : le corps de la requête n'est jamais
accumulé en mémoire d'un bloc, un import refusé (session absente, serveur
occupé, quota épuisé) l'est **avant** la lecture du corps
(`src/ourouler/api/limite_corps.py`, `src/ourouler/api/garde_avant_corps.py`),
une suppression de compte annule les tâches de fond de ce compte et attend
qu'elles aient rendu la main avant d'effacer (`taches_fond.annuler_et_attendre`,
`api/vie_privee.py`), et les fichiers bruts importés sont rangés par compte
dans le cache (jamais mêlés entre propriétaires). **Ces fichiers bruts
conservés par compte sont un écart avec [[Q48]]** (« on jette le brut, on
garde le dérivé ») — posé sans trancher en [[Q67]], le 25/09/2026.

**L9.3 — le coût par utilisateur.** Cache mutualisé des prévisions Open-Meteo
(`src/ourouler/meteo/cache_previsions.py` : même point arrondi, même heure,
un seul appel pour tous les comptes qui le partagent) et quotas journaliers
réglables par compte (`src/ourouler/api/quotas.py`,
`src/ourouler/api/exploitation.py`) : 20 générations/jour, 100 consultations
météo/jour, 1 calibration/jour, 5 imports/jour par défaut. Refus lisible
`quota_atteint` (429).

**L9.4 — la calibration depuis l'écran.** `POST /calibrations` lance la même
`physique.commande.calibrer_velo` que `ourouler calibrer` — pas une seconde
implémentation — en tâche de fond, sous le même verrou que l'import
(`src/ourouler/api/calibrations.py`,
`front/src/composants/CalibrationVelo.tsx`). Préconditions dites avant le
clic, avec leur code (`velo_absent`, `ftp_absente`, `sorties_insuffisantes` —
au moins 10 sorties exploitables —, `pneu_absent`). *Vérifié sur les vraies
données du mainteneur* : sur 102 FIT importés depuis l'écran (100
exploitables), CdA 0,364, 182 W à 30 km/h, MAE 3,6 %, biais −1,8 % (n=25),
fourchette × 1,030 à × 1,110 — contre 0,378, 188 W, 3,5 %, × 1,021 à × 1,099
par `ourouler calibrer` sur le même historique ; l'écart tient à ce qu'un FIT
importé perd le nom Intervals de la sortie, et que les sorties nommées
« club » (écartées par la ligne de commande) passent le filtre de groupe à
30 % — voir le point de backlog ci-dessous.

**L9.5 — le mode d'emploi de l'invitation.** `docs/inviter.md`, remis à jour
dans ce lot de finition (25/09/2026) pour refléter L9.4 et L9.6 fusionnés
depuis sa première version.

**L9.6 — le compte de l'invité.** `reinitialiser` (mot de passe oublié d'un
compte déjà actif) et `retirer` (fermeture d'un compte hébergé, RGPD, même
chemin que `DELETE /moi`) en ligne de commande du mainteneur
(`src/ourouler/cli.py`, `src/ourouler/api/invitation_commande.py`,
`src/ourouler/api/retrait_commande.py`, `src/ourouler/api/comptes.py:644,679,836`).
Côté invité, le volet « Mon compte » de l'écran des réglages
(`front/src/ecrans/Reglages.tsx`, `MonCompteVolet`) : adresse, changement de
mot de passe, export et suppression RGPD (double confirmation, texte à
recopier) — ces deux dernières routes existaient côté API depuis le sprint 7
sans bouton pour les atteindre ; ce lot ferme ce trou-là.

**Lot de finition (25/09/2026, branche `l9-finition`), à la contre-lecture des
tâches de fond et de la garde du corps de requête.** Une seconde `DELETE /moi`
du même compte pendant qu'une première attend jusqu'à 120 s la fin d'une
tâche de fond refuse désormais tout de suite (`suppression_deja_en_cours`,
409) au lieu d'occuper un second fil du serveur pour rien
(`taches_fond.debuter_effacement`/`finir_effacement`,
`api/vie_privee.effacer_donnees`, `api/erreurs.py`, `Echec.tsx`,
`inventaire_erreurs.test.tsx`). `api/garde_avant_corps.py` déporte l'appel
bloquant à la base des comptes hors de la boucle d'événements
(`run_in_threadpool`) et traduit une base en panne en
`service_externe_indisponible` (502) plutôt qu'un 500 brut, vérifié par un
test qui mesure que deux appels concurrents ne se bloquent pas l'un l'autre.

**L9.7 — l'accueil de l'invité, joué dans un vrai navigateur (25/09/2026).**
Service hébergé monté en local (Postgres jetable, BRouter et Open-Meteo réels),
un invité joué de bout en bout : lien d'invitation, mot de passe, assistant,
trois boucles (« entre 1 h 44 et 1 h 56 porte à porte »), import de 30 FIT
réels par la route, calibration depuis Réglages, suppression du compte (zéro
sortie ni fichier restant, connexion refusée ensuite). Huit défauts vus à
l'écran, corrigés sur `l9-7-accueil` : l'étape Strava/Garmin qui disait
l'import « pas encore proposé » propose désormais le dépôt
(`composants/DepotHistorique.tsx`) ; le pneu demandé dans l'assistant ; le
poids du vélo à 8 kg affiché contre 9 kg annoncés (une seule constante) ; des
champs pré-remplis où la saisie s'ajoutait (« 7075 kg ») ; une erreur de
validation brute (« [cycliste] masse_kg = 7075.0 hors de [20, 300] ») devenue
« Votre poids doit être entre 20 et 300 kg » ; l'accueil sans Intervals qui
taisait le dépôt des sorties ; `?onglet=` ignoré au chargement ; le numéro de
rue obligatoire pour une place. **Le rejeu de ces corrections dans le
navigateur a trouvé une régression** — un vélo sans poids (`null`, désormais
possible) faisait tomber le récapitulatif et Réglages — corrigée et gardée par
`front/tests/velo_sans_poids.test.tsx`. Une instabilité reste au backlog :
sur 30 sorties importées, la calibration donne 167 W à 30 km/h, contre 188 W
sur tout l'historique en ligne de commande et 199 W sur 40 sorties (essai
L9.4) — à 10 sorties minimum, le chiffre bouge de ±15 W ; l'erreur de
validation affichée (4,9 % sur 7 sorties) le laisse deviner sans le dire.

**Restent au mainteneur, hors du dépôt (règle absolue 7) :**

- ~~L'action Q66a sur Coolify~~ — **faite**, vérifiée le 25/09/2026 en
  invitant pour de vrai depuis la prod (`ssh inflexion` + `docker exec` dans
  le conteneur `api-hqcrmxt0dvyxlgojgvqmwhsk-*`) : `OUROULER_DEPART_*` et
  `OUROULER_INTERVALS_*` sont vides dans le panneau Coolify de
  `ourouler-api`, et `OUROULER_CONFIG_TOML_B64` ne contient plus que
  `[meteo]`, `[cache]`, `[brouter]`, `[boucle]` — ni `[cycliste]` ni
  `[[velos]]`. [[Q66]] est close.
- Déclarer `pneu` dans sa propre configuration (`config.toml`,
  `[[velos]]`), puis relancer `ourouler calibrer` : sa calibration actuelle,
  en date du 25/09, est encore l'ancienne à deux paramètres libres (avant
  L9.1), pas la nouvelle à Crr fixé.

### Après — dépôt public

AGPL-3.0-or-later (le fichier `LICENSE` est posé), anonymisation des documents
de cadrage (Q6). Le dépôt peut s'ouvrir
avant le sprint 8 : la publication du code et l'invitation de personnes
sont deux décisions distinctes.

Backlog « envoi au compteur » (décisions du 12/09, **requalifié le
25/09/2026**) : pas d'API Garmin Connect pour un particulier → le GPX
généré est le socle. Ce socle **est fait** — le bouton « Télécharger le
GPX » (`Boucles.tsx`, `Propositions.tsx`) marche, l'envoi manuel aussi ;
le mainteneur l'a d'ailleurs cru clos pour cette raison (« je pensais que
c'était fait car on a le bouton télécharger le GPX »). Ce qui reste est du
**confort**, pas un bloquant : sur mobile, partage direct du GPX vers
l'application Garmin Connect via la Web Share API avec fichier
(`navigator.share({ files: […] })`, remplace le détour « télécharger, puis
ouvrir avec ») ; puis, dans l'ordre d'intérêt exprimé, **Coros, Wahoo
(ELEMNT), Hammerhead (Karoo)**. Vérifié le 12/09 (doc des marques) :
**Wahoo** a une vraie API cloud (OAuth 2, envoi d'un parcours FIT qui
arrive sur le compteur ; accès développeur sur demande motivée) — la voie
la plus propre, à demander quand le service sera hébergé ; **COROS** : GPX
« ouvrir avec » l'application (donc déjà couvert par le partage direct
ci-dessus), ou synchro depuis Strava / Komoot / Ride with GPS, programme
développeur sur candidature ; **Hammerhead** : tableau de bord avec import
par URL (Strava, RWGPS, Komoot) et comptes liés (dont Intervals.icu pour
les séances), pas de dépôt direct public → intermédiaire ou import de
fichier. Le partage système du GPX depuis le mobile couvre Garmin et
COROS sans rien demander à personne. L'Edge sait charger un parcours et une séance
structurée en même temps : la séance vient déjà d'Intervals.icu. Aucun
sprint attribué : à cadrer (Web Share API d'abord, Wahoo cloud quand le
service sera hébergé) quand le mainteneur le priorisera.

Backlog « relief demandé » (note du mainteneur, 20/09/2026, aucun sprint
attribué) : pouvoir demander, en plus de la durée et de la direction, le
relief voulu — **plat, vallonné, qui grimpe, montagne** — et que le produit
réponde honnêtement dans deux cas : (1) **introuvable à portée** : pas de
montagne en Bretagne, on le dit au lieu de servir la moins plate des boucles
sous ce nom ; (2) **en désaccord avec les blocs de la séance** : on ne tient
pas une vraie Z2 sur un col à 15 %, un bloc de force à 60 rpm ne se place pas
sur du plat qui descend, etc. Ce désaccord doit s'afficher comme une alerte
qui nomme le bloc et la pente, pas se résoudre en silence par le placement
(sprint 4) ni par un relief « à peu près ». À rattacher au score de placement
et au profil coloré par la pente déjà livrés ; à cadrer avec [[Q53]] (qualité
du tracé, au backlog) quand le dogfooding le rendra urgent. Le vocabulaire des
quatre reliefs et leurs seuils (dénivelé par km, pente maximale) sont une
question produit à poser au mainteneur avant tout code.

Backlog « le modèle arbitre trop » (note du mainteneur, 20/09/2026, aucun
sprint attribué) : en demandant trois parcours pour une séance, l'appli n'en
retient souvent qu'un — mesuré le 20/09 à Rennes comme à La Rochelle, les
deux autres candidates étant écartées à 31 % de recouvrement pour un seuil
de 30 % (`seuil_recouvrement`, non réglable dans la configuration). Le
mainteneur veut **plusieurs solutions pour choisir lui-même** ; « c'est
chiant quand le modèle arbitre trop ». Pistes à cadrer, pas tranchées :
seuil réglable ou relevé, plus de candidates par défaut quand la
déduplication en mange, ou « Chercher plus loin » lancé d'office jusqu'à
trois retenues (mesuré : cinq candidates en donnent trois).

Backlog « la phrase sur la vitesse » (note du mainteneur, 20/09/2026,
**fait le 25/09/2026**) : sous « Ce que ça donnera »
(`front/src/ecrans/Demander.tsx`), le paragraphe « Estimé avec votre
moyenne compteur de … km/h, que le modèle physique tire de votre
puissance … Facteur de compteur supposé, faute de mesure ; modèle
physique littérature » est jugé incompréhensible (« c'est débile, faut faire
plus simple »). Deux formulations proposées le 20/09, en attente du choix du
mainteneur : A « Estimation d'après votre profil et votre vélo. Le tracé
vient avec le bouton. » ; B « Estimation d'après votre profil. Votre vitesse
réelle n'est pas encore mesurée : elle le sera sur vos sorties. » La règle de
provenance (doctrine : chaque écran dit d'où vient la valeur) reste ; c'est
la longueur et le jargon qui partent.

Décision du superviseur le 25/09, validée dans son principe par le
mainteneur (« fais 8 ») : formulation A, la plus courte, sans le chiffre de
moyenne compteur ni « Le tracé vient avec le bouton » (déjà dit ailleurs à
l'écran). Deux variantes seulement, selon `Zones.valeurs_liees` (`phraseEstimation`,
`front/src/ecrans/Demander.tsx`) : « Estimation d'après votre profil et
votre vélo. » quand rien n'est mesuré ; « Estimation d'après vos sorties. »
dès que le facteur de compteur est mesuré (`facteur_mesure`) ou que le vélo
est calibré (`modele_physique === "calibration"`). Aucun chiffre ni jargon
dans cette phrase-là ; la provenance détaillée (le facteur, le modèle
physique) reste dans Réglages, sous le dépliant « D'où viennent ces deux
chiffres » — la règle de provenance ne bouge pas, seule cette phrase se
simplifie.

Backlog « le porte à porte ignore le relief de la boucle » (note du
mainteneur, 21/09/2026, aucun sprint attribué) : `physique.modele.temps_ecoule`
calcule le porte à porte comme `distance / moyenne_compteur_kmh`, une moyenne
à plat qui ne redescend jamais au relief réel de la boucle évaluée — assumé
et documenté en toutes lettres dans le code (`temps_ecoule` docstring, «
limite assumée, à dire en toutes lettres »), pour ne pas compter deux fois
le relief déjà moyenné dans le facteur compteur. Mais ça laisse les deux
chiffres affichés insatisfaisants : le porte à porte ignore le relief de
cette boucle-ci, le temps en mouvement (`sans un seul arrêt`) ignore les
arrêts. « Je pige pas » (mainteneur, 21/09) devant le dépliant explicatif ;
« sinon en montagne ça va être débile » — le décalage entre un porte à
porte à plat et une boucle réellement montagneuse est justement le cas où
l'écart se voit le plus, et où il compte le plus.

Piste retenue par le mainteneur, à cadrer avant code : remplacer le porte à
porte par `temps_estime_s` (déjà fidèle au relief et au vent de cette boucle)
plus un temps d'arrêt dérivé du nombre **réel** de feux et de stops sur ce
tracé (`candidate.feux`/`candidate.stops`, déjà comptés et affichés
ailleurs à l'écran) — plutôt qu'une moyenne à plat ou la convention
`part_arret` à 5 %. Un seul chiffre, fidèle au relief et réaliste sur les
arrêts, au lieu de deux chiffres dont aucun ne répond à la question posée.

**Objection du mainteneur le 21/09, et elle tient** : « le temps de relancer
etc., je vois pas comment tu peux t'en sortir là. » Vérifié dans le code —
`physique/modele.py` le dit dès sa ligne 5, « ni inertie, ni frottement » :
le modèle n'a aucune notion d'accélération, seulement des vitesses
d'équilibre à puissance constante. Un feu ne coûte donc pas qu'un temps
d'attente ; il coûte aussi une décélération puis une relance dont rien dans
le modèle actuel ne sait le prix. Un simple « nombre de feux × durée fixe »
serait une convention de plus, pas mieux fondée que `part_arret`. Trois
chemins, aucun tranché :

1. **Modéliser la relance en vrai** (masse, énergie cinétique, accélération)
   — un vrai chantier de physique, pas un ajout à `temps_ecoule`.
2. **Une convention par arrêt, assumée comme telle** (secondes fixes par
   feu/stop, comme `part_arret` l'est déjà pour l'ensemble de la sortie) —
   simple, mais devine plutôt que mesure.
3. **Mesurer, pas deviner** — même méthode que le facteur compteur de
   [[Q51]] : sur l'historique GPS réel du mainteneur, chercher combien de
   temps se perd effectivement autour d'un carrefour connu par rapport à un
   passage sans ralentir, et en tirer une constante mesurée. Cohérent avec
   la manière dont ce projet traite d'habitude ce genre de question, mais
   demande des sorties où un carrefour est identifiable dans le tracé GPS.

**Le 21/09, en creusant l'option 3 : les deux ingrédients existent déjà,
séparés.** `physique/commande.py` (validation de `ourouler calibrer`)
calcule déjà, pour chaque sortie de validation, `temps_reel_s` (le vrai
porte à porte, arrêts compris) **et** `temps_simule_s` (le modèle sur ce
même tracé, relief et vent réels, sans arrêt — la docstring le dit : « ni
les arrêts, ni les redémarrages n'y sont modélisés »). L'écart entre les
deux, sortie par sortie, est déjà le coût réel des arrêts de cette
sortie-là, mesuré et non deviné — il manque seulement de le rapporter au
nombre de feux/stops rencontrés, et **le rejeu d'une trace GPS dans BRouter
pour en tirer les tags de carrefour** (feux, stops, cédez-le-passage) est
lui aussi une méthode déjà en service ailleurs (`marqueurs_retrospectif.py`,
`arrets_bloc_recup.py` question 2). Croiser les deux — `(temps_reel_s −
temps_simule_s) / nombre de feux-stops`, sur assez de sorties — donnerait
une constante mesurée en secondes par arrêt, sans modéliser de physique de
relance. Reste un vrai script à écrire (aucun des deux jeux de résultats
n'est aujourd'hui croisé l'un avec l'autre), mais pas une donnée à
collecter ni une physique à inventer — l'option 3 est donc plus proche que
les deux autres.

**Vérifié le 21/09 sur les vraies données du mainteneur** (`ourouler
calibrer --json`, 25 sorties de validation) : l'écart brut `temps_reel_s −
temps_simule_s` ne révèle **aucune logique simple** pris seul. Moyenne 245 s
(≈ 4 s/km), mais corrélation à la distance faible (r = 0,49), et surtout
écart-type de l'écart (373 s) plus grand que sa moyenne — huit sorties sur
vingt-cinq ont un écart **négatif**, ce qu'un coût d'arrêt pur ne peut pas
expliquer (un arrêt n'a jamais fait gagner du temps). Le bruit du modèle
lui-même (vent mal estimé, résidu de calibration, déjà documenté à 5-10 %)
domine le signal qu'on cherche à isoler.

**Objection du mainteneur le 21/09, et elle est décisive : compter les
feux/stops ne répare rien.** Sur huit sorties sur vingt-cinq, le temps
**simulé** dépasse déjà le temps **réel**, avant tout coût d'arrêt ajouté.
Le sens ne trompe pas : un arrêt ne peut qu'ajouter du temps, jamais en
retirer. Si le modèle est déjà trop lent sans compter le moindre feu, ce
n'est pas qu'un coût d'arrêt manque — c'est que `temps_simule_s` se trompe
déjà, pour une raison sans rapport avec les arrêts (vent, calibration,
saison). Ajouter un coût de feux/stops par-dessus **aggraverait** ces huit
prédictions au lieu de les corriger. La piste « croiser l'écart avec le
nombre de feux/stops » (ci-dessus, même jour) est donc **invalidée**, pas
seulement plus dure que prévu — elle a été écrite avant de vérifier le sens
des écarts, l'erreur est d'avoir maintenu la piste vivante après l'avoir
mesurée.

**Ce qui reste vrai, sous cette réserve** : les options 1 (modéliser la
relance en vrai) et 2 (convention assumée par arrêt) ne sont pas concernées
par cette objection — mais aucune n'est mesurée ni cadrée non plus. La
vraie question préalable, non résolue, est **pourquoi `temps_simule_s`
dépasse parfois `temps_reel_s`** : tant qu'elle n'a pas de réponse, ajouter
quoi que ce soit par-dessus (feux, convention, ou physique de relance) reste
prématuré.

**Réponse trouvée le 21/09, vérifiée et non plus devinée sur un nom de
sortie.** Première tentative (même jour) : six des huit écarts négatifs
portaient le même nom générique (« Rennes Cyclisme sur route ») que des
sorties d'apprentissage repérées à 50-78 % « en groupe » par
`calib.detecter_groupe` — mais ce critère, rejoué sur les huit, ne les
détecte pas (`groupes_en_validation` vide dans le rapport). Le mainteneur a
corrigé le tir : pas un gros groupe (le seuil du contrat, >50 % de la
distance anormalement rapide, ne devait pas s'appliquer), mais 2 ou 3 roues
— un effet plus discret, sous le seuil d'exclusion mais réel.

Vérifié en rejouant `detecter_groupe` sur les 25 sorties de validation et en
gardant, cette fois, la **part brute** (avant le seuil des 50 % qui décide
« en groupe » ou pas) plutôt que le seul booléen : la corrélation entre
cette part et l'écart de temps est de **-0,79** — forte. Les huit sorties à
écart négatif portent en moyenne 34,1 % de distance anormalement rapide,
contre 19,5 % pour les dix-sept autres. Aucune ne franchit le seuil de 50 %
qui déclencherait l'exclusion automatique, mais le signal est net, mesuré
sur le vrai critère du contrat, pas sur un nom de fichier. Ça correspond à
l'hypothèse du mainteneur : un effet de roue partiel, assez fort pour
biaiser le temps, pas assez soutenu pour être filtré. Strava (« riding
with ») confirmerait sortie par sortie, mais n'est branché nulle part ici.

**Ce que ça change pour le lot, sans le trancher** : la vraie explication
des écarts négatifs n'est probablement pas un défaut du modèle physique,
c'est une contamination de la donnée d'entrée — des sorties roulées à
plusieurs, partiellement, que le seuil d'exclusion actuel (>50 % de la
distance) ne repère pas. Avant tout travail sur le porte à porte ou sur un
coût d'arrêt, la question qui se pose est **si ce seuil doit descendre**,
et jusqu'où — sans savoir combien de vraies sorties solo il écarterait à
tort au passage. Non mesuré, non tranché.

**Objection du mainteneur, à raison : l'analyse ci-dessus ne portait que sur
les 25 sorties réservées à la validation.** Il y en a en réalité 99
calibrables au total (74 en apprentissage, 25 en validation). Rejoué sur les
99 (temps réel/simulé et part de groupe recalculés pour chacune avec les
paramètres finaux, indépendamment de leur usage en apprentissage ou en
validation) :

| seuil d'exclusion | sorties restantes | part négative |
|---|---|---|
| aucun | 99 | 61 % |
| < 40 % | 64 | 39 % |
| < 30 % | 39 | 18 % |
| < 25 % | 21 | 10 % |
| < 20 % | 13 | 8 % |
| < 15 % | 8 | **0 %** |

La baisse est régulière à chaque palier, avec cette fois des échantillons
substantiels au milieu (39 et 21 sorties, pas seulement 6) — beaucoup plus
convaincant qu'un artefact de petit échantillon. L'écart moyen, une fois
nettoyé sous 15 %, converge à **5,9 %**, quasiment le même chiffre que sur
les 25 seules (5,8 %) : deux calculs indépendants qui s'accordent.

**Ce que ça reste : un signal solide, pas encore une constante.** Le fond
du problème mesuré au 21/09 (l'exclusion à 61 % de négatifs quand on ne
filtre rien) montre surtout que **beaucoup plus d'un tiers de l'historique
du mainteneur porte un effet de roue**, pas seulement les cas extrêmes déjà
filtrés par le seuil des 50 %. Ce que ferait un abaissement du seuil
d'exclusion, et combien de vraies sorties solo il écarterait à tort au
passage, reste non mesuré.

**Le dénivelé n'explique rien de cet écart, vérifié.** Sur les sorties
« propres » (peu de signal de groupe), le dénivelé par kilomètre (6,6 à
23 m/km sur l'historique du mainteneur — la Bretagne, pas la montagne) ne
corrèle pas avec l'écart (r = -0,03). Logique : le modèle simulé calcule
déjà la pente réelle point par point sur le tracé, c'est son travail — s'il
y avait une corrélation, ce serait le signe d'un biais du modèle en côte,
pas d'un facteur à ajouter. Le facteur peut donc rester une constante
unique, sans varier selon le relief de la boucle — **dans la gamme de
terrain roulée jusqu'ici** ; rien ne dit ce qu'il donnerait sur une vraie
montagne, aucune sortie de ce profil dans l'historique.

**Conclusion, validée par le mainteneur le 22/09 : c'est le facteur qui
manquait au lot « le porte à porte ignore le relief » plus haut.** Les deux
chiffres actuels sont faux chacun à sa manière — le porte à porte ignore le
relief réel de cette boucle, le temps simulé ignore les arrêts. La
correction proposée : **porte à porte = `temps_estime_s` (relief et vent
réels de cette boucle, déjà calculé) × 1,06** — un seul chiffre qui tient
les deux à la fois, plutôt que les deux chiffres actuels, faux chacun à sa
manière. Réserve qui reste, honnête : 1,06 est mesuré sur un sous-ensemble
filtré (les sorties les plus « en groupe » écartées), pas sur l'ensemble de
l'historique — une bonne estimation, pas une certitude au dernier chiffre.

**Vérifié le 23/09 sur ses sorties de 3h20 à 5h10 réelles (RCR et BMC), et
un vrai sujet trouvé sur le second vélo.** Comparé sortie par sortie : réel,
porte à porte actuel, modèle seul, modèle × 1,06. Sur RCR, cinq sorties sur
neuf tombent quasiment à la minute près avec le ratio (4h14, 4h20, 4h53…),
contre zéro avec le porte à porte actuel — cohérent avec la mesure globale.
Sur BMC (le vélo de contre-la-montre), `detecter_groupe` signale 29 à 39 %
de distance anormalement rapide sur **chacune** de ses cinq sorties de cette
durée, sans exception — plus haut et plus systématique que sur RCR. Le
mainteneur est formel : **le BMC ne se roule quasiment jamais en groupe.**
Ce n'est donc probablement pas le même phénomène que sur RCR — plus
vraisemblablement un vrai décalage de calibration propre à ce vélo (la
position contre-la-montre change le CdA réel, que le modèle ne capte peut-
être pas correctement pour cette position), pas une contamination de
roue. Non vérifié plus loin ici ; à recalibrer et creuser séparément avant
d'appliquer le même ratio de 1,06 au BMC — rien ne dit qu'il vaut la même
chose sur les deux vélos.

**Confirmé le 23/09, avec `ourouler comparer` (mesure sans modèle) et le
bon sens du mainteneur.** Écart mesuré à 169 W : le BMC roule 2,4 km/h plus
vite, converti en 27 à 42 W selon la méthode — réel, mesuré sur 145 séries
BMC et 317 RCR, aucun modèle physique impliqué. Mais la calibration des
deux vélos (`RCR : CdA 0,2219, Crr 0,01062` / `BMC : CdA 0,2204,
Crr 0,00838`) répartit cet écart à l'envers de ce qu'on sait du matériel :
**mêmes pneus sur les deux vélos**, des roues un peu meilleures sur l'un
sans que ce soit flagrant, donc le Crr devrait être quasi identique entre
les deux et tout l'écart devrait sortir en CdA — pas l'inverse. Confirme,
sur un cas concret et vérifié, ce que le code documente déjà : CdA et Crr
« mal séparés » l'un de l'autre par la calibration, alors que leur total
est fiable. Sujet à part, propre à la calibration, pas à ce lot — non
traité ici.

**Essayé le 23/09, à la demande du mainteneur : fixer le Crr du BMC à celui
du RCR (mêmes pneus) et refitter le CdA seul. Résultat négatif, honnête,
et instructif.** Nouveau CdA obtenu par moindres carrés pondéré : 0,1856 m²
(contre 0,2204 en fit libre) — physiquement plus crédible pour une position
contre-la-montre. Mais rejoué sur les cinq vraies sorties BMC de 3h20 à
5h10, les temps prédits **s'éloignent** de la réalité au lieu de s'en
rapprocher (ex. 2025-05-01 : réel 3h24, ancien modèle 3h27, nouveau modèle
3h32). Cause probable : la calibration ne filtre que des tronçons très
plats (pente ≤ 0,8 %) pour séparer CdA et Crr. Sur du plat, un Crr plus
haut compensé par un CdA plus bas peut coller aussi bien aux mêmes
données ; mais Crr et CdA ne pèsent pas pareil selon la vitesse et la
pente (Crr compte plus en montée, CdA compte plus vite), et rejoué sur le
relief réel d'une sortie complète, la combinaison forcée pénalise plus que
l'ancienne. **Fixer un des deux paramètres à la main, sans données qui
varient assez en pente pour vraiment les séparer, ne suffit pas** — la
piste reste un vrai sujet de calibration (des tronçons à pentes variées,
pas seulement plats), pas un ajustement qui se règle en une session.

**Précisé le 23/09 : pas seulement les deux extrêmes, toute la plage entre
les deux.** Le mainteneur a demandé un compromis — un peu mieux sur le
Crr, un peu mieux sur le CdA, sans copier le RCR — plutôt que de forcer le
Crr à 100 %. Testé sur cinq points intermédiaires (0 %, 20 %, 40 %, 60 %,
100 % de la distance entre le Crr libre du BMC et celui du RCR), erreur
mesurée sur les vraies sorties complètes à chaque fois : **la progression
est monotone**, l'erreur augmente à chaque pas vers le Crr du RCR, sans
aucun minimum entre les deux (7,6 % au fit libre, 10,1 % au Crr forcé du
RCR). Aucun compromis ne fait mieux que le fit libre. Conclusion, honnête
et un peu à contre-intuition : l'hypothèse « mêmes pneus donc même Crr »
ne se vérifie pas dans les faits, même si elle paraît raisonnable sur le
papier — le fit libre du BMC, aussi étrange que sa répartition CdA/Crr
individuelle paraisse, reste le meilleur prédicteur trouvé. **Recommandation
pour ce vélo : garder sa calibration libre pour la prédiction, ne pas
essayer de la faire coller à celle du RCR** ; ne pas interpréter son CdA ou
son Crr pris isolément comme une vérité physique (le code le dit déjà),
seule la prédiction globale compte.

**Pourquoi « mêmes pneus » était faux, précisé le 23/09 : équipement réel du
mainteneur.** Les deux vélos sont en Continental GP5000, mais pas la même
version — **All Season sur le RCR**, connu pour un Crr plus élevé que le
**TR (tubeless) sur le BMC**, la version la plus rapide de la gamme dans les
tests publiés. Pression basse sur les deux, sous 5 bar : hookless (Zipp
303S) sur le RCR, confort d'épaule en position aéro sur le BMC — ce qui
pousse le Crr réel des deux au-dessus des chiffres labo publiés à haute
pression. L'hypothèse testée plus haut (« mêmes pneus donc même Crr ») était
donc fausse dès son point de départ, pas seulement invalidée par la mesure.
**Mais un vrai écart de pneu (All Season contre TR) n'explique
probablement pas la totalité du Crr mesuré** (0,0106 contre 0,0084, un
écart de 0,0022) : les écarts publiés entre versions du même pneu sont en
général plus petits. Le biais de calibration (CdA/Crr mal séparés)
coexiste vraisemblablement avec un vrai écart de pneu, sans qu'on sache
mesurer la part de chacun ici.

**Résolu le 23/09, avec la bonne méthode — Crr fixé par la littérature,
pas cherché, CdA laissé varier et jugé sur les vraies sorties, sans chercher
à faire coller le BMC au RCR.** La recherche libre (calibration à deux
paramètres) donnait une dérive sans fin dès qu'on s'écartait du point de
départ — un symptôme de sur-ajustement sur 5 à 9 sorties, pas une vraie
convergence physique, à raison signalé par le mainteneur. En fixant le Crr
à une valeur plausible de la littérature (0,006 pour le RCR, All Season,
haut de la fourchette « bon pneu route » ; 0,005 pour le BMC, TR, légèrement
en dessous) et en ne laissant varier que le CdA, **un vrai minimum en
cloche apparaît pour les deux vélos**, pas une dérive :

| | RCR | BMC |
|---|---|---|
| Crr (fixé, littérature) | 0,006 | 0,005 |
| CdA (minimum trouvé) | 0,30 m² | 0,23 m² |
| Erreur sur les vraies sorties (avec × 1,06) | 4,76 % | **0,72 %** |

Les deux CdA tombent dans les fourchettes plausibles (route amateur 0,27 à
0,36 ; contre-la-montre compétitif 0,20 à 0,24), sans avoir été cherchés
pour ça — c'est une conséquence du minimum, pas un objectif imposé.
**Recoupement indépendant, qui referme la boucle** : ces deux jeux de
paramètres, calibrés séparément chacun sur ses propres sorties, prédisent
entre eux un écart de puissance de 29,6 à 37,8 W à la vitesse réelle
mesurée (28,6-31,5 km/h) — dans la fourchette des 27 à 42 W mesurés
indépendamment par `ourouler comparer` (aucun modèle physique), et proche
des ~25-30 W de mémoire du mainteneur. Trois mesures indépendantes
(calibration RCR, calibration BMC, comparaison sans modèle) qui se
recoupent. **Le même ratio de 1,06 tient sur les deux vélos** avec ces
nouveaux paramètres — le sujet BMC séparé, ouvert plus haut, est refermé.

**Confirmé le 23/09 sur grand échantillon** (le mainteneur a raison de ne
pas se fier à 5-9 sorties) : rejoué sur les 99 sorties RCR et 35 BMC
calibrables, avec ces mêmes paramètres.

| | RCR (n=99) | BMC (n=35) |
|---|---|---|
| toutes | erreur 4,9 %, biais -2,9 % | erreur 2,3 %, biais +1,4 % |
| < 50 % groupe (83/34) | erreur 3,7 %, biais -1,3 % | erreur 2,3 %, biais +1,6 % |
| < 30 % groupe (39/15) | erreur 3,1 %, biais +2,0 % | erreur 2,8 %, biais +2,8 % |

Vérifié aussi que l'erreur n'est **pas systématiquement dans le même sens**
sur les sorties longues (4 sorties réel > prédit, 5 réel < prédit) — les
5 % initialement inquiétants sur 9 sorties venaient pour l'essentiel des
deux sorties déjà repérées en groupe (67 % et 46 %) ; sans elles, sept
sorties, erreur moyenne **signée** quasi nulle (-0,0 %), 3,2 % en absolu.
Nuance qui reste, honnête : plus on filtre serré sur les sorties les plus
solo, plus le biais devient positif (le modèle sous-prédit légèrement) —
1,06 est peut-être un peu bas pour les sorties vraiment propres, plutôt
1,07-1,08 ; le BMC, lui, reste stable autour de +1,4 à +2,8 % quel que soit
le filtre. Pas un problème de fond, une piste d'affinage.

**Le point le plus important de toute cette note, relevé le 23/09 par le
mainteneur, au-dessus des chiffres précis de CdA/Crr : l'erreur du modèle
sur une sortie (3 à 5 %) est du même ordre que l'effet qu'on cherche à
corriger (6 %).** Le ratio de 1,06 corrige bien le **biais moyen** sur cent
sorties — ça, c'est mesuré et solide. Mais il ne réduit pas le bruit propre
du modèle sur **une** boucle donnée, qui reste du même ordre de grandeur que
la correction elle-même. Concrètement : afficher un temps unique avec cette
précision (« 3h54 ») dit plus de précision que ce que le modèle sait
vraiment sur une sortie qu'il n'a jamais vue. Le ratio améliore la moyenne
affichée à l'utilisateur sur l'ensemble des sorties qu'il verra dans le
temps ; il ne rend pas fiable la prédiction d'une seule sortie prise à part.
**Conséquence pour le produit, non tranchée** : soit le dire (une fourchette
plutôt qu'un chiffre unique, cohérente avec l'incertitude réelle), soit
l'assumer sciemment (un chiffre, moins précis qu'il n'y paraît, mais plus
juste en moyenne que l'ancien porte-à-porte) — c'est une question produit,
pas un calcul de plus.

**Tranché le 23/09 par le mainteneur : une fourchette, pas un chiffre
unique.** Calculée en centiles sur le ratio réel/modèle mesuré (sorties à
moins de 50 % de signal de groupe, RCR n=83, BMC n=34) plutôt que devinée :

| | RCR | BMC |
|---|---|---|
| médiane | × 1,039 | × 1,082 |
| fourchette 25e-75e centile (la moitié des sorties) | × 1,015 à × 1,072 | × 1,057 à × 1,095 |
| fourchette 10e-90e centile (80 % des sorties) | × 0,997 à × 1,108 | × 1,048 à × 1,105 |

Exemple concret, pour un `temps_estime_s` de 4h20 : RCR entre 4h23 et 4h38
(moitié des sorties), BMC entre 4h34 et 4h44. **Fourchette retenue pour
l'affichage : 25e-75e centile** — assez resserrée pour rester utile, assez
large pour ne pas mentir sur l'incertitude réelle du modèle. Le porte à
porte devient donc `[temps_estime_s × bas, temps_estime_s × haut]`, propre
à chaque vélo, plutôt qu'un chiffre unique ou l'actuelle moyenne à plat.
Chaque vélo garde ses propres centiles — pas de constante partagée entre
RCR et BMC, cohérent avec tout ce que cette note a trouvé.

**Ce qui reste à faire pour que ce soit du code et pas une note** : ce
recalage (Crr fixé par catégorie de pneu, CdA cherché sur les sorties
longues) n'est écrit dans aucun script réutilisable — fait à la main dans
cette conversation. À coder dans le pipeline de calibration si retenu,
avec la même règle que partout ailleurs dans ce lot : ça tourne tout seul,
jamais un script relancé à la main.

**Condition posée par le mainteneur, et elle prime sur le choix du
chemin, quel qu'il soit** : « si je mets moi du temps, ça marchera jamais. »
Toute mesure retenue devra tourner **tout seule** dans le pipeline existant
— jamais un script que le mainteneur relance et interprète lui-même. Une
mesure qui dépend de son temps disponible n'arrivera jamais ; c'est un
critère d'acceptation, pas un confort.

**Reste à faire, non commencé** : recalibrer CdA/Crr par la méthode qui a
marché (Crr fixé par catégorie de pneu, CdA cherché sur les sorties
longues — pas la calibration libre à deux paramètres, qui dérive) ; calculer
les centiles du ratio réel/modèle une fois dans `ourouler calibrer`,
sorties à moins de 50 % de signal de groupe, écrire la fourchette (25e-75e
centile) dans `calibration.json` aux côtés de CdA/Crr ; brancher
`temps_ecoule` sur cette fourchette au lieu de `moyenne_compteur_kmh` et
rendre `[bas, haut]` plutôt qu'un chiffre unique jusqu'au front ; décider
d'une fourchette par défaut générique en attendant assez de sorties propres
pour un vélo neuf ; le filtrage du signal de groupe (seuil, méthode) doit se
faire **une seule fois**, dans le pipeline, jamais à la main. Rien n'est mis
en sprint. La moyenne compteur garde de toute façon son rôle ailleurs
(dimensionner la distance demandée), ça ne change pas.

**Récapitulatif du 23/09 — la fourchette retenue, et ce qui reste précisément
à vérifier sur le RCR.**

Fourchette d'affichage (`temps_estime_s × [bas, haut]`, centiles 25-75 du
ratio réel/modèle, sorties à moins de 50 % de signal de groupe) :

- **RCR** (n=83) : × 1,015 à × 1,072 — médiane × 1,039.
- **BMC** (n=34) : × 1,057 à × 1,095 — médiane × 1,082.

Sur le RCR, quatre choses restent ouvertes, distinctes les unes des autres,
à ne pas confondre :

1. **Le minimum de CdA/Crr est plat** (0,32 à 0,34 à 0,36 donnent presque la
   même erreur, Crr fixé à 0,006) — le point retenu (0,30) est dans cette
   zone mais pas forcément le meilleur ; un vrai minimum n'a été confirmé
   qu'à la louche, pas affiné.
2. **L'erreur bouge selon le seuil de filtrage du signal de groupe** (4,9 %
   sans filtre, 3,7 % sous 50 %, 3,1 % sous 30 %, 4,6 % sous 20 %) — le BMC,
   lui, reste stable quel que soit le filtre. Cette instabilité peut venir
   du plateau plat du point 1, ou du fait que 99 sorties couvrent beaucoup
   plus de saisons et de conditions que les 35 du BMC — pas départagé.
3. **Le biais change de sens selon le filtre** : légèrement négatif sans
   filtre (-2,9 %, les sorties en groupe tirent vers le bas), légèrement
   positif en filtrant serré (+4,5 % sous 20 %, seulement 13 sorties). Sur
   les 7 sorties propres et longues (3h20-5h40, hors les deux repérées en
   groupe), le biais signé tombe à quasi zéro (-0,0 %) — cohérent avec un
   modèle non biaisé, mais peu de sorties pour le confirmer à grande échelle.
4. **Le seuil de détection de groupe lui-même n'a jamais été abaissé ni
   réglé** — seulement testé en lecture, jamais changé dans le pipeline. Une
   partie de l'instabilité du RCR peut venir de sorties à 30-49 % de signal
   de groupe qui passent encore le filtre à 50 % sans être vraiment solo.

Rien de tout ça n'invalide la fourchette retenue — elle reste mesurée sur
83 sorties réelles — mais un futur lot qui recoderait ce recalage devrait
partir de ces quatre points plutôt que de repartir de zéro.

**Codé le 25/09 (L9.1, branche `l9-1-modele`), corrigé après la
contre-lecture Fable et la relecture Opus du même jour, et mesuré sur les
vraies données du mainteneur** — copie de sa configuration avec `pneu`
ajouté (RCR `course_quatre_saisons`, BMC `course_rapide`), calibration écrite
dans une copie du cache, jamais dans `~/.cache/ourouler/calibration.json`.

Ce qui tourne tout seul : un champ `pneu` par vélo donne le Crr
(`physique.litterature.PNEUS`) ; un `crr` écrit à la main est respecté et
figé de la même façon ; `ourouler calibrer` ne cherche alors que le CdA
(`--crr-libre` garde l'ancien ajustement), en minimisant l'erreur de temps en
mouvement des sorties d'apprentissage à moins de `part_groupe_max` (0,30,
section `[calibration]`) de signal de groupe ; la fourchette du porte à porte
est mesurée sur les **seules sorties de validation**, centiles 25/50/75 du
temps écoulé sur le temps simulé, sorties à moins de 50 % de signal de
groupe, au moins huit, et écrite dans `calibration.json` avec `crr_source`
et son n ; sinon la convention, dite comme telle. Un pneu changé depuis la
calibration le dit (« pneu changé depuis la calibration, relancez-la ») sans
jeter la calibration. `temps_ecoule` rend `temps simulé × [bas, haut]`
jusqu'au front.

**Trois choix de méthode, mesurés.**

1. *CdA cherché sur le temps, pas sur les tronçons* (RCR, Crr 0,006) :
   moindres carrés des tronçons → CdA 0,299, validation 6,5 % ; erreur de
   temps des sorties → 0,33, 4,6 %.
2. *Roue partielle hors de l'apprentissage.* Les sorties d'apprentissage du
   RCR portent 36 % de signal de groupe en moyenne, la validation 20 % : une
   roue partielle sous le seuil de 50 %, qui fait paraître le vélo plus fin.
   Seuil à 0,30 pour chercher le CdA (parts remesurées avec le CdA du temps,
   pas celui des tronçons, qui cachait la roue : 45 sorties passaient au lieu
   de 27) : validation 3,5 % au lieu de 4,6 %, biais −0,8 % au lieu de
   −4,2 %.
3. *Fourchette hors échantillon.* Mesurée sur toutes les sorties, elle
   héritait de l'ajustement et sous-prédisait une sortie neuve (RCR médiane
   1,054 en échantillon, 1,072 en validation).

| | RCR | BMC |
|---|---|---|
| Crr (fixé, pneu) | 0,006 | 0,005 |
| CdA cherché (compensation, pas une mesure) | 0,378 | 0,318 |
| sorties d'apprentissage sous 30 % de groupe | 27 | 10 |
| puissance à 25 / 30 / 35 km/h, plat sans vent | 121 / 188 / 277 W | 102 / 158 / 233 W |
| validation, temps en mouvement | MAE 3,5 %, biais −0,8 % (n=25) | MAE 2,5 %, biais +1,2 % (n=9) |
| fourchette écoulé / simulé, validation | **× 1,021 à × 1,099** (méd. 1,035, n=25) | 7 solo < 8 → **convention** (indicatif : 1,044-1,086-1,137) |

**Le recoupement avec `ourouler comparer` est refermé** : ces paramètres
prédisent 29,8 W d'écart à 30 km/h entre les deux vélos (19 W à 25 km/h),
dans les 27-42 W mesurés sans modèle et proches des 25-30 W de mémoire du
mainteneur — là où le seuil de 50 % n'en donnait que 20 W. Les CdA, eux, ne
se comparent ni à la littérature ni entre eux : le RCR porte un capteur
unilatéral (× 2), le BMC un double, et ± 4 % de puissance déplacent le CdA
de 0,306 à 0,356. D'où le critère d'acceptation révisé du contrat
(puissance par watt affiché, biais ≈ 0, MAE).

**Écart à la note, expliqué** : la note lisait un temps **en mouvement**
(`temps_reel_s` de la validation est `temps_mouvement_s`), pas le porte à
porte ; avec ses paramètres, les centiles en mouvement redonnent exactement
les siens. La fourchette codée est sur le temps **écoulé**.

Convention par défaut : **× 1,02 à × 1,14, médiane 1,06**, l'enveloppe des
fourchettes de validation des deux vélos (`physique.litterature`). Sur une
boucle réelle de 120 km (RCR, 168 W, `ourouler boucle`, 26/09 9 h) :
« entre 4 h 40 et 5 h 01 » pour 4 h 34 sans arrêt ; sur 80 km au BMC, la
convention le dit.

**L9.4 codé le 25/09 (branche `l9-4-calibration`) : la même calibration,
depuis l'écran.** `POST /calibrations` lance `physique.commande.calibrer_velo`
(extrait d'`executer_calibrer`, qui n'imprime plus rien lui-même) en tâche
de fond, sous le verrou des tâches lourdes partagé avec l'import
(`api/taches_fond.py`) ; une par jour et par compte, remboursée sur échec.
En hébergé, `calibration.json` s'écrit dans le dossier du compte
(`Config.cache.fichier_calibration`, posé par `api/routes._config`) : c'est
lui que ses boucles, sorties et simulations relisent, jamais celui d'un
autre. Avec plusieurs vélos, seules les sorties rattachées explicitement
(capteur, équipement, période) comptent ; au moins 10 sorties
exploitables (8 d'apprentissage + la part de validation). Sans pneu,
l'écran propose de le choisir ou de fixer le Crr de l'usage (`crr_source`
« usage »). *Vérifié sur les vraies données*, compte hébergé de test dans un
dossier temporaire, FIT du RCR importés par `POST /activites/import` (le
cache du mainteneur lu seulement) : sur les 40 plus récents, CdA 0,408,
199 W à 30 km/h, MAE 5,6 % sur 10 sorties de validation, fourchette par
convention (0 solo de validation sur 8 requis) ; sur les 102 de
l'historique (100 exploitables), CdA 0,364, 182 W à 30 km/h, MAE 3,6 %,
biais −1,8 % (n=25), fourchette × 1,030 à × 1,110 (n=25) — contre 0,378,
188 W, 3,5 %, × 1,021 à × 1,099 par `ourouler calibrer`. L'écart tient
d'abord à ce qu'un FIT importé perd le nom Intervals de la sortie : les
sorties nommées « club », que la ligne de commande écarte, passent ici.

Restent ouverts : le chrono n'a pas assez de sorties de validation roulées
seul pour sa propre fourchette ; le seuil de 50 % qui écarte une sortie
entière n'a pas bougé (seul l'apprentissage du CdA passe à 30 %) ; la
réconciliation « facteur compteur » ne sert plus qu'à dimensionner la
distance.

Backlog « la calibration sur import garde les sorties de club » (constat du
25/09/2026, mesuré en clôture du sprint 9 ci-dessus, aucun sprint attribué) :
une calibration lancée depuis l'écran sur des FIT importés (L9.2/L9.4)
apprend sur des sorties de club que `ourouler calibrer` écarte, parce que le
filtre de la ligne de commande porte sur le **nom Intervals** de la sortie
(`inventaire.py`), un champ qu'un `.fit` importé directement ne porte pas —
seul le filtre de groupe à 30 % (L9.1) en rattrape une partie, celles où le
signal de groupe reste assez fort pour être détecté. Mesuré comme un écart
de méthode (CdA 0,364 contre 0,378 sur le même historique, ci-dessus), pas
encore comme un biais isolé et chiffré : reste à mesurer combien de sorties
de club exactement passent le filtre de groupe sans être nommées, et si un
autre signal (fréquence cardiaque plus élevée et plus lissée, régularité du
pas de pédalage) les distinguerait mieux qu'un nom qui n'existe pas hors
d'Intervals.

Backlog « import par lien » ([[Q48]], non fait) : L9.2 dépose un fichier ou
une archive téléchargée à la main ; un import par lien direct vers Strava ou
Garmin (sans passer par le poste de l'invité) reste [[Q48]], jamais cadré ni
codé — voir aussi `docs/inviter.md`, §4, qui le nomme explicitement comme
absent.

**Précision du 25/09/2026, à ne pas perdre en repriorisant** : [[Q48]]
(17/09/2026, § « Le lien plutôt que le téléversement ») avait tranché le lien
comme la voie **principale** — « on ne fait pas traverser une archive de
plusieurs centaines de mégaoctets à un navigateur. La personne colle le lien
que la plateforme lui a envoyé par courriel, et le serveur va chercher
l'archive. Le téléversement reste en secours. » L9.2 n'a livré que le
téléversement — le secours, pas la voie principale décidée. Le mainteneur l'a
redit le 25/09/2026, en dogfooding : « pour Strava et Garmin on a vu aussi
qu'une méthode pouvait être de copier-coller le lien. » Les trois contraintes
posées par Q48 pour cette voie restent entières et n'ont pas bougé : **le lien
est un secret** (jamais journalisé, jamais en paramètre d'URL, jamais conservé
après usage), **une garde SSRF** (liste blanche de domaines, refus des plages
privées après résolution DNS, aucune redirection hors domaine, plafond de
taille et de durée), et une **expiration à sept jours** (Strava — Garmin et
Polar diffèrent, voir Q48 pour le détail par plateforme).

Backlog « la vidéo de démonstration a promis trois choses en plus » (constat
du mainteneur, 25/09/2026, en marge du carton « Bientôt » et du carton de fin
de la vidéo publique) :

1. **Les pauses et les nuits, pour les randonnées au long cours** — rien
   n'existe : plusieurs jours, pauses repas, étape du soir, météo par jour.
   Aucun sprint, aucune question ouverte encore posée dessus.
2. **La recherche par dénivelé** — déjà couverte par le backlog « relief
   demandé » ci-dessus (note du 20/09/2026) : même besoin, pas une entrée
   séparée.
3. **La météo et la durée d'un parcours qu'on a déjà** — le cœur porte
   l'essentiel : `ourouler simuler` / `POST /simulations`
   (`DemandeSimulation`, `src/ourouler/api/modeles.py`) calcule le temps d'un
   GPX déposé à puissance constante, la météo le long d'un tracé existe
   (chercher `meteo_trace`), et la fourchette porte à porte de L9.1
   s'applique au même modèle physique. Il manque un **écran** « déposer mon
   parcours » qui rende pluie, vent par tronçon et durée en fourchette à
   partir de ces briques — aucun aujourd'hui ne les assemble à l'écran.

   **Rattaché à un constat séparé du mainteneur, même jour** : le bouton
   « Déposer » de l'écran Aujourd'hui/Ma semaine sans Intervals
   (`front/src/App.tsx`, bloc « En attendant », ~lignes 592-616 et 651-675 —
   « Vous pouvez demander un parcours à la main, déposer un fichier de
   séance, ou déposer vos sorties passées ») ne dit que deux de ses usages
   réels. Ses mots : « déposer c'est pas que ça, c'est aussi l'analyse d'une
   trace existante pour y caler la météo, l'estimation, le vent etc. » —
   « Déposer » doit couvrir **trois** choses : une séance à faire
   (`.zwo`/`.mrc`, déjà géré), ses sorties passées (L9.2, déjà géré), et un
   parcours à **analyser** (le point 3 ci-dessus, qui n'existe pas encore en
   écran). Le texte d'accueil (`front/src/App.tsx`) et l'écran
   `front/src/ecrans/Importer.tsx` devront dire ces trois usages le jour où
   le troisième existe — pas avant, pour ne pas promettre un écran qui n'est
   pas là.
4. **« Garmin, bientôt »** (carton de fin, retiré de la version finale de la
   vidéo mais dit à l'enregistrement) — déjà couvert par le backlog « envoi
   au compteur » ci-dessus (décisions du 12/09/2026) : même sujet, pas une
   entrée séparée.

Backlog « le zoom de la carte des boucles » (constat du mainteneur,
25/09/2026, sur l'écran « 3 boucles » en production — boucle de 124 km au
départ de Rennes, `front/src/ecrans/Boucles.tsx`, **fait le 25/09/2026**) :
la carte (`front/src/composants/Carte.tsx`,
`carte.fitBounds(L.latLngBounds(tous), …)` où `tous` vient de **toutes**
les boucles proposées) s'ouvrait à l'échelle de la Bretagne et de la
Normandie (golfe du Morbihan, Fougères, parc Normandie-Maine visibles)
alors que les trois candidates tiennent dans un rayon d'environ 30 km
autour de Rennes et n'occupaient qu'un petit quart de la carte. Premier mot
du mainteneur : « le zoom par défaut n'est pas le plus adapté » ; précisé
ensuite : « en fait faut zoomer sur le circuit sélectionné » — la carte
doit se cadrer sur la boucle **retenue** (celle marquée « Retenue », ou
choisie dans la liste — `Boucles.tsx` porte déjà cet état,
`choisie`/`retenue`), pas sur l'emprise des trois boucles ensemble, et se
recadrer quand on change de boucle sélectionnée. Piste à cadrer, pas
tranchée : `fitBounds` sur les seuls points de la boucle sélectionnée (avec
une marge), redéclenché à chaque changement de sélection.

Fait : `Carte` cadre désormais sur les seuls points de la trace dont
`choisi` est vrai (fourni par `Boucles.tsx` et `Propositions.tsx`, qui
posent déjà cet état) — les autres boucles restent dessinées en pointillé,
elles ne pèsent simplement plus sur le zoom. Sans trace `choisi` (garde-fou,
pas un cas normal), le cadrage retombe sur l'emprise de toutes les traces,
comme avant. Le recadrage suit la sélection : changer de boucle change les
props de `Carte`, l'effet se redéclenche.

Observation de l'agent superviseur en marge de ce même constat, à distinguer
du mot du mainteneur : à l'échelle « les trois boucles », les étiquettes de
vent « vitesse/rafale » des trois tracés s'empilaient en un amas peu lisible.
Un cadrage sur la seule boucle sélectionnée réduit déjà ce risque en pratique
(un seul tracé de vent affiché à la fois) ; à revérifier une fois le zoom
corrigé, avant de coder quoi que ce soit de plus pour ça spécifiquement.

Revérifié : même une seule boucle de 124 km peut porter huit flèches de vent
assez rapprochées à l'écran pour se chevaucher, surtout dézoomée après un
`fitBounds`. `Carte` filtre donc désormais les étiquettes qui se
chevauchent à l'écran par détection de collision (`sansChevauchement`,
seuil de 46 px — la largeur approximative d'une étiquette « 24/38 »),
réévaluée à chaque zoom (`carte.on("zoomend", …)`) plutôt que figée au
premier rendu.

## Historique des sprints

- **2026-09-25** — Sprint 9 livré sur `sprint-9` (PR vers `main` en attente),
  cap « inviter pour de vrai » atteint : Crr par pneu et CdA cherché sur le
  temps en mouvement (L9.1), import de fichiers et d'archives en tâche de
  fond (L9.2), cache météo mutualisé et quotas par compte (L9.3),
  calibration depuis l'écran (L9.4), `docs/inviter.md` (L9.5), le compte de
  l'invité — Mon compte, `ourouler reinitialiser`, `ourouler retirer`
  (L9.6). Contre-lu par Fable sur L9.1 (méthode) et L9.2 (durcissement du
  dépôt de fichiers) ; lot de finition sur `l9-finition` (refus immédiat
  d'une seconde suppression concurrente, garde de requête hors boucle
  d'événements). Voir la clôture détaillée ci-dessus. Restent au
  mainteneur : l'action Q66a sur Coolify avant redéploiement, et déclarer
  `pneu` dans sa propre configuration pour que sa calibration passe à la
  méthode à un paramètre.

- **2026-09-13, nuit (après le sprint 4, sur la même branche)** — Le coût
  d'une descente sous un bloc **dépend maintenant de l'intensité demandée**,
  décision du mainteneur : « la descente doit être réduite dans les blocs et
  son poids négatif augmente avec la zone. Faire du Z3 en descente faible à
  moyenne, ça reste possible, position relevée face au vent. Z5 en descente,
  pas possible ou presque. » `evaluer_couloir` accepte la puissance cible du
  bloc et la FTP ; `POIDS_M_DESCENTE` est multiplié par un facteur de zone
  croissant (×0,4 sous 75 % de FTP, ×1 de 75 à 90 %, ×2 de 90 à 105 %, ×4
  au-delà) et le motif le dit — « descente de 0,4 km, coûteuse à cette
  intensité ». Les récupérations ne reçoivent toujours **aucune** évaluation,
  et leur puissance n'est donnée à personne : un test dédié garde les deux.

  **Mesuré, pas affirmé.** La validation rétrospective relancée passe de
  **42,7 % à 33,2 %** de la note du hasard (critère : au plus 70 %) — le
  facteur améliore la discrimination, parce que les tirages au hasard portent
  plus de descente (1,89 m/km) que les emplacements choisis (1,08). Sur les
  vraies séances : le 08/02, le **classement des candidates change** (les 3ᵉ
  et 4ᵉ s'échangent, 6,97/8,66 → 6,76/7,12) et la retenue reste la même ; le
  22/04, l'ordre ne bouge pas mais les notes et le nombre de demi-tours des
  candidates 2 à 4 changent. Une partie de la « dette assumée » du sprint 4
  est levée : le poids de la descente reste un arbitrage produit, mais il
  n'est plus un chiffre unique qui ignore ce qu'on demande au cycliste.

  **Q15 tranchée par le mainteneur** : l'heure de départ s'appelle
  **`--heure-depart`** partout (`meteo`, `boucle`, `simuler`, `sortie`), le
  lieu de départ s'appellera **`--adresse-depart`** — nom réservé, non livré,
  et gardé par un test pour qu'il ne soit pas pris entre-temps. Il remplace le
  `--depuis` annoncé au sprint 4, trop proche de `--depart`. Les anciens noms
  `--depart` et `--heure` restent acceptés et ne sont plus documentés.

- **2026-09-13, soirée** — Sprint 4 livré sur `sprint-4` (PR vers `main` en
  attente). Le cœur du projet : `ourouler sortie` lit la séance du jour,
  génère des boucles, place les blocs sur le terrain, écrit le GPX du
  **parcours réellement roulé** (demi-tours compris) et une **carte** qui
  montre chaque bloc à sa place. Quatre lots en parallèle + testeur
  adversarial, relecture Opus (13 points), **audit de probité des tests par
  mutation** (5 points de plus), quatre passes de corrections. État :
  2 892 tests, ruff vert.

  **Vérifié sur les vraies séances du mainteneur.** Le modèle et son
  cadrage écrit à la main se recoupent : bloc de 20 min à 206-219 W →
  11,2 km estimés contre « 11 km d'un trait » annoncés ; 8 min à 253 W →
  4,9 km contre « environ 4 km » ; demi-tour en 4 min de récup → 1,0 km de
  route au-delà contre « ≈ 800 m ». **Validation rétrospective** sur deux
  séances réellement faites dehors (22/04 et 25/04/2026) : les emplacements
  de blocs qu'il a choisis sont notés **43 % de la note du hasard**, donc
  nettement meilleurs — les poids sont justes. Et sur ses blocs longs, le
  constat qui justifie l'outil : ses 2×20' sont tombés sur un couloir noté
  6,46 alors qu'un couloir noté **1,81 existait sur la même boucle**.

  **Ce que la mesure a appris contre l'intuition** : il évite les zones
  bâties et les descentes, mais **ne fuit pas les montées** (il en prend
  plus que le hasard) et **ne se soucie pas des carrefours**. Poids corrigés
  dans ce sens.

  **Deux bugs trouvés par les seuls tests adversariaux** : les pentes
  étaient en pourcentage d'un côté et en tangente de l'autre, donc **tout
  demi-tour était refusé dès 0,1 % de pente** ; et un village traversé
  pendant une récupération était **facturé au bloc suivant**, en violation
  de la règle du mainteneur. **Deux règles non gardées trouvées par
  mutation** : un placement qui étirerait les récupérations « quand ça
  arrange » passait les 2 855 tests (288 sélections effectives), et « on
  note, on ne filtre pas » n'était protégé que par un dépaquetage de tuple.
  Les quatre sont corrigés et gardés par des tests qui échouent sur la
  mutation.

  **Décisions** : Q11 (`%ftp` nominal, zones de FC minoritaires), Q12
  (cascade de typage marqueurs → texte → puissance), Q13 (l'affichage ne
  montre que les blocs, à corriger), Q14 (le retour au calme ne peut pas
  absorber la variabilité de la boucle — arrondi au plus proche essayé et
  **annulé**, mesure à l'appui), Q15 (nom de l'heure et du lieu de
  départ — **tranchée la nuit suivante**, voir l'entrée ci-dessus). Fenêtre de détection des antennes portée de 3 à **6 km** après
  qu'un cul-de-sac de 3,4 km a été vu sur carte par le mainteneur.

  **Dette assumée** : le poids de la descente (0,10) n'est plus soutenu par
  sa mesure (57 % du hasard, pas 14 %) et reste un arbitrage produit ; le
  D+ du moteur et celui du parcours recalculé divergent de 40 % et sont
  désormais affichés côte à côte ; la météo et la tenue n'existent que dans
  la fenêtre de prévision, donc pas sur une séance passée ; Q13 et Q14
  restent entières.

- **2026-09-13, journée** — Sprint 3 livré sur `sprint-3` (PR vers `main` en
  attente). Trois lots en parallèle (antennes, routes connues, physique) +
  testeur adversarial ; relecture Opus (9 points, aucun bloquant) et passe
  Fable sur la physique ; trois passes de corrections. État : 2 364 tests,
  ruff vert. **Vérifié sur vraies données** : antennes (jusqu'à 6,6 km de
  culs-de-sac retirés par boucle, fenêtre 3 km décidée sur mesure ;
  `profile:correct_misplaced_via_points` est ignoré par le serveur
  — **corrigé le 18/09/2026 : c'était le mauvais nom de paramètre envoyé en
  snake_case, jamais reçu par le serveur qui attend le camelCase
  `correctMisplacedViaPoints`, voir `connecteurs/brouter.py`**) ;
  routes connues (154 sorties rejouées, tertiary 58 % / secondary 20 % /
  unclassified 13 %, poids appris secondary 3,0 → 0,44, colonne « connu % »
  cohérente avec la pratique : S 86-89 %, O 51 %) ; calibration RCR MAE
  4,2 %, BMC 2,4 % sur sorties non vues, après vent à hauteur du cycliste
  (×0,6) et terme cinétique — l'un sans l'autre laissait le CdA en butée ;
  `comparer` : BMC +2,4 km/h à puissance égale en Z2 sur séries plates,
  ≈ 27-42 W, conforme au « 25-30 W à la louche » d'Amiel. Décisions :
  on ne sépare plus CdA et Crr (Q9), multisport écarté (Q10), Q8 = Z2 par
  défaut puis la séance (S4). Dette assumée : `routes poids` fait 8 appels
  BRouter même sans `--appliquer` ; conversion en watts = fourchette, pas
  un chiffre ; BRouter bimodal sur l'azimut NE à 60 km ; élagage des
  antennes approximatif au raccord (re-tracé par le moteur à envisager) ;
  facteur vent 0,6 = hypothèse de rugosité, non mesurée.

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

Backlog « la séance du jour part à 9 h, quelle que soit l'heure » (constat du
mainteneur, 25/09/2026 vers 17:30, en production, onglet « Aujourd'hui »,
**non fait** — gel du sprint d'ouverture) : la proposition affichée disait
« 9 h 00 … retour vers 9 h 52 », avec une tenue d'automne (« au départ :
14 °C ressentis, catégorie frais » : manchettes, jambières, gilet, gants
longs) alors qu'il faisait environ 30 °C au moment de partir. Cause
localisée : `demandeInitiale()` pose `heure_depart: "09:00"` en dur
(`front/src/ecrans/Demander.tsx:70`), et le parcours « Aujourd'hui » reprend
cette demande sans jamais demander l'heure ni afficher un moyen de la
changer. Météo, tenue, placement des blocs selon le vent : tout est calculé
pour le matin.

Pistes à cadrer, pas tranchées :
- le jour même, partir par défaut de l'heure courante arrondie au quart
  d'heure suivant (et 9 h pour un autre jour) ;
- afficher l'heure de départ sur « Aujourd'hui » et la rendre modifiable en
  un geste ;
- si la séance planifiée d'Intervals porte une heure, la prendre.
Voisin du correctif 0.9.4 (fuseau du conteneur) mais distinct : là l'heure
demandée était bien 09:00, et c'est ce 09:00 qui est faux.

Backlog « le cycliste choisit ce qu'on garde de ses données » (demande du
mainteneur, 25/09/2026 au soir, **revient sur [[Q48]] et [[Q67]]**, non
fait — gel du sprint d'ouverture, à cadrer avant tout code) : aujourd'hui
la règle est unique pour tous (Q48 : « on jette le brut, on garde le
dérivé » ; la branche garée `q67-sans-brut` l'applique en hébergé). Le
mainteneur veut un **choix par personne, explicite et réversible** :

- **Soit conserver** ses sorties importées et ses données, **et autoriser le
  mainteneur à s'en servir pour apprendre et entraîner le modèle** (au-delà
  de sa propre calibration) ;
- **soit demander leur effacement** (ne garder que le dérivé nécessaire au
  service, ou rien).

Quand demander : **clairement, au moment où les données arrivent**, après
avoir branché intervals.icu ou après l'import d'un fichier ou d'une
archive. Pas une case pré-cochée, pas une clause enfouie dans les CGU.

Changer d'avis : depuis Réglages, à tout moment, dans les deux sens, **et
surtout après avoir accepté** — retirer son accord doit effacer (ou exclure
de tout entraînement futur) ce qui avait été conservé à ce titre.

À cadrer, pas tranché :
- ce qu'« entraîner le modèle » couvre exactement (calibration collective,
  priors par catégorie de vélo, routes apprises…) et si c'est anonymisé ou
  agrégé ;
- ce que devient un modèle déjà entraîné quand l'accord est retiré ;
- le défaut tant que la personne n'a pas répondu (le plus protecteur :
  rien de conservé au-delà du dérivé) ;
- l'articulation avec `q67-sans-brut` : cette branche devient le cas
  « refus », et la conservation le cas « accord » ;
- mentions RGPD : base légale (consentement), finalité, durée, preuve du
  consentement horodatée.

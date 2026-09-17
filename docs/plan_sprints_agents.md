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
- **L7.2 — comptes et isolation.** Authentification déléguée Google
  (doctrine §10), isolation par utilisateur **vérifiée côté serveur**.
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

---

**Ce que cette repriorisation ne range nulle part.** Trois fonctions de
qualité du tracé — [[Q29]], [[Q31]], [[Q32]] — n'entrent ni dans l'hébergé ni
dans l'accueil d'un nouveau venu. Elles sont posées en [[Q53]] avec trois
issues possibles ; aucune n'est tranchée, et elles n'ont pas de sprint.

### Après — dépôt public

MIT, anonymisation des documents de cadrage (Q6). Le dépôt peut s'ouvrir
avant le sprint 8 : la publication du code et l'invitation de personnes
sont deux décisions distinctes.

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
  `profile:correct_misplaced_via_points` est ignoré par le serveur) ;
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

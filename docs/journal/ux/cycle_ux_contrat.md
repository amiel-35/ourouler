# Cycle discovery et UX — contrat

Ouvert le 16/09/2026, à la demande du mainteneur : « lance un cycle de
discovery et d'UX pour faire une interface digne de ce nom ».

Ce document dit **ce qu'on conçoit, ce qu'on ne conçoit pas, et ce qui a
déjà été tranché**. Les parcours et les écrans sont dans
`discovery_parcours.md`, ce que le cœur sait déjà rendre dans
`discovery_donnees.md`, l'état de l'art dans `discovery_benchmark.md`.

## Ce qui est conçu ici

Une **interface web multi-utilisateur** : demande d'accès modérée,
assistant de configuration, demande d'itinéraire, consultation de la sortie
du jour. C'est le front du sprint 7 de `plan_sprints_agents.md`, dont le
premier étage — la page du jour servie en ligne — est déjà livré et
déployé.

**Ce n'est pas l'implémentation.** Ce cycle produit des maquettes et des
décisions. L'API, la base, les comptes et le front réel sont un sprint à
part, qui commencera par ces maquettes plutôt que par une page blanche.

## Les quatre arbitrages du mainteneur (16/09/2026)

### 1. L'entrée : lien magique d'abord, fournisseurs tiers ensuite

**V1** — demande d'accès → **le mainteneur valide à la main** → e-mail
d'invitation (Brevo) portant un lien de connexion → l'utilisateur peut
ensuite poser une **passkey**. Aucun mot de passe, nulle part.

**V2** — Google, puis Apple, en plus et non à la place.

**Ceci contredit la doctrine §10.2** telle qu'elle était écrite
(« authentification déléguée, Google d'abord, Apple ensuite »). La
contradiction a été posée au mainteneur, il a tranché, la doctrine est
mise à jour dans la même livraison — c'est la règle de CLAUDE.md.

Ce que la décision garde de la doctrine : **jamais de mot de passe chez
nous**. Un lien à usage unique et une passkey respectent cette règle mieux
qu'un mot de passe ; ce qui change est le fournisseur d'identité, pas le
principe.

Ce que la décision apporte en plus : **la modération est native**. Le
sprint 8 veut qu'Amiel puisse inviter des copains ; avec Google, il aurait
fallu construire une liste d'attente par-dessus une connexion ouverte.

### 2. L'horizon du vent reste à trois jours

Le brief disait « sans vent si à plus de 2 jours ». La mesure du
16/09/2026 sur 2 064 heures dit que la direction tombe dans le bon secteur
93 %, 92 % et 88 % du temps à un, deux et trois jours. `HORIZON_ORIENTATION_J
= 3` reste.

**C'est la mesure qui l'emporte sur l'intuition**, y compris celle du
mainteneur, et c'est lui qui l'a voulu ainsi. Règle absolue 5.

### 3. La clé Intervals : montrer où elle se trouve

L'écran de connexion à intervals.icu doit **guider vers la page où la clé
se génère** (Settings → Developer Settings), pas se contenter d'un champ
vide. La recherche a confirmé que ce geste n'a pas de motif rodé à copier :
dans l'écosystème cycliste, la norme est OAuth avec écran de consentement,
et intervals.icu est l'exception qui expose une clé personnelle.

### 4. Ce qu'on prend à Strava, ce qu'on prend à Apple

Correction explicite du mainteneur, à respecter dans toute la suite :

> « tu parles d'UI, je te parle d'UX sur l'organisation de l'information.
> Strava pour le générateur d'itinéraire est trop bon. Apple est bien pour
> le côté sobre. »

Donc : **l'architecture de l'information du générateur d'itinéraire suit
Strava** — les réglages et le résultat coexistent, on ajuste et on voit
l'effet sans changer d'écran. **La retenue vient d'Apple** — peu de
couleur, la hiérarchie portée par la typographie, rien qui clignote.

Ce n'est pas une charte graphique. C'est une règle de **placement de
l'information**, et elle se juge sur « est-ce que je trouve ce que je
cherche », pas sur « est-ce que c'est joli ».

### 5. L'import de séance : les deux formats simples d'abord

Arbitrage du mainteneur : « le FIT est complexe, peut-être les autres très
simples, et il y a sûrement même des bibliothèques toutes faites ».

**Vérifié, et son intuition est juste — en mieux :**

- `.ZWO` est du XML. `xml.etree` de la bibliothèque standard suffit, et le
  projet s'en sert déjà pour le TCX. **Aucune dépendance nouvelle.**
- `.MRC` est du texte : un en-tête, puis des couples minute / pourcentage.
  **Aucune dépendance nouvelle.**
- `.FIT` est binaire, mais `fitdecode` est **déjà** une dépendance du projet
  (`pyproject.toml`), utilisée par `activites/lecture.py`.

Donc **aucun des trois ne demande d'installer quoi que ce soit**. Ce qui
coûte n'est pas la lecture du fichier, c'est ce qu'on en fait : une séance
prescrite n'a pas la même forme qu'une activité enregistrée, et c'est ce
modèle-là qui manque. Le FIT ajoute en plus une difficulté propre — ses
messages de séance sont d'une autre famille que ses messages d'activité, les
seuls que le projet sait lire aujourd'hui.

**V1 : `.ZWO` et `.MRC`. `.FIT` attend**, et son absence se dit à l'écran
plutôt que de se découvrir au moment du dépôt.

### 6. L'attente : asynchrone, avec la durée annoncée

Arbitrage du mainteneur : « asynchrone ou semi-synchrone en précisant que ça
prend X secondes ».

La deuxième moitié de la phrase est la plus exigeante : **X doit être mesuré,
pas inventé.** La première version des maquettes annonçait « environ une
minute » sans aucune mesure derrière — la relecture adverse l'a relevé, et
elle avait raison.

Mesures du 16/09/2026, sur la machine du mainteneur, contre le BRouter
hébergé : voir `maquettes_v1.html` et la section des mesures ci-dessous. La
durée annoncée à l'écran doit venir de là, et être revue quand le calcul
change.

### 7. La position dans la zone, jamais la valeur

Idée du mainteneur, et c'est la décision structurante de la journée.

**Le problème qu'elle résout.** Le code porte aujourd'hui deux définitions de
« la Z2 » qui ne sont pas d'accord : la table `ZONES_PUISSANCE_DEFAUT`
(56–75 % de FTP) et `puissance_endurance_pct` (0,60), posés à des endroits
différents. Tant qu'un seul homme édite un TOML, ça passe. Le jour où une
interface laisse quelqu'un caler ses zones, les deux divergent en silence.

**Le mécanisme.** L'écran de FTP montre trois valeurs liées :

| | |
|---|---|
| la puissance visée | éditable — pour qui pense en watts |
| la vitesse **à plat, sans vent, lancé** | éditable — pour tous les autres |
| la moyenne compteur attendue | **non éditable** — la réconciliation |

Éditer l'une recalcule l'autre par le modèle physique. Là où l'utilisateur
s'arrête définit une **position dans sa Z2** — et c'est cette position, et
elle seule, qui est **stockée**. Elle se propage ensuite aux autres zones :
qui se met au milieu de sa Z2 prend le milieu de sa Z3 et de sa Z4.

**Et c'est le stockage qui fait la valeur de l'idée.** Mots du mainteneur :
« on stocke la position dans la zone, pas la valeur — comme ça la FTP change
ou les zones décalent, on suit ». Une FTP qui progresse de 12 W déplace tout
l'escalier sans qu'on touche à rien. Stocker des watts aurait recréé
exactement la dette qu'on vient de retirer : une valeur figée à côté d'une
table qui bouge.

`puissance_endurance_pct` cesse donc d'être un réglage : il devient une
conséquence de la position et de la table.

**V2** : un écran avancé où l'on cale chaque zone en watts. Même stockage —
la position, pas la valeur.

### 8. Pourquoi la troisième valeur est obligatoire, et son chiffre

Sans elle, quelqu'un tape dans le champ « à plat » la moyenne qu'il lit sur
son compteur. **Tout l'escalier des zones se décale alors vers le bas** :
mesuré chez le mainteneur, 26 km/h déclarés au lieu de 28,6 le placeraient à
131 W, soit 0,508 × FTP — *sous* sa Z2, à −27 % de la bande. Et cette
position fausse se propagerait à la Z3, la Z4 et toutes les autres.

**Mesuré le 16/09/2026**, sorties libres extérieures d'au moins une heure,
vélos séparés par le capteur de puissance, modèle pris à 0,60 × FTP :

| vélo | sorties | à plat, sans vent | en mouvement | au compteur |
|---|---|---|---|---|
| RCR (route) | 69 | 28,6 km/h | 26,1 (**91 %**) | 24,8 (**87 %**) |
| BMC (chrono) | 22 | 30,4 km/h | 28,5 (**94 %**) | 27,4 (**90 %**) |

Deux lectures qui comptent :

- **Le terrain coûte plus cher que les arrêts.** Sur les 13 points que perd le
  RCR, 9 viennent du relief et du vent, 4 seulement des arrêts et des
  relances. La relation puissance → vitesse est convexe : une côte coûte plus
  que la descente ne rend, un vent de face plus que le vent de dos.
- **Le facteur dépend du vélo**, et pas seulement par l'aérodynamique : le
  chrono perd 10 % quand la route en perd 13. Il ne roule pas sur les mêmes
  parcours.

**Ce que la mesure a corrigé dans ce document.** Une conclusion précédente
proposait de monter `puissance_endurance_pct` de 0,60 à 0,655 au motif que la
puissance normalisée mesurée valait 0,689 × FTP. C'était confondre deux
questions : la NP dit **quel effort est fourni**, pas **quelle distance est
parcourue**. Le mainteneur situe sa vitesse de croisière à plat entre 28 et
30 km/h, et le modèle à 0,60 en prédit 28,6 : il n'y avait rien à corriger.

## Ce qui reste à trancher

Les questions ouvertes sont numérotées dans `discovery_parcours.md`. Les
plus structurantes, dans l'ordre où elles bloquent :

1. **Ce qu'on montre pendant qu'on calcule.** Une génération coûte environ
   150 appels Open-Meteo et plusieurs appels BRouter. C'est le seul endroit
   où l'architecture de l'interface dépend d'une contrainte physique.
2. **Ce qu'on montre à un invité sans historique.** Il n'a aucune
   calibration : les chiffres qu'on affiche à Amiel sont des mesures, ceux
   qu'on afficherait à l'invité seraient des suppositions. Les afficher
   pareil serait un mensonge par mise en page.
3. **Le téléversement de séance** (`.FIT`, `.MRC`, `.ZWO`). Aucun de ces
   formats n'est lu aujourd'hui comme une **prescription** de séance. Ce
   n'est pas un branchement, c'est un lot entier.
4. **Ce qu'on dit de la géographie.** La mesure radiale sur quatre villes a
   montré que le service ne rend pas le même résultat partout. Le dit-on à
   l'utilisateur, et à quel moment ?

## Comment les maquettes seront jugées

- **Aucun écran ne montre une donnée qui n'existe pas.** Chaque chiffre
  affiché est rattaché à un champ de `discovery_donnees.md`, ou marqué
  comme à écrire.
- **Chaque écran a ses états dégradés dessinés**, pas seulement son état
  heureux : pas de séance, météo indisponible, aucune boucle trouvée, une
  seule proposition au lieu de trois.
- **Un cycliste qui n'a pas écrit le code comprend chaque écran** sans
  explication orale.
- **Aucune donnée personnelle** dans les maquettes ni dans le dépôt
  (règle absolue 1) : les exemples sont inventés.

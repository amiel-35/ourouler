# Contrat du sprint 5 — Le vent, la séance entière, la page du jour

Rédigé le 15/09/2026. Le cadrage produit fait foi et se lit d'abord :
`docs/plan_sprints_agents.md`, section « Sprint 5 ». Ce contrat fixe les
interfaces pour dev-feature, testeur-adversarial (en aveugle) et relecteur.

**L5.1 passe en premier et bloque tout le reste.** Les trois propositions
contrastées de L5.3 se classent en partie sur la qualité des blocs ; les
classer sur un placement qui ignore le vent reviendrait à cimenter l'erreur
dans le livrable principal du sprint.

## 0. Pourquoi le vent d'abord — la mesure qui l'impose

Mesuré le 15/09/2026 sur les paramètres calibrés du RCR (masse 100 kg,
CdA 0,2219 m², Crr 0,010615), terrain plat, bloc de 20 min à 210 W :

| Vent | Vitesse | Distance en 20 min |
|---|---|---|
| nul | 33,4 km/h | 11,14 km |
| 20 km/h dans le dos | 39,8 km/h | 13,28 km |
| 20 km/h de face | 27,6 km/h | 9,18 km |

**4,1 km d'écart sur un bloc qui en fait 11.** C'est plus large que la
fenêtre d'antenne (6 km) et sans commune mesure avec les couloirs qu'on
évalue. Le placement peut donc annoncer un bloc sur 3 km de route droite
hors agglomération et poser le cycliste en plein bourg.

L'objection « sur une boucle le vent s'annule » est fausse, et c'est mesuré,
pas supposé. Sur la sortie du 05/04/2026 (`i137367129`, 124 km au départ de
Rennes), Intervals.icu enregistre **27,7 % de vent de face contre 14,3 % de
vent dans le dos** — deux fois plus de face que de dos sur un parcours qui
revient à son point de départ. Sur les 162 sorties route de l'historique qui
portent la météo, la part de vent de face médiane est de 33 % et **monte à
85 %**. Les routes existantes ne sont pas réparties uniformément dans toutes
les directions ; rien n'oblige une boucle à être symétrique vis-à-vis du vent.

## 1. Lot L5.1 — Le vent dans le placement

### 1.1 Ce qui existe déjà et qu'on ne réécrit pas

- `boucle/meteo_trace.evaluer(...)` rend des `Echantillon` le long du tracé,
  **à l'heure de passage**, chacun avec `dist_m`, `t`, `cap_deg`,
  `vent_kmh`, `vent_depuis_deg` (direction d'où vient le vent, interpolée
  angulairement entre les deux heures encadrantes). Pas d'échantillonnage
  par défaut : 5 000 m.
- `seance/placement._Terrain` découpe le tracé en pas de `PAS_M` (100 m)
  avec la pente de chaque pas, et mémorise les vitesses par
  `(puissance arrondie, pente arrondie)`.
- `physique.modele.vitesse_regime(puissance_w, pente, vent_face_ms, p)`
  **prend déjà le vent de face en paramètre** : il est aujourd'hui appelé
  avec `0.0`. Le modèle physique n'est pas à toucher.

Autrement dit le lot est un branchement, pas une invention. Le risque n'est
pas dans la physique, il est dans l'interface et dans le coût.

### 1.2 Ce qu'il faut écrire

**a) Le cap de chaque pas.** `_Terrain` calcule aujourd'hui la pente de
chaque pas ; il calcule en plus son **cap** (degrés, 0 = nord, sens
horaire), par la même géométrie que `boucle.trace.cap_deg`. C'est de la
géométrie pure, calculée une fois à la construction, au même titre que les
pentes.

**b) Un champ de vent interrogeable par position.** Nouvelle classe, dans un
module à elle (`seance/vent.py`), construite à partir des `Echantillon` :

```python
class ChampVent:
    """Le vent le long du tracé, interrogeable à n'importe quelle position."""

    def __init__(self, echantillons: Sequence[Echantillon], facteur_hauteur: float = FACTEUR_HAUTEUR): ...

    def vent_face_ms(self, position_m: float, cap_deg: float, sens: int) -> float:
        """Composante de face en m/s : positive de face, négative dans le dos."""
```

Règles, toutes vérifiables :

- **Composante** : `v_face = V · cos(vent_depuis_deg − cap_effectif)`, où
  `cap_effectif = cap_deg` si `sens > 0`, `cap_deg + 180` sinon. Vent venant
  exactement du cap suivi → composante = +V (plein face). Vent de dos → −V.
  Vent perpendiculaire → 0. **Le vent de travers ne ralentit pas dans ce
  modèle** : c'est une approximation assumée, `vitesse_regime` ne connaît
  qu'une composante longitudinale. À dire dans la docstring, pas à corriger.
- **Facteur de hauteur** : Open-Meteo donne le vent à 10 m ; le cycliste est
  à ~1,5 m dans du bocage. Le projet applique déjà `0.6` (profil
  logarithmique, z₀ = 0,1 m) dans la calibration. **Même constante, importée
  du même endroit, jamais redéfinie.** Si elle est aujourd'hui locale à la
  calibration, elle remonte dans `physique/` et les deux appelants la lisent.
- **Interpolation** : entre deux échantillons distants de 5 km, on interpole
  linéairement la vitesse et **angulairement** la direction (350° et 10° font
  0°, pas 180° — la faute existe déjà dans `meteo_trace._angulaire`, on
  réutilise cette fonction plutôt que d'en réécrire une).
- **Vent inconnu** : un échantillon sans vent (`vent_kmh is None`) ne vaut pas
  zéro. `vent_face_ms` rend `0.0` **et** `ChampVent.complet` est `False` ;
  l'appelant doit pouvoir dire « vent non pris en compte » au lieu de
  laisser croire à un calcul qui n'a pas eu lieu.
- **Champ absent** : `ChampVent` optionnel de bout en bout. `placer(...,
  vent=None)` doit rendre **exactement** ce qu'il rend aujourd'hui, au bit
  près. C'est la garantie de non-régression des 2 936 tests existants.

**c) Le branchement dans `_Terrain`.** La clé de mémoïsation passe de
`(puissance, pente)` à `(puissance, pente, vent_face arrondi)`. Arrondir le
vent à **0,25 m/s** : le balayage des décalages repasse des milliers de fois
sur les mêmes pas, sans arrondi le cache ne sert plus à rien. Vérifier le
coût : le temps de `ourouler sortie` ne doit pas plus que **doubler**, et le
chiffre avant/après est à rapporter.

**d) La circularité, et comment on la coupe.** Le vent à une position dépend
de l'heure de passage, qui dépend du placement qu'on est en train de
calculer. On coupe ainsi : les `Echantillon` sont produits **une fois**, avec
les heures de passage estimées à l'allure d'endurance, comme aujourd'hui ;
le placement les utilise tels quels. Le champ de vent bouge lentement (pas
horaire interpolé) et l'écart d'heure de passage induit par le placement se
compte en minutes. **Ne pas itérer.** Si une relecture veut boucler, elle
doit d'abord mesurer l'écart que ça change.

### 1.3 Critère d'acceptation — le juge existe déjà

Intervals.icu publie, pour chaque activité, `headwind_percent`,
`tailwind_percent`, `prevailing_wind_deg` et `average_wind_speed` (m/s).
**162 des 163 sorties route depuis le 01/12/2023 les portent.** Ces chiffres
sont calculés par leur fournisseur météo, pas par nous : c'est un juge
indépendant.

Script de validation `tests/validation/vent_retrospectif.py` (non collecté
par pytest, lit le cache réel, sur le modèle de `terrain_retrospectif.py`) :

1. Pour chaque sortie route avec `has_weather`, reprendre la trace GPS du FIT
   déjà en cache et le vent d'archive Open-Meteo déjà utilisé par la
   calibration.
2. Recalculer nous-mêmes la part de vent de face et la part de vent de dos,
   avec la règle du secteur ±45° de `meteo.rapport.vent_relatif` appliquée au
   cap local — exactement ce que fait déjà `meteo_trace._resumer`.
3. Comparer à `headwind_percent` / `tailwind_percent` d'Intervals.

**Seuil à tenir : écart absolu médian ≤ 10 points de pourcentage sur les 162
sorties, et aucun biais systématique au-delà de ±5 points.** Un écart plus
grand ne condamne pas forcément notre chaîne — leur découpage en
échantillons et leur définition du secteur de face nous sont inconnus — mais
il doit alors être **expliqué et écrit**, pas absorbé. Si le seuil ne tient
pas, le lot est livré « non vérifié » et le dit en toutes lettres (règle 4).

Second effet mesurable, à rapporter aussi : sur les mêmes sorties, l'erreur
du modèle physique sur la vitesse, avec et sans le terme de vent. Elle doit
baisser ; si elle ne baisse pas, quelque chose est faux et le lot ne passe pas.

### 1.4 Ce qui n'est pas dans ce lot

Pas d'endpoint Intervals non documenté. Vérifié le 15/09/2026 sur
`i137367129` : `/activity/{id}/weather`, `weather-data`, `map-weather`,
`conditions`, `wind` rendent tous 404, et aucun des 12 streams disponibles
ne porte le vent. La carte de leur interface web est calculée côté
navigateur. **Notre source de vent reste Open-Meteo, pour la prévision comme
pour l'archive** ; Intervals ne sert que de juge.

### 1.5 Résultat mesuré le 15/09/2026 — le seuil de biais n'est pas tenu

Écrit ici **en toutes lettres** (règle 4) et pas seulement en commentaire du
script de validation, parce qu'un « non vérifié » que seul un lecteur du code
découvre n'est pas un aveu, c'est un enfouissement.

Sur 161 des 162 sorties (une écartée, aucune archive de vent) :

| Mesure | Obtenu | Seuil du §1.3 | Verdict |
|---|---|---|---|
| Écart absolu médian à `headwind_percent` | 6,6 points | ≤ 10 | tenu |
| Biais | **−7,0 points** | ±5 | **non tenu** |
| 90ᵉ centile | 15,6 points | — | — |

**L'explication, et pourquoi elle ne condamne pas le lot.** Nous comptons
moins de vent de face **et** moins de vent de dos qu'Intervals, donc plus de
travers : c'est la définition du **secteur** qui diffère, pas le vent. Le
biais s'annule vers 55° de demi-angle (écart médian 3,1, biais −1,3) là où
`meteo.rapport.vent_relatif` applique ±45°.

**Décision : on garde nos ±45° et on écrit l'écart.** S'aligner sur ~55°
serait se caler sur une définition qu'on ne connaît pas, et ce secteur sert
aussi à l'affichage de `meteo`.

**Ce que révèle surtout cet écart, c'est que le critère du §1.3 était mal
conçu** — il mélangeait deux choses. Le secteur ±45° ne sert qu'à *dire*
« face » ou « dos » ; la physique du placement, elle, n'utilise pas de
secteur du tout, mais le cosinus continu. Le biais mesure donc un désaccord
de vocabulaire avec Intervals, pas une erreur de calcul.

La vraie preuve du lot est ailleurs, et elle est plus forte (13 053 tronçons,
oracle = la vitesse GPS réelle) :

| Terme de vent | Erreur absolue moyenne sur la vitesse |
|---|---|
| avec le vent | **0,993 m/s** |
| sans le vent | 1,063 m/s |
| **vent retourné** | **1,445 m/s** |

Un signe inversé donnerait l'inverse de cette hiérarchie. C'est le contrôle
qui compte.

**Réserve de la relecture, retenue** : ce contrôle passe par
`physique/calibration._vent_de_face`, pas par `ChampVent`. Il valide la
convention de la calibration, et ne transfère au lot que par transitivité —
transitivité établie par mesure en relecture (`ChampVent.vent_face_ms` ≡
`_vent_de_face` à 1,5·10⁻¹⁴ m/s près sur 20 000 tirages, même fonction de
cap des deux côtés, facteur de hauteur appliqué une seule fois). **À
corriger un jour** : faire passer `erreurs_de_vitesse` par `ChampVent`, pour
que le juge mesure le code que le placement utilise vraiment.

### 1.6 Ce qui reste ouvert à la fin du lot

- **Le branchement dans `ourouler sortie` n'est pas fait.** `ChampVent` est
  livré, testé, validé — et rien ne l'appelle. Au sens de la règle 4, le lot
  n'est donc pas livré tant qu'une commande ne l'exerce pas.
- Le branchement n'est **pas** une ligne : `sortie/commande.py` place *avant*
  d'évaluer la météo, et date la météo avec la vitesse tirée du placement.
  Le §1.2 d écrivait « comme aujourd'hui », ce qui était faux sur le code
  d'aujourd'hui. Il faut donc soit une deuxième passe de placement (placer
  sans vent → heures de passage → météo → replacer avec vent), soit dater la
  météo à l'allure d'endurance, ce qui déplace aussi les heures de la pluie.
  **La deuxième passe est la voie retenue** : elle préserve la datation
  actuelle, et son coût est négligeable (le placement pèse 0,09 s quand
  BRouter en pèse 4,2).
- **Décision produit en attente du mainteneur** : une fois branché, le vent
  entre dans la note de placement, donc il départage les candidates **avant**
  la pluie. Le test `test_a_note_egale_la_pluie_departage` du sprint 4 tombe.
  Branche `l5.1-branchement-sortie`, déposée rouge et volontairement non
  fusionnée.

## 2. Lot L5.2 — La séance entière visible (Q13)

Origine : le mainteneur lit la sortie du 08/02 et demande « t'as pas oublié
l'échauffement ? ». Il n'était pas oublié — 28 min à 155 W, 13,2 km, très
exactement là où le premier bloc démarre — mais **rien ne le montrait**. Ce
qui rend le défaut sérieux : on ne peut pas vérifier ce qu'on ne voit pas, et
c'est précisément ce qu'on lui demande de faire sur la carte.

### 2.1 L'état des lieux

`Emplacement` (`seance/placement.py:192`) porte `etape_idx`, `debut_m`,
`longueur_m`, `demi_tour`, `note`. `Placement.emplacements` ne contient
**que les blocs** : `_dérouler` n'y ajoute rien pour l'échauffement, les
récupérations et le retour au calme, alors qu'il connaît leur position — il
vient de les parcourir pour arriver au bloc suivant.

`sortie/commande.py` liste ces emplacements, donc n'affiche que des blocs.
`sortie/carte.py` colore ces emplacements (`COULEURS_BLOCS`) sur un tracé
gris uniforme (`COULEUR_TRACE`). Conséquence visuelle : on ne distingue pas
« je roule ici pendant l'échauffement » de « cette portion de la boucle n'est
jamais parcourue ».

### 2.2 Ce qu'il faut écrire

**a) `placer` rend la position de chaque étape.** Toutes les étapes de la
séance retenue apparaissent dans l'ordre, avec leur début et leur longueur.
Les non-blocs n'ont **pas** de note — aucun terrain n'est évalué sous une
récupération, c'est la règle du sprint 4 et elle ne bouge pas — donc `note`
devient optionnelle plutôt que d'inventer une valeur neutre. Le champ
`demi_tour` garde son sens pour les récupérations qui en portent un.

**Invariant à tenir et à tester** : les emplacements se suivent sans trou ni
recouvrement, du départ à l'arrivée, et **la somme de leurs longueurs vaut
`distance_totale_m`**. C'est l'invariant qui prouve qu'on montre bien toute
la séance et pas des morceaux.

**Correction du 16/09/2026 — la première rédaction de cet invariant se
contredisait**, et le testeur adversarial l'a trouvée en la mesurant. Elle
faisait de `distance_totale_m` **et** de `jalons_m` deux autorités de la même
chose ; elles ne peuvent pas toutes les deux avoir raison. Sur une boucle
fermée de 48 km, `_variante_demi_tour` ajoute `2 × besoin_m` à la distance
mais range dans `jalons_m` le point de demi-tour **écrêté** par
`_Terrain.dans_le_trace` : 96 000 m de jalons contre 97 814 m de distance.

L'arbitrage n'est pas arbitraire — cet écrêtage est une approximation
**connue et documentée depuis le sprint 4** (docstring de `dans_le_trace` :
« la seule approximation du parcours rendu par `trace_parcourue` ») :

- **`distance_totale_m` fait autorité pour la distance.** L'invariant porte
  sur elle, et sur rien d'autre.
- **`jalons_m` fait autorité pour la géométrie** — où l'on est sur le tracé —
  avec son écrêtage aux bouts de boucle. Ce n'est pas une autorité de
  distance, et **on ne la corrige pas ici** : ce serait changer
  `trace_parcourue`, hors périmètre.

**Conséquence : la continuité s'exprime au compteur kilométrique, pas en
position sur le tracé.** `debut_m` est une position (`_couloir` rend
`min(a, b)`), pas un relevé de compteur : sur un demi-tour, la récup part de
P, monte à P+b, revient à P. « Le début de chacun est la fin du précédent »
est donc **faux au sens du tracé et vrai au sens du compteur**. `debut_m` ne
change pas de sémantique — les tests du sprint 4 restent valides — et le
compteur, si l'affichage en a besoin (« du km 13,2 au km 21,4 », qui est ce
que le mainteneur veut lire), est un **champ ajouté explicitement**, jamais
`debut_m` détourné.

**Le piège le plus coûteux du lot**, mesuré lui aussi : seize sites lisent
`e.note.note` sans condition (`sortie/commande.py` 144, 148, 1077, 1080,
1217 ; `sortie/carte.py` 166, 172, 185). Ils lèveront `AttributeError` dès
qu'un non-bloc arrivera — bruyant, donc ce n'est pas le danger. Le danger est
le réflexe `if e.note else 0.0` qui les ferait taire **en comptant faux** :
un `0.0` dans la moyenne pondérée fait passer `note_terrain` de 10,00 à 2,99
sans un mot. À ces seize endroits on **filtre sur les blocs**, on ne met
jamais de valeur par défaut.

**Compatibilité** : les appelants qui ne veulent que les blocs doivent le
rester simplement — une propriété `blocs()` ou un filtre sur le type
d'étape. **Aucun test existant du sprint 4 ne doit changer de sens** ; s'il
faut en modifier un, c'est un signal, pas une formalité.

**b) L'affichage texte liste toutes les étapes**, avec leur kilomètre de
début et de fin. Les blocs gardent leur note, les autres n'en ont pas et la
colonne reste vide plutôt que de porter un tiret ambigu.

**c) La carte montre la séance entière.** Échauffement et retour au calme
dans une teinte neutre **distincte du tracé non parcouru**, récupérations
déjà en pointillés. Le lecteur doit pouvoir répondre d'un coup d'œil à :
« où est-ce que je roule, et à quelle intensité ? ».

### 2.3 Critère d'acceptation

Sur une vraie séance à blocs du mainteneur, la sortie texte et la carte
doivent montrer **l'intégralité** de la séance, et la somme des longueurs
affichées doit égaler la distance du parcours. Le contrôle qui compte, dans
ses mots : l'échauffement du 08/02 était de 13,2 km et invisible — il doit
maintenant se voir, et se voir au bon endroit.

### 2.4 Ce qui n'est pas dans ce lot

Pas de changement de la règle de placement, pas de nouvelle note, pas de
nouveau critère de tri. On rend visible ce qui est déjà calculé.

## 3. Lot L5.3 — Trois propositions contrastées

Cadrage à écrire avant ouverture. Le point dur, dans les mots du mainteneur :
trois propositions ne servent à rien si elles se ressemblent, et les trois
premières d'un même classement se ressemblent souvent.

### 3.1 L'orientation au vent est un axe de contraste, pas une constante

Décision du mainteneur, 15/09/2026, à propos de l'arbitrage « le vent
départage-t-il avant la pluie ? » : **« on peut laisser arbitrer le
user ? »** — et il ajoute aussitôt le choix suivant, qui est du même
ordre : *vent dans le dos au départ de la sortie, ou à la fin, ou plutôt
vent latéral ?*

Conséquence de conception, et elle est structurante : ces questions ne se
tranchent pas une fois pour toutes dans le code. **Elles deviennent une
dimension sur laquelle on fabrique des propositions contrastées**, chacune
résumable en une phrase que le cycliste comprend sans explication :

- « vous rentrez avec le vent dans le dos » — dure au début, facile au retour ;
- « vent dans le dos au départ » — vous partez vite, vous rentrez dans le dur ;
- « vent de travers » — ni l'un ni l'autre, mais jamais de répit non plus.

**Vent contre pluie relève du même principe** (confirmé par le mainteneur le
15/09/2026 : « oui et priorité vent ou pluie »). Au lieu d'arbitrer, une
proposition est « la plus sèche » et une autre « la mieux orientée ». La
tolérance de note introduite au branchement de L5.1 reste utile comme
**départage** quand rien ne distingue deux candidates ; elle cesse d'être un
arbitrage produit.

### 3.1.1 « Laisser arbitrer le user » a une bonne et une mauvaise forme

À tenir fermement, parce que la pente est glissante :

- **Mauvaise forme** : un fichier de configuration avec douze réglages que
  personne ne touche, et des valeurs par défaut qui décident en réalité à la
  place du cycliste tout en se donnant l'air de lui laisser le choix.
- **Bonne forme** : il arbitre **en regardant**, pas en réglant. Trois
  propositions, une carte chacune, une phrase qui dit ce qui les distingue.
  Le réglage n'existe que pour **figer** une préférence quand on en a assez
  de la reprendre à chaque sortie.

Règle de conception qui en découle : **tout réglage ajouté doit avoir un
défaut qui n'a pas besoin d'être touché**, et toute question produit qui se
pose à chaque sortie se traite par le contraste, pas par un champ de
configuration. Un réglage supplémentaire se justifie devant le mainteneur,
il ne s'ajoute pas au fil de l'eau.

C'est aussi la bonne forme vis-à-vis de la doctrine §10 (« le profil est une
donnée, pas une constante ») : une préférence d'orientation au vent est un
champ de profil, pas une constante de module. Elle devra suivre l'utilisateur
dans la version hébergée.

### 3.1.2 Jusqu'à quand la prévision de vent est-elle fiable ? — mesuré le 16/09/2026

Question du mainteneur. Elle décide de l'horizon sur lequel l'outil a le
droit de proposer une orientation au vent.

**Horizon des modèles**, relevé le 16/09/2026 : AROME France HD (notre
principal) **67 h**, Météo-France seamless 115 h, ICON seamless (notre second
avis) 168 h. Au-delà de deux jours et demi, la haute résolution ne répond
plus du tout.

**Justesse**, 2 064 heures à Rennes, du 16/06 au 09/09/2026, **référence =
archive ERA5** (qui assimile les observations) :

| Prévu | Erreur vitesse | Erreur direction | Direction dans le bon secteur de ±45° |
|---|---|---|---|
| 1 jour avant | 1,3 km/h | 7° | 93 % |
| 2 jours | 1,8 km/h | 8° | 92 % |
| 3 jours | 2,1 km/h | 11° | 88 % |
| 4 jours | 2,1 km/h | 13° | 85 % |
| 5 jours | 2,2 km/h | 17° | 78 % |

**Règle produit qui en découle : on ne propose une orientation au vent que
jusqu'à 3 jours.** Au-delà, AROME est déjà sorti du jeu et une direction sur
cinq se trompe de secteur entier ; l'outil dit qu'il ne sait pas plutôt que
de promettre « vous rentrerez avec le vent dans le dos ». C'est la règle 5
appliquée : afficher un désaccord plutôt que le moyenner.

**Deux réserves, dont une qui corrige une affirmation antérieure.**

1. Une première mesure prenait pour référence la meilleure estimation
   courante d'Open-Meteo, et j'avais annoncé que l'erreur contre la réalité
   serait *plus grande*. Elle est **plus petite** (7° contre 11° à un jour) :
   cette première référence est elle-même un autre modèle, on mesurait donc
   un désaccord entre modèles. Signe qui le prouve : dans la mesure contre
   ERA5, le « run du jour » score moins bien (11°) que la prévision de la
   veille (7°) — impossible pour un même modèle, normal pour deux modèles
   différents. C'est AROME qui répond sur le court terme, et AROME s'écarte
   plus d'ERA5 parce qu'il voit du relief local qu'ERA5 lisse à 25 km.
2. **ERA5 n'est pas le vent que le cycliste sent.** À 25 km de maille, elle
   ignore le bocage, les vallons, les haies. L'écart réel est plus grand que
   7°, et on n'a aucun moyen de le mesurer sans anémomètre embarqué.

### 3.1.3 Trois constats du 16/09/2026 qui cadrent L5.3

Relevés en rejouant la commande sur les vraies données après la correction
des feux, et en regardant la carte avec le mainteneur.

**a) Le classement des routes ne compte pas dans la note d'un bloc.**
`HIGHWAY_TRAFIC` (`boucle/couts.py:36`) sert à choisir la boucle et à refuser
un demi-tour sur une départementale passante (`seance/terrain.py:455`). Il
**n'entre pas** dans la note du couloir. Un bloc peut donc tomber sur une
départementale rapide sans le moindre malus. Repéré à l'œil par le
mainteneur sur le bloc 4 du 01/09 : « me questionne plus sur l'absence de
feux et la capacité à rouler à plus de 35 ».

**b) Pour une séance sans bloc, le tri ne regarde presque rien.** Mesuré sur
la vraie EF 2 h du 12/09 : les cinq candidates notent 0,00 / 0,05 / 0,08 /
0,15 / 0,29 — ces écarts ne sont que la pénalité de dépassement du retour au
calme. Le terrain n'est pas évalué, faute de bloc sous lequel l'évaluer.
Conséquence concrète : la retenue porte **24,1 km de routes à trafic** sur
55,2, quand la quatrième n'en a que 20,9 et la cinquième 98 % de routes déjà
connues du mainteneur. Ni le trafic ni la part de routes connues — tout un
lot du sprint 3 — n'entrent dans le classement.

C'est d'autant plus lourd que **son plan actuel ne contient aucune séance à
blocs en extérieur** : sur 85 jours, toutes les séances vélo planifiées
dehors sont des EF ou des sorties cool, les HIT sont tous sur home-trainer.
Le cas « endurance » n'est donc pas un cas secondaire, c'est **son cas
courant**.

**Conséquence pour L5.3** : les axes de contraste ne peuvent pas reposer sur
la seule note de terrain sous les blocs, qui vaut zéro la plupart du temps.
Ils doivent couvrir le trafic, la part de routes connues, l'orientation au
vent et la pluie. Sans quoi les trois propositions seront identiques sur une
EF, c'est-à-dire sur la majorité des sorties.

**c) La forme de la séance décide de la géographie.** Constat du mainteneur :
« c'est la Z2 de 5 min à la fin qui fait que le moteur reste près de la
ville ». Vérifié — avec la vraie EF 2 h, la boucle passe à 55,2 km pour
2 h 00 pile et sort de l'agglomération. Les séances home-trainer ont des Z2
volontairement tronquées et **ne doivent pas servir de référence de test**.

### 3.1.4 Deux points remontés le 16/09/2026, à traiter plus tard

**a) Le demi-tour est autorisé, pas à mettre en avant.** Mots du mainteneur :
« le demi-tour est autorisé mais pas forcément à mettre en avant. Mais ça on
verra après, et ça peut être un choix visuel ». Donc : aucune règle nouvelle
dans le tri, et « sans demi-tour » devient un **axe de contraste** de L5.3 —
c'est exactement le genre de proposition qui se choisit en un coup d'œil.

Le motif est constant sur les trois sorties regardées ce soir : le tri retient
une candidate défendable, mais pas celle que le mainteneur prendrait. Sur la
HIT étendue, la retenue dépasse de 29 min avec deux demi-tours, quand la
quatrième roule 81,1 km en 2 h 54 **sans aucun demi-tour** et place deux blocs
sur quatre contre un sur quatre.

**b) Défaut d'affichage : le profil d'altitude superpose les blocs d'un
demi-tour.** Repéré par le mainteneur sur la HIT étendue — le bloc 1 (rouge)
et le bloc 3 (orange) se dessinent au même endroit vers le km 26, étiquettes
imprimées l'une sur l'autre.

Cause : L5.2 a fait passer le texte et les infobulles au **compteur
kilométrique** (`debut_parcouru_m`), mais la bande du profil d'altitude est
restée sur la **position dans le tracé** (`debut_m`). Après un demi-tour, deux
blocs partagent la même position et se recouvrent. Correction : le profil doit
suivre le parcours réellement roulé, comme le texte — chaque bloc apparaît
alors une fois, à sa place.

### 3.2 Mesurer la préférence avant de la demander

Avant d'ajouter un réglage, on regarde ce que le mainteneur **fait déjà** :
162 sorties avec vent enregistré et traces GPS permettent de dire s'il part
face au vent pour rentrer avec. Précédent du sprint 3 : les poids du terrain
avaient été calibrés contre son intuition, et la mesure l'avait contredit sur
les côtes — il ne les évite pas.

**Résultat, mesuré le 16/09/2026 sur 161 sorties : il n'y a pas de
préférence. C'est du bruit.**

| Angle | Résultat | p |
|---|---|---|
| Premier quart plus de face que le dernier | 82 sorties sur 161 (50,9 %) | 0,87 |
| Ampleur | médiane +0,14 m/s, moyenne +0,04 (écart-type 2,22) | — |
| Majoritairement en travers | 47,8 % | 0,64 |
| Sous vent **habituel** (ouest-sud-ouest, 93 sorties) | 54,8 % | 0,41 |
| Sous vent **inhabituel** (nord/est, 68 sorties) | 45,6 % | 0,54 |
| Jours de vent fort (> 6 m/s, 16 sorties) | 50,0 % | 1,0 |

Une pièce non truquée donnerait 50 %. Le contrôle géographique, qui devait
départager « préférence » et « artefact du réseau routier », **confirme la
nullité au lieu de la contredire** : l'effet n'existe dans aucun des deux
sous-groupes.

**Ce que ce résultat ne dit pas, et c'est l'essentiel.** Il ne prouve pas que
le mainteneur n'a pas de préférence — il prouve qu'il n'en a jamais exprimé
une. Et c'est attendu : on ne peut pas choisir son orientation au vent sans
un outil qui annonce le vent à l'avance, et cet outil n'existait pas. La
mesure constate donc l'absence d'un moyen, pas l'absence d'un goût.

**Conséquence : on ne pré-sélectionne rien.** La question se pose au
cycliste, avec « peu importe » comme réponse valable qui retombe sur les
trois propositions contrastées. Et elle redeviendra mesurable au sprint 6,
une fois que l'outil aura permis d'y répondre — c'est alors seulement que le
choix voudra dire quelque chose.

**Réserve de l'agent, retenue** : les sous-groupes sont modestes (68 sorties
sous vent inhabituel, 16 jours de vent fort), donc l'absence de signal y a
une puissance statistique limitée. Elle va dans le même sens que la mesure
globale, elle ne la renforce pas beaucoup.

Piège écarté par construction dans cette mesure : un effet apparent peut
n'être que de la géographie. Le vent dominant en Bretagne vient de
l'ouest-sud-ouest, et si ses routes habituelles partent majoritairement dans
une direction, le résultat serait un artefact du réseau routier. Le contrôle
qui décide : l'effet tient-il les jours où le vent vient du nord ou de l'est ?
Script : `tests/validation/orientation_vent_retrospectif.py`.

### 3.3 Le lot, tel qu'il s'ouvre le 16/09/2026

Cadré après les quatre constats ci-dessus, donc sur de la mesure et non sur
une intuition. Le point dur, dans les mots du mainteneur : **trois
propositions ne servent à rien si elles se ressemblent**, et les trois
premières d'un même classement se ressemblent presque toujours.

#### 3.3.1 Le risque à écarter, nommé d'abord

Trois candidates peuvent différer nettement **sur le papier** — 1,93 contre
2,30 contre 4,72 — et paraître identiques **sur une carte**. Une note de
placement n'est pas une différence perceptible.

Donc la règle de conception : **deux propositions ne sont contrastées que si
elles diffèrent sur quelque chose que le cycliste voit ou sent.** La liste
est courte et elle sort des trois soirées de mesure : la durée réelle, la
présence de demi-tours, la traversée de ville, l'orientation au vent, la
pluie, la part de routes qu'il connaît déjà. Pas la note.

#### 3.3.2 Les axes, et pourquoi ceux-là

| Axe | Mesure existante | Pourquoi il discrimine |
|---|---|---|
| Terrain sous les blocs | `Placement.note_terrain` | Le cœur du produit — **mais vaut zéro sur une séance sans bloc**, donc jamais seul |
| Durée tenue | écart entre `duree_totale_s` et la séance | Mesuré trois fois : le tri retient des dépassements de 29 à 43 min |
| Demi-tours | `Placement`, déjà compté | « Autorisé mais pas forcément à mettre en avant » |
| Pluie | `MeteoTrace.pluie_cumulee_mm` | Déjà au tri, en second rang |
| Orientation au vent | `ChampVent`, part de face par quart | Le seul axe que le mainteneur a demandé explicitement |
| Ville | densité de nœuds tagués au km | Ce qu'il appelle « la ville » : feux, passages piétons, ralentisseurs |
| ~~Routes connues~~ | — | **Retiré le 16/09/2026 : contredit le contrat du sprint 3** (voir ci-dessous) |
| **Recouvrement entre propositions** | mailles de 30 m, `apprentissage.routes.cle_maille` | Le seul axe qui mesure la différence **entre** les boucles et non leurs attributs |

**Erreur corrigée le 16/09/2026 — l'axe « routes connues » est retiré.**
`BaseRoutes.part_connue` porte la règle du sprint 3 dans sa docstring :
« **Informatif seulement.** Le contrat l'interdit dans tout score : les traces
ne couvrent qu'une partie du territoire, et pénaliser l'inconnu condamnerait
d'avance toute direction jamais explorée. » La première rédaction de ce
tableau l'avait mis en axe sans voir la règle. Et la règle est bonne : le
mainteneur a lui-même demandé au sprint 3 d'aller « tester des routes sud
sud-ouest pour voir ». La part connue reste **affichée**, peut servir à
décrire une proposition retenue pour une autre raison, et n'entre ni dans une
note ni dans la sélection.

**Le recouvrement entre propositions — idée du mainteneur, 16/09/2026** :
« pas forcément une bonne idée mais un seuil de pourcentage de route identique
entre des propositions ». C'est meilleur que les six autres axes pour ce qu'il
mesure, et il faut le dire : **les autres mesurent des attributs de chaque
boucle, celui-ci mesure la différence entre les boucles elles-mêmes.** Deux
boucles peuvent avoir des notes très éloignées et emprunter les mêmes routes ;
elles se ressembleront sur la carte quoi qu'en disent les chiffres.

Il s'applique en **contrainte de sélection** et non en note : deux
propositions dont le recouvrement dépasse le seuil ne sont pas contrastées,
quelles que soient leurs notes. La machinerie existe — `cle_maille` découpe
en mailles de 30 m et `part_connue` calcule déjà une part de kilomètres
tombant dans un ensemble de mailles ; on réutilise, on ne réécrit pas. Le
seuil se **mesure** sur la distribution des recouvrements deux à deux de
candidates réellement générées, il ne s'invente pas. Le recouvrement n'étant
pas symétrique quand les boucles diffèrent en longueur, la convention retenue
doit être écrite.

**La densité de marqueurs au kilomètre est à écrire** : c'est la seule
mesure nouvelle du lot, et elle remplace la détection de zone bâtie dont
l'angle mort est documenté (`terrain.MAXSPEED_BATI_KMH`). Elle se valide
contre les 162 sorties : les portions que le mainteneur roule vraiment
doivent en porter moins que des portions tirées au hasard, comme les poids
du terrain au sprint 3.

#### 3.3.3 Choisir trois représentants éloignés

On génère plus de candidates qu'aujourd'hui (`candidates = 5`), on les note
sur chaque axe, puis on retient **trois représentants éloignés les uns des
autres** — pas les trois premières d'un tri unique.

**Contrainte de coût, chiffrée** : BRouter pèse ~4,2 s par boucle quand tout
le reste d'une sortie coûte 0,5 s. Le nombre de candidates est donc le seul
poste qui compte. Mesure le temps total et rapporte-le ; si générer plus
coûte trop, dis-le plutôt que de livrer une commande qui prend une minute.

#### 3.3.3 bis — Ce que « éloignées » veut dire (16/09/2026 ; a) et b) retirés le 17/09/2026 par [[Q43]])

> **Amendement du 17/09/2026 — le recouvrement est le seul verrou.** Les
> conditions a) et b) ci-dessous **ne décident plus** qui entre dans le trio.
> Mots du mainteneur : *« oui, et en fait le parcours lui-même est distinctif
> en soi »*. Elles visaient les descriptions, pas les tracés, et elles
> jetaient des boucles franchement différentes — mesuré : quatre candidates à
> **1,4 %** de recouvrement médian n'en donnaient qu'une seule proposition.
>
> Elles gardent un rôle, et un seul : **le droit d'écrire une phrase.** Une
> proposition ne dit « la plus sèche » que si elle l'est de la marge écrite
> ici. Une proposition sans phrase est désormais normale — son tracé la
> distingue — et quand **aucune** n'en a, le produit le dit ([[Q45]],
> `motif_equivalence`).
>
> Seule c) décide, et elle décide seule.

Le testeur adversarial a relevé que la première rédaction ne le chiffrait
pas, et que c'était **le plus large trou de sa couverture** : une
implémentation rendant trois propositions séparées de 1 % serait passée. Il
avait raison, et le trou venait du contrat, pas du code.

**Ce que ça ne veut pas dire : une distance dans un espace d'axes
normalisés.** Normaliser sept grandeurs hétérogènes — des minutes, des
millimètres, un compte de demi-tours, des km équivalents — demande des poids
arbitraires, et un seuil sur cette distance serait infalsifiable.

Trois propositions sont contrastées quand **les trois conditions** tiennent :

a) **Chacune est la meilleure des trois sur au moins un axe**, et sur un axe
   différent de celles des deux autres. Aucune n'est là pour faire nombre.
b) **Elle l'est d'une marge exprimée dans l'unité de l'axe**, jamais en
   pourcentage d'une note — être meilleur de 1 % n'est pas une différence
   pour un cycliste. Point de départ, à ajuster si la mesure contredit :
   durée ≥ 10 min ; demi-tours : un compte différent ; pluie ≥ 0,5 mm ;
   vent : une catégorie relative dominante différente ; ville : un écart de
   densité chiffré par la mesure du lot ; terrain : au moins 1,0 km
   équivalent, soit le prix d'un feu (`POIDS_CARREFOUR`).
c) **Le recouvrement de routes reste sous le seuil mesuré** (§3.3.2).

~~Et le garde-fou qui prime sur les trois : **si la phrase n'est pas
écrivable et vraie, la proposition n'existe pas.** On en rend deux, et on le
dit.~~ **Retiré le 17/09/2026 ([[Q43]]).** Ce qui le remplace, et qui reste
absolu : *si la phrase n'est pas vraie, on ne l'écrit pas* — mais la
proposition, elle, existe toujours.

#### 3.3.3 ter — Les noms publiés

`--json` : la phrase sous `distinction`, l'axe qui la motive sous
`axe_distinctif`, la densité sous `densite_marqueurs_km`, la question du vent
sous `question_vent`, `motif_deux_propositions` quand il n'y en a que deux, et
**`motif_equivalence` quand aucune ne se détache des autres** ([[Q45]], ajouté
le 17/09/2026). `distinction` et `axe_distinctif` valent `null` sur une
proposition que rien ne distingue : c'est un état normal depuis [[Q43]], pas
une donnée manquante.

Deux conventions reprises d'ailleurs plutôt qu'inventées :

- **Le seuil de vent de la question est `SEUIL_AFFICHAGE_VENT_KMH` (8 km/h)**,
  celui des flèches de la carte. Une constante, un sens : la question se pose
  exactement quand les flèches se dessinent. Si le vent ne mérite pas d'être
  montré, il ne mérite pas qu'on demande son orientation.
- **La densité inconnue vaut `None`**, comme `note` pour les non-blocs depuis
  L5.2. Et l'invariant du sprint 3 tient : une portion sans nœud tagué n'est
  pas « la campagne prouvée », c'est « on ne sait pas », et ce n'est **jamais
  un malus**.

« Jusqu'à 3 jours » est **inclusif** : le jour 3 tient 88 % de directions dans
le bon secteur (§3.1.2), le jour 4 non.

**Chaque proposition porte une phrase qui dit ce qui la distingue des deux
autres**, en langage de cycliste et jamais en langage de note : « vous
rentrez avec le vent dans le dos », « aucun demi-tour », « la plus sèche »,
« 20 minutes de moins », « elle évite les villages ». ~~Si aucune phrase
n'est écrivable, c'est que les trois ne sont pas contrastées — et il vaut
mieux n'en proposer que deux et le dire.~~

**Amendé le 17/09/2026 ([[Q43]], [[Q45]]).** Une proposition sans phrase est
une proposition dont le tracé parle seul, et la carte le montre. Quand aucune
des trois n'en a, c'est le lot qui parle : « ces trois boucles se valent,
choisissez où vous voulez aller », avec ce qui, mesuré, ne les sépare pas.

#### 3.3.4 La question posée avant la recherche

Idée du mainteneur, qui réduit aussi l'espace de recherche : demander avant
de chercher plutôt que contraster après. « Pour moi ça peut être une question
avant de lancer la recherche. »

Forme retenue : une option d'orientation au vent, dont **« peu importe » est
une réponse valable** et le défaut — elle retombe alors sur les trois
propositions. Quand il répond, on cherche dans cette direction.

**Deux gardes, tous deux mesurés :**

- **On ne pose la question que si le vent a un effet.** Vent médian 14 km/h
  mais descend à 2,5 : sous le seuil, l'orientation ne change rien de
  perceptible et la question n'apprend qu'à cliquer sans lire.
- **On ne la pose pas au-delà de 3 jours.** §3.1.2 : à 3 jours la direction
  tombe dans le bon secteur 88 % du temps, à 5 jours 78 %, et AROME s'arrête
  de toute façon à 67 h. Au-delà, l'outil dit qu'il ne sait pas.

#### 3.3.5 Ce qui n'est pas dans ce lot

Pas de page HTML (c'est L5.4), pas de correction du profil d'altitude ni des
flèches au-delà d'un demi-tour (§3.1.4 b), pas de nouvelle règle de
placement. On note, on contraste, on explique — on ne replace pas.

#### 3.3.6 Résultat du lot, mesuré le 16/09/2026

**a) La densité de marqueurs discrimine les candidates, mais elle ne prédit
pas la préférence du mainteneur — et la mesure dit l'inverse de l'hypothèse.**

`tests/validation/marqueurs_retrospectif.py`, 111 sorties d'entraînement
réelles (≥ 40 km, partant de moins de 5 km du départ configuré, rejouées une
par une dans BRouter) contre 143 boucles proposées par le moteur aux mêmes
distances, dans 12 directions :

| | n | min | q1 | médiane | q3 | max |
|---|---|---|---|---|---|---|
| **Sorties réelles** | 111 | 1,17 | 1,88 | **2,91** | 3,60 | 6,71 |
| **Boucles proposées** | 143 | 0,69 | 1,21 | **1,50** | 2,01 | 3,94 |

Rapport des médianes **1,94** (le seuil du lot était 0,70, dans le sens
inverse). Rang apparié : médiane **0,92** — 77 sorties réelles sur 111 sont
**au-dessus** de la médiane du lot proposé de leur longueur. L'écart est
monotone en distance : les boucles proposées se dépeuplent quand elles
s'allongent (1,98 à 60 km → 0,98 à 170 km), ses sorties réelles non (2,72 →
3,03). Ce n'est donc pas un artefact du couloir de départ, qui se diluerait
dans les deux populations de la même façon.

**Ce que ça veut dire, et ce que ça ne veut pas dire.** La mesure ne dit pas
que l'axe est inutile : sur une même journée, les cinq candidates vont de 1,25
à 3,42 marqueurs au kilomètre — un facteur 2,7, soit 125 arrêts d'écart sur
une boucle de 56 km. L'axe **sépare** très bien. Ce qu'il ne fait pas, c'est
prédire lequel il choisirait : ses vraies sorties portent **deux fois plus**
de feux, stops et passages piétons que ce que le moteur lui propose. Il roule
de bourg en bourg, le moteur roule dans la campagne.

**Conséquence appliquée** : la densité est un axe de **contraste et de
description** (« elle évite les villages »), jamais un signal de qualité dans
un score. **Question au mainteneur** : veut-il que « moins de marqueurs » reste
le côté valorisé de l'axe (ce que le contrat supposait) ou la mesure
doit-elle inverser la phrase ?

Deux limites du protocole, à lire avec le chiffre : le comparateur est fait de
boucles `fastbike`, un profil qui fuit déjà le trafic, donc le test est
conservateur ; et `crossing` pèse deux marqueurs sur trois dans les deux
populations, ce qui fait de la densité surtout une densité de passages
piétons marqués.

**b) Un axe manquait au tableau §3.3.2 : le trafic.** §3.1.3 le demandait
pourtant en toutes lettres (« les axes de contraste doivent couvrir le
trafic »). Il est ajouté, sous la forme d'une **part de la boucle** et non de
kilomètres. Mesuré sur 35 boucles proposées à 40, 60 et 80 km : q1 34,8 %,
médiane 41,1 %, q3 49,5 %, écart interquartile 14,7 points — d'où un pas de
10 points (`contraste.PAS_TRAFIC_PART`).

**c) Le recouvrement de routes n'a pas de plancher, et il suit la
direction.** Recouvrements deux à deux de 12 boucles de 60 km réparties sur
l'horizon : 28,2 % de médiane à 30° d'écart d'azimut, 14,4 % à 60°, 8,0 % à
90°, **0,4 % à 180°**. Le couloir de départ ne fausse donc rien : tout
recouvrement mesuré est de la route vraiment commune. Seuil retenu **25 %**
(`contraste.SEUIL_RECOUVREMENT`), juste au-dessus de ce que produisent deux
directions franchement différentes et juste en dessous de deux directions
voisines ; en absolu, 15 km de route identique sur une boucle de 60.

**d) Le coût : BRouter est trois fois moins cher que le contrat le supposait,
et ce n'est plus lui qui borne.** Mesuré sur le serveur du mainteneur le
16/09/2026, 5 candidates :

| poste | EF 2 h du 12/09 | HIT étendue du 08/09 |
|---|---|---|
| question du vent (**nouveau**, 1 appel Open-Meteo) | 112 ms | 187 ms |
| BRouter (5 boucles) | 3 623 ms | 4 982 ms |
| placement sans vent | 60 ms | 479 ms |
| replacement avec vent (Open-Meteo × 5) | 319 ms | 851 ms |
| coûts + météo + routes connues (Open-Meteo × 5) | 259 ms | 530 ms |
| contraste (**nouveau** : marqueurs + recouvrement) | 13 ms | 18 ms |
| **total** | **4,4 s** | **7,0 s** |

BRouter coûte **0,7 à 1,0 s par boucle**, pas 4,2 s. Le lot ajoute 3 % au
total. **Mais le poste qui borne est Open-Meteo, pas BRouter** : la commande
fait `1 + 2 × candidates` appels, et à 8 candidates (17 appels) l'API rend
`HTTP 429 — Minutely API request limit exceeded`, ce qui fait disparaître la
pluie, le vent et la tenue.

**Conséquence : on n'augmente pas le nombre de candidates**, contrairement à
ce que §3.3.3 envisageait. Vérifié sur l'EF du 12/09 : à 5 candidates, deux
propositions contrastées en 4,8 s ; à 8, toujours deux, en 6,8 s et sans
météo ; à 12, 9,4 s. Générer plus ne produit pas un troisième contraste ici —
ça produit un 429. Réduire les appels Open-Meteo (un seul appel groupé pour
toutes les candidates) est le vrai levier, et c'est un lot à part.

**e) Trois propositions ne sont pas toujours possibles, et c'est mesuré.**
Sur l'EF 2 h du 12/09 — le cas courant du mainteneur —, cinq candidates
partagent la même pluie (0,0 mm), le même terrain (0,00, faute de bloc), le
même nombre de demi-tours (0) et la même orientation au vent (aucune, 1 km/h
au départ). Deux axes seulement portent du signal : la durée et le trafic.
La commande rend donc **deux** propositions et écrit pourquoi. Sur les deux
journées à blocs, elle en rend trois.


#### 3.3.7 Deux défauts trouvés par les tests adversariaux — corrigés le 17/09/2026

Le croisement avec les 163 tests écrits en aveugle en a trouvé deux qui
tenaient, et un faux positif qu'il faut nommer aussi.

**a) L'axe « durée » comparait des durées nues, et faisait mentir une phrase.**

Le contrat §3.3.2 écrit « durée tenue : écart entre `duree_totale_s` **et la
séance** ». `Profil.duree_s` portait la durée brute et `profil()` ne recevait
jamais la séance : la candidate la plus courte gagnait l'axe. Cas mesuré, sur
une séance de 7 200 s :

| distance | durée | ce que c'est |
|---|---|---|
| 54,2 km | 7 151 s | retour au calme entier |
| 22,0 km | 2 905 s | retour au calme amputé de 60 % — **gagnait l'axe** |

La phrase rendue était « **71 minutes de moins** », présentée comme un
avantage. Elle voulait dire « vous ne roulez pas votre séance ». Une phrase
est une affirmation et elle doit être vraie ; celle-là était fausse de la pire
façon, parce que le mensonge était flatteur.

**Corrigé.** `Profil` porte `depassement_s`, signé — positif on rentre plus
tard (normal, le retour au calme est là pour ça), négatif la séance est
amputée (pas normal). L'axe compare la **valeur absolue** : dépasser de 20 min
et amputer de 20 min ratent la cible d'autant. Et **une séance amputée ne
gagne jamais l'axe**, quelle que soit sa marge — l'amputation est déjà payée
par `PENALITE_SEANCE_NON_TENUE`, la récompenser ici la paierait deux fois en
sens inverse.

Ce qui décide qu'une séance est amputée **n'est pas un seuil inventé dans
`contraste`** : c'est le verdict que le placement rend déjà contre la fenêtre
fixée par le mainteneur, nommé pour l'occasion
`seance.placement.MOTIF_SEANCE_AMPUTEE`. Aucun seuil sur la durée totale ne
séparerait honnêtement une sortie 49 s plus courte que la prescription — un
arrondi — d'une sortie dont le retour au calme perd 60 % de sa durée.

La phrase a deux branches, toutes deux vraies par construction : « X minutes
de moins » **seulement** quand le gagnant tient sa séance *et* est le plus
court du groupe ; « la plus proche de la durée prévue » quand une autre est
plus courte, donc l'ampute. La ligne de détail affiche désormais l'écart
signé : `2:29 (+29 min)`, et `⚠ séance amputée de N min` s'il y a lieu.

**Effet mesuré sur `ourouler sortie --jour 2026-09-12`, le cas le plus
fréquent du mainteneur** : **aucun changement de compte, toujours deux
propositions.** Aucune des cinq candidates n'ampute ce jour-là (la plus courte
tombe pile sur les 2 h prescrites), donc le défaut ne s'y manifestait pas. Ce
qui change est l'affichage : n° 5 est maintenant annoncée `2:29 (+29 min)`.

**b) Une direction de vent non finie passait les deux gardes.**
`interroger` filtrait la vitesse par `math.isfinite` et la direction par le
seul `is None`. Une direction `nan` ressortait de `azimut_pour` (`nan % 360`
vaut `nan`), traversait `boucle.candidates.azimuts` et partait chez BRouter en
`roundTripStartDirection=nan`. Corrigé des deux côtés par un `_fini` unique,
aligné sur `seance.vent._utilisable` : un nombre non fini est une **ignorance**,
jamais une mesure. `azimut_pour` se garde en plus lui-même, parce que
`QuestionVent` est un objet public qu'un appelant peut construire à la main.

**c) Ce qui n'est pas un défaut, malgré un test qui l'affirmait.** Un test
adversarial demandait que `part_connue` soit un axe de contraste, en lisant la
ligne du tableau §3.3.2 qui est **barrée** depuis le 16/09. La règle est en
doctrine : *les routes déjà roulées sont un instrument de mesure, jamais un
critère.* Dans les mots du mainteneur : « c'est pour du test, ça permet de
comparer les critères de BRouter à ma réalité, pas du tout de privilégier mes
choix. » `part_connue` reste affichée et n'entre dans aucune sélection.

**d) Le message dit maintenant ce qui manquait.** Quand la commande rend deux
propositions au lieu de trois, « aucune ne se distinguait » était vrai mais
n'apprenait rien. Elle nomme désormais les axes **muets** — ceux où toutes les
candidates valent la même chose à moins d'un pas près — et ceux qui restaient.
Sur l'EF du 12/09 : « Ce jour-là, l'orientation au vent, les demi-tours, la
pluie et le terrain sous les blocs valaient la même chose sur toutes les
candidates : il ne restait que la durée, la ville et les grands axes pour les
distinguer. » C'est la vraie raison des deux propositions, et elle est
structurelle : une endurance sans bloc, par temps sec et sans vent, éteint
quatre axes sur sept.

## 4. Lot L5.4 — La page du jour

### 4.1 La forme, tranchée le 16/09/2026 (Q18)

Le mainteneur a proposé deux formes : « une carte et 3 itinéraires superposés
qui se mettent en grisé ou en surbrillance, c'est la méthode de Strava et des
GPS » ; ou « 3 cartes en miniature et on clique pour le détail ».

**Retenu : la première.** La raison n'est pas esthétique — **c'est la seule
qui montre où les trois divergent.** Le critère de contraste qu'il a
lui-même proposé est le pourcentage de route commune ; une carte unique le
rend visible littéralement, trois miniatures ne le montrent jamais et
obligent à comparer de mémoire.

Vérifié sur le cas réel du 08/09 : les trois propositions avaient **0 %, 0 %
et 17 % de routes communes**, donc trois directions différentes au départ de
chez lui. Superposées, elles répondent d'un coup d'œil à la question
d'origine du projet — *au sud, au nord ou à l'est ?*

**Ce qui empêche le spaghetti** : seule la proposition sélectionnée montre
ses blocs en couleurs ; les deux autres retombent en trait gris fin. On ne
demande jamais à l'œil de suivre trois choses à la fois.

**Les miniatures ne sont pas perdues, elles deviennent le sélecteur** : trois
cartes sous la grande, chacune avec sa phrase et ses chiffres ; cliquer
allume le tracé correspondant. Les deux formes proposées coexistent donc,
sans onglet — **un onglet cache, et comparer demande de voir ensemble.**

### 4.2 Ce que la page porte

- Les trois tracés superposés, la sélection, les blocs de la proposition
  active, et les flèches de vent déjà livrées au sprint 5.
- La météo par direction, la tenue, le profil d'altitude.
- **Un GPX par proposition**, téléchargeable : si c'est le cycliste qui
  choisit, le fichier suit son choix et non le classement. Type MIME
  `application/gpx+xml` et nom lisible sur un téléphone — Q5 est close, le
  partage système couvre Garmin, Coros et les autres.
- Aucun serveur, aucun compte, aucune base : un fichier HTML autonome.

### 4.3 Deux points à trancher pendant le lot

**a) La page garde-t-elle une recommandation ?** Soit elle présente trois
options à égalité, soit elle en met une en avant et laisse la contredire. Le
superviseur penche pour la seconde — il y aura des jours où le mainteneur ne
veut pas choisir — mais c'est une décision produit, à lui poser.

**b) Le nombre de candidates peut monter.** L5.3 l'a laissé à 5 sur un
diagnostic faux (`HTTP 429` pris pour une limite produit alors que c'était un
artefact de test ; voir la correction de doctrine du 16/09). Plus de
candidates, c'est mécaniquement plus de contraste. À mesurer avant de
changer.

### 4.4 Reste de l'ancien cadrage

Page HTML autonome écrite sur le disque. GPX en téléchargement avec le type
MIME `application/gpx+xml` et un nom de fichier lisible sur un téléphone :
Q5 est close le 15/09/2026, **le partage système du GPX est la voie retenue
pour toutes les marques**, pas un pis-aller. Aucun client Garmin, aucune
bibliothèque non officielle, aucun compte à brancher.

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

## 4. Lot L5.4 — La page du jour

Page HTML autonome écrite sur le disque. GPX en téléchargement avec le type
MIME `application/gpx+xml` et un nom de fichier lisible sur un téléphone :
Q5 est close le 15/09/2026, **le partage système du GPX est la voie retenue
pour toutes les marques**, pas un pis-aller. Aucun client Garmin, aucune
bibliothèque non officielle, aucun compte à brancher.

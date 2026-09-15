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

Conséquence de conception déjà écrite dans `docs/questions_mainteneur.md`
(Q13) : `placer` doit rendre la position de **chaque** étape, pas seulement
des blocs. Extension de `Placement`, pas une nouvelle mesure. Détail à
cadrer à l'ouverture du lot, après L5.1 — les deux touchent `Placement` et
ne se parallélisent pas.

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

### 3.2 Mesurer la préférence avant de la demander

Avant d'ajouter un réglage, on regarde ce que le mainteneur **fait déjà** :
162 sorties avec vent enregistré et traces GPS permettent de dire s'il part
face au vent pour rentrer avec. Précédent du sprint 3 : les poids du terrain
avaient été calibrés contre son intuition, et la mesure l'avait contredit sur
les côtes — il ne les évite pas.

Piège à écarter explicitement dans cette mesure : un effet apparent peut
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

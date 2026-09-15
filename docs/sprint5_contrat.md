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

## 4. Lot L5.4 — La page du jour

Page HTML autonome écrite sur le disque. GPX en téléchargement avec le type
MIME `application/gpx+xml` et un nom de fichier lisible sur un téléphone :
Q5 est close le 15/09/2026, **le partage système du GPX est la voie retenue
pour toutes les marques**, pas un pis-aller. Aucun client Garmin, aucune
bibliothèque non officielle, aucun compte à brancher.

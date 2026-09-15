# Contrat du sprint 4 — Séance ↔ terrain, tenue, carte

Rédigé le 13/09/2026 par le superviseur (Fable au cadrage, Opus à
l'exécution). Fixe les interfaces pour dev-feature, testeur-adversarial (en
aveugle) et relecteur. **Le cadrage produit fait foi et se lit d'abord** :
`docs/plan_sprints_agents.md`, section « Sprint 4 » — séances de référence
réelles, contrainte bloc par bloc, récup amortisseur, mécanique du
demi-tour, Z2 élastiques aux extrémités, note plutôt que filtre, validation
rétrospective, carte de vérification.

## 0. Ce qui existe (sprints 1 à 3)

`Trace`/`Segment`/`PointTrace` (`boucle/trace.py`, `Segment.tags` = WayTags,
`Segment.cout_km` = CostPerKm), `ClientBrouter`, `candidates.generer`,
`couts.evaluer(..., poids=)`, `meteo_trace.evaluer` (échantillons avec
pluie, vent, ressenti à l'heure de passage), `gpx.ecrire_gpx`,
`physique.modele.{Parametres, vitesse_regime, simuler}`,
`physique.commande` (lecture de `calibration.json`), `apprentissage.routes`
(`BaseRoutes.part_connue`), `Cache`, `ClientIntervals`.

Le superviseur ajoute au socle, **tel que livré** (le code fait foi, pas
cette ligne) : `Config.seance` → `ParametresSeance(elasticite_z2_max=0.20,
elasticite_z2_min=-0.05, demi_tour_penalite=1.0, puissance_endurance_pct=0.60,
seuil_recuperation_pct=0.75)` — depuis Q14 (close le 13/09/2026) s'y ajoutent
`elasticite_calme_max=1.5` et `elasticite_calme_min=-0.05`, la fenêtre propre
au retour au calme, qui absorbe et n'est pas un levier — il n'y a **pas** de `ftp_defaut_w`, la FTP
vient de `Config.cycliste.ftp_w` ; `Config.tenue` →
`ParametresTenue(bornes_c=(3.0, 9.0, 15.0, 22.0, 30.0),
bornes_pluie_mmh=(0.2, 0.5, 1.0), vent_veste_kmh=30.0, tenues=())` avec
`tenue_de(categorie)` qui rend les vêtements configurés ou `None`.

## 1. Lot L4.1 — La séance du jour (`seance/`)

`seance/modele.py` :

```python
TYPES = ("echauffement", "bloc", "recuperation", "calme")

@dataclass(frozen=True)
class Etape:
    type: str                  # dans TYPES
    duree_s: float
    puissance_min_w: float | None
    puissance_max_w: float | None
    libelle: str = ""
    elastique: bool = False    # vrai pour l'échauffement et le calme, faux ailleurs
    @property
    def puissance_cible_w(self) -> float | None   # milieu de la fourchette

@dataclass
class Seance:
    nom: str
    jour: date
    etapes: list[Etape]        # aplaties, répétitions développées
    duree_s: float
    meta: dict
    def blocs(self) -> list[tuple[int, Etape]]    # (indice, étape) des étapes de type "bloc"
```

`seance/intervals.py` : `depuis_workout_doc(doc: dict, *, nom, jour, ftp_w,
zones_puissance) -> Seance` et `seance_du_jour(client: ClientIntervals,
jour: date, *, ftp_w, zones_puissance) -> Seance | None`.

Format réel observé le 13/09 sur le compte du mainteneur : `doc["steps"]`
est une liste de **groupes** `{reps, text, duration, steps: [...]}` ; chaque
sous-étape porte `duration` (s) et, au choix, `power: {units, value}` ou
`{units, start, end}`, ou `hr: {units: "hr_zone", value: N}` ; les marqueurs
`warmup: true`, `cooldown: true`, `intensity: "warmup"|"recovery"|"cooldown"`
donnent le type. Règles :
- `reps` développe le groupe autant de fois.
- Type : `warmup`/`intensity=warmup` → "echauffement" ; `cooldown` →
  "calme" ; `intensity=recovery` → "recuperation" ; sinon "bloc".
- Puissance : `units="%ftp"` → part de FTP × `ftp_w`, **les deux écritures
  acceptées** : les séances du mainteneur donnent l'entier (`80` pour 80 %,
  soit 206-219 W pour une FTP de 258 W le 08/02), d'autres sources la
  fraction (`1.05` pour 105 %). Le seuil `SEUIL_FRACTION_FTP = 3.0` tranche
  — au-dessus, un pourcentage ; au-dessous ou égal, une fraction — parce que
  3 % de FTP vaudrait 8 W, ce qui n'existe pas comme consigne, alors que
  3 × FTP est un sprint plausible. L'interprétation retenue est écrite dans
  `meta["convention_pourcent_ftp"]`. `"watts"` → tel quel ;
  `"hr_zone"` → **approximation documentée** par les bornes de
  `zones_puissance` (pourcentages de FTP de la config, ex. Z4 = 105-120 %).
  Une approximation se dit : `meta["puissance_approximee"] = True` et le
  rendu l'affiche.
- `elastique = True` pour la **première** étape si elle est de type
  "echauffement" et la **dernière** si elle est de type "calme". Jamais
  ailleurs : toutes les récupérations sont fixes (décision du 13/09).

`seance/commande.py` : `ourouler seance [--jour AAAA-MM-JJ] [--json]`
affiche la séance, et pour chaque bloc la **longueur de route nécessaire**
estimée par le modèle calibré à la puissance cible, plus la longueur de
route nécessaire au-delà du segment si l'on fait demi-tour (moitié de la
récupération suivante). Sans séance ce jour-là : message clair, code 0.

## 2. Lot L4.2 — Le terrain sous un bloc (`seance/terrain.py`)

Prérequis : `Segment.node_tags: dict[str, str] = field(default_factory=dict)`
alimenté depuis la colonne `NodeTags` des messages BRouter (déjà lue dans
`COLONNES_MESSAGE`, non conservée à ce jour) — format observé :
`highway=traffic_signals`, `highway=crossing`, etc. ; vide si absent.

**Convention d'unité, écrite parce que son absence a produit un bug réel :
toutes les pentes du dépôt sont des tangentes**, jamais des pourcentages —
`0.05` vaut 5 %. C'est la convention de `physique/modele.py`, de
`physique/calibration.py` et de la CLI. `NoteBloc.pente_moyenne` et
`pente_max` la suivent ; le pourcentage n'apparaît que dans les motifs
lisibles. `pente_max` est signée et maximale en valeur absolue : −0,06 pour
une descente à 6 %.

```python
@dataclass
class NoteBloc:
    note: float                 # 0 = parfait, plus haut = moins bon (km équivalents)
    motifs: list[str]           # « deux feux », « descente de 1,2 km », lisibles
    pente_moyenne: float
    pente_max: float
    carrefours: int
    km_batis: float
    descente_m: float
    montee_m: float

def evaluer_couloir(trace, debut_m: float, longueur_m: float) -> NoteBloc
def route_au_dela(trace, position_m: float, besoin_m: float) -> bool
def demi_tour_faisable(trace, position_m: float) -> bool
```

Règles, poids en constantes nommées, **calibrées ensuite sur la validation
rétrospective** :
- **Carrefour** : nœud portant `highway` ∈ {traffic_signals, stop,
  give_way, mini_roundabout, crossing} ou virage de plus de 60° détecté
  géométriquement (réutiliser la mécanique de `couts`, ne pas la
  dupliquer). Poids par carrefour dans le bloc.
- **Zone bâtie** : `highway` ∈ {residential, living_street, service} ou
  tag `maxspeed` ≤ 50 quand il existe. Poids au kilomètre.
- **Descente** : portion de pente < −1,5 % sur plus de 300 m dans le bloc.
  Poids au mètre de dénivelé descendant. C'est le défaut le plus grave sur
  un bloc de seuil : on ne peut pas tenir la puissance.
- **Montée** : tolérée et non pénalisée jusqu'à +2 % ; au-delà, poids
  modéré (la puissance se tient, la vitesse chute).
- **Irrégularité** : écart-type de la pente sur le bloc, poids faible.
- **Les poids ne se devinent pas, ils se mesurent.** Ceux du dépôt sont
  calibrés par la validation rétrospective : le mainteneur évite les zones
  bâties et les descentes, ne fuit pas les montées (il en prend plus que le
  hasard) et ne se soucie pas des carrefours. Un test qui exigerait un
  ordre contraire a tort contre la mesure.
- `route_au_dela` : vrai s'il reste `besoin_m` de tracé après la position,
  ou si le tracé est une boucle fermée (on continue sur la boucle).
- `demi_tour_faisable` : faux si le segment à cette position est dans
  `HIGHWAY_TRAFIC`, vrai sinon. **Il ne juge que le type de route.** La
  troisième condition du mainteneur — un demi-tour ne vaut que sur du plat
  ou du faux-plat, parce qu'à l'envers une côte devient une descente —
  vit dans `placement.py` (constante `PENTE_DEMI_TOUR_MAX`), qui seul
  connaît le couple aller/retour. Les trois conditions sont donc : pente
  du segment, route au-delà, type de route.

**Aucune évaluation sous une récupération** (décision du 13/09) : ni
village, ni carrefour, ni revêtement. La seule question posée à une récup
est mécanique, via `route_au_dela`.

**Validation rétrospective — critère d'acceptation du lot.** Un script
versionné `tests/validation/terrain_retrospectif.py` (exécutable à la main,
hors suite pytest, lit le cache du mainteneur) qui : prend les sorties
réelles à intervalles marqués (au moins « 4x8 SV1 outdoor » du 22/04/2026
et « 2x20' + 4x3' » du 25/04/2026), relit où les blocs sont **réellement**
tombés, note ces emplacements avec `evaluer_couloir`, et les compare à la
note de tronçons tirés au hasard sur la même sortie. Sortie attendue : la
note médiane des emplacements réels doit être **nettement meilleure** que
celle des emplacements au hasard. Si ce n'est pas le cas, les poids sont
faux et il faut le dire.

## 3. Lot L4.3 — Placement et tenue (`seance/placement.py`, `seance/tenue.py`)

```python
@dataclass
class Emplacement:
    etape_idx: int; debut_m: float; longueur_m: float
    demi_tour: bool             # le bloc réutilise le segment précédent en sens inverse
    note: NoteBloc

@dataclass
class Placement:
    decalage_z2_s: float        # allongement (ou raccourcissement) de la Z2 d'ouverture
    emplacements: list[Emplacement]
    note_totale: float
    duree_totale_s: float
    distance_totale_m: float
    avertissements: list[str]

`note_totale` est la moyenne des notes de couloir **pondérée par la durée
de chaque bloc**, décision du superviseur du 13/09 : une activation de 40 s
et un bloc de 20 min sont tous deux des blocs, mais chercher un couloir
propre pour 40 s n'a pas de sens et la validation rétrospective montre que
les blocs courts ne se discriminent pas. On pondère plutôt que d'exclure.

```python
def placer(seance: Seance, trace: Trace, p: Parametres, *,
           elasticite: tuple[float, float] = (-0.05, 0.20),
           pas_s: float = 60.0, penalite_demi_tour: float = 1.0) -> Placement | None
```

Mécanique : la vitesse de chaque étape vient du modèle (`vitesse_regime` à
la puissance cible, pente locale), donc la position de chaque étape le long
du tracé se calcule de proche en proche. On fait varier le **seul** décalage
de la Z2 d'ouverture dans `elasticite` par pas de `pas_s`, on note chaque
configuration, on garde la meilleure. Pour chaque bloc, on essaie aussi la
variante **demi-tour** : le bloc reprend le segment du bloc précédent en
sens inverse si `route_au_dela(fin du bloc précédent, moitié de la récup)`
et `demi_tour_faisable`, avec `penalite_demi_tour` ajoutée à la note. La Z2
de fin absorbe le reste : elle n'est pas un levier de placement, seulement
la fermeture. Si la séance ne tient pas sur la boucle, `placer` rend `None` et range le
motif dans `trace.meta[CLE_MOTIF]` — `None` ne transporte rien, et
`Placement.avertissements` n'existe pas dans ce cas. Même convention que
`boucle.couts`, qui range ses réserves dans `meta`.

`seance/tenue.py` :

```python
@dataclass
class Tenue:
    categorie_temp: str      # « canicule » … « très froid »
    categorie_humidite: str  # « sec » | « humide » | « averses » | « pluie »
    base: list[str]          # ce qu'on met au départ
    a_emporter: list[str]
    a_enlever: list[str]
    motifs: list[str]
def conseiller(meteo: MeteoTrace, p: ParametresTenue) -> Tenue
```
Règle du 13/09 : **la base se décide sur le départ**, parce que c'est là
qu'on a froid ; puis on parcourt les échantillons du tracé — ressenti qui
monte d'une catégorie → « prévoir d'enlever X » ; pluie ≥ seuil → « emporter
la veste » ; ressenti qui baisse → « garder X ». Le vent entre dans le
ressenti et déclenche seul la veste au-delà de `vent_veste_kmh`. Les tenues
par catégorie viennent de la configuration, avec un jeu par défaut
raisonnable et modifiable.

## 4. Lot L4.4 — La commande `sortie` et la carte (superviseur)

`ourouler sortie [--jour] [--distance] [--direction] [--candidates]
[--velo] [--sortie f.gpx] [--carte f.html] [--json]` : séance du jour →
candidates → placement sur chacune → tri par note de placement puis par
météo → GPX + résumé + tenue + **carte HTML** montrant le tracé, les blocs
colorés là où ils tombent, le profil d'altitude, et les motifs de note.

## 5. Ce que le testeur adversarial vise

`workout_doc` : vide, `steps` absent, groupes imbriqués sur trois niveaux,
`reps` à 0 ou négatif, durées nulles, `power` et `hr` tous deux absents,
`units` inconnue, `%ftp` sans FTP disponible. Terrain : bloc plus long que
le tracé, position négative, tracé de deux points, segments sans tags,
`node_tags` vide, bloc à cheval sur la fermeture d'une boucle. Placement :
séance plus longue que la boucle, aucun décalage acceptable, demi-tour
demandé sans route au-delà, élasticité nulle, `pas_s` supérieur à la marge.
Tenue : aucun échantillon, ressenti absent, pluie `None`, toutes catégories
aux bornes exactes. Invariants des sprints 1-3 maintenus.

## 6. Definition of done

- `uv run pytest` et `uv run ruff check .` verts sur `sprint-4`.
- `ourouler seance` affiche la séance du jour réelle du mainteneur.
- Le script de validation rétrospective tourne et **conclut** : note des
  emplacements réels contre note au hasard, chiffres à l'appui.
- `ourouler sortie` produit GPX, résumé, tenue et carte sur la séance du
  jour ou une séance passée choisie avec `--jour`.
- Relecture Opus, puis passe Fable sur `seance/placement.py` et
  `seance/terrain.py` (points critiques).

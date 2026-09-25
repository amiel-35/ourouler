# Contrat du sprint 3 — Antennes, routes connues, modèle physique

Rédigé le 13/09/2026 par le superviseur (Fable). Fixe les interfaces pour
dev-feature, testeur-adversarial (en aveugle) et relecteur. Décisions du
mainteneur intégrées : antennes = seul défaut de tracé à corriger ;
traversées de bourg acceptées ; `fastbike` par défaut ; les traces servent
à **apprendre**, jamais comme critère (couverture sud/ouest de la ville du mainteneur) ;
home-trainer exclu ; précision « pas de folie » ; sorties en groupe =
nom + incohérence puissance/vitesse.

## 0. Ce qui existe déjà

Sprint 2 : `connecteurs/brouter.py` (`ClientBrouter.itineraire/boucle`,
`Trace` avec `segments` portant les tags OSM et, dans `meta`, ce que le
moteur renvoie), `boucle/candidates.py`, `boucle/couts.py` (`Couts`,
`evaluer`), `boucle/meteo_trace.py`, `boucle/gpx.py`, `boucle/commande.py`,
cache SQLite v2 avec 355 sorties vélo réelles du mainteneur (RCR 120, BMC
43, home-trainer 192), `meteo/openmeteo.py` (`ClientOpenMeteo.previsions`).
Config : `Config.boucle`, `Config.brouter`, `Velo(masse_kg, cda_m2,
capteur_puissance…)`, `Cycliste(masse_kg, ftp_w)`.

Le superviseur ajoute au socle : `[calibration]` → `ParametresCalibration(
mots_groupe=("club", "groupe", "peloton", "sortie club"),
part_validation=0.25, vitesse_min_kmh=8.0)` ; `[[evitements]]` →
`Evitement(nom, latitude, longitude, rayon_m)` (liste `Config.evitements`) ;
`Velo.crr` (float | None, roulement) à côté de `cda_m2`.

## 1. Lot L3.1 — Antennes (cul-de-sac) — `boucle/antennes.py` + candidates

```python
@dataclass(frozen=True)
class Antenne:
    debut_idx: int; fin_idx: int; longueur_m: float   # aller + retour, indices dans trace.points
def detecter(trace: Trace, *, fenetre_m: float = 3000, tolerance_m: float = 20) -> list[Antenne]
def elaguer(trace: Trace, antennes: list[Antenne]) -> Trace   # nouveau Trace, distances recalculées, segments réindexés
```
**`fenetre_m` : défaut 3000, décision du mainteneur du 13/09** (le contrat
partait sur 600). Mesuré sur les boucles réelles de 60 km : les culs-de-sac
font 1,5 à 2,7 km et 600 m les laissait tous passer ; un aller-retour assumé
dépasse rarement 3 km sur une telle boucle, et si l'on en rogne un, la
candidate est simplement raccourcie — l'ajustement de rayon compense.
Antenne = portion du tracé où la géométrie est reparcourue en sens inverse
(chaque point du retour à moins de `tolerance_m` d'un point de l'aller,
sur une longueur totale ≤ `fenetre_m`). `elaguer` retire l'aller-retour et
raccorde. `candidates.generer` : (a) passe à BRouter
`profile:correct_misplaced_via_points=1` et
`profile:correct_misplaced_via_points_distance=40` (paramètres d'URL,
vérifiés dans PR #759 — à confirmer sur le serveur réel) [confirmé le
18/09/2026, en partie : le serveur attend le camelCase
`correctMisplacedViaPoints`, pas ce snake_case, et le seuil qui agit
vraiment est 0, pas 40 — voir `connecteurs/brouter.py`] ; (b) après
génération, détecte et élague les antennes, note `meta["antennes"]`
(nombre, mètres retirés). `couts.Couts` gagne `antennes_m` (mètres
d'antennes **avant** élagage, pour information) et la CLI une colonne.
Vérification réelle : la boucle « 60 km NE » du 13/09 (deux communes
voisines) ne doit plus présenter de crochet — comparer avant/après sur les
mêmes azimuts.

## 2. Lot L3.2 — Routes connues : apprentissage — `apprentissage/routes.py` + CLI `routes`

Principe : rejouer les sorties extérieures du cache dans BRouter (points de
passage tous les 1 500 m, ≤ 60 par appel, `itineraire`) pour obtenir les
tronçons OSM réellement parcourus, puis apprendre ce que le cycliste accepte.

```python
@dataclass
class Troncon:          # maille ~30 m : clé = (round(lat*3000), round(lon*3000))
    cle: tuple[int, int]; highway: str; surface: str | None; maxspeed: str | None
    cout_km: float | None      # CostPerKm de BRouter
    passages: int; passages_semaine: int   # lundi-vendredi
class BaseRoutes:       # SQLite dans cache.dossier / "routes_connues.sqlite"
    def __init__(self, chemin: Path): ...
    def ajouter_trace(self, trace: Trace, *, jour: date, id_sortie: str) -> int   # idempotent par id_sortie
    def sorties_apprises(self) -> set[str]
    def statistiques(self) -> Statistiques   # km par highway, par maxspeed, par surface ; part semaine
    def part_connue(self, trace: Trace) -> float   # part des km d'un tracé passant par des mailles connues
def apprendre(cache: Cache, client: ClientBrouter, base: BaseRoutes, config: Config,
              *, depuis: date, max_sorties: int | None = None) -> RapportApprentissage
def poids_appris(stats: Statistiques, exposition: Statistiques) -> dict[str, float]
```
`poids_appris` : pour chaque classe `highway`, comparer sa part dans les
sorties (`stats`) à sa part dans un jeu de candidates générées dans les
mêmes directions (`exposition`, obtenu en générant ~8 boucles de 40 km
autour du départ, toutes directions) : `poids = min(4, max(0, log2(part_expo
/ part_sorties)))` en km-équivalents par km, `tertiary` forcé à 0. Sans
exposition (tests), `poids_appris` sur `stats` seule renvoie les poids par
défaut actuels. **Les poids appris sont écrits dans
`cache.dossier / "poids_routes.json"`** et `couts.evaluer` les charge s'ils
existent (paramètre `poids: dict | None = None`, injecté par la CLI — le
cœur ne lit pas de fichier : c'est `boucle/commande.py` qui lit le JSON et
passe le dict). « Inconnu » n'est jamais un malus : `part_connue` est
affichée à titre informatif (colonne « connu % »), jamais dans le score.
Colonne « coût profil » = moyenne pondérée par la longueur de `CostPerKm`
des segments (déjà dans `Segment.tags` ? sinon l'ajouter à `meta` du
segment côté `connecteurs/brouter.py` : `Segment.cout_km: float | None`).
Évitements : `Config.evitements` → paramètre `nogos=lon,lat,rayon|…` passé
par `ClientBrouter.boucle/itineraire`.
CLI : `ourouler routes apprendre [--depuis] [--max N]` (appelle BRouter :
~160 sorties × 1 appel ≈ 2 min ; idempotent), `ourouler routes stats`
(tableau par classe : km, part, part semaine, poids par défaut → poids
appris), `ourouler routes poids --appliquer` (écrit `poids_routes.json`).
Vérification réelle : sur les 160 sorties extérieures, la table des parts
(attendu ≈ tertiary 65 %, secondary 23 %) et les poids appris, à montrer
au mainteneur.

## 3. Lot L3.3 — Modèle physique et calibration — `physique/`

`physique/modele.py` :
```python
@dataclass(frozen=True)
class Parametres:
    masse_totale_kg: float; cda_m2: float; crr: float
    rendement: float = 0.976; rho: float = 1.226
def puissance_requise(v_ms: float, pente: float, vent_face_ms: float, p: Parametres) -> float
def vitesse_regime(puissance_w: float, pente: float, vent_face_ms: float, p: Parametres) -> float   # Newton/bissection, borne 0-30 m/s
def simuler(trace: Trace, puissance_w: float | Callable[[float], float], p: Parametres,
            vent: Callable[[float, float], float] | None = None) -> Simulation   # vent(dist_m, cap_deg) -> vent de face m/s
```
`Simulation` : `temps_s`, `distance_m`, `vitesse_moy_kmh`, `par_segment:
list[(dist_m, pente, v_kmh, t_s)]`, pas de 100 m, pente lissée (altitude
moyenne glissante ~7 points), vitesse plafonnée en descente (`v_max_kmh =
60`), et **temps aux arrêts non modélisé** (dit dans la doc : la
simulation donne un temps *en mouvement*).

`connecteurs/openmeteo_archive.py` : `ClientArchive(http, base_url=
"https://archive-api.open-meteo.com")`, `horaires(lat, lon, jour) ->
list[HeureArchive(t, vent_kmh, vent_depuis_deg, temp_c, pression_hpa)]`,
un appel par (jour, point arrondi à 0,05°), **mémoïsé dans
`cache.dossier / "archive_meteo.sqlite"`** (l'archive du passé ne change
pas) ; le cache est passé en paramètre (le cœur ne connaît pas le chemin).

`physique/calibration.py` :
```python
@dataclass
class Echantillon:   # segment de ~200 m d'une sortie réelle
    v_ms: float; puissance_w: float; pente: float; vent_face_ms: float; temp_c: float; retenu: bool; motif: str
def echantillonner(activite: Activite, vent: list[HeureArchive]) -> list[Echantillon]
def calibrer(echantillons: list[Echantillon], *, masse_totale_kg: float, cda_init=0.32, crr_init=0.005) -> Ajustement
def valider(sorties_test: list[tuple[Activite, list[HeureArchive]]], p: Parametres) -> Validation
def sorties_calibrables(cache, config, velo) -> list[EntreeCache]  # extérieur, puissance présente, ≥ 20 km, hors mots_groupe
def detecter_groupe(activite, p: Parametres, vent) -> tuple[bool, float]   # vrai si résidu de vitesse > +8 % sur > 50 % de la distance
```
Échantillons retenus : puissance entre 50 W et 2 × FTP, vitesse ≥
`vitesse_min_kmh`, pente entre −3 % et +8 %, accélération faible
(|Δv| < 0,3 m/s entre segments voisins), pas dans les 2 premiers km.
Ajustement : moindres carrés sur `puissance_requise(v) − puissance_mesurée`
pour (CdA, Crr), bornes CdA ∈ [0,18 ; 0,6], Crr ∈ [0,002 ; 0,012] ; masse
totale = `cycliste.masse_kg + velo.masse_kg` (défaut 9 kg si absent) ;
`numpy` autorisé (ajouter la dépendance), pas `scipy` (bissection/grille
maison suffit). Validation : sorties partagées par date (les 25 % les plus
récentes en test), erreur = temps simulé vs temps en mouvement réel, en %
par sortie, MAE et médiane ; rapport texte + JSON. Deux passes : calibrer,
détecter les sorties « groupe » par résidu, recalibrer sans elles.
Résultats écrits dans `cache.dossier / "calibration.json"` (par vélo :
paramètres, date, n sorties, erreurs) par la CLI.

CLI : `ourouler calibrer [--velo RCR] [--depuis AAAA-MM-JJ]` (télécharge les
archives météo nécessaires, calibre, valide, écrit le JSON, affiche le
rapport) ; `ourouler simuler --gpx fichier --puissance 200 [--velo RCR]
[--depart HH:MM]` (vent prévu via `meteo_trace` si départ donné) ;
`boucle` utilise la calibration du vélo (option `--velo`, défaut : premier
vélo route) pour la colonne « temps estimé » si `calibration.json` existe,
avec la mention `(modèle)` sinon `(27 km/h)`.
Vérification réelle : calibration RCR et BMC sur les vraies sorties, avec
le rapport d'erreur — c'est **le** livrable du sprint. Attendu réaliste :
MAE < 6 % sur les sorties de test ; sinon dire pourquoi (vent, arrêts,
groupe).

## 4. Ce que le testeur adversarial vise

Antennes : aller-retour exact, quasi-exact (bruit 10 m), boucle sans
antenne (aucune fausse détection), antenne plus longue que la fenêtre,
antenne au départ, élagage qui préserve la fermeture et les segments.
Routes : maille aux bornes, idempotence par id_sortie, base corrompue,
`poids_appris` avec classes absentes, part 0, log2 de 0/0, plafond 4,
`tertiary` = 0 ; `part_connue` sur tracé vide. Physique : pente 0 et
puissance 0 → vitesse 0 sans division par zéro, vent de dos fort (vitesse
bornée), pente −20 %, `vitesse_regime` monotone en puissance, cohérence
`puissance_requise(vitesse_regime(P)) = P` à 0,1 W, simulation d'un tracé
de 2 points, archive météo vide/partielle/`null`, jour futur refusé,
calibration avec 0/1/2 échantillons, échantillons tous identiques, bornes
atteintes, `detecter_groupe` sur une sortie parfaitement conforme (faux) et
sur une sortie 20 % trop rapide (vrai). Invariants du sprint 1-2
maintenus ; `numpy` interdit hors `physique/`.

## 5. Definition of done

- `uv run pytest` / `uv run ruff check .` verts sur `sprint-3`.
- Antennes : la boucle NE 60 km réelle n'a plus de crochet (comparaison
  avant/après dans le résumé).
- `ourouler routes apprendre` puis `routes stats` sur les vraies sorties ;
  poids appris montrés.
- `ourouler calibrer` sur RCR et BMC : rapport d'erreur réel dans le résumé
  ; `ourouler simuler --gpx` sur une boucle générée.
- Relecture Opus, puis passe Fable sur `physique/` (point critique).

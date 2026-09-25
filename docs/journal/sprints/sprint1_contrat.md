# Contrat du sprint 1 — Données et météo par direction

Rédigé le 12/09/2026 par le superviseur (Fable). Fixe les interfaces pour
que dev-feature, testeur-adversarial (en aveugle) et relecteur travaillent
sur la même cible. Tout écart à ce contrat se signale, ne s'improvise pas.

## 0. Ce qui existe déjà (L1.1, écrit par le superviseur)

- `ourouler.config` : dataclasses `Depart`, `Cycliste`, `Velo`, `Periode`,
  `ParametresMeteo`, `ParametresIntervals`, `ParametresCache`, `Config` ;
  `charger(chemin: Path) -> Config`, `depuis_dict(d: dict) -> Config`,
  `ErreurConfig(ValueError)` dont le message nomme le champ fautif.
  `config.py` est le **seul** module autorisé, avec `cli.py`, à toucher
  `tomllib`, `Path.home()`, `os.environ`, `Path.expanduser`.
- `ourouler.cli` : `main(argv=None) -> int`. Options globales `--config
  CHEMIN` (défaut `~/.config/ourouler/config.toml`) et `--json`. Chaque
  sous-commande est une fonction `ajouter_<nom>(sous_parsers)` dans
  `cli.py` qui importe **paresseusement** son module (pour qu'une
  sous-commande absente ne casse pas les autres) et attache
  `defaults(fonction=...)`. La fonction exécutée reçoit `(args, config)` et
  renvoie un code de sortie entier. Les sous-commandes de ce sprint :
  `inventaire`, `meteo`.
- Convention d'erreur CLI : une `ErreurUtilisateur(Exception)` (dans
  `ourouler.erreurs`) remontée par le cœur est affichée sur stderr en une
  ligne, code de sortie 2. Toute autre exception remonte (code 1, trace).

## 1. Lot L1.2 — Lecteur unique FIT / GPX / TCX

Module `ourouler.activites.modele` :

```python
@dataclass
class Point:
    t: datetime            # toujours conscient du fuseau, en UTC
    lat: float | None
    lon: float | None
    alt_m: float | None
    dist_m: float | None   # distance cumulée depuis le départ
    vitesse_ms: float | None
    puissance_w: float | None
    cadence_rpm: float | None
    fc_bpm: float | None
    temp_c: float | None

@dataclass
class Activite:
    source: str                       # "fit" | "gpx" | "tcx"
    fichier: str | None               # chemin d'origine, informatif
    debut: datetime                   # UTC
    duree_s: float                    # écoulée (dernier point − premier)
    duree_mouvement_s: float | None   # si la source la donne, sinon None
    distance_m: float | None
    denivele_m: float | None          # calculé sur les altitudes si présentes, lissé
    puissance_moy_w: float | None
    puissance_np_w: float | None      # puissance normalisée (30 s glissant, ^4)
    sport: str | None                 # tel que la source le nomme
    appareil: str | None              # tel que la source le nomme
    points: list[Point]
    meta: dict                        # tout champ utile non modélisé, sérialisable JSON
```

Module `ourouler.activites.lecture` : `lire(chemin: Path) -> Activite`
(choix par extension, insensible à la casse), `lire_fit`, `lire_gpx`,
`lire_tcx` (même signature, acceptent aussi des `bytes`). Toute entrée
illisible (fichier vide, tronqué, extension inconnue, XML invalide, FIT sans
enregistrement) lève `ErreurLecture(ErreurUtilisateur)` avec le chemin et
la cause. Un fichier sans GPS ou sans puissance est **valide** : les champs
sont `None`. Les horodatages non monotones sont tolérés et signalés dans
`meta["avertissements"]`.

Fixtures : `tests/fixtures/activites/` — fichiers **générés** par un script
versionné (`tests/fixtures/generer_activites.py`), trajectoire synthétique
autour d'un point fictif en mer (0.0, 0.0) ou en un lieu manifestement
inventé ; jamais une trace réelle.

## 2. Lot L1.3 — Cache local et inventaire

Module `ourouler.activites.cache` :

```python
class Cache:
    def __init__(self, dossier: Path): ...   # crée dossier/ et dossier/index.sqlite
    def ajouter(self, contenu: bytes, *, source: str, id_externe: str | None,
                extension: str, meta: dict) -> str   # renvoie l'identifiant interne (sha256 du contenu)
    def contient(self, *, source: str, id_externe: str) -> bool
    def lister(self, depuis: date | None = None, jusqua: date | None = None) -> list[EntreeCache]
    def chemin(self, identifiant: str) -> Path
    def indexer_dossier(self, dossier: Path) -> int   # importe tous les .fit/.gpx/.tcx, renvoie le nombre ajoutés
```

`EntreeCache` : `identifiant`, `source` ("intervals" | "fichier" | …),
`id_externe`, `debut` (UTC), `duree_s`, `distance_m`, `puissance_moy_w`,
`sport`, `appareil`, `equipement` (nom du vélo côté source, s'il existe),
`chemin`, `meta` (JSON). L'index est un SQLite (stdlib) ; le fichier brut
est stocké tel quel sous `dossier/brut/<identifiant>.<extension>`. Ajouter
deux fois le même contenu est idempotent.

Module `ourouler.activites.inventaire` :

```python
def rattacher_velo(entree: EntreeCache, config: Config) -> str
def inventaire(cache: Cache, config: Config, depuis: date) -> Inventaire
def rendre_texte(inv: Inventaire) -> str
def rendre_json(inv: Inventaire) -> dict
```

Règle de rattachement, dans cet ordre : (1) `entree.equipement` égal
(insensible à la casse) à `velo.intervals_gear` d'un vélo ; (2) une
`Periode` d'un vélo contient `entree.debut` ; (3) sport intérieur
(`VirtualRide`, appareil Zwift/Rouvy, ou `meta["interieur"]`) →
`"home-trainer"` ; (4) sinon le premier vélo d'usage `route`. `Inventaire`
porte : par vélo (nombre, km, heures, plage de dates, % avec puissance) et
par mois (sorties extérieures, km, dont avec puissance), plus la liste des
anomalies (durée < 10 min, distance nulle, sans puissance).

CLI : `ourouler inventaire [--depuis AAAA-MM-JJ] [--importer DOSSIER]
[--synchroniser]`. `--importer` indexe un dossier de fichiers ;
`--synchroniser` appelle le connecteur Intervals (L1.4). Sans option, lit
le cache et affiche l'inventaire depuis `config.historique_depuis`.

## 3. Lot L1.4 — Connecteur Intervals.icu

Module `ourouler.connecteurs.intervals` :

```python
class ClientIntervals:
    def __init__(self, athlete_id: str, api_key: str, http: httpx.Client | None = None,
                 base_url: str = "https://intervals.icu"): ...
    def activites(self, depuis: date, jusqua: date | None = None) -> list[dict]
    def telecharger_fichier(self, activite_id: str) -> tuple[bytes, str]   # (contenu, extension)
    def evenements(self, jour: date) -> list[dict]                        # séances planifiées du jour

def synchroniser(client: ClientIntervals, cache: Cache, depuis: date) -> RapportSynchro
```

Auth basique `API_KEY:<clé>`. Endpoints : `GET /api/v1/athlete/{id}/activities?oldest=&newest=`,
`GET /api/v1/activity/{id}/file`, `GET /api/v1/athlete/{id}/events?oldest=&newest=`.
Pagination : si l'API tronque, découper par mois. Erreurs HTTP → `ErreurConnecteur(ErreurUtilisateur)` nommant le code et l'endpoint, **sans jamais
imprimer la clé**. `synchroniser` n'appelle `telecharger_fichier` que pour
les activités absentes du cache et renvoie un rapport (vues, ajoutées,
ignorées, échecs). Les métadonnées Intervals (nom, type, `gear`, appareil,
puissance) sont copiées dans `meta` de l'entrée de cache ; `equipement` =
`gear.name` si présent.

Fixtures : réponses JSON **fabriquées** (identifiants et valeurs
inventés), jamais une copie d'une réponse réelle du mainteneur.

## 4. Lot L1.5 — Météo par direction

Module `ourouler.meteo.couronne` :

```python
NOMS_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")   # pour 8 ; 16 si demandé
@dataclass(frozen=True)
class PointCouronne: nom: str; azimut_deg: float; distance_km: float; lat: float; lon: float
def couronne(depart: Depart, directions: int, distances_km: Sequence[float]) -> list[PointCouronne]
```
Calcul de destination sur la sphère (rayon 6 371 km). Le point de départ
lui-même est inclus (nom `"ici"`, distance 0).

Module `ourouler.meteo.openmeteo` :

```python
class ClientOpenMeteo:
    def __init__(self, http: httpx.Client | None = None, base_url: str = "https://api.open-meteo.com"): ...
    def previsions(self, points: Sequence[tuple[float, float]], *, modele: str,
                   debut: datetime, horizon_h: int) -> list[PrevisionPoint]
```
Un seul appel pour tous les points (`latitude=a,b,c&longitude=…`), variables
horaires `precipitation,rain,wind_speed_10m,wind_direction_10m,wind_gusts_10m,
apparent_temperature,temperature_2m`, `models=<modele>`, `timezone=UTC`,
fenêtre `start_hour`/`end_hour`. `PrevisionPoint` : `lat`, `lon`, `heures:
list[PrevisionHeure]` avec `t` (UTC), `pluie_mm`, `vent_kmh`, `rafales_kmh`,
`vent_depuis_deg`, `ressenti_c`, `temp_c` (chacun `float | None`). Erreur
HTTP ou JSON inattendu → `ErreurConnecteur`.

Module `ourouler.meteo.rapport` :

```python
@dataclass
class Cellule:
    direction: str; distance_km: float; t: datetime
    pluie_mm: float | None; pluie_second_avis_mm: float | None
    vent_kmh: float | None; vent_depuis_deg: float | None
    vent_relatif: str | None      # "face" | "dos" | "travers" pour qui S'ÉLOIGNE du départ dans cette direction
    ressenti_c: float | None
    confiance: str                # "accord" | "desaccord" | "inconnu"

@dataclass
class RapportMeteo:
    depart: Depart; debut: datetime; horizon_h: int; modele: str; second_avis: str
    cellules: list[Cellule]
    def meilleure_direction(self) -> tuple[str, str]   # (nom, motif en une phrase)

def construire(depart, couronne, prevision_principale, prevision_second_avis, debut, horizon_h) -> RapportMeteo
def rendre_texte(rapport: RapportMeteo, distance_km: float | None = None) -> str
def rendre_json(rapport: RapportMeteo) -> dict
```

Règles : `vent_relatif` = "face" si le vent vient de ±45° de l'azimut de la
direction, "dos" si de ±45° de l'opposé, sinon "travers". `confiance` =
"desaccord" si un modèle donne ≥ 0,3 mm/h et l'autre < 0,1 mm/h ; "accord"
sinon ; "inconnu" si un des deux manque. `meilleure_direction` : cumul de
pluie minimal sur l'horizon toutes distances confondues ; à égalité (< 0,2 mm
d'écart), préférer le vent de **face à l'aller**. Le rendu texte : une table
par distance (lignes = directions, colonnes = heures locales du fuseau du
système), cellule `pluie vent(relatif) ressenti` et un marqueur `?` en cas de
désaccord ; puis une ligne « Direction conseillée ». Les heures sont
affichées en heure locale, calculées en UTC.

CLI : `ourouler meteo [--depart HH:MM | AAAA-MM-JJTHH:MM] [--horizon H]
[--distance KM] [--modele M] [--second-avis M] [--json]`. Sans `--depart`,
l'heure courante arrondie à l'heure. `--distance` restreint l'affichage à
une couronne. Ce lot **tourne pour de vrai** sur le point de départ de la
configuration (Open-Meteo est gratuit et sans clé).

## 5. Ce que le testeur adversarial vise

Fichiers d'activité tronqués, vides, sans GPS, sans puissance, à
horodatages non monotones, extension en majuscules ; réponses Intervals et
Open-Meteo vides, partielles, en 401/429/500, avec des `null` ou des types
inattendus, des tableaux de longueurs différentes ; passage à l'heure d'été
dans la fenêtre ; cache absent, dossier non inscriptible, index corrompu ;
et les invariants : aucun test ne touche le réseau (`httpx` reçoit toujours
un `MockTransport`), aucun module hors `cli.py`/`config.py` n'importe
`tomllib` ni ne lit `os.environ`/`Path.home()`, aucune fixture ne contient
de coordonnée à moins de 50 km d'une ville française réelle.

## 6. Definition of done du sprint

- `uv run pytest` et `uv run ruff check .` verts sur la branche `sprint-1`.
- `uv run ourouler meteo` tourne pour de vrai sur le point de départ de la
  configuration du mainteneur et affiche la table.
- `uv run ourouler inventaire --importer <dossier>` tourne sur des fichiers
  réels si le mainteneur en fournit ; `--synchroniser` tourne si la clé
  Intervals est fournie (Q1). Sinon : **non vérifié**, dit en clair.
- Verdict écrit du relecteur par lot dans `docs/journal/sprints/sprint1_relecture.md`.

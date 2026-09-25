# Contrat du sprint 2 — Tracé : boucles BRouter, coûts, pluie le long du tracé, rattachement par capteur

Rédigé le 12/09/2026 (nuit) par le superviseur (Fable). Fixe les interfaces
pour dev-feature, testeur-adversarial (en aveugle) et relecteur. Tout écart
se signale, ne s'improvise pas. Décisions du mainteneur prises en compte :
Q4 (BRouter sur Coolify, pas sur le Mac), Q5 (le GPX suffit), Q2 (vélos
distingués par le capteur de puissance).

## 0. Ce qui existe déjà (écrit par le superviseur)

- `ourouler.config` : section `[brouter]` → `ParametresBrouter(url, utilisateur,
  mot_de_passe, profil="fastbike", timeout_s=120)` (`Config.brouter`,
  `renseigne` vrai si url non vide ; `repr` masque le mot de passe) ;
  `[boucle]` → `ParametresBoucle(vitesse_moyenne_kmh=27.0, sens="horaire",
  candidates=5, tolerance_distance=0.10)` (`Config.boucle`) ; `Velo` gagne
  `capteur_puissance: str = ""` (valeur exacte du champ Intervals
  `power_meter`, ex. « SRAM 1052 ») et `intervals_gear_id: str = ""`.
- `ourouler.boucle.trace` : le modèle partagé.

```python
@dataclass(frozen=True)
class PointTrace:
    lat: float; lon: float; alt_m: float | None; dist_m: float   # distance cumulée
@dataclass
class Segment:            # un tronçon homogène tel que BRouter le décrit (messages)
    debut_idx: int; fin_idx: int          # indices dans points (inclusifs)
    longueur_m: float
    tags: dict[str, str]                  # ex. {"highway": "tertiary", "surface": "asphalt"}
@dataclass
class Trace:
    nom: str
    points: list[PointTrace]
    segments: list[Segment]               # vide pour un GPX importé
    distance_m: float
    denivele_m: float | None
    temps_moteur_s: float | None          # estimation du moteur, informative
    meta: dict                            # sérialisable JSON
    def bornee(self) -> bool              # premier et dernier point à < 300 m l'un de l'autre
```
`trace.py` contient aussi `cap_deg(a: PointTrace, b: PointTrace) -> float`
(azimut initial), `distance_m(a, b)` (haversine) et `sens_boucle(trace) ->
str` ("horaire" | "antihoraire" | "indetermine", par le signe de l'aire
signée en coordonnées projetées localement ; "indetermine" si non bornée ou
aire quasi nulle).

## 1. Lot L2.1 — Connecteur BRouter

Module `ourouler.connecteurs.brouter` :

```python
class ClientBrouter:
    def __init__(self, params: ParametresBrouter, http: httpx.Client | None = None): ...
    def itineraire(self, points: Sequence[tuple[float, float]], *, profil: str | None = None) -> Trace
    def boucle(self, depart: tuple[float, float], *, azimut_deg: float, rayon_m: float,
               nb_points: int = 5, ecart_deg: int | None = None, profil: str | None = None) -> Trace
```
Points en (lat, lon) côté Python, convertis en `lon,lat` pour BRouter. Auth
basique (utilisateur, mot de passe) ; jamais le mot de passe dans une
erreur, un log, un `repr`. Requêtes vérifiées ce soir sur le serveur réel :
- A→B : `GET {url}/brouter?lonlats=lon,lat|lon,lat&profile=P&alternativeidx=0&format=geojson`
- boucle : `GET {url}/brouter?engineMode=4&lonlats=lon,lat&roundTripStartDirection=A&roundTripDistance=R&roundTripPoints=N&profile=P&alternativeidx=0&format=geojson`
  (`engineMode` est un **entier**, 4 = boucle ; `roundTripDirectionAdd` optionnel).
  Mesuré : rayon 8 000 m → boucle 40,6 km ; 22 000 m → 103 km (ratio ≈ 5, à
  ne pas coder en dur : voir L2.3).
- Profils présents sur le serveur : `fastbike`, `fastbike-verylowtraffic`,
  `trekking`, `gravel`… (**pas** `fastbike-lowtraffic`). Un profil absent
  donne HTTP 500 sans corps → `ErreurConnecteur` « profil inconnu ? ».
- Lecture du GeoJSON : `features[0].geometry.coordinates` = `[lon, lat, alt]` ;
  `properties["track-length"]` (m), `["total-time"]` (s), `["filtered ascend"]`
  (m) ; `properties["messages"]` = tableau dont la première ligne est
  l'en-tête (`Longitude, Latitude, Elevation, Distance, CostPerKm, ElevCost,
  TurnCost, NodeCost, InitialCost, WayTags, NodeTags, Time, Energy`) et
  chaque ligne suivante décrit le tronçon se terminant au point
  (Longitude, Latitude) ; `WayTags` = `"highway=tertiary surface=asphalt …"`.
  Construire les `Segment` en rattachant chaque message au point de la
  géométrie le plus proche (ordre croissant). Longitudes/latitudes des
  messages en **microdegrés entiers** (à vérifier sur la réponse : sinon en
  degrés) — écrire le test avec une réponse enregistrée **fabriquée**.
- HTTP 4xx/5xx, corps vide, JSON inattendu, `features` vide → `ErreurConnecteur`.

## 2. Lot L2.2 — GPX : écriture et import

Module `ourouler.boucle.gpx` : `ecrire_gpx(trace: Trace, nom: str) -> str`
(GPX 1.1 avec `<trk>`, altitudes si présentes, `<name>`, `<desc>` reprenant
distance, D+, temps estimé) et `lire_gpx_trace(chemin_ou_bytes) -> Trace`
(première `<trk>` ou `<rte>` ; sans horodatage nécessaire ; `segments`
vide ; fichier vide/invalide → `ErreurLecture`). Aller-retour testé.

## 3. Lot L2.3 — Candidates de boucle

Module `ourouler.boucle.candidates` :

```python
@dataclass
class Candidate:
    trace: Trace; azimut_deg: float; rayon_m: float; ecart_relatif: float   # (distance − cible)/cible
def generer(client: ClientBrouter, depart: Depart, *, distance_km: float, azimut_deg: float,
            nb: int, tolerance: float, profil: str | None = None,
            appels_max: int = 12) -> list[Candidate]
```
Stratégie : azimuts = `azimut_deg` puis ± 20°, ± 40°… jusqu'à `nb` ; pour
chaque azimut, rayon initial = `distance_km * 1000 / 5`, puis **ajustement
par proportion** (rayon × cible/obtenu) au plus 2 fois tant que
`|ecart_relatif| > tolerance` ; ne garder que les boucles bornées
(`trace.bornee()`). Total d'appels plafonné par `appels_max` ; si aucune
candidate dans la tolérance, renvoyer les meilleures quand même, triées par
`|ecart_relatif|`. Le client est injectable : tests sur `MockTransport`
avec des réponses fabriquées.

## 4. Lot L2.4 — Coûts d'un tracé

Module `ourouler.boucle.couts` :

```python
@dataclass
class Couts:
    km_trafic: float          # km sur highway ∈ {primary, primary_link, secondary, secondary_link, trunk}
    km_calme: float           # tertiary, unclassified, residential, cycleway, track, service, living_street
    km_non_revetu: float      # surface ∈ {gravel, unpaved, dirt, ground, grass, compacted, fine_gravel, sand} ou track sans surface
    virages_gauche: int       # changements de cap ≤ −45° (à gauche) en ≤ 60 m
    virages_gauche_trafic: int   # dont sur un tronçon entrant ou sortant à trafic
    virages_droite: int
    sens: str                 # "horaire" | "antihoraire" | "indetermine"
    score: float              # plus bas = mieux
def evaluer(trace: Trace, *, sens_prefere: str = "horaire") -> Couts
```
Score = `km_trafic × 3 + km_non_revetu × 4 + virages_gauche × 0.3 +
virages_gauche_trafic × 1.0 + (0 si sens == sens_prefere sinon 2)`, en km
équivalents. Poids dans des constantes nommées en tête de module. Sans
`segments` (GPX importé), `km_trafic`/`km_calme`/`km_non_revetu` = 0 et
`meta["couts_partiels"] = True`. Détection des virages : cap calculé sur
des points espacés d'au moins 15 m pour éviter le bruit GPS.

## 5. Lot L2.5 — Pluie et vent le long du tracé, à l'heure de passage

Module `ourouler.boucle.meteo_trace` :

```python
@dataclass
class Echantillon:
    dist_m: float; t: datetime; lat: float; lon: float; cap_deg: float
    pluie_mm: float | None; vent_kmh: float | None; vent_relatif: str | None; ressenti_c: float | None
@dataclass
class MeteoTrace:
    echantillons: list[Echantillon]; pluie_cumulee_mm: float; minutes_pluie: float
    part_vent_face: float; part_vent_dos: float; ressenti_min_c: float | None; confiance: str
def evaluer(trace: Trace, client: ClientOpenMeteo, *, depart: datetime, vitesse_kmh: float,
            modele: str, second_avis: str | None = None, pas_m: float = 5000) -> MeteoTrace
```
Échantillons tous les `pas_m` (et au dernier point) ; heure de passage =
`depart + dist / vitesse` ; un **seul** appel Open-Meteo pour tous les
échantillons (fenêtre = du départ à l'arrivée + 1 h) ; valeur horaire
interpolée linéairement entre les deux heures encadrantes ; `vent_relatif`
relatif au **cap local** du tracé (réutiliser la règle ±45° de
`meteo.rapport`, ne pas la dupliquer : extraire une fonction commune si
besoin). `minutes_pluie` = minutes sur des échantillons à ≥ 0,2 mm/h.
`confiance` comme au sprint 1 si second avis fourni.

## 6. Lot L2.6 — CLI `ourouler boucle`

`ourouler boucle --distance 60 --direction NE [--depart HH:MM] [--candidates 5]
[--profil P] [--sortie fichier.gpx] [--gpx entree.gpx] [--json]`.
Sans `--gpx` : génère les candidates (L2.3), évalue coûts (L2.4) et météo
(L2.5), affiche un tableau trié par `score + pluie_cumulee_mm × 2` :
`n° | distance | D+ | temps estimé (à vitesse_moyenne_kmh) | trafic km | non revêtu km | virages G (dont trafic) | sens | pluie mm | vent face % | ressenti min`,
puis écrit la meilleure dans `--sortie` (défaut :
`boucle_<direction>_<distance>km_<AAAAMMJJ-HHMM>.gpx` dans le dossier
courant). Avec `--gpx` : évalue le fichier importé seul (coûts partiels +
météo) et l'affiche. `--direction` accepte N/NE/…/NO ou un azimut en degrés.
Commande dans `ourouler/boucle/commande.py`, `executer(args, config,
client_brouter=None, client_meteo=None) -> int`, enregistrée dans `cli.py`
(`ajouter_boucle`, import paresseux). **Tourne pour de vrai** sur le
serveur BRouter et Open-Meteo depuis la config de la machine.

## 7. Lot L2.7 — Rattachement par capteur, et métadonnées Intervals

Constaté sur les vraies données ce soir (API Intervals, champ `power_meter`) :
« SRAM 1052 » sur les sorties RCR (route, capteur unilatéral, `avg_lr_balance`
absent), « QUARQ 34055 » sur les sorties BMC (CLM, bilatéral,
`avg_lr_balance` présent) à partir de février 2025 ; `gear` dans la liste
d'activités ne porte qu'un `id` (`b13575434` = rcr, `b15055454` = BMC,
`b9447353` = VR home-trainer, `b5927777` = specialized sirrus), le nom vient
de `GET /api/v1/athlete/{id}/gear`. La parité des puissances **ne discrimine
pas** (41-48 % de valeurs paires partout) : ne pas l'implémenter.

- `connecteurs/intervals.py` : copier dans `meta` : `power_meter`,
  `power_meter_serial`, `bilateral` (= `avg_lr_balance is not None`),
  `gear_id`, `trainer`, `device_name` ; `equipement` = nom résolu via
  l'endpoint gear (un appel, mis en cache dans le client). `synchroniser`
  gagne `rafraichir_meta=True` : met à jour `meta`/`equipement` des entrées
  déjà présentes **sans** retélécharger le fichier.
- `activites/inventaire.rattacher_velo`, nouvel ordre (décision Q7 du
  superviseur, à confirmer par le mainteneur) : (1) intérieur
  (`VirtualRide`, `trainer`, appareil Zwift/Rouvy) → "home-trainer" ;
  (2) `meta["power_meter"]` égal à `velo.capteur_puissance` ; (3)
  `meta["gear_id"]` égal à `velo.intervals_gear_id` ou `equipement` égal à
  `velo.intervals_gear` ; (4) période ; (5) premier vélo route. Tests des
  cinq règles et de leur ordre.
- CLI : `ourouler inventaire --synchroniser` puis `ourouler inventaire`
  **sur les vraies données** doit montrer RCR et BMC séparés, avec le
  nombre de sorties, km, et % avec puissance. Le mainteneur renseigne
  `capteur_puissance`/`intervals_gear_id` dans sa config locale (le
  superviseur le fait ce soir).

## 8. Ce que le testeur adversarial vise

BRouter : 500 sans corps, GeoJSON sans `features`, `messages` absent ou
sans en-tête, coordonnées en microdegrés vs degrés, boucle non bornée,
distance 0, profil inconnu, timeout, mot de passe absent de toute erreur.
Candidates : moteur qui renvoie toujours la même boucle, boucle trop courte
malgré l'ajustement, plafond d'appels respecté. Coûts : trace de 2 points,
segments vides, tags sans `highway`, virages à 180°, cap au passage du
méridien 0 (Rennes est à −1,68°, mais tester à 0). Météo le long : trace
plus longue que l'horizon, échantillon unique, `null`, second avis absent.
GPX : vide, `<rte>` seulement, sans altitude, aller-retour. Invariants du
sprint 1 maintenus (pas de réseau, pas de config dans le cœur, pas de
coordonnée réelle en fixture, mot de passe jamais imprimé).

## 9. Definition of done du sprint

- `uv run pytest` et `uv run ruff check .` verts sur `sprint-2`.
- `uv run ourouler boucle --distance 60 --direction NE` tourne pour de vrai
  (BRouter Coolify + Open-Meteo) et écrit un GPX ; `--gpx` évalue un GPX.
- `uv run ourouler inventaire --synchroniser` puis `inventaire` séparent
  RCR et BMC sur les vraies données.
- Verdict du relecteur dans `docs/journal/sprints/sprint2_relecture.md`.

# Relecture du sprint 1 — lots L1.1 à L1.5

Relu le 12/09/2026 par l'agent `relecteur` (Opus) sur la branche `sprint-1`,
après fusion de `s1-meteo` et `s1-donnees`. Lecture de `CLAUDE.md`,
`doctrine_architecture.md`, `docs/sprint1_contrat.md`, de tout
`src/ourouler/` et de tout `tests/`. Aucun fichier sous `src/` ou `tests/`
n'a été modifié : ce document est le seul livrable de la relecture.

## 0. État mesuré

```
uv run ruff check .   → All checks passed!
uv run pytest -q      → 325 passed in 1.27s
```

Conforme à l'attendu. Les mesures faites en plus de la lecture (toutes
reproductibles, scripts jetables hors dépôt) :

| Mesure | Résultat |
|---|---|
| `ourouler meteo` sur un point français réel (45.0, 5.0) | **fonctionne**, table complète, AROME HD + `icon_seamless` |
| `ourouler meteo` sur le point fictif (0.0, 0.0) de `tests/fixtures/config_test.toml` | **échoue** avec un message inutilisable (§5, D1) |
| `heure_depart("2026-12-20T10:00")` demandé en septembre | horodatage à **+02:00** au lieu de +01:00 (§5, D2) |
| NP d'un même profil de puissance, échantillonné régulièrement puis irrégulièrement | **293,2 W contre 253,6 W** (§2, B1) |
| `indexer_dossier` sur un dossier contenant un fichier illisible (mode 000) | **`PermissionError` non rattrapée**, trace, code 1 (§3, C1) |
| `repr(Config)` avec une clé renseignée | **la clé apparaît en clair** (§1, A2 et §6) |
| `historique_depuis = 2023-12-01T00:00:00` (datetime TOML) | `TypeError` à la comparaison de périodes (§1, A5) |

## 1. Lot L1.1 — configuration et CLI

### Verdict : **bloquant**

Un seul point bloque, et il est à une ligne de la correction : le dépôt
contient des données personnelles réelles du mainteneur, alors que la règle
absolue 1 de `CLAUDE.md` l'interdit sans réserve et que le dépôt est destiné
à devenir public (Q6).

**A1 — données personnelles réelles dans `config.example.toml` (bloquant).**
`config.example.toml:11-12` donne `masse_kg = 91.0` et `ftp_w = 258`, qui
sont exactement les valeurs réelles du mainteneur telles qu'écrites dans
`docs/cadrage.md:12` (« FTP 258 W, 91 kg »). `config.example.toml:7-8` place
le départ à (48.11, -1.68), soit le centre de Rennes, la ville où habite le
mainteneur (`docs/cadrage.md:15`), et le commentaire la nomme.
`config.example.toml:29` propose `# ex. i183365`, un identifiant d'athlète
d'apparence réelle. Le fichier affirme lui-même en `config.example.toml:2-3`
« ne contient aucune donnée personnelle », et `README.md:48` affirme « rien
de personnel n'entre dans ce dépôt » : la contradiction est dans le dépôt.
*Correction : remplacer par des valeurs manifestement inventées (75 kg,
FTP 200, point rond hors de toute ville, `i000000` comme dans
`tests/test_intervals.py:28`) et retirer la mention de Rennes.*

**A2 — la clé d'API Intervals apparaît dans `repr(Config)` (à corriger).**
`config.py:66-73` : `ParametresIntervals` est une dataclass sans protection,
donc `repr(config)` et `repr(config.intervals)` impriment `api_key` en clair
— mesuré. Le masquage n'existe que dans la sortie JSON (`cli.py:58`), et le
test qui garde cet invariant ne couvre que le client
(`tests/test_intervals.py:104`, `assert CLE not in repr(c)`), pas la
configuration. N'importe quelle trace pytest (`-l`), n'importe quel futur
log de contexte suffit à la publier. *Correction : `api_key: str = field(default="", repr=False)`, ou un `__repr__` qui rend `api_key='***'`, et étendre
le test d'invariant à `repr(Config)`.*

**A3 — `--json` est refusé après la sous-commande (à corriger).** Le contrat
§4 écrit `ourouler meteo [...] [--json]`, mais `--json` n'est déclaré qu'en
option globale (`cli.py:33`) : `ourouler meteo --json` répond
`unrecognized arguments: --json` — mesuré. L'invocation naturelle est donc
cassée, et la seule forme qui marche (`ourouler --json meteo`) n'est écrite
nulle part. *Correction : ajouter `--json` à chaque sous-parseur (ou un parent
parser partagé) en gardant l'option globale.*

**A4 — validations absentes en `config.py` (à corriger, léger).**
`config.py:141-145` accepte sans broncher `directions = 7`, `horizon_h = -5`
et `distances_km = [-3, 0]` — mesuré. Les deux premiers sont rattrapés plus
loin avec un message correct (`couronne.py:67`, `meteo/commande.py:32`), mais
les distances négatives ou nulles sont silencieusement ignorées
(`couronne.py:112`) : l'utilisateur obtient une table sans couronne et sans
explication. Le contrat exige que `ErreurConfig` nomme le champ fautif ;
c'est le rôle de `config.py`. *Correction : valider `directions ∈ {8, 16}`,
`horizon_h ≥ 1` et `distances_km > 0` dans `depuis_dict`.*

**A5 — `historique_depuis` accepte un datetime et casse plus loin (à corriger,
léger).** `config.py:175-181` : `isinstance(x, date)` est vrai pour un
`datetime`, donc `historique_depuis = 2023-12-01T00:00:00` (forme TOML
parfaitement légale) produit un `datetime`, et la première comparaison de
période lève `TypeError: '<=' not supported between date and datetime`
(`config.py:44`) — mesuré : trace et code 1 pour une faute de frappe de
configuration. *Correction : `if isinstance(x, datetime): return x.date()`
avant le test `isinstance(x, date)`.*

**A6 — écarts au contrat, acceptables mais à déclarer.** La sous-commande
`config` (`cli.py:44-71`) n'est pas au contrat (« les sous-commandes de ce
sprint : `inventaire`, `meteo` ») ; elle est utile, sans risque, et masque la
clé. `historique_depuis` et `periodes` sont gérés par `config.py` mais
absents de `config.example.toml`, alors que la règle absolue 6 en fait des
paramètres de configuration : à documenter dans l'exemple.

## 2. Lot L1.2 — lecteur unique FIT / GPX / TCX

### Verdict : **à corriger**

Le lot est solide : signatures conformes, `Point`/`Activite` conformes au
contrat, entrées vides / tronquées / d'extension inconnue correctement
converties en `ErreurLecture`, extension en majuscules gérée (`lecture.py:44`,
fixture `COURTE.GPX`), fichiers sans GPS et sans puissance acceptés,
horodatages non monotones tolérés, signalés **et** réordonnés avant tout
calcul (`lecture.py:354-359`) — ce dernier point est mieux que le contrat ne
demandait. Trois défauts de correction.

**B1 — la puissance normalisée est faussée par un échantillonnage irrégulier,
et le docstring l'affirme corrigée (à corriger).** `modele.py:71-93` : la
fenêtre glissante est bien temporelle (`modele.py:88`), mais la moyenne
extérieure des puissances⁴ est faite **par échantillon** et non pondérée par
la durée (`modele.py:93`). Un même profil physique donne donc 293,2 W en
échantillonnage irrégulier (900 s denses à 1 Hz puis 900 s à 0,1 Hz) contre
253,6 W à 1 Hz constant — mesuré, 15 % d'écart. Or `modele.py:75-76` affirme
« une trace à 1 Hz, à 2 s ou irrégulière donne le même sens » : c'est vrai
pour les pas réguliers (240,2 / 239,8 / 238,6 / 237,0 W à 1, 2, 5 et 10 s),
faux pour l'irrégulier. Une affirmation non mesurée, contraire à la règle
absolue 5, sur la grandeur qui servira à calibrer le modèle physique.
*Correction : pondérer `moyenne**4` par l'intervalle de temps de chaque
échantillon (ou rééchantillonner à 1 s avant le calcul), puis remplacer le
docstring par la mesure.*

**B2 — FIT multi-sessions : la distance est celle de la dernière session
(à corriger, léger).** `lecture.py:87-90` : `duree_mouvement_s` et
`distance_m` sont réaffectés à chaque trame `session`, alors que `sport` est
protégé par `sport or ...`. Un fichier multisport (ou une sortie coupée en
deux sessions) rapporte donc la distance du dernier tronçon seulement, en
silence. *Correction : cumuler `total_distance` et `total_timer_time` sur
toutes les sessions, ou n'accepter la valeur qu'en l'absence de précédente et
poser un avertissement dans `meta` quand il y a plusieurs sessions.*

**B3 — un horodatage naïf est supposé UTC sans le dire (à corriger, léger).**
`lecture.py:417-418` : une source naïve est réputée UTC. C'est le bon choix
par défaut (le FIT l'est par spécification), mais un GPX ou un TCX exporté en
heure locale se décale silencieusement de 1 ou 2 h, ce qui déplacera des
sorties d'un mois à l'autre dans l'inventaire. *Correction : ajouter un
avertissement dans `meta["avertissements"]` quand au moins un horodatage
était naïf.*

## 3. Lot L1.3 — cache local et inventaire

### Verdict : **à corriger**

L'idempotence du cache est réelle et bien testée (sha256 du contenu, fichier
brut écrit une seule fois, `ON CONFLICT DO UPDATE`, `tests/test_cache.py:95-101`) ;
le dossier non inscriptible et l'index corrompu donnent bien des
`ErreurUtilisateur` explicites (`cache.py:87-90`, `cache.py:227-232`,
testés) ; les quatre règles de rattachement sont dans l'ordre du contrat
(`inventaire.py:81-99`) et chacune est testée, priorités comprises.

**C1 — `indexer_dossier` s'écroule sur un fichier illisible, contre son propre
docstring (à corriger).** `cache.py:147` lit le fichier **hors** du
`try/except` de `cache.py:151-163` : un fichier sans droit de lecture lève
une `PermissionError` nue, qui n'est pas une `ErreurUtilisateur` et sort donc
en trace avec le code 1 — mesuré. Le docstring promet en `cache.py:137`
« un seul fichier abîmé ne doit pas faire échouer tout un import », et le
test existant (`tests/test_cache.py:185`) ne couvre que le contenu
illisible, pas le fichier illisible. *Correction : entrer `read_bytes()` dans
le `try` et attraper `OSError` au même endroit que `ErreurLecture`.*

**C2 — `lister()` rend l'index `debut` inutilisable (à corriger, léger).**
`cache.py:188-192` filtre sur `substr(debut, 1, 10) >= ?` : SQLite ne peut
pas se servir de `idx_activites_debut` (`cache.py:47`) sur une expression, le
balayage est donc complet. Sur 355 sorties c'est indolore, sur la cible
multi-utilisateur de la doctrine §10 ce n'est plus vrai. *Correction :
comparer directement `debut >= ?` avec la date ISO (les horodatages stockés
sont des ISO 8601, l'ordre lexicographique suit l'ordre chronologique) et
`debut < ?` avec le lendemain de `jusqua`.*

**C3 — `PRAGMA user_version` est écrit, jamais relu (à corriger, léger).**
`cache.py:29` et `cache.py:94` posent `VERSION_SCHEMA = 1` sans qu'aucun
chemin ne le vérifie à l'ouverture : au schéma 2, un index v1 sera relu comme
s'il était à jour. *Correction : lire `PRAGMA user_version` dans `__init__` et
lever une `ErreurUtilisateur` explicite (« supprimer l'index le reconstruira »)
si elle est inférieure à `VERSION_SCHEMA`.*

**C4 — l'ordre des règles de rattachement rendra la règle « home-trainer »
inopérante (question au mainteneur, pas un bug).** `inventaire.py:87-94`
applique bien le contrat : période avant intérieur. Or Q2 demande justement au
mainteneur « les périodes où chaque vélo a servi » : dès qu'une période
couvrira l'historique, toute séance de home-trainer tombant dedans sera
rattachée au vélo de route, et la règle 3 deviendra du code mort. Le
`% avec puissance` par vélo mélangera alors intérieur et extérieur.
*À remonter au mainteneur (Q2) plutôt qu'à corriger en silence : l'ordre
« intérieur avant période » est probablement celui qu'il veut.*

**C5 — l'inventaire est découpé en jours et en mois UTC (dette, à noter).**
`cache.py:188` et `inventaire.py:139` : une sortie du 31 à 23 h locale tombe
dans le mois suivant en UTC, et `--depuis` filtre sur des jours UTC. Sans
conséquence sur un inventaire annuel, à savoir avant de comparer un total
mensuel à Intervals.

## 4. Lot L1.4 — connecteur Intervals.icu

### Verdict : **à corriger**

La sécurité de la clé est le point le mieux traité du sprint (détail en §6) ;
l'authentification est passée par requête sans modifier un client injecté
(`intervals.py:64`, `intervals.py:120`), les erreurs HTTP ne citent que le
libellé d'endpoint et le code, `__repr__` est surchargé, et les 34 tests
n'utilisent que `MockTransport` avec des réponses fabriquées. La découpe
mensuelle est correcte (`intervals.py:171-181`, y compris le passage
décembre → janvier), le dédoublonnage par `id` est réel, `synchroniser` ne
télécharge que l'absent et continue après un échec.

**D3 — la détection de troncature repose sur une constante devinée, avec
perte de données silencieuse à la clé (à corriger).** `intervals.py:29` pose
`SEUIL_TRONCATURE = 100` et `intervals.py:81` ne redemande mois par mois
qu'au-delà. Si la vraie limite de l'API est inférieure à 100 (elle n'est pas
documentée et le lot n'a **pas** pu être vérifié sur le vrai service, faute
de clé — Q1), la troncature n'est pas détectée et des sorties manquent sans
un mot. Les tests confirment la mécanique mais sont construits sur la
constante elle-même (`tests/test_intervals.py:212`, `:234`, `:242`) : ils ne
peuvent pas dire qu'elle est fausse. *Correction : découper systématiquement
par mois (25 appels pour deux ans, c'est gratuit et déterministe), ou comparer
le nombre reçu à un `limit` explicitement demandé.*

**D4 — `date.today()` dans le cœur (à corriger, léger).**
`intervals.py:77` : `jusqua` par défaut vient de l'horloge et du fuseau du
système, au milieu d'un module qui se veut ignorant de son environnement
(règle absolue 2 — la lettre de la règle ne vise que le fichier de
configuration, l'environnement et les chemins, donc ce n'est pas une
violation, mais c'est la même famille de dépendance cachée et cela rend le
comportement dépendant du jour où l'on teste). *Correction : paramètre
`aujourdhui: date | None = None` injecté par l'appelant, comme
`heure_depart(..., maintenant=...)` le fait déjà en L1.5.*

**D5 — tri du dédoublonnage sur `start_date_local` (dette, à noter).**
`intervals.py:167` trie sur une chaîne d'heure locale sans décalage, alors
que tout le modèle interne est en UTC. L'ordre est bon tant que l'athlète ne
change pas de fuseau ; à savoir.

**D6 — statut de vérification.** L1.4 est **non vérifié sur les vraies
données** : aucune clé n'est disponible (Q1). Le connecteur n'a donc jamais
parlé au vrai service. C'est connu et assumé, mais rien ne le dit à un
lecteur du dépôt : `README.md:33` présente `ourouler inventaire`, « synchronisation
Intervals.icu » comprise, comme un livrable de sprint 1 sans réserve.
*Correction : une colonne ou une note « non vérifié sur vraies données (Q1) »
dans le tableau du README, et la même mention pour L1.2 et L1.3.*

## 5. Lot L1.5 — météo par direction

### Verdict : **à corriger**

C'est le lot le plus abouti et le seul **vérifié sur le vrai service** : j'ai
lancé `ourouler meteo` sur un point français inventé (45.0, 5.0) et la table
complète sort correctement avec AROME HD et le second avis. La formule de
destination sphérique est juste, y compris la normalisation de longitude
(`couronne.py:90`, `(deg + 540) % 360 - 180`), et les fonctions inverses
(haversine, azimut initial) servent réellement à la vérifier dans les tests.
Les règles du contrat sont appliquées à la lettre et testées aux bornes :
vent relatif ±45° inclus (`rapport.py:148-152`, `tests/test_meteo_rapport.py:60-79`),
confiance 0,3 / 0,1 avec le cas « 0,1 n'est pas < 0,1 »
(`tests/test_meteo_rapport.py:96-103`), meilleure direction au cumul minimal
avec départage par vent de face. Les deux modèles ne sont jamais moyennés.
Le second avis est apparié **par horodatage** et non par position
(`rapport.py:195-199`), son échec est dégradé proprement en « inconnu »
partout avec un avertissement sur stderr, et `single point → objet` est géré
et testé (`openmeteo.py:212-221`, `tests/test_meteo_openmeteo.py:117-125`).

**D1 — un point hors du domaine du modèle donne un message inutilisable
(à corriger).** Mesuré sur le vrai service : pour un point hors couverture
d'AROME, Open-Meteo répond **HTTP 200** avec un corps contenant
`"latitude":nan` — littéral `nan` en minuscules, donc JSON invalide, que
`reponse.json()` refuse. L'utilisateur reçoit
`Open-Meteo : réponse non-JSON sur https://api.open-meteo.com/v1/forecast (Expecting value: line 1 column 14)`
(`openmeteo.py:117-120`), qui ne dit rien de la cause. C'est reproductible
avec le fichier du dépôt : `uv run ourouler --config tests/fixtures/config_test.toml meteo`
échoue ainsi, alors que ce fichier est précisément donné comme parcours de
vérification de bout en bout. *Correction : détecter ce corps (tentative de
parsing tolérante, ou test du `nan` avant parsing) et lever une
`ErreurUtilisateur` qui nomme la cause : « le point est hors du domaine de
<modèle> — utiliser un modèle global, par exemple --modele icon_seamless ».*

**D2 — `--depart` avec une date au-delà d'un changement d'heure se décale d'une
heure (à corriger).** `meteo/commande.py:83` prend
`datetime.now().astimezone()`, dont le `tzinfo` est un fuseau **à décalage
fixe** (CEST +02:00 en septembre), puis `meteo/commande.py:100` l'applique
telle quelle à la date demandée. Mesuré : `--depart 2026-12-20T10:00` demandé
en septembre produit `2026-12-20 10:00+02:00`, c'est-à-dire 09:00 UTC là où
il fallait 09:00 → 10:00 UTC ; toute la fenêtre de prévision est décalée
d'une heure. Symétriquement, une date d'été demandée en hiver décale dans
l'autre sens. Les tests ne peuvent pas l'attraper parce qu'ils injectent
eux-mêmes des fuseaux à décalage fixe (`tests/test_meteo_commande.py:100`,
`timezone(timedelta(hours=2))`) : le mock reproduit exactement la
simplification qui cause le bug. *Correction : pour un horodatage naïf,
`t.astimezone()` (qui applique le décalage réel de cette date-là) au lieu de
`t.replace(tzinfo=reference.tzinfo)` ; et un test avec
`ZoneInfo("Europe/Paris")` de part et d'autre du dernier dimanche d'octobre.*

**D7 — une direction sans donnée passe pour la plus sèche (à corriger).**
`rapport.py:110-111` : une cellule dont `pluie_mm` vaut `None` n'ajoute rien
au cumul. Une direction dont le modèle ne rend aucune pluie affiche donc un
cumul de 0,0 mm et sera **conseillée**, avec le motif « cumul de pluie le
plus faible ». C'est exactement l'affirmation sans mesure que la règle
absolue 5 interdit. *Correction : compter les cellules manquantes par
direction et, soit exclure de `meilleure_direction` une direction
incomplète, soit le dire dans le motif (« 3 h sans donnée »).*

**D8 — la ligne « ici » affiche un vent relatif qui n'a pas de sens
(à corriger, léger).** Le point de départ est créé avec `azimut_deg = 0.0`
(`couronne.py:104-108`), et `rapport.py:209` calcule donc son vent relatif
comme si l'on partait plein nord : la table réelle affiche
`ici  0.0 16f 23°`, ce « f » laissant croire à un vent de face sur place.
`meilleure_direction` exclut bien « ici » (`rapport.py:104`), le rendu non.
*Correction : ne pas mettre de lettre pour `NOM_ICI` dans `_case`, ou y
afficher l'origine cardinale du vent.*

**D9 — `NaN` accepté comme valeur numérique (à corriger, léger).**
`openmeteo.py:185-199` rejette les booléens et les types inattendus mais
laisse passer `float("nan")` (un `"NaN"` majuscule dans le JSON est accepté
par le module `json` de Python). Un NaN de pluie se propage alors dans les
cumuls et rend `meilleure_direction` arbitraire, sans aucun message —
`lecture.py:429` écarte pourtant explicitement les NaN, l'asymétrie est
accidentelle. *Correction : `return x if x == x else None` comme dans
`lecture.py`.*

**D10 — largeur de cellule et libellés d'heures (dette, à noter).**
`LARGEUR_CELLULE = 12` (`rapport.py:38`) suffit pour « 0.0 14f 12°? » mais
pas pour une pluie à deux chiffres (« 10.0 14f 12°? »), qui décalera la
colonne suivante. Et pendant le retour à l'heure d'hiver, deux heures UTC
différentes s'affichent sous la même étiquette « 02h » (`rapport.py:280`) :
ambigu, pas faux.

## 6. Sécurité de la clé Intervals — tous les chemins d'erreur et de log

Parcours exhaustif fait. La clé ne fuit **sur aucun chemin d'exécution** :

- `intervals.py:116-130` : les messages ne citent que le libellé d'endpoint
  (`"athlete/{id}/activities"`, littéral non interpolé) et le code HTTP ; le
  message de l'exception httpx d'origine est remplacé par son seul
  `type(e).__name__`, ce qui évite d'embarquer une URL.
- `intervals.py:66-67` : `__repr__` surchargé ; `httpx.BasicAuth` ne stocke
  que l'en-tête encodé et n'a pas de `__repr__` bavard (vérifié).
- `intervals.py:250` : les messages du `RapportSynchro` ne portent que
  l'identifiant d'activité et une `ErreurConnecteur` déjà assainie.
- `activites/commande.py:59-63` : `--synchroniser` sans clé refuse sans rien
  imprimer de sensible.
- `cli.py:58` : la clé est masquée dans `ourouler config --json`, et le
  rendu texte ne dit que « renseigné / non renseigné ».
- Aucun `print`, `logging` ni `warnings` ne touche la configuration ailleurs.

Une seule brèche, hors du connecteur : **A2**, `repr(Config)` /
`repr(ParametresIntervals)` imprime la clé en clair (mesuré). C'est le seul
correctif de sécurité à faire, et il est d'une ligne.

Point annexe : les messages Open-Meteo citent l'URL **sans ses paramètres**
(`openmeteo.py:71-72`), donc sans les coordonnées du départ. C'est un bon
réflexe de confidentialité, à conserver explicitement si un jour on ajoute
des logs.

## 7. Qualité des tests

325 tests, lisibles, paramétrés aux bornes, avec de vraies mesures là où il
faut (le test de dénivelé mesure l'atténuation du bruit au lieu d'affirmer un
zéro qu'on n'obtient pas ; les tests de couronne retrouvent distances et
azimuts à mieux que 0,5 % y compris à 60° de latitude). Aucun test ne touche
le réseau : vérifié à la main et par `tests/test_invariants.py:69`. Quatre
réserves.

**E1 — l'invariant « aucune coordonnée réelle dans les fixtures » ne mesure
pas les fixtures (à corriger).** `tests/test_invariants.py:83-90` vérifie que
le **texte source du générateur** contient `LAT_FICTIVE = 0.0` et que
`config_test.toml` contient `latitude = 0.0`. Le test ne lit aucun fichier de
fixture : remplacer `boucle.gpx` par une trace réelle, ou ajouter un décalage
ailleurs dans le générateur, le laisse vert. Il ne couvre pas non plus
`config.example.toml` — et c'est précisément là que la coordonnée réelle se
trouve (A1). L'invariant du contrat §5 (« aucune fixture ne contient de
coordonnée à moins de 50 km d'une ville française réelle ») n'est donc pas
mesuré. *Correction : lire les `.gpx`/`.tcx`/`.fit` du dossier de fixtures,
extraire les coordonnées et affirmer |lat| < 0,5 et |lon| < 0,5 ; étendre au
`config.example.toml`.*

**E2 — le garde-fou réseau laisse une porte (à corriger, léger).**
`tests/test_invariants.py:69-80` interdit `httpx.Client(...)` sans
`MockTransport`, mais rien n'empêche un futur test d'écrire
`ClientOpenMeteo()` ou `ClientIntervals(a, k)` sans client injecté : les deux
ouvrent alors un vrai client (`openmeteo.py:67`, `intervals.py:61`). Aucun
test actuel ne le fait (vérifié), donc c'est de la prévention. *Correction :
une fixture `autouse` dans `conftest.py` qui remplace `socket.socket` par une
levée d'exception — c'est la mesure de l'invariant, pas son approximation.*

**E3 — un test dont l'assertion ne peut pas contredire son intitulé.**
`tests/test_lecture.py:208` : `test_np_superieure_a_la_moyenne_si_variable`
affirme dans son nom et son docstring « NP > moyenne », puis assert
`195 < np < 205` alors que la moyenne vaut 200 — l'assertion est donc vraie
même si la NP est inférieure à la moyenne. Le test est utile (il mesure le
lissage 30 s), son nom est faux. *Correction : renommer en
« l'alternance rapide est lissée par la fenêtre de 30 s », et laisser la
démonstration NP > moyenne au test suivant, qui la fait vraiment.*

**E4 — deux angles morts, tous deux confirmés comme bugs réels.** Le contrat
§5 annonçait « passage à l'heure d'été dans la fenêtre » et des horodatages
irréguliers dans la cible du testeur adversarial : aucun test ne couvre ni
l'un (les mocks injectent des fuseaux à décalage fixe, D2) ni l'autre (le
paramètre `pas_s` de `_points` n'est jamais utilisé avec un pas variable, B1).
Ce sont exactement les deux endroits où une mesure a trouvé un écart.

## 8. Dette et lisibilité

Le style demandé par `CLAUDE.md` est respecté sans exception notable : code
direct, docstrings qui expliquent le *pourquoi* (le choix de garder le
sous-sport FIT, la raison du rayon sphérique, le refus de `or` pour
`--horizon 0`), français partout, identifiants sans accents, aucune ligne
« maligne ». Les fonctions longues (`lire_fit`, `rendre_texte`) restent
linéaires et se lisent de haut en bas. Le découpage `couronne` / `openmeteo`
/ `rapport` / `commande` est propre et testable séparément. `_remplacer`
(`config.py:211-214`) est un enrobage inutile autour de
`dataclasses.replace` avec un import local — la seule petite coquetterie du
sprint.

**Fixtures de 712 Ko : acceptable, mais redondant.** 340 points par trace,
`boucle.tcx` à 219 Ko, `boucle.gpx` à 145 Ko. La taille en soi ne gêne pas un
dépôt git (aucune de ces fixtures ne changera plus). Ce qui est discutable,
c'est de les **versionner alors que `conftest.py:43-44` les régénère quand
elles manquent** : le générateur est déjà la source de vérité, versionner sa
sortie ajoute 712 Ko de binaire et un risque de dérive entre les deux.
*Deux options cohérentes : les ignorer dans git et laisser la fixture les
produire (le plus propre), ou garder les fichiers et réduire les traces à
~60 points, largement assez pour ce qui est testé.* À trancher, pas bloquant.

## À corriger avant de montrer au mainteneur

Par gravité décroissante.

1. **`config.example.toml:7-12` et `:29` — données personnelles réelles dans
   le dépôt** (masse 91 kg, FTP 258 W, centre de Rennes, `i183365`), en
   violation de la règle absolue 1, dans un dépôt destiné à devenir public.
   Remplacer par des valeurs manifestement inventées et retirer « Rennes ».
   **Bloquant.**
2. **`docs/questions_mainteneur.md:17-19`, `docs/plan_sprints_agents.md:83-86`,
   `docs/cadrage.md:12` — même règle, autres fichiers** : noms d'équipement
   réels (`rcr`, `VR`, `BMC`), nombres de sorties, kilométrage, dates, FTP et
   masse. Et `README.md:48` affirme le contraire (« rien de personnel n'entre
   dans ce dépôt »). Décider avec le mainteneur ce qui reste avant l'ouverture
   du dépôt (Q6) : anonymiser, ou sortir ces chiffres dans un fichier ignoré
   par git. **Bloquant pour la publication.**
3. **`config.py:66-73` — la clé d'API Intervals est imprimée par
   `repr(Config)`.** `repr=False` sur le champ (ou un `__repr__` masquant), et
   étendre le test d'invariant de `tests/test_intervals.py:102` à `Config`.
4. **`meteo/commande.py:83` et `:100` — décalage d'une heure sur `--depart`
   au-delà d'un changement d'heure** (mesuré : +02:00 appliqué à une date de
   décembre). Utiliser `t.astimezone()` sur l'horodatage naïf ; test avec
   `ZoneInfo("Europe/Paris")` de part et d'autre du basculement.
5. **`openmeteo.py:117-120` — point hors du domaine du modèle : message
   inutilisable.** Open-Meteo répond 200 avec des `nan` non-JSON ; dire « hors
   du domaine de <modèle>, essayer un modèle global ». Rend au passage
   utilisable le parcours de vérification documenté dans
   `tests/fixtures/config_test.toml`.
6. **`cache.py:147` — `indexer_dossier` s'écroule en trace sur un fichier
   illisible**, contre son docstring. Entrer `read_bytes()` dans le `try` et
   attraper `OSError`.
7. **`modele.py:71-93` — NP faussée de 15 % par un échantillonnage irrégulier,
   et docstring qui affirme l'inverse.** Pondérer par la durée, puis
   remplacer l'affirmation par la mesure.
8. **`intervals.py:29` et `:81` — `SEUIL_TRONCATURE = 100` deviné, avec perte
   de sorties silencieuse si la vraie limite est plus basse.** Découper
   systématiquement par mois, ou demander une `limit` explicite. D'autant plus
   important que le lot n'a pas pu être vérifié sur le vrai service.
9. **`tests/test_invariants.py:83-90` — l'invariant « aucune coordonnée réelle »
   grep le générateur au lieu de lire les fixtures**, et ignore
   `config.example.toml`. Le réécrire en mesure ; c'est ce test qui aurait dû
   attraper le point 1.
10. **`cli.py:33` — `ourouler meteo --json` est refusé** alors que le contrat
    l'écrit ainsi. Ajouter `--json` aux sous-parseurs.
11. **`rapport.py:110-111` — une direction sans donnée est conseillée comme la
    plus sèche.** Exclure ou annoncer l'incomplétude dans le motif.
12. **`README.md:32-33` — L1.2, L1.3 et L1.4 apparaissent comme livrés sans la
    mention « non vérifié sur vraies données » (Q1, fichiers réels absents).**
    L'ajouter noir sur blanc.
13. **`config.py:141-145` et `:175-181` — validations manquantes** :
    `distances_km` négatives silencieusement ignorées, et
    `historique_depuis` en datetime TOML casse en `TypeError`.
14. **`rapport.py:209` — la ligne « ici » affiche un vent de face/dos/travers
    dépourvu de sens.** Supprimer la lettre pour `NOM_ICI`.
15. **`openmeteo.py:185-199` — `NaN` accepté** là où `lecture.py:429` le rejette.
16. **`lecture.py:87-90` — FIT multi-sessions : distance de la dernière session
    seulement**, en silence.
17. **`inventaire.py:87-94` — ordre « période avant intérieur »** : conforme au
    contrat, mais rendra la règle home-trainer inopérante dès que Q2 sera
    renseignée. À reposer au mainteneur, pas à corriger de sa propre autorité.

## Dette assumée, à noter au plan

- **L1.2, L1.3, L1.4 non vérifiés sur les vraies données** : pas de clé
  Intervals (Q1), pas de fichiers d'activité réels fournis. Assumé et annoncé
  dans le contrat §6 ; à écrire aussi dans le README (point 12 ci-dessus).
  L1.5 est vérifié, et je l'ai revérifié moi-même sur le vrai service.
- **Fixtures de 712 Ko versionnées alors que `conftest.py` les régénère** :
  acceptable, mais redondant avec le générateur. Les ignorer dans git, ou
  réduire les traces à ~60 points.
- **Lissage du dénivelé sur 5 points** (`modele.py:18`) : choix non mesuré
  contre une référence. Le test mesure l'atténuation du bruit, pas la
  justesse du dénivelé. À calibrer quand des fichiers réels existeront.
- **NP : pas de rejet des 30 premières secondes** (fenêtre partielle au
  démarrage) — écart connu avec l'implémentation de référence, négligeable
  devant B1 mais à documenter une fois B1 corrigé.
- **Découpage jour/mois en UTC** dans le cache et l'inventaire
  (`cache.py:188`, `inventaire.py:139`).
- **`PRAGMA user_version` écrit sans contrôle de migration** (`cache.py:94`).
- **`date.today()` dans le connecteur** (`intervals.py:77`) : dépendance
  cachée à l'horloge du système dans un module du cœur.
- **Tri du dédoublonnage Intervals sur `start_date_local`**
  (`intervals.py:167`), alors que le modèle interne est en UTC.
- **Garde-fou réseau par analyse statique** plutôt que par blocage de socket
  (`tests/test_invariants.py:69`) ; et l'exemption « `cli.py`/`config.py` »
  se fait sur le **nom** de fichier (`tests/test_invariants.py:20`), donc un
  futur `sous_paquet/config.py` serait exempté sans le vouloir.
- **Largeur de cellule 12** insuffisante pour une pluie à deux chiffres, et
  étiquettes d'heures ambiguës au retour à l'heure d'hiver (`rapport.py:38`,
  `:280`).
- **Écarts au contrat acceptés** : sous-commande `config` en plus
  (`cli.py:44`), `HORIZON_MAX_H = 48` en plus (`meteo/commande.py:22`),
  `construire(..., modele=, second_avis=)` en mots-clés en plus
  (`rapport.py:172-174`), `Cache.relire` et `Cache.contient_identifiant` en
  plus (`cache.py:177`, `:210`). Tous utiles, aucun ne contredit le contrat ;
  à enregistrer comme surface publique du sprint.
- **`_remplacer`** (`config.py:211-214`) : enrobage inutile de
  `dataclasses.replace`, à supprimer au prochain passage dans le fichier.

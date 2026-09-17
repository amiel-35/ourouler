# Discovery données — CLI vers interface web

Garde-fou contre la fiction : ce document dit, écran par écran, quelles
données existent réellement dans le code au 16/09/2026, lesquelles se
déduisent, et lesquelles n'existent pas du tout. Chaque affirmation est
sourcée par un chemin de fichier. Rien n'est deviné.

Doctrine de référence : `doctrine_architecture.md:206-207` — « Chaque
commande rend du JSON. C'est la future réponse d'API, et donc le contrat du
front. »

## 1. Inventaire des sous-commandes

Déclarées dans `src/ourouler/cli.py:39-48`. Toutes acceptent `--json`
(mécanisme `parent_json()`, `src/ourouler/cli.py:55-79` — avant ou après la
sous-commande).

| Commande | Entrée | Sortie texte | Sortie `--json` | Module |
|---|---|---|---|---|
| `config` | rien (lit la config chargée) | résumé lisible | oui, clé et mot de passe masqués | `cli.py:113-161` |
| `inventaire` | `--depuis`, `--importer DOSSIER`, `--synchroniser`, `--sans-rafraichir` | tableau par vélo/mois | oui | `src/ourouler/activites/commande.py:19-51`, JSON : `src/ourouler/activites/inventaire.py:317-349` |
| `meteo` | `--heure-depart`, `--horizon`, `--distance`, `--modele`, `--second-avis` | grille par direction/heure | oui | `src/ourouler/meteo/commande.py:26-74`, JSON : `src/ourouler/meteo/rapport.py:359-386` |
| `boucle` | `--distance`, `--direction`, `--heure-depart`, `--candidates`, `--profil`, `--sortie`, `--ecraser`, `--gpx`, `--velo`, `--puissance` | tableau de candidates + GPX écrit | oui | `src/ourouler/boucle/commande.py:151-…`, JSON : `boucle/commande.py:896-1010` |
| `routes apprendre\|stats\|poids` | `--depuis`, `--max`, `--appliquer` | texte par action | oui (aux 3 niveaux) | `src/ourouler/apprentissage/commande.py:70-…` |
| `calibrer` | `--velo`, `--depuis`, `--max` | rapport d'ajustement CdA/Crr | oui | `src/ourouler/physique/commande.py:186-…`, JSON : `physique/commande.py:444-508` |
| `simuler` | `--gpx` (obligatoire), `--puissance` (obligatoire), `--velo`, `--heure-depart` | temps simulé | oui | `physique/commande.py:518-…`, JSON : `physique/commande.py:671-704` |
| `comparer` | `--velos VELO VELO` (obligatoire), `--zone`, `--pente-max`, `--cap-max`, `--longueur-min`, `--depuis` | comparaison deux vélos | oui | `src/ourouler/physique/comparer.py:465-…`, JSON : `comparer.py:785-855` |
| `seance` | `--jour` | étapes de la séance du jour | oui | `src/ourouler/seance/commande.py:129-163`, JSON : `seance/commande.py:359-395` |
| `sortie` | `--jour`, `--distance`, `--direction`, `--candidates`, `--vent`, `--velo`, `--heure-depart`, `--sortie`, `--carte`, `--profil`, `--ecraser`, `--carte-sans-seance` | tableau + GPX + carte HTML | oui | `src/ourouler/sortie/commande.py:220-…`, JSON : `sortie/commande.py:1553-1632` |

Toutes les 10 commandes savent rendre du JSON. Aucune n'est texte-seul.

## 2. Forme réelle de chaque sortie JSON

### `config --json` (`cli.py:122-136`)

`dataclasses.asdict(config)` + masquage explicite de `intervals.api_key` et
`brouter.mot_de_passe` (`cli.py:133-134`). Reflète 1:1 les dataclasses de
`src/ourouler/config.py` (voir §3). Rien n'est nul par construction : toutes
les valeurs viennent d'une config chargée avec succès.

### `inventaire --json` (`activites/inventaire.py:317-349`)

```
{depuis, total, autres_sports, autres_sports_par_libelle,
 par_velo: [{velo, nombre, km, heures, premiere|null, derniere|null,
             avec_puissance, part_puissance, capteurs[]}],
 par_mois: [{mois, sorties, km, sorties_avec_puissance}],
 anomalies: [{identifiant, jour|null, motif}],
 journal: []}   # ajouté par activites/commande.py:43
```
`premiere`/`derniere` nuls si aucune sortie datée pour ce vélo.

### `meteo --json` (`meteo/rapport.py:359-386`)

```
{depart:{nom,latitude,longitude}, debut, horizon_h, modele, second_avis,
 meilleure_direction:{nom,motif},
 cellules:[{direction, distance_km, t, pluie_mm, pluie_second_avis_mm|null,
            vent_kmh, vent_depuis_deg, vent_relatif, ressenti_c, confiance}]}
```
`pluie_second_avis_mm` nul si le second avis a échoué
(`meteo/commande.py:48-57`, avertissement sur stderr, jamais dans le JSON).

### `boucle --json` (`boucle/commande.py:896-1010`)

```
{depart, demande, vitesse_moyenne_kmh, sens_prefere, modele, second_avis,
 gpx|null, poids_routes|null, modele_physique|null,
 candidates:[{numero, retenue, nom, distance_km, denivele_m,
   denivele_source, temps_estime_s, temps_source, vitesse_meteo_kmh|null,
   azimut_deg, rayon_m, ecart_relatif, total_tri, couts_partiels,
   segments_ignores, antennes_source, antennes, distance_source,
   cout_km_moyen, part_connue, km_par_highway{}, couts{...},
   meteo|null:{pluie_cumulee_mm, minutes_pluie, part_vent_face,
     part_vent_dos, n_vent_connu, n_echantillons, ressenti_min_c,
     confiance, echantillons:[{dist_m,t,cap_deg,pluie_mm,vent_kmh,
       vent_relatif,ressenti_c}]}, meta{}}]}
```
`meteo` de chaque candidate est `null` si Open-Meteo est tombé en panne
(`boucle/commande.py:20-23` du docstring : « la météo est le seul maillon
qu'on accepte de perdre »). **Aucun point lat/lon du tracé n'est dans ce
JSON** — seulement des agrégats (distance, dénivelé, coûts). La géométrie
n'existe que dans le GPX écrit sur disque (`--sortie FICHIER.GPX`).

### `seance --json` (`seance/commande.py:359-395`)

```
{jour, nom, duree_s, n_blocs, distance_estimee_m,
 vitesses:{provenance, velo, calibree, vitesse_kmh|null}, meta{},
 avertissements:[texte...],
 etapes:[{indice, type, libelle, duree_s, elastique, puissance_min_w|null,
   puissance_max_w|null, puissance_cible_w|null, vitesse_kmh|null,
   longueur_m|null, recuperation_suivante_s|null, route_au_dela_m|null}]}
```
Sans séance ce jour-là : `{"jour": ..., "seance": null}`
(`seance/commande.py:150-155`) — forme **différente** de la forme nominale,
un front doit tester la présence de `seance` avant de lire `etapes`.
`puissance_*_w` est nul pour une étape libre (`freeride`) ou d'unité non
reconnue (`seance/intervals.py:17-19`).

### `sortie --json` (`sortie/commande.py:1553-1632`, le plus riche)

```
{jour, seance:{nom,duree_s,n_etapes,n_blocs,meta}, demande{...},
 modele_physique, modele_meteo|null, seuil_bloc_bien_place,
 tolerance_egalite, gpx|null, carte|null,
 ecartees:[{azimut_deg,distance_km,motif}],
 tenue|null:{categorie_temp, categorie_humidite, base[], a_emporter[],
   a_enlever[], motifs[]},
 propositions:[{numero, retenue, distinction, axe_distinctif|null,
   duree_s, depassement_seance_s|null, demi_tours, pluie_mm|null,
   densite_marqueurs_km|null, part_trafic|null, orientation_vent,
   note_terrain, recouvrement_max_avec{}}],
 question_vent|null:{posee, motif|null, vent_kmh, vent_depuis_deg,
   seuil_kmh, horizon_jours, reponse, azimuts_recherche_deg[], choix[],
   azimuts_par_choix{}},
 motif_deux_propositions|null,
 candidates:[{numero, retenue, nom, distance_km, denivele_m, azimut_deg,
   ecart_relatif, part_connue, vitesse_kmh,
   placement:{note_totale, note_terrain, penalite_seance, decalage_z2_s,
     duree_totale_s, distance_totale_m, denivele_parcours_m|null,
     blocs_bien_places, demi_tours, avertissements[], informations[],
     emplacements:[{etape_idx, debut_m, debut_parcouru_m, longueur_m,
       demi_tour, note|null, motifs|null, pente_moyenne|null,
       pente_max|null, carrefours|null, km_batis|null, descente_m|null,
       montee_m|null}]},
   couts{...}, meteo|null:{...,modele_utilise,repli}}]}
```
Sans séance : même forme dégradée que `seance --json`, mais avec en plus
`--carte-sans-seance` qui écrit quand même une page HTML « rien de prévu »
(`cli.py:449-455`, `sortie/carte.py:1248` `construire_page_sans_seance`).

**Ici non plus, aucune géométrie de tracé (lat/lon) n'est dans le JSON.**
`--sortie` écrit un GPX (le parcours réellement roulé, demi-tours compris) ;
`--carte` écrit une page HTML autonome (Leaflet) qui embarque elle-même les
coordonnées via `_charge_json` (`sortie/carte.py:551`) — **pas exposées en
JSON consommable par un autre client que cette page**.

### `calibrer --json`, `simuler --json`, `comparer --json`

Détaillés dans le tableau §1 (chemins). Champs numériques, jamais de
lat/lon. `calibrer` peut renvoyer des `avertissements` et
`bornes_atteintes` (`physique/commande.py:481-484`) quand l'ajustement a
buté sur une borne physique — à afficher, pas à cacher (règle absolue 5).

## 3. Confrontation aux écrans voulus

### Assistant de configuration

| Donnée demandée | Existe | Se déduit | N'existe pas |
|---|---|---|---|
| Nom, prénom | | | **Aucun champ.** `Cycliste` (`config.py:44-47`) n'a que `masse_kg`, `ftp_w`. À ajouter au modèle. |
| Âge | | | Idem — absent de `Cycliste`. |
| Poids | `cycliste.masse_kg`, `config.py:46` | | |
| FTP | `cycliste.ftp_w`, `config.py:47` | | |
| Calage des zones de puissance | | | **`ZONES_PUISSANCE_DEFAUT`** (`seance/modele.py:52-60`) est une constante Python, table de Coggan figée. Aucun champ `Config` ne la porte : `seance/intervals.py:172` prend `zones_puissance` en paramètre mais tous les appelants (`seance/commande.py:146`, `sortie/commande.py:525`) passent toujours `ZONES_PUISSANCE_DEFAUT`. Éditer les zones demande d'ajouter une section `[seance.zones]` à `Config` et de la faire suivre jusqu'aux deux appelants — pas un simple champ, une plomberie à trois endroits. |
| Adresse de départ | `depart.nom/latitude/longitude` en TOML (`config.py:38-41`) | | **Aucune géocodification.** `--adresse-depart` est un nom réservé, non livré (`cli.py:85-92`, `docs/questions_mainteneur.md:519-524`). L'utilisateur doit connaître ses lat/lon. |
| Vélo : type route/CLM/gravel | `usage` existe (`config.py:60`) | | **`gravel` n'est pas une valeur acceptée.** `USAGES_VELO = ("route", "clm")` (`config.py:22`), validé strictement à l'écriture (`config.py:685-686`, lève `ErreurConfig`). Il faudrait étendre le tuple + vérifier ce que ça change en aval (choix du profil BRouter, etc. — pas vérifié ici). |
| Vélo : poids | `velo.masse_kg` (`config.py:66`) | | |
| Connexion Intervals.icu (clé d'API) | Champs `athlete_id`/`api_key` (`config.py:97-98`), variables d'env `INTERVALS_API_KEY`/`INTERVALS_ATHLETE_ID` (`config.py:329-332`) | Un « tester la connexion » se déduit en appelant `ClientIntervals.equipements()` ou `.activites()` une fois et en regardant si ça lève `ErreurConnecteur` (`connecteurs/intervals.py:149-166`) | **Aucune commande de validation dédiée** — `config --json` affiche seulement `renseigne` (bool, `config.py:104-106`), pas « la clé marche ». |

### Demande d'itinéraire manuel (durée, date, adresse de départ éventuellement différente)

| Donnée | Existe | Se déduit | N'existe pas |
|---|---|---|---|
| Durée | Pas directement — `boucle --distance` prend une distance, pas une durée | Se déduit d'une durée voulue via la vitesse moyenne (`config.boucle.vitesse_moyenne_kmh`) ou le modèle calibré, comme `sortie` le fait déjà pour convertir une séance en distance (`sortie/commande.py`, constante d'arrondi `ARRONDI_DISTANCE_KM`) — logique à extraire, pas à écrire de zéro | |
| Date, avec vent qui n'entre que si proche | `sortie` porte déjà cette règle : le vent n'est demandé que si `<= HORIZON_ORIENTATION_J` jours (`sortie/vent_demande.py`, utilisé `sortie/commande.py:9-13` du docstring) | | |
| Adresse de départ différente | | | Même trou que ci-dessus : pas de géocodification. `boucle`/`sortie` n'ont même pas d'option `--adresse-depart` réservée avec un TODO actif — le nom est juste gardé par un test (`cli.py:87-91`). |

### Upload d'un fichier de séance (`.FIT`, `.MRC`, `.ZWO`)

| Format | Existe | Se déduit | N'existe pas |
|---|---|---|---|
| `.FIT` en tant qu'**activité roulée** | `activites/lecture.py:31` (`EXTENSIONS = ("fit","gpx","tcx")`), via `fitdecode` (dépendance `pyproject.toml:11`) | | |
| `.FIT` en tant que **séance planifiée** (structure de blocs) | | | Rien ne lit un FIT structuré-entraînement (workout FIT, différent d'un FIT d'activité) — `lire_fit` (`activites/lecture.py:68-108`) ne produit qu'une trace de points GPS/puissance, pas des étapes. |
| `.MRC` | | | **Aucune trace dans le code ni dans `pyproject.toml`.** Aucune bibliothèque de parsing MRC. |
| `.ZWO` (Zwift workout, XML) | | Se déduirait avec `xml.etree` (déjà utilisé pour TCX, `activites/lecture.py:17`) et un peu d'écriture — pas de dépendance à ajouter | **Aucun parseur aujourd'hui.** |
| Séance structurée (bloc par bloc) | `seance/intervals.py` sait lire un `workout_doc` **venant d'Intervals.icu par API**, pas d'un fichier local | Le modèle `Etape`/`Seance` (`seance/modele.py:107-…`) est déjà la structure cible ; un futur lecteur `.ZWO`/`.MRC` n'aurait qu'à produire les mêmes objets — le cœur ne changerait pas | La commande CLI ne prend aucune option d'upload de fichier de séance (`cli.py:391-398`, `seance` ne connaît que `--jour`). |

### Liste des séances de la semaine (Intervals) + bouton « générer l'itinéraire »

| Donnée | Existe | Se déduit | N'existe pas |
|---|---|---|---|
| Séance d'**un** jour donné | `seance --jour` (`cli.py:397`, `seance/commande.py:129-163`) | | |
| Connecteur bas niveau multi-jours | `ClientIntervals._activites_fenetre(depuis, jusqua)` existe pour les **activités** passées (`connecteurs/intervals.py:179-185`) | `ClientIntervals.evenements(jour)` (`connecteurs/intervals.py:168-175`) force `oldest=newest=jour` — la même méthode API accepte une fenêtre côté Intervals (vu dans `_activites_fenetre`), mais le wrapper ne l'exploite pas pour les séances planifiées : élargir `evenements()` à `(depuis, jusqua)` est un changement d'une ligne de signature + son appelant | |
| Commande « liste de la semaine » | | Se construit en bouclant `seance_du_jour` sur 7 jours, ou en élargissant `evenements()` comme ci-dessus — le rendu JSON par jour existe déjà (`seance/commande.py:359`), il suffit de l'agréger | **Aucune commande CLI ne liste plusieurs jours.** `seance` est strictement mono-jour. |
| « Générer l'itinéraire » pour une séance de la liste | `sortie --jour AAAA-MM-JJ` fait exactement ça pour un jour donné (`cli.py:407-456`) | Le bouton par séance de la liste se déduit trivialement : il appelle `sortie --jour <celui de la ligne>` | |

### Page du jour (propositions, cartes, tenue, GPX)

| Donnée | Existe | Se déduit | N'existe pas |
|---|---|---|---|
| Propositions contrastées (2 ou 3) | `sortie --json` → `propositions[]` avec `distinction`, `axe_distinctif`, notes (`sortie/commande.py:1553-1632`) | | |
| Tenue | `sortie --json` → `tenue{base,a_emporter,a_enlever,motifs}` (`sortie/commande.py:1553-…`), configurable par catégorie (`config.example.toml:102-114`, `seance/tenue.py:39-46`) | | |
| GPX | Écrit sur disque par `--sortie FICHIER.GPX` (chemin dans le JSON, `sortie/commande.py:1553` champ `gpx`) | Le contenu binaire du fichier n'est pas dans le JSON — un endpoint web devrait le servir séparément (lecture disque, ou faire écrire en mémoire) | Pas de GPX par proposition dans le JSON : le docstring dit qu'il y en a un par proposition sur la **page HTML** (`sortie/commande.py:37-38` du docstring, « un GPX par proposition, téléchargeable depuis la page ») mais **`rendre_json` n'expose pas leurs chemins individuellement** — seul le GPX de la candidate retenue (`gpx`) est dans le JSON. |
| Carte | Page HTML autonome écrite par `--carte FICHIER.HTML` (`sortie/carte.py`, Leaflet + OSM, tout le reste inline) | Le chemin est dans le JSON (`carte`), pas son contenu | **Pas de géométrie exploitable en JSON** pour redessiner la carte dans un composant web autre que cette page HTML — voir §2. Un front qui veut sa propre carte devrait soit servir/iframer le HTML généré, soit ajouter un export JSON de la géométrie (nouveau code). |

## 4. Points durs

### Géocodification

**N'existe pas.** Recherché exhaustivement (`grep -rn "géocod\|geocod\|Nominatim\|photon"` sur `src/`) : zéro occurrence dans le cœur. `--adresse-depart` est un nom **réservé mais non implémenté** (`cli.py:82-92`, décision Q15 du 13/09/2026, `docs/questions_mainteneur.md:511-524`). La seule mention de Nominatim est une intention future notée dans une réponse du mainteneur (`docs/questions_mainteneur.md:57-61`) — jamais codée. Aujourd'hui, la configuration exige des `latitude`/`longitude` numériques saisies à la main (`config.example.toml:6-7`).

### Zones de puissance

Le code **connaît** une table fixe (Coggan, `ZONES_PUISSANCE_DEFAUT`, `seance/modele.py:52-60`), documentée comme calée sur les `zoneTimes` observés du compte Intervals.icu du mainteneur. Elle sert deux fois : traduire une consigne `power_zone` en watts, et approximer une consigne `hr_zone` haute (`seance/intervals.py:36-41`). **Rien dans `Config` ne permet de la modifier** — contrairement à `puissance_endurance_pct` ou `seuil_recuperation_pct`, qui sont bien des champs `ParametresSeance` éditables en TOML (`config.py:143-172`, `config.example.toml:73-92`). Éditer les zones demanderait : (1) un champ `Config` (ex. `[seance.zones]`, 7 paires bas/haut) ; (2) sa validation au chargement (comme `_zones()` le fait déjà côté lecture Intervals, `seance/intervals.py:844-856`, réutilisable) ; (3) le faire passer jusqu'aux deux appelants (`seance/commande.py:146`, `sortie/commande.py:525`) qui aujourd'hui codent en dur `ZONES_PUISSANCE_DEFAUT`.

### Formats de séance

- Activités roulées : `.fit`/`.gpx`/`.tcx` (`activites/lecture.py:31`), bibliothèques `fitdecode` et `gpxpy` en dépendance (`pyproject.toml:9-10`), TCX via `xml.etree` stdlib.
- Séances planifiées (structurées en blocs) : **une seule source, l'API Intervals.icu** (`seance/intervals.py`), jamais un fichier local.
- `.MRC` : zéro bibliothèque, zéro code.
- `.ZWO` : zéro bibliothèque, zéro code — mais XML, donc `xml.etree` (déjà une dépendance de fait) suffirait à en écrire un lecteur qui produit des `Etape` (`seance/modele.py:107`).

### Durée d'une génération

Aucune mesure de **temps d'horloge** (wall-clock) n'est consignée nulle part dans le code ou la doctrine — seuls des **comptages d'appels externes** existent :
- `boucle` à 5 candidates : ~10 requêtes Open-Meteo (regroupées, 14 points/requête) + 12 requêtes BRouter (`doctrine_architecture.md:216-217`).
- `sortie` à 5 candidates sur une boucle de 70 km : `1 + 2 × candidates` requêtes Open-Meteo (14 points chacune), soit **~150 appels décomptés** ; à 8 candidates, ~240 (`doctrine_architecture.md:227-233`, correction du 16/09/2026). Deux passes BRouter par candidate (génération + replacement après vent, docstring `sortie/commande.py:9-24`).
- BRouter : un timeout configurable par défaut à **120 s** par appel (`config.py:118`, `ParametresBrouter.timeout_s`) — c'est la seule borne de temps explicite du code, et c'est un plafond par requête, pas une mesure de durée totale de `sortie`.
- Aucun `time.time()`/chronométrage, aucun journal de latence observée n'apparaît dans `src/` (recherché). Un front qui a besoin d'un budget de temps pour afficher un état de chargement devra **mesurer lui-même** — rien à relire dans le code existant.

### Multi-vélo

`Config.velos` est déjà un **tuple** de `Velo` (`config.py:186`), pas un champ singulier — le modèle supporte plusieurs vélos nativement :
- chaque `Velo` porte `nom`, `usage` (route/clm seulement, voir plus haut), `masse_kg`, `cda_m2`, `crr`, les identifiants Intervals (`intervals_gear`, `intervals_gear_id`, `capteur_puissance`), et des `periodes` (`Periode.debut/fin`) pour dater quand un vélo a servi (`config.py:62-72`).
- `Config.velo(nom)` retrouve un vélo par nom, insensible à la casse (`config.py:188-191`), et lève `ErreurConfig` si absent.
- `boucle`, `simuler`, `sortie` prennent tous un `--velo` optionnel (défaut : premier vélo d'usage route) — `cli.py:232-234, 331, 437`.
- Un vélo sans nom configuré retombe sur un vélo `"Route"` par défaut si `[[velos]]` est absent (`config.py:378-379`).

Ce que le modèle **ne** fait pas : un champ « vélo actif/préféré » persistant côté utilisateur (c'est toujours un argument de commande, jamais un état) — pour une interface web, il faudrait soit le redemander à chaque écran, soit ajouter une préférence côté front/session.

## 5. Ce qui manque le plus

Classé par ce qu'il bloque dans l'interface, du plus bloquant au moins.

1. **Géocodification absente** — bloque l'assistant de configuration (adresse de départ) *et* la demande d'itinéraire manuel (adresse différente) : aucun écran ne peut se passer de lat/lon aujourd'hui, et rien ne les produit depuis une adresse tapée.
2. **Zones de puissance non éditables** — bloque l'assistant de configuration sur son point le plus spécifiquement demandé (« calage des zones de puissance ») : la table existe dans le code mais n'est reliée à aucun champ `Config`, contrairement à tous les autres réglages de séance.
3. **Aucune géométrie de tracé dans le JSON** (`boucle`/`sortie`) — bloque la carte de la page du jour dès qu'elle doit être un composant web (pas juste un iframe de la page HTML déjà générée) : coordonnées, blocs positionnés et flèches de vent n'existent qu'à l'intérieur du HTML Leaflet, jamais en JSON consommable.
4. **Upload de fichier de séance (`.FIT` structuré, `.MRC`, `.ZWO`)** — bloque l'écran d'upload demandé : aujourd'hui la seule source de séance structurée est l'API Intervals.icu, aucun parseur local n'existe pour ces trois formats (le modèle `Etape`/`Seance` cible, lui, existe déjà et n'aurait pas à changer).
5. **Pas de commande listant plusieurs jours de séances** — bloque l'écran « liste de la semaine » : le connecteur (`evenements(jour)`) et la commande CLI (`seance --jour`) sont tous deux strictement mono-jour ; c'est le trou le moins coûteux à combler (agrégation simple, pas de nouveau modèle de données).

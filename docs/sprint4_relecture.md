# Relecture du sprint 4 — lots L4.1 à L4.4

Relu le 13/09/2026 par l'agent `relecteur` (Opus) sur la branche `sprint-4`,
après fusion des quatre lots, des tests adversariaux et des corrections.
Lecture de `CLAUDE.md`, `doctrine_architecture.md` (dont §10),
`docs/plan_sprints_agents.md` section « Sprint 4 » (le cadrage produit fait
foi), `docs/sprint4_contrat.md`, `docs/questions_mainteneur.md` Q11 à Q14 et
`docs/sprint3_relecture.md` (grille et dette héritée) ; puis de tout
`src/ourouler/seance/` et `src/ourouler/sortie/`, des diffs `main...sprint-4`
de `boucle/{trace,couts,gpx}.py`, `connecteurs/{brouter,intervals}.py`,
`config.py`, `cli.py`, `README.md`, `config.example.toml`, et des tests
correspondants. Aucun fichier sous `src/` ou `tests/` n'a été modifié : ce
document est le seul livrable de la relecture.

**Verdict global : à corriger, rien de bloquant.** Les quatre lots sont au
cadrage produit — la contrainte porte bloc par bloc, aucune évaluation de
terrain n'a lieu sous une récupération, aucune durée de récupération ne bouge,
le demi-tour exige bien ses trois conditions dont la pente, seule la Z2
d'ouverture est un levier, et on note sans jamais filtrer. Les écarts au
contrat sont déclarés dans une constante nommée ou un docstring. Un défaut
sérieux (une option de configuration documentée qui n'a aucun effet, protégée
par un test qui ne pouvait pas la détecter), un trou d'une ligne dans
`.gitignore` qui met la règle absolue 1 à la merci d'un `git add -A`, une
incohérence d'affichage entre la boucle et le parcours réellement roulé, et
une mesure d'acceptation dont les chiffres écrits dans le code ne sont plus
reproductibles. Tout est corrigeable en peu de lignes.

| Lot | Verdict |
|---|---|
| Règles absolues | **à corriger** (un trou dans `.gitignore`, rien de commis) |
| Cadrage produit (les cinq règles du mainteneur) | **OK** |
| L4.1 — la séance du jour (`seance/{modele,intervals,commande}.py`) | **OK** |
| L4.2 — le terrain sous un bloc (`seance/terrain.py`, `boucle/couts.py`) | **à corriger** (la mesure, pas le code) |
| L4.3 — placement (`seance/placement.py`) | **OK** |
| L4.3 — tenue (`seance/tenue.py`) | **à corriger** |
| L4.4 — `sortie` et carte (`sortie/{commande,carte}.py`) | **à corriger** |
| Tests | **à corriger** (deux tests non probants, un mécanisme de doublure à retirer) |
| Doctrine §10 (cible hébergée) | **OK**, un point léger |

## 0. État mesuré

```
uv run ruff check .   → All checks passed!
uv run pytest -q      → 2855 passed, 32 skipped, 1 warning in 12,8 s
```

Conforme à l'annonce. Les 32 `skipped` sont les mêmes cas paramétrés du
sprint 3 (28 « puissance au-delà de la borne de bissection », 4 « vitesse
saturée »), aucun ne concerne le sprint 4 et aucun test n'est désactivé.

Mesures faites en plus de la lecture :

| Mesure | Résultat |
|---|---|
| `tests/validation/terrain_retrospectif.py` (mode nominal, Intervals) | **OUI**, code 0 — 9 blocs jugés, note réelle à 43 % du hasard (attendu ≤ 70 %) |
| le même, `--sans-reseau` | **NON**, code 1 — 13 blocs jugés, 70 % du hasard, « les poids sont faux » |
| `tests/adversarial/test_adv_placement.py` lancé seul | 24 passed, aucune dépendance à l'ordre de collecte |
| `[tenue.tenues]` de la configuration → tenue rendue | **ignorée** (voir T1) |
| D+ moteur contre `denivele_filtre` sur `tests/fixtures/brouter/boucle_fabriquee.json` | 40,0 m contre 36,1 m (−10 %) ; l'écart réel cité par le superviseur est de 460 contre 308 m (−33 %) |

## 1. Règles absolues

### Verdict : **à corriger** — un trou dans `.gitignore`, rien de commis

**Aucune donnée personnelle ni clé dans le dépôt.** Vérifié par recherche de
coordonnées françaises, de noms, d'identifiants de capteur et de motifs de
clé sur `src/`, `tests/`, `config.example.toml` et `README.md` : rien. Les
fixtures du sprint (`tests/fixtures/workouts.py`,
`tests/adversarial/fabriques4.py`) disent en tête qu'elles sont fabriquées et
donnent une FTP de test (200 W) qui n'est pas celle du mainteneur.
`config.example.toml:7` porte toujours la latitude inventée et le commentaire
qui l'explique.

**A1 — `ourouler sortie` écrit un `.html` que `.gitignore` n'ignore pas (à
corriger, une ligne).** `sortie/commande.py:203-204` écrit **toujours** le GPX
et la carte, même sans `--sortie` ni `--carte` : les noms par défaut sont
`sortie_<AAAAMMJJ>.gpx` et `sortie_<AAAAMMJJ>.html` dans le dossier courant
(`sortie/commande.py:334-341`). `.gitignore:18` ignore `*.gpx`, mais **rien
n'ignore `*.html`**. Or la carte contient la géométrie complète de la boucle,
donc le point de départ du mainteneur — sa maison — en clair dans
`donnees["depart"]`. Le mainteneur travaille dans ce dépôt : un `ourouler
sortie` lancé à la racine y laisse un fichier non ignoré, à un `git add -A` de
la règle absolue 1. Aujourd'hui l'arbre est propre et rien n'est commis, d'où
« à corriger » et non « bloquant ».
Correction proposée : ajouter à `.gitignore`, dans le bloc « Données et
secrets de l'utilisateur », `*.html` (ou `sortie_*.html` si un jour une page
versionnée apparaît).

**Le cœur ne sait pas où il tourne.** Vérifié : aucune occurrence de `open(`,
`Path(`, `read_text`, `write_text`, `os.environ`, `expanduser` ou `home()`
sous `seance/` et `sortie/` en dehors de `seance/commande.py` et
`sortie/commande.py`. Les deux modules de commande importent `physique.commande`
en import paresseux, commenté comme tel, pour la lecture de `calibration.json`.
`seance/carte.py` ne connaît aucune coordonnée : la géométrie vient du `Trace`
qu'on lui passe.

**Pas de réseau dans les tests.** Tous les clients HTTP des tests du sprint
passent par `httpx.MockTransport`, et `tests/test_invariants.py:86-99`
continue d'interdire par AST un `httpx.Client(...)` sans `MockTransport`.
`tests/validation/terrain_retrospectif.py` appelle Intervals, mais il n'est
pas collecté par pytest (nom hors `test_*`), il le dit en tête de module, et
il offre `--sans-reseau`.

**Lot vérifié sur vraies données.** `README.md` déclare `ourouler seance` et
`ourouler sortie` « vérifié sur vraies données (13/09/2026) », avec la limite
utile (« météo absente sur les jours passés »). Q11 et Q12 donnent les
tableaux avant/après sur trois séances réelles. En revanche la **conclusion de
la validation rétrospective du lot L4.2 n'est écrite nulle part** hors des
docstrings de constantes : voir D2.

## 2. Conformité au cadrage produit

### Verdict : **OK** sur les cinq règles

Vérifié en lisant le code, et non le contrat :

**(a) Aucune évaluation de terrain sous une récupération.** `evaluer_couloir`
n'est appelée qu'en trois endroits, tous sur un bloc :
`placement.py:603` (bloc droit), `671` (variante droite), `715` (variante
demi-tour). Une récupération ne traverse que `_rouler`, qui ne fait
qu'avancer. Le seul risque de contamination — les tags du tronçon précédent
attribués au bloc — est fermé par `tags_par_troncon`
(`boucle/couts.py:459-481`), dont le docstring nomme explicitement le défaut
qu'il corrige.

**(b) Aucune durée de récupération ne bouge.** Le décalage n'est ajouté qu'à
l'étape d'indice `idx_ouverture` (`placement.py:433`), et `_extremites`
(`placement.py:357-367`) ne rend comme ouverture que l'indice 0, et seulement
s'il est élastique. `_variante_droite` roule `recup.duree_s` tel quel, la
variante demi-tour ajoute `recup.duree_s` en deux moitiés
(`placement.py:695,710`). `intervals._marquer_elastiques` (`intervals.py:609`)
ne marque élastique que la première étape si elle échauffe et la dernière si
elle calme.

**(c) Le demi-tour exige ses trois conditions, dont la pente.** Dans l'ordre :
route au-delà du segment (`placement.py:699`), demi-tour faisable sur le type
de route (`701`), pente moyenne du couloir sous `PENTE_DEMI_TOUR_MAX` = 0,015
(`716`). La pente vit bien dans `placement.py`, seul module à connaître le
couple aller/retour, comme le contrat le prévoit. Réserve mineure : sur un
tracé sans altitude, `pente_moyenne` vaut 0,0 et la condition passe toujours ;
c'est cohérent avec « une ignorance n'est jamais un malus », et le motif
« altitude inconnue » l'accompagne, mais il faut le savoir.

**(d) Seule la Z2 d'ouverture sert de levier.** Un seul balayage,
`_decalages` sur la durée de l'ouverture (`placement.py:198`). `_fermer`
(`748-782`) **recalcule** la durée de la Z2 de fin à partir de la distance
restante et ne l'essaie jamais comme variable : elle absorbe, elle ne place
pas.

**(e) On note, on ne filtre pas.** `terrain.evaluer_couloir` ne lève jamais et
n'a pas de valeur de refus : un bloc plus long que le tracé reçoit
`PENALITE_BLOC_TRONQUE` = 10 et le motif qui va avec (`terrain.py:138-146`).
`placer` ne rend `None` que si la séance ne se déroule pas du tout, et range
le motif dans `trace.meta` comme `boucle.couts`. `sortie` écarte les
candidates où la séance ne tient pas, **en les comptant et en affichant leur
motif** (`sortie/commande.py:767-774`), et n'échoue que si aucune ne tient.

## 3. Lot L4.1 — La séance du jour

### Verdict : **OK**

La cascade de typage (Q12) est le point dur du lot et elle est bien faite :
marqueurs (`intervals.py:423-429`), puis mots du texte de l'étape puis de son
groupe (`430-433`), puis, seulement sur ce qui est resté « bloc » par défaut,
l'absence de consigne (`_reclasser_libres`) puis la puissance
(`_reclasser_par_puissance`), enfin le recadrage des extrémités. La provenance
de chaque type est gardée dans `meta["typage_source"]` : on peut toujours dire
pourquoi une étape est un bloc. Les deux replis sont explicites et se disent :
seuil tiré de la séance quand la FTP manque
(`meta["seuil_recuperation_replie"]`), et aucun bloc du tout quand rien ne
contraste — ce qui est le bon comportement plutôt que d'inventer un bloc.

La convention `%ftp` (contrat §1, seuil 3,0) est appliquée sur la **borne
haute** de la fourchette (`intervals.py:689-701`), ce qui est le bon choix :
une rampe `{start: 0, end: 80}` est en pourcentage alors que son début vaut 0.
L'interprétation retenue part dans `meta["convention_pourcent_ftp"]` avec le
compte des deux écritures, y compris le cas « mixte ». Rien à redire.

Le choix d'une séance quand le jour en porte deux (`intervals.py:185-222`) :
la plus longue gagne, l'ordre du calendrier départage les ex æquo, les autres
sont nommées dans `meta["seances_ignorees"]`. Le motif (« une séance n'est pas
la somme de deux prescriptions ») est juste.

**S1 — `sortie` ne dit pas qu'il a ignoré l'autre séance du jour (léger).**
`seance/commande.py:263-266` affiche « Autre(s) séance(s) vélo ce jour-là,
ignorée(s) au profit de la plus longue ». `sortie/commande.py` ne reprend rien
de cette clé dans `_entete` : il construit une boucle entière pour une séance
choisie en silence (la clé reste dans `meta`, donc visible en `--json` seul).
Correction : une ligne dans `_entete`, sur le modèle de `seance/commande.py`.

**S2 — `reps` tronqué sans le dire (léger).** `intervals.py:776-781` :
`min(int(valeur), REPS_MAX)` ramène `reps: 100000` à 500 sans rien écrire dans
`meta`, là où `reps <= 0` est compté dans `groupes_ignores`. Une séance
silencieusement amputée de 99 500 répétitions est absurde, donc sans
conséquence pratique ; mais `int(valeur)` tronque aussi `2.9` en `2`, et le
principe du lot est que toute perte se compte. Correction : incrémenter un
compteur `reps_bornees` quand la borne mord.

**S3 — un `power: {}` vide masque un `hr` valide (léger).**
`intervals.py:641-648` parcourt `("power", "hr")` et **s'arrête au premier
champ présent**, même si sa consigne est illisible : un document portant
`power: {}` et `hr: {units: "hr_zone", value: 2}` perd la consigne de FC. Le
commentaire assume le choix (« une consigne illisible reste une consigne »),
ce qui est défendable pour une unité inconnue, moins pour un dictionnaire sans
aucune borne. Correction possible : ne consommer `power` que si `_bornes` rend
quelque chose.

## 4. Lot L4.2 — Le terrain sous un bloc

### Verdict : **à corriger** — le code est bon, la mesure qui le justifie ne l'est plus

Le code est le meilleur du sprint. `tags_par_troncon` contre `tags_par_point`
est tranché et documenté au bon endroit (`boucle/couts.py:436-481`) : le
premier répond à « sur quelle route suis-je entre ce point et le suivant »
(une longueur, donc les kilomètres bâtis), le second à « suis-je passé par une
route à trafic » (un point, donc les virages à gauche). Le partage de
`virages_detectes` avec `boucle.couts` est fait par extraction et non par
copie, avec l'angle en paramètre (45° pour les coûts, 60° pour les
carrefours). Le dédoublonnage feu/virage à 40 m (`terrain.py:152-155`) est une
vraie trouvaille : sans lui, le carrefour le plus banal comptait double. La
convention d'unité — **toutes les pentes sont des tangentes** — est écrite en
commentaire de section (`terrain.py:66-72`), tenue partout, et
`_pourcent` est le seul endroit où une pente devient un pourcentage ; un
invariant adversarial la vérifie (`tests/adversarial/fabriques4.py:467-469`,
`abs(pente) <= 1.0`).

`POIDS_CARREFOUR` dit en toutes lettres qu'il **n'est pas mesuré** — une trace
GPS ne porte pas de feu — et que c'est un raisonnement produit
(`terrain.py:99-103`). C'est exactement ce que demande la règle absolue 5.

**D1 — les chiffres écrits dans les constantes ne sont plus ceux que le script
rend (à corriger).** Les docstrings de `POIDS_VIRAGE_MARQUE`, `POIDS_KM_BATI`,
`POIDS_M_DESCENTE`, `POIDS_M_MONTEE` et `POIDS_IRREGULARITE`
(`terrain.py:105-136`) citent une mesure du 13/09. Le script versionné, lancé
aujourd'hui en mode nominal, rend autre chose :

| Poste | Docstring | Mesuré ce jour (nominal) | Mesuré ce jour (`--sans-reseau`) |
|---|---|---|---|
| virages / km | 0,86 contre 0,90 | 0,74 contre 1,00 | 0,67 contre 1,15 |
| km bâtis / km | 0 contre 0,06 | 0,00 contre 0,05 | 0,00 contre 0,04 |
| descente m/km | 0,36 contre 2,52 (**14 %**) | 1,08 contre 1,89 (**57 %**) | 1,49 contre 1,63 (**91 %**) |
| montée m/km | 4,85 contre 3,64 | 4,34 contre 3,39 | 5,39 contre 2,61 |

L'écart le plus gênant est celui de la descente : le docstring en fait « le
second poste le plus discriminant », et le script lui-même imprime aujourd'hui
« POIDS_M_DESCENTE — sépare un peu » en nominal et « ne sépare rien : ce poste
ne doit presque pas peser » sans réseau. Une mesure qu'on cite doit être
reproductible par le script versionné, sinon elle redevient une opinion (règle
absolue 5). Correction : relancer, réécrire les chiffres, et dire dans chaque
docstring **de quel mode** ils viennent.

**D2 — le critère d'acceptation du lot n'est pas écrit, et les deux modes du
script ne concluent pas pareil (à corriger).** La *definition of done* dit « le
script tourne et **conclut** : note des emplacements réels contre note au
hasard, chiffres à l'appui ». Le résultat n'existe nulle part dans le dépôt —
ni `README.md`, ni `docs/`. Or il dépend du mode :

* mode nominal (blocs lus dans les intervalles Intervals) : **OUI**, 9 blocs
  jugés, 43 % de la note du hasard, code 0 ;
* `--sans-reseau` (blocs détectés par la puissance) : **NON**, 13 blocs jugés,
  70 % pour un seuil à 70 %, code 1, et le script imprime « les poids sont
  faux ».

Le mode sans réseau est le seul reproductible par quelqu'un qui n'a pas la clé
du mainteneur — c'est-à-dire par tout relecteur, humain ou agent. Correction :
consigner le résultat du mode nominal (date, chiffres, verdict) dans
`README.md` avec les autres vérifications sur vraies données, et dire dans le
docstring du script que le mode nominal fait foi et pourquoi le mode dégradé
diverge (la détection par la puissance retient 15 blocs au lieu de 11, dont
des fragments d'échauffement).

**D3 — le critère ne juge que les blocs courts et moyens (point produit,
§12).** `CATEGORIES_JUGEES` (`tests/validation/terrain_retrospectif.py:93-94`)
exclut les blocs de plus de 6 km du critère d'acceptation. Le contrat ne
prévoyait pas cette découpe. Elle écarte de fait l'une des deux sorties de
référence — les 2×20' du 25/04 — dont les deux blocs longs sont notés **214 %**
du hasard, c'est-à-dire nettement plus mal que le hasard. L'argument
(« sur 11 km le cycliste ne choisit pas son terrain, il roule là où il en est
rendu ») est plausible et honnêtement exposé par le script, mais c'est une
restriction du critère décidée après avoir vu la donnée : elle doit être
validée par le mainteneur, pas par l'agent qui écrit les poids.

**D4 — `pente_moyenne` est divisée par la longueur du couloir, pas par celle
du profil (léger).** `terrain.py:574` : `(profil[-1][1] - profil[0][1]) /
couloir.longueur_m`, alors que `profil` ne retient que les points qui portent
une altitude. Sur un couloir partiellement dépourvu d'altitude, la pente
moyenne est sous-estimée — et c'est elle qui décide du demi-tour. Correction :
diviser par `profil[-1][0] - profil[0][0]` quand cet écart est positif.

## 5. Lot L4.3 — Placement et tenue

### Verdict : **OK** pour `placement.py`, **à corriger** pour `tenue.py`

`placement.py` est dense mais lisible, et chaque décision produit y est citée
avec sa date. La mécanique du demi-tour est exactement celle du mainteneur
(figure symétrique, deux demi-récups, retour au bout du segment, segment pas
plus long que le bloc). `trace_parcourue` (`placement.py:233-280`) répond à un
vrai défaut — le GPX contenait la boucle, pas les 72,7 km réellement roulés —
et les jalons sont le bon moyen : entre deux jalons on roule dans un seul
sens, ce qui suffit à recoller le parcours. Le D+ y est recalculé et sa
provenance écrite (`DENIVELE_PARCOURS`), ce qui est la bonne discipline.

La pondération de la note par la durée des blocs est justifiée dans
`_note_ponderee` (`placement.py:541-570`), y compris la démonstration qu'elle
ne peut pas renverser le classement des décalages. Le repli quand aucun bloc
n'a de durée positive est explicite.

**Les deux poids de pénalité de séance non tenue (20 et 2) : justification
partiellement mesurée, à assumer comme telle.** L'ordre de grandeur de 20 est
ancré sur une mesure (`placement.py:101-109` : deux à quatre kilomètres
équivalents séparent le meilleur couloir du pire sur les boucles du 08/02,
donc aucune qualité de terrain ne doit racheter une séance amputée). Le
rapport de 10 entre les deux, lui, est un arbitrage assumé en toutes lettres
(« les deux défauts ne sont pas le même défaut ») et non une mesure : le
docstring ne prétend pas le contraire, ce qui est conforme à la règle 5. Ce
qui n'est pas examiné, c'est la conséquence chiffrée de l'asymétrie — voir
§12, point produit 2.

**T1 — `[tenue.tenues]` de la configuration n'a aucun effet (à corriger,
gravité 1).** `seance/tenue.py:271-276` lit `getattr(p, "tenues", None)` et ne
s'en sert **que si c'est un `dict`**. Or `ParametresTenue.tenues`
(`config.py:166`) est un `tuple[tuple[str, tuple[str, ...]], ...]`, et
l'accesseur prévu, `ParametresTenue.tenue_de` (`config.py:168`), n'est appelé
**nulle part** dans `src/`. Vérifié :

```
ParametresTenue(tenues=(("froid", ("cuissard magique", "veste test")),))
  .tenue_de("froid")            → ('cuissard magique', 'veste test')
seance.tenue._tenues(p)["froid"] → ('maillot manches longues', 'collant long', …)
```

Le docstring de `_tenues` dit encore « `ParametresTenue` n'expose pas encore
de champ `tenues` » : il décrit l'état d'avant le commit 6ffe838, qui a ajouté
le champ, la validation TOML et onze lignes de `config.example.toml`
promettant au mainteneur qu'il peut remplacer une tenue par catégorie. Il ne
le peut pas. Correction : remplacer la lecture par
`for categorie, pieces in getattr(p, "tenues", ()) : tableau[categorie] = pieces`
(ou un appel à `tenue_de` par catégorie), et réécrire le docstring.
Le test censé couvrir ce chemin ne pouvait pas le détecter : voir §7, X1.

**T2 — `PUISSANCE_SANS_CIBLE_W = 150.0` est une donnée de cycliste dans le
cœur (léger, mais contraire à l'esprit de la doctrine).**
`placement.py:87-90` : une étape sans fourchette de puissance est roulée à
150 W. Ce n'est pas une constante du modèle, c'est une puissance d'endurance —
et le sprint vient précisément de décider (Q11) que cette valeur-là est un
paramètre de profil, mesuré à 0,60 × FTP, soit 155 W pour le mainteneur. La
coïncidence est parlante. Le repli est annoncé dans les avertissements, donc
rien n'est caché, mais la doctrine §10.1 dit que « l'unité de tout est le
profil » : `placer` reçoit déjà `Parametres`, il pourrait recevoir la
puissance de repli. Correction : passer `puissance_sans_cible_w` en argument
nommé, défaut 150 W, alimenté par `config.seance.puissance_endurance_pct ×
config.cycliste.ftp_w` depuis `sortie/commande.py`.

**T3 — le choix demi-tour / tout droit est pris avant que la pénalité de
séance puisse peser (dette, à noter au plan, liée à Q14).**
`placement.py:641` : `min(candidates, key=lambda c: c[0].note.note)` tranche
la paire (récup, bloc) au seul vu de la note de couloir, bloc par bloc, alors
que `_penalite_seance` n'est calculée qu'à la fin du déroulé
(`placement.py:495`). La pénalité peut donc départager deux **décalages**,
jamais deux variantes d'une même paire : si le demi-tour gagne localement de
0,1 km équivalent, il est retenu même s'il fera payer 19 de pénalité en bout
de course, et tous les décalages en héritent. C'est très exactement la cause
(1) décrite dans Q14 (« un demi-tour ajoute de la distance que le
dimensionnement ignore ») et la piste (a) qu'elle propose. Rien à corriger au
sprint 4 — Q14 est ouverte et déclarée — mais la limite mérite d'être écrite
dans le docstring de `_recup_puis_bloc`, faute de quoi le lecteur croit que la
pénalité arbitre tout.

## 6. Lot L4.4 — `sortie` et la carte

### Verdict : **à corriger**

L'enchaînement est bon et l'ordre des appels est économe : le placement se
fait avant la météo, donc une candidate écartée ne coûte pas d'appel
Open-Meteo. La validation des options se fait avant le premier appel réseau, y
compris le test d'écriture des deux fichiers de sortie. La panne météo fait
disparaître des colonnes au lieu de perdre la sortie, avec un message sur la
sortie d'erreur — c'est la convention de `boucle`, tenue.

**C1 — le tableau décrit la boucle, le GPX décrit le parcours, et rien ne le
dit (à corriger, gravité 2).** Dans la même ligne de tableau,
`sortie/commande.py:806` affiche `trace.distance_m` (la **boucle**, 38,5 km le
22/04) et `808` affiche `placement.duree_totale_s` (la **séance**, 2 h 44).
Le lecteur y lit 14 km/h. La distance réellement roulée (72,7 km) n'apparaît
que dans le paragraphe « Séance placée » et dans les notes de la carte.
Correction : ajouter une colonne « parcours » (ou afficher
`38,5 → 72,7 km` quand il y a des demi-tours), et faire porter la colonne
« temps » la même chose que la distance.

**C2 — deux D+ pour la même sortie, sans qu'on dise qu'ils divergent (à
corriger, gravité 2).** Le tableau et le sous-titre de la carte affichent le
« filtered ascend » du moteur pour la boucle (460 m dans le cas relevé) ;
le `<desc>` du GPX affiche le D+ recalculé par `denivele_filtre` sur le
parcours placé (308 m), soit **−33 %**, alors qu'un aller-retour devrait
plutôt *augmenter* le D+. L'écart est méthodologique — le seuil d'hystérésis
de 2 m de `boucle/trace.py:124-152` efface les vallonnements de moins de 2 m,
que BRouter, lui, compte autrement — et il est mesurable même sur la fixture
synthétique (40,0 contre 36,1 m). La provenance est bien écrite dans chaque
artefact (`(moteur)`, `(parcours placé)`), ce qui était la correction du
sprint 2 ; mais la règle absolue 5 demande qu'un désaccord entre deux mesures
s'**affiche comme un désaccord**, et ici il faut ouvrir le GPX pour le voir.
Correction minimale : une ligne sous le tableau, du type « D+ : 460 m annoncés
par le moteur pour la boucle, 308 m recalculés sur le parcours placé — deux
méthodes, pas deux parcours ».

**C3 — `json.dumps` injecté dans un `<script>` sans neutraliser `<` (léger,
robustesse).** `sortie/carte.py:446` puis `500` : `const D = {charge};`. Rien
aujourd'hui ne peut y faire entrer `</script>` — tout le texte libre
(consigne, motifs) passe par `html.escape` avant d'entrer dans la charge —
mais la garantie tient à ce chemin-là et non à la sérialisation. Correction
d'une ligne : `charge.replace("<", "\\u003c")`.

**C4 — l'attribution OpenStreetMap n'est pas un lien (léger, licence).**
`sortie/carte.py:50` : `"© OpenStreetMap"`. La licence ODbL demande une
attribution qui pointe vers `https://www.openstreetmap.org/copyright`.
Correction : `'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'`.
Le reste est propre : Leaflet épinglé en version exacte
(`carte.py:44-46`) sur `cdnjs.cloudflare.com`, aucune autre ressource
externe, aucune donnée envoyée nulle part, le SVG du profil borné à 800 points
et refusant de dessiner une ligne plate quand l'altitude manque
(`carte.py:339-340`).

**C5 — `--depart` (heure) et le `--depuis` (lieu) prévu au plan vont se
télescoper (léger).** `cli.py` ajoute `--depart HH:MM` à `sortie` ; le plan du
sprint 4 annonce « option `--depuis` pour un départ autre que la maison »,
non livrée. Deux options dont les noms diffèrent d'une lettre pour deux sens
sans rapport. À arbitrer avant que `--depuis` existe (renommer `--depart` en
`--heure` reste possible tant que personne d'autre n'utilise la commande).

## 7. Qualité des tests

### Verdict : **à corriger** — deux tests non probants, un mécanisme à retirer

Le volume est là (2 855 tests) et les tests adversariaux du sprint sont
sérieux : `fabriques4.verifier_note` vérifie les invariants de `NoteBloc`
« quel que soit le barème », dont l'unité de pente ; `_verifier` du fichier
placement vérifie que chaque bloc de la prescription est placé, que la note se
décompose, et que les emplacements sont bien des blocs.

**Les deux tests adversariaux modifiés pendant le sprint le sont à bon
droit.** `tests/adversarial/test_adv_placement.py` a été touché deux fois :

* 058aeab (pondération par la durée) : l'invariant `note_totale >= somme des
  notes` devient « rester dans l'intervalle des notes, et rester strictement
  positive dès qu'un bloc porte une pénalité ». Le test **avait raison contre
  l'ancien code**, il aurait eu tort contre le nouveau : une moyenne n'est pas
  une somme. La modification est justifiée et le commit l'explique. Elle a un
  coût qu'il faut connaître : l'invariant nouveau est intrinsèquement plus
  faible — une moyenne pondérée peut diluer un très mauvais couloir parmi
  sept bons sans qu'aucune assertion ne s'en émeuve. C'est la conséquence de
  la décision produit, pas un affaiblissement clandestin.
* 2c71210 (pénalité de séance non tenue) : les assertions passent de
  `note_totale` à `note_terrain`, et **une assertion est ajoutée** —
  l'identité `note_totale == note_terrain + penalite_seance`. Modification
  justifiée, et le test en sort plus fort.

Aucun autre test adversarial du sprint n'a été retouché après sa création
(un seul commit chacun pour `test_adv_terrain.py`, `test_adv_seance.py`,
`test_adv_tenue.py`, `test_adv_invariants.py`, `fabriques4.py`).

**La fragilité signalée n'en est pas une.** `uv run pytest
tests/adversarial/test_adv_placement.py` seul : 24 passed. Aucun état global
mutable dans `fabriques4.py`, aucune fixture de portée session ou module.

**X1 — `tests/test_seance_tenue.py:174-185` ne pouvait pas détecter T1 (à
corriger).** Le test « les tenues de la configuration remplacent le défaut »
**n'utilise pas `ParametresTenue`** : il définit à la volée une sous-classe
`TenueConfiguree` dont le champ `tenues` est un `dict`, c'est-à-dire
exactement la forme que le code de production attend et que la vraie
configuration ne produit jamais. Le test vert prouve que `_tenues` sait lire
un dictionnaire ; il ne prouve rien de la chaîne TOML → `Config` → tenue
rendue, qui est cassée. Correction : réécrire le test avec
`ParametresTenue(tenues=(("frais", ("maillot de laine", "casquette")),))`, ce
qui le fera échouer jusqu'à ce que T1 soit corrigé, puis ajouter un test de
bout en bout depuis un TOML.

**X2 — le mécanisme de doublures de `tests/test_seance_placement.py:75-103`
doit partir (à corriger).** Le fichier installe, **à l'import**, de faux
modules `ourouler.seance.modele` et `ourouler.seance.terrain` dans
`sys.modules` si les vrais ne s'importent pas — échafaudage utile quand les
lots s'écrivaient en parallèle, inutile depuis la fusion (`DOUBLES` est vide
aujourd'hui). Il est dangereux tel quel : le `except ModuleNotFoundError`
n'attrape pas seulement « le module n'existe pas encore », il attrape aussi
« le module existe mais un de ses imports a disparu ». Le jour où
`seance/terrain.py` importera un symbole renommé de `boucle.couts`, ce fichier
installera silencieusement un `evaluer_couloir` qui rend toujours 0 et une
`demi_tour_faisable` qui dit toujours oui, et 24 tests de placement passeront
au vert contre une production cassée. Correction : supprimer
`_double`/`_installer_les_doubles` et importer normalement.

**X3 — `fabriques4.module(..., motif=...)` saute au lieu d'échouer (léger, même
famille).** `tests/adversarial/fabriques4.py:49-56` : `except ImportError:
continue`, puis `pytest.skip`. Aucun test n'est sauté aujourd'hui (les 32
`skipped` sont tous du sprint 3), mais un `ImportError` interne au paquet
`seance` transformerait une suite adversariale entière en « skipped » vert.
Correction : ne tolérer le saut que si le paquet lui-même est absent
(`ModuleNotFoundError` dont le `name` est `ourouler.seance`), et laisser
remonter le reste.

Sur les cinq règles produit, les tests sont réellement probants pour (a)
(`test_aucune_recuperation_n_est_evaluee`), (c)
(`test_demi_tour_refuse_sans_route_au_dela`, `…_sur_une_route_a_trafic`,
`…_en_cote` — les trois conditions, une par test), (d)
(`test_la_z2_de_fin_absorbe_le_reste`, `test_seance_sans_z2_elastiques`) et
(e) (`test_seance_trop_longue_pour_le_trace`, qui vérifie le motif dans
`meta` et non une exception). Pour (b), l'invariant « aucune durée de récup ne
bouge » n'a pas de test dédié : il est vérifié indirectement par les durées
totales. Un test explicite — dérouler une séance à récups inégales et vérifier
que la somme des durées non élastiques est conservée quel que soit le
décalage — coûterait dix lignes et fermerait la règle la plus facile à casser
par inadvertance.

## 8. Doctrine §10 — cible hébergée

### Verdict : **OK**, un point léger

Rien du sprint n'entrave l'hébergé. Les deux commandes rendent du JSON complet
(`sortie/commande.py:902-1007` expose jusqu'aux motifs et aux pentes de chaque
emplacement — c'est déjà une réponse d'API). Le cœur ne lit ni fichier ni
environnement. `carte.construire` rend une **chaîne**, jamais un fichier :
elle sera servie telle quelle par une future API. Les clés ne fuient nulle
part : aucun champ d'`[intervals]` dans les sorties texte ou JSON.

Deux réserves légères, sans action immédiate :

* `placer` écrit dans `trace.meta` (`placement.py:338`), donc mute son entrée.
  En CLI c'est sans conséquence ; en hébergé, si un `Trace` mis en cache était
  partagé entre deux requêtes, le motif d'échec de l'une deviendrait visible
  de l'autre. À garder en tête le jour où un cache de tracés apparaîtra.
* `PUISSANCE_SANS_CIBLE_W` (T2) est une valeur de profil dans le cœur : c'est
  exactement le genre de constante que §10.1 demande de transformer en donnée.

## 9. À corriger avant de montrer au mainteneur

Par gravité décroissante.

1. **T1 — `[tenue.tenues]` n'a aucun effet** (`src/ourouler/seance/tenue.py:271-276`).
   Une option documentée dans `config.example.toml` et validée par `config.py`
   ne change rien à la tenue rendue. Lire le tuple de couples de
   `ParametresTenue` (ou appeler `tenue_de`), et réécrire le docstring qui
   décrit un état dépassé. Avec X1 : le test qui devait couvrir ce chemin
   utilise une sous-classe maison et ne peut pas échouer.
2. **A1 — `.gitignore` n'ignore pas les cartes HTML** (`.gitignore:18`).
   `ourouler sortie` écrit `sortie_<AAAAMMJJ>.html` dans le dossier courant,
   avec le point de départ du mainteneur dedans. Une ligne : `*.html`.
3. **X2 — retirer les doublures de modules de
   `tests/test_seance_placement.py:75-103`.** Un `ImportError` interne ferait
   passer 24 tests au vert contre une production cassée.
4. **D1 — réaligner les chiffres des poids de `seance/terrain.py:105-136` sur
   ce que le script rend aujourd'hui**, et dire de quel mode ils viennent. Le
   poste « descente » est annoncé à 14 % du hasard, mesuré à 57 %.
5. **D2 — écrire quelque part la conclusion de la validation rétrospective**
   (README, section « vérifié »), et dire lequel des deux modes fait foi : le
   mode `--sans-reseau`, seul reproductible sans la clé du mainteneur, conclut
   aujourd'hui « les poids sont faux » et sort en 1.
6. **C1 — la ligne du tableau de `sortie` mélange la distance de la boucle et
   la durée de la séance** (`sortie/commande.py:806-808`) : 38,5 km en 2 h 44.
7. **C2 — les deux D+ (moteur 460 m, parcours placé 308 m) ne sont jamais
   montrés côte à côte** ; une ligne sous le tableau suffit.
8. **X1 — réécrire `tests/test_seance_tenue.py:174-185` avec le vrai
   `ParametresTenue`.**
9. **X3 — `fabriques4.module` ne doit sauter que si le paquet est absent**
   (`tests/adversarial/fabriques4.py:49-56`).
10. **D4 — `pente_moyenne` divisée par la longueur du couloir plutôt que par
    celle du profil** (`seance/terrain.py:574`) : c'est cette pente qui décide
    du demi-tour.
11. **C3 et C4 — neutraliser `<` dans le JSON injecté dans le `<script>`
    (`sortie/carte.py:446`) et faire de l'attribution OSM un lien
    (`sortie/carte.py:50`).**
12. **S1, S2, S3, C5 — quatre points légers** : `sortie` ne dit pas qu'une
    autre séance du jour a été ignorée ; `reps` tronqué sans compteur ;
    `power: {}` vide qui masque un `hr` valide ; `--depart` qui va se
    télescoper avec le `--depuis` prévu.
13. **Ajouter le test manquant de la règle (b)** : aucune durée de
    récupération ne bouge, quel que soit le décalage.

## 10. Dette assumée, à noter au plan

* **Q13 — `sortie` n'affiche que les blocs.** Déclarée, motivée, et non
  traitée par L4.4 alors que c'est le lot qui touche `sortie/`. Le choix se
  défend (l'extension demande que `placer` rende la position de **chaque**
  étape, ce qui est une extension de `Placement`, pas un affichage), mais la
  dette est donc reportée d'un lot après avoir été identifiée pendant.
* **Q14 — le retour au calme ne peut pas absorber la variabilité de la
  boucle.** Ouverte, quatre pistes, aucune tranchée. T3 en donne le mécanisme
  précis dans le code : la pénalité arbitre les décalages, pas les demi-tours.
* **`POIDS_CARREFOUR` n'est pas mesurable** avec les données disponibles (une
  trace GPS ne porte pas de feu). Assumé et écrit. Il le restera tant qu'on ne
  rejouera pas les sorties dans BRouter en gardant les tags de **nœud** — la
  base `routes_connues.sqlite` ne garde aujourd'hui que les tags de chemin.
* **Le demi-tour est autorisé quand l'altitude est inconnue** (pente réputée
  nulle). Cohérent avec « une ignorance n'est pas un malus », mais c'est une
  des trois conditions du mainteneur qui devient inopérante sur un tracé sans
  altitude.
* **`_liaisons` de la carte déduit les portions non notées de l'écart entre
  deux couloirs** (`sortie/carte.py:204-244`) plutôt que de les recevoir du
  placement. C'est la même racine que Q13 : le jour où `Placement` portera
  toutes les étapes, ce code se simplifiera au lieu de se compliquer.

## 11. Coût des appels externes de `ourouler sortie`

Pour `--candidates 5` sans `--direction` (le cas nominal) :

| Service | Appels | Détail |
|---|---|---|
| Intervals.icu | **1** | `evenements(jour)`, une fois |
| BRouter | **≤ 20** | 5 azimuts × `appels_pour(1)` = 1 essai + 3 ajustements |
| Open-Meteo | **≤ 10** | 2 par candidate **retenue** (modèle + second avis), tous les points en un seul appel HTTP |

Soit 31 appels au pire, du même ordre que `ourouler boucle` (~12 + 10) et sans
commune mesure avec les quotas décrits en doctrine §10.1 (≈ 10 000 Open-Meteo
par jour et par adresse IP). Deux remarques pour l'hébergé :

* l'ordre des étapes est déjà le bon pour le quota — le placement écarte les
  candidates avant que la météo soit demandée, donc une candidate où la séance
  ne tient pas ne coûte rien chez Open-Meteo ;
* en hébergé, 10 appels Open-Meteo par consultation donnent ~1 000
  consultations par jour depuis une seule adresse, soit la même conclusion
  qu'au sprint 2 : le cache mutualisé par maille et par heure suffit, et il
  reste à écrire au premier sprint de l'hébergé.

Le coût en calcul, lui, est local : `placer` déroule la séance pour chaque
décalage (jusqu'à quelques dizaines) et chaque candidate, et `evaluer_couloir`
reconstruit `tags_par_troncon` à chaque appel. Rien de gênant aux tailles
actuelles (la suite entière tourne en 12,8 s), mais c'est le premier endroit
qui deviendra sensible si une API doit répondre en moins d'une seconde.

## 12. Points produit, pour le mainteneur

1. **Le critère d'acceptation du terrain a été restreint aux blocs de moins de
   6 km** (D3). Sur les deux blocs longs des 2×20' du 25/04, les emplacements
   réellement choisis sont notés **plus mal que 95 % des tirages au hasard**,
   et le script conclut que ce n'est pas un échec des poids mais « la mesure de
   ce que l'outil apporte » (il existait un couloir à 1,81 là où les 20' ont
   été roulés à 6,45). C'est peut-être vrai, et c'est exactement la question à
   trancher : est-ce que l'outil doit chercher un couloir pour un 20', ou
   est-ce que sur cette durée-là le terrain se subit ?
2. **L'asymétrie 20 / 2 rend la séance rallongée très bon marché.** Un retour
   au calme de 38 min au lieu de 20 (le cas réel du 08/02, +90 %) coûte
   2,0 × 0,70 = **1,4 km équivalent**. Traverser un bourg sur 1 km pendant un
   bloc coûte 3,0 — mais la note de terrain est une **moyenne pondérée** sur
   les blocs : sur une séance à six blocs de durée voisine, le même bourg ne
   pèse plus que 0,5. Autrement dit, l'outil préfère aujourd'hui vous faire
   traverser un village plutôt que rentrer 18 minutes en retard. C'est
   peut-être le bon arbitrage ; il n'a pas été posé comme tel.
3. **Le GPX et le tableau ne parlent pas du même parcours** (C1, C2) : le
   tableau décrit la boucle proposée par le moteur, le fichier envoyé au
   compteur décrit ce que vous allez rouler, demi-tours compris. Les deux sont
   justes, l'écart est de +90 % en distance et de −33 % en D+, et rien à
   l'écran ne prévient.
4. **Quand deux séances vélo sont planifiées le même jour, `sortie` en choisit
   une en silence** (S1) : la plus longue. `ourouler seance` le dit, `ourouler
   sortie` non.
5. **La tenue configurée dans le TOML est ignorée** (T1) : tant que ce n'est
   pas corrigé, `[tenue.tenues]` ne sert à rien et le conseil vient toujours
   du jeu par défaut du code.

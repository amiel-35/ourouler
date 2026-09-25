# Relecture du sprint 2 — lots L2.1 à L2.7

Relu le 13/09/2026 par l'agent `relecteur` (Opus) sur la branche `sprint-2`,
après fusion des lots L2.1 à L2.7, des tests adversariaux et des corrections.
Lecture de `CLAUDE.md`, `doctrine_architecture.md` (dont §10),
`docs/journal/sprints/sprint2_contrat.md`, `docs/journal/sprints/sprint1_relecture.md` (grille et dette
héritée), de tout `src/ourouler/boucle/`, de
`src/ourouler/connecteurs/brouter.py`, des diffs de
`connecteurs/intervals.py`, `activites/inventaire.py`, `activites/cache.py`,
`config.py`, `cli.py`, et des tests correspondants. Aucun fichier sous `src/`
ou `tests/` n'a été modifié : ce document est le seul livrable de la
relecture.

**Verdict global : à corriger, rien de bloquant techniquement.** Les sept
lots sont au contrat, le mot de passe BRouter et la clé Intervals ne fuient
sur aucun chemin mesuré, et les tests sont de bonne qualité. Huit défauts de
correction sont mesurés ci-dessous, tous corrigeables en quelques lignes, et
onze points légers ou de documentation. Un seul point reste **bloquant pour
la publication du dépôt** (Q6), et il est hérité du sprint 1 : les données du
mainteneur dans `docs/` — que ce sprint a **augmentées** — et, désormais,
dans l'historique git.

| Lot | Verdict |
|---|---|
| Règles absolues | **à corriger** (bloquant pour la publication seulement) |
| L2.1 — connecteur BRouter | **à corriger** |
| L2.2 — GPX | **à corriger** |
| L2.3 — candidates | **à corriger** |
| L2.4 — coûts | **à corriger** |
| L2.5 — météo le long du tracé | **OK** |
| L2.6 — CLI `ourouler boucle` | **à corriger** |
| L2.7 — rattachement et métadonnées | **à corriger** |
| Doctrine §10 (cible hébergée) | **à corriger** sur un point explicite |

## 0. État mesuré

```
uv run ruff check .   → All checks passed!
uv run pytest -q      → 1286 passed, 1 warning in 1,95 s
```

Conforme à l'attendu. Mesures faites en plus de la lecture (scripts jetables
hors dépôt, tous reproductibles) :

| Mesure | Résultat |
|---|---|
| `_degres("570")` (coordonnée de message à 0,00057°) | rend **570,0 degrés** (§2, B1) |
| fixture BRouter : `track-length` contre cumul haversine | 7 543,0 m contre 7 544,1 m, soit **−0,01 %** — négligeable (§1) |
| D+ moteur contre D+ relu après aller-retour GPX (fixture) | **40 m contre 36,05 m** ; le dev a mesuré 251 contre 331 sur une vraie boucle (§3, C1) |
| `couts._ecart_cap(0°, 180°)` | **−180,0**, donc un demi-tour est compté **à gauche** — le docstring dit « à droite » (§5, E1) |
| `generer` face à un moteur qui rend toujours 100 m, cible 60 km | rayons demandés : 12 000 → **7 200 000** → **4 320 000 000** m (§4, D1) |
| deux activités Intervals partageant le même fichier d'origine | **une seule ligne en cache**, `id_externe` du dernier, `contient()` faux pour le premier (§8, H1) |
| `est_sport_velo("Triathlon")` | faux → écarté de l'inventaire ; `est_sport_velo(None)` → vrai (§8, H3) |
| appels Open-Meteo d'un `ourouler boucle` à 5 candidates | **10** (2 par candidate), sans cache mutualisé (§6 et §9) |
| `repr(Config)`, `str(Config)`, `ourouler config --json`, `ourouler boucle --json` | mot de passe BRouter et clé Intervals **absents** partout (§1) |

## 1. Règles absolues

### Verdict : **à corriger** — et **bloquant pour la publication** sur un point hérité

**Secrets : rien à redire.** Le mot de passe BRouter ne vit que dans l'objet
`httpx.BasicAuth` (`connecteurs/brouter.py:75-77`), n'est conservé dans aucun
attribut, `ClientBrouter.__repr__` est surchargé
(`connecteurs/brouter.py:79-80`), `ParametresBrouter.__repr__` masque
(`config.py:119-124`), les messages d'erreur ne citent que l'URL nue et le
code HTTP (`connecteurs/brouter.py:156-176`), et `cli.py:50-52` masque
explicitement les deux secrets dans `ourouler config --json` — parce que
`dataclasses.asdict` ignore les `__repr__` masquants, ce que le testeur
adversarial avait attrapé (`3436d1c`). `ourouler boucle --json`
(`boucle/commande.py:431-456`) ne publie aucun champ de `[brouter]`.
Vérifié à la main sur les quatre sorties, plus trois tests d'invariant
(`tests/adversarial/test_adv_invariants.py:321-347`). Rien à corriger.

**Cœur sans lecture de configuration : respecté.** `boucle/` ne lit ni
chemin, ni variable d'environnement, ni fichier de configuration ; la
vitesse, le sens, la tolérance et le nombre de candidates viennent tous de
`Config` (`boucle/commande.py:107-129`). Les deux clients sont injectables
(`boucle/commande.py:94-99`).

**Pas de réseau dans les tests : respecté, et mieux qu'au sprint 1.** Le
testeur adversarial a fait ce que la relecture du sprint 1 demandait (E2) :
une fixture *autouse* qui remplace `socket.socket`, `socket.create_connection`
et `socket.getaddrinfo` (`tests/adversarial/conftest.py:52-54`). Elle ne
couvre que `tests/adversarial/` ; `tests/conftest.py` n'en a pas et le reste
de la suite dépend encore de l'analyse statique de
`tests/test_invariants.py:93-101`. Dette inchangée, avec désormais le modèle
à recopier à côté.

**A1 — données du mainteneur dans `docs/`, augmentées par ce sprint, et
maintenant dans l'historique git (bloquant pour la publication).** La règle
absolue 1 dit « aucune donnée personnelle **dans le dépôt** », sans réserve
sur le dossier. `docs/journal/sprints/sprint2_contrat.md:17`, `:178-182` ajoute les deux
numéros de capteur réels et les quatre identifiants d'équipement Intervals du
mainteneur ; `docs/journal/questions/questions_mainteneur.md:29-34` ajoute les marques. La
relecture du sprint 1 avait déjà classé ce sujet « bloquant pour la
publication » (point 2 de sa liste) : le sprint 2 l'a aggravé, pas réduit.

Plus grave, et nouveau : le commit `24d2f09` a purgé le nom du capteur réel
de `src/` et de `tests/`, mais **`git log -p` le rend toujours** — il est
introduit par `2788ba7` dans `config.py`, `tests/test_config.py` et
`config.example.toml`. Une purge dans HEAD n'est pas une purge dans
l'historique, et c'est l'historique qu'un dépôt public publie.
*Correction : décider avec le mainteneur avant l'ouverture du dépôt (Q6) —
soit réécrire l'historique de `sprint-2` avant la PR (les commits concernés
ne sont pas encore sur `main`), soit sortir ces valeurs de `docs/` vers un
fichier ignoré par git et assumer l'historique. C'est une décision, pas une
correction d'agent.*

**A2 — le détecteur de données personnelles ne scanne ni
`config.example.toml` ni `README.md` (à corriger, léger).**
`tests/adversarial/test_adv_invariants.py:383-391` limite `_fichiers_a_scanner`
à `src/` et `tests/`, en l'écrivant. Or c'est précisément
`config.example.toml` qui portait « SRAM 1052 » avant `24d2f09`, et c'est le
fichier que l'utilisateur copie. Le détecteur lui-même est excellent (jetons
écrits à l'envers, test positif du détecteur en
`tests/adversarial/test_adv_invariants.py:394-402`) ; il regarde juste à côté
du seul endroit où la faute s'est produite. *Correction : ajouter
`config.example.toml` et `README.md` à `_fichiers_a_scanner`.*

## 2. Lot L2.1 — Connecteur BRouter

### Verdict : **à corriger**

Le lot est le plus soigné du sprint. Les trois pièges annoncés au contrat
sont traités et documentés par la mesure : `engineMode` entier
(`connecteurs/brouter.py:34`), coordonnées des messages en microdegrés
entiers passés en chaînes (`:370-378`), et surtout le **rattachement en
avançant** (`:276-314`, curseur strictement croissant, `_point_suivant`
cherche à partir de `curseur + 1`) — le dernier message d'une boucle cite le
point de départ, qui est aussi l'arrivée, et une recherche par valeur seule
l'aurait renvoyé à l'indice 0 en inversant le tronçon. C'est le bug le plus
subtil du lot, il est vu, expliqué et testé
(`tests/adversarial/test_adv_brouter.py:218-231`). Le repli sans ligne
d'en-tête (`:317-332`), le comptage des messages illisibles dans
`meta["messages_ignores"]` plutôt que leur disparition silencieuse
(`:221-236`), et l'indice « profil inconnu ? » sur un 500 sans corps
(`:186-190`) sont autant de bons réflexes.

**Distance `track-length` contre cumul : non, ce n'est pas un problème.**
`connecteurs/brouter.py:241` retient `track-length` et range le cumul
haversine dans `meta["distance_cumulee_m"]` (`:230`). Mesuré sur la fixture :
7 543,0 contre 7 544,1 m, soit 0,01 %. Le choix est le bon (le moteur mesure
sur le graphe, pas sur une corde), les deux chiffres sont conservés, l'écart
est négligeable. Rien à faire.

**B1 — une coordonnée de message à moins de 0,001° d'un axe
est lue comme des degrés (à corriger).** `connecteurs/brouter.py:56` pose
`SEUIL_MICRODEGRES = 1000.0` et `:377-378` fait `valeur / 1e6 if abs(valeur) >
SEUIL_MICRODEGRES else valeur`. Mesuré : `_degres("570")` rend **570,0
degrés**. La bande d'ambiguïté est |coordonnée| ≤ 0,001°, soit ±111 m de part
et d'autre de l'équateur **et du méridien de Greenwich**. Conséquence : le
message part sur `_point_suivant` (`:354-367`), dont le repli par distance
choisit alors le point le plus proche d'un point à 570° de latitude —
c'est-à-dire n'importe lequel, en silence. Les tronçons, leurs tags et donc
`km_trafic` deviennent faux sans le moindre message.

Ce n'est pas une hypothèse d'école pour ce dépôt : **toutes** les fixtures
vivent autour de (0, 0) par l'invariant d'anonymisation, et le contrat du
sprint §8 demandait explicitement de tester « le cap au passage du méridien
0 ». L'anneau de `tests/fixtures/generer_brouter.py:59-70` passe à 570
microdegrés de l'axe au point n° 7 — qui n'est simplement pas une fin de
tronçon (`FINS_DE_TRONCON = (5, 10, 15, 20, 25, 29)`). La fixture frôle le
bug sans le toucher, et les tests paramétrés microdegrés/degrés
(`tests/adversarial/test_adv_brouter.py:180-196`) ne visitent pas la bande.
Sans effet pour le mainteneur (sa ville est à <coordonnées>), faux partout
ailleurs et invisible.
*Correction : ne pas deviner l'unité valeur par valeur. Décider une fois pour
toute la réponse — par exemple, si la valeur brute est une chaîne d'entier
sans point décimal, c'est des microdegrés ; sinon des degrés — ou comparer le
maximum des |coordonnées| de la table de messages à celui de la géométrie et
appliquer le même facteur à toutes les lignes. Et ajouter au générateur de
fixture un tronçon dont la fin est à moins de 0,001° d'un axe.*

**B2 — un message sans point où s'accrocher disparaît sans être compté
(à corriger, léger).** `connecteurs/brouter.py:290-291` sort de la boucle par
`break` quand le curseur atteint le dernier point, sans rien ajouter à
`ignores`. Si le serveur envoie plus de messages que la géométrie ne porte de
points, `meta["messages_ignores"]` annonce 0 alors que des tronçons ont été
perdus — exactement le contraire de l'intention affichée en `:233-236`.
*Correction : compter les lignes restantes dans `ignores` avant le `break`.*

## 3. Lot L2.2 — GPX : écriture et import

### Verdict : **à corriger**

L'aller-retour est exact (mesuré : écart de coordonnées nul, distance
conservée au mètre — 7 544,1 m relus contre 7 544,1 m calculés), la
séparation d'avec `activites.lecture.lire_gpx` est expliquée et justifiée
(`boucle/gpx.py:6-10`), `<rte>` en repli et fichier vide en `ErreurLecture`
sont traités.

**C1 — la colonne « D+ » ne dit pas d'où elle vient, et change de valeur
selon le chemin (à corriger).** `boucle/gpx.py:126-146` recalcule un D+ avec
un seuil de 2 m ; `connecteurs/brouter.py:242` retient le « filtered ascend »
du moteur. `boucle/commande.py:399` affiche `trace.denivele_m` sous le même
en-tête « D+ » dans les deux cas, sans jamais dire lequel. Trois mesures, trois
écarts, et même deux signes différents :

| Tracé | D+ moteur | D+ relu | Écart |
|---|---|---|---|
| fixture du dépôt (30 points) | 40 m | 36,05 m | −10 % |
| vraie boucle du dev (1 800 points, commit `92a42fa`) | 251 m | 331 m | +32 % |
| vraie boucle citée par le superviseur | 463 m | 362 m | −22 % |

Pire : `ecrire_gpx` inscrit la valeur **du moteur** dans le `<desc>`
(`boucle/gpx.py:39`, `:50-57` — vérifié : `<desc>7,5 km · D+ 40 m · …</desc>`),
si bien que `ourouler boucle --gpx boucle.gpx` sur le fichier que `ourouler
boucle` vient d'écrire affiche un D+ différent de celui écrit dedans. Un
utilisateur qui compare les deux exécutions n'a aucun moyen de comprendre
pourquoi. La règle absolue 5 demande qu'un désaccord s'affiche comme un
désaccord.
*Correction : ranger la provenance dans `meta["denivele_source"]` (`"moteur"`
ou `"gpx"`) au moment de la construction, et l'afficher — « D+ 463 m
(moteur) » / « D+ 362 m (relu) » — dans le tableau texte comme dans le JSON.
Trois lignes, et l'écart cesse d'être un mystère.*

**C2 — `_denivele` est un seuil, pas un lissage, et le docstring le laisse
croire (à corriger, léger).** `boucle/gpx.py:129-132` parle de « bruit d'un
altimètre barométrique » qui « double le dénivelé d'un parcours plat », mais
l'algorithme ne fait que refuser les montées de moins de 2 m depuis la
dernière référence : sur un profil en dents de scie de 2,5 m d'amplitude, il
compte tout. Le chiffre est annoncé « indicatif » (`:131`), c'est honnête,
mais l'affirmation sur le bruit n'est pas mesurée — règle absolue 5.
*Correction : soit mesurer (un test qui compare le D+ d'un profil lisse et du
même profil bruité), soit retirer l'affirmation et écrire ce que le code fait
vraiment.*

## 4. Lot L2.3 — Candidates de boucle

### Verdict : **à corriger**

La stratégie du contrat est respectée à la lettre : azimuts en éventail
(`boucle/candidates.py:42-51`), rayon initial `cible / 5` avec le rapport 5
posé comme point d'entrée et non comme vérité (`:23-25`, `:101`), au plus deux
ajustements (`:103`), plafond global d'appels (`:104`, `:132-133`), seules les
boucles bornées retenues (`:119`), la **meilleure** tentative d'un azimut
gardée et non la dernière (`:119`) — détail que le dev a trouvé en mesurant
sur le vrai serveur, pas en raisonnant. L'erreur d'un azimut ne fait pas
perdre les autres (`:113-116`, `:135-136`). Le refus de `distance_km` non
finie et de `nb < 1` avant tout appel (`:88-94`) est le bon réflexe.

**D1 — l'ajustement par proportion n'est borné ni en facteur ni en valeur
(à corriger).** `boucle/candidates.py:129` fait `rayon *= cible_m /
trace.distance_m` sans garde-fou. Mesuré, avec un moteur qui rend toujours une
boucle de 100 m et une cible de 60 km : les rayons demandés sont 12 000 m,
puis **7 200 000 m**, puis **4 320 000 000 m**. Le plafond `appels_max` borne
le **nombre** d'appels, pas leur coût : les deux derniers partent sur le
serveur BRouter auto-hébergé du mainteneur avec `roundTripDistance` = 4,3
millions de kilomètres. Le docstring (`:72-73`) affirme d'ailleurs que le
plafond est « la seule garantie que la commande finit en un temps borné » —
c'est faux tant que le rayon peut exploser. Symétriquement, un moteur qui
rend une boucle beaucoup trop longue ramène le rayon à 1,73 m, arrondi à 2
par `connecteurs/brouter.py:135`.
*Correction : borner le facteur de correction (par exemple dans [0,2 ; 5]) et
le rayon lui-même dans une plage plausible (`cible / 50` à `cible`), puis
abandonner l'azimut si la borne est atteinte deux fois — une réponse qui
force la borne est une réponse qu'on ne sait pas exploiter, pas une réponse à
laquelle il faut insister.*

**D2 — au-delà de 18 candidates, des azimuts se répètent (dette, à noter).**
`boucle/candidates.py:42-51` ajoute ± 20°, ± 40°… : à `nb = 19`, `azimut+180`
et `azimut−180` désignent la même direction et le moteur est appelé deux fois
pour rien. `config.py:235` plafonne `candidates` à 20, donc c'est atteignable.
Sans gravité (`appels_max` protège), à savoir.

## 5. Lot L2.4 — Coûts d'un tracé

### Verdict : **à corriger**

Le score est exactement celui du contrat, tous les poids sont des constantes
nommées en tête de module (`boucle/couts.py:59-81`), et le test qui le vérifie
échappe à la tautologie : `tests/test_couts.py:296-302` recompose la formule à
partir des constantes **puis** `:303` épingle la valeur littérale
`3,0 × 3,0 + 0,3 + 1,0 + 2,0`. Le sous-échantillonnage à 15 m
(`boucle/couts.py:76`, `:268-276`), la fenêtre de 60 m (`:81`, `:245-253`), la
consommation du virage pour ne pas le recompter (`:226-228`) et le modulo du
cap au passage du nord (`:256-265`) sont justes et expliqués. Le traitement
d'une longueur de tronçon absurde (`:138-157`) — écarter et compter plutôt que
soustraire — a été ajouté après coup sur un défaut réel (`5ad0eb4`), et c'est
le bon geste.

**E1 — un demi-tour exact est compté à gauche, contre son propre docstring
(à corriger).** `boucle/couts.py:263-264` écrit « Un demi-tour exact (180°)
est compté à droite, faute de mieux ». Mesuré :
`_ecart_cap(0°, 180°) = −180,0`, parce que `(vers − depuis + 180) % 360 − 180`
rend un intervalle `[−180, 180)` et non `(−180, 180]` comme l'affirme `:257`.
Un aller-retour franc fabriqué pour l'occasion donne bien
`virages_gauche = 1, virages_droite = 0`. Conséquence : chaque demi-tour d'un
tracé coûte 0,3 (ou 1,3 sur une route à trafic) de score, et un aller-retour
est systématiquement pénalisé comme un tourne-à-gauche qu'il n'est pas.
*Correction : décider et écrire la même chose des deux côtés. Le plus honnête
est de ne compter le demi-tour ni à gauche ni à droite (le signe n'a pas de
sens géométrique, c'est le docstring qui le dit) : `if abs(cumul) >= 180 -
epsilon: continuer sans compter`, et corriger l'intervalle annoncé en `:257`.*

**E2 — les kilomètres non classés s'évaporent du tableau (à corriger,
léger).** `boucle/couts.py:172-178` ne compte un tronçon ni en trafic ni en
calme quand son `highway` est absent ou inconnu (`path`, `footway`, `steps`,
une nouvelle valeur OSM…). Le choix est le bon et il est commenté, mais le
tableau n'affiche que `trafic` et `non revêtu` (`boucle/commande.py:401-402`)
et rien ne dit que `km_trafic + km_calme` peut valoir nettement moins que la
distance. Un tracé à moitié sur des chemins non classés s'affiche donc
« 0,0 km de trafic » comme un tracé parfaitement calme.
*Correction : exposer `km_non_classe = distance − trafic − calme` dans le JSON
et, dans le tableau, ajouter une note quand il dépasse quelques pour cent —
comme la ligne déjà présente pour `couts_partiels` (`boucle/commande.py:359-362`).*

**Point produit, non tranché ici (voir §10).** `secondary` est dans
`HIGHWAY_TRAFIC` (`boucle/couts.py:33-35`) et vaut donc 3 km équivalents par
kilomètre. Le mainteneur a mesuré que `secondary` représente 23 % de sa
pratique : le classement est cohérent avec le contrat, la pondération est un
arbitrage qui lui appartient.

## 6. Lot L2.5 — Pluie et vent le long du tracé

### Verdict : **OK**

C'est le lot le plus propre du sprint, et le seul sans défaut de correction
trouvé. Les quatre pièges annoncés sont traités :

- **un seul appel** Open-Meteo pour tous les échantillons
  (`boucle/meteo_trace.py:125-127`, et `meteo/openmeteo.py:93` fait bien une
  seule requête HTTP pour N coordonnées) ;
- **heure pile** rendue seule des deux côtés
  (`boucle/meteo_trace.py:264-281`), avec la raison écrite : sinon une valeur
  absente à 08 h effacerait la valeur connue de 09 h ;
- **interpolation angulaire** de la direction du vent par ses composantes
  (`:290-299`), avec le cas dégénéré des directions opposées traité (`:297-298`) ;
- **hors de la série, tout est absent** (`:243-252`) — on ne prolonge pas la
  dernière heure connue, ce qui serait affirmer sans mesure.

La règle des ±45° n'est pas réécrite : `meteo.rapport.vent_relatif` est
importée et appliquée au cap local (`:29-37`, `:144-146`), exactement comme le
contrat le demandait. La pondération par la durée que chaque échantillon
représente (règle du point milieu, `:373-392`) est un raffinement au-delà du
contrat, et il est juste : la somme des durées vaut exactement la durée du
parcours.

**F1 — `part_vent_face` est un pourcentage sur un dénominateur partiel, sans
le dire (à corriger, très léger).** `boucle/meteo_trace.py:356-358` divise par
le nombre d'échantillons **au vent connu**. C'est le bon choix (un échantillon
sans donnée ne doit pas compter pour du travers) et il est commenté
(`:352-355`), mais `boucle/commande.py:409` affiche « vent face 100 % » sans
distinguer « 12 échantillons sur 12 » de « 1 sur 12, les autres hors horizon ».
*Correction : ajouter le dénominateur au JSON (`echantillons_vent_connus`) et
marquer la cellule quand il est inférieur au nombre total d'échantillons.*

## 7. Lot L2.6 — CLI `ourouler boucle`

### Verdict : **à corriger**

L'enchaînement est celui du contrat §6, les colonnes sont dans l'ordre demandé
(`boucle/commande.py:325-337`), le tri est bien `score + pluie × 2` avec le
poids posé en constante nommée et annoncé comme un arbitrage et non une mesure
(`:53-55`, `:298`). Trois décisions valent d'être saluées : toutes les erreurs
d'utilisation tombent **avant** le premier appel réseau (`:148-205`) ; une
panne Open-Meteo ne fait pas perdre la boucle, les colonnes météo disparaissent
au lieu d'afficher des tirets et un avertissement part sur stderr
(`:132-137`, `:246-275`) ; et `ABSENT = "—"` n'est jamais remplacé par un zéro
(`:60-63`), ce que la règle absolue 5 exige. Le lot est déclaré vérifié pour
de vrai sur le serveur BRouter et Open-Meteo (`15d841d`).

**G1 — une écriture de GPX qui échoue sort en trace, pas en message
(à corriger).** `boucle/commande.py:310` fait `chemin.write_text(...)` hors de
tout `try`. Un `--sortie /chemin/inexistant/x.gpx`, un disque plein ou un
dossier courant non inscriptible donnent une `OSError` nue : `cli.py:206-208`
n'attrape que `ErreurUtilisateur`, donc trace complète et code 1, après avoir
consommé jusqu'à 12 appels BRouter et 10 appels Open-Meteo. C'est la même
famille de défaut que C1 du sprint 1 (`cache.py:147`), corrigé là-bas.
*Correction : envelopper dans un `try` et lever
`ErreurUtilisateur(f"écriture impossible dans {chemin} ({e})")`. Et vérifier
l'inscriptibilité du dossier de sortie dans `lire_options`, avec les autres
refus d'avant-réseau.*

**G2 — le GPX écrase un fichier existant sans un mot (à corriger, léger).**
Même ligne. Le nom par défaut (`:314-317`) porte l'horodatage à la minute,
donc la collision est improbable ; avec `--sortie`, elle est le cas normal
d'une deuxième exécution. *Correction : dire en une ligne que le fichier a été
remplacé, ou refuser sans `--forcer`. À trancher avec le mainteneur : le
remplacement silencieux est peut-être ce qu'il veut.*

**G3 — le coût en appels externes n'est ni affiché ni borné côté météo
(à corriger, léger).** Mesuré : 2 appels Open-Meteo par candidate, soit 10
pour les 5 candidates par défaut, plus jusqu'à 12 appels BRouter. C'est
acceptable en CLI (le gratuit Open-Meteo tolère ~10 000 appels par jour et par
adresse, soit ~1 000 `ourouler boucle` par jour depuis une machine) et ce
n'est pas un sujet pour le mainteneur. Ça en devient un en hébergé : voir §9.
*Correction minimale : dire le nombre d'appels dans le JSON
(`appels_brouter`, `appels_meteo`), ce qui rend le coût mesurable au lieu
d'être à recalculer à la lecture du code.*

## 8. Lot L2.7 — Rattachement par capteur et métadonnées Intervals

### Verdict : **à corriger**

L'ordre du contrat §7 est implémenté exactement, dans le bon ordre, avec la
raison de l'inversion écrite (`activites/inventaire.py:83-132`), et la
comparaison des noms de capteur à la casse et aux blancs près
(`:135-144`) est le bon niveau de tolérance pour un champ libre. Les six
champs de `meta` demandés sont recopiés (`connecteurs/intervals.py:270-290`),
`bilateral` est bien déduit de la présence d'`avg_lr_balance`, et
`equipements()` ne coûte qu'un appel par client, gardé dans l'instance, même
vide (`:115-132`). Le rafraîchissement sans retéléchargement
(`:337-345`, `activites/cache.py:159-186`) fait exactement ce qu'il annonce et
c'est ce qui rend la DoD atteignable sur un cache de 355 sorties. La colonne
« capteur » de l'inventaire (`activites/inventaire.py:235-241`) est une bonne
idée hors contrat : elle montre au mainteneur sur quoi repose le rattachement
sans ouvrir le cache.

**H1 — deux activités qui partagent le même fichier n'en font qu'une, et la
synchronisation ne converge jamais (à corriger).** Le cache est indexé par
`sha256(contenu)` (`activites/cache.py:140`) avec
`ON CONFLICT(identifiant) DO UPDATE SET source, id_externe, equipement, meta`
(`:152-154`). Mesuré : deux activités Intervals distinctes portant le même
fichier d'origine donnent **une seule ligne**, celle de la dernière, et
`contient(source="intervals", id_externe="i1")` répond alors **faux**. Donc,
à chaque `--synchroniser`, le fichier de `i1` est retéléchargé, la ligne
bascule sur `i1`, et `i2` disparaît à son tour : la synchronisation oscille
indéfiniment et une des deux activités manque toujours à l'inventaire. C'est
le mécanisme derrière les triathlons sortis de l'inventaire. Le docstring
`activites/cache.py:135` présente la chose comme une qualité (« Idempotent :
ajouter deux fois le même contenu ne crée qu'une entrée ») — c'en est une pour
un même fichier réimporté deux fois, c'en est une perte de données pour deux
activités distinctes.
*Correction : rendre l'index unique sur `(source, id_externe)` **et** garder
`identifiant` comme nom du fichier brut — une ligne par activité, un fichier
par contenu. C'est aussi ce que la doctrine §10.1 demandera en hébergé (« une
colonne propriétaire en tête »), où deux utilisateurs auront à coup sûr des
fichiers identiques. À défaut, au minimum : détecter la collision et la
signaler dans le rapport de synchronisation, au lieu de l'écraser.*

**H2 — la limite « une ligne par contenu » n'est documentée nulle part pour
l'utilisateur (à corriger).** Grep sur `README.md` et `docs/` : rien. Elle
n'apparaît que dans un docstring (`activites/cache.py:135`), et présentée à
l'envers (§H1). Le mainteneur découvrira l'écart en comparant un total à
Intervals.
*Correction : une ligne dans le `README.md`, à côté de la description de
`ourouler inventaire`, tant que H1 n'est pas corrigé.*

**H3 — les deux filtres de sport ne disent pas la même chose (à corriger).**
`connecteurs/intervals.py:333` écarte tout ce dont le `type` n'est pas
littéralement dans `TYPES_VELO` — un type absent ou vide compris. Or
`activites/modele.py:59-64` fait exactement l'inverse pour l'inventaire : un
sport absent **compte comme du vélo**, « on ne jette pas une sortie parce que
la source s'est tue ». Les deux raisonnements sont défendables, mais pas
ensemble : une activité Intervals sans `type`, ou d'un type nouveau
(« Gravel » plutôt que « GravelRide »), n'est jamais rapatriée, comptée en
`autres_sports` et perdue en silence.
*Correction : faire passer les deux filtres par `est_sport_velo`, en laissant
le connecteur écarter seulement les sports **nommés et manifestement autres**,
comme l'inventaire.*

**H4 — l'inventaire dit combien d'activités il écarte, pas lesquelles
(à corriger, léger).** `activites/inventaire.py:253-254` affiche « N
activité(s) d'autres sports ignorée(s) ». C'est déjà bien plus qu'un silence,
mais avec « Triathlon » parmi les libellés écartés, le mainteneur ne peut pas
savoir que quatre sorties vélo réelles viennent d'en sortir.
*Correction : lister les libellés distincts écartés et leur compte —
« 622 activités d'autres sports ignorées (Run 410, Swim 180, Triathlon 4…) ».
Une ligne, et la question ne se pose plus.*

## 9. Doctrine §10 — cible hébergée

### Verdict : **à corriger sur un point explicite, conforme partout ailleurs**

Ce que le sprint respecte sans réserve : le cœur reçoit `Config` et des
connecteurs, jamais un chemin (`boucle/commande.py:94-129`) ; chaque commande
rend du JSON, et celui de `boucle` est complet, échantillons compris
(`boucle/commande.py:431-513`) ; les secrets sont masqués dans toutes les
sorties JSON (`cli.py:50-52`) ; le cache reste derrière la classe `Cache`,
aucun SQL n'a fui dans `boucle/`.

**I1 — la couche de cache injectable devant le client météo, exigée « dès le
sprint 2 », n'existe pas (à corriger).** `doctrine_architecture.md` §10.1
écrit noir sur blanc : « Le module météo est donc écrit avec une couche de
cache injectable devant le client HTTP **dès le sprint 2**. » Grep sur
`src/ourouler/meteo/` et `src/ourouler/boucle/` : aucune occurrence de cache.
`ourouler boucle` fait donc 10 appels Open-Meteo pour 5 candidates qui
partent toutes du même point et se recouvrent largement — un cache par maille
et par heure en effacerait la plus grande partie. En CLI, aucune conséquence
(le gratuit tolère ~10 000 appels par jour et par adresse). En hébergé, c'est
précisément l'escalade que la doctrine voulait éviter d'avoir à rattraper.
Aucun écart n'est déclaré : ni le contrat du sprint, ni un commit, ni une
docstring ne mentionnent ce point de la doctrine.
*Correction : soit poser la couche (un protocole `CacheMeteo` à deux méthodes,
une implémentation « sans mémoire » par défaut, injectée dans
`ClientOpenMeteo`), soit faire acter l'ajournement par le mainteneur et
l'écrire dans la doctrine — la doctrine se modifie par décision explicite, pas
par omission.*

**I2 — H1 (une ligne par contenu) est aussi un sujet de doctrine §10.** En hébergé, deux
utilisateurs qui importent le même GPX public partageraient une ligne
d'index. Le correctif proposé en H1 (unicité sur `(source, id_externe)`, plus
tard sur `(propriétaire, source, id_externe)`) est le même des deux côtés :
autant le faire une fois.

## 10. Qualité des tests

1 286 tests, dont un socle adversarial substantiel pour le sprint 2
(fabriques géométriques, GeoJSON BRouter, Open-Meteo, garde-fou de temps).
Trois raisons de leur faire confiance :

- **le garde-fou réseau est une mesure, plus une approximation**
  (`tests/adversarial/conftest.py:52-54`) ;
- **le détecteur de données personnelles a son propre test positif**
  (`tests/adversarial/test_adv_invariants.py:394-402`) : « un test négatif ne
  prouve rien sans la preuve que le détecteur détecte » ;
- **la tautologie évidente est évitée là où elle guettait**
  (`tests/test_couts.py:296-303`, formule recomposée **puis** valeur littérale).

Aucun mock complaisant trouvé : les réponses BRouter sont fabriquées par un
générateur reproductible et jamais enregistrées
(`tests/fixtures/generer_brouter.py`), les réponses Open-Meteo passent par
`httpx.MockTransport`, et le dev de L2.5 déclare avoir vérifié que deux
mutations clés (interpolation angulaire, heure pile) sont bien attrapées par
ses tests (`ca82839`) — la bonne façon de prouver qu'un test mesure.

**Les trois tests adversariaux modifiés au sprint 2, et leur justification :**

1. `tests/adversarial/test_adv_inventaire.py::test_equipement_prime_sur_le_home_trainer`
   → `test_l_interieur_prime_sur_l_equipement` (commit `cad2f1f`). L'assertion
   passe de `"Alpha"` à `HOME_TRAINER`. **Justifié** : le contrat du sprint 2
   §7 inverse explicitement l'ordre du sprint 1, la décision est tracée (Q7,
   close par `b4afa1d`), et le test réécrit cite le contrat dans son
   docstring. La cible a bougé par décision, pas par commodité.
2. `tests/adversarial/test_adv_inventaire.py::test_periode_prime_sur_le_home_trainer`
   → `test_l_interieur_prime_sur_la_periode` (même commit, même raison).
   **Justifié**, et c'est en prime la correction du défaut C4 que la relecture
   du sprint 1 avait signalé comme devant être reposé au mainteneur : il l'a
   été, il a tranché, le test suit.
3. `tests/adversarial/test_adv_rattachement2.py::test_sans_rafraichir_meta_rien_ne_bouge`
   (commit `c25aaeb`) : le test appelait `synchroniser` **sans** le drapeau
   tout en exigeant le comportement de `False` ; il passe désormais
   `rafraichir_meta=False` explicitement. **Justifié sur le fond** — le
   contrat §7 écrit « `synchroniser` gagne `rafraichir_meta=True` », donc un
   défaut à `True`, et la DoD l'impose. Le test a de surcroît été **renforcé**
   au passage (comparaison de `meta` et `equipement` avant/après, et
   `mises_a_jour == 0`), ce qui est la bonne manière de répondre à un test
   adversarial qu'on juge faux.

   *Réserve : la modification a supprimé la seule couverture du **défaut** du
   paramètre.* Après vérification, plus aucun test n'exerce `synchroniser`
   sans passer `rafraichir_meta` explicitement, et
   `tests/test_inventaire.py:455-457` ne vérifie que le code de sortie 2 de
   `--sans-rafraichir`. Le comportement dont dépend la DoD — `ourouler
   inventaire --synchroniser` **sans option** enrichit les entrées — n'est
   donc plus mesuré nulle part. *Correction : un test qui appelle
   `synchroniser(client, cache, depuis)` sans le drapeau et vérifie que la
   meta a bougé.*

**J1 — la bande d'ambiguïté des microdegrés n'est pas visitée (à corriger).**
`tests/adversarial/test_adv_brouter.py:180-196` paramètre bien
microdegrés/degrés, mais aucune coordonnée de test ne tombe dans
|coordonnée| ≤ 0,001°, seule zone où la conversion se trompe (§2, B1). Le
contrat §8 demandait pourtant « le cap au passage du méridien 0 ».
*Correction : ajouter le cas, dans `generer_brouter.py` comme dans les
fabriques adversariales.*

**J2 — `tests/test_trace.py` est mince pour un module partagé (dette, à
noter).** 2 tests, 39 lignes, pour `distance_m`, `cap_deg`, `sens_boucle` et
`bornee`, que quatre modules utilisent. Le seuil `FERMETURE_M = 300` n'est
testé à sa borne nulle part, et le seuil d'aire de 10 000 m²
(`boucle/trace.py:88`) non plus. Les usages indirects couvrent beaucoup, mais
ce sont les deux constantes qui décident si une boucle est une boucle.

## À corriger avant de montrer au mainteneur

Par gravité décroissante.

1. **`docs/journal/sprints/sprint2_contrat.md:17` et `:178-182`, `docs/journal/questions/questions_mainteneur.md:29-34`
   — données du mainteneur dans le dépôt, augmentées par ce sprint**
   (deux numéros de capteur, quatre identifiants d'équipement Intervals), et
   surtout **toujours présentes dans l'historique git** malgré la purge
   `24d2f09` : `git log -p` rend « SRAM 1052 » depuis `2788ba7`, dans
   `config.py`, `tests/test_config.py` et `config.example.toml`. La relecture
   du sprint 1 avait déjà classé le sujet bloquant pour la publication ; il
   s'est aggravé. **Bloquant pour l'ouverture du dépôt (Q6)**, décision du
   mainteneur : réécrire l'historique de `sprint-2` avant la PR (aucun de ces
   commits n'est sur `main`), ou sortir ces valeurs de `docs/` et assumer.
2. **`activites/cache.py:140` et `:152-154` — deux activités qui partagent le
   même fichier n'en font qu'une, et `--synchroniser` ne converge jamais**
   (mesuré : `contient()` devient faux pour la première, qui est
   retéléchargée à chaque exécution, faisant disparaître la seconde à son
   tour). Perte de données silencieuse, mécanisme derrière les triathlons
   sortis de l'inventaire. Index unique sur `(source, id_externe)`,
   `identifiant` restant le nom du fichier brut.
3. **`connecteurs/brouter.py:56` et `:377-378` — une coordonnée de message à
   moins de 0,001° d'un axe est lue comme des degrés** (mesuré :
   `_degres("570")` → 570,0). Les tronçons sont alors rattachés n'importe où,
   en silence, et `km_trafic` devient faux. Sans effet dans la ville du mainteneur, faux partout
   ailleurs — et toutes les fixtures du dépôt vivent dans cette zone.
   Décider l'unité une fois pour toute la réponse, pas valeur par valeur.
4. **`boucle/candidates.py:129` — l'ajustement du rayon n'est borné ni en
   facteur ni en valeur** (mesuré : 12 000 → 7 200 000 → 4 320 000 000 m face
   à un moteur qui rend 100 m). Le plafond `appels_max` borne le nombre
   d'appels, pas leur coût, contrairement à ce qu'affirme le docstring
   `:72-73`. Borner le facteur et le rayon, abandonner l'azimut à la borne.
5. **`boucle/commande.py:399` et `boucle/gpx.py:39` — la colonne « D+ » ne dit
   pas d'où elle vient**, alors que le moteur et la relecture du GPX
   divergent de 10 à 32 % sur trois mesures, dans les deux sens. Le `<desc>`
   du GPX écrit porte le chiffre du moteur, si bien que `--gpx` sur le
   fichier qu'on vient d'écrire affiche autre chose. Ranger la provenance dans
   `meta["denivele_source"]` et l'afficher.
6. **`boucle/couts.py:256-265` — un demi-tour exact est compté à gauche, alors
   que le docstring dit « à droite »** (mesuré : `_ecart_cap(0, 180) = −180`,
   et un aller-retour donne `virages_gauche = 1`). Ne le compter ni à gauche
   ni à droite, et corriger l'intervalle annoncé en `:257`.
7. **`connecteurs/intervals.py:333` contre `activites/modele.py:59-64` — les
   deux filtres de sport se contredisent** : le connecteur écarte un `type`
   absent, l'inventaire le compte comme du vélo. Une activité Intervals sans
   type ou d'un type nouveau n'est jamais rapatriée, en silence. Faire passer
   les deux par `est_sport_velo`.
8. **`boucle/commande.py:310` — une écriture de GPX qui échoue sort en trace
   et code 1**, après avoir consommé jusqu'à 22 appels externes. Même famille
   que C1 du sprint 1. `try` / `ErreurUtilisateur`, et vérification du dossier
   de sortie dans `lire_options`.
9. **`doctrine_architecture.md` §10.1 — la couche de cache injectable devant
   le client Open-Meteo, exigée « dès le sprint 2 », n'existe pas**, et aucun
   écart n'est déclaré. La poser, ou faire acter l'ajournement et mettre la
   doctrine à jour — elle ne se modifie pas par omission.
10. **`README.md` — la limite « une ligne par contenu » n'est écrite nulle
    part pour l'utilisateur**, et le seul docstring qui l'évoque
    (`activites/cache.py:135`) la présente comme une qualité. À écrire tant
    que le point 2 n'est pas corrigé. Au passage : le tableau du README
    annonce toujours `ourouler inventaire` « sprint 1 — non vérifié sur
    vraies données » alors que la DoD du sprint 2 exige l'inverse, et
    `ourouler boucle` n'y porte aucune mention de vérification.
11. **Aucun test ne mesure plus le défaut de `rafraichir_meta`** (§10, point
    3) : tous passent le drapeau explicitement depuis `c25aaeb`, alors que la
    DoD repose sur le comportement sans option. Ajouter un test qui appelle
    `synchroniser(client, cache, depuis)` nu.
12. **`tests/adversarial/test_adv_brouter.py:180-196` — la bande
    |coordonnée| ≤ 0,001° n'est jamais visitée**, alors que le contrat §8
    demandait le passage au méridien 0. C'est ce test qui aurait dû attraper
    le point 3.
13. **`tests/adversarial/test_adv_invariants.py:383-391` — le détecteur de
    données personnelles ne scanne ni `config.example.toml` ni `README.md`**,
    alors que c'est `config.example.toml` qui portait la faute purgée par
    `24d2f09`.
14. **`connecteurs/brouter.py:290-291` — des messages perdus faute de point où
    s'accrocher ne sont pas comptés** dans `meta["messages_ignores"]`,
    contrairement à l'intention affichée en `:233-236`.
15. **`boucle/couts.py:172-178` — les kilomètres non classés s'évaporent** :
    un tracé sur des chemins sans `highway` connu s'affiche « 0,0 km de
    trafic » comme un tracé calme. Exposer `km_non_classe` et le signaler.
16. **`activites/inventaire.py:253-254` — dire *lesquels***, pas seulement
    combien : « 622 activités d'autres sports ignorées (Run 410, Swim 180,
    Triathlon 4…) ».
17. **`boucle/gpx.py:129-132` — le docstring de `_denivele` affirme un effet
    sur le bruit d'altimètre qui n'est pas mesuré** (règle absolue 5) :
    mesurer, ou écrire ce que le seuil de 2 m fait vraiment.
18. **`boucle/meteo_trace.py:356-358` et `boucle/commande.py:409` — « vent
    face 100 % » ne distingue pas 12 échantillons sur 12 d'un seul sur 12.**
    Exposer le dénominateur.
19. **`boucle/commande.py:310` — le GPX de sortie écrase sans un mot.**
    Improbable avec le nom par défaut horodaté, normal avec `--sortie`. À
    trancher avec le mainteneur.

## Dette assumée, à noter au plan

- **Deux haversine dans le dépôt** : `boucle/trace.py:54` (mètres, sur
  `PointTrace`) et `meteo/couronne.py:135-142` (kilomètres, sur des flottants),
  avec deux constantes de rayon terrestre (`trace.py:14`,
  `couronne.py:18`). Ce n'est pas un copier-coller — les signatures diffèrent
  — mais c'est la même formule à deux endroits. À réunir au prochain passage.
- **Garde-fou réseau par blocage de socket seulement dans
  `tests/adversarial/`** (`tests/adversarial/conftest.py:52-54`) ;
  `tests/conftest.py` n'en a pas et le reste de la suite dépend encore de
  l'analyse statique (`tests/test_invariants.py:93-101`). Dette du sprint 1
  inchangée, avec désormais le modèle à recopier.
- **`tests/test_trace.py` : 2 tests pour le module géométrique partagé.**
  `FERMETURE_M = 300` et le seuil d'aire de 10 000 m² (`trace.py:88`) — les
  deux constantes qui décident si une boucle est une boucle — ne sont testés
  à leur borne nulle part.
- **Au-delà de 18 candidates, `azimuts()` répète des directions**
  (`boucle/candidates.py:42-51`), et `config.py:235` autorise jusqu'à 20.
  Sans gravité, `appels_max` protège.
- **`couts.evaluer` écrit dans `trace.meta`** (`boucle/couts.py:149`, `:166`) :
  une fonction d'évaluation qui modifie son entrée. C'est documenté et ça
  rend service à l'affichage, mais c'est un effet de bord à connaître si un
  jour deux évaluations tournent sur le même `Trace`.
- **10 appels Open-Meteo et jusqu'à 12 appels BRouter par `ourouler
  boucle`**, non comptés dans la sortie. Sans conséquence en CLI (~1 000
  exécutions par jour et par adresse sur le gratuit) ; à revoir en hébergé,
  avec le point 9 ci-dessus.
- **Dette du sprint 1 : rien n'a empiré côté code.** Vérifié un par un, les
  correctifs annoncés sont là (`--json` après la sous-commande, clé masquée
  dans `repr`, NP pondérée par la durée, découpe mensuelle systématique,
  `--depart` au passage d'heure, NaN rejeté, fixtures réduites à 147 Ko,
  `_remplacer` supprimé, `PRAGMA user_version` contrôlé). Le seul axe qui
  s'est dégradé est la donnée personnelle dans `docs/` et dans l'historique
  git (point 1).
- **Écarts au contrat, acceptés et déclarés** : `--sans-rafraichir` en plus
  (`cli.py:132-137`), `ourouler config` étendu à BRouter et boucle
  (`cli.py:96-118`), `--direction` acceptant les 16 secteurs et la notation
  anglaise du ouest (`boucle/commande.py:208-240`),
  `meta["segments_ignores"]` et `meta["messages_ignores"]` en plus, le filtre
  de sport côté inventaire (hors contrat §7, qui ne le demandait que côté
  connecteur). Tous utiles, tous déclarés en commit, aucun ne contredit le
  contrat — à enregistrer comme surface publique du sprint.

## Points produit pour le mainteneur

Aucun n'est tranché ici : ce sont des arbitrages qui lui appartiennent.

1. **`secondary` compte comme du trafic, à 3 km équivalents par kilomètre**
   (`boucle/couts.py:33-35`, `:62`). Il a mesuré que `secondary` représente
   23 % de sa pratique : avec cette pondération, un quart de ses routes
   habituelles pèse comme si elles étaient trois fois plus longues, et les
   boucles qui les empruntent seront systématiquement reléguées. Trois
   sorties possibles : sortir `secondary` du trafic, lui donner un poids
   propre entre `calme` et `trafic`, ou garder le classement et baisser
   `POIDS_KM_TRAFIC`. Le contrat fixait la classification, pas sa justesse
   pour sa pratique.
2. **Le poids de la pluie dans le tri** (`boucle/commande.py:53-55` : un
   millimètre cumulé = deux kilomètres équivalents de score). Le dev l'annonce
   lui-même comme « un arbitrage assumé, pas une mesure ». C'est le curseur
   qui décide si la commande préfère une boucle sèche et passante ou une
   boucle calme et mouillée.
3. **Quel D+ afficher** (point 5 de la liste ci-dessus) : celui du moteur ou
   celui relu du GPX ? Ils divergent de 10 à 32 %, dans les deux sens selon le
   tracé. La proposition est de nommer la provenance plutôt que de choisir en
   silence, mais s'il préfère un seul chiffre, c'est à lui de dire lequel.
4. **Les triathlons, et les activités multisport en général.** Quatre sorties
   vélo réelles sortent de l'inventaire parce qu'Intervals les nomme
   « Triathlon » (§8, H1 et H3). Veut-il que la partie vélo d'un triathlon
   compte dans ses kilomètres et dans la calibration, ou qu'elle en soit
   écartée comme une sortie atypique ? La réponse change le filtre et, plus
   tard, le jeu de calibration du modèle physique.
5. **Le GPX de sortie écrase-t-il sans prévenir ?** (point 19). Avec
   `--sortie fichier.gpx`, la deuxième exécution remplace la première sans un
   mot. Silence, avertissement, ou refus sans `--forcer` ?
6. **L'ordre de rattachement lui a été soumis et il a tranché (Q7, close).**
   Rien à redemander ; noté ici pour mémoire, parce que deux tests
   adversariaux ont été réécrits sur cette décision (§10).

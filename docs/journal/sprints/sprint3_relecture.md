# Relecture du sprint 3 — lots L3.1 à L3.3

Relu le 13/09/2026 par l'agent `relecteur` (Opus) sur la branche `sprint-3`,
après fusion des trois lots, des tests adversariaux et des corrections.
Lecture de `CLAUDE.md`, `doctrine_architecture.md` (dont §10),
`docs/journal/sprints/sprint3_contrat.md`, `docs/journal/sprints/sprint3_relecture_fable.md`,
`docs/journal/sprints/sprint2_relecture.md` (grille et dette héritée), puis de
`boucle/antennes.py`, `apprentissage/{routes,commande}.py`,
`physique/{modele,calibration,commande}.py`,
`connecteurs/openmeteo_archive.py`, des diffs `sprint-2...sprint-3` de
`boucle/{candidates,couts,commande,trace,meteo_trace}.py`,
`connecteurs/brouter.py`, `config.py`, `cli.py`, `README.md`, et des tests
correspondants. Aucun fichier sous `src/` ou `tests/` n'a été modifié : ce
document est le seul livrable de la relecture.

**`src/ourouler/physique/comparer.py` et `tests/test_physique_comparer.py` sont
hors relecture, en cours de réécriture par un autre agent** (schéma « séries
plates droites Z2 » validé par le mainteneur le 13/09, complément de
`docs/journal/sprints/sprint3_relecture_fable.md`). Tout ce qui touche `comparer` n'est cité
ici que pour ce qu'il impose **ailleurs** — le README, au §9 point 1.

**Verdict global : à corriger, rien de bloquant.** Les trois lots sont au
contrat, les écarts au contrat sont tous déclarés dans une constante nommée ou
un docstring, les quatre corrections de la passe Fable (vent à hauteur de
cycliste, terme cinétique, multisport, vitesse du modèle pour l'heure de
passage météo) sont en place et mesurées, les invariants du sprint 1-2 tiennent
et ont été étendus. Trois défauts de correction méritent d'être repris avant de
montrer le lot, tous corrigeables en quelques lignes, et neuf points légers ou
de documentation.

| Lot | Verdict |
|---|---|
| Règles absolues | **OK** |
| L3.1 — antennes (détection, élagage, intégration candidates) | **à corriger** |
| L3.2 — routes connues (apprentissage, poids, CLI `routes`) | **à corriger** |
| L3.3 — modèle physique et calibration | **OK** |
| L3.3 — archive météo (`connecteurs/openmeteo_archive.py`) | **à corriger** |
| L3.3 — `physique/commande.py` (`calibrer`, `simuler`) | **OK** |
| Intégration `boucle` (coûts, temps, colonnes) | **à corriger** |
| Tests | **OK** |
| Doctrine §10 (cible hébergée) | **à corriger** sur un point |
| `physique/comparer.py` | **hors relecture, en cours** |

## 0. État mesuré

```
uv run ruff check .   → All checks passed!
uv run pytest -q      → 2334 passed, 32 skipped, 1 warning in 8,4 s
```

Conforme à l'attendu. Les 32 `skipped` sont des cas paramétrés légitimes et
étiquetés (28 « puissance au-delà de la borne de bissection »,
4 « vitesse saturée : la réciprocité ne s'applique pas ») ; aucun test n'est
désactivé.

Mesures faites en plus de la lecture (scripts jetables hors dépôt, tous
reproductibles) :

| Mesure | Résultat |
|---|---|
| `generer(nb=5)` face à un moteur qui ne converge jamais | **3 candidates** rendues pour 12 appels (§4, D1) |
| `ClientArchive.horaires(jour = aujourd'hui)` sur une réponse tronquée à 10 h | acceptée, **écrite en cache** ; relue une semaine plus tard : 14 h sans vent, **0 appel HTTP** (§5, E1) |
| `detecter` sur une boucle de 60 km (12 001 points) | 9 ms — aucun enjeu de performance |
| `detecter` sur un zigzag de 6 000 points (pire cas du pré-filtre) | 53 ms — idem |
| grep coordonnées françaises sur `src/`, `tests/`, `docs/`, `README.md`, `config.example.toml` | une seule occurrence, `config.example.toml:7` `latitude = 47.0000`, explicitement annotée « inventé » |
| grep clés/jetons/mots de passe littéraux | un seul, `tests/test_brouter.py:27` `"secret-de-test-a-ne-jamais-imprimer"` — valeur de test, et c'est son objet |

## 1. Règles absolues

### Verdict : **OK**

**1 — aucune donnée personnelle ni clé.** Rien de nouveau n'entre dans le
dépôt. Le détecteur de données personnelles a été étendu comme la relecture du
sprint 2 le demandait (point A2) : `tests/adversarial/test_adv_invariants.py:388-401`
ajoute `config.example.toml` et `README.md` à `_fichiers_a_scanner`, et le
détecteur reste testé positivement (`:405-413`). La règle de terrain
(« toute coordonnée à moins de 50 km d'une ville française est refusée »,
`:252-292`) couvre les nouvelles fixtures. Les trois nouveaux fichiers écrits
dans le cache (`routes_connues.sqlite`, `poids_routes.json`,
`calibration.json`) vivent sous `config.cache.dossier`, jamais dans le dépôt.
Le point A1 du sprint 2 (données du mainteneur dans `docs/` et dans
l'historique git) reste ouvert et reste une décision du mainteneur (Q6) : ce
sprint ne l'aggrave pas — les nouveaux `docs/` ne citent ni capteur, ni
identifiant d'équipement, ni URL privée.

**2 — le cœur ne sait pas où il tourne. Bien tenu, et désormais outillé.**
Les noms des quatre fichiers du cache vivent dans les `commande.py`
(`apprentissage/commande.py:47,50`, `physique/commande.py:34,50`) et nulle part
ailleurs ; `BaseRoutes` et `ClientArchive` reçoivent un `Path` déjà résolu ;
`couts.evaluer` reçoit un `dict` de poids, `simuler` des `Parametres`.
Deux invariants neufs le vérifient au lieu de l'espérer :
`tests/adversarial/test_adv_invariants.py:536-551` interdit les quatre noms de
fichiers hors `cli.py`/`commande.py`, et `:482-497` confine `numpy` à
`physique/` (`scipy` et `pandas` interdits partout). Les deux détecteurs sont
eux-mêmes testés (`:499-507`, `:553-563`), et `tests/test_invariants.py:396-401`
vérifie que l'invariant `numpy` ne serait pas vert par simple absence de
`numpy`. C'est exactement ce que la grille demandait.

*Portée réelle de l'invariant « chemins du cache », pour qu'on sache ce qu'il
ne couvre pas :* il porte sur une **liste littérale de quatre noms**
(`FICHIERS_DU_CACHE`) et exempte tout fichier nommé `commande.py`. Un cinquième
fichier de cache inventé demain dans un module du cœur passerait. L'invariant
de fond, lui, est ailleurs et tient : `tests/adversarial/test_adv_invariants.py:85-113`
(AST) et `tests/test_invariants.py:59-78` (texte) interdisent `tomllib`,
`os.environ`, `getenv`, `Path.home`, `expanduser`, `expandvars`, `socket`,
`requests`, `urllib` partout sauf `cli.py` et `config.py`. À la prochaine
occasion, ajouter un nom à `FICHIERS_DU_CACHE` fait partie du geste.

**3 — pas de réseau dans les tests. Respecté, dette inchangée.** Tous les
nouveaux clients sont injectables et injectés : `ClientArchive(http=…)`,
`ClientBrouter(http=…)`, `executer_calibrer(..., client_archive=…)`,
`executer(..., client_brouter=…)`. Aucun test ne construit un `httpx.Client`
sans `MockTransport` (invariant statique `tests/test_invariants.py:88-104`,
qui couvre bien les douze nouveaux `tests/test_*.py`). La dette héritée du
sprint 1 (point E2) est inchangée : la coupure `socket` *autouse* n'existe que
dans `tests/adversarial/conftest.py:42-55` ; `tests/conftest.py` (45 lignes)
n'en a pas, et le reste de la suite dépend de l'analyse statique. Le sprint 3
a ajouté douze fichiers de tests qui manipulent des clients HTTP sous
`tests/` : la surface non durcie a grandi, la correction reste la même
demi-douzaine de lignes à recopier. Voir §10.

**4 — lot vérifié sur vraies données.** Les quatre commandes du sprint sont
déclarées vérifiées avec date, volumétrie et chiffres dans `README.md:35-38` et
`:54-79`. Les deux livrables du contrat sont là : `routes apprendre` sur 154
sorties réelles, `calibrer` sur 99 sorties RCR et 35 BMC avec l'erreur sur les
sorties non vues (MAE 4,2 % et 2,4 %). **Une réserve, au §9 point 1 :** la
vérification publiée de `comparer` a été invalidée depuis par le mainteneur
lui-même, et le README ne le dit pas encore.

**5 — ne rien affirmer sans mesure.** Excellent, et c'est la plus belle
qualité du sprint. Quelques exemples : le dénivelé qui reste celui du moteur
après élagage est marqué `meta["denivele_approximatif"] = True`
(`boucle/antennes.py:227-230`) au lieu d'être recalculé de travers ; le
`CostPerKm` absent vaut `None` et jamais 0 (`connecteurs/brouter.py:416-421`) ;
la colonne des antennes change de titre selon qu'elle compte des mètres
**retirés** ou **détectés** (`boucle/commande.py:78-79,651-677`) ; les
échantillons retenus sans vent d'archive sont comptés et affichés
(`physique/calibration.py:1308`, `physique/commande.py:379-383`) ; la
résistance totale passe devant CdA/Crr dans le rapport, avec la mention
« détail (mal séparé, à ne pas citer seul) » (`physique/commande.py:384-400`).

**7 — aucune installation sans accord.** Rien d'installé. `numpy` est ajouté
aux dépendances, ce que le contrat §3 autorisait explicitement.

## 2. Lot L3.1 — Antennes

### Verdict : **à corriger** (un point, sur l'intégration ; la détection est bonne)

`boucle/antennes.py` est le module le plus soigné du sprint. Le cœur du
problème est vu et traité : l'appariement se fait à la **géométrie** de
l'aller (distance au segment, `_appariement_a_l_aller:329-363` et
`_ecart_au_segment:366-388`) et non à ses sommets, avec la mesure qui justifie
le choix (un retour décalé de 10 m est aussi plus long, la distance parcourue
dérive, l'appariement à distance égale tombait en deçà de la vraie jonction).
Les quatre garde-fous ne disent pas la même chose et le docstring l'explique
un par un : `FENETRE_DEFAUT_M:93` tranche (et le dit : « il ne mesure rien, il
tranche »), `LONGUEUR_MIN_M:103` écarte le bruit, `FENETRE_APPARIEMENT:128`
empêche l'antenne de déborder sur la vraie route, `EPSILON_M:134` existe parce
qu'un aller-retour parfait était refusé à 2·10⁻¹² m près. L'ordre des tests
dans `_antenne_autour:308-326` — écart d'abord, fenêtre ensuite — est commenté
avec le cas qu'il protège. Le pré-filtre `_demi_tour_possible:269-283` rend la
détection gratuite en pratique (mesuré : 9 ms sur 60 km, 53 ms sur un zigzag
de 6 000 points).

**Conformité au contrat §1.** `fenetre_m = 3000` par défaut, décision du
mainteneur du 13/09, justifiée sur mesure dans la constante elle-même
(`:84-92`). `tolerance_m = 20`. La réindexation des segments est complète et
**`cout_km` est conservé** (`_resegmenter:485-497`) — le commentaire dit
pourquoi c'est un piège : le perdre faisait disparaître la colonne « coût
profil » de toute candidate générée, sans que rien ne le dise. Un tronçon
entièrement dans l'antenne disparaît, un tronçon à cheval reprend sa longueur
des distances recalculées. `_bornees:415-426` rend un tracé intact plutôt
qu'une exception quand on lui passe des indices d'un autre tracé.
Les quatre cas du contrat §4 sont testés (aller-retour exact, quasi-exact à
10 m, boucle sans antenne, antenne plus longue que la fenêtre, antenne au
départ, préservation de la fermeture et des segments).

**Le paramètre BRouter est déclaré au bon endroit.** `CORRECTION_POINTS_DE_PASSAGE`
(`connecteurs/brouter.py:66-79`) est envoyé et documenté comme **mesuré sans
effet** sur le serveur du mainteneur, avec le protocole (réponse identique
octet pour octet, y compris pour tout autre `profile:…`, alors que `profile`,
`alternativeidx` et `roundTripPoints` changent bien le tracé). L'écart au
contrat est déclaré et la correction repose sur `antennes.py`. Rien à redire.

### D1 — `ourouler boucle` rend 3 candidates quand on en demande 5 (à corriger)

`boucle/candidates.py:39` porte `AJUSTEMENTS_MAX` de 2 à 3 — décision du
superviseur, justifiée sur mesure (l'élagage fait osciller la distance, deux
corrections s'arrêtaient au milieu de l'oscillation). Mais `appels_max` reste
à 12 (`:112`) et `boucle/commande.py:165-172` ne le passe pas : un azimut peut
désormais consommer 4 appels au lieu de 3, et la boucle s'arrête net dès que le
budget est atteint (`:180-182`).

Mesuré, face à un moteur qui ne converge jamais (cas nominal quand le serveur
rend des longueurs instables — exactement ce que la nouvelle constante veut
absorber) : **`nb=5` rend 3 candidates pour 12 appels.** Sous `sprint-2`, le
même moteur en rendait 4. C'est une régression visible par le mainteneur : il
demande cinq directions, il en voit trois, et rien ne le lui dit.

Le commentaire de `:38` (« trois candidates tiennent encore dans les 12 appels
d'`appels_max` (3 × 4) ») montre que le calcul a été fait — mais il conclut à
l'inverse de ce qu'il faudrait : c'est le plafond qui doit suivre le nombre de
candidates, pas le nombre de candidates qui doit suivre le plafond.

*Correction : faire dépendre le plafond de la demande plutôt que de le laisser
constant. Dans `boucle/commande.py:165`, passer
`appels_max=demande.nb_candidates * (1 + AJUSTEMENTS_MAX)` ; ou, a minima,
dire dans le tableau combien de candidates ont été trouvées sur combien de
demandées quand les deux diffèrent. Ajouter le test qui manque : `nb=5` face à
un moteur qui ne converge pas doit rendre 5 candidates.*

### Point léger — le mot « candidate » a deux sens dans le même docstring

`boucle/antennes.py:41-44` : « c'est un aller-retour assumé sur une route […]
et la candidate est abandonnée entièrement ». Il s'agit de la **candidate
d'antenne** ; « candidate » est par ailleurs le nom de domaine d'une boucle
dans `boucle/candidates.py`. Un lecteur comprend « la boucle est jetée ».
*Correction : écrire « et le reparcours n'est pas rendu du tout », comme le
fait déjà le docstring de `detecter:162-163`.*

## 3. Lot L3.2 — Routes connues

### Verdict : **à corriger**

Le principe du lot est le bon, et il est tenu partout : **« inconnu » n'est
jamais un malus.** `part_connue` est calculée, affichée en colonne « connu % »
et **n'entre dans aucun score** — vérifié ligne à ligne dans
`boucle/commande.py:534` (elle est posée sur l'`Evaluation`) et `:533`
(`total = couts.score + pluie * POIDS_PLUIE_TRI`, sans elle). Le docstring de
`_classer:500-512` explique pourquoi, et l'en-tête du tableau le redit à
l'utilisateur (`:779`). C'est la décision produit la plus importante du
lot et elle est tenue de bout en bout.

**Maille et demi-maille : cohérent des deux côtés.** `cle_maille:209-216` a une
définition unique, réutilisée par `physique/comparer.py`. `_mailles_traversees:219-234`
sous-découpe à 15 m (une demi-maille) pour qu'aucune maille traversée ne soit
sautée, et **`part_connue:450-458` fait exactement le même découpage** que
`_decouper:268-305`. C'est la précaution qui compte : sans elle, `part_connue`
chuterait pour la seule raison que deux tracés n'ont pas le même pas
d'échantillonnage, et le docstring `:222-227` le dit.

**Idempotence.** `ajouter_trace:335-348` court-circuite sur `id_sortie` déjà
présent et rend le compte déjà enregistré ; `apprendre:639-642` saute sans
appeler le serveur. Le `ON CONFLICT … DO UPDATE` moyenne `cout_km` pondéré par
les mètres et laisse l'existant quand la nouvelle valeur est `NULL` (`:364-368`).
Une sortie sans identifiant est refusée (`:344-345`) plutôt qu'écrite sous une
clé vide.

**`poids_appris` : parts normalisées, comme la grille le demandait.**
`_parts:759-777` divise par la somme de `km_par_highway` et **non** par
`km_total`, avec le raisonnement écrit : les deux coïncident sur une base
complète, une table filtrée les désynchronise, et on comparerait alors des
kilomètres déguisés en parts. Conséquence testable : un jeu de sorties deux
fois plus fourni rend exactement les mêmes poids. `tertiary` forcé à 0,
classe absente de l'exposition à 0, classe absente des sorties au plafond 4,
`log2` jamais appelé sur 0 ou sur une division par 0 (`_poids_classe:780-791`).
Sans exposition, retour aux poids par défaut, comme le contrat §2 l'écrit.

**`PART_EXPOSITION_MIN = 0.02` est un écart au contrat, et il est déclaré.**
`apprentissage/routes.py:88-104` : sous 2 % d'exposition, la classe garde son
**poids par défaut** au lieu du poids appris. La constante porte la décision
(superviseur, 13/09), la mesure qui l'a provoquée (`living_street` à 2,56 pour
0,8 % d'exposition, `service` à 2,35 pour 0,6 % — des malus lourds tirés de
presque rien) et la distinction, subtile et juste, entre « rien vu du tout »
(→ 0) et « trop peu vu pour en tirer un rapport » (→ défaut). C'est de la
bonne dette : assumée, nommée, justifiée.

**Robustesse de la base.** Schéma versionné avec refus d'une base plus récente
(`:322-331`), connexion ouverte le temps d'une opération, erreurs SQLite
traduites en `ErreurUtilisateur` avec le geste de réparation
(`_connexion:496-513`), `_mailles_connues:475-494` interroge par bande de
latitude en paquets de 400 plutôt que maille par maille ou base entière.
`lire_poids:812-835` rend `None` sur un JSON abîmé plutôt que de faire échouer
une boucle — et rejette les `bool` et les non-finis un par un.

### C1 — l'exposition n'est pas élaguée, les candidates le sont (à corriger)

`apprentissage/commande.py:305-311` appelle `client.boucle(…)` **brut** pour
les huit boucles d'exposition, alors que `boucle/candidates.py:156` élague
systématiquement les antennes des candidates avant de les mesurer et de les
scorer. Les deux jeux qu'on met en rapport dans
`poids = min(4, max(0, log2(part_expo / part_sorties)))` ne décrivent donc pas
la même chose : l'exposition compte des kilomètres que le score ne verra
jamais.

Ce n'est pas neutre, parce que les antennes ne sont pas réparties au hasard :
`boucle/antennes.py:86-88` relève que les culs-de-sac réels font 1,5 à 2,7 km
sur une boucle de 60 km et sont parcourus « à 60-70 % sur `track` et
`unclassified` ». Sur une boucle d'exposition de 40 km, cela fait quelques
pour cent de la distance, concentrés sur deux classes marginales dont la part
d'exposition est justement petite — celles-là mêmes où le logarithme amplifie
le bruit, et celles-là mêmes que `PART_EXPOSITION_MIN` tente de protéger.
L'exposition gonfle leur part, donc leur poids appris.

*Correction : une ligne. Dans `_boucles_exposition`, remplacer
`traces.append(client.boucle(…))` par l'élagage, comme `generer` le fait :*

```python
from ourouler.boucle.antennes import detecter, elaguer
trace = client.boucle(…)
traces.append(elaguer(trace, detecter(trace)))
```

*et le dire dans le docstring : l'exposition mesure ce que le moteur propose
**après élagage**, c'est-à-dire ce que `boucle` proposera vraiment.*

### C2 — `routes apprendre --max N` ne borne pas les appels au serveur (à corriger)

`apprentissage/routes.py:637-668` : `restantes` n'est décrémenté qu'**après**
un appel réussi (`:667-668`). Une sortie illisible, sans position exploitable,
ou refusée par le moteur (`:648-666`) ne consomme rien du quota. Or l'appel à
`client.itineraire` (`:662`) a bien eu lieu avant qu'on sache qu'il échouerait.

Conséquence concrète, et le README la documente déjà comme un cas réel : deux
sorties de vacances hors des tuiles OSM du serveur rendent « datafile … not
found » (`README.md:65-69`). Avec `--max 5` et un lot de sorties hors région,
la commande peut passer des dizaines d'appels au serveur du mainteneur alors
que l'option existe précisément pour « essayer sans tout lancer »
(`cli.py:242`).

*Correction : décrémenter `restantes` juste avant `client.itineraire`, ou
mieux, compter les appels plutôt que les succès — renommer en
`appels_restants` et décrémenter dans le `try`. L'option promet de borner un
coût, elle doit borner le coût, pas le résultat.*

### C3 — le docstring de `_decouper` décrit une implémentation qui n'existe plus (léger)

`apprentissage/routes.py:270-274` : « Chaque paire de points consécutifs est
attribuée à la maille de son **milieu** : à 30 m de maille et quelques mètres
entre deux points d'un tracé BRouter, la différence avec une découpe exacte est
en dessous du bruit, pour un code dix fois plus simple. » Le code, lui
(`:287-289`), appelle `_mailles_traversees` et répartit la longueur sur **toutes**
les mailles sous-échantillonnées à 15 m — c'est-à-dire exactement la découpe
que le docstring dit ne pas faire, et c'est la bonne (c'est elle qui rend
`part_connue` indépendante du pas d'échantillonnage, cf. `:222-227`).

*Correction : réécrire le docstring sur le code. Un docstring faux coûte plus
cher qu'un docstring absent : c'est celui-là qu'un relecteur croit.*

### C4 — `points_de_passage(maximum=1)` divise par zéro (léger)

`apprentissage/routes.py:588` : `pas = math.ceil(len(retenus) / (maximum - 1))`.
Aucun appelant ne passe autre chose que le défaut `PASSAGES_MAX = 60`, donc
sans effet aujourd'hui ; c'est le genre de borne que le testeur adversarial
vise. *Correction : `max(1, maximum - 1)`, ou refuser `maximum < 2` en entrée.*

## 4. Lot L3.3 — Modèle physique et calibration

### Verdict : **OK**

La passe Fable a fait le gros du travail sur ce lot ; je vérifie ce qu'elle a
demandé et je relis le reste.

**Les quatre corrections de `docs/journal/sprints/sprint3_relecture_fable.md` sont en place.**

1. **Vent à hauteur de cycliste.** `physique/modele.py:75-91` pose
   `FACTEUR_VENT_HAUTEUR = 0.6` avec la dérivation complète du profil
   logarithmique (`ln(1,5/0,1) / ln(10/0,1) ≈ 0,588`), et
   `vent_au_cycliste:137-149` est le **point de passage unique**. Appliqué des
   deux côtés, comme demandé : calibration via
   `physique/calibration.py:487-504` (qui dit être le seul endroit où
   l'archive est convertie, et l'est : `echantillonner`, `detecter_groupe` et
   `vent_le_long` passent tous par `_vent_de_face`), et simulation via
   `physique/commande.py:594-622` (`vent_depuis_meteo`, utilisé par
   `simuler --depart` **et** par la colonne « temps » de `boucle`). Le signe
   est conservé, ce qui est testé (`tests/test_physique_commande.py:423-440`).
   Un test vérifie même que la constante vaut bien le calcul théorique
   (`tests/test_physique_modele.py:291`).
2. **Terme d'énergie cinétique.** `Echantillon.puissance_cinetique_w:206-228`
   implémente `m·(v_fin² − v_début²)/(2·Δt)` divisé par le rendement, avec le
   bon signe (positif quand le cycliste accélère) et `Δt ≤ 0 → 0.0`. Il
   rejoint la colonne `c` des **constantes** de la régression
   (`_matrices:709`), jamais `a` ni `b` — et le commentaire `:703-705` dit
   pourquoi c'est un piège (`a` et `b` sont des **écarts** à `sans_rien`).
   `DELTA_V_MAX_MS` est relâché à 1,0 (`:98`) avec l'historique dans la
   constante. Le résultat demandé est mesuré : `README.md:134-141` rapporte
   CdA décollé de la butée (0,22) et MAE 4,2 % / 2,4 %.
3. *(`comparer` — hors relecture.)*
4. **Multisport écarté.** `motif_multisport:1093-1126` avec trois signes
   indépendants (`meta["sessions"] > 1`, un avertissement de lecture citant
   « session », sport du **fichier** non cycliste) et l'explication de
   pourquoi le sport de l'**index** ne suffit pas (Intervals annonce « Ride »
   pour le segment vélo d'un triathlon dont le FIT porte les trois sports).
   Un fichier illisible rend `None` — on ne sait pas, donc on ne juge pas.
   La relecture n'est demandée qu'aux sorties ayant déjà passé les filtres
   bon marché (`sorties_calibrables_et_motifs:1154-1155`), donc jamais sur
   les footings ni sur l'autre vélo.
5. **`boucle` à la vitesse du modèle**, et **`chdir` dans les tests.**
   `boucle/commande.py:473-495` (`_vitesse_meteo`) date l'heure de passage
   météo avec la vitesse simulée du tracé, à vent nul, et le docstring assume
   l'approximation en la chiffrant (second ordre : quelques minutes, contre
   des dizaines de minutes d'écart entre 27 km/h supposés et la vraie allure
   d'un parcours vallonné). Le repli sur la configuration est explicite.
   Les tests de `boucle` font bien `monkeypatch.chdir(tmp_path)` (20 fois dans
   `tests/test_boucle_commande.py`).

**Le modèle.** `puissance_requise:169-187` est le bilan de Martin & al. réduit,
avec la traînée en `v_air·|v_air|` — écart au contrat §3 déclaré et justifié
au docstring du module (`:10-15`) : `(v + v_vent)²` rendait une traînée
positive pour un vent arrière plus rapide que le cycliste, c'est-à-dire un
vent de dos qui freine. Une entrée non finie est **refusée** plutôt que rendue
en NaN, avec le raisonnement (`:176-178`) : un NaN traverse les additions sans
bruit et ressort en tri arbitraire. `vitesse_regime:198-240` : bissection
bornée, unicité de la racine argumentée en montée **et** en descente, puissance
nulle traitée sans cas particulier (plat → 0 m/s sans division par zéro,
descente → vitesse limite), puissance négative → 0 avec la raison (« le modèle
ne sait pas freiner »). Réciprocité vérifiée bien mieux que les 0,1 W du
contrat. `simuler:246-314` : pas de 100 m, dernier pas absorbant le reste
plutôt qu'un pas dégénéré de 3 cm (`_bornes_pas:317-331`), altitude lissée
avant d'être dérivée, plafond en descente et plancher de vitesse **comptés**
(`pas_plafonnes`, `pas_bloques`) et affichés — un temps plancher n'est pas
présenté comme une mesure.

**La calibration.** Le choix le plus fort du lot est
`calibrer:601-675` : le modèle étant **linéaire** en (CdA, Crr), on prend la
solution exacte, et les coefficients `a`, `b`, `c` sont obtenus en appelant
`puissance_requise` elle-même avec des paramètres unitaires
(`_matrices:695-711`). Aucune formule n'est recopiée, donc la calibration ne
peut pas diverger de la physique du modèle. Écart au contrat (qui prévoyait
grille + affinage) déclaré au docstring.

- **Bornes et arêtes : correct.** `_borner:719-755` ne se contente pas
  d'écrêter les deux coordonnées séparément — il résout les quatre arêtes à
  une inconnue (`_arete:758-768`, qui écrête lui-même à ses bornes, donc
  couvre aussi les coins) et garde la meilleure. C'est le vrai minimum du
  pavé pour une forme quadratique convexe, et
  `tests/test_physique_calibration.py:445-467` le mesure au lieu de le croire :
  aucun autre Crr de la grille ne fait mieux à CdA en butée.
- **Rang déficient traité** (`:645-651`) : la solution de norme minimale est
  remplacée par le point de départ et un avertissement est émis, plutôt que
  de rendre un couple arbitraire.
- **Incertitude annoncée optimiste** (`:624-627`), avec la raison (résidus
  supposés indépendants alors que deux tronçons de 200 m voisins se
  ressemblent).
- **Interpolation angulaire correcte.** `_angulaire:513-522` interpole par les
  composantes (350° et 10° donnent 0°, pas 180°) et rend `a` sur le cas
  dégénéré `x = y = 0`.
- **Pas de fuite train/test.** `partager:1221-1235` trie par
  `(jour, nom)` et réserve les plus récentes au test, avec le raisonnement
  (un tirage aléatoire mettrait dans le test des sorties du même mois, faites
  avec le même matériel, et flatterait le modèle). `calibrer_en_deux_passes:1257-1287`
  n'échantillonne **que** `apprentissage` et ne valide que sur
  `validation_sorties` ; la passe 2 restreint `restants` aux sorties gardées.
  Les bornes sont robustes : `n_test = max(1, min(n-1, round(n·part)))` garde
  au moins une sortie de chaque côté quelle que soit `part_validation`.
  Vérifié : aucune fuite.
- **`valider` à la puissance moyenne en mouvement**, avec le tableau de mesures
  qui justifie le choix contre le profil par 100 m (5,0 % contre 15,7 % de MAE,
  `:856-866`), et l'argument d'usage : on demande « combien de temps cette
  boucle à 200 W ? », pas « rejoue-moi une sortie déjà faite ».
- **`detecter_groupe:1014-1053`** retranche la puissance cinétique **avant** de
  demander au modèle la vitesse d'équilibre (`:1044-1049`) — sans quoi tout
  tronçon de relance passerait pour de l'aspiration. Seuils du contrat
  respectés (résidu > 8 % sur > 50 % de la distance **retenue**).

### F1 — collision silencieuse de clés dans `calibrer_en_deux_passes` (léger)

`physique/calibration.py:1258` et `:1283` indexent les échantillons par
`s.identifiant or s.nom`. `SortieCalibration.identifiant` a `""` par défaut, et
`nom` retombe sur `meta["nom"]` puis `fichier` : deux sorties sans identifiant
et de même nom (« Sortie du matin ») écrasent silencieusement l'une l'autre
dans `par_sortie`, donc disparaissent de `tous` **et** de `restants`. La
commande réelle passe toujours un identifiant (`physique/commande.py:299`),
donc c'est sans effet aujourd'hui — mais un appelant de bibliothèque, ou un
test, perd des échantillons sans le savoir.

*Correction : indexer par l'indice dans `apprentissage` plutôt que par une
clé reconstruite — `par_sortie = [echantillonner(…) for s in apprentissage]`,
et `gardees` garde les indices. Cinq lignes, et la classe de bug disparaît.*

### F2 — un identifiant accentué, contre la convention (léger)

`physique/calibration.py:304` et `:312` : `tronçons`. CLAUDE.md fixe
« identifiants Python en français **sans accents** (`Activite`, `couronne`,
`velo`) ». C'est le seul du dépôt (vérifié par grep sur tout `src/`).
*Correction : `troncons`.*

## 5. Lot L3.3 — Archive météo (`connecteurs/openmeteo_archive.py`)

### Verdict : **à corriger**

Le module est bon par ailleurs : arrondi de clé stable (`arrondir:79-86`, avec
le bug qu'il corrige — `round(x/0.05)*0.05` rendait `0.15000000000000002` donc
une clé différente d'une exécution à l'autre), double mémoïsation disque +
processus avec la raison (`:108-112`), cache abîmé qui n'empêche jamais de
calibrer (`:197-217` et `:239-260` : on le dit sur `stderr` et on continue),
compteurs `appels` / `lectures_cache` exposés au rapport, colonne plus courte
que `time` complétée par des absences plutôt qu'une exception (`_colonne:320-334`),
`null` et non-finis rendus en `None` (`_valeur:337-345`), jour futur refusé
avant de consommer un appel, point hors du globe refusé. Toute la lecture de la
charge JSON est défensive dans le bon sens : ce qui manque manque, et le dit.

### E1 — le jour courant est mémoïsé, donc figé incomplet pour toujours (à corriger)

`horaires:144-148` refuse un jour **strictement** futur, donc accepte le jour
même. Le docstring du module (`:9-11`) pose pourtant la prémisse qui autorise
la mémoïsation : « L'archive du passé **ne change pas** ». Elle ne tient pas
pour aujourd'hui, ni pour les jours que le service n'a pas encore consolidés :
la réponse est alors tronquée ou partiellement `null`, et `:161`
(`self._ecrire_cache(...)`) l'écrit en base **sans condition**.

Mesuré, sur une réponse « jour en cours » de 24 heures dont 14 à `null` :

```
jour courant accepté : 24 heures, dont 14 sans vent
relu une semaine plus tard : 14 heures sans vent ; appels HTTP = 0
```

Conséquence pour le mainteneur : il rentre de sortie, lance
`ourouler calibrer`, et le vent de sa sortie du jour est enregistré comme
inconnu **définitivement** — toutes les calibrations ultérieures reliront la
version tronquée, sans jamais redemander. La sortie la plus récente est aussi
celle qui tombe dans les 25 % de validation. Le défaut est silencieux à
l'échelle d'une sortie (elle compte simplement dans
`echantillons_sans_vent`), et durable.

Même remarque, plus légère, pour une réponse **vide** (point hors grille) :
elle est mémoïsée telle quelle, et c'est délibéré — le test
`tests/test_openmeteo_archive.py:236-247` la fige comme comportement voulu,
avec une justification recevable (ne pas redemander un point hors grille à
chaque calibration). Mais une réponse vide due à un hoquet du service est
indiscernable d'un point hors grille, et devient elle aussi permanente.

*Correction, deux lignes, sans changer la signature :*

```python
heures = self._demander(lat_a, lon_a, jour)
self._memoire[cle] = heures
# L'archive d'un jour non clos peut encore changer : on la garde le temps
# du processus, jamais sur disque.
if jour < aujourd_hui and heures:
    self._ecrire_cache(lat_a, lon_a, jour, heures)
```

*et le dire dans le docstring du module, qui affirme aujourd'hui le contraire.
Si l'on veut aussi couvrir le délai de consolidation d'Open-Meteo (l'archive
ERA5 n'est pas immédiate), remplacer `jour < aujourd_hui` par une constante
nommée `DELAI_CONSOLIDATION_J` — mais ce serait un chiffre non mesuré, donc à
poser en question au mainteneur plutôt qu'à inventer.*

## 6. Intégration dans `boucle` (coûts, temps, colonnes)

### Verdict : **à corriger** (le D1 du §2 ; le reste est bon)

**Pas de régression sur le score par défaut.** `couts.evaluer:143-196` passe de
`km_trafic * POIDS_KM_TRAFIC` à une somme pondérée sur `km_par_highway`.
Vérifié ligne à ligne : `POIDS_HIGHWAY_DEFAUT` (`:73`) vaut 3,0 pour exactement
`HIGHWAY_TRAFIC`, et `_km_par_highway:220-226` classe sur
`segment.tags.get("highway", "")` — la **même** expression que
`_kilometrages:275` — donc sans poids injectés, le score est bit pour bit celui
du sprint 2. `POIDS_HIGHWAY_INCONNU = 0.0` (`:78`) tient la règle « inconnu n'est jamais
un malus » côté score aussi.

**`antennes_m` est honnête.** `couts._antennes_m:200-216` lit
`meta["antennes"]["metres_retires"]` pour une candidate déjà élaguée et
**redétecte** pour un GPX importé, avec la raison écrite (sinon la colonne
afficherait « 0 m » pour un tracé qui en est plein). Le coût de la redétection
est négligeable (mesuré 9 ms sur 60 km). Le titre de la colonne change avec la
provenance (`TITRE_ANTENNES_RETIREES` / `TITRE_ANTENNES_DETECTEES`,
`boucle/commande.py:78-79`, posés par `_titres:651-677`), et le JSON
porte `antennes_source`.

**L'en-tête dit d'où vient chaque chiffre.** Vitesse qui a daté la météo
(`_vitesse_passage:679-697`, avec l'étendue quand les candidates diffèrent),
puissance et vélo du modèle, poids par défaut ou appris avec les classes les
plus **présentes** dans les candidates affichées (`_classes_citees:784-801`, et
le docstring explique pourquoi citer les plus pénalisées donnait une ligne
vraie mais inutile). C'est la bonne granularité : deux exécutions séparées par
un `routes poids --appliquer` ne peuvent plus donner deux scores différents
sans que rien ne l'explique.

**Point léger — commentaire périmé.** `boucle/commande.py:79-86` :
`PART_FTP_DEFAUT = 0.65` est annoté « À arbitrer par le mainteneur ». Q8 est
**close** depuis le 13/09 (`docs/journal/questions/questions_mainteneur.md:167-173` : « Réponse
du mainteneur (13/09/2026) — close »), et le commit `0b9ea0a` le dit aussi.
*Correction : remplacer par « Q8, close le 13/09/2026 : allure Z2 tant que la
séance du jour n'est pas connue ; le sprint 4 la remplacera par la séance. »*

**Point léger — double simulation par candidate.** `_vitesse_meteo` puis
`_temps_modele` simulent chacune le tracé (la première à vent nul pour dater la
météo, la seconde avec le vent prévu). C'est délibéré et documenté
(`_vitesse_meteo:478-484`), le coût est invisible, mais il vaut une ligne au
plan : le jour où la simulation devient chère, c'est le premier endroit à regarder.

## 7. Qualité des tests

### Verdict : **OK**

2 334 tests, dont ~4 800 lignes neuves. Trois raisons de leur faire confiance.

**Les détecteurs sont testés positivement.** Chaque invariant statique neuf est
accompagné d'un test qui prouve qu'il détecterait la faute :
`test_le_detecteur_d_imports_fonctionne`, `test_le_detecteur_de_chemins_du_cache_fonctionne`,
`test_l_invariant_numpy_mesure_bien_quelque_chose` (« vert par absence de
numpy nulle part serait un invariant creux »). C'est la discipline que la
relecture du sprint 2 réclamait, appliquée systématiquement.

**Les contrôles négatifs existent là où la tautologie guettait.** Le risque
évident du lot physique est de fabriquer les échantillons avec
`puissance_requise` puis de les inverser avec la même fonction. Les auteurs le
disent (`tests/test_physique_calibration.py:399-400` : « des échantillons
fabriqués par le modèle, bruités, sont inversés » ;
`:522` : « Boucle fermée ») **et** ils encadrent chaque aller-retour d'un
contrôle qui doit échouer :

- `test_sans_les_vitesses_aux_bornes_l_acceleration_fausse_l_ajustement:770-786`
  rejoue les mêmes tronçons vitesses effacées et **exige** que CdA ou Crr
  dérape et que le RMSE soit dix fois pire. C'est la mesure de ce que le terme
  cinétique apporte, pas son affirmation.
- `test_valider_voit_un_cda_trop_grand:531`, `test_valider_tient_compte_du_vent:539-546`
  (« sans vent, le modèle se croit rapide », borne signée),
  `test_un_vent_de_dos_ignore_ferait_croire_a_un_groupe:596`.
- `test_la_borne_ne_se_contente_pas_d_ecreter:445-467` compare l'optimum rendu
  à six autres Crr de la grille.

**Les mocks ne sont pas complaisants.** Le moteur bouchonné de
`tests/test_boucle_candidates.py:298-323` fabrique une vraie géométrie
d'anneau avec un cul-de-sac radial calculé en mètres, pas un objet `Trace` posé
à la main : la chaîne complète GeoJSON → `_trace` → `detecter` → `elaguer` est
exercée. Les tests d'archive font passer des `null`, des colonnes tronquées,
un cache corrompu, un fichier qui n'est pas du SQLite.

**Le test adversarial modifié est justifié.** Un seul assouplissement dans tout
le sprint, et il est traité comme il faut :
`tests/adversarial/test_adv_candidates.py:220-238`,
`test_un_azimut_ne_coute_jamais_plus_de_deux_ajustements` →
`…_de_trois_ajustements`. Le seuil est extrait dans une constante nommée
`AJUSTEMENTS_CONSENTIS` portant la décision (superviseur, 13/09), la mesure qui
l'a provoquée et — c'est le point important — la phrase « **ce qui est testé
ici n'a pas changé** : un azimut ne mange pas le plafond global d'appels ».
L'invariant est préservé, seule la constante bouge. Idem côté test unitaire
(`tests/test_boucle_candidates.py:110-124`), où le montage est en plus changé
(50 km au lieu de 20) pour que ce soit bien `AJUSTEMENTS_MAX` qui arrête la
boucle et non la borne de facteur — précaution expliquée en commentaire. Aucun
autre test adversarial n'est affaibli ou supprimé.

**Ce qui manque.** Un seul test, celui du D1 : personne ne vérifie que
`generer(nb=5)` rend 5 candidates face à un moteur qui ne converge pas. C'est
précisément le trou par lequel la régression est passée.

## 8. Doctrine §10 — cible hébergée

### Verdict : **à corriger** sur un point

Ce qui est bon, et il y en a beaucoup : chaque nouvelle commande rend du JSON
(`rendre_json_calibration`, `rendre_json_simulation`, `_apprentissage_json`,
`_poids_json`, et `boucle --json` gagne `poids_routes`, `modele_physique`,
`part_connue`, `antennes`, `km_par_highway`) — c'est la future réponse d'API,
et le contrat du front. Le cœur reste appelable sans fichier ni environnement,
les deux nouveaux clients sont injectables, `Config` gagne `calibration` et
`evitements` comme données de profil et non comme constantes. Aucun secret
nouveau n'apparaît dans un JSON de sortie.

### G1 — `routes_connues.sqlite` naît sans colonne « propriétaire »

`doctrine_architecture.md` §10.1 : « Le schéma de l'index local est écrit avec
une colonne « propriétaire » en tête, pour que la migration soit un
déplacement, pas une réécriture. » Le schéma neuf de
`apprentissage/routes.py:109-131` n'en a pas, ni dans `troncons` (clé primaire
`(cle_lat, cle_lon, highway, surface, maxspeed)`) ni dans `sorties`. Or c'est
bien une donnée **par utilisateur** : ce sont les routes qu'*un* cycliste a
roulées, et en hébergé deux utilisateurs de la même ville partageraient des
mailles sans devoir partager des passages.

Le cache d'activités du sprint 1 (`activites/cache.py:42-56`) n'en a pas non
plus — dette héritée, déjà connue. Mais ce sprint **crée** un schéma neuf, et
c'était l'occasion de ne pas la reproduire. Je le signale au titre de la
contradiction avec la doctrine, pas pour la corriger sans décision :
`VERSION_SCHEMA` existe et `_migrer` a un précédent dans `activites/cache.py`,
donc le coût aujourd'hui est d'une colonne et d'un défaut ; le coût plus tard
est une migration.

*Correction proposée : ajouter `proprietaire TEXT NOT NULL DEFAULT ''` en tête
des deux tables et dans les clés primaires, passer `VERSION_SCHEMA` à 2 avec la
migration triviale. À arbitrer par le mainteneur : c'est une ligne de doctrine,
donc sa décision, pas celle d'un agent.*

*À l'inverse, `archive_meteo.sqlite` a raison de ne pas en avoir : sa clé
`(lat, lon, jour)` ne porte aucune donnée personnelle et se mutualise telle
quelle entre utilisateurs — c'est exactement le « cache des prévisions par
maille et par heure, partagé entre utilisateurs » de la doctrine §10.1. Le
noter au plan comme un acquis, pas comme un manque.*

## 9. À corriger avant de montrer au mainteneur

Par gravité décroissante.

1. **Le README publie un résultat de `comparer` que le mainteneur a déjà
   invalidé.** `README.md:41` (« vérifié sur vraies données »), `:73-79`
   (« +6 W pour le BMC, c'est-à-dire aucun avantage mesurable […] Ce résultat
   **contredit** la résistance totale calibrée ») et `:146-151` (« Deux mesures
   de l'écart RCR / BMC se contredisent […] l'écart n'est pas expliqué »). Le
   complément du 13/09 de `docs/journal/sprints/sprint3_relecture_fable.md` rapporte la mesure
   refaite selon le schéma que le mainteneur a validé (« tu as trouvé un
   schéma cohérent, c'est OK ») : **+2,6 km/h à puissance égale, ≈ 30-40 W en
   faveur du BMC**, cohérente avec la calibration et avec son « 25-30 W à la
   louche ». Montrer au mainteneur un README qui affirme le contraire de ce
   qu'il vient de valider est le pire des trois défauts, parce qu'il n'est pas
   technique : il porte sur ce qu'on lui dit. *Correction : mettre le README à
   jour **dans la même passe** que la réécriture de `comparer.py` — ligne du
   tableau, paragraphe de vérification, et suppression de la limite « deux
   mesures se contredisent » qui n'a plus lieu d'être. À coordonner avec
   l'agent qui réécrit `comparer`.*

2. **L'archive du jour courant est mémoïsée définitivement.**
   `connecteurs/openmeteo_archive.py:144` et `:161`. Mesuré : une réponse
   tronquée du jour même est figée en cache et relue sans appel une semaine
   plus tard. La sortie la plus récente du mainteneur — celle qui tombe dans la
   validation — perd son vent pour de bon. Correction et code proposé au §5,
   E1 : ne pas écrire sur disque quand `jour >= aujourd_hui` ou quand la
   réponse est vide.

3. **`ourouler boucle` rend 3 candidates quand on en demande 5.**
   `boucle/candidates.py:39` (`AJUSTEMENTS_MAX = 3`) contre `:112`
   (`appels_max = 12`) et `boucle/commande.py:165-172` qui ne le passe pas.
   Mesuré. Régression visible et silencieuse par rapport à `sprint-2`.
   Correction au §2, D1 : faire dépendre `appels_max` de `nb_candidates`, et
   ajouter le test qui manque.

4. **L'exposition n'est pas élaguée alors que les candidates le sont**, donc
   les poids appris sont biaisés en faveur des classes où tombent les antennes
   (`track`, `unclassified`). `apprentissage/commande.py:305-311` contre
   `boucle/candidates.py:156`. Correction au §3, C1 : une ligne d'élagage.

5. **`routes apprendre --max N` ne borne pas les appels au serveur.**
   `apprentissage/routes.py:643` et `:667-668` : un échec n'entame pas le
   quota alors qu'il a coûté un appel. Correction au §3, C2.

6. **Q9 et Q10 sont tranchées dans le code mais restent ouvertes dans
   `docs/journal/questions/questions_mainteneur.md`.** Q9 (`:174-206`) publie encore les
   mesures d'avant les corrections (CdA en butée à 0,18, MAE 5,2 % / 5,5 %) et
   quatre « pistes » dont trois sont abandonnées ; les vraies valeurs sont
   0,22 et MAE 4,2 % / 2,4 % (`README.md:58-68`), et
   `docs/journal/sprints/sprint3_relecture_fable.md` écrit « Q9 : close dans l'esprit
   ci-dessus — on ne sépare plus CdA et Crr ». Q10 (`:207-215`) pose la
   question « découper ou écarter ? » alors que le code a **écarté**
   (`physique/calibration.py:1093-1126`, décision de la passe Fable, point 4).
   C'est le document que le mainteneur lit pour savoir ce qu'on attend de lui :
   il ne doit pas lui demander de trancher ce qui est tranché, ni lui montrer
   des chiffres périmés. *Correction : refermer Q9 et Q10 avec la réponse et
   sa date, comme Q6 et Q8 le sont déjà.*

7. **Docstring de `_decouper` faux** — `apprentissage/routes.py:270-274`
   décrit une attribution « à la maille du milieu » alors que le code
   sous-découpe à la demi-maille. §3, C3.

8. **Commentaire périmé sur `PART_FTP_DEFAUT`** — `boucle/commande.py:85`
   dit « À arbitrer par le mainteneur » alors que Q8 est close. §6.

9. **Petites duretés** — trois lignes en tout :
   - `physique/calibration.py:304,312` : `tronçons` → `troncons` (identifiant
     accentué, contre CLAUDE.md).
   - `physique/calibration.py:1258,1283` : clé `identifiant or nom`, collision
     silencieuse ; indexer par position. §4, F1.
   - `apprentissage/routes.py:588` : `maximum - 1` peut valoir 0. §3, C4.
   - `config.py:131` et `:264` : `mots_groupe` vaut
     `("club", "groupe", "peloton")` là où le contrat §0 écrit quatre valeurs
     avec « sortie club ». Sans effet (la recherche est par sous-chaîne, donc
     « club » couvre « sortie club »), mais l'écart au contrat n'est pas
     déclaré. *Une ligne de commentaire suffit.*

## 10. Dette assumée, à noter au plan

Rien ici ne demande de correction ; tout demande d'être écrit quelque part.

- **Pas de coupure `socket` dans `tests/conftest.py`** (hérité du sprint 1,
  point E2). Le modèle à recopier est à côté depuis le sprint 2
  (`tests/adversarial/conftest.py:42-55`). Ce sprint a ajouté douze fichiers
  de tests manipulant des clients HTTP sous `tests/` : la surface non durcie a
  grandi, le coût de la correction n'a pas bougé.
- **Deux implémentations de la haversine** : `boucle/trace.py:69-73` (mètres,
  `PointTrace`) et `meteo/couronne.py:135-141` (kilomètres, flottants nus).
  Même formule, même rayon (6 371 km), signatures différentes. Hérité des
  sprints 1-2, inchangé. Pas de doublon nouveau : `cle_maille` est défini une
  seule fois (`apprentissage/routes.py:209`) et importé par
  `physique/comparer.py`.
- **Le vent d'archive est pris au point de départ pour toute la sortie**
  (`physique/commande.py:304-317`), sur une maille arrondie à 0,05° (≈ 5,5 km).
  Une boucle de 60 km en traverse plusieurs. Assumé et dit
  (`physique/calibration.py:22-26`).
- **Le facteur 0,6 est une hypothèse de rugosité moyenne**, pas une mesure du
  terrain. Dit dans la constante (`physique/modele.py:75-91`) et dans les
  limites du README (`:142-146`).
- **CdA et Crr ne se séparent pas** ; ce que les données mesurent est la
  résistance totale à 27 et 35 km/h. Dit partout où le couple est affiché.
  C'est Q9, à refermer (§9 point 6).
- **`PART_EXPOSITION_MIN = 0.02`** est un écart au contrat §2, déclaré,
  justifié sur mesure, et à revoir quand l'exposition sera élaguée (§3, C1
  peut en déplacer la frontière).
- **`AJUSTEMENTS_MAX = 3`** est un écart au contrat du sprint 2, déclaré dans
  la constante **et** dans les deux tests concernés. Bonne pratique à garder.
- **`routes_connues.sqlite` sans colonne « propriétaire »** (§8, G1) — dette
  nouvelle, contraire à la doctrine §10.1, à arbitrer.
- **Double simulation par candidate dans `boucle`** (§6) — délibérée,
  invisible aujourd'hui, premier endroit à regarder si la simulation
  s'alourdit.
- **`maxspeed` absent des `WayTags` de `fastbike`**, donc table vide dans
  `routes stats`. Déjà dans les limites connues du README (`:56-61`), avec la
  piste `estimated_traffic_class` non exploitée.

## 11. Coût des appels externes, par commande

Mesuré ou lu dans le code, avec ce que ça donnerait en hébergé.

| Commande | Appels externes | Mutualisable en hébergé ? |
|---|---|---|
| `ourouler routes apprendre` | **1 BRouter par sortie non encore apprise** ; 154 au premier passage (2 min 26 mesurées), 0 ensuite — idempotent par `id_sortie`. Réserve : un échec consomme un appel sans entamer `--max` (§3, C2). | BRouter est auto-hébergé : coût interne, pas de quota. En hébergé, c'est le CPU du serveur de tracé qui devient la ressource rare — 154 appels par utilisateur au premier import, à mettre en file plutôt qu'en synchrone. |
| `ourouler routes stats` | **0.** | — |
| `ourouler routes poids` | **8 BRouter** (une boucle de 40 km par direction, `NOMS_DIRECTIONS`), **à chaque invocation**, `--appliquer` ou non : consulter les poids sans les écrire coûte autant que les écrire. | L'exposition ne dépend que du **point de départ** et du profil. Deux utilisateurs de la même ville la recalculeraient à l'identique. Candidat naturel à un cache par maille de départ, au même titre que la météo (doctrine §10.1). À noter au plan de l'hébergé. |
| `ourouler calibrer` | **1 Open-Meteo archive par (jour, point arrondi à 0,05°)**, mémoïsé sur disque : 137 jours téléchargés une fois pour toutes sur la vérification réelle, 0 ensuite. Le rapport affiche `appels` et `lectures_cache`. | Le meilleur cas du sprint : la clé `(lat, lon, jour)` ne porte rien de personnel et se mutualise telle quelle. 137 appels pour le premier utilisateur, ~0 pour le suivant parti de la même ville. Très en dessous des ~10 000 appels/jour/IP du gratuit. |
| `ourouler simuler` | **0** sans `--depart` ; **2 Open-Meteo prévision** avec (un appel par modèle via `meteo_trace`). | Cache mutualisé par maille et par heure, comme `boucle`. |
| `ourouler boucle` | **jusqu'à 12 BRouter** (plafond `appels_max`, atteint dès 3 azimuts depuis `AJUSTEMENTS_MAX = 3` — c'est le D1) + **2 Open-Meteo par candidate**, soit ~6 à 10. Inchangé par rapport au sprint 2 côté météo. | Inchangé : la doctrine §10.1 a ajourné le cache mutualisé au premier sprint de l'hébergé, le client reste injectable. Rien dans ce sprint ne ferme cette porte. |
| `ourouler comparer` | **0** — *hors relecture, mais le principe (aucun appel : tout vient du cache et de `routes_connues.sqlite`) est le bon et mérite d'être conservé par la réécriture.* | — |

Rien dans ce sprint n'entrave la cible hébergée sur le plan des quotas. Les
deux points à noter au plan sont l'exposition de `routes poids` (recalculée à
chaque appel, mutualisable) et la file d'attente pour `routes apprendre`.

## 12. Points produit, pour le mainteneur

- **Les poids appris renversent le score.** `README.md:55-59` :
  « la `secondary` passe de 3,0 à 0,4 km équivalents par kilomètre ». Autrement
  dit, `routes poids --appliquer` supprime presque la pénalité de trafic sur
  les départementales, parce que le mainteneur en roule 20 %. C'est
  exactement ce que le lot devait mesurer — mais c'est aussi un basculement du
  comportement de `boucle`, opt-in, irréversible sans effacer un fichier. Deux
  questions : (a) veut-il ce basculement, ou veut-il un poids appris **plafonné
  par** le poids par défaut (apprendre à baisser, jamais à monter) ? (b) faut-il
  une commande pour revenir aux poids par défaut, ou lui dire d'effacer
  `poids_routes.json` suffit-il ? La ligne d'en-tête dit bien d'où viennent les
  poids, donc rien n'est caché — c'est un choix, pas un défaut.
- **Q8 est close, et le sprint 4 doit tenir la promesse.** L'allure Z2 (65 % de
  la FTP) n'est un défaut que jusqu'à ce que `sortie` connaisse la séance du
  jour. À inscrire comme dépendance explicite du lot « séance ↔ terrain ».
- **`routes poids` coûte 8 appels même sans `--appliquer`.** Si le mainteneur
  compte itérer sur les poids (regarder, ajuster, regarder), une option
  `--exposition-en-cache` lui éviterait 8 tracés par essai. Petite ergonomie,
  à arbitrer.
- **La colonne « connu % » est informative et le restera.** C'est sa décision
  du cadrage, elle est tenue de bout en bout et testée. Si un jour il veut
  s'en servir comme critère (« évite-moi ce que je connais par cœur »), ce
  sera un choix explicite à inscrire au contrat, pas une dérive possible du
  code actuel.
- **Deux chiffres à ne jamais citer seuls**, et le code le dit déjà partout :
  CdA et Crr pris séparément (citer la résistance totale à 27 et 35 km/h), et
  le temps simulé (c'est un temps **en mouvement**, les arrêts s'ajoutent).

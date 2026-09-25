# Relecture du lot F0 — sept lots fusionnés, avant l'API

Périmètre relu : `git diff ce1a5c7..ee5c8d0` sur la branche `ux-discovery`
(40 fichiers, ~5 000 lignes ajoutées), lots F0.1 à F0.7.
Relecture faite le 17/09/2026. `uv run pytest` : **3 772 passés, 32 ignorés**.
`uv run ruff check .` : **All checks passed**.

Ce qui suit est classé du plus grave au plus bénin. Chaque constat dit s'il a
été **vérifié** (mesuré, exécuté) ou **supposé** (lu).

---

## Bloquant

### B1 — La simplification du tracé efface des portions entières et annonce l'avoir mesuré

`src/ourouler/boucle/geometrie.py:164-170`

```python
cos_dat = math.cos(d_ap / RAYON_TERRE_M) / math.cos(dxt / RAYON_TERRE_M)
dat = math.acos(max(-1.0, min(1.0, cos_dat))) * RAYON_TERRE_M
if dat <= 0:
    return d_ap
```

`dat` sort d'un `math.acos` : il est **toujours ≥ 0**. Le cas que la garde de
la ligne 166 prétend couvrir — « si la projection perpendiculaire tombe hors du
segment » **du côté de `a`** — n'arrive donc jamais. Un point situé *en arrière*
de `a`, à moins de `distance(a, b)`, est mesuré par `abs(dxt)`, sa distance à la
**droite infinie**, au lieu de sa distance au **segment**. La ligne 168
(`dat >= d_ab`) ne rattrape que le côté `b`.

**Vérifié**, sur un segment de 1 000 m :

| point | distance réelle au segment | `_distance_segment_m` |
|---|---|---|
| 30 m derrière `a` | 30 m | **0,003 m** |
| 200 m derrière `a` | 200 m | **0,02 m** |
| 40 m de côté, au milieu | 40 m | 39,9 m (correct) |
| 300 m au-delà de `b` | 300 m | 299,7 m (correct) |

**Conséquence produit, vérifiée.** Boucle synthétique 1 500 × 1 200 m avec une
impasse de 150 m juste après le départ (le cas banal : on sort de chez soi, on
descend une voie sans issue, on fait demi-tour), 571 points échantillonnés à
10 m, tolérance par défaut 5 m :

```
points rendus                          : 5
simplification.ecart_max_m annoncé     : 0,05 m
écart réel, mesuré indépendamment      : 150,0 m
```

L'impasse a **entièrement disparu** de `points` et de `profil`. Pour qui
consomme l'API : la carte dessine une route que le cycliste n'a pas roulée,
plus courte que le `distance_km` du même objet JSON ; et dans `sortie --json`,
un bloc dont `debut_m` tombe dans le morceau effacé se place n'importe où par
la recherche dichotomique que la docstring du module recommande explicitement
(`geometrie.py`, docstring « Les blocs »).

C'est une violation de la **règle absolue 5** et pas seulement un bug :
`simplification.ecart_max_m` est présenté par le module comme la mesure qui
remplace la garantie théorique de Douglas-Peucker (« `geometrie_json` mesure
l'écart réellement introduit […] plutôt que de se fier seulement à la garantie
théorique »). Cette mesure est la sortie de la fonction fausse. Le chiffre du
message de commit `ba777f2` — « écart réel maximal 4,88-4,98 m » sur données
réelles — vient de la même fonction : il ne prouve rien.

*Correction, en une phrase* : rendre `dat` signé (ou tester le signe de
`cos(brg_ap − brg_ab)` et rendre `d_ap` quand il est négatif), et donner au cas
« en arrière de `a` » le test qu'il n'a pas.

### B2 — Le test censé vérifier B1 indépendamment se vérifie lui-même

`tests/test_boucle_geometrie.py:66-83`

`test_ecart_mesure_est_reellement_borne_par_la_tolerance` annonce dans sa
docstring : « Pas seulement “l'algorithme le garantit” : on mesure, comme
demande la règle absolue 5. Le point le plus proche du tracé simplifié est
cherché par **force brute, indépendamment de l'implémentation** de
`simplifier`. » Il appelle `_distance_segment_m`, c'est-à-dire exactement la
fonction fautive. Il passerait sur le tracé de B1, dont un tiers a disparu.

`tests/test_boucle_geometrie.py:153-157`,
`test_distance_segment_hors_segment_retombe_sur_le_bout_le_plus_proche`, ne
teste que le point **au-delà de `b`** : le seul des deux côtés qui fonctionne.
Le nom du test promet les deux.

C'est le cas d'école du test qui ne mord pas : il rend le calcul faux plus
crédible, pas moins.

---

## À corriger

### C1 — Les lecteurs `.ZWO` et `.MRC` (683 lignes) n'ont aucun appelant

`src/ourouler/seance/zwo.py` (403 l.), `src/ourouler/seance/mrc.py` (280 l.)

**Vérifié** : `grep` sur tout `src/` — zéro import de `zwo` ou de `mrc` hors de
ces deux fichiers. Aucune sous-commande, aucune option, rien dans `cli.py` ne
permet de déposer un fichier de séance. Le trou nommé dans
`docs/journal/ux/front_contrat.md` était « l'**import** de séance » : il n'est pas
comblé, c'est le lecteur qui existe, pas l'import.

F0.5 a honnêtement déclaré n'avoir aucune donnée réelle (règle 4). Le cumul
est ce qui pose problème : 683 lignes vérifiées ni par un utilisateur, ni par
une donnée réelle, ni par un chemin d'exécution. Pour F1 cela veut dire écrire
le point d'entrée **et** la vérification sur vraies données, pas seulement
brancher une route.

### C2 — `facteur_compteur` est un réglage que rien ne lit

`src/ourouler/config.py:97` et `:869` (le champ et sa validation),
`src/ourouler/physique/modele.py:393` (`moyenne_compteur_kmh`),
`config.example.toml:23-28` (l'invitation à le renseigner).

**Vérifié** : `moyenne_compteur_kmh` n'est appelée nulle part dans `src/`, et
`facteur_compteur` n'est lu par aucun module hors de `config.py`. La ligne
« Zones » ajoutée à `ourouler config` (`cli.py:308-313`) montre la position
dans la bande, pas le facteur.

Conséquence concrète : quelqu'un suit `config.example.toml`, écrit
`facteur_compteur = 0.85`, ne voit rien changer nulle part, et n'a aucun moyen
de savoir si sa valeur a seulement été lue. Un réglage qui ne fait rien est
pire qu'un réglage absent — il donne l'impression d'avoir agi.

F0.6 n'annonce pas cette dette dans son message de commit : elle est
implicite (« la troisième valeur de l'écran de FTP », écran qui est en F2).
Elle devrait être écrite : au minimum une ligne dans `ourouler config`, ou une
mention « pas encore utilisé » dans `config.example.toml`.

### C3 — La migration `puissance_endurance_pct → position_zone` peut produire une valeur que le chargeur refuse

`src/ourouler/config.py:661-670`, docstring `:653-655`

La docstring affirme : « Les bornes de lecture de l'ancienne clé sont
inchangées ([0,40 ; 0,80]) […] Les positions correspondantes tiennent dans
[−1 ; 2], d'où ces bornes-là côté position. » C'est vrai **pour la table de
Coggan seulement** — or `zones` est devenue configurable dans le même lot.

**Vérifié** :

```
zones = [[0.0,0.55],[0.70,0.72],[0.73,0.90],[0.91,1.05]]
puissance_endurance_pct = 0.40
→ charge sans un mot,      position_zone = -15.0
→ rechargement de la même valeur : REFUSÉ, « hors de [-1.0, 2.0] »
```

Pour l'API c'est directement gênant : la route qui écrit le profil produira
une position que la route qui le relit refusera. Le chemin ancienne-clé doit
passer par la même borne que le chemin `position_zone`, ou refuser la
conversion en nommant la table.

### C4 — Le trou de test qui avait laissé passer la collision F0.3 × F0.4 est toujours là

`tests/test_seance_intervals.py:991-1070`, `tests/test_seance_commande.py:448-525`

Le commit de correction `a2c7990` dit lui-même : « Trouvé par ruff (F821) et
non par les tests : **aucun test ne couvrait la plage avec une table de zones
personnalisée**. » **Vérifié** : aucun n'a été ajouté. Tous les appels à
`seances_periode` dans les tests omettent `zones_puissance=`, et les six tests
de plage de `test_seance_commande.py` utilisent la configuration par défaut.

La prochaine divergence entre le chemin mono-jour et le chemin plage ne sera
pas vue par les tests. Elle ne sera vue par `ruff` que si elle produit un nom
indéfini — ce qui, cette fois, était un coup de chance : passer la mauvaise
table (au lieu de l'oublier) est silencieux.

### C5 — `cli.py` importe `httpx` au démarrage, contre sa propre convention

`src/ourouler/cli.py:18`

Le fichier importe `ourouler.connecteurs.geocodage` au niveau module, alors que
toutes les autres sous-commandes passent par un import paresseux commenté
(« import paresseux (lot L1.5) », lignes 359, 403, 642, 655…).

**Mesuré** (`python -X importtime -c "import ourouler.cli"`) :

```
ourouler.cli                     50,2 ms cumulés
  ourouler.connecteurs.geocodage 33,9 ms   dont httpx 33,4 ms
  ourouler.config                12,7 ms
```

Les deux tiers du budget d'import, payés par `ourouler --help` comme par
`ourouler inventaire`. `lieu_depart` et `LIMITE_DEFAUT` peuvent se charger dans
la fonction, comme le reste.

---

## Mineur

### M1 — L'invariant AST de F0.7 mord, mais ne couvre que trois paquets

`tests/test_invariants.py:83-105`

**Vérifié qu'il mord** : en ajoutant
`from ourouler.connecteurs.geocodage import chercher_adresse` à
`src/ourouler/meteo/couronne.py`, le test échoue bien
(`test_le_coeur_ne_geocode_jamais_lui_meme[meteo]`). Restauré depuis.

Mais `PAQUETS_DE_COMMANDE = ("meteo", "boucle", "sortie")` est une liste en
dur : `seance/`, `activites/`, `apprentissage/`, `physique/`, `connecteurs/`
ne sont pas couverts, et un paquet créé demain ne le sera pas non plus. Les
deux invariants voisins (`test_le_coeur_ne_lit_pas_son_environnement`,
`test_le_coeur_n_importe_pas_tomllib`) sont bâtis à l'inverse : tout
`src/ourouler/` **sauf** une liste d'exceptions. Celui-ci devrait l'être aussi
(exceptions : `cli.py` et le paquet `geocodage/`).

*Au passage, pré-existant* : `AUTORISES = {"cli.py", "config.py"}`
(`tests/test_invariants.py:42`) filtre par **nom de fichier**, pas par chemin.
Un futur `src/ourouler/boucle/config.py` serait exempté de la règle 2 sans que
personne le voie.

### M2 — `seance --depuis/--jusqua` n'a aucune borne de largeur

`src/ourouler/seance/commande.py:179-206`

`--depuis 2020-01-01 --jusqua 2030-01-01` construit un dict de 3 653 entrées et
sérialise 3 653 séances. Sur la ligne de commande c'est le problème de celui
qui tape. Sur l'API, ce sera une requête non bornée servie par le serveur du
mainteneur : à border dans la forme de la requête, pas après.

### M3 — `--max` du géocodeur n'est ni borné ni validé

`src/ourouler/geocodage/commande.py:35` :
`limite = getattr(args, "max", None) or LIMITE_DEFAUT`

`--max 10000` est transmis tel quel aux deux services ; `--max -3` aussi (`-3`
est vrai au sens booléen). La politique d'usage de Nominatim, citée dans la
docstring du connecteur, interdit les requêtes systématiques et plafonne à 40.

### M4 — Petite asymétrie de filtrage entre le mono-jour et la plage

`src/ourouler/seance/intervals.py:242-250` contre `:185`

`seances_periode` regroupe les événements sur leur `start_date_local` et jette
ceux qui tombent hors de la plage ; `seance_du_jour` ne filtre rien et garde ce
que l'API a rendu pour `oldest=newest=jour`. Un événement dont le
`start_date_local` ne correspond pas à la fenêtre demandée est donc gardé par
l'un et jeté par l'autre. Le comportement mono-jour est pré-existant, mais les
deux chemins ne rendent plus tout à fait la même chose, ce que le commit F0.3
affirme (« exactement la forme du JSON de `seance --jour` »).

### M5 — `facteur_compteur_defaut` ne modélise pas le vent, alors que le facteur mesuré l'inclut

`src/ourouler/physique/modele.py:296-308` (l'en-tête) et `:330-390`

L'en-tête du bloc dit « le relief, le vent et les arrêts sont mélangés dans un
seul nombre » et « le vent coûtant plus cher que les arrêts ». La dérivation du
défaut, elle, ne prend que le relief (alternance symétrique) et une convention
d'arrêts à 5 %. Le défaut est donc **structurellement optimiste**, et pas
seulement incertain. **Vérifié** sur des paramètres plausibles (78 kg, CdA
0,32, Crr 0,005) : défaut 0,861 à 150 W, 0,874 à 170 W — au-dessus de la
mesure rétrospective annoncée. Le mot « supposition » est juste ; l'écran
devrait pouvoir dire *dans quel sens* elle se trompe.

### M6 — Les tests du facteur ne pinceraient pas une erreur d'échelle sur la pente

`tests/test_physique_modele.py:372-415`

Les tests vérifient la monotonie avec le dénivelé, la multiplicativité exacte
de `part_arret`, le cas plat = 1, la dépendance à la masse. Toutes ces
propriétés survivent intactes à `pente = denivele_m_par_km / 1000` au lieu de
`/ 500` : le facteur resterait décroissant, inférieur à 1, et sensible à la
masse. Rien ne fixe une valeur numérique contre un calcul indépendant.

J'ai revérifié à la main que `/ 500` est le bon facteur (10 m de montée par km
parcouru, dont la moitié seulement grimpe → 2 %). Il est correct ; il n'est
pas protégé. C'est la moitié de ce que la consigne appelait « un chiffre
plausible qui masque un calcul faux » : ici le chiffre est juste, mais rien ne
le tient.

---

## Ce qui tient

Sans arrondir les angles, il y a du solide, et il n'est pas réparti
uniformément.

**F0.4 est le meilleur des sept lots.** La décision 7 est appliquée jusqu'au
bout : une seule donnée stockée, `puissance_endurance_pct` devenue propriété
dérivée, plus deux définitions de « la Z2 » qui puissent diverger. Le choix de
`POSITION_ENDURANCE_DEFAUT` — la position qu'occupe la mesure de Q11, et non
un chiffre rond — est exactement ce que la règle 5 demande. Le traitement des
zones **ouvertes** (première et dernière, critère positionnel et non « Z1 et
Z7 ») est le genre de détail qu'on ne voit qu'en y ayant pensé. Le refus
d'écrêter une position hors de [0, 1] est délibéré, documenté et testé
(`test_seance_zones.py:121`).

**La claim « `seance --json` identique octet pour octet » se vérifie.**
`position_endurance(0.60)` = 0,21052631578947367, et
`puissance_endurance_pct` de cette position rend exactement `0.6` grâce à
l'arrondi à `DECIMALES_PCT = 6` — `0.6000000000000001` aurait suffi à faire
diverger un JSON. Le mécanisme est réfléchi, pas heureux. Le seul écart
observable est bien additif (deux champs de plus dans `config --json`).

**F0.3 est propre et modeste.** Une seule requête HTTP pour toute la plage,
testée pour ça (`test_plage_un_seul_appel_reseau`). Le regroupement sur
`start_date_local` sans reconversion UTC est le bon choix et il est justifié.
La distinction jour vide (`seance: null`) / jour hors plage (absent) est
exactement ce dont une API a besoin.

**Q34 est la meilleure page de doc du lot.** Mesurer que deux candidats
peuvent être séparés de 0,0001 de score et de 400 km, constater qu'aucun seuil
ne se déduit de quatre mesures, et **poser la question au lieu de poser un
chiffre**, c'est la règle 5 appliquée à une décision produit. Le fait que les
requêtes ne soient pas recopiées dans le dépôt est cohérent jusqu'au bout.

**La règle 1 est tenue.** Vérifié sur l'intégralité du diff : aucune
coordonnée réelle, aucune FTP, aucune masse, aucune clé, aucun jeton, ni dans
le code, ni dans les fixtures, ni dans les exemples, ni dans les messages de
commit. Les fixtures de géocodage sont entièrement inventées (« Vallombreuse »,
« Hautbocage », coordonnées autour de 0,12/0,23), et le README déclare ses
adresses comme inventées au lieu de laisser le doute.

**La règle 3 est tenue.** Les nouveaux tests injectent tous leur client ;
l'invariant `test_aucun_test_ne_cree_un_client_http_sans_transport_bouchonne`
les couvre. Aucun test ne sort sur le réseau.

**F0.7 a fait le bon choix d'architecture.** Substituer le `Depart` dans la
`Config` par `replace` plutôt que de le faire descendre de fonction en fonction
est le choix que je recommanderais : une seule ligne à ne pas oublier au lieu
de vingt. J'ai cherché ce que ça casse — un cache mémoïsé sur une clé qui
ignorerait le point de départ — et je n'ai rien trouvé : les seuls états
persistants (`routes.sqlite`, `poids_routes.json`) n'entrent dans aucun score,
et la commande le dit à l'utilisateur quand la base existe. C'est vérifié par
lecture, pas par exécution.

**L'invariant AST mord vraiment** (M1 : vérifié en le cassant). C'est plus que
ce qu'on peut dire de la plupart des tests d'invariant.

---

## Prêt pour l'API ?

**Non en l'état — mais le bloquant est étroit : une fonction.**

B1 porte sur la seule chose que F0 devait livrer et que l'API ne peut pas
contourner : la géométrie du tracé. Poser une route HTTP sur `geometrie_json`
aujourd'hui, c'est publier un contrat qui rend une carte fausse dans un cas
banal (impasse, aller-retour, demi-tour — c'est-à-dire dans un `sortie` sur
deux) **et** qui affirme dans le même objet JSON avoir mesuré que l'écart est
sous 5 cm. Un front n'a aucun moyen de s'en apercevoir. Une fois la route
publiée, c'est une donnée de plus qu'on ne peut plus retirer.

Ce qu'il faut avant F1, dans l'ordre :

1. **B1** — corriger `_distance_segment_m` (le cas « en arrière de `a` »).
2. **B2** — réécrire le test d'écart avec une distance point-segment
   indépendante (une projection plane locale suffit à cette échelle), et
   ajouter le cas manquant à `test_distance_segment_hors_segment…`. Sans ce
   pas, la correction de B1 n'est pas gardée.
3. **C3** — la migration ne doit pas produire une valeur que le chargeur
   refuse. C'est une demi-heure, et c'est un aller-retour d'API.

Le reste peut suivre F1, à **une condition** : que C1 (`.ZWO`/`.MRC` sans
appelant) et C2 (`facteur_compteur` sans lecteur) soient écrits quelque part
comme **non livrés**, et non comptés comme des trous comblés. Aujourd'hui
`front_contrat.md` laisse entendre que les cinq trous de F0 sont bouchés ; deux
ne le sont qu'à moitié, et c'est la moitié invisible — celle du chemin
d'exécution — qui manque.

C4 et C5 sont de la dette assumable : C4 est un trou de test connu et écrit,
C5 est trente millisecondes. Ni l'un ni l'autre ne doit retarder F1.

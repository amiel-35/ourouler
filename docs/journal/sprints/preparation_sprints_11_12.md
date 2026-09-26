# Préparation des sprints 11 et 12 — proposition au mainteneur

Écrit le 25/09/2026 par l'agent superviseur, en lecture seule du code. C'est
une **proposition**, pas une décision : rien n'est figé tant que le mainteneur
n'a pas répondu aux questions du §5. Les questions produit y restent ouvertes ;
seul le séquencement technique est argumenté ici.

Sources lues : backlog et clôtures de `docs/journal/sprints/plan_sprints_agents.md`,
questions ouvertes de `docs/journal/questions/questions_mainteneur.md`,
`docs/ouverture_plan.md` (§0, §5, §6), `CHANGELOG.md`, les consignes locales du
mainteneur (cadence : deux sprints figés, un esquissé), et les trois branches
garées `analyser-parcours`, `q67-sans-brut` et `backlog-admin`.


## Décisions du mainteneur (25/09/2026)

| Question | Décision |
|---|---|
| QP1 cadence | **(c) toute la restructuration d'abord** (lots 3 à 14), les fonctionnalités ensuite. Le découpage en deux pistes du §3 ne s'applique donc pas ; il sert d'ordre de reprise une fois la restructuration finie. |
| QP2 `analyser-parcours` | (a) rebaser et merger **avant le lot 3** |
| QP3 heure du jour | (a) le jour même, l'heure courante arrondie au quart d'heure suivant (9 h un autre jour), affichée et modifiable en un geste |
| QP4 trois boucles | (c) relancer « Chercher plus loin » d'office jusqu'à trois boucles retenues |
| QP5 consentement | (a) minimal, refus par défaut, « entraîner le modèle » nommé mais sans usage |
| QP6 administration | (c) jamais exposée : locale au serveur, par tunnel SSH |
| QP7 calibration | (a) afficher l'erreur de validation et le nombre de sorties, et « provisoire » sous un seuil |
| QP8 import par lien | (c) puis (b) : mesurer sur une vraie archive, puis détecter un historique tronqué |

**Conséquence de QP1** : pendant la restructuration, seuls passent la
branche `analyser-parcours` (un merge, avant le lot 3) et les **correctifs
de défauts vus en prod**, en patch `0.9.x`. B2, l'heure du jour, est un
défaut constaté en prod : proposé en correctif, selon QP3.

## 0. Hypothèses de départ

- Le sprint 10 (ouverture) est **gelé côté fonctionnalités** ; les
  correctifs de prod partent en patch. Les lots 3 à 14 (`ouverture_plan.md`
  §6) viennent après, et **ne changent aucun comportement** : références,
  `openapi.json` et P3 identiques.
- D'où la règle de collision qui guide ce document. Une fonctionnalité
  **mergée avant** le début d'un lot est absorbée par lui (bon marché, si
  elle arrive avec ses sorties de référence 0b) ; **mergée après**, elle
  s'écrit dans la nouvelle structure (bon marché aussi) ; développée
  **pendant** le lot qui déplace ses modules, elle coûte un rebasage sur des
  fichiers éclatés et des références régénérées au milieu d'un lot qui les
  veut fixes : **on l'interdit**.
- Une PR de fonctionnalité qui régénère une référence (`--regenerer-golden`)
  est un changement de comportement : jamais mergée pendant un lot ouvert
  sur le même scénario, les deux passent **en série**.

### Carte des collisions : quel lot déplace quel module

| Lot | Modules déplacés ou réécrits |
|---|---|
| 3 | `boucle/trace.py`, `activites/modele.py`, `erreurs.py`, `proprietaire.py` → `noyau/` (avec réexports) |
| 4 | types de `meteo/`, `seance/modele.py`, `seance/zones.py`, profil → `noyau/` |
| 5 | `api/vues.py`, `cli.py` (profil_json) ; `api/comptes.py`, `invitation_commande.py`, `retrait_commande.py` → `services/comptes` |
| 6 | rendu de `sortie/commande.py`, `boucle/commande.py`, `physique/commande.py` → `rendu/` |
| 7 | chemin de `calibration.json` → `stockage/calibrations` ; `config.cache` côté domaine |
| 8 | `physique/calibration.py` coupé en calcul pur et `services/calibrer` |
| 9 | `connecteurs/brouter.py`, `boucle/candidates.py` (`generer`) |
| 10 | argparse hors de tous les `commande.py` ; `cli.py` construit la `Demande` |
| 11 | `api/adaptateur.py`, `api/routes.py` (plus de `Namespace` ni de capture stdout) — **risque élevé**, double chemin une semaine |
| 12 | fonctions longues : `sortie/carte.py`, `api/application.py`, `boucle/candidates.py`, `sortie/commande.py` |
| 13 | `api/routes.py` scindé par domaine |
| 14 | front : `api/client.ts`, types contre openapi, `App.tsx` découpé |

Ne sont déplacés par aucun lot : `sortie/contraste.py`, `seance/intervals.py`,
`activites/import_archive.py`, `api/imports_fond.py`, `api/taches_fond.py`,
`api/vie_privee.py` et les écrans du front, sauf `App.tsx`. Ils sont touchés
à la marge par les lots 5, 7 et 11.

## 1. Inventaire du backlog ouvert

Taille : S tient en un lot d'une session ; M, deux à trois sessions avec
relecture ; L, un lot qui occupe la moitié d'un sprint ou plus.

| # | Sujet | Valeur pour le cycliste | Taille | Modules touchés | Lot qui les déplace → placement | Question produit bloquante |
|---|---|---|---|---|---|---|
| B1 | Analyser un parcours déjà en main (branche `analyser-parcours`) | La météo, le vent et la durée d'un brevet ou d'une boucle de club qu'il a déjà. | M (codé) | `physique/commande.py` (+396), `api/routes.py`, `cli.py`, `boucle/gpx.py`, `meteo_trace.py`, `App.tsx`, nouvel écran | 6, 10, 11, 13, 14 → **avant le lot 6**, sinon après le 11 | aucune, décisions déjà prises dans la branche |
| B2 | La séance du jour part à 9 h, quelle que soit l'heure | Météo, tenue et placement calculés pour l'heure où il part vraiment. | S | `front/src/ecrans/Demander.tsx`, `App.tsx` ; `seance/intervals.py` si l'heure Intervals est lue | 14 (front), aucun côté cœur → **n'importe quand avant le lot 14** | choix du défaut (QP3), pas de Qnn |
| B3 | Le modèle arbitre trop : une seule boucle retenue sur trois | Plusieurs vraies propositions, et c'est lui qui choisit. | S–M | `sortie/contraste.py`, `config.py`, `sortie/commande.py`, front si « chercher plus loin » d'office | 6, 10, 12 (`sortie/commande`) → **avant le lot 6** | quelle piste (QP4), pas de Qnn |
| B4 | Partage direct du GPX vers l'application du compteur (Web Share API) | Le parcours arrive sur le compteur sans le détour « télécharger, puis ouvrir avec ». | S | `Boucles.tsx`, `Propositions.tsx` | 14 → **avant le lot 14** | aucune ; Wahoo cloud à part, il faut un accès développeur |
| B5 | Le cycliste choisit ce qu'on garde de ses données (consentement) | Il décide, et peut revenir sur sa décision, de ce qui est gardé de ses sorties. | L | `activites/cache.py`, `import_archive.py`, `api/vie_privee.py`, `api/imports_fond.py`, `api/comptes.py` + migration Postgres, `Reglages.tsx`, `DepotHistorique.tsx` | 5, 7, 8, 11 → **après les lots 7 et 8** | oui : périmètre d'« entraîner », défaut, retrait (QP5). Rouvre [[Q48]] et [[Q67]] |
| B6 | Aucun fichier brut gardé en hébergé (branche `q67-sans-brut`) | Ses traces GPS ne dorment pas sur le serveur, ce qui est la promesse de [[Q48]]. | L (codé) | `activites/cache.py`, `physique/calibration.py`, `physique/modele.py`, `physique/commande.py`, nouveau `physique/derive.py`, `api/taches_fond.py`, `api/routes.py` | 6, 7, 8, 11 → **après les lots 7, 8 et 6** (décision du 25/09) | [[Q67]] : la branche la tranche (option 2), `main` la dit encore ouverte ; B5 en fait le « cas refus » |
| B7 | Mini-interface d'administration (branche `backlog-admin`, doc seule) | Aucune pour le cycliste ; pour le mainteneur, inviter et supprimer sans passer par `ssh`. | M–L | nouveau module `api/admin`, `services/comptes` (lot 5), nouvelle entrée du front, `service.toml` | 5 → **après le lot 5** ; module à part, donc pas de collision avec le lot 13 | second facteur et exposition (QP6) ; surface d'attaque neuve, contre-lecture Fable sur accord |
| B8 | Import par lien Strava ou Garmin, la voie principale de [[Q48]] | Il ne fait plus transiter une archive de plusieurs centaines de Mo par son téléphone. | L | nouveau connecteur à garde SSRF, `api/imports_fond.py`, `import_archive.py`, `DepotHistorique.tsx` | aucun déplacement direct, mais **après B6** (même chaîne d'import) | [[Q62]] ouverte (export en plusieurs archives) (QP8) |
| B9 | La calibration dit son incertitude sur peu de sorties (instabilité mesurée au sprint 9 à 10 sorties) | Il sait si le chiffre de son vélo est solide ou provisoire. | S–M | `physique/calibration.py`, `CalibrationVelo.tsx` | 8 → **après le lot 8, et après B6** (qui change l'entrée de la calibration) | forme de l'affichage (QP7) |
| B10 | La calibration sur import garde les sorties de club | Un CdA appris sur ses sorties seul, pas dans les roues. | M (mesure d'abord) | `physique/calibration.py` (détection de groupe) | 8 → **après le lot 8 et B6** | non : c'est une mesure à faire avant tout code |
| B11 | Fuseau explicite passé au cœur, le vrai correctif de 0.9.4 | Une heure juste même le jour où le conteneur perd `TZ` (règle 2). | M | `meteo/commande.py`, `date.today()` et horodatages de `sortie/` et `rendu` | 4, 6, 10 → **après le lot 10** (le fuseau entre dans la `Demande`) | non, sujet technique |
| B12 | Relief demandé : plat, vallonné, qui grimpe, montagne | Une boucle au relief voulu, et un aveu honnête quand il n'existe pas à portée. | L | `boucle/candidates.py`, `seance/placement.py`, front | 9, 12 → **après le lot 9** | vocabulaire et seuils des quatre reliefs, pas encore posés en Qnn |
| B13 | Facteur compteur mesuré depuis l'écran | Une vitesse estimée tirée de son historique, plus un défaut supposé. | M | nouvelle route, `physique/`, `Reglages.tsx` | 8, 11, 13 → **après le lot 13** | [[Q54]] ouverte |
| B14 | `PATCH /profil` sur `velos` gèle la liste et masque le TOML | Le mainteneur n'est plus trompé par deux sources qui se contredisent. | S–M | `api/depots.py`, `GET /profil` | 11 → **après le lot 11** | [[Q55]] ouverte |
| B15 | Message technique quand la clé Intervals est refusée dans l'assistant d'accueil | Un invité comprend pourquoi sa clé ne passe pas. | S | front de l'assistant, `api/erreurs.py` | aucun → **patch**, hors sprint | aucune |
| B16 | Pauses et nuits, pour la randonnée au long cours | Un voyage de plusieurs jours, avec les étapes et la météo de chaque jour. | L+ | nouveau | → hors de l'horizon | à cadrer entièrement, aucune question encore posée |
| B17 | Boucle de correction des sans-capteur (fenêtre glissante) | Une estimation qui s'améliore sans capteur de puissance. | L | `physique/`, `apprentissage/` | → hors de l'horizon | bloqué par la donnée : aucune sortie sans capteur dans le dépôt |
| B18 | Qualité du tracé : [[Q29]], [[Q31]], [[Q32]] | Feux concentrés, dégagement urbain, mode circuit. | M chacun | `boucle/`, `seance/` | 9, 12 | [[Q53]] tranchée : au fil du dogfooding, sans sprint |
| B19 | Choisir entre deux jeux de littérature, et la FTP par défaut | Des temps plus justes pour un invité jamais calibré. | S–M | `physique/litterature.py`, assistant | 8 | [[Q57]] et [[Q65]] ouvertes. Leur option « attendre un deuxième cycliste » est devenue jouable, les invités sont là |

Hors backlog de fonctionnalités : [[Q58]] (routes qui ignorent le
propriétaire) **se résout au lot 11**, quand l'API cessera d'appeler les
commandes, et s'inscrit dans son critère ; [[Q56]] (`roundTripPoints`) est
une mesure technique rattachée au lot 9.

## 2. Les trois branches garées

### `analyser-parcours` (3 commits, ~1 900 lignes, base `75dcf06`)

- **État** : codée, relue (1c1c588), décisions du superviseur prises
  (3916c53), vérifiée sur vraies données (deux GPX réels, vrai Open-Meteo) et
  testée en image. Elle ajoute `ourouler analyser`, `POST /parcours/fichier`,
  `POST /parcours/analyser` et l'écran `AnalyserParcours.tsx`.
- **Ce qui la bloque** : le gel seul. `src/` n'a bougé que de ~220 lignes
  depuis sa base, et `git merge-tree` la fusionne sur `origin/main` **sans
  conflit textuel** (mesuré le 25/09). Mais elle casse le snapshot
  `openapi.json` (0c), n'a pas de sorties de référence (0b), et ses
  fonctions devront passer les seuils du lot 2.
- **Quand** : **première PR du sprint 11, avant le lot 3** ; chaque lot la
  transporte ensuite. Après le lot 11, il faudrait recoder ~400 lignes de
  `physique/commande.py` éclatées par les lots 6, 8 et 10.
- **Recoder ou rebaser** : **rebaser**, quasi gratuit aujourd'hui, plus cher
  à chaque lot. En plus : ses scénarios dans les références, `openapi.json`
  régénéré (changement de contrat additif), et ce qui dépasse les seuils du
  lot 2 découpé plutôt qu'excepté.

### `q67-sans-brut` (5 commits, ~3 200 lignes, base `79a5eb3`)

- **État** : codée, contre-lue deux fois (fbf74fd, b40d0a6), calibration
  sur dérivé identique au bit à celle sur brut, sur les FIT réels du
  mainteneur. **Pas testée en image.** Q67 y est marquée tranchée
  (option 2) ; sur `main`, elle est encore ouverte.
- **Ce qui la bloque** : la décision du 25/09 (après les lots 7 et 8) ; un
  conflit textuel dans `api/routes.py` dès aujourd'hui ; et B5, qui fait de
  la règle unique un choix par personne, dont cette branche n'est plus que
  le « cas refus ».
- **Quand** : **sprint 12, après les lots 7, 8 et la partie
  `physique/commande` du lot 6**, les trois zones qu'elle touche.
- **Recoder ou rebaser** : **recoder, guidé par la branche.** On garde ses
  tests (`tests/test_sans_brut.py`, `tests/api/test_api_sans_brut.py`)
  comme critères d'acceptation, et le calcul pur de `physique/derive.py` et
  de `simuler_profil`. On recode la sérialisation (vers `stockage/`) et le
  branchement API. Rebaser à travers trois lots qui éclatent
  `calibration.py` et `commande.py` coûterait plus cher, et brouillerait le
  découpage calcul/stockage du lot 8.
- **Vigilance** : l'index reste au schéma 3 (`derives` par
  `CREATE TABLE IF NOT EXISTS`), compatible avec 0d moyennant un fichier de
  compatibilité pour `derives`.

### `backlog-admin` (1 commit, documentation seule, base `b8c390d`)

- **État** : une entrée de backlog de 38 lignes, écrite dans l'ancien chemin
  `docs/plan_sprints_agents.md`, que #47 a déplacé dans `docs/journal/`.
- **Ce qui la bloque** : rien sur le fond ; son exemple d'adresse masquée
  cite un domaine qui semble réel, à remplacer par un domaine d'exemple.
- **Quand** : **tout de suite**, comme #36 et #41 pendant le gel ; le code
  vient au sprint 12 (B7).
- **Recoder ou rebaser** : **recopier** le texte dans
  `docs/journal/sprints/plan_sprints_agents.md`, adresse anonymisée, puis
  supprimer la branche.

## 3. Proposition de découpage

Chaque sprint porte **deux pistes** : les lots du §6, aux critères
inchangés, et des fonctionnalités placées autour des collisions (cadence
proposée en QP1 ; avec des sprints purs, seuls les ordres relatifs
changent). Critères communs à tout sujet de fonctionnalité :
- `pytest`, `ruff` et la CI verts, sans nouvelle exception au contrat
  d'imports (lot 1) ni aux règles ruff (lot 2) ;
- la commande ou l'écran **tourne sur les vraies données du mainteneur**
  (sa configuration, son Intervals, ses fichiers, hors dépôt), sinon le
  sujet est déclaré **non vérifié** en toutes lettres ;
- références complétées, toute régénération justifiée dans la PR ; image
  rejouée en préprod avant `prod` (des invités réels sont en service) ; une
  ligne dans `CHANGELOG.md`.

### Sprint 11 — figé à la réponse du mainteneur

**Objectif** : quatre gestes quotidiens du cycliste réparés ou ouverts,
sans croiser la restructuration du cœur.

**Piste restructuration** : lots 3 et 4 (Haiku, risque faible), puis lot 5
(Opus) ; le lot 7 ferme le sprint s'il reste de la place. **Ordre** : B1,
puis lots 3 et 4, puis B2, B3 et B4 **en parallèle du lot 5**, dont aucun
ne touche les modules. B3 est mergé avant que le lot 6 ne commence.

| Sujet | Critères d'acceptation mesurables |
|---|---|
| B1 — analyser un parcours (rebasage) | fusionné **avant** l'ouverture du lot 3 ; `openapi.json` régénéré, avec deux routes additives et rien d'autre ; scénarios `analyser` ajoutés aux sorties de référence et stables sur 3 passages ; `ourouler analyser` sur deux GPX réels du mainteneur, dont un en plusieurs traces, et l'écran joué en préprod |
| B2 — l'heure de départ du jour | le jour même, « Aujourd'hui » n'affiche plus 09:00 en dur, mais la règle choisie en QP3 ; l'heure est visible et modifiable en un geste ; un test du front par cas (jour même, autre jour, heure passée) ; vérifié sur la séance réelle du mainteneur à une heure d'après-midi, la tenue suivant la température de cette heure-là |
| B3 — laisser choisir | selon la piste choisie en QP4, sur les séances réelles du mainteneur rejouées : la part des demandes qui rendent 3 propositions passe de la valeur mesurée avant (à relever en début de lot) à au moins 90 % ; le coût en appels BRouter par demande est mesuré et rapporté ; une génération compte toujours une seule fois dans le quota |
| B4 — partager le GPX | sur un téléphone réel, le bouton ouvre la feuille de partage système, avec le fichier `.gpx` ; repli sur le téléchargement actuel là où `navigator.canShare({files})` est faux, garanti par un test ; un parcours réel du mainteneur arrive dans l'application de son compteur |

Pourquoi ces quatre-là : **par la valeur**, B2 est un défaut vu en prod
(tenue d'automne par forte chaleur), B3 la plainte « le modèle arbitre
trop », B1 une promesse de la vidéo déjà codée, B4 un détour de moins à
chaque sortie ; **par les collisions**, aucun n'est pris au milieu d'un lot
(B1 et B3 avant le lot 6, B2 et B4 avant le lot 14). Consentement, B6 et
calibration attendent les lots 7 et 8 : les mettre ici, c'est les écrire
deux fois.

### Sprint 12 — figé à la réponse du mainteneur

**Objectif** : le cycliste invité décide de ce qu'on garde de ses sorties,
et le mainteneur administre le service sans `ssh`.

**Piste restructuration** : lot 7 (s'il reste du sprint 11), lot 8
(contre-lecture Fable sur accord), puis la partie `physique/commande` du
lot 6 ; le lot 9 tourne en parallèle des fonctionnalités, il ne touche ni
`activites/` ni `api/`. **Ordre** : lots 7, 8 et 6 (physique) → B6+B5 →
B9 ; B7 part dès le début, en parallèle, car il ne dépend que du lot 5.

| Sujet | Critères d'acceptation mesurables |
|---|---|
| B6+B5 — choix du cycliste sur ses données, le refus étant le défaut | les tests de `q67-sans-brut` repris, et verts sur la nouvelle structure ; la question posée **au moment où les données arrivent** (après avoir branché Intervals, après un dépôt), jamais pré-cochée ; accord et refus réversibles depuis Réglages, avec une preuve horodatée en base ; en refus, **zéro fichier brut** sous le dossier du compte après un import (compté par un test et en préprod) ; un retrait d'accord efface ce qui était conservé à ce titre ; `DELETE /moi` efface brut, dérivé et preuve ; calibration sur dérivé et sur brut identiques à 1e-9 sur les FIT réels du mainteneur ; fichier de compatibilité 0d pour la table `derives` |
| B7 — mini-interface d'administration | identifiant hors de la table des comptes, défini dans `service.toml` ; aucune session de cycliste n'atteint une route d'administration, ni l'inverse, testé comme l'isolation par propriétaire ; inviter, lister (adresse masquée), supprimer avec double validation, par **le même chemin** que `ourouler inviter`/`retirer` (`services/comptes`) ; journal des actions d'administration ; exposition et second facteur selon QP6 ; joué en préprod : une invitation puis une suppression de bout en bout |
| B9 — la calibration dit son incertitude | l'écran affiche, avec le CdA, l'erreur de validation et le nombre de sorties qui la portent, sous la forme choisie en QP7 ; sur l'historique réel du mainteneur, tiré à 10, 30 et toutes les sorties, le chiffre affiché et son incertitude sont rapportés dans la PR ; aucune calibration existante n'est invalidée (format `calibration.json` relu, 0d) |

Pourquoi : B5 et B6 corrigent un écart en prod, puisque des bruts d'invités
sont conservés contre la promesse de [[Q48]]. C'est le sujet de plus grande
valeur qui reste, et il ne peut venir qu'après les lots 7 et 8. B7 est
indépendant et pèse peu dans la collision, parce qu'il vit dans un module à
lui. B9 vient après B6, puisque B6 change l'entrée de la calibration.

### Sprint 13 — esquissé, sans engagement

**Objectif indicatif** : importer par lien, et une heure juste jusque dans
le cœur. Piste restructuration : lots 10 et 11 (double chemin, une semaine en
préprod), puis 13 ; les lots 12, 14 et le retrait des réexports suivent au
sprint 14. Candidats : B8 (import par lien, après B6, [[Q62]] tranchée),
B11 (le fuseau dans la `Demande`, juste après le lot 10), B10 (mesure des
sorties de club), B12 (relief, si ses seuils sont posés). B13 et B14
attendent le lot 13.

## 4. Ce que ce découpage évite, et ce qu'il coûte

**Évité** : aucun sujet n'est développé pendant le lot qui déplace ses
modules ; B1 est rebasée tant que c'est gratuit, B6 recodée une seule fois,
sur la structure finale. **Coûté** : B1 et B3 alourdissent les références
que les lots 6 et 10 gardent identiques (des scénarios en plus, pas du
risque) ; et d'ici le sprint 12, les bruts des invités restent sur le
serveur. Si cet écart est jugé intolérable jusque-là, la seule voie qui ne
croise aucun lot est un patch minimal (purger le brut après import et
calibration) ; il n'est pas proposé, parce qu'il contredit la décision du
25/09 et ferait recoder la calibration deux fois. **Hors de ces sprints** :
B15 en patch, B16 et B17 faute de cadrage ou de données, B18 au fil du
dogfooding ([[Q53]]), B19 en attente d'une mesure sur les invités.

## 5. Questions au mainteneur pour figer les sprints 11 et 12

**QP1 — La cadence après l'ouverture.**
- (a) Chaque sprint porte deux pistes, restructuration et fonctionnalités,
  ordonnées comme au §3.
- (b) Les sprints alternent : un de restructuration pure, puis un de
  fonctionnalités.
- (c) Toute la restructuration d'abord, sur 4 à 6 sprints, puis les
  fonctionnalités.
- *Recommandation : (a).* Avec (c), aucune valeur ne sort pendant des
semaines, et les deux branches codées pourrissent. Avec (b), on regroupe les
collisions au lieu de les éviter.

**QP2 — `analyser-parcours`.**
- (a) Rebaser et merger en première PR du sprint 11, avant le lot 3 ; (b)
  la recoder après le lot 11 ; (c) l'abandonner.
- *Recommandation : (a)* : sans conflit aujourd'hui, plus cher à chaque lot.

**QP3 — L'heure de départ par défaut sur « Aujourd'hui ».**
- (a) Le jour même, l'heure courante arrondie au quart d'heure suivant (9 h
  un autre jour), affichée et modifiable en un geste.
- (b) Toujours demander l'heure avant de proposer.
- (c) L'heure de la séance planifiée dans Intervals, sinon (a).
- *Recommandation : (a) tout de suite, puis (c) si une mesure sur vos
événements réels montre que l'heure Intervals est une vraie intention.* Elle
peut aussi n'être qu'une valeur posée par défaut.

**QP4 — « Le modèle arbitre trop ».**
- (a) Rendre `seuil_recouvrement` réglable, et le relever.
- (b) Générer plus de candidates dès que la déduplication en mange.
- (c) Relancer « Chercher plus loin » d'office, jusqu'à trois retenues.
- *Recommandation : (c).* C'est la seule piste mesurée (cinq candidates en
donnent trois), et elle ne change pas la règle qui écarte deux tracés
presque identiques. Son coût en appels BRouter est à rapporter.

**QP5 — Le périmètre du consentement au sprint 12.**
- (a) Choix « conserver » ou « effacer », refus par défaut (le comportement
  de `q67-sans-brut`), preuve horodatée, retrait qui efface. « Entraîner le
  modèle » reste nommé mais **sans usage** tant qu'aucun apprentissage
  collectif n'existe.
- (b) Tout d'un coup, avec la définition de l'entraînement (priors par
  catégorie, routes apprises), l'anonymisation et le devenir d'un modèle
  déjà entraîné.
- (c) Garder la règle unique de `q67-sans-brut`, et reporter le choix.
- *Recommandation : (a).* On ne demande pas un accord pour un usage qui
n'existe pas encore. Il se redemandera, précisé, le jour où il existera.

**QP6 — L'exposition de l'interface d'administration.**
- (a) Publique sous un préfixe dédié, avec un second facteur TOTP.
- (b) Publique, avec une passkey (WebAuthn).
- (c) Jamais exposée : elle n'écoute qu'en local sur le serveur, joignable
  par tunnel SSH, avec son identifiant dédié.
- *Recommandation : (c) pour la première version.* Elle ajoute zéro surface
d'attaque au moment même où le dépôt devient public, et le passage à (a)
reste possible. Les trois fonctions proposées par le superviseur
(invitations en attente, tâches en cours, consommation du jour) sont-elles
retenues ?

**QP7 — Comment la calibration dit son incertitude.**
- (a) Afficher l'erreur de validation et le nombre de sorties à côté du
  chiffre, avec « provisoire » sous un seuil.
- (b) Relever le minimum de 10 à 20 sorties exploitables.
- (c) Une fourchette de watts à 30 km/h plutôt qu'un chiffre.
- *Recommandation : (a).* Personne n'est bloqué, et on dit ce que l'on sait :
l'instabilité à 10 sorties est une information, pas une raison de refuser.

**QP8 — Pour esquisser le sprint 13 : l'import par lien et [[Q62]].**
- (a) L'écran accepte un lien et en propose un second, facultatif.
- (b) Après import, la couverture temporelle trouvée détecte un historique
  tronqué et le dit.
- (c) Vérifier d'abord sur une vraie archive volumineuse qu'un `_2` existe.
- *Recommandation : (c) puis (b).* Une mesure avant l'écran, et un constat
qui ne dépend pas de ce que la personne a collé.

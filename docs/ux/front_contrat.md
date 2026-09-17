# Cadrage du front — ce qu'on construit, dans quel ordre

Clos le 16/09/2026, à la fin du cycle discovery et UX. Les décisions produit
sont dans `cycle_ux_contrat.md`, les écrans dans `maquettes_v1.html`, ce que
le code sait rendre dans `discovery_donnees.md`.

## Les trois choix de technique du mainteneur

**React**, et non du HTML autonome. J'avais recommandé l'inverse au motif que
ça romprait le « pas de framework » du projet. L'argument était mal posé : ce
principe protège **un mainteneur qui relit le code**, et le mainteneur a dit
qu'il ne le relit pas. Ses mots : « c'est pas toi qui... c'est pas moi qui
code mais toi, tu connais React, tes maquettes sont quasi des artefacts
React ». Les écrans dessinés sont effectivement déjà découpés en composants.

**L'API avant le front**, et non une verticale mince. Argument du mainteneur :
« l'api json ça va, pareil, du code vide ». Il a raison sur le coût — les dix
sous-commandes rendent déjà du JSON, il ne reste que cinq trous nommés.

**Les comptes après**, et c'est lui qui a changé d'avis : « les comptes ça
peut effectivement se brancher après, je te l'accorde ». Le cœur reçoit déjà
un profil en paramètre, donc rien ne sera à réécrire.

## Ce que la doctrine autorise, et ce qu'il faut y corriger

`doctrine_architecture.md:74` dit « pas de Pydantic **tant qu'il n'y a pas
d'API** ». L'API arrive : FastAPI redevient légitime. En revanche
`CLAUDE.md:49` résume en « pas de Pydantic » tout court, plus strict que la
doctrine dont il est le résumé — **à corriger dans la même livraison**.

## Les lots, dans l'ordre

### F0 — Combler les cinq trous de JSON

Aucun ne se contourne, tous sont nommés dans `discovery_donnees.md`.

| trou | ce qu'il bloque | coût |
|---|---|---|
| **La géométrie du tracé** n'est nulle part en JSON — les coordonnées ne vivent que dans le GPX et le HTML Leaflet | toute carte, donc la moitié des écrans | le plus gros |
| **Le géocodage d'une adresse** n'existe pas ; `--adresse-depart` est un nom réservé non livré — *comblé : F0.2 (connecteur BAN + Nominatim, `ourouler geocoder`) puis F0.7 (`--adresse-depart` sur `meteo`/`boucle`/`sortie`, le cœur reçoit un `Depart`)* | l'assistant, le départ ponctuel | dépendance externe à choisir |
| **Le connecteur Intervals ne lit qu'un jour** à la fois | « Ma semaine » | faible |
| **Les zones de puissance sont figées** dans `seance/modele.py`, jamais reliées à `Config` | l'écran de FTP et la décision 7 | moyen |
| **Ni `.ZWO` ni `.MRC` ne sont lus** comme une prescription — *comblé : F0.5 (les lecteurs) puis F1 (`--fichier-seance` sur `seance` et `sortie`, `seance/fichier.py`) ; F0.5 seul ne l'était qu'à moitié, voir C1 de `relecture_f0.md`* | l'import de séance | moyen, sans dépendance nouvelle |

La décision 7 se construit ici : ce qu'on stocke est **la position dans la
zone**, jamais la valeur. `puissance_endurance_pct` cesse d'être un réglage.

### F1 — L'API — *livrée le 17/09/2026, contrat dans `api_contrat.md`*

Elle expose ce que la CLI rend déjà, une route par sous-commande, plus les
écritures du profil. Isolation par propriétaire **dès maintenant** dans la
forme des requêtes, même sans comptes : c'est gratuit à écrire et impossible
à rattraper après.

Ce que la livraison a tranché, et qui n'était pas écrit ici :

- **L'API n'implémente rien** : chaque route appelle la même fonction
  `executer` que la sous-commande, avec `json=True`, et rend son JSON. Le
  prix est un verrou — la sortie standard appartient au processus — et une
  réponse `calcul_en_cours` quand deux calculs se croisent.
- **L'attente reste sur la requête** (3 à 7 s mesurées), avec un budget
  annoncé qui dit s'il vient d'une mesure de ce serveur ou d'un défaut.
- **Le TOML du mainteneur n'est jamais réécrit** : un profil modifié est une
  surcharge par propriétaire, qui préfigure la table de F3.
- **Ce qui écrit dans le cache et dure des minutes reste en ligne de
  commande** : `inventaire --synchroniser`, `routes apprendre`, `calibrer`.

### F2 — Le front React — *livré le 17/09/2026, dans `front/`*

Les vingt écrans des maquettes, moins ceux des comptes. Ce qui est à tenir et
que le prototype fixe déjà : la **méthode Strava** sur le générateur (réglages
et résultat qui cohabitent, le résultat bouge quand on touche un réglage), les
**états d'échec dessinés** pour chaque écran, et les **trois valeurs liées**
de l'écran de FTP.

Chaîne de construction : **Vite + React 18 + TypeScript**, tests **Vitest** et
Testing Library, carte **Leaflet** sur les tuiles OpenStreetMap — les mêmes
que `sortie/carte.py`, plutôt qu'un second moteur de carte dans le même
produit. Détail dans `front/README.md`.

Ce que la livraison a tranché, et qui n'était pas écrit ici :

- **L'estimation du générateur est la moyenne compteur du modèle**, prise dans
  `/profil/zones`, multipliée par la durée — et l'écran dit si le facteur de
  cette moyenne est mesuré ou supposé. La maquette laissait cette réserve
  ouverte (« pour quelqu'un qui vient d'arriver, le modèle tourne sur ses
  valeurs par défaut, et l'écran ne le dit pas encore ») ; elle est refermée.
- **Les jalons d'attente ne portent aucun résultat intermédiaire.** La
  maquette en montrait un — « Le sud-est est au sec » — qu'il aurait fallu
  inventer, puisque rien ne remonte du calcul avant sa fin. Les jalons nomment
  les étapes, un compteur de secondes réelles prouve que ça avance, et
  l'écran dit que l'avancement est indicatif.
- **La page du jour n'a pas de parcours calculé la nuit**, parce qu'aucune
  route ne le rend. Elle montre le dernier parcours réellement obtenu pour ce
  jour, retenu par le navigateur, avec **l'heure à laquelle il l'a été**.
- **Le nombre de feux et stops est retrouvé** en multipliant
  `densite_marqueurs_km` par la distance de la candidate — le JSON n'expose
  que la densité, et la maquette interdit de l'afficher telle quelle. Le
  front ne l'affiche que si le produit retombe sur un entier.
- **Un seul GPX est écrit par génération**, celui de la proposition retenue :
  le bouton « Envoyer vers mon compteur » ne s'affiche donc que là, et les
  autres propositions le disent au lieu d'envoyer le mauvais tracé.
- **L'étape d'identité de l'assistant n'a pas été écrite** : les maquettes
  l'écartent exprès (question ouverte n° 4) et l'API n'a aucun champ où la
  ranger. Question posée en Q36 de `docs/questions_mainteneur.md`.

### F3 — Les comptes

Demande d'accès modérée, Brevo, lien à usage unique, passkeys, Postgres,
isolation vérifiée. Décision 1 du contrat. Quand le mainteneur voudra
vraiment inviter quelqu'un.

## Ce qui n'est pas dans ce cadrage

- **La cible de course** (Q33) — V2, et elle est bloquée par `CDA_MIN`.
- **La boucle de vérification** — comparer ce que l'outil annonce à ce qui a
  été roulé, à partir du FIT du retour. Proposée au sprint 6, jamais tranchée.
- **Les quatre questions ouvertes** au pied de `maquettes_v1.html` : l'invité
  sans historique, la géographie qu'on dit ou non, prescription contre
  activité pour les fichiers déposés, et l'âge qui ne sert à rien.

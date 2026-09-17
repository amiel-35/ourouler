# Géocodage — décision du lot F0.2

Comble le trou nommé dans `docs/ux/front_contrat.md` (F0) et
`docs/ux/discovery_donnees.md` §4 : transformer une adresse tapée en
coordonnées n'existait nulle part dans le dépôt. `--adresse-depart` reste le
nom **réservé** (Q15, `docs/questions_mainteneur.md:511-524`) pour l'option
qui, plus tard, utilisera ce connecteur sur `meteo`/`boucle`/`sortie` — ce
lot livre le connecteur et une commande dédiée (`ourouler geocoder`) pour
l'exercer, pas encore ce branchement-là.

## Ce qui a été regardé

Trois pistes, évaluées sur les trois critères du cadrage : sans clé,
légalement utilisable, bonne en France sans être inutilisable ailleurs.

### 1. La Base Adresse Nationale (BAN)

Service officiel français. L'ancien point d'entrée
`api-adresse.data.gouv.fr` répond encore (vérifié le 16/09/2026), mais la
documentation officielle (`cartes.gouv.fr`, guide « Géocodage ») indique
qu'il est **en cours de retrait au profit de la Géoplateforme de l'IGN**,
`https://data.geopf.fr/geocodage/search` — même données, même format de
réponse. C'est ce dernier que le connecteur appelle.

- **Sans clé.** Confirmé par un appel réel (`GET /search?q=8+bd+du+port`) :
  réponse immédiate, aucune authentification.
- **Légal.** Licence Etalab 2.0 (licence ouverte), débit annoncé à **50
  requêtes/s par IP** — sans rapport avec l'usage d'un cycliste qui tape
  une adresse de temps en temps. Rien n'impose d'en-tête particulier ;
  l'usage de la BAN en attribution reste une bonne pratique, pas une
  obligation contractuelle trouvée dans la documentation consultée.
- **Qualité en France : excellente.** Donnée d'adressage officielle, au
  numéro de rue près, avec un `score` par candidat déjà normalisé entre 0
  et 1 — exactement la forme dont ce lot a besoin (plusieurs candidats
  notés, jamais un choix imposé).
- **Limite mesurée** : une adresse hors de France rend une liste **vide**,
  pas une erreur — la BAN ne connaît que le territoire national. C'est le
  point que le cadrage demandait de ne pas ignorer (« sans être
  inutilisable ailleurs »).

### 2. Nominatim (OpenStreetMap)

Service mondial, construit sur OpenStreetMap.

- **Sans clé.** Confirmé par un appel réel.
- **Légal, mais avec des obligations concrètes** (politique d'usage lue le
  16/09/2026 sur `operations.osmfoundation.org/policies/nominatim`) :
  1 requête par seconde maximum, un en-tête `User-Agent` (ou `Referer`)
  identifiant l'application est **obligatoire** — les en-têtes par défaut
  d'une bibliothèque HTTP ne suffisent pas — attribution ODbL visible, et
  interdiction explicite de l'autocomplétion et des requêtes systématiques
  (grille de points, listes exhaustives).
- **Qualité en France : correcte mais inférieure à la BAN** sur l'adressage
  précis (données contributives, pas un registre officiel) ; en
  contrepartie, c'est la seule des deux pistes qui répond **partout**.

### 3. Photon (komoot), écarté sans test approfondi

Même famille que Nominatim (indexe OpenStreetMap), hébergé gratuitement par
komoot sans clé. Écarté à ce stade : pas de gain net sur Nominatim pour ce
lot (même source de données, couverture mondiale équivalente), et
ajouter un troisième fournisseur pour un score marginal ne semblait pas
justifié tant qu'aucun besoin concret (au-delà de la France) ne s'est
présenté. À reconsidérer si Nominatim se révèle trop capricieux à l'usage.

## Ce qui est retenu

**La BAN (Géoplateforme) en fournisseur principal, Nominatim en repli
explicite quand la BAN ne rend aucun candidat.**

Raisonnement : le besoin premier est celui du mainteneur et de ses copains
cyclistes, tous français d'abord (`CLAUDE.md`) — la BAN sert ce cas avec la
meilleure précision possible, sans dépendance externe à la qualité
variable d'OSM. Mais le cadrage demande explicitement de ne pas rendre le
connecteur inutilisable pour une adresse hors de France ; comme
l'implémentation reste petite (deux clients HTTP symétriques, une fonction
d'orchestration de 8 lignes, testables indépendamment), le coût de garder
les deux a semblé inférieur au coût de fermer complètement la porte à une
adresse étrangère. C'est un jugement, pas une mesure : si Nominatim s'avère
n'avoir jamais servi en usage réel, l'enlever est un retrait d'une dizaine
de lignes, pas une réécriture.

**Le repli ne se déclenche que sur une liste vide, jamais pour masquer une
panne.** Si la BAN répond une erreur technique (service injoignable,
réponse illisible), l'erreur remonte telle quelle — Nominatim n'est pas
appelé à sa place, pour ne pas travestir une panne en « adresse
introuvable » (règle absolue 5 : ne rien affirmer sans mesure). Si
Nominatim est ensuite appelé (parce que la BAN a légitimement répondu
« rien trouvé ») et qu'il échoue à son tour, cette erreur-là remonte aussi,
sans être avalée.

## Ce que ça implique

- **Le connecteur** est `src/ourouler/connecteurs/geocodage.py` :
  `ClientBAN`, `ClientNominatim`, la fonction d'orchestration
  `chercher_adresse()`, le type `Candidat` (`label`, `latitude`,
  `longitude`, `score`, `source`, `commune`, `code_postal`) et la fonction
  `ambiguite()`. Les deux clients HTTP sont injectables ; aucun test
  n'appelle le réseau (réponses fabriquées, adresses inventées, dans
  `tests/fixtures/geocodage/`). `ClientNominatim` demande
  `addressdetails=1` : sans lui Nominatim ne rend pas la commune, et
  `ambiguite()` refuserait alors tout résultat de repli.
- **La commande** `ourouler geocoder "<adresse>" [--max N] [--json]`
  (`src/ourouler/geocodage/commande.py`) expose le connecteur sans jamais
  trancher entre les candidats — exactement la forme qu'une future route
  d'API (F1) reprendra telle quelle.
- **`--adresse-depart` était réservé à la fin de ce lot ; il a été livré par
  le lot F0.7** (17/09/2026) sur `meteo`, `boucle` et `sortie` : `cli.py`
  résout l'adresse en un `Depart` et le passe au cœur, qui ne géocode
  toujours rien.
- **Une adresse ambiguë est refusée depuis le 17/09/2026** (réponse du
  mainteneur à Q34 : « on refuse »). Ce qui est ambigu ne se mesure **pas**
  par un écart de score : `ambiguite()` refuse quand les candidats rendus ne
  désignent pas tous la même commune, ou quand le géocodeur ne rattache pas
  la réponse à une commune. La CLI affiche alors les candidats, avec leur
  commune, et sort en code 2. Le raisonnement est dans la docstring
  d'`ambiguite()`, la décision et sa mesure dans Q34.

## Ce qui reste ouvert

- **Non vérifié sur les vraies données du mainteneur** : ce lot n'a pas
  d'adresse personnelle à tester (règle absolue 1 — aucune coordonnée
  réelle dans le dépôt, y compris comme entrée d'un test manuel dont la
  trace resterait dans l'historique). Les services ont été appelés en direct
  avec des **lieux publics** (mairies, gares, préfectures), jamais avec une
  adresse du mainteneur, et seuls les chiffres sont reportés. Une
  vérification avec sa vraie adresse reste à faire par lui, localement, hors
  du dépôt.
- **Le géocodage inverse n'existe pas.** La BAN a bien un `/reverse`, le
  connecteur ne l'expose pas. Conséquence visible dans le front : une
  position relevée par le navigateur reste une coordonnée affichée en
  chiffres, sans nom de rue. À ouvrir si le nom lisible devient nécessaire —
  il ne l'est pas pour tracer une boucle.
- **`ambiguite()` dépend du nombre de candidats demandé.** Demander vingt
  candidats au lieu de cinq fait apparaître des communes lointaines et mal
  notées, donc refuse plus souvent. `cli.lieu_depart` demande toujours
  `LIMITE_DEFAUT` ; `ourouler geocoder --max` et la route d'API laissent le
  choix, et c'est assumé — ni l'un ni l'autre ne refuse quoi que ce soit.
- **La migration `api-adresse.data.gouv.fr` → `data.geopf.fr`** n'a pas de
  date de bascule ferme trouvée dans la documentation consultée ; le
  connecteur pointe déjà sur la nouvelle URL, donc n'est pas concerné si
  l'ancienne s'arrête, mais si `data.geopf.fr` change de forme de réponse
  sans préavis, ça casserait silencieusement (aucune alerte de bascule
  n'existe côté IGN à notre connaissance).
- **Photon** n'a pas été codé ni comparé en pratique à Nominatim — piste à
  rouvrir seulement si Nominatim déçoit à l'usage.
- **Aucune limite de débit explicite côté client** (ni pour la BAN ni pour
  Nominatim) : pas nécessaire tant qu'un seul utilisateur tape une adresse
  à la fois, mais si ce connecteur sert un jour plusieurs comptes en
  parallèle (l'hébergé, F3), il faudra y revenir.

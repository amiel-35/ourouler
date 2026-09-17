# L'API — contrat du lot F1

Livré le 17/09/2026. Ce que le front React consommera, et ce sur quoi il
peut compter. Les décisions produit sont dans `cycle_ux_contrat.md`, les
écrans dans `maquettes_v1.html`, ce que le cœur sait rendre dans
`discovery_donnees.md`, l'ordre des lots dans `front_contrat.md`.

Doctrine de référence, §10.2 : « L'API expose ce que la CLI sait déjà rendre
en JSON ; le front la consomme. Le front ne parle jamais directement au
cœur. »

## Ce que l'API est, et ce qu'elle n'est pas

**Elle n'implémente rien.** Chaque route construit le même
`argparse.Namespace` que la ligne de commande, appelle la **même** fonction
`executer(args, config, …)` avec `json=True`, et rend le JSON imprimé.
Aucune divergence n'est possible entre ce que le mainteneur vérifie dans son
terminal et ce que le front reçoit — c'est le point de tout le lot.

**Le prix de ce choix, assumé et mesuré.** `executer` imprime sur la sortie
standard, qui appartient au processus et non au fil d'exécution : deux
commandes simultanées se mélangeraient. Un verrou sérialise donc les
exécutions ; une requête coûteuse qui arrive pendant une autre attend jusqu'à
15 secondes, puis reçoit `calcul_en_cours` (409). Pour un service dont le
poste dominant est BRouter et Open-Meteo, sérialiser ne coûte rien de réel —
et c'est ce qui rend la durée annoncée au front honnête.

**Ce que l'API ajoute.** Les avertissements du cœur (« météo indisponible —
le placement reste valable », « second avis indisponible ») partent sur la
sortie d'erreur : un humain les lit, un front ne les voit jamais. Ils sont
capturés et rendus dans `avertissements`.

## Les deux formes de réponse

Une route qui calcule :

```json
{
  "proprietaire": "local",
  "donnees": { … le JSON exact de la commande … },
  "avertissements": ["météo indisponible (…) — le placement reste valable"],
  "duree_ms": 6851,
  "budget": {"operation": "sortie", "attendu_ms": 6851, "source": "mesure",
             "n": 3, "median_ms": 6781}
}
```

Une panne :

```json
{"erreur": {"code": "brouter_indisponible",
            "message": "BRouter : HTTP 502 sur …",
            "service": "brouter",
            "details": {}}}
```

**Toute réponse nomme le propriétaire qu'elle a servi** (ajouté le
17/09/2026). Tant qu'il n'y a qu'une identité, la rattacher implicitement
« marche » ; le jour où il y en a deux, ce défaut devient une fuite répartie
dans toutes les routes. Une réponse qui dit pour qui elle a été calculée rend
l'oubli visible, et donne au front de quoi refuser d'afficher les données de
quelqu'un d'autre. Aucune route n'en est dispensée, `/systeme/budgets`
compris : une liste d'exceptions se remplit toute seule (doctrine §10.1).

**Le code prime sur le message.** Le message vient du cœur, il est écrit pour
un humain et peut être reformulé ; le code est une valeur du contrat et ne
change pas sans changer la version de l'API.

## Les routes

| méthode | route | ce qu'elle sert |
|---|---|---|
| GET | `/api/v1/systeme` | version, capacités (Intervals, BRouter, vélos), budgets |
| GET | `/api/v1/systeme/budgets` | combien de temps chaque opération prend **ici**, et d'où vient le chiffre |
| GET | `/api/v1/profil` | le profil du cycliste, clé masquée |
| PATCH | `/api/v1/profil` | modifie départ, poids, FTP, position dans la zone, vélos, clé Intervals |
| GET | `/api/v1/profil/zones` | l'escalier des zones en watts + les trois valeurs liées |
| POST | `/api/v1/profil/zones/apercu` | recalcule les trois valeurs **sans rien stocker** |
| GET | `/api/v1/geocodage?adresse=` | **tous** les candidats, notés, **avec leur commune** — l'API ne tranche jamais |
| GET | `/api/v1/meteo` | pluie, vent, ressenti par direction et par heure |
| GET | `/api/v1/seances?depuis=&jusqua=` | la semaine (défaut : 7 jours à partir d'aujourd'hui) |
| GET | `/api/v1/seances/{jour}` | une séance, étape par étape |
| POST | `/api/v1/seances/fichier` | dépôt d'un `.ZWO`/`.MRC`, rend la séance lue et un identifiant |
| POST | `/api/v1/sorties` | la séance du jour posée sur une boucle |
| POST | `/api/v1/boucles` | une boucle libre, sans séance |
| POST | `/api/v1/simulations` | le temps d'un GPX du dépôt à puissance constante |
| GET | `/api/v1/inventaire` | les sorties par vélo et par mois (sans synchroniser) |
| GET | `/api/v1/routes/{stats\|poids}` | ce que les sorties passées ont appris |
| GET | `/api/v1/fichiers/{id}` | le GPX ou la carte d'une génération |

`/docs` sert la documentation interactive engendrée par FastAPI.

**Ce qui n'est pas exposé, et pourquoi.** `inventaire --importer` et
`--synchroniser`, `routes apprendre`, `calibrer` écrivent dans le cache du
serveur et durent des minutes. Ce sont des gestes d'administration ; aucun
écran ne les demande, et les exposer ferait de l'API une console
d'administration avant qu'elle ait des comptes.

## Le géocodage : la commune, et pourquoi l'API ne refuse pas

`GET /geocodage?adresse=` rend chaque candidat avec `label`, `latitude`,
`longitude`, `score`, `source`, **`commune`** et **`code_postal`**, plus deux
champs au niveau des données : `ambigu` (booléen) et `motif_ambiguite`
(`communes_differentes`, `commune_absente`, ou `null`).

**La commune n'est pas un ornement.** Sans elle, deux candidats se distinguent
par un `label` qui peut être identique et par un score séparé de deux
millièmes : le front n'a alors rien à montrer qui permette de choisir. Mesuré
le 17/09/2026 sur la vraie BAN — une adresse sans commune rend cinq candidats
dans cinq communes distinctes, jusqu'à 400 km d'écart.

**`ambigu` n'est pas un arbitrage.** Les candidats sont rendus quand même,
toujours, et l'API ne retire rien. C'est une information pour l'écran : redire
la commune, ou insister sur la confirmation à l'œil. C'est l'inverse de la
ligne de commande, qui refuse (Q34) — parce que personne n'y confirme un point
sur une carte.

**Les routes de parcours ne prennent pas d'adresse, et c'est déjà le cas.**
`POST /sorties` et `POST /boucles` reçoivent un `depart` en **coordonnées**
(`nom`, `latitude`, `longitude`), tranché par le front. Rien n'y géocode au vol,
et rien n'y était à changer : la décision Q34 confirme cette forme au lieu de
la modifier.

## Le propriétaire, dès maintenant

Les comptes sont F3. Ce qui s'écrit ici est la **forme** : la dépendance
`proprietaire` résout l'identité (aujourd'hui une seule, fixe,
`PROPRIETAIRE_LOCAL`), et **toute** méthode publique des dépôts la reçoit en
premier argument positionnel — l'équivalent du `WHERE proprietaire = …`
qu'aucune requête n'aura le droit d'omettre le jour où la base sera un
PostgreSQL. Un invariant de `tests/test_invariants.py` le vérifie sur l'arbre
syntaxique.

Concrètement, aujourd'hui :

- le profil d'un propriétaire est une **surcharge** JSON rangée sous
  `<cache>/api/<propriétaire>/profil.json`, appliquée par-dessus le socle du
  serveur avant validation. **Le TOML du mainteneur n'est jamais réécrit** :
  il porte ses commentaires et ses réglages fins, et la surcharge par
  propriétaire est exactement la forme de la table de demain ;
- **le socle appartient à quelqu'un, et ne se sert qu'à lui** (corrigé le
  17/09/2026). La fusion décrite ci-dessus donnait à tout propriétaire ce
  qu'il ne surchargeait pas — donc `[intervals] api_key`, `athlete_id` et
  `[depart]` : la clé et le domicile du mainteneur. Le socle du service est
  désormais déclaré comme étant le sien, et le dépôt **refuse** de le servir à
  un autre plutôt que de décider seul quelles sections sont communes. Ce
  découpage est un arbitrage produit, posé en Q35 de
  `docs/questions_mainteneur.md` et à rendre avant F3 ;
- les fichiers produits ou déposés vivent sous `<cache>/api/<propriétaire>/`
  et sont servis par un identifiant opaque. L'identifiant d'un autre
  propriétaire est **introuvable**, sans que la réponse dise s'il existe ;
- le fichier de profil, qui porte la clé Intervals, est écrit en 0600. Le
  chiffrement au repos est F3 (doctrine §10.2).

Quand F3 arrivera, seule `proprietaire.resoudre()` changera : ni les routes,
ni les dépôts, ni le cœur.

## L'attente : semi-synchrone, avec une durée mesurée

Décision 6 du cycle UX : « asynchrone ou semi-synchrone en précisant que ça
prend X secondes », et « X doit être mesuré, pas inventé ».

**Le calcul reste sur la requête.** Une file de tâches et un identifiant à
interroger auraient ajouté un état persistant, une reprise sur panne et deux
routes de plus pour un calcul de trois à sept secondes ; ce n'est pas le bon
rapport aujourd'hui, et rien dans cette API n'interdit de l'ajouter plus tard
(la réponse porterait alors un identifiant au lieu des données).

**Le front anime son attente contre un budget annoncé**, qu'il lit dans
`/systeme/budgets` avant de lancer le calcul, et il retrouve dans la réponse
`duree_ms` — ce que ça a réellement pris. Le budget dit **d'où il vient** :
`source: "defaut"` tant que ce serveur n'a rien mesuré (les chiffres viennent
alors des mesures du 16/09/2026 rapportées dans `cycle_ux_contrat.md`),
`source: "mesure"` dès la première exécution réussie, avec le nombre de
mesures et leur médiane. Un écran ne doit jamais présenter l'une pour
l'autre.

Le budget annoncé est le **maximum** des dix dernières mesures, pas leur
moyenne : une barre qui finit avant le calcul est pire qu'une barre un peu
lente.

**Ce que ce choix ne donne pas** : une progression réelle par étape (météo →
candidates → placement → mesure). Elle demanderait que le cœur rende compte
de son avancement, donc qu'il connaisse son appelant — ce que la règle
absolue 2 lui interdit. La progression du front est donc indicative, et
c'est dit.

## Les pannes, et leurs codes

| code | statut | quand |
|---|---|---|
| `requete_invalide` | 400 / 422 | option fautive, corps mal formé, champ de profil non modifiable |
| `profil_invalide` | 422 | ce que le cycliste vient d'écrire ne fait pas une configuration valide |
| `aucune_boucle` | 422 | le moteur a répondu, mais rien ne convient (aucune boucle bornée, ou la séance n'entre sur aucune) |
| `fichier_illisible` | 422 | `.ZWO`/`.MRC` vide, tronqué ou mal formé |
| `format_non_lu` | 422 | un `.FIT` de séance — décision 5, V1 lit `.ZWO` et `.MRC` |
| `fichier_trop_gros` | 413 | plus d'un mégaoctet |
| `fichier_introuvable` | 404 | identifiant inconnu, ou appartenant à quelqu'un d'autre |
| `route_inconnue` | 404 | aucune route à ce chemin — la liste est dans `/openapi.json` |
| `methode_refusee` | 405 | la route existe, pas avec cette méthode |
| `calcul_en_cours` | 409 | un calcul occupe déjà le serveur |
| `brouter_indisponible` | 502 | BRouter injoignable ou en erreur |
| `meteo_indisponible` | 502 | Open-Meteo injoignable ou en erreur |
| `meteo_hors_domaine` | 502 | Open-Meteo ne couvre pas ce point ou cette fenêtre (Q19) |
| `intervals_refuse` | 502 | clé révoquée ou refusée — renvoyer vers l'écran de la clé, pas vers « réessayer » |
| `intervals_indisponible` | 502 | panne côté Intervals.icu |
| `geocodage_indisponible` | 502 | BAN ou Nominatim en erreur |
| `service_externe_indisponible` | 502 | un service externe non reconnu |
| `configuration_invalide` | 500 | le TOML du serveur ne charge pas |
| `erreur_interne` | 500 | un bug — le détail reste au journal, jamais dans la réponse |

**Le classement lit le préfixe du message des connecteurs** (« BRouter : … »,
« Open-Meteo : … »). C'est une convention du cœur, et un invariant la rattache
à son code : si un connecteur changeait son préfixe, le test le dirait avant
que le front se trompe d'écran.

**Deux cas qui n'en sont pas.** Ils valent 200 :

- **« aucune séance ce jour-là »** — `donnees.seance` vaut `null`, comme la
  ligne de commande sort en 0 ;
- **« une seule proposition au lieu de trois »** — `donnees.propositions` en
  compte une ou deux, et `donnees.motif_deux_propositions` porte
  l'explication en toutes lettres. Vérifié sur les vraies données du
  mainteneur le 17/09/2026.

Une **adresse introuvable** vaut aussi 200 (les services ont répondu), avec
`donnees.candidats` vide **et** une phrase dans `avertissements` : un écran
d'échec a besoin d'une phrase, pas d'une liste vide.

## Deux écarts avec le JSON de la ligne de commande

Tout le reste est transmis tel quel.

1. **Le profil n'est pas la configuration.** `ourouler config --json` rend
   aussi le dossier de cache, l'URL du serveur BRouter et son identifiant :
   utile dans un terminal, inutile dans un navigateur, et c'est
   l'arborescence d'un serveur. L'API rend le profil du **cycliste**, plus
   une section `services` qui dit seulement si chaque service est renseigné.
2. **Un fichier est un identifiant, pas un chemin.** `gpx` et `carte` valent
   `{"id", "nom", "url"}`, et c'est la route des fichiers — qui vérifie le
   propriétaire — qui sert le contenu.

## L'écran de FTP, bout à bout

1. `GET /profil/zones` — l'escalier en watts, les trois valeurs liées, et
   `facteur_mesure` qui dit si la moyenne compteur repose sur une **mesure**
   de l'historique ou sur une **supposition** du modèle (décision 8).
2. `POST /profil/zones/apercu` avec **une** des trois entrées —
   `position_zone`, `puissance_w` ou `vitesse_a_plat_kmh`. La moyenne
   compteur n'est pas éditable : elle n'a pas de champ. La réponse porte la
   position obtenue, et `hors_bande: true` si elle sort de [0, 1] — le cas de
   qui saisit sa moyenne compteur dans le champ « à plat », qu'on **montre**
   au lieu de le corriger en silence.
3. `PATCH /profil` avec `{"seance": {"position_zone": …}}` — et c'est la
   **position** qui part, jamais les watts (décision 7).

## Lancer le serveur

```
uv sync --extra api
uv run ourouler api --port 8000            # configuration : celle de la CLI
uv run uvicorn --factory ourouler.api.application:application   # variante service
```

La fabrique de service lit `OUROULER_CONFIG` (défaut : le chemin de
`config.py`). Rien d'autre n'est lu de l'environnement, et un seul module de
l'API a le droit de le faire — `api/exploitation.py`, vérifié par invariant.

**La fabrique de bibliothèque, elle, ne lit rien** (revu le 17/09/2026).
`creer_application()` s'appelle **sans aucun argument** et rend une
application complète, qui publie son contrat sans ouvrir ni fichier ni
socket : c'est ce que la règle absolue 3 exige d'un point d'injection. Le
profil vient, au choix, d'une `Config` déjà construite (`config=`), d'un
fichier (`chemin_config=`), d'un socle (`socle=`) ou de rien — auquel cas il
se remplit par `PATCH /profil`. Les clients externes s'injectent un par un
(`client_meteo=`, `client_ban=`, `client_geocodage=`…) ; un `httpx.Client` à
transport bouchonné suffit pour la météo et le géocodage, la fabrique
l'habille du connecteur. BRouter et Intervals s'injectent entiers, parce que
leur connecteur a besoin d'une URL et d'identifiants que la fabrique ne
connaît pas.

## Mesuré le 17/09/2026, sur la configuration réelle du mainteneur

Contre le BRouter hébergé et Open-Meteo, depuis la machine du mainteneur.

| appel | durée |
|---|---|
| `GET /systeme` | 2 ms |
| `GET /profil` | 67 ms |
| `GET /profil/zones` | 3 ms |
| `GET /meteo` (8 directions × 3 couronnes) | 184 ms |
| `GET /seances` (7 jours) | 283 ms |
| `GET /geocodage` | 202 ms |
| `POST /sorties`, 2 candidates | 1,6 s |
| `POST /sorties`, 3 candidates | 2,9 s |
| `POST /sorties`, 5 candidates | 6,9 s puis 6,8 s |
| `GET /fichiers/{id}` (GPX de 65 ko) | 7 ms |

Ces chiffres recoupent la mesure du 16/09 (3,8 à 6,0 s) et la précisent : la
durée suit le nombre de candidates, qui est le vrai réglage de l'attente.
Le budget par défaut de `sortie` est posé à 6 000 ms en conséquence, et le
serveur le remplace par ses propres mesures dès la première génération.

**Limite connue** : le budget est tenu par opération, pas par nombre de
candidates. Une génération à 3 puis une à 5 nourrissent le même compteur, et
c'est le maximum qui est annoncé — prudent, donc, mais grossier. À affiner
quand le front aura fixé son nombre de candidates par défaut.

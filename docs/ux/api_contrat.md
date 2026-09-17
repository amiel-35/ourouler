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
capturés et rendus dans `avertissements`, **chacun avec son code** (voir
« Les avertissements » plus bas).

## Les deux formes de réponse

Une route qui calcule :

```json
{
  "proprietaire": "local",
  "donnees": { … le JSON exact de la commande … },
  "avertissements": [{"code": "meteo_indisponible",
                      "message": "météo indisponible (…) — le placement reste valable"}],
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
| PATCH | `/api/v1/profil` | modifie identité (prénom, nom), départ, poids, FTP, position dans la zone, vélos, clé Intervals — le schéma de ce qu'elle accepte est engendré de `depots.CHAMPS_MODIFIABLES` |
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
| GET | `/api/v1/sorties/{generation}/propositions/{n}/gpx` | le GPX **de cette proposition-là**, fabriqué à l'appel |
| GET | `/api/v1/fichiers/{id}` | la carte d'une génération, ou un fichier déposé |

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

## Le GPX : aucun à la génération, un au choix — Q40 (g), 17/09/2026

> « oui, j'ai vu, et c'est con. Pourquoi ? Si c'est le coût de stockage et de
> création, je propose d'en faire aucun et de le faire à la demande quand
> l'user choisit son parcours. »

`POST /sorties` **n'écrit plus aucun GPX**. `donnees.gpx` vaut donc toujours
`null`, et **chaque proposition** porte à la place :

```json
{"numero": 2, "distinction": "passe au large de l'averse de 11 h",
 "gpx": {"nom": "sortie_20260918_n2.gpx",
         "url": "/api/v1/sorties/<generation>/propositions/2/gpx"}}
```

`donnees.generation` nomme la génération au premier niveau, pour qu'un écran
la garde sans relire les propositions.

**Pourquoi ni une ni trois.** Une seule était un **défaut** : les trois
propositions sont contrastées exprès, et choisir « la plus sèche » puis
l'envoyer au compteur envoyait la trace de « la plus calme » — l'erreur ne se
voyait qu'une fois dehors. Trois était du **gaspillage** : deux jetées à
chaque génération.

**Ce que la route rend est le fichier lui-même** (`application/gpx+xml`, avec
son `Content-Disposition`), pas une fiche à re-télécharger : rien n'est écrit
sur le disque, même au moment du choix. Vérifié le 17/09/2026 sur la
configuration réelle du mainteneur — aucun `.gpx` n'apparaît dans le cache,
ni après la génération, ni après les téléchargements.

**Une génération oubliée est un 404 nommé.** Les GPX vivent dans la mémoire du
processus, bornée aux vingt dernières générations (`depots.GENERATIONS_GARDEES`,
~4 Mo au plafond). Au-delà, ou après un redémarrage, la route rend
`generation_introuvable` : l'écran redemande une recherche, ce qui prend cinq
secondes. Les tenir sur le disque coûterait exactement ce que la décision
voulait éviter, puisque la géométrie d'une trace pèse ce que pèse son GPX.

**La ligne de commande ne change pas.** `ourouler sortie` écrit toujours le
GPX de la proposition retenue, à `--sortie` ou au nom daté par défaut : c'est
l'appelant qui décide, par `recueil_gpx=`, si le cœur écrit un fichier ou lui
remet les trois textes (voir `sortie/commande.executer`).

## Une date lointaine ne se refuse pas — Q40 (a) et (b), 17/09/2026

> « pour le jusqu'à quand : aucune limite. Juste, si on demande trop loin, ben
> pas de météo. »

Avant, une date hors de portée partait jusqu'à Open-Meteo, qui rendait un bloc
vide, et l'API répondait **502 `meteo_hors_domaine`** — « le service est en
panne » là où c'est la demande qui est hors de portée.

Désormais **le parcours est servi**, et la météo est déclarée absente. Les
routes de parcours portent, à côté de `modele_meteo` :

```json
"meteo_absente": {
  "jour": "2026-12-16",
  "dernier_jour_couvert": "2026-09-24",
  "message": "pas de météo pour le 16 décembre 2026 — les prévisions s'arrêtent au 24 septembre 2026"
}
```

`null` quand la météo a répondu. C'est l'état dégradé que dessine E14 ·
dégradé : la boucle reste là, et ce qui disparaît sont les affirmations qu'on
ne peut plus soutenir — `tenue`, `modele_meteo` et `candidates[].meteo`
valent `null`, et `question_vent.posee` est `false`.

**Le message dit le dernier jour couvert, jamais pourquoi.** Ça referme (b) du
même geste : Open-Meteo rend le même bloc vide pour un point hors du domaine
d'un modèle et pour une fenêtre hors de sa portée, le cœur refuse de trancher
(règle absolue 5), et côté produit la distinction ne sert à rien. Quand le
jour demandé est **dans** l'horizon et que la météo a quand même manqué
(panne), la phrase s'arrête à « pas de météo pour le … » : dire « les
prévisions s'arrêtent au … » serait faux, elles couvrent ce jour-là.

**D'où vient le chiffre.** `[meteo] horizon_jours`, 7 par défaut,
**mesuré le 17/09/2026 sur le vrai service** depuis un point français : AROME
HD rendait sa dernière valeur à J+2 (le 19/09 à 03 h), `icon_seamless` à J+7
(le 24/09 à 12 h). C'est le **modèle de repli** qui fixe la portée du produit,
d'où un réglage et non une constante — un autre `second_avis` donne un autre
horizon. Au-delà, **aucun appel n'est fait** : demander ~150 prévisions pour
récolter des blocs vides serait payer le service pour apprendre ce que la date
disait déjà.

**Le repli de Q19 n'est pas touché.** L'horizon est celui du repli précisément
pour que J+2 et J+3 gardent leur météo — vérifié le 17/09/2026 sur la
configuration réelle : `modele_meteo = {"utilise": "icon_seamless", "repli":
true}` aux deux échéances, avec tenue conseillée. E15 sert d'ailleurs une
séance à J+4 **avec** sa météo et **sans** son orientation au vent : l'horizon
du vent (`HORIZON_ORIENTATION_J`, 3 jours) est un autre horizon, plus court,
et il ne concerne que la direction.

**Le repli vaut maintenant pour `POST /boucles` aussi — 17/09/2026.** Il avait
été écrit sur le chemin de `sortie` et laissé ouvert sur celui de `boucle` :
une boucle libre demandée à J+3 perdait *toute* sa météo — pluie, vent,
ressenti, les trois colonnes — avec le message trompeur de Q19, celui qui
parle du « domaine » du modèle là où c'est sa portée temporelle qui manque.
Les deux commandes appellent le même `meteo_trace.evaluer` ; elles lui passent
désormais le même repli. `POST /boucles` porte donc `modele_meteo`
(`{utilise, repli}` ou `null`), la **même** forme que `POST /sorties` — les
champs `modele` et `second_avis` disent la configuration, `modele_meteo` dit
ce qui a répondu. Vérifié le 17/09/2026 sur la configuration réelle : une
boucle à J+3 rend sa pluie, son vent et son ressenti par `icon_seamless`, et
l'en-tête texte nomme la bascule.

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
| `generation_introuvable` | 404 | cette génération n'est plus en mémoire — relancer la recherche |
| `route_inconnue` | 404 | aucune route à ce chemin — la liste est dans `/openapi.json` |
| `methode_refusee` | 405 | la route existe, pas avec cette méthode |
| `calcul_en_cours` | 409 | un calcul occupe déjà le serveur |
| `brouter_indisponible` | 502 | BRouter injoignable ou en erreur |
| `meteo_indisponible` | 502 | Open-Meteo injoignable ou en erreur |
| `meteo_hors_domaine` | 502 | Open-Meteo ne couvre pas ce point ou cette fenêtre (Q19) — **plus jamais rendu par une route de parcours** depuis Q40 (a) |
| `intervals_refuse` | 502 | clé révoquée ou refusée — renvoyer vers l'écran de la clé, pas vers « réessayer » |
| `intervals_indisponible` | 502 | panne côté Intervals.icu |
| `geocodage_indisponible` | 502 | BAN ou Nominatim en erreur |
| `service_externe_indisponible` | 502 | un service externe non reconnu |
| `profil_absent` | 503 | l'application a été construite **sans profil** — voir « Les deux fabriques » |
| `configuration_invalide` | 500 | le TOML du serveur ne charge pas |
| `erreur_interne` | 500 | un bug — le détail reste au journal, jamais dans la réponse |

**Cette table est publiée** (ajouté le 17/09/2026). Elle est engendrée de
`api/erreurs.CODES_PANNE` — sa seule source — vers la description de
l'application et vers l'énumération du champ `erreur.code` du schéma. Un front
ne peut pas dessiner un état qu'il ne sait pas reconnaître, et deux des quatre
écrans d'échec des maquettes (« pas de météo ce matin » →
`meteo_indisponible`, « intervals.icu ne nous répond plus » →
`intervals_refuse`) n'étaient nommés nulle part dans le contrat publié : F2
devait lire le code de F1 pour les trouver.

**Une panne de service rappelle la date de son dernier succès** (ajouté le
17/09/2026), dans `erreur.details.dernier_succes`. E15 · échec en fait le cœur
de son encart : « "Plus lues depuis le 12 septembre" dit à quelqu'un ce qu'il
a manqué ; "erreur de connexion" ne dit rien. » Cette date n'est pas
déductible côté front, et le cœur ne sait pas qu'il a un appelant (règle
absolue 2) : elle est tenue par l'API, par propriétaire, dans
`<cache>/api/<propriétaire>/services.json`. Elle vaut `null` tant qu'aucun
succès n'a été enregistré — le cas d'un compte neuf, que l'écran doit savoir
distinguer d'une clé qui vient de tomber.

**Le classement lit le préfixe du message des connecteurs** (« BRouter : … »,
« Open-Meteo : … »). C'est une convention du cœur, et un invariant la rattache
à son code : si un connecteur changeait son préfixe, le test le dirait avant
que le front se trompe d'écran.

### Ce que le front nomme quand l'API n'a rien dit — 17/09/2026

Trois codes de plus, qui ne viennent **pas** du serveur et n'apparaissent
jamais dans une réponse : le front les fabrique quand il n'a rien reçu qui
soit du contrat. Ils sont ici parce qu'un écran les teste comme les autres
(`front/src/api/client.ts`).

| code | quand | statut porté |
|---|---|---|
| `serveur_injoignable` | rien n'a répondu (`fetch` jette), **ou** une réponse d'erreur sans l'enveloppe `{erreur}` — un intermédiaire a répondu à la place de l'API | 0, ou celui de l'intermédiaire |
| `delai_depasse` | la requête est partie, rien n'est revenu (30 s pour une lecture, 180 s pour `POST /sorties` et `POST /boucles`) | 0 |
| `reponse_illisible` | une réponse **acceptée** qui ne porte pas de JSON : le front servi sous `/api`, un portail qui intercepte | celui reçu |

**Le critère est le contrat, jamais le statut.** `api_contrat.md` promet du
JSON pour *toute* réponse de l'API, pannes comprises : une réponse qui ne le
porte pas ne vient donc pas de l'API. C'est ce qui permet de distinguer « le
serveur ne répond pas » de « le serveur a refusé » — un 500 de l'API porte son
enveloppe, celui du proxy de développement non.

**Ce que ça corrige.** Front lancé sans API derrière, ou avec l'API sur un
autre port : le proxy de Vite rend un `500 text/plain` au corps **vide**. Le
`fetch` réussit, l'écran affichait « le serveur a répondu 500 sans rien
expliquer » avec le code `erreur_interne` — donc sans bouton, puisque ce
code-là n'est pas réessayable. C'est le même motif que le bloquant 2 de la
relecture F2, appliqué non plus à une réponse de l'API mais à **l'absence de
réponse**.

**Aucun chemin du serveur ne sort dans un message** (corrigé le 17/09/2026).
L'API donne au cœur des chemins qu'elle a fabriqués — le `.ZWO` qu'elle vient
de ranger, le GPX qu'elle a réservé — et le cœur, qui ne sait pas d'où ils
viennent, les cite : « /var/folders/…/local/fichiers/137a….zwo : fichier
vide ». Ce n'est ni le nom que le cycliste a déposé, ni quelque chose
d'utilisable dans un navigateur, et en hébergé c'est l'arborescence du serveur
décrite à qui regarde. `erreurs.assainir` les remplace par le nom du fichier,
dans l'erreur **et** dans les avertissements.

**Une chaîne vide de sens est refusée au bord.** Les champs texte des corps de
requête et l'adresse de `/geocodage` exigent au moins une lettre ou un chiffre
(`modeles.TexteUtile`). `min_length=1` ne suffisait pas : un `jour=""`
devenait « aujourd'hui » parce qu'une chaîne vide est fausse en Python, et une
adresse d'espaces partait chez la BAN, y consommait un appel et revenait en
502 avec une phrase en anglais. Un champ à moitié effacé dans un formulaire
produit exactement ça, et E16 prévient qu'il en enverra.

**Un dépôt trop gros est refusé sur sa taille annoncée**, avant d'être lu
(`Content-Length`). La borne reste vérifiée après lecture : l'en-tête vient du
client, c'est une garde et pas une preuve.

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

## Les avertissements, et leurs codes

Ajouté le 17/09/2026, à la suite de la relecture du lot F2.

Chaque entrée de `avertissements` vaut `{code, message}`. **Le code se teste,
le message s'affiche** — exactement la règle des pannes, pour exactement la
même raison.

| code | quand |
|---|---|
| `meteo_indisponible` | Open-Meteo n'a rien rendu ; le parcours reste servi, sans pluie ni vent, et la tenue se tait (E14 · dégradé) |
| `second_avis_indisponible` | le second modèle météo n'a pas répondu — confiance « inconnu » partout |
| `adresse_introuvable` | aucun candidat pour cette adresse (E16) |
| `autre` | un avertissement que le catalogue ne nomme pas encore — à afficher tel quel, **jamais à lire pour en déduire un état** |

**Pourquoi ça n'était pas là, et ce que ça coûtait.** `avertissements` était
une liste de chaînes. Le front, qui devait dessiner le bandeau E14 « Pas de
météo », n'avait pas d'autre levier que de chercher `/m[ée]t[ée]o/i` dans la
prose du cœur — c'est-à-dire de décider d'un **état d'écran** sur un message
que ce document déclare deux sections plus haut reformulable sans préavis. Le
jour où quelqu'un écrivait « Open-Meteo injoignable », le bandeau disparaissait
en silence, et il restait un parcours servi sans pluie, sans vent **et sans la
phrase qui dit pourquoi** : pire qu'un bloc vide, que E14 interdit déjà.

Ce n'était pas une faute d'écriture du front, c'était un trou de ce contrat que
le front avait bouché comme il pouvait — **sans le dire**, ce qui est le vrai
défaut.

**Le classement lit un fragment du message du cœur**, comme celui des pannes
lit le préfixe des connecteurs, et avec le même garde-fou : un invariant de
`tests/test_invariants.py` vérifie que chaque fragment de
`erreurs.MOTIFS_AVERTISSEMENT` existe encore dans le module qui l'écrit. Une
reformulation casse un test du dépôt **avant** d'effacer un bandeau chez le
cycliste. La table est engendrée de `erreurs.CODES_AVERTISSEMENT`, sa seule
source, vers la description que publie l'application.

## Feux et stops sortent en nombre absolu

Ajouté le 17/09/2026, relecture F2 · C1. `POST /sorties` rend, sur chaque
proposition, `feux` et `stops` en **entiers**, à côté de
`densite_marqueurs_km` qui reste l'axe de contraste.

`sortie/contraste.Profil` les portait depuis le sprint 3 — « affiché tel
quel : 28 feux, 20 stops » — sans jamais être sérialisés. Le front les
retrouvait donc en multipliant la densité par la distance : le calcul était
juste, et c'était le geste que le commentaire de ce champ-là nomme comme le
piège à éviter (« une densité au kilomètre invitait à multiplier — 1,7 au km,
donc 170 sur 100 km »). Il avait en prime un défaut silencieux : la densité
étant arrondie à trois décimales, le produit sortait de sa tolérance au-delà
d'environ 100 km et **le chiffre s'effaçait sans explication**, précisément
pour qui prépare une sortie longue.

Deux lignes de JSON ont supprimé la seule arithmétique du front.

## Deux écarts avec le JSON de la ligne de commande

Tout le reste est transmis tel quel.

1. **Le profil n'est pas la configuration.** `ourouler config --json` rend
   aussi le dossier de cache, l'URL du serveur BRouter et son identifiant :
   utile dans un terminal, inutile dans un navigateur, et c'est
   l'arborescence d'un serveur. L'API rend le profil du **cycliste**, plus
   une section `services` qui dit seulement si chaque service est renseigné.
2. **Un fichier est un identifiant, pas un chemin.** `carte` vaut
   `{"id", "nom", "url"}`, et c'est la route des fichiers — qui vérifie le
   propriétaire — qui sert le contenu. `gpx`, au premier niveau, vaut
   désormais **toujours `null`** : plus aucun GPX n'est écrit à la génération
   (voir ci-dessous).

## L'écran de FTP, bout à bout

1. `GET /profil/zones` — l'escalier en watts, les trois valeurs liées, et
   `facteur_mesure` qui dit si la moyenne compteur repose sur une **mesure**
   de l'historique ou sur une **supposition** du modèle (décision 8).
   `facteur_provenance` dit la même chose en un mot (`"mesure"` ou
   `"suppose"`) : un booléen se lit quand on sait qu'il est là, un mot se lit
   quand on parcourt la réponse — et afficher une mesure et une supposition de
   la même façon est « un mensonge par mise en page » (E9).
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

**Le port 8000 n'est pas décoratif** : c'est celui que `ourouler api` prend
par défaut, et c'est celui que le proxy de développement du front va chercher
(`front/vite.config.ts`, `http://127.0.0.1:8000`, `OUROULER_API` pour en
changer). Servir l'API ailleurs sans le dire au front donne un écran « Le
serveur ne répond pas » — correct, mais évitable.

La fabrique de service lit `OUROULER_CONFIG` (défaut : le chemin de
`config.py`). Rien d'autre n'est lu de l'environnement, et un seul module de
l'API a le droit de le faire — `api/exploitation.py`, vérifié par invariant.

### Les deux fabriques, et laquelle lancer — 17/09/2026

**`ourouler.api.application:application` sert un profil. `creer_application`
n'en sert aucun.** Les deux construisent une application complète, et rien à
l'écran ne le disait : le mainteneur a lancé la seconde en croyant lancer la
première, et a obtenu un serveur qui démarrait normalement puis répondait
« configuration invalide — section [depart] manquante » sur toutes les routes
de données. La phrase reprochait à un fichier de ne pas exister alors que
personne n'avait eu l'intention d'en écrire un.

| fabrique | lit | pour qui |
|---|---|---|
| `ourouler.api.application:application` | le fichier de configuration, via `OUROULER_CONFIG` | **le service** — c'est ce que `ourouler api` lance |
| `creer_application(...)` | rien du tout | la bibliothèque et les tests : point d'injection de la règle absolue 3 |

**La fabrique de bibliothèque ne change pas**, et ne doit pas changer :
`creer_application()` s'appelle **sans aucun argument** et rend une
application qui publie son contrat sans ouvrir ni fichier ni socket. Le profil
vient, au choix, d'une `Config` déjà construite (`config=`), d'un fichier
(`chemin_config=`), d'un socle (`socle=`) ou de rien.

**Ce qui change est ce qu'elle répond quand elle n'a rien.** Les routes de
données rendent `profil_absent` (503, et non 500 : rien n'est cassé, le
service n'est pas prêt), avec une phrase qui dit qu'il n'y a **pas de
profil** — ni départ, ni vélo, ni clé — et les deux façons d'en donner un :
`PATCH /api/v1/profil`, ou lancer le serveur par la fabrique de service.
`/docs` et `/openapi.json`, eux, répondent 200 dans tous les cas.

**Et `PATCH /profil` marche enfin sur cette application-là.** Le contrôle de
propriétaire posé avant l'écriture validait le profil au passage : donner son
premier profil à une application au socle vide était refusé parce qu'elle n'en
avait pas encore. Le chemin que la documentation promettait depuis le début
n'avait jamais fonctionné.

## La convention d'injection — tranchée le 17/09/2026

**Ce qu'on injecte est un transport, jamais un connecteur.** Pour les cinq
services, `client_brouter=`, `client_meteo=`, `client_intervals=`,
`client_ban=` et `client_nominatim=` prennent un `httpx.Client` — à transport
bouchonné dans un test. La **route** l'habille du connecteur qui va avec, au
moment de l'appel, avec l'URL et les identifiants du **profil du propriétaire
de la requête**. `client_geocodage=` sert la BAN et Nominatim d'un coup, parce
que le géocodage est un service pour qui appelle et deux connecteurs ici.

**Il n'y a aucune exception par service**, et c'est le point. La règle
précédente en faisait deux : BRouter et Intervals devaient s'injecter
entiers, « parce que leur connecteur a besoin d'une URL et d'identifiants que
la fabrique ne connaît pas ». C'est exact de la *fabrique* — elle est appelée
avant toute requête — et faux de la *route*, qui a le profil sous la main.
Déplacer l'habillage de l'une à l'autre supprime le cas particulier : douze
tests de contrat échouaient sur ce seul nom d'argument, et le motif de leur
marque disait « F1 non livré » alors que F1 était livré.

Habiller à l'appel a un second effet, voulu : le connecteur est construit
**par propriétaire**, avec sa clé à lui. Une clé habillée une fois pour toutes
dans la fabrique serait celle du premier venu, servie à tous — exactement la
fuite que `depots.py` refuse déjà pour le socle (Q35).

**Un connecteur déjà construit reste accepté**, et pris tel quel : c'est ce
que fait le serveur réel quand il n'injecte rien, et ce que font les tests qui
veulent un connecteur pointé quelque part de précis. La règle se lit donc :
« un `httpx.Client` est un transport à habiller, tout le reste est déjà un
connecteur ». Elle vit en un seul endroit, `api/routes.FABRIQUES_CONNECTEUR`.

Le corollaire, pour qui écrit un test : **pour changer l'URL ou la clé d'un
service, on change le profil**, pas l'objet injecté.

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

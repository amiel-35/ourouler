# Doctrine d'architecture — ourouler (« où rouler ? »)

Nom : **ourouler** (paquet Python, commande et dépôt GitHub `amiel-35/ourouler`),
validé par le mainteneur le 13/09/2026. Ce
document fixe les choix structurants et leurs raisons. On le modifie par
décision explicite du mainteneur, jamais par dérive. `AGENTS.md` en est le
résumé opérationnel pour les agents de code, `ARCHITECTURE.md` la carte du
code tel qu'il est ; en cas de doute, c'est ce document qui fait foi. Le
besoin d'origine est dans `docs/journal/cadrage.md`.

Les passages marqués *État* disent où le code en est par rapport à une
décision écrite plus tôt ; ils ne changent pas la décision.

## 1. Principes

**Un seul mainteneur, premier utilisateur.** Amiel est seul sur ce projet et
en est le premier utilisateur. Son besoin passe avant toute généralisation :
un lot n'est fini que lorsqu'une commande tourne sur *ses* vraies données.

**Le cœur ne sait pas où il tourne.** La bibliothèque ne lit jamais un chemin
en dur, une variable d'environnement, un fichier `~/.config` : elle reçoit un
objet de configuration (point de départ, cycliste, vélos, clés) et des
connecteurs. Seules les entrées savent lire un fichier de configuration ou
l'environnement : la ligne de commande (`cli.py`, `config.py`) et, pour
l'API, `api/exploitation.py` (`tests/test_invariants.py`). Raison : le graal
à terme est un service hébergé où d'autres cyclistes se créent un compte,
renseignent leur profil et importent leurs données. On s'interdit ce qui le
rendrait impossible : un profil utilisateur est une donnée, pas une
constante. *État : ce service existe, sur invitation (§10).*

**Il y aura un front web, à terme (confirmé par le mainteneur le
12/09/2026).** La cible finale est un service hébergé avec une interface
web : compte, profil (puissance, point de départ habituel, vélos), import de
données, et les mêmes résultats que la CLI (météo par direction, boucle,
sortie du jour). D'où, dès aujourd'hui : le cœur est appelable sans fichier
ni environnement, chaque commande sait rendre du JSON, et la CLI n'est qu'un
adaptateur parmi d'autres — l'API web en sera un second, le moment venu.
Ordre imposé : d'abord la CLI qui couvre le besoin du mainteneur, ensuite
l'API, enfin le front. Ni API ni front ne s'écrivent avant que le sprint
« séance ↔ terrain » ait tourné sur ses vraies sorties. *État : cet ordre a
été suivi ; l'API (`src/ourouler/api/`) et le front (`front/`) existent, et
l'API rend le même JSON que la CLI (`ARCHITECTURE.md` §4).*

**Les données et les clés restent chez l'utilisateur.** Rien de personnel
dans le dépôt : ni fichier d'activité, ni coordonnées, ni clé d'API. Le
`.gitignore` ignore par défaut tout `.fit`/`.gpx`/`.tcx` et tout
`config*.toml` ; seules les fixtures de test nommées sont réintégrées.

**Ne rien affirmer sans mesure.** Le modèle physique est validé sur des
sorties qu'il n'a pas vues (erreur de temps par sortie, rapportée). La météo
prévue est comparée au réel après coup, par modèle. Deux modèles météo qui
divergent donnent un indice de confiance, jamais une moyenne.

**Chaque module tient debout seul.** `meteo`, `boucle`, `inventaire` sont
utilisables indépendamment, avant que la boucle séance ↔ terrain existe.
C'est aussi ce qui rend chaque lot démontrable.

**Natif et simple d'abord.** Pas de service payant obligatoire, pas de base
de données serveur, pas de file de messages. Tout tourne sur un Mac ou un
petit Linux. *État : le service hébergé a sa base PostgreSQL pour les
comptes (§10.2) ; la ligne de commande n'en a toujours pas.* Ce projet préfère 50 lignes évidentes à 20 lignes malignes.

## 2. Vue d'ensemble

```
        sources                       cœur (bibliothèque)                sorties
┌─────────────────────┐   ┌──────────────────────────────────┐   ┌──────────────────┐
│ FIT / GPX / TCX     │──▶│ lecteur unique → Activite         │   │ tableau météo    │
│ Intervals.icu (API) │──▶│ connecteurs → cache local        │   │ GPX de la boucle │
│ Open-Meteo (AROME…) │──▶│ meteo : couronne de points/heure │──▶│ résumé + tenue   │
│ BRouter/GraphHopper │──▶│ boucle : candidates, coûts       │   │ Garmin Connect   │
│ (plus tard)         │   │ physique : calibration par vélo  │   │ (plus tard)      │
└─────────────────────┘   │ sortie : séance ↔ terrain        │   └──────────────────┘
                          └──────────────────────────────────┘
```

Un seul paquet Python, `src/ourouler/`, avec des sous-modules par domaine.
La CLI (`ourouler <sous-commande>`) n'est qu'un adaptateur au-dessus ; l'API
en est un second, et le front ne parle qu'à l'API. *État : ni GraphHopper
ni Garmin Connect, dessinés ici au cadrage, ne sont branchés.*

## 3. Stack

- **Python ≥ 3.12**, `uv` + `pyproject.toml`, layout `src/`. Typage par
  annotations et `dataclasses`. **FastAPI et Pydantic ne dépassent pas
  `src/ourouler/api/`**, où Pydantic ne décrit que les corps de requête ; le
  cœur reste en dataclasses, et un `ourouler` installé sans l'extra `api`
  n'en voit rien.
- **CLI** : `argparse` (stdlib). Sortie texte lisible, `--json` quand un
  autre programme doit consommer.
- **HTTP** : `httpx`. Chaque connecteur expose une fonction qui prend un
  client injectable, pour que les tests n'appellent jamais le réseau.
- **Fichiers d'activité** : `fitdecode` (FIT), `gpxpy` (GPX), `xml.etree`
  (TCX). Un seul modèle `Activite` en sortie des trois lecteurs.
- **Cache local** : un dossier (`~/.cache/ourouler` par défaut, configurable)
  avec les fichiers bruts tels que reçus, et un index **SQLite** (stdlib)
  pour retrouver une activité par date, vélo, source. Pas d'ORM.
- **Configuration** : un fichier **TOML** (`tomllib`, stdlib) lu par les
  entrées seulement (`cli.py`, `config.py`, `api/exploitation.py`), plus
  `service.toml` pour les réglages du service hébergé ;
  `config.example.toml` et `service.example.toml` versionnés, les vrais
  fichiers ignorés.
- **Tests** : `pytest`, fixtures synthétiques ou anonymisées dans
  `tests/fixtures/`. Réseau interdit dans les tests. **Lint** : `ruff`.
- **Licence** : AGPL-3.0-or-later. Choisie le 18/09/2026 en remplacement de
  MIT, sur délégation du mainteneur (« GPL ou AGPL, m'en fous »). Raison : le
  cap est un service hébergé. La GPL ne couvre pas le logiciel qu'on expose en
  ligne sans jamais le distribuer ; l'AGPL si. MIT laisserait n'importe qui en
  faire un service fermé.

## 4. Repo et structure

```
ourouler/
├── AGENTS.md                  ← consignes pour tout agent de code
├── ARCHITECTURE.md            ← la carte du code, paquet par paquet
├── doctrine_architecture.md   ← ce document
├── config.example.toml        ← modèle du fichier du cycliste
├── service.example.toml       ← modèle des réglages du service hébergé
├── docs/                      ← documents relus ; docs/journal/ : le matériau brut
├── src/ourouler/
│   ├── cli.py, config.py      ← entrées : argparse, lecture TOML et environnement
│   ├── commandes/             ← du Namespace à la Demande, puis au rendu imprimé
│   ├── api/                   ← FastAPI, comptes, dépôts par propriétaire
│   ├── rendu/                 ← texte, JSON, carte HTML
│   ├── services/              ← cas d'usage (les autres sont dans */commande.py)
│   ├── connecteurs/, stockage/  ← adaptateurs HTTP et disque
│   ├── physique/, meteo/, boucle/, seance/, sortie/  ← le domaine
│   ├── activites/, apprentissage/, geocodage/
│   └── noyau/                 ← types partagés, bibliothèque standard seulement
├── front/                     ← l'interface web, qui ne parle qu'à l'API
├── deploiement/               ← images et compose (page du jour, API et front)
└── tests/
```

Le détail, et la règle d'imports entre ces couches, sont dans
`ARCHITECTURE.md`. Un dossier n'existe qu'à partir du lot qui le remplit :
pas de squelette vide « pour plus tard ».

## 5. Données de l'utilisateur

- **Fenêtre d'historique : à partir du 1ᵉʳ décembre 2023.** Avant, plusieurs
  vélos, roues et positions rendent la calibration non fiable. La date est un
  paramètre de configuration, pas une constante.
- **Calibration par vélo et par période.** Chaque activité est rattachée à un
  vélo (champ d'équipement Intervals, ou règle manuelle) ; les paramètres
  physiques (masse, CdA, roulement) sont estimés par vélo, et une période peut
  être scindée si la validation le demande. Depuis le 25/09/2026 (L9.1), le
  roulement d'un vélo dont le pneu (ou le `crr`) est déclaré n'est plus
  estimé mais **fixé**, et seul le CdA est cherché : les deux, laissés libres
  ensemble, se compensent sur ces données. Le CdA obtenu est un paramètre de
  compensation (capteur compris), pas une mesure physique : il ne se compare
  pas d'un capteur à l'autre.
- **Le dénominateur commun est le fichier.** Quelle que soit la source
  (Intervals, Garmin, Strava, Wahoo), le FIT/GPX/TCX brut est ce qui se lit,
  avec le même lecteur. Un connecteur ne fait que rapatrier des fichiers et
  des métadonnées.

  **Mais on ne le conserve pas — précisé le 19/09/2026 par le mainteneur**,
  parce que ce chapitre disait « on stocke le brut » là où [Q48](docs/journal/questions/questions_mainteneur.md) (17/09)
  avait décidé « on jette le brut, on garde le dérivé », et que les deux
  tournaient en même temps sans que personne l'ait voulu.

  La règle est : **on ne garde jamais ce qu'on peut redemander.**

  - **Intervals reste branché** : on relit quand on veut, donc rien à
    conserver. Le cache local (`~/.cache/ourouler`) garde bien les fichiers
    bruts, et c'est légitime — **c'est un cache, pas une archive** : il se
    remplit tout seul depuis la source, et se jette sans rien perdre.
  - **Un export déposé est un instantané** qu'on ne peut pas re-télécharger.
    On en extrait le dérivé — les mailles avec leurs tags et leurs kilomètres,
    les coefficients de calibration, quelques kilo-octets — et le brut part.
    Quand l'algorithme change vraiment, ou quand la personne a progressé, **on
    lui redemande une archive**. C'est le prix, et il est assumé : garder les
    traces pour lui permettre de revoir ses sorties ferait « un Strava bis »,
    explicitement écarté en [Q48](docs/journal/questions/questions_mainteneur.md).

  *État : le code ne suit pas encore cette règle.* L'import range chaque
  activité déposée dans le cache du propriétaire, fichier brut compris
  (`activites/import_archive.py`, `Cache.ajouter`), et la calibration depuis
  l'écran les relit. L'écart est posé au mainteneur, sans être tranché :
  [Q67](docs/journal/questions/questions_mainteneur.md).

  **Deux conséquences qui se voient dans le produit**, et qui ne sont pas des
  détails d'implémentation :

  1. **Le dérivé a un âge, et il se dit.** Quelqu'un qui a déposé un export en
     mars et qui a progressé depuis roule sur un modèle périmé. Le produit doit
     le montrer plutôt que de laisser croire qu'il est à jour — « ne rien
     affirmer sans mesure » (§1).
  2. **Ça donne sa raison d'être au branchement d'Intervals**, formulée comme
     un gain et non comme une préférence : avec Intervals le modèle se met à
     jour seul, avec un export il faut revenir.

  Le motif n'est pas réglementaire. Le mainteneur est formellement soumis au
  RGPD dès que le service sert quelqu'un d'autre que lui (§10.2), mais à cette
  échelle le risque d'action est nul et ce n'est pas ce qui décide. Ce qui
  décide : des traces GPS sont des données de localisation, elles portent le
  domicile de chacun au départ de chaque sortie, et **celui à qui ça se
  reprocherait est l'ami qui les a confiées**, pas un régulateur. Jeter ce
  qu'on n'a pas besoin de garder est la seule façon sûre de ne pas le perdre.

## 6. Sources externes et leurs limites, telles que connues au cadrage

| Source | Usage | Contrainte |
|---|---|---|
| Open-Meteo | prévisions par point, AROME HD 1,3 km en France (`meteofrance_arome_france_hd`), ICON/ECMWF ailleurs ou en second avis | gratuit sans clé, usage non commercial, plusieurs points par appel ; AROME ne donne pas de probabilité de pluie |
| Intervals.icu | séance du jour, liste des activités, **téléchargement du FIT d'origine** | clé d'API personnelle (Settings → Developer), auth basique `API_KEY:<clé>` |
| BRouter | boucles, profils `fastbike-*`, GPX natif | auto-hébergé (Java ou Docker), données OSM à télécharger |
| GraphHopper | mode boucle par distance | API hébergée gratuite à petit volume, clé |
| Strava | **pas** de génération d'itinéraire par API ; export GPX de ses propres itinéraires | import GPX manuel |
| Garmin Connect | envoi du parcours (S5) | pas d'API publique ; accès à cadrer avec le mainteneur ; rien n'est branché |

## 7. Ce qu'on refuse, et pourquoi

- **Home Assistant comme dépendance.** HA consommera les résultats plus tard ;
  le projet ne l'importe jamais et ne lit jamais sa configuration.
- **Une base serveur, un compte, une API web** tant que la CLI ne couvre pas
  le besoin du mainteneur. On garde la porte ouverte (principe « le cœur ne
  sait pas où il tourne », chapitre 10), on ne la franchit pas. *État :
  franchie une fois la CLI suffisante — l'API, les comptes sur invitation et
  PostgreSQL existent (chapitre 10, `CHANGELOG.md` 0.7.0 à 0.9.0).*
- **Un secret d'authentification stocké en clair.** L'entrée se fait par
  invitation, puis le compte porte **un moyen de s'authentifier dont la
  forme est ouverte** — mot de passe, passkey, autre (§10.2, révisé le
  18/09/2026). Ce qu'on refuse n'est pas une forme en particulier, c'est
  **le secret en clair, quelle que soit sa forme et où que ce soit** : base,
  journal, `repr`, message d'erreur.
- **Copier une clé ou un jeton dans le dépôt, un test ou une fixture.** Sans
  exception.
- **Une moyenne de modèles météo.** Le désaccord est une information, on
  l'affiche.
- **Un service payant obligatoire.** Une option payante (Solcast, GraphHopper
  au-delà du gratuit) reste une option, jamais le chemin nominal.
- **Les routes déjà roulées comme critère de choix.** Elles sont un
  **instrument de mesure**, jamais un critère. Mots du mainteneur, 16/09/2026 :
  « les routes connues et leur fréquence, c'est pour du test. Ce que je fais,
  c'est des routes sûres : ça permet de comparer les critères de BRouter à ma
  réalité dans ses choix, pas du tout de privilégier mes choix. »

  C'est la règle du sprint 3, et sa raison technique est écrite dans
  `apprentissage.routes.BaseRoutes.part_connue` : pénaliser l'inconnu
  condamnerait d'avance toute direction jamais explorée, alors que le
  mainteneur a lui-même demandé d'aller « tester des routes sud sud-ouest pour
  voir ».

  La raison de fond est plus forte que la raison technique : **le jour où les
  routes connues entrent dans le score, l'outil cesse de mesurer quoi que ce
  soit.** Il renvoie au cycliste ses propres habitudes en prétendant les avoir
  trouvées, et toute validation rétrospective devient circulaire — on
  vérifierait que le modèle prédit bien ce qu'on lui a donné comme cible.

  Conséquence pratique : la part connue s'**affiche**, sert d'**étalon** pour
  valider un critère nouveau (les poids du terrain au sprint 3, la densité de
  marqueurs urbains au sprint 5), et n'entre **ni dans une note, ni dans un
  tri, ni dans une sélection**. Une erreur de ce genre a été faite et
  rattrapée dans le cadrage de L5.3, le 16/09/2026.

## 10. Cible hébergée et multi-utilisateur — ce qu'on décide maintenant

Décision du mainteneur (12/09/2026) : la cible est **multi-utilisateur**,
et il faut y penser tôt parce que ça a des implications
techniques (base de données, stockage, secrets) qu'on ne rattrape pas.
Le **chemin d'authentification** de cette phrase (« déléguée, Google
d'abord ») a été révisé le 16/09, précisé le 17 et le 18/09 : voir §10.2,
qui fait foi — compte chez nous par invitation, puis un moyen
d'authentification dont la forme est ouverte et le secret jamais en clair ;
Google et Apple ensuite et en plus.
Rien de ce chapitre ne se construisait avant que la CLI couvre le besoin du
mainteneur ; tout ce chapitre s'applique à la manière d'écrire le cœur.
*État : l'hébergé est construit et sert des invités ; les notes « État »
ci-dessous disent ce qui en est appliqué.*

### 10.1 Ce qui s'applique dès aujourd'hui (coût nul, dette évitée)

- **L'unité de tout est le profil, pas la machine.** `Config` (départ,
  cycliste, vélos, clés, fenêtre d'historique) est *le* profil d'un
  utilisateur. Toute fonction du cœur reçoit ce profil ; aucune ne suppose
  qu'il n'y en a qu'un. Quand l'hébergé arrivera, `Config` gagnera un
  identifiant d'utilisateur et sera chargée depuis la base au lieu d'un TOML :
  le cœur ne le verra pas. *État : en hébergé, la `Config` d'un
  propriétaire se compose du socle du serveur et de son profil, rangé dans
  son dossier (`api/depots.py`), pas en base ; le cœur ne le voit pas.*
- **Les dépôts de données sont des interfaces.** Le cache d'activités
  (fichiers bruts + index) est aujourd'hui un dossier et un SQLite ; en
  hébergé ce sera un stockage d'objets et Postgres. Le cœur parle à une
  classe `Cache` (ajouter, contient, lister, chemin), jamais à un chemin ni
  à une requête SQL. *État : en hébergé aussi, le cache reste un dossier et
  un SQLite sur le disque du serveur, les fichiers bruts rangés par
  propriétaire (`activites/cache.py`) ; ni stockage d'objets, ni Postgres
  pour l'index.* Le schéma de l'index local est écrit avec une colonne
  « propriétaire » en tête, pour que la migration soit un déplacement, pas
  une réécriture.

  **Fait le 17/09/2026**, après constat que la règle n'était appliquée qu'à
  `routes_connues.sqlite`, et encore : la colonne y était sans qu'aucune
  requête ne la filtre. Les trois dépôts locaux (`index.sqlite`,
  `archive_meteo.sqlite`, `routes_connues.sqlite`) portent désormais la
  colonne, elle entre dans **l'identité** (clé primaire ou index unique), et
  chaque requête de lecture comme d'écriture porte la clause. Trois points
  décidés à cette occasion :

  - **Le propriétaire entre au constructeur du dépôt, et nulle part ailleurs**
    (`Cache(dossier, proprietaire=…)`) : exactement la position du `Path`, que
    la ligne de commande fournit déjà et que le cœur ignore. Aucune fonction
    du cœur ne le prononce ; en hébergé, c'est la couche web qui construira le
    dépôt avec l'identifiant de l'utilisateur authentifié.
  - **L'unicité d'une activité devient `(propriétaire, source,
    id_externe|contenu)`.** Sans le propriétaire, deux utilisateurs ayant la
    même activité Intervals — sortie en groupe, compte partagé — ne se
    seraient pas vu refuser l'écriture : le `ON CONFLICT DO UPDATE` aurait
    écrasé la ligne du premier, en silence.
  - **L'archive météo porte la colonne avec la valeur `partage`**, pas un
    identifiant d'utilisateur : la mutualisation voulue plus bas dans ce
    paragraphe est intacte, simplement **écrite** au lieu d'être déduite d'une
    absence de colonne — et il n'y a pas de liste d'exceptions à tenir pour
    l'invariant, or une liste d'exceptions se remplit toute seule.

  Un invariant de `tests/test_invariants.py` reconstitue le SQL de chaque
  appel `execute` du cœur et échoue si une requête neuve oublie la clause ;
  seules les fonctions préfixées `_migrer` en sont dispensées, puisqu'elles
  fabriquent la colonne.
- **Les clés d'API externes sont des données du profil, secrètes.** Clé
  Intervals, plus tard GraphHopper, Garmin : jamais en clair dans un log,
  une erreur, un JSON de sortie (`ourouler config --json` les masque déjà).
  En hébergé : chiffrées au repos, une par utilisateur. *État : pas
  encore — le profil d'un compte, clé comprise, est un fichier lisible du
  seul processus (droits 0600, `api/exploitation.ecrire_toml`).*
- **Chaque commande rend du JSON.** C'est la future réponse d'API, et donc
  le contrat du front.
- **Les quotas externes se pensent par service, pas par utilisateur.**
  Open-Meteo gratuit est réservé à un usage non commercial et limité par
  adresse IP : un service hébergé devra soit passer sur l'offre payante,
  soit mutualiser (cache des prévisions par maille et par heure, partagé
  entre utilisateurs). Le module météo recevra une couche de cache
  injectable devant le client HTTP **au premier sprint de l'hébergé** —
  l'exigence « dès le sprint 2 » écrite au cadrage a été ajournée par le
  superviseur le 13/09/2026 (relecture du sprint 2, point 9) : en CLI,
  chaque utilisateur appelle depuis sa propre adresse, et un `boucle` à 5
  candidates coûte ~10 **requêtes** Open-Meteo + 12 BRouter, sans enjeu de
  quota.

  **Correction du 16/09/2026 : requêtes et appels décomptés ne sont pas la
  même chose, et le chiffre ci-dessus confondait les deux.** Open-Meteo
  décompte **un appel par coordonnée**, pas par requête : grouper plusieurs
  points dans une requête économise du temps réseau, jamais du quota. La
  ligne « ~50 appels pour un `meteo` à 25 points × 2 modèles » appliquait
  déjà la bonne règle ; celle du `boucle` l'avait oubliée.

  Le vrai chiffre, pour une `sortie` à 5 candidates sur une boucle de 70 km
  échantillonnée tous les 5 km (`meteo_trace.PAS_DEFAUT_M`) : 14 points par
  requête, `1 + 2 × candidates` requêtes, soit **~150 appels décomptés**. À 8
  candidates, ~240.

  Conséquence pratique, mesurée le 16/09/2026 : un agent a vu passer un
  `HTTP 429 — Minutely API request limit exceeded` et en a conclu qu'il ne
  fallait pas augmenter le nombre de candidates. **Le diagnostic était faux** :
  240 appels restent sous les 600 par minute, et la limite n'a été atteinte
  qu'en enchaînant des essais. Une commande par jour coûte ~150 appels sur
  10 000. Le 429 était un artefact de test, pas une limite produit.

  Les leviers réels, si le poste devient contraignant : espacer les
  échantillons (`PAS_DEFAUT_M`), mettre le cache, et ne pas demander le
  second avis météo pour chaque candidate. **Pas « grouper les appels »** :
  c'est déjà fait et ça ne change rien au décompte.
  Le client Open-Meteo est déjà injectable, ce qui suffit à poser le cache
  plus tard sans toucher au cœur. *État : le cache mutualisé existe
  (`meteo/cache_previsions.py`), en mémoire du processus.*

  Ordres de grandeur (question du mainteneur, 12/09/2026) : le gratuit
  tolère environ 10 000 appels par jour et par adresse IP (5 000 par heure,
  600 par minute), et un `ourouler meteo` à 25 points × 2 modèles compte
  pour ~50 appels — soit ~200 consultations par jour depuis un seul
  serveur, tous utilisateurs confondus. En CLI, chacun appelle depuis sa
  propre adresse : aucun sujet. En hébergé, l'escalade décidée : (1) cache
  mutualisé par maille (~2 km) et par heure dès le premier jour ; (2) offre
  API payante d'Open-Meteo (quelques dizaines d'euros par mois, usage
  commercial autorisé, rien à exploiter) au premier signe de saturation ;
  (3) auto-hébergement d'Open-Meteo (open source, Docker, rapatrie lui-même
  les données ouvertes Météo-France / ICON / ECMWF) seulement si le volume
  ou la souveraineté des données l'exigent.

### 10.2 Ce qu'on décide maintenant, pour construire plus tard

- **Authentification : par invitation, puis un moyen dont la forme est
  ouverte.** Le principe d'un chemin propriétaire (pas de délégation à un
  tiers en entrée) ne bouge pas ; ce qu'il embarque, si — **révisé le
  16/09/2026** puis encore le **18/09/2026** par le mainteneur (« c'est pas
  une banque » ; « je trouve que tu compliques les choses, on va revenir au
  basique »).

  **« Jamais de mot de passe chez nous » était la version du 16/09 ; elle ne
  tient plus** — mais ce qui la remplace n'est pas « mot de passe » non plus.
  Le mainteneur l'a posé comme un principe, pas comme un choix de technique :
  *« un compte dans la vie c'est un login et un mot de passe »*, puis
  aussitôt *« après on peut changer le mot de passe par plein de trucs,
  passkey, lien, empreinte »*. Le compte porte donc **un moyen de
  s'authentifier**, et la forme de ce moyen est ouverte.

  Ce que la doctrine fixe, et qui ne dépend pas de la forme : **le secret
  n'est jamais en clair**, où que ce soit (base, journal, `repr`, message
  d'erreur), et il se vérifie en temps constant. Aujourd'hui c'est un mot de
  passe haché au scrypt avec un sel par compte, parce que c'est le plus
  simple à écrire ; une passkey s'ajoutera **sans changer le schéma** — le
  compte range une méthode et un secret, et rien d'autre du produit ne sait
  lequel des deux il porte. Détail d'implémentation :
  `src/ourouler/api/comptes.py`.

  **V1 : entrée modérée, par lien à usage unique.** Une demande d'accès, que
  le mainteneur valide à la main, puis un e-mail d'invitation (Brevo)
  portant un lien qui fait poser son moyen d'authentification ; une
  **passkey** (WebAuthn) pourra s'ajouter plus tard pour ne plus dépendre de
  sa boîte mail — non écrite aujourd'hui, voir plus bas la petite
  indirection qui lui laisse la place. Deux raisons de préférer ce chemin à ce qui était écrit ici avant :
  la **modération est native** — le sprint 8 veut qu'on invite des copains,
  et par-dessus une connexion Google il aurait fallu construire une liste
  d'attente — et l'écran d'entrée nous appartient, au lieu d'être celui d'un
  tiers.

  **Précisé le 18/09/2026 par le mainteneur, à l'ouverture du lot L7.2-A, et
  ce n'est pas un détail de V1 : l'entrée est sur invitation *uniquement*, et
  définitivement — y compris pour la version publique.** Il n'y a jamais de
  création de compte à la demande : pas de formulaire d'inscription, pas de
  demande d'accès, pas de liste d'attente. Le seul chemin vers un compte est
  un lien envoyé par le mainteneur, et **son propre compte passe par ce
  chemin-là**, sans exception ni trappe d'amorçage. La phrase « une demande
  d'accès, que le mainteneur valide à la main » ci-dessus décrivait un
  guichet qui n'existera pas ; ce qui reste vrai d'elle, c'est que rien
  n'entre sans un geste du mainteneur.

  Deux conséquences techniques, écrites au même moment parce qu'elles ne se
  rattrapent pas :

  - **« En base l'email est UNIQ, c'est pas le code qui porte ce genre de
    contrôle sinon catastrophe ; mais oui on a un id-account avec un id à
    nous qui est la clé. »** Toute unicité est une **contrainte de base de
    données**, jamais une vérification préalable dans le code : un `SELECT`
    puis `INSERT` se fait doubler par deux requêtes concurrentes. On insère
    (`ON CONFLICT … DO NOTHING`, jamais un `SELECT` puis un `INSERT`). De
    même, une invitation se consomme par un unique `UPDATE … WHERE … AND
    consomme_le IS NULL … RETURNING`.
  - **Le jeton d'invitation, lui, est en clair — révisé le 18/09/2026.**
    La version du 17/09 ne stockait que son condensé (SHA-256) ; le
    mainteneur est revenu dessus explicitement : il veut pouvoir relire un
    jeton émis et le renvoyer par le canal de son choix, ce qu'un condensé
    interdit. Le risque est repris par deux bornes plutôt que par
    l'irréversibilité du condensé : une durée de vie courte — **trois jours**
    au lieu de sept — et le fait qu'un lien n'ouvre jamais qu'un compte
    **vide** (aucun moyen de s'authentifier n'y est posé avant l'activation).
    Ce qui ne change pas : le jeton ne doit **jamais partir dans un
    journal** — c'est une règle de code (les `__repr__` d'`Invitation` et
    `InvitationEmise` le masquent), pas une règle de schéma.

  **Le cycle complet, décidé le 18/09/2026 ([Q59](docs/journal/questions/questions_mainteneur.md), close) :** inviter une
  adresse crée un compte inactif et une invitation ; ouvrir le lien ne
  consomme rien ; poser un mot de passe active le compte **et** consomme
  l'invitation, les trois dans une seule transaction — un compte actif sans
  secret, ou un secret posé sur une invitation déjà consommée, sont des
  états que la base elle-même refuse. Réinviter passe par la **même**
  commande, qui lit l'état : un compte déjà actif est refusé (« il a déjà un
  compte », jamais un doublon — « pas d'interface ne veut pas dire pas de
  contrôle ») ; un compte inactif dont l'invitation court encore se voit
  rendre **le même jeton**, ce que le jeton en clair permet enfin ; une
  invitation périmée est remplacée par une neuve. Il n'y a pas de geste
  séparé « relancer » : une seule commande suffit.

  **Le secret est rangé derrière une petite indirection** (une colonne qui
  nomme la méthode d'authentification, une qui porte le secret) plutôt que
  dans une colonne « mot de passe » directe — parce que le mot de passe ne
  restera pas le seul moyen (une passkey, plus tard — voir le paragraphe V1
  ci-dessus). L'abstraction s'arrête à ces deux colonnes : il n'y a pas de
  passkey aujourd'hui, et le code n'en écrit pas l'ombre.

  **V2 : Google, puis Apple, en plus et non à la place.** OpenID Connect
  avec ses contraintes propres côté Apple — compte développeur payant, clé
  privée et identifiant de service, relais d'adresse e-mail privée,
  obligation d'Apple si une app iOS propose d'autres connexions sociales.
  Bibliothèque au moment venu (Authlib ou équivalent), jamais une
  implémentation maison d'OAuth.

  **Ce qui ne change pas dans les deux cas** : l'identité interne est un
  identifiant opaque ; l'e-mail est une donnée du profil, pas une clé
  primaire (un utilisateur peut changer de fournisseur, ou passer du lien
  magique à Google) ; et **une passkey n'est jamais le seul moyen d'entrer**
  — le lien à usage unique reste le filet, parce qu'une passkey se perd avec
  l'appareil ou le trousseau qui la synchronise.
- **Compte et propriétaire sont deux choses, reliées par une table**
  (décidé le 17/09/2026, [Q46](docs/journal/questions/questions_mainteneur.md)). Le `Proprietaire` de §10.1 devient la clé
  **pseudonyme** sous laquelle vivent les poids de routes appris et les
  valeurs d'apprentissage ; le **compte** porte l'identité et l'accès. Une
  table de correspondance les relie, et c'est **elle** qu'on efface à la
  suppression d'un compte : le profil, les fichiers et les clés partent, les
  poids restent sous un propriétaire que plus rien ne rattache à quelqu'un.
  Cette table se décide maintenant parce qu'elle ne se rattrape pas.

  Ce qu'on range sous un propriétaire suit deux règles : **jamais de nom ni
  d'adresse**, et **la granularité la plus grossière qui serve** — l'année de
  naissance et non la date, si l'âge revient un jour. Une FTP ou une FCmax
  sont des grandeurs qui ne désignent personne.

  **Pseudonyme, pas anonyme** : les poids viennent de trajets réellement
  roulés dont le départ est un domicile, donc ré-identifiables. Le choix
  entre assumer la pseudonymisation, agréger entre propriétaires à
  l'écriture, ou n'agréger qu'après une fenêtre courte, reste ouvert et se
  tranchera au lot.

- **Base de données hébergée : PostgreSQL, dès le premier jour de
  l'hébergé, jamais SQLite.** Même raison qu'ix-presenter : le coût d'un
  Postgres sur Coolify est quasi nul, le coût d'une migration SQLite →
  Postgres tombe toujours au mauvais moment. Migrations SQL numérotées, SQL
  nu, pas d'ORM. Le SQLite local de la CLI reste : c'est un cache, pas la
  base.
- **Fichiers bruts (FIT/GPX/TCX) : stockage d'objets**, pas la base ni le
  disque du serveur — un utilisateur actif représente vite des centaines de
  fichiers. Cible naturelle : un stockage S3-compatible (Hetzner Object
  Storage ou équivalent), un préfixe par utilisateur. *État : non appliqué
  — les fichiers bruts vivent sur le disque du serveur, un dossier par
  propriétaire ; et §5 dit qu'un export déposé ne se garde pas : l'écart
  est ouvert en [Q67](docs/journal/questions/questions_mainteneur.md).*
- **Isolation des données : par utilisateur, vérifiée côté serveur** à
  chaque requête, jamais seulement côté front. Aucune requête sans clause
  de propriétaire.
- **RGPD par construction** : export de toutes ses données et suppression
  du compte (profil, fichiers, calibrations, clés) ; pas de suivi
  d'audience ; hébergement en Europe.

  **Calendrier révisé le 17/09/2026 par le mainteneur** ([Q46](docs/journal/questions/questions_mainteneur.md)) :
  l'export et la suppression étaient promis « dès la première version
  hébergée » ; ils passent au **sprint 9 ou 10**. Motif : « je suis pas un
  service, c'est des potes ». Le principe ne bouge pas, seul le moment
  change. *État : livrés — par l'API en 0.7.0, par l'écran « Mon compte »
  en 0.9.0 (`CHANGELOG.md`).*

  **Ce que ce report engage.** Le cercle restreint ne suspend pas le droit à
  l'effacement : l'exemption « activité strictement personnelle ou
  domestique » est étroite et ne couvre pas un service ouvert sur Internet.
  Le jalon à ne pas franchir sans ces deux fonctions est donc **la première
  invitation hors du cercle des proches**, pas la première invitation.

  **Et une chose est déjà tranchée** : les **poids de routes appris restent
  collectifs**. Ils sont fondus dans un modèle commun dès l'apprentissage et
  ne repartent pas avec un compte supprimé — c'est ce qui fait la valeur d'un
  service partagé, et c'est assumé.
- **API avant front.** L'API expose ce que la CLI sait déjà rendre en
  JSON ; le front la consomme. Le front ne parle jamais directement au cœur.

### 10.3 Ce qui a été décidé depuis, et ce qui ne l'est toujours pas

**Tranché le 16/09/2026** par le mainteneur, à l'ouverture du cycle UX
(`docs/journal/ux/front_contrat.md`) : le front sera **React**, l'API vient **avant**
le front, et les comptes après. **Livré le 17/09/2026** (lot F1) : le cadre
web est **FastAPI**, avec uvicorn pour le servir — c'est la seule dépendance
lourde qu'ouvre l'API, et elle ouvre avec elle la porte que `§3` laissait
alors entrebâillée (« pas de Pydantic tant qu'il n'y a pas d'API »). Le cœur, lui,
reste en dataclasses : Pydantic ne sert qu'aux corps de requête.

Ce que la livraison ajoute à ce chapitre, et qu'il faut lire avec lui : l'API
n'implémente rien, elle rend le JSON que la ligne de commande rend — par la
commande elle-même ou, sur son nouveau chemin, par les mêmes services et le
même rendu (`ARCHITECTURE.md` §4) ; l'isolation par propriétaire est écrite
dans la forme des dépôts, avec un invariant qui la garde ; et l'attente d'une
génération est semi-synchrone, avec une durée annoncée qui dit si elle est
mesurée. Le contrat qui fait foi est le schéma figé
`tests/caracterisation/openapi.json` ; `docs/journal/ux/api_contrat.md` en
garde l'histoire, en partie périmée (l'authentification y est dite non
choisie).

**Décidé depuis** : l'hébergement — le service tourne sur Coolify, avec une
préproduction et une production séparées (`docs/retour_arriere.md`).
**Toujours pas décidé** : la tarification éventuelle.

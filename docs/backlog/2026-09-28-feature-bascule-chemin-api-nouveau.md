# Basculer l'API vers le chemin « nouveau », puis retirer l'ancien

Type : feature
Statut : à valider

## Pourquoi

L'API appelle aujourd'hui le cœur par deux chemins qui coexistent
(`api/double_chemin.py`) : l'« ancien » (`api/adaptateur.py`, la ligne de
commande capturée — `Namespace`, sortie standard interceptée, un verrou
global) reste le défaut, le « nouveau » (`api/calculs.py`, service et rendu
directs, sans capture ni verrou) est prêt, et « double » sert à les comparer
en préproduction. Tant que « ancien » reste le défaut de production, chaque
requête sérialise sur un verrou de processus et paie le détour par
`argparse.Namespace` + capture de sortie standard — un coût que `nouveau`
n'a pas. Le module `adaptateur.py` (301 lignes) et tout ce qu'il entraîne
(le verrou `_VERROU`, `namespace()`, `executer_commande`) ne servent qu'à
maintenir ce chemin vivant le temps de la bascule ; ils sont voués à
disparaître avec elle (`adaptateur.py`, en-tête de module : « Il disparaîtra
avec elle »). [déduit]

## Ce que je veux voir

- Un état des lieux écrit (pas seulement dans cette fiche) de ce qui reste à
  faire avant de poser `OUROULER_API_CHEMIN=nouveau` en production : quelles
  routes ont déjà tourné en `double` en préproduction, depuis quand, avec
  combien d'écarts journalisés (`ecart_double_chemin`, niveau `WARNING`,
  `double_chemin.py`) — et un chiffre, pas une impression.
- Un calendrier de bascule en trois pas, chacun réversible par
  `OUROULER_API_CHEMIN` seul, sans redéploiement de code
  (`docs/retour_arriere.md`, « Revenir à l'ancien chemin de l'API ») :
  1. `double` en préproduction pendant une durée mesurée, zéro écart
     non expliqué ;
  2. `nouveau` en production, `ancien` gardé en filet
     (`OUROULER_API_CHEMIN=ancien` reste un geste d'un redéploiement) ;
  3. retrait de `api/adaptateur.py`, `api/double_chemin.py` et des trois
     valeurs de `OUROULER_API_CHEMIN` une fois `nouveau` éprouvé en
     production sur une durée à convenir avec le mainteneur.
- Le retrait effectif du code (pas seulement le réglage) est un lot séparé,
  après une période d'observation en production réelle — pas dans la même
  PR que le passage à `nouveau`.

## C'est fini quand

**Ce lot-ci** (l'état des lieux et le calendrier) est fini quand la fiche de
suivi (chantier ou fiche séparée pour chacun des trois pas) existe, avec le
compte des écarts déjà observés en préproduction depuis leur passage en
`double`, et que le mainteneur a validé le calendrier des trois pas. Le pas 3
(retrait du code) a son propre critère : plus aucune mention
d'`OUROULER_API_CHEMIN`, `ancien` ou `double` dans le déploiement de
production, `api/adaptateur.py` et `api/double_chemin.py` supprimés,
`Resultat`/`Avertissement`/`avertissements_de`/`Budgets` (qui servent aux
deux chemins) déplacés là où le chemin `nouveau` seul les attend.

## Hors sujet

- Réécrire `api/calculs.py` : il existe déjà et sert le chemin `nouveau`,
  ce lot ne change pas son comportement.
- Ajouter un quatrième chemin ou un mécanisme de bascule progressive
  (pourcentage de trafic, feature flag par compte) : `OUROULER_API_CHEMIN`
  reste un réglage par déploiement, comme aujourd'hui.

## Acquis techniques

- Le mécanisme de bascule existe déjà en entier et n'a rien à construire :
  `OUROULER_API_CHEMIN` (`ancien`/`nouveau`/`double`), lu une seule fois au
  démarrage par `api/exploitation.chemin_api`, refuse de démarrer sur une
  valeur inconnue (même discipline que `OUROULER_MODE`).
- `double_chemin.ecart_entre` journalise déjà une ligne structurée par écart
  (statut, chemins de clés qui diffèrent, jamais de valeur, message, adresse
  ni jeton) — c'est la source du chiffre d'écarts à rapporter dans l'état des
  lieux.
- `tests/api/conftest.py::chemin_api_de_l_environnement` rejoue déjà toute
  la suite `tests/api/` sur le chemin choisi par `OUROULER_API_CHEMIN` de
  l'environnement de test (marqueur `ecart_attendu` pour la mutation de
  contrôle en mode `double`) : la CI peut déjà confirmer que `nouveau` seul
  passe la suite avant de le poser en production.

## Questions ouvertes

- Combien de temps `double` doit-il tourner en préproduction avant de
  déclencher le pas 2 (poser `nouveau` en production) — un nombre de jours
  ou un nombre de requêtes comparées, à trancher avec le mainteneur.
- Le pas 3 (retrait du code) est-il un sprint à part entière ou un élément
  ajouté au sprint qui porte le pas 2 ? Dépend du calendrier réel du pas 2.

## Déjà en place / Doctrine révisée

- Constaté : `src/ourouler/api/double_chemin.py` (CHEMIN_ANCIEN = "ancien",
  CHEMIN_NOUVEAU = "nouveau", CHEMIN_DOUBLE = "double", CHEMIN_DEFAUT =
  CHEMIN_ANCIEN) porte les trois chemins et choisit entre eux ;
  l'en-tête du module dit explicitement « ancien pour ce lot : la bascule se
  fait en préproduction, par double d'abord ».
- Constaté : `src/ourouler/api/exploitation.py::chemin_api` (ligne 391) lit
  `OUROULER_API_CHEMIN`, refuse de démarrer sur une valeur qui n'est ni
  vide, ni `ancien`, ni `nouveau`, ni `double`.
- Constaté : `docker-compose.api.coolify.yml` déclare
  `OUROULER_API_CHEMIN=${OUROULER_API_CHEMIN:-}` avec le commentaire « vide
  ou absent = le défaut, ancien ; la préproduction passe en double pour
  comparer, la production ira directement en nouveau » — la variable est
  donc déjà câblée en prod/préprod, la décision de la faire avancer ne l'est
  pas encore.
- Constaté : `docs/retour_arriere.md`, section « Revenir à l'ancien chemin de
  l'API », décrit déjà le geste de repli (poser `OUROULER_API_CHEMIN=ancien`
  et redéployer) — la procédure de secours existe avant même la bascule.
- Constaté : `src/ourouler/api/adaptateur.py`, en-tête de module : « Il
  disparaîtra avec elle [la bascule] ; Resultat, Avertissement,
  avertissements_de et Budgets servent aux deux chemins et resteront » — le
  retrait visé par ce lot est déjà écrit comme intention dans le code, pas
  seulement dans cette fiche.

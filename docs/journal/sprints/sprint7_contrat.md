# Sprint 7 — ce qui peut avancer sans le mainteneur

Cadré le 18/09/2026. **Règle de ce sprint : aucun lot ne demande d'arbitrage.**
Tout ce qui attend une décision — la clé Brevo, la politique de modération,
[[Q35]], [[Q36]], [[Q46]], le choix de la méthode d'authentification — est
explicitement **hors périmètre**, et les lots ci-dessous sont écrits pour
s'arrêter proprement au bord de ces questions plutôt que de les trancher.

## Pourquoi ce découpage

L'état vérifié le 18/09 : la plomberie multi-utilisateur **existe** —
`Proprietaire` traverse toutes les routes, le stockage est cloisonné, un test
d'isolation existe — mais `proprietaire()` rend toujours le même utilisateur
local. Le commentaire du code le dit : « F3 remplacera `resoudre` par la
session ». La couture est prête, rien n'est branché dedans.

Ce qui bloque le dogfood est donc, dans l'ordre : le déploiement du front et
de l'API, les comptes, le stockage partagé, l'accueil. Les comptes demandent
des décisions ; **la session, l'isolation, l'export, les erreurs lisibles et
le paquetage n'en demandent aucune.** C'est le périmètre de ce sprint.

Ce que le 18/09 a déjà réglé sans qu'on le compte : les valeurs de littérature
par type de vélo donnent un modèle physique à qui n'a ni capteur ni
historique, et le disent. C'était le verrou de fond du sprint 8.

## Les lots

### L7.A — la session, et l'isolation prouvée

`proprietaire()` cesse de rendre un utilisateur en dur et lit une **session**,
derrière une interface injectable. **Aucune méthode d'authentification n'est
choisie ici** : le fournisseur de session est une dépendance, les tests en
injectent un, et le service en configure un. Sans session valide, toute route
de données répond **401**, jamais un profil par défaut.

L'isolation cesse d'être testée par échantillon : **toute route** qui lit ou
écrit des données d'utilisateur doit être couverte, et le test doit échouer si
une route nouvelle apparaît sans clause de propriétaire.

*Acceptation* : aucune route ne rend les données d'un propriétaire à un autre,
prouvé route par route contre le service réel ; une route ajoutée sans clause
fait échouer la suite.

### L7.B — export et suppression des données personnelles

Un propriétaire récupère ce qui le concerne, et peut demander son effacement.
**La frontière est celle que le mainteneur a posée le 17/09** : le tracé
(position, classe de route, revêtement, coût) est collectif ; **le lien** —
qui y est passé, quand, sur quelle sortie — est personnel. Ce lot n'emporte
que le personnel.

Ce qu'il **ne tranche pas** : ce que le service garde du collectif quand
quelqu'un s'en va. C'est [[Q46]], et elle reste ouverte.

*Acceptation* : après suppression, aucune route ne rend plus rien de cette
personne, et un test le vérifie sur chaque dépôt (profil, cache, fichiers,
routes apprises).

### L7.C — l'altitude vient du tracé rerouté, plus de l'appareil

Mesuré le 18/09 sur deux courses, avec les valeurs Strava corrigées comme
étalon :

| | appareil | Strava corrigé | notre filtre | BRouter, altitudes point par point, seuil 2 m |
|---|---|---|---|---|
| Lacanau | 858 m | **235 m** | 884 m | **234 m** |
| Les Sables | 1 566 m | **1 260 m** | 1 378 m | **1 076 m** |

Le filtre n'était pas en cause : **la source l'était**. Un altimètre
barométrique accumule 20 cm de bruit par point ; sur 9 731 points, il fabrique
1 563 m de fausse montée sur un parcours dont l'amplitude d'altitude est de
41 m.

Le tracé rerouté est **déjà en main** aux deux seuls endroits qui comptent :
la greffe des tags d'un GPX importé, et `apprentissage` qui rejoue les
sorties. On jette son altitude. Il suffit de la prendre.

*Acceptation* : sur les deux courses, le D+ rendu tombe à moins de 15 % des
valeurs Strava corrigées ; la provenance de l'altitude est dite (règle
absolue 5) ; sans reroutage possible, on retombe sur l'ancien comportement.

### L7.D — l'écran pour quelqu'un qui n'a pas écrit le code

Trois choses, toutes constatées à l'usage :

1. **Les messages d'erreur.** Chaque code d'erreur de l'API doit produire à
   l'écran une phrase qui dit ce qui s'est passé et ce qu'on peut faire. Pas
   de code technique nu, pas d'écran muet.
2. **Le « Direction » en double** dans le formulaire de demande — le libellé
   apparaît deux fois, pour le mode et pour l'azimut. Signalé le 18/09, jamais
   corrigé.
3. **Les deux horloges trop éloignées** : « 3 h 57 en roulant » est sur la
   première ligne, « ≈ 4 h 40 porte à porte » arrive après le D+, la pluie, le
   vent et les types de routes. L'œil ne les rapproche pas.

### L7.E — le paquetage, sans déployer

Le front et l'API packagés pour tourner ailleurs que sur le Mac du
mainteneur : image, compose, variables, sonde de santé. **Rien n'est
déployé** — règle absolue 7. Le lot rend un paquet prêt et la commande qui le
lance, le mainteneur décide s'il l'exécute.

## Hors périmètre, et pourquoi

| | pourquoi |
|---|---|
| la méthode d'authentification | demande la clé Brevo et la politique de modération |
| Postgres et le stockage d'objets | demande un arbitrage de coût |
| le cache météo mutualisé | dépend du stockage partagé |
| l'import d'historique | [[Q48]] ouverte |
| ce que le service garde du collectif | [[Q46]] ouverte |

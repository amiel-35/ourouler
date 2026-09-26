# La démarche — comment ourouler s'est construit, et ce qu'il a appris

D'où part le projet, comment on y a travaillé, avec quels outils, ce qui a
été essayé et abandonné, ce qui reste possible. Ce document recueille la
substance des contrats et relectures de sprint, gardés bruts dans
[`journal/sprints/`](journal/sprints/).
Les chiffres sont des ordres de grandeur ou des rapports : les mesures
portent sur l'historique réel du mainteneur, dont les valeurs personnelles
n'ont pas leur place ici. Mode d'emploi : `docs/guide_ligne_de_commande.md`.

## 1. Le besoin d'origine

La question de départ : « je vais rouler ; au nord, au sud ou à l'est,
où va-t-il pleuvoir ? » Puis en tirer un parcours de la bonne durée, dans
la bonne direction, cohérent avec la séance du jour, avec la tenue à
mettre, et le mettre sur le compteur.

Le premier utilisateur est le mainteneur : un cycliste avec capteur de
puissance, dont un entraîneur planifie les séances dans Intervals.icu, avec
un vélo de route, un vélo de contre-la-montre et plusieurs années
d'historique. **Son besoin passe en premier** : un lot n'est fini que quand
une commande tourne sur ses vraies données.

Le cadrage fixait aussi ce que le projet ne serait pas : dépendant d'un
service payant ou de Home Assistant ; porteur de la moindre donnée
personnelle, pas même dans un test ; enclin à moyenner deux modèles météo
qui divergent. Et il serait libre, sous AGPL-3.0-or-later, pour qu'un
service hébergé construit dessus reste ouvert.

Le cœur du produit, qui n'existait nulle part en libre, c'est la **boucle
séance ↔ terrain**. La même puissance ne fait pas la même vitesse en
montée et en descente, vent de face et vent dans le dos. Un modèle physique
calibré sur l'historique dit où tombera chaque bloc de la séance, et donc si
le terrain à cet endroit s'y prête.

### La cible, et l'ordre pour y aller

La cible est un **service hébergé** : un compte, un profil, ses sorties
importées, et la météo par direction, une boucle adaptée, la sortie du jour.
L'ordre imposé : une bibliothèque et une ligne de commande qui couvrent le
besoin du premier utilisateur, puis une API au-dessus du même cœur, enfin
l'interface web et les comptes.

D'où une règle posée dès le premier jour : **le cœur ne sait pas où il
tourne.** Il ne lit ni fichier de configuration, ni variable
d'environnement ; il reçoit un profil et des connecteurs, et un test le
vérifie. Quand l'API est arrivée, elle n'a rien eu à réimplémenter : chaque
route appelle la fonction qu'appelle déjà la sous-commande.

### Les sprints (septembre 2026)

| Sprint | Jalon |
|---|---|
| 0 | socle : doctrine, fiches d'agents, inventaire des données disponibles |
| 1 | lecture des fichiers d'activité, cache, inventaire ; météo par direction |
| 2 | tracé : boucles BRouter, coûts, pluie le long du tracé |
| 3 | antennes en cul-de-sac, routes connues, modèle physique |
| 4 | séance ↔ terrain : placement des blocs, tenue, carte de vérification |
| 5 | le vent dans le placement, propositions contrastées, page du jour |
| 6 | dogfooding : mesurer ce qui cloche sur les vraies sorties |
| 7 | l'hébergé : API, comptes, isolation par propriétaire |
| 8 | prêt à inviter : accueil, valeurs par défaut sans calibration |
| 9 | inviter pour de vrai : modèle vélo revu, import d'historique, coût par compte |

## 2. La façon de travailler

### Deux sprints figés, un troisième esquissé

Les deux prochains sprints sont écrits et figés : on les exécute tels
quels. Un troisième est esquissé et n'engage à rien. À la fin des deux
figés, le mainteneur repriorise à partir de ce qui a été livré, **des
écarts entre prévu et réalisé**, et du backlog. Un sprint figé ne s'élargit pas.

La règle a été enfreinte deux fois, et chaque fois dite. Le sprint 5 a tiré
deux lots du sprint 7 : sans la page du jour sur le téléphone, le
dogfooding du sprint 6 n'avait pas lieu. Le sprint 8 a passé son temps aux
comptes plutôt qu'à l'estimation sans capteur : sans comptes, personne à
inviter. Les deux débordements ont été actés, et ce sont eux qui ont le plus
rapporté.

Une clôture de sprint se fait **sur ce qui est livré, pas sur ce qui était
écrit**. Un lot non fait part ailleurs, nommément. Un texte périmé du plan
ne se réécrit pas en douce : il se cite, se disqualifie, et la correction
s'écrit à côté.

### Des agents, chacun à son niveau

Le code est écrit par des agents Claude Code. Un **superviseur** découpe
le sprint en lots aux critères d'acceptation vérifiables et remonte les
questions produit. Des **développeurs** implémentent, un **agent
mécanique** exécute les checklists. Un **testeur adversarial** écrit, **sans
voir le code**, les tests qui essaient de casser le lot. Un **relecteur**
rend un verdict écrit avant que le mainteneur voie quoi que ce soit. Deux
agents en parallèle travaillent chacun dans son propre arbre de travail :
dans le même, ils s'écrasent en silence. Seul le mainteneur fusionne.

Le modèle se choisit **d'avance, selon la nature de la tâche** : **Sonnet**
par défaut, pour l'implémentation bien cadrée ; **Haiku** pour le mécanique
en masse ; **Opus** pour le jugement et les algorithmes subtils (relecture,
tests adversariaux, découpage, placement, calibration) ; **Fable** quand
l'indépendance vis-à-vis du contexte du mainteneur est le but, pour une
relecture adverse de méthode, et toujours en demandant d'abord. Cette
doctrine a elle-même été corrigée en route : les premiers sprints tournaient
avec « Opus partout où ça suffit », une incompréhension de la consigne.

Deux règles vont avec. Le modèle est **obligatoire** sur chaque appel
d'agent, sinon il hérite en silence de celui de la session. Et on ne monte
pas de niveau sur un aveu d'incertitude quand la tâche est du jugement : un
agent sous-dimensionné ne dit pas qu'il doute, il répond faux avec
assurance. Commencer petit puis monter ne vaut que là où existe un signal
mécanique : tests, lint, intégration continue. Ce qu'un agent rend, ce sont
des pointeurs (chemins, commits), pas du contenu brut.

### Les relectures adverses, et la mutation

Les pires défauts n'ont pas été trouvés par les tests écrits avec le code.

- **Le testeur adversarial** a trouvé des pentes en pourcentage d'un côté
  et en tangente de l'autre, si bien que tout demi-tour était refusé dès
  0,1 % de pente ; un village traversé en récupération facturé au bloc
  suivant ; une direction de vent « pas un nombre » envoyée au moteur de
  tracé ; une phrase qui affichait « 71 minutes de moins » comme un
  avantage, alors qu'elle voulait dire « vous ne roulez pas votre séance ».
- **L'audit de mutation** modifie volontairement le code pour enfreindre
  une règle, et regarde si un test rougit. Un placement qui étirait les
  récupérations « quand ça arrange » passait près de trois mille tests ; la
  règle « on note, on ne filtre pas » n'était protégée que par un
  dépaquetage de tuple.
- **Une relecture de méthode indépendante** a expliqué pourquoi la
  calibration partait en butée (voir §4), et fait réécrire le critère
  d'acceptation du modèle vélo, qui comparait des grandeurs incomparables.
- **Le mainteneur, en regardant des cartes**, a trouvé au sprint 5 six
  défauts qu'aucun test ne voyait : les feux perdus à l'élagage des
  antennes, une étape libre comptée pour zéro kilomètre, les ralentisseurs
  jamais lus, les rafales téléchargées puis jetées, une division par zéro,
  des blocs superposés sur le profil après un demi-tour.

### Chaque lot tourne sur les vraies données

Un lot n'est fini que si ses tests passent, si le lint est vert et si **la
commande du jalon tourne sur les vraies données du mainteneur**. Sinon, il
est marqué **non vérifié**, en toutes lettres, avec la raison.

La règle a mordu. Sans clé d'API au premier sprint, lecteur, cache et
connecteur Intervals sont restés « non vérifiés » jusqu'à son arrivée. La
page du jour servie par l'API l'est restée tant que personne n'avait vu le
partage du GPX réussir sur un vrai téléphone : un test vert dans un
navigateur simulé n'en dit rien. Et la règle a arrêté du code : au sprint 6,
trois corrections cadrées se sont arrêtées **avant la première ligne**,
parce que la mesure exigée pour les accepter réfutait leur prémisse (§4).

### Ne rien affirmer sans mesure

Un modèle se valide sur des données qu'il n'a pas vues, avec son erreur.
Deux sources qui divergent s'affichent comme un désaccord. Une valeur
supposée se dit supposée : chaque écran dit d'où vient son chiffre.

Les erreurs de raisonnement du superviseur sont enregistrées aussi : une
proportion annoncée sur **une seule boucle** (une boucle n'est pas un
échantillon) ; une conclusion tirée du chiffre brut quand le chiffre
contrôlé disait l'inverse ; une erreur de vent mesurée contre une référence
qui était elle-même un modèle ; un filtre annoncé, mais inerte, parce que le
script lisait un champ absent des données.

### Les questions produit remontent

Règles de tenue et de séance, moteur de tracé, ce que le service peut
apprendre des sorties de chacun : rien ne se tranche à la place du
mainteneur. Chaque question entre dans un registre, avec la mesure qui
l'éclaire ; on avance sur ce qui n'en dépend pas. Aucune installation sur
une machine ou un serveur sans son accord : les agents préparent et
vérifient en local, le déploiement reste son geste. Ses constats de
dogfooding se notent au backlog ; ils ne se corrigent pas d'office.

## 3. Les outils et les sources, et pourquoi

**Python, sans cadre.** Python 3.12, `uv`, dataclasses, `argparse`,
`httpx`, SQLite pour l'index du cache. Pas d'ORM ; FastAPI et Pydantic
seulement dans le paquet `api/`, quand l'API est venue. Cinquante lignes
évidentes valent mieux que vingt lignes malignes.

**Le fichier comme dénominateur commun.** Quelle que soit la source, c'est
un FIT, un GPX ou un TCX qui se lit, avec un seul modèle d'activité en
sortie ; un connecteur ne fait que rapatrier des fichiers. Côté service, **on
ne garde jamais ce qu'on peut redemander** : une trace GPS porte le domicile
de chacun, et celui à qui une fuite se reprocherait, c'est l'ami qui l'a
confiée.

**Intervals.icu** donne, avec une clé personnelle, les activités, le FIT
d'origine de chacune et la séance planifiée du jour. Une séance peut aussi
venir d'un fichier `.zwo` ou `.mrc`.

**Open-Meteo**, gratuit et sans clé, interroge plusieurs points par appel.
Le modèle principal est AROME, la haute résolution de Météo-France ; un
second modèle donne un second avis, et leur désaccord devient un indice de
confiance. Trois leçons. AROME s'arrête à deux jours et demi, et un « hors
de portée » pris pour un « hors du domaine » faisait disparaître la météo à
J+2 : il fallait un repli sur le second modèle. Le quota se décompte **par
coordonnée**, pas par requête : une génération coûte plus d'une centaine
d'appels, d'où un cache mutualisé et des quotas par compte. La direction du
vent prévue tombe dans le bon secteur de 90° plus de neuf fois sur dix à un
ou deux jours, et se trompe une fois sur cinq à cinq jours : **pas
d'orientation au vent au-delà de trois jours.**

**BRouter**, auto-hébergé, plutôt que GraphHopper : libre, sans quota, des
profils vélo, un GPX natif, et les tags OpenStreetMap de chaque tronçon,
dont une estimation du trafic qu'il calcule lui-même. Ses pièges, tous
rencontrés : l'image stable lisait un format de données dépassé ; un
paramètre sous le mauvais nom était ignoré en silence ; un profil absent
répond par une erreur serveur sans corps ; `maxspeed` n'est pas exposé.
**Coolify**, sur un serveur du mainteneur, héberge BRouter, puis la page du
jour, l'API et l'interface.

**Garmin Connect** n'a pas d'API pour les particuliers : le GPX est le
socle, et le partage système du téléphone l'envoie vers l'application du
compteur. **Strava** n'a pas d'API de génération d'itinéraire, et sa carte de
popularité n'est ni exposée ni réplicable. Le dire vaut mieux que chercher
un ersatz.

## 4. Les réfutations mesurées

Des idées raisonnables sur le papier, qui ne tenaient pas sur le réel.

### Le modèle physique

**Laisser la calibration séparer traînée et roulement.** Ajustés ensemble,
CdA et Crr donnaient un CdA collé à sa borne basse et un roulement de vélo
tout terrain. La relecture de méthode a trouvé la cause : le vent
d'archive est mesuré à 10 m sur une maille de plusieurs kilomètres, donc
**avec erreur**, et une erreur sur un régresseur tire son coefficient vers
zéro (dilution de régression). Deux corrections ont décollé le CdA : le vent
ramené à hauteur de cycliste (facteur 0,6) et l'énergie cinétique de chaque
tronçon. L'une sans l'autre ne suffisait pas. Ce que les données mesuraient
bien, c'était la **résistance totale**, pas son partage.

**Figer le roulement, à une valeur de bitume ou au même chiffre pour deux
vélos « aux mêmes pneus », sans rien changer d'autre.** Dans les deux cas,
l'erreur croissait de façon monotone, sans optimum intérieur. Et les pneus
n'étaient pas les mêmes : même modèle, autre version. Figer le roulement
n'était pas faux ; seul, sur l'ajustement par tronçons plats, il l'était.

**La méthode qui a tenu** : **le roulement fixé par la littérature selon la
catégorie de pneu, et le CdA seul cherché**, sur l'erreur de temps en
mouvement des sorties plutôt que tronçon par tronçon, et sur les seules
sorties presque solo (voir la roue partielle, plus bas). Un vrai minimum
apparaît, au lieu d'une dérive. Le CdA obtenu est un **paramètre de
compensation** (il absorbe l'étalonnage du capteur, qui diffère d'un vélo à
l'autre) : il ne se compare ni à la littérature ni entre vélos. Le critère
d'acceptation a été réécrit : puissance à une vitesse donnée, biais proche
de zéro, erreur moyenne sur des sorties non vues.

**Le recoupement.** `comparer` mesure, sans modèle physique, l'écart de
vitesse entre les deux vélos à puissance égale. Converti en watts, il tombe
dans la fourchette que prédisent les deux calibrations prises séparément :
trois mesures indépendantes qui se recoupent.

### Le porte à porte

**Compter le coût des arrêts par feu et par stop.** Sur près d'un tiers
des sorties de validation, le temps simulé dépassait déjà le temps réel. Un
arrêt ne fait jamais gagner de temps : l'idée était invalidée, et l'avoir
gardée vivante après la mesure était l'erreur.

**La vraie cause** : une **roue partielle**, des sorties roulées en partie à
deux ou trois, sous le seuil qui écarte les sorties en groupe. La
corrélation entre la part de distance anormalement rapide et l'écart de
temps était forte (autour de −0,8), et les écarts négatifs disparaissaient
à mesure qu'on filtrait. Le dénivelé n'expliquait rien : le modèle calcule
déjà la pente point par point.

**Un facteur, puis une fourchette.** Sur les sorties propres, le porte à
porte valait environ 6 % de plus que le temps simulé. Mais l'erreur du
modèle sur **une** sortie est du même ordre que cette correction : un
chiffre unique aurait affiché une précision que le modèle n'a pas. Le porte
à porte est donc une **fourchette** (quartiles du rapport temps écoulé sur
temps simulé), mesurée par vélo sur les seules sorties de validation roulées
seul. Mesurée sur toutes les sorties, elle héritait de l'ajustement et
sous-estimait une sortie neuve. Faute de sorties, une convention générique
(×1,02 à ×1,14) s'applique et se dit.

**Arrondir la distance au plus proche plutôt qu'au-dessus.** Le placement
faisait alors un demi-tour, le parcours s'allongeait de plus d'un tiers et
le retour au calme triplait. Annulé. La vraie correction : séparer
l'élasticité de l'échauffement (qui place les blocs) de celle du retour au
calme (qui referme la boucle), et faire payer chaque minute de dépassement
peu, sans seuil.

### La campagne sans capteur, appliquée au mauvais cycliste

Au sprint 6, une campagne menée sur la chaîne **sans capteur** (fréquence
cardiaque, zone, physique) promettait un quart d'heure de gain sur deux
heures. Rejouée sur la puissance mesurée :

| correction | annoncé | mesuré | verdict |
|---|---|---|---|
| fenêtre glissante sur la puissance d'endurance | plusieurs minutes | sous le bruit | réfutée ici |
| masse datée par sortie | quelques watts | dégrade, seule | suspendue |
| roulement figé par surface | lève l'ambiguïté | régression | réfutée |
| CdA saisonnier | ~5 min | ~1 min, un seul vélo | redimensionnée |

Ce qui se corrige chez quelqu'un dont la constante est fausse n'apporte rien
à quelqu'un dont elle est juste. La fenêtre glissante a changé de
destinataire : le cycliste sans capteur.

**Déduire la zone 2 de la réserve cardiaque** : l'écart avec la zone réelle
s'aggravait. C'est le rapport entre le cœur et la puissance qui est
individuel, et aucune formule ne le devine. La fréquence cardiaque
**étiquette** une consigne ; elle n'entre jamais dans un calcul physique.

### Les routes et le terrain

**Les classes OSM comme mesure du trafic.** Au départ, `secondary` comptait
« à trafic ». Rejouées dans BRouter, les sorties réelles en portaient
environ un quart ; le poids appris est passé de trois kilomètres
équivalents à moins d'un demi. Le levier le plus simple s'est révélé être
de **privilégier les `tertiary`**, que le cycliste prend une fois et demie
plus que ce que le moteur propose. L'estimation de trafic de BRouter
confirme vue de l'autre côté : sur les classes les plus hautes, il en prend
environ la moitié de l'attendu, et un contrôle (la part sans classe,
restée neutre) aurait démenti un artefact.

**Les routes déjà roulées comme critère.** Refusé en doctrine, et c'est la
réfutation la plus importante du projet. Le jour où elles entrent dans le
score, l'outil renvoie au cycliste ses habitudes en prétendant les avoir
trouvées, et toute validation devient circulaire. Les routes connues sont un
**instrument de mesure** : elles s'affichent, servent d'étalon, et n'entrent
ni dans une note, ni dans un tri, ni dans une sélection.

**Moins de feux et de passages piétons, c'est ce qu'il préfère.** Ses
sorties réelles en portent environ **deux fois plus** au kilomètre que les
boucles proposées : il roule de bourg en bourg, « parce que je ne connais
pas les routes de contournement ». Ses sorties sont la référence à battre,
pas la cible à imiter. Il accepte de s'arrêter dans un village ; il refuse
une route passante.

**Les feux sous les blocs** : aucune différence nette avec les
récupérations, un résultat nul qui en est un. **La popularité des routes** :
aucune source libre, et les itinéraires balisés sont un contre-signal.

### Le vent

**« Sur une boucle, le vent s'annule. »** Faux : la part de vent de face
médiane est d'environ un tiers, et bien plus sur certaines sorties, parce
que les routes ne sont pas réparties également dans toutes les directions.
Un bloc de vingt minutes couvre près de 45 % de distance en plus vent dans
le dos que vent de face : de quoi poser en plein bourg un bloc annoncé sur
une route dégagée.

**Le contrôle qui prouve le signe** : sur des milliers de tronçons, avec la
vitesse GPS pour oracle, l'erreur baisse avec le vent et monte nettement
avec le vent retourné. Le critère d'origine, lui, comparait notre part de
vent de face à celle d'Intervals.icu : il mesurait un désaccord de
vocabulaire sur la largeur du secteur, pas une erreur de calcul.

**Plus de candidates pour trois propositions contrastées.** Au-delà de
quelques candidates, Open-Meteo refuse pour excès de requêtes, sans
troisième contraste. Une sortie d'endurance, par temps sec et sans vent,
éteint quatre axes sur sept : deux propositions honnêtes valent mieux que
trois qui se ressemblent, et la commande nomme les axes muets.

**Un seuil sur le score du géocodeur.** Une réponse juste et une réponse
arbitraire avaient le même écart de score. La commune, elle, les séparait
toujours : on l'exige, et on refuse quand les candidats en désignent
plusieurs.

## 5. La validation rétrospective du terrain sous un bloc

Les poids qui notent le terrain sous un bloc (zone bâtie, descente,
virages) sont confrontés aux emplacements où le cycliste a **réellement**
fait ses blocs, sur deux sorties de référence, contre des emplacements tirés
au hasard sur la même boucle. Le script lit le cache réel et n'est pas
collecté par la suite de tests :

```bash
uv run python scripts/validation/terrain_retrospectif.py
```

**Critère** : la note médiane des emplacements réels vaut au plus 70 % de
celle du hasard. **Résultat** : environ un tiers. La composition au
kilomètre en apprend plus. Les zones bâties sont quasi absentes sous les
vrais blocs : c'est le poste le plus discriminant. La descente vaut un peu
plus de la moitié du hasard, les virages les trois quarts, l'irrégularité
de la pente ne sépare rien. Et la montée dépasse le hasard : il ne fuit pas
les côtes, ni les carrefours. Les poids ont été corrigés dans ce sens.

**Le prix d'une descente dépend de l'intensité.** « Z5 en descente, pas
possible ou presque. » Son poids est multiplié par un facteur de zone :
×0,4 en endurance, ×1 au tempo, ×2 au seuil, ×4 au-delà. Blocs réels et
tirages sont notés à la même intensité. Le facteur a **amélioré** la
discrimination (de plus de 40 % à un tiers), parce que les tirages portaient
plus de descente que les emplacements choisis.

**Ce qui fait foi.** Le mode nominal lit les intervalles **marqués** dans
Intervals.icu : les blocs prescrits et exécutés. Le mode sans réseau les
**devine** d'après la puissance, en trouve trop, coupe un long bloc en
trois, et conclut juste au-dessus du seuil : c'est la conclusion honnête
d'un mode qui borne mal les blocs, pas un désaveu des poids. Le script
échoue quand les deux modes divergent.

**Deux limites.** Le poids d'un carrefour n'est validé par aucune mesure :
une trace GPS ne porte pas de nœud OpenStreetMap. Et seuls les blocs de
moins de 6 km jugent les poids : sur un bloc long, le cycliste roule là où
il en est rendu.

**Le constat qui justifie l'outil** : sur une sortie de référence, deux
longs blocs étaient tombés sur un couloir médiocre quand un couloir plus de
trois fois meilleur existait sur la même boucle. Le même geste a servi au
vent, aux marqueurs urbains et au trafic estimé (`scripts/validation/`).

## 6. Ce qui reste possible

Le backlog notable, sans ordre : c'est au mainteneur de le classer.

**Pour le cycliste** : **demander un relief** (plat, vallonné, qui
grimpe, montagne) et dire quand il est introuvable ou contredit les blocs ;
**analyser un parcours qu'on a déjà** (pluie, vent par tronçon, durée en
fourchette : les briques existent, pas l'écran) ; les **randonnées au long
cours**, sur plusieurs jours ; **plus de choix** quand la déduplication ne
laisse qu'une boucle ; **envoyer au compteur** au-delà du partage, par l'API
cloud de Wahoo, ou par fichier pour COROS et Hammerhead.

**Pour le modèle** : le **coût réel d'un arrêt**, relance comprise, que le
modèle ne connaît pas (préalable : régler la roue partielle) ; le **seuil
de détection de groupe**, jamais réglé ; les **sorties de club** que la
calibration sur fichiers importés ne reconnaît pas sans leur nom ; la
**stabilité à petit nombre** de sorties ; la **boucle de correction**, pour
que le réglage du premier jour se corrige sur les sorties suivantes ; le
**CdA saisonnier**, qui attend des arbitrages.

**Pour le tracé** : la concentration des feux plutôt que leur nombre ; la
distance de dégagement urbain, parce que le service rendu n'est pas le même
en ville et à la campagne ; un mode circuit quand il n'existe pas de
couloir ; un dimensionnement qui compte la distance des demi-tours.

**Pour le service** : l'**import par lien**, voie principale décidée dont
seul le secours (le téléversement) existe ; le lien est un secret, jamais
journalisé ni conservé, une garde doit refuser les adresses internes, et il
expire vite. Puis un stockage d'objets pour les fichiers, un état
d'embarquement qui distingue un profil neuf d'un profil incomplet, la
provenance du dénivelé à l'écran.

**Et toujours** : le dogfooding. Un bloc mal placé ne se voit qu'en roulant.

## 7. Ce qu'on en retient

Une mesure qui réfute la prémisse d'un lot vaut mieux que le lot. Le sens
d'un écart en dit souvent plus que sa taille. Un contrôle qui aurait pu
démentir vaut plus que le chiffre principal. Un test vert ne prouve rien
tant qu'un mutant ne l'a pas fait rougir. Une phrase affichée doit être
vraie, surtout quand elle flatte. Et les habitudes du cycliste mesurent
l'outil ; elles ne le pilotent pas.

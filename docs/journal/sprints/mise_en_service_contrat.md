# Contrat — Mise en service (après le sprint 5)

Rédigé le 16/09/2026. Cinq correctifs, tous trouvés **à l'œil par le
mainteneur sur de vraies sorties**, aucun par un test. Ordre d'importance :
on corrige d'abord ce qui l'empêche d'observer, parce que l'observer est le
contrôle qui a trouvé tous les autres.

Aucun de ces défauts n'est une régression du sprint 5 ; ils sont documentés en
Q19 à Q23 de `docs/journal/questions/questions_mainteneur.md`, qui fait foi pour le détail.

## 1. La carte (Q20) — le plus urgent

**Quatre empêchements se cumulent, et aucun n'est grave seul.** C'est pour ça
qu'une carte dont toutes les données sont présentes paraît vide.

a) **La boucle de la proposition sélectionnée n'est pas dessinée.**
`carte.py` construit la polyligne grise de la boucle complète pour chaque
proposition mais ne l'ajoute que pour les **non sélectionnées**. La
sélectionnée ne montre que ses blocs et ses liaisons : la portion qu'elle ne
parcourt pas, au-delà d'un demi-tour, n'est peinte par personne.
→ La sélectionnée dessine **aussi** sa boucle en fond, sous ses blocs.

b) **Le pointillé change de sens, et c'est la règle du mainteneur** : « les
pointillés sont très mal lisibles, il faut les réserver à la trace non
sélectionnée ». Aujourd'hui le pointillé veut dire « ce n'est pas un bloc »
(héritage de L5.2) ; il doit vouloir dire « ce n'est pas la sélection », **et
rien d'autre**. Un seul sens au lieu de deux.
→ La proposition active est **pleine de bout en bout** : blocs en couleurs
vives, reste du parcours en couleur franche, boucle non parcourue en fond.
Les autres propositions passent en **pointillé gris**.

c) **Conséquence de (b) à ne pas manquer** : une séance **sans bloc** — le cas
courant du mainteneur, son plan n'a aucune séance à blocs planifiée — n'a
aujourd'hui que des liaisons, donc toute la sortie est pâle et pointillée.
Avec la nouvelle règle elle devient pleine, comme elle doit l'être.

d) **Le cadrage est trop large.** Deux boucles de 56 km de tour (~18 km de
diamètre) s'affichent dans une vue de ~150 km. Hypothèse à vérifier : le
conteneur est large et peu haut, `fitBounds` ajuste sur la hauteur et laisse
filer la largeur. Corriger côté mise en page ou côté cadrage — **et vérifier
à l'œil sur une vraie page**, c'est le seul juge.

**Critère d'acceptation** : sur la sortie du 19/09 (sans bloc) et sur une
séance à blocs, les boucles remplissent la carte, la sélectionnée se distingue
au premier coup d'œil, et les autres se lisent sans être confondues avec le
fond.

## 2. Le repli météo (Q19)

`ourouler sortie --jour J+2` et `J+3` perdent **toute** la météo : ni pluie,
ni vent, ni tenue. C'est le cas d'usage le plus naturel du produit — préparer
mercredi la sortie du club de samedi.

**Diagnostic fait** : `meteo/openmeteo.py::_hors_domaine` conclut « hors de la
grille » sur deux signatures, dont **un bloc entièrement nul**. Or un bloc nul
est aussi ce qu'Open-Meteo rend **au-delà de la portée du modèle**. AROME
publie à 67 h ; la sortie du club est à 72 h. L'heuristique confond une limite
d'espace et une limite de temps.

Trois corrections, par ordre :

1. **Le repli automatique.** Quand le modèle principal ne couvre pas la
   fenêtre, basculer sur le modèle global **déjà configuré** (`second_avis`)
   et **le dire dans l'en-tête** : « AROME ne va pas jusqu'à samedi,
   prévision ICON ». C'est la règle 5 appliquée à la météo — deux modèles qui
   divergent s'affichent, mais **un modèle muet ne doit pas emporter les
   deux**. À écrire même si le diagnostic évolue.
2. **Distinguer les deux causes** : la portée se lit dans la réponse
   elle-même (dernière heure non nulle).
3. **Le conseil `--modele` est faux** : `sortie` n'a pas cette option. Un
   message de la couche connecteur ne doit pas nommer une option de ligne de
   commande qu'il ne connaît pas.

**Vérifié** : en basculant le modèle principal sur `icon_seamless`, la sortie
du 19/09 rend la pluie, le vent, la tenue — et **trois propositions au lieu de
deux**, dont « vous rentrez avec le vent dans le dos ». Le défaut n'amputait
pas que la météo, il amputait le produit.

**Critère d'acceptation** : `ourouler sortie --jour <J+3>` rend la météo et la
tenue, en nommant le modèle utilisé.

## 3. La fausse alerte d'amputation (Q21 a)

« 1 h 59 (⚠ séance amputée de 1 min) » pour 2 h prescrites — **0,8 %**.

Ses mots : « 1 min en plus ou en moins n'est pas un seuil important, faire une
alerte quand on est à 5 % de différence de durée, pas moins ».

**Sa règle des 5 % est déjà dans sa configuration** :
`ParametresSeance.elasticite_calme_min = -0.05`, et `placement.py` s'en sert
déjà pour décider d'un « retour au calme raccourci ». **Corriger en honorant
la valeur existante, pas en ajoutant un second seuil** : il a déjà répondu à
cette question, dans son fichier.

## 4. « 57 % de grands axes » (Q21 c)

Décision du mainteneur : **afficher le % de `primary` seul, et un pourcentage
urbain**. La catégorie composite disparaît.

Mesuré : `trunk` vaut **zéro** sur 381 km dans huit directions — BRouter n'y
envoie jamais un vélo — et `secondary` porte les deux tiers du chiffre alors
qu'il n'en a cure. L'étiquette multipliait par quatre ce qui devait
l'inquiéter.

**Dans ce lot : le % de `primary` seulement.** Le pourcentage urbain demande
la mesure par **étendue** et non par densité (Q17, Q21 b) — un village
traversé coûte peu, une agglomération coûte cher — qui n'est pas écrite. Elle
relève du sprint 6.

## 5. Les fichiers dans le dépôt (Q23)

Sans `--carte` ni `--sortie`, `sortie_AAAAMMJJ.gpx` et `.html` atterrissent
dans le répertoire courant, donc dans le dépôt. Aucune fuite possible
aujourd'hui — `.gitignore` les couvre — mais ils portent ses coordonnées de
départ. **Un fichier que seul `.gitignore` protège n'est pas protégé, il est
seulement discret.**

→ Destination par défaut hors du dépôt : `~/ourouler/` ou le répertoire de
cache déjà configuré.

## Ce qui n'est pas dans ce lot

Les règles de routage issues de Q25 à Q27 (`trunk` interdit, `primary`
pénalisé, `secondary` selon l'intensité, cible de calibration à 48 % de
`tertiary`) : c'est un lot de fond, mesuré et cadré, mais qui touche la
génération de boucles et demande une calibration. Sprint 6.

Le profil d'altitude qui superpose les blocs après un demi-tour (même cause
que Q20 a : un affichage resté sur le tracé quand le reste est passé au
compteur). Sprint 6.

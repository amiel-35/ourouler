# Doctrine du système de jetons — « suisse vivante »

Écrite le 20/09/2026, à la demande explicite du mainteneur : *« avec une
doctrine sérieuse de design system, même si l'appli n'a pas d'ambition. »*
Les deux moitiés de cette phrase tirent en sens opposés, et c'est
volontairement tenu ainsi dans tout ce document : **la rigueur est dans la
méthode, pas dans le volume.** Onze écrans, douze composants partagés, un
seul mainteneur — ce n'est pas un système pour cinquante produits. Un
système de jetons bien nommés, en deux couches, avec une règle d'admission
restrictive, vaut infiniment mieux que deux cents jetons exhaustifs que
personne ne retient.

C'est ce document qu'un agent doit lire **avant** d'ajouter un écran, un
composant ou un jeton — pas `jetons-systeme.css` seul, qui ne porte que le
résultat, pas les règles qui l'ont produit.

## 1. Deux couches, jamais une

- **Les primitives** (`front/directions/jetons-suisse-vivante.css` et la
  section « PRIMITIVES AJOUTÉES » de `front/directions/jetons-systeme.css`)
  portent une valeur brute à un rang : une teinte à un palier (`--sv-pluie-
  600`), une taille à un rang (`--sv-taille-4`), une durée (`--sv-duree`).
  Une primitive ne dit jamais à quoi elle sert.
- **Les jetons sémantiques** (le reste de `jetons-systeme.css`) portent un
  rôle : « la couleur de la pluie forte » (`--couleur-pluie-trait`),
  « l'espace entre deux blocs » (`--espace-section`). Chacun est un alias
  vers une primitive ; aucun n'invente une valeur qui n'existe pas déjà dans
  la couche du dessous.

**Les écrans, et tout composant qui en dérive, ne référencent que la couche
sémantique.** Un `.tsx` ou une feuille de style d'écran qui écrit `var(--sv-
pluie-600)` est un bug de doctrine, au même titre qu'un module du cœur qui
lit une variable d'environnement (règle absolue 2 de `CLAUDE.md` — la même
discipline, appliquée à un autre étage du produit).

**Pourquoi ça compte, concrètement** : si le mainteneur décide un jour que
le bleu de la pluie est trop froid, on change une valeur, à un seul endroit
(`--sv-pluie-600`), et tout ce qui l'utilise suit — sans grep ni relecture de
chaque écran. Sans la coupure entre les deux couches, ce changement demande
de chercher la couleur dans trente fichiers, exactement l'exemple donné par
le mainteneur en posant cette exigence.

## 2. La convention de nommage, en une phrase

> **Si le nom commence par `--sv-`, c'est une primitive — un écran ne
> l'utilise jamais directement.** Sinon, c'est un jeton sémantique, nommé
> d'après ce qu'il représente dans le produit, jamais d'après son
> apparence.

Corollaires tenus dans tout le système :

- Un jeton sémantique se nomme `<rôle>` ou `<rôle>-<nuance>`, en français,
  sans abréviation cryptique (`--espace-bloc`, pas `--sp-4` ; `--couleur-
  pluie-trait`, pas `--bleu-fort`).
- Une couleur de donnée se nomme `--couleur-<métier>-<usage>`, où `<usage>`
  est toujours l'un des trois rôles fixes : `fond` (aplat sous du texte),
  `remplissage` (aire, jauge, tracé), `trait` (ligne, icône, jamais de texte
  dessus). Jamais un quatrième usage inventé pour une occasion.
- Un état interactif se nomme `--interactif-<état>-<propriété>`
  (`--interactif-survol-fond`), jamais par le composant qui l'utilise — le
  même jeton sert le bouton, l'onglet et le segment, parce que c'est le même
  état.
- Une primitive se nomme `--sv-<famille>-<rang>`, où `<rang>` est neutre
  (un nombre, jamais un mot qui dit l'usage) : `--sv-pluie-600`, pas
  `--sv-pluie-soutenue`.

Un système où il faut deviner le nom du jeton suivant est un système qu'on
contourne. Si vous cherchez plus de dix secondes le nom d'un jeton qui
devrait exister, c'est probablement qu'il porte déjà ce nom, ou qu'il manque
et qu'il faut l'ajouter par la règle ci-dessous — pas en réinventer un.

## 3. La règle d'admission — restrictive par défaut

**Refuser un jeton est presque toujours le bon réflexe.** Un jeton n'entre
dans le système que si les trois conditions suivantes tiennent toutes :

1. **Un besoin réel l'exige** — un écran, un composant, ou l'inventaire
   documenté (`docs/ux/inventaire_systeme_visuel.md`) le demande
   effectivement. Un jeton posé « au cas où » n'entre pas.
2. **Aucun jeton existant ne répond déjà**, même approximativement. Une
   valeur à 2 px d'un rang existant se règle en arrondissant à ce rang, pas
   en ajoutant un rang intermédiaire. C'est le sens de l'échelle : elle doit
   rester assez courte pour qu'on la retienne.
3. **Le rôle est distinct d'un rôle déjà nommé.** Si le nouveau besoin est
   « la même chose que `--espace-bloc`, mais pour un autre composant »,
   c'est `--espace-bloc` qui s'applique, pas un troisième jeton.

**Quand un besoin réel ne trouve pas de réponse malgré ces trois filtres**,
il rentre par la même porte que tout le reste : une primitive d'abord (si la
valeur brute n'existe pas), un jeton sémantique ensuite, avec un commentaire
qui dit quel composant en a besoin et pourquoi aucun jeton existant ne
suffisait. C'est exactement ce que ce lot a fait pour l'espacement,
l'épaisseur des traits et l'intensité d'effort (Z1–Z5) : trois ajouts, tous
justifiés par un besoin déjà présent dans le code, aucun par anticipation.

**Ce qui n'entre jamais** : un jeton par composant (« --couleur-bouton-
special »), un jeton pour une valeur utilisée une seule fois (une valeur en
ligne, commentée, suffit), un jeton qui duplique une primitive existante
sous un autre nom pour « faire plus clair ».

## 4. Une source unique de vérité

Aucune valeur n'est écrite deux fois. En particulier :

- Un contraste WCAG est **calculé une fois**, par un script (voir la
  méthode dans l'en-tête de `jetons-suisse-vivante.css` et de
  `jetons-systeme.css` pour l'échelle d'effort), et son résultat vit en
  commentaire à côté de la primitive qu'il vérifie — jamais recalculé à
  l'œil ailleurs, jamais réécrit dans un second fichier.
- `composants-systeme.css` ne redéfinit **aucune** couleur, taille ou durée
  en dur : chaque déclaration y référence un jeton sémantique. Si vous
  trouvez un hexadécimal ou un `px` nu dans ce fichier en dehors des
  définitions de jetons elles-mêmes, c'est une régression de doctrine.
- La page de démonstration (`front/directions/systeme-composants.html`)
  n'invente pas non plus de couleur : sa propre feuille de style inline ne
  pose que de la mise en page (grilles, largeurs), jamais une teinte.

## 5. Les composants se documentent par leurs états

Un composant n'est pas décrit par une capture d'écran : il est décrit par la
liste de ses états, parce que c'est cette liste qui manque le plus souvent
à l'application et se retrouve improvisée à ce moment-là — exactement ce qui
s'est produit une première fois dans `front/src/style.css` (« aucun bouton,
aucun champ, aucun lien n'avait de survol, de pression ni de focus clavier
visible »).

`composants-systeme.css` documente, pour chaque composant qui en a besoin,
les états parmi : **repos, survol, focus, actif/pressé, désactivé, en cours
de chargement, en erreur, vide.** Tous ne s'appliquent pas à tous les
composants (un `Barriere` n'a pas de survol ; un `Attente` n'a pas de
désactivé) — mais l'absence d'un état dans un composant qui pourrait
raisonnablement l'avoir est un manque à combler, pas un silence à
interpréter.

Un composant qui gagne un état à l'usage (un exemple donné pour mémoire :
un bouton qui devient aussi annulable en cours de clic) voit son état
ajouté à `composants-systeme.css` avec un commentaire qui dit d'où vient le
besoin — jamais improvisé directement dans un `.tsx` au moment de
l'application.

## 6. Comment le système évolue

- **Une teinte change** (par exemple : le mainteneur juge le bleu de la
  pluie trop froid après usage). On modifie la primitive concernée dans
  `jetons-suisse-vivante.css` (ou `jetons-systeme.css` pour l'effort), on
  recalcule et on remet à jour les contrastes commentés en tête de fichier,
  on ne touche à rien d'autre — la couche sémantique ne bouge pas, les
  composants non plus.
- **Un composant gagne un état.** On l'ajoute dans `composants-systeme.css`,
  à la section du composant concerné, avec les jetons sémantiques
  existants — un nouvel état ne justifie presque jamais un nouveau jeton
  (voir §3) : un état se construit d'ordinaire en recomposant ce qui existe
  déjà (poids de trait, remplissage encre/papier, atténuation du texte).
- **Un écran a besoin de quelque chose que le système n'a pas.** On vérifie
  d'abord si c'est vraiment absent ou si un jeton existant répond déjà mal
  nommé pour qu'on l'ait cherché ailleurs (auquel cas c'est peut-être le nom
  qu'il faut revoir, pas ajouter un doublon). Si le besoin est réel et
  distinct, on l'ajoute par la règle d'admission (§3), dans le fichier
  correspondant, avec le commentaire qui justifie l'ajout — jamais en valeur
  brute dans l'écran qui en a besoin.
- **Un nouveau composant partagé apparaît.** Il se documente dans
  `composants-systeme.css` selon le même gabarit que les douze déjà
  couverts (à quoi il ressemble, ses états, ses éventuelles teintes de
  donnée) et rejoint la page de démonstration.
- **Ce que ce système ne fait pas, et ne fera pas sans décision du
  mainteneur** : gérer plusieurs marques, plusieurs plateformes visuelles
  distinctes, ou un outillage de génération de jetons. Deux thèmes (clair,
  sombre) et un seul produit — l'ajout d'un troisième thème ou d'une
  variante de marque est une décision produit, pas une extension mécanique
  de ce fichier.

## 7. Ce que ce lot a dû trancher, faute de précision dans la direction

`docs/ux/direction_visuelle.md` pose trois règles fermes sur la couleur des
**mesures**, mais ne dit rien de l'espacement, des états interactifs, des
messages système, ni de l'intensité d'effort. Ce lot a donc pris position
sur cinq points, chacun documenté en commentaire à l'endroit où il
s'applique et repris ici pour mémoire :

1. **Les messages système (`.encart`) perdent toute couleur.** Sous la
   règle 1 (« si c'est coloré, c'est une mesure »), un avertissement ou une
   erreur n'a pas droit à une teinte — ce n'est pas une donnée mesurée. La
   sévérité se lit désormais au poids du filet gauche et à une amorce en
   capitales (« Attention », « Ça n'a pas marché »), jamais à une couleur.
2. **L'intensité d'effort (Z1–Z5) devient un cinquième métier**, avec sa
   propre teinte (un ambre, qu'aucune des quatre familles météo/route
   n'utilise) et cinq crans au lieu de trois, parce que c'est une échelle
   ordinale à cinq niveaux, pas trois paliers d'une même mesure. Elle
   n'apparaît jamais dans la même vue qu'une donnée météo, donc ce
   cinquième métier ne viole pas « une teinte, une catégorie ».
3. **Les décisions de l'algorithme (`Arbitrage` : verdicts, matrice) restent
   entièrement en encre.** Le sort d'une candidate (retenue/écartée/place
   prise) est une décision, pas une mesure — règle 3, appliquée au-delà de
   la seule rose des directions. Le poids du filet et du texte la portent,
   jamais une couleur.
4. **`--sv-encre-att` (6,8:1 en clair) est en dessous du seuil que le
   mainteneur avait explicitement porté à 7,5:1** dans `front/src/style.css`
   pour la lisibilité en plein soleil. Ce n'est pas silencieux — signalé en
   commentaire dans `jetons-systeme.css` — et volontairement **non
   corrigé** par ce lot : durcir cette primitive appartient à
   `jetons-suisse-vivante.css`, hors de son périmètre, et c'est une décision
   produit (le mainteneur a-t-il vraiment besoin de ce demi-point
   supplémentaire avec la nouvelle typographie, plus grande ?), pas une
   décision de système.
5. **Un bloc n'a plus de fond ni de bordure pleine.** La direction retire
   les cartes empilées ; ce lot en tire la conséquence jusqu'au bout : un
   `.bloc` se délimite par un filet horizontal et du padding, jamais par une
   boîte — y compris là où l'ancien système utilisait un fond (`.bloc.doux`)
   pour distinguer un regroupement.

## Voir aussi

- `docs/ux/direction_visuelle.md` — la direction elle-même, ses trois règles
  et ses interdits.
- `docs/ux/inventaire_systeme_visuel.md` — le contrat : chaque classe
  réellement utilisée par l'application et sa réponse dans ce système.
- `front/directions/jetons-systeme.css` — les jetons, primitives et
  sémantiques.
- `front/directions/composants-systeme.css` — les composants, par leurs
  états.
- `front/directions/systeme-composants.html` — la démonstration, clair et
  sombre.

# La direction visuelle — « suisse vivante »

Retenue par le mainteneur le 19/09/2026, au terme d'une journée de
propositions. **Rien n'est encore appliqué** : la direction vit dans une page
de démonstration et un fichier de jetons, les écrans n'ont pas bougé.

## Ce qu'elle est

La **rigueur suisse** — grille, filets horizontaux, la typographie qui
hiérarchise, aucune ombre, aucun arrondi, aucune carte empilée — portant des
**données dessinées** en **couleurs très claires**.

Trois règles la tiennent :

1. **L'interface est en noir et blanc, les données sont en couleur.** Si
   quelque chose est coloré, c'est une mesure.
2. **Une teinte, une catégorie.** Jamais la pluie et le vent dans la même
   couleur. Le vent traversier n'a délibérément aucune teinte — une économie
   assumée, pas un oubli.
3. **Une décision n'est pas une donnée mesurée.** La direction recommandée
   n'est donc **pas colorée** : elle est cerclée d'un trait d'encre épais.
   C'est la conséquence la plus littérale de la règle 1, et elle a conduit à
   retirer la couleur de recommandation que la proposition suisse d'origine
   utilisait.

Les couleurs sont pâles **parce que** tout le reste est noir et blanc : dans
une grille où rien d'autre n'est coloré, une teinte pâle suffit à signifier.
Elle chuchote au lieu de crier.

**Et la légèreté est dans la couleur seule** : la structure reste dure —
traits nets, alignements stricts, contrastes typographiques marqués. Sans
ça, « ultra léger » glisse vers le beige poli, exactement ce que le
mainteneur a rejeté cinq fois dans la journée.

## Ce qui la compose, et d'où ça vient

| ce qu'on prend | à qui | ce qu'on refuse de lui |
|---|---|---|
| la grille, les filets, la hiérarchie typographique | direction *suisse éditoriale* | son rouge de recommandation |
| le disque des huit directions, les grands chiffres | direction *sportif grand public* | sa grammaire de cartes, son roux de marque |
| « une teinte, une catégorie » | direction *asiatique* | sa rondeur, sa palette vive |

## Conséquence d'accessibilité, non négociable

Un aplat pâle porte **moins** d'information qu'un aplat saturé. Le canal
non-coloré cesse donc d'être un supplément : hachure pour l'effort,
quadrillage pour la route passante, motif pour le désaccord entre modèles,
et **le mot écrit en toutes lettres partout**. Contrastes vérifiés par
calcul, pas à l'œil. Règle tenue par construction : **aucune teinte soutenue
ne porte jamais de texte**.

## Interdits, hérités du chemin parcouru

IBM Plex sous toutes ses formes, Inter, Space Grotesk. Tous les fonds crème,
papier, ivoire, beige, blanc cassé chaud. Les titres en serif sur fond chaud.
Les gris chauds avec un accent terracotta. Les ombres douces. Les arrondis
partout. Le pastiche vintage — carnet jauni, guide ancien, carte pliée : le
même défaut générique avec un déguisement.

Le verdict qui les a fait tomber, mot pour mot : *« c'est très IA, limite
Anthropic fait une appli de vélo »*, puis *« le IBM Plex, le crème, c'est vu
et revu — vous faites tout le temps ça »*.

## Ce que cette journée a appris sur la méthode

**Le modèle ne décide pas le goût, le brief le décide.** Trois modèles
différents — Sonnet, Opus, Fable — avec le même brief détaillé ont convergé
sur la même chose : l'instrument de navigation sombre, une police de
signalisation routière. Quatre briefs différents sur un seul modèle ont
produit quatre propositions franchement distinctes.

La correction est du mainteneur : **un brief de design ne décrit pas les
blocs à dessiner, il décrit le besoin et les parcours.** Le premier tour
demandait « une section logo, une palette, une rose des vents, un tracé » —
et s'étonnait que huit propositions se ressemblent. Le second ne disait que
ce que le produit fait et qui s'en sert.

**Et un résultat que personne n'avait cherché** : trois propositions sur
quatre ont indépendamment fait du **désaccord entre modèles météo** leur plus
bel élément visuel. La règle absolue 5 — ne jamais moyenner deux prévisions
qui divergent — s'avère être ce qu'il y a de plus dessinable dans ce produit,
et ce qui le distingue le plus des autres.

## Où sont les pièces

Page de démonstration et jetons dans le worktree de l'agent qui l'a composée,
branche `worktree-agent-ae336fbd1f5bcb510` :
`front/directions/suisse-vivante.html` et
`front/directions/jetons-suisse-vivante.css`.

Les sept autres propositions vivent dans leurs worktrees respectifs. Elles ne
sont pas à jeter : ce sont les pièces qui ont permis de composer celle-ci, et
la trace de ce qui a été essayé.

## Ce qui reste à faire

Appliquer. Aucun écran n'a été touché — c'est un lot à part entière, et il
devra traiter au passage les trois défauts d'usage relevés le même jour :
`Assistant` et `Importer` n'ont **aucun bouton retour**, les vues ne vivent
pas dans l'URL (le retour arrière du navigateur sort de l'application), et le
vent n'est dessiné qu'à huit points du tracé alors que `ChampVent` le donne
en tout point.

# Briefer une IA pour du design

Ce qu'on a appris le 19/09/2026 en faisant produire huit directions visuelles
pour `ourouler`. Le document est ici parce que c'est là qu'il a été gagné,
mais **il ne parle pas de ce projet** : il vaut pour toute délégation où l'on
attend autre chose que ce qu'on avait en tête.

## La règle, en une phrase

**Demander des fonctionnalités sans donner leur représentation graphique.**

Formulée par le mainteneur, après avoir constaté que la consigne la plus
déterminante de tout le brief était celle qu'on n'avait pas vue passer.

## Ce qui a été fait

**Premier tour.** Un brief, quatre agents — Sonnet, Opus, Fable, plus un
quatrième avec mandat de rompre. Le brief était détaillé sur **deux choses** :
la structure du livrable (« montre un logo, une palette, une typographie, une
rose des vents, un tracé, l'écran du jour, les composants ») et l'espace des
références (« instruments de bord, échelles météo, barbules de vent,
signalisation routière, diagrammes scientifiques »).

**Deuxième tour.** Un seul modèle, quatre briefs. Le brief commun ne décrivait
plus que le produit, l'utilisateur, ses conditions d'usage et ses parcours —
**rien sur ce qu'il fallait montrer, rien sur quoi s'inspirer**. Chacun
recevait un mandat esthétique différent.

## Ce qu'on a observé

Au premier tour, **trois modèles différents ont produit la même chose** :
instrument de navigation, fond sombre, police issue de signalétique routière.
Marine, marine, aviation. Barlow, Overpass, B612. Seul le quatrième — celui à
qui on avait demandé de rompre — a divergé.

Au deuxième tour, **un seul modèle a produit quatre choses franchement
distinctes** : un tableau, un disque, un compas, une boussole.

## Le mécanisme

**Ce n'est pas « précis contre flou ».** Les deux briefs étaient précis. Le
second l'était davantage : il décrivait le cycliste debout dans son couloir à
six heures du matin, le téléphone dans une main.

**C'est précis sur le problème contre précis sur la solution.**

La précision sur le problème **enrichit** l'espace de recherche : plus on
décrit l'usage, plus il existe de façons valables d'y répondre. La précision
sur la solution le **referme** : nommer l'artefact attendu, c'est le décrire à
un niveau qui suffit à le reproduire.

### Une fonctionnalité nommée par sa forme est déjà une décision de design

« Une rose des vents » n'est pas une fonctionnalité, c'est **une réponse**. La
fonctionnalité était « comparer huit directions d'un coup d'œil ». La preuve
qu'il s'agissait d'une décision et non d'un besoin : libérée de la contrainte,
la même demande a produit quatre autres formes, toutes valables.

**Et le piège est propre à l'IA.** Un designer humain à qui l'on dit « mets
une rose des vents » répond « pourquoi une rose ? ». Un modèle l'exécute. Il
ne pousse pas, il ne négocie pas, il ne s'étonne pas. Tout ce qu'on écrit sans
y penser devient une spécification.

### Une suggestion n'est pas plus faible qu'une instruction

Les « pistes » du premier brief — barbules, signalisation, instruments —
étaient données comme de l'inspiration. Elles ont fonctionné comme un cahier
des charges. **Un modèle traite une référence nommée comme une cible**, pas
comme un exemple.

C'est le piège principal, et il est invisible au moment d'écrire : on croit
ouvrir une porte, on en ferme sept.

### Une contrainte négative déplace l'attracteur, elle ne le dissout pas

Après le rejet d'une première série, on a interdit nommément IBM Plex, les
fonds crème, les serifs sur fond chaud. Les propositions suivantes ne sont pas
devenues originales : elles ont convergé vers **un autre point commun**,
l'instrument sombre.

Interdire une réponse ne crée pas de variance. Ça change où tout le monde
atterrit.

### Le modèle est une variable faible devant le brief

C'était la question de départ. La réponse est nette : trois modèles sous les
mêmes contraintes de solution donnent presque la même chose ; un modèle sous
quatre contraintes différentes donne quatre choses.

**Pour obtenir de la variance, varier le brief.** Changer de modèle ne
l'achète pas.

### Un dispositif marche là où l'exhortation échoue

Le premier brief disait : « prends un vrai parti, une direction que le
mainteneur pourrait détester ». Aucun des trois ne l'a fait.

Le quatrième disait autre chose : **« écris d'abord, pour toi, la proposition
que tu ferais par défaut. Puis ne la fais pas. »** Celui-là a divergé — et sa
réponse évitée, qu'il a consignée, décrivait exactement ce que les trois
autres avaient produit.

Demander l'audace ne produit rien. **Rendre le défaut explicite pour pouvoir
le refuser** produit quelque chose.

## Les règles qui en découlent

1. **Décrire le problème, pas l'artefact.** Ce que ça fait, pour qui, dans
   quelles conditions, quels parcours, comment on juge que c'est réussi.
   Jamais la liste des blocs attendus.
2. **Ne nommer aucune référence qu'on ne veuille pas voir copiée.** En nommer
   une, c'est la commander.
3. **Mettre la variance dans le brief**, explicitement, une par exécution. Pas
   dans le modèle, pas dans la température, pas dans le nombre d'essais.
4. **Faire nommer le défaut avant de le refuser.** Le seul mécanisme
   anti-convergence qui ait fonctionné.
5. **Les interdictions redirigent, elles ne libèrent pas.** Utiles pour sortir
   d'une ornière, inutiles pour créer de la diversité.

## Le test, à passer sur chaque brief

Surligner **chaque nom qui désigne un objet d'interface** : rose, carte,
liste, tableau, badge, onglet, graphique, curseur, menu, fiche, bandeau.

Chacun est une décision de design prise sans s'en apercevoir. Pour chacune :
**est-ce que je voulais la prendre ?** Parfois oui, il existe de vraies
contraintes. Le plus souvent non.

Ce qui doit rester ressemble à ça :

> Il est en cuissard dans son couloir, il a trois secondes et un pouce, il
> veut savoir de quel côté partir.

Ça ne dit pas quoi dessiner. Ça se juge quand même.

## Ce que cette expérience n'établit pas

À savoir avant de la réutiliser ailleurs.

- **Les deux tours diffèrent par deux choses à la fois** : ce que le brief
  contraignait, *et* le fait que la graine esthétique soit partagée ou non. La
  divergence ne peut pas être attribuée proprement à l'une des deux. Il
  faudrait un tour où le brief reste identique et où seule la graine varie.
- **Une exécution par cellule.** Trois modèles, un essai chacun. La
  convergence observée peut contenir du hasard.
- **Le biais le plus gros a été repéré par le mainteneur lui-même** : le
  premier brief demandait une rose des vents. Une partie de ce qu'on a appelé
  convergence était littéralement commandée. C'est d'ailleurs ce constat qui a
  donné la règle en tête de ce document.

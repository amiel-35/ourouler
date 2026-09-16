# Cycle discovery et UX — contrat

Ouvert le 16/09/2026, à la demande du mainteneur : « lance un cycle de
discovery et d'UX pour faire une interface digne de ce nom ».

Ce document dit **ce qu'on conçoit, ce qu'on ne conçoit pas, et ce qui a
déjà été tranché**. Les parcours et les écrans sont dans
`discovery_parcours.md`, ce que le cœur sait déjà rendre dans
`discovery_donnees.md`, l'état de l'art dans `discovery_benchmark.md`.

## Ce qui est conçu ici

Une **interface web multi-utilisateur** : demande d'accès modérée,
assistant de configuration, demande d'itinéraire, consultation de la sortie
du jour. C'est le front du sprint 7 de `plan_sprints_agents.md`, dont le
premier étage — la page du jour servie en ligne — est déjà livré et
déployé.

**Ce n'est pas l'implémentation.** Ce cycle produit des maquettes et des
décisions. L'API, la base, les comptes et le front réel sont un sprint à
part, qui commencera par ces maquettes plutôt que par une page blanche.

## Les quatre arbitrages du mainteneur (16/09/2026)

### 1. L'entrée : lien magique d'abord, fournisseurs tiers ensuite

**V1** — demande d'accès → **le mainteneur valide à la main** → e-mail
d'invitation (Brevo) portant un lien de connexion → l'utilisateur peut
ensuite poser une **passkey**. Aucun mot de passe, nulle part.

**V2** — Google, puis Apple, en plus et non à la place.

**Ceci contredit la doctrine §10.2** telle qu'elle était écrite
(« authentification déléguée, Google d'abord, Apple ensuite »). La
contradiction a été posée au mainteneur, il a tranché, la doctrine est
mise à jour dans la même livraison — c'est la règle de CLAUDE.md.

Ce que la décision garde de la doctrine : **jamais de mot de passe chez
nous**. Un lien à usage unique et une passkey respectent cette règle mieux
qu'un mot de passe ; ce qui change est le fournisseur d'identité, pas le
principe.

Ce que la décision apporte en plus : **la modération est native**. Le
sprint 8 veut qu'Amiel puisse inviter des copains ; avec Google, il aurait
fallu construire une liste d'attente par-dessus une connexion ouverte.

### 2. L'horizon du vent reste à trois jours

Le brief disait « sans vent si à plus de 2 jours ». La mesure du
16/09/2026 sur 2 064 heures dit que la direction tombe dans le bon secteur
93 %, 92 % et 88 % du temps à un, deux et trois jours. `HORIZON_ORIENTATION_J
= 3` reste.

**C'est la mesure qui l'emporte sur l'intuition**, y compris celle du
mainteneur, et c'est lui qui l'a voulu ainsi. Règle absolue 5.

### 3. La clé Intervals : montrer où elle se trouve

L'écran de connexion à intervals.icu doit **guider vers la page où la clé
se génère** (Settings → Developer Settings), pas se contenter d'un champ
vide. La recherche a confirmé que ce geste n'a pas de motif rodé à copier :
dans l'écosystème cycliste, la norme est OAuth avec écran de consentement,
et intervals.icu est l'exception qui expose une clé personnelle.

### 4. Ce qu'on prend à Strava, ce qu'on prend à Apple

Correction explicite du mainteneur, à respecter dans toute la suite :

> « tu parles d'UI, je te parle d'UX sur l'organisation de l'information.
> Strava pour le générateur d'itinéraire est trop bon. Apple est bien pour
> le côté sobre. »

Donc : **l'architecture de l'information du générateur d'itinéraire suit
Strava** — les réglages et le résultat coexistent, on ajuste et on voit
l'effet sans changer d'écran. **La retenue vient d'Apple** — peu de
couleur, la hiérarchie portée par la typographie, rien qui clignote.

Ce n'est pas une charte graphique. C'est une règle de **placement de
l'information**, et elle se juge sur « est-ce que je trouve ce que je
cherche », pas sur « est-ce que c'est joli ».

## Ce qui reste à trancher

Les questions ouvertes sont numérotées dans `discovery_parcours.md`. Les
plus structurantes, dans l'ordre où elles bloquent :

1. **Ce qu'on montre pendant qu'on calcule.** Une génération coûte environ
   150 appels Open-Meteo et plusieurs appels BRouter. C'est le seul endroit
   où l'architecture de l'interface dépend d'une contrainte physique.
2. **Ce qu'on montre à un invité sans historique.** Il n'a aucune
   calibration : les chiffres qu'on affiche à Amiel sont des mesures, ceux
   qu'on afficherait à l'invité seraient des suppositions. Les afficher
   pareil serait un mensonge par mise en page.
3. **Le téléversement de séance** (`.FIT`, `.MRC`, `.ZWO`). Aucun de ces
   formats n'est lu aujourd'hui comme une **prescription** de séance. Ce
   n'est pas un branchement, c'est un lot entier.
4. **Ce qu'on dit de la géographie.** La mesure radiale sur quatre villes a
   montré que le service ne rend pas le même résultat partout. Le dit-on à
   l'utilisateur, et à quel moment ?

## Comment les maquettes seront jugées

- **Aucun écran ne montre une donnée qui n'existe pas.** Chaque chiffre
  affiché est rattaché à un champ de `discovery_donnees.md`, ou marqué
  comme à écrire.
- **Chaque écran a ses états dégradés dessinés**, pas seulement son état
  heureux : pas de séance, météo indisponible, aucune boucle trouvée, une
  seule proposition au lieu de trois.
- **Un cycliste qui n'a pas écrit le code comprend chaque écran** sans
  explication orale.
- **Aucune donnée personnelle** dans les maquettes ni dans le dépôt
  (règle absolue 1) : les exemples sont inventés.

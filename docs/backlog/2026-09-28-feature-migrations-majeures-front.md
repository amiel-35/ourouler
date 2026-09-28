# Préparer les migrations majeures du front (React, TypeScript, jsdom, Vitest)

Type : feature
Statut : à valider

## Pourquoi

Le front (`front/package.json`) est aujourd'hui sur React 18.3.1, TypeScript
5.6.3, jsdom 25.0.1 et Vitest 2.1.5 — des versions qui datent déjà de
plusieurs mois à l'échelle du rythme de ces projets. Rester sur une version
majeure vieillissante n'est pas gênant en soi tant que le projet est petit,
mais chaque mois qui passe sans monter augmente l'écart à franchir d'un
coup, et repousse la découverte des changements cassants au jour où une
dépendance de sécurité forcera la main. [déduit] Ce lot ne fait pas les
migrations (aucune installation ni réseau nécessaire pour l'écrire) : il les
prépare, une par une, avec ce qu'il faut vérifier pour chacune.

## Ce que je veux voir

- Un inventaire, un par dépendance majeure, des points de rupture connus à
  vérifier avant de monter — pas une liste de versions à coller dans
  `package.json` sans lecture :
  - **React** (18.3.1 → la version majeure suivante) : `front/src/` n'utilise
    déjà que des API stables (pas d'`act()` maison à vérifier, pas de mode
    concurrent activé à la main d'après une lecture rapide) — la vérification
    porte surtout sur `@testing-library/react` et `@types/react`, dont la
    version doit suivre.
  - **TypeScript** (5.6.3 → la version majeure suivante) : `front/tsconfig`
    et le script `build` (`tsc --noEmit && vite build`) sont la seule porte
    de vérification de type du front — une version majeure de TypeScript qui
    durcirait une règle existante ferait échouer ce `tsc --noEmit` avant
    tout, donc avant même que la CI ne tourne les tests.
  - **jsdom** (25.0.1 → la version majeure suivante) : dépendance de test
    seulement (`devDependencies`), utilisée par Vitest pour simuler le DOM —
    vérifier que les tests qui touchent au DOM (`@testing-library/dom`,
    `@testing-library/react`) ne s'appuient pas sur un comportement corrigé
    entre-temps.
  - **Vitest** (2.1.5 → la version majeure suivante) : vérifier la
    configuration (`vite.config`, si elle existe, ou les options par défaut)
    et la compatibilité avec `@vitejs/plugin-react` et `vite` (5.4.11)
    eux-mêmes à surveiller pour la même raison.
- Un ordre de montée proposé (la dépendance la moins risquée d'abord,
  typiquement jsdom et Vitest ensemble, puis TypeScript, puis React en
  dernier si les trois autres passent), avec un commit séparé par montée
  pour qu'un échec de CI pointe une seule cause.
- **Aucune version cible n'est affirmée dans cette fiche** : au moment de
  l'écrire, la version majeure suivante de chaque dépendance n'a pas été
  vérifiée sur le registre (pas de réseau pour ce lot) — chaque montée
  commence par relire le CHANGELOG amont réel de la version disponible ce
  jour-là, pas par un numéro deviné ici.

## C'est fini quand

Pour chaque dépendance listée ci-dessus, une fiche ou un lot séparé existe
avec son propre critère (`npm run verifier` vert : typage, lint, tests), et
l'ordre de montée est validé par le mainteneur. La bascule effective de
chaque dépendance sort du périmètre de cette fiche-ci, qui prépare le
terrain plutôt que d'exécuter la montée.

## Hors sujet

- Exécuter une seule des quatre montées : chacune est son propre lot, avec
  son propre critère d'acceptation et sa propre PR (AGENTS.md : une ligne
  CHANGELOG par sujet livré).
- ESLint, `typescript-eslint`, Vite eux-mêmes : versions déjà récentes
  d'après `package.json` (9.39.5, 8.70.1, 5.4.11) — à revisiter si une des
  quatre montées ci-dessus les entraîne.
- Node 20 → une version majeure suivante : `front/package.json` fixe
  `engines.node >= 20` ; hors périmètre de cette fiche, qui porte sur les
  dépendances front, pas le runtime.

## Acquis techniques

- `npm run verifier` (`tsc --noEmit && eslint . && vitest run`) est déjà le
  seul geste à rejouer après chaque montée : pas de nouvelle tâche à
  écrire, seulement à faire passer.
- Le dépôt n'a qu'un seul `package.json` sous `front/` : pas de espace de
  travail (monorepo, workspaces) à coordonner pour ces montées.

## Questions ouvertes

- L'ordre proposé (jsdom+Vitest, puis TypeScript, puis React) est une
  proposition de cette fiche, pas une décision : à confirmer ou à réordonner
  avec le mainteneur, qui peut avoir une préférence (ex. React en premier
  s'il y a une fonctionnalité qui en dépend).
- Faut-il un test de compatibilité npm (`npm ci` reproductible) avant
  chaque montée, comme garde-fou de départ ?

## Déjà en place / Doctrine révisée

- Constaté (`front/package.json`) : `react` 18.3.1, `react-dom` 18.3.1,
  `typescript` 5.6.3, `jsdom` 25.0.1, `vitest` 2.1.5, `vite` 5.4.11,
  `@vitejs/plugin-react` 4.3.3, `@testing-library/react` 16.3.3.
- Constaté : `npm run verifier` = `tsc --noEmit && eslint . && vitest run`
  (script unique dans `package.json`) — c'est le critère de non-régression
  que chaque montée doit continuer à satisfaire (AGENTS.md : « cd front &&
  npm run verifier »).
- Constaté : aucune installation ni build n'a été lancé pour écrire cette
  fiche (consigne explicite du mainteneur, pas de réseau nécessaire) — les
  numéros de version cible ne sont donc pas vérifiés contre le registre npm
  réel et ne doivent pas être pris pour acquis avant de commencer chaque
  montée.

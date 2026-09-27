/** Séparé d'`App.tsx` — les types et utilitaires de navigation (page,
 * onglet, vue), et le résultat d'une recherche : ce qui n'a pas besoin de
 * vivre à côté du rendu.
 */

import type { Boucle, Enveloppe, Seance, Sortie } from "../api/types";

/**
 * Sur quelle page ce chargement de l'application s'est ouvert — lu **une
 * fois**, au démarrage, jamais réévalué.
 *
 * Pas de routeur : le reste de l'application navigue par état React
 * (`Onglet`, `Vue` ci-dessous), comme avant ce lot. Seuls ces deux chemins
 * sont distingués, parce qu'ils doivent fonctionner **avant** qu'aucune
 * session n'existe — l'un des deux, justement, sert à en ouvrir une.
 */
export type Pagina =
  | { genre: "application" }
  | { genre: "entrer"; jeton: string }
  | { genre: "reinitialiser"; jeton: string }
  | { genre: "connexion" };

export function paginaDepuisUrl(): Pagina {
  const chemin = window.location.pathname;
  if (chemin === "/entrer" || chemin === "/reinitialiser") {
    const jeton = new URLSearchParams(window.location.search).get("jeton") ?? "";
    // Le jeton n'a rien à faire dans l'historique du navigateur ni dans un
    // en-tête `Referer` une fois lu : une ligne, faite ici et nulle part
    // ailleurs, pour que ni le rechargement de l'écran ni un lien partagé
    // depuis cette page ne le fassent fuiter une seconde fois.
    window.history.replaceState(null, "", chemin);
    return chemin === "/entrer" ? { genre: "entrer", jeton } : { genre: "reinitialiser", jeton };
  }
  if (chemin === "/connexion") return { genre: "connexion" };
  return { genre: "application" };
}

export type Onglet = "aujourdhui" | "semaine" | "demander" | "reglages";
export type Vue =
  | { genre: "onglet" }
  | { genre: "assistant" }
  /**
   * **Le dépôt porte son jour.**
   *
   * `demande.jour` dérive : `chercher` le réécrit à chaque génération. Après
   * avoir généré le parcours de samedi depuis « Ma semaine », « Déposer une
   * séance » depuis l'écran **d'aujourd'hui** déposerait le fichier pour
   * samedi. Le rattachement au jour étant la garde de `SeanceDeposee`, un
   * rattachement au mauvais jour serait le même défaut déplacé.
   */
  | { genre: "importer"; jour: string }
  /** Un parcours déjà en main, à analyser — le troisième usage de
   * « Déposer », sans jour rattaché (ce n'est pas une prescription). */
  | { genre: "analyser"; jour: string }
  | { genre: "propositions" }
  | { genre: "detail"; numero: number }
  | { genre: "boucles" };

export interface Resultat {
  sortie: Enveloppe<Sortie> | null;
  boucle: Enveloppe<Boucle> | null;
  seance: Seance | null;
  jour: string;
}

/**
 * Un fichier de séance déposé — **et le jour pour lequel il l'a été**.
 *
 * Le fichier déposé est une séance à faire (décision Q38,
 * `docs/journal/questions/questions_mainteneur.md`) : une prescription, et une prescription vaut pour
 * un jour. `POST /seances/fichier` prend d'ailleurs ce jour.
 *
 * Retenir le seul identifiant, sans rien pour le remettre à `null` (ni le
 * changement de jour, ni le changement d'onglet, ni une séance Intervals
 * retrouvée, ni la fin de la génération), replacerait silencieusement un
 * `.ZWO` déposé mardi sur toutes les recherches suivantes — le cycliste
 * partirait faire les blocs de mardi le mercredi, et l'interface aurait l'air
 * d'accord avec lui.
 *
 * L'invariant tenu, et testé : **une séance déposée ne part qu'avec
 * une recherche pour son propre jour**, et elle est visible tant qu'elle est
 * en usage.
 */
export interface SeanceDeposee {
  identifiant: string;
  jour: string;
  nom: string;
}

/**
 * L'identifiant à joindre à une recherche — **ou rien**.
 *
 * La règle de B1, nommée plutôt que laissée en ligne dans l'appel : une
 * prescription déposée pour mardi ne part pas avec la recherche de mercredi.
 * C'est la seule chose qui sépare « le cycliste fait la séance du jour » de
 * « le cycliste part faire les blocs d'hier sans le savoir ».
 */
export function fichierPourLaRecherche(
  deposee: SeanceDeposee | null,
  jourDemande: string,
): string | undefined {
  if (deposee === null) return undefined;
  return deposee.jour === jourDemande ? deposee.identifiant : undefined;
}

export const ONGLETS: { cle: Onglet; nom: string }[] = [
  { cle: "aujourdhui", nom: "Aujourd'hui" },
  { cle: "semaine", nom: "Ma semaine" },
  { cle: "demander", nom: "Demander" },
  { cle: "reglages", nom: "Réglages" },
];

/** Un onglet connu de l'application — jamais déduit d'une simple présence
 * de champ. Sert à valider ce qui vient de l'extérieur (l'adresse, une
 * entrée d'historique) avant de le poser dans l'état React : `setOnglet`
 * n'a jamais le droit de recevoir autre chose qu'un `Onglet` des quatre. */
export function estOnglet(valeur: unknown): valeur is Onglet {
  return typeof valeur === "string" && ONGLETS.some((o) => o.cle === valeur);
}

/** L'onglet demandé par l'URL (`?onglet=reglages`), lu **une fois**, au
 * démarrage — même patron que `paginaDepuisUrl`. Le lien « Le relier dans les
 * réglages » pose ce paramètre : sans cette lecture, une ouverture directe de
 * ce lien retomberait sur Aujourd'hui.
 * Une clé absente ou inconnue garde le défaut plutôt que d'échouer. */
export function ongletDepuisUrl(): Onglet {
  const valeur = new URLSearchParams(window.location.search).get("onglet");
  return estOnglet(valeur) ? valeur : "aujourdhui";
}

/**
 * Ce que porte chaque entrée d'historique du navigateur — décision du
 * mainteneur du 27/09/2026 (`docs/backlog/2026-09-27-bug-retour-navigateur-quitte-l-appli.md`) :
 * **l'onglet est dans l'adresse** (`/?onglet=...`), les **résultats**
 * (propositions, détail, boucles) sont des étapes d'historique **sans
 * adresse propre** — un rechargement y ramène par l'onglet, jamais par eux.
 */
export interface EtatHistorique {
  onglet: Onglet;
  vue: Vue;
}

/**
 * Change d'onglet : une adresse différente, une entrée d'historique de
 * plus. **Ne pousse rien si l'onglet visé est déjà l'onglet actif** — sinon
 * un rechargement, un clic répété ou l'arrivée sur l'onglet par défaut
 * empileraient des entrées qui ne changent rien, et un seul retour ne
 * suffirait plus à sortir de l'onglet.
 */
export function pousserOnglet(actif: Onglet, cible: Onglet): void {
  if (cible === actif) return;
  const etat: EtatHistorique = { onglet: cible, vue: { genre: "onglet" } };
  window.history.pushState(etat, "", `/?onglet=${cible}`);
}

/**
 * Entre dans un écran de résultats — formulaire → propositions/boucles,
 * liste → détail d'une proposition : une entrée d'historique de plus, mais
 * la **même adresse** (les résultats n'ont pas d'adresse propre). Un retour
 * navigateur la dépile et retombe sur l'écran précédent (le formulaire,
 * rempli comme avant, ou la liste) sans le moindre appel réseau — les
 * résultats déjà obtenus restent dans `Resultat`/`etat/memoire.ts`, `popstate`
 * ne fait que les rafficher.
 */
export function pousserVue(onglet: Onglet, vue: Vue): void {
  const etat: EtatHistorique = { onglet, vue };
  window.history.pushState(etat, "", window.location.pathname + window.location.search);
}

/**
 * Remplace l'entrée courante par une nouvelle vue de résultats — même
 * adresse, comme `pousserVue`, mais **sans** entrée de plus. Sert quand
 * l'entrée courante est déjà des résultats du même genre : « Chercher plus
 * loin » (`surElargir`, `Propositions.tsx`) relance `chercher` alors que
 * l'écran affiche déjà des propositions — repousser en empilerait une
 * seconde, et un seul retour ne suffirait plus à quitter les résultats vers
 * le formulaire (relecture du 27/09/2026).
 */
export function remplacerVue(onglet: Onglet, vue: Vue): void {
  const etat: EtatHistorique = { onglet, vue };
  window.history.replaceState(etat, "", window.location.pathname + window.location.search);
}

/**
 * Entre dans une vue de résultats — pousse une entrée de plus, sauf si
 * l'entrée courante en est déjà une du même genre (voir `remplacerVue`).
 * `vueActuelle` est la vue affichée **avant** cet appel : c'est elle qui dit
 * si on entre pour la première fois ou si on ne fait que raffiner ce qui
 * est déjà là.
 */
export function entrerDansResultats(onglet: Onglet, vueActuelle: Vue, vueCible: Vue): void {
  if (vueActuelle.genre === vueCible.genre) {
    remplacerVue(onglet, vueCible);
  } else {
    pousserVue(onglet, vueCible);
  }
}

/**
 * Pose l'état courant sur l'entrée d'historique **sans en ajouter** —
 * `replaceState`, comme `paginaDepuisUrl` le fait déjà pour `/entrer` et
 * `/reinitialiser`. Sert deux fois : normaliser l'adresse au démarrage (pour
 * que `history.state` porte déjà la forme que `popstate` attend), et
 * resynchroniser l'entrée courante quand on quitte des résultats vers
 * l'onglet qui les a produits sans pousser de nouvelle entrée (l'onglet
 * était déjà l'onglet actif — voir `pousserOnglet`).
 */
export function remplacerVersOnglet(onglet: Onglet): void {
  const etat: EtatHistorique = { onglet, vue: { genre: "onglet" } };
  window.history.replaceState(etat, "", `/?onglet=${onglet}`);
}

/**
 * Le seul geste qui change d'onglet, où qu'il parte dans l'application
 * (barre d'onglets, écran d'échec, lien « Demander » d'un secours) — pose
 * l'historique avant l'état React, jamais l'inverse : sans quoi l'entrée
 * courante resterait sur une vue de résultats après un changement d'onglet
 * qui ne passe pas par `pousserOnglet` (l'onglet visé déjà actif), et un
 * retour navigateur retrouverait cette vue au lieu de l'onglet affiché.
 */
export function changerOnglet(
  actif: Onglet,
  cible: Onglet,
  setOnglet: (onglet: Onglet) => void,
  setVue: (vue: Vue) => void,
): void {
  if (cible === actif) {
    remplacerVersOnglet(cible);
  } else {
    pousserOnglet(actif, cible);
  }
  setOnglet(cible);
  setVue({ genre: "onglet" });
}

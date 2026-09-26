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

/** L'onglet demandé par l'URL (`?onglet=reglages`), lu **une fois**, au
 * démarrage — même patron que `paginaDepuisUrl`. Le lien « Le relier dans les
 * réglages » pose ce paramètre : sans cette lecture, une ouverture directe de
 * ce lien retomberait sur Aujourd'hui.
 * Une clé absente ou inconnue garde le défaut plutôt que d'échouer. */
export function ongletDepuisUrl(): Onglet {
  const valeur = new URLSearchParams(window.location.search).get("onglet");
  const trouve = ONGLETS.find((o) => o.cle === valeur);
  return trouve ? trouve.cle : "aujourdhui";
}

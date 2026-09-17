/** Ce que le navigateur retient d'une visite à l'autre.
 *
 * Deux choses, et **aucune valeur calculée par le front** : la dernière
 * réponse de l'API pour la sortie d'un jour donné, et la date du dernier
 * jour où les séances ont réellement été lues.
 *
 * La première sert à l'écran « Aujourd'hui » : la maquette y montre un
 * parcours « généré à 6 h », mais aucun calcul de nuit n'existe côté
 * serveur. Plutôt qu'inventer une heure, on garde **la réponse réellement
 * obtenue** et on affiche **l'heure à laquelle elle a été obtenue**.
 *
 * La seconde sert à l'écran d'échec d'Intervals : « plus lues depuis le 12
 * septembre » dit à quelqu'un ce qu'il a manqué, « erreur de connexion » ne
 * dit rien. Cette date n'est pas inventée non plus — c'est la dernière fois
 * que ce navigateur a reçu une semaine.
 *
 * Tout accès est sous `try` : une fenêtre privée ou un stockage refusé rend
 * `null`, et l'interface marche sans.
 */

import type { Enveloppe, Sortie } from "../api/types";

const CLE_SORTIE = "ourouler.sortie";
const CLE_SEANCES = "ourouler.seances-lues-le";

export interface SortieMemorisee {
  jour: string;
  /** L'horodatage de la réponse, pas une heure décidée par l'interface. */
  obtenue_le: string;
  reponse: Enveloppe<Sortie>;
}

export function retenirSortie(jour: string, reponse: Enveloppe<Sortie>): SortieMemorisee {
  const memoire: SortieMemorisee = {
    jour,
    obtenue_le: new Date().toISOString(),
    reponse,
  };
  try {
    window.localStorage.setItem(`${CLE_SORTIE}.${jour}`, JSON.stringify(memoire));
  } catch {
    /* stockage refusé : l'écran marche quand même, il ne se souvient pas */
  }
  return memoire;
}

export function sortieRetenue(jour: string): SortieMemorisee | null {
  try {
    const brut = window.localStorage.getItem(`${CLE_SORTIE}.${jour}`);
    if (!brut) return null;
    const memoire = JSON.parse(brut) as SortieMemorisee;
    return memoire.jour === jour ? memoire : null;
  } catch {
    return null;
  }
}

export function oublierSortie(jour: string): void {
  try {
    window.localStorage.removeItem(`${CLE_SORTIE}.${jour}`);
  } catch {
    /* rien à faire */
  }
}

export function retenirLectureSeances(jour: string): void {
  try {
    window.localStorage.setItem(CLE_SEANCES, jour);
  } catch {
    /* rien à faire */
  }
}

export function derniereLectureSeances(): string | null {
  try {
    return window.localStorage.getItem(CLE_SEANCES);
  } catch {
    return null;
  }
}

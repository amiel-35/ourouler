/** Les quatre champs d'adresse, le point à confirmer et la géolocalisation :
 * des fonctions pures, sans état. */

import type { Candidat } from "../../api/types";

/** Ce que ce formulaire rend une fois le point confirmé. */
export interface DepartChoisi {
  nom: string;
  latitude: number;
  longitude: number;
}

export interface Champs {
  numero: string;
  voie: string;
  codePostal: string;
  commune: string;
}

export const VIDES: Champs = { numero: "", voie: "", codePostal: "", commune: "" };

export const LIBELLES: Record<keyof Champs, string> = {
  numero: "Numéro",
  voie: "Voie",
  codePostal: "Code postal",
  commune: "Commune",
};

/** Les champs obligatoires — le numéro n'en fait pas partie (constaté le
 * 25/09/2026 : une place ou un lieu-dit, « Place de la Mairie », n'a pas de
 * numéro, et le formulaire refusait de chercher tant qu'il était vide). La
 * commune et le code postal restent obligatoires : c'est eux qui gardent le
 * garde-fou du géocodage (Q34) — sans commune, la même rue existe dans des
 * dizaines de communes, ce qu'un numéro seul ne corrige pas. */
export const OBLIGATOIRES: (keyof Champs)[] = ["voie", "codePostal", "commune"];

/** Le point à confirmer : soit un candidat du géocodeur, soit la position du navigateur. */
export type Apercu =
  | { genre: "candidat"; candidat: Candidat }
  | { genre: "position"; latitude: number; longitude: number; precision_m: number | null };

/** La géolocalisation est-elle seulement possible ici, et sinon pourquoi ?
 *
 * Trois pièges, et ils se traitent, ils ne se contournent pas : le navigateur
 * ne donne la position que sur HTTPS (ou en local), il faut une autorisation
 * explicite, et l'appel peut échouer. Le premier se voit avant de cliquer —
 * autant le dire plutôt que d'offrir un bouton qui ne marchera jamais.
 */
export function etatGeolocalisation(): { possible: boolean; raison: string | null } {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return { possible: false, raison: "Ce navigateur ne donne pas la position." };
  }
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return {
      possible: false,
      raison: "La position demande une connexion sécurisée (HTTPS) — le formulaire, non.",
    };
  }
  return { possible: true, raison: null };
}

/** Ce qu'on dit à l'utilisateur quand la position n'est pas venue.
 *
 * Le refus d'autorisation est séparé du reste **exprès** : c'est un choix, pas
 * une panne, et le formulaire fait la même chose.
 */
export function phraseEchecPosition(code: number): string {
  if (code === 1) {
    return "Position non partagée — c'est votre choix. Les champs ci-dessous font la même chose.";
  }
  if (code === 3) {
    return "La position met trop de temps à venir. Les champs ci-dessous restent disponibles.";
  }
  return "La position n'a pas pu être relevée. Les champs ci-dessous restent disponibles.";
}

/** L'adresse envoyée au géocodeur, à partir des quatre champs. */
export function requete(champs: Champs): string {
  return [champs.numero, champs.voie, champs.codePostal, champs.commune]
    .map((v) => v.trim())
    .filter((v) => v !== "")
    .join(" ");
}

/** Les champs obligatoires restés vides — le numéro est facultatif (voir `OBLIGATOIRES`). */
export function champsManquants(champs: Champs): (keyof Champs)[] {
  return OBLIGATOIRES.filter((clef) => champs[clef].trim() === "");
}

export function nomDuPoint(apercu: Apercu): string {
  if (apercu.genre === "candidat") return apercu.candidat.label;
  // Pas de géocodage inverse dans l'API : on ne connaît que des chiffres, on
  // n'invente pas un nom de rue par-dessus.
  return `Ma position (${apercu.latitude.toFixed(5)}, ${apercu.longitude.toFixed(5)})`;
}

export function coordonneesDu(apercu: Apercu): { latitude: number; longitude: number } {
  if (apercu.genre === "candidat") {
    return { latitude: apercu.candidat.latitude, longitude: apercu.candidat.longitude };
  }
  return { latitude: apercu.latitude, longitude: apercu.longitude };
}

/** Où est ce candidat, en une ligne — la commune d'abord, c'est elle qui distingue. */
export function ouEst(candidat: Candidat): string {
  if (!candidat.commune) return "commune inconnue";
  return candidat.code_postal ? `${candidat.commune} (${candidat.code_postal})` : candidat.commune;
}

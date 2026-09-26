/** Les étapes de l'assistant, leurs libellés et les choix fermés qu'il propose. */

import type { FocusEvent, MouseEvent } from "react";
export type Etape =
  | "bienvenue"
  | "identite"
  | "depart"
  | "t1_question"
  | "t1_cle"
  | "t1_confirmation"
  | "t2"
  | "poids"
  | "velo"
  | "t3"
  | "t4_vitesse"
  | "t4_terrain"
  | "recap";

/** L'étage de l'entonnoir qui a fini par établir une FTP — pour la seule
 * phrase de confiance du récapitulatif (§9 du document). */
export type Etage = "intervals" | "ftp_declare" | "vitesse_terrain" | "vitesse_terrain_montagne" | "litterature" | null;

export const PHRASE_CONFIANCE: Record<Exclude<Etage, null>, string> = {
  intervals: "Estimation confirmée depuis votre profil Intervals.",
  ftp_declare: "Estimation à partir de la FTP que vous avez donnée.",
  vitesse_terrain: "Estimation à partir de ce que vous nous avez dit de vos sorties.",
  vitesse_terrain_montagne:
    "Estimation à partir de ce que vous nous avez dit — en montagne, cette estimation est moins fiable qu'ailleurs.",
  litterature: "Estimation générique, à partir de votre poids et de votre vélo seuls.",
};

export const LIBELLES: Record<Etape, { rubrique: string; titre: string }> = {
  bienvenue: { rubrique: "Bienvenue", titre: "Bienvenue" },
  identite: { rubrique: "Votre identité", titre: "Comment vous appelez-vous ?" },
  depart: { rubrique: "Votre départ", titre: "D'où partez-vous ?" },
  t1_question: { rubrique: "intervals.icu", titre: "Avez-vous un compte intervals.icu ?" },
  t1_cle: { rubrique: "intervals.icu", titre: "Brancher intervals.icu" },
  t1_confirmation: { rubrique: "intervals.icu", titre: "On a retrouvé votre profil" },
  t2: { rubrique: "Export Strava ou Garmin", titre: "Pouvez-vous nous transmettre un export ?" },
  poids: { rubrique: "Votre poids", titre: "Votre poids" },
  velo: { rubrique: "Votre vélo", titre: "Avec quoi roulez-vous ?" },
  t3: { rubrique: "Votre puissance", titre: "Connaissez-vous votre FTP ?" },
  t4_vitesse: { rubrique: "Votre vécu", titre: "Votre vitesse au compteur" },
  t4_terrain: { rubrique: "Votre vécu", titre: "Et le terrain ?" },
  recap: { rubrique: "C'est prêt", titre: "Tout est en place" },
};

/** §5.2 — les tranches de vitesse font 2 km/h, mesuré. La valeur envoyée est
 * le milieu de la tranche ; les deux bornes ouvertes ont une valeur
 * représentative. `null` = « je ne sais pas trop », pas de valeur. */
export const CHOIX_VITESSE: Array<{ libelle: string; vitesse_kmh: number | null }> = [
  { libelle: "Moins de 20 km/h", vitesse_kmh: 19 },
  { libelle: "20 à 22 km/h", vitesse_kmh: 21 },
  { libelle: "22 à 24 km/h", vitesse_kmh: 23 },
  { libelle: "24 à 26 km/h", vitesse_kmh: 25 },
  { libelle: "26 à 28 km/h", vitesse_kmh: 27 },
  { libelle: "28 à 30 km/h", vitesse_kmh: 29 },
  { libelle: "Plus de 30 km/h", vitesse_kmh: 31 },
  { libelle: "Je ne sais pas trop", vitesse_kmh: null },
];

/** §6 — le terrain choisit le dénivelé de référence de la conversion. La
 * case « Montagne » (30 m/km) dégrade la phrase de confiance du récap. */
export const CHOIX_TERRAIN: Array<{ libelle: string; denivele_m_par_km: number | null }> = [
  { libelle: "Plat — moins de 250 m sur 50 km", denivele_m_par_km: 3 },
  { libelle: "Vallonné — 250 à 600 m sur 50 km", denivele_m_par_km: 10 },
  { libelle: "Ça grimpe — 600 à 1000 m sur 50 km", denivele_m_par_km: 18 },
  { libelle: "Montagne — plus de 1000 m sur 50 km", denivele_m_par_km: 30 },
  { libelle: "Je ne sais pas trop", denivele_m_par_km: null },
];

/** Sélectionne tout le contenu d'un champ dès qu'il reçoit le focus.
 *
 * Les champs préremplis avec une valeur qui n'est
 * pas forcément celle de la personne (poids « 70 », nom de vélo « Route » —
 * des défauts posés côté serveur quand rien n'a encore été déclaré, `depots.
 * SOCLE_MINIMAL`, `config.depuis_dict`) laisseraient taper à la suite du
 * texte existant : « 70 » puis « 75 » tapé donnerait « 7075 ». Le front ne peut pas
 * distinguer ce défaut fabriqué d'une vraie valeur déjà confirmée — les deux
 * ont le même type côté API — donc la sélection au focus, plutôt qu'un
 * placeholder, est la réponse qui marche pour ces champs-là : reprendre la
 * frappe remplace tout, sans qu'il faille d'abord tout effacer à la main.
 */
export function surFocusSelectionner(e: FocusEvent<HTMLInputElement>) {
  e.target.select();
}

/** Le clic qui donne le focus replace ensuite le curseur au point cliqué au
 * relâchement — un vrai navigateur fait ça aussi — ce qui annule la
 * sélection que `surFocusSelectionner` vient de poser. `preventDefault` sur
 * `mouseup` coupe cet ajustement sans empêcher le focus ni le clic lui-même. */
export function surRelacherNePasDeselectionner(e: MouseEvent<HTMLInputElement>) {
  if (document.activeElement === e.currentTarget) e.preventDefault();
}

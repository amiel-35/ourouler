/** Mettre en français ce que l'API rend, et **rien d'autre**.
 *
 * Aucune fonction de ce module n'invente de valeur : chacune reçoit un nombre
 * de l'API et rend sa forme lisible. La seule qui calcule est
 * `compteArrets`, et elle se refuse quand le compte ne retombe pas juste.
 */

const NBSP = " ";

/** `1234.5` → `1 234,5`. `null` n'a pas de forme : l'appelant s'en occupe. */
export function nombre(valeur: number, decimales = 0): string {
  return valeur.toLocaleString("fr-FR", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

export function km(metres: number): string {
  return `${nombre(metres / 1000, 1)}${NBSP}km`;
}

export function kmDepuisKm(valeur: number): string {
  return `${nombre(valeur, 1)}${NBSP}km`;
}

/** `2232` → `37 min`, `7200` → `2 h`, `6300` → `1 h 45`. */
export function duree(secondes: number): string {
  const total = Math.round(secondes / 60);
  const heures = Math.floor(total / 60);
  const minutes = total % 60;
  if (heures === 0) return `${minutes}${NBSP}min`;
  if (minutes === 0) return `${heures}${NBSP}h`;
  return `${heures}${NBSP}h${NBSP}${String(minutes).padStart(2, "0")}`;
}

/** `0.0162` → `2 %`. Un pourcentage se lit entier, sinon il ne se lit pas. */
export function pourcentage(part: number): string {
  return `${nombre(part * 100, 0)}${NBSP}%`;
}

/** `2026-09-16` → `mercredi 16 septembre`. */
export function jourEnLettres(iso: string): string {
  const quand = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(quand.getTime())) return iso;
  return quand.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
}

/** `2026-09-16` → `Mer. 16`. */
export function jourCourt(iso: string): string {
  const quand = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(quand.getTime())) return iso;
  const texte = quand.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric" });
  return texte.charAt(0).toUpperCase() + texte.slice(1);
}

/** « aujourd'hui », « demain », « dans 4 jours » — relatif à `aujourdhui`. */
export function ecartEnJours(iso: string, aujourdhui: string): string | null {
  const a = Date.parse(`${iso}T12:00:00`);
  const b = Date.parse(`${aujourdhui}T12:00:00`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  const jours = Math.round((a - b) / 86_400_000);
  if (jours === 0) return "aujourd'hui";
  if (jours === 1) return "demain";
  if (jours < 0) return jours === -1 ? "hier" : `il y a ${-jours} jours`;
  return `dans ${jours} jours`;
}

/** `2026-09-16T06:00:00+02:00` → `6 h 00`. */
export function heure(iso: string): string {
  const quand = new Date(iso);
  if (Number.isNaN(quand.getTime())) return iso;
  return `${quand.getHours()}${NBSP}h${NBSP}${String(quand.getMinutes()).padStart(2, "0")}`;
}

/** L'heure de retour : le départ plus la durée. */
export function heureDeRetour(departIso: string, secondes: number): string | null {
  const quand = new Date(departIso);
  if (Number.isNaN(quand.getTime())) return null;
  return heure(new Date(quand.getTime() + secondes * 1000).toISOString());
}

/** L'azimut d'où vient le vent, en points cardinaux. */
const CARDINAUX = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
export function cardinal(degres: number): string {
  return CARDINAUX[Math.round(((degres % 360) + 360) % 360 / 45) % 8];
}

/**
 * Le **nombre** de feux et stops, retrouvé depuis la densité au kilomètre.
 *
 * Le JSON n'expose que `densite_marqueurs_km`, qui est un compte divisé par
 * une distance (`boucle/marqueurs.py`) ; l'affichage, lui, doit montrer un
 * nombre absolu — « sur 100 km, personne ne croise 170 feux » (maquette E14).
 * La multiplication rend donc l'entier d'origine, et **on ne l'affiche que
 * si elle retombe juste** : un arrondi qui dérive est une valeur inventée,
 * et on préfère ne rien dire (règle absolue 5).
 */
export function compteArrets(densiteParKm: number | null, distanceKm: number | null): number | null {
  if (densiteParKm === null || distanceKm === null || distanceKm <= 0) return null;
  const brut = densiteParKm * distanceKm;
  const entier = Math.round(brut);
  return Math.abs(brut - entier) <= 0.05 ? entier : null;
}

/** Les quatre réponses possibles à la question du vent, telles qu'on les demande. */
export const VENT_EN_TOUTES_LETTRES: Record<string, string> = {
  "peu-importe": "Peu importe",
  "retour-dos": "Rentrer avec",
  "depart-dos": "Partir avec",
  travers: "De travers",
};

/** Les mêmes, telles qu'on les **constate** sur un parcours déjà tracé. */
export const VENT_DECRIT: Record<string, string> = {
  "peu-importe": "vent quelconque",
  "retour-dos": "vent de dos au retour",
  "depart-dos": "vent de dos à l'aller",
  travers: "vent de travers",
};

export { NBSP };

/**
 * La rose des huit directions : agréger `Meteo.cellules` (8 directions × N
 * couronnes × N heures, tel que `GET /meteo` le rend) en **une valeur par
 * direction**, pour dessiner un secteur plutôt qu'un tableau.
 *
 * Rien ici n'invente une donnée : chaque champ vient d'une cellule réelle,
 * et l'agrégation reprend **le même geste que le cœur**, pas un calcul
 * inventé pour l'écran :
 *
 * - le cumul de pluie par direction est celui de
 *   `RapportMeteo.meilleure_direction` (`src/ourouler/meteo/rapport.py`) —
 *   une somme de `pluie_mm` sur toutes les cellules de la direction, toutes
 *   distances et toutes heures confondues, le point « ici » exclu ;
 * - le désaccord est `confiance === "desaccord"`, le même champ que le cœur
 *   sérialise déjà (`meteo.rapport.confiance`) — jamais recalculé à partir
 *   de `pluie_mm`/`pluie_second_avis_mm` ici ;
 * - le vent affiché est celui de la cellule la plus proche dans l'espace
 *   (la couronne la plus proche) puis dans le temps (l'heure la plus
 *   proche) — « le vent qu'on sentirait en partant maintenant dans cette
 *   direction-là » — `vent_relatif` compris, tel que l'API le rend.
 */

import type { Cellule } from "./types";

/** Les huit directions, dans l'ordre où le cœur les nomme (`couronne.NOMS_DIRECTIONS`). */
export const HUIT_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"] as const;

/** L'azimut (0 = nord, sens horaire) de chaque direction fixe de la rose. */
export const AZIMUT_DIRECTION: Record<(typeof HUIT_DIRECTIONS)[number], number> = {
  N: 0,
  NE: 45,
  E: 90,
  SE: 135,
  S: 180,
  SO: 225,
  O: 270,
  NO: 315,
};

export type NiveauPluie = "aucune-donnee" | "sec" | "faible" | "modere" | "fort";

/**
 * Quatre paliers d'**affichage** pour un cumul de pluie sur l'horizon de la
 * rose — repris tels quels de la direction visuelle retenue
 * (`docs/journal/ux/directions/suisse-vivante.html`, légende « Pluie (3 h) ») : sec à
 * 0, faible de 0,1 à 1,0 mm, modérée de 1,1 à 3,0, forte au-delà.
 *
 * **Distinct du seuil météorologique du cœur** (`SEUIL_PLUIE_MM_H` = 0,3
 * mm/h dans `meteo/rapport.py`, qui décide « pleut-il cette heure-ci »,
 * pas « combien sur tout l'horizon ») : celui-là classe une heure, celui-ci
 * regroupe un cumul pour choisir une teinte. Les deux nombres ne se
 * comparent pas, et ce fichier ne prétend pas reproduire le premier.
 */
export function niveauPluie(cumulMm: number | null): NiveauPluie {
  if (cumulMm === null) return "aucune-donnee";
  const arrondi = Math.round(cumulMm * 10) / 10;
  if (arrondi <= 0) return "sec";
  if (arrondi <= 1.0) return "faible";
  if (arrondi <= 3.0) return "modere";
  return "fort";
}

export interface DirectionMeteo {
  nom: (typeof HUIT_DIRECTIONS)[number];
  azimutDeg: number;
  /** `null` : aucune cellule pour cette direction (pas un 0 : on n'affirme rien sans mesure). */
  pluieMm: number | null;
  niveau: NiveauPluie;
  /** Vrai si au moins une cellule de cette direction porte `confiance === "desaccord"`. */
  desaccord: boolean;
  ventKmh: number | null;
  ventDepuisDeg: number | null;
  /** « face » | « dos » | « travers » | `null`, tel que l'API le rend. */
  relatif: string | null;
}

/** Compare deux horodatages ISO 8601 : plus tôt d'abord. */
function parOrdreChronologique(a: Cellule, b: Cellule): number {
  if (a.distance_km !== b.distance_km) return a.distance_km - b.distance_km;
  return a.t.localeCompare(b.t);
}

/**
 * Agrège `cellules` (telles que rendues par `GET /meteo`) en une ligne par
 * direction, dans l'ordre fixe de la rose. Une direction absente de
 * `cellules` (météo partiellement indisponible) rend `pluieMm: null` — pas
 * un secteur « sec » qu'elle n'a pas gagné.
 */
export function directionsDepuisCellules(cellules: Cellule[]): DirectionMeteo[] {
  return HUIT_DIRECTIONS.map((nom) => {
    // `nom` parcourt les huit directions fixes de la rose, jamais le point
    // central de la couronne (`meteo.couronne.NOM_ICI` côté cœur, `"ici"`) :
    // il n'y a donc rien à en filtrer explicitement, il ne correspondra
    // simplement à aucun `nom` de cette liste.
    const deCetteDirection = cellules.filter((c) => c.direction === nom);
    if (deCetteDirection.length === 0) {
      return {
        nom,
        azimutDeg: AZIMUT_DIRECTION[nom],
        pluieMm: null,
        niveau: "aucune-donnee",
        desaccord: false,
        ventKmh: null,
        ventDepuisDeg: null,
        relatif: null,
      };
    }
    const pluieMm = deCetteDirection.reduce((somme, c) => somme + c.pluie_mm, 0);
    const desaccord = deCetteDirection.some((c) => c.confiance === "desaccord");
    // « Le vent qu'on sentirait en partant maintenant dans cette
    // direction-là » : la couronne la plus proche, à l'heure la plus proche.
    const reference = [...deCetteDirection].sort(parOrdreChronologique)[0];
    return {
      nom,
      azimutDeg: AZIMUT_DIRECTION[nom],
      pluieMm,
      niveau: niveauPluie(pluieMm),
      desaccord,
      ventKmh: reference.vent_kmh,
      ventDepuisDeg: reference.vent_depuis_deg,
      relatif: reference.vent_relatif,
    };
  });
}

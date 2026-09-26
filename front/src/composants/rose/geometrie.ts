/** La géométrie de la rose des directions et ses phrases : des fonctions pures. */

import { HUIT_DIRECTIONS, type DirectionMeteo, type NiveauPluie } from "../../api/meteoRose";
import {
  nombre,
  ventDepuisAvecPreposition,
  VENT_DEPUIS_EN_TOUTES_LETTRES,
} from "../../api/formats";

// `LARGEUR` porte une marge généreuse au-delà de `R_ETIQUETTE` (32px, deux
// lignes de texte — direction et mm) : posée trop juste (4px), elle rogne le
// haut de « N », rendu visible seulement comme deux tirets. Un SVG racine clippe par défaut tout
// ce qui déborde de son `viewBox` — ce n'est pas un bug d'affichage isolé,
// c'est une marge insuffisante, corrigée ici plutôt que par un `overflow:
// visible` qui aurait juste déplacé le rognage sur le conteneur parent.
export const LARGEUR = 320;
export const CENTRE = LARGEUR / 2;
export const R_EXTERIEUR = 118;
export const R_INTERIEUR = 54;
export const R_ETIQUETTE = 128;
export const R_FLECHE = 86;
export const LARGEUR_SECTEUR_DEG = 44; // < 45 : un mince filet de papier sépare chaque secteur

/** La forme de la flèche de vent, reprise à l'identique de `composants/Carte.tsx`
 * (elle-même reprise de `sortie/carte.py`) : une seule forme dans toute
 * l'application, jamais un second glyphe de vent inventé pour cet écran. */
export const FORME_FLECHE = "M10 1 L17 18 L10 14 L3 18 Z";

/** Le remplissage de chaque palier de pluie — trois usages du même métier
 * (fond/remplissage/trait), réutilisés comme une rampe claire → soutenue :
 * même geste que `--couleur-pente-1..4` sur `ProfilAltitude`, jamais un
 * quatrième jeton pour « sec » (aucun remplissage, le papier suffit). */
export const JETON_PLUIE: Record<NiveauPluie, string | null> = {
  "aucune-donnee": null,
  sec: null,
  faible: "--couleur-pluie-fond",
  modere: "--couleur-pluie-remplissage",
  fort: "--couleur-pluie-trait",
};

const LIBELLE_NIVEAU: Record<NiveauPluie, string> = {
  "aucune-donnee": "pluie inconnue",
  sec: "sec",
  faible: "pluie faible",
  modere: "pluie modérée",
  fort: "pluie forte",
};

export function polaire(rayon: number, azimutDeg: number): { x: number; y: number } {
  const rad = (azimutDeg * Math.PI) / 180;
  return { x: CENTRE + rayon * Math.sin(rad), y: CENTRE - rayon * Math.cos(rad) };
}

/** Un secteur annulaire (donut) centré sur `azimutDeg`, de largeur `largeurDeg`. */
export function cheminSecteur(rInterieur: number, rExterieur: number, azimutDeg: number, largeurDeg: number): string {
  const a0 = azimutDeg - largeurDeg / 2;
  const a1 = azimutDeg + largeurDeg / 2;
  const pExt0 = polaire(rExterieur, a0);
  const pExt1 = polaire(rExterieur, a1);
  const pInt1 = polaire(rInterieur, a1);
  const pInt0 = polaire(rInterieur, a0);
  return [
    `M ${pExt0.x.toFixed(1)} ${pExt0.y.toFixed(1)}`,
    `A ${rExterieur} ${rExterieur} 0 0 1 ${pExt1.x.toFixed(1)} ${pExt1.y.toFixed(1)}`,
    `L ${pInt1.x.toFixed(1)} ${pInt1.y.toFixed(1)}`,
    `A ${rInterieur} ${rInterieur} 0 0 0 ${pInt0.x.toFixed(1)} ${pInt0.y.toFixed(1)}`,
    "Z",
  ].join(" ");
}

function nomDirection(code: string): string {
  // Réutilise la table de `formats.ts` : une simple correspondance
  // code → nom en français, pas spécifique au vent malgré son nom — une
  // seconde table dupliquerait la même donnée sous un autre nom.
  return VENT_DEPUIS_EN_TOUTES_LETTRES[code] ?? code;
}

/** « de face » / « dans le dos » / « de travers », ou `null` si l'API n'a pas tranché. */
function relatifEnMots(relatif: string | null): string | null {
  if (relatif === "face") return "de face";
  if (relatif === "dos") return "dans le dos";
  if (relatif === "travers") return "de travers";
  return null;
}

/** La phrase de vent d'une direction, ou son absence — jamais un vent inventé. */
function phraseVentDirection(direction: DirectionMeteo): string {
  if (direction.ventDepuisDeg === null || direction.ventKmh === null) return "vent inconnu";
  const base = `vent ${ventDepuisAvecPreposition(cardinalDuVent(direction.ventDepuisDeg))} à ${nombre(direction.ventKmh, 0)} km/h`;
  const relatif = relatifEnMots(direction.relatif);
  return relatif ? `${base}, ${relatif}` : base;
}

/** L'étiquette accessible complète d'un secteur — le canal non coloré ultime :
 * tout ce que la forme et la couleur disent, en mots, pour qui ne les voit pas. */
export function libelleSecteur(direction: DirectionMeteo, recommandee: boolean): string {
  const morceaux = [nomDirection(direction.nom)];
  morceaux.push(
    direction.pluieMm === null
      ? "pluie inconnue"
      : `${LIBELLE_NIVEAU[direction.niveau]}, ${nombre(direction.pluieMm, 1)} mm`,
  );
  if (direction.desaccord) morceaux.push("modèles météo en désaccord");
  morceaux.push(phraseVentDirection(direction));
  if (recommandee) morceaux.push("recommandée");
  return morceaux.join(" — ");
}

/** La phrase d'une ligne, pour le résumé compact de `Aujourdhui.tsx`
 * (`RoseResume` plus bas) — les mêmes mots que `libelleSecteur`, dans
 * l'ordre d'une phrase plutôt qu'une liste. */
export function resumeDirection(direction: DirectionMeteo): string {
  const pluie =
    direction.pluieMm === null
      ? "pluie inconnue"
      : direction.niveau === "sec"
        ? "sec"
        : `${LIBELLE_NIVEAU[direction.niveau]} (${nombre(direction.pluieMm, 1)} mm${direction.desaccord ? ", désaccord entre modèles" : ""})`;
  return `${nomDirection(direction.nom)} : ${pluie}, ${phraseVentDirection(direction)}.`;
}

/** L'azimut d'où vient le vent, ramené au cardinal le plus proche — pour la
 * phrase seulement, jamais pour reclasser face/dos/travers (ça, c'est
 * `vent_relatif`, déjà tranché par l'API). */
function cardinalDuVent(azimutDeg: number): string {
  const index = Math.round((((azimutDeg % 360) + 360) % 360) / 45) % 8;
  return HUIT_DIRECTIONS[index];
}

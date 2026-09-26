/** Ce que la carte dessine, et comment : tuiles, flèches de vent, styles des tracés.
 *
 * Séparé de `Carte.tsx` pour que le composant ne garde que le montage de
 * Leaflet ; tout ce qui est ici se lit et se teste sans carte réelle.
 */

import L from "leaflet";
import type { FlecheVent } from "../../api/types";

export const TUILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

/**
 * La forme de la flèche, reprise telle quelle de `sortie/carte.py`.
 *
 * Elle pointe vers le haut dans un carré de 20 × 20 ; la rotation autour du
 * centre (10, 10) l'oriente sur `depuis_deg`, la convention météo (0 = nord,
 * sens horaire). Elle montre donc **d'où vient** le vent, comme une girouette.
 */
const FORME_FLECHE = "M10 1 L17 18 L10 14 L3 18 Z";

const VENT_EN_MOTS: Record<string, string> = {
  face: "vent de face",
  dos: "vent dans le dos",
  travers: "vent de travers",
};

/**
 * Le marqueur d'une flèche : le dessin, sa rotation, et les chiffres dessous.
 *
 * La forme change avec le vent relatif — pleine pour un vent de face, creuse
 * pour un vent de dos, en pointillé pour un vent de travers — et pas
 * seulement la couleur : la page du sprint 5 avait déjà tranché ce point
 * pour que la carte reste lisible en noir et blanc et pour un daltonien.
 */
export function icone(fleche: FlecheVent): L.DivIcon {
  const categorie = fleche.relatif ?? "inconnu";
  const etiquette =
    fleche.rafale_kmh === null
      ? String(fleche.vent_kmh)
      : `${fleche.vent_kmh}/${fleche.rafale_kmh}`;
  return L.divIcon({
    className: "",
    html:
      `<div class="vent-marqueur vent-${categorie}">` +
      `<svg class="vent-fleche" viewBox="0 0 20 20" aria-hidden="true">` +
      `<g transform="rotate(${fleche.depuis_deg} 10 10)">` +
      `<path class="fleche-forme" d="${FORME_FLECHE}"></path></g></svg>` +
      `<span class="vent-etiquette">${etiquette}</span></div>`,
    iconSize: undefined,
    iconAnchor: [10, 10],
  });
}

export function infobulle(fleche: FlecheVent): string {
  let texte = `Vent ${fleche.vent_kmh} km/h`;
  if (fleche.rafale_kmh !== null) texte += `, rafales ${fleche.rafale_kmh} km/h`;
  const mots = fleche.relatif === null ? undefined : VENT_EN_MOTS[fleche.relatif];
  if (mots) texte += ` — ${mots} ici`;
  return texte;
}

/**
 * En dessous de cette distance à l'écran (pixels), deux étiquettes de vent se
 * chevauchent — constat de l'agent superviseur sur une capture de production
 * (25/09/2026, trois boucles de ~124 km autour de Rennes, vitesse **et**
 * rafale empilées dans chaque étiquette). Mesuré à l'œil sur `.vent-
 * etiquette` (`style.css`) : une étiquette « 24/38 » tient sur une
 * quarantaine de pixels de large.
 */
export const SEUIL_CHEVAUCHEMENT_VENT_PX = 46;

/**
 * Filtre générique : garde `items` dans l'ordre reçu, en jetant tout élément
 * dont le point projeté tombe à moins de `seuilPx` d'un élément déjà gardé.
 *
 * Pure et sans Leaflet — testable directement avec des points en pixels
 * inventés, pas besoin de faire tourner une vraie carte (`Carte` l'appelle
 * avec `carte.latLngToContainerPoint`, mais le test n'en a pas besoin).
 * Le premier élément d'un groupe qui se chevauche gagne : `vents` arrive déjà
 * trié le long du tracé par le cœur, donc « le premier » n'est pas un choix
 * arbitraire, c'est l'ordre où on les rencontre en roulant.
 */
export function sansChevauchement<T>(
  items: T[],
  point: (item: T) => { x: number; y: number },
  seuilPx: number,
): T[] {
  const gardees: T[] = [];
  const points: { x: number; y: number }[] = [];
  for (const item of items) {
    const p = point(item);
    const chevauche = points.some((q) => Math.hypot(p.x - q.x, p.y - q.y) < seuilPx);
    if (chevauche) continue;
    gardees.push(item);
    points.push(p);
  }
  return gardees;
}

export interface TraceDessinee {
  points: [number, number][];
  /** Le tracé retenu est plein ; les autres sont en pointillé (maquette E19). */
  choisi: boolean;
  /**
   * `ecartee` : le produit l'a jetée, et le lot F2.4 la montre quand même —
   * trait fin et très pointillé (encre, comme une retenue, mais plus fin et
   * sans dérouler tout le tracé), pour qu'elle se distingue d'une
   * proposition non choisie sans jamais lui ressembler. Écarter une
   * candidate est une décision de l'algorithme, pas une mesure (règle 3,
   * direction « suisse vivante ») — elle n'a donc plus de rouge depuis
   * l'application de cette direction : c'est la FORME du trait qui la
   * distingue, jamais une couleur, cohérent avec les flèches de vent et la
   * matrice d'`Arbitrage`.
   */
  sort?: "retenue" | "ecartee";
  titre?: string;
}

/**
 * Comment un tracé se dessine, selon ce que le produit en a décidé.
 *
 * Aucune couleur en dur ici : le sort d'un tracé (retenu / non choisi /
 * écarté) est une décision, pas une mesure (règle 3, direction « suisse
 * vivante ») — elle reste en encre, jamais en couleur, y compris pour une
 * candidate écartée (qui portait un rouge avant ce lot). `className` porte
 * le style jusqu'à `front/src/style.css` (`.trace-retenue`, `.trace-non-
 * choisie`, `.trace-ecartee`), la seule source de vérité pour `stroke`/
 * `stroke-width`/`stroke-dasharray` : une règle CSS de classe l'emporte
 * toujours sur les attributs de présentation SVG que pose Leaflet par
 * défaut, donc rien à dupliquer ici. Le tracé reste distingué par sa FORME
 * (poids, pointillé), jamais par sa seule couleur — lisible en noir et
 * blanc et pour un daltonien.
 */
export function styleDe(trace: TraceDessinee): L.PolylineOptions {
  if (trace.sort === "ecartee") {
    // Pointillé **rond** et non tiret : la forme distingue une écartée d'une
    // retenue non choisie sans dépendre de la couleur.
    return { className: "trace-ecartee", opacity: 0.9, lineCap: "round" };
  }
  if (trace.choisi) {
    return { className: "trace-retenue", opacity: 1 };
  }
  return { className: "trace-non-choisie", opacity: 0.7 };
}

/**
 * Le style d'une portion colorée par le vent — deux teintes seulement,
 * jamais trois : le travers et l'inconnu ne passent jamais par ici (voir
 * `SegmentVent`), donc pas de troisième branche à écrire « en encre » ici,
 * c'est simplement l'absence de portion qui le fait.
 *
 * `dashArray` porte le canal non coloré (règle d'accessibilité absolue) :
 * plein pour le vent dans le dos, tireté pour le vent de face — le même
 * distinguo que les flèches (pleine/creuse) et que les tracés candidats,
 * lisible sans la couleur.
 */
export function styleVentDe(segment: SegmentVent): L.PolylineOptions {
  if (segment.categorie === "dos") {
    return { color: "var(--couleur-vent-dos-remplissage)", weight: 5, opacity: 0.95 };
  }
  return {
    color: "var(--couleur-vent-face-remplissage)",
    weight: 5,
    opacity: 0.95,
    dashArray: "9 6",
  };
}

export interface SegmentDessine {
  points: [number, number][];
  couleur: string;
  titre?: string;
}

/**
 * Une portion du tracé retenu, colorée par ce que le vent y coûte (point 5
 * du lot d'affordance, 20/09/2026).
 *
 * `ChampVent` (`seance.vent`) le dit déjà : le vent est interrogeable à
 * n'importe quelle position du tracé, pas seulement aux huit points des
 * flèches. `vent_par_position` (API) donne une catégorie par échantillon ;
 * l'écran appelant en fait des portions avec `portion()` (même fonction
 * que pour les blocs de la séance) et ne garde que celles qui portent une
 * couleur — le travers et l'inconnu restent le tracé noir de base, en
 * encre, jamais une couleur (règle absolue 5 : ni gênant ni favorable pour
 * l'un, une incertitude pour l'autre). `Carte` choisit seule la teinte et
 * le motif exacts (`styleVentDe` ci-dessous) : l'écran ne fait que trier
 * « face » de « dos », jamais une couleur.
 */
export interface SegmentVent {
  points: [number, number][];
  categorie: "face" | "dos";
  titre?: string;
}

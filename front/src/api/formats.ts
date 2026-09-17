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

/**
 * Vrai quand un kilométrage vaut encore quelque chose **une fois arrondi**.
 *
 * Sert aux chiffres qui ne s'affichent que lorsqu'ils existent. Tester
 * `> 0` ne suffisait pas : mesuré sur un vrai parcours, les kilomètres non
 * classés valaient 0,04 et l'écran annonçait « 0,0 km qu'on ne sait pas
 * classer » — un zéro, donc du bruit, à l'endroit précis où l'on voulait
 * dire quelque chose. Ce n'est pas un seuil produit, c'est la même décimale
 * que celle qu'on affiche.
 */
export function visibleEnKm(valeur: number): boolean {
  return Math.round(valeur * 10) > 0;
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
 * Le **nombre** de feux et stops d'un parcours — lu, jamais calculé.
 *
 * Cette fonction multipliait `densite_marqueurs_km` par la distance pour
 * retrouver l'entier d'origine. Le résultat était juste, et c'était quand
 * même la mauvaise méthode (relecture F2 · C1) :
 *
 * - le cœur portait déjà l'entier, sur le même objet que la densité
 *   (`sortie/contraste.py`), simplement non sérialisé — il l'est depuis le
 *   17/09/2026 ;
 * - le commentaire de ce champ-là désigne nommément ce geste comme celui à ne
 *   pas faire : « une densité au kilomètre invitait à multiplier — 1,7 au km,
 *   donc 170 sur 100 km » ;
 * - la densité est arrondie à trois décimales, donc le produit sortait de sa
 *   tolérance au-delà d'environ 100 km et **le chiffre disparaissait sans
 *   explication** — précisément pour qui prépare une sortie longue.
 *
 * Il ne reste ici qu'une somme de deux entiers que l'API rend. `null` quand le
 * tracé ne porte pas de tag de nœud : le cœur les met à `null` ensemble, et
 * l'ignorance ne s'affiche pas comme un zéro (règle absolue 5).
 */
export function compteArrets(feux: number | null, stops: number | null): number | null {
  if (feux === null || stops === null) return null;
  return feux + stops;
}

/** Les huit directions en toutes lettres, avec la préposition qui va avec. */
const DIRECTIONS = [
  "au nord",
  "au nord-est",
  "à l'est",
  "au sud-est",
  "au sud",
  "au sud-ouest",
  "à l'ouest",
  "au nord-ouest",
];

/**
 * Le titre d'une boucle libre — **sa direction, pas le nom du moteur**.
 *
 * `candidate.nom` vaut « Boucle 340° 5.8 km », où « 5.8 km » est le **rayon**
 * demandé au traceur. Affiché en titre, trois centimètres au-dessus de la
 * longueur réelle — « 24,8 km » — ça donnait deux distances contradictoires,
 * et le titre est ce qu'on lit en premier : il mentait de 19 kilomètres
 * (relecture F2 · C6). Le nom du moteur est un identifiant de moteur.
 *
 * Reste la direction, qui est ce qui distingue vraiment deux boucles libres,
 * et que la demande a explicitement posée.
 */
export function titreDeBoucle(azimutDeg: number | null, numero: number): string {
  if (azimutDeg === null) return `Boucle ${numero}`;
  return `Boucle ${DIRECTIONS[Math.round((((azimutDeg % 360) + 360) % 360) / 45) % 8]}`;
}

/**
 * La direction demandée, en toutes lettres — « SE » est un code d'entrée.
 *
 * Le champ vaut ce que le front a envoyé au moteur : « N », « SO »… L'écran
 * l'affichait tel quel en en-tête pendant que `titreDeBoucle` écrivait
 * « Boucle au sud-ouest » deux centimètres plus bas. Un azimut en degrés
 * passe aussi par ce champ ; on le rend alors à la boussole la plus proche
 * plutôt que d'afficher « 155° » à quelqu'un qui va rouler.
 */
export function directionEnToutesLettres(direction: string): string {
  const code = direction.trim().toUpperCase();
  const index = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"].indexOf(code);
  if (index >= 0) return DIRECTIONS[index];
  const degres = Number(code.replace("°", ""));
  if (Number.isFinite(degres)) {
    return DIRECTIONS[Math.round((((degres % 360) + 360) % 360) / 45) % 8];
  }
  // Un libellé que le front ne reconnaît pas s'affiche tel quel plutôt que de
  // disparaître : on préfère un mot brut à un silence (même parti pris que
  // `modelePhysique`).
  return direction;
}

/**
 * D'où viennent les paramètres physiques du vélo, **dit à un cycliste**.
 *
 * `modele_physique` vaut « calibration », « configuration » ou « défaut » :
 * c'est le vocabulaire du cœur (`physique/commande.parametres_du_velo`), et
 * il s'affichait tel quel au bout d'une phrase écrite pour quelqu'un qui va
 * rouler — « … — modèle calibration » (relecture F2 · C7).
 *
 * La traduction garde ce que ces mots distinguent, qui est le seul point
 * qui compte : une mesure n'est pas une supposition (règle absolue 5).
 */
export const MODELE_PHYSIQUE_EN_TOUTES_LETTRES: Record<string, string> = {
  calibration: "mesuré sur vos sorties",
  configuration: "d'après les caractéristiques que vous avez saisies",
  défaut: "valeurs par défaut, faute de mesure",
};

export function modelePhysique(provenance: string | null): string | null {
  if (provenance === null) return null;
  // Un mot que le cœur ajouterait sans qu'on le sache s'affiche tel quel
  // plutôt que de disparaître : on préfère un mot brut à un silence.
  return MODELE_PHYSIQUE_EN_TOUTES_LETTRES[provenance] ?? provenance;
}

/**
 * L'usage d'un vélo, dit comme le cycliste l'a choisi.
 *
 * `usage` vaut « route », « clm », « gravel »… — les valeurs de la
 * configuration. Les deux formulaires de l'application les traduisent déjà
 * dans leurs listes déroulantes (« Chrono » pour `clm`) ; l'affichage en
 * lecture seule, lui, montrait la valeur brute. Sur le récapitulatif de
 * l'assistant, le cycliste venait de cliquer « Chrono » et lisait « clm »
 * trois secondes plus tard.
 */
export const USAGE_VELO: Record<string, string> = {
  route: "Route",
  clm: "Chrono",
  gravel: "Gravel",
  vtt: "VTT",
};

export function usageDeVelo(usage: string): string {
  return USAGE_VELO[usage] ?? usage;
}

/**
 * D'où vient une adresse trouvée, **nommé plutôt que codé**.
 *
 * `source` vaut « ban » ou « nominatim » : les noms des deux services de
 * géocodage. Affichés tels quels sous une adresse, ils ne disent rien à
 * personne — et le score qui les suivait était présenté comme une
 * « confiance sur 100 » alors que le cœur écrit noir sur blanc qu'il n'est
 * comparable qu'entre candidats de la même source. Deux grandeurs
 * différentes, une seule échelle affichée : on garde la provenance, qui
 * distingue vraiment, et on laisse tomber le chiffre, qui trompe.
 */
export const SOURCE_ADRESSE: Record<string, string> = {
  ban: "adresses officielles françaises",
  nominatim: "OpenStreetMap",
};

export function sourceDAdresse(source: string): string {
  return SOURCE_ADRESSE[source] ?? source;
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

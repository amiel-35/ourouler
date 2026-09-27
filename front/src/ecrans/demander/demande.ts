/** La demande de parcours et ses mises en forme : des fonctions pures, sans état. */

import type { AzimutVent, Enveloppe, ValeursLiees, VentDepart } from "../../api/types";
import { nombre, ventDepuisAvecPreposition } from "../../api/formats";
import { aujourdhui } from "../../etat/ressource";
/** Les trois préférences de « selon le vent », dans l'ordre de la décision Q44. */
export const PREFERENCES_VENT = ["depart-dos", "retour-dos", "travers"];

/**
 * Un motif ou un message d'échec qui porte une URL ou un code HTTP — le
 * signe qu'il vient tel quel d'un connecteur externe (Open-Meteo, ici) et
 * n'a pas été mis en français pour le cycliste. Exemple réel : « vent au départ
 * indisponible (Open-Meteo : HTTP 400 sur https://api.open-meteo.com/v1/
 * forecast — No data is available for this location…) » s'affichait tel
 * quel sous « Direction ». On ne montre jamais ce détail — il reste
 * dans le `title` de la phrase, pour qui inspecte la page.
 */
const MOTIF_TECHNIQUE = /:\/\/|\bhttp\b/i;

export const MESSAGE_VENT_INDISPONIBLE = "Le vent au départ n'est pas disponible pour ce point de départ.";

export interface Demande {
  mode: "seance" | "z2";
  jour: string;
  heure_depart: string;
  duree_min: number;
  /**
   * Le **premier choix** (décision Q44) : indépendant de `mode`, il décide lequel
   * des deux sélecteurs suivants s'affiche — jamais les deux à la fois, pour
   * que la contradiction entre eux disparaisse par la forme.
   */
  modeDirection: "peu-importe" | "direction" | "vent";
  vent: string;
  direction: string;
  depart: { latitude: number; longitude: number; nom: string } | null;
  candidates: number;
}

/** Le jour d'une date, en AAAA-MM-JJ — même règle que `aujourdhui()`
 * (`etat/ressource.ts`), mais appliquée à l'horloge reçue plutôt qu'à
 * l'horloge système, pour que `heureDepartParDefaut` reste testable sans
 * dépendre de la machine ni du fuseau de la CI (qui tourne en UTC). */
function jourDe(date: Date): string {
  const decalage = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - decalage).toISOString().slice(0, 10);
}

/** L'heure locale d'une date, arrondie au quart d'heure supérieur,
 * "HH:MM" — un quart d'heure déjà pile ne bouge pas, et un dépassement de
 * minuit s'affiche tel quel (23:50 → 00:00), sans cas particulier. */
function arrondieAuQuartHeureSuivant(date: Date): string {
  const minutesTotales = date.getHours() * 60 + date.getMinutes();
  const arrondi = Math.ceil(minutesTotales / 15) * 15;
  const minutesDuJour = arrondi % (24 * 60);
  const heures = Math.floor(minutesDuJour / 60);
  const minutes = minutesDuJour % 60;
  return `${String(heures).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

/**
 * L'heure de départ par défaut (QP3, backlog « Séance du jour à l'heure
 * réelle ») : le jour même, l'heure courante arrondie au quart d'heure
 * suivant ; un autre jour, "09:00" comme avant.
 *
 * `maintenant` est l'horloge, injectable : les tests lui passent une date
 * fixe plutôt que de dépendre de l'heure de la machine ou du fuseau de la
 * CI (qui tourne en UTC), et restent donc déterministes.
 */
export function heureDepartParDefaut(jour: string, maintenant: () => Date = () => new Date()): string {
  const maintenant_ = maintenant();
  if (jour !== jourDe(maintenant_)) return "09:00";
  return arrondieAuQuartHeureSuivant(maintenant_);
}

export function demandeInitiale(maintenant: () => Date = () => new Date()): Demande {
  const jour = aujourdhui();
  return {
    mode: "seance",
    jour,
    heure_depart: heureDepartParDefaut(jour, maintenant),
    duree_min: 120,
    modeDirection: "peu-importe",
    vent: "peu-importe",
    direction: "N",
    depart: null,
    candidates: 3,
  };
}

/** `2:00` → 120 minutes. `90` → 90 minutes. Rien de lisible → `null`. */
export function minutesDe(texte: string): number | null {
  const propre = texte.trim().replace(",", ":").replace("h", ":");
  if (propre.includes(":")) {
    const [h, m] = propre.split(":");
    const heures = Number(h);
    const minutes = Number(m || "0");
    if (!Number.isFinite(heures) || !Number.isFinite(minutes)) return null;
    return Math.round(heures * 60 + minutes);
  }
  const brut = Number(propre);
  return Number.isFinite(brut) && brut > 0 ? Math.round(brut) : null;
}

export function texteDuree(minutes: number): string {
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/**
 * La phrase sous « Ce que ça donnera » : la plus courte possible, sans
 * chiffre de moyenne compteur ni jargon (« modèle physique littérature »).
 *
 * Mesuré = le facteur de compteur est mesuré sur l'historique, ou le vélo est
 * calibré (`modele_physique === "calibration"` — la calibration mesure aussi
 * bien la vitesse que la puissance, donc l'un ou l'autre suffit à dire
 * « mesuré »). Sinon, l'estimation ne repose que sur le profil déclaré et les
 * caractéristiques du vélo — jamais mesurées.
 *
 * La provenance détaillée (le facteur, le modèle physique, chiffre par
 * chiffre) reste ailleurs, dans Réglages, sous le dépliant « D'où viennent
 * ces deux chiffres » — la règle de provenance de la doctrine ne bouge pas,
 * c'est seulement cette phrase-ci qui se simplifie.
 */
export function phraseEstimation(liees: ValeursLiees): string {
  const mesure = liees.facteur_mesure || liees.modele_physique === "calibration";
  return mesure
    ? "Estimation d'après vos sorties."
    : "Estimation d'après votre profil et votre vélo.";
}

/**
 * La phrase du vent, ou pourquoi il n'y en a pas — jamais un vent inventé,
 * et jamais non plus le détail technique d'un connecteur externe : `texte`
 * est ce qui s'affiche, `detail` (quand il existe) le motif brut, réservé
 * au `title` de la phrase. `chargement` distingue l'attente initiale d'une
 * vraie absence, pour ne pas proposer le lien vers Réglages trop tôt.
 */
export function informationVent(
  vent: Enveloppe<VentDepart> | null,
  erreurVent: string | null,
): { texte: string; detail: string | null; chargement: boolean } {
  if (erreurVent !== null) {
    const technique = MOTIF_TECHNIQUE.test(erreurVent);
    return {
      texte: technique ? MESSAGE_VENT_INDISPONIBLE : erreurVent,
      detail: technique ? erreurVent : null,
      chargement: false,
    };
  }
  if (vent === null) return { texte: "Vent : en cours…", detail: null, chargement: true };
  const donnees = vent.donnees;
  if (!donnees.posee) {
    const motif = donnees.motif;
    const technique = motif !== null && MOTIF_TECHNIQUE.test(motif);
    return {
      texte: technique ? MESSAGE_VENT_INDISPONIBLE : (motif ?? "Le vent n'est pas connu pour ce départ."),
      detail: technique ? motif : null,
      chargement: false,
    };
  }
  if (donnees.vent_depuis_nom === null || donnees.vent_kmh === null) {
    return { texte: "Le vent n'est pas connu pour ce départ.", detail: null, chargement: false };
  }
  return {
    texte: `Vent ${ventDepuisAvecPreposition(donnees.vent_depuis_nom)} à ${nombre(
      donnees.vent_kmh,
      0,
    )} km/h`,
    detail: null,
    chargement: false,
  };
}

/** L'azimut (ou les deux, pour le latéral) qu'une préférence imposerait. */
export function azimutsTexte(items: AzimutVent[]): string {
  if (items.length === 0) return "azimut non communiqué";
  return items.map((a) => `${a.nom} (${nombre(a.azimut_deg, 0)}°)`).join(" et ");
}

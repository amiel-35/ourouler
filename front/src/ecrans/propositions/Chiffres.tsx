/** Les chiffres d'une proposition — ceux qui comptent pour elle, pas une grille fixe. */

import type { Candidate, Proposition } from "../../api/types";
import { compteArrets, duree, nombre, pourcentage, VENT_DECRIT } from "../../api/formats";
import { textePorteAPorte } from "../../composants/TempsEcoule";

/** Le nom de l'axe sur lequel le cœur a distingué cette proposition. */
export const AXES: Record<string, string> = {
  vent: "Le vent",
  pluie: "La pluie",
  ville: "Les arrêts",
  trafic: "Le trafic",
  demi_tours: "Les demi-tours",
  duree: "La durée",
  terrain: "Le terrain",
};

export interface Chiffre {
  cle: string;
  valeur: string;
  /** Second rang : présent, mais pas la réponse à la question posée. */
  second?: boolean;
}

/** Les chiffres qui comptent **pour cette proposition-là**. */
export function chiffresDe(proposition: Proposition, candidate: Candidate | null): Chiffre[] {
  const chiffres: Chiffre[] = [];
  if (candidate) chiffres.push({ cle: "km", valeur: nombre(candidate.distance_km, 1) });
  // Le porte à porte en majeur, le temps sans arrêt juste après
  // (18/09/2026) : « je demande 5 h, je veux 5 h, pas 4 h et un truc plus
  // loin qui me dit en fait c'est 5 h ». Sans porte à porte — aucun vélo,
  // donc aucune fourchette — le temps de mouvement reste seul, mais garde
  // son nom. Depuis L9.1, le porte à porte est une fourchette.
  const ecoule = candidate?.temps_ecoule_s;
  if (ecoule === null || ecoule === undefined) {
    chiffres.push({ cle: "en roulant", valeur: duree(proposition.duree_s) });
  } else {
    chiffres.push({
      cle: "porte à porte",
      valeur: textePorteAPorte(
        ecoule,
        candidate?.temps_ecoule_bas_s,
        candidate?.temps_ecoule_haut_s,
      ),
    });
    chiffres.push({
      cle: "sans un seul arrêt",
      valeur: duree(proposition.duree_s),
      second: true,
    });
  }
  if (candidate?.denivele_m !== null && candidate?.denivele_m !== undefined) {
    chiffres.push({ cle: "m D+", valeur: nombre(candidate.denivele_m) });
  }
  const axe = proposition.axe_distinctif ?? "";
  // La pluie se dessine désormais (`JaugePluie`, rendue à côté de ces
  // chiffres dans `Propositions.tsx`) plutôt que de s'écrire ici en texte —
  // ni doublon, ni régression : la même valeur, en jauge.
  if (axe === "trafic" && proposition.part_trafic !== null) {
    chiffres.push({ cle: "de trafic", valeur: pourcentage(proposition.part_trafic) });
  }
  if (axe === "demi_tours") {
    chiffres.push({ cle: "demi-tours", valeur: nombre(proposition.demi_tours) });
  }
  if (axe === "vent" && proposition.orientation_vent) {
    chiffres.push({
      cle: "",
      valeur: VENT_DECRIT[proposition.orientation_vent] ?? proposition.orientation_vent,
    });
  }
  const arrets = compteArrets(proposition.feux, proposition.stops);
  if (axe === "ville" && arrets !== null) {
    chiffres.push({ cle: "feux et stops", valeur: nombre(arrets) });
  }
  return chiffres;
}

export function Chiffres({ chiffres }: { chiffres: Chiffre[] }) {
  return (
    <div className="chiffres">
      {/* La clé peut être vide — « 1 h 05 » n'a pas d'unité à répéter — donc
          deux chiffres peuvent la partager : l'index sert de clé React. */}
      {chiffres.map((chiffre, rang) => (
        <span key={`${rang}-${chiffre.cle}`} className={chiffre.second ? "second-chiffre" : undefined}>
          {chiffre.second ? chiffre.valeur : <b>{chiffre.valeur}</b>} {chiffre.cle}
        </span>
      ))}
    </div>
  );
}

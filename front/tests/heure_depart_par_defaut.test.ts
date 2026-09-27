/** Backlog « Séance du jour à l'heure réelle » (2026-09-26) — QP3.
 *
 * Constaté en production le 25/09/2026 vers 17:30 : « Aujourd'hui » proposait
 * « 9 h 00 … retour vers 9 h 52 » avec une tenue d'automne alors qu'il
 * faisait environ 30 °C au moment réel du départ. `demandeInitiale()` posait
 * `heure_depart: "09:00"` en dur, sans jamais regarder l'heure courante.
 *
 * `heureDepartParDefaut` corrige ça : le jour même, l'heure courante
 * arrondie au quart d'heure suivant ; un autre jour, "09:00" comme avant.
 * L'horloge est un paramètre injectable — ces tests ne dépendent ni de
 * l'heure de la machine qui les exécute, ni du fuseau de la CI (UTC) :
 * `new Date(annee, mois, jour, heures, minutes)` construit une date locale à
 * l'exécution, quel que soit ce fuseau, et c'est cette même date qui sert à
 * la fois à fabriquer l'horloge injectée et le `jour` attendu.
 */

import { describe, expect, it } from "vitest";
import { demandeInitiale, heureDepartParDefaut } from "../src/ecrans/demander/demande";
import { aujourdhui } from "../src/etat/ressource";

/** Le AAAA-MM-JJ d'une date locale — même conversion que `aujourdhui()`. */
function jourDe(date: Date): string {
  const decalage = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - decalage).toISOString().slice(0, 10);
}

describe("heureDepartParDefaut", () => {
  it("arrondit au quart d'heure suivant, le jour même : 14:37 → 14:45", () => {
    const maintenant = new Date(2026, 8, 25, 14, 37);
    expect(heureDepartParDefaut(jourDe(maintenant), () => maintenant)).toBe("14:45");
  });

  it("ne bouge pas quand l'heure courante est déjà pile un quart d'heure : 14:45 → 14:45", () => {
    const maintenant = new Date(2026, 8, 25, 14, 45);
    expect(heureDepartParDefaut(jourDe(maintenant), () => maintenant)).toBe("14:45");
  });

  it("affiche le dépassement de minuit tel quel, sans cas particulier : 23:50 → 00:00", () => {
    const maintenant = new Date(2026, 8, 25, 23, 50);
    expect(heureDepartParDefaut(jourDe(maintenant), () => maintenant)).toBe("00:00");
  });

  it("reste à 09:00 pour un autre jour que celui de l'horloge, quelle que soit l'heure", () => {
    const maintenant = new Date(2026, 8, 25, 20, 3);
    const demain = jourDe(new Date(2026, 8, 26));
    expect(heureDepartParDefaut(demain, () => maintenant)).toBe("09:00");
  });

  it("une heure déjà avancée dans la journée n'est pas plafonnée à 09:00 (le sujet est le départ réel)", () => {
    // Réouverture à 20 h un jour de séance : ce n'est pas une régression,
    // "Aujourd'hui" affiche 20:15, pas 09:00 — voir « Hors sujet » de la
    // fiche (pas de plafond ni d'avertissement inventé).
    const maintenant = new Date(2026, 8, 25, 20, 5);
    expect(heureDepartParDefaut(jourDe(maintenant), () => maintenant)).toBe("20:15");
  });
});

describe("demandeInitiale", () => {
  it("pose heure_depart via heureDepartParDefaut, pour aujourd'hui, pas 09:00 en dur", () => {
    const maintenant = new Date();
    maintenant.setHours(20, 3, 0, 0);
    const attendu = heureDepartParDefaut(aujourdhui(), () => maintenant);
    expect(demandeInitiale(() => maintenant).heure_depart).toBe(attendu);
    expect(demandeInitiale(() => maintenant).jour).toBe(aujourdhui());
  });
});

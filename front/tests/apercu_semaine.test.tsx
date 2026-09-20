/** `ApercuSemaine` (`ecrans/MaSemaine.tsx`) — l'aperçu en sept colonnes,
 * ajouté le 20/09/2026 pour répondre à « ma semaine est-elle chargée ? »
 * sans additionner de tête la durée de chaque carte.
 *
 * Ce que ces tests protègent :
 *
 * - un jour de repos (`seance: null`) ne dessine jamais une barre — règle
 *   absolue 5, une absence de séance n'est pas une séance de durée nulle ;
 * - le résumé accessible (`aria-label`) dit un nombre de séances et une
 *   durée totale, tous deux calculés depuis les données reçues ;
 * - chaque colonne porte, dans un `<title>`, le jour et sa durée — jamais un
 *   second nombre qui ne soit pas déjà à l'écran ailleurs (voir le
 *   commentaire de `MaSemaine.tsx` sur la fusion de tokens dans
 *   `tests/provenance.test.tsx`).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ApercuSemaine } from "../src/ecrans/MaSemaine";
import type { Semaine } from "../src/api/types";

const SEMAINE_TEST: Semaine["jours"] = [
  {
    jour: "2026-09-14",
    seance: { jour: "2026-09-14", nom: "Longue", duree_s: 9900, n_blocs: 0, distance_estimee_m: 74_300 },
  },
  { jour: "2026-09-15", seance: null },
  {
    jour: "2026-09-16",
    seance: { jour: "2026-09-16", nom: "Séance", duree_s: 4380, n_blocs: 3, distance_estimee_m: 31_400 },
  },
];

describe("ApercuSemaine", () => {
  it("porte un résumé accessible avec le nombre de séances et la durée totale", () => {
    render(<ApercuSemaine jours={SEMAINE_TEST} aujourdhui="2026-09-16" />);
    const svg = screen.getByRole("img");
    // 9900 + 0 + 4380 = 14280 s = 3 h 58.
    expect(svg.getAttribute("aria-label")).toMatch(/2 séance\(s\)/);
    // `duree()` sépare les nombres par des espaces insécables, pas des
    // espaces ordinaires.
    expect(svg.getAttribute("aria-label")).toMatch(/3.h.58/);
  });

  it("un jour de repos porte un point, jamais une barre à hauteur zéro", () => {
    const { container } = render(<ApercuSemaine jours={SEMAINE_TEST} aujourdhui="2026-09-16" />);
    // Une seule séance a duree_s le plus court (4380s) donc une seule autre
    // (9900s) : deux `<rect>` de séance, et le jour de repos est un
    // `<circle>`, jamais un troisième `<rect>`.
    expect(container.querySelectorAll("rect").length).toBe(2);
    expect(container.querySelectorAll("circle").length).toBe(1);
  });

  it("le jour de repos dit « repos » dans son infobulle, jamais un nombre inventé", () => {
    render(<ApercuSemaine jours={SEMAINE_TEST} aujourdhui="2026-09-16" />);
    expect(screen.getByText("Mar. 15 : repos")).toBeTruthy();
  });

  it("le titre d'une colonne porte le jour et sa durée, sans second nombre collé", () => {
    render(<ApercuSemaine jours={SEMAINE_TEST} aujourdhui="2026-09-16" />);
    expect(screen.getByText("Mer. 16 : 1 h 13")).toBeTruthy();
  });
});

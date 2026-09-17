/** Les mises en forme, et surtout celle qui pourrait mentir.
 *
 * `compteArrets` est la seule fonction du front qui calcule au lieu de
 * transcrire : le JSON n'expose qu'une densité au kilomètre, l'affichage doit
 * montrer un nombre absolu. Le test vérifie qu'elle rend bien l'entier
 * d'origine, et qu'elle **se tait** quand le compte ne retombe pas juste.
 */

import { describe, expect, it } from "vitest";
import { compteArrets, duree, ecartEnJours, pourcentage } from "../src/api/formats";
import { portion } from "../src/ecrans/Proposition";
import { minutesDe, texteDuree } from "../src/ecrans/Demander";
import { phraseBudget } from "../src/composants/Attente";
import { budget } from "./fixtures";

describe("compteArrets", () => {
  it("retrouve l'entier que le cœur avait divisé", () => {
    for (const [compte, distance] of [
      [12, 16.4477],
      [4, 56.231],
      [0, 42.7],
      [170, 100.0],
    ] as [number, number][]) {
      const densite = Number((compte / distance).toFixed(3));
      expect(compteArrets(densite, distance)).toBe(compte);
    }
  });

  it("se tait quand la densité manque, ou quand la distance est nulle", () => {
    expect(compteArrets(null, 40)).toBeNull();
    expect(compteArrets(0.5, null)).toBeNull();
    expect(compteArrets(0.5, 0)).toBeNull();
  });

  it("se tait quand le produit ne retombe pas sur un entier", () => {
    // Une densité qui ne vient pas d'un compte divisé par cette distance-là.
    expect(compteArrets(0.73, 999.5)).toBeNull();
  });
});

describe("durées", () => {
  it("se lisent comme un cycliste les dit", () => {
    expect(duree(2100)).toBe("35 min");
    expect(duree(7200)).toBe("2 h");
    expect(duree(6300)).toBe("1 h 45");
  });

  it("se saisissent en heures:minutes ou en minutes", () => {
    expect(minutesDe("2:00")).toBe(120);
    expect(minutesDe("1:45")).toBe(105);
    expect(minutesDe("90")).toBe(90);
    expect(minutesDe("2h30")).toBe(150);
    expect(minutesDe("n'importe quoi")).toBeNull();
    expect(texteDuree(105)).toBe("1:45");
  });
});

describe("écarts en jours", () => {
  it("nomme les jours proches et compte les autres", () => {
    expect(ecartEnJours("2026-09-16", "2026-09-16")).toBe("aujourd'hui");
    expect(ecartEnJours("2026-09-17", "2026-09-16")).toBe("demain");
    expect(ecartEnJours("2026-09-20", "2026-09-16")).toBe("dans 4 jours");
  });
});

describe("pourcentages", () => {
  it("se lisent entiers", () => {
    expect(pourcentage(0.0162)).toBe("2 %");
    expect(pourcentage(0.317)).toBe("32 %");
  });
});

describe("le budget annoncé", () => {
  it("dit qu'il est mesuré quand il l'est, et sur combien d'exécutions", () => {
    expect(phraseBudget(budget("sortie", "mesure"))).toMatch(/mesuré sur ce serveur, sur 7/);
  });

  it("dit qu'il est par défaut quand ce serveur n'a rien mesuré", () => {
    expect(phraseBudget(budget("sortie", "defaut"))).toMatch(
      /valeur par défaut : ce serveur n'a encore rien mesuré/,
    );
  });

  it("ne ment pas quand il n'y a pas de budget du tout", () => {
    expect(phraseBudget(null)).toMatch(/Durée inconnue/);
  });
});

describe("la portion de tracé sous un bloc", () => {
  it("découpe par la distance cumulée du profil", () => {
    const trace = {
      points: [
        [47.0, -0.5],
        [47.01, -0.5],
        [47.02, -0.5],
        [47.03, -0.5],
      ] as [number, number][],
      profil: [
        [0, 50],
        [1000, 55],
        [2000, 60],
        [3000, 58],
      ] as [number, number][],
      simplification: { tolerance_m: 5, points_origine: 4, points_rendus: 4, ecart_max_m: 0 },
    };
    expect(portion(trace, 1000, 2000)).toEqual([
      [47.01, -0.5],
      [47.02, -0.5],
    ]);
    // Un demi-tour donne un début après la fin : la portion reste la même.
    expect(portion(trace, 2000, 1000)).toEqual([
      [47.01, -0.5],
      [47.02, -0.5],
    ]);
  });
});

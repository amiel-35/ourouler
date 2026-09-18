/** Les mises en forme, et surtout celle qui pourrait mentir.
 *
 * **Le front ne calcule plus rien** (17/09/2026). `compteArrets` était la
 * seule fonction qui calculait au lieu de transcrire : elle multipliait la
 * densité au kilomètre par la distance pour retrouver le nombre absolu de
 * feux et stops. L'API sérialise maintenant ces entiers, et il ne reste
 * qu'une somme — voir la description du groupe ci-dessous.
 */

import { describe, expect, it } from "vitest";
import { compteArrets, duree, dureeApprox, ecartEnJours, pourcentage } from "../src/api/formats";
import { portion } from "../src/ecrans/Proposition";
import { minutesDe, texteDuree } from "../src/ecrans/Demander";
import { phraseBudget } from "../src/composants/Attente";
import { budget } from "./fixtures";

/**
 * **Ces tests gardaient une multiplication qui n'a plus lieu d'être** (C1).
 *
 * Ils vérifiaient que `compteArrets(densité, distance)` retrouvait l'entier
 * que le cœur avait divisé, et qu'elle se taisait quand le produit ne
 * retombait pas juste. Le calcul était correct — mais l'entier existait déjà
 * dans le cœur, non sérialisé, et le commentaire de `sortie/contraste.py`
 * nommait cette multiplication comme le piège à éviter. Elle avait en prime
 * un défaut que ces tests ne montraient pas : la densité étant arrondie à
 * trois décimales, la tolérance était dépassée au-delà d'environ 100 km et
 * **le chiffre disparaissait** pour qui prépare une sortie longue.
 *
 * L'API rend maintenant `feux` et `stops`. Il ne reste qu'une somme, et ce
 * qu'il faut garder est le silence sur l'inconnu, pas la justesse d'un
 * produit.
 */
describe("compteArrets", () => {
  it("additionne les deux entiers que l'API rend", () => {
    expect(compteArrets(11, 7)).toBe(18);
    expect(compteArrets(0, 0)).toBe(0);
  });

  it("ne fait plus dépendre le chiffre de la distance", () => {
    // Le cas qui effaçait le compte au-delà de 100 km : il n'existe plus,
    // parce que la distance n'entre plus dans le calcul.
    expect(compteArrets(170, 0)).toBe(170);
  });

  it("se tait quand le tracé ne porte pas de tag de nœud", () => {
    // Le cœur met les deux à `null` ensemble : l'ignorance ne s'affiche pas
    // comme un zéro (règle absolue 5).
    expect(compteArrets(null, null)).toBeNull();
    expect(compteArrets(null, 7)).toBeNull();
    expect(compteArrets(11, null)).toBeNull();
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

describe("le second temps, arrondi à 5 minutes", () => {
  it("arrondit au lieu de prétendre à la minute", () => {
    // Le cas mesuré chez le mainteneur : 4 h 39 porte à porte s'arrondit à
    // 4 h 40, un arrondi honnête plutôt qu'une fausse précision.
    expect(dureeApprox(4 * 3600 + 39 * 60)).toBe("4 h 40");
    expect(dureeApprox(2100)).toBe("35 min");
    expect(dureeApprox(7200)).toBe("2 h");
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

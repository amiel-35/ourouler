/** `api/meteoRose.ts` : l'agrégation par direction, avant tout dessin.
 *
 * Ce que ces tests protègent :
 *
 * - le cumul de pluie par direction somme **toutes** les cellules de cette
 *   direction (les deux couronnes), comme `RapportMeteo.meilleure_direction`
 *   côté cœur — pas une seule couronne ;
 * - le point « ici » n'est jamais une neuvième direction ;
 * - une direction absente de `cellules` rend `pluieMm: null`, jamais un 0
 *   (règle absolue 5) ;
 * - le désaccord se lit sur `confiance`, jamais recalculé depuis
 *   `pluie_mm`/`pluie_second_avis_mm` ;
 * - le vent vient de la cellule la plus proche (distance puis heure), et
 *   `vent_relatif` est lu tel quel — jamais reclassé face/dos/travers ici.
 */

import { describe, expect, it } from "vitest";
import { directionsDepuisCellules, niveauPluie } from "../src/api/meteoRose";
import type { Cellule } from "../src/api/types";

function cellule(morceau: Partial<Cellule> & { direction: string }): Cellule {
  return {
    distance_km: 15,
    t: "2026-09-18T07:00:00Z",
    pluie_mm: 0,
    pluie_second_avis_mm: 0,
    vent_kmh: 10,
    vent_depuis_deg: 0,
    vent_relatif: null,
    ressenti_c: 14,
    confiance: "accord",
    ...morceau,
  };
}

describe("niveauPluie", () => {
  it("classe les quatre paliers d'affichage exactement aux bornes de la légende", () => {
    expect(niveauPluie(0)).toBe("sec");
    expect(niveauPluie(0.04)).toBe("sec"); // arrondit à 0,0
    expect(niveauPluie(0.1)).toBe("faible");
    expect(niveauPluie(1.0)).toBe("faible");
    expect(niveauPluie(1.1)).toBe("modere");
    expect(niveauPluie(3.0)).toBe("modere");
    expect(niveauPluie(3.1)).toBe("fort");
    expect(niveauPluie(null)).toBe("aucune-donnee");
  });
});

describe("directionsDepuisCellules", () => {
  it("rend les huit directions, dans l'ordre fixe de la rose, quel que soit l'ordre des cellules", () => {
    const cellules = [
      cellule({ direction: "NO", pluie_mm: 0 }),
      cellule({ direction: "N", pluie_mm: 0 }),
    ];
    const directions = directionsDepuisCellules(cellules);
    expect(directions.map((d) => d.nom)).toEqual(["N", "NE", "E", "SE", "S", "SO", "O", "NO"]);
  });

  it("ignore le point « ici » — jamais une neuvième direction", () => {
    const cellules = [
      cellule({ direction: "ici", pluie_mm: 99, distance_km: 0 }),
      cellule({ direction: "N", pluie_mm: 1 }),
    ];
    const directions = directionsDepuisCellules(cellules);
    expect(directions.find((d) => (d.nom as string) === "ici")).toBeUndefined();
    expect(directions.find((d) => d.nom === "N")?.pluieMm).toBe(1);
  });

  it("cumule TOUTES les cellules d'une direction (deux couronnes), pas une seule", () => {
    const cellules = [
      cellule({ direction: "E", distance_km: 15, pluie_mm: 1.4 }),
      cellule({ direction: "E", distance_km: 25, pluie_mm: 0.7 }),
    ];
    const [direction] = directionsDepuisCellules(cellules).filter((d) => d.nom === "E");
    expect(direction.pluieMm).toBeCloseTo(2.1, 5);
    expect(direction.niveau).toBe("modere");
  });

  it("rend `pluieMm: null` pour une direction absente — jamais un 0 inventé", () => {
    const cellules = [cellule({ direction: "N", pluie_mm: 0 })];
    const directions = directionsDepuisCellules(cellules);
    const so = directions.find((d) => d.nom === "SO");
    expect(so?.pluieMm).toBeNull();
    expect(so?.niveau).toBe("aucune-donnee");
  });

  it("lit `confiance` pour le désaccord, jamais un recalcul depuis les deux pluies", () => {
    // Deux valeurs de pluie qui, comparées à la main, se ressembleraient
    // (« accord ») — mais `confiance` dit le contraire, et c'est cette
    // valeur-là qui doit gagner : le cœur a pu la calculer avec un troisième
    // facteur (l'heure, le seuil horaire) que ce module ne reproduit pas.
    const cellules = [
      cellule({ direction: "S", pluie_mm: 0.5, pluie_second_avis_mm: 0.5, confiance: "desaccord" }),
    ];
    const [direction] = directionsDepuisCellules(cellules).filter((d) => d.nom === "S");
    expect(direction.desaccord).toBe(true);
  });

  it("prend le vent de la cellule la plus proche : distance d'abord, heure ensuite", () => {
    const cellules = [
      cellule({ direction: "O", distance_km: 25, t: "2026-09-18T06:00:00Z", vent_kmh: 99, vent_relatif: "face" }),
      cellule({ direction: "O", distance_km: 15, t: "2026-09-18T08:00:00Z", vent_kmh: 11, vent_relatif: "dos" }),
      cellule({ direction: "O", distance_km: 15, t: "2026-09-18T07:00:00Z", vent_kmh: 13, vent_relatif: "travers" }),
    ];
    const [direction] = directionsDepuisCellules(cellules).filter((d) => d.nom === "O");
    // La couronne des 15 km gagne sur celle des 25 km ; à distance égale,
    // 07h gagne sur 08h.
    expect(direction.ventKmh).toBe(13);
    expect(direction.relatif).toBe("travers");
  });

  it("lit `vent_relatif` tel quel, même géométriquement invraisemblable — jamais reclassé ici", () => {
    // Nord (azimut 0°), vent annoncé depuis le nord (0°) : la règle des
    // ±45° du cœur (`meteo.rapport.vent_relatif`) donnerait « face ». La
    // cellule dit pourtant « dos » — un cas qui ne devrait pas exister en
    // vrai, mais qui prouve que ce module ne referait jamais ce calcul :
    // il ne fait que lire le champ.
    const cellules = [cellule({ direction: "N", vent_depuis_deg: 0, vent_relatif: "dos" })];
    const [direction] = directionsDepuisCellules(cellules).filter((d) => d.nom === "N");
    expect(direction.relatif).toBe("dos");
  });
});

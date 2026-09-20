/** `segmentsVent` et `portion` — colorer le tracé par le vent (point 5 du
 * lot d'affordance, 20/09/2026), en aveugle de tout rendu Leaflet.
 *
 * Coordonnées inventées, en pleine mer (golfe de Guinée) : aucune donnée
 * personnelle, aucune adresse réelle (règle absolue 1).
 */

import { describe, expect, it } from "vitest";
import { portion, segmentsVent } from "../src/ecrans/Proposition";
import type { Trace, VentPosition } from "../src/api/types";

/** Un tracé rectiligne : un point tous les 1000 m, jusqu'à `n` km. */
function traceRectiligne(km: number): Trace {
  const points: [number, number][] = [];
  const profil: [number, number][] = [];
  for (let i = 0; i <= km; i += 1) {
    points.push([0, i / 111.2]); // ~1 km par 1/111.2° de longitude, à l'équateur
    profil.push([i * 1000, 50]);
  }
  return {
    points,
    profil,
    simplification: { tolerance_m: 0, points_origine: points.length, points_rendus: points.length, ecart_max_m: 0 },
  };
}

function position(dist_m: number, relatif: string | null): VentPosition {
  return { dist_m, relatif };
}

describe("portion", () => {
  it("garde les points entre deux distances, bornes incluses", () => {
    const trace = traceRectiligne(10);
    const p = portion(trace, 2000, 5000);
    expect(p).toEqual([
      [0, 2000 / 111_200],
      [0, 3000 / 111_200],
      [0, 4000 / 111_200],
      [0, 5000 / 111_200],
    ]);
  });

  it("accepte les bornes inversées", () => {
    const trace = traceRectiligne(10);
    expect(portion(trace, 5000, 2000)).toEqual(portion(trace, 2000, 5000));
  });
});

describe("segmentsVent", () => {
  it("ne produit rien quand tout est travers ou inconnu — le tracé noir de base suffit", () => {
    const trace = traceRectiligne(5);
    const positions = [
      position(0, "travers"),
      position(1000, null),
      position(2000, "travers"),
    ];
    expect(segmentsVent(trace, positions)).toEqual([]);
  });

  it("fusionne les échantillons consécutifs de même catégorie en une seule portion", () => {
    const trace = traceRectiligne(5);
    const positions = [
      position(0, "dos"),
      position(1000, "dos"),
      position(2000, "dos"),
      position(3000, "face"),
      position(4000, "face"),
    ];
    const segments = segmentsVent(trace, positions);
    expect(segments).toHaveLength(2);
    expect(segments[0].categorie).toBe("dos");
    // La portion « dos » va jusqu'au DÉBUT de la portion suivante (3000, pas
    // 2000) : chaque segment porte la catégorie de l'échantillon qui l'ouvre
    // (relecture du 20/09/2026, voir la docstring de `segmentsVent`) — sans
    // ça, l'intervalle [2000, 3000] ne serait couvert par aucune des deux
    // portions, un trou à chaque changement de catégorie.
    expect(segments[0].points).toEqual(portion(trace, 0, 3000));
    expect(segments[1].categorie).toBe("face");
    expect(segments[1].points).toEqual(portion(trace, 3000, 4000));
  });

  it("aucun trou à un changement de catégorie : la fin d'une portion est le début de la suivante", () => {
    const trace = traceRectiligne(5);
    const positions = [
      position(0, "dos"),
      position(2000, "face"),
      position(4000, "face"),
    ];
    const segments = segmentsVent(trace, positions);
    expect(segments).toHaveLength(2);
    const finDos = segments[0].points[segments[0].points.length - 1];
    const debutFace = segments[1].points[0];
    expect(finDos).toEqual(debutFace);
  });

  it("saute le travers au milieu — deux portions dos, pas une fusionnée à tort, et rien sur le travers", () => {
    const trace = traceRectiligne(6);
    const positions = [
      position(0, "dos"),
      position(1000, "dos"),
      position(2000, "travers"),
      position(3000, "dos"),
      position(4000, "dos"),
    ];
    const segments = segmentsVent(trace, positions);
    expect(segments).toHaveLength(2);
    expect(segments.every((s) => s.categorie === "dos")).toBe(true);
    // Le segment [2000, 3000], ouvert par l'échantillon « travers », ne doit
    // apparaître dans aucune des deux portions dos.
    expect(segments[0].points).toEqual(portion(trace, 0, 2000));
    expect(segments[1].points).toEqual(portion(trace, 3000, 4000));
  });

  it("n'écarte aucun échantillon sous un seuil de sensibilité — il n'y en a pas ici", () => {
    // Contrairement à `fleches_vent`, `vent_par_position` (et donc
    // `segmentsVent`) ne connaît aucun seuil de vitesse : deux échantillons
    // suffisent à produire une portion (il en faut au moins deux : le
    // dernier échantillon d'une liste n'ouvre jamais de segment, voir la
    // docstring).
    const trace = traceRectiligne(2);
    const segments = segmentsVent(trace, [position(0, "face"), position(1000, "face")]);
    expect(segments).toHaveLength(1);
  });

  it("une portion sans point réel du tracé est écartée, jamais poussée vide", () => {
    // Deux échantillons à 500 m d'écart, sur un tracé dont les points sont
    // espacés de 1000 m (comme `trace.profil` peut l'être une fois
    // simplifié, Douglas-Peucker, cf. `boucle.geometrie`) : aucun point réel
    // ne tombe dans l'intervalle. Une portion vide mentirait à l'écran
    // (`traceColoree`) sans jamais rien dessiner (`Carte` l'aurait de toute
    // façon écartée, mais après coup).
    const trace = traceRectiligne(5);
    const segments = segmentsVent(trace, [position(500, "dos"), position(900, "dos")]);
    expect(segments).toEqual([]);
  });

  it("liste vide → aucune portion", () => {
    const trace = traceRectiligne(2);
    expect(segmentsVent(trace, [])).toEqual([]);
  });

  it("un seul échantillon → aucune portion (il n'ouvre aucun segment, rien à fusionner avec lui-même)", () => {
    const trace = traceRectiligne(2);
    expect(segmentsVent(trace, [position(0, "face")])).toEqual([]);
  });
});

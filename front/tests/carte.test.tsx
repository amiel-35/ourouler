/** Le zoom de la carte des boucles, et les étiquettes de vent qui
 * s'entassent (backlog « le zoom de la carte des boucles », constat du
 * mainteneur du 25/09/2026 — boucle de 124 km au départ de Rennes).
 *
 * Ce que ces tests protègent :
 *
 * - la carte se cadre sur les seuls points de la boucle **sélectionnée**
 *   (`trace.choisi`), pas sur l'emprise de toutes les boucles proposées ;
 * - elle se recadre quand la sélection change ;
 * - sans boucle sélectionnée, elle retombe sur l'emprise de toutes les
 *   boucles plutôt que de ne rien cadrer (garde-fou, pas un cas normal) ;
 * - `sansChevauchement` jette les étiquettes de vent trop proches à l'écran,
 *   en aveugle de tout rendu Leaflet.
 *
 * On teste l'**appel** à `fitBounds` et les bornes calculées, jamais le
 * rendu Leaflet lui-même (jsdom ne sait pas mettre une vraie carte en page) :
 * `leaflet` est donc remplacé par un double qui enregistre ce qu'on lui
 * demande de faire.
 */

import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { Carte, sansChevauchement } from "../src/composants/Carte";
import type { FlecheVent } from "../src/api/types";

// --- `sansChevauchement`, pure, sans Leaflet -----------------------------

describe("sansChevauchement", () => {
  it("garde tout quand rien ne se chevauche", () => {
    const items = [{ x: 0 }, { x: 100 }, { x: 200 }];
    expect(sansChevauchement(items, (i) => ({ x: i.x, y: 0 }), 40)).toEqual(items);
  });

  it("jette un élément trop proche du précédent gardé, garde le premier rencontré", () => {
    const items = [{ x: 0 }, { x: 10 }, { x: 100 }];
    expect(sansChevauchement(items, (i) => ({ x: i.x, y: 0 }), 40)).toEqual([
      { x: 0 },
      { x: 100 },
    ]);
  });

  it("compare à tous les éléments déjà gardés, pas seulement au précédent", () => {
    // 0 et 80 sont assez loin l'un de l'autre (seuil 40, distance 80) pour
    // être gardés tous les deux ; 45 est à 45 px de 0 (pas de chevauchement)
    // mais à 35 px de 80 (chevauchement) — il doit être jeté à cause du
    // second élément gardé, pas seulement du premier ou de son voisin dans
    // la liste.
    const items = [{ x: 0 }, { x: 80 }, { x: 45 }];
    expect(sansChevauchement(items, (i) => ({ x: i.x, y: 0 }), 40)).toEqual([
      { x: 0 },
      { x: 80 },
    ]);
  });

  it("mesure une vraie distance euclidienne, pas seulement en x", () => {
    // (0,0) et (30,30) sont à ~42 px l'un de l'autre : au-dessus du seuil de
    // 40, donc gardés tous les deux malgré des coordonnées x et y proches.
    const items = [
      { x: 0, y: 0 },
      { x: 30, y: 30 },
    ];
    expect(sansChevauchement(items, (i) => i, 40)).toEqual(items);
  });

  it("liste vide → liste vide", () => {
    expect(sansChevauchement([], (i: { x: number }) => ({ x: i.x, y: 0 }), 40)).toEqual([]);
  });
});

// --- Le cadrage de la carte (`fitBounds`), via un double de `leaflet` ----

interface CoucheFactice {
  addTo: () => CoucheFactice;
  clearLayers: () => void;
}

interface CoucheAppelable {
  bindTooltip: () => CoucheAppelable;
  addTo: () => CoucheAppelable;
}

const appelsFitBounds: unknown[][] = [];
const appelsLatLngBounds: unknown[][] = [];
const appelsMarker: unknown[][] = [];
let latLngToContainerPointImpl: (pt: [number, number]) => { x: number; y: number } = (pt) => ({
  x: pt[1] * 1000,
  y: pt[0] * 1000,
});

vi.mock("leaflet", () => {
  function coucheAppelable(): CoucheAppelable {
    const objet: CoucheAppelable = {
      bindTooltip: () => objet,
      addTo: () => objet,
    };
    return objet;
  }

  function coucheFactice(): CoucheFactice {
    const objet: CoucheFactice = {
      addTo: () => objet,
      clearLayers: () => undefined,
    };
    return objet;
  }

  const carteFactice = {
    on: vi.fn(),
    remove: vi.fn(),
    fitBounds: vi.fn((...args: unknown[]) => appelsFitBounds.push(args)),
    setView: vi.fn(),
    latLngToContainerPoint: (pt: [number, number]) => latLngToContainerPointImpl(pt),
  };

  const L = {
    map: vi.fn(() => carteFactice),
    tileLayer: vi.fn(() => coucheAppelable()),
    layerGroup: vi.fn(() => coucheFactice()),
    polyline: vi.fn(() => coucheAppelable()),
    circleMarker: vi.fn(() => coucheAppelable()),
    marker: vi.fn((...args: unknown[]) => {
      appelsMarker.push(args);
      return coucheAppelable();
    }),
    divIcon: vi.fn(() => ({})),
    latLngBounds: vi.fn((...args: unknown[]) => {
      appelsLatLngBounds.push(args);
      return args[0];
    }),
  };
  return { default: L, ...L };
});

function trace(points: [number, number][], choisi: boolean) {
  return { points, choisi };
}

describe("le cadrage de la carte", () => {
  it("se cadre sur les seuls points de la boucle sélectionnée, pas sur les trois", () => {
    appelsFitBounds.length = 0;
    appelsLatLngBounds.length = 0;
    const rennes = trace(
      [
        [48.1, -1.68],
        [48.11, -1.66],
      ],
      true,
    );
    const lointaine1 = trace(
      [
        [47.6, -2.8],
        [47.65, -2.75],
      ],
      false,
    );
    const lointaine2 = trace(
      [
        [48.6, -0.2],
        [48.65, -0.15],
      ],
      false,
    );
    render(
      <Carte
        traces={[rennes, lointaine1, lointaine2]}
        description="trois boucles au départ de Rennes"
      />,
    );
    expect(appelsLatLngBounds).toHaveLength(1);
    expect(appelsLatLngBounds[0][0]).toEqual(rennes.points);
  });

  it("se recadre quand la sélection change", () => {
    appelsFitBounds.length = 0;
    appelsLatLngBounds.length = 0;
    const boucleA = trace(
      [
        [48.1, -1.68],
        [48.11, -1.66],
      ],
      true,
    );
    const boucleB = trace(
      [
        [48.6, -0.2],
        [48.65, -0.15],
      ],
      false,
    );
    const { rerender } = render(
      <Carte traces={[boucleA, boucleB]} description="deux boucles" />,
    );
    expect(appelsLatLngBounds[appelsLatLngBounds.length - 1][0]).toEqual(boucleA.points);

    rerender(
      <Carte
        traces={[
          { ...boucleA, choisi: false },
          { ...boucleB, choisi: true },
        ]}
        description="deux boucles"
      />,
    );
    expect(appelsLatLngBounds[appelsLatLngBounds.length - 1][0]).toEqual(boucleB.points);
  });

  it("sans boucle sélectionnée, retombe sur l'emprise de toutes les boucles", () => {
    appelsFitBounds.length = 0;
    appelsLatLngBounds.length = 0;
    const boucleA = trace(
      [
        [48.1, -1.68],
        [48.11, -1.66],
      ],
      false,
    );
    const boucleB = trace(
      [
        [48.6, -0.2],
        [48.65, -0.15],
      ],
      false,
    );
    render(<Carte traces={[boucleA, boucleB]} description="deux boucles, aucune choisie" />);
    expect(appelsLatLngBounds[0][0]).toEqual([...boucleA.points, ...boucleB.points]);
  });
});

describe("les étiquettes de vent affichées sur la carte", () => {
  function fleche(pt: [number, number]): FlecheVent {
    return { pt, depuis_deg: 90, vent_kmh: 20, rafale_kmh: 30, relatif: "face" };
  }

  it("n'affiche qu'une flèche par groupe d'étiquettes qui se chevauchent", () => {
    appelsMarker.length = 0;
    // Deux points projetés à 5 px l'un de l'autre (sous le seuil de 46 px),
    // un troisième loin des deux.
    latLngToContainerPointImpl = (pt) => {
      if (pt[0] === 1) return { x: 0, y: 0 };
      if (pt[0] === 2) return { x: 5, y: 0 };
      return { x: 500, y: 0 };
    };
    const vents = [fleche([1, 0]), fleche([2, 0]), fleche([3, 0])];
    render(
      <Carte
        traces={[trace([[0, 0], [0.01, 0.01]], true)]}
        vents={vents}
        description="une boucle avec du vent"
      />,
    );
    expect(appelsMarker).toHaveLength(2);
    expect(appelsMarker.map((appel) => appel[0])).toEqual([[1, 0], [3, 0]]);
  });

  it("affiche toutes les flèches quand aucune ne se chevauche", () => {
    appelsMarker.length = 0;
    latLngToContainerPointImpl = (pt) => ({ x: pt[0] * 500, y: 0 });
    const vents = [fleche([1, 0]), fleche([2, 0]), fleche([3, 0])];
    render(
      <Carte
        traces={[trace([[0, 0], [0.01, 0.01]], true)]}
        vents={vents}
        description="une boucle avec du vent, bien espacé"
      />,
    );
    expect(appelsMarker).toHaveLength(3);
  });
});

/** « Aujourd'hui » sans Intervals — le secours dit les trois usages du dépôt.
 *
 * Constaté le 25/09/2026 : quand Intervals ne répond pas, l'écart « En
 * attendant » ne mentionnait que demander à la main ou déposer *une* séance
 * du jour, jamais qu'on peut aussi déposer ses **sorties passées** — l'autre
 * source d'historique (L9.2), disponible depuis le même bouton « Déposer »
 * (`Importer.tsx` porte les trois : le dépôt du jour, « Mes sorties
 * passées », et depuis L9.8 l'analyse d'un parcours déjà en main).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEMAINE, SYSTEME, zones } from "./fixtures";

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/": panne("intervals_refuse", "Intervals.icu : HTTP 403", 502),
    "/api/v1/seances": { charge: SEMAINE },
  });
  serveur.installer();
  return serveur;
}

describe("l'écran du jour sans Intervals", () => {
  it("dit qu'on peut aussi déposer ses sorties passées, pas seulement une séance", async () => {
    installer();
    render(<App />);

    expect(await screen.findByText("En attendant")).toBeTruthy();
    expect(
      screen.getByText(/déposer un fichier de séance, déposer vos\s+sorties passées/),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Déposer" })).toBeTruthy();
  });

  it("dit aussi qu'on peut analyser un parcours qu'on a déjà (L9.8)", async () => {
    installer();
    render(<App />);

    expect(await screen.findByText("En attendant")).toBeTruthy();
    expect(
      screen.getByText(/ou analyser un\s+parcours que vous avez déjà/),
    ).toBeTruthy();
  });
});

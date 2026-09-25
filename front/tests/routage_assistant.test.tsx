/** Un compte neuf atterrit dans l'assistant, pas sur l'écran du jour.
 *
 * Défaut constaté en vrai le 19/09/2026 (`docs/ux/parcours_accueil.md`) : un
 * compte activé mais jamais passé par l'assistant tombait sur « Aujourd'hui »,
 * qui réclame Intervals et échoue. `donnees.assistant_recommande` (vrai tant
 * qu'aucun `PATCH /profil` n'a jamais été écrit) est le signal qui corrige
 * ça — et il ne doit forcer l'assistant **qu'une seule fois** : ce que ces
 * tests protègent, c'est le premier rendu, pas un comportement qui reboucle.
 */

import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEMAINE, SYSTEME, zones } from "./fixtures";

const ZONES = zones().donnees;

function serveurDeBase(assistantRecommande: boolean) {
  const profil = { ...PROFIL, donnees: { ...PROFIL.donnees, assistant_recommande: assistantRecommande } };
  return new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil": { charge: profil },
    // Aucune séance aujourd'hui : le contrat rend `{jour, seance: null}`,
    // pas une panne (`docs/ux/api_contrat.md`) — peu importe ici, seul
    // compte l'écran sur lequel on atterrit.
    "/api/v1/seances/": { charge: { proprietaire: "essai", donnees: { jour: "2026-09-19", seance: null } } },
    "/api/v1/seances": { charge: SEMAINE },
  });
}

describe("le routage du premier écran", () => {
  it("assistant_recommande: true → l'assistant apparaît au premier rendu", async () => {
    serveurDeBase(true).installer();
    render(<App />);

    expect(await screen.findByRole("button", { name: "Commencer" })).toBeTruthy();
    // L'écran du jour, lui, ne doit pas s'être affiché en dessous.
    expect(screen.queryByText("Rien de prévu")).toBeNull();
  });

  it("assistant_recommande: false → l'onglet « Aujourd'hui » reste le défaut", async () => {
    serveurDeBase(false).installer();
    render(<App />);

    await screen.findByRole("navigation", { name: "Navigation principale" });
    expect(screen.queryByRole("button", { name: "Commencer" })).toBeNull();
    expect(screen.getByRole("button", { name: "Aujourd'hui" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });
});

describe("l'onglet demandé par l'URL", () => {
  const url = window.location.href;
  afterEach(() => {
    window.history.replaceState(null, "", url);
  });

  it("« ?onglet=reglages » ouvre directement Réglages, pas Aujourd'hui", async () => {
    window.history.replaceState(null, "", "/?onglet=reglages");
    serveurDeBase(false).installer();
    render(<App />);

    await screen.findByRole("navigation", { name: "Navigation principale" });
    expect(screen.getByRole("button", { name: "Réglages" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.queryByRole("button", { name: "Aujourd'hui" })?.getAttribute("aria-current")).not.toBe(
      "page",
    );
  });

  it("un onglet inconnu ou absent retombe sur Aujourd'hui", async () => {
    window.history.replaceState(null, "", "/?onglet=n-importe-quoi");
    serveurDeBase(false).installer();
    render(<App />);

    await screen.findByRole("navigation", { name: "Navigation principale" });
    expect(screen.getByRole("button", { name: "Aujourd'hui" }).getAttribute("aria-current")).toBe(
      "page",
    );
  });
});

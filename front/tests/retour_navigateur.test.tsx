/** Le bouton retour du navigateur ne quitte plus l'appli — fiche du 27/09/2026
 * (`docs/backlog/2026-09-27-bug-retour-navigateur-quitte-l-appli.md`).
 *
 * Ce que ces tests protègent, décision du mainteneur à l'appui : l'onglet
 * est dans l'adresse (`/?onglet=...`), les résultats (propositions, détail,
 * boucles) sont des entrées d'historique **sans adresse propre** —
 * `history.back()` y ramène au formulaire tel qu'il était, **sans
 * recalcul** ; `history.forward()` retrouve les mêmes résultats, toujours
 * sans recalcul ; un rechargement retombe sur l'onglet lu dans l'adresse ;
 * cliquer l'onglet déjà actif ne pousse aucune entrée de plus.
 *
 * Avant ce lot, aucun écran n'inscrivait quoi que ce soit dans l'historique
 * (`front/src/app/navigation.ts` ne faisait qu'un `replaceState` pour
 * `/entrer`) : un retour depuis les résultats sortait de l'appli et
 * retombait sur ce qu'il y avait avant elle dans l'onglet du navigateur.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, sortie, zones } from "./fixtures";

const AUJOURDHUI = "2026-09-16";

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/": { charge: SEANCE },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
  });
  serveur.installer();
  return serveur;
}

// Les tests qui posent l'adresse avant de rendre l'appli (rechargement
// simulé) doivent repartir de la racine pour ne pas polluer les suivants —
// même précaution que `tests/session.test.tsx`.
afterEach(() => {
  window.history.pushState({}, "", "/");
});

describe("l'onglet est dans l'adresse", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("changer d'onglet pousse une entrée d'historique vers /?onglet=...", async () => {
    installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    expect(window.location.pathname + window.location.search).toBe("/?onglet=demander");

    await utilisateur.click(screen.getByRole("button", { name: "Ma semaine" }));
    expect(window.location.pathname + window.location.search).toBe("/?onglet=semaine");
  });

  it("un rechargement sur /?onglet=demander ouvre directement l'onglet Demander", async () => {
    installer();
    window.history.pushState(null, "", "/?onglet=demander");
    render(<App />);

    // Propre à l'onglet Demander : le bouton de recherche, absent des
    // autres onglets.
    expect(await screen.findByRole("button", { name: "Chercher 3 parcours" })).toBeTruthy();
    // Et pas l'écran d'Aujourd'hui, celui du défaut sans paramètre.
    expect(screen.queryByText(/Lecture de votre séance/)).toBeNull();
  });

  it("l'onglet déjà actif ne pousse rien", async () => {
    installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await screen.findByRole("button", { name: "Demander" });

    const pousser = vi.spyOn(window.history, "pushState");
    // « Aujourd'hui » est déjà l'onglet actif au démarrage.
    await utilisateur.click(screen.getByRole("button", { name: "Aujourd'hui" }));
    expect(pousser).not.toHaveBeenCalled();
    pousser.mockRestore();
  });
});

describe("Demander → Chercher → retour/avance", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function versPropositions(
    serveur: Serveur,
    utilisateur: ReturnType<typeof userEvent.setup>,
  ) {
    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    const heureDepart = (await screen.findByLabelText("Départ à")) as HTMLInputElement;
    fireEvent.change(heureDepart, { target: { value: "07:15" } });
    expect(heureDepart.value).toBe("07:15");

    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));
    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();
    return heureDepart;
  }

  it("history.back() ramène au formulaire, rempli comme avant", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await versPropositions(serveur, utilisateur);

    window.history.back();

    const heureDepart = (await screen.findByLabelText("Départ à")) as HTMLInputElement;
    expect(heureDepart.value).toBe("07:15");
    // Le bouton de résultats a disparu : on est bien revenu au formulaire,
    // pas resté sur les propositions.
    expect(screen.queryByRole("button", { name: "Modifier la demande" })).toBeNull();
  });

  it("history.forward() retrouve les mêmes résultats, sans nouvel appel réseau", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await versPropositions(serveur, utilisateur);

    window.history.back();
    await screen.findByLabelText("Départ à");

    // `forward()` seul : ce qu'il déclenche, et rien de ce que `back()`
    // avait déjà déclenché (le formulaire remonté peut relire le vent au
    // départ, ce n'est pas ce que ce test garde).
    const appelsAvantAvance = serveur.requetes.length;

    window.history.forward();
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();

    // Aucun appel — ni `POST /sorties` ni quoi que ce soit d'autre : les
    // résultats retrouvés sont ceux déjà en mémoire, pas un recalcul.
    expect(serveur.requetes.length).toBe(appelsAvantAvance);
  });

  it("« Modifier la demande » et le retour navigateur mènent au même état, sans double entrée", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await versPropositions(serveur, utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Modifier la demande" }));

    const heureDepart = (await screen.findByLabelText("Départ à")) as HTMLInputElement;
    expect(heureDepart.value).toBe("07:15");

    // Un seul pas d'avance suffit à retrouver les résultats : « Modifier la
    // demande » a dépilé l'historique, il ne l'a pas empilé une seconde
    // fois par-dessus.
    window.history.forward();
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();
  });
});

/** Le bouton retour du navigateur ne quitte plus l'appli — fiche du 27/09/2026
 * (`docs/backlog/2026-09-27-bug-retour-navigateur-quitte-l-appli.md`), et
 * relecture indépendante du même jour.
 *
 * Ce que ces tests protègent, décision du mainteneur à l'appui : l'onglet
 * est dans l'adresse (`/?onglet=...`), les résultats (propositions, détail,
 * boucles) sont des entrées d'historique **sans adresse propre** —
 * `history.back()` y ramène au formulaire tel qu'il était, **sans
 * recalcul** ; `history.forward()` retrouve les mêmes résultats, toujours
 * sans recalcul ; un rechargement retombe sur l'onglet lu dans l'adresse ;
 * cliquer l'onglet déjà actif ne pousse aucune entrée de plus.
 *
 * Relecture : « Chercher plus loin » remplace l'entrée de résultats plutôt
 * que d'en empiler une seconde ; un `popstate` à l'état étranger retombe sur
 * l'onglet lu dans l'adresse, jamais sur un onglet invalide ; un retour
 * pendant un calcul est ignoré, et un `popstate` referme l'écran d'échec de
 * calcul ; l'assistant, le dépôt et l'analyse deviennent aussi des étapes
 * d'historique ; « Modifier la demande » mène toujours au formulaire
 * Demander rempli, même rouvert depuis Aujourd'hui ou Ma semaine.
 *
 * Avant ce lot, aucun écran n'inscrivait quoi que ce soit dans l'historique
 * (`front/src/app/navigation.ts` ne faisait qu'un `replaceState` pour
 * `/entrer`) : un retour depuis les résultats sortait de l'appli et
 * retombait sur ce qu'il y avait avant elle dans l'onglet du navigateur.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, boucle, sortie, zones } from "./fixtures";

const AUJOURDHUI = "2026-09-16";

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/": { charge: SEANCE },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
    "/api/v1/boucles": { charge: boucle() },
  });
  serveur.installer();
  return serveur;
}

describe("l'onglet est dans l'adresse", () => {
  beforeEachHorloge();

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

  it("changer d'onglet puis revenir en arrière retombe sur l'onglet précédent", async () => {
    installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(screen.getByRole("button", { name: "Ma semaine" }));
    expect(screen.getByRole("button", { name: "Ma semaine" }).getAttribute("aria-current")).toBe("page");

    window.history.back();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Demander" }).getAttribute("aria-current")).toBe("page"),
    );
    expect(window.location.pathname + window.location.search).toBe("/?onglet=demander");
  });

  it("un popstate à l'état étranger retombe sur l'onglet lu dans l'adresse, jamais sur un onglet invalide", async () => {
    installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));

    // L'adresse change sans passer par le code de l'appli (une entrée
    // étrangère, ou posée par une version antérieure), puis un `popstate`
    // dont l'état ne porte pas d'onglet connu (`{}`, puis `null`) : la
    // solution relit l'onglet dans l'adresse plutôt que de le garder tel
    // quel ou de casser sur un onglet invalide.
    window.history.replaceState(null, "", "/?onglet=semaine");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ma semaine" }).getAttribute("aria-current")).toBe("page"),
    );

    window.history.replaceState(null, "", "/?onglet=reglages");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Réglages" }).getAttribute("aria-current")).toBe("page"),
    );
  });
});

describe("Demander → Chercher → retour/avance", () => {
  beforeEachHorloge();

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

  it("détail d'une proposition → retour → liste des propositions", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await versPropositions(serveur, utilisateur);
    const cartes = screen
      .getAllByRole("button")
      .filter((bouton) => bouton.className.includes("carte-bouton"));
    expect(cartes.length).toBeGreaterThan(0);
    await utilisateur.click(cartes[0]);

    expect(await screen.findByRole("button", { name: "Revenir aux propositions" })).toBeTruthy();

    window.history.back();

    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Revenir aux propositions" })).toBeNull();
  });

  it("Boucles (Endurance Z2) : « Modifier la demande » ramène au formulaire rempli", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(screen.getByRole("button", { name: "Endurance Z2" }));
    const heureDepart = (await screen.findByLabelText("Départ à")) as HTMLInputElement;
    fireEvent.change(heureDepart, { target: { value: "11:30" } });

    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));
    await waitFor(() => expect(serveur.vers("/api/v1/boucles").length).toBe(1));
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();

    await utilisateur.click(screen.getByRole("button", { name: "Modifier la demande" }));

    const heureApres = (await screen.findByLabelText("Départ à")) as HTMLInputElement;
    expect(heureApres.value).toBe("11:30");
  });

  it("« Chercher plus loin » remplace l'entrée de résultats plutôt que d'en empiler une seconde", async () => {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
      // Une seule proposition : c'est ce qui affiche « Chercher plus loin ».
      "/api/v1/sorties": { charge: sortie({ propositions: 1 }) },
    });
    serveur.installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await versPropositions(serveur, utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher plus loin" }));
    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(2));
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();

    // Un seul retour suffit à quitter les résultats vers le formulaire,
    // malgré la seconde recherche : l'entrée n'a pas été empilée deux fois.
    window.history.back();
    expect(await screen.findByLabelText("Départ à")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Modifier la demande" })).toBeNull();
  });

  it("un retour pendant un calcul est ignoré : l'écran d'attente reste affiché jusqu'à la fin", async () => {
    let resoudre: () => void = () => undefined;
    const enAttente = new Promise<{ charge: unknown }>((resolve) => {
      resoudre = () => resolve({ charge: sortie() });
    });
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
      "/api/v1/sorties": () => enAttente,
    });
    serveur.installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));
    await screen.findByRole("heading", { name: "On cherche" });

    window.history.back();
    // Laisse le temps à un `popstate` (mal filtré) de se propager avant de
    // vérifier que rien n'a bougé.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByRole("heading", { name: "On cherche" })).toBeTruthy();

    resoudre();
    expect(await screen.findByRole("button", { name: "Modifier la demande" })).toBeTruthy();
  });

  it("un popstate referme l'écran d'échec de calcul et redessine l'écran de l'entrée visée", async () => {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
      "/api/v1/sorties": panne("panne_inventee", "un message d'essai", 500),
    });
    serveur.installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));
    expect(await screen.findByRole("heading", { name: "Ça n'a pas marché" })).toBeTruthy();

    // Le calcul n'a rien poussé sur l'historique (il a échoué) : l'entrée
    // courante reste celle de l'onglet Demander, poussée au clic sur
    // l'onglet ; un retour dépile jusqu'à l'entrée d'avant, Aujourd'hui.
    window.history.back();

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Ça n'a pas marché" })).toBeNull(),
    );
    expect(screen.getByRole("button", { name: "Aujourd'hui" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("l'assistant, le dépôt et l'analyse deviennent des étapes d'historique", () => {
  it("un retour depuis l'assistant forcé à un nouvel invité ramène à l'onglet, pas hors de l'appli", async () => {
    const profilNeuf = { ...PROFIL, donnees: { ...PROFIL.donnees, assistant_recommande: true } };
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: profilNeuf },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
    });
    serveur.installer();
    render(<App />);

    // L'assistant s'ouvre de force (compte neuf) — son premier écran.
    expect(await screen.findByRole("button", { name: "Commencer" })).toBeTruthy();

    window.history.back();

    // Retombe sur l'onglet Aujourd'hui (le défaut), pas une page blanche ni
    // une sortie de l'application : l'assistant a bien posé une entrée
    // d'historique à son ouverture forcée.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Commencer" })).toBeNull());
    expect(screen.getByRole("button", { name: "Aujourd'hui" }).getAttribute("aria-current")).toBe("page");
  });
});

/** L'horloge figée sur le jour de `SEANCE`/`SEMAINE`, posée et remise en
 * place dans un `describe` — factorisé, plusieurs blocs en ont besoin. */
function beforeEachHorloge() {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });
}

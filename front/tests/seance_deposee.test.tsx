/** Une séance déposée est une prescription **pour un jour** — relecture F2 · B1.
 *
 * Le défaut que ces tests empêchent de revenir, dans les mots de la relecture :
 * « il dépose un `.ZWO` mardi parce qu'Intervals était muet. Mercredi,
 * Intervals a retrouvé la voix […]. Il appuie sur "Chercher le parcours du
 * jour" : le parcours est calculé **sur les blocs de mardi**. […] Il part
 * rouler avec le mauvais entraînement placé sur la bonne route, et l'interface
 * a l'air d'accord avec lui. »
 *
 * C'est le seul défaut du lot qui puisse envoyer quelqu'un s'entraîner de
 * travers, et il ne se voit qu'au retour, sur des données qu'on ne refait pas.
 *
 * **L'invariant gardé ici n'est pas « le fichier est remis à `null` »** — ça,
 * c'est un symptôme, et le remettre à `null` à la fin de la génération
 * casserait le cas légitime de la seconde recherche pour le même jour. C'est :
 * *une séance déposée ne part qu'avec une recherche pour son propre jour*.
 * Q38 tranche que le fichier est « une séance à faire », et
 * `POST /seances/fichier` prend déjà ce jour-là : le front ne l'honorait pas.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App, fichierPourLaRecherche } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, sortie, zones } from "./fixtures";

const AUJOURDHUI = "2026-09-16";
const AUTRE_JOUR = "2026-09-21";
const IDENTIFIANT = "fichier-invente-0001";

describe("la règle, nommée", () => {
  it("joint le fichier à une recherche pour son propre jour", () => {
    const deposee = { identifiant: IDENTIFIANT, jour: AUJOURDHUI, nom: "Déposée" };
    expect(fichierPourLaRecherche(deposee, AUJOURDHUI)).toBe(IDENTIFIANT);
  });

  it("ne le joint pas à une recherche pour un autre jour", () => {
    const deposee = { identifiant: IDENTIFIANT, jour: AUJOURDHUI, nom: "Déposée" };
    expect(fichierPourLaRecherche(deposee, AUTRE_JOUR)).toBeUndefined();
  });

  it("ne joint rien quand rien n'a été déposé", () => {
    expect(fichierPourLaRecherche(null, AUJOURDHUI)).toBeUndefined();
  });
});

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/fichier": {
      charge: { ...SEANCE, fichier: { id: IDENTIFIANT, nom: "seance.zwo" } },
    },
    // Intervals n'a rien pour aujourd'hui : c'est ce qui donne au cycliste
    // une raison de déposer un fichier, et c'est le début du scénario de B1.
    // La forme est celle du contrat — 200 avec `donnees.seance` à `null`,
    // « pas de séance ce jour-là » n'étant pas une panne.
    "/api/v1/seances/": {
      charge: { ...SEANCE, donnees: { jour: AUJOURDHUI, seance: null } },
    },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
  });
  serveur.installer();
  return serveur;
}

/** Dépose un fichier de séance pour le jour courant, depuis « Aujourd'hui ». */
async function deposerPourAujourdhui(utilisateur: ReturnType<typeof userEvent.setup>) {
  await utilisateur.click(await screen.findByRole("button", { name: "Déposer une séance" }));
  const champ = (await screen.findByLabelText("Fichier de séance")) as HTMLInputElement;
  // Un `.ZWO` minimal et entièrement inventé : le serveur factice rend la
  // séance de fixture quoi qu'il arrive, le contenu ne sert qu'au dépôt.
  const fichier = new File(["<workout_file></workout_file>"], "seance.zwo", {
    type: "application/xml",
  });
  await utilisateur.upload(champ, fichier);
  await screen.findByText("Chercher un parcours");
}

/** Le corps du dernier `POST /sorties` reçu. */
function derniereRecherche(serveur: Serveur): Record<string, unknown> {
  const envois = serveur.vers("/api/v1/sorties");
  expect(envois.length, "aucune recherche n'a été envoyée").toBeGreaterThan(0);
  return envois[envois.length - 1].corps as Record<string, unknown>;
}

describe("le fichier déposé et les recherches suivantes", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("part avec la recherche du jour pour lequel il a été déposé", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await deposerPourAujourdhui(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Chercher un parcours" }));

    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    const corps = derniereRecherche(serveur);
    expect(corps.jour).toBe(AUJOURDHUI);
    expect(corps.fichier_seance).toBe(IDENTIFIANT);
  });

  /** **Le cas de B1.** C'est celui qui envoyait rouler sur les blocs d'hier. */
  it("ne part PAS avec la recherche d'un autre jour", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await deposerPourAujourdhui(utilisateur);

    // Retour aux onglets, puis « Ma semaine » : générer le parcours d'un
    // autre jour — exactement le geste de la relecture.
    await utilisateur.click(screen.getByRole("button", { name: "Ma semaine" }));
    const blocs = await screen.findAllByRole("button", { name: "Générer le parcours" });
    // Le dernier bloc de la semaine de fixture est le 21, pas aujourd'hui.
    await utilisateur.click(blocs[blocs.length - 1]);

    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    const corps = derniereRecherche(serveur);
    expect(corps.jour).toBe(AUTRE_JOUR);
    expect(
      corps.fichier_seance,
      "la séance déposée pour aujourd'hui s'est replacée sur un autre jour : " +
        "le cycliste partirait faire les mauvais blocs",
    ).toBeUndefined();
  });

  it("se voit à l'écran tant qu'il est en usage, et se retire", async () => {
    installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);
    await deposerPourAujourdhui(utilisateur);

    // Le second défaut de B1 : « aucun écran ne dit qu'un fichier est en
    // usage ». Il le dit maintenant, et sur tous les écrans.
    expect(await screen.findByText(/Séance déposée/)).toBeTruthy();

    await utilisateur.click(screen.getByRole("button", { name: "Retirer ce fichier" }));
    await waitFor(() => expect(screen.queryByText(/Séance déposée/)).toBeNull());
  });
});

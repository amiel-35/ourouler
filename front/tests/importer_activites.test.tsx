/** « Mes sorties passées » — L9.2, dépôt de l'historique sans Intervals.icu.
 *
 * Distinct du dépôt de séance (voir `seance_deposee.test.tsx`) : celui-ci
 * n'indexe rien « pour aujourd'hui », il alimente le cache d'activités du
 * propriétaire — routes déjà connues, et plus tard le niveau du cycliste.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, sortie, zones } from "./fixtures";

function installer(routeImport: Record<string, unknown> = {}) {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/fichier": { charge: SEANCE },
    "/api/v1/seances/": { charge: { ...SEANCE, donnees: { jour: "2026-09-16", seance: null } } },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
    "/api/v1/activites/import": (requete) =>
      requete.methode === "GET"
        ? { charge: { donnees: { nombre: 0, premiere: null, derniere: null } } }
        : (routeImport.reponse ??
          {
            charge: {
              donnees: { importees: 1, doublons: 0, ignorees: [] },
            },
          }),
    ...routeImport,
  });
  serveur.installer();
  return serveur;
}

async function ouvrirLecranDeDepot(utilisateur: ReturnType<typeof userEvent.setup>) {
  render(<App />);
  await utilisateur.click(await screen.findByRole("button", { name: "Déposer une séance" }));
  await screen.findByText("Mes sorties passées");
}

describe("Mes sorties passées", () => {
  it("montre l'état déjà déposé au chargement", async () => {
    installer({
      "/api/v1/activites/import": (requete: { methode: string }) =>
        requete.methode === "GET"
          ? { charge: { donnees: { nombre: 12, premiere: "2024-01-05", derniere: "2024-06-10" } } }
          : { charge: { donnees: { importees: 1, doublons: 0, ignorees: [] } } },
    });
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);
    expect(await screen.findByText(/Déjà 12 sorties déposées/)).toBeTruthy();
  });

  it("dépose un fichier et affiche le rapport d'import", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);

    const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
    const fichier = new File(["<gpx></gpx>"], "sortie.gpx", { type: "application/gpx+xml" });
    await utilisateur.upload(champ, fichier);

    await screen.findByText("1 sortie importée");
    const envois = serveur.vers("/api/v1/activites/import").filter((r) => r.methode === "POST");
    expect(envois).toHaveLength(1);
  });

  it("dépose plusieurs fichiers en un seul appel", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);

    const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
    const fichiers = [
      new File(["<gpx></gpx>"], "un.gpx", { type: "application/gpx+xml" }),
      new File(["<gpx></gpx>"], "deux.gpx", { type: "application/gpx+xml" }),
    ];
    await utilisateur.upload(champ, fichiers);

    await screen.findByText("1 sortie importée");
    const envois = serveur.vers("/api/v1/activites/import").filter((r) => r.methode === "POST");
    expect(envois).toHaveLength(1);
  });

  it("montre les motifs d'une archive dont une partie a été ignorée", async () => {
    installer({
      "/api/v1/activites/import": (requete: { methode: string }) =>
        requete.methode === "GET"
          ? { charge: { donnees: { nombre: 0, premiere: null, derniere: null } } }
          : {
              charge: {
                donnees: {
                  importees: 2,
                  doublons: 1,
                  ignorees: [
                    { motif: "extension non prise en charge — média, .csv, .json… hors liste", nombre: 3, exemples: [] },
                  ],
                },
              },
            },
    });
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);
    const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
    await utilisateur.upload(champ, new File(["PK"], "export.zip", { type: "application/zip" }));

    await screen.findByText("2 sorties importées");
    expect(await screen.findByText(/déjà connue, non dupliquée/)).toBeTruthy();
    expect(await screen.findByText(/3 ignorés — extension non prise en charge/)).toBeTruthy();
  });

  it("affiche un écran d'échec sans casser l'écran quand l'import est refusé", async () => {
    installer({
      "/api/v1/activites/import": (requete: { methode: string }) =>
        requete.methode === "GET"
          ? { charge: { donnees: { nombre: 0, premiere: null, derniere: null } } }
          : panne("fichier_trop_gros", "trop gros pour être lu", 413),
    });
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);
    const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
    await utilisateur.upload(champ, new File(["x"], "gros.fit", { type: "application/octet-stream" }));

    expect(await screen.findByText(/trop gros pour être lu/)).toBeTruthy();
    // L'écran de dépôt de séance, lui, reste utilisable : l'échec de l'un
    // n'emporte pas l'autre.
    expect(screen.getByRole("button", { name: "Choisir un fichier" })).toBeTruthy();
  });
});

/** « Mes sorties passées » — L9.2, dépôt de l'historique sans Intervals.icu.
 *
 * Distinct du dépôt de séance (voir `seance_deposee.test.tsx`) : celui-ci
 * n'indexe rien « pour aujourd'hui », il alimente le cache d'activités du
 * propriétaire — routes déjà connues, et plus tard le niveau du cycliste.
 *
 * **L'import tourne en tâche de fond côté serveur** (relecture du
 * 25/09/2026, suite) : `POST` rend un `JobImport` (202, toujours « en_cours »
 * — le serveur vient de lancer le thread), l'écran interroge
 * `GET /activites/import/{id}` jusqu'à ce qu'il ne soit plus « en_cours ».
 * Le faux serveur répond « fini » dès la première interrogation par défaut
 * (un seul cycle réel de `DELAI_INTERROGATION_MS`) ; un test dédié le fait
 * répondre en deux temps pour vérifier l'état intermédiaire.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, sortie, zones } from "./fixtures";

const ID_JOB = "job-essai-0001";

/**
 * `POST` répond toujours « en_cours » (c'est le vrai contrat : le serveur
 * vient de lancer le thread, il n'a pas encore fini) — mais `GET .../import/{id}`
 * répond « fini » **dès son premier appel** par défaut. Chaque dépôt de test
 * attend donc une seule vraie interrogation (`DELAI_INTERROGATION_MS`, 1,5 s)
 * avant de voir le rapport, jamais deux : les tests qui déposent un fichier
 * donnent une marge généreuse pour cette seule attente. Un seul test, dédié,
 * vérifie l'état intermédiaire « en_cours » avant le rapport final.
 */
function installer(routeSuivi: Record<string, unknown> = {}) {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/fichier": { charge: SEANCE },
    "/api/v1/seances/": { charge: { ...SEANCE, donnees: { jour: "2026-09-16", seance: null } } },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
    // **L'ordre compte** : `Serveur.installer` trouve la première clé dont le
    // chemin reçu est préfixé (`chemin.startsWith(motif)`), et
    // `/api/v1/activites/import` est un préfixe de
    // `/api/v1/activites/import/{id}` — la route la plus spécifique doit
    // donc être déclarée **avant** la générique, sans quoi `GET .../import/{id}`
    // serait pris pour `GET .../import` (l'état du dépôt, une tout autre forme).
    [`/api/v1/activites/import/${ID_JOB}`]: _jobFini({ importees: 1, doublons: 0, ignorees: [] }),
    "/api/v1/activites/import": (requete: { methode: string }) =>
      requete.methode === "GET"
        ? { charge: { donnees: { nombre: 0, premiere: null, derniere: null } } }
        : {
            statut: 202,
            charge: {
              donnees: { id: ID_JOB, statut: "en_cours", traites: 0, total: 0, rapport: null, erreur: null },
            },
          },
    ...routeSuivi,
  });
  serveur.installer();
  return serveur;
}

function _jobFini(rapport: unknown) {
  return {
    charge: {
      donnees: { id: ID_JOB, statut: "fini", traites: 1, total: 1, rapport, erreur: null },
    },
  };
}

/** Un `GET .../import/{id}` qui répond « en_cours » une fois, puis « fini ». */
function _suiviEnDeuxTemps(rapport: unknown) {
  let appels = 0;
  return () => {
    appels += 1;
    if (appels === 1) {
      return {
        charge: {
          donnees: { id: ID_JOB, statut: "en_cours", traites: 1, total: 2, rapport: null, erreur: null },
        },
      };
    }
    return {
      charge: {
        donnees: { id: ID_JOB, statut: "fini", traites: 2, total: 2, rapport, erreur: null },
      },
    };
  };
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
          : {
              statut: 202,
              charge: { donnees: { id: ID_JOB, statut: "en_cours", traites: 0, total: 0, rapport: null, erreur: null } },
            },
    });
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);
    expect(await screen.findByText(/Déjà 12 sorties déposées/)).toBeTruthy();
  });

  it(
    "dépose un fichier, montre l'avancement, puis le rapport final",
    async () => {
      const serveur = installer({
        [`/api/v1/activites/import/${ID_JOB}`]: _suiviEnDeuxTemps({
          importees: 1,
          doublons: 0,
          ignorees: [],
        }),
      });
      const utilisateur = userEvent.setup();
      await ouvrirLecranDeDepot(utilisateur);

      const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
      const fichier = new File(["<gpx></gpx>"], "sortie.gpx", { type: "application/gpx+xml" });
      await utilisateur.upload(champ, fichier);

      // Premier temps : l'import est en cours, une barre l'annonce.
      expect(await screen.findByRole("progressbar")).toBeTruthy();
      expect(await screen.findByText(/Import en cours/)).toBeTruthy();

      // Second temps, après la prochaine interrogation (véritable minuterie
      // de 1,5 s, `DELAI_INTERROGATION_MS`) : le rapport final. Marge large
      // — le seul test du fichier qui dépend du minutage réel plutôt que
      // d'une réponse immédiate.
      await screen.findByText("1 sortie importée", {}, { timeout: 8000 });
      expect(screen.queryByRole("progressbar")).toBeNull();

      const envois = serveur.vers("/api/v1/activites/import").filter((r) => r.methode === "POST");
      expect(envois).toHaveLength(1);
    },
    15_000,
  );

  it(
    "dépose plusieurs fichiers en un seul appel",
    async () => {
      const serveur = installer();
      const utilisateur = userEvent.setup();
      await ouvrirLecranDeDepot(utilisateur);

      const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
      const fichiers = [
        new File(["<gpx></gpx>"], "un.gpx", { type: "application/gpx+xml" }),
        new File(["<gpx></gpx>"], "deux.gpx", { type: "application/gpx+xml" }),
      ];
      await utilisateur.upload(champ, fichiers);

      await screen.findByText("1 sortie importée", {}, { timeout: 8000 });
      const envois = serveur.vers("/api/v1/activites/import").filter((r) => r.methode === "POST");
      expect(envois).toHaveLength(1);
    },
    15_000,
  );

  it(
    "montre les motifs d'une archive dont une partie a été ignorée",
    async () => {
      installer({
        [`/api/v1/activites/import/${ID_JOB}`]: _jobFini({
          importees: 2,
          doublons: 1,
          ignorees: [
            {
              motif: "extension non prise en charge — média, .csv, .json… hors liste",
              nombre: 3,
              exemples: [],
            },
          ],
        }),
      });
      const utilisateur = userEvent.setup();
      await ouvrirLecranDeDepot(utilisateur);
      const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
      await utilisateur.upload(champ, new File(["PK"], "export.zip", { type: "application/zip" }));

      await screen.findByText("2 sorties importées", {}, { timeout: 8000 });
      expect(await screen.findByText(/déjà connue, non dupliquée/)).toBeTruthy();
      expect(await screen.findByText(/3 ignorés — extension non prise en charge/)).toBeTruthy();
    },
    15_000,
  );

  it("affiche un écran d'échec sans casser l'écran quand le dépôt est refusé", async () => {
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

    // Refusé sur le dépôt lui-même (413) : pas de job, pas d'attente —
    // ce cas-ci n'a jamais rien à interroger, il reste rapide.
    expect(await screen.findByText(/trop gros pour être lu/)).toBeTruthy();
    // L'écran de dépôt de séance, lui, reste utilisable : l'échec de l'un
    // n'emporte pas l'autre.
    expect(screen.getByRole("button", { name: "Choisir un fichier" })).toBeTruthy();
  });

  it(
    "affiche l'échec d'un import qui a tourné puis cassé côté serveur",
    async () => {
      installer({
        [`/api/v1/activites/import/${ID_JOB}`]: () => ({
          charge: {
            donnees: {
              id: ID_JOB,
              statut: "echoue",
              traites: 1,
              total: 2,
              rapport: null,
              erreur: "index corrompu",
            },
          },
        }),
      });
      const utilisateur = userEvent.setup();
      await ouvrirLecranDeDepot(utilisateur);
      const champ = (await screen.findByLabelText("Historique de sorties")) as HTMLInputElement;
      await utilisateur.upload(champ, new File(["PK"], "export.zip", { type: "application/zip" }));

      expect(
        await screen.findByText(/n'a pas pu aller au bout : index corrompu/, {}, { timeout: 8000 }),
      ).toBeTruthy();
    },
    15_000,
  );

  it("reprend le suivi d'un import après un rechargement de la page", async () => {
    window.localStorage.setItem("ourouler.import.job", ID_JOB);
    installer();
    const utilisateur = userEvent.setup();
    await ouvrirLecranDeDepot(utilisateur);

    // Sans avoir rien déposé cette fois-ci : l'écran retrouve le job tout
    // seul, depuis l'identifiant laissé par la « session » précédente.
    await waitFor(() => expect(screen.getByText("1 sortie importée")).toBeTruthy());
    window.localStorage.removeItem("ourouler.import.job");
  });
});

/** L9.8 — le troisième usage de « Déposer » : analyser un parcours déjà en main.
 *
 * L'écran `Importer.tsx` propose désormais trois usages (constat du
 * mainteneur, 25/09/2026) : une séance à faire (existant), les sorties
 * passées (existant), et un parcours à analyser (nouveau). Ce test vérifie
 * seulement le fil de navigation et le dépôt du GPX — le calcul lui-même
 * (météo, fourchette) est éprouvé côté cœur, sans réseau
 * (`tests/test_physique_analyser.py`, `tests/test_api.py`).
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, sortie, zones } from "./fixtures";

const APERCU = { nom: "Imposé du club", distance_km: 42.0, denivele_m: 310 };

const ANALYSE = {
  donnees: {
    nom: APERCU.nom,
    distance_km: APERCU.distance_km,
    denivele_m: APERCU.denivele_m,
    velo: "Route",
    puissance_w: 165,
    depart: "2026-09-20T08:00:00+00:00",
    temps_estime_s: 6300,
    vitesse_moy_kmh: 24.0,
    temps_ecoule_s: 6800,
    temps_ecoule_bas_s: 6600,
    temps_ecoule_haut_s: 7100,
    temps_ecoule_source: "defaut",
    heure_arrivee: "2026-09-20T09:53:20+00:00",
    heure_arrivee_bas: "2026-09-20T09:50:00+00:00",
    heure_arrivee_haut: "2026-09-20T10:01:40+00:00",
    meteo_absente: null,
    meteo: {
      pluie_cumulee_mm: 0.0,
      minutes_pluie: 0.0,
      part_vent_face: 0.2,
      part_vent_dos: 0.3,
      n_vent_connu: 8,
      n_echantillons: 8,
      ressenti_min_c: 12.0,
      confiance: "haute",
      modele_utilise: "meteofrance_arome_france_hd",
      repli: false,
      bascule_dist_m: null,
      fleches_vent: [],
      echantillons: [],
    },
    trace: {
      points: [
        [0.0, 0.0],
        [0.001, 0.001],
      ],
      profil: [
        [0, 100],
        [1000, 110],
      ],
      simplification: { tolerance_m: 5.0, points_origine: 2, points_rendus: 2, ecart_max_m: 0.0 },
    },
  },
  avertissements: [],
  duree_ms: 42,
  budget: { operation: "analyse", attendu_ms: 5000, source: "defaut", n: 0, median_ms: null },
};

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/fichier": { charge: SEANCE },
    "/api/v1/seances/": { charge: { ...SEANCE, donnees: { jour: "2026-09-16", seance: null } } },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/sorties": { charge: sortie() },
    "/api/v1/parcours/fichier": {
      charge: { fichier: { id: "gpx-essai-0001", nom: "imposé.gpx" }, apercu: APERCU },
    },
    "/api/v1/parcours/analyser": { charge: ANALYSE },
  });
  serveur.installer();
  return serveur;
}

describe("analyser un parcours déjà en main (L9.8)", () => {
  it("propose le troisième usage depuis « Déposer », dépose le GPX et rend la durée", async () => {
    installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Déposer une séance" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Analyser un parcours" }));

    const champ = (await screen.findByLabelText("Parcours à analyser")) as HTMLInputElement;
    const fichier = new File(["<gpx></gpx>"], "imposé.gpx", { type: "application/gpx+xml" });
    await utilisateur.upload(champ, fichier);

    expect(await screen.findByText(APERCU.nom)).toBeTruthy();

    const champHeure = (await screen.findByLabelText(/Heure de départ/)) as HTMLInputElement;
    await utilisateur.type(champHeure, "2026-09-20T08:00");
    await utilisateur.click(await screen.findByRole("button", { name: "Analyser" }));

    // La fourchette porte à porte (L9.1) : deux occurrences du mot légitimes
    // (l'intro de l'écran, puis le résultat) — on vise la fourchette elle-même.
    await waitFor(async () => {
      expect(await screen.findByText(/entre 1 h 50 et 1 h 58/)).toBeTruthy();
    });
    expect(screen.getByText(/165 W/)).toBeTruthy();
  });
});

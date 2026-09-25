/** La calibration sur la fiche vélo (L9.4, 25/09/2026).
 *
 * Ce que ces tests gardent :
 *
 * 1. le résultat se dit en mots simples — puissance à 30 km/h, écart sur des
 *    sorties jamais vues, fourchette du porte à porte, nombre de sorties — et
 *    le CdA/Crr n'apparaît que dans le détail replié ;
 * 2. « Calibrer sur mes sorties » lance `POST /calibrations`, suit
 *    l'avancement, puis relit l'état ;
 * 3. sans pneu, l'écran propose de le choisir ou de calibrer quand même
 *    (`sans_pneu: true`) ;
 * 4. trop peu de sorties : l'écran dit combien il y en a et combien il en
 *    faut, et ne propose pas de bouton ;
 * 5. un refus du serveur est affiché tel quel.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Reglages } from "../src/ecrans/Reglages";
import { panne, Serveur } from "./serveur";
import type { Table } from "./serveur";
import { PROFIL, zones } from "./fixtures";
import type {
  EtatCalibrations,
  EtatCalibrationVelo,
  JobCalibration,
  ResumeCalibration,
} from "../src/api/types";

const ZONES = zones().donnees;
const VELO = PROFIL.donnees.velos[0].nom;

const RESUME: ResumeCalibration = {
  velo: VELO,
  date: "2026-09-25",
  provenance: "mesure",
  puissance_repere_w: 188,
  vitesse_repere_kmh: 30,
  n_sorties: 27,
  n_validation: 25,
  erreur_validation: 0.035,
  biais_validation: -0.008,
  porte_a_porte: { bas: 1.021, mediane: 1.035, haut: 1.099, n: 25, provenance: "mesure" },
  crr_source: "pneu",
  pneu: "course_quatre_saisons",
  alerte: null,
  detail: { cda_m2: 0.378, crr: 0.006, masse_totale_kg: 100.3 },
};

function velo(morceau: Partial<EtatCalibrationVelo> = {}): EtatCalibrationVelo {
  return {
    velo: VELO,
    calibration: null,
    sorties_disponibles: 40,
    sorties_ecartees: {},
    pneu: "course_quatre_saisons",
    crr_connu: true,
    crr_usage: 0.005,
    tache: null,
    ...morceau,
  };
}

function etat(v: EtatCalibrationVelo, morceau: Partial<EtatCalibrations> = {}): EtatCalibrations {
  return { sorties_necessaires: 10, ftp_renseignee: true, velos: [v], ...morceau };
}

function job(morceau: Partial<JobCalibration> = {}): JobCalibration {
  return {
    id: "j1",
    statut: "en_cours",
    traites: 3,
    total: 40,
    etape: "lecture",
    nature: "calibration",
    sujet: VELO,
    rapport: null,
    erreur: null,
    ...morceau,
  };
}

function rendre(table: Table) {
  const serveur = new Serveur({
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil": { charge: { proprietaire: "essai", donnees: PROFIL.donnees } },
    ...table,
  });
  serveur.installer();
  render(
    <Reglages
      profil={PROFIL.donnees}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surRefaireInstallation={() => undefined}
      surDeconnexion={() => undefined}
    />,
  );
  return serveur;
}

function enveloppe(donnees: unknown) {
  return { charge: { proprietaire: "essai", donnees } };
}

describe("la calibration sur la fiche vélo", () => {
  it("dit le résultat en mots simples, et garde CdA/Crr dans le détail replié", async () => {
    rendre({ "/api/v1/calibrations": enveloppe(etat(velo({ calibration: RESUME }))) });
    const bloc = await screen.findByLabelText(`Calibration de ${VELO}`);
    expect(within(bloc).getByText(/il vous faut/).textContent).toContain("188 W");
    expect(bloc.textContent).toContain("3,5 %");
    expect(bloc.textContent).toMatch(/\+2\s%\sà\s\+10\s%/); // espaces insécables
    expect(bloc.textContent).toContain("mesuré sur 25 de vos sorties");
    expect(bloc.textContent).toContain("Mesuré sur 27 sorties");
    // CdA et Crr : seulement dans le `<details>`, jamais au premier plan.
    const detail = bloc.querySelector("details")!;
    expect(detail.textContent).toContain("CdA");
    const horsDetail = bloc.textContent!.replace(detail.textContent!, "");
    expect(horsDetail).not.toMatch(/CdA|Crr/);
    expect(within(bloc).getByRole("button", { name: "Recalibrer sur mes sorties" })).toBeTruthy();
    // Et la ligne du vélo porte la provenance.
    await waitFor(() =>
      expect(screen.getByText(/modèle mesuré sur vos sorties/)).toBeTruthy(),
    );
  });

  it("lance la calibration, montre l'avancement, puis relit l'état", async () => {
    let suivis = 0;
    let fini = false;
    const serveur = rendre({
      "/api/v1/calibrations/j1": () => {
        suivis += 1;
        fini = true;
        return enveloppe(
          job({ statut: "fini", traites: 1, total: 1, etape: "ajustement", rapport: {
            calibration: RESUME, sorties_lues: 40, sorties_apprentissage: 27, sorties_groupe: 3,
            archives_meteo_manquantes: 0, repli: null,
          } }),
        );
      },
      "/api/v1/calibrations": (requete) =>
        requete.methode === "POST"
          ? { statut: 202, ...enveloppe(job()) }
          : enveloppe(etat(velo(fini ? { calibration: RESUME } : {}))),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Calibrer sur mes sorties" }));
    const post = serveur.requetes.find((r) => r.methode === "POST")!;
    expect(post.corps).toEqual({ velo: VELO, sans_pneu: false });
    expect((await screen.findByRole("status")).textContent).toContain("Lecture de vos sorties");
    await waitFor(() => expect(suivis).toBeGreaterThan(0), { timeout: 4000 });
    await waitFor(() => expect(screen.getByText(/il vous faut/)).toBeTruthy(), { timeout: 4000 });
  });

  it("sans pneu, propose de le choisir ou de calibrer quand même", async () => {
    const serveur = rendre({
      "/api/v1/calibrations": (requete) =>
        requete.methode === "POST"
          ? { statut: 202, ...enveloppe(job()) }
          : enveloppe(etat(velo({ pneu: null, crr_connu: false }))),
    });
    expect(await screen.findByRole("button", { name: "Choisir mes pneus" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Calibrer sur mes sorties" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Calibrer quand même" }));
    const post = serveur.requetes.find((r) => r.methode === "POST")!;
    expect(post.corps).toEqual({ velo: VELO, sans_pneu: true });
  });

  it("« Choisir mes pneus » ouvre la liste des vélos", async () => {
    rendre({
      "/api/v1/calibrations": enveloppe(etat(velo({ pneu: null, crr_connu: false }))),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Choisir mes pneus" }));
    expect(await screen.findByLabelText("Pneus")).toBeTruthy();
  });

  it("trop peu de sorties : dit combien il y en a et combien il en faut, sans bouton", async () => {
    rendre({
      "/api/v1/calibrations": enveloppe(
        etat(velo({ sorties_disponibles: 3, sorties_ecartees: { "vélo non identifié": 12 } })),
      ),
    });
    const bloc = await screen.findByLabelText(`Calibration de ${VELO}`);
    expect(bloc.textContent).toContain("3 sorties exploitables sur ce vélo, il en faut au moins 10");
    expect(bloc.textContent).toContain("12 sorties ne disent pas sur quel vélo");
    expect(within(bloc).queryByRole("button")).toBeNull();
  });

  it("sans FTP, dit de la renseigner d'abord", async () => {
    rendre({
      "/api/v1/calibrations": enveloppe(etat(velo(), { ftp_renseignee: false })),
    });
    const bloc = await screen.findByLabelText(`Calibration de ${VELO}`);
    expect(bloc.textContent).toContain("Renseignez d'abord votre FTP");
    expect(within(bloc).queryByRole("button")).toBeNull();
  });

  it("reprend l'avancement d'une calibration en cours après un rechargement", async () => {
    rendre({
      "/api/v1/calibrations/j1": enveloppe(job({ etape: "meteo", traites: 12, total: 40 })),
      "/api/v1/calibrations": enveloppe(etat(velo({ tache: job({ etape: "meteo", traites: 12 }) }))),
    });
    const statut = await screen.findByRole("status");
    expect(statut.textContent).toContain("Vent de chaque jour de sortie — 12 / 40");
    expect(screen.queryByRole("button", { name: "Calibrer sur mes sorties" })).toBeNull();
  });

  it("affiche le refus du serveur tel quel", async () => {
    rendre({
      "/api/v1/calibrations": (requete) =>
        requete.methode === "POST"
          ? panne("tache_lourde_en_cours", "un import d'historique tourne déjà sur ce serveur", 409)
          : enveloppe(etat(velo())),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Calibrer sur mes sorties" }));
    expect(await screen.findByText("un import d'historique tourne déjà sur ce serveur")).toBeTruthy();
  });

  it("une calibration échouée le dit", async () => {
    rendre({
      "/api/v1/calibrations": enveloppe(
        etat(velo({ tache: job({ statut: "echoue", erreur: "aucune des 12 sorties n'est relisible" }) })),
      ),
    });
    expect(
      await screen.findByText(/La calibration n'a pas abouti : aucune des 12 sorties/),
    ).toBeTruthy();
  });
});

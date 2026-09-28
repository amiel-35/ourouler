/** Le bandeau « Départ par défaut » de l'onglet Demander.
 *
 * Fiche `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md` : un
 * compte hébergé sans départ calculait depuis (0, 0), sans qu'aucun écran ne
 * le dise. `Sortie.depart_par_defaut`/`Boucle.depart_par_defaut` porte
 * maintenant l'information, et le bandeau doit apparaître quand il est vrai,
 * disparaître quand il est faux — les deux comptent autant l'un que l'autre
 * (même exigence que `elargissement.test.tsx`).
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Boucles } from "../src/ecrans/Boucles";
import { Demander, demandeInitiale } from "../src/ecrans/Demander";
import { Propositions } from "../src/ecrans/Propositions";
import { RangeesDepartVelos } from "../src/ecrans/reglages/Rangees";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, boucle, sortie, ventDepart, zones } from "./fixtures";

const ZONES = zones().donnees;

describe("Propositions (onglet Demander → sortie)", () => {
  function afficher(departParDefaut: boolean) {
    const reponse = sortie({ departParDefaut });
    reponse.donnees.demande.lieu_depart = { ...reponse.donnees.demande.lieu_depart, nom: "Paris" };
    render(
      <Propositions
        reponse={reponse}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surElargir={() => undefined}
        surRetour={() => undefined}
      />,
    );
  }

  it("affiche le bandeau et son lien vers Réglages quand le départ est le défaut", () => {
    afficher(true);
    expect(screen.getByText(/Départ par défaut : Paris/)).toBeTruthy();
    const lien = screen.getByRole("link", { name: "Renseignez le vôtre dans Réglages" });
    expect(lien.getAttribute("href")).toBe("/?onglet=reglages");
  });

  it("n'affiche rien quand le départ est celui du cycliste", () => {
    afficher(false);
    expect(screen.queryByText(/Départ par défaut/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Renseignez le vôtre dans Réglages" })).toBeNull();
  });
});

describe("Boucles (onglet Demander → boucle libre)", () => {
  function afficher(departParDefaut: boolean) {
    const reponse = boucle({ departParDefaut });
    reponse.donnees.depart = { ...reponse.donnees.depart, nom: "Paris" };
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);
  }

  it("affiche le bandeau quand le départ est le défaut", () => {
    afficher(true);
    expect(screen.getByText(/Départ par défaut : Paris/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Renseignez le vôtre dans Réglages" })).toBeTruthy();
  });

  it("n'affiche rien quand le départ est celui du cycliste", () => {
    afficher(false);
    expect(screen.queryByText(/Départ par défaut/)).toBeNull();
  });
});

describe("Demander (formulaire, avant même de chercher)", () => {
  function profilAvec(parDefaut: boolean) {
    return { ...PROFIL.donnees, depart: { ...PROFIL.donnees.depart, nom: "Paris", par_defaut: parDefaut } };
  }

  function afficher(parDefaut: boolean) {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    render(
      <Demander
        profil={profilAvec(parDefaut)}
        zones={ZONES}
        dureeSeance_s={SEANCE.donnees.duree_s}
        nomSeance={SEANCE.donnees.nom}
        demande={demandeInitiale()}
        budget={null}
        surDemande={() => undefined}
        surChercher={() => undefined}
      />,
    );
    return serveur;
  }

  it("affiche le bandeau quand le profil n'a pas de départ renseigné", async () => {
    const serveur = afficher(true);
    expect(screen.getByText(/Départ par défaut : Paris/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Renseignez le vôtre dans Réglages" })).toBeTruthy();
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));
  });

  it("n'affiche rien quand le départ est celui du cycliste", async () => {
    const serveur = afficher(false);
    expect(screen.queryByText(/Départ par défaut/)).toBeNull();
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));
  });
});

describe("Réglages → Départ habituel", () => {
  function afficher(parDefaut: boolean) {
    render(
      <RangeesDepartVelos
        profil={{ ...PROFIL.donnees, depart: { ...PROFIL.donnees.depart, nom: "Paris", par_defaut: parDefaut } }}
        calibrations={null}
        volet={null}
        basculer={() => undefined}
      />,
    );
  }

  it("dit « (par défaut) », sans lien — le bouton ouvre déjà le volet qui le corrige", () => {
    afficher(true);
    expect(screen.getByText("Paris (par défaut)")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("ne dit rien de plus quand le départ est celui du cycliste", () => {
    afficher(false);
    expect(screen.getByText("Paris")).toBeTruthy();
    expect(screen.queryByText(/par défaut/)).toBeNull();
  });
});

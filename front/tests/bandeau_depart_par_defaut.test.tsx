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
import { render, screen } from "@testing-library/react";
import { Boucles } from "../src/ecrans/Boucles";
import { Propositions } from "../src/ecrans/Propositions";
import { boucle, sortie } from "./fixtures";

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

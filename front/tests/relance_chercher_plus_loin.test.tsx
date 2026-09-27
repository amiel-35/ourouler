/** Sprint 11 — « Trois boucles retenues d'office » (QP4, 25/09/2026).
 *
 * Le serveur relance désormais lui-même la recherche avec plus de
 * candidates avant de répondre (`services/sortie.py`) ; le bouton
 * « Chercher plus loin » ne reste qu'un filet, pour les cas où même la
 * relance n'a pas suffi. Sa condition d'affichage passe donc de
 * `sortie.propositions.length === 1` à « moins de trois propositions ».
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Propositions } from "../src/ecrans/Propositions";
import { sortie } from "./fixtures";

function afficher(nbPropositions: number) {
  render(
    <Propositions
      reponse={sortie({ propositions: nbPropositions })}
      choisie={1}
      surChoix={() => {}}
      surOuvrir={() => {}}
      surElargir={() => {}}
      surRetour={() => {}}
    />,
  );
}

describe("le bouton « Chercher plus loin », après la relance d'office côté serveur", () => {
  it("reste affiché quand la relance n'a retenu qu'une seule boucle", () => {
    afficher(1);
    expect(screen.getByRole("button", { name: "Chercher plus loin" })).toBeTruthy();
  });

  it("reste affiché quand la relance n'a retenu que deux boucles", () => {
    afficher(2);
    expect(screen.getByRole("button", { name: "Chercher plus loin" })).toBeTruthy();
  });

  it("disparaît dès que trois boucles sont retenues", () => {
    afficher(3);
    expect(screen.queryByRole("button", { name: "Chercher plus loin" })).toBeNull();
  });

  it("ne s'affiche pas sans `surElargir`, même à une seule proposition", () => {
    render(
      <Propositions
        reponse={sortie({ propositions: 1 })}
        choisie={1}
        surChoix={() => {}}
        surOuvrir={() => {}}
        surRetour={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "Chercher plus loin" })).toBeNull();
  });
});

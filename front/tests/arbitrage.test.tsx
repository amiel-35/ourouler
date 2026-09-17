/** Lot F2.4 — voir ce que le produit a jeté, et pourquoi.
 *
 * Le défaut d'origine, dans les mots du mainteneur : « je veux visuellement
 * voir le souci ». Il trouve ses défauts en regardant des cartes — il en a
 * trouvé six en une nuit de cette façon, dont aucune n'était visible dans
 * 4 273 tests verts. Le jugement du produit lui était pourtant invisible.
 *
 * Quatre exigences, et la dernière compte autant que les trois autres :
 *
 * 1. chaque candidate apparaît avec son sort ;
 * 2. une écartée dit **le pourcentage et contre laquelle** ;
 * 3. son **tracé** se dessine, parce qu'un azimut ne se regarde pas ;
 * 4. **l'écran nominal ne bouge pas** tant qu'on n'a pas ouvert le panneau.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Propositions } from "../src/ecrans/Propositions";
import { titreArbitrage } from "../src/composants/Arbitrage";
import type { Ecartee } from "../src/api/types";
import { sortie } from "./fixtures";

function afficher(options?: Parameters<typeof sortie>[0]) {
  return render(
    <Propositions
      reponse={sortie(options)}
      choisie={1}
      surChoix={() => {}}
      surOuvrir={() => {}}
      surRetour={() => {}}
    />,
  );
}

function ouvrir() {
  const bascule = screen.getByText(/candidates écartées|ont toutes été retenues/);
  fireEvent.click(bascule);
  // jsdom n'ouvre pas un <details> sur le clic du <summary> : on pose l'état
  // et on laisse React recevoir l'événement `toggle`, comme le navigateur.
  const panneau = bascule.closest("details") as HTMLDetailsElement;
  panneau.open = true;
  fireEvent(panneau, new Event("toggle", { bubbles: false }));
  return panneau;
}

describe("l'écran nominal", () => {
  it("ne montre qu'une ligne repliée, pas la matrice", () => {
    const { container } = afficher();
    const panneau = container.querySelector("details.arbitrage") as HTMLDetailsElement;
    expect(panneau).toBeTruthy();
    expect(panneau.open).toBe(false);
  });

  it("dit d'un mot ce qu'il y a derrière, plutôt que « détails »", () => {
    // Zéro écartée se dit aussi : le silence laisserait croire que
    // l'arbitrage n'a pas eu lieu.
    expect(titreArbitrage(sortie().donnees.arbitrage!)).toMatch(/ont toutes été retenues/);
    expect(titreArbitrage(sortie({ ecarteeAuContraste: true }).donnees.arbitrage!)).toMatch(
      /Voir les 1 candidates écartées/,
    );
  });
});

describe("le panneau ouvert", () => {
  it("donne un sort à chaque candidate, retenue comprise", () => {
    afficher({ ecarteeAuContraste: true });
    ouvrir();
    // Trois retenues et une écartée : la quatrième cesse d'être invisible.
    expect(screen.getAllByText("Retenue")).toHaveLength(3);
    expect(screen.getAllByText("Écartée")).toHaveLength(1);
  });

  it("dit pourquoi dans les termes qui décident — le pourcentage et la boucle", () => {
    afficher({ ecarteeAuContraste: true });
    ouvrir();
    // La phrase vient du cœur. Le front ne la reformule pas et ne recalcule
    // surtout pas ce 55 % (doctrine §10.2).
    expect(
      screen.getByText(/55% des mêmes routes que la n° 1, au-dessus du seuil de 30%/),
    ).toBeTruthy();
  });

  it("montre la paire fautive dans la matrice, et elle seule", () => {
    const { container } = afficher({ ecarteeAuContraste: true });
    ouvrir();
    const rouges = container.querySelectorAll("td.case-au-dessus");
    // La matrice est symétrique : une paire au-dessus du seuil, deux cases.
    expect(rouges).toHaveLength(2);
    expect([...rouges].every((c) => c.textContent?.includes("55"))).toBe(true);
  });

  it("dit, chiffres du cœur à l'appui, qu'une seule paire suffit à tout casser", () => {
    afficher({ ecarteeAuContraste: true });
    ouvrir();
    expect(screen.getByText(/une seule paire trop ressemblante/)).toBeTruthy();
  });

  it("pose les tracés des écartées sur la carte, et le dit à qui ne la voit pas", () => {
    const { container } = afficher({ ecarteeAuContraste: true });
    const carte = () => container.querySelector(".carte") as HTMLElement;
    expect(carte().getAttribute("aria-label")).not.toMatch(/écartée/);
    ouvrir();
    expect(carte().getAttribute("aria-label")).toMatch(/1 écartée\(s\)/);
  });
});

describe("les candidates tombées avant le contraste", () => {
  const avant: Ecartee[] = [
    {
      azimut_deg: 180,
      distance_km: 8.2,
      motif: "−83 % de la distance demandée (motif inventé)",
      etape: "distance",
      trace: null,
    },
  ];

  it("se distinguent des écartées du contraste, et disent qu'il n'y a rien à dessiner", () => {
    afficher({ ecarteesAvant: avant });
    ouvrir();
    expect(screen.getByText(/1 candidate\(s\) tombée\(s\) avant le contraste/)).toBeTruthy();
    expect(screen.getByText(/−83 % de la distance demandée/)).toBeTruthy();
    // Règle absolue 5 : une boucle jamais construite n'a pas de tracé, et on
    // n'en invente pas un vide.
    expect(screen.getByText(/la boucle n'a jamais été construite/)).toBeTruthy();
  });

  it("n'ajoutent aucun tracé à la carte quand elles n'en ont pas", () => {
    const { container } = afficher({ ecarteesAvant: avant });
    ouvrir();
    expect(
      (container.querySelector(".carte") as HTMLElement).getAttribute("aria-label"),
    ).not.toMatch(/écartée/);
  });
});

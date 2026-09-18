/** Le second temps de sortie — porte à porte, arrêts compris (18/09/2026).
 *
 * Le défaut mesuré chez le mainteneur : une sortie demandée pour 5 h
 * affichait « 3 h 57 ». Le chiffre n'était pas faux — c'est le temps de
 * **mouvement** du modèle physique, qui ignore les arrêts par construction
 * — mais seul, il se lisait comme une durée totale.
 *
 * Décision du mainteneur, mot pour mot : « plus que corriger faudrait
 * donner les 2 valeurs et une explication ; la durée en mouvement en
 * majeur et un truc qui dit s'il y avait pas d'arrêts etc. »
 *
 * Trois cas gardés ici, sur les trois écrans qui affichent une durée
 * (`Boucles`, `Propositions`, `Proposition`) :
 *
 * 1. les deux chiffres sont présents, le majeur porte le mot qui dit quelle
 *    horloge c'est, le second est arrondi et expliqué ;
 * 2. `compteur: null` (aucun vélo enregistré) : aucun second chiffre du
 *    tout, pas même un tiret ;
 * 3. `facteur_provenance: "suppose"` : l'écran le dit, avec la formulation
 *    déjà posée par `EcranFtp.tsx` pour ne pas en inventer une seconde.
 */

import { describe, expect, it } from "vitest";
import { render, screen, type RenderResult } from "@testing-library/react";
import { Boucles } from "../src/ecrans/Boucles";
import { Propositions } from "../src/ecrans/Propositions";
import { PropositionDetail } from "../src/ecrans/Proposition";
import { SEANCE, boucle, sortie } from "./fixtures";

function texte(vue: RenderResult): string {
  return vue.container.textContent ?? "";
}

describe("les boucles libres (Boucles.tsx)", () => {
  it("montrent le temps de mouvement, marqué, et le porte à porte en second", () => {
    const vue = render(<Boucles reponse={boucle()} surRetour={() => undefined} />);
    // Le majeur : le temps du modèle (temps_estime_s = 5460 s), avec le mot
    // qui dit quelle horloge c'est — il ne peut plus rester nu.
    expect(texte(vue)).toMatch(/1\s*h\s*31\s*en roulant/);
    // Le second, arrondi à 5 minutes et introduit par « ≈ » : ce n'est pas
    // une mesure à la minute.
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*45\s*porte à porte/);
  });

  it("explique les deux chiffres dans un dépliant, sans rien affirmer au hasard", () => {
    const vue = render(<Boucles reponse={boucle()} surRetour={() => undefined} />);
    expect(screen.getByText("D'où viennent ces deux chiffres")).toBeTruthy();
    // La simulation de cette boucle-ci, sans arrêt.
    expect(texte(vue)).toMatch(/simulation de cette boucle-ci/);
    // La moyenne compteur habituelle, avec sa valeur.
    expect(texte(vue)).toMatch(/24,6\s*km\/h/);
    // Le fait qui referme la boucle : la même moyenne a choisi la distance.
    expect(texte(vue)).toMatch(/a servi à choisir la distance/);
  });

  it("n'affiche aucun second chiffre, pas même un tiret, sans vélo enregistré", () => {
    const vue = render(<Boucles reponse={boucle({ compteur: null })} surRetour={() => undefined} />);
    expect(screen.queryByText(/porte à porte/)).toBeNull();
    expect(screen.queryByText("D'où viennent ces deux chiffres")).toBeNull();
    expect(vue.container.querySelector(".temps-ecoule")).toBeNull();
    // Le majeur reste là, seul : c'est la configuration qui manque, pas le
    // temps de mouvement.
    expect(texte(vue)).toMatch(/1\s*h\s*31\s*en roulant/);
  });

  it("dit que le facteur est supposé quand il ne vient pas d'une mesure", () => {
    render(<Boucles reponse={boucle({ compteur: "suppose" })} surRetour={() => undefined} />);
    // Formulation reprise telle quelle d'`EcranFtp.tsx` (décision 8, règle
    // absolue 5) : pas de seconde formulation inventée pour le même fait.
    expect(screen.getByText("supposé — il n'a pas été mesuré sur vos sorties")).toBeTruthy();
  });

  it("dit que le facteur est mesuré quand il l'est, sans dire qu'il est supposé", () => {
    render(<Boucles reponse={boucle({ compteur: "mesure" })} surRetour={() => undefined} />);
    expect(screen.queryByText(/supposé/)).toBeNull();
  });

  it("dit que la moyenne habituelle ne s'applique plus sur une boucle trop vallonnée", () => {
    render(
      <Boucles reponse={boucle({ arretsPlancher: true })} surRetour={() => undefined} />,
    );
    expect(screen.getByText(/assez vallonnée pour que votre moyenne habituelle/)).toBeTruthy();
  });
});

describe("la liste des propositions (Propositions.tsx)", () => {
  function afficher(options?: Parameters<typeof sortie>[0]) {
    return render(
      <Propositions
        reponse={sortie(options)}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surRetour={() => undefined}
      />,
    );
  }

  it("portent les deux chiffres sur chaque carte", () => {
    const vue = afficher();
    expect(texte(vue)).toMatch(/1\s*h\s*15\s*en roulant/);
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*20\s*porte à porte/);
  });

  it("n'affichent aucun second chiffre sans vélo enregistré", () => {
    const vue = afficher({ compteur: null });
    expect(screen.queryByText(/porte à porte/)).toBeNull();
    expect(vue.container.querySelector(".temps-ecoule")).toBeNull();
    // Le majeur, lui, reste affiché.
    expect(texte(vue)).toMatch(/1\s*h\s*15\s*en roulant/);
  });

  it("disent que le facteur est supposé quand il ne vient pas d'une mesure", () => {
    afficher({ compteur: "suppose" });
    // Une carte par proposition, donc une mention par carte : c'est le même
    // fait dit autant de fois qu'il y a de chiffres à expliquer.
    expect(screen.getAllByText("supposé — il n'a pas été mesuré sur vos sorties").length).toBeGreaterThan(0);
  });
});

describe("le détail d'une proposition (Proposition.tsx)", () => {
  function afficher(options?: Parameters<typeof sortie>[0]) {
    return render(
      <PropositionDetail
        reponse={sortie(options)}
        numero={1}
        seance={SEANCE.donnees}
        surRetour={() => undefined}
      />,
    );
  }

  it("porte les deux chiffres, le majeur marqué et le second expliqué", () => {
    const vue = afficher();
    expect(texte(vue)).toMatch(/1\s*h\s*15\s*en roulant/);
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*20\s*porte à porte/);
    expect(screen.getByText("D'où viennent ces deux chiffres")).toBeTruthy();
  });

  it("n'affiche aucun second chiffre sans vélo enregistré", () => {
    const vue = afficher({ compteur: null });
    expect(screen.queryByText(/porte à porte/)).toBeNull();
    expect(vue.container.querySelector(".temps-ecoule")).toBeNull();
  });

  it("dit que le facteur est supposé quand il ne vient pas d'une mesure", () => {
    afficher({ compteur: "suppose" });
    expect(screen.getByText("supposé — il n'a pas été mesuré sur vos sorties")).toBeTruthy();
  });
});

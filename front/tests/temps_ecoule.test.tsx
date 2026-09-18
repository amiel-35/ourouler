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

/**
 * L'index, parmi les enfants directs de `.chiffres`, du premier dont le
 * texte correspond à `motif` — ou -1.
 *
 * **Pourquoi pas la distance entre les deux chiffres de durée eux-mêmes**
 * (version précédente de ce test, retirée en relecture le 18/09/2026) :
 * `DureesDeSortie` (`composants/TempsEcoule.tsx`) rend son majeur et son
 * second chiffre dans un même fragment JSX. Ses deux `<span>` sont donc
 * toujours frères immédiats l'un de l'autre **quel que soit l'endroit où le
 * composant est placé** dans la ligne — mesurer leur écart mesure une
 * constante du composant, pas la position du bloc dans l'écran. La preuve
 * en relecture : ce test passait encore sur `Proposition.tsx` avec
 * `<DureesDeSortie>` remis à sa position fautive du 17/09 (après le D+, les
 * feux, le trafic et les routes non classées).
 *
 * Ce qui doit vraiment être mesuré est la position du **bloc de durées**
 * par rapport aux autres chiffres — c'est ce que fait `indexChiffre`, appelé
 * une fois pour le bloc de durées et une fois pour ce qui l'entourait avant
 * le correctif.
 */
function indexChiffre(conteneur: HTMLElement, motif: RegExp): number {
  const enfants = [...conteneur.querySelectorAll(".chiffres > *")];
  return enfants.findIndex((n) => motif.test(n.textContent ?? ""));
}

const DUREE = /porte à porte|en roulant/;

describe("les boucles libres (Boucles.tsx)", () => {
  it("montrent le porte à porte en majeur, et le temps sans arrêt en second", () => {
    const vue = render(<Boucles reponse={boucle()} surRetour={() => undefined} />);
    // Le majeur : le temps du modèle (temps_estime_s = 5460 s), avec le mot
    // qui dit quelle horloge c'est — il ne peut plus rester nu.
    expect(texte(vue)).toMatch(/1\s*h\s*31\s*sans un seul arrêt/);
    // Le second, arrondi à 5 minutes et introduit par « ≈ » : ce n'est pas
    // une mesure à la minute.
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*45\s*porte à porte/);
  });

  it("place le bloc de durées juste après le D+, avant la météo et les routes", () => {
    // Défaut signalé le 18/09/2026 : « 3 h 57 en roulant » ouvrait la ligne,
    // « ≈ 4 h 40 porte à porte » arrivait après le D+, la pluie, le vent et
    // les trois lignes de types de routes — l'œil ne les rapprochait plus.
    const vue = render(<Boucles reponse={boucle()} surRetour={() => undefined} />);
    const iDPlus = indexChiffre(vue.container, /m D\+/);
    const iDuree = indexChiffre(vue.container, DUREE);
    const iPluie = indexChiffre(vue.container, /mm de pluie/);
    const iCalme = indexChiffre(vue.container, /km de petites routes/);
    expect(iDPlus).toBeGreaterThanOrEqual(0);
    expect(iPluie).toBeGreaterThan(iDPlus);
    expect(iCalme).toBeGreaterThan(iDPlus);
    // Immédiatement après le D+ — pas seulement quelque part avant la météo.
    expect(iDuree).toBe(iDPlus + 1);
    expect(iDuree).toBeLessThan(iPluie);
    expect(iDuree).toBeLessThan(iCalme);
  });

  it("explique les deux chiffres dans un dépliant, sans rien affirmer au hasard", () => {
    const vue = render(<Boucles reponse={boucle()} surRetour={() => undefined} />);
    expect(screen.getByText("D'où viennent ces deux chiffres")).toBeTruthy();
    // La simulation de ce tracé-ci, sans arrêt — et le fait, dit en toutes
    // lettres, que c'est le seul des deux qui tienne compte du relief.
    expect(texte(vue)).toMatch(/simulation de ce tracé-ci/);
    expect(texte(vue)).toMatch(/seul des deux qui tienne compte du relief/);
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
    // Le temps de mouvement reste là, seul, et reprend son nom : c'est la
    // configuration qui manque, pas le chiffre.
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
    expect(texte(vue)).toMatch(/1\s*h\s*15\s*sans un seul arrêt/);
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*20\s*porte à porte/);
  });

  it("place le bloc de durées juste après le kilométrage, avant le D+", () => {
    // Construction différente des deux autres écrans : `chiffresDe` pousse
    // les deux chiffres de durée juste après le kilométrage, dans le même
    // tableau que le D+ — ici l'adjacence est garantie par l'ordre des
    // `push`, pas par un fragment JSX, donc un chiffre qui s'intercalerait
    // ferait vraiment échouer ce test.
    const vue = afficher();
    const iKm = indexChiffre(vue.container, /^\d[\d,]*\s*km$/);
    const iDuree = indexChiffre(vue.container, DUREE);
    const iDPlus = indexChiffre(vue.container, /m D\+/);
    expect(iKm).toBeGreaterThanOrEqual(0);
    expect(iDuree).toBe(iKm + 1);
    expect(iDPlus).toBeGreaterThan(iDuree);
  });

  it("n'affichent aucun second chiffre sans vélo enregistré", () => {
    const vue = afficher({ compteur: null });
    expect(screen.queryByText(/porte à porte/)).toBeNull();
    expect(vue.container.querySelector(".temps-ecoule")).toBeNull();
    // Le temps de mouvement reste affiché, et reprend son nom.
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

  it("porte le porte à porte en majeur, et le temps sans arrêt en second", () => {
    const vue = afficher();
    expect(texte(vue)).toMatch(/1\s*h\s*15\s*sans un seul arrêt/);
    expect(texte(vue)).toMatch(/≈\s*1\s*h\s*20\s*porte à porte/);
    expect(screen.getByText("D'où viennent ces deux chiffres")).toBeTruthy();
  });

  it("place le bloc de durées juste après le D+, avant feux, trafic et routes non classées", () => {
    // C'était ici, sur le détail d'une proposition, que le D+, les feux et
    // stops, le trafic et les routes non classées s'intercalaient entre les
    // deux chiffres : `Boucles.tsx` et `Propositions.tsx` avaient déjà été
    // corrigés le même jour, pas cet écran-ci.
    const vue = afficher();
    const iDPlus = indexChiffre(vue.container, /m D\+/);
    const iDuree = indexChiffre(vue.container, DUREE);
    const iFeux = indexChiffre(vue.container, /feux et stops/);
    const iTrafic = indexChiffre(vue.container, /sur routes passantes/);
    expect(iDPlus).toBeGreaterThanOrEqual(0);
    expect(iFeux).toBeGreaterThan(iDPlus);
    expect(iTrafic).toBeGreaterThan(iDPlus);
    expect(iDuree).toBe(iDPlus + 1);
    expect(iDuree).toBeLessThan(iFeux);
    expect(iDuree).toBeLessThan(iTrafic);
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

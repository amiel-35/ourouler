/** L'écart de distance cesse d'être tu (Q41 d).
 *
 * Le défaut que ces tests gardent est celui que le mainteneur a trouvé en
 * utilisant le produit : « j'ai demandé 6 h et j'ai 3 boucles de 5 h ». Le
 * moteur servait la boucle la plus proche, hors tolérance, **sans un mot**.
 *
 * Deux exigences symétriques, et la seconde compte autant que la première :
 * l'écart s'affiche quand il existe, et **rien ne s'affiche quand il
 * n'existe pas**. Un bandeau qui signale ce qui ne compte pas apprend à ne
 * plus lire le bandeau — c'est déjà la raison d'être de `SEUIL_ECART_DUREE`
 * côté cœur.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErreurApi } from "../src/api/client";
import { Echec, mesuresDistance } from "../src/composants/Echec";
import { signe } from "../src/composants/Elargissement";
import { Propositions } from "../src/ecrans/Propositions";
import { sortie } from "./fixtures";

function afficher(horsTolerance: boolean) {
  render(
    <Propositions
      reponse={sortie({ horsTolerance })}
      choisie={1}
      surChoix={() => {}}
      surOuvrir={() => {}}
      surElargir={() => {}}
      surRetour={() => {}}
    />,
  );
}

describe("une boucle servie hors tolérance", () => {
  it("dit de combien la tolérance a été élargie, et dans quel sens", () => {
    afficher(true);
    // Le chiffre du palier, pas une formule d'excuse.
    expect(screen.getByText(/Aucune boucle à ±10\s*%/)).toBeTruthy();
    expect(screen.getByText(/On a élargi de 10\s*%, soit ±20\s*%/)).toBeTruthy();
    // Et le signe : plus court que demandé ne se vit pas comme plus long.
    expect(screen.getByText(/Parcours 1 : 34\.0 km, −18\s*%/)).toBeTruthy();
  });

  it("ne dit rien du tout quand les boucles tiennent dans la tolérance", () => {
    afficher(false);
    expect(screen.queryByText(/Aucune boucle à ±/)).toBeNull();
    expect(screen.queryByText(/On a élargi/)).toBeNull();
  });
});

describe("le signe de l'écart", () => {
  it("distingue une boucle trop courte d'une boucle trop longue", () => {
    expect(signe(-0.177)).toMatch(/^−18/);
    expect(signe(0.177)).toMatch(/^\+18/);
  });
});

describe("E18 · échec, quand même l'élargissement n'a pas suffi", () => {
  const refus = new ErreurApi(
    {
      code: "aucune_boucle",
      message: "aucune boucle à moins de 10 % de 150 km",
      service: null,
      details: {
        motif: "distance_inatteignable",
        distance_cible_km: 150,
        distance_obtenue_km: 96.4,
        ecart_relatif: -0.3573,
        tolerance_distance: 0.1,
        elargissement_requis: 0.3,
        elargissement_max: 0.1,
      },
    },
    422,
  );

  it("porte les chiffres du refus au lieu d'un « réessayez »", () => {
    render(<Echec erreur={refus} contexte="Un contexte inventé" />);
    expect(screen.getByText(/96\.4 km pour 150 km demandés/)).toBeTruthy();
    expect(screen.getByText(/−36\s*%/)).toBeTruthy();
    expect(screen.getByText(/élargir de 30\s*%/)).toBeTruthy();
    expect(screen.getByText(/on s'arrête à 10\s*%/)).toBeTruthy();
  });

  it("reste lisible si l'API n'envoie pas les mesures", () => {
    const nu = new ErreurApi(
      { code: "aucune_boucle", message: "aucune boucle", service: null, details: {} },
      422,
    );
    expect(mesuresDistance(nu)).toBeNull();
    render(<Echec erreur={nu} contexte="Un contexte inventé" />);
    // L'écran existe toujours, sans bloc à trous.
    expect(screen.getByRole("heading", { name: "Aucune boucle" })).toBeTruthy();
    expect(screen.queryByText(/Ce qu'on a trouvé de plus proche/)).toBeNull();
  });

  it("refuse un détail mal typé plutôt que d'afficher NaN", () => {
    const abime = new ErreurApi(
      {
        code: "aucune_boucle",
        message: "aucune boucle",
        service: null,
        details: { motif: "distance_inatteignable", distance_cible_km: "150" },
      },
      422,
    );
    expect(mesuresDistance(abime)).toBeNull();
  });
});

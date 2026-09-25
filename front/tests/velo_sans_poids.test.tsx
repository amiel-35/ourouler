/** Un vélo sans poids déclaré (25/09/2026).
 *
 * Depuis L9.7, l'assistant laisse le poids du vélo vide et envoie `null` : le
 * serveur suppose alors `MASSE_VELO_DEFAUT_KG`. Le récapitulatif formatait ce
 * `null` comme un nombre et l'écran entier tombait (« Cannot read properties
 * of null (reading 'toLocaleString') ») — trouvé en rejouant un invité dans un
 * vrai navigateur. Ce que ces tests gardent :
 *
 * 1. Réglages s'affiche, et dit le poids supposé plutôt qu'un chiffre inventé ;
 * 2. le champ du formulaire part vide, et un champ vide repart `null`.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Reglages } from "../src/ecrans/Reglages";
import { masseVeloAffichee } from "../src/api/formats";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";
import type { Profil } from "../src/api/types";

const ZONES = zones().donnees;

function sansPoids(): Profil {
  const profil = structuredClone(PROFIL.donnees);
  profil.velos = profil.velos.map((v) => ({ ...v, masse_kg: null }));
  return profil;
}

function rendre(profil: Profil) {
  const serveur = new Serveur({
    "/api/v1/profil/zones/apercu": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil": { charge: { proprietaire: "essai", donnees: profil } },
  });
  serveur.installer();
  render(
    <Reglages
      profil={profil}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surRefaireInstallation={() => undefined}
      surDeconnexion={() => undefined}
    />,
  );
  return { serveur };
}

describe("un vélo sans poids déclaré", () => {
  it("dit le poids supposé, sans inventer de chiffre", () => {
    expect(masseVeloAffichee(null)).toBe("9 kg supposés");
    expect(masseVeloAffichee(8.5)).toBe("8,5 kg");
  });

  it("s'affiche dans Réglages et repart null quand on n'y touche pas", async () => {
    const { serveur } = rendre(sansPoids());
    expect(screen.getAllByText(/9 kg supposés/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ou retirer" }));
    const champ = (await screen.findAllByLabelText("Poids du vélo"))[0] as HTMLInputElement;
    expect(champ.value).toBe("");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const velos = (patch.corps as { velos: Array<Record<string, unknown>> }).velos;
    expect(velos[0].masse_kg).toBeNull();
  });
});

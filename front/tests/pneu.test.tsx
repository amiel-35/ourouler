/** Le pneu sur la fiche vélo (L9.1, 25/09/2026).
 *
 * La catégorie de pneu donne le Crr du vélo : le serveur ne cherche plus
 * alors que le CdA quand il calibre. Ce que ces tests gardent :
 *
 * 1. le sélecteur existe sur chaque vélo, et part de « Je ne sais pas » quand
 *    le profil n'en déclare pas ;
 * 2. le choix part dans `velos[].pneu`, avec la clé du serveur ;
 * 3. « Je ne sais pas » s'envoie `null`, jamais une chaîne vide ;
 * 4. un pneu déjà déclaré est relu, et les autres champs du vélo survivent.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";
import type { Profil } from "../src/api/types";

const ZONES = zones().donnees;

function rendre(profil: Profil = PROFIL.donnees) {
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

async function enregistrerEtLire(serveur: Serveur) {
  await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));
  await waitFor(() =>
    expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
  );
  const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
  return (patch.corps as { velos: Array<Record<string, unknown>> }).velos;
}

describe("le pneu sur la fiche vélo", () => {
  it("part de « Je ne sais pas » sans pneu déclaré, et l'envoie null", async () => {
    const { serveur } = rendre();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ou retirer" }));
    const choix = (await screen.findByLabelText("Pneus")) as HTMLSelectElement;
    expect(choix.value).toBe("");
    expect(screen.getByRole("option", { name: "Je ne sais pas" })).toBeTruthy();
    const velos = await enregistrerEtLire(serveur);
    expect(velos[0].pneu).toBeNull();
  });

  it("envoie la clé du serveur pour le pneu choisi", async () => {
    const { serveur } = rendre();
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ou retirer" }));
    const choix = await screen.findByLabelText("Pneus");
    await userEvent.selectOptions(choix, "course_quatre_saisons");
    const velos = await enregistrerEtLire(serveur);
    expect(velos[0].pneu).toBe("course_quatre_saisons");
  });

  it("relit un pneu déjà déclaré, sans perdre le reste du vélo", async () => {
    const profil: Profil = {
      ...PROFIL.donnees,
      velos: PROFIL.donnees.velos.map((v) => ({ ...v, pneu: "course_rapide" as const })),
    };
    const { serveur } = rendre(profil);
    await userEvent.click(screen.getByRole("button", { name: "Ajouter ou retirer" }));
    const choix = (await screen.findByLabelText("Pneus")) as HTMLSelectElement;
    expect(choix.value).toBe("course_rapide");
    const velos = await enregistrerEtLire(serveur);
    expect(velos[0].pneu).toBe("course_rapide");
    expect(velos[0].nom).toBe(PROFIL.donnees.velos[0].nom);
    expect(velos[0].usage).toBe(PROFIL.donnees.velos[0].usage);
  });
});

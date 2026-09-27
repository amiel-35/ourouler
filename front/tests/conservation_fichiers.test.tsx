/** Fiche « choix de garder ou d'effacer ses fichiers d'origine », sprint 12.
 *
 * Ce que ces tests protègent, dans le volet « Mon compte » de `Reglages` :
 * - l'état affiché (garder / ne pas garder, nombre de fichiers) vient bien de
 *   `GET /moi/fichiers-origine` ;
 * - passer à « ne pas garder » demande une confirmation qui dit le coût, et
 *   n'appelle `PUT /moi/fichiers-origine` qu'après ce second clic ;
 * - revenir à « garder » n'a pas de confirmation à franchir ;
 * - sans compte (mode personnel), la section n'apparaît pas.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

function rendreReglages() {
  return render(
    <Reglages
      profil={PROFIL.donnees}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surRefaireInstallation={() => undefined}
      surDeconnexion={() => undefined}
    />,
  );
}

describe("fichiers d'origine, dans le volet « Mon compte »", () => {
  it("affiche l'état gardé et le nombre de fichiers depuis GET /moi/fichiers-origine", async () => {
    const serveur = new Serveur({
      "/api/v1/moi/fichiers-origine": {
        charge: {
          proprietaire: "essai",
          donnees: { garder: true, depuis: null, nombre_fichiers: 42 },
        },
      },
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("Vous gardez vos fichiers d'origine (42 fichiers)");
    expect(screen.getByText(/pas encore utilisé/)).toBeTruthy();
  });

  it("affiche l'état non gardé", async () => {
    const serveur = new Serveur({
      "/api/v1/moi/fichiers-origine": {
        charge: {
          proprietaire: "essai",
          donnees: { garder: false, depuis: "2026-09-27T10:00:00Z" },
        },
      },
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("Vous ne gardez pas vos fichiers d'origine");
    // Revenir à « garder » n'a pas de confirmation à franchir : le bouton
    // agit directement.
    expect(screen.getByRole("button", { name: "Garder mes fichiers d'origine" })).toBeTruthy();
  });

  it("ne passe à « ne pas garder » qu'après confirmation, jamais sur le premier clic", async () => {
    const serveur = new Serveur({
      "/api/v1/moi/fichiers-origine": (requete) =>
        requete.methode === "PUT"
          ? {
              charge: {
                proprietaire: "essai",
                donnees: { garder: false, depuis: "2026-09-27T10:00:00Z", fichiers_effaces: 42 },
              },
            }
          : {
              charge: {
                proprietaire: "essai",
                donnees: { garder: true, depuis: null, nombre_fichiers: 42 },
              },
            },
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("Vous gardez vos fichiers d'origine (42 fichiers)");

    await userEvent.click(screen.getByRole("button", { name: "Ne plus les garder…" }));
    expect(serveur.vers("/api/v1/moi/fichiers-origine").filter((r) => r.methode === "PUT")).toHaveLength(0);
    await screen.findByText(/Vos calibrations et votre historique restent/);

    await userEvent.click(
      screen.getByRole("button", { name: "Confirmer : ne plus garder mes fichiers" }),
    );
    await screen.findByText("Vous ne gardez pas vos fichiers d'origine");

    const requetes = serveur.vers("/api/v1/moi/fichiers-origine").filter((r) => r.methode === "PUT");
    expect(requetes).toHaveLength(1);
    expect(requetes[0].corps).toEqual({ garder: false });
  });

  it("annuler la confirmation n'appelle pas PUT", async () => {
    const serveur = new Serveur({
      "/api/v1/moi/fichiers-origine": {
        charge: {
          proprietaire: "essai",
          donnees: { garder: true, depuis: null, nombre_fichiers: 3 },
        },
      },
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("Vous gardez vos fichiers d'origine (3 fichiers)");
    await userEvent.click(screen.getByRole("button", { name: "Ne plus les garder…" }));
    await screen.findByText(/Vos calibrations et votre historique restent/);
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    expect(screen.queryByText(/Vos calibrations et votre historique restent/)).toBeNull();
    expect(serveur.vers("/api/v1/moi/fichiers-origine").filter((r) => r.methode === "PUT")).toHaveLength(0);
  });

  it("n'affiche pas la section sans compte (mode personnel)", async () => {
    const serveur = new Serveur({
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: null } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("aucun compte sur ce serveur");

    expect(screen.queryByText(/gardez vos fichiers d'origine/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Fichiers d'origine" })).toBeNull();
  });
});

/** Lot L9.6 — réinitialisation de mot de passe et volet « Mon compte ».
 *
 * Ce que ces tests protègent :
 * - `/reinitialiser?jeton=…` réutilise l'écran `Entrer` (mode `"reinitialiser"`) et
 *   appelle bien `POST /reinitialiser`, pas `POST /entrer` — les deux jetons ne se
 *   consomment pas de la même façon côté serveur (`api/comptes.py`).
 * - le volet « Mon compte » de `Reglages` charge l'adresse (`GET /moi`), change le mot
 *   de passe (`POST /moi/mot-de-passe`) avec le bon corps, et n'efface le compte
 *   qu'après la double confirmation (`DELETE /moi`) — jamais sur le premier clic.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Entrer } from "../src/ecrans/Entrer";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

describe("Entrer en mode réinitialisation", () => {
  it("appelle POST /reinitialiser, pas /entrer, à la soumission", async () => {
    const serveur = new Serveur({
      "/api/v1/invitation": {
        charge: { donnees: { email: "reglee@exemple.invalid", expire_le: "2026-09-30T12:00:00Z" } },
      },
      "/api/v1/reinitialiser": { charge: { donnees: { proprietaire: "essai" } } },
    });
    serveur.installer();

    let entre = false;
    render(<Entrer jeton="un-jeton" mode="reinitialiser" surEntre={() => (entre = true)} />);

    await screen.findByRole("heading", { name: "Nouveau mot de passe" });

    await userEvent.type(screen.getByLabelText("Nouveau mot de passe"), "un-nouveau-secret-1234");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer le nouveau mot de passe" }));

    await waitFor(() => expect(entre).toBe(true));
    const requetes = serveur.vers("/api/v1/reinitialiser");
    expect(requetes).toHaveLength(1);
    expect(requetes[0].corps).toEqual({ jeton: "un-jeton", secret: "un-nouveau-secret-1234" });
    expect(serveur.vers("/api/v1/entrer")).toHaveLength(0);
  });
});

describe("le volet « Mon compte » des réglages", () => {
  function rendreReglages(surDeconnexion: () => void = () => undefined) {
    return render(
      <Reglages
        profil={PROFIL.donnees}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surRefaireInstallation={() => undefined}
        surDeconnexion={surDeconnexion}
      />,
    );
  }

  it("charge et affiche l'adresse du compte à l'ouverture du volet", async () => {
    const serveur = new Serveur({
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("compte@exemple.invalid");
  });

  it("envoie l'ancien et le nouveau mot de passe à POST /moi/mot-de-passe", async () => {
    const serveur = new Serveur({
      // Le chemin le plus spécifique d'abord : `Serveur.installer` retient le
      // premier motif dont le chemin demandé commence par lui (`vers`,
      // `tests/serveur.ts`) — "/api/v1/moi" est aussi un préfixe de
      // "/api/v1/moi/mot-de-passe", donc l'ordre inverse ferait retomber la
      // requête de changement de mot de passe sur la réponse de `GET /moi`.
      "/api/v1/moi/mot-de-passe": { charge: { proprietaire: "essai", donnees: {} } },
      "/api/v1/moi": { charge: { proprietaire: "essai", donnees: { email: "compte@exemple.invalid" } } },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("compte@exemple.invalid");

    await userEvent.type(screen.getByLabelText("Mot de passe actuel"), "ancien-secret");
    await userEvent.type(screen.getByLabelText("Nouveau mot de passe"), "nouveau-secret");
    await userEvent.click(screen.getByRole("button", { name: "Changer le mot de passe" }));

    await screen.findByText("Mot de passe changé.");
    const requetes = serveur.vers("/api/v1/moi/mot-de-passe");
    expect(requetes).toHaveLength(1);
    expect(requetes[0].corps).toEqual({
      mot_de_passe_actuel: "ancien-secret",
      nouveau_mot_de_passe: "nouveau-secret",
    });
  });

  it("n'efface le compte qu'après la double confirmation, jamais sur le premier clic", async () => {
    const serveur = new Serveur({
      "/api/v1/moi": {
        charge: { proprietaire: "essai", donnees: { email: "a-supprimer@exemple.invalid" } },
      },
    });
    serveur.installer();
    let deconnecte = false;
    rendreReglages(() => (deconnecte = true));

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("a-supprimer@exemple.invalid");

    await userEvent.click(screen.getByRole("button", { name: "Supprimer mon compte…" }));
    // Le premier clic n'a rien envoyé au serveur : seul le texte explicatif apparaît.
    expect(serveur.vers("/api/v1/moi").filter((r) => r.methode === "DELETE")).toHaveLength(0);
    await screen.findByText(/Ceci efface définitivement/, { selector: "b" });

    await userEvent.click(screen.getByRole("button", { name: "Confirmer la suppression définitive" }));
    await waitFor(() => expect(deconnecte).toBe(true));

    const suppressions = serveur.vers("/api/v1/moi").filter((r) => r.methode === "DELETE");
    expect(suppressions).toHaveLength(1);
  });

  it("annuler la confirmation ne supprime rien", async () => {
    const serveur = new Serveur({
      "/api/v1/moi": {
        charge: { proprietaire: "essai", donnees: { email: "hesitant@exemple.invalid" } },
      },
    });
    serveur.installer();
    rendreReglages();

    await userEvent.click(screen.getByRole("button", { name: "Gérer" }));
    await screen.findByText("hesitant@exemple.invalid");
    await userEvent.click(screen.getByRole("button", { name: "Supprimer mon compte…" }));
    await screen.findByText(/Ceci efface définitivement/, { selector: "b" });
    await userEvent.click(screen.getByRole("button", { name: "Annuler" }));

    expect(screen.queryByText(/Ceci efface définitivement/, { selector: "b" })).toBeNull();
    expect(serveur.vers("/api/v1/moi").filter((r) => r.methode === "DELETE")).toHaveLength(0);
  });
});

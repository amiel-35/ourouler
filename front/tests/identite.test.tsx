/** Prénom et nom — Q36, tranché le 17/09/2026 : « nom prénom obligatoire car
 * c'est la base ». Ce que ces tests protègent :
 *
 * - le premier écran de l'assistant bloque tant que l'un des deux manque,
 *   exactement comme le départ bloque plus loin dans le parcours ;
 * - le panneau « Identité » des réglages fait la même chose pour un profil
 *   qui arrive ici avec les champs vides — un profil créé avant ce lot ;
 * - ce qui part au serveur est bien `cycliste.prenom`/`cycliste.nom`, pas un
 *   champ inventé qu'`api/depots.CHAMPS_MODIFIABLES` refuserait.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

describe("l'assistant — étape d'identité", () => {
  it("refuse de continuer tant que prénom ou nom manque", async () => {
    render(
      <Assistant
        profil={{ ...PROFIL.donnees, cycliste: { ...PROFIL.donnees.cycliste, prenom: "", nom: "" } }}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surFin={() => undefined}
        vers="Aujourd'hui"
        surRetour={() => undefined}
      />,
    );
    // L'assistant ouvre maintenant sur AC1 Bienvenue (`docs/ux/
    // parcours_accueil.md` §1) : l'identité n'apparaît qu'après.
    await userEvent.click(screen.getByRole("button", { name: "Commencer" }));
    const continuer = screen.getByRole("button", { name: "Continuer" }) as HTMLButtonElement;
    expect(continuer.disabled).toBe(true);

    await userEvent.type(screen.getByLabelText("Prénom"), "Camille");
    expect(continuer.disabled).toBe(true);

    await userEvent.type(screen.getByLabelText("Nom"), "Ruiz");
    expect(continuer.disabled).toBe(false);
  });

  it("envoie prénom et nom, et rien d'autre, dans cycliste", async () => {
    const serveur = new Serveur({
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
      "/api/v1/profil": { charge: PROFIL },
    });
    serveur.installer();
    render(
      <Assistant
        profil={{ ...PROFIL.donnees, cycliste: { ...PROFIL.donnees.cycliste, prenom: "", nom: "" } }}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surFin={() => undefined}
        vers="Aujourd'hui"
        surRetour={() => undefined}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Commencer" }));
    await userEvent.type(screen.getByLabelText("Prénom"), "Camille");
    await userEvent.type(screen.getByLabelText("Nom"), "Ruiz");
    await userEvent.click(screen.getByRole("button", { name: "Continuer" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil").length).toBeGreaterThan(0));
    const patch = serveur.vers("/api/v1/profil").find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { cycliste?: Record<string, unknown> };
    expect(corps.cycliste).toEqual({ prenom: "Camille", nom: "Ruiz" });

    // L'écran suivant est bien celui du départ (AC5, juste après l'identité
    // dans le nouvel arbre — `docs/ux/parcours_accueil.md` §5.1) : l'étape a
    // avancé, et ce n'est plus la FTP qui ouvrait l'ancien parcours.
    await waitFor(() => expect(screen.getByText("D'où partez-vous ?")).toBeTruthy());
  });
});

describe("les réglages — panneau identité", () => {
  function rendre(cyclisteVide = false) {
    const profil = cyclisteVide
      ? { ...PROFIL.donnees, cycliste: { ...PROFIL.donnees.cycliste, prenom: "", nom: "" } }
      : PROFIL.donnees;
    const serveur = new Serveur({
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

  it("affiche « à renseigner » pour un profil antérieur à ce lot", () => {
    rendre(true);
    expect(screen.getByRole("button", { name: "à renseigner" })).toBeTruthy();
  });

  it("affiche le nom déjà enregistré", () => {
    rendre(false);
    expect(screen.getByRole("button", { name: "Alix Fictif" })).toBeTruthy();
  });

  it("bloque l'enregistrement tant que l'un des deux champs est vide", async () => {
    rendre(true);
    await userEvent.click(screen.getByRole("button", { name: "à renseigner" }));
    const enregistrer = screen.getByRole("button", { name: "Enregistrer" }) as HTMLButtonElement;
    expect(enregistrer.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Prénom"), "Camille");
    expect(enregistrer.disabled).toBe(true);
    await userEvent.type(screen.getByLabelText("Nom"), "Ruiz");
    expect(enregistrer.disabled).toBe(false);
  });

  it("enregistre prénom et nom quand les deux sont remplis", async () => {
    const { serveur } = rendre(true);
    await userEvent.click(screen.getByRole("button", { name: "à renseigner" }));
    await userEvent.type(screen.getByLabelText("Prénom"), "Camille");
    await userEvent.type(screen.getByLabelText("Nom"), "Ruiz");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { cycliste?: Record<string, unknown> };
    expect(corps.cycliste).toEqual({ prenom: "Camille", nom: "Ruiz" });
    expect(screen.getByText("Identité enregistrée.")).toBeTruthy();
  });
});

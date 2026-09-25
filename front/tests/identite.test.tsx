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

import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur, panne } from "./serveur";
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

describe("les réglages — panneau intervals.icu", () => {
  /** Porte le profil en état, comme le ferait `App.tsx` : c'est ce qui
   * permet d'observer la rangée « Branché » se mettre à jour après
   * `surProfil`, plutôt que de figer le prop comme les autres tests
   * de ce fichier (qui ne vérifient pas ce rafraîchissement). */
  function Porteur({ depart }: { depart: typeof PROFIL.donnees }) {
    const [profil, setProfil] = useState(depart);
    return (
      <Reglages
        profil={profil}
        zones={ZONES}
        surProfil={setProfil}
        surZones={() => undefined}
        surRefaireInstallation={() => undefined}
        surDeconnexion={() => undefined}
      />
    );
  }

  /** Le conteneur du volet ouvert — repéré par le champ de la clé, seul volet
   * affiché à la fois puisque `volet` est un état unique côté `Reglages`. */
  function conteneurVolet() {
    return screen.getByLabelText("Votre clé intervals.icu").closest(".bloc")! as HTMLElement;
  }

  it("affiche sous le bouton, dans le volet, que la clé a été vérifiée — et branche la rangée", async () => {
    const nonBranche = {
      ...PROFIL.donnees,
      services: { ...PROFIL.donnees.services, intervals: { renseigne: false, athlete_id: "" } },
    };
    const branche = {
      ...PROFIL.donnees,
      services: { ...PROFIL.donnees.services, intervals: { renseigne: true, athlete_id: "iFICTIF" } },
    };
    const serveur = new Serveur({
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
      "/api/v1/profil": { charge: { proprietaire: "essai", donnees: branche } },
    });
    serveur.installer();
    render(<Porteur depart={nonBranche} />);

    await userEvent.click(screen.getByRole("button", { name: "Non branché" }));
    await userEvent.type(screen.getByLabelText("Votre clé intervals.icu"), "une-cle-fictive");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer la clé" }));

    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    expect(patch.corps).toEqual({ intervals: { api_key: "une-cle-fictive" } });

    const message = await within(conteneurVolet()).findByText(
      "Clé vérifiée auprès d'intervals.icu : c'est branché.",
    );
    expect(message.getAttribute("role")).toBe("status");

    await waitFor(() => expect(screen.getByRole("button", { name: "Branché" })).toBeTruthy());
  });

  it("affiche l'erreur de l'API dans le volet, en role alert, quand intervals.icu refuse la clé", async () => {
    const nonBranche = {
      ...PROFIL.donnees,
      services: { ...PROFIL.donnees.services, intervals: { renseigne: false, athlete_id: "" } },
    };
    const serveur = new Serveur({
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
      "/api/v1/profil": panne("intervals_refuse", "Intervals.icu : HTTP 403", 502),
    });
    serveur.installer();
    render(<Porteur depart={nonBranche} />);

    await userEvent.click(screen.getByRole("button", { name: "Non branché" }));
    await userEvent.type(screen.getByLabelText("Votre clé intervals.icu"), "une-cle-refusee");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer la clé" }));

    const alerte = await screen.findByRole("alert");
    expect(alerte.textContent).toBe("Intervals.icu : HTTP 403");
    expect(conteneurVolet().contains(alerte)).toBe(true);
    // Refusée : le champ garde la clé saisie, rien n'est effacé.
    expect((screen.getByLabelText("Votre clé intervals.icu") as HTMLInputElement).value).toBe(
      "une-cle-refusee",
    );
  });
});

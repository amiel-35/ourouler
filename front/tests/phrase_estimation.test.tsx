/** La phrase sous « Ce que ça donnera » (`Demander.tsx`) — backlog « la
 * phrase sur la vitesse », note du mainteneur du 20/09/2026 (« c'est débile,
 * faut faire plus simple ») et décision du 25/09/2026 (« fais 8 ») :
 * formulation A, sans chiffre de moyenne compteur ni jargon « modèle
 * physique littérature ». Deux variantes seulement, selon que la vitesse (ou
 * le vélo) est mesurée ou non — jamais un troisième texte inventé.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Demander, demandeInitiale, phraseEstimation } from "../src/ecrans/Demander";
import type { ValeursLiees } from "../src/api/types";
import { Serveur } from "./serveur";
import { PROFIL, meteo, ventDepart, zones } from "./fixtures";

const BASE: ValeursLiees = zones().donnees.valeurs_liees!;

function installerServeur() {
  const serveur = new Serveur({
    "/api/v1/vent-depart": { charge: ventDepart() },
    "/api/v1/meteo": { charge: meteo() },
  });
  serveur.installer();
  return serveur;
}

describe("phraseEstimation", () => {
  it("dit « profil et vélo » quand rien n'est mesuré", () => {
    const liees = { ...BASE, facteur_mesure: false, modele_physique: "défaut" };
    expect(phraseEstimation(liees)).toBe("Estimation d'après votre profil et votre vélo.");
  });

  it("dit « vos sorties » quand le facteur de compteur est mesuré", () => {
    const liees = { ...BASE, facteur_mesure: true, modele_physique: "configuration" };
    expect(phraseEstimation(liees)).toBe("Estimation d'après vos sorties.");
  });

  it("dit « vos sorties » quand le vélo est calibré, même sans facteur mesuré", () => {
    const liees = { ...BASE, facteur_mesure: false, modele_physique: "calibration" };
    expect(phraseEstimation(liees)).toBe("Estimation d'après vos sorties.");
  });

  it("ne mentionne ni chiffre de moyenne compteur ni jargon de modèle physique", () => {
    for (const liees of [
      { ...BASE, facteur_mesure: false, modele_physique: "défaut" },
      { ...BASE, facteur_mesure: true, modele_physique: "configuration" },
    ]) {
      const phrase = phraseEstimation(liees);
      expect(phrase).not.toMatch(/km\/h/);
      expect(phrase).not.toMatch(/modèle physique/i);
      expect(phrase).not.toMatch(/facteur/i);
    }
  });
});

describe("l'écran « Ce que ça donnera »", () => {
  it("affiche la phrase courte, pas l'ancien paragraphe technique", async () => {
    const serveur = installerServeur();
    render(
      <Demander
        profil={PROFIL.donnees}
        zones={zones({ facteurMesure: false }).donnees}
        dureeSeance_s={null}
        nomSeance={null}
        demande={demandeInitiale()}
        budget={null}
        surDemande={() => undefined}
        surChercher={() => undefined}
      />,
    );
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));
    expect(screen.getByText("Estimation d'après votre profil et votre vélo.")).toBeTruthy();
    expect(screen.queryByText(/Estimé avec votre moyenne compteur/)).toBeNull();
    expect(screen.queryByText(/Facteur de compteur/)).toBeNull();
    expect(screen.queryByText(/modèle physique/)).toBeNull();
  });

  it("bascule sur « vos sorties » quand le facteur de compteur est mesuré", async () => {
    const serveur = installerServeur();
    render(
      <Demander
        profil={PROFIL.donnees}
        zones={zones({ facteurMesure: true }).donnees}
        dureeSeance_s={null}
        nomSeance={null}
        demande={demandeInitiale()}
        budget={null}
        surDemande={() => undefined}
        surChercher={() => undefined}
      />,
    );
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));
    expect(screen.getByText("Estimation d'après vos sorties.")).toBeTruthy();
  });
});

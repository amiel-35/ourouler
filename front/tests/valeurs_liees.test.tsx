/** Les trois valeurs liées — décisions 7 et 8.
 *
 * Ce que ces tests protègent, et qui casserait en silence :
 *
 * - éditer la puissance ou la vitesse **demande à l'API** de recalculer, avec
 *   **une seule** entrée, et affiche ce qui revient ;
 * - la moyenne compteur **ne s'édite pas**, et **dit** si son facteur est
 *   mesuré ou supposé — sans ça, l'écran ment à qui hérite du défaut ;
 * - une position hors bande **se montre** au lieu d'être corrigée en silence ;
 * - ce qu'on enregistre est la **position**, jamais les watts.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EcranFtp } from "../src/composants/EcranFtp";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

function rendre(options?: { facteurMesure?: boolean; horsBande?: boolean }) {
  const depart = zones(options).donnees;
  const apres = zones({ ...options, horsBande: true }).donnees;
  const serveur = new Serveur({
    "/api/v1/profil/zones/apercu": { charge: { proprietaire: "essai", donnees: apres } },
  });
  serveur.installer();
  const vues: unknown[] = [];
  const rendu = render(
    <EcranFtp zones={depart} surApercu={(z) => vues.push(z)} />,
  );
  return { serveur, vues, rendu, depart, apres };
}

describe("les trois valeurs", () => {
  it("affichent ce que l'API a rendu, et seulement ça", () => {
    const { depart } = rendre();
    const puissance = screen.getByLabelText("Puissance visée") as HTMLInputElement;
    const vitesse = screen.getByLabelText(/Vitesse à plat/) as HTMLInputElement;
    const moyenne = screen.getByLabelText("Moyenne compteur attendue") as HTMLInputElement;
    expect(puissance.value).toBe("131");
    expect(vitesse.value).toBe("26,3");
    expect(moyenne.value).toBe("21,9");
    expect(depart.valeurs_liees!.moyenne_compteur_kmh).toBe(21.9);
  });

  it("laissent la moyenne compteur en lecture seule", () => {
    rendre();
    const moyenne = screen.getByLabelText("Moyenne compteur attendue") as HTMLInputElement;
    expect(moyenne.readOnly).toBe(true);
    expect(moyenne.disabled).toBe(true);
  });

  it("disent que le facteur est supposé quand il n'est pas mesuré", () => {
    rendre({ facteurMesure: false });
    expect(screen.getByText("supposé — il n'a pas été mesuré sur vos sorties")).toBeTruthy();
    expect(screen.queryByText("mesuré sur vos sorties")).toBeNull();
  });

  it("disent que le facteur est mesuré quand il l'est", () => {
    rendre({ facteurMesure: true });
    expect(screen.getByText("mesuré sur vos sorties")).toBeTruthy();
    expect(screen.queryByText(/supposé/)).toBeNull();
  });
});

describe("la réconciliation", () => {
  it("n'envoie qu'une entrée à l'aperçu quand on tape une puissance", async () => {
    const { serveur, vues } = rendre();
    const puissance = screen.getByLabelText("Puissance visée");
    await userEvent.clear(puissance);
    await userEvent.type(puissance, "147");
    await waitFor(() => expect(serveur.vers("/api/v1/profil/zones/apercu").length).toBe(1), {
      timeout: 2000,
    });
    const corps = serveur.vers("/api/v1/profil/zones/apercu")[0].corps as Record<string, unknown>;
    expect(Object.keys(corps).filter((c) => corps[c] !== undefined).sort()).toEqual([
      "puissance_w",
    ]);
    expect(corps.puissance_w).toBe(147);
    expect(vues).toHaveLength(1);
  });

  it("n'envoie qu'une entrée quand on tape une vitesse à plat", async () => {
    const { serveur } = rendre();
    const vitesse = screen.getByLabelText(/Vitesse à plat/);
    await userEvent.clear(vitesse);
    await userEvent.type(vitesse, "24");
    await waitFor(() => expect(serveur.vers("/api/v1/profil/zones/apercu").length).toBe(1), {
      timeout: 2000,
    });
    const corps = serveur.vers("/api/v1/profil/zones/apercu")[0].corps as Record<string, unknown>;
    expect(corps.vitesse_a_plat_kmh).toBe(24);
    expect(corps.puissance_w).toBeUndefined();
    expect(corps.position_zone).toBeUndefined();
  });

  it("montre la sortie de bande au lieu de la corriger en silence", () => {
    rendre({ horsBande: true });
    expect(screen.getByText(/Vous êtes sorti de votre Z2/)).toBeTruthy();
    expect(screen.getByText(/quand on saisit sa moyenne compteur dans le champ/)).toBeTruthy();
  });
});

describe("ce qui est enregistré", () => {
  it("est la position dans la zone, jamais les watts", async () => {
    const etat = zones().donnees;
    const serveur = new Serveur({
      "/api/v1/profil/zones/apercu": { charge: { proprietaire: "essai", donnees: etat } },
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: etat } },
      "/api/v1/profil": { charge: PROFIL },
    });
    serveur.installer();
    render(
      <Reglages
        profil={PROFIL.donnees}
        zones={etat}
        surProfil={() => undefined}
        surZones={() => undefined}
        surRefaireInstallation={() => undefined}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /211/ }));
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer cette allure" }));
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { seance?: Record<string, unknown> };
    expect(corps.seance).toEqual({ position_zone: etat.position_zone });
    // Aucune clé en watts n'a le droit de partir dans cet enregistrement.
    expect(JSON.stringify(corps)).not.toMatch(/_w"/);
  });
});

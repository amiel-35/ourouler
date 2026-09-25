/** L'accueil ne garde plus un départ vide (rejoué le 25/09/2026).
 *
 * Un compte neuf n'a pas de départ réel : le profil porte le comblement
 * embarqué par le serveur (`COMBLEMENT_EMBARQUEMENT`, `src/ourouler/api/
 * depots.py`), nom « Départ », coordonnées (0, 0). L'assistant proposait
 * quand même « Garder ce départ » sous la recherche d'adresse, et le
 * cliquer gardait ce défaut. Ce test protège : un compte neuf n'a pas ce
 * bouton ; un compte qui refait l'installation (départ déjà réel) l'a
 * toujours.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

const DEPART_PAR_DEFAUT = { nom: "Départ", latitude: 0, longitude: 0 };

function rendre(depart: { nom: string; latitude: number; longitude: number }) {
  const profil = { ...PROFIL.donnees, depart };
  const serveur = new Serveur({
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil": { charge: { ...PROFIL, donnees: profil } },
  });
  serveur.installer();
  render(
    <Assistant
      profil={profil}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surFin={() => undefined}
      vers="Aujourd'hui"
      surRetour={() => undefined}
    />,
  );
  return { utilisateur: userEvent.setup() };
}

async function versDepart(utilisateur: ReturnType<typeof userEvent.setup>) {
  await utilisateur.click(screen.getByRole("button", { name: "Commencer" }));
  await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));
}

describe("compte neuf, départ jamais renseigné", () => {
  it("ne propose pas « Garder ce départ »", async () => {
    const { utilisateur } = rendre(DEPART_PAR_DEFAUT);
    await versDepart(utilisateur);

    expect(await screen.findByText("D'où partez-vous ?")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Garder ce départ" })).toBeNull();
  });
});

describe("réinstallation, départ déjà réel", () => {
  it("propose toujours « Garder ce départ »", async () => {
    const { utilisateur } = rendre({ nom: "Sainte-Fictive", latitude: 47.0, longitude: -0.5 });
    await versDepart(utilisateur);

    expect(await screen.findByText("D'où partez-vous ?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Garder ce départ" })).toBeTruthy();
  });
});

/** L'accueil ne garde plus un départ vide (rejoué le 25/09/2026).
 *
 * Un compte neuf n'a pas de départ réel : le profil porte le repli du
 * produit (« Paris », `DEPART_PAR_DEFAUT` côté serveur, fiche
 * `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md`), signalé
 * par `depart.par_defaut`. L'assistant proposait quand même « Garder ce
 * départ » sous la recherche d'adresse, et le cliquer gardait ce défaut. Ce
 * test protège : un compte neuf n'a pas ce bouton ; un compte qui refait
 * l'installation (départ déjà réel) l'a toujours.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import type { DepartProfil } from "../src/api/types";
import { Serveur } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

// Coordonnées fictives (règle absolue 1) : seule `noyau.profil.DEPART_PAR_DEFAUT`
// porte les vraies coordonnées du repli côté serveur. Ce qui compte ici est
// `par_defaut`, pas le couple de degrés.
const DEPART_PAR_DEFAUT = { nom: "Paris", latitude: 0, longitude: 0, par_defaut: true };

function rendre(depart: DepartProfil) {
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
    const { utilisateur } = rendre({
      nom: "Sainte-Fictive",
      latitude: 47.0,
      longitude: -0.5,
      par_defaut: false,
    });
    await versDepart(utilisateur);

    expect(await screen.findByText("D'où partez-vous ?")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Garder ce départ" })).toBeTruthy();
  });
});

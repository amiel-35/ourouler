/** La rose des huit directions — remplace les huit boutons de texte de
 * `Demander` (20/09/2026). Ce que ces tests protègent :
 *
 * - chaque secteur reste actionnable au clavier (Tab puis Entrée, ou
 *   Espace) — la exigence explicite du lot : au moins aussi accessible que
 *   les huit boutons qu'il remplace ;
 * - la direction recommandée se lit dans le nom accessible du secteur
 *   (« recommandée »), jamais par une couleur qui lui serait propre
 *   (règle 3 de la direction visuelle) ;
 * - le désaccord entre modèles se lit dans le nom accessible du secteur
 *   concerné, jamais dans une teinte ;
 * - `Aujourdhui` montre le résumé de la rose tant qu'aucun parcours n'existe
 *   pour ce jour, et s'en passe dès qu'un parcours est obtenu.
 */

import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Demander, demandeInitiale, type Demande } from "../src/ecrans/Demander";
import { Aujourdhui } from "../src/ecrans/Aujourdhui";
import { Boucles } from "../src/ecrans/Boucles";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, boucle, meteo, sortie, ventDepart, zones } from "./fixtures";

const ZONES = zones().donnees;

function ConteneurDemander({ demande: demandeDepart }: { demande: Demande }) {
  const [demande, setDemande] = useState(demandeDepart);
  return (
    <Demander
      profil={PROFIL.donnees}
      zones={ZONES}
      dureeSeance_s={SEANCE.donnees.duree_s}
      nomSeance={SEANCE.donnees.nom}
      demande={demande}
      budget={null}
      surDemande={setDemande}
      surChercher={() => undefined}
    />
  );
}

function demandeEssai(morceau?: Partial<Demande>): Demande {
  return { ...demandeInitiale(), jour: "2026-09-18", modeDirection: "direction", ...morceau };
}

function installerDemander() {
  const serveur = new Serveur({
    "/api/v1/vent-depart": { charge: ventDepart() },
    "/api/v1/meteo": { charge: meteo() },
  });
  serveur.installer();
  return serveur;
}

describe("la rose remplace les huit boutons cardinaux", () => {
  it("choisir un secteur à la souris pose bien `demande.direction`", async () => {
    installerDemander();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);

    const secteurNordOuest = await screen.findByRole("button", { name: /^nord-ouest/i });
    await utilisateur.click(secteurNordOuest);
    // `aria-pressed` bascule : c'est le même contrat que les anciens
    // boutons (`aria-pressed={demande.direction === point}`).
    expect(secteurNordOuest.getAttribute("aria-pressed")).toBe("true");
  });

  it("un secteur se choisit au clavier : Tab puis Entrée", async () => {
    installerDemander();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);

    const secteurNord = await screen.findByRole("button", { name: /^nord —/i });
    secteurNord.focus();
    expect(document.activeElement).toBe(secteurNord);
    await utilisateur.keyboard("{Enter}");
    expect(secteurNord.getAttribute("aria-pressed")).toBe("true");
  });

  it("un secteur se choisit au clavier : Tab puis Espace", async () => {
    installerDemander();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);

    const secteurSud = await screen.findByRole("button", { name: /^sud —/i });
    secteurSud.focus();
    await utilisateur.keyboard(" ");
    expect(secteurSud.getAttribute("aria-pressed")).toBe("true");
  });

  it("chaque secteur porte un `tabIndex`, donc un focus visible par la règle générale du socle", async () => {
    installerDemander();
    render(<ConteneurDemander demande={demandeEssai()} />);
    const secteurEst = await screen.findByRole("button", { name: /^est —/i });
    expect(secteurEst.getAttribute("tabindex")).toBe("0");
  });

  it("la direction recommandée se lit dans le nom accessible, jamais dans une couleur qui lui serait propre", async () => {
    installerDemander();
    render(<ConteneurDemander demande={demandeEssai()} />);
    // La fixture `meteo()` recommande le nord-ouest.
    const secteurRecommande = await screen.findByRole("button", { name: /^nord-ouest.*recommandée/i });
    expect(secteurRecommande).toBeTruthy();
    const secteurAutre = await screen.findByRole("button", { name: /^sud —/i });
    expect(secteurAutre.getAttribute("aria-label")).not.toMatch(/recommandée/);
  });

  it("le désaccord entre modèles se lit dans le nom accessible du secteur concerné", async () => {
    installerDemander();
    render(<ConteneurDemander demande={demandeEssai()} />);
    // La fixture pose le désaccord sur l'est (1,4 mm annoncés par un
    // modèle, 0,0 par l'autre).
    const secteurEst = await screen.findByRole("button", { name: /^est —/i });
    expect(secteurEst.getAttribute("aria-label")).toMatch(/désaccord/);
    const secteurNord = await screen.findByRole("button", { name: /^nord —/i });
    expect(secteurNord.getAttribute("aria-label")).not.toMatch(/désaccord/);
  });
});

describe("Aujourdhui : la rose répond à « où rouler » avant d'avoir rien demandé", () => {
  it("montre le résumé quand aucun parcours n'existe encore pour ce jour", async () => {
    new Serveur({ "/api/v1/meteo": { charge: meteo() } }).installer();
    render(
      <Aujourdhui
        jour="2026-09-18"
        seance={null}
        parcours={null}
        surGenerer={() => undefined}
        surOuvrir={() => undefined}
        surDemander={() => undefined}
        surDeposer={() => undefined}
      />,
    );
    expect(await screen.findByRole("heading", { name: "Où rouler" })).toBeTruthy();
    // Le résumé nomme la direction recommandée par la fixture.
    expect(await screen.findByText(/nord-ouest/i)).toBeTruthy();
  });

  it("s'efface dès qu'un parcours existe déjà — la carte répond déjà à « où »", async () => {
    const reponse = sortie();
    render(
      <Aujourdhui
        jour="2026-09-16"
        seance={null}
        parcours={{ obtenue_le: "2026-09-16T06:02:00+02:00", reponse }}
        surGenerer={() => undefined}
        surOuvrir={() => undefined}
        surDemander={() => undefined}
        surDeposer={() => undefined}
      />,
    );
    expect(screen.queryByRole("heading", { name: "Où rouler" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Parcours prêt" })).toBeTruthy();
  });
});

describe("la pluie se dessine, plutôt qu'un seul nombre (Boucles)", () => {
  it("un parcours sec garde le mot « Sec », sans jauge", () => {
    const reponse = boucle();
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    expect(screen.getByText("Sec")).toBeTruthy();
    expect(screen.getByText(/0,0 mm de pluie/)).toBeTruthy();
  });
});

/** Les quatre états d'échec sont des **écrans**, et ils cassent en silence.
 *
 * C'est exactement ce qui justifie ces tests : un écran d'échec n'est jamais
 * regardé pendant le développement, et un écran vide se lit « rien de prévu ».
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErreurApi } from "../src/api/client";
import { Echec } from "../src/composants/Echec";
import { Barriere } from "../src/composants/Barriere";
import { Propositions } from "../src/ecrans/Propositions";
import { Aujourdhui } from "../src/ecrans/Aujourdhui";
import { sortie } from "./fixtures";

function erreur(code: string, message: string, statut = 502) {
  return new ErreurApi({ code, message, service: null, details: {} }, statut);
}

describe("aucune boucle trouvée", () => {
  it("propose des leviers avec leurs valeurs, jamais un « réessayez » nu", () => {
    const essais: string[] = [];
    render(
      <Echec
        erreur={erreur("aucune_boucle", "aucune boucle dans la tolérance", 422)}
        contexte="Un contexte inventé"
        replis={[
          { titre: "Élargir la durée", detail: "108 à 132 minutes", action: () => essais.push("duree") },
          { titre: "Laisser le vent libre", action: () => essais.push("vent") },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Aucune boucle" })).toBeTruthy();
    expect(screen.getByText(/aucune boucle dans la tolérance/)).toBeTruthy();
    expect(screen.getByText("Élargir la durée")).toBeTruthy();
    expect(screen.getByText("108 à 132 minutes")).toBeTruthy();
    expect(screen.getByText(/ne coûte rien/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Essayer" })).toHaveLength(2);
  });
});

describe("clé Intervals révoquée", () => {
  it("dit la date du dernier succès et ce qui marche encore", () => {
    render(
      <Echec
        erreur={erreur("intervals_refuse", "Intervals.icu : HTTP 403")}
        dernierSucces="2026-09-12"
        secours={<p>Vous pouvez demander un parcours à la main.</p>}
      />,
    );
    expect(screen.getByText(/ne nous répond plus/)).toBeTruthy();
    expect(screen.getByText(/plus lues depuis le 2026-09-12/)).toBeTruthy();
    expect(screen.getByText(/demander un parcours à la main/)).toBeTruthy();
  });

  it("n'invente aucune date quand le navigateur n'en a pas", () => {
    render(<Echec erreur={erreur("intervals_refuse", "Intervals.icu : HTTP 403")} />);
    expect(screen.queryByText(/plus lues depuis/)).toBeNull();
  });
});

describe("météo indisponible", () => {
  it("se tait sur la tenue au lieu de conseiller au hasard", () => {
    render(
      <Echec
        erreur={erreur("meteo_indisponible", "Open-Meteo : HTTP 502")}
        reessayer={() => undefined}
      />,
    );
    expect(screen.getByText(/on ne conseille rien plutôt que de conseiller au hasard/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Réessayer la météo" })).toBeTruthy();
  });

  it("dégradé : le parcours reste servi, la météo est signalée absente", () => {
    const reponse = sortie({
      avertissements: ["météo indisponible (Open-Meteo : HTTP 502) — le placement reste valable"],
    });
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
    expect(screen.getByText(/Pas de météo/)).toBeTruthy();
    expect(screen.getByText(/le placement reste valable/)).toBeTruthy();
    // Le parcours n'a pas disparu pour autant.
    expect(screen.getByText("Parcours prêt")).toBeTruthy();
  });
});

describe("une seule proposition au lieu de trois", () => {
  it("n'a pas l'air d'une panne, et porte le motif du cœur", () => {
    const reponse = sortie({
      propositions: 1,
      motif: "les cinq boucles empruntaient plus du quart des mêmes routes",
    });
    render(
      <Propositions
        reponse={reponse}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surElargir={() => undefined}
        surRetour={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Un seul parcours" })).toBeTruthy();
    expect(screen.getByText(/On en voulait trois, et on en propose moins/)).toBeTruthy();
    expect(screen.getByText(/empruntaient plus du quart des mêmes routes/)).toBeTruthy();
    expect(screen.getByText("La seule candidate")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Chercher plus loin/ })).toBeTruthy();
    // Aucun mot d'erreur : ce n'est pas une panne.
    expect(screen.queryByText(/erreur/i)).toBeNull();
  });
});

describe("le serveur ne répond pas du tout", () => {
  it("se distingue d'une panne de l'API et nomme le code", () => {
    render(
      <Echec
        erreur={erreur("serveur_injoignable", "le serveur d'où rouler ne répond pas", 0)}
        reessayer={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Le serveur ne répond pas" })).toBeTruthy();
    expect(screen.getByText(/Code de la panne : serveur_injoignable/)).toBeTruthy();
  });
});

describe("l'écran d'un jour sans séance", () => {
  it("dit « jour de repos » plutôt que de rester vide", () => {
    render(
      <Aujourdhui
        jour="2026-09-17"
        seance={null}
        parcours={null}
        surGenerer={() => undefined}
        surOuvrir={() => undefined}
        surDemander={() => undefined}
        surDeposer={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Rien de prévu" })).toBeTruthy();
    expect(screen.getByText(/ce n'est pas une panne, c'est un jour de repos/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Demander un parcours" })).toBeTruthy();
  });
});

describe("la barrière de dernier recours", () => {
  it("remplace la page blanche par un écran qui dit ce qui s'est passé", () => {
    const Casse = () => {
      throw new Error("champ « etapes » absent de la réponse");
    };
    // React écrit lui-même la trace sur la console : on la tait le temps du
    // test, sinon la sortie laisse croire à un échec.
    const bruit = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <Barriere>
        <Casse />
      </Barriere>,
    );
    bruit.mockRestore();
    expect(screen.getByRole("heading", { name: "Cet écran n'a pas su s'afficher" })).toBeTruthy();
    expect(screen.getByText(/défaut de l'interface, pas de vos données/)).toBeTruthy();
    expect(screen.getByText(/champ « etapes » absent de la réponse/)).toBeTruthy();
  });

  it("laisse passer ce qui s'affiche normalement", () => {
    render(
      <Barriere>
        <p>tout va bien</p>
      </Barriere>,
    );
    expect(screen.getByText("tout va bien")).toBeTruthy();
    expect(screen.queryByText(/n'a pas su s'afficher/)).toBeNull();
  });
});

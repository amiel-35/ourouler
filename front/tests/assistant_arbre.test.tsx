/** L'arbre de l'accueil (`docs/ux/parcours_accueil.md`) : T1 à T5, et les
 * quatre chemins qui comptent.
 *
 * Ce que ces tests protègent :
 *
 * - un profil Intervals qui porte une FTP exploitable fait confirmer, puis
 *   saute T2 à T5 en entier — aucun appel d'aperçu ne doit partir ;
 * - sans compte Intervals, T2 dit honnêtement que l'export n'est pas encore
 *   possible, jamais un faux espoir ;
 * - la question de vitesse au compteur envoie la valeur exacte du milieu de
 *   tranche (pas une vitesse « à plat »), croisée avec le terrain choisi ;
 * - la case « Montagne » dégrade la phrase de confiance du récapitulatif ;
 * - « je ne sais pas » sur les deux questions de T4 tombe sur T5, en
 *   silence — aucun écran intermédiaire, aucun échec possible.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import { Serveur } from "./serveur";
import { PROFIL, apercuFtp, profilIntervals, zones } from "./fixtures";

const ZONES = zones().donnees;

function rendre(table: ConstructorParameters<typeof Serveur>[0]) {
  // **L'ordre compte** (`Serveur.installer` retrouve une route par préfixe,
  // la première qui correspond gagne) : "/api/v1/profil" est un préfixe de
  // toutes les routes plus spécifiques du profil (`/profil/intervals`,
  // `/profil/ftp/apercu`…) — il doit donc rester en dernier, sans quoi il
  // les avale toutes avant qu'elles ne soient jamais atteintes.
  const serveur = new Serveur({
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    ...table,
    "/api/v1/profil": { charge: PROFIL },
  });
  serveur.installer();
  render(
    <Assistant
      profil={PROFIL.donnees}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surFin={() => undefined}
      vers="Aujourd'hui"
      surRetour={() => undefined}
    />,
  );
  return { serveur, utilisateur: userEvent.setup() };
}

/** Bienvenue → identité (déjà remplie par la fixture) → départ, gardé tel quel. */
async function versEntonnoir(utilisateur: ReturnType<typeof userEvent.setup>) {
  await utilisateur.click(screen.getByRole("button", { name: "Commencer" }));
  await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));
  await utilisateur.click(screen.getByRole("button", { name: "Garder ce départ" }));
}

describe("T1 — Intervals confirme une FTP", () => {
  it("va directement au récapitulatif : T2 à T5 sont sautés", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/intervals": { charge: profilIntervals({ ftp_w: 240, masse_kg: 68.5 }) },
    });
    await versEntonnoir(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Oui" }));
    await utilisateur.type(screen.getByLabelText("Votre clé"), "cle-inventee");
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText(/FTP 240 W, poids 68,5 kg/)).toBeTruthy();
    await utilisateur.click(screen.getByRole("button", { name: "Oui" }));

    // Direct au vélo, jamais par l'export, la FTP déclarée ou le vécu.
    expect(await screen.findByText("Avec quoi roulez-vous ?")).toBeTruthy();
    expect(screen.queryByText(/pas encore proposé par ourouler/)).toBeNull();
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(screen.getByText("Estimation confirmée depuis votre profil Intervals.")).toBeTruthy();
    expect(serveur.vers("/api/v1/profil/ftp/apercu")).toEqual([]);
    expect(serveur.vers("/api/v1/profil/ftp/generique")).toEqual([]);

    const patchs = serveur
      .vers("/api/v1/profil")
      .filter((r) => r.methode === "PATCH")
      .map((r) => (r.corps as { cycliste?: Record<string, unknown> }).cycliste)
      .filter((c): c is Record<string, unknown> => c !== undefined);
    expect(patchs).toContainEqual({ ftp_w: 240, masse_kg: 68.5 });
  });
});

describe("T2 — pas de compte Intervals", () => {
  it("dit honnêtement que l'export n'est pas encore proposé, sans faux espoir", async () => {
    const { utilisateur } = rendre({});
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" }));

    const message = await screen.findByText(/pas encore proposé par ourouler/);
    expect(message).toBeTruthy();
    expect(screen.queryByText(/import.*en cours/i)).toBeNull();
  });
});

describe("T4 — le vécu, en choix", () => {
  async function versT4(utilisateur: ReturnType<typeof userEvent.setup>) {
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" })); // T1 → T2
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // T2 → poids
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // poids (déjà rempli) → vélo
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // vélo (déjà rempli) → T3
    await utilisateur.click(screen.getByRole("button", { name: "Je ne sais pas" })); // T3 → T4 vitesse
  }

  it("vitesse + terrain Vallonné : envoie vitesse_kmh et denivele_m_par_km corrects", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/apercu": { charge: apercuFtp(187) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "24 à 26 km/h" }));
    await utilisateur.click(screen.getByRole("button", { name: "Vallonné — 250 à 600 m sur 50 km" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/apercu").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")[0].corps).toEqual({
      vitesse_kmh: 25,
      denivele_m_par_km: 10,
      velo: "Le vert",
    });

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(
      screen.getByText("Estimation à partir de ce que vous nous avez dit de vos sorties."),
    ).toBeTruthy();
  });

  it("terrain Montagne : dégrade la phrase de confiance du récapitulatif", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/apercu": { charge: apercuFtp(203) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Plus de 30 km/h" }));
    await utilisateur.click(screen.getByRole("button", { name: "Montagne — plus de 1000 m sur 50 km" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/apercu").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")[0].corps).toEqual({
      vitesse_kmh: 31,
      denivele_m_par_km: 30,
      velo: "Le vert",
    });

    expect(
      await screen.findByText(
        "Estimation à partir de ce que vous nous avez dit — en montagne, cette estimation est moins fiable qu'ailleurs.",
      ),
    ).toBeTruthy();
  });

  it("« je ne sais pas trop » sur la vitesse tombe directement sur T5, sans écran de terrain", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/generique": { charge: apercuFtp(165) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Je ne sais pas trop" }));

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(screen.queryByText("Et le terrain ?")).toBeNull();
    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/generique").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")).toEqual([]);
    expect(
      screen.getByText("Estimation générique, à partir de votre poids et de votre vélo seuls."),
    ).toBeTruthy();
  });
});

/** Q44 — un seul réglage de direction à la fois, et le vent toujours montré.
 *
 * Deux défauts sont protégés ici, et ils ne se ressemblent pas.
 *
 * 1. **Deux sélecteurs fixaient le même azimut** sans que rien ne dise lequel
 *    gagnait. Ils s'excluent maintenant par la forme, et l'API refuse la
 *    contradiction : le test qui compte est celui qui regarde **ce qui part
 *    sur le réseau**, parce qu'un reste d'un mode qu'on a quitté suffirait à
 *    déclencher un 400 sans que l'écran ait l'air faux.
 *
 * 2. **L'écran ne disait pas d'où vient le vent**, alors qu'il demandait une
 *    direction. Il le dit dans les deux modes — et pour le vent latéral, il
 *    montre **les deux azimuts opposés**, pas un seul. C'est la moitié de Q44
 *    qu'un champ scalaire, ou un front pressé, aurait silencieusement réduite.
 */

import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Demander, demandeInitiale } from "../src/ecrans/Demander";
import type { Demande } from "../src/ecrans/Demander";
import type { Enveloppe, VentDepart } from "../src/api/types";
import { PROFIL, zones } from "./fixtures";
import { Serveur } from "./serveur";

/** Le vent au départ tel que l'API le rend — vent de sud-ouest, donc de 225°. */
function ventDepart(surcharge?: Partial<VentDepart>): Enveloppe<VentDepart> {
  return {
    proprietaire: "essai",
    donnees: {
      jour: "2026-09-19",
      depart: "2026-09-19T15:00:00+02:00",
      posee: true,
      motif: null,
      vent_kmh: 22,
      vent_depuis_deg: 225,
      vent_depuis_nom: "SO",
      seuil_kmh: 8,
      horizon_jours: 3,
      choix: ["peu-importe", "retour-dos", "depart-dos", "travers"],
      azimuts_par_choix: {
        "peu-importe": [],
        "retour-dos": [{ azimut_deg: 225, nom: "SO" }],
        "depart-dos": [{ azimut_deg: 45, nom: "NE" }],
        // Les deux flancs, opposés à 180° — le cœur de Q44.
        travers: [
          { azimut_deg: 315, nom: "NO" },
          { azimut_deg: 135, nom: "SE" },
        ],
      },
      ...surcharge,
    },
  } as Enveloppe<VentDepart>;
}

/** Rend l'écran de demande, serveur factice installé, et suit la demande. */
function poser(options?: { vent?: Enveloppe<VentDepart>; demande?: Partial<Demande> }) {
  const serveur = new Serveur({
    "/api/v1/vent-depart": { charge: options?.vent ?? ventDepart() },
  });
  serveur.installer();
  let demande: Demande = { ...demandeInitiale(), ...options?.demande };

  /** L'écran est piloté par son parent : on rejoue ce que fait `App`.
   *
   * `rerender` et non un second `render` — celui-ci **ajouterait** un écran à
   * côté du premier, et les deux sélecteurs paraîtraient coexister alors que
   * c'est le test qui les aurait dupliqués.
   */
  function ecran() {
    return (
      <Demander
        profil={PROFIL.donnees}
        zones={zones().donnees}
        dureeSeance_s={7200}
        nomSeance="Sortie fabriquée"
        demande={demande}
        budget={null}
        surDemande={(suivante) => {
          demande = suivante;
          rejouer(ecran());
        }}
        surChercher={() => undefined}
      />
    );
  }
  const { rerender } = render(ecran());
  function rejouer(noeud: ReactElement) {
    rerender(noeud);
  }
  return {
    serveur,
    lire: () => demande,
  };
}

const utilisateur = userEvent.setup();

describe("le premier choix de Q44", () => {
  it("n'affiche jamais les deux sélecteurs de direction en même temps", async () => {
    poser();
    // Au départ, « peu importe » : ni cardinaux, ni préférences de vent.
    expect(screen.queryByRole("button", { name: "NE" })).toBeNull();
    expect(screen.queryByText("Vent latéral")).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));
    expect(screen.getByRole("button", { name: "NE" })).toBeTruthy();
    expect(screen.queryByText("Vent latéral")).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    expect(screen.queryByRole("button", { name: "NE" })).toBeNull();
    expect(screen.getByText("Vent latéral")).toBeTruthy();
  });

  it("propose les trois préférences que le mainteneur a nommées, et rien d'autre", async () => {
    poser();
    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    expect(screen.getByRole("button", { name: "Vent dans le dos au départ" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vent dans le dos au retour" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vent latéral" })).toBeTruthy();
    // « Peu importe » vit au premier choix, pas parmi les préférences : il n'y
    // est pas une quatrième façon de s'orienter, c'est l'absence de demande.
    expect(screen.queryByRole("button", { name: "Peu importe (vent)" })).toBeNull();
  });

  it("ne laisse jamais coexister une direction et une orientation contraignante", async () => {
    // Le test qui protège du 400 : l'état interne peut porter les deux champs
    // (on a changé d'avis), ce qui part sur le réseau ne le doit pas.
    const { lire } = poser({ demande: { direction: "N", vent: "retour-dos" } });

    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));
    expect(lire().modeDirection).toBe("direction");

    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    const finale = lire();
    expect(finale.modeDirection).toBe("vent");
    // `modeDirection` fait seule foi : c'est elle que `App.chercher` lit pour
    // n'envoyer qu'un seul des deux champs.
    expect(["depart-dos", "retour-dos", "travers"]).toContain(finale.vent);
  });
});

describe("le vent au départ", () => {
  it("s'affiche alors qu'aucune direction n'est encore choisie", async () => {
    poser();
    await waitFor(() => expect(screen.getByText(/Vent de sud-ouest/)).toBeTruthy());
    expect(screen.getByText(/22 km\/h/)).toBeTruthy();
  });

  it("s'affiche aussi quand le cycliste choisit sa direction lui-même", async () => {
    poser();
    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));
    await waitFor(() => expect(screen.getByText(/Vent de sud-ouest/)).toBeTruthy());
  });

  it("vient de l'API et n'est jamais recalculé ici", async () => {
    // Un vent d'est : si l'écran déduisait quoi que ce soit, il resterait au
    // sud-ouest de la fixture précédente ou inventerait un nom.
    poser({
      vent: ventDepart({
        vent_depuis_deg: 90,
        vent_depuis_nom: "E",
        vent_kmh: 31,
        azimuts_par_choix: {
          "peu-importe": [],
          "retour-dos": [{ azimut_deg: 90, nom: "E" }],
          "depart-dos": [{ azimut_deg: 270, nom: "O" }],
          travers: [
            { azimut_deg: 180, nom: "S" },
            { azimut_deg: 0, nom: "N" },
          ],
        },
      }),
    });
    await waitFor(() => expect(screen.getByText(/Vent d'est|Vent de est/)).toBeTruthy());
    expect(screen.getByText(/31 km\/h/)).toBeTruthy();
    expect(screen.queryByText(/sud-ouest/)).toBeNull();
  });
});

describe("le vent latéral ouvre deux azimuts", () => {
  it("les montre tous les deux, pas seulement le premier", async () => {
    poser();
    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    // 315° et 135°, les deux flancs d'un vent de 225°.
    const ligne = await screen.findByText(/Vent latéral\s*:/);
    expect(ligne.textContent).toContain("NO");
    expect(ligne.textContent).toContain("315");
    expect(ligne.textContent).toContain("SE");
    expect(ligne.textContent).toContain("135");
  });

  it("n'en montre qu'un pour les deux préférences qui n'en fixent qu'un", async () => {
    poser();
    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    const retour = await screen.findByText(/Vent dans le dos au retour\s*:/);
    expect(retour.textContent).toContain("225");
    expect(retour.textContent).not.toContain(" et ");
  });
});

describe("quand la question du vent ne se pose pas", () => {
  it("affiche le motif au lieu d'inventer un vent, et ferme le mode", async () => {
    poser({
      vent: ventDepart({
        posee: false,
        motif:
          "2 km/h au départ, sous les 8 km/h à partir desquels on sent le vent sur le visage",
        vent_kmh: 2,
        azimuts_par_choix: {
          "peu-importe": [],
          "retour-dos": [],
          "depart-dos": [],
          travers: [],
        },
      }),
    });
    await waitFor(() => expect(screen.getByText(/sous les 8 km\/h/)).toBeTruthy());
    // Aucun vent affirmé, et « selon le vent » n'est pas proposable.
    expect(screen.queryByText(/Vent de sud-ouest/)).toBeNull();
    const selonLeVent = screen.getByRole("button", { name: "Selon le vent" });
    expect((selonLeVent as HTMLButtonElement).disabled).toBe(true);
  });
});

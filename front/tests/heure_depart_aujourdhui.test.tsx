/** Backlog « Séance du jour à l'heure réelle » (2026-09-26) — QP3, sur les
 * deux écrans qui posent `demande.heure_depart` : « Aujourd'hui » et
 * « Demander ». Voir `tests/heure_depart_par_defaut.test.ts` pour la
 * fonction pure ; ici, l'affichage, l'édition en un geste, et l'envoi à la
 * recherche.
 *
 * L'horloge système est figée avec `vi.setSystemTime` — pas pour dépendre de
 * l'heure de la machine, mais pour la contrôler : `demandeInitiale()` (donc
 * `App.tsx`) prend l'horloge par défaut (`() => new Date()`), figée ici sur
 * une heure connue.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, meteo, sortie, zones } from "./fixtures";

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/": { charge: SEANCE },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/meteo": { charge: meteo() },
    "/api/v1/sorties": { charge: sortie() },
  });
  serveur.installer();
  return serveur;
}

/** Une heure de bureau quelconque, un après-midi — le jour reste le vrai
 * "aujourd'hui" (seules les heures/minutes sont fixées), pour que
 * `demande.jour === aujourdhui()` sans dépendre de la date du jour où le
 * test tourne. */
function figerHeure(heures: number, minutes: number) {
  const maintenant = new Date();
  maintenant.setHours(heures, minutes, 0, 0);
  vi.setSystemTime(maintenant);
}

describe("« Aujourd'hui » à l'heure réelle", () => {
  afterEach(() => vi.useRealTimers());

  it("affiche l'heure courante arrondie au quart d'heure suivant, pas 09:00 en dur", async () => {
    figerHeure(14, 37);
    installer();
    render(<App />);

    const champ = (await screen.findByLabelText(/Départ à/)) as HTMLInputElement;
    expect(champ.value).toBe("14:45");
  });

  it("l'heure affichée est modifiable en un geste, et c'est elle qui part à la recherche", async () => {
    figerHeure(14, 37);
    const serveur = installer();
    const utilisateur = userEvent.setup({ delay: null });
    render(<App />);

    const champ = (await screen.findByLabelText(/Départ à/)) as HTMLInputElement;
    expect(champ.value).toBe("14:45");

    await utilisateur.clear(champ);
    await utilisateur.type(champ, "16:30");
    expect(champ.value).toBe("16:30");

    await utilisateur.click(screen.getByRole("button", { name: "Chercher le parcours du jour" }));

    await waitFor(() => expect(serveur.vers("/api/v1/sorties")).toHaveLength(1));
    const requete = serveur.vers("/api/v1/sorties")[0];
    const corps = requete.corps as { heure_depart: string };
    expect(corps.heure_depart.endsWith("T16:30")).toBe(true);
  });
});

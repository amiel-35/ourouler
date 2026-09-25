/** Correctif 0.9.6 — « Aujourd'hui » ne se redemandait pas après l'assistant.
 *
 * Défaut constaté en prod le 25/09/2026 : un nouvel invité ouvre l'appli,
 * « Aujourd'hui » échoue en 409 `intervals_absent` (normal, pas de clé),
 * puis il enregistre sa clé intervals.icu — depuis l'assistant ou depuis
 * Réglages, `surProfil` est le même callback des deux côtés (`App.tsx`).
 * Revenu sur « Aujourd'hui », l'écran affichait TOUJOURS « Votre compte
 * intervals.icu n'est pas encore relié » : `seanceDuJour` et `semaine` ne
 * dépendaient que de `jour`, jamais de l'état de branchement du profil
 * courant. Un rechargement de page réglait tout — signe que la donnée
 * était bonne, seule la ressource n'était jamais redemandée.
 *
 * Passe par Réglages plutôt que par l'arbre complet de l'assistant : les
 * deux écrans appellent le même `surProfil={setProfilCourant}` (`App.tsx`),
 * donc l'un vaut l'autre pour ce défaut-ci, et Réglages est le chemin le
 * plus court pour l'atteindre.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, zones } from "./fixtures";
import type { Simple } from "../src/api/types";
import type { Profil } from "../src/api/types";

const MESSAGE_NON_RELIE = "Votre compte intervals.icu n'est pas encore relié.";

const PROFIL_SANS_INTERVALS: Simple<Profil> = {
  ...PROFIL,
  donnees: {
    ...PROFIL.donnees,
    // Comme un compte tout juste créé : l'assistant n'a pas encore de quoi
    // recommander, on ne veut pas être renvoyé dessus malgré nous ici — le
    // scénario testé part volontairement de « Aujourd'hui ».
    assistant_recommande: false,
    services: {
      ...PROFIL.donnees.services,
      intervals: { renseigne: false, athlete_id: "" },
    },
  },
};

const PROFIL_AVEC_INTERVALS: Simple<Profil> = {
  ...PROFIL_SANS_INTERVALS,
  donnees: {
    ...PROFIL_SANS_INTERVALS.donnees,
    services: {
      ...PROFIL_SANS_INTERVALS.donnees.services,
      intervals: { renseigne: true, athlete_id: "iFICTIF" },
    },
  },
};

function installer() {
  let branche = false;
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": (requete) => {
      if (requete.methode === "PATCH") {
        branche = true;
        return { charge: PROFIL_AVEC_INTERVALS };
      }
      return { charge: branche ? PROFIL_AVEC_INTERVALS : PROFIL_SANS_INTERVALS };
    },
    // Le motif le plus spécifique d'abord (voir `tests/serveur.ts` : le
    // premier préfixe qui matche gagne) — sinon la requête de la séance du
    // jour retomberait sur la réponse de la semaine.
    "/api/v1/seances/": () =>
      branche ? { charge: SEANCE } : panne("intervals_absent", "Intervals.icu : clé absente", 409),
    "/api/v1/seances": { charge: SEMAINE },
  });
  serveur.installer();
  return serveur;
}

describe("« Aujourd'hui » une fois Intervals branché", () => {
  it("redemande la séance du jour et n'affiche plus le message « non relié »", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    await screen.findByText(MESSAGE_NON_RELIE);
    expect(serveur.vers("/api/v1/seances/")).toHaveLength(1);

    // Branchement depuis Réglages — même callback `surProfil` que
    // l'assistant, donc représentatif du même défaut.
    await utilisateur.click(screen.getByRole("button", { name: "Réglages" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Non branché" }));
    await utilisateur.type(
      screen.getByLabelText("Votre clé intervals.icu"),
      "cle-inventee-de-test",
    );
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer la clé" }));
    await screen.findByText("Clé vérifiée auprès d'intervals.icu : c'est branché.");

    // Retour sur « Aujourd'hui » : la ressource doit s'être redemandée
    // d'elle-même, sans rechargement de page.
    await utilisateur.click(screen.getByRole("button", { name: "Aujourd'hui" }));

    await waitFor(() => expect(serveur.vers("/api/v1/seances/")).toHaveLength(2));
    await screen.findByText(SEANCE.donnees.nom);
    expect(screen.queryByText(MESSAGE_NON_RELIE)).toBeNull();
  });
});

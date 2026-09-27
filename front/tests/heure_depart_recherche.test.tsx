/** Backlog « Séance du jour à l'heure réelle » (2026-09-26) — QP3, relu à
 * charge le 27/09/2026 : un premier correctif confondait heure **par
 * défaut** et heure **saisie**. Trois défauts trouvés en relecture, avec la
 * même cause :
 *
 * 1. Cliquer « Demain » (Demander) ou « Générer le parcours » d'un autre
 *    jour depuis Ma semaine reprenait l'heure par défaut du jour courant
 *    (ex. 14:45) au lieu de 9 h, parce que `heure_depart` avait été résolue
 *    une fois pour toutes dans l'état.
 * 2. Cliquer « Aujourd'hui » écrasait une heure saisie par le cycliste.
 * 3. Un écran resté ouvert depuis 9 h cherchait encore à 09:15 à 14 h,
 *    parce que la valeur par défaut avait été figée à l'ouverture.
 *
 * Le correctif : `demande.heure_depart` est `string | null` — `null` = « le
 * défaut du jour », résolu à chaque affichage et à chaque recherche par
 * `heureDepartResolue` (`ecrans/demander/demande.ts`), jamais mémorisé ;
 * une chaîne = saisie du cycliste, qui ne bouge plus tant qu'il n'a pas
 * retapé le champ. Ces tests vérifient ce qui **part réellement** à l'API
 * (`POST /sorties`), pas seulement ce qui s'affiche.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, boucle, meteo, sortie, ventDepart, zones } from "./fixtures";

function installer() {
  const serveur = new Serveur({
    "/api/v1/systeme": { charge: SYSTEME },
    "/api/v1/profil/zones": { charge: zones() },
    "/api/v1/profil": { charge: PROFIL },
    "/api/v1/seances/": { charge: SEANCE },
    "/api/v1/seances": { charge: SEMAINE },
    "/api/v1/meteo": { charge: meteo() },
    "/api/v1/vent-depart": { charge: ventDepart() },
    "/api/v1/sorties": { charge: sortie() },
    "/api/v1/boucles": { charge: boucle() },
  });
  serveur.installer();
  return serveur;
}

/** L'heure de départ du dernier envoi reçu sur `chemin` ("HH:MM"). */
async function heureEnvoyee(serveur: Serveur, chemin: string, attendu = 1): Promise<string> {
  await waitFor(() => expect(serveur.vers(chemin)).toHaveLength(attendu));
  const envois = serveur.vers(chemin);
  const corps = envois[envois.length - 1].corps as { heure_depart: string };
  return corps.heure_depart.split("T")[1];
}

/** Le bouton « Aujourd'hui »/« Demain »/« Après-demain » du sélecteur
 * « Quand » de Demander.tsx — jamais celui de la barre d'onglets, qui porte
 * le même nom accessible. */
function boutonQuand(nom: string): HTMLElement {
  return within(document.getElementById("quand")!).getByRole("button", { name: nom });
}

/** Fige l'horloge système sur l'heure donnée, le jour réel où le test
 * tourne (seules les heures/minutes sont contrôlées) — nécessaire pour que
 * `demande.jour === aujourdhui()` sans dépendre de la date du jour du test. */
function figerHeure(heures: number, minutes: number) {
  const maintenant = new Date();
  maintenant.setHours(heures, minutes, 0, 0);
  vi.setSystemTime(maintenant);
}

describe("ce qui part réellement à la recherche (POST /sorties)", () => {
  afterEach(() => vi.useRealTimers());

  it("par défaut, choisir « Demain » envoie 09:00 — sans avoir forcé l'état initial", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    // Aucune manipulation de `demande` avant ce geste : l'état initial est
    // celui de `demandeInitiale()` tel quel (`heure_depart: null`).
    //
    // Endurance Z2, pas « Ma séance » : le bouton « Chercher » reste actif
    // sans séance connue pour ce jour-là (voir `Demander.tsx`,
    // `disabled={demande.mode === "seance" && dureeSeance_s === null}`) —
    // la fixture de semaine n'a pas de séance pour « demain », et ce n'est
    // pas le sujet de ce test.
    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(screen.getByRole("button", { name: "Endurance Z2" }));
    await utilisateur.click(boutonQuand("Demain"));
    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));

    expect(await heureEnvoyee(serveur, "/api/v1/boucles")).toBe("09:00");
  });

  it("une heure saisie survit à un aller-retour « Demain » puis « Aujourd'hui », et c'est elle qui part", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    const champ = (await screen.findByLabelText(/Départ à/)) as HTMLInputElement;
    await utilisateur.clear(champ);
    await utilisateur.type(champ, "16:30");
    expect(champ.value).toBe("16:30");

    await utilisateur.click(boutonQuand("Demain"));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("16:30");

    // Le clic sur « Aujourd'hui » ne doit plus écraser la saisie — c'était
    // le second défaut trouvé en relecture.
    await utilisateur.click(boutonQuand("Aujourd'hui"));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("16:30");

    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));
    expect(await heureEnvoyee(serveur, "/api/v1/sorties")).toBe("16:30");
  });

  it("un écran ouvert à 9 h et relancé à 14:37 envoie 14:45, pas l'heure calculée à l'ouverture", async () => {
    figerHeure(9, 0);
    const serveur = installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    // Ouvert à 9 h : la valeur affichée par défaut est 09:00.
    expect((await screen.findByLabelText(/Départ à/)) as HTMLInputElement).toHaveProperty(
      "value",
      "09:00",
    );

    // L'horloge avance sans qu'on retouche l'écran — exactement le cas
    // trouvé en relecture (un onglet resté ouvert).
    figerHeure(14, 37);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher le parcours du jour" }));

    expect(await heureEnvoyee(serveur, "/api/v1/sorties")).toBe("14:45");
  });

  it("« Générer le parcours » d'un autre jour depuis Ma semaine envoie 09:00", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup();
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Ma semaine" }));
    const blocs = await screen.findAllByRole("button", { name: "Générer le parcours" });
    // Le dernier bloc de la semaine de fixture (2026-09-21) n'est jamais le
    // jour réel où ce test tourne.
    await utilisateur.click(blocs[blocs.length - 1]);

    expect(await heureEnvoyee(serveur, "/api/v1/sorties")).toBe("09:00");
  });
});

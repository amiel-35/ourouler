/** La frontière avec l'API : ce qui entre, et ce qui en sort.
 *
 * Le test de la séance absente est une **régression trouvée en vrai** : sur
 * la configuration du mainteneur, un jour sans séance planifiée fait rendre
 * `{jour, seance: null}` au lieu de la séance, et l'écran « Aujourd'hui »
 * plantait en lisant `etapes` sur cet objet-là. La forme est normalisée à la
 * frontière, et c'est ici qu'on le vérifie.
 */

import { describe, expect, it } from "vitest";
import { api, ErreurApi, reessayable } from "../src/api/client";
import { panne, Serveur } from "./serveur";
import { SEANCE } from "./fixtures";

describe("la séance d'un jour", () => {
  it("rend la séance quand il y en a une", async () => {
    new Serveur({ "/api/v1/seances/": { charge: SEANCE } }).installer();
    const reponse = await api.seance("2026-09-16");
    expect(reponse.donnees?.nom).toBe(SEANCE.donnees.nom);
    expect(reponse.donnees?.etapes).toHaveLength(4);
  });

  it("rend null quand le jour n'en porte pas, sans planter", async () => {
    new Serveur({
      "/api/v1/seances/": {
        charge: {
          proprietaire: "essai",
          donnees: { jour: "2026-09-17", seance: null },
          avertissements: [],
          duree_ms: 12,
          budget: SEANCE.budget,
        },
      },
    }).installer();
    const reponse = await api.seance("2026-09-17");
    expect(reponse.donnees).toBeNull();
    expect(reponse.budget.operation).toBe("seance");
  });
});

describe("les pannes", () => {
  it("portent le code du contrat, pas seulement un message", async () => {
    new Serveur({
      "/api/v1/profil": panne("intervals_refuse", "Intervals.icu : HTTP 403", 502),
    }).installer();
    await expect(api.profil()).rejects.toMatchObject({
      code: "intervals_refuse",
      statut: 502,
    });
  });

  it("distinguent un serveur muet d'une API qui répond mal", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;
    const erreur = await api.systeme().catch((e) => e as ErreurApi);
    expect(erreur).toBeInstanceOf(ErreurApi);
    expect((erreur as ErreurApi).code).toBe("serveur_injoignable");
    expect(reessayable(erreur as ErreurApi)).toBe(true);
  });

  it("ne proposent pas de réessayer quand ça ne sert à rien", () => {
    const refus = new ErreurApi(
      { code: "format_non_lu", message: "un .FIT", service: null, details: {} },
      422,
    );
    expect(reessayable(refus)).toBe(false);
  });
});

describe("l'aperçu des zones", () => {
  it("n'envoie que l'entrée qu'on lui donne", async () => {
    const serveur = new Serveur({
      "/api/v1/profil/zones/apercu": { charge: { proprietaire: "essai", donnees: {} } },
    });
    serveur.installer();
    await api.apercuZones({ vitesse_a_plat_kmh: 27.4 });
    const corps = serveur.requetes[0].corps as Record<string, unknown>;
    expect(corps).toEqual({ vitesse_a_plat_kmh: 27.4 });
  });
});

/** La frontière avec l'API : ce qui entre, et ce qui en sort.
 *
 * Le test de la séance absente est une **régression trouvée en vrai** : sur
 * la configuration du mainteneur, un jour sans séance planifiée fait rendre
 * `{jour, seance: null}` au lieu de la séance, et l'écran « Aujourd'hui »
 * plantait en lisant `etapes` sur cet objet-là. La forme est normalisée à la
 * frontière, et c'est ici qu'on le vérifie.
 */

import { describe, expect, it, vi } from "vitest";
import {
  api,
  DELAI_CALCUL_MS,
  DELAI_MS,
  ErreurApi,
  reessayable,
  serveurMuet,
} from "../src/api/client";
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

  /**
   * **Le défaut trouvé en faisant tourner le produit, le 17/09/2026.**
   *
   * Lancer le front sans API derrière — ou avec l'API sur un autre port — ne
   * fait pas jeter `fetch` : le proxy de développement de Vite répond à sa
   * place, `500 text/plain`, corps vide. Le test ci-dessus ne couvrait donc
   * pas le cas le plus courant, et l'écran affichait « le serveur a répondu
   * 500 sans rien expliquer » — ni cause, ni geste, ni bouton.
   *
   * Le critère de reconnaissance est le contrat : `api_contrat.md` promet du
   * JSON pour **toute** réponse de l'API, pannes comprises.
   */
  it("reconnaissent le proxy dont la cible est éteinte, et non une panne de l'API", async () => {
    new Serveur({ "/api/v1/systeme": { statut: 500, texte: "" } }).installer();
    const erreur = await api.systeme().catch((e) => e as ErreurApi);
    expect((erreur as ErreurApi).code).toBe("serveur_injoignable");
    expect(serveurMuet(erreur as ErreurApi)).toBe(true);
    expect(reessayable(erreur as ErreurApi)).toBe(true);
    expect((erreur as ErreurApi).message).not.toMatch(/sans rien expliquer/);
  });

  it("laissent passer un vrai 500 de l'API, qui porte son enveloppe", async () => {
    new Serveur({
      "/api/v1/systeme": panne("configuration_invalide", "le TOML ne charge pas", 500),
    }).installer();
    const erreur = await api.systeme().catch((e) => e as ErreurApi);
    expect((erreur as ErreurApi).code).toBe("configuration_invalide");
    expect(serveurMuet(erreur as ErreurApi)).toBe(false);
  });

  it("nomment autrement une page servie à la place de l'API", async () => {
    new Serveur({
      "/api/v1/systeme": { statut: 200, texte: "<!doctype html><title>où rouler</title>" },
    }).installer();
    const erreur = await api.systeme().catch((e) => e as ErreurApi);
    expect((erreur as ErreurApi).code).toBe("reponse_illisible");
  });

  it("comptent une passerelle sans amont comme un serveur muet, même en JSON", async () => {
    new Serveur({
      "/api/v1/systeme": { statut: 503, charge: { detail: "Service Unavailable" } },
    }).installer();
    const erreur = await api.systeme().catch((e) => e as ErreurApi);
    expect((erreur as ErreurApi).code).toBe("serveur_injoignable");
  });

  it("abandonnent quand le serveur ne rend jamais la main", async () => {
    vi.useFakeTimers();
    globalThis.fetch = ((_entree: RequestInfo | URL, options?: RequestInit) =>
      new Promise((_resoudre, rejeter) => {
        options?.signal?.addEventListener("abort", () =>
          rejeter(new DOMException("abandon", "AbortError")),
        );
      })) as typeof fetch;
    const attendu = api.systeme().catch((e) => e as ErreurApi);
    await vi.advanceTimersByTimeAsync(DELAI_MS + 1000);
    const erreur = await attendu;
    vi.useRealTimers();
    expect((erreur as ErreurApi).code).toBe("delai_depasse");
    expect((erreur as ErreurApi).message).toMatch(/30 secondes/);
  });

  it("laissent une génération durer bien plus longtemps qu'une lecture", async () => {
    expect(DELAI_CALCUL_MS).toBeGreaterThan(DELAI_MS);
    vi.useFakeTimers();
    let abandonnee = false;
    globalThis.fetch = ((_entree: RequestInfo | URL, options?: RequestInit) =>
      new Promise((_resoudre, rejeter) => {
        options?.signal?.addEventListener("abort", () => {
          abandonnee = true;
          rejeter(new DOMException("abandon", "AbortError"));
        });
      })) as typeof fetch;
    const attendu = api
      .boucle({ distance_km: 40, direction: "N" })
      .catch((e) => e as ErreurApi);
    await vi.advanceTimersByTimeAsync(DELAI_MS + 1000);
    expect(abandonnee).toBe(false);
    await vi.advanceTimersByTimeAsync(DELAI_CALCUL_MS);
    await attendu;
    vi.useRealTimers();
    expect(abandonnee).toBe(true);
  });

  it("ne transforment pas une annulation de l'appelant en panne", async () => {
    const controleur = new AbortController();
    globalThis.fetch = ((_entree: RequestInfo | URL, options?: RequestInit) =>
      new Promise((_resoudre, rejeter) => {
        options?.signal?.addEventListener("abort", () =>
          rejeter(new DOMException("abandon", "AbortError")),
        );
      })) as typeof fetch;
    const attendu = api
      .boucle({ distance_km: 40, direction: "N" }, controleur.signal)
      .catch((e) => e);
    controleur.abort();
    const cause = await attendu;
    expect(cause).not.toBeInstanceOf(ErreurApi);
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

/** Ce que chaque test trouve en place, et ce qu'aucun test n'a le droit de faire.
 *
 * **Aucun réseau** (règle absolue 3) : `fetch` est remplacé par un serveur
 * factice, et toute requête vers une route qu'un test n'a pas prévue fait
 * échouer le test au lieu de partir sur Internet.
 */

import { afterEach, beforeEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom, sous ce Node, ne fournit pas `window.localStorage` du tout (pas
// « refusé », absent — `typeof window.localStorage === "undefined"`). Un
// polyfill minimal, posé une fois : sans lui, un test qui vérifie qu'une
// mémoire survit à un remontage de composant (`etat/memoire.ts`) ne peut
// rien prouver, puisque l'écriture échouerait en silence (`try/catch`,
// exactement comme en navigation privée réelle) et la lecture aussi.
if (typeof window !== "undefined" && !window.localStorage) {
  const magasin = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    value: {
      getItem: (cle: string) => (magasin.has(cle) ? magasin.get(cle)! : null),
      setItem: (cle: string, valeur: string) => void magasin.set(cle, String(valeur)),
      removeItem: (cle: string) => void magasin.delete(cle),
      clear: () => void magasin.clear(),
      key: (index: number) => Array.from(magasin.keys())[index] ?? null,
      get length() {
        return magasin.size;
      },
    },
    configurable: true,
  });
}

beforeEach(() => {
  globalThis.fetch = (async (entree: RequestInfo | URL) => {
    throw new Error(
      `réseau interdit dans les tests : ${String(entree)} — installer un serveur factice`,
    );
  }) as typeof fetch;
  try {
    window.localStorage.clear();
  } catch {
    /* pas de stockage : les écrans doivent marcher quand même */
  }
});

afterEach(() => {
  cleanup();
});

expect.extend({});

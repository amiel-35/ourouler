/** Ce que chaque test trouve en place, et ce qu'aucun test n'a le droit de faire.
 *
 * **Aucun réseau** (règle absolue 3) : `fetch` est remplacé par un serveur
 * factice, et toute requête vers une route qu'un test n'a pas prévue fait
 * échouer le test au lieu de partir sur Internet.
 */

import { afterEach, beforeEach, expect } from "vitest";
import { cleanup } from "@testing-library/react";

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

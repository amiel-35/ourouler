/** Lot 14 — un seul point d'accès au réseau.
 *
 * `docs/ouverture_plan.md` §7 : « Seul `api/client.ts` appelle `fetch`… ».
 * N'importe quel autre fichier qui parlerait directement au réseau
 * contournerait la frontière que `api/client.ts` est censée être — le
 * contrat des réponses, les trois codes fabriqués par le front
 * (`serveur_injoignable`, `delai_depasse`, `reponse_illisible`) n'y seraient
 * plus garantis. Ce test relit les sources, pas une convention qu'on espère
 * tenue.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const RACINE_SRC = join(__dirname, "..", "src");
const FICHIER_AUTORISE = join("src", "api", "client.ts");

function fichiersSources(dossier: string): string[] {
  const resultats: string[] = [];
  for (const entree of readdirSync(dossier, { withFileTypes: true })) {
    const chemin = join(dossier, entree.name);
    if (entree.isDirectory()) {
      resultats.push(...fichiersSources(chemin));
    } else if (/\.(ts|tsx)$/.test(entree.name)) {
      resultats.push(chemin);
    }
  }
  return resultats;
}

describe("un seul point d'accès au réseau (docs/ouverture_plan.md §7)", () => {
  // Le trafic applicatif seulement : les tuiles de carte, chargées par Leaflet
  // (`composants/Carte.tsx`), sont l'exception documentée dans
  // docs/services_externes.md.
  it("aucun fichier hors api/client.ts n'appelle fetch(...) ou XMLHttpRequest", () => {
    const fautifs: string[] = [];
    for (const chemin of fichiersSources(RACINE_SRC)) {
      const chemin_relatif = relative(join(__dirname, ".."), chemin);
      if (chemin_relatif === FICHIER_AUTORISE) continue;
      const contenu = readFileSync(chemin, "utf-8");
      if (/\bfetch\(/.test(contenu) || /\bXMLHttpRequest\b/.test(contenu)) {
        fautifs.push(chemin_relatif);
      }
    }
    expect(fautifs).toEqual([]);
  });
});

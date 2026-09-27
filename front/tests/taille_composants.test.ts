// @vitest-environment node
/** Lot 14 — un composant fait 300 lignes au plus.
 *
 * `docs/journal/ouverture_plan.md` §7 : « un composant fait 300 lignes au plus ».
 * Ce test relit chaque `.tsx` de `src/` et échoue au premier qui dépasse :
 * un écran qui grossit se découpe (un volet, une étape, une section par
 * fichier) plutôt que d'attendre une relecture pour s'en apercevoir.
 *
 * Seuls les `.tsx` sont comptés : `api/types.ts`, `api/client.ts` et
 * `api/formats.ts` ne sont pas des composants — ce sont la frontière avec
 * l'API, qui se lit d'un seul tenant.
 *
 * On compte les lignes du fichier telles qu'un éditeur les numérote,
 * commentaires compris : un commentaire qui explique un choix a sa place,
 * mais il ne dispense pas le fichier de rester lisible d'un coup d'œil.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const RACINE_FRONT = join(__dirname, "..");
const RACINE_SRC = join(RACINE_FRONT, "src");
const PLAFOND_LIGNES = 300;

function composants(dossier: string): string[] {
  const resultats: string[] = [];
  for (const entree of readdirSync(dossier, { withFileTypes: true })) {
    const chemin = join(dossier, entree.name);
    if (entree.isDirectory()) resultats.push(...composants(chemin));
    else if (entree.name.endsWith(".tsx")) resultats.push(chemin);
  }
  return resultats;
}

/** Le nombre de lignes numérotées : la ligne vide après le dernier saut ne compte pas. */
function lignes(contenu: string): number {
  const morceaux = contenu.split("\n");
  if (morceaux[morceaux.length - 1] === "") morceaux.pop();
  return morceaux.length;
}

describe("la taille des composants", () => {
  it("trouve bien des composants à mesurer", () => {
    // Garde-fou : un chemin faux rendrait le test suivant vert sans rien lire.
    expect(composants(RACINE_SRC).length).toBeGreaterThan(20);
  });

  it(`ne dépasse ${PLAFOND_LIGNES} lignes dans aucun .tsx de src/`, () => {
    const trop = composants(RACINE_SRC)
      .map((chemin) => ({ chemin, n: lignes(readFileSync(chemin, "utf8")) }))
      .filter(({ n }) => n > PLAFOND_LIGNES)
      .map(({ chemin, n }) => `${relative(RACINE_FRONT, chemin)} : ${n} lignes`);
    expect(trop, trop.join("\n")).toEqual([]);
  });

  it("compte les lignes comme un éditeur", () => {
    expect(lignes("a\nb\n")).toBe(2);
    expect(lignes("a\nb")).toBe(2);
    expect(lignes("")).toBe(0);
  });
});

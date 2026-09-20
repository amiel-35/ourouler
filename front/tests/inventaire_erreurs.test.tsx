/** L'inventaire des pannes de l'API, confronté à ce que l'écran sait dire.
 *
 * L7.D (18/09/2026) : 13 des 21 codes d'`api/erreurs.CODES_PANNE` avaient un
 * écran — 9 par un titre dans `Echec.tsx`, 4 par un écran dédié — les 8
 * autres tombaient dans le générique « Ça n'a pas marché ». Ce n'était pas un
 * écran muet — le message du cœur et le code restaient affichés — mais ce
 * n'était pas non plus la phrase qui dit ce qui s'est passé, seulement celle
 * que l'API avait déjà écrite.
 *
 * Plutôt que de recopier la liste des codes ici, où elle se périmerait en
 * silence à la prochaine panne ajoutée côté serveur, ce test relit
 * `CODES_PANNE` dans les sources Python — même geste que
 * `tests/provenance.test.tsx` pour les valeurs de maquette, même principe
 * que les invariants Python qui rattachent `MOTIFS_AVERTISSEMENT` au code
 * qui écrit chaque fragment : la source du catalogue est unique, et le front
 * ne peut pas dessiner un état qu'il ne sait pas reconnaître. C'est ce geste
 * qui a trouvé `session_absente` (lot L7.A, mergé pendant celui-ci) avant
 * même de le chercher : ce test a échoué dès le rebase, pour un code qu'on
 * n'avait pas encore lu.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErreurApi } from "../src/api/client";
import { Echec } from "../src/composants/Echec";

const ERREURS_PY = join(__dirname, "..", "..", "src", "ourouler", "api", "erreurs.py");

/** Les codes de `CODES_PANNE`, lus dans la source plutôt que recopiés ici. */
function codesPanne(): string[] {
  const source = readFileSync(ERREURS_PY, "utf8");
  const bloc = source.match(/CODES_PANNE: dict\[str, str\] = \{([\s\S]*?)\n\}/);
  if (!bloc) {
    throw new Error(
      "CODES_PANNE introuvable dans erreurs.py — la forme de la source a changé, " +
        "ce test doit être mis à jour avant de faire confiance à son résultat",
    );
  }
  const codes = [...bloc[1].matchAll(/"([a-z_]+)":/g)].map((m) => m[1]);
  expect(codes.length, "le motif n'a rien capturé — vérifier la regex").toBeGreaterThan(10);
  return codes;
}

/** Les codes qui ont leur propre écran, avant même le tableau des titres. */
const TITRES_HORS_TABLEAU: Record<string, string> = {
  aucune_boucle: "Aucune boucle",
  meteo_indisponible: "Pas de météo",
  meteo_hors_domaine: "Pas de météo",
  // `intervals_refuse` n'a pas de titre fixe : sans `contexte`, `Echec` retombe
  // sur « Vos séances » (l'écran où cette panne arrive dans l'app réelle).
  intervals_refuse: "Vos séances",
  // `intervals_absent` a le même titre de repli, et pour la même raison : les
  // deux parlent des séances, l'un à qui n'a jamais relié son compte, l'autre
  // à qui l'avait relié et dont la clé a cessé.
  intervals_absent: "Vos séances",
  // `session_absente` n'a plus d'écran dédié depuis le lot L7.2-D
  // (19/09/2026) : `App.tsx` intercepte ce code avant `Echec` et montre
  // l'écran de connexion. Il reste couvert par le tableau générique de
  // `Echec.tsx`, donc absent d'ici — voir le commentaire sur ce tableau.
};

function erreur(code: string, statut = 502): ErreurApi {
  return new ErreurApi(
    { code, message: `message d'essai pour ${code}`, service: null, details: {} },
    statut,
  );
}

describe("chaque code de CODES_PANNE produit un titre reconnaissable", () => {
  for (const code of codesPanne()) {
    it(`« ${code} » n'affiche pas le titre générique`, () => {
      const vue = render(<Echec erreur={erreur(code)} />);
      const titre = vue.container.querySelector("h1")?.textContent ?? "";
      expect(titre, `code « ${code} » : aucun titre nommé, retombe sur le générique`).not.toBe(
        "Ça n'a pas marché",
      );
      const attendu = TITRES_HORS_TABLEAU[code];
      if (attendu) expect(titre).toBe(attendu);
      // Le message du cœur reste affiché dans tous les cas, sauf sur l'écran
      // d'`intervals_refuse` : lui remplace le message brut par une phrase
      // fixe qui renvoie vers l'écran de la clé (E15), pas vers
      // « réessayez » — c'est la décision documentée dans `erreurs.py`.
      // Même exception pour `intervals_absent` : son écran remplace le message
      // du cœur — « compléter [intervals] athlete_id et api_key dans la
      // configuration » — par une phrase et un bouton vers les réglages. Ce
      // message-là décrit un fichier TOML que personne d'autre que le
      // mainteneur ne verra jamais.
      if (code !== "intervals_refuse" && code !== "intervals_absent") {
        expect(screen.getByText(new RegExp(`message d'essai pour ${code}`))).toBeTruthy();
      }
      vue.unmount();
    });
  }
});

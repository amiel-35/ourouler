/** L'attente (E18) — semi-synchrone, contre un budget annoncé.
 *
 * « Un écran muet pendant un calcul long est indistinguable d'un écran
 * cassé » : les jalons nomment ce qui se passe, dans le vocabulaire du
 * cycliste, et un compteur de secondes **réelles** prouve que ça avance.
 *
 * Deux honnêtetés, et elles ne sont pas négociables :
 *
 * 1. **L'avancement est indicatif.** Le cœur ne rend pas compte de son
 *    avancement — il ne connaît pas son appelant, règle absolue 2 — donc le
 *    front ne peut qu'interpoler contre la durée annoncée. Il le dit.
 * 2. **Le budget dit d'où il vient.** `source: "mesure"` est une mesure de ce
 *    serveur, `source: "defaut"` une valeur d'attente. Un écran ne doit
 *    jamais présenter l'une pour l'autre (`docs/journal/ux/api_contrat.md`).
 *
 * Les jalons ne portent **aucun résultat intermédiaire**. La maquette en
 * montrait un (« Le sud-est est au sec ») ; il aurait fallu l'inventer,
 * puisque rien ne remonte du calcul avant sa fin. Une étape nommée est
 * vraie ; un résultat inventé ne l'est pas (règle absolue 5).
 */

import { useEffect, useState } from "react";
import type { Budget } from "../api/types";
import { nombre } from "../api/formats";

const JALONS = [
  "Vent et pluie relevés autour de vous",
  "Directions comparées",
  "Boucles tracées",
  "Terrain relevé sous les blocs",
  "Propositions retenues",
];

interface Props {
  titre?: string;
  contexte?: string;
  budget: Budget | null;
  annuler?: () => void;
}

/** Ce qu'on dit du budget, selon qu'il est mesuré ici ou pris par défaut. */
export function phraseBudget(budget: Budget | null): string {
  if (budget === null) return "Durée inconnue : le serveur n'a pas annoncé de budget.";
  const secondes = nombre(budget.attendu_ms / 1000, 0);
  if (budget.source === "mesure") {
    return `Environ ${secondes} secondes — mesuré sur ce serveur, sur ${budget.n} exécution${
      budget.n > 1 ? "s" : ""
    }.`;
  }
  return `Environ ${secondes} secondes — valeur par défaut : ce serveur n'a encore rien mesuré.`;
}

export function Attente({ titre = "On cherche", contexte, budget, annuler }: Props) {
  const [millisecondes, setMillisecondes] = useState(0);

  useEffect(() => {
    const debut = Date.now();
    const minuteur = window.setInterval(() => setMillisecondes(Date.now() - debut), 200);
    return () => window.clearInterval(minuteur);
  }, []);

  const attendu = budget?.attendu_ms ?? 0;
  const part = attendu > 0 ? Math.min(millisecondes / attendu, 1) : 0;
  const atteint = attendu > 0 ? Math.min(Math.floor(part * JALONS.length), JALONS.length - 1) : 0;
  const depasse = attendu > 0 && millisecondes > attendu;

  return (
    <section>
      <div className="app-tete">
        <div>
          {contexte ? <span className="quand">{contexte}</span> : null}
          <h1>{titre}</h1>
        </div>
        <div className="a-droite">
          <div className="grand secondaire" aria-label="temps écoulé">
            {nombre(millisecondes / 1000, 0)}
            <small>s</small>
          </div>
        </div>
      </div>

      <div className="barre-avance" role="progressbar" aria-valuetext="avancement indicatif">
        <i style={{ width: `${Math.round(part * 100)}%` }} />
      </div>

      <div className="jalons">
        {JALONS.map((jalon, index) => {
          const etat = index < atteint ? "fait" : index === atteint ? "cours" : "suite";
          return (
            <div className={`jalon ${etat}`} key={jalon}>
              <span className="etat" aria-hidden="true">
                {etat === "fait" ? "✓" : etat === "cours" ? "→" : "·"}
              </span>
              <span>{jalon}</span>
              <span />
            </div>
          );
        })}
      </div>

      <div className="encart info" style={{ marginTop: "var(--espace-bloc)" }}>
        <b>{phraseBudget(budget)}</b>
      </div>
      <p className="mention">
        L'avancement affiché est indicatif : le calcul ne rend pas compte de ses étapes, seules
        les secondes écoulées sont réelles.
      </p>
      {depasse ? (
        <p className="mention" style={{ marginTop: "var(--espace-interne)" }}>
          Ça dure plus longtemps que prévu. Le calcul tourne toujours — ne rechargez pas, une
          page rechargée relance tout depuis le début.
        </p>
      ) : null}
      {annuler ? (
        <button type="button" className="bouton fantome" onClick={annuler}>
          Annuler la recherche
        </button>
      ) : null}
    </section>
  );
}

/** L'écart de distance, quand il cesse d'être tu.
 *
 * Demander 6 h et recevoir trois boucles de 5 h, **sans un mot** : le moteur
 * ne refuse pas, il sert la boucle la plus proche, avec son écart. On le dit
 * donc : « on n'a pas trouvé de boucle dans les contraintes, on a élargi de
 * X % », par paliers de 5 % (décision Q41 d,
 * `docs/journal/questions/questions_mainteneur.md`). Le chiffre n'est donc
 * pas un seuil à défendre, c'est un **résultat à montrer** — d'où un bandeau qui
 * porte des nombres mesurés et aucune formule d'excuse.
 *
 * Ce n'est pas une alerte : la boucle est bonne, elle est simplement d'une
 * autre longueur que celle demandée, et c'est au cycliste d'en juger.
 */

import type { Candidate } from "../api/types";
import { pourcentage } from "../api/formats";

/** Les candidates qu'il a fallu élargir pour servir, les autres écartées. */
export function elargies(candidates: Candidate[]): Candidate[] {
  return candidates.filter((c) => c.hors_tolerance && (c.elargissement ?? 0) > 0);
}

export function BandeauElargissement({
  candidates,
  distanceVisee,
}: {
  candidates: Candidate[];
  distanceVisee: number;
}) {
  const concernees = elargies(candidates);
  if (concernees.length === 0) return null;

  // Le palier affiché est le plus large de ceux qu'il a fallu concéder : dire
  // « élargi de 5 % » alors qu'une proposition a demandé 10 % serait plus
  // rassurant que vrai.
  const palier = Math.max(...concernees.map((c) => c.elargissement ?? 0));
  const tolerance = concernees[0].tolerance_distance ?? 0;

  return (
    <div className="encart info">
      <b>
        Aucune boucle à ±{pourcentage(tolerance)} de {Math.round(distanceVisee)} km.
      </b>{" "}
      On a élargi de {pourcentage(palier)}, soit ±{pourcentage(tolerance + palier)}.
      <ul className="mention">
        {concernees.map((c) => (
          <li key={c.numero}>
            Parcours {c.numero} : {c.distance_km.toFixed(1)} km,{" "}
            {signe(c.ecart_relatif ?? 0)} de la distance demandée.
          </li>
        ))}
      </ul>
    </div>
  );
}

/** « +18 % » ou « −17 % » : le signe compte et se dit.
 *
 * Plus court que demandé et plus long que demandé ne se vivent pas pareil —
 * rentrer plus tôt n'est pas rentrer plus tard. Les confondre sous une valeur
 * absolue ferait dire la même chose à deux situations opposées.
 */
export function signe(ecart: number): string {
  const symbole = ecart < 0 ? "−" : "+";
  return `${symbole}${pourcentage(Math.abs(ecart))}`;
}

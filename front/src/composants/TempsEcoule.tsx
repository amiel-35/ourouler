/** Le second chiffre du temps de sortie — porte à porte, arrêts compris.
 *
 * Le défaut que ce composant corrige, mesuré chez le mainteneur : une sortie
 * demandée pour 5 h affichait « 3 h 57 ». Le chiffre n'était pas faux — c'est
 * le temps de **mouvement** du modèle physique, qui ignore les arrêts par
 * construction — mais seul, il se lisait comme une durée totale.
 *
 * Décision du mainteneur, mot pour mot : « plus que corriger faudrait donner
 * les 2 valeurs et une explication ; la durée en mouvement en majeur et un
 * truc qui dit s'il y avait pas d'arrêts etc. » Le majeur ne bouge donc pas
 * de sa place ; celui-ci vient en second, et explique la différence au lieu
 * de la cacher.
 *
 * `compteur === null` (ou absent) : la configuration ne porte aucun vélo —
 * il n'y a alors ni modèle ni facteur, et **aucun second chiffre ne
 * s'affiche**, pas même un tiret (règle absolue 5 : l'ignorance ne se
 * montre pas comme une valeur).
 */

import { dureeApprox, nombre } from "../api/formats";
import type { Candidate, Compteur } from "../api/types";

interface Props {
  candidate: Candidate;
  compteur: Compteur | null | undefined;
}

export function TempsEcoule({ candidate, compteur }: Props) {
  const tempsEcouleS = candidate.temps_ecoule_s;
  if (!compteur || tempsEcouleS === null || tempsEcouleS === undefined) return null;
  return (
    <div className="temps-ecoule">
      <p className="mention">≈ {dureeApprox(tempsEcouleS)} porte à porte</p>
      <details>
        <summary>D'où viennent ces deux chiffres</summary>
        <p className="mention">
          Le premier est la simulation de <b>cette boucle-ci</b> : puissance d'endurance,
          relief et vent, sans aucun arrêt.
        </p>
        <p className="mention">
          Le second applique votre <b>moyenne compteur habituelle</b> —{" "}
          {nombre(compteur.moyenne_compteur_kmh, 1)} km/h — à la distance ; il ne tient donc
          pas compte du relief propre à cette boucle, contrairement au premier.
        </p>
        {compteur.facteur_provenance === "suppose" ? (
          <p className="mention">
            Facteur {nombre(compteur.facteur_compteur, 3)},{" "}
            <span>supposé — il n'a pas été mesuré sur vos sorties</span>.
          </p>
        ) : null}
        {candidate.temps_ecoule_source === "plancher_arrets" ? (
          <p className="mention">
            Cette boucle est assez vallonnée pour que votre moyenne habituelle ne s'applique
            plus : le chiffre est alors le temps de mouvement, plus une part d'arrêts.
          </p>
        ) : null}
        <p className="mention">
          C'est cette même moyenne compteur qui a servi à choisir la distance de cette
          sortie — elle se retrouve dans Réglages.
        </p>
      </details>
    </div>
  );
}

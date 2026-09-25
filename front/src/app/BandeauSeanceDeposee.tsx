/** Lot 14 : extrait d'`App.tsx` sans changement de comportement — le bandeau
 * qui dit qu'un fichier de séance est en usage. */

import { jourEnLettres } from "../api/formats";
import type { SeanceDeposee } from "./navigation";

/**
 * « Un fichier est en usage » — dit à l'écran, pas seulement dans l'état React.
 *
 * Le second défaut de B1 : même corrigé, un fichier qui se replace tout seul
 * sur une recherche est invisible. Le bandeau dit lequel, pour quel jour, et
 * **s'il va servir à la recherche en cours** — parce que « déposé » et
 * « appliqué » ne sont plus la même chose depuis qu'il est rattaché à un jour.
 */
export function BandeauSeanceDeposee({
  deposee,
  jourDemande,
  surRetirer,
}: {
  deposee: SeanceDeposee;
  jourDemande: string;
  surRetirer: () => void;
}) {
  const actif = deposee.jour === jourDemande;
  return (
    <div className={actif ? "encart attention" : "encart"}>
      <b>Séance déposée : {deposee.nom}.</b>{" "}
      {actif
        ? `Elle sera placée sur le parcours du ${jourEnLettres(deposee.jour)}.`
        : `Elle vaut pour le ${jourEnLettres(deposee.jour)} — la recherche en cours porte sur
           un autre jour, et ne s'en servira pas.`}{" "}
      <button type="button" className="lien" onClick={surRetirer}>
        Retirer ce fichier
      </button>
    </div>
  );
}

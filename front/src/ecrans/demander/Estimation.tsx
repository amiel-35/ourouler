/** « Ce que ça donnera » : l'estimation en tête de l'écran, qui bouge avec les réglages. */

import type { ValeursLiees } from "../../api/types";
import { duree, nombre } from "../../api/formats";
import { phraseEstimation } from "./demande";

export function Estimation({
  distanceEstimee,
  liees,
  minutes,
  retour,
}: {
  distanceEstimee: number | null;
  liees: ValeursLiees | null;
  minutes: number;
  retour: string | null;
}) {
  return (
    <div className="bloc choisi hero">
      <div className="bloc-tete">
        <h2>Ce que ça donnera</h2>
        <span className="rang">Estimation</span>
      </div>
      <div className="estimation-duo">
        <div>
          <div className="grand">
            {distanceEstimee === null ? "—" : nombre(distanceEstimee, 0)}
            <small>km</small>
          </div>
          <p className="mention">
            {liees === null
              ? "aucun vélo : rien à estimer"
              : `à ${nombre(liees.puissance_endurance_w)} W en endurance`}
          </p>
        </div>
        <div>
          <div className="grand">{duree(minutes * 60)}</div>
          <p className="mention">{retour ? `retour vers ${retour}` : "heure à préciser"}</p>
        </div>
      </div>
      {liees ? <p className="mention">{phraseEstimation(liees)}</p> : null}
    </div>
  );
}

/** Les deux horloges d'une sortie : le porte à porte, et le temps sans arrêt.
 *
 * Le défaut d'origine, mesuré chez le mainteneur : une sortie demandée pour
 * 5 h affichait « 3 h 57 ». Le chiffre n'était pas faux — c'est le temps de
 * **mouvement** du modèle physique, qui ignore les arrêts par construction —
 * mais seul, il se lisait comme une durée totale.
 *
 * **L'ordre des deux chiffres est celui du mainteneur** (corrigé le
 * 18/09/2026, il avait d'abord été posé à l'envers) : « je demande 5 h, je
 * veux 5 h, pas 4 h et un truc plus loin qui me dit en fait c'est 5 h ».
 * Le majeur est donc le **porte à porte**, celui qu'on lit sur une montre du
 * départ au retour ; le temps de mouvement vient juste à côté, et dit ce que
 * ça donnerait sans un seul feu ni un seul stop.
 *
 * Les deux ne sont pas de la même finesse, et `Explication` le dit : le temps
 * de mouvement est une simulation de *ce tracé-ci* — pente point par point et
 * vent prévu à chaque cap — tandis que le porte à porte applique la moyenne
 * compteur habituelle à la distance, donc à plat.
 *
 * `compteur === null` (ou absent) : la configuration ne porte aucun vélo — il
 * n'y a alors ni modèle ni facteur, et **on retombe sur le seul chiffre
 * disponible**, nommé pour ce qu'il est, plutôt que d'afficher un tiret
 * (règle absolue 5 : l'ignorance ne se montre pas comme une valeur).
 */

import { duree, dureeApprox, nombre } from "../api/formats";
import type { Candidate, Compteur } from "../api/types";

/** Ce que porte la ligne de chiffres d'une carte : le majeur, puis le second. */
export function DureesDeSortie({
  mouvementS,
  ecouleS,
}: {
  mouvementS: number | null | undefined;
  ecouleS: number | null | undefined;
}) {
  if (ecouleS === null || ecouleS === undefined) {
    // Sans porte à porte, le temps de mouvement reste le seul chiffre — mais
    // il garde son nom, sans quoi on retombe exactement dans le défaut.
    return mouvementS ? (
      <span>
        <b>{duree(mouvementS)}</b> en roulant
      </span>
    ) : null;
  }
  return (
    <>
      <span>
        <b>≈ {dureeApprox(ecouleS)}</b> porte à porte
      </span>
      {mouvementS ? (
        <span className="second-chiffre">{duree(mouvementS)} sans un seul arrêt</span>
      ) : null}
    </>
  );
}

/** Le dépliant qui dit d'où viennent les deux chiffres, sous la carte. */
export function TempsEcoule({
  candidate,
  compteur,
}: {
  candidate: Candidate;
  compteur: Compteur | null | undefined;
}) {
  const tempsEcouleS = candidate.temps_ecoule_s;
  if (!compteur || tempsEcouleS === null || tempsEcouleS === undefined) return null;
  return (
    <div className="temps-ecoule">
      <details>
        <summary>D'où viennent ces deux chiffres</summary>
        <p className="mention">
          Le premier applique votre <b>moyenne compteur habituelle</b> —{" "}
          {nombre(compteur.moyenne_compteur_kmh, 1)} km/h — à la distance : c'est la durée
          que vous liriez sur une montre, du départ au retour, arrêts compris.
        </p>
        <p className="mention">
          Le second est la simulation de <b>ce tracé-ci</b> — puissance d'endurance, pente
          point par point et vent prévu à chaque cap — <b>sans aucun arrêt</b> : ni feu, ni
          stop, ni bidon. C'est le seul des deux qui tienne compte du relief de cette
          boucle ; le premier, lui, est une moyenne à plat.
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
            plus : le porte à porte est alors le temps de mouvement, plus une part d'arrêts.
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

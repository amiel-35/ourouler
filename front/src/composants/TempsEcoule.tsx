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
 * **Depuis L9.1 (25/09/2026), le porte à porte est une fourchette** :
 * « entre 4 h 23 et 4 h 38 ». Il part du temps sans arrêt de *ce tracé-ci*
 * (côtes et vent compris) et y ajoute ce que les vraies sorties du cycliste
 * prennent en plus — la moitié d'entre elles tombent dans la fourchette. Il
 * ne s'appuie plus sur la moyenne compteur, qui était à plat (« je pige
 * pas », mainteneur, 21/09, devant l'ancien dépliant : d'où les phrases
 * courtes et sans jargon ci-dessous).
 *
 * `compteur === null` (ou absent) : la configuration ne porte aucun vélo — il
 * n'y a alors pas de fourchette, et **on retombe sur le seul chiffre
 * disponible**, nommé pour ce qu'il est, plutôt que d'afficher un tiret
 * (règle absolue 5 : l'ignorance ne se montre pas comme une valeur).
 */

import { duree, dureeApprox, enPlus, entreDurees, nombre } from "../api/formats";
import type { Candidate, Compteur } from "../api/types";

/** Le porte à porte en toutes lettres : la fourchette, ou la seule médiane d'une
 * réponse d'avant L9.1 (arrondie et précédée de « ≈ », comme alors). */
export function textePorteAPorte(
  ecouleS: number,
  basS: number | null | undefined,
  hautS: number | null | undefined,
): string {
  if (basS !== null && basS !== undefined && hautS !== null && hautS !== undefined) {
    return entreDurees(basS, hautS);
  }
  return `≈ ${dureeApprox(ecouleS)}`;
}

/** Ce que porte la ligne de chiffres d'une carte : le majeur, puis le second. */
export function DureesDeSortie({
  mouvementS,
  ecouleS,
  basS,
  hautS,
}: {
  mouvementS: number | null | undefined;
  ecouleS: number | null | undefined;
  basS?: number | null;
  hautS?: number | null;
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
        <b>{textePorteAPorte(ecouleS, basS, hautS)}</b> porte à porte
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
  const fourchette = compteur.porte_a_porte;
  return (
    <div className="temps-ecoule">
      <details>
        <summary>D'où viennent ces deux chiffres</summary>
        <p className="mention">
          <b>Sans un seul arrêt</b> : le temps calculé sur ce parcours-ci, avec ses côtes et
          le vent prévu.
        </p>
        {fourchette ? (
          fourchette.provenance === "mesure" ? (
            <p className="mention">
              <b>Porte à porte</b> : on y ajoute ce que vos vraies sorties prennent en plus
              — feux, pauses, relances. Sur vos {nombre(fourchette.n)} sorties roulées seul,
              la moitié ont duré de {enPlus(fourchette.bas)} à {enPlus(fourchette.haut)} de
              plus : <span>mesuré sur vos sorties</span>.
            </p>
          ) : (
            <p className="mention">
              <b>Porte à porte</b> : on y ajoute de {enPlus(fourchette.bas)} à{" "}
              {enPlus(fourchette.haut)} pour les feux, les pauses et les relances.{" "}
              <span>Convention, pas encore mesurée sur vos sorties</span> — elle vient d'un
              seul cycliste.
            </p>
          )
        ) : null}
        <p className="mention">
          La distance, elle, a été choisie avec votre moyenne habituelle au compteur —{" "}
          {nombre(compteur.moyenne_compteur_kmh, 1)} km/h
          {compteur.facteur_provenance === "suppose" ? (
            <>
              , <span>supposé — il n'a pas été mesuré sur vos sorties</span>
            </>
          ) : null}
          . Elle se règle dans Réglages.
        </p>
      </details>
    </div>
  );
}

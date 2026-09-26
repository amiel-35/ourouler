/** Les morceaux du détail d'une proposition : ses chiffres, l'envoi du GPX, la tenue. */

import type { Candidate, Proposition, Sortie } from "../../api/types";
import type { PanneGpx } from "../../api/client";
import { compteArrets, kmDepuisKm, nombre, pourcentage, visibleEnKm } from "../../api/formats";
import { DureesDeSortie } from "../../composants/TempsEcoule";
import { partager } from "./partager";

export function ChiffresParcours({
  proposition,
  candidate,
}: {
  proposition: Proposition;
  candidate: Candidate;
}) {
  const arrets = compteArrets(proposition.feux, proposition.stops);
  return (
    <div className="chiffres espace">
      <span>
        <b>{kmDepuisKm(candidate.distance_km)}</b>
      </span>
      {candidate.denivele_m !== null ? (
        <span>
          <b>{nombre(candidate.denivele_m)}</b> m D+
        </span>
      ) : null}
      {/* Le porte à porte en majeur, le temps sans arrêt juste à côté
          (18/09/2026) : « je demande 5 h, je veux 5 h ». Les deux
          chiffres restaient corrects mais éloignés — le porte à porte
          arrivait après le D+, les feux, le trafic et les routes non
          classées, si loin que l'œil ne les rapprochait plus l'un de
          l'autre. Ils suivent maintenant tout de suite le D+, comme sur
          `Boucles.tsx` et `Propositions.tsx`. */}
      <DureesDeSortie
        mouvementS={proposition.duree_s}
        ecouleS={candidate.temps_ecoule_s}
        basS={candidate.temps_ecoule_bas_s}
        hautS={candidate.temps_ecoule_haut_s}
      />
      {arrets !== null ? (
        <span>
          <b>{nombre(arrets)}</b> feux et stops
        </span>
      ) : null}
      {proposition.part_trafic !== null ? (
        <span>
          <b>{pourcentage(proposition.part_trafic)}</b> sur routes passantes
        </span>
      ) : null}
      {/* Le même piège qu'à l'écran des boucles : « 5 % sur routes
          passantes » se lit « 95 % de tranquillité », alors qu'une part
          de la distance est sur des voies que la carte ne classe pas.
          Elle n'apparaît que lorsqu'elle existe, jamais en zéro. */}
      {candidate.couts && visibleEnKm(candidate.couts.km_non_classe) ? (
        <span>
          <b>{kmDepuisKm(candidate.couts.km_non_classe)}</b> qu'on ne sait pas
          classer
        </span>
      ) : null}
    </div>
  );
}

export function EnvoiGpx({
  proposition,
  erreurGpx,
  surErreurGpx,
}: {
  proposition: Proposition;
  erreurGpx: PanneGpx | null;
  surErreurGpx: (panne: PanneGpx | null) => void;
}) {
  return (
    <>
      {/* Q40 (g) : chaque proposition porte **sa** trace, fabriquée au
          moment où on la demande. Auparavant un seul GPX existait, celui
          de la proposition retenue : emporter « la plus sèche » envoyait
          la trace de « la plus calme » au compteur. */}
      {proposition.gpx ? (
        <>
          {erreurGpx ? (
            <div className="encart alerte">
              <b>L'envoi vers votre compteur a échoué.</b> {erreurGpx.message}
              <p className="mention" style={{ marginTop: "var(--espace-interne)", marginBottom: 0 }}>
                Code de la panne : {erreurGpx.code}.
              </p>
            </div>
          ) : null}
          <button
            type="button"
            className="bouton"
            onClick={partager(proposition.gpx.url, proposition.gpx.nom, surErreurGpx)}
          >
            Envoyer vers mon compteur
          </button>
          <a className="bouton fantome" href={proposition.gpx.url} download={proposition.gpx.nom}>
            Télécharger le GPX
          </a>
        </>
      ) : (
        <p className="mention">Aucun GPX n'est disponible pour ce parcours.</p>
      )}
    </>
  );
}

/** L'onglet « La tenue » : ce qu'on porte, ce qu'on emporte, ce qu'on enlève en route. */
export function Tenue({ tenue }: { tenue: Sortie["tenue"] }) {
  return tenue ? (
    <div>
      <div className="bloc">
        <div className="bloc-tete">
          <h2>Sur vous</h2>
          <span className="rang">
            {tenue.categorie_temp} · {tenue.categorie_humidite}
          </span>
        </div>
        <ul className="liste-simple">
          {tenue.base.map((piece) => (
            <li key={piece}>{piece}</li>
          ))}
        </ul>
      </div>
      {tenue.a_emporter.length > 0 ? (
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>À emporter</h2>
          </div>
          <ul className="liste-simple">
            {tenue.a_emporter.map((piece) => (
              <li key={piece}>{piece}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {tenue.a_enlever.length > 0 ? (
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>À enlever en route</h2>
          </div>
          <ul className="liste-simple">
            {tenue.a_enlever.map((piece) => (
              <li key={piece}>{piece}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {tenue.motifs.map((motif) => (
        <p className="mention" key={motif}>
          {motif}
        </p>
      ))}
    </div>
  ) : (
    <div className="bloc doux">
      <div className="bloc-tete">
        <h2>La tenue</h2>
      </div>
      <p className="mention">
        Sans température, on ne conseille rien plutôt que de conseiller au hasard.
      </p>
    </div>
  );
}


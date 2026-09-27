/** E14 — la page du jour. Le seul écran qui doit se lire en trois secondes.
 *
 * L'ordre : ce qu'on va faire, puis où. Bras tendu, en plein soleil, trois
 * minutes avant de partir.
 *
 * **Un écart avec la maquette, assumé et dit ici.** La maquette montre un
 * parcours « généré à 6 h », calculé pendant la nuit. Aucun calcul de nuit
 * n'existe côté serveur, et l'API ne l'expose pas : l'inventer aurait été
 * afficher une heure fausse. L'écran montre donc le **dernier parcours
 * réellement obtenu pour ce jour**, avec l'heure à laquelle il l'a été, et
 * un bouton quand il n'y en a pas encore.
 *
 * **La rose des huit directions se lit sans avoir rien demandé** : tant qu'aucun parcours n'a encore été cherché aujourd'hui,
 * un résumé compact — la direction recommandée, sa pluie, son vent — répond
 * à « où rouler » avant même le bouton « Chercher ». Une fois un parcours
 * obtenu, la carte et son tracé coloré par le vent répondent déjà à cette
 * question pour *ce* parcours-là : répéter la rose ferait deux réponses à
 * la même question, potentiellement contradictoires si le parcours n'est
 * pas parti dans la direction recommandée.
 */

import { useEffect, useState } from "react";
import type { Enveloppe, Meteo, Seance, Sortie } from "../api/types";
import { duree, heure, jourEnLettres, kmDepuisKm, nombre, pourcentage, compteArrets } from "../api/formats";
import { api, ErreurApi } from "../api/client";
import { directionsDepuisCellules } from "../api/meteoRose";
import { Etapes } from "../composants/Etapes";
import { Carte } from "../composants/Carte";
import { RoseDirections, resumeDirection } from "../composants/RoseDirections";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";

interface Props {
  jour: string;
  seance: Seance | null;
  parcours: { obtenue_le: string; reponse: Enveloppe<Sortie> } | null;
  /** L'heure de départ qui servira à la recherche (`heureDepartParDefaut`,
   * `demander/demande.ts`) — le même état que celui de « Demander ». */
  heureDepart: string;
  surHeureDepart: (heure: string) => void;
  surGenerer: () => void;
  surOuvrir: () => void;
  surDemander: () => void;
  surDeposer: () => void;
}

export function Aujourdhui({
  jour,
  seance,
  parcours,
  heureDepart,
  surHeureDepart,
  surGenerer,
  surOuvrir,
  surDemander,
  surDeposer,
}: Props) {
  const sortie = parcours?.reponse.donnees ?? null;
  const retenue = sortie?.propositions.find((p) => p.retenue) ?? sortie?.propositions[0] ?? null;
  const candidate = retenue ? sortie?.candidates.find((c) => c.numero === retenue.numero) : null;
  const manque = parcours ? meteoManquante(parcours.reponse.avertissements) : null;

  // Le résumé de la rose, chargé une fois — cet écran ne pose ni jour ni
  // heure de départ (c'est `Demander` qui les négocie) : « maintenant »
  // suffit pour la lecture en trois secondes, l'écran n'attend pas de
  // réponse plus précise qu'un coup d'œil.
  //
  // **Chargée seulement tant qu'aucun parcours n'existe déjà** (`!sortie`) :
  // une fois un parcours obtenu, la rose ne s'affiche plus (voir plus bas),
  // et lui faire quand même payer un appel à `/meteo` serait un appel pour
  // rien — huit directions et leurs couronnes, pour un résultat qu'on ne
  // montre jamais.
  const [meteo, setMeteo] = useState<Enveloppe<Meteo> | null>(null);
  const [erreurMeteo, setErreurMeteo] = useState<string | null>(null);
  useEffect(() => {
    if (sortie) return;
    let annule = false;
    api
      .meteo()
      .then((reponse) => {
        if (!annule) setMeteo(reponse);
      })
      .catch((erreur) => {
        if (!annule) setErreurMeteo(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      });
    return () => {
      annule = true;
    };
  }, [sortie]);
  const directionsMeteo = meteo ? directionsDepuisCellules(meteo.donnees.cellules) : [];
  const directionRecommandee = meteo?.donnees.meilleure_direction?.nom ?? null;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">{jourEnLettres(jour)}</span>
          <h1>{seance ? seance.nom : "Rien de prévu"}</h1>
        </div>
        {seance ? (
          <div className="a-droite">
            <div className="grand secondaire">{duree(seance.duree_s)}</div>
          </div>
        ) : null}
      </div>

      {/* Même champ que `Demander.tsx`, relié au même état
          (`demande.heure_depart`) : la recherche du jour part de cette
          heure-là, affichée et modifiable en un geste, plutôt que d'une
          heure figée à 9 h invisible à l'écran (backlog « Séance du jour à
          l'heure réelle »). */}
      <p className="mention">
        <label htmlFor="heure-depart">Départ à </label>
        <input
          id="heure-depart"
          type="time"
          value={heureDepart}
          onChange={(e) => surHeureDepart(e.target.value)}
          style={{ font: "inherit", border: "none", background: "none", color: "inherit" }}
        />
      </p>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

      {/* La réponse à « où rouler » se lit sans avoir rien demandé — tant
          qu'aucun parcours n'existe déjà pour aujourd'hui. Une fois un
          parcours obtenu, la carte plus bas (tracé coloré par le vent)
          répond déjà à cette question pour *ce* parcours-là. */}
      {!sortie ? (
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>Où rouler</h2>
          </div>
          {erreurMeteo !== null ? (
            <p className="mention">{erreurMeteo}</p>
          ) : meteo === null ? (
            <p className="mention">Météo des huit directions : en cours…</p>
          ) : (
            <>
              <div className="rose-conteneur">
                <RoseDirections directions={directionsMeteo} recommandee={directionRecommandee} compact />
              </div>
              {(() => {
                const direction = directionsMeteo.find((d) => d.nom === directionRecommandee);
                return direction ? (
                  <p className="mention rose-resume">→ {resumeDirection(direction)}</p>
                ) : (
                  <p className="mention rose-resume">
                    {meteo.donnees.meilleure_direction?.motif ?? "Aucune direction ne se distingue."}
                  </p>
                );
              })()}
            </>
          )}
        </div>
      ) : null}

      {seance === null ? (
        <>
          <div className="encart info">
            <b>Aucune séance aujourd'hui.</b> Rien n'a été planifié sur intervals.icu pour ce
            jour-là — ce n'est pas une panne, c'est un jour de repos.
          </div>
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>Si vous voulez rouler quand même</h2>
            </div>
            <div className="boutons">
              <button type="button" className="bouton second" onClick={surDemander}>
                Demander un parcours
              </button>
              <button type="button" className="bouton second" onClick={surDeposer}>
                Déposer une séance
              </button>
            </div>
          </div>
        </>
      ) : (
        <>
          <Etapes etapes={seance.etapes} />
          {seance.avertissements.map((phrase) => (
            <div className="encart attention" key={phrase}>
              {phrase}
            </div>
          ))}
        </>
      )}

      {sortie && retenue && candidate ? (
        <div className="bloc choisi">
          <div className="bloc-tete">
            <h2>Parcours prêt</h2>
            <span className="rang">Obtenu à {heure(parcours!.obtenue_le)}</span>
          </div>
          {candidate.trace ? (
            <Carte
              traces={[{ points: candidate.trace.points, choisi: true }]}
              depart={sortie.demande.lieu_depart}
              description={`Boucle de ${nombre(candidate.distance_km, 1)} kilomètres`}
            />
          ) : null}
          <div className="chiffres">
            <span>
              <b>{kmDepuisKm(candidate.distance_km)}</b>
            </span>
            {candidate.denivele_m !== null ? (
              <span>
                <b>{nombre(candidate.denivele_m)}</b> m D+
              </span>
            ) : null}
            {(() => {
              const arrets = compteArrets(retenue.feux, retenue.stops);
              return arrets === null ? null : (
                <span>
                  <b>{nombre(arrets)}</b> feux et stops
                </span>
              );
            })()}
            {retenue.part_trafic !== null ? (
              <span>
                <b>{pourcentage(retenue.part_trafic)}</b> de trafic
              </span>
            ) : null}
          </div>
          {retenue.distinction ? <p className="mention forte">{retenue.distinction}</p> : null}
          <div className="boutons">
            <button type="button" className="bouton second" onClick={surGenerer}>
              Autre parcours
            </button>
            <button type="button" className="bouton" onClick={surOuvrir}>
              Ouvrir
            </button>
          </div>
        </div>
      ) : seance ? (
        <>
          <button type="button" className="bouton" onClick={surGenerer}>
            Chercher le parcours du jour
          </button>
          <p className="mention centre">
            Rien n'est calculé à l'avance : le parcours se cherche quand vous le demandez.
          </p>
        </>
      ) : null}
    </section>
  );
}

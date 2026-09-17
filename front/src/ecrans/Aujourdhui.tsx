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
 */

import type { Enveloppe, Seance, Sortie } from "../api/types";
import { duree, heure, jourEnLettres, kmDepuisKm, nombre, pourcentage, compteArrets } from "../api/formats";
import { Etapes } from "../composants/Etapes";
import { Carte } from "../composants/Carte";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";

interface Props {
  jour: string;
  seance: Seance | null;
  parcours: { obtenue_le: string; reponse: Enveloppe<Sortie> } | null;
  surGenerer: () => void;
  surOuvrir: () => void;
  surDemander: () => void;
  surDeposer: () => void;
}

export function Aujourdhui({
  jour,
  seance,
  parcours,
  surGenerer,
  surOuvrir,
  surDemander,
  surDeposer,
}: Props) {
  const sortie = parcours?.reponse.donnees ?? null;
  const retenue = sortie?.propositions.find((p) => p.retenue) ?? sortie?.propositions[0] ?? null;
  const candidate = retenue ? sortie?.candidates.find((c) => c.numero === retenue.numero) : null;
  const manque = parcours ? meteoManquante(parcours.reponse.avertissements) : null;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">{jourEnLettres(jour)}</span>
          <h1>{seance ? seance.nom : "Rien de prévu"}</h1>
        </div>
        {seance ? (
          <div style={{ textAlign: "right" }}>
            <div className="grand" style={{ fontSize: 22 }}>
              {duree(seance.duree_s)}
            </div>
          </div>
        ) : null}
      </div>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

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
          {retenue.distinction ? (
            <p className="mention" style={{ marginTop: 7 }}>
              {retenue.distinction}
            </p>
          ) : null}
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
          <p className="mention" style={{ textAlign: "center", marginTop: 10 }}>
            Rien n'est calculé à l'avance : le parcours se cherche quand vous le demandez.
          </p>
        </>
      ) : null}
    </section>
  );
}

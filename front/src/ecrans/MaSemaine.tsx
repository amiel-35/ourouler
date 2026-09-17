/** E15 — ma semaine. Trois séances, trois états différents.
 *
 * Une séance proche et une séance lointaine ne se traitent pas pareil :
 * au-delà de l'horizon d'orientation au vent, l'écran **dit pourquoi** le
 * vent disparaît plutôt que de l'omettre en silence (arbitrage 2 : trois
 * jours inclus, quatre non).
 *
 * Le parcours n'est pré-calculé pour aucun jour : générer coûte cher, et
 * chaque séance porte donc son propre bouton.
 */

import type { Semaine } from "../api/types";
import { duree, ecartEnJours, jourCourt, nombre } from "../api/formats";

/** L'horizon au-delà duquel on ne dit plus d'où le vent soufflera. */
const HORIZON_VENT_JOURS = 3;

interface Props {
  semaine: Semaine;
  aujourdhui: string;
  joursAvecParcours: string[];
  surGenerer: (jour: string) => void;
  surVoir: (jour: string) => void;
  surDeposer: () => void;
}

export function MaSemaine({
  semaine,
  aujourdhui,
  joursAvecParcours,
  surGenerer,
  surVoir,
  surDeposer,
}: Props) {
  const avecSeance = semaine.jours.filter((j) => j.seance !== null);

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">Depuis intervals.icu</span>
          <h1>Cette semaine</h1>
        </div>
      </div>

      {avecSeance.length === 0 ? (
        <>
          <div className="encart info">
            <b>Aucune séance planifiée du {jourCourt(semaine.depuis)} au{" "}
            {jourCourt(semaine.jusqua)}.</b>{" "}
            intervals.icu a répondu, il n'y avait rien à lire — ce n'est pas une panne de
            connexion.
          </div>
          <button type="button" className="bouton second" onClick={surDeposer}>
            Déposer une séance
          </button>
        </>
      ) : null}

      {avecSeance.map(({ jour, seance }) => {
        const ecart = ecartEnJours(jour, aujourdhui);
        const joursDEcart = Math.round(
          (Date.parse(`${jour}T12:00:00`) - Date.parse(`${aujourdhui}T12:00:00`)) / 86_400_000,
        );
        const pret = joursAvecParcours.includes(jour);
        return (
          <div className={jour === aujourdhui ? "bloc choisi" : "bloc"} key={jour}>
            <div className="bloc-tete">
              <h2>
                {jourCourt(jour)} — {seance!.nom}
              </h2>
              <span className="rang">{ecart ?? jour}</span>
            </div>
            <div className="chiffres" style={{ marginBottom: 9 }}>
              <span>
                <b>{duree(seance!.duree_s)}</b>
              </span>
              {seance!.n_blocs > 0 ? (
                <span>
                  <b>{nombre(seance!.n_blocs)}</b> blocs
                </span>
              ) : null}
              {seance!.distance_estimee_m !== null ? (
                <span>
                  <b>{nombre(seance!.distance_estimee_m / 1000, 1)}</b> km estimés
                </span>
              ) : null}
            </div>
            {pret ? (
              <button type="button" className="bouton second" onClick={() => surVoir(jour)}>
                Voir le parcours
              </button>
            ) : (
              <button type="button" className="bouton second" onClick={() => surGenerer(jour)}>
                Générer le parcours
              </button>
            )}
            {joursDEcart > HORIZON_VENT_JOURS ? (
              <p className="mention" style={{ marginTop: 9 }}>
                Sans le vent : à {joursDEcart} jours, on ne sait pas encore d'où il soufflera.
              </p>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

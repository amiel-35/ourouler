/** E15 — ma semaine. Trois séances, trois états différents.
 *
 * Une séance proche et une séance lointaine ne se traitent pas pareil :
 * au-delà de l'horizon d'orientation au vent, l'écran **dit pourquoi** le
 * vent disparaît plutôt que de l'omettre en silence (arbitrage 2 : trois
 * jours inclus, quatre non).
 *
 * Le parcours n'est pré-calculé pour aucun jour : générer coûte cher, et
 * chaque séance porte donc son propre bouton.
 *
 * **L'aperçu de la semaine** (`ApercuSemaine`) répond à une question que
 * l'écran pose : « ma semaine est-elle chargée ? » ne doit pas se lire en
 * additionnant de tête trois cartes, chacune sa propre durée en texte — le
 * genre de reconstruction mentale qu'un écran doit épargner. Sept colonnes, une par
 * jour, la hauteur pour la durée : le repos se lit d'un coup d'œil, pas en
 * cherchant l'absence d'une carte. En encre seule — la durée n'est pas une
 * des familles de données mesurées du système (pluie, vent, trafic, effort,
 * pente), lui inventer une teinte violerait la règle d'admission
 * restrictive de la doctrine (§3) pour un besoin qu'aucune teinte existante
 * ne sert et qu'aucune nouvelle teinte ne justifie.
 */

import type { Semaine } from "../api/types";
import { duree, ecartEnJours, jourCourt, nombre } from "../api/formats";

/** L'horizon au-delà duquel on ne dit plus d'où le vent soufflera. */
const HORIZON_VENT_JOURS = 3;

const LARGEUR_COL = 40;
const HAUTEUR_BARRES = 56;
const HAUTEUR_SVG = HAUTEUR_BARRES + 22;

/** Une lettre par jour (« L », « M », « M », « J »…) — la locale du
 * navigateur, pas une table française codée en dur : ce produit ne dépend
 * déjà de rien d'autre pour ses dates. */
function initialeJour(iso: string): string {
  const quand = new Date(`${iso}T12:00:00`);
  const lettre = quand.toLocaleDateString("fr-FR", { weekday: "narrow" });
  return lettre.toUpperCase();
}

/**
 * Sept colonnes, une par jour de `semaine.jours` — celui-ci les porte déjà
 * tous, séance ou non, dans l'ordre chronologique (contrat de `GET
 * /seances`). Un jour de repos est un point à la ligne de base, jamais une
 * barre à hauteur zéro : l'absence de séance n'est pas une séance de durée
 * nulle (on n'affirme rien sans mesure), et une barre à peine visible se confondrait avec
 * une vraie séance très courte.
 */
export function ApercuSemaine({ jours, aujourdhui }: { jours: Semaine["jours"]; aujourdhui: string }) {
  const dureeMax = Math.max(...jours.map((j) => j.seance?.duree_s ?? 0), 1);
  const largeur = jours.length * LARGEUR_COL;
  const total = jours.reduce((somme, j) => somme + (j.seance?.duree_s ?? 0), 0);
  const nSeances = jours.filter((j) => j.seance !== null).length;

  return (
    <svg
      className="apercu-semaine"
      viewBox={`0 0 ${largeur} ${HAUTEUR_SVG}`}
      width="100%"
      height={HAUTEUR_SVG}
      role="img"
      aria-label={`Semaine du ${jourCourt(jours[0]?.jour ?? aujourdhui)} au ${jourCourt(
        jours[jours.length - 1]?.jour ?? aujourdhui,
      )} : ${nombre(nSeances)} séance(s), ${duree(total)} au total.`}
    >
      {jours.map((j, i) => {
        const x = i * LARGEUR_COL;
        const centreX = x + LARGEUR_COL / 2;
        const estAujourdhui = j.jour === aujourdhui;
        if (j.seance === null) {
          return (
            <g key={j.jour}>
              <circle
                cx={centreX}
                cy={HAUTEUR_BARRES - 3}
                r={2.5}
                fill="none"
                stroke="var(--texte-attenue)"
                strokeWidth={1.5}
              />
              <text
                x={centreX}
                y={HAUTEUR_SVG - 4}
                textAnchor="middle"
                fontSize={11}
                fontWeight={estAujourdhui ? 700 : 400}
                fill={estAujourdhui ? "var(--texte)" : "var(--texte-attenue)"}
              >
                {initialeJour(j.jour)}
              </text>
              <title>{`${jourCourt(j.jour)} : repos`}</title>
            </g>
          );
        }
        const hauteur = Math.max((j.seance.duree_s / dureeMax) * (HAUTEUR_BARRES - 6), 4);
        return (
          <g key={j.jour}>
            <rect
              x={x + LARGEUR_COL * 0.22}
              y={HAUTEUR_BARRES - hauteur}
              width={LARGEUR_COL * 0.56}
              height={hauteur}
              fill={estAujourdhui ? "var(--texte)" : "var(--texte-faible)"}
            />
            <text
              x={centreX}
              y={HAUTEUR_SVG - 4}
              textAnchor="middle"
              fontSize={11}
              fontWeight={estAujourdhui ? 700 : 400}
              fill={estAujourdhui ? "var(--texte)" : "var(--texte-attenue)"}
            >
              {initialeJour(j.jour)}
            </text>
            {/* Juste la durée, pas les blocs : la carte juste en dessous
                les porte déjà. Un second nombre ajouté ici, séparé du
                premier par une virgule, entrait par hasard en collision
                avec un autre — trouvé par `tests/provenance.test.tsx`, qui
                compare le texte affiché entre deux jeux de données
                disjoints : sans séparateur entre deux `<span>` voisins,
                deux nombres fusionnent en un seul token dans le texte
                sérialisé (« 13 » et « 3 » lus comme « 133 ») ; avec une
                virgule, ils redeviennent deux tokens distincts, et l'un
                d'eux peut alors coïncider avec un nombre sans rapport de
                l'autre rendu. Pas un bug de fond, juste un second nombre
                que la carte du dessous porte déjà — inutile de le
                répéter ici. */}
            <title>{`${jourCourt(j.jour)} : ${duree(j.seance.duree_s)}`}</title>
          </g>
        );
      })}
      {/* La ligne de base : le repère commun à toutes les colonnes, sans
          lequel un point de repos et le pied d'une barre ne se liraient pas
          sur la même échelle. */}
      <line
        x1={0}
        y1={HAUTEUR_BARRES}
        x2={largeur}
        y2={HAUTEUR_BARRES}
        stroke="var(--trait)"
        strokeWidth={1}
      />
    </svg>
  );
}

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

      <div className="apercu-semaine-conteneur">
        <ApercuSemaine jours={semaine.jours} aujourdhui={aujourdhui} />
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
            <div className="chiffres espace">
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
              <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
                Sans le vent : à {joursDEcart} jours, on ne sait pas encore d'où il soufflera.
              </p>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

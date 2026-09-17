/** Lot F2.4 — **toutes** les candidates, avec leur sort et sa raison.
 *
 * Le défaut que ce panneau corrige, dans les mots du mainteneur : « je veux
 * visuellement voir le souci ». Le produit montrait ce qu'il retenait, jamais
 * ce qu'il avait jeté ni pourquoi — et c'est au **contraste** que ses
 * candidates disparaissaient, l'étape dont rien ne sortait à l'écran.
 *
 * Deux formes étaient possibles : court-circuiter l'arbitrage pour voir les
 * rejets bruts, ou tout montrer avec la décision. C'est la seconde — voir les
 * écartées sans savoir pourquoi n'apprend rien.
 *
 * **Ce que ce panneau doit rendre évident**, et c'est ce qui a motivé la
 * demande : un groupe est disqualifié par **une seule** mauvaise paire. La
 * moyenne des recouvrements ne prédit pas le résultat ; c'est l'existence
 * d'un groupe dont *toutes* les paires passent qui décide. D'où la matrice
 * complète plutôt qu'une liste de motifs : une case rouge se voit, et on voit
 * du même coup qu'elle interdit toutes les lignes qui la traversent.
 *
 * **Aucun chiffre n'est calculé ici.** Les pourcentages, les verdicts, les
 * phrases et le compte des groupes essayés viennent tous de
 * `sortie/contraste.py` (doctrine §10.2, règle absolue 5). Ce fichier met en
 * page, il ne mesure pas.
 */

import type { Arbitrage, Candidate, Ecartee, VerdictCandidate } from "../api/types";
import { directionEnToutesLettres, kmDepuisKm, nombre, pourcentage } from "../api/formats";

/** Ce que chaque sort s'appelle à l'écran, et la classe qui le colore. */
const SORTS: Record<string, { mot: string; classe: string }> = {
  retenue: { mot: "Retenue", classe: "sort-retenue" },
  trop_proche: { mot: "Écartée", classe: "sort-ecartee" },
  place_prise: { mot: "Pas de place", classe: "sort-place" },
};

function sortDe(verdict: VerdictCandidate) {
  return SORTS[verdict.sort] ?? { mot: verdict.sort, classe: "sort-place" };
}

/** Combien de candidates le contraste a réellement écartées. */
export function compteEcartees(arbitrage: Arbitrage | null | undefined): number {
  if (!arbitrage) return 0;
  return arbitrage.candidates.filter((c) => c.sort !== "retenue").length;
}

/**
 * Le titre du dépliant : il dit ce qu'on va voir, pas « détails ».
 *
 * Le compte vient de la réponse. Zéro écartée est un état qui se dit aussi —
 * « les 3 candidates ont été retenues » — parce que le silence laisserait
 * croire que l'arbitrage n'a pas eu lieu.
 */
export function titreArbitrage(arbitrage: Arbitrage): string {
  const jetees = compteEcartees(arbitrage);
  const total = arbitrage.candidates.length;
  if (jetees === 0) {
    return `Pourquoi ces parcours — les ${nombre(total)} candidates ont toutes été retenues`;
  }
  return `Voir les ${nombre(jetees)} candidates écartées, et pourquoi`;
}

/** La matrice des routes communes, deux à deux. */
function Matrice({ arbitrage }: { arbitrage: Arbitrage }) {
  const numeros = arbitrage.candidates.map((c) => c.numero);
  const part = new Map(
    arbitrage.paires.flatMap((p) => [
      [`${p.a}-${p.b}`, p],
      [`${p.b}-${p.a}`, p],
    ] as [string, (typeof arbitrage.paires)[number]][]),
  );
  return (
    <div className="matrice-cadre">
      <table className="matrice">
        <caption>
          Part de routes communes, deux à deux. Au-delà de{" "}
          {pourcentage(arbitrage.seuil_recouvrement)}, les deux boucles vont au même endroit
          et ne peuvent pas être proposées ensemble.
        </caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="invisible">Candidate</span>
            </th>
            {numeros.map((n) => (
              <th scope="col" key={n}>
                n° {nombre(n)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {numeros.map((ligne) => (
            <tr key={ligne}>
              <th scope="row">n° {nombre(ligne)}</th>
              {numeros.map((colonne) => {
                if (ligne === colonne) {
                  return (
                    <td key={colonne} className="case-diagonale" aria-label="elle-même">
                      —
                    </td>
                  );
                }
                const paire = part.get(`${ligne}-${colonne}`);
                if (!paire) return <td key={colonne}>·</td>;
                return (
                  <td
                    key={colonne}
                    className={paire.au_dessus_du_seuil ? "case-au-dessus" : "case-sous"}
                  >
                    {pourcentage(paire.recouvrement)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface Props {
  arbitrage: Arbitrage;
  /** Les candidates, pour leurs kilomètres et leur dénivelé. */
  candidates: Candidate[];
  /** Les candidates tombées **avant** le contraste, s'il y en a. */
  ecartees: Ecartee[];
  /** Ouvert ? Le parent le sait, parce que la carte change avec. */
  ouvert: boolean;
  surBascule: (ouvert: boolean) => void;
}

export function PanneauArbitrage({
  arbitrage,
  candidates,
  ecartees,
  ouvert,
  surBascule,
}: Props) {
  const parNumero = new Map(candidates.map((c) => [c.numero, c]));
  return (
    <details
      className="arbitrage"
      open={ouvert}
      onToggle={(evenement) => surBascule((evenement.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>{titreArbitrage(arbitrage)}</summary>

      <p className="mention">
        Toutes les candidates sont sur la carte ci-dessus quand ce panneau est ouvert :
        les retenues en trait plein ou pointillé gris, les écartées en trait rouge fin.
      </p>

      <ol className="verdicts">
        {arbitrage.candidates.map((verdict) => {
          const candidate = parNumero.get(verdict.numero) ?? null;
          const { mot, classe } = sortDe(verdict);
          return (
            <li key={verdict.numero} className={classe}>
              <div className="verdict-tete">
                <b>n° {nombre(verdict.numero)}</b>
                <span className={`etiquette ${classe}`}>{mot}</span>
              </div>
              {candidate ? (
                <div className="chiffres">
                  <span>
                    <b>{kmDepuisKm(candidate.distance_km)}</b>
                  </span>
                  {candidate.denivele_m !== null && candidate.denivele_m !== undefined ? (
                    <span>
                      <b>{nombre(candidate.denivele_m)}</b> m D+
                    </span>
                  ) : null}
                  {/* La direction en toutes lettres, jamais l'azimut brut :
                      c'est un paramètre du traceur, et le produit a déjà
                      décidé qu'il ne s'affiche pas tel quel. */}
                  {candidate.azimut_deg !== null && candidate.azimut_deg !== undefined ? (
                    <span>{directionEnToutesLettres(String(candidate.azimut_deg))}</span>
                  ) : null}
                </div>
              ) : null}
              {/* La phrase du cœur, telle quelle : c'est elle qui porte le
                  pourcentage et le numéro de la boucle contre laquelle la
                  décision s'est jouée. */}
              <p className="mention motif">{verdict.motif}</p>
            </li>
          );
        })}
      </ol>

      <Matrice arbitrage={arbitrage} />

      {/* Le point de conception, et il est mesuré, pas affirmé : le cœur a
          compté les groupes essayés et ceux qui ne tombent que sur une paire. */}
      {arbitrage.phrase ? <p className="encart info phrase-essais">{arbitrage.phrase}</p> : null}

      {ecartees.length > 0 ? (
        <div className="avant-contraste">
          <h3>
            {nombre(ecartees.length)} candidate(s) tombée(s) avant le contraste
          </h3>
          <p className="mention">
            Celles-ci n'ont jamais atteint la comparaison des tracés : la distance n'était
            pas atteignable dans cette direction, ou la séance ne tenait pas sur la boucle.
          </p>
          <ul className="verdicts">
            {ecartees.map((ecartee, rang) => (
              <li key={`${ecartee.azimut_deg ?? "?"}-${rang}`} className="sort-ecartee">
                <div className="verdict-tete">
                  <b>
                    {ecartee.azimut_deg === null
                      ? "direction inconnue"
                      : directionEnToutesLettres(String(ecartee.azimut_deg))}
                  </b>
                  <span className="etiquette sort-ecartee">
                    {ecartee.etape === "distance" ? "Distance" : "Séance"}
                  </span>
                </div>
                <div className="chiffres">
                  <span>
                    <b>{kmDepuisKm(ecartee.distance_km)}</b>
                  </span>
                </div>
                <p className="mention motif">{ecartee.motif}</p>
                {ecartee.trace === null ? (
                  <p className="mention">
                    Aucun tracé à montrer : la boucle n'a jamais été construite.
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </details>
  );
}

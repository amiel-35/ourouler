/** E20 — le détail, et le geste qui fait tout converger.
 *
 * Les blocs sont **dessinés sur le tracé**, pas listés à côté : c'est la
 * seule façon de voir qu'un bloc tombe sur une portion plate et sans
 * carrefour, ce qui est la raison d'être de l'outil. Chaque étape porte son
 * kilométrage de début et de fin, parce que c'est ce qu'on lit sur un
 * compteur en roulant.
 *
 * Le GPX de la proposition affichée se télécharge (décision du 27/09/2026 :
 * sur iPhone, la feuille de partage d'iOS ne propose pas Garmin Connect pour
 * ce fichier, donc plus de « Envoyer vers mon compteur »).
 *
 * Le découpage du tracé est dans `proposition/traceVent.ts`, le lien de
 * téléchargement dans `proposition/Onglets.tsx` (`LienGpx`), les chiffres et
 * la tenue aussi dans `proposition/Onglets.tsx`.
 */

import { useState } from "react";
import type { Candidate, Enveloppe, Seance, Sortie } from "../api/types";
import { duree, heure, heureDeRetour, nombre, jourEnLettres } from "../api/formats";
import { Carte, LegendeVent, type SegmentDessine } from "../composants/Carte";
import { RetourEnTete } from "../composants/Retour";
import { Etapes, COULEUR_TYPE } from "../composants/Etapes";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";
import { TempsEcoule } from "../composants/TempsEcoule";
import { ChiffresParcours, LienGpx, Tenue } from "./proposition/Onglets";
import { portion, segmentsVent } from "./proposition/traceVent";

export { portion, segmentsVent } from "./proposition/traceVent";

interface Props {
  reponse: Enveloppe<Sortie>;
  numero: number;
  seance: Seance | null;
  surRetour: () => void;
}

export function PropositionDetail({ reponse, numero, seance, surRetour }: Props) {
  const [onglet, setOnglet] = useState<"parcours" | "tenue">("parcours");
  const sortie = reponse.donnees;
  const proposition = sortie.propositions.find((p) => p.numero === numero) ?? null;
  const candidate: Candidate | null = sortie.candidates.find((c) => c.numero === numero) ?? null;
  const manque = meteoManquante(reponse.avertissements);

  if (proposition === null || candidate === null) {
    return (
      <section>
        <div className="vide">Cette proposition n'est plus là. Relancez une recherche.</div>
        <button type="button" className="bouton second" onClick={surRetour}>
          Revenir
        </button>
      </section>
    );
  }

  const placement = candidate.placement ?? null;
  const trace = candidate.trace;
  const segments: SegmentDessine[] =
    trace && placement
      ? placement.emplacements
          .filter((e) => (seance?.etapes[e.etape_idx]?.type ?? "") === "bloc")
          .map((e) => ({
            points: portion(trace, e.debut_m, e.debut_m + e.longueur_m),
            couleur: COULEUR_TYPE.bloc,
            titre: seance?.etapes[e.etape_idx]?.libelle ?? "Bloc",
          }))
      : [];

  const blocsProfil =
    placement && seance
      ? placement.emplacements
          .filter((e) => seance.etapes[e.etape_idx]?.type === "bloc")
          .map((e) => ({
            debut_m: e.debut_m,
            fin_m: e.debut_m + e.longueur_m,
            couleur: COULEUR_TYPE.bloc,
          }))
      : [];

  // Déjà filtrées par le cœur au seuil où le vent se sent : le front les pose
  // sur la carte sans en écarter aucune et sans en ajouter.
  const vents = candidate.meteo?.fleches_vent ?? [];
  // Le tracé entier, coloré par le vent (point 5) — pas de filtre de
  // sensibilité ici, voir `segmentsVent`.
  const traceVent =
    trace && candidate.meteo?.vent_par_position
      ? segmentsVent(trace, candidate.meteo.vent_par_position)
      : [];
  const retour = heureDeRetour(sortie.demande.depart, proposition.duree_s);

  return (
    <section>
      {/* Le retour était en bas, après la carte, le profil, les étapes et le
          bouton d'envoi au compteur : personne ne le trouvait. Son libellé
          nomme la destination — combien de parcours, et pour quel jour — au
          lieu de dire « Retour », qui ne dit pas où. */}
      <RetourEnTete
        vers={
          // Le cœur ne rend pas toujours trois propositions, et « Les 1
          // parcours du samedi 19 » se lisait comme une faute plutôt que
          // comme un chiffre.
          sortie.propositions.length === 1
            ? `Le parcours du ${jourEnLettres(sortie.jour)}`
            : `Les ${nombre(sortie.propositions.length)} parcours du ${jourEnLettres(sortie.jour)}`
        }
        surRetour={surRetour}
      />
      <div className="app-tete">
        <div>
          <span className="quand">
            {heure(sortie.demande.depart)} · {sortie.demande.lieu_depart.nom}
            {retour ? ` · retour vers ${retour}` : ""}
          </span>
          {/* `distinction` peut être une chaîne vide quand le cœur n'a trouvé
              aucun axe qui distingue : `??` ne l'aurait pas rattrapée, et le
              titre serait resté blanc. */}
          <h1>{proposition.distinction || `Proposition ${proposition.numero}`}</h1>
          {sortie.seance ? <p className="mention">{sortie.seance.nom}</p> : null}
        </div>
        <div className="a-droite">
          <div className="grand secondaire">
            {nombre(candidate.distance_km, 1)}
            <small>km</small>
          </div>
        </div>
      </div>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

      <div className="segments">
        <button
          type="button"
          aria-pressed={onglet === "parcours"}
          onClick={() => setOnglet("parcours")}
        >
          Le parcours
        </button>
        <button type="button" aria-pressed={onglet === "tenue"} onClick={() => setOnglet("tenue")}>
          La tenue
        </button>
      </div>

      {onglet === "parcours" ? (
        <>
          {trace ? (
            <>
              <Carte
                traces={[{ points: trace.points, choisi: true }]}
                segments={segments}
                traceVent={traceVent}
                vents={vents}
                depart={sortie.demande.lieu_depart}
                description={`Boucle de ${nombre(candidate.distance_km, 1)} kilomètres, blocs de la séance en surbrillance${vents.length > 0 ? `, ${vents.length} flèches de vent le long du tracé` : ""}`}
              />
              <LegendeVent
                vents={vents}
                seuilKmh={sortie.question_vent?.seuil_kmh ?? null}
                traceColoree={traceVent.length > 0}
              />
              <ProfilAltitude profil={trace.profil} blocs={blocsProfil} />
            </>
          ) : (
            <div className="encart attention">
              <b>Pas de tracé.</b> Les chiffres du parcours sont là, mais pas son dessin : rien à
              montrer sur la carte, et rien à envoyer au compteur.
            </div>
          )}

          <ChiffresParcours proposition={proposition} candidate={candidate} />

          <TempsEcoule candidate={candidate} compteur={sortie.compteur} />

          {seance && seance.etapes.length > 0 ? (
            <Etapes etapes={seance.etapes} emplacements={placement?.emplacements} />
          ) : (
            <p className="mention" style={{ marginBottom: "var(--espace-champ)" }}>
              Pas de séance sur ce parcours : c'est une boucle d'endurance, à tenir à
              l'allure de votre Z2.
            </p>
          )}

          {placement && placement.decalage_z2_s !== 0 ? (
            <div className="encart info">
              <b>
                Z2 d'ouverture{" "}
                {placement.decalage_z2_s > 0 ? "allongée" : "raccourcie"} de{" "}
                {duree(Math.abs(placement.decalage_z2_s))}
              </b>{" "}
              pour placer les blocs au mieux : l'échauffement coulisse, et les blocs
              coulissent avec lui.
            </div>
          ) : null}

          {placement?.informations.map((phrase) => (
            <div className="encart info" key={phrase}>
              {phrase}
            </div>
          ))}
          {placement?.avertissements.map((phrase) => (
            <div className="encart attention" key={phrase}>
              {phrase}
            </div>
          ))}

          <LienGpx proposition={proposition} />
        </>
      ) : (
        <Tenue tenue={sortie.tenue} />
      )}

      <button type="button" className="bouton fantome" onClick={surRetour}>
        Revenir aux propositions
      </button>
    </section>
  );
}

/** E20 — le détail, et le geste qui fait tout converger.
 *
 * Les blocs sont **dessinés sur le tracé**, pas listés à côté : c'est la
 * seule façon de voir qu'un bloc tombe sur une portion plate et sans
 * carrefour, ce qui est la raison d'être de l'outil. Chaque étape porte son
 * kilométrage de début et de fin, parce que c'est ce qu'on lit sur un
 * compteur en roulant.
 *
 * « Envoyer vers mon compteur » plutôt que « Télécharger » : décision Q5, le
 * partage système du mobile, qui marche avec Garmin, Coros, Wahoo et les
 * autres sans intégration par marque. Le téléchargement reste en dessous,
 * discret, pour celui qui est sur un ordinateur — et c'est le seul recours
 * quand le navigateur ne sait pas partager de fichier.
 */

import { useState } from "react";
import type { Candidate, Enveloppe, Seance, Sortie, Trace } from "../api/types";
import {
  duree,
  heure,
  heureDeRetour,
  kmDepuisKm,
  nombre,
  pourcentage,
  compteArrets,
} from "../api/formats";
import { Carte, type SegmentDessine } from "../composants/Carte";
import { Etapes, COULEUR_TYPE } from "../composants/Etapes";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";

/**
 * La portion de tracé entre deux distances, en mètres.
 *
 * `trace.profil[i][0]` est la distance cumulée au point `trace.points[i]` :
 * les deux listes ont la même longueur, c'est ce que rend le lot F0.1.
 */
export function portion(trace: Trace, debutM: number, finM: number): [number, number][] {
  const [a, b] = debutM <= finM ? [debutM, finM] : [finM, debutM];
  const points: [number, number][] = [];
  for (let i = 0; i < trace.points.length && i < trace.profil.length; i += 1) {
    const distance = trace.profil[i][0];
    if (distance >= a && distance <= b) points.push(trace.points[i]);
  }
  return points;
}

interface Props {
  reponse: Enveloppe<Sortie>;
  numero: number;
  seance: Seance | null;
  surRetour: () => void;
}

function partager(url: string, nom: string) {
  return async () => {
    try {
      const reponse = await fetch(url);
      const contenu = await reponse.blob();
      const fichier = new File([contenu], nom, { type: "application/gpx+xml" });
      const partage = navigator as Navigator & {
        canShare?: (donnees: { files: File[] }) => boolean;
        share?: (donnees: { files: File[]; title?: string }) => Promise<void>;
      };
      if (partage.share && partage.canShare?.({ files: [fichier] })) {
        await partage.share({ files: [fichier], title: nom });
        return;
      }
    } catch {
      /* le partage a été refusé ou n'existe pas : le lien du dessous reste */
    }
    window.alert(
      "Ce navigateur ne sait pas partager de fichier. Utilisez « Télécharger le GPX » " +
        "juste en dessous, puis envoyez-le à votre compteur comme d'habitude.",
    );
  };
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

  const arrets = compteArrets(proposition.densite_marqueurs_km, candidate.distance_km);
  const retour = heureDeRetour(sortie.demande.depart, proposition.duree_s);

  return (
    <section>
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
        <div style={{ textAlign: "right" }}>
          <div className="grand" style={{ fontSize: 21 }}>
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
                depart={sortie.demande.lieu_depart}
                description={`Boucle de ${nombre(candidate.distance_km, 1)} kilomètres, blocs de la séance en surbrillance`}
              />
              <ProfilAltitude profil={trace.profil} blocs={blocsProfil} />
            </>
          ) : (
            <div className="encart attention">
              <b>Pas de tracé.</b> Le moteur a rendu des chiffres mais aucune géométrie.
            </div>
          )}

          <div className="chiffres" style={{ marginBottom: 12 }}>
            <span>
              <b>{kmDepuisKm(candidate.distance_km)}</b>
            </span>
            {candidate.denivele_m !== null ? (
              <span>
                <b>{nombre(candidate.denivele_m)}</b> m D+
              </span>
            ) : null}
            {arrets !== null ? (
              <span>
                <b>{nombre(arrets)}</b> feux et stops
              </span>
            ) : null}
            {proposition.part_trafic !== null ? (
              <span>
                <b>{pourcentage(proposition.part_trafic)}</b> de trafic
              </span>
            ) : null}
            <span>
              <b>{duree(proposition.duree_s)}</b>
            </span>
          </div>

          {seance && seance.etapes.length > 0 ? (
            <Etapes etapes={seance.etapes} emplacements={placement?.emplacements} />
          ) : (
            <p className="mention" style={{ marginBottom: 12 }}>
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

          {/* Q40 (g) : chaque proposition porte **sa** trace, fabriquée au
              moment où on la demande. Auparavant un seul GPX existait, celui
              de la proposition retenue : emporter « la plus sèche » envoyait
              la trace de « la plus calme » au compteur. */}
          {proposition.gpx ? (
            <>
              <button
                type="button"
                className="bouton"
                onClick={partager(proposition.gpx.url, proposition.gpx.nom)}
              >
                Envoyer vers mon compteur
              </button>
              <a
                className="bouton fantome"
                href={proposition.gpx.url}
                download={proposition.gpx.nom}
                style={{ display: "block", textDecoration: "none" }}
              >
                Télécharger le GPX
              </a>
            </>
          ) : (
            <p className="mention">Aucun GPX n'est disponible pour ce parcours.</p>
          )}
        </>
      ) : sortie.tenue ? (
        <div>
          <div className="bloc">
            <div className="bloc-tete">
              <h2>Sur vous</h2>
              <span className="rang">
                {sortie.tenue.categorie_temp} · {sortie.tenue.categorie_humidite}
              </span>
            </div>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {sortie.tenue.base.map((piece) => (
                <li key={piece}>{piece}</li>
              ))}
            </ul>
          </div>
          {sortie.tenue.a_emporter.length > 0 ? (
            <div className="bloc doux">
              <div className="bloc-tete">
                <h2>À emporter</h2>
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {sortie.tenue.a_emporter.map((piece) => (
                  <li key={piece}>{piece}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {sortie.tenue.a_enlever.length > 0 ? (
            <div className="bloc doux">
              <div className="bloc-tete">
                <h2>À enlever en route</h2>
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {sortie.tenue.a_enlever.map((piece) => (
                  <li key={piece}>{piece}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {sortie.tenue.motifs.map((motif) => (
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
      )}

      <button type="button" className="bouton fantome" onClick={surRetour}>
        Revenir aux propositions
      </button>
    </section>
  );
}

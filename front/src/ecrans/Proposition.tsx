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
import type { Candidate, Enveloppe, Seance, Sortie, Trace, VentPosition } from "../api/types";
import { type PanneGpx, recupererGpx } from "../api/client";
import {
  duree,
  heure,
  heureDeRetour,
  kmDepuisKm,
  nombre,
  pourcentage,
  compteArrets,
  visibleEnKm,
  jourEnLettres,
} from "../api/formats";
import { Carte, LegendeVent, type SegmentDessine, type SegmentVent } from "../composants/Carte";
import { RetourEnTete } from "../composants/Retour";
import { Etapes, COULEUR_TYPE } from "../composants/Etapes";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";
import { DureesDeSortie, TempsEcoule } from "../composants/TempsEcoule";

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

/**
 * Colore le tracé lui-même par ce que le vent y coûte (point 5 du lot
 * d'affordance, 20/09/2026) — pas seulement les huit flèches.
 *
 * `positions` couvre le tracé entier, échantillon par échantillon, sans
 * filtre de sensibilité (`vent_par_position`, voir sa docstring côté cœur).
 * Chaque **intervalle** entre deux échantillons consécutifs porte la
 * catégorie de l'échantillon qui l'ouvre (« le vent mesuré ici vaut jusqu'au
 * prochain échantillon ») ; les intervalles consécutifs de même catégorie
 * sont fusionnés en une seule portion, pour ne pas redessiner un segment
 * par échantillon. **Point de relecture du 20/09/2026** : une version
 * antérieure fusionnait les échantillons eux-mêmes plutôt que les
 * intervalles entre eux, ce qui laissait un trou d'un pas d'échantillonnage
 * (5 km par défaut) à chaque changement de catégorie — un vent qui bascule
 * souvent de face à dos sur une boucle se serait retrouvé troué à chaque
 * bascule. Fusionner les intervalles élimine le trou : la borne de fin d'une
 * portion est toujours la borne de début de la suivante.
 *
 * Le travers et l'inconnu ne produisent aucune portion — le tracé noir de
 * base reste visible en dessous, exactement comme la direction le demande
 * pour ces deux cas (règle absolue 5, et « le vent traversier n'a
 * délibérément aucune teinte »).
 *
 * Une portion dont `portion()` ne retrouve aucun point réel (bornes trop
 * rapprochées pour qu'un point du tracé simplifié tombe entre les deux,
 * notamment aux confins du tracé) est écartée plutôt que poussée vide :
 * sans ce filtre, `traceColoree` (l'écran) mentait — la légende affirmait
 * une coloration que `Carte` n'aurait de toute façon pas dessinée
 * (`Carte.tsx` écarte déjà un segment à moins de deux points, mais après
 * que l'écran a cru, à tort, qu'il y en avait un).
 */
export function segmentsVent(trace: Trace, positions: VentPosition[]): SegmentVent[] {
  const segments: SegmentVent[] = [];
  let i = 0;
  const n = positions.length;
  while (i < n - 1) {
    const categorie = positions[i].relatif;
    if (categorie !== "face" && categorie !== "dos") {
      i += 1;
      continue;
    }
    let j = i;
    while (j + 1 < n - 1 && positions[j + 1].relatif === categorie) j += 1;
    const points = portion(trace, positions[i].dist_m, positions[j + 1].dist_m);
    if (points.length >= 2) {
      segments.push({
        points,
        categorie,
        titre: categorie === "face" ? "Vent de face" : "Vent dans le dos",
      });
    }
    i = j + 1;
  }
  return segments;
}

interface Props {
  reponse: Enveloppe<Sortie>;
  numero: number;
  seance: Seance | null;
  surRetour: () => void;
}

function partager(url: string, nom: string, surEchec: (panne: PanneGpx | null) => void) {
  return async () => {
    // Un nouvel essai efface la panne du précédent : sinon le message reste
    // affiché même quand l'essai suivant réussit.
    surEchec(null);
    let contenu: Blob;
    try {
      contenu = await recupererGpx(url);
    } catch (panne) {
      // Le serveur a refusé, ou le réseau ne répond pas : ni l'un ni l'autre
      // n'est une affaire de navigateur, et dire « ce navigateur ne sait pas
      // partager » serait faux ici — c'est exactement le défaut trouvé le
      // 18/09/2026.
      surEchec(panne as PanneGpx);
      return;
    }
    try {
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
  // La panne du partage GPX, quand c'est le serveur (ou le réseau) qui a
  // refusé plutôt que le navigateur : un écran ne peut pas rester muet sur
  // ce cas (18/09/2026).
  const [erreurGpx, setErreurGpx] = useState<PanneGpx | null>(null);
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
  const arrets = compteArrets(proposition.feux, proposition.stops);
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
                onClick={partager(proposition.gpx.url, proposition.gpx.nom, setErreurGpx)}
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
      ) : sortie.tenue ? (
        <div>
          <div className="bloc">
            <div className="bloc-tete">
              <h2>Sur vous</h2>
              <span className="rang">
                {sortie.tenue.categorie_temp} · {sortie.tenue.categorie_humidite}
              </span>
            </div>
            <ul className="liste-simple">
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
              <ul className="liste-simple">
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
              <ul className="liste-simple">
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

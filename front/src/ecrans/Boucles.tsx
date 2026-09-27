/** Le résultat d'une boucle libre — sans séance, donc sans placement.
 *
 * `POST /boucles` ne rend **pas** de `propositions` : pas de phrase qui
 * distingue, pas d'axe de contraste. Fabriquer ces phrases côté front aurait
 * été inventer ce que le cœur n'a pas dit ; l'écran montre donc ce qui
 * existe vraiment — les chiffres de chaque candidate — et laisse le cycliste
 * comparer lui-même.
 *
 * Comme pour une sortie, **un seul GPX est écrit** : celui de la candidate
 * retenue par le moteur. Le bouton d'envoi ne s'affiche que là.
 *
 * « Envoyer vers mon compteur » réutilise `BoutonsGpx` (`composants/BoutonsGpx.tsx`),
 * partagé avec l'écran de proposition d'une sortie
 * (`ecrans/proposition/Onglets.tsx`) : même bouton, même encart d'échec,
 * même distinction entre une panne du serveur et un navigateur qui ne sait
 * pas partager de fichier.
 */

import { useState } from "react";
import type { Boucle, Enveloppe } from "../api/types";
import type { PanneGpx } from "../api/client";
import {
  heure,
  kmDepuisKm,
  nombre,
  pourcentage,
  titreDeBoucle,
  directionEnToutesLettres,
  visibleEnKm,
} from "../api/formats";
import { Carte, LegendeVent } from "../composants/Carte";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";
import { DureesDeSortie, TempsEcoule } from "../composants/TempsEcoule";
import { JaugePluie } from "../composants/JaugePluie";
import { BoutonsGpx } from "../composants/BoutonsGpx";

interface Props {
  reponse: Enveloppe<Boucle>;
  surRetour: () => void;
}

export function Boucles({ reponse, surRetour }: Props) {
  const boucle = reponse.donnees;
  const retenue = boucle.candidates.find((c) => c.retenue) ?? boucle.candidates[0] ?? null;
  const [choisie, setChoisie] = useState<number | null>(retenue?.numero ?? null);
  const active = boucle.candidates.find((c) => c.numero === choisie) ?? null;
  const manque = meteoManquante(reponse.avertissements);
  const [erreurGpx, setErreurGpx] = useState<PanneGpx | null>(null);

  if (boucle.candidates.length === 0) {
    return (
      <section>
        <div className="app-tete">
          <div>
            <span className="quand">{boucle.depart.nom}</span>
            <h1>Aucune boucle</h1>
          </div>
        </div>
        <div className="encart alerte">
          La recherche a abouti, mais aucune boucle ne tenait dans la distance demandée.
        </div>
        <button type="button" className="bouton second" onClick={surRetour}>
          Modifier la demande
        </button>
      </section>
    );
  }

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">
            {boucle.depart.nom} · {heure(boucle.depart.heure)} ·{" "}
            {directionEnToutesLettres(boucle.demande.direction)}
          </span>
          <h1>
            {nombre(boucle.candidates.length)} boucle
            {boucle.candidates.length > 1 ? "s" : ""}
          </h1>
        </div>
        {/* « Modifier » seul ne disait pas ce qu'on modifiait ni où l'on
            atterrissait. C'est la sortie de cet écran : elle se nomme. */}
        <button type="button" className="lien" onClick={surRetour}>
          Modifier la demande
        </button>
      </div>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

      <Carte
        traces={boucle.candidates.map((candidate) => ({
          points: candidate.trace?.points ?? [],
          choisi: candidate.numero === choisie,
          // Surtout pas `candidate.nom` : c'est « Boucle 115° 27.6 km », où
          // « 27.6 km » est le **rayon** demandé au traceur — la même fuite
          // et le même mensonge de dix-neuf kilomètres que dans le titre.
          titre: titreDeBoucle(candidate.azimut_deg, candidate.numero),
        }))}
        vents={active?.meteo?.fleches_vent ?? []}
        depart={boucle.depart}
        haute
        description={`${boucle.candidates.length} boucle(s) au départ de ${boucle.depart.nom}`}
      />
      <LegendeVent vents={active?.meteo?.fleches_vent ?? []} />

      {active?.trace ? <ProfilAltitude profil={active.trace.profil} /> : null}

      {boucle.candidates.map((candidate) => (
        <div
          className={candidate.numero === choisie ? "bloc choisi" : "bloc"}
          key={candidate.numero}
        >
          <button
            type="button"
            className="carte-bouton"
            onClick={() => {
              // La panne d'envoi appartient à la candidate affichée quand
              // elle est survenue : en changer sans la vider ferait
              // réapparaître un message qui ne concerne plus rien à l'écran.
              setChoisie(candidate.numero);
              setErreurGpx(null);
            }}
            aria-pressed={candidate.numero === choisie}
          >
            <div className="bloc-tete">
              <h2>{titreDeBoucle(candidate.azimut_deg, candidate.numero)}</h2>
              <span className="rang">{candidate.retenue ? "Retenue" : candidate.numero}</span>
            </div>
            <div className="chiffres">
              <span>
                <b>{kmDepuisKm(candidate.distance_km)}</b>
              </span>
              {candidate.denivele_m !== null ? (
                <span>
                  <b>{nombre(candidate.denivele_m)}</b> m D+
                </span>
              ) : null}
              {/* Le porte à porte en majeur, le temps sans arrêt juste à
                  côté : qui demande 5 h veut lire 5 h. */}
              <DureesDeSortie
                mouvementS={candidate.temps_estime_s}
                ecouleS={candidate.temps_ecoule_s}
                basS={candidate.temps_ecoule_bas_s}
                hautS={candidate.temps_ecoule_haut_s}
              />
              {candidate.meteo?.pluie_cumulee_mm !== null &&
              candidate.meteo?.pluie_cumulee_mm !== undefined ? (
                <JaugePluie
                  mm={candidate.meteo.pluie_cumulee_mm}
                  minutesPluie={candidate.meteo.minutes_pluie}
                />
              ) : null}
              {candidate.meteo?.part_vent_face !== null &&
              candidate.meteo?.part_vent_face !== undefined ? (
                <span>
                  <b>{pourcentage(candidate.meteo.part_vent_face)}</b> de vent de face
                </span>
              ) : null}
              {/* « 88,9 km au calme » ne disait ni ce qu'était le calme, ni
                  qu'il manquait deux tiers de la distance. Les trois chiffres
                  du cœur sont là, tous les trois : ensemble ils font la
                  distance, et c'est ce qui permet de le vérifier à l'œil. Le
                  troisième n'apparaît que lorsqu'il existe — ce qui n'existe
                  pas ne se tait pas, il n'est simplement pas. */}
              {candidate.couts ? (
                <>
                  <span>
                    <b>{nombre(candidate.couts.km_calme, 1)}</b> km de petites routes
                  </span>
                  <span>
                    <b>{nombre(candidate.couts.km_trafic, 1)}</b> km de routes passantes
                  </span>
                  {visibleEnKm(candidate.couts.km_non_classe) ? (
                    <span>
                      <b>{nombre(candidate.couts.km_non_classe, 1)}</b> km qu'on ne sait
                      pas classer
                    </span>
                  ) : null}
                </>
              ) : null}
            </div>
          </button>
          {/* Hors du bouton exprès : un `<details>` dans un `<button>` est
              un contrôle interactif imbriqué dans un autre, invalide en
              HTML. */}
          <TempsEcoule candidate={candidate} compteur={boucle.compteur} />
        </div>
      ))}

      <p className="mention">
        Petites routes et routes passantes : c'est le type de voie porté par la carte
        qui les sépare, pas une mesure du trafic réel. Le reste — chemins, voies sans
        type — est compté à part parce qu'on ne sait pas ce qui y passe, et le compter
        comme calme ferait passer un tracé inconnu pour un tracé tranquille.
      </p>

      {boucle.gpx && active?.retenue ? (
        <BoutonsGpx gpx={boucle.gpx} erreur={erreurGpx} surErreur={setErreurGpx} classeLien="bouton" />
      ) : boucle.gpx ? (
        <p className="mention">
          Le GPX prêt est celui de la boucle retenue, pas de celle-ci.
        </p>
      ) : null}

      <p className="mention centre">Calculé en {nombre(reponse.duree_ms / 1000, 1)} s.</p>
    </section>
  );
}

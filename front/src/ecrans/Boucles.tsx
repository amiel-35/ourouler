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
 */

import { useState } from "react";
import type { Boucle, Enveloppe } from "../api/types";
import {
  duree,
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
import { TempsEcoule } from "../composants/TempsEcoule";

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
          // « 27.6 km » est le **rayon** demandé au traceur. Le titre avait
          // été nettoyé (relecture F2 · C6), l'infobulle de la carte gardait
          // la même fuite et le même mensonge de dix-neuf kilomètres.
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
            onClick={() => setChoisie(candidate.numero)}
            aria-pressed={candidate.numero === choisie}
            style={{ all: "unset", display: "block", width: "100%", cursor: "pointer" }}
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
              {candidate.temps_estime_s ? (
                // « 3 h 57 » nu se lisait comme une durée totale. C'est le
                // temps de mouvement du modèle physique — le mot le dit, le
                // second chiffre (sous le bloc) dit le reste.
                <span>
                  <b>{duree(candidate.temps_estime_s)}</b> en roulant
                </span>
              ) : null}
              {candidate.meteo?.pluie_cumulee_mm !== null &&
              candidate.meteo?.pluie_cumulee_mm !== undefined ? (
                <span>
                  <b>{nombre(candidate.meteo.pluie_cumulee_mm, 1)}</b> mm de pluie
                </span>
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
        <a
          className="bouton"
          href={boucle.gpx.url}
          download={boucle.gpx.nom}
          style={{ display: "block", textDecoration: "none" }}
        >
          Télécharger le GPX
        </a>
      ) : boucle.gpx ? (
        <p className="mention">
          Le GPX prêt est celui de la boucle retenue, pas de celle-ci.
        </p>
      ) : null}

      <p className="mention" style={{ textAlign: "center", marginTop: 10 }}>
        Calculé en {nombre(reponse.duree_ms / 1000, 1)} s.
      </p>
    </section>
  );
}

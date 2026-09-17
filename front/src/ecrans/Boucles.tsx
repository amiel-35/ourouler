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
import { duree, heure, kmDepuisKm, nombre, pourcentage, titreDeBoucle } from "../api/formats";
import { Carte } from "../composants/Carte";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";

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
          Le moteur a répondu, mais rien ne tenait dans la distance demandée.
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
            {boucle.depart.nom} · {heure(boucle.depart.heure)} · {boucle.demande.direction}
          </span>
          <h1>
            {nombre(boucle.candidates.length)} boucle
            {boucle.candidates.length > 1 ? "s" : ""}
          </h1>
        </div>
        <button type="button" className="lien" onClick={surRetour}>
          Modifier
        </button>
      </div>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

      <Carte
        traces={boucle.candidates.map((candidate) => ({
          points: candidate.trace?.points ?? [],
          choisi: candidate.numero === choisie,
          titre: candidate.nom,
        }))}
        depart={boucle.depart}
        haute
        description={`${boucle.candidates.length} boucle(s) au départ de ${boucle.depart.nom}`}
      />

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
                <span>
                  <b>{duree(candidate.temps_estime_s)}</b>
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
              {candidate.couts ? (
                <span>
                  <b>{nombre(candidate.couts.km_calme, 1)}</b> km au calme
                </span>
              ) : null}
            </div>
          </button>
        </div>
      ))}

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
          Le GPX écrit est celui de la boucle retenue par le moteur, pas de celle-ci.
        </p>
      ) : null}

      <p className="mention" style={{ textAlign: "center", marginTop: 10 }}>
        Calculé en {nombre(reponse.duree_ms / 1000, 1)} s.
      </p>
    </section>
  );
}

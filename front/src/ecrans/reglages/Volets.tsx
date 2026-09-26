/** Les volets de saisie des Réglages : identité, FTP, poids, clé intervals.icu.
 *
 * Composants sans état propre : la saisie reste tenue par `Reglages`, pour
 * qu'un volet refermé puis rouvert retrouve ce qu'on y avait tapé.
 */

import { api } from "../../api/client";
import type { EtatCalibrations, Zones } from "../../api/types";
import { CalibrationVelo } from "../../composants/CalibrationVelo";
import { EcranFtp } from "../../composants/EcranFtp";

/** Ce que `Reglages.enregistrer` attend : les sections modifiées et la phrase de réussite. */
export type Enregistrer = (sections: Record<string, unknown>, phrase: string) => Promise<void>;

export function VoletIdentite({
  prenom,
  nom,
  surPrenom,
  surNom,
  enregistrer,
}: {
  prenom: string;
  nom: string;
  surPrenom: (valeur: string) => void;
  surNom: (valeur: string) => void;
  enregistrer: Enregistrer;
}) {
  return (
    <div className="bloc">
      <div className="champ">
        <label htmlFor="reglages-prenom">Prénom</label>
        <input
          className="saisie"
          id="reglages-prenom"
          value={prenom}
          onChange={(e) => surPrenom(e.target.value)}
        />
      </div>
      <div className="champ">
        <label htmlFor="reglages-nom">Nom</label>
        <input
          className="saisie"
          id="reglages-nom"
          value={nom}
          onChange={(e) => surNom(e.target.value)}
        />
        <div className="aide">
          La base du compte (17/09/2026). Aucun calcul ne s'en sert aujourd'hui ; l'usage
          prévu est le compte multi-utilisateurs du lot F3.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        disabled={prenom.trim() === "" || nom.trim() === ""}
        onClick={() =>
          enregistrer(
            { cycliste: { prenom: prenom.trim(), nom: nom.trim() } },
            "Identité enregistrée.",
          )
        }
      >
        Enregistrer
      </button>
    </div>
  );
}

export function VoletFtp({
  zones,
  surZones,
  enregistrer,
}: {
  zones: Zones;
  surZones: (zones: Zones) => void;
  enregistrer: Enregistrer;
}) {
  return (
    <div className="bloc">
      <EcranFtp
        zones={zones}
        surApercu={surZones}
        surFtp={(ftp) => enregistrer({ cycliste: { ftp_w: ftp } }, "FTP enregistrée.")}
      />
      <button
        type="button"
        className="bouton"
        onClick={() =>
          enregistrer(
            { seance: { position_zone: zones.position_zone } },
            "Position dans la zone enregistrée — pas les watts : si votre FTP change, tout suit.",
          )
        }
      >
        Enregistrer cette allure
      </button>
    </div>
  );
}

export function VoletPoids({
  poids,
  surPoids,
  enregistrer,
}: {
  poids: string;
  surPoids: (valeur: string) => void;
  enregistrer: Enregistrer;
}) {
  return (
    <div className="bloc">
      <div className="champ">
        <label htmlFor="poids">Votre poids, équipé</label>
        <div className="saisie-unite">
          <input
            className="saisie mono"
            id="poids"
            inputMode="decimal"
            value={poids}
            onChange={(e) => surPoids(e.target.value)}
          />
          <span className="unite">kg</span>
        </div>
        <div className="aide">
          Le poids total — vous, le vélo, ce que vous emportez — entre dans le calcul du
          temps.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        onClick={() =>
          enregistrer(
            { cycliste: { masse_kg: Number(poids.replace(",", ".")) } },
            "Poids enregistré.",
          )
        }
      >
        Enregistrer
      </button>
    </div>
  );
}

export function VoletIntervals({
  cle,
  surCle,
  verification,
  dit,
  panne,
  surEnregistrer,
}: {
  cle: string;
  surCle: (valeur: string) => void;
  verification: boolean;
  dit: string | null;
  panne: string | null;
  surEnregistrer: () => void;
}) {
  return (
    <div className="bloc">
      <div className="champ">
        <label htmlFor="cle-intervals">Votre clé intervals.icu</label>
        <input
          className="saisie mono"
          id="cle-intervals"
          value={cle}
          onChange={(e) => surCle(e.target.value)}
          placeholder="collez la clé ici"
        />
        <div className="aide">
          Réglages d'intervals.icu, tout en bas de la page, section « Developer Settings ».
          La clé est affichée en clair : masquer un secret qu'on vient de coller empêche
          de le relire pour vérifier.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        onClick={surEnregistrer}
        disabled={cle.trim() === "" || verification}
      >
        {verification ? "Vérification…" : "Enregistrer la clé"}
      </button>
      {dit ? (
        <div className="encart bien" role="status">
          {dit}
        </div>
      ) : null}
      {panne ? (
        <div className="encart alerte" role="alert">
          {panne}
        </div>
      ) : null}
    </div>
  );
}

/** La section « Vos vélos, mesurés sur vos sorties » (L9.4). */
export function SectionCalibrations({
  calibrations,
  surChoisirPneus,
  surRelire,
  surZones,
}: {
  calibrations: EtatCalibrations;
  surChoisirPneus: () => void;
  surRelire: () => void;
  surZones: (zones: Zones) => void;
}) {
  return (
    <>
      <h2>Vos vélos, mesurés sur vos sorties</h2>
      <p className="mention">
        Avec un capteur de puissance, vos propres sorties disent ce que coûte chaque vélo :
        le temps annoncé des boucles part alors de là plutôt que d'une valeur typique.
      </p>
      {calibrations.velos.map((etat) => (
        <CalibrationVelo
          key={etat.velo}
          etat={etat}
          sortiesNecessaires={calibrations.sorties_necessaires}
          ftpRenseignee={calibrations.ftp_renseignee}
          quotaRestant={calibrations.quota?.restant}
          surChoisirPneus={surChoisirPneus}
          surCalibree={() => {
            surRelire();
            api
              .zones()
              .then((reponse) => surZones(reponse.donnees))
              .catch(() => undefined);
          }}
        />
      ))}
    </>
  );
}

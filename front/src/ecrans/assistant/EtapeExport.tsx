/** T2 : un export Strava ou Garmin, déposé tout de suite ou plus tard. */

import { DepotHistorique } from "../../composants/DepotHistorique";
import type { EtatAssistant } from "./useAssistant";

export function EtapeExport({ a }: { a: EtatAssistant }) {
  const { exportChoisi, setExportChoisi, poidsConnu, aller } = a;
  return (
    <>
      <div className="segments">
        {["Strava", "Garmin", "Non"].map((choix) => (
          <button
            type="button"
            key={choix}
            aria-pressed={exportChoisi === choix}
            onClick={() => setExportChoisi(choix)}
          >
            {choix}
          </button>
        ))}
      </div>
      {exportChoisi === "Strava" || exportChoisi === "Garmin" ? (
        <>
          {/* L'import existe (`POST /activites/import`, tâche de fond) :
              deux lignes pour l'obtenir, puis le même dépôt qu'« Importer » (`DepotHistorique`),
              réutilisé plutôt que dupliqué. */}
          <p className="mention" style={{ marginBottom: 16 }}>
            {exportChoisi === "Strava" ? (
              <>
                Demandez votre export sur{" "}
                <a
                  href="https://www.strava.com/athlete/download_my_account"
                  target="_blank"
                  rel="noreferrer"
                >
                  strava.com
                </a>
                .
              </>
            ) : (
              <>
                Demandez votre export sur{" "}
                <a
                  href="https://www.garmin.com/en-US/account/datamanagement/"
                  target="_blank"
                  rel="noreferrer"
                >
                  garmin.com
                </a>
                .
              </>
            )}
            <br />
            Vous recevez une archive par courriel : déposez-la ici tout de suite, ou plus
            tard depuis « Déposer ».
          </p>
          <DepotHistorique intro={<></>} masquerTitre />
          <p className="mention" style={{ marginTop: 8 }}>
            L'import continue en fond : vous pouvez avancer dans l'assistant pendant ce
            temps-là.
          </p>
        </>
      ) : null}
      <button type="button" className="bouton" onClick={() => aller(poidsConnu ? "velo" : "poids")}>
        {exportChoisi === "Strava" || exportChoisi === "Garmin" ? "Plus tard, depuis Déposer" : "Continuer"}
      </button>
    </>
  );
}

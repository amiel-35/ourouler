/** T1 : brancher intervals.icu, puis confirmer ou corriger ce qu'on y a trouvé. */

import type { Profil } from "../../api/types";
import { nombre } from "../../api/formats";
import { surFocusSelectionner, surRelacherNePasDeselectionner } from "./arbre";
import type { EtatAssistant } from "./useAssistant";

export function EtapeT1Cle({ a, profil }: { a: EtatAssistant; profil: Profil }) {
  const { cle, setCle, enCours, aller, enregistrerCle } = a;
  return (
    <>
      <p className="mention" style={{ marginBottom: 16, fontSize: 13.5 }}>
        Si vous y planifiez vos séances, on les lit et on vous propose le parcours qui va
        avec. Sinon, vous déposerez un fichier de séance ou demanderez une boucle
        d'endurance — ça marche aussi.
      </p>
      <div className="bloc doux">
        <div className="bloc-tete">
          <h2>Où trouver votre clé</h2>
        </div>
        <div className="etapes">
          <div className="etape">
            <span className="km">1</span>
            <span className="nom">
              <b>intervals.icu</b>
              <small>Ouvrez vos réglages</small>
            </span>
            <a className="lien" href="https://intervals.icu/settings" target="_blank" rel="noreferrer">
              Ouvrir ↗
            </a>
          </div>
          <div className="etape">
            <span className="km">2</span>
            <span className="nom">
              <b>Tout en bas de la page</b>
              <small>Section « Developer Settings »</small>
            </span>
            <span />
          </div>
          <div className="etape">
            <span className="km">3</span>
            <span className="nom">
              <b>Copiez la clé</b>
              <small>Une suite de lettres et de chiffres</small>
            </span>
            <span />
          </div>
        </div>
      </div>
      <div className="champ">
        <label htmlFor="cle">Votre clé</label>
        <input className="saisie mono" id="cle" value={cle} onChange={(e) => setCle(e.target.value)} />
        <div className="aide">
          Elle est affichée en clair : masquer un secret qu'on vient de coller empêche de
          le relire, et c'est comme ça qu'on colle un espace en trop sans le voir.
        </div>
      </div>
      {profil.services.intervals.renseigne ? (
        <div className="encart bien">
          <b>Une clé est déjà enregistrée.</b> Compte {profil.services.intervals.athlete_id}.
        </div>
      ) : null}
      <div className="boutons">
        <button type="button" className="bouton second" onClick={() => aller("t2")} disabled={enCours}>
          Plus tard
        </button>
        <button
          type="button"
          className="bouton"
          disabled={cle.trim() === "" || enCours}
          onClick={enregistrerCle}
        >
          Enregistrer
        </button>
      </div>
    </>
  );
}

export function EtapeT1Confirmation({
  a,
  intervalsTrouve,
}: {
  a: EtatAssistant;
  intervalsTrouve: NonNullable<EtatAssistant["intervalsTrouve"]>;
}) {
  const {
    correctionIntervals,
    setCorrectionIntervals,
    enCours,
    confirmerIntervals,
    ftpCorrigee,
    setFtpCorrigee,
    masseCorrigee,
    setMasseCorrigee,
  } = a;
  return (
    <>
      <div className="encart info">
        On a trouvé dans votre profil Intervals : FTP {nombre(intervalsTrouve.ftp_w)} W
        {intervalsTrouve.masse_kg !== null ? `, poids ${nombre(intervalsTrouve.masse_kg, 1)} kg` : ""}.
        C'est toujours d'actualité ?
      </div>
      {!correctionIntervals ? (
        <div className="boutons">
          <button
            type="button"
            className="bouton second"
            onClick={() => setCorrectionIntervals(true)}
            disabled={enCours}
          >
            Je corrige
          </button>
          <button type="button" className="bouton" onClick={confirmerIntervals} disabled={enCours}>
            Oui
          </button>
        </div>
      ) : (
        <>
          <div className="champ">
            <label htmlFor="ftp-corrigee">FTP</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="ftp-corrigee"
                inputMode="decimal"
                value={ftpCorrigee}
                onChange={(e) => setFtpCorrigee(e.target.value)}
                onFocus={surFocusSelectionner}
                onMouseUp={surRelacherNePasDeselectionner}
              />
              <span className="unite">W</span>
            </div>
          </div>
          {intervalsTrouve.masse_kg !== null ? (
            <div className="champ">
              <label htmlFor="masse-corrigee">Poids</label>
              <div className="saisie-unite">
                <input
                  className="saisie mono"
                  id="masse-corrigee"
                  inputMode="decimal"
                  value={masseCorrigee}
                  onChange={(e) => setMasseCorrigee(e.target.value)}
                  onFocus={surFocusSelectionner}
                  onMouseUp={surRelacherNePasDeselectionner}
                />
                <span className="unite">kg</span>
              </div>
            </div>
          ) : null}
          <button type="button" className="bouton" onClick={confirmerIntervals} disabled={enCours}>
            Continuer
          </button>
        </>
      )}
    </>
  );
}

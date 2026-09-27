import { useEffect, useState } from "react";
import { api, ErreurApi } from "../../api/client";
import type { ConservationFichiers } from "../../api/types";
import { nombre } from "../../api/formats";

/**
 * Le bloc « Fichiers d'origine » du volet « Mon compte » — fiche « choix de
 * garder ou d'effacer ses fichiers d'origine ».
 *
 * Composant séparé de `MonCompteVolet` (au-delà du plafond de lignes des
 * `.tsx` du dépôt, `taille_composants.test.ts`) : il porte son propre état
 * (choix chargé à la demande, confirmation avant d'effacer), sans rapport
 * avec le mot de passe ou la suppression du compte que `MonCompteVolet`
 * garde par ailleurs.
 *
 * N'est monté que sous un compte (`aUnCompte` de l'appelant) : sans compte,
 * il n'y a pas de choix à faire, et `GET /moi/fichiers-origine` répondrait
 * de toute façon le défaut (« garder »).
 */
export function FichiersOrigineVolet() {
  const [conservation, setConservation] = useState<ConservationFichiers | null>(null);
  const [confirmation, setConfirmation] = useState(false);
  const [enCours, setEnCours] = useState(false);
  const [panne, setPanne] = useState<string | null>(null);

  useEffect(() => {
    let vivant = true;
    api
      .etatConservationFichiers()
      .then((reponse) => {
        if (vivant) setConservation(reponse.donnees);
      })
      .catch(() => {
        // Un état qui ne charge pas n'empêche pas le reste de l'écran de fonctionner.
      });
    return () => {
      vivant = false;
    };
  }, []);

  async function basculer(garder: boolean) {
    setPanne(null);
    setEnCours(true);
    try {
      const reponse = await api.definirConservationFichiers(garder);
      setConservation(reponse.donnees);
      setConfirmation(false);
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  return (
    <>
      <div className="bloc-tete">
        <h2>Fichiers d'origine</h2>
      </div>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      <div className="champ">
        <span className="cle">État</span>
        <div className="val texte">
          {conservation === null ? (
            "Chargement…"
          ) : conservation.garder ? (
            <>
              Vous gardez vos fichiers d'origine ({nombre(conservation.nombre_fichiers ?? 0)} fichier
              {(conservation.nombre_fichiers ?? 0) > 1 ? "s" : ""})
            </>
          ) : (
            "Vous ne gardez pas vos fichiers d'origine"
          )}
        </div>
      </div>
      <p className="mention">
        « Entraîner le modèle » avec vos fichiers d'origine : usage futur, pas encore utilisé
        aujourd'hui.
      </p>

      {conservation?.garder && !confirmation ? (
        <button type="button" className="lien" onClick={() => setConfirmation(true)}>
          Ne plus les garder…
        </button>
      ) : null}

      {conservation?.garder && confirmation ? (
        <>
          <div className="encart alerte">
            <p>
              Vos calibrations et votre historique restent. Si le calcul change un jour, il faudra
              redéposer un export (ou Intervals relira vos sorties).
            </p>
          </div>
          <button type="button" className="bouton" disabled={enCours} onClick={() => basculer(false)}>
            {enCours ? "Effacement…" : "Confirmer : ne plus garder mes fichiers"}
          </button>
          <button
            type="button"
            className="lien"
            disabled={enCours}
            onClick={() => setConfirmation(false)}
          >
            Annuler
          </button>
        </>
      ) : null}

      {conservation !== null && !conservation.garder ? (
        <button type="button" className="bouton" disabled={enCours} onClick={() => basculer(true)}>
          {enCours ? "Changement…" : "Garder mes fichiers d'origine"}
        </button>
      ) : null}
    </>
  );
}

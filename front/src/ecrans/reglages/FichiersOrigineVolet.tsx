import { useEffect, useState } from "react";
import { api, ErreurApi } from "../../api/client";
import type { ConservationFichiers, TacheConservation } from "../../api/types";
import { nombre } from "../../api/formats";

/** Combien de temps entre deux interrogations de `GET /moi/fichiers-origine/{id}`. */
const DELAI_INTERROGATION_MS = 1_500;

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
  const [tache, setTache] = useState<TacheConservation | null>(null);
  const [panne, setPanne] = useState<string | null>(null);

  function rechargerEtat() {
    return api.etatConservationFichiers().then((reponse) => setConservation(reponse.donnees));
  }

  useEffect(() => {
    let vivant = true;
    api
      .etatConservationFichiers()
      .then((reponse) => {
        if (!vivant) return;
        setConservation(reponse.donnees);
        // Un effacement tournait déjà (rechargement de la page pendant la
        // purge) : reprendre son suivi, plutôt que de proposer de nouveau
        // « Garder » comme si rien n'était en cours.
        if (reponse.donnees.tache) setTache(reponse.donnees.tache);
      })
      .catch(() => {
        // Un état qui ne charge pas n'empêche pas le reste de l'écran de fonctionner.
      });
    return () => {
      vivant = false;
    };
  }, []);

  // Interroge périodiquement tant que l'effacement tourne, et recharge
  // l'état final (nombre de fichiers à 0) une fois qu'il a fini.
  useEffect(() => {
    if (!tache || tache.statut !== "en_cours") return;
    const jeton = setInterval(() => {
      api
        .suivreConservation(tache.id)
        .then((reponse) => {
          setTache(reponse.donnees);
          if (reponse.donnees.statut !== "en_cours") {
            rechargerEtat().catch(() => undefined);
          }
        })
        .catch(() => {
          // Un raté d'interrogation ne coupe pas le suivi : le prochain
          // intervalle réessaie. Le serveur, lui, continue la tâche.
        });
    }, DELAI_INTERROGATION_MS);
    return () => clearInterval(jeton);
  }, [tache]);

  async function basculer(garder: boolean) {
    setPanne(null);
    setEnCours(true);
    try {
      const reponse = await api.definirConservationFichiers(garder);
      if (reponse.donnees.tache) {
        // « Ne plus garder » : la tâche de fond dérive puis efface — l'écran
        // dit « effacement en cours » jusqu'à ce qu'elle finisse.
        setTache(reponse.donnees.tache);
        setConfirmation(false);
      } else {
        // « Garder » : rien à dériver ni à effacer, la réponse est déjà finale.
        await rechargerEtat();
      }
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  const tacheEnCours = tache !== null && tache.statut === "en_cours";
  // Le choix est déjà « ne pas garder », rien ne tourne, mais des fichiers
  // restent : l'effacement a échoué, ou le serveur a redémarré pendant la
  // tâche (`api/routes/moi.py`). Un nouveau `PUT` la relance.
  const effacementIncomplet =
    !tacheEnCours && conservation !== null && !conservation.garder && conservation.nombre_fichiers > 0;

  return (
    <>
      <div className="bloc-tete">
        <h2>Fichiers d'origine</h2>
      </div>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      {tache?.statut === "echoue" ? (
        <div className="encart alerte">
          L'effacement n'a pas pu aller au bout : {tache.erreur ?? "erreur inconnue"}.
        </div>
      ) : null}
      <div className="champ">
        <span className="cle">État</span>
        <div className="val texte">
          {tacheEnCours ? (
            "Effacement en cours…"
          ) : conservation === null ? (
            "Chargement…"
          ) : conservation.garder ? (
            <>
              Vous gardez vos fichiers d'origine ({nombre(conservation.nombre_fichiers)} fichier
              {conservation.nombre_fichiers > 1 ? "s" : ""})
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

      {!tacheEnCours && conservation?.garder && !confirmation ? (
        <button type="button" className="lien" onClick={() => setConfirmation(true)}>
          Ne plus les garder…
        </button>
      ) : null}

      {!tacheEnCours && conservation?.garder && confirmation ? (
        <>
          <div className="encart alerte">
            <p>
              Vos calibrations et votre historique restent. Si le calcul change un jour, il faudra
              redéposer un export (ou Intervals relira vos sorties).
            </p>
          </div>
          <button type="button" className="bouton" disabled={enCours} onClick={() => basculer(false)}>
            {enCours ? "Lancement…" : "Confirmer : ne plus garder mes fichiers"}
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

      {effacementIncomplet && conservation !== null ? (
        <div className="encart alerte">
          <p>
            {nombre(conservation.nombre_fichiers)} fichier{conservation.nombre_fichiers > 1 ? "s" : ""}{" "}
            restent à effacer — l'effacement n'a pas pu aller au bout.
          </p>
          <button type="button" className="bouton" disabled={enCours} onClick={() => basculer(false)}>
            {enCours ? "Lancement…" : "Relancer l'effacement"}
          </button>
        </div>
      ) : null}

      {!tacheEnCours && conservation !== null && !conservation.garder ? (
        <button type="button" className="bouton" disabled={enCours} onClick={() => basculer(true)}>
          {enCours ? "Changement…" : "Garder mes fichiers d'origine"}
        </button>
      ) : null}
    </>
  );
}

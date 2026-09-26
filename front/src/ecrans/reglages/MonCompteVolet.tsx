import { useEffect, useState } from "react";
import { api, ErreurApi } from "../../api/client";

/**
 * Le volet « Mon compte » : adresse, changement de mot de passe, export,
 * suppression — les quatre gestes qui reviennent au compte.
 *
 * Composant séparé plutôt qu'un bloc de plus dans `Reglages` : il porte son propre état
 * (adresse chargée à la demande, formulaire de mot de passe, double confirmation de
 * suppression) qui n'a aucun rapport avec le profil cycliste que `Reglages` gère par
 * ailleurs — les mélanger aurait fait grossir un unique gros composant pour un gain nul.
 */
export function MonCompteVolet({ surCompteSupprime }: { surCompteSupprime: () => void }) {
  const [email, setEmail] = useState<string | null | undefined>(undefined);
  const [motDePasseActuel, setMotDePasseActuel] = useState("");
  const [nouveauMotDePasse, setNouveauMotDePasse] = useState("");
  const [envoiMotDePasse, setEnvoiMotDePasse] = useState(false);
  const [ditMotDePasse, setDitMotDePasse] = useState<string | null>(null);
  const [panneMotDePasse, setPanneMotDePasse] = useState<string | null>(null);
  const [confirmationSuppression, setConfirmationSuppression] = useState(false);
  const [suppressionEnCours, setSuppressionEnCours] = useState(false);
  const [panneSuppression, setPanneSuppression] = useState<string | null>(null);

  useEffect(() => {
    let vivant = true;
    if (email !== undefined) return;
    api
      .monCompte()
      .then((reponse) => {
        if (vivant) setEmail(reponse.donnees.email);
      })
      .catch(() => {
        if (vivant) setEmail(null);
      });
    return () => {
      vivant = false;
    };
  }, [email]);

  async function changerLeMotDePasse() {
    setPanneMotDePasse(null);
    setDitMotDePasse(null);
    setEnvoiMotDePasse(true);
    try {
      await api.changerMotDePasse(motDePasseActuel, nouveauMotDePasse);
      setMotDePasseActuel("");
      setNouveauMotDePasse("");
      setDitMotDePasse("Mot de passe changé.");
    } catch (erreur) {
      setPanneMotDePasse(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnvoiMotDePasse(false);
    }
  }

  async function confirmerLaSuppression() {
    setPanneSuppression(null);
    setSuppressionEnCours(true);
    try {
      await api.supprimerMesDonnees();
      // Le compte, ses sessions et son invitation viennent d'être effacés
      // côté serveur (`DELETE /moi`, `vie_privee.effacer_donnees`) : il n'y
      // a plus de session à fermer, seulement l'écran de connexion à
      // montrer — le même geste qu'après « Se déconnecter ».
      surCompteSupprime();
    } catch (erreur) {
      setPanneSuppression(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      setSuppressionEnCours(false);
    }
  }

  // Vrai seulement sur un déploiement hébergé avec un compte lié à cette
  // session — `GET /moi` rend `email: null` en mode personnel (un seul
  // cycliste, pas de compte) ou hébergé sans base de comptes configurée
  // (`api/routes/moi.py:mon_compte`). Changer un mot de passe ou fermer un
  // compte n'a alors aucun sens : il n'y en a pas — `DELETE /moi` viserait quand même le propriétaire local et
  // effacerait tout son cache en deux clics si les boutons restaient là.
  const aUnCompte = email !== undefined && email !== null;

  return (
    <div className="bloc">
      <div className="champ">
        <span className="cle">Adresse</span>
        <div className="val texte">
          {email === undefined ? "Chargement…" : (email ?? "aucun compte sur ce serveur")}
        </div>
      </div>

      {aUnCompte ? (
        <>
          <div className="bloc-tete">
            <h2>Changer de mot de passe</h2>
          </div>
          {ditMotDePasse ? <div className="encart bien">{ditMotDePasse}</div> : null}
          {panneMotDePasse ? <div className="encart alerte">{panneMotDePasse}</div> : null}
          <div className="champ">
            <label htmlFor="compte-mdp-actuel">Mot de passe actuel</label>
            <input
              className="saisie"
              id="compte-mdp-actuel"
              type="password"
              autoComplete="current-password"
              value={motDePasseActuel}
              onChange={(e) => setMotDePasseActuel(e.target.value)}
            />
          </div>
          <div className="champ">
            <label htmlFor="compte-mdp-nouveau">Nouveau mot de passe</label>
            <input
              className="saisie"
              id="compte-mdp-nouveau"
              type="password"
              autoComplete="new-password"
              value={nouveauMotDePasse}
              onChange={(e) => setNouveauMotDePasse(e.target.value)}
            />
          </div>
          <button
            type="button"
            className="bouton"
            disabled={
              motDePasseActuel.trim() === "" || nouveauMotDePasse.trim() === "" || envoiMotDePasse
            }
            onClick={changerLeMotDePasse}
          >
            {envoiMotDePasse ? "Changement…" : "Changer le mot de passe"}
          </button>
        </>
      ) : null}

      <div className="bloc-tete">
        <h2>Mes données</h2>
      </div>
      <div className="rangee">
        <span className="cle">Télécharger mes données</span>
        {/* Lien natif, pas un appel de ce module : le cookie de session
            (même origine) suffit à authentifier le téléchargement, comme le
            GPX d'une proposition (`Proposition.tsx`). Disponible sans compte
            aussi (mode personnel) : l'export porte sur le propriétaire de la
            session, pas sur un compte. */}
        <a className="lien" href={api.urlExportMesDonnees()} download>
          Export ZIP
        </a>
      </div>

      {aUnCompte ? (
        <>
          <div className="bloc-tete">
            <h2>Supprimer mon compte</h2>
          </div>
          {panneSuppression ? <div className="encart alerte">{panneSuppression}</div> : null}
          {!confirmationSuppression ? (
            <button
              type="button"
              className="lien"
              onClick={() => setConfirmationSuppression(true)}
            >
              Supprimer mon compte…
            </button>
          ) : (
            <>
              {/* Le texte de référence sur ce qui part et ce qui reste est
                  `vie_privee.GABARIT_LISEZ_MOI` (`api/vie_privee.py`) — repris
                  ici en substance, pas copié mot à mot (c'est un fichier
                  d'archive, pas un texte d'écran), et sans le jargon interne
                  (« doctrine du projet, §10.2 » ne veut rien dire pour un
                  cycliste). */}
              <div className="encart alerte">
                <p>
                  <b>Ceci efface définitivement</b> votre profil, vos fichiers déposés ou
                  générés, votre journal de services et votre cache d'activités. Ceci ferme
                  aussi votre compte : mot de passe, sessions ouvertes et invitation en cours
                  disparaissent avec lui.
                </p>
                <p>
                  <b>Ceci ne touche pas</b> les routes apprises de vos sorties : elles restent,
                  parce qu'elles décrivent la géographie parcourue par tous les cyclistes qui
                  utilisent ce serveur, pas seulement vous — elles ne repartent donc jamais
                  avec un compte supprimé.
                </p>
              </div>
              <button
                type="button"
                className="bouton"
                disabled={suppressionEnCours}
                onClick={confirmerLaSuppression}
              >
                {suppressionEnCours ? "Suppression…" : "Confirmer la suppression définitive"}
              </button>
              <button
                type="button"
                className="lien"
                disabled={suppressionEnCours}
                onClick={() => setConfirmationSuppression(false)}
              >
                Annuler
              </button>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}

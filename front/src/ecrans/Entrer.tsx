/** E6 · activation d'une invitation, atteint par `/entrer?jeton=…` — et son pendant,
 * `/reinitialiser?jeton=…`, la réinitialisation d'un mot de passe.
 *
 * Le lien du mail d'invitation (ou de réinitialisation), et lui seul — jamais une
 * navigation interne : le front n'a pas de routeur, `App.tsx` lit
 * `window.location.pathname` une fois au démarrage et choisit cet écran plutôt que
 * l'application. Le jeton est retiré de la barre d'adresse dès qu'il est lu
 * (`history.replaceState`, fait par l'appelant) : il n'a rien à faire dans
 * l'historique du navigateur ni dans un en-tête `Referer`.
 *
 * **Un seul composant pour les deux liens** (`mode`, défaut `"entrer"`) : l'écran
 * d'activation se réutilise plutôt que de se refaire —
 * `GET /invitation` rend la même forme dans les deux cas (même table `invitations`,
 * `api/comptes.py`), et le formulaire de mot de passe est identique. Seuls changent le
 * texte d'accueil, le libellé du bouton et la route appelée à la soumission
 * (`api.entrer` / `api.reinitialiser`).
 *
 * `GET /invitation` dit si le jeton tient encore — inconnu, expiré ou déjà
 * consommé rendent la **même** réponse (404 `invitation_invalide`), et cet
 * écran ne cherche pas à deviner lequel : c'est voulu côté serveur
 * (`api/routes/sessions.py`, « on ne dit pas à un inconnu lequel des trois il a
 * rencontré »).
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import { jourEnLettres } from "../api/formats";

type Mode = "entrer" | "reinitialiser";

interface Props {
  jeton: string;
  /** La session vient de s'ouvrir : l'appelant décide de la suite. */
  surEntre: () => void;
  /** `"entrer"` (défaut) : activation d'une invitation. `"reinitialiser"` : nouveau mot de passe. */
  mode?: Mode;
}

type Etat =
  | { genre: "verification" }
  | { genre: "valable"; email: string; expireLe: string }
  | { genre: "refuse" };

export function Entrer({ jeton, surEntre, mode = "entrer" }: Props) {
  const [etat, setEtat] = useState<Etat>({ genre: "verification" });
  const [secret, setSecret] = useState("");
  const [visible, setVisible] = useState(false);
  const [panne, setPanne] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  useEffect(() => {
    let vivant = true;
    if (jeton.trim() === "") {
      // Aucun jeton dans le lien : inutile d'appeler l'API pour se le faire dire.
      setEtat({ genre: "refuse" });
      return;
    }
    api
      .invitation(jeton)
      .then((reponse) => {
        if (!vivant) return;
        setEtat({
          genre: "valable",
          email: reponse.donnees.email,
          expireLe: reponse.donnees.expire_le,
        });
      })
      .catch(() => {
        if (!vivant) return;
        setEtat({ genre: "refuse" });
      });
    return () => {
      vivant = false;
    };
  }, [jeton]);

  async function activer() {
    setPanne(null);
    setEnvoi(true);
    try {
      if (mode === "reinitialiser") await api.reinitialiser(jeton, secret);
      else await api.entrer(jeton, secret);
      surEntre();
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnvoi(false);
    }
  }

  if (etat.genre === "verification") {
    return (
      <section className="coquille">
        <div className="vide">
          {mode === "reinitialiser" ? "Vérification du lien…" : "Vérification de votre invitation…"}
        </div>
      </section>
    );
  }

  if (etat.genre === "refuse") {
    return (
      <section className="coquille">
        <div className="app-tete">
          <div>
            <span className="quand">où rouler</span>
            <h1>Ce lien n'est plus valable</h1>
          </div>
        </div>
        <div className="encart alerte">
          Ce lien {mode === "reinitialiser" ? "de réinitialisation" : "d'invitation"} n'est
          plus valable — inconnu, expiré ou déjà utilisé.
        </div>
        {/*
          Deux suites, et la première est de loin la plus frequente : un lien
          d'invitation ne vaut qu'une fois, donc celui qui reclique sur le sien
          est quelqu'un qui a **deja** un compte. Lui dire de redemander une
          invitation comme seule reponse serait la mauvaise.

          Proposer la connexion ne dit rien de l'etat du jeton : la meme page
          s'affiche pour un lien inconnu, expire ou consomme, et ce bouton y
          est toujours. Le silence du serveur reste entier.
        */}
        <p>
          <a className="bouton" href="/connexion">
            Se connecter
          </a>
        </p>
        <p className="mention">
          {mode === "reinitialiser"
            ? "Il faut un nouveau lien : demandez au mainteneur d'en émettre un."
            : "Si vous n'avez pas encore de compte, il faut une nouvelle invitation : le " +
              "mainteneur seul peut en émettre une."}
        </p>
      </section>
    );
  }

  return (
    <section className="coquille">
      <div className="app-tete">
        <div>
          <span className="quand">où rouler</span>
          <h1>{mode === "reinitialiser" ? "Nouveau mot de passe" : "Bienvenue"}</h1>
        </div>
      </div>
      <p className="mention">
        {mode === "reinitialiser" ? (
          <>
            Réinitialisation pour <b>{etat.email}</b>, lien valable jusqu'au{" "}
            {jourEnLettres(etat.expireLe.slice(0, 10))}. Choisissez un nouveau mot de passe.
          </>
        ) : (
          <>
            Invitation pour <b>{etat.email}</b>, valable jusqu'au{" "}
            {jourEnLettres(etat.expireLe.slice(0, 10))}. Choisissez un mot de passe pour ouvrir
            votre compte.
          </>
        )}
      </p>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      <div className="champ">
        <label htmlFor="entrer-secret">
          {mode === "reinitialiser" ? "Nouveau mot de passe" : "Mot de passe"}
        </label>
        <input
          className="saisie"
          id="entrer-secret"
          type={visible ? "text" : "password"}
          autoComplete="new-password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && secret.trim() !== "") activer();
          }}
        />
        <button type="button" className="lien" onClick={() => setVisible((v) => !v)}>
          {visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}
        </button>
        <div className="aide">
          Affiché en clair sur demande, comme la clé intervals.icu de l'assistant : masquer un
          mot de passe qu'on vient de saisir empêche de le relire avant de l'enregistrer.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        disabled={secret.trim() === "" || envoi}
        onClick={activer}
      >
        {mode === "reinitialiser"
          ? envoi
            ? "Enregistrement…"
            : "Enregistrer le nouveau mot de passe"
          : envoi
            ? "Ouverture…"
            : "Ouvrir mon compte"}
      </button>
    </section>
  );
}

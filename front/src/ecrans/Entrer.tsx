/** E6 · activation d'une invitation, atteint par `/entrer?jeton=…`.
 *
 * Le lien du mail d'invitation, et lui seul — jamais une navigation interne :
 * le front n'a pas de routeur, `App.tsx` lit `window.location.pathname` une
 * fois au démarrage et choisit cet écran plutôt que l'application (lot
 * L7.2-D). Le jeton est retiré de la barre d'adresse dès qu'il est lu
 * (`history.replaceState`, fait par l'appelant) : il n'a rien à faire dans
 * l'historique du navigateur ni dans un en-tête `Referer`.
 *
 * `GET /invitation` dit si le jeton tient encore — inconnu, expiré ou déjà
 * consommé rendent la **même** réponse (404 `invitation_invalide`), et cet
 * écran ne cherche pas à deviner lequel : c'est voulu côté serveur
 * (`api/routes.py`, « on ne dit pas à un inconnu lequel des trois il a
 * rencontré »).
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import { jourEnLettres } from "../api/formats";

interface Props {
  jeton: string;
  /** La session vient de s'ouvrir : l'appelant décide de la suite. */
  surEntre: () => void;
}

type Etat =
  | { genre: "verification" }
  | { genre: "valable"; email: string; expireLe: string }
  | { genre: "refuse" };

export function Entrer({ jeton, surEntre }: Props) {
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
      await api.entrer(jeton, secret);
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
        <div className="vide">Vérification de votre invitation…</div>
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
          Ce lien d'invitation n'est plus valable — inconnu, expiré ou déjà utilisé.
        </div>
        <p className="mention">
          La seule suite utile : redemander une invitation au mainteneur, lui seul peut en
          émettre une nouvelle.
        </p>
      </section>
    );
  }

  return (
    <section className="coquille">
      <div className="app-tete">
        <div>
          <span className="quand">où rouler</span>
          <h1>Bienvenue</h1>
        </div>
      </div>
      <p className="mention">
        Invitation pour <b>{etat.email}</b>, valable jusqu'au {jourEnLettres(etat.expireLe.slice(0, 10))}.
        Choisissez un mot de passe pour ouvrir votre compte.
      </p>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      <div className="champ">
        <label htmlFor="entrer-secret">Mot de passe</label>
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
          mot de passe qu'on vient de saisir empêche de le relire avant d'ouvrir le compte.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        disabled={secret.trim() === "" || envoi}
        onClick={activer}
      >
        {envoi ? "Ouverture…" : "Ouvrir mon compte"}
      </button>
    </section>
  );
}

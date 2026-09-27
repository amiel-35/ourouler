/** E5 · connexion — revenir sur un compte déjà actif, sans jeton.
 *
 * Deux usages du même écran : ouvert directement sur
 * `/connexion` (lu au démarrage, `App.tsx`), et affiché à la place de
 * l'application dès qu'une route de données répond 401 `session_absente` —
 * la session a expiré ou n'a jamais existé, et ce serveur ne peut montrer
 * les données de personne tant qu'il ne sait pas qui parle
 * (`docs/journal/ux/api_contrat.md`, « La session, et les deux produits »). Les deux
 * cas passent `surConnecte`, qui diffère selon d'où l'écran est montré : une
 * navigation complète depuis `/connexion`, une reprise en place depuis
 * l'application.
 *
 * **Pas d'inscription ici.** Il n'y a jamais de création de compte à la
 * demande (décision définitive) — un compte s'ouvre par invitation
 * (`/entrer`), jamais depuis cet écran. Pas de récupération de mot de passe
 * en libre-service non plus : un nouveau lien s'émet en ligne de commande
 * (`ourouler reinitialiser`).
 *
 * Le serveur rend le **même** refus pour une adresse inconnue et un mot de
 * passe faux (`identifiants_refuses`) : cet écran ne le décore pas, il
 * affiche le message tel quel.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";

interface Props {
  surConnecte: () => void;
}

export function Connexion({ surConnecte }: Props) {
  const [email, setEmail] = useState("");
  const [secret, setSecret] = useState("");
  const [visible, setVisible] = useState(false);
  const [panne, setPanne] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  const pret = email.trim() !== "" && secret.trim() !== "" && !envoi;

  async function connecter() {
    if (!pret) return;
    setPanne(null);
    setEnvoi(true);
    try {
      await api.connexion(email.trim(), secret);
      surConnecte();
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnvoi(false);
    }
  }

  return (
    <section className="coquille">
      <div className="app-tete">
        <div>
          <span className="quand">où rouler</span>
          <h1>Se connecter</h1>
        </div>
      </div>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      <div className="champ">
        <label htmlFor="connexion-email">Adresse</label>
        <input
          className="saisie"
          id="connexion-email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") connecter();
          }}
        />
      </div>
      <div className="champ">
        <label htmlFor="connexion-secret">Mot de passe</label>
        <input
          className="saisie"
          id="connexion-secret"
          type={visible ? "text" : "password"}
          autoComplete="current-password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") connecter();
          }}
        />
        <button type="button" className="lien" onClick={() => setVisible((v) => !v)}>
          {visible ? "Masquer le mot de passe" : "Afficher le mot de passe"}
        </button>
      </div>
      <button type="button" className="bouton" disabled={!pret} onClick={connecter}>
        {envoi ? "Connexion…" : "Se connecter"}
      </button>
      <p>
        <a className="lien" href="/demande-invitation">
          Pas encore de compte ? Demander une invitation
        </a>
      </p>
    </section>
  );
}

/** Le formulaire public « Demander une invitation », atteint par `/demande-invitation`.
 *
 * Sprint 12. Doctrine §10.2 (révisée le 26/09/2026) : ce formulaire ne crée jamais de
 * compte ni d'invitation — il dépose une demande, que le mainteneur accepte ou refuse
 * depuis l'administration. **Un seul message après envoi, toujours le même** : que
 * l'adresse existe déjà ou non, qu'elle soit retenue ensuite ou pas, l'écran ne dit
 * jamais rien d'autre que « si votre demande est retenue, vous recevrez un courriel » —
 * c'est le serveur qui rend une réponse identique dans tous les cas
 * (`api/routes/demandes.py`), et cet écran ne doit pas inventer de distinction que le
 * serveur refuse de faire.
 *
 * `piege` est un champ honeypot : un champ de saisie **hors du champ visuel** (pas
 * `display: none`, que certains lecteurs de robots ignorent déjà — décalé hors écran à
 * la place), qu'un humain ne remplit jamais et qu'un remplissage automatique remplit
 * souvent. Il porte `tabIndex={-1}` et `aria-hidden` pour rester invisible aussi à la
 * navigation au clavier et aux lecteurs d'écran.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";

type Etat = { genre: "saisie" } | { genre: "envoye" };

export function DemanderInvitation() {
  const [adresse, setAdresse] = useState("");
  const [message, setMessage] = useState("");
  const [piege, setPiege] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [panne, setPanne] = useState<string | null>(null);
  const [etat, setEtat] = useState<Etat>({ genre: "saisie" });

  const pret = adresse.trim() !== "" && !envoi;

  async function envoyer() {
    if (!pret) return;
    setPanne(null);
    setEnvoi(true);
    try {
      await api.demanderInvitation(adresse.trim(), message, piege);
      // Le serveur répond toujours pareil, réussite comprise : l'écran affiche donc
      // toujours ce même message, quelle que soit l'adresse saisie.
      setEtat({ genre: "envoye" });
    } catch (erreur) {
      // Une panne réseau ou de délai reste affichée (elle ne renseigne sur rien) ;
      // le serveur, lui, ne renvoie jamais d'échec propre à cette route.
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnvoi(false);
    }
  }

  if (etat.genre === "envoye") {
    return (
      <section className="coquille">
        <div className="app-tete">
          <div>
            <span className="quand">où rouler</span>
            <h1>Demande envoyée</h1>
          </div>
        </div>
        <p>Si votre demande est retenue, vous recevrez un courriel.</p>
        <p>
          <a className="bouton" href="/connexion">
            Retour à la connexion
          </a>
        </p>
      </section>
    );
  }

  return (
    <section className="coquille">
      <div className="app-tete">
        <div>
          <span className="quand">où rouler</span>
          <h1>Demander une invitation</h1>
        </div>
      </div>
      <p className="mention">
        où rouler fonctionne sur invitation. Laissez votre adresse et, si vous le
        voulez, un mot — le mainteneur vous répondra par courriel s'il retient votre
        demande.
      </p>
      {panne ? <div className="encart alerte">{panne}</div> : null}
      <div className="champ">
        <label htmlFor="demande-adresse">Adresse</label>
        <input
          className="saisie"
          id="demande-adresse"
          type="email"
          autoComplete="email"
          value={adresse}
          onChange={(e) => setAdresse(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") envoyer();
          }}
        />
      </div>
      <div className="champ">
        <label htmlFor="demande-message">Un mot (facultatif)</label>
        <input
          className="saisie"
          id="demande-message"
          type="text"
          maxLength={500}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") envoyer();
          }}
        />
      </div>
      {/* Honeypot : invisible pour un humain, laissé vide. Un remplissage
          automatique le remplit souvent — la demande n'est alors jamais
          enregistrée côté serveur, silencieusement. */}
      <div style={{ position: "absolute", left: "-9999px", top: "-9999px" }} aria-hidden="true">
        <label htmlFor="demande-site-web">Site web</label>
        <input
          id="demande-site-web"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={piege}
          onChange={(e) => setPiege(e.target.value)}
        />
      </div>
      <button type="button" className="bouton" disabled={!pret} onClick={envoyer}>
        {envoi ? "Envoi…" : "Envoyer la demande"}
      </button>
      <p>
        <a className="lien" href="/connexion">
          J'ai déjà un compte
        </a>
      </p>
    </section>
  );
}

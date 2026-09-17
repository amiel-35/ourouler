/** Choisir une adresse — **c'est le front qui tranche, jamais l'API**.
 *
 * `GET /geocodage` rend *tous* les candidats, notés, et ne choisit pas : « là
 * où la CLI choisit et le dit, l'API ne choisit pas et fait choisir » (F0.7).
 * Un géocodage qui se trompe de commune est indétectable dans un champ
 * texte ; une liste où l'on désigne le bon rend l'erreur visible.
 *
 * Zéro candidat **n'est pas une panne** : les services ont répondu. L'API
 * joint alors une phrase dans `avertissements`, et c'est elle qu'on affiche —
 * un écran d'échec a besoin d'une phrase, pas d'une liste vide.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Candidat } from "../api/types";
import { nombre } from "../api/formats";

interface Props {
  valeurActuelle?: string;
  surChoix: (candidat: Candidat) => void;
}

export function ChoixAdresse({ valeurActuelle, surChoix }: Props) {
  const [adresse, setAdresse] = useState("");
  const [candidats, setCandidats] = useState<Candidat[] | null>(null);
  const [phrase, setPhrase] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  async function chercher() {
    if (adresse.trim() === "") return;
    setEnCours(true);
    setPhrase(null);
    try {
      const reponse = await api.geocodage(adresse);
      setCandidats(reponse.donnees.candidats);
      if (reponse.donnees.candidats.length === 0) {
        // `avertissements` porte maintenant `{code, message}` (B3) : seule la
        // lecture change ici, l'écran est le même.
        setPhrase(reponse.avertissements[0]?.message ?? "Aucune adresse trouvée.");
      }
    } catch (erreur) {
      setCandidats(null);
      setPhrase(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  return (
    <div className="champ">
      <label htmlFor="adresse">Adresse de départ</label>
      <input
        className="saisie"
        id="adresse"
        value={adresse}
        placeholder={valeurActuelle ?? "numéro, rue, commune"}
        onChange={(e) => setAdresse(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") chercher();
        }}
      />
      <div className="aide">
        Vous pourrez partir d'ailleurs à chaque sortie. Celle-ci n'est que le défaut.
      </div>
      <button type="button" className="bouton second" onClick={chercher} disabled={enCours}>
        {enCours ? "Recherche…" : "Chercher"}
      </button>
      {phrase ? <p className="mention">{phrase}</p> : null}
      {candidats && candidats.length > 0 ? (
        <ul className="liste-candidats">
          {candidats.map((candidat) => (
            <li key={`${candidat.latitude},${candidat.longitude}`}>
              <button type="button" onClick={() => surChoix(candidat)}>
                {candidat.label}
                <span className="mention">
                  {" "}
                  · {candidat.source} · confiance {nombre(candidat.score * 100)} / 100
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

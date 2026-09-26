/** Séparé d'`App.tsx` — les deux
 * écrans qui priment sur tout le reste au démarrage : la session perdue, et
 * l'échec d'une des trois ressources de démarrage (système, profil, zones).
 */

import { sessionRouverte } from "../api/client";
import type { Ressource } from "../etat/ressource";
import { Echec } from "../composants/Echec";
import { Connexion } from "../ecrans/Connexion";

export function EcranAmorcage(props: {
  sessionPerdue: boolean;
  setSessionPerdue: (perdue: boolean) => void;
  systeme: Ressource<unknown>;
  profil: Ressource<unknown>;
  zones: Ressource<unknown>;
  semaine: Ressource<unknown>;
  seanceDuJour: Ressource<unknown>;
}): JSX.Element | null {
  const { sessionPerdue, setSessionPerdue, systeme, profil, zones, semaine, seanceDuJour } = props;

  // **Avant même `zones.erreur`** : une session perdue amène
  // l'écran de connexion, pas un écran d'échec. `surConnecte` ne perd rien
  // de ce que le cycliste faisait — `onglet`, `vue`, `demande` restent tels
  // quels, seules les ressources qui ont échoué sont relues.
  if (sessionPerdue) {
    return (
      <div className="coquille">
        <Connexion
          surConnecte={() => {
            // **Avant de recharger.** Une requête partie sous l'ancienne
            // session peut encore revenir avec son 401 ; sans ce repère, elle
            // rouvrirait cet écran alors qu'on vient d'en sortir.
            sessionRouverte();
            setSessionPerdue(false);
            systeme.recharger();
            profil.recharger();
            zones.recharger();
            semaine.recharger();
            seanceDuJour.recharger();
          }}
        />
      </div>
    );
  }

  // **`zones.erreur` compte comme les deux autres.** L'affichage est interdit
  // tant que `zonesCourantes` est `null` : sans ce test, une panne de
  // `/profil/zones` laisserait « Connexion au serveur… » pour toujours — sans
  // code, sans bouton, sans barre d'onglets. C'est exactement l'écran muet que
  // la section « Quand ça casse » des maquettes interdit, et le seul geste
  // possible serait le rechargement, que l'écran d'attente déconseille.
  if (systeme.erreur || profil.erreur || zones.erreur) {
    return (
      <div className="coquille">
        <Echec
          erreur={(systeme.erreur ?? profil.erreur ?? zones.erreur)!}
          contexte="Démarrage"
          reessayer={() => {
            systeme.recharger();
            profil.recharger();
            zones.recharger();
          }}
        />
      </div>
    );
  }

  return null;
}

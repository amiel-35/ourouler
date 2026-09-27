/** Séparé d'`App.tsx` — l'historique du navigateur.
 *
 * Décision du mainteneur du 27/09/2026
 * (`docs/backlog/2026-09-27-bug-retour-navigateur-quitte-l-appli.md`) :
 * l'onglet est dans l'adresse (`/?onglet=...`), les résultats (propositions,
 * détail, boucles) sont des étapes d'historique sans adresse propre. Ce
 * fichier porte les deux effets qui font vivre cette règle — normaliser
 * l'adresse au démarrage, redessiner sur `popstate` — et le seul geste qui
 * change d'onglet, pour qu'`App.tsx` et `Contenu.tsx` ne réinventent pas
 * chacun leur propre variante.
 */

import { useEffect } from "react";
import {
  changerOnglet,
  ongletDepuisUrl,
  remplacerVersOnglet,
  type EtatHistorique,
  type Onglet,
  type Vue,
} from "./navigation";

export function useNavigationHistorique(
  onglet: Onglet,
  setOnglet: (onglet: Onglet) => void,
  setVue: (vue: Vue) => void,
): (cible: Onglet) => void {
  // Au démarrage, un `replaceState` (pas de `pushState` : rien de nouveau à
  // empiler) pose la même forme d'état que celle que `changerOnglet` et
  // `pousserVue` poseront ensuite — sans lui, la toute première entrée
  // n'aurait pas d'`history.state`, et un retour jusqu'à elle retomberait
  // dans la branche « état absent » plutôt que de retrouver l'onglet.
  useEffect(() => {
    remplacerVersOnglet(onglet);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Retour et avance du navigateur : redessine l'onglet et la vue portés
  // par l'entrée d'historique, sans rien recalculer — les résultats d'une
  // recherche restent en mémoire (`Resultat`, `etat/memoire.ts`), `popstate`
  // ne fait que les rafficher.
  useEffect(() => {
    function surPopstate(evenement: PopStateEvent) {
      const etat = evenement.state as EtatHistorique | null;
      if (etat) {
        setOnglet(etat.onglet);
        setVue(etat.vue);
      } else {
        // Une entrée sans état : avant que cette appli n'en pose un, ou
        // au-delà de ce qu'elle connaît. Retombe sur l'onglet lu dans
        // l'adresse plutôt que d'échouer — la règle qui empêche qu'un
        // retour depuis l'appli produise une erreur de l'appli.
        setOnglet(ongletDepuisUrl());
        setVue({ genre: "onglet" });
      }
    }
    window.addEventListener("popstate", surPopstate);
    return () => window.removeEventListener("popstate", surPopstate);
  }, [setOnglet, setVue]);

  // Le seul geste qui change d'onglet, où qu'il parte dans l'application.
  return (cible: Onglet) => changerOnglet(onglet, cible, setOnglet, setVue);
}

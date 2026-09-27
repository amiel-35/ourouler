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
import type { ErreurApi } from "../api/client";
import {
  changerOnglet,
  estOnglet,
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
  /** Un calcul en vol (`enCalcul !== null` côté `useRecherche`) : l'écran
   * d'attente ne dépend ni de l'onglet ni de la vue, et laisser `popstate`
   * les changer pendant que la requête tient romprait l'accord entre
   * l'adresse et l'état une fois le calcul fini — `chercher` pousse ou
   * remplace déjà sa propre entrée à ce moment-là. */
  enCalcul: boolean,
  /** Referme l'écran d'échec de calcul sur un retour/avance navigateur,
   * pour qu'il redessine l'écran de l'entrée visée plutôt que de rester
   * affiché malgré une adresse qui a changé sous lui. */
  setErreurCalcul: (erreur: ErreurApi | null) => void,
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
      // Ignoré tant qu'un calcul tient — voir la note sur `enCalcul`
      // ci-dessus : rien à redessiner, la requête décidera elle-même de la
      // suite en aboutissant ou en échouant.
      if (enCalcul) return;
      // Un retour ou une avance referme l'écran d'échec de calcul, qu'il
      // soit affiché ou non (`setErreurCalcul(null)` sur `null` est sans
      // effet) : l'entrée visée redessine son propre écran, jamais celui
      // d'une panne qui ne la concerne plus.
      setErreurCalcul(null);
      const etat = evenement.state as Partial<EtatHistorique> | null;
      // `etat.onglet` peut être n'importe quoi : une entrée posée par une
      // version antérieure, ou tout ce qu'un autre script aurait poussé.
      // `setOnglet` ne reçoit jamais rien d'autre qu'un des quatre onglets
      // connus.
      if (etat && estOnglet(etat.onglet)) {
        setOnglet(etat.onglet);
        setVue(etat.vue ?? { genre: "onglet" });
      } else {
        // Une entrée sans état exploitable : avant que cette appli n'en
        // pose un, au-delà de ce qu'elle connaît, ou étrangère. Retombe
        // sur l'onglet lu dans l'adresse plutôt que d'échouer — la règle
        // qui empêche qu'un retour depuis l'appli produise une erreur de
        // l'appli.
        setOnglet(ongletDepuisUrl());
        setVue({ genre: "onglet" });
      }
    }
    window.addEventListener("popstate", surPopstate);
    return () => window.removeEventListener("popstate", surPopstate);
  }, [setOnglet, setVue, enCalcul, setErreurCalcul]);

  // Le seul geste qui change d'onglet, où qu'il parte dans l'application.
  return (cible: Onglet) => changerOnglet(onglet, cible, setOnglet, setVue);
}

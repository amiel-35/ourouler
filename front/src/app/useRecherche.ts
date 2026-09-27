/** Séparé d'`App.tsx` — l'état et
 * la fonction d'une recherche de parcours (séance du jour ou boucle Z2),
 * calculée en semi-synchrone contre le budget annoncé par `/systeme/budgets`.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Budget, Zones } from "../api/types";
import { retenirSortie, sortieRetenue, type SortieMemorisee } from "../etat/memoire";
import { demandeInitiale, heureDepartResolue, type Demande } from "../ecrans/Demander";
import {
  entrerDansResultats,
  fichierPourLaRecherche,
  type Onglet,
  type Resultat,
  type SeanceDeposee,
  type Vue,
} from "./navigation";

export interface Recherche {
  demande: Demande;
  setDemande: (demande: Demande) => void;
  resultat: Resultat | null;
  setResultat: (resultat: Resultat | null) => void;
  enCalcul: Budget | null;
  erreurCalcul: ErreurApi | null;
  setErreurCalcul: (erreur: ErreurApi | null) => void;
  memoire: SortieMemorisee | null;
  setMemoire: (memoire: SortieMemorisee | null) => void;
  joursMemorises: string[];
  setJoursMemorises: (maj: string[] | ((connus: string[]) => string[])) => void;
  chercher: (surcharge?: Partial<Demande>) => Promise<void>;
}

export function useRecherche(params: {
  jour: string;
  /** L'onglet actif au moment de l'appel — porté par l'entrée d'historique
   * poussée quand la recherche aboutit (`entrerDansResultats`), pour qu'un
   * retour navigateur retrouve le formulaire d'où elle est partie. */
  onglet: Onglet;
  /** La vue affichée au moment de l'appel — dit si on entre dans les
   * résultats pour la première fois (on pousse) ou si on y est déjà
   * (« Chercher plus loin » depuis les propositions : on remplace, voir
   * `entrerDansResultats`). */
  vue: Vue;
  fichierSeance: SeanceDeposee | null;
  zonesCourantes: Zones | null;
  budgetDe: (operation: string) => Budget | null;
  setVue: (vue: Vue) => void;
}): Recherche {
  const { jour, onglet, vue, fichierSeance, zonesCourantes, budgetDe, setVue } = params;

  const [demande, setDemande] = useState<Demande>(demandeInitiale);
  const [resultat, setResultat] = useState<Resultat | null>(null);
  const [enCalcul, setEnCalcul] = useState<Budget | null>(null);
  const [erreurCalcul, setErreurCalcul] = useState<ErreurApi | null>(null);
  const [memoire, setMemoire] = useState<SortieMemorisee | null>(() => sortieRetenue(jour));
  /**
   * Les jours pour lesquels ce navigateur a déjà un parcours.
   *
   * `etat/memoire` range chaque sortie sous sa propre clé. Ne retenir que
   * celle du jour ferait que générer le parcours de demain depuis « Ma
   * semaine » ne laisserait aucune trace : le bouton resterait « Générer le
   * parcours », et le calcul — trois à sept secondes contre BRouter et
   * Open-Meteo — serait à refaire.
   */
  const [joursMemorises, setJoursMemorises] = useState<string[]>([]);

  async function chercher(surcharge?: Partial<Demande>) {
    const finale = { ...demande, ...surcharge };
    setDemande(finale);
    setErreurCalcul(null);
    const operation = finale.mode === "seance" ? "sortie" : "boucle";
    setEnCalcul(budgetDe(operation) ?? null);
    // Résolue ici, à l'instant du calcul — pas au moment où le champ a été
    // affiché : un écran resté ouvert depuis 9 h et relancé à 14 h 37
    // cherche à 14:45, pas à l'heure calculée à l'ouverture.
    const heureDepart = heureDepartResolue(finale);
    try {
      if (finale.mode === "seance") {
        // **Un seul des deux champs part** (décision Q44) : l'API refuse `direction`
        // et un `vent` contraignant envoyés ensemble. `modeDirection` est la
        // seule source de vérité ici — jamais les deux champs à la fois,
        // quoi que porte encore `demande.direction`/`demande.vent` d'un
        // mode qu'on a quitté.
        const orientation: { direction?: string; vent?: string } =
          finale.modeDirection === "direction"
            ? { direction: finale.direction, vent: "peu-importe" }
            : finale.modeDirection === "vent"
              ? { vent: finale.vent }
              : { vent: "peu-importe" };
        const reponse = await api.sortie({
          jour: finale.jour,
          heure_depart: `${finale.jour}T${heureDepart}`,
          candidates: finale.candidates,
          ...orientation,
          depart: finale.depart ?? undefined,
          // **Le jour doit correspondre** — voir `fichierPourLaRecherche`.
          fichier_seance: fichierPourLaRecherche(fichierSeance, finale.jour),
        });
        // La séance placée porte les emplacements, pas les étapes : celles-ci
        // viennent de la route des séances, ou du dépôt de fichier.
        let seance = null;
        try {
          seance = (await api.seance(finale.jour)).donnees;
        } catch {
          seance = null;
        }
        setResultat({ sortie: reponse, boucle: null, seance, jour: finale.jour });
        // Retenu pour **son** jour, quel qu'il soit.
        const memorisee = retenirSortie(finale.jour, reponse);
        if (finale.jour === jour) setMemoire(memorisee);
        setJoursMemorises((connus) =>
          connus.includes(finale.jour) ? connus : [...connus, finale.jour],
        );
        // Une recherche qui aboutit entre dans les résultats — une entrée
        // d'historique de plus la première fois, la même remplacée si on y
        // est déjà (« Chercher plus loin ») : un retour navigateur retrouve
        // le formulaire tel qu'il était, sans recalcul, en un seul pas.
        entrerDansResultats(onglet, vue, { genre: "propositions" });
        setVue({ genre: "propositions" });
      } else {
        // `boucle` balaie tout l'horizon sans direction, comme `sortie`
        // — même règle que la branche `seance` ci-dessus, `modeDirection` est
        // la seule source de vérité. `/boucles` n'a pas de champ `vent` : le
        // mode « vent » retombe déjà sur « peu importe » en Z2 (voir l'effet dans `Demander.tsx`), donc seul
        // « direction » envoie un azimut ici.
        const reponse = await api.boucle({
          distance_km: Math.max(
            1,
            ((zonesCourantes?.valeurs_liees?.moyenne_compteur_kmh ?? 0) * finale.duree_min) / 60,
          ),
          direction: finale.modeDirection === "direction" ? finale.direction : undefined,
          heure_depart: `${finale.jour}T${heureDepart}`,
          candidates: finale.candidates,
          depart: finale.depart ?? undefined,
        });
        setResultat({ sortie: null, boucle: reponse, seance: null, jour: finale.jour });
        entrerDansResultats(onglet, vue, { genre: "boucles" });
        setVue({ genre: "boucles" });
      }
    } catch (cause) {
      setErreurCalcul(
        cause instanceof ErreurApi
          ? cause
          : new ErreurApi(
              { code: "erreur_interne", message: String(cause), service: null, details: {} },
              0,
            ),
      );
    } finally {
      setEnCalcul(null);
    }
  }

  return {
    demande,
    setDemande,
    resultat,
    setResultat,
    enCalcul,
    erreurCalcul,
    setErreurCalcul,
    memoire,
    setMemoire,
    joursMemorises,
    setJoursMemorises,
    chercher,
  };
}

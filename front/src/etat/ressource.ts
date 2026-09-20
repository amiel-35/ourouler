/** Charger une ressource de l'API, et savoir dans quel état on est.
 *
 * Trois états, jamais deux : on charge, on a, ou ça a cassé. Le troisième
 * porte une `ErreurApi` avec son code — c'est lui qui choisit l'écran
 * d'échec, et c'est pour ça qu'il ne se réduit pas à `null`.
 */

import { useCallback, useEffect, useState } from "react";
import { ErreurApi } from "../api/client";

export interface Ressource<T> {
  valeur: T | null;
  erreur: ErreurApi | null;
  chargement: boolean;
  recharger: () => void;
}

export function useRessource<T>(charger: () => Promise<T>, dependances: unknown[]): Ressource<T> {
  const [valeur, setValeur] = useState<T | null>(null);
  const [erreur, setErreur] = useState<ErreurApi | null>(null);
  const [chargement, setChargement] = useState(true);
  const [essai, setEssai] = useState(0);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const memorise = useCallback(charger, dependances);

  useEffect(() => {
    let vivant = true;
    setChargement(true);
    memorise()
      .then((resultat) => {
        if (!vivant) return;
        setValeur(resultat);
        setErreur(null);
      })
      .catch((cause) => {
        if (!vivant) return;
        setValeur(null);
        setErreur(
          cause instanceof ErreurApi
            ? cause
            : new ErreurApi(
                { code: "erreur_interne", message: String(cause), service: null, details: {} },
                0,
              ),
        );
      })
      .finally(() => {
        if (vivant) setChargement(false);
      });
    return () => {
      vivant = false;
    };
  }, [memorise, essai]);

  return {
    valeur,
    erreur,
    chargement,
    recharger: () => {
      // La panne précédente ne doit pas rester affichée pendant qu'une
      // nouvelle tentative est en vol — sinon un écran de connexion réussi
      // rouvre, une fraction de seconde, l'écran d'échec qu'il vient de
      // fermer (lot L7.2-D : c'est exactement ce que fait `recharger` après
      // une reconnexion, dans `App.tsx`).
      setErreur(null);
      setEssai((n) => n + 1);
    },
  };
}

/** La date d'aujourd'hui en AAAA-MM-JJ, dans le fuseau du navigateur. */
export function aujourdhui(): string {
  const maintenant = new Date();
  const decalage = maintenant.getTimezoneOffset() * 60_000;
  return new Date(maintenant.getTime() - decalage).toISOString().slice(0, 10);
}

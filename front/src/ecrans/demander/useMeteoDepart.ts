/** Le vent au départ et la météo des huit directions, rechargés quand le
 * jour ou l'heure de départ changent. */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../../api/client";
import type { Enveloppe, Meteo, VentDepart } from "../../api/types";

export function useMeteoDepart(jour: string, heure_depart: string) {
  // D'où vient le vent au départ — chargé pendant que le cycliste
  // choisit, affiché dans les deux modes, jamais recalculé ici.
  const [vent, setVent] = useState<Enveloppe<VentDepart> | null>(null);
  const [erreurVent, setErreurVent] = useState<string | null>(null);
  // La rose des huit directions (pluie cumulée, vent, désaccord entre
  // modèles) : remplace « Là où il fait sec », qui ne faisait qu'un seul de
  // ces trois appels à `/meteo` pour ne montrer que le nom d'une direction.
  const [meteo, setMeteo] = useState<Enveloppe<Meteo> | null>(null);
  const [erreurMeteo, setErreurMeteo] = useState<string | null>(null);
  const departIso = `${jour}T${heure_depart}:00`;

  // Rechargé quand le jour ou l'heure de départ changent — c'est ce qui
  // décide de l'azimut, pas le mode ni le reste de la demande.
  useEffect(() => {
    let annule = false;
    setVent(null);
    setErreurVent(null);
    api
      .ventDepart({ jour: jour, heure_depart: `${jour}T${heure_depart}:00` })
      .then((reponse) => {
        if (!annule) setVent(reponse);
      })
      .catch((erreur) => {
        if (!annule) setErreurVent(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      });
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jour, heure_depart]);

  // La rose : même déclenchement que le vent au départ ci-dessus (jour et
  // heure de départ décident de la fenêtre interrogée), chargée qu'on soit
  // ou non sur « Ma direction » — pour qu'elle soit déjà prête au premier
  // clic sur ce mode, sans reflash.
  useEffect(() => {
    let annule = false;
    setMeteo(null);
    setErreurMeteo(null);
    api
      .meteo({ heure_depart: departIso })
      .then((reponse) => {
        if (!annule) setMeteo(reponse);
      })
      .catch((erreur) => {
        if (!annule) setErreurMeteo(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      });
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jour, heure_depart]);

  return { vent, erreurVent, meteo, erreurMeteo };
}

/** Séparé d'`App.tsx` — l'écran
 * d'échec d'un calcul de parcours (« aucune boucle », et le reste), avec ses
 * leviers de repli. */

import type { ErreurApi } from "../api/client";
import { derniereLectureSeances } from "../etat/memoire";
import { Echec, type Repli } from "../composants/Echec";
import type { Demande } from "../ecrans/Demander";
import { BarreOnglets } from "./BarreOnglets";
import type { Onglet } from "./navigation";

export interface EchecCalculProps {
  erreur: ErreurApi;
  demande: Demande;
  onglet: Onglet;
  chercher: (surcharge?: Partial<Demande>) => void | Promise<void>;
  fermerErreur: () => void;
  allerVersDemander: () => void;
  allerVersDepot: () => void;
  changerOnglet: (cle: Onglet) => void;
}

export function EchecCalcul({
  erreur,
  demande,
  onglet,
  chercher,
  fermerErreur,
  allerVersDemander,
  allerVersDepot,
  changerOnglet,
}: EchecCalculProps) {
  const replis: Repli[] = [];
  if (erreur.code === "aucune_boucle") {
    if (demande.mode === "z2") {
      replis.push({
        titre: "Élargir la durée",
        detail: `${Math.round(demande.duree_min * 0.9)} à ${Math.round(
          demande.duree_min * 1.1,
        )} minutes`,
        action: () => chercher({ duree_min: Math.round(demande.duree_min * 1.1) }),
      });
    }
    if (demande.modeDirection === "vent" && demande.vent !== "peu-importe") {
      replis.push({
        titre: "Laisser le vent libre",
        detail: "« Peu importe » au lieu d'imposer une orientation",
        action: () => chercher({ vent: "peu-importe", modeDirection: "peu-importe" }),
      });
    }
    replis.push({
      titre: "Chercher plus loin",
      detail: `${demande.candidates} candidates aujourd'hui, 8 au prochain essai`,
      action: () => chercher({ candidates: 8 }),
    });
  }
  return (
    <div className="coquille">
      <Echec
        erreur={erreur}
        contexte={`${demande.jour} · départ ${demande.heure_depart}`}
        replis={replis}
        dernierSucces={derniereLectureSeances()}
        reessayer={() => chercher()}
        secours={
          <div className="boutons">
            <button type="button" className="bouton second" onClick={allerVersDemander}>
              Modifier la demande
            </button>
            <button type="button" className="bouton second" onClick={allerVersDepot}>
              Déposer une séance
            </button>
          </div>
        }
      />
      <BarreOnglets
        onglet={onglet}
        surOnglet={(cle) => {
          fermerErreur();
          changerOnglet(cle);
        }}
      />
    </div>
  );
}

/** Lot 14 : extrait d'`App.tsx` sans changement de comportement — la barre
 * des quatre onglets. */

import { IconeAujourdhui, IconeDemander, IconeReglages, IconeSemaine } from "../composants/Pictogrammes";
import { ONGLETS, type Onglet } from "./navigation";

const PICTOGRAMMES: Record<Onglet, (props: { className?: string }) => JSX.Element> = {
  aujourdhui: IconeAujourdhui,
  semaine: IconeSemaine,
  demander: IconeDemander,
  reglages: IconeReglages,
};

export function BarreOnglets({
  onglet,
  surOnglet,
}: {
  onglet: Onglet;
  surOnglet: (cle: Onglet) => void;
}) {
  return (
    <nav className="onglets" aria-label="Navigation principale">
      {ONGLETS.map((entree) => {
        const Pictogramme = PICTOGRAMMES[entree.cle];
        return (
          <button
            type="button"
            key={entree.cle}
            aria-current={onglet === entree.cle ? "page" : undefined}
            onClick={() => surOnglet(entree.cle)}
          >
            <Pictogramme className="onglet-icone" />
            <span className="onglet-libelle">{entree.nom}</span>
          </button>
        );
      })}
    </nav>
  );
}

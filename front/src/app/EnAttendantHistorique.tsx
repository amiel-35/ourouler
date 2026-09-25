/** Lot 14 : extrait d'`App.tsx` sans changement de comportement — le bloc
 * « en attendant » d'un échec de lecture (séance du jour ou semaine), qui
 * était dupliqué à l'identique dans les deux branches. */

export function EnAttendantHistorique({
  surDemander,
  surDeposer,
}: {
  surDemander: () => void;
  surDeposer: () => void;
}) {
  return (
    <div className="bloc doux">
      <div className="bloc-tete">
        <h2>En attendant</h2>
      </div>
      <p className="mention">
        Vous pouvez demander un parcours à la main, déposer un fichier de séance, déposer vos
        sorties passées — c'est l'autre source d'historique, sans Intervals — ou analyser un
        parcours que vous avez déjà (l'imposé d'un brevet, la boucle du club).
        Tout le reste fonctionne.
      </p>
      <div className="boutons" style={{ marginTop: 11 }}>
        <button type="button" className="bouton second" onClick={surDemander}>
          Demander
        </button>
        <button type="button" className="bouton second" onClick={surDeposer}>
          Déposer
        </button>
      </div>
    </div>
  );
}

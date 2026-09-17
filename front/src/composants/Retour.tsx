/** La sortie d'un écran de profondeur — **en haut, et nommée**.
 *
 * Le retour existait déjà sur chacun de ces écrans, mais tout en bas : sur le
 * détail d'une proposition il venait après la carte, le profil d'altitude,
 * les étapes de la séance, les bandeaux et le bouton d'envoi au compteur. Le
 * mainteneur ne l'a jamais vu et a conclu qu'il n'y en avait pas — ce qui,
 * sur un téléphone, revient au même.
 *
 * **Pas de routeur, et c'est délibéré.** Le produit a huit écrans et
 * `App.tsx` les enchaîne déjà par une petite machine à états (`vue` +
 * `onglet`) dont chaque transition de retour est écrite noir sur blanc.
 * Ajouter une bibliothèque de routage pour afficher un lien plus haut aurait
 * été une dépendance et un changement d'architecture pour un défaut de mise
 * en page. Il ne manquait rien à la navigation : il manquait de la voir.
 *
 * **Le libellé dit la destination, pas « Retour ».** Revenir aux parcours du
 * samedi 19 n'est pas revenir à « Ma semaine », et un écran qui ne dit pas
 * d'où l'on vient laisse le lecteur sans repère de profondeur — la barre
 * d'onglets, elle, continue de surligner la même destination qu'on soit à la
 * surface ou deux niveaux plus bas. Chaque écran fabrique donc sa phrase à
 * partir de ce qu'il affiche déjà.
 */

interface Props {
  /** Où l'on revient, en toutes lettres. Jamais « Retour » tout seul. */
  vers: string;
  surRetour: () => void;
}

export function RetourEnTete({ vers, surRetour }: Props) {
  return (
    <button type="button" className="retour" onClick={surRetour}>
      <span aria-hidden="true">←</span> {vers}
    </button>
  );
}

/** Les quatre pictogrammes de la barre d'onglets.
 *
 * Dessinés à la main, aucune bibliothèque d'icônes, aucun paquet npm. Le style reprend une tradition suisse antérieure à
 * ce produit : celle d'Otl Aicher et des pictogrammes ISO (signalétique des
 * jeux Olympiques de Munich 1972, panneaux normalisés) — géométrique, un seul
 * poids de trait, aucun détail, lisible à 16 px. Ils portent `currentColor`
 * et rien d'autre : ni couleur, ni fond, ni ombre — c'est l'encre du bouton
 * qui les colore, au repos comme à l'état actif (règle 1 de la direction
 * visuelle, appliquée jusqu'à l'icône).
 *
 * Cohérence avec le reste du système : **aucun arrondi**. Les angles sont
 * droits (`stroke-linecap="square"`, `stroke-linejoin="miter"`), comme
 * `--rayon: 0` partout ailleurs — un cercle reste un cercle (le soleil, le
 * centre de la rose des vents), ce n'est pas un coin arrondi.
 *
 * Le texte reste à côté de chaque pictogramme dans `App.tsx` : un
 * pictogramme seul est une devinette, jamais l'unique porteur du sens
 * (contrainte d'accessibilité du lot). `aria-hidden` : le nom accessible du
 * bouton reste porté par le texte.
 */

interface Props {
  className?: string;
}

const SOCLE = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "square" as const,
  strokeLinejoin: "miter" as const,
  "aria-hidden": true,
};

/** Aujourd'hui — un soleil : cercle et quatre rayons, rien de plus. */
export function IconeAujourdhui({ className }: Props) {
  return (
    <svg {...SOCLE} className={className}>
      <circle cx="12" cy="12" r="4.5" />
      <line x1="12" y1="1.5" x2="12" y2="4.5" />
      <line x1="12" y1="19.5" x2="12" y2="22.5" />
      <line x1="1.5" y1="12" x2="4.5" y2="12" />
      <line x1="19.5" y1="12" x2="22.5" y2="12" />
      <line x1="4.6" y1="4.6" x2="6.7" y2="6.7" />
      <line x1="17.3" y1="17.3" x2="19.4" y2="19.4" />
      <line x1="19.4" y1="4.6" x2="17.3" y2="6.7" />
      <line x1="6.7" y1="17.3" x2="4.6" y2="19.4" />
    </svg>
  );
}

/** Ma semaine — un calendrier : corps, bandeau d'en-tête, trois colonnes de jour. */
export function IconeSemaine({ className }: Props) {
  return (
    <svg {...SOCLE} className={className}>
      <rect x="3" y="5" width="18" height="16" />
      <line x1="3" y1="10" x2="21" y2="10" />
      <line x1="7.5" y1="2" x2="7.5" y2="5" />
      <line x1="16.5" y1="2" x2="16.5" y2="5" />
      <line x1="9" y1="14" x2="9" y2="17.5" />
      <line x1="12" y1="14" x2="12" y2="17.5" />
      <line x1="15" y1="14" x2="15" y2="17.5" />
    </svg>
  );
}

/** Demander — une rose des vents : le cercle et l'aiguille du produit
 * (« au nord, au sud, à l'est »), pas un point d'interrogation générique. */
export function IconeDemander({ className }: Props) {
  return (
    <svg {...SOCLE} className={className}>
      <circle cx="12" cy="12" r="9" />
      <polygon points="12,4.5 14.3,12 12,10.4 9.7,12" fill="currentColor" stroke="none" />
      <polygon points="12,19.5 14.3,12 12,13.6 9.7,12" fill="none" />
    </svg>
  );
}

/** Réglages — trois curseurs : plus lisible à 16 px qu'un engrenage, qui perd
 * ses dents à cette taille et se lit comme un cercle plein. */
export function IconeReglages({ className }: Props) {
  return (
    <svg {...SOCLE} className={className}>
      <line x1="3" y1="6" x2="21" y2="6" />
      <circle cx="15" cy="6" r="2.3" fill="currentColor" stroke="none" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <circle cx="9" cy="12" r="2.3" fill="currentColor" stroke="none" />
      <line x1="3" y1="18" x2="21" y2="18" />
      <circle cx="17" cy="18" r="2.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

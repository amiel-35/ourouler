/** Le profil d'altitude, en paires `[distance_m, altitude_m]` (lot F0.1).
 *
 * Un SVG et rien d'autre : le tracé se lit d'un coup d'œil, et les deux
 * chiffres qui l'encadrent — le point le plus bas et le plus haut — viennent
 * des données, jamais d'une échelle arrondie « pour faire joli ».
 */

import { nombre } from "../api/formats";

interface Props {
  profil: [number, number][];
  /** Les blocs, en mètres parcourus, pour les teinter sous la courbe. */
  blocs?: { debut_m: number; fin_m: number; couleur: string }[];
}

const LARGEUR = 320;
const HAUTEUR = 74;

export function ProfilAltitude({ profil, blocs = [] }: Props) {
  if (profil.length < 2) return null;
  const distances = profil.map(([d]) => d);
  const altitudes = profil.map(([, a]) => a);
  const distanceMax = Math.max(...distances);
  const bas = Math.min(...altitudes);
  const haut = Math.max(...altitudes);
  const amplitude = haut - bas || 1;

  const x = (metres: number) => (metres / (distanceMax || 1)) * LARGEUR;
  const y = (altitude: number) => HAUTEUR - 12 - ((altitude - bas) / amplitude) * (HAUTEUR - 20);

  const ligne = profil.map(([d, a]) => `${x(d).toFixed(1)},${y(a).toFixed(1)}`).join(" ");
  const aire = `0,${HAUTEUR} ${ligne} ${LARGEUR},${HAUTEUR}`;

  return (
    <svg
      className="profil-alt"
      viewBox={`0 0 ${LARGEUR} ${HAUTEUR}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`Profil du parcours, de ${nombre(bas, 0)} à ${nombre(haut, 0)} mètres d'altitude`}
    >
      {/* L'aire et la ligne du profil ne sont ni une mesure météo, ni une
          décision, ni l'effort d'une étape : elles ne rentrent dans aucune
          des familles colorées du système (règle 1 — « si c'est coloré,
          c'est une mesure »), donc elles restent en encre, comme le reste
          de la structure. Les rectangles de `blocs`, eux, portent la teinte
          d'effort de leur étape (`couleur`, fournie par l'écran) : c'est
          une vraie mesure. */}
      <polygon points={aire} fill="var(--trait)" />
      {blocs.map((bloc) => (
        <rect
          key={`${bloc.debut_m}-${bloc.fin_m}`}
          x={x(bloc.debut_m)}
          y={0}
          width={Math.max(x(bloc.fin_m) - x(bloc.debut_m), 1)}
          height={HAUTEUR}
          fill={bloc.couleur}
          opacity="0.18"
        />
      ))}
      <polyline points={ligne} fill="none" stroke="var(--texte)" strokeWidth="1.5" />
      <text x="2" y={HAUTEUR - 2} fontSize="9" fill="var(--texte-attenue)">
        {nombre(bas, 0)} m
      </text>
      <text x={LARGEUR - 2} y="9" fontSize="9" fill="var(--texte-attenue)" textAnchor="end">
        {nombre(haut, 0)} m
      </text>
    </svg>
  );
}

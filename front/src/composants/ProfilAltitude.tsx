/** Le profil d'altitude, en paires `[distance_m, altitude_m]`.
 *
 * Un SVG et rien d'autre : le tracé se lit d'un coup d'œil, et les deux
 * chiffres qui l'encadrent — le point le plus bas et le plus haut — viennent
 * des données, jamais d'une échelle arrondie « pour faire joli ».
 *
 * **La pente colore l'aire sous la courbe** — un polygone gris uniforme
 * traiterait le profil comme de l'interface. C'est une mesure (règle 1 de la direction
 * visuelle), donc elle se colore, au standard du domaine que tout cycliste
 * lit sans légende : vert < 3 %, jaune 3–6 %, orange 6–9 %, rouge au-delà
 * (`--couleur-pente-1..4`, voir `jetons-primitives.css` pour les seuils, les
 * contrastes vérifiés, et la tension assumée avec `vent-dos`/`vent-face`/
 * `effort` sur ce même écran). La pente d'une **descente** compte tout
 * autant qu'une montée pour la lecture d'un parcours (freinage, technicité) :
 * la classification porte sur la valeur absolue du dénivelé local, pas
 * seulement les montées — à confirmer à l'usage, la direction ne tranchait
 * pas ce point.
 *
 * Ne colore JAMAIS par l'effort de la séance ici — c'est une autre mesure
 * (Z1–Z5), elle reste réservée aux `blocs` (rectangles translucides posés
 * par-dessus, propriété de l'écran, pas de ce composant) et ira un jour sur
 * une frise de la sortie, pas sur ce profil.
 *
 * Canal non coloré (règle d'accessibilité absolue de la direction) : le
 * trait du haut, toujours à l'encre, s'épaissit avec la pente locale — un
 * daltonien ou une lecture en plein soleil s'en sort sans la couleur. Le
 * point le plus raide du profil porte en plus son pourcentage écrit, et
 * `aria-label` le répète pour qui n'a pas d'image.
 */

import { nombre } from "../api/formats";

interface Props {
  profil: [number, number][];
  /** Les blocs, en mètres parcourus, pour les teinter sous la courbe. */
  blocs?: { debut_m: number; fin_m: number; couleur: string }[];
}

const LARGEUR = 320;
const HAUTEUR = 74;

/** Les quatre crans du standard du domaine, sur la valeur absolue du % de pente. */
const JETON_PENTE = ["--couleur-pente-1", "--couleur-pente-2", "--couleur-pente-3", "--couleur-pente-4"];
const EPAISSEUR_PENTE = [1.25, 1.75, 2.25, 2.75];

function bandeDe(pentePct: number): number {
  const abs = Math.abs(pentePct);
  if (abs < 3) return 0;
  if (abs < 6) return 1;
  if (abs < 9) return 2;
  return 3;
}

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

  // La pente locale de chaque segment (entre deux points consécutifs du
  // profil), en pourcentage — et le cran qui en découle. `n - 1` segments
  // pour `n` points.
  let bandeMax = -1;
  let indexPenteMax = 0;
  let pentePctMax = 0;
  const bandesSegments = profil.slice(0, -1).map(([d, a], i) => {
    const [dSuivant, aSuivant] = profil[i + 1];
    const distanceSegment = dSuivant - d;
    const pentePct = distanceSegment > 0 ? ((aSuivant - a) / distanceSegment) * 100 : 0;
    const bande = bandeDe(pentePct);
    if (bande > bandeMax || (bande === bandeMax && Math.abs(pentePct) > Math.abs(pentePctMax))) {
      bandeMax = bande;
      indexPenteMax = i;
      pentePctMax = pentePct;
    }
    return bande;
  });

  // Fusionne les segments consécutifs du même cran en une seule aire et une
  // seule ligne — sans ça, chaque segment redessinerait son propre polygone
  // et sa propre ligne, corrects mais inutilement nombreux (un profil de
  // 100 points ferait 99 formes au lieu d'une poignée de rubans).
  const runs: { debut: number; fin: number; bande: number }[] = [];
  for (let i = 0; i < bandesSegments.length; i += 1) {
    const bande = bandesSegments[i];
    const precedent = runs[runs.length - 1];
    if (precedent && precedent.bande === bande) {
      precedent.fin = i + 1;
    } else {
      runs.push({ debut: i, fin: i + 1, bande });
    }
  }

  // Le point le plus raide (calé sur `indexPenteMax`, le segment) : le
  // milieu du segment, pour poser l'étiquette au bon endroit de la courbe.
  const pointeLabel: [number, number] = [
    (profil[indexPenteMax][0] + profil[indexPenteMax + 1][0]) / 2,
    Math.max(profil[indexPenteMax][1], profil[indexPenteMax + 1][1]),
  ];
  const montreLabel = bandeMax >= 1; // à partir de « modérée » (≥ 3 %)

  return (
    <svg
      className="profil-alt"
      viewBox={`0 0 ${LARGEUR} ${HAUTEUR}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={
        `Profil du parcours, de ${nombre(bas, 0)} à ${nombre(haut, 0)} mètres d'altitude` +
        (montreLabel ? `, ${nombre(Math.abs(pentePctMax), 0)} % au point le plus raide` : "")
      }
    >
      {runs.map((run) => {
        const debutM = profil[run.debut][0];
        const finM = profil[run.fin][0];
        const points = profil
          .slice(run.debut, run.fin + 1)
          .map(([d, a]) => `${x(d).toFixed(1)},${y(a).toFixed(1)}`)
          .join(" ");
        const aire = `${x(debutM).toFixed(1)},${HAUTEUR} ${points} ${x(finM).toFixed(1)},${HAUTEUR}`;
        return (
          <polygon key={run.debut} points={aire} fill={`var(${JETON_PENTE[run.bande]})`} />
        );
      })}
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
      {/* Le trait du haut, toujours à l'encre : c'est le canal non coloré de
          la pente. Un ruban par cran, d'épaisseur croissante — une douce se
          voit fine, une sévère se voit épaisse, sans lire une seule teinte. */}
      {runs.map((run) => (
        <polyline
          key={`ligne-${run.debut}`}
          points={profil
            .slice(run.debut, run.fin + 1)
            .map(([d, a]) => `${x(d).toFixed(1)},${y(a).toFixed(1)}`)
            .join(" ")}
          fill="none"
          stroke="var(--texte)"
          strokeWidth={EPAISSEUR_PENTE[run.bande]}
        />
      ))}
      {montreLabel ? (
        <text
          x={Math.min(Math.max(x(pointeLabel[0]), 14), LARGEUR - 14)}
          y={Math.max(y(pointeLabel[1]) - 5, 9)}
          fontSize="9"
          fontWeight="700"
          textAnchor="middle"
          fill="var(--texte)"
        >
          {nombre(Math.abs(pentePctMax), 0)} %
        </text>
      ) : null}
      <text x="2" y={HAUTEUR - 2} fontSize="9" fill="var(--texte-attenue)">
        {nombre(bas, 0)} m
      </text>
      <text x={LARGEUR - 2} y="9" fontSize="9" fill="var(--texte-attenue)" textAnchor="end">
        {nombre(haut, 0)} m
      </text>
    </svg>
  );
}

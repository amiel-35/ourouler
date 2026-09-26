/** Le tracé découpé : portions entre deux distances, et coloration par le vent. */

import type { Trace, VentPosition } from "../../api/types";
import type { SegmentVent } from "../../composants/Carte";

/**
 * La portion de tracé entre deux distances, en mètres.
 *
 * `trace.profil[i][0]` est la distance cumulée au point `trace.points[i]` :
 * les deux listes ont la même longueur, c'est ce que rend l'API.
 */
export function portion(trace: Trace, debutM: number, finM: number): [number, number][] {
  const [a, b] = debutM <= finM ? [debutM, finM] : [finM, debutM];
  const points: [number, number][] = [];
  for (let i = 0; i < trace.points.length && i < trace.profil.length; i += 1) {
    const distance = trace.profil[i][0];
    if (distance >= a && distance <= b) points.push(trace.points[i]);
  }
  return points;
}

/**
 * Colore le tracé lui-même par ce que le vent y coûte — pas seulement les
 * huit flèches.
 *
 * `positions` couvre le tracé entier, échantillon par échantillon, sans
 * filtre de sensibilité (`vent_par_position`, voir sa docstring côté cœur).
 * Chaque **intervalle** entre deux échantillons consécutifs porte la
 * catégorie de l'échantillon qui l'ouvre (« le vent mesuré ici vaut jusqu'au
 * prochain échantillon ») ; les intervalles consécutifs de même catégorie
 * sont fusionnés en une seule portion, pour ne pas redessiner un segment
 * par échantillon. **Les intervalles, pas les échantillons** : fusionner les
 * échantillons eux-mêmes laisserait un trou d'un pas d'échantillonnage
 * (5 km par défaut) à chaque changement de catégorie — un vent qui bascule
 * souvent de face à dos sur une boucle se serait retrouvé troué à chaque
 * bascule. Fusionner les intervalles élimine le trou : la borne de fin d'une
 * portion est toujours la borne de début de la suivante.
 *
 * Le travers et l'inconnu ne produisent aucune portion — le tracé noir de
 * base reste visible en dessous, exactement comme la direction le demande
 * pour ces deux cas (l'ignorance ne se montre pas comme une valeur, et « le
 * vent traversier n'a délibérément aucune teinte »).
 *
 * Une portion dont `portion()` ne retrouve aucun point réel (bornes trop
 * rapprochées pour qu'un point du tracé simplifié tombe entre les deux,
 * notamment aux confins du tracé) est écartée plutôt que poussée vide :
 * sans ce filtre, `traceColoree` (l'écran) mentait — la légende affirmait
 * une coloration que `Carte` n'aurait de toute façon pas dessinée
 * (`Carte.tsx` écarte déjà un segment à moins de deux points, mais après
 * que l'écran a cru, à tort, qu'il y en avait un).
 */
export function segmentsVent(trace: Trace, positions: VentPosition[]): SegmentVent[] {
  const segments: SegmentVent[] = [];
  let i = 0;
  const n = positions.length;
  while (i < n - 1) {
    const categorie = positions[i].relatif;
    if (categorie !== "face" && categorie !== "dos") {
      i += 1;
      continue;
    }
    let j = i;
    while (j + 1 < n - 1 && positions[j + 1].relatif === categorie) j += 1;
    const points = portion(trace, positions[i].dist_m, positions[j + 1].dist_m);
    if (points.length >= 2) {
      segments.push({
        points,
        categorie,
        titre: categorie === "face" ? "Vent de face" : "Vent dans le dos",
      });
    }
    i = j + 1;
  }
  return segments;
}

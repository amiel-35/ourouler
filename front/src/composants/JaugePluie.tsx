/**
 * La pluie d'un parcours, dessinée plutôt qu'un seul nombre.
 *
 * Avant ce lot, `Boucles.tsx` et `Propositions.tsx` écrivaient « 0,0 mm de
 * pluie » — un chiffre nu, alors que le vent, lui, colore déjà le tracé
 * entier (`Proposition.tsx`, lot du 20/09/2026). La pluie a sa teinte dans
 * le système depuis toujours (`--couleur-pluie-*`) ; elle ne se dessinait
 * simplement pas encore ici.
 *
 * Une jauge courte, à l'échelle des quatre paliers d'affichage de la rose
 * (`api/meteoRose.niveauPluie` — sec/faible/modéré/fort, 0 à 3 mm et
 * au-delà) : le remplissage dit combien, le nombre écrit à côté dit
 * combien exactement — le canal non coloré, comme partout ailleurs dans ce
 * système.
 *
 * Un parcours sec (règle `visibleEnMm`, même seuil que `visibleEnKm`) ne
 * dessine **aucune jauge** — une barre vide ne montrerait rien — mais garde
 * le mot « sec » : contrairement à `km_non_classe` (un artefact d'arrondi
 * que taire est correct), « 0,0 mm » est ici la réponse normale et
 * attendue la plupart du temps, et la taire changerait un renseignement
 * (« c'est sec ») en absence d'information.
 */

import { nombre, dureeApprox } from "../api/formats";
import { niveauPluie, type NiveauPluie } from "../api/meteoRose";

/** Même seuil que `visibleEnKm` (`api/formats.ts`), pour des millimètres :
 * un cumul qui arrondit à 0,0 ne mérite ni jauge ni phrase. */
export function visibleEnMm(mm: number): boolean {
  return Math.round(mm * 10) > 0;
}

const JETON_PLUIE: Record<NiveauPluie, string | null> = {
  "aucune-donnee": null,
  sec: null,
  faible: "--couleur-pluie-fond",
  modere: "--couleur-pluie-remplissage",
  fort: "--couleur-pluie-trait",
};

/** L'échelle de la jauge : 3 mm remplissent la barre, au-delà elle sature —
 * la même borne « forte » que `niveauPluie`, pas une échelle inventée. */
const PLAFOND_MM = 3;
const LARGEUR = 34;
const HAUTEUR = 8;

export function JaugePluie({
  mm,
  minutesPluie,
}: {
  mm: number;
  /** Combien de minutes de ce parcours se font sous la pluie, si connu. */
  minutesPluie?: number | null;
}) {
  if (!visibleEnMm(mm)) {
    // Pas de jauge vide : le mot suffit, et il porte la même information
    // qu'avant ce lot (« 0,0 mm de pluie »), simplement plus court à lire.
    return (
      <span className="jauge-pluie">
        <b>Sec</b> — 0,0 mm de pluie
      </span>
    );
  }
  const niveau = niveauPluie(mm);
  const jeton = JETON_PLUIE[niveau];
  const largeurRemplie = Math.min(mm / PLAFOND_MM, 1) * LARGEUR;
  return (
    // Un seul bloc de texte qui s'enroule normalement (jamais un flex sur
    // toute la phrase) : posé en `inline-flex` sur l'ensemble, une phrase
    // longue — « (35 min sous la pluie) » — s'enroulait sur elle-même en
    // laissant le chiffre seul, centré à côté, un défaut trouvé à l'écran le
    // 20/09/2026. Seuls la jauge et son chiffre restent solidaires
    // (`.jauge-pluie-valeur`, `white-space: nowrap`) ; le reste de la phrase
    // est un flux normal, qui s'enroule comme n'importe quel texte.
    <span className="jauge-pluie">
      <span className="jauge-pluie-valeur">
        <svg viewBox={`0 0 ${LARGEUR} ${HAUTEUR}`} width={LARGEUR} height={HAUTEUR} aria-hidden="true">
          <rect x={0} y={0} width={LARGEUR} height={HAUTEUR} fill="var(--papier)" stroke="var(--trait)" />
          {jeton ? <rect x={0} y={0} width={largeurRemplie} height={HAUTEUR} fill={`var(${jeton})`} /> : null}
          {/* Les deux graduations à 1 et 3 mm — le canal non coloré de
              l'échelle elle-même, pour lire la jauge sans connaître le
              plafond par cœur. */}
          <line x1={LARGEUR / 3} y1={0} x2={LARGEUR / 3} y2={HAUTEUR} stroke="var(--trait)" strokeWidth={1} />
          <line x1={LARGEUR} y1={0} x2={LARGEUR} y2={HAUTEUR} stroke="var(--trait)" strokeWidth={1} />
        </svg>
        <b>{nombre(mm, 1)}</b>
      </span>{" "}
      mm de pluie
      {minutesPluie !== null && minutesPluie !== undefined && minutesPluie > 0
        ? ` (${dureeApprox(minutesPluie * 60)} sous la pluie)`
        : ""}
    </span>
  );
}

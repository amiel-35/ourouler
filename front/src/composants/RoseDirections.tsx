/**
 * La rose des huit directions — remplace les huit boutons de texte
 * (`N NE E SE S SO O NO`) qui ne portaient aucune information avant ce lot.
 *
 * Chaque secteur dessine ce que le produit sait déjà pour cette
 * direction-là : la pluie cumulée sur l'horizon (teinte pâle, quatre
 * paliers — `meteoRose.niveauPluie`), le désaccord entre les deux modèles
 * météo (un motif hachuré, jamais une cinquième couleur — règle absolue 5),
 * et le vent qu'on sentirait en partant maintenant dans cette direction
 * (une flèche-girouette, la même forme et les mêmes classes que sur la
 * carte — `composants/Carte.tsx`).
 *
 * Deux usages :
 *
 * - **interactif** (`onChoisir` fourni) : chaque secteur est un vrai
 *   contrôle — `role="button"`, `tabIndex`, `aria-pressed` — actionnable au
 *   clavier (Tab pour parcourir, Entrée/Espace pour choisir), au moins aussi
 *   bien que les huit boutons qu'il remplace. C'est `Demander.tsx`.
 * - **résumé** (`onChoisir` absent) : purement informatif, pas de contrôle,
 *   pour la lecture en trois secondes de `Aujourdhui.tsx` — la direction
 *   recommandée reste cerclée, rien ne se clique.
 *
 * Une décision (la direction recommandée) n'est jamais coloriée (règle 3) :
 * son secteur garde la teinte de sa propre pluie, et gagne seulement un
 * trait d'encre plus épais autour du secteur — jamais une couleur qui lui
 * serait propre.
 */

import { useId } from "react";
import {
  HUIT_DIRECTIONS,
  type DirectionMeteo,
  type NiveauPluie,
} from "../api/meteoRose";
import {
  nombre,
  ventDepuisAvecPreposition,
  VENT_DEPUIS_EN_TOUTES_LETTRES,
} from "../api/formats";

// `LARGEUR` porte une marge généreuse au-delà de `R_ETIQUETTE` (32px, deux
// lignes de texte — direction et mm) : posée trop juste (4px) à la première
// vérification à l'écran (20/09/2026), elle rognait le haut de « N », rendu
// visible seulement comme deux tirets. Un SVG racine clippe par défaut tout
// ce qui déborde de son `viewBox` — ce n'est pas un bug d'affichage isolé,
// c'est une marge insuffisante, corrigée ici plutôt que par un `overflow:
// visible` qui aurait juste déplacé le rognage sur le conteneur parent.
const LARGEUR = 320;
const CENTRE = LARGEUR / 2;
const R_EXTERIEUR = 118;
const R_INTERIEUR = 54;
const R_ETIQUETTE = 128;
const R_FLECHE = 86;
const LARGEUR_SECTEUR_DEG = 44; // < 45 : un mince filet de papier sépare chaque secteur

/** La forme de la flèche de vent, reprise à l'identique de `composants/Carte.tsx`
 * (elle-même reprise de `sortie/carte.py`) : une seule forme dans toute
 * l'application, jamais un second glyphe de vent inventé pour cet écran. */
const FORME_FLECHE = "M10 1 L17 18 L10 14 L3 18 Z";

/** Le remplissage de chaque palier de pluie — trois usages du même métier
 * (fond/remplissage/trait), réutilisés comme une rampe claire → soutenue :
 * même geste que `--couleur-pente-1..4` sur `ProfilAltitude`, jamais un
 * quatrième jeton pour « sec » (aucun remplissage, le papier suffit). */
const JETON_PLUIE: Record<NiveauPluie, string | null> = {
  "aucune-donnee": null,
  sec: null,
  faible: "--couleur-pluie-fond",
  modere: "--couleur-pluie-remplissage",
  fort: "--couleur-pluie-trait",
};

const LIBELLE_NIVEAU: Record<NiveauPluie, string> = {
  "aucune-donnee": "pluie inconnue",
  sec: "sec",
  faible: "pluie faible",
  modere: "pluie modérée",
  fort: "pluie forte",
};

function polaire(rayon: number, azimutDeg: number): { x: number; y: number } {
  const rad = (azimutDeg * Math.PI) / 180;
  return { x: CENTRE + rayon * Math.sin(rad), y: CENTRE - rayon * Math.cos(rad) };
}

/** Un secteur annulaire (donut) centré sur `azimutDeg`, de largeur `largeurDeg`. */
function cheminSecteur(rInterieur: number, rExterieur: number, azimutDeg: number, largeurDeg: number): string {
  const a0 = azimutDeg - largeurDeg / 2;
  const a1 = azimutDeg + largeurDeg / 2;
  const pExt0 = polaire(rExterieur, a0);
  const pExt1 = polaire(rExterieur, a1);
  const pInt1 = polaire(rInterieur, a1);
  const pInt0 = polaire(rInterieur, a0);
  return [
    `M ${pExt0.x.toFixed(1)} ${pExt0.y.toFixed(1)}`,
    `A ${rExterieur} ${rExterieur} 0 0 1 ${pExt1.x.toFixed(1)} ${pExt1.y.toFixed(1)}`,
    `L ${pInt1.x.toFixed(1)} ${pInt1.y.toFixed(1)}`,
    `A ${rInterieur} ${rInterieur} 0 0 0 ${pInt0.x.toFixed(1)} ${pInt0.y.toFixed(1)}`,
    "Z",
  ].join(" ");
}

function nomDirection(code: string): string {
  // Réutilise la table de `formats.ts` : une simple correspondance
  // code → nom en français, pas spécifique au vent malgré son nom — une
  // seconde table dupliquerait la même donnée sous un autre nom.
  return VENT_DEPUIS_EN_TOUTES_LETTRES[code] ?? code;
}

/** « de face » / « dans le dos » / « de travers », ou `null` si l'API n'a pas tranché. */
function relatifEnMots(relatif: string | null): string | null {
  if (relatif === "face") return "de face";
  if (relatif === "dos") return "dans le dos";
  if (relatif === "travers") return "de travers";
  return null;
}

/** La phrase de vent d'une direction, ou son absence — jamais un vent inventé. */
function phraseVentDirection(direction: DirectionMeteo): string {
  if (direction.ventDepuisDeg === null || direction.ventKmh === null) return "vent inconnu";
  const base = `vent ${ventDepuisAvecPreposition(cardinalDuVent(direction.ventDepuisDeg))} à ${nombre(direction.ventKmh, 0)} km/h`;
  const relatif = relatifEnMots(direction.relatif);
  return relatif ? `${base}, ${relatif}` : base;
}

/** L'étiquette accessible complète d'un secteur — le canal non coloré ultime :
 * tout ce que la forme et la couleur disent, en mots, pour qui ne les voit pas. */
function libelleSecteur(direction: DirectionMeteo, recommandee: boolean): string {
  const morceaux = [nomDirection(direction.nom)];
  morceaux.push(
    direction.pluieMm === null
      ? "pluie inconnue"
      : `${LIBELLE_NIVEAU[direction.niveau]}, ${nombre(direction.pluieMm, 1)} mm`,
  );
  if (direction.desaccord) morceaux.push("modèles météo en désaccord");
  morceaux.push(phraseVentDirection(direction));
  if (recommandee) morceaux.push("recommandée");
  return morceaux.join(" — ");
}

/** La phrase d'une ligne, pour le résumé compact de `Aujourdhui.tsx`
 * (`RoseResume` plus bas) — les mêmes mots que `libelleSecteur`, dans
 * l'ordre d'une phrase plutôt qu'une liste. */
export function resumeDirection(direction: DirectionMeteo): string {
  const pluie =
    direction.pluieMm === null
      ? "pluie inconnue"
      : direction.niveau === "sec"
        ? "sec"
        : `${LIBELLE_NIVEAU[direction.niveau]} (${nombre(direction.pluieMm, 1)} mm${direction.desaccord ? ", désaccord entre modèles" : ""})`;
  return `${nomDirection(direction.nom)} : ${pluie}, ${phraseVentDirection(direction)}.`;
}

/** L'azimut d'où vient le vent, ramené au cardinal le plus proche — pour la
 * phrase seulement, jamais pour reclasser face/dos/travers (ça, c'est
 * `vent_relatif`, déjà tranché par l'API). */
function cardinalDuVent(azimutDeg: number): string {
  const index = Math.round((((azimutDeg % 360) + 360) % 360) / 45) % 8;
  return HUIT_DIRECTIONS[index];
}

export interface Props {
  directions: DirectionMeteo[];
  /** Le nom de la direction que la météo recommande (`Meteo.meilleure_direction`). */
  recommandee: string | null;
  /** La direction choisie — pour le mode interactif comme pour le résumé. */
  choisie?: string | null;
  /** Sa présence bascule le composant en mode interactif (voir l'en-tête du fichier). */
  onChoisir?: (nom: string) => void;
  /** Le résumé de `Aujourdhui.tsx` : plus petit, sans les étiquettes de pluie en mm. */
  compact?: boolean;
}

export function RoseDirections({ directions, recommandee, choisie, onChoisir, compact = false }: Props) {
  const idMotif = useId();
  const idDesaccord = `${idMotif}-desaccord`;
  const idInconnu = `${idMotif}-inconnu`;
  const interactif = onChoisir !== undefined;
  // Le viewBox reste toujours 280×280 : `width`/`height` demandent au SVG de
  // mettre à l'échelle tout le dessin d'un coup — c'est ainsi que `compact`
  // rétrécit la rose sans recalculer un seul rayon.
  const largeur = compact ? 200 : LARGEUR;

  return (
    <svg
      className={`rose-directions${compact ? " compacte" : ""}`}
      viewBox={`0 0 ${LARGEUR} ${LARGEUR}`}
      width={largeur}
      height={largeur}
      role={interactif ? "group" : "img"}
      aria-label={
        interactif
          ? "Choisir une direction — pluie et vent des huit directions"
          : "Où rouler : la pluie et le vent des huit directions"
      }
    >
      <defs>
        <pattern id={idDesaccord} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--texte)" strokeWidth="1.4" />
        </pattern>
        <pattern id={idInconnu} width="7" height="7" patternUnits="userSpaceOnUse">
          <circle cx="1.5" cy="1.5" r="0.9" fill="var(--texte-faible)" />
        </pattern>
      </defs>

      {directions.map((direction) => {
        const jeton = JETON_PLUIE[direction.niveau];
        const estRecommandee = recommandee === direction.nom;
        const estChoisie = choisie === direction.nom;
        const chemin = cheminSecteur(R_INTERIEUR, R_EXTERIEUR, direction.azimutDeg, LARGEUR_SECTEUR_DEG);
        const contenu = (
          <>
            <path
              d={chemin}
              fill={
                direction.niveau === "aucune-donnee"
                  ? `url(#${idInconnu})`
                  : jeton
                    ? `var(${jeton})`
                    : "var(--papier)"
              }
              stroke="var(--trait)"
              strokeWidth={1}
            />
            {direction.desaccord ? <path d={chemin} fill={`url(#${idDesaccord})`} /> : null}
            {estRecommandee ? (
              // La direction recommandée n'est jamais coloriée (règle 3, une
              // décision n'est pas une mesure) : un cerclage d'encre épais,
              // `--epaisseur-decision` — le même trait que la matrice
              // d'`Arbitrage` pour une décision du cœur.
              <path d={chemin} fill="none" stroke="var(--trait-fort)" strokeWidth="var(--epaisseur-decision)" />
            ) : null}
            {estChoisie && !estRecommandee ? (
              <path d={chemin} fill="none" stroke="var(--texte)" strokeWidth="1.5" strokeDasharray="2 2" />
            ) : null}
            {direction.ventDepuisDeg !== null ? (
              (() => {
                const { x, y } = polaire(R_FLECHE, direction.azimutDeg);
                return (
                  <g
                    className={`vent-marqueur vent-${direction.relatif ?? "inconnu"}`}
                    transform={`translate(${(x - 10).toFixed(1)} ${(y - 10).toFixed(1)}) rotate(${direction.ventDepuisDeg} 10 10)`}
                  >
                    <path className="fleche-forme" d={FORME_FLECHE} />
                  </g>
                );
              })()
            ) : null}
            {(() => {
              const { x, y } = polaire(R_ETIQUETTE, direction.azimutDeg);
              return (
                <g>
                  <text
                    x={x}
                    y={compact ? y + 3 : y - 3}
                    textAnchor="middle"
                    fontSize={compact ? 12 : 13}
                    fontWeight={estRecommandee ? 700 : 500}
                    fill="var(--texte)"
                  >
                    {direction.nom}
                  </text>
                  {!compact ? (
                    <text x={x} y={y + 12} textAnchor="middle" fontSize={9} fill="var(--texte-attenue)">
                      {direction.pluieMm === null ? "?" : `${nombre(direction.pluieMm, 1)}${direction.desaccord ? "*" : ""}`}
                    </text>
                  ) : null}
                </g>
              );
            })()}
          </>
        );

        if (!interactif) {
          return <g key={direction.nom}>{contenu}</g>;
        }

        return (
          <g
            key={direction.nom}
            role="button"
            tabIndex={0}
            aria-pressed={estChoisie}
            aria-label={libelleSecteur(direction, estRecommandee)}
            className="rose-secteur"
            onClick={() => onChoisir(direction.nom)}
            onKeyDown={(evenement) => {
              if (evenement.key === "Enter" || evenement.key === " ") {
                evenement.preventDefault();
                onChoisir(direction.nom);
              }
            }}
          >
            {contenu}
          </g>
        );
      })}

      <circle cx={CENTRE} cy={CENTRE} r={R_INTERIEUR - 6} fill="none" stroke="var(--trait)" strokeWidth={1} />
      <text x={CENTRE} y={CENTRE + 4} textAnchor="middle" fontSize={compact ? 10 : 11} fill="var(--texte-attenue)">
        Départ
      </text>
    </svg>
  );
}

/**
 * La légende complète, sous la rose — `Demander.tsx` seulement (le résumé
 * de `Aujourdhui.tsx` s'en passe, voir `RoseResume`). Reprend le même
 * vocabulaire que `LegendeVent` (`composants/Carte.tsx`) pour le vent : les
 * mêmes classes `.vent-swatch`, les mêmes trois glyphes.
 */
export function LegendeRose() {
  return (
    <div className="legende-rose">
      <div className="groupe">
        <span className="titre-groupe">Pluie cumulée</span>
        <span className="puce">
          <span className="pluie-swatch" data-niveau="sec" /> Sec
        </span>
        <span className="puce">
          <span className="pluie-swatch" data-niveau="faible" /> Faible — 0,1 à 1,0 mm
        </span>
        <span className="puce">
          <span className="pluie-swatch" data-niveau="modere" /> Modérée — 1,1 à 3,0 mm
        </span>
        <span className="puce">
          <span className="pluie-swatch" data-niveau="fort" /> Forte — plus de 3,0 mm
        </span>
        <span className="puce">
          <span className="pluie-swatch" data-niveau="desaccord" /> * — les deux modèles ne
          sont pas d'accord, affiché tel quel
        </span>
      </div>
      <div className="groupe">
        <span className="titre-groupe">Vent, en partant</span>
        <span className="puce">
          <span className="vent-swatch vent-face">▲</span> de face (ça freine)
        </span>
        <span className="puce">
          <span className="vent-swatch vent-dos">△</span> dans le dos (ça pousse)
        </span>
        <span className="puce">
          <span className="vent-swatch vent-travers">◇</span> de travers (aucune teinte)
        </span>
      </div>
    </div>
  );
}

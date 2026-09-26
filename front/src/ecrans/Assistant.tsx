/** L'assistant d'accueil — un arbre, pas six étapes fixes.
 *
 * Réécrit le 19/09/2026 pour suivre `docs/ux/parcours_accueil.md` : l'ancien
 * assistant posait FTP puis poids puis vélo dans un ordre figé. Le nouveau
 * distingue deux axes indépendants — d'où viennent les sorties (Intervals >
 * export > rien), et si la FTP est connue — et descend un **entonnoir en
 * cinq étages** (T1 à T5, du plus précis au plus flou) qui saute les étages
 * inutiles dès qu'un chiffre exploitable est trouvé plus haut. C'est pour ça
 * que l'état n'est plus un simple index dans un tableau : `Etape` est une
 * union nommée, et chaque écran décide lui-même de la suivante.
 *
 * Le socle — identité, départ — reste en tête, dans un ordre humain qui ne
 * calcule rien (§5.1 du document) ; poids et vélo se posent juste avant la
 * première chose qui en a besoin dans l'entonnoir, pas en bloc figé.
 *
 * `etage` retient par quelle voie une FTP a fini par exister, uniquement
 * pour la phrase de confiance du récapitulatif (§9) — rien d'autre n'en
 * dépend.
 *
 * L'état et les enregistrements vivent dans `assistant/useAssistant.ts`,
 * chaque étape de l'arbre dans `assistant/Etape*.tsx` ; cet écran ne fait
 * qu'aiguiller vers l'étape courante.
 */

import type { Profil, Zones } from "../api/types";
import { RetourEnTete } from "../composants/Retour";
import { LIBELLES } from "./assistant/arbre";
import { EtapeExport } from "./assistant/EtapeExport";
import { EtapeRecap, EtapeT3, EtapeT4Terrain, EtapeT4Vitesse } from "./assistant/EtapesFtp";
import { EtapeT1Cle, EtapeT1Confirmation } from "./assistant/EtapesIntervals";
import { EtapePoids, EtapeVelo } from "./assistant/EtapesProfil";
import { EtapeBienvenue, EtapeDepart, EtapeIdentite, EtapeT1Question } from "./assistant/EtapesSocle";
import { useAssistant } from "./assistant/useAssistant";

interface Props {
  profil: Profil;
  zones: Zones;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
  surFin: () => void;
  /** D'où l'assistant a été ouvert (Aujourd'hui, à la première connexion ;
   * Réglages, via « Refaire l'installation ») — jamais « Retour » seul. */
  vers: string;
  /** Quitter l'assistant sans le terminer — il ne force jamais qu'une
   * seule fois (`App.tsx`), la personne doit pouvoir sortir volontairement. */
  surRetour: () => void;
}

export function Assistant({ profil, zones, surProfil, surZones, surFin, vers, surRetour }: Props) {
  const a = useAssistant({ profil, surProfil, surZones });
  const { etape, historique, panne, etage, intervalsTrouve, revenir } = a;
  const { rubrique, titre } = LIBELLES[etape];

  return (
    <section>
      {/* L'assistant n'avait aucun moyen d'en sortir avant la fin (constat
          du 19/09/2026) — seulement un pas en arrière dans l'arbre
          (`revenir`, plus bas), jamais une sortie complète. */}
      <RetourEnTete vers={vers} surRetour={surRetour} />
      {/* La rubrique ne s'affiche qu'une fois. Elle l'était deux : ici et dans
          `app-tete` juste dessous — reste du compteur « Étape X sur Y »,
          retiré quand l'assistant est devenu un arbre qui branche, sans que
          son emplacement le soit. Constaté à l'écran le 20/09/2026. */}
      <div className="app-tete">
        <div>
          <span className="quand">{rubrique}</span>
          <h1>{titre}</h1>
        </div>
      </div>

      {panne ? <div className="encart alerte">{panne}</div> : null}

      {etape === "bienvenue" ? <EtapeBienvenue a={a} /> : null}
      {etape === "identite" ? <EtapeIdentite a={a} /> : null}
      {etape === "depart" ? <EtapeDepart a={a} profil={profil} /> : null}
      {etape === "t1_question" ? <EtapeT1Question a={a} /> : null}
      {etape === "t1_cle" ? <EtapeT1Cle a={a} profil={profil} /> : null}
      {etape === "t1_confirmation" && intervalsTrouve ? (
        <EtapeT1Confirmation a={a} intervalsTrouve={intervalsTrouve} />
      ) : null}
      {etape === "t2" ? <EtapeExport a={a} /> : null}
      {etape === "poids" ? <EtapePoids a={a} zones={zones} /> : null}
      {etape === "velo" ? <EtapeVelo a={a} profil={profil} /> : null}
      {etape === "t3" ? <EtapeT3 a={a} zones={zones} surZones={surZones} /> : null}
      {etape === "t4_vitesse" ? <EtapeT4Vitesse a={a} /> : null}
      {etape === "t4_terrain" ? <EtapeT4Terrain a={a} /> : null}
      {etape === "recap" ? (
        <EtapeRecap etage={etage} profil={profil} zones={zones} surFin={surFin} />
      ) : null}

      {historique.length > 0 && etape !== "recap" ? (
        <button type="button" className="bouton fantome" onClick={revenir}>
          Revenir en arrière
        </button>
      ) : null}
    </section>
  );
}

/** La séance, étape par étape — le même vocabulaire partout.
 *
 * Quand un emplacement accompagne l'étape (écran du détail), la colonne de
 * droite porte le **kilométrage parcouru**, celui qui monte sur un compteur,
 * jamais la position sur le tracé — qui peut reculer après un demi-tour
 * (`src/ourouler/services/sortie.py`).
 */

import type { Emplacement, Etape } from "../api/types";
import { duree, nombre } from "../api/formats";

/**
 * La couleur d'un type d'étape : les quatre du cœur, et rien d'autre.
 *
 * Sur l'échelle d'effort à cinq crans (`--couleur-effort-1..5`, direction
 * « suisse vivante », `docs/ux/doctrine_design_system.md`) : échauffement et
 * retour au calme sont légers (effort-1), la récupération un cran au-dessus
 * (effort-2), et le bloc — l'intervalle qui compte — au rang le plus
 * soutenu (effort-5). C'est la correspondance proposée par le système
 * lui-même (`front/src/style.css`, section ÉTAPES), reprise ici.
 */
export const COULEUR_TYPE: Record<string, string> = {
  echauffement: "var(--couleur-effort-1)",
  bloc: "var(--couleur-effort-5)",
  recuperation: "var(--couleur-effort-2)",
  calme: "var(--couleur-effort-1)",
};

export const NOM_TYPE: Record<string, string> = {
  echauffement: "Échauffement",
  bloc: "Bloc",
  recuperation: "Récupération",
  calme: "Retour au calme",
};

function puissance(etape: Etape): string | null {
  if (etape.puissance_min_w !== null && etape.puissance_max_w !== null) {
    if (etape.puissance_min_w !== etape.puissance_max_w) {
      return `${nombre(etape.puissance_min_w)} – ${nombre(etape.puissance_max_w)} W`;
    }
  }
  if (etape.puissance_cible_w !== null) return `${nombre(etape.puissance_cible_w)} W`;
  return null;
}

interface Props {
  etapes: Etape[];
  /** Un emplacement par étape, quand la séance est posée sur un parcours. */
  emplacements?: Emplacement[];
}

export function Etapes({ etapes, emplacements }: Props) {
  const parIndice = new Map((emplacements ?? []).map((e) => [e.etape_idx, e]));
  return (
    <div className="etapes">
      {etapes.map((etape) => {
        const place = parIndice.get(etape.indice);
        const watts = puissance(etape);
        const motifs = place?.motifs?.length ? place.motifs.join(", ") : null;
        return (
          <div className="etape" key={etape.indice}>
            <span
              className="pt"
              style={{ background: COULEUR_TYPE[etape.type] ?? "var(--texte-attenue)" }}
              aria-hidden="true"
            />
            <span className="nom">
              <b>
                {NOM_TYPE[etape.type] ?? etape.type} — {duree(etape.duree_s)}
              </b>
              <small>
                {[etape.libelle, watts, motifs].filter(Boolean).join(" · ")}
                {place?.demi_tour ? " · demi-tour" : ""}
              </small>
            </span>
            <span className="km">
              {place
                ? `${nombre(place.debut_parcouru_m / 1000, 1)} → ${nombre(
                    (place.debut_parcouru_m + place.longueur_m) / 1000,
                    1,
                  )}`
                : duree(etape.duree_s)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

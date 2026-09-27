/** « Envoyer vers mon compteur » + le lien de téléchargement — communs à
 * l'écran d'une boucle libre (`ecrans/Boucles.tsx`) et à celui d'une
 * proposition (`ecrans/proposition/Onglets.tsx`) : même geste, même
 * distinction entre une panne du serveur et un navigateur qui ne sait pas
 * partager de fichier (`composants/partager.ts`).
 *
 * Le lien garde exactement les attributs que l'écran lui donne : `classeLien`
 * n'est pas un choix de ce composant, c'est celui de chaque écran (`bouton`
 * sur les boucles, `bouton fantome` sur la proposition), pour ne rien changer
 * à ce que les tests existants vérifient (`href`/`download`/classe).
 */

import type { PanneGpx } from "../api/client";
import { partager } from "./partager";

export function BoutonsGpx({
  gpx,
  erreur,
  surErreur,
  classeLien,
}: {
  gpx: { nom: string; url: string };
  erreur: PanneGpx | null;
  surErreur: (panne: PanneGpx | null) => void;
  classeLien: string;
}) {
  return (
    <>
      {erreur ? (
        <div className="encart alerte" role="alert">
          <b>L'envoi vers votre compteur a échoué.</b> {erreur.message}
          <p className="mention" style={{ marginTop: "var(--espace-interne)", marginBottom: 0 }}>
            Code de la panne : {erreur.code}.
          </p>
        </div>
      ) : null}
      <button type="button" className="bouton" onClick={partager(gpx.url, gpx.nom, surErreur)}>
        Envoyer vers mon compteur
      </button>
      <a className={classeLien} href={gpx.url} download={gpx.nom}>
        Télécharger le GPX
      </a>
    </>
  );
}

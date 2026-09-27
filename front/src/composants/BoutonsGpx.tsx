/** « Envoyer vers mon compteur » + le lien de téléchargement — communs à
 * l'écran d'une boucle libre (`ecrans/Boucles.tsx`) et à celui d'une
 * proposition (`ecrans/proposition/Onglets.tsx`) : même geste, même
 * distinction entre une panne du serveur et un navigateur qui ne sait pas
 * partager de fichier (`composants/partager.ts`).
 *
 * Le fichier GPX est récupéré ici, **dès que le bouton s'affiche** pour une
 * URL donnée — pas au clic. Safari (iPhone) exige que `navigator.share` soit
 * appelé dans l'activation transitoire du clic ; attendre le réseau avant de
 * l'appeler la lui fait perdre et le partage échoue silencieusement en
 * « ce navigateur ne sait pas partager ». Tant que le fichier n'est pas prêt,
 * le bouton est désactivé avec un libellé d'attente court.
 *
 * Le lien garde exactement les attributs que l'écran lui donne : `classeLien`
 * n'est pas un choix de ce composant, c'est celui de chaque écran (`bouton`
 * sur les boucles, `bouton fantome` sur la proposition), pour ne rien changer
 * à ce que les tests existants vérifient (`href`/`download`/classe).
 */

import { useEffect, useState } from "react";
import { type PanneGpx, recupererGpx } from "../api/client";
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
  const [contenu, setContenu] = useState<Blob | null>(null);

  useEffect(() => {
    setContenu(null);
    let annule = false;
    recupererGpx(gpx.url).then(
      (blob) => {
        if (!annule) setContenu(blob);
      },
      (panne: unknown) => {
        // Le serveur a refusé, ou le réseau ne répond pas : ni l'un ni
        // l'autre n'est une affaire de navigateur, et dire « ce navigateur
        // ne sait pas partager » serait faux ici.
        if (!annule) surErreur(panne as PanneGpx);
      },
    );
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `surErreur` change à chaque rendu (fermeture sur l'état local de l'écran) ; ne dépendre que de l'URL évite de relancer la requête à chaque rendu.
  }, [gpx.url]);

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
      <button
        type="button"
        className="bouton"
        disabled={!contenu}
        onClick={contenu ? partager(contenu, gpx.nom, surErreur) : undefined}
      >
        {contenu ? "Envoyer vers mon compteur" : "Préparation du fichier…"}
      </button>
      <a className={classeLien} href={gpx.url} download={gpx.nom}>
        Télécharger le GPX
      </a>
    </>
  );
}

/** « Envoyer vers mon compteur » : le partage système du fichier GPX (décision Q5). */

import { type PanneGpx, recupererGpx } from "../../api/client";

export function partager(url: string, nom: string, surEchec: (panne: PanneGpx | null) => void) {
  return async () => {
    // Un nouvel essai efface la panne du précédent : sinon le message reste
    // affiché même quand l'essai suivant réussit.
    surEchec(null);
    let contenu: Blob;
    try {
      contenu = await recupererGpx(url);
    } catch (panne) {
      // Le serveur a refusé, ou le réseau ne répond pas : ni l'un ni l'autre
      // n'est une affaire de navigateur, et dire « ce navigateur ne sait pas
      // partager » serait faux ici — c'est exactement le défaut trouvé le
      // 18/09/2026.
      surEchec(panne as PanneGpx);
      return;
    }
    try {
      const fichier = new File([contenu], nom, { type: "application/gpx+xml" });
      const partage = navigator as Navigator & {
        canShare?: (donnees: { files: File[] }) => boolean;
        share?: (donnees: { files: File[]; title?: string }) => Promise<void>;
      };
      if (partage.share && partage.canShare?.({ files: [fichier] })) {
        await partage.share({ files: [fichier], title: nom });
        return;
      }
    } catch {
      /* le partage a été refusé ou n'existe pas : le lien du dessous reste */
    }
    window.alert(
      "Ce navigateur ne sait pas partager de fichier. Utilisez « Télécharger le GPX » " +
        "juste en dessous, puis envoyez-le à votre compteur comme d'habitude.",
    );
  };
}

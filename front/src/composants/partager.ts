/** « Envoyer vers mon compteur » : le partage système du fichier GPX (décision Q5).
 *
 * Partagé par deux écrans — la proposition d'une sortie
 * (`ecrans/proposition/Onglets.tsx`) et une boucle libre (`ecrans/Boucles.tsx`) —
 * donc rangé ici plutôt que sous l'un des deux.
 *
 * Safari (iPhone) exige que `navigator.share` soit appelé **dans**
 * l'activation transitoire du clic : le moindre `await` avant — même un
 * `fetch` déjà terminé — la lui fait perdre, et `share()` rejette alors avec
 * `NotAllowedError`. C'est pour ça que le GPX est récupéré à l'avance par
 * `BoutonsGpx` (dès que le bouton s'affiche pour une URL donnée) : cette
 * fonction ne fait plus aucune attente réseau, elle reçoit le contenu déjà en
 * main et appelle `share` en tout premier geste synchrone du clic.
 */

import type { PanneGpx } from "../api/client";

const PANNE_PARTAGE_REFUSE: PanneGpx = {
  code: "partage_refuse",
  message: "Le partage a été refusé par le navigateur. Utilisez « Télécharger le GPX » juste en dessous.",
};

type NavigateurPartage = Navigator & {
  canShare?: (donnees: { files: File[] }) => boolean;
  share?: (donnees: { files: File[]; title?: string }) => Promise<void>;
};

/** Les types MIME essayés dans l'ordre : certains navigateurs refusent le
 * premier via `canShare` (type GPX pas reconnu) mais acceptent le second. */
const TYPES_MIME_ESSAYES = ["application/gpx+xml", "application/octet-stream"];

function fichierPartageable(contenu: Blob, nom: string, partage: NavigateurPartage): File | null {
  if (!partage.share) return null;
  for (const type of TYPES_MIME_ESSAYES) {
    const fichier = new File([contenu], nom, { type });
    if (partage.canShare?.({ files: [fichier] })) return fichier;
  }
  return null;
}

/**
 * `contenu` est déjà en main (récupéré par `BoutonsGpx` avant l'affichage du
 * bouton) : cette fonction n'attend plus rien, elle ne fait qu'appeler
 * `navigator.share` en premier geste du clic, pour rester dans l'activation
 * transitoire que Safari exige.
 */
export function partager(contenu: Blob, nom: string, surEchec: (panne: PanneGpx | null) => void) {
  return () => {
    // Un nouvel essai efface la panne du précédent : sinon le message reste
    // affiché même quand l'essai suivant réussit.
    surEchec(null);
    const partage = navigator as NavigateurPartage;
    const fichier = fichierPartageable(contenu, nom, partage);
    if (!fichier) {
      window.alert(
        "Ce navigateur ne sait pas partager de fichier. Utilisez « Télécharger le GPX » " +
          "juste en dessous, puis envoyez-le à votre compteur comme d'habitude.",
      );
      return;
    }
    partage.share!({ files: [fichier], title: nom }).catch((erreur: unknown) => {
      // Le cycliste a fermé la feuille de partage : ce n'est pas un échec,
      // rien à afficher. `DOMException` n'hérite pas forcément d'`Error`
      // (ce n'est pas le cas sous Node/jsdom) : on lit `.name` directement
      // plutôt que de filtrer par `instanceof Error`.
      const nomErreur = (erreur as { name?: unknown } | null)?.name;
      if (nomErreur === "AbortError") return;
      surEchec(PANNE_PARTAGE_REFUSE);
    });
  };
}

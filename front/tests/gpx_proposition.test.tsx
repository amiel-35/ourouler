/** Q40 (g) : chaque proposition emporte **sa** trace, pas celle du classement.
 *
 * Le défaut corrigé se voyait dehors et pas avant : choisir « la plus
 * sèche », appuyer sur « Envoyer vers mon compteur », et partir avec « la
 * plus calme ». L'écran doit donc pointer l'adresse de la proposition
 * affichée, et d'aucune autre.
 *
 * Depuis la correction du 27/09/2026 (iPhone Safari, `NotAllowedError`), le
 * GPX est récupéré **avant** le clic, dès que le bouton s'affiche : les
 * tests qui simulent le partage stubbent donc `fetch` avant le rendu, et
 * attendent que le bouton passe de « Préparation du fichier… » à « Envoyer
 * vers mon compteur » avant de cliquer.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PropositionDetail } from "../src/ecrans/Proposition";
import { SEANCE, sortie } from "./fixtures";
import { panne } from "./serveur";

function afficher(numero: number) {
  const reponse = sortie({ propositions: 3 });
  return {
    reponse,
    rendu: render(
      <PropositionDetail
        reponse={reponse}
        numero={numero}
        seance={SEANCE.donnees}
        surRetour={() => undefined}
      />,
    ),
  };
}

function reponseGpxOk(): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(["<gpx />"], { type: "application/gpx+xml" }),
  } as unknown as Response;
}

function stubPartage(
  canShareImpl: (donnees: { files: File[] }) => boolean,
  shareImpl: (donnees: { files: File[]; title?: string }) => Promise<void>,
) {
  const canShare = vi.fn(canShareImpl);
  const share = vi.fn(shareImpl);
  Object.defineProperty(navigator, "canShare", { value: canShare, configurable: true });
  Object.defineProperty(navigator, "share", { value: share, configurable: true });
  return { canShare, share };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (navigator as { canShare?: unknown }).canShare;
  delete (navigator as { share?: unknown }).share;
});

describe("le GPX d'une proposition", () => {
  it("pointe la trace de la proposition affichée, quelle qu'elle soit", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    for (const numero of [1, 2, 3]) {
      const { reponse, rendu } = afficher(numero);
      const attendue = reponse.donnees.propositions.find((p) => p.numero === numero)!.gpx!;
      const lien = screen.getByText("Télécharger le GPX").closest("a")!;
      expect(lien.getAttribute("href")).toBe(attendue.url);
      expect(lien.getAttribute("download")).toBe(attendue.nom);
      // Laisse la récupération du GPX (déclenchée dès l'affichage du
      // bouton) se terminer avant de démonter, pour ne pas mettre à jour un
      // composant déjà démonté.
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
      rendu.unmount();
    }
  });

  it("propose le bouton d'envoi sur une proposition qui n'est pas la retenue", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const { rendu } = afficher(3);
    await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
    rendu.unmount();
  });

  describe("le partage n'attend plus le réseau au clic (Safari iPhone)", () => {
    it("récupère le GPX dès l'affichage du bouton, et le partage sans nouvel appel réseau au clic", async () => {
      const fetchMock = vi.fn(reponseGpxOk);
      vi.stubGlobal("fetch", fetchMock);
      afficher(1);

      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
      expect(fetchMock).toHaveBeenCalledTimes(1);

      let fichiersPartages: File[] = [];
      const { share } = stubPartage(
        () => true,
        async (donnees) => {
          fichiersPartages = donnees.files;
        },
      );

      const utilisateur = userEvent.setup();
      await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(share).toHaveBeenCalledTimes(1);
      expect(fichiersPartages).toHaveLength(1);
      expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();
    });

    it("désactive le bouton tant que le fichier n'est pas prêt", async () => {
      let resoudre: (reponse: Response) => void = () => undefined;
      vi.stubGlobal(
        "fetch",
        vi.fn(() => new Promise<Response>((r) => (resoudre = r))),
      );
      afficher(1);

      const bouton = screen.getByText("Préparation du fichier…").closest("button") as HTMLButtonElement;
      expect(bouton.disabled).toBe(true);

      resoudre(reponseGpxOk());
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
      const boutonPret = screen.getByText("Envoyer vers mon compteur").closest("button") as HTMLButtonElement;
      expect(boutonPret.disabled).toBe(false);
    });

    it("essaie application/octet-stream quand canShare refuse application/gpx+xml", async () => {
      vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
      afficher(1);
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());

      const typesEssayes: string[] = [];
      let fichierPartage: File | null = null;
      stubPartage(
        (donnees) => {
          typesEssayes.push(donnees.files[0].type);
          return donnees.files[0].type === "application/octet-stream";
        },
        async (donnees) => {
          fichierPartage = donnees.files[0];
        },
      );

      const utilisateur = userEvent.setup();
      await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

      expect(typesEssayes).toEqual(["application/gpx+xml", "application/octet-stream"]);
      expect(fichierPartage).not.toBeNull();
      expect(fichierPartage!.type).toBe("application/octet-stream");
    });

    it("n'affiche rien quand le cycliste ferme la feuille de partage (AbortError)", async () => {
      vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
      afficher(1);
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());

      stubPartage(
        () => true,
        async () => {
          throw new DOMException("Share canceled", "AbortError");
        },
      );
      const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);

      const utilisateur = userEvent.setup();
      await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));
      await new Promise((resoudre) => setTimeout(resoudre, 0));

      expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();
      expect(alerte).not.toHaveBeenCalled();
    });

    it("affiche un message distinct — pas l'alerte — quand le partage est refusé (NotAllowedError)", async () => {
      vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
      afficher(1);
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());

      stubPartage(
        () => true,
        async () => {
          throw new DOMException("Not allowed", "NotAllowedError");
        },
      );
      const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);

      const utilisateur = userEvent.setup();
      await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

      await waitFor(() =>
        expect(screen.getByText(/Le partage a été refusé par le navigateur/)).toBeTruthy(),
      );
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(alerte).not.toHaveBeenCalled();
    });

    it("laisse le lien de téléchargement quand aucun type MIME n'est accepté", async () => {
      vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
      afficher(1);
      await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());

      const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
      // Pas de `navigator.share` : le navigateur ne sait pas partager du tout.

      const utilisateur = userEvent.setup();
      await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

      expect(alerte).toHaveBeenCalled();
      expect(alerte.mock.calls[0][0]).toMatch(/Ce navigateur ne sait pas partager de fichier/);
      expect(screen.getByText("Télécharger le GPX")).toBeTruthy();
    });
  });

  /**
   * Trouvé le 18/09/2026 en confrontant l'inventaire des codes d'erreur à
   * cet écran : `partager` avalait toute réponse en échec de `fetch(url)`
   * sous « ce navigateur ne sait pas partager de fichier » — vrai la moitié
   * du temps, faux quand c'est le serveur qui refuse (une génération sortie
   * de la mémoire, par exemple, `generation_introuvable`). Le message ne
   * disait ni ce qui s'était passé ni quoi faire d'autre que changer de
   * navigateur, ce qui n'aurait rien réparé.
   *
   * Depuis le 27/09/2026, la récupération du GPX se fait au chargement, pas
   * au clic : ces pannes s'affichent donc dès l'affichage du bouton, sans
   * action du cycliste.
   */
  describe("le partage GPX distingue une panne du serveur d'un navigateur qui ne partage pas", () => {
    it("affiche le message de l'API plutôt que « ce navigateur ne sait pas partager »", async () => {
      const reponsePanne = panne(
        "generation_introuvable",
        "cette génération n'est plus en mémoire — relancer la recherche",
        404,
      );
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => ({
          ok: false,
          status: 404,
          text: async () => JSON.stringify(reponsePanne.charge),
        })),
      );
      const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
      afficher(1);

      await waitFor(() =>
        expect(
          screen.getByText(/cette génération n'est plus en mémoire — relancer la recherche/),
        ).toBeTruthy(),
      );
      expect(screen.getByText("L'envoi vers votre compteur a échoué.")).toBeTruthy();
      // Le code de la panne reste visible, comme sur tous les autres écrans d'échec.
      expect(screen.getByText(/Code de la panne : generation_introuvable/)).toBeTruthy();
      // Et surtout : plus jamais le mauvais diagnostic pour cette panne-là.
      expect(alerte).not.toHaveBeenCalled();
    });

    it("nomme le serveur injoignable plutôt que de laisser fuir le texte de l'exception réseau", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => {
          throw new TypeError("Failed to fetch");
        }),
      );
      const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
      afficher(1);

      await waitFor(() =>
        expect(
          screen.getByText(/le serveur d'où rouler ne répond pas — vérifiez qu'il tourne/),
        ).toBeTruthy(),
      );
      // Jamais le texte brut de l'exception du navigateur.
      expect(screen.queryByText(/Failed to fetch/)).toBeNull();
      expect(alerte).not.toHaveBeenCalled();
    });
  });

  it("ne promet rien quand la proposition ne porte pas de trace", () => {
    const reponse = sortie({ propositions: 2 });
    reponse.donnees.propositions[0].gpx = null;
    const rendu = render(
      <PropositionDetail
        reponse={reponse}
        numero={1}
        seance={SEANCE.donnees}
        surRetour={() => undefined}
      />,
    );
    expect(screen.queryByText("Télécharger le GPX")).toBeNull();
    expect(screen.getByText(/Aucun GPX/)).toBeTruthy();
    rendu.unmount();
  });
});

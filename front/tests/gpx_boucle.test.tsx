/** Le partage GPX sur l'écran des boucles libres — calqué sur
 * `tests/gpx_proposition.test.tsx`, qui couvre le même geste sur la
 * proposition d'une sortie.
 *
 * Réutilise `BoutonsGpx` (`../src/composants/BoutonsGpx.tsx`, lui-même
 * construit sur `partager()`) : ce fichier vérifie que `Boucles.tsx` le
 * branche correctement — bouton en plus, lien de téléchargement inchangé,
 * panne nommée jamais confondue avec « ce navigateur ne sait pas partager »,
 * panne remise à zéro quand on change de candidate, et le garde-fou sur une
 * candidate qui n'est pas la retenue.
 *
 * Depuis la correction du 27/09/2026 (iPhone Safari, `NotAllowedError`), le
 * GPX est récupéré **avant** le clic, dès que `BoutonsGpx` s'affiche : les
 * tests stubbent donc `fetch` avant le rendu (plus au clic), et attendent
 * que le bouton passe de « Préparation du fichier… » à « Envoyer vers mon
 * compteur » avant de cliquer.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Boucles } from "../src/ecrans/Boucles";
import { boucle } from "./fixtures";
import { panne } from "./serveur";

function reponseGpxOk(): Response {
  return {
    ok: true,
    status: 200,
    blob: async () => new Blob(["<gpx />"], { type: "application/gpx+xml" }),
  } as unknown as Response;
}

function reponsePanneServeur(code: string, message: string, statut: number): Response {
  const reponsePanne = panne(code, message, statut);
  return {
    ok: false,
    status: statut,
    text: async () => JSON.stringify(reponsePanne.charge),
  } as unknown as Response;
}

/** Installe `navigator.share`/`canShare` factices pour un test. */
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

describe("le partage GPX d'une boucle libre", () => {
  it("pointe le GPX de la boucle, avec le lien de téléchargement inchangé", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    const lien = screen.getByText("Télécharger le GPX").closest("a")!;
    expect(lien.getAttribute("href")).toBe(reponse.donnees.gpx!.url);
    expect(lien.getAttribute("download")).toBe(reponse.donnees.gpx!.nom);
    expect(lien.getAttribute("class")).toBe("bouton");
    await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
    rendu.unmount();
  });

  it("désactive le bouton d'envoi tant que le fichier n'est pas prêt", async () => {
    let resoudre: (reponse: Response) => void = () => undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (resoudre = r))),
    );
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    const bouton = screen.getByText("Préparation du fichier…").closest("button") as HTMLButtonElement;
    expect(bouton.disabled).toBe(true);

    resoudre(reponseGpxOk());
    await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());
    const boutonPret = screen.getByText("Envoyer vers mon compteur").closest("button") as HTMLButtonElement;
    expect(boutonPret.disabled).toBe(false);

    rendu.unmount();
  });

  it("appelle le partage sans attendre le réseau au clic : le GPX est déjà récupéré", async () => {
    const fetchMock = vi.fn(reponseGpxOk);
    vi.stubGlobal("fetch", fetchMock);
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    // Le fichier est récupéré dès l'affichage du bouton, pas au clic.
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

    // Aucun appel réseau supplémentaire au clic.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(share).toHaveBeenCalledTimes(1);
    expect(fichiersPartages).toHaveLength(1);
    expect(fichiersPartages[0].name).toBe(reponse.donnees.gpx!.nom);
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    rendu.unmount();
  });

  it("essaie application/octet-stream quand canShare refuse application/gpx+xml", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
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
    expect(fichierPartage!.name).toBe(reponse.donnees.gpx!.nom);

    rendu.unmount();
  });

  it("laisse le lien de téléchargement quand aucun type MIME n'est accepté", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    await waitFor(() => expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy());

    const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    // Pas de `navigator.share` : le navigateur ne sait pas partager du tout.

    const utilisateur = userEvent.setup();
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

    expect(alerte).toHaveBeenCalled();
    expect(alerte.mock.calls[0][0]).toMatch(/Ce navigateur ne sait pas partager de fichier/);
    // Le lien natif reste là, inchangé, pour ce cas-là.
    expect(screen.getByText("Télécharger le GPX")).toBeTruthy();

    rendu.unmount();
  });

  it("n'affiche rien quand le cycliste ferme la feuille de partage (AbortError)", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
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

    // Laisse le temps au `.catch()` de la promesse de partage de s'exécuter.
    await new Promise((resoudre) => setTimeout(resoudre, 0));

    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();
    expect(alerte).not.toHaveBeenCalled();
    rendu.unmount();
  });

  it("affiche un message distinct — pas l'alerte — quand le partage est refusé (NotAllowedError)", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
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
    expect(screen.getByText("Télécharger le GPX")).toBeTruthy();

    rendu.unmount();
  });

  it("affiche le message nommé de l'API, jamais « ce navigateur ne sait pas partager » (panne au chargement)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        reponsePanneServeur(
          "generation_introuvable",
          "cette génération n'est plus en mémoire — relancer la recherche",
          404,
        ),
      ),
    );
    const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const reponse = boucle();
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    await waitFor(() =>
      expect(
        screen.getByText(/cette génération n'est plus en mémoire — relancer la recherche/),
      ).toBeTruthy(),
    );
    // L'encart d'échec porte `role="alert"` : un lecteur d'écran l'annonce
    // sans que le cycliste ait à le chercher.
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("L'envoi vers votre compteur a échoué.")).toBeTruthy();
    expect(screen.getByText(/Code de la panne : generation_introuvable/)).toBeTruthy();
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
    const reponse = boucle();
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    await waitFor(() =>
      expect(
        screen.getByText(/le serveur d'où rouler ne répond pas — vérifiez qu'il tourne/),
      ).toBeTruthy(),
    );
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    expect(alerte).not.toHaveBeenCalled();
  });

  it("remet la panne à zéro quand on change de candidate, plutôt que de la laisser réapparaître toute seule", async () => {
    // `BoutonsGpx` disparaît complètement pour une candidate qui n'est pas
    // la retenue (voir plus bas) : y revenir le remonte, ce qui relance la
    // récupération du GPX. Le premier essai échoue tout de suite ; le
    // second (au retour sur la retenue) reste délibérément en suspens dans
    // ce test, pour vérifier que la panne est bien effacée **au clic**,
    // sans attendre l'issue d'un nouvel essai encore en cours.
    let essais = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        essais += 1;
        if (essais === 1) return Promise.reject(new TypeError("Failed to fetch"));
        return new Promise<Response>(() => undefined);
      }),
    );
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const reponse = boucle();
    reponse.donnees.candidates.push({
      ...reponse.donnees.candidates[0],
      numero: 2,
      retenue: false,
    });
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByText("L'envoi vers votre compteur a échoué.")).toBeTruthy(),
    );

    const utilisateur = userEvent.setup();
    // On regarde la candidate 2 (pas de bouton d'envoi pour elle).
    await utilisateur.click(screen.getByRole("button", { name: /Boucle 2/ }));
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    // … puis on revient sur la retenue : l'ancienne panne ne réapparaît pas
    // toute seule, sans nouvel essai.
    await utilisateur.click(screen.getByRole("button", { name: /Boucle 1/ }));
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    rendu.unmount();
  });

  it("ne propose ni bouton d'envoi ni GPX quand une autre candidate que la retenue est sélectionnée", async () => {
    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const reponse = boucle();
    // Une seconde candidate, non retenue, pour sélectionner autre chose que
    // celle dont le GPX est prêt.
    reponse.donnees.candidates.push({
      ...reponse.donnees.candidates[0],
      numero: 2,
      retenue: false,
    });
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    const utilisateur = userEvent.setup();
    await utilisateur.click(screen.getByRole("button", { name: /Boucle 2/ }));

    expect(screen.queryByText("Envoyer vers mon compteur")).toBeNull();
    expect(screen.queryByText("Préparation du fichier…")).toBeNull();
    expect(screen.queryByText("Télécharger le GPX")).toBeNull();
    expect(
      screen.getByText("Le GPX prêt est celui de la boucle retenue, pas de celle-ci."),
    ).toBeTruthy();

    rendu.unmount();
  });
});

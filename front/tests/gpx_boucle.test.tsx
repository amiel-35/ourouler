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

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (navigator as { canShare?: unknown }).canShare;
  delete (navigator as { share?: unknown }).share;
});

describe("le partage GPX d'une boucle libre", () => {
  it("pointe le GPX de la boucle, avec le lien de téléchargement inchangé", () => {
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    const lien = screen.getByText("Télécharger le GPX").closest("a")!;
    expect(lien.getAttribute("href")).toBe(reponse.donnees.gpx!.url);
    expect(lien.getAttribute("download")).toBe(reponse.donnees.gpx!.nom);
    expect(lien.getAttribute("class")).toBe("bouton");
    expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy();
    rendu.unmount();
  });

  it("simule un partage réussi avec le fichier GPX", async () => {
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    let fichiersPartages: File[] = [];
    const canShare = vi.fn(() => true);
    const share = vi.fn(async (donnees: { files: File[] }) => {
      fichiersPartages = donnees.files;
    });
    Object.defineProperty(navigator, "canShare", { value: canShare, configurable: true });
    Object.defineProperty(navigator, "share", { value: share, configurable: true });

    const utilisateur = userEvent.setup();
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

    await waitFor(() => expect(fichiersPartages).toHaveLength(1));
    expect(fichiersPartages[0].name).toBe(reponse.donnees.gpx!.nom);
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    rendu.unmount();
  });

  it("laisse le lien de téléchargement quand le navigateur ne sait pas partager de fichier", async () => {
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    vi.stubGlobal("fetch", vi.fn(reponseGpxOk));
    const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);

    const utilisateur = userEvent.setup();
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

    await waitFor(() => expect(alerte).toHaveBeenCalled());
    expect(alerte.mock.calls[0][0]).toMatch(/Ce navigateur ne sait pas partager de fichier/);
    // Le lien natif reste là, inchangé, pour ce cas-là.
    expect(screen.getByText("Télécharger le GPX")).toBeTruthy();

    rendu.unmount();
  });

  it("affiche le message nommé de l'API, jamais « ce navigateur ne sait pas partager »", async () => {
    const reponse = boucle();
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);

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

    const utilisateur = userEvent.setup();
    const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

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
    const reponse = boucle();
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const utilisateur = userEvent.setup();
    const alerte = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));

    await waitFor(() =>
      expect(
        screen.getByText(/le serveur d'où rouler ne répond pas — vérifiez qu'il tourne/),
      ).toBeTruthy(),
    );
    expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    expect(alerte).not.toHaveBeenCalled();
  });

  it("remet la panne à zéro quand on change de candidate, plutôt que de la laisser réapparaître", async () => {
    const reponse = boucle();
    reponse.donnees.candidates.push({
      ...reponse.donnees.candidates[0],
      numero: 2,
      retenue: false,
    });
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    vi.spyOn(window, "alert").mockImplementation(() => undefined);
    const utilisateur = userEvent.setup();

    // La candidate retenue échoue en tentant l'envoi.
    await utilisateur.click(screen.getByText("Envoyer vers mon compteur"));
    await waitFor(() =>
      expect(screen.getByText("L'envoi vers votre compteur a échoué.")).toBeTruthy(),
    );

    // On regarde la candidate 2 (pas de GPX pour elle)…
    await utilisateur.click(screen.getByRole("button", { name: /Boucle 2/ }));
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    // … puis on revient sur la retenue : l'ancienne panne ne doit pas
    // réapparaître toute seule.
    await utilisateur.click(screen.getByRole("button", { name: /Boucle 1/ }));
    expect(screen.queryByText("L'envoi vers votre compteur a échoué.")).toBeNull();

    rendu.unmount();
  });

  it("ne propose ni bouton d'envoi ni GPX quand une autre candidate que la retenue est sélectionnée", async () => {
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
    expect(screen.queryByText("Télécharger le GPX")).toBeNull();
    expect(
      screen.getByText("Le GPX prêt est celui de la boucle retenue, pas de celle-ci."),
    ).toBeTruthy();

    rendu.unmount();
  });
});

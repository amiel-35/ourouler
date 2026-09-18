/** Q40 (g) : chaque proposition emporte **sa** trace, pas celle du classement.
 *
 * Le défaut corrigé se voyait dehors et pas avant : choisir « la plus
 * sèche », appuyer sur « Envoyer vers mon compteur », et partir avec « la
 * plus calme ». L'écran doit donc pointer l'adresse de la proposition
 * affichée, et d'aucune autre.
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

describe("le GPX d'une proposition", () => {
  it("pointe la trace de la proposition affichée, quelle qu'elle soit", () => {
    for (const numero of [1, 2, 3]) {
      const { reponse, rendu } = afficher(numero);
      const attendue = reponse.donnees.propositions.find((p) => p.numero === numero)!.gpx!;
      const lien = screen.getByText("Télécharger le GPX").closest("a")!;
      expect(lien.getAttribute("href")).toBe(attendue.url);
      expect(lien.getAttribute("download")).toBe(attendue.nom);
      rendu.unmount();
    }
  });

  it("propose le bouton d'envoi sur une proposition qui n'est pas la retenue", () => {
    const { rendu } = afficher(3);
    expect(screen.getByText("Envoyer vers mon compteur")).toBeTruthy();
    rendu.unmount();
  });

  /**
   * Trouvé le 18/09/2026 en confrontant l'inventaire des codes d'erreur à
   * cet écran : `partager` avalait toute réponse en échec de `fetch(url)`
   * sous « ce navigateur ne sait pas partager de fichier » — vrai la moitié
   * du temps, faux quand c'est le serveur qui refuse (une génération sortie
   * de la mémoire, par exemple, `generation_introuvable`). Le message ne
   * disait ni ce qui s'était passé ni quoi faire d'autre que changer de
   * navigateur, ce qui n'aurait rien réparé.
   */
  describe("le partage GPX distingue une panne du serveur d'un navigateur qui ne partage pas", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("affiche le message de l'API plutôt que « ce navigateur ne sait pas partager »", async () => {
      afficher(1);
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
      expect(screen.getByText("L'envoi vers votre compteur a échoué.")).toBeTruthy();
      // Le code de la panne reste visible, comme sur tous les autres écrans d'échec.
      expect(screen.getByText(/Code de la panne : generation_introuvable/)).toBeTruthy();
      // Et surtout : plus jamais le mauvais diagnostic pour cette panne-là.
      expect(alerte).not.toHaveBeenCalled();
      alerte.mockRestore();
    });

    it("nomme le serveur injoignable plutôt que de laisser fuir le texte de l'exception réseau", async () => {
      afficher(1);
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
      // Jamais le texte brut de l'exception du navigateur.
      expect(screen.queryByText(/Failed to fetch/)).toBeNull();
      expect(alerte).not.toHaveBeenCalled();
      alerte.mockRestore();
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

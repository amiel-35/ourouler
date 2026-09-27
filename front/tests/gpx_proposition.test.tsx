/** Q40 (g) : chaque proposition emporte **sa** trace, pas celle du classement.
 *
 * Le défaut corrigé se voyait dehors et pas avant : choisir « la plus
 * sèche », télécharger, et partir avec le GPX de « la plus calme ». L'écran
 * doit donc pointer l'adresse de la proposition affichée, et d'aucune autre.
 *
 * Le bouton « Envoyer vers mon compteur » a été retiré le 27/09/2026 : sur
 * iPhone, la feuille de partage d'iOS ne propose pas Garmin Connect pour ce
 * fichier, seul « Télécharger le GPX » restait utile.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PropositionDetail } from "../src/ecrans/Proposition";
import { SEANCE, sortie } from "./fixtures";

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
  it("pointe la trace de la proposition affichée, quelle qu'elle soit, sans bouton d'envoi", () => {
    for (const numero of [1, 2, 3]) {
      const { reponse, rendu } = afficher(numero);
      const attendue = reponse.donnees.propositions.find((p) => p.numero === numero)!.gpx!;
      const lien = screen.getByText("Télécharger le GPX").closest("a")!;
      expect(lien.getAttribute("href")).toBe(attendue.url);
      expect(lien.getAttribute("download")).toBe(attendue.nom);
      expect(lien.getAttribute("class")).toBe("bouton fantome");
      expect(screen.queryByText("Envoyer vers mon compteur")).toBeNull();
      rendu.unmount();
    }
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

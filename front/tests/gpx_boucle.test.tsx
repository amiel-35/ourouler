/** Le téléchargement du GPX sur l'écran des boucles libres — calqué sur
 * `tests/gpx_proposition.test.tsx`, qui couvre le même geste sur la
 * proposition d'une sortie.
 *
 * Le bouton « Envoyer vers mon compteur » a été retiré le 27/09/2026 : sur
 * iPhone, la feuille de partage d'iOS ne propose pas Garmin Connect pour ce
 * fichier, seul « Télécharger le GPX » restait utile. Ce fichier vérifie que
 * `Boucles.tsx` garde le lien de téléchargement exact, sans bouton d'envoi,
 * et le garde-fou sur une candidate qui n'est pas la retenue.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Boucles } from "../src/ecrans/Boucles";
import { boucle } from "./fixtures";

describe("le téléchargement du GPX d'une boucle libre", () => {
  it("pointe le GPX de la boucle, sans bouton d'envoi", () => {
    const reponse = boucle();
    const rendu = render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    const lien = screen.getByText("Télécharger le GPX").closest("a")!;
    expect(lien.getAttribute("href")).toBe(reponse.donnees.gpx!.url);
    expect(lien.getAttribute("download")).toBe(reponse.donnees.gpx!.nom);
    expect(lien.getAttribute("class")).toBe("bouton");
    expect(screen.queryByText("Envoyer vers mon compteur")).toBeNull();
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

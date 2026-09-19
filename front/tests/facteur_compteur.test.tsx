/** Le facteur compteur, éditable par vélo, défaut serveur en indication.
 *
 * Le serveur savait déjà écrire `velos[].facteur_compteur` (`LISTES_MODIFIABLES`,
 * bornes 0,4 – 1,2 dans `config.py`) et `GET /profil/zones` acceptait déjà un
 * nom de vélo (`velo`) : aucune route n'a dû bouger pour ce lot. Ce que ces
 * tests protègent côté front :
 *
 * - la saisie d'une valeur part bien dans `velos[].facteur_compteur`, en
 *   nombre, pas en texte ;
 * - un champ vide envoie `null` — jamais une valeur inventée — et c'est le
 *   défaut serveur qui s'applique alors ;
 * - le geste « Revenir au défaut » écrit `null`, même après une saisie ;
 * - un champ vide affiche le défaut supposé, avec la mention « supposé » que
 *   `EcranFtp.tsx` emploie déjà — pas une seconde formulation ;
 * - une valeur hors bornes affiche l'erreur du serveur telle quelle, jamais
 *   une vérification réinventée côté front.
 */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur, panne } from "./serveur";
import { PROFIL, zones } from "./fixtures";

const ZONES = zones().donnees;

function rendre(profil = PROFIL.donnees, table: ConstructorParameters<typeof Serveur>[0] = {}) {
  const serveur = new Serveur({
    "/api/v1/profil/zones/apercu": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    "/api/v1/profil": { charge: { proprietaire: "essai", donnees: profil } },
    ...table,
  });
  serveur.installer();
  render(
    <Reglages
      profil={profil}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surRefaireInstallation={() => undefined}
      surDeconnexion={() => undefined}
    />,
  );
  return { serveur };
}

async function ouvrirVelos() {
  await userEvent.click(screen.getByRole("button", { name: "Ajouter ou retirer" }));
}

describe("le facteur compteur — champ vide, défaut affiché", () => {
  it("affiche le défaut supposé, avec la mention déjà employée par EcranFtp", async () => {
    // « Le vert » (fixture) a `facteur_compteur: null` : c'est exactement le
    // cas du mainteneur, sur ses deux vélos.
    rendre();
    await ouvrirVelos();

    const champ = (await screen.findByLabelText("Facteur compteur")) as HTMLInputElement;
    expect(champ.value).toBe("");
    // La valeur calculée du défaut vient de `GET /profil/zones?velo=Le vert`
    // (fixture `zones()` : `facteur_compteur: 0.833`) et s'affiche en
    // indication dans le champ.
    await waitFor(() => expect(champ.placeholder).toBe("0,833"));
    expect(
      screen.getByText("supposé — il n'a pas été mesuré sur vos sorties", { exact: false }),
    ).toBeTruthy();
    // Sans saisie, il n'y a rien dont revenir : le geste explicite ne
    // s'affiche pas.
    expect(screen.queryByRole("button", { name: "Revenir au défaut" })).toBeNull();
  });
});

describe("le facteur compteur — saisie et enregistrement", () => {
  it("envoie la valeur saisie, en nombre, dans velos[].facteur_compteur", async () => {
    const { serveur } = rendre();
    await ouvrirVelos();
    const champ = await screen.findByLabelText("Facteur compteur");
    await userEvent.type(champ, "0,79");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));

    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { velos?: Array<Record<string, unknown>> };
    expect(corps.velos?.[0].facteur_compteur).toBe(0.79);
    expect(typeof corps.velos?.[0].facteur_compteur).toBe("number");
  });

  it("propose « Revenir au défaut » une fois une valeur saisie, et il écrit null", async () => {
    const { serveur } = rendre();
    await ouvrirVelos();
    const champ = (await screen.findByLabelText("Facteur compteur")) as HTMLInputElement;
    await userEvent.type(champ, "0,79");
    expect(champ.value).toBe("0,79");

    await userEvent.click(screen.getByRole("button", { name: "Revenir au défaut" }));
    expect(champ.value).toBe("");

    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { velos?: Array<Record<string, unknown>> };
    expect(corps.velos?.[0].facteur_compteur).toBeNull();
  });

  it("envoie null quand le champ n'a jamais été touché", async () => {
    const { serveur } = rendre();
    await ouvrirVelos();
    await screen.findByLabelText("Facteur compteur");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
    const patch = serveur.requetes.find((r) => r.methode === "PATCH")!;
    const corps = patch.corps as { velos?: Array<Record<string, unknown>> };
    expect(corps.velos?.[0].facteur_compteur).toBeNull();
  });
});

describe("le facteur compteur — erreur serveur hors bornes", () => {
  it("affiche l'erreur du serveur telle quelle, sans validation réinventée", async () => {
    const { serveur } = rendre(PROFIL.donnees, {
      "/api/v1/profil": (requete) => {
        if (requete.methode === "PATCH") {
          return panne(
            "profil_invalide",
            "velos[0].facteur_compteur = 1.8 hors de [0.4, 1.2]",
            422,
          );
        }
        return { charge: PROFIL };
      },
    });
    await ouvrirVelos();
    const champ = await screen.findByLabelText("Facteur compteur");
    await userEvent.type(champ, "1,8");
    await userEvent.click(screen.getByRole("button", { name: "Enregistrer les vélos" }));

    expect(
      await screen.findByText("velos[0].facteur_compteur = 1.8 hors de [0.4, 1.2]"),
    ).toBeTruthy();
    await waitFor(() =>
      expect(serveur.requetes.filter((r) => r.methode === "PATCH").length).toBe(1),
    );
  });
});

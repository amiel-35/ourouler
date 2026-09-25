/** Le formulaire d'adresse : ce que la décision Q34 exige de l'écran.
 *
 * Quatre champs obligatoires, un point à confirmer sur la carte, et une
 * géolocalisation qui n'est jamais le seul chemin. Aucun réseau : le serveur
 * factice répond, et une route non prévue fait échouer le test.
 *
 * Aucune adresse réelle : les communes sont inventées (« Vallombreuse »,
 * « Hautbocage ») et les coordonnées tournent autour du point zéro du golfe de
 * Guinée, comme dans les fixtures Python.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  FormulaireAdresse,
  champsManquants,
  etatGeolocalisation,
  ouEst,
  phraseEchecPosition,
  requete,
} from "../src/composants/FormulaireAdresse";
import type { Candidat } from "../src/api/types";
import { Serveur } from "./serveur";

function candidat(
  label: string,
  commune: string | null,
  code_postal: string | null,
  latitude = 0.123456,
): Candidat {
  return { label, latitude, longitude: 0.234567, score: 0.98, source: "ban", commune, code_postal };
}

function enveloppe(candidats: Candidat[], ambigu = false) {
  return {
    charge: {
      proprietaire: "cycliste-test",
      donnees: { adresse: "…", candidats, ambigu, motif_ambiguite: null },
      // `{code, message}` depuis la correction du troisième bloquant de la
      // relecture F2 : un avertissement porte un code, le front ne lit plus
      // une phrase française pour décider d'un état.
      avertissements:
        candidats.length === 0
          ? [{ code: "adresse_introuvable", message: "aucune adresse trouvée pour « … »" }]
          : [],
      budget: null,
      duree_ms: 12,
    },
  };
}

async function remplir(utilisateur: ReturnType<typeof userEvent.setup>) {
  await utilisateur.type(screen.getByLabelText("Numéro"), "7");
  await utilisateur.type(screen.getByLabelText("Voie"), "Rue du If");
  await utilisateur.type(screen.getByLabelText("Code postal"), "44999");
  await utilisateur.type(screen.getByLabelText("Commune"), "Vallombreuse");
}

describe("les fonctions pures de la décision", () => {
  it("assemble la requête à partir des quatre champs, dans l'ordre que la BAN attend", () => {
    expect(
      requete({ numero: "7", voie: "Rue du If", codePostal: "44999", commune: "Vallombreuse" }),
    ).toBe("7 Rue du If 44999 Vallombreuse");
  });

  it("nomme les champs vides, sauf le numéro qui est facultatif", () => {
    expect(
      champsManquants({ numero: "7", voie: "", codePostal: " ", commune: "Vallombreuse" }),
    ).toEqual(["voie", "codePostal"]);
    // Une place ou un lieu-dit n'a pas de numéro : il ne compte pas parmi
    // les champs manquants, même vide.
    expect(
      champsManquants({ numero: "", voie: "Place de la Mairie", codePostal: "44999", commune: "Vallombreuse" }),
    ).toEqual([]);
  });

  it("montre la commune d'un candidat, et le dit quand elle manque", () => {
    expect(ouEst(candidat("A", "Vallombreuse", "44999"))).toBe("Vallombreuse (44999)");
    expect(ouEst(candidat("A", "Vallombreuse", null))).toBe("Vallombreuse");
    expect(ouEst(candidat("A", null, null))).toBe("commune inconnue");
  });

  it("traite le refus d'autorisation comme un choix, pas comme une panne", () => {
    const refus = phraseEchecPosition(1);
    expect(refus).toMatch(/votre choix/);
    expect(refus).not.toMatch(/erreur|échec|panne/i);
    expect(refus).toMatch(/champs/);
    // Les deux autres codes sont des échecs, et renvoient aussi au formulaire.
    expect(phraseEchecPosition(3)).toMatch(/champs/);
    expect(phraseEchecPosition(2)).toMatch(/champs/);
  });
});

describe("la géolocalisation n'est jamais le seul chemin", () => {
  it("ne propose pas la position hors connexion sécurisée, et dit pourquoi", () => {
    const sauvegarde = Object.getOwnPropertyDescriptor(window, "isSecureContext");
    // Le navigateur *sait* géolocaliser : c'est bien la connexion qui bloque.
    Object.defineProperty(navigator, "geolocation", {
      value: { getCurrentPosition: () => {} },
      configurable: true,
    });
    Object.defineProperty(window, "isSecureContext", { value: false, configurable: true });
    try {
      const etat = etatGeolocalisation();
      expect(etat.possible).toBe(false);
      expect(etat.raison).toMatch(/HTTPS/);
    } finally {
      if (sauvegarde) Object.defineProperty(window, "isSecureContext", sauvegarde);
    }
  });

  it("laisse le formulaire entier quand le navigateur refuse la position", async () => {
    const utilisateur = userEvent.setup();
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    Object.defineProperty(navigator, "geolocation", {
      value: {
        getCurrentPosition: (_ok: unknown, ko: (e: { code: number }) => void) => ko({ code: 1 }),
      },
      configurable: true,
    });

    render(<FormulaireAdresse surChoix={() => {}} />);
    await utilisateur.click(screen.getByRole("button", { name: "Utiliser ma position" }));

    expect(await screen.findByText(/votre choix/)).toBeTruthy();
    // Le refus ne ferme rien : les quatre champs sont toujours là.
    for (const nom of ["Numéro", "Voie", "Code postal", "Commune"]) {
      expect(screen.getByLabelText(nom)).toBeTruthy();
    }
  });

  it("montre la position relevée sur la carte, sans lui inventer un nom d'adresse", async () => {
    const utilisateur = userEvent.setup();
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    Object.defineProperty(navigator, "geolocation", {
      value: {
        getCurrentPosition: (ok: (p: unknown) => void) =>
          ok({ coords: { latitude: 0.5, longitude: 0.25, accuracy: 18 } }),
      },
      configurable: true,
    });
    const choisi = vi.fn();

    render(<FormulaireAdresse surChoix={choisi} />);
    await utilisateur.click(screen.getByRole("button", { name: "Utiliser ma position" }));

    expect(await screen.findByText(/géocodage inverse/)).toBeTruthy();
    expect(screen.getByLabelText(/point de départ à confirmer/)).toBeTruthy();
    expect(screen.getByText(/environ 18 m/)).toBeTruthy();
    // Rien n'est retenu tant que le point n'est pas confirmé.
    expect(choisi).not.toHaveBeenCalled();

    await utilisateur.click(screen.getByRole("button", { name: "C'est bien là, partir d'ici" }));
    expect(choisi).toHaveBeenCalledWith({
      nom: "Ma position (0.50000, 0.25000)",
      latitude: 0.5,
      longitude: 0.25,
    });
  });

  it("amène le point relevé sous les yeux, au lieu de le poser hors de l'écran", async () => {
    // Le bouton de position est en haut, la carte naît sous les quatre champs :
    // sur un téléphone, rien ne bouge à l'écran et le clic passe pour un échec
    // (constaté par le mainteneur le 20/09/2026). jsdom n'implémente pas
    // `scrollIntoView` — on le pose nous-mêmes pour l'observer.
    const utilisateur = userEvent.setup();
    Object.defineProperty(window, "isSecureContext", { value: true, configurable: true });
    Object.defineProperty(navigator, "geolocation", {
      value: {
        getCurrentPosition: (ok: (p: unknown) => void) =>
          ok({ coords: { latitude: 0.5, longitude: 0.25, accuracy: 18 } }),
      },
      configurable: true,
    });
    const defiler = vi.fn();
    const sauvegarde = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      value: defiler,
      configurable: true,
      writable: true,
    });

    try {
      render(<FormulaireAdresse surChoix={() => {}} />);
      // Rien n'a encore paru : personne n'a fait défiler quoi que ce soit.
      expect(defiler).not.toHaveBeenCalled();

      await utilisateur.click(screen.getByRole("button", { name: "Utiliser ma position" }));
      expect(await screen.findByLabelText(/point de départ à confirmer/)).toBeTruthy();

      await waitFor(() => expect(defiler).toHaveBeenCalled());
      // C'est bien le bloc du point qu'on amène, pas un autre élément.
      const surQui = defiler.mock.instances[0] as HTMLElement;
      expect(surQui.querySelector("[aria-label*='point de départ à confirmer']")).toBeTruthy();
    } finally {
      if (sauvegarde) Object.defineProperty(Element.prototype, "scrollIntoView", sauvegarde);
      else Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });
});

describe("le formulaire à champs obligatoires", () => {
  it("refuse de chercher tant que la commune manque, et ne touche pas au réseau", async () => {
    const utilisateur = userEvent.setup();
    const serveur = new Serveur({});
    serveur.installer();

    render(<FormulaireAdresse surChoix={() => {}} />);
    await utilisateur.type(screen.getByLabelText("Numéro"), "7");
    await utilisateur.type(screen.getByLabelText("Voie"), "Rue du If");
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    expect(await screen.findByText(/sont demandés/)).toBeTruthy();
    expect(serveur.requetes).toEqual([]);
    expect(screen.getByLabelText("Commune").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByLabelText("Numéro").getAttribute("aria-invalid")).toBe("false");
  });

  it("cherche sans numéro — une place ou un lieu-dit n'en a pas", async () => {
    const utilisateur = userEvent.setup();
    const serveur = new Serveur({
      "/api/v1/geocodage": enveloppe([
        candidat("Place de la Mairie 44999 Vallombreuse", "Vallombreuse", "44999"),
      ]),
    });
    serveur.installer();

    render(<FormulaireAdresse surChoix={() => {}} />);
    await utilisateur.type(screen.getByLabelText("Voie"), "Place de la Mairie");
    await utilisateur.type(screen.getByLabelText("Code postal"), "44999");
    await utilisateur.type(screen.getByLabelText("Commune"), "Vallombreuse");
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    await waitFor(() => expect(serveur.vers("/api/v1/geocodage").length).toBe(1));
    expect(screen.getByLabelText("Numéro").hasAttribute("required")).toBe(false);
  });

  it("envoie les quatre champs assemblés au géocodage", async () => {
    const utilisateur = userEvent.setup();
    const serveur = new Serveur({
      "/api/v1/geocodage": enveloppe([
        candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999"),
      ]),
    });
    serveur.installer();

    render(<FormulaireAdresse surChoix={() => {}} />);
    await remplir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    await waitFor(() => expect(serveur.vers("/api/v1/geocodage").length).toBe(1));
    // `URLSearchParams` encode l'espace en « + » : on le rend avant de comparer.
    const envoye = decodeURIComponent(
      serveur.vers("/api/v1/geocodage")[0].chemin.replace(/\+/g, " "),
    );
    expect(envoye).toContain("7 Rue du If 44999 Vallombreuse");
  });

  it("fait confirmer le point sur la carte avant de retenir un candidat unique", async () => {
    const utilisateur = userEvent.setup();
    new Serveur({
      "/api/v1/geocodage": enveloppe([
        candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999"),
      ]),
    }).installer();
    const choisi = vi.fn();

    render(<FormulaireAdresse surChoix={choisi} />);
    await remplir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    expect(await screen.findByLabelText(/point de départ à confirmer/)).toBeTruthy();
    expect(choisi).not.toHaveBeenCalled(); // un seul candidat ne dispense pas du contrôle à l'œil

    await utilisateur.click(screen.getByRole("button", { name: "C'est bien là, partir d'ici" }));
    expect(choisi).toHaveBeenCalledWith({
      nom: "7 Rue du If 44999 Vallombreuse",
      latitude: 0.123456,
      longitude: 0.234567,
    });
  });

  it("distingue les candidats par leur commune, ce que le label seul ne fait pas", async () => {
    const utilisateur = userEvent.setup();
    new Serveur({
      "/api/v1/geocodage": enveloppe(
        [
          candidat("7 Rue du If", "Vallombreuse", "44999", 0.123456),
          candidat("7 Rue du If", "Hautbocage", "62999", 0.876543),
        ],
        true,
      ),
    }).installer();

    render(<FormulaireAdresse surChoix={() => {}} />);
    await remplir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    expect(await screen.findByText(/Vallombreuse \(44999\)/)).toBeTruthy();
    expect(screen.getByText(/Hautbocage \(62999\)/)).toBeTruthy();
  });

  it("revient sur ses pas quand le point affiché n'est pas le bon", async () => {
    const utilisateur = userEvent.setup();
    new Serveur({
      "/api/v1/geocodage": enveloppe([
        candidat("7 Rue du If 44999 Vallombreuse", "Vallombreuse", "44999"),
      ]),
    }).installer();
    const choisi = vi.fn();

    render(<FormulaireAdresse surChoix={choisi} />);
    await remplir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));
    await screen.findByLabelText(/point de départ à confirmer/);
    await utilisateur.click(screen.getByRole("button", { name: "Ce n'est pas là" }));

    await waitFor(() => expect(screen.queryByLabelText(/point de départ à confirmer/)).toBeNull());
    expect(choisi).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Commune")).toBeTruthy();
  });

  it("affiche la phrase de l'API quand aucune adresse n'est trouvée", async () => {
    const utilisateur = userEvent.setup();
    new Serveur({ "/api/v1/geocodage": enveloppe([]) }).installer();

    render(<FormulaireAdresse surChoix={() => {}} />);
    await remplir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Chercher cette adresse" }));

    expect(await screen.findByText(/aucune adresse trouvée/)).toBeTruthy();
  });
});

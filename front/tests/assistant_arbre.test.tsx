/** L'arbre de l'accueil (`docs/journal/ux/parcours_accueil.md`) : T1 à T5, et les
 * quatre chemins qui comptent.
 *
 * Ce que ces tests protègent :
 *
 * - un profil Intervals qui porte une FTP exploitable fait confirmer, puis
 *   saute T2 à T5 en entier — aucun appel d'aperçu ne doit partir ;
 * - choisir Strava ou Garmin propose de déposer l'historique tout de suite
 *   (L9.2, `POST /activites/import`), plutôt que de prétendre que l'import
 *   n'existe pas encore — faux depuis L9.2, constaté le 25/09/2026 ;
 * - « Non » sur T2 continue tel quel, sans zone de dépôt ;
 * - la question de vitesse au compteur envoie la valeur exacte du milieu de
 *   tranche (pas une vitesse « à plat »), croisée avec le terrain choisi ;
 * - la case « Montagne » dégrade la phrase de confiance du récapitulatif ;
 * - « je ne sais pas » sur les deux questions de T4 tombe sur T5, en
 *   silence — aucun écran intermédiaire, aucun échec possible.
 */

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Assistant } from "../src/ecrans/Assistant";
import { Serveur, panne } from "./serveur";
import { PROFIL, apercuFtp, profilIntervals, zones } from "./fixtures";

const ZONES = zones().donnees;

function rendre(table: ConstructorParameters<typeof Serveur>[0]) {
  // **L'ordre compte** (`Serveur.installer` retrouve une route par préfixe,
  // la première qui correspond gagne) : "/api/v1/profil" est un préfixe de
  // toutes les routes plus spécifiques du profil (`/profil/intervals`,
  // `/profil/ftp/apercu`…) — il doit donc rester en dernier, sans quoi il
  // les avale toutes avant qu'elles ne soient jamais atteintes.
  const serveur = new Serveur({
    "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
    ...table,
    "/api/v1/profil": { charge: PROFIL },
  });
  serveur.installer();
  render(
    <Assistant
      profil={PROFIL.donnees}
      zones={ZONES}
      surProfil={() => undefined}
      surZones={() => undefined}
      surFin={() => undefined}
      vers="Aujourd'hui"
      surRetour={() => undefined}
    />,
  );
  return { serveur, utilisateur: userEvent.setup() };
}

/** Bienvenue → identité (déjà remplie par la fixture) → départ, gardé tel quel. */
async function versEntonnoir(utilisateur: ReturnType<typeof userEvent.setup>) {
  await utilisateur.click(screen.getByRole("button", { name: "Commencer" }));
  await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));
  await utilisateur.click(screen.getByRole("button", { name: "Garder ce départ" }));
}

describe("T1 — Intervals confirme une FTP", () => {
  it("va directement au récapitulatif : T2 à T5 sont sautés", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/intervals": { charge: profilIntervals({ ftp_w: 240, masse_kg: 68.5 }) },
    });
    await versEntonnoir(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Oui" }));
    await utilisateur.type(screen.getByLabelText("Votre clé"), "cle-inventee");
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText(/FTP 240 W, poids 68,5 kg/)).toBeTruthy();
    await utilisateur.click(screen.getByRole("button", { name: "Oui" }));

    // Direct au vélo, jamais par l'export, la FTP déclarée ou le vécu.
    expect(await screen.findByText("Avec quoi roulez-vous ?")).toBeTruthy();
    expect(screen.queryByText(/pas encore proposé par ourouler/)).toBeNull();
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(screen.getByText("Estimation confirmée depuis votre profil Intervals.")).toBeTruthy();
    expect(serveur.vers("/api/v1/profil/ftp/apercu")).toEqual([]);
    expect(serveur.vers("/api/v1/profil/ftp/generique")).toEqual([]);

    const patchs = serveur
      .vers("/api/v1/profil")
      .filter((r) => r.methode === "PATCH")
      .map((r) => (r.corps as { cycliste?: Record<string, unknown> }).cycliste)
      .filter((c): c is Record<string, unknown> => c !== undefined);
    expect(patchs).toContainEqual({ ftp_w: 240, masse_kg: 68.5 });
  });
});

describe("T2 — pas de compte Intervals", () => {
  it("« Non » n'affiche aucune zone de dépôt, et continue tel quel", async () => {
    const { utilisateur } = rendre({});
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" }));

    expect(screen.queryByText("Mes sorties passées")).toBeNull();
    expect(screen.queryByRole("button", { name: "Choisir un fichier ou une archive" })).toBeNull();
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));
    expect(await screen.findByRole("heading", { name: "Votre poids" })).toBeTruthy();
  });

  it("choisir Strava propose de déposer l'export tout de suite, ou plus tard", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/activites/import": { charge: { donnees: { nombre: 0, premiere: null, derniere: null } } },
    });
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" }));
    await utilisateur.click(screen.getByRole("button", { name: "Strava" }));

    expect(await screen.findByRole("link", { name: "strava.com" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choisir un fichier ou une archive" })).toBeTruthy();
    expect(screen.queryByText(/pas encore proposé/)).toBeNull();

    // « Plus tard » avance dans l'assistant sans avoir rien déposé.
    await utilisateur.click(screen.getByRole("button", { name: "Plus tard, depuis Déposer" }));
    expect(await screen.findByRole("heading", { name: "Votre poids" })).toBeTruthy();
    expect(serveur.vers("/api/v1/activites/import").filter((r) => r.methode === "POST")).toEqual([]);
  });
});

describe("T4 — le vécu, en choix", () => {
  async function versT4(utilisateur: ReturnType<typeof userEvent.setup>) {
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" })); // T1 → T2
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // T2 → poids
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // poids (déjà rempli) → vélo
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // vélo (déjà rempli) → T3
    await utilisateur.click(screen.getByRole("button", { name: "Je ne sais pas" })); // T3 → T4 vitesse
  }

  it("vitesse + terrain Vallonné : envoie vitesse_kmh et denivele_m_par_km corrects", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/apercu": { charge: apercuFtp(187) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "24 à 26 km/h" }));
    await utilisateur.click(screen.getByRole("button", { name: "Vallonné — 250 à 600 m sur 50 km" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/apercu").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")[0].corps).toEqual({
      vitesse_kmh: 25,
      denivele_m_par_km: 10,
      velo: "Le vert",
    });

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(
      screen.getByText("Estimation à partir de ce que vous nous avez dit de vos sorties."),
    ).toBeTruthy();
  });

  it("terrain Montagne : dégrade la phrase de confiance du récapitulatif", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/apercu": { charge: apercuFtp(203) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Plus de 30 km/h" }));
    await utilisateur.click(screen.getByRole("button", { name: "Montagne — plus de 1000 m sur 50 km" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/apercu").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")[0].corps).toEqual({
      vitesse_kmh: 31,
      denivele_m_par_km: 30,
      velo: "Le vert",
    });

    expect(
      await screen.findByText(
        "Estimation à partir de ce que vous nous avez dit — en montagne, cette estimation est moins fiable qu'ailleurs.",
      ),
    ).toBeTruthy();
  });

  it("« je ne sais pas trop » sur la vitesse tombe directement sur T5, sans écran de terrain", async () => {
    const { serveur, utilisateur } = rendre({
      "/api/v1/profil/ftp/generique": { charge: apercuFtp(165) },
    });
    await versT4(utilisateur);

    await utilisateur.click(screen.getByRole("button", { name: "Je ne sais pas trop" }));

    expect(await screen.findByText("Tout est en place")).toBeTruthy();
    expect(screen.queryByText("Et le terrain ?")).toBeNull();
    await waitFor(() => expect(serveur.vers("/api/v1/profil/ftp/generique").length).toBe(1));
    expect(serveur.vers("/api/v1/profil/ftp/apercu")).toEqual([]);
    expect(
      screen.getByText("Estimation générique, à partir de votre poids et de votre vélo seuls."),
    ).toBeTruthy();
  });
});

describe("un profil invalide arrive lisible à l'écran", () => {
  it("affiche la phrase de l'API telle quelle — plus de jargon technique brut", async () => {
    // Constaté le 25/09/2026 : « [cycliste] masse_kg = 7075.0 hors de
    // [20, 300] » s'affichait tel quel. L'API traduit désormais ce message
    // (`api/erreurs.message_profil_invalide`) ; le front n'a rien à faire
    // de plus que l'afficher, ce que ce test verrouille.
    // `rendre()` réécrit toujours "/api/v1/profil" en dernier (voir son
    // commentaire) : impossible d'y distinguer GET et PATCH par ce biais.
    // On construit donc le serveur factice à la main, comme pour le poids du
    // vélo plus bas.
    const serveur = new Serveur({
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
      "/api/v1/profil": (requete: { methode: string; corps: unknown }) => {
        const masse = (requete.corps as { cycliste?: { masse_kg?: number } } | null)?.cycliste
          ?.masse_kg;
        // Seul le `PATCH` qui porte le poids fautif échoue — l'identité et le
        // départ, plus tôt dans `versEntonnoir`, doivent s'enregistrer
        // normalement pour atteindre l'étape « poids ».
        if (requete.methode === "PATCH" && typeof masse === "number" && masse > 300) {
          return panne("profil_invalide", "Votre poids doit être entre 20 et 300 kg.", 422);
        }
        return { charge: PROFIL };
      },
    });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(
      <Assistant
        profil={PROFIL.donnees}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surFin={() => undefined}
        vers="Aujourd'hui"
        surRetour={() => undefined}
      />,
    );
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" })); // T1 → T2
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // T2 → poids

    const champ = screen.getByLabelText("Votre poids");
    fireEvent.change(champ, { target: { value: "7075" } });
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));

    expect(await screen.findByText("Votre poids doit être entre 20 et 300 kg.")).toBeTruthy();
    expect(screen.queryByText(/hors de/)).toBeNull();
  });
});

describe("l'étape vélo — pneu, poids par défaut, et les champs préremplis", () => {
  async function versVelo(utilisateur: ReturnType<typeof userEvent.setup>) {
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" })); // T1 → T2
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // T2 → poids
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // poids (déjà rempli) → vélo
  }

  it("propose le pneu, facultatif, et l'envoie avec la clé du serveur", async () => {
    const { serveur, utilisateur } = rendre({});
    await versVelo(utilisateur);

    const pneu = screen.getByLabelText("Pneus") as HTMLSelectElement;
    expect(pneu.value).toBe(""); // « Je ne sais pas » par défaut
    expect(screen.getByRole("option", { name: "Je ne sais pas" })).toBeTruthy();

    await utilisateur.selectOptions(pneu, "course_quatre_saisons");
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));

    await waitFor(() => expect(serveur.vers("/api/v1/profil").length).toBeGreaterThan(0));
    const patch = serveur
      .vers("/api/v1/profil")
      .find((r) => r.methode === "PATCH" && (r.corps as { velos?: unknown }).velos);
    const velos = (patch!.corps as { velos: Array<Record<string, unknown>> }).velos;
    expect(velos[0].pneu).toBe("course_quatre_saisons");
  });

  it("le poids du vélo reste vide sans valeur réelle — jamais un chiffre inventé — et l'envoie null", async () => {
    const profilSansPoidsVelo = {
      ...PROFIL,
      donnees: { ...PROFIL.donnees, velos: [{ ...PROFIL.donnees.velos[0], masse_kg: null as unknown as number }] },
    };
    const serveur = new Serveur({
      "/api/v1/profil/zones": { charge: { proprietaire: "essai", donnees: ZONES } },
      "/api/v1/profil": { charge: profilSansPoidsVelo },
    });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(
      <Assistant
        profil={profilSansPoidsVelo.donnees}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surFin={() => undefined}
        vers="Aujourd'hui"
        surRetour={() => undefined}
      />,
    );
    await versVelo(utilisateur);

    const champ = screen.getByLabelText("Poids du vélo") as HTMLInputElement;
    expect(champ.value).toBe("");
    expect(champ.placeholder).toBe("9"); // MASSE_VELO_DEFAUT_KG, la même que le texte d'aide
    expect(screen.getByText(/on suppose 9 kg/)).toBeTruthy();

    await utilisateur.click(screen.getByRole("button", { name: "Continuer" }));
    await waitFor(() => expect(serveur.vers("/api/v1/profil").length).toBeGreaterThan(0));
    const patch = serveur
      .vers("/api/v1/profil")
      .find((r) => r.methode === "PATCH" && (r.corps as { velos?: unknown }).velos);
    const velos = (patch!.corps as { velos: Array<Record<string, unknown>> }).velos;
    expect(velos[0].masse_kg).toBeNull();
  });

  it("un champ préreempli se sélectionne au focus : retaper remplace, n'ajoute pas", async () => {
    const { utilisateur } = rendre({});
    await versEntonnoir(utilisateur);
    await utilisateur.click(screen.getByRole("button", { name: "Non, ou je ne sais pas" })); // T1 → T2
    await utilisateur.click(screen.getByRole("button", { name: "Continuer" })); // T2 → poids

    // La fixture porte déjà 63.4 kg — un défaut serveur ou une vraie réponse,
    // le front ne peut pas savoir laquelle, d'où la sélection au focus
    // (constaté le 25/09/2026 : taper après un tel champ donnait « 63.475 »).
    const champ = screen.getByLabelText("Votre poids") as HTMLInputElement;
    expect(champ.value).toBe("63.4");
    // `userEvent.click` simule un clic complet dont jsdom ne rejoue pas la
    // mécanique de sélection d'un vrai navigateur ; `fireEvent.focus` pose le
    // focus tout aussi réellement (l'`onFocus` du composant s'exécute), sans
    // dépendre de cette mécanique absente pour vérifier `select()`.
    fireEvent.focus(champ);
    expect(champ.selectionStart).toBe(0);
    expect(champ.selectionEnd).toBe(champ.value.length);
    await utilisateur.type(champ, "75");
    expect(champ.value).toBe("75");
  });
});

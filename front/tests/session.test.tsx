/** Entrer, revenir, sortir — lot L7.2-D.
 *
 * Ce que ces tests protègent, par l'effet plutôt que par la forme :
 *
 * - `/entrer?jeton=…` retire le jeton de la barre d'adresse dès qu'il est
 *   lu — il n'a rien à faire dans l'historique ni dans un `Referer` ;
 * - un jeton valable montre l'adresse invitée et demande un mot de passe ;
 *   un jeton refusé ne montre **aucun** formulaire ;
 * - `/connexion` ouvre l'écran de connexion directement, sans passer par
 *   l'application des quatre onglets ;
 * - se déconnecter appelle `POST /sortir` puis ramène à l'écran de connexion.
 *
 * Le cas « un 401 session_absente amène l'écran de connexion, et n'y
 * reboucle pas » vit dans `tests/echecs.test.tsx`, à côté des autres écrans
 * d'échec qu'il remplace.
 */

import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Connexion } from "../src/ecrans/Connexion";
import { Entrer } from "../src/ecrans/Entrer";
import { Reglages } from "../src/ecrans/Reglages";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, zones } from "./fixtures";

const ZONES = zones().donnees;

// Plusieurs tests posent `window.location` sur `/entrer` ou `/connexion` :
// jsdom garde cet état d'un test à l'autre dans le même fichier, donc on le
// remet à la racine après chacun.
afterEach(() => {
  window.history.pushState({}, "", "/");
});

describe("Entrer — activation d'une invitation", () => {
  it("jeton valable : montre l'adresse invitée et demande un mot de passe", async () => {
    const serveur = new Serveur({
      "/api/v1/invitation": {
        charge: {
          donnees: { email: "cycliste@exemple.invalid", expire_le: "2026-09-26T10:00:00+02:00" },
        },
      },
    });
    serveur.installer();
    render(<Entrer jeton="un-jeton-valable" surEntre={() => undefined} />);

    expect(await screen.findByText(/cycliste@exemple\.invalid/)).toBeTruthy();
    expect(screen.getByLabelText("Mot de passe")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ouvrir mon compte" })).toBeTruthy();

    expect(serveur.requetes[0].chemin).toContain("jeton=un-jeton-valable");
  });

  it("jeton refusé : aucun formulaire, et un seul geste, celui qui mène quelque part", async () => {
    const serveur = new Serveur({
      "/api/v1/invitation": panne("invitation_invalide", "ce lien n'est plus valable", 404),
    });
    serveur.installer();
    render(<Entrer jeton="un-jeton-perime" surEntre={() => undefined} />);

    expect(await screen.findByRole("heading", { name: "Ce lien n'est plus valable" })).toBeTruthy();
    // Aucun mot de passe à saisir sur un jeton refusé — il n'y a rien à activer.
    expect(screen.queryByLabelText("Mot de passe")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();

    // **Mais un chemin, et le plus frequent.** Un lien d'invitation ne vaut
    // qu'une fois : celui qui reclique sur le sien a deja un compte. Sans ce
    // lien, on lui disait de redemander une invitation dont il n'a aucun
    // besoin (constate le 19/09/2026, sur le premier lien reclique).
    const versConnexion = screen.getByRole("link", { name: "Se connecter" });
    expect(versConnexion.getAttribute("href")).toBe("/connexion");
    expect(screen.getByText(/une nouvelle invitation/)).toBeTruthy();
  });

  it("active le compte : envoie le jeton et le secret, puis prévient l'appelant", async () => {
    const serveur = new Serveur({
      "/api/v1/invitation": {
        charge: { donnees: { email: "cycliste@exemple.invalid", expire_le: "2026-09-26T10:00:00+02:00" } },
      },
      "/api/v1/entrer": { charge: { donnees: { proprietaire: "essai" } } },
    });
    serveur.installer();
    let entre = false;
    render(<Entrer jeton="un-jeton-valable" surEntre={() => (entre = true)} />);

    await screen.findByLabelText("Mot de passe");
    const utilisateur = userEvent.setup();
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "un-secret-de-test");
    await utilisateur.click(screen.getByRole("button", { name: "Ouvrir mon compte" }));

    expect(entre).toBe(true);
    const requete = serveur.vers("/api/v1/entrer")[0];
    expect(requete.corps).toEqual({ jeton: "un-jeton-valable", secret: "un-secret-de-test" });
  });
});

describe("Connexion", () => {
  it("envoie l'adresse et le secret, puis prévient l'appelant", async () => {
    const serveur = new Serveur({
      "/api/v1/connexion": { charge: { donnees: { proprietaire: "essai" } } },
    });
    serveur.installer();
    let connecte = false;
    render(<Connexion surConnecte={() => (connecte = true)} />);

    const utilisateur = userEvent.setup();
    await utilisateur.type(screen.getByLabelText("Adresse"), "cycliste@exemple.invalid");
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "un-secret-de-test");
    await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(connecte).toBe(true);
    expect(serveur.vers("/api/v1/connexion")[0].corps).toEqual({
      email: "cycliste@exemple.invalid",
      secret: "un-secret-de-test",
    });
  });

  it("un refus (même réponse pour une adresse inconnue et un mauvais secret) s'affiche tel quel", async () => {
    const serveur = new Serveur({
      "/api/v1/connexion": panne("identifiants_refuses", "adresse ou mot de passe refusés", 401),
    });
    serveur.installer();
    render(<Connexion surConnecte={() => undefined} />);

    const utilisateur = userEvent.setup();
    await utilisateur.type(screen.getByLabelText("Adresse"), "cycliste@exemple.invalid");
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "un-mauvais-secret");
    await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText(/adresse ou mot de passe refusés/)).toBeTruthy();
    // Toujours à l'écran de connexion, pas ailleurs : pas de création de
    // compte proposée depuis ici.
    expect(screen.getByRole("heading", { name: "Se connecter" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /créer un compte/i })).toBeNull();
  });
});

describe("l'application choisit sa page sur window.location.pathname, une fois au démarrage", () => {
  it("/entrer retire le jeton de la barre d'adresse dès qu'il est lu", async () => {
    window.history.pushState({}, "", "/entrer?jeton=un-jeton-secret");
    const serveur = new Serveur({
      "/api/v1/invitation": panne("invitation_invalide", "ce lien n'est plus valable", 404),
    });
    serveur.installer();
    render(<App />);

    await screen.findByRole("heading", { name: "Ce lien n'est plus valable" });
    expect(window.location.pathname).toBe("/entrer");
    expect(window.location.search).toBe("");
  });

  it("/connexion ouvre l'écran de connexion directement, sans passer par l'application", () => {
    window.history.pushState({}, "", "/connexion");
    render(<App />);

    expect(screen.getByRole("heading", { name: "Se connecter" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Navigation principale" })).toBeNull();
  });

  it("tout le reste (« / ») est l'application d'aujourd'hui, inchangée", async () => {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
    });
    serveur.installer();
    render(<App />);

    // La session ouvre normalement (pas de 401 ici) : c'est bien l'application
    // des quatre onglets qui tourne à la racine, pas un écran de session.
    expect(await screen.findByRole("navigation", { name: "Navigation principale" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Se connecter" })).toBeNull();
  });
});

describe("se déconnecter", () => {
  it("appelle POST /sortir puis ramène à l'écran de connexion", async () => {
    const serveur = new Serveur({ "/api/v1/sortir": { charge: { donnees: {} } } });
    serveur.installer();
    let deconnecte = false;
    render(
      <Reglages
        profil={PROFIL.donnees}
        zones={ZONES}
        surProfil={() => undefined}
        surZones={() => undefined}
        surRefaireInstallation={() => undefined}
        surDeconnexion={() => (deconnecte = true)}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Se déconnecter" }));

    expect(deconnecte).toBe(true);
    expect(serveur.vers("/api/v1/sortir")).toHaveLength(1);
    expect(serveur.vers("/api/v1/sortir")[0].methode).toBe("POST");
  });
});

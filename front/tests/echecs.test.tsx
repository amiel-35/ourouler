/** Les quatre états d'échec sont des **écrans**, et ils cassent en silence.
 *
 * C'est exactement ce qui justifie ces tests : un écran d'échec n'est jamais
 * regardé pendant le développement, et un écran vide se lit « rien de prévu ».
 */

import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErreurApi } from "../src/api/client";
import { Echec, meteoManquante } from "../src/composants/Echec";
import { Barriere } from "../src/composants/Barriere";
import { Propositions } from "../src/ecrans/Propositions";
import { Aujourdhui } from "../src/ecrans/Aujourdhui";
import { App } from "../src/App";
import { Serveur, panne } from "./serveur";
import { PROFIL, SEMAINE, SYSTEME, meteo, sortie, zones } from "./fixtures";

function erreur(code: string, message: string, statut = 502) {
  return new ErreurApi({ code, message, service: null, details: {} }, statut);
}

describe("aucune boucle trouvée", () => {
  it("propose des leviers avec leurs valeurs, jamais un « réessayez » nu", () => {
    const essais: string[] = [];
    render(
      <Echec
        erreur={erreur("aucune_boucle", "aucune boucle dans la tolérance", 422)}
        contexte="Un contexte inventé"
        replis={[
          { titre: "Élargir la durée", detail: "108 à 132 minutes", action: () => essais.push("duree") },
          { titre: "Laisser le vent libre", action: () => essais.push("vent") },
        ]}
      />,
    );
    expect(screen.getByRole("heading", { name: "Aucune boucle" })).toBeTruthy();
    expect(screen.getByText(/aucune boucle dans la tolérance/)).toBeTruthy();
    expect(screen.getByText("Élargir la durée")).toBeTruthy();
    expect(screen.getByText("108 à 132 minutes")).toBeTruthy();
    expect(screen.getByText(/ne coûte rien/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Essayer" })).toHaveLength(2);
  });
});

describe("clé Intervals révoquée", () => {
  /**
   * **Ce test gravait un défaut d'affichage** (corrigé le 17/09/2026).
   *
   * Il attendait `/plus lues depuis le 2026-09-12/`, c'est-à-dire la date ISO
   * telle qu'elle sort de l'API, affichée telle quelle au cycliste. La
   * maquette E15 fait pourtant de cette phrase le point de l'écran : « la date
   * compte plus que le message — “plus lues depuis le 12 septembre” dit à
   * quelqu'un ce qu'il a manqué ». Le test ne gardait pas l'exigence, il
   * figeait l'écart avec elle (relecture F2 · C2).
   *
   * Il attend maintenant la date en toutes lettres, et refuse explicitement la
   * forme ISO — sans quoi rien n'empêcherait d'y revenir.
   */
  it("dit la date du dernier succès en toutes lettres, et ce qui marche encore", () => {
    render(
      <Echec
        erreur={erreur("intervals_refuse", "Intervals.icu : HTTP 403")}
        dernierSucces="2026-09-12"
        secours={<p>Vous pouvez demander un parcours à la main.</p>}
      />,
    );
    expect(screen.getByText(/ne nous répond plus/)).toBeTruthy();
    expect(screen.getByText(/plus lues depuis le samedi 12 septembre/)).toBeTruthy();
    expect(screen.queryByText(/2026-09-12/)).toBeNull();
    expect(screen.getByText(/demander un parcours à la main/)).toBeTruthy();
  });

  /** C11 : le cadre titrait « Cette semaine » même sous l'onglet du jour. */
  it("se titre d'après l'écran où la panne est arrivée", () => {
    render(
      <Echec
        erreur={erreur("intervals_refuse", "Intervals.icu : HTTP 403")}
        contexte="Aujourd'hui"
      />,
    );
    expect(screen.getByRole("heading", { name: "Aujourd'hui" })).toBeTruthy();
    expect(screen.queryByText("Cette semaine")).toBeNull();
  });

  it("n'invente aucune date quand le navigateur n'en a pas", () => {
    render(<Echec erreur={erreur("intervals_refuse", "Intervals.icu : HTTP 403")} />);
    expect(screen.queryByText(/plus lues depuis/)).toBeNull();
  });
});

describe("météo indisponible", () => {
  it("se tait sur la tenue au lieu de conseiller au hasard", () => {
    render(
      <Echec
        erreur={erreur("meteo_indisponible", "Open-Meteo : HTTP 502")}
        reessayer={() => undefined}
      />,
    );
    expect(screen.getByText(/on ne conseille rien plutôt que de conseiller au hasard/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Réessayer la météo" })).toBeTruthy();
  });

  it("dégradé : le parcours reste servi, la météo est signalée absente", () => {
    const reponse = sortie({
      avertissements: [
        {
          code: "meteo_indisponible",
          message: "météo indisponible (Open-Meteo : HTTP 502) — le placement reste valable",
        },
      ],
    });
    render(
      <Aujourdhui
        jour="2026-09-16"
        seance={null}
        parcours={{ obtenue_le: "2026-09-16T06:02:00+02:00", reponse }}
        heureDepart="09:00"
        surHeureDepart={() => undefined}
        surGenerer={() => undefined}
        surOuvrir={() => undefined}
        surDemander={() => undefined}
        surDeposer={() => undefined}
      />,
    );
    expect(screen.getByText(/Pas de météo/)).toBeTruthy();
    expect(screen.getByText(/le placement reste valable/)).toBeTruthy();
    // Le parcours n'a pas disparu pour autant.
    expect(screen.getByText("Parcours prêt")).toBeTruthy();
  });
});

describe("une seule proposition au lieu de trois", () => {
  it("n'a pas l'air d'une panne, et porte le motif du cœur", () => {
    const reponse = sortie({
      propositions: 1,
      motif: "les cinq boucles empruntaient plus du quart des mêmes routes",
    });
    render(
      <Propositions
        reponse={reponse}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surElargir={() => undefined}
        surRetour={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Un seul parcours" })).toBeTruthy();
    expect(screen.getByText(/On en voulait trois, et on en propose moins/)).toBeTruthy();
    expect(screen.getByText(/empruntaient plus du quart des mêmes routes/)).toBeTruthy();
    // « La seule candidate » portait le mot du moteur — `candidates` est le
    // nombre de boucles tracées avant tri, pas un parcours proposé. Le badge
    // dit maintenant la même chose sans ce mot-là.
    expect(screen.getByText("Le seul")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Chercher plus loin/ })).toBeTruthy();
    // Aucun mot d'erreur : ce n'est pas une panne.
    expect(screen.queryByText(/erreur/i)).toBeNull();
  });
});

describe("trois propositions qui se valent (Q45)", () => {
  it("le dit au lieu de laisser chercher une différence, et n'a pas l'air d'une panne", () => {
    const reponse = sortie({
      muettes: true,
      equivalence:
        "Ces trois boucles se valent : la pluie, les demi-tours et le terrain sous les blocs " +
        "valaient la même chose sur les trois. Choisissez où vous voulez aller.",
    });
    render(
      <Propositions
        reponse={reponse}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surElargir={() => undefined}
        surRetour={() => undefined}
      />,
    );
    // Les trois sont bien là : c'est tout l'intérêt de Q43, on ne les jette
    // plus faute de savoir les résumer.
    expect(screen.getByRole("heading", { name: "3 parcours" })).toBeTruthy();
    expect(screen.getByText(/Au choix/)).toBeTruthy();
    expect(screen.getByText(/Ces trois boucles se valent/)).toBeTruthy();
    expect(screen.getByText(/Choisissez où vous voulez aller/)).toBeTruthy();
    // Sans axe distinctif, le titre reste le numéro : nommer « Le vent » ou
    // « La pluie » sur une proposition que rien ne distingue serait inventer.
    expect(screen.getByRole("heading", { name: "Proposition 2" })).toBeTruthy();
    // Ce n'est pas une panne, et ce n'est pas non plus le cas « moins de trois ».
    expect(screen.queryByText(/On en voulait trois/)).toBeNull();
    expect(screen.queryByText(/erreur/i)).toBeNull();
  });

  it("se tait quand une proposition se détache — la phrase serait fausse", () => {
    render(
      <Propositions
        reponse={sortie()}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surElargir={() => undefined}
        surRetour={() => undefined}
      />,
    );
    expect(screen.queryByText(/se valent/)).toBeNull();
    expect(screen.getByRole("heading", { name: "Le vent" })).toBeTruthy();
  });
});

describe("le serveur ne répond pas du tout", () => {
  it("se distingue d'une panne de l'API et nomme le code", () => {
    render(
      <Echec
        erreur={erreur("serveur_injoignable", "le serveur d'où rouler ne répond pas", 0)}
        reessayer={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Le serveur ne répond pas" })).toBeTruthy();
    expect(screen.getByText(/Code de la panne : serveur_injoignable/)).toBeTruthy();
  });

  it("dit ce qui est sûr et offre le geste, au lieu d'une phrase nue", () => {
    const essais: string[] = [];
    render(
      <Echec
        erreur={erreur("serveur_injoignable", "le serveur d'où rouler ne répond pas", 500)}
        reessayer={() => essais.push("encore")}
      />,
    );
    expect(screen.getByText(/Rien n'est perdu/)).toBeTruthy();
    expect(screen.getByText(/n'est jamais arrivée/)).toBeTruthy();
    const bouton = screen.getByRole("button", { name: "Réessayer" });
    bouton.click();
    expect(essais).toEqual(["encore"]);
  });

  it("distingue un serveur sans profil d'un serveur muet", () => {
    render(
      <Echec
        erreur={erreur("profil_absent", "cette application a été construite sans profil", 503)}
      />,
    );
    expect(screen.getByRole("heading", { name: "Ce serveur n'a pas de profil" })).toBeTruthy();
    expect(screen.queryByText(/Rien n'est perdu/)).toBeNull();
  });

  it("nomme autrement un délai dépassé et une réponse d'ailleurs", () => {
    const { unmount } = render(
      <Echec erreur={erreur("delai_depasse", "pas de réponse en 30 secondes", 0)} />,
    );
    expect(screen.getByRole("heading", { name: "Le serveur ne rend pas la main" })).toBeTruthy();
    unmount();
    render(<Echec erreur={erreur("reponse_illisible", "ce n'est pas l'API", 200)} />);
    expect(
      screen.getByRole("heading", { name: "Ce n'est pas d'où rouler qui a répondu" }),
    ).toBeTruthy();
  });

  /**
   * **Le défaut trouvé en faisant tourner le produit, le 17/09/2026.**
   *
   * Front lancé sans API derrière : le proxy de développement répond `500`
   * en `text/plain`, corps vide. L'écran affichait « Ça n'a pas marché — le
   * serveur a répondu 500 sans rien expliquer », code `erreur_interne`, sans
   * bouton parce que ce code-là n'est pas réessayable. C'est l'écran muet que
   * la section « Quand ça casse » des maquettes interdit, pour la panne la
   * plus banale de toutes : personne au bout du fil.
   */
  it("reconnaît l'API absente derrière le proxy, au démarrage de l'application", async () => {
    new Serveur({ "/api/v1/": { statut: 500, texte: "" } }).installer();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Le serveur ne répond pas" })).toBeTruthy();
    expect(screen.queryByText(/sans rien expliquer/)).toBeNull();
    expect(screen.queryByText("Connexion au serveur…")).toBeNull();
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeTruthy();
    expect(screen.getByText(/ourouler api --port 8000/)).toBeTruthy();
  });
});

describe("l'écran d'un jour sans séance", () => {
  it("dit « jour de repos » plutôt que de rester vide", async () => {
    // Sans parcours (`parcours={null}`), l'écran charge la rose des huit
    // directions (« où rouler » sans avoir rien demandé) — il lui faut donc
    // un serveur factice pour `/api/v1/meteo`, même si ce test ne regarde
    // pas la rose elle-même.
    new Serveur({ "/api/v1/meteo": { charge: meteo() } }).installer();
    render(
      <Aujourdhui
        jour="2026-09-17"
        seance={null}
        parcours={null}
        heureDepart="09:00"
        surHeureDepart={() => undefined}
        surGenerer={() => undefined}
        surOuvrir={() => undefined}
        surDemander={() => undefined}
        surDeposer={() => undefined}
      />,
    );
    expect(screen.getByRole("heading", { name: "Rien de prévu" })).toBeTruthy();
    expect(screen.getByText(/ce n'est pas une panne, c'est un jour de repos/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Demander un parcours" })).toBeTruthy();
    // Laisse la rose s'installer avant la fin du test, pour ne pas laisser
    // une mise à jour d'état retomber hors de tout `act(...)`.
    expect(await screen.findByRole("img", { name: /Où rouler/ })).toBeTruthy();
  });
});

describe("la barrière de dernier recours", () => {
  it("remplace la page blanche par un écran qui dit ce qui s'est passé", () => {
    const Casse = () => {
      throw new Error("champ « etapes » absent de la réponse");
    };
    // React écrit lui-même la trace sur la console : on la tait le temps du
    // test, sinon la sortie laisse croire à un échec.
    const bruit = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <Barriere>
        <Casse />
      </Barriere>,
    );
    bruit.mockRestore();
    expect(screen.getByRole("heading", { name: "Cet écran n'a pas su s'afficher" })).toBeTruthy();
    expect(screen.getByText(/défaut de l'interface, pas de vos données/)).toBeTruthy();
    expect(screen.getByText(/champ « etapes » absent de la réponse/)).toBeTruthy();
  });

  it("laisse passer ce qui s'affiche normalement", () => {
    render(
      <Barriere>
        <p>tout va bien</p>
      </Barriere>,
    );
    expect(screen.getByText("tout va bien")).toBeTruthy();
    expect(screen.queryByText(/n'a pas su s'afficher/)).toBeNull();
  });
});

describe("une panne au démarrage ne fige pas l'application", () => {
  /**
   * B2 : `zones.erreur` n'était consulté nulle part, alors que l'affichage
   * est interdit tant que les zones ne sont pas chargées. Une panne de
   * `/profil/zones` laissait donc « Connexion au serveur… » **pour
   * toujours** : pas de code, pas de bouton, pas de barre d'onglets. C'est
   * l'écran muet que la section « Quand ça casse » des maquettes interdit,
   * dans sa forme la plus nue — rien n'y distingue un serveur en panne d'une
   * application cassée, et le seul geste restant était le rechargement, que
   * l'écran d'attente prend soin de déconseiller.
   */
  it("nomme la panne de /profil/zones au lieu d'attendre indéfiniment", async () => {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": panne("erreur_interne", "zones : la table est vide", 500),
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances": { charge: SEMAINE },
    });
    serveur.installer();
    render(<App />);

    expect(await screen.findByText(/zones : la table est vide/)).toBeTruthy();
    expect(screen.getByText(/Code de la panne : erreur_interne/)).toBeTruthy();
    expect(screen.queryByText("Connexion au serveur…")).toBeNull();
  });

  /**
   * Le bouton n'apparaît que pour une panne dont on peut espérer qu'elle
   * passe : proposer « Réessayer » sur un bug du serveur serait promettre au
   * cycliste que le geste sert à quelque chose. `reessayable` en tient la
   * liste ; ce test vérifie que la panne rattrapable, elle, l'offre bien.
   */
  it("offre le geste suivant quand la panne est de celles qui passent", async () => {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": panne(
        "service_externe_indisponible",
        "le service des zones ne répond pas",
        502,
      ),
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances": { charge: SEMAINE },
    });
    serveur.installer();
    render(<App />);

    expect(await screen.findByRole("button", { name: "Réessayer" })).toBeTruthy();
    expect(screen.queryByText("Connexion au serveur…")).toBeNull();
  });

  /**
   * `session_absente` a un écran de connexion depuis le lot L7.2-D
   * (19/09/2026) — avant, aucune méthode d'authentification n'existait, et
   * ce test vérifiait explicitement l'inverse : ni formulaire, ni bouton
   * « se connecter ». Maintenant qu'un compte et un mot de passe existent
   * (`/entrer`, `/connexion`), laisser l'ancienne affirmation aurait figé un
   * refus qui n'a plus lieu d'être — la même erreur que la relecture du
   * 17/09/2026 mettait en garde contre, ailleurs dans ce fichier.
   *
   * Ce test couvre les deux moitiés de l'exigence : l'écran de connexion
   * s'affiche sur le 401 (pas l'ancien écran muet), et une fois connecté
   * l'application reprend **sans y reboucler** — la session étant ouverte,
   * `/systeme` etc. répondent, et « Se connecter » disparaît pour de bon.
   */
  /**
   * Le cas que le précédent ne couvrait pas, et qui arrivait quand même.
   *
   * Le test au-dessus rebranche tout le serveur d'un coup : aucune requête ne
   * reste en vol par-dessus la reconnexion. La vraie vie, si — le cookie
   * expire pendant qu'une recherche de sortie tourne, le cycliste se
   * reconnecte, puis la vieille requête revient avec son 401 et le ramène à
   * l'écran de connexion sans qu'il comprenne pourquoi.
   *
   * Trouvé en relecture le 19/09/2026, sur du code dont le premier test
   * passait déjà.
   */
  it("un 401 en retard, arrivé après la reconnexion, ne rouvre pas l'écran", async () => {
    let connecte = false;
    let repondreEnRetard: (() => void) | null = null;
    const serveur = new Serveur({
      "/api/v1/systeme": () =>
        connecte ? { charge: SYSTEME } : panne("session_absente", "aucune session ouverte", 401),
      "/api/v1/profil/zones": () =>
        connecte ? { charge: zones() } : panne("session_absente", "aucune session ouverte", 401),
      // Celle-ci ne répond **jamais** tout de suite : elle reste en vol, et
      // on la fait revenir à la main, après la reconnexion.
      "/api/v1/profil": () =>
        connecte
          ? { charge: PROFIL }
          : new Promise<ReturnType<typeof panne>>((resoudre) => {
              repondreEnRetard = () =>
                resoudre(panne("session_absente", "aucune session ouverte", 401));
            }),
      "/api/v1/connexion": () => {
        connecte = true;
        return { charge: { donnees: { proprietaire: "essai" } } };
      },
    });
    serveur.installer();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Se connecter" })).toBeTruthy();

    const utilisateur = userEvent.setup();
    await utilisateur.type(screen.getByLabelText("Adresse"), "cycliste@exemple.invalid");
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "un-secret-de-test");
    await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByRole("navigation", { name: "Navigation principale" })).toBeTruthy();

    // Et maintenant, la requête d'avant revient — trop tard.
    expect(repondreEnRetard).not.toBeNull();
    await act(async () => {
      repondreEnRetard!();
      // Deux tours de boucle : le `await` du corps de la réponse, puis celui
      // du client. Un seul laissait le 401 en chemin, et le test verdissait
      // sans avoir rien mesuré.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByRole("heading", { name: "Se connecter" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Navigation principale" })).toBeTruthy();
  });

  it("un 401 session_absente amène l'écran de connexion, et n'y reboucle pas après connexion", async () => {
    let connecte = false;
    const serveur = new Serveur({
      "/api/v1/systeme": () =>
        connecte ? { charge: SYSTEME } : panne("session_absente", "aucune session ouverte", 401),
      "/api/v1/profil/zones": () =>
        connecte
          ? { charge: zones() }
          : panne("session_absente", "aucune session ouverte", 401),
      "/api/v1/profil": () =>
        connecte ? { charge: PROFIL } : panne("session_absente", "aucune session ouverte", 401),
      "/api/v1/connexion": () => {
        connecte = true;
        return { charge: { donnees: { proprietaire: "essai" } } };
      },
    });
    serveur.installer();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Se connecter" })).toBeTruthy();
    expect(screen.queryByText("Connexion au serveur…")).toBeNull();
    // L'ancien écran (fixe, sans geste possible) ne doit plus jamais apparaître ici.
    expect(
      screen.queryByRole("heading", { name: "Ce serveur ne sait pas encore qui vous êtes" }),
    ).toBeNull();

    const utilisateur = userEvent.setup();
    await utilisateur.type(screen.getByLabelText("Adresse"), "cycliste@exemple.invalid");
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "un-secret-de-test");
    await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));

    // La session est ouverte : l'application reprend, et ne rouvre pas
    // l'écran de connexion derrière elle.
    expect(await screen.findByRole("navigation", { name: "Navigation principale" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Se connecter" })).toBeNull();

    const requetesConnexion = serveur.vers("/api/v1/connexion");
    expect(requetesConnexion).toHaveLength(1);
    expect(requetesConnexion[0].corps).toEqual({
      email: "cycliste@exemple.invalid",
      secret: "un-secret-de-test",
    });
  });
});

describe("le bandeau météo se décide sur le code, jamais sur la phrase", () => {
  /**
   * L'invariant de B3, et la raison d'être du code dans `avertissements`.
   *
   * Avant le 17/09/2026, `meteoManquante` testait `/m[ée]t[ée]o/i` sur le
   * message. Le jour où quelqu'un reformulait l'avertissement du cœur en
   * « Open-Meteo injoignable » — ce que `docs/journal/ux/api_contrat.md` autorise
   * explicitement — le bandeau disparaissait en silence, et il restait un
   * parcours servi sans pluie, sans vent et sans la phrase qui dit pourquoi.
   *
   * Les trois cas ci-dessous sont exactement ceux que l'ancienne expression
   * régulière ratait, dans un sens ou dans l'autre.
   */
  it("reconnaît un avertissement reformulé, sans le mot « météo »", () => {
    expect(
      meteoManquante([{ code: "meteo_indisponible", message: "Open-Meteo injoignable" }]),
    ).toBe("Open-Meteo injoignable");
  });

  it("ne déclenche rien sur un avertissement qui parle de météo sans en être un", () => {
    expect(
      meteoManquante([
        {
          code: "second_avis_indisponible",
          message: "second avis « icon » indisponible — confiance « inconnu » partout",
        },
      ]),
    ).toBeNull();
  });

  it("ignore un avertissement que le catalogue ne nomme pas encore", () => {
    expect(
      meteoManquante([{ code: "autre", message: "une phrase imprévue au sujet de la météo" }]),
    ).toBeNull();
  });
});

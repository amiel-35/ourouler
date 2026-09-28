/** Q44 — un seul choix de direction, jamais deux réglages qui se contredisent.
 *
 * Ce que ces tests protègent :
 *
 * - « Ma direction » et « Selon le vent » n'affichent jamais leur
 *   sélecteur en même temps — la contradiction disparaît par la forme,
 *   elle ne se contrôle pas au moment de l'envoi ;
 * - l'appel à `POST /sorties` ne porte jamais `direction` **et** un `vent`
 *   contraignant à la fois — c'est le point qui casse en vrai (l'API refuse
 *   avec un 400) si on le rate ;
 * - le vent s'affiche dans les deux modes (« Ma séance » et « Endurance
 *   Z2 »), jamais recalculé côté front ;
 * - le latéral montre ses **deux** azimuts opposés, pas un seul ;
 * - `posee: false` affiche le motif de l'API, jamais un vent inventé.
 */

import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Demander, demandeInitiale, type Demande } from "../src/ecrans/Demander";
import { Boucles } from "../src/ecrans/Boucles";
import { Serveur } from "./serveur";
import { PROFIL, SEANCE, SEMAINE, SYSTEME, boucle, meteo, sortie, ventDepart, zones } from "./fixtures";

const ZONES = zones().donnees;

/** `Demander` est entièrement pilotée depuis l'extérieur : ce conteneur lui
 * donne l'état local qu'`App` lui donne d'habitude. */
function ConteneurDemander({ demande: demandeDepart }: { demande: Demande }) {
  const [demande, setDemande] = useState(demandeDepart);
  return (
    <Demander
      profil={PROFIL.donnees}
      zones={ZONES}
      dureeSeance_s={SEANCE.donnees.duree_s}
      nomSeance={SEANCE.donnees.nom}
      demande={demande}
      budget={null}
      surDemande={setDemande}
      surChercher={() => undefined}
    />
  );
}

function demandeEssai(morceau?: Partial<Demande>): Demande {
  return { ...demandeInitiale(), jour: "2026-09-18", ...morceau };
}

describe("le libellé « Direction » ne se répète plus (signalé le 18/09/2026)", () => {
  it("distingue le choix du mode de celui du point cardinal", async () => {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));

    // Avant « Ma direction » : un seul champ porte « Direction », celui du mode.
    expect(screen.getAllByText("Direction")).toHaveLength(1);
    expect(screen.queryByText("Point cardinal")).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));

    // Le sélecteur d'azimut apparaît, et il ne recopie plus le même mot.
    expect(screen.getAllByText("Direction")).toHaveLength(1);
    expect(screen.getByText("Point cardinal")).toBeTruthy();
  });
});

describe("un seul sélecteur affiché à la fois", () => {
  // « Là où il fait sec » a disparu le 20/09/2026 : la rose des directions
  // (`RoseDirections`, mode « Ma direction ») montre déjà la direction
  // recommandée, cerclée, sans qu'il faille cliquer un bouton à part pour
  // la demander. Ce test vérifie donc la présence de la rose (un groupe
  // accessible nommé) plutôt que ce lien disparu.
  it("« Ma direction » puis « Selon le vent » ne laissent jamais les deux sélecteurs visibles", async () => {
    const serveur = new Serveur({
      "/api/v1/vent-depart": { charge: ventDepart() },
      "/api/v1/meteo": { charge: meteo() },
    });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);

    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));

    // Au départ (« peu importe ») : ni l'un ni l'autre.
    expect(screen.queryByRole("group", { name: /Choisir une direction/ })).toBeNull();
    expect(screen.queryByText("Vent dans le dos au départ")).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));
    await waitFor(() => expect(serveur.vers("/api/v1/meteo").length).toBeGreaterThan(0));
    expect(await screen.findByRole("group", { name: /Choisir une direction/ })).toBeTruthy();
    expect(screen.queryByText("Vent dans le dos au départ")).toBeNull();
    expect(screen.queryByText("Vent dans le dos au retour")).toBeNull();
    expect(screen.queryByText("Vent latéral")).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    expect(screen.queryByRole("group", { name: /Choisir une direction/ })).toBeNull();
    expect(screen.getByText("Vent dans le dos au départ")).toBeTruthy();
    expect(screen.getByText("Vent dans le dos au retour")).toBeTruthy();
    expect(screen.getByText("Vent latéral")).toBeTruthy();

    await utilisateur.click(screen.getByRole("button", { name: "Peu importe" }));
    expect(screen.queryByRole("group", { name: /Choisir une direction/ })).toBeNull();
    expect(screen.queryByText("Vent dans le dos au départ")).toBeNull();
  });
});

describe("le vent s'affiche dans les deux modes", () => {
  it("affiche « Vent de sud-ouest à 22 km/h » en mode « Ma séance »", async () => {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai({ mode: "seance" })} />);
    expect(await screen.findByText("Vent de sud-ouest à 22 km/h")).toBeTruthy();
  });

  it("affiche « Vent de sud-ouest à 22 km/h » en mode « Endurance Z2 »", async () => {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai({ mode: "z2" })} />);
    expect(await screen.findByText("Vent de sud-ouest à 22 km/h")).toBeTruthy();
  });

  it("griser le mode « Selon le vent » en Endurance Z2, sans le faire disparaître", async () => {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai({ mode: "z2" })} />);
    await screen.findByText("Vent de sud-ouest à 22 km/h");

    const selonLeVent = screen.getByRole("button", { name: "Selon le vent" }) as HTMLButtonElement;
    expect(selonLeVent.disabled).toBe(true);
    expect(screen.getByText(/pas encore disponible pour une sortie libre/)).toBeTruthy();
  });
});

describe("le latéral ouvre deux azimuts opposés", () => {
  it("montre les deux azimuts, pas un seul, pour « Vent latéral »", async () => {
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: ventDepart() } });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));

    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));

    // Les deux azimuts opposés du latéral, tels que rend `azimuts_par_choix.travers`
    // dans la fixture — jamais un seul, jamais recalculés.
    expect(screen.getByText("Vent latéral : NO (315°) et SE (135°)")).toBeTruthy();
    // Et les deux préférences à un seul azimut, pour vérifier qu'on ne les confond pas.
    expect(screen.getByText("Vent dans le dos au départ : NE (45°)")).toBeTruthy();
    expect(screen.getByText("Vent dans le dos au retour : SO (225°)")).toBeTruthy();
  });
});

describe("posee: false n'invente aucun vent", () => {
  it("affiche le motif de l'API et grise « Selon le vent »", async () => {
    const serveur = new Serveur({
      "/api/v1/vent-depart": {
        charge: ventDepart({ posee: false, motif: "vent sous le seuil (motif inventé)" }),
      },
    });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai()} />);

    expect(await screen.findByText("vent sous le seuil (motif inventé)")).toBeTruthy();
    // Aucun vent inventé : ni la phrase « Vent de … », ni un chiffre de vent.
    expect(screen.queryByText(/^Vent de /)).toBeNull();
    const selonLeVent = screen.getByRole("button", { name: "Selon le vent" }) as HTMLButtonElement;
    expect(selonLeVent.disabled).toBe(true);
  });

  it("n'affirme aucun vent quand la question n'est pas posée, même en mode « selon le vent »", async () => {
    // Le cas qui se produit vraiment : le cycliste avait choisi « selon le
    // vent » hier, il revient un jour sans vent. On ne garde pas une
    // préférence qui ne dirige plus rien en faisant croire qu'elle agit.
    const serveur = new Serveur({
      "/api/v1/vent-depart": { charge: ventDepart({ posee: false }) },
    });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai({ modeDirection: "vent", vent: "travers" })} />);
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));

    // Aucun azimut annoncé sous les préférences : `azimuts_par_choix` est vide
    // partout, et l'écran ne comble pas le vide.
    expect(screen.queryByText(/Vent latéral\s*:/)).toBeNull();
    expect(screen.queryByText(/315|135/)).toBeNull();
    expect(screen.queryByText(/^Vent de /)).toBeNull();
  });
});

describe("le motif technique d'un connecteur externe ne s'affiche jamais tel quel (rejoué le 25/09/2026)", () => {
  it("remplace un motif qui porte une URL par une phrase courte, sans URL ni HTTP", async () => {
    const motifBrut =
      "vent au départ indisponible (Open-Meteo : HTTP 400 sur https://api.open-meteo.com/v1/forecast — No data is available for this location (modèle demandé : arome))";
    const serveur = new Serveur({
      "/api/v1/vent-depart": { charge: ventDepart({ posee: false, motif: motifBrut }) },
    });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai()} />);

    expect(
      await screen.findByText("Le vent au départ n'est pas disponible pour ce point de départ."),
    ).toBeTruthy();
    expect(screen.queryByText(/https?:\/\//)).toBeNull();
    expect(screen.queryByText(/HTTP/)).toBeNull();
    expect(screen.queryByText(motifBrut)).toBeNull();
  });

  it("garde un motif déjà en français quand il ne porte aucun détail technique", async () => {
    const serveur = new Serveur({
      "/api/v1/vent-depart": {
        charge: ventDepart({ posee: false, motif: "vent sous le seuil (motif inventé)" }),
      },
    });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai()} />);

    expect(await screen.findByText("vent sous le seuil (motif inventé)")).toBeTruthy();
  });

  it("propose Réglages quand le départ n'est encore que le défaut du compte neuf", async () => {
    const motifBrut = "vent au départ indisponible (Open-Meteo : HTTP 400 sur https://api.open-meteo.com/v1/forecast)";
    // Coordonnées fictives (règle absolue 1) : seule `noyau.profil.DEPART_PAR_DEFAUT`
    // porte les vraies coordonnées du repli côté serveur.
    const profilSansDepart = {
      ...PROFIL.donnees,
      depart: { nom: "Paris", latitude: 0, longitude: 0, par_defaut: true },
    };
    const serveur = new Serveur({
      "/api/v1/vent-depart": { charge: ventDepart({ posee: false, motif: motifBrut }) },
    });
    serveur.installer();
    render(
      <Demander
        profil={profilSansDepart}
        zones={ZONES}
        dureeSeance_s={SEANCE.donnees.duree_s}
        nomSeance={SEANCE.donnees.nom}
        demande={demandeEssai()}
        budget={null}
        surDemande={() => undefined}
        surChercher={() => undefined}
      />,
    );

    await screen.findByText("Le vent au départ n'est pas disponible pour ce point de départ.");
    expect(screen.getByRole("link", { name: "Renseigner votre départ dans les réglages" })).toBeTruthy();
  });

  it("ne propose pas Réglages quand un départ réel est déjà enregistré", async () => {
    const motifBrut = "vent au départ indisponible (Open-Meteo : HTTP 400 sur https://api.open-meteo.com/v1/forecast)";
    const serveur = new Serveur({
      "/api/v1/vent-depart": { charge: ventDepart({ posee: false, motif: motifBrut }) },
    });
    serveur.installer();
    render(<ConteneurDemander demande={demandeEssai()} />);

    await screen.findByText("Le vent au départ n'est pas disponible pour ce point de départ.");
    expect(screen.queryByRole("link", { name: /Réglages/ })).toBeNull();
  });
});

describe("les valeurs du vent viennent de l'API, jamais d'un calcul local", () => {
  it("suit la fixture quand elle change de vent, au lieu de rester au sud-ouest", async () => {
    // Le défaut le plus silencieux d'un front : un secteur déduit sur place
    // (ou pire, recopié de la maquette) passe toutes les relectures. Ici tout
    // vient d'`azimuts_par_choix`, donc changer la fixture doit tout changer.
    const est = ventDepart();
    est.donnees.vent_kmh = 31;
    est.donnees.vent_depuis_deg = 90;
    est.donnees.vent_depuis_nom = "E";
    est.donnees.azimuts_par_choix = {
      "peu-importe": [],
      "retour-dos": [{ azimut_deg: 90, nom: "E" }],
      "depart-dos": [{ azimut_deg: 270, nom: "O" }],
      travers: [
        { azimut_deg: 180, nom: "S" },
        { azimut_deg: 0, nom: "N" },
      ],
    };
    const serveur = new Serveur({ "/api/v1/vent-depart": { charge: est } });
    serveur.installer();
    const utilisateur = userEvent.setup();
    render(<ConteneurDemander demande={demandeEssai()} />);
    await waitFor(() => expect(serveur.vers("/api/v1/vent-depart").length).toBe(1));

    expect(screen.getByText("Vent d'est à 31 km/h")).toBeTruthy();
    expect(screen.queryByText(/sud-ouest/)).toBeNull();

    await utilisateur.click(screen.getByRole("button", { name: "Selon le vent" }));
    // Le latéral d'un vent d'est : plein sud et plein nord, toujours deux.
    expect(screen.getByText("Vent latéral : S (180°) et N (0°)")).toBeTruthy();
    expect(screen.queryByText(/315|135/)).toBeNull();
  });
});

describe("l'envoi à POST /sorties ne porte jamais direction et un vent contraignant ensemble", () => {
  const AUJOURDHUI = "2026-09-16";

  function installer() {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
      "/api/v1/vent-depart": { charge: ventDepart() },
      "/api/v1/meteo": { charge: meteo() },
      "/api/v1/sorties": { charge: sortie() },
      "/api/v1/boucles": { charge: boucle() },
    });
    serveur.installer();
    return serveur;
  }

  function derniereRecherche(serveur: Serveur): Record<string, unknown> {
    const envois = serveur.vers("/api/v1/sorties");
    expect(envois.length, "aucune recherche n'a été envoyée").toBeGreaterThan(0);
    return envois[envois.length - 1].corps as Record<string, unknown>;
  }

  /** L'invariant que l'API fait respecter côté serveur (400 sinon) : jamais
   * les deux à la fois, et jamais un `vent` contraignant avec `direction`. */
  function verifierJamaisLesDeux(corps: Record<string, unknown>) {
    const contraint = corps.direction !== undefined;
    const ventContraignant = corps.vent !== undefined && corps.vent !== "peu-importe";
    expect(contraint && ventContraignant, JSON.stringify(corps)).toBe(false);
  }

  beforeEach(() => {
    // Pile 9 h : `heure_depart` (nul par défaut, voir `demande.ts`) se
    // résout sur cette horloge — la requête envoyée en dépend.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("« peu importe » : envoie vent=peu-importe, jamais de direction", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Chercher 3 parcours" }));

    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    const corps = derniereRecherche(serveur);
    verifierJamaisLesDeux(corps);
    expect(corps.vent).toBe("peu-importe");
    expect(corps.direction).toBeUndefined();
  });

  it("« ma direction » : envoie direction=<cardinal>, jamais un vent contraignant", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Ma direction" }));
    // Le secteur nord-est de la rose (`RoseDirections`), pas un bouton « NE »
    // — remplacé le 20/09/2026. Le nom accessible commence par « nord-est »,
    // suivi de ce que la rose sait (pluie, vent) : voir `libelleSecteur`.
    await utilisateur.click(await screen.findByRole("button", { name: /^nord-est/i }));
    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));

    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    const corps = derniereRecherche(serveur);
    verifierJamaisLesDeux(corps);
    expect(corps.direction).toBe("NE");
  });

  it("« selon le vent » : envoie vent=<préférence>, jamais de direction", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Selon le vent" }));
    await utilisateur.click(screen.getByRole("button", { name: "Vent latéral" }));
    await utilisateur.click(screen.getByRole("button", { name: "Chercher 3 parcours" }));

    await waitFor(() => expect(serveur.vers("/api/v1/sorties").length).toBe(1));
    const corps = derniereRecherche(serveur);
    verifierJamaisLesDeux(corps);
    expect(corps.vent).toBe("travers");
    expect(corps.direction).toBeUndefined();
  });
});

describe("Q47 — Endurance Z2 balaie l'horizon sans direction, comme « Ma séance »", () => {
  const AUJOURDHUI = "2026-09-16";

  function installer() {
    const serveur = new Serveur({
      "/api/v1/systeme": { charge: SYSTEME },
      "/api/v1/profil/zones": { charge: zones() },
      "/api/v1/profil": { charge: PROFIL },
      "/api/v1/seances/": { charge: SEANCE },
      "/api/v1/seances": { charge: SEMAINE },
      "/api/v1/vent-depart": { charge: ventDepart() },
      "/api/v1/meteo": { charge: meteo() },
      "/api/v1/boucles": { charge: boucle() },
    });
    serveur.installer();
    return serveur;
  }

  function derniereRecherche(serveur: Serveur): Record<string, unknown> {
    const envois = serveur.vers("/api/v1/boucles");
    expect(envois.length, "aucune recherche n'a été envoyée").toBeGreaterThan(0);
    return envois[envois.length - 1].corps as Record<string, unknown>;
  }

  beforeEach(() => {
    // Pile 9 h : `heure_depart` (nul par défaut, voir `demande.ts`) se
    // résout sur cette horloge — la requête envoyée en dépend.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(`${AUJOURDHUI}T09:00:00`));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("le bouton « Chercher » n'est plus grisé en Z2 sur « peu importe »", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Endurance Z2" }));

    const bouton = (await screen.findByRole("button", {
      name: /Chercher .* parcours/,
    })) as HTMLButtonElement;
    // Avant Q47, ce bouton restait grisé tant qu'aucune direction n'était
    // choisie en Z2 — exactement l'incohérence que le mainteneur a relevée.
    expect(bouton.disabled).toBe(false);

    await utilisateur.click(bouton);
    await waitFor(() => expect(serveur.vers("/api/v1/boucles").length).toBe(1));
    const corps = derniereRecherche(serveur);
    expect(corps.direction).toBeUndefined();
  });

  it("« Ma direction » en Z2 envoie toujours un azimut", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Endurance Z2" }));
    await utilisateur.click(screen.getByRole("button", { name: "Ma direction" }));
    await utilisateur.click(await screen.findByRole("button", { name: /^nord-est/i }));
    await utilisateur.click(screen.getByRole("button", { name: /Chercher .* parcours/ }));

    await waitFor(() => expect(serveur.vers("/api/v1/boucles").length).toBe(1));
    const corps = derniereRecherche(serveur);
    expect(corps.direction).toBe("NE");
  });

  it("« Selon le vent » reste grisé et indisponible en Z2 — /boucles n'a pas de champ vent", async () => {
    const serveur = installer();
    const utilisateur = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<App />);

    await utilisateur.click(await screen.findByRole("button", { name: "Demander" }));
    await utilisateur.click(await screen.findByRole("button", { name: "Endurance Z2" }));

    const selonLeVent = screen.getByRole("button", { name: "Selon le vent" }) as HTMLButtonElement;
    expect(selonLeVent.disabled).toBe(true);
    expect(screen.getByText(/pas encore disponible pour une sortie libre/)).toBeTruthy();
    // Et ce blocage-là ne se contourne pas silencieusement : aucune
    // recherche n'a été envoyée, et le serveur ne sert donc aucun /boucles.
    expect(serveur.vers("/api/v1/boucles").length).toBe(0);
  });

  it("l'écran des résultats affiche « toutes directions » sans planter (direction: null)", () => {
    // Trouvé en vérifiant contre les vrais services (Q47) : l'écran plantait
    // avec « Cannot read properties of null (reading 'trim') »,
    // `directionEnToutesLettres` supposant encore une direction toujours
    // présente. `demande.direction` vaut `null` quand le moteur a balayé.
    const reponse = boucle();
    reponse.donnees.demande = { ...reponse.donnees.demande, direction: null };
    render(<Boucles reponse={reponse} surRetour={() => undefined} />);
    expect(screen.getByText(/toutes directions/)).toBeTruthy();
  });
});

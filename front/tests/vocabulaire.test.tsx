/** Ce que l'écran dit au cycliste, et ce qu'il ne doit plus lui dire.
 *
 * Trois défauts trouvés en trois minutes par le mainteneur devant l'écran :
 * pas de vent sur les tracés, « au calme » jamais expliqué et amputé de sa
 * troisième catégorie, et un titre qui portait l'azimut et le rayon demandé
 * au traceur. Les tests d'ici gardent les trois — et surtout le principe
 * commun : **rien de ce qui s'affiche ne vient du vocabulaire du moteur**.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  directionEnToutesLettres,
  sourceDAdresse,
  titreDeBoucle,
  usageDeVelo,
  visibleEnKm,
} from "../src/api/formats";
import { LegendeVent } from "../src/composants/Carte";
import type { FlecheVent } from "../src/api/types";
import { PropositionDetail } from "../src/ecrans/Proposition";
import { sortie } from "./fixtures";

describe("le titre d'une boucle ne porte aucun paramètre du moteur", () => {
  it("rend la direction, jamais l'azimut ni le rayon demandé au traceur", () => {
    // `candidate.nom` valait « Boucle 115° 27.6 km » au-dessus d'une boucle
    // de 130,4 km : deux chiffres internes, dont un qui mentait de 100 km.
    const titre = titreDeBoucle(115, 1);
    expect(titre).toBe("Boucle au sud-est");
    expect(titre).not.toMatch(/\d/);
    expect(titre).not.toMatch(/°/);
  });

  it("retombe sur le numéro quand la direction est inconnue, sans inventer", () => {
    expect(titreDeBoucle(null, 3)).toBe("Boucle 3");
  });
});

describe("la direction demandée se lit en français", () => {
  it("traduit le code que le front a envoyé au moteur", () => {
    expect(directionEnToutesLettres("SE")).toBe("au sud-est");
    expect(directionEnToutesLettres("no")).toBe("au nord-ouest");
  });

  it("rend un azimut à la boussole la plus proche plutôt qu'en degrés", () => {
    expect(directionEnToutesLettres("155")).toBe("au sud-est");
  });

  it("laisse passer un libellé inconnu plutôt que de l'effacer", () => {
    // Même parti pris que `modelePhysique` : un mot brut vaut mieux qu'un
    // silence, parce qu'un silence ne se remarque pas.
    expect(directionEnToutesLettres("plein vent")).toBe("plein vent");
  });
});

describe("les valeurs d'énumération du cœur se disent en français", () => {
  it("nomme l'usage d'un vélo comme le formulaire le propose", () => {
    // Le cycliste cliquait « Chrono » et lisait « clm » trois secondes plus
    // tard, sur le récapitulatif de son propre choix.
    expect(usageDeVelo("clm")).toBe("Chrono");
    expect(usageDeVelo("route")).toBe("Route");
  });

  it("nomme le service de géocodage au lieu de son identifiant", () => {
    expect(sourceDAdresse("ban")).toBe("adresses officielles françaises");
    expect(sourceDAdresse("nominatim")).toBe("OpenStreetMap");
  });

  it("laisse passer une valeur que le front ne connaît pas", () => {
    expect(usageDeVelo("cyclocross")).toBe("cyclocross");
    expect(sourceDAdresse("photon")).toBe("photon");
  });
});

describe("un kilométrage ne s'affiche pas quand il s'arrondit à zéro", () => {
  it("cache ce qui vaut 0,0 une fois arrondi", () => {
    // Mesuré sur un vrai parcours : 0,04 km non classés donnaient
    // « 0,0 km qu'on ne sait pas classer », un zéro là où l'on voulait dire
    // quelque chose.
    expect(visibleEnKm(0)).toBe(false);
    expect(visibleEnKm(0.04)).toBe(false);
  });

  it("montre ce que la décimale affichée porte encore", () => {
    expect(visibleEnKm(0.05)).toBe(true);
    expect(visibleEnKm(0.6)).toBe(true);
  });
});

const fleche: FlecheVent = {
  pt: [0.5, 0.5],
  depuis_deg: 217.2,
  vent_kmh: 14,
  rafale_kmh: 24,
  relatif: "face",
};

describe("la légende du vent", () => {
  it("dit ce que les trois formes veulent dire, et d'où pointe la flèche", () => {
    render(<LegendeVent vents={[fleche]} />);
    expect(screen.getByText(/girouette/)).toBeDefined();
    expect(screen.getByText(/de face/)).toBeDefined();
    expect(screen.getByText(/rafale/)).toBeDefined();
  });

  it("distingue « pas de vent » de « vent non regardé » quand rien n'est dessiné", () => {
    // Une carte sans flèche se lisait aussi bien « le vent n'a pas été
    // regardé » que « il n'y a pas de vent » : l'ignorance ne doit jamais
    // passer pour un zéro (règle absolue 5).
    render(<LegendeVent vents={[]} seuilKmh={8} />);
    expect(screen.getByText(/sous les 8 km\/h/)).toBeDefined();
  });

  it("se passe du seuil plutôt que d'en inventer un quand l'API ne le donne pas", () => {
    render(<LegendeVent vents={[]} />);
    expect(screen.getByText(/très faible/)).toBeDefined();
    expect(screen.queryByText(/km\/h/)).toBeNull();
  });
});

describe("la sortie d'un écran de profondeur", () => {
  it("est en tête du détail, avant la carte et tout ce qui la suit", () => {
    // Le retour existait déjà, mais tout en bas : sous la carte, le profil,
    // les étapes, les bandeaux et le bouton d'envoi au compteur. Le
    // mainteneur ne l'a jamais vu, et sur un téléphone c'est équivalent à ne
    // pas en avoir. Ce test garde sa **place**, pas seulement son existence.
    const reponse = sortie();
    const { container } = render(
      <PropositionDetail reponse={reponse} numero={1} seance={null} surRetour={() => {}} />,
    );
    const premier = container.querySelector("section > *");
    expect(premier?.className).toContain("retour");
  });

  it("nomme le jour d'où l'on vient, au lieu de dire « Retour »", () => {
    // Revenir aux parcours du mercredi 16 n'est pas revenir à « Ma semaine ».
    render(
      <PropositionDetail reponse={sortie()} numero={1} seance={null} surRetour={() => {}} />,
    );
    expect(screen.getByText(/parcours du mercredi 16 septembre/)).toBeDefined();
  });

  it("accorde au singulier quand le cœur n'a rendu qu'un parcours", () => {
    render(
      <PropositionDetail
        reponse={sortie({ propositions: 1 })}
        numero={1}
        seance={null}
        surRetour={() => {}}
      />,
    );
    expect(screen.getByText(/Le parcours du mercredi 16 septembre/)).toBeDefined();
    expect(screen.queryByText(/Les 1 parcours/)).toBeNull();
  });

  it("ramène vraiment en arrière quand on la suit", () => {
    let revenu = false;
    render(
      <PropositionDetail
        reponse={sortie()}
        numero={1}
        seance={null}
        surRetour={() => {
          revenu = true;
        }}
      />,
    );
    screen.getByRole("button", { name: /parcours du mercredi 16/ }).click();
    expect(revenu).toBe(true);
  });
});

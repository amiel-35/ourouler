/** Aucune valeur affichée ne vient d'ailleurs que de l'API.
 *
 * C'est la panne la plus silencieuse d'un front : un chiffre de maquette
 * laissé dans le code passe toutes les relectures, et ment à chaque écran.
 *
 * Trois façons de la prendre, et elles se complètent :
 *
 * 1. **Deux jeux de données disjoints donnent deux affichages disjoints.**
 *    Une valeur figée dans le code apparaîtrait dans les deux.
 * 2. **Un champ absent n'affiche rien**, jamais un substitut.
 * 3. **Aucune valeur des maquettes** ne se retrouve écrite dans les sources.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Propositions } from "../src/ecrans/Propositions";
import { PropositionDetail } from "../src/ecrans/Proposition";
import { MaSemaine } from "../src/ecrans/MaSemaine";
import { SEANCE, SEMAINE, sortie } from "./fixtures";

const SOURCES = join(__dirname, "..", "src");

/** Les clés qui servent de jointure : les décaler casserait les liens. */
const CLES_DE_JOINTURE = new Set(["numero", "indice", "etape_idx"]);

/** Décale tous les nombres d'une charge, sauf ce qui sert à joindre. */
function decaler<T>(valeur: T, cle?: string): T {
  if (typeof valeur === "number") {
    if (cle !== undefined && CLES_DE_JOINTURE.has(cle)) return valeur;
    if (cle === "latitude" || cle === "longitude") return valeur;
    if (valeur === 0) return valeur;
    return (Math.round(valeur * 10_000 * 2.7183 + 7) / 10_000) as unknown as T;
  }
  if (Array.isArray(valeur)) return valeur.map((v) => decaler(v, cle)) as unknown as T;
  if (valeur !== null && typeof valeur === "object") {
    const sortie: Record<string, unknown> = {};
    for (const [nom, contenu] of Object.entries(valeur as Record<string, unknown>)) {
      sortie[nom] = decaler(contenu, nom);
    }
    return sortie as unknown as T;
  }
  return valeur;
}

/** Tous les nombres lisibles dans un rendu, sans les dates. */
function nombresAffiches(noeud: HTMLElement): Set<string> {
  let texte = noeud.textContent ?? "";
  texte = texte.replace(/\d{4}-\d{2}-\d{2}(T[\d:+-]+)?/g, " ");
  // Le séparateur de milliers du français est une espace insécable : on la
  // retire avant d'extraire, sinon « 1 234 » se lirait « 1 » puis « 234 ».
  for (let i = 0; i < 3; i += 1) {
    texte = texte.replace(/(\d)[  \s](\d{3})(?!\d)/g, "$1$2");
  }
  const trouves = texte.match(/\d+(?:[.,]\d+)?/g) ?? [];
  return new Set(trouves.map((n) => n.replace(",", ".")));
}

/**
 * Ce qui a le droit d'être identique dans les deux rendus, et pourquoi.
 *
 * - les **clés de jointure** (`numero`, `indice`, `etape_idx`) : les décaler
 *   casserait le lien entre une proposition et sa candidate ;
 * - les nombres contenus dans les **chaînes** de la réponse — une date, une
 *   heure de départ, un nom de boucle : `decaler` ne touche pas au texte, et
 *   ces nombres viennent quand même de l'API ;
 * - **zéro**, que `decaler` laisse tel quel exprès : « 0 mm de pluie » est
 *   une mesure, pas une absence ;
 * - **le pourcentage de pente lu sur `profil`** (`ProfilAltitude`, lot
 *   d'affordance du 20/09/2026) : c'est un RATIO entre deux nombres bruts du
 *   même tableau (dénivelé / distance), et `decaler` multiplie tout nombre
 *   par le même facteur avant d'y ajouter une constante qui s'annule dans
 *   toute soustraction — la pente calculée est donc mathématiquement
 *   invariante sous ce décalage précis, quelles que soient les données. Ce
 *   n'est pas un chiffre figé dans le code : la preuve, dans la mécanique
 *   même de `decaler`, pas une exception de confort.
 */
function tolerees(valeur: unknown, cle?: string, vues = new Set<string>()): Set<string> {
  vues.add("0");
  vues.add("0.0");
  if (typeof valeur === "number") {
    if (cle !== undefined && CLES_DE_JOINTURE.has(cle)) vues.add(String(valeur));
    return vues;
  }
  if (typeof valeur === "string") {
    for (const morceau of valeur.match(/\d+/g) ?? []) {
      vues.add(morceau);
      vues.add(String(Number(morceau)));
    }
    return vues;
  }
  if (
    cle === "profil" &&
    Array.isArray(valeur) &&
    valeur.every((p) => Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number"))
  ) {
    const points = valeur as [number, number][];
    for (let i = 0; i < points.length - 1; i += 1) {
      const [d, a] = points[i];
      const [dSuivant, aSuivant] = points[i + 1];
      const distanceSegment = dSuivant - d;
      if (distanceSegment <= 0) continue;
      const pente = Math.abs(((aSuivant - a) / distanceSegment) * 100);
      vues.add(String(Math.round(pente)));
    }
    return vues;
  }
  if (Array.isArray(valeur)) {
    for (const v of valeur) tolerees(v, cle, vues);
    return vues;
  }
  if (valeur !== null && typeof valeur === "object") {
    for (const [nom, contenu] of Object.entries(valeur as Record<string, unknown>)) {
      tolerees(contenu, nom, vues);
    }
  }
  return vues;
}

function rendus(reponse: ReturnType<typeof sortie>) {
  const a = render(
    <Propositions
      reponse={reponse}
      choisie={1}
      surChoix={() => undefined}
      surOuvrir={() => undefined}
      surRetour={() => undefined}
    />,
  );
  const nombres = nombresAffiches(a.container);
  a.unmount();
  return nombres;
}

describe("deux jeux de données disjoints", () => {
  it("donnent deux affichages disjoints, aux jointures près", () => {
    const original = sortie();
    const decale = decaler(sortie());
    const admises = tolerees(original);

    const premier = rendus(original);
    const second = rendus(decale);

    const communs = [...premier].filter((n) => second.has(n) && !admises.has(n));
    expect(communs, `valeurs identiques malgré des données différentes : ${communs}`).toEqual([]);
    expect(premier.size).toBeGreaterThan(6);
  });

  it("vaut aussi pour le détail d'une proposition", () => {
    const rendre = (reponse: ReturnType<typeof sortie>, seance: typeof SEANCE.donnees) => {
      const vue = render(
        <PropositionDetail
          reponse={reponse}
          numero={1}
          seance={seance}
          surRetour={() => undefined}
        />,
      );
      const nombres = nombresAffiches(vue.container);
      vue.unmount();
      return nombres;
    };
    const admises = tolerees({ a: sortie(), b: SEANCE });
    const premier = rendre(sortie(), SEANCE.donnees);
    const second = rendre(decaler(sortie()), decaler(SEANCE).donnees);
    const communs = [...premier].filter((n) => second.has(n) && !admises.has(n));
    expect(communs, `valeurs figées : ${communs}`).toEqual([]);
  });

  it("vaut aussi pour la semaine", () => {
    const rendre = (semaine: typeof SEMAINE, quand: string) => {
      const vue = render(
        <MaSemaine
          semaine={semaine.donnees}
          aujourdhui={quand}
          joursAvecParcours={[]}
          surGenerer={() => undefined}
          surVoir={() => undefined}
          surDeposer={() => undefined}
        />,
      );
      const nombres = nombresAffiches(vue.container);
      vue.unmount();
      return nombres;
    };
    // Les dates sont du texte : `decaler` ne les touche pas. On change donc
    // aussi le jour de référence, pour que « dans N jours » diffère aussi.
    const admises = tolerees(SEMAINE);
    const premier = rendre(SEMAINE, "2026-09-16");
    const second = rendre(decaler(SEMAINE), "2026-09-09");
    const communs = [...premier].filter((n) => second.has(n) && !admises.has(n));
    expect(communs, `valeurs figées : ${communs}`).toEqual([]);
  });
});

describe("un champ absent", () => {
  it("n'affiche rien plutôt qu'un substitut", () => {
    const creuse = sortie();
    for (const proposition of creuse.donnees.propositions) {
      proposition.densite_marqueurs_km = null;
      // Le compte de feux et stops vient de ces deux entiers depuis le
      // 17/09/2026, plus d'un produit avec la distance (C1) : c'est eux
      // qu'il faut vider pour vérifier que l'écran se tait.
      proposition.feux = null;
      proposition.stops = null;
      proposition.part_trafic = null;
      proposition.pluie_mm = null;
      proposition.distinction = null;
    }
    for (const candidate of creuse.donnees.candidates) {
      candidate.denivele_m = null;
    }
    const vue = render(
      <Propositions
        reponse={creuse}
        choisie={1}
        surChoix={() => undefined}
        surOuvrir={() => undefined}
        surRetour={() => undefined}
      />,
    );
    const texte = vue.container.textContent ?? "";
    expect(texte).not.toMatch(/m D\+/);
    expect(texte).not.toMatch(/feux et stops/);
    expect(texte).not.toMatch(/de trafic/);
    expect(texte).not.toMatch(/mm de pluie/);
    // Et surtout : pas de zéro de remplacement.
    expect(texte).not.toMatch(/0 m D\+/);
  });

  it("cache la moyenne compteur et l'estimation quand aucun vélo n'est enregistré", () => {
    const sansVelo = sortie();
    sansVelo.donnees.tenue = null;
    const vue = render(
      <PropositionDetail
        reponse={sansVelo}
        numero={1}
        seance={null}
        surRetour={() => undefined}
      />,
    );
    expect(vue.container.textContent).toMatch(/c'est une boucle d'endurance/);
  });
});

describe("les sources", () => {
  function fichiers(dossier: string): string[] {
    return readdirSync(dossier).flatMap((nom) => {
      const chemin = join(dossier, nom);
      if (statSync(chemin).isDirectory()) return fichiers(chemin);
      return /\.tsx?$/.test(nom) ? [chemin] : [];
    });
  }

  /** Les chiffres inventés des maquettes. Aucun n'a le droit d'être dans le code. */
  const VALEURS_DE_MAQUETTE = [
    "245", "147", "28.6", "56.2", "54.8", "17.0", "8.4", "312", "288", "196", "276",
    "1l0nlqjq3j1obdhg08rz5rfhx", "Pacé", "camille.ruiz", "Le gris", "Camille Ruiz",
  ];

  it("ne portent aucune valeur de maquette", () => {
    const fautifs: string[] = [];
    for (const chemin of fichiers(SOURCES)) {
      const contenu = readFileSync(chemin, "utf8");
      for (const valeur of VALEURS_DE_MAQUETTE) {
        if (contenu.includes(valeur)) fautifs.push(`${chemin} : « ${valeur} »`);
      }
    }
    expect(fautifs, fautifs.join("\n")).toEqual([]);
  });

  it("ne portent aucune coordonnée : le front ne connaît aucun lieu", () => {
    // Une latitude française écrite en dur dans une source serait une donnée
    // personnelle (règle absolue 1) et une valeur qui ne vient pas de l'API.
    const fautifs: string[] = [];
    for (const chemin of fichiers(SOURCES)) {
      const contenu = readFileSync(chemin, "utf8");
      for (const trouve of contenu.match(/\b4[1-9]\.\d{3,}\b/g) ?? []) {
        fautifs.push(`${chemin} : ${trouve}`);
      }
    }
    expect(fautifs, fautifs.join("\n")).toEqual([]);
  });
});

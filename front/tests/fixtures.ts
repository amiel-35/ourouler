/** Des données **entièrement inventées** (règle absolue 1).
 *
 * Aucune valeur d'ici ne vient de la configuration du mainteneur : ni la
 * commune, ni la FTP, ni le poids, ni le vélo, ni les coordonnées. Le point
 * de référence est celui de `config.example.toml` — 47,0 / −0,5 — choisi
 * parce qu'il est à plus de cinquante kilomètres de toute ville que
 * l'invariant de `tests/test_invariants.py` connaît.
 *
 * Les nombres sont volontairement **distinctifs** : c'est ce qui permet au
 * test de provenance d'affirmer qu'une valeur affichée vient bien de la
 * réponse et de nulle part ailleurs.
 */

import type {
  Arbitrage,
  Avertissement,
  Boucle,
  Budget,
  Cellule,
  Compteur,
  Ecartee,
  Enveloppe,
  Meteo,
  Profil,
  Seance,
  Semaine,
  Simple,
  Sortie,
  Systeme,
  VentDepart,
  Zones,
} from "../src/api/types";

export const LAT = 47.0;
export const LON = -0.5;

export const DEPART = { nom: "Sainte-Fictive", latitude: LAT, longitude: LON };

function trace(n: number, decalage = 0): { points: [number, number][]; profil: [number, number][] } {
  const points: [number, number][] = [];
  const profil: [number, number][] = [];
  for (let i = 0; i < n; i += 1) {
    points.push([LAT + i * 0.002 + decalage, LON + i * 0.003 + decalage]);
    profil.push([i * 500, 60 + (i % 5) * 7]);
  }
  return { points, profil };
}

export function budget(operation: string, source: "defaut" | "mesure" = "mesure"): Budget {
  return {
    operation,
    attendu_ms: 4321,
    source,
    n: source === "mesure" ? 7 : 0,
    median_ms: source === "mesure" ? 3210 : null,
  };
}

export const SYSTEME: Systeme = {
  proprietaire: "essai",
  version: "0.0.1-essai",
  capacites: { intervals: true, brouter: true, velos: ["Le vert"] },
  budgets: [budget("sortie"), budget("boucle"), budget("seance"), budget("seances")],
};

export const PROFIL: Simple<Profil> = {
  proprietaire: "essai",
  donnees: {
    depart: DEPART,
    cycliste: { masse_kg: 63.4, ftp_w: 211, prenom: "Alix", nom: "Fictif" },
    velos: [
      {
        nom: "Le vert",
        usage: "route",
        masse_kg: 9.3,
        cda_m2: null,
        crr: null,
        facteur_compteur: null,
      },
    ],
    seance: {
      position_zone: 0.317,
      puissance_endurance_pct: 0.616,
      vitesse_compteur: null,
    },
    historique_depuis: "2024-02-29",
    // Ce profil-ci est complet : l'assistant n'a plus rien à recommander.
    // Le champ existe depuis que le compte neuf a été trouvé bloqué sur
    // l'écran du jour (19/09/2026) — c'est lui qui l'y envoie.
    assistant_recommande: false,
    services: {
      intervals: { renseigne: true, athlete_id: "iFICTIF" },
      brouter: { renseigne: true, profil: "essai-profil" },
    },
  },
};

export function zones(options?: { facteurMesure?: boolean; horsBande?: boolean }): Simple<Zones> {
  return {
    proprietaire: "essai",
    donnees: {
      ftp_w: 211,
      position_zone: options?.horsBande ? -0.418 : 0.317,
      zone_endurance: 2,
      hors_bande: options?.horsBande ?? false,
      zones: [
        { numero: 1, bas_w: 0, haut_w: 116, puissance_w: null, ouverte: false, bas_pct: 0, haut_pct: 0.55 },
        { numero: 2, bas_w: 118, haut_w: 158, puissance_w: null, ouverte: false, bas_pct: 0.56, haut_pct: 0.75 },
        { numero: 3, bas_w: 160, haut_w: 190, puissance_w: null, ouverte: false, bas_pct: 0.76, haut_pct: 0.9 },
        { numero: 4, bas_w: 192, haut_w: 222, puissance_w: null, ouverte: false, bas_pct: 0.91, haut_pct: 1.05 },
        { numero: 5, bas_w: 224, haut_w: 253, puissance_w: null, ouverte: true, bas_pct: 1.06, haut_pct: 1.2 },
      ],
      valeurs_liees: {
        velo: "Le vert",
        modele_physique: "modele-invente",
        position_zone: options?.horsBande ? -0.418 : 0.317,
        puissance_endurance_w: 130.7,
        puissance_endurance_pct: 0.616,
        vitesse_a_plat_kmh: 26.3,
        moyenne_compteur_kmh: 21.9,
        facteur_compteur: 0.833,
        facteur_mesure: options?.facteurMesure ?? false,
        hors_bande: options?.horsBande ?? false,
      },
    },
  };
}

/**
 * T1 : ce que `GET /profil/intervals` rendrait pour un profil Intervals
 * rempli — jamais un jeton ni un compte réel, une FTP et un poids inventés.
 */
export function profilIntervals(options?: {
  ftp_w?: number | null;
  masse_kg?: number | null;
}): Simple<{ ftp_w: number | null; masse_kg: number | null }> {
  return {
    proprietaire: "essai",
    donnees: {
      ftp_w: options?.ftp_w === undefined ? 235 : options.ftp_w,
      masse_kg: options?.masse_kg === undefined ? 71.4 : options.masse_kg,
    },
  };
}

/**
 * T4/T5 : ce que `POST /profil/ftp/apercu` ou `GET /profil/ftp/generique`
 * rendraient — même forme que `zones()`, avec une FTP distinctive pour
 * vérifier qu'elle se propage bien jusqu'au récapitulatif.
 */
export function apercuFtp(ftp_w: number): Simple<Zones> {
  const base = zones();
  return { ...base, donnees: { ...base.donnees, ftp_w } };
}

/**
 * Le second temps de sortie et son facteur (18/09/2026, décision « les 2
 * valeurs et une explication »). `provenance` inventée et distinctive :
 * 0,872 ne se retrouve nulle part ailleurs dans ces fixtures.
 *
 * `fourchette` (L9.1, 25/09/2026) : la fourchette du porte à porte,
 * mesurée sur les sorties du vélo (valeurs inventées, 41 sorties) ou la
 * convention du serveur.
 */
export const FOURCHETTE_MESUREE = { bas: 1.03, mediane: 1.06, haut: 1.08, n: 83 };
export const FOURCHETTE_CONVENTION = { bas: 1.02, mediane: 1.06, haut: 1.14, n: 0 };

export function compteur(options?: {
  provenance?: "mesure" | "suppose";
  fourchette?: "mesure" | "defaut";
}): Compteur {
  const fourchette = options?.fourchette ?? "mesure";
  const valeurs = fourchette === "mesure" ? FOURCHETTE_MESUREE : FOURCHETTE_CONVENTION;
  return {
    velo: "Le vert",
    moyenne_compteur_kmh: 24.6,
    facteur_compteur: 0.872,
    facteur_provenance: options?.provenance ?? "mesure",
    porte_a_porte: { ...valeurs, provenance: fourchette },
  };
}

/** Le porte à porte d'une candidate, tel que le serveur le calcule : le temps
 * sans arrêt multiplié par la fourchette. `null` partout sans vélo. */
function porteAPorte(mouvementS: number, fourchette: "mesure" | "defaut" | null) {
  if (fourchette === null) {
    return {
      temps_ecoule_s: null,
      temps_ecoule_bas_s: null,
      temps_ecoule_haut_s: null,
      temps_ecoule_source: null,
    };
  }
  const f = fourchette === "mesure" ? FOURCHETTE_MESUREE : FOURCHETTE_CONVENTION;
  return {
    temps_ecoule_s: Math.round(mouvementS * f.mediane),
    temps_ecoule_bas_s: Math.round(mouvementS * f.bas),
    temps_ecoule_haut_s: Math.round(mouvementS * f.haut),
    temps_ecoule_source: fourchette,
  };
}

/**
 * D'où vient le vent au départ, et ce que chaque préférence imposerait
 * (Q44). Les azimuts « depart-dos » et « retour-dos » sont bien opposés
 * (45° / 225°), et le latéral en porte deux, opposés entre eux (315° / 135°)
 * — exactement ce que Q44 demande de vérifier.
 */
export function ventDepart(options?: {
  posee?: boolean;
  motif?: string | null;
}): Enveloppe<VentDepart> {
  const posee = options?.posee ?? true;
  return {
    proprietaire: "essai",
    donnees: {
      jour: "2026-09-18",
      depart: "2026-09-18T09:00:00",
      posee,
      motif: posee ? null : (options?.motif ?? "vent en dessous du seuil (motif inventé)"),
      vent_kmh: posee ? 22.4 : null,
      vent_depuis_deg: posee ? 225.0 : null,
      vent_depuis_nom: posee ? "SO" : null,
      seuil_kmh: 8.0,
      horizon_jours: 3,
      choix: ["peu-importe", "retour-dos", "depart-dos", "travers"],
      azimuts_par_choix: posee
        ? {
            "peu-importe": [],
            "retour-dos": [{ azimut_deg: 225.0, nom: "SO" }],
            "depart-dos": [{ azimut_deg: 45.0, nom: "NE" }],
            travers: [
              { azimut_deg: 315.0, nom: "NO" },
              { azimut_deg: 135.0, nom: "SE" },
            ],
          }
        : { "peu-importe": [], "retour-dos": [], "depart-dos": [], travers: [] },
    },
    avertissements: [],
    duree_ms: 89,
    budget: budget("vent-depart"),
  };
}

/**
 * `GET /meteo` : huit directions, deux couronnes chacune (15 et 25 km),
 * plus le point « ici » — que le cœur inclut toujours et que
 * `meteoRose.directionsDepuisCellules` doit ignorer, jamais une neuvième
 * direction.
 *
 * Les chiffres reprennent **ceux de la proposition retenue** le 19/09/2026
 * (`front/directions/suisse-vivante.html`, la table accessible de la rose) :
 * pas une coïncidence, la continuité entre la maquette qui a fait choisir
 * cette direction et la fixture qui la teste. Toute la pluie est posée sur
 * la couronne des 15 km ; celle des 25 km reste sèche et en accord partout
 * — c'est ce qui permet à un test de vérifier le **cumul** (`niveauPluie`
 * lit la somme des deux couronnes, pas une seule) sans calcul caché.
 *
 * `vent_relatif` est posé **à la main**, cohérent avec `vent_depuis_deg` et
 * l'azimut de chaque direction (vérifiable avec la règle des ±45° de
 * `meteo.rapport.vent_relatif`) — mais rien n'oblige un test à le garder
 * cohérent : c'est le point exact de `tests/rose_directions.test.tsx`, qui
 * pose une valeur volontairement incohérente pour prouver que le front lit
 * ce champ, jamais ne le recalcule.
 */
export function meteo(options?: {
  /** Remplace entièrement les cellules par défaut — pour un cas dégradé
   * (une direction absente, un vent inconnu…) sans reconstruire la table. */
  cellules?: Cellule[];
  meilleureDirection?: { nom: string; motif: string } | null;
}): Enveloppe<Meteo> {
  const parDirection: Record<
    string,
    { pluie: number; secondAvis: number; confiance: string; ventKmh: number; ventDepuisDeg: number; relatif: string }
  > = {
    N: { pluie: 0.0, secondAvis: 0.0, confiance: "accord", ventKmh: 14, ventDepuisDeg: 90, relatif: "travers" },
    NE: { pluie: 0.2, secondAvis: 0.2, confiance: "accord", ventKmh: 11, ventDepuisDeg: 315, relatif: "travers" },
    // Le seul désaccord de la fixture : AROME annonce 1,4 mm, le second avis
    // n'en voit pas — exactement le cas que la légende de la rose illustre.
    E: { pluie: 1.4, secondAvis: 0.0, confiance: "desaccord", ventKmh: 9, ventDepuisDeg: 180, relatif: "travers" },
    SE: { pluie: 3.8, secondAvis: 3.6, confiance: "accord", ventKmh: 13, ventDepuisDeg: 135, relatif: "face" },
    S: { pluie: 2.1, secondAvis: 2.0, confiance: "accord", ventKmh: 18, ventDepuisDeg: 200, relatif: "face" },
    SO: { pluie: 0.6, secondAvis: 0.5, confiance: "accord", ventKmh: 22, ventDepuisDeg: 225, relatif: "face" },
    O: { pluie: 0.0, secondAvis: 0.0, confiance: "accord", ventKmh: 16, ventDepuisDeg: 270, relatif: "face" },
    // La direction recommandée : sèche sur tout l'horizon, vent de dos.
    NO: { pluie: 0.0, secondAvis: 0.0, confiance: "accord", ventKmh: 12, ventDepuisDeg: 135, relatif: "dos" },
  };
  const cellules: Cellule[] =
    options?.cellules ??
    [
      // Le point de départ : jamais une direction, doit être ignoré par
      // `directionsDepuisCellules`.
      {
        direction: "ici",
        distance_km: 0,
        t: "2026-09-18T07:00:00Z",
        pluie_mm: 0,
        pluie_second_avis_mm: 0,
        vent_kmh: 12,
        vent_depuis_deg: 135,
        vent_relatif: null,
        ressenti_c: 14,
        confiance: "accord",
      },
      ...Object.entries(parDirection).flatMap(([direction, valeurs]) => [
        {
          direction,
          distance_km: 15,
          t: "2026-09-18T07:00:00Z",
          pluie_mm: valeurs.pluie,
          pluie_second_avis_mm: valeurs.secondAvis,
          vent_kmh: valeurs.ventKmh,
          vent_depuis_deg: valeurs.ventDepuisDeg,
          vent_relatif: valeurs.relatif,
          ressenti_c: 14,
          confiance: valeurs.confiance,
        },
        {
          direction,
          distance_km: 25,
          t: "2026-09-18T08:00:00Z",
          pluie_mm: 0,
          pluie_second_avis_mm: 0,
          vent_kmh: valeurs.ventKmh - 2,
          vent_depuis_deg: valeurs.ventDepuisDeg,
          vent_relatif: valeurs.relatif,
          ressenti_c: 13,
          confiance: "accord",
        },
      ]),
    ];
  return {
    proprietaire: "essai",
    donnees: {
      depart: DEPART,
      debut: "2026-09-18T07:00:00Z",
      horizon_h: 3,
      modele: "modele-invente",
      second_avis: "second-avis-invente",
      meilleure_direction:
        options?.meilleureDirection !== undefined
          ? options.meilleureDirection
          : { nom: "NO", motif: "sec sur tout l'horizon, vent de dos à l'aller (motif inventé)" },
      cellules,
    },
    avertissements: [],
    duree_ms: 184,
    budget: budget("meteo"),
  };
}

export const SEANCE: Enveloppe<Seance> = {
  proprietaire: "essai",
  donnees: {
    jour: "2026-09-16",
    nom: "Séance inventée — trois blocs",
    duree_s: 4380,
    n_blocs: 3,
    distance_estimee_m: 31_400,
    avertissements: [],
    meta: { ftp_w: 211, source: "essai" },
    etapes: [
      {
        indice: 0,
        type: "echauffement",
        libelle: "Montée en température",
        duree_s: 900,
        elastique: true,
        puissance_min_w: 94,
        puissance_max_w: 137,
        puissance_cible_w: 116,
        vitesse_kmh: 24.1,
        longueur_m: 6025,
      },
      {
        indice: 1,
        type: "bloc",
        libelle: "Bloc inventé n° 1",
        duree_s: 1200,
        elastique: false,
        puissance_min_w: 183,
        puissance_max_w: 183,
        puissance_cible_w: 183,
        vitesse_kmh: 31.7,
        longueur_m: 10_567,
      },
      {
        indice: 2,
        type: "recuperation",
        libelle: "Souffler",
        duree_s: 480,
        elastique: false,
        puissance_min_w: 121,
        puissance_max_w: 121,
        puissance_cible_w: 121,
        vitesse_kmh: 25.2,
        longueur_m: 3360,
      },
      {
        indice: 3,
        type: "calme",
        libelle: "Rentrer doucement",
        duree_s: 1800,
        elastique: true,
        puissance_min_w: 88,
        puissance_max_w: 105,
        puissance_cible_w: 97,
        vitesse_kmh: 22.8,
        longueur_m: 11_400,
      },
    ],
  },
  avertissements: [],
  duree_ms: 137,
  budget: budget("seance"),
};

export const SEMAINE: Enveloppe<Semaine> = {
  proprietaire: "essai",
  donnees: {
    depuis: "2026-09-16",
    jusqua: "2026-09-22",
    jours: [
      {
        jour: "2026-09-16",
        seance: {
          jour: "2026-09-16",
          nom: "Séance inventée — trois blocs",
          duree_s: 4380,
          n_blocs: 3,
          distance_estimee_m: 31_400,
        },
      },
      { jour: "2026-09-17", seance: null },
      {
        jour: "2026-09-21",
        seance: {
          jour: "2026-09-21",
          nom: "Longue inventée",
          duree_s: 9900,
          n_blocs: 0,
          distance_estimee_m: 74_300,
        },
      },
    ],
  },
  avertissements: [],
  duree_ms: 211,
  budget: budget("seances"),
};

/** Une sortie à trois propositions, toutes les valeurs inventées. */
/**
 * L'arbitrage tel que le cœur le rendrait, pour `combien` retenues.
 *
 * Avec `ecartee`, une quatrième candidate partage 55 % de ses routes avec la
 * n° 1 : c'est le cas exact du sud du départ du mainteneur, celui où quatre
 * candidates ne rendent que deux propositions. Les chiffres sont inventés
 * mais **cohérents** — la seule paire au-dessus du seuil est bien celle qui
 * porte le verdict.
 */
function arbitrageDe(combien: number, ecartee: boolean): Arbitrage {
  const total = combien + (ecartee ? 1 : 0);
  const paires = [];
  for (let a = 1; a <= total; a += 1) {
    for (let b = a + 1; b <= total; b += 1) {
      const part = ecartee && a === 1 && b === total ? 0.55 : 0.02 + (a + b) / 100;
      paires.push({ a, b, recouvrement: part, au_dessus_du_seuil: part > 0.3 });
    }
  }
  const candidates = Array.from({ length: total }, (_, i) => {
    const numero = i + 1;
    if (ecartee && numero === total) {
      return {
        numero,
        sort: "trop_proche",
        recouvrement_max: 0.55,
        contre_numero: 1,
        motif: "écartée : 55% des mêmes routes que la n° 1, au-dessus du seuil de 30%",
      };
    }
    return {
      numero,
      sort: "retenue",
      recouvrement_max: 0.07,
      contre_numero: numero === 1 ? 2 : 1,
      motif: "retenue — au plus 7% des mêmes routes que la n° 1, sous le seuil de 30%",
    };
  });
  return {
    seuil_recouvrement: 0.3,
    candidates,
    paires,
    essais: ecartee
      ? { taille: 3, essayes: 3, valides: 0, refuses_par_une_paire: 2 }
      : { taille: 3, essayes: 1, valides: 1, refuses_par_une_paire: 0 },
    phrase: ecartee
      ? "3 groupe(s) de trois contenant la première du tri ont été essayés ; 0 tiennent " +
        "sous les 30% de routes communes. 2 des refusés ne tombent que sur une seule " +
        "paire trop ressemblante : une paire suffit à disqualifier un groupe entier, " +
        "quelle que soit la moyenne des autres."
      : "1 groupe(s) de trois contenant la première du tri ont été essayés ; 1 tiennent " +
        "sous les 30% de routes communes.",
  };
}

export function sortie(options?: {
  propositions?: number;
  motif?: string | null;
  /** La phrase de Q45 : aucune proposition ne se détache des autres. */
  equivalence?: string | null;
  /** Trois propositions sans la moindre phrase — le jour où rien ne change. */
  muettes?: boolean;
  avertissements?: Avertissement[];
  /** Fait servir des boucles hors de la tolérance de distance (Q41 d).
   *
   * Par défaut les candidates tiennent dans les 10 % : 41,3 km visés, 42,7 /
   * 44,1 / 39,6 km rendus. C'est le cas normal, et le bandeau d'élargissement
   * ne doit alors apparaître nulle part — ce que garde un test.
   */
  horsTolerance?: boolean;
  /**
   * Le cas qui a motivé le lot F2.4 : quatre candidates, **une** paire à
   * 55 %, et deux propositions seulement. Ajoute une quatrième candidate
   * écartée au contraste et l'arbitrage qui l'explique.
   *
   * Les pourcentages sont ceux que l'API rendrait ; aucun n'est recalculé par
   * l'écran, et un test le garde.
   */
  ecarteeAuContraste?: boolean;
  /** Une candidate tombée **avant** le contraste, avec ou sans tracé. */
  ecarteesAvant?: Ecartee[];
  /**
   * Le second temps de sortie (18/09/2026). `null` : la configuration ne
   * porte aucun vélo — aucun écran ne doit alors montrer de second chiffre,
   * pas même un tiret. Par défaut, un facteur mesuré.
   */
  compteur?: "mesure" | "suppose" | null;
  /** D'où vient la fourchette du porte à porte (L9.1) : mesurée par défaut. */
  fourchette?: "mesure" | "defaut";
}): Enveloppe<Sortie> {
  const combien = options?.propositions ?? 3;
  const axes = ["ville", "pluie", "vent"];
  const distinctions = [
    "six carrefours de moins que les deux autres",
    "passe au large de l'averse du milieu de matinée",
    "rentre avec le vent dans le dos sur la fin",
  ];
  // 41,3 km visés. Sans `horsTolerance`, les trois tiennent dans les 10 %.
  // Avec, elles sont franchement plus courtes : 34,0 km, soit −17,7 %, qui
  // est l'ordre de grandeur mesuré chez le mainteneur (6 h demandées, 5 h
  // servies). Un palier de 10 % suffit à les accepter, la tolérance atteinte
  // vaut alors ±20 %.
  const distances = options?.horsTolerance ? [34.0, 34.9, 33.2] : [42.7, 44.1, 39.6];
  const denivele = [317, 268, 401];
  const densites = [0.234, 0.703, 0.126];
  // Les entiers que l'API sérialise depuis le 17/09/2026 (C1). Ils ne sont
  // volontairement **pas** le produit `densité × distance` : le front ne doit
  // plus retrouver ce chiffre par un calcul, et une fixture cohérente avec
  // l'ancien produit laisserait passer un retour en arrière sans le voir.
  const feux = [11, 34, 6];
  const stops = [7, 19, 3];
  return {
    proprietaire: "essai",
    donnees: {
      jour: "2026-09-16",
      seance: {
        nom: "Séance inventée — trois blocs",
        duree_s: 4380,
        n_etapes: 4,
        n_blocs: 3,
      },
      demande: {
        distance_km: 41.3,
        distance_source: "estimée pour l'essai",
        direction: null,
        candidates: combien,
        depart: "2026-09-16T08:15:00+02:00",
        lieu_depart: DEPART,
        velo: "Le vert",
      },
      compteur:
        options?.compteur === null
          ? null
          : compteur({ provenance: options?.compteur ?? "mesure", fourchette: options?.fourchette }),
      modele_physique: "modele-invente (Le vert)",
      modele_meteo: { utilise: "modele-meteo-invente", repli: false },
      meteo_absente: null,
      generation: "c".repeat(32),
      // Q40 (g) : aucun GPX n'est écrit à la génération — la clé du cœur
      // reste nulle, et chaque proposition porte la sienne.
      gpx: null,
      carte: null,
      tenue: {
        categorie_temp: "frais-invente",
        categorie_humidite: "sec-invente",
        base: ["maillot inventé", "gants inventés"],
        a_emporter: [],
        a_enlever: [],
        motifs: ["au départ : 13,7 °C ressentis (valeur inventée)"],
      },
      question_vent: {
        posee: true,
        motif: null,
        vent_kmh: 17.4,
        vent_depuis_deg: 213,
        seuil_kmh: 8,
        horizon_jours: 3,
        reponse: "peu-importe",
        choix: ["peu-importe", "retour-dos", "depart-dos", "travers"],
      },
      motif_deux_propositions: options?.motif ?? null,
      motif_equivalence: options?.equivalence ?? null,
      propositions: Array.from({ length: combien }, (_, i) => ({
        numero: i + 1,
        retenue: i === 0,
        // Depuis Q43, une proposition peut n'avoir aucune phrase : son tracé
        // la distingue, pas un axe mesuré. `muettes` fabrique ce jour-là.
        distinction: options?.muettes ? null : distinctions[i],
        axe_distinctif: options?.muettes ? null : axes[i],
        duree_s: 4512 + i * 97,
        depassement_seance_s: 132,
        demi_tours: 0,
        pluie_mm: i === 1 ? 0.4 : 0,
        densite_marqueurs_km: densites[i],
        feux: feux[i],
        stops: stops[i],
        part_trafic: 0.0713 + i / 100,
        orientation_vent: ["travers", "depart-dos", "retour-dos"][i],
        note_terrain: 0,
        recouvrement_max_avec: null,
        gpx: {
          nom: `sortie_20260916_n${i + 1}.gpx`,
          url: `/api/v1/sorties/${"c".repeat(32)}/propositions/${i + 1}/gpx`,
        },
      })),
      ecartees: options?.ecarteesAvant ?? [],
      arbitrage: arbitrageDe(combien, Boolean(options?.ecarteeAuContraste)),
      candidates: Array.from({ length: combien + (options?.ecarteeAuContraste ? 1 : 0) }, (_, i) => ({
        numero: i + 1,
        retenue: i === 0,
        nom: `Boucle inventée ${i + 1}`,
        distance_km: distances[i % distances.length],
        denivele_m: denivele[i % denivele.length],
        azimut_deg: 47 + i,
        ecart_relatif: (distances[i % distances.length] - 41.3) / 41.3,
        hors_tolerance: Boolean(options?.horsTolerance),
        elargissement: options?.horsTolerance ? 0.1 : 0,
        tolerance_distance: 0.1,
        // Le second temps (18/09/2026) : `temps_estime_s` est le temps de
        // mouvement — la même valeur que `duree_s` de la proposition et que
        // `placement.duree_totale_s` ci-dessous, ce sont trois vues du même
        // chiffre. `temps_ecoule_*` y ajoutent les arrêts, en fourchette ;
        // `null` quand `compteur` (sur la réponse) l'est aussi.
        temps_estime_s: 4512 + i * 97,
        temps_source: "modele" as const,
        ...porteAPorte(
          4512 + i * 97,
          options?.compteur === null ? null : (options?.fourchette ?? "mesure"),
        ),
        // `km_non_classe` : la troisième catégorie de trafic, ajoutée en même
        // temps que l'élargissement de tolérance par un autre agent. Les deux
        // sont vrais, la fixture porte les deux.
        couts: {
          km_trafic: 3.1,
          km_calme: 36.2,
          km_non_classe: 0,
          km_non_revetu: 0,
          score: 19.4,
          sens: "horaire",
        },
        meteo: {
          pluie_cumulee_mm: i === 1 ? 0.4 : 0,
          minutes_pluie: 0,
          part_vent_face: 0.264,
          ressenti_min_c: 13.7,
          confiance: "accord",
        },
        placement: {
          note_totale: 0.017,
          note_terrain: 0.011,
          decalage_z2_s: 240,
          duree_totale_s: 4512 + i * 97,
          distance_totale_m: distances[i] * 1000,
          denivele_parcours_m: denivele[i],
          blocs_bien_places: 1,
          demi_tours: 0,
          avertissements: [],
          informations: [],
          emplacements: [
            {
              etape_idx: 0,
              debut_m: 0,
              debut_parcouru_m: 0,
              longueur_m: 6025,
              demi_tour: false,
              note: null,
              motifs: null,
              pente_moyenne: null,
              pente_max: null,
              carrefours: null,
            },
            {
              etape_idx: 1,
              debut_m: 6025,
              debut_parcouru_m: 6025,
              longueur_m: 10_567,
              demi_tour: false,
              note: 0.011,
              motifs: ["plat, un seul carrefour (motif inventé)"],
              pente_moyenne: 0.003,
              pente_max: 0.021,
              carrefours: 1,
            },
            {
              etape_idx: 2,
              debut_m: 16_592,
              debut_parcouru_m: 16_592,
              longueur_m: 3360,
              demi_tour: false,
              note: null,
              motifs: null,
              pente_moyenne: null,
              pente_max: null,
              carrefours: null,
            },
            {
              etape_idx: 3,
              debut_m: 19_952,
              debut_parcouru_m: 19_952,
              longueur_m: 11_400,
              demi_tour: false,
              note: null,
              motifs: null,
              pente_moyenne: null,
              pente_max: null,
              carrefours: null,
            },
          ],
        },
        trace: { ...trace(40, i * 0.01), simplification: {
          tolerance_m: 5,
          points_origine: 400,
          points_rendus: 40,
          ecart_max_m: 4.2,
        } },
      })),
    },
    avertissements: options?.avertissements ?? [],
    duree_ms: 2718,
    budget: budget("sortie"),
  };
}

export function boucle(options?: {
  /** Le second temps (18/09/2026). `null` : pas de vélo enregistré — pas de
   * second chiffre à l'écran, pas même un tiret. Par défaut, un facteur
   * mesuré. */
  compteur?: "mesure" | "suppose" | null;
  /** D'où vient la fourchette du porte à porte (L9.1) : mesurée par défaut. */
  fourchette?: "mesure" | "defaut";
}): Enveloppe<Boucle> {
  return {
    proprietaire: "essai",
    donnees: {
      depart: { ...DEPART, heure: "2026-09-16T08:15:00+02:00" },
      demande: { distance_km: 41.3, direction: "NE", candidates: 2 },
      compteur:
        options?.compteur === null
          ? null
          : compteur({ provenance: options?.compteur ?? "mesure", fourchette: options?.fourchette }),
      meteo_absente: null,
      gpx: { id: "b".repeat(32), nom: "boucle.gpx", url: "/api/v1/fichiers/" + "b".repeat(32) },
      candidates: [
        {
          numero: 1,
          retenue: true,
          nom: "Boucle libre inventée",
          distance_km: 40.8,
          denivele_m: 289,
          azimut_deg: 46,
          temps_estime_s: 5460,
          temps_source: "modele",
          ...porteAPorte(5460, options?.compteur === null ? null : (options?.fourchette ?? "mesure")),
          // 2,4 + 38,4 ne font pas les 40,8 km de la boucle : les 3,2 qui
          // manquent sont sur des voies que la carte ne classe pas. C'est
          // exactement le cas que l'écran taisait, et une fixture qui le
          // mettrait à zéro ne testerait jamais rien.
          couts: {
            km_trafic: 2.4,
            km_calme: 35.2,
            km_non_classe: 3.2,
            km_non_revetu: 0,
            score: 17.1,
            sens: "horaire",
          },
          meteo: {
            pluie_cumulee_mm: 0,
            minutes_pluie: 0,
            part_vent_face: 0.311,
            ressenti_min_c: 12.2,
            confiance: "accord",
          },
          trace: { ...trace(30), simplification: {
            tolerance_m: 5,
            points_origine: 300,
            points_rendus: 30,
            ecart_max_m: 3.9,
          } },
        },
      ],
    },
    avertissements: [],
    duree_ms: 1904,
    budget: budget("boucle"),
  };
}

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
  Avertissement,
  Boucle,
  Budget,
  Enveloppe,
  Profil,
  Seance,
  Semaine,
  Simple,
  Sortie,
  Systeme,
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
export function sortie(options?: {
  propositions?: number;
  motif?: string | null;
  avertissements?: Avertissement[];
}): Enveloppe<Sortie> {
  const combien = options?.propositions ?? 3;
  const axes = ["ville", "pluie", "vent"];
  const distinctions = [
    "six carrefours de moins que les deux autres",
    "passe au large de l'averse du milieu de matinée",
    "rentre avec le vent dans le dos sur la fin",
  ];
  const distances = [42.7, 44.1, 39.6];
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
      propositions: Array.from({ length: combien }, (_, i) => ({
        numero: i + 1,
        retenue: i === 0,
        distinction: distinctions[i],
        axe_distinctif: axes[i],
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
      candidates: Array.from({ length: combien }, (_, i) => ({
        numero: i + 1,
        retenue: i === 0,
        nom: `Boucle inventée ${i + 1}`,
        distance_km: distances[i],
        denivele_m: denivele[i],
        azimut_deg: 47 + i,
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

export function boucle(): Enveloppe<Boucle> {
  return {
    proprietaire: "essai",
    donnees: {
      depart: { ...DEPART, heure: "2026-09-16T08:15:00+02:00" },
      demande: { distance_km: 41.3, direction: "NE", candidates: 2 },
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

/** Le contrat de l'API, tel qu'il est écrit dans `docs/ux/api_contrat.md`.
 *
 * Ces types décrivent **ce que l'API rend**, pas ce que le front voudrait
 * recevoir. Quand un champ manque au contrat, il manque ici aussi : c'est la
 * seule façon que le compilateur ait de refuser un écran qui afficherait une
 * valeur inventée (doctrine §10.2, règle absolue 5).
 *
 * Tout ce qui peut valoir `null` le vaut ici. Le cœur distingue « zéro » de
 * « on ne sait pas », et l'interface doit pouvoir le distinguer aussi.
 */

/**
 * Un avertissement de l'API : **un code qu'on teste, un message qu'on affiche**.
 *
 * Le code vient de `api/erreurs.CODES_AVERTISSEMENT`, publié dans
 * `/openapi.json`. Il n'a pas toujours existé : jusqu'au 17/09/2026,
 * `avertissements` était une liste de chaînes, et le bandeau « Pas de météo »
 * se décidait en cherchant le mot « météo » dans une prose que
 * `docs/ux/api_contrat.md` déclare reformulable. Aucun écran ne lit plus une
 * phrase pour en déduire un état.
 *
 * `code` vaut `"autre"` pour ce que le catalogue ne nomme pas encore : on
 * affiche alors le message sans rien en conclure.
 */
export interface Avertissement {
  code: string;
  message: string;
}

/** L'enveloppe de toute route qui calcule. */
export interface Enveloppe<T> {
  proprietaire: string;
  donnees: T;
  avertissements: Avertissement[];
  duree_ms: number;
  budget: Budget;
}

/** L'enveloppe des routes qui ne calculent pas (profil, zones, système). */
export interface Simple<T> {
  proprietaire: string;
  donnees: T;
}

/** Combien de temps une opération prend **ici**, et d'où vient le chiffre. */
export interface Budget {
  operation: string;
  attendu_ms: number;
  /** `defaut` tant que ce serveur n'a rien mesuré, `mesure` ensuite. */
  source: "defaut" | "mesure";
  n: number;
  median_ms: number | null;
}

export interface Systeme {
  proprietaire: string;
  version: string;
  capacites: { intervals: boolean; brouter: boolean; velos: string[] };
  budgets: Budget[];
}

/** Une panne, telle que l'API la rend. Le **code** est le contrat. */
export interface Panne {
  code: string;
  message: string;
  service: string | null;
  details: Record<string, unknown>;
}

// --- profil -------------------------------------------------------------

export interface PointDepart {
  nom: string;
  latitude: number;
  longitude: number;
}

export interface VeloProfil {
  nom: string;
  usage: string;
  masse_kg: number;
  cda_m2: number | null;
  crr: number | null;
  facteur_compteur: number | null;
  capteur_puissance?: string | null;
}

export interface Profil {
  depart: PointDepart;
  /** `prenom`/`nom` : identité du compte, obligatoire depuis l'assistant (Q36,
   * 17/09/2026), mais peuvent revenir vides pour un profil créé avant ce lot —
   * jamais absents. Aucun calcul ne s'en sert aujourd'hui ; l'usage prévu est
   * le compte multi-utilisateurs du lot F3 (e-mail d'invitation, affichage). */
  cycliste: { masse_kg: number; ftp_w: number; prenom: string; nom: string };
  velos: VeloProfil[];
  seance: {
    position_zone: number;
    puissance_endurance_pct: number;
    vitesse_compteur: ValeursLiees | null;
  };
  historique_depuis: string;
  services: {
    intervals: { renseigne: boolean; athlete_id: string };
    brouter: { renseigne: boolean; profil: string | null };
  };
}

/** Les trois valeurs liées de l'écran de FTP (décisions 7 et 8). */
export interface ValeursLiees {
  velo: string;
  modele_physique: string;
  position_zone: number;
  puissance_endurance_w: number;
  puissance_endurance_pct: number;
  vitesse_a_plat_kmh: number;
  /** Non éditable : c'est la réconciliation. */
  moyenne_compteur_kmh: number;
  facteur_compteur: number;
  /** Mesuré sur l'historique, ou supposé par le modèle. L'écran doit le dire. */
  facteur_mesure: boolean;
  hors_bande: boolean;
}

export interface Palier {
  numero: number;
  bas_w: number;
  haut_w: number;
  puissance_w: number | null;
  ouverte: boolean;
  bas_pct: number;
  haut_pct: number;
}

export interface Zones {
  ftp_w: number;
  position_zone: number;
  zone_endurance: number;
  hors_bande: boolean;
  zones: Palier[];
  valeurs_liees: ValeursLiees | null;
}

// --- géocodage ----------------------------------------------------------

export interface Candidat {
  label: string;
  latitude: number;
  longitude: number;
  score: number;
  source: string;
  /**
   * La commune, seule chose qui distingue vraiment deux candidats — un même
   * `label` de rue existe dans des centaines de communes (Q34). `null` quand
   * le géocodeur ne la rend pas : ce n'est pas une erreur, c'est un candidat
   * qu'on ne sait pas situer.
   */
  commune: string | null;
  code_postal: string | null;
}

export interface Geocodage {
  adresse: string;
  candidats: Candidat[];
  /**
   * Les candidats ne désignent pas un seul lieu (communes différentes, ou pas
   * de commune du tout). **Ce n'est pas un arbitrage** : l'API rend les
   * candidats quand même et ne tranche jamais — c'est une information pour
   * décider quoi afficher.
   */
  ambigu: boolean;
  motif_ambiguite: string | null;
}

// --- séances ------------------------------------------------------------

export interface Etape {
  indice: number;
  type: string;
  libelle: string;
  duree_s: number;
  elastique: boolean;
  puissance_min_w: number | null;
  puissance_max_w: number | null;
  puissance_cible_w: number | null;
  vitesse_kmh: number | null;
  longueur_m: number | null;
}

export interface Seance {
  jour: string;
  nom: string;
  duree_s: number;
  n_blocs: number;
  distance_estimee_m: number | null;
  etapes: Etape[];
  avertissements: string[];
  meta: { ftp_w: number; source?: string; description?: string | null };
}

export interface Semaine {
  depuis: string;
  jusqua: string;
  jours: { jour: string; seance: SeanceResumee | null }[];
}

/** Ce que la liste de la semaine rend : la séance sans ses étapes. */
export interface SeanceResumee {
  jour: string;
  nom: string;
  duree_s: number;
  n_blocs: number;
  distance_estimee_m: number | null;
}

export interface FicheFichier {
  id: string;
  nom: string;
  url: string;
}

/**
 * Le GPX d'une proposition (Q40 g). Pas d'`id` : ce n'est pas un fichier
 * rangé quelque part, c'est une adresse qui le fabrique à l'appel — rien
 * n'est écrit tant que le cycliste n'a pas choisi.
 */
export interface FicheGpx {
  nom: string;
  url: string;
}

/**
 * « Pas de météo pour ce jour-là. » Le message dit le dernier jour couvert,
 * jamais pourquoi celui-ci ne l'est pas : Open-Meteo rend le même bloc vide
 * pour un point hors domaine et pour une date hors de portée.
 */
export interface MeteoAbsente {
  jour: string;
  dernier_jour_couvert: string;
  message: string;
}

// --- météo --------------------------------------------------------------

export interface Cellule {
  direction: string;
  distance_km: number;
  t: string;
  pluie_mm: number;
  pluie_second_avis_mm: number | null;
  vent_kmh: number;
  vent_depuis_deg: number;
  ressenti_c: number;
  confiance: string;
}

export interface Meteo {
  depart: PointDepart;
  debut: string;
  horizon_h: number;
  modele: string;
  second_avis: string | null;
  meilleure_direction: { nom: string; motif: string } | null;
  cellules: Cellule[];
}

// --- parcours -----------------------------------------------------------

export interface Trace {
  /** Le tracé, en paires `[latitude, longitude]`. */
  points: [number, number][];
  /** Le profil, en paires `[distance_m, altitude_m]`. */
  profil: [number, number][];
  simplification: {
    tolerance_m: number;
    points_origine: number;
    points_rendus: number;
    ecart_max_m: number;
  };
}

export interface Emplacement {
  etape_idx: number;
  debut_m: number;
  /** Le compteur, celui qui monte — jamais `debut_m` après un demi-tour. */
  debut_parcouru_m: number;
  longueur_m: number;
  demi_tour: boolean;
  note: number | null;
  motifs: string[] | null;
  pente_moyenne: number | null;
  pente_max: number | null;
  carrefours: number | null;
}

export interface Placement {
  note_totale: number;
  note_terrain: number;
  decalage_z2_s: number;
  duree_totale_s: number;
  distance_totale_m: number;
  denivele_parcours_m: number;
  blocs_bien_places: number;
  demi_tours: number;
  avertissements: string[];
  informations: string[];
  emplacements: Emplacement[];
}

/**
 * Une flèche de vent à poser sur le tracé — **déjà triée par le cœur**.
 *
 * Le front ne décide ni où elle va, ni si elle mérite d'être dessinée : la
 * liste qu'il reçoit est celle que `boucle.meteo_trace.fleches_vent` a
 * filtrée au seuil où le vent se sent (8 km/h, le haut de la force 1 de
 * Beaufort). C'est la même liste, produite par le même code, que celle que
 * dessine la page HTML autonome du sprint 5 : deux écrans qui montreraient
 * deux vents différents pour le même parcours seraient un défaut, pas une
 * variante.
 */
export interface FlecheVent {
  /** `[latitude, longitude]`, comme les points du tracé. */
  pt: [number, number];
  /** D'où **vient** le vent, en degrés (0 = nord). La flèche pointe dessus. */
  depuis_deg: number;
  vent_kmh: number;
  /** `null` quand la prévision ne donne pas de rafale : jamais un zéro. */
  rafale_kmh: number | null;
  /** « face », « dos » ou « travers » **au cap suivi à cet endroit**. */
  relatif: string | null;
}

export interface MeteoCandidate {
  pluie_cumulee_mm: number | null;
  minutes_pluie: number | null;
  part_vent_face: number | null;
  ressenti_min_c: number | null;
  confiance: string | null;
  fleches_vent?: FlecheVent[];
  modele_utilise?: string;
  repli?: boolean;
}

export interface Candidate {
  numero: number;
  retenue: boolean;
  nom: string;
  distance_km: number;
  denivele_m: number | null;
  azimut_deg: number | null;
  /** (distance − cible) / cible. Négatif : la boucle est plus courte que demandé. */
  ecart_relatif?: number | null;
  /** Vrai quand la boucle n'entre pas dans la tolérance de distance demandée. */
  hors_tolerance?: boolean;
  /** De combien la tolérance a dû être élargie, par paliers de 5 % (Q41 d). */
  elargissement?: number | null;
  /** La tolérance de distance en vigueur, pour dire « ±10 % demandés, ±20 % servis ». */
  tolerance_distance?: number | null;
  vitesse_kmh?: number | null;
  temps_estime_s?: number | null;
  couts: {
    km_trafic: number;
    km_calme: number;
    /**
     * Les kilomètres que le moteur **ne sait pas classer** : `highway`
     * absent, ou d'une valeur qu'il ne connaît pas. Ni trafic, ni calme.
     *
     * Il n'était pas typé ici, donc pas affiché, et l'écran présentait deux
     * catégories pour une distance qui en compte trois — un tracé à moitié
     * sur des chemins non classés s'annonçait « 0,0 km de trafic » comme un
     * tracé parfaitement calme. C'est le commentaire de `boucle.couts.Couts`
     * qui nomme ce piège, et l'écran tombait dedans.
     */
    km_non_classe: number;
    km_non_revetu: number;
    score: number;
    sens: string;
  } | null;
  meteo: MeteoCandidate | null;
  placement?: Placement | null;
  trace: Trace | null;
}

/** Le résumé d'une proposition : ce qui la distingue, et ses chiffres. */
export interface Proposition {
  numero: number;
  retenue: boolean;
  /** Ce qui la distingue des autres, en une phrase du cœur. */
  distinction: string | null;
  axe_distinctif: string | null;
  duree_s: number;
  depassement_seance_s: number | null;
  demi_tours: number;
  pluie_mm: number | null;
  /** Arrêts au kilomètre — l'axe de contraste « ville », pas un affichage. */
  densite_marqueurs_km: number | null;
  /**
   * Feux et stops en **nombre absolu**, tels que le cœur les compte.
   *
   * Sérialisés depuis le 17/09/2026. Avant, le front les retrouvait en
   * multipliant `densite_marqueurs_km` par la distance — le geste exact que
   * `sortie/contraste.py` nomme comme le piège à éviter, et qui effaçait le
   * chiffre au-delà de 100 km parce que la densité est arrondie à trois
   * décimales.
   */
  feux: number | null;
  stops: number | null;
  part_trafic: number | null;
  orientation_vent: string | null;
  note_terrain: number | null;
  recouvrement_max_avec: Record<string, number> | null;
  /** Où demander **cette** trace-ci. `null` sur une réponse d'avant Q40 (g). */
  gpx: FicheGpx | null;
}

export interface Tenue {
  categorie_temp: string;
  categorie_humidite: string;
  base: string[];
  a_emporter: string[];
  a_enlever: string[];
  motifs: string[];
}

/** Un azimut qu'une préférence de vent imposerait — **jamais recalculé côté front** (Q44). */
export interface AzimutVent {
  azimut_deg: number;
  nom: string;
}

/**
 * Ce que `GET /vent-depart` rend : d'où souffle le vent, et l'azimut (ou les
 * deux, pour le latéral) que chaque préférence imposerait (Q44).
 *
 * `posee: false` veut dire qu'on ne pose pas la question — vent sous le
 * seuil, séance trop loin dans l'horizon, ou météo indisponible — et
 * `azimuts_par_choix` est alors vide partout. `motif` dit pourquoi, en
 * clair ; l'écran l'affiche au lieu d'inventer un vent.
 */
export interface VentDepart {
  jour: string;
  depart: string;
  posee: boolean;
  motif: string | null;
  vent_kmh: number | null;
  vent_depuis_deg: number | null;
  vent_depuis_nom: string | null;
  seuil_kmh: number;
  horizon_jours: number;
  choix: string[];
  azimuts_par_choix: Record<string, AzimutVent[]>;
}

export interface QuestionVent {
  posee: boolean;
  motif: string | null;
  vent_kmh: number | null;
  vent_depuis_deg: number | null;
  seuil_kmh: number;
  horizon_jours: number;
  reponse: string;
  choix: string[];
}

export interface Sortie {
  jour: string;
  seance: { nom: string; duree_s: number; n_etapes: number; n_blocs: number } | null;
  demande: {
    distance_km: number;
    distance_source: string | null;
    direction: string | null;
    candidates: number;
    depart: string;
    lieu_depart: PointDepart;
    velo: string | null;
  };
  modele_physique: string | null;
  modele_meteo: { utilise: string; repli: boolean } | null;
  /** Déclarée absente plutôt que rendue en panne (Q40 a). */
  meteo_absente: MeteoAbsente | null;
  /** L'identifiant de cette génération, à qui appartiennent les GPX. */
  generation: string | null;
  /** Toujours `null` depuis Q40 (g) : aucun GPX n'est écrit à la génération. */
  gpx: FicheFichier | null;
  carte: FicheFichier | null;
  tenue: Tenue | null;
  propositions: Proposition[];
  question_vent: QuestionVent | null;
  /** Rempli quand le cœur n'a pas pu en rendre trois. Ce n'est pas une panne. */
  motif_deux_propositions: string | null;
  candidates: Candidate[];
}

export interface Boucle {
  depart: PointDepart & { heure: string };
  demande: { distance_km: number; direction: string; candidates: number };
  meteo_absente: MeteoAbsente | null;
  gpx: FicheFichier | null;
  candidates: Candidate[];
}

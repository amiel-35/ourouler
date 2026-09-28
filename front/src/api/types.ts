/** Le contrat de l'API, tel qu'il est écrit dans `tests/caracterisation/openapi.json`
 * (schéma qui fait foi, vérifié par `tests/types_openapi.test.ts` ; les
 * arbitrages qui l'expliquent sont dans `docs/journal/ux/api_contrat.md`).
 *
 * Ces types décrivent **ce que l'API rend**, pas ce que le front voudrait
 * recevoir. Quand un champ manque au contrat, il manque ici aussi : c'est la
 * seule façon que le compilateur ait de refuser un écran qui afficherait une
 * valeur inventée (doctrine §10.2 ; on n'affirme rien sans mesure).
 *
 * Tout ce qui peut valoir `null` le vaut ici. Le cœur distingue « zéro » de
 * « on ne sait pas », et l'interface doit pouvoir le distinguer aussi.
 */

/**
 * Un avertissement de l'API : **un code qu'on teste, un message qu'on affiche**.
 *
 * Le code vient de `api/erreurs.CODES_AVERTISSEMENT`, publié dans
 * `/openapi.json`. Sans lui, le bandeau « Pas de météo » se déciderait en
 * cherchant le mot « météo » dans une prose que
 * `docs/journal/ux/api_contrat.md` déclare reformulable. Aucun écran ne lit
 * une phrase pour en déduire un état.
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

/**
 * Les quatre routes de session (`api/routes/sessions.py` : « comptes et
 * sessions »). Elles précèdent tout propriétaire, donc rendent seulement
 * `donnees` — jamais l'enveloppe complète (`Enveloppe`) ni la forme courte
 * des routes de profil (`Simple`, qui porte un `proprietaire` que ces
 * quatre-là n'ont pas encore).
 */
export interface DonneesSeules<T> {
  donnees: T;
}

/** `GET /invitation` : l'état d'un jeton, sans le consommer. */
export interface Invitation {
  email: string;
  /** ISO 8601, avec l'heure — pas seulement une date (`comptes.DUREE_INVITATION`). */
  expire_le: string;
}

/** `POST /entrer`, `POST /connexion` et `POST /reinitialiser` : la session vient de s'ouvrir. */
export interface AccesOuvert {
  proprietaire: string;
}

/** `GET /moi` : l'adresse du compte de la session en cours.
 *
 * `email` vaut `null` sur un déploiement sans base de comptes — mode personnel, ou
 * hébergé sans compte configuré — voir `api/routes/moi.py:mon_compte`.
 */
export interface MonCompte {
  email: string | null;
}

/**
 * `GET /moi/fichiers-origine` (`donnees`) : le choix de garder ou d'effacer
 * ses fichiers d'origine (FIT/GPX/TCX), et combien il en reste.
 *
 * `garder` vaut `true` par défaut sur un déploiement sans base de comptes
 * (mode personnel) — il n'y a alors pas de choix à faire. `depuis` est
 * `null` tant que personne n'a jamais posé le réglage explicitement.
 * `tache` n'est rendue que si un effacement tourne encore : c'est ce qui
 * permet à l'écran de reprendre « Effacement en cours… » après un
 * rechargement, plutôt que de proposer de nouveau « Garder » pendant que la
 * purge efface encore.
 */
export interface ConservationFichiers {
  garder: boolean;
  depuis: string | null;
  nombre_fichiers: number;
  tache: TacheConservation | null;
}

/** Ce que `RapportConservation.rapport` porte une fois la tâche finie. */
export interface RapportConservation {
  candidates: number;
  derivees: number;
  deja_a_jour: number;
  sans_vent: number;
  echecs: number;
  fichiers_effaces: number;
}

/**
 * Une tâche de fond de `PUT /moi/fichiers-origine` (`garder: false`) :
 * dérive chaque sortie calibrable puis efface les fichiers d'origine.
 * `GET /moi/fichiers-origine/{id}` la suit, comme un import.
 */
export interface TacheConservation {
  id: string;
  statut: "en_cours" | "fini" | "echoue";
  traites: number;
  total: number;
  rapport: RapportConservation | null;
  erreur: string | null;
  code_erreur?: string | null;
}

/**
 * `PUT /moi/fichiers-origine` (`donnees`) : le choix, aussitôt posé, et la
 * tâche de fond qu'il a pu lancer.
 *
 * `tache` est `null` en revenant à « garder » — rien à dériver ni à
 * effacer, la réponse est immédiate (200) — et porte la tâche lancée en
 * passant à « ne pas garder » (202, à suivre via `TacheConservation`).
 */
export interface ReponseConservation {
  garder: boolean;
  depuis: string;
  tache: TacheConservation | null;
}

/** `DELETE /moi` (`donnees`) : ce que l'effacement RGPD a supprimé, et ce qu'il a conservé.
 *
 * Forme volontairement ouverte (`Record<string, boolean | number>` pour `supprime`,
 * `Record<string, string>` pour `conserve`) : c'est `api/vie_privee.effacer_donnees` qui
 * décide des clés, et ce module ne les recopie pas en dur — un dépôt de plus qui gagne
 * un compteur ne doit pas casser ce type.
 */
export interface EffacementCompte {
  supprime: Record<string, boolean | number>;
  conserve: Record<string, string>;
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
  /** `null` : rien déclaré, le serveur suppose `MASSE_VELO_DEFAUT_KG`. */
  masse_kg: number | null;
  cda_m2: number | null;
  crr: number | null;
  facteur_compteur: number | null;
  capteur_puissance?: string | null;
  /** La catégorie de pneu : elle donne le Crr du vélo par
   * la littérature, et la calibration ne cherche plus alors que le CdA.
   * `null` ou absent : pas de pneu déclaré. */
  pneu?: CategoriePneu | null;
}

/** Les catégories de pneu que le serveur accepte (`config.PNEUS_VELO`). */
export type CategoriePneu =
  | "course_rapide"
  | "course_quatre_saisons"
  | "entrainement"
  | "gravel"
  | "vtt";

export interface Profil {
  depart: PointDepart;
  /** `prenom`/`nom` : identité du compte, obligatoire dans l'assistant
   * (décision Q36), mais peuvent revenir vides pour un profil plus ancien —
   * jamais absents. Aucun calcul ne s'en sert ; ils servent au compte (e-mail
   * d'invitation, affichage). `ftp_w` est **facultative**
   * (`docs/journal/ux/parcours_accueil.md`) : `null` tant que l'entonnoir de l'accueil n'a pas
   * établi de FTP, quelle qu'en soit la voie (T1 à T5). */
  cycliste: { masse_kg: number; ftp_w: number | null; prenom: string; nom: string };
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
  /**
   * Vrai tant que ce compte n'a **jamais** écrit de `PATCH /profil` — un
   * compte activé mais jamais passé par l'assistant, quel qu'ait été le
   * socle lu au démarrage. Sans lui, un compte neuf atterrirait sur l'écran
   * du jour, qui réclame Intervals et échoue. Le premier `PATCH /profil` le
   * fait tomber à `false` — dans **sa propre réponse** déjà, pas seulement au
   * prochain `GET` (`api/routes/profil.py::_profil_avec_flags`).
   */
  assistant_recommande: boolean;
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
  /** `null` sans FTP encore établie — `zones` vaut alors `[]` et
   * `valeurs_liees` vaut `null` (`seance.ecran_ftp.rendu`). La
   * position, elle, reste rendue : elle ne dépend pas de la FTP. */
  ftp_w: number | null;
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
   * `label` de rue existe dans des centaines de communes. `null` quand
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

/** Un motif de dépôt ignoré, groupé — `POST /activites/import`. */
export interface MotifIgnore {
  motif: string;
  nombre: number;
  exemples: string[];
}

/** Le rapport final d'un import — fichiers isolés ou archive Strava/Garmin. */
export interface RapportImport {
  importees: number;
  doublons: number;
  ignorees: MotifIgnore[];
  /** Faux pour un compte qui ne garde pas ses fichiers d'origine : le fichier
   * n'a pas été gardé, seul ce qu'on en a tiré (`derivees`) pour la calibration. */
  fichiers_conserves: boolean;
  derivees: number;
  rafraichies: number;
  sans_vent: number;
}

/** Ce que rend `GET /activites/import` : l'état du dépôt pour ce cycliste. */
export interface EtatImport {
  nombre: number;
  premiere: string | null;
  derniere: string | null;
  /** Le choix en vigueur au moment de l'appel — voir `ConservationFichiers`. */
  fichiers_conserves: boolean;
}

/**
 * Ce que rendent `POST /activites/import` (202) et `GET /activites/import/{id}`.
 *
 * Une archive Strava réelle (≈2 900 sorties) prend environ 16 minutes à
 * importer — bien au-delà des 180 s où le front abandonne un appel — d'où
 * un import en tâche de fond : le dépôt rend tout de suite `id` et
 * `statut: "en_cours"`, et l'écran interroge `GET .../import/{id}` pour
 * suivre `traites`/`total` jusqu'à `"fini"` ou `"echoue"`.
 */
export interface JobImport {
  id: string;
  statut: "en_cours" | "fini" | "echoue";
  traites: number;
  total: number;
  rapport: RapportImport | null;
  erreur: string | null;
  /** Le code de l'échec (« erreur_interne », « annulee »…), `null` sinon. */
  code_erreur?: string | null;
}

/**
 * Une calibration, en mots simples — `GET /calibrations` et le rapport d'un
 * job de calibration.
 *
 * Ce qui se montre d'abord : la puissance qu'il faut à `vitesse_repere_kmh`
 * sur le plat sans vent, l'erreur mesurée sur des sorties que le calcul
 * n'avait pas vues, la fourchette du porte à porte, le nombre de sorties.
 * `detail` (CdA, Crr) ne se montre que replié : ce sont des paramètres de
 * compensation — ils absorbent aussi l'étalonnage du capteur —, pas des
 * mesures du vélo à comparer à un catalogue.
 */
export interface ResumeCalibration {
  velo: string;
  date: string | null;
  provenance: "mesure";
  puissance_repere_w: number;
  vitesse_repere_kmh: number;
  n_sorties: number;
  n_validation: number;
  /** Erreur absolue moyenne sur le temps en mouvement, en fraction (0,035 = 3,5 %). */
  erreur_validation: number | null;
  biais_validation: number | null;
  porte_a_porte: {
    bas: number;
    mediane: number;
    haut: number;
    n: number;
    provenance: "mesure" | "defaut";
  };
  /** « pneu », « configuration », « usage » (aucun pneu déclaré) ou « ajuste ». */
  crr_source: string | null;
  pneu: string | null;
  /** « pneu changé depuis la calibration, relancez-la », ou `null`. */
  alerte: string | null;
  detail: { cda_m2: number; crr: number; masse_totale_kg: number };
}

/** Ce que rendent `POST /calibrations` (202) et `GET /calibrations/{id}`. */
export interface JobCalibration {
  id: string;
  statut: "en_cours" | "fini" | "echoue";
  traites: number;
  total: number;
  /** « lecture » (des fichiers), « meteo » (archives du jour), « ajustement ». */
  etape: "" | "lecture" | "meteo" | "ajustement";
  nature: "calibration";
  sujet: string | null;
  rapport: {
    calibration: ResumeCalibration | null;
    sorties_lues: number;
    sorties_apprentissage: number;
    sorties_groupe: number;
    archives_meteo_manquantes: number;
    repli: string | null;
  } | null;
  erreur: string | null;
  /** Le code de l'échec (« calibration_impossible », « annulee », « erreur_interne »). */
  code_erreur?: string | null;
}

/** Un vélo dans `GET /calibrations` : sa calibration, ce qui la permettrait, la tâche récente. */
export interface EtatCalibrationVelo {
  velo: string;
  calibration: ResumeCalibration | null;
  sorties_disponibles: number;
  sorties_ecartees: Record<string, number>;
  pneu: string | null;
  crr_connu: boolean;
  crr_usage: number;
  tache: JobCalibration | null;
}

export interface EtatCalibrations {
  sorties_necessaires: number;
  ftp_renseignee: boolean;
  velos: EtatCalibrationVelo[];
  /** Absent en mode personnel (pas de quota). */
  quota?: { plafond: number; restant: number };
}

/**
 * Le GPX d'une proposition (décision Q40 g). Pas d'`id` : ce n'est pas un fichier
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
  /**
   * « face », « dos » ou « travers » **pour qui partirait dans cette
   * direction-là** — déjà tranché par `meteo.rapport.vent_relatif` (secteur
   * de ±45°) et sérialisé par `rendre_json`, au même titre que `confiance`.
   * `null` sur le point « ici » (exclu du contrat, voir `meteo/rapport.py`)
   * ou quand le vent manque à cette heure-là. Jamais recalculé côté front (même discipline que `azimuts_par_choix`,
   * `direction_vent.test.tsx`).
   */
  vent_relatif: string | null;
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
 * dessine la page HTML autonome : deux écrans qui montreraient
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

/**
 * Le vent à une position du tracé entier — **sans filtre de sensibilité**,
 * contrairement à `FlecheVent` (`boucle.meteo_trace.vent_par_position`).
 *
 * Sert à colorer le tracé lui-même, pas à poser un marqueur : `dist_m` se
 * raccorde à `trace.profil` (même convention que les `emplacements` de
 * `Placement`), le front n'a donc pas besoin d'un second `[lat, lon]`.
 */
export interface VentPosition {
  /** Distance cumulée depuis le départ, en mètres — se raccorde à `trace.profil`. */
  dist_m: number;
  /** « face », « dos », « travers », ou `null` si le cœur n'a pas pu trancher. */
  relatif: string | null;
}

export interface MeteoCandidate {
  pluie_cumulee_mm: number | null;
  minutes_pluie: number | null;
  part_vent_face: number | null;
  ressenti_min_c: number | null;
  confiance: string | null;
  fleches_vent?: FlecheVent[];
  vent_par_position?: VentPosition[];
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
  /** De combien la tolérance a dû être élargie, par paliers de 5 %. */
  elargissement?: number | null;
  /** La tolérance de distance en vigueur, pour dire « ±10 % demandés, ±20 % servis ». */
  tolerance_distance?: number | null;
  vitesse_kmh?: number | null;
  /** Le temps de **mouvement**, modèle physique de cette boucle-ci — INCHANGÉ. */
  temps_estime_s?: number | null;
  /** D'où vient `temps_estime_s`. Absent d'une réponse plus ancienne. */
  temps_source?: "modele" | "vitesse_moyenne";
  /**
   * Porte à porte, arrêts compris : la **médiane** d'une fourchette : `temps_estime_s × médiane`. `null`
   * quand `compteur` (sur la réponse) l'est aussi : sans vélo enregistré, il
   * n'y a pas de fourchette. Absent d'une réponse plus ancienne.
   */
  temps_ecoule_s?: number | null;
  /** Les bornes de la fourchette : la moitié des sorties du cycliste tombe
   * entre les deux (centiles 25 et 75). Absentes d'une réponse plus ancienne. */
  temps_ecoule_bas_s?: number | null;
  temps_ecoule_haut_s?: number | null;
  /**
   * `"mesure"` : fourchette mesurée sur les sorties de ce vélo (`ourouler
   * calibrer`). `"defaut"` : convention, mesurée sur un seul cycliste — à
   * dire à l'écran (on ne présente jamais une estimation comme une mesure).
   */
  temps_ecoule_source?: "mesure" | "defaut" | null;
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
  /**
   * Ce qui la distingue des autres, en une phrase du cœur.
   *
   * **Vide ou `null` est normal** (décision Q43) : le tracé se
   * distingue par lui-même, et le cœur n'écrit une phrase que quand elle est
   * vraie. Ne jamais la remplacer par un texte de remplissage — quand aucune
   * n'en a, `motif_equivalence` dit pourquoi.
   */
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
   * Sérialisés pour que le front n'ait pas à les retrouver en multipliant
   * `densite_marqueurs_km` par la distance — le geste exact que
   * `sortie/contraste.py` nomme comme le piège à éviter, et qui effacerait le
   * chiffre au-delà de 100 km parce que la densité est arrondie à trois
   * décimales.
   */
  feux: number | null;
  stops: number | null;
  part_trafic: number | null;
  orientation_vent: string | null;
  note_terrain: number | null;
  recouvrement_max_avec: Record<string, number> | null;
  /** Où demander **cette** trace-ci. `null` sur une réponse plus ancienne. */
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

/** Un azimut qu'une préférence de vent imposerait — **jamais recalculé côté front**. */
export interface AzimutVent {
  azimut_deg: number;
  nom: string;
}

/**
 * Ce que `GET /vent-depart` rend : d'où souffle le vent, et l'azimut (ou les
 * deux, pour le latéral) que chaque préférence imposerait (décision Q44).
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

/**
 * Une candidate tombée **avant** le contraste, et où elle est tombée.
 *
 * `etape` vaut `"distance"` — la génération n'a pas su faire la distance dans
 * cette direction, il n'y a donc aucun tracé — ou `"placement"` : la boucle
 * existe, c'est la séance qui n'y tenait pas, et celle-là se dessine.
 */
export interface Ecartee {
  azimut_deg: number | null;
  distance_km: number;
  motif: string;
  etape: "distance" | "placement" | string;
  trace: Trace | null;
}

/** Le sort d'**une** candidate au contraste, tel que le cœur l'a décidé. */
export interface VerdictCandidate {
  numero: number;
  /**
   * `retenue` · `trop_proche` (écartée : trop de routes communes avec une
   * retenue) · `place_prise` (assez différente, mais le groupe était complet).
   *
   * Les deux derniers ne sont **pas** la même chose : confondre « écartée »
   * et « pas de place » ferait voir un défaut là où il n'y en a pas.
   */
  sort: "retenue" | "trop_proche" | "place_prise" | string;
  /** La part de routes communes la plus forte avec une retenue. */
  recouvrement_max: number | null;
  /** Le numéro de cette retenue-là. */
  contre_numero: number | null;
  /** La phrase du cœur : « 55 % des mêmes routes que la n° 1 ». */
  motif: string;
}

/** Une paire de candidates et sa part de routes communes. */
export interface PaireRecouvrement {
  a: number;
  b: number;
  recouvrement: number;
  au_dessus_du_seuil: boolean;
}

/**
 * Ce que le contraste a décidé, et de quoi le refaire.
 *
 * Rien ici ne se recalcule côté front : les pourcentages, les verdicts et la
 * phrase viennent tous de `sortie/contraste.py`. `paires` porte **toutes**
 * les paires, pas seulement celles des retenues — c'est cette matrice qui
 * montre qu'une seule case au-dessus du seuil interdit tout groupe contenant
 * ses deux boucles.
 */
export interface Arbitrage {
  seuil_recouvrement: number;
  candidates: VerdictCandidate[];
  paires: PaireRecouvrement[];
  essais: {
    taille: number;
    essayes: number;
    valides: number;
    /** Combien de groupes refusés ne tombent que sur **une seule** paire. */
    refuses_par_une_paire: number;
  } | null;
  phrase: string | null;
}

/**
 * D'où vient la distance visée, et le facteur du second temps de sortie
 * (« porte à porte »).
 *
 * `null` quand la configuration ne porte aucun vélo : il n'y a alors ni
 * modèle ni facteur, `temps_ecoule_s` vaut `null` sur chaque candidate, et
 * aucun écran n'affiche de second chiffre — pas même un tiret. Absent d'une
 * réponse plus ancienne, ce qui revient au même côté lecture.
 */
export interface Compteur {
  velo: string;
  moyenne_compteur_kmh: number;
  facteur_compteur: number;
  /** Mesuré sur l'historique, ou supposé par le modèle — à dire à l'écran
   * (décision 8 du cycle UX ; on ne présente jamais une estimation comme une mesure) chaque fois que la valeur
   * s'affiche. */
  facteur_provenance: "mesure" | "suppose";
  /** La fourchette qui chronomètre le porte à porte :
   * `temps_estime_s × [bas, haut]`, et d'où elle vient. `n` : le nombre de
   * sorties roulées seul sur lesquelles elle a été mesurée (0 en convention). */
  porte_a_porte: FourchettePorteAPorte;
}

export interface FourchettePorteAPorte {
  bas: number;
  mediane: number;
  haut: number;
  provenance: "mesure" | "defaut";
  n: number;
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
  /** Absent d'une réponse plus ancienne : à lire comme `null`. */
  compteur?: Compteur | null;
  modele_physique: string | null;
  modele_meteo: { utilise: string; repli: boolean } | null;
  /** Déclarée absente plutôt que rendue en panne (décision Q40 a). */
  meteo_absente: MeteoAbsente | null;
  /**
   * L'identifiant de cette génération, à qui appartiennent les GPX.
   *
   * Absent (pas seulement `null`) quand aucun GPX n'a été recueilli
   * (`api/routes/generations.py::generer_sortie`, `if recueillis:` avant
   * `vues.avec_gpx_par_proposition`) — le front ne s'en sert pas aujourd'hui,
   * mais un futur usage doit lire le cas plutôt que le supposer toujours là.
   */
  generation?: string | null;
  /** Toujours `null` : aucun GPX n'est écrit à la génération (décision Q40 g). */
  gpx: FicheFichier | null;
  carte: FicheFichier | null;
  tenue: Tenue | null;
  propositions: Proposition[];
  question_vent: QuestionVent | null;
  /** Rempli quand le cœur n'a pas pu en rendre trois. Ce n'est pas une panne. */
  motif_deux_propositions: string | null;
  /**
   * Rempli quand **aucune proposition ne se détache** des autres (décision Q45).
   *
   * « Ces trois boucles se valent, choisissez où vous voulez aller », avec ce
   * qui, mesuré, ne les sépare pas. C'est une bonne nouvelle, pas un défaut :
   * rien ne contraint le choix. Peut coexister avec le champ précédent.
   */
  motif_equivalence: string | null;
  /** Les candidates tombées avant le contraste. Absent d'une réponse ancienne. */
  ecartees?: Ecartee[] | null;
  /** Le sort de toutes les candidates au contraste. Absent d'une réponse ancienne. */
  arbitrage?: Arbitrage | null;
  candidates: Candidate[];
}

export interface Boucle {
  depart: PointDepart & { heure: string };
  // `null` sans direction demandée — le moteur a balayé tout l'horizon.
  demande: { distance_km: number; direction: string | null; candidates: number };
  /** Absent d'une réponse plus ancienne : à lire comme `null`. */
  compteur?: Compteur | null;
  meteo_absente: MeteoAbsente | null;
  gpx: FicheFichier | null;
  candidates: Candidate[];
}

// --- un parcours déjà en main, à analyser -------------------------------------

/** Ce que `POST /parcours/fichier` rend tout de suite, avant l'analyse. */
export interface ApercuParcours {
  nom: string;
  distance_km: number;
  denivele_m: number | null;
  /** « 3 traces enchaînées », « un trou de 12 km entre… » — vide pour une seule trace. */
  avertissements: string[];
}

/**
 * `POST /parcours/analyser` — le pendant de `Candidate`, pour un parcours **déjà
 * choisi** (l'imposé d'un BRM, une boucle de club) plutôt qu'une candidate du moteur.
 * Même forme de `trace`/`meteo` que `Candidate` : `Carte`, `LegendeVent` et
 * `ProfilAltitude` se réutilisent sans rien réécrire.
 */
export interface Analyse {
  nom: string;
  distance_km: number;
  denivele_m: number | null;
  velo: string;
  puissance_w: number;
  depart: string;
  temps_estime_s: number;
  vitesse_moy_kmh: number;
  temps_ecoule_s: number;
  temps_ecoule_bas_s: number;
  temps_ecoule_haut_s: number;
  temps_ecoule_source: "mesure" | "defaut";
  heure_arrivee: string;
  heure_arrivee_bas: string;
  heure_arrivee_haut: string;
  /** La fourchette du vélo : sa médiane date aussi les échantillons météo. */
  porte_a_porte: { bas: number; mediane: number; haut: number; provenance: string; n: number };
  meteo_absente: MeteoAbsente | null;
  meteo_panne: string | null;
  avertissements_trace: string[];
  /** `bascule_dist_m` : au-delà, la prévision vient du second modèle (portée
   * horaire du principal dépassée) — un long parcours y arrive souvent.
   * `au_dela_prevision_dist_m` : au-delà, plus aucune prévision. */
  meteo:
    | (MeteoCandidate & { bascule_dist_m?: number | null; au_dela_prevision_dist_m?: number | null })
    | null;
  trace: Trace;
}

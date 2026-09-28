// @vitest-environment node
/** Lot 14, puis lot 11 (25/09/2026) — les types du front vérifiés contre la
 * référence openapi.
 *
 * `docs/journal/ouverture_plan.md` §7 : « les types sont vérifiés contre openapi ».
 * Sans dépendance nouvelle (ni générateur de types, ni analyseur TypeScript) :
 *
 * 1. une **table explicite** dit, pour chaque type du front qui a un
 *    équivalent dans `tests/caracterisation/openapi.json`, quel schéma il
 *    reflète et quels champs il porte (et lesquels sont facultatifs) ;
 * 2. le test compare cette liste au schéma openapi : chaque champ du front
 *    existe sous le même nom, et l'optionnalité concorde ;
 * 3. le test relit la source TypeScript **comme du texte** pour vérifier que
 *    la liste de la table est bien celle du type réel — sinon la table
 *    pourrait mentir et le point 2 ne prouverait rien.
 *
 * **Depuis le lot 11, les réponses réussies ont un schéma** (`api/reponses.py`) :
 * un modèle par route, qui nomme les champs que le rendu écrit toujours, et
 * laisse `extra="allow"` au-delà — ces modèles **décrivent, ils ne
 * filtrent pas** (`reponses.py`, en-tête). La table couvre maintenant aussi
 * les réponses, avec une différence de méthode par rapport aux requêtes :
 *
 * - pour une **requête**, un champ requis par le schéma que le front ne
 *   déclarerait pas serait un appel qui échoue — la table exige donc que
 *   *tout* champ requis soit couvert (`ligne.champs`).
 * - pour une **réponse**, le front n'est pas obligé de tout lire : il type
 *   ce dont les écrans se servent, et le schéma peut en garantir davantage
 *   (`Profil` ne porte pas `boucle`, `intervals`… que `DonneesProfil`
 *   décrit). Ne pas couvrir un champ n'est donc pas une erreur — seul
 *   compte ce qui *est* déclaré : un champ que le front lit doit exister
 *   dans le schéma sous le même nom (`champsHorsSchema` documente les rares
 *   exceptions), et parmi les champs qu'il déclare, l'optionnalité doit
 *   concorder dans les deux sens (`facultatifsConnus` documente le front
 *   plus prudent que le serveur — rétrocompatibilité —, `garantisHorsSchema`
 *   le contraire — un champ que pydantic ne dit pas requis mais que le rendu
 *   écrit toujours).
 *
 * Les réponses à enveloppe générique (`ReponseCalcul` : simulations, analyse
 * de parcours, routes apprises) n'ont pas de modèle de données précis —
 * `donnees` y reste un dictionnaire ouvert — et sont donc listées comme
 * *non couvertes*, avec leur raison, plutôt que forcées dans la table.
 * Pareil pour deux routes que le front n'appelle pas du tout aujourd'hui
 * (`GET /inventaire`, `GET /systeme/budgets`).
 *
 * Autres limites, assumées :
 * - on compare des **noms** et une **optionnalité**, pas des types (`number`
 *   contre `integer`, `string` contre une énumération, `| null`…) ;
 * - la lecture du TypeScript est volontairement naïve (voir `champsDuBloc`) :
 *   elle suffit aux déclarations plates de `api/types.ts` et `api/client.ts`,
 *   pas à une déclaration qui mettrait une fonction fléchée ou un générique à
 *   virgule en tête de champ ;
 * - les paramètres de chemin et de requête (`?jour=`, `?velo=`…) ne sont pas
 *   couverts, ni les corps multipart (`FormData`) ;
 * - les champs de type `list[dict[str, Any]]` ou `dict[str, Any]` côté
 *   serveur (`candidates`, `propositions`, `demande`, `seance`…) n'ont pas de
 *   schéma imbriqué à comparer : le contrat les laisse ouverts, la table
 *   s'arrête donc au premier niveau typé pour ces champs-là.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { CODE_DELAI, CODE_ILLISIBLE, CODE_INJOIGNABLE } from "../src/api/client";
import { TITRES_PANNE } from "../src/composants/echec/titres";

const RACINE_FRONT = join(__dirname, "..");
const OPENAPI = join(RACINE_FRONT, "..", "tests", "caracterisation", "openapi.json");

interface SchemaObjet {
  type?: string;
  properties?: Record<string, unknown>;
  required?: string[];
  additionalProperties?: unknown;
  $ref?: string;
}

const reference = JSON.parse(readFileSync(OPENAPI, "utf8")) as {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, SchemaObjet> };
};
interface Operation {
  requestBody?: { content?: Record<string, { schema?: SchemaObjet }> };
  responses?: Record<string, { content?: Record<string, { schema?: SchemaObjet }> }>;
}

/**
 * Une ligne de la table : un type du front, le schéma openapi qu'il reflète.
 *
 * - `ancre` : le texte qui ouvre la déclaration dans `fichier`, terminé par
 *   l'accolade ouvrante. Toutes les occurrences sont vérifiées (le départ
 *   `depart?: {` apparaît dans deux demandes, il vaut pour les deux).
 * - `genre` : `type` pour une interface ou un type en ligne (les `?` y disent
 *   l'optionnalité), `litteral` pour un objet construit sur place, qui envoie
 *   toujours tous ses champs.
 * - `sens` : `requete` (le front l'envoie) ou `reponse` (le serveur le rend).
 */
interface Correspondance {
  fichier: "api/types.ts" | "api/client.ts";
  ancre: string;
  schema: string;
  genre: "type" | "litteral";
  sens: "requete" | "reponse";
  champs: string[];
  facultatifs: string[];
  /**
   * Pour une réponse : les champs que le front tient pour toujours présents
   * alors qu'openapi ne les déclare pas `required`. Chacun est un écart
   * connu, justifié à côté ; la liste doit rester exacte.
   */
  garantisHorsSchema?: string[];
  /**
   * Pour une réponse : les champs facultatifs côté front (rétrocompatibilité
   * avec une réponse plus ancienne, voir le commentaire du champ dans
   * `types.ts`) alors que le schéma les déclare `required` aujourd'hui.
   * Chacun est un écart connu ; la liste doit rester exacte.
   */
  facultatifsConnus?: string[];
  /**
   * Pour une réponse : les champs que le front déclare mais qu'openapi ne
   * décrit pas du tout (ni requis, ni facultatif) — un champ ajouté
   * dynamiquement par le serveur, hors du modèle pydantic. Chacun est un
   * écart connu, justifié à côté.
   */
  champsHorsSchema?: string[];
}

const TABLE: Correspondance[] = [
  {
    fichier: "api/types.ts",
    ancre: "export interface Panne {",
    schema: "Panne",
    genre: "type",
    sens: "reponse",
    champs: ["code", "message", "service", "details"],
    facultatifs: [],
    // Le serveur les écrit toujours (`api/erreurs.py`, `ErreurApi.charge` ;
    // `api/limite_corps.py`, la réponse 413), mais le modèle pydantic leur
    // donne une valeur par défaut, et openapi ne les dit donc pas requis.
    garantisHorsSchema: ["service", "details"],
  },
  {
    fichier: "api/client.ts",
    ancre: "export interface DemandeSortie {",
    schema: "DemandeSortie",
    genre: "type",
    sens: "requete",
    champs: [
      "jour",
      "heure_depart",
      "distance_km",
      "direction",
      "candidates",
      "vent",
      "velo",
      "depart",
      "fichier_seance",
    ],
    facultatifs: [
      "jour",
      "heure_depart",
      "distance_km",
      "direction",
      "candidates",
      "vent",
      "velo",
      "depart",
      "fichier_seance",
    ],
  },
  {
    fichier: "api/client.ts",
    ancre: "export interface DemandeBoucle {",
    schema: "DemandeBoucle",
    genre: "type",
    sens: "requete",
    champs: ["distance_km", "direction", "heure_depart", "candidates", "velo", "puissance_w", "depart"],
    facultatifs: ["direction", "heure_depart", "candidates", "velo", "puissance_w", "depart"],
  },
  {
    fichier: "api/client.ts",
    ancre: "export interface DemandeAnalyse {",
    schema: "DemandeAnalyse",
    genre: "type",
    sens: "requete",
    champs: ["gpx", "heure_depart", "velo", "puissance_w"],
    facultatifs: ["velo", "puissance_w"],
  },
  {
    fichier: "api/client.ts",
    ancre: "depart?: {",
    schema: "Point",
    genre: "type",
    sens: "requete",
    champs: ["latitude", "longitude", "nom"],
    facultatifs: ["nom"],
  },
  {
    fichier: "api/client.ts",
    ancre: "apercuZones: (entree: {",
    schema: "ApercuZones",
    genre: "type",
    sens: "requete",
    champs: ["position_zone", "puissance_w", "vitesse_a_plat_kmh", "velo"],
    facultatifs: ["position_zone", "puissance_w", "vitesse_a_plat_kmh", "velo"],
  },
  {
    fichier: "api/client.ts",
    ancre: "apercuFtpDepuisTerrain: (entree: {",
    schema: "DemandeVitesseCompteur",
    genre: "type",
    sens: "requete",
    champs: ["vitesse_kmh", "denivele_m_par_km", "velo"],
    facultatifs: ["velo"],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/entrer", {',
    schema: "DemandeEntree",
    genre: "litteral",
    sens: "requete",
    champs: ["jeton", "secret"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/connexion", {',
    schema: "DemandeConnexion",
    genre: "litteral",
    sens: "requete",
    champs: ["email", "secret"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/reinitialiser", {',
    schema: "DemandeReinitialisation",
    genre: "litteral",
    sens: "requete",
    champs: ["jeton", "secret"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/demandes-invitation", {',
    schema: "DemandeInvitationPublique",
    genre: "litteral",
    sens: "requete",
    champs: ["adresse", "message", "piege"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/moi/mot-de-passe", {',
    schema: "DemandeChangementMotDePasse",
    genre: "litteral",
    sens: "requete",
    champs: ["mot_de_passe_actuel", "nouveau_mot_de_passe"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/moi/fichiers-origine", {',
    schema: "DemandeConservationFichiers",
    genre: "litteral",
    sens: "requete",
    champs: ["garder"],
    facultatifs: [],
  },
  {
    fichier: "api/client.ts",
    ancre: '("/calibrations", {',
    schema: "DemandeCalibration",
    genre: "litteral",
    sens: "requete",
    champs: ["velo", "sans_pneu"],
    facultatifs: [],
  },

  // --- réponses (lot 11, 25/09/2026) --------------------------------------
  //
  // L'enveloppe d'abord (`Enveloppe<T>`/`Simple<T>`, génériques : un seul
  // bloc source, vérifié contre chaque schéma qui l'utilise), puis le
  // contenu (`donnees`) de chaque route, type par type.

  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseBoucle",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseGeocodage",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseMeteo",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseVentDepart",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseSemaine",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseSeance",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseSeanceDeposee",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Enveloppe<T> {",
    schema: "ReponseSortie",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees", "avertissements", "duree_ms", "budget"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Simple<T> {",
    schema: "ReponseCalibrations",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Simple<T> {",
    schema: "ReponseZones",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Simple<T> {",
    schema: "ReponseProfilIntervals",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Simple<T> {",
    schema: "ReponseProfil",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "donnees"],
    facultatifs: [],
  },

  // Le contenu (« donnees ») de chaque route, type par type.

  {
    fichier: "api/types.ts",
    ancre: "export interface Boucle {",
    schema: "DonneesBoucle",
    genre: "type",
    sens: "reponse",
    champs: ["depart", "demande", "compteur", "meteo_absente", "gpx", "candidates", "depart_par_defaut"],
    facultatifs: ["compteur"],
    // Le schéma le dit requis (nullable) ; le front le garde facultatif pour
    // rester lisible sur une réponse d'avant le 18/09/2026 (commentaire du
    // champ, `types.ts`).
    facultatifsConnus: ["compteur"],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Geocodage {",
    schema: "DonneesGeocodage",
    genre: "type",
    sens: "reponse",
    champs: ["adresse", "candidats", "ambigu", "motif_ambiguite"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Meteo {",
    schema: "DonneesMeteo",
    genre: "type",
    sens: "reponse",
    champs: ["depart", "debut", "horizon_h", "modele", "second_avis", "meilleure_direction", "cellules"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface VentDepart {",
    schema: "DonneesVentDepart",
    genre: "type",
    sens: "reponse",
    champs: [
      "jour",
      "depart",
      "posee",
      "motif",
      "vent_kmh",
      "vent_depuis_deg",
      "vent_depuis_nom",
      "seuil_kmh",
      "horizon_jours",
      "choix",
      "azimuts_par_choix",
    ],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Semaine {",
    schema: "DonneesSemaine",
    genre: "type",
    sens: "reponse",
    champs: ["depuis", "jusqua", "jours"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Seance {",
    schema: "DonneesSeance",
    genre: "type",
    sens: "reponse",
    champs: ["jour", "nom", "duree_s", "n_blocs", "distance_estimee_m", "etapes", "avertissements", "meta"],
    facultatifs: [],
  },
  {
    // `GET /seances/{jour}` sans séance ce jour-là : `donnees` prend cette
    // forme-ci plutôt que la précédente (`api/client.ts::seance`).
    fichier: "api/client.ts",
    ancre: "Enveloppe<Seance | {",
    schema: "DonneesJourSansSeance",
    genre: "type",
    sens: "reponse",
    champs: ["jour", "seance"],
    facultatifs: [],
  },
  {
    // `POST /seances/fichier` : le second membre de l'intersection
    // (`Enveloppe<Seance> & { fichier: … }`) — la partie `Enveloppe<Seance>`
    // est déjà vérifiée par la ligne « ReponseSeanceDeposee » ci-dessus.
    fichier: "api/client.ts",
    ancre: "Enveloppe<Seance> & {",
    schema: "ReponseSeanceDeposee",
    genre: "type",
    sens: "reponse",
    champs: ["fichier"],
    facultatifs: [],
  },
  {
    // Le détail du `fichier` ci-dessus : le front n'y lit que `id` (pour la
    // resoumission) et `nom` — jamais `url`, que `FichierServi` porte aussi.
    fichier: "api/client.ts",
    ancre: "& { fichier: {",
    schema: "FichierServi",
    genre: "type",
    sens: "reponse",
    champs: ["id", "nom"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface FicheFichier {",
    schema: "FichierServi",
    genre: "type",
    sens: "reponse",
    champs: ["id", "nom", "url"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Sortie {",
    schema: "DonneesSortie",
    genre: "type",
    sens: "reponse",
    champs: [
      "jour",
      "seance",
      "demande",
      "compteur",
      "modele_physique",
      "modele_meteo",
      "meteo_absente",
      "generation",
      "gpx",
      "carte",
      "tenue",
      "propositions",
      "question_vent",
      "motif_deux_propositions",
      "motif_equivalence",
      "ecartees",
      "arbitrage",
      "candidates",
      "depart_par_defaut",
    ],
    facultatifs: ["compteur", "ecartees", "arbitrage", "generation"],
    // `compteur`, `ecartees`, `arbitrage` : le schéma les dit requis, le
    // front les garde facultatifs pour rester lisible sur une réponse plus
    // ancienne (commentaire de chaque champ, `types.ts`). `generation` : le
    // schéma ne le dit pas requis non plus — corrigé de « toujours présent »
    // à facultatif dans ce lot, voir le commentaire du champ (`types.ts`).
    facultatifsConnus: ["compteur", "ecartees", "arbitrage"],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Zones {",
    schema: "DonneesZones",
    genre: "type",
    sens: "reponse",
    champs: ["ftp_w", "position_zone", "zone_endurance", "hors_bande", "zones", "valeurs_liees"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Profil {",
    schema: "DonneesProfil",
    genre: "type",
    sens: "reponse",
    champs: ["depart", "cycliste", "velos", "seance", "historique_depuis", "services", "assistant_recommande"],
    facultatifs: [],
  },
  {
    // T1 de l'accueil (`GET /profil/intervals`) : un littéral en ligne,
    // jamais nommé côté front.
    fichier: "api/client.ts",
    ancre: "Simple<{",
    schema: "DonneesProfilIntervals",
    genre: "type",
    sens: "reponse",
    champs: ["ftp_w", "masse_kg"],
    facultatifs: [],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface EtatCalibrations {",
    schema: "DonneesCalibrations",
    genre: "type",
    sens: "reponse",
    champs: ["sorties_necessaires", "ftp_renseignee", "velos", "quota"],
    facultatifs: ["quota"],
    // `quota` : ajouté au dict par la route en mode hébergé
    // (`api/routes/calibrations.py::etat_calibrations`), hors du modèle
    // pydantic qui décrit `DonneesCalibrations` — `extra="allow"` l'admet,
    // openapi ne le décrit pas.
    champsHorsSchema: ["quota"],
  },
  {
    fichier: "api/types.ts",
    ancre: "export interface Systeme {",
    schema: "ReponseSysteme",
    genre: "type",
    sens: "reponse",
    champs: ["proprietaire", "version", "capacites", "budgets"],
    facultatifs: [],
  },
  {
    // Le détail de `capacites` ci-dessus, en ligne dans `Systeme`.
    fichier: "api/types.ts",
    ancre: "capacites: {",
    schema: "Capacites",
    genre: "type",
    sens: "reponse",
    champs: ["intervals", "brouter", "velos"],
    facultatifs: [],
  },
  {
    // `Meteo.depart` : le seul endroit où `PointDepart` reflète un schéma
    // imbriqué nommé (`Lieu`) plutôt qu'un dictionnaire ouvert — `Boucle.depart`
    // et `Sortie.demande.lieu_depart` restent génériques côté serveur.
    fichier: "api/types.ts",
    ancre: "export interface PointDepart {",
    schema: "Lieu",
    genre: "type",
    sens: "reponse",
    champs: ["nom", "latitude", "longitude", "par_defaut"],
    facultatifs: ["par_defaut"],
    // `par_defaut` sert `Profil.depart` (fiche
    // `docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md`) ; `Lieu`
    // (`GET /meteo`) ne le décrit pas — `PointDepart` reste le seul type
    // partagé, ce champ-là n'a de sens qu'au profil.
    champsHorsSchema: ["par_defaut"],
  },
];

/**
 * Les réponses 200 avec schéma que la table ci-dessus ne couvre pas, et
 * pourquoi. Un schéma de réponse qui n'est ni dans la table ni ici fait
 * échouer le test « toute réponse 200… ».
 */
const NON_COUVERTES_REPONSES: Record<string, string> = {
  // `donnees` y reste un dictionnaire ouvert (`api/reponses.py::ReponseCalcul`) :
  // aucun champ précis à comparer à un type du front.
  ReponseCalcul: "enveloppe générique (simulations, analyse de parcours, routes apprises) — donnees non typé",
  // Le front n'appelle aucune de ces deux routes aujourd'hui.
  ReponseInventaire: "le front n'appelle pas GET /inventaire",
  ReponseBudgets: "le front n'appelle pas GET /systeme/budgets (il lit budgets sur GET /systeme)",
};

/**
 * Les schémas de requête openapi que la table ne couvre pas, et pourquoi.
 * Un schéma de requête qui n'est ni dans la table ni ici fait échouer le test.
 */
const NON_COUVERTS: Record<string, string> = {
  DemandeSimulation: "le front n'appelle pas POST /simulations",
  Body_deposer_parcours_api_v1_parcours_fichier_post: "corps multipart (FormData)",
  Body_deposer_seance_api_v1_seances_fichier_post: "corps multipart (FormData)",
  Body_importer_activites_api_v1_activites_import_post: "corps multipart (FormData)",
};

// --- La lecture du TypeScript comme texte -------------------------------

/** Retire les commentaires `/* … *\/` et `// …` (sans s'occuper des chaînes :
 * aucune déclaration lue ici n'en contient qui ressemble à un commentaire). */
function sansCommentaires(texte: string): string {
  return texte.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

/** Le contenu entre l'accolade qui termine `ancre` et son accolade fermante. */
function blocsApres(source: string, ancre: string): string[] {
  const blocs: string[] = [];
  let depart = source.indexOf(ancre);
  while (depart !== -1) {
    const ouverture = depart + ancre.length - 1; // l'ancre finit par « { »
    let profondeur = 0;
    for (let i = ouverture; i < source.length; i += 1) {
      if (source[i] === "{") profondeur += 1;
      else if (source[i] === "}") {
        profondeur -= 1;
        if (profondeur === 0) {
          blocs.push(source.slice(ouverture + 1, i));
          break;
        }
      }
    }
    depart = source.indexOf(ancre, depart + ancre.length);
  }
  return blocs;
}

/**
 * Les champs de premier niveau d'un bloc `{ … }`.
 *
 * On découpe le bloc aux `;`, `,` et fins de ligne **de profondeur nulle**
 * (hors `{}`, `()`, `[]`, `<>`), puis on lit le nom en tête de chaque
 * morceau avec une expression simple : `^nom(?)?` suivi de `:` ou de rien
 * (raccourci `{ jeton, secret }`). Un `?` juste après le nom le rend
 * facultatif. Limite : un `=>` de profondeur nulle fausserait le compte des
 * `<>` — aucune des déclarations de la table n'en a.
 */
function champsDuBloc(bloc: string): { nom: string; facultatif: boolean }[] {
  const morceaux: string[] = [];
  let courant = "";
  let profondeur = 0;
  for (const c of sansCommentaires(bloc)) {
    if ("{([<".includes(c)) profondeur += 1;
    if ("})]>".includes(c)) profondeur -= 1;
    if (profondeur === 0 && (c === ";" || c === "," || c === "\n")) {
      morceaux.push(courant);
      courant = "";
    } else courant += c;
  }
  morceaux.push(courant);
  const champs: { nom: string; facultatif: boolean }[] = [];
  for (const morceau of morceaux) {
    const trouve = /^\s*([A-Za-z_$][\w$]*)(\?)?\s*(?::|$)/.exec(morceau);
    if (trouve) champs.push({ nom: trouve[1], facultatif: trouve[2] === "?" });
  }
  return champs;
}

const SOURCES: Record<Correspondance["fichier"], string> = {
  "api/types.ts": readFileSync(join(RACINE_FRONT, "src", "api", "types.ts"), "utf8"),
  "api/client.ts": readFileSync(join(RACINE_FRONT, "src", "api", "client.ts"), "utf8"),
};

const trie = (liste: string[]) => [...liste].sort();

// --- Les tests ------------------------------------------------------------

describe("la lecture du TypeScript", () => {
  it("lit les champs, l'optionnalité et ignore l'imbriqué et les commentaires", () => {
    const bloc = `
      /** un commentaire: piège */
      a: string;
      b?: { c: number; d?: string };
      e?: Record<string, unknown>, // fin: de ligne
      f`;
    expect(champsDuBloc(bloc)).toEqual([
      { nom: "a", facultatif: false },
      { nom: "b", facultatif: true },
      { nom: "e", facultatif: true },
      { nom: "f", facultatif: false },
    ]);
  });

  it("lit un objet littéral", () => {
    expect(champsDuBloc(" velo, sans_pneu: sansPneu ").map((c) => c.nom)).toEqual(["velo", "sans_pneu"]);
  });
});

describe.each(TABLE)("$fichier · $ancre → openapi $schema", (ligne) => {
  const schema = reference.components.schemas[ligne.schema];
  const proprietes = Object.keys(schema?.properties ?? {});
  const requis = schema?.required ?? [];
  const obligatoires = ligne.champs.filter((c) => !ligne.facultatifs.includes(c));

  it("la table décrit le type réel (lu dans la source)", () => {
    const blocs = blocsApres(SOURCES[ligne.fichier], ligne.ancre);
    expect(blocs.length, `ancre introuvable : ${ligne.ancre}`).toBeGreaterThan(0);
    for (const bloc of blocs) {
      const lus = champsDuBloc(bloc);
      expect(trie(lus.map((c) => c.nom))).toEqual(trie(ligne.champs));
      expect(trie(lus.filter((c) => c.facultatif).map((c) => c.nom))).toEqual(trie(ligne.facultatifs));
    }
  });

  it("le schéma existe dans openapi", () => {
    expect(schema, `schéma absent : ${ligne.schema}`).toBeDefined();
    expect(proprietes.length).toBeGreaterThan(0);
  });

  it("chaque champ du front existe dans le schéma, sous le même nom, sauf écart documenté", () => {
    const horsSchema = ligne.champsHorsSchema ?? [];
    const inattendus = ligne.champs.filter((c) => !proprietes.includes(c) && !horsSchema.includes(c));
    expect(inattendus).toEqual([]);
    // Et réciproquement : un écart documenté qui existe bel et bien dans le
    // schéma aujourd'hui est périmé — il devrait redevenir une vérification.
    expect(horsSchema.filter((c) => proprietes.includes(c))).toEqual([]);
  });

  if (ligne.sens === "requete") {
    it("le front envoie tout ce que le schéma exige", () => {
      expect(requis.filter((c) => !obligatoires.includes(c))).toEqual([]);
    });
    if (ligne.genre === "type") {
      it("un champ facultatif côté front l'est aussi dans le schéma, et réciproquement", () => {
        expect(ligne.facultatifs.filter((c) => requis.includes(c))).toEqual([]);
        expect(obligatoires.filter((c) => !requis.includes(c))).toEqual([]);
      });
    }
  } else {
    // Une réponse n'oblige pas le front à tout lire (voir l'en-tête) : on ne
    // regarde que les champs qu'il déclare *ici*, jamais ceux qu'il omet.
    const requisEtDeclares = requis.filter((c) => ligne.champs.includes(c));

    it("un champ déclaré par le front et requis par le schéma n'est pas tenu pour facultatif, sauf écart documenté", () => {
      const manquants = requisEtDeclares.filter((c) => !obligatoires.includes(c));
      expect(trie(manquants)).toEqual(trie(ligne.facultatifsConnus ?? []));
    });
    it("les champs tenus pour présents hors schéma sont exactement les écarts connus", () => {
      const horsSchema = obligatoires.filter((c) => !requis.includes(c));
      expect(trie(horsSchema)).toEqual(trie(ligne.garantisHorsSchema ?? []));
    });
  }
});

describe("la couverture de la référence", () => {
  const operations = Object.values(reference.paths).flatMap((methodes) => Object.values(methodes));
  const refs = (schema: SchemaObjet | undefined) => (schema?.$ref ? [schema.$ref.split("/").pop()!] : []);

  it("chaque schéma de requête est dans la table, ou écarté avec sa raison", () => {
    const requetes = new Set(
      operations.flatMap((op) =>
        Object.values(op.requestBody?.content ?? {}).flatMap((contenu) => refs(contenu.schema)),
      ),
    );
    const couverts = new Set([...TABLE.map((l) => l.schema), ...Object.keys(NON_COUVERTS)]);
    expect([...requetes].filter((nom) => !couverts.has(nom)).sort()).toEqual([]);
    // Et réciproquement : une raison d'écarter un schéma qui n'existe plus est périmée.
    expect(Object.keys(NON_COUVERTS).filter((nom) => !(nom in reference.components.schemas))).toEqual([]);
  });

  it("toute réponse 200 avec schéma est dans la table, ou écartée avec sa raison", () => {
    const typees: string[] = [];
    for (const [chemin, methodes] of Object.entries(reference.paths)) {
      for (const [methode, op] of Object.entries(methodes)) {
        const schema = op.responses?.["200"]?.content?.["application/json"]?.schema;
        if (!schema) continue;
        const nomme = refs(schema)[0];
        const sansChamps = !schema.$ref && !schema.properties;
        const couverte = nomme && (TABLE.some((l) => l.schema === nomme) || nomme in NON_COUVERTES_REPONSES);
        if (!sansChamps && !couverte) {
          typees.push(`${methode.toUpperCase()} ${chemin}`);
        }
      }
    }
    expect(typees).toEqual([]);
    // Et réciproquement : une raison d'écarter un schéma qui n'existe plus est périmée.
    expect(Object.keys(NON_COUVERTES_REPONSES).filter((nom) => !(nom in reference.components.schemas))).toEqual(
      [],
    );
  });

  it("les réponses en panne suivent ReponseErreur → Panne", () => {
    const enveloppe = reference.components.schemas.ReponseErreur;
    expect(enveloppe.required).toEqual(["erreur"]);
    expect(refs(enveloppe.properties?.erreur as SchemaObjet)).toEqual(["Panne"]);
  });
});

describe("les codes de panne", () => {
  const enumeration = (
    reference.components.schemas.Panne.properties?.code as { enum?: string[] } | undefined
  )?.enum ?? [];

  it("chaque titre nommé par le front correspond à un code du contrat", () => {
    expect(enumeration.length).toBeGreaterThan(0);
    expect(Object.keys(TITRES_PANNE).filter((code) => !enumeration.includes(code))).toEqual([]);
  });

  it("les trois codes fabriqués par le front ne sont pas des codes de l'API", () => {
    expect([CODE_INJOIGNABLE, CODE_DELAI, CODE_ILLISIBLE].filter((c) => enumeration.includes(c))).toEqual([]);
  });
});

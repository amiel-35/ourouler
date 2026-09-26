/** Le seul endroit du front qui parle au serveur.
 *
 * Doctrine §10.2 : le front ne parle jamais au cœur, il consomme l'API. Ce
 * module est donc la frontière — aucun écran n'appelle `fetch` lui-même, et
 * aucun écran ne fabrique une valeur que l'API n'a pas rendue.
 *
 * Une panne a toujours un **code**, jamais seulement un message : c'est le
 * code qui choisit l'écran d'échec, parce que le message vient du cœur et
 * peut être reformulé (`docs/ux/api_contrat.md`).
 */

import type {
  AccesOuvert,
  Analyse,
  ApercuParcours,
  Boucle,
  DonneesSeules,
  EffacementCompte,
  Enveloppe,
  EtatCalibrations,
  EtatImport,
  JobCalibration,
  Geocodage,
  Invitation,
  JobImport,
  Meteo,
  MonCompte,
  Panne,
  Profil,
  Seance,
  Semaine,
  Simple,
  Sortie,
  Systeme,
  VentDepart,
  Zones,
} from "./types";

export const RACINE = "/api/v1";

/**
 * Les trois codes que **le front fabrique**, parce que l'API n'a rien dit.
 *
 * Tous les autres codes viennent du serveur et sont ceux du contrat. Ces
 * trois-là nomment l'inverse : une requête qui n'aboutit pas, un délai
 * dépassé, une réponse illisible. Ils sont publiés dans
 * `docs/ux/api_contrat.md` sous « Ce que le front nomme quand l'API n'a rien
 * dit », pour qu'un écran puisse les reconnaître comme les autres.
 *
 * **La distinction que l'écran doit pouvoir faire** : « le serveur ne répond
 * pas » (il faut le lancer, ou l'adresse est fausse) n'est pas « le serveur a
 * refusé » (il tourne, et il dit pourquoi). Les confondre envoie le cycliste
 * chercher un problème dans sa demande alors qu'il n'y a personne au bout.
 */
export const CODE_INJOIGNABLE = "serveur_injoignable";
export const CODE_DELAI = "delai_depasse";
export const CODE_ILLISIBLE = "reponse_illisible";

/**
 * Le code que le **serveur** rend, lui, quand aucune session n'est ouverte
 * (`api/session.py:CODE_SANS_SESSION`, lot L7.2-D). Nommé ici, à côté des
 * trois codes que le front fabrique, parce que c'est à cette même frontière
 * qu'il déclenche `surSessionAbsente` ci-dessous — un seul endroit qui
 * reconnaît ce code, plutôt qu'une chaîne « session_absente » recopiée dans
 * chaque écran qui pourrait le recevoir.
 */
export const CODE_SESSION_ABSENTE = "session_absente";

type EcouteurSessionAbsente = () => void;
let ecouteurSessionAbsente: EcouteurSessionAbsente | null = null;

/**
 * Quelle session est en cours. Un simple compteur, incrémenté à chaque
 * réouverture.
 *
 * **Pourquoi il faut ça.** Une requête partie avant l'expiration du cookie
 * peut revenir *après* que le cycliste s'est reconnecté — le temps d'une
 * recherche de sortie, c'est courant. Sans repère, son `session_absente`
 * tardif rouvrait l'écran de connexion alors que la session venait d'être
 * ouverte avec succès : il retapait son mot de passe sans comprendre
 * pourquoi (trouvé en relecture le 19/09/2026, prouvé en laissant une requête
 * en vol pendant la reconnexion).
 *
 * Chaque appel retient la génération sous laquelle il est parti, et ne
 * prévient l'application que si elle n'a pas changé entre-temps. Une réponse
 * qui parle d'une session révolue est ignorée, ce qui est exactement ce
 * qu'elle mérite.
 */
let generationSession = 0;

/** À appeler quand une session vient d'être ouverte : ce qui précède est périmé. */
export function sessionRouverte(): void {
  generationSession += 1;
}

/**
 * S'abonne au moment où **n'importe quel** appel à l'API répond
 * `session_absente` — un seul écouteur à la fois, c'est l'application elle-
 * même (`App.tsx`) qui s'y abonne au montage pour afficher l'écran de
 * connexion à la place de ce qu'elle montrait.
 *
 * Centralisé ici plutôt que vérifié route par route : `session_absente` peut
 * sortir de **toute** route de données (`api/routes.py`, dépendance
 * `proprietaire`), pas seulement des trois appels de démarrage — une séance
 * qui expire pendant que le cycliste choisit une proposition doit amener le
 * même écran, pas une erreur technique nue.
 */
export function surSessionAbsente(ecouteur: EcouteurSessionAbsente | null): void {
  ecouteurSessionAbsente = ecouteur;
}

/**
 * Au bout de combien de temps on cesse d'attendre.
 *
 * Deux valeurs et pas une : une lecture de profil qui met trente secondes est
 * cassée, une génération de parcours qui met trois minutes ne l'est pas — elle
 * enchaîne cinq à huit appels BRouter et autant d'Open-Meteo, et l'API
 * sérialise les calculs (`docs/ux/api_contrat.md`). Sans délai du tout, une
 * requête partie dans le vide laisse l'écran d'attente tourner jusqu'à ce que
 * le cycliste recharge la page — l'écran muet que les maquettes interdisent.
 */
export const DELAI_MS = 30_000;
export const DELAI_CALCUL_MS = 180_000;

/** Le motif d'abandon qui vient de notre minuterie, et non de l'appelant. */
const MOTIF_DELAI = { delai: true } as const;

export class ErreurApi extends Error {
  readonly code: string;
  readonly statut: number;
  readonly service: string | null;
  /** Les mesures que la panne porte, quand elle en porte.
   *
   * L'API les remplit depuis le 17/09/2026 pour le refus sur la distance
   * (Q41 d) : sans elles, E18 · échec ne pouvait dire que « réessayez ». Le
   * type reste volontairement ouvert — c'est le `code` qui est le contrat,
   * pas la forme des détails, et chaque écran vérifie ce qu'il lit.
   */
  readonly details: Record<string, unknown>;

  constructor(panne: Panne, statut: number) {
    super(panne.message);
    this.name = "ErreurApi";
    this.code = panne.code;
    this.statut = statut;
    this.service = panne.service;
    this.details = panne.details ?? {};
  }
}

/**
 * Vrai quand la panne vient de ce qu'aucune API n'a répondu.
 *
 * C'est le test que fait l'écran d'échec pour choisir entre « le serveur ne
 * répond pas » et « le serveur a refusé » — jamais le statut HTTP, qui vaut
 * 500 aussi bien pour un bug de l'API que pour un proxy de développement dont
 * la cible est éteinte.
 */
export function serveurMuet(erreur: ErreurApi): boolean {
  return [CODE_INJOIGNABLE, CODE_DELAI, CODE_ILLISIBLE].includes(erreur.code);
}

/** Vrai quand un nouvel essai a une chance d'aboutir. */
export function reessayable(erreur: ErreurApi): boolean {
  return [
    CODE_INJOIGNABLE,
    CODE_DELAI,
    CODE_ILLISIBLE,
    "calcul_en_cours",
    "brouter_indisponible",
    "meteo_indisponible",
    "intervals_indisponible",
    "geocodage_indisponible",
    "service_externe_indisponible",
  ].includes(erreur.code);
}

/**
 * La panne d'une réponse en échec, pour le partage du GPX (`Proposition.tsx`,
 * bouton « Envoyer vers mon compteur »).
 *
 * Cette requête doit rester un `fetch` brut — le navigateur a besoin d'un
 * fichier, pas d'un JSON désérialisé, pour le passer à `navigator.share` —
 * mais une réponse en échec porte la même enveloppe `{erreur}` que partout
 * ailleurs, et la lire ici évite d'inventer une seconde façon de reconnaître
 * une panne de l'API. Trouvé le 18/09/2026 : `partager` avalait toute
 * réponse en échec (un GPX de génération oubliée, par exemple —
 * `generation_introuvable`) sous « ce navigateur ne sait pas partager de
 * fichier », qui n'est vrai que la moitié du temps et jamais quand c'est le
 * serveur qui a refusé.
 *
 * Le bouton « Télécharger le GPX », lui, reste un `<a href download>` natif
 * (`tests/gpx_proposition.test.tsx` vérifie son `href`/`download` exacts) :
 * cette fonction ne le concerne pas.
 */
export async function panneDeReponseGpx(reponse: Response): Promise<{ code: string; message: string }> {
  const texte = await reponse.text();
  try {
    const charge = texte ? JSON.parse(texte) : null;
    const panne = (charge as { erreur?: Panne } | null)?.erreur;
    if (panne?.code && panne.message) return { code: panne.code, message: panne.message };
  } catch {
    // Pas du JSON : ce n'est pas l'API qui a répondu (proxy, passerelle…),
    // le code générique et le statut suffisent.
  }
  return {
    code: CODE_ILLISIBLE,
    message: `la réponse reçue n'est pas celle d'où rouler (HTTP ${reponse.status})`,
  };
}

/** Ce qu'une panne du partage GPX affiche — jamais un code technique nu. */
export interface PanneGpx {
  code: string;
  message: string;
}

/**
 * Récupère le GPX d'une proposition, pour le bouton « Envoyer vers mon
 * compteur » de `ecrans/Proposition.tsx`.
 *
 * **Reste un `fetch` brut** — le navigateur a besoin d'un fichier, pas d'un
 * JSON désérialisé, pour le passer à `navigator.share` — mais il vit ici,
 * avec `appeler` ci-dessous : `api/client.ts` est le seul module du front
 * qui touche au réseau (`docs/ouverture_plan.md` §7, `tests/reseau_unique.
 * test.ts`).
 *
 * Distingue les deux échecs qui n'appellent pas le même mot : le réseau ne
 * répond pas du tout (`fetch` jette un `TypeError`, hors ligne ou serveur
 * éteint — pas de JSON à lire, donc le code et la phrase de
 * `CODE_INJOIGNABLE`, plutôt que de laisser fuir le texte technique de
 * l'exception du navigateur), ou le serveur a répondu et refusé (une panne
 * nommée, lue par `panneDeReponseGpx`).
 */
export async function recupererGpx(url: string): Promise<Blob> {
  let reponse: Response;
  try {
    reponse = await fetch(url);
  } catch {
    throw {
      code: CODE_INJOIGNABLE,
      message: "le serveur d'où rouler ne répond pas — vérifiez qu'il tourne",
    } satisfies PanneGpx;
  }
  if (!reponse.ok) throw await panneDeReponseGpx(reponse);
  return reponse.blob();
}

function url(chemin: string, parametres?: Record<string, string | number | undefined>): string {
  const requete = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(parametres ?? {})) {
    if (valeur !== undefined && valeur !== null && valeur !== "") {
      requete.set(cle, String(valeur));
    }
  }
  const suffixe = requete.toString();
  return `${RACINE}${chemin}${suffixe ? `?${suffixe}` : ""}`;
}

/** Une minuterie qui abandonne la requête, et qui se laisse doubler par l'appelant. */
function minuterie(delai_ms: number, externe?: AbortSignal) {
  const controleur = new AbortController();
  const jeton = setTimeout(() => controleur.abort(MOTIF_DELAI), delai_ms);
  const repercuter = () => controleur.abort(externe?.reason);
  if (externe) {
    if (externe.aborted) repercuter();
    else externe.addEventListener("abort", repercuter);
  }
  return {
    signal: controleur.signal,
    /** Vrai quand c'est **nous** qui avons abandonné, et non l'appelant. */
    expiree: () => controleur.signal.reason === MOTIF_DELAI,
    finir: () => {
      clearTimeout(jeton);
      externe?.removeEventListener("abort", repercuter);
    },
  };
}

/**
 * Un appel à l'API, et la famille entière de ce qui peut l'empêcher d'aboutir.
 *
 * Quatre issues, pas deux (corrigé le 17/09/2026) :
 *
 * 1. **Rien ne répond** — `fetch` jette : serveur éteint, adresse fausse,
 *    réseau coupé.
 * 2. **Le délai est dépassé** — la requête est partie, rien ne revient.
 * 3. **Quelque chose répond, mais ce n'est pas l'API** — c'est le cas qui
 *    était passé au travers, et il est le plus courant en développement : le
 *    proxy de Vite, dont la cible est éteinte ou sur un autre port, rend un
 *    **500 `text/plain` au corps vide**. Le `fetch` réussit, la branche 1 ne
 *    se déclenche jamais, et l'écran affichait « le serveur a répondu 500 sans
 *    rien expliquer », sans geste et sans bouton — alors que la cause est
 *    exactement celle de la branche 1.
 *    **Le critère est le contrat, pas le statut** : `api_contrat.md` garantit
 *    que *toute* réponse de l'API est du JSON, pannes comprises. Une réponse
 *    qui ne parse pas ne vient donc pas de l'API mais d'un intermédiaire, et
 *    un 500 de l'API elle-même reste distinct — il porte son enveloppe.
 * 4. **L'API a refusé** — l'enveloppe `{erreur: {code, …}}` est là, elle passe
 *    telle quelle : c'est le serveur qui parle, pas nous.
 */
async function appeler<T>(
  chemin: string,
  options: RequestInit = {},
  delai_ms: number = DELAI_MS,
): Promise<T> {
  const horloge = minuterie(delai_ms, options.signal ?? undefined);
  // Retenu **avant** de partir : c'est ce qui permettra, au retour, de savoir
  // si la réponse parle encore de la session en cours (voir `generationSession`).
  const generation = generationSession;
  let reponse: Response;
  try {
    // **`credentials: "same-origin"`, explicite** (lot L7.2-D). Le cookie de
    // session est `HttpOnly` : ce module ne le lit ni ne l'écrit jamais, mais
    // il doit accompagner chaque requête pour que le serveur sache qui parle.
    // Le défaut du navigateur est déjà `same-origin` — et le front n'appelle
    // que des chemins relatifs sous `/api/v1` (`front/README.md`), donc
    // toujours la même origine que la page — mais un défaut silencieux n'est
    // pas quelque chose sur quoi une session tout entière devrait reposer.
    reponse = await fetch(chemin, { ...options, credentials: "same-origin", signal: horloge.signal });
  } catch (cause) {
    if (horloge.expiree()) {
      throw new ErreurApi(
        {
          code: CODE_DELAI,
          message: `le serveur d'où rouler n'a pas répondu en ${Math.round(
            delai_ms / 1000,
          )} secondes — il tourne peut-être, mais il ne rend pas la main`,
          service: null,
          details: { delai_ms },
        },
        0,
      );
    }
    // L'appelant a abandonné lui-même : ce n'est pas une panne, et ça ne
    // mérite pas un écran d'échec. On laisse passer l'erreur d'origine.
    if (options.signal?.aborted) throw cause;
    throw new ErreurApi(
      {
        code: CODE_INJOIGNABLE,
        message: "le serveur d'où rouler ne répond pas — vérifiez qu'il tourne",
        service: null,
        details: { cause: String(cause) },
      },
      0,
    );
  } finally {
    horloge.finir();
  }
  const texte = await reponse.text();
  let charge: unknown = null;
  let contrat = false;
  try {
    charge = texte ? JSON.parse(texte) : null;
    contrat = charge !== null;
  } catch {
    charge = null;
  }
  if (!reponse.ok) {
    const panne = (charge as { erreur?: Panne } | null)?.erreur;
    // **L'enveloppe, et elle seule, prouve que c'est l'API qui a refusé.**
    if (panne?.code) {
      // Prévenir l'application avant de jeter : le code sort de **cette**
      // fonction pour toute route, et c'est le seul endroit qui les voit
      // toutes passer.
      if (panne.code === CODE_SESSION_ABSENTE && generation === generationSession) {
        ecouteurSessionAbsente?.();
      }
      throw new ErreurApi(panne, reponse.status);
    }
    // Sinon, quelque chose a répondu à la place de l'API : proxy de
    // développement dont la cible est éteinte, passerelle sans amont. Le
    // statut ne sert pas à le reconnaître — Vite rend 500, une passerelle
    // rend 502, et l'API elle-même peut rendre un 500 qui, lui, porte son
    // enveloppe. Le geste, en revanche, est le même dans tous ces cas :
    // vérifier que l'API tourne, et à quelle adresse.
    throw new ErreurApi(
      {
        code: CODE_INJOIGNABLE,
        message:
          "le serveur d'où rouler ne répond pas — l'adresse répond, mais ce n'est pas " +
          "l'API qui parle",
        service: null,
        details: { statut: reponse.status },
      },
      reponse.status,
    );
  }
  if (!contrat) {
    // Une réponse acceptée qui ne porte pas de JSON : le plus souvent le
    // front lui-même servi sous `/api`, ou un portail qui intercepte. Ce
    // n'est pas la même chose qu'un serveur muet, et le geste diffère — c'est
    // l'adresse de l'API qui est à revoir, pas son état.
    throw new ErreurApi(
      {
        code: CODE_ILLISIBLE,
        message:
          "la réponse reçue n'est pas celle d'où rouler — l'adresse de l'API mène " +
          "peut-être ailleurs",
        service: null,
        details: { statut: reponse.status },
      },
      reponse.status,
    );
  }
  return charge as T;
}

export interface DemandeSortie {
  jour?: string;
  heure_depart?: string;
  distance_km?: number;
  direction?: string;
  candidates?: number;
  vent?: string;
  velo?: string;
  depart?: { latitude: number; longitude: number; nom?: string };
  fichier_seance?: string;
}

export interface DemandeBoucle {
  distance_km: number;
  // Q47 : facultative, comme côté `DemandeSortie` — sans direction, `/boucles`
  // balaie tout l'horizon au lieu de refuser.
  direction?: string;
  heure_depart?: string;
  candidates?: number;
  velo?: string;
  puissance_w?: number;
  depart?: { latitude: number; longitude: number; nom?: string };
}

/** L9.8 : un parcours déjà en main (imposé d'un BRM, boucle de club) — `POST /parcours/analyser`. */
export interface DemandeAnalyse {
  gpx: string;
  /** Obligatoire ici (à la différence de `DemandeBoucle`) : sans elle, rien à caler. */
  heure_depart: string;
  velo?: string;
  /** Facultative : à défaut, la puissance d'endurance du profil (position_zone × FTP). */
  puissance_w?: number;
}

function poster<T>(
  chemin: string,
  corps: unknown,
  signal?: AbortSignal,
  delai_ms: number = DELAI_MS,
): Promise<T> {
  return appeler<T>(
    `${RACINE}${chemin}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(corps),
      signal,
    },
    delai_ms,
  );
}

export const api = {
  // --- comptes et sessions (lot L7.2-D) — précèdent tout propriétaire ------

  /** `GET /invitation` : l'état d'un jeton, sans le consommer. */
  invitation: (jeton: string) =>
    appeler<DonneesSeules<Invitation>>(url("/invitation", { jeton })),

  /** `POST /entrer` : active l'invitation, pose le secret choisi, ouvre la session. */
  entrer: (jeton: string, secret: string) =>
    poster<DonneesSeules<AccesOuvert>>("/entrer", { jeton, secret }),

  /** `POST /connexion` : revient sur un compte déjà actif, sans jeton. */
  connexion: (email: string, secret: string) =>
    poster<DonneesSeules<AccesOuvert>>("/connexion", { email, secret }),

  /** `POST /sortir` : révoque la session en cours. Toujours 200, même sans cookie. */
  sortir: () => poster<DonneesSeules<Record<string, never>>>("/sortir", {}),

  /**
   * `POST /reinitialiser` (lot L9.6) : consomme un jeton de réinitialisation, pose le
   * nouveau mot de passe, ferme les autres sessions du compte, ouvre celle-ci. Émis
   * uniquement par `ourouler reinitialiser` (mainteneur) — pas de « mot de passe
   * oublié » en libre-service ici.
   */
  reinitialiser: (jeton: string, secret: string) =>
    poster<DonneesSeules<AccesOuvert>>("/reinitialiser", { jeton, secret }),

  // --- mon compte (lot L9.6) — routes de données, sous session ouverte -----

  /** `GET /moi` : l'adresse du compte de la session en cours. */
  monCompte: () => appeler<Simple<MonCompte>>(url("/moi")),

  /** `POST /moi/mot-de-passe` : change le mot de passe — l'ancien est vérifié côté serveur. */
  changerMotDePasse: (motDePasseActuel: string, nouveauMotDePasse: string) =>
    poster<Simple<Record<string, never>>>("/moi/mot-de-passe", {
      mot_de_passe_actuel: motDePasseActuel,
      nouveau_mot_de_passe: nouveauMotDePasse,
    }),

  /**
   * `DELETE /moi` : efface les données personnelles du compte de la session en cours,
   * et ferme le compte lui-même. Irréversible — l'écran qui l'appelle porte la double
   * confirmation, pas ce module.
   */
  supprimerMesDonnees: () =>
    appeler<Simple<EffacementCompte>>(url("/moi"), { method: "DELETE" }),

  /**
   * `GET /moi/export`, l'adresse à donner à un lien de téléchargement — pas un appel
   * JSON : l'archive ZIP n'est pas une réponse que ce module désérialise, et un lien
   * `<a href download>` laisse le navigateur gérer le téléchargement et le cookie de
   * session (même origine, même geste que le GPX d'une proposition).
   */
  urlExportMesDonnees: () => `${RACINE}/moi/export`,

  systeme: () => appeler<Systeme>(url("/systeme")),

  profil: () => appeler<Simple<Profil>>(url("/profil")),

  modifierProfil: (sections: Record<string, unknown>) =>
    appeler<Simple<Profil>>(`${RACINE}/profil`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(sections),
    }),

  zones: (velo?: string, position?: number) =>
    appeler<Simple<Zones>>(url("/profil/zones", { velo, position })),

  /** Recalcule les trois valeurs liées sans rien stocker. Une entrée à la fois. */
  apercuZones: (entree: {
    position_zone?: number;
    puissance_w?: number;
    vitesse_a_plat_kmh?: number;
    velo?: string;
  }) => poster<Simple<Zones>>("/profil/zones/apercu", entree),

  /**
   * T1 de l'accueil : lit le profil de l'athlète sur Intervals.icu pour
   * confirmation, **n'écrit rien**. Répond 409 `intervals_absent` si la clé
   * n'est pas encore posée pour ce compte — un état normal à gérer, pas une
   * panne (`docs/ux/parcours_accueil.md` §4).
   */
  profilIntervals: () =>
    appeler<Simple<{ ftp_w: number | null; masse_kg: number | null }>>(url("/profil/intervals")),

  /**
   * T4 de l'accueil : une FTP à partir d'une vitesse au compteur et d'un
   * terrain déclarés, **n'écrit rien**.
   */
  apercuFtpDepuisTerrain: (entree: { vitesse_kmh: number; denivele_m_par_km: number; velo?: string }) =>
    poster<Simple<Zones>>("/profil/ftp/apercu", entree),

  /**
   * T5 de l'accueil, le fond du tunnel : une FTP à partir du seul poids déjà
   * enregistré, **n'écrit rien**. Ne peut jamais échouer côté serveur.
   */
  ftpGenerique: (velo?: string) => appeler<Simple<Zones>>(url("/profil/ftp/generique", { velo })),

  geocodage: (adresse: string) => appeler<Enveloppe<Geocodage>>(url("/geocodage", { adresse })),

  meteo: (parametres?: { heure_depart?: string; latitude?: number; longitude?: number }) =>
    appeler<Enveloppe<Meteo>>(url("/meteo", parametres)),

  /**
   * D'où vient le vent au départ, et ce que chaque préférence imposerait
   * (Q44) — appelée **pendant** que le cycliste choisit, pas après.
   */
  ventDepart: (parametres?: { jour?: string; heure_depart?: string }) =>
    appeler<Enveloppe<VentDepart>>(url("/vent-depart", parametres)),

  semaine: (depuis?: string, jusqua?: string) =>
    appeler<Enveloppe<Semaine>>(url("/seances", { depuis, jusqua })),

  /**
   * La séance d'un jour, ou `null` s'il n'y en a pas.
   *
   * **La réponse change de forme, et c'est voulu côté cœur** : quand la
   * séance existe, `donnees` *est* la séance ; quand elle n'existe pas,
   * `donnees` vaut `{jour, seance: null}` — 200, parce que « pas de séance ce
   * jour-là » n'est pas une erreur (`docs/ux/api_contrat.md`). Le front
   * ramène les deux à une seule forme ici, à la frontière, plutôt que de
   * laisser chaque écran deviner : un écran qui devine finit par lire
   * `etapes` sur un objet qui n'en a pas.
   */
  seance: async (jour: string): Promise<Enveloppe<Seance | null>> => {
    const reponse = await appeler<Enveloppe<Seance | { jour: string; seance: null }>>(
      url(`/seances/${jour}`),
    );
    const donnees = reponse.donnees as Partial<Seance> & { seance?: null };
    const vide = donnees.etapes === undefined || donnees.seance === null;
    return { ...reponse, donnees: vide ? null : (reponse.donnees as Seance) };
  },

  deposerSeance: (fichier: File, jour?: string) => {
    const corps = new FormData();
    corps.append("fichier", fichier);
    return appeler<Enveloppe<Seance> & { fichier: { id: string; nom: string } }>(
      url("/seances/fichier", { jour }),
      { method: "POST", body: corps },
    );
  },

  /** Combien de sorties déjà déposées, et sur quelle période (L9.2). */
  etatImport: () => appeler<Enveloppe<EtatImport>>(url("/activites/import")),

  /**
   * Lance en tâche de fond le dépôt de l'historique d'un cycliste sans
   * Intervals — un ou plusieurs fichiers `.fit`/`.gpx`/`.tcx` (`.gz`
   * compris), ou une archive `.zip` d'export Strava ou Garmin. Plusieurs
   * dépôts successifs sont le cas normal (Q62) : réimporter ne duplique
   * rien, c'est le serveur qui dédoublonne.
   *
   * **Rend un `JobImport` tout de suite (202), pas le rapport** : une
   * archive Strava réelle (≈2 900 sorties) prend environ 16 minutes à
   * importer, bien au-delà des 180 s où le front abandonne. `suivreImport`
   * dit où l'import en est. Le délai long reste sur *ce* seul appel : c'est
   * l'envoi de l'archive elle-même — plusieurs centaines de méga-octets —
   * qui peut dépasser les 30 s par défaut, pas le traitement.
   */
  importerActivites: (fichiers: File[]) => {
    const corps = new FormData();
    for (const fichier of fichiers) corps.append("fichiers", fichier);
    return appeler<Enveloppe<JobImport>>(
      url("/activites/import"),
      { method: "POST", body: corps },
      DELAI_CALCUL_MS,
    );
  },

  /** L'état d'un import lancé par `importerActivites` — à interroger périodiquement. */
  suivreImport: (id: string) => appeler<Enveloppe<JobImport>>(url(`/activites/import/${id}`)),

  /** Pour chaque vélo : sa calibration, ce qui la permettrait, la tâche récente (L9.4). */
  etatCalibrations: () => appeler<Simple<EtatCalibrations>>(url("/calibrations")),

  /**
   * Lance la calibration d'un vélo sur les sorties du cycliste (L9.4). Rend
   * un `JobCalibration` tout de suite (202) : le calcul relit toutes les
   * sorties et l'archive météo de chaque jour, il se suit par
   * `suivreCalibration`. `sansPneu` : calibrer quand même sans pneu déclaré
   * (la résistance au roulement de l'usage est alors gardée fixe).
   */
  calibrer: (velo: string, sansPneu = false) =>
    poster<Enveloppe<JobCalibration>>("/calibrations", { velo, sans_pneu: sansPneu }),

  /** L'état d'une calibration lancée par `calibrer` — à interroger périodiquement. */
  suivreCalibration: (id: string) =>
    appeler<Enveloppe<JobCalibration>>(url(`/calibrations/${id}`)),

  // Les deux seuls appels qui calculent : cinq à huit tracés BRouter et
  // autant d'appels Open-Meteo, sérialisés par le verrou de l'API. Ils ont
  // droit au délai long — les autres n'en ont pas besoin.
  sortie: (demande: DemandeSortie, signal?: AbortSignal) =>
    poster<Enveloppe<Sortie>>("/sorties", demande, signal, DELAI_CALCUL_MS),

  boucle: (demande: DemandeBoucle, signal?: AbortSignal) =>
    poster<Enveloppe<Boucle>>("/boucles", demande, signal, DELAI_CALCUL_MS),

  // L9.8 : un parcours déjà en main, à analyser plutôt qu'à chercher.
  deposerParcours: (fichier: File) => {
    const corps = new FormData();
    corps.append("fichier", fichier);
    return appeler<{ fichier: { id: string; nom: string }; apercu: ApercuParcours }>(
      url("/parcours/fichier"),
      { method: "POST", body: corps },
    );
  },

  analyserParcours: (demande: DemandeAnalyse, signal?: AbortSignal) =>
    poster<Enveloppe<Analyse>>("/parcours/analyser", demande, signal, DELAI_CALCUL_MS),
};

export type Api = typeof api;

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
  Boucle,
  Enveloppe,
  Geocodage,
  Meteo,
  Panne,
  Profil,
  Seance,
  Semaine,
  Simple,
  Sortie,
  Systeme,
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

  constructor(panne: Panne, statut: number) {
    super(panne.message);
    this.name = "ErreurApi";
    this.code = panne.code;
    this.statut = statut;
    this.service = panne.service;
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
  let reponse: Response;
  try {
    reponse = await fetch(chemin, { ...options, signal: horloge.signal });
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
    if (panne?.code) throw new ErreurApi(panne, reponse.status);
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
  direction: string;
  heure_depart?: string;
  candidates?: number;
  velo?: string;
  puissance_w?: number;
  depart?: { latitude: number; longitude: number; nom?: string };
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

  geocodage: (adresse: string) => appeler<Enveloppe<Geocodage>>(url("/geocodage", { adresse })),

  meteo: (parametres?: { heure_depart?: string; latitude?: number; longitude?: number }) =>
    appeler<Enveloppe<Meteo>>(url("/meteo", parametres)),

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

  // Les deux seuls appels qui calculent : cinq à huit tracés BRouter et
  // autant d'appels Open-Meteo, sérialisés par le verrou de l'API. Ils ont
  // droit au délai long — les autres n'en ont pas besoin.
  sortie: (demande: DemandeSortie, signal?: AbortSignal) =>
    poster<Enveloppe<Sortie>>("/sorties", demande, signal, DELAI_CALCUL_MS),

  boucle: (demande: DemandeBoucle, signal?: AbortSignal) =>
    poster<Enveloppe<Boucle>>("/boucles", demande, signal, DELAI_CALCUL_MS),
};

export type Api = typeof api;

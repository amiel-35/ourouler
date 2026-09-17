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

/** Le code que porte une panne dont l'API elle-même n'a pas répondu. */
export const CODE_INJOIGNABLE = "serveur_injoignable";

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

/** Vrai quand un nouvel essai a une chance d'aboutir. */
export function reessayable(erreur: ErreurApi): boolean {
  return [
    CODE_INJOIGNABLE,
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

async function appeler<T>(chemin: string, options: RequestInit = {}): Promise<T> {
  let reponse: Response;
  try {
    reponse = await fetch(chemin, options);
  } catch (cause) {
    // Le serveur n'a pas répondu du tout : ce n'est pas une panne de l'API,
    // c'est l'absence d'API. L'écran doit pouvoir le dire autrement.
    throw new ErreurApi(
      {
        code: CODE_INJOIGNABLE,
        message: "le serveur d'où rouler ne répond pas — vérifiez qu'il tourne",
        service: null,
        details: { cause: String(cause) },
      },
      0,
    );
  }
  const texte = await reponse.text();
  let charge: unknown = null;
  try {
    charge = texte ? JSON.parse(texte) : null;
  } catch {
    charge = null;
  }
  if (!reponse.ok) {
    const panne = (charge as { erreur?: Panne } | null)?.erreur;
    throw new ErreurApi(
      panne ?? {
        code: "erreur_interne",
        message: `le serveur a répondu ${reponse.status} sans rien expliquer`,
        service: null,
        details: {},
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

function poster<T>(chemin: string, corps: unknown, signal?: AbortSignal): Promise<T> {
  return appeler<T>(`${RACINE}${chemin}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(corps),
    signal,
  });
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

  sortie: (demande: DemandeSortie, signal?: AbortSignal) =>
    poster<Enveloppe<Sortie>>("/sorties", demande, signal),

  boucle: (demande: DemandeBoucle, signal?: AbortSignal) =>
    poster<Enveloppe<Boucle>>("/boucles", demande, signal),
};

export type Api = typeof api;

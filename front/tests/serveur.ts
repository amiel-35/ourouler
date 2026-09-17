/** Un serveur factice, et **rien qui touche au réseau** (règle absolue 3).
 *
 * Il rend ce qu'on lui a dit de rendre, et il **retient les requêtes** : c'est
 * ce qui permet de vérifier non seulement ce que l'écran affiche, mais aussi
 * ce qu'il envoie — par exemple qu'un enregistrement de zone porte une
 * position et jamais des watts (décision 7).
 */

export interface Requete {
  chemin: string;
  methode: string;
  corps: unknown;
}

export interface Reponse {
  statut?: number;
  charge?: unknown;
  /**
   * Un corps **brut**, rendu tel quel au lieu de `charge` sérialisée.
   *
   * Sert à jouer ce que rend un intermédiaire qui n'est pas l'API : le proxy
   * de développement de Vite, quand sa cible est éteinte, répond `500` en
   * `text/plain` avec un corps vide. Le contrat, lui, promet du JSON pour
   * toute réponse de l'API, pannes comprises — c'est cette différence-là que
   * le client doit savoir lire.
   */
  texte?: string;
}

export type Table = Record<string, Reponse | ((requete: Requete) => Reponse)>;

export class Serveur {
  readonly requetes: Requete[] = [];

  constructor(private table: Table) {}

  /** Les requêtes reçues sur un chemin, corps compris. */
  vers(prefixe: string): Requete[] {
    return this.requetes.filter((r) => r.chemin.startsWith(prefixe));
  }

  installer(): void {
    globalThis.fetch = (async (entree: RequestInfo | URL, options?: RequestInit) => {
      const chemin = String(entree);
      const methode = (options?.method ?? "GET").toUpperCase();
      let corps: unknown = null;
      if (typeof options?.body === "string") {
        try {
          corps = JSON.parse(options.body);
        } catch {
          corps = options.body;
        }
      } else if (options?.body) {
        corps = options.body;
      }
      const requete: Requete = { chemin, methode, corps };
      this.requetes.push(requete);

      const cle = Object.keys(this.table).find((motif) => chemin.startsWith(motif));
      if (cle === undefined) {
        throw new Error(`le serveur factice ne connaît pas ${methode} ${chemin}`);
      }
      const entreeTable = this.table[cle];
      const reponse = typeof entreeTable === "function" ? entreeTable(requete) : entreeTable;
      const statut = reponse.statut ?? 200;
      return {
        ok: statut >= 200 && statut < 300,
        status: statut,
        text: async () =>
          reponse.texte !== undefined ? reponse.texte : JSON.stringify(reponse.charge),
      } as Response;
    }) as typeof fetch;
  }
}

export function panne(code: string, message: string, statut: number): Reponse {
  return { statut, charge: { erreur: { code, message, service: null, details: {} } } };
}

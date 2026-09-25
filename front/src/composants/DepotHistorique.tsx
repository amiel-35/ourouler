/** E17 bis — L9.2 : déposer son historique, sans passer par Intervals.icu.
 *
 * Extrait de `ecrans/Importer.tsx` le 25/09/2026 (L9.7) pour que l'assistant
 * (T2, « Export Strava ou Garmin ») puisse proposer le même dépôt, tout de
 * suite, au lieu de dire que l'import « n'est pas encore proposé » — faux
 * depuis L9.2. La logique ne change pas d'un trait : suivi d'un import en
 * fond via `localStorage` (`etat/memoire.ts`), reprise après rechargement,
 * interrogation périodique tant qu'il tourne.
 *
 * Place *un* historique entier pour que les parcours proposés reconnaissent
 * les routes déjà connues — utile même sans capteur de puissance ([[Q48]] :
 * « l'import permet de comprendre les routes, la puissance permet de
 * comprendre le niveau — c'est 2 choses »).
 *
 * **L'import tourne en tâche de fond côté serveur** : le dépôt rend un
 * identifiant tout de suite, ce composant l'interroge périodiquement et
 * affiche une barre d'avancement plutôt que de bloquer sur un appel qui peut
 * durer un quart d'heure — l'appelant (l'assistant comme l'écran Déposer)
 * reste utilisable pendant ce temps.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ErreurApi } from "../api/client";
import type { EtatImport, JobImport } from "../api/types";
import { jourEnLettres, nombre } from "../api/formats";
import {
  importEnCoursRetenu,
  oublierImportEnCours,
  retenirImportEnCours,
} from "../etat/memoire";
import { Echec } from "./Echec";

/** Combien de temps entre deux interrogations de `GET /activites/import/{id}`. */
const DELAI_INTERROGATION_MS = 1_500;

interface Props {
  /** Le texte au-dessus de la zone de dépôt. Par défaut, l'explication
   * générique (Strava + Garmin) de l'écran Déposer ; l'assistant passe la
   * sienne, plus courte et déjà orientée sur la plateforme choisie. */
  intro?: ReactNode;
  /** L'assistant porte déjà son propre titre d'étape — un second « Mes
   * sorties passées » juste en dessous serait redondant. */
  masquerTitre?: boolean;
}

export function DepotHistorique({ intro, masquerTitre }: Props) {
  const [etat, setEtat] = useState<EtatImport | null>(null);
  const [job, setJob] = useState<JobImport | null>(null);
  const [erreur, setErreur] = useState<ErreurApi | null>(null);
  const [depotEnCours, setDepotEnCours] = useState(false);
  const [survole, setSurvole] = useState(false);
  const champ = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api
      .etatImport()
      .then((reponse) => setEtat(reponse.donnees))
      .catch(() => {
        // Un état qui ne charge pas n'empêche pas de déposer : l'écran reste
        // utilisable, il ne sait simplement pas encore dire « déjà XX sorties ».
      });
  }, []);

  // Reprend le suivi d'un import déjà en cours au moment où l'écran s'ouvre
  // — après un rechargement, ou une seconde visite pendant qu'il tournait.
  useEffect(() => {
    const id = importEnCoursRetenu();
    if (!id) return;
    api
      .suivreImport(id)
      .then((reponse) => setJob(reponse.donnees))
      .catch(() => oublierImportEnCours()); // job trop vieux, oublié par le serveur : on efface
  }, []);

  // Interroge périodiquement tant qu'un import tourne, et s'arrête net dès
  // qu'il ne tourne plus — un `setInterval` qui continuerait après « fini »
  // gaspillerait des appels pour rien.
  useEffect(() => {
    if (!job || job.statut !== "en_cours") return;
    const jeton = setInterval(() => {
      api
        .suivreImport(job.id)
        .then((reponse) => {
          setJob(reponse.donnees);
          if (reponse.donnees.statut !== "en_cours") {
            oublierImportEnCours();
            if (reponse.donnees.statut === "fini" && reponse.donnees.rapport) {
              setEtat((precedent) => ({
                nombre: (precedent?.nombre ?? 0) + reponse.donnees.rapport!.importees,
                premiere: precedent?.premiere ?? null,
                derniere: precedent?.derniere ?? null,
              }));
            }
          }
        })
        .catch(() => {
          // Un raté d'interrogation ne coupe pas le suivi : le prochain
          // intervalle réessaie. Le serveur, lui, continue l'import.
        });
    }, DELAI_INTERROGATION_MS);
    return () => clearInterval(jeton);
  }, [job]);

  async function deposer(fichiers: File[]) {
    if (!fichiers.length) return;
    setDepotEnCours(true);
    setErreur(null);
    try {
      const reponse = await api.importerActivites(fichiers);
      setJob(reponse.donnees);
      retenirImportEnCours(reponse.donnees.id);
    } catch (cause) {
      setErreur(
        cause instanceof ErreurApi
          ? cause
          : new ErreurApi(
              { code: "erreur_interne", message: String(cause), service: null, details: {} },
              0,
            ),
      );
    } finally {
      setDepotEnCours(false);
    }
  }

  const enCours = depotEnCours || job?.statut === "en_cours";

  return (
    <section className="mt-depot">
      {masquerTitre ? null : (
        <div className="app-tete">
          <h2>Mes sorties passées</h2>
        </div>
      )}
      {intro ?? (
        <p className="mention">
          Sans Intervals.icu, l'appli ne connaît vos routes qu'à partir de ce que vous déposez ici.
          Demandez votre export sur{" "}
          <a href="https://www.strava.com/athlete/download_my_account" target="_blank" rel="noreferrer">
            strava.com
          </a>{" "}
          ou{" "}
          <a href="https://www.garmin.com/en-US/account/datamanagement/" target="_blank" rel="noreferrer">
            garmin.com
          </a>{" "}
          — vous recevez une archive par courriel, à déposer ici telle quelle.
        </p>
      )}

      {etat && etat.nombre > 0 ? (
        <p className="mention">
          Déjà {nombre(etat.nombre)} sortie{etat.nombre > 1 ? "s" : ""} déposée
          {etat.nombre > 1 ? "s" : ""}
          {etat.premiere && etat.derniere
            ? ` entre ${jourEnLettres(etat.premiere)} et ${jourEnLettres(etat.derniere)}`
            : ""}
          .
        </p>
      ) : null}

      <div
        className={survole ? "depot survole" : "depot"}
        onDragOver={(e) => {
          e.preventDefault();
          setSurvole(true);
        }}
        onDragLeave={() => setSurvole(false)}
        onDrop={(e) => {
          e.preventDefault();
          setSurvole(false);
          deposer(Array.from(e.dataTransfer.files));
        }}
      >
        <div className="grosse">Déposez votre archive ou vos fichiers</div>
        <p className="mention">un export Strava/Garmin, ou des .fit/.gpx/.tcx isolés</p>
        <input
          ref={champ}
          type="file"
          multiple
          accept=".fit,.gpx,.tcx,.gz,.zip,.FIT,.GPX,.TCX,.GZ,.ZIP"
          aria-label="Historique de sorties"
          style={{ display: "none" }}
          onChange={(e) => {
            deposer(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="bouton second mt-depot"
          onClick={() => champ.current?.click()}
          disabled={enCours}
        >
          {enCours ? "Import…" : "Choisir un fichier ou une archive"}
        </button>
        <div className="fmt">.FIT · .GPX · .TCX · .ZIP (Strava/Garmin)</div>
      </div>

      {erreur ? <Echec erreur={erreur} contexte="Import de l'historique" /> : null}

      {job?.statut === "en_cours" ? <BarreAvancement job={job} /> : null}

      {job?.statut === "echoue" ? (
        <div className="encart alerte">
          L'import n'a pas pu aller au bout : {job.erreur ?? "erreur inconnue"}.
        </div>
      ) : null}

      {job?.statut === "fini" && job.rapport ? (
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>
              {job.rapport.importees} sortie{job.rapport.importees > 1 ? "s" : ""} importée
              {job.rapport.importees > 1 ? "s" : ""}
            </h2>
            <span className="rang">Compris</span>
          </div>
          {job.rapport.doublons ? (
            <p className="mention">
              {nombre(job.rapport.doublons)} déjà connue{job.rapport.doublons > 1 ? "s" : ""}, non
              dupliquée{job.rapport.doublons > 1 ? "s" : ""}.
            </p>
          ) : null}
          {job.rapport.ignorees.map((groupe) => (
            <p className="mention" key={groupe.motif}>
              {nombre(groupe.nombre)} ignoré{groupe.nombre > 1 ? "s" : ""} — {groupe.motif}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

/** La barre d'avancement d'un import en cours — `traites`/`total`. */
function BarreAvancement({ job }: { job: JobImport }) {
  // `total` grandit en cours de route (une archive imbriquée s'ouvre) : il
  // peut donc valoir 0 tout au début, avant la première réponse utile.
  const part = job.total > 0 ? Math.min(1, job.traites / job.total) : 0;
  return (
    <div className="bloc doux" role="status">
      <p className="mention">
        Import en cours — {nombre(job.traites)}
        {job.total > 0 ? ` sur ${nombre(job.total)}` : ""} fichier{job.traites > 1 ? "s" : ""}.
      </p>
      <div
        role="progressbar"
        aria-valuenow={Math.round(part * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        style={{
          height: "8px",
          borderRadius: "4px",
          background: "var(--gris-clair, #e5e5e5)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${Math.round(part * 100)}%`,
            background: "var(--accent, #2a6df4)",
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}

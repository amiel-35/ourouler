/** E17 — déposer une séance.
 *
 * L'écran ne se contente pas d'accepter le fichier : **il montre ce qu'il a
 * compris dedans**, dans le même vocabulaire que partout ailleurs. C'est le
 * seul moyen de voir qu'un fichier a été mal lu avant de partir rouler avec.
 *
 * Et il dit la conversion : un `.ZWO` ne porte que des pourcentages, les
 * watts affichés dépendent de la FTP. Quelqu'un qui voit 220 W là où il
 * attendait 250 vient d'apprendre que sa FTP est mal renseignée.
 *
 * Le `.FIT` n'est pas lu en V1, et **son absence se dit ici** plutôt que de
 * se découvrir au moment du dépôt (décision 5).
 */

import { useEffect, useRef, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { EtatImport, JobImport, Seance } from "../api/types";
import { duree, jourEnLettres, nombre } from "../api/formats";
import {
  importEnCoursRetenu,
  oublierImportEnCours,
  retenirImportEnCours,
} from "../etat/memoire";
import { Etapes } from "../composants/Etapes";
import { Echec } from "../composants/Echec";
import { RetourEnTete } from "../composants/Retour";

interface Props {
  jour: string;
  surSeanceLue: (seance: Seance, identifiant: string) => void;
  surChercher: () => void;
  /** D'où l'écran a été ouvert (Aujourd'hui, Ma semaine…) — jamais « Retour » seul. */
  vers: string;
  surRetour: () => void;
}

export function Importer({ jour, surSeanceLue, surChercher, vers, surRetour }: Props) {
  const [seance, setSeance] = useState<Seance | null>(null);
  const [erreur, setErreur] = useState<ErreurApi | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [survole, setSurvole] = useState(false);
  const champ = useRef<HTMLInputElement | null>(null);

  async function deposer(fichier: File) {
    setEnCours(true);
    setErreur(null);
    try {
      const reponse = await api.deposerSeance(fichier, jour);
      setSeance(reponse.donnees);
      surSeanceLue(reponse.donnees, reponse.fichier.id);
    } catch (cause) {
      setSeance(null);
      setErreur(
        cause instanceof ErreurApi
          ? cause
          : new ErreurApi(
              { code: "erreur_interne", message: String(cause), service: null, details: {} },
              0,
            ),
      );
    } finally {
      setEnCours(false);
    }
  }

  return (
    <section>
      {/* Cet écran n'avait aucun moyen d'en sortir (constat du 19/09/2026) :
          arrivé ici, le retour arrière du navigateur restait la seule
          issue. Même geste que `Proposition` : le composant existant, en
          tête, nommé. */}
      <RetourEnTete vers={vers} surRetour={surRetour} />
      <div className="app-tete">
        <div>
          {/* **Pour quel jour** — le dépôt en prend un, et le placement ne
              vaudra que pour lui : autant que l'écran le dise avant. */}
          <span className="quand">Sans Intervals · {jourEnLettres(jour)}</span>
          <h1>Déposer une séance</h1>
        </div>
      </div>

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
          const fichier = e.dataTransfer.files[0];
          if (fichier) deposer(fichier);
        }}
      >
        <div className="grosse">Déposez votre fichier</div>
        <p className="mention">ou choisissez-le sur votre téléphone</p>
        <input
          ref={champ}
          type="file"
          accept=".zwo,.mrc,.ZWO,.MRC"
          aria-label="Fichier de séance"
          style={{ display: "none" }}
          onChange={(e) => {
            const fichier = e.target.files?.[0];
            if (fichier) deposer(fichier);
          }}
        />
        <button
          type="button"
          className="bouton second mt-depot"
          onClick={() => champ.current?.click()}
          disabled={enCours}
        >
          {enCours ? "Lecture…" : "Choisir un fichier"}
        </button>
        <div className="fmt">.ZWO · .MRC</div>
        <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
          Le <b>.FIT</b> viendra plus tard — c'est le seul des trois qui soit un format
          binaire.
        </p>
      </div>

      {erreur ? <Echec erreur={erreur} contexte="Dépôt de séance" /> : null}

      {seance ? (
        <>
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>{seance.nom}</h2>
              <span className="rang">Compris</span>
            </div>
            <Etapes etapes={seance.etapes} />
            <p className="mention">
              {duree(seance.duree_s)} au total, {nombre(seance.n_blocs)} bloc
              {seance.n_blocs > 1 ? "s" : ""}. Les pourcentages sont convertis avec votre FTP
              de {nombre(seance.meta.ftp_w)} W.
            </p>
          </div>
          {seance.avertissements.map((phrase) => (
            <div className="encart attention" key={phrase}>
              {phrase}
            </div>
          ))}
          <button type="button" className="bouton" onClick={surChercher}>
            Chercher un parcours
          </button>
        </>
      ) : null}

      <MesSortiesPassees />
    </section>
  );
}

/** Combien de temps entre deux interrogations de `GET /activites/import/{id}`. */
const DELAI_INTERROGATION_MS = 1_500;

/** E17 bis — L9.2 : déposer son historique, sans passer par Intervals.icu.
 *
 * Distinct du dépôt de séance ci-dessus : celui-là place *une* sortie pour
 * *aujourd'hui*, celui-ci indexe *tout un historique* pour que les parcours
 * proposés reconnaissent les routes déjà connues — utile même sans capteur
 * de puissance ([[Q48]] : « l'import permet de comprendre les routes, la
 * puissance permet de comprendre le niveau — c'est 2 choses »).
 *
 * **L'import tourne en tâche de fond côté serveur** (relecture du
 * 25/09/2026, suite) : le dépôt rend un identifiant tout de suite, cet écran
 * l'interroge périodiquement et affiche une barre d'avancement plutôt que de
 * bloquer sur un appel qui peut durer un quart d'heure. L'identifiant
 * survit à un rechargement de page (`localStorage`, `etat/memoire.ts`) :
 * revenir sur l'écran reprend le suivi là où il en était.
 */
function MesSortiesPassees() {
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
      <div className="app-tete">
        <h2>Mes sorties passées</h2>
      </div>
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

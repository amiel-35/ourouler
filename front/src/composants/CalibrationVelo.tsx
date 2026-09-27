/** La calibration d'un vélo, sur la fiche vélo des Réglages.
 *
 * Un cycliste avec capteur de puissance lance le calcul lui-même : « Calibrer
 * sur mes sorties ». Le serveur relit ses sorties, va chercher le vent de
 * chaque jour, et cherche ce qui explique le mieux ses temps — en tâche de
 * fond, parce que ça dure (`POST /calibrations`, puis `GET /calibrations/{id}`).
 *
 * **Ce qui se dit d'abord, en mots simples** : la puissance qu'il faut à
 * 30 km/h sur le plat sans vent, l'écart mesuré sur des sorties que le calcul
 * n'avait pas vues, la fourchette du porte à porte, le nombre de sorties. Le
 * CdA et le Crr ne sortent que dans un détail replié, et présentés pour ce
 * qu'ils sont : des paramètres de compensation (ils absorbent aussi
 * l'étalonnage du capteur), pas des mesures du vélo à comparer à un catalogue.
 *
 * **Ce qui empêcherait de calibrer se dit avant le clic** — pas de FTP, pas
 * assez de sorties (combien il en faut, combien il y en a), pas de pneu (le
 * choisir, ou calibrer quand même avec la valeur de l'usage, et le résultat
 * le dit). Le serveur refuse de toute façon avec le même code ; l'écran ne
 * fait qu'éviter un clic pour rien.
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { EtatCalibrationVelo, JobCalibration, ResumeCalibration } from "../api/types";
import { enPlus, jourEnLettres, nombre } from "../api/formats";

/** Tous les combien on redemande où en est le calcul. */
const INTERVALLE_SUIVI_MS = 1500;

/**
 * Sous ce nombre de sorties de validation, l'erreur affichée se dit
 * « provisoire » (fiche du 26/09/2026, QP7). Le double du minimum de 10
 * sorties exploitables déjà exigé pour calibrer (L9.4) : au sprint 9,
 * l'écart mesuré est passé de 5,6 % à 10 sorties de validation à 3,6 % à 25,
 * donc l'instabilité se réduit nettement avant ce palier. Ne change rien au
 * calcul ni au minimum pour calibrer — seulement l'affichage d'un résultat
 * déjà mesuré.
 */
const N_VALIDATION_PROVISOIRE = 20;

const ETAPES: Record<string, string> = {
  lecture: "Lecture de vos sorties",
  meteo: "Vent de chaque jour de sortie",
  ajustement: "Calcul",
};

interface Props {
  etat: EtatCalibrationVelo;
  sortiesNecessaires: number;
  ftpRenseignee: boolean;
  /** Calibrations restantes aujourd'hui ; absent en mode personnel (pas de quota). */
  quotaRestant?: number;
  /** Ouvre la liste des vélos, pour choisir les pneus. */
  surChoisirPneus: () => void;
  /** Appelée quand une calibration vient de finir : l'écran relit ce qui en dépend. */
  surCalibree: () => void;
}

export function CalibrationVelo({
  etat,
  sortiesNecessaires,
  ftpRenseignee,
  quotaRestant,
  surChoisirPneus,
  surCalibree,
}: Props) {
  const [job, setJob] = useState<JobCalibration | null>(etat.tache);
  const [panne, setPanne] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);

  // La tâche la plus récente vient du serveur (`GET /calibrations`) : c'est
  // ce qui fait reprendre l'avancement après un rechargement de page, sans
  // rien retenir dans le navigateur.
  useEffect(() => setJob(etat.tache), [etat.tache]);

  useEffect(() => {
    if (!job || job.statut !== "en_cours") return;
    const jeton = setInterval(() => {
      api
        .suivreCalibration(job.id)
        .then((reponse) => {
          setJob(reponse.donnees);
          if (reponse.donnees.statut === "fini") surCalibree();
        })
        .catch(() => undefined); // un raté de suivi n'arrête pas le calcul : on réessaie
    }, INTERVALLE_SUIVI_MS);
    return () => clearInterval(jeton);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.statut]);

  async function lancer(sansPneu: boolean) {
    setPanne(null);
    setEnvoi(true);
    try {
      const reponse = await api.calibrer(etat.velo, sansPneu);
      setJob(reponse.donnees);
    } catch (cause) {
      setPanne(cause instanceof ErreurApi ? cause.message : String(cause));
    } finally {
      setEnvoi(false);
    }
  }

  const enCours = job?.statut === "en_cours";
  const calibration = etat.calibration;
  const assez = etat.sorties_disponibles >= sortiesNecessaires;
  const quotaEpuise = quotaRestant !== undefined && quotaRestant <= 0;
  const empechement = !ftpRenseignee
    ? "Renseignez d'abord votre FTP : elle sert à écarter les efforts qui ne disent rien du vélo (sprints, relances)."
    : !assez
      ? `${etat.sorties_disponibles} sortie${etat.sorties_disponibles > 1 ? "s" : ""} exploitable${etat.sorties_disponibles > 1 ? "s" : ""} sur ce vélo, il en faut au moins ${sortiesNecessaires} : en extérieur, 20 km et plus, avec un capteur de puissance.${nonIdentifiees(etat)}`
      : quotaEpuise
        ? "Une calibration par jour : la prochaine sera possible demain."
        : null;

  return (
    <div className="bloc" aria-label={`Calibration de ${etat.velo}`}>
      <div className="rangee">
        <span className="cle">{etat.velo}</span>
        <span className="val texte">
          {calibration ? "mesuré sur vos sorties" : "pas encore mesuré sur vos sorties"}
        </span>
      </div>

      {calibration ? <Resultat calibration={calibration} /> : null}

      {enCours && job ? <Avancement job={job} /> : null}
      {job?.statut === "echoue" ? (
        <div className="encart alerte">La calibration n'a pas abouti : {job.erreur}</div>
      ) : null}
      {job?.statut === "fini" && job.rapport?.repli ? (
        <p className="mention">{job.rapport.repli}</p>
      ) : null}
      {panne ? <div className="encart alerte">{panne}</div> : null}

      {!enCours && empechement ? <p className="aide">{empechement}</p> : null}

      {!enCours && !empechement && !etat.crr_connu ? (
        <div className="encart">
          <p>
            Aucun pneu déclaré sur ce vélo. Le choisir rend le résultat plus sûr ; sinon, la
            résistance au roulement typique de l'usage ({nombre(etat.crr_usage, 4)}) sera gardée
            telle quelle, et le résultat le dira.
          </p>
          <button type="button" className="bouton second" onClick={surChoisirPneus}>
            Choisir mes pneus
          </button>
          <button
            type="button"
            className="bouton fantome"
            disabled={envoi}
            onClick={() => lancer(true)}
          >
            Calibrer quand même
          </button>
        </div>
      ) : null}

      {!enCours && !empechement && etat.crr_connu ? (
        <button type="button" className="bouton" disabled={envoi} onClick={() => lancer(false)}>
          {calibration ? "Recalibrer sur mes sorties" : "Calibrer sur mes sorties"}
        </button>
      ) : null}
    </div>
  );
}

function nonIdentifiees(etat: EtatCalibrationVelo): string {
  const n = etat.sorties_ecartees["vélo non identifié"] ?? 0;
  if (!n) return "";
  return ` ${n} sortie${n > 1 ? "s" : ""} ne ${n > 1 ? "disent" : "dit"} pas sur quel vélo elle${n > 1 ? "s ont" : " a"} été faite${n > 1 ? "s" : ""} : avec plusieurs vélos, seules comptent celles que rattachent un capteur, un équipement intervals.icu ou une période.`;
}

function Avancement({ job }: { job: JobCalibration }) {
  const libelle = ETAPES[job.etape] ?? "Préparation";
  const compte = job.total > 0 && job.etape !== "ajustement" ? ` — ${job.traites} / ${job.total}` : "";
  return (
    <div className="encart" role="status">
      Calibration en cours · {libelle}
      {compte}. Ça peut prendre quelques minutes ; vous pouvez quitter cet écran.
    </div>
  );
}

function Resultat({ calibration }: { calibration: ResumeCalibration }) {
  const pp = calibration.porte_a_porte;
  return (
    <>
      <p>
        À {nombre(calibration.vitesse_repere_kmh)} km/h sur le plat, sans vent, il vous faut{" "}
        <b>{nombre(calibration.puissance_repere_w)} W</b> sur ce vélo.
      </p>
      {calibration.erreur_validation !== null && calibration.n_validation > 0 ? (
        <>
          <p>
            Sur {calibration.n_validation} sortie{calibration.n_validation > 1 ? "s" : ""} que le
            calcul n'avait pas vue{calibration.n_validation > 1 ? "s" : ""}, le temps prévu
            s'écarte en moyenne de <b>{nombre(calibration.erreur_validation * 100, 1)} %</b> du
            temps réel.
            {calibration.n_validation < N_VALIDATION_PROVISOIRE ? (
              <>
                {" "}
                <b>Provisoire.</b>
              </>
            ) : null}
          </p>
          {calibration.n_validation < N_VALIDATION_PROVISOIRE ? (
            <p className="mention">
              Peu de sorties ont servi à vérifier ce chiffre : il peut encore bouger en important
              plus d'historique.
            </p>
          ) : null}
        </>
      ) : null}
      <p>
        Porte à porte, arrêts compris : {enPlus(pp.bas)} à {enPlus(pp.haut)} sur le temps de
        roulage calculé
        {pp.provenance === "mesure"
          ? ` — mesuré sur ${pp.n} de vos sorties roulées seul.`
          : " — valeur par défaut : pas encore assez de sorties roulées seul pour mesurer la vôtre."}
      </p>
      <p className="mention">
        Mesuré sur {calibration.n_sorties} sortie{calibration.n_sorties > 1 ? "s" : ""}
        {calibration.date ? `, le ${jourEnLettres(calibration.date)}` : ""}.
        {calibration.crr_source === "usage"
          ? " Aucun pneu n'était déclaré : la résistance au roulement typique de l'usage a été gardée."
          : ""}
      </p>
      {calibration.alerte ? <div className="encart alerte">{calibration.alerte}</div> : null}
      <details>
        <summary>Détail du calcul</summary>
        <p className="mention">
          Ces deux nombres sont des paramètres de compensation : ils absorbent tout ce que le
          modèle ne sait pas, l'étalonnage de votre capteur compris. Ils ne se comparent ni à un
          catalogue ni d'un vélo à l'autre.
        </p>
        <ul className="mention">
          <li>Surface frontale × traînée (CdA) : {nombre(calibration.detail.cda_m2, 3)} m²</li>
          <li>
            Résistance au roulement (Crr) : {nombre(calibration.detail.crr, 4)}
            {calibration.crr_source === "pneu" ? " (fixée par vos pneus)" : ""}
            {calibration.crr_source === "usage" ? " (fixée par l'usage du vélo)" : ""}
          </li>
          <li>Masse, vous et le vélo : {nombre(calibration.detail.masse_totale_kg, 1)} kg</li>
          {calibration.biais_validation !== null ? (
            <li>
              Biais sur les sorties de contrôle : {calibration.biais_validation >= 0 ? "+" : "−"}
              {nombre(Math.abs(calibration.biais_validation) * 100, 1)} %
            </li>
          ) : null}
        </ul>
      </details>
    </>
  );
}

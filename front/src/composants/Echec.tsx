/** Les états d'échec — des **écrans**, pas des alertes.
 *
 * « Un écran vide se lit "rien de prévu", et l'utilisateur ne va pas rouler »
 * (`docs/ux/maquettes_v1.html`, section « Quand ça casse »). Chaque échec dit
 * donc trois choses : ce qui s'est passé, ce qui marche encore, et le geste
 * suivant — jamais un simple « réessayez ».
 *
 * Le choix de l'écran se fait sur le **code** de la panne, jamais sur son
 * message : le message vient du cœur et peut être reformulé, le code est une
 * valeur du contrat (`docs/ux/api_contrat.md`).
 */

import type { ReactNode } from "react";
import { ErreurApi, reessayable } from "../api/client";

export interface Repli {
  titre: string;
  detail?: string;
  action: () => void;
}

interface Props {
  erreur: ErreurApi;
  /** Les leviers qui marchent vraiment, avec leurs valeurs. */
  replis?: Repli[];
  /** Ce qui reste possible pendant la panne. */
  secours?: ReactNode;
  reessayer?: () => void;
  /** Ce que l'utilisateur demandait, en une ligne — il l'a peut-être oublié. */
  contexte?: string;
  /** Dernier jour où les séances ont réellement été lues, si on le sait. */
  dernierSucces?: string | null;
}

function Cadre({
  contexte,
  titre,
  children,
}: {
  contexte?: string;
  titre: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="app-tete">
        <div>
          {contexte ? <span className="quand">{contexte}</span> : null}
          <h1>{titre}</h1>
        </div>
      </div>
      {children}
    </section>
  );
}

function ListeReplis({ replis }: { replis: Repli[] }) {
  if (replis.length === 0) return null;
  return (
    <div className="bloc doux">
      <div className="bloc-tete">
        <h2>Ce qui peut aider</h2>
      </div>
      <div className="etapes">
        {replis.map((repli) => (
          <div className="etape" key={repli.titre}>
            <span className="km">→</span>
            <span className="nom">
              <b>{repli.titre}</b>
              {repli.detail ? <small>{repli.detail}</small> : null}
            </span>
            <button type="button" className="lien" onClick={repli.action}>
              Essayer
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Echec({
  erreur,
  replis = [],
  secours,
  reessayer,
  contexte,
  dernierSucces,
}: Props) {
  // --- E18 · échec : aucune boucle dans la tolérance de distance.
  if (erreur.code === "aucune_boucle") {
    return (
      <Cadre contexte={contexte} titre="Aucune boucle">
        <div className="encart alerte">
          <b>On n'a rien trouvé qui tienne.</b> {erreur.message}
        </div>
        <ListeReplis replis={replis} />
        <p className="mention">
          Rien n'a été décompté de votre côté : un essai qui ne rend rien ne coûte rien.
        </p>
      </Cadre>
    );
  }

  // --- E15 · échec : la clé marchait, et elle a cessé.
  if (erreur.code === "intervals_refuse") {
    return (
      <Cadre contexte={contexte} titre="Cette semaine">
        <div className="encart alerte">
          <b>intervals.icu ne nous répond plus.</b> Votre clé a sans doute été changée ou
          retirée.
          {dernierSucces ? ` Vos séances ne sont plus lues depuis le ${dernierSucces}.` : ""}
        </div>
        {secours}
      </Cadre>
    );
  }

  // --- E14 · dégradé porté à l'extrême : la météo n'a rien rendu du tout.
  if (erreur.code === "meteo_indisponible" || erreur.code === "meteo_hors_domaine") {
    return (
      <Cadre contexte={contexte} titre="Pas de météo">
        <div className="encart attention">
          <b>La météo n'a rien rendu.</b> {erreur.message}
        </div>
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>La tenue</h2>
          </div>
          <p className="mention">
            Sans température, on ne conseille rien plutôt que de conseiller au hasard.
          </p>
        </div>
        {secours}
        {reessayer ? (
          <button type="button" className="bouton second" onClick={reessayer}>
            Réessayer la météo
          </button>
        ) : null}
      </Cadre>
    );
  }

  // --- tout le reste : une panne qu'on nomme, et ce qui marche encore.
  const titres: Record<string, string> = {
    brouter_indisponible: "Le traceur ne répond pas",
    calcul_en_cours: "Un calcul occupe déjà le serveur",
    fichier_illisible: "Ce fichier n'a pas été compris",
    format_non_lu: "Ce format n'est pas encore lu",
    fichier_trop_gros: "Ce fichier est trop gros",
    geocodage_indisponible: "L'annuaire d'adresses ne répond pas",
    intervals_indisponible: "intervals.icu est en panne",
    profil_invalide: "Ce réglage ne tient pas",
    serveur_injoignable: "Le serveur ne répond pas",
  };
  return (
    <Cadre contexte={contexte} titre={titres[erreur.code] ?? "Ça n'a pas marché"}>
      <div className="encart alerte">{erreur.message}</div>
      <ListeReplis replis={replis} />
      {secours}
      {reessayer && reessayable(erreur) ? (
        <button type="button" className="bouton second" onClick={reessayer}>
          Réessayer
        </button>
      ) : null}
      <p className="mention" style={{ marginTop: 10 }}>
        Code de la panne : {erreur.code}
      </p>
    </Cadre>
  );
}

/**
 * E14 · dégradé : le parcours est servi, la météo non.
 *
 * Le cœur prévient sur sa sortie d'erreur, l'API capture dans
 * `avertissements`. On ne retire alors que les affirmations qu'on ne peut
 * plus soutenir — la pluie, le vent, la tenue —, jamais le parcours.
 */
export function meteoManquante(avertissements: string[]): string | null {
  const trouve = avertissements.find((phrase) => /m[ée]t[ée]o/i.test(phrase));
  return trouve ?? null;
}

export function BandeauMeteoAbsente({ phrase }: { phrase: string }) {
  return (
    <div className="encart attention">
      <b>Pas de météo.</b> Le parcours est calculé sans la pluie ni le vent — on ne vous dira
      pas où il fait sec. <span className="mention">{phrase}</span>
    </div>
  );
}

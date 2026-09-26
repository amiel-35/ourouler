/** Les états d'échec — des **écrans**, pas des alertes.
 *
 * « Un écran vide se lit "rien de prévu", et l'utilisateur ne va pas rouler »
 * (`docs/journal/ux/maquettes_v1.html`, section « Quand ça casse »). Chaque échec dit
 * donc trois choses : ce qui s'est passé, ce qui marche encore, et le geste
 * suivant — jamais un simple « réessayez ».
 *
 * Le choix de l'écran se fait sur le **code** de la panne, jamais sur son
 * message : le message vient du cœur et peut être reformulé, le code est une
 * valeur du contrat (`docs/journal/ux/api_contrat.md`).
 *
 * Le cadre et les replis sont dans `echec/Cadre.tsx`, les titres du
 * générique dans `echec/titres.ts`, le bandeau « pas de météo » dans
 * `echec/MeteoAbsente.tsx`.
 */

import type { ReactNode } from "react";
import { CODE_DELAI, CODE_ILLISIBLE, ErreurApi, reessayable, serveurMuet } from "../api/client";
import { jourEnLettres, pourcentage } from "../api/formats";
import { signe } from "./Elargissement";
import { Cadre, ListeReplis } from "./echec/Cadre";
import type { Repli } from "./echec/Cadre";
import { TITRES_PANNE } from "./echec/titres";

export type { Repli } from "./echec/Cadre";
export { BandeauMeteoAbsente, meteoManquante } from "./echec/MeteoAbsente";

/** Les mesures du refus sur la distance, quand l'API les a jointes.
 *
 * `details` est un `Record<string, unknown>` : il faut donc vérifier, pas
 * supposer. Une version de l'API qui ne les envoie pas doit laisser l'écran
 * correct — d'où le `null` plutôt qu'un affichage à trous.
 */
export function mesuresDistance(erreur: ErreurApi): {
  cible: number;
  obtenue: number;
  ecart: number;
  requis: number;
  plafond: number;
} | null {
  const details = erreur.details as Record<string, unknown> | undefined;
  if (!details || details.motif !== "distance_inatteignable") return null;
  const nombres = [
    details.distance_cible_km,
    details.distance_obtenue_km,
    details.ecart_relatif,
    details.elargissement_requis,
    details.elargissement_max,
  ];
  if (!nombres.every((v) => typeof v === "number" && Number.isFinite(v))) return null;
  const [cible, obtenue, ecart, requis, plafond] = nombres as number[];
  return { cible, obtenue, ecart, requis, plafond };
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

export function Echec({
  erreur,
  replis = [],
  secours,
  reessayer,
  contexte,
  dernierSucces,
}: Props) {
  // --- le serveur n'a rien dit : ce n'est pas une panne de l'API, c'est son
  // absence. Cet écran n'existait pas, et le cas le plus courant tombait dans
  // le fourre-tout du bas avec « le serveur a répondu 500 sans rien
  // expliquer » : ni cause, ni geste, ni bouton — parce qu'`erreur_interne`
  // n'est pas réessayable. Or il n'y a **rien** à réparer côté demande, et
  // réessayer est précisément le seul geste qui vaille.
  if (serveurMuet(erreur)) {
    const titre =
      erreur.code === CODE_DELAI
        ? "Le serveur ne rend pas la main"
        : erreur.code === CODE_ILLISIBLE
          ? "Ce n'est pas d'où rouler qui a répondu"
          : "Le serveur ne répond pas";
    return (
      <Cadre contexte={contexte} titre={titre}>
        <div className="encart alerte">
          <b>Aucune réponse d'où rouler.</b> {erreur.message}
        </div>
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>Ce qui est sûr</h2>
          </div>
          <p className="mention">
            Rien n'est perdu : votre profil, vos réglages et vos parcours sont sur le serveur,
            pas dans cette page. Ce n'est pas non plus votre demande qui est en cause — elle
            n'est jamais arrivée.
          </p>
        </div>
        <ListeReplis replis={replis} />
        {secours}
        {reessayer ? (
          <button type="button" className="bouton" onClick={reessayer}>
            Réessayer
          </button>
        ) : null}
        <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
          Si vous faites tourner où rouler vous-même : l'interface appelle l'API sur la même
          adresse qu'elle, et le serveur de développement la cherche sur le port 8000
          (<code>uv run ourouler api --port 8000</code>, ou <code>OUROULER_API</code> pour la
          chercher ailleurs). Code de la panne : {erreur.code}.
        </p>
      </Cadre>
    );
  }

  // --- Le serveur a répondu, et il refuse : il ne sait pas qui parle.
  //
  // Trouvé le 18/09/2026 (lot L7.A) : un service exposé répond 401
  // `session_absente` à **toute** route de données, y compris `/systeme` —
  // le tout premier appel de l'application. `session_absente` n'a plus
  // d'écran dédié ici depuis le lot L7.2-D (19/09/2026) : `App.tsx`
  // intercepte ce code **avant** qu'`Echec` ne soit atteint, et affiche
  // l'écran de connexion à la place (`écrans/Connexion.tsx`) — se
  // reconnecter est redevenu un geste qui aboutit, maintenant qu'il existe
  // un compte et un mot de passe. Le code garde tout de même son entrée
  // dans le tableau générique ci-dessous, en filet : si un appel échappait
  // un jour à cette interception, mieux vaut un titre nommé que le
  // générique.

  // --- E18 · échec : aucune boucle dans la tolérance de distance.
  if (erreur.code === "aucune_boucle") {
    const mesures = mesuresDistance(erreur);
    return (
      <Cadre contexte={contexte} titre="Aucune boucle">
        <div className="encart alerte">
          <b>On n'a rien trouvé qui tienne.</b> {erreur.message}
        </div>
        {/* Les leviers de repli étaient dessinés avec des valeurs que rien ne
            soutenait. Ils ont maintenant leur chiffre : celui de
            l'élargissement qu'il aurait fallu, mesuré, pas supposé (Q41 d). */}
        {mesures ? (
          <div className="bloc doux">
            <div className="bloc-tete">
              <h5>Ce qu'on a trouvé de plus proche</h5>
            </div>
            <p className="mention">
              {mesures.obtenue.toFixed(1)} km pour {Math.round(mesures.cible)} km demandés
              ({signe(mesures.ecart)}). Il aurait fallu élargir de{" "}
              {pourcentage(mesures.requis)} ; on s'arrête à {pourcentage(mesures.plafond)},
              au-delà on ne desserre plus votre contrainte, on en sert une autre.
            </p>
          </div>
        ) : null}
        <ListeReplis replis={replis} />
        <p className="mention">
          Rien n'a été décompté de votre côté : un essai qui ne rend rien ne coûte rien.
        </p>
      </Cadre>
    );
  }

  // --- Intervals jamais relié : ni une panne, ni une faute.
  //
  // À distinguer de `intervals_refuse` juste en dessous, qui dit « votre clé
  // a cessé de marcher » : celui-ci s'adresse à quelqu'un qui n'en a jamais
  // eu. L'API rendait `requete_invalide` pour les deux, donc le premier
  // compte invité lisait « Cette demande n'est pas valide » et se voyait
  // renvoyé vers une section `[intervals]` d'un fichier TOML qu'il ne verra
  // jamais (constaté le 19/09/2026, sur le premier parcours complet).
  if (erreur.code === "intervals_absent") {
    return (
      <Cadre titre={contexte ?? "Vos séances"}>
        <div className="encart">
          <b>Votre compte intervals.icu n'est pas encore relié.</b> C'est lui qui donne la
          séance du jour et l'historique dont le modèle apprend.
        </div>
        <p>
          <a className="bouton" href="/?onglet=reglages">
            Le relier dans les réglages
          </a>
        </p>
        {secours}
      </Cadre>
    );
  }

  // --- E15 · échec : la clé marchait, et elle a cessé.
  if (erreur.code === "intervals_refuse") {
    // C11 : le titre annonçait « Cette semaine » même quand la panne venait
    // de l'onglet « Aujourd'hui ». L'écran se nomme donc d'après l'endroit
    // où le cycliste se trouve — et le contexte ne se répète pas au-dessus.
    return (
      <Cadre titre={contexte ?? "Vos séances"}>
        <div className="encart alerte">
          <b>intervals.icu ne nous répond plus.</b> Votre clé a sans doute été changée ou
          retirée.
          {/* C2 : « depuis le 2026-09-12 » est une date de machine. E15 fait
              de cette phrase le point de l'écran — « plus lues depuis le
              12 septembre » dit à quelqu'un ce qu'il a manqué. */}
          {dernierSucces
            ? ` Vos séances ne sont plus lues depuis le ${jourEnLettres(dernierSucces)}.`
            : ""}
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

  // --- tout le reste : une panne qu'on nomme (`TITRES_PANNE`), et ce qui
  // marche encore.
  return (
    <Cadre contexte={contexte} titre={TITRES_PANNE[erreur.code] ?? "Ça n'a pas marché"}>
      <div className="encart alerte">{erreur.message}</div>
      <ListeReplis replis={replis} />
      {secours}
      {reessayer && reessayable(erreur) ? (
        <button type="button" className="bouton second" onClick={reessayer}>
          Réessayer
        </button>
      ) : null}
      <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
        Code de la panne : {erreur.code}
      </p>
    </Cadre>
  );
}

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
import { CODE_DELAI, CODE_ILLISIBLE, ErreurApi, reessayable, serveurMuet } from "../api/client";
import type { Avertissement } from "../api/types";
import { jourEnLettres, pourcentage } from "../api/formats";
import { signe } from "./Elargissement";

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
        <p className="mention" style={{ marginTop: 10 }}>
          Si vous faites tourner où rouler vous-même : l'interface appelle l'API sur la même
          adresse qu'elle, et le serveur de développement la cherche sur le port 8000
          (<code>uv run ourouler api --port 8000</code>, ou <code>OUROULER_API</code> pour la
          chercher ailleurs). Code de la panne : {erreur.code}.
        </p>
      </Cadre>
    );
  }

  // --- Le serveur a répondu, et il refuse : il ne sait pas encore qui parle.
  //
  // Trouvé le 18/09/2026 (lot L7.A, mergé pendant ce lot-ci) : un service
  // exposé (`OUROULER_MODE=heberge`, ou l'absence de la variable) répond
  // 401 `session_absente` à **toute** route de données, y compris `/systeme`
  // — le tout premier appel de l'application, avant même l'écran vide de
  // démarrage. Sans ce cas, l'écran serait resté sur « Connexion au
  // serveur… » pour toujours : exactement le défaut muet du 17/09 que ce
  // lot existe pour tuer, et le cas le plus probable en usage réel plutôt
  // qu'un cas rare.
  //
  // **Pas d'écran de connexion.** Aucune méthode d'authentification n'est
  // choisie — c'est hors périmètre du sprint (`docs/sprint7_contrat.md`,
  // « hors périmètre »). Un formulaire ou un bouton « se connecter » qui ne
  // mènerait nulle part serait une fausse promesse ; l'écran se contente de
  // dire ce qui manque, sans `reessayer` — se reconnecter n'a aucune chance
  // d'aboutir tant que rien n'existe pour le faire.
  if (erreur.code === "session_absente") {
    return (
      <Cadre contexte={contexte} titre="Ce serveur ne sait pas encore qui vous êtes">
        <div className="encart alerte">
          <b>Aucune session ouverte.</b> {erreur.message}
        </div>
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>Ce qui manque</h2>
          </div>
          <p className="mention">
            Ce service peut servir plusieurs cyclistes, et aucune méthode de connexion n'est
            encore branchée ici — ni compte, ni lien, ni mot de passe. Ce n'est pas une panne :
            ce serveur ne peut simplement montrer les données de personne tant que ça
            n'existe pas. Il n'y a rien à faire ici pour l'instant.
          </p>
        </div>
        {secours}
      </Cadre>
    );
  }

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

  // --- tout le reste : une panne qu'on nomme, et ce qui marche encore.
  //
  // **Inventaire complet du 18/09/2026** (L7.D). Avant ce lot, 13 des 21
  // codes d'`api/erreurs.CODES_PANNE` avaient un écran — 9 par une entrée de
  // ce tableau, 4 par un écran dédié (`aucune_boucle`, `meteo_indisponible`,
  // `meteo_hors_domaine`, `intervals_refuse`, tous traités plus haut). Les 8
  // restants (`requete_invalide`, `fichier_introuvable`,
  // `generation_introuvable`, `route_inconnue`, `methode_refusee`,
  // `service_externe_indisponible`, `configuration_invalide`,
  // `erreur_interne`) tombaient dans « Ça n'a pas marché » — pas un écran
  // muet (le message et le code restaient affichés), mais pas non plus le
  // titre qui dit ce qui s'est passé. `tests/inventaire_erreurs.test.tsx`
  // relit `CODES_PANNE` dans les sources Python pour qu'un code qu'on y
  // ajoute sans le nommer ici casse un test, plutôt que de retomber en
  // silence dans le générique — c'est ainsi que `session_absente` (L7.A,
  // mergé pendant ce lot) a été trouvé, et il a son propre écran plus haut.
  const titres: Record<string, string> = {
    requete_invalide: "Cette demande n'est pas valide",
    profil_invalide: "Ce réglage ne tient pas",
    fichier_illisible: "Ce fichier n'a pas été compris",
    format_non_lu: "Ce format n'est pas encore lu",
    fichier_trop_gros: "Ce fichier est trop gros",
    fichier_introuvable: "Ce fichier n'est plus accessible",
    // Le GPX d'une génération oubliée : l'API le dit dans son message
    // (« relancer la recherche »), mais un titre qui reprend le mot
    // « introuvable » sans le nommer laisserait croire à un bug plutôt qu'à
    // une mémoire qui a fait sa place (`docs/ux/api_contrat.md`).
    generation_introuvable: "Cette recherche n'est plus disponible",
    // Pas « adresse » : ce mot désigne déjà l'adresse postale du départ
    // ailleurs dans l'écran (`FormulaireAdresse`, E16) — l'ambigüité aurait
    // fait croire à une adresse mal saisie plutôt qu'à un chemin d'API
    // inconnu.
    route_inconnue: "Cette route de l'API n'existe pas",
    methode_refusee: "Cette route n'accepte pas cette méthode",
    calcul_en_cours: "Un calcul occupe déjà le serveur",
    brouter_indisponible: "Le traceur ne répond pas",
    intervals_indisponible: "intervals.icu est en panne",
    geocodage_indisponible: "L'annuaire d'adresses ne répond pas",
    service_externe_indisponible: "Un service externe ne répond pas",
    // Le serveur tourne et **refuse** : la distinction avec « ne répond pas »
    // se voit dès le titre, qui dit ce qui manque au serveur et non ce qui
    // manquerait à la demande.
    profil_absent: "Ce serveur n'a pas de profil",
    configuration_invalide: "La configuration du serveur ne tient pas",
    erreur_interne: "Quelque chose a cassé côté serveur",
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
 *
 * **Sur le code, jamais sur la phrase** (corrigé le 17/09/2026). Cette
 * fonction cherchait `/m[ée]t[ée]o/i` dans le message, alors que
 * `docs/ux/api_contrat.md` pose l'inverse en toutes lettres : « le code prime
 * sur le message […] qui peut être reformulé ». Le jour où quelqu'un écrivait
 * « Open-Meteo injoignable », le bandeau disparaissait sans bruit et il
 * restait un parcours servi sans pluie, sans vent, **et sans la phrase qui
 * dit pourquoi** — pire qu'un bloc vide, que E14 interdit déjà.
 *
 * Le front n'avait alors aucun autre levier : `avertissements` ne portait pas
 * de code. C'était un trou du contrat F1, il a été bouché côté API
 * (`api/erreurs.CODES_AVERTISSEMENT`) plutôt que contourné ici.
 */
export function meteoManquante(avertissements: Avertissement[]): string | null {
  const trouve = avertissements.find((a) => a.code === "meteo_indisponible");
  return trouve?.message ?? null;
}

export function BandeauMeteoAbsente({ phrase }: { phrase: string }) {
  return (
    <div className="encart attention">
      <b>Pas de météo.</b> Le parcours est calculé sans la pluie ni le vent — on ne vous dira
      pas où il fait sec. <span className="mention">{phrase}</span>
    </div>
  );
}

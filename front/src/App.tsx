/** L'application : quatre onglets, et ce qui se passe entre eux.
 *
 * Tout ce qui s'affiche vient de l'API. Cette règle n'est pas une intention,
 * c'est la forme du code : aucun écran n'a de valeur par défaut, et un champ
 * que l'API ne rend pas n'existe pas dans les types (`api/types.ts`).
 *
 * Le calcul d'un parcours est **semi-synchrone** : la requête tient, l'écran
 * d'attente anime contre le budget annoncé par `/systeme/budgets`, et la
 * réponse dit ce que ça a réellement pris.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ErreurApi, sessionRouverte, surSessionAbsente } from "./api/client";
import type { Boucle, Budget, Enveloppe, Profil, Seance, Sortie, Zones } from "./api/types";
import { aujourdhui, useRessource } from "./etat/ressource";
import { jourEnLettres } from "./api/formats";
import {
  derniereLectureSeances,
  retenirLectureSeances,
  retenirSortie,
  sortieRetenue,
  type SortieMemorisee,
} from "./etat/memoire";
import { Attente } from "./composants/Attente";
import { Echec, type Repli } from "./composants/Echec";
import { Aujourdhui } from "./ecrans/Aujourdhui";
import { MaSemaine } from "./ecrans/MaSemaine";
import { Demander, demandeInitiale, type Demande } from "./ecrans/Demander";
import { Importer } from "./ecrans/Importer";
import { Propositions } from "./ecrans/Propositions";
import { PropositionDetail } from "./ecrans/Proposition";
import { Boucles } from "./ecrans/Boucles";
import { Reglages } from "./ecrans/Reglages";
import { Assistant } from "./ecrans/Assistant";
import { Connexion } from "./ecrans/Connexion";
import { Entrer } from "./ecrans/Entrer";
import { IconeAujourdhui, IconeSemaine, IconeDemander, IconeReglages } from "./composants/Pictogrammes";

/**
 * Sur quelle page ce chargement de l'application s'est ouvert — lu **une
 * fois**, au démarrage, jamais réévalué (lot L7.2-D).
 *
 * Pas de routeur : le reste de l'application navigue par état React
 * (`Onglet`, `Vue` ci-dessous), comme avant ce lot. Seuls ces deux chemins
 * sont distingués, parce qu'ils doivent fonctionner **avant** qu'aucune
 * session n'existe — l'un des deux, justement, sert à en ouvrir une.
 */
type Pagina =
  | { genre: "application" }
  | { genre: "entrer"; jeton: string }
  | { genre: "reinitialiser"; jeton: string }
  | { genre: "connexion" };

function paginaDepuisUrl(): Pagina {
  const chemin = window.location.pathname;
  if (chemin === "/entrer" || chemin === "/reinitialiser") {
    const jeton = new URLSearchParams(window.location.search).get("jeton") ?? "";
    // Le jeton n'a rien à faire dans l'historique du navigateur ni dans un
    // en-tête `Referer` une fois lu : une ligne, faite ici et nulle part
    // ailleurs, pour que ni le rechargement de l'écran ni un lien partagé
    // depuis cette page ne le fassent fuiter une seconde fois.
    window.history.replaceState(null, "", chemin);
    return chemin === "/entrer" ? { genre: "entrer", jeton } : { genre: "reinitialiser", jeton };
  }
  if (chemin === "/connexion") return { genre: "connexion" };
  return { genre: "application" };
}

type Onglet = "aujourdhui" | "semaine" | "demander" | "reglages";
type Vue =
  | { genre: "onglet" }
  | { genre: "assistant" }
  /**
   * **Le dépôt porte son jour** (trouvé en cliquant, le 17/09/2026).
   *
   * `Importer` recevait `demande.jour`, qui dérive : `chercher` le réécrit à
   * chaque génération. Après avoir généré le parcours de samedi depuis « Ma
   * semaine », « Déposer une séance » depuis l'écran **d'aujourd'hui**
   * déposait le fichier pour samedi. Le rattachement au jour étant devenu la
   * garde de B1, un rattachement au mauvais jour est le même défaut déplacé.
   */
  | { genre: "importer"; jour: string }
  | { genre: "propositions" }
  | { genre: "detail"; numero: number }
  | { genre: "boucles" };

interface Resultat {
  sortie: Enveloppe<Sortie> | null;
  boucle: Enveloppe<Boucle> | null;
  seance: Seance | null;
  jour: string;
}

/**
 * Un fichier de séance déposé — **et le jour pour lequel il l'a été**.
 *
 * Q38 : « le fichier déposé c'est une séance à faire ». C'est une
 * prescription, et une prescription vaut pour un jour. `POST /seances/fichier`
 * prend d'ailleurs ce jour ; le front ne l'honorait pas.
 *
 * Avant le 17/09/2026, seul l'identifiant était retenu, et **rien ne le
 * remettait à `null`** : ni le changement de jour, ni le changement d'onglet,
 * ni une séance Intervals retrouvée, ni la fin de la génération. Un `.ZWO`
 * déposé mardi se replaçait silencieusement sur toutes les recherches
 * suivantes — le cycliste partait faire les blocs de mardi le mercredi, sur
 * des données qu'il ne pourrait pas refaire, et l'interface avait l'air
 * d'accord avec lui (relecture F2 · B1).
 *
 * L'invariant tenu maintenant, et testé : **une séance déposée ne part qu'avec
 * une recherche pour son propre jour**, et elle est visible tant qu'elle est
 * en usage.
 */
export interface SeanceDeposee {
  identifiant: string;
  jour: string;
  nom: string;
}

/**
 * L'identifiant à joindre à une recherche — **ou rien**.
 *
 * La règle de B1, nommée plutôt que laissée en ligne dans l'appel : une
 * prescription déposée pour mardi ne part pas avec la recherche de mercredi.
 * C'est la seule chose qui sépare « le cycliste fait la séance du jour » de
 * « le cycliste part faire les blocs d'hier sans le savoir ».
 */
export function fichierPourLaRecherche(
  deposee: SeanceDeposee | null,
  jourDemande: string,
): string | undefined {
  if (deposee === null) return undefined;
  return deposee.jour === jourDemande ? deposee.identifiant : undefined;
}

const ONGLETS: { cle: Onglet; nom: string }[] = [
  { cle: "aujourdhui", nom: "Aujourd'hui" },
  { cle: "semaine", nom: "Ma semaine" },
  { cle: "demander", nom: "Demander" },
  { cle: "reglages", nom: "Réglages" },
];

/** L'onglet demandé par l'URL (`?onglet=reglages`), lu **une fois**, au
 * démarrage — même patron que `paginaDepuisUrl`. Constaté le 25/09/2026 :
 * le lien « Le relier dans les réglages » posait ce paramètre, mais rien ne
 * le lisait, et une ouverture directe de ce lien retombait sur Aujourd'hui.
 * Une clé absente ou inconnue garde le défaut plutôt que d'échouer. */
function ongletDepuisUrl(): Onglet {
  const valeur = new URLSearchParams(window.location.search).get("onglet");
  const trouve = ONGLETS.find((o) => o.cle === valeur);
  return trouve ? trouve.cle : "aujourdhui";
}

/**
 * Le point d'entrée : décide une fois pour toutes sur quelle page on est
 * (lot L7.2-D), et rend `ApplicationPrincipale` — les quatre onglets
 * d'aujourd'hui, inchangés — pour tout le reste.
 *
 * `Entrer` et `Connexion` naviguent en repartant à la racine
 * (`window.location.assign`) plutôt qu'en gardant un état de page ici : une
 * fois la session ouverte, il n'y a rien à préserver d'un écran qui n'a
 * montré qu'un formulaire, et repartir à zéro relance
 * `ApplicationPrincipale` sur une base propre, cookie posé.
 */
export function App() {
  const [pagina] = useState<Pagina>(() => paginaDepuisUrl());

  if (pagina.genre === "entrer") {
    return <Entrer jeton={pagina.jeton} surEntre={() => window.location.assign("/")} />;
  }
  if (pagina.genre === "reinitialiser") {
    return (
      <Entrer
        jeton={pagina.jeton}
        mode="reinitialiser"
        surEntre={() => window.location.assign("/")}
      />
    );
  }
  if (pagina.genre === "connexion") {
    return <Connexion surConnecte={() => window.location.assign("/")} />;
  }
  return <ApplicationPrincipale />;
}

function ApplicationPrincipale() {
  const jour = aujourdhui();
  const [onglet, setOnglet] = useState<Onglet>(ongletDepuisUrl);
  const [vue, setVue] = useState<Vue>({ genre: "onglet" });
  const [demande, setDemande] = useState<Demande>(demandeInitiale);
  const [resultat, setResultat] = useState<Resultat | null>(null);
  const [enCalcul, setEnCalcul] = useState<Budget | null>(null);
  const [erreurCalcul, setErreurCalcul] = useState<ErreurApi | null>(null);
  const [fichierSeance, setFichierSeance] = useState<SeanceDeposee | null>(null);
  const [memoire, setMemoire] = useState<SortieMemorisee | null>(() => sortieRetenue(jour));
  /**
   * Les jours pour lesquels ce navigateur a déjà un parcours (C10).
   *
   * `etat/memoire` range chaque sortie sous sa propre clé depuis le début ;
   * c'est l'application qui ne retenait que celle du jour. Générer le parcours
   * de demain depuis « Ma semaine » ne laissait donc aucune trace : le bouton
   * restait « Générer le parcours », et le calcul — trois à sept secondes
   * contre BRouter et Open-Meteo — était à refaire.
   */
  const [joursMemorises, setJoursMemorises] = useState<string[]>([]);
  const [profilCourant, setProfilCourant] = useState<Profil | null>(null);
  const [zonesCourantes, setZonesCourantes] = useState<Zones | null>(null);
  /**
   * Vrai dès qu'une route quelconque a répondu 401 `session_absente` (lot
   * L7.2-D) — la session a expiré, ou n'a jamais existé. `api.client`
   * prévient au moment même où **n'importe quel** appel reçoit ce code, pas
   * seulement les trois ressources de démarrage ci-dessous : une séance qui
   * expire pendant que le cycliste choisit une proposition doit amener le
   * même écran de connexion, pas l'erreur technique nue que `session_absente`
   * produisait avant ce lot.
   */
  const [sessionPerdue, setSessionPerdue] = useState(false);

  const systeme = useRessource(() => api.systeme(), []);
  const profil = useRessource(() => api.profil(), []);
  const zones = useRessource(() => api.zones(), []);

  useEffect(() => {
    if (profil.valeur) setProfilCourant(profil.valeur.donnees);
  }, [profil.valeur]);
  useEffect(() => {
    if (zones.valeur) setZonesCourantes(zones.valeur.donnees);
  }, [zones.valeur]);

  /**
   * Un compte neuf atterrit dans l'assistant, pas sur l'écran du jour
   * (défaut constaté en vrai le 19/09/2026 : « Aujourd'hui » réclame
   * Intervals et échoue). Ne force qu'**une seule fois** — dès que la
   * personne a fini l'assistant ou l'a quitté volontairement, plus rien ne
   * doit l'y ramener, y compris quand `profil.valeur` se recharge ensuite
   * (reconnexion, `recharger()`).
   */
  const assistantDejaImpose = useRef(false);
  useEffect(() => {
    if (!profil.valeur || assistantDejaImpose.current) return;
    assistantDejaImpose.current = true;
    if (profil.valeur.donnees.assistant_recommande) {
      setVue({ genre: "assistant" });
    }
  }, [profil.valeur]);

  const budgetDe = useCallback(
    (operation: string): Budget | null =>
      systeme.valeur?.budgets.find((b) => b.operation === operation) ?? null,
    [systeme.valeur],
  );

  // --- les ressources des onglets ---------------------------------------

  const seanceDuJour = useRessource(() => api.seance(jour), [jour]);
  const semaine = useRessource(() => api.semaine(), []);

  useEffect(() => {
    if (semaine.valeur) retenirLectureSeances(jour);
  }, [semaine.valeur, jour]);

  // Au retour sur l'application, les parcours déjà calculés de la semaine
  // sont dans le stockage : on les y relit plutôt que de les oublier (C10).
  useEffect(() => {
    const jours = semaine.valeur?.donnees.jours ?? [];
    setJoursMemorises(jours.map((j) => j.jour).filter((j) => sortieRetenue(j) !== null));
  }, [semaine.valeur]);

  const seanceDemandee = useMemo(() => {
    if (demande.jour === jour) return seanceDuJour.valeur?.donnees ?? null;
    const trouve = semaine.valeur?.donnees.jours.find((j) => j.jour === demande.jour);
    return trouve?.seance ?? null;
  }, [demande.jour, jour, seanceDuJour.valeur, semaine.valeur]);

  useEffect(() => {
    surSessionAbsente(() => setSessionPerdue(true));
    // Un seul abonné à la fois (`api/client.ts`) : se désabonner au
    // démontage, sinon une seconde instance (peu probable, mais le mode
    // strict de React en monte deux au développement) écraserait la
    // première sans le dire.
    return () => surSessionAbsente(null);
  }, []);

  // --- le calcul ---------------------------------------------------------

  async function chercher(surcharge?: Partial<Demande>) {
    const finale = { ...demande, ...surcharge };
    setDemande(finale);
    setErreurCalcul(null);
    const operation = finale.mode === "seance" ? "sortie" : "boucle";
    setEnCalcul(budgetDe(operation) ?? null);
    try {
      if (finale.mode === "seance") {
        // **Un seul des deux champs part** (Q44) : l'API refuse `direction`
        // et un `vent` contraignant envoyés ensemble. `modeDirection` est la
        // seule source de vérité ici — jamais les deux champs à la fois,
        // quoi que porte encore `demande.direction`/`demande.vent` d'un
        // mode qu'on a quitté.
        const orientation: { direction?: string; vent?: string } =
          finale.modeDirection === "direction"
            ? { direction: finale.direction, vent: "peu-importe" }
            : finale.modeDirection === "vent"
              ? { vent: finale.vent }
              : { vent: "peu-importe" };
        const reponse = await api.sortie({
          jour: finale.jour,
          heure_depart: `${finale.jour}T${finale.heure_depart}`,
          candidates: finale.candidates,
          ...orientation,
          depart: finale.depart ?? undefined,
          // **Le jour doit correspondre** (B1) — voir `fichierPourLaRecherche`.
          fichier_seance: fichierPourLaRecherche(fichierSeance, finale.jour),
        });
        // La séance placée porte les emplacements, pas les étapes : celles-ci
        // viennent de la route des séances, ou du dépôt de fichier.
        let seance: Seance | null = null;
        try {
          seance = (await api.seance(finale.jour)).donnees;
        } catch {
          seance = null;
        }
        setResultat({ sortie: reponse, boucle: null, seance, jour: finale.jour });
        // Retenu pour **son** jour, quel qu'il soit (C10).
        const memorisee = retenirSortie(finale.jour, reponse);
        if (finale.jour === jour) setMemoire(memorisee);
        setJoursMemorises((connus) =>
          connus.includes(finale.jour) ? connus : [...connus, finale.jour],
        );
        setVue({ genre: "propositions" });
      } else {
        // Q47 : `boucle` balaie tout l'horizon sans direction, comme `sortie`
        // — même règle que la branche `seance` ci-dessus, `modeDirection` est
        // la seule source de vérité. `/boucles` n'a pas de champ `vent`
        // (Q44, resté ouvert) : le mode « vent » retombe déjà sur « peu
        // importe » en Z2 (voir l'effet dans `Demander.tsx`), donc seul
        // « direction » envoie un azimut ici.
        const reponse = await api.boucle({
          distance_km: Math.max(
            1,
            ((zonesCourantes?.valeurs_liees?.moyenne_compteur_kmh ?? 0) * finale.duree_min) / 60,
          ),
          direction: finale.modeDirection === "direction" ? finale.direction : undefined,
          heure_depart: `${finale.jour}T${finale.heure_depart}`,
          candidates: finale.candidates,
          depart: finale.depart ?? undefined,
        });
        setResultat({ sortie: null, boucle: reponse, seance: null, jour: finale.jour });
        setVue({ genre: "boucles" });
      }
    } catch (cause) {
      setErreurCalcul(
        cause instanceof ErreurApi
          ? cause
          : new ErreurApi(
              { code: "erreur_interne", message: String(cause), service: null, details: {} },
              0,
            ),
      );
    } finally {
      setEnCalcul(null);
    }
  }

  // --- l'amorçage --------------------------------------------------------

  // **Avant même `zones.erreur`** (lot L7.2-D) : une session perdue amène
  // l'écran de connexion, pas un écran d'échec. `surConnecte` ne perd rien
  // de ce que le cycliste faisait — `onglet`, `vue`, `demande` restent tels
  // quels, seules les ressources qui ont échoué sont relues.
  if (sessionPerdue) {
    return (
      <div className="coquille">
        <Connexion
          surConnecte={() => {
            // **Avant de recharger.** Une requête partie sous l'ancienne
            // session peut encore revenir avec son 401 ; sans ce repère, elle
            // rouvrirait cet écran alors qu'on vient d'en sortir.
            sessionRouverte();
            setSessionPerdue(false);
            systeme.recharger();
            profil.recharger();
            zones.recharger();
            semaine.recharger();
            seanceDuJour.recharger();
          }}
        />
      </div>
    );
  }

  // **`zones.erreur` compte comme les deux autres** (corrigé le 17/09/2026).
  // Il n'était consulté nulle part, alors que l'affichage est interdit tant
  // que `zonesCourantes` est `null` : une panne de `/profil/zones` laissait
  // donc « Connexion au serveur… » pour toujours — sans code, sans bouton,
  // sans barre d'onglets. C'est exactement l'écran muet que la section
  // « Quand ça casse » des maquettes interdit, et le seul geste possible
  // était le rechargement, que l'écran d'attente déconseille (B2).
  if (systeme.erreur || profil.erreur || zones.erreur) {
    return (
      <div className="coquille">
        <Echec
          erreur={(systeme.erreur ?? profil.erreur ?? zones.erreur)!}
          contexte="Démarrage"
          reessayer={() => {
            systeme.recharger();
            profil.recharger();
            zones.recharger();
          }}
        />
      </div>
    );
  }

  if (!profilCourant || !zonesCourantes || !systeme.valeur) {
    return (
      <div className="coquille">
        <div className="vide">Connexion au serveur…</div>
      </div>
    );
  }

  if (enCalcul !== null) {
    return (
      <div className="coquille">
        <Attente
          budget={enCalcul}
          contexte={`${demande.mode === "seance" ? "Votre séance" : "Endurance Z2"} · ${
            demande.jour
          } · ${demande.heure_depart}`}
        />
      </div>
    );
  }

  // --- les échecs de calcul, qui sont des écrans -------------------------

  if (erreurCalcul !== null) {
    const replis: Repli[] = [];
    if (erreurCalcul.code === "aucune_boucle") {
      if (demande.mode === "z2") {
        replis.push({
          titre: "Élargir la durée",
          detail: `${Math.round(demande.duree_min * 0.9)} à ${Math.round(
            demande.duree_min * 1.1,
          )} minutes`,
          action: () => chercher({ duree_min: Math.round(demande.duree_min * 1.1) }),
        });
      }
      if (demande.modeDirection === "vent" && demande.vent !== "peu-importe") {
        replis.push({
          titre: "Laisser le vent libre",
          detail: "« Peu importe » au lieu d'imposer une orientation",
          action: () => chercher({ vent: "peu-importe", modeDirection: "peu-importe" }),
        });
      }
      replis.push({
        titre: "Chercher plus loin",
        detail: `${demande.candidates} candidates aujourd'hui, 8 au prochain essai`,
        action: () => chercher({ candidates: 8 }),
      });
    }
    return (
      <div className="coquille">
        <Echec
          erreur={erreurCalcul}
          contexte={`${demande.jour} · départ ${demande.heure_depart}`}
          replis={replis}
          dernierSucces={derniereLectureSeances()}
          reessayer={() => chercher()}
          secours={
            <div className="boutons">
              <button
                type="button"
                className="bouton second"
                onClick={() => {
                  setErreurCalcul(null);
                  setOnglet("demander");
                  setVue({ genre: "onglet" });
                }}
              >
                Modifier la demande
              </button>
              <button
                type="button"
                className="bouton second"
                onClick={() => {
                  setErreurCalcul(null);
                  // La recherche qui vient d'échouer portait sur ce jour-là :
                  // c'est pour lui qu'on dépose.
                  setVue({ genre: "importer", jour: demande.jour });
                }}
              >
                Déposer une séance
              </button>
            </div>
          }
        />
        <BarreOnglets
          onglet={onglet}
          surOnglet={(cle) => {
            setErreurCalcul(null);
            setOnglet(cle);
            setVue({ genre: "onglet" });
          }}
        />
      </div>
    );
  }

  // --- les vues ----------------------------------------------------------

  let contenu: JSX.Element;

  // Le nom de l'onglet courant — l'assistant et l'importateur n'en changent
  // pas eux-mêmes, donc c'est là qu'on revient en en sortant. « Aujourd'hui »
  // par défaut : c'est aussi le seul onglet possible avant tout profil.
  const versOnglet = ONGLETS.find((o) => o.cle === onglet)?.nom ?? "Aujourd'hui";

  if (vue.genre === "assistant") {
    contenu = (
      <Assistant
        profil={profilCourant}
        zones={zonesCourantes}
        surProfil={setProfilCourant}
        surZones={setZonesCourantes}
        surFin={() => {
          setVue({ genre: "onglet" });
          setOnglet("aujourdhui");
        }}
        vers={versOnglet}
        surRetour={() => setVue({ genre: "onglet" })}
      />
    );
  } else if (vue.genre === "importer") {
    contenu = (
      <Importer
        jour={vue.jour}
        surSeanceLue={(seance, identifiant) =>
          setFichierSeance({ identifiant, jour: vue.jour, nom: seance.nom })
        }
        surChercher={() => chercher({ mode: "seance", jour: vue.jour })}
        vers={versOnglet}
        surRetour={() => setVue({ genre: "onglet" })}
      />
    );
  } else if (vue.genre === "propositions" && resultat?.sortie) {
    const reponse = resultat.sortie;
    const parDefaut = reponse.donnees.propositions.find((p) => p.retenue)?.numero ?? 1;
    contenu = (
      <Propositions
        reponse={reponse}
        choisie={parDefaut}
        surChoix={(numero) => setVue({ genre: "detail", numero })}
        surOuvrir={() => setVue({ genre: "detail", numero: parDefaut })}
        surElargir={() => chercher({ candidates: 8 })}
        surRetour={() => {
          setVue({ genre: "onglet" });
          setOnglet("demander");
        }}
      />
    );
  } else if (vue.genre === "detail" && resultat?.sortie) {
    contenu = (
      // `key` force un démontage à chaque changement de proposition : sans
      // lui, l'état local de l'écran (la panne du partage GPX, par exemple)
      // survivrait au passage de la proposition N à la M — relevé en
      // relecture le 18/09/2026.
      <PropositionDetail
        key={vue.numero}
        reponse={resultat.sortie}
        numero={vue.numero}
        seance={resultat.seance}
        surRetour={() => setVue({ genre: "propositions" })}
      />
    );
  } else if (vue.genre === "boucles" && resultat?.boucle) {
    contenu = (
      <Boucles
        reponse={resultat.boucle}
        surRetour={() => {
          setVue({ genre: "onglet" });
          setOnglet("demander");
        }}
      />
    );
  } else if (onglet === "aujourdhui") {
    contenu = seanceDuJour.erreur ? (
      <Echec
        erreur={seanceDuJour.erreur}
        contexte="Aujourd'hui"
        dernierSucces={derniereLectureSeances()}
        reessayer={seanceDuJour.recharger}
        secours={
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>En attendant</h2>
            </div>
            <p className="mention">
              Vous pouvez demander un parcours à la main, déposer un fichier de séance, ou déposer vos
              sorties passées — c'est l'autre source d'historique, sans Intervals.
              Tout le reste fonctionne.
            </p>
            <div className="boutons" style={{ marginTop: 11 }}>
              <button
                type="button"
                className="bouton second"
                onClick={() => setOnglet("demander")}
              >
                Demander
              </button>
              <button
                type="button"
                className="bouton second"
                onClick={() => setVue({ genre: "importer", jour })}
              >
                Déposer
              </button>
            </div>
          </div>
        }
      />
    ) : seanceDuJour.chargement ? (
      <div className="vide">Lecture de votre séance…</div>
    ) : (
      <Aujourdhui
        jour={jour}
        seance={seanceDuJour.valeur?.donnees ?? null}
        parcours={memoire}
        surGenerer={() => chercher({ mode: "seance", jour })}
        surOuvrir={() => {
          if (memoire) {
            setResultat({
              sortie: memoire.reponse,
              boucle: null,
              seance: seanceDuJour.valeur?.donnees ?? null,
              jour,
            });
            setVue({ genre: "propositions" });
          }
        }}
        surDemander={() => setOnglet("demander")}
        surDeposer={() => setVue({ genre: "importer", jour })}
      />
    );
  } else if (onglet === "semaine") {
    contenu = semaine.erreur ? (
      <Echec
        erreur={semaine.erreur}
        contexte="Ma semaine"
        dernierSucces={derniereLectureSeances()}
        reessayer={semaine.recharger}
        secours={
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>En attendant</h2>
            </div>
            <p className="mention">
              Vous pouvez demander un parcours à la main, déposer un fichier de séance, ou déposer vos
              sorties passées — c'est l'autre source d'historique, sans Intervals.
              Tout le reste fonctionne.
            </p>
            <div className="boutons" style={{ marginTop: 11 }}>
              <button
                type="button"
                className="bouton second"
                onClick={() => setOnglet("demander")}
              >
                Demander
              </button>
              <button
                type="button"
                className="bouton second"
                onClick={() => setVue({ genre: "importer", jour })}
              >
                Déposer
              </button>
            </div>
          </div>
        }
      />
    ) : semaine.chargement ? (
      <div className="vide">Lecture de votre semaine…</div>
    ) : (
      <MaSemaine
        semaine={semaine.valeur!.donnees}
        aujourdhui={jour}
        joursAvecParcours={joursMemorises}
        surGenerer={(quand) => chercher({ mode: "seance", jour: quand })}
        // **Le jour qu'on nous passe** (C10). `surVoir` l'ignorait et rouvrait
        // toujours la sortie d'aujourd'hui — un corollaire mort tant qu'un
        // seul jour pouvait être mémorisé, un faux parcours dès que deux le
        // sont.
        surVoir={(quand) => {
          const memorisee = quand === jour ? memoire : sortieRetenue(quand);
          if (!memorisee) return;
          setResultat({
            sortie: memorisee.reponse,
            boucle: null,
            // Les étapes de la séance ne sont sous la main que pour
            // aujourd'hui : ailleurs, l'écran s'en passe plutôt que de
            // montrer celles d'un autre jour.
            seance: quand === jour ? (seanceDuJour.valeur?.donnees ?? null) : null,
            jour: quand,
          });
          setVue({ genre: "propositions" });
        }}
        surDeposer={() => setVue({ genre: "importer", jour })}
      />
    );
  } else if (onglet === "demander") {
    contenu = (
      <Demander
        profil={profilCourant}
        zones={zonesCourantes}
        dureeSeance_s={seanceDemandee?.duree_s ?? null}
        nomSeance={seanceDemandee?.nom ?? null}
        demande={demande}
        // Le même budget que celui contre lequel l'attente s'animera (C3).
        budget={budgetDe(demande.mode === "seance" ? "sortie" : "boucle")}
        surDemande={setDemande}
        surChercher={() => chercher()}
      />
    );
  } else {
    contenu = (
      <Reglages
        profil={profilCourant}
        zones={zonesCourantes}
        surProfil={setProfilCourant}
        surZones={setZonesCourantes}
        surRefaireInstallation={() => setVue({ genre: "assistant" })}
        // Repart à `/connexion` plutôt que de tenter de remettre l'état de
        // cette instance à zéro : après une déconnexion volontaire, rien de
        // ce que le cycliste faisait n'a de raison de survivre.
        surDeconnexion={() => window.location.assign("/connexion")}
      />
    );
  }

  return (
    <div className="coquille">
      {fichierSeance ? (
        <BandeauSeanceDeposee
          deposee={fichierSeance}
          jourDemande={demande.jour}
          surRetirer={() => setFichierSeance(null)}
        />
      ) : null}
      {contenu}
      <BarreOnglets
        onglet={onglet}
        surOnglet={(cle) => {
          setOnglet(cle);
          setVue({ genre: "onglet" });
        }}
      />
    </div>
  );
}

/**
 * « Un fichier est en usage » — dit à l'écran, pas seulement dans l'état React.
 *
 * Le second défaut de B1 : même corrigé, un fichier qui se replace tout seul
 * sur une recherche est invisible. Le bandeau dit lequel, pour quel jour, et
 * **s'il va servir à la recherche en cours** — parce que « déposé » et
 * « appliqué » ne sont plus la même chose depuis qu'il est rattaché à un jour.
 */
function BandeauSeanceDeposee({
  deposee,
  jourDemande,
  surRetirer,
}: {
  deposee: SeanceDeposee;
  jourDemande: string;
  surRetirer: () => void;
}) {
  const actif = deposee.jour === jourDemande;
  return (
    <div className={actif ? "encart attention" : "encart"}>
      <b>Séance déposée : {deposee.nom}.</b>{" "}
      {actif
        ? `Elle sera placée sur le parcours du ${jourEnLettres(deposee.jour)}.`
        : `Elle vaut pour le ${jourEnLettres(deposee.jour)} — la recherche en cours porte sur
           un autre jour, et ne s'en servira pas.`}{" "}
      <button type="button" className="lien" onClick={surRetirer}>
        Retirer ce fichier
      </button>
    </div>
  );
}

const PICTOGRAMMES: Record<Onglet, (props: { className?: string }) => JSX.Element> = {
  aujourdhui: IconeAujourdhui,
  semaine: IconeSemaine,
  demander: IconeDemander,
  reglages: IconeReglages,
};

function BarreOnglets({
  onglet,
  surOnglet,
}: {
  onglet: Onglet;
  surOnglet: (cle: Onglet) => void;
}) {
  return (
    <nav className="onglets" aria-label="Navigation principale">
      {ONGLETS.map((entree) => {
        const Pictogramme = PICTOGRAMMES[entree.cle];
        return (
          <button
            type="button"
            key={entree.cle}
            aria-current={onglet === entree.cle ? "page" : undefined}
            onClick={() => surOnglet(entree.cle)}
          >
            <Pictogramme className="onglet-icone" />
            <span className="onglet-libelle">{entree.nom}</span>
          </button>
        );
      })}
    </nav>
  );
}

/** L'application : quatre onglets, et ce qui se passe entre eux.
 *
 * Tout ce qui s'affiche vient de l'API. Cette règle n'est pas une intention,
 * c'est la forme du code : aucun écran n'a de valeur par défaut, et un champ
 * que l'API ne rend pas n'existe pas dans les types (`api/types.ts`).
 *
 * Le calcul d'un parcours est **semi-synchrone** : la requête tient, l'écran
 * d'attente anime contre le budget annoncé par `/systeme/budgets`, et la
 * réponse dit ce que ça a réellement pris.
 *
 * Ce fichier ne porte que l'assemblage — la page (avant
 * toute session), le chargement des ressources de démarrage, et le choix de
 * l'écran. Les types de navigation, la barre d'onglets, le bandeau de séance
 * déposée, l'état d'une recherche et le contenu selon la vue vivent dans
 * `src/app/`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, surSessionAbsente } from "./api/client";
import type { Profil, Zones } from "./api/types";
import { aujourdhui, useRessource } from "./etat/ressource";
import { retenirLectureSeances, sortieRetenue } from "./etat/memoire";
import { Attente } from "./composants/Attente";
import { Connexion } from "./ecrans/Connexion";
import { Entrer } from "./ecrans/Entrer";
import { BarreOnglets } from "./app/BarreOnglets";
import { BandeauSeanceDeposee } from "./app/BandeauSeanceDeposee";
import { EchecCalcul } from "./app/EchecCalcul";
import { EcranAmorcage } from "./app/EcranAmorcage";
import { Contenu } from "./app/Contenu";
import { useRecherche } from "./app/useRecherche";
import { heureDepartResolue } from "./ecrans/Demander";
import { useNavigationHistorique } from "./app/useNavigationHistorique";
import {
  ongletDepuisUrl,
  paginaDepuisUrl,
  type Onglet,
  type SeanceDeposee,
  type Vue,
} from "./app/navigation";

export { fichierPourLaRecherche } from "./app/navigation";
export type { SeanceDeposee } from "./app/navigation";

/**
 * Le point d'entrée : décide une fois pour toutes sur quelle page on est
 * et rend `ApplicationPrincipale` — les quatre onglets — pour tout le reste.
 *
 * `Entrer` et `Connexion` naviguent en repartant à la racine
 * (`window.location.assign`) plutôt qu'en gardant un état de page ici : une
 * fois la session ouverte, il n'y a rien à préserver d'un écran qui n'a
 * montré qu'un formulaire, et repartir à zéro relance
 * `ApplicationPrincipale` sur une base propre, cookie posé.
 */
export function App() {
  const [pagina] = useState(() => paginaDepuisUrl());

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
  const [fichierSeance, setFichierSeance] = useState<SeanceDeposee | null>(null);
  const [profilCourant, setProfilCourant] = useState<Profil | null>(null);
  const [zonesCourantes, setZonesCourantes] = useState<Zones | null>(null);
  /**
   * Vrai dès qu'une route quelconque a répondu 401 `session_absente` — la session a expiré, ou n'a jamais existé. `api.client`
   * prévient au moment même où **n'importe quel** appel reçoit ce code, pas
   * seulement les trois ressources de démarrage ci-dessous : une séance qui
   * expire pendant que le cycliste choisit une proposition doit amener le
   * même écran de connexion, pas l'erreur technique nue de `session_absente`.
   */
  const [sessionPerdue, setSessionPerdue] = useState(false);

  // L'historique du navigateur (onglet dans l'adresse, résultats en
  // entrées sans adresse propre) — voir `useNavigationHistorique.ts`.
  const allerVersOnglet = useNavigationHistorique(onglet, setOnglet, setVue);

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
   * (« Aujourd'hui » réclame Intervals et échouerait). Ne force qu'**une seule fois** — dès que la
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
    (operation: string) => systeme.valeur?.budgets.find((b) => b.operation === operation) ?? null,
    [systeme.valeur],
  );

  // --- les ressources des onglets ---------------------------------------

  const seanceDuJour = useRessource(() => api.seance(jour), [jour]);
  const semaine = useRessource(() => api.semaine(), []);

  const {
    demande,
    setDemande,
    resultat,
    setResultat,
    enCalcul,
    erreurCalcul,
    setErreurCalcul,
    memoire,
    joursMemorises,
    setJoursMemorises,
    chercher,
  } = useRecherche({ jour, onglet, fichierSeance, zonesCourantes, budgetDe, setVue });

  // Intervals se branche via l'assistant ou Réglages sans que `jour` bouge :
  // sans ce rechargement, la séance et la semaine restent sur leur premier
  // échec (409 intervals_absent) jusqu'au rechargement de page. Seul le passage « profil connu, non branché » →
  // « branché » recharge : l'arrivée du profil au démarrage (null → branché)
  // ne doit pas doubler les appels de chaque ouverture.
  const intervalsBranche = profilCourant ? profilCourant.services.intervals.renseigne : null;
  const brancheAvant = useRef(intervalsBranche);
  useEffect(() => {
    if (brancheAvant.current === false && intervalsBranche === true) {
      seanceDuJour.recharger();
      semaine.recharger();
    }
    brancheAvant.current = intervalsBranche;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalsBranche]);

  useEffect(() => {
    if (semaine.valeur) retenirLectureSeances(jour);
  }, [semaine.valeur, jour]);

  // Au retour sur l'application, les parcours déjà calculés de la semaine
  // sont dans le stockage : on les y relit plutôt que de les oublier.
  useEffect(() => {
    const jours = semaine.valeur?.donnees.jours ?? [];
    setJoursMemorises(jours.map((j) => j.jour).filter((j) => sortieRetenue(j) !== null));
  }, [semaine.valeur, setJoursMemorises]);

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

  // --- l'amorçage --------------------------------------------------------

  const amorcage = EcranAmorcage({
    sessionPerdue,
    setSessionPerdue,
    systeme,
    profil,
    zones,
    semaine,
    seanceDuJour,
  });
  if (amorcage) return amorcage;

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
          } · ${heureDepartResolue(demande)}`}
        />
      </div>
    );
  }

  // --- les échecs de calcul, qui sont des écrans -------------------------

  if (erreurCalcul !== null) {
    return (
      <EchecCalcul
        erreur={erreurCalcul}
        demande={demande}
        onglet={onglet}
        chercher={chercher}
        fermerErreur={() => setErreurCalcul(null)}
        allerVersDemander={() => {
          setErreurCalcul(null);
          allerVersOnglet("demander");
        }}
        allerVersDepot={() => {
          setErreurCalcul(null);
          setVue({ genre: "importer", jour: demande.jour });
        }}
        changerOnglet={allerVersOnglet}
      />
    );
  }

  // --- les vues ------------------------------------------------------------

  const contenu = (
    <Contenu
      vue={vue}
      setVue={setVue}
      onglet={onglet}
      setOnglet={setOnglet}
      resultat={resultat}
      setResultat={setResultat}
      jour={jour}
      profilCourant={profilCourant}
      setProfilCourant={setProfilCourant}
      zonesCourantes={zonesCourantes}
      setZonesCourantes={setZonesCourantes}
      setFichierSeance={setFichierSeance}
      demande={demande}
      setDemande={setDemande}
      seanceDemandee={seanceDemandee}
      budgetDe={budgetDe}
      chercher={chercher}
      seanceDuJour={seanceDuJour}
      semaine={semaine}
      joursMemorises={joursMemorises}
      memoire={memoire}
    />
  );

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
      <BarreOnglets onglet={onglet} surOnglet={allerVersOnglet} />
    </div>
  );
}

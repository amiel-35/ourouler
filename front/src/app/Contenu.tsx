/** Séparé d'`App.tsx` — le contenu principal (hors barre d'onglets et
 * bandeau de séance déposée), choisi sur `vue.genre` puis sur `onglet` : un
 * arbre de décision, dans son propre fichier.
 */

import type { Budget, Enveloppe, Profil, Seance, SeanceResumee, Semaine, Zones } from "../api/types";
import type { Ressource } from "../etat/ressource";
import { derniereLectureSeances, sortieRetenue, type SortieMemorisee } from "../etat/memoire";
import { Echec } from "../composants/Echec";
import { Aujourdhui } from "../ecrans/Aujourdhui";
import { MaSemaine } from "../ecrans/MaSemaine";
import { Demander, heureDepartResolue, type Demande } from "../ecrans/Demander";
import { Importer } from "../ecrans/Importer";
import { AnalyserParcours } from "../ecrans/AnalyserParcours";
import { Propositions } from "../ecrans/Propositions";
import { PropositionDetail } from "../ecrans/Proposition";
import { Boucles } from "../ecrans/Boucles";
import { Reglages } from "../ecrans/Reglages";
import { Assistant } from "../ecrans/Assistant";
import { EnAttendantHistorique } from "./EnAttendantHistorique";
import { ONGLETS, type Onglet, type Resultat, type SeanceDeposee, type Vue } from "./navigation";

export interface ContenuProps {
  vue: Vue;
  setVue: (vue: Vue) => void;
  onglet: Onglet;
  setOnglet: (onglet: Onglet) => void;
  resultat: Resultat | null;
  setResultat: (resultat: Resultat | null) => void;
  jour: string;
  profilCourant: Profil;
  setProfilCourant: (profil: Profil) => void;
  zonesCourantes: Zones;
  setZonesCourantes: (zones: Zones) => void;
  setFichierSeance: (deposee: SeanceDeposee | null) => void;
  demande: Demande;
  setDemande: (demande: Demande) => void;
  seanceDemandee: Seance | SeanceResumee | null;
  budgetDe: (operation: string) => Budget | null;
  chercher: (surcharge?: Partial<Demande>) => void | Promise<void>;
  seanceDuJour: Ressource<Enveloppe<Seance | null>>;
  semaine: Ressource<Enveloppe<Semaine>>;
  joursMemorises: string[];
  memoire: SortieMemorisee | null;
}

export function Contenu(props: ContenuProps): JSX.Element {
  const {
    vue,
    setVue,
    onglet,
    setOnglet,
    resultat,
    setResultat,
    jour,
    profilCourant,
    setProfilCourant,
    zonesCourantes,
    setZonesCourantes,
    setFichierSeance,
    demande,
    setDemande,
    seanceDemandee,
    budgetDe,
    chercher,
    seanceDuJour,
    semaine,
    joursMemorises,
    memoire,
  } = props;

  // Le nom de l'onglet courant — l'assistant et l'importateur n'en changent
  // pas eux-mêmes, donc c'est là qu'on revient en en sortant. « Aujourd'hui »
  // par défaut : c'est aussi le seul onglet possible avant tout profil.
  const versOnglet = ONGLETS.find((o) => o.cle === onglet)?.nom ?? "Aujourd'hui";

  if (vue.genre === "assistant") {
    return (
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
  }
  if (vue.genre === "importer") {
    return (
      <Importer
        jour={vue.jour}
        surSeanceLue={(seance, identifiant) =>
          setFichierSeance({ identifiant, jour: vue.jour, nom: seance.nom })
        }
        surChercher={() => chercher({ mode: "seance", jour: vue.jour })}
        surAnalyser={() => setVue({ genre: "analyser", jour: vue.jour })}
        vers={versOnglet}
        surRetour={() => setVue({ genre: "onglet" })}
      />
    );
  }
  if (vue.genre === "analyser") {
    return (
      <AnalyserParcours vers="Déposer" surRetour={() => setVue({ genre: "importer", jour: vue.jour })} />
    );
  }
  if (vue.genre === "propositions" && resultat?.sortie) {
    const reponse = resultat.sortie;
    const parDefaut = reponse.donnees.propositions.find((p) => p.retenue)?.numero ?? 1;
    return (
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
  }
  if (vue.genre === "detail" && resultat?.sortie) {
    return (
      // `key` force un démontage à chaque changement de proposition : sans
      // lui, l'état local de l'écran (la panne du partage GPX, par exemple)
      // survivrait au passage de la proposition N à la M.
      <PropositionDetail
        key={vue.numero}
        reponse={resultat.sortie}
        numero={vue.numero}
        seance={resultat.seance}
        surRetour={() => setVue({ genre: "propositions" })}
      />
    );
  }
  if (vue.genre === "boucles" && resultat?.boucle) {
    return (
      <Boucles
        reponse={resultat.boucle}
        surRetour={() => {
          setVue({ genre: "onglet" });
          setOnglet("demander");
        }}
      />
    );
  }
  if (onglet === "aujourdhui") {
    if (seanceDuJour.erreur) {
      return (
        <Echec
          erreur={seanceDuJour.erreur}
          contexte="Aujourd'hui"
          dernierSucces={derniereLectureSeances()}
          reessayer={seanceDuJour.recharger}
          secours={
            <EnAttendantHistorique
              surDemander={() => setOnglet("demander")}
              surDeposer={() => setVue({ genre: "importer", jour })}
            />
          }
        />
      );
    }
    if (seanceDuJour.chargement) {
      return <div className="vide">Lecture de votre séance…</div>;
    }
    return (
      <Aujourdhui
        jour={jour}
        seance={seanceDuJour.valeur?.donnees ?? null}
        parcours={memoire}
        // Résolue ici, pas mémorisée : le défaut du jour (`heure_depart ===
        // null`) reste à jour tant que le cycliste n'a rien saisi.
        heureDepart={heureDepartResolue(demande)}
        surHeureDepart={(heure_depart) => setDemande({ ...demande, heure_depart })}
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
  }
  if (onglet === "semaine") {
    if (semaine.erreur) {
      return (
        <Echec
          erreur={semaine.erreur}
          contexte="Ma semaine"
          dernierSucces={derniereLectureSeances()}
          reessayer={semaine.recharger}
          secours={
            <EnAttendantHistorique
              surDemander={() => setOnglet("demander")}
              surDeposer={() => setVue({ genre: "importer", jour })}
            />
          }
        />
      );
    }
    if (semaine.chargement) {
      return <div className="vide">Lecture de votre semaine…</div>;
    }
    return (
      <MaSemaine
        semaine={semaine.valeur!.donnees}
        aujourdhui={jour}
        joursAvecParcours={joursMemorises}
        surGenerer={(quand) => chercher({ mode: "seance", jour: quand })}
        // **Le jour qu'on nous passe.** L'ignorer rouvrirait toujours la
        // sortie d'aujourd'hui — un faux parcours dès que deux jours sont
        // mémorisés.
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
  }
  if (onglet === "demander") {
    return (
      <Demander
        profil={profilCourant}
        zones={zonesCourantes}
        dureeSeance_s={seanceDemandee?.duree_s ?? null}
        nomSeance={seanceDemandee?.nom ?? null}
        demande={demande}
        // Le même budget que celui contre lequel l'attente s'animera.
        budget={budgetDe(demande.mode === "seance" ? "sortie" : "boucle")}
        surDemande={setDemande}
        surChercher={() => chercher()}
      />
    );
  }
  return (
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


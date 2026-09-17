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

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ErreurApi } from "./api/client";
import type { Boucle, Budget, Enveloppe, Profil, Seance, Sortie, Zones } from "./api/types";
import { aujourdhui, useRessource } from "./etat/ressource";
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

type Onglet = "aujourdhui" | "semaine" | "demander" | "reglages";
type Vue =
  | { genre: "onglet" }
  | { genre: "assistant" }
  | { genre: "importer" }
  | { genre: "propositions" }
  | { genre: "detail"; numero: number }
  | { genre: "boucles" };

interface Resultat {
  sortie: Enveloppe<Sortie> | null;
  boucle: Enveloppe<Boucle> | null;
  seance: Seance | null;
  jour: string;
}

const ONGLETS: { cle: Onglet; nom: string }[] = [
  { cle: "aujourdhui", nom: "Aujourd'hui" },
  { cle: "semaine", nom: "Ma semaine" },
  { cle: "demander", nom: "Demander" },
  { cle: "reglages", nom: "Réglages" },
];

export function App() {
  const jour = aujourdhui();
  const [onglet, setOnglet] = useState<Onglet>("aujourdhui");
  const [vue, setVue] = useState<Vue>({ genre: "onglet" });
  const [demande, setDemande] = useState<Demande>(demandeInitiale);
  const [resultat, setResultat] = useState<Resultat | null>(null);
  const [enCalcul, setEnCalcul] = useState<Budget | null>(null);
  const [erreurCalcul, setErreurCalcul] = useState<ErreurApi | null>(null);
  const [fichierSeance, setFichierSeance] = useState<string | null>(null);
  const [memoire, setMemoire] = useState<SortieMemorisee | null>(() => sortieRetenue(jour));
  const [profilCourant, setProfilCourant] = useState<Profil | null>(null);
  const [zonesCourantes, setZonesCourantes] = useState<Zones | null>(null);

  const systeme = useRessource(() => api.systeme(), []);
  const profil = useRessource(() => api.profil(), []);
  const zones = useRessource(() => api.zones(), []);

  useEffect(() => {
    if (profil.valeur) setProfilCourant(profil.valeur.donnees);
  }, [profil.valeur]);
  useEffect(() => {
    if (zones.valeur) setZonesCourantes(zones.valeur.donnees);
  }, [zones.valeur]);

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

  const seanceDemandee = useMemo(() => {
    if (demande.jour === jour) return seanceDuJour.valeur?.donnees ?? null;
    const trouve = semaine.valeur?.donnees.jours.find((j) => j.jour === demande.jour);
    return trouve?.seance ?? null;
  }, [demande.jour, jour, seanceDuJour.valeur, semaine.valeur]);

  // --- le calcul ---------------------------------------------------------

  async function chercher(surcharge?: Partial<Demande>) {
    const finale = { ...demande, ...surcharge };
    setDemande(finale);
    setErreurCalcul(null);
    const operation = finale.mode === "seance" ? "sortie" : "boucle";
    setEnCalcul(budgetDe(operation) ?? null);
    try {
      if (finale.mode === "seance") {
        const reponse = await api.sortie({
          jour: finale.jour,
          heure_depart: `${finale.jour}T${finale.heure_depart}`,
          candidates: finale.candidates,
          vent: finale.vent,
          depart: finale.depart ?? undefined,
          fichier_seance: fichierSeance ?? undefined,
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
        if (finale.jour === jour) setMemoire(retenirSortie(jour, reponse));
        setVue({ genre: "propositions" });
      } else {
        const reponse = await api.boucle({
          distance_km: Math.max(
            1,
            ((zonesCourantes?.valeurs_liees?.moyenne_compteur_kmh ?? 0) * finale.duree_min) / 60,
          ),
          direction: finale.direction,
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

  if (systeme.erreur || profil.erreur) {
    return (
      <div className="coquille">
        <Echec
          erreur={(systeme.erreur ?? profil.erreur)!}
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
      if (demande.vent !== "peu-importe") {
        replis.push({
          titre: "Laisser le vent libre",
          detail: "« Peu importe » au lieu d'imposer une orientation",
          action: () => chercher({ vent: "peu-importe" }),
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
                  setVue({ genre: "importer" });
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
      />
    );
  } else if (vue.genre === "importer") {
    contenu = (
      <Importer
        jour={demande.jour}
        surSeanceLue={(_seance, identifiant) => setFichierSeance(identifiant)}
        surChercher={() => chercher({ mode: "seance" })}
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
      <PropositionDetail
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
              Vous pouvez demander un parcours à la main, ou déposer un fichier de séance.
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
                onClick={() => setVue({ genre: "importer" })}
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
        surDeposer={() => setVue({ genre: "importer" })}
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
              Vous pouvez demander un parcours à la main, ou déposer un fichier de séance.
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
                onClick={() => setVue({ genre: "importer" })}
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
        joursAvecParcours={memoire ? [memoire.jour] : []}
        surGenerer={(quand) => chercher({ mode: "seance", jour: quand })}
        surVoir={() => {
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
        surDeposer={() => setVue({ genre: "importer" })}
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
      />
    );
  }

  return (
    <div className="coquille">
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

function BarreOnglets({
  onglet,
  surOnglet,
}: {
  onglet: Onglet;
  surOnglet: (cle: Onglet) => void;
}) {
  return (
    <nav className="onglets" aria-label="Navigation principale">
      {ONGLETS.map((entree) => (
        <button
          type="button"
          key={entree.cle}
          aria-current={onglet === entree.cle ? "page" : undefined}
          onClick={() => surOnglet(entree.cle)}
        >
          {entree.nom}
        </button>
      ))}
    </nav>
  );
}

/** Les listes de rangées des Réglages : chaque rangée montre une valeur et
 * ouvre, quand elle se modifie, le volet correspondant. */

import { api } from "../../api/client";
import type { EtatCalibrations, Profil } from "../../api/types";
import { jourEnLettres, masseVeloAffichee, usageDeVelo } from "../../api/formats";

export type Volet = "identite" | "ftp" | "poids" | "depart" | "velos" | "intervals" | "compte" | null;

interface Bascule {
  volet: Volet;
  basculer: (cible: Exclude<Volet, null>) => void;
}

export function RangeesDepartVelos({
  profil,
  calibrations,
  volet,
  basculer,
}: Bascule & { profil: Profil; calibrations: EtatCalibrations | null }) {
  return (
    <div className="bloc doux liste">
      <div className="rangee">
        <span className="cle">Départ habituel</span>
        <button
          type="button"
          className="val lien"
          onClick={() => basculer("depart")}
          aria-expanded={volet === "depart"}
        >
          {profil.depart.nom}
          {/* Le repli du produit (« Paris »), pas encore un départ renseigné
              — fiche docs/backlog/2026-09-28-bug-depart-fictif-golfe-de-guinee.md.
              On est déjà dans Réglages : pas de lien, le bouton ouvre déjà
              le volet qui le corrige. */}
          {profil.depart.par_defaut ? " (par défaut)" : ""}
        </button>
      </div>
      {profil.velos.map((velo) => (
        <div className="rangee" key={velo.nom}>
          <span className="cle">{velo.nom}</span>
          <span className="val texte">
            {usageDeVelo(velo.usage)} · {masseVeloAffichee(velo.masse_kg)}
            {velo.facteur_compteur === null
              ? " · vitesse supposée"
              : " · vitesse mesurée sur vos sorties"}
            {calibrations?.velos.find((c) => c.velo === velo.nom)?.calibration
              ? " · modèle mesuré sur vos sorties"
              : ""}
          </span>
        </div>
      ))}
      <div className="rangee">
        <span className="cle">Vos vélos</span>
        <button
          type="button"
          className="lien"
          onClick={() => basculer("velos")}
          aria-expanded={volet === "velos"}
        >
          Ajouter ou retirer
        </button>
      </div>
    </div>
  );
}

export function RangeesServices({ profil, volet, basculer }: Bascule & { profil: Profil }) {
  return (
    <div className="bloc doux liste">
      <div className="rangee">
        <span className="cle">intervals.icu</span>
        <button
          type="button"
          className="val lien texte"
          onClick={() => basculer("intervals")}
          aria-expanded={volet === "intervals"}
        >
          {profil.services.intervals.renseigne ? "Branché" : "Non branché"}
        </button>
      </div>
      <div className="rangee">
        <span className="cle">Traceur d'itinéraires</span>
        <span className="val texte">
          {/* `profil` est le nom du fichier de profil du traceur
              (`trekking`, `fastbike`…) : un identifiant de moteur de
              routage, sur une ligne qui s'appelle « Traceur d'itinéraires »
              en français. Il n'apprend rien à un cycliste, et le seul fait
              utile ici est que le service répond. */}
          {profil.services.brouter.renseigne ? "Branché" : "Non branché"}
        </span>
      </div>
      <div className="rangee">
        <span className="cle">Historique depuis</span>
        {/* C2, même défaut qu'à l'écran d'échec : une date ISO est une date
            de machine. */}
        <span className="val texte">{jourEnLettres(profil.historique_depuis)}</span>
      </div>
    </div>
  );
}

export function RangeesCompte({
  volet,
  basculer,
  surRefaireInstallation,
  surDeconnexion,
}: Bascule & { surRefaireInstallation: () => void; surDeconnexion: () => void }) {
  return (
    <div className="bloc doux liste">
      <div className="rangee">
        <span className="cle">Refaire l'installation</span>
        <button type="button" className="lien" onClick={surRefaireInstallation}>
          Reprendre
        </button>
      </div>
      {/* Mon compte : les clés d'accès (passkey) n'existent pas
          (`api/comptes.py`), mais l'adresse, le mot de passe, l'export et la
          suppression sont tous les quatre branchés. */}
      <div className="rangee">
        <span className="cle">Mon compte</span>
        <button
          type="button"
          className="val lien texte"
          onClick={() => basculer("compte")}
          aria-expanded={volet === "compte"}
        >
          Gérer
        </button>
      </div>
      {/* Se déconnecter. `POST /sortir` révoque la session et
          efface le cookie, toujours 200 (idempotent) : rien à vérifier
          avant d'appeler `surDeconnexion`, qui ramène à l'écran de
          connexion. */}
      <div className="rangee">
        <span className="cle">Session</span>
        <button
          type="button"
          className="lien"
          onClick={async () => {
            await api.sortir().catch(() => undefined);
            surDeconnexion();
          }}
        >
          Se déconnecter
        </button>
      </div>
    </div>
  );
}

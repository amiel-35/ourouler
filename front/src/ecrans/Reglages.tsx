/** E21 · E22 — profil et réglages.
 *
 * Six groupes, dans l'ordre où on y revient : l'identité, qui ne bouge
 * presque jamais, puis ce qui change souvent — un poids bouge, une FTP
 * progresse — et enfin ce qui ne se touche qu'une fois, en bas, jusqu'au
 * compte lui-même.
 *
 * **Identité (prénom, nom) reprend l'écran E8 de l'assistant** (obligatoires,
 * c'est la base : décision Q36). Un profil plus ancien peut arriver ici avec les deux champs vides — ce n'est pas une
 * panne, `Cycliste.prenom`/`nom` restent optionnels au chargement pour cette
 * raison précise — et ce panneau est l'endroit où le compléter.
 *
 * **« Mon compte » (`reglages/MonCompteVolet.tsx`)** porte ce qui revient au
 * compte : adresse, changement de mot de passe,
 * export RGPD et suppression — celle-ci à double confirmation, un texte
 * explicite avant le geste irréversible. Les clés d'accès (passkey) restent
 * hors sujet : `api/comptes.py` n'en porte toujours aucune.
 *
 * Les volets, les listes de rangées et la liste des vélos vivent dans
 * `reglages/` ; cet écran garde l'état partagé et les enregistrements.
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { EtatCalibrations, Profil, Zones } from "../api/types";
import { nombre, pourcentage } from "../api/formats";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";
import { ListeVelos } from "./reglages/ListeVelos";
import { MonCompteVolet } from "./reglages/MonCompteVolet";
import { RangeesCompte, RangeesDepartVelos, RangeesServices } from "./reglages/Rangees";
import type { Volet } from "./reglages/Rangees";
import { SectionCalibrations, VoletFtp, VoletIdentite, VoletIntervals, VoletPoids } from "./reglages/Volets";

interface Props {
  profil: Profil;
  zones: Zones;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
  surRefaireInstallation: () => void;
  /** Appelée une fois `POST /sortir` fait — l'écran de connexion, rien de plus. */
  surDeconnexion: () => void;
}

export function Reglages({
  profil,
  zones,
  surProfil,
  surZones,
  surRefaireInstallation,
  surDeconnexion,
}: Props) {
  const [volet, setVolet] = useState<Volet>(null);
  const [poids, setPoids] = useState(String(profil.cycliste.masse_kg));
  const [prenom, setPrenom] = useState(profil.cycliste.prenom ?? "");
  const [nom, setNom] = useState(profil.cycliste.nom ?? "");
  const [cle, setCle] = useState("");
  const [panne, setPanne] = useState<string | null>(null);
  const [dit, setDit] = useState<string | null>(null);
  // Enregistrement de la clé intervals.icu : message et état affichés juste
  // sous le bouton de ce volet, pas en haut de l'écran — le serveur vérifie
  // la clé auprès d'intervals.icu avant d'enregistrer, ça prend une ou deux
  // secondes, et sur téléphone un message en haut passe inaperçu.
  const [panneIntervals, setPanneIntervals] = useState<string | null>(null);
  const [ditIntervals, setDitIntervals] = useState<string | null>(null);
  const [verificationIntervals, setVerificationIntervals] = useState(false);
  // Ce que le serveur sait de la calibration de chaque vélo. `null` tant
  // qu'il n'a pas répondu — ou s'il ne sait pas répondre (un serveur plus
  // ancien) : la section ne s'affiche alors simplement pas.
  const [calibrations, setCalibrations] = useState<EtatCalibrations | null>(null);

  function relireCalibrations() {
    api
      .etatCalibrations()
      .then((reponse) => setCalibrations(reponse.donnees))
      .catch(() => setCalibrations(null));
  }

  useEffect(relireCalibrations, [profil]);

  async function enregistrer(sections: Record<string, unknown>, phrase: string) {
    setPanne(null);
    setDit(null);
    try {
      const reponse = await api.modifierProfil(sections);
      surProfil(reponse.donnees);
      const fraiches = await api.zones();
      surZones(fraiches.donnees);
      setDit(phrase);
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    }
  }

  function basculer(cible: Exclude<Volet, null>) {
    setVolet(volet === cible ? null : cible);
    setDit(null);
    setPanne(null);
    setDitIntervals(null);
    setPanneIntervals(null);
  }

  async function enregistrerIntervals() {
    setPanneIntervals(null);
    setDitIntervals(null);
    setVerificationIntervals(true);
    try {
      const reponse = await api.modifierProfil({ intervals: { api_key: cle } });
      surProfil(reponse.donnees);
      const fraiches = await api.zones();
      surZones(fraiches.donnees);
      setDitIntervals("Clé vérifiée auprès d'intervals.icu : c'est branché.");
      setCle("");
    } catch (erreur) {
      setPanneIntervals(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setVerificationIntervals(false);
    }
  }

  const liees = zones.valeurs_liees;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">Votre profil</span>
          <h1>Réglages</h1>
        </div>
      </div>

      {dit ? <div className="encart bien">{dit}</div> : null}
      {panne ? <div className="encart alerte">{panne}</div> : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">Identité</span>
          <button
            type="button"
            className="val lien texte"
            onClick={() => basculer("identite")}
            aria-expanded={volet === "identite"}
          >
            {profil.cycliste.prenom || profil.cycliste.nom
              ? `${profil.cycliste.prenom} ${profil.cycliste.nom}`.trim()
              : "à renseigner"}
          </button>
        </div>
      </div>

      {volet === "identite" ? (
        <VoletIdentite
          prenom={prenom}
          nom={nom}
          surPrenom={setPrenom}
          surNom={setNom}
          enregistrer={enregistrer}
        />
      ) : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">FTP</span>
          <button
            type="button"
            className="val lien"
            onClick={() => basculer("ftp")}
            aria-expanded={volet === "ftp"}
          >
            {/* Facultative depuis ce lot. Le bouton reste — c'est par lui qu'on
                la renseigne — mais il n'annonce pas une valeur qui n'existe pas. */}
            {zones.ftp_w === null ? "à renseigner" : `${nombre(zones.ftp_w)} W`}
          </button>
        </div>
        <div className="rangee">
          <span className="cle">Poids</span>
          <button
            type="button"
            className="val lien"
            onClick={() => basculer("poids")}
            aria-expanded={volet === "poids"}
          >
            {nombre(profil.cycliste.masse_kg, 1)} kg
          </button>
        </div>
        <div className="rangee">
          <span className="cle">Allure d'endurance</span>
          <span className="val">
            {liees
              ? `${nombre(liees.puissance_endurance_w)} W · ${pourcentage(liees.position_zone)} de la Z${zones.zone_endurance}`
              : "aucun vélo"}
          </span>
        </div>
      </div>

      {volet === "ftp" ? (
        <VoletFtp zones={zones} surZones={surZones} enregistrer={enregistrer} />
      ) : null}

      {volet === "poids" ? (
        <VoletPoids poids={poids} surPoids={setPoids} enregistrer={enregistrer} />
      ) : null}

      <RangeesDepartVelos
        profil={profil}
        calibrations={calibrations}
        volet={volet}
        basculer={basculer}
      />

      {volet === "depart" ? (
        <div className="bloc">
          <FormulaireAdresse
            valeurActuelle={profil.depart.nom}
            libelleConfirmation="C'est bien là, enregistrer ce départ"
            aide="Vous pourrez partir d'ailleurs à chaque sortie. Celui-ci n'est que le défaut."
            surChoix={(depart: DepartChoisi) =>
              enregistrer({ depart }, "Départ enregistré.")
            }
          />
        </div>
      ) : null}

      {volet === "velos" ? (
        <ListeVelos
          profil={profil}
          surListe={(velos) => enregistrer({ velos }, "Vélos enregistrés.")}
        />
      ) : null}

      {calibrations && calibrations.velos.length > 0 ? (
        <SectionCalibrations
          calibrations={calibrations}
          surChoisirPneus={() => {
            setVolet("velos");
            setDit(null);
            setPanne(null);
          }}
          surRelire={relireCalibrations}
          surZones={surZones}
        />
      ) : null}

      <RangeesServices profil={profil} volet={volet} basculer={basculer} />

      {volet === "intervals" ? (
        <VoletIntervals
          cle={cle}
          surCle={setCle}
          verification={verificationIntervals}
          dit={ditIntervals}
          panne={panneIntervals}
          surEnregistrer={enregistrerIntervals}
        />
      ) : null}

      <RangeesCompte
        volet={volet}
        basculer={basculer}
        surRefaireInstallation={surRefaireInstallation}
        surDeconnexion={surDeconnexion}
      />

      {volet === "compte" ? (
        <MonCompteVolet surCompteSupprime={surDeconnexion} />
      ) : null}
    </section>
  );
}

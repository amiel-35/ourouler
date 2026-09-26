/** T3 à T5 et le récapitulatif : la FTP, déclarée ou déduite, puis ce qui en découle. */

import type { Profil, Zones } from "../../api/types";
import { masseVeloAffichee, nombre, pourcentage, usageDeVelo } from "../../api/formats";
import { EcranFtp } from "../../composants/EcranFtp";
import { CHOIX_TERRAIN, CHOIX_VITESSE, PHRASE_CONFIANCE } from "./arbre";
import type { Etage } from "./arbre";
import type { EtatAssistant } from "./useAssistant";

export function EtapeT3({
  a,
  zones,
  surZones,
}: {
  a: EtatAssistant;
  zones: Zones;
  surZones: (zones: Zones) => void;
}) {
  const { enregistrer, setEtage, aller } = a;
  return (
    /* « Connaissez-vous votre FTP ? » se répond par oui ou par non, et les
       deux réponses tiennent dans le même regard. « Je ne sais pas » tout en
       bas, après les zones et l'allure d'endurance, viendrait après deux
       écrans de conséquences d'une FTP, servies à celui qui vient de dire
       qu'il n'en a pas. Il passe donc sous le champ, par `echappatoire`. */
    <EcranFtp
      zones={zones}
      surApercu={surZones}
      surFtp={async (ftp) => {
        const bon = await enregistrer({ cycliste: { ftp_w: ftp } });
        if (bon) {
          setEtage("ftp_declare");
          aller("recap");
        }
      }}
      echappatoire={
        <button type="button" className="bouton second" onClick={() => aller("t4_vitesse")}>
          Je ne sais pas
        </button>
      }
    />
  );
}

export function EtapeT4Vitesse({ a }: { a: EtatAssistant }) {
  const { vitesseKmh, setVitesseKmh, enCours, appelFiletLitterature, aller } = a;
  return (
    <div className="champ" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {CHOIX_VITESSE.map((choix) => (
        <button
          type="button"
          key={choix.libelle}
          className="bouton second"
          aria-pressed={vitesseKmh === choix.vitesse_kmh}
          disabled={enCours}
          onClick={() => {
            if (choix.vitesse_kmh === null) {
              appelFiletLitterature();
              return;
            }
            setVitesseKmh(choix.vitesse_kmh);
            aller("t4_terrain");
          }}
        >
          {choix.libelle}
        </button>
      ))}
    </div>
  );
}

export function EtapeT4Terrain({ a }: { a: EtatAssistant }) {
  const { enCours, choisirTerrain } = a;
  return (
    <div className="champ" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {CHOIX_TERRAIN.map((choix) => (
        <button
          type="button"
          key={choix.libelle}
          className="bouton second"
          disabled={enCours}
          onClick={() => choisirTerrain(choix.denivele_m_par_km)}
        >
          {choix.libelle}
        </button>
      ))}
    </div>
  );
}

export function EtapeRecap({
  etage,
  profil,
  zones,
  surFin,
}: {
  etage: Etage;
  profil: Profil;
  zones: Zones;
  surFin: () => void;
}) {
  const liees = zones.valeurs_liees;
  return (
    <>
      <div className="bloc doux" style={{ padding: "4px 14px" }}>
        <div className="rangee">
          <span className="cle">Identité</span>
          <span className="val texte">
            {profil.cycliste.prenom} {profil.cycliste.nom}
          </span>
        </div>
        <div className="rangee">
          <span className="cle">FTP</span>
          <span className="val">{nombre(zones.ftp_w ?? 0)} W</span>
        </div>
        <div className="rangee">
          <span className="cle">Poids</span>
          <span className="val">{nombre(profil.cycliste.masse_kg, 1)} kg</span>
        </div>
        <div className="rangee">
          <span className="cle">Départ</span>
          <span className="val texte">{profil.depart.nom}</span>
        </div>
        {profil.velos.map((velo) => (
          <div className="rangee" key={velo.nom}>
            <span className="cle">{velo.nom}</span>
            <span className="val texte">
              {usageDeVelo(velo.usage)} · {masseVeloAffichee(velo.masse_kg)}
            </span>
          </div>
        ))}
        <div className="rangee">
          <span className="cle">intervals.icu</span>
          <span className="val texte">
            {profil.services.intervals.renseigne ? "branché" : "pas branché"}
          </span>
        </div>
      </div>
      {etage ? <p className="mention" style={{ marginTop: 8 }}>{PHRASE_CONFIANCE[etage]}</p> : null}
      {liees ? (
        <div className="encart info">
          <b>
            En endurance vous viserez {nombre(liees.puissance_endurance_w)} W, soit{" "}
            {pourcentage(liees.puissance_endurance_pct)} de votre FTP.
          </b>{" "}
          Sur le plat, sans vent, ça fait {nombre(liees.vitesse_a_plat_kmh, 1)} km/h, et
          votre compteur devrait afficher {nombre(liees.moyenne_compteur_kmh, 1)} km/h de
          moyenne — avec un facteur{" "}
          {liees.facteur_mesure ? "mesuré sur vos sorties" : "supposé, faute de mesure"}.
        </div>
      ) : null}
      <button type="button" className="bouton" onClick={surFin}>
        Terminer
      </button>
    </>
  );
}

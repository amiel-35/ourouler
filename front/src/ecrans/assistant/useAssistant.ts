/** L'état de l'assistant et ses enregistrements.
 *
 * Tout l'état vit ici, pas dans les écrans d'étape : « Revenir en arrière »
 * doit retrouver chaque étape telle qu'on l'a laissée (la clé collée, le
 * profil Intervals retrouvé, l'export choisi), ce qu'un état local à l'étape
 * perdrait dès qu'elle quitte l'écran.
 */

import { useState } from "react";
import { api, ErreurApi } from "../../api/client";
import type { CategoriePneu, Profil, Zones } from "../../api/types";
import { ftpAffichee } from "../../composants/EcranFtp";
import type { Etage, Etape } from "./arbre";

interface Entrees {
  profil: Profil;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
}

export function useAssistant({ profil, surProfil, surZones }: Entrees) {
  const [etape, setEtapeSeule] = useState<Etape>("bienvenue");
  const [historique, setHistorique] = useState<Etape[]>([]);
  const [panne, setPanne] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);

  const [prenom, setPrenom] = useState(profil.cycliste.prenom ?? "");
  const [nom, setNom] = useState(profil.cycliste.nom ?? "");
  const [poids, setPoids] = useState(String(profil.cycliste.masse_kg));
  const [poidsConnu, setPoidsConnu] = useState(false);
  const [nomVelo, setNomVelo] = useState(profil.velos[0]?.nom ?? "");
  const [usageVelo, setUsageVelo] = useState(profil.velos[0]?.usage ?? "route");
  // Vide tant qu'aucun poids réel n'est connu — jamais `8` ni aucun autre
  // chiffre inventé côté front (constaté le 25/09/2026 : le texte d'aide
  // disait « on suppose 9 kg » pendant que le champ en préremplissait un
  // autre). Le `placeholder` montre `MASSE_VELO_DEFAUT_KG`, et un champ vide
  // part `null` : c'est le serveur, seul, qui applique le défaut.
  const [poidsVelo, setPoidsVelo] = useState(
    profil.velos[0]?.masse_kg != null ? String(profil.velos[0].masse_kg) : "",
  );
  const [pneu, setPneu] = useState<CategoriePneu | "">((profil.velos[0]?.pneu as CategoriePneu) ?? "");
  const [cle, setCle] = useState("");
  const [exportChoisi, setExportChoisi] = useState<string | null>(null);

  const [etage, setEtage] = useState<Etage>(null);
  const [intervalsTrouve, setIntervalsTrouve] = useState<{ ftp_w: number; masse_kg: number | null } | null>(
    null,
  );
  const [correctionIntervals, setCorrectionIntervals] = useState(false);
  const [ftpCorrigee, setFtpCorrigee] = useState("");
  const [masseCorrigee, setMasseCorrigee] = useState("");
  const [vitesseKmh, setVitesseKmh] = useState<number | null>(null);

  /** Avance dans l'arbre, en gardant de quoi revenir en arrière. */
  function aller(suivante: Etape) {
    setHistorique((h) => [...h, etape]);
    setPanne(null);
    setEtapeSeule(suivante);
  }

  function revenir() {
    setHistorique((h) => {
      if (h.length === 0) return h;
      const copie = [...h];
      const precedente = copie.pop()!;
      setPanne(null);
      setEtapeSeule(precedente);
      return copie;
    });
  }

  async function enregistrer(sections: Record<string, unknown>): Promise<boolean> {
    setPanne(null);
    try {
      const reponse = await api.modifierProfil(sections);
      surProfil(reponse.donnees);
      const fraiches = await api.zones();
      surZones(fraiches.donnees);
      return true;
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      return false;
    }
  }

  /** T1, une fois la clé Intervals enregistrée : lit le profil de l'athlète
   * et fait confirmer, ou descend directement à T2 si rien d'exploitable. */
  async function enregistrerCle() {
    setEnCours(true);
    try {
      const bon = await enregistrer({ intervals: { api_key: cle } });
      if (!bon) return;
      try {
        const reponse = await api.profilIntervals();
        if (reponse.donnees.ftp_w === null) {
          aller("t2");
          return;
        }
        setIntervalsTrouve({ ftp_w: reponse.donnees.ftp_w, masse_kg: reponse.donnees.masse_kg });
        setFtpCorrigee(ftpAffichee(reponse.donnees.ftp_w));
        setMasseCorrigee(reponse.donnees.masse_kg === null ? "" : String(reponse.donnees.masse_kg));
        setCorrectionIntervals(false);
        aller("t1_confirmation");
      } catch {
        // 409 `intervals_absent`, ou toute autre panne : traité comme
        // « rien trouvé », pas comme un échec à afficher en rouge.
        aller("t2");
      }
    } finally {
      setEnCours(false);
    }
  }

  /** « Oui » confirme tel quel, « je corrige » envoie les valeurs
   * corrigées — dans les deux cas, l'étage atteint est `intervals`. */
  async function confirmerIntervals() {
    if (!intervalsTrouve) return;
    setEnCours(true);
    try {
      const ftp = correctionIntervals ? Number(ftpCorrigee.replace(",", ".")) : intervalsTrouve.ftp_w;
      const masse =
        intervalsTrouve.masse_kg === null
          ? null
          : correctionIntervals
            ? Number(masseCorrigee.replace(",", "."))
            : intervalsTrouve.masse_kg;
      const cycliste: Record<string, number> = { ftp_w: ftp };
      if (masse !== null) cycliste.masse_kg = masse;
      const bon = await enregistrer({ cycliste });
      if (!bon) return;
      setEtage("intervals");
      if (masse !== null) setPoidsConnu(true);
      aller("velo");
    } finally {
      setEnCours(false);
    }
  }

  /** T4, seconde question : appelle l'aperçu vitesse+terrain et enregistre
   * la FTP rendue. « Je ne sais pas trop » tombe directement sur T5. */
  async function choisirTerrain(denivele_m_par_km: number | null) {
    if (denivele_m_par_km === null) {
      await appelFiletLitterature();
      return;
    }
    if (vitesseKmh === null) return;
    setEnCours(true);
    try {
      const reponse = await api.apercuFtpDepuisTerrain({
        vitesse_kmh: vitesseKmh,
        denivele_m_par_km,
        velo: nomVelo,
      });
      const bon = await enregistrer({ cycliste: { ftp_w: reponse.donnees.ftp_w } });
      if (!bon) return;
      setEtage(denivele_m_par_km === 30 ? "vitesse_terrain_montagne" : "vitesse_terrain");
      aller("recap");
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  /** T5, le fond du tunnel — silencieux, ne peut pas échouer côté serveur,
   * mais une panne réseau reste possible et s'affiche comme ailleurs. */
  async function appelFiletLitterature() {
    setEnCours(true);
    try {
      const reponse = await api.ftpGenerique(nomVelo);
      const bon = await enregistrer({ cycliste: { ftp_w: reponse.donnees.ftp_w } });
      if (!bon) return;
      setEtage("litterature");
      aller("recap");
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  return {
    etape,
    historique,
    panne,
    enCours,
    prenom,
    setPrenom,
    nom,
    setNom,
    poids,
    setPoids,
    poidsConnu,
    setPoidsConnu,
    nomVelo,
    setNomVelo,
    usageVelo,
    setUsageVelo,
    poidsVelo,
    setPoidsVelo,
    pneu,
    setPneu,
    cle,
    setCle,
    exportChoisi,
    setExportChoisi,
    etage,
    setEtage,
    intervalsTrouve,
    correctionIntervals,
    setCorrectionIntervals,
    ftpCorrigee,
    setFtpCorrigee,
    masseCorrigee,
    setMasseCorrigee,
    vitesseKmh,
    setVitesseKmh,
    aller,
    revenir,
    enregistrer,
    enregistrerCle,
    confirmerIntervals,
    choisirTerrain,
    appelFiletLitterature,
  };
}

export type EtatAssistant = ReturnType<typeof useAssistant>;

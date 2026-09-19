/** L'assistant d'accueil — un arbre, pas six étapes fixes.
 *
 * Réécrit le 19/09/2026 pour suivre `docs/ux/parcours_accueil.md` : l'ancien
 * assistant posait FTP puis poids puis vélo dans un ordre figé. Le nouveau
 * distingue deux axes indépendants — d'où viennent les sorties (Intervals >
 * export > rien), et si la FTP est connue — et descend un **entonnoir en
 * cinq étages** (T1 à T5, du plus précis au plus flou) qui saute les étages
 * inutiles dès qu'un chiffre exploitable est trouvé plus haut. C'est pour ça
 * que l'état n'est plus un simple index dans un tableau : `Etape` est une
 * union nommée, et chaque écran décide lui-même de la suivante.
 *
 * Le socle — identité, départ — reste en tête, dans un ordre humain qui ne
 * calcule rien (§5.1 du document) ; poids et vélo se posent juste avant la
 * première chose qui en a besoin dans l'entonnoir, pas en bloc figé.
 *
 * `etage` retient par quelle voie une FTP a fini par exister, uniquement
 * pour la phrase de confiance du récapitulatif (§9) — rien d'autre n'en
 * dépend.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Profil, Zones } from "../api/types";
import { nombre, pourcentage, usageDeVelo } from "../api/formats";
import { EcranFtp } from "../composants/EcranFtp";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";

type Etape =
  | "bienvenue"
  | "identite"
  | "depart"
  | "t1_question"
  | "t1_cle"
  | "t1_confirmation"
  | "t2"
  | "poids"
  | "velo"
  | "t3"
  | "t4_vitesse"
  | "t4_terrain"
  | "recap";

/** L'étage de l'entonnoir qui a fini par établir une FTP — pour la seule
 * phrase de confiance du récapitulatif (§9 du document). */
type Etage = "intervals" | "ftp_declare" | "vitesse_terrain" | "vitesse_terrain_montagne" | "litterature" | null;

const PHRASE_CONFIANCE: Record<Exclude<Etage, null>, string> = {
  intervals: "Estimation confirmée depuis votre profil Intervals.",
  ftp_declare: "Estimation à partir de la FTP que vous avez donnée.",
  vitesse_terrain: "Estimation à partir de ce que vous nous avez dit de vos sorties.",
  vitesse_terrain_montagne:
    "Estimation à partir de ce que vous nous avez dit — en montagne, cette estimation est moins fiable qu'ailleurs.",
  litterature: "Estimation générique, à partir de votre poids et de votre vélo seuls.",
};

const LIBELLES: Record<Etape, { rubrique: string; titre: string }> = {
  bienvenue: { rubrique: "Bienvenue", titre: "Bienvenue" },
  identite: { rubrique: "Votre identité", titre: "Comment vous appelez-vous ?" },
  depart: { rubrique: "Votre départ", titre: "D'où partez-vous ?" },
  t1_question: { rubrique: "intervals.icu", titre: "Avez-vous un compte intervals.icu ?" },
  t1_cle: { rubrique: "intervals.icu", titre: "Brancher intervals.icu" },
  t1_confirmation: { rubrique: "intervals.icu", titre: "On a retrouvé votre profil" },
  t2: { rubrique: "Export Strava ou Garmin", titre: "Pouvez-vous nous transmettre un export ?" },
  poids: { rubrique: "Votre poids", titre: "Votre poids" },
  velo: { rubrique: "Votre vélo", titre: "Avec quoi roulez-vous ?" },
  t3: { rubrique: "Votre puissance", titre: "Connaissez-vous votre FTP ?" },
  t4_vitesse: { rubrique: "Votre vécu", titre: "Votre vitesse au compteur" },
  t4_terrain: { rubrique: "Votre vécu", titre: "Et le terrain ?" },
  recap: { rubrique: "C'est prêt", titre: "Tout est en place" },
};

/** §5.2 — les tranches de vitesse font 2 km/h, mesuré. La valeur envoyée est
 * le milieu de la tranche ; les deux bornes ouvertes ont une valeur
 * représentative. `null` = « je ne sais pas trop », pas de valeur. */
const CHOIX_VITESSE: Array<{ libelle: string; vitesse_kmh: number | null }> = [
  { libelle: "Moins de 20 km/h", vitesse_kmh: 19 },
  { libelle: "20 à 22 km/h", vitesse_kmh: 21 },
  { libelle: "22 à 24 km/h", vitesse_kmh: 23 },
  { libelle: "24 à 26 km/h", vitesse_kmh: 25 },
  { libelle: "26 à 28 km/h", vitesse_kmh: 27 },
  { libelle: "28 à 30 km/h", vitesse_kmh: 29 },
  { libelle: "Plus de 30 km/h", vitesse_kmh: 31 },
  { libelle: "Je ne sais pas trop", vitesse_kmh: null },
];

/** §6 — le terrain choisit le dénivelé de référence de la conversion. La
 * case « Montagne » (30 m/km) dégrade la phrase de confiance du récap. */
const CHOIX_TERRAIN: Array<{ libelle: string; denivele_m_par_km: number | null }> = [
  { libelle: "Plat — moins de 250 m sur 50 km", denivele_m_par_km: 3 },
  { libelle: "Vallonné — 250 à 600 m sur 50 km", denivele_m_par_km: 10 },
  { libelle: "Ça grimpe — 600 à 1000 m sur 50 km", denivele_m_par_km: 18 },
  { libelle: "Montagne — plus de 1000 m sur 50 km", denivele_m_par_km: 30 },
  { libelle: "Je ne sais pas trop", denivele_m_par_km: null },
];

interface Props {
  profil: Profil;
  zones: Zones;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
  surFin: () => void;
}

export function Assistant({ profil, zones, surProfil, surZones, surFin }: Props) {
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
  const [poidsVelo, setPoidsVelo] = useState(String(profil.velos[0]?.masse_kg ?? 8));
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

  const liees = zones.valeurs_liees;

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
        setFtpCorrigee(String(reponse.donnees.ftp_w));
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

  const { rubrique, titre } = LIBELLES[etape];

  return (
    <section>
      <div className="etapes-assistant">{rubrique}</div>
      <div className="app-tete">
        <div>
          <span className="quand">{rubrique}</span>
          <h1>{titre}</h1>
        </div>
      </div>

      {panne ? <div className="encart alerte">{panne}</div> : null}

      {etape === "bienvenue" ? (
        <>
          <p className="mention" style={{ fontSize: 15, lineHeight: 1.5 }}>
            <b>Bienvenue sur ourouler.</b> Vous dites où et quand vous voulez rouler, ourouler
            regarde la météo dans toutes les directions et vous propose un parcours qui colle à
            votre séance — puis l'envoie sur votre compteur.
          </p>
          <p className="mention" style={{ fontSize: 15, lineHeight: 1.5, marginTop: 10, marginBottom: 16 }}>
            Pour ça, on a besoin de vous connaître un peu : votre poids, votre vélo, d'où vous
            partez, et une idée de votre niveau. On part de ce que vous avez de plus précis ; si
            vous n'avez rien, on s'en sort quand même. Quatre minutes, et vous pourrez toujours
            corriger plus tard.
          </p>
          <button type="button" className="bouton" onClick={() => aller("identite")}>
            Commencer
          </button>
        </>
      ) : null}

      {etape === "identite" ? (
        <>
          <div className="champ">
            <label htmlFor="cycliste-prenom">Prénom</label>
            <input
              className="saisie"
              id="cycliste-prenom"
              value={prenom}
              onChange={(e) => setPrenom(e.target.value)}
            />
          </div>
          <div className="champ">
            <label htmlFor="cycliste-nom">Nom</label>
            <input className="saisie" id="cycliste-nom" value={nom} onChange={(e) => setNom(e.target.value)} />
            <div className="aide">
              La base du compte. On ne vous demande pas votre âge : rien ne s'en sert
              aujourd'hui, ni dans le calcul ni ailleurs.
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            disabled={prenom.trim() === "" || nom.trim() === ""}
            onClick={async () => {
              const bon = await enregistrer({ cycliste: { prenom: prenom.trim(), nom: nom.trim() } });
              if (bon) aller("depart");
            }}
          >
            Continuer
          </button>
        </>
      ) : null}

      {etape === "depart" ? (
        <>
          <FormulaireAdresse
            valeurActuelle={profil.depart.nom}
            libelleConfirmation="C'est bien là, enregistrer ce départ"
            aide="Vous pourrez partir d'ailleurs à chaque sortie. Celui-ci n'est que le défaut."
            surChoix={async (depart: DepartChoisi) => {
              const bon = await enregistrer({ depart });
              if (bon) aller("t1_question");
            }}
          />
          <button type="button" className="bouton second" onClick={() => aller("t1_question")}>
            Garder ce départ
          </button>
        </>
      ) : null}

      {etape === "t1_question" ? (
        <div className="boutons">
          <button type="button" className="bouton second" onClick={() => aller("t2")}>
            Non, ou je ne sais pas
          </button>
          <button type="button" className="bouton" onClick={() => aller("t1_cle")}>
            Oui
          </button>
        </div>
      ) : null}

      {etape === "t1_cle" ? (
        <>
          <p className="mention" style={{ marginBottom: 16, fontSize: 13.5 }}>
            Si vous y planifiez vos séances, on les lit et on vous propose le parcours qui va
            avec. Sinon, vous déposerez un fichier de séance ou demanderez une boucle
            d'endurance — ça marche aussi.
          </p>
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>Où trouver votre clé</h2>
            </div>
            <div className="etapes">
              <div className="etape">
                <span className="km">1</span>
                <span className="nom">
                  <b>intervals.icu</b>
                  <small>Ouvrez vos réglages</small>
                </span>
                <a className="lien" href="https://intervals.icu/settings" target="_blank" rel="noreferrer">
                  Ouvrir ↗
                </a>
              </div>
              <div className="etape">
                <span className="km">2</span>
                <span className="nom">
                  <b>Tout en bas de la page</b>
                  <small>Section « Developer Settings »</small>
                </span>
                <span />
              </div>
              <div className="etape">
                <span className="km">3</span>
                <span className="nom">
                  <b>Copiez la clé</b>
                  <small>Une suite de lettres et de chiffres</small>
                </span>
                <span />
              </div>
            </div>
          </div>
          <div className="champ">
            <label htmlFor="cle">Votre clé</label>
            <input className="saisie mono" id="cle" value={cle} onChange={(e) => setCle(e.target.value)} />
            <div className="aide">
              Elle est affichée en clair : masquer un secret qu'on vient de coller empêche de
              le relire, et c'est comme ça qu'on colle un espace en trop sans le voir.
            </div>
          </div>
          {profil.services.intervals.renseigne ? (
            <div className="encart bien">
              <b>Une clé est déjà enregistrée.</b> Compte {profil.services.intervals.athlete_id}.
            </div>
          ) : null}
          <div className="boutons">
            <button type="button" className="bouton second" onClick={() => aller("t2")} disabled={enCours}>
              Plus tard
            </button>
            <button
              type="button"
              className="bouton"
              disabled={cle.trim() === "" || enCours}
              onClick={enregistrerCle}
            >
              Enregistrer
            </button>
          </div>
        </>
      ) : null}

      {etape === "t1_confirmation" && intervalsTrouve ? (
        <>
          <div className="encart info">
            On a trouvé dans votre profil Intervals : FTP {nombre(intervalsTrouve.ftp_w)} W
            {intervalsTrouve.masse_kg !== null ? `, poids ${nombre(intervalsTrouve.masse_kg, 1)} kg` : ""}.
            C'est toujours d'actualité ?
          </div>
          {!correctionIntervals ? (
            <div className="boutons">
              <button
                type="button"
                className="bouton second"
                onClick={() => setCorrectionIntervals(true)}
                disabled={enCours}
              >
                Je corrige
              </button>
              <button type="button" className="bouton" onClick={confirmerIntervals} disabled={enCours}>
                Oui
              </button>
            </div>
          ) : (
            <>
              <div className="champ">
                <label htmlFor="ftp-corrigee">FTP</label>
                <div className="saisie-unite">
                  <input
                    className="saisie mono"
                    id="ftp-corrigee"
                    inputMode="decimal"
                    value={ftpCorrigee}
                    onChange={(e) => setFtpCorrigee(e.target.value)}
                  />
                  <span className="unite">W</span>
                </div>
              </div>
              {intervalsTrouve.masse_kg !== null ? (
                <div className="champ">
                  <label htmlFor="masse-corrigee">Poids</label>
                  <div className="saisie-unite">
                    <input
                      className="saisie mono"
                      id="masse-corrigee"
                      inputMode="decimal"
                      value={masseCorrigee}
                      onChange={(e) => setMasseCorrigee(e.target.value)}
                    />
                    <span className="unite">kg</span>
                  </div>
                </div>
              ) : null}
              <button type="button" className="bouton" onClick={confirmerIntervals} disabled={enCours}>
                Continuer
              </button>
            </>
          )}
        </>
      ) : null}

      {etape === "t2" ? (
        <>
          <div className="segments">
            {["Strava", "Garmin", "Non"].map((choix) => (
              <button
                type="button"
                key={choix}
                aria-pressed={exportChoisi === choix}
                onClick={() => setExportChoisi(choix)}
              >
                {choix}
              </button>
            ))}
          </div>
          <div className="encart attention">
            L'import d'un export Strava ou Garmin n'est pas encore proposé par ourouler.
          </div>
          <button type="button" className="bouton" onClick={() => aller(poidsConnu ? "velo" : "poids")}>
            Continuer
          </button>
        </>
      ) : null}

      {etape === "poids" ? (
        <>
          <div className="champ">
            <label htmlFor="poids-cycliste">Votre poids</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="poids-cycliste"
                inputMode="decimal"
                value={poids}
                onChange={(e) => setPoids(e.target.value)}
              />
              <span className="unite">kg</span>
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            onClick={async () => {
              const bon = await enregistrer({
                cycliste: { masse_kg: Number(poids.replace(",", ".")) },
                seance: { position_zone: zones.position_zone },
              });
              if (bon) {
                setPoidsConnu(true);
                aller("velo");
              }
            }}
          >
            Continuer
          </button>
        </>
      ) : null}

      {etape === "velo" ? (
        <>
          <div className="champ">
            <label htmlFor="usage">Type</label>
            <div className="segments" id="usage" style={{ marginBottom: 0 }}>
              {[
                ["route", "Route"],
                ["clm", "Chrono"],
              ].map(([valeur, nom]) => (
                <button
                  type="button"
                  key={valeur}
                  aria-pressed={usageVelo === valeur}
                  onClick={() => setUsageVelo(valeur)}
                >
                  {nom}
                </button>
              ))}
            </div>
            <div className="aide">
              Le type fixe votre position sur le vélo, donc la prise au vent : un chrono
              avance plus vite à puissance égale, et souffre moins de face.
            </div>
          </div>
          <div className="champ">
            <label htmlFor="velo-nom">Nom</label>
            <input
              className="saisie"
              id="velo-nom"
              value={nomVelo}
              onChange={(e) => setNomVelo(e.target.value)}
            />
            <div className="aide">Pour le reconnaître quand vous en aurez deux.</div>
          </div>
          <div className="champ">
            <label htmlFor="velo-poids">Poids du vélo</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="velo-poids"
                inputMode="decimal"
                value={poidsVelo}
                onChange={(e) => setPoidsVelo(e.target.value)}
              />
              <span className="unite">kg</span>
            </div>
            <div className="aide">Facultatif — sans chiffre, on suppose 9 kg.</div>
          </div>
          <button
            type="button"
            className="bouton"
            disabled={nomVelo.trim() === ""}
            onClick={async () => {
              const autres = profil.velos.slice(1).map((v) => v as unknown as object);
              const premier = {
                ...((profil.velos[0] ?? {}) as unknown as object),
                nom: nomVelo,
                usage: usageVelo,
                masse_kg: Number(poidsVelo.replace(",", ".")),
              };
              const bon = await enregistrer({ velos: [premier, ...autres] });
              // Une FTP déjà confirmée par Intervals (T1) saute T3 à T5 en
              // entier : le vélo était la seule chose qui lui manquait.
              if (bon) aller(etage === "intervals" ? "recap" : "t3");
            }}
          >
            Continuer
          </button>
        </>
      ) : null}

      {etape === "t3" ? (
        <>
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
          />
          <button type="button" className="bouton second" onClick={() => aller("t4_vitesse")}>
            Je ne sais pas
          </button>
        </>
      ) : null}

      {etape === "t4_vitesse" ? (
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
      ) : null}

      {etape === "t4_terrain" ? (
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
      ) : null}

      {etape === "recap" ? (
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
                  {usageDeVelo(velo.usage)} · {nombre(velo.masse_kg, 1)} kg
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
      ) : null}

      {historique.length > 0 && etape !== "recap" ? (
        <button type="button" className="bouton fantome" onClick={revenir}>
          Revenir en arrière
        </button>
      ) : null}
    </section>
  );
}

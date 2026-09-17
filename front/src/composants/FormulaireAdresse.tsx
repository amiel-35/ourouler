/** D'où l'on part — **des champs séparés, une carte, et la position du téléphone**.
 *
 * Remplace la ligne de texte libre, et c'est la décision du mainteneur sur
 * Q34, le 17/09/2026 : « on refuse. Et on peut faire contrôler la position en
 * affichant un point, voire proposer la géoloc sur mobile. S'il faut, en V1,
 * on fait un formulaire à champs obligatoires. »
 *
 * **Ce que la mesure dit, et pourquoi la forme est celle-là.** Quinze requêtes
 * sur la vraie BAN (17/09/2026, lieux publics uniquement) : une adresse sans
 * commune rend cinq candidats séparés de 0,0016 à 0,0024 de score, dans cinq
 * communes distinctes jusqu'à 400 km d'écart — le premier est arbitraire. Les
 * neuf adresses complètes rendent toutes une seule commune. La commune n'est
 * donc pas un champ de confort, c'est ce qui fait la différence entre une
 * réponse et un tirage au sort. Elle est demandée à part pour qu'on ne puisse
 * pas l'oublier.
 *
 * **Trois chemins, et jamais un seul.** Le formulaire marche partout. La
 * position du navigateur n'est proposée qu'en plus : elle exige HTTPS (ou
 * localhost), une autorisation que l'utilisateur peut refuser, et elle peut
 * échouer ou traîner. Un refus d'autorisation **n'est pas une erreur** — c'est
 * un choix, et il s'affiche comme tel. La confirmation sur la carte est le
 * troisième : un géocodage qui se trompe de commune est indétectable dans un
 * champ texte et visible en une seconde sur un point.
 *
 * **Ce qui manque, et qu'on ne fabrique pas** : l'API ne fait pas de géocodage
 * inverse. Une position relevée par le navigateur est donc une *coordonnée*,
 * pas une adresse — elle s'affiche comme telle, en chiffres, et on ne lui
 * invente pas un nom de rue.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Candidat } from "../api/types";
import { nombre } from "../api/formats";
import { Carte } from "./Carte";

/** Ce que ce formulaire rend une fois le point confirmé. */
export interface DepartChoisi {
  nom: string;
  latitude: number;
  longitude: number;
}

interface Props {
  /** Le départ déjà enregistré, montré en repère. */
  valeurActuelle?: string;
  surChoix: (depart: DepartChoisi) => void | Promise<void>;
  /** Le mot du bouton final. « Partir d'ici » sur E16, « Enregistrer » ailleurs. */
  libelleConfirmation?: string;
  /** La phrase sous les champs — chaque écran a son contexte. */
  aide?: string;
}

interface Champs {
  numero: string;
  voie: string;
  codePostal: string;
  commune: string;
}

const VIDES: Champs = { numero: "", voie: "", codePostal: "", commune: "" };

const LIBELLES: Record<keyof Champs, string> = {
  numero: "Numéro",
  voie: "Voie",
  codePostal: "Code postal",
  commune: "Commune",
};

/** Le point à confirmer : soit un candidat du géocodeur, soit la position du navigateur. */
type Apercu =
  | { genre: "candidat"; candidat: Candidat }
  | { genre: "position"; latitude: number; longitude: number; precision_m: number | null };

/** La géolocalisation est-elle seulement possible ici, et sinon pourquoi ?
 *
 * Trois pièges, et ils se traitent, ils ne se contournent pas : le navigateur
 * ne donne la position que sur HTTPS (ou en local), il faut une autorisation
 * explicite, et l'appel peut échouer. Le premier se voit avant de cliquer —
 * autant le dire plutôt que d'offrir un bouton qui ne marchera jamais.
 */
export function etatGeolocalisation(): { possible: boolean; raison: string | null } {
  if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
    return { possible: false, raison: "Ce navigateur ne donne pas la position." };
  }
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    return {
      possible: false,
      raison: "La position demande une connexion sécurisée (HTTPS) — le formulaire, non.",
    };
  }
  return { possible: true, raison: null };
}

/** Ce qu'on dit à l'utilisateur quand la position n'est pas venue.
 *
 * Le refus d'autorisation est séparé du reste **exprès** : c'est un choix, pas
 * une panne, et le formulaire fait la même chose.
 */
export function phraseEchecPosition(code: number): string {
  if (code === 1) {
    return "Position non partagée — c'est votre choix. Les champs ci-dessous font la même chose.";
  }
  if (code === 3) {
    return "La position met trop de temps à venir. Les champs ci-dessous restent disponibles.";
  }
  return "La position n'a pas pu être relevée. Les champs ci-dessous restent disponibles.";
}

/** L'adresse envoyée au géocodeur, à partir des quatre champs. */
export function requete(champs: Champs): string {
  return [champs.numero, champs.voie, champs.codePostal, champs.commune]
    .map((v) => v.trim())
    .filter((v) => v !== "")
    .join(" ");
}

/** Les champs restés vides. Tous sont obligatoires : c'est le fond de la décision. */
export function champsManquants(champs: Champs): (keyof Champs)[] {
  return (Object.keys(VIDES) as (keyof Champs)[]).filter((clef) => champs[clef].trim() === "");
}

function nomDuPoint(apercu: Apercu): string {
  if (apercu.genre === "candidat") return apercu.candidat.label;
  // Pas de géocodage inverse dans l'API : on ne connaît que des chiffres, on
  // n'invente pas un nom de rue par-dessus.
  return `Ma position (${apercu.latitude.toFixed(5)}, ${apercu.longitude.toFixed(5)})`;
}

function coordonneesDu(apercu: Apercu): { latitude: number; longitude: number } {
  if (apercu.genre === "candidat") {
    return { latitude: apercu.candidat.latitude, longitude: apercu.candidat.longitude };
  }
  return { latitude: apercu.latitude, longitude: apercu.longitude };
}

/** Où est ce candidat, en une ligne — la commune d'abord, c'est elle qui distingue. */
export function ouEst(candidat: Candidat): string {
  if (!candidat.commune) return "commune inconnue";
  return candidat.code_postal ? `${candidat.commune} (${candidat.code_postal})` : candidat.commune;
}

export function FormulaireAdresse({
  valeurActuelle,
  surChoix,
  libelleConfirmation = "C'est bien là, partir d'ici",
  aide,
}: Props) {
  const [champs, setChamps] = useState<Champs>(VIDES);
  const [manquants, setManquants] = useState<(keyof Champs)[]>([]);
  const [candidats, setCandidats] = useState<Candidat[] | null>(null);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [phrase, setPhrase] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [positionEnCours, setPositionEnCours] = useState(false);

  const geoloc = etatGeolocalisation();

  function changer(clef: keyof Champs, valeur: string) {
    setChamps({ ...champs, [clef]: valeur });
    setManquants(manquants.filter((m) => m !== clef));
  }

  async function chercher() {
    const vides = champsManquants(champs);
    if (vides.length > 0) {
      setManquants(vides);
      setPhrase(
        "Les quatre champs sont demandés : sans la commune, le géocodeur rend jusqu'à cinq " +
          "adresses identiques à des centaines de kilomètres, et la première est prise au hasard.",
      );
      return;
    }
    setEnCours(true);
    setPhrase(null);
    setApercu(null);
    try {
      const reponse = await api.geocodage(requete(champs));
      setCandidats(reponse.donnees.candidats);
      if (reponse.donnees.candidats.length === 0) {
        setPhrase(reponse.avertissements[0] ?? "Aucune adresse trouvée.");
      } else if (reponse.donnees.candidats.length === 1) {
        // Un seul candidat : il reste à confirmer sur la carte, mais on évite
        // une liste d'un seul élément.
        setApercu({ genre: "candidat", candidat: reponse.donnees.candidats[0] });
      }
    } catch (erreur) {
      setCandidats(null);
      setPhrase(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnCours(false);
    }
  }

  function demanderPosition() {
    if (!geoloc.possible) return;
    setPositionEnCours(true);
    setPhrase(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setPositionEnCours(false);
        setCandidats(null);
        setApercu({
          genre: "position",
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          precision_m: Number.isFinite(position.coords.accuracy)
            ? position.coords.accuracy
            : null,
        });
      },
      (erreur) => {
        setPositionEnCours(false);
        setPhrase(phraseEchecPosition(erreur.code));
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  return (
    <div>
      {geoloc.possible ? (
        <button
          type="button"
          className="bouton second"
          onClick={demanderPosition}
          disabled={positionEnCours}
        >
          {positionEnCours ? "On demande votre position…" : "Utiliser ma position"}
        </button>
      ) : (
        <p className="mention">{geoloc.raison}</p>
      )}

      <fieldset className="champs-adresse">
        <legend>Adresse de départ</legend>
        <p className="mention">
          Quatre champs plutôt qu'une ligne : sans la commune, la même rue existe dans des
          dizaines de communes et rien ne permet de choisir la bonne.
        </p>
        {(Object.keys(VIDES) as (keyof Champs)[]).map((clef) => (
          <div className="champ" key={clef}>
            <label htmlFor={`adresse-${clef}`}>{LIBELLES[clef]}</label>
            <input
              className="saisie"
              id={`adresse-${clef}`}
              value={champs[clef]}
              required
              aria-invalid={manquants.includes(clef)}
              inputMode={clef === "codePostal" || clef === "numero" ? "numeric" : "text"}
              autoComplete={
                { numero: "off", voie: "address-line1", codePostal: "postal-code", commune: "address-level2" }[
                  clef
                ]
              }
              onChange={(e) => changer(clef, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") chercher();
              }}
            />
          </div>
        ))}
        {aide ? <div className="aide">{aide}</div> : null}
        {valeurActuelle ? <p className="mention">Départ actuel : {valeurActuelle}.</p> : null}
        <button type="button" className="bouton second" onClick={chercher} disabled={enCours}>
          {enCours ? "Recherche…" : "Chercher cette adresse"}
        </button>
      </fieldset>

      {phrase ? <p className="mention">{phrase}</p> : null}

      {candidats && candidats.length > 1 ? (
        <ul className="liste-candidats">
          {candidats.map((candidat) => (
            <li key={`${candidat.latitude},${candidat.longitude}`}>
              <button
                type="button"
                onClick={() => setApercu({ genre: "candidat", candidat })}
              >
                {candidat.label}
                <span className="mention">
                  {" "}
                  · {ouEst(candidat)} · {candidat.source} · confiance{" "}
                  {nombre(candidat.score * 100)} / 100
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {apercu ? (
        <div className="bloc doux">
          <p className="mention">
            {apercu.genre === "candidat"
              ? `Vérifiez le point avant de partir : ${ouEst(apercu.candidat)}.`
              : "Le point relevé par votre navigateur. Sans nom d'adresse : ourouler ne fait pas " +
                "de géocodage inverse, il n'en connaît que les coordonnées."}
          </p>
          <Carte
            traces={[]}
            depart={{ ...coordonneesDu(apercu), nom: nomDuPoint(apercu) }}
            zoomPoint={16}
            description={`Le point de départ à confirmer : ${nomDuPoint(apercu)}`}
          />
          {apercu.genre === "position" && apercu.precision_m !== null ? (
            <p className="mention">Précision annoncée : environ {nombre(apercu.precision_m)} m.</p>
          ) : null}
          <div className="boutons">
            <button
              type="button"
              className="bouton"
              onClick={() => surChoix({ nom: nomDuPoint(apercu), ...coordonneesDu(apercu) })}
            >
              {libelleConfirmation}
            </button>
            <button type="button" className="bouton fantome" onClick={() => setApercu(null)}>
              Ce n'est pas là
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** D'où l'on part — **des champs séparés, une carte, et la position du téléphone**.
 *
 * Pas de ligne de texte libre : une adresse ambiguë se refuse, la position se
 * fait contrôler en affichant un point, la géolocalisation est proposée sur
 * mobile, et le formulaire a des champs obligatoires (décision Q34,
 * `docs/journal/questions/questions_mainteneur.md`).
 *
 * **Ce que la mesure dit, et pourquoi la forme est celle-là.** Quinze requêtes
 * sur la vraie BAN (lieux publics uniquement) : une adresse sans
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
 * **Le point confirmé vient au lecteur.** Il s'affiche sous les quatre champs
 * — c'est sa place pour un géocodage, dont il est le résultat — mais le bouton
 * de position est tout en haut, et sur un téléphone la carte naît alors hors
 * de l'écran : on a cliqué, rien n'a bougé, on croit que ça a raté. Le bloc se fait donc défiler jusqu'à lui
 * quand il apparaît, quel que soit le chemin qui l'a produit.
 *
 * **Ce qui manque, et qu'on ne fabrique pas** : l'API ne fait pas de géocodage
 * inverse. Une position relevée par le navigateur est donc une *coordonnée*,
 * pas une adresse — elle s'affiche comme telle, en chiffres, et on ne lui
 * invente pas un nom de rue.
 *
 * Les champs, le point à confirmer et la géolocalisation, sans état, sont
 * dans `adresse/champs.ts`.
 */

import { useEffect, useRef, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Candidat } from "../api/types";
import { nombre, sourceDAdresse } from "../api/formats";
import { Carte } from "./Carte";
import {
  champsManquants,
  coordonneesDu,
  etatGeolocalisation,
  LIBELLES,
  nomDuPoint,
  OBLIGATOIRES,
  ouEst,
  phraseEchecPosition,
  requete,
  VIDES,
} from "./adresse/champs";
import type { Apercu, Champs, DepartChoisi } from "./adresse/champs";

export {
  champsManquants,
  etatGeolocalisation,
  ouEst,
  phraseEchecPosition,
  requete,
} from "./adresse/champs";
export type { DepartChoisi } from "./adresse/champs";

interface Props {
  /** Le départ déjà enregistré, montré en repère. */
  valeurActuelle?: string;
  surChoix: (depart: DepartChoisi) => void | Promise<void>;
  /** Le mot du bouton final. « Partir d'ici » sur E16, « Enregistrer » ailleurs. */
  libelleConfirmation?: string;
  /** La phrase sous les champs — chaque écran a son contexte. */
  aide?: string;
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
  const blocApercu = useRef<HTMLDivElement>(null);

  // Le point apparaît sous les champs, alors que le bouton de position est en
  // haut : sans ce défilement, un téléphone ne montre rien de neuf et le clic
  // passe pour un échec. `scrollIntoView` n'existe pas partout (jsdom ne
  // l'implémente pas) — son absence n'est pas une panne, juste un écran qui
  // ne bouge pas.
  useEffect(() => {
    const bloc = blocApercu.current;
    if (!bloc || typeof bloc.scrollIntoView !== "function") return;
    bloc.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [apercu]);

  function changer(clef: keyof Champs, valeur: string) {
    setChamps({ ...champs, [clef]: valeur });
    setManquants(manquants.filter((m) => m !== clef));
  }

  async function chercher() {
    const vides = champsManquants(champs);
    if (vides.length > 0) {
      setManquants(vides);
      setPhrase(
        "La voie, le code postal et la commune sont demandés : sans eux, le géocodeur rend " +
          "jusqu'à cinq adresses identiques à des centaines de kilomètres, et la première est " +
          "prise au hasard.",
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
        // `avertissements` porte `{code, message}` : le front ne lit jamais
        // une phrase française pour décider d'un état.
        setPhrase(reponse.avertissements[0]?.message ?? "Aucune adresse trouvée.");
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
          dizaines de communes et rien ne permet de choisir la bonne. Le numéro est
          facultatif — une place ou un lieu-dit n'en a pas.
        </p>
        {(Object.keys(VIDES) as (keyof Champs)[]).map((clef) => (
          <div className="champ" key={clef}>
            <label htmlFor={`adresse-${clef}`}>{LIBELLES[clef]}</label>
            <input
              className="saisie"
              id={`adresse-${clef}`}
              value={champs[clef]}
              required={OBLIGATOIRES.includes(clef)}
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
                  {/* « ban » était le nom du service, et le « score » était
                      présenté comme une confiance sur 100 : le cœur écrit
                      qu'il n'est comparable qu'entre candidats de la même
                      source (`connecteurs/geocodage.py`), or les deux
                      sources se mélangent dans cette liste. Une échelle
                      commune sur deux grandeurs différentes fait choisir sur
                      un chiffre qui ne veut rien dire ; la commune, elle,
                      distingue vraiment. */}· {ouEst(candidat)} ·{" "}
                  {sourceDAdresse(candidat.source)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {apercu ? (
        <div className="bloc doux" ref={blocApercu}>
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

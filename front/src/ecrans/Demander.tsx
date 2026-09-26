/** E16 — demander un parcours. L'organisation de l'information suit Strava.
 *
 * « Le résultat est en haut, les réglages en dessous, et le résultat bouge
 * quand on touche un réglage. » On ne remplit pas un formulaire pour
 * découvrir la réponse à la fin, on négocie avec un chiffre qu'on a sous les
 * yeux.
 *
 * Ce qui bouge en direct est **l'estimation**, pas le tracé : une boucle
 * coûte plusieurs appels de calcul et environ 150 appels météo, ça ne se
 * recalcule pas à chaque frappe.
 *
 * Et l'estimation ne s'invente pas. Elle est la **moyenne compteur du modèle
 * physique** — celle que rend `/profil/zones` — multipliée par la durée. Le
 * même écran dit si le facteur de cette moyenne est mesuré ou supposé : la
 * maquette laissait cette réserve ouverte (« pour quelqu'un qui vient
 * d'arriver, le modèle tourne sur ses valeurs par défaut, et l'écran ne le
 * dit pas encore »), ici elle est refermée.
 *
 * Les fonctions pures de la demande sont dans `demander/demande.ts`, le
 * chargement du vent et de la météo dans `demander/useMeteoDepart.ts`, les
 * champs de direction dans `demander/ChampsDirection.tsx`.
 */

import { useEffect, useState } from "react";
import type { Budget, Profil, Zones } from "../api/types";
import { phraseBudget } from "../composants/Attente";
import { duree, heureDeRetour, nombre } from "../api/formats";
import { aujourdhui } from "../etat/ressource";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";
import { ChoixDirection, PointCardinal, PreferenceVent } from "./demander/ChampsDirection";
import { minutesDe, texteDuree } from "./demander/demande";
import type { Demande } from "./demander/demande";
import { Estimation } from "./demander/Estimation";
import { useMeteoDepart } from "./demander/useMeteoDepart";

export { demandeInitiale, minutesDe, phraseEstimation, texteDuree } from "./demander/demande";
export type { Demande } from "./demander/demande";

interface Props {
  profil: Profil;
  zones: Zones;
  /** La durée de la séance du jour, quand il y en a une. */
  dureeSeance_s: number | null;
  nomSeance: string | null;
  demande: Demande;
  /**
   * Ce que la recherche va coûter en attente, **avant de la lancer** (C3).
   *
   * Décision 6 du cycle UX : « semi-synchrone, en précisant que ça prend X
   * secondes », et « X doit être mesuré, pas inventé ». Le budget était déjà
   * chargé au démarrage, mais il n'apparaissait qu'une fois l'attente
   * commencée : le cycliste apprenait le prix au moment où il le payait.
   */
  budget: Budget | null;
  surDemande: (demande: Demande) => void;
  surChercher: () => void;
}

export function Demander({
  profil,
  zones,
  dureeSeance_s,
  nomSeance,
  demande,
  budget,
  surDemande,
  surChercher,
}: Props) {
  const [texte, setTexte] = useState(texteDuree(demande.duree_min));
  // « Partir d'ailleurs » est replié par défaut : le formulaire à quatre champs
  // et sa carte prennent de la place, et la plupart des sorties partent du
  // départ habituel.
  const [ailleurs, setAilleurs] = useState(false);
  const { vent, erreurVent, meteo, erreurMeteo } = useMeteoDepart(demande.jour, demande.heure_depart);

  const liees = zones.valeurs_liees;
  const minutes =
    demande.mode === "seance" && dureeSeance_s !== null
      ? Math.round(dureeSeance_s / 60)
      : demande.duree_min;
  const distanceEstimee =
    liees === null ? null : (liees.moyenne_compteur_kmh * minutes) / 60;
  const departIso = `${demande.jour}T${demande.heure_depart}:00`;
  const retour = heureDeRetour(departIso, minutes * 60);

  function changer(morceau: Partial<Demande>) {
    surDemande({ ...demande, ...morceau });
  }

  // Le vent qu'on ne sait pas prévoir ne se propose pas comme orientation :
  // si le mode « selon le vent » était choisi et que la question cesse
  // d'être posée (jour changé, météo indisponible…), on revient à « peu
  // importe » plutôt que de laisser un mode actif sans azimut à proposer.
  useEffect(() => {
    if (vent !== null && !vent.donnees.posee && demande.modeDirection === "vent") {
      changer({ modeDirection: "peu-importe" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vent]);

  // « Selon le vent » n'existe pas pour la boucle libre (Endurance Z2) —
  // `POST /boucles` n'a pas de champ `vent` (voir `chercher` dans `App.tsx`).
  // Un mode qui bascule en z2 pendant qu'il était actif retombe sur « peu
  // importe » plutôt que de laisser un choix qui n'aboutira jamais.
  useEffect(() => {
    if (demande.mode === "z2" && demande.modeDirection === "vent") {
      changer({ modeDirection: "peu-importe" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demande.mode]);

  const jours = [0, 1, 2].map((decalage) => {
    const quand = new Date(`${aujourdhui()}T12:00:00`);
    quand.setDate(quand.getDate() + decalage);
    return quand.toISOString().slice(0, 10);
  });

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">Demander</span>
          <h1>Un parcours</h1>
        </div>
      </div>

      <Estimation distanceEstimee={distanceEstimee} liees={liees} minutes={minutes} retour={retour} />

      <div className="champ">
        <label htmlFor="quoi">Ce que vous faites</label>
        <div className="segments colle" id="quoi">
          <button
            type="button"
            aria-pressed={demande.mode === "seance"}
            onClick={() => changer({ mode: "seance" })}
          >
            Ma séance
          </button>
          <button
            type="button"
            aria-pressed={demande.mode === "z2"}
            onClick={() => changer({ mode: "z2" })}
          >
            Endurance Z2
          </button>
        </div>
        {demande.mode === "seance" ? (
          <div className="aide">
            {nomSeance
              ? `${nomSeance} — ${duree(dureeSeance_s ?? 0)}. C'est la séance qui fixe la durée.`
              : "Aucune séance ce jour-là. Choisissez un autre jour, déposez un fichier, ou passez en endurance."}
          </div>
        ) : null}
      </div>

      {demande.mode === "z2" ? (
        <div className="champ">
          <label htmlFor="duree">Durée</label>
          <div className="saisie-unite">
            <input
              className="saisie mono"
              id="duree"
              inputMode="numeric"
              value={texte}
              onChange={(e) => {
                setTexte(e.target.value);
                const lues = minutesDe(e.target.value);
                if (lues !== null && lues > 0) changer({ duree_min: lues });
              }}
            />
            <span className="unite">h:min</span>
          </div>
        </div>
      ) : null}

      <div className="champ">
        <label htmlFor="quand">Quand</label>
        <div className="segments colle" id="quand">
          {jours.map((jour, index) => (
            <button
              type="button"
              key={jour}
              aria-pressed={demande.jour === jour}
              onClick={() => changer({ jour })}
            >
              {["Aujourd'hui", "Demain", "Après-demain"][index]}
            </button>
          ))}
        </div>
        <div className="aide">
          <label htmlFor="heure-depart">Départ à </label>
          <input
            id="heure-depart"
            type="time"
            value={demande.heure_depart}
            onChange={(e) => changer({ heure_depart: e.target.value })}
            style={{ font: "inherit", border: "none", background: "none", color: "inherit" }}
          />
        </div>
      </div>

      {/* Le premier choix de Q44, indépendant de `mode` : un seul des deux
          sélecteurs suivants s'affiche, la contradiction disparaît par la
          forme. Et le vent s'affiche dans les deux modes — ce n'est pas une
          alternative à ce choix, c'est son complément (Q44). */}
      <ChoixDirection
        demande={demande}
        changer={changer}
        vent={vent}
        erreurVent={erreurVent}
        profil={profil}
      />

      {demande.modeDirection === "direction" ? (
        <PointCardinal demande={demande} changer={changer} meteo={meteo} erreurMeteo={erreurMeteo} />
      ) : null}

      {demande.modeDirection === "vent" ? (
        <PreferenceVent demande={demande} changer={changer} vent={vent} />
      ) : null}
      <div className="champ">
        <label htmlFor="depart">Départ</label>
        <input
          className="saisie"
          id="depart"
          value={demande.depart?.nom ?? profil.depart.nom}
          readOnly
        />
        {demande.depart ? (
          <button type="button" className="lien" onClick={() => changer({ depart: null })}>
            Revenir à mon départ habituel
          </button>
        ) : null}
        <button
          type="button"
          className="lien"
          aria-expanded={ailleurs}
          onClick={() => setAilleurs(!ailleurs)}
        >
          {ailleurs ? "· Annuler" : "· Partir d'ailleurs cette fois"}
        </button>
      </div>

      {ailleurs ? (
        <FormulaireAdresse
          libelleConfirmation="Partir d'ici cette fois"
          aide="Ce départ ne vaut que pour cette sortie — votre départ habituel ne bouge pas."
          surChoix={(depart: DepartChoisi) => {
            changer({ depart });
            setAilleurs(false);
          }}
        />
      ) : null}

      <button
        type="button"
        className="bouton"
        onClick={surChercher}
        // Q47 : `boucle` balaie tout l'horizon sans direction, comme
        // `sortie` — « peu importe » n'est plus un blocage en Endurance Z2,
        // c'est une demande valable que le moteur sait désormais traiter.
        disabled={demande.mode === "seance" && dureeSeance_s === null}
      >
        Chercher {nombre(demande.candidates)} parcours
      </button>
      <p className="mention centre">{phraseBudget(budget)}</p>
    </section>
  );
}

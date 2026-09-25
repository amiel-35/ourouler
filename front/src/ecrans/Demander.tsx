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
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type {
  AzimutVent,
  Budget,
  Enveloppe,
  Meteo,
  Profil,
  ValeursLiees,
  VentDepart,
  Zones,
} from "../api/types";
import { phraseBudget } from "../composants/Attente";
import { directionsDepuisCellules } from "../api/meteoRose";
import { RoseDirections, LegendeRose } from "../composants/RoseDirections";
import {
  duree,
  heureDeRetour,
  nombre,
  VENT_PREFERENCE_EN_TOUTES_LETTRES,
  ventDepuisAvecPreposition,
} from "../api/formats";
import { aujourdhui } from "../etat/ressource";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";

/** Les trois préférences de « selon le vent », dans l'ordre où Q44 les pose. */
const PREFERENCES_VENT = ["depart-dos", "retour-dos", "travers"];

export interface Demande {
  mode: "seance" | "z2";
  jour: string;
  heure_depart: string;
  duree_min: number;
  /**
   * Le **premier choix** de Q44 : indépendant de `mode`, il décide lequel
   * des deux sélecteurs suivants s'affiche — jamais les deux à la fois, pour
   * que la contradiction entre eux disparaisse par la forme.
   */
  modeDirection: "peu-importe" | "direction" | "vent";
  vent: string;
  direction: string;
  depart: { latitude: number; longitude: number; nom: string } | null;
  candidates: number;
}

export function demandeInitiale(): Demande {
  return {
    mode: "seance",
    jour: aujourdhui(),
    heure_depart: "09:00",
    duree_min: 120,
    modeDirection: "peu-importe",
    vent: "peu-importe",
    direction: "N",
    depart: null,
    candidates: 3,
  };
}

/** `2:00` → 120 minutes. `90` → 90 minutes. Rien de lisible → `null`. */
export function minutesDe(texte: string): number | null {
  const propre = texte.trim().replace(",", ":").replace("h", ":");
  if (propre.includes(":")) {
    const [h, m] = propre.split(":");
    const heures = Number(h);
    const minutes = Number(m || "0");
    if (!Number.isFinite(heures) || !Number.isFinite(minutes)) return null;
    return Math.round(heures * 60 + minutes);
  }
  const brut = Number(propre);
  return Number.isFinite(brut) && brut > 0 ? Math.round(brut) : null;
}

export function texteDuree(minutes: number): string {
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/**
 * La phrase sous « Ce que ça donnera » (backlog « la phrase sur la vitesse »,
 * note du mainteneur du 20/09/2026 : « c'est débile, faut faire plus simple »
 * devant l'ancien paragraphe — chiffre de moyenne compteur et jargon « modèle
 * physique littérature » compris). Décision du 25/09/2026 (« fais 8 ») :
 * formulation A, la plus courte des deux proposées, sans chiffre ni jargon.
 *
 * Mesuré = le facteur de compteur est mesuré sur l'historique, ou le vélo est
 * calibré (`modele_physique === "calibration"` — la calibration mesure aussi
 * bien la vitesse que la puissance, donc l'un ou l'autre suffit à dire
 * « mesuré »). Sinon, l'estimation ne repose que sur le profil déclaré et les
 * caractéristiques du vélo — jamais mesurées.
 *
 * La provenance détaillée (le facteur, le modèle physique, chiffre par
 * chiffre) reste ailleurs, dans Réglages, sous le dépliant « D'où viennent
 * ces deux chiffres » — la règle de provenance de la doctrine ne bouge pas,
 * c'est seulement cette phrase-ci qui se simplifie.
 */
export function phraseEstimation(liees: ValeursLiees): string {
  const mesure = liees.facteur_mesure || liees.modele_physique === "calibration";
  return mesure
    ? "Estimation d'après vos sorties."
    : "Estimation d'après votre profil et votre vélo.";
}

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
  // D'où vient le vent au départ (Q44) — chargé pendant que le cycliste
  // choisit, affiché dans les deux modes, jamais recalculé ici.
  const [vent, setVent] = useState<Enveloppe<VentDepart> | null>(null);
  const [erreurVent, setErreurVent] = useState<string | null>(null);
  // La rose des huit directions (pluie cumulée, vent, désaccord entre
  // modèles) : remplace « Là où il fait sec », qui ne faisait qu'un seul de
  // ces trois appels à `/meteo` pour ne montrer que le nom d'une direction.
  const [meteo, setMeteo] = useState<Enveloppe<Meteo> | null>(null);
  const [erreurMeteo, setErreurMeteo] = useState<string | null>(null);

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

  // Rechargé quand le jour ou l'heure de départ changent — c'est ce qui
  // décide de l'azimut, pas le mode ni le reste de la demande.
  useEffect(() => {
    let annule = false;
    setVent(null);
    setErreurVent(null);
    api
      .ventDepart({ jour: demande.jour, heure_depart: `${demande.jour}T${demande.heure_depart}:00` })
      .then((reponse) => {
        if (!annule) setVent(reponse);
      })
      .catch((erreur) => {
        if (!annule) setErreurVent(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      });
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demande.jour, demande.heure_depart]);

  // La rose : même déclenchement que le vent au départ ci-dessus (jour et
  // heure de départ décident de la fenêtre interrogée), chargée qu'on soit
  // ou non sur « Ma direction » — pour qu'elle soit déjà prête au premier
  // clic sur ce mode, sans reflash.
  useEffect(() => {
    let annule = false;
    setMeteo(null);
    setErreurMeteo(null);
    api
      .meteo({ heure_depart: departIso })
      .then((reponse) => {
        if (!annule) setMeteo(reponse);
      })
      .catch((erreur) => {
        if (!annule) setErreurMeteo(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      });
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demande.jour, demande.heure_depart]);

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

  /** La phrase du vent, ou pourquoi il n'y en a pas — jamais un vent inventé. */
  function phraseVent(): string {
    if (erreurVent !== null) return erreurVent;
    if (vent === null) return "Vent : en cours…";
    const donnees = vent.donnees;
    if (!donnees.posee) return donnees.motif ?? "Le vent n'est pas connu pour ce départ.";
    if (donnees.vent_depuis_nom === null || donnees.vent_kmh === null) {
      return "Le vent n'est pas connu pour ce départ.";
    }
    return `Vent ${ventDepuisAvecPreposition(donnees.vent_depuis_nom)} à ${nombre(
      donnees.vent_kmh,
      0,
    )} km/h`;
  }

  /** L'azimut (ou les deux, pour le latéral) qu'une préférence imposerait. */
  function azimutsTexte(items: AzimutVent[]): string {
    if (items.length === 0) return "azimut non communiqué";
    return items.map((a) => `${a.nom} (${nombre(a.azimut_deg, 0)}°)`).join(" et ");
  }

  const jours = [0, 1, 2].map((decalage) => {
    const quand = new Date(`${aujourdhui()}T12:00:00`);
    quand.setDate(quand.getDate() + decalage);
    return quand.toISOString().slice(0, 10);
  });

  // La rose : une ligne par direction, agrégée depuis les cellules brutes de
  // `/meteo` (`meteoRose.directionsDepuisCellules`, documenté là-bas —
  // jamais un second calcul ici).
  const directionsMeteo = meteo ? directionsDepuisCellules(meteo.donnees.cellules) : [];
  const directionRecommandee = meteo?.donnees.meilleure_direction?.nom ?? null;
  const motifRecommandation = meteo?.donnees.meilleure_direction?.motif ?? null;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">Demander</span>
          <h1>Un parcours</h1>
        </div>
      </div>

      <div className="bloc choisi hero">
        <div className="bloc-tete">
          <h2>Ce que ça donnera</h2>
          <span className="rang">Estimation</span>
        </div>
        <div className="estimation-duo">
          <div>
            <div className="grand">
              {distanceEstimee === null ? "—" : nombre(distanceEstimee, 0)}
              <small>km</small>
            </div>
            <p className="mention">
              {liees === null
                ? "aucun vélo : rien à estimer"
                : `à ${nombre(liees.puissance_endurance_w)} W en endurance`}
            </p>
          </div>
          <div>
            <div className="grand">{duree(minutes * 60)}</div>
            <p className="mention">{retour ? `retour vers ${retour}` : "heure à préciser"}</p>
          </div>
        </div>
        {liees ? <p className="mention">{phraseEstimation(liees)}</p> : null}
      </div>

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
      <div className="champ">
        <label htmlFor="mode-direction">Direction</label>
        <div className="segments colle" id="mode-direction">
          <button
            type="button"
            aria-pressed={demande.modeDirection === "peu-importe"}
            onClick={() => changer({ modeDirection: "peu-importe" })}
          >
            Peu importe
          </button>
          <button
            type="button"
            aria-pressed={demande.modeDirection === "direction"}
            onClick={() => changer({ modeDirection: "direction" })}
          >
            Ma direction
          </button>
          <button
            type="button"
            aria-pressed={demande.modeDirection === "vent"}
            disabled={demande.mode === "z2" || (vent !== null && !vent.donnees.posee)}
            onClick={() =>
              changer({
                modeDirection: "vent",
                vent: demande.vent === "peu-importe" ? "depart-dos" : demande.vent,
              })
            }
          >
            Selon le vent
          </button>
        </div>
        {demande.mode === "z2" ? (
          <div className="aide">
            L'orientation au vent n'est pas encore disponible pour une sortie libre (Endurance
            Z2) — le moteur de boucle libre ne pose pas encore cette question.
          </div>
        ) : null}
        <div className="aide">{phraseVent()}</div>
      </div>

      {demande.modeDirection === "direction" ? (
        <div className="champ">
          {/* « Direction » se lisait deux fois : une fois pour le choix du
              mode (ci-dessus), une fois pour l'azimut qui en dépend —
              signalé le 18/09/2026. Ce champ-ci choisit un point cardinal,
              pas une seconde fois « la » direction.

              Choisir à l'aveugle était la question ouverte que ce lot ferme
              (20/09/2026) : huit boutons de texte devenaient huit secteurs
              qui montrent la pluie cumulée, le vent et le désaccord entre
              modèles — ce que le produit savait déjà sans jamais le
              montrer avant de cliquer. `RoseDirections` reste un vrai
              contrôle clavier (Tab, puis Entrée ou Espace) : au moins
              aussi accessible que les huit boutons qu'elle remplace. */}
          <label>Point cardinal</label>
          {erreurMeteo !== null ? (
            <p className="mention">{erreurMeteo}</p>
          ) : meteo === null ? (
            <p className="mention">Météo des huit directions : en cours…</p>
          ) : (
            <>
              <div className="rose-conteneur">
                <RoseDirections
                  directions={directionsMeteo}
                  recommandee={directionRecommandee}
                  choisie={demande.direction}
                  onChoisir={(nom) => changer({ direction: nom })}
                />
              </div>
              <LegendeRose />
              {motifRecommandation ? <p className="mention">{motifRecommandation}</p> : null}
            </>
          )}
        </div>
      ) : null}

      {demande.modeDirection === "vent" ? (
        <div className="champ">
          <label htmlFor="vent-preference">Selon le vent</label>
          <div className="segments colle enveloppe" id="vent-preference">
            {PREFERENCES_VENT.map((choix) => (
              <button
                type="button"
                key={choix}
                aria-pressed={demande.vent === choix}
                onClick={() => changer({ vent: choix })}
              >
                {VENT_PREFERENCE_EN_TOUTES_LETTRES[choix]}
              </button>
            ))}
          </div>
          <div className="aide">
            Posée avant la recherche, elle réduit l'espace exploré au lieu de trier après coup.
          </div>
          {vent && vent.donnees.posee ? (
            <div>
              {PREFERENCES_VENT.map((choix) => (
                <p className="mention" key={choix}>
                  {VENT_PREFERENCE_EN_TOUTES_LETTRES[choix]} :{" "}
                  {azimutsTexte(vent.donnees.azimuts_par_choix[choix] ?? [])}
                </p>
              ))}
            </div>
          ) : null}
        </div>
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

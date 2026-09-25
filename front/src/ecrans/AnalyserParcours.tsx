/** L9.8 — analyser un parcours déjà en main.
 *
 * Le troisième usage de « Déposer » (`docs/plan_sprints_agents.md`, constat du
 * mainteneur du 25/09/2026) : « déposer c'est pas que ça, c'est aussi l'analyse
 * d'une trace existante pour y caler la météo, l'estimation, le vent etc. » —
 * l'imposé d'un BRM ou d'une Flèche, une boucle de club, pas un parcours que le
 * moteur cherche. Trois gestes : déposer le GPX, dire l'heure de départ (la
 * puissance a un défaut), lire la météo par tronçon et l'heure d'arrivée.
 *
 * **Rien de neuf pour l'affichage du résultat** : `Carte`, `LegendeVent` et
 * `ProfilAltitude` sont ceux de `Boucles.tsx` — `POST /parcours/analyser` rend
 * `trace`/`meteo` dans la même forme qu'une candidate de boucle (F0.1)
 * précisément pour ça.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Analyse, ApercuParcours } from "../api/types";
import { duree, entreDurees, heure, kmDepuisKm, nombre } from "../api/formats";
import { Carte, LegendeVent } from "../composants/Carte";
import { ProfilAltitude } from "../composants/ProfilAltitude";
import { BandeauMeteoAbsente, Echec, meteoManquante } from "../composants/Echec";
import { JaugePluie } from "../composants/JaugePluie";
import { RetourEnTete } from "../composants/Retour";

interface Props {
  vers: string;
  surRetour: () => void;
}

type Etape =
  | { nom: "depot" }
  | { nom: "pret"; fichierId: string; apercu: ApercuParcours }
  | { nom: "analyse"; fichierId: string; apercu: ApercuParcours; resultat: Analyse; avertissements: { code: string; message: string }[] };

export function AnalyserParcours({ vers, surRetour }: Props) {
  const [etape, setEtape] = useState<Etape>({ nom: "depot" });
  const [erreur, setErreur] = useState<ErreurApi | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [survole, setSurvole] = useState(false);
  const [heureDepart, setHeureDepart] = useState("");
  const [puissance, setPuissance] = useState("");

  async function deposer(fichier: File) {
    setEnCours(true);
    setErreur(null);
    try {
      const reponse = await api.deposerParcours(fichier);
      setEtape({ nom: "pret", fichierId: reponse.fichier.id, apercu: reponse.apercu });
    } catch (cause) {
      setErreur(cause instanceof ErreurApi ? cause : erreurInterne(cause));
    } finally {
      setEnCours(false);
    }
  }

  async function analyser() {
    if (etape.nom === "depot" || !heureDepart) return;
    setEnCours(true);
    setErreur(null);
    try {
      const reponse = await api.analyserParcours({
        gpx: etape.fichierId,
        heure_depart: heureDepart,
        puissance_w: puissance ? Number(puissance) : undefined,
      });
      setEtape({
        nom: "analyse",
        fichierId: etape.fichierId,
        apercu: etape.apercu,
        resultat: reponse.donnees,
        avertissements: reponse.avertissements,
      });
    } catch (cause) {
      setErreur(cause instanceof ErreurApi ? cause : erreurInterne(cause));
    } finally {
      setEnCours(false);
    }
  }

  const resultat = etape.nom === "analyse" ? etape.resultat : null;
  const manque = etape.nom === "analyse" ? meteoManquante(etape.avertissements) : null;

  return (
    <section>
      <RetourEnTete vers={vers} surRetour={surRetour} />
      <div className="app-tete">
        <div>
          <span className="quand">Sans Intervals · un parcours déjà en main</span>
          <h1>Analyser un parcours</h1>
        </div>
      </div>
      <p className="mention">
        L'imposé d'un brevet, d'une Flèche, la boucle du club — pas un parcours à chercher.
        Déposez le GPX, dites l'heure de départ : la météo par tronçon et la durée porte à
        porte en fourchette.
      </p>

      {etape.nom === "depot" ? (
        <div
          className={survole ? "depot survole" : "depot"}
          onDragOver={(e) => {
            e.preventDefault();
            setSurvole(true);
          }}
          onDragLeave={() => setSurvole(false)}
          onDrop={(e) => {
            e.preventDefault();
            setSurvole(false);
            const fichier = e.dataTransfer.files[0];
            if (fichier) deposer(fichier);
          }}
        >
          <div className="grosse">Déposez le GPX du parcours</div>
          <p className="mention">l'imposé reçu par courriel, ou exporté de votre club</p>
          <input
            type="file"
            accept=".gpx,.GPX"
            aria-label="Parcours à analyser"
            style={{ display: "none" }}
            id="depot-parcours"
            onChange={(e) => {
              const fichier = e.target.files?.[0];
              if (fichier) deposer(fichier);
            }}
          />
          <button
            type="button"
            className="bouton second mt-depot"
            onClick={() => document.getElementById("depot-parcours")?.click()}
            disabled={enCours}
          >
            {enCours ? "Lecture…" : "Choisir un fichier"}
          </button>
          <div className="fmt">.GPX</div>
        </div>
      ) : null}

      {erreur ? <Echec erreur={erreur} contexte="Analyse d'un parcours" /> : null}

      {etape.nom !== "depot" ? (
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>{etape.apercu.nom}</h2>
            <span className="rang">Compris</span>
          </div>
          <p className="mention">
            {kmDepuisKm(etape.apercu.distance_km)}
            {etape.apercu.denivele_m !== null ? `, ${nombre(etape.apercu.denivele_m)} m D+` : ""}
          </p>
          <label>
            Heure de départ
            <input
              type="datetime-local"
              value={heureDepart}
              onChange={(e) => setHeureDepart(e.target.value)}
            />
          </label>
          <label>
            Puissance (W) — vide : celle de votre endurance
            <input
              type="number"
              inputMode="numeric"
              placeholder="défaut : puissance d'endurance"
              value={puissance}
              onChange={(e) => setPuissance(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="bouton"
            onClick={analyser}
            disabled={enCours || !heureDepart}
          >
            {enCours ? "Analyse…" : "Analyser"}
          </button>
        </div>
      ) : null}

      {resultat ? (
        <>
          {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

          <Carte
            traces={[{ points: resultat.trace.points, choisi: true, titre: resultat.nom }]}
            vents={resultat.meteo?.fleches_vent ?? []}
            haute
            description={`Le parcours « ${resultat.nom} »`}
          />
          <LegendeVent vents={resultat.meteo?.fleches_vent ?? []} />
          <ProfilAltitude profil={resultat.trace.profil} />

          <div className="bloc choisi">
            <div className="chiffres">
              <span>
                <b>{entreDurees(resultat.temps_ecoule_bas_s, resultat.temps_ecoule_haut_s)}</b> porte à
                porte
              </span>
              <span className="second-chiffre">{duree(resultat.temps_estime_s)} sans un seul arrêt</span>
            </div>
            <p className="mention">
              {resultat.temps_ecoule_source === "mesure"
                ? "Fourchette mesurée sur vos sorties."
                : "Fourchette par convention (pas encore assez de vos sorties)."}{" "}
              Arrivée estimée entre {heure(resultat.heure_arrivee_bas)} et{" "}
              {heure(resultat.heure_arrivee_haut)}.
            </p>
            <p className="mention">Puissance tenue : {nombre(resultat.puissance_w)} W.</p>
            {resultat.meteo ? (
              <JaugePluie
                mm={resultat.meteo.pluie_cumulee_mm ?? 0}
                minutesPluie={null}
              />
            ) : null}
          </div>
        </>
      ) : null}
    </section>
  );
}

function erreurInterne(cause: unknown): ErreurApi {
  return new ErreurApi({ code: "erreur_interne", message: String(cause), service: null, details: {} }, 0);
}

/** E17 — déposer une séance.
 *
 * L'écran ne se contente pas d'accepter le fichier : **il montre ce qu'il a
 * compris dedans**, dans le même vocabulaire que partout ailleurs. C'est le
 * seul moyen de voir qu'un fichier a été mal lu avant de partir rouler avec.
 *
 * Et il dit la conversion : un `.ZWO` ne porte que des pourcentages, les
 * watts affichés dépendent de la FTP. Quelqu'un qui voit 220 W là où il
 * attendait 250 vient d'apprendre que sa FTP est mal renseignée.
 *
 * Le `.FIT` n'est pas lu en V1, et **son absence se dit ici** plutôt que de
 * se découvrir au moment du dépôt (décision 5).
 */

import { useRef, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Seance } from "../api/types";
import { duree, jourEnLettres, nombre } from "../api/formats";
import { Etapes } from "../composants/Etapes";
import { Echec } from "../composants/Echec";
import { RetourEnTete } from "../composants/Retour";
import { DepotHistorique } from "../composants/DepotHistorique";

interface Props {
  jour: string;
  surSeanceLue: (seance: Seance, identifiant: string) => void;
  surChercher: () => void;
  /** Le troisième usage de cet écran — un parcours déjà en main, à
   * analyser plutôt qu'à chercher. */
  surAnalyser: () => void;
  /** D'où l'écran a été ouvert (Aujourd'hui, Ma semaine…) — jamais « Retour » seul. */
  vers: string;
  surRetour: () => void;
}

export function Importer({ jour, surSeanceLue, surChercher, surAnalyser, vers, surRetour }: Props) {
  const [seance, setSeance] = useState<Seance | null>(null);
  const [erreur, setErreur] = useState<ErreurApi | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [survole, setSurvole] = useState(false);
  const champ = useRef<HTMLInputElement | null>(null);

  async function deposer(fichier: File) {
    setEnCours(true);
    setErreur(null);
    try {
      const reponse = await api.deposerSeance(fichier, jour);
      setSeance(reponse.donnees);
      surSeanceLue(reponse.donnees, reponse.fichier.id);
    } catch (cause) {
      setSeance(null);
      setErreur(
        cause instanceof ErreurApi
          ? cause
          : new ErreurApi(
              { code: "erreur_interne", message: String(cause), service: null, details: {} },
              0,
            ),
      );
    } finally {
      setEnCours(false);
    }
  }

  return (
    <section>
      {/* Une sortie de cet écran, pour que le retour arrière du navigateur ne
          soit pas la seule issue. Même geste que `Proposition` : le composant existant, en
          tête, nommé. */}
      <RetourEnTete vers={vers} surRetour={surRetour} />
      <div className="app-tete">
        <div>
          {/* **Pour quel jour** — le dépôt en prend un, et le placement ne
              vaudra que pour lui : autant que l'écran le dise avant. */}
          <span className="quand">Sans Intervals · {jourEnLettres(jour)}</span>
          <h1>Déposer une séance</h1>
        </div>
      </div>

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
        <div className="grosse">Déposez votre fichier</div>
        <p className="mention">ou choisissez-le sur votre téléphone</p>
        <input
          ref={champ}
          type="file"
          accept=".zwo,.mrc,.ZWO,.MRC"
          aria-label="Fichier de séance"
          style={{ display: "none" }}
          onChange={(e) => {
            const fichier = e.target.files?.[0];
            if (fichier) deposer(fichier);
          }}
        />
        <button
          type="button"
          className="bouton second mt-depot"
          onClick={() => champ.current?.click()}
          disabled={enCours}
        >
          {enCours ? "Lecture…" : "Choisir un fichier"}
        </button>
        <div className="fmt">.ZWO · .MRC</div>
        <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
          Le <b>.FIT</b> viendra plus tard — c'est le seul des trois qui soit un format
          binaire.
        </p>
      </div>

      {erreur ? <Echec erreur={erreur} contexte="Dépôt de séance" /> : null}

      {seance ? (
        <>
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>{seance.nom}</h2>
              <span className="rang">Compris</span>
            </div>
            <Etapes etapes={seance.etapes} />
            <p className="mention">
              {duree(seance.duree_s)} au total, {nombre(seance.n_blocs)} bloc
              {seance.n_blocs > 1 ? "s" : ""}. Les pourcentages sont convertis avec votre FTP
              de {nombre(seance.meta.ftp_w)} W.
            </p>
          </div>
          {seance.avertissements.map((phrase) => (
            <div className="encart attention" key={phrase}>
              {phrase}
            </div>
          ))}
          <button type="button" className="bouton" onClick={surChercher}>
            Chercher un parcours
          </button>
        </>
      ) : null}

      <DepotHistorique />

      {/* Le troisième usage de « Déposer » — un parcours qu'on a déjà
          (l'imposé d'un brevet, une boucle de club), à analyser plutôt qu'à
          chercher : y caler la météo, l'estimation et le vent. */}
      <section className="mt-depot">
        <div className="app-tete">
          <h2>Un parcours déjà en main</h2>
        </div>
        <p className="mention">
          L'imposé d'un brevet ou d'une Flèche, la boucle du club — pas un parcours à
          chercher : sa météo par tronçon et sa durée porte à porte.
        </p>
        <button type="button" className="bouton second" onClick={surAnalyser}>
          Analyser un parcours
        </button>
      </section>
    </section>
  );
}

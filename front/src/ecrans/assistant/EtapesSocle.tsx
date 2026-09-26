/** Le socle de l'assistant : bienvenue, identité, départ, puis la question T1. */

import type { Profil } from "../../api/types";
import { departEstReel } from "../../api/formats";
import { FormulaireAdresse } from "../../composants/FormulaireAdresse";
import type { DepartChoisi } from "../../composants/FormulaireAdresse";
import type { EtatAssistant } from "./useAssistant";

export function EtapeBienvenue({ a }: { a: EtatAssistant }) {
  const { aller } = a;
  return (
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
  );
}

export function EtapeIdentite({ a }: { a: EtatAssistant }) {
  const { prenom, setPrenom, nom, setNom, enregistrer, aller } = a;
  return (
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
  );
}

export function EtapeDepart({ a, profil }: { a: EtatAssistant; profil: Profil }) {
  const { enregistrer, aller } = a;
  return (
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
      {departEstReel(profil.depart) ? (
        <button type="button" className="bouton second" onClick={() => aller("t1_question")}>
          Garder ce départ
        </button>
      ) : null}
    </>
  );
}

export function EtapeT1Question({ a }: { a: EtatAssistant }) {
  const { aller } = a;
  return (
    <div className="boutons">
      <button type="button" className="bouton second" onClick={() => aller("t2")}>
        Non, ou je ne sais pas
      </button>
      <button type="button" className="bouton" onClick={() => aller("t1_cle")}>
        Oui
      </button>
    </div>
  );
}

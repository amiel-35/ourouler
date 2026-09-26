/** La liste des vélos du profil, modifiable en entier (volet « Vos vélos » des Réglages). */

import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Profil } from "../../api/types";
import { nombre, PNEUS } from "../../api/formats";

export function ListeVelos({
  profil,
  surListe,
}: {
  profil: Profil;
  surListe: (velos: Record<string, unknown>[]) => void;
}) {
  // La liste des vélos se **remplace en entier** (`api/depots.py`). On repart
  // donc du vélo tel que l'API l'a rendu et on ne remplace que les quatre
  // champs de l'écran : sinon un simple changement de nom effacerait le
  // rattachement Intervals, le capteur et le facteur de compteur mesuré.
  const [velos, setVelos] = useState(
    profil.velos.map((v) => ({
      origine: v as unknown as Record<string, unknown>,
      nom: v.nom,
      usage: v.usage,
      masse_kg: v.masse_kg === null ? "" : String(v.masse_kg),
      // Vide quand `null` : « rien saisi » n'est pas la même chose que
      // « zéro », et c'est le défaut serveur qui s'applique dans ce cas
      // (voir `defauts` ci-dessous).
      facteurCompteur: v.facteur_compteur === null ? "" : String(v.facteur_compteur),
      // Vide : aucun pneu déclaré, le Crr reste celui de l'usage (L9.1).
      pneu: v.pneu ?? "",
    })),
  );

  // Le défaut que le serveur appliquerait à un champ vide, par vélo
  // d'origine (`origine.nom`, jamais le nom en cours de saisie qui peut
  // changer sous nos pieds). `GET /profil/zones` ne le rend que pour un
  // vélo dont `facteur_compteur` vaut déjà `null` côté serveur — pour les
  // autres, le champ vide n'a pas encore de défaut à montrer tant que
  // l'enregistrement n'a pas eu lieu, et on le dit plutôt que d'inventer un
  // chiffre.
  const [defauts, setDefauts] = useState<Record<string, number>>({});

  useEffect(() => {
    let annule = false;
    const aRecuperer = profil.velos.filter((v) => v.facteur_compteur === null);
    Promise.all(
      aRecuperer.map((v) =>
        api
          .zones(v.nom)
          .then(
            (reponse) => [v.nom, reponse.donnees.valeurs_liees?.facteur_compteur ?? null] as const,
          )
          .catch(() => [v.nom, null] as const),
      ),
    ).then((paires) => {
      if (annule) return;
      const table: Record<string, number> = {};
      for (const [nom, valeur] of paires) if (valeur !== null) table[nom] = valeur;
      setDefauts(table);
    });
    return () => {
      annule = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function modifier(index: number, morceau: Partial<(typeof velos)[number]>) {
    setVelos(velos.map((velo, i) => (i === index ? { ...velo, ...morceau } : velo)));
  }

  return (
    <div className="bloc">
      {velos.map((velo, index) => (
        <div key={index} className="velo-ligne">
          <div className="champ">
            <label htmlFor={`velo-nom-${index}`}>Nom</label>
            <input
              className="saisie"
              id={`velo-nom-${index}`}
              value={velo.nom}
              onChange={(e) => modifier(index, { nom: e.target.value })}
            />
          </div>
          <div className="champ">
            <label htmlFor={`velo-usage-${index}`}>Usage</label>
            <select
              className="saisie"
              id={`velo-usage-${index}`}
              value={velo.usage}
              onChange={(e) => modifier(index, { usage: e.target.value })}
            >
              <option value="route">route</option>
              <option value="clm">chrono</option>
            </select>
          </div>
          <div className="champ">
            <label htmlFor={`velo-pneu-${index}`}>Pneus</label>
            <select
              className="saisie"
              id={`velo-pneu-${index}`}
              value={velo.pneu}
              onChange={(e) => modifier(index, { pneu: e.target.value })}
            >
              <option value="">Je ne sais pas</option>
              {PNEUS.map((p) => (
                <option key={p.cle} value={p.cle}>
                  {p.libelle}
                </option>
              ))}
            </select>
          </div>
          <div className="champ">
            <label htmlFor={`velo-poids-${index}`}>Poids du vélo</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id={`velo-poids-${index}`}
                inputMode="decimal"
                value={velo.masse_kg}
                onChange={(e) => modifier(index, { masse_kg: e.target.value })}
              />
              <span className="unite">kg</span>
            </div>
          </div>
          {(() => {
            const nomOrigine = typeof velo.origine.nom === "string" ? velo.origine.nom : null;
            const defaut = nomOrigine ? defauts[nomOrigine] : undefined;
            const vide = velo.facteurCompteur.trim() === "";
            return (
              <div className="champ">
                <label htmlFor={`velo-facteur-${index}`}>Facteur compteur</label>
                <input
                  className="saisie mono"
                  id={`velo-facteur-${index}`}
                  inputMode="decimal"
                  value={velo.facteurCompteur}
                  onChange={(e) => modifier(index, { facteurCompteur: e.target.value })}
                  placeholder={defaut !== undefined ? nombre(defaut, 3) : undefined}
                />
                {vide ? (
                  <div className="aide">
                    {defaut !== undefined ? (
                      <>
                        Vide : {nombre(defaut, 3)} s'applique —{" "}
                        <b>supposé — il n'a pas été mesuré sur vos sorties</b>.
                      </>
                    ) : (
                      "Vide : le défaut du serveur s'applique."
                    )}
                  </div>
                ) : (
                  <button
                    type="button"
                    className="lien"
                    onClick={() => modifier(index, { facteurCompteur: "" })}
                  >
                    Revenir au défaut
                  </button>
                )}
              </div>
            );
          })()}
          <button
            type="button"
            className="bouton fantome"
            onClick={() => setVelos(velos.filter((_, i) => i !== index))}
          >
            Retirer {velo.nom}
          </button>
        </div>
      ))}
      <p className="mention">
        Le facteur compteur est le rapport entre la vitesse à plat que prédit le modèle et
        votre moyenne compteur réelle, arrêts compris. C'est lui qui convertit « je veux rouler
        5 h » en kilomètres à chercher. La durée porte à porte des boucles, elle, part du
        temps calculé sur chaque parcours.
      </p>
      <button
        type="button"
        className="bouton second"
        // **Champ vide, pas un poids inventé** (C8). Un vélo neuf arrivait
        // avec « 8 » kg, qui ne vient d'aucune API et que personne n'a saisi ;
        // qui ne corrigeait pas le champ voyait toutes ses estimations de
        // distance calculées là-dessus, sans que rien le signale — alors même
        // que le facteur de compteur, lui, dit qu'il est supposé. Un champ
        // vide demande une réponse ; un champ prérempli fait passer un défaut
        // pour une saisie (règle absolue 5).
        onClick={() =>
          setVelos([
            ...velos,
            {
              origine: {},
              nom: "",
              usage: "route",
              masse_kg: "",
              facteurCompteur: "",
              pneu: "",
            },
          ])
        }
      >
        Ajouter un vélo
      </button>
      <button
        type="button"
        className="bouton"
        onClick={() =>
          surListe(
            velos.map((velo) => ({
              ...velo.origine,
              nom: velo.nom,
              usage: velo.usage,
              masse_kg: velo.masse_kg.trim() === "" ? null : Number(velo.masse_kg.replace(",", ".")),
              facteur_compteur:
                velo.facteurCompteur.trim() === ""
                  ? null
                  : Number(velo.facteurCompteur.replace(",", ".")),
              pneu: velo.pneu === "" ? null : velo.pneu,
            })),
          )
        }
      >
        Enregistrer les vélos
      </button>
      <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
        Le type fixe votre position sur le vélo, donc la prise au vent : un chrono avance plus
        vite à puissance égale, et souffre moins de face. Les pneus disent combien le vélo
        roule facilement : un pneu de course tubeless coûte moins d'effort qu'un pneu
        d'entraînement renforcé.
      </p>
    </div>
  );
}

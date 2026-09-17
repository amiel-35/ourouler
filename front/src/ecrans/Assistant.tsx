/** E8 · E9 · E10 · E11 · E12 — s'installer. Six étapes, et un récapitulatif.
 *
 * L'ordre n'est pas administratif : il va du **bloquant** — sans identité,
 * sans départ et sans FTP, rien ne tourne — vers le **reportable** :
 * Intervals peut se brancher un mois plus tard, et l'étape se saute.
 *
 * **L'étape d'identité existe maintenant, et elle ouvre le parcours.**
 * Décision du mainteneur (17/09/2026, Q36) : « nom prénom obligatoire car
 * c'est la base, voilà, point. » Ça reste cohérent avec la réponse qui l'a
 * précédée — l'assistant *est* la création du profil, il n'y a pas d'étape
 * « identité » séparée du reste — celle-ci porte simplement les deux
 * premiers champs de `cycliste`. `CHAMPS_MODIFIABLES` (`api/depots.py`)
 * couvre désormais `cycliste.prenom` et `cycliste.nom`, au même titre que la
 * FTP et le poids.
 *
 * Rien n'en dépend dans le calcul : ni le modèle physique, ni les zones, ni
 * la tenue (règle absolue 5 — on ne prétend pas à un usage qui n'existe
 * pas). L'usage réel attend le lot F3 des comptes multi-utilisateurs :
 * e-mail d'invitation, affichage d'un compte parmi plusieurs. Jusque-là,
 * c'est une donnée de compte pure, et l'écran le dit plutôt que de laisser
 * croire à autre chose.
 */

import { useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Profil, Zones } from "../api/types";
import { nombre, pourcentage } from "../api/formats";
import { EcranFtp } from "../composants/EcranFtp";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";

const ETAPES = ["Votre identité", "Votre puissance", "Votre départ", "Votre vélo", "intervals.icu", "C'est prêt"];

interface Props {
  profil: Profil;
  zones: Zones;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
  surFin: () => void;
}

export function Assistant({ profil, zones, surProfil, surZones, surFin }: Props) {
  const [etape, setEtape] = useState(0);
  const [panne, setPanne] = useState<string | null>(null);
  const [nomVelo, setNomVelo] = useState(profil.velos[0]?.nom ?? "");
  const [usageVelo, setUsageVelo] = useState(profil.velos[0]?.usage ?? "route");
  const [poidsVelo, setPoidsVelo] = useState(String(profil.velos[0]?.masse_kg ?? 8));
  const [poids, setPoids] = useState(String(profil.cycliste.masse_kg));
  const [prenom, setPrenom] = useState(profil.cycliste.prenom ?? "");
  const [nom, setNom] = useState(profil.cycliste.nom ?? "");
  const [cle, setCle] = useState("");

  async function enregistrer(sections: Record<string, unknown>) {
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

  function suivant() {
    setPanne(null);
    setEtape((n) => Math.min(n + 1, ETAPES.length - 1));
  }

  const liees = zones.valeurs_liees;

  return (
    <section>
      <div className="etapes-assistant">
        Étape {etape + 1} sur {ETAPES.length}
      </div>
      <div className="app-tete">
        <div>
          <span className="quand">{ETAPES[etape]}</span>
          <h1>
            {
              [
                "Comment vous appelez-vous ?",
                "Quelle est votre FTP ?",
                "D'où partez-vous ?",
                "Avec quoi roulez-vous ?",
                "Brancher intervals.icu",
                "Tout est en place",
              ][etape]
            }
          </h1>
        </div>
      </div>

      {panne ? <div className="encart alerte">{panne}</div> : null}

      {etape === 0 ? (
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
            <input
              className="saisie"
              id="cycliste-nom"
              value={nom}
              onChange={(e) => setNom(e.target.value)}
            />
            <div className="aide">
              La base du compte. On ne vous demande pas votre âge : rien ne s'en sert
              aujourd'hui, ni dans le calcul ni ailleurs.
            </div>
          </div>
          <div className="bloc doux">
            <div className="bloc-tete">
              <h2>Et ensuite, on va vous demander</h2>
            </div>
            <div className="etapes">
              <div className="etape">
                <span className="km">1</span>
                <span className="nom">
                  <b>Votre puissance seuil</b>
                  <small>Elle fixe vos zones, et la longueur de vos boucles.</small>
                </span>
                <span />
              </div>
              <div className="etape">
                <span className="km">2</span>
                <span className="nom">
                  <b>D'où vous partez d'habitude</b>
                  <small>Rien ne tourne sans point de départ.</small>
                </span>
                <span />
              </div>
              <div className="etape">
                <span className="km">3</span>
                <span className="nom">
                  <b>Votre vélo</b>
                  <small>Son poids et son type entrent dans le calcul du temps.</small>
                </span>
                <span />
              </div>
              <div className="etape">
                <span className="km">4</span>
                <span className="nom">
                  <b>Votre clé intervals.icu</b>
                  <small>Facultatif, et ça se branche plus tard.</small>
                </span>
                <span />
              </div>
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            disabled={prenom.trim() === "" || nom.trim() === ""}
            onClick={async () => {
              const bon = await enregistrer({
                cycliste: { prenom: prenom.trim(), nom: nom.trim() },
              });
              if (bon) suivant();
            }}
          >
            Continuer
          </button>
        </>
      ) : null}

      {etape === 1 ? (
        <>
          <EcranFtp
            zones={zones}
            surApercu={surZones}
            surFtp={async (ftp) => {
              await enregistrer({ cycliste: { ftp_w: ftp } });
            }}
          />
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
              if (bon) suivant();
            }}
          >
            Continuer
          </button>
          <p className="mention" style={{ textAlign: "center", marginTop: 8 }}>
            C'est la position dans la zone qui est enregistrée, jamais les watts.
          </p>
        </>
      ) : null}

      {etape === 2 ? (
        <>
          <FormulaireAdresse
            valeurActuelle={profil.depart.nom}
            libelleConfirmation="C'est bien là, enregistrer ce départ"
            aide="Vous pourrez partir d'ailleurs à chaque sortie. Celui-ci n'est que le défaut."
            surChoix={async (depart: DepartChoisi) => {
              const bon = await enregistrer({ depart });
              if (bon) suivant();
            }}
          />
          <button type="button" className="bouton second" onClick={suivant}>
            Garder ce départ
          </button>
        </>
      ) : null}

      {etape === 3 ? (
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
          </div>
          <button
            type="button"
            className="bouton"
            onClick={async () => {
              const autres = profil.velos.slice(1).map((v) => v as unknown as object);
              const premier = {
                ...((profil.velos[0] ?? {}) as unknown as object),
                nom: nomVelo,
                usage: usageVelo,
                masse_kg: Number(poidsVelo.replace(",", ".")),
              };
              const bon = await enregistrer({ velos: [premier, ...autres] });
              if (bon) suivant();
            }}
            disabled={nomVelo.trim() === ""}
          >
            Continuer
          </button>
        </>
      ) : null}

      {etape === 4 ? (
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
                <a
                  className="lien"
                  href="https://intervals.icu/settings"
                  target="_blank"
                  rel="noreferrer"
                >
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
            <input
              className="saisie mono"
              id="cle"
              value={cle}
              onChange={(e) => setCle(e.target.value)}
            />
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
            <button type="button" className="bouton second" onClick={suivant}>
              Plus tard
            </button>
            <button
              type="button"
              className="bouton"
              disabled={cle.trim() === ""}
              onClick={async () => {
                const bon = await enregistrer({ intervals: { api_key: cle } });
                if (bon) suivant();
              }}
            >
              Enregistrer
            </button>
          </div>
        </>
      ) : null}

      {etape === 5 ? (
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
              <span className="val">{nombre(zones.ftp_w)} W</span>
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
                  {velo.usage} · {nombre(velo.masse_kg, 1)} kg
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

      {etape > 0 && etape < ETAPES.length - 1 ? (
        <button type="button" className="bouton fantome" onClick={() => setEtape(etape - 1)}>
          Revenir en arrière
        </button>
      ) : null}
    </section>
  );
}

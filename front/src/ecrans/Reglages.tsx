/** E21 · E22 — profil et réglages.
 *
 * Six groupes, dans l'ordre où on y revient : l'identité, qui ne bouge
 * presque jamais, puis ce qui change souvent — un poids bouge, une FTP
 * progresse — et enfin ce qui ne se touche qu'une fois, en bas, jusqu'au
 * compte lui-même.
 *
 * **Identité (prénom, nom) reprend l'écran E8 de l'assistant** (Q36,
 * 17/09/2026 : « nom prénom obligatoire car c'est la base »). Un profil créé
 * avant ce lot peut arriver ici avec les deux champs vides — ce n'est pas une
 * panne, `Cycliste.prenom`/`nom` restent optionnels au chargement pour cette
 * raison précise — et ce panneau est l'endroit où le compléter.
 *
 * **« Mon compte » (lot L9.6, `MonCompteVolet` plus bas)** ferme ce que le
 * lot F2 avait renvoyé aux comptes : adresse, changement de mot de passe,
 * export RGPD et suppression — celle-ci à double confirmation, un texte
 * explicite avant le geste irréversible. Les clés d'accès (passkey) restent
 * hors sujet : `api/comptes.py` n'en porte toujours aucune.
 */

import { useEffect, useState } from "react";
import { api, ErreurApi } from "../api/client";
import type { Profil, Zones } from "../api/types";
import { jourEnLettres, nombre, PNEUS, pourcentage, usageDeVelo } from "../api/formats";
import { EcranFtp } from "../composants/EcranFtp";
import { FormulaireAdresse } from "../composants/FormulaireAdresse";
import type { DepartChoisi } from "../composants/FormulaireAdresse";

type Volet = "identite" | "ftp" | "poids" | "depart" | "velos" | "intervals" | "compte" | null;

interface Props {
  profil: Profil;
  zones: Zones;
  surProfil: (profil: Profil) => void;
  surZones: (zones: Zones) => void;
  surRefaireInstallation: () => void;
  /** Appelée une fois `POST /sortir` fait — l'écran de connexion, rien de plus (lot L7.2-D). */
  surDeconnexion: () => void;
}

export function Reglages({
  profil,
  zones,
  surProfil,
  surZones,
  surRefaireInstallation,
  surDeconnexion,
}: Props) {
  const [volet, setVolet] = useState<Volet>(null);
  const [poids, setPoids] = useState(String(profil.cycliste.masse_kg));
  const [prenom, setPrenom] = useState(profil.cycliste.prenom ?? "");
  const [nom, setNom] = useState(profil.cycliste.nom ?? "");
  const [cle, setCle] = useState("");
  const [panne, setPanne] = useState<string | null>(null);
  const [dit, setDit] = useState<string | null>(null);

  async function enregistrer(sections: Record<string, unknown>, phrase: string) {
    setPanne(null);
    setDit(null);
    try {
      const reponse = await api.modifierProfil(sections);
      surProfil(reponse.donnees);
      const fraiches = await api.zones();
      surZones(fraiches.donnees);
      setDit(phrase);
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    }
  }

  function basculer(cible: Exclude<Volet, null>) {
    setVolet(volet === cible ? null : cible);
    setDit(null);
    setPanne(null);
  }

  const liees = zones.valeurs_liees;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">Votre profil</span>
          <h1>Réglages</h1>
        </div>
      </div>

      {dit ? <div className="encart bien">{dit}</div> : null}
      {panne ? <div className="encart alerte">{panne}</div> : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">Identité</span>
          <button
            type="button"
            className="val lien texte"
            onClick={() => basculer("identite")}
            aria-expanded={volet === "identite"}
          >
            {profil.cycliste.prenom || profil.cycliste.nom
              ? `${profil.cycliste.prenom} ${profil.cycliste.nom}`.trim()
              : "à renseigner"}
          </button>
        </div>
      </div>

      {volet === "identite" ? (
        <div className="bloc">
          <div className="champ">
            <label htmlFor="reglages-prenom">Prénom</label>
            <input
              className="saisie"
              id="reglages-prenom"
              value={prenom}
              onChange={(e) => setPrenom(e.target.value)}
            />
          </div>
          <div className="champ">
            <label htmlFor="reglages-nom">Nom</label>
            <input
              className="saisie"
              id="reglages-nom"
              value={nom}
              onChange={(e) => setNom(e.target.value)}
            />
            <div className="aide">
              La base du compte (17/09/2026). Aucun calcul ne s'en sert aujourd'hui ; l'usage
              prévu est le compte multi-utilisateurs du lot F3.
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            disabled={prenom.trim() === "" || nom.trim() === ""}
            onClick={() =>
              enregistrer(
                { cycliste: { prenom: prenom.trim(), nom: nom.trim() } },
                "Identité enregistrée.",
              )
            }
          >
            Enregistrer
          </button>
        </div>
      ) : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">FTP</span>
          <button
            type="button"
            className="val lien"
            onClick={() => basculer("ftp")}
            aria-expanded={volet === "ftp"}
          >
            {/* Facultative depuis ce lot. Le bouton reste — c'est par lui qu'on
                la renseigne — mais il n'annonce pas une valeur qui n'existe pas. */}
            {zones.ftp_w === null ? "à renseigner" : `${nombre(zones.ftp_w)} W`}
          </button>
        </div>
        <div className="rangee">
          <span className="cle">Poids</span>
          <button
            type="button"
            className="val lien"
            onClick={() => basculer("poids")}
            aria-expanded={volet === "poids"}
          >
            {nombre(profil.cycliste.masse_kg, 1)} kg
          </button>
        </div>
        <div className="rangee">
          <span className="cle">Allure d'endurance</span>
          <span className="val">
            {liees
              ? `${nombre(liees.puissance_endurance_w)} W · ${pourcentage(liees.position_zone)} de la Z${zones.zone_endurance}`
              : "aucun vélo"}
          </span>
        </div>
      </div>

      {volet === "ftp" ? (
        <div className="bloc">
          <EcranFtp
            zones={zones}
            surApercu={surZones}
            surFtp={(ftp) => enregistrer({ cycliste: { ftp_w: ftp } }, "FTP enregistrée.")}
          />
          <button
            type="button"
            className="bouton"
            onClick={() =>
              enregistrer(
                { seance: { position_zone: zones.position_zone } },
                "Position dans la zone enregistrée — pas les watts : si votre FTP change, tout suit.",
              )
            }
          >
            Enregistrer cette allure
          </button>
        </div>
      ) : null}

      {volet === "poids" ? (
        <div className="bloc">
          <div className="champ">
            <label htmlFor="poids">Votre poids, équipé</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="poids"
                inputMode="decimal"
                value={poids}
                onChange={(e) => setPoids(e.target.value)}
              />
              <span className="unite">kg</span>
            </div>
            <div className="aide">
              Le poids total — vous, le vélo, ce que vous emportez — entre dans le calcul du
              temps.
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            onClick={() =>
              enregistrer(
                { cycliste: { masse_kg: Number(poids.replace(",", ".")) } },
                "Poids enregistré.",
              )
            }
          >
            Enregistrer
          </button>
        </div>
      ) : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">Départ habituel</span>
          <button
            type="button"
            className="val lien"
            onClick={() => basculer("depart")}
            aria-expanded={volet === "depart"}
          >
            {profil.depart.nom}
          </button>
        </div>
        {profil.velos.map((velo) => (
          <div className="rangee" key={velo.nom}>
            <span className="cle">{velo.nom}</span>
            <span className="val texte">
              {usageDeVelo(velo.usage)} · {nombre(velo.masse_kg, 1)} kg
              {velo.facteur_compteur === null
                ? " · vitesse supposée"
                : " · vitesse mesurée sur vos sorties"}
            </span>
          </div>
        ))}
        <div className="rangee">
          <span className="cle">Vos vélos</span>
          <button
            type="button"
            className="lien"
            onClick={() => basculer("velos")}
            aria-expanded={volet === "velos"}
          >
            Ajouter ou retirer
          </button>
        </div>
      </div>

      {volet === "depart" ? (
        <div className="bloc">
          <FormulaireAdresse
            valeurActuelle={profil.depart.nom}
            libelleConfirmation="C'est bien là, enregistrer ce départ"
            aide="Vous pourrez partir d'ailleurs à chaque sortie. Celui-ci n'est que le défaut."
            surChoix={(depart: DepartChoisi) =>
              enregistrer({ depart }, "Départ enregistré.")
            }
          />
        </div>
      ) : null}

      {volet === "velos" ? (
        <ListeVelos
          profil={profil}
          surListe={(velos) => enregistrer({ velos }, "Vélos enregistrés.")}
        />
      ) : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">intervals.icu</span>
          <button
            type="button"
            className="val lien texte"
            onClick={() => basculer("intervals")}
            aria-expanded={volet === "intervals"}
          >
            {profil.services.intervals.renseigne ? "Branché" : "Non branché"}
          </button>
        </div>
        <div className="rangee">
          <span className="cle">Traceur d'itinéraires</span>
          <span className="val texte">
            {/* `profil` est le nom du fichier de profil du traceur
                (`trekking`, `fastbike`…) : un identifiant de moteur de
                routage, sur une ligne qui s'appelle « Traceur d'itinéraires »
                en français. Il n'apprend rien à un cycliste, et le seul fait
                utile ici est que le service répond. */}
            {profil.services.brouter.renseigne ? "Branché" : "Non branché"}
          </span>
        </div>
        <div className="rangee">
          <span className="cle">Historique depuis</span>
          {/* C2, même défaut qu'à l'écran d'échec : une date ISO est une date
              de machine. */}
          <span className="val texte">{jourEnLettres(profil.historique_depuis)}</span>
        </div>
      </div>

      {volet === "intervals" ? (
        <div className="bloc">
          <div className="champ">
            <label htmlFor="cle-intervals">Votre clé intervals.icu</label>
            <input
              className="saisie mono"
              id="cle-intervals"
              value={cle}
              onChange={(e) => setCle(e.target.value)}
              placeholder="collez la clé ici"
            />
            <div className="aide">
              Réglages d'intervals.icu, tout en bas de la page, section « Developer Settings ».
              La clé est affichée en clair : masquer un secret qu'on vient de coller empêche
              de le relire pour vérifier.
            </div>
          </div>
          <button
            type="button"
            className="bouton"
            onClick={() => enregistrer({ intervals: { api_key: cle } }, "Clé enregistrée.")}
            disabled={cle.trim() === ""}
          >
            Enregistrer la clé
          </button>
        </div>
      ) : null}

      <div className="bloc doux liste">
        <div className="rangee">
          <span className="cle">Refaire l'installation</span>
          <button type="button" className="lien" onClick={surRefaireInstallation}>
            Reprendre
          </button>
        </div>
        {/* Mon compte (lot L9.6) : remplace le "Pas encore ici" de F2 — les
            clés d'accès (passkey) n'existent toujours pas (`api/comptes.py`),
            mais l'adresse, le mot de passe, l'export et la suppression sont
            désormais tous les quatre branchés. */}
        <div className="rangee">
          <span className="cle">Mon compte</span>
          <button
            type="button"
            className="val lien texte"
            onClick={() => basculer("compte")}
            aria-expanded={volet === "compte"}
          >
            Gérer
          </button>
        </div>
        {/* Se déconnecter (lot L7.2-D). `POST /sortir` révoque la session et
            efface le cookie, toujours 200 (idempotent) : rien à vérifier
            avant d'appeler `surDeconnexion`, qui ramène à l'écran de
            connexion. */}
        <div className="rangee">
          <span className="cle">Session</span>
          <button
            type="button"
            className="lien"
            onClick={async () => {
              await api.sortir().catch(() => undefined);
              surDeconnexion();
            }}
          >
            Se déconnecter
          </button>
        </div>
      </div>

      {volet === "compte" ? (
        <MonCompteVolet surCompteSupprime={surDeconnexion} />
      ) : null}
    </section>
  );
}

/**
 * Le volet « Mon compte » (lot L9.6) : adresse, changement de mot de passe, export,
 * suppression — les quatre gestes que F2 avait renvoyés au lot des comptes.
 *
 * Composant séparé plutôt qu'un bloc de plus dans `Reglages` : il porte son propre état
 * (adresse chargée à la demande, formulaire de mot de passe, double confirmation de
 * suppression) qui n'a aucun rapport avec le profil cycliste que `Reglages` gère par
 * ailleurs — les mélanger aurait fait grossir un unique gros composant pour un gain nul.
 */
function MonCompteVolet({ surCompteSupprime }: { surCompteSupprime: () => void }) {
  const [email, setEmail] = useState<string | null | undefined>(undefined);
  const [motDePasseActuel, setMotDePasseActuel] = useState("");
  const [nouveauMotDePasse, setNouveauMotDePasse] = useState("");
  const [envoiMotDePasse, setEnvoiMotDePasse] = useState(false);
  const [ditMotDePasse, setDitMotDePasse] = useState<string | null>(null);
  const [panneMotDePasse, setPanneMotDePasse] = useState<string | null>(null);
  const [confirmationSuppression, setConfirmationSuppression] = useState(false);
  const [suppressionEnCours, setSuppressionEnCours] = useState(false);
  const [panneSuppression, setPanneSuppression] = useState<string | null>(null);

  useEffect(() => {
    let vivant = true;
    if (email !== undefined) return;
    api
      .monCompte()
      .then((reponse) => {
        if (vivant) setEmail(reponse.donnees.email);
      })
      .catch(() => {
        if (vivant) setEmail(null);
      });
    return () => {
      vivant = false;
    };
  }, [email]);

  async function changerLeMotDePasse() {
    setPanneMotDePasse(null);
    setDitMotDePasse(null);
    setEnvoiMotDePasse(true);
    try {
      await api.changerMotDePasse(motDePasseActuel, nouveauMotDePasse);
      setMotDePasseActuel("");
      setNouveauMotDePasse("");
      setDitMotDePasse("Mot de passe changé.");
    } catch (erreur) {
      setPanneMotDePasse(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    } finally {
      setEnvoiMotDePasse(false);
    }
  }

  async function confirmerLaSuppression() {
    setPanneSuppression(null);
    setSuppressionEnCours(true);
    try {
      await api.supprimerMesDonnees();
      // Le compte, ses sessions et son invitation viennent d'être effacés
      // côté serveur (`DELETE /moi`, `vie_privee.effacer_donnees`) : il n'y
      // a plus de session à fermer, seulement l'écran de connexion à
      // montrer — le même geste qu'après « Se déconnecter ».
      surCompteSupprime();
    } catch (erreur) {
      setPanneSuppression(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      setSuppressionEnCours(false);
    }
  }

  return (
    <div className="bloc">
      <div className="champ">
        <span className="cle">Adresse</span>
        <div className="val texte">
          {email === undefined ? "Chargement…" : (email ?? "aucun compte sur ce serveur")}
        </div>
      </div>

      <div className="bloc-tete">
        <h2>Changer de mot de passe</h2>
      </div>
      {ditMotDePasse ? <div className="encart bien">{ditMotDePasse}</div> : null}
      {panneMotDePasse ? <div className="encart alerte">{panneMotDePasse}</div> : null}
      <div className="champ">
        <label htmlFor="compte-mdp-actuel">Mot de passe actuel</label>
        <input
          className="saisie"
          id="compte-mdp-actuel"
          type="password"
          autoComplete="current-password"
          value={motDePasseActuel}
          onChange={(e) => setMotDePasseActuel(e.target.value)}
        />
      </div>
      <div className="champ">
        <label htmlFor="compte-mdp-nouveau">Nouveau mot de passe</label>
        <input
          className="saisie"
          id="compte-mdp-nouveau"
          type="password"
          autoComplete="new-password"
          value={nouveauMotDePasse}
          onChange={(e) => setNouveauMotDePasse(e.target.value)}
        />
      </div>
      <button
        type="button"
        className="bouton"
        disabled={motDePasseActuel.trim() === "" || nouveauMotDePasse.trim() === "" || envoiMotDePasse}
        onClick={changerLeMotDePasse}
      >
        {envoiMotDePasse ? "Changement…" : "Changer le mot de passe"}
      </button>

      <div className="bloc-tete">
        <h2>Mes données</h2>
      </div>
      <div className="rangee">
        <span className="cle">Télécharger mes données</span>
        {/* Lien natif, pas un appel de ce module : le cookie de session
            (même origine) suffit à authentifier le téléchargement, comme le
            GPX d'une proposition (`Proposition.tsx`). */}
        <a className="lien" href={api.urlExportMesDonnees()} download>
          Export ZIP
        </a>
      </div>

      <div className="bloc-tete">
        <h2>Supprimer mon compte</h2>
      </div>
      {panneSuppression ? <div className="encart alerte">{panneSuppression}</div> : null}
      {!confirmationSuppression ? (
        <button
          type="button"
          className="lien"
          onClick={() => setConfirmationSuppression(true)}
        >
          Supprimer mon compte…
        </button>
      ) : (
        <>
          {/* Le texte de référence sur ce qui part et ce qui reste est
              `vie_privee.GABARIT_LISEZ_MOI` (`api/vie_privee.py`) — repris
              ici en substance, pas copié mot à mot (c'est un fichier
              d'archive, pas un texte d'écran). */}
          <div className="encart alerte">
            <p>
              <b>Ceci efface définitivement</b> votre profil, vos fichiers déposés ou générés,
              votre journal de services et votre cache d'activités. Ceci ferme aussi votre
              compte : mot de passe, sessions ouvertes et invitation en cours disparaissent
              avec lui.
            </p>
            <p>
              <b>Ceci ne touche pas</b> les routes apprises de vos sorties : elles restent,
              collectives, comme le reste de la contribution de tous les cyclistes à la
              carte (doctrine du projet, §10.2).
            </p>
          </div>
          <button
            type="button"
            className="bouton"
            disabled={suppressionEnCours}
            onClick={confirmerLaSuppression}
          >
            {suppressionEnCours ? "Suppression…" : "Confirmer la suppression définitive"}
          </button>
          <button
            type="button"
            className="lien"
            disabled={suppressionEnCours}
            onClick={() => setConfirmationSuppression(false)}
          >
            Annuler
          </button>
        </>
      )}
    </div>
  );
}

function ListeVelos({
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
      masse_kg: String(v.masse_kg),
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
              masse_kg: Number(velo.masse_kg.replace(",", ".")),
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

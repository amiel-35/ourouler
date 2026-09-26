/** FTP, zones, et les **trois valeurs liées** (décisions 7 et 8).
 *
 * | la puissance visée | éditable — pour qui pense en watts |
 * | la vitesse à plat, sans vent, lancé | éditable — pour tous les autres |
 * | la moyenne compteur attendue | **non éditable** — la réconciliation |
 *
 * Éditer l'une recalcule les autres, et c'est l'API qui recalcule : le front
 * n'a pas le modèle physique et ne l'aura jamais. Il envoie **une** entrée à
 * `POST /profil/zones/apercu`, il affiche ce qui revient, et rien de plus.
 *
 * Ce qui est **enregistré** est la position dans la zone, jamais les watts :
 * une FTP qui progresse de 12 W déplace tout l'escalier sans qu'on touche à
 * rien. C'est le point de la décision 7, et le `PATCH` ne porte que
 * `seance.position_zone`.
 *
 * Et la moyenne compteur **dit toujours si son facteur est mesuré ou
 * supposé**. Sans cette mention, l'écran ment à qui hérite du défaut
 * (décision 8 ; on ne présente jamais une estimation comme une mesure).
 */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ErreurApi } from "../api/client";
import type { Zones } from "../api/types";
import { modelePhysique, nombre, pourcentage } from "../api/formats";

interface Props {
  zones: Zones;
  velo?: string;
  /** Appelé quand l'API a rendu un nouvel état des trois valeurs. */
  surApercu: (zones: Zones) => void;
  /** Absent dans l'assistant, où l'enregistrement se fait à l'étape suivante. */
  surFtp?: (ftp: number) => Promise<void>;
  /** La seconde réponse à la question posée, quand l'écran en pose une.
   *
   * L'assistant demande « connaissez-vous votre FTP ? » : les deux réponses
   * doivent tenir dans le même regard. Rendue sous le champ, avant les zones
   * — qui sont la *conséquence* d'une FTP, donc exactement ce que n'a pas à
   * lire celui qui répond non. Dans les réglages, il n'y a pas de question,
   * donc pas d'échappatoire. */
  echappatoire?: ReactNode;
}

type Champ = "puissance" | "vitesse" | null;

/** La FTP telle qu'on la met dans le champ : des watts entiers.
 *
 * Une FTP qui sort de l'entonnoir (vitesse puis terrain, `t4`) est le résultat
 * d'une inversion du modèle physique, donc un flottant : le champ affichait
 * « 250.97864468892416 », quatorze décimales sur une grandeur dont le dernier
 * watt n'est déjà pas mesurable.
 *
 * `null` (FTP facultative, `docs/journal/ux/parcours_accueil.md`)
 * rend un champ vide, jamais le texte « null ».
 */
export function ftpAffichee(ftp_w: number | null): string {
  return ftp_w === null ? "" : String(Math.round(ftp_w));
}

export function EcranFtp({ zones, velo, surApercu, surFtp, echappatoire }: Props) {
  const liees = zones.valeurs_liees;
  // `zones.ftp_w` peut valoir `null` (FTP facultative,
  // `docs/journal/ux/parcours_accueil.md`) : un profil qui n'a pas encore franchi
  // l'étage T3/T4 de l'accueil. Un champ vide, jamais le texte « null ».
  const [ftp, setFtp] = useState(ftpAffichee(zones.ftp_w));
  const [enEdition, setEnEdition] = useState<Champ>(null);
  const [brouillon, setBrouillon] = useState("");
  const [panne, setPanne] = useState<string | null>(null);
  const minuteur = useRef<number | undefined>(undefined);

  useEffect(() => setFtp(ftpAffichee(zones.ftp_w)), [zones.ftp_w]);
  useEffect(() => () => window.clearTimeout(minuteur.current), []);

  function demanderApercu(champ: Exclude<Champ, null>, texte: string) {
    setEnEdition(champ);
    setBrouillon(texte);
    const valeur = Number(texte.replace(",", "."));
    window.clearTimeout(minuteur.current);
    if (!Number.isFinite(valeur) || valeur <= 0) return;
    minuteur.current = window.setTimeout(async () => {
      try {
        const entree =
          champ === "puissance"
            ? { puissance_w: valeur, velo }
            : { vitesse_a_plat_kmh: valeur, velo };
        const reponse = await api.apercuZones(entree);
        setPanne(null);
        surApercu(reponse.donnees);
      } catch (erreur) {
        setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
      }
    }, 350);
  }

  function valeurAffichee(champ: Exclude<Champ, null>, depuisApi: number): string {
    return enEdition === champ ? brouillon : nombre(depuisApi, champ === "puissance" ? 0 : 1);
  }

  async function validerFtp() {
    const valeur = Number(ftp.replace(",", "."));
    if (!surFtp || !Number.isFinite(valeur) || valeur <= 0) return;
    // Sous le watt, ce n'est pas une modification : c'est l'arrondi d'affichage
    // qui reviendrait. Sans cette tolérance, ouvrir puis quitter le champ
    // réécrirait la FTP en silence, alors qu'on n'a rien tapé.
    if (zones.ftp_w !== null && Math.abs(valeur - zones.ftp_w) < 0.5) return;
    try {
      await surFtp(valeur);
      setPanne(null);
    } catch (erreur) {
      setPanne(erreur instanceof ErreurApi ? erreur.message : String(erreur));
    }
  }

  const hautDeLEchelle = Math.max(...zones.zones.map((z) => z.haut_w), zones.ftp_w ?? 0);

  return (
    <div>
      <div className="champ">
        <label htmlFor="ftp">Puissance seuil (FTP)</label>
        <div className="saisie-unite">
          <input
            className="saisie mono"
            id="ftp"
            inputMode="decimal"
            value={ftp}
            onChange={(e) => setFtp(e.target.value)}
            onBlur={validerFtp}
            disabled={!surFtp}
          />
          <span className="unite">W</span>
        </div>
        <div className="aide">
          La puissance que vous tenez environ une heure. Si vous avez fait un test de
          20 minutes, comptez 95 % de la moyenne.
        </div>
      </div>

      {echappatoire}

      {zones.ftp_w === null ? (
        <div className="encart attention">
          <b>Pas encore de FTP renseignée.</b> Tapez un chiffre ci-dessus pour voir vos zones,
          ou continuez sans — l'assistant sait s'en passer.
        </div>
      ) : (
      <div className="bloc doux">
        <div className="bloc-tete">
          <h2>Vos zones</h2>
          <span className="rang">Calculées</span>
        </div>
        <div className="zones">
          {zones.zones.map((palier) => (
            <div
              className={`zone-l${palier.numero === zones.zone_endurance ? " endurance" : ""}`}
              key={palier.numero}
            >
              <span className="n">Z{palier.numero}</span>
              <span
                className="jauge"
                style={{
                  background: `var(--couleur-effort-${Math.min(palier.numero, 5)})`,
                  width: `${Math.round((palier.haut_w / hautDeLEchelle) * 100)}%`,
                }}
              />
              <span className="v">
                {palier.ouverte
                  ? `${nombre(palier.bas_w)} W et +`
                  : `${nombre(palier.bas_w)} – ${nombre(palier.haut_w)} W`}
              </span>
            </div>
          ))}
        </div>
      </div>
      )}

      {liees === null && zones.ftp_w !== null ? (
        // `zones.ftp_w !== null` : sans FTP, l'encart au-dessus l'a déjà dit,
        // pas la peine d'en afficher un second qui parlerait du vélo à tort.
        <div className="encart attention">
          <b>Pas de vélo enregistré.</b> Sans vélo, il n'y a ni modèle physique ni facteur de
          compteur — les trois valeurs liées n'ont rien à réconcilier.
        </div>
      ) : liees !== null ? (
        <div className="bloc">
          <div className="bloc-tete">
            <h2>Votre allure d'endurance</h2>
            <span className="rang">{liees.velo}</span>
          </div>

          <div className="champ">
            <label htmlFor="puissance-visee">Puissance visée</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="puissance-visee"
                inputMode="decimal"
                value={valeurAffichee("puissance", liees.puissance_endurance_w)}
                onChange={(e) => demanderApercu("puissance", e.target.value)}
                onBlur={() => setEnEdition(null)}
              />
              <span className="unite">W</span>
            </div>
          </div>

          <div className="champ">
            <label htmlFor="vitesse-plat">Vitesse à plat, sans vent, lancé</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="vitesse-plat"
                inputMode="decimal"
                value={valeurAffichee("vitesse", liees.vitesse_a_plat_kmh)}
                onChange={(e) => demanderApercu("vitesse", e.target.value)}
                onBlur={() => setEnEdition(null)}
              />
              <span className="unite">km/h</span>
            </div>
            <div className="aide">
              Pas la moyenne de votre compteur : la vitesse que vous tenez sur du plat, à
              l'abri du vent, une fois lancé.
            </div>
          </div>

          <div className="champ">
            <label htmlFor="moyenne-compteur">Moyenne compteur attendue</label>
            <div className="saisie-unite">
              <input
                className="saisie mono"
                id="moyenne-compteur"
                value={nombre(liees.moyenne_compteur_kmh, 1)}
                readOnly
                disabled
              />
              <span className="unite">km/h</span>
            </div>
            <div className="aide">
              Ce que votre compteur affichera, relief et arrêts compris.{" "}
              {liees.facteur_mesure ? (
                <b>
                  Facteur {nombre(liees.facteur_compteur, 3)},{" "}
                  <span>mesuré sur vos sorties</span>.
                </b>
              ) : (
                <b>
                  Facteur {nombre(liees.facteur_compteur, 3)},{" "}
                  <span>supposé — il n'a pas été mesuré sur vos sorties</span>.
                </b>
              )}{" "}
              Cette valeur ne s'édite pas : c'est elle qui réconcilie les deux autres.
            </div>
          </div>

          <p className="mention">
            Vous êtes à {pourcentage(liees.position_zone)} de votre Z{zones.zone_endurance},
            soit {pourcentage(liees.puissance_endurance_pct)} de votre FTP. C'est cette
            position qui est enregistrée — pas les watts : si votre FTP change, tout
            l'escalier suit.
          </p>

          {liees.hors_bande ? (
            <div className="encart attention" style={{ marginTop: "var(--espace-champ)" }}>
              <b>Vous êtes sorti de votre Z{zones.zone_endurance}.</b> C'est ce qui arrive
              quand on saisit sa moyenne compteur dans le champ « à plat ». On vous le montre
              plutôt que de le corriger en silence.
            </div>
          ) : null}

          <p className="mention" style={{ marginTop: "var(--espace-champ)" }}>
            Modèle physique : {modelePhysique(liees.modele_physique)}.
          </p>
        </div>
      ) : null}

      {panne ? <div className="encart alerte">{panne}</div> : null}
    </div>
  );
}

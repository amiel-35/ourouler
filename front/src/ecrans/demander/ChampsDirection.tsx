/** Les champs de direction de Q44 : le mode, puis le point cardinal (sur la
 * rose des huit directions) ou la préférence au vent. */

import type { Enveloppe, Meteo, Profil, VentDepart } from "../../api/types";
import { directionsDepuisCellules } from "../../api/meteoRose";
import { departEstReel, VENT_PREFERENCE_EN_TOUTES_LETTRES } from "../../api/formats";
import { LegendeRose, RoseDirections } from "../../composants/RoseDirections";
import {
  azimutsTexte,
  informationVent,
  MESSAGE_VENT_INDISPONIBLE,
  PREFERENCES_VENT,
} from "./demande";
import type { Demande } from "./demande";

type Changer = (morceau: Partial<Demande>) => void;

export function ChoixDirection({
  demande,
  changer,
  vent,
  erreurVent,
  profil,
}: {
  demande: Demande;
  changer: Changer;
  vent: Enveloppe<VentDepart> | null;
  erreurVent: string | null;
  profil: Profil;
}) {
  return (
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
      {(() => {
        const infoVent = informationVent(vent, erreurVent);
        return (
          <div className="aide" title={infoVent.detail ?? undefined}>
            {infoVent.texte}
            {infoVent.texte === MESSAGE_VENT_INDISPONIBLE && !departEstReel(profil.depart) ? (
              <>
                {" "}
                <a href="/?onglet=reglages">Renseigner votre départ dans les réglages</a>
              </>
            ) : null}
          </div>
        );
      })()}
    </div>
  );
}

export function PointCardinal({
  demande,
  changer,
  meteo,
  erreurMeteo,
}: {
  demande: Demande;
  changer: Changer;
  meteo: Enveloppe<Meteo> | null;
  erreurMeteo: string | null;
}) {
  // La rose : une ligne par direction, agrégée depuis les cellules brutes de
  // `/meteo` (`meteoRose.directionsDepuisCellules`, documenté là-bas —
  // jamais un second calcul ici).
  const directionsMeteo = meteo ? directionsDepuisCellules(meteo.donnees.cellules) : [];
  const directionRecommandee = meteo?.donnees.meilleure_direction?.nom ?? null;
  const motifRecommandation = meteo?.donnees.meilleure_direction?.motif ?? null;

  return (
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
  );
}

export function PreferenceVent({
  demande,
  changer,
  vent,
}: {
  demande: Demande;
  changer: Changer;
  vent: Enveloppe<VentDepart> | null;
}) {
  return (
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
  );
}

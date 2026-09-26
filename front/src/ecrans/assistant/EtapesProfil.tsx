/** Poids et vélo : posés juste avant la première étape qui en a besoin. */

import type { CategoriePneu, Profil, Zones } from "../../api/types";
import { MASSE_VELO_DEFAUT_KG, PNEUS } from "../../api/formats";
import { surFocusSelectionner, surRelacherNePasDeselectionner } from "./arbre";
import type { EtatAssistant } from "./useAssistant";

export function EtapePoids({ a, zones }: { a: EtatAssistant; zones: Zones }) {
  const { poids, setPoids, enregistrer, setPoidsConnu, aller } = a;
  return (
    <>
      <div className="champ">
        <label htmlFor="poids-cycliste">Votre poids</label>
        <div className="saisie-unite">
          <input
            className="saisie mono"
            id="poids-cycliste"
            inputMode="decimal"
            value={poids}
            onChange={(e) => setPoids(e.target.value)}
            onFocus={surFocusSelectionner}
            onMouseUp={surRelacherNePasDeselectionner}
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
          if (bon) {
            setPoidsConnu(true);
            aller("velo");
          }
        }}
      >
        Continuer
      </button>
    </>
  );
}

export function EtapeVelo({ a, profil }: { a: EtatAssistant; profil: Profil }) {
  const {
    usageVelo,
    setUsageVelo,
    nomVelo,
    setNomVelo,
    poidsVelo,
    setPoidsVelo,
    pneu,
    setPneu,
    enregistrer,
    aller,
    etage,
  } = a;
  return (
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
          onFocus={surFocusSelectionner}
          onMouseUp={surRelacherNePasDeselectionner}
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
            placeholder={String(MASSE_VELO_DEFAUT_KG)}
          />
          <span className="unite">kg</span>
        </div>
        <div className="aide">Facultatif — sans chiffre, on suppose {MASSE_VELO_DEFAUT_KG} kg.</div>
      </div>
      <div className="champ">
        <label htmlFor="velo-pneu">Pneus</label>
        <select
          className="saisie"
          id="velo-pneu"
          value={pneu}
          onChange={(e) => setPneu(e.target.value as CategoriePneu | "")}
        >
          <option value="">Je ne sais pas</option>
          {PNEUS.map((p) => (
            <option key={p.cle} value={p.cle}>
              {p.libelle}
            </option>
          ))}
        </select>
        <div className="aide">
          Les pneus disent combien le vélo roule facilement — c'est ce qui fixe le
          roulement du modèle aujourd'hui. Vous pourrez le préciser plus tard, dans
          Réglages.
        </div>
      </div>
      <button
        type="button"
        className="bouton"
        disabled={nomVelo.trim() === ""}
        onClick={async () => {
          const autres = profil.velos.slice(1).map((v) => v as unknown as object);
          const premier = {
            ...((profil.velos[0] ?? {}) as unknown as object),
            nom: nomVelo,
            usage: usageVelo,
            masse_kg: poidsVelo.trim() === "" ? null : Number(poidsVelo.replace(",", ".")),
            pneu: pneu === "" ? null : pneu,
          };
          const bon = await enregistrer({ velos: [premier, ...autres] });
          // Une FTP déjà confirmée par Intervals (T1) saute T3 à T5 en
          // entier : le vélo était la seule chose qui lui manquait.
          if (bon) aller(etage === "intervals" ? "recap" : "t3");
        }}
      >
        Continuer
      </button>
    </>
  );
}

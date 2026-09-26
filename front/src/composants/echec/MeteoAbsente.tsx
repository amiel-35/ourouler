import type { Avertissement } from "../../api/types";


/**
 * E14 · dégradé : le parcours est servi, la météo non.
 *
 * Le cœur prévient sur sa sortie d'erreur, l'API capture dans
 * `avertissements`. On ne retire alors que les affirmations qu'on ne peut
 * plus soutenir — la pluie, le vent, la tenue —, jamais le parcours.
 *
 * **Sur le code, jamais sur la phrase** (corrigé le 17/09/2026). Cette
 * fonction cherchait `/m[ée]t[ée]o/i` dans le message, alors que
 * `docs/journal/ux/api_contrat.md` pose l'inverse en toutes lettres : « le code prime
 * sur le message […] qui peut être reformulé ». Le jour où quelqu'un écrivait
 * « Open-Meteo injoignable », le bandeau disparaissait sans bruit et il
 * restait un parcours servi sans pluie, sans vent, **et sans la phrase qui
 * dit pourquoi** — pire qu'un bloc vide, que E14 interdit déjà.
 *
 * Le front n'avait alors aucun autre levier : `avertissements` ne portait pas
 * de code. C'était un trou du contrat F1, il a été bouché côté API
 * (`api/erreurs.CODES_AVERTISSEMENT`) plutôt que contourné ici.
 */
export function meteoManquante(avertissements: Avertissement[]): string | null {
  const trouve = avertissements.find((a) => a.code === "meteo_indisponible");
  return trouve?.message ?? null;
}

export function BandeauMeteoAbsente({ phrase }: { phrase: string }) {
  return (
    <div className="encart attention">
      <b>Pas de météo.</b> Le parcours est calculé sans la pluie ni le vent — on ne vous dira
      pas où il fait sec. <span className="mention">{phrase}</span>
    </div>
  );
}

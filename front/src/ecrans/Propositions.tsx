/** E19 — les propositions, et E19 dégradé — quand il n'y en a qu'une.
 *
 * Une seule carte, les tracés superposés, **le choisi en couleur pleine et
 * les autres en pointillé gris**. Chaque proposition dit d'abord ce qui la
 * distingue — c'est le cœur qui écrit cette phrase — puis ses chiffres, et
 * **les chiffres ne sont pas les mêmes d'une carte à l'autre** : montrer
 * quatre colonnes identiques obligerait à lire quatre chiffres pour trouver
 * celui qui compte.
 *
 * Aucune note globale, aucun classement sur dix : c'est au cycliste de
 * savoir si aujourd'hui il préfère le sec ou le calme.
 */

import { useState } from "react";
import type { Candidate, Enveloppe, Proposition, Sortie } from "../api/types";
import {
  compteArrets,
  duree,
  dureeApprox,
  kmDepuisKm,
  nombre,
  pourcentage,
  VENT_DECRIT,
} from "../api/formats";
import { Carte, type TraceDessinee } from "../composants/Carte";
import { PanneauArbitrage } from "../composants/Arbitrage";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";
import { BandeauElargissement } from "../composants/Elargissement";
import { TempsEcoule } from "../composants/TempsEcoule";
import { JaugePluie } from "../composants/JaugePluie";

/** Le nom de l'axe sur lequel le cœur a distingué cette proposition. */
const AXES: Record<string, string> = {
  vent: "Le vent",
  pluie: "La pluie",
  ville: "Les arrêts",
  trafic: "Le trafic",
  demi_tours: "Les demi-tours",
  duree: "La durée",
  terrain: "Le terrain",
};

export interface Chiffre {
  cle: string;
  valeur: string;
  /** Second rang : présent, mais pas la réponse à la question posée. */
  second?: boolean;
}

/** Les chiffres qui comptent **pour cette proposition-là**. */
export function chiffresDe(proposition: Proposition, candidate: Candidate | null): Chiffre[] {
  const chiffres: Chiffre[] = [];
  if (candidate) chiffres.push({ cle: "km", valeur: nombre(candidate.distance_km, 1) });
  // Le porte à porte en majeur, le temps sans arrêt juste après
  // (18/09/2026) : « je demande 5 h, je veux 5 h, pas 4 h et un truc plus
  // loin qui me dit en fait c'est 5 h ». Sans porte à porte — aucun vélo,
  // donc aucune moyenne compteur — le temps de mouvement reste seul, mais
  // garde son nom.
  const ecoule = candidate?.temps_ecoule_s;
  if (ecoule === null || ecoule === undefined) {
    chiffres.push({ cle: "en roulant", valeur: duree(proposition.duree_s) });
  } else {
    chiffres.push({ cle: "porte à porte", valeur: `≈ ${dureeApprox(ecoule)}` });
    chiffres.push({
      cle: "sans un seul arrêt",
      valeur: duree(proposition.duree_s),
      second: true,
    });
  }
  if (candidate?.denivele_m !== null && candidate?.denivele_m !== undefined) {
    chiffres.push({ cle: "m D+", valeur: nombre(candidate.denivele_m) });
  }
  const axe = proposition.axe_distinctif ?? "";
  // La pluie se dessine désormais (`JaugePluie`, rendue à côté de ces
  // chiffres dans `Propositions.tsx`) plutôt que de s'écrire ici en texte —
  // ni doublon, ni régression : la même valeur, en jauge.
  if (axe === "trafic" && proposition.part_trafic !== null) {
    chiffres.push({ cle: "de trafic", valeur: pourcentage(proposition.part_trafic) });
  }
  if (axe === "demi_tours") {
    chiffres.push({ cle: "demi-tours", valeur: nombre(proposition.demi_tours) });
  }
  if (axe === "vent" && proposition.orientation_vent) {
    chiffres.push({
      cle: "",
      valeur: VENT_DECRIT[proposition.orientation_vent] ?? proposition.orientation_vent,
    });
  }
  const arrets = compteArrets(proposition.feux, proposition.stops);
  if (axe === "ville" && arrets !== null) {
    chiffres.push({ cle: "feux et stops", valeur: nombre(arrets) });
  }
  return chiffres;
}

export function Chiffres({ chiffres }: { chiffres: Chiffre[] }) {
  return (
    <div className="chiffres">
      {/* La clé peut être vide — « 1 h 05 » n'a pas d'unité à répéter — donc
          deux chiffres peuvent la partager : l'index sert de clé React. */}
      {chiffres.map((chiffre, rang) => (
        <span key={`${rang}-${chiffre.cle}`} className={chiffre.second ? "second-chiffre" : undefined}>
          {chiffre.second ? chiffre.valeur : <b>{chiffre.valeur}</b>} {chiffre.cle}
        </span>
      ))}
    </div>
  );
}

interface Props {
  reponse: Enveloppe<Sortie>;
  choisie: number;
  surChoix: (numero: number) => void;
  surOuvrir: () => void;
  surElargir?: () => void;
  surRetour: () => void;
}

export function Propositions({
  reponse,
  choisie,
  surChoix,
  surOuvrir,
  surElargir,
  surRetour,
}: Props) {
  const sortie = reponse.donnees;
  const parNumero = new Map(sortie.candidates.map((c) => [c.numero, c]));
  // L'inspection est **repliée par défaut** : celui qui veut juste rouler ne
  // doit pas être noyé sous des tracés gris. Elle s'ouvre d'un clic, pas en
  // éditant un fichier — et c'est l'ouverture qui pose les écartées sur la
  // carte, parce qu'une décision qu'on ne voit pas sur le tracé n'apprend rien.
  const [inspection, setInspection] = useState(false);
  const arbitrage = sortie.arbitrage ?? null;
  const ecarteesAvant = sortie.ecartees ?? [];
  const retenus = new Set(sortie.propositions.map((p) => p.numero));

  const traces: TraceDessinee[] = sortie.propositions.map((proposition) => ({
    points: parNumero.get(proposition.numero)?.trace?.points ?? [],
    choisi: proposition.numero === choisie,
    sort: "retenue",
    titre: proposition.distinction || `Proposition ${proposition.numero}`,
  }));
  if (inspection) {
    // Les candidates que le contraste a jetées : le tracé existait déjà dans
    // `candidates`, il n'était dessiné nulle part. Le titre porte la phrase du
    // cœur — c'est elle qui dit le pourcentage et contre quelle boucle.
    for (const verdict of arbitrage?.candidates ?? []) {
      if (retenus.has(verdict.numero)) continue;
      const points = parNumero.get(verdict.numero)?.trace?.points ?? [];
      if (points.length < 2) continue;
      traces.push({
        points,
        choisi: false,
        sort: "ecartee",
        titre: `n° ${verdict.numero} — ${verdict.motif}`,
      });
    }
    // Et celles tombées avant le contraste, quand elles ont un tracé : un
    // refus sur la distance n'en a aucun, et on n'en invente pas.
    for (const ecartee of ecarteesAvant) {
      const points = ecartee.trace?.points ?? [];
      if (points.length < 2) continue;
      traces.push({ points, choisi: false, sort: "ecartee", titre: ecartee.motif });
    }
  }

  const seule = sortie.propositions.length === 1;
  const manque = meteoManquante(reponse.avertissements);
  const dessinees = traces.filter((t) => t.sort === "ecartee").length;

  return (
    <section>
      <div className="app-tete">
        <div>
          <span className="quand">
            {sortie.demande.lieu_depart.nom} · {kmDepuisKm(sortie.demande.distance_km)} visés
          </span>
          <h1>
            {sortie.propositions.length === 1
              ? "Un seul parcours"
              : `${nombre(sortie.propositions.length)} parcours`}
          </h1>
        </div>
        {/* « Modifier » seul ne disait pas ce qu'on modifiait ni où l'on
            atterrissait. C'est la sortie de cet écran : elle se nomme. */}
        <button type="button" className="lien" onClick={surRetour}>
          Modifier la demande
        </button>
      </div>

      {manque ? <BandeauMeteoAbsente phrase={manque} /> : null}

      {/* L'écart à la distance demandée, quand il y en a un. Au-dessus des
          propositions et non dans chaque carte : c'est un fait sur la
          recherche entière, pas une propriété d'un parcours. */}
      <BandeauElargissement
        candidates={sortie.candidates}
        distanceVisee={sortie.demande.distance_km}
      />

      {/* Ce n'est pas une panne, et tout l'enjeu est que l'écran n'en ait pas
          l'air. Le motif vient du cœur en toutes lettres, et il porte déjà le
          compte : le répéter au-dessus ferait un écran qui bégaie. */}
      {sortie.motif_deux_propositions ? (
        <div className="encart info">
          <b>On en voulait trois, et on en propose moins.</b> {sortie.motif_deux_propositions}
        </div>
      ) : null}

      {/* Q45, et c'est le pendant exact du bandeau précédent : là il manquait
          une proposition, ici il manque une raison de préférer l'une des
          trois. Les deux se disent, parce que dans les deux cas le silence
          laisserait chercher quelque chose qui n'est pas là. Celui-ci est une
          bonne nouvelle — rien ne contraint le choix — et le mot qui le dit
          est « au choix », pas un avertissement. */}
      {sortie.motif_equivalence ? (
        <div className="encart info">
          <b>Au choix.</b> {sortie.motif_equivalence}
        </div>
      ) : null}

      <Carte
        traces={traces}
        depart={sortie.demande.lieu_depart}
        haute
        description={
          dessinees === 0
            ? `${sortie.propositions.length} boucle(s) au départ de ${sortie.demande.lieu_depart.nom}, celle qui est choisie en trait plein`
            : `${sortie.propositions.length} boucle(s) proposée(s) et ${dessinees} écartée(s) au départ de ${sortie.demande.lieu_depart.nom} ; celle qui est choisie en trait plein, les écartées en rouge fin`
        }
      />

      {sortie.propositions.map((proposition) => {
        const candidate = parNumero.get(proposition.numero) ?? null;
        const active = proposition.numero === choisie;
        return (
          <div className={active ? "bloc choisi" : "bloc"} key={proposition.numero}>
            <button
              type="button"
              className="carte-bouton"
              onClick={() => surChoix(proposition.numero)}
              aria-pressed={active}
            >
              <div className="bloc-tete">
                {/* Sans axe distinctif — le cas normal depuis Q43 — le titre
                    est le numéro de la proposition, et rien d'autre : nommer
                    un axe qui ne la distingue pas serait une invention. */}
                <h2>{AXES[proposition.axe_distinctif ?? ""] ?? `Proposition ${proposition.numero}`}</h2>
                <span className="rang">
                  {seule ? "Le seul" : active ? "Choisi" : proposition.numero}
                </span>
              </div>
              {proposition.distinction ? (
                <p className="mention forte">
                  {proposition.distinction}
                </p>
              ) : null}
              <Chiffres chiffres={chiffresDe(proposition, candidate)} />
              {proposition.axe_distinctif === "pluie" && proposition.pluie_mm !== null ? (
                <JaugePluie mm={proposition.pluie_mm} minutesPluie={candidate?.meteo?.minutes_pluie} />
              ) : null}
            </button>
            {/* Hors du bouton exprès : un `<details>` dans un `<button>` est
                un contrôle interactif imbriqué dans un autre, invalide en
                HTML. */}
            {candidate ? <TempsEcoule candidate={candidate} compteur={sortie.compteur} /> : null}
          </div>
        );
      })}

      {/* Replié sous les propositions, et non derrière un mode qui change
          toute la page : le mainteneur n'a pas tranché entre les deux, et
          celui-ci ne gêne personne tout en se découvrant à la souris. Un mode
          d'inspection global demanderait de décider ce que deviennent la
          tenue, la séance et le bouton « Ouvrir » — ce qui est une autre
          question que celle posée. */}
      {arbitrage ? (
        <PanneauArbitrage
          arbitrage={arbitrage}
          candidates={sortie.candidates}
          ecartees={ecarteesAvant}
          ouvert={inspection}
          surBascule={setInspection}
        />
      ) : null}

      <button type="button" className="bouton" onClick={surOuvrir}>
        Ouvrir
      </button>
      {seule && surElargir ? (
        <button type="button" className="bouton fantome" onClick={surElargir}>
          Chercher plus loin
        </button>
      ) : null}
      <p className="mention centre">Calculé en {nombre(reponse.duree_ms / 1000, 1)} s.</p>
    </section>
  );
}

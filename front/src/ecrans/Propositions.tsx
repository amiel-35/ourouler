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
 *
 * Les chiffres de chaque proposition sont choisis dans
 * `propositions/Chiffres.tsx`.
 */

import { useState } from "react";
import type { Enveloppe, Sortie } from "../api/types";
import { kmDepuisKm, nombre } from "../api/formats";
import { Carte, type TraceDessinee } from "../composants/Carte";
import { PanneauArbitrage } from "../composants/Arbitrage";
import { BandeauMeteoAbsente, meteoManquante } from "../composants/Echec";
import { BandeauElargissement } from "../composants/Elargissement";
import { TempsEcoule } from "../composants/TempsEcoule";
import { JaugePluie } from "../composants/JaugePluie";
import { AXES, Chiffres, chiffresDe } from "./propositions/Chiffres";

export { Chiffres, chiffresDe } from "./propositions/Chiffres";
export type { Chiffre } from "./propositions/Chiffres";

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
  // Depuis la relance d'office côté serveur (sprint 11, QP4) : le serveur a
  // déjà relancé lui-même la recherche avec plus de candidates avant de
  // répondre. Le bouton ne reste un filet que si, malgré cette relance,
  // moins de trois boucles ont été retenues — avant ce lot, il ne
  // s'affichait que pour une seule proposition (`seule`).
  const moinsDeTrois = sortie.propositions.length < 3;
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

      {/* Le pendant exact du bandeau précédent (décision Q45) : là il manquait
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
                {/* Sans axe distinctif — le cas normal (décision Q43) — le titre
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
          toute la page : celui-ci ne gêne personne tout en se découvrant à la souris. Un mode
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
      {moinsDeTrois && surElargir ? (
        <button type="button" className="bouton fantome" onClick={surElargir}>
          Chercher plus loin
        </button>
      ) : null}
      <p className="mention centre">Calculé en {nombre(reponse.duree_ms / 1000, 1)} s.</p>
    </section>
  );
}

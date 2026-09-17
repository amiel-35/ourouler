/** La carte — Leaflet et les tuiles OpenStreetMap, comme la page du jour.
 *
 * `src/ourouler/sortie/carte.py` utilise déjà Leaflet et ces tuiles-là, avec
 * l'attribution que l'ODbL impose ; le front fait pareil plutôt que
 * d'introduire un second moteur de carte dans le même produit.
 *
 * Les tracés arrivent en paires `[latitude, longitude]` (lot F0.1) : c'est
 * exactement ce que Leaflet attend, aucune conversion.
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { FlecheVent } from "../api/types";

const TUILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

/**
 * La forme de la flèche, reprise telle quelle de `sortie/carte.py`.
 *
 * Elle pointe vers le haut dans un carré de 20 × 20 ; la rotation autour du
 * centre (10, 10) l'oriente sur `depuis_deg`, la convention météo (0 = nord,
 * sens horaire). Elle montre donc **d'où vient** le vent, comme une girouette.
 */
const FORME_FLECHE = "M10 1 L17 18 L10 14 L3 18 Z";

const VENT_EN_MOTS: Record<string, string> = {
  face: "vent de face",
  dos: "vent dans le dos",
  travers: "vent de travers",
};

/**
 * Le marqueur d'une flèche : le dessin, sa rotation, et les chiffres dessous.
 *
 * La forme change avec le vent relatif — pleine pour un vent de face, creuse
 * pour un vent de dos, en pointillé pour un vent de travers — et pas
 * seulement la couleur : la page du sprint 5 avait déjà tranché ce point
 * pour que la carte reste lisible en noir et blanc et pour un daltonien.
 */
function icone(fleche: FlecheVent): L.DivIcon {
  const categorie = fleche.relatif ?? "inconnu";
  const etiquette =
    fleche.rafale_kmh === null
      ? String(fleche.vent_kmh)
      : `${fleche.vent_kmh}/${fleche.rafale_kmh}`;
  return L.divIcon({
    className: "",
    html:
      `<div class="vent-marqueur vent-${categorie}">` +
      `<svg class="vent-fleche" viewBox="0 0 20 20" aria-hidden="true">` +
      `<g transform="rotate(${fleche.depuis_deg} 10 10)">` +
      `<path class="fleche-forme" d="${FORME_FLECHE}"></path></g></svg>` +
      `<span class="vent-etiquette">${etiquette}</span></div>`,
    iconSize: undefined,
    iconAnchor: [10, 10],
  });
}

function infobulle(fleche: FlecheVent): string {
  let texte = `Vent ${fleche.vent_kmh} km/h`;
  if (fleche.rafale_kmh !== null) texte += `, rafales ${fleche.rafale_kmh} km/h`;
  const mots = fleche.relatif === null ? undefined : VENT_EN_MOTS[fleche.relatif];
  if (mots) texte += ` — ${mots} ici`;
  return texte;
}

export interface TraceDessinee {
  points: [number, number][];
  /** Le tracé retenu est plein ; les autres sont en pointillé (maquette E19). */
  choisi: boolean;
  titre?: string;
}

export interface SegmentDessine {
  points: [number, number][];
  couleur: string;
  titre?: string;
}

interface Props {
  traces: TraceDessinee[];
  /** Les blocs de la séance, posés sur le tracé retenu (maquette E20). */
  segments?: SegmentDessine[];
  /**
   * Le vent le long du tracé, **tel que l'API le rend**.
   *
   * Aucun filtre ici : la liste arrive déjà réduite aux échantillons où le
   * vent se sent. Un tableau vide veut donc dire « rien à montrer », et c'est
   * une réponse, pas un trou — d'où la phrase que les écrans affichent à côté
   * de la carte plutôt qu'un silence.
   */
  vents?: FlecheVent[];
  depart?: { latitude: number; longitude: number; nom?: string } | null;
  /**
   * Le zoom quand il n'y a qu'un point et aucun tracé. 12 montre la commune ;
   * 16 montre la rue, ce que demande une confirmation d'adresse (Q34) — on ne
   * vérifie pas qu'un géocodage a trouvé la bonne rue depuis 20 km d'altitude.
   */
  zoomPoint?: number;
  haute?: boolean;
  /** Ce que la carte montre, pour qui ne la voit pas. */
  description: string;
}

export function Carte({
  traces,
  segments = [],
  vents = [],
  depart,
  zoomPoint = 12,
  haute,
  description,
}: Props) {
  const conteneur = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const noeud = conteneur.current;
    if (!noeud) return;
    let carte: L.Map | null = null;
    try {
      carte = L.map(noeud, { attributionControl: true, scrollWheelZoom: false });
      L.tileLayer(TUILES, { attribution: ATTRIBUTION, maxZoom: 19 }).addTo(carte);

      const couche = L.layerGroup().addTo(carte);
      for (const trace of traces) {
        if (trace.points.length < 2) continue;
        L.polyline(trace.points, {
          color: trace.choisi ? "#12657f" : "#9aa5a2",
          weight: trace.choisi ? 4 : 2,
          opacity: trace.choisi ? 1 : 0.7,
          dashArray: trace.choisi ? undefined : "6 5",
        })
          .bindTooltip(trace.titre ?? "")
          .addTo(couche);
      }
      for (const segment of segments) {
        if (segment.points.length < 2) continue;
        L.polyline(segment.points, {
          color: segment.couleur,
          weight: 6,
          opacity: 0.95,
          lineCap: "round",
        })
          .bindTooltip(segment.titre ?? "")
          .addTo(couche);
      }
      // Après les tracés et les blocs : les flèches se posent dessus, jamais
      // dessous, sinon un bloc de séance les recouvre là où elles comptent le
      // plus — sur la portion où l'on va pousser.
      for (const fleche of vents) {
        L.marker(fleche.pt, { icon: icone(fleche) })
          .bindTooltip(infobulle(fleche), { sticky: true })
          .addTo(couche);
      }
      if (depart) {
        L.circleMarker([depart.latitude, depart.longitude], {
          radius: 6,
          color: "#12657f",
          fillColor: "#12657f",
          fillOpacity: 1,
        })
          .bindTooltip(depart.nom ?? "Départ")
          .addTo(couche);
      }

      const tous = traces.flatMap((t) => t.points);
      if (tous.length > 0) {
        carte.fitBounds(L.latLngBounds(tous), { padding: [14, 14] });
      } else if (depart) {
        carte.setView([depart.latitude, depart.longitude], zoomPoint);
      } else {
        carte.setView([0, 0], 2);
      }
    } catch {
      // Un environnement sans vraie mise en page (un test, une capture) ne
      // peut pas faire tourner Leaflet : la description textuelle reste, et
      // c'est elle qui porte le sens.
    }

    return () => {
      try {
        carte?.remove();
      } catch {
        /* rien à nettoyer */
      }
    };
  }, [traces, segments, vents, depart, zoomPoint]);

  return (
    <div
      className={haute ? "carte haute" : "carte"}
      ref={conteneur}
      role="img"
      aria-label={description}
    />
  );
}

/**
 * Ce que les flèches veulent dire — et ce que leur absence veut dire.
 *
 * Sans cette phrase, une carte sans flèche se lit « le vent n'a pas été
 * regardé » aussi bien que « il n'y a pas de vent ». Les deux ne sont pas la
 * même chose, et c'est l'ignorance qui ne doit jamais passer pour un zéro.
 *
 * `seuilKmh` vient de l'API (`question_vent.seuil_kmh`) quand l'écran l'a ;
 * sans lui la phrase se dit sans chiffre, plutôt que d'en inventer un.
 */
export function LegendeVent({ vents, seuilKmh }: { vents: FlecheVent[]; seuilKmh?: number | null }) {
  if (vents.length === 0) {
    return (
      <p className="mention legende-vent">
        Pas de flèche de vent sur ce parcours : le vent y reste
        {seuilKmh ? ` sous les ${seuilKmh} km/h` : " très faible"}, sous ce qui se sent
        sur le visage.
      </p>
    );
  }
  return (
    <p className="mention legende-vent">
      <span className="vent-swatch vent-face">▲</span> de face (ça freine) ·{" "}
      <span className="vent-swatch vent-dos">△</span> dans le dos (ça pousse) ·{" "}
      <span className="vent-swatch vent-travers">◇</span> de travers. La flèche pointe
      d'où vient le vent, comme une girouette ; les chiffres donnent la vitesse moyenne,
      puis la rafale, en km/h.
    </p>
  );
}

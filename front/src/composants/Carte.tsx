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

const TUILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

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

export function Carte({ traces, segments = [], depart, zoomPoint = 12, haute, description }: Props) {
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
  }, [traces, segments, depart, zoomPoint]);

  return (
    <div
      className={haute ? "carte haute" : "carte"}
      ref={conteneur}
      role="img"
      aria-label={description}
    />
  );
}

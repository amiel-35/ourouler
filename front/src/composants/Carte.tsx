/** La carte — Leaflet et les tuiles OpenStreetMap, comme la page du jour.
 *
 * `src/ourouler/sortie/carte.py` utilise déjà Leaflet et ces tuiles-là, avec
 * l'attribution que l'ODbL impose ; le front fait pareil plutôt que
 * d'introduire un second moteur de carte dans le même produit.
 *
 * Les tracés arrivent en paires `[latitude, longitude]` : c'est
 * exactement ce que Leaflet attend, aucune conversion.
 *
 * Les formes, styles et filtres sont dans `carte/dessin.ts`, la légende du
 * vent dans `carte/LegendeVent.tsx`.
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { FlecheVent } from "../api/types";
import {
  ATTRIBUTION,
  icone,
  infobulle,
  sansChevauchement,
  SEUIL_CHEVAUCHEMENT_VENT_PX,
  styleDe,
  styleVentDe,
  TUILES,
} from "./carte/dessin";
import type { SegmentDessine, SegmentVent, TraceDessinee } from "./carte/dessin";

export { sansChevauchement } from "./carte/dessin";
export type { SegmentDessine, SegmentVent, TraceDessinee } from "./carte/dessin";
export { LegendeVent } from "./carte/LegendeVent";

interface Props {
  traces: TraceDessinee[];
  /** Les blocs de la séance, posés sur le tracé retenu (maquette E20). */
  segments?: SegmentDessine[];
  /** Les portions du tracé retenu colorées par le coût du vent (point 5). */
  traceVent?: SegmentVent[];
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
   * 16 montre la rue, ce que demande une confirmation d'adresse — on ne
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
  traceVent = [],
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
        L.polyline(trace.points, styleDe(trace))
          .bindTooltip(trace.titre ?? "")
          .addTo(couche);
      }
      // Le vent, posé sur le tracé noir : avant les blocs de la séance, pour
      // qu'un bloc reste visible par-dessus là où les deux se recouvrent —
      // l'effort de la séance est la donnée la plus immédiatement utile en
      // roulant, le vent un contexte.
      for (const segment of traceVent) {
        if (segment.points.length < 2) continue;
        L.polyline(segment.points, styleVentDe(segment))
          .bindTooltip(segment.titre ?? "")
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
        // Même logique que `styleDe()` : `className` porte la couleur
        // jusqu'à `.trace-depart` dans `front/src/style.css`, jamais une
        // valeur hexadécimale recopiée ici.
        L.circleMarker([depart.latitude, depart.longitude], {
          radius: 6,
          className: "trace-depart",
          fillOpacity: 1,
        })
          .bindTooltip(depart.nom ?? "Départ")
          .addTo(couche);
      }

      // Cadrée sur l'emprise de **toutes** les boucles proposées, la carte
      // s'ouvrirait à l'échelle de deux régions pour trois candidates qui
      // tiennent dans un rayon de 30 km (constaté sur une boucle réelle de
      // 124 km). Le cadrage porte donc sur les seuls points de la boucle
      // **retenue** (`trace.choisi`), les autres
      // restant visibles en pointillé sans peser sur le zoom. Sans boucle
      // sélectionnée (aucune `choisi`, ou son tracé est vide — écran qui ne
      // distingue encore rien), on retombe sur l'emprise de toutes les
      // boucles plutôt que de ne rien cadrer.
      const traceChoisie = traces.find((t) => t.choisi && t.points.length > 0);
      const pointsCadrage = traceChoisie ? traceChoisie.points : traces.flatMap((t) => t.points);
      if (pointsCadrage.length > 0) {
        carte.fitBounds(L.latLngBounds(pointsCadrage), { padding: [14, 14] });
      } else if (depart) {
        carte.setView([depart.latitude, depart.longitude], zoomPoint);
      } else {
        carte.setView([0, 0], 2);
      }

      // Les flèches de vent, posées après le cadrage : leur position à
      // l'écran (donc leur chevauchement) dépend du zoom et du centre que
      // `fitBounds`/`setView` viennent de fixer. Une couche à elles, pour
      // pouvoir les redessiner seules quand le zoom change (boutons +/-, la
      // molette étant coupée) sans reconstruire toute la carte.
      const coucheVent = L.layerGroup().addTo(carte);
      const carteVent = carte;
      function redessinerVent() {
        coucheVent.clearLayers();
        if (vents.length === 0) return;
        // Amas illisible constaté sur une capture de production (trois
        // boucles de ~124 km) : les étiquettes « vitesse/rafale » qui se chevauchent à
        // l'écran se filtrent par détection de collision (`sansChevauchement`),
        // réévaluée à chaque zoom plutôt que figée au premier rendu.
        let visibles: FlecheVent[];
        try {
          visibles = sansChevauchement(
            vents,
            (fleche) => carteVent.latLngToContainerPoint(fleche.pt),
            SEUIL_CHEVAUCHEMENT_VENT_PX,
          );
        } catch {
          visibles = vents;
        }
        // Après les tracés et les blocs : les flèches se posent dessus,
        // jamais dessous, sinon un bloc de séance les recouvre là où elles
        // comptent le plus — sur la portion où l'on va pousser.
        for (const fleche of visibles) {
          L.marker(fleche.pt, { icon: icone(fleche) })
            .bindTooltip(infobulle(fleche), { sticky: true })
            .addTo(coucheVent);
        }
      }
      redessinerVent();
      carte.on("zoomend", redessinerVent);
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
  }, [traces, segments, traceVent, vents, depart, zoomPoint]);

  return (
    <div
      className={haute ? "carte haute" : "carte"}
      ref={conteneur}
      role="img"
      aria-label={description}
    />
  );
}

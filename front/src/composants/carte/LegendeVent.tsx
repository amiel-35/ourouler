import type { FlecheVent } from "../../api/types";

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
export function LegendeVent({
  vents,
  seuilKmh,
  traceColoree = false,
}: {
  vents: FlecheVent[];
  seuilKmh?: number | null;
  /** Le tracé porte au moins une portion colorée (point 5) — dit en mots, pour
   * qui ne voit pas la couleur ou ne peut pas la distinguer. */
  traceColoree?: boolean;
}) {
  if (vents.length === 0) {
    // Un vent trop faible pour mériter une flèche (< `seuilKmh`) reste
    // classé face/dos/travers — direction connue, vitesse négligeable — donc
    // le tracé peut se colorer même sans la moindre flèche : les deux ne
    // dépendent pas du même seuil (`vent_par_position` n'en a aucun).
    return (
      <p className="mention legende-vent">
        Pas de flèche de vent sur ce parcours : le vent y reste
        {seuilKmh ? ` sous les ${seuilKmh} km/h` : " très faible"}, sous ce qui se sent
        sur le visage.
        {traceColoree
          ? " Le tracé se colore quand même par endroits, en continu : vert là où il pousse, orange tireté là où il freine — plus fin qu'une flèche, mais réel."
          : ""}
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
      {traceColoree
        ? " Le tracé lui-même se colore pareil, en continu : vert là où il pousse, orange tireté là où il freine — pas seulement aux huit flèches."
        : ""}
    </p>
  );
}

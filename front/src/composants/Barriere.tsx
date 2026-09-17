/** Le dernier filet : une page blanche est le pire des états d'échec.
 *
 * Tous les échecs prévus sont des écrans (`Echec.tsx`). Restent les
 * imprévus — une réponse dont la forme a changé, un champ qu'on croyait
 * toujours là. Sans barrière, React démonte l'arbre entier et le cycliste
 * voit du blanc : indistinguable d'un écran cassé, et sans la moindre piste.
 *
 * C'est arrivé pendant la vérification de bout à bout du lot F2 : un jour
 * sans séance rend `{jour, seance: null}` au lieu d'une séance, et l'écran
 * « Aujourd'hui » se vidait. La cause est corrigée à la frontière de l'API ;
 * la barrière, elle, reste, parce que la prochaine surprise ne sera pas
 * celle-là.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface Etat {
  panne: Error | null;
}

export class Barriere extends Component<Props, Etat> {
  state: Etat = { panne: null };

  static getDerivedStateFromError(panne: Error): Etat {
    return { panne };
  }

  componentDidCatch(panne: Error, infos: ErrorInfo): void {
    // La console du navigateur est le seul journal qu'on ait ici, et c'est
    // là que le mainteneur ira regarder.
    console.error("où rouler : l'interface a buté", panne, infos.componentStack);
  }

  render(): ReactNode {
    if (this.state.panne === null) return this.props.children;
    return (
      <div className="coquille">
        <div className="app-tete">
          <div>
            <span className="quand">L'interface, pas le serveur</span>
            <h1>Cet écran n'a pas su s'afficher</h1>
          </div>
        </div>
        <div className="encart alerte">
          <b>C'est un défaut de l'interface, pas de vos données.</b> Le serveur a peut-être
          très bien répondu : c'est l'affichage qui a buté sur sa réponse.
        </div>
        <div className="bloc doux">
          <div className="bloc-tete">
            <h2>Ce qui aide à le corriger</h2>
          </div>
          <p className="mention" style={{ fontFamily: "var(--mono)" }}>
            {this.state.panne.message}
          </p>
        </div>
        <button
          type="button"
          className="bouton"
          onClick={() => {
            this.setState({ panne: null });
            window.location.reload();
          }}
        >
          Recharger
        </button>
      </div>
    );
  }
}

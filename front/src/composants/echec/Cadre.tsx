/** Le cadre commun des écrans d'échec, et la liste des leviers de repli. */

import type { ReactNode } from "react";


export interface Repli {
  titre: string;
  detail?: string;
  action: () => void;
}

export function Cadre({
  contexte,
  titre,
  children,
}: {
  contexte?: string;
  titre: string;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="app-tete">
        <div>
          {contexte ? <span className="quand">{contexte}</span> : null}
          <h1>{titre}</h1>
        </div>
      </div>
      {children}
    </section>
  );
}

export function ListeReplis({ replis }: { replis: Repli[] }) {
  if (replis.length === 0) return null;
  return (
    <div className="bloc doux">
      <div className="bloc-tete">
        <h2>Ce qui peut aider</h2>
      </div>
      <div className="etapes">
        {replis.map((repli) => (
          <div className="etape" key={repli.titre}>
            <span className="km">→</span>
            <span className="nom">
              <b>{repli.titre}</b>
              {repli.detail ? <small>{repli.detail}</small> : null}
            </span>
            <button type="button" className="lien" onClick={repli.action}>
              Essayer
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

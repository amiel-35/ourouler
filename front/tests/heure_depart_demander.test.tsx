/** Backlog « Séance du jour à l'heure réelle » (2026-09-26) — QP3 : « Si on
 * bascule de Demain vers Aujourd'hui dans l'écran Demander, l'heure par
 * défaut se recalcule — elle ne reste pas gelée à ce qu'elle était au
 * chargement de la page. » Pour Demain/Après-demain, rien ne change
 * (non-régression).
 */

import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Demander, demandeInitiale, type Demande } from "../src/ecrans/Demander";
import { Serveur } from "./serveur";
import { PROFIL, meteo, ventDepart, zones } from "./fixtures";

function installerServeur() {
  const serveur = new Serveur({
    "/api/v1/vent-depart": { charge: ventDepart() },
    "/api/v1/meteo": { charge: meteo() },
  });
  serveur.installer();
  return serveur;
}

function Harnais({ initiale }: { initiale: Demande }) {
  const [demande, setDemande] = useState(initiale);
  return (
    <Demander
      profil={PROFIL.donnees}
      zones={zones().donnees}
      dureeSeance_s={null}
      nomSeance={null}
      demande={demande}
      budget={null}
      surDemande={setDemande}
      surChercher={() => undefined}
    />
  );
}

describe("le sélecteur « Quand » de Demander.tsx", () => {
  it("recalcule l'heure par défaut en choisissant « Aujourd'hui », même si elle était gelée sur un autre jour", async () => {
    const maintenant = new Date();
    maintenant.setHours(20, 3, 0, 0);
    vi.setSystemTime(maintenant);

    installerServeur();
    const utilisateur = userEvent.setup({ delay: null });
    // Départ sur « Demain », avec l'heure par défaut d'un autre jour (9 h) —
    // comme au chargement de la page un autre jour que celui du calcul.
    const initiale = { ...demandeInitiale(), heure_depart: "09:00" };
    render(<Harnais initiale={initiale} />);

    await utilisateur.click(screen.getByRole("button", { name: "Demain" }));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("09:00");

    await utilisateur.click(screen.getByRole("button", { name: "Aujourd'hui" }));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("20:15");

    vi.useRealTimers();
  });

  it("laisse l'heure inchangée en choisissant « Demain » ou « Après-demain » (non-régression)", async () => {
    installerServeur();
    const utilisateur = userEvent.setup();
    const initiale = { ...demandeInitiale(), heure_depart: "11:30" };
    render(<Harnais initiale={initiale} />);

    await utilisateur.click(screen.getByRole("button", { name: "Demain" }));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("11:30");

    await utilisateur.click(screen.getByRole("button", { name: "Après-demain" }));
    expect((screen.getByLabelText(/Départ à/) as HTMLInputElement).value).toBe("11:30");
  });
});

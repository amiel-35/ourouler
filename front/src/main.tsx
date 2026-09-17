import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Barriere } from "./composants/Barriere";
import "./style.css";

const racine = document.getElementById("application");
if (racine === null) throw new Error("le point de montage « application » est introuvable");

createRoot(racine).render(
  <StrictMode>
    <Barriere>
      <App />
    </Barriere>
  </StrictMode>,
);

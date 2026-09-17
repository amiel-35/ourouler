/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// L'API tourne à côté. En développement, Vite lui renvoie `/api` : le front
// n'a donc jamais d'URL absolue dans son code, et la même construction sert
// en production, où l'API et le front sont servis par la même origine.
const API = process.env.OUROULER_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": { target: API, changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/installation.ts"],
    include: ["tests/**/*.test.tsx", "tests/**/*.test.ts"],
  },
});

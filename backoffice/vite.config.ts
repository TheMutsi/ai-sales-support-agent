import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The admin API sends no CORS headers on purpose (ADR-0016), so the browser talks to the dev
// server and the dev server forwards `/api` to the backend.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "jsdom" },
});

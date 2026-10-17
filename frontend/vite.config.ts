import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// One self-contained script: a shop pastes a single <script src=".../mew.js?key=...">,
// so there are no chunks, no ES modules and no separate CSS file to load.
export default defineConfig({
  plugins: [react()],
  publicDir: "example", // example/index.html is copied next to mew.js so one server shows both
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    lib: {
      entry: "src/index.ts",
      name: "MewWidget",
      formats: ["iife"],
      fileName: () => "mew.js",
    },
    cssCodeSplit: false,
  },
  test: { environment: "jsdom" },
});

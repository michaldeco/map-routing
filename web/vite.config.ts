/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API (`map-routing api`) runs on this address; the dev server forwards /api to it,
// so the browser talks to one origin in development as in production.
const API_URL = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": API_URL },
  },
  build: {
    // MapLibre alone is about 1 MB minified (350 kB compressed). The app is the map,
    // so splitting it into lazily loaded chunks would not show anything sooner.
    chunkSizeWarningLimit: 1500,
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ holds Playwright's browser tests
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});

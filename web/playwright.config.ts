import { defineConfig } from "@playwright/test";

// Browser tests run against the production build (what users get), served by Vite's
// preview server. The API and the basemap are replaced in the tests themselves, so
// neither a running API nor internet access is needed.
const PORT = 4173;

export default defineConfig({
  testDir: "e2e",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    browserName: "chromium",
    // Software WebGL for headless Chromium (MapLibre needs WebGL).
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
  webServer: {
    command: `pnpm run build && pnpm exec vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
  },
});

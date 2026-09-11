// Phase 12 browser E2E: Playwright owns both server processes.
// Launched from the repository root. API on 127.0.0.1:8001, Expo web export
// served at http://localhost:8081 (the origin FastAPI's CORS policy allows).
// Both servers use reuseExistingServer: false so a run never attaches to an
// unrelated development server; an occupied port fails the run instead.
import * as path from "node:path";
import { defineConfig } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "..", "..");
// `uv run --directory` executes the child with apps/api as its cwd, so the
// static server needs an absolute --directory to serve the web export.

export default defineConfig({
  testDir: ".",
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  forbidOnly: process.env.CI !== undefined,
  reporter: [
    ["list"],
    [
      "html",
      {
        open: "never",
        outputFolder: path.join(repoRoot, "artifacts", "e2e", "web", "report"),
      },
    ],
  ],
  outputDir: path.join(repoRoot, "artifacts", "e2e", "web", "test-results"),
  use: {
    baseURL: "http://localhost:8081",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command:
        "uv run --directory apps/api uvicorn e2e.app:app --host 127.0.0.1 --port 8001",
      url: "http://127.0.0.1:8001/health",
      cwd: repoRoot,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        E2E_DATABASE_URL: process.env.E2E_DATABASE_URL ?? "",
      },
    },
    {
      command: `uv run --directory apps/api python -m http.server 8081 --bind 127.0.0.1 --directory ${path.join(repoRoot, "apps", "mobile", "dist-e2e")}`,
      url: "http://localhost:8081/",
      cwd: repoRoot,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});

# Phase 17 Cloudflare Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the existing web application for Pages and give the learner a complete manual deployment and acceptance guide.

**Architecture:** Pages hosts the existing static single-page Expo export. The browser calls Cloud Run directly using its existing public API URL and bearer-token contracts. Exact API origins are configured per Cloud Run revision.

**Tech Stack:** Expo 57.0.19, React Native 0.86.3, Node 24.20.0, pnpm 11.25.0, FastAPI, pytest, existing Playwright, Cloudflare Pages Git integration.

**Spec:** [Phase 17 design](../specs/2026-09-13-cloudflare-pages-design.md).

## Global constraints

- Planning documents only are complete; application implementation and manual acceptance remain pending.
- Work in `codex/phase-17-cloudflare-pages` at `.worktrees/phase-17-cloudflare-pages`, based on `eb7cf84`.
- Retain all existing dependency pins and the lockfile; add no dependencies.
- Preserve local `pnpm build:web`, local CORS defaults, native behavior, auth, and owner isolation.
- Do not run local E2E fixture/reset machinery against the deployed API or Cloud SQL.
- Pages project name, assigned production `pages.dev` hostname, actual preview alias, and final API origin are deployment inputs copied from the learner's resources.
- Do not commit tokens, secret URLs, generated exports, environment files with credentials, or unredacted browser traces.
- No cloud mutations during repository implementation; the learner executes the guide.
- Route mechanical implementation to Luna; escalate integration issues to Terra; use Sol medium for significant/final review under project instructions. Do not broaden architecture without returning the issue to the controller.

## File ownership and order

| Task | Files | Responsibility |
| --- | --- | --- |
| 1 | `apps/api/app/cors.py`, `apps/api/app/main.py`, `apps/api/tests/test_cors.py`, `apps/api/tests/test_health.py`, `apps/api/.env.example` | Exact configurable API origin policy |
| 2 | `scripts/build-pages.mjs`, `tests/build-pages.test.mjs`, `package.json`, `apps/mobile/public/_headers`, `.github/workflows/quality.yml` | Validated hosted export and static headers |
| 3 | `docs/guides/17-cloudflare-pages.md`, `README.md` | Complete manual deployment handoff and honest status |

Tasks 1 and 2 are independent. Task 3 consumes both. No new router, client abstraction, or backend proxy is needed.

## Task 1: Exact CORS configuration

**Interfaces:** `get_cors_origins() -> list[str]` in `app.cors`; consumes `CORS_ALLOWED_ORIGINS` JSON and returns the complete replacement allowlist. Called by `create_app()`, not cached globally.

- [ ] Write focused tests in `apps/api/tests/test_cors.py`. Use pytest monkeypatch to set/unset the variable before constructing the app; use the health endpoint to avoid database queries.

```python
@pytest.mark.parametrize("origin", [
    "https://project.pages.dev",
    "https://trusted.example.pages.dev",
])
def test_configured_origin_preflight(monkeypatch, origin):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", json.dumps([origin]))
    with TestClient(create_app()) as client:
        response = client.options("/todos", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers
```

- [ ] Cover unset default, explicit empty array, two origins, localhost excluded when configured, unlisted preview, deceptive suffix, rejected preflight, missing allow-origin on a simple GET, and non-CORS health requests. Parameterize malformed JSON, scalar/object JSON, non-string entries, `*`, HTTP external hosts, userinfo, paths, trailing slash, query, fragment, spaces, invalid port, and empty string. Assert a generic `ValueError` without reflecting the value.
- [ ] Run `uv run --directory apps/api python -m pytest tests/test_cors.py tests/test_health.py -q`; confirm the new configured-origin case fails against the old fixed allowlist.
- [ ] Implement the parser with stdlib JSON and URL parsing. The following is the contract implementation; retain tests as the authority on edge cases:

```python
import json
import os
from urllib.parse import urlsplit

LOCAL_ORIGIN = "http://localhost:8081"


def get_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if raw is None:
        return [LOCAL_ORIGIN]
    try:
        origins = json.loads(raw)
        if not isinstance(origins, list):
            raise ValueError
        for origin in origins:
            if not isinstance(origin, str):
                raise ValueError
            parsed = urlsplit(origin)
            _ = parsed.port
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment
                or "?" in origin or "#" in origin
                or "*" in origin or "\\" in origin
                or any(c.isspace() or ord(c) < 32 for c in origin)
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or (parsed.scheme != "https" and origin != LOCAL_ORIGIN)
            ):
                raise ValueError
        return list(dict.fromkeys(origins))
    except (ValueError, TypeError):
        raise ValueError("Invalid CORS_ALLOWED_ORIGINS configuration") from None
```

- [ ] Import `get_cors_origins` in `app/main.py`, replace `allow_origins=[EXPO_WEB_ORIGIN]` with `allow_origins=get_cors_origins()`, remove the unused constant, and leave credentials/method/header policy unchanged.
- [ ] Make the existing health test fixture explicitly unset this variable using monkeypatch, so an operator's shell cannot change test expectations. Add the documented example `CORS_ALLOWED_ORIGINS=["http://localhost:8081"]` to `apps/api/.env.example`, noting that the API process must receive the environment variable; the example file is not automatically loaded by this change.
- [ ] Run focused tests and `pnpm lint:api`. Then run the existing API suite with its dedicated PostgreSQL test database. Distinguish infrastructure errors from assertions.
- [ ] Commit only Task 1 files: `feat: configure exact browser origins for hosted web`.

## Task 2: Hosted export and headers

**Interfaces:** `pnpm build:pages` consumes `EXPO_PUBLIC_API_URL`, rejects invalid hosted targets, runs existing `build:web` with `EXPO_NO_DOTENV=1`, and emits `apps/mobile/dist`. Existing clients and local build entry points are unchanged.

- [ ] Create a dependency-free Node entry point `scripts/build-pages.mjs`, exporting `validateApiOrigin(value)` for tests. Separate validation from process execution using the standard direct-entry check. Throw a generic error for invalid values; do not print the supplied value.

```javascript
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

export function validateApiOrigin(value) {
  try {
    if (!value || value.trim() !== value) throw new Error();
    const url = new URL(value);
    const host = url.hostname;
    if (url.protocol !== "https:" || url.username || url.password ||
        url.pathname !== "/" || url.search || url.hash ||
        value.includes("?") || value.includes("#") ||
        host === "localhost" || host.endsWith(".localhost") ||
        host === "[::1]" || host.startsWith("127.") || host === "0.0.0.0" ||
        (value !== url.origin && value !== `${url.origin}/`)) throw new Error();
  } catch {
    throw new Error("EXPO_PUBLIC_API_URL must be a non-loopback HTTPS origin");
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    validateApiOrigin(process.env.EXPO_PUBLIC_API_URL);
    const result = spawnSync("pnpm", ["build:web"], {
      stdio: "inherit",
      env: { ...process.env, EXPO_NO_DOTENV: "1" },
    });
    process.exitCode = result.status ?? 1;
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
```

- [ ] Add Node built-in tests before implementing validation, run to observe failure, then implement. Include a successful origin and optional trailing slash, missing value, HTTP, local/IPv4/IPv6 loopback, credentials, query, fragment, path, malformed URL, and leading/trailing whitespace.

```javascript
import test from "node:test";
import assert from "node:assert/strict";
import { validateApiOrigin } from "../scripts/build-pages.mjs";

test("accepts hosted origin", () => {
  assert.doesNotThrow(() => validateApiOrigin("https://api.example.test"));
});
for (const value of [undefined, "", "http://api.example.test", "https://localhost",
  "https://127.0.0.1", "https://[::1]", "https://user:secret@api.example.test",
  "https://api.example.test/path", "https://api.example.test?key=secret",
  "https://api.example.test#fragment", "not a url", " https://api.example.test"]) {
  test(`rejects invalid target ${String(value).length}`, () => {
    assert.throws(() => validateApiOrigin(value), /non-loopback HTTPS origin/);
  });
}
```

- [ ] Add root scripts `"build:pages": "node scripts/build-pages.mjs"` and `"test:pages": "node --test tests/build-pages.test.mjs"`.
- [ ] Create `apps/mobile/public/_headers` with the exact content in the spec. Do not add `_redirects` or `404.html`; verify exported assets and native Pages fallback instead.
- [ ] Run `pnpm test:pages`. Confirm `env -u EXPO_PUBLIC_API_URL pnpm build:pages` exits nonzero before Expo runs. Run `EXPO_PUBLIC_API_URL=https://api.example.test pnpm build:pages` and inspect `apps/mobile/dist/index.html`, JS assets, and the copied `_headers` file. The example target is for export verification only, never a deployed acceptance target.
- [ ] In the quality workflow, add `pnpm test:pages` after dependencies are installed. After the existing web export verification, run the hosted build with `EXPO_PUBLIC_API_URL: https://api.example.test` and verify `test -f apps/mobile/dist/index.html` and `cmp apps/mobile/public/_headers apps/mobile/dist/_headers`. Preserve the existing local web build and E2E checks.
- [ ] Run `pnpm lint:mobile`, `pnpm typecheck`, and the existing local `pnpm test:e2e:web` using its dedicated test environment. No cloud keys or deployment permissions belong in CI.
- [ ] Commit only Task 2 files: `feat: prepare validated Expo export for Cloudflare Pages`.

## Task 3: Numbered manual guide and status

**Interfaces:** Produce `docs/guides/17-cloudflare-pages.md` for the learner; README links it as code-ready/manual-acceptance-pending, never complete before results arrive.

- [ ] Write numbered steps with commands and console fields for this exact sequence:
  1. Verify Phase 16 API signup/todos and record current revision, image digest, traffic, Cloud SQL attachment, secret reference versions, and intended Pages project and assigned `pages.dev` hostname.
  2. Run repository verification and local hosted export. Explain build-time public configuration and show the Pages settings table from the spec.
  3. Build/push the API image from `apps/api` for `linux/amd64` and resolve an immutable digest using the Phase 14 pattern.
  4. Generate a non-secret YAML env file containing a JSON string for `CORS_ALLOWED_ORIGINS`. Read existing non-secret env configuration first: `--env-vars-file` replaces normal variables, so preserve all of them, including any `OPENROUTER_MODEL`; secret references remain separately configured. Prefer a documented alternate-delimiter `--update-env-vars` command to change only CORS. For example, `--update-env-vars='^|^CORS_ALLOWED_ORIGINS=["https://project.pages.dev"]'`; clearly label examples and substitute observed origins. Do not dump plaintext secrets while inspecting configuration.
  5. Deploy the API candidate with `--no-traffic --tag=web-v1`, preserve database/secrets, verify preflight against its tag, then explicitly promote it so the stable URL uses the new policy. Record rollback target before promotion.
  6. Create a Pages Git-integrated project scoped to this repository. Configure production/preview environments separately, tool pins, skipped automatic install, root build command, output path, main production branch, and trusted preview branch controls.
  7. Build the implementation branch preview, copy the actual branch-alias URL, and inspect build logs/network calls. Explain that the initial main deployment may still be pre-Phase-17 code.
  8. Run the denied-preview exercise with OPTIONS requesting POST and Authorization/Content-Type. In a browser confirm blocked response access. Update the API allowlist with only that exact preview alias, deploy/promote a fresh revision, and retest in a fresh browser context to avoid preflight-cache confusion.
  9. Execute the preview acceptance journey in A8/A9 with disposable accounts and a bounded live AI request. Reuse normal application operations, not E2E fixtures. Verify AG-UI streaming through the browser boundary.
  10. Ask the learner for implementation PR merge when preview/CI evidence is ready; merge only with authorization. Verify Pages then builds the intended main commit and repeat the journey on production.
  11. Verify the assigned production `pages.dev` hostname, certificate validity, and HTTP-to-HTTPS behavior. Record its exact origin and confirm it is allowed by API CORS. The learner explicitly chose `pages.dev`; do not require a custom domain or DNS changes for A5.
  12. Inspect HTTPS redirect, headers, real JS MIME types, root refresh, unmatched-path fallback, preview noindex, and fresh deployment cache behavior using browser devtools plus `curl -I` against observed URLs.
  13. Make two successful production deployments identifiable by commit and deployment ID; use a harmless guide-only commit for the second if needed. Roll back to the first in Pages, verify selected production deployment identity, then restore the second. Do not invent visible app version labels just for this exercise.
  14. Remove temporary preview origins in a fresh API revision and promote; verify denied preflight, final production success, and cleanup of disposable todos. Record any account-retention limitation rather than adding an account deletion API.
  15. Fill A1–A12 evidence rows and note shared sandbox data, cost settings, assigned Pages hostname, final image/revision/deployment IDs, rollback observations, and remaining gaps.
- [ ] Include troubleshooting for wrong build root/output, tool-version mismatch, localhost baked into JS, API target changes requiring rebuild, missing Authorization preflight headers, Pages hostname/certificate availability, API errors versus browser CORS errors, and inactive Cloud Run revisions requiring a tag.
- [ ] Explain Pages rollback and Cloud Run rollback are independent; neither performs database rollback. Direct hosted browser acceptance is manual, not the local Playwright suite retargeted to the cloud.
- [ ] Update README with spec/plan/guide links and explicitly pending cloud acceptance. Preserve earlier acceptance caveats. Do not mark Phase 17 complete or Phase 18 next until the learner reports required checks passed.
- [ ] Run `pnpm lint:markdown`, `pnpm lint:links`, and `git diff --check`. Resolve errors introduced by these files; report environmental failures separately.
- [ ] Commit: `docs: add Phase 17 manual Pages deployment guide`.

## Final review and manual handoff

- [ ] Review all implementation changes against A1–A12; check exact origin matching, fail-closed malformed configuration, preserved secret mappings, preview trust, and no new native dependencies.
- [ ] Run repository quality and existing web E2E checks once after integration. Record results and any missing prerequisites accurately.
- [ ] Obtain final whole-branch review under the project model routing. Fix actionable findings and rerun affected checks.
- [ ] Deliver the numbered guide, branch/worktree, relevant checks, and deployment-time inputs. Stop before cloud mutations: the learner requested a manual walkthrough.
- [ ] After learner-reported acceptance, update the evidence record and README without inventing observed values. Commit/push/merge only when authorized for that step.

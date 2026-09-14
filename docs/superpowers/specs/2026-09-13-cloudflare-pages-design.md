# Phase 17: Cloudflare Pages design

## Status and outcome

Implementation authorized by the learner on 2026-09-14; repository preparation is implemented and reviewed; cloud acceptance remains pending. Phase 16 is merged at `eb7cf84`. This phase serves the existing Expo web app from Cloudflare Pages and connects browser requests directly to the Cloud Run API backed by Cloud SQL. The learner performs cloud configuration, deployment, and acceptance manually after repository preparation.

## Decisions and alternatives

Use Pages Git integration with the repository root as the build root and `main` as the production branch. This teaches the monorepo build and preview boundary already specified by the curriculum. Manual Direct Upload would avoid a Git integration but omit the intended build/preview lesson. A Worker or Pages Function proxy would add another backend boundary without a requirement; retain direct browser-to-Cloud-Run requests.

Keep the current single-page Expo application. It registers `App` directly and has no Expo Router or URL-addressable todo screens. Do not introduce a router for a hosting phase. Pages' native SPA fallback serves the shell at otherwise unmatched paths; this is not support for navigating directly to a particular todo.

## Existing contracts

- Expo `57.0.19`, React Native `0.86.3`, Node `24.20.0`, pnpm `11.25.0`; retain existing dependency pins and lockfile.
- `pnpm build:web` exports `apps/mobile/dist`; keep it usable for existing local and CI workflows.
- `EXPO_PUBLIC_API_URL` already supplies API clients and AG-UI. It is public, compiled into the browser bundle, and must be set before export.
- API `create_app()` currently permits only `http://localhost:8081` through CORS, with bearer Authorization and no cookie credentials.
- Phase 12 Playwright owns local servers and database fixtures. Do not point that suite at Cloud SQL or add test reset endpoints to the deployed app.
- Cloud SQL credentials and OpenRouter keys remain server-side secrets. No authentication redesign or native iOS distribution is included.

## Build and environment contract

Add `pnpm build:pages` as a hosted-build entry point. Validate that `EXPO_PUBLIC_API_URL` is an HTTPS origin without credentials, path (other than `/`), query, or fragment. Reject missing, malformed, and loopback targets. Print a generic error without echoing a supplied value. Run Expo with dotenv loading disabled so local files cannot override Pages configuration. Reuse `pnpm build:web` after validation. Clear Metro caches on both the shared web export and direct E2E export so changing the build-time API target cannot reuse a previous target.

Pages settings:

| Setting | Value |
| --- | --- |
| Git repository | `tylervsd/expo-fastapi-todo` |
| Root directory | Repository root |
| Production branch | `main` |
| Framework preset | None |
| Build command | `pnpm install --frozen-lockfile && pnpm build:pages` |
| Output directory | `apps/mobile/dist` |
| `NODE_VERSION` | `24.20.0` |
| `PNPM_VERSION` | `11.25.0` |
| `SKIP_DEPENDENCY_INSTALL` | `true` |
| `EXPO_PUBLIC_API_URL` | Verified stable Cloud Run service origin, configured separately for production and preview |

Check tool versions in the first Pages build log. If the build image cannot supply a pinned version, stop and resolve the build environment without silently changing repository pins. No private registry credentials or application secrets are needed. Restrict the Git integration to this repository and preview builds to trusted branches.

The sandbox uses one API/database for both Pages environments, explicitly documented as shared test data. Production here means the Pages production deployment, not a separately provisioned production backend. Use disposable accounts. Do not connect unreviewed preview code to real user data.

## Exact CORS policy

Introduce `CORS_ALLOWED_ORIGINS`, a JSON array of exact origins. Read it at app construction so tests and new revisions receive the selected policy. When unset, preserve the local default `http://localhost:8081`. An explicitly empty array denies all browser origins; malformed values fail app construction with a generic configuration error. Hosted deployments must set this variable explicitly and exclude localhost.

Accept HTTPS origins and the exact local development origin. Reject wildcards, regexes, credentials, paths including trailing slash, query, fragment, whitespace, invalid ports, and non-string list entries. Do not infer trust from `Origin`, a hostname suffix, or all `pages.dev` sites. Keep the existing methods, headers, and `allow_credentials=False`.

Allow the exact assigned Pages production origin (`https://<project>.pages.dev`). The preview exercise begins with its exact origin absent. Confirm browser rejection, then add only the selected trusted branch alias copied from the Pages deployment UI. Hash preview URLs remain disallowed unless explicitly listed. Removing that alias must revoke browser access again.

CORS governs browser access to responses; it is not authentication or protection against non-browser clients. Existing API auth and owner isolation continue to enforce access. Negative checks must inspect preflight and response headers; a denied simple GET can still return HTTP 200 without an allow-origin header.

## Static hosting, headers, and caching

Add `apps/mobile/public/_headers`, copied by Expo into the export:

```text
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: frame-ancestors 'none'; base-uri 'self'; object-src 'none'
```

This is a deliberately limited CSP, not a comprehensive script-source policy. Avoid an untested full CSP that breaks React Native Web styles or AG-UI connections. A stricter source policy is outside this phase. Do not add CORS headers to frontend assets as a substitute for API CORS.

Retain native Pages caching and SPA fallback. No top-level `404.html`, service worker, catch-all `_redirects`, or custom cache rules are required. Verify real asset requests return their correct MIME types, the root shell reloads, and `/phase17-refresh-check` loads the shell rather than a server 404. A refresh restores the existing app/auth behavior, not an invented URL route.

## Pages hostname and TLS

The learner chose the assigned Cloudflare `pages.dev` hostname for Phase 17. Copy the exact production hostname from the created Pages project; the project name is a deployment-time input. Verify HTTPS, certificate validity, and HTTP-to-HTTPS behavior on that hostname. Keep production and preview aliases distinct in configuration and evidence.

This explicitly narrows the provisional roadmap's custom-origin requirement: domain purchase, custom DNS records, nameserver changes, and custom-domain acceptance are out of scope. They are optional later exercises, not outstanding Phase 17 acceptance gaps. Exact production and preview CORS policies still apply.

## Deployment sequence and rollback

1. Implement and locally verify the repository changes; produce `docs/guides/17-cloudflare-pages.md` before the learner starts.
2. Build/push a Phase 17 API image containing configurable CORS. Capture the current image, revision, traffic, and non-secret configuration. Preserve Cloud SQL attachment and both existing secret references.
3. Deploy a tagged Cloud Run candidate with the exact production Pages origin. Validate it and promote it before testing against the stable service URL. A tagged revision alone does not change which revision the stable service URL reaches.
4. Connect Pages to Git, build a trusted branch preview, inspect the embedded API destination, and perform the denied-origin exercise. Add the specific preview origin through a new API revision and promote after checking it.
5. Verify the preview end-to-end before authorizing the implementation PR merge. Pages may have created an initial production deployment from the older `main`; do not count it as acceptance of this phase.
6. After merge, verify the production Pages deployment on its assigned `pages.dev` hostname. Git-driven deployment does not itself enforce GitHub check success; protected-main PR checks remain the merge gate.
7. Exercise a frontend rollback between two successful production deployments using Pages' native rollback, record their IDs/commits, then restore the intended release. Do not roll back a database or disable auth.
8. If API CORS breaks, restore the previously recorded Cloud Run revision/traffic; the previous API may lack hosted-origin support, so this restores prior service behavior rather than guaranteeing hosted frontend availability.

## Acceptance record

Every row starts unverified. Record observed date, URL/origin, commit/image digest or deployment ID, result, and redacted evidence. Do not mark completion based solely on CI or resource creation.

| ID | Required evidence |
| --- | --- |
| A1 | Invalid/missing hosted API target fails before export; valid target builds; public output contains the intended target and no server secrets |
| A2 | Pages preview and production builds use pinned tools, frozen lockfile, correct root/output, and separately configured API targets |
| A3 | Existing local CORS behavior passes; hosted allowlist excludes localhost and rejects unrelated, deceptive-suffix, and unlisted preview origins |
| A4 | Real browser denied-preview failure, exact-origin grant, success, and removal/rejection are observed |
| A5 | Assigned production `pages.dev` origin loads over HTTPS; certificate and HTTP redirect behavior are verified; preview and production deployments are distinguished |
| A6 | Root refresh and unmatched-path shell fallback work; JS/CSS assets have correct content types; no browser console regressions |
| A7 | Headers are present, preview has noindex, and a fresh deployment/refresh loads the intended asset version without stale-page errors |
| A8 | Hosted signup, login, todo create/edit/complete/delete, reload persistence, sign-out, and second-user isolation pass |
| A9 | Hosted guided workflow and AI suggestion/AG-UI stream complete with explicit confirmation; cancellation and refresh/resume preserve existing semantics |
| A10 | Existing local Playwright suite and repository quality checks pass; native behavior is unchanged by web-only configuration |
| A11 | Pages production rollback and restoration of the intended deployment are observed and recorded |
| A12 | Temporary preview origins removed, test data cleaned through normal app operations, final API/Pages state and recurring costs recorded |

## Scope boundaries

No Pages Functions, Workers, SSR, Expo Router adoption, auth changes, new production database, frontend secrets, native distribution, Terraform, or new GitHub deployment pipeline. Phase 18 owns infrastructure as code. The manual guide separates code-ready from cloud-accepted status and never claims a hosted origin or deployed test has passed before observation.

## References

- [Expo web export and public assets](https://docs.expo.dev/guides/publishing-websites/)
- [Pages monorepos](https://developers.cloudflare.com/pages/configuration/monorepos/)
- [Pages build image and version overrides](https://developers.cloudflare.com/pages/configuration/build-image/)
- [Pages preview aliases](https://developers.cloudflare.com/pages/configuration/preview-deployments/)
- [Pages SPA fallback and caching](https://developers.cloudflare.com/pages/configuration/serving-pages/)
- [Pages headers](https://developers.cloudflare.com/pages/configuration/headers/)
- [Pages rollback](https://developers.cloudflare.com/pages/configuration/rollbacks/)

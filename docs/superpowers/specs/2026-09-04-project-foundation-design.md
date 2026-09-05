# Phase 1: Project Foundation Design

**Status:** Design sections approved; written specification awaiting review

**Date:** 2026-09-04

**Repository:** `tylervsd/expo-fastapi-todo`

**Starting checkpoint:** `phase-00-environment`

**Completion checkpoint:** `phase-01-foundation`

## Purpose

Phase 1 establishes the tutorial's first runnable application boundary. A learner runs an Expo TypeScript app on the web and in the iOS Simulator, runs FastAPI in a second host terminal, and sees whether the service satisfies a small health contract. The phase teaches workspace ownership, browser CORS, explicit client states, service contracts, and baseline application CI without adding product behavior.

## Baseline and implementation precondition

Phase 0 is complete at the annotated `phase-00-environment` tag, which contains the root tool pins, pnpm workspace, doctor, documentation checks, tests, CI, and setup guide. The current local checkout may contain only earlier planning documents. Phase 1 implementation must reconcile the checkout with the completed checkpoint instead of recreating Phase 0, and Phase 1 history must descend from that tag.

Implementation planning will verify Expo and native-runtime compatibility with the Phase 0 Node and Xcode/iOS environment, and FastAPI tooling compatibility with the Phase 0 uv-managed Python. Exact framework, test-library, and native-runtime versions are implementation decisions recorded in lockfiles after verification; this design does not invent them.

## Goals and non-goals

Phase 1 will:

1. Add one Expo TypeScript screen that runs on web and the reference iOS Simulator.
2. Add a uv-managed FastAPI app with one health endpoint.
3. Show deterministic connecting, connected, and unavailable states.
4. Expose separate named root commands for Expo and FastAPI.
5. Extend the Phase 0 quality gate with frontend, API, and web-export checks.
6. Document setup, startup, verification, recovery, and the manual journey.

It will not add todos, persistence, a database, authentication, authorization, a generated API client, deployment, physical-device support, or automated browser/iOS E2E tests. It will not run application processes in Docker or add Docker Compose, a process supervisor, or a combined long-running startup command. Android may remain scaffold-compatible but is neither documented nor accepted in this phase.

## Repository and runtime architecture

```text
apps/
  mobile/   Expo and React Native TypeScript app
  api/      FastAPI app, tests, pyproject.toml, and uv.lock
docs/guides/
  01-project-foundation.md
```

The existing root pnpm workspace owns JavaScript installation, lock resolution, and quality commands. `apps/mobile` is a pnpm workspace package. `apps/api` owns its Python dependencies and lock; all Python execution goes through uv and preserves the Phase 0 managed-interpreter contract.

The root exposes two stable commands: `pnpm dev:mobile` starts Expo for web or iOS, and `pnpm dev:api` starts FastAPI at the documented local address. Learners keep both processes and their logs visible in separate host terminals. Neither command supervises the other.

The checked-in mobile environment example contains:

```dotenv
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

The Expo web server uses the documented origin `http://localhost:8081`, and FastAPI allows that exact origin. CORS does not use a wildcard. Stable documented ports keep the browser origin and API URL aligned; port conflicts receive direct remediation rather than silently changing ports. The guide explains that `EXPO_PUBLIC_` values are visible to clients and must not contain secrets.

## API contract

FastAPI exposes side-effect-free `GET /health` with no authentication, parameters, body, or database dependency. A healthy response is HTTP `200` with exactly:

```json
{"status":"ok"}
```

The API explicitly grants CORS permission to `http://localhost:8081`, including required preflight behavior. An unlisted origin is not granted permission. iOS consumes the same URL and response contract but does not rely on browser CORS enforcement.

## Mobile screen and state model

The shared web/iOS screen contains a project heading, a brief explanation, and the current API result. On mount it immediately shows **Connecting** and starts one request. It shows **Connected** only after HTTP `200` and JSON matching the health contract. A network error, five-second timeout, non-`200` response, invalid JSON, or unexpected body produces **Unavailable**, a short user-readable explanation, and a Retry button.

Retry is available from both Connected and Unavailable. It starts exactly one new attempt and returns the screen to Connecting, where Retry is disabled or hidden until the attempt settles. Connected describes the last successful check; stopping the API does not change the screen until the learner checks again. There is no polling, background retry, backoff, or periodic refresh.

Each attempt has its own cancellation signal and identity. Unmounting cancels the active request. A newer attempt invalidates an older one, and an invalidated or cancelled completion cannot overwrite current state. The timeout is cleared when the attempt settles or is cancelled. User-facing errors never expose stack traces.

Network work sits behind a small health-check boundary instead of presentation code. The screen owns visible state transitions; the boundary owns URL construction, the timeout, cancellation, JSON parsing, and response validation. Tests can control outcomes without starting FastAPI.

## Local workflow and documentation

After Phase 0 setup, a learner installs root JavaScript dependencies, syncs the API environment through uv, and copies the mobile environment example to the documented ignored local file. In two terminals they run `pnpm dev:api`, then `pnpm dev:mobile`, and select web or iOS from Expo.

`docs/guides/01-project-foundation.md` explains boundaries, dependency ownership, configuration, two-terminal startup, expected states, direct health diagnosis, tests, web export, and common recovery steps. It contains the complete manual journey and explains browser CORS. The README advances the current checkpoint to Phase 1 and links the guide. The roadmap is changed only where its provisional Phase 1 description conflicts with this design, including removal of Docker Compose from Phase 1. Phase 0 documentation remains available.

## Testing and CI

FastAPI tests run in-process and prove that `/health` returns the exact status and JSON contract without database or authentication setup. They also prove that the configured Expo origin receives the expected CORS permission or preflight response and that an unlisted origin does not.

Expo tests use controlled health-check outcomes and timers. They cover initial Connecting, Connected on a valid response, Unavailable for timeout/network/non-`200`/malformed or unexpected responses, Retry from either Connected or Unavailable starting one new attempt, recovery after Retry, stale-response protection, and cancellation without a later state update on unmount. They do not use wall-clock waits or a live API.

The existing Phase 0 workflow and all its checks remain active. CI adds mobile lint, TypeScript type checking, Expo component tests, API lint and tests, and a non-interactive Expo web export. The export is a build compatibility check, not E2E. CI does not require a simulator in this phase, and third-party Actions remain pinned by full commit SHA.

## Manual acceptance

Run this journey on both the browser target and the designated iOS Simulator:

1. Start FastAPI and Expo in separate terminals.
2. Open the app and observe Connecting followed by Connected.
3. Stop FastAPI, select Retry, and observe Unavailable with a short explanation.
4. Restart FastAPI, select Retry, and observe Connecting followed by Connected.

Calling `/health` directly may aid diagnosis but does not replace either journey. Browser and simulator E2E automation is deferred.

## Acceptance criteria

Phase 1 is complete when:

1. Its history descends from `phase-00-environment` and preserves Phase 0 checks and docs.
2. `apps/mobile` renders the approved screen on web and the reference iOS Simulator.
3. `apps/api` is uv-managed with committed dependency metadata and lock data.
4. `GET /health` returns HTTP `200` and exactly `{"status":"ok"}`.
5. FastAPI explicitly allows the documented Expo browser origin and not an unlisted origin.
6. The screen implements all three states, five-second timeout, manual Retry, validation, cancellation, and stale-response protection without polling.
7. Root commands start Expo and FastAPI separately in two host terminals.
8. The approved API and Expo tests pass.
9. CI retains Phase 0 checks and passes frontend lint, typecheck, component tests, API lint/tests, and web export.
10. The guide, README, and roadmap accurately describe the implemented scope and workflow.
11. The recovery journey passes on both web and the reference iOS Simulator.
12. The annotated `phase-01-foundation` tag is created only after CI passes and both manual journeys are recorded successful.

## Sources

- [Expo environment variables](https://docs.expo.dev/guides/environment-variables/)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)

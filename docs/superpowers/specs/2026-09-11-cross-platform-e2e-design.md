# Phase 12: Cross-platform E2E Design

**Status:** Draft for review; Playwright/Maestro direction accepted. This document and its implementation plan are the requested planning deliverables, not evidence of implemented or passing tests.

**Base:** Phase 11 and its acceptance follow-up; existing Jest, pytest, and quality workflows remain in place.

**Checkpoint:** `phase-12-cross-platform-e2e` only after implementation, platform acceptance, integration, and successful CI.

## Goal

Prove a thin set of signed-in journeys through the actual Expo application,
FastAPI HTTP endpoints, and PostgreSQL on Chromium and iOS Simulator.
Provider results are deterministic, while application validation, AG-UI event
encoding, streaming transport, workflow transitions, and persistence stay real.
This phase teaches test isolation, stable UI selectors, native build setup,
failure diagnosis, and the distinction between component and E2E coverage.

## Decisions and boundaries

Use `@playwright/test` with TypeScript for Expo web and Maestro YAML flows for
iOS Simulator. Keep the existing Jest/React Native Testing Library and pytest
suites as the primary coverage for edge cases. Do not introduce a wrapper
framework or a common language for browser and native UI actions.

- Chromium only initially; no browser/device matrix.
- Three journey families on each platform, with AI direct and agent variants.
- Web runs on pull requests and pushes to `main`; iOS runs on pushes to `main` and manual dispatch.
- Real HTTP, authentication, PostgreSQL, migrations, and application AG-UI streams.
- No live model calls, production credentials, paid test service, or EAS account required.
- No new production API route, authentication bypass, test-mode environment switch, or provider abstraction.
- Preserve current dependency pins: Node 24.20.0, pnpm 11.25.0, Python 3.14.7, uv 0.12.1, Expo 57.0.19, React Native 0.86.3, and PostgreSQL 18.6.
- Resolve and exact-pin Playwright and Maestro during the compatibility task; record the tested Xcode, macOS runner, Simulator runtime, Java, and CocoaPods versions before declaring native CI ready.

Android, physical devices, Safari certification, performance testing, pixel
snapshots, full screen-reader auditing, and comprehensive race/fault injection
are outside this phase. Existing concurrency/idempotency tests remain required;
these E2E tests do not independently prove all such guarantees.

## Harness architecture

Create a test-only package at `apps/api/e2e/`. Its FastAPI entry point calls
`create_app(suggestion_callable=..., agent_choice=...)`, reusing the existing
credential-free seams. Normal `app.main:app` remains unchanged. Both injected
callables are mandatory so neither path can accidentally fall back to OpenRouter.
The entry point refuses any database except the explicitly configured E2E target.
It does not load application `.env` files.

The deterministic choice returns `constraints`. Suggestions return three titles:
`Gather supplies`, `Prepare workspace`, and `Complete the task`. The callable
accepts the existing optional clarification argument and validates the fixture's
expected `constraints` answer (`Use supplies already available`) when present.
An unexpected fixture input fails visibly instead of contacting a real provider.
No mutable process-global scenario registry, sleeps, or scripted SSE replay is
needed: real application code produces the stream with dynamic request IDs.

A small host-side Python CLI provides `prepare`, `seed`, and `assert-todos`.
`prepare` validates the SQLAlchemy URL before connecting, verifies
`current_database()`, and applies Alembic `head`. Allow only
`postgresql+psycopg`, loopback host, database/user `todo_e2e`, no URL query
parameters, and an explicitly supplied `E2E_DATABASE_URL`; never fall back to
`DATABASE_URL` or `TEST_DATABASE_URL`. Reject the development and pytest targets.
The E2E entry point uses the same validation. Do not log URL passwords.

`seed` creates a fresh username using `/auth/signup` and returns synthetic
credentials. `assert-todos` signs in via `/auth/login` and compares sorted title
and completion pairs from `/todos` against an expected JSON list, including
cardinality. No direct row insertion, truncation, or cleanup HTTP endpoint.
Each case and retry has its own account; browser/native suites never share one.
Fresh users isolate data without destructive resets. Locally, remove only the
dedicated E2E service when cleanup is desired.

Add a PostgreSQL `db-e2e` Compose profile using `todo_e2e`, loopback port 5434,
and ephemeral storage, separate from both `db` and `db-test`. Linux CI uses an
isolated service container. macOS CI starts local PostgreSQL without Docker
service containers, creates the same dedicated role/database, and records the
actual server version. Provision PostgreSQL 18.6 explicitly; if unavailable on
the selected runner, report the compatibility blocker instead of silently
substituting a different major/minor version.

## Web execution

Export Expo web with `EXPO_PUBLIC_API_URL=http://127.0.0.1:8001` and
`EXPO_NO_DOTENV=1`. Serve that export at `http://localhost:8081`, preserving
FastAPI's existing allowed CORS origin. A standard-library static server is
sufficient for the current single-screen app. Playwright owns the static server
and test API subprocesses through `webServer`, with `reuseExistingServer: false`.
Fail on occupied ports; do not attach to or kill an unrelated development server.

Start with one worker and zero retries. Each test receives a fresh browser
context and account. Prefer `getByRole` and `getByLabel` using existing accessible
names. Use scoped locators and exact matching where labels collide; add a stable
`testID` only after reproducing a native selector ambiguity. No CSS/layout
selectors, coordinates, arbitrary sleeps, or forced clicks.

## iOS execution

Use an app-specific unsigned Simulator Release build with bundled JavaScript,
not Expo Go. Set the iOS bundle identifier to `dev.codex.fullstack.todo` in Expo
configuration. Generate the native iOS project through Expo prebuild; ignore
native build output and keep generation reproducible. Verify the installed CLI's
build flags and native workspace/scheme during the first task, then record exact
commands in the guide and script. Do not commit generated native sources merely
for E2E automation.

Build with the same API URL and dotenv suppression as web. Validate loopback
HTTP connectivity in the Release build; if native transport policy blocks it,
use a narrowly scoped Expo configuration change and document it. Never disable
transport security globally to make a test pass.

The wrapper selects an explicit available Simulator UDID, installs the app,
starts the fixture API, waits for readiness, seeds the account, and invokes each
Maestro flow with `APP_ID`, `USERNAME`, and `PASSWORD`. First launch for each
case clears app state and keychain using supported commands verified in the
compatibility task. If reset cannot guarantee a clean session, use a dedicated
fresh Simulator. A resume test terminates and relaunches without clearing state.
Only stop/delete resources created by that invocation; preserve an existing
user Simulator and unrelated services.

Maestro uses accessible text/identifiers, scrolling, and bounded visibility
waits. Capture the native hierarchy when a label fails; fix accessibility
semantics minimally if needed. Assert final database state with the same Python
CLI used by browser setup. For pre-confirmation checks, split the native flow
into preparation and confirmation files, with a host-side API assertion between
them. This avoids adding test-control APIs or embedding a second HTTP client in
Maestro JavaScript.

## Required journeys

Every case signs in through the UI using a newly seeded account and ends with
sign-out, asserting the sign-in UI and absence of the prior user's todo content.
The core case additionally signs in as a second fresh user and observes an empty
list. API checks use separate real sessions and never inject browser/native tokens.

| Family | UI actions on both platforms | Required assertions |
| --- | --- | --- |
| Core todo | Sign in; add `Buy milk`; rename to `Buy oat milk`; complete; use Active/Completed filters; delete through confirmation | Persisted title/completion after edit; correct filter membership; empty API list after delete; second account sees no prior content |
| Guided creation/resume | Start `Prepare weekend`; choose the multiple-step path; save `Pack bag` and `Check weather`; stop at review; reload web or terminate/relaunch native; resume the saved plan; confirm | No todos before confirmation; review survives restart; exactly two expected todos afterward; reload/relaunch and verify no duplicates |
| AI-assisted creation | Run both direct **Suggest todos** and **Ask agent for help** variants; agent answers the `constraints` form; edit first suggestion to `Gather reusable supplies`; remove the third; accept/save; explicit confirmation | Agent renders clarification and editable review through real streaming; neither requesting nor accepting suggestions creates todos; exactly the two edited/retained titles after confirmation |

Direct suggestions populate the existing multiline draft; edit that draft and
use **Save tasks**. The agent renders individual suggestion inputs and uses
**Use these suggestions**. Both then reach the same **Confirm plan** screen.
Do not assume those two UI paths have identical controls. Four executable cases
per platform cover these three families.

## Failure handling and diagnostics

Readiness waits have deadlines and distinguish missing tools, unavailable
Simulator, occupied ports, database/migration errors, build failures, and failed
UI assertions. Any skipped required native case is an incomplete acceptance,
not a successful suite. Wrapper scripts propagate the first failing command's
exit status, retain diagnostics, and clean up their own child processes on exit
or interruption.

Keep Playwright traces on failure and screenshots only on failure; upload its
HTML report and native Maestro report/hierarchy/screenshots plus build/API logs
with `if: always()`. Retain artifacts for seven days. They can contain synthetic
session tokens, so use disposable accounts only, never print authorization
headers, and never attach real development credentials. Avoid full environment
dumps. Include tool versions and the selected Simulator runtime in diagnostics.
Retries default to zero so flakes remain visible. A failure may be rerun manually
with a new account, but the original failure remains recorded.

## Acceptance and documentation

Deliver `pnpm test:e2e:web` and `pnpm test:e2e:ios`, documented setup and teardown,
and a Phase 12 guide linking this spec and the plan. Keep native E2E out of the
cross-platform `pnpm quality` command; CI owns platform scheduling. New harness
Python, TypeScript, and shell files must participate in lint/typechecking as
appropriate; do not assume the current globs include them automatically.

Acceptance requires four passing cases on each platform, two consecutive local
runs with new users, a successful browser PR job, and a successful native CI run
using the documented compatible runner/toolchain. Exercise an intentional failed
assertion once to prove nonzero exit and artifact capture, then remove it. Record
date, tool versions, commands, results, and remaining manual accessibility limits.
Do not rewrite earlier phases' unobserved acceptance claims as passing.

## References

- [Curriculum roadmap](../../curriculum-roadmap.md)
- [Phase 11 guide](../../guides/11-agentic-ui.md)
- [Playwright isolation](https://playwright.dev/docs/browser-contexts)
- [Playwright web servers](https://playwright.dev/docs/test-webserver)
- [Playwright traces](https://playwright.dev/docs/trace-viewer)
- [Maestro React Native support](https://docs.maestro.dev/platform-support/react-native)
- [Expo E2E example](https://docs.expo.dev/eas/workflows/examples/e2e-tests/)
- [Expo SDK 57 reference](https://docs.expo.dev/versions/v57.0.0/)
- [Expo CLI](https://docs.expo.dev/more/expo-cli/)

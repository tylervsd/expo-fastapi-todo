# Phase 12: Cross-platform E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run four deterministic critical-journey cases through Expo, FastAPI, and PostgreSQL on Chromium and iOS Simulator, with actionable CI evidence.

**Architecture:** Reuse the existing `create_app` provider seams in a test-only API entry point. A small Python CLI owns database validation/migration, account seeding, and persisted-result checks; Playwright and Maestro own their respective UI interactions. Native tests run a standalone Simulator Release build.

**Tech Stack:** Playwright Test/TypeScript, Maestro/YAML, Expo 57, FastAPI, PostgreSQL, Python standard library plus existing SQLAlchemy/Alembic/httpx, GitHub Actions.

**Spec:** [Phase 12 design](../specs/2026-09-11-cross-platform-e2e-design.md)

**Status:** Planning deliverable; implementation has not started. The first task resolves native compatibility before dependent implementation begins.

## Global Constraints

- Preserve current dependency pins: Node 24.20.0, pnpm 11.25.0, Python 3.14.7, uv 0.12.1, Expo 57.0.19, React Native 0.86.3, and PostgreSQL 18.6.
- Chromium only initially; no browser/device matrix.
- Web runs on pull requests and pushes to `main`; iOS runs on pushes to `main` and manual dispatch.
- Real HTTP, authentication, PostgreSQL, migrations, and application AG-UI streams.
- No live model calls, production credentials, paid test service, or EAS account required.
- No new production API route, authentication bypass, test-mode environment switch, or provider abstraction.
- Resolve and exact-pin Playwright and Maestro during the compatibility task; record the tested Xcode, macOS runner, Simulator runtime, Java, and CocoaPods versions before declaring native CI ready.
- One worker, zero automatic retries, new account per case/attempt, seven-day artifact retention.
- Follow existing project model routing: Astra for architecture; Luna for defined mechanical implementation; Terra for integration/debugging; Sol for significant/final review. Luna returns architecture gaps to the controller.

## File map and dependencies

All paths below are repository-relative. New paths are proposed deliverables,
not claims that files already exist. Read `apps/mobile/AGENTS.md` and the linked
SDK 57 reference before changing native configuration or application code.

| Files | Responsibility |
| --- | --- |
| `apps/api/e2e/__init__.py`, `app.py`, `support.py` | Test-only provider injection; guarded database preparation; host-side account and API assertion CLI |
| `apps/api/tests/test_e2e_support.py` | Focused checks for target safety and fixture callables |
| `compose.yaml` | Separate ephemeral `db-e2e` profile |
| `e2e/web/playwright.config.ts`, `journeys.spec.ts`, `tsconfig.json` | Browser servers, isolated accounts, four journey cases, E2E TypeScript validation |
| `e2e/ios/*.yaml` | Native flow segments; named individually in Task 4 |
| `scripts/e2e-ios` | Native build/install, owned server lifecycle, flow execution, API checkpoints |
| `apps/mobile/app.json` | Stable iOS bundle identifier |
| `package.json`, `pnpm-lock.yaml`, `.gitignore` | Exact Playwright dependency, entry commands, generated-output exclusions |
| `.github/workflows/e2e.yml` | Browser PR/main and native main/manual jobs |
| `docs/guides/12-cross-platform-e2e.md`, `README.md`, `docs/curriculum-roadmap.md` | Setup, version record, acceptance evidence, navigation |

Execute Tasks 1 and 2 first. Tasks 3 and 4 consume Task 2's fixed interfaces;
they may use separate implementers once Task 1 is reviewed. Task 5 integrates
both suites. Task 6 closes acceptance and documentation. Avoid concurrent edits
to `package.json`, the lockfile, or shared support files.

## Task 1: Prove and pin the native/browser toolchain

**Files:** Modify `package.json`, `pnpm-lock.yaml`, `apps/mobile/app.json`, `.gitignore`; create the initial `docs/guides/12-cross-platform-e2e.md` version/setup sections.

**Interfaces:** Produces an exact Playwright package pin, exact Maestro installation recipe, known native workspace/scheme, a validated Simulator build command, and a documented compatible macOS CI runner selection. No test suite or app behavior changes yet.

- [ ] Read the spec, current package pins, `.github/workflows/quality.yml`, and the official SDK 57 and CLI references. Check the current workspace for user changes before prebuild. Do not erase an existing native project.
- [ ] Inspect available tools and installed CLI flags; record outputs without dumping the environment.

  ```sh
  xcodebuild -version
  xcrun simctl list devices available
  xcrun simctl list runtimes
  java -version
  pod --version
  pnpm --dir apps/mobile exec expo run:ios --help
  pnpm view @playwright/test version
  ```

- [ ] Resolve the stable Playwright version once, install it with an exact pin, and install matching Chromium. Verify published Maestro installation/version-selection instructions and pin a release; do not use an unversioned installer in CI. Record Java and CocoaPods requirements for that release.

  ```sh
  PLAYWRIGHT_VERSION=$(pnpm view @playwright/test version)
  pnpm add -Dw --save-exact "@playwright/test@$PLAYWRIGHT_VERSION"
  pnpm exec playwright install chromium
  pnpm exec playwright --version
  maestro --version
  ```

- [ ] Add `expo.ios.bundleIdentifier: "dev.codex.fullstack.todo"` to the existing app config. Ignore generated `apps/mobile/ios/`, `apps/mobile/dist-e2e/`, `artifacts/e2e/`, and Playwright report/results directories. Do not replace existing ignore entries.
- [ ] Generate and prove an unsigned Simulator Release build with bundled JS. Use the explicit UDID obtained above; commands below express the required invocation, with the observed device ID supplied in the environment. Verify the generated workspace/scheme and record them for Task 4.

  ```sh
  EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8001 \
    pnpm --dir apps/mobile exec expo prebuild --platform ios --no-install
  EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8001 \
    pnpm --dir apps/mobile exec expo run:ios --configuration Release \
    --device "$E2E_SIMULATOR_UDID" --no-bundler
  ```

  Install pods as required by the observed CLI/prebuild behavior. Launch the app without Metro and observe the sign-in screen. Verify API loopback access against a local `/health` service when the harness is ready in Task 2. A missing required Xcode/runtime or build incompatibility is a blocker to resolve, not permission to substitute Expo Go.

- [ ] Verify Maestro can target the app, clear app/keychain state between cases, and preserve state for a stop/relaunch. Read the installed release's command help/docs and record exact supported reset syntax. Validate runner availability against Expo 57's Xcode requirement; do not inherit the existing `macos-15` doctor job blindly.
- [ ] Update the guide with observed versions and commands, identify any compatibility blockers, run `git diff --check` and Markdown lint, then commit only this task's changes with `test: establish phase 12 e2e toolchain`.

## Task 2: Add the isolated, deterministic backend harness

**Files:** Create `apps/api/e2e/{__init__,app,support}.py`, `apps/api/tests/test_e2e_support.py`; modify `compose.yaml`.

**Interfaces:** `validated_database_url(value: str) -> str`; `prepare_database(value: str) -> None`; async `suggestions(goal, config, *, clarification=None) -> tuple[str, ...]`; async `choice(goal, config, *, transport=None) -> ClarificationField`. CLI: `python -m e2e.support prepare`; `seed --prefix NAME`; `assert-todos --expected JSON`. Configuration: `E2E_DATABASE_URL`, `E2E_API_URL` (default `http://127.0.0.1:8001`), and, for assertions, `E2E_USERNAME`/`E2E_PASSWORD`. `seed` prints exactly `{"username": "...", "password": "..."}`; failures exit nonzero.

- [ ] Write a small parameterized target-validation check before implementation. Reject non-loopback hosts, wrong database/user/driver, query parameters, and missing values before opening any connection.

  ```python
  import pytest
  from e2e.support import validated_database_url

  @pytest.mark.parametrize("value", [
      "", "sqlite:///todo_e2e",
      "postgresql+psycopg://todo:todo@127.0.0.1:5432/todo",
      "postgresql+psycopg://todo_test:todo_test@127.0.0.1:5433/todo_test",
      "postgresql+psycopg://todo_e2e:x@db.example:5432/todo_e2e",
      "postgresql+psycopg://todo_e2e:x@localhost/todo_e2e?options=x",
  ])
  def test_rejects_unsafe_target(value):
      with pytest.raises(ValueError):
          validated_database_url(value)
  ```

- [ ] Run `uv run --directory apps/api python -m pytest tests/test_e2e_support.py -q`; expect import failure until support exists. Implement validation using `sqlalchemy.engine.make_url`, exact driver/database/user checks, host allowlist `localhost`, `127.0.0.1`, `::1`, and empty query. Render passwords only into connection arguments, never logs. `prepare` checks `current_database()` before Alembic `head` and uses the existing connection-injection pattern from `tests/conftest.py`.
- [ ] Add the independent Compose service using the existing PostgreSQL healthcheck pattern:

  ```yaml
  db-e2e:
    image: postgres:18.6
    profiles: [e2e]
    environment:
      POSTGRES_USER: todo_e2e
      POSTGRES_PASSWORD: todo_e2e
      POSTGRES_DB: todo_e2e
    ports: ["127.0.0.1:5434:5432"]
    tmpfs: [/var/lib/postgresql]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U todo_e2e -d todo_e2e"]
      interval: 2s
      timeout: 3s
      retries: 15
  ```

- [ ] Implement both credential-free callables. Keep existing protocol signatures, return `constraints` for the choice and the three spec titles for suggestions. When clarification is supplied, require field `constraints` and value `Use supplies already available`. Add one async-callable check using `asyncio.run`; no async test plugin needed. Patch the real provider functions to raise in that check to detect accidental delegation.
- [ ] Build `e2e.app:app` from the validated E2E URL and existing engine/session factory, injecting both callables. Dispose the owned engine when the test server exits. Do not modify `app.main:app`. Use `argparse`, existing `httpx`, and `secrets` in the support CLI. Seed usernames must fit the existing 3–32 ASCII character rule. API assertion compares full sorted `(title, completed)` lists and rejects duplicates through cardinality.
- [ ] Run the harness over HTTP with real migrations, then seed an account and assert an empty list. Also verify unauthenticated `/todos` still returns 401.

  ```sh
  docker compose --profile e2e up -d --wait db-e2e
  export E2E_DATABASE_URL=postgresql+psycopg://todo_e2e:todo_e2e@127.0.0.1:5434/todo_e2e
  uv run --directory apps/api python -m e2e.support prepare
  uv run --directory apps/api uvicorn e2e.app:app --host 127.0.0.1 --port 8001
  ```

  In a second terminal run `uv run --directory apps/api python -m e2e.support seed --prefix smoke`; supply the returned synthetic credentials through the assertion environment and run `assert-todos --expected '[]'`. Unset OpenRouter variables for this smoke check. The fixture API must start without them.

- [ ] Run focused pytest and `pnpm lint:api`; verify the database guard's rejection leaves development/pytest databases untouched. Commit as `test: add isolated e2e api harness`.

## Task 3: Implement four browser journeys

**Files:** Create `e2e/web/playwright.config.ts`, `journeys.spec.ts`, `tsconfig.json`; modify root `package.json`.

**Interfaces:** `pnpm test:e2e:web` prepares the dedicated database, exports web, and runs Playwright. It requires `E2E_DATABASE_URL` and an available database. Config is launched from repository root and uses API port 8001, browser origin `http://localhost:8081`. It owns both server processes.

- [ ] Write one core sign-in/add assertion in `journeys.spec.ts`, then wire config. Resolve seed script paths from repository root; use `execFileSync` with an argument array, not shell interpolation of credentials. Create one account in `beforeEach`; sign in via the UI. Keep a real API session for independent read assertions.

  ```ts
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Todo title', { exact: true }).fill('Buy milk');
  await page.getByRole('button', { name: 'Add todo', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'Buy milk', exact: true })).toBeVisible();
  ```

- [ ] Use Playwright's config directly; resolve filesystem paths from the config location so working-directory differences cannot launch the wrong app.

  ```ts
  // webServer commands run from the explicit repository-root cwd.
  use: {
    baseURL: 'http://localhost:8081',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // Two webServer entries: uvicorn e2e.app:app on 8001 and
  // python -m http.server 8081 --bind 127.0.0.1 --directory apps/mobile/dist-e2e.
  // API readiness URL is /health; static readiness URL is /.
  // Both have reuseExistingServer: false and a 60-second startup timeout.
  ```

  Export with `EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=http://127.0.0.1:8001 pnpm --dir apps/mobile exec expo export --platform web --output-dir dist-e2e`. Use existing uv-managed Python for the static server. Add the export/preparation commands to the root script, keeping all paths explicit. Verify port collision exits nonzero rather than connecting to an unrelated server.

- [ ] Complete core CRUD: edit through `Edit Buy milk`, `Edit todo title`, `Save changes`; wait for persisted rename, then check the checkbox, assert API completion, inspect Active/Completed filters, delete through `Delete Buy oat milk` and `Confirm delete`. Assert API list empty. Sign out and sign in as a second fresh account; assert empty UI and API.
- [ ] Add the guided case using these exact existing names. Wait for each distinct question before selecting **Yes**, so the second click cannot hit the first screen.

  ```ts
  await page.getByRole('button', { name: 'Help me plan a task', exact: true }).click();
  await page.getByLabel('Task title', { exact: true }).fill('Prepare weekend');
  await page.getByRole('button', { name: 'Start planning', exact: true }).click();
  await expect(page.getByText('Does this task involve multiple steps?', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Yes', exact: true }).click();
  await expect(page.getByText('Would you like to split it into smaller todos?', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Yes', exact: true }).click();
  await page.getByLabel('Todo titles (one per line)', { exact: true }).fill('Pack bag\nCheck weather');
  await page.getByRole('button', { name: 'Save tasks', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Confirm plan', exact: true })).toBeVisible();
  ```

  Check zero API todos; reload and resume via `Prepare weekend, Review your plan`; confirm; assert exactly `Pack bag`/`Check weather`, both incomplete. Reload again and verify exactly two rows through UI and API. Sign out.

- [ ] Add separate direct/agent AI cases, sharing only small local sign-in/start helpers in the same spec file. Direct: **Suggest todos**, await the fixture draft, check zero API todos, replace multiline draft with `Gather reusable supplies\nPrepare workspace`, then **Save tasks**. Agent: **Ask agent for help**, fill **Your answer**, **Continue**, await **Suggestion 1 of 3**, edit it, **Remove suggestion 3**, check zero todos, then **Use these suggestions**. Both check zero todos at final review and confirm exactly the same two expected rows. End with sign-out assertions.
- [ ] API assertions must wait for actual completion where writes are optimistic: use `expect.poll` around real `/todos` reads, not a sleep. Do not intercept application routes or inject tokens into storage. Confirm the agent case uses real `/agent` streaming by recording successful stream requests without logging their bearer headers.
- [ ] Add `e2e/web/tsconfig.json` with strict/noEmit settings covering config/spec, and `typecheck:e2e` using the installed TypeScript compiler. Run browser tests twice with different accounts and `pnpm typecheck:e2e`. Review failure traces, then commit as `test: cover critical browser journeys`.

## Task 4: Implement native journeys and lifecycle wrapper

**Files:** Create `scripts/e2e-ios`; create `e2e/ios/sign-in.yaml`, `sign-out.yaml`, `core-edit.yaml`, `core-delete.yaml`, `guided-review.yaml`, `guided-resume-confirm.yaml`, `ai-direct-review.yaml`, `ai-agent-review.yaml`, `confirm.yaml`; modify root `package.json` and the guide.

**Interfaces:** `pnpm test:e2e:ios` requires `E2E_DATABASE_URL` and `E2E_SIMULATOR_UDID`; Task 1 supplies the verified build/reset commands. Wrapper passes `APP_ID`, `USERNAME`, `PASSWORD` to Maestro. Python API checkpoints use the same credentials through `E2E_USERNAME`/`E2E_PASSWORD`. Native API and browser API both use port 8001 and must not run simultaneously on one host.

- [ ] Write the sign-in and core-edit flow first. Verify Maestro selectors against the actual hierarchy before adding IDs; the following text selectors are the starting point, not permission to ignore duplicate matches.

  ```yaml
  appId: ${APP_ID}
  ---
  - tapOn: "Username"
  - inputText: ${USERNAME}
  - tapOn: "Password"
  - inputText: ${PASSWORD}
  - hideKeyboard
  - tapOn: "Sign in"
  - assertVisible: "Todo title"
  ```

  For duplicated native text (for example Sign in heading/button), scope using supported hierarchy selectors or add a narrowly targeted `testID` to the control, retaining its accessible label. Any app changes need existing component tests rerun.

- [ ] Implement the POSIX shell wrapper with `set -eu`, explicit prerequisite checks, bounded startup waits, and traps that terminate only its own processes. Validate the database first; check ports before launching. Use a task-owned temporary directory for seed JSON and logs. Parse JSON through Python, not `eval`, and keep credentials out of command tracing. Propagate failures and retain artifacts under `artifacts/e2e/ios/`.
- [ ] Build/install using Task 1's observed commands, recording the app output path rather than searching arbitrary DerivedData directories. Boot/wait for the selected Simulator and verify the app opens without Metro. Prepare database, launch the fixture API, wait for `/health`, then seed a fresh account. Native shell orchestration uses the CLI contract directly:

  ```sh
  uv run --directory apps/api python -m e2e.support prepare
  uv run --directory apps/api python -m e2e.support seed --prefix ios
  # Parse seed output into USERNAME/PASSWORD and export E2E_USERNAME/E2E_PASSWORD.
  maestro --device "$E2E_SIMULATOR_UDID" test \
    -e APP_ID=dev.codex.fullstack.todo \
    -e USERNAME="$E2E_USERNAME" -e PASSWORD="$E2E_PASSWORD" \
    e2e/ios/sign-in.yaml
  uv run --directory apps/api python -m e2e.support assert-todos --expected '[]'
  ```

  Use the verified Maestro report/output flags for each segment, with unique filenames so subsequent invocations cannot overwrite an earlier failure. No global Simulator erase or `killall`.

- [ ] Finish core-edit with add, rename, complete, and filters; assert API `[ {"title":"Buy oat milk","completed":true} ]`. Run core-delete, assert `[]`, sign out, seed/sign in as another user, assert empty state, and sign out. Reset app/keychain only between independent cases.
- [ ] Implement guided-review through the two distinct Yes questions and **Save tasks**; assert API `[]`. Stop and relaunch without clearing state; resume the named plan in guided-resume-confirm, confirm, and assert the two spec titles. Relaunch once more and verify the persisted UI and exact API cardinality, then sign out.
- [ ] Implement direct and agent AI flows separately, using the distinct controls listed in Task 3. Split each preparation flow at the visible suggestion stage for an API `[]` check, then again at final review for another `[]` check; use additional `runFlow` segments within the named family if required. Host orchestration calls Maestro once per checkpoint boundary. Agent must render **Your answer** and the three editable suggestion controls before edits. **confirm.yaml** confirms and returns to todos; assert exactly the edited/retained titles, then sign out.
- [ ] Add bounded `extendedWaitUntil`/scroll actions only where needed, without fixed sleeps or coordinates. Validate sign-out shows authentication and no previous todo content. If a required case cannot run, exit nonzero with the platform/build reason.
- [ ] Run all four native cases twice. Run `shellcheck scripts/e2e-ios`, `pnpm typecheck`, and targeted component tests if selectors changed. Commit as `test: cover critical ios simulator journeys`.

## Task 5: Add platform-aware CI and artifact checks

**Files:** Create `.github/workflows/e2e.yml`; modify root lint scripts only as needed to include new shell/TypeScript files; update the guide's CI/version sections.

**Interfaces:** Independent `web` and `ios` jobs. Browser runs on pull requests, main pushes, and manual dispatch; native only main pushes/manual dispatch. Read-only repository permissions; no OpenRouter secrets or paid services.

- [ ] Build workflow triggers and native condition explicitly:

  ```yaml
  on:
    pull_request:
    push:
      branches: [main]
    workflow_dispatch:
  permissions:
    contents: read
  # Under the ios job:
  # if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'
  ```

- [ ] Browser job reuses exact existing Node/Python/pnpm/uv setup from quality CI, uses PostgreSQL 18.6 service with database/user `todo_e2e`, installs matching Chromium OS dependencies, runs `pnpm typecheck:e2e` and `pnpm test:e2e:web`. Set `E2E_DATABASE_URL` to the service's loopback mapping. Bound the job to 20 minutes.
- [ ] Native job uses the compatible runner/Xcode/runtime recorded in Task 1. Provision PostgreSQL 18.6 directly on macOS, initialize a job-owned cluster, and create only `todo_e2e` role/database; do not use GitHub service containers on macOS. Install the exact verified Maestro/Java/CocoaPods versions, choose a device UDID from the pinned runtime, and run `pnpm test:e2e:ios`. Bound the job to 60 minutes. Missing required tooling is a failed setup, never a skipped success.
- [ ] Pin newly added actions to verified commit SHAs following current workflow conventions. Keep current quality/security workflows unchanged unless adding the new harness lint coverage. Add `scripts/e2e-ios` to shellcheck, include harness Python under Ruff, and run E2E TypeScript validation in the browser job. Do not move native tests into `pnpm quality`.
- [ ] Upload reports and logs on every outcome with unique platform names and seven-day retention. Avoid failure masking:

  ```yaml
  - name: Upload E2E evidence
    if: always()
    # Add the verified SHA-pinned upload-artifact action here during implementation.
    with:
      name: e2e-web
      path: artifacts/e2e/
      retention-days: 7
      if-no-files-found: warn
  ```

  Resolve the action SHA from its official release before writing executable YAML; this excerpt specifies artifact settings only. Reports must exist for assertion failures; setup failures must still preserve their logs. No `continue-on-error` for required tests.

- [ ] Temporarily force a false UI assertion locally, confirm nonzero exit and readable failure evidence, and remove the intentional failure. Validate final workflow syntax and inspect triggers. Run web CI on a PR and native via manual dispatch of an accessible branch before relying on main scheduling. If remote workflow execution is unavailable, record it as pending acceptance rather than claiming CI success.
- [ ] Commit as `ci: run browser and native e2e journeys`.

## Task 6: Complete guide, acceptance, and review

**Files:** Finish `docs/guides/12-cross-platform-e2e.md`; update `README.md` and Phase 12 status in `docs/curriculum-roadmap.md`; correct this plan/spec only when execution evidence requires a documented change.

- [ ] Document exact install/build/run commands, explicit database setup, port ownership, native state reset versus resume, environment variables, failure artifacts, and teardown limited to E2E resources. Explain provider fixture boundaries and what E2E does not prove.
- [ ] Record four cases per platform with actual dates, tool versions, local double-run results, browser PR result, native CI result, and accessibility limits. Leave unobserved rows explicitly pending. Preserve prior guides' acceptance history.
- [ ] Run the relevant final commands once after integration:

  ```sh
  pnpm lint:markdown
  pnpm lint:links
  pnpm lint:api
  pnpm typecheck:e2e
  shellcheck scripts/e2e-ios
  uv run --directory apps/api python -m pytest tests/test_e2e_support.py -q
  pnpm test:e2e:web
  pnpm test:e2e:ios
  git diff --check
  ```

  Run the existing `pnpm quality` gate before integration. Use the dedicated E2E database for E2E and keep the existing pytest database configuration for quality. Do not rerun native builds merely because unrelated prose changed.
- [ ] Request Sol whole-branch review with spec, diff, and observed acceptance evidence. Resolve findings; use Terra for integration failures and return architecture changes to the controller. Commit documentation as `docs: document phase 12 e2e acceptance`.
- [ ] Integrate through the project's normal development workflow. Only then update completion status and create the checkpoint after required CI has actually passed. A plan, successful export, or skipped native run is not phase completion.

## Coverage audit

| Spec requirement | Implementation task |
| --- | --- |
| Exact compatible toolchain; standalone native build | 1, 4, 5 |
| Safe independent database; credentials-free deterministic provider seams | 2 |
| Four web cases, explicit confirmation, restart, account isolation | 3 |
| Four native cases, host-side pre/post-write checks, reset/resume distinction | 4 |
| Stable selectors, useful failures, no silent skips/retries | 3, 4, 5 |
| PR/main platform scheduling and seven-day evidence | 5 |
| Runnable commands, lint coverage, truthful acceptance/checkpoint | 5, 6 |

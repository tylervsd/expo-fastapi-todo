# Phase 1 Project Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first runnable Expo web/iOS and FastAPI boundary, with an exact health contract, explicit connection states, separate host processes, and a repeatable quality gate.

**Architecture:** `apps/mobile` is an Expo SDK 57 pnpm workspace whose screen owns connection state while a focused health client owns URL construction, timeout, cancellation, parsing, and contract validation. `apps/api` is an independent uv project exposing one FastAPI route and exact localhost CORS policy; root scripts and CI compose both packages without supervising either development process.

**Tech Stack:** Node.js 24.20.0, pnpm 11.25.0, Expo SDK 57.0.19, React Native 0.86.3, React 19.2.3, TypeScript, Jest 29.7.0, jest-expo 57.0.5, React Native Testing Library 14.0.1, test-renderer 1.2.0, Python 3.14.7, uv 0.12.1, FastAPI 0.141.1, Pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-04-project-foundation-design.md`

## Global Constraints

- Start Phase 1 history from annotated tag `phase-00-environment` (`c95a9a14bdd18702fb07f06b08c075c669277a8f`) in an isolated `codex/phase-01-foundation` worktree; carry the approved Phase 1 spec commits `2893bab` and `81476cb` plus this plan, and do not recreate Phase 0.
- Preserve Phase 0's Node.js `24.20.0`, pnpm `11.25.0`, Python `3.14.7`, doctor, setup documentation, repository contracts, and CI checks except for replacing the now-obsolete assertion that application workspaces do not exist.
- Use Expo SDK `57.0.19`, React Native `0.86.3`, React `19.2.3`, and the verified `expo-template-blank-typescript@57.0.22`; SDK 57 requires Node `>=22.13`, Xcode `>=26.4`, and iOS `>=16.4`, so the Phase 0 reference environment satisfies it. The 57.0.19 patch is pinned because its Expo CLI/core/JSI graph is eligible under the repository's minimum release-age policy.
- Run Expo and FastAPI as two visible host processes: `pnpm dev:mobile` and `pnpm dev:api`. Do not add Docker, Compose, a supervisor, or a combined long-running command.
- Expo uses stable web origin `http://localhost:8081`; the client API URL is `http://127.0.0.1:8000`; FastAPI binds to `127.0.0.1:8000` and grants CORS only to the Expo origin.
- `GET /health` has no auth, parameters, request body, database, or side effects and returns HTTP `200` with exactly `{"status":"ok"}`.
- The mobile screen supports Connecting, Connected, and Unavailable. Every request, including body consumption, has a five-second timeout; unmount, cancelled, and stale completions cannot update state.
- Retry is available after both Connected and Unavailable, launches exactly one new attempt, and is unavailable while Connecting. Do not poll, back off, or retry automatically.
- `EXPO_PUBLIC_` values are public client configuration and must never contain secrets.
- Do not add todos, persistence, a database, auth, authorization, a generated client, deployment, physical-device support, automated browser/iOS E2E, or Android acceptance work.
- CI retains every Phase 0 check and adds mobile lint/typecheck/component tests, API lint/tests, and non-interactive web export. All third-party Actions remain pinned to full commit SHAs.
- Create annotated tag `phase-01-foundation` only after CI passes and the recovery journey is recorded successful on web and the designated iPhone 17 Pro iOS Simulator; record the installed Expo Go version used for iOS acceptance.
- Route plan control and architecture decisions through a `gpt-5.6-sol` controller; use `gpt-5.6-luna` only for bounded implementation tasks, escalate integration or difficult debugging to `gpt-5.6-terra`, and use `gpt-5.6-sol` for the final whole-branch review. Luna workers must return any architecture or scope issue to the Sol controller.
- Preserve the untracked `AGENTS.md`; do not stage or publish it.

---

## Planned file map and interfaces

- `package.json` — preserves root pins and Phase 0 commands; adds `dev:mobile`, `dev:api`, and aggregate mobile/API/build quality commands.
- `pnpm-lock.yaml` — locks the verified Expo, React, Jest, Testing Library, and lint graph.
- `.gitignore` — ignores Expo local state, generated exports, coverage, Python caches, and the copied mobile environment file while keeping its example.
- `tests/repository_contract.bats` — replaces only the obsolete no-apps assertion with the Phase 1 workspace and command contract.
- `apps/api/pyproject.toml` and `apps/api/uv.lock` — own Python 3.14, FastAPI 0.141.1, Uvicorn, Ruff, HTTPX, and Pytest resolution.
- `apps/api/app/main.py` — exports `app: FastAPI` with exact localhost CORS policy and `health() -> dict[str, str]`.
- `apps/api/tests/test_health.py` — in-process route and allowed/disallowed-origin contract tests.
- `apps/mobile/package.json`, `app.json`, `tsconfig.json`, `index.ts`, `assets/*` — verified blank Expo TypeScript scaffold and package commands.
- `apps/mobile/.env.example` — documents `EXPO_PUBLIC_API_URL=http://127.0.0.1:8000`; `apps/mobile/.env.local` is learner-owned and ignored.
- `apps/mobile/eslint.config.js` and `jest.config.js` — Expo-compatible static and component-test configuration using `test-renderer`, without deprecated `react-test-renderer`.
- `apps/mobile/src/health/checkHealth.ts` — exports `HealthPayload`, `HealthCheckOptions`, `HealthCheckError`, and `checkHealth(options): Promise<HealthPayload>`; owns timeout, abort, parsing, and validation.
- `apps/mobile/src/health/checkHealth.test.ts` — deterministic unit tests for every transport/contract result and cancellation.
- `apps/mobile/src/HealthScreen.tsx` — exports `HealthScreen({ healthCheck? })`; owns the visible state machine, attempt identity, active controller, and Retry.
- `apps/mobile/src/HealthScreen.test.tsx` — controlled component tests using async React Native Testing Library APIs.
- `apps/mobile/App.tsx` — composition root that renders `HealthScreen`.
- `.github/workflows/quality.yml` — preserves Phase 0 jobs and adds locked Node/Python application checks and web export.
- `docs/guides/01-project-foundation.md` — learner workflow, boundaries, diagnostics, recovery, manual acceptance, and acceptance record.
- `README.md` — advances the current checkpoint to Phase 1 and links the guide while preserving Phase 0 setup.
- `docs/curriculum-roadmap.md` — removes Docker Compose and service-smoke claims that conflict with the approved Phase 1 scope.

### Task 1: Reconstruct the approved Phase 1 branch from the completed checkpoint

**Files:**

- Carry: `docs/superpowers/specs/2026-09-04-project-foundation-design.md`
- Carry: `docs/superpowers/plans/2026-09-04-project-foundation.md`

**Interfaces:**

- Consumes: immutable Phase 0 tag `phase-00-environment`, spec commits `2893bab` and `81476cb`, and the commit containing this plan on the planning checkout.
- Produces: isolated worktree `.worktrees/phase-01-foundation` on `codex/phase-01-foundation`, with Phase 0 as an ancestor and both approved documents present.

- [ ] **Step 1: Prove the checkpoint and planning inputs exist**

Run from the planning checkout:

```bash
git rev-parse phase-00-environment^{commit}
test "$(git cat-file -t refs/tags/phase-00-environment)" = tag
git show --quiet --oneline 2893bab
git show --quiet --oneline 81476cb
phase1_plan_commit="$(git log -1 --format=%H -- docs/superpowers/plans/2026-09-04-project-foundation.md)"
test -n "$phase1_plan_commit"
```

Expected: the first command prints `c95a9a14bdd18702fb07f06b08c075c669277a8f`; the ref is an annotated tag object; both spec commits and a committed plan resolve.

- [ ] **Step 2: Create the isolated implementation worktree and carry reviewed docs**

```bash
git worktree add .worktrees/phase-01-foundation -b codex/phase-01-foundation phase-00-environment
git -C .worktrees/phase-01-foundation cherry-pick 2893bab 81476cb "$phase1_plan_commit"
```

Expected: cherry-picks apply cleanly; no Phase 0 implementation file changes.

- [ ] **Step 3: Verify ancestry and baseline quality before editing**

```bash
cd .worktrees/phase-01-foundation
git merge-base --is-ancestor phase-00-environment HEAD
test -f docs/superpowers/specs/2026-09-04-project-foundation-design.md
test -f docs/superpowers/plans/2026-09-04-project-foundation.md
pnpm install --frozen-lockfile
pnpm quality
git status --short
```

Expected: all checks pass and the status is clean. Perform every later task in this worktree.

### Task 2: Add the exact FastAPI health and CORS contract

**Files:**

- Create: `apps/api/pyproject.toml`
- Create: `apps/api/uv.lock`
- Create: `apps/api/app/__init__.py`
- Create: `apps/api/app/main.py`
- Create: `apps/api/tests/test_health.py`

**Interfaces:**

- Consumes: Python 3.14.7 and uv from Phase 0.
- Produces: `app.main:app`, `GET /health -> {"status":"ok"}`, allowed origin `http://localhost:8081`, and root-addressable commands through `uv run --project apps/api`.

- [ ] **Step 1: Declare and lock the API environment**

Create `apps/api/pyproject.toml`:

```toml
[project]
name = "expo-fastapi-todo-api"
version = "0.1.0"
requires-python = "==3.14.*"
dependencies = [
  "fastapi==0.141.1",
  "uvicorn[standard]",
]

[dependency-groups]
dev = ["httpx", "pytest", "ruff"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py314"
line-length = 88
```

Then run:

```bash
UV_PYTHON_DOWNLOADS=never uv lock --project apps/api --python 3.14.7
UV_PYTHON_DOWNLOADS=never uv sync --project apps/api --frozen --python 3.14.7
```

Expected: `apps/api/uv.lock` records the resolved Uvicorn, HTTPX, Pytest, and Ruff versions; uv uses the already-installed managed Python 3.14.7.

- [ ] **Step 2: Write failing route and CORS tests**

Create `apps/api/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_exact_contract() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_allows_documented_expo_web_origin() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8081"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_health_does_not_allow_unlisted_origin() -> None:
    response = client.get(
        "/health", headers={"Origin": "http://localhost:9999"}
    )

    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 3: Run the test and verify the missing app fails**

```bash
uv run --directory apps/api python -m pytest tests/test_health.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 4: Implement the smallest API**

Create empty `apps/api/app/__init__.py` and `apps/api/app/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

EXPO_WEB_ORIGIN = "http://localhost:8081"

app = FastAPI(title="Expo FastAPI Todo API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[EXPO_WEB_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 5: Verify API tests and lint, then commit**

```bash
uv run --directory apps/api python -m pytest tests/test_health.py -v
uv run --directory apps/api ruff check .
git add apps/api
git commit -m "feat: add API health contract"
```

Expected: three tests pass, Ruff passes, and only API files are committed.

### Task 3: Scaffold Expo and test the cancellable health boundary

**Files:**

- Create: `apps/mobile/package.json`, `app.json`, `tsconfig.json`, `index.ts`, `assets/*`
- Create: `apps/mobile/.env.example`
- Create: `apps/mobile/eslint.config.js`
- Create: `apps/mobile/jest.config.js`
- Create: `apps/mobile/src/health/checkHealth.ts`
- Create: `apps/mobile/src/health/checkHealth.test.ts`
- Modify: `pnpm-lock.yaml`

**Interfaces:**

- Consumes: SDK URL from `process.env.EXPO_PUBLIC_API_URL`, optional `AbortSignal`, injectable `fetchImpl`, and timeout milliseconds.
- Produces: `checkHealth(options?: HealthCheckOptions): Promise<HealthPayload>`, resolving only to `{ status: "ok" }`; `HealthCheckError.message` is safe to display; caller cancellation rejects with an `AbortError`.

- [ ] **Step 1: Create the verified SDK 57 package and testing toolchain**

```bash
pnpm dlx create-expo-app@4.0.0 apps/mobile --template expo-template-blank-typescript@57.0.22 --no-install
pnpm install
pnpm --dir apps/mobile exec expo install react-dom react-native-web @expo/metro-runtime
pnpm --dir apps/mobile add --save-exact --save-dev jest@29.7.0 jest-expo@57.0.5 @react-native/jest-preset@0.86.3 @testing-library/react-native@14.0.1 test-renderer@1.2.0 @types/jest@29.5.14
pnpm --dir apps/mobile exec expo install eslint eslint-config-expo -- --save-dev
```

Expected: `apps/mobile/package.json` retains `expo57.0.19`, `react-native0.86.3`, `react19.2.3`, and `expo-status-bar~57.0.1`; Expo selects compatible web packages; the root lockfile contains the complete resolved graph. Do not add `react-test-renderer` directly; the selected Jest preset may retain it transitively.

Merge these entries into the scaffold's `scripts` object, retaining its existing startup commands:

```json
{
  "lint": "expo lint",
  "typecheck": "tsc --noEmit",
  "test": "jest",
  "export:web": "expo export --platform web --output-dir dist"
}
```

Create `jest.config.js`:

```javascript
module.exports = { preset: "jest-expo", testMatch: ["**/*.test.ts?(x)"] };
```

Create `eslint.config.js`:

```javascript
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");
module.exports = defineConfig([expoConfig, { ignores: ["dist/**"] }]);
```

Run `pnpm --dir apps/mobile exec expo install --check` to confirm Expo's package alignment. Resolve any test-transform or peer mismatch against the pinned SDK through the Sol controller; do not switch SDKs or use force flags to hide it.

Create `apps/mobile/.env.example`:

```dotenv
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
```

- [ ] **Step 2: Write deterministic boundary tests first**

Create `apps/mobile/src/health/checkHealth.test.ts` with a `response(status, body)` helper returning a minimal `Response` double, then these cases:

```typescript
import { checkHealth, HealthCheckError } from "./checkHealth";

const response = (status: number, body: unknown) =>
  ({ status, json: jest.fn().mockResolvedValue(body) }) as unknown as Response;

it("resolves only the exact healthy payload", async () => {
  const fetchImpl = jest.fn().mockResolvedValue(response(200, { status: "ok" }));
  await expect(checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl })).resolves.toEqual({ status: "ok" });
  expect(fetchImpl).toHaveBeenCalledWith("http://127.0.0.1:8000/health", expect.objectContaining({ method: "GET" }));
});

it.each([
  ["network", jest.fn().mockRejectedValue(new TypeError("offline")), "Could not reach the API."],
  ["non-200", jest.fn().mockResolvedValue(response(503, { status: "ok" })), "The API returned an unexpected response."],
  ["invalid JSON", jest.fn().mockResolvedValue({ status: 200, json: jest.fn().mockRejectedValue(new SyntaxError()) }), "The API returned invalid data."],
  ["unexpected body", jest.fn().mockResolvedValue(response(200, { status: "up" })), "The API returned invalid data."],
])("maps %s to safe unavailable copy", async (_case, fetchImpl, message) => {
  await expect(checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl })).rejects.toEqual(new HealthCheckError(message));
});

it("times out body consumption after five seconds and aborts transport", async () => {
  jest.useFakeTimers();
  const json = jest.fn(() => new Promise<never>(() => undefined));
  const fetchImpl = jest.fn().mockResolvedValue({ status: 200, json } as unknown as Response);
  const pending = checkHealth({ apiUrl: "http://127.0.0.1:8000", fetchImpl });
  const rejection = expect(pending).rejects.toEqual(new HealthCheckError("The API check timed out."));
  await jest.advanceTimersByTimeAsync(5_000);
  await rejection;
  expect((fetchImpl.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
  jest.useRealTimers();
});

it("rejects immediately when the caller cancels even if fetch ignores abort", async () => {
  const controller = new AbortController();
  const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
  const pending = checkHealth({ apiUrl: "http://127.0.0.1:8000", signal: controller.signal, fetchImpl });
  controller.abort();
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
});
```

- [ ] **Step 3: Run the focused suite and verify it fails**

```bash
pnpm --dir apps/mobile test --runInBand src/health/checkHealth.test.ts
```

Expected: FAIL because `./checkHealth` does not exist.

- [ ] **Step 4: Implement one-settlement timeout and cancellation**

Create `apps/mobile/src/health/checkHealth.ts`:

```typescript
export type HealthPayload = { status: "ok" };
export type HealthCheckOptions = {
  apiUrl?: string;
  timeoutMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
};
export class HealthCheckError extends Error {}

export function checkHealth(options: HealthCheckOptions = {}): Promise<HealthPayload> {
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      options.signal?.removeEventListener("abort", cancel);
      if (error) reject(error);
      else resolve({ status: "ok" });
    };
    const cancel = () => {
      const error = new Error("The API check was cancelled.");
      error.name = "AbortError";
      finish(error);
      controller.abort();
    };
    if (options.signal?.aborted) { cancel(); return; }
    options.signal?.addEventListener("abort", cancel, { once: true });
    let url: string;
    try {
      const base = options.apiUrl ?? process.env.EXPO_PUBLIC_API_URL;
      if (!base) throw new Error("Missing API URL");
      const parsed = new URL(base);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("Invalid protocol");
      url = new URL("/health", parsed).toString();
    } catch {
      finish(new HealthCheckError("The API URL is not configured correctly."));
      return;
    }
    timer = setTimeout(() => {
      finish(new HealthCheckError("The API check timed out."));
      controller.abort();
    }, options.timeoutMs ?? 5_000);
    void (async () => {
      try {
        const result = await (options.fetchImpl ?? fetch)(url, {
          method: "GET", signal: controller.signal,
        });
        if (settled) return;
        if (result.status !== 200) {
          finish(new HealthCheckError("The API returned an unexpected response."));
          controller.abort();
          return;
        }
        let body: unknown;
        try { body = await result.json(); }
        catch { finish(new HealthCheckError("The API returned invalid data.")); return; }
        if (typeof body !== "object" || body === null || Array.isArray(body) ||
            Object.keys(body).length !== 1 || !("status" in body) || body.status !== "ok") {
          finish(new HealthCheckError("The API returned invalid data."));
          return;
        }
        finish();
      } catch {
        finish(new HealthCheckError("Could not reach the API."));
      }
    })();
  });
}
```

Add these resource-cleanup tests to the boundary suite before completing this task:

```typescript
it("does not start transport for an already cancelled caller", async () => {
  const controller = new AbortController();
  controller.abort();
  const fetchImpl = jest.fn();
  await expect(checkHealth({ signal: controller.signal, fetchImpl }))
    .rejects.toMatchObject({ name: "AbortError" });
  expect(fetchImpl).not.toHaveBeenCalled();
});

it.each(["success", "timeout", "cancel"])("cleans up after %s", async (mode) => {
  jest.useFakeTimers();
  try {
    const controller = new AbortController();
    const removed = jest.spyOn(controller.signal, "removeEventListener");
    const fetchImpl = jest.fn().mockImplementation(() => mode === "success"
      ? Promise.resolve(response(200, { status: "ok" }))
      : new Promise<Response>(() => undefined));
    const result = checkHealth({ apiUrl: "http://127.0.0.1:8000", signal: controller.signal, fetchImpl });
    const assertion = mode === "success" ? expect(result).resolves.toEqual({ status: "ok" })
      : expect(result).rejects.toBeInstanceOf(Error);
    if (mode === "cancel") controller.abort();
    if (mode === "timeout") await jest.advanceTimersByTimeAsync(5_000);
    await assertion;
    expect(jest.getTimerCount()).toBe(0);
    expect(removed).toHaveBeenCalledWith("abort", expect.any(Function));
  } finally { jest.useRealTimers(); }
});
```

- [ ] **Step 5: Verify the boundary and commit the package foundation**

```bash
pnpm --dir apps/mobile test --runInBand src/health/checkHealth.test.ts
pnpm --dir apps/mobile typecheck
pnpm --dir apps/mobile lint
git add apps/mobile pnpm-lock.yaml
git commit -m "feat: add cancellable mobile health client"
```

Expected: all boundary cases pass without wall-clock waits; typecheck and lint pass.

### Task 4: Build and test the explicit screen state machine

**Files:**

- Create: `apps/mobile/src/HealthScreen.tsx`
- Create: `apps/mobile/src/HealthScreen.test.tsx`
- Modify: `apps/mobile/App.tsx`

**Interfaces:**

- Consumes: injected `healthCheck(options: { signal: AbortSignal }): Promise<HealthPayload>`, defaulting to Task 3's `checkHealth`.
- Produces: shared web/iOS `HealthScreen` with visible Connecting/Connected/Unavailable states, one active attempt, Retry after settled states, unmount abort, and attempt-identity protection.

- [ ] **Step 1: Write controlled component tests**

Create `apps/mobile/src/HealthScreen.test.tsx`. Use RNTL 14's async `render` and `fireEvent.press`, plus `screen`, `waitFor`, and this deferred helper. Cover initial Connecting and one call, valid Connected, safe Unavailable after rejection, Retry from Connected, Retry from Unavailable followed by recovery, stale completion after an effect replacement, and unmount cancellation. The key interaction assertions are:

```typescript
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { HealthScreen } from "./HealthScreen";
import { type HealthPayload, HealthCheckError } from "./health/checkHealth";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

it("connects and allows exactly one new check through Retry", async () => {
const first = deferred<HealthPayload>();
const second = deferred<HealthPayload>();
const healthCheck = jest.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
await render(<HealthScreen healthCheck={healthCheck} />);
expect(screen.getByText("Connecting")).toBeTruthy();
await act(async () => first.resolve({ status: "ok" }));
expect(screen.getByText("Connected")).toBeTruthy();
await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
expect(screen.getByText("Connecting")).toBeTruthy();
expect(healthCheck).toHaveBeenCalledTimes(2);
await act(async () => second.resolve({ status: "ok" }));
expect(screen.getByText("Connected")).toBeTruthy();

const activeSignal = healthCheck.mock.calls[1][0].signal as AbortSignal;
await screen.unmount();
expect(activeSignal.aborted).toBe(true);
});

it("shows a safe failure and recovers through Retry", async () => {
  const first = deferred<HealthPayload>();
  const next = deferred<HealthPayload>();
  const healthCheck = jest.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(next.promise);
  await render(<HealthScreen healthCheck={healthCheck} />);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  await act(async () => first.reject(new HealthCheckError("The API check timed out.")));
  expect(screen.getByText("Unavailable")).toBeTruthy();
  expect(screen.getByText("The API check timed out.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
  expect(screen.getByText("Connecting")).toBeTruthy();
  expect(healthCheck).toHaveBeenCalledTimes(2);
  await act(async () => next.resolve({ status: "ok" }));
  expect(screen.getByText("Connected")).toBeTruthy();
});

it("ignores an old result after replacing the health checker", async () => {
  const old = deferred<HealthPayload>();
  const current = deferred<HealthPayload>();
  const one = jest.fn().mockReturnValue(old.promise);
  const two = jest.fn().mockReturnValue(current.promise);
  await render(<HealthScreen healthCheck={one} />);
  await screen.rerender(<HealthScreen healthCheck={two} />);
  expect(one.mock.calls[0][0].signal.aborted).toBe(true);
  await act(async () => current.resolve({ status: "ok" }));
  await act(async () => old.reject(new Error("stale failure")));
  expect(screen.getByText("Connected")).toBeTruthy();
  expect(screen.queryByText("stale failure")).toBeNull();
});

it("aborts a pending attempt on unmount and ignores late completion", async () => {
  const pending = deferred<HealthPayload>();
  const healthCheck = jest.fn().mockReturnValue(pending.promise);
  await render(<HealthScreen healthCheck={healthCheck} />);
  const signal = healthCheck.mock.calls[0][0].signal as AbortSignal;
  await screen.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ status: "ok" }));
  expect(healthCheck).toHaveBeenCalledTimes(1);
});
```

For stale protection, render with `healthCheckOne` returning a pending deferred promise, rerender with `healthCheckTwo`, resolve attempt two to Connected, then reject attempt one and assert the screen remains Connected. Retry from an unavailable first attempt must show Connecting immediately and resolve to Connected. Assert no button with accessible name Retry exists while Connecting, and assert rejection copy is displayed without the original exception or stack.

- [ ] **Step 2: Run the focused suite and verify it fails**

```bash
pnpm --dir apps/mobile test --runInBand src/HealthScreen.test.tsx
```

Expected: FAIL because `HealthScreen` does not exist.

- [ ] **Step 3: Implement the screen and attempt lifecycle**

Create `HealthScreen.tsx` with the discriminated union below and render a project heading, a short sentence explaining the API check, the exact state label, unavailable copy when present, and a Retry `Pressable` only for settled states.

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { checkHealth, HealthCheckError, type HealthPayload } from "./health/checkHealth";

type ScreenState =
  | { kind: "connecting" }
  | { kind: "connected" }
  | { kind: "unavailable"; message: string };

export type HealthCheck = (options: { signal: AbortSignal }) => Promise<HealthPayload>;
export function HealthScreen({ healthCheck = checkHealth }: { healthCheck?: HealthCheck }) {
  const [state, setState] = useState<ScreenState>({ kind: "connecting" });
  const mounted = useRef(false);
  const attempt = useRef(0);
  const active = useRef<AbortController | null>(null);
  const busy = useRef(false);

  const runCheck = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    const id = ++attempt.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState({ kind: "connecting" });
    try {
      await healthCheck({ signal: controller.signal });
      if (mounted.current && attempt.current === id && !controller.signal.aborted) {
        setState({ kind: "connected" });
      }
    } catch (error) {
      if (!mounted.current || attempt.current !== id || controller.signal.aborted) return;
      const message = error instanceof HealthCheckError ? error.message : "Could not reach the API.";
      setState({ kind: "unavailable", message });
    } finally {
      if (attempt.current === id) busy.current = false;
    }
  }, [healthCheck]);

  useEffect(() => {
    mounted.current = true;
    void runCheck();
    return () => {
      mounted.current = false;
      ++attempt.current;
      active.current?.abort();
      busy.current = false;
    };
  }, [runCheck]);

  return (
    <View style={{ flex: 1, justifyContent: "center", padding: 24, gap: 16 }}>
      <Text accessibilityRole="header">Project Foundation</Text>
      <Text>Check the connection to your local API.</Text>
      <Text accessibilityLiveRegion="polite">
        {state.kind === "connecting" ? "Connecting" : state.kind === "connected" ? "Connected" : "Unavailable"}
      </Text>
      {state.kind === "unavailable" && <Text>{state.message}</Text>}
      {state.kind !== "connecting" && (
        <Pressable accessibilityRole="button" accessibilityLabel="Retry"
          style={{ minHeight: 44, padding: 12 }} onPress={() => void runCheck()}>
          <Text>Retry</Text>
        </Pressable>
      )}
    </View>
  );
}
```

Replace `App.tsx` with:

```tsx
import { HealthScreen } from "./src/HealthScreen";

export default function App() {
  return <HealthScreen />;
}
```

- [ ] **Step 4: Verify state behavior and commit**

```bash
pnpm --dir apps/mobile test --runInBand src/HealthScreen.test.tsx
pnpm --dir apps/mobile test --runInBand
pnpm --dir apps/mobile typecheck
pnpm --dir apps/mobile lint
git add apps/mobile/App.tsx apps/mobile/src
git commit -m "feat: show API connection states"
```

Expected: all component and boundary tests pass; no live API or wall-clock delay is used.

### Task 5: Expose stable root commands and evolve the Phase 0 contract

**Files:**

- Modify: `package.json`
- Modify: `.gitignore`
- Modify: `tests/repository_contract.bats`
- Modify: `pnpm-lock.yaml`

**Interfaces:**

- Consumes: package commands from Tasks 2–4.
- Produces: `pnpm dev:api`, `pnpm dev:mobile`, and root `quality` that covers every Phase 0 and Phase 1 check.

- [ ] **Step 1: Replace only the obsolete repository assertion**

Replace `phase 0 contains no application workspaces` with:

```bash
@test "phase 1 contains the approved application boundaries and root commands" {
  [ -f apps/mobile/package.json ]
  [ -f apps/mobile/.env.example ]
  [ -f apps/api/pyproject.toml ]
  [ -f apps/api/uv.lock ]
  grep -F '"dev:mobile": "pnpm --dir apps/mobile start --port 8081"' package.json
  grep -F '"dev:api": "uv run --directory apps/api uvicorn app.main:app --host 127.0.0.1 --port 8000"' package.json
}
```

Leave all pin, SHA, README, doctor, troubleshooting, roadmap, and Python guidance tests unchanged.

- [ ] **Step 2: Run the contract and observe the missing root commands**

```bash
bats tests/repository_contract.bats
```

Expected: the new Phase 1 test fails on `dev:mobile`; all preserved assertions pass.

- [ ] **Step 3: Add root command composition and local ignores**

Add exact scripts:

```json
"dev:mobile": "pnpm --dir apps/mobile start --port 8081",
"dev:api": "uv run --directory apps/api uvicorn app.main:app --host 127.0.0.1 --port 8000",
"lint:mobile": "pnpm --dir apps/mobile lint",
"lint:api": "uv run --directory apps/api ruff check .",
"typecheck": "pnpm --dir apps/mobile typecheck",
"test:mobile": "pnpm --dir apps/mobile test --runInBand",
"test:api": "uv run --directory apps/api python -m pytest tests",
"build:web": "pnpm --dir apps/mobile export:web"
```

Keep existing `lint` and `test` as the Phase 0-only entry points used by its CI jobs. Set `quality` to `pnpm lint && pnpm test && pnpm lint:mobile && pnpm lint:api && pnpm typecheck && pnpm test:mobile && pnpm test:api && pnpm build:web`, so the complete local gate composes both phases without making the existing static job depend on an unsynced Python environment.

Append these focused ignores:

```gitignore
.expo/
apps/mobile/.env.local
apps/mobile/dist/
__pycache__/
.pytest_cache/
.ruff_cache/
*.pyc
```

- [ ] **Step 4: Verify the root interface and commit**

```bash
bats tests/repository_contract.bats
pnpm install --lockfile-only
pnpm quality
git add package.json pnpm-lock.yaml .gitignore tests/repository_contract.bats
git commit -m "build: add phase 1 root quality commands"
```

Expected: all preserved and new contracts pass; the Expo web export completes non-interactively.

### Task 6: Extend CI without weakening Phase 0

**Files:**

- Modify: `.github/workflows/quality.yml`

**Interfaces:**

- Consumes: frozen `pnpm-lock.yaml`, `apps/api/uv.lock`, root quality commands, and Python 3.14.7.
- Produces: Linux application job proving mobile lint/typecheck/tests/export and API Ruff/tests while the three Phase 0 jobs remain active.

- [ ] **Step 1: Add a repository test for the Phase 1 CI surface**

Add to `tests/repository_contract.bats`:

```bash
@test "workflow runs the locked phase 1 application quality gate" {
  grep -F 'UV_PYTHON_DOWNLOADS: never' .github/workflows/quality.yml
  grep -F 'pipx install uv==0.12.1' .github/workflows/quality.yml
  grep -F 'uv python install 3.14.7' .github/workflows/quality.yml
  grep -F 'uv sync --project apps/api --frozen --python 3.14.7' .github/workflows/quality.yml
  grep -F 'pnpm lint:mobile' .github/workflows/quality.yml
  grep -F 'pnpm typecheck' .github/workflows/quality.yml
  grep -F 'pnpm test:mobile' .github/workflows/quality.yml
  grep -F 'pnpm lint:api' .github/workflows/quality.yml
  grep -F 'pnpm test:api' .github/workflows/quality.yml
  grep -F 'pnpm build:web' .github/workflows/quality.yml
}
```

Run `bats tests/repository_contract.bats`; expect this new test to fail on the first missing line.

- [ ] **Step 2: Add the application job**

Add `application` on `ubuntu-latest`. Reuse the existing full-SHA checkout and setup-node refs, Node 24.20.0, Corepack, and pnpm 11.25.0. Bootstrap the Phase 0 uv version with the runner's preinstalled `pipx`, provision Python before disabling downloads, and run these commands in order:

```yaml
- run: pnpm install --frozen-lockfile
- run: pipx install uv==0.12.1
- run: uv python install 3.14.7
- run: uv sync --project apps/api --frozen --python 3.14.7
  env:
    UV_PYTHON_DOWNLOADS: never
- run: pnpm lint:mobile
- run: pnpm typecheck
- run: pnpm test:mobile
- run: pnpm lint:api
- run: pnpm test:api
- run: pnpm build:web
```

Do not modify or remove `static`, `doctor-unit`, or `doctor-macos-integration`. Verify every `uses:` ref remains exactly 40 hexadecimal characters with the existing contract.

- [ ] **Step 3: Verify CI contracts and commit**

```bash
bats tests/repository_contract.bats
pnpm quality
git add .github/workflows/quality.yml tests/repository_contract.bats
git commit -m "ci: verify phase 1 application boundary"
```

Expected: all local checks pass; the workflow contains four jobs and no simulator or E2E step.

### Task 7: Publish the learner workflow and acceptance record

**Files:**

- Create: `docs/guides/01-project-foundation.md`
- Modify: `README.md`
- Modify: `docs/curriculum-roadmap.md`

**Interfaces:**

- Consumes: exact commands, ports, states, and recovery behavior implemented by Tasks 2–6.
- Produces: one linear guide with copyable setup/start/diagnosis/test/export commands and a dated web/iOS acceptance table; README and roadmap match Phase 1.

- [ ] **Step 1: Write a failing documentation contract**

Add a repository test that requires the guide and checks these literal contracts:

```bash
@test "phase 1 guide documents the two-process recovery journey" {
  guide=docs/guides/01-project-foundation.md
  [ -f "$guide" ]
  grep -F 'pnpm dev:api' "$guide"
  grep -F 'pnpm dev:mobile' "$guide"
  grep -F 'http://localhost:8081' "$guide"
  grep -F 'http://127.0.0.1:8000/health' "$guide"
  grep -F 'EXPO_PUBLIC_API_URL=http://127.0.0.1:8000' "$guide"
  grep -F 'Expo Go version' "$guide"
}
```

Run `bats tests/repository_contract.bats`; expect failure because the guide is missing.

- [ ] **Step 2: Write the complete guide and update entry points**

Write `docs/guides/01-project-foundation.md` in this order: outcome and package ownership; prerequisites linking Phase 0 setup; `pnpm install`, `uv sync --project apps/api --frozen --python 3.14.7`, and `cp apps/mobile/.env.example apps/mobile/.env.local`; explanation that `EXPO_PUBLIC_` values ship to clients and cannot contain secrets; two-terminal startup with API first; web `w` and iOS `i` selection; expected Connecting/Connected/Unavailable and manual Retry behavior; direct `curl http://127.0.0.1:8000/health`; browser CORS explanation naming exact origin; `pnpm quality` and each focused test/export command; port-conflict recovery using `lsof -nP -iTCP:8000 -sTCP:LISTEN` and `lsof -nP -iTCP:8081 -sTCP:LISTEN` followed by stopping the identified owned process rather than accepting another port; cache/config recovery using `pnpm --dir apps/mobile start --port 8081 --clear`; and the exact four-step manual recovery journey from the spec.

End with this initially unchecked record:

```markdown
## Phase 1 acceptance record

| Target | Date | Runtime | Connected | API stopped + Retry → Unavailable | API restarted + Retry → Connected |
| --- | --- | --- | --- | --- | --- |
| Web | — | `http://localhost:8081` | ☐ | ☐ | ☐ |
| iOS Simulator | — | iPhone 17 Pro, iOS 26, Expo Go version: — | ☐ | ☐ | ☐ |
```

Update README's current checkpoint to Phase 1, state that the health boundary is runnable, link `docs/guides/01-project-foundation.md`, and keep the Phase 0 setup link. In roadmap Phase 2, replace Docker Compose with the two host-process boundary and replace the service integration smoke wording with in-process API contract tests plus mobile component tests. Change no later phase.

- [ ] **Step 3: Verify documentation and commit**

```bash
bats tests/repository_contract.bats
pnpm lint:markdown
pnpm lint:links
git add docs/guides/01-project-foundation.md README.md docs/curriculum-roadmap.md tests/repository_contract.bats
git commit -m "docs: add project foundation guide"
```

Expected: documentation and every repository contract pass; Phase 0 guides remain linked and unchanged.

### Task 8: Run final review, manual acceptance, CI, and checkpoint tagging

**Files:**

- Modify after observation: `docs/guides/01-project-foundation.md`

**Interfaces:**

- Consumes: complete `codex/phase-01-foundation` branch and reference Mac.
- Produces: recorded web/iOS acceptance, passing CI, Sol-reviewed branch, and annotated `phase-01-foundation` tag on the integrated commit.

- [ ] **Step 1: Run fresh automated verification**

```bash
pnpm install --frozen-lockfile
UV_PYTHON_DOWNLOADS=never uv sync --project apps/api --frozen --python 3.14.7
pnpm quality
git diff --check phase-00-environment...HEAD
git merge-base --is-ancestor phase-00-environment HEAD
git status --short
```

Expected: every Phase 0 and Phase 1 check passes, diff check is clean, ancestry succeeds, and the worktree is clean.

- [ ] **Step 2: Complete the recovery journey on both targets**

In terminal one run `pnpm dev:api`; in terminal two run `pnpm dev:mobile`. On web, then on the designated iPhone 17 Pro iOS Simulator: observe Connecting then Connected; stop API with Ctrl-C; select Retry and observe Unavailable; restart `pnpm dev:api`; select Retry and observe Connecting then Connected. Confirm the browser request succeeds from `http://localhost:8081` and direct curl returns exactly `{"status":"ok"}`. Record the date, check every table cell, and replace the iOS runtime dash with the installed Expo Go version shown by the simulator.

- [ ] **Step 3: Commit the observed acceptance evidence and repeat docs checks**

```bash
git add docs/guides/01-project-foundation.md
git commit -m "docs: record phase 1 manual acceptance"
pnpm lint:markdown
pnpm lint:links
```

Expected: both target rows contain dates, checked cells, and concrete runtime data.

- [ ] **Step 4: Obtain final Sol review and address only verified findings**

Dispatch a `gpt-5.6-sol` whole-branch reviewer against `phase-00-environment...HEAD`, with the approved spec and this plan. If integration or a non-mechanical defect requires redesign, route it to `gpt-5.6-terra`; rerun the focused failing check and then `pnpm quality` after every fix.

- [ ] **Step 5: Publish the branch and require GitHub Actions success**

```bash
git push --set-upstream origin codex/phase-01-foundation
gh pr create --base main --head codex/phase-01-foundation --title "feat: establish phase 1 project foundation" --body "Adds the Expo web/iOS health screen, FastAPI health contract, two-process local workflow, Phase 1 quality gates, and recorded manual acceptance."
gh pr checks --watch
```

Expected: all `static`, `doctor-unit`, `doctor-macos-integration`, and `application` checks pass. Merge through the repository's normal reviewed PR workflow.

- [ ] **Step 6: Tag only the integrated, verified checkpoint**

```bash
reviewed_head="$(git rev-parse HEAD)"
git fetch origin main
git merge-base --is-ancestor "$reviewed_head" origin/main
git merge-base --is-ancestor phase-00-environment origin/main
git tag -a phase-01-foundation origin/main -m "Phase 1: project foundation"
git push origin phase-01-foundation
```

Expected: `origin/main` contains the exact reviewed branch head, and the tag points at that integrated commit containing the checked acceptance record and passing CI. Do not merge or switch to the stale local `main` planning checkout.

Use a merge that preserves reviewed commit ancestry. Before tagging, inspect the successful `quality` run for the exact fetched `origin/main` commit, not merely the PR head. If the branch was squash-merged, stop and have the controller verify the integrated tree and CI against the reviewed tree before changing the ancestry gate; do not silently skip it.

## Spec coverage and planning verification

- Baseline and workspace ownership: Tasks 1, 2, 3, and 5.
- Exact health contract and explicit CORS: Task 2.
- Timeout, response validation, cancellation, and cleanup: Task 3.
- States, Retry from both settled states, and stale protection: Task 4.
- Separate host commands, version pins, and retained checks: Tasks 5 and 6.
- Guide, entry points, and provisional roadmap: Task 7.
- Web/iOS recovery, final review, CI, and checkpoint: Task 8.

Package metadata and platform requirements were checked during planning. The implementation snippets are a starting point for the prescribed red/green test cycles, not evidence that application tests or acceptance have already passed. Native acceptance must record the actual iOS 26.5 runtime and SDK-compatible Expo Go version; a newer Expo Go that cannot load SDK 57 is not a substitute.

## Verified references

- [Expo SDK 57 platform requirements](https://docs.expo.dev/versions/v57.0.0/)
- [Expo TypeScript templates](https://docs.expo.dev/more/create-expo/)
- [Expo unit testing setup](https://docs.expo.dev/develop/unit-testing/)
- [React Native Testing Library async render](https://oss.callstack.com/react-native-testing-library/docs/api/render)
- [React Native Testing Library async events](https://oss.callstack.com/react-native-testing-library/docs/api/events/fire-event)
- [FastAPI Python support and releases](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI CORS configuration](https://fastapi.tiangolo.com/tutorial/cors/)

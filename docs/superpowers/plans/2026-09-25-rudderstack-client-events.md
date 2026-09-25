# Phase 30a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send four deliberate client events from Expo web through RudderStack Cloud into a Terraform-managed BigQuery dataset, reachable without keys, and join them to the Phase 26 server events in two curated views.

**Architecture:** One wrapper module (`apps/mobile/src/analytics/`) is the only code that touches the RudderStack SDK; it applies opt-out consent and Global Privacy Control, and does nothing without a write key. Screens call `analytics.track/identify/reset`. Terraform adds an opt-in `rudderstack` root: a raw dataset, a staging bucket, a loader service account, and a workload identity pool that trusts only RudderStack's AWS account and the learner's workspace; curated views are gated behind a second apply. A deterministic Python script sends backdated synthetic client events through RudderStack's HTTP API, aligned with the Phase 28b outbox seed.

**Tech Stack:** Expo 57 / React Native Web, `@rudderstack/analytics-js` 3.34.2, Jest + Testing Library, Terraform 1.14.7 with Google provider 8.2.0 (mock tests), BigQuery SQL, Python 3.14 stdlib + pytest, Markdown.

**Spec:** [Phase 30a design](../specs/2026-09-25-rudderstack-client-events-design.md)

## Global Constraints

- **Event names (exact):** `auth_screen_viewed` (`mode`: `signin` | `signup`), `signup_submitted` (no properties), `signin_submitted` (no properties), `suggestion_requested` (`workflow_key`). All `track`. No other events, no free text, no traits.
- **Identity:** `identify(user.id)` with exactly one argument; `user.id` is `users.public_id` (= Phase 26 `user_key`). `reset()` clears the anonymous ID too.
- **Consent:** opt-out, default on; stored on web under `localStorage` key `analytics.consent` as `"on"` / `"off"`; `navigator.globalPrivacyControl === true` forces off.
- **No sends** when `EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY` or `EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL` is unset or empty, with consent off, or under GPC.
- **Telemetry never throws** into the UI.
- **Terraform:** `rudderstack` requires `analytics`; `workspace_id` must match `^[A-Za-z0-9]+$` (it's interpolated into a CEL condition). RudderStack AWS account `422074288268`. Attribute mapping `google.subject = assertion.arn`, `attribute.workspace = assertion.arn.extract('assumed-role/data-plane-service-account/{workspace}')`. All BigQuery dataset grants via `google_bigquery_dataset_access`. Staging bucket lifecycle: delete at 7 days.
- **Curated views** exist only when `rudderstack.curated_views = true`, and select no `context_*` columns.
- **Synthetic prefixes:** user IDs `00000000-0000-4000-8000-` + 12 digits (the 28b users); anonymous IDs `00000000-0000-4000-9000-` + 12 digits. No synthetic event at or after `2026-09-25T00:00:00Z`.
- **Randomness:** only the 28b `md5` rule: first 7 hex chars of `md5(seed)` as an integer, divided by 2^28.
- **Stop and ask the learner** before anything touches cloud resources, RudderStack, or Cloudflare. Invented data only. Keep `.pi/` untouched.
- **Commands:**
  - `pnpm test:mobile`, `pnpm typecheck`, `pnpm lint:mobile`
  - `pnpm test:api` (needs the test database: `pnpm db:test:up`, or reuse a running one on 5433)
  - `PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox test -no-color` (symlink `infra/terraform/.local/bin` to the main checkout's binary and `terraform init -backend=false` first, as in 28b)
  - `pnpm lint:markdown && pnpm lint:links`

## Review Focus

1. **Browser storage unavailable** (Safari private mode, blocked site data): consent reads and writes throw. The app must keep working and treat consent as the default. Pinned in Task 1.
2. **A second tap while a suggestion request is in flight** must not record a tap that sent nothing: tracked taps equal requests sent. Pinned in Task 3.
3. **A revoked stored session** must not `identify` anyone. Pinned in Task 3.
4. **A workspace ID containing quotes** would rewrite the WIF trust condition; it must fail validation. Pinned in Task 4.
5. **An empty-string write key** (a blank Cloudflare variable) must behave as unset. Pinned in Task 1.

---

### Task 1: Analytics wrapper and web SDK adapter

**Files:**

- Create: `apps/mobile/src/analytics/analytics.ts`, `apps/mobile/src/analytics/sdk.ts`, `apps/mobile/src/analytics/sdk.web.ts`, `apps/mobile/src/analytics/index.ts`
- Test: `apps/mobile/src/analytics/analytics.test.ts`, `apps/mobile/src/analytics/sdk.web.test.ts`
- Modify: `apps/mobile/package.json` (dependency), `pnpm-lock.yaml`, `apps/mobile/.env.example`

**Interfaces:**

- Produces:
  - `type EventProperties = { auth_screen_viewed: { mode: "signin" | "signup" }; signup_submitted: Record<string, never>; signin_submitted: Record<string, never>; suggestion_requested: { workflow_key: string } }`, `type EventName = keyof EventProperties`
  - `type AnalyticsSdk = { track: (name: EventName, properties: Record<string, string>) => void; identify: (userId: string) => void; reset: () => void }`
  - `type ConsentStore = { get: () => boolean | null; set: (enabled: boolean) => void }`
  - `type ConsentState = { available: boolean; enabled: boolean; gpc: boolean }`
  - `type Analytics = { track: <N extends EventName>(name: N, properties: EventProperties[N]) => void; identify: (userId: string) => void; reset: () => void; consent: () => ConsentState; setConsent: (enabled: boolean) => void }`
  - `createAnalytics(options: { sdk: AnalyticsSdk | null; consentStore: ConsentStore; gpc: () => boolean }): Analytics`
  - `createMemoryConsentStore(initial?: boolean | null): ConsentStore`, `webConsentStore: ConsentStore`, `browserGpc(): boolean`
  - `createSdk(config?: { writeKey?: string; dataPlaneUrl?: string }): AnalyticsSdk | null` (from `./sdk`; `sdk.ts` always returns `null` until 30b)
  - `analytics: Analytics` (singleton, from `src/analytics/index.ts`, the module later tasks import as `../analytics`)

- [ ] **Step 1: Add the dependency**

Run: `pnpm --dir apps/mobile add @rudderstack/analytics-js@3.34.2 --save-exact`
Expected: `apps/mobile/package.json` lists `"@rudderstack/analytics-js": "3.34.2"`; lockfile updated.

Append to `apps/mobile/.env.example`:

```sh
# Phase 30a (optional): leave unset locally so nothing is sent.
# EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY=
# EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL=
```

- [ ] **Step 2: Write the failing wrapper tests** in `apps/mobile/src/analytics/analytics.test.ts`

```ts
import {
  createAnalytics,
  createMemoryConsentStore,
  type AnalyticsSdk,
  type ConsentStore,
} from "./analytics";

const makeSdk = (): AnalyticsSdk & { [K in keyof AnalyticsSdk]: jest.Mock } => ({
  track: jest.fn(),
  identify: jest.fn(),
  reset: jest.fn(),
});

const make = (options?: { store?: ConsentStore; gpc?: boolean; sdk?: AnalyticsSdk | null }) => {
  const sdk = options?.sdk === undefined ? makeSdk() : options.sdk;
  const store = options?.store ?? createMemoryConsentStore();
  const analytics = createAnalytics({ sdk, consentStore: store, gpc: () => options?.gpc ?? false });
  return { analytics, sdk, store };
};

it("does nothing and reports unavailable without an SDK", () => {
  const { analytics } = make({ sdk: null });
  expect(() => {
    analytics.track("signup_submitted", {});
    analytics.identify("u-1");
    analytics.reset();
    analytics.setConsent(false);
  }).not.toThrow();
  expect(analytics.consent()).toEqual({ available: false, enabled: true, gpc: false });
});

it("sends by default (opt-out) with only the typed properties", () => {
  const { analytics, sdk } = make();
  analytics.track("auth_screen_viewed", { mode: "signup" });
  analytics.track("suggestion_requested", { workflow_key: "wf-1" });
  expect(sdk!.track).toHaveBeenNthCalledWith(1, "auth_screen_viewed", { mode: "signup" });
  expect(sdk!.track).toHaveBeenNthCalledWith(2, "suggestion_requested", { workflow_key: "wf-1" });
});

it("identifies with the id only, never traits", () => {
  const { analytics, sdk } = make();
  analytics.identify("6fc33b84-16a8-4d8e-ae94-fc50bb457d72");
  expect(sdk!.identify.mock.calls).toEqual([["6fc33b84-16a8-4d8e-ae94-fc50bb457d72"]]);
});

it("stops sending and resets when the user opts out", () => {
  const { analytics, sdk, store } = make();
  analytics.setConsent(false);
  expect(store.get()).toBe(false);
  expect(sdk!.reset).toHaveBeenCalledTimes(1);
  analytics.track("signup_submitted", {});
  analytics.identify("u-1");
  expect(sdk!.track).not.toHaveBeenCalled();
  expect(sdk!.identify).not.toHaveBeenCalled();
  expect(analytics.consent()).toEqual({ available: true, enabled: false, gpc: false });
  analytics.setConsent(true);
  analytics.track("signup_submitted", {});
  expect(sdk!.track).toHaveBeenCalledTimes(1);
});

it("treats Global Privacy Control as off even when consent is stored on", () => {
  const { analytics, sdk } = make({ store: createMemoryConsentStore(true), gpc: true });
  analytics.track("signup_submitted", {});
  analytics.identify("u-1");
  expect(sdk!.track).not.toHaveBeenCalled();
  expect(sdk!.identify).not.toHaveBeenCalled();
  expect(analytics.consent()).toEqual({ available: true, enabled: false, gpc: true });
});

it("resets on sign-out even when consent is off", () => {
  const { analytics, sdk } = make({ store: createMemoryConsentStore(false) });
  analytics.reset();
  expect(sdk!.reset).toHaveBeenCalledTimes(1);
});

it("never throws when the SDK throws", () => {
  const sdk = makeSdk();
  sdk.track.mockImplementation(() => { throw new Error("blocked"); });
  sdk.identify.mockImplementation(() => { throw new Error("blocked"); });
  sdk.reset.mockImplementation(() => { throw new Error("blocked"); });
  const { analytics } = make({ sdk });
  expect(() => {
    analytics.track("signin_submitted", {});
    analytics.identify("u-1");
    analytics.reset();
    analytics.setConsent(false);
  }).not.toThrow();
});

it("keeps working with the default when browser storage throws", () => {
  const store: ConsentStore = {
    get: () => { throw new Error("SecurityError"); },
    set: () => { throw new Error("SecurityError"); },
  };
  const { analytics, sdk } = make({ store });
  expect(() => analytics.setConsent(false)).not.toThrow();
  expect(analytics.consent().enabled).toBe(true);
  analytics.track("signup_submitted", {});
  expect(sdk!.track).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics/analytics.test.ts`
Expected: FAIL with "Cannot find module './analytics'".

- [ ] **Step 4: Implement** `apps/mobile/src/analytics/analytics.ts`

```ts
// Phase 30a: the only analytics surface screens use. Opt-out consent,
// Global Privacy Control, and no-op without an SDK live here, so switching to
// opt-in (EU) later changes one function. Event names and properties are a
// fixed contract: no free text, no traits.

export type EventProperties = {
  auth_screen_viewed: { mode: "signin" | "signup" };
  signup_submitted: Record<string, never>;
  signin_submitted: Record<string, never>;
  suggestion_requested: { workflow_key: string };
};

export type EventName = keyof EventProperties;

/** The SDK calls the wrapper needs; one adapter per platform (sdk.web.ts). */
export type AnalyticsSdk = {
  track: (name: EventName, properties: Record<string, string>) => void;
  identify: (userId: string) => void;
  reset: () => void;
};

export type ConsentStore = {
  get: () => boolean | null;
  set: (enabled: boolean) => void;
};

export type ConsentState = { available: boolean; enabled: boolean; gpc: boolean };

export type Analytics = {
  track: <N extends EventName>(name: N, properties: EventProperties[N]) => void;
  identify: (userId: string) => void;
  reset: () => void;
  consent: () => ConsentState;
  setConsent: (enabled: boolean) => void;
};

// Telemetry never breaks the app: every SDK and storage call is isolated.
const safely = (call: () => void): void => {
  try {
    call();
  } catch (error) {
    if (__DEV__) console.debug("analytics call dropped", error);
  }
};

const attempt = <T,>(read: () => T, fallback: T): T => {
  try {
    return read();
  } catch {
    return fallback;
  }
};

export function createAnalytics({
  sdk,
  consentStore,
  gpc,
}: {
  sdk: AnalyticsSdk | null;
  consentStore: ConsentStore;
  gpc: () => boolean;
}): Analytics {
  const consent = (): ConsentState => {
    const stored = attempt<boolean | null>(consentStore.get, null);
    const gpcOn = attempt(gpc, false);
    return { available: sdk !== null, enabled: !gpcOn && (stored ?? true), gpc: gpcOn };
  };
  const active = (): AnalyticsSdk | null => (sdk !== null && consent().enabled ? sdk : null);

  return {
    track: (name, properties) => {
      const live = active();
      if (live) safely(() => live.track(name, { ...properties } as Record<string, string>));
    },
    identify: (userId) => {
      const live = active();
      if (live) safely(() => live.identify(userId));
    },
    reset: () => {
      if (sdk) safely(() => sdk.reset());
    },
    consent,
    setConsent: (enabled) => {
      safely(() => consentStore.set(enabled));
      if (!enabled && sdk) safely(() => sdk.reset());
    },
  };
}

export function createMemoryConsentStore(initial: boolean | null = null): ConsentStore {
  let value = initial;
  return {
    get: () => value,
    set: (enabled) => {
      value = enabled;
    },
  };
}

const CONSENT_KEY = "analytics.consent";

export const webConsentStore: ConsentStore = {
  get: () => {
    const stored = localStorage.getItem(CONSENT_KEY);
    return stored === null ? null : stored === "on";
  },
  set: (enabled) => localStorage.setItem(CONSENT_KEY, enabled ? "on" : "off"),
};

export const browserGpc = (): boolean =>
  typeof navigator !== "undefined" &&
  (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true;
```

Note: `consent()` reads through `attempt`, so the "storage throws" test sees `stored = null` → default on, and `setConsent(false)` failing to persist leaves consent on. That's the intended default when the browser won't store the choice; the guide records it.

- [ ] **Step 5: Run to verify they pass**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics/analytics.test.ts`
Expected: PASS, 8 tests.

- [ ] **Step 6: Write the failing SDK adapter tests** in `apps/mobile/src/analytics/sdk.web.test.ts`

```ts
const mockLoad = jest.fn();
const mockTrack = jest.fn();
const mockIdentify = jest.fn();
const mockReset = jest.fn();

jest.mock("@rudderstack/analytics-js/bundled", () => ({
  RudderAnalytics: jest.fn().mockImplementation(() => ({
    load: mockLoad,
    track: mockTrack,
    identify: mockIdentify,
    reset: mockReset,
  })),
}));

import { createSdk } from "./sdk.web";

beforeEach(() => jest.clearAllMocks());

it("returns null and loads nothing without both settings", () => {
  expect(createSdk({ writeKey: undefined, dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(createSdk({ writeKey: "key", dataPlaneUrl: undefined })).toBeNull();
  expect(createSdk({ writeKey: "", dataPlaneUrl: "https://dp.example.test" })).toBeNull();
  expect(mockLoad).not.toHaveBeenCalled();
});

it("loads cloud mode with localStorage and forwards calls without traits", () => {
  const sdk = createSdk({ writeKey: "key", dataPlaneUrl: "https://dp.example.test" });
  expect(mockLoad).toHaveBeenCalledWith(
    "key",
    "https://dp.example.test",
    expect.objectContaining({ storage: { type: "localStorage" }, loadIntegration: false }),
  );
  sdk!.track("suggestion_requested", { workflow_key: "wf-1" });
  sdk!.identify("u-1");
  sdk!.reset();
  expect(mockTrack).toHaveBeenCalledWith("suggestion_requested", { workflow_key: "wf-1" });
  expect(mockIdentify.mock.calls).toEqual([["u-1"]]);
  expect(mockReset).toHaveBeenCalledWith({ entries: { anonymousId: true } });
});

it("returns null when the SDK fails to load", () => {
  mockLoad.mockImplementationOnce(() => { throw new Error("blocked"); });
  expect(createSdk({ writeKey: "key", dataPlaneUrl: "https://dp.example.test" })).toBeNull();
});
```

If Jest can't resolve the `bundled` subpath export, add `{ virtual: true }` as the third `jest.mock` argument and ledger a ruling.

- [ ] **Step 7: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics/sdk.web.test.ts`
Expected: FAIL with "Cannot find module './sdk.web'".

- [ ] **Step 8: Implement the adapters and singleton**

`apps/mobile/src/analytics/sdk.web.ts`:

```ts
import { RudderAnalytics } from "@rudderstack/analytics-js/bundled";
import type { AnalyticsSdk } from "./analytics";

// Phase 30a: RudderStack JavaScript SDK (web). The bundled build ships its
// plugins, so no plugin scripts load from a CDN at runtime. Cloud mode only
// (no device-mode destinations); the anonymous ID lives in localStorage.
export function createSdk(
  config: { writeKey?: string; dataPlaneUrl?: string } = {
    writeKey: process.env.EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY,
    dataPlaneUrl: process.env.EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL,
  },
): AnalyticsSdk | null {
  const { writeKey, dataPlaneUrl } = config;
  if (!writeKey || !dataPlaneUrl) return null;
  try {
    const rudder = new RudderAnalytics();
    rudder.load(writeKey, dataPlaneUrl, {
      storage: { type: "localStorage" },
      loadIntegration: false,
    });
    return {
      track: (name, properties) => rudder.track(name, properties),
      identify: (userId) => rudder.identify(userId),
      reset: () => rudder.reset({ entries: { anonymousId: true } }),
    };
  } catch {
    return null;
  }
}
```

`apps/mobile/src/analytics/sdk.ts`:

```ts
import type { AnalyticsSdk } from "./analytics";

// Native platforms send nothing until Phase 30b adds the React Native SDK.
export function createSdk(): AnalyticsSdk | null {
  return null;
}
```

`apps/mobile/src/analytics/index.ts`:

```ts
import { Platform } from "react-native";
import { browserGpc, createAnalytics, createMemoryConsentStore, webConsentStore } from "./analytics";
import { createSdk } from "./sdk";

export const analytics = createAnalytics({
  sdk: createSdk(),
  consentStore: Platform.OS === "web" ? webConsentStore : createMemoryConsentStore(),
  gpc: Platform.OS === "web" ? browserGpc : () => false,
});
```

Metro resolves `./sdk` to `sdk.web.ts` on web and `sdk.ts` elsewhere; TypeScript sees `sdk.ts`, whose signature is compatible.

- [ ] **Step 9: Run tests, typecheck, lint, and a web export**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics && pnpm typecheck && pnpm lint:mobile`
Expected: PASS (11 tests), no type or lint errors.

Run: `EXPO_NO_DOTENV=1 EXPO_PUBLIC_API_URL=https://api.example.test EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY=test-key EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL=https://dp.example.test pnpm --dir apps/mobile exec expo export --platform web --output-dir /tmp/phase30a-web && grep -l "dp.example.test" /tmp/phase30a-web/_expo/static/js/web/*.js && rm -rf /tmp/phase30a-web`
Expected: export succeeds and one bundle contains the data plane URL (proves Metro resolved `sdk.web.ts` and the `bundled` export). If Metro can't resolve `@rudderstack/analytics-js/bundled`, switch both import and mock to `@rudderstack/analytics-js`, ledger a ruling, and note in the guide that plugins then load from RudderStack's CDN.

- [ ] **Step 10: Commit**

```bash
git add apps/mobile/package.json pnpm-lock.yaml apps/mobile/.env.example apps/mobile/src/analytics
git commit -m "feat(mobile): add consent-aware RudderStack analytics wrapper for web (phase 30a)"
```

---

### Task 2: Consent switch

**Files:**

- Create: `apps/mobile/src/analytics/AnalyticsConsentSwitch.tsx`
- Test: `apps/mobile/src/analytics/AnalyticsConsentSwitch.test.tsx`

**Interfaces:**

- Consumes: `Analytics`, `ConsentState` from `./analytics`; `analytics` from `./index`.
- Produces: `AnalyticsConsentSwitch({ analytics?: Analytics }): React.JSX.Element | null`, accessibility label `"Share usage analytics"`.

- [ ] **Step 1: Write the failing tests**

```tsx
import { fireEvent, render, screen } from "@testing-library/react-native";
import { createAnalytics, createMemoryConsentStore } from "./analytics";
import { AnalyticsConsentSwitch } from "./AnalyticsConsentSwitch";

const sdk = () => ({ track: jest.fn(), identify: jest.fn(), reset: jest.fn() });

it("renders nothing when analytics is unavailable", async () => {
  const analytics = createAnalytics({ sdk: null, consentStore: createMemoryConsentStore(), gpc: () => false });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  expect(screen.queryByLabelText("Share usage analytics")).toBeNull();
});

it("defaults on and turns analytics off", async () => {
  const store = createMemoryConsentStore();
  const client = sdk();
  const analytics = createAnalytics({ sdk: client, consentStore: store, gpc: () => false });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  const toggle = screen.getByLabelText("Share usage analytics");
  expect(toggle).toHaveProp("value", true);
  await fireEvent(toggle, "valueChange", false);
  expect(store.get()).toBe(false);
  expect(client.reset).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Share usage analytics")).toHaveProp("value", false);
});

it("shows off and disabled under Global Privacy Control", async () => {
  const analytics = createAnalytics({ sdk: sdk(), consentStore: createMemoryConsentStore(true), gpc: () => true });
  await render(<AnalyticsConsentSwitch analytics={analytics} />);
  const toggle = screen.getByLabelText("Share usage analytics");
  expect(toggle).toHaveProp("value", false);
  expect(toggle).toHaveProp("disabled", true);
  expect(screen.getByText("Off: your browser sends Global Privacy Control.")).toBeTruthy();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics/AnalyticsConsentSwitch.test.tsx`
Expected: FAIL with "Cannot find module './AnalyticsConsentSwitch'".

- [ ] **Step 3: Implement**

```tsx
import { useState } from "react";
import { StyleSheet, Switch, Text, View } from "react-native";
import type { Analytics } from "./analytics";
import { analytics as defaultAnalytics } from "./index";

export function AnalyticsConsentSwitch({
  analytics = defaultAnalytics,
}: {
  analytics?: Analytics;
}): React.JSX.Element | null {
  const [state, setState] = useState(() => analytics.consent());
  if (!state.available) return null;
  return (
    <View style={styles.row}>
      <Text style={styles.label}>
        {state.gpc ? "Off: your browser sends Global Privacy Control." : "Share usage analytics"}
      </Text>
      <Switch
        accessibilityLabel="Share usage analytics"
        value={state.enabled}
        disabled={state.gpc}
        onValueChange={(next) => {
          analytics.setConsent(next);
          setState(analytics.consent());
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignItems: "center",
    flexDirection: "row",
    gap: 12,
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingVertical: 4,
  },
  label: {
    color: "#42526b",
    flex: 1,
    fontSize: 14,
  },
});
```

- [ ] **Step 4: Run to verify they pass**

Run: `pnpm --dir apps/mobile test --runInBand src/analytics`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/mobile/src/analytics/AnalyticsConsentSwitch.tsx apps/mobile/src/analytics/AnalyticsConsentSwitch.test.tsx
git commit -m "feat(mobile): add opt-out analytics consent switch with GPC (phase 30a)"
```

---

### Task 3: Instrument auth, session identity, and suggestion taps

**Files:**

- Modify: `apps/mobile/src/auth/AuthScreen.tsx`, `apps/mobile/src/auth/AuthProvider.tsx`, `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.tsx` (`startSuggestion`, ~line 1521)
- Test: `apps/mobile/src/auth/AuthScreen.test.tsx`, `apps/mobile/src/auth/AuthProvider.test.tsx`, `apps/mobile/src/todoWorkflows/TodoWorkflowScreen.test.tsx`

**Interfaces:**

- Consumes: `analytics` from `../analytics`; `AnalyticsConsentSwitch` from `../analytics/AnalyticsConsentSwitch`.

Each test file mocks the singleton. Add near the top of all three test files (after existing `jest.mock` calls):

```ts
jest.mock("../analytics", () => ({
  analytics: {
    track: jest.fn(),
    identify: jest.fn(),
    reset: jest.fn(),
    consent: jest.fn(() => ({ available: true, enabled: true, gpc: false })),
    setConsent: jest.fn(),
  },
}));

const mockAnalytics = () =>
  (jest.requireMock("../analytics") as { analytics: Record<string, jest.Mock> }).analytics;

beforeEach(() => {
  Object.values(mockAnalytics()).forEach((fn) => fn.mockClear());
});
```

- [ ] **Step 1: Write the failing AuthScreen tests** (append to `AuthScreen.test.tsx`)

```tsx
describe("analytics", () => {
  it("records the auth screen view on mount and on mode switch", async () => {
    await setup();
    expect(mockAnalytics().track.mock.calls).toEqual([["auth_screen_viewed", { mode: "signin" }]]);
    await fireEvent.press(screen.getByRole("button", { name: "New here? Create an account." }));
    expect(mockAnalytics().track).toHaveBeenLastCalledWith("auth_screen_viewed", { mode: "signup" });
  });

  it("records no submit when validation fails", async () => {
    await setup();
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
    expect(mockAnalytics().track.mock.calls.map(([name]) => name)).toEqual(["auth_screen_viewed"]);
  });

  it("records signup submit, identifies the new user, and sends no typed text", async () => {
    const { signup } = await setup();
    await fireEvent.press(screen.getByRole("button", { name: "New here? Create an account." }));
    await fireEvent.changeText(screen.getByLabelText("Real name (optional)"), "Real Person");
    await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
    await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
    await fireEvent.press(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(signup).toHaveBeenCalled());
    await waitFor(() => expect(mockAnalytics().identify.mock.calls).toEqual([[user.id]]));
    expect(mockAnalytics().track).toHaveBeenCalledWith("signup_submitted", {});
    const sent = JSON.stringify([mockAnalytics().track.mock.calls, mockAnalytics().identify.mock.calls]);
    expect(sent).not.toMatch(/alice|long-enough-password|Real Person/);
  });

  it("records sign-in submit and leaves identify to the provider", async () => {
    const { login } = await setup();
    await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
    await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(login).toHaveBeenCalled());
    expect(mockAnalytics().track).toHaveBeenCalledWith("signin_submitted", {});
    expect(mockAnalytics().identify).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/auth/AuthScreen.test.tsx`
Expected: FAIL on the four new tests (no track calls); existing tests pass.

- [ ] **Step 3: Implement in `AuthScreen.tsx`**

Change the React import to `import { useEffect, useRef, useState } from "react";`, add `import { analytics } from "../analytics";`, then:

```tsx
  // One view per mount and per mode switch (Phase 30a funnel entry).
  useEffect(() => {
    analytics.track("auth_screen_viewed", { mode });
  }, [mode]);
```

In `submit`, immediately after `busy.current = true;`:

```ts
    analytics.track(mode === "signin" ? "signin_submitted" : "signup_submitted", {});
```

In the success branch's `else` (signup), first line:

```ts
          analytics.identify((result as AuthUser).id);
```

- [ ] **Step 4: Run to verify they pass**

Run: `pnpm --dir apps/mobile test --runInBand src/auth/AuthScreen.test.tsx`
Expected: PASS.

- [ ] **Step 5: Write the failing AuthProvider tests** (append to `AuthProvider.test.tsx`)

```tsx
describe("analytics identity", () => {
  it("identifies a restored session by user id only", async () => {
    const storage = createMemoryTokenStorage();
    await storage.set("tok-1");
    await renderProvider({ storage });
    await waitFor(() => expect(screen.getByText("Welcome, alice")).toBeTruthy());
    expect(mockAnalytics().identify.mock.calls).toEqual([[alice.id]]);
  });

  it("does not identify when the stored session is revoked", async () => {
    const authApi = makeAuthApi();
    authApi.fetchMe.mockRejectedValueOnce(new TodoApiError("auth-required", "Please sign in again."));
    const storage = createMemoryTokenStorage();
    await storage.set("tok-1");
    await renderProvider({ authApi, storage });
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(mockAnalytics().identify).not.toHaveBeenCalled();
  });

  it("identifies after sign-in and resets at sign-out", async () => {
    await renderProvider();
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    await fireEvent.changeText(screen.getByLabelText("Username"), "alice");
    await fireEvent.changeText(screen.getByLabelText("Password"), "long-enough-password");
    await fireEvent.press(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByText("Welcome, alice")).toBeTruthy());
    expect(mockAnalytics().identify.mock.calls).toEqual([[alice.id]]);
    await fireEvent.press(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByLabelText("Username")).toBeTruthy());
    expect(mockAnalytics().reset).toHaveBeenCalledTimes(1);
  });

  it("shows the consent switch when signed in", async () => {
    const storage = createMemoryTokenStorage();
    await storage.set("tok-1");
    await renderProvider({ storage });
    await waitFor(() => expect(screen.getByLabelText("Share usage analytics")).toBeTruthy());
  });
});
```

- [ ] **Step 6: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/auth/AuthProvider.test.tsx`
Expected: FAIL on the new identify/reset/switch tests (the revoked-session test passes already; that's fine, it pins behavior).

- [ ] **Step 7: Implement in `AuthProvider.tsx`**

Add imports:

```ts
import { analytics } from "../analytics";
import { AnalyticsConsentSwitch } from "../analytics/AnalyticsConsentSwitch";
```

In the restore effect, after `setStatus("signed-in");`: `analytics.identify(restored.id);`

In `handleAuthenticated`, after `setStatus("signed-in");` (inside the non-superseded path): `analytics.identify(session.user.id);`

In `cleanupSession`, after `bumpEpoch();` (the non-superseded path): `analytics.reset();`

In the signed-in render, inside `<SafeAreaView style={styles.headerSafe}>` after the header `View`: `<AnalyticsConsentSwitch />`

- [ ] **Step 8: Run to verify they pass**

Run: `pnpm --dir apps/mobile test --runInBand src/auth`
Expected: PASS.

- [ ] **Step 9: Write the failing suggestion-tap tests** (append to `TodoWorkflowScreen.test.tsx`)

```tsx
describe("suggestion tap analytics", () => {
  it("records one tap with the workflow key when a suggestion request is sent", async () => {
    const api = makeApi();
    await renderHost(api);
    await driveToCollect(api);
    api.getWorkflow.mockResolvedValue(collectWorkflow);
    api.getSuggestion.mockResolvedValueOnce(readySuggestion);
    api.suggestWorkflow.mockResolvedValueOnce(readySuggestion);

    await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
    await waitFor(() => expect(api.suggestWorkflow).toHaveBeenCalled());
    expect(mockAnalytics().track.mock.calls).toEqual([
      ["suggestion_requested", { workflow_key: WORKFLOW_ID }],
    ]);
  });

  it("records taps only for requests actually sent", async () => {
    const api = makeApi();
    const pending = deferred<WorkflowSuggestion>();
    await renderHost(api);
    await driveToCollect(api);
    api.getWorkflow.mockResolvedValue(collectWorkflow);
    api.suggestWorkflow.mockReturnValueOnce(pending.promise);

    await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
    await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
    await waitFor(() => expect(api.suggestWorkflow).toHaveBeenCalled());
    expect(mockAnalytics().track).toHaveBeenCalledTimes(api.suggestWorkflow.mock.calls.length);
    await act(async () => pending.resolve(readySuggestion));
  });
});
```

Use the file's existing helpers (`makeApi`, `renderHost`, `driveToCollect`, `collectWorkflow`, `readySuggestion`, `deferred`, `WORKFLOW_ID`); read the "offers suggestions only from the server-supported task breakdown template" test (~line 876) for the exact setup, and mirror it if a helper's signature differs.

- [ ] **Step 10: Run to verify they fail**

Run: `pnpm --dir apps/mobile test --runInBand src/todoWorkflows/TodoWorkflowScreen.test.tsx -t "suggestion tap analytics"`
Expected: FAIL (no track calls).

- [ ] **Step 11: Implement in `TodoWorkflowScreen.tsx`**

Add `import { analytics } from "../analytics";`. In `startSuggestion`, after the `cached` guard (`if (cached === undefined || cached.workflow_id !== workflowId) return;`) and before `const requestId = generateRequestId();`:

```ts
    // Phase 30a: the tap, counted separately from the server's confirmed outcome.
    analytics.track("suggestion_requested", { workflow_key: workflowId });
```

- [ ] **Step 12: Run the whole mobile suite, typecheck and lint**

Run: `pnpm test:mobile && pnpm typecheck && pnpm lint:mobile`
Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add apps/mobile/src/auth apps/mobile/src/todoWorkflows
git commit -m "feat(mobile): record auth funnel, identity, and suggestion tap events (phase 30a)"
```

---

### Task 4: Terraform: RudderStack loader, keyless trust, and curated views

**Files:**

- Create: `infra/terraform/sandbox/rudderstack.tf`, `infra/terraform/sandbox/analytics/signup_funnel.sql.tftpl`, `infra/terraform/sandbox/analytics/suggestion_taps.sql.tftpl`
- Modify: `infra/terraform/sandbox/variables.tf` (after `variable "hex"`), `infra/terraform/sandbox/terraform.tfvars.example` (after `# hex = {}`)
- Test: `infra/terraform/sandbox/tests/analytics.tftest.hcl`

**Interfaces:**

- Consumes: `local.analytics_enabled`, `google_bigquery_dataset.analytics`, `google_bigquery_table.events_deduped`, `data.google_project.current`, `var.region`, `var.project_id`.
- Produces: output `rudderstack_settings` (object: `pool_project_number`, `pool_id`, `provider_id`, `service_account`, `bucket`, `dataset`), used by the guide.

- [ ] **Step 1: Write the failing tests** (append to `tests/analytics.tftest.hcl`; add the override next to the `hex_reader` override)

```hcl
override_resource {
  target          = google_service_account.rudderstack_loader
  override_during = plan
  values = {
    email = "example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    name  = "projects/example-phase18-project/serviceAccounts/example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
  }
}
```

```hcl
run "rudderstack_disabled_by_default" {
  command = plan

  variables {
    analytics = { readers = [] }
  }

  assert {
    condition     = length(google_bigquery_dataset.rudderstack_raw) == 0 && length(google_storage_bucket.rudderstack_staging) == 0 && length(google_iam_workload_identity_pool.rudderstack) == 0 && length(google_service_account.rudderstack_loader) == 0
    error_message = "RudderStack must create nothing unless enabled."
  }
}

run "rudderstack_enabled" {
  command = plan

  variables {
    analytics   = { readers = ["user:learner@example.test"] }
    rudderstack = { workspace_id = "2AbCdEfGh123" }
  }

  assert {
    condition     = google_bigquery_dataset.rudderstack_raw[0].dataset_id == "rudderstack_raw" && google_bigquery_dataset.rudderstack_raw[0].location == "us-west1"
    error_message = "The raw client dataset must be rudderstack_raw in the sandbox region."
  }
  assert {
    condition     = google_bigquery_dataset_access.rudderstack_loader[0].dataset_id == "rudderstack_raw" && google_bigquery_dataset_access.rudderstack_loader[0].role == "roles/bigquery.dataEditor" && google_bigquery_dataset_access.rudderstack_loader[0].iam_member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The loader must get dataEditor on rudderstack_raw only."
  }
  assert {
    condition     = google_project_iam_member.rudderstack_job_user[0].role == "roles/bigquery.jobUser" && google_project_iam_member.rudderstack_job_user[0].member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"
    error_message = "The loader needs project jobUser for load jobs, nothing broader."
  }
  assert {
    condition     = google_storage_bucket.rudderstack_staging[0].uniform_bucket_level_access && google_storage_bucket.rudderstack_staging[0].public_access_prevention == "enforced" && google_storage_bucket.rudderstack_staging[0].lifecycle_rule[0].condition[0].age == 7 && google_storage_bucket.rudderstack_staging[0].lifecycle_rule[0].action[0].type == "Delete"
    error_message = "The staging bucket must be uniform, non-public, and delete objects after 7 days."
  }
  assert {
    condition     = toset([for m in google_storage_bucket_iam_member.rudderstack_staging : m.role]) == toset(["roles/storage.objectCreator", "roles/storage.objectViewer"]) && alltrue([for m in google_storage_bucket_iam_member.rudderstack_staging : m.member == "serviceAccount:example-rudderstack-loader@example-phase18-project.iam.gserviceaccount.com"])
    error_message = "The loader gets only object create and view, on the staging bucket only."
  }
  assert {
    condition     = google_iam_workload_identity_pool_provider.rudderstack[0].aws[0].account_id == "422074288268" && google_iam_workload_identity_pool_provider.rudderstack[0].attribute_condition == "attribute.workspace == '2AbCdEfGh123'" && google_iam_workload_identity_pool_provider.rudderstack[0].attribute_mapping["attribute.workspace"] == "assertion.arn.extract('assumed-role/data-plane-service-account/{workspace}')"
    error_message = "The pool must trust only RudderStack's AWS account and this workspace."
  }
  assert {
    condition     = google_service_account_iam_member.rudderstack_wif[0].role == "roles/iam.workloadIdentityUser" && google_service_account_iam_member.rudderstack_wif[0].member == "principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/rudderstack/attribute.workspace/2AbCdEfGh123"
    error_message = "Only this workspace's federated identity may impersonate the loader."
  }
  assert {
    condition     = length(google_bigquery_table.signup_funnel) == 0 && length(google_bigquery_table.suggestion_taps) == 0
    error_message = "Curated client views wait for curated_views = true (tables exist only after the first sync)."
  }
}

run "rudderstack_curated_views" {
  command = plan

  variables {
    analytics   = { readers = ["user:learner@example.test"] }
    rudderstack = { workspace_id = "2AbCdEfGh123", curated_views = true }
  }

  assert {
    condition     = strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "example-phase18-project.rudderstack_raw.identifies") && strcontains(google_bigquery_table.signup_funnel[0].view[0].query, "example-phase18-project.analytics.events_deduped") && strcontains(google_bigquery_table.suggestion_taps[0].view[0].query, "INTERVAL 30 MINUTE")
    error_message = "The views must join client tables to the curated server events."
  }
  assert {
    condition     = alltrue([for q in [google_bigquery_table.signup_funnel[0].view[0].query, google_bigquery_table.suggestion_taps[0].view[0].query] : !strcontains(q, "context_") && strcontains(q, "PARTITION BY id")])
    error_message = "Views must deduplicate by message id and select no context (IP, user agent, URL) columns."
  }
  assert {
    condition     = toset([for a in google_bigquery_dataset_access.rudderstack_authorized_view : a.view[0].table_id]) == toset(["signup_funnel", "suggestion_taps"]) && alltrue([for a in google_bigquery_dataset_access.rudderstack_authorized_view : a.dataset_id == "rudderstack_raw"])
    error_message = "Both views must be authorized on rudderstack_raw."
  }
}

run "rudderstack_requires_analytics" {
  command = plan

  variables {
    analytics   = null
    rudderstack = { workspace_id = "2AbCdEfGh123" }
  }

  expect_failures = [var.rudderstack]
}

run "rudderstack_rejects_unsafe_workspace_id" {
  command = plan

  variables {
    analytics   = { readers = [] }
    rudderstack = { workspace_id = "x' || true || '" }
  }

  expect_failures = [var.rudderstack]
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox test -no-color`
Expected: errors referencing undeclared `var.rudderstack` / `google_bigquery_dataset.rudderstack_raw`.

- [ ] **Step 3: Add the variable** to `variables.tf` after `variable "hex"`

```hcl
variable "rudderstack" {
  description = "Opt-in Phase 30a client events: a raw dataset, staging bucket, and loader identity that RudderStack reaches through workload identity federation (no key). Set curated_views = true after RudderStack's first sync creates its tables. Requires analytics."
  type = object({
    workspace_id  = string
    curated_views = optional(bool, false)
    raw_dataset   = optional(string, "rudderstack_raw")
    bucket_name   = optional(string)
    account_id    = optional(string, "rudderstack-loader")
    pool_id       = optional(string, "rudderstack")
  })
  default = null

  validation {
    condition     = var.rudderstack == null || var.analytics != null
    error_message = "rudderstack requires analytics to be enabled."
  }

  validation {
    # Interpolated into the pool's CEL trust condition, so only plain IDs.
    condition     = var.rudderstack == null ? true : can(regex("^[A-Za-z0-9]+$", var.rudderstack.workspace_id))
    error_message = "rudderstack.workspace_id must be the alphanumeric RudderStack workspace ID."
  }
}
```

Append to `terraform.tfvars.example` after `# hex = {}`:

```hcl
# Phase 30a RudderStack client events (see docs/guides/30a-rudderstack-client-events.md).
# rudderstack = {
#   workspace_id  = "your-rudderstack-workspace-id"
#   curated_views = false # true after the first sync
# }
```

- [ ] **Step 4: Write `rudderstack.tf`**

```hcl
# Phase 30a: RudderStack Cloud loads client events into BigQuery through a
# staging bucket. It authenticates from its AWS account through workload
# identity federation and impersonates one loader account: no key exists.
# Curated views join client events to the Phase 26 server events.

locals {
  rudderstack_enabled = var.rudderstack != null && local.analytics_enabled
  rudderstack_views   = local.rudderstack_enabled && try(var.rudderstack.curated_views, false)
  rudderstack_bucket  = local.rudderstack_enabled ? coalesce(var.rudderstack.bucket_name, "${var.project_id}-rudderstack-staging") : null
}

resource "google_bigquery_dataset" "rudderstack_raw" {
  count = local.rudderstack_enabled ? 1 : 0

  project                    = var.project_id
  dataset_id                 = var.rudderstack.raw_dataset
  location                   = var.region
  description                = "Phase 30a raw client events, written by RudderStack. Owner-only; analysts use the curated views."
  delete_contents_on_destroy = false

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "rudderstack_staging" {
  count = local.rudderstack_enabled ? 1 : 0

  project                     = var.project_id
  name                        = local.rudderstack_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true # staging files only

  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_service_account" "rudderstack_loader" {
  count = local.rudderstack_enabled ? 1 : 0

  project      = var.project_id
  account_id   = var.rudderstack.account_id
  display_name = "RudderStack loader (rudderstack_raw only)"
}

resource "google_bigquery_dataset_access" "rudderstack_loader" {
  count = local.rudderstack_enabled ? 1 : 0

  project    = var.project_id
  dataset_id = google_bigquery_dataset.rudderstack_raw[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  iam_member = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

# Required to run load jobs; grants no data access.
resource "google_project_iam_member" "rudderstack_job_user" {
  count = local.rudderstack_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

resource "google_storage_bucket_iam_member" "rudderstack_staging" {
  for_each = local.rudderstack_enabled ? toset(["roles/storage.objectCreator", "roles/storage.objectViewer"]) : toset([])

  bucket = google_storage_bucket.rudderstack_staging[0].name
  role   = each.value
  member = "serviceAccount:${google_service_account.rudderstack_loader[0].email}"
}

resource "google_iam_workload_identity_pool" "rudderstack" {
  count = local.rudderstack_enabled ? 1 : 0

  project                   = var.project_id
  workload_identity_pool_id = var.rudderstack.pool_id
  display_name              = "RudderStack"
  description               = "Federates RudderStack's warehouse loader for one workspace."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "rudderstack" {
  count = local.rudderstack_enabled ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "rudderstack-aws"
  display_name                       = "RudderStack AWS"

  attribute_mapping = {
    "google.subject"      = "assertion.arn"
    "attribute.workspace" = "assertion.arn.extract('assumed-role/data-plane-service-account/{workspace}')"
  }

  # RudderStack's AWS account is shared by all its customers; the workspace
  # condition is what makes this pool yours.
  attribute_condition = "attribute.workspace == '${var.rudderstack.workspace_id}'"

  aws {
    account_id = "422074288268"
  }
}

resource "google_service_account_iam_member" "rudderstack_wif" {
  count = local.rudderstack_enabled ? 1 : 0

  service_account_id = google_service_account.rudderstack_loader[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id}/attribute.workspace/${var.rudderstack.workspace_id}"
}

resource "google_bigquery_table" "signup_funnel" {
  count = local.rudderstack_views ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "signup_funnel"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/signup_funnel.sql.tftpl", {
      project     = var.project_id
      dataset     = var.analytics.dataset
      raw_dataset = var.rudderstack.raw_dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_table" "suggestion_taps" {
  count = local.rudderstack_views ? 1 : 0

  project             = var.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "suggestion_taps"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/analytics/suggestion_taps.sql.tftpl", {
      project     = var.project_id
      dataset     = var.analytics.dataset
      raw_dataset = var.rudderstack.raw_dataset
    })
  }

  depends_on = [google_bigquery_table.events_deduped]
}

resource "google_bigquery_dataset_access" "rudderstack_authorized_view" {
  for_each = local.rudderstack_views ? toset(["signup_funnel", "suggestion_taps"]) : toset([])

  project    = var.project_id
  dataset_id = google_bigquery_dataset.rudderstack_raw[0].dataset_id

  view {
    project_id = var.project_id
    dataset_id = google_bigquery_dataset.analytics[0].dataset_id
    table_id   = each.value
  }

  depends_on = [google_bigquery_table.signup_funnel, google_bigquery_table.suggestion_taps]
}

output "rudderstack_settings" {
  description = "Values for the RudderStack BigQuery destination (workload identity federation)."
  value = local.rudderstack_enabled ? {
    pool_project_number = data.google_project.current.number
    pool_id             = google_iam_workload_identity_pool.rudderstack[0].workload_identity_pool_id
    provider_id         = google_iam_workload_identity_pool_provider.rudderstack[0].workload_identity_pool_provider_id
    service_account     = google_service_account.rudderstack_loader[0].email
    bucket              = google_storage_bucket.rudderstack_staging[0].name
    dataset             = google_bigquery_dataset.rudderstack_raw[0].dataset_id
  } : null
}
```

- [ ] **Step 5: Write the view templates**

`analytics/signup_funnel.sql.tftpl`:

```sql
-- Signup funnel (Phase 30a definition). Client events are deduplicated by
-- RudderStack message id; weeks are UTC ISO weeks. No context columns.
WITH views AS (
  SELECT anonymous_id, MIN(timestamp) AS first_view_at
  FROM (
    SELECT * FROM `${project}.${raw_dataset}.auth_screen_viewed`
    WHERE TRUE
    QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY received_at) = 1
  )
  GROUP BY anonymous_id
),
submits AS (
  SELECT anonymous_id, timestamp AS submitted_at
  FROM `${project}.${raw_dataset}.signup_submitted`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY received_at) = 1
),
links AS (
  SELECT DISTINCT anonymous_id, user_id AS user_key
  FROM `${project}.${raw_dataset}.identifies`
  WHERE user_id IS NOT NULL
),
server_signups AS (
  SELECT user_key, occurred_at AS signed_up_at
  FROM `${project}.${dataset}.events_deduped`
  WHERE event_name = 'user_signed_up'
),
visitor_submits AS (
  SELECT v.anonymous_id, v.first_view_at, MIN(s.submitted_at) AS submitted_at
  FROM views v
  LEFT JOIN submits s
    ON s.anonymous_id = v.anonymous_id
   AND s.submitted_at >= v.first_view_at
   AND s.submitted_at < TIMESTAMP_ADD(v.first_view_at, INTERVAL 24 HOUR)
  GROUP BY v.anonymous_id, v.first_view_at
),
visitor_outcomes AS (
  SELECT vs.anonymous_id, vs.first_view_at, vs.submitted_at,
         LOGICAL_OR(ss.user_key IS NOT NULL) AS signed_up
  FROM visitor_submits vs
  LEFT JOIN links l ON l.anonymous_id = vs.anonymous_id
  LEFT JOIN server_signups ss
    ON ss.user_key = l.user_key
   AND vs.submitted_at IS NOT NULL
   AND ss.signed_up_at >= vs.submitted_at
   AND ss.signed_up_at < TIMESTAMP_ADD(vs.submitted_at, INTERVAL 24 HOUR)
  GROUP BY vs.anonymous_id, vs.first_view_at, vs.submitted_at
),
funnel AS (
  SELECT DATE_TRUNC(DATE(first_view_at), ISOWEEK) AS week,
         COUNT(*) AS visitors,
         COUNTIF(submitted_at IS NOT NULL) AS submitted_24h,
         COUNTIF(signed_up) AS signed_up_24h
  FROM visitor_outcomes
  GROUP BY week
),
coverage AS (
  SELECT DATE_TRUNC(DATE(ss.signed_up_at), ISOWEEK) AS week,
         COUNT(*) AS server_signups,
         COUNTIF(k.user_key IS NOT NULL) AS server_signups_identified
  FROM server_signups ss
  LEFT JOIN (SELECT DISTINCT user_key FROM links) k ON k.user_key = ss.user_key
  GROUP BY week
)
SELECT COALESCE(f.week, c.week) AS week,
       IFNULL(f.visitors, 0) AS visitors,
       IFNULL(f.submitted_24h, 0) AS submitted_24h,
       IFNULL(f.signed_up_24h, 0) AS signed_up_24h,
       IFNULL(c.server_signups, 0) AS server_signups,
       IFNULL(c.server_signups_identified, 0) AS server_signups_identified,
       ROUND(SAFE_DIVIDE(c.server_signups_identified, c.server_signups), 4) AS client_coverage,
       DATE_ADD(COALESCE(f.week, c.week), INTERVAL 9 DAY) <= CURRENT_DATE('UTC') AS cohort_complete
FROM funnel f
FULL OUTER JOIN coverage c ON f.week = c.week
```

`analytics/suggestion_taps.sql.tftpl`:

```sql
-- Suggestion taps vs confirmed outcomes (Phase 30a definition). A tap's
-- outcome is the first server suggestion_finished for the same workflow
-- within 30 minutes (15-minute reservation TTL plus expiry slack) and before
-- that workflow's next tap. Client events deduplicated by message id.
WITH taps AS (
  SELECT id, workflow_key, timestamp AS tapped_at
  FROM `${project}.${raw_dataset}.suggestion_requested`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY received_at) = 1
),
ordered AS (
  SELECT id, workflow_key, tapped_at,
         LEAD(tapped_at) OVER (PARTITION BY workflow_key ORDER BY tapped_at, id) AS next_tap_at
  FROM taps
),
outcomes AS (
  SELECT workflow_key, outcome, occurred_at
  FROM `${project}.${dataset}.events_deduped`
  WHERE event_name = 'suggestion_finished'
),
tap_outcomes AS (
  SELECT o.id, o.workflow_key, o.tapped_at,
         ARRAY_AGG(r.outcome IGNORE NULLS ORDER BY r.occurred_at LIMIT 1)[SAFE_OFFSET(0)] AS outcome
  FROM ordered o
  LEFT JOIN outcomes r
    ON r.workflow_key = o.workflow_key
   AND r.occurred_at >= o.tapped_at
   AND r.occurred_at < TIMESTAMP_ADD(o.tapped_at, INTERVAL 30 MINUTE)
   AND (o.next_tap_at IS NULL OR r.occurred_at < o.next_tap_at)
  GROUP BY o.id, o.workflow_key, o.tapped_at
)
SELECT DATE_TRUNC(DATE(tapped_at), ISOWEEK) AS week,
       COUNT(*) AS taps,
       COUNT(DISTINCT workflow_key) AS workflows_tapped,
       COUNTIF(outcome = 'ready') AS taps_ready,
       COUNTIF(outcome = 'failed') AS taps_failed,
       COUNTIF(outcome = 'expired') AS taps_expired,
       COUNTIF(outcome IS NULL) AS taps_no_outcome
FROM tap_outcomes
GROUP BY week
```

- [ ] **Step 6: Run to verify they pass**

Run: `PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox fmt -check && PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox validate -no-color && PATH="$PWD/infra/terraform/.local/bin:$PATH" terraform -chdir=infra/terraform/sandbox test -no-color`
Expected: `Success! 60 passed, 0 failed.`

- [ ] **Step 7: Commit**

```bash
git add infra/terraform/sandbox
git commit -m "feat(terraform): add keyless RudderStack loader and curated client views (phase 30a)"
```

---

### Task 5: Synthetic client events and unseed

**Files:**

- Create: `analytics_practice/seed_client_events.py`, `analytics_practice/unseed_client.sql`
- Test: `apps/api/tests/test_client_seed.py`

**Interfaces:**

- Consumes: the 28b generator rules in `analytics_practice/seed_outbox.sql` (reproduced, not imported).
- Produces: `build_events() -> list[dict]`, `server_timeline() -> list[dict]`, `USER_PREFIX`, `ANON_PREFIX`, CLI `--dry-run | --probe | --send`.

- [ ] **Step 1: Write the failing tests** in `apps/api/tests/test_client_seed.py`

```python
"""Phase 30a synthetic client events: deterministic, free of text, aligned with the 28b seed."""

import importlib.util
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

SCRIPTS = Path(__file__).parents[3] / "analytics_practice"
_spec = importlib.util.spec_from_file_location("seed_client_events", SCRIPTS / "seed_client_events.py")
assert _spec is not None and _spec.loader is not None
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)

ALLOWED = {
    "auth_screen_viewed": {"mode"},
    "signup_submitted": set(),
    "suggestion_requested": {"workflow_key"},
}


def test_build_is_deterministic_unique_and_prefixed() -> None:
    events = seed.build_events()
    assert events == seed.build_events()
    assert 2500 < len(events) < 5000
    assert len({e["messageId"] for e in events}) == len(events)
    assert all(e["anonymousId"].startswith(seed.ANON_PREFIX) for e in events)
    assert all(e.get("userId", seed.USER_PREFIX).startswith(seed.USER_PREFIX) for e in events)
    assert all(e["timestamp"] < "2026-09-25" for e in events)


def test_events_carry_no_free_text_or_traits() -> None:
    for event in seed.build_events():
        if event["type"] == "identify":
            assert "traits" not in event and "properties" not in event
            continue
        assert event["type"] == "track"
        assert set(event["properties"]) == ALLOWED[event["event"]]


def test_shape_has_blocked_users_visitors_and_retaps() -> None:
    events = seed.build_events()
    identified = {e["userId"] for e in events if e["type"] == "identify"}
    assert 340 <= len(identified) <= 390  # about 8% of 400 simulate ad blockers
    anonymous = {e["anonymousId"] for e in events}
    linked = {e["anonymousId"] for e in events if e["type"] == "identify"}
    assert 550 <= len(anonymous - linked) <= 600  # visitors who never sign up
    taps = [e for e in events if e.get("event") == "suggestion_requested"]
    server_suggestions = sum(
        sum(1 for at in u["suggestions"] if at < seed.CUTOFF)
        for u in seed.server_timeline()
        if u["user_key"] in identified
    )
    assert len(taps) > server_suggestions  # retaps add taps without outcomes


def test_matches_the_28b_outbox_seed(database_session: Session, database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        connection.connection.cursor().execute((SCRIPTS / "seed_outbox.sql").read_text())
    signups = dict(
        database_session.execute(
            text("SELECT user_key::text, occurred_at FROM analytics_events WHERE event_name = 'user_signed_up'")
        ).all()
    )
    outcomes = database_session.execute(
        text("SELECT workflow_key::text, occurred_at FROM analytics_events WHERE event_name = 'suggestion_finished'")
    ).all()
    events = seed.build_events()
    at = lambda e: datetime.fromisoformat(e["timestamp"])  # noqa: E731

    identifies = [e for e in events if e["type"] == "identify"]
    assert identifies
    for event in identifies:
        assert at(event) - timedelta(seconds=1) == signups[event["userId"]]

    taps = defaultdict(list)
    for event in events:
        if event.get("event") == "suggestion_requested":
            taps[event["properties"]["workflow_key"]].append(at(event))
    tapped_workflows = set(taps)
    matched = 0
    for workflow_key, finished_at in outcomes:
        if workflow_key in tapped_workflows:
            assert any(timedelta(seconds=5) <= finished_at - t <= timedelta(seconds=60) for t in taps[workflow_key])
            matched += 1
    assert matched > 500
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --directory apps/api python -m pytest tests/test_client_seed.py -q`
Expected: FAIL at import (`seed_client_events.py` missing).

- [ ] **Step 3: Implement** `analytics_practice/seed_client_events.py`

```python
"""Phase 30a: deterministic synthetic client events, sent through RudderStack.

Reproduces the Phase 28b outbox seed's users and suggestion times (same md5
rule), then adds the client side: auth screen views, signup submits, an
identify per user, a tap before each suggestion outcome, retaps, ~8% of users
with no client events (ad blockers / opt-outs), and 600 visitors who never
sign up. Invented data only; remove with unseed_client.sql.

  python analytics_practice/seed_client_events.py --dry-run
  RUDDERSTACK_WRITE_KEY=... RUDDERSTACK_DATA_PLANE_URL=https://... \\
    python analytics_practice/seed_client_events.py --probe   # one event
  ... --send                                                  # everything
"""

import argparse
import base64
import hashlib
import json
import math
import os
import urllib.request
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

USER_PREFIX = "00000000-0000-4000-8000-"
ANON_PREFIX = "00000000-0000-4000-9000-"
START = datetime(2026, 7, 27, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
USERS = 400
VISITORS = 600
BATCH = 200


def u(seed: str) -> float:
    """pg_temp.u from seed_outbox.sql: 28 bits of md5, scaled to [0, 1)."""
    return int(hashlib.md5(seed.encode()).hexdigest()[:7], 16) / 268435456.0


def md5_uuid(seed: str) -> str:
    return str(uuid.UUID(hashlib.md5(seed.encode()).hexdigest()))


def _offset(fraction: float, days: int) -> timedelta:
    return timedelta(seconds=math.floor(fraction * days * 86400))


def server_timeline() -> list[dict]:
    """The 28b seed's users, workflows and suggestion outcome times, exactly."""
    users = []
    for n in range(1, USERS + 1):
        signed_up_at = START + _offset(u(f"signup-{n}"), 60)
        suggestions = []
        if u(f"starts-{n}") < 0.7:
            started_at = signed_up_at + _offset(u(f"start-delay-{n}"), 10)
            for k in range(1, math.floor(u(f"sugg-count-{n}") * 9) + 1):
                suggestions.append(started_at + _offset(u(f"sugg-at-{n}-{k}"), 5))
        users.append({
            "n": n,
            "user_key": f"{USER_PREFIX}{n:012d}",
            "workflow_key": md5_uuid(f"hex-seed-workflow-{n}"),
            "signed_up_at": signed_up_at,
            "suggestions": suggestions,
        })
    return users


def _iso(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _message(key: str, at: datetime, anonymous_id: str, *, user_id: str | None = None,
             event: str | None = None, properties: dict | None = None) -> dict:
    message = {
        "type": "track" if event else "identify",
        "messageId": md5_uuid(f"client-seed-{key}"),
        "anonymousId": anonymous_id,
        "timestamp": _iso(at),
        "originalTimestamp": _iso(at),
        "context": {"library": {"name": "phase30a-seed"}},
    }
    if user_id:
        message["userId"] = user_id
    if event:
        message["event"] = event
        message["properties"] = properties or {}
    return message


def build_events() -> list[dict]:
    events: list[dict] = []
    for user in server_timeline():
        n, signed = user["n"], user["signed_up_at"]
        if u(f"client-blocked-{n}") < 0.08 or signed >= CUTOFF:
            continue
        anon, key, workflow = f"{ANON_PREFIX}{n:012d}", user["user_key"], user["workflow_key"]
        viewed = signed - timedelta(seconds=60 + math.floor(u(f"view-lead-{n}") * 1800))
        events += [
            _message(f"view-signin-{n}", viewed, anon, event="auth_screen_viewed", properties={"mode": "signin"}),
            _message(f"view-signup-{n}", viewed + timedelta(seconds=10), anon,
                     event="auth_screen_viewed", properties={"mode": "signup"}),
            _message(f"submit-{n}", signed - timedelta(seconds=2), anon, event="signup_submitted"),
            _message(f"identify-{n}", signed + timedelta(seconds=1), anon, user_id=key),
        ]
        for k, finished_at in enumerate(user["suggestions"], start=1):
            if finished_at >= CUTOFF:
                continue
            tapped = finished_at - timedelta(seconds=5 + math.floor(u(f"tap-lead-{n}-{k}") * 55))
            tap = {"workflow_key": workflow}
            if u(f"retap-{n}-{k}") < 0.10:
                events.append(_message(f"retap-{n}-{k}", tapped - timedelta(seconds=30), anon,
                                       user_id=key, event="suggestion_requested", properties=tap))
            events.append(_message(f"tap-{n}-{k}", tapped, anon, user_id=key,
                                   event="suggestion_requested", properties=tap))
    for v in range(1, VISITORS + 1):
        anon = f"{ANON_PREFIX}{100000 + v:012d}"
        viewed = START + _offset(u(f"visitor-{v}"), 60)
        events.append(_message(f"visitor-view-{v}", viewed, anon, event="auth_screen_viewed",
                               properties={"mode": "signin"}))
        if u(f"visitor-signup-{v}") < 0.5:
            events.append(_message(f"visitor-signup-{v}", viewed + timedelta(seconds=10), anon,
                                   event="auth_screen_viewed", properties={"mode": "signup"}))
            if u(f"visitor-submit-{v}") < 0.3:
                events.append(_message(f"visitor-submit-{v}", viewed + timedelta(seconds=40), anon,
                                       event="signup_submitted"))
    return sorted(events, key=lambda e: (e["timestamp"], e["messageId"]))


def send(events: list[dict], write_key: str, data_plane_url: str) -> None:
    # HTTP API basic auth: the write key is the username, the password is empty.
    token = base64.b64encode(f"{write_key}:".encode()).decode()
    for start in range(0, len(events), BATCH):
        request = urllib.request.Request(
            f"{data_plane_url.rstrip('/')}/v1/batch",
            data=json.dumps({"batch": events[start:start + BATCH]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Basic {token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            pass  # non-2xx raises HTTPError with the status


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Phase 30a synthetic client events.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print a summary; send nothing")
    mode.add_argument("--probe", action="store_true", help="send the first event only")
    mode.add_argument("--send", action="store_true", help="send every event")
    args = parser.parse_args(argv)
    events = build_events()
    if args.dry_run:
        names = Counter(e.get("event", e["type"]) for e in events)
        print(json.dumps({"events": len(events), "by_name": dict(sorted(names.items())),
                          "first": events[0]}, indent=2))
        return
    batch = events[:1] if args.probe else events
    send(batch, os.environ["RUDDERSTACK_WRITE_KEY"], os.environ["RUDDERSTACK_DATA_PLANE_URL"])
    print(f"sent {len(batch)} events")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write `analytics_practice/unseed_client.sql`** (BigQuery; run in the console)

```sql
-- Phase 30a: remove synthetic client events from every table the seed writes.
-- RudderStack can't delete from a warehouse; the warehouse owner does.
DELETE FROM rudderstack_raw.tracks
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.auth_screen_viewed
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.signup_submitted
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.suggestion_requested
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.identifies
WHERE anonymous_id LIKE '00000000-0000-4000-9000-%';
DELETE FROM rudderstack_raw.users
WHERE id LIKE '00000000-0000-4000-8000-%';
```

- [ ] **Step 5: Run to verify they pass, and dry-run**

Run: `pnpm test:api > /tmp/phase30a-api.log 2>&1; tail -3 /tmp/phase30a-api.log && uv run --directory apps/api python ../../analytics_practice/seed_client_events.py --dry-run | head -12`
Expected: full suite passes (751 + 4 = 755), and the dry run prints a total between 2500 and 5000 with counts for `auth_screen_viewed`, `identify`, `signup_submitted`, `suggestion_requested`. If the 28b alignment test fails, fix the generator (never the assertion): the rule must match `seed_outbox.sql` exactly.

- [ ] **Step 6: Commit**

```bash
git add analytics_practice/seed_client_events.py analytics_practice/unseed_client.sql apps/api/tests/test_client_seed.py
git commit -m "feat(analytics): add deterministic synthetic client events aligned with the 28b seed (phase 30a)"
```

---

### Task 6: Walkthrough, definitions, and status

**Files:**

- Create: `docs/guides/30a-rudderstack-client-events.md`
- Modify: `docs/superpowers/specs/2026-09-25-rudderstack-client-events-design.md` (status, related links), `docs/curriculum-roadmap.md` (30a `Spec:` line adds the walkthrough), `README.md` (status sentence after 28b)

- [ ] **Step 1: Write the guide** with these sections, in this order, in the style of `docs/guides/28b-hex-analytics.md` (status line, numbered sections, commands in `sh` blocks, an acceptance record table):

  1. **Why client events.** What server events can't see; the four events and the question each answers; "count confirmed outcomes separately from taps".
  2. **The event plan and definitions.** The event table from the spec; identity (`identify(user.id)`, no traits, `reset()` at sign-out); opt-out consent and GPC, including that a browser refusing storage leaves consent at its default; written definitions of every `signup_funnel` and `suggestion_taps` column (copy the SQL comments' rules: 24-hour windows, the 30-minute/next-tap outcome rule, `client_coverage`, `cohort_complete` = week ended 48 hours ago).
  3. **Keyless vendor access.** A table like 28b's exception table, but showing why no key exists: WIF pool, AWS account `422074288268`, workspace condition, impersonation of `rudderstack-loader`, bucket-only storage roles, `dataEditor` on `rudderstack_raw` only. The question for Accountable: "Which vendors hold keys to our warehouse, and which could use federation instead?"
  4. **Setup** (from the main checkout after merge):
     - Create a free RudderStack Cloud account (US region); copy the workspace ID (Settings → Workspace).
     - Add `rudderstack = { workspace_id = "…" }` to `terraform.tfvars`; plan (expect the dataset, bucket, loader, two bucket grants, dataset grant, job user, pool, provider, WIF binding); apply; `terraform output rudderstack_settings`.
     - In RudderStack: add a **JavaScript** source (copy the write key and data plane URL); add a **BigQuery** destination with authentication **Workload Identity Federation**, project, location `us-west1`, bucket, namespace **`rudderstack_raw`** (can't be changed later), pool project number, pool ID, provider ID, target service account from the output; leave staging-file cleanup off (the loader can't delete objects; the lifecycle rule does); connect source to destination.
     - Cloudflare Pages: add `EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY` and `EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL` to production (as `EXPO_PUBLIC_API_URL` in guide 17), redeploy. Note the write key is public by design.
  5. **See it live.** Open the site, watch RudderStack **Live Events** while viewing the auth screen, switching to signup, signing in, and tapping Suggest todos. DevTools Network: record which hosts the SDK contacts (data plane, `api.rudderstack.com` for source config). Confirm no payload contains a username, title or prompt.
  6. **Synthetic events.** `--dry-run`; `--probe`; trigger **Sync now** on the destination (or wait up to 3 hours); in BigQuery confirm the probe row's `timestamp` is backdated to 2026-07; then `--send`; sync again.
  7. **Curated views.** Set `curated_views = true`, plan (two views, two authorized-view grants), apply. Query both views; compare with `analytics_practice/expected_client.md` (recorded in Task 7). Explain the numbers: coverage ~0.92, the 2026-09-07 dip visible in `taps_ready`, retaps in `taps_no_outcome`.
  8. **Consent, GPC, sign-out.** Turn the switch off: no requests to the data plane. Enable GPC (Brave, or Firefox `privacy.globalprivacycontrol.enabled`): switch disabled with the explanation. Sign out and back in: a new anonymous ID in Live Events.
  9. **Ad blocker experiment.** With uBlock Origin on, sign up a new test account: the server signup appears in `analytics.events_deduped` (after the next export) but no client events; `client_coverage` for this week drops.
  10. **Deletion drill.** RudderStack's suppression API is Growth/Enterprise and doesn't reach warehouses. Delete one real test user's client rows by `user_id` and every linked `anonymous_id` across the tables; run `unseed_client.sql` for the synthetic rows; confirm the views changed; note the 7-day bucket lifecycle and BigQuery time travel (up to 7 days). Record what "fully deleted" required.
  11. **Cost.** Free plan (250K events/month, 3-hour sync); load jobs free; staging storage negligible.
  12. **Acceptance record.** Rows (Pending until done): Terraform applied; RudderStack source/destination with WIF; web deployed with key; live events seen; hosts recorded; probe backdated; seed sent and synced; views applied and match references; opt-out; GPC; sign-out reset; ad-blocker gap; deletion drill.
  13. **Deferred.** iOS (30b), custom-domain proxy, EU opt-in, device-mode destinations, self-hosted data plane, Hex tiles, RudderStack Terraform provider.
  14. **Local verification** (the commands from Global Constraints) and **Sources** (the spec's list).

- [ ] **Step 2: Update status and links**

Spec status line: `**Status:** Design and written spec approved by the learner on 2026-09-25. Implemented; live walkthrough pending.` and add `[Implementation plan](../plans/2026-09-25-rudderstack-client-events.md), [walkthrough](../../guides/30a-rudderstack-client-events.md)` to **Related**.

Roadmap 30a `Spec:` line: `[Phase 30a design](superpowers/specs/2026-09-25-rudderstack-client-events-design.md); [walkthrough](guides/30a-rudderstack-client-events.md).`

README, after the 28b sentence: `[Phase 30a RudderStack client events](docs/guides/30a-rudderstack-client-events.md) is implemented; the learner's live walkthrough is pending.` and change `Phases 24, 25, 27 and 29 remain future work.` to `Phases 24, 25, 27, 29 and 30b remain future work.`

- [ ] **Step 3: Check**

Run: `pnpm lint:markdown && pnpm lint:links`
Expected: 0 issues; links pass.

- [ ] **Step 4: Commit**

```bash
git add docs README.md
git commit -m "docs: add Phase 30a RudderStack walkthrough and status"
```

---

### Task 7: Live seed and reference results (learner-driven)

This task needs the learner: it touches RudderStack, Cloudflare and the sandbox project. **Stop and ask** before each external step; the learner runs them, pastes outputs, and approves recording.

**Files:**

- Create: `analytics_practice/expected_client.md`
- Modify: `docs/guides/30a-rudderstack-client-events.md` (acceptance rows the learner completed)

- [ ] **Step 1:** Ask the learner to run guide sections 4 and 6 (setup, probe, full send, sync) from the merged main checkout, or from this branch if they prefer to test before merge. Confirm the probe row is backdated before `--send`.
- [ ] **Step 2:** Ask the learner to apply `curated_views = true` and paste `SELECT * FROM analytics.signup_funnel ORDER BY week` and `SELECT * FROM analytics.suggestion_taps ORDER BY week` as CSV.
- [ ] **Step 3:** Record `analytics_practice/expected_client.md` in the style of `expected_hex.md`: totals (synthetic events sent, from the dry run; distinct message IDs in `tracks`), both view tables, recording date, the `cohort_complete` caveat, and which rows include real test events. Cross-check: `server_signups` per week equals `signed_up` in `expected_hex.md` for the same weeks; `client_coverage` between 0.85 and 1.0 for full synthetic weeks.
- [ ] **Step 4:** Mark the acceptance rows the learner completed as Passed with the date.
- [ ] **Step 5: Check and commit**

Run: `pnpm lint:markdown && pnpm lint:links`

```bash
git add analytics_practice/expected_client.md docs/guides/30a-rudderstack-client-events.md
git commit -m "docs(analytics): record Phase 30a reference results from the live seed"
```

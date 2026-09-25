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
    if (sdk === null) return { available: false, enabled: true, gpc: false };
    const stored = attempt<boolean | null>(consentStore.get, null);
    const gpcOn = attempt(gpc, false);
    return { available: true, enabled: !gpcOn && (stored ?? true), gpc: gpcOn };
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

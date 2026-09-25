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

type MockSdk = AnalyticsSdk & { [K in keyof AnalyticsSdk]: jest.Mock };

const make = (options?: { store?: ConsentStore; gpc?: boolean; sdk?: MockSdk | null }) => {
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

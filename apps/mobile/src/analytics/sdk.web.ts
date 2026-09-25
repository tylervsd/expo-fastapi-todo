import { RudderAnalytics } from "@rudderstack/analytics-js/bundled";
import type { AnalyticsSdk } from "./analytics";

// Phase 30a: RudderStack JavaScript SDK (web). The bundled build ships its
// plugins, so no plugin scripts load from a CDN at runtime. Cloud mode only
// (no device-mode destinations); the anonymous ID lives in localStorage.
// Loading is lazy: nothing contacts RudderStack until the first call. The
// wrapper only tracks/identifies with consent on and GPC off; reset loads too
// (explicit sign-out, opt-out, or a rejected session must clear an identity a
// previous page session persisted).
export function createSdk(
  config: { writeKey?: string; dataPlaneUrl?: string } = {
    writeKey: process.env.EXPO_PUBLIC_RUDDERSTACK_WRITE_KEY,
    dataPlaneUrl: process.env.EXPO_PUBLIC_RUDDERSTACK_DATA_PLANE_URL,
  },
): AnalyticsSdk | null {
  const { writeKey, dataPlaneUrl } = config;
  if (!writeKey || !dataPlaneUrl) return null;
  // undefined = not loaded yet; null = load failed (every later call is a no-op).
  let rudder: RudderAnalytics | null | undefined;
  const loaded = (): RudderAnalytics | null => {
    if (rudder === undefined) {
      try {
        const instance = new RudderAnalytics();
        instance.load(writeKey, dataPlaneUrl, {
          storage: { type: "localStorage" },
          loadIntegration: false,
        });
        rudder = instance;
      } catch {
        rudder = null;
      }
    }
    return rudder;
  };
  return {
    track: (name, properties) => loaded()?.track(name, properties),
    identify: (userId) => loaded()?.identify(userId),
    reset: () => loaded()?.reset({ entries: { anonymousId: true } }),
  };
}

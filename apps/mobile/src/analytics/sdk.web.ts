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

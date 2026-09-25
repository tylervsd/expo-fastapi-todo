import type { AnalyticsSdk } from "./analytics";

// Native platforms send nothing until Phase 30b adds the React Native SDK.
export function createSdk(): AnalyticsSdk | null {
  return null;
}

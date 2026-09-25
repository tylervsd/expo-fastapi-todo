import { Platform } from "react-native";
import { browserGpc, createAnalytics, createMemoryConsentStore, webConsentStore } from "./analytics";
import { createSdk } from "./sdk";

export const analytics = createAnalytics({
  sdk: createSdk(),
  consentStore: Platform.OS === "web" ? webConsentStore : createMemoryConsentStore(),
  gpc: Platform.OS === "web" ? browserGpc : () => false,
});

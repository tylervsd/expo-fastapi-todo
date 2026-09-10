import { getRandomValues } from "expo-crypto";

if (!globalThis.crypto) {
  Object.defineProperty(globalThis, "crypto", { value: {} });
}
if (!globalThis.crypto.getRandomValues) {
  Object.defineProperty(globalThis.crypto, "getRandomValues", {
    value: getRandomValues,
  });
}

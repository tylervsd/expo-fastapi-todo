import { getRandomValues } from 'expo-crypto';
// AG-UI's UUID dependency expects Web Crypto even in React Native.
if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: {} });
if (!globalThis.crypto.getRandomValues) {
  Object.defineProperty(globalThis.crypto, 'getRandomValues', { value: getRandomValues });
}

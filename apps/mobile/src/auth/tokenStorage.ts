import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

export type TokenStorage = {
  get: () => Promise<string | null>;
  set: (token: string) => Promise<void>;
  clear: () => Promise<void>;
};

const TOKEN_KEY = "todo.session-token";

export const nativeTokenStorage: TokenStorage = {
  get: () => SecureStore.getItemAsync(TOKEN_KEY),
  set: (token) => SecureStore.setItemAsync(TOKEN_KEY, token).then(() => undefined),
  clear: () => SecureStore.deleteItemAsync(TOKEN_KEY),
};

const readWeb = (): string | null => {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
};

export const webTokenStorage: TokenStorage = {
  get: async () => readWeb(),
  set: async (token) => {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      // Private-mode Safari and similar: session simply will not restore.
    }
  },
  clear: async () => {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // Nothing persisted, nothing to remove.
    }
  },
};

export function createMemoryTokenStorage(): TokenStorage {
  let token: string | null = null;
  return {
    get: async () => token,
    set: async (next) => {
      token = next;
    },
    clear: async () => {
      token = null;
    },
  };
}

export const tokenStorage: TokenStorage =
  Platform.OS === "web" ? webTokenStorage : nativeTokenStorage;

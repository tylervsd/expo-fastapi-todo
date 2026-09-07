import { Platform } from "react-native";
import {
  createMemoryTokenStorage,
  nativeTokenStorage,
  tokenStorage,
  webTokenStorage,
} from "./tokenStorage";

jest.mock("expo-secure-store", () => {
  const store = new Map<string, string>();
  return {
    getItemAsync: jest.fn(async (key: string) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      store.delete(key);
    }),
  };
});

if (typeof localStorage === "undefined") {
  const backing = new Map<string, string>();
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (key: string) => backing.get(key) ?? null,
    setItem: (key: string, value: string) => {
      backing.set(key, value);
    },
    removeItem: (key: string) => {
      backing.delete(key);
    },
    clear: () => {
      backing.clear();
    },
  };
}

it("round-trips through the native store", async () => {
  expect(await nativeTokenStorage.get()).toBeNull();
  await nativeTokenStorage.set("tok-1");
  expect(await nativeTokenStorage.get()).toBe("tok-1");
  await nativeTokenStorage.clear();
  expect(await nativeTokenStorage.get()).toBeNull();
});

it("round-trips through web localStorage", async () => {
  localStorage.clear();
  expect(await webTokenStorage.get()).toBeNull();
  await webTokenStorage.set("tok-2");
  expect(await webTokenStorage.get()).toBe("tok-2");
  await webTokenStorage.clear();
  expect(await webTokenStorage.get()).toBeNull();
});

it("memory storage is isolated per instance", async () => {
  const first = createMemoryTokenStorage();
  const second = createMemoryTokenStorage();
  await first.set("a");
  expect(await second.get()).toBeNull();
});

it("exports the platform implementation", () => {
  expect(tokenStorage).toBe(
    Platform.OS === "web" ? webTokenStorage : nativeTokenStorage
  );
});

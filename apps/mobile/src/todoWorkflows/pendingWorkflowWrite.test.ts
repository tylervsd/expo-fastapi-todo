import { Platform } from "react-native";
import {
  createMemoryPendingWriteStorage,
  createPendingWriteStore,
  defaultUuidGenerator,
  nativePendingWriteStore,
  PENDING_WRITE_KEY_PREFIX,
  pendingWriteStore,
  saveAndSendPendingWrite,
  webPendingWriteStore,
  type PendingWorkflowWrite,
  type PendingWriteStore,
  type RawPendingWriteStorage,
} from "./pendingWorkflowWrite";

jest.mock("expo-crypto", () => ({
  randomUUID: jest.fn(() => "123e4567-e89b-42d3-a456-426614174000"),
}));

jest.mock("expo-secure-store", () => {
  const store = new Map<string, string>();
  // Mirror the native module: keys outside [A-Za-z0-9._-] are rejected, so
  // a key regression fails behaviorally instead of passing against a
  // permissive mock.
  const assertKey = (key: string) => {
    if (key.length === 0 || !/^[A-Za-z0-9._-]+$/.test(key)) {
      throw new Error(
        'Invalid key provided to SecureStore. Keys must not be empty and contain only alphanumeric characters, ".", "-", and "_".'
      );
    }
  };
  return {
    getItemAsync: jest.fn(async (key: string) => {
      assertKey(key);
      return store.get(key) ?? null;
    }),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      assertKey(key);
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      assertKey(key);
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

const OWNER_A = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const OWNER_B = "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72";
const REQUEST_A = "30bfb542-17f1-48a0-9fd8-3930379d5974";
const REQUEST_B = "f019129d-1936-4a5d-9de8-3da5aa01ccb1";
const WORKFLOW_A = "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3";

const startRecord = (overrides: Partial<PendingWorkflowWrite & { body: { request_id: string; title: string } }> = {}): PendingWorkflowWrite => ({
  version: 1,
  ownerId: OWNER_A,
  requestId: REQUEST_A,
  operation: "start",
  body: { request_id: REQUEST_A, title: "Plan birthday party" },
  ...overrides,
} as PendingWorkflowWrite);

const advanceRecord = (
  titles: string[] = ["Send invitations", "Order birthday cake"],
): PendingWorkflowWrite => ({
  version: 1,
  ownerId: OWNER_A,
  requestId: REQUEST_B,
  operation: "advance",
  workflowId: WORKFLOW_A,
  body: {
    request_id: REQUEST_B,
    expected_revision: 2,
    step_id: `${WORKFLOW_A}:COLLECT_TASKS`,
    action: { action: "submit_tasks", titles },
  },
});

const setup = () => createPendingWriteStore(createMemoryPendingWriteStorage());

describe("pending workflow write store", () => {
  it("uses storage keys valid for SecureStore on native", async () => {
    // expo-secure-store rejects keys outside [A-Za-z0-9._-]; localStorage
    // accepts anything, so this pins the native contract explicitly.
    expect(`${PENDING_WRITE_KEY_PREFIX}${OWNER_A}`).toMatch(/^[A-Za-z0-9._-]+$/);
  });

  it("round-trips a start record with Unicode exactly", async () => {
    const store = setup();
    const record = startRecord({
      body: { request_id: REQUEST_A, title: "🎂 Plan fête d'anniversaire — 日本語のケーキ" },
    });
    await store.save(record);
    await expect(store.read(OWNER_A)).resolves.toEqual(record);
  });

  it("round-trips a maximum ten-title advance payload without truncation", async () => {
    const store = setup();
    const titles = [
      "🎈 Send invitations",
      "Order the birthday cake with crème brûlée",
      "Decorate the hall — entrée & dessert",
      "Buy 日本語 balloons",
      "Confirm the музыка playlist",
      "Wrap gifts for Zoë",
      "Charge the caméra batteries",
      "Print naïve seating charts",
      "Call Günter about piñatas",
      "Sweep the façade steps",
    ];
    const record = advanceRecord(titles);
    await store.save(record);
    const loaded = await store.read(OWNER_A);
    expect(loaded).toEqual(record);
    if (loaded?.operation === "advance" && loaded.body.action.action === "submit_tasks") {
      expect(loaded.body.action.titles).toHaveLength(10);
      expect(loaded.body.action.titles).toEqual(titles);
    } else {
      throw new Error("expected the saved advance record back");
    }
  });

  it("returns null when nothing is stored", async () => {
    await expect(setup().read(OWNER_A)).resolves.toBeNull();
  });

  it.each([
    ["not json", "plain text, not JSON"],
    ["null", "null"],
    ["array", "[1, 2]"],
    ["wrong version", JSON.stringify({ ...startRecord(), version: 2 })],
    ["missing body", JSON.stringify({ version: 1, ownerId: OWNER_A, requestId: REQUEST_A, operation: "start" })],
    ["extra key", JSON.stringify({ ...startRecord(), surprise: true })],
    ["unknown operation", JSON.stringify({ ...startRecord(), operation: "delete" })],
    ["advance without workflowId", JSON.stringify({ ...advanceRecord(), workflowId: undefined })],
  ])("returns null for invalid stored data (%s)", async (_label, raw) => {
    const backing = new Map<string, string>([
      [`${PENDING_WRITE_KEY_PREFIX}${OWNER_A}`, raw],
    ]);
    const store = createPendingWriteStore({
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async () => undefined,
      removeItem: async () => undefined,
    });
    await expect(store.read(OWNER_A)).resolves.toBeNull();
  });

  it("returns null for a record owned by someone else", async () => {
    const store = setup();
    await store.save(startRecord());
    await expect(store.read(OWNER_B)).resolves.toBeNull();
    // The original owner's record is untouched.
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
  });

  it("returns null when the body request ID differs from the record request ID", async () => {
    const tampered = {
      version: 1,
      ownerId: OWNER_A,
      requestId: REQUEST_A,
      operation: "start",
      body: { request_id: REQUEST_B, title: "Plan birthday party" },
    };
    const backing = new Map<string, string>([
      [`${PENDING_WRITE_KEY_PREFIX}${OWNER_A}`, JSON.stringify(tampered)],
    ]);
    const tamperedStore = createPendingWriteStore({
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async () => undefined,
      removeItem: async () => undefined,
    });
    await expect(tamperedStore.read(OWNER_A)).resolves.toBeNull();
  });

  it.each([
    ["bad owner", { ...startRecord(), ownerId: "not-a-uuid" }],
    ["bad request id", { ...startRecord(), requestId: "xyz" }],
    ["untrimmed title", startRecord({ body: { request_id: REQUEST_A, title: "  Padded  " } })],
    ["over-long title", startRecord({ body: { request_id: REQUEST_A, title: "x".repeat(121) } })],
    ["negative revision", { ...advanceRecord(), body: { request_id: REQUEST_B, expected_revision: -1, step_id: `${WORKFLOW_A}:COLLECT_TASKS`, action: { action: "confirm" as const } } }],
    ["step id for another workflow", { ...advanceRecord(), body: { request_id: REQUEST_B, expected_revision: 2, step_id: `${OWNER_A}:COLLECT_TASKS`, action: { action: "confirm" } } }],
    ["malformed action", { ...advanceRecord(), body: { request_id: REQUEST_B, expected_revision: 2, step_id: `${WORKFLOW_A}:COLLECT_TASKS`, action: { action: "explode" } } }],
  ])("rejects invalid records on save (%s)", async (_label, record) => {
    const raw = createMemoryPendingWriteStorage();
    const setItem = jest.fn(raw.setItem.bind(raw));
    const spiedStore = createPendingWriteStore({ ...raw, setItem });
    await expect(spiedStore.save(record as PendingWorkflowWrite)).rejects.toThrow();
    expect(setItem).not.toHaveBeenCalled();
  });

  it("surfaces storage write errors", async () => {
    const store = createPendingWriteStore({
      getItem: async () => null,
      setItem: async () => {
        throw new Error("disk is full");
      },
      removeItem: async () => undefined,
    });
    await expect(store.save(startRecord())).rejects.toThrow("disk is full");
  });

  it("rejects when the read-back after save does not match", async () => {
    const backing = new Map<string, string>();
    const store = createPendingWriteStore({
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async (key) => {
        backing.set(key, "corrupted-by-platform");
      },
      removeItem: async (key) => {
        backing.delete(key);
      },
    });
    await expect(store.save(startRecord())).rejects.toThrow("could not save a safe retry");
  });

  it("surfaces storage read errors", async () => {
    const store = createPendingWriteStore({
      getItem: async () => {
        throw new Error("keychain locked");
      },
      setItem: async () => undefined,
      removeItem: async () => undefined,
    });
    await expect(store.read(OWNER_A)).rejects.toThrow("keychain locked");
  });

  it("clears only the matching request", async () => {
    const store = setup();
    await store.save(startRecord());
    await store.clear(OWNER_A, "11111111-2222-4333-8444-555555555555");
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
    await store.clear(OWNER_A, REQUEST_A);
    await expect(store.read(OWNER_A)).resolves.toBeNull();
  });

  it("treats clearing an absent record as success", async () => {
    await expect(setup().clear(OWNER_A, REQUEST_A)).resolves.toBeUndefined();
  });

  it("rejects a second save with a different request ID and keeps the original", async () => {
    const store = setup();
    await store.save(startRecord());
    await expect(
      store.save({
        version: 1,
        ownerId: OWNER_A,
        requestId: REQUEST_B,
        operation: "start",
        body: { request_id: REQUEST_B, title: "Second draft" },
      }),
    ).rejects.toThrow(/pending/i);
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
  });

  it("allows re-saving the same request ID", async () => {
    const store = setup();
    await store.save(startRecord());
    await expect(store.save(startRecord())).resolves.toBeUndefined();
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
  });

  it("leaves the record alone when clearing a request ID that was never stored", async () => {
    const store = setup();
    await store.save(startRecord());
    await store.clear(OWNER_A, REQUEST_B);
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
  });

  it.each([["one", 1], ["eleven", 11]])(
    "rejects a submit_tasks payload with %s titles on save",
    async (_label, count) => {
      const store = setup();
      const titles = Array.from({ length: count as number }, (_, index) => `Task ${index + 1}`);
      await expect(store.save(advanceRecord(titles))).rejects.toThrow();
      await expect(store.read(OWNER_A)).resolves.toBeNull();
    },
  );

  it("serializes a clear behind an in-flight save", async () => {
    const backing = new Map<string, string>();
    let releaseSet!: () => void;
    const setGate = new Promise<void>((resolve) => {
      releaseSet = resolve;
    });
    const removeItem = jest.fn(async (key: string) => {
      backing.delete(key);
    });
    const store = createPendingWriteStore({
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async (key, value) => {
        await setGate;
        backing.set(key, value);
      },
      removeItem,
    });
    const saving = store.save(startRecord());
    const clearing = store.clear(OWNER_A, REQUEST_A);
    // The clear must not run while the save is still persisting.
    await Promise.resolve();
    await Promise.resolve();
    expect(removeItem).not.toHaveBeenCalled();
    releaseSet();
    await saving;
    await clearing;
    expect(removeItem).toHaveBeenCalledTimes(1);
    await expect(store.read(OWNER_A)).resolves.toBeNull();
  });

  it("lets a newer save survive a concurrent stale clear", async () => {
    const backing = new Map<string, string>([
      [`${PENDING_WRITE_KEY_PREFIX}${OWNER_A}`, JSON.stringify(startRecord())],
    ]);
    let releaseGet!: (value: string | null) => void;
    const getGate = new Promise<string | null>((resolve) => {
      releaseGet = resolve;
    });
    let getCalls = 0;
    const staleBytes = JSON.stringify(startRecord());
    const store = createPendingWriteStore({
      getItem: async (key) => {
        getCalls += 1;
        if (getCalls === 1) return getGate;
        return backing.get(key) ?? null;
      },
      setItem: async (key, value) => {
        backing.set(key, value);
      },
      removeItem: async (key) => {
        backing.delete(key);
      },
    });
    const clearing = store.clear(OWNER_A, REQUEST_A);
    const newer: PendingWorkflowWrite = {
      version: 1,
      ownerId: OWNER_A,
      requestId: REQUEST_B,
      operation: "start",
      body: { request_id: REQUEST_B, title: "Second draft" },
    };
    const saving = store.save(newer);
    releaseGet(staleBytes);
    await clearing;
    await saving;
    await expect(store.read(OWNER_A)).resolves.toEqual(newer);
  });

  it("surfaces storage delete errors", async () => {
    const backing = new Map<string, string>([
      [`${PENDING_WRITE_KEY_PREFIX}${OWNER_A}`, JSON.stringify(startRecord())],
    ]);
    const store = createPendingWriteStore({
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async () => undefined,
      removeItem: async () => {
        throw new Error("cannot delete");
      },
    });
    await expect(store.clear(OWNER_A, REQUEST_A)).rejects.toThrow("cannot delete");
  });

  it("scopes storage keys by owner so users never collide", async () => {
    const backing = new Map<string, string>();
    const raw: RawPendingWriteStorage = {
      getItem: async (key) => backing.get(key) ?? null,
      setItem: async (key, value) => {
        backing.set(key, value);
      },
      removeItem: async (key) => {
        backing.delete(key);
      },
    };
    const store = createPendingWriteStore(raw);
    await store.save(startRecord());
    await store.save({ ...advanceRecord(), ownerId: OWNER_B, requestId: REQUEST_B });
    const keys = [...backing.keys()];
    expect(keys).toHaveLength(2);
    expect(keys[0]).toContain(OWNER_A);
    expect(keys[1]).toContain(OWNER_B);
    for (const value of backing.values()) {
      expect(value).not.toMatch(/Bearer|token/i);
    }
  });
});

describe("web adapter", () => {
  it("round-trips exact Unicode through localStorage", async () => {
    localStorage.clear();
    const record = startRecord({
      body: { request_id: REQUEST_A, title: "🎂 Tōkyō fête — naïve façade déjà vu" },
    });
    await webPendingWriteStore.save(record);
    await expect(webPendingWriteStore.read(OWNER_A)).resolves.toEqual(record);
    await webPendingWriteStore.clear(OWNER_A, REQUEST_A);
    localStorage.clear();
  });

  it("surfaces localStorage failures instead of sending", async () => {
    const holder = globalThis as Record<string, unknown>;
    const real = holder.localStorage;
    holder.localStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("private mode");
      },
      removeItem: () => undefined,
    };
    try {
      await expect(webPendingWriteStore.save(startRecord())).rejects.toThrow("private mode");
    } finally {
      holder.localStorage = real;
    }
  });
});

describe("native adapter", () => {
  it("round-trips through SecureStore", async () => {
    const SecureStore = jest.requireMock("expo-secure-store") as {
      getItemAsync: jest.Mock;
      setItemAsync: jest.Mock;
      deleteItemAsync: jest.Mock;
    };
    SecureStore.getItemAsync.mockClear();
    SecureStore.setItemAsync.mockClear();
    SecureStore.deleteItemAsync.mockClear();
    const record = advanceRecord();
    await nativePendingWriteStore.save(record);
    await expect(nativePendingWriteStore.read(OWNER_A)).resolves.toEqual(record);
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
      expect.stringContaining(OWNER_A),
      expect.any(String),
    );
    await nativePendingWriteStore.clear(OWNER_A, REQUEST_B);
    await expect(nativePendingWriteStore.read(OWNER_A)).resolves.toBeNull();
  });

  it("surfaces SecureStore failures", async () => {
    const SecureStore = jest.requireMock("expo-secure-store") as { setItemAsync: jest.Mock };
    SecureStore.setItemAsync.mockRejectedValueOnce(new Error("secure enclave unavailable"));
    await expect(nativePendingWriteStore.save(startRecord())).rejects.toThrow(
      "secure enclave unavailable",
    );
  });
});

describe("request ID generation", () => {
  it("delegates to expo-crypto randomUUID", () => {
    const Crypto = jest.requireMock("expo-crypto") as { randomUUID: jest.Mock };
    expect(defaultUuidGenerator()).toBe("123e4567-e89b-42d3-a456-426614174000");
    expect(Crypto.randomUUID).toHaveBeenCalled();
  });
});

describe("saveAndSendPendingWrite", () => {
  const isCurrent = () => true;

  it("never calls send when persistence fails", async () => {
    const failing: PendingWriteStore = {
      read: async () => null,
      save: async () => {
        throw new Error("This device could not save a safe retry.");
      },
      clear: async () => undefined,
    };
    const send = jest.fn(async (_record: PendingWorkflowWrite) => undefined);
    await expect(
      saveAndSendPendingWrite({
        record: startRecord(),
        store: failing,
        sessionEpoch: 1,
        isSessionCurrent: isCurrent,
        send,
      }),
    ).rejects.toThrow("This device could not save a safe retry.");
    expect(send).not.toHaveBeenCalled();
  });

  it("sends the exact stored body when the session is still current", async () => {
    const store = setup();
    const record = advanceRecord();
    const send = jest.fn(async (_saved: PendingWorkflowWrite) => undefined);
    await expect(
      saveAndSendPendingWrite({
        record,
        store,
        sessionEpoch: 7,
        isSessionCurrent: (epoch) => epoch === 7,
        send,
      }),
    ).resolves.toBe("sent");
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(record);
  });

  it("skips send when the session changed during persistence", async () => {
    const store = setup();
    const send = jest.fn(async (_saved: PendingWorkflowWrite) => undefined);
    await expect(
      saveAndSendPendingWrite({
        record: startRecord(),
        store,
        sessionEpoch: 7,
        isSessionCurrent: () => false,
        send,
      }),
    ).resolves.toBe("stale-session");
    expect(send).not.toHaveBeenCalled();
    // The persisted record remains recoverable for an explicit retry.
    await expect(store.read(OWNER_A)).resolves.toEqual(startRecord());
  });
});

describe("platform store", () => {
  it("exports the platform implementation", () => {
    expect(pendingWriteStore).toBe(
      Platform.OS === "web" ? webPendingWriteStore : nativePendingWriteStore,
    );
  });

  it("creates isolated memory stores", async () => {
    const first = createPendingWriteStore(createMemoryPendingWriteStorage());
    const second = createPendingWriteStore(createMemoryPendingWriteStorage());
    await first.save(startRecord());
    await expect(second.read(OWNER_A)).resolves.toBeNull();
  });
});

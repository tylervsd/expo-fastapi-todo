import { Platform } from "react-native";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import {
  MAX_WORKFLOW_REVISION,
  normalizeTodoTitle,
  type TodoWorkflowAction,
  type WorkflowActionRequest,
} from "../todos/todoApi";

export type PendingWorkflowWrite =
  | {
      version: 1;
      ownerId: string;
      requestId: string;
      operation: "start";
      body: { request_id: string; title: string };
    }
  | {
      version: 1;
      ownerId: string;
      requestId: string;
      operation: "advance";
      workflowId: string;
      body: WorkflowActionRequest;
    };

export class PendingWriteStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PendingWriteStoreError";
  }
}

export type RawPendingWriteStorage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  removeItem: (key: string) => Promise<void>;
};

export type PendingWriteStore = {
  read: (ownerId: string) => Promise<PendingWorkflowWrite | null>;
  save: (record: PendingWorkflowWrite) => Promise<void>;
  clear: (ownerId: string, requestId: string) => Promise<void>;
};

export type UuidGenerator = () => string;

/** Request IDs come from the platform CSPRNG; no custom UUID generator. */
export const defaultUuidGenerator: UuidGenerator = () => Crypto.randomUUID();

export const PENDING_WRITE_KEY_PREFIX = "todo.pending-workflow-write:";

const pendingWriteKey = (ownerId: string): string =>
  `${PENDING_WRITE_KEY_PREFIX}${ownerId}`;

const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const isUuid = (value: unknown): value is string =>
  typeof value === "string" && uuidPattern.test(value);

const exactObject = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  typeof value === "object" &&
  value !== null &&
  !Array.isArray(value) &&
  Reflect.ownKeys(value).length === keys.length &&
  keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));

const isCanonicalTitle = (value: unknown): value is string =>
  typeof value === "string" && normalizeTodoTitle(value) === value;

const isValidAction = (value: unknown): value is TodoWorkflowAction => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  switch (record.action) {
    case "answer_multiple_steps":
      return (
        exactObject(record, ["action", "answer"]) && typeof record.answer === "boolean"
      );
    case "submit_tasks":
      return (
        exactObject(record, ["action", "titles"]) &&
        Array.isArray(record.titles) &&
        record.titles.length >= 1 &&
        record.titles.every(isCanonicalTitle)
      );
    case "confirm":
    case "cancel":
      return exactObject(record, ["action"]);
    default:
      return false;
  }
};

const isValidStartBody = (
  body: unknown,
  requestId: string,
): body is { request_id: string; title: string } =>
  exactObject(body, ["request_id", "title"]) &&
  body.request_id === requestId &&
  isUuid(body.request_id) &&
  isCanonicalTitle(body.title);

const isValidAdvanceBody = (
  body: unknown,
  requestId: string,
  workflowId: string,
): body is WorkflowActionRequest => {
  if (!exactObject(body, ["request_id", "expected_revision", "step_id", "action"])) {
    return false;
  }
  if (body.request_id !== requestId || !isUuid(body.request_id)) return false;
  if (
    !Number.isInteger(body.expected_revision) ||
    (body.expected_revision as number) < 0 ||
    (body.expected_revision as number) > MAX_WORKFLOW_REVISION
  ) {
    return false;
  }
  if (
    typeof body.step_id !== "string" ||
    !body.step_id.startsWith(`${workflowId}:`) ||
    body.step_id.length <= workflowId.length + 1
  ) {
    return false;
  }
  return isValidAction(body.action);
};

const isPendingWorkflowWrite = (value: unknown): value is PendingWorkflowWrite => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (record.version !== 1) return false;
  if (!isUuid(record.ownerId) || !isUuid(record.requestId)) return false;
  if (record.operation === "start") {
    return (
      exactObject(record, ["version", "ownerId", "requestId", "operation", "body"]) &&
      isValidStartBody(record.body, record.requestId)
    );
  }
  if (record.operation === "advance") {
    return (
      exactObject(record, [
        "version",
        "ownerId",
        "requestId",
        "operation",
        "workflowId",
        "body",
      ]) &&
      isUuid(record.workflowId) &&
      isValidAdvanceBody(record.body, record.requestId, record.workflowId)
    );
  }
  return false;
};

const assertValidRecord = (record: PendingWorkflowWrite): void => {
  if (!isPendingWorkflowWrite(record)) {
    throw new PendingWriteStoreError("Refusing to store an invalid pending workflow write.");
  }
};

export function createPendingWriteStore(raw: RawPendingWriteStorage): PendingWriteStore {
  return {
    read: async (ownerId: string) => {
      const stored = await raw.getItem(pendingWriteKey(ownerId));
      if (stored === null) return null;
      let parsed: unknown;
      try {
        parsed = JSON.parse(stored);
      } catch {
        return null;
      }
      if (!isPendingWorkflowWrite(parsed) || parsed.ownerId !== ownerId) return null;
      return parsed;
    },
    save: async (record: PendingWorkflowWrite) => {
      assertValidRecord(record);
      const key = pendingWriteKey(record.ownerId);
      const serialized = JSON.stringify(record);
      await raw.setItem(key, serialized);
      const readBack = await raw.getItem(key);
      if (readBack !== serialized) {
        try {
          await raw.removeItem(key);
        } catch {
          // The mismatch itself is the surfaced failure; cleanup is best effort.
        }
        throw new PendingWriteStoreError(
          "This device could not save a safe retry. The plan was not sent. Try again.",
        );
      }
    },
    clear: async (ownerId: string, requestId: string) => {
      const key = pendingWriteKey(ownerId);
      const stored = await raw.getItem(key);
      if (stored === null) return;
      let parsed: unknown;
      try {
        parsed = JSON.parse(stored);
      } catch {
        return;
      }
      if (!isPendingWorkflowWrite(parsed) || parsed.ownerId !== ownerId) return;
      if (parsed.requestId !== requestId) return;
      await raw.removeItem(key);
    },
  };
}

export function createMemoryPendingWriteStorage(): RawPendingWriteStorage {
  const backing = new Map<string, string>();
  return {
    getItem: async (key) => backing.get(key) ?? null,
    setItem: async (key, value) => {
      backing.set(key, value);
    },
    removeItem: async (key) => {
      backing.delete(key);
    },
  };
}

const webRawStorage: RawPendingWriteStorage = {
  getItem: async (key) => localStorage.getItem(key),
  setItem: async (key, value) => {
    localStorage.setItem(key, value);
  },
  removeItem: async (key) => {
    localStorage.removeItem(key);
  },
};

const nativeRawStorage: RawPendingWriteStorage = {
  getItem: (key) => SecureStore.getItemAsync(key),
  setItem: async (key, value) => {
    await SecureStore.setItemAsync(key, value);
  },
  removeItem: (key) => SecureStore.deleteItemAsync(key).then(() => undefined),
};

export const webPendingWriteStore: PendingWriteStore =
  createPendingWriteStore(webRawStorage);

export const nativePendingWriteStore: PendingWriteStore =
  createPendingWriteStore(nativeRawStorage);

export const pendingWriteStore: PendingWriteStore =
  Platform.OS === "web" ? webPendingWriteStore : nativePendingWriteStore;

/**
 * Durable before-send sequence shared by start and advance writes.
 * The record is persisted and read back before anything is sent; a failed
 * save rejects and the sender is never invoked. When the authentication
 * session changed while persisting, nothing is sent and the caller keeps
 * the persisted record for an explicit retry. `send` is provided by the
 * workflow screen (Task 5), which dispatches solely by record.operation
 * and transmits the stored body unchanged.
 */
export async function saveAndSendPendingWrite(args: {
  record: PendingWorkflowWrite;
  store: PendingWriteStore;
  sessionEpoch: number;
  isSessionCurrent: (epoch: number) => boolean;
  send: (record: PendingWorkflowWrite) => Promise<unknown>;
}): Promise<"sent" | "stale-session"> {
  await args.store.save(args.record);
  if (!args.isSessionCurrent(args.sessionEpoch)) return "stale-session";
  await args.send(args.record);
  return "sent";
}

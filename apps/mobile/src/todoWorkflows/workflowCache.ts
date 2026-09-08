import type { TodoWorkflow } from "../todos/todoApi";

/**
 * Internal marker for a query completion that arrived after the
 * authentication session moved on. Callers treat it as "no data yet"
 * rather than surfacing an error: the session transition owns the UI.
 */
export class StaleWorkflowSessionError extends Error {
  constructor() {
    super("The authentication session changed while loading.");
    this.name = "StaleWorkflowSessionError";
  }
}

/**
 * The one shared workflow-cache reconciliation rule (Phase 9): a stored
 * snapshot is replaced only by a snapshot for the same workflow whose
 * revision is at least the cached revision. A replayed historical outcome
 * with a lower revision is recovery evidence only and never overwrites
 * newer cached data. Callers validate identity and runtime shape before
 * calling; a mismatched identity still fails closed to the cached value.
 */
export function keepLatestWorkflow(
  oldData: TodoWorkflow | undefined,
  incoming: TodoWorkflow
): TodoWorkflow {
  if (oldData === undefined) return incoming;
  if (oldData.workflow_id !== incoming.workflow_id) return oldData;
  return incoming.revision >= oldData.revision ? incoming : oldData;
}

export type WorkflowListSnapshot = { items: TodoWorkflow[] };

/** Minimal runtime shape shared by cached and incoming snapshots. */
function asSnapshot(value: unknown): TodoWorkflow | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.workflow_id !== "string") return null;
  if (typeof record.revision !== "number" || !Number.isInteger(record.revision)) {
    return null;
  }
  return value as TodoWorkflow;
}

/**
 * `structuralSharing` adapter for one workflow query. TanStack types the
 * callback inputs as `unknown`, so validate identity/runtime shape here
 * before delegating to {@link keepLatestWorkflow}. An invalid incoming
 * snapshot fails closed to the cache; nothing cached yet accepts it.
 */
export function shareWorkflowSnapshot(oldData: unknown, incoming: unknown): unknown {
  const cached = asSnapshot(oldData);
  const next = asSnapshot(incoming);
  if (next === null) return cached ?? incoming;
  if (cached === null) return incoming;
  return keepLatestWorkflow(cached, next);
}

function asSnapshotList(value: unknown): WorkflowListSnapshot | null {
  if (typeof value !== "object" || value === null) return null;
  const items = (value as { items?: unknown }).items;
  if (!Array.isArray(items)) return null;
  return value as WorkflowListSnapshot;
}

/**
 * `structuralSharing` adapter for owner-scoped discovery. Validates the
 * list envelope before delegating to {@link keepLatestWorkflowList}; an
 * invalid incoming list fails closed to the cache.
 */
export function shareWorkflowListSnapshot(oldData: unknown, incoming: unknown): unknown {
  const cached = asSnapshotList(oldData);
  const next = asSnapshotList(incoming);
  if (next === null) return cached ?? incoming;
  if (cached === null) return incoming;
  return keepLatestWorkflowList(cached, next);
}

/**
 * List-level structural sharing for owner-scoped discovery: each incoming
 * item is reconciled against the cached entry for the same workflow with
 * {@link keepLatestWorkflow}. The incoming list is authoritative for
 * membership, so plans that left the active set are dropped. Returns the
 * cached list object when every reconciled item is reference-identical.
 */
export function keepLatestWorkflowList(
  oldData: WorkflowListSnapshot | undefined,
  incoming: WorkflowListSnapshot
): WorkflowListSnapshot {
  if (oldData === undefined) return incoming;
  const merged = incoming.items.map((item) => {
    const cached = oldData.items.find(
      (entry) => entry.workflow_id === item.workflow_id
    );
    return cached === undefined ? item : keepLatestWorkflow(cached, item);
  });
  if (
    merged.length === oldData.items.length &&
    merged.every((item, index) => item === oldData.items[index])
  ) {
    return oldData;
  }
  return { items: merged };
}

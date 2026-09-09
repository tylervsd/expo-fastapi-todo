import { QueryClient } from "@tanstack/react-query";
import {
  keepLatestWorkflow,
  keepLatestWorkflowList,
  shareWorkflowListSnapshot,
  shareWorkflowSnapshot,
} from "./workflowCache";
import type { TodoWorkflow } from "../todos/todoApi";

const WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const OTHER_ID = "7dd44c95-27b9-5e8f-bf05-0d61cc568e83";

const base: TodoWorkflow = {
  workflow_id: WORKFLOW_ID,
  revision: 3,
  definition_version: 1,
  view_contract_version: 1,
  state: "REVIEW",
  title: "Plan birthday party",
  context: {
    involves_multiple_steps: true,
    proposed_todo_titles: ["Send invitations", "Buy decorations"],
  },
  result: null,
  view: {
    type: "review",
    step_id: `${WORKFLOW_ID}:REVIEW`,
    title: "Review your plan",
    proposed_titles: ["Send invitations", "Buy decorations"],
  },
};

const atRevision = (revision: number): TodoWorkflow => ({ ...base, revision });

afterEach(() => {
  jest.clearAllMocks();
});

it("keeps the newer snapshot whichever side it arrives on", () => {
  const newer = atRevision(4);
  const older = atRevision(3);
  expect(keepLatestWorkflow(newer, older)).toBe(newer);
  expect(keepLatestWorkflow(older, newer)).toBe(newer);
});

it("keeps the incoming snapshot when nothing is cached", () => {
  const incoming = atRevision(2);
  expect(keepLatestWorkflow(undefined, incoming)).toBe(incoming);
});

it("keeps an equal revision from the incoming side", () => {
  const cached = atRevision(2);
  const incoming = atRevision(2);
  expect(keepLatestWorkflow(cached, incoming)).toBe(incoming);
});

it("never replaces a cached snapshot with a different workflow identity", () => {
  const cached = atRevision(5);
  const stranger: TodoWorkflow = { ...atRevision(9), workflow_id: OTHER_ID };
  expect(keepLatestWorkflow(cached, stranger)).toBe(cached);
});

it("merges discovery lists per workflow without lowering revisions", () => {
  const cached = { items: [atRevision(4)] };
  const incoming = { items: [atRevision(3)] };
  const merged = keepLatestWorkflowList(cached, incoming);
  expect(merged.items).toHaveLength(1);
  expect(merged.items[0]).toBe(cached.items[0]);
});

it("returns the cached list when item references are unchanged", () => {
  const item = atRevision(2);
  const cached = { items: [item] };
  expect(keepLatestWorkflowList(cached, { items: [item] })).toBe(cached);
});

it("adds newly discovered workflows and drops plans that left the active set", () => {
  const fresh: TodoWorkflow = { ...atRevision(0), workflow_id: OTHER_ID };
  const cachedItem = atRevision(4);
  const cached = { items: [cachedItem] };
  // An equal revision refreshes from the incoming side; a lower revision
  // never overwrites the cached entry.
  const refreshed = keepLatestWorkflowList(cached, { items: [atRevision(4)] });
  expect(refreshed.items[0].revision).toBe(4);
  const merged = keepLatestWorkflowList(cached, { items: [atRevision(3), fresh] });
  expect(merged.items).toHaveLength(2);
  expect(merged.items[0]).toBe(cachedItem);
  expect(merged.items[1]).toBe(fresh);

  const narrowed = keepLatestWorkflowList(merged, { items: [fresh] });
  expect(narrowed.items).toEqual([fresh]);
});

it("proves TanStack Query cannot replace revision 4 with a deferred revision 3", async () => {
  const client = new QueryClient();
  try {
    const key = ["todo-workflow", "user-1", WORKFLOW_ID] as const;
    const newer = atRevision(4);
    const older = atRevision(3);
    client.setQueryData(key, newer);

    let release!: (value: TodoWorkflow) => void;
    const deferredGet = new Promise<TodoWorkflow>((resolve) => {
      release = resolve;
    });
    const pending = client.fetchQuery({
      queryKey: key,
      queryFn: () => deferredGet,
      structuralSharing: (oldData, incoming) =>
        keepLatestWorkflow(
          oldData as TodoWorkflow | undefined,
          incoming as TodoWorkflow
        ),
    });
    release(older);
    // fetchQuery resolves the raw fetched value, but the cache keeps the
    // newer revision: historical replay is recovery evidence only.
    await pending;
    expect(client.getQueryData(key)).toBe(newer);
  } finally {
    client.unmount();
    client.clear();
  }
});

describe("shareWorkflowSnapshot", () => {
  const newer = atRevision(4);
  const older = atRevision(3);
  const other: TodoWorkflow = { ...base, workflow_id: OTHER_ID };

  it("accepts the incoming snapshot when nothing is cached", () => {
    expect(shareWorkflowSnapshot(undefined, newer)).toBe(newer);
  });

  it("keeps the newer revision whichever side it arrives on", () => {
    expect(shareWorkflowSnapshot(newer, older)).toBe(newer);
    expect(shareWorkflowSnapshot(older, newer)).toBe(newer);
  });

  it("fails closed to the cached snapshot on mismatched or invalid input", () => {
    expect(shareWorkflowSnapshot(newer, other)).toBe(newer);
    expect(shareWorkflowSnapshot(newer, null)).toBe(newer);
    expect(shareWorkflowSnapshot(newer, { revision: 9 })).toBe(newer);
  });

  it("accepts the incoming snapshot when the cache holds nothing valid", () => {
    expect(shareWorkflowSnapshot(undefined, older)).toBe(older);
    expect(shareWorkflowSnapshot(null, older)).toBe(older);
  });
});

describe("shareWorkflowListSnapshot", () => {
  const newer = atRevision(4);
  const older = atRevision(3);
  const listOf = (items: TodoWorkflow[]) => ({ items });

  it("reconciles per workflow without lowering cached revisions", () => {
    const cached = listOf([newer]);
    const incoming = listOf([older]);
    const merged = shareWorkflowListSnapshot(cached, incoming) as { items: TodoWorkflow[] };
    expect(merged.items[0]).toBe(newer);
  });

  it("fails closed to the cached list when the incoming list is invalid", () => {
    const cached = listOf([newer]);
    expect(shareWorkflowListSnapshot(cached, null)).toBe(cached);
    expect(shareWorkflowListSnapshot(cached, { items: "nope" })).toBe(cached);
  });
});

import React, { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { fireEvent, render, waitFor } from "@testing-library/react-native";
import {
  ComposerPrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react-native";
import { useAgUiState } from "@assistant-ui/react-ag-ui";
import { AgentSessionProvider, type AgentState } from "./AgentSessionProvider";
import { AgentRuntimeProvider } from "./AgentRuntimeProvider";

const API_URL = "https://api.example.test";
const WORKFLOW_A = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const WORKFLOW_B = "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72";
const RUN_ID = "11111111-1111-4111-8111-111111111111";

const STATE_A: AgentState = {
  contract_version: 1,
  expected_revision: 2,
  step_id: `${WORKFLOW_A}:COLLECT_TASKS`,
  suggestion_request_id: null,
};
const STATE_B: AgentState = {
  contract_version: 1,
  expected_revision: 2,
  step_id: `${WORKFLOW_B}:COLLECT_TASKS`,
  suggestion_request_id: null,
};

// Count real constructions (delegating to the actual HttpAgent) so the suite
// proves one stable agent per workflow/session without changing behavior.
jest.mock("@ag-ui/client", () => {
  const actual = jest.requireActual("@ag-ui/client");
  const constructed: unknown[] = [];
  const instances: unknown[] = [];
  class SpyHttpAgent extends actual.HttpAgent {
    constructor(config: unknown) {
      super(config);
      constructed.push(config);
      instances.push(this);
    }
  }
  return {
    ...actual,
    HttpAgent: SpyHttpAgent,
    __constructed: constructed,
    __instances: instances,
  };
});

const constructedConfigs = (): Array<{
  url: string;
  headers: Record<string, string>;
  threadId: string;
}> =>
  (
    jest.requireMock("@ag-ui/client") as {
      __constructed: Array<{
        url: string;
        headers: Record<string, string>;
        threadId: string;
      }>;
    }
  ).__constructed;

const agentInstances = (): unknown[] =>
  (
    jest.requireMock("@ag-ui/client") as {
      __instances: unknown[];
    }
  ).__instances;

let savedApiUrl: string | undefined;
const realFetch = globalThis.fetch;

beforeEach(() => {
  savedApiUrl = process.env.EXPO_PUBLIC_API_URL;
  process.env.EXPO_PUBLIC_API_URL = API_URL;
  constructedConfigs().length = 0;
  agentInstances().length = 0;
});

afterEach(() => {
  if (savedApiUrl === undefined) {
    delete process.env.EXPO_PUBLIC_API_URL;
  } else {
    process.env.EXPO_PUBLIC_API_URL = savedApiUrl;
  }
  globalThis.fetch = realFetch;
  jest.restoreAllMocks();
});

function ReadyProbe({ mounts }: { mounts: Array<AgentState | undefined> }) {
  // Records every render (not just mount): the gate withholds children until
  // the initial state is installed, so every entry must already be correct.
  mounts.push(useAgUiState<AgentState>());
  return <View testID="agent-ready" />;
}

function Harness({
  workflowId,
  initialState,
  mounts,
  token = "tok",
  sessionEpoch = 1,
}: {
  workflowId: string;
  initialState: AgentState;
  mounts: Array<AgentState | undefined>;
  token?: string;
  sessionEpoch?: number;
}) {
  return (
    <AgentSessionProvider token={token} sessionEpoch={sessionEpoch}>
      <AgentRuntimeProvider workflowId={workflowId} initialState={initialState}>
        <ReadyProbe mounts={mounts} />
      </AgentRuntimeProvider>
    </AgentSessionProvider>
  );
}

const sse = (events: unknown[]): string =>
  events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

const runEvents = (threadId: string) => [
  { type: "RUN_STARTED", threadId, runId: RUN_ID },
  { type: "TEXT_MESSAGE_START", messageId: "m1", role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: "m1", delta: "noted" },
  { type: "TEXT_MESSAGE_END", messageId: "m1" },
  { type: "RUN_FINISHED", threadId, runId: RUN_ID },
];

const sseResponse = (threadId: string): Response =>
  new Response(sse(runEvents(threadId)), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });

// Deterministic fixture transport: echoes the request's threadId back into
// the streamed events and records every body for assertions. No network.
const installFixtureFetch = () => {
  const bodies: Array<{ threadId?: string }> = [];
  const fetchImpl = jest.fn(async (_url: unknown, init?: RequestInit) => {
    const body =
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as { threadId?: string })
        : {};
    bodies.push(body);
    return sseResponse(body.threadId ?? WORKFLOW_A);
  });
  globalThis.fetch = fetchImpl as unknown as typeof fetch;
  return { bodies, fetchImpl };
};

function RunHarness({
  workflowId,
  initialState,
  mounts,
  seenIds,
}: {
  workflowId: string;
  initialState: AgentState;
  mounts: Array<AgentState | undefined>;
  seenIds: Set<string>;
}) {
  return (
    <AgentSessionProvider token="tok" sessionEpoch={1}>
      <AgentRuntimeProvider workflowId={workflowId} initialState={initialState}>
        <ReadyProbe mounts={mounts} />
        <ThreadPrimitive.Root>
          <ThreadPrimitive.MessagesFlatList>
            {({ message }) => {
              seenIds.add(message.id);
              return <View />;
            }}
          </ThreadPrimitive.MessagesFlatList>
          <ComposerPrimitive.Root>
            <ComposerPrimitive.Input placeholder="Type a message" />
            <ComposerPrimitive.Send>
              <Text>Send</Text>
            </ComposerPrimitive.Send>
          </ComposerPrimitive.Root>
        </ThreadPrimitive.Root>
      </AgentRuntimeProvider>
    </AgentSessionProvider>
  );
}

describe("AgentRuntimeProvider", () => {
  it("installs the exact initial state before enabling children", async () => {
    const mounts: Array<AgentState | undefined> = [];
    const view = await render(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );

    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());
    // The gate holds children until the state setter has run, so every
    // observed child state — including the first — is already correct.
    expect(mounts.length).toBeGreaterThan(0);
    for (const state of mounts) {
      expect(state).toEqual(STATE_A);
    }
  });

  it("creates one stable agent for one workflow and session", async () => {
    const mounts: Array<AgentState | undefined> = [];
    const view = await render(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());
    expect(constructedConfigs()).toHaveLength(1);

    await view.rerender(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());
    expect(constructedConfigs()).toHaveLength(1);
    expect(constructedConfigs()[0]).toEqual({
      url: `${API_URL}/agent`,
      headers: { Authorization: "Bearer tok" },
      threadId: WORKFLOW_A,
    });
  });

  it("mints a distinct workflow-scoped agent when the workflow is replaced", async () => {
    const mounts: Array<AgentState | undefined> = [];
    const view = await render(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await view.rerender(
      <Harness workflowId={WORKFLOW_B} initialState={STATE_B} mounts={mounts} />,
    );

    await waitFor(() =>
      expect(
        mounts.some((state) => state?.step_id === STATE_B.step_id),
      ).toBe(true),
    );
    // Every observation is either the old or the new installed state — the
    // workflows never merge.
    for (const state of mounts) {
      expect([STATE_A.step_id, STATE_B.step_id]).toContain(state?.step_id);
    }
    expect(constructedConfigs()).toHaveLength(2);
    expect(constructedConfigs()[1]).toEqual({
      url: `${API_URL}/agent`,
      headers: { Authorization: "Bearer tok" },
      threadId: WORKFLOW_B,
    });
    // No runtime carries the previous workflow's identity forward.
    expect(constructedConfigs()[1].threadId).not.toBe(WORKFLOW_A);
    expect(constructedConfigs()[1].threadId).not.toBe("main");
  });

  it("aborts the previous agent when the workflow is replaced and on unmount", async () => {
    const { HttpAgent: MockAgent } = jest.requireMock("@ag-ui/client") as {
      HttpAgent: { prototype: { abortRun: () => void } };
    };
    const abortSpy = jest.spyOn(MockAgent.prototype, "abortRun");
    const mounts: Array<AgentState | undefined> = [];
    const view = await render(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await view.rerender(
      <Harness workflowId={WORKFLOW_B} initialState={STATE_B} mounts={mounts} />,
    );
    await waitFor(() => expect(constructedConfigs()).toHaveLength(2));
    // Replacing the workflow aborts the previous agent; the new one is live.
    // Both layers abort on teardown (inner cleanup plus session teardown)
    // and AbortController.abort is idempotent, so assert per-agent rather
    // than exact totals.
    const [agentA, agentB] = agentInstances();
    expect(abortSpy.mock.instances).toContain(agentA);
    expect(abortSpy.mock.instances).not.toContain(agentB);

    await view.unmount();
    expect(abortSpy.mock.instances).toContain(agentB);
  });

  it("does not remount or overwrite installed state when revision props change", async () => {
    const mounts: Array<AgentState | undefined> = [];
    const revised: AgentState = {
      ...STATE_A,
      expected_revision: 3,
      suggestion_request_id: "30bfb542-17f1-48a0-9fd8-3930379d5974",
    };
    const view = await render(
      <Harness workflowId={WORKFLOW_A} initialState={STATE_A} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await view.rerender(
      <Harness workflowId={WORKFLOW_A} initialState={revised} mounts={mounts} />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    // Same workflow and session reuses its one runtime: later state updates
    // are explicit Task 5 setter calls, never effect overwrites, and the
    // runtime stays alive for the COLLECT_TASKS → REVIEW acknowledgement.
    expect(constructedConfigs()).toHaveLength(1);
    expect(mounts.length).toBeGreaterThan(0);
    for (const state of mounts) {
      expect(state?.expected_revision).toBe(2);
    }
  });

  it("becomes ready with mount-time state when props change during init", async () => {
    const mounts: Array<AgentState | undefined> = [];
    const revised: AgentState = {
      ...STATE_A,
      expected_revision: 3,
      suggestion_request_id: "30bfb542-17f1-48a0-9fd8-3930379d5974",
    };
    // Child effects run before parent effects, so the gate installs the
    // mount-time snapshot before the parent switches props — readiness must
    // follow the same snapshot instead of deadlocking against the new props.
    function SwitchingHarness() {
      const [state, setState] = useState<AgentState>(STATE_A);
      useEffect(() => {
        setState(revised);
      }, []);
      return (
        <Harness workflowId={WORKFLOW_A} initialState={state} mounts={mounts} />
      );
    }
    const view = await render(<SwitchingHarness />);

    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());
    expect(mounts.length).toBeGreaterThan(0);
    for (const state of mounts) {
      expect(state).toEqual(STATE_A);
    }
    expect(constructedConfigs()).toHaveLength(1);
  });

  it("aborts the in-flight transport when unmounted mid-run", async () => {
    // runtime.thread.cancelRun has no public spy seam (the core class is not
    // exported), so assert its observable outcome: the fetch signal aborts.
    let resolveStream!: (response: Response) => void;
    const signals: AbortSignal[] = [];
    const fetchImpl = jest.fn(async (_url: unknown, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal);
      return new Promise<Response>((resolve) => {
        resolveStream = resolve;
      });
    });
    globalThis.fetch = fetchImpl as unknown as typeof fetch;
    const mounts: Array<AgentState | undefined> = [];
    const seenIds = new Set<string>();
    const view = await render(
      <RunHarness
        workflowId={WORKFLOW_A}
        initialState={STATE_A}
        mounts={mounts}
        seenIds={seenIds}
      />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await fireEvent.changeText(
      view.getByPlaceholderText("Type a message"),
      "Plan birthday party",
    );
    await fireEvent.press(view.getByText("Send"));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));

    await view.unmount();
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(true);
    resolveStream(sseResponse(WORKFLOW_A));
  }, 30000);

  it("posts the workflow UUID as threadId, never main, on a real run", async () => {
    const { bodies, fetchImpl } = installFixtureFetch();
    const mounts: Array<AgentState | undefined> = [];
    const seenIds = new Set<string>();
    const view = await render(
      <RunHarness
        workflowId={WORKFLOW_A}
        initialState={STATE_A}
        mounts={mounts}
        seenIds={seenIds}
      />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await fireEvent.changeText(
      view.getByPlaceholderText("Type a message"),
      "Plan birthday party",
    );
    await fireEvent.press(view.getByText("Send"));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    expect(bodies).toHaveLength(1);
    expect(bodies[0].threadId).toBe(WORKFLOW_A);
    expect(bodies[0].threadId).not.toBe("main");
  }, 30000);

  it("carries no messages or state across a workflow switch", async () => {
    const { fetchImpl } = installFixtureFetch();
    const mounts: Array<AgentState | undefined> = [];
    const seenA = new Set<string>();
    const view = await render(
      <RunHarness
        workflowId={WORKFLOW_A}
        initialState={STATE_A}
        mounts={mounts}
        seenIds={seenA}
      />,
    );
    await waitFor(() => expect(view.getByTestId("agent-ready")).toBeTruthy());

    await fireEvent.changeText(
      view.getByPlaceholderText("Type a message"),
      "Plan birthday party",
    );
    await fireEvent.press(view.getByText("Send"));
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(seenA.size).toBeGreaterThan(0));

    const seenB = new Set<string>();
    const mountsB: Array<AgentState | undefined> = [];
    await view.rerender(
      <RunHarness
        workflowId={WORKFLOW_B}
        initialState={STATE_B}
        mounts={mountsB}
        seenIds={seenB}
      />,
    );

    await waitFor(() =>
      expect(
        mountsB.some((state) => state?.step_id === STATE_B.step_id),
      ).toBe(true),
    );
    // Fresh runtime: no messages bled across, state is exactly the new
    // installed initial, and the new agent carries the new workflow UUID.
    expect(seenB.size).toBe(0);
    for (const state of mountsB) {
      expect(state).toEqual(STATE_B);
    }
    expect(constructedConfigs()).toHaveLength(2);
    expect(constructedConfigs()[1].threadId).toBe(WORKFLOW_B);
  }, 30000);
});

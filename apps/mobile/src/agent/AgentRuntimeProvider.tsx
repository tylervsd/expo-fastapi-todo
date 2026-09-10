import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react-native";
import {
  useAgUiRuntime,
  useAgUiSetState,
  useAgUiState,
} from "@assistant-ui/react-ag-ui";
import type { HttpAgent } from "@ag-ui/client";
import { useAgentSession, type AgentState } from "./AgentSessionProvider";

export type { AgentState };

// Installs the mount-time initial AgentState through the public setter
// exactly once per mount, and withholds children until the gate itself
// observes those same snapshot values back through the public state hook —
// the install notification and the readiness flag flush in separate passes,
// so latching on the effect alone would mount children one render early on
// stale state, while comparing readiness against live props could deadlock
// if props changed between the passes. The snapshot therefore serves both
// installation and readiness, and later revision changes are never installed
// or compared: later state updates are explicit Task 5
// setter-before-addToolResult calls, never effect overwrites.
function AgentStateGate({
  initialState,
  children,
}: {
  initialState: AgentState;
  children?: ReactNode;
}): React.JSX.Element | null {
  const setAgentState = useAgUiSetState<AgentState>();
  const current = useAgUiState<AgentState>();
  const installed = useRef(false);
  const [ready, setReady] = useState(false);
  const snapshot = useRef(initialState);
  const { contract_version, expected_revision, step_id, suggestion_request_id } =
    snapshot.current;

  useEffect(() => {
    if (installed.current) return;
    installed.current = true;
    setAgentState({
      contract_version,
      expected_revision,
      step_id,
      suggestion_request_id,
    });
  }, [
    setAgentState,
    contract_version,
    expected_revision,
    step_id,
    suggestion_request_id,
  ]);

  useEffect(() => {
    if (
      !ready &&
      current?.contract_version === contract_version &&
      current?.expected_revision === expected_revision &&
      current?.step_id === step_id &&
      current?.suggestion_request_id === suggestion_request_id
    ) {
      setReady(true);
    }
  }, [
    ready,
    current,
    contract_version,
    expected_revision,
    step_id,
    suggestion_request_id,
  ]);

  if (!ready) return null;
  return <>{children}</>;
}

function AgentRuntimeInner({
  workflowId,
  initialState,
  createAgent,
  children,
}: {
  workflowId: string;
  initialState: AgentState;
  createAgent: (workflowId: string) => HttpAgent;
  children?: ReactNode;
}): React.JSX.Element {
  // One stable agent per workflow and session era: the same props reuse the
  // instance, while a replaced workflow (or session factory) remounts through
  // the key below into a fresh agent and runtime.
  const agent = useMemo(
    () => createAgent(workflowId),
    [createAgent, workflowId],
  );
  const runtime = useAgUiRuntime({ agent });

  useEffect(
    () => () => {
      // Workflow/session replacement or unmount: cancel the in-flight thread
      // and abort the transport so no run or continuation outlives its scope.
      try {
        runtime.thread.cancelRun();
      } catch {
        // Best effort: the thread may already be settled.
      }
      try {
        agent.abortRun();
      } catch {
        // Best effort: the transport may already be closed.
      }
    },
    [runtime, agent],
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <AgentStateGate initialState={initialState}>{children}</AgentStateGate>
    </AssistantRuntimeProvider>
  );
}

export function AgentRuntimeProvider({
  workflowId,
  initialState,
  children,
}: {
  workflowId: string;
  initialState: AgentState;
  children?: ReactNode;
}): React.JSX.Element {
  const { createAgent } = useAgentSession();

  // Workflow-keyed boundary under the session-keyed boundary above
  // (AuthProvider keys AgentSessionProvider by session epoch): a replaced
  // workflow remounts into a clean runtime with no carried messages, tool
  // results, or state. Deliberately never keyed by revision or step — the
  // runtime must stay alive for the COLLECT_TASKS → REVIEW acknowledgement.
  return (
    <AgentRuntimeInner
      key={workflowId}
      workflowId={workflowId}
      initialState={initialState}
      createAgent={createAgent}
    >
      {children}
    </AgentRuntimeInner>
  );
}

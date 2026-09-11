import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { HttpAgent } from "@ag-ui/client";

// Exact AG-UI state contract shared with the Python /agent route. The token
// never enters this object: it carries only the workflow identity the server
// re-validates against PostgreSQL on every run.
export type AgentState = {
  contract_version: 1;
  expected_revision: number;
  step_id: string;
  suggestion_request_id: string | null;
};

export type AgentSession = {
  createAgent: (workflowId: string) => HttpAgent;
};

// Private app context: only useAgentSession may read it, so the bearer token
// stays inside the factory closure and never reaches workflow props, query
// keys, agent state, pending storage, or logs.
const AgentSessionContext = createContext<AgentSession | null>(null);

export function useAgentSession(): AgentSession {
  const value = useAgentSessionOrNull();
  if (value === null) {
    throw new Error("useAgentSession must be used inside AgentSessionProvider");
  }
  return value;
}

// Nullable read for test probes that mount outside the signed-in branch:
// the hook call itself stays unconditional, so hook order never changes.
export function useAgentSessionOrNull(): AgentSession | null {
  return useContext(AgentSessionContext);
}

function agentUrl(): string {
  // Reuses the existing mobile API URL; no new environment variable.
  const base = process.env.EXPO_PUBLIC_API_URL;
  if (!base) throw new Error("Missing API URL");
  return `${base}/agent`;
}

export function AgentSessionProvider({
  getToken,
  sessionEpoch,
  children,
}: {
  // Lazy token read: called at agent-creation time (event/effect), never
  // during render, so the bearer token stays in the caller's private ref
  // and out of React state, props snapshots, query keys, and logs.
  getToken: () => string | null;
  sessionEpoch: number;
  children?: ReactNode;
}): React.JSX.Element {
  const agentsRef = useRef<Set<HttpAgent> | null>(null);
  if (agentsRef.current === null) {
    agentsRef.current = new Set<HttpAgent>();
  }

  const createAgent = useCallback(
    (workflowId: string) => {
      const token = getToken();
      if (!token) throw new Error("No session token for agent creation");
      const agent = new HttpAgent({
        url: agentUrl(),
        headers: { Authorization: `Bearer ${token}` },
        threadId: workflowId,
      });
      agentsRef.current?.add(agent);
      return agent;
    },
    [getToken],
  );

  // sessionEpoch keys the value identity to the authentication era: even if a
  // future token string repeated, a new era mints a fresh factory. The parent
  // additionally remounts this provider via key={sessionEpoch}.
  const value = useMemo(
    () => ({ createAgent }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [createAgent, sessionEpoch],
  );

  useEffect(
    () => () => {
      // Session teardown (replacement, logout, unmount): stop every agent
      // this era created so no run outlives its session.
      for (const agent of agentsRef.current ?? []) {
        try {
          agent.abortRun();
        } catch {
          // Best effort: the transport may already be closed.
        }
      }
      agentsRef.current?.clear();
    },
    [],
  );

  return (
    <AgentSessionContext.Provider value={value}>
      {children}
    </AgentSessionContext.Provider>
  );
}

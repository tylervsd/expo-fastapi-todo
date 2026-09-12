import { View } from "react-native";
import { render } from "@testing-library/react-native";
import { HttpAgent } from "@ag-ui/client";
import {
  AgentSessionProvider,
  useAgentSession,
} from "./AgentSessionProvider";

const API_URL = "https://api.example.test";
const WORKFLOW_A = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const WORKFLOW_B = "9ab4d5e6-16a8-4d8e-ae94-fc50bb457d72";

let savedApiUrl: string | undefined;

beforeEach(() => {
  savedApiUrl = process.env.EXPO_PUBLIC_API_URL;
  process.env.EXPO_PUBLIC_API_URL = API_URL;
});

afterEach(() => {
  if (savedApiUrl === undefined) {
    delete process.env.EXPO_PUBLIC_API_URL;
  } else {
    process.env.EXPO_PUBLIC_API_URL = savedApiUrl;
  }
  jest.restoreAllMocks();
});

type SessionValue = { createAgent: (workflowId: string) => HttpAgent };

// Stable fixture token getters: shared closures so rerenders reuse the same
// factory identity; the replacement test uses a distinct era getter.
const sessionGetToken = () => "tok";
const sessionGetTokenOld = () => "tok-old";
const sessionGetTokenNew = () => "tok-new";

function Capture({ seen }: { seen: SessionValue[] }) {
  const value = useAgentSession();
  seen.push(value);
  return <View testID="session-capture" />;
}

const renderSession = async (props?: { getToken?: () => string | null; sessionEpoch?: number }) => {
  const seen: SessionValue[] = [];
  const view = await render(
    <AgentSessionProvider
      getToken={props?.getToken ?? sessionGetToken}
      sessionEpoch={props?.sessionEpoch ?? 1}
    >
      <Capture seen={seen} />
    </AgentSessionProvider>,
  );
  return { view, seen };
};

describe("AgentSessionProvider", () => {
  it("builds agents against the existing API URL with the exact bearer header", async () => {
    const { seen } = await renderSession();
    const agent = seen[seen.length - 1].createAgent(WORKFLOW_A);

    expect(agent.url).toBe(`${API_URL}/agent`);
    expect(agent.headers).toEqual({ Authorization: "Bearer tok" });
    expect(agent.threadId).toBe(WORKFLOW_A);
  });

  it("sends no cookie, client URL, or extra agent configuration", async () => {
    const { seen } = await renderSession();
    const agent = seen[seen.length - 1].createAgent(WORKFLOW_A);

    expect(agent.url).not.toBe("/agent");
    expect(agent.url.startsWith(`${API_URL}/`)).toBe(true);
    expect("Cookie" in agent.headers).toBe(false);
    expect("cookie" in agent.headers).toBe(false);
    expect(agent.threadId).not.toBe("main");
  });

  it("keeps a stable factory and agent for one workflow and session", async () => {
    const { view, seen } = await renderSession({ sessionEpoch: 1 });
    const first = seen[seen.length - 1];
    const agentA = first.createAgent(WORKFLOW_A);

    await view.rerender(
      <AgentSessionProvider getToken={sessionGetToken} sessionEpoch={1}>
        <Capture seen={seen} />
      </AgentSessionProvider>,
    );

    const second = seen[seen.length - 1];
    expect(second.createAgent).toBe(first.createAgent);
    // The factory keeps handing out workflow-scoped agents for the session.
    expect(second.createAgent(WORKFLOW_A).threadId).toBe(WORKFLOW_A);
    expect(agentA.threadId).toBe(WORKFLOW_A);
  });

  it("mints distinct agents for distinct workflows", async () => {
    const { seen } = await renderSession({ sessionEpoch: 1 });
    const factory = seen[seen.length - 1];
    const agentA = factory.createAgent(WORKFLOW_A);
    const agentB = factory.createAgent(WORKFLOW_B);

    expect(agentA).not.toBe(agentB);
    expect(agentA.threadId).toBe(WORKFLOW_A);
    expect(agentB.threadId).toBe(WORKFLOW_B);
    expect(agentB.headers).toEqual({ Authorization: "Bearer tok" });
  });

  it("mints agents with the new bearer header after token replacement", async () => {
    const { view, seen } = await renderSession({ getToken: sessionGetTokenOld, sessionEpoch: 1 });
    const before = seen[seen.length - 1];

    await view.rerender(
      <AgentSessionProvider getToken={sessionGetTokenNew} sessionEpoch={2}>
        <Capture seen={seen} />
      </AgentSessionProvider>,
    );

    const after = seen[seen.length - 1];
    expect(after.createAgent).not.toBe(before.createAgent);
    expect(after.createAgent(WORKFLOW_A).headers).toEqual({
      Authorization: "Bearer tok-new",
    });
  });

  it("exposes only the factory and aborts created agents on unmount", async () => {
    const abortSpy = jest.spyOn(HttpAgent.prototype, "abortRun");
    const { view, seen } = await renderSession({ sessionEpoch: 1 });
    const factory = seen[seen.length - 1];

    expect(Object.keys(factory)).toEqual(["createAgent"]);
    expect("token" in factory).toBe(false);
    expect(JSON.stringify(Object.keys(factory))).not.toContain("tok");

    factory.createAgent(WORKFLOW_A);
    factory.createAgent(WORKFLOW_B);
    await view.unmount();

    expect(abortSpy).toHaveBeenCalledTimes(2);
  });
});

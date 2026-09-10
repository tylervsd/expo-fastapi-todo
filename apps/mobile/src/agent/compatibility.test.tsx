import React, { useMemo } from "react";
import { Button, Text, View } from "react-native";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import {
  AssistantRuntimeProvider,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react-native";
import { HttpAgent } from "@ag-ui/client";
import { useAgUiRuntime, useAgUiSetState } from "@assistant-ui/react-ag-ui";

jest.mock("expo-crypto", () => ({
  getRandomValues: jest.fn(<T,>(arr: T): T => arr),
  randomUUID: jest.fn(() => "123e4567-e89b-42d3-a456-426614174000"),
}));

const sse = (events: unknown[]): string =>
  events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");

const THREAD_ID = "a5693d6a-159d-4ae2-b9d3-e4184e6b82b3";
const RUN_ID_1 = "11111111-1111-4111-8111-111111111111";
const RUN_ID_2 = "22222222-2222-4222-8222-222222222222";
const TOOL_CALL_ID = `${RUN_ID_1}:clarify_plan:0`;
const TOOL_RESULT = {
  contract_version: 1,
  suggestion_request_id: "30bfb542-17f1-48a0-9fd8-3930379d5974",
};

const firstRunEvents = [
  { type: "RUN_STARTED", threadId: THREAD_ID, runId: RUN_ID_1 },
  { type: "TOOL_CALL_START", toolCallId: TOOL_CALL_ID, toolCallName: "clarify_plan" },
  { type: "TOOL_CALL_ARGS", toolCallId: TOOL_CALL_ID, delta: '{"field":"date"}' },
  { type: "TOOL_CALL_END", toolCallId: TOOL_CALL_ID },
  { type: "RUN_FINISHED", threadId: THREAD_ID, runId: RUN_ID_1 },
];

const secondRunEvents = [
  { type: "RUN_STARTED", threadId: THREAD_ID, runId: RUN_ID_2 },
  { type: "TEXT_MESSAGE_START", messageId: "m2", role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", messageId: "m2", delta: "received tool result" },
  { type: "TEXT_MESSAGE_END", messageId: "m2" },
  { type: "RUN_FINISHED", threadId: THREAD_ID, runId: RUN_ID_2 },
];

const sseResponse = (events: unknown[]): Response =>
  new Response(sse(events), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });

function FixtureThread() {
  return (
    <ThreadPrimitive.Root>
      <ThreadPrimitive.MessagesFlatList>
        {({ message }) => (
          <View testID={`message-${message.id}`}>
            <MessagePrimitive.Parts>
              {({ part }) => {
                if (part.type === "text") {
                  return <Text testID={`text-${message.id}`}>{part.text}</Text>;
                }
                if (part.type === "tool-call") {
                  const toolPart = part as {
                    toolCallId: string;
                    toolName?: string;
                    name?: string;
                    args?: unknown;
                    result?: unknown;
                  };
                  const name =
                    toolPart.toolName ?? toolPart.name ?? "unknown";
                  return (
                    <View testID={`tool-${toolPart.toolCallId}`}>
                      <Text testID={`tool-name-${toolPart.toolCallId}`}>{name}</Text>
                      <Button
                        title="Send tool result"
                        onPress={() => {
                          const runtime = FixtureThread.capturedRuntime;
                          if (!runtime) throw new Error("runtime not captured");
                          runtime.thread
                            .getMessageById(message.id)
                            .getMessagePartByToolCallId(toolPart.toolCallId)
                            .addToolResult(TOOL_RESULT);
                        }}
                      />
                    </View>
                  );
                }
                return null;
              }}
            </MessagePrimitive.Parts>
          </View>
        )}
      </ThreadPrimitive.MessagesFlatList>
    </ThreadPrimitive.Root>
  );
}

FixtureThread.capturedRuntime = null as unknown as {
  thread: {
    append: (text: string) => void;
    getMessageById: (id: string) => {
      getMessagePartByToolCallId: (toolCallId: string) => {
        addToolResult: (result: unknown) => void;
      };
    };
  };
} | null;

function FixtureApp({ fetchImpl }: { fetchImpl: jest.Mock }) {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: "https://api.example.test/agent",
        headers: { Authorization: "Bearer test-token" },
        threadId: THREAD_ID,
        fetch: fetchImpl,
      }),
    [fetchImpl],
  );
  const runtime = useAgUiRuntime({ agent });
  FixtureThread.capturedRuntime = runtime as unknown as typeof FixtureThread.capturedRuntime;
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <StateProbe />
      <Button title="Start run" onPress={() => runtime.thread.append("Plan birthday party")} />
      <FixtureThread />
    </AssistantRuntimeProvider>
  );
}

function StateProbe() {
  const setState = useAgUiSetState();
  (StateProbe as { setState?: unknown }).setState = setState;
  return null;
}

describe("assistant-ui AG-UI compatibility slice", () => {
  beforeEach(() => {
    FixtureThread.capturedRuntime = null;
    jest.clearAllMocks();
  });

  it("initializes WebCrypto randomness from expo-crypto without Math.random", () => {
    const expoCrypto = jest.requireMock("expo-crypto") as {
      getRandomValues: jest.Mock;
    };
    const mathRandomSpy = jest.spyOn(Math, "random");
    const hadCrypto = typeof globalThis.crypto !== "undefined";
    const originalGetRandomValues = hadCrypto
      ? globalThis.crypto.getRandomValues
      : undefined;
    // Jest (Node) already ships WebCrypto; force the missing-native path
    // so the polyfill assignment is exercised without resetting modules
    // (resetModules would duplicate React and break hooks).
    if (hadCrypto) {
      Object.defineProperty(globalThis.crypto, "getRandomValues", {
        value: undefined,
        writable: true,
        configurable: true,
      });
    } else {
      Object.defineProperty(globalThis, "crypto", {
        value: {},
        writable: true,
        configurable: true,
      });
    }
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const nodeRequire = require as unknown as {
      (id: string): unknown;
      resolve: (id: string) => string;
      cache: Record<string, unknown>;
    };
    const polyfillPath = nodeRequire.resolve("../polyfills");
    delete nodeRequire.cache[polyfillPath];
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    require("../polyfills");
    expect(globalThis.crypto?.getRandomValues).toBe(expoCrypto.getRandomValues);
    expect(mathRandomSpy).not.toHaveBeenCalled();
    mathRandomSpy.mockRestore();
    if (originalGetRandomValues) {
      Object.defineProperty(globalThis.crypto, "getRandomValues", {
        value: originalGetRandomValues,
        writable: true,
        configurable: true,
      });
    }
  });

  it("resolves the pinned public runtime surface", async () => {
    expect(AssistantRuntimeProvider).toBeDefined();
    expect(ThreadPrimitive).toBeDefined();
    expect(MessagePrimitive).toBeDefined();
    expect(MessagePrimitive.Parts).toBeDefined();
    expect(useAgUiRuntime).toBeDefined();
    expect(useAgUiSetState).toBeDefined();
    expect(HttpAgent).toBeDefined();

    const agent = new HttpAgent({
      url: "https://api.example.test/agent",
      headers: { Authorization: "Bearer test-token" },
      threadId: THREAD_ID,
      fetch: jest.fn(async () => sseResponse(secondRunEvents)),
    });
    expect(agent.url).toBe("https://api.example.test/agent");
    expect(agent.headers).toEqual({ Authorization: "Bearer test-token" });
    expect(agent.threadId).toBe(THREAD_ID);
  });

  it("streams recorded tool events and auto-sends a second request on addToolResult", async () => {
    const bodies: unknown[] = [];
    const fetchImpl = jest.fn(async (_url: string, init?: RequestInit) => {
      const raw = init?.body;
      bodies.push(typeof raw === "string" ? JSON.parse(raw) : raw);
      return bodies.length === 1 ? sseResponse(firstRunEvents) : sseResponse(secondRunEvents);
    });

    await render(<FixtureApp fetchImpl={fetchImpl} />);

    await fireEvent.press(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1), { timeout: 10000 });
    await waitFor(
      () => expect(screen.getByTestId(`tool-${TOOL_CALL_ID}`)).toBeTruthy(),
      { timeout: 10000 },
    );
    expect(screen.getByTestId(`tool-name-${TOOL_CALL_ID}`)).toHaveTextContent("clarify_plan");

    await fireEvent.press(screen.getByRole("button", { name: "Send tool result" }));

    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(2), { timeout: 10000 });

    const secondBody = bodies[1] as {
      threadId: string;
      messages: Array<{ role: string; content?: unknown; toolCallId?: string }>;
    };
    expect(secondBody.threadId).toBe(THREAD_ID);
    const toolMessages = secondBody.messages.filter((m) => m.role === "tool");
    expect(toolMessages.length).toBeGreaterThan(0);
    expect(JSON.stringify(toolMessages)).toContain(TOOL_RESULT.suggestion_request_id);
  }, 30000);
});

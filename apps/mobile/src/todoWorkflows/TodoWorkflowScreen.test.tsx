import * as mockReact from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { StyleSheet } from "react-native";
import { createAppQueryClient } from "../../App";
import {
  TodoApiError,
  type TodoWorkflow,
  type WorkflowActionRequest,
  type WorkflowSuggestion,
} from "../todos/todoApi";
import {
  createMemoryPendingWriteStorage,
  createPendingWriteStore,
  PENDING_WRITE_KEY_PREFIX,
  type PendingWriteStore,
  type PendingWorkflowWrite,
} from "./pendingWorkflowWrite";
import {
  TodoWorkflowScreen,
  workflowQueryKey,
} from "./TodoWorkflowScreen";
import type { TodoWorkflowScreenApi } from "../auth/authenticatedApi";

const mockInputFocus = jest.fn();
const mockControlFocus: (unknown[] | undefined)[] = [];
const mockAnnounceForAccessibility = jest.fn();
const mockSetAccessibilityFocus = jest.fn();
const mockFindNodeHandle = jest.fn(() => 123);
let mockPlatformOs: "ios" | "web" = "ios";

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestTextInput = mockReact.forwardRef(
    (
      props: Record<string, unknown>,
      ref: mockReact.Ref<{ focus: () => void; blur: () => void }>
    ) => {
      mockReact.useImperativeHandle(
        ref,
        () => ({ focus: mockInputFocus, blur: jest.fn() }),
        []
      );
      return mockReact.createElement(actual.TextInput, props);
    }
  );
  TestTextInput.displayName = "TestTextInput";
  const TestPressable = mockReact.forwardRef(
    (props: Record<string, unknown>, ref: mockReact.Ref<{ focus: () => void }>) => {
      mockReact.useImperativeHandle(
        ref,
        () => ({
          focus: () => {
            mockControlFocus.push(props.accessibilityLabel as unknown[] | undefined);
          },
        }),
        [props.accessibilityLabel]
      );
      return mockReact.createElement("View", {
        ...props,
        accessible: true,
        accessibilityState:
          props.disabled === undefined
            ? props.accessibilityState
            : {
                ...(props.accessibilityState as Record<string, unknown>),
                disabled: props.disabled,
              },
      });
    }
  );
  TestPressable.displayName = "TestPressable";
  return new Proxy(actual, {
    get(target, property, receiver) {
      if (property === "TextInput") return TestTextInput;
      if (property === "Pressable") return TestPressable;
      if (property === "AccessibilityInfo") {
        return {
          ...actual.AccessibilityInfo,
          announceForAccessibility: mockAnnounceForAccessibility,
          setAccessibilityFocus: mockSetAccessibilityFocus,
        };
      }
      if (property === "findNodeHandle") return mockFindNodeHandle;
      if (property === "Platform") {
        return { get OS() { return mockPlatformOs; } };
      }
      return Reflect.get(target, property, receiver);
    },
  });
});

type MockWorkflowApi = {
  startWorkflow: jest.MockedFunction<TodoWorkflowScreenApi["startWorkflow"]>;
  getWorkflow: jest.MockedFunction<TodoWorkflowScreenApi["getWorkflow"]>;
  advanceWorkflow: jest.MockedFunction<TodoWorkflowScreenApi["advanceWorkflow"]>;
  getSuggestion: jest.MockedFunction<TodoWorkflowScreenApi["getSuggestion"]>;
  suggestWorkflow: jest.MockedFunction<TodoWorkflowScreenApi["suggestWorkflow"]>;
  listWorkflows: jest.MockedFunction<TodoWorkflowScreenApi["listWorkflows"]>;
};

const makeApi = (): MockWorkflowApi => ({
  startWorkflow: jest.fn() as MockWorkflowApi["startWorkflow"],
  getWorkflow: jest.fn() as MockWorkflowApi["getWorkflow"],
  advanceWorkflow: jest.fn() as MockWorkflowApi["advanceWorkflow"],
  getSuggestion: jest.fn(async (_id: string, _options: { signal: AbortSignal }): Promise<WorkflowSuggestion> => {
    throw new TodoApiError("not-found", "That plan has no saved todo suggestions.");
  }) as MockWorkflowApi["getSuggestion"],
  suggestWorkflow: jest.fn() as MockWorkflowApi["suggestWorkflow"],
  listWorkflows: jest.fn() as MockWorkflowApi["listWorkflows"],
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

const WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const USER_ID = "9a4b3c2d-1e2f-4a5b-8c6d-7e8f9a0b1c2d";
const OTHER_USER_ID = "8b3a2c1d-9e8f-4a5b-8c6d-7e8f9a0b1c2e";
const REQUEST_ID = "30bfb542-17f1-48a0-9fd8-3930379d5974";
const REQUEST_ID_2 = "f019129d-1936-4a5d-9de8-3da5aa01ccb1";

const assessWorkflow: TodoWorkflow = {
  workflow_id: WORKFLOW_ID,
  revision: 0,
  definition_version: 1,
  view_contract_version: 1,
  state: "ASSESS_TASK",
  title: "Plan birthday party",
  context: { involves_multiple_steps: null, proposed_todo_titles: [] },
  result: null,
  view: {
    type: "yes_no",
    step_id: `${WORKFLOW_ID}:ASSESS_TASK`,
    title: "Assessment title from the view",
    question: "Does this task involve multiple steps?",
    actions: [
      { id: "yes", label: "Yes" },
      { id: "no", label: "No" },
    ],
  },
};

const offerWorkflow: TodoWorkflow = {
  ...assessWorkflow,
  revision: 1,
  state: "OFFER_BREAKDOWN",
  context: { involves_multiple_steps: true, proposed_todo_titles: [] },
  view: {
    type: "yes_no",
    step_id: `${WORKFLOW_ID}:OFFER_BREAKDOWN`,
    title: "Breakdown offer title from the view",
    question: "Would you like to split it into smaller todos?",
    actions: [
      { id: "yes", label: "Yes" },
      { id: "no", label: "No" },
    ],
  },
};

const readySuggestion: WorkflowSuggestion = {
  contract_version: 1,
  workflow_id: WORKFLOW_ID,
  request_id: REQUEST_ID,
  base_revision: 2,
  step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  status: "ready",
  proposed_titles: ["Choose a date", "Invite guests"],
  error_code: null,
};

const newerSuggestion: WorkflowSuggestion = {
  ...readySuggestion,
  request_id: REQUEST_ID_2,
  proposed_titles: ["Newer saved title", "Another newer title"],
};

const pendingSuggestion: WorkflowSuggestion = {
  ...readySuggestion,
  status: "pending",
  proposed_titles: [],
};

const failedSuggestion: WorkflowSuggestion = {
  ...readySuggestion,
  status: "failed",
  proposed_titles: [],
  error_code: "invalid_output",
};

const supersededSuggestion: WorkflowSuggestion = {
  ...readySuggestion,
  status: "superseded",
  proposed_titles: [],
};

const collectWorkflow: TodoWorkflow = {
  ...assessWorkflow,
  revision: 2,
  state: "COLLECT_TASKS",
  context: { involves_multiple_steps: true, proposed_todo_titles: [] },
  view: {
    type: "task_breakdown",
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
    title: "Break it into smaller todos",
    min_titles: 2,
    max_titles: 10,
  },
};

const reviewWorkflow: TodoWorkflow = {
  ...assessWorkflow,
  revision: 3,
  state: "REVIEW",
  context: {
    involves_multiple_steps: true,
    proposed_todo_titles: ["Send invitations", "Buy decorations", "Book venue"],
  },
  view: {
    type: "review",
    step_id: `${WORKFLOW_ID}:REVIEW`,
    title: "Review your plan",
    proposed_titles: ["Send invitations", "Buy decorations", "Book venue"],
  },
};

const completedWorkflow: TodoWorkflow = {
  ...reviewWorkflow,
  revision: 4,
  state: "COMPLETED",
  result: {
    created_todos: [
      {
        id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72",
        title: "Send invitations",
        completed: false,
      },
      {
        id: "92c4d5e6-16a8-4d8e-ae94-fc50bb457d72",
        title: "Buy decorations",
        completed: false,
      },
      {
        id: "a3d5e6f7-16a8-4d8e-ae94-fc50bb457d72",
        title: "Book venue",
        completed: false,
      },
    ],
  },
  view: {
    type: "completion",
    step_id: `${WORKFLOW_ID}:COMPLETED`,
    title: "Plan complete",
    outcome: "completed",
    created_todos: [
      {
        id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72",
        title: "Send invitations",
        completed: false,
      },
      {
        id: "92c4d5e6-16a8-4d8e-ae94-fc50bb457d72",
        title: "Buy decorations",
        completed: false,
      },
      {
        id: "a3d5e6f7-16a8-4d8e-ae94-fc50bb457d72",
        title: "Book venue",
        completed: false,
      },
    ],
  },
};

const savedSuggestionWrite: PendingWorkflowWrite = {
  version: 1,
  ownerId: USER_ID,
  requestId: REQUEST_ID,
  operation: "suggest",
  workflowId: WORKFLOW_ID,
  body: {
    request_id: REQUEST_ID,
    expected_revision: 2,
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  },
};

const cancelledWorkflow: TodoWorkflow = {
  ...assessWorkflow,
  revision: 1,
  state: "CANCELLED",
  view: {
    type: "completion",
    step_id: `${WORKFLOW_ID}:CANCELLED`,
    title: "Plan cancelled",
    outcome: "cancelled",
    created_todos: [],
  },
};

// TanStack Query schedules minute-scale GC timeouts that can outlive component
// unmounts under jsdom and hold Jest's event loop open after the run. Unref
// them so they still fire while the loop is otherwise alive but never block
// suite exit. Production behavior is unchanged.
timeoutManager.setTimeoutProvider({
  setTimeout: (callback, delay) => {
    const id = setTimeout(callback, delay);
    (id as unknown as { unref?: () => void }).unref?.();
    return id as unknown as number;
  },
  clearTimeout: (timeoutId) => clearTimeout(timeoutId as unknown as ReturnType<typeof setTimeout>),
  setInterval: (callback, delay) => {
    const id = setInterval(callback, delay);
    (id as unknown as { unref?: () => void }).unref?.();
    return id as unknown as number;
  },
  clearInterval: (intervalId) =>
    clearInterval(intervalId as unknown as ReturnType<typeof setInterval>),
});

const liveClients: QueryClient[] = [];

type RenderHostOptions = {
  userId?: string;
  store?: PendingWriteStore;
  generateRequestId?: () => string;
  sessionEpoch?: number;
  isSessionCurrent?: (epoch: number) => boolean;
  initialWorkflowId?: string | null;
};

const renderHost = async (
  api: MockWorkflowApi,
  client = createAppQueryClient(),
  options: RenderHostOptions = {}
) => {
  liveClients.push(client);
  const onExit = jest.fn();
  const store =
    options.store ?? createPendingWriteStore(createMemoryPendingWriteStorage());
  const view = await render(
    <QueryClientProvider client={client}>
      <TodoWorkflowScreen
        userId={options.userId ?? USER_ID}
        api={api}
        onExit={onExit}
        initialWorkflowId={options.initialWorkflowId ?? null}
        pendingStore={store}
        generateRequestId={options.generateRequestId ?? (() => REQUEST_ID)}
        sessionEpoch={options.sessionEpoch ?? 0}
        isSessionCurrent={options.isSessionCurrent ?? (() => true)}
      />
    </QueryClientProvider>
  );
  return { view, onExit, client, store };
};

beforeEach(() => {
  mockInputFocus.mockClear();
  mockControlFocus.length = 0;
  mockAnnounceForAccessibility.mockClear();
  mockSetAccessibilityFocus.mockClear();
  mockFindNodeHandle.mockClear();
});

afterEach(() => {
  while (liveClients.length > 0) {
    const client = liveClients.pop() as QueryClient;
    client.unmount();
    client.clear();
  }
});

it("shows the start form with Back available", async () => {
  const api = makeApi();
  await renderHost(api);

  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect(screen.getByLabelText("Task title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Start planning" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Back to todos" })).toBeTruthy();
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(mockInputFocus).toHaveBeenCalledTimes(1);
});

it("validates the start title locally without a request", async () => {
  const api = makeApi();
  await renderHost(api);

  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a task title.");
  expect(api.startWorkflow).not.toHaveBeenCalled();

  await fireEvent.changeText(screen.getByLabelText("Task title"), "x".repeat(121));
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Check the plan title and try again.");
  expect(api.startWorkflow).not.toHaveBeenCalled();
});

it("sends one canonical start despite rapid press and submit", async () => {
  const starting = deferred<TodoWorkflow>();
  const api = makeApi();
  api.startWorkflow.mockReturnValueOnce(starting.promise);
  await renderHost(api);

  await fireEvent.changeText(screen.getByLabelText("Task title"), "  Plan birthday party  ");
  const input = screen.getByLabelText("Task title");
  const startButton = screen.getByRole("button", { name: "Start planning" });
  const pressStart = startButton.props.onPress as () => void;
  const submitEditing = input.props.onSubmitEditing as () => void;
  await act(async () => {
    pressStart();
    submitEditing();
  });

  expect(api.startWorkflow).toHaveBeenCalledTimes(1);
  expect(api.startWorkflow).toHaveBeenCalledWith({
    request_id: REQUEST_ID,
    title: "Plan birthday party",
  });
  expect(screen.getByText("Submitting…")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Back to todos" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  api.getWorkflow.mockResolvedValueOnce(assessWorkflow);
  await act(async () => {
    starting.resolve(assessWorkflow);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Does this task involve multiple steps?" })).toBeTruthy()
  );
  await waitForQuiescence();
  expect(screen.queryByText("Submitting…")).toBeNull();
  expect(mockControlFocus[mockControlFocus.length - 1]).toBe("Yes");
});

it("shows Submitting… while assessment and collection actions are pending", async () => {
  const answering = deferred<TodoWorkflow>();
  const submitting = deferred<TodoWorkflow>();
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockReturnValueOnce(answering.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(screen.getByText("Submitting…")).toBeTruthy());
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await act(async () => answering.resolve(collectWorkflow));
  await waitFor(() => expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy());
  await waitForQuiescence();

  api.advanceWorkflow.mockReturnValueOnce(submitting.promise);
  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), "One\nTwo");
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() => expect(screen.getByText("Submitting…")).toBeTruthy());
});

it("preserves the start draft on 422", async () => {
  const api = makeApi();
  api.startWorkflow.mockRejectedValueOnce(
    new TodoApiError("validation", "Check the plan details and try again.")
  );
  await renderHost(api);

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Check the plan details and try again.")
  );
  expect(screen.getByLabelText("Task title")).toHaveProp("value", "Plan birthday party");
  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
});

it("offers retry and discard after a lost start and keeps Back", async () => {
  const api = makeApi();
  api.startWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not start planning.")
  );
  const { onExit, store } = await renderHost(api);

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Could not start planning.");
  expect(api.startWorkflow).toHaveBeenCalledTimes(1);
  expect(await store.read(USER_ID)).not.toBeNull();
  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  const back = screen.getByRole("button", { name: "Back to todos" });
  expect(back).toHaveProp("accessibilityState", expect.objectContaining({ disabled: false }));
  await fireEvent.press(back);
  expect(onExit).toHaveBeenCalledTimes(1);
});

const startToAssess = async (api: MockWorkflowApi, title = "Plan birthday party") => {
  api.startWorkflow.mockResolvedValueOnce(assessWorkflow);
  // Recovery reconciliation performs a current GET after every accepted
  // mutation; default it to the fresh snapshot unless a test overrides it.
  api.getWorkflow.mockResolvedValue(assessWorkflow);
  await fireEvent.changeText(screen.getByLabelText("Task title"), title);
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  // Quiescence: the mutation response renders only after the
  // reconciliation GET seeds it, and pending-record cleanup finishes after
  // that. Wait for the retry banner to clear so no reconciling GET is
  // still in flight when the test registers its own staged mocks.
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull()
  );
};

const waitForQuiescence = async () => {
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull()
  );
};

it("uses the shared yes/no template for both questions", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  expect(screen.getByText("Assessment title from the view")).toBeTruthy();
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  expect(screen.getByText("Breakdown offer title from the view")).toBeTruthy();

  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  expect(api.advanceWorkflow).toHaveBeenLastCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 1,
    step_id: `${WORKFLOW_ID}:OFFER_BREAKDOWN`,
    action: { action: "answer_multiple_steps", answer: true },
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
});

it("answers No in offer and renders the server-returned review", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );

  const declined: TodoWorkflow = {
    ...offerWorkflow,
    revision: 2,
    state: "REVIEW",
    context: {
      involves_multiple_steps: true,
      proposed_todo_titles: ["Plan birthday party"],
    },
    view: {
      type: "review",
      step_id: `${WORKFLOW_ID}:REVIEW`,
      title: "Review your plan",
      proposed_titles: ["Plan birthday party"],
    },
  };
  api.advanceWorkflow.mockResolvedValueOnce(declined);
  api.getWorkflow.mockResolvedValueOnce(declined);
  await fireEvent.press(screen.getByRole("button", { name: "No" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenLastCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 1,
    step_id: `${WORKFLOW_ID}:OFFER_BREAKDOWN`,
    action: { action: "answer_multiple_steps", answer: false },
  }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  expect(screen.getByLabelText("Proposed todo 1 of 1: Plan birthday party")).toBeTruthy();
});

it("answers No and renders the returned review", async () => {
  const answering = deferred<TodoWorkflow>();
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockReturnValueOnce(answering.promise);

  await fireEvent.press(screen.getByRole("button", { name: "No" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 0,
    step_id: `${WORKFLOW_ID}:ASSESS_TASK`,
    action: { action: "answer_multiple_steps", answer: false },
  }));

  const noReview: TodoWorkflow = {
    ...assessWorkflow,
    revision: 1,
    state: "REVIEW",
    context: { involves_multiple_steps: false, proposed_todo_titles: ["Plan birthday party"] },
    view: {
      type: "review",
      step_id: `${WORKFLOW_ID}:REVIEW`,
      title: "Review your plan",
      proposed_titles: ["Plan birthday party"],
    },
  };
  api.getWorkflow.mockResolvedValueOnce(noReview);
  await act(async () => {
    answering.resolve(noReview);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  expect(screen.getByLabelText("Proposed todo 1 of 1: Plan birthday party")).toBeTruthy();
});

it("submits exact newline-separated titles", async () => {
  const submitting = deferred<TodoWorkflow>();
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  api.advanceWorkflow.mockReturnValueOnce(submitting.promise);

  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\n\nBuy decorations  \nBook venue\n"
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 2,
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
    action: {
      action: "submit_tasks",
      titles: ["Send invitations", "Buy decorations", "Book venue"],
    },
  }));
  expect(screen.queryByRole("header", { name: "Review your plan" })).toBeNull();

  api.getWorkflow.mockResolvedValueOnce(reviewWorkflow);
  await act(async () => {
    submitting.resolve(reviewWorkflow);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  expect(screen.getByLabelText("Proposed todo 1 of 3: Send invitations")).toBeTruthy();
  expect(screen.getByLabelText("Proposed todo 2 of 3: Buy decorations")).toBeTruthy();
  expect(screen.getByLabelText("Proposed todo 3 of 3: Book venue")).toBeTruthy();
});

it("rejects out-of-bounds breakdowns using the view limits", async () => {
  const customCollect: TodoWorkflow = {
    ...collectWorkflow,
    view: {
      type: "task_breakdown",
      step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
      title: "Break it into smaller todos",
      min_titles: 3,
      max_titles: 4,
    },
  };
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  api.advanceWorkflow.mockResolvedValueOnce(customCollect);
  api.getWorkflow.mockResolvedValueOnce(customCollect);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );

  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), "Only one\nTwo");
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Enter 3 to 4 todo titles, one per line."
  );

  const five = Array.from({ length: 5 }, (_, index) => `Task ${index + 1}`).join("\n");
  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), five);
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Enter 3 to 4 todo titles, one per line."
  );
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(2);
});

it("keeps the breakdown draft on 422 without optimistic review", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("validation", "Check the plan details and try again.")
  );

  const draft = "Send invitations\nBuy decorations";
  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), draft);
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Check the plan details and try again.")
  );
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", draft);
  expect(screen.queryByRole("header", { name: "Review your plan" })).toBeNull();
});

it("confirms the exact backend list and shows the persisted result", async () => {
  const confirming = deferred<TodoWorkflow>();
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  api.advanceWorkflow.mockResolvedValueOnce(reviewWorkflow);
  api.getWorkflow.mockResolvedValueOnce(reviewWorkflow);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\nBuy decorations\nBook venue"
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  api.advanceWorkflow.mockReturnValueOnce(confirming.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 3,
    step_id: `${WORKFLOW_ID}:REVIEW`,
    action: { action: "confirm" },
  }));
  expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy();

  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await act(async () => {
    confirming.resolve(completedWorkflow);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  expect(screen.getByLabelText("Created todo 1 of 3: Send invitations")).toBeTruthy();
  expect(screen.getByLabelText("Created todo 3 of 3: Book venue")).toBeTruthy();
});

const driveToCollect = async (api: MockWorkflowApi) => {
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  // Rendering waits for the reconciliation GET: stage it per advance.
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  await waitForQuiescence();
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  await waitForQuiescence();
};

it("offers suggestions only from the server-supported task breakdown template", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToCollect(api);
  expect(screen.getByRole("button", { name: "Suggest todos" })).toBeTruthy();
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.getSuggestion.mockResolvedValueOnce(readySuggestion);
  api.suggestWorkflow.mockResolvedValueOnce(readySuggestion);

  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  await waitFor(() => expect(api.suggestWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 2,
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  }));
  await waitFor(() =>
    expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp(
      "value",
      "Choose a date\nInvite guests",
    ),
  );
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(2);
});

it("keeps a user edit when a deferred suggestion completes", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "My own task",
  );
  api.getSuggestion.mockResolvedValueOnce(readySuggestion);
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", "My own task");
  await act(async () => pending.resolve(readySuggestion));
  await waitFor(() => expect(screen.queryByText("Getting todo suggestions…")).toBeNull());
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp(
    "value",
    "My own task",
  );
  expect(screen.getByRole("button", { name: "Apply saved suggestions" })).toBeTruthy();
});

it("ignores a deferred suggestion after the workflow advances to another step", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  api.getWorkflow.mockResolvedValueOnce(reviewWorkflow);
  await act(async () => client.setQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID), reviewWorkflow));
  await waitFor(() => expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy());
  await act(async () => pending.resolve(readySuggestion));
  await waitFor(() => expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy());
  expect(screen.queryByText("Choose a date")).toBeNull();
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(reviewWorkflow);
});

it("ignores a deferred suggestion after sign-out", async () => {
  let current = true;
  const api = makeApi();
  const { client } = await renderHost(api, createAppQueryClient(), {
    isSessionCurrent: () => current,
  });
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  current = false;
  await act(async () => pending.resolve(readySuggestion));
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", "");
});

it("ignores a deferred suggestion after same-owner re-login changes the epoch", async () => {
  let epoch = 0;
  const api = makeApi();
  const { client } = await renderHost(api, createAppQueryClient(), {
    sessionEpoch: epoch,
    isSessionCurrent: (captured) => captured === epoch,
  });
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  epoch = 1;
  await act(async () => pending.resolve(readySuggestion));
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", "");
});

it("discards a late older result when a newer saved suggestion is active", async () => {
  const api = makeApi();
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  const { client } = await renderHost(api, createAppQueryClient(), { store });
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  api.getSuggestion.mockResolvedValueOnce(newerSuggestion);
  await act(async () => pending.resolve(readySuggestion));
  await waitFor(() => expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp(
    "value",
    "Newer saved title\nAnother newer title",
  ));
  expect(screen.queryByText("Choose a date")).toBeNull();
  expect(await store.read(USER_ID)).toBeNull();
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
});

it("does not mutate draft or cache when a deferred suggestion resolves after unmount", async () => {
  const api = makeApi();
  const { view, client } = await renderHost(api);
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  const pending = deferred<WorkflowSuggestion>();
  api.suggestWorkflow.mockReturnValueOnce(pending.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  await view.unmount();
  await act(async () => pending.resolve(readySuggestion));
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
});

it("recovers saved pending and failed suggestions without creating todos", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToCollect(api);
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.suggestWorkflow.mockResolvedValueOnce(pendingSuggestion);
  api.getSuggestion.mockResolvedValueOnce(pendingSuggestion);
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Start another request" })).toBeTruthy());
  expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
  expect(screen.queryByText("Getting todo suggestions…")).toBeNull();

  api.getSuggestion.mockResolvedValueOnce(failedSuggestion);
  await fireEvent.press(screen.getByRole("button", { name: "Check status" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Try suggestions again" })).toBeTruthy());
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(2);
});

it("clears a retained suggestion retry when mount recovers a ready result", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(savedSuggestionWrite);
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.getSuggestion.mockResolvedValue(readySuggestion);
  await renderHost(api, createAppQueryClient(), {
    store,
    initialWorkflowId: WORKFLOW_ID,
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Apply saved suggestions" })).toBeTruthy());
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull());
  expect(api.suggestWorkflow).not.toHaveBeenCalled();
  expect(await store.read(USER_ID)).toBeNull();
});

it.each([
  ["failed", failedSuggestion],
  ["superseded", supersededSuggestion],
])("clears a retained retry after a %s result is recovered", async (_status, result) => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(savedSuggestionWrite);
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.getSuggestion.mockResolvedValue(result);
  await renderHost(api, createAppQueryClient(), {
    store,
    initialWorkflowId: WORKFLOW_ID,
  });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull());
  expect(api.suggestWorkflow).not.toHaveBeenCalled();
  expect(await store.read(USER_ID)).toBeNull();
});

it("does not post a retained suggestion until explicit retry or discard", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(savedSuggestionWrite);
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.getSuggestion.mockResolvedValue(pendingSuggestion);
  await renderHost(api, createAppQueryClient(), {
    store,
    initialWorkflowId: WORKFLOW_ID,
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy());
  expect(api.suggestWorkflow).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByRole("button", { name: "Discard saved request" }));
  expect(screen.getByText(/may still finish or be billed/)).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Discard saved suggestion anyway" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull());
  expect(api.suggestWorkflow).not.toHaveBeenCalled();
  expect(await store.read(USER_ID)).toBeNull();
});

it("starts another pending request with a new UUID after an explicit warning", async () => {
  const api = makeApi();
  let requestNumber = 0;
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  await renderHost(api, createAppQueryClient(), {
    generateRequestId: () => (requestNumber++ === 0 ? REQUEST_ID : REQUEST_ID_2),
    initialWorkflowId: WORKFLOW_ID,
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Suggest todos" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  ));
  api.suggestWorkflow.mockResolvedValueOnce(pendingSuggestion).mockResolvedValueOnce({
    ...readySuggestion,
    request_id: REQUEST_ID_2,
  });
  api.getSuggestion.mockResolvedValueOnce(pendingSuggestion).mockResolvedValueOnce({
    ...readySuggestion,
    request_id: REQUEST_ID_2,
  });
  await fireEvent.press(screen.getByRole("button", { name: "Suggest todos" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Start another request" })).toBeTruthy());
  await fireEvent.press(screen.getByRole("button", { name: "Start another request" }));
  expect(screen.getByText(/may bill the earlier request/)).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Start another request anyway" }));
  await waitFor(() => expect(api.suggestWorkflow).toHaveBeenCalledTimes(2));
  expect(api.suggestWorkflow.mock.calls[1][1]).toEqual({
    request_id: REQUEST_ID_2,
    expected_revision: 2,
    step_id: `${WORKFLOW_ID}:COLLECT_TASKS`,
  });
});

it("requires explicit replacement before applying saved suggestions over edits", async () => {
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(collectWorkflow);
  api.getSuggestion.mockResolvedValue(readySuggestion);
  await renderHost(api, createAppQueryClient(), { initialWorkflowId: WORKFLOW_ID });
  await waitFor(() => expect(screen.getByRole("button", { name: "Apply saved suggestions" })).toBeTruthy());
  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), "My own task");
  await fireEvent.press(screen.getByRole("button", { name: "Apply saved suggestions" }));
  expect(screen.getByRole("button", { name: "Replace draft with saved suggestions" })).toBeTruthy();
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", "My own task");
  await fireEvent.press(screen.getByRole("button", { name: "Replace draft with saved suggestions" }));
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp(
    "value",
    "Choose a date\nInvite guests",
  );
});

const driveToReview = async (api: MockWorkflowApi) => {
  await driveToCollect(api);
  api.advanceWorkflow.mockResolvedValueOnce(reviewWorkflow);
  api.getWorkflow.mockResolvedValueOnce(reviewWorkflow);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\nBuy decorations\nBook venue"
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  await waitForQuiescence();
};

it.each([["assess"], ["collect"], ["review"]])(
  "cancels from %s with the exact command",
  async (from) => {
    const api = makeApi();
    await renderHost(api);
    if (from === "assess") {
      await startToAssess(api);
    } else if (from === "collect") {
      await driveToCollect(api);
    } else {
      await driveToReview(api);
    }
    // A cancel response always advances the revision past the current step;
    // an older revision would be recovery evidence, never a regression.
    const cancelledAt =
      from === "assess"
        ? cancelledWorkflow
        : from === "collect"
          ? { ...cancelledWorkflow, revision: 3 }
          : { ...cancelledWorkflow, revision: 4 };
    api.advanceWorkflow.mockResolvedValueOnce(cancelledAt);
    api.getWorkflow.mockResolvedValueOnce(cancelledAt);

    await fireEvent.press(screen.getByRole("button", { name: "Cancel planning" }));
    const cancelStep =
      from === "assess"
        ? { expected_revision: 0, step_id: `${WORKFLOW_ID}:ASSESS_TASK` }
        : from === "collect"
          ? { expected_revision: 2, step_id: `${WORKFLOW_ID}:COLLECT_TASKS` }
          : { expected_revision: 3, step_id: `${WORKFLOW_ID}:REVIEW` };
    await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
      request_id: REQUEST_ID,
      ...cancelStep,
      action: { action: "cancel" },
    }));

    await waitFor(() =>
      expect(screen.getByRole("header", { name: "Plan cancelled" })).toBeTruthy()
    );
    expect(screen.queryByRole("button", { name: "Cancel planning" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Yes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
  }
);

it("terminal screens expose only Back and call onExit once", async () => {
  const api = makeApi();
  const { onExit } = await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockResolvedValueOnce(completedWorkflow);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );

  expect(screen.queryByRole("button", { name: "Cancel planning" })).toBeNull();
  await fireEvent.press(screen.getByRole("button", { name: "Back to todos" }));
  expect(onExit).toHaveBeenCalledTimes(1);
});

it("seeds the workflow cache on start and replaces it on advance", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toBeUndefined();

  await startToAssess(api);
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(assessWorkflow);

  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
});

it("locks on uncertain advance and unlocks through an explicit retry", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Could not update the plan.");
  expect(
    screen.getByRole("header", { name: "Does this task involve multiple steps?" })
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );
  const callsAfterFailure = api.advanceWorkflow.mock.calls.length;

  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Retry saved request" }));
  expect(api.advanceWorkflow.mock.calls.length).toBe(callsAfterFailure + 1);
  const retryRequest = api.advanceWorkflow.mock.calls[callsAfterFailure][1] as WorkflowActionRequest;
  const firstRequest = api.advanceWorkflow.mock.calls[callsAfterFailure - 1][1] as WorkflowActionRequest;
  expect(retryRequest.request_id).toBe(firstRequest.request_id);
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
});


it("announces and focuses the state returned by an explicit retry", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  const inputFocusBefore = mockInputFocus.mock.calls.length;
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Retry saved request" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy());
  expect(mockInputFocus.mock.calls.length).toBeGreaterThan(inputFocusBefore);
  expect(mockAnnounceForAccessibility).toHaveBeenCalledWith("Break it into smaller todos");
});

it("invalidates todos on completion without a second todo array", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  client.setQueryData(["todos"], []);
  await driveToReview(api);
  api.advanceWorkflow.mockResolvedValueOnce(completedWorkflow);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );

  expect(client.getQueryState(["todos"])?.isInvalidated).toBe(true);
  expect(screen.queryByRole("header", { name: "Todos" })).toBeNull();
});

it("forgets the workflow ID on remount", async () => {
  const api = makeApi();
  const { view, client } = await renderHost(api);
  await startToAssess(api);
  const getsAfterFirstMount = api.getWorkflow.mock.calls.length;
  expect(getsAfterFirstMount).toBeGreaterThan(0);

  await view.unmount();
  await renderHost(api, client);

  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  expect(api.getWorkflow.mock.calls.length).toBe(getsAfterFirstMount);
  expect(api.startWorkflow).toHaveBeenCalledTimes(1);
});

it("moves focus to the Yes action after assessment appears", async () => {
  const api = makeApi();
  await renderHost(api);
  const focusBefore = mockControlFocus.length;
  await startToAssess(api);

  await waitFor(() => expect(mockControlFocus.length).toBeGreaterThan(focusBefore));
  expect(mockControlFocus[mockControlFocus.length - 1]).toBe("Yes");
  expect(mockAnnounceForAccessibility).toHaveBeenCalledWith("Does this task involve multiple steps?");
  expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123);
});

it("keeps web focus usable without native accessibility focus", async () => {
  mockPlatformOs = "web";
  try {
    const api = makeApi();
    await renderHost(api);
    await startToAssess(api);

    expect(mockControlFocus[mockControlFocus.length - 1]).toBe("Yes");
    expect(mockAnnounceForAccessibility).toHaveBeenCalledWith("Does this task involve multiple steps?");
    expect(mockFindNodeHandle).not.toHaveBeenCalled();
    expect(mockSetAccessibilityFocus).not.toHaveBeenCalled();
    expect(screen.getByRole("header", { name: "Does this task involve multiple steps?" })).toHaveProp(
      "accessibilityLiveRegion",
      "polite"
    );
  } finally {
    mockPlatformOs = "ios";
  }
});

it("moves focus to the breakdown input, Confirm, and terminal Back", async () => {
  const api = makeApi();
  await renderHost(api);
  const focusAfterStart = mockInputFocus.mock.calls.length;
  await driveToReview(api);

  expect(mockInputFocus.mock.calls.length).toBeGreaterThan(focusAfterStart);
  api.advanceWorkflow.mockResolvedValueOnce(completedWorkflow);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  expect(mockControlFocus[mockControlFocus.length - 1]).toBe("Back to todos");
  expect(mockAnnounceForAccessibility).toHaveBeenCalledWith("Plan complete");
  expect(mockSetAccessibilityFocus).toHaveBeenCalledWith(123);
});

it("keeps explicit roles, alerts, disabled semantics, and 44-point targets", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToReview(api);

  const confirm = screen.getByRole("button", { name: "Confirm plan" });
  const cancel = screen.getByRole("button", { name: "Cancel planning" });
  const back = screen.queryByRole("button", { name: "Back to todos" });
  expect(back).toBeNull();
  for (const control of [confirm, cancel]) {
    expect(StyleSheet.flatten(control.props.style).minHeight).toBeGreaterThanOrEqual(44);
  }

  const root = screen.root as unknown as {
    type: string;
    props: Record<string, unknown>;
    children: (unknown | string)[];
  };
  expect(root.type).toBe("RCTSafeAreaView");
});

it("preserves a draft when a refetch keeps the same step id", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToCollect(api);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations",
  );
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await act(async () => {
    await client.invalidateQueries({
      queryKey: workflowQueryKey(USER_ID, WORKFLOW_ID),
      refetchType: "none",
    });
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save tasks" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false })
    )
  );
  expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp(
    "value",
    "Send invitations"
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("clears draft and local error when step id changes", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToCollect(api);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Only one",
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  expect(screen.getByRole("alert")).toBeTruthy();

  await act(async () => {
    await client.invalidateQueries({
      queryKey: workflowQueryKey(USER_ID, WORKFLOW_ID),
      refetchType: "none",
    });
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());

  api.getWorkflow.mockResolvedValueOnce({
    ...collectWorkflow,
    state: "FUTURE_COLLECT",
    view: {
      type: "task_breakdown",
      step_id: `${WORKFLOW_ID}:FUTURE_COLLECT`,
      title: "Break it into smaller todos",
      min_titles: 3,
      max_titles: 4,
    },
  });
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() =>
    expect(screen.getByLabelText("Todo titles (one per line)")).toHaveProp("value", ""),
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("renders an unsupported view without submitting", async () => {
  const api = makeApi();
  api.startWorkflow.mockResolvedValueOnce({
    ...assessWorkflow,
    state: "FUTURE_STATE",
    view: {
      type: "unsupported",
      server_type: "future_template",
      step_id: `${WORKFLOW_ID}:FUTURE_STATE`,
    },
  });
  await renderHost(api);
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() => expect(screen.getByRole("header", { name: "Unsupported step" })).toBeTruthy());
  expect(screen.getByText("This planning step needs a newer app version.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Back to todos" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy();
  expect(mockControlFocus[mockControlFocus.length - 1]).toBe("Back to todos");
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

it("keeps one reload for an unsupported stale view through failed and working reloads", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  const unsupportedStart: TodoWorkflow = {
    ...assessWorkflow,
    state: "FUTURE_STATE",
    view: {
      type: "unsupported",
      server_type: "future_template",
      step_id: `${WORKFLOW_ID}:FUTURE_STATE`,
    },
  };
  api.startWorkflow.mockResolvedValueOnce(unsupportedStart);
  api.getWorkflow.mockResolvedValue(unsupportedStart);
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Unsupported step" })).toBeTruthy());
  await waitForQuiescence();
  // The post-start reconciliation GET already ran once (unmocked transport
  // rejects with invalid data); the unsupported view still exposes exactly
  // its own single reload and never submits.
  const getsAfterStart = api.getWorkflow.mock.calls.length;
  expect(getsAfterStart).toBeGreaterThan(0);
  expect(screen.getAllByRole("button", { name: "Reload plan" })).toHaveLength(1);

  await act(async () => {
    await client.invalidateQueries({
      queryKey: workflowQueryKey(USER_ID, WORKFLOW_ID),
      refetchType: "none",
    });
  });
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Reload plan" })).toHaveLength(1)
  );

  api.getWorkflow.mockRejectedValueOnce(
    new TodoApiError("invalid-data", "The API returned invalid plan data.")
  );
  await fireEvent.press(screen.getAllByRole("button", { name: "Reload plan" })[0]);
  await waitFor(() =>
    expect(api.getWorkflow.mock.calls.length).toBe(getsAfterStart + 1)
  );
  await waitFor(() =>
    expect(client.getQueryState(workflowQueryKey(USER_ID, WORKFLOW_ID))?.fetchStatus).toBe("idle")
  );
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Reload plan" })).toHaveLength(1)
  );
  expect(api.advanceWorkflow).not.toHaveBeenCalled();

  api.getWorkflow.mockResolvedValueOnce(assessWorkflow);
  await fireEvent.press(screen.getAllByRole("button", { name: "Reload plan" })[0]);
  await waitFor(() =>
    expect(api.getWorkflow.mock.calls.length).toBe(getsAfterStart + 2)
  );
  await waitFor(() =>
    expect(client.getQueryState(workflowQueryKey(USER_ID, WORKFLOW_ID))?.fetchStatus).toBe("idle")
  );
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Does this task involve multiple steps?" })).toBeTruthy()
  );
  expect(screen.queryAllByRole("button", { name: "Reload plan" })).toHaveLength(0);
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

const advanceRecord = (
  requestId: string,
  action: WorkflowActionRequest["action"],
  expectedRevision: number,
  state = "ASSESS_TASK"
): PendingWorkflowWrite => ({
  version: 1,
  ownerId: USER_ID,
  requestId,
  operation: "advance",
  workflowId: WORKFLOW_ID,
  body: {
    request_id: requestId,
    expected_revision: expectedRevision,
    step_id: `${WORKFLOW_ID}:${state}`,
    action,
  },
});

it("sends the stored start body with the generated request ID and reconciles", async () => {
  const api = makeApi();
  api.startWorkflow.mockResolvedValueOnce(assessWorkflow);
  api.getWorkflow.mockResolvedValueOnce(assessWorkflow);
  await renderHost(api);

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() => expect(api.startWorkflow).toHaveBeenCalledTimes(1));
  expect(api.startWorkflow).toHaveBeenCalledWith({
    request_id: REQUEST_ID,
    title: "Plan birthday party",
  });
  await waitFor(() => expect(api.getWorkflow).toHaveBeenCalled());
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
});

it("sends advance as a versioned envelope with the frozen revision and step", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledTimes(1));
  expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    request_id: REQUEST_ID,
    expected_revision: 0,
    step_id: `${WORKFLOW_ID}:ASSESS_TASK`,
    action: { action: "answer_multiple_steps", answer: true },
  });
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(offerWorkflow);
});

it("offers retry for a saved start without sending automatically", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save({
    version: 1,
    ownerId: USER_ID,
    requestId: REQUEST_ID,
    operation: "start",
    body: { request_id: REQUEST_ID, title: "Plan birthday party" },
  });
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), { store });

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(screen.getByRole("button", { name: "Discard saved request" })).toBeTruthy();
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(api.getWorkflow).not.toHaveBeenCalled();
});

it("offers retry for a saved action without sending automatically", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(
    advanceRecord(REQUEST_ID, { action: "answer_multiple_steps", answer: true }, 0)
  );
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(assessWorkflow);
  await renderHost(api, createAppQueryClient(), { store });

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
});

it("retries a lost confirmation with the same request ID and renders the newest revision", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await driveToReview(api);
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(reviewWorkflow);

  const confirming = deferred<TodoWorkflow>();
  api.advanceWorkflow.mockReturnValueOnce(confirming.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await act(async () => {
    confirming.reject(new TodoApiError("unavailable", "Could not update the plan."));
  });

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  // Three advances drive to review; the fourth is the lost confirmation.
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(4);
  const firstRequest = api.advanceWorkflow.mock.calls[3][1] as WorkflowActionRequest;
  expect(firstRequest.expected_revision).toBe(3);
  expect(firstRequest.step_id).toBe(`${WORKFLOW_ID}:REVIEW`);
  // A second write cannot replace the unresolved record.
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(4);

  // Another device advanced the plan while the response was lost.
  await act(async () => {
    client.setQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID), completedWorkflow);
    client.setQueryData(["todos"], []);
  });
  api.advanceWorkflow.mockResolvedValueOnce(reviewWorkflow);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Retry saved request" }));

  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledTimes(5));
  const retryRequest = api.advanceWorkflow.mock.calls[4][1] as WorkflowActionRequest;
  expect(retryRequest.request_id).toBe(firstRequest.request_id);
  // The replayed older outcome never regresses the newer cache entry.
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(
    completedWorkflow
  );
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  expect(client.getQueryState(["todos"])?.isInvalidated).toBe(true);
});

it("recovers a lost start with the same request ID after a restart", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  const api = makeApi();
  const first = await renderHost(api, createAppQueryClient(), { store });
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  const failing = deferred<TodoWorkflow>();
  api.startWorkflow.mockReturnValueOnce(failing.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await act(async () => {
    failing.reject(new TodoApiError("unavailable", "Could not start planning."));
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(api.startWorkflow).toHaveBeenCalledWith({
    request_id: REQUEST_ID,
    title: "Plan birthday party",
  });

  await first.view.unmount();
  api.startWorkflow.mockResolvedValueOnce(assessWorkflow);
  api.getWorkflow.mockResolvedValueOnce(assessWorkflow);
  await renderHost(api, first.client, { store });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(api.startWorkflow).toHaveBeenCalledTimes(1);

  await fireEvent.press(screen.getByRole("button", { name: "Retry saved request" }));
  await waitFor(() => expect(api.startWorkflow).toHaveBeenCalledTimes(2));
  expect(api.startWorkflow).toHaveBeenLastCalledWith({
    request_id: REQUEST_ID,
    title: "Plan birthday party",
  });
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
});

it("keeps controls disabled with a visible retry when reconciliation GET fails", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not reload the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy()
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Could not reload the plan.");
  // The mutation succeeded but reconciliation is unproven: the saved request
  // is retained and every write stays disabled until the GET succeeds.
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Reload plan" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false })
  );
});

it("reconciles a stale conflict automatically through a current GET", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "This plan changed. Reload it and try again.", "stale_step")
  );
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));

  await waitFor(() => expect(api.getWorkflow).toHaveBeenCalled());
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
});

it("keeps the stale explanation visible after reconciling to the current step", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "This plan changed. Reload it and try again.", "stale_step")
  );
  // The winner advanced the plan: the reconciliation GET returns a newer
  // step (an older revision would be correctly ignored by the cache guard).
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);

  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));

  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  // The reconciliation GET decides the rendered step, but the stale
  // explanation must survive it: the submitted answer was stale.
  expect(screen.getByRole("alert")).toHaveTextContent(
    "This plan changed. Reload it and try again."
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
});

it("clears the stale explanation when the next write starts", async () => {
  const api = makeApi();
  await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "This plan changed. Reload it and try again.", "stale_step")
  );
  api.getWorkflow.mockResolvedValueOnce({ ...reviewWorkflow, revision: 4 });
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This plan changed. Reload it and try again."
    )
  );

  api.advanceWorkflow.mockResolvedValueOnce(completedWorkflow);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("keeps a reused request ID until it is explicitly discarded", async () => {
  const api = makeApi();
  const { store } = await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError(
      "conflict",
      "This request ID was already used with different details.",
      "request_id_reused"
    )
  );
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "This request ID was already used with different details."
  );

  await fireEvent.press(screen.getByRole("button", { name: "Discard saved request" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The saved request was discarded locally, but the server may already have applied it. Refresh the list to check."
    )
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  await waitFor(() => expect(store.read(USER_ID)).resolves.toBeNull());
});

it("offers a saved request after same-user re-login but never for another user", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(
    advanceRecord(REQUEST_ID, { action: "answer_multiple_steps", answer: true }, 0)
  );
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(assessWorkflow);

  const first = await renderHost(api, createAppQueryClient(), {
    store,
    sessionEpoch: 0,
    isSessionCurrent: (epoch) => epoch === 0,
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  await first.view.unmount();

  // Same user, new session epoch: the record is still offered, never auto-sent.
  await renderHost(api, first.client, {
    store,
    sessionEpoch: 1,
    isSessionCurrent: (epoch) => epoch === 1,
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  expect(api.advanceWorkflow).not.toHaveBeenCalled();

  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Retry saved request" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
});

it("never loads another user's saved request", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(
    advanceRecord(REQUEST_ID, { action: "answer_multiple_steps", answer: true }, 0)
  );
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), { store, userId: OTHER_USER_ID });

  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

it("ignores a storage read that resolves after the session changed", async () => {
  const saved = advanceRecord(REQUEST_ID, { action: "answer_multiple_steps", answer: true }, 0);
  const backing = new Map<string, string>([
    [`${PENDING_WRITE_KEY_PREFIX}${USER_ID}`, JSON.stringify(saved)],
  ]);
  let releaseRead!: () => void;
  const raw = {
    getItem: (key: string) =>
      new Promise<string | null>((resolve) => {
        releaseRead = () => resolve(backing.get(key) ?? null);
      }),
    setItem: async (key: string, value: string) => {
      backing.set(key, value);
    },
    removeItem: async (key: string) => {
      backing.delete(key);
    },
  };
  const store = createPendingWriteStore(raw);
  let currentEpoch = 0;
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(assessWorkflow);
  await renderHost(api, createAppQueryClient(), {
    store,
    sessionEpoch: 0,
    isSessionCurrent: (epoch) => epoch === currentEpoch,
  });
  currentEpoch = 1;
  await act(async () => {
    releaseRead();
  });
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Help me plan a task" })
    ).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
});

it("blocks the network write when the device cannot save a safe retry", async () => {
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), {
    store: createPendingWriteStore({
      getItem: async () => null,
      setItem: async () => {
        throw new Error("disk full");
      },
      removeItem: async () => {},
    }),
  });

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This device could not save a safe retry. The plan was not sent. Try again."
    )
  );
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Start planning" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false })
  );
});

it("renders an unsupported definition without action controls", async () => {
  const api = makeApi();
  api.getWorkflow.mockRejectedValue(
    new TodoApiError(
      "conflict",
      "This plan uses an unsupported workflow definition.",
      "unsupported_workflow_definition"
    )
  );
  await renderHost(api, createAppQueryClient(), { initialWorkflowId: WORKFLOW_ID });

  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Unsupported step" })).toBeTruthy()
  );
  expect(screen.queryByRole("button", { name: "Yes" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Cancel planning" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Confirm plan" })).toBeNull();
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

it("keeps a second write from replacing an unresolved saved request", async () => {
  const store = createPendingWriteStore(createMemoryPendingWriteStorage());
  await store.save(
    advanceRecord(REQUEST_ID, { action: "answer_multiple_steps", answer: true }, 0)
  );
  const api = makeApi();
  api.getWorkflow.mockResolvedValue(assessWorkflow);
  await renderHost(api, createAppQueryClient(), {
    store,
    generateRequestId: () => REQUEST_ID_2,
  });

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  // The saved action targets a workflow that still has to load: wait for
  // its authoritative view before attempting the second write.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Yes" })).toBeTruthy()
  );
  // A new action press must not replace the unresolved record: the stored
  // request ID is unchanged and nothing is sent. Flush all pending async
  // work first so a leaked write would have completed before asserting.
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await act(async () => {});
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
  expect((await store.read(USER_ID))?.requestId).toBe(REQUEST_ID);
});

it("keeps recovery locked when clearing the saved request fails", async () => {
  const backing = createMemoryPendingWriteStorage();
  // Fail only the discard-time clear: the setup flow's own
  // reconciliation cleanup must still succeed.
  let failClear = false;
  const store = createPendingWriteStore({
    ...backing,
    removeItem: async (key: string) => {
      if (failClear) throw new Error("storage locked");
      await backing.removeItem(key);
    },
  });
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), { store });
  await startToAssess(api);
  failClear = true;
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy()
  );
  await fireEvent.press(screen.getByRole("button", { name: "Discard saved request" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The plan was saved, but recovery is still pending. Retry or discard the saved request."
    )
  );
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy();
  expect((await store.read(USER_ID))?.requestId).toBe(REQUEST_ID);
});

it("rejects an advance response that names a different workflow", async () => {
  const api = makeApi();
  const { client, store } = await renderHost(api);
  await startToAssess(api);
  const callsBefore = api.getWorkflow.mock.calls.length;
  // A rogue response for a workflow this request never targeted: valid
  // UUID, but not the workflow the saved advance targeted.
  const rogueWorkflow: TodoWorkflow = { ...offerWorkflow, workflow_id: OTHER_USER_ID };
  api.advanceWorkflow.mockResolvedValueOnce(rogueWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The API returned invalid plan data."
    )
  );
  // Invalid-response evidence: the pending record is retained for an
  // explicit retry, and the rogue identity is never seeded, fetched, or
  // adopted.
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy();
  expect((await store.read(USER_ID))?.requestId).toBe(REQUEST_ID);
  expect(api.getWorkflow.mock.calls.length).toBe(callsBefore);
  expect(
    client.getQueryData(workflowQueryKey(USER_ID, OTHER_USER_ID))
  ).toBeUndefined();
  expect(
    screen.getByRole("header", { name: "Does this task involve multiple steps?" })
  ).toBeTruthy();
  expect(
    screen.queryByRole("header", {
      name: "Would you like to split it into smaller todos?",
    })
  ).toBeNull();
});

it("clears the saved request before reconciling a stale conflict, even when the GET fails", async () => {
  const api = makeApi();
  const { store } = await renderHost(api);
  await driveToReview(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "This plan changed. Reload it and try again.", "stale_step")
  );
  api.getWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not reload the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));

  // The matching record is cleared first, so a failed reconciliation GET
  // leaves no Retry behind: controls stay disabled with Reload offered.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy()
  );
  await waitFor(() => expect(store.read(USER_ID)).resolves.toBeNull());
  expect(screen.queryByRole("button", { name: "Retry saved request" })).toBeNull();
  expect(screen.getByRole("button", { name: "Confirm plan" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );
});

it("ignores a failed save's storage read when the session changed", async () => {
  // Deterministic gating: the save's own existence check always resolves,
  // the save itself waits for release, and only reads after the release
  // (the failure handler's follow-up read) stay deferred.
  let releaseSave!: () => void;
  const saveGate = new Promise<void>((resolve) => {
    releaseSave = resolve;
  });
  let saveAttempted = false;
  let gateReads = false;
  let releaseRead!: () => void;
  const store = createPendingWriteStore({
    getItem: (key: string) => {
      if (!gateReads) return Promise.resolve(null);
      return new Promise<string | null>((resolve) => {
        releaseRead = () => resolve(null);
      });
    },
    setItem: async () => {
      saveAttempted = true;
      await saveGate;
      throw new Error("disk full");
    },
    removeItem: async () => {},
  });
  let currentEpoch = 0;
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), {
    store,
    sessionEpoch: 0,
    isSessionCurrent: (epoch) => epoch === currentEpoch,
  });

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() => expect(saveAttempted).toBe(true));
  gateReads = true;
  currentEpoch = 1;
  await act(async () => {
    releaseSave();
  });
  await act(async () => {
    releaseRead();
  });
  await act(async () => {});

  // The stale failure handler must not touch state: no alert, no send.
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("leaves reconciliation state untouched when the session changes mid-reconcile", async () => {
  let currentEpoch = 0;
  const api = makeApi();
  const { client } = await renderHost(api, createAppQueryClient(), {
    sessionEpoch: 0,
    isSessionCurrent: (epoch) => epoch === currentEpoch,
  });
  await startToAssess(api);
  const callsBefore = api.getWorkflow.mock.calls.length;
  const advanceGate = deferred<TodoWorkflow>();
  const getGate = deferred<TodoWorkflow>();
  api.advanceWorkflow.mockReturnValueOnce(advanceGate.promise);
  api.getWorkflow.mockReturnValueOnce(getGate.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledTimes(1));
  await act(async () => {
    advanceGate.resolve(offerWorkflow);
  });
  await waitFor(() =>
    expect(api.getWorkflow.mock.calls.length).toBe(callsBefore + 1)
  );
  // The session changes while the reconciliation GET is in flight.
  currentEpoch = 1;
  await act(async () => {
    getGate.resolve(offerWorkflow);
  });
  await act(async () => {});

  // The stale GET resolves into nothing: no render, no cache write.
  expect(
    screen.getByRole("header", { name: "Does this task involve multiple steps?" })
  ).toBeTruthy();
  expect(
    screen.queryByRole("header", {
      name: "Would you like to split it into smaller todos?",
    })
  ).toBeNull();
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(
    assessWorkflow
  );
  // And the stale completion must not reset the in-flight indicator:
  // state updates require a current session, including finally blocks.
  expect(screen.getByText("Reloading plan…")).toBeTruthy();
});

it("renders an advance only after its reconciliation GET resolves", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  const advanceGate = deferred<TodoWorkflow>();
  const getGate = deferred<TodoWorkflow>();
  api.advanceWorkflow.mockReturnValueOnce(advanceGate.promise);
  api.getWorkflow.mockReturnValueOnce(getGate.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(api.advanceWorkflow).toHaveBeenCalledTimes(1));
  await act(async () => {
    advanceGate.resolve(offerWorkflow);
  });
  await act(async () => {});

  // The mutation response alone renders nothing and writes stay disabled
  // until the reconciliation GET resolves.
  expect(
    screen.getByRole("header", { name: "Does this task involve multiple steps?" })
  ).toBeTruthy();
  expect(
    screen.queryByRole("header", {
      name: "Would you like to split it into smaller todos?",
    })
  ).toBeNull();
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  await act(async () => {
    getGate.resolve(offerWorkflow);
  });
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false })
  );
});

it("resets the recovery lock when clearing before a stale reconciliation fails", async () => {
  const backing = createMemoryPendingWriteStorage();
  // Fail only the conflict-time clear: the setup flow's own reconciliation
  // cleanup must still succeed.
  let failClear = false;
  const store = createPendingWriteStore({
    ...backing,
    removeItem: async (key: string) => {
      if (failClear) throw new Error("storage locked");
      await backing.removeItem(key);
    },
  });
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), { store });
  await driveToReview(api);
  failClear = true;
  const callsBefore = api.getWorkflow.mock.calls.length;
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "This plan changed. Reload it and try again.", "stale_step")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));

  // The clear failed before any reconciliation GET: the pending record is
  // retained with a recovery lock, but reconciliation itself must reset so
  // Retry/Discard stay usable and no GET is attempted.
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The plan was saved, but recovery is still pending. Retry or discard the saved request."
    )
  );
  await act(async () => {});
  expect(api.getWorkflow.mock.calls.length).toBe(callsBefore);
  expect((await store.read(USER_ID))?.requestId).toBe(REQUEST_ID);
  expect(screen.queryByText("Reloading plan…")).toBeNull();
  expect(screen.getByRole("button", { name: "Retry saved request" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false })
  );
  expect(screen.getByRole("button", { name: "Discard saved request" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false })
  );
});

it("ignores a reload's storage clear that resolves after the session changed", async () => {
  const backing = createMemoryPendingWriteStorage();
  let releaseClear!: () => void;
  const clearGate = new Promise<void>((resolve) => {
    releaseClear = resolve;
  });
  let clearAttempted = false;
  let gateClear = false;
  const store = createPendingWriteStore({
    ...backing,
    removeItem: async (key: string) => {
      if (gateClear) {
        clearAttempted = true;
        await clearGate;
      }
      await backing.removeItem(key);
    },
  });
  let currentEpoch = 0;
  const api = makeApi();
  await renderHost(api, createAppQueryClient(), {
    store,
    sessionEpoch: 0,
    isSessionCurrent: (epoch) => epoch === currentEpoch,
  });
  await startToAssess(api);
  // Reach the GET-failure lock with a retained record: Retry and Reload
  // are both visible.
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);
  api.getWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not reload the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy()
  );
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy();

  // The manual reload's refetch succeeds but its storage clear stays
  // deferred; the session changes before the clear resolves.
  gateClear = true;
  api.getWorkflow.mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() => expect(clearAttempted).toBe(true));
  currentEpoch = 1;
  await act(async () => {
    releaseClear();
  });
  await act(async () => {});

  // The stale clear resolves into nothing: the retry stays offered, the
  // lock message stays, and no state is consumed. The storage delete
  // itself already landed (the refetch had proven the request resolved);
  // only the UI consumption is skipped for the stale session.
  expect(screen.getByRole("button", { name: "Retry saved request" })).toBeTruthy();
  expect(screen.getByRole("alert")).toHaveTextContent("Could not reload the plan.");
  await waitFor(() => expect(store.read(USER_ID)).resolves.toBeNull());
});

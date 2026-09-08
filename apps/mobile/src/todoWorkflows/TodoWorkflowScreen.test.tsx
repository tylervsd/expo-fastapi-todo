import * as mockReact from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { StyleSheet } from "react-native";
import { createAppQueryClient } from "../../App";
import { TodoApiError, type TodoWorkflow } from "../todos/todoApi";
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
  listWorkflows: jest.MockedFunction<TodoWorkflowScreenApi["listWorkflows"]>;
};

const makeApi = (): MockWorkflowApi => ({
  startWorkflow: jest.fn() as MockWorkflowApi["startWorkflow"],
  getWorkflow: jest.fn() as MockWorkflowApi["getWorkflow"],
  advanceWorkflow: jest.fn() as MockWorkflowApi["advanceWorkflow"],
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
const USER_ID = "user-1";

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

const renderHost = async (api: MockWorkflowApi, client = createAppQueryClient()) => {
  liveClients.push(client);
  const onExit = jest.fn();
  const view = await render(
    <QueryClientProvider client={client}>
      <TodoWorkflowScreen userId={USER_ID} api={api} onExit={onExit} />
    </QueryClientProvider>
  );
  return { view, onExit, client };
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
  expect(api.startWorkflow).toHaveBeenCalledWith("Plan birthday party");
  expect(screen.getByText("Submitting…")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Back to todos" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  await act(async () => {
    starting.resolve(assessWorkflow);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Does this task involve multiple steps?" })).toBeTruthy()
  );
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
  expect(screen.getByText("Submitting…")).toBeTruthy();
  await act(async () => answering.resolve(collectWorkflow));
  await waitFor(() => expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy());

  api.advanceWorkflow.mockReturnValueOnce(submitting.promise);
  await fireEvent.changeText(screen.getByLabelText("Todo titles (one per line)"), "One\nTwo");
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  expect(screen.getByText("Submitting…")).toBeTruthy();
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

it("shows lost-start uncertainty without retry and keeps Back", async () => {
  const api = makeApi();
  api.startWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not start planning.")
  );
  const { onExit } = await renderHost(api);

  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The result may be unknown. Starting again may create another draft."
    )
  );
  expect(api.startWorkflow).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  const back = screen.getByRole("button", { name: "Back to todos" });
  expect(back).toHaveProp("accessibilityState", expect.objectContaining({ disabled: false }));
  await fireEvent.press(back);
  expect(onExit).toHaveBeenCalledTimes(1);
});

const startToAssess = async (api: MockWorkflowApi, title = "Plan birthday party") => {
  api.startWorkflow.mockResolvedValueOnce(assessWorkflow);
  await fireEvent.changeText(screen.getByLabelText("Task title"), title);
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
};

it("uses the shared yes/no template for both questions", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  expect(screen.getByText("Assessment title from the view")).toBeTruthy();
  api.advanceWorkflow.mockResolvedValueOnce(offerWorkflow);

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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  expect(api.advanceWorkflow).toHaveBeenLastCalledWith(WORKFLOW_ID, {
    action: "answer_multiple_steps",
    answer: true,
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
  await fireEvent.press(screen.getByRole("button", { name: "No" }));
  expect(api.advanceWorkflow).toHaveBeenLastCalledWith(WORKFLOW_ID, {
    action: "answer_multiple_steps",
    answer: false,
  });
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
  expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    action: "answer_multiple_steps",
    answer: false,
  });

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
  expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, {
    action: "submit_tasks",
    titles: ["Send invitations", "Buy decorations", "Book venue"],
  });
  expect(screen.queryByRole("header", { name: "Review your plan" })).toBeNull();

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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  api.advanceWorkflow.mockResolvedValueOnce(customCollect);
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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  api.advanceWorkflow.mockResolvedValueOnce(reviewWorkflow);
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
  expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, { action: "confirm" });
  expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy();

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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  api.advanceWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
};

const driveToReview = async (api: MockWorkflowApi) => {
  await driveToCollect(api);
  api.advanceWorkflow.mockResolvedValueOnce(reviewWorkflow);
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\nBuy decorations\nBook venue"
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
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
    api.advanceWorkflow.mockResolvedValueOnce(cancelledWorkflow);

    await fireEvent.press(screen.getByRole("button", { name: "Cancel planning" }));
    expect(api.advanceWorkflow).toHaveBeenCalledWith(WORKFLOW_ID, { action: "cancel" });

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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  expect(client.getQueryData(workflowQueryKey(USER_ID, WORKFLOW_ID))).toEqual(collectWorkflow);
});

it("locks on uncertain advance and unlocks only on a valid reload", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The result may be unknown. Reload this plan before trying again."
    )
  );
  expect(
    screen.getByRole("header", { name: "Does this task involve multiple steps?" })
  ).toBeTruthy();
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());
  const callsAfterFailure = api.advanceWorkflow.mock.calls.length;

  const reloading = deferred<TodoWorkflow>();
  api.getWorkflow.mockReturnValueOnce(reloading.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  expect(api.getWorkflow).toHaveBeenCalledTimes(1);
  expect(api.advanceWorkflow.mock.calls.length).toBe(callsAfterFailure);

  await act(async () => {
    reloading.resolve(collectWorkflow);
  });
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button", { name: "Reload plan" })).toBeNull();
});

it("keeps the lock when reload fails and unlocks on the next valid reload", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());

  api.getWorkflow.mockRejectedValueOnce(
    new TodoApiError("invalid-data", "The API returned invalid plan data.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "Yes" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
});

it("reconciles conflict immediately through exactly one safe GET", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  const recovering = deferred<TodoWorkflow>();
  api.getWorkflow.mockReturnValueOnce(recovering.promise);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("conflict", "The plan changed. Reload to continue.")
  );

  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));

  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("The plan changed. Reload to continue.")
  );
  await waitFor(() => expect(api.getWorkflow).toHaveBeenCalledTimes(1));
  expect(api.advanceWorkflow).toHaveBeenCalledTimes(1);
  await act(async () => recovering.resolve(collectWorkflow));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("announces and focuses the state returned by recovery GET", async () => {
  const api = makeApi();
  await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());
  const inputFocusBefore = mockInputFocus.mock.calls.length;
  api.getWorkflow.mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy());
  expect(mockInputFocus.mock.calls.length).toBeGreaterThan(inputFocusBefore);
  expect(mockAnnounceForAccessibility).toHaveBeenCalledWith("Break it into smaller todos");
});

it("invalidates todos when recovery GET returns COMPLETED", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  await startToAssess(api);
  api.advanceWorkflow.mockRejectedValueOnce(
    new TodoApiError("unavailable", "Could not update the plan.")
  );
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload plan" })).toBeTruthy());
  client.setQueryData(["todos"], []);
  api.getWorkflow.mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Reload plan" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy());
  expect(client.getQueryState(["todos"])?.isInvalidated).toBe(true);
});

it("invalidates todos on completion without a second todo array", async () => {
  const api = makeApi();
  const { client } = await renderHost(api);
  client.setQueryData(["todos"], []);
  await driveToReview(api);
  api.advanceWorkflow.mockResolvedValueOnce(completedWorkflow);

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
  expect(api.getWorkflow).not.toHaveBeenCalled();

  await view.unmount();
  await renderHost(api, client);

  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect(api.getWorkflow).not.toHaveBeenCalled();
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
  api.startWorkflow.mockResolvedValueOnce({
    ...assessWorkflow,
    state: "FUTURE_STATE",
    view: {
      type: "unsupported",
      server_type: "future_template",
      step_id: `${WORKFLOW_ID}:FUTURE_STATE`,
    },
  });
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Unsupported step" })).toBeTruthy());

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
  await waitFor(() => expect(api.getWorkflow).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(client.getQueryState(workflowQueryKey(USER_ID, WORKFLOW_ID))?.fetchStatus).toBe("idle")
  );
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Reload plan" })).toHaveLength(1)
  );
  expect(api.advanceWorkflow).not.toHaveBeenCalled();

  api.getWorkflow.mockResolvedValueOnce(assessWorkflow);
  await fireEvent.press(screen.getAllByRole("button", { name: "Reload plan" })[0]);
  await waitFor(() => expect(api.getWorkflow).toHaveBeenCalledTimes(2));
  await waitFor(() =>
    expect(client.getQueryState(workflowQueryKey(USER_ID, WORKFLOW_ID))?.fetchStatus).toBe("idle")
  );
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Does this task involve multiple steps?" })).toBeTruthy()
  );
  expect(screen.queryAllByRole("button", { name: "Reload plan" })).toHaveLength(0);
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

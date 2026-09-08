import * as mockReact from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { createAppQueryClient } from "../App";
import type { AuthenticatedApi } from "./auth/authenticatedApi";
import type { Todo, TodoWorkflow } from "./todos/todoApi";
import { TodoExperience } from "./TodoExperience";
import {
  createMemoryPendingWriteStorage,
  createPendingWriteStore,
} from "./todoWorkflows/pendingWorkflowWrite";

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestTextInput = mockReact.forwardRef(
    (
      props: Record<string, unknown>,
      ref: mockReact.Ref<{ focus: () => void; blur: () => void }>
    ) => {
      mockReact.useImperativeHandle(ref, () => ({ focus: jest.fn(), blur: jest.fn() }), []);
      return mockReact.createElement(actual.TextInput, props);
    }
  );
  TestTextInput.displayName = "TestTextInput";
  const TestPressable = (props: Record<string, unknown>) =>
    mockReact.createElement("View", {
      ...props,
      accessible: true,
      accessibilityState:
        props.disabled === undefined
          ? props.accessibilityState
          : { ...(props.accessibilityState as Record<string, unknown>), disabled: props.disabled },
    });
  TestPressable.displayName = "TestPressable";
  return new Proxy(actual, {
    get(target, property, receiver) {
      if (property === "TextInput") return TestTextInput;
      if (property === "Pressable") return TestPressable;
      if (property === "findNodeHandle") return () => 123;
      if (property === "AccessibilityInfo") {
        return {
          ...actual.AccessibilityInfo,
          announceForAccessibility: () => undefined,
          setAccessibilityFocus: () => undefined,
        };
      }
      return Reflect.get(target, property, receiver);
    },
  });
});

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

const WORKFLOW_ID = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
const OTHER_WORKFLOW_ID = "7dd44c95-27b9-5e8f-bf05-0d61cc568e83";
const USER_ID = "9a4b3c2d-1e2f-4a5b-8c6d-7e8f9a0b1c2d";
const OTHER_USER_ID = "8b3a2c1d-9e8f-4a5b-8c6d-7e8f9a0b1c2e";
const REQUEST_ID = "30bfb542-17f1-48a0-9fd8-3930379d5974";

const todo = (id: string, title: string): Todo => ({ id, title, completed: false });

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
    title: "Plan birthday party",
    question: "Does this task involve multiple steps?",
    actions: [
      { id: "yes", label: "Yes" },
      { id: "no", label: "No" },
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

type MockShellApi = {
  [K in keyof AuthenticatedApi]: jest.Mock;
};

const makeShellApi = (): MockShellApi =>
  ({
    list: jest.fn(async () => []),
    create: jest.fn(),
    rename: jest.fn(),
    setCompleted: jest.fn(),
    remove: jest.fn(),
    startWorkflow: jest.fn(),
    getWorkflow: jest.fn(async () => assessWorkflow),
    advanceWorkflow: jest.fn(),
    listWorkflows: jest.fn(async () => ({ items: [] })),
  }) as unknown as MockShellApi;

const renderShell = async (
  api: MockShellApi,
  userId = USER_ID,
  client = createAppQueryClient()
) => {
  liveClients.push(client);
  const view = await render(
    <QueryClientProvider client={client}>
      <TodoExperience
        userId={userId}
        api={api}
        pendingStore={createPendingWriteStore(createMemoryPendingWriteStorage())}
        generateRequestId={() => REQUEST_ID}
        sessionEpoch={0}
        isSessionCurrent={() => true}
      />
    </QueryClientProvider>
  );
  return { view, client };
};

afterEach(() => {
  while (liveClients.length > 0) {
    const client = liveClients.pop() as QueryClient;
    client.unmount();
    client.clear();
  }
});

it("starts on the todo list with quick-add intact", async () => {
  const api = makeShellApi();
  await renderShell(api);

  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByLabelText("Todo title")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
  expect(api.startWorkflow).not.toHaveBeenCalled();
});

it("switches to workflow start without a workflow request", async () => {
  const api = makeShellApi();
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));

  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect(screen.queryByRole("header", { name: "Todos" })).toBeNull();
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(api.getWorkflow).not.toHaveBeenCalled();
});

it("returns from pre-ID start without losing todos", async () => {
  const api = makeShellApi();
  ;(api.list as jest.Mock).mockResolvedValue([todo("1", "Buy milk")]);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.press(screen.getByRole("button", { name: "Back to todos" }));

  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy()
  );
  expect(api.startWorkflow).not.toHaveBeenCalled();
});

it("disables Back while start is pending and stays in workflow mode", async () => {
  const api = makeShellApi();
  let release!: (value: TodoWorkflow) => void;
  ;(api.startWorkflow as jest.Mock).mockReturnValueOnce(
    new Promise<TodoWorkflow>((resolve) => {
      release = resolve;
    })
  );
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Ignored draft");
  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));

  expect(screen.getByRole("button", { name: "Back to todos" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true })
  );

  release(assessWorkflow);
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
});

it("returns to todos after cancel", async () => {
  const api = makeShellApi();
  ;(api.list as jest.Mock).mockResolvedValue([]);
  ;(api.startWorkflow as jest.Mock).mockResolvedValue(assessWorkflow);
  ;(api.advanceWorkflow as jest.Mock).mockResolvedValue(cancelledWorkflow);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  // Rendering waits for the reconciliation GET: stage it for the cancel.
  ;(api.getWorkflow as jest.Mock).mockResolvedValueOnce(cancelledWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Cancel planning" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan cancelled" })).toBeTruthy()
  );

  await fireEvent.press(screen.getByRole("button", { name: "Back to todos" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy());
});

it("returns after completion onto a refetching todo list", async () => {
  const offerWorkflow: TodoWorkflow = {
    ...assessWorkflow,
    revision: 1,
    state: "OFFER_BREAKDOWN",
    context: { involves_multiple_steps: true, proposed_todo_titles: [] },
    view: {
      type: "yes_no",
      step_id: `${WORKFLOW_ID}:OFFER_BREAKDOWN`,
      title: "Plan birthday party",
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
      proposed_todo_titles: ["Send invitations", "Buy decorations"],
    },
    view: {
      type: "review",
      step_id: `${WORKFLOW_ID}:REVIEW`,
      title: "Review your plan",
      proposed_titles: ["Send invitations", "Buy decorations"],
    },
  };
  const completedWorkflow: TodoWorkflow = {
    ...reviewWorkflow,
    revision: 4,
    state: "COMPLETED",
    result: {
      created_todos: [
        { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Send invitations", completed: false },
      ],
    },
    view: {
      type: "completion",
      step_id: `${WORKFLOW_ID}:COMPLETED`,
      title: "Plan complete",
      outcome: "completed",
      created_todos: [
        { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Send invitations", completed: false },
      ],
    },
  };
  const api = makeShellApi();
  ;(api.list as jest.Mock).mockResolvedValue([]);
  ;(api.startWorkflow as jest.Mock).mockResolvedValue(assessWorkflow);
  ;(api.advanceWorkflow as jest.Mock)
    .mockResolvedValueOnce(offerWorkflow)
    .mockResolvedValueOnce(collectWorkflow)
    .mockResolvedValueOnce(reviewWorkflow)
    .mockResolvedValueOnce(completedWorkflow);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  const listsBefore = (api.list as jest.Mock).mock.calls.length;

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  ;(api.getWorkflow as jest.Mock).mockResolvedValueOnce(offerWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", {
        name: "Would you like to split it into smaller todos?",
      })
    ).toBeTruthy()
  );
  ;(api.getWorkflow as jest.Mock).mockResolvedValueOnce(collectWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\nBuy decorations"
  );
  ;(api.getWorkflow as jest.Mock).mockResolvedValueOnce(reviewWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
  ;(api.getWorkflow as jest.Mock).mockResolvedValueOnce(completedWorkflow);
  await fireEvent.press(screen.getByRole("button", { name: "Confirm plan" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan complete" })).toBeTruthy()
  );

  await fireEvent.press(screen.getByRole("button", { name: "Back to todos" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy());
  await waitFor(() =>
    expect((api.list as jest.Mock).mock.calls.length).toBeGreaterThan(listsBefore)
  );
});

it("hides shell Back on a persisted active workflow", async () => {
  const api = makeShellApi();
  ;(api.startWorkflow as jest.Mock).mockResolvedValue(assessWorkflow);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );

  const backs = screen.queryAllByRole("button", { name: "Back to todos" });
  expect(backs).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Cancel planning" })).toBeTruthy();
});

it("switching users through remount cannot render the prior workflow key", async () => {
  const api = makeShellApi();
  ;(api.startWorkflow as jest.Mock).mockResolvedValue(assessWorkflow);
  const { view, client } = await renderShell(api, USER_ID);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  await fireEvent.changeText(screen.getByLabelText("Task title"), "Plan birthday party");
  await fireEvent.press(screen.getByRole("button", { name: "Start planning" }));
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  expect(
    client.getQueryData(["todo-workflow", USER_ID, WORKFLOW_ID])
  ).toEqual(assessWorkflow);
  const getsAfterFirstUser = (api.getWorkflow as jest.Mock).mock.calls.length;

  await view.unmount();
  await renderShell(api, OTHER_USER_ID, client);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect((api.getWorkflow as jest.Mock).mock.calls.length).toBe(getsAfterFirstUser);
  expect(
    client.getQueryData(["todo-workflow", OTHER_USER_ID, WORKFLOW_ID])
  ).toBeUndefined();
});

const reviewItem: TodoWorkflow = {
  ...assessWorkflow,
  workflow_id: OTHER_WORKFLOW_ID,
  revision: 3,
  state: "REVIEW",
  context: {
    involves_multiple_steps: true,
    proposed_todo_titles: ["Send invitations", "Buy decorations"],
  },
  view: {
    type: "review",
    step_id: `${OTHER_WORKFLOW_ID}:REVIEW`,
    title: "Review your plan",
    proposed_titles: ["Send invitations", "Buy decorations"],
  },
};

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
};

it("lists active plans with quick add intact and resumes without advancing", async () => {
  const api = makeShellApi();
  ;(api.listWorkflows as jest.Mock).mockResolvedValue({
    items: [assessWorkflow, reviewItem],
  });
  const { client } = await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Resume plans" })).toBeTruthy()
  );
  expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
  const resumeButton = screen.getByRole("button", {
    name: "Plan birthday party, Does this task involve multiple steps?",
  });
  expect(resumeButton).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Plan birthday party, Review your plan" })
  ).toBeTruthy();
  // Discovery seeds per-workflow entries for instant resume.
  expect(
    client.getQueryData(["todo-workflow", USER_ID, OTHER_WORKFLOW_ID])
  ).toEqual(reviewItem);

  await fireEvent.press(resumeButton);
  await waitFor(() =>
    expect(
      screen.getByRole("header", { name: "Does this task involve multiple steps?" })
    ).toBeTruthy()
  );
  expect(api.startWorkflow).not.toHaveBeenCalled();
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

it("hides the resume section when no plans are active", async () => {
  const api = makeShellApi();
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  await waitFor(() =>
    expect((api.listWorkflows as jest.Mock).mock.calls.length).toBeGreaterThan(0)
  );
  expect(screen.queryByRole("header", { name: "Resume plans" })).toBeNull();
  expect(screen.getByRole("button", { name: "Add todo" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Help me plan a task" })).toBeTruthy();
});

it("shows loading, error, and retry states for discovery", async () => {
  const api = makeShellApi();
  const pending = deferred<{ items: TodoWorkflow[] }>();
  ;(api.listWorkflows as jest.Mock).mockReturnValueOnce(pending.promise);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await waitFor(() =>
    expect(screen.getByText("Loading saved plans…")).toBeTruthy()
  );

  await act(async () => {
    pending.reject(new Error("offline"));
  });
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load saved plans.")
  );
  ;(api.listWorkflows as jest.Mock).mockResolvedValueOnce({ items: [assessWorkflow] });
  await fireEvent.press(screen.getByRole("button", { name: "Retry loading saved plans" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", {
        name: "Plan birthday party, Does this task involve multiple steps?",
      })
    ).toBeTruthy()
  );
});

it("resumes an unsupported saved plan without submitting", async () => {
  const api = makeShellApi();
  const unsupported = {
    workflow_id: OTHER_WORKFLOW_ID,
    revision: 1,
    definition_version: 1,
    view_contract_version: 2,
    view: {
      type: "unsupported",
      server_type: "contract:2",
      step_id: `${OTHER_WORKFLOW_ID}:unsupported-contract:2`,
    },
  } as unknown as TodoWorkflow;
  ;(api.listWorkflows as jest.Mock).mockResolvedValue({ items: [unsupported] });
  ;(api.getWorkflow as jest.Mock).mockResolvedValue(unsupported);
  await renderShell(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  const resumeButton = await waitFor(() =>
    screen.getByRole("button", {
      name: `Unsupported saved plan, ${OTHER_WORKFLOW_ID}`,
    })
  );
  await fireEvent.press(resumeButton);
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Unsupported step" })).toBeTruthy()
  );
  expect(api.advanceWorkflow).not.toHaveBeenCalled();
});

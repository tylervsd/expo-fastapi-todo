import * as mockReact from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { createAppQueryClient } from "../App";
import type { AuthenticatedApi } from "./auth/authenticatedApi";
import type { Todo, TodoWorkflow } from "./todos/todoApi";
import { TodoExperience } from "./TodoExperience";

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

const todo = (id: string, title: string): Todo => ({ id, title, completed: false });

const assessWorkflow: TodoWorkflow = {
  workflow_id: WORKFLOW_ID,
  state: "ASSESS_TASK",
  title: "Plan birthday party",
  context: { involves_multiple_steps: null, proposed_todo_titles: [] },
  result: null,
};

const cancelledWorkflow: TodoWorkflow = { ...assessWorkflow, state: "CANCELLED" };

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
    getWorkflow: jest.fn(),
    advanceWorkflow: jest.fn(),
  }) as unknown as MockShellApi;

const renderShell = async (
  api: MockShellApi,
  userId = "user-1",
  client = createAppQueryClient()
) => {
  liveClients.push(client);
  const view = await render(
    <QueryClientProvider client={client}>
      <TodoExperience userId={userId} api={api} />
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
  await fireEvent.press(screen.getByRole("button", { name: "Cancel planning" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Plan cancelled" })).toBeTruthy()
  );

  await fireEvent.press(screen.getByRole("button", { name: "Back to todos" }));
  await waitFor(() => expect(screen.getByRole("header", { name: "Todos" })).toBeTruthy());
});

it("returns after completion onto a refetching todo list", async () => {
  const reviewWorkflow: TodoWorkflow = {
    ...assessWorkflow,
    state: "REVIEW",
    context: {
      involves_multiple_steps: true,
      proposed_todo_titles: ["Send invitations", "Buy decorations"],
    },
  };
  const completedWorkflow: TodoWorkflow = {
    ...reviewWorkflow,
    state: "COMPLETED",
    result: {
      created_todos: [
        { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Send invitations", completed: false },
      ],
    },
  };
  const api = makeShellApi();
  ;(api.list as jest.Mock).mockResolvedValue([]);
  ;(api.startWorkflow as jest.Mock).mockResolvedValue(assessWorkflow);
  ;(api.advanceWorkflow as jest.Mock)
    .mockResolvedValueOnce({
      ...assessWorkflow,
      state: "COLLECT_TASKS",
      context: { involves_multiple_steps: true, proposed_todo_titles: [] },
    })
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
  await fireEvent.press(screen.getByRole("button", { name: "Yes" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Break it into smaller todos" })).toBeTruthy()
  );
  await fireEvent.changeText(
    screen.getByLabelText("Todo titles (one per line)"),
    "Send invitations\nBuy decorations"
  );
  await fireEvent.press(screen.getByRole("button", { name: "Save tasks" }));
  await waitFor(() =>
    expect(screen.getByRole("header", { name: "Review your plan" })).toBeTruthy()
  );
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
  const { view, client } = await renderShell(api, "user-1");
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
    client.getQueryData(["todo-workflow", "user-1", WORKFLOW_ID])
  ).toEqual(assessWorkflow);

  await view.unmount();
  await renderShell(api, "user-2", client);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());

  await fireEvent.press(screen.getByRole("button", { name: "Help me plan a task" }));
  expect(screen.getByRole("header", { name: "Help me plan a task" })).toBeTruthy();
  expect(api.getWorkflow).not.toHaveBeenCalled();
});

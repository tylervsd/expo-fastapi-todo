import * as mockReact from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { QueryClientProvider, timeoutManager, type QueryClient } from "@tanstack/react-query";
import { StyleSheet } from "react-native";
import { createAppQueryClient } from "../App";
import { TodoApiError, type Todo } from "./todos/todoApi";
import { TodoScreen, type TodoScreenApi } from "./TodoScreen";

const mockInputFocusEditable: (boolean | undefined)[] = [];
const mockInputBlurEditable: (boolean | undefined)[] = [];
let mockInputEditable: boolean | undefined;
const mockInputFocus = jest.fn(() => {
  mockInputFocusEditable.push(mockInputEditable);
});
const mockInputBlur = jest.fn(() => {
  mockInputBlurEditable.push(mockInputEditable);
});

jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const TestTextInput = mockReact.forwardRef((props: Record<string, unknown>, ref: mockReact.Ref<{ focus: () => void; blur: () => void }>) => {
    mockInputEditable = props.editable as boolean | undefined;
    mockReact.useImperativeHandle(ref, () => ({ focus: mockInputFocus, blur: mockInputBlur }), []);
    return mockReact.createElement(actual.TextInput, props);
  });
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

type MockTodoApi = {
  list: jest.MockedFunction<TodoScreenApi["list"]>;
  create: jest.MockedFunction<TodoScreenApi["create"]>;
  rename: jest.MockedFunction<TodoScreenApi["rename"]>;
  setCompleted: jest.MockedFunction<TodoScreenApi["setCompleted"]>;
  remove: jest.MockedFunction<TodoScreenApi["remove"]>;
};

const todo = (id: string, title: string, completed = false): Todo => ({
  id,
  title,
  completed,
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

const makeApi = (): MockTodoApi => ({
  list: jest.fn() as jest.MockedFunction<TodoScreenApi["list"]>,
  create: jest.fn() as jest.MockedFunction<TodoScreenApi["create"]>,
  rename: jest.fn() as jest.MockedFunction<TodoScreenApi["rename"]>,
  setCompleted: jest.fn() as jest.MockedFunction<TodoScreenApi["setCompleted"]>,
  remove: jest.fn() as jest.MockedFunction<TodoScreenApi["remove"]>,
});

type HostNode = {
  type: string;
  props: Record<string, unknown>;
  children: (HostNode | string)[];
};

const findHost = (
  node: HostNode,
  predicate: (candidate: HostNode) => boolean,
): HostNode | undefined => {
  if (predicate(node)) return node;
  for (const child of node.children) {
    if (typeof child !== "string") {
      const match = findHost(child, predicate);
      if (match) return match;
    }
  }
  return undefined;
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
  clearInterval: (intervalId) => clearInterval(intervalId as unknown as ReturnType<typeof setInterval>),
});

const liveClients: QueryClient[] = [];

const renderScreen = async (api: MockTodoApi, client = createAppQueryClient()) => {
  liveClients.push(client);
  const view = await render(
    <QueryClientProvider client={client}>
      <TodoScreen api={api} />
    </QueryClientProvider>,
  );
  return { view, client };
};

const load = async (api: MockTodoApi, rows: Todo[] = []) => {
  api.list.mockResolvedValueOnce(rows);
  const rendered = await renderScreen(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  return rendered;
};

const unavailable = () => new TodoApiError("unavailable", "Could not load todos.");
const invalidData = () => new TodoApiError("invalid-data", "bad data");

beforeEach(() => {
  mockInputFocus.mockClear();
  mockInputFocusEditable.length = 0;
  mockInputBlur.mockClear();
  mockInputBlurEditable.length = 0;
  mockInputEditable = undefined;
  jest.useRealTimers();
});

afterEach(() => {
  cleanup();
  while (liveClients.length > 0) {
    const client = liveClients.pop() as QueryClient;
    client.unmount();
    client.clear();
  }
});

it("starts with Loading todos… and one GET without permitting writes", async () => {
  const pending = deferred<Todo[]>();
  const api = makeApi();
  api.list.mockReturnValueOnce(pending.promise);

  const { view } = await renderScreen(api);

  expect(screen.getByText("Loading todos…")).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(api.list.mock.calls[0][0].signal).toBeInstanceOf(AbortSignal);
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false);
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  expect(screen.queryByText("No todos yet. Add one above.")).toBeNull();

  await view.unmount();
  await act(async () => pending.resolve([]));
});

it("retries an unavailable GET exactly once after 500 ms before failing", async () => {
  jest.useFakeTimers();
  try {
    const api = makeApi();
    api.list.mockRejectedValue(unavailable());
    await renderScreen(api);
    expect(api.list).toHaveBeenCalledTimes(1);

    await act(async () => {
      await jest.advanceTimersByTimeAsync(600);
    });

    expect(api.list).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load todos.");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(screen.queryByText("No todos yet. Add one above.")).toBeNull();
  } finally {
    jest.useRealTimers();
  }
});

it("does not retry an invalid-data GET", async () => {
  const api = makeApi();
  api.list.mockRejectedValue(invalidData());
  await renderScreen(api);

  await waitFor(() => expect(screen.getByText("Could not load todos.")).toBeTruthy());
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 650));
  });
  expect(api.list).toHaveBeenCalledTimes(1);
});

it("replaces rows after the initial GET and exposes Refresh", async () => {
  const rows = [todo("one", "Buy milk"), todo("two", "Write tests", true)];
  const api = makeApi();

  await load(api, rows);

  expect(api.list).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(screen.getByRole("checkbox", { name: "Write tests" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  );
  expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("reuses a fresh cache on remount without another GET", async () => {
  const api = makeApi();
  api.list.mockResolvedValueOnce([todo("one", "Buy milk")]);
  const { view, client } = await renderScreen(api);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());
  expect(api.list).toHaveBeenCalledTimes(1);

  await view.unmount();
  await renderScreen(api, client);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());
  expect(api.list).toHaveBeenCalledTimes(1);
});

it("refetches an invalidated cache on remount", async () => {
  const api = makeApi();
  const { view, client } = await load(api, [todo("one", "Buy milk")]);

  const refresh = deferred<Todo[]>();
  api.list.mockReturnValueOnce(refresh.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => refresh.reject(invalidData()));
  await waitFor(() => expect(screen.getByText("Could not refresh todos.")).toBeTruthy());

  api.list.mockResolvedValueOnce([todo("one", "Buy milk"), todo("two", "Server row")]);
  await view.unmount();
  await renderScreen(api, client);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Server row" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("keeps an invalidated cache locked across remount until a fresh GET succeeds", async () => {
  const api = makeApi();
  const { view, client } = await load(api, [todo("one", "Buy milk")]);

  api.list.mockRejectedValueOnce(invalidData());
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByText("Could not refresh todos.")).toBeTruthy());
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  const pending = deferred<Todo[]>();
  api.list.mockReturnValueOnce(pending.promise);
  await view.unmount();
  await renderScreen(api, client);

  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  await act(async () => pending.resolve([todo("one", "Buy milk"), todo("two", "Fresh row")]));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Fresh row" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("refreshes with one GET while preserving the draft and selected filter", async () => {
  const next = deferred<Todo[]>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Done", true)]);

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Draft kept across refresh");
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  api.list.mockReturnValueOnce(next.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByText("Refreshing todos…")).toBeTruthy());

  expect(api.list).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: "Completed" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "Draft kept across refresh");
  await act(async () => next.resolve([todo("three", "Server row")]));

  expect(screen.getByRole("button", { name: "Completed" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "Draft kept across refresh");
  await waitFor(() => expect(screen.getByText("No completed todos.")).toBeTruthy());
  expect(screen.queryByText("Server row")).toBeNull();
});

it("preserves rows on failed refresh and disables remote writes until recovery", async () => {
  const refresh = deferred<Todo[]>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  api.list.mockReturnValueOnce(refresh.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => refresh.reject(invalidData()));

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not refresh todos."));
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Refresh" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false);
  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  expect(api.setCompleted).not.toHaveBeenCalled();
});

it("does not start a write during the refresh handoff", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  const refreshing = deferred<Todo[]>();
  api.list.mockReturnValueOnce(refreshing.promise);

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "New todo");
  const refresh = screen.getByRole("button", { name: "Refresh" }).props.onPress as () => void;
  const add = screen.getByRole("button", { name: "Add todo" }).props.onPress as () => void;
  await act(async () => {
    refresh();
    add();
  });

  await waitFor(() => expect(api.list).toHaveBeenCalledTimes(2));
  expect(api.create).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  ));

  await act(async () => refreshing.resolve([todo("one", "Buy milk")]));
  await waitFor(() => expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  ));
});

it("creates pessimistically: unchanged until the response, then one confirming GET while locked", async () => {
  const creating = deferred<Todo>();
  const confirming = deferred<Todo[]>();
  const api = makeApi();
  await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(api.create).toHaveBeenCalledWith("Buy milk");
  expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull();
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  api.list.mockReturnValueOnce(confirming.promise);
  const created = todo("server-id", "Buy milk");
  await act(async () => creating.resolve(created));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());
  expect(api.list).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  await act(async () => confirming.resolve([created]));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false }),
    ),
  );
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "");
});

it("keeps a failed confirming GET visible with refresh copy until recovery", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  api.list.mockRejectedValueOnce(invalidData());
  const created = todo("server-id", "Buy milk");
  await act(async () => creating.resolve(created));

  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());
  expect(screen.getByRole("alert")).toHaveTextContent("Could not refresh todos.");
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  api.list.mockResolvedValueOnce([created]);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false }),
    ),
  );
  expect(screen.queryByRole("alert")).toBeNull();
});

it("completes optimistically with the requested Boolean and rolls back on failure", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Other")]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  expect(api.setCompleted).toHaveBeenCalledWith("one", true);
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  );

  api.list.mockResolvedValueOnce([todo("one", "Buy milk"), todo("two", "Other")]);
  await act(async () => updating.reject(new Error("boom")));

  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ checked: false }),
    ),
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "The result may be unknown. Refresh before making more changes.",
  );
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
});

it("replaces the optimistic row with the server row on completion success", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  api.list.mockResolvedValueOnce([todo("one", "Canonical title", true)]);
  await act(async () => updating.resolve(todo("one", "Canonical title", true)));

  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: "Canonical title" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ checked: true }),
    ),
  );
});

it("renames pessimistically and keeps the editor open on failure", async () => {
  const renaming = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockReturnValueOnce(renaming.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  const editor = screen.getByLabelText("Edit todo title");
  await fireEvent.changeText(editor, "Renamed");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));
  expect(api.rename).toHaveBeenCalledWith("one", "Renamed");
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();

  api.list.mockResolvedValueOnce([todo("one", "Renamed")]);
  await act(async () => renaming.resolve(todo("one", "Renamed")));

  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Renamed" })).toBeTruthy());
  expect(screen.queryByLabelText("Edit todo title")).toBeNull();
});

it("locks on an unknown rename result and unlocks after a fresh GET", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockRejectedValueOnce(new Error("private detail"));

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Renamed");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "The result may be unknown. Refresh before making more changes.",
  );
  expect(screen.queryByText("private detail")).toBeNull();
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Renamed");
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  api.list.mockResolvedValueOnce([todo("one", "Buy milk")]);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false }),
    ),
  );
});

it("rolls back and locks on a rename 404 without an immediate GET", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockRejectedValueOnce(
    new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
  );

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Renamed");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "That todo no longer exists. Refresh the list.",
  );
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(1);
});

it("deletes pessimistically only after confirmation and one confirming GET", async () => {
  const removing = deferred<void>();
  const confirming = deferred<Todo[]>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Other")]);
  api.remove.mockReturnValueOnce(removing.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  expect(screen.getByText("Delete \u201cBuy milk\u201d?")).toBeTruthy();
  expect(api.remove).not.toHaveBeenCalled();
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();

  await fireEvent.press(screen.getByRole("button", { name: "Confirm delete" }));
  expect(api.remove).toHaveBeenCalledWith("one");
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();

  api.list.mockReturnValueOnce(confirming.promise);
  await act(async () => removing.resolve());
  await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull());
  expect(screen.getByRole("checkbox", { name: "Other" })).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(2);

  await act(async () => confirming.resolve([todo("two", "Other")]));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false }),
    ),
  );
});

it("cancels a delete confirmation without a request", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  await fireEvent.press(screen.getByRole("button", { name: "Cancel delete" }));

  expect(api.remove).not.toHaveBeenCalled();
  expect(screen.queryByText("Delete \u201cBuy milk\u201d?")).toBeNull();
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
});

it("keeps the editor open when Cancel edit races a pending save", async () => {
  const renaming = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockReturnValueOnce(renaming.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Renamed");
  const save = screen.getByRole("button", { name: "Save changes" }).props.onPress as () => void;
  const cancel = screen.getByRole("button", { name: "Cancel edit" }).props.onPress as () => void;
  await act(async () => {
    save();
    cancel();
  });

  expect(api.rename).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Renamed");
  expect(screen.getByRole("button", { name: "Cancel edit" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
});

it("keeps the delete confirmation open when Cancel delete races a pending delete", async () => {
  const removing = deferred<void>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.remove.mockReturnValueOnce(removing.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  const confirm = screen.getByRole("button", { name: "Confirm delete" }).props.onPress as () => void;
  const cancel = screen.getByRole("button", { name: "Cancel delete" }).props.onPress as () => void;
  await act(async () => {
    confirm();
    cancel();
  });

  expect(api.remove).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Delete \u201cBuy milk\u201d?")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Cancel delete" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
});

it("maps a delete 404 to safe copy and keeps the row locked", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.remove.mockRejectedValueOnce(
    new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
  );

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  await fireEvent.press(screen.getByRole("button", { name: "Confirm delete" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "That todo no longer exists. Refresh the list.",
  );
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(api.list).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
});

it("shows an unknown create error after remount and unlocks only after a fresh GET", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  const { view, client } = await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Pending row");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await view.unmount();
  await renderScreen(api, client);

  await act(async () => creating.reject(new Error("private detail")));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
    "The result may be unknown. Refresh before making more changes.",
  ));
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  api.list.mockResolvedValueOnce([]);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("shows a delete 404 after remount and unlocks only after a fresh GET", async () => {
  const removing = deferred<void>();
  const api = makeApi();
  const { view, client } = await load(api, [todo("one", "Buy milk")]);
  api.remove.mockReturnValueOnce(removing.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  await fireEvent.press(screen.getByRole("button", { name: "Confirm delete" }));
  await view.unmount();
  await renderScreen(api, client);

  await act(async () => removing.reject(new TodoApiError("not-found", "gone")));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
    "That todo no longer exists. Refresh the list.",
  ));
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  api.list.mockResolvedValueOnce([todo("one", "Buy milk")]);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("blocks a new write after remount during a pending mutation and reconciles on settle", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  const { view, client } = await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Pending row");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(api.create).toHaveBeenCalledTimes(1);

  await view.unmount();
  await renderScreen(api, client);

  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Second attempt");
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(api.create).toHaveBeenCalledTimes(1);

  const created = todo("server-id", "Pending row");
  api.list.mockResolvedValueOnce([created]);
  await act(async () => creating.resolve(created));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Pending row" })).toBeTruthy());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
      "accessibilityState",
      expect.objectContaining({ disabled: false }),
    ),
  );
});

it("gates rapid Add and submit handlers to one create", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "  Buy milk  ");
  const addButton = screen.getByRole("button", { name: "Add todo" });
  const pressAdd = addButton.props.onPress as () => void;
  const submitEditing = input.props.onSubmitEditing as () => void;
  await act(async () => {
    pressAdd();
    submitEditing();
  });

  expect(api.create).toHaveBeenCalledTimes(1);
  expect(api.create.mock.calls[0][0]).toBe("Buy milk");
  expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull();
  await waitFor(() => expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false));
  expect(mockInputBlurEditable).toEqual([true]);
  expect(mockInputFocus).not.toHaveBeenCalled();
  api.list.mockResolvedValueOnce([todo("server-id", "Buy milk")]);
  await act(async () => {
    creating.resolve(todo("server-id", "Buy milk"));
  });
  await waitFor(() => {
    expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
    expect(mockInputFocus).toHaveBeenCalledTimes(1);
  });
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "");
  expect(mockInputFocusEditable).toEqual([true]);
});

it("gates rapid checkbox press and Space handlers to one update", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  const checkbox = screen.getByRole("checkbox", { name: "Buy milk" });
  const pressCheckbox = checkbox.props.onPress as () => void;
  const onKeyDown = checkbox.props.onKeyDown as (event: {
    nativeEvent: { key: string };
    preventDefault: () => void;
  }) => void;
  const preventDefault = jest.fn();
  await act(async () => {
    pressCheckbox();
    onKeyDown({ nativeEvent: { key: " " }, preventDefault });
  });

  expect(preventDefault).toHaveBeenCalled();
  expect(api.setCompleted).toHaveBeenCalledTimes(1);
  api.list.mockResolvedValueOnce([todo("one", "Buy milk", true)]);
  await act(async () => updating.resolve(todo("one", "Buy milk", true)));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  ));
});

it("toggles a focused checkbox with Space and prevents the browser default", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockResolvedValueOnce(todo("one", "Buy milk", true));

  const checkbox = screen.getByRole("checkbox", { name: "Buy milk" });
  const preventDefault = jest.fn();
  api.list.mockResolvedValueOnce([todo("one", "Buy milk", true)]);
  await fireEvent(checkbox, "keyDown", { nativeEvent: { key: " " }, preventDefault });

  expect(preventDefault).toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  ));
});

it("gates rapid Save and Confirm delete handlers to one request each", async () => {
  const renaming = deferred<Todo>();
  const removing = deferred<void>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Other")]);
  api.rename.mockReturnValueOnce(renaming.promise);
  api.remove.mockReturnValueOnce(removing.promise);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Renamed");
  const save = screen.getByRole("button", { name: "Save changes" });
  const pressSave = save.props.onPress as () => void;
  await act(async () => {
    pressSave();
    pressSave();
  });
  expect(api.rename).toHaveBeenCalledTimes(1);

  api.list.mockResolvedValueOnce([todo("one", "Renamed"), todo("two", "Other")]);
  await act(async () => renaming.resolve(todo("one", "Renamed")));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Renamed" })).toBeTruthy());

  await fireEvent.press(screen.getByRole("button", { name: "Delete Other" }));
  const confirm = screen.getByRole("button", { name: "Confirm delete" });
  const pressConfirm = confirm.props.onPress as () => void;
  await act(async () => {
    pressConfirm();
    pressConfirm();
  });
  expect(api.remove).toHaveBeenCalledTimes(1);
  api.list.mockResolvedValueOnce([todo("one", "Renamed")]);
  await act(async () => removing.resolve());
  await waitFor(() => expect(screen.queryByRole("checkbox", { name: "Other" })).toBeNull());
});

it("allows only one open row action at a time", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Other")]);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  expect(screen.getByLabelText("Edit todo title")).toBeTruthy();

  await fireEvent.press(screen.getByRole("button", { name: "Edit Other" }));
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Other");
  expect(screen.getAllByLabelText("Edit todo title")).toHaveLength(1);

  await fireEvent.press(screen.getByRole("button", { name: "Cancel edit" }));
  expect(screen.queryByLabelText("Edit todo title")).toBeNull();

  await fireEvent.press(screen.getByRole("button", { name: "Delete Buy milk" }));
  expect(screen.getByText("Delete \u201cBuy milk\u201d?")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Edit Other" }));
  expect(screen.queryByText("Delete \u201cBuy milk\u201d?")).toBeNull();
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Other");
});

it("cancels an edit without a request and restores the row", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Changed mind");
  await fireEvent.press(screen.getByRole("button", { name: "Cancel edit" }));

  expect(api.rename).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Edit todo title")).toBeNull();
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
});

it("validates rename input locally including NUL without a request", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Bad\u0000title");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));

  expect(api.rename).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("Check the todo title and try again.");
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Bad\u0000title");
});

it("maps rename validation to exact copy and keeps the editor writable", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockRejectedValueOnce(
    new TodoApiError("validation", "Check the todo title and try again."),
  );

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Bad server title");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Check the todo title and try again.");
  expect(screen.getByLabelText("Edit todo title")).toHaveProp("value", "Bad server title");
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: false }),
  );
});

it("does not let an old rename validation mask a failed confirming GET", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockRejectedValueOnce(new TodoApiError("validation", "bad title"));

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Bad title");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
    "Check the todo title and try again.",
  ));
  await fireEvent.press(screen.getByRole("button", { name: "Cancel edit" }));

  api.create.mockResolvedValueOnce(todo("two", "Valid title"));
  api.list.mockRejectedValueOnce(invalidData());
  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Valid title");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));

  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Could not refresh todos."));
});

it("does not let an old rename validation mask a local blank-title error", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.rename.mockRejectedValueOnce(new TodoApiError("validation", "bad title"));

  await fireEvent.press(screen.getByRole("button", { name: "Edit Buy milk" }));
  await fireEvent.changeText(screen.getByLabelText("Edit todo title"), "Bad title");
  await fireEvent.press(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
    "Check the todo title and try again.",
  ));
  await fireEvent.press(screen.getByRole("button", { name: "Cancel edit" }));

  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");
});

it("maps create validation to the exact alert and keeps the draft writable", async () => {
  const api = makeApi();
  await load(api);
  api.create.mockRejectedValueOnce(
    new TodoApiError("validation", "Check the todo title and try again."),
  );

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Bad server title");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Check the todo title and try again.");
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "Bad server title");
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", true);
  expect(screen.queryByRole("checkbox", { name: "Bad server title" })).toBeNull();
});

it("validates create input locally with ECMAScript trimming and code-point limits", async () => {
  const api = makeApi();
  await load(api);
  const input = screen.getByLabelText("Todo title");

  await fireEvent.changeText(input, "\u2003\uFEFF");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");

  await fireEvent.changeText(input, "under limit\uD83D");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Todo titles must be 120 characters or fewer.",
  );

  await fireEvent.changeText(input, "\u{1F600}".repeat(120));
  api.create.mockResolvedValueOnce(todo("emoji", "\u{1F600}".repeat(120)));
  api.list.mockResolvedValueOnce([todo("emoji", "\u{1F600}".repeat(120))]);
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(api.create).toHaveBeenCalledWith("\u{1F600}".repeat(120));
});

it("keeps filters usable during a cached error and filters locally while busy", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Done", true)]);

  api.list.mockRejectedValueOnce(invalidData());
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() => expect(screen.getByText("Could not refresh todos.")).toBeTruthy());

  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getByRole("checkbox", { name: "Done" })).toBeTruthy();
  expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull();
  expect(screen.getByText("Could not refresh todos.")).toBeTruthy();

  await fireEvent.press(screen.getByRole("button", { name: "All" }));
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
});

it("renders sibling row controls with checkbox semantics and target sizes", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp("aria-checked", false);
  expect(screen.getByRole("button", { name: "Edit Buy milk" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Delete Buy milk" })).toBeTruthy();

  const root = screen.root as unknown as HostNode;
  const checkboxNode = findHost(
    root,
    (node) => node.props.accessibilityRole === "checkbox",
  );
  if (!checkboxNode) throw new Error("checkbox host was not rendered");
  const nestedButton = findHost(
    checkboxNode,
    (node) => node !== checkboxNode && node.props.accessibilityRole === "button",
  );
  expect(nestedButton).toBeUndefined();

  const input = screen.getByLabelText("Todo title");
  const addButton = screen.getByRole("button", { name: "Add todo" });
  const refreshButton = screen.getByRole("button", { name: "Refresh" });
  const checkbox = screen.getByRole("checkbox", { name: "Buy milk" });
  const editButton = screen.getByRole("button", { name: "Edit Buy milk" });
  const deleteButton = screen.getByRole("button", { name: "Delete Buy milk" });
  expect(StyleSheet.flatten(input.props.style).minHeight).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(addButton.props.style).minHeight).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(refreshButton.props.style).minHeight).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(checkbox.props.style).minHeight).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(checkbox.props.style).minWidth).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(editButton.props.style).minHeight).toBeGreaterThanOrEqual(44);
  expect(StyleSheet.flatten(deleteButton.props.style).minHeight).toBeGreaterThanOrEqual(44);
});

it("preserves containers, keyboard props, duplicates, filters, and empty states", async () => {
  const api = makeApi();
  await load(api);
  const root = screen.root as unknown as HostNode;
  expect(root.type).toBe("RCTSafeAreaView");
  const scrollView = findHost(
    root,
    (node) => node.props.automaticallyAdjustKeyboardInsets === true,
  );
  if (!scrollView) throw new Error("ScrollView host was not rendered");
  expect(scrollView.props.keyboardShouldPersistTaps).toBe("handled");

  expect(screen.getByText("No todos yet. Add one above.")).toBeTruthy();
  const input = screen.getByLabelText("Todo title");
  api.create.mockResolvedValueOnce(todo("one", "Buy milk"));
  api.list.mockResolvedValueOnce([todo("one", "Buy milk")]);
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());

  api.create.mockResolvedValueOnce(todo("two", "Buy milk"));
  api.list.mockResolvedValueOnce([todo("one", "Buy milk"), todo("two", "Buy milk")]);
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await waitFor(() => expect(screen.getAllByRole("checkbox", { name: "Buy milk" })).toHaveLength(2));

  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getByText("No completed todos.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Active" }));
  expect(screen.getAllByRole("checkbox", { name: "Buy milk" })).toHaveLength(2);
  expect(screen.queryByText("No active todos.")).toBeNull();
  await fireEvent.press(screen.getByRole("button", { name: "All" }));
  expect(screen.getByRole("button", { name: "All" })).toHaveProp("aria-pressed", true);
});

it("resets local UI state on remount while loading the server again", async () => {
  const api = makeApi();
  api.list.mockResolvedValueOnce([]);
  const { view } = await renderScreen(api);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  await fireEvent.changeText(screen.getByLabelText("Todo title"), "Local draft");
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));

  await view.unmount();
  api.list.mockResolvedValueOnce([todo("one", "Server row", true)]);
  const second = await renderScreen(api);
  await waitFor(() => expect(second.view).toBeTruthy());
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Server row" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "All" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "");
});

it("aborts the list request on unmount", async () => {
  const pending = deferred<Todo[]>();
  const api = makeApi();
  api.list.mockReturnValueOnce(pending.promise);

  const { view } = await renderScreen(api);
  const signal = api.list.mock.calls[0][0].signal as AbortSignal;
  await view.unmount();
  expect(signal.aborted).toBe(true);

  await act(async () => pending.resolve([todo("late", "Late row")]));
  expect(api.list).toHaveBeenCalledTimes(1);
});

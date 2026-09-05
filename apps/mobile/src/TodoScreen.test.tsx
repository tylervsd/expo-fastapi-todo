import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { TodoApiError, type Todo } from "./todos/todoApi";
import { TodoScreen, type TodoScreenApi } from "./TodoScreen";

type MockTodoApi = {
  list: jest.MockedFunction<TodoScreenApi["list"]>;
  create: jest.MockedFunction<TodoScreenApi["create"]>;
  setCompleted: jest.MockedFunction<TodoScreenApi["setCompleted"]>;
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
  setCompleted: jest.fn() as jest.MockedFunction<TodoScreenApi["setCompleted"]>,
});

const load = async (api: MockTodoApi, rows: Todo[] = []) => {
  api.list.mockResolvedValueOnce(rows);
  await render(<TodoScreen api={api} />);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
};

it("starts with Loading todos… and one GET without permitting writes", async () => {
  const pending = deferred<Todo[]>();
  const api = makeApi();
  api.list.mockReturnValueOnce(pending.promise);

  const view = await render(<TodoScreen api={api} />);

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

it("shows initial load failure with Retry and no empty-list copy", async () => {
  const first = deferred<Todo[]>();
  const retry = deferred<Todo[]>();
  const api = makeApi();
  api.list.mockReturnValueOnce(first.promise).mockReturnValueOnce(retry.promise);

  await render(<TodoScreen api={api} />);
  await act(async () => first.reject(new TodoApiError("unavailable", "Could not load todos.")));

  expect(screen.getByRole("alert")).toHaveTextContent("Could not load todos.");
  expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  expect(screen.queryByText("No todos yet. Add one above.")).toBeNull();
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false);

  await fireEvent.press(screen.getByRole("button", { name: "Retry" }));
  expect(api.list).toHaveBeenCalledTimes(2);
  await act(async () => retry.resolve([todo("one", "Recovered")]));
  expect(screen.getByRole("checkbox", { name: "Recovered" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
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
  expect(screen.getByText("No completed todos.")).toBeTruthy();
  expect(screen.queryByText("Server row")).toBeNull();
});

it("preserves rows on failed refresh and disables remote writes until recovery", async () => {
  const refresh = deferred<Todo[]>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);

  api.list.mockReturnValueOnce(refresh.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => refresh.reject(new TodoApiError("unavailable", "Could not load todos.")));

  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy();
  expect(screen.getByRole("alert")).toHaveTextContent("Could not refresh todos.");
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

it("accepts one create before rerender, sends the title, and appends canonical data only on success", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "  Buy milk  ");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await fireEvent(input, "submitEditing");

  expect(api.create).toHaveBeenCalledTimes(1);
  expect(api.create.mock.calls[0][0]).toBe("Buy milk");
  expect(api.create.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull();
  await waitFor(() => expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false));
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "  Buy milk  ");
  await act(async () => {
    creating.resolve(todo("server-id", "Canonical Buy milk", true));
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Canonical Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  ));
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "");
});

it("disables the draft while create is pending and clears it after success", async () => {
  const creating = deferred<Todo>();
  const api = makeApi();
  await load(api);
  api.create.mockReturnValueOnce(creating.promise);

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "First");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await waitFor(() => expect(input).toHaveProp("editable", false));
  await act(async () => creating.resolve(todo("server-id", "First")));

  await waitFor(() => expect(screen.getByRole("checkbox", { name: "First" })).toBeTruthy());
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "");
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

it("uses ECMAScript trimming, Unicode code-point limits, and rejects lone surrogates locally", async () => {
  const api = makeApi();
  await load(api);
  const input = screen.getByLabelText("Todo title");

  await fireEvent.changeText(input, "\u2003\uFEFF");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");

  await fireEvent.changeText(input, `${"😀".repeat(120)}\uD83D`);
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Todo titles must be 120 characters or fewer.",
  );

  await fireEvent.changeText(input, "😀".repeat(120));
  api.create.mockResolvedValueOnce(todo("emoji", "😀".repeat(120)));
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(api.create).toHaveBeenCalledWith("😀".repeat(120), expect.anything());
});

it("sends the desired Boolean and replaces a row only after canonical PATCH success", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  expect(api.setCompleted).toHaveBeenCalledWith("one", true, expect.anything());
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: false }),
  );

  await act(async () => updating.resolve(todo("one", "Canonical title", true)));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Canonical title" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  ));
});

it("gates rapid checkbox and Space events to one PATCH", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  const checkbox = screen.getByRole("checkbox", { name: "Buy milk" });
  await fireEvent.press(checkbox);
  await fireEvent.press(checkbox);

  expect(api.setCompleted).toHaveBeenCalledTimes(1);
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
  await fireEvent(checkbox, "keyDown", { nativeEvent: { key: " " }, preventDefault });

  expect(preventDefault).toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  ));
});

it("maps a missing PATCH target without changing the row", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockRejectedValueOnce(
    new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
  );

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "That todo no longer exists. Refresh the list.",
  );
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: false }),
  );
});

it("locks writes after an unknown create result until a successful Refresh", async () => {
  const refresh = deferred<Todo[]>();
  const api = makeApi();
  await load(api, [todo("one", "Existing")]);
  api.create.mockRejectedValueOnce(new Error("private transport detail"));

  const input = screen.getByLabelText("Todo title");
  await fireEvent.changeText(input, "Maybe created");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "The result may be unknown. Refresh before making more changes.",
  );
  expect(screen.queryByText("private transport detail")).toBeNull();
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "Maybe created");
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", false);
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  await fireEvent.press(screen.getByRole("checkbox", { name: "Existing" }));
  expect(api.setCompleted).not.toHaveBeenCalled();

  api.list.mockReturnValueOnce(refresh.promise);
  await fireEvent.press(screen.getByRole("button", { name: "Refresh" }));
  await act(async () => refresh.resolve([todo("one", "Existing"), todo("server", "Maybe created")]));

  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Maybe created" })).toBeTruthy());
  expect(screen.getByLabelText("Todo title")).toHaveProp("value", "Maybe created");
  expect(screen.getByLabelText("Todo title")).toHaveProp("editable", true);
});

it("locks writes after an unknown update result and preserves the displayed row", async () => {
  const api = makeApi();
  await load(api, [todo("one", "Buy milk")]);
  api.setCompleted.mockRejectedValueOnce(new Error("private update detail"));

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));

  expect(screen.getByRole("alert")).toHaveTextContent(
    "The result may be unknown. Refresh before making more changes.",
  );
  expect(screen.getByRole("checkbox", { name: "Buy milk" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: false }),
  );
  expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
});

it("derives filters locally while a remote action is busy", async () => {
  const updating = deferred<Todo>();
  const api = makeApi();
  await load(api, [todo("one", "Buy milk"), todo("two", "Done", true)]);
  api.setCompleted.mockReturnValueOnce(updating.promise);

  await fireEvent.press(screen.getByRole("checkbox", { name: "Buy milk" }));
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));

  expect(screen.getByRole("button", { name: "Completed" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
  expect(screen.getByRole("checkbox", { name: "Done" })).toBeTruthy();
  expect(screen.queryByRole("checkbox", { name: "Buy milk" })).toBeNull();
  expect(screen.getByRole("button", { name: "Refresh" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );
  expect(screen.getByRole("button", { name: "Add todo" })).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ disabled: true }),
  );

  await act(async () => updating.resolve(todo("one", "Buy milk", true)));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Buy milk" })).toBeTruthy());
});

it("retains Phase 2 validation, duplicate rows, filters, accessibility, and empty states", async () => {
  const api = makeApi();
  await load(api);
  const input = screen.getByLabelText("Todo title");
  const first = deferred<Todo>();
  const second = deferred<Todo>();
  api.create.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

  await fireEvent.changeText(input, "   ");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a todo title.");

  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await act(async () => first.resolve(todo("one", "Buy milk")));
  await fireEvent.changeText(input, "Buy milk");
  await fireEvent.press(screen.getByRole("button", { name: "Add todo" }));
  await act(async () => second.resolve(todo("two", "Buy milk")));

  expect(screen.getAllByRole("checkbox", { name: "Buy milk" })).toHaveLength(2);
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getByText("No completed todos.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "All" }));
  api.setCompleted
    .mockResolvedValueOnce(todo("one", "Buy milk", true))
    .mockResolvedValueOnce(todo("two", "Buy milk", true));
  await fireEvent.press(screen.getAllByRole("checkbox", { name: "Buy milk" })[0]);
  await fireEvent.press(screen.getAllByRole("checkbox", { name: "Buy milk" })[1]);
  expect(screen.getByRole("button", { name: "All" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
  expect(screen.getByRole("button", { name: "All" })).toHaveProp("aria-pressed", true);
  await fireEvent.press(screen.getByRole("button", { name: "Active" }));
  expect(screen.getByRole("button", { name: "Active" })).toHaveProp("aria-pressed", true);
  expect(screen.getByText("No active todos.")).toBeTruthy();
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));
  expect(screen.getAllByRole("checkbox", { name: "Buy milk" })[0]).toHaveProp(
    "accessibilityState",
    expect.objectContaining({ checked: true }),
  );
});

it("resets the filter to All on remount while loading the server again", async () => {
  const api = makeApi();
  api.list.mockResolvedValueOnce([]);
  const view = await render(<TodoScreen api={api} />);
  await waitFor(() => expect(screen.queryByText("Loading todos…")).toBeNull());
  await fireEvent.press(screen.getByRole("button", { name: "Completed" }));

  await view.unmount();
  api.list.mockResolvedValueOnce([todo("one", "Server row", true)]);
  await render(<TodoScreen api={api} />);
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "Server row" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "All" })).toHaveProp(
    "accessibilityState",
    { selected: true },
  );
});

it("aborts on unmount and suppresses stale completion", async () => {
  const pending = deferred<Todo[]>();
  const api = makeApi();
  api.list.mockReturnValueOnce(pending.promise);

  const view = await render(<TodoScreen api={api} />);
  const signal = api.list.mock.calls[0][0].signal;
  await view.unmount();
  expect(signal.aborted).toBe(true);

  await act(async () => pending.resolve([todo("late", "Late row")]));
  expect(api.list).toHaveBeenCalledTimes(1);
});

it("suppresses stale load errors after a newer accepted load", async () => {
  const first = deferred<Todo[]>();
  const second = deferred<Todo[]>();
  const firstApi = makeApi();
  const secondApi = makeApi();
  firstApi.list.mockReturnValueOnce(first.promise);
  secondApi.list.mockReturnValueOnce(second.promise);

  const view = await render(<TodoScreen api={firstApi} />);
  const oldSignal = firstApi.list.mock.calls[0][0].signal;
  await view.rerender(<TodoScreen api={secondApi} />);
  expect(oldSignal.aborted).toBe(true);
  await act(async () => second.resolve([todo("current", "Current row")]));
  await act(async () => first.reject(new Error("stale failure")));

  expect(screen.getByRole("checkbox", { name: "Current row" })).toBeTruthy();
  expect(screen.queryByText("stale failure")).toBeNull();
});

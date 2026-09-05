import {
  createTodo,
  listTodos,
  setTodoCompleted,
  TodoApiError,
} from "./todoApi";

const apiUrl = "http://127.0.0.1:8000";
const todo = {
  id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72",
  title: "Buy milk",
  completed: false,
};

const response = (status: number, body: unknown) =>
  ({ status, json: jest.fn().mockResolvedValue(body) }) as unknown as Response;

describe("todo API client", () => {
  it("lists exact todo payloads with the configured URL", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, [todo]));

    await expect(listTodos({ apiUrl, fetchImpl })).resolves.toEqual([todo]);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos`, {
      method: "GET",
      signal: expect.any(AbortSignal),
    });
  });

  it("creates a todo with a JSON request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(201, todo));

    await expect(createTodo("Buy milk", { apiUrl, fetchImpl })).resolves.toEqual(todo);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Buy milk" }),
      signal: expect.any(AbortSignal),
    });
  });

  it("updates only completion with a JSON PATCH request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, { ...todo, completed: true }));

    await expect(setTodoCompleted(todo.id, true, { apiUrl, fetchImpl })).resolves.toEqual({
      ...todo,
      completed: true,
    });
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos/${todo.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed: true }),
      signal: expect.any(AbortSignal),
    });
  });

  it.each([
    ["list", () => listTodos({ apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(201, [todo])) })],
    ["create", () => createTodo("Buy milk", { apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(200, todo)) })],
    ["update", () => setTodoCompleted(todo.id, true, { apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(201, todo)) })],
  ])("rejects a wrong success status for %s as unavailable", async (_operation, run) => {
    const pending = run();
    await expect(pending).rejects.toMatchObject({ kind: "unavailable" });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("Buy milk") });
  });

  it("maps validation responses to safe validation copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(422, { detail: "server details" }));

    await expect(createTodo("", { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("validation", "Check the todo title and try again."),
    );
  });

  it("maps a PATCH validation response to the same safe validation copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(422, { detail: "server details" }));

    await expect(setTodoCompleted(todo.id, true, { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("validation", "Check the todo title and try again."),
    );
  });

  it("maps a missing PATCH target to safe not-found copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(404, { detail: "Todo not found." }));

    await expect(setTodoCompleted(todo.id, true, { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
    );
  });

  it("rejects a non-HTTP API URL without starting transport", async () => {
    const fetchImpl = jest.fn();

    await expect(listTodos({ apiUrl: "ftp://127.0.0.1:8000", fetchImpl })).rejects.toMatchObject({
      kind: "unavailable",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ["list", () => listTodos({ apiUrl, fetchImpl: jest.fn().mockRejectedValue(new Error("secret transport")) })],
    ["create", () => createTodo("Buy milk", { apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(503, { detail: "secret server" })) })],
    ["update", () => setTodoCompleted(todo.id, true, { apiUrl, fetchImpl: jest.fn().mockRejectedValue(new Error("secret transport")) })],
  ])("maps %s transport/status failures to safe unavailable copy", async (_operation, run) => {
    const pending = run();
    await expect(pending).rejects.toMatchObject({ kind: "unavailable" });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("secret") });
  });

  it.each([
    ["list", () => listTodos({ apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(200, [{ ...todo, extra: true }])) })],
    ["create", () => createTodo("Buy milk", { apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(201, { ...todo, completed: "no" })) })],
    ["update", () => setTodoCompleted(todo.id, true, { apiUrl, fetchImpl: jest.fn().mockResolvedValue(response(200, { ...todo, id: "not-a-uuid" })) })],
  ])("maps %s malformed success data to safe invalid-data copy", async (_operation, run) => {
    const pending = run();
    await expect(pending).rejects.toMatchObject({ kind: "invalid-data" });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("not-a-uuid") });
  });

  it.each([
    ["array", [todo, { ...todo, title: "  padded  " }]],
    ["extra todo key", [{ ...todo, extra: true }]],
    ["wrong todo key type", [{ ...todo, completed: 0 }]],
    ["invalid UUID", [{ ...todo, id: "not-a-uuid" }]],
    ["non-canonical title", [{ ...todo, title: " Buy milk" }]],
    ["empty title", [{ ...todo, title: "" }]],
    ["too many code points", [{ ...todo, title: "😀".repeat(121) }]],
  ])("rejects %s list data as invalid-data", async (_case, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(listTodos({ apiUrl, fetchImpl })).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it("rejects invalid JSON as invalid-data without exposing parser text", async () => {
    const fetchImpl = jest.fn().mockResolvedValue({
      status: 200,
      json: jest.fn().mockRejectedValue(new SyntaxError("secret parser details")),
    } as unknown as Response);

    await expect(listTodos({ apiUrl, fetchImpl })).rejects.toMatchObject({ kind: "invalid-data" });
    await expect(listTodos({ apiUrl, fetchImpl })).rejects.not.toMatchObject({
      message: expect.stringContaining("secret"),
    });
  });

  it("times out body parsing after five seconds and aborts transport", async () => {
    jest.useFakeTimers();
    try {
      const json = jest.fn(() => new Promise<never>(() => undefined));
      const fetchImpl = jest.fn().mockResolvedValue({ status: 200, json } as unknown as Response);
      const pending = listTodos({ apiUrl, fetchImpl });
      const rejection = expect(pending).rejects.toMatchObject({ kind: "unavailable" });

      await jest.advanceTimersByTimeAsync(5_000);
      await rejection;
      expect((fetchImpl.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
      expect(json).toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });

  it("relays caller cancellation as AbortError even when fetch ignores abort", async () => {
    const controller = new AbortController();
    const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
    const pending = listTodos({ apiUrl, signal: controller.signal, fetchImpl });

    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await expect(pending).rejects.not.toBeInstanceOf(TodoApiError);
  });

  it("does not start transport for an already cancelled caller", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = jest.fn();

    await expect(listTodos({ apiUrl, signal: controller.signal, fetchImpl })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it.each([
    ["success", response(200, [todo]), true],
    ["status", response(503, {}), false],
    ["invalid JSON", { status: 200, json: jest.fn().mockRejectedValue(new SyntaxError()) } as unknown as Response, false],
  ])("removes listeners and timers after %s", async (_case, result, succeeds) => {
    jest.useFakeTimers();
    try {
      const controller = new AbortController();
      const removed = jest.spyOn(controller.signal, "removeEventListener");
      const fetchImpl = jest.fn().mockResolvedValue(result);
      const pending = listTodos({ apiUrl, signal: controller.signal, fetchImpl });
      if (succeeds) await expect(pending).resolves.toEqual([todo]);
      else await expect(pending).rejects.toBeDefined();
      expect(jest.getTimerCount()).toBe(0);
      expect(removed).toHaveBeenCalledWith("abort", expect.any(Function));
    } finally {
      jest.useRealTimers();
    }
  });

  it("removes the caller listener after success", async () => {
    const controller = new AbortController();
    const removed = jest.spyOn(controller.signal, "removeEventListener");
    const fetchImpl = jest.fn().mockResolvedValue(response(200, [todo]));

    await expect(listTodos({ apiUrl, signal: controller.signal, fetchImpl })).resolves.toEqual([todo]);
    expect(removed).toHaveBeenCalledWith("abort", expect.any(Function));
  });
});

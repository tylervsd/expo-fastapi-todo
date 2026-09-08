import {
  advanceTodoWorkflow,
  createTodo,
  deleteTodo,
  fetchMe,
  getTodoWorkflow,
  listTodos,
  login,
  logout,
  normalizeTodoTitle,
  setTodoCompleted,
  setTodoTitle,
  signup,
  startTodoWorkflow,
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
    ["NUL title", [{ ...todo, title: "Buy\u0000milk" }]],
    ["too many code points", [{ ...todo, title: "😀".repeat(121) }]],
    ["trailing high surrogate", [{ ...todo, title: `Buy milk${String.fromCharCode(0xd800)}` }]],
    ["lone low surrogate", [{ ...todo, title: `Buy milk${String.fromCharCode(0xdc00)}` }]],
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
    ["success", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn().mockResolvedValue(response(200, [todo])),
    }), "success"],
    ["status", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn().mockResolvedValue(response(503, {})),
    }), "failure"],
    ["invalid JSON", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn().mockResolvedValue({
        status: 200,
        json: jest.fn().mockRejectedValue(new SyntaxError()),
      } as unknown as Response),
    }), "failure"],
    ["timeout", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn().mockResolvedValue({
        status: 200,
        json: jest.fn(() => new Promise<never>(() => undefined)),
      } as unknown as Response),
    }), "timeout"],
    ["caller abort", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn(() => new Promise<Response>(() => undefined)),
    }), "abort"],
    ["transport rejection", (controller: AbortController) => listTodos({
      apiUrl,
      signal: controller.signal,
      fetchImpl: jest.fn().mockRejectedValue(new Error("offline")),
    }), "failure"],
    ["invalid URL", (controller: AbortController) => listTodos({
      apiUrl: "ftp://127.0.0.1:8000",
      signal: controller.signal,
      fetchImpl: jest.fn(),
    }), "failure"],
    ["already aborted", (controller: AbortController) => {
      controller.abort();
      return listTodos({ apiUrl, signal: controller.signal, fetchImpl: jest.fn() });
    }, "failure"],
  ])("removes listeners and timers after %s", async (_case, run, mode) => {
    jest.useFakeTimers();
    try {
      const controller = new AbortController();
      const removed = jest.spyOn(controller.signal, "removeEventListener");
      const pending = run(controller);
      const timeoutRejection = mode === "timeout" ? expect(pending).rejects.toBeDefined() : undefined;
      if (mode === "timeout") await jest.advanceTimersByTimeAsync(5_000);
      if (mode === "abort") controller.abort();
      if (mode === "success") await expect(pending).resolves.toEqual([todo]);
      else if (timeoutRejection) await timeoutRejection;
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

describe("CRUD extensions", () => {
  it("normalizes canonical titles and rejects invalid input", async () => {
    expect(normalizeTodoTitle("Buy milk")).toBe("Buy milk");
    expect(normalizeTodoTitle("  Buy milk  ")).toBe("Buy milk");
    expect(normalizeTodoTitle("")).toBeNull();
    expect(normalizeTodoTitle("   ")).toBeNull();
    expect(normalizeTodoTitle("Buy\u0000milk")).toBeNull();
    expect(normalizeTodoTitle("\u{1F600}".repeat(121))).toBeNull();
    expect(normalizeTodoTitle(`Buy milk${String.fromCharCode(0xd800)}`)).toBeNull();
    expect(normalizeTodoTitle(`Buy milk${String.fromCharCode(0xdc00)}`)).toBeNull();
  });

  it("renames a todo with an exact PATCH title request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, todo));

    await expect(setTodoTitle(todo.id, "Renamed", { apiUrl, fetchImpl })).resolves.toEqual(todo);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos/${todo.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Renamed" }),
      signal: expect.any(AbortSignal),
    });
  });

  it("maps rename 404 to safe not-found copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(404, { detail: "Todo not found." }));

    await expect(setTodoTitle(todo.id, "Renamed", { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
    );
  });

  it("deletes with no body and accepts empty 204 without parsing", async () => {
    const json = jest.fn();
    const fetchImpl = jest.fn().mockResolvedValue({ status: 204, json } as unknown as Response);

    await expect(deleteTodo(todo.id, { apiUrl, fetchImpl })).resolves.toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos/${todo.id}`, {
      method: "DELETE",
      signal: expect.any(AbortSignal),
    });
    expect(json).not.toHaveBeenCalled();
  });

  it("maps delete 404 to safe not-found copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(404, { detail: "Todo not found." }));

    await expect(deleteTodo(todo.id, { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("not-found", "That todo no longer exists. Refresh the list."),
    );
  });

  it.each([
    ["status", response(503, { detail: "secret server" })],
    ["wrong status", response(200, {})],
  ])("maps delete %s failures to exact delete unavailable copy", async (_case, resp) => {
    const fetchImpl = jest.fn().mockResolvedValue(resp);

    await expect(deleteTodo(todo.id, { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("unavailable", "Could not delete todo."),
    );
  });

  it("maps delete transport rejection to exact delete unavailable copy", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("secret transport"));

    const pending = deleteTodo(todo.id, { apiUrl, fetchImpl });
    await expect(pending).rejects.toEqual(
      new TodoApiError("unavailable", "Could not delete todo."),
    );
  });
});

describe("auth transport", () => {
  const user = { id: "6fc33b84-16a8-4d8e-ae94-fc50bb457d72", username: "alice" };
  const session = { token: "tok-1", expires_at: "2026-10-07T00:00:00+00:00", user };

  it("signs up with an exact POST JSON request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(201, user));

    await expect(signup("alice", "long-enough-password", { apiUrl, fetchImpl })).resolves.toEqual(user);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "alice", password: "long-enough-password" }),
      signal: expect.any(AbortSignal),
    });
  });

  it("maps duplicate signup to the account validation copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(422, { detail: "Username is taken." }));

    await expect(signup("alice", "long-enough-password", { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("validation", "Check the username and password and try again."),
    );
  });

  it("logs in with an exact POST JSON request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, session));

    await expect(login("alice", "long-enough-password", { apiUrl, fetchImpl })).resolves.toEqual(session);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "alice", password: "long-enough-password" }),
      signal: expect.any(AbortSignal),
    });
  });

  it("maps bad credentials to auth-required with the server-safe copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(401, { detail: "Invalid username or password." }));

    await expect(login("alice", "wrong-password-ok", { apiUrl, fetchImpl })).rejects.toEqual(
      new TodoApiError("auth-required", "Invalid username or password."),
    );
  });

  it("logs out with the bearer header, no body, and no JSON parse", async () => {
    const json = jest.fn();
    const fetchImpl = jest.fn().mockResolvedValue({ status: 204, json } as unknown as Response);

    await expect(logout({ apiUrl, token: "tok-1", fetchImpl })).resolves.toBeUndefined();
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/auth/logout`, {
      method: "POST",
      headers: { Authorization: "Bearer tok-1" },
      signal: expect.any(AbortSignal),
    });
    expect(json).not.toHaveBeenCalled();
  });

  it("fetches the session user with the bearer header", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, user));

    await expect(fetchMe({ apiUrl, token: "tok-1", fetchImpl })).resolves.toEqual(user);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/auth/me`, {
      method: "GET",
      headers: { Authorization: "Bearer tok-1" },
      signal: expect.any(AbortSignal),
    });
  });

  it("maps a revoked session to auth-required restore copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(401, { detail: "Not authenticated." }));

    await expect(fetchMe({ apiUrl, token: "tok-1", fetchImpl })).rejects.toEqual(
      new TodoApiError("auth-required", "Please sign in again."),
    );
  });

  it("maps a todo 401 with a bad token to auth-required", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(401, { detail: "Not authenticated." }));

    await expect(listTodos({ apiUrl, token: "bogus", fetchImpl })).rejects.toEqual(
      new TodoApiError("auth-required", "Please sign in again."),
    );
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todos`, {
      method: "GET",
      headers: { Authorization: "Bearer bogus" },
      signal: expect.any(AbortSignal),
    });
  });

  it("maps malformed session JSON to invalid-data without leaking", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, { ...session, token: "" }));

    const pending = login("alice", "long-enough-password", { apiUrl, fetchImpl });
    await expect(pending).rejects.toMatchObject({ kind: "invalid-data" });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("tok-1") });
  });
});

describe("todo workflow transport", () => {
  const workflowId = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
  const assessView = {
    type: "yes_no" as const,
    step_id: `${workflowId}:ASSESS_TASK`,
    title: "Plan birthday party",
    question: "Does this task involve multiple steps?",
    actions: [
      { id: "yes" as const, label: "Yes" },
      { id: "no" as const, label: "No" },
    ],
  };
  const assessWorkflow = {
    workflow_id: workflowId,
    state: "ASSESS_TASK",
    title: "Plan birthday party",
    context: { involves_multiple_steps: null, proposed_todo_titles: [] },
    result: null,
    view: assessView,
  };
  const completedWorkflow = {
    workflow_id: workflowId,
    state: "COMPLETED",
    title: "Plan birthday party",
    context: {
      involves_multiple_steps: false,
      proposed_todo_titles: ["Plan birthday party"],
    },
    result: {
      created_todos: [
        { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Plan birthday party", completed: false },
      ],
    },
    view: {
      type: "completion" as const,
      step_id: `${workflowId}:COMPLETED`,
      title: "Plan complete",
      outcome: "completed" as const,
      created_todos: [
        { id: "81b3c4d5-16a8-4d8e-ae94-fc50bb457d72", title: "Plan birthday party", completed: false },
      ],
    },
  };
  it("starts a workflow with an exact POST request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(201, assessWorkflow));

    await expect(
      startTodoWorkflow("Plan birthday party", { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(assessWorkflow);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer tok" },
      body: JSON.stringify({ title: "Plan birthday party" }),
      signal: expect.any(AbortSignal),
    });
  });

  it("fetches a workflow snapshot with an exact GET request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, assessWorkflow));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(assessWorkflow);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows/${workflowId}`, {
      method: "GET",
      headers: { Authorization: "Bearer tok" },
      signal: expect.any(AbortSignal),
    });
  });

  it.each([
    [
      "task breakdown",
      {
        ...assessWorkflow,
        state: "COLLECT_TASKS",
        context: { involves_multiple_steps: true, proposed_todo_titles: [] },
        view: {
          type: "task_breakdown" as const,
          step_id: `${workflowId}:COLLECT_TASKS`,
          title: "Break it down",
          min_titles: 2,
          max_titles: 10,
        },
      },
    ],
    [
      "review",
      {
        ...assessWorkflow,
        state: "REVIEW",
        context: { involves_multiple_steps: false, proposed_todo_titles: ["Plan birthday party"] },
        view: {
          type: "review" as const,
          step_id: `${workflowId}:REVIEW`,
          title: "Review the plan",
          proposed_titles: ["Plan birthday party"],
        },
      },
    ],
  ])("accepts a valid %s workflow view", async (_name, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(body);
  });

  it("advances with exact action bodies", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, completedWorkflow));

    await expect(
      advanceTodoWorkflow(workflowId, { action: "confirm" }, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(completedWorkflow);
    expect(fetchImpl).toHaveBeenCalledWith(
      `${apiUrl}/todo-workflows/${workflowId}/actions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer tok" },
        body: JSON.stringify({ action: "confirm" }),
        signal: expect.any(AbortSignal),
      }
    );
  });

  it("relays caller cancellation on workflow GET", async () => {
    const controller = new AbortController();
    const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
    const pending = getTodoWorkflow(workflowId, {
      apiUrl,
      token: "tok",
      signal: controller.signal,
      fetchImpl,
    });

    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it.each([
    ["extra key", { ...assessWorkflow, extra: true }],
    ["missing key", { workflow_id: workflowId, state: "ASSESS_TASK" }],
    ["malformed UUID", { ...assessWorkflow, workflow_id: "not-a-uuid" }],
    ["noncanonical title", { ...assessWorkflow, title: "  Padded  " }],
    ["bad context", { ...assessWorkflow, context: { involves_multiple_steps: "maybe" } }],
    [
      "malformed created todo",
      {
        ...completedWorkflow,
        result: { created_todos: [{ ...todo, id: "nope" }] },
      },
    ],
  ])("rejects %s workflow bodies as invalid-data", async (_case, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    const pending = getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl });
    await expect(pending).rejects.toMatchObject({ kind: "invalid-data" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("birthday"),
    });
  });

  it("accepts an opaque state and normalizes an unknown view", async () => {
    const body = {
      ...assessWorkflow,
      state: "FUTURE_STATE",
      view: {
        type: "future_template",
        step_id: `${workflowId}:FUTURE_STATE`,
        server_only: true,
      },
    };
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual({
      ...body,
      view: {
        type: "unsupported",
        server_type: "future_template",
        step_id: `${workflowId}:FUTURE_STATE`,
      },
    });
  });

  it.each([
    ["empty state", { ...assessWorkflow, state: "" }],
    ["wrong step", { ...assessWorkflow, view: { ...assessView, step_id: "wrong" } }],
    ["missing view key", { ...assessWorkflow, view: { type: "future_template" } }],
    ["extra known key", { ...assessWorkflow, view: { ...assessView, extra: true } }],
    ["wrong choice id", {
      ...assessWorkflow,
      view: {
        ...assessView,
        actions: [{ id: "maybe", label: "Maybe" }, { id: "no", label: "No" }],
      },
    }],
  ])("rejects %s", async (_name, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));
    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it.each([
    [
      "breakdown with invalid bounds",
      {
        ...assessWorkflow,
        state: "COLLECT_TASKS",
        view: {
          type: "task_breakdown",
          step_id: `${workflowId}:COLLECT_TASKS`,
          title: "Break it down",
          min_titles: 10,
          max_titles: 2,
        },
      },
    ],
    [
      "review with noncanonical title",
      {
        ...assessWorkflow,
        state: "REVIEW",
        view: {
          type: "review",
          step_id: `${workflowId}:REVIEW`,
          title: "Review the plan",
          proposed_titles: [" Plan birthday party "],
        },
      },
    ],
    [
      "review with an extra key",
      {
        ...assessWorkflow,
        state: "REVIEW",
        view: {
          type: "review",
          step_id: `${workflowId}:REVIEW`,
          title: "Review the plan",
          proposed_titles: ["Plan birthday party"],
          extra: true,
        },
      },
    ],
  ])("rejects malformed %s view", async (_name, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it("accepts declined breakdown context structurally", async () => {
    const body = {
      ...assessWorkflow,
      state: "REVIEW",
      context: {
        involves_multiple_steps: true,
        proposed_todo_titles: ["Plan birthday party"],
      },
      view: {
        type: "review",
        step_id: `${workflowId}:REVIEW`,
        title: "Review your plan",
        proposed_titles: ["Plan birthday party"],
      },
    };
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));
    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(body);
  });

  it("maps workflow 401 to auth-required", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(401, { detail: "x" }));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toEqual(new TodoApiError("auth-required", "Please sign in again."));
  });

  it("maps workflow 409 to conflict without leaking", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(response(409, { detail: "Action is not valid here." }));

    const pending = advanceTodoWorkflow(
      workflowId,
      { action: "confirm" },
      { apiUrl, token: "tok", fetchImpl }
    );
    await expect(pending).rejects.toMatchObject({ kind: "conflict" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("not valid"),
    });
  });

  it("maps workflow 422 to the safe validation copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(422, { detail: "x" }));

    await expect(
      startTodoWorkflow("", { apiUrl, token: "tok", fetchImpl })
    ).rejects.toEqual(
      new TodoApiError("validation", "Check the plan details and try again.")
    );
  });

  it("maps workflow transport failures to unavailable", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("secret offline"));

    const pending = advanceTodoWorkflow(
      workflowId,
      { action: "cancel" },
      { apiUrl, token: "tok", fetchImpl }
    );
    await expect(pending).rejects.toMatchObject({ kind: "unavailable" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("secret"),
    });
  });
});

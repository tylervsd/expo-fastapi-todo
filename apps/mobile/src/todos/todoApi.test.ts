import {
  advanceTodoWorkflow,
  createTodo,
  deleteTodo,
  fetchMe,
  getTodoWorkflow,
  getWorkflowSuggestion,
  listTodoWorkflows,
  listTodos,
  login,
  logout,
  normalizeTodoTitle,
  setTodoCompleted,
  setTodoTitle,
  signup,
  startTodoWorkflow,
  suggestWorkflowTodos,
  TodoApiError,
  type WorkflowConflictCode,
  type WorkflowSuggestion,
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
  const requestId = "30bfb542-17f1-48a0-9fd8-3930379d5974";
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
    revision: 0,
    definition_version: 1,
    view_contract_version: 1,
    state: "ASSESS_TASK",
    title: "Plan birthday party",
    context: { involves_multiple_steps: null, proposed_todo_titles: [] },
    result: null,
    view: assessView,
  };
  const completedWorkflow = {
    workflow_id: workflowId,
    revision: 2,
    definition_version: 1,
    view_contract_version: 1,
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
  const startRequest = { request_id: requestId, title: "Plan birthday party" };

  it("starts a workflow with an exact request envelope", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(201, assessWorkflow));

    await expect(
      startTodoWorkflow(startRequest, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(assessWorkflow);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer tok" },
      body: JSON.stringify({ request_id: requestId, title: "Plan birthday party" }),
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

  const readySuggestion: WorkflowSuggestion = {
    contract_version: 1,
    workflow_id: workflowId,
    request_id: requestId,
    base_revision: 2,
    step_id: `${workflowId}:COLLECT_TASKS`,
    status: "ready",
    proposed_titles: ["Choose a date", "Invite guests"],
    error_code: null,
  };

  it("gets a strict saved suggestion contract", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, readySuggestion));

    await expect(
      getWorkflowSuggestion(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(readySuggestion);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows/${workflowId}/suggestions`, {
      method: "GET",
      headers: { Authorization: "Bearer tok" },
      signal: expect.any(AbortSignal),
    });
  });

  it("posts the exact suggestion request and accepts a fresh 201", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(201, readySuggestion));
    const request = {
      request_id: requestId,
      expected_revision: 2,
      step_id: `${workflowId}:COLLECT_TASKS`,
    };

    await expect(
      suggestWorkflowTodos(workflowId, request, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual(readySuggestion);
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows/${workflowId}/suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer tok" },
      body: JSON.stringify(request),
      signal: expect.any(AbortSignal),
    });
  });

  it("accepts a ready replay with 200 and rejects unknown suggestion contracts", async () => {
    const request = {
      request_id: requestId,
      expected_revision: 2,
      step_id: `${workflowId}:COLLECT_TASKS`,
    };
    const fetchImpl = jest
      .fn()
      .mockResolvedValueOnce(response(200, readySuggestion))
      .mockResolvedValueOnce(response(200, { ...readySuggestion, contract_version: 2 }));

    await expect(suggestWorkflowTodos(workflowId, request, { apiUrl, fetchImpl })).resolves.toEqual(
      readySuggestion,
    );
    await expect(suggestWorkflowTodos(workflowId, request, { apiUrl, fetchImpl })).rejects.toMatchObject({
      kind: "invalid-data",
    });
  });

  it.each([
    ["pending with titles", { ...readySuggestion, status: "pending", proposed_titles: ["Unexpected"] }],
    ["failed without error", { ...readySuggestion, status: "failed", proposed_titles: [], error_code: null }],
    ["extra key", { ...readySuggestion, extra: true }],
    ["one title", { ...readySuggestion, proposed_titles: ["Only one"] }],
    ["noncanonical title", { ...readySuggestion, proposed_titles: [" Choose", "Invite"] }],
  ])("rejects malformed %s suggestion response", async (_label, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));
    await expect(getWorkflowSuggestion(workflowId, { apiUrl, fetchImpl })).rejects.toMatchObject({
      kind: "invalid-data",
    });
  });

  it("maps typed provider failures without exposing server details", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      response(504, { detail: { code: "timeout", message: "secret provider body" } })
    );
    const pending = suggestWorkflowTodos(
      workflowId,
      {
        request_id: requestId,
        expected_revision: 2,
        step_id: `${workflowId}:COLLECT_TASKS`,
      },
      { apiUrl, fetchImpl },
    );
    await expect(pending).rejects.toMatchObject({ kind: "unavailable", suggestionCode: "timeout" });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("secret") });
  });

  it("uses the 35 second timeout only for suggestion POST", async () => {
    jest.useFakeTimers();
    try {
      const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
      const pending = suggestWorkflowTodos(
        workflowId,
        {
          request_id: requestId,
          expected_revision: 2,
          step_id: `${workflowId}:COLLECT_TASKS`,
        },
        { apiUrl, timeoutMs: 1, fetchImpl },
      );
      const rejection = expect(pending).rejects.toMatchObject({ kind: "unavailable" });
      await jest.advanceTimersByTimeAsync(1_000);
      expect(jest.getTimerCount()).toBeGreaterThan(0);
      await jest.advanceTimersByTimeAsync(34_000);
      await rejection;
    } finally {
      jest.useRealTimers();
    }
  });

  it.each([
    ["not found", 404, { detail: "hidden" }, "not-found"],
    ["in progress", 409, { detail: { code: "suggestion_in_progress", message: "hidden" } }, "conflict"],
  ])("maps suggestion %s safely", async (_label, status, body, kind) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(status, body));
    const pending = suggestWorkflowTodos(
      workflowId,
      { request_id: requestId, expected_revision: 2, step_id: `${workflowId}:COLLECT_TASKS` },
      { apiUrl, fetchImpl },
    );
    await expect(pending).rejects.toMatchObject({ kind });
    await expect(pending).rejects.not.toMatchObject({ message: expect.stringContaining("hidden") });
  });

  it.each([
    [401, "timeout"],
    [502, "timeout"],
    [503, "invalid_output"],
    [504, "provider_unavailable"],
  ])("does not trust a suggestion error code with the wrong HTTP status", async (status, code) => {
    const fetchImpl = jest.fn().mockResolvedValue(
      response(status, { detail: { code, message: "hidden" } }),
    );
    const pending = suggestWorkflowTodos(
      workflowId,
      { request_id: requestId, expected_revision: 2, step_id: `${workflowId}:COLLECT_TASKS` },
      { apiUrl, fetchImpl },
    );
    const expectedKind = status === 401 ? "auth-required" : "unavailable";
    await expect(pending).rejects.toMatchObject({ kind: expectedKind });
    await expect(pending).rejects.not.toMatchObject({ suggestionCode: code });
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

  it("advances with the exact nested action envelope", async () => {
    const actionRequestId = "f019129d-1936-4a5d-9de8-3da5aa01ccb1";
    const fetchImpl = jest.fn().mockResolvedValue(response(200, completedWorkflow));

    await expect(
      advanceTodoWorkflow(
        workflowId,
        {
          request_id: actionRequestId,
          expected_revision: 2,
          step_id: `${workflowId}:COLLECT_TASKS`,
          action: { action: "submit_tasks", titles: ["Invite guests", "Buy cake"] },
        },
        { apiUrl, token: "tok", fetchImpl }
      )
    ).resolves.toEqual(completedWorkflow);
    expect(JSON.parse(fetchImpl.mock.calls[0][1].body)).toEqual({
      request_id: actionRequestId,
      expected_revision: 2,
      step_id: `${workflowId}:COLLECT_TASKS`,
      action: { action: "submit_tasks", titles: ["Invite guests", "Buy cake"] },
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      `${apiUrl}/todo-workflows/${workflowId}/actions`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer tok" },
        body: expect.any(String),
        signal: expect.any(AbortSignal),
      }
    );
  });

  it("lists active workflows with an exact discovery request", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, { items: [assessWorkflow] }));

    await expect(listTodoWorkflows({ apiUrl, token: "tok", fetchImpl })).resolves.toEqual({
      items: [assessWorkflow],
    });
    expect(fetchImpl).toHaveBeenCalledWith(`${apiUrl}/todo-workflows?status=active`, {
      method: "GET",
      headers: { Authorization: "Bearer tok" },
      signal: expect.any(AbortSignal),
    });
  });

  it.each([
    ["missing items", {}],
    ["non-array items", { items: assessWorkflow }],
    ["malformed item", { items: [{ ...assessWorkflow, revision: "zero" }] }],
    ["extra envelope key", { items: [], extra: true }],
  ])("rejects %s discovery bodies as invalid-data", async (_case, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    const pending = listTodoWorkflows({ apiUrl, token: "tok", fetchImpl });
    await expect(pending).rejects.toMatchObject({ kind: "invalid-data" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("birthday"),
    });
  });

  it("relays caller cancellation on discovery GET", async () => {
    const controller = new AbortController();
    const fetchImpl = jest.fn(() => new Promise<Response>(() => undefined));
    const pending = listTodoWorkflows({
      apiUrl,
      token: "tok",
      signal: controller.signal,
      fetchImpl,
    });

    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
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

  it.each([
    ["missing revision", { ...assessWorkflow, revision: undefined }],
    ["missing definition version", { ...assessWorkflow, definition_version: undefined }],
    ["missing view contract version", { ...assessWorkflow, view_contract_version: undefined }],
  ])("rejects workflow bodies with %s as invalid-data", async (_case, body) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it.each([
    ["float revision", 1.5],
    ["string revision", "1"],
    ["negative revision", -1],
    ["exhausted-plus-one revision", 2147483648],
    ["boolean revision", true],
  ])("rejects %s as invalid-data", async (_name, revision) => {
    const fetchImpl = jest.fn().mockResolvedValue(response(200, { ...assessWorkflow, revision }));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it.each([
    ["zero view contract version", 0],
    ["string view contract version", "1"],
    ["float view contract version", 1.5],
  ])("rejects %s as invalid-data", async (_name, view_contract_version) => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(response(200, { ...assessWorkflow, view_contract_version }));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it("returns a metadata-only member for an unknown view contract", async () => {
    const body = {
      workflow_id: workflowId,
      revision: 4,
      definition_version: 1,
      view_contract_version: 2,
      state: "FUTURE_STATE",
      title: "Unknowable",
      context: { involves_multiple_steps: true, proposed_todo_titles: ["X"] },
      result: null,
      view: { type: "future", step_id: `${workflowId}:FUTURE_STATE` },
    };
    const fetchImpl = jest.fn().mockResolvedValue(response(200, body));

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).resolves.toEqual({
      workflow_id: workflowId,
      revision: 4,
      definition_version: 1,
      view_contract_version: 2,
      view: {
        type: "unsupported",
        server_type: "contract:2",
        step_id: `${workflowId}:unsupported-contract:2`,
      },
    });
  });

  it("rejects an unknown definition version under contract 1 as invalid-data", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      response(200, { ...assessWorkflow, definition_version: 2 })
    );

    await expect(
      getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toMatchObject({ kind: "invalid-data" });
  });

  it("accepts an opaque state and normalizes an unknown version-1 view", async () => {
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

  it("maps a missing workflow GET to safe not-found copy", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(response(404, { detail: "Todo workflow not found." }));

    const pending = getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl });
    await expect(pending).rejects.toMatchObject({ kind: "not-found" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("Todo workflow"),
    });
  });

  it("maps workflow 409 to conflict without leaking", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(response(409, { detail: "Action is not valid here." }));

    const pending = advanceTodoWorkflow(
      workflowId,
      {
        request_id: requestId,
        expected_revision: 0,
        step_id: `${workflowId}:ASSESS_TASK`,
        action: { action: "confirm" },
      },
      { apiUrl, token: "tok", fetchImpl }
    );
    await expect(pending).rejects.toMatchObject({ kind: "conflict" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("not valid"),
    });
  });

  const conflictCases: [WorkflowConflictCode, string][] = [
    ["stale_step", "This plan changed. Reload it and try again."],
    ["request_id_reused", "This request ID was already used with different details."],
    ["invalid_action", "Action is not valid for the current workflow state."],
    ["terminal_workflow", "Todo workflow is already terminal."],
    ["unsupported_workflow_definition", "This plan uses an unsupported workflow definition."],
    ["revision_exhausted", "This plan has reached its revision limit."],
  ];
  it.each(conflictCases)("maps conflict code %s to its typed copy", async (code, message) => {
    const fetchImpl = jest.fn().mockResolvedValue(
      response(409, { detail: { code, message: `server says ${code} loudly` } })
    );

    const pending = advanceTodoWorkflow(
      workflowId,
      {
        request_id: requestId,
        expected_revision: 0,
        step_id: `${workflowId}:ASSESS_TASK`,
        action: { action: "confirm" },
      },
      { apiUrl, token: "tok", fetchImpl }
    );
    await expect(pending).rejects.toMatchObject({ kind: "conflict", conflictCode: code });
    await expect(pending).rejects.toEqual(new TodoApiError("conflict", message, code));
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("loudly"),
    });
  });

  it("maps an unknown conflict code to the generic conflict copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      response(409, { detail: { code: "future_code", message: "secret future" } })
    );

    const pending = getTodoWorkflow(workflowId, { apiUrl, token: "tok", fetchImpl });
    await expect(pending).rejects.toMatchObject({ kind: "conflict" });
    const error = await pending.catch((thrown: unknown) => thrown);
    expect(error).toBeInstanceOf(TodoApiError);
    expect((error as TodoApiError).conflictCode).toBeUndefined();
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("secret"),
    });
  });

  it("maps workflow 422 to the safe validation copy", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(response(422, { detail: "x" }));

    await expect(
      startTodoWorkflow(startRequest, { apiUrl, token: "tok", fetchImpl })
    ).rejects.toEqual(
      new TodoApiError("validation", "Check the plan details and try again.")
    );
  });

  it("maps workflow transport failures to unavailable", async () => {
    const fetchImpl = jest.fn().mockRejectedValue(new Error("secret offline"));

    const pending = advanceTodoWorkflow(
      workflowId,
      {
        request_id: requestId,
        expected_revision: 0,
        step_id: `${workflowId}:ASSESS_TASK`,
        action: { action: "cancel" },
      },
      { apiUrl, token: "tok", fetchImpl }
    );
    await expect(pending).rejects.toMatchObject({ kind: "unavailable" });
    await expect(pending).rejects.not.toMatchObject({
      message: expect.stringContaining("secret"),
    });
  });
});

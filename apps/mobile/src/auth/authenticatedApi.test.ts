import { TodoApiError, type Todo, type TodoWorkflow } from "../todos/todoApi";
import { createAuthenticatedApi, type TodoTransport } from "./authenticatedApi";

const row = (id: string): Todo => ({ id, title: "Row", completed: false });

const makeTransport = (): TodoTransport & {
  [K in keyof TodoTransport]: jest.Mock;
} => ({
  listTodos: jest.fn(async () => [row("1")]),
  createTodo: jest.fn(async () => row("2")),
  setTodoTitle: jest.fn(async () => row("1")),
  setTodoCompleted: jest.fn(async () => row("1")),
  deleteTodo: jest.fn(async () => undefined),
  startTodoWorkflow: jest.fn(),
  getTodoWorkflow: jest.fn(),
  advanceTodoWorkflow: jest.fn(),
});

it("injects the token into every call", async () => {
  const transport = makeTransport();
  const api = createAuthenticatedApi(() => "tok", jest.fn(), transport);

  await api.list({ signal: new AbortController().signal });
  await api.create("Hi");
  await api.rename("1", "New");
  await api.setCompleted("1", true);
  await api.remove("1");

  expect(transport.listTodos).toHaveBeenCalledWith({
    signal: expect.any(AbortSignal),
    token: "tok",
  });
  expect(transport.createTodo).toHaveBeenCalledWith("Hi", { token: "tok" });
  expect(transport.setTodoTitle).toHaveBeenCalledWith("1", "New", { token: "tok" });
  expect(transport.setTodoCompleted).toHaveBeenCalledWith("1", true, { token: "tok" });
  expect(transport.deleteTodo).toHaveBeenCalledWith("1", { token: "tok" });
});

it("signs out and rethrows on auth-required", async () => {
  const transport = makeTransport();
  const failure = new TodoApiError("auth-required", "Please sign in again.");
  transport.listTodos.mockRejectedValueOnce(failure);
  const onAuthRequired = jest.fn();
  const api = createAuthenticatedApi(() => "tok", onAuthRequired, transport);

  await expect(api.list({ signal: new AbortController().signal })).rejects.toBe(failure);
  expect(onAuthRequired).toHaveBeenCalledTimes(1);
});

it("does not sign out for other errors", async () => {
  const transport = makeTransport();
  transport.createTodo.mockRejectedValueOnce(new Error("boom"));
  const onAuthRequired = jest.fn();
  const api = createAuthenticatedApi(() => "tok", onAuthRequired, transport);

  await expect(api.create("Hi")).rejects.toThrow("boom");
  expect(onAuthRequired).not.toHaveBeenCalled();
});

it("sends no token when signed out", async () => {
  const transport = makeTransport();
  const api = createAuthenticatedApi(() => null, jest.fn(), transport);

  await api.create("Hi");

  expect(transport.createTodo).toHaveBeenCalledWith("Hi", {});
});

describe("workflow calls", () => {
  const workflowId = "6fc33b84-16a8-4d8e-ae94-fc50bb457d72";
  const assessWorkflow: TodoWorkflow = {
    workflow_id: workflowId,
    state: "ASSESS_TASK",
    title: "Plan birthday party",
    context: { involves_multiple_steps: null, proposed_todo_titles: [] },
    result: null,
    view: {
      type: "yes_no",
      step_id: `${workflowId}:ASSESS_TASK`,
      title: "Plan birthday party",
      question: "Does this task involve multiple steps?",
      actions: [
        { id: "yes", label: "Yes" },
        { id: "no", label: "No" },
      ],
    },
  };

  const makeWorkflowTransport = () => ({
    ...makeTransport(),
    startTodoWorkflow: jest.fn(async () => assessWorkflow),
    getTodoWorkflow: jest.fn(async () => assessWorkflow),
    advanceTodoWorkflow: jest.fn(async () => assessWorkflow),
  });

  it("sends the current token on all three workflow calls", async () => {
    const transport = makeWorkflowTransport();
    const api = createAuthenticatedApi(() => "tok", jest.fn(), transport);

    await api.startWorkflow("Plan birthday party");
    await api.getWorkflow(workflowId, { signal: new AbortController().signal });
    await api.advanceWorkflow(workflowId, { action: "confirm" });

    expect(transport.startTodoWorkflow).toHaveBeenCalledWith("Plan birthday party", {
      token: "tok",
    });
    expect(transport.getTodoWorkflow).toHaveBeenCalledWith(workflowId, {
      signal: expect.any(AbortSignal),
      token: "tok",
    });
    expect(transport.advanceTodoWorkflow).toHaveBeenCalledWith(
      workflowId,
      { action: "confirm" },
      { token: "tok" }
    );
  });

  it("captures the token once and reports it on later auth-required", async () => {
    const transport = makeWorkflowTransport();
    let current: string | null = "old";
    const getToken = jest.fn(() => current);
    const pending = Promise.withResolvers<TodoWorkflow>();
    transport.getTodoWorkflow.mockReturnValueOnce(pending.promise);
    const onAuthRequired = jest.fn();
    const api = createAuthenticatedApi(getToken, onAuthRequired, transport);

    const call = api.getWorkflow(workflowId, { signal: new AbortController().signal });
    expect(getToken).toHaveBeenCalledTimes(1);
    current = "new";
    pending.reject(new TodoApiError("auth-required", "Please sign in again."));

    await expect(call).rejects.toMatchObject({ kind: "auth-required" });
    expect(onAuthRequired).toHaveBeenCalledTimes(1);
    expect(onAuthRequired).toHaveBeenCalledWith("old");
  });

  it.each([
    ["validation", new TodoApiError("validation", "Check the plan details and try again.")],
    ["conflict", new TodoApiError("conflict", "The plan changed. Reload to continue.")],
    ["unavailable", new TodoApiError("unavailable", "Could not update the plan.")],
  ])("does not invoke the callback for %s errors", async (_kind, failure) => {
    const transport = makeWorkflowTransport();
    transport.advanceTodoWorkflow.mockRejectedValueOnce(failure);
    const onAuthRequired = jest.fn();
    const api = createAuthenticatedApi(() => "tok", onAuthRequired, transport);

    await expect(
      api.advanceWorkflow(workflowId, { action: "cancel" })
    ).rejects.toBe(failure);
    expect(onAuthRequired).not.toHaveBeenCalled();
  });
});

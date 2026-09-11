import {
  TodoApiError,
  type Todo,
  type TodoWorkflow,
  type WorkflowSuggestion,
} from "../todos/todoApi";
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
  getWorkflowSuggestion: jest.fn(),
  suggestWorkflowTodos: jest.fn(),
  listTodoWorkflows: jest.fn(),
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
  const startRequest = {
    request_id: "30bfb542-17f1-48a0-9fd8-3930379d5974",
    title: "Plan birthday party",
  };
  const actionRequest = {
    request_id: "f019129d-1936-4a5d-9de8-3da5aa01ccb1",
    expected_revision: 0,
    step_id: `${workflowId}:ASSESS_TASK`,
    action: { action: "confirm" as const },
  };
  const assessWorkflow: TodoWorkflow = {
    workflow_id: workflowId,
    revision: 0,
    definition_version: 1,
    view_contract_version: 1,
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
    startTodoWorkflow: jest.fn(async (): Promise<TodoWorkflow> => assessWorkflow),
    getTodoWorkflow: jest.fn(async (): Promise<TodoWorkflow> => assessWorkflow),
    advanceTodoWorkflow: jest.fn(async (): Promise<TodoWorkflow> => assessWorkflow),
    getWorkflowSuggestion: jest.fn(async (): Promise<WorkflowSuggestion> => ({
      contract_version: 1,
      workflow_id: workflowId,
      request_id: startRequest.request_id,
      base_revision: 0,
      step_id: `${workflowId}:ASSESS_TASK`,
      status: "pending",
      proposed_titles: [],
      error_code: null,
    })),
    suggestWorkflowTodos: jest.fn(async (): Promise<WorkflowSuggestion> => ({
      contract_version: 1,
      workflow_id: workflowId,
      request_id: startRequest.request_id,
      base_revision: 0,
      step_id: `${workflowId}:ASSESS_TASK`,
      status: "pending",
      proposed_titles: [],
      error_code: null,
    })),
    listTodoWorkflows: jest.fn(async (): Promise<{ items: TodoWorkflow[] }> => ({ items: [] })),
  });

  it("sends the current token on all workflow calls", async () => {
    const transport = makeWorkflowTransport();
    const api = createAuthenticatedApi(() => "tok", jest.fn(), transport);
    const listSignal = new AbortController().signal;

    await api.startWorkflow(startRequest);
    await api.getWorkflow(workflowId, { signal: new AbortController().signal });
    await api.advanceWorkflow(workflowId, actionRequest);
    await api.getSuggestion(workflowId, { signal: new AbortController().signal });
    await api.suggestWorkflow(workflowId, {
      request_id: startRequest.request_id,
      expected_revision: 0,
      step_id: `${workflowId}:ASSESS_TASK`,
    });
    await api.listWorkflows({ signal: listSignal });

    expect(transport.startTodoWorkflow).toHaveBeenCalledWith(startRequest, {
      token: "tok",
    });
    expect(transport.getTodoWorkflow).toHaveBeenCalledWith(workflowId, {
      signal: expect.any(AbortSignal),
      token: "tok",
    });
    expect(transport.advanceTodoWorkflow).toHaveBeenCalledWith(
      workflowId,
      actionRequest,
      { token: "tok" }
    );
    expect(transport.getWorkflowSuggestion).toHaveBeenCalledWith(workflowId, {
      signal: expect.any(AbortSignal),
      token: "tok",
    });
    expect(transport.suggestWorkflowTodos).toHaveBeenCalledWith(
      workflowId,
      {
        request_id: startRequest.request_id,
        expected_revision: 0,
        step_id: `${workflowId}:ASSESS_TASK`,
      },
      { token: "tok" },
    );
    expect(transport.listTodoWorkflows).toHaveBeenCalledWith({
      signal: listSignal,
      token: "tok",
    });
  });

  it("passes an exact clarification through with the bearer header", async () => {
    const transport = makeWorkflowTransport();
    const api = createAuthenticatedApi(() => "tok", jest.fn(), transport);
    const request = {
      request_id: startRequest.request_id,
      expected_revision: 0,
      step_id: `${workflowId}:ASSESS_TASK`,
      clarification: { field: "budget" as const, value: "under $50" },
    };

    await api.suggestWorkflow(workflowId, request);

    expect(transport.suggestWorkflowTodos).toHaveBeenCalledWith(workflowId, request, {
      token: "tok",
    });
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
      api.advanceWorkflow(workflowId, actionRequest)
    ).rejects.toBe(failure);
    expect(onAuthRequired).not.toHaveBeenCalled();
  });
});

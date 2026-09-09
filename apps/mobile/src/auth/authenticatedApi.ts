import {
  advanceTodoWorkflow,
  createTodo,
  deleteTodo,
  getTodoWorkflow,
  listTodoWorkflows,
  listTodos,
  setTodoCompleted,
  setTodoTitle,
  startTodoWorkflow,
  TodoApiError,
  type TodoRequestOptions,
  type TodoWorkflow,
  type WorkflowActionRequest,
  type WorkflowStartRequest,
} from "../todos/todoApi";
import type { TodoScreenApi } from "../TodoScreen";

export type TodoTransport = {
  listTodos: typeof listTodos;
  createTodo: typeof createTodo;
  setTodoTitle: typeof setTodoTitle;
  setTodoCompleted: typeof setTodoCompleted;
  deleteTodo: typeof deleteTodo;
  startTodoWorkflow: typeof startTodoWorkflow;
  getTodoWorkflow: typeof getTodoWorkflow;
  advanceTodoWorkflow: typeof advanceTodoWorkflow;
  listTodoWorkflows: typeof listTodoWorkflows;
};

export const defaultTransport: TodoTransport = {
  listTodos,
  createTodo,
  setTodoTitle,
  setTodoCompleted,
  deleteTodo,
  startTodoWorkflow,
  getTodoWorkflow,
  advanceTodoWorkflow,
  listTodoWorkflows,
};

export type TodoWorkflowScreenApi = {
  startWorkflow: (request: WorkflowStartRequest) => Promise<TodoWorkflow>;
  getWorkflow: (
    id: string,
    options: { signal: AbortSignal }
  ) => Promise<TodoWorkflow>;
  advanceWorkflow: (id: string, request: WorkflowActionRequest) => Promise<TodoWorkflow>;
  listWorkflows: (options: { signal: AbortSignal }) => Promise<{ items: TodoWorkflow[] }>;
};

export type AuthenticatedApi = TodoScreenApi & TodoWorkflowScreenApi;

export function createAuthenticatedApi(
  getToken: () => string | null,
  onAuthRequired: (requestToken: string | null) => void,
  transport: TodoTransport = defaultTransport,
): AuthenticatedApi {
  const guard = async <T>(
    run: (requestToken: string | null) => Promise<T>
  ): Promise<T> => {
    const requestToken = getToken();
    try {
      return await run(requestToken);
    } catch (error) {
      if (error instanceof TodoApiError && error.kind === "auth-required") {
        onAuthRequired(requestToken);
      }
      throw error;
    }
  };
  const opts = (requestToken: string | null): TodoRequestOptions =>
    requestToken === null ? {} : { token: requestToken };
  return {
    list: (options) =>
      guard((requestToken) =>
        transport.listTodos({ ...options, ...opts(requestToken) })
      ),
    create: (title) =>
      guard((requestToken) => transport.createTodo(title, opts(requestToken))),
    rename: (id, title) =>
      guard((requestToken) => transport.setTodoTitle(id, title, opts(requestToken))),
    setCompleted: (id, completed) =>
      guard((requestToken) =>
        transport.setTodoCompleted(id, completed, opts(requestToken))
      ),
    remove: (id) => guard((requestToken) => transport.deleteTodo(id, opts(requestToken))),
    startWorkflow: (request) =>
      guard((requestToken) => transport.startTodoWorkflow(request, opts(requestToken))),
    getWorkflow: (id, options) =>
      guard((requestToken) =>
        transport.getTodoWorkflow(id, { ...options, ...opts(requestToken) })
      ),
    advanceWorkflow: (id, request) =>
      guard((requestToken) =>
        transport.advanceTodoWorkflow(id, request, opts(requestToken))
      ),
    listWorkflows: (options) =>
      guard((requestToken) =>
        transport.listTodoWorkflows({ ...options, ...opts(requestToken) })
      ),
  };
}

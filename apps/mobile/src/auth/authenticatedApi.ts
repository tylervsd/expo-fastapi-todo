import {
  createTodo,
  deleteTodo,
  listTodos,
  setTodoCompleted,
  setTodoTitle,
  TodoApiError,
  type TodoRequestOptions,
} from "../todos/todoApi";
import type { TodoScreenApi } from "../TodoScreen";

export type TodoTransport = {
  listTodos: typeof listTodos;
  createTodo: typeof createTodo;
  setTodoTitle: typeof setTodoTitle;
  setTodoCompleted: typeof setTodoCompleted;
  deleteTodo: typeof deleteTodo;
};

export const defaultTransport: TodoTransport = {
  listTodos,
  createTodo,
  setTodoTitle,
  setTodoCompleted,
  deleteTodo,
};

export function createAuthenticatedApi(
  getToken: () => string | null,
  onAuthRequired: () => void,
  transport: TodoTransport = defaultTransport,
): TodoScreenApi {
  const opts = (): TodoRequestOptions => {
    const token = getToken();
    return token === null ? {} : { token };
  };
  const guard = async <T>(run: () => Promise<T>): Promise<T> => {
    try {
      return await run();
    } catch (error) {
      if (error instanceof TodoApiError && error.kind === "auth-required") {
        onAuthRequired();
      }
      throw error;
    }
  };
  return {
    list: (options) => guard(() => transport.listTodos({ ...options, ...opts() })),
    create: (title) => guard(() => transport.createTodo(title, opts())),
    rename: (id, title) => guard(() => transport.setTodoTitle(id, title, opts())),
    setCompleted: (id, completed) =>
      guard(() => transport.setTodoCompleted(id, completed, opts())),
    remove: (id) => guard(() => transport.deleteTodo(id, opts())),
  };
}
